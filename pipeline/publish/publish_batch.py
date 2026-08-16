#!/usr/bin/env python3
"""publish_batch.py — the ONLY sanctioned path from a staged wave GLB to the
live catalogue. Built to the council mandate after the wave-5 rescue incident,
where hand-rolled publish scripts hardcoded visualStatus, inherited template
fields, and re-published already-shipped sources.

Six gates, all mandatory, none skippable by flag:

  G1  Owner review manifest. Every published item must appear in
      REVIEWED_KEEP.csv (the owner's recorded keep verdicts) with a glb_sha256;
      the staged GLB is downloaded and hashed, and a mismatch refuses the item
      — what ships is provably the exact file the owner reviewed.
  G2  Measured fields only. paintMaterialNames / glassMaterialNames /
      technicalStatus come from a fresh mat_audit of the UPLOADED public GLB,
      never copied from another entry. There is no template entry anywhere in
      this file. visualStatus is "owner-reviewed" solely because G1 proved the
      owner's verdict; nothing else may set it.
  G3  Source dedup. A sourceReferenceId already present in the catalogue —
      approved OR quarantined — refuses the item (quarantined means the owner
      already rejected that source; approved means it already ships).
  G4  Licence is RECORDED, not enforced (owner instruction 2026-07-30, "don't
      worry about licence"). Whatever LICENCES.csv states for the uid is written
      verbatim to the entry's `licence` field, and "unverified" when the uid is
      absent. It no longer refuses. Note the `licence` field used to be
      hardcoded to "CC-BY (attribution required)" — harmless while the gate
      guaranteed CC-BY, false the moment it did not, so it now carries the real
      string. Selection is decided on the render.
  G5  gate_catalogue wired into the only upload path. serve_catalogue() is the
      single function that can upload the catalogue, it runs the gate first,
      and it always writes BOTH public paths (resolver/ and root).
  G6  Smoke + breakers. The first item runs end-to-end and is re-verified
      before the batch continues; 8 consecutive network failures abort
      (storm breaker); 3 item crashes abort (crash breaker). Every network
      action is appended to jobs.jsonl.

Items publish single-neutral (no colourVariants). Colour baking and the
recolour audit stamp happen afterwards through pipeline/qc/recolour_audit.py
--stamp; gate_catalogue enforces that ordering. customization.colourOptions is
filled from platform/paint/oem_paint_db.csv for the entry's make only — an
absent make gets an empty list, never another car's paints.

Secrets arrive via env (SB_KEY, RP_KEY) per the no-secrets-in-repo rule.

Usage:
  SB_KEY=... RP_KEY=... python3 pipeline/publish/publish_batch.py \
      --keep REVIEWED_KEEP.csv --licences LICENCES.csv --wave w6 \
      [--staging-prefix staging/qc_wave6] [--limit N]

REVIEWED_KEEP.csv required columns:
  uid, glb_sha256, make, model, reviewed_at
optional columns (title-verbatim / owner-confirmed only, per accuracy rule):
  year_start, year_end, body_style, trim
"""
import argparse, csv, datetime, hashlib, http.client, json, os, re, ssl, subprocess, sys, time
import urllib.request, urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")
PAINT_DB = os.path.join(REPO, "platform", "paint", "oem_paint_db.csv")
SB_BASE = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
RP_EP = "https://api.runpod.ai/v2/ng8oiz4p2l0xa0"

SB = os.environ.get("SB_KEY") or sys.exit("FATAL: SB_KEY env var required")
RP = os.environ.get("RP_KEY") or sys.exit("FATAL: RP_KEY env var required")

ap = argparse.ArgumentParser()
ap.add_argument("--keep", required=True, help="owner review manifest (REVIEWED_KEEP.csv)")
ap.add_argument("--licences", required=True, help="LICENCES.csv from the wave run")
ap.add_argument("--wave", required=True, help="wave tag for assetIds/notes, e.g. w6")
ap.add_argument("--staging-prefix", default="staging/qc_wave6")
ap.add_argument("--limit", type=int, default=0, help="publish at most N items (0 = all)")
A = ap.parse_args()

JOBLOG = open(os.path.join(os.path.dirname(os.path.abspath(A.keep)), "publish_jobs.jsonl"), "a")
def jlog(**kw):
    JOBLOG.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **kw}) + "\n")
    JOBLOG.flush()

_consec_net_fail = 0

