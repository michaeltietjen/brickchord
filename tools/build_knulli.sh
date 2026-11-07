#!/bin/bash
# Build the KNULLI release zips (TrimUI Brick Pro and other KNULLI devices):
#   dist/brickchord-<ver>-knulli.zip  and  dist/bricklab-<ver>-knulli.zip
# Each holds the app folder (code, kits, demos, samples, NumPy for Python 3.12
# aarch64), its launcher and its menu artwork, laid out like roms/ports.
# Usage: tools/build_knulli.sh [version]
set -e
VER="${1:-v0.3.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"
mkdir -p "$OUT"
WHL="$(mktemp -d)"
python3 -m pip download -q --only-binary=:all: --no-deps --platform manylinux2014_aarch64 \
    --implementation cp --python-version 312 -d "$WHL" numpy==1.26.4

build() {   # build <folder name> <launcher> <edition or empty> <image prefix>
    local NAME="$1" SH="$2" ED="$3" IMG="$4"
    local STAGE="$(mktemp -d)"
    local APP="$STAGE/$NAME"
    mkdir -p "$APP/_vendor" "$APP/samples" "$STAGE/images"
    cp "$ROOT"/brickchord/*.py "$ROOT/brickchord/README.txt" "$ROOT/brickchord/samples_README.txt" "$APP/"
    cp -R "$ROOT/brickchord/kits" "$ROOT/brickchord/demos" "$ROOT/brickchord/fonts" "$APP/"
    cp "$ROOT"/brickchord/samples/*.wav "$APP/samples/" 2>/dev/null || true
    [ -d "$ROOT/brickchord/samples/textures" ] && cp -R "$ROOT/brickchord/samples/textures" "$APP/samples/"
    [ -f "$ROOT/brickchord/samples/samples.json" ] && cp "$ROOT/brickchord/samples/samples.json" "$APP/samples/"
    cp "$ROOT/LICENSE" "$APP/LICENSE.txt"
    [ -n "$ED" ] && printf '%s\n' "$ED" > "$APP/edition.txt"
    (cd "$APP/_vendor" && unzip -q "$WHL"/numpy-*.whl -x 'numpy/*/tests/*' 'numpy/tests/*' 'numpy/typing/tests/*')
    cp "$ROOT/$SH" "$STAGE/"
    chmod +x "$STAGE/$SH"
    cp "$ROOT/docs/$IMG-image.png" "$ROOT/docs/$IMG-marquee.png" "$STAGE/images/"
    cat > "$STAGE/INSTALL.txt" <<EOF
$NAME $VER for KNULLI

1. Copy everything in this zip into roms/ports on the SD card (over the network share
   or with a card reader): the $NAME folder, $SH and the images folder.
2. On the device: Main menu > Game settings > Update gamelists. $NAME appears under Ports.
3. On first launch, press each button and push each stick once so it learns your controls.

Logs: roms/ports/$NAME/$NAME.log. Source and issues: https://github.com/michaeltietjen/brickchord
EOF
    local ZIP="$OUT/$NAME-$VER-knulli.zip"
    rm -f "$ZIP"
    (cd "$STAGE" && COPYFILE_DISABLE=1 zip -qr -X "$ZIP" INSTALL.txt "$NAME" "$SH" images)
    rm -rf "$STAGE"
    ls -l "$ZIP"
}

build brickchord Brickchord.sh "" brickchord
build bricklab Bricklab.sh lab bricklab
build brickglide Brickglide.sh glide bricklab
build brickchop Brickchop.sh chop bricklab
rm -rf "$WHL"
