"""A shaded picture of a finished model, without a GPU.

A job that returns a GLB and an IFC has done its work, but nobody can tell at
a glance whether the geometry is right. A builder opening a proposal wants to
SEE the house before they open anything in a viewer, and every wrong model
this project has produced — a roof floating clear of its walls, an extension
on the wrong side, a terrace slabbed as one block — was obvious the moment it
was drawn and invisible in the numbers.

So this rasterises the same triangles the GLB carries, in software:
z-sorted painter's algorithm, one flat shade per face from a fixed sun, drawn
with PIL. No GPU, no Blender, no headless browser, no extra megabyte in the
image — PIL is already there for Render Mode. It is not a photoreal render
and does not pretend to be; it is a clear, honest look at the actual
geometry, which is the thing that has to be right first.
"""
import math
import os

import model3d


# Sun direction in the render's own axes — high, front-left, the convention
# every architectural visual uses because it reads the massing without
# flattening the elevations.
SUN = (-0.42, 0.80, 0.43)

# Ambient floor. Pure n-dot-l puts north elevations at zero and they vanish
# into the background; real skylight does not work that way.
AMBIENT = 0.42

# Faces within this of edge-on are dropped. They contribute nothing but
# z-fighting speckle along the wall heads.
EDGE_ON = 1e-4

BACKGROUND = (238, 240, 243)
GROUND = (206, 212, 205)
OUTLINE = (44, 48, 54)


def _shade(rgb, lambert):
    """A base colour under one flat light."""
    k = AMBIENT + (1.0 - AMBIENT) * max(lambert, 0.0)
    return tuple(max(0, min(255, int(round(c * 255 * k)))) for c in rgb[:3])


# What an OUTSIDE view is made of. Internal floor plates and internal
# plasterwork are not merely redundant here, they actively wreck the picture:
# a floor slab spans the whole building, so its mean depth can beat a wall it
# genuinely sits behind, and the painter's sort then paints it straight
# across the elevation as a diagonal white band. Ordering triangles can never
# fix a polygon that is both in front of and behind another one — not drawing
# the invisible ones can.
# Plasterwork stays IN. It is the inside face of every external wall, so it
# sits behind the brick and the sort hides it — but where a single-storey
# extension abuts the house, the wall it abuts is marked internal for its
# whole height, and dropping plaster punched a hole straight through the
# elevation above the extension roof. Only the horizontal plates come out.
EXTERIOR_MATERIALS = ("brick", "tile", "glass", "door", "plaster")


def _faces(model, materials=EXTERIOR_MATERIALS):
    """Every triangle in the model as (points, colour_rgba), world axes.

    Reuses model3d's own mesh builder, so the picture is of the geometry that
    ships in the GLB rather than of a second, parallel description of it that
    could drift from it.
    """
    out = []
    groups = model3d._glb_mesh(model)
    for name, (pos, nrm, idx) in groups.items():
        if materials and name not in materials:
            continue
        rgba = dict((n, c) for n, c, *_ in model3d.GLB_MATERIALS)[name]
        for i in range(0, len(idx), 3):
            tri = [(pos[3 * idx[i + k]], pos[3 * idx[i + k] + 1],
                    pos[3 * idx[i + k] + 2]) for k in range(3)]
            out.append((tri, rgba, name))
    return out


def _look_at(eye, target, up=(0.0, 1.0, 0.0)):
    """Camera basis vectors, right-handed, looking down -z."""
    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def norm(v):
        m = math.sqrt(sum(c * c for c in v)) or 1.0
        return (v[0] / m, v[1] / m, v[2] / m)

    def cross(a, b):
        return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0])

    f = norm(sub(target, eye))
    r = norm(cross(f, up))
    u = cross(r, f)
    return r, u, f


