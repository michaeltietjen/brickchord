#!/bin/bash
# Brickchord for muOS / PortMaster-family firmware (experimental).
# Put this file and the brickchord/ folder in the ports folder, or install the
# zip through PortMaster. Bricklab.sh launches the groovebox from the same folder.
EDITION="${BRICK_EDITION:-chord}"
NAME="Brickchord"; [ "$EDITION" = "lab" ] && NAME="Bricklab"

# PortMaster control folder (gives $directory, $ESUDO, controller setup) when present
XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
if [ -d "/opt/system/Tools/PortMaster/" ]; then controlfolder="/opt/system/Tools/PortMaster"
elif [ -d "/opt/tools/PortMaster/" ]; then controlfolder="/opt/tools/PortMaster"
elif [ -d "$XDG_DATA_HOME/PortMaster/" ]; then controlfolder="$XDG_DATA_HOME/PortMaster"
elif [ -d "/mnt/mmc/MUOS/PortMaster/" ]; then controlfolder="/mnt/mmc/MUOS/PortMaster"
else controlfolder="/roms/ports/PortMaster"; fi
if [ -f "$controlfolder/control.txt" ]; then
  source "$controlfolder/control.txt"
  [ -f "${controlfolder}/mod_${CFW_NAME}.txt" ] && source "${controlfolder}/mod_${CFW_NAME}.txt"
  get_controls 2>/dev/null
fi

PORTDIR="$(cd "$(dirname "$0")" && pwd)"
APPDIR="$PORTDIR/brickchord"
[ -d "$APPDIR" ] || APPDIR="/$directory/ports/brickchord"
LOG="$APPDIR/$(echo $NAME | tr A-Z a-z).log"
cd "$APPDIR" || exit 1
[ -f "$LOG" ] && mv -f "$LOG" "${LOG%.log}.prev.log"

{
  printf '=== %s (muOS/PortMaster build) %s ===\n' "$NAME" "$(date)"
  uname -a
  export BRICK_EDITION="$EDITION"
  PY="$(command -v python3)"
  if [ -z "$PY" ] || ! "$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then
    # no usable system Python: mount the PortMaster Python runtime
    RT="$(ls "$controlfolder"/libs/python*.squashfs 2>/dev/null | head -1)"
    if [ -z "$RT" ] && [ -f "$controlfolder/harbourmaster" ]; then
      $ESUDO "$controlfolder/harbourmaster" --quiet --no-check runtime_check "python_3.11.squashfs" 2>/dev/null
      RT="$(ls "$controlfolder"/libs/python*.squashfs 2>/dev/null | head -1)"
    fi
    if [ -n "$RT" ]; then
      PYDIR=/tmp/brickchord_python
      $ESUDO mkdir -p "$PYDIR"
      [[ "$PM_CAN_MOUNT" != "N" ]] && $ESUDO umount "$PYDIR" 2>/dev/null
      $ESUDO mount "$RT" "$PYDIR" && PY="$(ls "$PYDIR"/bin/python3* 2>/dev/null | head -1)"
      echo "python runtime: $RT -> $PY"
    fi
  fi
  if [ -z "$PY" ]; then
    echo "No Python 3.9+ found and no PortMaster Python runtime. Install the Python runtime from PortMaster > Options > Runtime Manager."
    exit 127
  fi
  echo "python3: $PY ($("$PY" --version 2>&1))"
  OLDGOV="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)"
  echo performance | $ESUDO tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor >/dev/null 2>&1
  "$PY" -u -B "$APPDIR/launch.py"
  RC=$?
  if [ $RC -ne 0 ] && grep -q "No available video device\|video system not initialized" "$LOG" 2>/dev/null; then
    echo "retrying with SDL_VIDEODRIVER=kmsdrm"
    SDL_VIDEODRIVER=kmsdrm "$PY" -u -B "$APPDIR/launch.py"
    RC=$?
  fi
  [ -n "$OLDGOV" ] && echo "$OLDGOV" | $ESUDO tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor >/dev/null 2>&1
  [ -n "$PYDIR" ] && [[ "$PM_CAN_MOUNT" != "N" ]] && $ESUDO umount "$PYDIR" 2>/dev/null
  echo "exit $RC"
} > "$LOG" 2>&1
