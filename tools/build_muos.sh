#!/bin/bash
# Build the muOS / PortMaster-family zip: Brickchord + Bricklab from one folder,
# with NumPy and pygame wheels for aarch64 Python 3.9-3.12 (unpacked on first
# launch). Usage: tools/build_muos.sh [version]
set -e
VER="${1:-v0.3.0-test}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"
STAGE="$(mktemp -d)"
APP="$STAGE/ports/brickchord"
mkdir -p "$APP/_vendor/wheels" "$APP/samples" "$OUT"
cp "$ROOT"/brickchord/*.py "$ROOT/brickchord/README.txt" "$ROOT/brickchord/samples_README.txt" "$APP/"
cp -R "$ROOT/brickchord/kits" "$ROOT/brickchord/demos" "$APP/"
cp "$ROOT/LICENSE" "$APP/LICENSE.txt"
cp "$ROOT/muos/Brickchord.sh" "$ROOT/muos/Bricklab.sh" "$STAGE/ports/"
chmod +x "$STAGE/ports/"*.sh
cp "$ROOT/muos/INSTALL-MUOS.txt" "$STAGE/"
W="$APP/_vendor/wheels"
dl() { python3 -m pip download -q --only-binary=:all: --no-deps \
         --platform manylinux2014_aarch64 --implementation cp --python-version "$1" -d "$W" "$2"; }
for v in 39 310 311 312; do dl $v numpy==1.26.4; dl $v pygame==2.5.2; done
ZIP="$OUT/brickchord-bricklab-muos-$VER.zip"
rm -f "$ZIP"
(cd "$STAGE" && COPYFILE_DISABLE=1 zip -qr -X "$ZIP" INSTALL-MUOS.txt ports)
rm -rf "$STAGE"
ls -l "$ZIP"
