#!/bin/bash
# Build the PortMaster ports: one zip per app, for any firmware that runs PortMaster
# (KNULLI, muOS, ROCKNIX, ArkOS, NextUI / NX Redux on the TrimUI Brick, and more).
#   dist/brickchord-<ver>-portmaster.zip   dist/bricklab-<ver>-portmaster.zip
#   dist/brickglide-<ver>-portmaster.zip
# Each runs on PortMaster's python_3.11 runtime (fetched by PortMaster on first launch)
# with its own pylib/: NumPy 1.26.4 (manylinux2014 aarch64 wheel) and pygame 2.6.1
# built for that runtime against the device's own SDL2. That pygame build comes from
# PortMaster's "Angry Drunken Dwarves" port (LGPL; see its README for how it was built),
# so it uses each firmware's SDL2 and works with its screen and audio.
# Also writes dist/portmaster-new/ports/<name>/ folders laid out for a PortMaster-New PR.
# Usage: tools/build_portmaster.sh [version]
set -e
VER="${1:-v0.4.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"
WORK="$(mktemp -d)"
mkdir -p "$OUT"

# ---- shared libraries
python3 -m pip download -q --only-binary=:all: --no-deps --platform manylinux2014_aarch64 \
    --implementation cp --python-version 311 -d "$WORK/whl" numpy==1.26.4
git clone -q --filter=blob:none --no-checkout --depth 1 https://github.com/PortsMaster/PortMaster-New "$WORK/pmnew"
(cd "$WORK/pmnew" && git sparse-checkout set --no-cone /ports/angrydd/angrydd/gamedata.tar.gz \
    /ports/angrydd/angrydd/licenses/pygame-LGPL.txt && git checkout -q)
mkdir -p "$WORK/pg" "$WORK/pylib"
tar xzf "$WORK/pmnew/ports/angrydd/angrydd/gamedata.tar.gz" -C "$WORK/pg" pylib/pygame
cp -R "$WORK/pg/pylib/pygame" "$WORK/pylib/"
(cd "$WORK/pylib" && unzip -q "$WORK"/whl/numpy-*.whl -x 'numpy/*/tests/*' 'numpy/tests/*' 'numpy/typing/tests/*')
NPLIC="$(ls "$WORK"/pylib/numpy-*.dist-info/LICENSE.txt)"
grep -q 'ver = "2.6.1"' "$WORK/pylib/pygame/version.py"

