# Door regression review — ON STANDBY (owner, 2026-10-06)

45 cars scored lower after the door cutter in the 17:33 re-run
(`worse.txt`, scratchpad `worse_run/`). That run predates the
implausible-net fix (7818842f) and the two-door fix (6d2329a2). Against the
final survey (`survey.jsonl`, commit 39024736) versus the pre-cutter survey
(commit 7c60a247): 1 better (Porsche Macan, 2 -> 4 doors, cut), 17 back to
their old result, 27 still lower.

A lower count is not proof of a regression — the old rigger also counted
wrong parts as doors. The 27 sort into the `_implausible` rules that dropped
parts; each class still needs an A/B render (`SB_NO_IMPLAUSIBLE=1` vs default)
before anything changes:

| rule that dropped it | cars | suspicion |
|---|---|---|
| rear door "hinged at the front axle" | Kona, RS4, Mirage, Civic 2015, BYD U7, V50, 918 | real rear doors on 4-door cars may be dropped; 918 (2-door) drop looks right |
| door "hinged outside the wheelbase (a wing)" | SLS AMG, GT-R nw1, Lotus Emeya, G-class | SLS gullwings and GT-R front doors are real doors — likely false drops |
| door "more than 42% of the car" | Lancer Evo, G-class rear, S2000, Cefiro, 300C | probably a whole flank grouped as one door; drop is right, but no door replaces it |
| bonnet "reaches down to bumper height" | EV9, XJ220 x2, GT40, E-type | GT40 and E-type have real front clamshells — likely false drops |
| tailgate "more than 35%" / "not at the back" | EV9, 206, GT40, 911 (2021) | GT40 rear clamshell is real |
| cutter refused, "reaches above the glass line" | S60 2004, Cefiro, 300C | old doors dropped and none cut |
| Blender timeout (no change) | BMW XM, Opel Corsa 1997 | refused before, error now |

Next step when resumed: render the open state for one car per class, both
ways, and look.
