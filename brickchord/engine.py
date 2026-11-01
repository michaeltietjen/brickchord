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
DRUM_PAN = {"hat": 0.15, "ohat": 0.15, "shk": -0.25, "rim": -0.15, "tom": 0.2}
MAX_VOICES = 40      # hard cap on sounding voices (keeps the mixer inside its time budget)

STRUM_PATTERNS = {"Strum Folk": "D.DU.UDU", "Strum Pop": "D.D.UDUd", "Strum Skank": ".D.D.D.D"}


class _V:
    __slots__ = ("a", "l", "pos", "start", "gain", "lg", "rg", "rel_at", "rel_len", "tag", "midi",
                 "srev", "sdly", "done")


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
        self.flt_hist = np.zeros((L - 1, 2), np.float32)
        self.drum_hist = np.zeros(((L - 1) // 2, 2), np.float32)   # keeps dry drums in time with the filtered synth
        self.flt_t = (0.0, 0.0)          # target (filter, resonance), each 0..1
        self.flt_cur = None
        self.flt_S = self._flt_design(0.0, 0.0)
        self.flt_win = np.hanning(L).astype(np.float32)

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
        self.flt_t = (round(max(0.0, min(1.0, f)), 2), round(max(0.0, min(1.0, r)), 2))

    def _filter(self, x):
        L, N, nf = self.FLT_L, self.N, self.flt_nfft
        frame = np.concatenate([self.flt_hist, x])
        self.flt_hist = frame[-(L - 1):]
        X = np.fft.rfft(frame, nf, axis=0)
        y = np.fft.irfft(X * self.flt_S[:, None], nf, axis=0)[L - 1:L - 1 + N]
        if self.flt_t != self.flt_cur:
            first = self.flt_cur is None
            self.flt_cur = self.flt_t
            S_new = self._flt_design(*self.flt_t)
            y_new = np.fft.irfft(X * S_new[:, None], nf, axis=0)[L - 1:L - 1 + N]
            self.flt_S = S_new
            if first:
                y = y_new
            else:
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
        self.voices.append(v)
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

    def _release(self, tags, at, length=None):
        for v in self.voices:
            if v.tag in tags and (v.rel_at is None or v.rel_at > at):
                v.rel_at = int(at)
                if length is not None:
                    v.rel_len = int(length)
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

    def c_chime(self):
        """Short two-note startup chime so you know audio is alive."""
        sr = self.sr
        for i, f in enumerate((660.0, 990.0)):
            t = np.arange(int(0.35 * sr)) / sr
            x = (np.sin(2 * np.pi * f * t) * np.exp(-t * 9) * 0.35).astype(np.float32)
            self._voice((np.repeat(x[:, None], 2, 1), None), 1.0, 0.0, self.t + int(i * 0.12 * sr), "drum",
                        srev=0.5, sdly=0, rel=int(0.02 * sr))

    def c_click(self):
        if "click" in self.kit:
            self._voice(self.kit["click"], 0.8, 0.0, self.t, "drum", srev=0, sdly=0, rel=int(0.01 * self.sr))

    def c_chord(self, notes, snd, revoice=False):
        mode = self.mode
        q = self.quantize and self.drums_on and not revoice
        t = int(self.next16) if (q and self.next16 >= self.t) else self.t
        prev = self.chord
        self.chord = {"notes": list(notes), "snd": snd, "pat": notes[1:] + [notes[1] + 12]}
        xf = int(0.025 * self.sr)
        if mode in ("Chord", "Slop"):
            self._release(("held",), t, xf if revoice else None)
            for i, m in enumerate(notes):
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
        notes = self.chord["pat"]
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
        if not self.chord:
            return
        mode = self.mode
        fresh = at - self.chord_t < int(0.09 * self.sr)     # just played on press
        if mode.startswith("Strum") and s % 2 == 0 and not fresh:
            pat = STRUM_PATTERNS[mode]
            self._strum(pat[(s // 2) % len(pat)], at)
        elif mode.startswith("Arp") and not fresh:
            if "1/16" in mode or s % 2 == 0:
                self._arp_step(at)

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
            fn(max(when, t), *args) if fn == self._ev_note else fn(*args)

        mix = np.zeros((N, 2), np.float32)
        dmix = np.zeros((N, 2), np.float32)      # drums: dry, no effects
        rbus = np.zeros((N, 2), np.float32)
        dbus = np.zeros((N, 2), np.float32)
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
            if v.tag == "drum":
                dmix[o:] += seg
                if not v.done:
                    live.append(v)
                continue
            mix[o:] += seg
            if v.srev:
                rbus[o:] += seg * v.srev
            if v.sdly:
                dbus[o:] += seg * v.sdly
            if not v.done:
                live.append(v)
        self.voices = live

        # smoothed fx amounts (linear ramp across the block = no zipper noise)
        ramp = np.linspace(0, 1, N, dtype=np.float32)[:, None]
        rv = self.rev + (self.rev_t - self.rev) * ramp
        dv = self.dly + (self.dly_t - self.dly) * ramp
        mv = self.master + (self.master_t - self.master) * ramp
        self.rev, self.dly, self.master = self.rev_t, self.dly_t, self.master_t

        # delay (type chosen in Settings), tempo synced except Slapback
        y = self._delay(dbus * dv, N, sr)
        mix += y
        rbus = rbus * rv + y * 0.35
        mix += self._reverb(rbus) * 1.1
        frame = np.concatenate([self.drum_hist, dmix])
        self.drum_hist = frame[N:]
        out = np.tanh((self._filter(mix) + frame[:N]) * mv)

        self.t += N
        self.active = frozenset(v.midi for v in self.voices if v.rel_at is None and v.midi is not None)
        el = time.perf_counter() - t0
        if el > N / sr:
            self.underruns += 1
        self.load = 0.9 * self.load + 0.1 * (el / (N / sr))
        return out.astype(np.float32)

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
