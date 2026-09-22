#!/usr/bin/env python3
"""Derive the rig a teardown bay needs — hinge axes, wheel corners, ground —
from a GLB's own geometry, so a second car does not need a hand-written
table like the Golf's.

WHY THIS EXISTS. `golf-bay.html` carries a HINGE constant with hard-coded
numbers measured off one car:

    door_fl:{x: 0.772,y:0,z: 0.870} …  tailgate:{x:0,y:1.394,z:-1.472}

Those are correct for `volkswagen-golf-2021-w12-v1` and meaningless for
anything else, so the app can only ever take that one car apart. Every
number here is computed from the file instead: a door hinges on its own
FORWARD vertical edge, a bonnet on its REAR transverse edge, a tailgate
on its TOP transverse edge. That is where the hinge is on a real car and
it falls out of the part's own bounding box once the axes are known.

WHAT IT DOES NOT DO, stated because a silent limit is worse than a gap:

  * It reads BOUNDING BOXES, not hinge hardware. A door whose bbox is
    skewed by a mirror on its leading edge will hinge slightly forward of
    true. Good enough to swing a door for teaching; not a measurement of
    the real hinge position.
  * It cannot tell a suicide door from a conventional one. Everything
    front-hinges except the tailgate and bonnet.
  * THE WHEELS ARE THE INTERESTING CASE. The sim-mod family instances one
    wheel four times — `wheel_x`, `.001`, `.002`, `.003` — so no NAME says
    which corner is which. They are assigned here by POSITION, and that is
    the only honest way to do it: a trainer that says "front left" while
    moving an arbitrary wheel teaches the wrong thing.
"""
import json, struct, sys, math, argparse, os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glb_parts import classify3, c3_prefix   # one classifier, not a copy


def load_glb(path):
    d = open(path, 'rb').read()
    magic, ver, total, jlen, jtype = struct.unpack('<IIIII', d[:20])
    if magic != 0x46546C67:
        raise ValueError('not a GLB')
    g = json.loads(d[20:20 + jlen])
    return g


def mat_mul(a, b):
    return [sum(a[i * 4 + k] * b[k * 4 + j] for k in range(4))
            for i in range(4) for j in range(4)]


def trs(node):
    """Node local matrix. glTF order is T * R * S, and `matrix` wins if set."""
    if 'matrix' in node:                 # glTF stores column-major
        m = node['matrix']
        return [m[0], m[4], m[8], m[12], m[1], m[5], m[9], m[13],
                m[2], m[6], m[10], m[14], m[3], m[7], m[11], m[15]]
    t = node.get('translation', [0, 0, 0])
    q = node.get('rotation', [0, 0, 0, 1])
    s = node.get('scale', [1, 1, 1])
    x, y, z, w = q
    R = [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0,
         2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0,
         2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0,
         0, 0, 0, 1]
    for c in range(3):
        for r in range(3):
            R[r * 4 + c] *= s[c]
    R[3], R[7], R[11] = t[0], t[1], t[2]
    return [R[0], R[1], R[2], t[0], R[4], R[5], R[6], t[1],
            R[8], R[9], R[10], t[2], 0, 0, 0, 1]


def xform(m, p):
    return [m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + m[3],
            m[4] * p[0] + m[5] * p[1] + m[6] * p[2] + m[7],
            m[8] * p[0] + m[9] * p[1] + m[10] * p[2] + m[11]]


def part_boxes(g):
    """World-space bbox per NAMED PART node.

    The part name is the nearest NAMED ANCESTOR, because this exporter
    family puts the part name on a parent and splits its children one per
    material: `xc90_door_FL` holds `xc90_door_FL_xc90_black_0`,
    `…_chrome_0` and so on. Classifying the children individually would
    scatter one door across several groups.
    """
    acc = g.get('accessors', [])
    boxes = defaultdict(lambda: [[1e30] * 3, [-1e30] * 3])
    ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]

    def walk(i, M, owner):
        n = g['nodes'][i]
        M = mat_mul(M, trs(n))
        nm = n.get('name', '')
        # a node with children and a name is a part; a leaf mesh inherits
        if nm and ('children' in n or 'mesh' not in n):
            owner = nm
        if 'mesh' in n:
            who = owner or nm
            lo, hi = boxes[who]
            for prim in g['meshes'][n['mesh']].get('primitives', []):
                ai = prim.get('attributes', {}).get('POSITION')
                if ai is None:
                    continue
                a = acc[ai]
                if 'min' not in a:
                    continue
                mn, mx = a['min'], a['max']
                for cx in (mn[0], mx[0]):
                    for cy in (mn[1], mx[1]):
                        for cz in (mn[2], mx[2]):
                            w = xform(M, [cx, cy, cz])
                            for k in range(3):
                                lo[k] = min(lo[k], w[k])
                                hi[k] = max(hi[k], w[k])
        for c in n.get('children', []):
            walk(c, M, owner)

    for r in g['scenes'][g.get('scene', 0)]['nodes']:
        walk(r, ident, None)
    return {k: v for k, v in boxes.items() if v[0][0] < 1e29}


