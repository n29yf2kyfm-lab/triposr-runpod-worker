"""Turn 'the glazing looks torn' into numbers: per-pane holes and fragments.
Welds by coordinate first — a GLB stores split vertices, so a naive component
count reads a single sheet as thousands of pieces (recorded trap)."""
import bpy, bmesh, sys, json
a=sys.argv[sys.argv.index("--")+1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=a[0])
out={}
for o in bpy.context.scene.objects:
    if o.type!="MESH" or "glass" not in o.name.lower(): continue
    bm=bmesh.new(); bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bnd=[e for e in bm.edges if len(e.link_faces)==1]
    # connected components over faces
    seen=set(); comps=0
    for f in bm.faces:
        if f.index in seen: continue
        comps+=1; stack=[f]; seen.add(f.index)
        while stack:
            c=stack.pop()
            for e in c.edges:
                for nf in e.link_faces:
                    if nf.index not in seen:
                        seen.add(nf.index); stack.append(nf)
    # boundary LOOPS: 1 loop per component = a clean pane with no holes
    ein={e for e in bnd}; loops=0
    while ein:
        e0=ein.pop(); loops+=1; st=[e0]
        while st:
            e=st.pop()
            for v in e.verts:
                for ne in v.link_edges:
                    if ne in ein: ein.discard(ne); st.append(ne)
    out[o.name]={"faces":len(bm.faces),"components":comps,
                 "boundary_edges":len(bnd),"boundary_loops":loops,
                 "holes_beyond_outline":max(0,loops-comps)}
    bm.free()
print("GLASSTOPO="+json.dumps(out))
