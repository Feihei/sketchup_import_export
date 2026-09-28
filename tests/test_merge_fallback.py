# Probe how merge_coplanar_tris handles real-world structures:
# faces with holes, pinch vertices, non-manifold edges, coplanar quad grids.
# Faces with holes are returned as (outer_ring, [hole_rings...]) tuples.
import numpy as np

SRC = r"E:\play\coding\Sketchup_Importer\sketchup_import_export\__init__.py"
text = open(SRC, encoding="utf-8").read()
code = text[text.index("def _boundary_rings"): text.index("class SceneExporter")]
ns = {"defaultdict": __import__("collections").defaultdict, "np": np}
exec(code, ns)
merge_coplanar_tris = ns["merge_coplanar_tris"]

def report(name, verts, tris, expect=None):
    faces = merge_coplanar_tris(np.asarray(verts, float), np.asarray(tris, np.int64))
    sizes = [len(f[0]) if isinstance(f, tuple) else len(f) for f in faces]
    holes = [len(f[1]) for f in faces if isinstance(f, tuple)]
    desc = f"{len(faces)} faces, sizes={sizes}"
    if holes:
        desc += f", faces with holes={len(holes)}"
    ok = "OK" if (expect is None or sizes == expect) else f"FAIL (expect {expect})"
    print(f"{name:46s} -> {desc}  {ok}")

# 1. coplanar 4x4 quad grid (32 tris, one flat plane) -> single 16-gon
verts = [(x, y, 0.0) for y in range(5) for x in range(5)]
tris = []
for gy in range(4):
    for gx in range(4):
        i = gy * 5 + gx
        tris += [(i, i + 1, i + 6), (i, i + 6, i + 5)]
report("4x4 coplanar quad grid", verts, tris, expect=[16])

# 2. square plate with a square hole -> one face with 1 hole ring
V = [(0, 0), (10, 0), (10, 10), (0, 10), (3, 3), (7, 3), (7, 7), (3, 7)]
V = [(x, y, 0.0) for x, y in V]
tris = [
    (0, 1, 4), (1, 5, 4), (1, 2, 5), (2, 6, 5),
    (2, 3, 6), (3, 7, 6), (3, 0, 7), (0, 4, 7),
]
plate_tris = tris  # 留给 case 5 复用
report("plate with square hole (8 tris)", V, tris, expect=[4])

# 3. two coplanar quads touching at ONE vertex (pinch) -> single 6-gon
V = [(0, 0), (1, 0), (1, 1), (0, 1), (1, -1), (2, 0)]
V = [(x, y, 0.0) for x, y in V]
tris = [(0, 1, 2), (0, 2, 3), (1, 4, 5), (1, 5, 2)]
report("two quads pinched at one vertex", V, tris, expect=[6])

# 4. non-manifold: 3 triangles sharing one edge -> that block falls back to tris
V = [(0, 0), (1, 0), (0, 1), (0, -1)]
V = [(x, y, 0.0) for x, y in V]
tris = [(0, 1, 2), (1, 0, 3), (0, 1, 2)]
report("3 tris sharing one edge (non-manifold)", V, tris, expect=[3, 3, 3])

# 5. quad + plate-with-hole in the SAME group: quad must still merge now
V5 = [(0, 0), (1, 0), (1, 1), (0, 1),            # quad 0-3
      (10, 0), (20, 0), (20, 10), (10, 10),       # plate outer 4-7
      (13, 3), (17, 3), (17, 7), (13, 7)]         # plate hole 8-11
V5 = [(x, y, 0.0) for x, y in V5]
tris5 = [(0, 1, 2), (0, 2, 3)] + [(a + 4, b + 4, c + 4) for a, b, c in plate_tris]
report("quad + plate-with-hole in same group", V5, tris5, expect=[4, 4])
