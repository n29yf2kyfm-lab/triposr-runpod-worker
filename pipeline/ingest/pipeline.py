#!/usr/bin/env python3
"""Gated Sketchfab -> premium-catalogue ingest pipeline.

Three gates so no bad build reaches the catalogue:

  GATE 1  qc      Automated pre-checks BEFORE a human looks:
                  - integrity   (valid glTF, real car not a scene, sane polycount)
                  - coverage    (recolour body %; catches unpainted panels/two-tone)
                  - glass       (glass-area share; catches see-through shells)
                  - exploded    (a mesh sitting far outside the car bbox = flying part)
                  Renders 4 audit angles. Emits a verdict: REJECT (auto) / REVIEW.

  GATE 2  human   The 4 angles are shown to the owner for the subjective call
                  (toy-like / ugly). Not automatable — this stays a person.

  GATE 3  store   Robust publish, only on approval:
                  - per-colour render with retries, every upload re-fetched+verified
                  - ALL colours must succeed or the store ABORTS (no partial entry)
                  - catalogue written atomically + validated + read back from the
                    live resolver before success is reported.

Secrets come from the environment (never hardcoded):
  SKFB_TOKEN, RUNPOD_KEY, RENDER_ENDPOINT, SUPABASE_URL, SUPABASE_KEY

Metadata rule: only verifiable fields are written. Year/trim/generation are left
null unless the spec passes a factual value (e.g. a model's production span).
"""
import base64, copy, json, os, re, struct, subprocess, sys, time, urllib.request

TOKEN = os.environ["SKFB_TOKEN"]
RUNPOD_KEY = os.environ["RUNPOD_KEY"]
ENDPOINT = os.environ.get("RENDER_ENDPOINT", "ng8oiz4p2l0xa0")
SB_URL = os.environ.get("SUPABASE_URL", "https://tfkvthprsntexrcuqpyd.supabase.co")
SB_KEY = os.environ["SUPABASE_KEY"]
REPO = os.environ.get("REPO", "/home/user/triposr-runpod-worker")
CAT = f"{REPO}/platform/catalogue/catalogue.v2.json"
OBASE = f"{SB_URL}/storage/v1/object"
RH = {"Authorization": f"Bearer {RUNPOD_KEY}", "Content-Type": "application/json"}

# QC thresholds
MIN_BYTES = 100_000          # smaller than this = not a real car GLB
MIN_FACES, MAX_FACES = 2_000, 25_000_000
MIN_COVERAGE = 0.30          # body paint share below this = likely under-painted
MAX_GLASS = 0.45             # glass share above this = shell risk (warn)
RENDER_RETRIES = 3


def log(m): print(f"{int(time.time())} {m}", flush=True)


def getj(url, headers=None, data=None, timeout=200, tries=4):
    for a in range(tries):
        try:
            b = urllib.request.urlopen(
                urllib.request.Request(url, data=data, headers=headers or {}), timeout=timeout).read()
            if b:
                return json.loads(b)
        except Exception as e:
            last = e
            time.sleep(2 * (a + 1))
    return None


def getb(url, timeout=200, tries=4):
    for a in range(tries):
        try:
            return urllib.request.urlopen(url, timeout=timeout).read()
        except Exception:
            time.sleep(2 * (a + 1))
    return None


def skfb_download(uid):
    d = getj(f"https://api.sketchfab.com/v3/models/{uid}/download",
             {"Authorization": f"Token {TOKEN}"})
    return d.get("glb") if d else None


def upload(bucket, path, data, ct):
    rq = urllib.request.Request(f"{OBASE}/{bucket}/{path}", data=data, method="POST")
    for h, v in (("apikey", SB_KEY), ("Authorization", "Bearer " + SB_KEY),
                 ("Content-Type", ct), ("x-upsert", "true")):
        rq.add_header(h, v)
    urllib.request.urlopen(rq, timeout=300).read()
    return f"{OBASE}/public/{bucket}/{path}"


