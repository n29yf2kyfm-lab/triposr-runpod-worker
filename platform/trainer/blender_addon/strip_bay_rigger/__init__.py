"""Strip Bay Rigger — make a car GLB open up: doors, bonnet, tailgate, wheels.

Install: Edit > Preferences > Add-ons > Install... > strip_bay_rigger.zip,
then tick "Strip Bay Rigger". The panel is in the 3D View sidebar (N), tab
"Strip Bay".

  Rig one car    import a GLB, rig it, and get open/close sliders
  Controls       the sliders for every rigged car in the scene
  Batch          a whole folder: rigged GLBs + per-car reports + summary.csv

Headless, for a thousand cars:
  blender -b --factory-startup --python strip_bay_rigger/cli.py -- IN OUT [--blend]

What it can and cannot do is written in core.py's docstring and in every
car's report: it rigs cars whose doors are SEPARATE objects in the file and
refuses, with the reason, cars whose doors are welded into the body.
"""
bl_info = {
    'name': 'Strip Bay Rigger',
    'author': 'ExpertCarCheck',
    'version': (1, 0, 0),
    'blender': (3, 6, 0),
    'location': 'View3D > Sidebar > Strip Bay',
    'description': 'Rig car and van GLBs so doors, bonnet, tailgate and wheels open; batch a folder',
    'category': 'Import-Export',
}

import os, json
import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty
from bpy_extras.io_utils import ImportHelper

from . import core, rig, batch


def _cars(scene):
    return [o for o in scene.objects if o.name.startswith('SB_Controls') and 'sb_controls' in o]


class SB_OT_rig_file(bpy.types.Operator, ImportHelper):
    """Import a car GLB and rig it: doors, bonnet, tailgate and wheels get sliders"""
    bl_idname = 'strip_bay.rig_file'
    bl_label = 'Rig a car GLB…'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.glb'
    filter_glob: StringProperty(default='*.glb;*.gltf', options={'HIDDEN'})

    def execute(self, context):
        car = os.path.splitext(os.path.basename(self.filepath))[0]
        ov = core.load_overrides(os.path.join(os.path.dirname(__file__), 'overrides.json'),
                                 os.path.join(os.path.dirname(self.filepath), 'overrides.json'))
        try:
            rep, parts = core.process_file(self.filepath, None, None, ov.get(car))
        except core.Refused as e:
            self.report({'WARNING'}, f'Refused: {e}')
            return {'CANCELLED'}
        rig.add_controls(parts, rep['hinge'], rep.get('motion'), car, rep)
        msg = f"{car}: {sum(1 for k in rep['parts'] if k.startswith('door_'))} doors"
        if rep.get('missing'):
            msg += ', no ' + ' / '.join(m.replace('panel_', '') for m in rep['missing'])
        if rep.get('motion'):
            msg += ', ' + ' '.join(f"{k} {v['type']}" for k, v in rep['motion'].items())
        self.report({'INFO'}, msg)
        context.scene['sb_last_report'] = str({k: rep[k] for k in ('parts', 'missing', 'motion') if k in rep})
        return {'FINISHED'}


class SB_OT_export(bpy.types.Operator):
    """Export the rigged car, shut, as a GLB the web trainer reads"""
    bl_idname = 'strip_bay.export'
    bl_label = 'Export rigged car…'
    filepath: StringProperty(subtype='FILE_PATH')
    car: StringProperty()

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        ctl = context.scene.objects.get(f'SB_Controls.{self.car}')
        if ctl:
            rig.reset(ctl)                      # export SHUT, whatever the sliders say
        parts = {}
        for o in context.scene.objects:
            if 'sb_part' in o and o.get('sb_car') == self.car:
                parts.setdefault(o['sb_part'], []).append(o)
        if not parts:
            self.report({'ERROR'}, 'No rigged parts found')
            return {'CANCELLED'}
        path = self.filepath if self.filepath.lower().endswith('.glb') else self.filepath + '.glb'
        core.export_parts(parts, path)
        # the report travels with the GLB: hinges and door motion are what the
        # web trainer's fleet_gen.py reads
        if ctl and 'sb_report' in ctl:
            with open(path[:-4] + '.report.json', 'w') as fh:
                json.dump(json.loads(ctl['sb_report']), fh, indent=1)
        self.report({'INFO'}, f'Exported {path} and its .report.json')
        return {'FINISHED'}


