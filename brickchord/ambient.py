# Brickglide: an ambient machine on the Brickchord engine, played like Brickchord.
#
#   < ^ > v X A B            the seven chords of the key (I to VII): the voices glide into it
#                            and hold it; the same chord again lets it fade
#   L1 / R1 / L1+R1 / Y      with a chord: 7th / sus4 / 9th / flip major-minor (as in Brickchord)
#   hold a chord + left stick  Scrub: the stick plays the glide to that chord, as far as you
#                            push it; hold halfway for an in-between chord; let go to finish
#                            (or go back, or stay: Settings > Chords > Scrub release)
#   R2 + left stick          the Move compass: hold a direction and press a chord
#   L2 + left stick          Cloud compass (direction = texture, distance = amount)
#   right stick              filter and space, as in Brickchord
#   R2                       bloom: every voice from one note, fanning out into the chord
#   R2 + chord               that chord with the chosen Move (Settings > Chords): Bloom, Cascade,
#                            Spiral, Swoop, Scatter, Swap, Rise
#   L2 + chord button        recall a scene (SELECT + chord button saves one)
#   START                    stop everything; from silence, the progression plays by itself
#   L3                       glide guides / spectrogram
#   SELECT                   Settings (sounds, glide time and path, the progression, scenes)
#   SELECT + chord button    save a scene
import json
import os
import math
import time

import numpy as np
import pygame

import engine
import edition
import synth  # noqa

DRONE_BTNS = ["UP", "RIGHT", "DOWN", "LEFT", "X", "Y"]
MEL_BTNS = ["A", "B"]
GLYPH = {"UP": "^", "RIGHT": ">", "DOWN": "v", "LEFT": "<", "X": "X", "Y": "Y", "A": "A", "B": "B"}
VCOL = [(110, 200, 190), (190, 140, 255), (255, 170, 110), (120, 200, 140), (255, 120, 160), (140, 170, 255),
        (255, 215, 120), (235, 235, 225)]
NV = 8
GLIDES = [0.0, 0.5, 1, 2, 4, 8, 15, 30, 60]
FADES = [0.2, 0.5, 1, 2, 4, 8, 15]
STEP_TIMES = [0.5, 1, 2, 3, 4, 6, 8, 12, 16]
MORPHS = [1, 2, 4, 8, 15, 30, 60]
HIST_SECS = 24.0
# chords the drones can glide into: ("name", kind, steps). "deg" steps are scale
# degrees stacked on the chosen degree (they follow the key and scale); "semi"
# steps are fixed intervals in semitones from it.
CHORDS = [("Triad", "deg", [0, 2, 4]), ("Seventh", "deg", [0, 2, 4, 6]), ("Ninth", "deg", [0, 2, 4, 6, 8]),
          ("Eleventh", "deg", [0, 2, 4, 6, 8, 10]), ("Sus2", "semi", [0, 2, 7, 14]), ("Sus4", "semi", [0, 5, 7, 12, 17]),
          ("Quartal", "semi", [0, 5, 10, 15, 20]), ("Lydian", "semi", [0, 4, 6, 11, 14, 18]),
          ("Minor 11", "semi", [0, 3, 7, 10, 14, 17]), ("Major 9", "semi", [0, 4, 7, 11, 14]),
          ("Fifths", "semi", [0, 7, 14, 21]), ("Cluster", "semi", [0, 2, 3, 5, 7]), ("Open", "semi", [0, 7, 16, 19, 26])]
# Glide paths: the curve each voice draws between two notes (the engine's shape number is
# the index, except Scale steps, which walks the notes of the scale on the way)
PATHS = ["Smooth", "Linear", "Ease", "Swell", "Bounce", "Late", "Snap", "Wobble", "Semitones", "Scale steps"]
SCALE_STEPS = 9
# Glide timing: how long each voice takes
TIMINGS = ["Together", "By distance", "Bass lags", "Bass leads", "Loose"]
# Moves: how the voices travel into the next chord when you ask for more than a plain glide
MOVES = ["Bloom", "Cascade up", "Cascade down", "Spiral", "Swoop", "Scatter", "Converge", "Fall"]
ORDERS = ["Together", "Low first", "High first", "Outside in", "Random"]
STAGGERS = [0, 0.5, 1, 2, 3, 5, 8]
CHORD_TIMES = [0.25, 0.4, 0.6, 1, 2, 4, 6, 8, 12, 20, 30, 60]
PROG_TIMES = [1, 2, 3, 4, 6, 8, 12, 16]
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII"]
BEND_RANGES = [1, 2, 3, 5, 7, 12, 24]                   # semitones at full stick
SNAPS = ["Scale", "Semitone", "Free"]                    # where a bent voice settles when you let go


def M():
    import main
    return main


def _find(bank, name):
    return next(p for p in bank if p["name"] == name)


def amb_bank():
    """The sounds a voice can be: sustaining drones and pads first, struck and
    plucked ones (for the melodic voices) after."""
    out = list(synth.DRONE_PATCHES)
    for n in ("Saw Bass", "Square Bass", "Supersaw", "Juno Strings", "Poly Pad", "Prophet Brass", "Bowed String",
              "Bowed Glass", "Blown Pipe",
              "Vowel Choir", "Organ Pipes",
              "Folded Sine", "Bell Bowl", "Marimba", "Kalimba", "Plucked String", "Twin Strings"):
        try:
            out.append(_find(synth.MACRO_PATCHES, n))
        except StopIteration:
            pass
    for n in ("Choir Pad", "Air Pad", "Glass Bells"):
        try:
            out.append(_find(synth.PATCHES, n))
        except StopIteration:
            pass
    if edition.PLAY:
        # any WAV in samples/ (this app's, and Bricklab's and Brickchord's next to it)
        # as a pad that follows the chords, and the texture beds in samples/textures/
        d = synth.SAMPLE_DIR
        ports = os.path.dirname(os.path.dirname(d))
        dirs = [d] + [os.path.join(ports, app, "samples") for app in ("bricklab", "brickchord", "brickglide")]
        seen = set()
        try:                                             # what each of your samples is best used as
            with open(os.path.join(d, "samples.json")) as fh:
                manifest = json.load(fh)
        except Exception:
            manifest = {}
        beds = []
        for k, sd in enumerate(dirs):
            try:
                files = sorted(os.listdir(sd))
            except OSError:
                continue
            for f in files:
                if not f.lower().endswith(".wav") or f.startswith(".") or f in seen:
                    continue
                seen.add(f)
                path = f if k == 0 else os.path.join(sd, f)
                info = manifest.get(f, {})
                role = info.get("role", "pad")
                title = info.get("name") or sample_title(f)
                if role == "skip":
                    continue
                if role in ("bed", "beat"):
                    # a loop in its own key, under everything; it is moved into yours
                    beds.append(dict({"name": ("Beat " if role == "beat" else "Bed ") + title, "sample": path, "root": 60,
                                      "texture": True, "bed": role == "bed"},
                                     **{k2: v for k2, v in info.items() if k2 not in ("role", "name")}))
                    continue
                out.append(dict({"name": "Sample " + title, "sample": path, "root": sample_root(f), "pad": True},
                                **{k2: v for k2, v in info.items() if k2 not in ("role", "name")}))
        out += beds
        try:
            for f in sorted(os.listdir(os.path.join(d, "textures"))):
                if f.lower().endswith(".wav") and not f.startswith("."):
                    out.append({"name": "Texture " + os.path.splitext(f)[0], "sample": "textures/" + f,
                                "root": 60, "pad": True, "texture": True})
        except OSError:
            pass
    return out



def sample_title(f):
    """A readable sound name from a sample's file name."""
    s = os.path.splitext(f)[0].replace("_", " ").replace("-", " ")
    s = " ".join(w for w in s.split() if not w.isdigit())
    return (s[:22] + "\u2026") if len(s) > 23 else s


def sample_root(f):
    """The note a sample is in, read from its file name (Em, C#m, Fmin, Cmaj, A3...),
    so it plays in tune; C4 when the name doesn't say."""
    import re
    s = os.path.splitext(f)[0]
    m = re.findall(r"(?:^|[\s_\-(])([A-G])([#b]?)(?:m(?:in(?:or)?)?|maj(?:or)?|M)?(-?\d)?(?=$|[\s_\-)])", s)
    if not m:
        return 60
    note, acc, octv = m[-1]
    pc = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[note] + (1 if acc == "#" else -1 if acc == "b" else 0)
    octave = int(octv) if octv else 4
    return 12 * (octave + 1) + pc % 12

def struck(p):
    return p.get("macro") is not None and int(p.get("macro", 0)) in synth.MACRO_STRUCK


# The guided demo: one move at a time, each waiting until you have done it.
# (instruction, the chord tile to point at or None, check)
TUTORIAL = [
    ("Press  <  to play the first chord of your key", 0, lambda s: s.acur_deg == 0 and s.amb_sounding()),
    ("Press  A  for the sixth chord.  Watch every voice glide", 5, lambda s: s.acur_deg == 5),
    ("Press  v  for the fourth chord, then  X  for the fifth", 4, lambda s: s.acur_deg == 4 and 3 in s.atut_seen),
    ("Hold  L1  and press  X :  the fifth chord with a 7th", 4, lambda s: s.acur_deg == 4 and "seventh" in (s.acur_key or (0, ()))[1]),
    ("Hold  Y  and press  ^ :  Y flips major and minor", 1,
     lambda s: s.acur_deg == 1 and "flip" in (s.acur_key or (0, ()))[1]),
    ("HOLD  X  and push the LEFT STICK slowly: you play the glide", 4,
     lambda s: s.atut_flags.get("scrub")),
    ("Press  R2 :  bloom, every voice from one note", None, lambda s: s.atut_flags.get("bloom")),
    ("Press  START :  everything stops", None, lambda s: not s.amb_sounding() and not s.aprog.get("run")),
    ("Press  START  again:  the chords play by themselves", None, lambda s: s.aprog.get("run")),
    ("Click  L3  (press the left stick in)  to see the sound", None,
     lambda s: getattr(s, "aview", "guides") == "spectrum"),
    ("Press  START  to stop everything.  SELECT opens Settings", None,
     lambda s: not s.aprog.get("run") and not s.amb_sounding()),
]


