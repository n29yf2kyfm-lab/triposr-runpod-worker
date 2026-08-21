#!/usr/bin/env python3
"""
mobile_gate.py -- THE MOBILE-PERFORMANCE GATE. Given a master GLB, build the
candidate mobile exports, measure every one of them, and return PASS / FAIL /
BLOCKED with the evidence attached.

    python3 pipeline/machine/mobile/mobile_gate.py master.glb --out-dir OUT
    python3 pipeline/machine/mobile/mobile_gate.py master.glb --out-dir OUT \\
            --ladder draco,dec50,dec30,dec20 --skip-load

Re-runnable and re-targetable by design: nothing about this file is specific to
one car. Node names, close-up zones, cameras and the critical-material list are
all derived from the master or overridable, so a revised car from any other gate
runs through unchanged.

--------------------------------------------------------------------------
THE FOUR MUST-NOT-BREAK PROPERTIES -- checked on EVERY written output
--------------------------------------------------------------------------
  G1 GLAZING      glass_probe must return clear/proven. Opaque glazing is a hard
                  SCRAP under the owner's confirmed 2026-08-11 ruling; 119 live
                  cars (10.3% of the catalogue) were culled on it alone.
                  *** glass_probe ALONE IS NOT SUFFICIENT HERE. *** It reads the
                  MATERIAL TABLE. A decimator that collapses a window pane leaves
                  the `glass` material and its transmission factor untouched, so
                  the probe still says clear on a car with no glass in it. G1 is
                  therefore glass_probe AND fidelity.geometry_retention on the
                  glazing area. Negative control NC2 exists to prove exactly
                  this, and it does: see the run report.
  G2 TYRES        the tyre material must read as black rubber in the shipped
                  glTF. Reported as measured baseColorFactor luminance.
                  Honest scope, from CLAUDE.md 2026-08-11: a glTF tyre probe was
                  validated at RECALL 0/8 against 131 ground-truthed cars and
                  CANNOT detect the per-corner render artefact. What G2 rules out
                  is the body-paint-over-rubber and flat-shell mechanisms, and
                  that a reduction DARKENED or LIGHTENED the rubber. It is an
                  invariance check between master and candidate, not a verdict on
                  the car.
  G3 RESPRAY      a name-targeted respray of `carpaint` must move the body and
                  must NOT move glazing, tyres, rims or lamps. Run in the real
                  <model-viewer> material API -- the same path the product uses
                  -- with a per-material ID pass to attribute the change.
                  CLAUDE.md 2026-08-15: every automated gate passed a car whose
                  separation was fake, and only the respray control caught it.
                  "The control is not a formality, it is the verdict."
  G4 VALIDATOR    Khronos glTF-Validator, ZERO errors.

  Plus, non-negotiable and cheap: NORMAL accessors present on EVERY primitive of
  the RE-READ written file. trimesh submesh exports drop them and the studio
  clearcoat renders that as crumpled foil -- a lesson this project has now paid
  for three separate times, twice AFTER writing it down.

--------------------------------------------------------------------------
WHY PSNR AND NOT IoU
--------------------------------------------------------------------------
Measured on this programme: a control deleting 96% of triangles still scored
min silhouette IoU 0.991. IoU is blind to surface destruction. PSNR caught the
same case at 26.93 dB against a healthy 37.81 dB. This gate uses PSNR at matched
cameras as the fidelity metric and keeps IoU only as a gross-failure channel.

AND IT SHIPS ITS OWN NEGATIVE CONTROLS. "A metric that has never returned a
failure is not a metric" -- two checks on this programme were found to have
never once fired. Every run of this gate builds:

  NC1  a deliberately over-decimated car. The fidelity metric MUST fail it.
  NC2  a car with the GLAZING GEOMETRY GUTTED and the material table untouched.
       glass_probe MUST still pass it (proving the probe's blind spot) and
       geometry_retention MUST fail it (proving the blind spot is covered).
  NC3  a car with the tyre primitives RE-BOUND to `carpaint` -- the
       paint-over-rubber mechanism the owner's 2026-08-09 tyre ruling is about.
       The GATE STACK must catch it, and the report names which check did.
       Note WHICH one, because it is not the obvious one: the per-material
       pixel-change test CANNOT see this, since after the rebind there is no
       tyre geometry left whose pixels could change. It is caught by the
       PHANTOM-MATERIAL check (`Tyre_Rubber` still in the table, renders on
       nothing) and by geometry_retention (Tyre_Rubber area -> 0).

If a negative control does not fail, the gate reports BLOCKED, not PASS -- a
run whose instruments cannot be shown to fire has measured nothing.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MACHINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(MACHINE))
sys.path.insert(0, HERE)
sys.path.insert(0, MACHINE)
sys.path.insert(0, os.path.join(REPO, "pipeline", "ingest"))

import mobile_metrics as MM                                  # noqa: E402
import fidelity as FID                                       # noqa: E402
import load_probe as LP                                      # noqa: E402

GLTF_TRANSFORM = shutil.which("gltf-transform") or "/opt/node22/bin/gltf-transform"
VALIDATE = os.path.join(MACHINE, "gltf_validate.py")

TYRE_MAT = re.compile(r"(?<![a-z0-9])(tyre|tire|rubber)(?![a-z0-9])", re.I)
PAINT_MAT = "carpaint"


# ==========================================================================
# helpers
# ==========================================================================

def gt(args, timeout=1800):
    p = subprocess.run([GLTF_TRANSFORM] + args, capture_output=True, text=True,
                       timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("gltf-transform %s rc=%d\n%s\n%s"
                           % (args[0], p.returncode, p.stdout[-1500:], p.stderr[-1500:]))
    return p.stdout


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# ==========================================================================
# G1 glazing -- glass_probe on a LOCAL file, reusing the shipped rules verbatim
# ==========================================================================

def glass_probe_local(path):
    """Run pipeline/ingest/glass_probe.py's own classifier against a local GLB.

    The rules are NOT reimplemented. `glass_probe.probe()` fetches the glTF JSON
    chunk through `gltf_json(url)`; only that one function is redirected at the
    local file. CLAUDE.md is explicit about why: "A retro check that
    reimplements them drifts from the wave check, and then the two disagree
    about the same car."
    """
    import glass_probe as GP
    js, _ = MM.glb_read(path)
    orig = GP.gltf_json
    try:
        GP.gltf_json = lambda _url: js
        return GP.probe(os.path.basename(path), url="local://%s" % path)
    finally:
        GP.gltf_json = orig


# ==========================================================================
# G2 tyres
# ==========================================================================

def tyre_report(path):
    js, _ = MM.glb_read(path)
    rows = []
    for m in js.get("materials", []):
        nm = m.get("name") or ""
        if not TYRE_MAT.search(nm):
            continue
        pbr = m.get("pbrMetallicRoughness") or {}
        bcf = pbr.get("baseColorFactor") or [1, 1, 1, 1]
        lum = 0.2126 * bcf[0] + 0.7152 * bcf[1] + 0.0722 * bcf[2]
        rows.append({"material": nm, "baseColorFactor": bcf,
                     "luminance": round(lum, 5),
                     "textured": bool(pbr.get("baseColorTexture")),
                     "black": bool(lum < 0.12 and not pbr.get("baseColorTexture"))})
    return {"status": "PASS" if rows and all(r["black"] for r in rows)
            else ("FAIL" if rows else "NOT_TESTED"),
            "materials": rows,
            "scope": "rules out body-paint-over-rubber and flat-shell only; a glTF "
                     "tyre probe scored RECALL 0/8 on the per-corner render artefact "
                     "(CLAUDE.md 2026-08-11) and this cannot see it either"}


# ==========================================================================
# G4 validator
# ==========================================================================

def validate(path, out_json=None):
    cmd = [sys.executable, VALIDATE, path, "--quiet"]
    if out_json:
        cmd += ["--json", out_json]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    rep = None
    if out_json and os.path.exists(out_json):
        rep = json.load(open(out_json))
        if isinstance(rep, list):
            rep = rep[0]
    if rep is None:
        return {"status": "NOT_TESTED", "reason": p.stderr[-400:] or p.stdout[-400:]}
    counts = rep.get("counts") or rep.get("issues") or {}
    err = counts.get("errors", counts.get("ERROR"))
    warn = counts.get("warnings", counts.get("WARNING"))
    if err is None:
        # tolerate a differently-shaped report rather than inventing a number
        txt = json.dumps(rep)
        err = txt.count('"severity": 0')
        warn = txt.count('"severity": 1')
    return {"status": "PASS" if err == 0 else "FAIL",
            "errors": err, "warnings": warn, "report": out_json}


# ==========================================================================
# NORMAL accessor assertion -- on the RE-READ written file
# ==========================================================================

def assert_normals(path):
    js, _ = MM.glb_read(path)
    tot = miss = 0
    for m in js.get("meshes", []):
        for p in m["primitives"]:
            tot += 1
            if "NORMAL" not in p["attributes"]:
                miss += 1
    return {"status": "PASS" if (tot and miss == 0) else "FAIL",
            "primitives": tot, "missingNormal": miss}


# ==========================================================================
# G3 respray control, in the real <model-viewer> material API
# ==========================================================================

RESPRAY_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="icon" href="data:,">
<style>html,body{margin:0;background:#202024}
model-viewer{width:768px;height:576px;background:#202024}</style></head><body>
<model-viewer id="mv" disable-pan disable-zoom interaction-prompt="none"
  shadow-intensity="0" exposure="1" environment-image="neutral"
  min-camera-orbit="auto auto 0m" max-camera-orbit="auto auto 1000m"></model-viewer>
<script>window.__loaded=false;window.__failed=null;
const mv=document.getElementById('mv');
mv.addEventListener('load',()=>{window.__loaded=true;});
mv.addEventListener('error',e=>{window.__failed=JSON.stringify(e.detail||'error');});</script>
<script type="module">
import '/model-viewer.min.js';
await customElements.whenDefined('model-viewer');
const MV=customElements.get('model-viewer');
MV.meshoptDecoderLocation='/meshopt_decoder.js'; MV.dracoDecoderLocation='/draco/';
const mv=document.getElementById('mv');
window.__setSrc=(s)=>{window.__loaded=false;window.__failed=null;mv.src=s;};
window.__cam=(o,t,f)=>{mv.cameraOrbit=o;mv.cameraTarget=t;mv.fieldOfView=f;
  mv.jumpCameraToGoal();};
// isLoaded is load-bearing EVIDENCE, not defensive coding. <model-viewer>
// refuses to load a material no primitive references -- "Material X has not
// been loaded" -- so an UNLOADED material is exactly the phantom signature:
// present in the glTF material table, bound to nothing on screen. Every
// accessor below therefore skips unloaded materials instead of throwing, and
// the loaded flag is reported back to Python.
window.__mats=()=>mv.model.materials.map(m=>({name:m.name,loaded:!!m.isLoaded}));
window.__save=()=>{window.__orig=mv.model.materials.map(m=>{
  if(!m.isLoaded) return null;
  return {bc:Array.from(m.pbrMetallicRoughness.baseColorFactor),
          mt:m.pbrMetallicRoughness.metallicFactor,
          rg:m.pbrMetallicRoughness.roughnessFactor,
          em:Array.from(m.emissiveFactor)};});};
window.__restore=()=>{mv.model.materials.forEach((m,i)=>{const o=window.__orig[i];
  if(!o||!m.isLoaded) return;
  m.pbrMetallicRoughness.setBaseColorFactor(o.bc);
  m.pbrMetallicRoughness.setMetallicFactor(o.mt);
  m.pbrMetallicRoughness.setRoughnessFactor(o.rg);
  m.setEmissiveFactor(o.em);});};
// ISOLATION pass k: everything matte black, material k emissive WHITE.
// One material per screenshot -- see the docstring for why a single
// many-colours-at-once ID pass does not work through a tone mapper.
//
// Split into INIT + INCREMENTAL on purpose. Touching all 11 materials for every
// pass made each screenshot take ~60 s (three.js re-uploads and recompiles on a
// material change, and SwiftShader then redraws 985k triangles). __isoInit runs
// the expensive whole-table reset ONCE; each subsequent pass touches exactly the
// two materials that differ.
window.__isoPrev=-1;
window.__isoInit=()=>{mv.model.materials.forEach(m=>{
  if(!m.isLoaded) return;
  m.pbrMetallicRoughness.setBaseColorFactor([0,0,0,1]);
  m.pbrMetallicRoughness.setMetallicFactor(0);
  m.pbrMetallicRoughness.setRoughnessFactor(1);
  m.setEmissiveFactor([0,0,0]);}); window.__isoPrev=-1;};
window.__isolate=(k)=>{const ms=mv.model.materials;
  if(window.__isoPrev>=0&&ms[window.__isoPrev].isLoaded)
    ms[window.__isoPrev].setEmissiveFactor([0,0,0]);
  if(ms[k].isLoaded) ms[k].setEmissiveFactor([1,1,1]);
  window.__isoPrev=k;};
window.__paint=(name,rgba)=>{let n=0;mv.model.materials.forEach(m=>{
  if(m.name===name&&m.isLoaded){m.pbrMetallicRoughness.setBaseColorFactor(rgba);n++;}});
  return n;};
window.__ready=true;
</script></body></html>"""



