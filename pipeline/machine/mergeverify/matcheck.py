"""
matcheck.py -- the four must-not-break material properties, read from the WRITTEN
glTF material table.

Why not glass_probe: two agents proved independently on 2026-08-21 that it passes a
car whose windscreen aperture is `carpaint`, and passes a control whose glazing
GEOMETRY was cut to 2.5% of its area with the table untouched. It reads the TABLE and
never asks how much SURFACE carries it. So the glazing verdict here is always a PAIR:
(material is transparent) AND (glazing area retained). Separately, trimesh drops every
KHR extension on a round-trip, so the extension block is read from the file's own JSON
and never from a re-export.
"""
import numpy as np
from glbcore import Glb, tri_areas

GLASSY = ('glass', 'window', 'windscreen', 'windshield', 'screen', 'glazing', 'backlight')


def normals_audit(g):
    tot = bad = miss = nonunit = 0
    for mi, m in enumerate(g.json.get('meshes', [])):
        for pi, pr in enumerate(m['primitives']):
            tot += 1
            if 'NORMAL' not in pr['attributes']:
                miss += 1
                continue
            N = g.accessor(pr['attributes']['NORMAL'])
            ln = np.linalg.norm(N, axis=1)
            nz = int((ln < 1e-6).sum())
            nu = int((np.abs(ln - 1.0) > 1e-3).sum())
            bad += nz
            nonunit += nu
    return dict(primitives=tot, missing_NORMAL=miss,
                zero_length_normals=bad, non_unit_normals=nonunit)


def material_audit(g):
    js = g.json
    out = {'extensionsUsed': js.get('extensionsUsed'), 'materials': {}}
    for i, m in enumerate(js.get('materials', [])):
        pbr = m.get('pbrMetallicRoughness', {})
        ext = m.get('extensions', {}) or {}
        bcf = pbr.get('baseColorFactor', [1, 1, 1, 1])
        out['materials'][m.get('name', f'mat{i}')] = dict(
            index=i,
            baseColorFactor=bcf,
            alpha=bcf[3] if len(bcf) > 3 else 1.0,
            metallic=pbr.get('metallicFactor', 1.0),
            roughness=pbr.get('roughnessFactor', 1.0),
            alphaMode=m.get('alphaMode', 'OPAQUE'),
            extensions=sorted(ext.keys()),
            transmission=(ext.get('KHR_materials_transmission') or {}).get('transmissionFactor'),
            ior=(ext.get('KHR_materials_ior') or {}).get('ior'),
            clearcoat=(ext.get('KHR_materials_clearcoat') or {}).get('clearcoatFactor'),
            doubleSided=m.get('doubleSided', False),
            hasTexture='baseColorTexture' in pbr)
    return out


def glazing_pair(g):
    """The combined verdict: transparent material AND how much AREA carries it."""
    import measure as M
    ma = M.material_area(g)
    mats = material_audit(g)['materials']
    glass_names = [n for n in mats if any(k in n.lower() for k in GLASSY)]
    tot = sum(ma.values())
    rows = {}
    for n in glass_names:
        d = mats[n]
        transparent = (d['alphaMode'] in ('BLEND', 'MASK') and d['alpha'] < 1.0) \
            or (d['transmission'] not in (None, 0))
        rows[n] = dict(area_m2=ma.get(n, 0.0), transparent=bool(transparent),
                       alphaMode=d['alphaMode'], alpha=d['alpha'],
                       transmission=d['transmission'], ior=d['ior'])
    return dict(glazing_materials=rows,
                glazing_area_m2=float(sum(r['area_m2'] for r in rows.values())),
                total_area_m2=float(tot),
                glazing_pct_of_area=float(100.0 * sum(r['area_m2'] for r in rows.values())
                                          / tot) if tot else 0.0)


def tyre_check(g, expect=0.027, tol=0.010):
    mats = material_audit(g)['materials']
    out = {}
    for n, d in mats.items():
        if 'tyre' in n.lower() or 'tire' in n.lower() or 'rubber' in n.lower():
            L = float(np.mean(d['baseColorFactor'][:3]))
            out[n] = dict(mean_baseColor=L, within_tol=bool(abs(L - expect) <= tol),
                          metallic=d['metallic'], roughness=d['roughness'])
    return out


def paint_check(g):
    mats = material_audit(g)['materials']
    out = {}
    for n, d in mats.items():
        if 'carpaint' in n.lower() or n.lower() == 'paint':
            out[n] = dict(baseColorFactor=d['baseColorFactor'], metallic=d['metallic'],
                          roughness=d['roughness'], clearcoat=d['clearcoat'],
                          # the recorded flat-shell trap: glTF DEFAULTS metallic=1 rough=1
                          hasTexture=d['hasTexture'],
                          # CORRECTED 2026-08-21. The flat-shell signature is
                          # [1,1,1,1]/metallic 1/rough 1 on an UNTEXTURED material.
                          # On a TEXTURED one those factors are the neutral MULTIPLIER
                          # and are correct -- CLAUDE.md records exactly this trap for
                          # the tyre probe ("the factor on a textured material is a
                          # MULTIPLIER and is [1,1,1] on nearly all of them"). Calling
                          # a textured car flat invents a defect.
                          looks_like_gltf_defaults=bool(
                              (not d['hasTexture'])
                              and d['metallic'] == 1.0 and d['roughness'] == 1.0
                              and list(d['baseColorFactor']) == [1, 1, 1, 1]))
    return out
