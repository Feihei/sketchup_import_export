# Reproduce: quads merge but bigger polys don't, at real-world scale?
# Blender stores f32; round-tripping coords through f32 adds ~1.2e-7 * |coord| error.
# merge_coplanar_tris uses ABSOLUTE tolerances (normal_eps=1e-6 on dot,
# dist_eps=1e-6 m on plane offset) -> suspected to fail at building scale.
import math
from collections import defaultdict

import numpy as np

SRC = r"E:\play\coding\Sketchup_Importer\sketchup_import_export\__init__.py"
text = open(SRC, encoding="utf-8").read()
code = text[text.index("def _boundary_rings"): text.index("class SceneExporter")]
ns = {"defaultdict": defaultdict, "np": np}
exec(code, ns)
merge_coplanar_tris = ns["merge_coplanar_tris"]

def f32(v):
    return float(np.float32(v))

def case(name, offset, radius, n, f32_round):
    """n-gon fan centered at (offset), radius r, coords optionally f32-rounded."""
    cx, cy = offset
    verts = [(cx + radius * math.cos(2 * math.pi * i / n),
              cy + radius * math.sin(2 * math.pi * i / n), 0.0) for i in range(n)]
    if f32_round:
        verts = [(f32(x), f32(y), 0.0) for x, y, _ in verts]
    tris = [(0, i, i + 1) for i in range(1, n - 1)]
    faces = merge_coplanar_tris(np.asarray(verts, float), np.asarray(tris, np.int64))
    sizes = sorted(len(f) for f in faces)
    verdict = "OK (single n-gon)" if sizes == [n] else "FELL BACK TO TRIS"
    print(f"{name:44s} -> faces={sizes}  {verdict}")

print("== coords rounded through float32 (Blender reality), n-gon at various scales ==")
case("quad r=1m @ origin", (0, 0), 1.0, 4, True)
case("pentagon r=1m @ origin", (0, 0), 1.0, 5, True)
case("pentagon r=10m @ origin", (0, 0), 10.0, 5, True)
case("pentagon r=100m @ origin", (0, 0), 100.0, 5, True)
case("hexagon r=10m @ (100,100)m", (100, 100), 10.0, 6, True)
case("octagon r=30m @ (500,0)m", (500, 0), 30.0, 8, True)
print()
print("== same shapes with exact f64 coords (control) ==")
case("pentagon r=100m @ origin (f64)", (0, 0), 100.0, 5, False)
case("octagon r=30m @ (500,0)m (f64)", (500, 0), 30.0, 8, False)
