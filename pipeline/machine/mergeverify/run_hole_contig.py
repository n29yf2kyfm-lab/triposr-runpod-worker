"""Contiguous-hole control. A merge's realistic failure is a DROPPED PANEL REGION,
not 8% of triangles scattered at random -- and the two have very different
detectability at a given ray density. Both are measured so the sensitivity of the
hole test is a stated number rather than an assumption."""
import glbcore as G, measure as M, glbedit as E, holes as H, numpy as np, json
g=G.Glb('src/car_merged.glb')
V,F=M.node_world_tris(g,'Body_Shell')
c=G.tri_centroids(V,F)
# a 150 mm disc on the roof, centred on the cabin
roof=c[(c[:,1]>np.percentile(c[:,1],97))]
ctr=roof.mean(0)
d=np.linalg.norm(c-ctr,axis=1)
keep=d>0.150
print(f"contiguous hole: deleting {int((~keep).sum())} of {len(F)} Body_Shell faces "
      f"({100*(~keep).mean():.2f}%) within 150 mm of {ctr.round(3)}")
ed=E.Editor('src/car_merged.glb')
ni=ed.node_index('Body_Shell'); mi=ed.js['nodes'][ni]['mesh']
Fo=g.prim_indices(mi,0)
ed.set_indices(mi,0,Fo[keep])
ed.write('nc/NC9_contig_hole.glb')
r=H.hole_test(G.Glb('src/car_merged.glb'), G.Glb('nc/NC9_contig_hole.glb'), n=32)
print("CONTIGUOUS-HOLE CONTROL:",json.dumps(r['total']))
json.dump(dict(deleted_faces=int((~keep).sum()),total_faces=len(F),result=r),
          open('meta/hole_contig.json','w'),indent=1)
open('meta/HOLE_CONTIG_DONE','w').write('ok')
print("HOLE_CONTIG_EXIT=0")
