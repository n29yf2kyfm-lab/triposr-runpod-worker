"""train.py: train the heads on the run's own answers, test them on vehicles held out, write heads.json.

    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/train.py [--encoder FILE] [--cache DIR] [--out FILE]

A fifth of the vehicles (a fixed draw, dataset.split) are held out: every
head is trained without them, and its score on them is the one reported (in
heads.json's card and on screen). The heads written are then trained again
on every vehicle, held-out ones too.

Needs numpy, pillow, onnxruntime and scikit-learn; about 5 minutes on 4 CPUs
the first time (reading the run's 1,650 pictures), under a minute after: what
the encoder makes of each picture is kept in the cache.
"""
import argparse
import collections
import hashlib
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dataset  # noqa: E402
import heads as H  # noqa: E402
import vision  # noqa: E402

FLIP = {"left": "right", "right": "left"}
C = {"colour": 100.0, "side": 100.0, "kind": 10.0, "match": 10.0}
# a build the reviewers found not the photo's vehicle weighs as this many made-up mismatches
# (tried 0, 1, 3, 10: 10 caught the reviewers' wrong builds best, held out)
REAL_WRONG = 10
# the share of builds of the photo's own model the match may flag: its threshold is set by it
OWN_FLAGGED = 0.1


def file_id(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()[:16]


def featurise(files, enc, cache):
    """(embedding, mirrored embedding, colour histogram) for every file, from the cache where it is there."""
    store = os.path.join(cache, f"features-{os.path.basename(enc.path)}.npz")
    old = dict(np.load(store)) if os.path.exists(store) else {}
    ids = [file_id(f) for f in files]
    todo = [(i, f) for i, f in zip(ids, files) if i + ":e" not in old]
    t0 = time.time()
    for n in range(0, len(todo), 64):
        chunk = todo[n:n + 64]
        e, ef, h = H.features(enc, [f for _, f in chunk])
        for (i, _), a, b, c in zip(chunk, e, ef, h):
            old[i + ":e"], old[i + ":f"], old[i + ":h"] = a, b, c
        print(f"  pictures read: {min(n + 64, len(todo))}/{len(todo)} ({time.time() - t0:.0f} s)", flush=True)
    if todo:
        os.makedirs(cache, exist_ok=True)
        np.savez(store + ".part.npz", **old)
        os.replace(store + ".part.npz", store)
    return {f: (old[i + ":e"], old[i + ":f"], old[i + ":h"]) for i, f in zip(ids, files)}


def stack(feat, files, part):
    return np.stack([feat[f][part] for f in files])


def model_of(it):
    return f"{it.get('make')}|{it.get('model')}".lower()


def match_pairs(its, feat, rng, real=REAL_WRONG, n_random=3, n_hard=2):
    """Each build with its own photo (1) and with other vehicles' photos (0), some of them close lookalikes;
    and a build the reviewers found not the photo's vehicle, with its photo (0, counted REAL times: they are few)."""
    own = [it for it in its if it.get("build")]
    if not own:
        return np.zeros((0, 1024), np.float32), np.zeros(0, int), np.zeros(0)
    P = stack(feat, [it["photo"] for it in own], 0)
    B = stack(feat, [it["build"] for it in own], 0)
    sim = B @ P.T
    X, y, w = [], [], []
    for i, it in enumerate(own):
        wrong = it.get("shape_fault_ever") or set(it.get("faults") or []) & dataset.SHAPE_FAULTS
        if not wrong or real:
            X.append(H.pair(P[i], B[i]))
            y.append(0 if wrong else 1)
            w.append(real if wrong else 1)
        other = [j for j in range(len(own)) if model_of(own[j]) != model_of(it)]
        rand = rng.choice(other, size=min(n_random, len(other)), replace=False)
        # lookalikes: among the 5th-30th closest photos to this build (the very closest are often twins)
        so = set(other)
        close = [j for j in np.argsort(-sim[i]) if j in so][4:30]
        hard = rng.choice(close, size=min(n_hard, len(close)), replace=False) if close else []
        for j in list(rand) + list(hard):
            X.append(H.pair(P[j], B[i]))
            y.append(0)
            w.append(1)
    return np.stack(X), np.array(y), np.array(w, float)


def auc(pos, neg):
    pos, neg = np.asarray(pos), np.asarray(neg)
    if not len(pos) or not len(neg):
        return None
    return float(((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean()))


def fit_all(its, feat, rng):
    """The four heads, trained on these vehicles."""
    col = [(it["photo"], it["colour"]) for it in its if it.get("colour")]
    col += [(it["build"], it["build_colour"]) for it in its if it.get("build_colour")]
    Xc = np.hstack([stack(feat, [f for f, _ in col], 0), stack(feat, [f for f, _ in col], 2)])
    sd = [(it["photo"], it["side"]) for it in its if it.get("side")]
    Xs = np.vstack([stack(feat, [f for f, _ in sd], 0), stack(feat, [f for f, _ in sd], 1)])
    ys = [s for _, s in sd] + [FLIP[s] for _, s in sd]
    kd = [(it["photo"], it["kind"]) for it in its] + [(it["build"], it["kind"]) for it in its if it.get("build")]
    return {
        "colour": H.Head.fit(Xc, [c for _, c in col], C=C["colour"]),
        "side": H.Head.fit(Xs, ys, C=C["side"]),
        "kind": H.Head.fit(stack(feat, [f for f, _ in kd], 0), [k for _, k in kd], C=C["kind"], class_weight="balanced"),
        "match": fit_match(its, feat, rng),
    }


def fit_match(its, feat, rng):
    Xm, ym, wm = match_pairs(its, feat, rng)
    return H.Head.fit(Xm, ym, C=C["match"], sample_weight=wm, class_weight="balanced")


def near(a, b, limit=25.0):
    """Two families whose paints are within LIMIT (CIE76) of each other: grey and dark grey, white and pearl."""
    la, lb = dataset._lab([dataset.FAMILY[a], dataset.FAMILY[b]])
    return a == b or float(np.linalg.norm(la - lb)) < limit


def evaluate(hs, its, feat, rng):
    """Each head's score on these (held-out) vehicles."""
    out = {}
    for src, lab in (("photo", "colour"), ("build", "build_colour")):
        xs = [it for it in its if it.get(lab)]
        X = np.hstack([stack(feat, [it[src] for it in xs], 0), stack(feat, [it[src] for it in xs], 2)])
        p = hs["colour"].proba(X)
        pred = [hs["colour"].classes[i] for i in p.argmax(1)]
        top3 = [[hs["colour"].classes[i] for i in np.argsort(-r)[:3]] for r in p]
        ys = [it[lab] for it in xs]
        out[f"colour_{src}"] = {
            "n": len(xs), "right": round(np.mean([a == b for a, b in zip(pred, ys)]), 3),
            "right_or_next_shade": round(np.mean([near(a, b) for a, b in zip(pred, ys)]), 3),
            "in_top_3": round(np.mean([y in t for y, t in zip(ys, top3)]), 3),
            "mistakes": collections.Counter(f"{y}->{a}" for a, y in zip(pred, ys) if a != y).most_common(8)}
    for src in ("photo", "build"):
        xs = [it for it in its if it.get("side") and it.get(src)]
        fs = [it[src] for it in xs]
        p = H.side_proba(hs["side"], stack(feat, fs, 0), stack(feat, fs, 1))
        pred = [hs["side"].classes[i] for i in p.argmax(1)]
        out[f"side_{src}"] = {"n": len(xs), "right": round(np.mean([a == it["side"] for a, it in zip(pred, xs)]), 3)}
    for src in ("photo", "build"):
        xs = [it for it in its if it.get(src)]
        p = hs["kind"].proba(stack(feat, [it[src] for it in xs], 0))
        pred = [hs["kind"].classes[i] for i in p.argmax(1)]
        out[f"kind_{src}"] = {"n": len(xs), "right": round(np.mean([a == it["kind"] for a, it in zip(pred, xs)]), 3),
                              "mistakes": collections.Counter(f"{it['kind']}->{a}" for a, it in zip(pred, xs)
                                                              if a != it["kind"]).most_common(5)}
    Xm, ym, _ = match_pairs(its, feat, rng, real=0)
    pm = hs["match"].proba(Xm)[:, 1]
    out["match_pairs"] = {"n_own": int(ym.sum()), "n_other": int((ym == 0).sum()),
                          "auc": round(auc(pm[ym == 1], pm[ym == 0]), 3),
                          "right_at_0.5": round(float(np.mean((pm > 0.5) == (ym == 1))), 3)}
    return out


def reviewed(scored, th):
    """The match head's scores (from heads that did not see the vehicle) on the builds the reviewers judged
    and on the stand-ins, and how many of each fall below the threshold TH."""
    def block(ok, shape):
        ok, shape = np.array(ok), np.array(shape)
        return {"n_ok": len(ok), "n_wrong_shape": len(shape), "auc": round(auc(ok, shape), 3) if len(shape) else None,
                "wrong_shape_flagged": round(float(np.mean(shape < th)), 3) if len(shape) else None,
                "ok_flagged": round(float(np.mean(ok < th)), 3) if len(ok) else None}
    cur = [(s, it) for s, it in scored if it.get("verdict")]
    ok = [s for s, it in cur if it["verdict"] == "ok"]
    out = {"threshold": round(th, 3),
           "on_their_builds_now": block(ok, [s for s, it in cur if set(it["faults"]) & dataset.SHAPE_FAULTS]),
           "any_shape_fault_recorded": block(ok, [s for s, it in scored if it.get("shape_fault_ever")])}
    own = np.array([s for s, it in scored if not it.get("standin") and not it.get("shape_fault_ever")])
    st = np.array([s for s, it in scored if it.get("standin")])
    out["own_model_vs_standin"] = {"n_own_model": len(own), "n_standin": len(st), "auc": round(auc(own, st), 3),
                                   "own_model_flagged": round(float(np.mean(own < th)), 3),
                                   "standin_flagged": round(float(np.mean(st < th)), 3)}
    out["on_their_builds_now"]["wrong_shape"] = sorted(
        (round(s, 3), it["key"]) for s, it in cur if set(it["faults"]) & dataset.SHAPE_FAULTS)
    out["lowest_not_found_wrong"] = sorted((round(s, 3), it["key"]) for s, it in scored
                                           if not it.get("shape_fault_ever") and it.get("verdict") != "bad")[:15]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoder", default=None, help="the encoder's .onnx (default: fetched, see vision.py)")
    ap.add_argument("--cache", default=os.path.join(vision.home(), "cache"))
    ap.add_argument("--out", default=os.path.join(HERE, "heads.json"))
    a = ap.parse_args()
    enc = vision.Encoder(a.encoder)
    its = dataset.items()
    files = sorted({it[s] for it in its for s in ("photo", "build") if it.get(s)})
    print(f"{len(its)} vehicles, {len(files)} pictures", flush=True)
    feat = featurise(files, enc, a.cache)
    held = dataset.split([it["key"] for it in its])
    train_its = [it for it in its if it["key"] not in held]
    test_its = [it for it in its if it["key"] in held]
    hs = fit_all(train_its, feat, np.random.default_rng(0))
    test = evaluate(hs, test_its, feat, np.random.default_rng(1))
    # the reviewers' wrong-shape builds are few: every build is scored by heads trained without it
    # (five rounds, each holding out a fifth of the vehicles), and the match's threshold set from those scores
    keys = sorted(it["key"] for it in its)
    order = np.random.default_rng(7).permutation(len(keys))
    scored = []
    for r in range(5):
        fold = {keys[i] for i in order[r::5]}
        m5 = fit_match([it for it in its if it["key"] not in fold], feat, np.random.default_rng(r))
        for it in its:
            if it["key"] in fold and it.get("build"):
                p = m5.proba(H.pair(feat[it["photo"]][0], feat[it["build"]][0]))[0, 1]
                scored.append((float(p), it))
    # the threshold: one in ten builds of the photo's own model (not a stand-in, no shape fault) below it
    own = [s for s, it in scored if not it.get("standin") and not it.get("shape_fault_ever")]
    thresholds = {"sure": 0.6, "match": float(np.quantile(own, OWN_FLAGGED))}
    faults = reviewed(scored, thresholds["match"])
    final = fit_all(its, feat, np.random.default_rng(0))
    card = {
        "trained": time.strftime("%Y-%m-%d %H:%M:%S"), "encoder": os.path.basename(enc.path),
        "encoder_sha256": vision.file_sha256(enc.path),
        "examples": {"vehicles": len(its), "held_out": len(test_its),
                     "colour": sum(1 for it in its if it.get("colour")) + sum(1 for it in its if it.get("build_colour")),
                     "side": 2 * sum(1 for it in its if it.get("side")), "kind": len(files),
                     "reviewed_builds": sum(1 for it in its if it.get("verdict"))},
        "held_out_scores": test, "reviewers_wrong_shape_builds": faults,
        "paint": dataset.FAMILY, "thresholds": thresholds,
        "note": "Scores are on vehicles the heads were not trained on. The heads written were then trained on all.",
    }
    H.save(a.out, final, card)
    print(json.dumps({"held_out_scores": test, "reviewers_wrong_shape_builds": faults}, indent=1))
    print("written", a.out)


if __name__ == "__main__":
    main()
