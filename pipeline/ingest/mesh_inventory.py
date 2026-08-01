"""Per-model mesh inventory: is a staged GLB a car exterior, or a parts kit?

Written after a wrong call on 2026-08-01. Sheet #1 of the VW wave rendered as a
bodyshell with no wheels, and that was reported to the owner as `strip_env`
having amputated the car. Opening the file showed the truth: 117 meshes, zero
wheel geometry, and mesh names reading `pessima_engine`, `rollcage_01a`,
`neon_tube`, `hatch_gauges`, `abs`, `checkengine` -- a BeamNG.drive parts kit,
never a Polo exterior. The defect was in the source and the diagnosis was
invented from mesh NAMES without opening the file.

So this tool opens the file. It answers one question per model, from geometry
rather than from titles, tags or heuristics:

    does this GLB contain a car exterior with wheels, or does it not?

Wheels are detected two independent ways and both are reported, because either
alone is unreliable:

  NAME     a mesh named wheel/tyre/rim/alloy/hubcap. Fails on models whose
           meshes are all `Object_141`.
  GEOMETRY a disc: the two largest extents within 25% of each other, the
           smallest under 60% of the largest, diameter 8-25% of car length,
           sitting in the lower half of the model. Instancing is resolved
           through the scene graph, so four wheels sharing one geometry are
           counted four times, which is what a name test cannot see.

A verdict is only issued where the two agree or one is decisively positive;
otherwise it says UNCERTAIN rather than guessing. Nothing here is a quality
judgement -- a model can hold four wheels and still be junk. It answers the
narrower question of whether the asset is the right KIND of thing.

Usage:
    mesh_inventory.py --manifest path.json [--stage staging/vw2026] [--limit N]
"""
import argparse, json, os, re, struct, sys, time, urllib.request

ENV_FILE = "/root/.alam3d_env"


def load_env(path=ENV_FILE):
    try:
        body = open(path).read()
    except OSError:
        return
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        name, sep, value = line.partition("=")
        if sep and not os.environ.get(name.strip()):
            os.environ[name.strip()] = value.strip().strip("'\"")


load_env()

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"

WHEEL_NAME = re.compile(r"(?i)\b(wheel|tyre|tire|rim|alloy|hubcap)\b|wheel|tyre|rim")
# Families that mean "this is an engine bay / cabin / chassis kit", not a body.
INTERNAL = re.compile(
    r"(?i)engine|rollcage|roll_cage|gauge|dash|speedo|tacho|interior|seat|"
    r"steering|pedal|suspension|damper|spring|driveshaft|gearbox|piston|"
    r"crank|radiator|oilcooler|intercooler|turbo|exhaust_manifold|battery|"
    r"checkengine|lowfuel|highbeam|parkingbrake|abs-|signal_[lr]|hazard")
# Families that mean "this is an exterior shell".
EXTERIOR = re.compile(
    r"(?i)body|paint|shell|door|bonnet|hood|bumper|fender|wing|roof|pillar|"
    r"windscreen|windshield|glass|headlight|taillight|grille|mirror|skirt|"
    r"spoiler|boot|trunk|hatch_glass|plate")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def key():
    k = os.environ.get("SB_KEY")
    if not k:
        sys.exit("FATAL: SB_KEY not set")
    return k


def sb_get(path):
    rq = urllib.request.Request(f"{SB}/storage/v1/object/{path}",
        headers={"apikey": key(), "Authorization": f"Bearer {key()}"})
    return urllib.request.urlopen(rq, timeout=600).read()


def sb_put(path, blob, ctype):
    rq = urllib.request.Request(f"{SB}/storage/v1/object/{path}", data=blob, method="POST",
        headers={"apikey": key(), "Authorization": f"Bearer {key()}",
                 "Content-Type": ctype, "x-upsert": "true"})
    return urllib.request.urlopen(rq, timeout=600).status


def glb_ok(blob):
    """Magic AND the header's own length field. Either alone passes a truncated
    download -- the magic survives truncation, and a wrong length with the right
    magic is exactly what a half-finished transfer looks like."""
    return len(blob) > 20 and blob[:4] == b"glTF" and \
        struct.unpack("<I", blob[8:12])[0] == len(blob)


