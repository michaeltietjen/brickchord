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
    return "lab" if v.startswith("lab") else ("ambient" if v.startswith("amb") else "chord")


EDITION = _read()
LAB = EDITION == "lab"
AMBIENT = EDITION == "ambient"           # Brickambient: drones, long glides, scenes
NAME = "Bricklab" if LAB else ("Brickambient" if AMBIENT else "Brickchord")
