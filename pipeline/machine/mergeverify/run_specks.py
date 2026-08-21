"""Roof / bonnet dark-speck fraction, with the clay floor measured in the same run.

Definition: of the pixels the material-ID pass says are PAINT, in the roof or bonnet
zone of a top-down orthographic view, the fraction whose luminance is below 45% of
that zone's own 75th-percentile paint level. The CLAY FLOOR is the identical count on
a render where EVERY material is the paint colour -- shading alone, no material
contrast -- and it is the only thing that makes a speck percentage interpretable.
"""
import respray as R, glbcore as G, measure as M, numpy as np, json
from PIL import Image

def zones(glb):
    g=G.Glb(glb); V=M.node_world_verts(g,'Body_Shell')
    xmin,xmax=V[:,0].min(),V[:,0].max()
    return xmin,xmax

out={}
views=[dict(name='top',az=0,el=90)]
for glb,tag in [('src/car_merged.glb','sp_before'),('src/car_deskin.glb','sp_after')]:
    mats=G.Glb(glb).material_names()
    R.dark_specks(glb,tag,views,mats,res=1000,samples=90)
    pal=R.matid_palette(mats)
    mid=np.asarray(Image.open(f'rend/{tag}/sk_matid_top.png').convert('RGB')).astype(float)/255.
    S=np.asarray(Image.open(f'rend/{tag}/sk_shade_top.png').convert('RGB')).astype(float).mean(2)
    C=np.asarray(Image.open(f'rend/{tag}/sk_clay_top.png').convert('RGB')).astype(float).mean(2)
    paint=np.abs(mid-R._srgb(pal['carpaint'])[None,None,:]).max(2)<0.04
    anyc=mid.max(2)>0.02
    H,W=paint.shape
    ys,xs=np.nonzero(anyc)
    # nose at -X. In this top view work out the length axis from the car's own mask.
    span=xs.max()-xs.min(); lo=xs.min()
    rows={}
    for name,(a,b) in dict(bonnet=(0.05,0.32), roof=(0.42,0.72)).items():
        band=np.zeros_like(paint); band[:, int(lo+a*span):int(lo+b*span)]=True
        pm=paint&band; am=anyc&band
        if pm.sum()<200: rows[name]=dict(px=int(pm.sum()),note='too few'); continue
        ref=np.percentile(S[pm],75); cref=np.percentile(C[am],75)
        rows[name]=dict(painted_px=int(pm.sum()),ref=float(ref),
            dark_pct=float(100*(S[pm]<0.45*ref).mean()),
            clay_floor_pct=float(100*(C[am]<0.45*cref).mean()))
    out[tag]=rows
    print(tag,json.dumps(rows,indent=1))
json.dump(out,open('meta/specks.json','w'),indent=1)
open('meta/SPECKS_DONE','w').write('ok')
print("SPECKS_EXIT=0")