# Transport faults that are worth another attempt. urllib.error.URLError is in
# here for a specific, measured reason: a mid-transfer TLS cut surfaces as
# `URLError(<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING]>)`, NOT as
# IncompleteRead, so the original truncation fix did not cover it and one
# Porsche (28dbd433) still vanished from an otherwise clean batch. ssl.SSLError
# is listed separately because a cut during .read() — after the headers are in —
# is raised raw rather than wrapped in URLError.
TRANSIENT = (http.client.IncompleteRead, http.client.RemoteDisconnected,
             TimeoutError, ConnectionError, ssl.SSLError, urllib.error.URLError)

def net(req, timeout=120, tries=4):
    """All network goes through here so the storm breaker sees everything.

    Retries TRUNCATED reads. A partial body raises http.client.IncompleteRead,
    which used to propagate straight to the per-item crash handler: the item was
    logged CRASH, skipped, and — because a crash is not a REFUSED — the batch
    summary still printed "refused=0". That is how four cars vanished from
    apparently clean batches (a 1999 Odyssey, a Peugeot 405, a 2020 Ariya, a
    Subaru Legacy Wagon), each caught only by reconciling the keep list against
    the catalogue afterwards. GLBs here run to 48MB, so a mid-transfer cut is a
    routine event and must not cost a car.
    """
    global _consec_net_fail

    def _count_and_raise(e):
        global _consec_net_fail
        _consec_net_fail += 1
        if _consec_net_fail >= 8:
            jlog(event="STORM_BREAKER", fails=_consec_net_fail)
            print("STORM BREAKER: 8 consecutive network failures — environment "
                  "down, aborting resumably (re-run when it recovers)", flush=True)
            sys.exit(4)
        raise e

    last = None
    for a in range(tries):
        try:
            r = urllib.request.urlopen(req, timeout=timeout).read()
            _consec_net_fail = 0
            return r
        except TRANSIENT as e:
            # HTTPError subclasses URLError but is a real HTTP status, not a
            # transport fault — a 400 on a bad row must fail immediately, not
            # be retried four times.
            if isinstance(e, urllib.error.HTTPError):
                _count_and_raise(e)
            last = e
            if a < tries - 1:
                time.sleep(2 * (a + 1))
                continue
        except Exception as e:
            _count_and_raise(e)
    _count_and_raise(last)

def sb_req(path, data=None, method=None, ctype="application/json"):
    rq = urllib.request.Request(f"{SB_BASE}/{path}", data=data,
                                method=method or ("POST" if data else "GET"))
    for h, v in (("apikey", SB), ("Authorization", "Bearer " + SB), ("Content-Type", ctype)):
        rq.add_header(h, v)
    return rq

# ---- preflight canary --------------------------------------------------
def preflight():
    net(sb_req("list/car-meshes", json.dumps({"prefix": A.staging_prefix + "/", "limit": 1}).encode()), 30)
    rq = urllib.request.Request(f"{RP_EP}/health", headers={"Authorization": f"Bearer {RP}"})
    net(rq, 30)
    print("preflight OK: supabase + render endpoint reachable", flush=True)
    catalogue_is_current()


def catalogue_is_current():
    """G0: refuse to run on a catalogue that is behind the live one.

    serve_catalogue() overwrites BOTH public paths with whatever is on local
    disk. Correct when the checkout is current; catastrophic when it is not.
    On 2026-08-04 this container rolled back mid-session, reverting
    catalogue.v2.json to a pre-wave state, and the next publish served that
    stale file over production. The live index lost 20 approved entries -- every
    car published that day -- and none of the six gates noticed, because they
    all check the ITEM being published and none checks the BASE it is added to.

    Nothing was destroyed: the GLBs, colour variants and posters live under
    other paths and were never written, and origin still held the good
    catalogue, so recovery was a fast-forward and a re-serve. The hole is
    closed here rather than left to discipline -- a rollback is silent, and
    "remember to check git first" is not a control.

    Refusing on a LOWER local approved set is the point; a higher one is
    expected, since this batch is about to add to it. PUBLISH_ALLOW_STALE=1
    overrides, for a deliberate rollback only.
    """
    try:
        live = json.loads(net(sb_req("car-renders/catalogue.v2.json"), 60))
    except Exception as e:
        print(f"WARNING: could not read the live catalogue ({type(e).__name__}); "
              "staleness UNVERIFIED", flush=True)
        return
    live = live if isinstance(live, list) else live.get("entries", live)
    local = json.load(open(CAT))
    local = local if isinstance(local, list) else local.get("entries", local)
    la = {e["assetId"] for e in live if e.get("publicationStatus") == "approved"}
    ca = {e["assetId"] for e in local if e.get("publicationStatus") == "approved"}
    lost = sorted(la - ca)
    if lost:
        print(f"STALE CATALOGUE: local is missing {len(lost)} approved entries that are "
              f"live, e.g. {lost[:5]}", flush=True)
        print("  the checkout is behind production — publishing would overwrite the live "
              "index and drop those cars.", flush=True)
        print("  fix: git fetch origin <branch> && git merge --ff-only origin/<branch>",
              flush=True)
        if os.environ.get("PUBLISH_ALLOW_STALE") != "1":
            jlog(event="STALE_CATALOGUE", missing=len(lost))
            sys.exit(4)
        print("  PUBLISH_ALLOW_STALE=1 set — proceeding anyway", flush=True)
    print(f"catalogue current: local {len(ca)} approved vs live {len(la)}", flush=True)