class AmbientMixin:
    # ------------------------------------------------------------ state
    def amb_init(self):
        self.amb_sounds = amb_bank()
        names = [p["name"] for p in self.amb_sounds]

        def ix(n):
            return names.index(n) if n in names else 0
        st = self.cfg.get("amb") or {}
        k = self.key
        default_notes = [36, 43, 48, 55, 60, 64]           # root, fifth, octave, fifth, two octaves, tenth
        default_snd = [ix("Saw Bass"), ix("Deep Space"), ix("Tape Choir"), ix("Bowed Glass"), ix("Shimmer"),
                       ix("Sub Drone")]
        self.av = []
        for i in range(NV):
            d = {"on": False, "snd": default_snd[i] if i < 6 else ix("Kalimba" if i == 6 else "Bowed String"),
                 "note": (default_notes[i] + k) if i < 6 else 60 + k, "cents": 0,
                 "level": 0.7 if i == 0 else (0.6 if i < 6 else 0.5), "pan": [0.0, -0.4, 0.4, -0.2, 0.2, 0.0, -0.3, 0.3][i],
                 "glide": 4 if i < 6 else 2, "fade": 4 if i < 6 else 1, "vib": 4, "rate": 0.15 + 0.05 * i,
                 "trem": 0.0, "drift": 8 if i < 6 else 0, "base": None}
            if i < len(st.get("voices", [])):
                sv = st["voices"][i]
                d.update({kk: vv for kk, vv in sv.items() if kk in d})
                # sounds are kept by name: when your samples change, the list shifts, and an
                # index would land on a different sound (a loop where a pad should be)
                nm = sv.get("snd_name")
                names_ = [p["name"] for p in self.amb_sounds]
                if nm in names_:
                    d["snd"] = names_.index(nm)
                elif i != 7 and self.amb_sounds[d["snd"] % len(self.amb_sounds)].get("texture"):
                    d["snd"] = default_snd[i] if i < 6 else ix("Bowed String" if edition.PLAY else "Kalimba")
                d["on"] = False
                d["base"] = None
            self.av.append(d)
        self.amel = st.get("mel") or [{"steps": [0, 2, 4, 2, None], "time": 4, "run": False},
                                       {"steps": [7, None, 4, 5, None], "time": 6, "run": False}]
        for m in self.amel:
            m["run"] = False
            m["i"] = -1
            m["next"] = 0.0
        self.ascenes = st.get("scenes") or [None] * 6
        self.amorph = st.get("morph", 8)
        self.achord = dict({"type": 2, "path": 2, "time": 1.5, "stagger": 0, "order": 0, "root": True},
                           **(st.get("chord") or {}))
        if not self.achord.get("v2"):            # played like Brickchord now: chords glide in about a second
            self.achord.update(time=1.5, stagger=0, order=0, path=2, v2=True)
        self.achord.setdefault("move", 0)
        if not self.achord.get("v3"):            # chord buttons and the progression agree: plain triads by default
            self.achord.update(type=0, v3=True)
        if not self.achord.get("v4"):            # more paths: the old Steps (4) is now Scale steps
            if self.achord.get("path") == 4:
                self.achord["path"] = SCALE_STEPS
            self.achord.update(v4=True)
        self.achord.setdefault("timing", 0)
        self.achord.setdefault("sub", True)      # a sub voice an octave under the bass
        # a chord progression that steps by itself: every voice glides into each chord
        self.aprog = dict({"steps": [5, 0, 4, 3, None, None, None, None], "time": 4}, **(st.get("prog") or {}))
        self.aprog.update(run=False, i=-1, next=0.0)
        self.r2_used = False
        self.aexp = {}            # voices held for expression: i -> {"bend", "press", "moved", "was_on", "sent"}
        self.aexpr = dict({"range": 7, "snap": 0}, **(st.get("expr") or {}))
        self.asel = 0
        self.afreeze = False
        self.ahist = [[] for _ in range(NV)]
        self.aui = [{"cur": None, "lvl": 0.0} for _ in range(NV)]
        self.alast = time.perf_counter()
        self.ahist_t = 0.0
        self.aspread = self.amove = 0.0
        self.amb_pending = {}
        self.atut = 0 if not self.cfg.get("glide_tutorial_done") else None   # the guided demo, on first launch
        self.atut_seen, self.atut_flags, self.atut_t = set(), {}, time.perf_counter()
        self.acur_deg = self.acur_key = None
        self.acompass = self.ascrub = None
        # Brickglide Play: the melody over the progression, the strum, the texture bed
        self.amel_oct, self.amel_held, self.astrum_idx = 0, [], None
        # the strum and arp: instrument, level, arp pattern, range in octaves
        self.astrum = dict({"inst": 0, "level": 1.0, "style": 0, "range": 2, "rev": "Plate", "rev_amt": 0.6,
                            "dly": "Ping-Pong", "dly_amt": 0.35, "dly_time": 2}, **(st.get("strum") or {}))
        self.atexture = dict({"name": "", "level": 0.45}, **(st.get("texture") or {})) if edition.PLAY else None
        if edition.PLAY:
            lv = self.av[6]
            names = [p["name"] for p in self.amb_sounds]
            if not st.get("play_v1"):
                lv.update(snd=names.index("Bowed String") if "Bowed String" in names else lv["snd"], level=0.7,
                          fade=0.12, vib=9, rate=5.0, drift=0, glide=0.12, pan=0.1)
            self.aplay_v1 = True
        self.acur_name = ""
        self.eng.post("amb_global", 0.0, 1.0)

    def amb_sounding(self):
        return any(self.av[i]["on"] for i in range(6))

    def amb_tutorial_start(self):
        self.atut, self.atut_seen, self.atut_flags = 0, set(), {}
        self.atut_t = time.perf_counter()
        self.aview = "guides"
        self.flash("GUIDED DEMO   ONE MOVE AT A TIME")

    def amb_tutorial_tick(self, now):
        if self.atut is None:
            return
        if getattr(self, "acur_deg", None) is not None:
            self.atut_seen.add(self.acur_deg)
        if now - self.atut_t < 1.2:                          # a beat between steps
            return
        if TUTORIAL[self.atut][2](self):
            self.atut += 1
            self.atut_t = now
            if self.atut >= len(TUTORIAL):
                self.atut = None
                self.cfg["glide_tutorial_done"] = True
                self.save_cfg()
                self.flash("DEMO DONE   SETTINGS > SCENES > GUIDED DEMO RUNS IT AGAIN")

    def draw_amb_tutorial(self, c, now):
        if self.atut is None:
            return
        mm = M()
        W = mm.BASE_W
        text, tile, _ = TUTORIAL[self.atut]
        k = self.since(self.atut_t, 0.35)
        r = pygame.Rect(30, 52 + int((1 - k) * 10), W - 60, 62)
        pygame.draw.rect(c, self.mix(mm.BG, mm.PANEL, 0.95), r, border_radius=12)
        pygame.draw.rect(c, mm.ACCENT, r, 2, border_radius=12)
        self.text(c, "STEP %d OF %d" % (self.atut + 1, len(TUTORIAL)), self.f_small, mm.ACCENT, (r.x + 16, r.y + 8))
        self.text(c, "SELECT skips", self.f_small, mm.DIM, (r.right - 16, r.y + 8), right=True)
        f = self.f_med if self.f_med.size(text)[0] <= r.w - 28 else self.f_small
        self.text(c, text, f, mm.INK, (r.centerx, r.y + 40), center=True)
        if tile is not None:                                 # point at the button to press
            tw, gap = 82, 6
            x0 = (W - (7 * tw + 6 * gap)) // 2
            b = 0.5 + 0.5 * math.sin(now * 6)
            tr = pygame.Rect(x0 + tile * (tw + gap), mm.L["tiles_y"], tw, mm.L["tile_h"]).inflate(6, 6)
            pygame.draw.rect(c, self.mix(mm.PANEL, mm.ACCENT2, 0.4 + 0.6 * b), tr, 3, border_radius=12)

    # ------------------------------------------------------------ effects (Settings > FX)
    FX_ROWS = [("Space", None), ("Reverb", None), ("Echo", None), ("Echo type", None), ("Echo time", None),
               ("Cloud", "Cloud"), ("Cloud texture", "Cloud"), ("Chorus", "Chorus"), ("Wide", "Wide"),
               ("Tape wobble", "Vibrato"), ("Filter drift", "Filter LFO"), ("Drive", "Drive"), ("Lo-fi", "Lo-fi")]

    def amb_fx_defaults(self):
        """Brickglide starts wet and wide (once; your changes are kept after that)."""
        if self.cfg.get("amb_fx_v1"):
            return
        mm = M()
        self.cfg["amb_fx_v1"] = True
        self.base_rev, self.base_dly = 0.5, 0.3
        self.rev_type = "Big Hall" if "Big Hall" in synth.REVERBS else self.rev_type
        self.dly_type = "Tape" if "Tape" in mm.DELAY_TYPES else self.dly_type
        self.dly_time = next((i for i, (n, _) in enumerate(mm.DELAY_TIMES) if n == "1/4 dotted"), self.dly_time)
        for name, on, amt in (("Chorus", True, 0.35), ("Wide", True, 0.6)):
            cur = self.rack.get(name) or [False, 0.5, 2]
            self.rack[name] = [on, amt, cur[2]]
        self.rev, self.dly = self.base_rev, self.base_dly
        self.push_types()
        self.push_fx()
        self.push_rack()

    def amb_fx_items(self):
        mm = M()
        out = []
        if edition.PLAY:
            out += [("Texture", (self.atexture.get("name") or "Off").replace("Texture ", "")),
                    ("Texture level", "%d%%" % round(self.atexture.get("level", 0.45) * 100))]
        for label, key in self.FX_ROWS:
            if label == "Space":
                v = "%d%%" % round(self.base_rev * 100)
            elif label == "Reverb":
                v = self.rev_type
            elif label == "Echo":
                v = "%d%%" % round(self.base_dly * 100)
            elif label == "Echo type":
                v = self.dly_type
            elif label == "Echo time":
                v = mm.DELAY_TIMES[self.dly_time][0]
            elif label == "Cloud texture":
                r = self.rack.get("Cloud") or [False, 0.5, 3]
                v = engine.Engine.CLOUD_TEX[int(r[2]) % len(engine.Engine.CLOUD_TEX)][0]
            else:
                r = self.rack.get(key) or [False, 0.0, 2]
                v = ("%d%%" % round(r[1] * 100)) if r[0] else "Off"
            out.append((label, v))
        return out

    def amb_fx_change(self, name, d):
        mm = M()
        if name == "Texture":
            opts = [""] + self.amb_texture_names()
            cur = self.atexture.get("name") or ""
            self.atexture["name"] = opts[(opts.index(cur) + d) % len(opts) if cur in opts else 0]
            self.amb_set_texture()
            return
        if name == "Texture level":
            self.atexture["level"] = round(max(0.0, min(1.0, self.atexture.get("level", 0.45) + 0.05 * d)), 2)
            self.av[7]["level"] = self.atexture["level"]
            if self.av[7]["on"]:
                self.amb_push(7)
            return
        key = dict(self.FX_ROWS).get(name)
        if name == "Space":
            self.base_rev = round(max(0.0, min(1.0, self.base_rev + 0.05 * d)), 2)
        elif name == "Reverb":
            self.rev_type = synth.REVERBS[(synth.REVERBS.index(self.rev_type) + d) % len(synth.REVERBS)]
            self.push_types()
        elif name == "Echo":
            self.base_dly = round(max(0.0, min(1.0, self.base_dly + 0.05 * d)), 2)
        elif name == "Echo type":
            self.dly_type = mm.DELAY_TYPES[(mm.DELAY_TYPES.index(self.dly_type) + d) % len(mm.DELAY_TYPES)]
            self.push_types()
        elif name == "Echo time":
            self.dly_time = (self.dly_time + d) % len(mm.DELAY_TIMES)
            self.push_types()
        elif name == "Cloud texture":
            r = list(self.rack.get("Cloud") or [False, 0.5, 3])
            r[2] = (int(r[2]) + d) % len(engine.Engine.CLOUD_TEX)
            self.rack["Cloud"] = r
            self.push_rack()
        elif key:
            r = list(self.rack.get(key) or [False, 0.0, 2])
            amt = 0.0 if not r[0] else float(r[1])
            amt = round(max(0.0, min(1.0, amt + 0.05 * d)), 2)
            r[0], r[1] = amt > 0, max(amt, 0.05) if amt > 0 else r[1]
            self.rack[key] = r
            self.push_rack()
        self.rev, self.dly = self.base_rev, self.base_dly
        self.push_fx()

    def amb_state(self):
        keys = ("snd", "note", "cents", "level", "pan", "glide", "fade", "vib", "rate", "trem", "drift")
        return {"voices": [dict({k: v[k] for k in keys}, snd_name=self.amb_sounds[v["snd"] % len(self.amb_sounds)]["name"])
                           for v in self.av],
                "mel": [{"steps": m["steps"], "time": m["time"]} for m in self.amel],
                "scenes": self.ascenes, "morph": self.amorph, "chord": self.achord, "expr": self.aexpr,
                "prog": {"steps": self.aprog["steps"], "time": self.aprog["time"]},
                "texture": getattr(self, "atexture", None), "play_v1": getattr(self, "aplay_v1", False),
                "strum": getattr(self, "astrum", None)}

    # ------------------------------------------------------------ talking to the engine
    def amb_next_sound(self, cur, d):
        """The next sound a voice can take: beds, beats and textures are for the
        texture layer (Settings > FX), not for a voice."""
        n = len(self.amb_sounds)
        s = cur
        for _ in range(n):
            s = (s + d) % n
            if not self.amb_sounds[s].get("texture"):
                return s
        return cur

    def amb_patch(self, i):
        return self.amb_sounds[self.av[i]["snd"] % len(self.amb_sounds)]

    def amb_render(self, i):
        """Ask for voice i's sound at its base note (rendered once, pitched on the fly)."""
        v = self.av[i]
        v["base"] = int(v["note"])
        key = (v["base"], json.dumps(self.amb_patch(i), sort_keys=True))
        if hasattr(self.eng, "request"):
            self.eng.request("hi", [key])
        if hasattr(self.eng, "resolve"):
            snd = self.eng.resolve({0: key}).get(0)
            self.eng.post("amb_snd", i, snd, True)

    def amb_tgt(self, i):
        v = self.av[i]
        if v["base"] is None:
            return 0.0
        return (v["note"] - v["base"]) * 100.0 + v["cents"]

    def amb_push(self, i, jump=False, glide=None, shape=0, delay=0.0, via=None):
        """Send voice i to the engine. A new pitch is reached along a shaped glide:
        shape (Smooth, Linear, Ease, Swell), after delay seconds, through via (the
        notes to pass on the way, as absolute cents)."""
        v = self.av[i]
        if v["base"] is None or abs(v["note"] - v["base"]) > 24:
            self.amb_render(i)
            jump = True
        g = float(v["glide"] if glide is None else glide)
        d = {"tgt": self.amb_tgt(i), "on": v["on"], "level": v["level"], "pan": v["pan"],
             "glide": g, "fade": float(v["fade"]),
             "vib": float(v["vib"]), "rate": float(v["rate"]), "trem": float(v["trem"]), "drift": float(v["drift"]),
             "shape": int(shape), "delay": float(delay)}
        base = v["base"] * 100.0
        if via:
            d["path"] = [c - base for c in via]
        if jump:
            d["jump"] = True
        self.eng.post("amb", i, d)
        u = self.aui[i]
        tgt = v["note"] * 100.0 + v["cents"]
        if jump or u["cur"] is None:
            u["cur"] = tgt
            u["path"] = None
        elif abs(tgt - (u["path"][-1] if u.get("path") else u["cur"])) > 0.5 or via:
            u["path"] = [u["cur"]] + list(via or []) + [tgt]
            u["t0"], u["delay"], u["dur"], u["shape"] = time.perf_counter(), float(delay), g, int(shape)

    def amb_toggle(self, i):
        v = self.av[i]
        v["on"] = not v["on"]
        if v["on"] and v["base"] is None:
            self.amb_render(i)
        self.amb_push(i, jump=self.aui[i]["lvl"] < 0.02)
        if i >= 6:
            m = self.amel[i - 6]
            m["run"] = v["on"]
            m["i"], m["next"] = -1, 0.0
        self.flash("%s %s   %s" % ("VOICE %d" % (i + 1) if i < 6 else "MELODY %s" % "AB"[i - 6],
                                    "ON" if v["on"] else "OFF", self.amb_patch(i)["name"]))

    def amb_degree_midi(self, deg, octave=4):
        sc = M().SCALES[self.scale]
        o, d = divmod(int(deg), 7)
        return 12 * (octave + 1 + o) + self.key + sc[d]

    # ------------------------------------------------------------ input
    def amb_handle(self, name, down):
        """Brickchord's controls: the seven chord buttons play chords (L1 7th, R1 sus4,
        L1+R1 9th, Y flips major and minor), the voices gliding from chord to chord."""
        mm = M()
        if name == "R2":
            if down:
                self.r2_used = False
            elif not self.r2_used:
                self.amb_bloom()                        # R2: bloom from one note
            return True
        if self.amb_melody_mode():
            if name in mm.CHORD_BUTTONS and not ({"SELECT", "L2"} & set(self.inp.held)):
                k = mm.CHORD_BUTTONS.index(name)
                if down and "R2" in self.inp.held:
                    self.r2_used = True
                    self.amb_play(k)                     # R2 + button: change the chord by hand
                elif down:
                    self.amb_mel_on(k)
                else:
                    self.amb_mel_off(k)
                return True
            if name in ("L1", "R1"):
                if down:
                    self.amel_oct = max(-2, min(2, self.amel_oct + (1 if name == "R1" else -1)))
                    self.flash("MELODY OCTAVE %+d" % self.amel_oct)
                return True
        if not down:
            sc = getattr(self, "ascrub", None)
            if sc is not None and name == sc["btn"]:
                self.ascrub = None
                if sc["active"]:
                    self.amb_scrub_finish(sc)
                else:                                    # a tap: the chord plays as always
                    self.amb_play(sc["deg"], sc["mods"], False, toggle=True)
                return True
            return name in mm.CHORD_BUTTONS + ["START", "L3", "Y"]
        if name in mm.CHORD_BUTTONS:
            if "SELECT" in self.inp.held:
                s = mm.CHORD_BUTTONS.index(name)
                if s < 6:
                    self.sel_combo = True
                    self.amb_save_scene(s)
                return True
            if "L2" in self.inp.held:
                s = mm.CHORD_BUTTONS.index(name)
                self.l2_moved = True
                if s < 6:
                    self.amb_recall(s)
                return True
            if "R2" in self.inp.held:
                self.r2_used = True
                self.amb_press_chord(name, with_move=True)   # R2 + chord: travel there with the chosen Move
                return True
            if self.amb_scrub_begin(name):
                return True                              # held: the left stick steers the glide (Scrub)
            self.amb_press_chord(name)
            return True
        if name == "START":
            if self.aprog.get("run") or any(self.av[i]["on"] for i in range(6)):
                self.amb_stop()                          # START stops everything, progression and voices
            else:
                self.amb_prog_toggle()                   # from silence: the progression plays by itself
            return True
        if name == "L3":
            self.aview = "spectrum" if getattr(self, "aview", "guides") == "guides" else "guides"
            self.flash("VIEW: " + ("SPECTROGRAM" if self.aview == "spectrum" else "GLIDE GUIDES"))
            return True
        if name == "Y":
            return True                                 # Y is the flip modifier, held with a chord
        return False

    def amb_stick(self, x, y):
        if (edition.PLAY and "L2" not in self.inp.held and "R2" not in self.inp.held
                and getattr(self, "ascrub", None) is None):
            # Brickglide Play: the left stick strums and arpeggiates whatever chord is
            # sounding, from the progression, the chord buttons or the Orchid
            self.amb_strum(x, y)
            return
        if "L2" in self.inp.held:
            self.l2_moved = getattr(self, "l2_moved", False) or math.hypot(x, y) > 0.3
            self.drone_cloud(x, y)
            return
        if self.aexp:
            self.amb_express(x, y)
            return
        if "R2" in self.inp.held:
            if math.hypot(x, y) > 0.4:
                self.r2_used = True                      # R2 + stick picks a Move; no bloom on release
            self.amb_compass(x, y)
            return
        if getattr(self, "acompass", None) is not None:
            self.acompass = None
        if getattr(self, "ascrub", None) is not None:
            self.amb_scrub(x, y)                         # holding a chord: the left stick plays the glide
        return
        dz = 0.15
        sx = 0.0 if abs(x) < dz else x
        sy = 0.0 if abs(y) < dz else y
        spread = round(sx * 40) / 1.0                       # up to 40 cents fanned across the voices
        move = round((1.0 + sy * 2.0) * 10) / 10.0          # 0x .. 3x movement
        if (spread, move) != (self.aspread, self.amove):
            self.aspread, self.amove = spread, move
            self.eng.post("amb_global", spread, max(0.0, move))

    # ------------------------------------------------------------ per-voice expression
    def amb_express(self, x, y):
        """While drone buttons are held: X bends each held voice (up to the bend
        range at full stick), Y is pressure (up swells it and deepens its vibrato,
        down softens it). Like MPE, only the held voices move."""
        dz = 0.08
        bx = 0.0 if abs(x) < dz else (x - math.copysign(dz, x)) / (1 - dz)
        py = 0.0 if abs(y) < dz else (y - math.copysign(dz, y)) / (1 - dz)
        bend = bx * self.aexpr["range"] * 100.0
        for i, e in self.aexp.items():
            e["bend"], e["press"] = bend, py
            if abs(bx) > 0.12 or abs(py) > 0.12:
                e["moved"] = True
            v = self.av[i]
            if v["base"] is None:
                continue
            tgt = self.amb_tgt(i) + bend
            lvl = max(0.0, min(1.0, v["level"] * (1.0 + 0.6 * py)))
            vib = v["vib"] * (1.0 + 3.0 * max(0.0, py))
            sent = (round(tgt / 3), round(lvl * 50), round(vib))
            if sent == e["sent"]:
                continue
            e["sent"] = sent
            self.eng.post("amb", i, {"tgt": tgt, "level": lvl, "on": True, "glide": 0.08, "shape": 1, "vib": vib})
        if self.aexp and abs(bend) > 1:
            self.flash("BEND %+d CENTS%s" % (round(bend), "   PRESSURE %+d%%" % round(py * 100) if abs(py) > 0.12 else ""))

    def amb_commit_bend(self, i, e):
        """Let go of a bent voice: it settles on the nearest note of the scale (or
        semitone, or exactly where it is), and its level and vibrato come back."""
        v = self.av[i]
        total = v["note"] * 100.0 + v["cents"] + e["bend"]
        snap = self.aexpr["snap"]
        if snap == 0:
            sc = M().SCALES[self.scale]
            cands = [n for n in range(int(total // 100) - 3, int(total // 100) + 4) if (n - self.key) % 12 in sc]
            v["note"], v["cents"] = min(cands, key=lambda n: abs(n * 100 - total)), 0
        elif snap == 1:
            v["note"], v["cents"] = int(round(total / 100.0)), 0
        else:
            n = int(round(total / 100.0))
            v["note"], v["cents"] = n, int(round(total - n * 100))
        self.aui[i]["cur"] = total
        self.amb_push(i, glide=0.6, shape=2)

    # ------------------------------------------------------------ scenes and evolve
    def amb_save_scene(self, s):
        keys = ("on", "snd", "note", "cents", "level", "pan", "glide", "fade", "vib", "rate", "trem", "drift")
        self.ascenes[s] = [{k: v[k] for k in keys} for v in self.av[:6]]
        self.save_cfg()
        self.flash("SCENE %d SAVED   L2 + %s RECALLS IT" % (s + 1, M().BUTTON_GLYPH[M().CHORD_BUTTONS[s]]))

    def amb_recall(self, s):
        sc = self.ascenes[s] if s < len(self.ascenes) else None
        if not sc:
            self.flash("SCENE %d IS EMPTY   SELECT + %s SAVES ONE" % (s + 1, M().BUTTON_GLYPH[M().CHORD_BUTTONS[s]]))
            return
        for i, d in enumerate(sc[:6]):
            v = self.av[i]
            new_snd = d.get("snd", v["snd"]) != v["snd"]
            v.update({k: d[k] for k in d if k in v})
            if new_snd or v["base"] is None:
                v["base"] = None
                if v["on"]:
                    self.amb_render(i)
            self.amb_push(i, glide=self.amorph)
        self.flash("SCENE %d   MORPHING OVER %ds" % (s + 1, self.amorph))

    def amb_route(self, order, items):
        """Delays for voices moving together, by the chosen order. items: (i, pitch)."""
        st = float(self.achord["stagger"])
        rank = sorted(items, key=lambda t: t[1])
        n = len(rank)
        if order == 0 or st <= 0 or n < 2:
            return {i: 0.0 for i, _ in items}
        if order == 1:
            seq = [i for i, _ in rank]
        elif order == 2:
            seq = [i for i, _ in reversed(rank)]
        elif order == 3:
            seq = []
            lo, hi = 0, n - 1
            while lo <= hi:
                seq.append(rank[lo][0])
                if hi != lo:
                    seq.append(rank[hi][0])
                lo, hi = lo + 1, hi - 1
        else:
            import random
            seq = [i for i, _ in rank]
            random.shuffle(seq)
        return {i: k * st for k, i in enumerate(seq)}

    def amb_steps_via(self, frm, to):
        """The notes of the scale between two pitches (in cents), for the Steps path."""
        sc = M().SCALES[self.scale]
        lo, hi = sorted((frm / 100.0, to / 100.0))
        notes = [n * 100.0 for n in range(int(math.ceil(lo)) + 0, int(hi) + 1)
                 if (n - self.key) % 12 in sc and lo + 0.3 < n < hi - 0.3]
        if frm > to:
            notes.reverse()
        return notes[:10]

    def amb_glide_all(self, moves, label, move=None, glide_x=1.0):
        """moves: {voice: new midi}. Every voice glides there along the chord path.
        With a move (see MOVES), the voices travel a longer way: through one note
        (Bloom), one after another (Cascade), round an octave (Spiral), dipping
        (Swoop), via random scale notes (Scatter), meeting in the middle (Converge),
        or from an octave above (Fall)."""
        import random
        ch = self.achord
        path = ch["path"] % len(PATHS)
        shape = 2 if path == SCALE_STEPS else path
        secs = float(ch["time"]) * float(glide_x)
        items = [(i, self.aui[i]["cur"] or self.av[i]["note"] * 100.0) for i in moves]
        delays = self.amb_route(ch["order"], items)
        vias = {}
        if move is not None:
            name = MOVES[move % len(MOVES)]
            rank = sorted(moves, key=lambda i: moves[i])
            n = max(1, len(rank))
            secs = max(secs, 2.5) * (2.0 if name in ("Bloom", "Spiral", "Swoop", "Rise", "Scatter") else 1.0)
            if name == "Bloom":
                low = min(moves.values()) * 100.0
                vias = {i: [low] for i in moves}
            elif name == "Cascade up":
                delays = {i: k * secs * 0.6 / n for k, i in enumerate(rank)}
            elif name == "Cascade down":
                delays = {i: k * secs * 0.6 / n for k, i in enumerate(reversed(rank))}
            elif name == "Spiral":
                vias = {i: [moves[i] * 100.0 + (1200.0 if k % 2 else -1200.0)] for k, i in enumerate(rank)}
            elif name == "Swoop":
                vias = {i: [moves[i] * 100.0 - 1200.0] for i in moves}
            elif name == "Scatter":
                sc = M().SCALES[self.scale]
                for i in moves:
                    c = int(moves[i])
                    opts = [m for m in range(c - 7, c + 8) if (m - self.key) % 12 in sc and m != c]
                    vias[i] = [random.choice(opts) * 100.0] if opts else []
            elif name == "Converge":
                mid = (min(moves.values()) + max(moves.values())) * 50.0
                vias = {i: [mid] for i in moves}
            elif name == "Fall":
                vias = {i: [moves[i] * 100.0 + 1200.0] for i in moves}
            if path in (SCALE_STEPS, 8):
                shape = 2                               # through a Move's turning points, an ease reads best
        timing = TIMINGS[ch.get("timing", 0) % len(TIMINGS)]
        rank = sorted(moves, key=lambda i: moves[i])
        for i, note in moves.items():
            v = self.av[i]
            frm = self.aui[i]["cur"] or v["note"] * 100.0
            v["note"], v["cents"] = int(note), 0
            via = vias.get(i) or (self.amb_steps_via(frm, note * 100.0) if path == SCALE_STEPS else None)
            g = secs
            k = rank.index(i) / max(1, len(rank) - 1)           # 0 = bass .. 1 = top
            if timing == "By distance":                          # a big leap takes longer than a step
                g = secs * max(0.35, min(2.5, abs(note * 100.0 - frm) / 500.0))
            elif timing == "Bass lags":
                g = secs * (1.8 - 0.9 * k)
            elif timing == "Bass leads":
                g = secs * (0.6 + 0.9 * k)
            elif timing == "Loose":
                import random
                g = secs * random.uniform(0.6, 1.6)
            self.amb_push(i, glide=g, shape=shape, delay=delays.get(i, 0.0), via=via)
        self.amb_sub_follow(moves, secs)
        if label:
            self.flash(label)

    def amb_sub_follow(self, moves, secs):
        """The sub voice (voice 6) sits an octave under the bass when Sub bass is on."""
        v = self.av[5]
        if not self.achord.get("sub") or not moves:
            if v["on"]:
                v["on"] = False
                self.amb_push(5)
            return
        bass = min(moves.values())
        names = [p["name"] for p in self.amb_sounds]
        if names[v["snd"] % len(names)] != "Sub Drone" and not v.get("sub_set"):
            v["snd"], v["sub_set"] = names.index("Sub Drone") if "Sub Drone" in names else v["snd"], True
            v["base"] = None
            v["level"], v["pan"], v["vib"], v["drift"], v["fade"] = 0.6, 0.0, 0, 0, 1.0
        was_on = v["on"]
        v["note"], v["cents"], v["on"] = int(bass) - 12, 0, True
        if v["base"] is None:
            self.amb_render(5)
        self.amb_push(5, jump=not was_on, glide=secs, shape=2)

    def amb_chord(self, deg, with_move=False):
        """The progression's chord: exactly what pressing that chord button plays."""
        self.amb_play(deg % 7, None, with_move)

    def amb_voicelead(self, on, pcs, root_pc):
        """Each sounding voice to a tone of the chord (pcs): the lowest to the root, as
        a bass would, the rest, low to high, to the nearest chord tone above the one
        below, preferring tones not used yet so the chord is complete."""
        cand = [n for n in range(24, 97) if n % 12 in pcs]
        cur = sorted(((self.aui[i]["cur"] or self.av[i]["note"] * 100.0) / 100.0, i) for i in on)
        # the lowest voice takes the root (as a bass would), then each voice, low to high,
        # takes the nearest chord tone above the one below it, preferring tones not used
        # yet so the chord is complete
        best, used, prev = [], set(), 0
        rest = cur
        if self.achord.get("root") and len(cur) > 1:
            c0 = cur[0][0]
            b = min((n for n in range(36, 48) if n % 12 == root_pc), key=lambda n: abs(n - c0))   # bass stays C2..B2
            best, used, prev, rest = [b], {root_pc}, b, cur[1:]
        for c, _ in rest:
            opts = [n for n in cand if n > prev] or [cand[-1]]
            n = min(opts, key=lambda n: abs(n - c) + (2.5 if n % 12 in used and len(used) < len(pcs) else 0))
            best.append(n)
            used.add(n % 12)
            prev = n
        return {i: n for n, (_, i) in zip(best, cur)}

    # ------------------------------------------------------------ playing chords, Brickchord-style
    NCH = 5                     # how many drone voices a chord button plays

    # the left stick as a Move compass: hold a direction while you press a chord
    COMPASS_MOVES = [7, 3, 1, 0, 4, 6, 2, 5]   # up Fall, up-right Spiral, right Cascade up, down-right Bloom,
                                               # down Swoop, down-left Converge, left Cascade down, up-left Scatter

    def amb_chord_tones(self, deg, held):
        """The chord on a degree, the same way for the buttons and the progression: the
        held modifiers (L1 / R1 / Y) if any, otherwise the Chord setting."""
        mm = M()
        name = CHORDS[self.achord["type"] % len(CHORDS)][0]
        m = dict(held or {})
        if not any(m.values()):
            m = {"Seventh": {"seventh": True}, "Ninth": {"ninth": True}, "Sus4": {"sus": True}}.get(name, {})
        pc, iv, cname = mm.build_chord(self.key, self.scale, deg, m)
        root_pc = pc % 12                          # build_chord's root is already in the key
        if any((held or {}).values()) or name in ("Triad", "Seventh", "Ninth", "Sus4"):
            pcs = {(root_pc + i) % 12 for i in iv}
        else:                                       # the colour chords: Eleventh, Quartal, Lydian and the rest
            _, kind, steps = CHORDS[self.achord["type"] % len(CHORDS)]
            sc = mm.SCALES[self.scale]
            pcs = ({(self.key + sc[(deg + s) % 7]) % 12 for s in steps} if kind == "deg"
                   else {(root_pc + s) % 12 for s in steps})
            cname = cname + " " + name
        key = (deg, tuple(sorted(k for k, v in m.items() if v)), name)
        return root_pc, pcs, mm.roman_for(deg, iv) + "  " + cname, key

    def amb_play(self, deg, held=None, with_move=False, move=None, glide_x=1.0, toggle=False):
        """Play the chord on a degree: from silence the voices lay it out and fade in;
        otherwise every voice glides there (straight, or with a Move)."""
        root_pc, pcs, label, key = self.amb_chord_tones(deg, held)
        sounding = [i for i in range(self.NCH) if self.av[i]["on"]]
        if toggle and sounding and getattr(self, "acur_key", None) == key and not with_move:
            self.amb_stop("RELEASED")                  # the same chord again: let it go
            return
        if move is None and with_move:
            move = self.achord["move"]
        fresh = [i for i in range(self.NCH) if not self.av[i]["on"]]
        if len(fresh) == self.NCH:
            notes = self.amb_voicelead(list(range(self.NCH)), pcs, root_pc)
            for i, n in notes.items():
                v = self.av[i]
                v["note"], v["cents"], v["on"] = int(n), 0, True
                if v["base"] is None or abs(v["note"] - v["base"]) > 24:
                    self.amb_render(i)
                self.amb_push(i, jump=True)
            self.amb_sub_follow(notes, 0.5)
            if move is not None:
                self.amb_bloom(secs=max(3.0, self.achord["time"] * 2 * glide_x))
        else:
            for i in fresh:
                self.av[i]["on"] = True
                self.amb_push(i, jump=True)
            moves = self.amb_voicelead(list(range(self.NCH)), pcs, root_pc)
            self.amb_glide_all(moves, MOVES[move % len(MOVES)].upper() if move is not None else "",
                               move=move, glide_x=glide_x)
        if getattr(self, "acur_deg", None) is not None and self.acur_deg != deg:
            self.aprev_deg = self.acur_deg
        self.acur_key, self.acur_deg, self.acur_name = key, deg, label
        self.amidi_pcs = None
        self.hit_t, self.hit_big = time.perf_counter(), True

    def amb_press_chord(self, btn, with_move=False):
        """A chord button: Brickchord's chord (L1 7th, R1 sus4, L1+R1 9th, Y flip). The
        left stick, held in a direction, picks a Move for this change; R2 uses the
        Move from Settings."""
        mm = M()
        deg = mm.CHORD_BUTTONS.index(btn)
        sel = getattr(self, "acompass", None)
        if sel is not None:
            self.atut_flags["compass"] = True
            self.amb_play(deg, self.mods(), True, move=sel[0], glide_x=sel[1])
        else:
            self.amb_play(deg, self.mods(), with_move, toggle=True)

    def amb_preview_path(self):
        """While a chord is sounding, changing the path or timing replays the move to
        the same chord from the one before, so you hear the new curve at once."""
        if getattr(self, "acur_deg", None) is None or not self.amb_sounding():
            return
        prev = getattr(self, "aprev_deg", None)
        cur = self.acur_deg
        other = prev if prev is not None and prev != cur else (cur + 3) % 7
        self.amb_play(other)
        self._preview_back = (time.perf_counter() + max(0.6, float(self.achord["time"]) * 1.2), cur)

    # ------------------------------------------------------------ Scrub: play the glide yourself
    SCRUB_RELEASE = ["Complete", "Return", "Stay"]

    def amb_scrub_begin(self, btn):
        """Pressing a chord while voices sound arms a scrub: nothing moves until the
        left stick does. A tap (no stick) plays the chord on release, as before."""
        mm = M()
        if not self.amb_sounding() or self.aprog.get("run"):
            return False
        deg = mm.CHORD_BUTTONS.index(btn)
        held = self.mods()
        root_pc, pcs, label, key = self.amb_chord_tones(deg, held)
        if key == getattr(self, "acur_key", None):
            return False                                 # the same chord: a tap releases it
        frm = {i: (self.aui[i]["cur"] if self.aui[i]["cur"] is not None else self.av[i]["note"] * 100.0)
               for i in range(6)}
        to = self.amb_voicelead(list(range(self.NCH)), pcs, root_pc)
        tgt = {i: n * 100.0 for i, n in to.items()}
        if self.av[5]["on"] and self.achord.get("sub"):
            tgt[5] = (min(to.values()) - 12) * 100.0
        self.ascrub = {"btn": btn, "deg": deg, "mods": held, "key": key, "label": label, "from": frm,
                       "to": tgt, "notes": to, "p": 0.0, "active": False, "sent": None}
        return True

    def amb_scrub(self, x, y):
        """The stick's distance from centre is how far along the glide you are: push
        slowly to travel slowly, hold halfway for an in-between chord, ease back
        and the harmony slides back."""
        sc = self.ascrub
        r = math.hypot(x, y)
        raw = 0.0 if r < 0.22 else min(1.0, (r - 0.22) / 0.7)      # a wide centre, so a nudge does nothing
        raw = raw ** 1.6                                          # fine control near the start
        p = sc["p"] + (raw - sc["p"]) * 0.18                      # follows the stick smoothly, not twitchily
        if abs(p - raw) < 0.003:
            p = raw
        if p > 0.04:
            sc["active"] = True
        sc["p"] = p
        sent = round(p * 200)
        if sent == sc["sent"]:
            return
        sc["sent"] = sent
        for i, t in sc["to"].items():
            v = self.av[i]
            if v["base"] is None:
                continue
            f = sc["from"][i]
            c = f + (t - f) * p
            self.aui[i]["cur"] = c
            self.aui[i]["path"] = None
            self.eng.post("amb", i, {"tgt": c - v["base"] * 100.0, "glide": 0.06, "shape": 1, "on": True})
        if sc["active"]:
            self.flash("SCRUB  %d%%   TO %s" % (round(p * 100), sc["label"]))

    def amb_scrub_finish(self, sc):
        """Let go of the chord button: finish the move, go back, or stay in between
        (Settings > Chords > Scrub release)."""
        how = self.SCRUB_RELEASE[self.achord.get("scrub_release", 0) % 3]
        p = sc["p"]
        rest = max(0.15, float(self.achord["time"]) * (1.0 - p))
        for i, t in sc["to"].items():
            v = self.av[i]
            f = sc["from"][i]
            if how == "Complete":
                v["note"], v["cents"] = int(round(t / 100.0)), 0
                self.amb_push(i, glide=rest, shape=2)
            elif how == "Return":
                n = int(round(f / 100.0))
                v["note"], v["cents"] = n, int(round(f - n * 100))
                self.amb_push(i, glide=max(0.15, float(self.achord["time"]) * p), shape=2)
            else:                                        # Stay: the in-between chord is the new chord
                c = f + (t - f) * p
                n = int(round(c / 100.0))
                v["note"], v["cents"] = n, int(round(c - n * 100))
                self.amb_push(i, glide=0.1, shape=1)
        if how == "Complete":
            if getattr(self, "acur_deg", None) is not None and self.acur_deg != sc["deg"]:
                self.aprev_deg = self.acur_deg
            self.acur_key, self.acur_deg, self.acur_name = sc["key"], sc["deg"], sc["label"]
            self.flash(sc["label"])
        elif how == "Stay":
            self.acur_key = None
            self.acur_name = "between"
            self.flash("IN BETWEEN   %d%% OF THE WAY TO %s" % (round(p * 100), sc["label"]))
        else:
            self.flash("BACK")
        self.atut_flags["scrub"] = True

    # ------------------------------------------------------------ Brickglide Play
    def amb_melody_mode(self):
        return bool(edition.PLAY and self.aprog.get("run"))

    def amb_mel_note(self, k):
        """Button k (0..6) is the k-th note of the scale above the current chord's
        root: buttons 1, 3 and 5 (< > v) are always the chord's own tones."""
        mm = M()
        sc = mm.SCALES[self.scale]
        deg = self.acur_deg if getattr(self, "acur_deg", None) is not None else 0
        r = 60 + (self.key + sc[deg % 7]) % 12
        if r > 66:
            r -= 12
        iv = (sc[(deg + k) % 7] - sc[deg % 7]) % 12
        return r + iv + 12 * self.amel_oct

    def amb_mel_on(self, k):
        """A melody note on the lead voice; pressed while another is held, it glides
        there (legato), which is the whole point of Brickglide."""
        v = self.av[6]
        legato = v["on"] and len(self.amel_held) > 0
        self.amel_held = [h for h in self.amel_held if h != k] + [k]
        v["note"], v["cents"] = self.amb_mel_note(k), 0
        if not legato:
            v["on"] = True
            self.amb_push(6, jump=True, glide=0.0)
        else:
            self.amb_push(6, glide=float(v["glide"]), shape=2)
        self.amel_lit = time.perf_counter()

    def amb_mel_off(self, k):
        self.amel_held = [h for h in self.amel_held if h != k]
        v = self.av[6]
        if self.amel_held:                               # back to the note still held
            v["note"], v["cents"] = self.amb_mel_note(self.amel_held[-1]), 0
            self.amb_push(6, glide=float(v["glide"]), shape=2)
        elif v["on"]:
            v["on"] = False
            self.amb_push(6)

    ARP_STYLES = ["By stick", "Bounce", "Random", "Root and up"]

    def amb_strum_fx(self):
        """The strum and arp's own reverb and echo, on bus B, apart from the pads'."""
        mm = M()
        sa = self.astrum
        times = mm.DELAY_TIMES
        self.eng.post("busfx", 1, sa["rev"], sa["dly"], times[sa["dly_time"] % len(times)][1])
        self.eng.post("pluckfx", sa["rev_amt"], sa["dly_amt"])

    def amb_strum_tones(self):
        deg = self.acur_deg if getattr(self, "acur_deg", None) is not None else None
        if deg is None and getattr(self, "amidi_pcs", None):
            pcs = self.amidi_pcs                            # a chord from MIDI (the Orchid) has no degree
        else:
            _, pcs, _, _ = self.amb_chord_tones(deg or 0, None)
        lo, hi = {1: (60, 72), 2: (55, 79), 3: (48, 84), 4: (43, 91)}[int(self.astrum.get("range", 2))]
        return [n for n in range(lo, hi + 1) if n % 12 in pcs]

    def amb_strum(self, x, y):
        """Left stick, the way a harp or an Omnichord plate is played:
        LEFT / RIGHT strums: the stick's position across is the string you're on, so a
        sweep plays every chord tone it crosses, low on the left, high on the right.
        UP / DOWN arpeggiates: up climbs the chord tones over and over, down falls,
        faster the further you push. Whichever way the stick moves first decides which,
        until it comes back to the middle."""
        now = time.perf_counter()
        r = math.hypot(x, y)
        if r < 0.18:
            if getattr(self, "astick_center_t", None) is None:
                self.astick_center_t = now
            elif now - self.astick_center_t > 0.15:          # resting in the middle: let go
                self.astick_mode, self.astrum_idx, self.aarp = None, None, None
            return
        self.astick_center_t = None
        if getattr(self, "astick_mode", None) is None:
            self.astick_mode = "strum" if abs(x) >= abs(y) else "arp"
        tones = self.amb_strum_tones()
        if not tones:
            return
        if self.astick_mode == "strum":
            idx = int(round((max(-1.0, min(1.0, x)) + 1) / 2 * (len(tones) - 1)))
            prev = getattr(self, "astrum_idx", None)
            self.astrum_idx = idx
            if prev == idx:
                return
            run = [idx] if prev is None else (list(range(prev + 1, idx + 1)) if idx > prev
                                              else list(range(prev - 1, idx - 1, -1)))
            for j in run[-6:]:
                self.eng.post("pluck", int(tones[j]), (0.5 + 0.35 * min(1.0, abs(x))) * self.astrum["level"],
                              -0.6 + 1.2 * j / max(1, len(tones) - 1), self.astrum["inst"])
            n = getattr(self, "_strum_logged", 0)
            if n < 8:
                self._strum_logged = n + 1
                print("strum:", [int(tones[j]) for j in run[-6:]], flush=True)
        else:
            k = max(0.0, (abs(y) - 0.18) / 0.82)
            rate = 3.0 + 13.0 * k ** 1.3                      # notes a second: 3 near the middle, 16 at the rim
            d = 1 if y > 0 else -1
            if getattr(self, "aarp", None) is None:
                self.aarp = {"dir": d, "rate": rate, "i": 0 if d > 0 else len(tones) - 1, "next": now}
                print("arp: %s at %.1f notes/s over %s" % ("up" if d > 0 else "down", rate, tones), flush=True)
            else:
                by_stick = self.ARP_STYLES[self.astrum.get("style", 0) % len(self.ARP_STYLES)] == "By stick"
                if by_stick and self.aarp["dir"] != d:       # turn round from the note just played
                    self.aarp["i"] = (self.aarp["i"] - self.aarp["dir"] + d) % len(tones)
                    self.aarp["dir"] = d
                self.aarp["rate"] = rate

    def amb_arp_tick(self, now):
        ap = getattr(self, "aarp", None)
        if not ap or now < ap["next"]:
            return
        tones = self.amb_strum_tones()
        if not tones:
            return
        n = len(tones)
        i = ap["i"] % n
        self.eng.post("pluck", int(tones[i]), 0.6 * self.astrum["level"], -0.6 + 1.2 * i / max(1, n - 1),
                      self.astrum["inst"])
        style = self.ARP_STYLES[self.astrum.get("style", 0) % len(self.ARP_STYLES)]
        if style == "Bounce":                            # up then down, never repeating the ends
            nxt = i + ap["dir"]
            if nxt < 0 or nxt >= n:
                ap["dir"] = -ap["dir"]
                nxt = i + ap["dir"]
            ap["i"] = max(0, min(n - 1, nxt))
        elif style == "Random":
            import random
            ap["i"] = random.choice([k for k in range(n) if k != i] or [i])
        elif style == "Root and up":                     # back to the lowest note between each step up
            ap["step"] = ap.get("step", 0) + 1
            ap["i"] = 0 if ap["step"] % 2 else (ap.get("hi", 0) % (n - 1)) + 1
            if not ap["step"] % 2:
                ap["hi"] = ap.get("hi", 0) + 1
        else:
            ap["i"] = (i + ap["dir"]) % n
        ap["next"] = max(now, ap["next"]) + 1.0 / ap["rate"]

    def amb_texture_names(self):
        return [p["name"] for p in self.amb_sounds if p.get("texture")]   # beds and beats, then textures

    def amb_set_texture(self):
        """The texture bed lives on voice 8: a room sound at its own pitch, under
        everything, not following the chords."""
        if not edition.PLAY:
            return
        v = self.av[7]
        names = [p["name"] for p in self.amb_sounds]
        nm = self.atexture.get("name") or ""
        if nm not in names:
            if v["on"]:
                v["on"] = False
                self.amb_push(7)
            return
        p = self.amb_sounds[names.index(nm)]
        note = 60
        if p.get("bed"):
            # move the loop from its key to yours (a minor loop to your key's minor, a major
            # loop to its major), by the smallest step either way
            minor_key = self.scale in ("Minor", "Dorian", "Phrygian", "Harmonic Minor", "Melodic Minor")
            home = self.key % 12
            if bool(p.get("minor")) and not minor_key:
                home = (home + 9) % 12                   # the relative minor of a major key
            elif not p.get("minor") and minor_key:
                home = (home + 3) % 12                   # the relative major of a minor key
            sh = (home - int(p.get("tonic", 0))) % 12
            note = 60 + (sh - 12 if sh > 6 else sh)
        v.update(snd=names.index(nm), note=note, cents=0, level=float(self.atexture.get("level", 0.45)), pan=0.0,
                 vib=0.0, trem=0.0, drift=0.0, fade=2.5, on=True, base=None)
        self.amb_render(7)
        self.amb_push(7, jump=True)

    # ------------------------------------------------------------ MIDI in (Brickglide Play)
    def amb_midi_start(self):
        """Watch for USB MIDI devices (an Orchid, an OP-Z, a keyboard) and read them on
        a thread: notes arrive in a queue the UI drains every frame. Plug in or out
        at any time; what is found is written to the log."""
        import collections
        import glob
        import select
        import threading
        self._midi_q = collections.deque()
        self.amidi_held, self.amidi_applied, self.amidi_due = set(), frozenset(), 0.0

        def card_name(path):
            try:
                n = os.path.basename(path)[5:].split("D")[0]
                return open("/proc/asound/card%s/id" % n).read().strip()
            except Exception:
                return os.path.basename(path)

        def run():
            fds, status, logged = {}, {}, [0]
            while True:
                try:
                    for p in glob.glob("/dev/snd/midiC*D*"):
                        if p not in fds.values():
                            try:
                                fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
                                fds[fd] = p
                                status[fd] = 0
                                nm = card_name(p)
                                print("MIDI in: opened %s (%s)" % (p, nm), flush=True)
                                self._midi_q.append(("connect", nm))
                            except OSError as ex:
                                print("MIDI in: cannot open %s: %s" % (p, ex), flush=True)
                    if not fds:
                        time.sleep(1.0)
                        continue
                    r, _, _ = select.select(list(fds), [], [], 1.0)
                    for fd in r:
                        try:
                            data = os.read(fd, 256)
                        except OSError:
                            data = b""
                        if not data:
                            print("MIDI in: %s went away" % fds[fd], flush=True)
                            self._midi_q.append(("disconnect", card_name(fds[fd])))
                            os.close(fd)
                            del fds[fd]
                            continue
                        msg = []
                        for b in data:
                            if b >= 0xF8:
                                continue                  # clock and other real-time bytes
                            if b & 0x80:
                                status[fd] = b
                                msg = []
                                continue
                            msg.append(b)
                            st = status[fd] & 0xF0
                            if st in (0x80, 0x90) and len(msg) == 2:
                                note, vel = msg
                                on = st == 0x90 and vel > 0
                                self._midi_q.append(("on" if on else "off", note, vel))
                                if logged[0] < 40:
                                    logged[0] += 1
                                    print("MIDI in: note %s %d vel %d" % ("on" if on else "off", note, vel),
                                          flush=True)
                                msg = []
                            elif st in (0xA0, 0xB0, 0xE0) and len(msg) == 2:
                                msg = []
                            elif st in (0xC0, 0xD0) and len(msg) == 1:
                                msg = []
                except Exception as ex:
                    print("MIDI in: error %s" % ex, flush=True)
                    time.sleep(1.0)

        threading.Thread(target=run, daemon=True).start()

    def amb_midi_tick(self, now):
        q = getattr(self, "_midi_q", None)
        if q is None:
            return
        while q:
            ev = q.popleft()
            if ev[0] == "connect":
                self.flash("MIDI IN: %s   PLAY A CHORD" % ev[1].upper())
            elif ev[0] == "disconnect":
                self.flash("MIDI IN: %s UNPLUGGED" % ev[1].upper())
            elif ev[0] == "on":
                self.amidi_held.add(ev[1])
                self.amidi_due = now + 0.035            # the notes of a chord arrive one by one
            elif ev[0] == "off":
                self.amidi_held.discard(ev[1])
                self.amidi_due = now + 0.035
        if self.amidi_due and now >= self.amidi_due:
            self.amidi_due = 0.0
            held = frozenset(self.amidi_held)
            if len(held) >= 2 and held != self.amidi_applied:
                self.amidi_applied = held
                self.amb_follow(sorted(held))
            elif len(held) == 1 and not self.amidi_applied:
                pass
            elif not held:
                self.amidi_applied = frozenset()        # let go: the chord holds until the next one

    def amb_follow(self, notes):
        """A chord from MIDI (the Orchid): every voice glides to it, the bass to its
        lowest note's pitch class, with the sub underneath. Let go and it holds."""
        mm = M()
        pcs = {n % 12 for n in notes}
        root_pc = notes[0] % 12
        self.amidi_pcs = set(pcs)
        iv = sorted({(p - root_pc) % 12 for p in pcs})
        try:
            nm = mm.chord_name(root_pc, iv, False, False, self.key, self.scale)
        except Exception:
            nm = mm.note_name(root_pc, self.key, self.scale)
        fresh = [i for i in range(self.NCH) if not self.av[i]["on"]]
        if len(fresh) == self.NCH:
            to = self.amb_voicelead(list(range(self.NCH)), pcs, root_pc)
            for i, n in to.items():
                v = self.av[i]
                v["note"], v["cents"], v["on"] = int(n), 0, True
                if v["base"] is None or abs(v["note"] - v["base"]) > 24:
                    self.amb_render(i)
                self.amb_push(i, jump=True)
            self.amb_sub_follow(to, 0.5)
        else:
            for i in fresh:
                self.av[i]["on"] = True
                self.amb_push(i, jump=True)
            self.amb_glide_all(self.amb_voicelead(list(range(self.NCH)), pcs, root_pc), "")
        self.acur_key, self.acur_deg = None, None
        self.acur_name = nm
        self.flash("MIDI CHORD  %s" % nm)

    def amb_stop(self, why="STOPPED"):
        """Everything fades out: the voices, the sub, the progression."""
        for i in range(7):
            if self.av[i]["on"]:
                self.av[i]["on"] = False
                self.amb_push(i)
        self.amel_held = []
        self.aprog["run"] = False
        self.acur_key = self.acur_deg = None
        self.acur_name = ""
        self.flash(why + "   PRESS A CHORD")

    def amb_compass(self, x, y):
        """Left stick: hold a direction and the next chord you press travels there with
        that direction's Move; push further for a longer glide (up to 4x)."""
        r = math.hypot(x, y)
        if r < 0.4:
            if getattr(self, "acompass", None) is not None:
                self.acompass = None
            return
        sector = int(((math.degrees(math.atan2(x, y)) + 360 + 22.5) % 360) // 45)
        mv = self.COMPASS_MOVES[sector]
        gx = round((1.0 + 3.0 * min(1.0, (r - 0.4) / 0.55)) * 2) / 2.0
        if getattr(self, "acompass", None) != (mv, gx):
            self.acompass = (mv, gx)
            self.flash("MOVE: %s   %gx GLIDE   PRESS A CHORD" % (MOVES[mv].upper(), gx))

    def amb_bend_all(self, x, y):
        """Left stick with nothing held: bend the whole chord and swell it; it springs
        back when you let go."""
        dz = 0.1
        bx = 0.0 if abs(x) < dz else (x - math.copysign(dz, x)) / (1 - dz)
        py = 0.0 if abs(y) < dz else (y - math.copysign(dz, y)) / (1 - dz)
        state = (round(bx * 40), round(py * 20))
        if state == getattr(self, "abend_state", (0, 0)):
            return
        self.abend_state = state
        bend = bx * self.aexpr["range"] * 100.0
        self.abend = bend
        for i in range(6):
            v = self.av[i]
            if not v["on"] or v["base"] is None:
                continue
            self.eng.post("amb", i, {"tgt": self.amb_tgt(i) + bend, "glide": 0.12 if (bx or py) else 0.5, "shape": 1,
                                     "level": max(0.0, min(1.0, v["level"] * (1 + 0.6 * py))), "on": True,
                                     "vib": v["vib"] * (1 + 3 * max(0.0, py))})

    def amb_bloom(self, secs=None, swell=True):
        """Unison bloom: every sounding drone jumps to one note (the lowest voice's)
        and fans out to its own pitch along an S-curve, while the filter opens.
        The classic cinema swell."""
        on = [i for i in range(6) if self.av[i]["on"]]
        if len(on) < 2:
            self.flash("TURN ON TWO OR MORE VOICES FIRST")
            return
        secs = float(secs or max(3.0, self.achord["time"] * 3))
        low = min(self.av[i]["note"] for i in on if i != 5) * 100.0
        for i in on:
            if i == 5:
                continue
            v = self.av[i]
            if v["base"] is None:
                self.amb_render(i)
            # draw the voices together first, then fan out: no jump, one smooth gesture
            self.amb_push(i, glide=secs * 1.5, shape=2, via=[low])
        if swell:
            self.amb_swell(min(30.0, secs * 4))
        self.atut_flags["bloom"] = True
        self.flash("BLOOM   %d VOICES FANNING OUT OVER %gs" % (len(on), secs))

    def amb_swell(self, secs, start=0.7):
        """The filter starts closed and opens over secs (the right stick still overrides)."""
        self.aswell = (time.perf_counter(), float(secs), float(start))

    def amb_deep_bloom(self):
        """Deep Bloom: five brassy voices bloom out of one low note into a minor chord,
        the filter slowly opening, then move i, V, VI, IV, V on long S-curve glides."""
        names = [p["name"] for p in self.amb_sounds]

        def ix(n):
            return names.index(n) if n in names else 0
        if self.scale not in ("Minor", "Dorian", "Phrygian"):
            self.scale = "Minor"
        sc = M().SCALES[self.scale]
        k = self.key
        chord = [12 * 3 + k, 12 * 3 + k + 7, 12 * 4 + k + sc[2], 12 * 4 + k + 7, 12 * 5 + k]
        snds = ["Saw Bass", "Supersaw", "Juno Strings", "Supersaw", "Prophet Brass"]
        pans = [0.0, -0.5, 0.5, -0.25, 0.25]
        self.aprog["run"] = False
        for i in range(6):
            v = self.av[i]
            if i >= 5:
                if v["on"]:
                    self.amb_toggle(i)
                continue
            v.update(snd=ix(snds[i]), note=chord[i], cents=0, level=0.6 if i == 0 else 0.48, pan=pans[i], glide=1.2,
                     fade=2.0, vib=4, rate=0.25, trem=0.0, drift=4, base=None, on=True)
            self.amb_render(i)
            self.amb_push(i, jump=True)
        self.amb_sub_follow({i: chord[i] for i in range(5)}, 0.5)
        self.achord.update(type=0, path=2, time=1.2, stagger=0, order=0, root=True)
        self.aprog.update(steps=[0, 4, 5, 3, 4, None, None, None], time=5, run=False, i=0, next=0.0)
        self.amb_bloom(secs=3.5)
        self.aprog["run"] = True
        self.aprog["next"] = time.perf_counter() + 6.0          # let the bloom finish first
        self.flash("DEEP BLOOM   %s %s   START STOPS IT" % (M().NOTE_NAMES[k], self.scale))

    def amb_starter(self):
        """Glide Chords: five bright saw voices sliding through vi, I, V, IV in your
        key, a chord every four seconds, every voice gliding at once."""
        names = [p["name"] for p in self.amb_sounds]

        def ix(n):
            return names.index(n) if n in names else 0
        sc = M().SCALES[self.scale]
        k = self.key
        start = [12 * 3 + k + sc[5], 12 * 4 + k, 12 * 4 + k + sc[2], 12 * 5 + k, 12 * 5 + k + sc[2]]   # vi in five voices
        snds = ["Saw Bass", "Supersaw", "Juno Strings", "Supersaw", "Juno Strings"]
        pans = [0.0, -0.5, 0.5, -0.25, 0.25]
        for i in range(6):
            v = self.av[i]
            if v["on"] and i >= 5:
                self.amb_toggle(i)
            if i >= 5:
                continue
            v.update(snd=ix(snds[i]), note=start[i], cents=0, level=0.65 if i == 0 else 0.5, pan=pans[i], glide=0.4,
                     fade=0.8, vib=3, rate=0.3, trem=0.0, drift=3, base=None)
            if not v["on"]:
                v["on"] = True
            self.amb_render(i)
            self.amb_push(i, jump=True)
        self.amb_sub_follow({i: start[i] for i in range(5)}, 0.5)
        self.achord.update(type=0, path=1, time=0.4, stagger=0, order=0, root=True)
        self.aprog.update(steps=[5, 0, 4, 3, None, None, None, None], time=4, run=False)
        self.amb_prog_toggle()
        self.flash("GLIDE CHORDS   START STOPS IT")

    def amb_prog_toggle(self):
        p = self.aprog
        if not any(s is not None for s in p["steps"]):
            self.flash("NO CHORDS IN THE PROGRESSION   SETTINGS > CHORDS")
            return
        p["run"] = not p["run"]
        p["i"], p["next"] = -1, 0.0
        steps = "  ".join(ROMAN[s % 7] for s in p["steps"] if s is not None)
        if p["run"] and edition.PLAY:
            self.flash("PLAY A MELODY:  BUTTONS ARE NOTES   L-STICK: SIDEWAYS STRUM, UP/DOWN ARP")
        else:
            self.flash(("PROGRESSION  %s   EVERY %gs" % (steps, p["time"])) if p["run"] else "PROGRESSION STOPPED")

    def amb_evolve(self):
        """Every sounding drone glides to a nearby note of the scale: the slow
        harmonic turn of a film cue."""
        import random
        moved = 0
        for i in range(6):
            v = self.av[i]
            if not v["on"]:
                continue
            sc = M().SCALES[self.scale]
            cands = [n for n in range(v["note"] - 5, v["note"] + 6) if (n - self.key) % 12 in sc and n != v["note"]]
            if cands:
                moves = getattr(self, "_ev_moves", {})
                moves[i] = random.choice(cands)
                self._ev_moves = moves
                moved += 1
        if moved:
            self.amb_glide_all(self._ev_moves, "EVOLVE   %d VOICES GLIDING" % moved)
        else:
            self.flash("TURN SOME VOICES ON FIRST")
        self._ev_moves = {}

    # ------------------------------------------------------------ time
    def amb_tick(self, now):
        self.amb_tutorial_tick(now)
        if edition.PLAY:
            self.amb_midi_tick(now)
            self.amb_arp_tick(now)
        if edition.PLAY and not getattr(self, "_tex_started", False):
            self._tex_started = True
            self.amb_midi_start()
            self.amb_set_texture()                         # the texture bed you left playing comes back
            self.eng.post("pluck_warm", list(range(43, 101)), self.astrum["inst"])   # every strum note, built ahead
            self.amb_strum_fx()
        pb = getattr(self, "_preview_back", None)
        if pb and now >= pb[0]:
            self._preview_back = None
            self.amb_play(pb[1])                        # back to the chord you were on
        dt = min(0.25, now - self.alast)
        self.alast = now
        sw = getattr(self, "aswell", None)
        if sw:
            t0, dur, f0 = sw
            p = min(1.0, (now - t0) / dur)
            f = round(f0 * (1 - p) ** 2, 3)
            if abs(f - getattr(self, "aswell_sent", -1)) > 0.004 or p >= 1:
                self.aswell_sent = f
                if not (getattr(self, "rx", 0.0) or 0.0):            # the right stick wins while it is pushed
                    self.eng.post("filter", f, 0.0)
            if p >= 1:
                self.aswell = None
        # the progression steps through its chords
        pr = self.aprog
        if pr["run"] and now >= pr["next"]:
            for _ in range(8):
                pr["i"] = (pr["i"] + 1) % 8
                if pr["steps"][pr["i"]] is not None:
                    break
            pr["next"] = now + float(pr["time"])
            if pr["steps"][pr["i"]] is not None:
                self.amb_chord(pr["steps"][pr["i"]], with_move=self.achord.get("prog_move", False))
        # the melodic voices step through their notes
        for j, m in enumerate(self.amel):
            i = 6 + j
            if not m["run"]:
                continue
            if now >= m["next"]:
                for _ in range(5):
                    m["i"] = (m["i"] + 1) % 5
                    if m["steps"][m["i"]] is not None:
                        break
                deg = m["steps"][m["i"]]
                m["next"] = now + float(m["time"])
                if deg is None:
                    continue
                v = self.av[i]
                v["note"] = self.amb_degree_midi(deg)
                v["cents"] = 0
                if struck(self.amb_patch(i)):
                    if v["base"] is None:
                        self.amb_render(i)
                    self.eng.post("amb_trig", i, self.amb_tgt(i))
                    self.aui[i]["cur"] = v["note"] * 100.0
                    self.aui[i]["hit"] = now
                else:
                    self.amb_push(i)
        # the screen's model of every voice: same glide and fade as the engine
        for i, v in enumerate(self.av):
            u = self.aui[i]
            tgt = v["note"] * 100.0 + v["cents"] + (self.aexp[i]["bend"] if i in self.aexp else 0.0)
            if u["cur"] is None:
                u["cur"] = tgt
            if i in self.aexp:
                u["cur"] = tgt + (u["cur"] - tgt) * math.exp(-dt / 0.03)
                u["path"] = None
            elif u.get("path"):
                el = now - u["t0"] - u["delay"]
                u["cur"] = engine.Engine.amb_path_at(u["path"], el, u["dur"], u["shape"])
                if el >= u["dur"]:
                    u["path"] = None
            elif v["glide"] and v["glide"] > 0.02:
                u["cur"] = tgt + (u["cur"] - tgt) * math.exp(-4.0 * dt / v["glide"])
            else:
                u["cur"] = tgt
            lt = v["level"] if v["on"] else 0.0
            step = dt / max(0.05, float(v["fade"]))
            u["lvl"] = min(lt, u["lvl"] + step) if lt > u["lvl"] else max(lt, u["lvl"] - step)
        self.sounding = [v["note"] for v in self.av if v["on"]]          # the keyboard lights them
        if now - self.ahist_t > 0.08:
            self.ahist_t = now
            for i in range(NV):
                h = self.ahist[i]
                u = self.aui[i]
                h.append((now, u["cur"], u["lvl"]))
                while h and now - h[0][0] > HIST_SECS:
                    h.pop(0)

    # ------------------------------------------------------------ settings pages
    def amb_menu_pages(self):
        return ["Voice", "Chords", "Melody", "Scenes", "Global", "FX"]

    def amb_menu_items(self, pg):
        mm = M()
        if pg == "Voice":
            i = self.asel
            v = self.av[i]
            vname = ("Voice %d   %s" % (i + 1, GLYPH[DRONE_BTNS[i]])) if i < 6 else ("Melody %s" % "AB"[i - 6])
            nn = mm.NOTE_NAMES[v["note"] % 12] + str(v["note"] // 12 - 1)
            return [("Voice", vname), ("Sound", self.amb_patch(i)["name"]), ("On", "On" if v["on"] else "Off"),
                    ("Note", nn), ("Fine", "%+d cents" % v["cents"]), ("Level", "%d%%" % round(v["level"] * 100)),
                    ("Pan", "C" if abs(v["pan"]) < 0.05 else ("L%d" % round(-v["pan"] * 100) if v["pan"] < 0
                                                               else "R%d" % round(v["pan"] * 100))),
                    ("Glide", ("%g s" % v["glide"]) if v["glide"] else "Off"), ("Fade", "%g s" % v["fade"]),
                    ("Vibrato", "%d cents" % v["vib"]), ("Rate", "%.2f Hz" % v["rate"]),
                    ("Tremolo", "%d%%" % round(v["trem"] * 100)), ("Drift", "%d cents" % v["drift"])]
        if pg == "Chords":
            ch = self.achord
            return [("Bend range", "%d semitones" % self.aexpr["range"]), ("Bend settles on", SNAPS[self.aexpr["snap"]]),
                    ("Chord", CHORDS[ch["type"] % len(CHORDS)][0]), ("Path", PATHS[ch["path"] % len(PATHS)]),
                    ("Glide timing", TIMINGS[ch.get("timing", 0) % len(TIMINGS)]),
                    ("Glide time", "%g s" % ch["time"]), ("Stagger", ("%g s apart" % ch["stagger"]) if ch["stagger"] else "Off"),
                    ("Order", ORDERS[ch["order"]]),
                    ("Bass on root", "On" if ch.get("root") else "Off"),
                    ("Sub bass", "On" if ch.get("sub") else "Off"),
                    ("Scrub release", self.SCRUB_RELEASE[ch.get("scrub_release", 0) % 3]),
                    ("Move", "%s   (R2 + chord)" % MOVES[ch["move"] % len(MOVES)]),
                    ("Progression moves", "On" if ch.get("prog_move") else "Off"),
                    ("Progression", "playing   START stops" if self.aprog["run"] else "START plays it"),
                    ("Chord time", "%g s each" % self.aprog["time"])] + [
                ("Chord %d" % (s + 1), "-" if self.aprog["steps"][s] is None else ROMAN[self.aprog["steps"][s] % 7])
                for s in range(8)]
        if pg == "Melody":
            j = max(0, self.asel - 6) if self.asel >= 6 else getattr(self, "amel_sel", 0)
            self.amel_sel = j
            m = self.amel[j]
            sc = mm.SCALES[self.scale]
            rows = []
            if edition.PLAY:
                sa = self.astrum
                rows += [("Strum sound", engine.Engine.PLUCKS[sa["inst"] % len(engine.Engine.PLUCKS)][0]),
                         ("Strum level", "%d%%" % round(sa["level"] * 100)),
                         ("Arp pattern", self.ARP_STYLES[sa["style"] % len(self.ARP_STYLES)]),
                         ("Strum range", "%d octave%s" % (sa["range"], "" if sa["range"] == 1 else "s")),
                         ("Strum reverb", sa["rev"]),
                         ("Strum space", "%d%%" % round(sa["rev_amt"] * 100)),
                         ("Strum echo", sa["dly"]),
                         ("Strum echo amount", "%d%%" % round(sa["dly_amt"] * 100)),
                         ("Strum echo time", mm.DELAY_TIMES[sa["dly_time"] % len(mm.DELAY_TIMES)][0])]
            rows += [("Melody", "Melody %s   %s" % ("AB"[j], "running" if m["run"] else "stopped"))]
            for s in range(5):
                d = m["steps"][s]
                rows.append(("Step %d" % (s + 1), "rest" if d is None else
                             "%s  (degree %d)" % (mm.NOTE_NAMES[(self.key + sc[d % 7]) % 12] + str(4 + d // 7), d + 1)))
            rows.append(("Step time", "%g s" % m["time"]))
            rows.append(("Sound", self.amb_patch(6 + j)["name"]))
            rows.append(("Glide", ("%g s" % self.av[6 + j]["glide"]) if self.av[6 + j]["glide"] else "Off"))
            return rows
        if pg == "Scenes":
            mm = M()
            rows = [("Guided demo", "A starts it"), ("Starter", "Glide Chords"), ("Starter 2", "Deep Bloom"),
                    ("Morph time", "%d s" % self.amorph)]
            for s in range(6):
                sc = self.ascenes[s] if s < len(self.ascenes) else None
                g = mm.BUTTON_GLYPH[mm.CHORD_BUTTONS[s]]
                rows.append(("Scene %d" % (s + 1), ("L2 + %s recalls" % g) if sc else "SELECT + %s saves" % g))
            return rows
        return []

    def amb_menu_change(self, pg, name, d):
        if pg == "Voice":
            i = self.asel
            v = self.av[i]
            if name == "Voice":
                self.asel = (i + d) % NV
                return
            if name == "Sound":
                v["snd"] = self.amb_next_sound(v["snd"], d)
                v["base"] = None
                if v["on"]:
                    self.amb_render(i)
                self.amb_push(i)
                return
            if name == "On":
                self.amb_toggle(i)
                return
            if name == "Note":
                v["note"] = max(24, min(96, v["note"] + d))
            elif name == "Fine":
                v["cents"] = max(-50, min(50, v["cents"] + 2 * d))
            elif name == "Level":
                v["level"] = round(max(0.0, min(1.0, v["level"] + 0.05 * d)), 2)
            elif name == "Pan":
                v["pan"] = round(max(-1.0, min(1.0, v["pan"] + 0.1 * d)), 2)
            elif name == "Glide":
                v["glide"] = self._amb_step(GLIDES, v["glide"], d)
            elif name == "Fade":
                v["fade"] = self._amb_step(FADES, v["fade"], d)
            elif name == "Vibrato":
                v["vib"] = max(0, min(60, v["vib"] + 2 * d))
            elif name == "Rate":
                v["rate"] = round(max(0.02, min(6.0, v["rate"] * (1.25 if d > 0 else 0.8))), 3)
            elif name == "Tremolo":
                v["trem"] = round(max(0.0, min(1.0, v["trem"] + 0.05 * d)), 2)
            elif name == "Drift":
                v["drift"] = max(0, min(100, v["drift"] + 2 * d))
            self.amb_push(i)
            return
        if pg == "Melody" and name.startswith(("Strum", "Arp")):
            sa = self.astrum
            mm = M()
            if name == "Strum reverb":
                sa["rev"] = synth.REVERBS[(synth.REVERBS.index(sa["rev"]) + d) % len(synth.REVERBS)] \
                    if sa["rev"] in synth.REVERBS else synth.REVERBS[0]
            elif name == "Strum space":
                sa["rev_amt"] = round(max(0.0, min(1.0, sa["rev_amt"] + 0.05 * d)), 2)
            elif name == "Strum echo":
                sa["dly"] = mm.DELAY_TYPES[(mm.DELAY_TYPES.index(sa["dly"]) + d) % len(mm.DELAY_TYPES)] \
                    if sa["dly"] in mm.DELAY_TYPES else mm.DELAY_TYPES[0]
            elif name == "Strum echo amount":
                sa["dly_amt"] = round(max(0.0, min(1.0, sa["dly_amt"] + 0.05 * d)), 2)
            elif name == "Strum echo time":
                sa["dly_time"] = (sa["dly_time"] + d) % len(mm.DELAY_TIMES)
            if name in ("Strum reverb", "Strum space", "Strum echo", "Strum echo amount", "Strum echo time"):
                self.amb_strum_fx()
            if name == "Strum sound":
                sa["inst"] = (sa["inst"] + d) % len(engine.Engine.PLUCKS)
                self.eng.post("pluck_warm", list(range(43, 101)), sa["inst"])
            elif name == "Strum level":
                sa["level"] = round(max(0.1, min(2.5, sa["level"] + 0.1 * d)), 2)
            elif name == "Arp pattern":
                sa["style"] = (sa["style"] + d) % len(self.ARP_STYLES)
            elif name == "Strum range":
                sa["range"] = max(1, min(4, sa["range"] + d))
            tones = self.amb_strum_tones()                 # hear it: a quick strum of the chord
            for k, n in enumerate(tones[:: max(1, len(tones) // 5)][:5]):
                self.eng.post("pluck", int(n), 0.6 * sa["level"], -0.4 + 0.2 * k, sa["inst"])
            return
        if pg == "Melody":
            j = getattr(self, "amel_sel", 0)
            m = self.amel[j]
            if name == "Melody":
                self.amel_sel = (j + d) % 2
                self.asel = 6 + self.amel_sel
            elif name.startswith("Step ") and name != "Step time":
                s = int(name.split()[1]) - 1
                opts = [None] + list(range(15))
                cur = m["steps"][s]
                m["steps"][s] = opts[(opts.index(cur) + d) % len(opts)]
            elif name == "Step time":
                m["time"] = self._amb_step(STEP_TIMES, m["time"], d)
            elif name == "Sound":
                v = self.av[6 + j]
                v["snd"] = self.amb_next_sound(v["snd"], d)
                v["base"] = None
                if v["on"]:
                    self.amb_render(6 + j)
                self.amb_push(6 + j)
            elif name == "Glide":
                v = self.av[6 + j]
                v["glide"] = self._amb_step(GLIDES, v["glide"], d)
                self.amb_push(6 + j)
            return
        if pg == "Chords":
            ch = self.achord
            if name == "Bend range":
                self.aexpr["range"] = self._amb_step(BEND_RANGES, self.aexpr["range"], d)
            elif name == "Bend settles on":
                self.aexpr["snap"] = (self.aexpr["snap"] + d) % len(SNAPS)
            elif name == "Chord":
                ch["type"] = (ch["type"] + d) % len(CHORDS)
            elif name == "Path":
                ch["path"] = (ch["path"] + d) % len(PATHS)
                self.amb_preview_path()
            elif name == "Glide time":
                ch["time"] = self._amb_step(CHORD_TIMES, ch["time"], d)
            elif name == "Stagger":
                ch["stagger"] = self._amb_step(STAGGERS, ch["stagger"], d)
            elif name == "Order":
                ch["order"] = (ch["order"] + d) % len(ORDERS)
            elif name == "Glide timing":
                ch["timing"] = (ch.get("timing", 0) + d) % len(TIMINGS)
                self.amb_preview_path()
            elif name == "Bass on root":
                ch["root"] = not ch.get("root")
            elif name == "Sub bass":
                ch["sub"] = not ch.get("sub")
                if not ch["sub"] and self.av[5]["on"]:
                    self.av[5]["on"] = False
                    self.amb_push(5)
            elif name == "Scrub release":
                ch["scrub_release"] = (ch.get("scrub_release", 0) + d) % 3
            elif name == "Move":
                ch["move"] = (ch["move"] + d) % len(MOVES)
            elif name == "Progression moves":
                ch["prog_move"] = not ch.get("prog_move")
            elif name == "Progression":
                self.amb_prog_toggle()
            elif name == "Chord time":
                self.aprog["time"] = self._amb_step(PROG_TIMES, self.aprog["time"], d)
            elif name.startswith("Chord ") and name[6:].isdigit():
                s = int(name[6:]) - 1
                opts = [None] + list(range(7))
                cur = self.aprog["steps"][s]
                self.aprog["steps"][s] = opts[(opts.index(cur) + d) % len(opts)]
            return
        if pg == "Scenes" and name == "Morph time":
            self.amorph = self._amb_step(MORPHS, self.amorph, d)

    def amb_menu_activate(self, pg, name):
        if pg == "Voice" and name == "On":
            self.amb_toggle(self.asel)
        elif pg == "Melody" and name == "Melody":
            self.amb_toggle(6 + getattr(self, "amel_sel", 0))
        elif pg == "Chords" and name == "Progression":
            self.amb_prog_toggle()
        elif pg == "Scenes" and name == "Guided demo":
            self.menu = False
            self.amb_tutorial_start()
        elif pg == "Scenes" and name == "Starter":
            self.menu = False
            self.amb_starter()
        elif pg == "Scenes" and name == "Starter 2":
            self.menu = False
            self.amb_deep_bloom()
        elif pg == "Scenes" and name.startswith("Scene "):
            self.menu = False
            self.amb_recall(int(name.split()[1]) - 1)

    @staticmethod
    def _amb_step(opts, cur, d):
        i = min(range(len(opts)), key=lambda n: abs(opts[n] - cur))
        return opts[max(0, min(len(opts) - 1, i + d))]

    # ------------------------------------------------------------ drawing
    def amb_header_info(self):
        n = sum(1 for v in self.av if v["on"])
        chord = getattr(self, "acur_name", "") if n else ""
        return "%s%s %s%s" % ((chord + "   ") if chord else "", M().NOTE_NAMES[self.key], self.scale,
                              "   PROGRESSION" if self.aprog.get("run") else "")

    # ------------------------------------------------------------ spectrogram view (L3)
    SPEC_LO, SPEC_HI = 45.0, 4000.0

    def amb_spec_feed(self, w, h):
        """Take each new block of output from the scope, keep the last 2048 samples,
        and add one column of a log-frequency spectrogram: harmonics as lines."""
        e = getattr(self.eng, "eng", None)
        sc = getattr(e, "scope", None)
        if sc is None or not len(sc):
            return
        last = getattr(self, "_spec_last", None)
        if last is not None and len(last) == len(sc) and np.array_equal(last, sc):
            return                                          # the same block again
        self._spec_last = np.array(sc, copy=True)
        buf = getattr(self, "_spec_buf", None)
        if buf is None:
            buf = np.zeros(2048, np.float32)
        buf = np.concatenate([buf, np.asarray(sc, np.float32)])[-2048:]
        self._spec_buf = buf
        surf = getattr(self, "_spec_surf", None)
        if surf is None or surf.get_size() != (w, h):
            surf = self._spec_surf = pygame.Surface((w, h))
            surf.fill(M().BG)
            self._spec_grid = None
        sr = 11025.0                                        # the scope is the output at half rate
        if getattr(self, "_spec_win", None) is None:
            self._spec_win = np.hanning(2048).astype(np.float32)
        mag = np.abs(np.fft.rfft(buf * self._spec_win))
        prev = getattr(self, "_spec_avg", None)
        mag = mag if prev is None else 0.55 * prev + 0.45 * mag    # steadier lines, less flicker
        self._spec_avg = mag
        db = 20 * np.log10(mag + 1e-6)
        pk = getattr(self, "_spec_pk", -40.0)
        pk = max(float(db.max()), pk - 0.25)               # a slowly falling reference
        self._spec_pk = pk
        # crisp lines, not a heat map: only the spectral peaks are drawn. Each peak's
        # frequency is refined between bins (parabolic), then placed on the log scale,
        # so a harmonic is a thin bright line wherever it sits.
        lo_b, hi_b = int(self.SPEC_LO / sr * 2048) + 1, min(1022, int(self.SPEC_HI / sr * 2048))
        d = db[lo_b - 1:hi_b + 2]
        mid = d[1:-1]
        is_pk = (mid > d[:-2]) & (mid >= d[2:]) & (mid > pk - 32)
        idx = np.nonzero(is_pk)[0]
        if len(idx) > 24:                                   # the strongest 24: the harmonics that matter
            idx = idx[np.argsort(mid[idx])[-24:]]
        last = getattr(self, "_spec_lines", {})              # row -> (colour, age) from the columns before
        last_rows = set(last)
        rows_now = {}
        col = np.tile(np.array(M().BG, np.uint8), (h, 1))
        grid = getattr(self, "_spec_grid", None)
        if grid is None or len(grid[0]) != h:
            rows = []
            for n in range(12, 120, 12):                    # faint octave lines of the key
                fq = 440.0 * 2 ** ((n + self.key - 69) / 12.0)
                if self.SPEC_LO < fq < self.SPEC_HI:
                    rows.append(int(round((h - 1) * (1 - math.log(fq / self.SPEC_LO) /
                                                     math.log(self.SPEC_HI / self.SPEC_LO)))))
            grid = self._spec_grid = (np.zeros(h), rows)
        gcol = np.array(self.mix(M().BG, M().DIM, 0.22), np.uint8)
        for r in grid[1]:
            col[r] = gcol
        v = np.array(M().ACCENT, np.float32)
        g = np.array(M().ACCENT2, np.float32)
        wht = np.array((250, 246, 236), np.float32)
        logspan = math.log(self.SPEC_HI / self.SPEC_LO)
        for j in idx:
            a_, b_, c_ = d[j], d[j + 1], d[j + 2]
            den = a_ - 2 * b_ + c_
            off = 0.5 * (a_ - c_) / den if den != 0 else 0.0
            fq = (lo_b + j + off) * sr / 2048
            if not (self.SPEC_LO < fq < self.SPEC_HI):
                continue
            y = int(round((h - 1) * (1 - math.log(fq / self.SPEC_LO) / logspan)))
            lv = min(1.0, max(0.0, (b_ - (pk - 32)) / 32.0))
            near = [r for r in last_rows if abs(r - y) <= 8]
            # a line continues from the column before (or is strong enough to start one):
            # stray one-column specks are left out
            if lv < 0.6 and not any(abs(r - y) <= 2 for r in near):
                continue
            lv = round(lv * 4) / 4.0                        # a few steps of brightness: digital, not smeared
            cc = v + (g - v) * min(1.0, lv / 0.7) if lv < 0.7 else g + (wht - g) * ((lv - 0.7) / 0.3)
            ci = cc.astype(np.uint8)
            col[y] = ci
            if near:                                         # a glide: join it to where it was, no gaps
                r0 = min(near, key=lambda r: abs(r - y))
                if abs(r0 - y) > 1:
                    lo_, hi_ = sorted((r0, y))
                    col[lo_:hi_ + 1] = ci
            if lv >= 0.5 and 0 < y < h - 1:                 # strong harmonics get a 2 px line
                col[y + 1] = (cc * 0.55 + np.array(M().BG) * 0.45).astype(np.uint8)
            rows_now[y] = (ci, 0)
        for r, (ci, age) in last.items():                  # a line missing for a column holds briefly
            if age < 2 and r not in rows_now and not any(abs(r - y) <= 2 for y in rows_now):
                col[r] = ci
                rows_now[r] = (ci, age + 1)
        self._spec_lines = rows_now
        surf.scroll(-1, 0)
        px = pygame.surfarray.pixels3d(surf)
        px[w - 1, :, :] = col
        del px

    def draw_ambient(self, c, now):
        mm = M()
        L = mm.L
        W = mm.BASE_W
        gx0, gx1 = 20, W - 20
        gy0, gy1 = 46, L["tiles_y"] - 12
        pygame.draw.rect(c, self.mix(mm.BG, mm.PANEL, 0.55), (gx0 - 8, gy0 - 4, gx1 - gx0 + 16, gy1 - gy0 + 8),
                         border_radius=10)
        if getattr(self, "aview", "guides") == "spectrum":
            gw, gh = gx1 - gx0, gy1 - gy0
            self.amb_spec_feed(gw, gh)
            if getattr(self, "_spec_surf", None) is not None:
                c.blit(self._spec_surf, (gx0, gy0))
            # a few note names up the side, where those frequencies sit
            for n in range(24, 108, 12):
                fq = 440.0 * 2 ** ((n + self.key - 69) / 12.0)
                if self.SPEC_LO < fq < self.SPEC_HI:
                    y = gy1 - math.log(fq / self.SPEC_LO) / math.log(self.SPEC_HI / self.SPEC_LO) * gh
                    self.text(c, mm.note_name((n + self.key) % 12, self.key, self.scale) + str((n + self.key) // 12 - 1),
                              self.f_small,
                              self.mix(mm.BG, mm.DIM, 0.8), (gx0 + 4, int(y) - 15))
            lab = "SPECTROGRAM    L3: GUIDES"
            lw = self.f_small.size(lab)[0] + 16
            pygame.draw.rect(c, mm.BG, (gx1 - lw - 2, gy0 + 3, lw, 20), border_radius=8)
            self.text(c, lab, self.f_small, mm.DIM, (gx1 - lw // 2 - 2, gy0 + 13), center=True)
            self.draw_amb_tiles(c, now)
            self.draw_amb_tutorial(c, now)
            return
        # the range follows the voices (at least three octaves), easing as they move
        ps = [p for i in range(NV) if self.aui[i]["lvl"] > 0.01 or self.av[i]["on"]
              for p in (self.aui[i]["cur"] or 0, self.av[i]["note"] * 100.0) if p]
        if ps:
            mid = (min(ps) + max(ps)) / 2.0
            span = max(3600.0, max(ps) - min(ps) + 900.0)
        else:
            mid, span = (self.key + 60) * 100.0, 4800.0
        mid = self.sm("amb_mid", mid, 2.5)
        span = self.sm("amb_span", span, 2.5)
        lo, hi = mid - span / 2.0, mid + span / 2.0

        def ypos(cents):
            return gy1 - (cents - lo) / (hi - lo) * (gy1 - gy0)
        # guides: every note of the scale, roots and fifths brighter and labelled
        sc = mm.SCALES[self.scale]
        for n in range(int(lo // 100), int(hi // 100) + 1):
            if (n - self.key) % 12 not in sc:
                continue
            y = int(ypos(n * 100))
            root = (n - self.key) % 12 == 0
            fifth = (n - self.key) % 12 == 7
            col = self.mix(mm.BG, mm.DIM, 0.55 if root else (0.32 if fifth else 0.16))
            pygame.draw.line(c, col, (gx0, y), (gx1, y), 1)
            if root or fifth:
                self.text(c, mm.note_name(n % 12, self.key, self.scale) + str(n // 12 - 1), self.f_small, col,
                          (gx0 + 2, y - 15))
        # each voice's pitch over the last seconds: a line that glides
        span = HIST_SECS
        for i in range(NV):
            h = self.ahist[i]
            if len(h) < 2:
                continue
            col = VCOL[i]
            pts = []
            for (t, cents, lvl) in h:
                if lvl < 0.01:
                    if len(pts) > 1:
                        pygame.draw.lines(c, self.mix(mm.BG, col, 0.85), False, pts, 2)
                    pts = []
                    continue
                pts.append((int(gx1 - (now - t) / span * (gx1 - gx0)), int(ypos(cents))))
            if len(pts) > 1:
                pygame.draw.lines(c, self.mix(mm.BG, col, 0.85), False, pts, 2 if i < 6 else 3)
            u = self.aui[i]
            v = self.av[i]
            if u["lvl"] > 0.01:
                y = int(ypos(u["cur"]))
                rr = 4 + int(4 * u["lvl"])
                pygame.draw.circle(c, col, (gx1, y), rr)
                tgt = v["note"] * 100.0 + v["cents"]
                if abs(tgt - u["cur"]) > 8:                    # gliding: a guide to where it is headed
                    ty = int(ypos(tgt))
                    for yy in range(min(y, ty), max(y, ty), 6):
                        pygame.draw.line(c, col, (gx1 + 6, yy), (gx1 + 6, min(yy + 3, max(y, ty))), 1)
                    pygame.draw.line(c, col, (gx1 + 2, ty), (gx1 + 10, ty), 2)
        self.draw_amb_tiles(c, now)
        # the progression: its chords along the bottom of the graph, the current one lit
        pr = self.aprog
        if pr["run"]:
            xx = gx0 + 100
            for s, deg in enumerate(pr["steps"]):
                if deg is None:
                    continue
                lab = mm.roman_for(deg % 7, mm.build_chord(self.key, self.scale, deg % 7, {})[1])
                r = self.text(c, lab, self.f_small, mm.ACCENT if s == pr["i"] else mm.DIM, (xx, gy1 - 16))
                xx = r.right + 10
        # scenes: six dots under the graph
        for s in range(6):
            sx = gx0 + s * 14
            full = s < len(self.ascenes) and self.ascenes[s]
            pygame.draw.circle(c, mm.ACCENT if full else self.mix(mm.BG, mm.DIM, 0.5), (sx + 4, gy1 + 2), 3)
        self.draw_amb_tutorial(c, now)

    def draw_amb_tiles(self, c, now):
        """Seven chord tiles, like Brickchord's: the chord you are on lit."""
        mm = M()
        L = mm.L
        W = mm.BASE_W
        tw, gap = 82, 6
        x0 = (W - (7 * tw + 6 * gap)) // 2
        th = L["tile_h"]
        m = self.mods()
        ck = (self.key, self.scale, tuple(sorted(k for k, v in m.items() if v)))
        if getattr(self, "_amb_ck", None) != ck:
            self._amb_ck = ck
            self._amb_chords = [mm.build_chord(self.key, self.scale, i, m) for i in range(7)]
        cur = getattr(self, "acur_deg", None)
        if self.amb_melody_mode():
            self.draw_amb_melody_tiles(c, now, x0, tw, gap, th)
            return
        for i, btn in enumerate(mm.CHORD_BUTTONS):
            pc, iv, name = self._amb_chords[i]
            active = cur == i and any(self.av[k]["on"] for k in range(6))
            lv = self.sm("atile%d" % i, 1.0 if active else 0.0, 20 if active else 4)
            sc = getattr(self, "ascrub", None)
            if sc is not None and sc["active"]:              # scrubbing: the tiles cross-fade with the stick
                if i == sc["deg"]:
                    lv = max(lv * 0, sc["p"])
                elif active:
                    lv = 1.0 - sc["p"]
            r = pygame.Rect(x0 + i * (tw + gap), L["tiles_y"], tw, th)
            pygame.draw.rect(c, self.mix(mm.PANEL, mm.ACCENT, lv), r, border_radius=10)
            self.text(c, mm.roman_for(i, iv), self.f_med, self.mix(mm.ACCENT2, mm.BG, lv), (r.centerx, r.y + th * 21 // 100),
                      center=True)
            self.text(c, name, self.f_med if len(name) < 6 else self.f_small, self.mix(mm.INK, mm.BG, lv),
                      (r.centerx, r.y + th * 54 // 100), center=True)
            self.text(c, mm.BUTTON_GLYPH[btn], self.f_small, self.mix(mm.DIM, mm.BG, lv), (r.centerx, r.y + th * 83 // 100),
                      center=True)
        self.draw_amb_scrub(c, now)

    # ------------------------------------------------------------ the intro film
    INTRO_SECS = 4.6

    def amb_intro_wave(self):
        """A soft band-limited saw, made right here (no render wait): one second that
        loops exactly, at 131 Hz, the base note C3 and a little."""
        import numpy as np
        sr = 22050
        n = np.arange(sr)
        x = sum(np.sin(2 * np.pi * 131 * k * n / sr) / k * (0.92 ** k) for k in range(1, 14))
        x = (x / np.abs(x).max() * 0.11).astype(np.float32)
        st = np.repeat(x[:, None], 2, axis=1)
        return np.ascontiguousarray(st[:1024]), np.ascontiguousarray(np.concatenate([st[1024:], st[:1024]]))

    def amb_intro_notes(self):
        """The home chord of the key, laid out over two octaves, and the note they all start on."""
        mm = M()
        pc, iv, _ = mm.build_chord(self.key, self.scale, 0, {})
        r = 48 + (pc % 12)
        if r > 54:
            r -= 12
        notes = [r - 12, r, r + 12 + iv[1], r + 12 + iv[2], r + 24]
        return r + iv[2], notes          # they all start on the fifth and fan out both ways

    def amb_intro_start(self):
        """Five voices on one note, about to bloom: the same sound the app is about."""
        base = 48 + 12 * 0      # the wave's own pitch is 131 Hz ~ C3 (48) + 3 cents
        r, notes = self.amb_intro_notes()
        snd = self.amb_intro_wave()
        self._intro = {"r": r, "notes": notes, "bloomed": False, "out": False}
        for i in range(5):
            self.eng.post("amb_snd", i, snd, True)
            self.eng.post("amb", i, {"tgt": (r - base) * 100.0 - 3, "on": True, "level": 0.55 if i else 0.7,
                                     "pan": [0.0, -0.55, 0.55, -0.3, 0.3][i], "fade": 0.5, "glide": 0.0,
                                     "vib": 3.0, "rate": 0.3 + 0.07 * i, "trem": 0.0, "drift": 0.0, "jump": True})

    def amb_intro_tick(self, t):
        st = getattr(self, "_intro", None)
        if st is None:
            return
        if not st["bloomed"] and t >= 0.8:
            st["bloomed"] = True
            for i, n in enumerate(st["notes"]):
                self.eng.post("amb", i, {"tgt": (n - 48) * 100.0 - 3, "glide": 2.4, "shape": 2,
                                         "delay": 0.08 * i})
        if not st["out"] and t >= 3.4:
            st["out"] = True
            self.amb_intro_end(fade=1.4)

    def amb_intro_end(self, fade=0.4):
        """Let the intro voices go; the slots are rendered with the real sounds when played."""
        for i in range(5):
            self.eng.post("amb", i, {"on": False, "fade": float(fade)})
        self._intro_done = True

    def draw_amb_intro(self, c, t):
        """The film: five lines leave one point and bloom into the chord across the
        screen, the mark settles above them, and the name types in."""
        mm = M()
        W, H = mm.BASE_W, mm.BASE_H
        st = getattr(self, "_intro", None)
        r, notes = (st["r"], st["notes"]) if st else self.amb_intro_notes()
        x0, x1 = 50, W - 50
        lo, hi = min(notes) - 3, max(notes) + 3
        ytop, ybot = H * 0.42, H * 0.93

        def ypos(m):
            return ybot - (m - lo) / float(hi - lo) * (ybot - ytop)
        span = 3.3
        head = min(1.0, t / span)
        fade_out = max(0.0, min(1.0, (t - 3.6) / 0.8))
        for i, n in enumerate(notes):
            col = VCOL[i]
            col = self.mix(col, mm.BG, 0.55 * fade_out)
            pts = []
            steps = max(2, int(80 * head))
            for s in range(steps + 1):
                tt = span * head * s / steps
                d = 0.08 * i
                p = 0.0 if tt < 0.8 + d else min(1.0, (tt - 0.8 - d) / 2.4)
                e = p * p * (3 - 2 * p)
                m = r + (n - r) * e
                pts.append((x0 + (x1 - x0) * tt / span, ypos(m)))
            if len(pts) > 1:
                pygame.draw.lines(c, col, False, [(int(x), int(y)) for x, y in pts], 3)
                hx, hy = pts[-1]
                if head < 1.0:
                    pygame.draw.circle(c, col, (int(hx), int(hy)), 5)
        # the mark: 4 x 4 keys, the first lit, dropping in once the bloom is under way
        k, g = 20, 6
        mx = W // 2 - (4 * k + 3 * g) // 2
        my = int(H * 0.08)
        for i in range(16):
            ti = 1.6 + 0.035 * i
            p = max(0.0, min(1.0, (t - ti) / 0.25))
            if p <= 0:
                continue
            drop = int((1 - p) ** 2 * -18)
            col = mm.ACCENT if i == 0 else mm.INK
            col = self.mix(mm.BG, col, p)
            x = mx + (i % 4) * (k + g)
            y = my + (i // 4) * (k + g) + drop
            pygame.draw.rect(c, col, (x, y, k, k), border_radius=4)
        # the name types in under the mark
        word = "brickglide"
        n = 0 if t < 2.3 else min(len(word), int((t - 2.3) / 0.055) + 1)
        if n:
            full = self.f_big.render(word, True, mm.INK)
            part = self.f_big.render(word[:n], True, mm.INK)
            x = W // 2 - full.get_width() // 2
            y = my + 4 * k + 3 * g + 22
            c.blit(part, (x, y))
            if n < len(word) or int(t * 6) % 2 == 0:
                pygame.draw.rect(c, mm.ACCENT, (x + part.get_width() + 3, y + 8, 4, full.get_height() - 14))


    def draw_amb_scrub(self, c, now):
        """While a chord button is held: a slider from the chord you are on to the one
        you are holding, its marker where the voices are, so you can see the stick is
        what moves them."""
        sc = getattr(self, "ascrub", None)
        if sc is None:
            return
        mm = M()
        W = mm.BASE_W
        p = sc["p"]
        w, h = 440, 66
        r = pygame.Rect((W - w) // 2, mm.L["tiles_y"] - h - 10, w, h)
        pygame.draw.rect(c, self.mix(mm.BG, mm.PANEL, 0.96), r, border_radius=14)
        pygame.draw.rect(c, mm.ACCENT, r, 2, border_radius=14)
        frm = getattr(self, "acur_name", "") or "here"
        self.text(c, frm, self.f_small, self.mix(mm.INK, mm.DIM, p), (r.x + 16, r.y + 8))
        self.text(c, sc["label"], self.f_small, self.mix(mm.DIM, mm.ACCENT2, p), (r.right - 16, r.y + 8), right=True)
        tx0, tx1, ty = r.x + 24, r.right - 24, r.y + 42
        pygame.draw.line(c, self.mix(mm.BG, mm.DIM, 0.6), (tx0, ty), (tx1, ty), 4)
        mx = int(tx0 + (tx1 - tx0) * p)
        pygame.draw.line(c, mm.ACCENT, (tx0, ty), (mx, ty), 4)
        pygame.draw.circle(c, mm.ACCENT2, (mx, ty), 9)
        pygame.draw.circle(c, mm.BG, (mx, ty), 4)
        if not sc["active"]:
            b = 0.55 + 0.45 * math.sin(now * 6)
            self.text(c, "push the left stick", self.f_small, self.mix(mm.BG, mm.INK, b), (r.centerx, r.y + 8),
                      center=True)
        else:
            self.text(c, "%d%%" % round(p * 100), self.f_small, mm.INK, (r.centerx, r.y + 8), center=True)

    def draw_amb_melody_tiles(self, c, now, x0, tw, gap, th):
        """Brickglide Play: the seven buttons as melody notes over the current chord.
        The chord's own tones (1, 3, 5) are marked; a held note is lit."""
        mm = M()
        names = ["1", "2", "3", "4", "5", "6", "7"]
        for k, btn in enumerate(mm.CHORD_BUTTONS):
            n = self.amb_mel_note(k)
            held = k in self.amel_held
            lv = self.sm("amel%d" % k, 1.0 if held else 0.0, 30 if held else 6)
            r = pygame.Rect(x0 + k * (tw + gap), mm.L["tiles_y"], tw, th)
            base = self.mix(mm.PANEL, mm.ACCENT2, 0.22) if k in (0, 2, 4) else mm.PANEL
            pygame.draw.rect(c, self.mix(base, mm.ACCENT, lv), r, border_radius=10)
            self.text(c, names[k], self.f_med, self.mix(mm.ACCENT2 if k in (0, 2, 4) else mm.DIM, mm.BG, lv),
                      (r.centerx, r.y + th * 21 // 100), center=True)
            self.text(c, mm.note_name(n % 12, self.key, self.scale) + str(n // 12 - 1), self.f_med,
                      self.mix(mm.INK, mm.BG, lv), (r.centerx, r.y + th * 54 // 100), center=True)
            self.text(c, mm.BUTTON_GLYPH[btn], self.f_small, self.mix(mm.DIM, mm.BG, lv),
                      (r.centerx, r.y + th * 83 // 100), center=True)