def axes(boxes):
    """Which world axis is the car's LENGTH, WIDTH and HEIGHT.

    Derived, never assumed. glTF is Y-up by convention but an FBX
    conversion can land the car on any axis, and this project has already
    shipped a car lying on its side because a pose was assumed rather than
    measured. Length is the longest extent; UP is the axis on which the
    GLAZING sits above the WHEELS, which is a physical fact about a car
    rather than a convention.
    """
    lo = [min(b[0][k] for b in boxes.values()) for k in range(3)]
    hi = [max(b[1][k] for b in boxes.values()) for k in range(3)]
    ext = [hi[k] - lo[k] for k in range(3)]
    length = ext.index(max(ext))
    # candidate up = the remaining axis on which wheels sit lowest
    wheel = [b for n, b in boxes.items()
             if any(w in n.lower() for w in ('wheel', 'tire', 'tyre'))]
    glass = [b for n, b in boxes.items()
             if any(w in n.lower() for w in ('glass', 'windshield', 'window'))]
    up, best = None, -1e30
    for k in range(3):
        if k == length or not wheel or not glass:
            continue
        wmid = sum((b[0][k] + b[1][k]) / 2 for b in wheel) / len(wheel)
        gmid = sum((b[0][k] + b[1][k]) / 2 for b in glass) / len(glass)
        if gmid - wmid > best:
            best, up = gmid - wmid, k
    if up is None:
        up = ext.index(min(ext))
    width = 3 - length - up
    return {'length': length, 'up': up, 'width': width,
            'lo': lo, 'hi': hi, 'ext': ext,
            'glassAboveWheels': round(best, 4)}