def _settle(page, clip, tmpdir, max_wait_s=60.0, tol=1.0):
    """Block until two consecutive frames are the same, or give up.

    A fixed wait_for_timeout() is not a settle check. Under SwiftShader a
    material-table change takes tens of seconds to redraw ~1M triangles, and a
    screenshot taken during that window shows a HALF-UPDATED car -- which is how
    this gate once reported ten simultaneous paint leaks that did not exist.
    Returns the seconds waited and whether it actually converged, so a caller can
    refuse rather than silently measure a transient frame.
    """
    import time as _t
    from PIL import Image
    a = os.path.join(tmpdir, "_settle_a.png")
    b_ = os.path.join(tmpdir, "_settle_b.png")
    t0 = _t.time()
    page.wait_for_timeout(400)
    page.screenshot(path=a, clip=clip)
    while _t.time() - t0 < max_wait_s:
        page.wait_for_timeout(700)
        page.screenshot(path=b_, clip=clip)
        A = np.asarray(Image.open(a).convert("RGB")).astype(np.float64)
        B = np.asarray(Image.open(b_).convert("RGB")).astype(np.float64)
        if float(np.abs(A - B).mean()) <= tol:
            return {"seconds": round(_t.time() - t0, 1), "converged": True}
        os.replace(b_, a)
    return {"seconds": round(_t.time() - t0, 1), "converged": False}


