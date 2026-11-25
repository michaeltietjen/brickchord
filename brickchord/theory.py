"""Music theory shared by the apps and Bricklab web: scales, chords built on a
scale degree, their names, and the smooth voicing the chord buttons use.
Pure Python (no pygame), so the browser can run it too."""


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
SCALES = {"Major": [0, 2, 4, 5, 7, 9, 11], "Minor": [0, 2, 3, 5, 7, 8, 10],
          "Dorian": [0, 2, 3, 5, 7, 9, 10], "Mixolydian": [0, 2, 4, 5, 7, 9, 10]}
SCALE_NAMES = list(SCALES)
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII"]

MOD_KEYS = ("flip", "seventh", "sus", "ninth", "sus2", "dim", "aug", "maj7")


# Spelling: flat keys get flat names (Db, not C#). The scale's parent major decides.
_PARENT = {"Major": 0, "Minor": 3, "Dorian": 10, "Phrygian": 8, "Lydian": 7, "Mixolydian": 5, "Locrian": 1,
           "Harmonic Minor": 3, "Melodic Minor": 3}
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]


def note_name(pc, key=None, scale=None):
    if key is not None:
        parent = (key + _PARENT.get(scale, 0)) % 12
        if parent in (5, 10, 3, 8, 1, 6):
            return FLAT_NAMES[pc % 12]
    return NOTE_NAMES[pc % 12]


def build_chord(key, scale, degree, m):
    """m: dict with any of MOD_KEYS set True."""
    sc = SCALES[scale]

    def tone(i):
        return sc[(degree + i) % 7] + 12 * ((degree + i) // 7)

    root = tone(0)
    third = tone(2) - root
    fifth = tone(4) - root
    sev = tone(6) - root
    if m.get("flip"):
        third = 3 if third == 4 else 4
        if fifth == 6:
            fifth = 7
        sev = 10 if sev == 11 or third == 3 else sev
    if m.get("dim"):
        third, fifth, sev = 3, 6, 10
    if m.get("aug"):
        third, fifth = 4, 8
    if m.get("maj7"):
        sev = 11
    ivals = [0, third, fifth]
    sus = bool(m.get("sus"))
    sus2 = bool(m.get("sus2")) and not sus
    if sus:
        ivals[1] = 5
    elif sus2:
        ivals[1] = 2
    if m.get("seventh") or m.get("ninth") or m.get("maj7"):
        ivals.append(sev)
    if m.get("ninth"):
        ivals.append(14)
    pc_root = (key + root) % 12
    return pc_root, ivals, chord_name(pc_root, ivals, sus, sus2, key, scale)


def chord_name(pc, iv, sus, sus2=False, key=None, scale=None):
    s = set(i % 12 for i in iv)
    third = 3 if 3 in s and not sus else (4 if 4 in s else None)
    fifth = 6 if 6 in s else (8 if 8 in s else 7)
    has7 = 10 in s or 11 in s
    maj7 = 11 in s
    has9 = 2 in s and not sus2
    n = note_name(pc, key, scale)
    if sus2:
        return n + ("maj7sus2" if maj7 else ("7sus2" if has7 else "sus2"))
    if sus:
        q = ("7sus4" if has7 else "sus4")
        if has9:
            q = "9sus4"
        return n + q
    if third == 4 and fifth == 8:
        return n + ("augMaj7" if maj7 else ("aug7" if has7 else "aug"))
    if third == 3 and fifth == 6:
        if has7:
            return n + ("m7b5" if not maj7 else "mMaj7b5")
        return n + "dim"
    base = "m" if third == 3 else ""
    if has9:
        return n + base + ("maj9" if maj7 else "9") if base == "" else n + ("m9" if not maj7 else "mMaj9")
    if has7:
        if base == "m":
            return n + ("mMaj7" if maj7 else "m7")
        return n + ("maj7" if maj7 else "7")
    return n + base


def roman_for(degree, ivals):
    r = ROMAN[degree]
    s = set(i % 12 for i in ivals)
    if 3 in s and 5 not in s:
        r = r.lower()
    if 6 in s and 7 not in s:
        r += "°"
    return r


def voice(pc_root, ivals, prev, octave):
    bass = 36 + pc_root
    if bass < 40:
        bass += 12
    center = (sum(prev) / len(prev)) if prev else 64
    upper = []
    for iv in ivals:
        pc = (pc_root + iv) % 12
        cands = [pc + 12 * o for o in range(3, 8)]
        best = min(cands, key=lambda m: (abs(m - center), m))
        best = clamp(best, 55, 79)
        if best not in upper:
            upper.append(best)
    upper.sort()
    return [bass + 12 * octave] + [m + 12 * octave for m in upper], upper
