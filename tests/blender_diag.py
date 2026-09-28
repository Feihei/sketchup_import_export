# Diagnose road.007: per-material-slot triangle counts, vertex count,
# and what merge_coplanar_tris produces for each group.
import bmesh
import bpy
import sys
from collections import defaultdict

sys.path.insert(0, r"E:\play\coding\Sketchup_Importer\tests")
import numpy as np

text = open(r"E:\play\coding\Sketchup_Importer\sketchup_import_export\__init__.py", encoding="utf-8").read()
code = text[text.index("def _boundary_rings"): text.index("class SceneExporter")]
ns = {"defaultdict": defaultdict, "np": np}
exec(code, ns)
merge_coplanar_tris = ns["merge_coplanar_tris"]

for ob in bpy.context.scene.objects:
    if ob.type != "MESH":
        continue
    dg = bpy.context.evaluated_depsgraph_get()
    m = ob.evaluated_get(dg).to_mesh()
    m.calc_loop_triangles()
    verts = np.empty(len(m.vertices) * 3, dtype=np.float64)
    m.vertices.foreach_get("co", verts)
    verts = verts.reshape(-1, 3)
    loops = np.empty(len(m.loops), dtype=np.int32)
    m.loops.foreach_get("vertex_index", loops)
    by_slot = defaultdict(list)
    for t in m.loop_triangles:
        by_slot[t.material_index].append(
            [int(loops[t.loops[0]]), int(loops[t.loops[1]]), int(loops[t.loops[2]])])
    print(f"[DIAG] {ob.name}: verts={len(m.vertices)} tris={len(m.loop_triangles)} slots={dict((k, len(v)) for k, v in by_slot.items())}")
    total_faces = 0
    for idx, tris in sorted(by_slot.items()):
        faces = merge_coplanar_tris(verts, tris)
        ntuple = sum(1 for f in faces if isinstance(f, tuple))
        sizes = sorted((len(f[0]) if isinstance(f, tuple) else len(f)) for f in faces)
        total_faces += len(faces)
        print(f"[DIAG]   slot {idx}: {len(tris)} tris -> {len(faces)} faces ({ntuple} with holes), sizes min/max={sizes[0]}/{sizes[-1]}")
    print(f"[DIAG]   TOTAL: {len(m.loop_triangles)} tris -> {total_faces} faces")
    ob.evaluated_get(dg).to_mesh_clear()
