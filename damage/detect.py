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

    # THE SIX CLASSES THE SHIPPED DETECTOR ACTUALLY EMITS.
    #
    # These were absent, and absent is not "falls back to grey" — an unmapped
    # label hits `if not dtype: continue` in detections_to_findings and the
    # detection is DISCARDED. Five of the six trained classes were therefore
    # deleted between the model and the report, silently, with dent surviving
    # only because its name happens to collide with a taxonomy type.
    #
    # Each of these is a merge of several taxonomy types (that is why the
    # training index has six classes and the taxonomy has nineteen), so the
    # mapping picks the type that carries the class's dominant member and the
    # loss is stated rather than hidden:
    #
    #   scratch_scuff  scratch + scuff + light paint damage -> scratch
    #   crack_glass    body cracks + glass cracks + shatter -> crack
    #   lamp_wheel     broken lamps + wheel/tyre damage     -> lamp_damage
    #   rust_paint     corrosion + paint failure            -> rust
    #   structural     deformation + misalignment + missing -> deformation
    #
    # A finding therefore names a narrower type than the model can justify
    # (a lamp_wheel box reported as lamp_damage may be a kerbed alloy). The
    # honest fix is a detector whose classes match the taxonomy; until then
    # this is the mapping, and _selftest below asserts it stays complete.
    "scratch_scuff": "scratch",
    "crack_glass": "crack",
    "lamp_wheel": "lamp_damage",
    "rust_paint": "rust",
    "structural": "deformation",

    # AND THE GROUPED VOCABULARIES, which are the same bug again.
    # build_train_index supports --merge-groups and --groups-v2, which train
    # against `surface` / `broken_part` / `deformation` instead of the six
    # above. Those names were not here either, so a groups-v2 model would have
    # had two of its three classes deleted by the same `if not dtype: continue`
    # — including surface, which is scratches and rust together. Fixing only
    # the vocabulary that happens to be in production leaves the trap armed
    # for the next run that uses a supported flag.
    #   surface      scratches + rust + paint failure  -> scratch
    #   broken_part  glass + lamps + wheels            -> crack
    #   deformation  dents + structural                -> deformation
    "surface": "scratch",
    "broken_part": "crack",
}

# Every class vocabulary the training pipeline can emit. Anything here must
# resolve through DAMAGE_CLASS_MAP or its detections are silently dropped.
TRAINING_VOCABULARIES = {
    "six-class": ("crack_glass", "dent", "lamp_wheel", "rust_paint",
                  "scratch_scuff", "structural"),
    "merge-groups": ("surface", "dent", "structural", "broken_part"),
    "groups-v2": ("surface", "deformation", "broken_part"),
}

# The class names the shipped 6-class model emits, in the id order its
# classes.json uses. Kept here so the completeness check has something to
# assert against without importing the training package.
DETECTOR_CLASSES = ("crack_glass", "dent", "lamp_wheel", "rust_paint",
                    "scratch_scuff", "structural")

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

# MEASURED, not chosen. Swept on 814 independently-labelled ECC images with
# 9,080 ground-truth boxes — data this detector never trained on and whose
# annotators never saw our taxonomy:
#
#     thresh    precision   recall       F1       per-image correct
#       0.14       0.159    0.379     0.224            95.7%
#       0.20       0.275    0.262     0.268            90.4%
#       0.21       0.298    0.247     0.270            89.4%   <- F1 optimum
#       0.30       0.483    0.133     0.208            72.1%
#       0.35 (old)     ~0.55   ~0.10    ~0.17            ~65%
#
# The old 0.35 sat far below the optimum and was discarding most of what the
# model could find: recall roughly 0.10 against 0.26 here. Nothing about it was
# measured — it predated any external test set.
#
# 0.20 rather than the strict F1 optimum at 0.21, and rather than the
# recall-weighted F2 optimum at 0.14, because:
#   - a missed damage is a disputed claim later, a false one is an assessor's
#     time now, so the operating point should lean recall-ward of F1;
#   - but F2's 0.14 means six false flags per true one, and a report nobody
#     trusts is worse than a thin one. 0.20 more than doubles recall against
#     the old default while keeping per-image location at 90%.
#
# This is an operating point, NOT a fix for the underlying 26%. See
# eval_external.py for what the model actually does.
DEFAULT_MIN_CONFIDENCE = 0.20

