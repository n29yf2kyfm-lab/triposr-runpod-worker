"""Which cabin parts poke OUTSIDE the body? Measured per part, per view."""
import sys, json, numpy as np, trimesh, raster
CAR=sys.argv[1] if len(sys.argv)>1 else "car_cabin_v1.glb"
GLAZE={"Glass_Rear","Glass_Windscreen","Glass_Side_L","Glass_Side_R"}
sc=trimesh.load(CAR,force="scene",process=False)
opV,opF=[],[]; cabin={}; gl=[]
for node in sc.graph.nodes_geometry:
    T,gn=sc.graph[node]; g=sc.geometry[gn]
    v=trimesh.transform_points(g.vertices,T); f=np.asarray(g.faces)
    if node.startswith("Cabin_"): cabin[node]=(raster.gltf_to_blender(v),f)
    elif node in GLAZE: gl.append((v,f))
    else:
        opF.append(f+sum(len(x) for x in opV)); opV.append(v)
OV=raster.gltf_to_blender(np.vstack(opV)); OF=np.vstack(opF)
gV=[];gF=[]
for v,f in gl:
    gF.append(f+sum(len(x) for x in gV)); gV.append(v)
GV=raster.gltf_to_blender(np.vstack(gV)); GF=np.vstack(gF)
cams,_=raster.cams_from_cfg("rig_cfg.json")
tot={k:0 for k in cabin}
for view,cam in list(cams.items())[:3]:
    _,zo=raster.rasterise(cam,OV,OF)
    _,zg=raster.rasterise(cam,GV,GF)
    AP=np.isfinite(zg)                 # a glazing pane covers this pixel
    for n,(V,F) in cabin.items():
        idb,zc=raster.rasterise(cam,V,F)
        # POKING OUT = visible in front of the body where NO glazing pane
        # covers the pixel. Without the aperture exclusion this test flags every
        # part legitimately seen THROUGH a window, which is what it did first.
        poke=(idb>0)&(zc<zo-0.002)&(~AP)
        tot[n]+=int(poke.sum())
print("cabin part pixels visible IN FRONT of the opaque body (= poking out):")
bad=0
for n,c in sorted(tot.items(),key=lambda x:-x[1]):
    if c: print(f"   {n:24s} {c:7d} px"); bad+=c
print(f"TOTAL {bad} px over {len(cams)} views")
json.dump(tot,open("poke.json","w"),indent=1)
