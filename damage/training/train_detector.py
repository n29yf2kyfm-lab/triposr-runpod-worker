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


def _cudnn_probe():
    """Disable cuDNN in THIS process if this host's cuDNN cannot initialise.

    train.sh runs a GPU preflight that, on the v16 host, hit
    CUDNN_STATUS_NOT_INITIALIZED three times, proved the GPU could still
    convolve with cuDNN off, set torch.backends.cudnn.enabled = False -- and
    then exited, because it is a separate python heredoc. Nothing carried
    over. Training started here with cuDNN enabled again and would have died
    on its first convolution, an hour of setup and materialise after launch,
    with the preflight having correctly diagnosed the exact problem.

    So the process that trains does its own probe. A tiny conv on the device;
    if cuDNN raises, fall back to native kernels for the run. Slower, but a
    slow run that finishes beats a fast one that never starts. The env var is
    for forcing the fallback when a host is known to be bad.
    """
    import torch
    if os.environ.get("DAMAGE_CUDNN_DISABLE") == "1":
        torch.backends.cudnn.enabled = False
        print("cuDNN DISABLED by DAMAGE_CUDNN_DISABLE=1")
        return
    if not torch.cuda.is_available():
        return
    try:
        x = torch.randn(1, 3, 32, 32, device="cuda")
        w = torch.randn(4, 3, 3, 3, device="cuda")
        torch.nn.functional.conv2d(x, w)
        torch.cuda.synchronize()
        print("cuDNN probe OK")
    except RuntimeError as e:
        if "cuDNN" not in str(e) and "CUDNN" not in str(e):
            raise
        torch.backends.cudnn.enabled = False
        print(f"cuDNN probe FAILED ({str(e)[:80]}); "
              f"training with cuDNN disabled for this run")
        x = torch.randn(1, 3, 32, 32, device="cuda")
        w = torch.randn(4, 3, 3, 3, device="cuda")
        torch.nn.functional.conv2d(x, w)          # must work now, or die here
        torch.cuda.synchronize()


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
                    help="export/benchmark an existing checkpoint only; "
                         "requires --weights")
    ap.add_argument("--weights", default=None,
                    help="checkpoint to load before exporting. Mandatory with "
                         "--skip-train: without it the export runs on a "
                         "freshly initialised model and produces a valid ONNX "
                         "file containing random weights, which is worse than "
                         "no file at all because it looks like a result")
    args = ap.parse_args()

    labels_path = os.path.join(args.data, "labels.txt")
    labels = open(labels_path).read().strip().split(",")
    # labels[0] is the reserved placeholder; real classes start at index 1.
    print(f"labels ({len(labels)}): {labels}")
    os.makedirs(args.out, exist_ok=True)

    if args.skip_train and not args.weights:
        raise SystemExit(
            "--skip-train without --weights would export an untrained model. "
            "Pass the checkpoint to export.")

    _cudnn_probe()

    from rfdetr import RFDETRBase, RFDETRLarge
    Model = RFDETRBase if args.model == "base" else RFDETRLarge
    if args.weights:
        model = _load_weights(Model, args.resolution, args.weights,
                              len(labels) - 1)
    else:
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


def _load_weights(Model, resolution, ckpt, num_classes):
    """Build the model with a trained checkpoint in it, and PROVE it loaded.

    This exists because the export path used to construct a fresh model and
    export that. It never raised — a randomly initialised RF-DETR exports
    perfectly well — so the failure mode was an ONNX file of the right size
    and shape that detected nothing, which is the worst kind of artefact to
    ship because it looks like success.

    rfdetr's constructor keyword for this has moved between releases and the
    pod installs whatever is current, so several shapes are tried. What is NOT
    negotiable is the verification: a parameter tensor is compared against the
    checkpoint's own copy, and a mismatch raises rather than warns.
    """
    import torch
    if not os.path.exists(ckpt):
        raise SystemExit(f"--weights: no such file {ckpt}")
    blob = torch.load(ckpt, map_location="cpu", weights_only=False)
    state = blob.get("model", blob) if isinstance(blob, dict) else blob
    if hasattr(state, "state_dict"):
        state = state.state_dict()
    print(f"checkpoint {ckpt}: {len(state)} tensors"
          + (f", epoch {blob['epoch']}" if isinstance(blob, dict)
             and "epoch" in blob else ""))

    attempts = [
        {"pretrain_weights": ckpt, "num_classes": num_classes},
        {"pretrain_weights": ckpt},
        {"pretrained_weights": ckpt},
    ]
    model = last = None
    for kw in attempts:
        try:
            model = Model(resolution=resolution, **kw)
            print(f"constructed with {sorted(kw)}")
            break
        except Exception as e:
            last = f"{sorted(kw)}: {type(e).__name__} {e}"
            print("  " + last)
    if model is None:
        raise SystemExit(f"could not load {ckpt} into the model; last: {last}")

    # --- verify, do not assume ---
    torch_module = None
    for path in ("model.model", "model", "_model"):
        obj = model
        for part in path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                break
        if obj is not None and hasattr(obj, "state_dict"):
            torch_module = obj
            break
    if torch_module is None:
        raise SystemExit("cannot reach the torch module to verify the load; "
                         "refusing to export weights I cannot check")

    live = torch_module.state_dict()
    checked = matched = 0
    for k, v in state.items():
        if not hasattr(v, "shape"):
            continue
        lk = k[7:] if k.startswith("module.") else k
        if lk in live and live[lk].shape == v.shape:
            checked += 1
            if torch.allclose(live[lk].float().cpu(), v.float().cpu(),
                              atol=1e-5):
                matched += 1
            if checked >= 20:
                break
    if checked == 0:
        raise SystemExit("no comparable tensors between checkpoint and model; "
                         "the load cannot be verified")
    print(f"weight check: {matched}/{checked} sampled tensors match the "
          f"checkpoint")
    if matched < checked:
        raise SystemExit("the constructed model does not hold the checkpoint's "
                         "weights — refusing to export an untrained model")
    return model


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
