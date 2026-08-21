#!/usr/bin/env python3
"""body_surf.py — measured inner surfaces of the body, for fitting cabin parts.

Saves body_surf.npz:
  ZIN_R / ZIN_L : |z| of the flank inner surface on a (x,y) grid, robust p20 of
                  the local sample so a single stray return cannot drag it in
  YTOP          : roof underside on an (x,z) grid, robust p80
Both are gap-filled by nearest-value and lightly smoothed. Built from the MAIN
component of Body_Shell only, so fragments cannot define the surface.
"""
import os, numpy as np, trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.ndimage import uniform_filter, distance_transform_edt

CAR=os.environ.get("CABIN_CAR","car_merged.glb")
OUTF=os.environ.get("CABIN_SURF","body_surf.npz")
print("CAR:",CAR)
sc=trimesh.load(CAR,force="scene",process=False)
def W(n):
    T,gn=sc.graph[n]; g=sc.geometry[gn]
    return trimesh.transform_points(g.vertices,T), np.asarray(g.faces)
BV,BF=W("Body_Shell")
q=np.round(BV/1e-5).astype(np.int64); _,inv=np.unique(q,axis=0,return_inverse=True)
Fw=inv[BF]; e=np.vstack([Fw[:,[0,1]],Fw[:,[1,2]],Fw[:,[2,0]]])
A=coo_matrix((np.ones(len(e)),(e[:,0],e[:,1])),shape=(int(inv.max())+1,)*2)
_,lab=connected_components(A,directed=False); flab=lab[Fw[:,0]]
MAIN=int(np.argmax(np.bincount(flab))); P=BV[np.unique(BF[flab==MAIN])]
print("main-component verts:",len(P))

X0,X1,NX=-1.30,1.95,66      # 50 mm cells
Y0,Y1,NY=0.20,1.50,27
Z0,Z1,NZ=-0.95,0.95,39
xe=np.linspace(X0,X1,NX+1); ye=np.linspace(Y0,Y1,NY+1); ze=np.linspace(Z0,Z1,NZ+1)

def grid(pts, ax, ay, val, pct, shape):
    gi=np.clip(np.digitize(pts[:,ax[0]],ax[1])-1,0,shape[0]-1)
    gj=np.clip(np.digitize(pts[:,ay[0]],ay[1])-1,0,shape[1]-1)
    out=np.full(shape,np.nan)
    key=gi*shape[1]+gj
    order=np.argsort(key); key=key[order]; v=val[order]
    idx=np.flatnonzero(np.r_[True,key[1:]!=key[:-1]])
    for s,en in zip(idx,np.r_[idx[1:],len(key)]):
        out.flat[key[s]]=np.percentile(v[s:en],pct)
    return out

def fill_smooth(a, it=2):
    m=np.isnan(a)
    if m.any():
        _,ind=distance_transform_edt(m,return_indices=True)
        a=a[tuple(ind)]
    for _ in range(it): a=uniform_filter(a,size=3,mode="nearest")
    return a

res={}
for s,tag in ((-1,"ZIN_R"),(1,"ZIN_L")):
    m=(np.sign(P[:,2])==s)&(np.abs(P[:,2])>=0.30)
    pts=P[m]
    gg=grid(pts,(0,xe),(1,ye),np.abs(pts[:,2]),20,(NX,NY))
    res[tag]=fill_smooth(gg)
    print(f"{tag}: filled {np.isnan(gg).sum()}/{gg.size} empty cells, "
          f"range {np.nanmin(res[tag]):.3f}..{np.nanmax(res[tag]):.3f}")
