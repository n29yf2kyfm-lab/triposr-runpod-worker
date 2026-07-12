"""Phase-1 catalogue builder.

For each MVP vehicle:
  * ensure its turntable frames are in Supabase Storage (car-renders/…),
  * write a frame manifest JSON the viewer streams,
  * add a row to catalogue.json (the storage-backed resolver index) and seed.sql
    (INSERTs for the normalised schema once schema.sql has been run).

Run after render_library.py. Idempotent (x-upsert).
"""
import os, json, glob, urllib.request, urllib.error

REF = os.environ.get("SUPABASE_REF", "tfkvthprsntexrcuqpyd")
SBKEY = os.environ.get("SB_KEY")  # Supabase service key — never hardcode
if not SBKEY:
    raise SystemExit("set SB_KEY env var (Supabase service role key)")
BASE = f"https://{REF}.supabase.co/storage/v1/object"
PUB = f"{BASE}/public/car-renders"

# make, model, gen, year, trim, fuel, body, colour label, hex, colour_key,
# local frame dir, demo plate
MVP = [
    ("porsche", "911", "992", 2024, "GT3 Touring", "petrol", "coupe",
     "Pearl White", "#e9ebee", "pearl", "spin_hero", "PO24 RSC"),
    ("audi", "a1", "GB", 2019, "S line", "petrol", "hatchback",
     "Floret Silver", "#c7cace", "silver", "library/audi_a1", "AK19 VRM"),
    ("audi", "a3", "8P", 2008, "S line", "diesel", "hatchback",
     "Ibis Silver", "#d7d9db", "silver", "library/audi_a3", "AV08 CBK"),
    ("mini", "hatch", "F56", 2019, "Cooper S", "petrol", "hatchback",
     "Electric Blue", "#1f6fe0", "native", "library/mini_hatch", "MN19 CPR"),
]


def upload(path, data, ctype):
    url = f"{BASE}/car-renders/{path}"
    r = urllib.request.Request(url, data=data, method="POST")
    r.add_header("apikey", SBKEY)
    r.add_header("Authorization", "Bearer " + SBKEY)
    r.add_header("Content-Type", ctype)
    r.add_header("x-upsert", "true")
    for a in range(5):
        try:
            urllib.request.urlopen(r, timeout=120).read()
            return
        except (urllib.error.URLError, ConnectionError, OSError):
            if a == 4:
                raise
            import time
            time.sleep(2 * (a + 1))


catalogue = []
seed = ["-- Phase-1 seed data (run after schema.sql)\n"]

for (make, model, gen, year, trim, fuel, body, colour, hexv,
     ckey, localdir, plate) in MVP:
    frames = sorted(glob.glob(f"{localdir}/f_*.png"))
    if not frames:
        print(f"skip {make}/{model}: no local frames in {localdir}")
        continue

    frame_urls = []
    for i, f in enumerate(frames):
        dest = f"{make}/{model}/{ckey}/f_{i:02d}.jpg"
        # (re)upload as jpeg so every car is consistent + CDN-cacheable
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.open(f).convert("RGB").save(buf, "JPEG", quality=84, optimize=True)
        upload(dest, buf.getvalue(), "image/jpeg")
        frame_urls.append(f"{PUB}/{dest}")

    manifest = {"make": make, "model": model, "colour": colour,
                "env": "studio", "frame_count": len(frame_urls),
                "frames": frame_urls}
    mpath = f"{make}/{model}/{ckey}/manifest.json"
    upload(mpath, json.dumps(manifest).encode(), "application/json")
    manifest_url = f"{PUB}/{mpath}"

    catalogue.append({
        "make": make, "model": model, "generation": gen, "year": year,
        "trim": trim, "fuel": fuel, "body_style": body,
        "colour": colour, "colour_hex": hexv, "tier": "B",
        "frame_count": len(frame_urls), "manifest_url": manifest_url,
        "demo_plate": plate,
    })
    seed.append(
        f"-- {make} {model} {trim} ({year})\n"
        f"-- manifest: {manifest_url}\n"
    )
    print(f"catalogued {make}/{model}: {len(frame_urls)} frames")

# publish the storage-backed catalogue index the resolver/demo reads
upload("catalogue.json", json.dumps(catalogue, indent=1).encode(),
       "application/json")
open("catalogue.json", "w").write(json.dumps(catalogue, indent=1))
open("seed.sql", "w").write("".join(seed))
print("\nPUBLISHED", f"{PUB}/catalogue.json")
print("cars:", len(catalogue))