# PER-CLASS FLOORS. One global cut cannot serve six classes whose precision
# ranges from 15% (crack_glass) to 41% (structural): the same 0.20 that is
# about right for a scratch admits three wrong dents for every good one.
#
# Fitted by coordinate ascent on F1 over half the ECC set and scored on the
# other half — 427 images to choose, 387 it had never seen to report. The
# held-out gain is what is quoted below, not the fitting-half gain, because
# six free parameters will always flatter themselves on their own data.
#
# Absent entries fall back to DEFAULT_MIN_CONFIDENCE, so a vocabulary this map
# does not cover still runs.
CLASS_MIN_CONFIDENCE = {
    "crack_glass": 0.25,
    "dent": 0.25,
    "lamp_wheel": 0.25,
    "rust_paint": 0.20,
    "scratch_scuff": 0.20,
    "structural": 0.15,
}

# NMS IoU. RF-DETR is trained with Hungarian matching and needs no NMS to
# deduplicate — measured on the ECC set, only 3.5% of its boxes overlap another
# at all. This is not deduplication: it suppresses the pile of near-copies that
# accumulates once the confidence floor is low enough to be useful, which is
# where the precision goes.
#
# 0.5 beat 0.6 and 0.7 on the held-out half. Together with the per-class floors:
#   precision 24.1% -> 28.5%, recall 22.9% -> 22.7%, F1 23.5% -> 25.3%
# i.e. roughly a fifth of the false positives removed at flat recall.
DEFAULT_NMS_IOU = 0.5


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


# A measured severity tier, on the 1-10 scale the rest of the pipeline speaks.
# Both ladders share this table; "medium" and "severe" mean the same thing on
# either, which is why they map to the same number.
TIER_SEVERITY = {"faint": 2, "light": 3, "minor": 3, "medium": 5,
                 "major": 7, "deep": 7, "severe": 9}

# Below this, the severity module's own confidence is too low to override the
# extent-based estimate. A dent photographed in flat diffuse light lands here,
# and its grade is a guess dressed as a measurement.
GRADE_TRUST = 0.4


def severity_from_grade(damage_type, area_frac, confidence, grade):
    """Severity from a MEASURED depth or deformation, falling back to extent.

    Extent alone gets insurance-grade scans backwards, which is the whole
    reason severity_grade.py exists. A 30cm faint clearcoat scuff covers far more of
    the frame than a 1cm scratch through to primer, so the area rule rates the
    scuff — which polishes out — above the one that needs the panel resprayed.

    So depth leads and extent modifies, 70/30. Extent still counts, because a
    deep scratch across a whole door is worse than the same depth in one spot,
    and because the tier ladder has only five rungs.

    When the measurement does not trust itself, extent is used unchanged. A
    number that is wrong is worse than a number that is coarse.
    """
    size_sev = severity_from_box(damage_type, area_frac, confidence)
    if not grade or not grade.get("tier"):
        return size_sev, None
    if float(grade.get("confidence") or 0) < GRADE_TRUST:
        return size_sev, "low-confidence measurement; severity from extent"
    tier_sev = TIER_SEVERITY.get(grade["tier"])
    if tier_sev is None:
        return size_sev, None
    blended = 0.7 * tier_sev + 0.3 * size_sev
    ceiling = SEVERITY_CEILING.get(damage_type, 10)
    floor = SEVERITY_FLOOR.get(damage_type, 2)
    sev = int(max(1, min(10, min(ceiling, max(floor, round(blended))))))
    return sev, None


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
        grade = d.get("grade")
        sev, caveat = severity_from_grade(dtype, area, score, grade)
        evidence = [
            f"detector found {label or dtype} at "
            f"{cx * 100:.0f}%,{cy * 100:.0f}% of the frame, covering "
            f"{area * 100:.1f}% of the image (confidence {score:.2f})"
        ]
        if grade and grade.get("tier"):
            m = grade.get("metrics") or {}
            # The evidence names the MEASUREMENT, not just its conclusion, so
            # a disputed grade can be checked against the photo rather than
            # argued about. An insurance report that says "deep" and cannot
            # say why is an opinion.
            bits = [f"graded {grade['tier']}",
                    f"depth score {grade.get('score')}",
                    f"basis {grade.get('basis')}"]
            if grade.get("basis") == "chroma" and m.get("ref_C"):
                lost = 1.0 - (m.get("dmg_C", 0) / m["ref_C"])
                bits.append(f"{lost * 100:.0f}% of the paint's colour is "
                            f"absent inside the damage")
            if grade.get("basis") == "lightness":
                bits.append("paint too neutral for a colour comparison; "
                            "graded on lightness alone")
            if grade.get("basis") == "curvature" and m.get("curv_ratio"):
                bits.append(f"reflection is bent {m['curv_ratio']:.1f}x more "
                            f"than the undamaged paint around it")
            if m.get("length_px"):
                bits.append(f"{m['length_px']:.0f}x{m.get('width_px', 0):.0f}px")
            bits.append(f"measurement confidence {grade.get('confidence')}")
            evidence.append("; ".join(bits))
        if caveat:
            evidence.append(caveat)
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
            "evidence": evidence,
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
    return onnx_detect_image(img, session=session, input_size=size,
                             labels=labels, min_confidence=min_confidence)


