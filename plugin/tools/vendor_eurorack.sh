#!/bin/sh
# vendor.sh <eurorack checkout> <plugin dir>: the parts of the open-source engines the plugin uses
S="$1"; D="$2/third_party/eurorack"
rm -rf "$D"; mkdir -p "$D/stmlib" "$D/clouds" "$D/rings"
cp "$S"/stmlib/*.h "$D/stmlib/"; cp -R "$S/stmlib/dsp" "$S/stmlib/utils" "$S/stmlib/fft" "$D/stmlib/"
cp "$S"/clouds/resources.* "$D/clouds/"; cp -R "$S/clouds/dsp" "$D/clouds/"; mkdir -p "$D/clouds/drivers"; cp "$S/clouds/drivers/debug_pin.h" "$D/clouds/drivers/"
cp "$S"/rings/resources.* "$D/rings/"; cp -R "$S/rings/dsp" "$D/rings/"
find "$D" -name "*.py" -delete; find "$D" -name "makefile*" -delete
cat > "$D/README.md" <<'T'
Parts of https://github.com/pichenettes/eurorack (commit f4cfa76) and its stmlib submodule: the granular
processor from clouds, the resonator from rings, and the stmlib code they need. Copyright Emilie Gillet,
MIT licence (each file's header carries the notice). Bricklab Studio uses the engine code only; it is not
made, endorsed or supported by the original author or her company.
T