CRITICAL_VISIBLE = ("glass", "Tyre_Rubber", "Rim_Alloy",
                    "Lamp_Lens", "Lamp_Lens_Rear")


def respray_control(path, out_dir, cams, new_rgba=(0.05, 0.12, 0.75, 1.0),
                    paint_material=PAINT_MAT, leak_tol=0.03, move_min=0.15,
                    min_mask_coverage=0.90, min_sample_px=1000, phantom_px=100,
                    paint_share_max=0.90, critical_visible=CRITICAL_VISIBLE,
                    verbose=True):
    """Paint `carpaint` blue in the live viewer and attribute every changed
    pixel to a material via PER-MATERIAL ISOLATION passes.

    PASS requires BOTH halves:
      * the paint MOVED   -- >= move_min of the paint material's own pixels changed
      * nothing else did  -- <= leak_tol of each protected material's pixels changed
    A respray that raises no error and moves nothing ships eight identical files
    (CLAUDE.md, corolla-cross at dist=0.004); a respray that moves everything is
    the toyota-auris cov=1.000 retirement. Both directions are gated.

    WHY ISOLATION PASSES AND NOT ONE MULTI-COLOUR ID PASS -- a bug this gate
    made and had to correct mid-run
    ----------------------------------------------------------------------
    The first implementation set every material's emissive to a distinct
    saturated ID colour in ONE pass and matched pixels back by nearest colour.
    It ran, produced a confident FAIL ("PAINT LEAK onto `Underbody`: 13.9%"),
    and was WRONG: only ONE material of eleven matched at all, because
    <model-viewer> tone-maps the frame, so an emissive [1,0,1] does NOT land on
    sRGB (255,0,255) and every saturated key missed. The one match was white,
    which survived the mapping closest. A gate reporting a specific failure off
    a mask that covered 882 pixels of the car is exactly the "safety check that
    is itself wrong" failure this project has paid for before, so the leak claim
    was WITHDRAWN and the instrument rebuilt.

    Isolation is immune to it: in pass k every material is matte black and only
    material k is emissive WHITE, so the mask is "is this pixel bright", which
    no monotonic tone curve can break.

    AND THE INSTRUMENT CHECKS ITSELF. The union of the per-material masks must
    cover at least `min_mask_coverage` of the car's silhouette. If it does not,
    the masks are not a partition of the car and the result is NOT_TESTED --
    never PASS, never a named FAIL. That self-check is what the first version
    lacked, and it is what would have caught it in one run.
    """
    from PIL import Image
    from playwright.sync_api import sync_playwright
    import socketserver, threading
    import viewer_check as VC

    mv = VC.find_model_viewer(); exe = VC.find_chromium()
    if not mv or not exe:
        return {"status": "NOT_TESTED", "reason": "model-viewer or Chromium unavailable"}
    os.makedirs(out_dir, exist_ok=True)
    web = os.path.join(out_dir, "web"); os.makedirs(web, exist_ok=True)
    shutil.copy(path, os.path.join(web, "c.glb"))
    shutil.copy(mv, os.path.join(web, "model-viewer.min.js"))
    VC.vendor_decoders(web)
    with open(os.path.join(web, "index.html"), "w") as fh:
        fh.write(RESPRAY_PAGE)
    handler = lambda *a, **k: VC.Quiet(*a, directory=web, **k)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    cam = cams[0]
    shots = {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, executable_path=exe, args=[
                "--use-gl=angle", "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader", "--no-sandbox", "--disable-dev-shm-usage"])
            p = b.new_page(viewport={"width": 820, "height": 620})
            # 180 s, not playwright's 30 s default. A whole-material-table
            # update makes three.js re-upload and recompile, and SwiftShader then
            # needs tens of seconds to redraw ~1M triangles -- measured, both
            # locator.screenshot() and page.screenshot() raised
            # "Timeout 30000ms exceeded" on exactly that frame. The timeout was
            # the real limit; the locator form ALSO waits for element STABILITY,
            # which a continuously re-rendering <model-viewer> never reaches, so
            # both the clip form and this timeout are needed.
            p.set_default_timeout(180000)
            p.goto("http://127.0.0.1:%d/index.html" % port)
            p.wait_for_function("()=>window.__ready===true", timeout=60000)
            p.evaluate("s=>window.__setSrc(s)", "/c.glb")
            p.wait_for_function("()=>window.__loaded===true||window.__failed!==null",
                                timeout=300000)
            if p.evaluate("window.__failed"):
                raise RuntimeError(p.evaluate("window.__failed"))
            p.wait_for_timeout(1200)
            p.evaluate("a=>window.__cam(a[0],a[1],a[2])",
                       [cam["orbit"], cam["target"], cam["fov"]])
            p.wait_for_timeout(600)
            matinfo = p.evaluate("()=>window.__mats()")
            names = [m["name"] for m in matinfo]
            loaded = [bool(m["loaded"]) for m in matinfo]
            p.evaluate("()=>window.__save()")
            # clipped PAGE screenshot, never locator.screenshot() -- see
            # fidelity.appearance() for the measured reason.
            box = p.locator("#mv").bounding_box()
            clip = {"x": box["x"], "y": box["y"],
                    "width": box["width"], "height": box["height"]}

            # ORDER MATTERS, and getting it wrong produced a second wrong
            # verdict. The first ordering ran the isolation passes BETWEEN the
            # before and after frames and then called __restore(); restoring the
            # whole material table forces a re-upload that takes ~20 s under
            # SwiftShader, so the "after" frame was captured on a car that was
            # still half-black from the isolation pass. Every protected material
            # then read 53-80% "changed" and the gate reported ten simultaneous
            # paint leaks on a car with none. Now NOTHING is restored before a
            # measured frame: before -> paint -> after, and the isolation passes
            # come last, where a slow settle costs nothing.
            shots["before"] = os.path.join(out_dir, "respray_before.png")
            _settle(p, clip, out_dir)
            p.screenshot(path=shots["before"], clip=clip)

            n = p.evaluate("a=>window.__paint(a[0],a[1])",
                           [paint_material, list(new_rgba)])
            _settle(p, clip, out_dir)
            shots["after"] = os.path.join(out_dir, "respray_after.png")
            p.screenshot(path=shots["after"], clip=clip)

            p.evaluate("()=>window.__isoInit()")
            _settle(p, clip, out_dir)
            for k, nm in enumerate(names):
                p.evaluate("k=>window.__isolate(k)", k)
                p.wait_for_timeout(400)
                fp = os.path.join(out_dir, "iso_%02d_%s.png"
                                  % (k, re.sub(r"[^A-Za-z0-9_.-]", "_", nm or "?")))
                p.screenshot(path=fp, clip=clip)
                shots["iso_%d" % k] = fp
            b.close()
    finally:
        httpd.shutdown()

    A = np.asarray(Image.open(shots["before"]).convert("RGB")).astype(np.int16)
    B = np.asarray(Image.open(shots["after"]).convert("RGB")).astype(np.int16)
    changed = np.abs(A - B).max(axis=2) > 16
    bg = np.array([0x20, 0x20, 0x24])
    car = (np.abs(A - bg).sum(axis=2) > 24) | (np.abs(B - bg).sum(axis=2) > 24)

    # ---- masks: ARGMAX, not a brightness THRESHOLD ------------------------
    # A threshold was the second wrong instrument. Measured on this car: at
    # lum>90 the eleven masks summed to 438,081 pixels over a 199,992-pixel car
    # -- they overlap 2.2x, because model-viewer's material API does not expose
    # KHR_materials_clearcoat, so a "matte black" material still throws a bright
    # specular highlight from the neutral IBL and every frame lights up in the
    # same places. Assigning each pixel to the BRIGHTEST isolation frame is
    # immune to that: a full white emissive always beats a highlight on black.
    lums = []
    for i in range(len(names)):
        I = np.asarray(Image.open(shots["iso_%d" % i]).convert("RGB")).astype(np.float64)
        lums.append(0.2126 * I[:, :, 0] + 0.7152 * I[:, :, 1] + 0.0722 * I[:, :, 2])
    L = np.stack(lums)
    best = L.argmax(axis=0)
    top = L.max(axis=0)
    second = np.sort(L, axis=0)[-2] if len(names) > 1 else np.zeros_like(top)
    part = (top > 25) & ((top - second) > 12) & car
    coverage = float(part.sum()) / float(car.sum()) if car.sum() else 0.0

    def erode1(m):
        e = m.copy()
        e[1:, :] &= m[:-1, :]; e[:-1, :] &= m[1:, :]
        e[:, 1:] &= m[:, :-1]; e[:, :-1] &= m[:, 1:]
        return e

    # GLAZING IS EXEMPT FROM THE PIXEL LEAK TEST, and that is not a loophole.
    # Glass here carries KHR_materials_transmission 0.92, so the body is VISIBLE
    # THROUGH IT: repainting the body necessarily changes glazing pixels, and it
    # measured 29.1% change on a car with no leak at all. Pixels with glazing in
    # front are excluded from every other material's sample for the same reason.
    # Glazing is gated by G1 (glass_probe + geometry retention), which is the
    # stronger test for it anyway.
    import glass_probe as GP
    glassy = [i for i, nm in enumerate(names) if GP.GLASSY.search(nm or "")]
    glass_front = np.zeros_like(car)
    for i in glassy:
        glass_front |= (lums[i] > 60)

    rows, fails, advisory = [], [], []
    for i, nm in enumerate(names):
        raw = part & (best == i)
        m = erode1(raw)
        is_glass = i in glassy
        sample = m if is_glass else (m & ~glass_front)
        px, spx = int(raw.sum()), int(sample.sum())
        frac = float(changed[sample].mean()) if spx else None
        protected = nm != paint_material
        row = {"material": nm, "loadedInViewer": loaded[i],
               "maskPixels": px, "samplePixels": spx,
               "maskShareOfCar": round(px / float(car.sum()), 4) if car.sum() else 0,
               "changedFraction": round(frac, 4) if frac is not None else None,
               "protected": protected, "glazing": is_glass,
               "gated": bool(protected and not is_glass and spx >= min_sample_px)}
        rows.append(row)
        if not protected:
            if frac is None or frac < move_min:
                fails.append("paint did NOT move: `%s` changed on %s of its own pixels"
                             % (nm, "no" if frac is None else "%.1f%%" % (100 * frac)))
            if row["maskShareOfCar"] > paint_share_max:
                fails.append("`%s` covers %.1f%% of the car (ceiling %.0f%%) -- one "
                             "material over the whole model is the toyota-auris "
                             "cov=1.000 retirement signature"
                             % (nm, 100 * row["maskShareOfCar"], 100 * paint_share_max))
        elif is_glass:
            advisory.append("`%s` changed %.1f%% -- EXPECTED, it is transmissive and "
                            "the repainted body is visible through it; gated by G1"
                            % (nm, 100 * frac) if frac is not None else nm)
        elif spx < min_sample_px:
            advisory.append("`%s` sample only %d px after erosion and glazing "
                            "exclusion -- reported, not gated (changed %s)"
                            % (nm, spx, "n/a" if frac is None
                               else "%.1f%%" % (100 * frac)))
        elif frac > leak_tol:
            fails.append("PAINT LEAK onto `%s`: %.1f%% of its pixels changed "
                         "(tolerance %.1f%%)" % (nm, 100 * frac, 100 * leak_tol))

    # PHANTOM-MATERIAL CHECK. A material that is in the table but renders on
    # (almost) nothing is the signature of its geometry having been absorbed --
    # e.g. tyre primitives re-bound to carpaint leave `Tyre_Rubber` sitting in
    # the table, black and innocent-looking, with no pixels. The per-material
    # pixel-change test CANNOT see that (there is nothing left to change), so it
    # is checked separately, and only for materials that must be visible at a
    # three-quarter view.
    for i, nm in enumerate(names):
        if nm not in critical_visible:
            continue
        if not loaded[i]:
            fails.append("`%s` is in the material table but <model-viewer> reports it "
                         "NOT LOADED -- no primitive references it, so its geometry "
                         "has been absorbed by another material" % nm)
        elif int((part & (best == i)).sum()) < phantom_px:
            fails.append("`%s` is in the material table but renders on <%d pixels -- "
                         "its geometry appears to have been absorbed by another "
                         "material" % (nm, phantom_px))

    if paint_material not in names:
        fails.append("no material named %r -- respray-by-name cannot work"
                     % paint_material)

    # SELF-CHECK. If the masks do not partition the car, no verdict drawn from
    # them is worth anything -- report NOT_TESTED, never a named failure.
    if coverage < min_mask_coverage:
        return {"status": "NOT_TESTED", "paintMaterial": paint_material,
                "reason": "isolation masks partition only %.1f%% of the car "
                          "silhouette (need %.0f%%); the instrument is not "
                          "measuring the car, so no leak verdict is reported"
                          % (100 * coverage, 100 * min_mask_coverage),
                "maskCoverage": round(coverage, 4), "materials": rows,
                "shots": shots, "camera": cam}

    res = {"status": "PASS" if not fails else "FAIL",
           "paintMaterial": paint_material, "primitivesRepainted": n,
           "moveMin": move_min, "leakTolerance": leak_tol,
           "maskCoverage": round(coverage, 4), "minSamplePx": min_sample_px,
           "materials": rows, "failures": fails, "advisory": advisory,
           "shots": shots, "camera": cam}
    if verbose:
        print("RESPRAY CONTROL (%s -> blue, live model-viewer material API)  %s"
              % (paint_material, res["status"]))
        print("  masks partition %.1f%% of the car silhouette (need %.0f%%); "
              "argmax over %d isolation frames"
              % (100 * coverage, 100 * min_mask_coverage, len(names)))
        for r in sorted(rows, key=lambda r: -r["maskPixels"]):
            if r["maskPixels"] < 100:
                continue
            print("  %-20s %-9s %-6s mask %7d  sample %7d  changed %s"
                  % (r["material"],
                     "PAINT" if not r["protected"] else
                     ("GLAZING" if r["glazing"] else "PROTECTED"),
                     "gated" if r["gated"] else "advis.",
                     r["maskPixels"], r["samplePixels"],
                     "  n/a" if r["changedFraction"] is None
                     else "%5.1f%%" % (100 * r["changedFraction"])))
        for a in advisory:
            print("  [note] %s" % a)
        for f in fails:
            print("  FAIL: %s" % f)
    return res


