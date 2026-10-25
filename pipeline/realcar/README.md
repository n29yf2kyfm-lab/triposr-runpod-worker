# The GLB machine

Ask for a car in plain words and get back an interactive GLB: every door, the
bonnet and the tailgate open (glTF animation clips), the glass is clear, the
model's cabin is kept, and a generic engine bay and exhaust sit under it,
painted the colour asked for. Python (numpy, scipy, Pillow) and Node; **no
Blender**, no GPU. ExpertCarCheck's own software: see `LICENSE` and, for every
component and the car models' licences, `THIRD_PARTY.md`.

## Install and run

```
pip install -r pipeline/realcar/requirements.txt
python3 pipeline/realcar/glbmachine.py setup          # npm install + work folder (~/.glbmachine)
python3 pipeline/realcar/glbmachine.py make "Nissan Micra 2004 red"
python3 pipeline/realcar/glbmachine.py make "Ford Fiesta 2012 blue" --no-sheet
python3 pipeline/realcar/glbmachine.py batch --top 20 --workers 3
python3 pipeline/realcar/glbmachine.py serve --port 8080
```

Or as one image (Python, Node 22, Chromium):

```
docker build -f pipeline/realcar/Dockerfile -t glbmachine .
docker run -p 8080:8080 -v glbdata:/data -e GLBMACHINE_KEYS=key1,key2 glbmachine
docker run --rm -v glbdata:/data glbmachine make "Toyota Yaris 2003 silver"
```

On any rented server with Docker, one command builds and starts it, restarts it
after a reboot and keeps the cars on a volume:

```
GLBMACHINE_KEYS=key-a,key-b docker compose -f pipeline/realcar/docker-compose.yml up -d
```

Customers need nothing installed: they call the API with their key. Put
HTTPS in front before they do.

Commercial only by default: no CC BY-NC model is used, and a car the
catalogue has only under CC BY-NC is made as a stand-in from one that may be
sold; the report names the model left out (`noncommercial_left_out`) and
says `"licence_mode": "commercial only"`. A demo may allow them per car
(`--allow-noncommercial`, or `"noncommercial": true` in the API request) or
for the whole server (`GLBMACHINE_COMMERCIAL_ONLY=0`). Of the UK's 40 best
sellers, only the Ford Fiesta has no commercial model.

The web API (`serve`): `POST /v1/cars {"request": "...", "spec": "...",
"sheet": false, "noncommercial": false}` answers with an id; `GET /v1/cars/ID` gives the status and
the report; `GET /v1/cars/ID/car.glb` and `/sheet.jpg` give the files;
`GET /v1/cars` lists the last 40 cars and `GET /v1/catalogue` every make,
model and year the catalogue has. With `GLBMACHINE_KEYS` set, each call
needs `Authorization: Bearer KEY`, which is where licence keys plug in.

## The Maker: the program in one page

`glbmachine serve`, then open the machine's address (`http://localhost:8080`).
The page that opens is the whole program:

1. **Make, Model**: type them; the lists offer what the catalogue has and
   the line under them gives its years.
2. **Year or plate**: `2012`, or a UK plate, `12` (March 2012) or `62`
   (September 2012).
3. **Spec** (optional): as a car check gives it. A badge the catalogue has
   as its own model picks that model (`GTI` with a Golf, `GR` with a
   Yaris, `Type R` with a Civic). A trim name (`ST-Line`, `R-Line`,
   `M Sport`) or an engine keeps the standard body, and the report says
   so. Doors (`5dr`) and body (`hatchback`) in it count too.
4. **Doors** and **Colour**: the DVLA colour names.
5. **Build GLB**: a clock runs against the minute, from asking to the file.
   Catalogue cars take 5-20 s. A request has 50 s
   (`GLBMACHINE_DEADLINE_S`): no other model is tried, and no stand-in photo
   waited for, that would not fit in it. The four-view picture, when ticked,
   is drawn after the car is handed over, and its button appears when it is
   ready.

The car then opens in 3D with every door, the bonnet and the tailgate open:
- drag to turn it, the wheel to zoom, and go all the way round, underneath
  too;
- **Doors**, **Bonnet**, **Tailgate** and **Open all** shut and open them;
- **Spin** turns it on its own;
- **Flip** turns it over to show the floor, the engine from below and the
  exhaust;
- **Picture** saves the view as a PNG;
- **Download GLB** gives the file for the app.

Beside the car is what was built: the catalogue model and how it matched
the year, what opens, what is missing, the paint, the model's credit and
licence (with whether commercial use is allowed), and the time each step
took. **Fix a part in Studio** opens the same car in GLB Studio. **Recent**
lists every car built, so you can open any of them again.

## Under a minute, every request

A request has 50 s to its file (`GLBMACHINE_DEADLINE_S`):
- **No retry past the deadline.** The machine starts another model only when another try, about as long as the last one, would still finish inside it.
- **Photo search is cut short.** A stand-in waits for its photo search only while a rebuild with the photo would still fit. A search still running carries on, and its photo is used the next time.
- **The sheet comes after.** The car is handed over as soon as it is built. A four-view sheet, when asked for, is drawn afterwards: the API marks the car `done`, then `sheet_status` goes from `drawing` to `done`, and the Maker shows the sheet's button when it is ready. Sheets are drawn on a thread of their own, so a car waiting in the queue doesn't also wait for another car's sheet. A sheet cut short by a restart reads `failed`, not `drawing` for ever.
- **A known photo goes in first time.** A stand-in whose side photo is already known, from the standby library or an earlier search, gets its roofline in its first build, not in a second build that the time may not allow.

**The rig cache.** Every model's rig is kept in `$GLBMACHINE_HOME/rigs/<model>/<2|4>`. Each server job builds in a fresh folder, and before the cache it downloaded and rigged its model again every time. With the cache, a model rigged once is only finished (finished, checked and compressed) for every request after.

**Rigging ahead of time.** `glbmachine warm --top N`, or `--all`, rigs models before anyone asks. `GLBMACHINE_WARM` does the same in the background when the server starts; the compose file sets 100. `--all` covers the 782 models the server may sell: about 10 GB as published, more once decoded.

**Faster steps.** Two changes made the steps faster without changing a byte of their output:
- the file reader no longer copies the whole buffer to read data the finisher has added;
- the rigger and finisher sort vertices as one packed number, not rows of three.

The rigger also tests each material's name once, not once per triangle. On the largest model tested, the 2021 Land Rover Defender, the rig went from 37.8 to 19.5 s and the finish from 35.7 to 14.4 s. Rig output was checked byte-identical on three models, and finish output on four.

Time to file for 14 requests, as the server runs them, 2026-10-19 (one process, no check sheet, 2 CPU cores shared):