build() {   # build <dir> <title> <edition> <short description> <genre>
    local DIR="$1" TITLE="$2" ED="$3" DESC="$4" GENRE="$5"
    local STAGE="$WORK/stage_$DIR"
    local APP="$STAGE/$DIR"
    mkdir -p "$APP/samples" "$APP/licenses"
    cp "$ROOT"/brickchord/*.py "$ROOT/brickchord/README.txt" "$ROOT/brickchord/samples_README.txt" "$APP/"
    cp -R "$ROOT/brickchord/kits" "$ROOT/brickchord/demos" "$ROOT/brickchord/fonts" "$APP/"
    cp "$ROOT"/brickchord/samples/*.wav "$APP/samples/" 2>/dev/null || true
    [ "$ED" != "chord" ] && printf '%s\n' "$ED" > "$APP/edition.txt"
    cp -R "$WORK/pylib" "$APP/pylib"
    cp "$ROOT/LICENSE" "$APP/licenses/brickchord-MIT.txt"
    cp "$WORK/pmnew/ports/angrydd/angrydd/licenses/pygame-LGPL.txt" "$APP/licenses/"
    cp "$NPLIC" "$APP/licenses/numpy-LICENSE.txt"
    cp "$ROOT/brickchord/fonts/Inter-LICENSE.txt" "$APP/licenses/Inter-OFL.txt"
    sed -e "s/@TITLE@/$TITLE/g" -e "s/@DIR@/$DIR/g" -e "s/@EDITION@/$ED/g" \
        "$ROOT/portmaster/launcher.sh.in" > "$STAGE/$TITLE.sh"
    chmod +x "$STAGE/$TITLE.sh"
    # 640x480 in-app screenshot (PortMaster listing); add portmaster/screenshots/<dir>.png
    [ -f "$ROOT/portmaster/screenshots/$DIR.png" ] && cp "$ROOT/portmaster/screenshots/$DIR.png" "$APP/screenshot.png"
    cat > "$APP/port.json" <<EOF
{
  "version": 4,
  "name": "$DIR.zip",
  "items": ["$TITLE.sh", "$DIR"],
  "items_opt": [],
  "attr": {
    "title": "$TITLE",
    "porter": ["Michael Tietjen"],
    "desc": "$DESC",
    "desc_md": "",
    "inst": "Ready to run. On first launch, press each button once so it learns your controls. Quit from Settings > Quit.",
    "inst_md": "",
    "genres": ["$GENRE"],
    "image": null,
    "rtr": true,
    "exp": false,
    "runtime": ["python_3.11"],
    "store": [],
    "availability": "full",
    "reqs": [],
    "arch": ["aarch64"],
    "min_glibc": ""
  }
}
EOF
    cat > "$APP/gameinfo.xml" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<gameList>
  <game>
    <path>./$TITLE.sh</path>
    <name>$TITLE</name>
    <desc>$DESC</desc>
    <releasedate>20261104T000000</releasedate>
    <developer>Michael Tietjen</developer>
    <publisher>Open Source</publisher>
    <genre>Music</genre>
    <image>./$DIR/screenshot.png</image>
  </game>
</gameList>
EOF
    cat > "$APP/README.md" <<EOF
## Notes

$TITLE is by Michael Tietjen, free and open source (MIT): https://github.com/michaeltietjen/brickchord
Site and guide: https://michaeltietjen.github.io/brickchord/

$DESC

Runs on PortMaster's Python 3.11 runtime. NumPy and pygame are bundled in pylib/; the pygame
build (2.6.1, against the device's own SDL2) is the one from PortMaster's Angry Drunken
Dwarves port. Thanks to the PortMaster team.

On first launch it asks you to press each button and push each stick once, so it works
with any controller layout. Settings opens with SELECT. Quit from Settings > Quit.

Tested on: TrimUI Brick Pro (KNULLI). Reports from other devices and firmwares are welcome.

## Controls

| Button | Action |
|--|--|
| D-pad, A, B, X | The seven chords of the key |
| L1 / R1 / Y | 7th / sus4 / flip the voicing |
| Left stick | Chord colors and bends |
| Right stick | Filter and effects |
| START | Beat, play or progression |
| SELECT | Settings (Quit is there) |

Each app shows its current controls at the bottom of the screen and in Settings.
EOF
    local ZIP="$OUT/$DIR-$VER-portmaster.zip"
    rm -f "$ZIP"
    (cd "$STAGE" && COPYFILE_DISABLE=1 zip -qr -X "$ZIP" "$TITLE.sh" "$DIR")
    # a PortMaster-New style folder (port.json etc. beside the launcher)
    local PR="$OUT/portmaster-new/ports/$DIR"
    rm -rf "$PR"
    mkdir -p "$PR"
    cp -R "$STAGE/$TITLE.sh" "$STAGE/$DIR" "$PR/"
    mv "$PR/$DIR/port.json" "$PR/$DIR/gameinfo.xml" "$PR/$DIR/README.md" "$PR/"
    [ -f "$PR/$DIR/screenshot.png" ] && mv "$PR/$DIR/screenshot.png" "$PR/"
    ls -l "$ZIP"
}

build brickchord Brickchord chord \
  "A pocket chord machine: one button per chord, always in key. Bend chords with the stick, 23 synth sounds, strums, arps, drones, an effects rack and backing beats." \
  "other"
build bricklab Bricklab lab \
  "A pocket groovebox: Brickchord plus a step drum machine with kits and your own samples, 6 recorded tracks per pattern with their own sounds and effects, and 16 patterns chained into songs." \
  "other"
build brickglide Brickglide glide \
  "An ambient machine on the Brickchord engine: six gliding voices, chords that glide into each other, blooms, drones, scenes and a live spectrogram." \
  "other"
rm -rf "$WORK"
