# Review: agents that check every build against its real photo

The car machine builds each of the UK's most-licensed cars and vans in 3D, and
each build is shown beside a real photo of that vehicle. This folder is the
run around it: build the fleet, picture it, have agents name each photo's
colour and side, judge every build beside its photo, replace weak photos, and
check that every record agrees before anything is published.

Everything reads and writes one data folder, `F1K_HOME` (targets.json,
results.jsonl, car_photos/, the labels and verdicts), and the car machine's
own `GLBMACHINE_HOME`. Run every tool from the repository root:

    export F1K_HOME=/path/to/f1k GLBMACHINE_HOME=/path/to/gmhome
    python3 pipeline/realcar/review/check.py

## The loop

1. **Build**: `fleet.py build --workers 3` (again after fixes: `fleet.py redo`, which also takes everything on the rebuild queue).
   Picture each build as it lands: three of `node hero.mjs $F1K_HOME/pending $F1K_HOME/hero_png 0/3` (1/3, 2/3).
2. **Name colours and sides**: `brief.py colour NAME @keys.txt` and `brief.py side NAME @keys.txt`, one agent per batch
   (about 240 photos each). A colour or side that changes queues a rebuild by itself.
3. **Rebuild what changed**: `fleet.py redo`.
4. **Review**: `brief.py build NAME @keys.txt` per batch of about 120 builds, one agent each. A replaced photo
   brings its own colour and side and queues its rebuild by itself.
5. **Roofs**: `brief.py roof NAME @keys.txt`, one agent per batch of about 240: the roof alone against the photo's (the general review missed about one in twelve). A roof that is not the photo's is rebuilt so by itself: go to 3, then 4 for those.
6. **Gate**: `check.py`. It must say "all clear" before the report is published. If it lists rebuilds, go to 3;
   if it lists verdicts, review those builds (4); if it lists a batch that missed a checked item, give that
   batch's sheets to a new agent.
7. `webp.py` makes the small pictures for the report; `webp.py --prune` removes the full ones once every review is done.

`brief.py` makes a batch's sheets and fills in its instructions from `prompts/`: never edit a prompt by hand for
one batch. Change the prompt file, and every batch after gets the change.

## How the agents are kept right

**Checked items (gold.json).** About 50 answers checked by hand: builds known to be ok or bad and why, photos whose
colour and side are known. `brief.py` puts one among the items of every sheet, unmarked. A wrong answer on one is
refused on the spot with the right answer and the reason, and the agent is told to look again at the rest of that
sheet: it learns the rule from its own mistake while it works. Every answer is logged (`gold_score.jsonl`), and
`check.py` names any batch that missed one, so its sheets are looked at again.

A checked answer only holds for what was checked: a build's for that build (its `built_at`), a photo's for that
photo (its fingerprint). After a rebuild or a new photo the item drops out until it is checked again:

    python3 pipeline/realcar/review/gold.py list                       # which still hold
    python3 pipeline/realcar/review/gold.py add build KEY bad "body" "why"
    python3 pipeline/realcar/review/gold.py add side KEY left "why"
    python3 pipeline/realcar/review/gold.py add paint KEY white "why"
    python3 pipeline/realcar/review/gold.py add roof KEY same|body|FAMILY "why"
    python3 pipeline/realcar/review/gold.py withdraw build KEY "why"      # an answer found wrong or arguable
    python3 pipeline/realcar/review/gold.py resolved BATCH "how"          # its sheets looked at again

Only add what you have looked at yourself, at full size, and are sure of; leave out anything a careful reviewer
could call either way.

**Answers that cannot be right are refused**, each with the reason, before anything is written:

