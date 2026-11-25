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
    if v.startswith("chop"):
        return "chop"
    return "lab" if v.startswith("lab") else ("ambient" if v.startswith(("amb", "glide")) else "chord")


_RAW = ""


EDITION = _read()
LAB = EDITION == "lab"
AMBIENT = EDITION == "ambient"           # Brickglide: drones, long glides, chords, scenes
PLAY = AMBIENT   # Brickglide plays melody over the progression, strums, arps, samples and MIDI (was the Play fork)
CHOP = EDITION == "chop"                 # Brickchop: a K.O. II-style sampler, chop and play on pads
NAME = "Bricklab" if LAB else ("Brickglide" if AMBIENT else ("Brickchop" if CHOP else "Brickchord"))
