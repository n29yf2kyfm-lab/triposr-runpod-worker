#!/usr/bin/env python3
"""backlight_render.py — the confirmation step between a glTF probe and a cull.

CLAUDE.md's evidence rule: a probe NOMINATES, it does not convict. 39 live cars
were once quarantined on weaker evidence and all 39 had to be restored. This is
the cheap decisive check that sits between the two — render the SHIPPED glb
against a saturated magenta world and look:

  transparent glazing  -> magenta reads through the windows
  opaque glazing       -> windows stay body-coloured or a flat tint
  global-alpha shell   -> magenta reads through the BODY and the far-side wheels
  flat clay shell      -> one uniform surface, no glass, no rubber
  healthy car          -> solid body, black tread, glass you can see into

Two traps this tool exists to avoid, both paid for:

1. DRACO. A Draco-compressed GLB fails to import (missing libextern_draco.so)
   and Blender STILL EXITS 0, leaving no image. Judging "no car" from that is
   judging nothing. Every file is decoded through gltf-transform first, and
   success is tested by "did a PNG appear", never by the exit code.

2. THE RAW BBOX. Four stray vertices are enough to blow a car's bounding box up
   ~100x (measured on two Chrysler 300Cs against 377,393 sane vertices), which
   put the camera inside the car and produced a frame containing two floating
   wheels. Same root cause as the pose gate's false rejects. The camera is
   framed on a PERCENTILE bounding box, so outliers cannot drag it.

Usage:
  backlight_render.py --assets a,b,c [--out DIR] [--catalogue PATH]
  backlight_render.py --from-json FILE --key assetId
"""
import argparse, concurrent.futures as cf, json, os, subprocess, sys, time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
GT = ["npx", "--yes", "@gltf-transform/cli@4"]

BLENDER = r'''
import bpy, sys, math, mathutils, numpy as np
inp, out = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=inp)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'; sc.cycles.samples = 24; sc.cycles.device = 'CPU'
sc.cycles.use_denoising = False
sc.render.resolution_x = 640; sc.render.resolution_y = 480
sc.render.film_transparent = False
try: sc.view_settings.view_transform = 'Standard'
except Exception: pass
# A CHECKERED world, not a flat colour. glTF defaults metallicFactor to 1.0
# when a material omits pbrMetallicRoughness, so a flat-shell car is a perfect
# MIRROR: against a uniform magenta backdrop it reflects magenta and vanishes
# entirely. toyota-corolla-tw1-v1 rendered as an empty magenta frame with two
# faint wheels, which reads exactly like "no car" and is really "no material
# data". A two-tone checker makes a mirror legible -- it reflects a PATTERN --
# while still reading straight through transparent glazing.
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
nt = w.node_tree
bg = nt.nodes["Background"]; bg.inputs[1].default_value = 1.2
tc = nt.nodes.new("ShaderNodeTexCoord")
mp = nt.nodes.new("ShaderNodeMapping"); mp.inputs[3].default_value = (8, 8, 8)
ck = nt.nodes.new("ShaderNodeTexChecker")
ck.inputs[1].default_value = (1.0, 0.0, 1.0, 1.0)   # magenta
ck.inputs[2].default_value = (0.0, 0.85, 1.0, 1.0)  # cyan
ck.inputs[3].default_value = 6.0
nt.links.new(tc.outputs["Generated"], mp.inputs[0])
nt.links.new(mp.outputs[0], ck.inputs[0])
nt.links.new(ck.outputs["Color"], bg.inputs[0])
# a neutral key so diffuse paint still reads as its own colour
lt = bpy.data.lights.new("key", type='AREA'); lt.energy = 2000; lt.size = 8
key_obj = bpy.data.objects.new("key", lt); sc.collection.objects.link(key_obj)

# PERCENTILE bbox over real vertices. A handful of stray verts can otherwise
# put the camera inside the car -- the same fault that made the pose gate
# reject good cars on a bbox ~100x the vehicle.
pts = []
for o in bpy.data.objects:
    if o.type != 'MESH' or not o.data.vertices: continue
    n = len(o.data.vertices)
    co = np.empty(n * 3, dtype=np.float32)
    o.data.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    m = np.array(o.matrix_world.to_4x4())
    co = co @ m[:3, :3].T + m[:3, 3]
    pts.append(co if n <= 60000 else co[np.random.default_rng(0).choice(n, 60000, replace=False)])
P = np.concatenate(pts, 0) if pts else np.zeros((1, 3), dtype=np.float32)
lo = np.percentile(P, 1.0, axis=0); hi = np.percentile(P, 99.0, axis=0)
ctr = mathutils.Vector(((lo + hi) / 2).tolist())
rad = float(max(hi - lo)) / 2 or 1.0

cam = bpy.data.cameras.new("c"); co_ = bpy.data.objects.new("c", cam)
sc.collection.objects.link(co_)
ang = math.radians(35); d = rad * 3.0
co_.location = (ctr.x + d * math.cos(ang), ctr.y - d * math.sin(ang), ctr.z + rad * 0.55)
co_.rotation_euler = (ctr - co_.location).to_track_quat('-Z', 'Y').to_euler()
sc.camera = co_
key_obj.location = (ctr.x + rad*2, ctr.y - rad*2, ctr.z + rad*2.5)
key_obj.rotation_euler = (ctr - mathutils.Vector(key_obj.location)).to_track_quat('-Z','Y').to_euler()
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
'''


