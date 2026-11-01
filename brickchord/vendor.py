# Brickchord library setup.
#
# KNULLI (TrimUI Brick) build: _vendor/ holds one unpacked NumPy, pygame comes
# from the system.
#
# R36Max / ArkOS-family build: _vendor/wheels/ holds NumPy and pygame wheels for
# several Python versions (aarch64). On first launch the pair matching this
# device's Python is unpacked into _vendor/cpXY/ and reused after that. The
# bundled pygame is only used when the system doesn't have one, because the
# firmware's own pygame/SDL is built for its screen.
import os
import sys
import zipfile

APP = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(APP, "_vendor")


def _log(*a):
    print("vendor:", *a, flush=True)


def _unpack(whl, dest):
    tmp = dest + ".part"
    if os.path.isdir(tmp):
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(whl) as z:
        for m in z.namelist():
            # skip test suites, docs and examples: not needed to run
            if "/tests/" in m or m.startswith(("pygame/examples/", "pygame/docs/")):
                continue
            z.extract(m, tmp)
    os.replace(tmp, dest)


def setup(need_pygame=True):
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    if os.path.isdir(os.path.join(VENDOR, "numpy")):          # KNULLI layout
        sys.path.insert(0, VENDOR)
        return
    wheels = os.path.join(VENDOR, "wheels")
    if not os.path.isdir(wheels):
        return                                                 # system libraries only
    tag = "cp%d%d" % sys.version_info[:2]
    have = os.listdir(wheels)
    base = os.path.join(VENDOR, tag)
    os.makedirs(base, exist_ok=True)
    for lib in ("numpy", "pygame"):
        if lib == "pygame":
            if not need_pygame:
                continue
            try:
                import pygame  # noqa: F401  (system pygame wins)
                _log("using system pygame", pygame.version.ver)
                continue
            except Exception:
                pass
        dest = os.path.join(base, lib)
        if not os.path.isdir(dest):
            whl = [w for w in have if w.startswith(lib + "-") and ("-%s-" % tag) in w]
            if not whl:
                _log("no bundled %s for Python %d.%d" % ((lib,) + sys.version_info[:2]))
                continue
            _log("first run: unpacking", whl[0])
            _unpack(os.path.join(wheels, whl[0]), dest)
        sys.path.insert(0, dest)
        _log("using bundled", lib, "for", tag)
