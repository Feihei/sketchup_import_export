"""Reproduce the Blender export crash outside Blender, feature by feature.

Each case runs in a subprocess so an access violation only kills that case.
Usage: python tests/repro_export_crash.py
"""
import os
import subprocess
import sys
import zlib
import struct

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_png(path):
    """Write a tiny 2x2 red PNG without PIL."""
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00\x00" * 2 + b"\x00\xff\x00\x00\x00" * 2
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


CASES = {}

CASES["A_group_plain"] = """
m = sk.Model()
g = sk.Group.create()
g.name = "cube"
geom = sk.GeometryInput()
geom.AddVertices(VERTS)
for tri in [[0,1,2],[0,2,3],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]]:
    geom.add_face(tri)
g.entities.addGeometryInput(geom)
m.entities.addGroup(g)
m.save(OUT)
m.close()
"""

CASES["B_group_transform"] = """
m = sk.Model()
g = sk.Group.create()
g.name = "cube"
g.transform = [[1,0,0,2.0],[0,1,0,3.0],[0,0,1,4.0],[0,0,0,1]]
geom = sk.GeometryInput()
geom.AddVertices(VERTS)
for tri in [[0,1,2],[0,2,3],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]]:
    geom.add_face(tri)
g.entities.addGeometryInput(geom)
m.entities.addGroup(g)
m.save(OUT)
m.close()
"""

CASES["C_group_material"] = """
m = sk.Model()
mat = sk.Material.create()
mat.name = "Red"
mat.color = (255, 0, 0, 255)
m.addMaterials([mat])
g = sk.Group.create()
g.name = "cube"
m.entities.addGroup(g)  # attach first: material refs require model context
geom = sk.GeometryInput()
geom.AddVertices(VERTS)
for tri in [[0,1,2],[0,2,3],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]]:
    geom.add_face(tri, material=mat)
g.entities.addGeometryInput(geom)
m.save(OUT)
m.close()
"""

CASES["D_group_material_texture"] = """
m = sk.Model()
mat = sk.Material.create()
mat.name = "Textured"
mat.color = (255, 255, 255, 255)
tex = sk.Texture.create_from_file(PNG)
mat.set_texture(tex)
m.addMaterials([mat])
g = sk.Group.create()
g.name = "cube"
m.entities.addGroup(g)  # attach first
geom = sk.GeometryInput()
geom.AddVertices(VERTS)
uvs = [[0,0],[1,0],[1,1],[0,1]]
for i, tri in enumerate([[0,1,2],[0,2,3],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]]):
    geom.add_face(tri, material=mat, uvs=[uvs[j % 4] for j in range(3)])
g.entities.addGeometryInput(geom)
m.save(OUT)
m.close()
"""

CASES["E_component_instance"] = """
m = sk.Model()
comp = sk.Component.create()
comp.name = "sharedcube"
geom = sk.GeometryInput()
geom.AddVertices(VERTS)
for tri in [[0,1,2],[0,2,3],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]]:
    geom.add_face(tri)
comp.entities.addGeometryInput(geom)
m.addComponentDefinitions([comp])
inst = comp.createInstance()
inst.name = "cube1"
inst.transform = [[1,0,0,5.0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
m.entities.addInstance(inst, "cube1")
m.save(OUT)
m.close()
"""


def run_case(name, body):
    out = os.path.join(REPO, "build", f"repro_{name}.skp")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    png = os.path.join(REPO, "build", "repro.png")
    make_png(png)
    code = f"""
import sys
sys.path.insert(0, {REPO!r})
import numpy as np
import sketchup as sk
OUT = {out!r}
PNG = {png!r}
VERTS = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,0,1],[1,0,1],[1,1,1],[0,1,1]], dtype=np.float64)
{body}
print("OK")
"""
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO)
    status = "PASS" if p.returncode == 0 and "OK" in p.stdout else f"CRASH/FAIL rc={p.returncode}"
    err = (p.stderr or "").strip().splitlines()
    tail = err[-1] if err else ""
    print(f"{name:32s} {status}  {tail[:120]}")
    return p.returncode


if __name__ == "__main__":
    failures = []
    for name, body in CASES.items():
        if run_case(name, body) != 0:
            failures.append(name)
    print()
    print("failing cases:", failures or "none")