def onnx_detect_image(img, session, input_size=None, labels=None,
                      min_confidence=None):
    """The same inference, on an already-open image.

    Split out because tiled_detect hands this function crops that were never
    files. Re-encoding each of a dozen tiles to disk so the path-based version
    could re-decode it would dominate the runtime of the very feature that
    exists to make inference thorough.
    """
    import numpy as np

    size = input_size or int(os.environ.get("DAMAGE_DETECTOR_SIZE", "640"))
    orig = img.size
    arr = np.asarray(img.convert("RGB").resize((size, size)),
                     dtype=np.float32) / 255.0
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
    # RF-DETR's boxes are already normalised, so they scale by the ORIGINAL
    # size and not by the model/original ratio. Mixing the two conventions is
    # how a box ends up at a plausible-looking but wrong place.
    if _is_rfdetr(outputs):
        # The unpacker gates on score before this function can consult the
        # per-class table, so a class whose fitted floor sits BELOW the global
        # default would be cut here and its floor would never apply. Hand it
        # the lowest floor in play and let the per-class cut happen below,
        # where the label is known. Getting this wrong is silent: the constant
        # still reads 0.15 in the source and nothing ever honours it.
        gate = floor if min_confidence is not None else min(
            [floor] + list(CLASS_MIN_CONFIDENCE.values()))
        boxes, scores, class_ids = _unpack_rfdetr(outputs, orig_size, gate)
        sx = sy = 1.0
    else:
        boxes, scores, class_ids = _unpack_outputs(outputs)
        sx = float(orig_size[0]) / float(model_size[0])
        sy = float(orig_size[1]) / float(model_size[1])
    dets = []
    for box, score, cid in zip(boxes, scores, class_ids):
        label = _label_for(labels, int(cid))
        # The per-class floor only applies when the caller did not name one.
        # An explicit min_confidence is an operator decision and must not be
        # quietly overridden per class — a sweep asking for 0.05 has to get
        # 0.05 for every class or the curve it draws is a fiction.
        cut = floor if min_confidence is not None else \
            CLASS_MIN_CONFIDENCE.get(label, floor)
        if float(score) < cut:
            continue
        dets.append({
            "label": label,
            "score": float(score),
            "box": [float(box[0]) * sx, float(box[1]) * sy,
                    float(box[2]) * sx, float(box[3]) * sy],
        })
    return nms(dets, DEFAULT_NMS_IOU)