| Mistake made in the run of October 2026 | What stops it now |
|---|---|
| A key mistyped, a verdict on a build that failed | `verdict` checks the key has a build |
| "ok" with faults, "bad" with none, no note | `verdict` refuses it |
| "photo" as the fault when no photo was replaced | `verdict` checks the photo was replaced after the build |
| A modern MINI photo on the classic Mini builds | `choose` refuses a photo whose years are not the build's generation |
| A wheel close-up, an interior, a car cut off chosen as the photo | `choose` refuses a candidate with no whole car in it |
| A new photo left in the old photo's colour (the 300C) | `choose` takes the colour and side with it, reads the paint and queues the rebuild |
| A side or colour named wrong, never redone | a side or colour fault puts the key back on the label list; `check.py` shows it |
| A side label convention misread | checked photos on every side sheet; a wrong one refuses the sheet |
| Verdicts left on builds that were rebuilt since | every verdict records the build and photo it judged; `check.py` finds stale ones |
| A results line cut short by a full disk stopping the next run | whole-line writes; the reader reads past a bad line; the runner stops cleanly on a low disk |
| Full pictures deleted while agents were still opening them | `webp.py` keeps them unless told `--prune` |
| A checked answer that was wrong (the 3-door Fiesta's 5-door photo called fine) taught agents the wrong rule | `gold.py withdraw` takes it back with the reason; its answers stop counting; only what you are sure of is checked |
| An answer charged to every batch whose sheets carried the item | each command carries `F1K_BATCH` (brief.py puts it in the prompt): the batch that answered is charged |
| Agents could find the checked items from the key lists beside the sheets | the manifest and key lists are kept in `review_runs/`, away from the sheets |
| Whole cars refused as cut off (a row of parked cars behind them touched the frame), so agents overrode the guard | cut off means the car meets the frame along 80% of its height |
| A 5-door stand-in for a 3-door car passed as a small difference | the door count is body, in the fault list and the past mistakes |
| A donor's black roof on a one-colour car, or a photo's white roof missing | the fault `roof` with `--roof body` or `--roof FAMILY`: the rebuild paints the roof so |
| A batch that missed one stayed on the gate after its sheets were looked at again | `gold.py resolved BATCH "how"` |
| The roof command failed on every call (a name in `main()` hid the function); its tests had called the function only | every command the prompts give is tested as typed (`test_the_commands_as_the_agents_type_them`) |
| The runner, moved into the repo, dropped the run's choice of models (any licence): 36 vehicles came out of other models | `fleet.py licence any|commercial` keeps it in `run.json`; the gate stops a build that left it out |
| Roofs left in a donor's or the model's colour, and photos' two-tone roofs missing (about one in twelve builds) | the roof pass; the machine paints the roof as the photo's |
| The roof rule's paint on windscreens and A-pillars (about 18 builds in round 3): a windscreen's black band far from its glass's corners, a donor's roof running down the pillars, a roof-named material painted whole | the rule measures to the glass's surface, paints nothing ahead of the roof's front edge, and no material whole; pinned in `test_rules.py` |
| A roof the machine cannot make (a Smart's frame, an ID Buzz's white upper half) asked for again on every review, so rebuilt again and again | a roof asked for again on a build already made asking for it goes to `roof_limits.json`, not the queue |
| Checked answers made from a sheet's thumbnail (an MG HS and a Swift called ok, a Kamiq Monte Carlo's black roof missed) | withdrawn; an answer is checked on the full-size photo and build, or not added |
| A roof answer corrected to "same" on the same build left its label, its rebuild and its limit behind (three in round 4) | `take_back_roof`: the later "same", from the same kind of pass, undoes all three; a verdict that leaves the roof out does not undo the roof pass's |
| Pale and earthy paints built in a family's far darker or brighter paint (a pale sage as a Defender's green, a terracotta as crimson) | the sage, olive, copper and aqua families; the colour prompt asks for the family closest in lightness too |

The machine's own rules that went wrong are pinned by `pipeline/realcar/test_rules.py` ("black" is no paint name,
"carpaint.198" no inside, "M Sport Touring" an estate, a wheel in the paint's colour never painted, people
carriers and twins), and this folder's tools by `test_review.py`:

    python3 -m pytest pipeline/realcar/test_rules.py pipeline/realcar/review/test_review.py -q

## Files

| File | What it does |
|---|---|
| `paths.py` | the data folder, whole-file and whole-line writes, the rebuild queue |
| `fleet.py` | builds the targets through the car machine, one results line each |
| `hero.mjs`, `hero_settings.json`, `qa_glb.mjs` | the studio picture of each build; the shape check |
| `webp.py` | small pictures for the report |
| `photo_paint.py` | each photo's paint colour (and the outline guess at its side) |
| `paint_label.py`, `view_label.py` | colours and sides named by eye |
| `web_photo.py` | judging and replacing photos |
| `build_review.py` | judging builds |
| `gold.py`, `gold.json` | the checked answers and each batch's score |
| `brief.py` | a batch's sheets and instructions |
| `check.py` | the gate before publishing |
| `prompts/` | the agents' instructions |
