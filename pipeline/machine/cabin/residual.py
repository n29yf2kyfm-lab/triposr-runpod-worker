"""How much body geometry still hangs in the glazed cabin AFTER the component
deletion, and is it attached to the main shell or not?"""
import os,sys,json,numpy as np,trimesh,raster
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
CAR=sys.argv[1]; CFG=sys.argv[2]
GLAZE=["Glass_Rear","Glass_Windscreen","Glass_Side_L","Glass_Side_R"]
sc=trimesh.load(CAR,force="scene",process=False)
def W(n):
    T,gn=sc.graph[n]; g=sc.geometry[gn]
    return trimesh.transform_points(g.vertices,T), np.asarray(g.faces)
BV,BF=W("Body_Shell")
q=np.round(BV/1e-5).astype(np.int64); _,inv=np.unique(q,axis=0,return_inverse=True)
Fw=inv[BF]; e=np.vstack([Fw[:,[0,1]],Fw[:,[1,2]],Fw[:,[2,0]]])
A=coo_matrix((np.ones(len(e)),(e[:,0],e[:,1])),shape=(int(inv.max())+1,)*2)
_,lab=connected_components(A,directed=False); flab=lab[Fw[:,0]]
MAIN=int(np.argmax(np.bincount(flab)))
gv,gf=[],[]
for n in GLAZE:
    v,f=W(n); gf.append(f+sum(len(x) for x in gv)); gv.append(v)
GV=raster.gltf_to_blender(np.vstack(gv)); GF=np.vstack(gf)
Vb=raster.gltf_to_blender(BV)
cams,_=raster.cams_from_cfg(CFG)
tot={"main":0,"nonmain":0,"glaze":0}
for view,cam in cams.items():
    _,zg=raster.rasterise(cam,GV,GF)
    _,zgf=raster.rasterise(cam,GV,GF,keep="far")
    idm,zm=raster.rasterise(cam,Vb,BF[flab==MAIN])
    ido,zo=raster.rasterise(cam,Vb,BF[flab!=MAIN])
    OPEN=np.isfinite(zg)&(zg<zm-0.005)
    inside=lambda z,h: h&OPEN&(z>zg+0.002)&(z<zgf-0.002)
    m=inside(zm,idm>0); o=inside(zo,ido>0)
    tot["main"]+=int(m.sum()); tot["nonmain"]+=int(o.sum()); tot["glaze"]+=int(OPEN.sum())
    print(f"  {view}: through-glass {int(OPEN.sum()):6d}  MAIN-attached in cabin {int(m.sum()):5d}"
          f"  detached in cabin {int(o.sum()):5d}")
print(f"\nTOTAL through-glass px {tot['glaze']}")
print(f"  body still hanging in the cabin, ATTACHED to the main shell : {tot['main']} "
      f"({100*tot['main']/tot['glaze']:.2f}% of through-glass px)")
print(f"  body still hanging in the cabin, DETACHED                   : {tot['nonmain']} "
      f"({100*tot['nonmain']/tot['glaze']:.2f}%)")
json.dump(tot,open(f"residual_{os.path.basename(CAR)}.json","w"),indent=1)
