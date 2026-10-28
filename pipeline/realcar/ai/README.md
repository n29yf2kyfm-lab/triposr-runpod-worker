# Vehicle AI: a trained model for the car machine's photos and builds

A real trained model, not written rules: it learned from the run's own answers
(1,647 pictures: 936 photos and 711 builds, named by the colour, side and
review agents, with their hand-checked gold items) on top of CLIP, an image model OpenAI trained on
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

Scores on vehicles the model was never trained on (a fifth of the run, held out
by a fixed draw; `heads.json`'s `card` keeps every number):

| Question | On | Right | |
|---|---|---|---|
| kind | 187 photos | 92.5% | every mistake a car read as a van or a van as a car |
| | 147 builds | 94.6% | |
| side | 147 photos | 97.3% | |
| | 147 builds | 98.6% | |
| colour | 150 photos | 73.3% | 94.0% its family or the next shade (grey for dark grey, silver for white); 90.0% in its top 3. The measurer it can replace (`photo_paint.py` before the colour agents) named 41.3% |
| | 147 builds | 89.1% | 97.3% its family or the next shade |
| match | 131 builds with their own photo, 735 with other vehicles' | 0.87 | the chance a build scores higher with its own photo than another vehicle's build does (AUC) |

The match against what the run knows was wrong (every build scored by heads that
had not seen it, five rounds of a fifth each):

| | AUC | Below the threshold (0.47) |
|---|---|---|
| 251 builds of the photo's own model, against 458 stand-ins (another model's body reshaped) | 0.74 | 10% of own-model builds, 34% of stand-ins |
| the reviewers' 107 passed builds, against the 10 they found the wrong shape on the build there now | 0.66 | 5 of the 10 |
| ... against the 61 they ever found the wrong shape (some fixed since) | 0.72 | 59% |

And by eye: `predict.py run` over the run's 711 builds flagged 124 as the wrong
shape (a run over vehicles the model was trained on). Of every third of them, 42,
looked at photo beside build: 38 are stand-ins wearing another model's body (a
Caravelle built as an ID Buzz, a Mini Clubman as a BMW 3 Series Touring, a Saab
9-5 as an Audi A6, a Citroën 2CV as a 1964 Skyline), 3 are builds the reviewers
had failed for another fault (purple glass, grey bumpers), and 1 is a false alarm
(a Mondeo estate). The reviewers' last verdict was ok on 59 of the 124.

These are the run's labels, which are the agents' answers checked by gold items,
not certain truth: a "mistake" is sometimes the label's.

## Use it

    pip install numpy pillow onnxruntime
    python3 pipeline/realcar/ai/predict.py photo car.jpg
    python3 pipeline/realcar/ai/predict.py check car.jpg build.png
    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/predict.py key car-ford-fiesta
    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/predict.py run     # every build: $F1K_HOME/ai_review.json

The first run fetches the image encoder (350 MB, pinned and checked by its
SHA-256) into `$VEHICLE_AI_HOME` (default `~/.cache/vehicle-ai`). From Python:

```python
import sys; sys.path.insert(0, "pipeline/realcar/ai")
from predict import VehicleAI
ai = VehicleAI()
ai.photo("car.jpg")
# {"kind": {"answer": "car", "p": 0.99}, "side": {"answer": "left", "p": 0.97},
#  "colour": {"answer": "white", "p": 0.71, "paint": "#eeefed", "top3": [...]}}
ai.check("car.jpg", "build.png")
# {"photo": {...}, "build": {...}, "match": 0.91, "flags": [], "answer": "ok"}
```

About 0.2 s a picture on one CPU core (a check reads two); no GPU, no PyTorch.

## Take it with you

    python3 pipeline/realcar/ai/bundle.py vehicle-ai

makes `vehicle-ai/` and `vehicle-ai.zip`: the code, the trained heads and the
encoder in one folder that runs anywhere with Python 3.9+, offline:

    cd vehicle-ai && pip install -r requirements.txt && python3 predict.py photo car.jpg

The encoder is a standard ONNX file and `heads.json` is plain numbers (a score
is `x @ W.T + b`, then a softmax), so the model also runs outside Python: in a
browser or Node with onnxruntime-web, or in any language with an ONNX runtime.
The encoder's input is the picture padded to a square of CLIP's mean colour, 224
pixels a side, normalised (`vision.prep`); the colour head also takes the
picture's middle as a Lab histogram (`heads.colour_hist`).

## Train it again

After a review round (new labels, new verdicts, rebuilt builds):

    pip install scikit-learn
    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/train.py

reads every label in `$F1K_HOME` (`dataset.py` says which), reads every picture
once (about 5 minutes on 4 CPUs; kept in a cache, so a second run takes
under a minute), trains the heads without the held-out vehicles, scores them on those,
then trains them on all and writes `heads.json`. A verdict is only used on the
build and photo it was made on; a build since rebuilt is not.

## What it is not

- **Not a replacement for the review.** The match sees whether a build looks like
  the photo's model; it does not see a wrong door count, a small error in
  proportion, a roof or a broken part. Half of the reviewers' wrong-shape builds
  pass it. Use it to put the builds to look at first at the top, and to catch the
  stand-ins furthest from their car.
- **It learned one run**: 936 vehicles, labelled by agents with gold checks. A
  label is sometimes wrong, so is a score.
- **Colour**: five families have four examples or fewer (purple, olive, beige,
  bronze, copper); it seldom answers them. Silver against white and grey against
  dark grey are its usual slips.
- **Side** is the way a side or three-quarter view points; a photo from straight
  ahead or behind has no answer worth reading.
- **Kind**: cars and vans that share a body (a Berlingo, a Nemo, a Bipper) are where it errs.
- In `check`, the colour and side flags seldom fire on this run's builds: they are
  built in the photo's paint and pictured from its side. They are for builds that
  are not.
- **The int8 encoder** (`bundle.py --int8`, 90 MB instead of 350 MB) reads side
  worse: 89% of photos, held out. Colour, kind and match stay within about a point.

## Files

| File | What it does |
|---|---|
| `vision.py` | the image encoder: fetch, check, read a picture, 512 numbers |
| `heads.py` | the trained heads: colour histogram, fit, run, save |
| `dataset.py` | the run's labels as training examples, the held-out draw |
| `train.py` | trains, scores on the held-out vehicles, writes `heads.json` |
| `predict.py` | the model for the tool and for code: photo, check, key, run |
| `bundle.py` | the model as one folder and zip, encoder included |
| `heads.json` | the trained weights and their card (scores, data, encoder) |
| `test_ai.py` | `python3 -m pytest pipeline/realcar/ai/test_ai.py -q` |
