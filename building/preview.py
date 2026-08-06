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
GROUND = (176, 192, 158)
SHADOW = (150, 166, 136)
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


def _quads(model, materials=EXTERIOR_MATERIALS):
    """The model's surfaces as QUADS rather than triangles.

    _glb_mesh emits each face as four vertices indexed [b,b+1,b+2, b,b+2,b+3],
    so the quad is recoverable and worth recovering: a course line drawn
    across a whole wall needs the wall, not two halves of it with a seam up
    the diagonal.
    """
    out = []
    groups = model3d._glb_mesh(model)
    for name, (pos, nrm, idx) in groups.items():
        if materials and name not in materials:
            continue
        rgba = dict((n, c) for n, c, *_ in model3d.GLB_MATERIALS)[name]
        for b in range(0, len(pos) // 3, 4):
            quad = [(pos[3 * (b + k)], pos[3 * (b + k) + 1],
                     pos[3 * (b + k) + 2]) for k in range(4)]
            out.append((quad, rgba, name))
    return out


# Course heights, in metres, for the surfaces that are actually coursed.
# 75mm is a UK brick course including its bed joint — the same figure the
# elevation reader checks drawings against.
COURSE_M = {"brick": 0.075, "plaster": None, "tile": 0.30,
            "glass": None, "door": None}


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


def _course(draw, quad, poly, project, name, colour, supersample):
    """Draw the coursing across one face, in the plane of that face.

    A flat-shaded box reads as a diagram; the same box with its brick courses
    and tile battens on it reads as a building, and the lines cost nothing
    because the geometry to hang them on is already exact. They are stepped
    in WORLD metres up the face's own edges, so they stay parallel to the
    eaves and converge correctly with the perspective instead of being
    stripes painted over a picture.
    """
    step = COURSE_M.get(name)
    if not step:
        return
    # Face height measured up the two side edges, whichever pair is longer.
    a, b, c, d = quad
    e0 = (d[0] - a[0], d[1] - a[1], d[2] - a[2])
    e1 = (c[0] - b[0], c[1] - b[1], c[2] - b[2])
    rise = math.sqrt(sum(k * k for k in e0))
    if rise < step * 1.5:
        return
    n = int(rise / step)
    if n < 2 or n > 400:
        return
    line = tuple(max(0, int(v * 0.86)) for v in colour)
    w = max(1, supersample // 2)
    for i in range(1, n):
        t = i / float(n)
        p0 = project((a[0] + e0[0] * t, a[1] + e0[1] * t, a[2] + e0[2] * t))
        p1 = project((b[0] + e1[0] * t, b[1] + e1[1] * t, b[2] + e1[2] * t))
        if p0 and p1:
            draw.line([(p0[0], p0[1]), (p1[0], p1[1])], fill=line, width=w)


def _sky(img, top=(150, 178, 210), bottom=(226, 234, 240)):
    """A vertical gradient instead of a flat card behind the building."""
    from PIL import Image
    w, h = img.size
    grad = Image.new("RGB", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / float(max(h - 1, 1))
        px[0, y] = tuple(int(top[k] + (bottom[k] - top[k]) * t)
                         for k in range(3))
    return grad.resize((w, h))


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

    faces = _quads(model)
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

    storeys_n = model.get("storeys", 1)
    per = model.get("storey_height_m", 2.75)

    S = size * supersample
    img = _sky(Image.new("RGB", (S, S), BACKGROUND))
    draw = ImageDraw.Draw(img)
    focal = (S / 2) / math.tan(math.radians(fov_deg) / 2)

    NEAR = 0.05

    def to_cam(p):
        d = (p[0] - eye[0], p[1] - eye[1], p[2] - eye[2])
        return (d[0] * right[0] + d[1] * right[1] + d[2] * right[2],
                d[0] * up[0] + d[1] * up[1] + d[2] * up[2],
                d[0] * fwd[0] + d[1] * fwd[1] + d[2] * fwd[2])

    def project(p):
        cx, cy, cz = to_cam(p)
        if cz <= NEAR:
            return None
        return (S / 2 + focal * cx / cz, S / 2 - focal * cy / cz, cz)

    def project_clipped(points):
        """Project a polygon that may run behind the camera.

        The ground plane is deliberately much larger than the building, so
        two of its corners sit behind the eye and project() correctly refuses
        them. Dropping the whole polygon for that left the building standing
        on open sky. Clipping it against the near plane first is the fix —
        the same Sutherland-Hodgman step, in camera space."""
        poly = [to_cam(p) for p in points]
        out = []
        for i in range(len(poly)):
            cur, prv = poly[i], poly[i - 1]
            cin, pin = cur[2] > NEAR, prv[2] > NEAR
            if cin != pin:
                t = (NEAR - prv[2]) / (cur[2] - prv[2])
                out.append(tuple(prv[k] + t * (cur[k] - prv[k])
                                 for k in range(3)))
            if cin:
                out.append(cur)
        return [(S / 2 + focal * c[0] / c[2], S / 2 - focal * c[1] / c[2])
                for c in out]

    # Ground first, as one big quad under the building.
    g = span * 2.4
    ground = [(centre[0] - g, min(ys) - 0.01, centre[2] - g),
              (centre[0] + g, min(ys) - 0.01, centre[2] - g),
              (centre[0] + g, min(ys) - 0.01, centre[2] + g),
              (centre[0] - g, min(ys) - 0.01, centre[2] + g)]
    gp = project_clipped(ground)
    if len(gp) >= 3:
        draw.polygon(gp, fill=GROUND)

    # The building's shadow, cast by the SAME sun that shades the faces —
    # the plan outline slid along the sun direction and flattened onto the
    # ground. Without it the model floats and reads as a cut-out.
    if SUN[1] > 0.05:
        k = (max(ys) - min(ys)) / SUN[1]
        for r in model.get("rooms") or []:
            rx0, ry0 = r["x"], r["y"]
            rx1, ry1 = rx0 + r["width_m"], ry0 + r["depth_m"]
            lift = (per * ((r.get("storeys") or storeys_n) - 1)
                    + r["height_m"])
            kk = lift / SUN[1]
            sh = []
            for px, py in ((rx0, ry0), (rx1, ry0), (rx1, ry1), (rx0, ry1)):
                # plan (x, y) -> render axes (x, up, -y), slid down the sun
                q = project((px - SUN[0] * kk, min(ys) + 0.02,
                             -(py - SUN[2] * kk)))
                if not q:
                    sh = []
                    break
                sh.append((q[0], q[1]))
            if len(sh) == 4:
                draw.polygon(sh, fill=SHADOW)

    drawn = []
    for quad, rgba, name in faces:
        proj = [project(p) for p in quad]
        if any(p is None for p in proj):
            continue
        u = (quad[1][0] - quad[0][0], quad[1][1] - quad[0][1],
             quad[1][2] - quad[0][2])
        v = (quad[3][0] - quad[0][0], quad[3][1] - quad[0][1],
             quad[3][2] - quad[0][2])
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
        depth = sum(p[2] for p in proj) / 4.0
        drawn.append((depth, quad, [(p[0], p[1]) for p in proj],
                      _shade(rgba, lam), rgba[3] if len(rgba) > 3 else 1.0,
                      name, lam))

    # Painter's algorithm: far to near. Per-quad sorting is exact enough for
    # building massing, where faces are large, planar and rarely
    # interpenetrate — the case that defeats it.
    drawn.sort(key=lambda t: -t[0])
    for _, quad, poly, colour, alpha, name, lam in drawn:
        if alpha < 0.95:
            # Glazing: let the wall behind read through, or every window
            # becomes a flat plate and the elevation stops being legible.
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).polygon(
                poly, fill=colour + (int(alpha * 255),))
            img = Image.alpha_composite(img.convert("RGBA"), layer
                                        ).convert("RGB")
            draw = ImageDraw.Draw(img)
            continue
        draw.polygon(poly, fill=colour, outline=colour)
        _course(draw, quad, poly, project, name, colour, supersample)

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
