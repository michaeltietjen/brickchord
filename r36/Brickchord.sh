#!/bin/bash
# Brickchord: pocket chord machine with an analog-VA voice
# R36Max / R36S / ArkOS-family port. Put this file and the brickchord/ folder
# in the ports folder of the SD card, then restart EmulationStation.

PORTDIR="$(cd "$(dirname "$0")" && pwd)"
APPDIR="$PORTDIR/brickchord"
LOG="$APPDIR/brickchord.log"
cd "$APPDIR" || exit 1
[ -f "$LOG" ] && mv -f "$LOG" "$APPDIR/brickchord.prev.log"

{
  printf '=== Brickchord (R36) %s ===\n' "$(date)"
  uname -a
  PY="$(command -v python3)"
  if [ -z "$PY" ]; then
    echo "python3 not found on this firmware. Install ArkOS or dArkOS, which include Python 3."
    exit 127
  fi
  echo "python3: $PY ($("$PY" --version 2>&1))"
  # free the CPU for audio: performance governor while we run (ignored if not allowed)
  OLDGOV="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)"
  echo performance | sudo -n tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor >/dev/null 2>&1
  "$PY" -u -B "$APPDIR/launch.py"
  RC=$?
  # some firmwares need the KMS driver named explicitly when the bundled pygame is used
  if [ $RC -ne 0 ] && grep -q "No available video device\|video system not initialized" "$LOG" 2>/dev/null; then
    echo "retrying with SDL_VIDEODRIVER=kmsdrm"
    SDL_VIDEODRIVER=kmsdrm "$PY" -u -B "$APPDIR/launch.py"
    RC=$?
  fi
  [ -n "$OLDGOV" ] && echo "$OLDGOV" | sudo -n tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor >/dev/null 2>&1
  echo "exit $RC"
} > "$LOG" 2>&1
