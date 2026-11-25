"""Brickchord played live, without the app: the engine streaming block by block,
chords built and voiced exactly as the chord buttons do (theory.py), the synth
bass under them and the preset beats. Bricklab web's live page runs this in a
browser worker; notes are rendered elsewhere (a second worker) and handed in
with add_note, so making a new sound never stalls the audio.

A note that isn't rendered yet plays as a pitch-shifted copy of the nearest one
that is (the app's stand-ins), so the first chords sound while the rest arrive."""
import json

import numpy as np

import engine
import synth
import theory

SR = 22050
BUSES = ((0, "Hall", "Ping-Pong", 0.75), (1, "Plate", "Tape", 1.0))
MODES = ["Chord", "Strum Folk", "Strum Pop", "Strum Skank", "Slop", "Harp Up", "Harp Down",       # main.PLAY_MODES
         "Arp 1/8 Up", "Arp 1/16 Up", "Arp 1/16 Up-Down", "Arp 1/8 Down", "Arp 1/16 Random",
         "Repeat 1/4", "Repeat 1/8", "Repeat 1/16"]


BANK = synth.PATCHES + synth.LEAD_PATCHES + synth.DRONE_PATCHES      # Brickchord's 41 sounds
FX = engine.Engine.FX_ORDER + ["Glide"]
FX_DEFAULTS = {"Drive": (0.4, 3), "Lo-fi": (0.4, 3), "Chorus": (0.5, 5), "Flanger": (0.5, 6),        # modes.py
               "Vibrato": (0.3, 0), "Tremolo": (0.5, 1), "Gate": (0.7, 0), "Auto-Pan": (0.6, 4),
               "Wide": (0.6, 3), "Filter LFO": (0.6, 5), "Cloud": (0.5, 2), "Glide": (0.3, 0)}
DELAY_TIMES = [("1/16", 0.25), ("1/8", 0.5), ("1/8 dotted", 0.75), ("1/4", 1.0), ("1/4 dotted", 1.5),   # main.py
               ("1/8 triplet", 1 / 3.0), ("1/4 triplet", 2 / 3.0)]
STICK_SECTORS = {0: "ninth", 1: "maj7", 2: "seventh", 3: "sus2", 4: "sus", 5: "dim", 6: "flip", 7: "aug"}