| | slowest | median | over a minute |
| --- | --- | --- | --- |
| Before | 95.8 s (G63 stand-in), 85.9 s (Defender) | 12.4 s | 2 |
| Cold: fresh folder, empty rig cache | 40.8 s (Defender) | 10.2 s | 0 |
| Warm: fresh folder, model rigged before | 19.0 s (Defender) | 5.9 s | 0 |

The minute is from the start of the build. A request waiting in the queue behind others adds its wait, so a busy server needs more `GLBMACHINE_WORKERS`: about one per CPU core.

## A car as a page: `--page`

`glbmachine make "Peugeot 307 2001 blue" --page DIR` builds the car with no check sheet, unless `--sheet` is given. It then writes it as a page anyone can open: `DIR/index.html` plus `car1.json` … `carN.json` (`page.py`, about 0.1 s).

The page is the machine's own viewer:
- spin, zoom, and flip the car over;
- open each part, or everything at once;
- the Finish Lab: wheels, calipers and body in chrome, gloss, satin, matt, brushed or candy, in any colour.

It is filled in from the build's report:
- the request and how it was read;
- the time to the file, what opens, the paint and the model used;
- the file's size and validator result;
- the machine's own notes (parts not opening, a stand-in, a trim not matched);
- the model's credit and licence.

The GLB travels as base64 JSON parts of 15 MB at most, so the folder can be published where only data files are served. A request for a model rigged before took 4.5 s from asking to a finished page.

## The parts bench: catalogue, callouts, explode, cut-away, procedures

Every car page carries a parts bench beside the 3D view, the kind of thing a
3D technical-documentation suite sells (an interactive parts catalogue and
animated procedures), built here from scratch for a car:

