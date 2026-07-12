"""Generate a generic procedural undercarriage (floor pan, engine/gearbox,
driveshaft, exhaust+muffler, fuel tank, subframes, axles) fitted to a car GLB's
bounding box, and merge it in. glTF is Y-up; length = larger of X/Z footprint."""
import sys,numpy as np,trimesh
def build(glb_in, glb_out, audit_flip=False):
    scene=trimesh.load(glb_in)
    if not hasattr(scene,"geometry") or not scene.geometry:
        print("no geometry");return False
    b=scene.bounds  # [[minx,miny,minz],[maxx,maxy,maxz]]
    size=b[1]-b[0]; ctr=(b[0]+b[1])/2
    # Y up
    W,H,L = size[0],size[1],size[2]
    # ensure length is Z; if X>Z, swap axes роль by using max
    length_axis = 2 if size[2]>=size[0] else 0
    width_axis = 0 if length_axis==2 else 2
    Ln=size[length_axis]; Wd=size[width_axis]
    gy=b[0][1]                      # ground (min Y)
    cx=ctr[0]; cz=ctr[2]
    y0=gy+H*0.06                    # underbody plane a bit above ground
    parts=[]
    def add(mesh, colour=(40,42,46)):
        parts.append(mesh)
    def box(sx,sy,sz,x,y,z,colour=(40,42,46)):
        m=trimesh.creation.box(extents=[sx,sy,sz]); m.apply_translation([x,y,z]); add(m,colour)
    def tube(r,h,x,y,z,axis="z",colour=(70,72,78)):
        m=trimesh.creation.cylinder(radius=r,height=h,sections=16)
        if axis=="z": pass
        elif axis=="x": m.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2,[0,1,0]))
        m.apply_translation([x,y,z]); add(m,colour)
    # coordinate helpers along length(Z) and width(X)
    def L_(f): return cz + (f-0.5)*Ln     # f in 0..1 along length
    def X_(f): return cx + (f-0.5)*Wd     # f in 0..1 along width
    # floor pan (dark tray) — kept tight within the footprint
    box(Wd*0.66,0.03,Ln*0.70, cx,y0,cz,(28,29,32))
    # engine/gearbox block (front third)
    box(Wd*0.34,H*0.14,Ln*0.16, cx,y0+H*0.05,L_(0.22),(52,54,60))
    box(Wd*0.22,H*0.10,Ln*0.10, cx,y0+H*0.02,L_(0.34),(46,48,54))  # gearbox
    # driveshaft down centreline
    tube(0.028,Ln*0.5, cx,y0+0.01,cz,"z",(90,92,98))
    # rear axle / diff
    tube(0.05,Wd*0.7, cx,y0+0.02,L_(0.80),"x",(70,72,78))
    box(Wd*0.14,H*0.09,Ln*0.07, cx,y0+0.02,L_(0.80),(52,54,60))
    # front subframe + control arms
    tube(0.04,Wd*0.7, cx,y0,L_(0.15),"x",(60,62,68))
    box(Wd*0.5,0.04,Ln*0.06, cx,y0,L_(0.15),(48,50,56))
    # fuel tank (rear-mid, offset)
    box(Wd*0.42,H*0.09,Ln*0.14, cx,y0+0.02,L_(0.62),(34,35,40))
    # exhaust: pipe from engine to rear + muffler + tailpipe (offset to one side)
    exo=X_(0.33)
    tube(0.03,Ln*0.60, exo,y0-0.01,cz+Ln*0.02,"z",(120,122,128))
    tube(0.075,Ln*0.14, exo,y0-0.01,L_(0.84),"z",(110,112,120))   # muffler
    tube(0.028,Ln*0.08, exo,y0+0.0,L_(0.97),"z",(140,142,150))    # tailpipe
    # heat shields / sills
    box(0.03,H*0.10,Ln*0.6, X_(0.06),y0+H*0.04,cz,(30,31,35))
    box(0.03,H*0.10,Ln*0.6, X_(0.94),y0+H*0.04,cz,(30,31,35))
    under=trimesh.util.concatenate(parts)
    # single dark metal PBR material named so the render recolour never touches it
    mat=trimesh.visual.material.PBRMaterial(name="undercarriage_metal",
        baseColorFactor=[0.06,0.06,0.07,1.0], metallicFactor=0.55, roughnessFactor=0.6)
    under.visual=trimesh.visual.TextureVisuals(material=mat)
    scene.add_geometry(under, node_name="undercarriage")
    if audit_flip:
        scene.apply_transform(trimesh.transformations.rotation_matrix(np.pi,[0,0,1]))  # flip to show underside up
    scene.export(glb_out)
    return True
if __name__=="__main__":
    a=sys.argv
    build(a[1],a[2], audit_flip=(len(a)>3 and a[3]=="flip"))
    print("done",a[2])
