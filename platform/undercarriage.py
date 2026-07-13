"""Generate a generic procedural undercarriage (floor pan, engine/gearbox,
driveshaft, exhaust+muffler, fuel tank, subframes, axles) fitted to a car GLB's
bounding box, and merge it in. glTF is Y-up; length = larger of X/Z footprint.

v2: ALL dimensions scale-relative (works on mm- or m-scale models), and the
running gear (exhaust line, muffler, tailpipe, driveshaft, axles) hangs
VISIBLY below the floor pan so orbiting under the car shows real mechanicals,
not a flat tray. Two-tone materials: dark pan + lighter steel components."""
import sys,numpy as np,trimesh

def normalise_pose(scene):
    """Fix models stored in the wrong rest pose: standing on the nose (length
    along Y) or upside-down (roof toward the ground). Cars must lie flat,
    wheels down, grounded at min-Y."""
    R=trimesh.transformations.rotation_matrix
    b=scene.bounds; size=b[1]-b[0]
    # 1) standing up: Y is the longest dimension -> lay flat about X
    if size[1]>=size[0] and size[1]>=size[2]:
        scene.apply_transform(R(-np.pi/2,[1,0,0]))
        b=scene.bounds; size=b[1]-b[0]
    # 2) upside-down: cars are wider near the ground (wheels/sills) than the
    # roof. Compare footprint width in the bottom vs top height-quartile.
    try:
        whole=scene.dump(concatenate=True); v=whole.vertices
        la=2 if size[2]>=size[0] else 0
        wa=0 if la==2 else 2
        y0,y1=b[0][1],b[1][1];H=y1-y0
        bot=v[v[:,1]<y0+H*0.25]; top=v[v[:,1]>y1-H*0.25]
        if len(bot)>100 and len(top)>100:
            # a car is LONGEST near the ground (bumper to bumper) and short at
            # the roof; if the top band is longer, the model is upside-down
            lb=bot[:,la].max()-bot[:,la].min()
            lt=top[:,la].max()-top[:,la].min()
            if lt>lb*1.15:
                axis=[0,0,1] if la==2 else [1,0,0]   # 180° about the length axis
                scene.apply_transform(R(np.pi,axis))
    except Exception:
        pass
    return scene

