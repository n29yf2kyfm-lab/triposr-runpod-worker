"""Through-glass cabin measure, done GEOMETRICALLY rather than from pixels.

For each glazing node, cast rays along its own mean outward normal, keep the rays
that actually hit that glazing first, then report the FIRST NON-GLAZING surface
behind it. That is exactly "what does the glazing show", with no renderer, no
transparency dither and no AA in the way.
"""
import glbcore as G, measure as M, raycast as RC, numpy as np, json, sys

def run(path):
    g=G.Glb(path)
    V,F,own,names=RC.gather(g)
    glass=[n for n in names if n.startswith('Glass')]
    out={}
    for gn in glass:
        st=M.node_normal_stats(g,gn)
        d=-np.array(st['mean_normal']); d/=np.linalg.norm(d)   # ray goes INTO the car
        Vn,Fn=M.node_world_tris(g,gn); u=np.unique(Fn); P=Vn[u]
        c=P.mean(0)
        a=np.array([0.,1.,0.])
        uu=np.cross(d,a); uu/=np.linalg.norm(uu); vv=np.cross(d,uu)
        r=float(np.linalg.norm(P.max(0)-P.min(0))/2)*0.80
        O,_=RC.grid_origins(c,uu,vv,r,r,44,44,d,back=3.0)
        b=RC.Binned(V,F,own,d,ncell=160)
        hits=b.hits(O)
        gi=names.index(gn)
        behind={}; n_on=0
        for t,o in hits:
            if not len(t) or o[0]!=gi: continue
            n_on+=1
            for oo in o[1:]:
                nm=names[oo]
                if nm.startswith('Glass'): continue
                behind[nm]=behind.get(nm,0)+1
                break
        tot=max(n_on,1)
        out[gn]=dict(rays=len(O), rays_first_hit_this_glass=n_on,
                     behind_pct={k:round(100.0*v/tot,2) for k,v in sorted(behind.items(),key=lambda x:-x[1])[:8]})
    return out

res={}
for p in sys.argv[1:]:
    res[p]=run(p)
    print(p, json.dumps(res[p],indent=1))
json.dump(res,open('meta/throughglass.json','w'),indent=1)
open('meta/THROUGHGLASS_DONE','w').write('ok')
print("THROUGHGLASS_EXIT=0")