try:
    preflight()
except SystemExit:
    raise
except Exception as e:
    print(f"PREFLIGHT FAILED ({type(e).__name__}) — aborting before any write", flush=True)
    sys.exit(3)

# ---- inputs ------------------------------------------------------------
keep = list(csv.DictReader(open(A.keep, encoding="utf-8-sig")))
need = {"uid", "glb_sha256", "make", "model", "reviewed_at"}
missing_cols = need - set(keep[0].keys() if keep else [])
if missing_cols:
    sys.exit(f"FATAL: {A.keep} missing required columns {sorted(missing_cols)}")
lic = {r["uid"]: r for r in csv.DictReader(open(A.licences, encoding="utf-8-sig"))}
cat = json.load(open(CAT))
known_sources = {e.get("sourceReferenceId") for e in cat if e.get("sourceReferenceId")}
known_ids = {e["assetId"] for e in cat}
paints = {}
for r in csv.DictReader(open(PAINT_DB)):
    # Key on the SAME normalised form the lookup uses. The DB writes
    # "Mercedes-Benz" with a hyphen while the lookup has always converted
    # hyphens to spaces, so every Mercedes entry ever published carried an
    # empty colourOptions list (measured 2026-08-16: 56 live cars). Keying
    # both sides identically is the fix; no make loses paints by it.
    paints.setdefault(r["MANUFACTURER"].strip().lower().replace("-", " "), []).append(r)

def _paint_make(make):
    """Resolve the make through the SAME alias map the resolver uses.

    The paint DB is keyed by UK marque (it holds 9 `vauxhall` rows and no
    `opel` rows), while a source title states the marque the uploader typed.
    platform/resolver/index.ts normalises BOTH the vehicle's make and the
    asset's make through aliases.json, so an entry filed `opel` matches a
    DVLA "VAUXHALL" lookup correctly — but this lookup used the raw string
    and silently returned [] for every aliased marque. Measured 2026-08-16:
    the whole vx1 wave shipped with empty colourOptions while real Vauxhall
    paints existed. Falls back to the raw make when the alias map is
    unreachable, which is the old behaviour and never worse.
    """
    m = make.lower().replace("-", " ").strip()
    try:
        with urllib.request.urlopen(
                f"{SB_BASE}/public/car-renders/resolver/aliases.json", timeout=20) as r:
            al = json.load(r).get("make", {})
        return (al.get(m) or m).lower().replace("-", " ")
    except Exception:
        return m


def colour_options(make):
    return [{"family": r["COLOUR_FAMILY"].strip().split()[-1].lower(),
             "label": r["OEM_PAINT_NAME"].strip(), "hex": None,
             "finish": r["FINISH"].strip().lower(),
             "oemPaintName": r["OEM_PAINT_NAME"].strip(), "glbUrl": None}
            for r in paints.get(_paint_make(make), [])]

