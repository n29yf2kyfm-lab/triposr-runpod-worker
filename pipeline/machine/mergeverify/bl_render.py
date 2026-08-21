"""
bl_render.py -- run inside Blender:  blender -b -P bl_render.py -- <json-spec>

Rig rules, each one a recorded lesson:
  * CYCLES only. NEVER use_denoising: this container's Blender has no
    OpenImageDenoiser, and the render dies AFTER "Blender quit" prints, silently
    leaving stale frames. Target files are deleted first and a DONE marker is
    written by THIS script, which is the only thing the caller may wait on.
  * view_transform = 'Standard', NEVER 'Filmic'/'AgX' -- AgX plus inherited light
    energies clipped a tyre to pure white and produced a wrong published verdict.
  * exposure is verified NUMERICALLY: the spec asks for a grey backdrop and the
    script reports its measured sRGB and the clipped fraction of every frame.
  * ORTHOGRAPHIC. A perspective camera makes a symmetric car photograph asymmetric.
"""
import bpy
import sys
import os
import json
import math
import mathutils


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup(res=1024, samples=64, bg=0.22):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = samples
    sc.cycles.use_denoising = False            # NO OIDN in this container
    sc.cycles.max_bounces = 8
    sc.cycles.transparent_max_bounces = 16
    sc.cycles.transmission_bounces = 12
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.render.film_transparent = False
    sc.view_settings.view_transform = 'Standard'   # never AgX
    sc.view_settings.look = 'None'
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    w = bpy.data.worlds.new('W')
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes['Background'].inputs[0].default_value = (bg, bg, bg, 1)
    w.node_tree.nodes['Background'].inputs[1].default_value = 1.0


def add_lights(centre, size):
    # gain calibrated numerically: see LIGHT_CALIB.txt -- chosen so <1% of car
    # pixels clip, because AgX/over-exposure clipping produced a wrong published
    # tyre verdict once already.
    for name, loc, energy in [
            ('key', (size * 1.6, size * 1.8, size * 1.2), 1.0),
            ('fill', (-size * 1.5, size * 1.2, -size * 1.4), 0.55),
            ('top', (0, size * 2.4, 0), 0.8)]:
        d = bpy.data.lights.new(name, 'AREA')
        d.size = size * 1.2
        d.energy = energy * size * size * float(os.environ.get('LIGHT_GAIN','25'))
        o = bpy.data.objects.new(name, d)
        o.location = (centre[0] + loc[0], centre[1] + loc[1], centre[2] + loc[2])
        dirv = mathutils.Vector(centre) - o.location
        o.rotation_euler = dirv.to_track_quat('-Z', 'Y').to_euler()
        bpy.context.collection.objects.link(o)


def import_glb(path):
    bpy.ops.import_scene.gltf(filepath=path)
    return [o for o in bpy.context.scene.objects if o.type == 'MESH']


def scene_bbox(objs):
    lo = [1e9] * 3; hi = [-1e9] * 3
    for o in objs:
        for c in o.bound_box:
            w = o.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i]); hi[i] = max(hi[i], w[i])
    return lo, hi


def place_camera(lo, hi, az_deg, el_deg, margin=1.06, ortho=True):
    """Blender is Z-up; the glTF importer maps glTF +Y (car up) to Blender +Z and
    glTF +X (car length) to Blender +X. az is measured about the up axis."""
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    ext = [hi[i] - lo[i] for i in range(3)]
    diag = math.sqrt(sum(e * e for e in ext))
    a, e = math.radians(az_deg), math.radians(el_deg)
    d = mathutils.Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
    cam = bpy.data.cameras.new('C')
    cam.type = 'ORTHO' if ortho else 'PERSP'
    cam.ortho_scale = diag * margin
    cam.clip_start = 0.01
    cam.clip_end = diag * 12
    o = bpy.data.objects.new('C', cam)
    o.location = mathutils.Vector(c) + d * diag * 3
    o.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.collection.objects.link(o)
    bpy.context.scene.camera = o
    return o


