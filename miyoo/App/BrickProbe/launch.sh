#!/bin/sh
# Brick Probe: lists what this Miyoo Mini has for running Brickchord (Python, NumPy,
# SDL, sound, CPU, memory). Changes nothing. The report goes to the SD card root:
# brickprobe.txt. Send that file to the Brickchord developer.
OUT=/mnt/SDCARD/brickprobe.txt
{
  echo "=== Brick Probe $(date) ==="
  echo "--- system";  uname -a; cat /proc/version 2>/dev/null
  echo "--- onion";   cat /mnt/SDCARD/.tmp_update/onionVersion/version.txt 2>/dev/null
  echo "--- cpu";     grep -E "model name|Processor|Hardware|Features|BogoMIPS" /proc/cpuinfo 2>/dev/null | sort -u
  echo "cores: $(grep -c ^processor /proc/cpuinfo)"
  cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies 2>/dev/null
  cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null
  echo "--- memory";  free 2>/dev/null || head -3 /proc/meminfo
  echo "--- libc";    ls -l /lib/libc.so* /lib/ld-linux* /lib/libc-* 2>/dev/null; /lib/libc.so.6 2>&1 | head -1
  echo "--- python";  for p in python python2 python3 python3.7 python3.9 python3.11; do command -v $p && $p -c "import sys; print(sys.version)" 2>&1; done
  find / -maxdepth 6 \( -name "python3*" -o -name "python2*" -o -name "libpython*" \) 2>/dev/null | grep -v /proc | head -40
  echo "--- numpy / pygame on the card"
  find /mnt/SDCARD -maxdepth 6 -type d \( -name numpy -o -name pygame \) 2>/dev/null | head -20
  echo "--- SDL";     find / -maxdepth 5 -name "libSDL*" 2>/dev/null | grep -v /proc | head -30
  echo "--- sound";   cat /proc/asound/cards 2>/dev/null; ls -l /dev/snd /dev/dsp* 2>/dev/null; ls /dev/mi_ao 2>/dev/null
  echo "--- display"; cat /sys/class/graphics/fb0/virtual_size 2>/dev/null; cat /sys/class/graphics/fb0/bits_per_pixel 2>/dev/null
  echo "--- input";   cat /proc/bus/input/devices 2>/dev/null | grep -E "Name|Handlers"
  echo "--- usb midi"; ls /dev/snd/midi* /dev/midi* 2>/dev/null || echo none
  echo "--- storage"; df -h /mnt/SDCARD 2>/dev/null
  echo "=== end ==="
} > "$OUT" 2>&1
sync
