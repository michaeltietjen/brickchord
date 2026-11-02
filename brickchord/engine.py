"""Brickchord audio engine.

One continuous stereo stream, mixed in NumPy block by block.
Everything that makes sound (chords, strums, arps, harp sweeps, drums)
is scheduled in *sample time* on one shared clock, so timing is exact
and independent of how fast the screen redraws. Reverb (partitioned FFT
convolution) and a tempo-synced ping-pong delay run on the whole mix.

The UI thread only posts commands; the audio thread owns all state.
"""
import collections
import ctypes
import glob
import heapq
import math
import os
import random
import threading
import time
import traceback

import numpy as np

DRUM_GAIN = {"kick": 0.9, "snare": 0.75, "hat": 0.7, "ohat": 0.7, "clap": 0.8, "rim": 0.6, "tom": 0.8, "shk": 0.7}
REPEAT_STEPS = {"Repeat 1/4": 4, "Repeat 1/8": 2, "Repeat 1/16": 1}
DRUM_PAN = {"hat": 0.15, "ohat": 0.15, "shk": -0.25, "rim": -0.15, "tom": 0.2}
LOOP_TRACKS = 6
CAP_TAGS = ("held", "strum", "arp", "harp", "drone", "bass")    # live notes the looper records
MAX_VOICES = 56      # hard cap on sounding voices (keeps the mixer inside its time budget)

STRUM_PATTERNS = {"Strum Folk": "D.DU.UDU", "Strum Pop": "D.D.UDUd", "Strum Skank": ".D.D.D.D"}


class _V:
    __slots__ = ("a", "l", "pos", "start", "gain", "lg", "rg", "rel_at", "rel_len", "tag", "midi",
                 "srev", "sdly", "done", "trk", "rec")


class _Chain:
    """One effects chain: the rack (drive, chorus, ...) and the sweepable filter.
    The live synth has one and every looper track has its own."""
    def __init__(self, L, nfft, flat):
        self.rack = {}
        self.was = set()
        self.mod_hist = np.zeros((1200, 2), np.float32)
        self.flt_hist = np.zeros((L - 1, 2), np.float32)
        self.flt_user = (0.0, 0.0)
        self.flt_t = (0.0, 0.0)
        self.flt_cur = (0.0, 0.0)
        self.flt_S = flat


class _Track:
    def __init__(self, chain):
        self.ev = []             # [pos16, kind, ident, gain, pan, dur16, rel_s, skip]
        self.by = {}             # step -> events starting in it
        self.snd = {}            # midi -> (attack, loop) for kind "n"
        self.mute = False
        self.vol, self.pan, self.rs, self.ds = 0.85, 0.0, 0.25, 0.0
        self.ch = chain
        self.idle = 99


