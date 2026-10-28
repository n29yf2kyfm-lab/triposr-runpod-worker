"""bundle.py: the trained model as one folder (and zip) to take anywhere, encoder included.

    python3 pipeline/realcar/ai/bundle.py OUT_DIR [--int8]

OUT_DIR gets the code that runs the model (vision.py, heads.py, predict.py),
the trained heads (heads.json), the image encoder (clip-b32.onnx, about
350 MB; --int8: the 90 MB quantised one, a little less exact), a
requirements.txt and the README; and OUT_DIR.zip beside it. Unzipped
anywhere with Python 3.9+:

    pip install -r requirements.txt
    python3 predict.py photo car.jpg

needs no download and no network.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import vision  # noqa: E402

CODE = ("vision.py", "heads.py", "predict.py", "heads.json", "README.md")
REQUIREMENTS = "numpy>=1.24\npillow>=9\nonnxruntime>=1.16\n"


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    out, int8 = sys.argv[1], "--int8" in sys.argv[2:]
    os.makedirs(out, exist_ok=True)
    for f in CODE:
        shutil.copy2(os.path.join(HERE, f), os.path.join(out, f))
    enc = vision.fetch("clip-b32-int8" if int8 else "clip-b32")
    # the bundle's encoder sits beside vision.py under the name fetch() looks for
    shutil.copy2(os.path.realpath(enc), os.path.join(out, "clip-b32.onnx"))
    with open(os.path.join(out, "requirements.txt"), "w") as fh:
        fh.write(REQUIREMENTS)
    z = shutil.make_archive(out.rstrip("/"), "zip", out)
    print(out, z, f"{os.path.getsize(z) / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
