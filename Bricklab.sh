#!/bin/sh
# Bricklab: Brickchord plus song mode (patterns into songs). Shares Brickchord's sound cache.
APPDIR=/userdata/roms/ports/bricklab
cd "$APPDIR" || exit 1
command -v python3 >/dev/null 2>&1 || { echo 'python3 not found' >&2; exit 127; }
[ -f bricklab.log ] && mv -f bricklab.log bricklab.prev.log
{ printf '=== Bricklab %s ===\n' "$(date)"; python3 -u -B "$APPDIR/launch.py"; echo "exit $?"; } > "$APPDIR/bricklab.log" 2>&1
