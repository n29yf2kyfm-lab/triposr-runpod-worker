# Vehicle AI: a trained model for the car machine's photos and builds

A real trained model, not written rules: it learned from the run's own answers
(1,647 pictures: 936 photos and 711 builds, named by the colour, side and
review agents, with their hand-checked gold items, and the machine's own record
of which builds are stand-ins) on top of CLIP, an image model OpenAI trained on
400 million pictures. It answers four questions the review agents answer:

| Question | Of | Answers |
|---|---|---|
| **kind** | a photo or a build | car, van, motorbike |
| **side** | a photo or a build | left, right (the way the vehicle points) |
| **colour** | a photo or a build | one of 29 of the review's paint families (gold and lilac had no example), with the paint the machine builds it in |
| **match** | a build beside its photo | how likely the build is the photo's vehicle (its shape, not its paint) |

and `check` puts them together into a second opinion on a build: what looks wrong
(`flags`), and `look` or `ok`.

## How good it is

Every vehicle is in one of five folds; vehicles that share a picture (twins
with one photo, a van and its car version with one build: 88 pictures) share a
fold. Each fold was answered by heads trained on the other four, so every
number here is on photos and builds the model had not seen (`heads.json`'s
`card` keeps them all):

| Question | On | Right | Always the commonest answer | |
|---|---|---|---|---|
| kind | 936 photos | 94.0% | 63.9% (car) | every mistake a car read as a van or a van as a car |
| | 722 photos of cars and vans | 92.2% | 82.8% (car) | the motorbikes left out: they are the easy ones |
| | 711 builds | 93.0% | 84.0% (car) | |
| side | 711 photos | 95.1% | 54.0% (right) | |
| | 711 builds | 99.7% | 54.0% (right) | |
| colour | 722 photos | 67.2% | 28.7% (white) | 83.2% its family or the next shade (always white: 49.6%); 87.5% in its top 3. The measurer it can replace (`photo_paint.py` before the colour agents) named 41% |
| | 711 builds | 92.3% | 28.3% (white) | 96.6% its family or the next shade |
| match | 650 builds with their own photo, 3,555 with other vehicles' | 0.88 | 0.50 | the chance a build scores higher with its own photo than with another vehicle's (AUC; 0.5 is a coin, 1 is never wrong) |

The next shade is a family within 25 of it in Lab and in its group (white to
black as one group, the rest by hue): grey for dark grey, silver for white, not
aqua for white. Until 28 October it had no groups and counted 51 pairs, white
and aqua and dark grey and dark blue among them (found by the audit, below); it
counts 17, and photos' colour to the next shade fell from 89.2% to 83.2%.

**Sure.** Each head's threshold is the lowest `p` from which photos were right
99 times in 100, held out. That is set and scored on the same answers, so set
on one half of the vehicles (by fold) and tried on the other: answers that sure
were right 98% and 100% of the time for kind, 97.5% and 98.9% for side, 96.8%
and 98.6% for colour (its family or the next shade). Read the 99 as about 98.

