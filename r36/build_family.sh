#!/bin/bash
# Build the R36 family zip: Brickchord, Bricklab and Brickglide for the R36Max,
# R36S and other ArkOS-family handhelds, sharing one set of NumPy/pygame wheels
# (aarch64, Python 3.7-3.12, unpacked on the device at first launch).
# Usage: r36/build_family.sh [version]
set -e
VER="${1:-v0.4.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"
STAGE="$(mktemp -d)"
P="$STAGE/ports"
mkdir -p "$P/brick_vendor/wheels" "$OUT"
app() {   # app <dir> <Name> <edition or empty> <description>
    local D="$1" N="$2" E="$3" DESC="$4"
    mkdir -p "$P/$D/samples"
    cp "$ROOT"/brickchord/*.py "$ROOT/brickchord/README.txt" "$P/$D/"
    cp -R "$ROOT/brickchord/kits" "$ROOT/brickchord/demos" "$ROOT/brickchord/fonts" "$P/$D/"
    cp "$ROOT"/brickchord/samples/*.wav "$P/$D/samples/" 2>/dev/null || true
    cp "$ROOT/LICENSE" "$P/$D/LICENSE.txt"
    [ -n "$E" ] && printf '%s\n' "$E" > "$P/$D/edition.txt"
    sed -e "s/@NAME@/$N/g" -e "s/@DIR@/$D/g" -e "s/@DESC@/$DESC/g" "$ROOT/r36/launcher.sh.in" > "$P/$N.sh"
    chmod +x "$P/$N.sh"
}
app brickchord Brickchord "" "pocket chord machine with an analog-VA voice"
app bricklab Bricklab lab "the groovebox: looper, patterns, machines, drums"
app brickglide Brickglide glide "chords that glide: an ambient machine"
W="$P/brick_vendor/wheels"
dl() { python3 -m pip download -q --only-binary=:all: --no-deps \
         --platform manylinux2014_aarch64 --implementation cp --python-version "$1" -d "$W" "$2"; }
dl 37 numpy==1.21.6
dl 38 numpy==1.24.4
for v in 39 310 311 312; do dl $v numpy==1.26.4; done
for v in 37 38 39 310 311 312; do dl $v pygame==2.5.2; done
cp "$ROOT/r36/INSTALL-R36.txt" "$STAGE/"
ZIP="$OUT/brick-family-r36-$VER.zip"
rm -f "$ZIP"
(cd "$STAGE" && COPYFILE_DISABLE=1 zip -qr -X "$ZIP" INSTALL-R36.txt ports)
rm -rf "$STAGE"
ls -l "$ZIP"
