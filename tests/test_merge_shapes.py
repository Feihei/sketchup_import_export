# Test: does merge_coplanar_tris rebuild complex coplanar polygons (not just quads)?
# Extracts _boundary_loop / merge_coplanar_tris from blender plugin __init__.py
# without importing bpy. Reports resulting face sizes per shape.
import math
from collections import defaultdict

import numpy as np

SRC = r"E:\play\coding\Sketchup_Importer\sketchup_importer\__init__.py"
text = open(SRC, encoding="utf-8").read()
code = text[text.index("def _boundary_loop"): text.index("class SceneExporter")]
ns = {"defaultdict": defaultdict, "np": np}
exec(code, ns)
merge_coplanar_tris = ns["merge_coplanar_tris"]

def tri_fan(n):
    """n-gon on XY plane, fan triangulation around vertex 0."""
    verts = [(math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0.0) for i in range(n)]
    tris = [(0, i, i + 1) for i in range(1, n - 1)]
    return verts, tris

def l_shape():
    """Concave L-shaped 6-gon, ear-cut triangulation."""
    verts = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    verts = [(x, y, 0.0) for x, y in verts]
    tris = [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 5)]
    return verts, tris

def quad_with_center():
    """Quad triangulated with an interior (Steiner) vertex 4."""
    verts = [(0, 0), (2, 0), (2, 2), (0, 2), (1, 1)]
    verts = [(x, y, 0.0) for x, y in verts]
    tris = [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    return verts, tris

def two_ngons_sharing_edge():
    """Two coplanar quads sharing edge 1-2 -> that edge has 4 triangles."""
    verts = [(0, 0), (1, 0), (1, 1), (0, 1), (2, 0), (2, 1)]
    verts = [(x, y, 0.0) for x, y in verts]
    tris = [(0, 1, 2), (0, 2, 3), (1, 4, 5), (1, 5, 2)]
    return verts, tris

def f32_noisy_ngon(n, scale=10.0):
    """n-gon with coordinates rounded through float32 (Blender stores f32),
    exported at ~10 m scale -> rounding error ~1e-6 m."""
    verts, tris = tri_fan(n)
    verts = [(np.float32(x * scale), np.float32(y * scale), 0.0) for x, y, _ in verts]
    verts = [(float(x) / scale, float(y) / scale, 0.0) for x, y, _ in verts]
    return verts, tris

def sliver_ngon(n):
    """n-gon where fan triangles are thin slivers (very low height)."""
    verts = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 1e-3, 0.0),
             (5.0, 2e-3, 0.0), (0.0, 1e-3, 0.0)]
    tris = [(0, 1, 2), (0, 2, 3), (0, 3, 4)]
    return verts, tris

cases = [
    ("triangle fan pentagon (5-gon)", *tri_fan(5), 5),
    ("triangle fan hexagon (6-gon)", *tri_fan(6), 6),
    ("triangle fan 12-gon", *tri_fan(12), 12),
    ("concave L-shape (6-gon)", *l_shape(), 6),
    ("quad + interior vertex (4-gon)", *quad_with_center(), 4),
    ("two coplanar ngons sharing edge", *two_ngons_sharing_edge(), None),
    ("f32-rounded 12-gon @10m", *f32_noisy_ngon(12), 12),
    ("sliver fan (thin 5-gon)", *sliver_ngon(5), 5),
]

for name, verts, tris, expect in cases:
    faces = merge_coplanar_tris(np.asarray(verts, float), np.asarray(tris, np.int64))
    sizes = sorted(len(f) for f in faces)
    if expect is not None:
        ok = sizes == [expect]
        verdict = "OK" if ok else f"FAIL (expected single {expect}-gon)"
    else:
        ok = sizes == [4, 4]
        verdict = "OK (two quads)" if ok else f"note: {sizes}"
    print(f"{name:38s} -> faces={sizes}  {verdict}")
