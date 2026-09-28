# End-to-end check OUTSIDE Blender: simulate the export pipeline
# (fan-triangulated coplanar polygon -> merge_coplanar_tris -> GeometryInput -> .skp)
# then reopen the .skp and count edges per face to see whether N-gons survive.
import os
import sys
import tempfile
from collections import defaultdict

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import sketchup  # compiled cp313 binding, needs SketchUpAPI.dll on PATH
from sketchup import GeometryInput, Model

# import merge code from the plugin without bpy
text = open(os.path.join(REPO, "sketchup_importer", "__init__.py"), encoding="utf-8").read()
code = text[text.index("def _boundary_rings"): text.index("class SceneExporter")]
ns = {"defaultdict": defaultdict, "np": np}
exec(code, ns)
merge_coplanar_tris = ns["merge_coplanar_tris"]

import math

def ngon_case(n, name):
    verts = [(math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0.0) for i in range(n)]
    tris = [(0, i, i + 1) for i in range(1, n - 1)]
    return name, np.asarray(verts), np.asarray(tris, np.int64), [n]

def l_shape_case():
    verts = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    verts = [(x, y, 0.0) for x, y in verts]
    tris = [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 5)]
    return "concave L-shape", np.asarray(verts), np.asarray(tris, np.int64), [6]

def mixed_solid_case():
    """Pentagonal prism-ish: pentagon top + bottom + quads, all triangulated
    as Blender would after calc_loop_triangles."""
    import math as _m
    pent = [(_m.cos(2 * _m.pi * i / 5), _m.sin(2 * _m.pi * i / 5), 0.0) for i in range(5)]
    top = [(x, y, 1.0) for x, y, _ in pent]
    verts = pent + top
    tris = []
    for i in range(1, 4):  # bottom fan
        tris.append((0, i, i + 1))
    for i in range(1, 4):  # top fan
        tris.append((5, 5 + i, 5 + i + 1))
    for i in range(5):  # side quads, 2 tris each
        a, b = i, (i + 1) % 5
        tris += [(a, b, 5 + b), (a, 5 + b, 5 + a)]
    return "pentagon prism (all tris)", np.asarray(verts), np.asarray(tris, np.int64), [4, 4, 4, 4, 4, 5, 5]

def plate_with_hole_case():
    """Square plate with a square hole: 8-triangle ngon-with-hole -> 1 face (4+4 edges)."""
    V = [(0, 0), (10, 0), (10, 10), (0, 10), (3, 3), (7, 3), (7, 7), (3, 7)]
    V = [(x, y, 0.0) for x, y in V]
    tris = [
        (0, 1, 4), (1, 5, 4), (1, 2, 5), (2, 6, 5),
        (2, 3, 6), (3, 7, 6), (3, 0, 7), (0, 4, 7),
    ]
    return "plate with square hole", np.asarray(V), np.asarray(tris, np.int64), [8]

CASES = [
    ngon_case(3, "triangle (control)"),
    ngon_case(4, "quad (control)"),
    ngon_case(5, "pentagon"),
    ngon_case(6, "hexagon"),
    ngon_case(8, "octagon"),
    l_shape_case(),
    plate_with_hole_case(),
    mixed_solid_case(),
]

for name, verts, tris, expect_edges in CASES:
    faces = merge_coplanar_tris(verts, tris)
    out = os.path.join(tempfile.gettempdir(), "merge_e2e.skp")
    model = Model()
    geom = GeometryInput()
    geom.AddVertices(verts)
    for f in faces:
        if isinstance(f, tuple):
            geom.add_face([int(i) for i in f[0]], inner_loops=[[int(i) for i in h] for h in f[1]])
        else:
            geom.add_face([int(i) for i in f])
    model.entities.addGeometryInput(geom)
    model.save(out)
    model.close()

    reopened = Model.from_file(out)
    edge_counts = sorted(len(f.edges) for f in reopened.entities.faces)
    reopened.close()
    ok = edge_counts == sorted(expect_edges)
    merged_sizes = sorted(len(f[0]) if isinstance(f, tuple) else len(f) for f in faces)
    print(f"{name:28s} merged={merged_sizes!s:20s} "
          f"skp face edge counts={edge_counts} expect={sorted(expect_edges)}  "
          f"{'OK' if ok else 'MISMATCH'}")
