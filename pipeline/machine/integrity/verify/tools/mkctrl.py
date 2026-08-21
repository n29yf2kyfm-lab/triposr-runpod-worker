#!/usr/bin/env python3
"""
INJECTED NEGATIVE CONTROLS.

CLAUDE.md: "A gate nobody tested is a gate that does not exist."  Nine checks
were found on this project in a single day that could never fire -- a
`run_controls()` that was dead code, a fidelity gate that passed eleven blank
images at 46.24 dB, a hole test whose `lost` class is structurally zero on this
car.  Every check this verifier reports must therefore be shown FAILING on a
deliberately broken copy, and must return the magnitude that was injected.

Each control is a byte-level edit of a COPY of the locked source.  Index data
is overwritten IN PLACE wherever possible so that no accessor count, no
bufferView offset and no buffer length changes -- the only difference between
control and source is the defect itself.  The locked source is opened read-only
and is never written to.

Usage: python3 mkctrl.py <source.glb> <outdir>
"""
import sys, os, json, struct, hashlib
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from glb_audit import load_glb, read_accessor, CT, NC

SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
RAW = open(SRC, 'rb').read()
SRC_SHA = hashlib.sha256(RAW).hexdigest()


def parse_chunks(data):
    off, js_range, bin_range = 12, None, None
    while off < len(data):
        clen, ctype = struct.unpack('<II', data[off:off + 8])
        if ctype == 0x4E4F534A:
            js_range = (off + 8, off + 8 + clen)
        elif ctype == 0x004E4942:
            bin_range = (off + 8, off + 8 + clen)
        off += 8 + clen
        off = off if off % 4 == 0 else off + (4 - off % 4)
    return js_range, bin_range


JSR, BINR = parse_chunks(RAW)
G = json.loads(RAW[JSR[0]:JSR[1]].decode('utf-8'))
BIN = bytearray(RAW[BINR[0]:BINR[1]])


