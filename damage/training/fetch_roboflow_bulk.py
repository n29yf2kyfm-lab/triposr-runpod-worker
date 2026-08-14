"""Download the audited Roboflow projects, with a disk guard and resume.

Two agent sweeps produced manifests of car-damage projects on Roboflow
Universe. This pulls the ones that survived the licence and usability audit.

WHAT IS EXCLUDED, AND WHY IT MATTERS MORE THAN WHAT IS INCLUDED:

  cardd_derivative — 19 projects, 58,424 images. CarDD's official download is
    gated behind a signed licensing form emailed to its authors, so every free
    copy is unauthorised BY CONSTRUCTION and every permissive tag on one is
    false automatically. These carry MIT, Apache-2.0 and CC BY 4.0 tags; none
    of the uploaders had standing to apply them. Two sit inside otherwise-clean
    workspaces, which is exactly how one gets swept in when a workspace is
    harvested wholesale. Fingerprint: exactly dent/scratch/crack/glass shatter/
    lamp broken/tire flat, usually ~4,000 or ~10,000 images.

  versions == 0 — 29 projects, 53,883 images. No exportable release exists.
    The metadata looks perfectly healthy and the download always 404s.

  off-domain — roofs rather than cars, whole-vehicle boxes rather than damage
    regions, "car detected"/"not a car" class pairs.

LICENCE CAVEAT KEPT IN THE OUTPUT, NOT JUST THE DOCSTRING: 192 of 199 projects
in the second sweep carry the same default CC BY 4.0, so the tag conveys almost
no information, and the most permissive tags sit on the most obviously scraped
corpora. Every downloaded project therefore writes its declared licence into
provenance.jsonl so a later audit can find them without re-querying the API.

DISK GUARD. The volume has ~18GB free against an estimated ~11GB of exports,
and running it to zero would take the whole session down rather than just this
script. Downloads stop cleanly when free space falls below --min-free-gb.

    python fetch_roboflow_bulk.py --manifests DIR --out /home/user/rf/bulk \\
        --api-key KEY --min-free-gb 3
"""
import argparse
import json
import os
import shutil
import time
import zipfile

API = "https://api.roboflow.com"