| Bench | What it does |
| --- | --- |
| Parts list | Every named part of the file, numbered and grouped: body and openings, wheels, the engine bay's 54 parts by name (battery, radiator top hose, turbocharger ...), under the car, the cabin. A click in the list picks the part on the car; a click on the car picks it in the list; shift adds to the pick. ◎ looks at it. |
| Callouts | Numbered labels over the car, each on a leader to its part, as a parts drawing numbers them. They follow the car as it turns. Focus a group (Engine bay) and the callouts are its parts. A callout is a button. |
| X-ray, Isolate | X-ray ghosts everything but the pick (12% grey); Isolate hides everything else. |
| Explode | A slider moves the focused level's parts apart, each its own way: doors out sideways, lids up and away, wheels out, the engine up out of the bay; inside the bay, each part away from the bay's middle. |
| Cut away | A plane slides through the car across, along or by height (the renderer's clipping plane), a dynamic cross-section. |
| Measure | Two clicks on the car give the distance between them in mm. |
| Procedures | Step-by-step checks over the car, each step opening the parts it needs, picking the ones to look at, and moving the camera: the walk-round inspection (8 steps), under the bonnet (8), doors and cabin, boot and underside (the car turned over). Prev, Next, Play (6 s a step), a scrub bar, arrow keys, the step's text over the view. `page.py` writes the steps for each car from the parts it has. |
| Report | ⚑ flags a part; the Report tab lists the flagged parts with room for a note each and a copy button, kept in the browser for that car. The print view is the list and the report. |

None of it is the other suite's code or assets: it is our viewer (three.js) reading the parts our own rigger and finisher named.

## One app on a phone: Parts, Steps, Report, Style, Engine

The car page is one app, made for a phone first. On a phone the car is
pinned at the top of the screen (46% of its height) and everything else
scrolls under it; the toolbars scroll sideways rather than wrap; every
control is a 40-44 px touch target; a tap picks, a drag turns, two fingers
zoom. On a desk the tabs sit beside the car. Frames are drawn only when
something changes or moves, so a still car costs no battery.

| Tab | What it does |
| --- | --- |
| Parts | The parts bench above. Callouts start off on a phone (a small screen fills up); one tap turns them on. **On the ramp** raises the car on a two-post lift so you can see underneath, and **Take a wheel off** lifts the front wheel out onto the floor to show the hub; both our own geometry. |
| Steps | The procedures, with the step's text at the top of the car on a phone. |
| Report | Flagged parts with notes and **photos from the phone's camera**: each part has Add photo, and the car itself has its own. Photos are shrunk to 1,600 px and kept on that device only (the browser's own database), never sent anywhere. **Share report** opens the phone's share sheet with the text and the photos (mail, WhatsApp ...); where there is none it copies the text. Print or save as PDF prints the report with its photos. |
| Style | **New wheels**, modelled by the machine in code at the car's own wheel size: 5-spoke, 10-spoke, cross-spoke, turbine, steel, each with its tyre, barrel, brake disc, caliper and wheel nuts; the factory wheel stays in the file, hidden under it. **Rim size** standard, +1 or +2 inch (the tyre gets lower, the wheel stays the same size). **Ride height** -60 to +40 mm (the body and everything on it moves; the wheels stay on the ground). **Wheel offset** -20 to +40 mm. The **Finish Lab** (chrome, gloss, satin, matt, brushed, candy, any colour) works on the new rims and calipers too. The build line and every choice are kept on the device. |
| Engine | **Lift the engine out**: the bonnet opens and the engine with its gearbox rises clear of the bay on a hoist chain, then swings out over the nose (over the tail on a rear-engined car); Put it back reverses it. Look in the bay; Number every part (the bay's 54 callouts); the engine and gearbox parts by name, each a tap to look at. The card says what the engine is: a representative turbo petrol engine and gearbox, sized to the bay, standing for the family, not this car's own unit. **See it run** opens the running engine below. |
| Engine → See it run | A four-cylinder petrol engine **modelled here in code and cut open**, running through its four strokes: the pistons ride the crank on a real slider-crank, the rods swing, the camshafts turn at half crank speed and push the valves, the timing chain's sprockets turn with them, and each cylinder fires at the top of its compression stroke. A readout names each cylinder's stroke live (firing order 1-3-4-2). **Run** plays and pauses it with a speed control (slowed so the strokes can be followed). **Systems** lights up the air, fuel, spark, exhaust, cooling or oil path with a line on what it does. **Teardown** strips it down — head and cams up, valves out, pistons and rods apart, crank below. It is a teaching model of how an engine of this kind works, not a scan of the car's own engine. |

The wheel designs, the hoist, the running engine and the report are ours,
written for this page; nothing is taken from another app. The running engine
follows the plain physics of a four-stroke engine (the slider-crank, the
two-to-one cam timing, the firing order), which is public knowledge, not any
other program.

## One request, one page: `glbmachine car` and `/car`

`glbmachine car Peugeot 307 2001 blue` builds the car, writes its page, and prints one short JSON answer. The answer holds:
- the page's `index`, and the `files` to publish beside it;
- a one-line `summary` and the machine's `notes`;
- the time to the file;
- or, if no car was built, `error` and what the catalogue has instead.

In Claude Code the `/car` skill (`.claude/skills/car/SKILL.md`) runs it, publishes the page, and replies with the link, before any checking. A request takes about 4 s for a model rigged before, and a first build 10–40 s. With publishing, it stays under a minute from the message to the link.

## GLB Studio: fix a car by hand

When the machine gets a part wrong (a welded bonnet it could not find, a
boot lid cut wrong, stray sheets in the bay), open the car in the Studio:

```
python3 pipeline/realcar/glbmachine.py serve --port 8080   # then http://localhost:8080/studio/
```

1. Pick the car from the list (every car built here that kept its rig).
2. Click a panel: the selection grows from that face to the nearest crease or
   shut line (*Panel*), takes a whole loose piece (*Piece*), or everything
   facing you in a box you drag (*Box*). Shift adds, Alt takes away.
3. Say what it is: Bonnet (B), Tailgate (T), a door (1-4), Body (0) or
   Remove (Del). Ctrl-Z undoes. A coloured line shows where each part will
   hinge; change the edge (a rear-hinged door, a side-hinged tailgate) or the
   angle in the parts list.
4. Build car: the server applies the edits to the rigger's own parts
   (`edits.py`, kept apart so they can be changed or undone at any time) and
   finishes the car again (`finish.py` takes hand-set parts as they are).
   About 5 s. The Result view opens each part.

Tested 2026-10-16: the Qashqai J11 and the Fiat 500e, both "bonnet missing",
fixed with one click and one key each; both now build with everything
opening. "Back to automatic" throws the edits away. The edits are saved with
the car, so later rebuilds (and batch runs) keep them.

## Ask for a car

Your catalogue only: no Sketchfab, no outside service. The only network use
is fetching the model file from the catalogue's own storage.

```
glbmachine make "Vauxhall Corsa 2012 red" -o corsa.glb           # web GLB (meshopt)
glbmachine make "Vauxhall Corsa 2012 red" --full -o corsa.glb    # opens in any 3D program
```

The steps, in order:
1. The approved catalogue is searched for that model in a generation on
   sale that year. If it has the model but not that generation, the nearest
   generation is built and the report says so (`--exact` refuses instead).
   If it has no such model, the report lists what it has for that make.
   Among records that fit as well, the plain body comes before a long or
   special one (Allspace, Tiguan L, LWB), the newer generation first, then
   one ExpertCarCheck may use commercially, then the newest and best graded.
   A generation still built somewhere after its successor came (the Tiguan
   Mk2, kept on in China) counts as on sale only until the successor starts.
   A model the rigger cannot use (its wheels and doors fused into a few
   shells) is passed over for the next best, up to three. The report lists
   it under `passed_over`, with the reason.
2. The file is decoded (`decode.mjs`), rigged (`rig.py`), finished in the
   colour asked for (`finish.py`), validated, compressed and, unless
   `--no-sheet`, drawn on a four-view check sheet; `-o` writes the GLB
   where you want it.
3. The credit written into the file (`asset.copyright`) comes from the
   catalogue record: title, author, licence, link. Only 187 of the 1,044
   approved records carry the author's name; the others are credited by
   title and link until the catalogue records the author.

Timed on catalogue cars (2026-10-16, one at a time):

| Step | Fiesta 2009 | Micra 2004 | Yaris 2001 (in Docker) |
| --- | --- | --- | --- |
| download | 1.0 s | 0.5 s | 0.9 s |
| decode | 0.3 s | 0.3 s | 0.6 s |
| rig | 1.1 s | 1.9 s | 2.6 s |
| finish | 0.5 s | 0.9 s | 1.5 s |
| validator and web copy | 1.3 s | 1.6 s | 2.4 s |
| **car ready** | **about 5 s** | **about 6 s** | **about 9 s** |
| check sheet (optional) | | 20 s | 29 s |

The largest catalogue cars (Juke, Clio) rig in 13-21 s. The top-20 UK
sellers, three at a time: 7 min 16 s in all.

**The rigger** (`rig.py`) is the old Blender rig step ported rule for rule
to numpy, then checked against Blender on the 21 UK top-seller catalogue
cars: the same parts open on 20, with hinges within 5 mm. The one difference
(the catalogue's mislabelled "Honda Jazz") is better in `rig.py`. Blender is
GPL, and code that drives it would have made the whole product GPL; that is
why it was replaced.

**Size.** About half the catalogue's models are not at metre scale. The
rigger sizes those from a guessed wheel height, which can be 15% out.
`wheelbase.py` looks the car up instead, in `wheelbase_table.json`, which
ships with the machine (building a car makes no outside call):
1. The table holds every generation's years, wheelbase and length for each
   make and model in the catalogue, read once from English Wikipedia's page
   text by `wheelbase.py --build` (2026-10-17: 566 makes and models; a
   wheelbase for 621 of the 1,044 approved models and 487 of the 737 that
   match the UK top 2,000). Run it again when the catalogue grows
   (`--build`; `--build --all` reads every page again). Rebuilt
   2026-10-17 after a parser fix: an empty infobox field had swallowed the
   next line, losing years such as the Tiguan Mk3's "2024–present". Now
   1,110 generations, 7 without years (was 1,075 and 45); no wheelbase
   changed.
2. It takes the generation built in the model's year (or, failing that,
   one that started the year after). When two overlap that year, it takes
   the one whose wheelbase-to-length proportion matches the 3D model. A
   generation built on elsewhere after its successor came ends when the
   successor starts. Race and rally cars on a model's page (Fiesta R5) are
   not generations.
3. The answer is used only if it leaves the wheels a real car's size
   (0.50–0.85 m). Otherwise the car is flagged.

Hand-checked figures in `batch.WHEELBASE` win. Tested on seven cars against hand-read infoboxes:
Micra K12, Fiesta Mk6, Golf Mk8, Qashqai J11, Polo Mk6, Focus Mk4 and
Corsa D (through Vauxhall to Opel). All matched, and the A-Class W176/W177
overlap was settled by proportion.

## Stand-in cars: a car the catalogue does not have

When the catalogue has no model of the car asked for, or not of the
generation sold that year, the machine builds a **stand-in**. It takes the
nearest catalogue car of the same body and reshapes it to the real car's
size, so everything still works: doors, bonnet and tailgate open, the glass
is clear, the cabin, engine bay and exhaust are there, and the paint is
right.

```
glbmachine make "2026 Tiguan green 4 door"      # 2022 Tiguan Allspace, reshaped to the Tiguan Mk3
glbmachine make "Vauxhall Insignia 2018 blue"   # no Insignia in the catalogue: a saloon of its size
glbmachine make "..." --no-standin              # the nearest generation as it is, never reshaped
```

1. **The real car's size.** Its length, wheelbase, width, height and body
   come from the wheelbase table (`wheelbase.py`). A model the table has
   never seen is looked up on Wikipedia once, which is the agent's one
   outside call, and kept in `$GLBMACHINE_HOME/wheelbase_local.json`.
2. **The donor** (`make.donors`) must have the same body: hatch, saloon,
   estate, SUV, MPV, coupé, convertible, pickup or van. The body asked for
   wins ("M5 Touring" is an estate); else the record's own word, and a
   title saying "Touring", "Avant", "SW", "Combi", "Shooting Brake" or
   "Estate" counts (`make.record_body`). When the body is known, a donor of
   the same make or maker group comes first if one is within about 10% of
   the size: the reshape makes any donor the car's size, so the face counts
   most (a BMW 3 Series Touring for an M5 Touring, not a Ford of the right
   size). Then the nearest in size, with height weighted most. Then the
   asked model's own other generation first, the same make next, then the
   same maker group (Volkswagen, Skoda, SEAT and Audi; Peugeot, Citroën,
   Vauxhall and Fiat; Renault, Dacia and Nissan; Hyundai and Kia; and so
   on), whose cars share a family look and often a platform, and the closer
   year. A donor that came out short of parts before goes later. Ties go to
   the doors asked for, then the plain car before a GTI or Allspace, then a
   licence ExpertCarCheck may use commercially, then the better grade.
3. **The reshape** (`standin.py`, between the rig and the finish):
   - one axis at a time, so normals stay exact;
   - the target's wheelbase and overhangs along the car, each arch at the
     wheel's own scale;
   - the height above the arch tops;
   - the width across;
   - the wheels moved whole to the new axles and track.

   The roof is measured with aerials and fins ignored. The finisher then
   hangs the doors, fits the engine and paints, as for any car.

   **The donor's name comes off** (`standin.debadge`), found by shape on the
   car's front and rear faces:
   - number plates (plate-sized flat rectangles near the centre line,
     measured in their own plane, so a tilted one counts) become plain:
     white at the front, yellow at the back;
   - the brand's badge (small pieces on the face within 13 cm of the centre
     line) and the model and engine lettering at the back are painted in
     the body colour and pressed flat onto the panel they sit on, taking the
     panel's own normal, so not even their shape is left in relief;
   - whatever lies inside a badge's outline goes with it: its backing, its
     inlay and a lit logo (a ring of fragments counts as holding its middle);
   - glass, lamps and anything seen through the glass are never touched.
     A lit badge or plate that the rigger filed with the lamps still counts
     as a badge.

   Tested on the four donors used so far. The Superb's ŠKODA, SUPERB and
   TSI 380 and its bonnet badge are gone, and the Arteon's VW, ARTEON and
   HYBRID too. The Tiguan's VW roundels are body-colour discs, with faint
   outlines left at the back. The Captur's diamond is part of its grille
   trim, so the frame stays. The lamps and grille keep the donor's shape.
   That is the stand-in's honest limit.
