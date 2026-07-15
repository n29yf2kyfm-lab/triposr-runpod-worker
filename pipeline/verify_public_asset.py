#!/usr/bin/env python3
"""verify_public_asset.py — byte-level verification of published assets.
HTTP 200 alone never marks an asset healthy (product rule 7).

For each approved catalogue entry (or one --asset-id):
  1. GET the public desktopGlbUrl
  2. content length plausible (>100 KB)
  3. first four bytes == b"glTF"
  4. sha256 of downloaded bytes matches entry.contentHash (when recorded)
  5. Khronos glTF validator on the downloaded bytes -> 0 errors required

Exit 0 only when every checked asset passes. Writes reports/public-verify.json.

  python3 pipeline/verify_public_asset.py --catalogue platform/catalogue/catalogue.v2.json
  python3 pipeline/verify_public_asset.py --catalogue ... --asset-id hyundai-ioniq-x-2020-2022-v1
"""
import argparse, hashlib, json, os, subprocess, sys, tempfile, urllib.request, datetime

def check(entry):
    res = {"assetId": entry["assetId"], "url": entry["desktopGlbUrl"], "checks": {}}
    try:
        u = entry["desktopGlbUrl"]
        data = urllib.request.urlopen(
            u + ("&" if "?" in u else "?") + "cb=verify", timeout=300).read()
    except Exception as e:
        res["checks"]["fetch"] = f"FAIL: {e}"
        res["status"] = "failed"
        return res
    res["checks"]["fetch"] = "ok"
    res["checks"]["length"] = "ok" if len(data) > 100_000 else f"FAIL: {len(data)} bytes"
    res["checks"]["magic"] = "ok" if data[:4] == b"glTF" else f"FAIL: {data[:4]!r}"
    h = "sha256:" + hashlib.sha256(data).hexdigest()
    if entry.get("contentHash"):
        res["checks"]["hash"] = "ok" if h == entry["contentHash"] else f"FAIL: {h} != {entry['contentHash']}"
    else:
        res["checks"]["hash"] = "skipped (no recorded hash)"
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
        f.write(data); tmp = f.name
    try:
        val = subprocess.run(["node", os.path.join(os.path.dirname(__file__), "validate.js"), tmp],
                             capture_output=True, text=True, timeout=120)
        line = next((l for l in val.stdout.splitlines() if "errors=" in l), "")
        res["checks"]["validator"] = "ok" if "errors=0" in line else f"FAIL: {line or val.stderr[-120:]}"
    finally:
        os.unlink(tmp)
    res["status"] = "passed" if all(v == "ok" or v.startswith("skipped") for v in res["checks"].values()) else "failed"
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", required=True)
    ap.add_argument("--asset-id")
    ap.add_argument("--report", default="reports/public-verify.json")
    a = ap.parse_args()
    cat = json.load(open(a.catalogue, encoding="utf-8"))
    targets = [e for e in cat if e.get("publicationStatus") == "approved"
               and (not a.asset_id or e["assetId"] == a.asset_id)]
    results = [check(e) for e in targets]
    failed = [r for r in results if r["status"] == "failed"]
    report = {"verifiedAt": datetime.datetime.utcnow().isoformat() + "Z",
              "checked": len(results), "failed": len(failed), "results": results}
    os.makedirs(os.path.dirname(a.report), exist_ok=True)
    json.dump(report, open(a.report, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    for r in failed:
        print("FAIL", r["assetId"], r["checks"], file=sys.stderr)
    print(f"checked={len(results)} failed={len(failed)}")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
