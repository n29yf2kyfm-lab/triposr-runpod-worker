"""Fine-tune RF-DETR on the prepared damage dataset and export ONNX for CPU.

Runs on a rented GPU once; the exported model then serves free on CPU via
DAMAGE_BACKEND=detector. RF-DETR is Apache-2.0, which is the whole point — see
README.md for why the AGPL YOLO weights and the CarDD-derived models cannot be
used in a commercial product.

    python train_detector.py --data ./prepared --out ./runs --epochs 12

The script deliberately ends by measuring CPU latency on the exported ONNX. The
entire justification for this backend is "~0.1-0.4 s on CPU instead of 5-20 s
via a hosted VLM", and an unverified performance claim is just a hope.
"""
import argparse
import json
import os
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="output of prepare_data.py")
    ap.add_argument("--out", default="./runs")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--resolution", type=int, default=560)
    ap.add_argument("--num-workers", type=int, default=4,
                    help="DataLoader workers; each builds its own COCO index, "
                         "so the library default can exhaust RAM on a corpus "
                         "this size")
    ap.add_argument("--model", default="base", choices=["base", "large"])
    ap.add_argument("--skip-train", action="store_true",
                    help="export/benchmark an existing checkpoint only")
    args = ap.parse_args()

    labels_path = os.path.join(args.data, "labels.txt")
    labels = open(labels_path).read().strip().split(",")
    # labels[0] is the reserved placeholder; real classes start at index 1.
    print(f"labels ({len(labels)}): {labels}")
    os.makedirs(args.out, exist_ok=True)

    from rfdetr import RFDETRBase, RFDETRLarge
    Model = RFDETRBase if args.model == "base" else RFDETRLarge
    model = Model(resolution=args.resolution)

    if not args.skip_train:
        t0 = time.time()
        # num_workers IS CAPPED DELIBERATELY. Each DataLoader worker builds
        # its own pycocotools index, and the train split here is 369,762
        # images with 862,550 boxes — roughly 170MB of JSON that inflates to
        # gigabytes of Python objects per process. At the library default that
        # is tens of gigabytes before a single batch is read, which is exactly
        # how the materialise stage wedged: no error, no output, just a box
        # thrashing. Four workers keep the GPU fed at this batch size.
        model.train(
            dataset_dir=args.data,
            epochs=args.epochs,
            batch_size=args.batch_size,
            grad_accum_steps=args.grad_accum,
            lr=args.lr,
            output_dir=args.out,
            num_workers=args.num_workers,
        )
        print(f"\ntrained in {(time.time() - t0) / 60:.1f} min")

    # --- export ONNX (this is the artefact the worker actually runs) --------
    print("\nexporting ONNX ...")
    model.export(output_dir=args.out)
    onnx_path = _find_onnx(args.out)
    print(f"onnx: {onnx_path} "
          f"({os.path.getsize(onnx_path) / 1e6:.1f} MB)" if onnx_path
          else "onnx: NOT FOUND")

    # --- verify the claim that made us choose this architecture ------------
    if onnx_path:
        _benchmark_cpu(onnx_path, args.resolution)

    with open(os.path.join(args.out, "deploy.json"), "w") as f:
        json.dump({
            "DAMAGE_BACKEND": "detector",
            "DAMAGE_DETECTOR_MODEL": os.path.basename(onnx_path or ""),
            "DAMAGE_DETECTOR_LABELS": ",".join(labels),
            "DAMAGE_DETECTOR_SIZE": args.resolution,
        }, f, indent=2)
    print(f"\nwrote {args.out}/deploy.json — these are the endpoint env vars.")


def _find_onnx(root):
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if fn.endswith(".onnx"):
                return os.path.join(dirpath, fn)
    return None


def _benchmark_cpu(onnx_path, resolution, runs=10):
    """Measure real CPU latency — the number this whole backend is sold on."""
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError:
        print("(onnxruntime not installed here; benchmark skipped)")
        return
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    x = np.random.rand(1, 3, resolution, resolution).astype(np.float32)
    sess.run(None, {name: x})                      # warm up
    t0 = time.time()
    for _ in range(runs):
        sess.run(None, {name: x})
    per = (time.time() - t0) / runs
    print(f"\nCPU latency: {per * 1000:.0f} ms/image over {runs} runs "
          f"({os.cpu_count()} cores)")
    print("compare: hosted VLM 5-20 s/scan, frontier VLM 10-20 s/scan")


if __name__ == "__main__":
    main()
