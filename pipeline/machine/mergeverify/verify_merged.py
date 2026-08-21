"""
verify_merged.py <merged.glb> [outdir]

Runs the whole table against a merged car. Every threshold below was fixed BEFORE
the merged car existed, from measurements on the six source files, so nothing here
is tuned to the answer.

Usage:  python3 verify_merged.py path/to/car_merged_all.glb meta/
"""
import json
import os
import sys
import numpy as np
import glbcore as G
import measure as M
import matcheck as MC
import panel as P
import raycast as RC

# ---- the component inventory each gate is entitled to contribute -------------
BASE_WHEELS = [f'Wheel_{c}_{p}' for c in ('FL', 'FR', 'RL', 'RR')
               for p in ('Tyre', 'Rim', 'Disc')]
GATE78 = BASE_WHEELS + ['Glass_Rear', 'Glass_Windscreen', 'Glass_Side_L', 'Glass_Side_R',
                        'Mirror_L', 'Mirror_R', 'TailLamp_L', 'TailLamp_R', 'Interior',
                        'Arch_Liner', 'Underbody', 'Bumper_Rear_Paint', 'Bumper_Rear_Trim',
                        'Body_Shell']
GLASS_GATE = ['Glass_Quarter_L']
CABIN_GATE = ['Cabin_Floor', 'Cabin_Tunnel', 'Cabin_Dash', 'Cabin_Binnacle', 'Cabin_Wheel',
              'Cabin_Hub', 'Cabin_Spokes', 'Cabin_Column', 'Cabin_Console',
              'Cabin_SeatFD_Cush', 'Cabin_SeatFD_Back', 'Cabin_SeatFD_BolB',
              'Cabin_SeatFD_BolA', 'Cabin_SeatFD_Head', 'Cabin_SeatFP_Cush',
              'Cabin_SeatFP_Back', 'Cabin_SeatFP_BolB', 'Cabin_SeatFP_BolA',
              'Cabin_SeatFP_Head', 'Cabin_BenchCush', 'Cabin_BenchBack',
              'Cabin_BenchHead_R', 'Cabin_BenchHead_L', 'Cabin_ParcelShelf',
              'Cabin_BootFloor', 'Cabin_DoorCard_R', 'Cabin_DoorCard_L', 'Cabin_Headliner']
V7_FRONT = ['Valance_Front', 'Bumper_Front', 'Grille_Upper', 'Grille_Lower',
            'Headlamp_R_Lens', 'Headlamp_R_Housing', 'Headlamp_R_Internal',
            'Headlamp_L_Lens', 'Headlamp_L_Housing', 'Headlamp_L_Internal',
            'DRL_Blade', 'Badge', 'Badge_Mount', 'Plate_Carrier', 'Plate',
            'Intake_R', 'Intake_L', 'Intake_R_Blades', 'Intake_L_Blades', 'TowEye_Cover']
REAR_V2 = ['Hatch', 'Hatch_Inner', 'Bumper_Rear', 'Bumper_Rear_Inner', 'Plate_Rear',
           'Glass_Backlight', 'Tail_Lens_LO', 'Tail_Lens_RO', 'Tail_Lens_LH',
           'Tail_Lens_RH', 'Tail_Housing_LO', 'Tail_Housing_RO', 'Tail_Housing_LH',
           'Tail_Housing_RH']
GATES = dict(gate78=GATE78, glass=GLASS_GATE, cabin=CABIN_GATE, v7=V7_FRONT, rear=REAR_V2)

TYRES = ['Wheel_FL_Tyre', 'Wheel_FR_Tyre', 'Wheel_RL_Tyre', 'Wheel_RR_Tyre']
V7_SYM_PAIRS = [('Headlamp_L_Lens', 'Headlamp_R_Lens'),
                ('Headlamp_L_Housing', 'Headlamp_R_Housing'),
                ('Headlamp_L_Internal', 'Headlamp_R_Internal'),
                ('Intake_L', 'Intake_R'), ('Intake_L_Blades', 'Intake_R_Blades')]
