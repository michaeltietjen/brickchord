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
        self.prev = []
        self.notes = {}             # midi -> (attack, loop) in the current sound

    def params(self):
        """Tempo, the sound's release and sustain, and the play mode, as the app sends them."""
        p = synth.PATCHES[self.sound % len(synth.PATCHES)]
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
        return json.dumps(synth.edited_patch(synth.PATCHES[self.sound % len(synth.PATCHES)], None), sort_keys=True)

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
                           "roman": theory.roman_for(int(degree), iv)})

    def release(self):
        self.e.post("clear")

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
        return json.dumps({"sounds": [p["name"] for p in synth.PATCHES],
                           "modes": MODES, "bass": list(synth.BASS_MODES),
                           "beats": [b[0] for b in synth.BEATS],
                           "chords": [[theory.build_chord(self.key, self.scale, d, {})[2] for d in range(7)]]})


def render_note(midi, pj):
    """For the render worker: (attack flat, attack frames, loop flat, loop frames)."""
    a, l = synth.render_note(int(midi), json.loads(pj), arrays=True)
    a = np.ascontiguousarray(a, np.float32)
    lf = np.ascontiguousarray(l, np.float32) if l is not None else np.zeros((0, 2), np.float32)
    return a.ravel(), len(a), lf.ravel(), len(lf)
