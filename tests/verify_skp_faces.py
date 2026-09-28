# Verify a .skp outside Blender: walk model entities, groups and component
# definitions; report face count and edge-count histogram (triangles vs quads vs
# n-gons). Usage: python tests/verify_skp_faces.py <file.skp>
import sys
from collections import Counter

sys.path.insert(0, r"E:\play\coding\Sketchup_Importer")

from sketchup import Model

path = sys.argv[1]
model = Model.from_file(path)

hist = Counter()
holes = 0
soft_edges = 0

def walk(entities):
    global holes, soft_edges
    for f in entities.faces:
        hist[len(f.edges)] += 1
        for e in f.edges:
            try:
                if e.GetSoft():
                    soft_edges += 1
            except Exception:
                pass
    for g in entities.groups:
        walk(g.entities)

def walk_instances(entities):
    # component instances -> count via definitions once
    return

walk(model.entities)

# component definitions (instances reference these)
def_faces = Counter()
try:
    defs = model.component_definitions
    for d in defs:
        for f in d.entities.faces:
            def_faces[len(f.edges)] += 1
        for g in d.entities.groups:
            walk(g.entities)  # count into main hist (geometry lives here)
except Exception as ex:
    print("[VERIFY] component_definitions not walkable:", ex)

model.close()

nfaces = sum(hist.values())
ndef = sum(def_faces.values())
total = nfaces + ndef
print(f"[VERIFY] faces (model+groups)={nfaces}, in component defs={ndef}, total={total}")
print(f"[VERIFY] soft edge flags (per face side)={soft_edges}")
print(f"[VERIFY] edge-count histogram={dict(sorted(hist.items()))}")
if def_faces:
    print(f"[VERIFY] def-face histogram={dict(sorted(def_faces.items()))}")
tris = hist.get(3, 0) + def_faces.get(3, 0)
if total:
    print(f"[VERIFY] triangle faces={tris} ({tris / total * 100:.1f}%), "
          f"quads={hist.get(4, 0) + def_faces.get(4, 0)}, "
          f"n-gons(>=5)={sum(v for k, v in hist.items() if k >= 5) + sum(v for k, v in def_faces.items() if k >= 5)}")