V7_CENTRELINE = ['Badge', 'Plate', 'Plate_Carrier', 'Grille_Upper', 'Grille_Lower',
                 'DRL_Blade', 'Badge_Mount']

# thresholds, fixed in advance
TH = dict(tyre_air_mm=1.0, windscreen_m2=0.90, glazing_area_m2=3.30,
          symmetry_mm=1.0e-3, centreline_mm=1.0e-2, coincidence_pct=1.0,
          validator_errors=0, missing_normals=0,
          tyre_basecolor=(0.017, 0.037), respray_paint_delta=25.0,
          respray_frozen_delta=10.0)


def hierarchy(g):
    present = {}
    for n in g.nodes():
        if n.mesh is None:
            present[n.name] = dict(present=True, faces=0, empty_node=True)
            continue
        f = sum(len(g.prim_indices(n.mesh, p))
                for p in range(len(g.json['meshes'][n.mesh]['primitives'])))
        mats = sorted({(g.json['materials'][g.prim_material(n.mesh, p)].get('name')
                        if g.prim_material(n.mesh, p) is not None else None)
                       for p in range(len(g.json['meshes'][n.mesh]['primitives']))}, key=str)
        present[n.name] = dict(present=True, faces=int(f), empty_node=False, materials=mats)
    rows = {}
    for gate, names in GATES.items():
        miss = [n for n in names if n not in present]
        empty = [n for n in names if n in present and present[n]['faces'] == 0]
        rows[gate] = dict(expected=len(names), found=len(names) - len(miss),
                          missing=miss, empty_or_no_geometry=empty)
    extra = sorted(set(present) - set(sum(GATES.values(), [])))
    # "never a name on a merged mesh": two named nodes pointing at ONE mesh look
    # like two components to a name check and are one component in the file.
    by_mesh = {}
    for n in g.nodes():
        if n.mesh is not None:
            by_mesh.setdefault(n.mesh, []).append(n.name)
    shared = [v for v in by_mesh.values() if len(v) > 1]
    return dict(per_gate=rows, node_count=len(present), extra_nodes=extra,
                nodes_sharing_one_mesh=shared,
                all_nodes={k: v.get('faces') for k, v in present.items()})


def provenance(g, g_src, node_names, tol_m=1e-4):
    """Geometric provenance, NOT node name. A renamed melt component reads 0.0% by
    name and 100% by provenance -- so this is the classifier used everywhere here."""
    from scipy.spatial import cKDTree
    C = []
    for n in g_src.nodes():
        for _mi, Vw, F in g_src.node_world_geom(n):
            if len(F):
                C.append(G.tri_centroids(Vw, F))
    tree = cKDTree(np.vstack(C))
    out = {}
    for nm in node_names:
        V, F = M.node_world_tris(g, nm)
        if V is None:
            out[nm] = None
            continue
        d, _ = tree.query(G.tri_centroids(V, F), k=1)
        out[nm] = dict(faces=int(len(F)), coincident_pct=float(100.0 * (d <= tol_m).mean()),
                       median_d_mm=float(np.median(d) * 1000))
    return out