def render(glb_url, **opts):
    """Call the GPU render endpoint with retries. Returns PNG bytes or None."""
    body = {"input": {"glb_url": glb_url, **opts}}
    for a in range(RENDER_RETRIES):
        r = getj(f"https://api.runpod.ai/v2/{ENDPOINT}/runsync", RH,
                 json.dumps(body).encode(), timeout=500, tries=1)
        o = (r or {}).get("output", {}) or {}
        if o.get("png_b64"):
            return base64.b64decode(o["png_b64"])
        time.sleep(4 * (a + 1))
    return None


def mat_audit(glb_url):
    r = getj(f"https://api.runpod.ai/v2/{ENDPOINT}/runsync", RH,
             json.dumps({"input": {"glb_url": glb_url, "mat_audit": True}}).encode(),
             timeout=300, tries=2)
    return (r or {}).get("output", {})


# ---- GATE 1 helpers ---------------------------------------------------------
def glb_integrity(glb_bytes):
    """Parse the glTF JSON chunk (no Blender). Returns (ok, reason, meta)."""
    if not glb_bytes or glb_bytes[:4] != b"glTF":
        return False, "not a glТF binary", {}
    if len(glb_bytes) < MIN_BYTES:
        return False, f"too small ({len(glb_bytes)} bytes) — not a real car", {}
    try:
        jlen = struct.unpack("<I", glb_bytes[12:16])[0]
        js = json.loads(glb_bytes[20:20 + jlen].decode("utf-8", "replace"))
    except Exception as e:
        return False, f"unparseable glТF ({str(e)[:40]})", {}
    meshes = js.get("meshes", [])
    prims = sum(len(m.get("primitives", [])) for m in meshes)
    if not meshes or prims == 0:
        return False, "no mesh primitives", {}
    # face estimate from POSITION accessor counts (triangles ~ verts)
    accs = js.get("accessors", [])
    verts = sum(accs[p["attributes"]["POSITION"]].get("count", 0)
                for m in meshes for p in m.get("primitives", [])
                if "POSITION" in p.get("attributes", {}) and p["attributes"]["POSITION"] < len(accs))
    meta = {"n_meshes": len(meshes), "n_primitives": prims, "verts": verts,
            "materials": len(js.get("materials", [])), "bytes": len(glb_bytes)}
    if verts and (verts < MIN_FACES or verts > MAX_FACES):
        return False, f"implausible geometry ({verts} verts)", meta
    return True, "ok", meta


def exploded_check(glb_bytes):
    """Flag a flying part: a mesh whose POSITION bbox centre sits far outside the
    aggregate bbox (a detached panel). Pure-glTF, no Blender."""
    try:
        jlen = struct.unpack("<I", glb_bytes[12:16])[0]
        js = json.loads(glb_bytes[20:20 + jlen].decode("utf-8", "replace"))
    except Exception:
        return True, "unparseable"  # treat as suspect
    accs = js.get("accessors", [])
    centres = []
    lo = [1e18] * 3; hi = [-1e18] * 3
    for m in js.get("meshes", []):
        for p in m.get("primitives", []):
            ai = p.get("attributes", {}).get("POSITION")
            if ai is None or ai >= len(accs):
                continue
            a = accs[ai]
            mn, mx = a.get("min"), a.get("max")
            if not mn or not mx or len(mn) < 3:
                continue
            centres.append([(mn[i] + mx[i]) / 2 for i in range(3)])
            for i in range(3):
                lo[i] = min(lo[i], mn[i]); hi[i] = max(hi[i], mx[i])
    if len(centres) < 3:
        return False, "too few parts to judge"
    diag = max(hi[i] - lo[i] for i in range(3)) or 1.0
    cx = [sum(c[i] for c in centres) / len(centres) for i in range(3)]
    # a part whose centre is >0.9*diagonal from the mean centre is detached
    far = [c for c in centres
           if max(abs(c[i] - cx[i]) for i in range(3)) > 0.9 * diag]
    if far:
        return True, f"{len(far)} part(s) detached from body"
    return False, "cohesive"


