import sys, math, numpy as np
sys.path.insert(0, 'pipeline/template')
import photoproj as pp
from morph import collect, measure
from gltf import GLTF
g = GLTF(sys.argv[1])
parts = collect(g)
tris = []
for pt in parts:
    if not pt['name'].startswith(('Ext', 'ExtBody', 'Panel_', 'Asm_', 'Tire')): continue
    for p, P in pt['prims']:
        mat = g.j['materials'][p.get('material', 0)]
        if mat.get('alphaMode') == 'BLEND' or 'indices' not in p: continue
        tris.append(P[g.accessor(p['indices']).reshape(-1, 3)])
tris = np.concatenate(tris)
target = np.array([0.0, 0.6, (tris[:, :, 2].max() + tris[:, :, 2].min()) / 2])
truth = np.array([math.radians(-40), math.radians(8), math.log(6.5), math.log(1.2), 0.02, 0.03, 0.0])
W, H = 960, 560
xy, z, _ = pp.project(tris.reshape(-1, 3), {'p': truth, 'target': target}, W, H)
mask = pp.raster(xy.reshape(-1, 3, 2), W, H)
log = {}
cam = pp.fit_camera(tris, mask, 'front', log)
cam['overlay'].save(sys.argv[2])
print('truth az %.1f el %.1f D %.2f F %.2f' % (math.degrees(truth[0]), math.degrees(truth[1]), math.exp(truth[2]), math.exp(truth[3])))
print('found', log)