def slug(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")

def mat_audit_public(url):
    """Fresh measured audit of the uploaded public GLB (G2) — also proves the
    public URL actually serves. runsync can return early with a job id on a
    cold worker, so fall back to polling /status."""
    body = json.dumps({"input": {"mat_audit": True, "glb_url": url}}).encode()
    rq = urllib.request.Request(f"{RP_EP}/runsync", data=body,
        headers={"Authorization": f"Bearer {RP}", "Content-Type": "application/json"})
    resp = json.loads(net(rq, 300))
    out = resp.get("output", {})
    jid = resp.get("id")
    t0 = time.time()
    while not out and jid and time.time() - t0 < 600:
        time.sleep(10)
        st = json.loads(net(urllib.request.Request(f"{RP_EP}/status/{jid}",
            headers={"Authorization": f"Bearer {RP}"}), 60))
        if st.get("status") == "COMPLETED":
            out = st.get("output", {})
        elif st.get("status") in ("FAILED", "CANCELLED", "TIMED_OUT"):
            break
    if out.get("status") != "success":
        raise RuntimeError(f"mat_audit on public URL failed: {str(out or resp)[:120]}")
    return out

def serve_catalogue():
    """G5: the ONLY catalogue upload. Gate first; both paths always."""
    g = subprocess.run([sys.executable, os.path.join(REPO, "pipeline", "qc", "gate_catalogue.py")],
                       capture_output=True, text=True)
    print(g.stdout.strip()[-400:], flush=True)
    if g.returncode != 0:
        jlog(event="GATE_FAIL")
        sys.exit("FATAL: gate_catalogue refused the catalogue — nothing served")
    data = open(CAT, "rb").read()
    for path in ("car-renders/resolver/catalogue.v2.json", "car-renders/catalogue.v2.json"):
        rq = sb_req(path, data, method="POST", ctype="application/json")
        rq.add_header("x-upsert", "true")
        net(rq, 120)
        jlog(event="served", path=path, bytes=len(data))
    print(f"catalogue served to BOTH paths ({len(data)} bytes)", flush=True)

# ---- per-item publish --------------------------------------------------
def publish_item(row):
    uid = row["uid"].strip()
    make, model = row["make"].strip(), row["model"].strip()
    if not (uid and row["glb_sha256"].strip() and make and model and row["reviewed_at"].strip()):
        return ("REFUSED", "incomplete manifest row")
    lr = lic.get(uid) or {}                                                  # G4
    licence_actual = (lr.get("licence") or "").strip() or "unverified"
    if uid in known_sources:                                                 # G3
        return ("REFUSED", "sourceReferenceId already in catalogue")

    blob = net(sb_req(f"car-meshes/{A.staging_prefix}/{uid}.glb"), 300)
    sha = hashlib.sha256(blob).hexdigest()
    if sha != row["glb_sha256"].strip().lower():                             # G1
        return ("REFUSED", f"sha256 mismatch (staged {sha[:12]} != reviewed {row['glb_sha256'][:12]})")

    ys = (row.get("year_start") or "").strip()
    aid = slug(f"{make}-{model}" + (f"-{ys}" if ys else "")) + f"-{A.wave}-v1"
    n = 1
    while aid in known_ids:
        n += 1
        aid = re.sub(r"-v\d+$", f"-v{n}", aid)

    dest = f"car-meshes/finished/{slug(make)}/{aid}.glb"
    rq = sb_req(dest, blob, method="POST", ctype="model/gltf-binary")
    rq.add_header("x-upsert", "true")
    net(rq, 300)
    pub_url = f"{SB_BASE}/public/{dest}"
    jlog(event="glb_uploaded", uid=uid, assetId=aid, sha256=sha, bytes=len(blob))

    audit = mat_audit_public(pub_url)                                        # G2
    mats = audit.get("materials", [])
    body_name = audit.get("chosen_body")
    # worker returns chosen_body as a str or a list of material names
    body_names = ([str(b) for b in body_name] if isinstance(body_name, list)
                  else [str(body_name)] if body_name else [])
    glass_names = [str(m["name"]) for m in mats if m.get("glass") and m.get("name")]

    today = datetime.date.today().isoformat()
    entry = {
        "schemaVersion": 2, "assetId": aid,
        "make": slug(make), "model": model,
        "modelFamily": f"{make} {model}".lower(), "modelAliases": [model],
        "generation": None, "generationAliases": [], "generationConfirmed": False,
        "yearStart": int(ys) if ys.isdigit() else None,
        "yearEnd": int(row["year_end"]) if (row.get("year_end") or "").strip().isdigit() else None,
        "bodyStyle": (row.get("body_style") or "").strip() or None,
        "compatibleFuelTypes": [],
        "compatibleTrimFamilies": [t for t in [(row.get("trim") or "").strip()] if t],
        "exactDerivative": None, "exactTrim": False,
        "provenance": "sourced",
        "sourceTitle": lr.get("title", ""), "sourceUrl": lr.get("page", ""),
        "sourceCreator": lr.get("author", ""), "sourceReferenceId": uid,
        "sourceRetrievedAt": today, "sourceEvidenceUrl": None,
        "licence": licence_actual,
        "generatedFromReference": False, "referenceImageCount": 0,
        "accuracyGrade": "representative", "qualityGrade": "B",
        "technicalStatus": "passed" if body_names else "no-body-material",
        "visualStatus": "owner-reviewed",     # G1 proved the owner's verdict
        "publicationStatus": "approved", "quarantineReason": None,
        "hasInterior": False, "interiorMode": "none",
        "hasSeparateDoors": False, "hasSeparateBonnet": False,
        "hasSeparateBoot": False, "supportsOpenableParts": False,
        "paintMaterialNames": body_names,
        "glassMaterialNames": glass_names,
        "defaultColourFamily": None, "renderColourLabel": None,
        "oemPaintVerified": False, "oemPaintCode": None, "oemPaintName": None,
        "colourVariants": None,
        "desktopGlbUrl": pub_url, "mobileGlbUrl": pub_url,
        "fallbackGlbUrl": None, "posterUrl": None, "turntableUrl": None,
        "interiorUrl": None,
        "fileSizeBytes": len(blob), "mobileFileSizeBytes": len(blob),
        "triangleCount": None, "vertexCount": None,
        "textureMemoryBytes": None, "maxTextureResolution": None,
        "contentHash": sha, "pipelineVersion": f"publish-batch-{A.wave}-{today}",
        "publishedAt": today, "replacedAssetId": None, "needsHumanReview": [],
        "notes": [f"{A.wave} gated publish {today}: licence recorded as '{licence_actual}' "
                  f"(author '{lr.get('author', '')}'), owner keep verdict {row['reviewed_at']}, "
                  f"sha256-verified against reviewed file; year/trim from review manifest "
                  f"(title-verbatim or owner-confirmed) only"],
        "customization": {"configuratorReady": False,
                          "componentPipelineVersion": f"publish-batch-{A.wave}",
                          "wheelSets": [], "wraps": [],
                          "colourOptions": colour_options(make)},
        "platesBaked": False,
    }
    cat.append(entry)
    known_ids.add(aid); known_sources.add(uid)
    json.dump(cat, open(CAT, "w"), indent=1, ensure_ascii=False)
    jlog(event="entry_added", uid=uid, assetId=aid)
    return ("PUBLISHED", aid)

# ---- batch with smoke + crash breaker (G6) ------------------------------
rows = keep[:A.limit] if A.limit else keep
crashes = 0
published, refused = [], []
for i, row in enumerate(rows):
    try:
        verdict, detail = publish_item(row)
    except SystemExit:
        raise
    except Exception as e:
        crashes += 1
        jlog(event="item_crash", uid=row.get("uid"), err=f"{type(e).__name__}: {str(e)[:120]}")
        print(f"CRASH {row.get('uid', '?')[:8]}: {type(e).__name__}: {str(e)[:100]}", flush=True)
        # A crash IS a car that did not publish. It used to be omitted from
        # both tallies, so the summary read "refused=0" on a batch that had
        # silently dropped a car -- four times before this was noticed.
        refused.append((row["uid"], f"CRASH {type(e).__name__}: {str(e)[:60]}"))
        if crashes >= 3:
            print("CRASH BREAKER: 3 item crashes — aborting batch (catalogue not served)", flush=True)
            sys.exit(5)
        continue
    (published if verdict == "PUBLISHED" else refused).append((row["uid"], detail))
    print(f"[{i+1}/{len(rows)}] {verdict} {row['uid'][:8]} {detail}", flush=True)
    if i == 0 and verdict == "PUBLISHED":
        # smoke: re-verify the first item end-to-end before continuing
        chk = net(urllib.request.Request(
            f"{SB_BASE}/public/car-meshes/finished/{slug(row['make'])}/{detail}.glb"), 120)
        if hashlib.sha256(chk).hexdigest() != row["glb_sha256"].strip().lower():
            sys.exit("SMOKE FAILED: first published GLB does not read back with the reviewed sha256")
        print(f"smoke OK: {detail} reads back byte-identical from the public URL", flush=True)

print(f"\npublished={len(published)} refused={len(refused)}", flush=True)
for u, why in refused:
    print(f"  refused {u[:8]}: {why}", flush=True)
if published:
    serve_catalogue()
else:
    print("nothing published — catalogue untouched, not served", flush=True)