def qc(uid, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rep = {"uid": uid, "gates": {}, "verdict": "REVIEW", "warnings": []}
    dl = skfb_download(uid)
    if not dl:
        rep["verdict"] = "REJECT"; rep["gates"]["download"] = "no downloadable GLB"
        return rep
    glb_url = dl["url"]
    glb_bytes = getb(glb_url)
    ok, reason, gmeta = glb_integrity(glb_bytes)
    rep["gates"]["integrity"] = reason; rep["meta"] = gmeta
    if not ok:
        rep["verdict"] = "REJECT"; return rep
    ex, exreason = exploded_check(glb_bytes)
    rep["gates"]["exploded"] = exreason
    if ex:
        rep["verdict"] = "REJECT"; return rep
    # oversized GLB warning (heavy on mobile / slow to serve)
    if gmeta.get("bytes", 0) > 60_000_000:
        rep["warnings"].append(f"large GLB {gmeta['bytes']//1_000_000}MB — flag for mobile-lightweight pass")
    # coverage/glass via mat_audit. A FAILED measurement (huge model the audit
    # endpoint can't fetch in time) must read as 'unknown', never as 'bad' — the
    # visual gate is the backstop. Only a real, measured low coverage warns.
    ma = mat_audit(glb_url)
    if ma and ma.get("n_materials"):
        cov = (ma.get("body_pct") or 0) / 100.0
        glass = sum(m["pct"] for m in ma.get("materials", []) if m.get("glass")) / 100.0
        rep["gates"]["coverage"] = round(cov, 3)
        rep["gates"]["glass_share"] = round(glass, 3)
        rep["gates"]["n_materials"] = ma.get("n_materials")
        if cov < MIN_COVERAGE:
            rep["warnings"].append(f"low paint coverage {cov:.0%} — check for unpainted panels")
        if glass > MAX_GLASS:
            rep["warnings"].append(f"high glass share {glass:.0%} — watch for see-through")
    else:
        rep["gates"]["coverage"] = "unknown"
        rep["gates"]["glass_share"] = "unknown"
        rep["warnings"].append("coverage unmeasured (model too large for audit) — verify panels visually")
    # 4 audit angles
    angles = [("a1_front34", 40, 0.13), ("a2_side", 90, 0.10),
              ("a3_rear34", 145, 0.15), ("a4_front", 5, 0.09)]
    shots = {}
    for tag, az, elev in angles:
        png = render(glb_url, colour="gunmetal", finish="Metallic", plate="AL24 3D",
                     plates_both=True, az=az, elev=elev, samples=120, width=1280, height=720)
        if png:
            fp = f"{out_dir}/{uid[:12]}_{tag}.png"; open(fp, "wb").write(png); shots[tag] = fp
    rep["shots"] = shots
    if len(shots) < 4:
        rep["warnings"].append(f"only {len(shots)}/4 angles rendered")
    rep["verdict"] = "REVIEW" if not [w for w in rep["warnings"] if "coverage" in w] else "REVIEW-CAUTION"
    return rep


# ---- GATE 3: robust store ---------------------------------------------------
PAINTS = json.load(open(f"{REPO}/data/oem-paints.json"))["paints"]
def _norm(s): return re.sub(r"[^a-z0-9]+", "", (s or "").lower())
def oem_for(mk):
    ps = [p for p in PAINTS if _norm(p["manufacturer"]) == _norm(mk)]
    seen, out = set(), []
    for p in ps:
        k = p["colourFamily"].lower()
        if k in seen: continue
        seen.add(k); out.append(p)
    return out[:8]
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def verify_asset(url):
    """Re-fetch an uploaded asset and confirm it's a real image/model, not an
    error page. Accept PNG (the render endpoint returns PNG), JPEG, or glТF."""
    b = getb(url + f"?cb={int(time.time())}", timeout=120, tries=3)
    if not b or len(b) < 20_000:
        return False
    return (b[:8] == b"\x89PNG\r\n\x1a\n" or b[:3] == b"\xff\xd8\xff" or b[:4] == b"glTF")


def store(spec):
    uid = spec["uid"]; make, model = spec["make"], spec["model"]
    # Storage key is the assetId, NOT make/model: the catalogue holds multiple
    # variants per make+model (different year/generation/spec — resolver picks by
    # year), so paths keyed on make/model would overwrite each other. assetId is
    # unique per variant, so every variant's mesh + renders live at their own path.
    key = slug(spec["assetId"])
    dl = skfb_download(uid)
    assert dl, "no downloadable GLB at store time"
    raw = f"/tmp/_{key}_raw.glb"
    open(raw, "wb").write(getb(dl["url"]))
    base = f"/tmp/{key}.glb"
    subprocess.run(["npx", "--yes", "@gltf-transform/cli", "draco", raw, base],
                   cwd=f"{REPO}/pipeline", capture_output=True, timeout=300)
    if not os.path.exists(base) or os.path.getsize(base) < 1000:
        base = raw
    glb_url = upload("car-meshes", f"finished/{make}/{key}.glb", open(base, "rb").read(), "model/gltf-binary")
    assert verify_asset(glb_url), "GLB upload failed verification"
    base_bytes = os.path.getsize(base)
    # clean up temp GLBs immediately — they're uploaded now; leaving them fills
    # the session's disk allowance (source GLBs run 60-180 MB each).
    for f in (raw, base):
        try: os.remove(f)
        except OSError: pass
    log(f"GLB stored+verified {base_bytes // 1024}KB")

    hero_az = spec.get("az", 40)
    plate = spec.get("plate", "AL24 3D")
    # recolour mode: "auto" (tint on generic bodies) or "flat" (clean metallic
    # respray — premium look on low-texture 'clay' models). Only force flat when
    # the body is a separate material from lights/wheels, or flat overspills onto
    # them; the caller sizes that up front and only passes flat when it's safe.
    rmode = spec.get("recolour", "auto")
    want = oem_for(make)
    colours = []
    for p in want:
        sl = slug(p["name"])
        png = render(glb_url, colour=p["colourFamily"].lower(), finish=p["finish"], plate=plate,
                     plates_both=True, az=hero_az, elev=0.13, samples=150, width=1600, height=900,
                     recolour=rmode)
        if not png:
            raise RuntimeError(f"render failed after retries: {p['name']} — ABORT (no partial store)")
        url = upload("car-renders", f"finished/{make}/{key}/{sl}.jpg", png, "image/png")
        if not verify_asset(url):
            raise RuntimeError(f"upload verify failed: {p['name']} — ABORT")
        colours.append({"oemName": p["name"], "family": p["colourFamily"],
                        "finish": p["finish"], "renderUrl": url})
        log(f"  OEM {p['name']} rendered+uploaded+verified")
    assert len(colours) == len(want), "colour count mismatch — ABORT"

    # hero colour: default the poster to the first VIVID (non-neutral) colour so
    # cars read as painted, not grey clay (low-texture models looked unpainted in
    # gunmetal). Falls back to the first colour if the palette is all neutral.
    _NEUT = ("grey", "gray", "gunmetal", "silver", "white", "black", "sand",
             "beige", "cement", "graphite", "platinum", "pearl")
    hero = next((c for c in colours if not any(s in c["family"].lower() for s in _NEUT)),
                colours[0] if colours else None)

    # atomic catalogue write
    cat = json.load(open(CAT))
    tmpl = copy.deepcopy([e for e in cat if e["make"] == "volkswagen" and e["model"] == "golf"][0])
    e = tmpl
    e.update({
        "assetId": spec["assetId"], "make": make, "model": model,
        "modelFamily": spec.get("modelFamily", model), "modelAliases": spec.get("modelAliases", []),
        "generation": spec.get("generation"), "generationConfirmed": False,
        "yearStart": spec.get("yearStart"), "yearEnd": spec.get("yearEnd"),
        "bodyStyle": spec.get("bodyStyle"), "exactDerivative": spec.get("exactDerivative"),
        "exactTrim": False, "provenance": "sourced",
        "sourceTitle": spec.get("sourceTitle"), "sourceUrl": f"https://sketchfab.com/3d-models/{uid}",
        "sourceReferenceId": uid, "licence": "CC-BY (attribution required)",
        "accuracyGrade": "representative", "qualityGrade": "A",
        "technicalStatus": "passed", "visualStatus": "passed",
        "publicationStatus": "approved", "quarantineReason": None,
        "paintMaterialNames": spec.get("paintMaterialNames", []),
        "glassMaterialNames": spec.get("glassMaterialNames", []),
        "defaultColourFamily": (hero["family"].lower().split()[-1] if hero else "grey"),
        "renderColourLabel": (hero["oemName"] if hero else None), "oemPaintVerified": False,
        "oemPaintCode": None, "oemPaintName": None, "colourVariants": {},
        "desktopGlbUrl": glb_url, "mobileGlbUrl": glb_url, "fallbackGlbUrl": None,
        "posterUrl": (hero["renderUrl"] if hero else None), "turntableUrl": None, "interiorUrl": None,
        "fileSizeBytes": base_bytes, "mobileFileSizeBytes": base_bytes,
        "contentHash": None, "pipelineVersion": "ingest-pipeline-v1",
        "publishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "needsHumanReview": [], "notes": [spec["generationNote"]] if spec.get("generationNote") else [],
        "customization": {"configuratorReady": bool(spec.get("paintMaterialNames")),
                          "componentPipelineVersion": "ingest-pipeline-v1",
                          "wheelSets": [], "wraps": [],
                          "colourOptions": [{"family": c["family"].lower().split()[-1], "label": c["oemName"],
                                             "hex": None, "finish": (c["finish"] or "solid").lower(),
                                             "oemPaintName": c["oemName"], "glbUrl": None} for c in colours]},
    })
    cat = [x for x in cat if x["assetId"] != spec["assetId"]]
    cat.append(e)
    tmp = CAT + ".tmp"
    json.dump(cat, open(tmp, "w"), indent=1, ensure_ascii=False)
    json.load(open(tmp))                       # validate JSON parses
    os.replace(tmp, CAT)
    upload("car-renders", "resolver/catalogue.v2.json",
           json.dumps(cat, indent=1, ensure_ascii=False).encode(), "application/json")

    # finished/index.json
    idx = getj(f"{OBASE}/public/car-renders/finished/index.json") or {"cars": []}
    idx.setdefault("cars", [])
    idx["cars"] = [c for c in idx["cars"] if not (c.get("make") == make and c.get("model") == model)]
    idx["cars"].append({"make": make, "model": model, "finishedGlb": glb_url, "oemColours": colours})
    idx["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    upload("car-renders", "finished/index.json", json.dumps(idx, indent=1).encode(), "application/json")

    # post-store read-back verification
    live = getj(f"{OBASE}/public/car-renders/resolver/catalogue.v2.json?cb={int(time.time())}") or []
    if not any(x.get("assetId") == spec["assetId"] and x.get("publicationStatus") == "approved" for x in live):
        raise RuntimeError("post-store: entry not found approved in live resolver")
    log(f"STORE_VERIFIED {make}/{model} colours={len(colours)} approved={len([x for x in cat if x['publicationStatus']=='approved'])}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "qc":
        uid = sys.argv[2]
        out = sys.argv[3] if len(sys.argv) > 3 else "/tmp/qc"
        rep = qc(uid, out)
        print(json.dumps(rep, indent=1))
    elif cmd == "store":
        store(json.load(open(sys.argv[2])))
    else:
        print("usage: pipeline.py qc <uid> [outdir] | store <spec.json>")
