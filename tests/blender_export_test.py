# Run inside Blender headless:
#   blender --background test.blend --python tests/blender_export_test.py -- <out.skp>
# Opens the blend, enables the addon, exports via SceneExporter, prints stats.
import sys
import time

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
out = argv[0]

bpy.ops.preferences.addon_enable(module="sketchup_importer")
from sketchup_importer.__init__ import SceneExporter

depsgraph = bpy.context.evaluated_depsgraph_get()
total_tris = 0
n_mesh = 0
for ob in bpy.context.scene.objects:
    if ob.type == "MESH" and ob.visible_get():
        m = ob.evaluated_get(depsgraph).to_mesh()
        m.calc_loop_triangles()
        total_tris += len(m.loop_triangles)
        n_mesh += 1
        ob.evaluated_get(depsgraph).to_mesh_clear()
print(f"[TEST] mesh objects={n_mesh}, total tris={total_tris}", flush=True)

t0 = time.time()
exp = SceneExporter()
exp.set_filename(out)
exp.save(bpy.context, soften_edges=True, soft_angle=20.0)
print(f"[TEST] export took {time.time() - t0:.1f}s -> {out}", flush=True)
