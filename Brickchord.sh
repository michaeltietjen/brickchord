#!/bin/sh
# Brickchord: pocket chord machine with an analog-VA voice (KNULLI port)
APPDIR=/userdata/roms/ports/brickchord
cd "$APPDIR" || exit 1
command -v python3 >/dev/null 2>&1 || { echo 'python3 not found' >&2; exit 127; }
[ -f brickchord.log ] && mv -f brickchord.log brickchord.prev.log
{ printf '=== Brickchord %s ===\n' "$(date)"; python3 -u -B "$APPDIR/launch.py"; echo "exit $?"; } > "$APPDIR/brickchord.log" 2>&1