def free_gb(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / (1 << 30)


def load_manifests(d):
    """Merge the sweep manifests, keeping only projects that passed the audit."""
    rows, seen = [], set()
    for name in ("sources_roboflow.json", "sources_roboflow2.json"):
        p = os.path.join(d, name)
        if not os.path.exists(p):
            continue
        with open(p) as f:
            data = json.load(f)
        for r in data.get("new_projects", []):
            path = r.get("path")
            if not path or path in seen:
                continue
            if r.get("cardd_derivative"):
                continue
            if (r.get("versions") or 0) == 0:
                continue
            if r.get("relevance") == "off-domain":
                continue
            seen.add(path)
            rows.append(r)
    rows.sort(key=lambda r: -(r.get("images") or 0))
    return rows


def resolve_version(sess, path, api_key, fallback):
    """The real latest version number, from the API rather than the count.

    The manifest records `versions` as a COUNT. Those usually coincide — a
    project reporting 586 versions really does expose version 586 — but they
    diverge the moment a version is deleted, and then every export 404s for a
    reason nothing in the metadata explains. The project endpoint returns
    versions[] with ids shaped "workspace/project/586", so take the number from
    there and only fall back to the count if the call fails.
    """
    try:
        r = sess.get(f"{API}/{path}", params={"api_key": api_key}, timeout=45)
        if r.status_code == 200:
            vs = r.json().get("versions") or []
            nums = []
            for v in vs:
                vid = str(v.get("id", ""))
                tail = vid.rsplit("/", 1)[-1]
                if tail.isdigit():
                    nums.append(int(tail))
            if nums:
                return max(nums)
    except Exception:
        pass
    return fallback


def download_project(sess, path, version, api_key, dest, tries=4):
    """Fetch one COCO export. Roboflow returns {"export":{"link":...}} and may
    answer {"progress":0} while it builds the zip, so a retry loop is required
    rather than optional."""
    url = f"{API}/{path}/{version}/coco"
    for attempt in range(tries):
        try:
            r = sess.get(url, params={"api_key": api_key}, timeout=90)
        except Exception:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code != 200:
            if r.status_code in (429, 502, 503):
                time.sleep(10 * (attempt + 1))
                continue
            return None, f"http {r.status_code}"
        try:
            j = r.json()
        except Exception:
            return None, "bad json"
        link = (j.get("export") or {}).get("link")
        if not link:
            time.sleep(8 * (attempt + 1))       # still building
            continue
        try:
            z = sess.get(link, timeout=300)
        except Exception:
            time.sleep(5 * (attempt + 1))
            continue
        if z.status_code != 200 or not z.content:
            time.sleep(5 * (attempt + 1))
            continue
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(z.content)
        os.rename(tmp, dest)
        return dest, None
    return None, "gave up"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifests", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--min-free-gb", type=float, default=3.0)
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import requests
    sess = requests.Session()
    sess.headers.update({"User-Agent": "triposr-damage-dataset/1.0"})

    rows = load_manifests(args.manifests)
    if args.limit:
        rows = rows[:args.limit]
    total_imgs = sum(r.get("images") or 0 for r in rows)
    print(f"{len(rows)} audited projects, {total_imgs:,} declared images")
    print(f"free disk: {free_gb('/'):.1f} GB (stop below {args.min_free_gb} GB)")
    if args.dry_run:
        for r in rows[:25]:
            print(f"  {r['path'][:56]:58s} {r.get('images',0):>7} "
                  f"v{r.get('versions')} {str(r.get('license'))[:16]}")
        return

    zips = os.path.join(args.out, "_zips")
    os.makedirs(zips, exist_ok=True)
    prov_path = os.path.join(args.out, "provenance.jsonl")
    done = set()
    if os.path.exists(prov_path):
        with open(prov_path) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["path"])
                except Exception:
                    pass
    print(f"already fetched: {len(done)}")

    ok = fail = skipped = 0
    got_imgs = 0
    with open(prov_path, "a") as prov:
        for i, r in enumerate(rows, 1):
            path = r["path"]
            if path in done:
                skipped += 1
                continue
            if free_gb("/") < args.min_free_gb:
                print(f"\nSTOPPING: free disk {free_gb('/'):.1f} GB below "
                      f"{args.min_free_gb} GB. {len(rows)-i+1} projects unfetched.")
                break
            ver = resolve_version(sess, path, args.api_key, r.get("versions") or 1)
            dest = os.path.join(zips, path.replace("/", "__") + ".zip")
            got, err = download_project(sess, path, ver, args.api_key, dest)
            if not got:
                fail += 1
                print(f"  [{i}/{len(rows)}] FAIL {path[:48]}: {err}")
                continue
            # count what actually arrived rather than trusting the metadata
            try:
                with zipfile.ZipFile(got) as z:
                    n = sum(1 for x in z.namelist()
                            if x.lower().endswith((".jpg", ".jpeg", ".png")))
            except Exception:
                n = 0
            got_imgs += n
            ok += 1
            prov.write(json.dumps({
                "path": path, "version": ver, "zip": os.path.basename(got),
                "declared_images": r.get("images"), "actual_images": n,
                "license_declared": r.get("license"),
                "classes": r.get("classes"), "relevance": r.get("relevance"),
                "note": "licence is the uploader's self-declared tag, unverified",
            }) + "\n")
            prov.flush()
            if ok % 10 == 0:
                print(f"  [{i}/{len(rows)}] {ok} ok, {fail} fail, "
                      f"{got_imgs:,} images, {free_gb('/'):.1f} GB free")
    print(f"\nfetched {ok}, failed {fail}, skipped {skipped}")
    print(f"images downloaded: {got_imgs:,}")
    print(f"free disk: {free_gb('/'):.1f} GB")
    print(f"zips -> {zips}")


if __name__ == "__main__":
    main()