# ==========================================================================
# variant + negative-control builders
# ==========================================================================

def cull_hidden(src, dst, target_material, dilate=2, verbose=True):
    """Delete only the faces of `target_material` with NO line of sight from ANY
    camera. Reuses mobile_export's EXACT per-face ray test, which is the right
    implementation and already carries its own hard-won caveats.

    Why this rung exists at all: on `car_rebound.glb` the `Interior` shell is
    331,014 triangles -- 33.6% of the whole car -- and its bbox spans the entire
    body, so it is an inner shell of the car, not cabin furniture. A UNIFORM
    decimation ratio spends a third of its error budget on geometry nobody can
    see, while taking that same error out of the paint and the wheels that
    everybody can.

    It is NOT free budget. Measured in mobile_export.py: 15.24% of car pixels
    show interior through the glazing (22.26% from the rear), which is exactly
    the through-glass read the owner's glazing ruling protects. So the cull is
    line-of-sight EXACT, treats glass as transparent so through-glass sightlines
    count as visible, and dilates the keep-set over face adjacency.
    """
    sys.path.insert(0, MACHINE)
    import mobile_export as ME
    # TWO DIFFERENT NAME SPACES, and they do not agree on this car.
    # `hidden_face_mask` looks the target up in `scene.geometry`, which trimesh
    # keys by MESH name; `apply_face_cull` looks it up by MATERIAL name. Here the
    # mesh is `Interior` and the material is `Interior_Plastic`, so passing one
    # name to both raises. Resolve the mesh name from the material binding.
    js, _ = MM.glb_read(src)
    mats = js.get("materials", [])
    mesh_names = [m.get("name") for m in js["meshes"]
                  for p in m["primitives"]
                  if "material" in p
                  and mats[p["material"]].get("name") == target_material]
    if len(set(mesh_names)) != 1:
        raise ValueError("material %r maps to %d distinct meshes (%s); the cull "
                         "target must be unambiguous"
                         % (target_material, len(set(mesh_names)), sorted(set(mesh_names))))
    geom_name = mesh_names[0]
    keep, stats = ME.hidden_face_mask(src, target=geom_name, dilate=dilate,
                                      verbose=verbose)
    ME.apply_face_cull(src, dst, target_material, keep)
    stats["meshName"] = geom_name
    stats["materialName"] = target_material
    return stats


