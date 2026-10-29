# Vehicle AI: a trained model for the car machine's photos and builds

A real trained model, not written rules: it learned from the run's own answers
(1,647 pictures: 936 photos and 711 builds, named by the colour, side and
review agents, with their hand-checked gold items, and the machine's own record
of which builds are stand-ins), from 1,776 CC-licensed Flickr photos whose
titles name a vehicle and its colour, and from 1,905 pictures of no vehicle
(1,684 Flickr photos of landscapes, animals, food, rooms, people; 221 drawn:
noise, plain colours), on top of two image models: SigLIP (Google's, trained on
10 billion captioned pictures) and DINOv2 (Meta's, trained without captions to
tell pictures apart). The colour head also reads how near a picture is to
SigLIP's own reading of each paint's words ("a photo of a silver car",
`words.py`). It answers the review agents' questions, and one more:

| Question | Of | Answers |
|---|---|---|
| **vehicle** | a photo or a build | yes, no (whether there is a vehicle in it at all) |
| **kind** | a photo or a build | car, van, motorbike (what the picture shows) |
| **side** | a photo or a build | left, right (the way the vehicle points) |
| **colour** | a photo or a build | one of 29 of the review's paint families (gold and lilac had no example), with the paint the machine builds it in |
| **match** | a build beside its photo | how likely the build is the photo's vehicle (its shape, not its paint); a stand-in held to the stand-ins' own line |

and `check` puts them together into a second opinion on a build: what looks wrong
(`flags`), and `look` or `ok`.

## How good it is

Every vehicle is in one of five folds; vehicles that share a picture (twins
with one photo, a van and its car version with one build: 88 pictures) share a
fold, and so do the Flickr photos. Each fold was answered by heads trained on
the other four, so every number here is on photos and builds the model had not
seen (`heads.json`'s `card` keeps them all), beside what always giving the
commonest answer would score:

| Question | On | Right | Always the commonest | |
|---|---|---|---|---|
| kind | 936 photos | 98.2% | 63.0% (car) | 14 cars read as vans, 3 vans as cars; the motorbikes are the easy ones |
| | 722 photos of cars and vans | 97.6% | 81.7% (car) | |
| | 1,776 Flickr photos | 94.8% | 89.1% (car) | strangers' pictures, of every angle and light |
| side | 711 photos | 100% | 54.0% (right) | not one miss; 100% on the builds too |
| colour | 722 photos | 77.8% | 28.7% (white) | 90.7% its family or the next shade (always white: 49.6%); 95.3% in its top 3 |
| | 711 builds | 92.5% | 28.3% (white) | 97.3% its family or the next shade |
| match | 650 builds with their own photo, 3,555 with other vehicles' | 0.95 | 0.50 | the chance a build scores higher with its own photo than with another vehicle's (AUC; 0.5 is a coin, 1 is never wrong) |
| vehicle | 1,684 photos of no vehicle | 99.9% none | 0% (always "a vehicle") | 2 missed: a family, a sunset; the 221 drawn pictures all none |
| | 1,647 run photos and builds | 100% a vehicle | | and 98.0% of the 1,776 Flickr vehicle photos (31 cars read as none) |

What counts as a vehicle: part of one too. Of the Flickr photos `qa.py` left out
(not trained on), an engine bay read as a vehicle 25 times in 25, a drawing of
a car 7 in 10, a car park 25 in 25; a building photographed under a car's tag
read as none 25 times in 25.

The next shade is a family within 25 of it in Lab and in its group (white to
black as one group, the rest by hue), or both dark (L under 32: black, dark
blue and dark green are a toss-up in a photo, looked at): grey for dark grey,
silver for white, not aqua for white; 22 pairs of the 406.

**What the picture shows.** The run's kind is the target list's class: a
Transit is listed as a car, and a Corsa van's photo shows the Corsa hatchback.
The model's kind is what the picture shows: 36 photos were looked at and
corrected in `kind_by_eye.json` (22 panel vans and van-bodied MPVs listed as
cars, 14 hatchbacks, estates and SUVs listed as vans). Scored against the
list's classes instead, kind is 94%: the difference is the list, not the model.

**Sure.** Each head's threshold is the lowest `p` from which photos were right
99 times in 100, held out; set on one half of the vehicles and tried on the
other, read the 99 as about 98. Colour is now that sure on half the photos (it
was 36%); set on one half and tried on the other, 98.1% and 99.0% right. Some settings (the heads' `C`, `REAL_WRONG`, `SURE_RIGHT`,
`WORDS_WEIGHT`) were picked after looking at held-out scores: they may flatter
them a little.

The match against what the run knows was wrong, beside the encoders untrained
(the cosine of the photo's and the build's embeddings, its threshold set the same way):

| | AUC | Flagged | Untrained: AUC, flagged |
|---|---|---|---|
| 251 builds of the photo's own model, against 458 stand-ins (another model's body reshaped) | 0.92 | 10% of own-model builds, 13% of stand-ins (each held to its own line) | 0.86 |
| the reviewers' 107 passed builds, against the 10 they found the wrong shape on the build there now | 0.72 | 3 of the 10, and 13% of the passed builds | 0.65, 1 of the 10 |
| ... against the 61 whose last verdict named a shape fault (on that build or an earlier one) | 0.79 | 34% | 0.67, 18% |