def write_glb(path, gjson, binbytes):
    js = json.dumps(gjson, separators=(',', ':')).encode('utf-8')
    js += b' ' * ((4 - len(js) % 4) % 4)
    bb = bytes(binbytes)
    bb += b'\x00' * ((4 - len(bb) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bb)
    out = bytearray()
    out += b'glTF' + struct.pack('<II', 2, total)
    out += struct.pack('<II', len(js), 0x4E4F534A) + js
    out += struct.pack('<II', len(bb), 0x004E4942) + bb
    open(path, 'wb').write(out)
    return hashlib.sha256(out).hexdigest(), total


def node_by_name(g, name):
    for i, n in enumerate(g.get('nodes', [])):
        if n.get('name') == name:
            return i
    raise SystemExit('no node named ' + name)


def idx_view(g, prim):
    """byte offset, stride, component format and count of a primitive's indices"""
    a = g['accessors'][prim['indices']]
    bv = g['bufferViews'][a['bufferView']]
    fmt, sz = CT[a['componentType']]
    base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    return base, sz, fmt, a['count']


def pos_minmax(g, prim):
    a = g['accessors'][prim['attributes']['POSITION']]
    return a['min'], a['max']


REPORT = {'source': os.path.basename(SRC), 'source_sha256': SRC_SHA, 'controls': []}


def emit(name, gjson, binb, desc, injected):
    p = os.path.join(OUT, name + '.glb')
    sha, n = write_glb(p, gjson, binb)
    REPORT['controls'].append({'control': name, 'file': name + '.glb',
                               'sha256': sha, 'bytes': n,
                               'defect': desc, 'injected_magnitude': injected})
    print('%-18s %-56s %s' % (name, desc[:56], json.dumps(injected)))


import copy

# ---------------------------------------------------------------- C1 dup faces
# Overwrite the LAST n triangles of Body_Shell's index run with copies of its
# FIRST n.  Accessor count is unchanged, so the file still DECLARES the same
# triangle total; Blender must now drop exactly n more on import.
N_DUP = 250
g = copy.deepcopy(G); b = bytearray(BIN)
ni = node_by_name(g, 'Body_Shell')
pr = g['meshes'][g['nodes'][ni]['mesh']]['primitives'][0]
base, sz, fmt, cnt = idx_view(g, pr)
tri = cnt // 3
src0 = bytes(b[base: base + N_DUP * 3 * sz])
dst = base + (tri - N_DUP) * 3 * sz
b[dst: dst + N_DUP * 3 * sz] = src0
emit('C1_dupfaces', g, b,
     'Body_Shell: last 250 triangles replaced by copies of its first 250',
     {'duplicate_index_triples_added': N_DUP,
      'expected_blender_triangle_drop': N_DUP,
      'expected_declared_triangle_change': 0})

# ---------------------------------------------------------------- C2 5 mm sink
# glTF is Y-UP: height is component 1.  Sinking every scene root by 5 mm puts
# all four tyres 5 mm BELOW the ground plane.
SINK = 0.005
g = copy.deepcopy(G)
for r in g['scenes'][g.get('scene', 0)]['nodes']:
    n = g['nodes'][r]
    if 'matrix' in n:
        n['matrix'][13] -= SINK
    else:
        t = n.get('translation', [0, 0, 0])
        n['translation'] = [t[0], t[1] - SINK, t[2]]
emit('C2_sink5mm', g, BIN,
     'every scene root translated -5 mm on glTF Y (height)',
     {'sink_m': SINK, 'expected_tyre_zmin_m': -SINK})

# ---------------------------------------------------------------- C3 glass cut
# Shrink every glazing node about its own centroid to 16% linear = 2.56% area.
# CLAUDE.md warns that glass_probe returns "clear/proven" on glazing cut to 2.5%
# of its area; this control exists to prove the paired glass-AREA figure fires.
S = 0.16
g = copy.deepcopy(G)
touched = []
for i, n in enumerate(g.get('nodes', [])):
    nm = (n.get('name') or '').lower()
    if 'glass' not in nm:
        continue
    m = g['meshes'][n['mesh']]
    mn, mx = pos_minmax(g, m['primitives'][0])
    c = [(mn[k] + mx[k]) / 2.0 for k in range(3)]
    t = n.get('translation', [0, 0, 0])
    sc_ = n.get('scale', [1, 1, 1])
    n['scale'] = [sc_[k] * S for k in range(3)]
    n['translation'] = [t[k] + c[k] * sc_[k] * (1 - S) for k in range(3)]
    touched.append(n.get('name'))
emit('C3_glasscut', g, BIN,
     'every glazing node scaled to 16%% linear about its centroid (%d nodes)' % len(touched),
     {'linear_scale': S, 'expected_area_fraction_of_baseline': round(S * S, 4),
      'nodes': touched})

# ------------------------------------------------------------- C4 flip winding
# Reverse the winding of Bumper_Front_Paint's first primitive.  Its faces then
# point INWARD: the face-orientation sheet must go red there and the
# backface-culling-ON sheet must show a hole.
g = copy.deepcopy(G); b = bytearray(BIN)
ni = node_by_name(g, 'Bumper_Front_Paint')
pr = g['meshes'][g['nodes'][ni]['mesh']]['primitives'][0]
base, sz, fmt, cnt = idx_view(g, pr)
st = struct.Struct('<' + fmt)
flipped = 0
for t in range(cnt // 3):
    o = base + t * 3 * sz
    a0 = st.unpack_from(b, o)[0]
    a2 = st.unpack_from(b, o + 2 * sz)[0]
    st.pack_into(b, o, a2)
    st.pack_into(b, o + 2 * sz, a0)
    flipped += 1
emit('C4_flipwinding', g, b,
     'Bumper_Front_Paint primitive 0: winding reversed on every triangle',
     {'triangles_flipped': flipped})

# ------------------------------------------------------------ C5 wheel mismatch
# Enlarge ONE front wheel group by 5%.  The left/right wheel-parity metric must
# report ~5% linear / ~10.25% area on that corner and stay put on the others.
WS = 1.05
g = copy.deepcopy(G)
grp = [n for n in g['nodes'] if (n.get('name') or '').startswith('Wheel_FL_')]
for n in grp:
    m = g['meshes'][n['mesh']]
    mn, mx = pos_minmax(g, m['primitives'][0])
    c = [(mn[k] + mx[k]) / 2.0 for k in range(3)]
    t = n.get('translation', [0, 0, 0])
    sc_ = n.get('scale', [1, 1, 1])
    n['scale'] = [sc_[k] * WS for k in range(3)]
    n['translation'] = [t[k] + c[k] * sc_[k] * (1 - WS) for k in range(3)]
emit('C5_wheelmismatch', g, BIN,
     'Wheel_FL_* group scaled 1.05 about its centroid (%d nodes)' % len(grp),
     {'linear_scale': WS, 'expected_area_ratio': round(WS * WS, 4),
      'expected_radius_delta_pct': round((WS - 1) * 100, 2),
      'nodes': [n.get('name') for n in grp]})

# ------------------------------------------------------------------- C6 hole
# Collapse 3,000 triangles in the middle of Body_Shell to degenerate triples.
# They vanish at render time: a genuine hole in the flank, with a known count.
N_HOLE = 3000
g = copy.deepcopy(G); b = bytearray(BIN)
ni = node_by_name(g, 'Body_Shell')
pr = g['meshes'][g['nodes'][ni]['mesh']]['primitives'][0]
base, sz, fmt, cnt = idx_view(g, pr)
st = struct.Struct('<' + fmt)
tri = cnt // 3
start = tri // 3
for t in range(start, start + N_HOLE):
    o = base + t * 3 * sz
    a0 = st.unpack_from(b, o)[0]
    st.pack_into(b, o + sz, a0)
    st.pack_into(b, o + 2 * sz, a0)
emit('C6_hole3000', g, b,
     'Body_Shell: 3000 consecutive triangles collapsed to degenerate',
     {'triangles_removed': N_HOLE, 'expected_degenerate_count_delta': N_HOLE,
      'expected_blender_triangle_drop': N_HOLE})

# ------------------------------------------------------------- C7 mirrored node
# Negative scale on one wheel.  Stage 0 found ZERO mirrored determinants in the
# source and used that to rule out mirroring as the wheel-defect cause; this
# control proves that the determinant test can actually detect one.
g = copy.deepcopy(G)
ni = node_by_name(g, 'Wheel_FR_Rim')
n = g['nodes'][ni]
m = g['meshes'][n['mesh']]
mn, mx = pos_minmax(g, m['primitives'][0])
c = [(mn[k] + mx[k]) / 2.0 for k in range(3)]
t = n.get('translation', [0, 0, 0])
sc_ = n.get('scale', [1, 1, 1])
n['scale'] = [sc_[0], sc_[1], -sc_[2]]
n['translation'] = [t[0], t[1], t[2] + 2 * c[2] * sc_[2]]
emit('C7_mirrored', g, BIN,
     'Wheel_FR_Rim node given a negative Z scale (mirrored determinant)',
     {'mirrored_nodes': 1, 'expected_determinant_sign': -1})

json.dump(REPORT, open(os.path.join(OUT, 'CONTROLS.json'), 'w'), indent=1)
print('\nwrote %d controls to %s' % (len(REPORT['controls']), OUT))