def build_variant(master, out, recipe, workdir):
    """recipe: dict with optional cullHidden/weld/simplifyRatio/simplifyError/compress."""
    os.makedirs(workdir, exist_ok=True)
    cur = master
    t0 = time.time()
    if recipe.get("cullHidden"):
        nxt = os.path.join(workdir, "cull.glb")
        recipe = dict(recipe)
        recipe["cullStats"] = cull_hidden(cur, nxt, recipe["cullHidden"])
        cur = nxt
    if recipe.get("weld", True) and (recipe.get("simplifyRatio") is not None):
        nxt = os.path.join(workdir, "w.glb")
        if not os.path.exists(nxt):
            gt(["weld", cur, nxt])
        cur = nxt
    if recipe.get("simplifyRatio") is not None:
        nxt = os.path.join(workdir, "s.glb")
        args = ["simplify", cur, nxt, "--ratio", str(recipe["simplifyRatio"]),
                "--error", str(recipe.get("simplifyError", 0.01))]
        if recipe.get("lockBorder") is False:
            args += ["--lock-border", "false"]
        gt(args)
        cur = nxt
    comp = recipe.get("compress")
    if comp and comp != "none":
        nxt = os.path.join(workdir, "c.glb")
        gt(["draco", cur, nxt] if comp == "draco"
           else ["meshopt", cur, nxt, "--level", "high"])
        cur = nxt
    shutil.copy(cur, out)
    return {"seconds": round(time.time() - t0, 1), "recipe": recipe}


