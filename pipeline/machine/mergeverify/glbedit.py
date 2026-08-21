"""
glbedit.py -- minimal GLB rewriter used ONLY to build NEGATIVE CONTROLS.

A check that has never returned a failure is not a check. These controls are real
files with a real defect injected, so every check is run end-to-end through the same
code path that judges the production car -- not a unit test on the estimator, which
is the failure mode CLAUDE.md records for wheel_angle_calib ("a unit test on the
fitter would have passed, because the fitter was never the problem").

New data is APPENDED to the BIN chunk and referenced by new bufferViews, so nothing
that is not being deliberately broken changes by even a byte.
"""
import json
import struct
import copy
import numpy as np
from glbcore import Glb


class Editor:
    def __init__(self, path):
        g = Glb(path)
        self.js = copy.deepcopy(g.json)
        self.bin = bytearray(g.bin)
        self._g = g

    def _append(self, data: bytes):
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin.extend(data)
        self.js.setdefault('bufferViews', []).append(
            dict(buffer=0, byteOffset=off, byteLength=len(data)))
        return len(self.js['bufferViews']) - 1

    def set_indices(self, mesh, prim, F):
        F = np.asarray(F, np.uint32).reshape(-1, 3)
        bv = self._append(F.tobytes())
        self.js.setdefault('accessors', []).append(
            dict(bufferView=bv, componentType=5125, count=int(F.size),
                 type='SCALAR', min=[int(F.min())], max=[int(F.max())]))
        self.js['meshes'][mesh]['primitives'][prim]['indices'] = len(self.js['accessors']) - 1

    def node_index(self, name):
        for i, n in enumerate(self.js.get('nodes', [])):
            if n.get('name') == name:
                return i
        raise KeyError(name)

    def translate_node(self, name, delta):
        i = self.node_index(name)
        n = self.js['nodes'][i]
        if 'matrix' in n:
            M = np.array(n['matrix'], float).reshape(4, 4)   # column-major
            M[3, :3] = M[3, :3] + np.asarray(delta, float)
            n['matrix'] = M.reshape(-1).tolist()
        else:
            t = np.array(n.get('translation', [0, 0, 0]), float) + np.asarray(delta, float)
            n['translation'] = t.tolist()

    def strip_extensions(self):
        self.js.pop('extensionsUsed', None)
        self.js.pop('extensionsRequired', None)
        for m in self.js.get('materials', []):
            m.pop('extensions', None)

    def drop_normals(self, mesh=None):
        n = 0
        for mi, m in enumerate(self.js.get('meshes', [])):
            if mesh is not None and mi != mesh:
                continue
            for pr in m['primitives']:
                if pr['attributes'].pop('NORMAL', None) is not None:
                    n += 1
        return n

    def set_material_value(self, name, **kw):
        for m in self.js.get('materials', []):
            if m.get('name') == name:
                pbr = m.setdefault('pbrMetallicRoughness', {})
                for k, v in kw.items():
                    if k in ('baseColorFactor', 'metallicFactor', 'roughnessFactor'):
                        pbr[k] = v
                    else:
                        m[k] = v
                return True
        return False

    def repoint_material(self, node_name, new_material_name):
        """Bind every primitive of `node_name` to the material called
        `new_material_name` -- e.g. paint a windscreen with carpaint."""
        i = self.node_index(node_name)
        mi = self.js['nodes'][i]['mesh']
        target = None
        for k, m in enumerate(self.js['materials']):
            if m.get('name') == new_material_name:
                target = k
        assert target is not None, new_material_name
        for pr in self.js['meshes'][mi]['primitives']:
            pr['material'] = target

    def write(self, path):
        j = json.dumps(self.js, separators=(',', ':')).encode('utf-8')
        j += b' ' * ((4 - len(j) % 4) % 4)
        b = bytes(self.bin)
        b += b'\0' * ((4 - len(b) % 4) % 4)
        total = 12 + 8 + len(j) + 8 + len(b)
        with open(path, 'wb') as f:
            f.write(struct.pack('<III', 0x46546C67, 2, total))
            f.write(struct.pack('<II', len(j), 0x4E4F534A)); f.write(j)
            f.write(struct.pack('<II', len(b), 0x004E4942)); f.write(b)
        return path


def keep_fraction_of_node(src, dst, node_name, frac, seed=0):
    """Delete (1-frac) of a node's triangles, leaving the material table untouched.
    This is the control that shows glass_probe passing a car with no glass in it."""
    ed = Editor(src)
    g = ed._g
    ni = ed.node_index(node_name)
    mi = ed.js['nodes'][ni]['mesh']
    for pi in range(len(ed.js['meshes'][mi]['primitives'])):
        F = g.prim_indices(mi, pi)
        k = max(1, int(round(len(F) * frac)))
        idx = np.random.default_rng(seed).choice(len(F), k, replace=False)
        ed.set_indices(mi, pi, F[np.sort(idx)])
    return ed.write(dst)
