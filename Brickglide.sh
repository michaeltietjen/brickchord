#!/bin/sh
# Brickglide: the ambient machine on the Brickchord engine. Shares Brickchord's sound cache.
APPDIR=/userdata/roms/ports/brickglide
cd "$APPDIR" || exit 1
command -v python3 >/dev/null 2>&1 || { echo 'python3 not found' >&2; exit 127; }
[ -f brickglide.log ] && mv -f brickglide.log brickglide.prev.log
# Audio needs steady CPU: run the cores at full speed while the app is open, then
# put the governor back. (A governor that scales down between notes makes blocks
# late when the load jumps, which you hear as clicks.)
GOV=/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
OLDGOV=$(cat $GOV 2>/dev/null)
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > "$g" 2>/dev/null; done
usbcheck() {
  echo "--- USB / MIDI / sound check ---"
  echo "sound cards:"; cat /proc/asound/cards 2>&1
  echo "sound devices:"; ls -l /dev/snd 2>&1
  echo "midi ports:"; ls /dev/snd/midiC* /dev/midi* 2>/dev/null || echo "  none"
  echo "audio inputs (capture):"; grep capture /proc/asound/pcm 2>/dev/null || echo "  none"
  echo "arecord:"; (command -v arecord && arecord -l) 2>&1 | head -20
  echo "usb devices:"; (command -v lsusb >/dev/null && lsusb) || cat /sys/bus/usb/devices/*/product 2>/dev/null
  echo "usb roles:"; cat /sys/class/usb_role/*/role 2>/dev/null; cat /sys/devices/platform/*usb*/*/mode 2>/dev/null
  echo "kernel (usb, midi, audio):"; dmesg 2>/dev/null | grep -i -E "usb|midi|audio|snd" | tail -25
  echo "--- end check ---"
}
{ printf '=== Brickglide %s ===\n' "$(date)"; echo "cpu governor: $OLDGOV -> $(cat $GOV 2>/dev/null)"; usbcheck; python3 -u -B "$APPDIR/launch.py"; echo "exit $?"; } > "$APPDIR/brickglide.log" 2>&1
[ -n "$OLDGOV" ] && for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo "$OLDGOV" > "$g" 2>/dev/null; done
