#!/bin/bash
# Build the R36Max / ArkOS-family zip: app code + NumPy/pygame wheels for
# aarch64, Python 3.7-3.12 (unpacked on the device at first launch).
# Usage: r36/build_zip.sh [version]
set -e
VER="${1:-v0.2.0-alpha}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"
STAGE="$(mktemp -d)"
APP="$STAGE/ports/brickchord"
mkdir -p "$APP/_vendor/wheels" "$OUT"
cp "$ROOT"/brickchord/*.py "$ROOT/brickchord/README.txt" "$APP/"
cp "$ROOT/LICENSE" "$APP/LICENSE.txt"
cp "$ROOT/r36/Brickchord.sh" "$STAGE/ports/"
chmod +x "$STAGE/ports/Brickchord.sh"
cp "$ROOT/r36/INSTALL-R36.txt" "$STAGE/"
W="$APP/_vendor/wheels"
dl() { python3 -m pip download -q --only-binary=:all: --no-deps \
         --platform manylinux2014_aarch64 --implementation cp --python-version "$1" -d "$W" "$2"; }
dl 37 numpy==1.21.6
dl 38 numpy==1.24.4
for v in 39 310 311 312; do dl $v numpy==1.26.4; done
for v in 37 38 39 310 311 312; do dl $v pygame==2.5.2; done
ZIP="$OUT/brickchord-r36max-$VER.zip"
rm -f "$ZIP"
(cd "$STAGE" && COPYFILE_DISABLE=1 zip -qr -X "$ZIP" INSTALL-R36.txt ports)
rm -rf "$STAGE"
ls -l "$ZIP"