def render(model, path, size=1100, yaw_deg=35.0, pitch_deg=24.0,
           fov_deg=38.0, supersample=2):
    """Draw the model to a PNG and return the path.

    `yaw_deg` orbits around the building measured from the FRONT elevation,
    so 0 is a straight-on front view and 35 is the three-quarter view a
    proposal is normally drawn from.
    """
    from PIL import Image, ImageDraw

    faces = _faces(model)
    if not faces:
        raise ValueError("the model has no geometry to draw")

    pts = [p for tri, _, _ in faces for p in tri]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    centre = ((min(xs) + max(xs)) / 2, min(ys), (min(zs) + max(zs)) / 2)
    span = max(max(xs) - min(xs), max(zs) - min(zs), max(ys) - min(ys)) or 1.0

    # Sit back far enough that the whole building fits the frame with air
    # around it, then aim a third of the way up rather than at the base.
    dist = span * 2.05
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    eye = (centre[0] + dist * math.cos(pitch) * math.sin(yaw),
           centre[1] + dist * math.sin(pitch),
           centre[2] + dist * math.cos(pitch) * math.cos(yaw))
    target = (centre[0], centre[1] + span * 0.30, centre[2])
    right, up, fwd = _look_at(eye, target)

    S = size * supersample
    img = Image.new("RGB", (S, S), BACKGROUND)
    draw = ImageDraw.Draw(img)
    focal = (S / 2) / math.tan(math.radians(fov_deg) / 2)

    def project(p):
        d = (p[0] - eye[0], p[1] - eye[1], p[2] - eye[2])
        cz = d[0] * fwd[0] + d[1] * fwd[1] + d[2] * fwd[2]
        if cz <= 0.05:
            return None
        cx = d[0] * right[0] + d[1] * right[1] + d[2] * right[2]
        cy = d[0] * up[0] + d[1] * up[1] + d[2] * up[2]
        return (S / 2 + focal * cx / cz, S / 2 - focal * cy / cz, cz)

    # Ground first, as one big quad under the building.
    g = span * 2.4
    ground = [(centre[0] - g, min(ys) - 0.01, centre[2] - g),
              (centre[0] + g, min(ys) - 0.01, centre[2] - g),
              (centre[0] + g, min(ys) - 0.01, centre[2] + g),
              (centre[0] - g, min(ys) - 0.01, centre[2] + g)]
    gp = [project(p) for p in ground]
    if all(gp):
        draw.polygon([(p[0], p[1]) for p in gp], fill=GROUND)

    drawn = []
    for tri, rgba, name in faces:
        proj = [project(p) for p in tri]
        if any(p is None for p in proj):
            continue
        u = (tri[1][0] - tri[0][0], tri[1][1] - tri[0][1],
             tri[1][2] - tri[0][2])
        v = (tri[2][0] - tri[0][0], tri[2][1] - tri[0][1],
             tri[2][2] - tri[0][2])
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
             u[0] * v[1] - u[1] * v[0])
        m = math.sqrt(sum(c * c for c in n))
        if m < EDGE_ON:
            continue
        n = (n[0] / m, n[1] / m, n[2] / m)
        # NO BACKFACE CULLING. The quads are emitted with a winding that
        # depends on which side of the wall each face sits, so a
        # winding-based cull removes the wrong half. The painter's sort is
        # what keeps the inside hidden, and it is sufficient because the
        # envelope is closed.
        lam = abs(n[0] * SUN[0] + n[1] * SUN[1] + n[2] * SUN[2])
        depth = sum(p[2] for p in proj) / 3.0
        drawn.append((depth, [(p[0], p[1]) for p in proj],
                      _shade(rgba, lam), rgba[3] if len(rgba) > 3 else 1.0))

    # Painter's algorithm: far to near. Per-triangle sorting is exact enough
    # for building massing, where faces are large, planar and rarely
    # interpenetrate — the case that defeats it.
    drawn.sort(key=lambda t: -t[0])
    for _, poly, colour, alpha in drawn:
        if alpha < 0.95:
            # Glazing: let the wall behind read through, or every window
            # becomes a flat plate and the elevation stops being legible.
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).polygon(
                poly, fill=colour + (int(alpha * 255),))
            img = Image.alpha_composite(img.convert("RGBA"), layer
                                        ).convert("RGB")
            draw = ImageDraw.Draw(img)
        else:
            draw.polygon(poly, fill=colour, outline=colour)

    img = img.resize((size, size), Image.LANCZOS)
    img.save(path, quality=95)
    return path


def views(model, directory, scan, angles=((35, 24), (-45, 22), (0, 8))):
    """A small set of standard views: three-quarter, the other corner, front.

    One view can hide the whole point of a proposal — a side extension is
    invisible from the wrong corner — so a proposal ships with more than one.
    """
    out = []
    names = ("corner", "rear-corner", "front")
    for (yaw, pitch), name in zip(angles, names):
        p = os.path.join(directory, f"{scan}.{name}.png")
        try:
            render(model, p, yaw_deg=yaw, pitch_deg=pitch)
            out.append((p, f"previews/{scan}.{name}.png", None))
        except Exception as e:
            # A preview is a convenience. Losing one must never lose the
            # model it was drawn from.
            print(f"preview {name} failed: {type(e).__name__}: {e}")
    return out
