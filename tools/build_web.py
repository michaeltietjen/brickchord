#!/usr/bin/env python3
"""Copy what Bricklab web needs into docs/web/ (served by GitHub Pages):
the engine (engine.py, synth.py, songrender.py), the built-in drum kits, the
bundled samples and the demo songs, plus manifest.json listing them.
Run it after changing the engine or the demos:  python3 tools/build_web.py"""
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "brickchord")
WEB = os.path.join(ROOT, "docs", "web")

files = []
for sub in ("py", "kits", "samples", "demos"):
    shutil.rmtree(os.path.join(WEB, sub), ignore_errors=True)
os.makedirs(os.path.join(WEB, "py"))
for f in ("engine.py", "synth.py", "songrender.py", "theory.py", "live.py", "edition.py", "ambient.py", "glideweb.py", "chop.py", "chopweb.py"):
    shutil.copy(os.path.join(APP, f), os.path.join(WEB, "py", f))
    files.append("py/" + f)
for kit in sorted(os.listdir(os.path.join(APP, "kits"))):
    d = os.path.join(APP, "kits", kit)
    if not os.path.isdir(d):
        continue
    os.makedirs(os.path.join(WEB, "kits", kit))
    for w in sorted(os.listdir(d)):
        if w.endswith(".wav"):
            shutil.copy(os.path.join(d, w), os.path.join(WEB, "kits", kit, w))
            files.append("kits/%s/%s" % (kit, w))
os.makedirs(os.path.join(WEB, "samples"))
for w in sorted(os.listdir(os.path.join(APP, "samples"))):
    if w.lower().endswith(".wav") and os.path.isfile(os.path.join(APP, "samples", w)):
        shutil.copy(os.path.join(APP, "samples", w), os.path.join(WEB, "samples", w))
        files.append("samples/" + w)
os.makedirs(os.path.join(WEB, "demos"))
demos = []
for f in sorted(os.listdir(os.path.join(APP, "demos"))):
    if f.endswith(".json"):
        shutil.copy(os.path.join(APP, "demos", f), os.path.join(WEB, "demos", f))
        with open(os.path.join(APP, "demos", f)) as fh:
            demos.append({"file": f, "name": json.load(fh).get("demo") or f[:-5]})
with open(os.path.join(WEB, "manifest.json"), "w") as fh:
    json.dump({"files": files, "demos": demos}, fh, indent=1)
size = sum(os.path.getsize(os.path.join(WEB, f)) for f in files)
print("docs/web: %d engine files, %d demos, %.1f MB" % (len(files), len(demos), size / 1e6))
