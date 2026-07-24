#!/bin/bash
# stage_a_condfix.sh — forensic-audit fix F1: Stage A left only 142/365 assets
# with conditioning renders, which silently caps training at 142 cars. This
# audits WHY, then re-runs render_cond for the missing assets only (upstream
# skips anything with transforms.json, so the good 142 are never touched), and
# deliberately does NOT rewrite the root metadata.csv — a concurrently running
# Stage B resume-probe re-reads it, and the next stage boot's metadata-merge
# sweeps the per-directory records this produces. Progress on :8000. No secrets.
ROOT=/workspace/alamcars
OUT=/workspace/alam3d_condfix
mkdir -p "$OUT/logs"
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="condfix_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT/logs/stage_b.log"   # poller compatibility
exec > >(tee -a "$OUT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT/logs/status.json"; echo "===== $1 ====="; }

status boot
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:$PYTHONPATH
# datasets/ ships empty upstream (subset modules are user-provided), so a fresh
# container has no such dir — py3 namespace packages make it importable bare
mkdir -p datasets
cp "$ROOT/AlamCars.py" datasets/ || { status FATAL-no-shim; sleep infinity; }

status audit-before
python3 - <<'PY'
import os, glob, pandas as pd
root="/workspace/alamcars"
m=pd.read_csv(f"{root}/metadata.csv")
have={os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{root}/renders_cond/*/transforms.json")}
partial={os.path.basename(p.rstrip('/')) for p in glob.glob(f"{root}/renders_cond/*/")}-have
print(f"metadata rows: {len(m)}; complete cond renders: {len(have)}; "
      f"partial (no transforms.json, will re-render): {len(partial)}; "
      f"missing entirely: {len(set(m['sha256'])-have-partial)}")
PY
# WHY were they missed? pull error lines from any Stage A logs on the volume.
for f in $(find /workspace -maxdepth 3 -name "*stage_a*.log" 2>/dev/null | head -5); do
  echo "--- errors in $f:"
  grep -aiE "foreach_instance error|Traceback|killed|CUDA|blender" "$f" | sort | uniq -c | sort -rn | head -10
done

status deps
bash data_toolkit/setup.sh || echo "setup.sh failed (continuing)"
# blender needs X client libs even headless; image has some, not all, and
# upstream's installer uses sudo which containers lack — install directly
apt-get update -qq && apt-get install -y -qq libxi6 libxkbcommon-x11-0 libxfixes3 libxrender1 libsm6 libgl1 2>&1 | tail -1 || true

status webp-to-png
# ROOT CAUSE (proven by un-devnulled blender log 2026-07-24): the 218 failing
# assets embed WebP textures (EXT_texture_webp) — Blender 3.0.1's glTF importer
# (pinned by upstream) predates WebP. Convert the textures to PNG in-place in
# the raw GLBs; geometry untouched, trainer never reads raw/, and the sha256
# filenames stay as row keys (metadata is NOT rewritten — a concurrent Stage B
# resume re-reads it). Idempotent: files without webp are left byte-identical.
python3 - <<'PY'
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
    bvs=js.get('bufferViews',[])
    changed=False
    for img in js['images']:
        if img.get('mimeType')!='image/webp': continue
        bv=bvs[img['bufferView']]
        s=bv.get('byteOffset',0); e=s+bv['byteLength']
        png=io.BytesIO(); Image.open(io.BytesIO(bytes(bn[s:e]))).save(png,'PNG')
        pad=(-len(bn))%4; bn.extend(b'\0'*pad)
        bvs.append({'buffer':0,'byteOffset':len(bn),'byteLength':len(png.getvalue())})
        bn.extend(png.getvalue())
        img['bufferView']=len(bvs)-1; img['mimeType']='image/png'; changed=True
    for tex in js.get('textures',[]):
        ext=(tex.get('extensions') or {}).pop('EXT_texture_webp',None)
        if ext is not None:
            tex.setdefault('source',ext.get('source'))
            if tex['source'] is None: tex['source']=ext.get('source')
            if not tex['extensions']: del tex['extensions']
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
    open(path,'wb').write(out)
    return "converted"

stats={}
for p in sorted(glob.glob('/workspace/alamcars/raw/*.glb')):
    try: r=convert(p)
    except Exception as e: r=f"ERROR {str(e)[:60]}"
    stats[r]=stats.get(r,0)+1
    if r.startswith(("converted","ERROR")): print(os.path.basename(p)[:12], r)
print("WEBP2PNG:", stats)
PY

status reproduce-one-failure
# upstream devnulls blender output, hiding why 218 instances fail in ~1.5s;
# un-silence it so the real per-instance error lands in this log
sed -i 's/call(args, stdout=DEVNULL, stderr=DEVNULL)/call(args)/' data_toolkit/render_cond.py
python3 - <<'PY'
import os, glob, pandas as pd
root="/workspace/alamcars"
m=pd.read_csv(f"{root}/metadata.csv")
have={os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{root}/renders_cond/*/transforms.json")}
missing=[r for _,r in m.iterrows() if r["sha256"] not in have]
if missing:
    r=missing[0]
    print("reproducing:", r["sha256"][:12], r.get("make"), r.get("model"), r.get("local_path"))
    open("/tmp/one_missing.txt","w").write(r["sha256"])
PY

status render-cond-backfill
python3 data_toolkit/render_cond.py AlamCars --root "$ROOT" \
  --num_cond_views 16 --max_workers 8 \
  || echo "RENDER_COND FAILED (see log)"

status audit-after
python3 - <<'PY'
import os, glob, pandas as pd
root="/workspace/alamcars"
m=pd.read_csv(f"{root}/metadata.csv")
have={os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{root}/renders_cond/*/transforms.json")}
missing=sorted(set(m['sha256'])-have)
print(f"AFTER: complete cond renders {len(have)}/{len(m)}; still missing {len(missing)}")
for s in missing[:20]:
    row=m[m['sha256']==s].iloc[0]
    print("  still-missing:", s[:12], row.get('make'), row.get('model'))
PY

status DONE
sleep infinity