def gut_material_geometry(src, dst, material, keep_every=40):
    """NEGATIVE CONTROL GENERATOR ONLY -- never a production stage.

    Deletes almost all triangles bound to `material` while leaving the MATERIAL
    TABLE completely untouched, which is precisely the shape of the failure that
    `glass_probe` cannot see. Vertices are compacted and every accessor is
    re-emitted into its own tight bufferView so the output is a valid GLB and
    the validator has something real to check.
    """
    js, bin_ = MM.glb_read(src)
    data = {i: MM.read_accessor(js, bin_, i) for i in range(len(js["accessors"]))}
    index_accessors = {p["indices"] for m in js["meshes"] for p in m["primitives"]
                       if "indices" in p}
    touched = 0
    for m in js["meshes"]:
        for p in m["primitives"]:
            if "material" not in p:
                continue
            if js["materials"][p["material"]].get("name") != material:
                continue
            idx = data[p["indices"]].reshape(-1, 3)
            kept = idx[::keep_every]
            used = np.unique(kept)
            remap = np.full(int(used.max()) + 1, -1, dtype=np.int64)
            remap[used] = np.arange(used.size)
            data[p["indices"]] = remap[kept].ravel()
            for _nm, ai in p["attributes"].items():
                data[ai] = np.ascontiguousarray(data[ai][used])
            touched += 1
    out = bytearray(); new_bvs = []

    def emit(raw, extra=None):
        while len(out) % 4:
            out.append(0)
        off = len(out); out.extend(raw)
        bv = {"buffer": 0, "byteOffset": off, "byteLength": len(raw)}
        if extra:
            bv.update(extra)
        new_bvs.append(bv); return len(new_bvs) - 1

    NP2C = {np.dtype("uint8"): 5121, np.dtype("uint16"): 5123,
            np.dtype("uint32"): 5125, np.dtype("float32"): 5126}
    for i, acc in enumerate(js["accessors"]):
        arr = data[i]
        if i in index_accessors:
            mx = int(arr.max()) if arr.size else 0
            arr = arr.astype(np.uint16 if mx < 65536 else np.uint32)
        elif acc["componentType"] == 5126:
            arr = arr.astype(np.float32)
        arr = np.ascontiguousarray(arr)
        acc["componentType"] = NP2C[arr.dtype]
        acc["count"] = int(arr.shape[0]) if arr.ndim > 1 else int(arr.size)
        acc["bufferView"] = emit(arr.tobytes(),
                                 {"target": 34963 if i in index_accessors else 34962})
        acc.pop("byteOffset", None)
        if acc["type"] == "VEC3" and arr.ndim > 1 and arr.size:
            acc["min"] = [float(x) for x in arr.min(axis=0)]
            acc["max"] = [float(x) for x in arr.max(axis=0)]
    js["bufferViews"] = new_bvs
    js["buffers"] = [{"byteLength": len(out)}]
    MM.glb_write(dst, js, bytes(out))
    return {"primitivesGutted": touched, "keepEvery": keep_every}


def rebind_material(src, dst, from_mat, to_mat):
    """NEGATIVE CONTROL GENERATOR ONLY. Re-binds every primitive using
    `from_mat` to `to_mat`, so a respray of `to_mat` MUST visibly leak onto that
    geometry. This is the control for the respray control."""
    js, bin_ = MM.glb_read(src)
    names = [m.get("name") for m in js["materials"]]
    if from_mat not in names or to_mat not in names:
        raise KeyError("need both %r and %r in %s" % (from_mat, to_mat, names))
    fi, ti = names.index(from_mat), names.index(to_mat)
    n = 0
    for m in js["meshes"]:
        for p in m["primitives"]:
            if p.get("material") == fi:
                p["material"] = ti; n += 1
    MM.glb_write(dst, js, bin_)
    return {"primitivesRebound": n, "from": from_mat, "to": to_mat}