def fetch(url, dst, key, tries=4):
    """Retries truncated reads. A 42MB GLB died mid-transfer with IncompleteRead
    on the very first run of this check, so it is routine, not exotic."""
    for a in range(tries):
        try:
            rq = urllib.request.Request(url, headers={"apikey": key,
                                                      "Authorization": "Bearer " + key})
            open(dst, "wb").write(urllib.request.urlopen(rq, timeout=600).read())
            return
        except Exception:
            if a == tries - 1:
                raise
            time.sleep(2 * (a + 1))


def render_one(aid, url, outdir, key, bpath):
    src = os.path.join(outdir, f"{aid}.glb")
    nd = src + ".nd.glb"
    png = os.path.join(outdir, f"{aid}.png")
    try:
        if not os.path.exists(src) or os.path.getsize(src) < 10000:
            fetch(f"{SB}/{url.split('/object/public/', 1)[-1]}", src, key)
        if not os.path.exists(nd) or os.path.getsize(nd) < 10000:
            subprocess.run(GT + ["copy", src, nd], capture_output=True, timeout=600)
        use = nd if os.path.exists(nd) and os.path.getsize(nd) > 10000 else src
        subprocess.run(["blender", "-b", "-P", bpath, "--", use, png],
                       capture_output=True, timeout=1200)
        # Blender exits 0 on a failed import, so the PNG is the only proof.
        ok = os.path.exists(png) and os.path.getsize(png) > 5000
        for f in (src, nd):
            try: os.remove(f)
            except OSError: pass
        return (aid, "OK" if ok else "NO-IMAGE", png if ok else None)
    except Exception as e:
        return (aid, f"FAILED {type(e).__name__}", None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", help="comma-separated assetIds")
    ap.add_argument("--from-json", help="json file of rows")
    ap.add_argument("--key", default="assetId")
    ap.add_argument("--catalogue", default=os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json"))
    ap.add_argument("--out", default="/tmp/backlight")
    ap.add_argument("--parallel", type=int, default=2)
    a = ap.parse_args()
    sb = os.environ.get("SB_KEY") or sys.exit("FATAL: SB_KEY env var required")
    os.makedirs(a.out, exist_ok=True)
    bpath = os.path.join(a.out, "_bl.py")
    open(bpath, "w").write(BLENDER)

    cat = {e["assetId"]: e for e in json.load(open(a.catalogue))}
    if a.assets:
        ids = [x.strip() for x in a.assets.split(",") if x.strip()]
    elif a.from_json:
        ids = [r[a.key] for r in json.load(open(a.from_json))]
    else:
        sys.exit("need --assets or --from-json")
    todo = [(i, cat[i]["desktopGlbUrl"]) for i in ids if i in cat and cat[i].get("desktopGlbUrl")]
    print(f"{len(todo)} of {len(ids)} resolvable -> {a.out}", flush=True)

    done = 0
    with cf.ThreadPoolExecutor(a.parallel) as ex:
        futs = [ex.submit(render_one, i, u, a.out, sb, bpath) for i, u in todo]
        for f in cf.as_completed(futs):
            aid, status, png = f.result()
            done += 1
            print(f"  [{done}/{len(todo)}] {status:16} {aid}", flush=True)
    print("BACKLIGHT_DONE", flush=True)


if __name__ == "__main__":
    main()
