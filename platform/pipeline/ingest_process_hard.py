#!/usr/bin/env python3
"""Wave ingest — PHASE 1 HARDENED. Normal path uses fix_glb_hard.py (bakes world
transforms, recalcs normals OUTWARD, normalizes extreme scale -> fixes mis-scale blobs,
detached wheels, and many inverted-normal dark renders). After the verify render, if the
plated result is DARK or a BLOB (brightness gate), auto-fall-back to a PLATELESS path
(copy->webp->draco, no Blender) which renders correctly like the raw source — recovering
models whose complex material graph the Blender exporter mangles. Records path used.
Usage: ingest_process_hard.py <spec.json> <tag>"""
import sys, json, re, os, base64, subprocess, urllib.request, time, shutil, itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageDraw, ImageFont, ImageStat
import config
HERE=os.path.dirname(os.path.abspath(__file__))
S=config.WORKDIR; os.makedirs(S, exist_ok=True)
_tok=itertools.cycle(config.sketchfab_tokens())
SBKEY=config.supabase_service_key()
RP=config.runpod_api_key(); EP=config.RUNPOD_ENDPOINT
OB=config.SUPABASE_OBJECT_URL; GT=["npx","--yes","@gltf-transform/cli@4"]
DARK_GATE=22.0   # verify-render brightness below this => body black / blob => fall back
def sapi(p):
    for _ in range(10):
        tok=next(_tok); r=urllib.request.Request("https://api.sketchfab.com/v3/"+p); r.add_header("Authorization","Token "+tok)
        try: return json.loads(urllib.request.urlopen(r,timeout=60).read())
        except urllib.error.HTTPError as e:
            if e.code in (429,403): time.sleep(4); continue
            time.sleep(2)
        except Exception: time.sleep(2)
    return None
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
    return urllib.request.urlopen(urllib.request.Request(f"{OB}/{p}",data=d,method="POST",headers=h),timeout=300).status
def gt(args,to=500): subprocess.run(GT+args,capture_output=True,text=True,timeout=to)
def plated(src_glb,out_glb,tmp,upright):
    """Normal path: copy -> fix_glb_hard (plate + harden) -> webp -> draco."""
    copy=f"{tmp}_c.glb"; fx=f"{tmp}_f.glb"; wf=f"{tmp}_w.glb"
    gt(["copy",src_glb,copy]); step=copy if os.path.exists(copy) and os.path.getsize(copy)>20000 else src_glb
    fixer="fix_glb_np.py" if upright else "fix_glb_hard.py"
    subprocess.run(["blender","-b","-P",f"{HERE}/{fixer}","--",step,fx,"AL24 3D"],capture_output=True,text=True,timeout=800)
    if not(os.path.exists(fx) and os.path.getsize(fx)>20000): return None
    gt(["webp",fx,wf,"--quality","82"]); step=wf if os.path.exists(wf) and os.path.getsize(wf)>20000 else fx
    gt(["draco",step,out_glb])
    if not(os.path.exists(out_glb) and os.path.getsize(out_glb)>20000): shutil.copy(step,out_glb)
    for f in (copy,fx,wf):
        try: os.remove(f)
        except OSError: pass
    return out_glb
def plateless(src_glb,out_glb,tmp):
    """Fallback: copy -> webp -> draco (NO Blender) — preserves source material graph."""
    copy=f"{tmp}_pc.glb"; wf=f"{tmp}_pw.glb"
    gt(["copy",src_glb,copy]); step=copy if os.path.exists(copy) and os.path.getsize(copy)>20000 else src_glb
    gt(["webp",step,wf,"--quality","82"]); step=wf if os.path.exists(wf) and os.path.getsize(wf)>20000 else step
    gt(["draco",step,out_glb])
    if not(os.path.exists(out_glb) and os.path.getsize(out_glb)>20000): shutil.copy(step,out_glb)
    for f in (copy,wf):
        try: os.remove(f)
        except OSError: pass
    return out_glb
def render(url):
    jid=rp(f"https://api.runpod.ai/v2/{EP}/run","POST",{"input":{"glb_url":url+f"?cb={int(time.time())}","recolour":"auto","colour":"grey","studio":True,"az":40,"elev":0.13,"samples":100,"width":820,"height":500}}).get("id")
    if not jid: return None,[]
    for _ in range(80):
        st=rp(f"https://api.runpod.ai/v2/{EP}/status/{jid}")
        if st.get("status")=="COMPLETED":
            o=st.get("output") or {}; mats=((o.get("recolour") or {}).get("materials")) or []
            return o.get("png_b64"),mats
        if st.get("status") not in ("IN_QUEUE","IN_PROGRESS"): return None,[]
        time.sleep(5)
    return None,[]
