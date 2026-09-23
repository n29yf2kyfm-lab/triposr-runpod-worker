"""Run the rigger over a folder with no Blender window — for 1,000 cars overnight.

    blender -b --factory-startup --python cli.py -- IN_DIR OUT_DIR [--blend] [--redo] [--limit N]

Works whether or not the add-on is installed: it imports the package from the
folder this file sits in. Exit code 0 when the batch ran (even if some cars
were refused — that is what summary.csv is for), 1 on a usage error.
"""
import sys, os

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
import strip_bay_rigger.batch as batch        # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
flags = {a for a in args if a.startswith('--')}
pos = [a for a in args if not a.startswith('--')]
limit = 0
if '--limit' in args:
    limit = int(args[args.index('--limit') + 1])
    pos = [a for a in pos if a != str(limit)]
if len(pos) != 2:
    print(__doc__)
    sys.exit(1)
# start from an EMPTY scene: the factory startup Cube is 2 m across, sits at
# the origin inside the car, and showed through every open door as a white
# block in the saved .blend files
import bpy                                     # noqa: E402
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
batch.run(pos[0], pos[1], save_blend='--blend' in flags, redo='--redo' in flags, limit=limit)
