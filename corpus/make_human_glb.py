#!/usr/bin/env python3
"""
make_human_glb.py — generate a REAL, license-free 3D human as a binary glTF (.glb).

No GPU, no accounts, no gated checkpoints. The body is built from anatomically
placed volumetric primitives (capsules for limbs/torso, ellipsoids for head and
mass groups), sampled onto a signed-distance field, and turned into a smooth
watertight surface with marching cubes. Three anatomy layers are produced and
packed into a single .glb scene:

    * skin      — outer body surface (semi-transparent skin tone)
    * muscle    — an inset surface (deep red) sitting just below the skin
    * skeleton  — a bone stick-figure (cylinders + joint spheres)

Output: human.glb  (open in any glTF viewer, or https://gltf-viewer.donmccurdy.com/)

Run:
    pip install numpy scipy scikit-image trimesh
    python make_human_glb.py
"""

import argparse
import numpy as np
import trimesh
from skimage import measure


# ----------------------------------------------------------------------------
# Signed-distance helpers.  Everything works in metres, +Y up, model centred on
# the origin in X/Z with the feet near the grid floor.
# ----------------------------------------------------------------------------
def sd_capsule(pts, a, b, r):
    """Distance from each point to a capsule (line segment a->b, radius r)."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    ab = b - a
    ap = pts - a
    denom = float(ab @ ab) or 1e-9
    t = np.clip((ap @ ab) / denom, 0.0, 1.0)
    proj = a + t[:, None] * ab
    return np.linalg.norm(pts - proj, axis=1) - r


def sd_ellipsoid(pts, center, radii):
    """Approximate signed distance to an axis-aligned ellipsoid."""
    center = np.asarray(center, float)
    radii = np.asarray(radii, float)
    p = (pts - center) / radii
    k0 = np.linalg.norm(p, axis=1)
    k1 = np.linalg.norm(p / radii, axis=1)
    k1 = np.where(k1 == 0, 1e-9, k1)
    return k0 * (k0 - 1.0) / k1


def smin(a, b, k=0.06):
    """Polynomial smooth-minimum — fuses primitives into one organic body."""
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


# ----------------------------------------------------------------------------
# Body definition — a neutral standing adult, roughly 1.75 m tall.
# Joint centres are shared between the surface build and the skeleton so the
# layers line up.
# ----------------------------------------------------------------------------
JOINTS = {
    "head_top":   (0.00, 1.75, 0.0),
    "head":       (0.00, 1.60, 0.0),
    "neck":       (0.00, 1.48, 0.0),
    "chest":      (0.00, 1.30, 0.0),
    "waist":      (0.00, 1.05, 0.0),
    "pelvis":     (0.00, 0.95, 0.0),
    "shoulder_l": (-0.19, 1.45, 0.0),
    "shoulder_r": (0.19, 1.45, 0.0),
    "elbow_l":    (-0.42, 1.18, 0.02),
    "elbow_r":    (0.42, 1.18, 0.02),
    "wrist_l":    (-0.55, 0.92, 0.04),
    "wrist_r":    (0.55, 0.92, 0.04),
    "hip_l":      (-0.10, 0.92, 0.0),
    "hip_r":      (0.10, 0.92, 0.0),
    "knee_l":     (-0.11, 0.52, 0.02),
    "knee_r":     (0.11, 0.52, 0.02),
    "ankle_l":    (-0.11, 0.08, -0.02),
    "ankle_r":    (0.11, 0.08, -0.02),
    "toe_l":      (-0.11, 0.02, 0.12),
    "toe_r":      (0.11, 0.02, 0.12),
}


def body_sdf(pts, inset=0.0):
    """
    Signed distance to the body surface. `inset` shrinks every radius so the
    same description yields the skin (inset=0) and the muscle layer (inset>0).
    """
    j = JOINTS

    def cap(a, b, r):
        return sd_capsule(pts, j[a], j[b], max(r - inset, 0.01))

    # Torso: stack a few capsules with tapering radii for a natural silhouette.
    d = sd_ellipsoid(pts, j["head"], (0.095 - inset, 0.115 - inset, 0.105 - inset))
    d = smin(d, cap("neck", "chest", 0.065))
    d = smin(d, cap("chest", "waist", 0.135))
    d = smin(d, cap("waist", "pelvis", 0.145))
    # shoulders / hips as broadening ellipsoids
    d = smin(d, sd_ellipsoid(pts, (0.0, 1.42, 0.0), (0.22 - inset, 0.07 - inset, 0.11 - inset)))
    d = smin(d, sd_ellipsoid(pts, (0.0, 0.94, 0.0), (0.16 - inset, 0.09 - inset, 0.12 - inset)))

    # Arms
    d = smin(d, cap("shoulder_l", "elbow_l", 0.050))
    d = smin(d, cap("elbow_l", "wrist_l", 0.040))
    d = smin(d, cap("shoulder_r", "elbow_r", 0.050))
    d = smin(d, cap("elbow_r", "wrist_r", 0.040))
    # hands
    d = smin(d, sd_ellipsoid(pts, (j["wrist_l"][0] - 0.02, j["wrist_l"][1] - 0.08, j["wrist_l"][2]),
                             (0.045 - inset, 0.075 - inset, 0.025 - inset)))
    d = smin(d, sd_ellipsoid(pts, (j["wrist_r"][0] + 0.02, j["wrist_r"][1] - 0.08, j["wrist_r"][2]),
                             (0.045 - inset, 0.075 - inset, 0.025 - inset)))

    # Legs
    d = smin(d, cap("hip_l", "knee_l", 0.075))
    d = smin(d, cap("knee_l", "ankle_l", 0.055))
    d = smin(d, cap("hip_r", "knee_r", 0.075))
    d = smin(d, cap("knee_r", "ankle_r", 0.055))
    # feet
    d = smin(d, cap("ankle_l", "toe_l", 0.040))
    d = smin(d, cap("ankle_r", "toe_r", 0.040))
    return d


# ----------------------------------------------------------------------------
# Meshing.
# ----------------------------------------------------------------------------
def surface_mesh(inset=0.0, res=140, pad=0.15):
    """Sample body_sdf on a grid and extract the zero level set."""
    lo = np.array([-0.75, -0.05, -0.35]) - pad
    hi = np.array([0.75, 1.85, 0.35]) + pad
    nx, ny, nz = res // 2, res, res // 3
    xs = np.linspace(lo[0], hi[0], nx)
    ys = np.linspace(lo[1], hi[1], ny)
    zs = np.linspace(lo[2], hi[2], nz)
    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
    pts = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)

    field = body_sdf(pts, inset=inset).reshape(nx, ny, nz)

    spacing = ((hi - lo) / (np.array([nx, ny, nz]) - 1))
    verts, faces, normals, _ = measure.marching_cubes(field, level=0.0, spacing=tuple(spacing))
    verts += lo  # marching_cubes returns grid-local coords; shift back to world
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, vertex_normals=normals, process=True)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    trimesh.smoothing.filter_taubin(mesh, iterations=12)
    return mesh


def skeleton_mesh():
    """A simple bone stick-figure: cylinders for bones, spheres for joints."""
    j = JOINTS
    bones = [
        ("head", "neck"), ("neck", "chest"), ("chest", "waist"), ("waist", "pelvis"),
        ("shoulder_l", "shoulder_r"),
        ("chest", "shoulder_l"), ("chest", "shoulder_r"),
        ("shoulder_l", "elbow_l"), ("elbow_l", "wrist_l"),
        ("shoulder_r", "elbow_r"), ("elbow_r", "wrist_r"),
        ("hip_l", "hip_r"), ("pelvis", "hip_l"), ("pelvis", "hip_r"),
        ("hip_l", "knee_l"), ("knee_l", "ankle_l"), ("ankle_l", "toe_l"),
        ("hip_r", "knee_r"), ("knee_r", "ankle_r"), ("ankle_r", "toe_r"),
    ]
    parts = []
    for a, b in bones:
        seg = trimesh.creation.cylinder(radius=0.014,
                                        segment=[np.array(j[a]), np.array(j[b])],
                                        sections=12)
        parts.append(seg)
    for name, c in j.items():
        if name in ("toe_l", "toe_r", "head_top"):
            continue
        s = trimesh.creation.icosphere(subdivisions=2, radius=0.024)
        s.apply_translation(c)
        parts.append(s)
    # skull
    skull = trimesh.creation.icosphere(subdivisions=3, radius=0.085)
    skull.apply_translation(j["head"])
    parts.append(skull)
    return trimesh.util.concatenate(parts)


def colored(mesh, rgba):
    mesh = mesh.copy()
    mesh.visual = trimesh.visual.TextureVisuals()  # reset
    mat = trimesh.visual.material.PBRMaterial(
        baseColorFactor=rgba,
        metallicFactor=0.0,
        roughnessFactor=0.85,
        alphaMode="BLEND" if rgba[3] < 255 else "OPAQUE",
    )
    mesh.visual = trimesh.visual.TextureVisuals(material=mat)
    return mesh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="human.glb")
    ap.add_argument("--res", type=int, default=140, help="grid resolution (higher = smoother, slower)")
    ap.add_argument("--layers", default="skin,muscle,skeleton",
                    help="comma list of layers to include")
    args = ap.parse_args()
    want = {s.strip() for s in args.layers.split(",") if s.strip()}

    scene = trimesh.Scene()

    if "skin" in want:
        print("[build] skin surface ...")
        skin = surface_mesh(inset=0.0, res=args.res)
        print(f"        skin: {len(skin.vertices)} verts, {len(skin.faces)} faces, "
              f"watertight={skin.is_watertight}")
        scene.add_geometry(colored(skin, [226, 178, 126, 235]), geom_name="skin")

    if "muscle" in want:
        print("[build] muscle surface ...")
        muscle = surface_mesh(inset=0.022, res=args.res)
        print(f"        muscle: {len(muscle.vertices)} verts, {len(muscle.faces)} faces")
        scene.add_geometry(colored(muscle, [201, 74, 74, 255]), geom_name="muscle")

    if "skeleton" in want:
        print("[build] skeleton ...")
        skel = skeleton_mesh()
        print(f"        skeleton: {len(skel.vertices)} verts, {len(skel.faces)} faces")
        scene.add_geometry(colored(skel, [245, 239, 235, 255]), geom_name="skeleton")

    scene.export(args.out)
    print(f"[done] wrote {args.out}")


if __name__ == "__main__":
    main()