def bright(png_bytes,save):
    im=Image.open(__import__("io").BytesIO(base64.b64decode(png_bytes))).convert("RGB"); im.save(save)
    return ImageStat.Stat(im.convert("L")).mean[0]
SPEC=json.load(open(sys.argv[1])); TAG=sys.argv[2] if len(sys.argv)>2 else "wave"
A=f"{S}/ingest/{TAG}"; os.makedirs(A,exist_ok=True)
def one(sp):
    aid=sp["assetId"]; uid=sp["uid"]; raw=f"{A}/{aid}_raw.glb"; out=f"{A}/{aid}.glb"
    try:
        d=sapi(f"models/{uid}/download"); url=(d.get("glb") or {}).get("url") if d else None
        if not url: return (aid,None,0,[],"nodl",False)
        urllib.request.urlretrieve(url,raw)
        # 1) plated hardened path
        if not plated(raw,out,f"{A}/{aid}",sp.get("upright",False)): return (aid,None,0,[],"platefail",False)
        stg=f"car-meshes/staging/ing_{aid}.glb"; put(stg,open(out,"rb").read(),"model/gltf-binary")
        b64,mats=render(f"{OB}/public/{stg}")
        plateless_used=False
        if b64:
            br=bright(b64,f"{A}/{aid}.png")
        else: br=0
        # 2) fallback if dark/blob
        if br < DARK_GATE:
            outp=f"{A}/{aid}_pl.glb"
            if plateless(raw,outp,f"{A}/{aid}"):
                stg2=f"car-meshes/staging/ing_{aid}_pl.glb"; put(stg2,open(outp,"rb").read(),"model/gltf-binary")
                b2,m2=render(f"{OB}/public/{stg2}")
                if b2:
                    br2=bright(b2,f"{A}/{aid}.png")
                    if br2 > br + 6:   # fallback meaningfully brighter -> use it
                        shutil.copy(outp,out); br=br2; mats=m2; plateless_used=True
                try: os.remove(outp)
                except OSError: pass
        sz=os.path.getsize(out)
        status="ok" if br>=DARK_GATE else f"still-dark({br:.0f})"
        return (aid,f"{A}/{aid}.png" if os.path.exists(f"{A}/{aid}.png") else None,sz,mats,status,plateless_used)
    except Exception as e: return (aid,None,0,[],str(e)[:50],False)
    finally:
        try: os.remove(raw)
        except OSError: pass
res={}
with ThreadPoolExecutor(max_workers=3) as ex:
    for f in as_completed([ex.submit(one,sp) for sp in SPEC]):
        aid,p,sz,mats,why,pl=f.result(); res[aid]=(p,sz,mats,why,pl)
        print(f"{'OK ' if p and 'dark' not in why else 'XX '} {aid:26s} {sz//1024 if sz else 0}KB m{len(mats)} {'PLATELESS ' if pl else ''}{why}",flush=True)
json.dump({a:{"sz":res[a][1],"mats":res[a][2],"why":res[a][3],"plateless":res[a][4]} for a in res}, open(f"{A}/status.json","w"), indent=1)
try: font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",17)
except Exception: font=ImageFont.load_default()
ids=[sp["assetId"] for sp in SPEC]; cols=3; tw,th,lab=820,500,30; rows=(len(ids)+cols-1)//cols
sheet=Image.new("RGB",(cols*tw,rows*(th+lab)),(15,15,17)); dr=ImageDraw.Draw(sheet)
for k,aid in enumerate(ids):
    cc,ro=k%cols,k//cols; x,y=cc*tw,ro*(th+lab); p,sz,mats,why,pl=res.get(aid,(None,0,[],"?",False))
    col=(255,150,150) if ("dark" in why or not p) else ((255,220,120) if pl else (150,220,150))
    dr.text((x+5,y+5),f"{aid} {sz//1024 if sz else 0}KB {'PLATELESS ' if pl else ''}{why}",fill=col,font=font)
    if p and os.path.exists(p): sheet.paste(Image.open(p).convert("RGB"),(x,y+lab))
sheet.save(f"{A}/sheet.jpg","JPEG",quality=88)
print("INGEST_HARD_DONE",A)