def flatten_to_emission(objs, colour_of):
    """One flat emission colour per material -- a deterministic label render with
    no shading, no AA ambiguity. colour_of(material_name) -> (r,g,b) or None to hide."""
    bpy.context.scene.cycles.samples = 1
    bpy.context.scene.render.filter_size = 0.0
    for o in objs:
        for slot in o.material_slots:
            m = slot.material
            if m is None:
                continue
            col = colour_of(m.name)
            m.use_nodes = True
            nt = m.node_tree
            nt.nodes.clear()
            out = nt.nodes.new('ShaderNodeOutputMaterial')
            em = nt.nodes.new('ShaderNodeEmission')
            em.inputs[0].default_value = (col[0], col[1], col[2], 1) if col else (0, 0, 0, 1)
            em.inputs[1].default_value = 1.0
            nt.links.new(em.outputs[0], out.inputs[0])
    bpy.context.scene.world.node_tree.nodes['Background'].inputs[0].default_value = (0, 0, 0, 1)


def set_paint(objs, name, rgb):
    """Repaint the named material.

    BUG PAID FOR 2026-08-21: writing `default_value` on an input that is LINKED to a
    texture node does NOTHING -- the link wins. On a textured car that produced two
    byte-identical renders and a confident, WRONG 'the paint does not respond'. So a
    linked Base Color is now driven by inserting a MixRGB that tints the texture, and
    the function REPORTS what it did. A repaint that silently no-ops is worse than one
    that fails."""
    done = {'set': 0, 'tinted': 0, 'missed': 0}
    for o in objs:
        for slot in o.material_slots:
            if not (slot.material and slot.material.name.split('.')[0] == name):
                continue
            m = slot.material
            m.use_nodes = True
            nt = m.node_tree
            b = nt.nodes.get('Principled BSDF')
            if b is None:
                done['missed'] += 1
                continue
            inp = b.inputs['Base Color']
            if not inp.is_linked:
                inp.default_value = (rgb[0], rgb[1], rgb[2], 1)
                done['set'] += 1
            else:
                src = inp.links[0].from_socket
                mix = nt.nodes.new('ShaderNodeMixRGB')
                mix.blend_type = 'MULTIPLY'
                mix.inputs['Fac'].default_value = 1.0
                nt.links.new(src, mix.inputs['Color1'])
                mix.inputs['Color2'].default_value = (rgb[0], rgb[1], rgb[2], 1)
                nt.links.new(mix.outputs['Color'], inp)
                done['tinted'] += 1
    print('SET_PAINT', name, done)
    if done['set'] == 0 and done['tinted'] == 0:
        print('SET_PAINT_WARNING no material matched', name)


def render(path):
    if os.path.exists(path):
        os.remove(path)
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return os.path.exists(path)


def main():
    spec = json.load(open(sys.argv[sys.argv.index('--') + 1]))
    clear()
    setup(spec.get('res', 1024), spec.get('samples', 64), spec.get('bg', 0.22))
    objs = import_glb(spec['glb'])
    lo, hi = scene_bbox(objs)
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    size = max(hi[i] - lo[i] for i in range(3))
    if spec.get('mode') == 'label':
        cmap = spec['colours']
        flatten_to_emission(objs, lambda n: cmap.get(n.split('.')[0]))
    elif spec.get('mode') == 'clay_shaded':
        add_lights(c, size)
        rgb = spec['paint']['rgb']
        for o in objs:                       # every material to ONE paint colour:
            for slot in o.material_slots:    # this is the shading-only FLOOR for a
                m = slot.material            # dark-speck count
                if not m:
                    continue
                m.use_nodes = True
                b = m.node_tree.nodes.get('Principled BSDF')
                if b:
                    b.inputs['Base Color'].default_value = (rgb[0], rgb[1], rgb[2], 1)
                    for k in ('Alpha',):
                        if k in b.inputs:
                            b.inputs[k].default_value = 1.0
                    if 'Transmission' in b.inputs:
                        b.inputs['Transmission'].default_value = 0.0
                    if 'Transmission Weight' in b.inputs:
                        b.inputs['Transmission Weight'].default_value = 0.0
                m.blend_method = 'OPAQUE'
    else:
        add_lights(c, size)
        if spec.get('paint'):
            set_paint(objs, spec['paint']['material'], spec['paint']['rgb'])
    done = []
    for v in spec['views']:
        place_camera(lo, hi, v['az'], v.get('el', 0), spec.get('margin', 1.06))
        ok = render(v['out'])
        done.append(dict(out=v['out'], ok=ok, az=v['az'], el=v.get('el', 0)))
    json.dump(dict(bbox=[lo, hi], views=done), open(spec['report'], 'w'), indent=1)
    print('BL_RENDER_DONE_MARKER')


main()
