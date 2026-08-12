"""Self-hosted CPU damage detector — the fast, owned, zero-cost vision path.

WHY A DETECTOR AND NOT A VLM
A vision-language model *generates prose* about an image; a detector *measures*
it. For "where is the damage, what kind, how big", the detector is the right
instrument, and the difference is not marginal:

    hosted VLM (free tier)   ~5-20 s / scan, rate-capped, someone else's box
    frontier VLM             ~10-20 s / scan, per-scan fee
    CPU detector (this)      ~0.1-0.4 s / image, unlimited, yours

It also produces something no VLM reliably does: a **box**. That is what turns
a "dent on the hood" into a pin at a real position on the 3D model, and it is
why this path is the one that eventually makes fusion.precision better than
"panel".

LICENSING — READ BEFORE SWAPPING IN WEIGHTS
The convenient pre-trained car-damage models are legally unusable in a
commercial product, which is why this module ships a contract and not a
checkpoint:
  * Ultralytics YOLOv8/v11 weights are AGPL-3.0. Serving one over a network —
    exactly what this worker does — triggers copyleft on the whole application
    unless an Ultralytics commercial licence is bought.
  * The CarDD dataset (which nearly every good HF car-damage model is fine-tuned
    on) is non-commercial research only, and CarDD does not own the underlying
    Flickr/Shutterstock image copyrights.
The clean path is an Apache-2.0 architecture (RF-DETR, RT-DETR, D-FINE) trained
on permissively licensed data (e.g. CC-BY-4.0 sets, or your own captures), which
also means the weights are genuinely YOURS. Nothing here depends on which of
those you pick — set DAMAGE_DETECTOR_MODEL to an ONNX file and go.

STRUCTURE
The deterministic half — class mapping, severity, evidence, the findings
contract — is pure stdlib and fully tested. The model-specific tensor handling
is one clearly marked seam (`onnx_detect`), because writing elaborate untested
inference against weights this repo does not have would be pretending.
"""
import os
import json

# Detector label -> taxonomy damage id. Deliberately generous about spelling:
# every public car-damage dataset names these six slightly differently, and a
# label that fails to map would silently drop a real finding.
DAMAGE_CLASS_MAP = {
    "dent": "dent", "dents": "dent", "body_dent": "dent",
    "scratch": "scratch", "scratches": "scratch", "scrape": "scratch",
    "crack": "crack", "cracks": "crack", "cracked": "crack",
    "glass shatter": "shattered_glass", "glass_shatter": "shattered_glass",
    "shattered_glass": "shattered_glass", "broken_glass": "shattered_glass",
    "glass_broken": "shattered_glass",
    "lamp broken": "lamp_damage", "lamp_broken": "lamp_damage",
    "broken_lamp": "lamp_damage", "lamp_damage": "lamp_damage",
    "headlight_damage": "lamp_damage", "light_broken": "lamp_damage",
    "tire flat": "tire_damage", "tire_flat": "tire_damage",
    "flat_tire": "tire_damage", "tire_damage": "tire_damage",
    "rust": "rust", "corrosion": "rust",
    "missing_part": "missing_part", "part_missing": "missing_part",
    "misalignment": "misalignment", "gap": "misalignment",
    "deformation": "deformation", "deformed": "deformation",
}

# Floor severity per damage type, before the size term. A shattered windshield
# is never "minor" however small the box; a scratch is never "severe" however
# long. These bracket the size-derived score rather than replace it.
SEVERITY_FLOOR = {
    "shattered_glass": 7, "crack": 4, "deformation": 5, "missing_part": 5,
    "tire_damage": 5, "lamp_damage": 4, "misalignment": 3, "rust": 3,
    "dent": 2, "scratch": 1,
}
SEVERITY_CEILING = {
    "scratch": 6, "rust": 7, "misalignment": 6,
}

# How much of the frame a box covers before it counts as "large". Damage boxes
# are small in absolute terms — 12% of a well-framed panel photo is a big hit.
LARGE_AREA_FRAC = 0.12