# YWS: the UNDERSIDE of the WINDSCREEN pane on an (x,z) grid. Only the
# windscreen pane, deliberately: using all glazing would put the side glass's
# beltline over the seats and sink them. Cabin parts must pass under this.
ws,_=W("Glass_Windscreen")
gg=grid(ws,(0,xe),(2,ze),ws[:,1],5,(NX,NZ))
cov=~np.isnan(gg)
# a thin pane on a 50 mm grid leaves HOLES in its own coverage mask (measured:
# 103 of ~230 cells inside the pane's footprint), which let the steering wheel
# slip through the clamp. Dilate the mask by 2 cells before using it.
from scipy.ndimage import maximum_filter
covd=maximum_filter(cov.astype(float),size=5)>0.5
res["YWS"]=fill_smooth(gg,it=1); res["YWS_COV"]=covd.astype(float)
print(f"YWS: {cov.sum()} raw -> {covd.sum()} dilated cells of {cov.size}, "
      f"range {np.nanmin(gg):.3f}..{np.nanmax(gg):.3f}")

m=P[:,1]>1.05
pts=P[m]
gg=grid(pts,(0,xe),(2,ze),pts[:,1],80,(NX,NZ))
res["YTOP"]=fill_smooth(gg)
print(f"YTOP: filled {np.isnan(gg).sum()}/{gg.size}, range {res['YTOP'].min():.3f}..{res['YTOP'].max():.3f}")
# ---- the cabin FRAME, measured on THIS car (never hardcoded)
GL=[W(n)[0] for n in ("Glass_Side_L","Glass_Side_R")]
BELT=float(min(g[:,1].min() for g in GL))
WS=W("Glass_Windscreen")[0]
i=int(np.argmin(WS[:,0]))
# windscreen base = the forward-lower edge: lowest y among the most forward 3%
fw=WS[WS[:,0]<=np.percentile(WS[:,0],3)]
WSB=[float(fw[:,0].mean()), float(np.percentile(fw[:,1],20))]
rim={c:W(f"Wheel_{c}_Rim")[0] for c in ("FL","FR","RL","RR")}
FAX=float((rim["FL"][:,0].mean()+rim["FR"][:,0].mean())/2)
RAX=float((rim["RL"][:,0].mean()+rim["RR"][:,0].mean())/2)
cab=(P[:,0]>-1.0)&(P[:,0]<1.3)&(np.abs(P[:,2])<0.45)
FLOOR=float(np.percentile(P[cab,1],10))
# HALFW / ROOFY tables, measured
HALFW=[]
for y0 in np.arange(0.30,1.45,0.10)+ (FLOOR-0.30):
    m=(P[:,0]>BELT-2.1)&(P[:,0]<RAX+0.1)&(P[:,1]>=y0)&(P[:,1]<y0+0.10)
    if m.sum()>200: HALFW.append([float(y0+0.05), float(np.percentile(np.abs(P[m,2]),60))])
ROOFY=[]
for x0 in np.arange(-1.2,1.7,0.30):
    m=(P[:,0]>=x0)&(P[:,0]<x0+0.30)&(np.abs(P[:,2])<0.40)
    if m.sum()>200: ROOFY.append([float(x0+0.15), float(P[m,1].max())])
# BELT as a FUNCTION of x: this car's beltline is styled with a ~4.8 deg rise to
# the rear, so a single global minimum under-reads it everywhere but the nose.
BELTX=[]
GLall=np.vstack(GL)
for x0 in np.arange(-1.25,1.35,0.20):
    m=(GLall[:,0]>=x0)&(GLall[:,0]<x0+0.20)
    if m.sum()>40: BELTX.append([float(x0+0.10), float(np.percentile(GLall[m,1],2))])
frame=dict(BELT=BELT,BELTX=BELTX,WSB=WSB,FAX=FAX,RAX=RAX,FLOOR=FLOOR,HALFW=HALFW,ROOFY=ROOFY)
print("BELTX:",[(round(a,2),round(b,3)) for a,b in BELTX])
print("FRAME:",{k:(round(v,4) if isinstance(v,float) else v) for k,v in frame.items() if k not in("HALFW","ROOFY")})
print("HALFW:",[(round(a,2),round(b,3)) for a,b in HALFW])
print("ROOFY:",[(round(a,2),round(b,3)) for a,b in ROOFY])
import json
np.savez(OUTF, xe=xe, ye=ye, ze=ze, frame=np.frombuffer(json.dumps(frame).encode(),dtype=np.uint8), **res)
print("wrote",OUTF)