Some settings (the heads' `C`, `REAL_WRONG`, `SURE_RIGHT`) were picked after
looking at these held-out scores: they may flatter them a little.

A correction: until 28 October the folds went by key alone, and 75 shared
pictures sat in two folds, so some vehicles were scored on a picture the heads
had trained on (found by the code's audit, below). Fixed, photos' colour fell
from 70.4% to 67.2%, and the shape check's catch of the reviewers' wrong builds
from 60% to 40%: the numbers here are the fixed ones.

The match against what the run knows was wrong, beside the encoder untrained
(the cosine of the photo's and the build's embeddings, its threshold set the same way):

| | AUC | Flagged (below 0.48) | Untrained: AUC, flagged |
|---|---|---|---|
| 251 builds of the photo's own model, against 458 stand-ins (another model's body reshaped) | 0.76 | 10% of own-model builds (the threshold is set so), 40% of stand-ins | 0.72, 29% of stand-ins |
| the reviewers' 107 passed builds, against the 10 they found the wrong shape on the build there now | 0.64 | 4 of the 10 | 0.43, 2 of the 10 |
| ... against the 61 whose last verdict named a shape fault (on that build or an earlier one) | 0.64 | 38% | 0.52, 16% |

Training adds to CLIP here, but not much on the reviewers' wrong builds, and
10 is a small number. 64% of the builds are stand-ins. The threshold set on one
half of the vehicles and tried on the other flags 9% and 12% of own-model
builds, 46% and 37% of stand-ins.

The reviewers' passed builds are flagged 27% of the time: most of those are
stand-ins, which they pass when the body is the right sort.

**By eye.** Of the builds the held-out answers flagged as the wrong shape, every
fifth (43) was looked at photo beside build: 39 were another model or another
generation (a Kia Rio built as a Golf, a Rover 25 as a Punto, a Kia Stinger as a
Genesis G70, a Mini Paceman as a BMW X1) and 4 false alarms, all builds of the
photo's own model (a Scénic, a Fiesta, a GT-R, a 300C). That was before the
correction; after it 207 are flagged, 35 of those 43 among them (31 another
model, the same 4 false alarms). Of the 207, 182 are stand-ins; the reviewers'
verdict on the build there now was ok on 29.

The run's labels are the agents' answers checked by gold items, not certain
truth: a "mistake" is sometimes the label's.

## Try it yourself

`try_it.py` checks the model with nothing of this run's: paste it into a Google
Colab cell (works from a phone's browser) or run `python3 try_it.py` anywhere;
about 3 minutes. It downloads the code and weights from GitHub at a pinned
commit (refusing any file whose SHA-256 is not the one it prints), and then:

- checks its 29 Wikimedia test photos were not trained on: each against the
  looks (`vision.dhash`) of every training picture, published in
  `train_pictures.json`
- scores the answers against a person's, strictly (the one answer a person
  gives) and leniently (a fair second: a Multivan is a van but registered as a
  car), beside random guessing and always giving the commonest answer
- runs the same code with the trained weights swapped for random ones: it falls
  to guessing, so the skill is in the training, not in the code
- recolours the photos on the spot (red and blue swapped; grey) and sees whether
  the paint read moves with them
- shows photos picked at random as it runs, that nobody chose, and asks you what
  you see before it shows the model's answer (`BLIND`)

The mirror is not a check: the side reading averages a picture with its mirror,
so a mirrored picture always reads the other way.

Its run here (28 October, a new Python environment, 2 min 50 s with the
download): no test photo within 61 bits of a training picture; kind 27 of 29
strictly, 29 leniently (always "car": 20); side 28 of 29 (always "left": 19);
colour 20 of 29 strictly, 22 leniently (always "white": 9). With random weights:
kind 9, side 10, colour 1. Red and blue swapped, the paint moved with it on 3 of
the 7 coloured cars (a weakness: a swapped red reads dark red or white, a
swapped dark blue black); turned grey, the colour went on 7 of 7. Random noise
still reads as a car (50%).

## Checked by other AIs

Three other models (Claude Haiku, Sonnet and Fable) ran `try_it.py` from a
fresh copy and audited the code without being told what to find. All three
found a real model (Fable: the same code with random weights scores at chance).
They also found what was overstated, all of it fixed since: the mirror check
cannot fail; a model always answering "silver" passed the grey check; three
hand answers had been loosened ("car or van") after the model missed them; the
colour swap was scored by a swatch's tint; the training pictures were not
published, so "never trained on" could not be checked; and the leak above.
Sonnet's second pass found more, fixed too: the next shade counted 51 pairs
(white and aqua among them); no score stood beside a baseline (always "car" is
right on 83% of cars and vans); the 99-in-100 threshold was set and scored on
the same answers; the settings tuned on held-out scores were not said; and the
phone page's example is a vehicle the model was trained on (the page now says so).

## Use it

    pip install numpy pillow onnxruntime
    python3 pipeline/realcar/ai/predict.py photo car.jpg [more.jpg ...]
    python3 pipeline/realcar/ai/predict.py check car.jpg build.png
    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/predict.py key car-ford-fiesta
    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/predict.py run     # every build: $F1K_HOME/ai_review.json

The first run fetches the image encoder (350 MB, pinned and checked by its
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
are rare (2 of 711) and the shape flag is the one that finds things.

`run` is the run's second opinion. `train.py` leaves every build's held-out
answer in `ai_review.json`; `run` keeps those while the build and photo are the
ones answered, checks with the final heads only a build or photo that is newer,
and lists the flagged builds the reviewers passed (their verdict counts only
on the build and photo it was made on). About 0.2 s a picture on one CPU core
(a check reads two); no GPU, no PyTorch.

## Take it with you

    python3 pipeline/realcar/ai/bundle.py vehicle-ai

makes `vehicle-ai/` and `vehicle-ai.zip` (about 210 MB): the code, the trained
heads and the encoder in one folder that runs anywhere with Python 3.9+, offline:

    cd vehicle-ai && pip install -r requirements.txt && python3 predict.py photo car.jpg

(`key` and `run` read a run's data folder and need the repository.)

The encoder is a standard ONNX file and `heads.json` is plain numbers (a score
is `x @ W.T + b`, then a softmax), so the model also runs outside Python: in a
browser or Node with onnxruntime-web, or in any language with an ONNX runtime.
To match it there: a cut-out (a picture with a see-through background) is
cropped to its vehicle and put on white (`vision.load`); the picture is padded
to a square of CLIP's mean colour, 224 pixels a side, normalised
(`vision.prep`); the colour head also takes the picture's middle as a Lab
histogram (`heads.colour_hist`); side reads the picture and its mirror
(`heads.side_proba`).

## On a phone

`web/` is the model as a web page that runs in the phone's browser: nothing is
installed and the pictures never leave the phone. It uses the encoder's 8-bit
copy (90 MB, downloaded once and kept by the browser) with onnxruntime-web, and
heads trained for it (`web/heads.json`). Its JavaScript repeats `vision.load`,
`vision.prep`, `heads.colour_hist`, `heads.read` and `heads.judge` step for step
(Pillow's resampling included), and `web/check.py` holds it to them in a real
browser: the picture handed to the encoder is the same size as Python's and
every 97th value of it within 0.00001 (the page normalises in one step, Python
in three, so the last bit of rounding differs), and on the page's own numbers
Python's heads give the page's every answer. It does not show the page's
answers are right: on the 29 unseen photos of `try_it.py` the page itself, in
Chromium, scores kind 28 of 29, side 27 of 29 and colour 18 of 29 strictly (20
leniently).

The browser's engine does the 8-bit arithmetic a little otherwise than
onnxruntime here (its numbers 0.99 alike), so the page's heads are trained on the
page's own reading of every picture (`web/features.py`). WebAssembly's
arithmetic is specified to be the same on every device, so a phone should read
as Chromium does here; not checked on a phone. Held out, as above, the page reads kind on 93.7% of
photos, side on 90.9% of photos and 91.4% of builds (the full model 95.1% and
99.7%: the 8-bit encoder keeps less of which way a vehicle points), colour on
66.9% (83.2% to the next shade) and builds' colour on 91.7%; it tells a build's
own photo from another vehicle's at an AUC of 0.86 and flags 36.5% of the
stand-ins, but only 1 of the reviewers' 10 wrong-shape builds (the full model 4,
the untrained encoder 2). For checking builds, use the full model.

To make it again after training:

    python3 pipeline/realcar/ai/web/build.py SITE --example ""              # the page, to read the pictures with
    python3 pipeline/realcar/ai/web/features.py SITE features.npz           # every picture read by the page (Chromium)
    python3 pipeline/realcar/ai/train.py --encoder INT8.onnx --features features.npz \
        --out pipeline/realcar/ai/web/heads.json --review /tmp/phone_review.json
    python3 pipeline/realcar/ai/web/build.py SITE --features features.npz   # the page with its heads and example
    python3 pipeline/realcar/ai/web/check.py SITE                          # it answers as Python does

then publish `SITE`'s files together on any web host (or as a claude.ai
artifact): the page, `heads.json`, the encoder's pieces (`encoder.N.txt`, base64
text under 15 MB each: an artifact serves text and media, not raw bytes),
onnxruntime's `.wasm` and the example's two pictures.

## Train it again

After a review round (new labels, new verdicts, rebuilt builds):

    pip install scikit-learn opencv-python-headless      # (the run's paint families come with OpenCV's colour code)
    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/train.py

reads every label in `$F1K_HOME` (`dataset.py` says which) and every picture
(about 5 minutes on 4 CPUs the first time; kept in a cache by encoder and
feature version, so later runs read only new pictures), answers each fold with
heads trained on the others, sets the thresholds from those answers, writes
them as the run's second opinion, then trains the heads on all and writes
`heads.json`. A vehicle keeps its fold when others are added, so rounds compare.
A verdict is used only on the build and photo it was made on.

## What it is not

- **Not a replacement for the review.** The match sees whether a build looks like
  the photo's model; it does not see a wrong door count, a small error in
  proportion, a roof or a broken part. Six of the reviewers' ten wrong-shape
  builds pass it. Use it to put the builds to look at first at the top, and to
  catch the stand-ins furthest from their car.
- **It learned one run**: 936 vehicles, labelled by agents with gold checks. A
  label is sometimes wrong, so is a score.
- **It does not know a vehicle from no vehicle.** A wheel close-up or an interior
  still gets a kind, a side and a colour.
- **Colour**: five families have four examples or fewer (purple, olive, beige,
  bronze, copper); it seldom answers them. Silver against white and grey against
  dark grey are its usual slips.
- **Side** is the way a side or three-quarter view points; a photo from straight
  ahead or behind has no answer worth reading. Its `p` is seldom above 0.8 even
  when right (the picture and its mirror are averaged).
- **Kind**: cars and vans that share a body (a Berlingo, a Nemo, a Vito) are where
  it errs, as the target list does. On cars and vans alone it beats always saying
  "car" by less than ten points (92.2% against 82.8%).

## Files

| File | What it does |
|---|---|
| `vision.py` | the image encoder: fetch, check, read a picture, 512 numbers |
| `heads.py` | the trained heads: colour histogram, fit, run, save; a photo's answers; a build's check |
| `dataset.py` | the run's labels as training examples, the folds |
| `train.py` | trains, answers every fold held out, sets the thresholds, writes `heads.json` and `ai_review.json` |
| `predict.py` | the model for the tool and for code: photo, check, key, run |
| `bundle.py` | the model as one folder and zip, encoder included |
| `heads.json` | the trained weights and their card (scores, data, encoder, thresholds) |
| `web/index.html` | the phone page: the model in the browser |
| `web/heads.json` | the phone page's heads, trained on its own reading (8-bit encoder) |
| `web/build.py`, `web/features.py`, `web/check.py` | the page's folder; every picture read by the page; the page held to Python |
| `web/check_page.cjs`, `web/features.cjs` | the browser side of those two (Playwright) |
| `test_ai.py` | `python3 -m pytest pipeline/realcar/ai/test_ai.py -q` |
| `try_it.py` | anyone's own check: unseen photos, controls, a blind test |
| `train_pictures.json` | the looks of every training picture (`vision.dhash`), to check a photo was not trained on |
