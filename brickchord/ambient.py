# Brickglide: an ambient machine on the Brickchord engine. Six drone voices
# you switch on and leave running, two melodic voices that step through five
# notes, long glides between pitches drawn as guides on screen, scenes that
# morph the whole texture, and the sticks for spread, movement and Cloud.
#
#   UP RIGHT DOWN LEFT X Y   drone voices 1-6: press starts one, tap a sounding one to stop it;
#                            hold one (or several) and the left stick bends and swells only
#                            those voices, MPE-style; let go and they settle on the scale
#   A B                      melodic voices 1-2: start / stop their steps
#   L1 + a voice button      select that voice (Settings opens on it)
#   R1 + a drone button      recall scene 1-6 (the voices glide there)
#   SELECT + a drone button  save the current sound as that scene
#   R2 + a drone button      glide the drones into a chord on degree I-VI (Settings > Chords
#                            picks the chord, the path shape, the time and the order)
#   R2 (tap)                 evolve: every voice glides to a new note of the scale
#   R2 + A                   run / stop the chord progression (Settings > Chords)
#   R2 + B                   bloom: every voice from one note, fanning out, the filter opening
#   START                    freeze: the cloud holds what is sounding
#   left stick               X spreads the voices apart, Y deepens their movement
#   L2 + left stick          Cloud compass (direction = texture, distance = amount)
import json
import math
import time

import numpy as np
import pygame

