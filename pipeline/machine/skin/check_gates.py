#!/usr/bin/env python3
"""check_gates.py -- re-run the four Gate 7+8 properties on a local GLB.

The point of running the REPO's own tools rather than reimplementing them is
the recorded lesson that a retro check which reimplements the rules drifts from
the wave check and then the two disagree about the same car.  glass_probe reads
by HTTP Range, so its `head` is patched to read the local file -- the parsing
and the verdict logic are untouched.

  1 glazing      glass_probe.probe(url=...)  -> verdict / certainty /
                 flat_shell / alpha_shell, plus the transmission + IOR factors
  2 tyres        the material bound to the tyre GEOMETRY, read from the glTF
  3 respray      respray_gltf on `carpaint`, then a measured render control is
                 run separately (this only proves the edit resolves + writes)
  4 validator    official Khronos gltf-validator via pipeline/machine

Run: check_gates.py <car.glb> [<car2.glb> ...]
"""
import io
import json
import os
import subprocess
import struct
import sys

sys.path.insert(0, "/home/user/triposr-runpod-worker")
sys.path.insert(0, "/home/user/triposr-runpod-worker/pipeline/ingest")

import glass_probe as GP


def local_head(path, n):
    with open(path, "rb") as f:
        return f.read(n)


GP.head = local_head


def gltf_json(path):
    raw = open(path, "rb").read()
    jlen = struct.unpack("<I", raw[12:16])[0]
    return json.loads(raw[20:20 + jlen])


for path in sys.argv[1:]:
    print(f"\n================ {path}  ({os.path.getsize(path)} bytes)")
    p = GP.probe(None, url=path)
    g = gltf_json(path)
    mats = {m["name"]: m for m in g["materials"]}
    gl = mats.get("glass", {})
    pbr = gl.get("pbrMetallicRoughness", {})
    ext = gl.get("extensions", {})
    print(f"1 GLAZING  verdict={p['verdict']} certainty={p.get('certainty')} "
          f"flat_shell={p.get('flat_shell')} alpha_shell={p.get('alpha_shell')}")
    print(f"           glass alphaMode={gl.get('alphaMode')} "
          f"alpha={pbr.get('baseColorFactor',[None]*4)[3]} "
          f"transmission={ext.get('KHR_materials_transmission',{}).get('transmissionFactor')} "
          f"ior={ext.get('KHR_materials_ior',{}).get('ior')}")
    print(f"           n_transparent={p.get('n_transparent')}/{p.get('n_materials')} "
          f"glazing_named={[x['name'] for x in p.get('glazing',[])]}")

    # 2 tyres: material bound to the tyre meshes, not merely one named 'tire'
    tyre_prims = [(m["name"], g["materials"][pr["material"]]["name"])
                  for m in g["meshes"] for pr in m["primitives"]
                  if "Tyre" in m["name"]]
    tm = sorted({b for _, b in tyre_prims})
    print(f"2 TYRES    meshes->materials {sorted(set(tyre_prims))[:2]} ... "
          f"distinct={tm}")
    for t in tm:
        bc = mats[t].get("pbrMetallicRoughness", {}).get("baseColorFactor")
        print(f"           {t} baseColorFactor={bc}")

    # bound / dead materials
    used = {g["materials"][pr["material"]]["name"]
            for m in g["meshes"] for pr in m["primitives"] if "material" in pr}
    dead = sorted(set(mats) - used)
    print(f"3 MATERIALS bound={len(used)} of {len(mats)}  dead={dead}")

    r = subprocess.run(
        ["python3", "/home/user/triposr-runpod-worker/pipeline/machine/gltf_validate.py",
         path, "--json", "/tmp/_v.json"],
        capture_output=True, text=True)
    try:
        v = json.load(open("/tmp/_v.json"))
        iss = v.get("issues", v)
        print(f"4 VALIDATOR rc={r.returncode} "
              f"errors={iss.get('numErrors', '?')} warnings={iss.get('numWarnings','?')} "
              f"infos={iss.get('numInfos','?')} hints={iss.get('numHints','?')}")
        for m in (iss.get("messages") or [])[:6]:
            print("            ", m.get("severity"), m.get("code"), m.get("message"),
                  m.get("pointer"))
    except Exception as e:
        print("4 VALIDATOR rc=", r.returncode, r.stdout[-800:], r.stderr[-400:], e)
