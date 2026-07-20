#!/usr/bin/env python3
"""Live Sketchfab search sourcing: for each target model, search the API (downloadable,
CC-BY/CC0), junk-filter, render top-N raw candidates at standard settings. Build per-model
sheets + one combined audit sheet. Token-rotating. Usage: live_cand.py <targets.json> <tag>"""
import sys, json, re, os, base64, urllib.request, urllib.parse, time, itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageDraw, ImageFont
import config
HERE=os.path.dirname(os.path.abspath(__file__))
S=config.WORKDIR; os.makedirs(S, exist_ok=True)
_tok=itertools.cycle(config.sketchfab_tokens())
SBKEY=config.supabase_service_key()
RP=config.runpod_api_key(); EP=config.RUNPOD_ENDPOINT
OB=config.SUPABASE_OBJECT_URL
JUNK=["wreck","crush","destroy","burnt","rusty","lowpoly","concept","rally","drift","widebody","body kit",
 "police","taxi","fortnite","asphalt"," gta","roblox","toon","cartoon","liberty","lbworks","stance","hotwheels",
 "interior only","engine only","wheel","rim only","spoiler","seat","steering","hoonigan","livery","nascar","f1 ",
 "formula","kart","monster","6x6","apocalyp","zombie","military","tank","printable","for print","3d print","keychain","diorama"]
def toks(): return next(_tok)
def api(url):
    for _ in range(8):
        r=urllib.request.Request(url); r.add_header("Authorization","Token "+toks())
        try: return json.loads(urllib.request.urlopen(r,timeout=60).read())
        except urllib.error.HTTPError as e:
            if e.code in (429,403): time.sleep(3); continue
            time.sleep(2)
        except Exception: time.sleep(2)
    return None
def search(q,n=24):
    p=urllib.parse.urlencode({"q":q,"downloadable":"true","archives_flavours":"true","type":"models","count":n,"sort_by":"-likeCount"})
    d=api("https://api.sketchfab.com/v3/search?"+p); return (d or {}).get("results",[]) if d else []
def dl_url(uid):
    d=api(f"https://api.sketchfab.com/v3/models/{uid}/download"); return (d.get("glb") or {}).get("url") if d else None
def rp(u,m="GET",b=None):
    d=json.dumps(b).encode() if b else None
    rq=urllib.request.Request(u,data=d,method=m); rq.add_header("Authorization","Bearer "+RP); rq.add_header("Content-Type","application/json")
    for a in range(6):
        try: return json.loads(urllib.request.urlopen(rq,timeout=150).read())
        except Exception:
            if a==5: return {}
            time.sleep(2*(a+1))
def put(p,d,ct):
    h={"apikey":SBKEY,"Authorization":f"Bearer {SBKEY}","Content-Type":ct,"x-upsert":"true","cache-control":"no-cache"}
    return urllib.request.urlopen(urllib.request.Request(f"{OB}/{p}",data=d,method="POST",headers=h),timeout=240).status
def norm(s): return re.sub(r'[^a-z0-9]','',(s or '').lower())
TARGETS=json.load(open(sys.argv[1])); TAG=sys.argv[2] if len(sys.argv)>2 else "live"
A=f"{S}/batch/{TAG}"; os.makedirs(A,exist_ok=True)
def pick(model_key, q):
    seen={}
    for res in search(q):
        nm=res["name"].lower(); lic=(res.get("license") or {}).get("slug","")
        if not("cc-by" in lic or "cc0" in lic or lic==""): continue
        if any(j in nm for j in JUNK): continue
        if model_key not in norm(res["name"]) and model_key not in norm(res.get("description","")[:60] or ""):
            # require the model token to appear in the name (avoid wrong cars)
            if model_key not in norm(res["name"]): continue
        fc=res.get("faceCount") or 0
        if fc and (fc<8000 or fc>3_500_000): continue
        seen[res["uid"]]=(res.get("likeCount") or 0, res["name"][:44])
    return sorted([(lk,u,n) for u,(lk,n) in seen.items()],reverse=True)[:3]
def render_one(mk,key,human,lk,uid,nm):
    raw=f"{A}/{key}_{uid}.glb"
    try:
        url=dl_url(uid)
        if not url: return (key,uid,None,nm,lk,"nodl")
        urllib.request.urlretrieve(url,raw); sz=os.path.getsize(raw)
        if sz<40000: return (key,uid,None,nm,lk,"tiny")
        stg=f"car-meshes/staging/lc_{uid}.glb"
        if put(stg,open(raw,"rb").read(),"model/gltf-binary") not in (200,201): return (key,uid,None,nm,lk,"putfail")
        o=(rp(f"https://api.runpod.ai/v2/{EP}/runsync","POST",{"input":{"glb_url":f"{OB}/public/{stg}","recolour":"auto","colour":"grey","studio":True,"az":40,"elev":0.13,"samples":80,"width":640,"height":400}}) or {}).get("output",{}) or {}
        if o.get("png_b64"):
            open(f"{A}/{key}_{uid}.png","wb").write(base64.b64decode(o["png_b64"])); return (key,uid,f"{A}/{key}_{uid}.png",nm,lk,f"{sz//1024}KB")
        return (key,uid,None,nm,lk,"norender")
    except Exception as e: return (key,uid,None,nm,lk,str(e)[:30])
    finally:
        try: os.remove(raw)
        except OSError: pass
# gather candidates (search is sequential-ish but fast)
jobs=[]; candmap={}
for mk,key,human,q in TARGETS:
    cs=pick(key,q); candmap[key]=(human,cs)
    for lk,uid,nm in cs: jobs.append((mk,key,human,lk,uid,nm))
    print(f"search {human:22s} -> {len(cs)} candidates",flush=True)
res={}
with ThreadPoolExecutor(max_workers=5) as ex:
    for f in as_completed([ex.submit(render_one,*j) for j in jobs]):
        key,uid,p,nm,lk,why=f.result(); res.setdefault(key,[]).append((p,uid,nm,lk,why))
        print(("OK " if p else "XX "),key,uid[:10],f"L{lk}",why,nm,flush=True)
try: font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",15)
except Exception: font=ImageFont.load_default()
tw,th,lab=640,400,34
# per-model sheets
for mk,key,human,q in TARGETS:
    cl=[c for c in res.get(key,[]) if c[0]]
    if not cl: continue
    cols=len(cl); sh=Image.new("RGB",(cols*tw,th+lab),(15,15,17)); dr=ImageDraw.Draw(sh)
    for k,(p,uid,nm,lk,why) in enumerate(cl):
        x=k*tw; dr.text((x+4,4),f"{human} | {uid[:12]} L{lk}",fill=(150,220,150),font=font); dr.text((x+4,19),nm[:52],fill=(200,200,210),font=font)
        if p and os.path.exists(p): sh.paste(Image.open(p).convert("RGB"),(x,lab))
    sh.save(f"{A}/{key}.jpg","JPEG",quality=86)
# combined audit sheet (best candidate per model, 3 cols)
best=[]
for mk,key,human,q in TARGETS:
    cl=[c for c in res.get(key,[]) if c[0]]
    if cl: best.append((human,key,cl))
json.dump({k:[(u,n,l,w) for (p,u,n,l,w) in v] for k,v in res.items()}, open(f"{A}/index.json","w"), indent=1)
print("LIVE_CAND_DONE",A,"models_with_candidates=",len(best))
