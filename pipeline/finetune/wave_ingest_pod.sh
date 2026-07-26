#!/bin/bash
# wave_ingest_pod.sh — grow the AlamCars training set with the owner-approved
# wave 1+2 shapes and the shape-usable quarantined library cars, then run the
# same data_toolkit pipeline Stage A used so the new assets are trainable.
#
# Safe by construction:
#   * only assets marked "approved" in finetune/training_candidates.json enter;
#   * quarantined library cars enter only if their reason is a QUALITY reason
#     (never wrong-vehicle / duplicate / broken-geometry);
#   * WebP textures are converted to PNG BEFORE rendering (Blender 3.0.1 in the
#     toolkit cannot read EXT_texture_webp — this cost us 218 cars once);
#   * every toolkit step skips assets it has already processed, so the existing
#     361-car dataset is untouched and only the new shapes cost GPU time.
# No secrets in this file (HF_TOKEN via pod env if needed).
ROOT=/workspace/alamcars
mkdir -p "$ROOT/logs"
( cd "$ROOT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="ingest_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$ROOT/logs/stage_b.log"      # launcher polls this name
exec > >(tee -a "$ROOT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$ROOT/logs/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export HF_TOKEN HUGGING_FACE_HUB_TOKEN
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:$PYTHONPATH
pip install -q tensorboard pandas easydict pillow || true
bash data_toolkit/setup.sh || echo "setup.sh failed (continuing)"
apt-get update -qq && apt-get install -y -qq libxi6 libxkbcommon-x11-0 libxfixes3 libxrender1 libsm6 libgl1 2>&1 | tail -1 || true
mkdir -p datasets && cp "$ROOT/AlamCars.py" datasets/AlamCars.py && touch datasets/__init__.py

status fetch-approved
python3 - <<'PY'
import csv, hashlib, json, os, urllib.request
ROOT="/workspace/alamcars"; RAW=f"{ROOT}/raw"
PUB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public"
os.makedirs(RAW, exist_ok=True)

def get(url, timeout=300):
    rq=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    return urllib.request.urlopen(rq, timeout=timeout).read()

cands=json.loads(get(f"{PUB}/car-renders/finetune/training_candidates.json?cb=1", 120))
approved=[c for c in cands if str(c.get("status","")).startswith("approved")]
print(f"approved wave candidates: {len(approved)}")

cat=json.loads(get(f"{PUB}/car-renders/catalogue.v2.json?cb=1", 120))
BAD=("wrong","duplicate","not a","melt","geometry","proportion","broken","de-dup","redundant")
quar=[e for e in cat if e.get("publicationStatus")=="quarantined" and e.get("desktopGlbUrl")
      and not any(k in (e.get("quarantineReason") or "").lower() for k in BAD)]
print(f"shape-usable quarantined library cars: {len(quar)}")

meta=f"{ROOT}/metadata.csv"
rows=list(csv.DictReader(open(meta)))
cols=list(rows[0].keys()) if rows else ["sha256","file_identifier","local_path","make","model","licence","source_url"]
have_ids={r.get("file_identifier") for r in rows}
have_sha={r.get("sha256") for r in rows}
print(f"existing dataset rows: {len(rows)}")

def add(ident, url, make, model, licence, source):
    if ident in have_ids:
        return "skip-known"
    try:
        data=get(url)
    except Exception as e:
        return f"fail {str(e)[:40]}"
    if len(data) < 150*1024:
        return "skip-tiny"
    sha=hashlib.sha256(data).hexdigest()
    if sha in have_sha:
        return "skip-dupe"
    open(f"{RAW}/{sha}.glb","wb").write(data)
    row={c:"" for c in cols}
    row.update({"sha256":sha,"file_identifier":ident,"local_path":f"{sha}.glb",
                "make":make,"model":model,"licence":licence,"source_url":source})
    rows.append(row); have_ids.add(ident); have_sha.add(sha)
    return f"ok {len(data)//1024}KB"

added=0
for c in approved:
    mk=c.get("relabel_make") or c.get("make"); md=c.get("relabel_model") or c.get("model")
    r=add(c["uid"], f"{PUB}/car-meshes/{c['glb_path']}", mk, md, c.get("licence"), c.get("source_url"))
    if r.startswith("ok"): added+=1
    print(f"  wave {mk} {md}: {r}", flush=True)
for e in quar:
    r=add(e["assetId"], e["desktopGlbUrl"], e.get("make"), e.get("model"),
          e.get("licence"), e.get("sourceUrl"))
    if r.startswith("ok"): added+=1
    print(f"  quar {e.get('assetId')}: {r}", flush=True)

with open(meta,"w",newline="") as f:
    w=csv.DictWriter(f, fieldnames=cols); w.writeheader()
    for r in rows: w.writerow({c:r.get(c,"") for c in cols})
print(f"INGEST: +{added} new assets; dataset now {len(rows)} rows")
PY

status webp-to-png
python3 - <<'PY'
# Blender 3.0.1 (pinned by the toolkit) cannot import EXT_texture_webp; convert
# in place. Idempotent — files without webp are left byte-identical.
import glob, io, json, os, struct
from PIL import Image

def convert(path):
    raw=open(path,'rb').read()
    if raw[:4]!=b'glTF': return "not-glb"
    ln=struct.unpack('<I',raw[8:12])[0]
    off=12; js=bn=None
    while off<ln:
        clen,ctyp=struct.unpack('<I4s',raw[off:off+8]); data=raw[off+8:off+8+clen]
        if ctyp==b'JSON': js=json.loads(data)
        elif ctyp==b'BIN\x00': bn=bytearray(data)
        off+=8+clen
    if js is None or 'images' not in js: return "no-images"
    if 'EXT_texture_webp' not in (js.get('extensionsUsed') or []): return "no-webp"
    bvs=js.get('bufferViews',[]); changed=False
    for img in js['images']:
        if img.get('mimeType')!='image/webp': continue
        bv=bvs[img['bufferView']]; s=bv.get('byteOffset',0); e=s+bv['byteLength']
        png=io.BytesIO(); Image.open(io.BytesIO(bytes(bn[s:e]))).save(png,'PNG')
        bn.extend(b'\0'*((-len(bn))%4))
        bvs.append({'buffer':0,'byteOffset':len(bn),'byteLength':len(png.getvalue())})
        bn.extend(png.getvalue())
        img['bufferView']=len(bvs)-1; img['mimeType']='image/png'; changed=True
    for tex in js.get('textures',[]):
        ext=(tex.get('extensions') or {}).pop('EXT_texture_webp',None)
        if ext is not None:
            tex.setdefault('source',ext.get('source'))
            if tex.get('source') is None: tex['source']=ext.get('source')
            if not tex.get('extensions'): tex.pop('extensions',None)
            changed=True
    for key in ('extensionsUsed','extensionsRequired'):
        if key in js and 'EXT_texture_webp' in js[key]:
            js[key]=[x for x in js[key] if x!='EXT_texture_webp']
            if not js[key]: del js[key]
    if not changed: return "no-webp"
    js['buffers'][0]['byteLength']=len(bn)
    jb=json.dumps(js,separators=(',',':')).encode(); jb+=b' '*((-len(jb))%4)
    bb=bytes(bn)+b'\0'*((-len(bn))%4)
    out=struct.pack('<4sII',b'glTF',2,12+8+len(jb)+8+len(bb))
    out+=struct.pack('<I4s',len(jb),b'JSON')+jb+struct.pack('<I4s',len(bb),b'BIN\x00')+bb
    open(path,'wb').write(out); return "converted"

stats={}
for p in sorted(glob.glob('/workspace/alamcars/raw/*.glb')):
    try: r=convert(p)
    except Exception as e: r=f"ERROR {str(e)[:50]}"
    stats[r]=stats.get(r,0)+1
print("WEBP2PNG:", stats)
PY

run(){ s="$1"; shift; status "$s"; "$@" || echo "STEP-FAILED $s (continuing)"; \
       python3 data_toolkit/build_metadata.py AlamCars --root "$ROOT" >/dev/null 2>&1 || true; }
run dump_mesh    python3 data_toolkit/dump_mesh.py    AlamCars --root "$ROOT"
run dump_pbr     python3 data_toolkit/dump_pbr.py     AlamCars --root "$ROOT"
run dual_grid    python3 data_toolkit/dual_grid.py    AlamCars --root "$ROOT" --resolution 256,512,1024
run render_cond  python3 data_toolkit/render_cond.py  AlamCars --root "$ROOT" --num_cond_views 16 --max_workers 8
run enc_shape    python3 data_toolkit/encode_shape_latent.py --root "$ROOT" --resolution 1024
LNAME=$(ls "$ROOT/shape_latents" 2>/dev/null | head -1)
if [ -n "$LNAME" ]; then run enc_ss python3 data_toolkit/encode_ss_latent.py --root "$ROOT" --shape_latent_name "$LNAME"
else echo "SKIP enc_ss: no shape_latents"; fi

status audit
python3 - <<'PY'
import glob, os, pandas as pd
root="/workspace/alamcars"
m=pd.read_csv(f"{root}/metadata.csv")
have={os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{root}/renders_cond/*/transforms.json")}
lat=len(glob.glob(f"{root}/shape_latents/*/*.npz"))+len(glob.glob(f"{root}/shape_latents/*/*.pt"))
print(f"DATASET: {len(m)} assets | cond renders {len(have)} | shape-latent files {lat}")
missing=[r for _,r in m.iterrows() if r["sha256"] not in have]
print(f"without cond renders: {len(missing)}")
for r in missing[:15]: print("   ", r["sha256"][:12], r.get("make"), r.get("model"))
PY

status DONE
df -h /workspace | tail -1
sleep infinity