4. **Up to three donors are tried**, and the most complete car is kept:
   - a donor the rigger refuses is skipped and remembered in
     `$GLBMACHINE_HOME/rig_refused.json`, so no request waits on it again;
   - a donor whose result misses parts gives way to the next. Doors on one
     side only, or front doors only on a 5-door, count as missing;
   - no new donor is started after 70 s;
   - the sheet is drawn only for the car kept.

5. **The photo agent** (`photos.py`) runs beside the build, with a
   45-second limit and up to 24 downloads. It looks for a photo of the real car on Openverse
   (openly licensed images from Wikimedia Commons and Flickr, each with its
   licence and author), and on Commons itself as a backup. It keeps only
   licences that allow commercial use: CC BY, CC BY-SA, CC0, public domain.
   It takes side and profile files first, removes the background (rembg, on
   the CPU), and keeps the first photo that passes these checks:
   - the whole car in the picture (not running off an edge), in one piece;
   - one car, and a plain-painted one;
   - both wheels on the ground, at the real car's wheelbase-to-length
     spacing within 6%;
   - its height-to-length proportion within 8%, which rejects an older car
     of the same name.

   **More open photos** (`openphotos.py`, `glbmachine photos --index`, once):
   the Yahoo Flickr Creative Commons set (YFCC100M), in its 15-million
   photo subset on Hugging Face, with each photo's title, tags, date taken
   and licence. It is streamed once (10 GB) and the CC BY and CC BY-SA
   photos that name a car make are kept as a local index
   (`$GLBMACHINE_HOME/open_photos.jsonl`, not shipped). A search takes them
   beside Openverse's, fetched from Flickr (1024 px) only when used. They
   were taken 2004-2014, so they serve older generations. A photo taken
   before a generation went on sale cannot show it, and is left out.
   Hugging Face serves this set from any address, which Wikimedia does not.

   A true side view is tried first. A nearly side-on photo (the car a
   little turned) counts when it passes the same checks, which a real
   three-quarter view cannot. The wheels are found against the ground of
   each half of the car, so a camera that is not quite level still counts.
   File names that say "interior", "toy" or "rally" are skipped, matched as
   whole words: until 2026-10-17 "toy" matched every Toyota. A host that
   says "too many requests" is asked once more after the pause it names, if
   that fits the time, and not again in that search after two refusals.
   Openverse's own copy of the photo is tried instead. A photo whose name
   or tags give no year is marked: the Maker says it may show another
   generation of the same shape.

   Then the stand-in's roof, windscreen, bonnet and tail are shaped to the
   photo's outline (`standin.roof_stage`). The change is up to ±20% above
   the arch tops, smoothed, and the photo's wheels sit on the new axles.
   The published height still sets the size. The photo is only measured:
   nothing of it is in the car. Its credit is shown beside the car in the
   Maker. Each car's search result is kept in `$GLBMACHINE_HOME/photos/`.
   - Measured on the Golf Mk7's side photo, the average gap to the photo's
     outline fell from 5.9 to 2.7 cm (its own model), from 8.2 to 4.8 cm
     (a Mk8 reshaped to it) and from 7.5 to 3.1 cm (a Corsa D reshaped to
     it).
   - Honest limits. Most car photos are three-quarter views, which the
     checks reject. Wikimedia refuses the test machine's shared address
     outright: every direct download is HTTP 429, and Openverse's copy of a
     Wikimedia file is 424. So from there only Flickr photos come through,
     and most stand-ins were shaped from their size alone, as the report
     says. On a server with its own address the Wikimedia files, which are
     most of the side views, should download. That is not yet tested.
   **The standby library** (`photolib.py`, `glbmachine photos`). An agent
   goes down the UK licensing list by rank, through each model's
   generations from 2000 on. It finds a side photo the same way and keeps
   the measured outline in `roofline_table.json`, which ships with the
   machine. That file holds heights along the car, the wheel centres, and
   the photo's file, author, licence and page: numbers and a credit only,
   no photograph. The photos stay in `$GLBMACHINE_HOME/photos/`. A stand-in
   takes its roofline from the library at once, and searches only when the
   library has nothing. The library keeps only photos dated to the
   generation by their name or tags, one photo for one generation, and no
   tuned or widebody cars. One model's generations often share their
   proportions: an undated "VW Golf" passed the checks for three Golfs at
   once, and a Prior-Design widebody 3 Series for five 3 Series.
   - Run on the top 30 (2026-10-17, from the test machine, Flickr only):
     before these fixes 3 of 106 generations were found. After them 16 of
     103 were, and 5 more of 101 with the open Flickr index. Kept under the
     rules as they now stand (`photolib.py --recheck`): Polo 2001 and 2009,
     Mini 2013. The rest were a rally Fiesta, a long-wheelbase Tiguan, a
     motor-show concept Yaris, and photos that fit another generation on
     sale in their year as well (one model's generations often share their
     proportions). A photo is dated by a year in its name (within the
     generation's first ten years) or by when it was taken; either way no
     other generation then on sale may fit it as well, and its name may not
     say it is another body (Allspace, estate, cabrio, coupé, van).
   - The checks alone cannot tell a same-name model from another market:
     a 2016 Indonesian Yaris (XP150) fitted the European XP130's
     proportions better than a real 2024 Mini fits its own, since a photo's
     perspective alone is off by 4-8%. The rule above now leaves it out,
     because the XP150 was on sale that year too. The Maker shows every
     photo it uses, so a person can see it.
   - The run can be stopped and restarted: done cars are skipped, and a
     car not found is tried again after 30 days.
   - It pauses when a source says "too many requests".
   - `glbmachine photos --top 2000 --hours 8` is a night's run;
     `glbmachine photos --status` shows what the library holds.
   - Google Images is not used: its photos are copyrighted, and Google's
     terms forbid scraping its results.
6. **No game or toy models** (`batch.is_game`), for stand-ins or anything
   else: Gran Turismo or Forza rips, low-poly game assets, die-cast, Lego.

The report's `standin` says what the car is, its real size, its body and
the donor. The Maker labels the car "stand-in". The file's credit names the
donor model and its licence, and says the car was reshaped. What a stand-in
is not: the real car's face. Its lamps and grille are the donor's shape;
its badges and plates are taken off (above).

Tested 2026-10-17 (four-view sheet included):

| Asked | Stand-in made from | Time |
| --- | --- | --- |
| 2026 Tiguan green 4 door | 2022 Tiguan Allspace (the plain 2020 Tiguan is fused: passed over once, then remembered) | 22 s |
| Ford Puma 2021 grey | Renault Captur (Skoda Kamiq: doors not separate, passed over once) | 31 s |
| Vauxhall Insignia 2018 blue (looked up online) | 2020 Skoda Superb, a liftback like it (Audi A6: left doors fused; Honda Accord: front doors only) | 53 s |
| Nissan Micra 2004 red (in the catalogue: no stand-in) | its own model | 17 s |

All four open every door, the bonnet and the tailgate. The Superb model's
headlamps came joined to its bonnet, so at first they lifted with it. The
finisher now keeps them on the body (the bonnet rule below), with no Studio
fix needed. Rebuilt with debadging, the Insignia takes 31 s, the Puma 11 s
and the Tiguan 6 s (rigs reused).

## Add your own model

A model bought from a shop or made for you goes into the catalogue beside
the shared one, and a request then finds it like any other. GLB, glTF and
OBJ are read. For an OBJ, its `.mtl` colours, transparency and textures are
packed in, and its object names are kept, so a shop's `Door_FL` still
counts.

```
glbmachine add shop/yaris.obj --make Toyota --model Yaris --years 2011-2020 \
    --doors 3 --licence "royalty-free, CGTrader standard" --author "..." --build
glbmachine models                     # what you have added
glbmachine remove toyota-yaris-2011-own-v1
```

`--doors` decides the doors the rigger cuts, and a request that asks for
those doors prefers this model. The file is converted once, into
`$GLBMACHINE_HOME/models`. The record goes into
`$GLBMACHINE_HOME/catalogue_local.json`. Tested 2026-10-17: a 49 MB OBJ
(431,000 triangles, 21 textures) was added in 7 s. "12 Yaris white colour
2 door" then picked it and built it in 15 s, with two side doors, bonnet
and tailgate.

## The steps by hand

```
node pipeline/realcar/decode.mjs SRC.glb PLAIN.glb               # Draco / meshopt -> plain
python3 pipeline/realcar/rig.py PLAIN.glb OUT_DIR                 # cut: doors, wheels, frame
python3 pipeline/realcar/finish.py OUT_DIR/src.glb SPEC.json CAR.glb
node pipeline/realcar/encode.mjs CAR.glb CAR_web.glb              # meshopt web copy
```

`SPEC.json` (see `specs/polo_mk6.json`): `name`, `wheelbase` (mm, the car
is rescaled to it), `engine_pack` (the workshop petrol bay, exported by
`pipeline/template/tools/export_engine_bay.mjs`), and `credit` (written to
`asset.copyright`).

## What it does

| Step | How |
| --- | --- |
| Bonnet | A modelled car's panels are separate pieces. The bonnet is the largest paint piece lying flat over the front axle, plus the badges on it. Hinged at its rear edge, opens 55°. A piece that is not paint goes with it only if it lies on the bonnet's own skin (under the panel, within 6 cm). The rigger's lamps never go with it. Some source models join the headlamps to the bonnet, such as the Skoda Superb's 7,330 triangles; they now stay on the car. |
| Bonnet, welded | When the bonnet is welded into one shell with the wings and has no shut line in the mesh, it is cut. The region is the shell's top over the front: ahead of the windscreen base plus the cowl, facing up, and above the wheels. The line is that region's half-width along the car, median- then Gaussian-smoothed, and straight across at the cowl. Triangles that cross the line are split along it, with every attribute interpolated, so the edge is a clean curve rather than a staircase. |
| Tailgate | The rear window, the paint panel directly under it, and every piece inside the box they span that sits on the car's rear skin (within 12 cm of the rearmost surface). That takes the tail-lamp inners, the badge, the wiper and the spoiler, and leaves the boot trim and the corner lamps on the body. Hinged at its top edge, opens 75°. |
| Tailgate, from the rig | If no rear window is found (some models make it from dark plastic, not glass), the rig machine's tailgate stands. Like a door, it then takes every piece in its box that touches it: the rear window and the inner lamps. |
| Doors | The rig machine's door cut, plus every small piece inside a door's box and above the wheels that touches the door (within 1 cm of its surface): window frames, belt mouldings and mirrors. Seats and brakes in the same box don't touch the door, so they stay on the body. Hinged at the front edge, opens 65°. |
| Doors inside one mesh | Many models merge every paint panel into one object, which reads as "the doors are not separate objects", yet each door skin is still a loose piece of that mesh. The rigger takes the door-shaped pieces of each flank's outer skin (within 10 cm of the outermost: the cabin's trim inside is left to join its door later) and keeps each one whose twin is on the other flank at the same place along the car, pair by pair. A modeller's left and right doors are seldom the same size, so the biggest piece of one side may be the front door and of the other the rear (the Kamiq, refused before, now opens all four). Re-rigged 2026-10-17, the 58 catalogue cars refused for their doors: 4 more now build (Skoda Octavia Estate, Peugeot 307, Mercedes C-Class, Alfa Romeo Tonale; the last two partly), and the Mazda 3 opens four doors, not two. When the pieces found turn out not to be doors (a front door hinged behind the middle of the car), the car is refused, not built with doors that never open (the Audi A5 Sportback). |
| Bonnet, front clip | A bonnet piece that runs down the sides past the wheel tops behind the front axle is a front clip, the wings welded to it: then only its top is cut out along the shoulders, as for a welded shell, and the wings stay on the car (the Kamiq, and the Superb, whose wings lifted with its bonnet). A tinted windscreen still marks where the bonnet ends; a lamp's glass never does. |
| Glass | Every blended, colourless material becomes clear (light tint, alpha 0.14, glossy). Lamp lenses keep their colour. |
| Names that are a material's | An exporter names each material's mesh `<object>_<material>_0`. A material several objects wear (`door_plastic` on the 2026 G-Class's gear lever, engine and cabin; `door_handles` on its tailgate) says nothing of which part a mesh is, so the rigger reads the object's name without it, and groups a door's meshes by the object, not by material. The G-Class went from three openings to all six. A material only one object wears may still name it. Wheels are found by material names in Turkish too (jant, lastik, teker, frendisk), with the rest of a wheel object's meshes (rims, calipers) taken with its tyres. |
| Spare wheel on the back door | A spare wheel mounted on the tailgate (the G-Class, a Jimny, an old RAV4) rides on it, and the door swings sideways: hinged on the side away from its handle. |
| The model's own lids first | When the rigger found the bonnet or tailgate by the artist's names, the finisher starts from that piece: the G-Class's wings and front panel, welded into one larger piece, are not its bonnet, and the box round its rear window would take the tail lamps beside a door that swings between them. |
| Wheelbase by year and doors | A catalogue model with no years is sized from the generation of the year asked (a 2026 G-Class: the W465's 2,890 mm, not the 2,400 mm of the short W461), and a car with rear doors never from a two- or three-door body of the same name. |
| Both doors in one named mesh | A five-door model whose doors are one named mesh per side (the 2017 Golf's `Doors`) is split at the shut line between them, as a loose door piece is; it opened only its bonnet and tailgate before. |
| Three doors from the table | When neither the request nor the catalogue gives the doors, a model only ever built with two or three (the GR Yaris, "3-door hatchback") is cut as one: its one long door is not split into two. |
| Names match whole words | A model's name must be the request's words, whole: "CLA" is not found inside "G-Class". |
| A saved rig from an older rigger | is rigged again on the next build, unless it was corrected by hand in the Studio. |
| Engine pack in a short nose | The pack is lowered up to 15 cm and moved back up to 12 cm to sit under the bonnet and behind the nose. Where that is not enough, a pack part still out past the car's outer skin by more than a centimetre is left out, and the finisher's log names it with how far it stood out (`engine_pack.left_out_no_room`, `no_room_cm`). The outer skin is the furthest body or lid surface within 25 cm, so a radiator seen through a grille opening stays. The Focus RS's cooling pack had stood 19 cm out in front of its grille; the classic Defender's bay floor 34 cm out under its bumper. |
| A file that is another car | `batch.WRONG_CAR` lists catalogue files that are a different car from the one they are filed under (the 2018 Honda Jazz file is a Toyota RAV4; the 2023 Ford Ranger file is a Suzuki Vitara). Neither a request nor a batch builds them, or uses them as a stand-in donor, and they are not offered in `catalogue_has`. Before, only a batch skipped them: "Honda Jazz 2018" was built as the RAV4. |
| Vans: barn doors | A van's back opens as two barn doors, each hinged at its outer edge, not as one lid (a stand-in Transit from the Renault Master); its tail lamps stay in the rear pillars. A tailgate the model names stands as it is. |
| Two doors asked for | "Transit 2 door" from a model with rear side doors keeps them shut, part of the body. A five-door model whose doors are one piece a side (the 2017 Golf's `Doors`) is still split at its shut line when that piece is longer than any door (42% of the car), and a cut that comes out that long is cut again as four: before, "Golf 2017 2 door" was refused and built with four doors open. The rear pair are closed up so they read as body: the outside handles go, the skin's outer edge grows over the 4 mm gap to the body (never at the edge against the front door, which opens), and the lining behind it steps 1 cm inboard, so its edge no longer shows as an outline. The 1998 Micra (a 5-door model, asked for as a 2-door) is the case. |
| Electric car | A model the catalogue files as electric only (Tesla, Polestar, the BYD Atto and Seal, the iX, the ID. family ...; never a hybrid, a PHEV, an i8 or a BYD DM-i) gets no engine pack: the bay keeps the model's own front end, the page says so ("an electric car: it has no engine") and its steps are electric-car checks (the front lid, the charge port, the battery casing underneath, the tyres). The Model 3, the EV6 and the i4 had had a petrol engine under the bonnet. |
| Panel van without rear glass | A van's back with no window to start from (the NV200's is all steel) is taken from its painted back: inside the tail lamps in the rear pillars, up to just under the roof's edge, down to the bumper's top, then split into its two barn doors. The NV200 had opened no back door at all. |
| Sliding side doors | A van's side doors slide, they do not swing: out from the body 7 cm, then back along it by most of the door's length, never past the tail (their clip moves the door; the vehicle file says `"type": "slide"`). Every van's side doors, a tall MPV's (2.6 wheels or more: the ID Buzz), and any the rigger judged sliding by name or by the van signature. The NV200, Vito, Caddy and Sprinter had swung them open like a car's. |
| Tinted windows | A blended, colourless material too dark or too opaque for clear glass (the 1998 Micra's grey at 0.79, named `Material.002`) is glass when it covers over a square metre above the waist on both sides and at both ends of the cabin. The Micra's bonnet and tailgate are found from its windows, so it had opened neither. |
| A tailgate's bottom edge | A tailgate cut from a welded shell runs down to the bumper's top: going down its back off the middle, the first place the surface steps back 4 cm within 3 cm of height (beyond the panel's own lean) and stays back, or turns from paint to a black bumper for the next 15 cm (the Master's, all but flush). The surface is sampled across its triangles, not at their corners. A boot lid (a deck of 35 cm or more behind the rear window: the Model 3, the Roma, the 128i coupe) still ends at its own lip. The Micra's tailgate now takes its number plate, the Master's barn doors reach the paint's end 10 cm lower, and the Focus RS's the bumper. Tail lamps in the body's corners stay on the body; a floor meeting the back at the sill stays in the van. |
| Wheel pieces outside the wheel | Pieces the rigger gave a wheel that lie wholly outside it, past its tyre's sides by 3 cm or its tread by 5% (the 2017 Golf's model floats a small black, plastic and chrome piece by each wheel), are dropped, before the car is measured. They had set the ground 10.6 cm under the Golf's tyres and its wheels' cylinders too big, which gave pieces of the rear bumper to the rear wheels. A tyre modelled as two sidewalls and a tread (the M5's) is measured across all its pieces on the axle. |
| Required extensions travel with a pack | A file brought in (`gltf.append`: the cabin pack, whose WebP textures have no fallback image) brings its `extensionsRequired` along, so the car file says what it cannot be read without. |
| A download cut short | is tried again, twice (the Discovery's 47 MB came through 1.2 MB short once). |
| The workshop exhaust | ends 30 cm inside the car's tail, under the floor: seen from below (Flip over, the ramp), never a second tailpipe beside the model's own. The 2025 M5's four dark tips had a silver fifth; the 911 Turbo S keeps its own twin tips alone. |
| A solid material marked see-through | A model's material at full alpha set to blend (the 2025 M5's cabin) blends with what is behind it: the dash screen showed through the steering wheel's rim. When its texture's alpha is mostly on or off (perforation, stitching, a grille's holes), it is drawn as a cut-out: solid, with its holes. One soft all over is see-through by design and stays (the 2001 Yaris's gauge cover), as do glass, lamp lenses, shadows and decals. |
| Right-hand drive | "RHD" or "right hand drive" in the request: a left-hand-drive model's cabin is mirrored across the car (the rigger's cabin and every body piece wholly inside it, from the seats to the pedals at the bulkhead; never the outer shell, doors, wheels or engine bay), and the steering wheel is carried across whole, not mirrored, so its badge and buttons read the right way round. The driver's side is found from the steering wheel and column's dense pieces behind the dash; the wheel's centre line is the middle of its rim, so the pieces carried across line up with those mirrored. A model already right-hand drive, or one whose wheel's side is unclear (the G-Class) or whose cabin is not its own part, is left as it is and the page says why. Checked on the 2025 M5, the 2017 Golf and the 911. |
| A body the catalogue does not have | Makers' own names for an estate count as estate: Touring, Avant, Variant, SW, Combi, Sports Tourer, Shooting Brake, Wagon (not a Wagon R, a 911 GT3 Touring or an Active Tourer). When the model is in the catalogue only in another body, it is a stand-in of the body asked: "BMW M5 Touring 2025" was the F90 saloon, said nowhere; it is now a BMW 3 Series Touring reshaped to the M5's size. A hatch's estate takes the donor's own proportions on the car's wheelbase (a Golf estate is longer than the Golf). If no stand-in can be made, the note says which body was built. |
| A paint finish, a wheel colour | "matt grey" (or matte, satin, BMW's "Frozen"): the page starts the body in that Finish Lab finish, in the colour asked. "black wheels" ("gloss black alloys", "matt black rims"): the rims start in it, and its colour is never taken for the paint. Both hold until the viewer picks another. |
| A cabin for a model with none | A model with nothing inside (the 1998 Micra: 42 triangles where a modelled cabin has thousands) gets the cabin pack, `assets/cabin_pack.glb`: the seats, dashboard, steering wheel and console of the 2001 Toyota Yaris (CC BY 4.0, credited in the file and on the page). It is scaled to the car's wheelbase, width and roof height (the roof read over the middle of the cabin, so an aerial does not count), then moved back, down or made lower, by at most 20 cm, 4 cm and 12%, until it stays under the roof and the windscreen and over the floor. The Micra's moved back 18 cm. `cabin_pack.py` cuts a pack from any rigged car: only the pieces wholly inside the cabin, below 78% of the roof (the pillar trims, mirror and visors follow their own car's glass). |
| Wheels kept in pairs | A model whose wheel meshes each hold both wheels of an axle, with nothing named (the 1998 Micra's `Object_4..12`), has them split left and right, where each half alone is round, narrow and grounded. |
| Default material names | Siblings of the paint by name (`primary`, `primary.001`) are the same paint, but not a modeller's untouched defaults (`Material.001` ... `Material.019`), which were the Micra's tyres, glass and lamps. A default with its own number (`Material_1467`, Maya's `lambert2`) is one material, and its `.001` copies that one again. When the finisher's pick of the paint is a colourless near-black layer lying on the door skin (a door card with no thickness), the rigger's pick from the doors' outer faces wins. |
| A van's rear plate | may sit on one of its doors, off the centre line: it is made plain too (the NV200's). |
| Rear engine (911) | Every 911 has its engine behind the rear axle. The engine lid lifts 60°, wing and all, from the rear window's lower edge. The window stays fixed, and the light bar below the lid stays on the body. The light bar is found as the band with the most lamp area, so a third brake light in the wing doesn't count. The workshop bay is turned round onto the rear axle, with the engine under the middle of the lid. The pack's radiator, tank and front gear are left out: a 911 carries its radiators and tank in the nose. The front lid opens on the model's own luggage space. Under the engine lid, everything but the paint and the lamps is cleared up to the lid's top, which takes the 992 grille's deep fins. A dark wall closes the front of the bay at the lid's edge, hiding the seat backs, which are never modelled from behind. The check sheet's bay view looks at the back. A stand-in takes the layout of the car it stands in for, not its donor's. The rule is checked on the 992 Turbo S. On a GT3 some paint pieces still stand in the bay, and a classic 911's lid underside comes out ragged. |
| Trim from the request | The words after the model are its trim: "911 2024 turbo s" builds the catalogue's Turbo body, not the 2024 S/T. A record made as one or two trims counts. A record listing the trims its body fits (SE, Sport, ST-Line ...) is the standard car. A record with no year can be dated in `GENERATION_FIX` from its own renders. |
| "2024 plate" | is read as the year, and "plate" is dropped from the model words. |
| Tangents | Every piece whose material has a normal map (or a clear coat's) gets tangents of its own, from its texture coordinates, so no viewer has to make them up and the file passes the glTF validator with no errors or warnings. The engine bay's pieces carry theirs in `assets/engine_pack.glb` (about 0.7 MB more per car). A map with no texture coordinates to apply it is dropped. |
| Maps with no coordinates | A piece whose material has a map but which has no texture coordinates to read it by gets a copy of the material without that map. The engine pack's gearbox case and bellhousing were the cases: the full file passed the validator, but every web copy since showed 28 errors once gltf-transform re-wrote it. Each build now validates the web copy as well as the full file, and a car is "done" only when both pass. |
| Engine | The workshop's petrol bay goes in. The bay, engine, gearbox and front suspension are scaled to this car's track about the front axle. The rear suspension and fuel tank are placed about the rear axle. The exhaust is stretched from the front pipe back to 10 cm inside the rear bumper. Pieces reaching below the ground (workshop leftovers) are dropped. |
| Frame | The car is centred on its wheelbase, with x = 0 down the middle and the ground at y = 0. Nose is +z and the car's left is +x, the same frame as the template cars. |
| Clips | `door_fl_open` … `door_rr_open`, `bonnet_open`, `tailgate_open`, `doors_open`, `all_open`. |

## First proof: Volkswagen Polo Mk6 GTI (2026-10-16)

Source: catalogue `volkswagen-polo-2023-v1`, "2023 Volkswagen Polo GTI" by
tonielpro520, CC BY 4.0 (commercial use allowed, credit required).

- The rig machine alone gave four doors and a 42-triangle strip it took for
  the bonnet. It found no tailgate, and it left the window frames floating
  when the doors opened.
- After the finisher, everything opens:
  - bonnet: one 1.4 m² panel, 26 pieces;
  - tailgate: 245 pieces;
  - 42–46 trim pieces per door.
- Glass: the windows and headlamp lenses are cleared.
- Engine: the bay is scaled ×0.963 and the exhaust stretched ×0.960.
- Size: rescaled ×0.970 to the 2564 mm wheelbase. The output is 27.5 MB,
  and the meshopt web copy is 9.0 MB.
- glTF validator: 0 errors. The 49 warnings are the engine pack's
  normal-mapped parts, which have no tangents.

![Polo Mk6 finished](polo_mk6_sheet.jpg)

Known limits:
- The engine is the workshop's petrol bay, not each car's own engine.
- The inside face of the tailgate is the outer panel's back (no trim card).
- The model is 4.13 m long on the published wheelbase. This source runs about
  1% long.

## Second proof: Nissan Qashqai Mk2 J11 (2026-10-16)

Source: catalogue `nissan-qashqai-2018-v1`, "2018 Nissan Qashqai" by
Ddiaz Design, CC BY-NC-SA 4.0. The catalogue had this as CC-BY; Sketchfab
says NC-SA, so it is free-app use only.

- The rig machine alone gave four doors and the tailgate panel. It found no
  bonnet (the body is one welded shell) and left the rear window (dark
  plastic) on the body.
- After the finisher, everything opens:
  - bonnet: cut along a smoothed shut line, 1.16 m², 212 triangles split;
  - tailgate: took 34 touching pieces, including the rear window and the
    inner lamps.
- Glass: the windows and lamp lenses are cleared.
- Size: rescaled ×1.008 to the 2646 mm wheelbase. The meshopt web copy is
  7.5 MB.
- glTF validator: 0 errors.
- Polo re-run with this code: same bonnet, doors and trims. The tailgate
  takes 11 more small touching pieces (checked by eye).

![Qashqai finished](qashqai_j11_sheet.jpg)

## Bikes modelled in code

`bikes/cruiser.mjs` builds a heavy cruiser motorbike from three.js geometry
and writes it as glTF with gltf-transform: no downloaded model, so the file is
wholly ExpertCarCheck's. Its sizes are a real bike's published figures (the
`FATBOY` preset: 1,665 mm wheelbase, 2,370 mm long, 30 deg rake, 132 mm trail,
675 mm seat, 160/60R18 and 240/40R18 tyres); the fork offset follows from rake
and trail (48 mm). Parts move about their real pivots: `wheels_spin` (a loop),
`steer_left` / `steer_right` (about the raked steering axis, with the front
wheel), `stand_down`. The paint is one material (`paint`), set with
`--paint=#hex` or changed in a viewer. No maker's badge or lettering is
modelled; the maker's names are trademarks.

    node pipeline/realcar/bikes/cruiser.mjs bike.glb --paint=#121214
    node pipeline/realcar/encode.mjs bike.glb bike_web.glb      # 0.83 MB, validator clean

With `--parts` every piece is its own named node under the pivot it moves
with, so a trainer can take any one off: frame, swingarm, rear shocks, fork,
crankcase, cylinders, cylinder heads, rocker covers, pushrod tubes, spark
plugs, gearbox, primary cover, belt, air cleaner, exhaust, tank, fuel cap,
speedo, seat, both mudguards, lamps and indicators, bars, mirrors,
footboards, pedals, both calipers, discs, rims and tyres (40 in all, each
with `extras.moves_with`). The motion is unchanged, and without the switch
the file is byte-identical to before.

Two more are built the same way, from what the bikes share in `bikes/kit.mjs`
(the geometry helpers, the cast wheel and tyre, the writer; the cruiser's
output is byte-identical on it):

| | `bikes/sports.mjs` | `bikes/scooter.mjs` |
| --- | --- | --- |
| Kind | 600 cc inline-four supersport (the `SUPERSPORT` preset, an R6-style 600) | 125 cc scooter (the `SCOOTER125` preset, a PCX125-style) |
| Sizes | 1,375 mm wheelbase, 2,040 mm long, 24 deg rake, 97 mm trail (33 mm fork offset), 850 mm seat, 120/70ZR17 and 180/55ZR17 | 1,315 mm wheelbase, 1,935 mm long, 27 deg rake, 86 mm trail (39 mm offset), 764 mm seat, 110/70-14 and 130/70-13 |
| Moves | `wheels_spin`, `steer_left` / `steer_right` (28 deg; the fairing stays), `stand_down` | the same (35 deg; the bar cover steers), `centre_stand_down`, `seat_open` (the seat lifts 70 deg on its front hinge, `seat_hinge`, over the storage bin) |
| Pieces (`--parts`) | 59: twin-spar frame, subframe, braced swingarm, monoshock, upside-down fork, twin discs and radial calipers, the four's crankcase, block, head, cam cover, coils, clutch and alternator covers, oil filter, sump, throttle bodies, airbox, radiator and hoses, four headers and the silencer, chain and sprockets, upper fairing, both lowers, belly pan, screen, headlamps, dash, tank, seats, side covers, tail, battery ... | 50: step-through frame, front cowl, leg shield, floorboard, the fuel tank under it, floor skirts, both body panels, tail cowl, storage bin, the single's crankcase, cylinder, head, cam cover, CVT case, final drive, air filter, radiator, exhaust, twin shocks, disc and caliper, rear drum, bar cover, dash, both stands, seat ... |

    node pipeline/realcar/bikes/sports.mjs sports.glb --parts       # validator clean
    node pipeline/realcar/bikes/scooter.mjs scooter.glb --parts     # validator clean

## App packs

`app_pack.py` turns builds into what an app loads: per vehicle a plain GLB
and a vehicle file (parts with labels, systems, boxes and which way each
comes off; hinges with pivot, axis and angle; clips; procedures; the
engine's real layout beside the teaching engine; the credit). It runs the
machine itself from a list of requests, so the pack rebuilds from one file;
`app_hero.mjs` renders a studio picture of each. The Vehicle Analyser app's
pack and brief are in `apps/vehicle-analyser/`.

    python3 pipeline/realcar/app_pack.py apps/vehicle-analyser/fleet apps/vehicle-analyser/fleet.spec.json
    node pipeline/realcar/app_hero.mjs apps/vehicle-analyser/fleet
    python3 pipeline/realcar/app_pack.py --heroes apps/vehicle-analyser/fleet
