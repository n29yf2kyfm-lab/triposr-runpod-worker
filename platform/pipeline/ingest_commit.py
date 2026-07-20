#!/usr/bin/env python3
"""Wave ingest — PHASE 2: promote the verified processed GLBs to live and write the
catalogue. For mode=resource, update the existing entry; for mode=new, create a full
schema-v2 entry. Renders hero + bakes 4 colour variants. Serve catalogue.
Usage: ingest_commit.py <spec.json> <tag> [comma-separated assetIds to include | ALL]"""
import sys, json, re, os, base64, subprocess, struct, urllib.request, io, time, copy
from PIL import Image
import config
HERE=os.path.dirname(os.path.abspath(__file__))
S=config.WORKDIR; os.makedirs(S, exist_ok=True)
REPO=os.environ.get("PIPELINE_REPO") or os.path.abspath(os.path.join(HERE, "..", ".."))
CAT=os.environ.get("PIPELINE_CATALOGUE") or f"{REPO}/platform/catalogue/catalogue.v2.json"
SBKEY=config.supabase_service_key()
RP=config.runpod_api_key(); EP=config.RUNPOD_ENDPOINT
OB=config.SUPABASE_OBJECT_URL; PUB=f"{OB}/public"
GT=["npx","--yes","@gltf-transform/cli@4"]
TAG=sys.argv[2] if len(sys.argv)>2 else "wave"; A=f"{S}/ingest/{TAG}"
SPEC=json.load(open(sys.argv[1]))
INCLUDE=None if (len(sys.argv)<4 or sys.argv[3]=="ALL") else set(sys.argv[3].split(","))
def s2l(c): return c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4
def hexlin(h): h=h.lstrip("#"); return [round(s2l(int(h[i:i+2],16)/255),4) for i in (0,2,4)]
COLOURS={"grey":hexlin("6f7276"),"silver":hexlin("b6b9be"),"black":hexlin("1b1d20"),"white":hexlin("e4e6e8")}
def rp(u,m="GET",b=None):
    d=json.dumps(b).encode() if b else None
    rq=urllib.request.Request(u,data=d,method=m); rq.add_header("Authorization","Bearer "+RP); rq.add_header("Content-Type","application/json")
    for a in range(6):
        try: return json.loads(urllib.request.urlopen(rq,timeout=150).read())
        except Exception:
            if a==5: return {}
            time.sleep(2*(a+1))
def put(p,d,ct):
    h={"apikey":SBKEY,"Authorization":f"Bearer {SBKEY}","Content-Type":ct,"x-upsert":"true","cache-control":"no-cache, max-age=0"}
    for a in range(3):
        try: return urllib.request.urlopen(urllib.request.Request(f"{OB}/{p}",data=d,method="POST",headers=h),timeout=300).status
        except Exception:
            if a==2: raise
            time.sleep(3)
def gltf_mats(path):
    d=open(path,"rb").read(); jl=struct.unpack("<I",d[12:16])[0]
    return [m.get("name") for m in json.loads(d[20:20+jl]).get("materials",[])]
cat=json.load(open(CAT)); by={e["assetId"]:e for e in cat}
TEMPLATE=copy.deepcopy([e for e in cat if e.get("publicationStatus")=="approved" and e.get("colourVariants")][0])
def new_entry(sp):
    e=copy.deepcopy(TEMPLATE); aid=sp["assetId"]; mk=sp["make"]
    gpath=f"car-meshes/finished/{mk}/{aid}.glb"
    for k in list(e.keys()):
        pass
    e.update({"assetId":aid,"make":mk,"model":sp["model"],"modelFamily":sp["model"],"modelAliases":sp.get("aliases",[]),
        "generation":None,"generationAliases":[],"generationConfirmed":False,"yearStart":None,"yearEnd":None,
        "bodyStyle":sp["bodyStyle"],"exactDerivative":None,"exactTrim":False,"provenance":"sourced",
        "sourceTitle":sp["sourceTitle"],"sourceUrl":f"https://sketchfab.com/3d-models/{sp['uid']}","sourceCreator":None,
        "licence":"CC-BY (attribution required)","generatedFromReference":False,"referenceImageCount":0,
        "accuracyGrade":"representative","qualityGrade":sp["grade"],"technicalStatus":"passed","visualStatus":"passed",
        "publicationStatus":"approved","quarantineReason":None,"hasInterior":False,"interiorMode":"none",
        "paintMaterialNames":[],"glassMaterialNames":[],"defaultColourFamily":"grey","renderColourLabel":"Studio Grey",
        "oemPaintVerified":False,"oemPaintCode":None,"oemPaintName":None,"colourVariants":{},
        "desktopGlbUrl":f"{PUB}/{gpath}","mobileGlbUrl":f"{PUB}/{gpath}","fallbackGlbUrl":None,
        "posterUrl":f"{PUB}/car-renders/finished/{mk}/{aid}/hero.jpg","turntableUrl":None,"interiorUrl":None,
        "triangleCount":None,"vertexCount":None,"pipelineVersion":"ingest-hardened-2026-07-20","publishedAt":None,
        "replacedAssetId":None,"needsHumanReview":[],"notes":[],"platesBaked":True})
    return e
