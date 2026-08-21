"""
glbcore.py -- INDEPENDENT VERIFIER core reader for the merged Golf Mk8.

Design rules (each one is a lesson already paid for in CLAUDE.md):
  * Parse the GLB container and its JSON chunk DIRECTLY. Never round-trip through
    trimesh: trimesh silently drops every KHR material extension on any glTF
    round-trip (transmission / IOR / clearcoat vanish while alphaMode survives),
    so a probe run on a re-exported file reports on a file nobody ships.
  * Every position is a WORLD-SPACE position -- node-local minima gave
    -0.3067/-0.3241 where world space gives FL +183.2 mm. Compose the full node
    chain transform and apply it.
  * Never select geometry by material NAME alone and never by face normal.
    Selection is by NODE, and a node's identity is checked against its geometry.

Public API
  Glb(path)                 -- parsed container
    .json                   -- the raw glTF JSON dict (authoritative material table)
    .nodes()                -- [NodeInfo] flattened scene graph with world matrices
    .prim_positions(m,p)    -- (V,3) float64 LOCAL positions for mesh m primitive p
    .prim_indices(m,p)      -- (F,3) int64
    .prim_normals(m,p)      -- (V,3) or None
"""
import json
import struct
import numpy as np

COMP = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2),
        5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4,
         'MAT2': 4, 'MAT3': 9, 'MAT4': 16}
DT = {5120: np.int8, 5121: np.uint8, 5122: np.int16,
      5123: np.uint16, 5125: np.uint32, 5126: np.float32}


class NodeInfo:
    __slots__ = ('idx', 'name', 'mesh', 'world', 'parent', 'path')

    def __init__(self, idx, name, mesh, world, parent, path):
        self.idx, self.name, self.mesh = idx, name, mesh
        self.world, self.parent, self.path = world, parent, path

    def __repr__(self):
        return f'<Node {self.idx} {self.name!r} mesh={self.mesh}>'


def _trs(node):
    """glTF node -> 4x4 float64. matrix wins if present, else T*R*S."""
    if 'matrix' in node:
        return np.array(node['matrix'], dtype=np.float64).reshape(4, 4).T
    M = np.eye(4)
    if 'scale' in node:
        M = np.diag(list(node['scale']) + [1.0]) @ M
    if 'rotation' in node:
        x, y, z, w = node['rotation']
        R = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
            [0, 0, 0, 1]], dtype=np.float64)
        M = R @ M
    if 'translation' in node:
        T = np.eye(4)
        T[:3, 3] = node['translation']
        M = T @ M
    return M


