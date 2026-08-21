"""Direct assertion: does any cabin vertex sit ABOVE the windscreen surface?"""
import json,numpy as np,trimesh
from scipy.spatial import cKDTree
sc=trimesh.load("car_merged.glb",force="scene",process=False)
T,gn=sc.graph["Glass_Windscreen"]; g=sc.geometry[gn]
WS=trimesh.transform_points(g.vertices,T)
tree=cKDTree(WS[:,[0,2]])
rz=np.load("cabin_kit2.npz"); man=json.loads(bytes(rz["manifest"]).decode())
worst=[]
for p in man["parts"]:
    V=rz[f"{p['name']}__v"]
    d,i=tree.query(V[:,[0,2]],k=1)
    near=d<0.06                       # under the pane's footprint
    if not near.any(): continue
    over=V[near,1]-WS[i[near],1]
    worst.append((p["name"],float(over.max()),int((over>0).sum()),int(near.sum())))
worst.sort(key=lambda r:-r[1])
print("part                      max(y - windscreen_y)  verts_above  verts_under_pane")
for n,o,a,t in worst[:8]:
    print(f"  {n:24s} {o*1000:+8.1f} mm {a:8d} {t:10d}")
bad=[w for w in worst if w[1]>0]
print("VERDICT:", "PASS — nothing penetrates the windscreen" if not bad
      else f"FAIL — {len(bad)} parts penetrate: {[b[0] for b in bad]}")
