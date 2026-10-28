"""train.py: train the heads on the run's own answers, score them on vehicles they did not see, write heads.json.

    F1K_HOME=/path/to/f1k python3 pipeline/realcar/ai/train.py [--encoder FILE] [--cache DIR] [--out FILE]

Every vehicle is in one of five folds (dataset.folds: vehicles sharing a picture share a fold).
Five times over, the heads are trained on four folds and answer for the
fifth, so every photo and build is answered by heads that never saw it:
those answers are the scores in heads.json's card, they set each head's
threshold, and they are the run's second opinion, $F1K_HOME/ai_review.json
(predict.py run keeps them, and checks with the final heads only what was
built after). The heads written are then trained on every vehicle.

Needs numpy, pillow, onnxruntime and scikit-learn; about 5 minutes on 4 CPUs
the first time (reading the run's 1,650 pictures), a few minutes after: what
the encoder makes of each picture is kept in the cache.
"""
import argparse
import collections
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

paths = dataset.paths
FLIP = {"left": "right", "right": "left"}
C = {"colour": 100.0, "side": 100.0, "kind": 10.0, "match": 10.0}
FOLDS = 5
# a build the reviewers found not the photo's vehicle weighs as this many made-up mismatches
# (tried 0, 1, 3, 10: 10 caught the reviewers' wrong builds best, held out)
REAL_WRONG = 10
# the share of builds of the photo's own model the match may flag: its threshold is set by it
OWN_FLAGGED = 0.1
# kind, side and colour count against a build only when both readings are this sure: photos read
# that surely were right this often, held out (for colour: its family or the next shade). The run's
# own labels, which its builds are made from, are right about 99 times in 100 (their gold checks):
# at 97 in 100 nine flags in ten on the run were the model's own misreadings
SURE_RIGHT = 0.99


def r3(x):
    return None if x is None else round(float(x), 3)


def cache_file(cache, encoder_sha):
    """Features made by this encoder and this version of the reading: another of either is another file."""
    return os.path.join(cache, f"features-v{H.FEATURES_VERSION}-{encoder_sha[:12]}.npz")


def featurise(files, enc, cache, encoder_sha):
    """(embedding, mirrored embedding, colour histogram) for every file, from the cache where it is there."""
    store = cache_file(cache, encoder_sha)
    old = dict(np.load(store)) if os.path.exists(store) else {}
    ids = [paths.sha(f) for f in files]
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


def read_features(files, path):
    """Features made elsewhere, keyed as the cache is (the picture's fingerprint): every picture must be there."""
    got = dict(np.load(path))
    ids = [paths.sha(f) for f in files]
    missing = [f for i, f in zip(ids, files) if i + ":e" not in got]
    if missing:
        raise SystemExit(f"train: {len(missing)} pictures have no features in {path}, e.g. {missing[:3]}")
    return {f: (got[i + ":e"], got[i + ":f"], got[i + ":h"]) for i, f in zip(ids, files)}


def stack(feat, files, part):
    return np.stack([feat[f][part] for f in files])


def model_of(it):
    return f"{it.get('make')}|{it.get('model')}".lower()


def wrong_shape(it):
    return it.get("shape_fault_last") or bool(set(it.get("faults") or []) & dataset.SHAPE_FAULTS)


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
        wrong = wrong_shape(it)
        if not wrong or real:
            X.append(H.pair(P[i], B[i]))
            y.append(0 if wrong else 1)
            w.append(real if wrong else 1)
        other = [j for j in range(len(own)) if model_of(own[j]) != model_of(it)]
        if not other:
            continue
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


def cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def auc(pos, neg):
    """The chance a POS score is above a NEG one (ties half): None when either is empty."""
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if not len(pos) or not len(neg):
        return None
    return float(((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean()))


def fit_all(its, feat, rng):
    """The four heads, trained on these vehicles."""
    col = [(it["photo"], it["colour"]) for it in its if it.get("colour")]
    col += [(it["build"], it["build_colour"]) for it in its if it.get("build_colour")]
    sd = [(it["photo"], it["side"]) for it in its if it.get("side")]
    kd = [(it["photo"], it["kind"]) for it in its] + [(it["build"], it["kind"]) for it in its if it.get("build")]
    Xm, ym, wm = match_pairs(its, feat, rng)
    for what, n in (("colour", len(col)), ("side", len(sd)), ("kind", len(kd)), ("match", int(ym.sum()))):
        if n < 10:
            raise SystemExit(f"train: {n} examples for the {what} head: too few to train it (check $F1K_HOME)")
    Xc = np.hstack([stack(feat, [f for f, _ in col], 0), stack(feat, [f for f, _ in col], 2)])
    Xs = np.vstack([stack(feat, [f for f, _ in sd], 0), stack(feat, [f for f, _ in sd], 1)])
    ys = [s for _, s in sd] + [FLIP[s] for _, s in sd]
    return {
        "colour": H.Head.fit(Xc, [c for _, c in col], C=C["colour"]),
        "side": H.Head.fit(Xs, ys, C=C["side"]),
        "kind": H.Head.fit(stack(feat, [f for f, _ in kd], 0), [k for _, k in kd], C=C["kind"], class_weight="balanced"),
        "match": H.Head.fit(Xm, ym, C=C["match"], sample_weight=wm, class_weight="balanced"),
    }


def held_out(its, feat, fold_of):
    """Every picture answered, and every build matched, by heads trained without its vehicle's fold."""
    answers, scored, pairs_ = [], [], []
    for r in range(FOLDS):
        fold = [it for it in its if fold_of[it["key"]] == r]
        hs = fit_all([it for it in its if fold_of[it["key"]] != r], feat, np.random.default_rng(r))
        for it in fold:
            for src in ("photo", "build"):
                if it.get(src):
                    answers.append((src, it, H.read(hs, dataset.FAMILY, feat[it[src]])))
            if it.get("build"):
                scored.append((it, hs))
        Xm, ym, _ = match_pairs(fold, feat, np.random.default_rng(100 + r), real=0)
        if len(ym):
            pairs_ += list(zip(hs["match"].proba(Xm)[:, 1], ym))
    return answers, scored, pairs_


def threshold(ps, rights, want=SURE_RIGHT, at_least=20):
    """The lowest p from which answers were right WANT of the time (at least AT_LEAST of them): above 1 if none."""
    ps, rights = np.asarray(ps, float), np.asarray(rights, bool)
    for t in np.unique(ps):
        above = ps >= t
        if above.sum() >= at_least and rights[above].mean() >= want:
            return float(t)
    return 1.01


def split_half(ps, rights, halves, pick):
    """A threshold set on one half of the vehicles (HALVES: by fold) and tried on the other, both ways round:
    whether answers that sure are as right on vehicles it was not set on."""
    ps, rights, halves = np.asarray(ps, float), np.asarray(rights, bool), np.asarray(halves)
    out = []
    for h in (0, 1):
        t = pick(ps[halves == h], rights[halves == h])
        p, r = ps[halves != h], rights[halves != h]
        above = p >= t
        out.append({"threshold": r3(t), "photos_this_sure": r3(above.mean()) if len(p) else None,
                    "right_when_this_sure": r3(r[above].mean()) if above.any() else None})
    return out


def scores(answers, fold_of):
    """Each head's held-out scores on photos and on builds, against always giving the commonest answer,
    and its threshold (tried on the half of the vehicles it was not set on)."""
    truth = {"photo": {"kind": "kind", "side": "side", "colour": "colour"},
             "build": {"kind": "kind", "side": "side", "colour": "build_colour"}}
    out, th = {}, {}
    for what in ("kind", "side", "colour"):
        ps, rights, halves = [], [], []
        for src in ("photo", "build"):
            xs = [(it, a[what]) for s, it, a in answers if s == src and it.get(truth[src][what])]
            if not xs:
                continue
            ys = [it[truth[src][what]] for it, _ in xs]
            got = [a["answer"] for _, a in xs]
            right = [g == y for g, y in zip(got, ys)]
            common = collections.Counter(ys).most_common(1)[0][0]
            o = {"n": len(xs), "right": r3(np.mean(right)),
                 "always_the_commonest": {"answer": common, "right": r3(np.mean([y == common for y in ys]))},
                 "mistakes": collections.Counter(f"{y}->{g}" for g, y in zip(got, ys) if g != y).most_common(8)}
            if what == "kind":          # motorbikes are easy (built in code, two wheels): cars and vans alone
                cv = [(g, y) for g, y in zip(got, ys) if y in ("car", "van")]
                o["cars_and_vans"] = {"n": len(cv), "right": r3(np.mean([g == y for g, y in cv])),
                                      "always_car": r3(np.mean([y == "car" for _, y in cv]))}
            if what == "colour":        # from here on, right is its family or the next shade
                right = [H.next_shade(dataset.FAMILY, g, y) for g, y in zip(got, ys)]
                o["right_or_next_shade"] = r3(np.mean(right))
                o["always_the_commonest"]["right_or_next_shade"] = r3(np.mean([H.next_shade(dataset.FAMILY, common, y)
                                                                                for y in ys]))
                o["in_top_3"] = r3(np.mean([y in [c for c, _ in a["top3"]] for (_, a), y in zip(xs, ys)]))
            out[f"{what}_{src}"] = o
            if src == "photo":          # the harder of the two to read: sure enough on photos is surer on builds
                ps, rights = [a["p"] for _, a in xs], right
                halves = [fold_of[it["key"]] % 2 for it, _ in xs]
        th[what] = threshold(ps, rights)
        above = np.asarray(ps) >= th[what]
        out[f"{what}_sure"] = {"threshold": r3(th[what]), "photos_this_sure": r3(above.mean()) if ps else None,
                               "right_when_this_sure": r3(np.asarray(rights)[above].mean()) if above.any() else None,
                               "set_on_one_half_tried_on_the_other": split_half(ps, rights, halves, threshold)}
    return out, th


def reviewed(scored, th):
    """The match's held-out scores on the builds the reviewers judged and on the stand-ins,
    and how many of each fall below the threshold TH."""
    def block(ok, shape):
        ok, shape = np.array(ok, float), np.array(shape, float)
        return {"n_ok": len(ok), "n_wrong_shape": len(shape), "auc": r3(auc(ok, shape)),
                "wrong_shape_flagged": r3(np.mean(shape < th)) if len(shape) else None,
                "ok_flagged": r3(np.mean(ok < th)) if len(ok) else None}
    cur = [(s, it) for s, it in scored if it.get("verdict")]
    ok = [s for s, it in cur if it["verdict"] == "ok"]
    now = [(s, it) for s, it in cur if set(it["faults"]) & dataset.SHAPE_FAULTS]
    out = {"threshold": r3(th),
           "on_their_builds_now": block(ok, [s for s, _ in now]),
           "shape_fault_on_last_verdict": block(ok, [s for s, it in scored if it.get("shape_fault_last")])}
    own = np.array([s for s, it in scored if not it.get("standin") and not it.get("shape_fault_last")], float)
    st = np.array([s for s, it in scored if it.get("standin")], float)
    out["own_model_vs_standin"] = {"n_own_model": len(own), "n_standin": len(st), "auc": r3(auc(own, st)),
                                   "own_model_flagged": r3(np.mean(own < th)) if len(own) else None,
                                   "standin_flagged": r3(np.mean(st < th)) if len(st) else None}
    out["on_their_builds_now"]["wrong_shape"] = sorted((r3(s), it["key"]) for s, it in now)
    out["lowest_not_found_wrong"] = sorted((r3(s), it["key"]) for s, it in scored
                                           if not it.get("shape_fault_last") and it.get("verdict") != "bad")[:15]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoder", default=None, help="the encoder's .onnx (default: fetched, see vision.py)")
    ap.add_argument("--cache", default=os.path.join(vision.home(), "cache"))
    ap.add_argument("--out", default=os.path.join(HERE, "heads.json"))
    ap.add_argument("--review", default=None, help="the second opinion's file (default $F1K_HOME/ai_review.json)")
    ap.add_argument("--features", default=None, help="the pictures' features read elsewhere (web/features.py: the "
                    "phone page's own reading), instead of the encoder's here; --encoder names the encoder they came from")
    a = ap.parse_args()
    enc = vision.Encoder(a.encoder) if not a.features else type("Read", (), {"path": a.encoder or vision.fetch()})
    enc_sha = vision.file_sha256(enc.path)
    its = dataset.items()
    files = sorted({it[s] for it in its for s in ("photo", "build") if it.get(s)})
    print(f"{len(its)} vehicles, {len(files)} pictures", flush=True)
    feat = featurise(files, enc, a.cache, enc_sha) if not a.features else read_features(files, a.features)
    looks = {it["key"]: vision.dhash(vision.load(it["photo"])) for it in its}
    fold_of = dataset.folds(its, FOLDS, looks)
    answers, scored, pairs_ = held_out(its, feat, fold_of)
    test, th = scores(answers, fold_of)
    pm = [float(hs["match"].proba(H.pair(feat[it["photo"]][0], feat[it["build"]][0]))[0, 1]) for it, hs in scored]
    # the match's threshold: one in ten builds of the photo's own model (not a stand-in, no shape fault) below it
    own = [s for s, (it, _) in zip(pm, scored) if not it.get("standin") and not it.get("shape_fault_last")]
    th["match"] = float(np.quantile(own, OWN_FLAGGED)) if own else 0.5
    ps, ys = (np.array([p for p, _ in pairs_]), np.array([y for _, y in pairs_])) if pairs_ else (np.zeros(0), np.zeros(0))
    test["match_pairs"] = {"n_own": int(ys.sum()), "n_other": int((ys == 0).sum()), "auc": r3(auc(ps[ys == 1], ps[ys == 0]))}
    faults = reviewed(list(zip(pm, [it for it, _ in scored])), th["match"])
    # the same threshold rule, set on one half of the vehicles and tried on the other
    halves = np.array([fold_of[it["key"]] % 2 for it, _ in scored])
    own_of = np.array([not it.get("standin") and not it.get("shape_fault_last") for it, _ in scored])
    st_of = np.array([bool(it.get("standin")) for it, _ in scored])
    pm_ = np.array(pm)
    faults["set_on_one_half_tried_on_the_other"] = [
        {"threshold": r3(t), "own_model_flagged": r3(np.mean(pm_[(halves != h) & own_of] < t)),
         "standin_flagged": r3(np.mean(pm_[(halves != h) & st_of] < t))}
        for h in (0, 1) for t in [float(np.quantile(pm_[(halves == h) & own_of], OWN_FLAGGED))]]
    faults["standin_share"] = r3(st_of.mean())
    # against the encoder untrained: the photo's and the build's embeddings' cosine, the same threshold rule
    raw = [float(cos(feat[it["photo"]][0], feat[it["build"]][0])) for it, _ in scored]
    raw_th = float(np.quantile([c for c, o in zip(raw, own_of) if o], OWN_FLAGGED))
    rr = reviewed(list(zip(raw, [it for it, _ in scored])), raw_th)
    faults["untrained_cosine"] = {"threshold": rr["threshold"],
                                  "on_their_builds_now": {k: v for k, v in rr["on_their_builds_now"].items()
                                                          if k != "wrong_shape"},
                                  "shape_fault_on_last_verdict": rr["shape_fault_on_last_verdict"],
                                  "own_model_vs_standin": rr["own_model_vs_standin"]}
    trained = time.strftime("%Y-%m-%d %H:%M:%S")
    second = {}
    for it, hs in scored:
        v = H.judge(hs, th, dataset.FAMILY, feat[it["photo"]], feat[it["build"]])
        second[it["key"]] = {**v, "photo_sha": paths.sha(it["photo"]), "build_sha": paths.sha(it["build"]),
                             "heads": trained, "by": "heads trained without this vehicle",
                             "reviewers": it.get("verdict")}
    final = fit_all(its, feat, np.random.default_rng(0))
    card = {
        "trained": trained, "encoder": os.path.basename(enc.path), "encoder_sha256": enc_sha,
        "features": "read by " + (a.features and os.path.basename(a.features) or "onnxruntime here"),
        "examples": {"vehicles": len(its), "pictures": len(files),
                     "colour": sum(1 for it in its if it.get("colour")) + sum(1 for it in its if it.get("build_colour")),
                     "side": 2 * sum(1 for it in its if it.get("side")),
                     "reviewed_builds": sum(1 for it in its if it.get("verdict"))},
        "held_out_scores": test, "reviewers_wrong_shape_builds": faults,
        "paint": dataset.FAMILY, "thresholds": th,
        "note": f"Scores are held out: every vehicle answered by heads trained on the other {FOLDS - 1} of "
                f"{FOLDS} folds. The heads written were then trained on all. Some settings (C, REAL_WRONG, "
                f"SURE_RIGHT) were picked after looking at these same held-out scores: they may flatter "
                f"them a little.",
    }
    H.save(a.out, final, card)
    seen = sorted({vision.dhash(vision.load(f)) for f in files})
    with open(os.path.join(os.path.dirname(os.path.abspath(a.out)), "train_pictures.json"), "w") as fh:
        json.dump({"about": "vision.dhash of every picture the heads were trained on (photos and builds): "
                            "a photo within ~10 bits of one of these was trained on", "dhash": seen}, fh)
    review = a.review or paths.f("ai_review.json")
    paths.save(review, second)
    print(json.dumps({"held_out_scores": test, "reviewers_wrong_shape_builds": faults, "thresholds": th}, indent=1))
    look = [k for k, v in second.items() if v["answer"] == "look"]
    print(f"written {a.out}; {review}: {len(second)} builds, {len(look)} to look at")


if __name__ == "__main__":
    main()