import engine
import synth

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
PATHS = ["Smooth", "Linear", "Ease", "Swell", "Steps"]       # Steps walks the scale notes on the way
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
    for n in ("Supersaw", "Juno Strings", "Poly Pad", "Prophet Brass", "Bowed String", "Bowed Glass", "Blown Pipe",
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
    return out


def struck(p):
    return p.get("macro") is not None and int(p.get("macro", 0)) in synth.MACRO_STRUCK


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
        default_snd = [ix("Sub Drone"), ix("Deep Space"), ix("Tape Choir"), ix("Bowed Glass"), ix("Shimmer"),
                       ix("Breath")]
        self.av = []
        for i in range(NV):
            d = {"on": False, "snd": default_snd[i] if i < 6 else ix("Kalimba" if i == 6 else "Bowed String"),
                 "note": (default_notes[i] + k) if i < 6 else 60 + k, "cents": 0,
                 "level": 0.6 if i < 6 else 0.5, "pan": [0.0, -0.4, 0.4, -0.2, 0.2, 0.0, -0.3, 0.3][i],
                 "glide": 4 if i < 6 else 2, "fade": 4 if i < 6 else 1, "vib": 4, "rate": 0.15 + 0.05 * i,
                 "trem": 0.0, "drift": 8 if i < 6 else 0, "base": None}
            if i < len(st.get("voices", [])):
                d.update({kk: vv for kk, vv in st["voices"][i].items() if kk in d})
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
        self.achord = dict({"type": 2, "path": 2, "time": 8, "stagger": 1, "order": 1, "root": True},
                           **(st.get("chord") or {}))
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
        self.eng.post("amb_global", 0.0, 1.0)

    def amb_state(self):
        keys = ("snd", "note", "cents", "level", "pan", "glide", "fade", "vib", "rate", "trem", "drift")
        return {"voices": [{k: v[k] for k in keys} for v in self.av],
                "mel": [{"steps": m["steps"], "time": m["time"]} for m in self.amel],
                "scenes": self.ascenes, "morph": self.amorph, "chord": self.achord, "expr": self.aexpr,
                "prog": {"steps": self.aprog["steps"], "time": self.aprog["time"]}}

    # ------------------------------------------------------------ talking to the engine
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
        held = self.inp.held
        if name == "R2":
            if down:
                self.r2_used = False
            elif not self.r2_used:
                self.amb_evolve()                       # a tap: evolve
            return True
        if not down:
            if name in DRONE_BTNS:
                i = DRONE_BTNS.index(name)
                e = self.aexp.pop(i, None)
                if e is not None:
                    if e["moved"]:
                        self.amb_commit_bend(i, e)       # a bend: the voice settles where you left it
                    elif e["was_on"]:
                        self.amb_toggle(i)               # a plain tap on a sounding voice: off
            return name in DRONE_BTNS + MEL_BTNS + ["START", "L3"]
        if name in DRONE_BTNS or name in MEL_BTNS:
            i = (DRONE_BTNS + MEL_BTNS).index(name)
            if "L1" in held:
                self.asel = i
                self.flash("SELECTED %s   SELECT EDITS IT" % (("VOICE %d" % (i + 1)) if i < 6 else "MELODY %s" % "AB"[i - 6]))
                return True
            if "R2" in held and i < 6:
                self.r2_used = True
                self.amb_chord(i)                       # R2 + a drone button: glide into a chord on that degree
                return True
            if "R2" in held and name == "A":
                self.r2_used = True
                self.amb_prog_toggle()                  # R2 + A: the progression runs (or stops)
                return True
            if "R2" in held and name == "B":
                self.r2_used = True
                self.amb_bloom()                        # R2 + B: every voice from one note, fanning out
                return True
            if "R1" in held and i < 6:
                self.amb_recall(i)
                return True
            if "SELECT" in held and i < 6:
                self.sel_combo = True                    # SELECT was part of a combo: no menu on release
                self.amb_save_scene(i)
                return True
            if i < 6:
                # press: an off voice starts now; hold it and the left stick bends and swells
                # just this voice (MPE-style); a plain tap on a sounding voice turns it off
                was_on = self.av[i]["on"]
                if not was_on:
                    self.amb_toggle(i)
                self.aexp[i] = {"bend": 0.0, "press": 0.0, "moved": False, "was_on": was_on, "sent": None}
            else:
                self.amb_toggle(i)
            self.asel = i
            return True
        if name == "START":
            self.afreeze = not self.afreeze
            if self.afreeze:
                self.amb_prev_cloud = list(self.rack.get("Cloud") or [False, 0.5, 3])
                self.set_cloud(True, 0.85, 7)
            else:
                pc = getattr(self, "amb_prev_cloud", [False, 0.5, 3])
                self.set_cloud(pc[0], pc[1], pc[2])
            self.flash("FREEZE " + ("ON: THE CLOUD HOLDS WHAT IS SOUNDING" if self.afreeze else "OFF"))
            return True
        if name == "L3":
            self.aview = "spectrum" if getattr(self, "aview", "guides") == "guides" else "guides"
            self.flash("VIEW: " + ("SPECTROGRAM  (the real sound, every harmonic)" if self.aview == "spectrum"
                                   else "GLIDE GUIDES"))
            return True
        return False

    def amb_stick(self, x, y):
        if "L2" in self.inp.held:
            self.l2_moved = getattr(self, "l2_moved", False) or math.hypot(x, y) > 0.3
            self.drone_cloud(x, y)
            return
        if self.aexp:
            self.amb_express(x, y)
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
        self.flash("SCENE %d SAVED   R1+%s RECALLS IT" % (s + 1, GLYPH[DRONE_BTNS[s]]))

    def amb_recall(self, s):
        sc = self.ascenes[s] if s < len(self.ascenes) else None
        if not sc:
            self.flash("SCENE %d IS EMPTY   SELECT+%s SAVES ONE" % (s + 1, GLYPH[DRONE_BTNS[s]]))
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

    def amb_glide_all(self, moves, label):
        """moves: {voice: new midi}. Every voice glides there along the chord path."""
        ch = self.achord
        shape = min(3, ch["path"])
        items = [(i, self.aui[i]["cur"] or self.av[i]["note"] * 100.0) for i in moves]
        delays = self.amb_route(ch["order"], items)
        for i, note in moves.items():
            v = self.av[i]
            frm = self.aui[i]["cur"] or v["note"] * 100.0
            v["note"], v["cents"] = int(note), 0
            via = self.amb_steps_via(frm, note * 100.0) if ch["path"] == 4 else None
            self.amb_push(i, glide=ch["time"], shape=shape, delay=delays.get(i, 0.0), via=via)
        self.flash(label)

    def amb_chord(self, deg):
        """Glide the sounding drones into a chord on scale degree deg (0..5), each
        voice to the nearest chord tone so the voices lead smoothly."""
        on = [i for i in range(6) if self.av[i]["on"]]
        if not on:
            self.flash("TURN SOME VOICES ON FIRST")
            return
        name, kind, steps = CHORDS[self.achord["type"] % len(CHORDS)]
        sc = M().SCALES[self.scale]
        if kind == "deg":
            pcs = {(self.key + sc[(deg + s) % 7]) % 12 for s in steps}
        else:
            root = (self.key + sc[deg % 7]) % 12
            pcs = {(root + s) % 12 for s in steps}
        cand = [n for n in range(24, 97) if n % 12 in pcs]
        cur = sorted(((self.aui[i]["cur"] or self.av[i]["note"] * 100.0) / 100.0, i) for i in on)
        # the lowest voice takes the root (as a bass would), then each voice, low to high,
        # takes the nearest chord tone above the one below it, preferring tones not used
        # yet so the chord is complete
        best, used, prev = [], set(), 0
        rest = cur
        if self.achord.get("root") and len(cur) > 1:
            root_pc = (self.key + sc[deg % 7]) % 12
            c0 = cur[0][0]
            b = min((n for n in range(24, 97) if n % 12 == root_pc), key=lambda n: abs(n - c0))
            best, used, prev, rest = [b], {root_pc}, b, cur[1:]
        for c, _ in rest:
            opts = [n for n in cand if n > prev] or [cand[-1]]
            n = min(opts, key=lambda n: abs(n - c) + (2.5 if n % 12 in used and len(used) < len(pcs) else 0))
            best.append(n)
            used.add(n % 12)
            prev = n
        moves = {i: n for n, (_, i) in zip(best, cur)}
        roman = ["I", "II", "III", "IV", "V", "VI", "VII"][deg % 7]
        self.amb_glide_all(moves, "%s %s   %s PATH   %ds" % (roman, name.upper(),
                                                            PATHS[self.achord["path"]].upper(), self.achord["time"]))

    def amb_bloom(self, secs=None, swell=True):
        """Unison bloom: every sounding drone jumps to one note (the lowest voice's)
        and fans out to its own pitch along an S-curve, while the filter opens.
        The classic cinema swell."""
        on = [i for i in range(6) if self.av[i]["on"]]
        if len(on) < 2:
            self.flash("TURN ON TWO OR MORE VOICES FIRST")
            return
        secs = float(secs or max(3.0, self.achord["time"] * 3))
        low = min(self.av[i]["note"] for i in on)
        for i in on:
            v = self.av[i]
            if v["base"] is None:
                self.amb_render(i)
            self.eng.post("amb", i, {"tgt": (low - v["base"]) * 100.0, "jump": True})
            self.aui[i]["cur"] = low * 100.0
            self.aui[i]["path"] = None
            self.amb_push(i, glide=secs, shape=2)
        if swell:
            self.amb_swell(min(30.0, secs * 4))
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
        snds = ["Prophet Brass", "Supersaw", "Juno Strings", "Supersaw", "Prophet Brass"]
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
        self.achord.update(type=0, path=2, time=1.2, stagger=0, order=0, root=True)
        self.aprog.update(steps=[0, 4, 5, 3, 4, None, None, None], time=5, run=False, i=0, next=0.0)
        self.amb_bloom(secs=3.5)
        self.aprog["run"] = True
        self.aprog["next"] = time.perf_counter() + 6.0          # let the bloom finish first
        self.flash("DEEP BLOOM   %s %s   i V VI IV V   R2+A STOPS IT" % (M().NOTE_NAMES[k], self.scale))

    def amb_starter(self):
        """Glide Chords: five bright saw voices sliding through vi, I, V, IV in your
        key, a chord every four seconds, every voice gliding at once."""
        names = [p["name"] for p in self.amb_sounds]

        def ix(n):
            return names.index(n) if n in names else 0
        sc = M().SCALES[self.scale]
        k = self.key
        start = [12 * 3 + k + sc[5], 12 * 4 + k, 12 * 4 + k + sc[2], 12 * 5 + k, 12 * 5 + k + sc[2]]   # vi in five voices
        snds = ["Juno Strings", "Supersaw", "Juno Strings", "Supersaw", "Juno Strings"]
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
        self.achord.update(type=0, path=1, time=0.4, stagger=0, order=0, root=True)
        self.aprog.update(steps=[5, 0, 4, 3, None, None, None, None], time=4, run=False)
        self.amb_prog_toggle()
        self.flash("GLIDE CHORDS   vi  I  V  IV   R2+A STOPS IT")

    def amb_prog_toggle(self):
        p = self.aprog
        if not any(s is not None for s in p["steps"]):
            self.flash("THE PROGRESSION IS EMPTY   SETTINGS > CHORDS")
            return
        p["run"] = not p["run"]
        p["i"], p["next"] = -1, 0.0
        steps = "  ".join(ROMAN[s % 7] for s in p["steps"] if s is not None)
        self.flash(("PROGRESSION  %s   every %gs" % (steps, p["time"])) if p["run"] else "PROGRESSION STOPPED")

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
                self.amb_chord(pr["steps"][pr["i"]])
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
                    ("Chord", CHORDS[ch["type"] % len(CHORDS)][0]), ("Path", PATHS[ch["path"]]),
                    ("Glide time", "%g s" % ch["time"]), ("Stagger", ("%g s apart" % ch["stagger"]) if ch["stagger"] else "Off"),
                    ("Order", ORDERS[ch["order"]]),
                    ("Bass on root", "On" if ch.get("root") else "Off"),
                    ("Play", "R2 + ^ > v < X Y = degree I to VI"), ("Evolve", "tap R2"),
                    ("Bloom", "R2 + B: all voices from one note, fanning out"),
                    ("Progression", ("running   R2+A stops" if self.aprog["run"] else "stopped   R2+A runs it")),
                    ("Chord time", "%g s each" % self.aprog["time"])] + [
                ("Chord %d" % (s + 1), "-" if self.aprog["steps"][s] is None else ROMAN[self.aprog["steps"][s] % 7])
                for s in range(8)]
        if pg == "Melody":
            j = max(0, self.asel - 6) if self.asel >= 6 else getattr(self, "amel_sel", 0)
            self.amel_sel = j
            m = self.amel[j]
            sc = mm.SCALES[self.scale]
            rows = [("Melody", "Melody %s   %s" % ("AB"[j], "running" if m["run"] else "stopped"))]
            for s in range(5):
                d = m["steps"][s]
                rows.append(("Step %d" % (s + 1), "rest" if d is None else
                             "%s  (degree %d)" % (mm.NOTE_NAMES[(self.key + sc[d % 7]) % 12] + str(4 + d // 7), d + 1)))
            rows.append(("Step time", "%g s" % m["time"]))
            rows.append(("Sound", self.amb_patch(6 + j)["name"]))
            rows.append(("Glide", ("%g s" % self.av[6 + j]["glide"]) if self.av[6 + j]["glide"] else "Off"))
            return rows
        if pg == "Scenes":
            rows = [("Starter", "Glide Chords   A loads it"), ("Starter 2", "Deep Bloom   A loads it"),
                    ("Morph time", "%d s" % self.amorph)]
            for s in range(6):
                sc = self.ascenes[s] if s < len(self.ascenes) else None
                rows.append(("Scene %d  %s" % (s + 1, GLYPH[DRONE_BTNS[s]]),
                             ("%d voices   R1+%s recalls" % (sum(1 for d in sc if d.get("on")), GLYPH[DRONE_BTNS[s]]))
                             if sc else "empty   SELECT+%s saves" % GLYPH[DRONE_BTNS[s]]))
            rows.append(("Evolve", "R2 on the main screen"))
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
                v["snd"] = (v["snd"] + d) % len(self.amb_sounds)
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
                v["snd"] = (v["snd"] + d) % len(self.amb_sounds)
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
            elif name == "Glide time":
                ch["time"] = self._amb_step(CHORD_TIMES, ch["time"], d)
            elif name == "Stagger":
                ch["stagger"] = self._amb_step(STAGGERS, ch["stagger"], d)
            elif name == "Order":
                ch["order"] = (ch["order"] + d) % len(ORDERS)
            elif name == "Bass on root":
                ch["root"] = not ch.get("root")
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
        return "%s %s   %d voice%s%s" % (M().NOTE_NAMES[self.key], self.scale, n, "" if n == 1 else "s",
                                         "   FREEZE" if self.afreeze else "")

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
            self._spec_rows = None
        sr = 11025.0                                        # the scope is the output at half rate
        if self._spec_rows is None or len(self._spec_rows) != h:
            f = np.geomspace(self.SPEC_LO, self.SPEC_HI, h)[::-1]
            self._spec_rows = np.clip((f / sr * 2048).astype(int), 1, 1023)
            self._spec_win = np.hanning(2048).astype(np.float32)
        mag = np.abs(np.fft.rfft(buf * self._spec_win))
        db = 20 * np.log10(mag[self._spec_rows] + 1e-4)
        pk = getattr(self, "_spec_pk", 0.0)
        pk = max(db.max(), pk - 0.3)                        # a slowly falling reference, so quiet parts still show
        self._spec_pk = pk
        lv = np.clip((db - (pk - 60)) / 60.0, 0, 1) ** 1.6
        # palette: background, violet, gold, white
        bg = np.array(M().BG, np.float32)
        v = np.array(M().ACCENT, np.float32)
        g = np.array(M().ACCENT2, np.float32)
        wht = np.array((250, 246, 236), np.float32)
        col = np.where(lv[:, None] < 0.5, bg + (v - bg) * (lv[:, None] / 0.5),
                       np.where(lv[:, None] < 0.85, v + (g - v) * ((lv[:, None] - 0.5) / 0.35),
                                g + (wht - g) * ((lv[:, None] - 0.85) / 0.15)))
        surf.scroll(-1, 0)
        px = pygame.surfarray.pixels3d(surf)
        px[w - 1, :, :] = col.astype(np.uint8)
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
                    self.text(c, mm.NOTE_NAMES[(n + self.key) % 12] + str((n + self.key) // 12 - 1), self.f_small,
                              self.mix(mm.BG, mm.DIM, 0.8), (gx0 + 4, int(y) - 15))
            self.text(c, "SPECTROGRAM   L3 GUIDES", self.f_small, self.mix(mm.BG, mm.DIM, 0.8), (gx1 - 4, gy0 + 2),
                      right=True)
            self.draw_amb_tiles(c, now)
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
                self.text(c, mm.NOTE_NAMES[n % 12] + str(n // 12 - 1), self.f_small, col, (gx0 + 2, y - 15))
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
                lab = ROMAN[deg % 7]
                r = self.text(c, lab, self.f_small, mm.ACCENT if s == pr["i"] else mm.DIM, (xx, gy1 - 16))
                xx = r.right + 10
        # scenes: six dots under the graph
        for s in range(6):
            sx = gx0 + s * 14
            full = s < len(self.ascenes) and self.ascenes[s]
            pygame.draw.circle(c, mm.ACCENT if full else self.mix(mm.BG, mm.DIM, 0.5), (sx + 4, gy1 + 2), 3)

    def draw_amb_tiles(self, c, now):
        mm = M()
        L = mm.L
        W = mm.BASE_W
        # voice tiles
        tw, gap = 70, 6
        x0 = (W - (NV * tw + (NV - 1) * gap)) // 2
        ty0, th = L["tiles_y"], L["tile_h"]
        for i in range(NV):
            v = self.av[i]
            u = self.aui[i]
            col = VCOL[i]
            r = pygame.Rect(x0 + i * (tw + gap) + (8 if i >= 6 else 0) - (8 if i < 6 else 0), ty0, tw, th)
            lv = u["lvl"] / max(0.05, v["level"]) if v["level"] else 0.0
            pygame.draw.rect(c, self.mix(mm.PANEL, col, 0.28 * min(1.0, lv)), r, border_radius=10)
            if i == self.asel:
                pygame.draw.rect(c, mm.INK, r, 2, border_radius=10)
            btn = (DRONE_BTNS + MEL_BTNS)[i]
            self.text(c, GLYPH[btn], self.f_med, col if v["on"] else mm.DIM, (r.centerx, r.y + th * 20 // 100),
                      center=True)
            nm = self.amb_patch(i)["name"]
            self.text(c, nm if len(nm) <= 9 else nm[:8] + ".", self.f_small, mm.INK if v["on"] else mm.DIM,
                      (r.centerx, r.y + th * 48 // 100), center=True)
            note = mm.NOTE_NAMES[v["note"] % 12] + str(v["note"] // 12 - 1)
            if v["cents"]:
                note += " %+d" % v["cents"]
            if i >= 6:
                m = self.amel[i - 6]
                note = ("step %d" % (m["i"] + 1)) if m["run"] and m["i"] >= 0 else "steps"
            self.text(c, note, self.f_small, self.mix(mm.DIM, col, 0.5), (r.centerx, r.y + th * 70 // 100),
                      center=True)
            bw = int((tw - 16) * min(1.0, u["lvl"]))
            pygame.draw.rect(c, mm.BG, (r.x + 8, r.bottom - 9, tw - 16, 4), border_radius=2)
            if bw:
                pygame.draw.rect(c, col, (r.x + 8, r.bottom - 9, bw, 4), border_radius=2)
