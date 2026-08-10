#!/usr/bin/env python3
"""Build a review datasheet of the PASSING cars for a marque.
Usage: mkdatasheet.py <marque>   (reads pipeline/ingest/<marque>_audit_verdicts.json)
Writes <scratch>/<marque>_datasheet.html with each pass tile + face count + uid,
and a wheel-zoom crop beside it so tyre colour is checkable at a glance."""
import json, os, io, sys, base64, html, urllib.request, concurrent.futures as cf
from PIL import Image
M=sys.argv[1]
SCRATCH="/tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad"
SB="https://tfkvthprsntexrcuqpyd.supabase.co"; K=os.environ["SB_KEY"]
v=json.load(open(f'pipeline/ingest/{M}_audit_verdicts.json'))
try: rows={r['uid']:r for r in json.load(open(f'/tmp/{M}/manifest.filtered.json'))}
except Exception: rows={}
p=[x for x in v if x['verdict']=='pass']
def b64(im,q=74):
    o=io.BytesIO(); im.save(o,"JPEG",quality=q,optimize=True); return base64.b64encode(o.getvalue()).decode()
def get(x):
    rq=urllib.request.Request(f"{SB}/storage/v1/object/car-meshes/audit/{M}/{x['uid']}.jpg",
        headers={"apikey":K,"Authorization":f"Bearer {K}"})
    try:
        im=Image.open(io.BytesIO(urllib.request.urlopen(rq,timeout=120).read())).convert("RGB")
    except Exception: return None
    W,H=im.size
    side=im.crop((0,H//2,W//2,H)); w,h=side.size
    wheel=side.crop((int(w*0.50),int(h*0.46),int(w*0.88),int(h*0.92))).resize((420,430),Image.LANCZOS)
    full=im.copy(); full.thumbnail((880,880))
    return x, b64(full), b64(wheel,80)
with cf.ThreadPoolExecutor(max_workers=8) as ex: got=[g for g in ex.map(get,p) if g]
got.sort(key=lambda t:t[0]['name'].lower())
tiles=[]
for i,(x,full,wheel) in enumerate(got,1):
    f=rows.get(x['uid'],{}).get('faces',0)
    # Caption FIRST. It used to sit after the images, so scrolling on a phone
    # showed: wheel zoom -> caption -> NEXT car's sheet, which reads as though
    # the caption labels the picture below it. The owner reasonably took two
    # correctly-labelled cars for mislabelled ones.
    tiles.append(f'''<figure>
<figcaption><span class="n">#{i}</span> {html.escape(x['name'])}
<span class="meta">{f:,} faces · {x['uid'][:8]}</span></figcaption>
<img loading="lazy" src="data:image/jpeg;base64,{full}" alt="{html.escape(x['name'])}">
<div class="wz"><img loading="lazy" src="data:image/jpeg;base64,{wheel}" alt="wheel zoom">
<span>wheel zoom — tyres must read BLACK</span></div></figure>''')
tot=len(v); np_=sum(1 for x in v if x['verdict']=='pass')
nf=sum(1 for x in v if x['verdict']=='fail'); nr=sum(1 for x in v if x['verdict']=='fail-rerender')
page=f'''<title>{M.title()} wave — {np_} passes</title>
<style>
:root{{--bg:#faf9f7;--fg:#1a1a1a;--mut:#6b6b6b;--line:#e2e0dc;--card:#fff}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#141414;--fg:#ececec;--mut:#9a9a9a;--line:#2e2e2e;--card:#1d1d1d}}}}
:root[data-theme="dark"]{{--bg:#141414;--fg:#ececec;--mut:#9a9a9a;--line:#2e2e2e;--card:#1d1d1d}}
*{{box-sizing:border-box}}
body{{background:var(--bg);color:var(--fg);margin:0;padding:2rem 1.25rem 4rem;font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}}
header{{max-width:1500px;margin:0 auto 2rem}} h1{{font-size:1.6rem;margin:0 0 .4rem}}
.sub{{color:var(--mut);margin:0 0 1rem;max-width:66ch}}
.stats{{display:flex;flex-wrap:wrap;gap:.5rem 1.5rem;padding:.9rem 1.1rem;background:var(--card);border:1px solid var(--line);border-radius:10px}}
.stats div{{font-size:.9rem}} .stats b{{font-size:1.15rem;display:block}}
.grid{{max-width:1500px;margin:0 auto;display:grid;gap:1.25rem;grid-template-columns:repeat(auto-fill,minmax(340px,1fr))}}
figure{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
img{{width:100%;display:block;background:#0b0b0b}}
.wz{{position:relative;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}}
.wz img{{width:60%;margin:0 auto}}
.wz span{{display:block;text-align:center;font-size:.7rem;color:var(--mut);padding:.2rem 0 .35rem}}
figcaption{{padding:.6rem .8rem;font-size:.88rem;border-bottom:2px solid var(--line);background:var(--card);position:sticky;top:0;z-index:2}}
.n{{font-weight:700;margin-right:.35rem}} .meta{{display:block;color:var(--mut);font-size:.78rem;margin-top:.15rem}}
</style>
<header><h1>{M.title()} wave — {np_} passes</h1>
<p class="sub">Every rendered sheet was audited individually against the owner rubric:
tyres must read as black rubber, glazing must read as glass, rim faces must be present.
Each tile carries a wheel zoom so the tyre check is verifiable at a glance.</p>
<div class="stats"><div><b>{tot}</b>audited</div><div><b>{np_}</b>passed</div>
<div><b>{nf}</b>failed</div><div><b>{nr}</b>fail-rerender</div>
<div><b>{round(100*np_/tot) if tot else 0}%</b>survival</div></div></header>
<div class="grid">{''.join(tiles)}</div>'''
out=f"{SCRATCH}/{M}_datasheet.html"
open(out,'w').write(page)
print(f"{M}: {len(got)} tiles, {len(page)/1e6:.1f} MB -> {out}")
