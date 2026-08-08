#!/usr/bin/env python3
"""Audit a folder of local GLBs: stage to Supabase, mat_audit + 4-view GPU render,
compose the same contact sheet the sourcing waves use. Resumable against the bucket."""
import base64, io, json, os, sys, time, urllib.request, urllib.error, hashlib
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw, ImageFont

EP="ng8oiz4p2l0xa0"; SUPA="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
STAGE="car-meshes/staging/inbox"; SHEETS="car-meshes/audit/inbox"
VIEWS=[("front34",35),("front34_L",325),("side",90),("rear34",215)]
RP=os.environ["RUNPOD_API_KEY"]; SB=os.environ["SB_KEY"]
H={"apikey":SB,"Authorization":"Bearer "+SB}
def log(*a): print(time.strftime("%H:%M:%S"),*a,flush=True)

def sb_put(path,data,ctype):
    rq=urllib.request.Request(f"{SUPA}/{path}",data=data,method="POST")
    for k,v in list(H.items())+[("Content-Type",ctype),("x-upsert","true")]: rq.add_header(k,v)
    for a in range(4):
        try: return urllib.request.urlopen(rq,timeout=900).read()
        except Exception as e:
            if a==3: raise
            time.sleep(5*(a+1))
            rq=urllib.request.Request(f"{SUPA}/{path}",data=data,method="POST")
            for k,v in list(H.items())+[("Content-Type",ctype),("x-upsert","true")]: rq.add_header(k,v)

def sb_has(path):
    try:
        rq=urllib.request.Request(f"{SUPA}/{path}",method="HEAD")
        for k,v in H.items(): rq.add_header(k,v)
        return urllib.request.urlopen(rq,timeout=60).status==200
    except Exception: return False

def rp_call(url,body=None,timeout=300):
    rq=urllib.request.Request(url,data=json.dumps(body).encode() if body else None,
        headers={"Authorization":"Bearer "+RP,"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(rq,timeout=timeout).read())

def job(payload,waits=150):
    for a in range(4):
        try:
            j=rp_call(f"https://api.runpod.ai/v2/{EP}/run",payload); break
        except Exception: time.sleep(10*(a+1))
    else: return None
    jid=j.get("id")
    if not jid: return None
    for _ in range(waits):
        time.sleep(4)
        try: st=rp_call(f"https://api.runpod.ai/v2/{EP}/status/{jid}",timeout=60)
        except Exception: continue
        s=st.get("status")
        if s=="COMPLETED": return st.get("output") or {}
        if s in ("FAILED","CANCELLED","TIMED_OUT"): return None
    return None

def main():
    root=sys.argv[1]
    files=sorted(p for p in
        (os.path.join(dp,f) for dp,_,fs in os.walk(root) for f in fs) if p.endswith(".glb"))
    log(f"{len(files)} GLBs")
    man=[]
    try: man=json.load(open("/tmp/inbox_manifest.json"))
    except Exception: pass
    done={m["uid"]:m for m in man}
    out=[]
    for i,path in enumerate(files,1):
        rel=os.path.relpath(path,root)
        marque=rel.split(os.sep)[-2] if os.sep in rel else "?"
        name=os.path.basename(path)[:-4]
        uid=hashlib.sha1(rel.encode()).hexdigest()[:16]
        rec=done.get(uid) or {"uid":uid,"marque":marque,"name":name,"file":rel,
                              "mb":round(os.path.getsize(path)/1e6,1)}
        if rec.get("sheet") and sb_has(f"{SHEETS}/{uid}.jpg"):
            out.append(rec); log(f"[{i}/{len(files)}] skip {name}"); continue
        blob=open(path,"rb").read()
        if not sb_has(f"{STAGE}/{uid}.glb"):
            sb_put(f"{STAGE}/{uid}.glb",blob,"model/gltf-binary")
        url=f"https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-meshes/staging/inbox/{uid}.glb"
        if "mats" not in rec:
            o=job({"input":{"mat_audit":True,"glb_url":url}})
            mats=(o or {}).get("materials") or []
            rec["mats"]=len([m for m in mats if m.get("body")])
            rec["cov"]=round(((o or {}).get("body_pct") or 0)/100.0,3)
            rec["faces"]=(o or {}).get("faces")
        ims=[]
        for vn,az in VIEWS:
            o=job({"input":{"glb_url":url,"recolour":"off","studio":True,"az":az,
                            "elev":0.10,"samples":64,"width":760,"height":470}})
            b=(o or {}).get("png_b64")
            if b: ims.append((Image.open(io.BytesIO(base64.b64decode(b))).convert("RGB"),vn))
        if not ims:
            rec["sheet"]=None; out.append(rec); log(f"[{i}/{len(files)}] NO VIEWS {name}"); continue
        w,h=ims[0][0].size; TW=860; TH=int(h*TW/w); PAD=28
        sheet=Image.new("RGB",(TW*2,(TH+PAD)*2+PAD),(14,14,16)); d=ImageDraw.Draw(sheet)
        try:
            FT=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",17)
            FS=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",13)
        except Exception: FT=FS=ImageFont.load_default()
        nm=rec.get("mats") or 0; cov=rec.get("cov") or 0
        adv=1<=nm<=2 and 0.05<=cov<=0.45
        d.text((10,5),f"{rec['marque'].upper()}  |  {name[:46]}  |  {rec['mb']}MB  |  "
                      f"body mats={nm} cov={cov}  |  {'recolourable' if adv else 'MATERIAL SPLIT SUSPECT'}",
               fill=(150,255,170) if adv else (255,170,170),font=FT)
        for j,(im,lab) in enumerate(ims):
            x=(j%2)*TW; y=PAD+(j//2)*(TH+PAD)
            sheet.paste(im.resize((TW,TH),Image.LANCZOS),(x,y))
            d.text((x+8,y+TH+4),lab,fill=(155,155,163),font=FS)
        buf=io.BytesIO(); sheet.save(buf,"JPEG",quality=91)
        sb_put(f"{SHEETS}/{uid}.jpg",buf.getvalue(),"image/jpeg")
        rec["sheet"]=f"{SHEETS}/{uid}.jpg"
        out.append(rec)
        json.dump(out,open("/tmp/inbox_manifest.json","w"),indent=1)
        log(f"[{i}/{len(files)}] SHEET {rec['marque']}/{name}  mats={nm} cov={cov}")
    json.dump(out,open("/tmp/inbox_manifest.json","w"),indent=1)
    sb_put(f"{SHEETS}/_manifest.json",json.dumps(out,indent=1).encode(),"application/json")
    log(f"DONE {len([r for r in out if r.get('sheet')])} sheets")

main()
