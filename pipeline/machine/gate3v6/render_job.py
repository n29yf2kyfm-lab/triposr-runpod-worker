"""GATE 3 v6 — job runner (Blender side).

    blender -b --noaudio --python render_job.py -- <job.json>

Executes every view in the job against ONE imported GLB, in one Blender
process, so the scene import and BVH are paid for once.

Writes <outdir>/<id>.png for every view, <outdir>/_meta_<jobname>.json with the
measured camera parameters and label projections, and finally the DONE marker.
GREP FOR THE DONE MARKER, never for Blender's exit - this container has no
OpenImageDenoiser and a failed render dies AFTER "Blender quit" prints.
"""
import bpy, json, math, os, sys, time
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rig
from rig import (log, wipe_scene, import_glb, world_verts, scene_points,
                 make_principled, make_emission, make_normal_mat, make_wire_mat,
                 make_mask_mat, id_palette, assign_all, assign_per_object,
                 studio_lights, strip_lights, add_ground, clear_lights,
                 make_camera, project_extent, fit_ortho, render_settings,
                 render_to, NEUTRAL_MATTE, CLAY, ZEBRA_SURF)


def gltf_to_blender_pt(p):
    """glTF (x,y,z) -> Blender (x,-z,y)."""
    return (p[0], -p[2], p[1])