def main():
    glb = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else '.'
    os.makedirs(outdir, exist_ok=True)
    g = G.Glb(glb)
    R = {'file': glb, 'bytes': os.path.getsize(glb)}
    import hashlib
    R['sha256'] = hashlib.sha256(open(glb, 'rb').read()).hexdigest()

    R['frame'] = M.derive_frame(g)
    R['hierarchy'] = hierarchy(g)
    R['normals'] = MC.normals_audit(g)
    R['materials'] = MC.material_audit(g)
    R['glazing_pair'] = MC.glazing_pair(g)
    R['tyre_material'] = MC.tyre_check(g)
    R['paint_material'] = MC.paint_check(g)
    R['grounding'] = M.tyre_grounding(g, up=1)
    R['glass_node_area_m2'] = M.node_areas(g, prefix='Glass')
    R['glass_node_normals'] = {k: M.node_normal_stats(g, k)
                               for k in R['glass_node_area_m2']}

    # v7 symmetry + centreline, about a mirror plane FITTED to the car.
    #
    # BUG PAID FOR 2026-08-21: this used to mirror about a z = const plane. After the
    # merge applies a 4.73 deg rigid rotation about a TILTED axis, a plane that was
    # z = const is no longer z = const -- and the z-const test reported the v7 kit's
    # symmetry as 50.45 mm when the kit is in fact symmetric to 1.6e-04 mm about its
    # own plane. The plane is now FITTED (normal direction + offset, 3 parameters),
    # so the test measures the car and not my frame assumption.
    from scipy.spatial import cKDTree
    from scipy.optimize import minimize
    pairs = [(a, b) for a, b in V7_SYM_PAIRS
             if M.node_world_verts(g, a) is not None
             and M.node_world_verts(g, b) is not None]
    if pairs:
        L = [M.node_world_verts(g, a) for a, _ in pairs]
        Rv = [M.node_world_verts(g, b) for _, b in pairs]
        trees = [cKDTree(r) for r in Rv]

        def _n(p):
            th, ph, off = p
            n = np.array([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)])
            return n, n * off

        def _cost(p):
            n, p0 = _n(p)
            tot = cnt = 0.0
            for Lv, tr in zip(L, trees):
                Mv = Lv - 2 * ((Lv - p0) @ n)[:, None] * n[None, :]
                d, _ = tr.query(Mv, k=1)
                tot += float((d ** 2).sum()); cnt += len(d)
            return np.sqrt(tot / cnt)
        best = None
        for ph0 in (np.pi / 2 - 0.05, np.pi / 2, np.pi / 2 + 0.05):
            for o0 in (-0.05, 0.0, 0.03):
                r = minimize(_cost, [np.pi / 2, ph0, o0], method='Nelder-Mead',
                             options=dict(xatol=1e-9, fatol=1e-12, maxiter=4000))
                if best is None or r.fun < best.fun:
                    best = r
        n, p0 = _n(best.x)
        R['v7_mirror_plane'] = dict(normal=n.tolist(), offset_mm=float(best.x[2] * 1000),
                                    fit_rms_mm=float(best.fun * 1000),
                                    tilt_from_Z_deg=float(np.degrees(np.arccos(abs(n[2])))))
        sym = {}
        for (a, b), Lv, tr in zip(pairs, L, trees):
            Mv = Lv - 2 * ((Lv - p0) @ n)[:, None] * n[None, :]
            d, _ = tr.query(Mv, k=1)
            sym[f'{a}|{b}'] = dict(max_mm=float(d.max() * 1000), mean_mm=float(d.mean() * 1000))
        R['v7_symmetry'] = sym
        R['v7_centreline_offset_mm'] = {}
        for nm in V7_CENTRELINE:
            V = M.node_world_verts(g, nm)
            if V is None:
                continue
            sd = (V - p0) @ n
            R['v7_centreline_offset_mm'][nm] = float(((sd.min() + sd.max()) / 2) * 1000)

    # rear panel waviness, like-for-like, at the radius sweep used on the source
    R['waviness'] = {}
    for nm in ['Hatch', 'Bumper_Rear', 'Body_Shell', 'Bumper_Front']:
        V, F = M.node_world_tris(g, nm)
        if V is None:
            continue
        for r in (0.020, 0.030):
            w = P.waviness(V[np.unique(F)], radius_m=r, sample=4000)
            R['waviness'][f'{nm}@{int(r*1000)}mm'] = w.get('rms_mm')

    # provenance of everything a gate says it BUILT
    src = os.environ.get('SRC_GLB', 'src/car_rebound.glb')
    if os.path.exists(src):
        want = [n for n in (V7_FRONT + REAR_V2 + CABIN_GATE)
                if n in R['hierarchy']['all_nodes']]
        R['provenance_vs_source'] = provenance(g, G.Glb(src), want)

    json.dump(R, open(os.path.join(outdir, 'verify_merged.json'), 'w'), indent=1)
    print(json.dumps({k: R[k] for k in ('file', 'sha256', 'bytes')}))
    print('VERIFY_MERGED_EXIT=0')


if __name__ == '__main__':
    main()