class SB_OT_slide(bpy.types.Operator):
    """Make this car's rear side doors slide back on a rail (van, MPV) or swing on hinges"""
    bl_idname = 'strip_bay.slide'
    bl_label = 'Rear doors slide'
    bl_options = {'REGISTER', 'UNDO'}
    car: StringProperty()
    slide: BoolProperty(default=True)

    def execute(self, context):
        ctl = context.scene.objects.get(f'SB_Controls.{self.car}')
        if not ctl:
            return {'CANCELLED'}
        rig.rear_doors_slide(ctl, self.slide)
        self.report({'INFO'}, f"{self.car}: rear doors now {'slide' if self.slide else 'swing'}")
        return {'FINISHED'}


class SB_OT_reset(bpy.types.Operator):
    """Shut every door, bonnet and tailgate and put the wheels back"""
    bl_idname = 'strip_bay.reset'
    bl_label = 'Shut everything'
    car: StringProperty()

    def execute(self, context):
        ctl = context.scene.objects.get(f'SB_Controls.{self.car}')
        if ctl:
            rig.reset(ctl)
        return {'FINISHED'}


class SB_OT_batch(bpy.types.Operator):
    """Rig every GLB in the input folder; write rigged GLBs, reports and summary.csv"""
    bl_idname = 'strip_bay.batch'
    bl_label = 'Process folder'

    def execute(self, context):
        s = context.scene
        src, dst = bpy.path.abspath(s.sb_in_dir), bpy.path.abspath(s.sb_out_dir)
        if not os.path.isdir(src):
            self.report({'ERROR'}, 'Choose an input folder of GLB files')
            return {'CANCELLED'}
        if not dst:
            self.report({'ERROR'}, 'Choose an output folder')
            return {'CANCELLED'}
        wm = context.window_manager
        wm.progress_begin(0, 100)
        counts = batch.run(src, dst, save_blend=s.sb_save_blend, redo=s.sb_redo, limit=s.sb_limit,
                           progress=lambda i, n: wm.progress_update(int(100 * i / max(n, 1))))
        wm.progress_end()
        self.report({'INFO'}, 'Batch done: ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items()))
                    + f' — see {os.path.join(dst, "summary.csv")}')
        return {'FINISHED'}


class SB_PT_panel(bpy.types.Panel):
    bl_label = 'Strip Bay Rigger'
    bl_idname = 'SB_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Strip Bay'

    def draw(self, context):
        L, s = self.layout, context.scene
        box = L.box()
        box.label(text='Rig one car', icon='AUTO')
        box.operator('strip_bay.rig_file', icon='IMPORT')

        for ctl in _cars(s):
            car = ctl.get('sb_car', ctl.name)
            b = L.box()
            b.label(text=car, icon='AUTO')
            for k in ctl['sb_controls'].split(','):
                if k:
                    b.prop(ctl, f'["{k}"]', text=k.replace('_', ' '), slider=True)
            if f'SB_pivot_door_rl.{car}' in s.objects or f'SB_pivot_door_rr.{car}' in s.objects:
                mo = json.loads(ctl.get('sb_report', '{}')).get('motion', {})
                sliding = any(mo.get(d, {}).get('type') == 'slide' for d in ('door_rl', 'door_rr'))
                op = b.operator('strip_bay.slide', icon='TRACKING',
                                text='Rear doors: make them swing' if sliding else 'Rear doors: make them slide')
                op.car, op.slide = car, not sliding
            r = b.row(align=True)
            r.operator('strip_bay.reset', icon='LOOP_BACK').car = car
            r.operator('strip_bay.export', icon='EXPORT').car = car

        box = L.box()
        box.label(text='Batch a folder', icon='FILE_FOLDER')
        box.prop(s, 'sb_in_dir')
        box.prop(s, 'sb_out_dir')
        row = box.row()
        row.prop(s, 'sb_save_blend')
        row.prop(s, 'sb_redo')
        box.prop(s, 'sb_limit')
        box.operator('strip_bay.batch', icon='PLAY')
        box.label(text='Refused cars are listed with the reason in summary.csv', icon='INFO')


CLASSES = (SB_OT_rig_file, SB_OT_export, SB_OT_slide, SB_OT_reset, SB_OT_batch, SB_PT_panel)


def register():
    S = bpy.types.Scene
    S.sb_in_dir = StringProperty(name='Input', subtype='DIR_PATH', description='Folder of car GLB files')
    S.sb_out_dir = StringProperty(name='Output', subtype='DIR_PATH', description='Where rigged GLBs and reports go')
    S.sb_save_blend = BoolProperty(name='Save .blend too', description='Also save each car with its sliders')
    S.sb_redo = BoolProperty(name='Redo done cars', description='Process cars that already have a report again')
    S.sb_limit = IntProperty(name='Only first N (0 = all)', min=0, default=0)
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
    for a in ('sb_in_dir', 'sb_out_dir', 'sb_save_blend', 'sb_redo', 'sb_limit'):
        delattr(bpy.types.Scene, a)
