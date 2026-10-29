"""bundle.py: the trained model as one folder (and zip) to take anywhere, encoder included.

    python3 pipeline/realcar/ai/bundle.py OUT_DIR

OUT_DIR gets the code that runs the model (vision.py, heads.py, predict.py),
the trained heads (heads.json), the image encoders the heads' card names
(siglip-b16.onnx and dinov2-base.onnx, about 720 MB together), a
requirements.txt and the README; and OUT_DIR.zip beside it.
Unzipped anywhere with Python 3.9+:

    pip install -r requirements.txt
    python3 predict.py photo car.jpg
    python3 predict.py check car.jpg build.png

needs no download and no network. (`key` and `run` read a run's data folder
and need the repository.)
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import vision  # noqa: E402

CODE = ("vision.py", "heads.py", "predict.py", "heads.json", "README.md")
REQUIREMENTS = "numpy>=1.24\npillow>=9\nonnxruntime>=1.16\n"


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    out = sys.argv[1].rstrip("/")
    os.makedirs(out, exist_ok=True)
    for f in CODE:
        shutil.copy2(os.path.join(HERE, f), os.path.join(out, f))
    # beside vision.py, under the names fetch() looks for there
    card = json.load(open(os.path.join(HERE, "heads.json")))["card"]
    names = [e["name"] for e in card.get("encoders", [])] or vision.DEFAULT_ENCODERS
    for name in names:
        shutil.copy2(os.path.realpath(vision.fetch(name)), os.path.join(out, name + ".onnx"))
    with open(os.path.join(out, "requirements.txt"), "w") as fh:
        fh.write(REQUIREMENTS)
    z = shutil.make_archive(out, "zip", out)
    print(out, z, f"{os.path.getsize(z) / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