DEFAULT_MIN_CONFIDENCE = 0.35


def severity_from_box(damage_type, area_frac, confidence=1.0):
    """Severity 1-10 for a detection, from its type and how much frame it takes.

    Deliberately simple and monotonic: bigger box -> higher severity, bounded by
    the per-type floor and ceiling. This is an approximation of damage extent,
    not a measurement of repair cost, and `evidence` says so — the honest claim
    is "this much of the frame is damaged", not "this will cost X".
    """
    frac = max(0.0, min(1.0, float(area_frac)))
    floor = SEVERITY_FLOOR.get(damage_type, 2)
    ceiling = SEVERITY_CEILING.get(damage_type, 10)
    # size term: 0 at no area, ~6 at LARGE_AREA_FRAC, saturating after
    size = 6.0 * min(1.0, frac / LARGE_AREA_FRAC) ** 0.7
    sev = floor + size
    # a barely-confident detection should not drive a severe headline
    if confidence < 0.5:
        sev -= 1
    return int(max(1, min(10, min(ceiling, round(sev)))))


def _box_area_frac(box, image_size):
    """Fraction of the image covered by an (x1, y1, x2, y2) box."""
    x1, y1, x2, y2 = [float(v) for v in box]
    w, h = float(image_size[0]), float(image_size[1])
    if w <= 0 or h <= 0:
        return 0.0
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return max(0.0, min(1.0, area / (w * h)))


def _to_norm_xywh(box, image_size):
    """Absolute (x1, y1, x2, y2) pixels -> normalised [x, y, w, h] in 0..1."""
    x1, y1, x2, y2 = [float(v) for v in box]
    w, h = float(image_size[0]), float(image_size[1])
    if w <= 0 or h <= 0:
        return None
    x = max(0.0, min(1.0, x1 / w))
    y = max(0.0, min(1.0, y1 / h))
    bw = max(0.0, min(1.0 - x, (x2 - x1) / w))
    bh = max(0.0, min(1.0 - y, (y2 - y1) / h))
    return [round(x, 4), round(y, 4), round(bw, 4), round(bh, 4)]


def _box_centre_frac(box, image_size):
    x1, y1, x2, y2 = [float(v) for v in box]
    w, h = float(image_size[0]), float(image_size[1])
    if w <= 0 or h <= 0:
        return (0.5, 0.5)
    return (max(0.0, min(1.0, ((x1 + x2) / 2.0) / w)),
            max(0.0, min(1.0, ((y1 + y2) / 2.0) / h)))


def detections_to_findings(detections, image_size, image_index=0,
                           panel_hint=None, min_confidence=None):
    """Detector output -> findings in the schema analyze.normalize_findings eats.

    `detections` is a list of {label, box: [x1,y1,x2,y2], score}. `panel_hint`
    is the panel this photo is known to show (the capture grid already asks the
    user for "front", "left rear" and so on, so the app usually knows) — without
    it the finding still scores and prices, it just lands on body_other.

    Every finding gets concrete, checkable evidence naming the measurement that
    produced it. That is not decoration: normalize_findings DROPS a finding with
    no evidence, so a detection that cannot say what it saw does not become a
    charge on someone's invoice.
    """
    floor = DEFAULT_MIN_CONFIDENCE if min_confidence is None else min_confidence
    out = []
    for d in detections or []:
        if not isinstance(d, dict):
            continue
        score = float(d.get("score", d.get("confidence", 0)) or 0)
        if score < floor:
            continue
        label = str(d.get("label", d.get("class", ""))).strip().lower()
        dtype = DAMAGE_CLASS_MAP.get(label) or DAMAGE_CLASS_MAP.get(
            label.replace(" ", "_"))
        if not dtype:
            continue
        box = d.get("box") or d.get("bbox")
        if not box or len(box) != 4:
            continue
        area = _box_area_frac(box, image_size)
        cx, cy = _box_centre_frac(box, image_size)
        sev = severity_from_box(dtype, area, score)
        out.append({
            "panel": panel_hint or d.get("panel") or "body_other",
            "damage_type": dtype,
            "severity": sev,
            "confidence": round(score, 3),
            "image_index": image_index,
            # NORMALISED [x, y, w, h] in the unit square — the one bbox
            # convention this product uses, matching analyze._bbox_or_none.
            # Detectors speak absolute pixel corners, so the conversion happens
            # here at the boundary. Emitting pixels instead would be silently
            # destroyed by normalisation (clamped to 0..1, zero width, dropped),
            # and the finding would reach the report with no box at all while
            # every log looked healthy. Normalised also survives the report
            # being rendered at any resolution, which pixels do not.
            "bbox": _to_norm_xywh(box, image_size),
            "evidence": [
                f"detector found {label or dtype} at "
                f"{cx * 100:.0f}%,{cy * 100:.0f}% of the frame, covering "
                f"{area * 100:.1f}% of the image (confidence {score:.2f})"
            ],
        })
    return out