def run(job):
    glb = job["glb"]
    outdir = job["outdir"]
    os.makedirs(outdir, exist_ok=True)
    name = job.get("name", "job")

    wipe_scene()
    objs = import_glb(glb)
    by_name = {}
    for o in objs:
        by_name.setdefault(o.name.split(".")[0], []).append(o)
    orig_mats = {o.name: [m for m in o.data.materials] for o in objs}
    orig_loc = {o.name: tuple(o.location) for o in objs}

    allpts = scene_points(objs, stride=1)
    lo, hi = allpts.min(0), allpts.max(0)
    centre = (lo + hi) / 2.0
    diag = float(np.linalg.norm(hi - lo))
    log("blender bbox lo=%s hi=%s diag=%.4f" % (np.round(lo, 4), np.round(hi, 4), diag))
    # sample for framing (fast, still exact enough - max 400k pts)
    stride = max(1, len(allpts) // 400000)
    fitpts = allpts[::stride]

    meta = {"glb": glb, "glb_bytes": os.path.getsize(glb),
            "blender_bbox_lo": lo.tolist(), "blender_bbox_hi": hi.tolist(),
            "diag": diag, "views": {}}

    for view in job["views"]:
        t0 = time.time()
        vid = view["id"]
        res_x, res_y = view.get("res", [2560, 2048])
        samples = view.get("samples", 48)
        pss = view["pass"]
        flat = pss in ("matid", "mask", "normals", "wire", "explode_id")

        # ---- restore scene state -------------------------------------
        for o in objs:
            o.hide_render = False
            o.location = orig_loc[o.name]
        for o in list(bpy.context.scene.objects):
            if o.name == "GROUND":
                bpy.data.objects.remove(o, do_unlink=True)

        only = view.get("only")
        hide = set(view.get("hide", []))
        for o in objs:
            base = o.name.split(".")[0]
            if only is not None and base not in only:
                o.hide_render = True
            if base in hide:
                o.hide_render = True
        vis = [o for o in objs if not o.hide_render]

        # ---- explode --------------------------------------------------
        labels = []
        exp = view.get("explode")
        if exp:
            axis = np.array(exp.get("axis_blender", [-1, 0, 0]), dtype=float)
            axis /= np.linalg.norm(axis)
            spacing = exp["spacing"]
            ranks = exp["ranks"]          # {objname: rank}
            for o in vis:
                base = o.name.split(".")[0]
                r = ranks.get(base)
                if r is None:
                    continue
                d = axis * (spacing * r)
                o.location = (orig_loc[o.name][0] + d[0],
                              orig_loc[o.name][1] + d[1],
                              orig_loc[o.name][2] + d[2])
            bpy.context.view_layer.update()

        # ---- materials -------------------------------------------------
        if pss in ("matte", "beauty"):
            assign_all(vis, make_principled("M_%s" % vid, **NEUTRAL_MATTE))
        elif pss == "clay":
            assign_all(vis, make_principled("C_%s" % vid, **CLAY))
        elif pss == "zebra":
            assign_all(vis, make_principled("Z_%s" % vid, **ZEBRA_SURF))
        elif pss == "normals":
            assign_all(vis, make_normal_mat("N_%s" % vid))
        elif pss == "wire":
            assign_all(vis, make_wire_mat("W_%s" % vid, view.get("wire_px", 0.9)))
        elif pss == "mask":
            assign_all(vis, make_mask_mat())
        elif pss in ("matid", "explode_id"):
            keys = sorted({o.name.split(".")[0] for o in vis})
            pal = id_palette(len(keys))
            cmap = dict(zip(keys, pal))
            mats = {k: make_emission("ID_%s_%s" % (vid, k), cmap[k]) for k in keys}
            for o in vis:
                o.data.materials.clear()
                o.data.materials.append(mats[o.name.split(".")[0]])
            meta.setdefault("id_colours", {})[vid] = {
                k: [round(c, 4) for c in cmap[k]] for k in keys}

        # ---- render settings + world ------------------------------------
        wg = view.get("world_grey", 0.22)
        transparent = (pss == "mask")
        render_settings(res_x, res_y, samples, flat=flat, world_grey=wg,
                        transparent=transparent)

        # ---- lights + ground -------------------------------------------
        if flat:
            clear_lights()
        elif pss == "zebra":
            strip_lights(centre, diag, n_strips=view.get("n_strips", 22))
        else:
            studio_lights(centre, diag, bright=view.get("bright", 1.0))

        if view.get("ground", False) and not flat:
            add_ground(centre, diag, float(lo[2]) - 0.002,
                       grey=view.get("ground_grey", 0.30))

        # ---- camera ------------------------------------------------------
        az = view["az"]
        elev = view.get("elev", 0.0)
        ty = view.get("target_y_gltf")
        tgt = (float(centre[0]), float(centre[1]),
               float(ty) if ty is not None else float(centre[2]))
        if view.get("target_x_gltf") is not None:
            tgt = (float(view["target_x_gltf"]), tgt[1], tgt[2])
        if view.get("target_z_gltf") is not None:
            tgt = (tgt[0], -float(view["target_z_gltf"]), tgt[2])
        radius = diag * view.get("radius_mult", 3.0)

        if view.get("cam", "ortho") == "ortho":
            cam = make_camera("CAM_%s" % vid, az, elev, tgt, radius, ortho_scale=10.0)
            fitset = view.get("fit_objects")
            if view.get("ortho_scale"):
                cam.data.ortho_scale = float(view["ortho_scale"])
                if view.get("shift"):
                    cam.data.shift_x, cam.data.shift_y = view["shift"]
            else:
                if fitset:
                    fp = scene_points([o for o in vis
                                       if o.name.split(".")[0] in set(fitset)])
                else:
                    fp = scene_points(vis, stride=stride)
                fit_ortho(cam, fp, res_x, res_y, view.get("occ", 0.80))
            # For the symmetry overlay the optical axis must pass EXACTLY through
            # the mirror plane (glTF z=0), otherwise a mirrored image is compared
            # against a shifted one and every car looks asymmetric.
            if view.get("no_shift_x"):
                cam.data.shift_x = 0.0
            if view.get("no_shift_y"):
                cam.data.shift_y = 0.0
        else:
            cam = make_camera("CAM_%s" % vid, az, elev, tgt, radius,
                              lens=view.get("lens", 85.0))

        # optional section cut (near-plane slice)
        sec = view.get("section_gltf_z")
        if sec is not None:
            yb = -float(sec)
            cam.data.clip_start = max(0.001, (yb - cam.location[1]))

        bpy.context.view_layer.update()

        # ---- record camera params + label projections ---------------------
        vpts = scene_points(vis, stride=max(1, stride))
        u0, v0, u1, v1 = project_extent(cam, vpts, res_x, res_y)
        if exp:
            for o in vis:
                base = o.name.split(".")[0]
                if base not in exp["ranks"]:
                    continue
                w = world_verts(o)
                c = w.mean(0)[None, :]
                cu, cv, _, _ = project_extent(cam, c, res_x, res_y)
                labels.append({"name": base, "u": cu, "v": cv})

        vmeta = {"pass": pss, "az": az, "elev": elev, "res": [res_x, res_y],
                 "samples": samples,
                 "cam_type": cam.data.type,
                 "ortho_scale": float(cam.data.ortho_scale) if cam.data.type == "ORTHO" else None,
                 "lens_mm": float(cam.data.lens) if cam.data.type == "PERSP" else None,
                 "cam_loc_blender": [round(float(x), 5) for x in cam.location],
                 "target_blender": [round(float(x), 5) for x in tgt],
                 "target_y_gltf": tgt[2],
                 "shift": [float(cam.data.shift_x), float(cam.data.shift_y)],
                 "world_grey": wg,
                 "view_transform": bpy.context.scene.view_settings.view_transform,
                 "proj_extent_ndc": [u0, v0, u1, v1],
                 "proj_bbox_occ_x": round(u1 - u0, 5),
                 "proj_bbox_occ_y": round(v1 - v0, 5),
                 "labels": labels,
                 "n_visible_objects": len(vis)}

        # ---- exposure: MEASURED, never assumed --------------------------
        # A 0.22 world background must land at sRGB ~130. AgX is never used.
        # For lit passes a small alpha probe sets the stops so the brightest car
        # surface lands just under clipping; the same probe yields the exact
        # silhouette coverage used for the populated / occupancy assertions.
        if not flat:
            probe = rig.auto_exposure(os.path.join(outdir, "_probe_%s.png" % vid),
                                      res_x, res_y,
                                      target_lin=view.get("target_peak_linear", 0.85),
                                      probe_px=view.get("probe_px", 384))
            vmeta["exposure"] = probe
        else:
            bpy.context.scene.view_settings.exposure = 0.0
            vmeta["exposure"] = {"exposure_stops": 0.0, "note": "flat pass, no tone mapping needed"}

        path = os.path.join(outdir, "%s.png" % vid)
        render_to(path)
        vmeta["file"] = os.path.basename(path)
        # background sRGB for the given linear world grey, Standard transform
        b = int(round(255.0 * (1.055 * (wg ** (1 / 2.4)) - 0.055))) if wg > 0.0031308 \
            else int(round(255.0 * 12.92 * wg))
        vmeta["expected_bg_srgb"] = b
        try:
            vmeta["measured"] = rig.measure_render(path, bg_srgb=[b, b, b])
        except Exception as e:
            vmeta["measured"] = {"error": str(e)}
        vmeta["seconds"] = round(time.time() - t0, 1)
        meta["views"][vid] = vmeta
        with open(os.path.join(outdir, "_meta_%s.json" % name), "w") as f:
            json.dump(meta, f, indent=1)

        # restore materials for the next view
        for o in objs:
            o.data.materials.clear()
            for m in orig_mats[o.name]:
                o.data.materials.append(m)

    with open(os.path.join(outdir, "_meta_%s.json" % name), "w") as f:
        json.dump(meta, f, indent=1)
    marker = job.get("done_marker", os.path.join(outdir, "_DONE_%s" % name))
    with open(marker, "w") as f:
        f.write("RIG_DONE %s %d views %s\n" % (name, len(job["views"]),
                                               time.strftime("%Y-%m-%dT%H:%M:%S")))
    log("RIG_DONE %s" % name)


if __name__ == "__main__":
    a = rig.argv_after_dashes()
    with open(a[0]) as f:
        job = json.load(f)
    run(job)
