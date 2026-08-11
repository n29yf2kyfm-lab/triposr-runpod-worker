"""Corrected flat-shell test.

glass_probe.flat is defeated by the PIPELINE'S OWN injected materials.
`wheel_rim` (0.56,0.57,0.6), `plate_front` and `plate_rear` (textured) are added
downstream by this project's own tooling -- they appear verbatim on cars from
completely different uploaders (Hyundai Ioniq 6, Kia Rio, LR Discovery, Honda
Insight, Mazda 2, Mini hatch). `wheel_rim` alone puts a SECOND entry in
flat_vals, so `len(flat_vals)==1` is False and the gate never fires, on every
car the pipeline touched. Confirmed by magenta-backlight render: ioniq-6,
kia-rio, eclipse-cross and lr-discovery render as pure white clay with opaque
white glazing and white tyres, and every one scored flat_shell=False.
"""
import json, sys, re, concurrent.futures as cf
sys.path.insert(0,'/home/user/triposr-runpod-worker/pipeline/ingest')
import glass_probe as gp
INJECTED = {"wheel_rim","plate_front","plate_rear"}

def flat2(g):
    mats=g.get("materials") or []
    vals=set(); untex=0; nonop=False; bgtex=False
    for m in mats:
        nm=m.get("name") or ""
        if nm in INJECTED: continue
        pbr=m.get("pbrMetallicRoughness") or {}
        sg=(m.get("extensions") or {}).get("KHR_materials_pbrSpecularGlossiness") or {}
        bcf=pbr.get("baseColorFactor") or sg.get("diffuseFactor") or [1,1,1,1]
        tex=bool(pbr.get("baseColorTexture") or sg.get("diffuseTexture"))
        if m.get("alphaMode","OPAQUE")!="OPAQUE": nonop=True
        if tex and (gp.BODYISH.search(nm) or gp.GLASSY.search(nm)): bgtex=True
        if not tex:
            untex+=1; vals.add(tuple(round(x,4) for x in bcf[:3]))
    return dict(flat=bool(untex>=3 and len(vals)==1 and min(list(vals)[0])>=0.4
                          and not bgtex and not nonop),
                n_untex=untex, n_vals=len(vals),
                vals=sorted(vals)[:3])

if __name__=="__main__":
    c=json.load(open('/home/user/triposr-runpod-worker/platform/catalogue/catalogue.v2.json'))
    mine=[x for x in c if x.get('publicationStatus')=='approved' and x['make'][:1].lower() in 'ghijklmn']
    def one(e):
        try: r=flat2(gp.gltf_json(e['desktopGlbUrl']))
        except Exception as ex: r={'flat':None,'err':str(ex)[:50]}
        r['assetId']=e['assetId']; return r
    with cf.ThreadPoolExecutor(10) as ex: out=list(ex.map(one,mine))
    json.dump(out,open('FLAT2.json','w'),indent=1)
    hit=[r for r in out if r.get('flat')]
    print('flat shells:',len(hit),'of',len(out))
    for r in hit: print('  ',r['assetId'], r['vals'], 'untex',r['n_untex'])
