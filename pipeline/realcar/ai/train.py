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
import words  # noqa: E402

paths = dataset.paths
FLIP = {"left": "right", "right": "left"}
C = {"colour": 100.0, "side": 100.0, "kind": 10.0, "match": 10.0, "vehicle": 10.0}
FOLDS = 5
# a build the reviewers found not the photo's vehicle weighs as this many made-up mismatches
# (tried 0, 1, 3, 10: 10 caught the reviewers' wrong builds best, held out)
REAL_WRONG = 10
# the share of builds of the photo's own model the match may flag: its threshold is set by it
OWN_FLAGGED = 0.1
# and of the stand-ins with no shape fault found: a stand-in is another model's body reshaped, never quite its
# photo, so it has its own threshold (one threshold for both flagged half the builds the reviewers passed)
STANDIN_FLAGGED = 0.1
# kind, side and colour count against a build only when both readings are this sure: photos read
# that surely were right this often, held out (for colour: its family or the next shade). The run's
# own labels, which its builds are made from, are right about 99 times in 100 (their gold checks):
# at 97 in 100 nine flags in ten on the run were the model's own misreadings
SURE_RIGHT = 0.99
# a photo from outside the run (--extra) counts this much of one of the run's: its kind and coarse colour are
# a person's (Commons' categories), its fine family the model's own guess within that colour
EXTRA_WEIGHT = 0.5
# the colour head also reads each picture's likeness to every family's words (words.py), this loud against the
# embedding and histogram: the run's photos read 74.8% right held out without them, 74.4% at 3, 78.1% at 10,
# 79.6% at 30. At 30 its answers are so sure that the surest wrong ones decide where SURE_RIGHT falls: set on
# one half of the vehicles no threshold reached it, and the phone's heads found none (colour never counted
# against a build there); at 10 it holds on both halves (picked on those same held-out scores)
WORDS_WEIGHT = 10.0


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
    os.makedirs(cache, exist_ok=True)

    def keep():                 # written as it goes: a stop loses at most the last few hundred pictures
        np.savez(store + ".part.npz", **old)
        os.replace(store + ".part.npz", store)
    t0 = time.time()
    for n in range(0, len(todo), 64):
        chunk = todo[n:n + 64]
        e, ef, h = H.features(enc, [f for _, f in chunk])
        for (i, _), a, b, c in zip(chunk, e, ef, h):
            old[i + ":e"], old[i + ":f"], old[i + ":h"] = a, b, c
        print(f"  pictures read: {min(n + 64, len(todo))}/{len(todo)} ({time.time() - t0:.0f} s)", flush=True)
        if (n // 64) % 5 == 4:
            keep()
    if todo:
        keep()
    return {f: (old[i + ":e"], old[i + ":f"], old[i + ":h"]) for i, f in zip(ids, files)}


def read_features(files, path, optional=()):
    """Features made elsewhere, keyed as the cache is (the picture's fingerprint): every picture must be there
    but the OPTIONAL ones, which are left out when they are not."""
    got = dict(np.load(path))
    ids = [paths.sha(f) for f in files]
    missing = [f for i, f in zip(ids, files) if i + ":e" not in got]
    if missing:
        raise SystemExit(f"train: {len(missing)} pictures have no features in {path}, e.g. {missing[:3]}")
    opt = [(paths.sha(f), f) for f in optional]
    if optional:
        print(f"  {sum(1 for i, _ in opt if i + ':e' in got)} of {len(opt)} extra photos have features in {path}")
    return {f: (got[i + ":e"], got[i + ":f"], got[i + ":h"]) for i, f in list(zip(ids, files)) + opt if i + ":e" in got}


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


def pseudo_label(hs, feat, extras):
    """Each extra photo's fine colour: the colour head HS's likeliest family within the photo's coarse group."""
    out = []
    for it in extras:
        if not it.get("families"):
            out.append({**it, "colour": None})
            continue
        e, _, h = feat[it["photo"]]
        p = hs["colour"].proba(np.concatenate([e, h]))[0]
        inside = [(p[i], c) for i, c in enumerate(hs["colour"].classes) if c in it["families"]]
        out.append({**it, "colour": max(inside)[1] if inside else it["families"][0]})
    return out


def fit_all(its, feat, rng, extras=(), T=None):
    """The heads, trained on these vehicles; the colour and kind heads also on EXTRAS (photos from outside
    the run, at EXTRA_WEIGHT each), their fine colour first guessed by heads trained on the run alone. With
    pictures of no vehicle among the extras (kind "none": extra/none.py), the vehicle head too: every other
    picture is a vehicle. With T (words.directions, the families' words), the colour head is fitted with each
    picture's likeness to them beside its numbers, and written folded (heads.fold_words): it reads the same
    numbers as one without."""
    if extras:
        extras = pseudo_label(fit_all(its, feat, rng, T=T), feat, extras)
    col = [(it["photo"], it["colour"], 1.0) for it in its if it.get("colour")]
    col += [(it["build"], it["build_colour"], 1.0) for it in its if it.get("build_colour")]
    col += [(it["photo"], it["colour"], EXTRA_WEIGHT) for it in extras if it.get("colour")]
    sd = [(it["photo"], it["side"]) for it in its if it.get("side")]
    kd = [(it["photo"], it["kind"], 1.0) for it in its]
    kd += [(it["build"], it["kind"], 1.0) for it in its if it.get("build") and not it.get("build_other_kind")]
    kd += [(it["photo"], it["kind"], EXTRA_WEIGHT) for it in extras if it["kind"] != "none"]
    vd = [(it[s], "vehicle") for it in its for s in ("photo", "build") if it.get(s)]
    vd += [(it["photo"], "none" if it["kind"] == "none" else "vehicle") for it in extras]
    Xm, ym, wm = match_pairs(its, feat, rng)
    for what, n in (("colour", len(col)), ("side", len(sd)), ("kind", len(kd)), ("match", int(ym.sum()))):
        if n < 10:
            raise SystemExit(f"train: {n} examples for the {what} head: too few to train it (check $F1K_HOME)")
    Xc = np.hstack([stack(feat, [f for f, _, _ in col], 0), stack(feat, [f for f, _, _ in col], 2)])
    if T is not None:
        Xc = np.hstack([Xc, words.likeness(Xc, T, WORDS_WEIGHT)])
    Xs = np.vstack([stack(feat, [f for f, _ in sd], 0), stack(feat, [f for f, _ in sd], 1)])
    ys = [s for _, s in sd] + [FLIP[s] for _, s in sd]
    vehicle = {}
    if any(v == "none" for _, v in vd):
        vehicle["vehicle"] = H.Head.fit(stack(feat, [f for f, _ in vd], 0), [v for _, v in vd], C=C["vehicle"],
                                        class_weight="balanced")
    colour = H.Head.fit(Xc, [c for _, c, _ in col], C=C["colour"], sample_weight=np.array([w for _, _, w in col]))
    return {
        **vehicle,
        "colour": colour if T is None else H.fold_words(colour, T, WORDS_WEIGHT),
        "side": H.Head.fit(Xs, ys, C=C["side"]),
        "kind": H.Head.fit(stack(feat, [f for f, _, _ in kd], 0), [k for _, k, _ in kd], C=C["kind"], class_weight="balanced",
                           sample_weight=np.array([w for _, _, w in kd])),
        "match": H.Head.fit(Xm, ym, C=C["match"], sample_weight=wm, class_weight="balanced"),
    }


def held_out(its, feat, fold_of, extras=(), T=None):
    """Every picture answered, and every build matched, by heads trained without its vehicle's fold
    (the extra photos too: answered as "extra", by heads trained on the other folds' extras)."""
    answers, scored, pairs_ = [], [], []
    for r in range(FOLDS):
        fold = [it for it in its if fold_of[it["key"]] == r]
        hs = fit_all([it for it in its if fold_of[it["key"]] != r], feat, np.random.default_rng(r),
                     [it for it in extras if fold_of[it["key"]] != r], T)
        for it in fold:
            for src in ("photo", "build"):
                if it.get(src):
                    answers.append((src, it, H.read(hs, dataset.FAMILY, feat[it[src]])))
            if it.get("build"):
                scored.append((it, hs))
        for it in extras:
            if fold_of[it["key"]] == r:
                answers.append(("extra", it, H.read(hs, dataset.FAMILY, feat[it["photo"]])))
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


def vehicle_scores(answers):
    """The vehicle head's held-out scores: the run's photos and builds and the extra vehicle photos read as a
    vehicle, the pictures of none (extra/none.py: photos by topic, and the pictures drawn there) read as none;
    and its threshold: the lowest p from which its "no vehicle" answers were right SURE_RIGHT of the time."""
    xs = [(s, it, a["vehicle"]) for s, it, a in answers if "vehicle" in a]
    if not xs:
        return {}, {}
    truth = lambda s, it: "no" if s == "extra" and it["kind"] == "none" else "yes"  # noqa: E731
    out = {}
    for name, pick in (("vehicle_run", lambda s, it: s in ("photo", "build")),
                       ("vehicle_extra", lambda s, it: s == "extra" and it["kind"] != "none"),
                       ("none_photos", lambda s, it: s == "extra" and it["kind"] == "none" and it.get("topic") != "made"),
                       ("none_made", lambda s, it: s == "extra" and it.get("topic") == "made")):
        sub = [(s, it, v) for s, it, v in xs if pick(s, it)]
        if sub:
            want = truth(*sub[0][:2])
            out[name] = {"n": len(sub), "right": r3(np.mean([v["answer"] == want for _, _, v in sub])),
                         "mistakes": collections.Counter(it.get("topic") or it.get("kind") or s for s, it, v in sub
                                                         if v["answer"] != want).most_common(8)}
    no = [(v["p"], truth(s, it) == "no") for s, it, v in xs if v["answer"] == "no"]
    t = threshold([p for p, _ in no], [r for _, r in no]) if no else 1.01
    above = [r for p, r in no if p >= t]
    out["vehicle_sure"] = {"threshold": r3(t), "no_vehicle_answers_this_sure": r3(len(above) / len(no)) if no else None,
                           "right_when_this_sure": r3(np.mean(above)) if above else None}
    return out, {"vehicle": t}


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
    out_v, th_v = vehicle_scores(answers)
    out.update(out_v)
    th.update(th_v)
    ex = [(it, a) for s, it, a in answers if s == "extra" and it["kind"] != "none"]
    if ex:                      # photos from outside the run: a person's kind and coarse colour, held out the same way
        ks = [it["kind"] for it, _ in ex]
        ck = collections.Counter(ks).most_common(1)[0][0]
        out["kind_extra"] = {"n": len(ex), "right": r3(np.mean([a["kind"]["answer"] == k for (_, a), k in zip(ex, ks)])),
                             "always_the_commonest": {"answer": ck, "right": r3(np.mean([k == ck for k in ks]))},
                             "mistakes": collections.Counter(f"{k}->{a['kind']['answer']}" for (_, a), k in zip(ex, ks)
                                                             if a["kind"]["answer"] != k).most_common(6)}
        ex = [(it, a) for it, a in ex if it.get("families")]
    if ex:
        gs = [it["group"] for it, _ in ex]
        cg = collections.Counter(gs).most_common(1)[0][0]
        out["colour_extra"] = {"n": len(ex), "right_group": r3(np.mean([a["colour"]["answer"] in it["families"] for it, a in ex])),
                               "always_the_commonest": {"answer": cg, "right_group": r3(np.mean([g == cg for g in gs]))},
                               "mistakes": collections.Counter(f"{it['group']}->{a['colour']['answer']}" for it, a in ex
                                                               if a["colour"]["answer"] not in it["families"]).most_common(10)}
    return out, th


def reviewed(scored, th, th_standin=None):
    """The match's held-out scores on the builds the reviewers judged and on the stand-ins, and how many of
    each are flagged: below TH, a stand-in below TH_STANDIN (its own threshold; TH too when None)."""
    th_standin = th if th_standin is None else th_standin
    low = lambda s, it: s < (th_standin if it.get("standin") else th)  # noqa: E731

    def block(ok, shape):
        return {"n_ok": len(ok), "n_wrong_shape": len(shape), "auc": r3(auc([s for s, _ in ok], [s for s, _ in shape])),
                "wrong_shape_flagged": r3(np.mean([low(s, it) for s, it in shape])) if shape else None,
                "ok_flagged": r3(np.mean([low(s, it) for s, it in ok])) if ok else None}
    cur = [(s, it) for s, it in scored if it.get("verdict")]
    ok = [(s, it) for s, it in cur if it["verdict"] == "ok"]
    now = [(s, it) for s, it in cur if set(it["faults"]) & dataset.SHAPE_FAULTS]
    out = {"threshold": r3(th), "threshold_standin": r3(th_standin),
           "on_their_builds_now": block(ok, now),
           "shape_fault_on_last_verdict": block(ok, [(s, it) for s, it in scored if it.get("shape_fault_last")]),
           "stand_ins_alone": {"now": block([(s, it) for s, it in ok if it.get("standin")],
                                            [(s, it) for s, it in now if it.get("standin")]),
                               "last_verdict": block([(s, it) for s, it in ok if it.get("standin")],
                                                     [(s, it) for s, it in scored if it.get("standin")
                                                      and it.get("shape_fault_last")])}}
    own = [(s, it) for s, it in scored if not it.get("standin") and not it.get("shape_fault_last")]
    st = [(s, it) for s, it in scored if it.get("standin")]
    out["own_model_vs_standin"] = {"n_own_model": len(own), "n_standin": len(st),
                                   "auc": r3(auc([s for s, _ in own], [s for s, _ in st])),
                                   "own_model_flagged": r3(np.mean([low(s, it) for s, it in own])) if own else None,
                                   "standin_flagged": r3(np.mean([low(s, it) for s, it in st])) if st else None}
    out["on_their_builds_now"]["wrong_shape"] = sorted((r3(s), it["key"]) for s, it in now)
    out["lowest_not_found_wrong"] = sorted((r3(s), it["key"]) for s, it in scored
                                           if not it.get("shape_fault_last") and it.get("verdict") != "bad")[:15]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoder", default=None, help="the encoders' .onnx files or names, comma-separated "
                    "(default vision.DEFAULT_ENCODERS, fetched)")
    ap.add_argument("--cache", default=os.path.join(vision.home(), "cache"))
    ap.add_argument("--out", default=os.path.join(HERE, "heads.json"))
    ap.add_argument("--review", default=None, help="the second opinion's file (default $F1K_HOME/ai_review.json)")
    ap.add_argument("--features", default=None, help="the pictures' features read elsewhere (web/features.py: the "
                    "phone page's own reading), instead of the encoder's here; --encoder names the encoder they came from")
    ap.add_argument("--extra", default=None, help="folders of photos from outside the run (extra/, comma-separated), "
                    "for the colour and kind heads")
    a = ap.parse_args()
    enc = vision.encoders(a.encoder)
    shas = [vision.file_sha256(p) for p in enc.path.split(",")]
    enc_sha = shas[0] if len(shas) == 1 else hashlib.sha256(",".join(shas).encode()).hexdigest()
    encoders = [{"name": next((n for n, v in vision.ENCODERS.items() if v[3] == sha), os.path.basename(p)),
                 "file": os.path.basename(p), "sha256": sha} for p, sha in zip(enc.path.split(","), shas)]
    its = dataset.items()
    extras = dataset.extra_items(a.extra) if a.extra else []
    files = sorted({it[s] for it in its for s in ("photo", "build") if it.get(s)})
    print(f"{len(its)} vehicles, {len(files)} pictures, {len(extras)} extra photos", flush=True)
    if a.features:
        feat = read_features(files, a.features, optional=[it["photo"] for it in extras])
        extras = [it for it in extras if it["photo"] in feat]
    else:
        feat = featurise(files + [it["photo"] for it in extras], enc, a.cache, enc_sha)
    looks = {it["key"]: vision.dhash(vision.load(it["photo"])) for it in its + extras}
    fold_of = dataset.folds(its + extras, FOLDS, looks)
    # the families' words, where the encoder's first numbers are SigLIP's (the words' own space)
    T = words.directions(list(dataset.FAMILY)) if encoders[0]["name"] in words.SPACE else None
    answers, scored, pairs_ = held_out(its, feat, fold_of, extras, T)
    test, th = scores(answers, fold_of)
    pm = [float(hs["match"].proba(H.pair(feat[it["photo"]][0], feat[it["build"]][0]))[0, 1]) for it, hs in scored]
    # the match's threshold: one in ten builds of the photo's own model (not a stand-in, no shape fault) below it
    own = [s for s, (it, _) in zip(pm, scored) if not it.get("standin") and not it.get("shape_fault_last")]
    th["match"] = float(np.quantile(own, OWN_FLAGGED)) if own else 0.5
    good_st = [s for s, (it, _) in zip(pm, scored) if it.get("standin") and not it.get("shape_fault_last")]
    th["match_standin"] = float(np.quantile(good_st, STANDIN_FLAGGED)) if good_st else th["match"]
    ps, ys = (np.array([p for p, _ in pairs_]), np.array([y for _, y in pairs_])) if pairs_ else (np.zeros(0), np.zeros(0))
    test["match_pairs"] = {"n_own": int(ys.sum()), "n_other": int((ys == 0).sum()), "auc": r3(auc(ps[ys == 1], ps[ys == 0]))}
    faults = reviewed(list(zip(pm, [it for it, _ in scored])), th["match"], th["match_standin"])
    # as it was: one threshold for both
    faults["one_threshold_for_both"] = {k: reviewed(list(zip(pm, [it for it, _ in scored])), th["match"])[k]
                                        for k in ("on_their_builds_now", "shape_fault_on_last_verdict")}
    # the same threshold rule, set on one half of the vehicles and tried on the other
    halves = np.array([fold_of[it["key"]] % 2 for it, _ in scored])
    own_of = np.array([not it.get("standin") and not it.get("shape_fault_last") for it, _ in scored])
    st_of = np.array([bool(it.get("standin")) for it, _ in scored])
    pm_ = np.array(pm)
    good_st_of = st_of & np.array([not it.get("shape_fault_last") for it, _ in scored])
    faults["set_on_one_half_tried_on_the_other"] = [
        {"threshold": r3(t), "own_model_flagged": r3(np.mean(pm_[(halves != h) & own_of] < t)),
         "threshold_standin": r3(ts), "good_standin_flagged": r3(np.mean(pm_[(halves != h) & good_st_of] < ts))}
        for h in (0, 1) for t, ts in [(float(np.quantile(pm_[(halves == h) & own_of], OWN_FLAGGED)),
                                       float(np.quantile(pm_[(halves == h) & good_st_of], STANDIN_FLAGGED)))]]
    faults["standin_share"] = r3(st_of.mean())
    # against the encoder untrained: the photo's and the build's embeddings' cosine, the same threshold rule
    raw = [float(cos(feat[it["photo"]][0], feat[it["build"]][0])) for it, _ in scored]
    raw_th = float(np.quantile([c for c, o in zip(raw, own_of) if o], OWN_FLAGGED))
    raw_ts = float(np.quantile([c for c, o in zip(raw, good_st_of) if o], STANDIN_FLAGGED))
    rr = reviewed(list(zip(raw, [it for it, _ in scored])), raw_th, raw_ts)
    faults["untrained_cosine"] = {"threshold": rr["threshold"], "threshold_standin": rr["threshold_standin"],
                                  "on_their_builds_now": {k: v for k, v in rr["on_their_builds_now"].items()
                                                          if k != "wrong_shape"},
                                  "shape_fault_on_last_verdict": rr["shape_fault_on_last_verdict"],
                                  "own_model_vs_standin": rr["own_model_vs_standin"]}
    trained = time.strftime("%Y-%m-%d %H:%M:%S")
    second = {}
    for it, hs in scored:
        v = H.judge(hs, th, dataset.FAMILY, feat[it["photo"]], feat[it["build"]], standin=bool(it.get("standin")))
        second[it["key"]] = {**v, "photo_sha": paths.sha(it["photo"]), "build_sha": paths.sha(it["build"]),
                             "heads": trained, "by": "heads trained without this vehicle",
                             "reviewers": it.get("verdict")}
    final = fit_all(its, feat, np.random.default_rng(0), extras, T)
    card = {
        "trained": trained, "encoder": "+".join(e["file"] for e in encoders), "encoder_sha256": enc_sha,
        "encoders": encoders,
        "features": "read by " + (a.features and os.path.basename(a.features) or "onnxruntime here"),
        "examples": {"vehicles": len(its), "pictures": len(files),
                     "colour": sum(1 for it in its if it.get("colour")) + sum(1 for it in its if it.get("build_colour")),
                     "side": 2 * sum(1 for it in its if it.get("side")),
                     "reviewed_builds": sum(1 for it in its if it.get("verdict")),
                     "extra_photos": len(extras), "extra_weight": EXTRA_WEIGHT if extras else None,
                     "extra_sources": collections.Counter(it["source"] for it in extras).most_common(),
                     "extra_licences": collections.Counter(it["licence"] for it in extras).most_common(8),
                     "extra_kinds": collections.Counter(it["kind"] for it in extras).most_common()},
        "held_out_scores": test, "reviewers_wrong_shape_builds": faults,
        "paint": dataset.FAMILY, "thresholds": th,
        "colour_words": None if T is None else {"model": words.TEXT["siglip-b16-text.onnx"][0],
                                                "weight": WORDS_WEIGHT, "templates": words.TEMPLATES,
                                                "how": "fitted with the likeness to each family's words, folded "
                                                       "into the embedding's weights (heads.fold_words)"},
        "note": f"Scores are held out: every vehicle answered by heads trained on the other {FOLDS - 1} of "
                f"{FOLDS} folds. The heads written were then trained on all. Some settings (C, REAL_WRONG, "
                f"SURE_RIGHT, WORDS_WEIGHT) were picked after looking at these same held-out scores: they may flatter "
                f"them a little.",
    }
    H.save(a.out, final, card)
    seen = sorted({vision.dhash(vision.load(f)) for f in files} | {looks[it["key"]] for it in extras})
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