def build(glb_in, glb_out, audit_flip=False):
    scene=trimesh.load(glb_in)
    if not hasattr(scene,"geometry") or not scene.geometry:
        print("no geometry");return False
    scene=normalise_pose(scene)
    b=scene.bounds
    size=b[1]-b[0]; ctr=(b[0]+b[1])/2
    W,H,L = size[0],size[1],size[2]
    length_axis = 2 if size[2]>=size[0] else 0
    Ln=size[length_axis]; Wd=size[0] if length_axis==2 else size[2]
    S=Ln/4.5                          # scale unit: 1.0 for a ~4.5m car
    gy=b[0][1]
    cx=ctr[0]; cz=ctr[2]
    y0=gy+H*0.075                     # underbody plane
    yd=lambda f: y0 - S*f             # hang below the pan by f (scale-relative)
    pan_parts=[]; gear_parts=[]
    def box(sx,sy,sz,x,y,z,dark=True):
        m=trimesh.creation.box(extents=[sx,sy,sz]); m.apply_translation([x,y,z])
        (pan_parts if dark else gear_parts).append(m)
    def tube(r,h,x,y,z,axis="z",dark=False):
        m=trimesh.creation.cylinder(radius=r,height=h,sections=18)
        if axis=="x": m.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2,[0,1,0]))
        m.apply_translation([x,y,z]); (pan_parts if dark else gear_parts).append(m)
    ax = "z" if length_axis==2 else "x"   # axis along the car length
    wx = "x" if length_axis==2 else "z"   # axis across the car
    # ---- orientation: which end is the FRONT? The roof mass (top ~22% of
    # height) sits rear-of-centre on virtually all cars (bonnet is low), so the
    # front is the end AWAY from the roof centroid. Mirror fractions if needed.
    flip_len=False
    try:
        whole=scene.dump(concatenate=True)
        v=whole.vertices
        top=v[v[:,1] > (gy+H*0.78)]
        if len(top)>50:
            f_roof=(np.mean(top[:,length_axis]) - b[0][length_axis])/Ln
            flip_len = f_roof < 0.5   # roof nearer f=0 → front is at f=1
    except Exception:
        pass
    def at(f_len, off_w=0.0):
        # (x,z) at fraction f_len along the length (0=front), off_w across width
        if flip_len: f_len = 1.0-f_len
        if length_axis==2: return cx+off_w, cz+(f_len-0.5)*Ln
        else: return cx+(f_len-0.5)*Ln, cz+off_w
    def lbox(len_frac, h, wid, f_len, y, off_w=0.0, dark=True):
        # box aligned with the car: len_frac of length, wid across width
        x,z=at(f_len,off_w)
        if length_axis==2: box(wid,h,Ln*len_frac, x,y,z,dark)
        else: box(Ln*len_frac,h,wid, x,y,z,dark)
    # ---- floor pan (dark tray, slightly narrower so gear peeks out) ----
    lbox(0.68, S*0.035, Wd*0.60, 0.5, y0, 0, True)
    # ---- engine (front third) + gearbox — kept LOW (scale-relative, centred
    # on the floor line) so nothing pokes above a low van bonnet or shows
    # through glass when viewed from above ----
    lbox(0.15, S*0.11, Wd*0.36, 0.20, y0-S*0.01, 0, True)
    lbox(0.11, S*0.09, Wd*0.20, 0.33, yd(0.02), 0, True)
    # ---- driveshaft: chunky steel tube visibly below the pan ----
    dx,dz=at(0.55); tube(S*0.045,Ln*0.45, dx,yd(0.055),dz,ax,False)
    # ---- rear axle + diff ----
    rx,rz=at(0.79); tube(S*0.055,Wd*0.72, rx,yd(0.05),rz,wx,False)
    lbox(0.08, H*0.10, Wd*0.15, 0.79, yd(0.03), 0, True)
    # ---- front subframe / anti-roll bar ----
    fx,fz=at(0.14); tube(S*0.04,Wd*0.70, fx,yd(0.03),fz,wx,False)
    # ---- fuel tank (rear-mid, dark) ----
    lbox(0.14, H*0.10, Wd*0.40, 0.62, y0-S*0.01, 0, True)
    # (exhaust line removed by request — pan + running gear only)
    # ---- sills / heat shields ----
    for side in (-1,1):
        lbox(0.58, H*0.09, S*0.03, 0.5, y0+H*0.03, side*Wd*0.44, True)
    # ---- UK number plates: white front / yellow rear, blue GB band ----
    pw=S*0.52; ph=S*0.115; pt=S*0.015           # 520x111mm plate on a 4.5m car
    py=gy+H*0.30
    def plate(f_len,colour,name):
        x,z=at(f_len)
        ext=[pw,ph,pt] if length_axis==2 else [pt,ph,pw]
        m=trimesh.creation.box(extents=ext); m.apply_translation([x,py,z])
        m.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name=name,baseColorFactor=colour,metallicFactor=0.0,roughnessFactor=0.35))
        scene.add_geometry(m,node_name=name)
        # blue GB band on the left edge, slightly proud to avoid z-fighting
        bx,bz=at(f_len,-(pw/2-pw*0.055))
        bext=[pw*0.11,ph*0.98,pt*1.08] if length_axis==2 else [pt*1.08,ph*0.98,pw*0.11]
        bm=trimesh.creation.box(extents=bext); bm.apply_translation([bx,py,bz])
        bm.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name=name+"_gb",baseColorFactor=[0.02,0.14,0.55,1.0],metallicFactor=0.0,roughnessFactor=0.4))
        scene.add_geometry(bm,node_name=name+"_gb")
    plate(0.001,[0.90,0.91,0.93,1.0],"number_plate_front")
    plate(0.999,[0.95,0.76,0.06,1.0],"number_plate_rear")
    # ---- materials: dark pan, lighter steel gear so detail reads ----
    pan=trimesh.util.concatenate(pan_parts)
    pan.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        name="undercarriage_metal",baseColorFactor=[0.07,0.07,0.08,1.0],
        metallicFactor=0.5,roughnessFactor=0.65))
    gear=trimesh.util.concatenate(gear_parts)
    gear.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        name="undercarriage_steel",baseColorFactor=[0.32,0.33,0.35,1.0],
        metallicFactor=0.85,roughnessFactor=0.35))
    scene.add_geometry(pan, node_name="undercarriage")
    scene.add_geometry(gear, node_name="undercarriage_gear")
    if audit_flip:
        scene.apply_transform(trimesh.transformations.rotation_matrix(np.pi,[0,0,1]))
    scene.export(glb_out)
    return True
if __name__=="__main__":
    a=sys.argv
    build(a[1],a[2], audit_flip=(len(a)>3 and a[3]=="flip"))
    print("done",a[2])
