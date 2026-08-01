"""Prove _ground_z on real staged GLBs before it ships.

Pulls the per-mesh bounding-box minima straight out of the GLB with trimesh and
runs the same arithmetic the handler runs, so the thresholds are tested against
the geometry that actually broke rather than against invented numbers.

A pass means: the 2017 Golf's floor climbs off its stray and onto the tyres,
and every model that was already sitting correctly is left exactly where it was.
"""
import json, os, sys, urllib.request
import numpy as np
import trimesh

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
_STRAY_GAP, _STRAY_MASS, _STRAY_MAX = 0.05, 0.01, 0.30


def load_env(path="/root/.alam3d_env"):
    try:
        body = open(path).read()
    except OSError:
        return
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        n, sep, v = line.partition("=")
        if sep and not os.environ.get(n.strip()):
            os.environ[n.strip()] = v.strip().strip("'\"")


load_env()
K = os.environ["SB_KEY"]


def ground_z(ms):
    """ms = [(bbox_min_on_up_axis, faces)]. Mirrors handler._ground_z."""
    if not ms:
        return 0.0
    ms = sorted(ms, key=lambda t: t[0])
    spread = ms[-1][0] - ms[0][0]
    total = sum(f for _, f in ms)
    if spread <= 0 or total <= 0:
        return ms[0][0]
    floor, cum = ms[0][0], 0
    for i in range(len(ms) - 1):
        cum += ms[i][1]
        if (ms[i + 1][0] - ms[i][0]) > _STRAY_GAP * spread \
                and cum <= _STRAY_MASS * total \
                and (ms[i + 1][0] - ms[0][0]) <= _STRAY_MAX * spread:
            floor = ms[i + 1][0]
            continue
        break
    return floor


def minima(uid, stage="staging/vwfull"):
    rq = urllib.request.Request(f"{SB}/storage/v1/object/car-meshes/{stage}/{uid}.glb",
                                headers={"apikey": K, "Authorization": "Bearer " + K})
    blob = urllib.request.urlopen(rq, timeout=900).read()
    sc = trimesh.load(trimesh.util.wrap_as_stream(blob), file_type="glb",
                      force="scene", process=False)
    per = []
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        g = sc.geometry.get(gname)
        if g is None or g.bounds is None:
            continue
        lo, hi = g.bounds
        c = np.array([[x, y, z] for x in (lo[0], hi[0])
                      for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        w = (T[:3, :3] @ c.T).T + T[:3, 3]
        per.append((w.min(axis=0), w.max(axis=0), len(g.faces)))
    # Pick the up axis from BULK geometry only. The stray being tested for is
    # exactly the thing that distorts a whole-scene span -- on the 2017 Golf it
    # inflates the true up axis past the width axis, so a naive argmin picks the
    # wrong one and the test reports a false pass. Blender does not need this
    # guess (glTF import fixes up to Z); only this harness does.
    total_f = sum(p[2] for p in per) or 1
    bulk = [p for p in per if p[2] >= 0.005 * total_f] or per
    lo_b = np.min([p[0] for p in bulk], axis=0)
    hi_b = np.max([p[1] for p in bulk], axis=0)
    up = int(np.argmin(hi_b - lo_b))
    span = np.max([p[1] for p in per], axis=0) - np.min([p[0] for p in per], axis=0)
    span[up] = (hi_b - lo_b)[up]      # report the car's height, not the stray's
    return [(float(p[0][up]), p[2]) for p in per], up, span


CASES = [
    ("P014 Golf 2017  (stray Object_177)", "0fcad8513cc248008fbd6c19d12ebb1f", True),
    ("P013 Golf GTI 2014", "bfb760393b0f4b6ea6ca2babea3b8a10", False),
    ("P001 Beetle 1950", "af3c44cbc02342369285a4f47bd604bb", False),
    ("P010 Fox 2004", "2673fe0f4af14326abbdb5b8d704b4e7", False),
]

if __name__ == "__main__":
    only = sys.argv[1:] or None
    bad = 0
    for label, uid, expect_move in CASES:
        if only and uid not in only:
            continue
        try:
            ms, up, span = minima(uid)
        except Exception as e:
            print(f"{label:38s} FETCH {type(e).__name__}: {str(e)[:60]}")
            continue
        blind = min(m[0] for m in ms)
        fixed = ground_z(ms)
        moved = abs(fixed - blind) > 1e-9
        height = float(span[up])
        ok = (moved == expect_move)
        bad += not ok
        print(f"{label:38s} up=ax{up} h={height:8.3f} "
              f"blind={blind:9.3f} fixed={fixed:9.3f} "
              f"lift={fixed - blind:7.3f} ({100 * (fixed - blind) / height:5.1f}% of height) "
              f"{'MOVED' if moved else 'unchanged':10s} {'ok' if ok else 'FAIL'}")
    print("\n%s" % ("all cases behaved as expected" if not bad else f"{bad} CASE(S) WRONG"))
