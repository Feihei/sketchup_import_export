# Standalone check: does merge_coplanar_tris preserve triangle winding?
# Extracts _boundary_loop / merge_coplanar_tris from blender plugin __init__.py
# without importing bpy, then verifies merged face orientation.
from collections import defaultdict

import numpy as np

SRC = r"E:\play\coding\Sketchup_Importer\sketchup_importer\__init__.py"
text = open(SRC, encoding="utf-8").read()
start = text.index("def _boundary_rings")
end = text.index("class SceneExporter")
code = text[start:end]
ns = {"defaultdict": defaultdict, "np": np}
exec(code, ns)
merge_coplanar_tris = ns["merge_coplanar_tris"]

def check(name, verts, tris, expect_ccw_normal):
    faces = merge_coplanar_tris(np.asarray(verts, float), tris)
    print(f"--- {name}: {len(faces)} face(s)")
    ok = True
    for f in faces:
        if isinstance(f, tuple):
            f = f[0]  # 带孔洞面只检查外环
        a, b, c = (np.asarray(verts, float)[i] for i in f[:3])
        n = np.cross(b - a, c - a)
        d = float(np.dot(n, expect_ccw_normal))
        status = "OK  (same winding)" if d > 0 else "FLIPPED"
        if d <= 0:
            ok = False
        print(f"    loop {list(f)} -> normal dot expected = {d:+.1f}  {status}")
    return ok

V = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
up = [0, 0, 1]
ok1 = check("quad CCW (normal +Z)", V, [(0, 1, 2), (0, 2, 3)], up)
ok2 = check("single tri CCW (normal +Z)", V, [(0, 1, 2)], up)

# fallback path (hole -> triangles) must stay unflipped
Vh = [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0], [1, 1, 0]]
tris_h = [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
# ring around center hole: boundary only, each boundary edge used once -> simple ring
faces = merge_coplanar_tris(np.asarray(Vh, float), tris_h)
print(f"--- ring-with-hole: {len(faces)} face(s)")
ok3 = True
for f in faces:
    if isinstance(f, tuple):
        f = f[0]
    if len(f) == 3 and list(f) in [list(t) for t in tris_h]:
        a, b, c = (np.asarray(Vh, float)[i] for i in f)
        n = np.cross(b - a, c - a)
        good = float(np.dot(n, up)) > 0
        print(f"    tri {list(f)} -> {'OK' if good else 'FLIPPED'}")
        ok3 = ok3 and good
    else:
        print(f"    ngon {list(f)} (len={len(f)})")

print()
print("RESULT:", "ALL SAME WINDING" if (ok1 and ok2 and ok3) else "WINDING FLIPPED BY MERGE")
