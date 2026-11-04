#!/bin/sh
# Brickambient: the ambient machine on the Brickchord engine. Shares Brickchord's sound cache.
APPDIR=/userdata/roms/ports/brickambient
cd "$APPDIR" || exit 1
command -v python3 >/dev/null 2>&1 || { echo 'python3 not found' >&2; exit 127; }
[ -f brickambient.log ] && mv -f brickambient.log brickambient.prev.log
# Audio needs steady CPU: run the cores at full speed while the app is open, then
# put the governor back. (A governor that scales down between notes makes blocks
# late when the load jumps, which you hear as clicks.)
GOV=/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
OLDGOV=$(cat $GOV 2>/dev/null)
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > "$g" 2>/dev/null; done
{ printf '=== Brickambient %s ===\n' "$(date)"; echo "cpu governor: $OLDGOV -> $(cat $GOV 2>/dev/null)"; python3 -u -B "$APPDIR/launch.py"; echo "exit $?"; } > "$APPDIR/brickambient.log" 2>&1
[ -n "$OLDGOV" ] && for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo "$OLDGOV" > "$g" 2>/dev/null; done
