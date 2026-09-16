"""Phase 1 冒烟测试(Blender 外): 创建立方体 → save → 读回断言 face 数。

运行前置(见 编译.md):
  1. SketchUp SDK headers/ 与 binaries/ 已就位
  2. python setup.py build_ext --inplace
用法: python tests/smoke_export.py [输出路径]
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import sketchup
from sketchup import GeometryInput, Model

# 1 m 立方体的 8 个顶点(米)
CUBE_VERTS = np.array(
    [
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ],
    dtype=np.float64,
)
# 6 个四边形面(顶点索引)
CUBE_FACES = [
    [0, 1, 2, 3],  # bottom
    [4, 5, 6, 7],  # top
    [0, 1, 5, 4],  # front
    [1, 2, 6, 5],  # right
    [2, 3, 7, 6],  # back
    [3, 0, 4, 7],  # left
]


def build_cube_model(filepath):
    model = Model()
    geom = GeometryInput()
    geom.AddVertices(CUBE_VERTS)
    for face in CUBE_FACES:
        geom.add_face(face)
    model.entities.addGeometryInput(geom)
    model.save(filepath)
    model.close()
    return filepath


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "smoke_cube.skp")
    print("API version:", sketchup.get_API_version())

    build_cube_model(out)
    assert os.path.exists(out) and os.path.getsize(out) > 0, "save produced no file"
    print("saved:", out, os.path.getsize(out), "bytes")

    reopened = Model.from_file(out)
    num_faces = reopened.entities.NumFaces()
    num_groups = reopened.entities.NumGroups()
    print("reopened: faces =", num_faces, "groups =", num_groups)
    reopened.close()

    assert num_faces == 6, f"expected 6 faces, got {num_faces}"
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
