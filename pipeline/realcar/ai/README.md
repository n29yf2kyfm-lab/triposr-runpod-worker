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

Every vehicle is in one of five folds (by its key). Each fold was answered by
heads trained on the other four, so every number here is on photos and builds
the model had not seen (`heads.json`'s `card` keeps them all):

| Question | On | Right | |
|---|---|---|---|
| kind | 936 photos | 92.7% | every mistake a car read as a van or a van as a car |
| | 711 builds | 92.7% | |
| side | 711 photos | 95.2% | |
| | 711 builds | 99.6% | |
| colour | 722 photos | 70.4% | 90.2% its family or the next shade (grey for dark grey, silver for white); 88.0% in its top 3. The measurer it can replace (`photo_paint.py` before the colour agents) named 41% |
| | 711 builds | 92.3% | 97.7% its family or the next shade |
| match | 650 builds with their own photo, 3,555 with other vehicles' | 0.89 | the chance a build scores higher with its own photo than with another vehicle's (AUC; 0.5 is a coin, 1 is never wrong) |

The match against what the run knows was wrong:

| | AUC | Flagged (below 0.49) |
|---|---|---|
| 251 builds of the photo's own model, against 458 stand-ins (another model's body reshaped) | 0.76 | 10% of own-model builds (the threshold is set so), 42% of stand-ins |
| the reviewers' 107 passed builds, against the 10 they found the wrong shape on the build there now | 0.71 | 6 of the 10 |
| ... against the 61 whose last verdict named a shape fault (on that build or an earlier one) | 0.76 | 66% |

The reviewers' passed builds are flagged 27% of the time: most of those are
stand-ins, which they pass when the body is the right sort.

**By eye.** Of the 217 builds the held-out answers flag as the wrong shape, every
fifth (43) was looked at photo beside build: 39 are another model or another
generation (a Kia Rio built as a Golf, a Rover 25 as a Punto, a Kia Stinger as a
Genesis G70, a Mini Paceman as a BMW X1); 4 are false alarms, all builds of the
photo's own model (a Scénic, a Fiesta, a GT-R, a 300C). Of the 217, 192 are
stand-ins; the reviewers' verdict on the build there now was ok on 29.

**On photos from outside the run.** 34 Wikimedia photos of the run's vehicles
that it never trained on, named by hand: kind 31 of 34 (the three misses are a
California, a Multivan and a Master the target list calls cars, read as vans),
side 30 of 33 (a wheel close-up left out), colour 26 of 32 (counting a shade
either name would fit).

The run's labels are the agents' answers checked by gold items, not certain
truth: a "mistake" is sometimes the label's.

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
browser: the picture handed to the encoder is Python's to the last bit of
rounding, and on the page's own numbers Python's heads give the page's every answer.

The browser's engine does the 8-bit arithmetic a little otherwise than
onnxruntime here (its numbers 0.99 alike), so the page's heads are trained on the
page's own reading of every picture (`web/features.py`); WebAssembly gives the
same numbers on every phone. Held out, as above, the page reads kind on 92.7% of
photos, side on 90.6% (the full model 95.2%: the 8-bit encoder keeps less of
which way a vehicle points), colour on 69.9% (90.0% to the next shade) and
builds' colour on 91.8%; it tells a build's own photo from another vehicle's at
an AUC of 0.87 and flags 40% of the stand-ins.

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

    pip install scikit-learn
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
  proportion, a roof or a broken part. A third of the reviewers' wrong-shape
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
  it errs, as the target list does.

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
