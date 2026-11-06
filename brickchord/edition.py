# Which app this folder runs as. A file named edition.txt next to this one
# containing "lab" makes it Bricklab (Brickchord plus song mode); without it
# the app is Brickchord, the chord machine.
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _read():
    v = os.environ.get("BRICK_EDITION")
    if not v:
        try:
            with open(os.path.join(APP_DIR, "edition.txt")) as f:
                v = f.read().strip()
        except Exception:
            v = "chord"
    v = v.lower()
    global _RAW
    _RAW = v
    return "lab" if v.startswith("lab") else ("ambient" if v.startswith(("amb", "glide")) else "chord")


_RAW = ""


EDITION = _read()
LAB = EDITION == "lab"
AMBIENT = EDITION == "ambient"           # Brickglide: drones, long glides, chords, scenes
PLAY = AMBIENT and _RAW.startswith("glideplay")   # the Brickglide Play fork: melody over the progression
NAME = "Bricklab" if LAB else (("Brickglide Play" if PLAY else "Brickglide") if AMBIENT else "Brickchord")