# ==========================================================================
# per-candidate gate
# ==========================================================================

def gate_one(master, cand, out_dir, cams, budget=None, min_psnr=35.0,
             min_area_ratio=0.85, do_load=True, load_tiers=None, load_repeats=3,
             do_respray=True, verbose=True, master_cache=None):
    os.makedirs(out_dir, exist_ok=True)
    r = {"file": os.path.abspath(cand), "sha256": sha256(cand)}
    r["metrics"] = MM.measure(cand)
    r["budget"] = MM.budget_verdict(r["metrics"], budget)
    r["normals"] = assert_normals(cand)
    r["glass"] = glass_probe_local(cand)
    r["tyres"] = tyre_report(cand)
    r["validator"] = validate(cand, os.path.join(out_dir, "validator.json"))
    r["geometryRetention"] = FID.geometry_retention(
        master, cand, workdir=os.path.join(out_dir, "_geom"),
        min_area_ratio=min_area_ratio)
    r["appearance"] = FID.appearance(master, cand, os.path.join(out_dir, "appearance"),
                                     cams=cams, min_psnr=min_psnr, verbose=verbose,
                                     master_cache=master_cache)
    if do_respray:
        r["respray"] = respray_control(cand, os.path.join(out_dir, "respray"),
                                       cams, verbose=verbose)
    if do_load:
        r["load"] = LP.probe(cand, out_dir=os.path.join(out_dir, "load"),
                             tiers=load_tiers, repeats=load_repeats, verbose=verbose)

    # ---- verdict ---------------------------------------------------------
    hard = []
    if r["glass"]["verdict"] == "opaque" and r["glass"]["certainty"] == "proven":
        hard.append("G1 glazing: opaque/proven -- owner-ruling SCRAP")
    if r["geometryRetention"]["status"] == "FAIL":
        hard.append("G1/geometry: " + "; ".join(r["geometryRetention"]["failures"]))
    if r["tyres"]["status"] == "FAIL":
        hard.append("G2 tyres: not black in the shipped glTF")
    if r.get("respray", {}).get("status") == "FAIL":
        hard.append("G3 respray: " + "; ".join(r["respray"]["failures"]))
    if r["validator"]["status"] != "PASS":
        hard.append("G4 validator: %s errors" % r["validator"].get("errors"))
    if r["normals"]["status"] != "PASS":
        hard.append("NORMAL accessors missing on %d primitives"
                    % r["normals"]["missingNormal"])
    if r["appearance"].get("status") == "FAIL":
        hard.append("fidelity: min PSNR %.2f dB below %.1f"
                    % (r["appearance"]["psnrMin"], min_psnr))
    lost_nodes = r["geometryRetention"].get("nodeNamesLost") or []
    if lost_nodes:
        hard.append("viewer contract: node names lost %s" % lost_nodes[:6])
    r["hardFailures"] = hard
    r["status"] = "PASS" if not hard else "FAIL"
    r["withinBudget"] = r["budget"]["pass"]
    return r


