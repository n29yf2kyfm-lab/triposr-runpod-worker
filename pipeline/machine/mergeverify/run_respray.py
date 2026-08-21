import respray as R, glbcore as G, json, sys, os
glb=sys.argv[1]; tag=sys.argv[2]
mats=G.Glb(glb).material_names()
views=[dict(name='f34',az=215,el=12),dict(name='side',az=270,el=6),dict(name='rear34',az=35,el=12)]
r=R.run(glb,tag,views,mats,res=800,samples=80)
json.dump(r,open(f'meta/respray_{tag}.json','w'),indent=1)
open(f'meta/RESPRAY_{tag}_DONE','w').write('ok')
print("RESPRAY_EXIT=0",tag)