def box_iou(a, b):
    """IoU of two [x1, y1, x2, y2] boxes."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    ua = ((a[2] - a[0]) * (a[3] - a[1]) +
          (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / ua if ua > 0 else 0.0


def nms(dets, iou_thresh=None):
    """Drop any detection an already-kept, higher-scoring one covers.

    Class-agnostic on purpose. Two labels on one rectangle is two claims about
    the same piece of metal, and reporting both means an assessor reading
    "dent" and "scratch" for one mark. Suppressing across classes scored the
    same as within-class on the held-out half (both +1.0pp F1) and produces the
    more honest report, so the tie goes to the one that does not double-count.
    """
    t = DEFAULT_NMS_IOU if iou_thresh is None else iou_thresh
    keep = []
    for d in sorted(dets, key=lambda x: -x["score"]):
        if any(box_iou(d["box"], k["box"]) >= t for k in keep):
            continue
        keep.append(d)
    return keep


def _label_for(labels, cid):
    """Name for a class id, from either an id->name map or a positional list.

    TWO CONVENTIONS COLLIDE HERE and confusing them mislabels every detection
    instead of failing. RF-DETR reserves class 0 as a placeholder and emits
    1-BASED ids, which is why its classes.json is keyed {"1": "crack_glass",
    ...}. The older exporters emit 0-based ids and are configured with a plain
    list. Indexing a 6-item list with a 1-based id shifts every class by one —
    a crack reported as a dent — and silently drops the last class, which is
    exactly what happened before this function existed.

    So a dict is read BY ID and a list BY POSITION, and the two are never
    treated as interchangeable. Prefer the dict: it carries the ids explicitly
    and cannot be misread.
    """
    if not labels:
        return str(cid)
    if isinstance(labels, dict):
        # classes.json round-trips through JSON, so keys may be str or int.
        v = labels.get(cid, labels.get(str(cid)))
        return str(v) if v is not None else str(cid)
    return labels[cid] if 0 <= cid < len(labels) else str(cid)


def _input_size(session):
    """Square input side the graph declares, or None if it is dynamic.

    Returns None rather than guessing when the dimension is a symbol: a
    dynamic-axis model genuinely accepts a range and the caller's default is
    then the right answer.
    """
    try:
        shape = session.get_inputs()[0].shape
    except Exception:
        return None
    if not shape or len(shape) != 4:
        return None
    h, w = shape[2], shape[3]
    if isinstance(h, int) and isinstance(w, int) and h == w and h > 0:
        return int(h)
    return None


def _labels_beside_model(model_path):
    """id -> name from a classes.json sitting next to the ONNX, or None.

    The training pipeline writes classes.json with the index the model was
    actually trained on, so the artefact can describe itself. Reading it is
    what stops the class names being a deployment detail someone has to
    remember to set — and forgetting produced not a warning but an empty
    report, because an unresolved name becomes "3", which maps to nothing and
    is dropped.
    """
    if not model_path:
        return None
    d = os.path.dirname(os.path.abspath(model_path))
    for cand in (os.path.splitext(model_path)[0] + ".classes.json",
                 os.path.join(d, "classes.json")):
        try:
            with open(cand) as f:
                doc = json.load(f)
        except Exception:
            continue
        m = doc.get("index_to_name") if isinstance(doc, dict) else None
        # ACCEPT A BARE id -> name MAPPING TOO.
        #
        # Requiring the "index_to_name" wrapper meant an obvious-looking
        # {"1": "crack_glass", ...} was read, found wanting, and SILENTLY
        # skipped -- falling through to unresolved names, which become "1"
        # and "2", map to no damage type, and are dropped. The report comes
        # back empty and nothing anywhere says why. Hand-writing this file is
        # a normal step when deploying a checkpoint, so the obvious form has
        # to work.
        if m is None and isinstance(doc, dict) and doc and all(
                str(k).lstrip("-").isdigit() and isinstance(v, str)
                for k, v in doc.items()):
            m = doc
        if isinstance(m, dict) and m:
            return {int(k): str(v) for k, v in m.items()}
    return None


def _is_rfdetr(outputs):
    """Two outputs, (1,N,4) boxes and (1,N,C) class logits — the DETR family.

    Shape-based, not name-based: exporters rename tensors between versions and
    a name check would break silently on the next export.
    """
    if len(outputs) != 2:
        return False
    try:
        import numpy as np
        a, b = np.asarray(outputs[0]), np.asarray(outputs[1])
    except Exception:
        return False
    return (a.ndim == 3 and b.ndim == 3 and a.shape[-1] == 4
            and a.shape[1] == b.shape[1] and b.shape[-1] >= 2)


def _unpack_rfdetr(outputs, orig_size, min_confidence):
    """RF-DETR ONNX -> (boxes_xyxy_pixels, scores, class_ids).

    THIS EXISTS BECAUSE THE GENERIC PARSER WAS WRONG IN THREE WAYS AT ONCE, and
    every one of them was invisible. The module shipped without weights to test
    against, so the contract was written from the common case and never
    verified. Run against the real exported model it produced garbage while
    looking perfectly healthy — the session loads, the tensors come back, the
    parser returns boxes, and nothing raises.

    What the model actually emits:

        dets   (1, 300, 4)   normalised cx, cy, w, h in 0..1
        labels (1, 300, C)   raw LOGITS, not probabilities

    Against a parser expecting pixel x1,y1,x2,y2 and ready-made scores. So the
    boxes were read as corners when they were centres, and the "scores" were
    negative logits that no confidence floor would ever pass.

    Three specifics that matter:

    * SIGMOID, NOT SOFTMAX. The DETR family trains with sigmoid focal loss, so
      each class is an independent probability. Softmax here would normalise
      across classes and invent confidence for a query that matched nothing.

    * CLASS 0 IS SKIPPED. Index 0 is the reserved `_placeholder_` that keeps
      COCO ids 1-based, matching labels.txt. Taking an argmax over all C would
      let the placeholder win a query and emit a detection with no class.

    * SET PREDICTION, SO NMS IS NOT DEDUPLICATION. DETR's queries are already
      one-per-object by construction, and measurement agrees: on the 814-image
      ECC set only 3.5% of kept boxes overlap another at all. What parse_detections
      suppresses afterwards is not duplicate queries but the pile of near-copies
      that appears once the confidence floor is low enough to be useful. The
      cost this docstring used to warn about — losing genuinely adjacent damage
      — is real and was measured rather than argued: recall 22.9% -> 22.7%,
      against precision 24.1% -> 28.5%. Suppression happens in parse_detections,
      not here, so this function stays a faithful reading of the raw graph.
    """
    import numpy as np
    boxes = np.asarray(outputs[0])[0]          # (N, 4) cxcywh normalised
    logits = np.asarray(outputs[1])[0]         # (N, C) raw
    probs = 1.0 / (1.0 + np.exp(-logits))      # sigmoid: independent per class
    probs = probs[:, 1:]                       # drop the reserved placeholder
    cls = probs.argmax(axis=1) + 1             # back to 1-based class ids
    score = probs.max(axis=1)

    W, H = float(orig_size[0]), float(orig_size[1])
    cx, cy, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    x1 = (cx - w / 2.0) * W
    y1 = (cy - h / 2.0) * H
    x2 = (cx + w / 2.0) * W
    y2 = (cy + h / 2.0) * H
    keep = score >= (min_confidence if min_confidence is not None
                     else DEFAULT_MIN_CONFIDENCE)
    return (np.stack([x1, y1, x2, y2], axis=1)[keep],
            score[keep], cls[keep])


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
        # THE MODEL DESCRIBES ITSELF FIRST, the environment only overrides.
        # This used to read the environment alone, and with the variable unset
        # — the default — every class id resolved to its own number, matched
        # nothing in DAMAGE_CLASS_MAP and was dropped: a scan that found
        # damage reported none, with no error anywhere. Config that is
        # mandatory but silent when missing is not config, it is a trap.
        # THE MODEL WINS OVER THE ENVIRONMENT, not the other way round.
        #
        # This read the env var FIRST, and that turned the error message below
        # into a trap: it tells the operator to set DAMAGE_DETECTOR_LABELS,
        # and a plain comma list is read BY POSITION while RF-DETR emits
        # 1-based ids. Following the instruction therefore shifted every class
        # by one and silently dropped the sixth — re-entering, through the
        # escape hatch, the exact off-by-one _label_for exists to prevent.
        # The model's own classes.json carries explicit ids and cannot be
        # misread, so it is authoritative and the override is the fallback.
        labels = _labels_beside_model(model_path) or _labels_from_env()
        if not labels:
            raise RuntimeError(
                "detector class names could not be resolved: no classes.json "
                f"beside {model_path}, and DAMAGE_DETECTOR_LABELS is unset. "
                "Without names every detection is discarded and the scan "
                "reports no damage, so this fails instead of returning an "
                "empty report. FIX: copy the training run's classes.json to "
                f"{os.path.splitext(model_path or 'model')[0]}.classes.json. "
                "Only if that is impossible, set DAMAGE_DETECTOR_LABELS — and "
                "write it as explicit ids, '1=crack_glass,2=dent,...', "
                "because a bare comma list is read by POSITION and this "
                "model's ids start at 1.")
        # The input resolution likewise comes from the model when it declares
        # one. The shipped export is fixed at 560 while this defaulted to 640,
        # so the default was not merely suboptimal — a fixed-shape input
        # rejects a 640 tensor outright. Reading the graph removes a second
        # deployment detail that had to be remembered and could only be got
        # wrong.
        size = _input_size(state["session"]) or 640
        env_size = os.environ.get("DAMAGE_DETECTOR_SIZE")
        if env_size:
            size = int(env_size)
        # TILING IS ON BY DEFAULT and DAMAGE_TILED=0 turns it off. The default
        # is the way round it is because the whole reason this backend exists
        # is fine damage: at 728 a 3px scratch in a 4032px photo is half a
        # pixel, so a single whole-frame pass cannot see the thing the product
        # is for. Off is for benchmarking against the old behaviour.
        tiled = os.environ.get("DAMAGE_TILED", "1") not in ("0", "false", "no")
        # Grading opens every image a second time in severity.measure, so it
        # is separately switchable — but it is what turns a box into a claim
        # an assessor can act on, so it too defaults on.
        do_grade = os.environ.get("DAMAGE_GRADE", "1") not in ("0", "false",
                                                               "no")
        per_image = []
        for ref in image_refs:
            path = _local_path(ref)
            img = Image.open(path).convert("RGB")
            if tiled:
                from tiled_detect import tiled_detect as _tiled

                def run(crop, _sess=state["session"], _lab=labels, _s=size):
                    return onnx_detect_image(crop, session=_sess, labels=_lab,
                                             input_size=_s)

                dets = _tiled(img, run, model_size=size)
            else:
                # input_size MUST be passed here too. The tiled branch above
                # threads the resolved size through and this one did not, so it
                # fell back to onnx_detect's own 640 default and a fixed-shape
                # 560 export rejected the tensor outright:
                #   Got invalid dimensions for input: Got 640 Expected 560
                # Tiling is on by default, which is the only reason this was
                # not the first thing anyone hit -- DAMAGE_TILED=0 crashed.
                dets = onnx_detect(path, session=state["session"],
                                   labels=labels, input_size=size)
            if do_grade:
                _attach_grades(img, dets)
            per_image.append((dets, img.size, None))
        return detections_to_json(per_image)

    return vision_fn


def _attach_grades(img, dets):
    """Measure each detection and hang the verdict on it.

    Failures are swallowed PER DETECTION. A grade is an enrichment: if the
    measurement cannot be made — the box is two pixels wide, the crop is
    degenerate — the finding should still be reported with its extent-based
    severity rather than the whole photo failing. Losing a real dent because
    a scratch beside it could not be measured would be a bad trade.
    """
    try:                                # flat import, as the worker runs it
        from severity_grade import grade as _grade
    except ImportError:                 # package import
        from damage.severity_grade import grade as _grade
    for d in dets:
        b = d.get("box")
        if not b or len(b) != 4:
            continue
        x1, y1, x2, y2 = [float(v) for v in b]
        if x2 <= x1 or y2 <= y1:
            continue
        try:
            d["grade"] = _grade(img, (x1, y1, x2 - x1, y2 - y1),
                                str(d.get("label", "")).lower())
        except Exception:
            pass


def _labels_from_env():
    """Class names from DAMAGE_DETECTOR_LABELS. Two accepted forms.

        1=crack_glass,2=dent,...   explicit ids -> dict, read BY ID
        crack_glass,dent,...       positional   -> list, read BY POSITION

    The explicit form exists because the positional one is a foot-gun for any
    1-based exporter: RF-DETR reserves class 0, so a plain list silently shifts
    every class by one and loses the last. Both are supported because the older
    0-based exporters are configured with a plain list and still work, but
    anything written today should use ids.
    """
    raw = os.environ.get("DAMAGE_DETECTOR_LABELS", "")
    parts = [s.strip() for s in raw.split(",") if s.strip()]
    if not parts:
        return None
    if all("=" in p for p in parts):
        out = {}
        for p in parts:
            k, _, v = p.partition("=")
            try:
                out[int(k.strip())] = v.strip()
            except ValueError:
                return parts          # not really id=name; treat as positional
        return out or None
    return parts


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