done=[]
for sp in SPEC:
    aid=sp["assetId"]
    if INCLUDE is not None and aid not in INCLUDE: continue
    out=f"{A}/{aid}.glb"
    if not os.path.exists(out): print("MISSING",aid); continue
    if sp["mode"]=="new" and aid not in by:
        e=new_entry(sp); cat.append(e); by[aid]=e
    else:
        e=by[aid]
    gpath=e["desktopGlbUrl"].split("/object/public/")[1]; baseurl=e["desktopGlbUrl"]; sz=os.path.getsize(out)
    put(gpath,open(out,"rb").read(),"model/gltf-binary")
    # hero
    jid=rp(f"https://api.runpod.ai/v2/{EP}/run","POST",{"input":{"glb_url":baseurl+f"?cb={int(time.time())}","recolour":"off","studio":True,"az":40,"elev":0.13,"samples":110,"width":1200,"height":700}}).get("id")
    if jid:
        for _ in range(70):
            st=rp(f"https://api.runpod.ai/v2/{EP}/status/{jid}")
            if st.get("status")=="COMPLETED":
                o=st.get("output") or {}
                if o.get("png_b64"):
                    buf=io.BytesIO(); Image.open(io.BytesIO(base64.b64decode(o["png_b64"]))).convert("RGB").save(buf,"JPEG",quality=88)
                    put(e["posterUrl"].split("/object/public/")[1],buf.getvalue(),"image/jpeg")
                break
            if st.get("status") not in ("IN_QUEUE","IN_PROGRESS"): break
            time.sleep(5)
    # variants
    names=set(gltf_mats(out))
    jid=rp(f"https://api.runpod.ai/v2/{EP}/run","POST",{"input":{"glb_url":baseurl+f"?cb={int(time.time())}","colour":"grey","recolour":"auto","studio":True,"az":40,"samples":20,"width":400,"height":260}}).get("id")
    mats=[]
    if jid:
        for _ in range(50):
            st=rp(f"https://api.runpod.ai/v2/{EP}/status/{jid}")
            if st.get("status")=="COMPLETED": mats=((st.get("output") or {}).get("recolour") or {}).get("materials") or []; break
            if st.get("status") not in ("IN_QUEUE","IN_PROGRESS"): break
            time.sleep(4)
    mats=[m for m in mats if m in names]; variants={}
    bakesrc=f"{A}/{aid}_bake.glb"; subprocess.run(GT+["copy",out,bakesrc],capture_output=True,text=True,timeout=400)
    if mats and os.path.exists(bakesrc):
        for cname,rgb in COLOURS.items():
            op=f"{A}/{aid}__{cname}.glb"; oc=f"{A}/{aid}__{cname}_c.glb"; fc=f"{A}/{aid}__{cname}_d.glb"
            subprocess.run(["blender","-b","-P",f"{HERE}/bake_colour.py","--",bakesrc,op,f"{rgb[0]},{rgb[1]},{rgb[2]}",",".join(mats)],capture_output=True,text=True,timeout=300)
            if not os.path.exists(op) or os.path.getsize(op)<20000: continue
            subprocess.run(GT+["webp",op,oc,"--quality","82"],capture_output=True,text=True,timeout=300)
            step=oc if os.path.exists(oc) and os.path.getsize(oc)>20000 else op
            subprocess.run(GT+["draco",step,fc],capture_output=True,text=True,timeout=300)
            vf=fc if os.path.exists(fc) and os.path.getsize(fc)>20000 else step
            vpath=gpath.replace(".glb",f"__{cname}.glb")
            if put(vpath,open(vf,"rb").read(),"model/gltf-binary") in (200,201): variants[cname]=f"{PUB}/{vpath}"
            for f in (op,oc,fc):
                try: os.remove(f)
                except OSError: pass
    try: os.remove(bakesrc)
    except OSError: pass
    e["colourVariants"]=variants; e["publicationStatus"]="approved"; e["qualityGrade"]=sp["grade"]
    e["technicalStatus"]="passed"; e["visualStatus"]="passed"; e["needsHumanReview"]=[]; e["quarantineReason"]=None
    e["fileSizeBytes"]=sz; e["mobileFileSizeBytes"]=sz; e["sourceUrl"]=f"https://sketchfab.com/3d-models/{sp['uid']}"
    e["bodyStyle"]=sp["bodyStyle"]
    tag_new="NEW" if sp["mode"]=="new" else "RE-SOURCED"
    e.setdefault("notes",[]).append(f"2026-07-20 {tag_new} from CSV library-fill: CC-BY model {sp['uid']} ({sp['sourceTitle']}), hardened material-preserving pipeline{' + auto-upright' if sp.get('upright') else ''}, render-verified clear glass + wheels + orientation. Hero + variants {list(variants)}. grade {sp['grade']}.")
    done.append((aid,sp["mode"],sp["grade"],list(variants),sz))
    print(f"COMMIT {aid} {sp['mode']} grade={sp['grade']} variants={list(variants)} {sz//1024}KB",flush=True)
json.dump(cat,open(CAT,"w"),indent=1,ensure_ascii=False)
put("car-renders/resolver/catalogue.v2.json",json.dumps(cat,ensure_ascii=False).encode(),"application/json")
print("INGEST_COMMIT_DONE committed",len(done),"approved=",sum(1 for e in cat if e.get("publicationStatus")=="approved"))