class Glb:
    def __init__(self, path):
        self.path = str(path)
        with open(path, 'rb') as f:
            magic, ver, total = struct.unpack('<III', f.read(12))
            assert magic == 0x46546C67, f'not a GLB: {path}'
            self.json = None
            self.bin = None
            while f.tell() < total:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                clen, ctype = struct.unpack('<II', hdr)
                data = f.read(clen)
                if ctype == 0x4E4F534A:
                    self.json = json.loads(data.decode('utf-8'))
                elif ctype == 0x004E4942:
                    self.bin = data
        assert self.json is not None
        self._acc_cache = {}

    # ---------- accessors ----------
    def accessor(self, i):
        if i in self._acc_cache:
            return self._acc_cache[i]
        a = self.json['accessors'][i]
        n = NCOMP[a['type']]
        count = a['count']
        dt = DT[a['componentType']]
        if 'bufferView' not in a:
            out = np.zeros((count, n), dtype=np.float64)
        else:
            bv = self.json['bufferViews'][a['bufferView']]
            off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
            stride = bv.get('byteStride')
            esz = COMP[a['componentType']][1]
            if stride is None or stride == esz * n:
                raw = np.frombuffer(self.bin, dtype=dt, count=count * n, offset=off)
                out = raw.reshape(count, n).astype(np.float64)
            else:  # interleaved
                rows = np.frombuffer(self.bin, dtype=np.uint8,
                                     count=stride * count, offset=off)
                rows = rows.reshape(count, stride)[:, :esz * n].copy()
                out = rows.view(dt).reshape(count, n).astype(np.float64)
            if a.get('normalized'):
                mx = {np.int8: 127., np.uint8: 255., np.int16: 32767.,
                      np.uint16: 65535.}.get(dt)
                if mx:
                    out = np.maximum(out / mx, -1.0)
        # sparse
        if 'sparse' in a:
            sp = a['sparse']
            ib = self.json['bufferViews'][sp['indices']['bufferView']]
            idt = DT[sp['indices']['componentType']]
            io = ib.get('byteOffset', 0) + sp['indices'].get('byteOffset', 0)
            sidx = np.frombuffer(self.bin, dtype=idt, count=sp['count'], offset=io)
            vb = self.json['bufferViews'][sp['values']['bufferView']]
            vo = vb.get('byteOffset', 0) + sp['values'].get('byteOffset', 0)
            sval = np.frombuffer(self.bin, dtype=dt, count=sp['count'] * n,
                                 offset=vo).reshape(sp['count'], n)
            out = out.copy()
            out[sidx] = sval
        if n == 1:
            out = out.reshape(-1)
        self._acc_cache[i] = out
        return out

    # ---------- primitives ----------
    def prim_positions(self, m, p):
        pr = self.json['meshes'][m]['primitives'][p]
        return self.accessor(pr['attributes']['POSITION'])

    def prim_normals(self, m, p):
        pr = self.json['meshes'][m]['primitives'][p]
        if 'NORMAL' not in pr['attributes']:
            return None
        return self.accessor(pr['attributes']['NORMAL'])

    def prim_indices(self, m, p):
        pr = self.json['meshes'][m]['primitives'][p]
        if 'indices' not in pr:
            n = len(self.prim_positions(m, p))
            return np.arange(n, dtype=np.int64).reshape(-1, 3)
        return self.accessor(pr['indices']).astype(np.int64).reshape(-1, 3)

    def prim_material(self, m, p):
        return self.json['meshes'][m]['primitives'][p].get('material')

    # ---------- scene graph ----------
    def nodes(self):
        js = self.json
        out = []
        scene = js.get('scenes', [{}])[js.get('scene', 0)]
        roots = scene.get('nodes', list(range(len(js.get('nodes', [])))))

        def walk(i, parentM, parent, path):
            nd = js['nodes'][i]
            W = parentM @ _trs(nd)
            nm = nd.get('name', f'node{i}')
            pth = path + '/' + nm
            out.append(NodeInfo(i, nm, nd.get('mesh'), W, parent, pth))
            for c in nd.get('children', []):
                walk(c, W, i, pth)
        for r in roots:
            walk(r, np.eye(4), None, '')
        return out

    # ---------- world geometry per node ----------
    def node_world_geom(self, node):
        """-> list of (material_index, V_world(N,3), F(M,3))"""
        res = []
        if node.mesh is None:
            return res
        R, t = node.world[:3, :3], node.world[:3, 3]
        for p in range(len(self.json['meshes'][node.mesh]['primitives'])):
            V = self.prim_positions(node.mesh, p)
            F = self.prim_indices(node.mesh, p)
            Vw = V @ R.T + t
            res.append((self.prim_material(node.mesh, p), Vw, F))
        return res

    def material_names(self):
        return [m.get('name', f'mat{i}')
                for i, m in enumerate(self.json.get('materials', []))]


def tri_areas(V, F):
    a = V[F[:, 1]] - V[F[:, 0]]
    b = V[F[:, 2]] - V[F[:, 0]]
    return 0.5 * np.linalg.norm(np.cross(a, b), axis=1)


def tri_centroids(V, F):
    return V[F].mean(axis=1)
