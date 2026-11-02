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
    return "lab" if v.lower().startswith("lab") else "chord"


EDITION = _read()
LAB = EDITION == "lab"
NAME = "Bricklab" if LAB else "Brickchord"