class Live:
    def __init__(self, sr=SR, block=512):
        self.sr, self.N = sr, block
        e = self.e = engine.Engine(sr, block, synth.reverb_ir(1.2))
        e.post("drums", False, None, synth.kit_arrays())
        e.post("kits", synth.all_kits(synth.SAMPLE_DIR))
        self.bpm, self.beat_i, self.beat_on = 96, 1, False
        self.mode, self.arp_oct = "Chord", 2
        self.sound = 0
        self.params()
        e.post("arp_oct", self.arp_oct)
        e.post("fx", 0.25, 0.0, 0.75, 0.8)
        for b in BUSES:
            e.post("busfx", *b)
        e.post("bass", "Synth", 1.0)
        e.post("bass", None, None, {m: synth.render_bass(m, sr) for m in range(28, 64)})
        self.key, self.scale = 0, "Major"
        self.rack = {k: [False, FX_DEFAULTS[k][0], FX_DEFAULTS[k][1]] for k in FX}
        self.rev, self.dly, self.dly_time, self.volume = 0.25, 0.0, 2, 0.8
        self.space = 0.0
        self.drone_notes = []
        self.prev = []
        self.notes = {}             # midi -> (attack, loop) in the current sound

    def params(self):
        """Tempo, the sound's release and sustain, and the play mode, as the app sends them."""
        p = BANK[self.sound % len(BANK)]
        self.e.post("params", self.bpm, p["r"], p["s"] > 0.001, 0, self.mode, True, 0)

    def set_mode(self, mode):
        self.mode = str(mode)
        self.params()

    def set_bass(self, mode):
        if mode in synth.BASS_MODES:
            self.e.post("bass", mode, None)

    # ---------------- the sound
    def set_sound(self, i):
        self.sound = int(i)
        self.notes = {}
        self.params()
        return self.patch_json()

    def patch_json(self):
        return json.dumps(synth.edited_patch(BANK[self.sound % len(BANK)], None), sort_keys=True)

    def add_note(self, sound, midi, a, la, l, ll):
        """A rendered note arrives (flat float32 stereo buffers and their frame counts)."""
        if int(sound) != self.sound:
            return
        att = np.asarray(a, np.float32).reshape(int(la), 2)
        loop = np.asarray(l, np.float32).reshape(int(ll), 2) if int(ll) else None
        self.notes[int(midi)] = (att, loop)

    def wanted(self, key=None, scale=None):
        """Every note a chord button can ask for in this key, the likely ones first."""
        key = self.key if key is None else key
        scale = self.scale if scale is None else scale
        first, prev = [], []
        for d in range(7):
            pc, iv, _ = theory.build_chord(key, scale, d, {})
            notes, prev = theory.voice(pc, iv, prev, 0)
            for m in notes[1:] + [notes[1] + 12]:
                if m not in first:
                    first.append(m)
        for m in range(36, 67):                                     # drones sit low
            if m % 12 == key % 12 and m not in first:
                first.append(m)
        rest = [m for m in range(36, 100) if m not in first]       # harp and arp reach up here
        return first + rest

    def _standin(self, m):
        have = sorted(self.notes, key=lambda n: abs(n - m))
        if not have:
            return None
        n = have[0]
        a, l = self.notes[n]
        r = 2.0 ** ((m - n) / 12.0)

        def rs(x):
            if x is None:
                return None
            idx = np.arange(0, len(x) - 1, r)
            return np.stack([np.interp(idx, np.arange(len(x)), x[:, c]) for c in (0, 1)], 1).astype(np.float32)
        return rs(a), rs(l)

    # ---------------- playing
    def chord(self, degree, mods_json="{}"):
        mods = json.loads(mods_json) if isinstance(mods_json, str) else dict(mods_json)
        pc, iv, name = theory.build_chord(self.key, self.scale, int(degree), mods)
        return self._play(pc, iv, name, int(degree))

    def chord_exact(self, notes_json):
        """Two or more MIDI keys together (an Orchid, a Gamma, a chord on a keyboard):
        that exact chord, named and voiced like the buttons (main.py midi_tick)."""
        notes = sorted(int(n) for n in json.loads(notes_json))
        pc = notes[0] % 12
        iv = sorted({(n - pc) % 12 for n in notes})
        name = theory.chord_name(pc, iv, False, False, self.key, self.scale)
        return self._play(pc, iv, name, self.midi_degree(notes[0]))

    def midi_degree(self, note):
        sc = theory.SCALES[self.scale]
        pc = (int(note) - self.key) % 12
        return min(range(7), key=lambda i: min((pc - sc[i]) % 12, (sc[i] - pc) % 12))

    def _play(self, pc, iv, name, degree):
        notes, upper = theory.voice(pc, iv, self.prev, 0)
        core = set(notes) | {notes[1] + 12}
        extra = set()                       # what the play mode reaches for (main.py _play_voicing)
        if self.mode.startswith("Harp"):
            pcs = set(m % 12 for m in notes)
            lo = (notes[1] // 12) * 12 - 2
            extra |= {m for m in range(lo, lo + 36) if m % 12 in pcs}
        if self.mode.startswith("Arp"):
            base = sorted(set(notes[1:]))
            extra |= {m + 12 * k for k in range(self.arp_oct) for m in base if m + 12 * k <= 118}
            if base[0] + 12 * self.arp_oct <= 118:
                extra.add(base[0] + 12 * self.arp_oct)
        snd, missing = {}, 0
        for m in core:
            if m in self.notes:
                snd[m] = self.notes[m]
            else:
                s = self._standin(m)
                if s is None:
                    return json.dumps({"name": name, "ready": False})
                snd[m] = s
                missing += 1
        for m in extra - core:              # runs and arpeggios use what is ready; the rest fill in later
            if m in self.notes:
                snd[m] = self.notes[m]
        self.prev = upper
        self.e.post("chord", notes, snd, False)
        return json.dumps({"name": name, "ready": True, "standins": missing,
                           "roman": theory.roman_for(degree, iv)})

    def release(self):
        self.e.post("clear")

    def _snd(self, midis):
        out = {}
        for m in midis:
            out[m] = self.notes.get(m) or self._standin(m)
        return out

    # ---------------- Lead: the buttons are scale notes, one at a time, gliding
    def lead_on(self, degree, up=False, down=False, sharp=False):
        sc = theory.SCALES[self.scale]
        m = 60 + self.key + sc[int(degree) % 7] - (12 if self.key >= 7 else 0)
        m += (12 if up else 0) - (12 if down else 0) + (1 if sharp else 0)
        snd = self._snd([m]).get(m)
        if snd is None:
            return json.dumps({"ready": False})
        g = self.rack["Glide"]
        self.e.post("lead_on", m, snd, g[1] * 0.4 if g[0] else 0.0)
        return json.dumps({"ready": True, "name": theory.NOTE_NAMES[m % 12] + str(m // 12 - 1)})

    def lead_off(self):
        self.e.post("lead_off")

    def lead_mod(self, bend, vib):
        self.e.post("lead_mod", float(bend), float(vib))

    # ---------------- Drone: a held root, fifth and octaves under everything
    def drone(self, degree, third=False):
        sc = theory.SCALES[self.scale]
        d = int(degree) % 7
        root = 36 + (self.key + sc[d]) % 12
        notes = [root, root + 7, root + 12, root + 19]
        if third:
            notes.append(root + 12 + (sc[(d + 2) % 7] - sc[d]) % 12)
        snd = self._snd(notes)
        if any(v is None for v in snd.values()):
            return json.dumps({"ready": False})
        self.e.post("drone", notes, snd)
        self.drone_notes = notes
        return json.dumps({"ready": True, "name": theory.note_name((self.key + sc[d]) % 12, self.key, self.scale)})

    def drone_off(self):
        self.e.post("drone", [], {})
        self.drone_notes = []

    def drone_mod(self, x, y):
        self.e.post("drone_mod", float(x), float(y))

    # ---------------- the sticks and the effects
    def chord_mod(self, x, y):
        """Left stick in Play: which of the eight chord bends it points at (None in the middle)."""
        import math
        if math.hypot(x, y) < 0.55:
            return None
        return STICK_SECTORS[int(round(math.degrees(math.atan2(y, x)) / 45.0)) % 8]

    def right_stick(self, x, y):
        """Left: filter, right: resonance; up: more reverb and delay, down: drier (main.py)."""
        x = 0.0 if abs(x) < 0.12 else float(x)
        y = 0.0 if abs(y) < 0.12 else float(y)
        self.e.post("filter", round(max(0.0, -x), 2), round(max(0.0, x), 2))
        self.space = y
        self.push_fx()

    def push_fx(self):
        y = self.space
        if y >= 0:
            rev = self.rev + y * (1 - self.rev)
            dly = self.dly + y * max(0.0, 0.8 - self.dly)
        else:
            rev, dly = self.rev * (1 + y), self.dly * (1 + y)
        self.e.post("fx", rev, dly, DELAY_TIMES[self.dly_time][1], self.volume)

    def set_space(self, rev, dly, dly_time, volume):
        self.rev, self.dly, self.dly_time, self.volume = float(rev), float(dly), int(dly_time), float(volume)
        self.push_fx()

    def set_fx(self, name, on, amount, rate):
        if name in self.rack:
            self.rack[name] = [bool(on), float(amount), int(rate)]
            self.e.post("rack", {k: tuple(v) for k, v in self.rack.items() if k != "Glide"})

    def set_key(self, key, scale):
        self.key, self.scale = int(key) % 12, scale if scale in theory.SCALES else "Major"
        self.prev = []

    def beat(self, on, i=None, bpm=None):
        if i is not None:
            self.beat_i = int(i) % len(synth.BEATS)
        if bpm:
            self.bpm = int(bpm)
            self.params()
        self.beat_on = bool(on) and self.beat_i > 0
        self.e.post("drums", self.beat_on, synth.BEATS[self.beat_i][1])

    def block(self):
        """One block of audio, interleaved L R L R, float32."""
        return np.ascontiguousarray(self.e.process(), np.float32).ravel()

    def names(self):
        return json.dumps({"sounds": [p["name"] for p in BANK], "groups": [len(synth.PATCHES), len(synth.LEAD_PATCHES), len(synth.DRONE_PATCHES)],
                           "fx": FX, "fx_defaults": FX_DEFAULTS, "rates": [r[0] for r in engine.Engine.RATES],
                           "clouds": [c[0] for c in engine.Engine.CLOUD_TEX], "delay_times": [d[0] for d in DELAY_TIMES],
                           "modes": MODES, "bass": list(synth.BASS_MODES),
                           "beats": [b[0] for b in synth.BEATS],
                           "chords": [[theory.build_chord(self.key, self.scale, d, {})[2] for d in range(7)]]})


def render_note(midi, pj):
    """For the render worker: (attack flat, attack frames, loop flat, loop frames)."""
    a, l = synth.render_note(int(midi), json.loads(pj), arrays=True)
    a = np.ascontiguousarray(a, np.float32)
    lf = np.ascontiguousarray(l, np.float32) if l is not None else np.zeros((0, 2), np.float32)
    return a.ravel(), len(a), lf.ravel(), len(lf)
