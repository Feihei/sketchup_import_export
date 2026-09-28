# Check that every SU* C API call used in sketchup.pyx is exported by the DLL.
import re
import subprocess

DUMPBIN = r"C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Tools\MSVC\14.51.36231\bin\Hostx64\x64\dumpbin.exe"
DLL = r"C:\Users\THAD\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\sketchup_import_export\SketchUpAPI.dll"

out = subprocess.run([DUMPBIN, "/EXPORTS", DLL], capture_output=True, text=True)
exported = set()
for line in out.stdout.splitlines():
    m = re.match(r"\s*\d+\s+[0-9A-F]+\s+[0-9A-F]+\s+(\w+)", line)
    if m:
        exported.add(m.group(1))

used = set()
for m in re.finditer(r"\b(SU[A-Z]\w+)\s*\(", open("sketchup.pyx", encoding="utf-8").read()):
    used.add(m.group(1))

missing = sorted(used - exported)
print(f"pyx uses {len(used)} SU functions; DLL exports {len(exported)}")
print("missing from DLL:", missing if missing else "NONE - all present")