def detections_to_json(per_image, summary=""):
    """Wrap per-image findings in the same JSON envelope a VLM returns.

    This is the trick that makes the detector a drop-in: analyze() already
    parses this envelope, so the detector reuses the entire downstream
    pipeline — normalisation, scoring, pricing, fusion, report — with no
    branching anywhere else in the worker.
    """
    findings, images = [], []
    for i, (dets, size, hint) in enumerate(per_image):
        found = detections_to_findings(dets, size, image_index=i,
                                       panel_hint=hint)
        findings.extend(found)
        images.append({"index": i,
                       "panels_visible": [hint] if hint else [],
                       "tags": []})
    return json.dumps({"findings": findings, "images": images,
                       "summary": summary})


# --- the model-specific seam ------------------------------------------------

def onnx_detect(image_path, session=None, input_size=None, labels=None,
                min_confidence=None):
    """Run one image through an ONNX detection model on CPU.

    Kept thin and separate on purpose: input layout, output tensor order and
    label indexing differ per architecture (RF-DETR vs RT-DETR vs D-FINE), and
    this repo holds no weights to verify against. Point
    DAMAGE_DETECTOR_MODEL at your exported .onnx and adjust here once; every
    other line in this module is model-agnostic and covered by tests.

    Returns a list of {label, box, score} — the shape detections_to_findings
    expects.
    """
    import onnxruntime  # noqa: F401  (imported lazily; CPU EP, no CUDA needed)
    from PIL import Image
    import numpy as np

    size = input_size or int(os.environ.get("DAMAGE_DETECTOR_SIZE", "640"))
    if session is None:
        model_path = os.environ.get("DAMAGE_DETECTOR_MODEL")
        if not model_path:
            raise RuntimeError(
                "DAMAGE_BACKEND=detector needs DAMAGE_DETECTOR_MODEL pointing "
                "at an ONNX detection model. See this module's docstring for "
                "why no checkpoint ships here (AGPL weights / non-commercial "
                "datasets) and what to train instead.")
        session = onnxruntime.InferenceSession(
            model_path, providers=["CPUExecutionProvider"])

    img = Image.open(image_path).convert("RGB")
    orig = img.size
    arr = np.asarray(img.resize((size, size)), dtype=np.float32) / 255.0
    arr = np.transpose(arr, (2, 0, 1))[None, ...]

    outputs = session.run(None, {session.get_inputs()[0].name: arr})
    return parse_detections(outputs, orig, (size, size), labels,
                            min_confidence)