**Stand-ins have their own line.** A stand-in (64% of the run's builds) is
another model's body reshaped to the car, never quite its photo: held to the
line of a build of the photo's own model, 78% of them were flagged, and 47% of
the builds the reviewers passed. Now a build of the photo's own model is held
to the line one in ten of those fall below, and a stand-in to the line one in
ten good stand-ins fall below (set on one half of the vehicles and tried on the
other: 4% and 14% of own-model builds, 15% and 6% of good stand-ins). Flagged:
13% of the passed builds. The price: of the 10 builds the reviewers found the
wrong shape now, 3 are flagged; the single line flagged 8, by flagging half of
everything (at random, half would flag 5). Among stand-ins alone the score
ranks good above wrong barely better than a coin (AUC 0.58): the faults it
misses are the right kind of body with the wrong look (a 1950s Ford Popular
made from a modern saloon, a Vivaro the wrong van). Neither a body-type head
(tried: right on 85% of photos, but it caught 1 of the 10) nor the machine's
record of how far it stretched the donor separated them from good ones; 10
wrong stand-ins are too few to learn from. More reviewed wrong stand-ins are
what would teach it. Read a `look` as "worth a look", not "wrong".

The run's labels are the agents' answers checked by gold items, not certain
truth: a "mistake" is sometimes the label's.

## What changed on 29 October

The first model (28 October) sat on CLIP ViT-B/32 alone and scored kind 94%,
side 95%, colour 67% and match 0.88, flagging 40% of stand-ins. Five encoders
were tried on the same folds (`heads.json`'s card keeps the table):

| Encoder | kind | side | colour | match AUC | stand-ins flagged | 
|---|---|---|---|---|---|
| CLIP ViT-B/32 (the first model) | 94.0% | 95.1% | 67.2% | 0.88 | 40% |
| CLIP ViT-L/14 | 94.8% | 94.1% | 67.3% | 0.92 | 55% |
| DINOv2 base | 94.1% | 100% | 67.7% | 0.89 | 40% |
| SigLIP base | 95.2% | 92.5% | 71.3% | 0.94 | 75% |
| SigLIP + DINOv2, side by side | 98.5%* | 100% | 71.6% | 0.95 | 76% |

(* against the by-eye kind; the others against the list's.) Cutting the
vehicle out of its background before reading the paint (a segmentation model)
helped nothing and was dropped. The Flickr photos (`extra/`) teach the colour
and kind heads at half the weight of the run's own; their colour word is the
photographer's, so only pictures whose paint bears it out (`extra/qa.py`) teach
colour. Wikimedia Commons' colour categories (348,000 photos) were listed but
could not be fetched from here: its servers refuse three requests in four from
this machine's address.

Later the same day: the vehicle head (pictures of no vehicle, `extra/none.py`:
Flickr photos by topic, each held to CLIP against vehicle prompts, and drawn
noise), and the stand-ins' own line for the shape check (see above). Neither
moved the other heads' scores.

In the evening, colour (74.8% of photos right, held out). Tried on the same
folds, and no better: a smaller or larger `C` (73.6%, 73.0%), standardised
numbers (74.8%), paint statistics of the picture's middle (72.0%), the mirror's
reading averaged in (73.1%) or trained on (74.4%), 1,106 more Flickr photos
naming one colour and a make (74.7%), and the run's coloured photos and builds
with their paint's hue turned, to teach it to follow the paint (72.2%). What
worked: SigLIP read the run's photos' colour from words alone, untrained, 62%
right (86% to the next shade), so its words for each family are a direction in
the pictures' own space that thousands of captioned pictures set. Given each
picture's likeness to them beside its numbers, the head scores 74.4% at weight
3, 78.1% at 10 and 79.6% at 30, on both halves of the vehicles. At 30 its
answers were so sure that its surest wrong ones decided where the 99-in-100
`sure` line fell: on one half of the vehicles there was none, and the phone's
heads found none, so colour never counted against a build there. At 10 the line
holds on both halves, so 10 it is (trained in: 77.8%). The paint moves with it
more: with red and blue swapped, held out, a coloured car's colour moved to the
swapped paint's group on 89% of 208 photos (83% of 199 before; 91% at 30); turned grey,
the colour went on 98.6% (99.5% before). The head is written folded: the words' weights become the embedding's, so
`heads.json`, `predict.py` and the phone page read the same numbers as before.

## Try it yourself

`try_it.py` checks the model with nothing of this run's: paste it into a Google
Colab cell (works from a phone's browser) or run `python3 try_it.py` anywhere;
about 5 minutes (720 MB of encoders to download). It downloads the code and
weights from GitHub at a pinned commit (refusing any file whose SHA-256 is not
the one it prints), and then:

- checks its 29 Wikimedia test photos, and 16 Flickr photos of no vehicle (from
  further down the set than the training's were taken), were not trained on:
  each against the looks (`vision.dhash`) of every training picture, published
  in `train_pictures.json`
- scores the answers against a person's, strictly (the one answer a person
  gives) and leniently (a fair second: a Multivan is a van but registered as a
  car), beside random guessing and always giving the commonest answer
- runs the same code with the trained weights swapped for random ones: it falls
  to guessing, so the skill is in the training, not in the code
- recolours the photos on the spot (red and blue swapped; grey) and sees whether
  the paint read moves with them, and reads random noise (it should be none)
- shows photos picked at random as it runs, that nobody chose, and asks you what
  you see before it shows the model's answer (`BLIND`)

The mirror is not a check: the side reading averages a picture with its mirror,
so a mirrored picture always reads the other way.

Its run here (29 October, the colour head with SigLIP's words, pinned to that
commit): no test photo within 61 bits of a training picture; kind 29 of 29, side
29 of 29, colour 27 of 29 strictly and leniently (it was 20 and 22; the misses: a
silver Boxster read grey, a white Mini Coupe pearl-white); the vehicle photos read
as a vehicle 29 of 29, the 16 photos of none as none 16 of 16, random noise as
none. Red and blue swapped, the paint moved with it on 8 of the 9 coloured cars
(it was 4: a champagne S-Class swapped still reads silver); turned grey, the
colour went on 9 of 9. With random weights, ten draws averaged: kind 12.4, side
13.6, colour 0.5, vehicle 11.6 of 29 and none 8.8 of 16.

The run before (29 October, the model that tells a vehicle from none, a new Python
environment): no test photo within 61 bits of a training picture; kind 29 of 29,
side 29 of 29, colour 20 of 29 strictly and 22 leniently, as before; the 29 vehicle
photos read as a vehicle 29 of 29, the 16 photos of none as none 16 of 16 (always
saying vehicle: 29 and 0), and random noise as none (100%). With random weights,
ten draws averaged: kind 12.4, side 13.6, colour 1.1, vehicle 11.6 of 29 and none
8.8 of 16. (One draw can land far from half for side, which reads a picture
against its mirror: a random direction gets nearly all right or nearly all wrong
by its sign, 26 and 6 in two draws; hence the ten.)

The v2 model's run (29 October, a new Python environment, about 5 minutes with the
720 MB download): no test photo within 61 bits of a training picture; kind 29 of
29 strictly and leniently (always "car": 20); side 29 of 29 (always "left": 19);
colour 20 of 29 strictly, 22 leniently (always "white": 9), its misses silver
against white or grey and champagne against silver. With random weights: kind 13,
side 6, colour 1. Red and blue swapped, the paint moved with it on 4 of the 9
coloured cars (a weakness: a swapped dark blue still reads dark blue); turned
grey, the colour went on 8 of 9. Random noise still reads as a car (91%): it
cannot tell a vehicle from no vehicle. (The first model, 28 October: kind 27,
side 28, colour 20 and 22.)

## Checked by other AIs

Three other models (Claude Haiku, Sonnet and Fable) ran `try_it.py` on the
first model from a fresh copy and audited the code without being told what to
find. All three found a real model (Fable: the same code with random weights
scores at chance). They also found what was overstated, all of it fixed since:
the mirror check cannot fail; a model always answering "silver" passed the grey
check; three hand answers had been loosened ("car or van") after the model
missed them; the colour swap was scored by a swatch's tint; the training
pictures were not published, so "never trained on" could not be checked; a leak
of shared pictures across folds; the next shade counted 51 pairs (white and
aqua among them); no score stood beside a baseline; the 99-in-100 threshold was
set and scored on the same answers; the settings tuned on held-out scores were
not said; and the phone page's example is a vehicle the model was trained on
(the page says so). This model has not been audited again yet.

## Use it

    pip install numpy pillow onnxruntime
    python3 pipeline/realcar/ai/predict.py photo car.jpg [more.jpg ...]
    python3 pipeline/realcar/ai/predict.py check car.jpg build.png
    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/predict.py key car-ford-fiesta
    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/predict.py run     # every build: $F1K_HOME/ai_review.json

The first run fetches the two encoders (720 MB, each pinned and checked by its
SHA-256) into `$VEHICLE_AI_HOME` (default `~/.cache/vehicle-ai`). A file it
cannot read (missing, broken, not a picture, under 64 pixels a side) gets
`{"error": ...}` and the others go on. From Python:

```python
import sys; sys.path.insert(0, "pipeline/realcar/ai")
from predict import VehicleAI
ai = VehicleAI()
ai.photo("car.jpg")
# {"file": "car.jpg", "kind": {"answer": "car", "p": 0.9}, "side": {"answer": "right", "p": 0.68},
#  "colour": {"answer": "silver", "p": 0.97, "paint": "#c4c7ca", "top3": [...]}}
ai.check("car.jpg", "build.png")
# {"photo": {...}, "build": {...}, "match": 0.93, "flags": [], "answer": "ok"}
```

`p` is how sure the head is. A kind, side or colour that differs between photo
and build is only flagged when both readings are at least as sure as the
head's threshold in the card: photos read that surely were right 99 times in
100, held out. The run's labels are about that good, so on this run those flags
are rare and the shape flag is the one that finds things.

`run` is the run's second opinion. `train.py` leaves every build's held-out
answer in `ai_review.json`; `run` keeps those while the build and photo are the
ones answered, checks with the final heads only a build or photo that is newer,
and lists the flagged builds the reviewers passed (their verdict counts only
on the build and photo it was made on). About 0.5 s a picture on one CPU core
(a check reads two); no GPU, no PyTorch.

## Take it with you

    python3 pipeline/realcar/ai/bundle.py vehicle-ai

makes `vehicle-ai/` and `vehicle-ai.zip` (about 720 MB): the code, the trained
heads and both encoders in one folder that runs anywhere with Python 3.9+, offline:

    cd vehicle-ai && pip install -r requirements.txt && python3 predict.py photo car.jpg

(`key` and `run` read a run's data folder and need the repository.)

The encoders are standard ONNX files and `heads.json` is plain numbers (a score
is `x @ W.T + b`, then a softmax), so the model also runs outside Python: in a
browser or Node with onnxruntime-web, or in any language with an ONNX runtime.
To match it there: a cut-out (a picture with a see-through background) is
cropped to its vehicle and put on white (`vision.load`); the picture is padded
to a square of CLIP's mean colour, 224 pixels a side, and normalised each
encoder's way (`vision.prep`); SigLIP's pooled output and DINOv2's class token
with its patches' mean, each of unit length, go side by side (`vision.Encoders`);
the colour head also takes the picture's middle as a Lab histogram
(`heads.colour_hist`); side reads the picture and its mirror
(`heads.side_proba`).

## On a phone

`web/` is the model as a web page that runs in the phone's browser: nothing is
installed and the pictures never leave the phone. It uses the encoders' 4-bit
copies (105 MB together, downloaded once and kept by the browser) with
onnxruntime-web, and heads trained for them (`web/heads.json`). Its JavaScript
repeats `vision.load`, `vision.prep`, `vision.Encoders`, `heads.colour_hist`,
`heads.read` and `heads.judge` step for step (Pillow's resampling included), and
`web/check.py` holds it to them in a real browser: the picture handed to the
encoder is the same size as Python's and every 97th value of it within 0.00001,
each encoder's numbers are this machine's (cosine), and on the page's own numbers
Python's heads give the page's every answer. Its check here, on 12 of the run's
vehicles (24 pictures and 13 build checks, the page's example among them): every
answer Python's, each encoder's numbers this machine's (cosine 1.0000), about 8 s a
picture in a headless browser with no graphics card. The phone's heads score as
the full model's to a point or two: kind 98.4%, side 100%, colour 72.6% (86.7%
its family or the next shade), match 0.95, no vehicle read as none on all 1,684
photos of none, the shape check flagging 11% of the builds the reviewers passed
(`web/heads.json`'s card). A build to check can be marked a stand-in on the page.

To make it again after training:

    python3 pipeline/realcar/ai/train.py --encoder siglip-b16-q4,dinov2-base-q4 --extra EXTRA \
        --out pipeline/realcar/ai/web/heads.json --review /tmp/phone_review.json
    python3 pipeline/realcar/ai/web/build.py SITE                           # the page with its heads and example
    python3 pipeline/realcar/ai/web/check.py SITE                           # it answers as Python does

(`web/features.py SITE features.npz` reads every picture with the page itself,
for heads trained on the page's own numbers, `train.py --features`, when the
browser's engine strays from this machine's.) Then publish `SITE`'s files
together on any web host (or as a claude.ai artifact): the page, `heads.json`,
the encoders' pieces (`encoder.N.txt`, `encoder1.N.txt`: base64 text under 15 MB
each, as an artifact serves text and media, not raw bytes), onnxruntime's
`.wasm` and the example's two pictures.

## Train it again

After a review round (new labels, new verdicts, rebuilt builds):

    pip install scikit-learn opencv-python-headless      # (the run's paint families come with OpenCV's colour code)
    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/train.py --extra EXTRA

reads every label in `$F1K_HOME` (`dataset.py` says which; `kind_by_eye.json`
corrects the list's class where the photo shows the other kind) and every
picture (about 20 minutes on 4 CPUs the first time, and SigLIP's text half, 110 MB,
fetched once and pinned, for the colour words; kept in a cache by encoder
and feature version, so later runs read only new pictures), answers each fold
with heads trained on the others, sets the thresholds from those answers,
writes them as the run's second opinion, then trains the heads on all and
writes `heads.json`. A vehicle keeps its fold when others are added, so rounds
compare. A verdict is used only on the build and photo it was made on.

`EXTRA` is a folder of photos from outside the run, made once:

    GLBMACHINE_HOME=/path/to/home python3 pipeline/realcar/ai/extra/flickr.py EXTRA    # the index's vehicle photos
    pip install tokenizers; python3 pipeline/realcar/ai/extra/qa.py EXTRA              # which to train on

## What it is not

- **Not a replacement for the review.** The match sees whether a build looks like
  the photo's model; it does not see a wrong door count, a small error in
  proportion, a roof or a broken part. Use it to put the builds to look at
  first at the top, and to catch the stand-ins furthest from their car.
- **It learned one run**: 936 vehicles, labelled by agents with gold checks, and
  Flickr photos labelled by their photographers' words. A label is sometimes
  wrong, so is a score.
- **Part of a vehicle is a vehicle.** An engine bay, a wheel close-up or an
  interior reads as a vehicle, and still gets a kind, a side and a colour.
- **Colour** is still the weakest answer, at 78%: silver against white and grey
  against dark grey or silver are its usual slips, and five families have four
  examples or fewer (purple, olive, bronze, copper, beige), so it seldom answers
  them. In a photo these are often a toss-up for a person too.
- **Side** is the way a side or three-quarter view points; a photo from straight
  ahead or behind has no answer worth reading.
- **Kind**: a car and a van that share a body (a Berlingo, a Nemo, a Vito) are
  told apart by what the picture shows, not by how they are registered.

## Files

| File | What it does |
|---|---|
| `vision.py` | the image encoders: fetch, check, read a picture, numbers side by side |
| `heads.py` | the trained heads: colour histogram, fit, run, save; a photo's answers; a build's check |
| `words.py` | each paint family's words as SigLIP reads them, for training the colour head |
| `dataset.py` | the run's labels as training examples, the folds, the extra photos |
| `kind_by_eye.json` | the photos whose kind, looked at, is not the list's class |
| `train.py` | trains, answers every fold held out, sets the thresholds, writes `heads.json` and `ai_review.json` |
| `predict.py` | the model for the tool and for code: photo, check, key, run |
| `bundle.py` | the model as one folder and zip, encoders included |
| `heads.json` | the trained weights and their card (scores, data, encoders, thresholds) |
| `extra/flickr.py`, `extra/qa.py` | photos from outside the run: the index's, and which to train on |
| `web/index.html` | the phone page: the model in the browser |
| `web/heads.json` | the phone page's heads, trained on the 4-bit encoders' numbers |
| `web/build.py`, `web/features.py`, `web/check.py` | the page's folder; every picture read by the page; the page held to Python |
| `web/check_page.cjs`, `web/features.cjs` | the browser side of those two (Playwright) |
| `test_ai.py` | `python3 -m pytest pipeline/realcar/ai/test_ai.py -q` |
| `try_it.py` | anyone's own check: unseen photos, controls, a blind test |
| `train_pictures.json` | the looks of every training picture (`vision.dhash`), to check a photo was not trained on |