def rig(g):
    boxes = part_boxes(g)
    raw = dict(boxes)          # UNGROUPED — the wheels need this, see below
    ax = axes(boxes)
    L, U, W = ax['length'], ax['up'], ax['width']
    lo, hi = ax['lo'], ax['hi']
    mid_w = (lo[W] + hi[W]) / 2
    out = {'axes': ax, 'hinges': {}, 'wheels': {}, 'ground': lo[U],
           'parts': {}}

    # NOSE DIRECTION. The bonnet sits over the engine, so the end of the
    # car its centre is nearer IS the nose. Refuse rather than guess when
    # there is no bonnet — a wrong nose mirrors every hinge on the car.
    nose = None
    for n, b in boxes.items():
        if n.lower().endswith('hood') or n.lower().endswith('bonnet'):
            c = (b[0][L] + b[1][L]) / 2
            nose = +1 if c > (lo[L] + hi[L]) / 2 else -1
    out['nose'] = nose

    def box(n):
        return boxes.get(n)

    # GROUP BEFORE MEASURING. `xc90_door_FL_trim_chrome` is a sibling node
    # of `xc90_door_FL`, not a child, so measuring per NODE gave the door's
    # chrome strip its own hinge — a hinge for a part that is not a part.
    # Group by the id the APP will classify to, then take one box per group,
    # so the hinge is the hinge of the thing that actually swings.
    grouped = defaultdict(lambda: [[1e30] * 3, [-1e30] * 3])
    members = defaultdict(list)
    pre = c3_prefix(list(boxes))
    for name, b in boxes.items():
        pid = classify3(name, pre)
        if pid == 'body':
            pid = name                       # keep unclassified parts distinct
        members[pid].append(name)
        lo_, hi_ = grouped[pid]
        for k in range(3):
            lo_[k] = min(lo_[k], b[0][k])
            hi_[k] = max(hi_[k], b[1][k])
    boxes = dict(grouped)

    for name, b in boxes.items():
        low = name.lower()
        base = low.split('_', 1)[1] if '_' in low else low
        cen = [(b[0][k] + b[1][k]) / 2 for k in range(3)]
        out['parts'][name] = {'min': [round(v, 4) for v in b[0]],
                              'max': [round(v, 4) for v in b[1]],
                              'centre': [round(v, 4) for v in cen],
                              'nodes': members.get(name, [])}
        # ── DOORS hinge on their own FORWARD vertical edge ──
        if low.startswith('door_') and 'glass' not in low and nose:
            fwd = b[1][L] if nose > 0 else b[0][L]
            h = [0, 0, 0]
            h[L] = fwd
            h[W] = cen[W]
            h[U] = cen[U]
            out['hinges'][name] = {'point': [round(v, 4) for v in h],
                                   'axis': 'up', 'side': 1 if cen[W] > mid_w else -1}
        # ── BONNET hinges on its REAR transverse edge ──
        if low in ('panel_bonnet', 'hood', 'bonnet') and nose:
            rear = b[0][L] if nose > 0 else b[1][L]
            h = [0, 0, 0]
            h[L] = rear
            h[U] = b[1][U]
            h[W] = cen[W]
            out['hinges'][name] = {'point': [round(v, 4) for v in h],
                                   'axis': 'width'}
        # ── TAILGATE hinges on its TOP transverse edge ──
        if low in ('tailgate', 'trunk', 'hatch', 'boot'):
            h = [0, 0, 0]
            h[L] = cen[L]
            h[U] = b[1][U]
            h[W] = cen[W]
            out['hinges'][name] = {'point': [round(v, 4) for v in h],
                                   'axis': 'width'}

    # ── WHEELS BY POSITION, because the names do not say which corner ──
    # MEASURED ON THE UNGROUPED BOXES, and that is the whole point. Grouping
    # by name first merged all four rims into one `wheels_unsided` blob with
    # a 1.74 m radius centred on the car — a perfect demonstration of why a
    # name cannot assign a corner. Each NODE is placed by where it sits.
    # substring, not a prefix: these names are car-prefixed
    # (`xc90_wheel_inscription`), so anchoring finds only the tyres
    wheels = {n: b for n, b in raw.items()
              if any(w in n.lower() for w in ('wheel', 'tire', 'tyre'))
              and not any(x in n.lower() for x in ('steering', 'arch', 'well'))}
    if wheels and nose:
        for n, b in wheels.items():
            cen = [(b[0][k] + b[1][k]) / 2 for k in range(3)]
            # a wheel sits in the bottom half of the car; anything above
            # that is a spare, a steering wheel or a badge
            if cen[U] > lo[U] + 0.45 * (hi[U] - lo[U]):
                continue
            front = (cen[L] - (lo[L] + hi[L]) / 2) * nose > 0
            left = cen[W] > mid_w
            corner = ('F' if front else 'R') + ('L' if left else 'R')
            out['wheels'].setdefault(corner, []).append(
                {'node': n, 'centre': [round(v, 4) for v in cen],
                 'radius': round(max(b[1][L] - b[0][L], b[1][U] - b[0][U]) / 2, 4)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glb')
    ap.add_argument('--json', help='write the rig here')
    a = ap.parse_args()
    g = load_glb(a.glb)
    r = rig(g)
    ax = r['axes']
    names = ['X', 'Y', 'Z']
    print(f"axes: length={names[ax['length']]} up={names[ax['up']]} "
          f"width={names[ax['width']]}   extents="
          f"{[round(v,3) for v in ax['ext']]}")
    print(f"glazing sits {ax['glassAboveWheels']} above the wheels on the up axis "
          f"(positive = the up axis is right)")
    print(f"nose towards {'+' if r['nose']==1 else '-'}{names[ax['length']]}"
          if r['nose'] else "nose: UNDECIDABLE (no bonnet found)")
    print(f"ground plane at {round(r['ground'],4)}\n")
    print(f"HINGES ({len(r['hinges'])}):")
    for n, h in sorted(r['hinges'].items()):
        print(f"   {n:<28} {h['point']}  about {h['axis']}")
    print(f"\nWHEEL CORNERS ({len(r['wheels'])}/4 found by POSITION):")
    for c in ('FL', 'FR', 'RL', 'RR'):
        for w in r['wheels'].get(c, []):
            print(f"   {c}  {w['node']:<34} centre {w['centre']} r={w['radius']}")
        if c not in r['wheels']:
            print(f"   {c}  -- none --")
    if a.json:
        json.dump(r, open(a.json, 'w'), indent=1)
        print(f"\nwrote {a.json}")


if __name__ == '__main__':
    main()