class Engine:
    def __init__(self, sr=22050, block=512, ir=None):
        self.sr = sr
        self.N = block
        self.t = 0
        self.cmds = collections.deque()
        self.voices = []
        self.events = []          # heap of (abs_sample, seq, fn, args)
        self.seq = 0
        # clock (always running; patterns and drums share it)
        self.bpm = 96.0
        self.step16 = 0
        self.next16 = 0.0
        self.drums_on = False
        self.drum_pat = None
        self.kit = {}
        # chord / pattern state
        self.mode = "Chord"
        self.chord = None         # dict: notes(list), snd(dict midi->(a,l)), ...
        self.chord_t = -10 ** 9
        self.pat_i = 0
        self.pat_dir = 1
        # bass: its own synth voice on the dry bus (no filter/reverb = stays punchy)
        self.bass_mode = "Synth"
        self.bass_gain = 1.0
        self.bass_bank = {}       # midi -> (a, None), rendered by the UI side
        self.bass_root = None
        self.arp_oct = 1
        self.leads = []            # mono lead voice(s): the playing one + any fading out
        self.lead_bend = 0.0
        self.lead_vib = 0.0
        self.vib_ph = 0.0
        self.drone = None          # {"notes": [...], "snd": {...}, "restrike": bool}
        # looper: tracks of recorded playing, each through its own effects
        self.lp_len = 32
        self.lp_tracks = []
        self.lp_on = False
        self.lp_i = 0              # absolute index of the next loop step
        self.lp_cur = -1           # absolute index of the last processed loop step
        self.lp_step_at = 0        # sample time of that step
        self.lp_rec = None         # armed / recording track
        self.lp_state = None       # None | "armed" | "rec"
        self.lp_rec_start = 0.0
        self.lp_rec_end = 0.0
        self.lp_open = []          # recorded voices whose length isn't known yet
        self.lp_lead = None        # open lead note event while recording
        self.lp_ver = 0            # bumps on every change (UI redraw / save)
        self.lp_undo = None        # [track, events, sounds] from before the last pass / clear
        self._nocap = False
        self.rack_beat = 0.0
        self.rel_len = int(0.4 * sr)
        self.sustains = True
        self.spread = 0
        self.quantize = True
        # fx
        self.rev = 0.25
        self.rev_t = 0.25
        self.dly = 0.0
        self.dly_t = 0.0
        self.dly_beats = 0.75
        self.master = 0.8
        self.master_t = 0.8
        self.dbuf_len = int(sr * 4.0)
        self.dbuf = np.zeros((self.dbuf_len, 2), np.float32)
        self.dw = 0
        self.dly_type = "Ping-Pong"
        L = 63
        self.tape_hist = np.zeros((L - 1, 2), np.float32)
        self.tape_S = {}
        self._setup_reverb(ir)
        self._setup_filter()
        self.lp_tracks = [_Track(self._chain()) for _ in range(LOOP_TRACKS)]
        # monitoring
        self.active = frozenset()
        self.load = 0.0
        self.underruns = 0
        self.sink = None
        self.running = False

    # ------------------------------------------------------------ reverb
    def _setup_reverb(self, ir):
        N = self.N
        if ir is None:
            ir = np.zeros((N, 2), np.float32)
        P = int(math.ceil(len(ir) / N))
        pad = np.zeros((P * N, 2), np.float32)
        pad[:len(ir)] = ir
        parts = pad.reshape(P, N, 2)
        self.H = np.fft.rfft(parts, 2 * N, axis=1).astype(np.complex64)      # (P, N+1, 2)
        self.FDL = np.zeros_like(self.H)
        self.rprev = np.zeros((N, 2), np.float32)

    # ------------------------------------------------------------ live filter
    # Notes are pre-rendered, so a filter you can sweep while playing has to run on
    # the output. It is a linear-phase FIR applied with one FFT per block (cheap in
    # NumPy), redesigned when the stick moves and crossfaded so sweeps are smooth.
    FLT_L = 511                     # taps; constant 255-sample (11 ms) delay

    def _setup_filter(self):
        L, N = self.FLT_L, self.N
        self.flt_nfft = 1 << int(math.ceil(math.log2(N + L - 1)))
        self.drum_hist = np.zeros(((L - 1) // 2, 2), np.float32)   # keeps dry drums in time with the filtered synth
        self.flt_flat = self._flt_design(0.0, 0.0)
        self.live = self._chain()

    def _chain(self):
        return _Chain(self.FLT_L, self.flt_nfft, self.flt_flat)

    def _flt_design(self, f, r):
        L, sr = self.FLT_L, self.sr
        M = 2048
        fr = np.fft.rfftfreq(M, 1.0 / sr)
        if f <= 0 and r <= 0:
            H = np.ones_like(fr)
        else:
            if r > f:       # resonance side: a resonant peak that sweeps down as you push
                fc = 5000.0 * (800.0 / 5000.0) ** r
                q = 0.9 + 9.0 * r
            else:           # filter side: low-pass closes as you push
                fc = 14000.0 * (110.0 / 14000.0) ** f
                q = 0.75 + 0.6 * f
            w = fr / fc
            H = 1.0 / np.sqrt((1 - w * w) ** 2 + (w / q) ** 2)
            H /= max(1.0, H.max()) ** 0.65          # tame the peak so it doesn't jump in volume
        h = np.fft.irfft(H, M)
        h = np.roll(h, (L - 1) // 2)[:L] * np.hanning(L)
        return np.fft.rfft(h, self.flt_nfft).astype(np.complex64)

    def c_filter(self, f, r):
        ch = self.live
        ch.flt_user = (max(0.0, min(1.0, f)), max(0.0, min(1.0, r)))
        ch.flt_t = (round(ch.flt_user[0], 2), round(ch.flt_user[1], 2))

    # ------------------------------------------------------------ effects rack
    # Stackable effects on the synth bus (drums and bass stay dry). Each is
    # (on, amount 0..1, rate index into RATES). Synced to the tempo.
    RATES = [("1/16", 0.25), ("1/8", 0.5), ("1/8.", 0.75), ("1/4", 1.0), ("1/2", 2.0),
             ("1 bar", 4.0), ("2 bars", 8.0), ("4 bars", 16.0)]
    FX_ORDER = ["Drive", "Lo-fi", "Chorus", "Flanger", "Vibrato", "Tremolo", "Gate",
                "Auto-Pan", "Wide", "Filter LFO"]

    def c_rack(self, rack):
        self.live.rack = {k: tuple(v) for k, v in rack.items()}

    def _lfo_phase(self, N, sr, beats):
        bps = self.bpm / 60.0 / sr
        return ((self.rack_beat + np.arange(N, dtype=np.float64) * bps) / beats) % 1.0

    def _mod_delay(self, ch, x, N, dl_l, dl_r):
        """Read the bus through a delay that moves per sample (chorus,
        flanger, vibrato). dl_*: delay in samples per output sample."""
        H = ch.mod_hist.shape[0]
        frame = np.concatenate([ch.mod_hist, x])
        ch.mod_hist = frame[-H:]
        idx = np.arange(len(frame), dtype=np.float64)
        base = H + np.arange(N, dtype=np.float64)
        y = np.empty_like(x)
        y[:, 0] = np.interp(base - dl_l, idx, frame[:, 0])
        y[:, 1] = np.interp(base - dl_r, idx, frame[:, 1])
        return y

    def _rack(self, ch, x, N, sr):
        rack = ch.rack
        beats_now = self.rack_beat
        if rack:
            R = self.RATES
            on = {k: v for k, v in rack.items() if v[0]}
            if "Drive" in on:
                a = on["Drive"][1]
                k = 1.0 + a * 8.0
                x = np.tanh(x * k) / k * (1 + a * 1.5)          # saturate, keep loudness close
            if "Lo-fi" in on:
                a = on["Lo-fi"][1]
                hold = 1 + int(a * 6)
                if hold > 1:
                    x = np.repeat(x[::hold], hold, axis=0)[:N]
                steps = 2.0 ** (12 - a * 8)
                x = np.round(x * steps) / steps
            mods = [k for k in ("Chorus", "Flanger", "Vibrato") if k in on]
            if mods:
                ms = sr / 1000.0
                acc = np.zeros_like(x)
                wet_total = 0.0
                for k in mods:
                    a, ri = on[k][1], on[k][2]
                    ph = self._lfo_phase(N, sr, R[ri][1])
                    if k == "Chorus":
                        dl = (12 + 4 * a * np.sin(2 * np.pi * ph)) * ms
                        dr = (12 + 4 * a * np.sin(2 * np.pi * (ph + 0.25))) * ms
                        acc += self._mod_delay(ch, x, N, dl, dr) * (0.45 + 0.25 * a)
                    elif k == "Flanger":
                        dl = (0.6 + (2.4 + 3 * a) * (0.5 + 0.5 * np.sin(2 * np.pi * ph))) * ms
                        acc += self._mod_delay(ch, x, N, dl, dl) * (0.5 + 0.4 * a)
                    else:                              # Vibrato: pitch wobble, fully wet
                        dl = (5 + 3 * a * np.sin(2 * np.pi * ph)) * ms
                        acc += self._mod_delay(ch, x, N, dl, dl) - x
                    wet_total += 1
                x = x + acc / max(1.0, wet_total * 0.8)
            else:
                ch.mod_hist = np.concatenate([ch.mod_hist, x])[-ch.mod_hist.shape[0]:]
            if "Tremolo" in on:
                a, ri = on["Tremolo"][1], on["Tremolo"][2]
                ph = self._lfo_phase(N, sr, R[ri][1])
                x = x * (1 - a * 0.5 * (1 - np.cos(2 * np.pi * ph)))[:, None].astype(np.float32)
            if "Gate" in on:
                a, ri = on["Gate"][1], on["Gate"][2]
                ph = self._lfo_phase(N, sr, R[ri][1])
                edge = np.clip((0.55 - ph) * 30, 0, 1) * np.clip(ph * 60, 0, 1)
                x = x * (1 - a + a * edge)[:, None].astype(np.float32)
            if "Auto-Pan" in on:
                a, ri = on["Auto-Pan"][1], on["Auto-Pan"][2]
                ph = self._lfo_phase(N, sr, R[ri][1])
                pan = a * np.sin(2 * np.pi * ph)
                x = x * np.stack([np.sqrt(0.5 - 0.5 * pan), np.sqrt(0.5 + 0.5 * pan)], 1).astype(np.float32) * 1.414
            if "Wide" in on:
                a = on["Wide"][1]
                m = (x[:, 0] + x[:, 1]) * 0.5
                sd = (x[:, 0] - x[:, 1]) * 0.5 * (1 + a * 1.5)
                x = np.stack([m + sd, m - sd], 1).astype(np.float32)
            if "Filter LFO" in on:
                a, ri = on["Filter LFO"][1], on["Filter LFO"][2]
                ph = (beats_now / R[ri][1]) % 1.0
                f_user, r_user = ch.flt_user
                sweep = a * 0.85 * (0.5 - 0.5 * math.cos(2 * np.pi * ph))
                ch.flt_t = (round(max(f_user, sweep), 2), round(max(r_user, 0.35 * a), 2))
            elif "Filter LFO" in ch.was:
                fu = ch.flt_user
                ch.flt_t = (round(fu[0], 2), round(fu[1], 2))
            ch.was = set(on)
        elif ch.was:
            if "Filter LFO" in ch.was:
                ch.flt_t = (round(ch.flt_user[0], 2), round(ch.flt_user[1], 2))
            ch.was = set()
        return x.astype(np.float32)

    def _filter(self, ch, x):
        L, N, nf = self.FLT_L, self.N, self.flt_nfft
        frame = np.concatenate([ch.flt_hist, x])
        ch.flt_hist = frame[-(L - 1):]
        flat = (0.0, 0.0)
        if ch.flt_t == flat and ch.flt_cur == flat:
            # open filter = a plain 255-sample delay (keeps every bus in time), no FFT
            h = (L - 1) // 2
            return frame[h:h + N].astype(np.float32)
        X = np.fft.rfft(frame, nf, axis=0)
        y = np.fft.irfft(X * ch.flt_S[:, None], nf, axis=0)[L - 1:L - 1 + N]
        if ch.flt_t != ch.flt_cur:
            ch.flt_cur = ch.flt_t
            S_new = self.flt_flat if ch.flt_t == flat else self._flt_design(*ch.flt_t)
            y_new = np.fft.irfft(X * S_new[:, None], nf, axis=0)[L - 1:L - 1 + N]
            ch.flt_S = S_new
            ramp = np.linspace(0, 1, N, dtype=np.float32)[:, None]
            y = y * (1 - ramp) + y_new * ramp
        return y.astype(np.float32)

    def c_reverb(self, ir):
        """Switch reverb type. The old tail is dropped (a short fade avoids a click)."""
        self._setup_reverb(ir)

    def _reverb(self, x):
        N = self.N
        buf = np.concatenate([self.rprev, x])
        self.rprev = x
        self.FDL[1:] = self.FDL[:-1]
        self.FDL[0] = np.fft.rfft(buf, 2 * N, axis=0)
        Y = np.einsum("pkc,pkc->kc", self.FDL, self.H)
        return np.fft.irfft(Y, 2 * N, axis=0)[N:].astype(np.float32)

    # ------------------------------------------------------------ commands (UI thread)
    def post(self, name, *args):
        self.cmds.append((name, args))

    # ------------------------------------------------------------ scheduling helpers
    def _at(self, when, fn, *args):
        self.seq += 1
        heapq.heappush(self.events, (int(when), self.seq, fn, args))

    def _voice(self, snd, gain, pan, start, tag, midi=None, gate=None, rel=None, srev=1.0, sdly=1.0):
        a, l = snd
        v = _V()
        v.a, v.l, v.pos, v.start, v.gain = a, l, 0, int(start), gain
        v.lg, v.rg = min(1.0, 1.0 - pan), min(1.0, 1.0 + pan)
        v.rel_len = int(rel if rel is not None else self.rel_len)
        v.rel_at = int(start + gate) if gate else None
        v.tag, v.midi, v.srev, v.sdly, v.done = tag, midi, srev, sdly, False
        v.trk = v.rec = None
        self.voices.append(v)
        if self.lp_state and not self._nocap and tag in CAP_TAGS and midi is not None:
            self._cap_voice(v, "b" if tag == "bass" else "n", midi)
        if len(self.voices) > MAX_VOICES:
            self._steal(start)
        return v

    def _steal(self, at):
        """Keep the voice count bounded. Long release tails and gated strum/harp
        notes used to pile up past the cap (hundreds of voices), which pushed the
        mixer over its time budget and made the sound drop out."""
        fast = int(0.012 * self.sr)
        cands = [v for v in self.voices
                 if not (v.rel_at is not None and v.rel_at <= at and v.rel_len <= fast)]
        excess = len(cands) - MAX_VOICES
        if excess <= 0:
            return
        # first to go: tails already releasing, then oldest non-held, held chord last
        cands.sort(key=lambda v: (v.rel_at is None or v.rel_at > at, v.tag == "held", v.start))
        for v in cands[:excess]:
            v.rel_at, v.rel_len = int(at), fast
            if v.rec is not None:
                self._rec_close(v, at)

    def _release(self, tags, at, length=None):
        for v in self.voices:
            if v.tag in tags and (v.rel_at is None or v.rel_at > at):
                v.rel_at = int(at)
                if length is not None:
                    v.rel_len = int(length)
                if v.rec is not None:
                    self._rec_close(v, at)
        # cancel not-yet-started events for those tags
        self.events = [e for e in self.events if not (e[2] == self._ev_note and e[3][2] in tags)]
        heapq.heapify(self.events)

    def _ev_note(self, when, snd, midi, tag, gain, pan, gate, rel):
        self._voice(snd, gain, pan, when, tag, midi, gate, rel)

    def _note(self, when, midi, tag, gain=0.95, pan=0.0, gate=None, rel=None):
        snd = self.chord["snd"].get(midi) if self.chord else None
        if snd is None:
            return
        if when <= self.t + self.N:
            self._voice(snd, gain, pan, max(when, self.t), tag, midi, gate, rel)
        else:
            self._at(when, self._ev_note, snd, midi, tag, gain, pan, gate, rel)

    # ------------------------------------------------------------ command handlers (audio thread)
    def c_bass(self, mode=None, level=None, bank=None):
        if bank:
            self.bass_bank.update(bank)
        if level is not None:
            self.bass_gain = float(level)
        if mode is not None and mode != self.bass_mode:
            self.bass_mode = mode
            self._release(("bass",), self.t, int(0.03 * self.sr))

    def c_arp_oct(self, n):
        self.arp_oct = max(1, min(4, int(n)))
        if self.chord:
            self.chord["arp"] = self._arp_notes(self.chord["notes"], self.chord["snd"])

    def _arp_notes(self, notes, snd):
        base = sorted(set(notes[1:]))
        out = [m + 12 * k for k in range(self.arp_oct) for m in base] + [base[0] + 12 * self.arp_oct]
        out = [m for m in out if m in snd]
        return out or base

    def _bass(self, at, midi, gain=1.0, gate=None):
        snd = self.bass_bank.get(midi)
        if snd is None:
            return
        g = 0.75 * self.bass_gain * gain
        rel = int(0.05 * self.sr)
        if at <= self.t + self.N:
            self._voice(snd, g, 0.0, max(at, self.t), "bass", midi, gate, rel, srev=0, sdly=0)
        else:
            self._at(at, self._ev_bass, snd, midi, g, gate, rel)

    def _ev_bass(self, at, snd, midi, g, gate, rel):
        self._voice(snd, g, 0.0, at, "bass", midi, gate, rel, srev=0, sdly=0)

    def _bass_start(self, t, notes, revoice):
        """Called on every chord: the bass modes that hold a note start it here;
        the rhythmic ones are played by the clock (see _bass_step)."""
        root = notes[0] - 12                     # an octave under the patch's bass note
        while root < 28:
            root += 12
        changed = root != self.bass_root
        self.bass_root = root
        mode = self.bass_mode
        if mode in ("Synth", "Sub + Patch"):
            if changed or not revoice:
                self._release(("bass",), t, int(0.02 * self.sr))
                self._bass(t, root, 0.8 if mode == "Sub + Patch" else 1.0)
        elif mode in ("Pulse", "Octaves", "Walk"):
            if not revoice or changed:
                self._release(("bass",), t, int(0.02 * self.sr))
                self.bass_i = 0
                if not (self.quantize and self.drums_on):
                    self._bass_step(t, first=True)
                    self.bass_t0 = t

    def _bass_step(self, at, first=False):
        mode = self.bass_mode
        if self.bass_root is None:
            return
        r = self.bass_root
        i = getattr(self, "bass_i", 0)
        if mode == "Pulse":
            m = r
        elif mode == "Octaves":
            m = r if i % 2 == 0 else r + 12
        else:                                    # Walk: root, root, fifth, octave
            m = r + (0, 0, 7, 12)[i % 4]
        self.bass_i = i + 1
        step = 60.0 / self.bpm / 2 * self.sr
        self._release(("bass",), at, int(0.015 * self.sr))
        self._bass(at, m, 1.0 if i % 2 == 0 else 0.8, int(step * 0.8))

    # ------------------------------------------------------------ repeat
    def _repeat(self, at, k):
        if not self.chord:
            return
        step = 60.0 / self.bpm / 4 * self.sr * k
        self._release(("strum",), at, int(0.01 * self.sr))
        notes = self.chord["notes"][1:]
        for i, m in enumerate(notes):
            pan = (i / max(1, len(notes) - 1) - 0.5) * 0.5
            self._note(at, m, "strum", 0.85, pan, int(step * 0.55), int(0.04 * self.sr))

    # ------------------------------------------------------------ drum pads
    def c_hit(self, part, gain=1.0):
        if part in self.kit:
            g, pan = DRUM_GAIN.get(part, 0.75) * gain, DRUM_PAN.get(part, 0.0)
            self._voice(self.kit[part], g, pan, self.t, "drum", srev=0, sdly=0, rel=int(0.02 * self.sr))
            if self.lp_state:
                self._cap(self.t, "d", part, g, pan, None, 0.02)

    # ------------------------------------------------------------ drone layer
    def c_drone(self, notes, snd):
        """Sustained notes on their own layer: they keep going while you play
        chords or lead on top. Sounds that don't sustain are re-struck."""
        self._release(("drone",), self.t, int(0.8 * self.sr))
        if not notes:
            self.drone = None
            return
        restrike = any(snd.get(m) is not None and snd[m][1] is None for m in notes)
        self.drone = {"notes": list(notes), "snd": snd, "restrike": restrike}
        self._drone_strike(self.t)

    def _drone_strike(self, at):
        d = self.drone
        if d.get("restrike"):
            self._release(("drone",), at, int(0.3 * self.sr))
        for i, m in enumerate(d["notes"]):
            e = d["snd"].get(m)
            if e is None:
                continue
            pan = (i / max(1, len(d["notes"]) - 1) - 0.5) * 0.8
            self._voice(e, 0.7, pan, at, "drone", m, None, int(1.2 * self.sr))

    # ------------------------------------------------------------ lead voice
    class _Lead:
        pass

    def c_lead_on(self, midi, snd, glide=0.0):
        if self.lp_state and not self._nocap:
            self._lead_cap_end(self.t)
            self.lp_lead = self._cap(self.t, "n", midi, 0.95, 0.0, None, 0.3, snd)
        cur = self.leads[-1] if self.leads and not self.leads[-1].rel else None
        if cur is not None and glide > 0.005:
            cur.target, cur.glide = midi, glide        # legato slide to the new note
            return
        for v in self.leads:                           # quick fade of the old note
            if not v.rel:
                v.rel, v.rel_n = True, int(0.02 * self.sr)
        if snd is None:
            return
        v = self._Lead()
        v.a, v.l = snd
        v.base = v.target = midi
        v.ratio = 1.0
        v.glide = glide
        v.pos = 0.0
        v.env = 1.0
        v.rel, v.rel_n = False, 0
        self.leads.append(v)
        self.leads = self.leads[-3:]

    def c_lead_off(self):
        self._lead_cap_end(self.t)
        for v in self.leads:
            if not v.rel:
                v.rel, v.rel_n = True, max(64, int(min(self.rel_len, 0.6 * self.sr)))

    def c_lead_mod(self, bend, vib):
        self.lead_bend, self.lead_vib = float(bend), float(vib)

    def _lead_fetch(self, v, idx):
        a, l = v.a, v.l
        na = len(a)
        out = np.zeros((len(idx), 2), np.float32)
        m = idx < na
        out[m] = a[idx[m]]
        if l is not None:
            mm = ~m
            out[mm] = l[(idx[mm] - na) % len(l)]
        return out

    def _lead_render(self, mix, N, sr):
        i = np.arange(N, dtype=np.float64)
        vib = 1.0
        if self.lead_vib > 0.01:
            ph = self.vib_ph + 2 * np.pi * 5.5 * i / sr
            vib = 2.0 ** (self.lead_vib * 0.6 * np.sin(ph) / 12.0)
        self.vib_ph = (self.vib_ph + 2 * np.pi * 5.5 * N / sr) % (2 * np.pi)
        bend = 2.0 ** (self.lead_bend / 12.0)
        keep = []
        for v in self.leads:
            rt = 2.0 ** ((v.target - v.base) / 12.0)
            if v.glide > 0.005 and abs(v.ratio - rt) > 1e-5:
                c = math.exp(-1.0 / (v.glide * 0.35 * sr))
                r = rt + (v.ratio - rt) * c ** (i + 1)
            else:
                r = np.full(N, rt)
            v.ratio = float(r[-1])
            r = r * vib * bend
            pos = v.pos + np.concatenate(([0.0], np.cumsum(r[:-1])))
            v.pos = float(pos[-1] + r[-1])
            i0 = pos.astype(np.int64)
            fr = (pos - i0).astype(np.float32)[:, None]
            seg = self._lead_fetch(v, i0) * (1 - fr) + self._lead_fetch(v, i0 + 1) * fr
            if v.rel:
                env = v.env - np.arange(1, N + 1, dtype=np.float32) / max(1, v.rel_n)
                env = np.clip(env, 0, 1)
                v.env = float(env[-1])
                seg *= (env * env)[:, None]
            seg *= 0.95
            mix += seg
            if v.l is None and v.pos >= len(v.a):
                continue
            if v.rel and v.env <= 0.0:
                continue
            keep.append(v)
        self.leads = keep

    # ------------------------------------------------------------ looper
    # Tracks record what you play (the notes the engine actually sounds, so
    # strums, arps and repeats come back exactly), not audio. Playback goes
    # through each track's own effects chain, so you can change a track's
    # effects, level, pan and sound after recording.
    def _step_len(self):
        return 60.0 / self.bpm / 4 * self.sr

    def _lp_abspos(self, T):
        return self.lp_cur + (T - self.lp_step_at) / self._step_len()

    def _lp_has(self):
        return any(tr.ev for tr in self.lp_tracks)

    def _lp_begin(self, T):
        """First note after arming: start the loop if it isn't running (on the
        bar line when the beat is on), then record exactly one loop's length."""
        step = self._step_len()
        if not self.lp_on:
            self.lp_step_at = int(self.next16 - step)
            last = self.step16 - 1                 # the clock step that just went by
            if self.drums_on:
                self.lp_cur = last % 16
            else:
                self.lp_cur = -1 if T >= self.next16 - 0.5 else 0
            self.lp_i = self.lp_cur + 1
            self.lp_on = True
        tr = self.lp_tracks[self.lp_rec]
        self.lp_undo = [self.lp_rec, list(tr.ev), dict(tr.snd)]
        self.lp_rec_start = self._lp_abspos(T)
        self.lp_rec_end = self.lp_rec_start + self.lp_len
        self.lp_state = "rec"
        self.lp_ver += 1

    def _cap(self, T, kind, ident, gain, pan, dur, rel, snd=None):
        k = self.lp_rec
        if k is None or not self.lp_state:
            return None
        if self.lp_state == "armed":
            self._lp_begin(T)
        ap = self._lp_abspos(T)
        if ap >= self.lp_rec_end or ap < self.lp_rec_start - 0.5:
            return None
        L = self.lp_len
        pos = ap % L
        tr = self.lp_tracks[k]
        skip = int(math.floor(ap)) > self.lp_cur     # its step hasn't played yet this pass
        ev = [round(pos, 4), kind, ident, round(float(gain), 3), round(float(pan), 3),
              None if dur is None else min(float(L), dur), round(float(rel), 3), skip]
        tr.ev.append(ev)
        tr.by.setdefault(int(pos) % L, []).append(ev)
        if kind == "n" and snd is not None and ident not in tr.snd:
            tr.snd[ident] = snd
        self.lp_ver += 1
        return ev

    def _cap_voice(self, v, kind, midi):
        step = self._step_len()
        dur = (v.rel_at - v.start) / step if v.rel_at is not None else None
        ev = self._cap(v.start, kind, midi, v.gain, v.rg - v.lg, dur, v.rel_len / self.sr,
                       (v.a, v.l) if kind == "n" else None)
        if ev is not None:
            v.rec = ev
            if dur is None:
                self.lp_open.append(v)

    def _rec_close(self, v, at):
        ev, v.rec = v.rec, None
        d = max(0.05, (at - v.start) / self._step_len())
        if ev[5] is None or d < ev[5]:
            ev[5] = round(min(float(self.lp_len), d), 3)

    def _lead_cap_end(self, at):
        ev, self.lp_lead = self.lp_lead, None
        if ev is not None and ev[5] is None:
            st = ev[0]
            now = self._lp_abspos(at) % self.lp_len
            ev[5] = round(max(0.1, (now - st) % self.lp_len), 3)

    def _lp_rec_stop(self, at):
        for v in self.lp_open:
            if v.rec is not None and v.l is not None:
                self._rec_close(v, at)
            v.rec = None
        self.lp_open = []
        self._lead_cap_end(at)
        self.lp_rec = None
        self.lp_state = None
        self.lp_ver += 1

    def c_lp(self, op, *a):
        if op == "len":
            if not self._lp_has():
                self.lp_len = int(a[0])
        elif op == "arm":
            k = a[0]
            if self.lp_state:
                self._lp_rec_stop(self.t)
            if k is not None:
                self.lp_rec, self.lp_state = int(k), "armed"
                if self._lp_has() and not self.lp_on:
                    self.c_lp("play", True)
            self.lp_ver += 1
        elif op == "clear":
            k = a[0]
            if self.lp_rec == k and self.lp_state:
                self._lp_rec_stop(self.t)
            tr = self.lp_tracks[k]
            if tr.ev:
                self.lp_undo = [k, list(tr.ev), dict(tr.snd)]
            tr.ev, tr.by, tr.snd = [], {}, {}
            self._release_track(k)
            if not self._lp_has() and not self.lp_state:
                self.lp_on = False
            self.lp_ver += 1
        elif op == "play":
            on = bool(a[0])
            if on and not self.lp_on and (self._lp_has() or self.lp_state):
                step = self._step_len()
                self.lp_step_at = int(self.next16 - step)
                # start on the next bar line when the beat is on, else the next step
                self.lp_cur = -((16 - self.step16 % 16) % 16) - 1 if self.drums_on else -1
                self.lp_i = self.lp_cur + 1
                self.lp_on = True
            elif not on and self.lp_on:
                if self.lp_state:
                    self._lp_rec_stop(self.t)
                self.lp_on = False
                for k in range(len(self.lp_tracks)):
                    self._release_track(k)
            self.lp_ver += 1
        elif op == "mix":
            k, d = a[0], a[1]
            tr = self.lp_tracks[k]
            for name in ("vol", "pan", "rs", "ds", "mute"):
                if name in d:
                    setattr(tr, name, d[name])
            if d.get("mute"):
                self._release_track(k, 0.05)
        elif op == "fx":
            k, rack, flt = a[0], a[1], a[2]
            ch = self.lp_tracks[k].ch
            ch.rack = {n: tuple(v) for n, v in rack.items()}
            ch.flt_user = (max(0.0, min(1.0, flt[0])), max(0.0, min(1.0, flt[1])))
            if "Filter LFO" not in ch.was:
                ch.flt_t = (round(ch.flt_user[0], 2), round(ch.flt_user[1], 2))
        elif op == "snd":
            k, snd, replace = a[0], a[1], (a[2] if len(a) > 2 else False)
            tr = self.lp_tracks[k]
            if replace:
                tr.snd = dict(snd)
                self._release_track(k, 0.08)
            else:
                tr.snd.update(snd)
        elif op == "undo":
            if self.lp_state:
                self._lp_rec_stop(self.t)
            if self.lp_undo:
                k, ev, snd = self.lp_undo
                tr = self.lp_tracks[k]
                self.lp_undo = [k, list(tr.ev), dict(tr.snd)]      # undo again = redo
                tr.ev, tr.snd = ev, snd
                self._lp_index(tr)
                self._release_track(k)
                if self._lp_has() and not self.lp_on:
                    self.c_lp("play", True)
                self.lp_ver += 1
        elif op == "load":
            k, evs = a[0], a[1]
            tr = self.lp_tracks[k]
            tr.ev, tr.by = [], {}
            L = self.lp_len
            for e in evs:
                ev = list(e[:7]) + [False]
                ev[0] = float(ev[0]) % L
                tr.ev.append(ev)
                tr.by.setdefault(int(ev[0]) % L, []).append(ev)
            self.lp_ver += 1

    def _lp_index(self, tr):
        L = self.lp_len
        tr.by = {}
        for ev in tr.ev:
            ev[7] = False
            tr.by.setdefault(int(ev[0]) % L, []).append(ev)

    def _release_track(self, k, fade=0.03):
        at = self.t
        for v in self.voices:
            if v.trk == k and (v.rel_at is None or v.rel_at > at):
                v.rel_at, v.rel_len = at, int(fade * self.sr)

    def _lp_step(self, at):
        if not self.lp_on:
            return
        a = self.lp_i
        self.lp_i += 1
        self.lp_cur = a
        self.lp_step_at = at
        step = self._step_len()
        if self.lp_state == "rec" and a >= self.lp_rec_end:
            self._lp_rec_stop(int(at - (a - self.lp_rec_end) * step))
        if a < 0:
            return
        L = self.lp_len
        li = a % L
        self._nocap = True
        try:
            for k, tr in enumerate(self.lp_tracks):
                evs = tr.by.get(li)
                if not evs:
                    continue
                for ev in evs:
                    if ev[7]:
                        ev[7] = False          # recorded just now and still sounding live
                        continue
                    if not tr.mute:
                        self._lp_play(k, tr, ev, at + (ev[0] - li) * step, step)
        finally:
            self._nocap = False

    def _lp_play(self, k, tr, ev, start, step):
        pos, kind, ident, gain, pan, dur, rel = ev[:7]
        if kind == "n":
            snd = tr.snd.get(ident)
        elif kind == "b":
            snd = self.bass_bank.get(ident)
        else:
            snd = self.kit.get(ident)
        if snd is None:
            return
        if dur is None:
            gate = int(self.lp_len * step) if snd[1] is not None else None
        else:
            gate = max(64, int(dur * step))
        v = self._voice(snd, gain, max(-1.0, min(1.0, pan)), int(start), "loop", ident if kind != "d" else None,
                        gate, int(rel * self.sr), srev=0, sdly=0)
        v.trk = k

    def c_params(self, bpm=None, rel=None, sustains=None, spread=None, mode=None, quantize=None):
        if quantize is not None:
            self.quantize = quantize
        if bpm:
            self.bpm = float(bpm)
        if rel is not None:
            self.rel_len = int(rel * self.sr)
        if sustains is not None:
            self.sustains = sustains
        if spread is not None:
            self.spread = spread
        if mode is not None:
            if mode != self.mode:
                self.c_clear()
            self.mode = mode

    def c_delay_type(self, name):
        self.dly_type = name

    def _lp_fir(self, key, lo, hi):
        """Short band-limiting FIR used on delay repeats (Tape / Dub)."""
        S = self.tape_S.get(key)
        if S is None:
            L, M = 63, 1024
            fr = np.fft.rfftfreq(M, 1.0 / self.sr)
            H = 1.0 / np.sqrt(1 + (fr / hi) ** 4)
            if lo:
                H *= 1.0 / np.sqrt(1 + (lo / np.maximum(fr, 1.0)) ** 4)
            h = np.roll(np.fft.irfft(H, M), (L - 1) // 2)[:L] * np.hanning(L)
            S = np.fft.rfft(h, 2048).astype(np.complex64)
            self.tape_S[key] = S
        return S

    def _darken(self, y, key, lo, hi):
        L = 63
        frame = np.concatenate([self.tape_hist, y])
        self.tape_hist = frame[-(L - 1):]
        Y = np.fft.rfft(frame, 2048, axis=0)
        return np.fft.irfft(Y * self._lp_fir(key, lo, hi)[:, None], 2048, axis=0)[L - 1:L - 1 + len(y)].astype(np.float32)

    def _delay(self, x, N, sr):
        """Read the delay line, write input + feedback. Returns the wet signal."""
        typ = self.dly_type
        size = self.dbuf_len
        idx = np.arange(N)
        widx = (self.dw + idx) % size
        beat = 60.0 / self.bpm * sr

        def tap(samples):
            dd = int(max(N, min(samples, size - N)))
            return self.dbuf[(self.dw - dd + idx) % size]

        amt = float(self.dly_t)
        if typ == "Slapback":
            y = tap(0.105 * sr)
            fb_sig = y * 0.12
            wet = y * 1.1
        elif typ == "Multi-Tap":
            d = beat * self.dly_beats
            a, b, c = tap(d), tap(d * 1.5), tap(d * 2)
            wet = a * np.array([0.9, 0.35], np.float32) + b * np.array([0.35, 0.9], np.float32) + c * 0.55
            fb_sig = c * (0.15 + 0.35 * amt)
            y = wet
        else:
            y = tap(beat * self.dly_beats)
            if typ == "Straight":
                fb_sig = y * (0.3 + 0.45 * amt)
            elif typ == "Tape":
                fb_sig = np.tanh(self._darken(y, "tape", 90.0, 2600.0) * 1.6) / 1.6 * (0.35 + 0.47 * amt)
            elif typ == "Dub":
                fb_sig = np.tanh(self._darken(y, "dub", 220.0, 1500.0) * 2.0) / 2.0 * (0.55 + 0.33 * amt)
            else:                                   # Ping-Pong
                fb_sig = y[:, ::-1] * (0.3 + 0.45 * amt)
            wet = y
        self.dbuf[widx] = x + fb_sig
        self.dw = (self.dw + N) % size
        return wet

    def c_fx(self, rev, dly, beats, master):
        self.rev_t, self.dly_t, self.dly_beats, self.master_t = rev, dly, beats, master

    def c_drums(self, on, pattern, kit=None):
        if kit:
            self.kit = kit
        self.drum_pat = pattern
        if on and not self.drums_on:
            self.step16 = 0
            self.next16 = float(self.t)
        self.drums_on = on

    def c_chime(self, midis=None):
        """Startup chord, struck with the logo animation: a soft bell/e-piano
        tone, strummed low to high, through the synth's reverb and delay."""
        sr = self.sr
        midis = list(midis or [48, 55, 59, 62, 64, 71])
        n = int(1.8 * sr)
        t = np.arange(n) / sr
        att = np.minimum(1.0, t / 0.004)
        for i, m in enumerate(midis):
            f = 440.0 * 2 ** ((m - 69) / 12.0)
            x = (np.sin(2 * np.pi * f * t) * np.exp(-t * 2.2)
                 + 0.30 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 5.0)
                 + 0.10 * np.sin(2 * np.pi * 3.01 * f * t) * np.exp(-t * 9.0)
                 + 0.05 * np.sin(2 * np.pi * 7.1 * f * t) * np.exp(-t * 30.0))
            x = (x * att * (0.24 if m >= 52 else 0.30)).astype(np.float32)
            pan = 0.0 if len(midis) < 2 else -0.45 + 0.9 * i / (len(midis) - 1)
            self._voice((np.repeat(x[:, None], 2, 1), None), 1.0, pan, self.t + int(i * 0.045 * sr),
                        "chime", srev=1.0, sdly=0.6, rel=int(0.05 * sr))

    def c_click(self):
        if "click" in self.kit:
            self._voice(self.kit["click"], 0.8, 0.0, self.t, "drum", srev=0, sdly=0, rel=int(0.01 * self.sr))

    def c_chord(self, notes, snd, revoice=False):
        mode = self.mode
        q = self.quantize and self.drums_on and not revoice
        t = int(self.next16) if (q and self.next16 >= self.t) else self.t
        prev = self.chord
        self.chord = {"notes": list(notes), "snd": snd, "pat": notes[1:] + [notes[1] + 12]}
        self.chord["arp"] = self._arp_notes(notes, snd)
        xf = int(0.025 * self.sr)
        bm = self.bass_mode
        patch_bass = bm in ("Patch", "Sub + Patch")
        self._bass_start(t, notes, revoice)
        if mode in ("Chord", "Slop"):
            self._release(("held",), t, xf if revoice else None)
            for i, m in enumerate(notes):
                if i == 0 and not patch_bass:
                    continue                     # the synth bass (or nothing) replaces it
                when = t + int(i * self.spread * self.sr / 1000)
                gain = 0.95
                if mode == "Slop" and not revoice:
                    when += int(random.uniform(0, 0.045) * self.sr)
                    gain = random.uniform(0.72, 1.0)
                self._note(when, m, "held", gain)
            return
        # pattern modes keep a bass voice
        new_bass = notes[0]
        old_bass = prev["notes"][0] if (prev and revoice) else None
        if not revoice or new_bass != old_bass:
            self._release(("held",), t, xf if revoice else None)
            if patch_bass:
                self._note(t, new_bass, "held", 0.7)
        if mode.startswith("Harp"):
            run = self._harp_run(notes)
            sr = self.sr
            for i, m in enumerate(run):
                pan = (i / max(1, len(run) - 1)) - 0.5
                self._note(t + int(i * 0.034 * sr), m, "harp", 0.6, pan,
                           int(1.4 * sr) if self.sustains else None)
            return
        if q:
            # let the clock play the first strum / arp note on the next grid step
            if not revoice:
                self.pat_i, self.pat_dir = 0, 1
            self.chord_t = -10 ** 9
            return
        if mode.startswith("Strum"):
            self._strum("d" if revoice else "D", t)
        elif mode.startswith("Repeat"):
            self._repeat(t, REPEAT_STEPS.get(mode, 2))
        else:
            if not revoice:
                self.pat_i, self.pat_dir = 0, 1
                self._arp_step(t)
        self.chord_t = t

    def _harp_run(self, notes):
        pcs = set(m % 12 for m in notes)
        lo = (notes[1] // 12) * 12 - 2
        run = [m for m in range(lo, lo + 36) if m % 12 in pcs and m in self.chord["snd"]]
        return list(reversed(run)) if self.mode == "Harp Down" else run

    def c_clear(self):
        t = self.t
        self._release(("held",), t)
        self._release(("strum",), t, int(0.12 * self.sr))
        self._release(("arp",), t, int(0.06 * self.sr))
        self._release(("bass",), t, int(0.08 * self.sr))
        self.bass_root = None
        self.chord = None

    # ------------------------------------------------------------ patterns
    def _strum(self, ch, at):
        if ch == "." or not self.chord:
            return
        sr = self.sr
        notes = sorted(self.chord["pat"])
        skank = self.mode == "Strum Skank"
        self._release(("strum",), at, int((0.05 if skank else 0.11) * sr))
        if ch in "Dd":
            seq, gap, vol = notes, 0.013, (0.95 if ch == "D" else 0.6)
        else:
            seq, gap, vol = list(reversed(notes))[:4], 0.010, 0.62
        gate = int(0.11 * sr) if skank else (None if not self.sustains else int(60.0 / self.bpm * 2 * sr))
        for i, m in enumerate(seq):
            pan = (i / max(1, len(seq) - 1) - 0.5) * 0.6
            self._note(at + int(i * gap * sr), m, "strum", vol * (1 - 0.04 * i), pan, gate)

    def _arp_step(self, at):
        if not self.chord:
            return
        mode = self.mode
        notes = self.chord.get("arp") or self.chord["pat"]
        div = 2 if "1/8" in mode else 4
        step = 60.0 / self.bpm / div * self.sr
        if "Random" in mode:
            n = random.choice(notes)
        elif "Down" in mode and "Up" not in mode:
            n = notes[-1 - (self.pat_i % len(notes))]
            self.pat_i += 1
        elif "Up-Down" in mode:
            self.pat_i = max(0, min(self.pat_i, len(notes) - 1))
            n = notes[self.pat_i]
            if len(notes) > 1:
                if not 0 <= self.pat_i + self.pat_dir < len(notes):
                    self.pat_dir *= -1
                self.pat_i += self.pat_dir
        else:
            n = notes[self.pat_i % len(notes)]
            self.pat_i += 1
        self._release(("arp",), at, int(0.03 * self.sr))
        self._note(at, n, "arp", 0.85, 0.0, int(step * 0.9), int(min(self.rel_len, step * 0.8)))

    def _on_step(self, s, at):
        if self.drums_on and self.drum_pat:
            sw = self.drum_pat.get("swing", 0.0)
            when = at + (int(sw * 60.0 / self.bpm / 4 * self.sr) if s % 2 else 0)
            for part, pat in self.drum_pat.items():
                if part == "swing" or part not in self.kit:
                    continue
                ch = pat[s % 16]
                if ch == ".":
                    continue
                gain = DRUM_GAIN.get(part, 0.75) * (0.4 if ch == "g" else 1.0)
                pan = DRUM_PAN.get(part, 0.0)
                self._voice(self.kit[part], gain, pan, when, "drum", srev=0, sdly=0, rel=int(0.02 * self.sr))
        self._lp_step(at)
        if self.drone and self.drone.get("restrike") and s % 8 == 0:
            self._drone_strike(at)
        if not self.chord:
            return
        mode = self.mode
        if self.bass_mode in ("Pulse", "Octaves", "Walk") and s % 2 == 0:
            if at - getattr(self, "bass_t0", -10 ** 9) > int(0.09 * self.sr):
                self._bass_step(at)
        fresh = at - self.chord_t < int(0.09 * self.sr)     # just played on press
        if mode.startswith("Strum") and s % 2 == 0 and not fresh:
            pat = STRUM_PATTERNS[mode]
            self._strum(pat[(s // 2) % len(pat)], at)
        elif mode.startswith("Arp") and not fresh:
            if "1/16" in mode or s % 2 == 0:
                self._arp_step(at)
        elif mode.startswith("Repeat") and not fresh:
            k = REPEAT_STEPS.get(mode, 2)
            if s % k == 0:
                self._repeat(at, k)

    # ------------------------------------------------------------ render one block
    def process(self):
        t0 = time.perf_counter()
        N, t, sr = self.N, self.t, self.sr
        while self.cmds:
            name, args = self.cmds.popleft()
            try:
                getattr(self, "c_" + name)(*args)
            except Exception as e:      # never let a bad command kill audio
                print("engine cmd error", name, e, flush=True)
        # clock steps that fall inside this block
        step_len = 60.0 / self.bpm / 4 * sr
        if self.next16 < t:
            self.next16 = float(t)
        while self.next16 < t + N:
            self._on_step(self.step16, int(self.next16))
            self.step16 += 1
            self.next16 += step_len
        while self.events and self.events[0][0] < t + N:
            when, _, fn, args = heapq.heappop(self.events)
            fn(max(when, t), *args) if fn in (self._ev_note, self._ev_bass) else fn(*args)

        mix = np.zeros((N, 2), np.float32)
        dmix = np.zeros((N, 2), np.float32)      # drums: dry, no effects
        tb = {}                                  # looper track buses
        T = np.arange(t, t + N)
        live = []
        for v in self.voices:
            o = v.start - t
            if o >= N:
                live.append(v)
                continue
            o = max(0, o)
            n = N - o
            seg = self._take(v, n)
            if seg is None:
                continue
            g = np.full(n, v.gain, np.float32)
            if v.rel_at is not None and v.rel_at < t + N:
                x = (T[o:] - v.rel_at) / max(1, v.rel_len)
                env = np.clip(1 - x, 0, 1)
                g *= np.where(x < 0, 1.0, env * env)
                if v.rel_at + v.rel_len <= t + N:
                    v.done = True
            seg *= g[:, None]
            seg[:, 0] *= v.lg
            seg[:, 1] *= v.rg
            if v.done and v.rec is not None:
                v.rec = None
            if v.trk is not None:
                b = tb.get(v.trk)
                if b is None:
                    b = tb[v.trk] = np.zeros((N, 2), np.float32)
                b[o:] += seg
            elif v.tag in ("drum", "bass"):
                dmix[o:] += seg
            else:
                mix[o:] += seg
            if not v.done:
                live.append(v)
        self.voices = live
        if self.leads:
            self._lead_render(mix, N, sr)

        # smoothed fx amounts (linear ramp across the block = no zipper noise)
        ramp = np.linspace(0, 1, N, dtype=np.float32)[:, None]
        rv = self.rev + (self.rev_t - self.rev) * ramp
        dv = self.dly + (self.dly_t - self.dly) * ramp
        mv = self.master + (self.master_t - self.master) * ramp
        self.rev, self.dly, self.master = self.rev_t, self.dly_t, self.master_t

        # live synth: its rack, then its filter, then sends to the shared delay/reverb
        x = self._filter(self.live, self._rack(self.live, mix, N, sr))
        out = x.copy()
        rsend = x * rv
        dsend = x * dv
        # looper tracks: each through its own rack and filter, then level, pan, sends
        for k, tr in enumerate(self.lp_tracks):
            b = tb.get(k)
            if b is None:
                if tr.idle > 2:
                    continue
                tr.idle += 1
                b = np.zeros((N, 2), np.float32)
            else:
                tr.idle = 0
            y = self._filter(tr.ch, self._rack(tr.ch, b, N, sr))
            p = tr.pan
            y[:, 0] *= tr.vol * min(1.0, 1.0 - p)
            y[:, 1] *= tr.vol * min(1.0, 1.0 + p)
            out += y
            if tr.rs:
                rsend += y * tr.rs
            if tr.ds:
                dsend += y * tr.ds
        self.rack_beat += N * self.bpm / 60.0 / sr
        # delay (type chosen in Settings), tempo synced except Slapback
        y = self._delay(dsend, N, sr)
        out += y
        out += self._reverb(rsend + y * 0.35) * 1.1
        frame = np.concatenate([self.drum_hist, dmix])
        self.drum_hist = frame[N:]
        out = np.tanh((out + frame[:N]) * mv)

        self.t += N
        self.active = frozenset(v.midi for v in self.voices if v.rel_at is None and v.midi is not None)
        el = time.perf_counter() - t0
        if el > N / sr:
            self.underruns += 1
        self.load = 0.9 * self.load + 0.1 * (el / (N / sr))
        out = out.astype(np.float32)
        self.scope = out[::2, 0]            # for the on-screen oscilloscope
        return out

    def _take(self, v, n):
        a, l = v.a, v.l
        pos = v.pos
        la = len(a)
        out = np.empty((n, 2), np.float32)
        k = 0
        if pos < la:
            k = min(n, la - pos)
            out[:k] = a[pos:pos + k]
        if k < n:
            if l is None:
                if k == 0:
                    v.done = True
                    return None
                out[k:] = 0
                v.done = True
            else:
                ll = len(l)
                start = pos + k - la
                ii = (np.arange(start, start + n - k)) % ll
                out[k:] = l[ii]
        v.pos = pos + n
        return out

    # ------------------------------------------------------------ audio output
    def start(self, prefer="stream"):
        """Open the audio output. Default: stream blocks through pygame.mixer,
        which always uses the system's default output (the speaker / headphones).
        The raw SDL callback is optional because device naming varies by firmware."""
        self.running = True
        order = ["stream", "callback"] if prefer == "stream" else ["callback", "stream"]
        last = None
        for kind in order:
            try:
                (self._start_stream if kind == "stream" else self._start_callback)()
                self.sink = kind
                return
            except Exception as e:
                last = e
                print("audio output %s failed: %s" % (kind, e), flush=True)
        raise RuntimeError("no audio output: %s" % last)

    def _init_sdl_audio(self):
        cands = ["libSDL2-2.0.so.0", "libSDL2.so"]
        try:
            import pygame
            base = os.path.dirname(pygame.__file__)
            cands = sorted(glob.glob(os.path.join(base, "..", "pygame.libs", "libSDL2-2*"))) + cands
        except Exception:
            pass
        for c in [None] + cands:
            try:
                lib = ctypes.CDLL(c)
                if lib.SDL_InitSubSystem(0x10) == 0:
                    return
            except (OSError, AttributeError):
                continue
        raise RuntimeError("could not init SDL audio")

    def _start_callback(self):
        from pygame._sdl2 import audio as A
        self._init_sdl_audio()
        names = A.get_audio_device_names(False)
        print("audio devices:", names, flush=True)

        def cb(dev, mem):
            try:
                mem[:] = self.process().tobytes()
            except Exception as e:
                print("audio callback error", e, flush=True)
                mem[:] = bytes(len(mem))

        self.dev = A.AudioDevice(devicename=names[0] if names else "", iscapture=False, frequency=self.sr,
                                 audioformat=A.AUDIO_F32, numchannels=2, chunksize=self.N,
                                 allowed_changes=0, callback=cb)
        self.dev.pause(0)

    def _start_stream(self):
        import pygame
        pygame.mixer.pre_init(self.sr, -16, 2, self.N)
        pygame.mixer.init(self.sr, -16, 2, self.N)
        print("mixer opened:", pygame.mixer.get_init(), flush=True)
        pygame.mixer.set_num_channels(2)
        self.ch = pygame.mixer.Channel(0)

        def loop():
            first = True
            try:
                os.nice(-5)
            except Exception:
                pass
            while self.running:
                try:
                    if first or self.ch.get_queue() is None:
                        blk = self.process()
                        snd = pygame.mixer.Sound(buffer=(np.clip(blk, -1, 1) * 32767).astype(np.int16).tobytes())
                        if first or not self.ch.get_busy():
                            if not first:
                                self.underruns += 1
                            self.ch.play(snd)      # (re)start the stream if it ever ran dry
                            first = False
                        else:
                            self.ch.queue(snd)
                    else:
                        time.sleep(0.002)
                except Exception as e:             # keep the audio thread alive no matter what
                    print("audio stream error:", repr(e), flush=True)
                    traceback.print_exc()
                    self.voices = []           # drop whatever caused it
                    time.sleep(0.05)

        self.th = threading.Thread(target=loop, daemon=True)
        self.th.start()

    def stop(self):
        self.running = False
        try:
            if self.sink == "callback":
                self.dev.pause(1)
                self.dev.close()
            elif self.sink == "stream":
                self.th.join(0.5)
                import pygame
                pygame.mixer.quit()
        except Exception:
            pass