LADDER = {
    "raw":     {"compress": None},
    "meshopt": {"compress": "meshopt"},
    "draco":   {"compress": "draco"},
    "dec80":   {"simplifyRatio": 0.80, "compress": "draco"},
    "dec50":   {"simplifyRatio": 0.50, "compress": "draco"},
    "dec30":   {"simplifyRatio": 0.30, "compress": "draco"},
    "dec20":   {"simplifyRatio": 0.20, "compress": "draco"},
    "dec12":   {"simplifyRatio": 0.12, "compress": "draco"},
    # TARGETED rungs: spend the error budget only on geometry somebody can see.
    "cull":    {"cullHidden": "Interior_Plastic", "compress": "draco"},
    "cull50":  {"cullHidden": "Interior_Plastic", "simplifyRatio": 0.50,
                "compress": "draco"},
    "cull30":  {"cullHidden": "Interior_Plastic", "simplifyRatio": 0.30,
                "compress": "draco"},
}
DEFAULT_LADDER = ["draco", "dec50", "dec30", "dec20"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("master")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--ladder", default=",".join(DEFAULT_LADDER),
                    help="comma list from %s" % ",".join(LADDER))
    ap.add_argument("--min-psnr", type=float, default=35.0)
    ap.add_argument("--min-area-ratio", type=float, default=0.85)
    ap.add_argument("--budget-json")
    ap.add_argument("--skip-load", action="store_true")
    ap.add_argument("--skip-respray", action="store_true")
    ap.add_argument("--skip-controls", action="store_true",
                    help="DIAGNOSTIC ONLY. A run without negative controls "
                         "cannot report PASS -- it reports BLOCKED.")
    ap.add_argument("--load-tiers", default=",".join(LP.DEFAULT_TIERS))
    ap.add_argument("--load-repeats", type=int, default=3)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    work = os.path.join(a.out_dir, "work"); os.makedirs(work, exist_ok=True)
    mcache = os.path.join(a.out_dir, "_master_frames"); os.makedirs(mcache, exist_ok=True)
    budget = json.load(open(a.budget_json)) if a.budget_json else None

    print("=" * 78)
    print("MOBILE GATE  master = %s" % a.master)
    print("=" * 78)
    mdec = FID.decode(a.master, work)
    mm = MM.measure(mdec); mm["_decodedPath"] = mdec
    print(MM.fmt(MM.measure(a.master), budget))
    cams = FID.build_cameras(mm)
    print("\ncameras: %d (%d full-car, %d close-up) derived from the master's WORLD bounds"
          % (len(cams), sum(1 for c in cams if c["zone"] == "full"),
             sum(1 for c in cams if c["zone"] == "closeup")))

    report = {"master": MM.measure(a.master), "masterSha256": sha256(a.master),
              "cameras": cams, "candidates": {}, "controls": {},
              "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    # ---- candidates ------------------------------------------------------
    for name in a.ladder.split(","):
        if name not in LADDER:
            raise SystemExit("unknown ladder rung %r" % name)
        print("\n" + "-" * 78)
        print("CANDIDATE %s   recipe %s" % (name, LADDER[name]))
        print("-" * 78)
        out = os.path.join(a.out_dir, "%s.glb" % name)
        build = build_variant(a.master, out, LADDER[name], os.path.join(work, name))
        print("  built in %.1fs -> %.3f MB" % (build["seconds"], os.path.getsize(out) / 1e6))
        r = gate_one(a.master, out, os.path.join(a.out_dir, "gate_%s" % name), cams,
                     budget=budget, min_psnr=a.min_psnr,
                     min_area_ratio=a.min_area_ratio,
                     do_load=not a.skip_load, load_tiers=a.load_tiers.split(","),
                     load_repeats=a.load_repeats, do_respray=not a.skip_respray,
                     master_cache=mcache)
        r["build"] = build
        report["candidates"][name] = r
        print("  VERDICT %s%s" % (r["status"],
                                  "" if r["status"] == "PASS"
                                  else "  <- " + "; ".join(r["hardFailures"])))

    # ---- negative controls ----------------------------------------------
    if not a.skip_controls:
        print("\n" + "=" * 78)
        print("NEGATIVE CONTROLS -- these MUST fail. A gate whose instruments have")
        print("never fired has measured nothing.")
        print("=" * 78)

        # NC1 -- brutal decimation. PSNR must fail; IoU is expected to survive.
        nc1 = os.path.join(a.out_dir, "NC1_overdecimated.glb")
        build_variant(a.master, nc1, {"simplifyRatio": 0.02, "simplifyError": 1.0,
                                      "lockBorder": False, "compress": None},
                      os.path.join(work, "nc1"))
        g1 = FID.geometry_retention(a.master, nc1, os.path.join(work, "nc1g"),
                                    min_area_ratio=a.min_area_ratio)
        a1 = FID.appearance(a.master, nc1, os.path.join(a.out_dir, "NC1_appearance"),
                            cams=cams, min_psnr=a.min_psnr, master_cache=mcache)
        report["controls"]["NC1_overdecimated"] = {
            "file": nc1, "triangles": MM.measure(nc1)["triangles"],
            "appearance": a1, "geometryRetention": g1,
            "expected": "appearance FAIL", "fired": a1["status"] == "FAIL"}
        print("  NC1 over-decimated: %s tris, PSNR min %.2f dB -> appearance %s, "
              "IoU min %.4f  [%s]"
              % ("{:,}".format(MM.measure(nc1)["triangles"]), a1["psnrMin"],
                 a1["status"], a1["iouMin"],
                 "FIRED" if a1["status"] == "FAIL" else "DID NOT FIRE"))

        # NC2 -- glazing geometry gutted, material table untouched.
        nc2 = os.path.join(a.out_dir, "NC2_glass_gutted.glb")
        gut = gut_material_geometry(a.master, nc2, "glass", keep_every=40)
        gp2 = glass_probe_local(nc2)
        g2 = FID.geometry_retention(a.master, nc2, os.path.join(work, "nc2g"),
                                    min_area_ratio=a.min_area_ratio)
        report["controls"]["NC2_glass_gutted"] = {
            "file": nc2, "gut": gut, "glassProbe": gp2, "geometryRetention": g2,
            "expected": "glass_probe PASSES (blind spot) and geometryRetention FAILS",
            "probeBlind": gp2["verdict"] == "clear",
            "fired": g2["status"] == "FAIL"}
        print("  NC2 glazing gutted: glass_probe says %r/%r  [%s]  |  "
              "geometryRetention %s  [%s]"
              % (gp2["verdict"], gp2["certainty"],
                 "BLIND as predicted" if gp2["verdict"] == "clear" else "unexpected",
                 g2["status"], "FIRED" if g2["status"] == "FAIL" else "DID NOT FIRE"))

        # NC3 -- tyres re-bound to carpaint; the respray must leak.
        if not a.skip_respray:
            nc3 = os.path.join(a.out_dir, "NC3_tyre_bound_to_paint.glb")
            rb = rebind_material(a.master, nc3, "Tyre_Rubber", PAINT_MAT)
            r3 = respray_control(nc3, os.path.join(a.out_dir, "NC3_respray"), cams)
            report["controls"]["NC3_paint_on_tyre"] = {
                "file": nc3, "rebind": rb, "respray": r3,
                "expected": "respray FAIL (paint moves onto rubber geometry)",
                "fired": r3["status"] == "FAIL"}
            print("  NC3 tyre bound to carpaint: respray %s  [%s]"
                  % (r3["status"], "FIRED" if r3["status"] == "FAIL" else "DID NOT FIRE"))

    # ---- overall ---------------------------------------------------------
    controls = report["controls"]
    ctl_ok = bool(controls) and all(c.get("fired") for c in controls.values())
    passing = [n for n, r in report["candidates"].items()
               if r["status"] == "PASS" and r["withinBudget"]]
    if not controls:
        overall = "BLOCKED"
        why = "no negative controls were run; the instruments were not shown to fire"
    elif not ctl_ok:
        overall = "BLOCKED"
        why = ("a negative control did not fire: %s"
               % [n for n, c in controls.items() if not c.get("fired")])
    elif passing:
        overall = "PASS"
        why = "candidates within budget and passing every gate: %s" % passing
    else:
        overall = "FAIL"
        why = "no candidate is both within budget and clean on all gates"
    report["verdict"] = overall
    report["verdictReason"] = why
    report["passingCandidates"] = passing

    print("\n" + "=" * 78)
    print("MOBILE GATE -- %s" % overall)
    print("=" * 78)
    print(why)
    print("\n  %-9s %10s %10s %8s %8s %8s %8s %8s"
          % ("candidate", "MB", "tris", "draws", "PSNRmin", "glass", "tyres", "valid"))
    for n, r in report["candidates"].items():
        m = r["metrics"]
        print("  %-9s %10.3f %10s %8d %8.2f %8s %8s %8s"
              % (n, m["sizeBytes"] / 1e6, "{:,}".format(m["triangles"]), m["drawCalls"],
                 r["appearance"].get("psnrMin", -1), r["glass"]["verdict"],
                 r["tyres"]["status"], r["validator"]["status"]))

    jp = a.json or os.path.join(a.out_dir, "MOBILE_GATE.json")
    with open(jp, "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    print("\nreport: %s" % jp)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
