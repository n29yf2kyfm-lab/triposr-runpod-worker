"""Convert ONE catalogue car into a Strip Bay car. Any family, one tool.

    blender -b --python sb_convert.py -- in.glb out.glb report.json

A thin wrapper: the converter itself lives in the Blender add-on,
`blender_addon/strip_bay_rigger/core.py`, so the add-on, its folder batch and
this script can never drift apart. Read core.py's docstring for what the names
are trusted for, the families it handles and what it refuses.

Exit 0 and prints `SB_DONE` when the car was written; exit 2 and prints
`SB_REFUSED <reason>` (report written, no GLB) when it was refused. Batch
scripts depend on both.
"""
import bpy, sys, os, json

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, 'blender_addon'))
from strip_bay_rigger import core        # noqa: E402

a = sys.argv[sys.argv.index('--') + 1:]
src, dst, outj = a[0], a[1], a[2]
bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    rep, parts = core.process_file(src, dst, outj)
except core.Refused as e:
    print('SB_REFUSED', e)
    sys.exit(2)
print('SB_DONE', json.dumps(rep['parts']), 'missing', rep['missing'])