def parse_detections(outputs, orig_size, model_size, labels=None,
                     min_confidence=None):
    """Normalise raw ONNX outputs into {label, box, score} in ORIGINAL pixels.

    Handles the common (boxes, scores, labels) triple. Boxes are rescaled from
    the model's letterboxed input back to the source image, because every
    downstream consumer — severity, bbox, and eventually the 3D pin — is in
    source-image coordinates.
    """
    floor = DEFAULT_MIN_CONFIDENCE if min_confidence is None else min_confidence
    if not outputs:
        return []
    boxes, scores, class_ids = _unpack_outputs(outputs)
    sx = float(orig_size[0]) / float(model_size[0])
    sy = float(orig_size[1]) / float(model_size[1])
    dets = []
    for box, score, cid in zip(boxes, scores, class_ids):
        if float(score) < floor:
            continue
        label = (labels[int(cid)] if labels and int(cid) < len(labels)
                 else str(cid))
        dets.append({
            "label": label,
            "score": float(score),
            "box": [float(box[0]) * sx, float(box[1]) * sy,
                    float(box[2]) * sx, float(box[3]) * sy],
        })
    return dets


def _unpack_outputs(outputs):
    """(boxes, scores, class_ids) from the usual ONNX detection output shapes."""
    if len(outputs) >= 3:
        return (_squeeze(outputs[0], 2), _squeeze(outputs[1], 1),
                _squeeze(outputs[2], 1))
    # single (N, 6) tensor: x1, y1, x2, y2, score, class
    rows = _squeeze(outputs[0], 2)
    return ([r[:4] for r in rows], [r[4] for r in rows],
            [r[5] for r in rows])


def _squeeze(t, ndim):
    """Drop leading batch dims of 1 down to `ndim`, without requiring numpy.

    `ndim` is essential rather than cosmetic: a batch of one detection and a
    single unbatched detection have the same length, so squeezing "while the
    length is 1" eats the detection axis exactly when there is one detection —
    the most common real result. Squeezing only down to the expected rank keeps
    (1, N, 4) and (N, 4) apart when N is 1.
    """
    seq = t.tolist() if hasattr(t, "tolist") else list(t)
    while _depth(seq) > ndim and isinstance(seq, list) and len(seq) == 1:
        seq = seq[0]
    return list(seq)


def _depth(x):
    d = 0
    while isinstance(x, list) and x:
        d += 1
        x = x[0]
    return d


def detector_backend():
    """A vision_fn backed by the local CPU detector.

    Signature-compatible with the VLM backends (it ignores the text prompt and
    returns the same JSON envelope), so DAMAGE_BACKEND=detector changes the
    instrument without changing the pipeline.
    """
    state = {}

    def vision_fn(prompt, image_refs):
        # Config is checked BEFORE the heavy imports on purpose: a missing
        # model path should say so, not surface as "No module named
        # 'onnxruntime'" and send someone debugging the wrong problem.
        model_path = os.environ.get("DAMAGE_DETECTOR_MODEL")
        if not model_path:
            raise RuntimeError(
                "DAMAGE_BACKEND=detector needs DAMAGE_DETECTOR_MODEL "
                "(path to an ONNX detection model).")
        import onnxruntime
        from PIL import Image
        if "session" not in state:
            state["session"] = onnxruntime.InferenceSession(
                model_path, providers=["CPUExecutionProvider"])
        labels = _labels_from_env()
        per_image = []
        for ref in image_refs:
            path = _local_path(ref)
            dets = onnx_detect(path, session=state["session"], labels=labels)
            per_image.append((dets, Image.open(path).size, None))
        return detections_to_json(per_image)

    return vision_fn


def _labels_from_env():
    """Class-index -> name, from DAMAGE_DETECTOR_LABELS (comma separated)."""
    raw = os.environ.get("DAMAGE_DETECTOR_LABELS", "")
    return [s.strip() for s in raw.split(",") if s.strip()] or None


def _local_path(ref):
    """Detection runs on pixels, so a URL must be fetched to disk first."""
    s = str(ref)
    if not s.startswith(("http://", "https://")):
        return s
    import tempfile
    import requests
    from analyze import FETCH_HEADERS
    r = requests.get(s, headers=FETCH_HEADERS, timeout=30)
    r.raise_for_status()
    fd, path = tempfile.mkstemp(suffix=".jpg")
    with os.fdopen(fd, "wb") as f:
        f.write(r.content)
    return path