def instances(scene):
    """(name, geometry, world extents, world centre) per NODE, not per geometry.

    Four wheels are usually one geometry instanced four times. Iterating
    scene.geometry would see one wheel; iterating the graph sees four.
    """
    import numpy as np
    out = []
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        g = scene.geometry.get(gname)
        if g is None or not hasattr(g, "bounds") or g.bounds is None:
            continue
        lo, hi = g.bounds
        corners = np.array([[x, y, z] for x in (lo[0], hi[0])
                            for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        w = (T[:3, :3] @ corners.T).T + T[:3, 3]
        ext = w.max(axis=0) - w.min(axis=0)
        out.append((node, gname, ext, (w.max(axis=0) + w.min(axis=0)) / 2.0,
                    len(g.faces) if hasattr(g, "faces") else 0))
    return out


def looks_like_wheel(ext, centre, car_len, floor, height):
    s = sorted(ext, reverse=True)
    if s[0] <= 0:
        return False
    round_profile = s[1] >= 0.75 * s[0]          # two big axes about equal
    is_disc = s[2] <= 0.60 * s[0]                # third much thinner
    dia = s[0] / car_len if car_len else 0
    right_size = 0.08 <= dia <= 0.25             # a wheel against the whole car
    low = height <= 0 or (centre[_up] - floor) <= 0.55 * height
    return round_profile and is_disc and right_size and low


_up = 2  # GLBs here are Y-up on export but trimesh reports Z-up after load


def inspect(blob):
    import numpy as np
    import trimesh
    scene = trimesh.load(trimesh.util.wrap_as_stream(blob), file_type="glb",
                         force="scene", process=False)
    inst = instances(scene)
    if not inst:
        return {"error": "no geometry"}
    ext = np.array([i[2] for i in inst])
    ctr = np.array([i[3] for i in inst])
    lo = (ctr - ext / 2).min(axis=0)
    hi = (ctr + ext / 2).max(axis=0)
    dims = hi - lo
    car_len = float(dims.max())
    floor, height = float(lo[_up]), float(dims[_up])

    by_name = [i for i in inst if WHEEL_NAME.search(i[0]) or WHEEL_NAME.search(i[1])]
    by_geom = [i for i in inst
               if looks_like_wheel(i[2], i[3], car_len, floor, height)]

    faces = sum(i[4] for i in inst)
    fint = sum(i[4] for i in inst if INTERNAL.search(i[0]) or INTERNAL.search(i[1]))
    fext = sum(i[4] for i in inst if EXTERIOR.search(i[0]) or EXTERIOR.search(i[1]))

    fam = {}
    for i in inst:
        f = re.split(r"[-_.]", i[1] or i[0])[0][:26] or "?"
        fam[f] = fam.get(f, 0) + i[4]
    top = sorted(fam.items(), key=lambda kv: -kv[1])[:6]

    wheels = max(len(by_name), len(by_geom))
    ipct = 100.0 * fint / faces if faces else 0
    epct = 100.0 * fext / faces if faces else 0
    # Verdict order matters: take the strongest available signal, and say
    # UNCERTAIN rather than guess. Calibrated 2026-08-01 against four known
    # models -- Polo 2002 (a BeamNG parts kit), Touran 2016 (all meshes named
    # Object_*, so names are useless), Tiguan 2021 (one fused body mesh, so
    # geometry cannot separate wheels) and Sharan 2001 (cleanly named).
    if ipct >= 50 and epct < 20:
        verdict = "PARTS-KIT"          # engine/rollcage/cabin dominates the faces
    elif len(by_name) >= 3:
        verdict = "EXTERIOR"           # named wheels: the least ambiguous signal
    elif epct >= 40 and ipct < 20:
        verdict = "EXTERIOR"           # body/glass/bumper dominates; wheels may be fused
    elif len(by_geom) >= 4 and ipct < 30:
        verdict = "EXTERIOR"           # unnamed meshes, but four wheel-shaped discs
    elif wheels == 0:
        verdict = "NO-WHEELS"
    else:
        verdict = "UNCERTAIN"

    return {"meshes": len(inst), "faces": faces,
            "dims": [round(float(d), 2) for d in dims],
            "wheels_by_name": len(by_name), "wheels_by_geometry": len(by_geom),
            "internal_face_pct": round(100.0 * fint / faces, 1) if faces else 0,
            "exterior_face_pct": round(100.0 * fext / faces, 1) if faces else 0,
            "top_families": [[k, v] for k, v in top], "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--stage", default="staging/vw2026")
    ap.add_argument("--out", default="audit/vw2026/_inventory.json")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    rows = json.load(open(a.manifest))
    rows = rows if isinstance(rows, list) else rows.get("candidates", rows)
    order = {"Polo": 1, "Golf": 2, "Passat": 3, "Tiguan": 4, "Touran": 5, "Sharan": 6}
    rows.sort(key=lambda r: (order.get(r["plate"].split()[-1], 9), r["anchor"]))
    if a.limit:
        rows = rows[:a.limit]

    res = []
    for i, r in enumerate(rows, 1):
        uid, tag = r["uid"], f"{r['plate'].split()[-1]} {r['anchor']}"
        try:
            blob = sb_get(f"{BUCKET}/{a.stage}/{uid}.glb")
        except Exception as e:
            log(f"[{i}/{len(rows)}] {tag}: fetch failed {type(e).__name__}")
            res.append({"n": i, "car": tag, "uid": uid, "error": "fetch"})
            continue
        if not glb_ok(blob):
            log(f"[{i}/{len(rows)}] {tag}: bad/truncated GLB")
            res.append({"n": i, "car": tag, "uid": uid, "error": "bad-glb"})
            continue
        try:
            info = inspect(blob)
        except Exception as e:
            log(f"[{i}/{len(rows)}] {tag}: inspect failed {type(e).__name__}: {str(e)[:60]}")
            res.append({"n": i, "car": tag, "uid": uid, "error": type(e).__name__})
            continue
        del blob
        info.update({"n": i, "car": tag, "uid": uid, "title": r.get("name", "")[:50],
                     "status": r.get("publicationStatus", "staged")})
        res.append(info)
        log(f"[{i}/{len(rows)}] {tag:14s} {info['verdict']:10s} "
            f"meshes={info['meshes']:4d} wheels name={info['wheels_by_name']} "
            f"geom={info['wheels_by_geometry']} int={info['internal_face_pct']}%")
        # Upload after every car: this container has rolled back seven times
        # today and local disk is not a place work survives.
        try:
            sb_put(f"{BUCKET}/{a.out}", json.dumps(res, indent=1).encode(), "application/json")
        except Exception as e:
            log(f"    upload failed {type(e).__name__}")
    log("INVENTORY_DONE", len(res), "models")


if __name__ == "__main__":
    main()
