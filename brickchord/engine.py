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
NPATS = 16
CAP_TAGS = ("held", "strum", "arp", "harp", "drone", "bass")    # live notes that get recorded
LIVE_TAGS = ("held", "strum", "arp", "harp", "drone")           # live notes routed through the selected track
ACCENT_G, GHOST_G = 1.35, 0.4      # the levels the grid writes for accent and ghost steps
DRUM_ATTRS = ("drum", "kit", "swing", "swres", "acc", "ghost", "human", "choke")
DRUM_ORDER = ["kick", "snare", "clap", "rim", "tom", "hat", "ohat", "shk"]
MAX_VOICES = 56      # hard cap on sounding voices (keeps the mixer inside its time budget)

STRUM_PATTERNS = {"Strum Folk": "D.DU.UDU", "Strum Pop": "D.D.UDUd", "Strum Skank": ".D.D.D.D"}


class _V:
    __slots__ = ("a", "l", "pos", "start", "gain", "lg", "rg", "rel_at", "rel_len", "tag", "midi",
                 "srev", "sdly", "done", "trk", "rec", "part")


class _Chain:
    """One effects chain: the rack (drive, chorus, ...) and the sweepable filter.
    The live synth has one and every looper track has its own."""
    def __init__(self, L, nfft, flat):
        self.rack = {}
        self.was = set()
        self.mod_hist = np.zeros((1200, 2), np.float32)
        self.flt_hist = np.zeros((L - 1, 2), np.float32)
        self.flt_base = (0.0, 0.0)       # the track's own filter setting
        self.flt_user = (0.0, 0.0)       # base, or the right stick on the selected track
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
        self.bus = 0             # which send bus (A or B) this track's reverb and delay go to
        self.locks = {}          # step -> {"flt": (cutoff, res), "slide": True}: parameter locks
        self.lock_flt = False    # a filter lock is holding the chain's filter right now
        self.ch = chain
        self.idle = 99
        # drum track (Bricklab track 1): kit name, per-lane [level, mute, tune], swing 0..0.5 of
        # a step (on odd 16ths, or on the off-beat 8ths), accent/ghost depth, humanize, hat choke
        self.drum = False
        self.kit = None
        self.lanes = {}
        self.swing = 0.0
        self.swres = 16
        self.acc, self.ghost = ACCENT_G, GHOST_G
        self.human = 0.0
        self.choke = True


class _Bus:
    """One send bus: a reverb (partitioned FFT convolution at half rate) and a
    tempo-synced delay. Bricklab has two (A and B); each track sends to one."""
    def __init__(self, sr, N):
        self.sr, self.N = sr, N
        self.dly_beats = 0.75
        self.dbuf_len = int(sr * 4.0)
        self.dbuf = np.zeros((self.dbuf_len, 2), np.float32)
        self.dw = 0
        self.dly_type = "Ping-Pong"
        self.tape_hist = np.zeros((62, 2), np.float32)
        self.rev_name = None
        self.tail = 0               # blocks left to keep processing after the last send


class _Pattern:
    def __init__(self, mk):
        self.len = 32
        self.tracks = [_Track(mk()) for _ in range(LOOP_TRACKS)]
        self.ver = 0


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
        self.kits = {}            # name -> kit (the Classic one is also self.kit)
        self.tuned = {}           # (kit, lane, semitones) -> pitched drum sound
        # metronome (Bricklab): "off", "rec" (while counting in, armed or recording) or "on"
        self.metro, self.metro_lvl, self.metro_snd = "off", 0.7, None
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
        self.drone_xy = (0.0, 0.0) # left stick in Drone mode: x = thin/shimmer, y = pulse/swell
        self.drone_slide = 0.0     # seconds; > 0 and the drone glides to a new degree instead of restriking
        self.dvoices = []          # sliding drone voices (lead-style, pitch-shifted on the fly)
        self.amb = {}              # Brickambient: slot -> a long-gliding voice (see c_amb)
        self.amb_spread = 0.0      # cents of detune fanned across the voices (left stick X)
        self.amb_move = 1.0        # movement depth multiplier (left stick Y)
        self.gvoices = []          # sequenced slide voices: a track with slide locks plays mono and glides
        self.slide_time = 0.09     # seconds a slide step takes to reach its note
        self.drone_ph = 0.0
        # patterns and songs (see the section below)
        self.pats = []
        self.cur = 0               # playing (and edited) pattern
        self.cue = None            # pattern to switch to at the end of this one
        self.sel = 0               # selected track: live playing goes through it
        self.route = True
        self.song = [[0, 1]]
        self.song_on = False
        self.song_row = 0
        self.song_rep = 0
        self.stick_flt = (0.0, 0.0)
        self.lp_on = False         # transport running
        self.lp_pos = -1           # step within the pattern of the last processed step
        self.lp_abs = -1           # same, counted from the start (for recording spans)
        self.lp_step_at = 0        # sample time of that step
        self.lp_rec_p = 0
        self.lp_rec = None         # armed / recording track
        self.lp_state = None       # None | "armed" | "rec"
        self.rec_quant = 0         # record quantize, in 16ths (0 off, 1 = 1/16, 2 = 1/8, 4 = 1/4)
        self.lp_rec_start = 0.0
        self.lp_rec_end = 0.0
        self.lp_open = []          # recorded voices whose length isn't known yet
        self.lp_lead = None        # open lead note event while recording
        self.lp_ver = 0            # bumps on every change (UI redraw / save)
        self.lp_undo = None        # [pattern, length, tracks] from before the last change
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
        self.master = 0.8
        self.master_t = 0.8
        self.tape_S = {}
        self.buses = [_Bus(sr, block), _Bus(sr, block)]
        self._setup_reverb(self.buses[0], ir)
        self._setup_reverb(self.buses[1], ir)
        self._setup_filter()
        self.pats = [_Pattern(self._chain) for _ in range(NPATS)]
        self._tails = set()
        # monitoring
        self.active = frozenset()
        self.load = 0.0
        self.underruns = 0
        self.sink = None
        self.running = False

    # ------------------------------------------------------------ reverb
    def _setup_reverb(self, b, ir):
        """Partitioned FFT convolution run at half the sample rate: reverb tails
        have little above 5 kHz, and it costs about a quarter as much."""
        N2 = self.N // 2
        if ir is None:
            ir = np.zeros((self.N, 2), np.float32)
        ir = np.asarray(ir, np.float32)
        m = len(ir) // 2
        ir2 = ir[0:2 * m:2] + ir[1:2 * m:2]           # decimate, keeping the level
        P = max(1, int(math.ceil(len(ir2) / N2)))
        pad = np.zeros((P * N2, 2), np.float32)
        pad[:len(ir2)] = ir2
        b.H = np.fft.rfft(pad.reshape(P, N2, 2), 2 * N2, axis=1).astype(np.complex64)   # (P, N2+1, 2)
        b.rv_P = P
        b.FDL = np.zeros((2 * P,) + b.H.shape[1:], np.complex64)   # ring buffer, written twice
        b.rv_i = 0
        b.rprev = np.zeros((N2, 2), np.float32)
        b.rv_last = np.zeros(2, np.float32)

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
        """Right stick filter / resonance: acts on the selected track."""
        self.stick_flt = (max(0.0, min(1.0, f)), max(0.0, min(1.0, r)))
        self._apply_flt(self._sel_chain(), True)

    # ------------------------------------------------------------ effects rack
    # Stackable effects on the synth bus (drums and bass stay dry). Each is
    # (on, amount 0..1, rate index into RATES). Synced to the tempo.
    RATES = [("1/16", 0.25), ("1/8", 0.5), ("1/8.", 0.75), ("1/4", 1.0), ("1/2", 2.0),
             ("1 bar", 4.0), ("2 bars", 8.0), ("4 bars", 16.0)]
    FX_ORDER = ["Drive", "Lo-fi", "Chorus", "Flanger", "Vibrato", "Tremolo", "Gate",
                "Auto-Pan", "Wide", "Filter LFO", "Cloud"]
    # Cloud: a granular texture processor on the track. Its "rate" picks a texture:
    # (name, grain ms, grains per second, stereo spread, octave-up share, freeze, reverse share, crush)
    CLOUD_TEX = [("Dust", 30, 40, 0.0, 0.0, False, 0.0, 0), ("Grit", 35, 55, 0.6, 0.0, False, 0.5, 5),
                 ("Smear", 140, 18, 0.15, 0.0, False, 0.0, 0), ("Shimmer", 200, 14, 0.1, 0.5, False, 0.0, 0),
                 ("Haze", 320, 10, 0.4, 0.0, False, 0.3, 0), ("Drift", 500, 7, 0.8, 0.15, False, 0.5, 0),
                 ("Bloom", 800, 5, 0.25, 0.3, False, 0.0, 0), ("Freeze", 400, 12, 0.2, 0.2, True, 0.25, 0)]

    def c_rack(self, rack):
        """The Effects page: the selected track's rack."""
        self._sel_chain().rack = {k: tuple(v) for k, v in rack.items()}

    _CL_WIN = {}
    _RAMPS = {}

    @classmethod
    def _ramp(cls, N):
        """0..1 across a block, shaped (N, 1): built once, not every block."""
        r = cls._RAMPS.get(N)
        if r is None:
            r = cls._RAMPS[N] = np.linspace(0, 1, N, dtype=np.float32)[:, None]
            r.setflags(write=False)
        return r

    def _cloud_alive(self, ch):
        """Keep a silent track's chain running only while its Cloud still has
        something to play: Freeze holds forever; the others for the two seconds
        their buffer reaches back. (A silent chain with a full rack costs real CPU.)"""
        c = ch.rack.get("Cloud")
        if not c or not c[0]:
            return False
        tex = self.CLOUD_TEX[int(c[2]) % len(self.CLOUD_TEX)]
        if tex[5]:
            return True
        return bool(getattr(ch, "cl_grains", None)) or getattr(ch, "cl_quiet", 0) < 2 * self.sr

    def _cloud(self, ch, x, N, sr, a, ti):
        """Granular texture: the track's last two seconds sit in a mono buffer; grains
        are read back from it (behind the write head, scattered), at the same pitch or
        an octave up, windowed, panned and mixed in. Freeze keeps the last thing played.
        Cheap on purpose: grains are plain slices of the buffer, at most six at once."""
        name, gms, dens, spread, octup, freeze, revs, crush = self.CLOUD_TEX[ti % len(self.CLOUD_TEX)]
        B = 2 * sr
        if getattr(ch, "cl_buf", None) is None:
            ch.cl_buf = np.zeros(2 * B, np.float32)         # the ring, written twice, so reads never wrap
            ch.cl_w = 0
            ch.cl_grains = []
            ch.cl_rng = np.random.default_rng(1234)
        mono = (x[:, 0] + x[:, 1]) * 0.5
        loud = float(np.abs(mono).max()) > 1e-3
        ch.cl_quiet = 0 if loud else getattr(ch, "cl_quiet", 0) + N
        if not freeze or loud:                              # Freeze keeps the last thing played
            w = ch.cl_w
            e = w + N
            if e <= B:
                ch.cl_buf[w:e] = mono
                ch.cl_buf[B + w:B + e] = mono
            else:
                k = B - w
                ch.cl_buf[w:B] = mono[:k]
                ch.cl_buf[B + w:2 * B] = mono[:k]
                ch.cl_buf[:N - k] = mono[k:]
                ch.cl_buf[B:B + N - k] = mono[k:]
            ch.cl_w = e % B
        rng = ch.cl_rng
        gl = max(64, int(gms * sr / 1000))
        expect = dens * (0.4 + 0.8 * a) * N / sr
        n_new = min(rng.poisson(expect), 6 - len(ch.cl_grains))
        for _ in range(max(0, n_new)):
            up = rng.random() < octup
            back = rng.uniform(0.05, 1.6) * sr if not freeze else rng.uniform(0.0, 1.9) * sr
            back += gl * (2 if up else 1)
            start = int(ch.cl_w - back) % B
            pan = float(rng.uniform(-0.7, 0.7) * (0.4 + spread))
            rev = (not up) and rng.random() < revs
            ch.cl_grains.append([start, 0, gl, -1 if rev else (2 if up else 1), pan, int(rng.integers(0, N))])
        wl = np.zeros(N, np.float32)
        wr = np.zeros(N, np.float32)
        keep = []
        for g in ch.cl_grains:
            start, done, L, step, pan, off = g
            o = off if done == 0 else 0
            n = min(N - o, L - done)
            wv = self._CL_WIN.get(L)                       # each grain keeps its own length's window
            if wv is None:                                 # (it may have started under another texture)
                wv = self._CL_WIN[L] = np.hanning(L).astype(np.float32)
            if n > 0:
                if step < 0:                               # reversed grain: read backwards through it
                    e0 = start + L - done
                    seg = ch.cl_buf[e0 - n:e0][::-1] * wv[done:done + n]
                else:
                    p0 = start + done * step
                    seg = ch.cl_buf[p0:p0 + n * step:step][:n] * wv[done:done + n]
                if len(seg) == n:
                    wl[o:o + n] += seg * (1.0 - max(0.0, pan))
                    wr[o:o + n] += seg * (1.0 + min(0.0, pan))
                g[1] = done + n
            g[5] = 0
            if g[1] < L:
                keep.append(g)
        ch.cl_grains = keep
        norm = 1.0 / max(1.0, math.sqrt(dens * gms / 1000.0))
        mix = min(1.0, a * 1.2)
        g_wet = norm * (0.4 + 1.2 * mix)
        if crush:                                          # Grit: the cloud itself is bit-crushed and sample-held
            q = float(2 ** crush)
            wl = np.round(np.repeat(wl[::3], 3)[:N] * q) / q
            wr = np.round(np.repeat(wr[::3], 3)[:N] * q) / q
            g_wet *= 1.4
        out = x * (1.0 - 0.6 * mix)
        out[:, 0] += wl * g_wet
        out[:, 1] += wr * g_wet
        return out.astype(np.float32)

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
            if "Cloud" in on:
                x = self._cloud(ch, x, N, sr, on["Cloud"][1], on["Cloud"][2])
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
            ramp = self._ramp(N)
            y = y * (1 - ramp) + y_new * ramp
        return y.astype(np.float32)

    def c_reverb(self, ir, bus=0):
        """Switch a bus's reverb: an impulse response, or a reverb name (rendered
        here, so nothing big crosses the pipe). The old tail is dropped."""
        b = self.buses[int(bus)]
        if isinstance(ir, str):
            if ir == b.rev_name:
                return
            import synth
            b.rev_name = ir
            ir = synth.make_reverb(ir)
        else:
            b.rev_name = None
        self._setup_reverb(b, ir)

    def c_busfx(self, bus, rev_name, dly_type, beats):
        b = self.buses[int(bus)]
        b.dly_type = dly_type
        b.dly_beats = float(beats)
        self.c_reverb(rev_name, bus)

    def _reverb(self, b, x):
        N2 = self.N // 2
        P = b.rv_P
        xh = (x[0::2] + x[1::2]) * 0.5
        buf = np.concatenate([b.rprev, xh])
        b.rprev = xh
        i = b.rv_i = (b.rv_i - 1) % P
        X = np.fft.rfft(buf, 2 * N2, axis=0)
        b.FDL[i] = X
        b.FDL[i + P] = X
        Y = np.einsum("pkc,pkc->kc", b.FDL[i:i + P], b.H)       # newest block first
        yh = np.fft.irfft(Y, 2 * N2, axis=0)[N2:].astype(np.float32)
        y = np.empty((self.N, 2), np.float32)
        y[1::2] = yh
        y[0::2] = 0.5 * (yh + np.concatenate([b.rv_last[None, :], yh[:-1]]))
        b.rv_last = yh[-1]
        return y

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
        v.trk = v.rec = v.part = None
        if self.route and tag in LIVE_TAGS and not self._nocap and not self._seltr().drum:
            v.trk = (self.cur, self.sel)
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
                if not (self.quantize and (self.drums_on or self.lp_on)):
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
        tr = self._seltr() if self.route else None
        if tr is not None and tr.drum:
            snd, lv = self._drum_snd(tr, part)
        else:
            snd, lv = self.kit.get(part), 1.0
        if snd is None:
            return
        g, pan = DRUM_GAIN.get(part, 0.75) * gain, DRUM_PAN.get(part, 0.0)
        v = self._voice(snd, g * lv, pan, self.t, "drum", srev=0, sdly=0, rel=int(0.02 * self.sr))
        v.part = part
        if tr is not None and tr.drum:
            v.trk = (self.cur, self.sel)            # heard through the drum track's effects
            if tr.choke and part == "hat":
                self._choke(v.trk, self.t)
        if self.lp_state:
            self._cap(self.t, "d", part, g, pan, None, 0.02)

    def c_dhit(self, p, part, gain=1.0):
        """Audition one lane of pattern p's drum track (its kit, level, tune), from Settings."""
        tr = next((t for t in self.pats[int(p)].tracks if t.drum), None)
        if tr is None:
            return
        snd, lv = self._drum_snd(tr, part, audition=True)
        if snd is None:
            return
        v = self._voice(snd, DRUM_GAIN.get(part, 0.75) * gain * lv, DRUM_PAN.get(part, 0.0), self.t, "drum",
                        srev=0, sdly=0, rel=int(0.02 * self.sr))
        v.part = part

    def _choke(self, key, at):
        """A closed hat cuts the open hat still ringing on the same track."""
        fast = int(0.015 * self.sr)
        for v in self.voices:
            if v.part == "ohat" and v.trk == key and v.start < at and (v.rel_at is None or v.rel_at > at):
                v.rel_at, v.rel_len = int(at), fast

    def c_metro(self, mode, level, sound=None):
        """Metronome mode, level and sound. The sound is named, not sent: a pipe
        message that big (70 KB of arrays) could wedge the UI against the audio
        process, so the audio side renders the two clicks itself."""
        self.metro = mode if mode in ("off", "rec", "on") else "off"
        self.metro_lvl = max(0.0, min(1.0, float(level)))
        if sound and sound != getattr(self, "metro_name", None):
            import synth
            self.metro_name = sound
            self.metro_snd = synth.metro_arrays(sound)

    def _click(self, at, bar):
        snd = self.metro_snd[0 if bar else 1] if self.metro_snd else self.kit.get("click")
        if snd is not None:
            self._voice(snd, self.metro_lvl * (1.0 if bar else 0.8), 0.0, at, "drum", srev=0, sdly=0,
                        rel=int(0.01 * self.sr))

    def c_kits(self, kits):
        self.kits = dict(kits)
        self.tuned = {}
        if "Classic" in kits:
            self.kit = kits["Classic"]

    # ------------------------------------------------------------ drone layer
    # ------------------------------------------------------------ Brickambient voices
    # Each slot is one sustained voice: a sound rendered once at its base note and
    # pitched on the fly, so it can glide anywhere over seconds or minutes. Level
    # fades in and out; vibrato, tremolo and a slow random drift keep it moving.
    class _Amb:
        pass

    def _amb_slot(self, k):
        v = self.amb.get(k)
        if v is None:
            v = self.amb[k] = self._Amb()
            v.a = v.l = None
            v.pos, v.cur, v.tgt, v.glide = 0.0, 0.0, 0.0, 2.0
            v.lvl, v.lvl_t, v.fade = 0.0, 0.0, 3.0
            v.pan, v.vib, v.rate, v.trem, v.drift = 0.0, 0.0, 0.2, 0.0, 0.0
            v.ph = k * 1.7
            v.dr, v.dr_t, v.dr_n = 0.0, 0.0, 0
            v.retrig = False
            v.path = None              # a shaped glide: [cents...], from v.p_t0, delay, duration, shape
            v.p_t0, v.p_delay, v.p_dur, v.p_shape = 0, 0.0, 0.0, 0
        return v

    def c_amb_snd(self, k, snd, base_restart=True):
        v = self._amb_slot(int(k))
        if snd is None:
            return
        v.a, v.l = snd
        if base_restart or v.pos >= len(v.a) + (len(v.l) if v.l is not None else 0):
            v.pos = 0.0

    @staticmethod
    def amb_shape(p, shape):
        """Glide shapes, 0..1 -> 0..1 (the UI draws the same curves):
        0 smooth (fast then settling), 1 linear, 2 ease (S-curve), 3 swell (slight
        overshoot, then settle)."""
        p = 0.0 if p < 0 else (1.0 if p > 1 else p)
        if shape == 1:
            return p
        if shape == 2:
            return p * p * (3 - 2 * p)
        if shape == 3:
            e = p * p * (3 - 2 * p)
            return e + 0.45 * math.sin(math.pi * p) * p
        if shape == 4:                                  # Bounce: lands, overshoots, settles in two swings
            return 1.0 - (1.0 - p) ** 4 * math.cos(3.0 * math.pi * p)
        if shape == 5:                                  # Late: holds the old note, then slides at the end
            q = max(0.0, (p - 0.65) / 0.35)
            return q * q * (3 - 2 * q)
        if shape == 6:                                  # Snap: slides at once, then sits on the new note
            q = min(1.0, p / 0.25)
            return q * q * (3 - 2 * q)
        if shape == 7:                                  # Wobble: wavers around the way, like a hand on a ribbon
            e = p * p * (3 - 2 * p)
            return e + 0.09 * math.sin(6 * math.pi * p) * math.sin(math.pi * p)
        if shape == 8:                                  # Semitones: linear; the steps are made in amb_path_at
            return p
        return (1 - math.exp(-5 * p)) / (1 - math.exp(-5))

    @classmethod
    def amb_path_at(cls, path, el, dur, shape):
        """Where a shaped glide is el seconds after it starts (its delay already
        taken off). A path of several points walks them in equal steps, easing
        into each one."""
        if el <= 0:
            return path[0]
        if dur <= 0.02 or el >= dur:
            return path[-1]
        n = len(path) - 1
        if n == 1:
            v = path[0] + (path[1] - path[0]) * cls.amb_shape(el / dur, shape)
            if shape == 8:                              # Semitones: a staircase, every semitone on the way
                v = path[0] + round((v - path[0]) / 100.0) * 100.0
            return v
        q = el / dur * n
        i = min(n - 1, int(q))
        return path[i] + (path[i + 1] - path[i]) * cls.amb_shape(q - i, 2)

    def c_amb(self, k, d):
        """Update a voice: tgt (cents from its base note), level, on, pan, glide,
        fade, vib (cents), rate (Hz), trem (0..1), drift (cents). A new tgt starts a
        shaped glide from where the voice is now: shape, delay (s) and path (the
        cents to pass through) shape it; glide is its length."""
        v = self._amb_slot(int(k))
        old_tgt = v.tgt
        for name in ("tgt", "pan", "glide", "fade", "vib", "rate", "trem", "drift", "retrig"):
            if name in d:
                setattr(v, name, d[name])
        if "tgt" in d and (abs(v.tgt - old_tgt) > 0.5 or d.get("path")):
            via = [float(c) for c in (d.get("path") or [])]
            v.path = [v.cur] + via + [v.tgt]
            v.p_t0, v.p_delay = self.t, float(d.get("delay", 0.0))
            v.p_dur, v.p_shape = float(v.glide), int(d.get("shape", 0))
        if "level" in d or "on" in d:
            v.lvl_t = float(d.get("level", getattr(v, "level", 0.7))) if d.get("on", v.lvl_t > 0) else 0.0
            v.level = float(d.get("level", getattr(v, "level", 0.7)))
        if d.get("jump"):
            v.cur = v.tgt
            v.path = None

    def c_amb_trig(self, k, cents):
        """Melodic voice step on a struck sound: start the sound again at this pitch."""
        v = self._amb_slot(int(k))
        v.pos, v.cur, v.tgt = 0.0, float(cents), float(cents)

    def c_amb_global(self, spread, move):
        self.amb_spread, self.amb_move = float(spread), float(move)

    def _amb_render(self, mix, N, sr):
        dt = N / sr
        keep = {}
        for k, v in self.amb.items():
            if v.a is None:
                continue
            if v.lvl <= 0.0 and v.lvl_t <= 0.0:
                continue
            # pitch: glide toward the target (about 98% of the way in `glide` seconds)
            c0 = v.cur
            if v.path is not None:
                el = (self.t + N - v.p_t0) / sr - v.p_delay
                v.cur = self.amb_path_at(v.path, el, v.p_dur, v.p_shape)
                if el >= v.p_dur:
                    v.path = None
            elif v.glide > 0.02:
                v.cur = v.tgt + (v.cur - v.tgt) * math.exp(-4.0 * dt / v.glide)
            else:
                v.cur = v.tgt
            # slow random drift: a new target every few seconds, eased toward
            if v.drift > 0:
                v.dr_n -= 1
                if v.dr_n <= 0:
                    v.dr_t = (random.random() * 2 - 1) * v.drift * self.amb_move
                    v.dr_n = int((2.0 + 4.0 * random.random()) / dt)
                v.dr += (v.dr_t - v.dr) * min(1.0, dt / 1.5)
            ph0 = v.ph
            v.ph = (v.ph + 2 * math.pi * v.rate * dt) % (2 * math.pi)
            vib0 = v.vib * self.amb_move * math.sin(ph0)
            vib1 = v.vib * self.amb_move * math.sin(v.ph)
            spread = self.amb_spread * ((k % 6) / 2.5 - 1.0) if k < 6 else 0.0
            cents0 = c0 + v.dr + vib0 + spread
            cents1 = v.cur + v.dr + vib1 + spread
            r0, r1 = 2.0 ** (cents0 / 1200.0), 2.0 ** (cents1 / 1200.0)
            # level: linear fade, with tremolo riding on it
            l0 = v.lvl
            step = dt / max(0.05, v.fade)
            v.lvl = min(v.lvl_t, v.lvl + step) if v.lvl_t > v.lvl else max(v.lvl_t, v.lvl - step)
            t0 = 1.0 - v.trem * 0.5 * (1 + math.sin(ph0 * 0.5))
            t1 = 1.0 - v.trem * 0.5 * (1 + math.sin(v.ph * 0.5))
            ramp = self._ramp(N)[:, 0]
            r = r0 + (r1 - r0) * ramp
            pos = v.pos + np.concatenate(([0.0], np.cumsum(r[:-1], dtype=np.float64)))
            v.pos = float(pos[-1] + r[-1])
            total = len(v.a) + (1e18 if v.l is not None else 0)
            if pos[0] >= total:
                continue
            seg = self._lead_interp(v, pos)
            g = (l0 * t0 + (v.lvl * t1 - l0 * t0) * ramp).astype(np.float32)
            lg, rg = min(1.0, 1.0 - v.pan), min(1.0, 1.0 + v.pan)
            seg[:, 0] *= g * lg
            seg[:, 1] *= g * rg
            mix += seg
        return keep

    def c_drone_slide(self, secs):
        self.drone_slide = max(0.0, float(secs))

    def c_drone(self, notes, snd):
        """Sustained notes on their own layer: they keep going while you play
        chords or lead on top. Sounds that don't sustain are re-struck. With
        drone_slide set, a new degree is reached by sliding every voice there."""
        recording = bool(self.lp_state) and not self._nocap
        if self.drone_slide > 0 and not recording and notes and \
                all(snd.get(m) is not None and snd[m][1] is not None for m in notes):
            self._release(("drone",), self.t, int(0.8 * self.sr))      # any old struck drone fades
            self.drone = {"notes": list(notes), "snd": snd, "restrike": False}
            live = [v for v in self.dvoices if not v.rel]
            notes = sorted(notes)
            # voices that stay slide, extras fade, new ones fade in
            for idx, m in enumerate(notes):
                if idx < len(live):
                    v = live[idx]
                    v.target = m
                    v.glide = self.drone_slide * (1.0 + 0.25 * idx)     # upper voices arrive a little later
                    v.midi = m
                else:
                    v = self._Lead()
                    v.a, v.l = snd[m]
                    v.base = v.target = m
                    v.ratio = 1.0
                    v.glide = 0.0
                    v.pos = 0.0
                    v.env = 0.0
                    v.rel, v.rel_n = False, 0
                    v.fade_in = int(0.6 * self.sr)
                    v.midi = m
                    self.dvoices.append(v)
            for v in live[len(notes):]:
                v.rel, v.rel_n = True, int(0.8 * self.sr)
            return
        for v in self.dvoices:
            if not v.rel:
                v.rel, v.rel_n = True, int(0.8 * self.sr)
        self._release(("drone",), self.t, int(0.8 * self.sr))
        if not notes:
            self.drone = None
            return
        restrike = any(snd.get(m) is not None and snd[m][1] is None for m in notes)
        self.drone = {"notes": list(notes), "snd": snd, "restrike": restrike}
        self._drone_strike(self.t)

    def c_drone_mod(self, x, y):
        self.drone_xy = (max(-1.0, min(1.0, float(x))), max(-1.0, min(1.0, float(y))))

    def _drone_env(self, v, T, N):
        """The left stick shaping the drone, per block. Down: tempo-synced pulses
        that get faster and harder the further you push. Up: a swell with a slow
        rotating pan. Left: thins to the root. Right: the upper voices bloom and
        breathe. Returns (gain array, left gain, right gain)."""
        x, y = self.drone_xy
        dz = 0.25                                           # a resting stick does nothing
        if abs(x) < dz and abs(y) < dz:
            return None
        x = 0.0 if abs(x) < dz else (abs(x) - dz) / (1 - dz) * (1 if x > 0 else -1)
        y = 0.0 if abs(y) < dz else (abs(y) - dz) / (1 - dz) * (1 if y > 0 else -1)
        sr = self.sr
        i = v.midi - min(self.drone["notes"]) if self.drone else 0     # 0 at the root, higher = upper voice
        g = np.ones(N, np.float32)
        lg = rg = 1.0
        if y < 0:                                           # pulse: a smooth gate, no clicks
            beat = 60.0 / self.bpm
            div = 2 if y > -0.4 else (4 if y > -0.75 else 8)         # 1/8, 1/16, 1/32
            ph = (T / sr) % (beat / div) / (beat / div)
            depth = min(1.0, -y * 1.1)
            duty = 0.6 - 0.3 * depth
            edge = 0.12
            on = np.clip(ph / edge, 0, 1) * np.clip((duty - ph) / edge, 0, 1)
            pulse = 0.5 - 0.5 * np.cos(np.pi * on)                   # raised cosine in and out
            g *= (1 - depth) + depth * pulse.astype(np.float32)
        elif y > 0:                                         # swell + rotation
            sw = y
            g *= 1.0 + 0.6 * sw
            rot = 2 * np.pi * (T[-1] / sr) * (0.15 + 0.6 * sw) + i * 1.3
            lg, rg = 1.0 - 0.6 * sw * (0.5 + 0.5 * np.sin(rot)), 1.0 - 0.6 * sw * (0.5 - 0.5 * np.sin(rot))
        if x < 0 and i > 0:                                 # thin: upper voices fade
            g *= max(0.0, 1.0 + x * 1.1)
        elif x > 0 and i > 0:                               # bloom: upper voices breathe up
            br = 0.5 + 0.5 * np.sin(2 * np.pi * (T / sr) * (0.25 + 0.5 * x) + i * 0.9)
            g *= 1.0 + x * (0.3 + 0.9 * br.astype(np.float32))
        return g, lg, rg

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

    def _lead_window(self, v, lo, hi):
        """Samples lo..hi (inclusive) of a voice's sound: the attack, then the loop
        repeated (or silence after a one-shot), copied as slices."""
        a, l = v.a, v.l
        na = len(a)
        n = hi - lo + 1
        out = np.zeros((n, 2), np.float32)
        k = 0
        if lo < na:
            k = min(n, na - lo)
            out[:k] = a[lo:lo + k]
        if k < n and l is not None:
            ll = len(l)
            st = (lo + k - na) % ll
            while k < n:
                c = min(n - k, ll - st)
                out[k:k + c] = l[st:st + c]
                k += c
                st = 0
        return out

    def _lead_interp(self, v, pos):
        """Resample a voice at fractional positions: one window copy, two takes."""
        i0 = pos.astype(np.int64)
        lo = int(i0[0])
        w = self._lead_window(v, lo, int(i0[-1]) + 1)
        j = i0 - lo
        fr = (pos - i0).astype(np.float32)[:, None]
        return w[j] * (1 - fr) + w[j + 1] * fr

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

    def _drone_render(self, mix, N, sr):
        """The sliding drone voices: lead-style resampling with glide, each with
        its own pan and the left-stick shaping, into the drone's bus."""
        i = np.arange(N, dtype=np.float64)
        T = np.arange(self.t, self.t + N)
        keep = []
        n = max(1, len(self.drone["notes"]) if self.drone else 1)
        for idx, v in enumerate(self.dvoices):
            rt = 2.0 ** ((v.target - v.base) / 12.0)
            if v.target == v.base and v.ratio == 1.0 and float(v.pos).is_integer():
                p0 = int(v.pos)                            # at its own pitch: a plain slice
                seg = self._lead_window(v, p0, p0 + N - 1)
                v.pos = float(p0 + N)
            else:
                if v.glide > 0.005 and abs(v.ratio - rt) > 1e-5:
                    c = math.exp(-1.0 / (v.glide * 0.35 * sr))
                    r = rt + (v.ratio - rt) * c ** (i + 1)
                else:
                    r = np.full(N, rt)
                v.ratio = float(r[-1])
                pos = v.pos + np.concatenate(([0.0], np.cumsum(r[:-1])))
                v.pos = float(pos[-1] + r[-1])
                seg = self._lead_interp(v, pos)
            if v.fade_in > 0:
                env = v.env + np.arange(1, N + 1, dtype=np.float32) / v.fade_in
                env = np.clip(env, 0, 1)
                v.env = float(env[-1])
                if v.env >= 1.0:
                    v.fade_in = 0
                seg *= env[:, None]
            if v.rel:
                env = v.env - np.arange(1, N + 1, dtype=np.float32) / max(1, v.rel_n)
                env = np.clip(env, 0, 1)
                v.env = float(env[-1])
                seg *= (env * env)[:, None]
            pan = (idx / max(1, n - 1) - 0.5) * 0.8 if n > 1 else 0.0
            g = 0.7 * 0.95
            lg, rg = min(1.0, 1.0 - pan), min(1.0, 1.0 + pan)
            de = self._drone_env(v, T, N) if self.drone else None
            if de is not None:
                seg *= (g * de[0])[:, None]
                lg, rg = lg * de[1], rg * de[2]
            else:
                seg *= g
            seg[:, 0] *= lg
            seg[:, 1] *= rg
            mix += seg
            if v.rel and v.env <= 0.0:
                continue
            keep.append(v)
        self.dvoices = keep

    def _lead_render(self, mix, N, sr):
        i = np.arange(N, dtype=np.float64)
        vib = 1.0
        if self.lead_vib > 0.01:
            ph = self.vib_ph + 2 * np.pi * 5.5 * i / sr
            vib = 2.0 ** (self.lead_vib * 0.6 * np.sin(ph) / 12.0)
        self.vib_ph = (self.vib_ph + 2 * np.pi * 5.5 * N / sr) % (2 * np.pi)
        bend = 2.0 ** (self.lead_bend / 12.0)
        keep = []
        still = not isinstance(vib, np.ndarray) and bend == 1.0
        for v in self.leads:
            rt = 2.0 ** ((v.target - v.base) / 12.0)
            if still and v.target == v.base and v.ratio == 1.0 and float(v.pos).is_integer():
                # at its own pitch, no bend or vibrato: the same samples, copied as a slice
                p0 = int(v.pos)
                seg = self._lead_window(v, p0, p0 + N - 1)
                v.pos = float(p0 + N)
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
                continue
            if v.glide > 0.005 and abs(v.ratio - rt) > 1e-5:
                c = math.exp(-1.0 / (v.glide * 0.35 * sr))
                r = rt + (v.ratio - rt) * c ** (i + 1)
            else:
                r = np.full(N, rt)
            v.ratio = float(r[-1])
            r = r * vib * bend
            pos = v.pos + np.concatenate(([0.0], np.cumsum(r[:-1])))
            v.pos = float(pos[-1] + r[-1])
            seg = self._lead_interp(v, pos)
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

    # ------------------------------------------------------------ patterns and songs
    # 16 patterns, each 1 to 8 bars with 6 tracks. A track holds the notes you
    # played (the notes the engine actually sounded, so strums and arps come
    # back exactly) plus its own sound, effects chain, level, pan and sends.
    # Live playing goes through the selected track of the playing pattern, so
    # what you hear while playing is what that track will sound like.
    # A song is a list of [pattern, repeats] rows.
    def _step_len(self):
        return 60.0 / self.bpm / 4 * self.sr

    def _abspos(self, T):
        return self.lp_abs + (T - self.lp_step_at) / self._step_len()

    def _ppos(self, T):
        L = self.pats[self.cur].len
        return (self.lp_pos + (T - self.lp_step_at) / self._step_len()) % L

    def _has(self, p=None):
        pats = self.pats if p is None else [self.pats[p]]
        return any(tr.ev for pat in pats for tr in pat.tracks)

    def _bump(self, p):
        self.pats[p].ver += 1
        self.lp_ver += 1

    def _index(self, pat, tr):
        tr.by = {}
        for ev in tr.ev:
            ev[7] = False
            if ev[0] < pat.len:
                tr.by.setdefault(int(ev[0]), []).append(ev)

    def _snap_undo(self, p):
        pat = self.pats[p]
        self.lp_undo = [p, pat.len, [([list(e) for e in tr.ev], dict(tr.snd)) for tr in pat.tracks]]

    def _sel_chain(self):
        return self.pats[self.cur].tracks[self.sel].ch if self.route else self.live

    def _seltr(self):
        return self.pats[self.cur].tracks[self.sel]

    def _drum_snd(self, tr, part, audition=False):
        """A drum lane's sound and level on a drum track (its kit, lane level, mute, tune)."""
        kit = self.kits.get(tr.kit) or self.kit
        lv = tr.lanes.get(part)
        if lv is not None and lv[1] and not audition:
            return None, 0.0
        snd = kit.get(part) or self.kit.get(part)
        semis = int(lv[2]) if lv is not None and len(lv) > 2 else 0
        if semis and snd is not None:
            snd = self._tuned(tr.kit, part, snd, semis)
        return snd, (1.0 if lv is None else float(lv[0]))

    def _tuned(self, kit, part, snd, semis):
        """A drum sound pitched by semitones (resampled once, then kept)."""
        key = (kit, part, semis)
        out = self.tuned.get(key)
        if out is None:
            a = snd[0]
            r = 2.0 ** (semis / 12.0)
            n = max(16, int(len(a) / r))
            x = np.arange(n, dtype=np.float64) * r
            i = np.arange(len(a), dtype=np.float64)
            b = np.stack([np.interp(x, i, a[:, ch]) for ch in range(a.shape[1])], axis=1).astype(np.float32)
            out = self.tuned[key] = (b, None)
            if len(self.tuned) > 96:
                self.tuned.pop(next(iter(self.tuned)))
        return out

    def _apply_flt(self, ch, stick):
        f, r = ch.flt_base
        if stick:
            f, r = max(f, self.stick_flt[0]), max(r, self.stick_flt[1])
        ch.flt_user = (f, r)
        if "Filter LFO" not in ch.was:
            ch.flt_t = (round(f, 2), round(r, 2))

    def _route_changed(self, old_ch):
        new = self._sel_chain()
        if old_ch is not new:
            self._apply_flt(old_ch, False)
        self._apply_flt(new, True)

    def _lp_begin(self, T):
        """First note after arming: start the transport if it isn't running (on
        the bar line when the beat is on), then record one pass of the pattern."""
        step = self._step_len()
        if not self.lp_on:
            self.lp_step_at = int(self.next16 - step)
            if self.drums_on:
                pos = (self.step16 - 1) % 16
            else:
                pos = -1 if T >= self.next16 - 0.5 else 0
            self.lp_pos = self.lp_abs = pos
            self.lp_on = True
        self.lp_rec_p = self.cur
        self._snap_undo(self.cur)
        self.lp_rec_start = self._abspos(T)
        self.lp_rec_end = self.lp_rec_start + self.pats[self.cur].len
        self.lp_state = "rec"
        self.lp_ver += 1

    def _cap(self, T, kind, ident, gain, pan, dur, rel, snd=None):
        k = self.lp_rec
        if k is None or not self.lp_state:
            return None
        if self.lp_state == "count":
            return None
        if self.lp_state == "armed":
            self._lp_begin(T)
        if self.cur != self.lp_rec_p:
            return None
        ap = self._abspos(T)
        if ap >= self.lp_rec_end or ap < self.lp_rec_start - 0.5:
            return None
        pat = self.pats[self.cur]
        L = pat.len
        pos = self._ppos(T)
        if self.rec_quant and kind in ("n", "b", "d"):
            q = float(self.rec_quant)
            pos = (round(pos / q) * q) % L
            ap = self.lp_rec_start + ((ap - self.lp_rec_start) // L) * L + pos   # the same snap, in absolute steps
        tr = pat.tracks[k]
        if tr.drum and kind != "d":
            return None                   # the drum track only takes drum hits
        skip = int(math.floor(ap)) > self.lp_abs     # its step hasn't played yet this pass
        ev = [round(pos, 4), kind, ident, round(float(gain), 3), round(float(pan), 3),
              None if dur is None else min(float(L), dur), round(float(rel), 3), skip]
        tr.ev.append(ev)
        tr.by.setdefault(int(pos) % L, []).append(ev)
        if kind == "n" and snd is not None and ident not in tr.snd:
            tr.snd[ident] = snd
        self._bump(self.cur)
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
        L = self.pats[self.lp_rec_p].len
        d = max(0.05, (at - v.start) / self._step_len())
        if self.rec_quant:                                    # length quantize: end on a step too
            q = float(self.rec_quant)
            d = max(q, round(d / q) * q)
        if ev[5] is None or d < ev[5]:
            ev[5] = round(min(float(L), d), 3)

    def _lead_cap_end(self, at):
        ev, self.lp_lead = self.lp_lead, None
        if ev is not None and ev[5] is None and self.cur == self.lp_rec_p:
            L = self.pats[self.cur].len
            d = max(0.1, (self._ppos(at) - ev[0]) % L)
            if self.rec_quant:
                q = float(self.rec_quant)
                d = max(q, round(d / q) * q)
            ev[5] = round(min(float(L), d), 3)

    def _lp_rec_stop(self, at):
        for v in self.lp_open:
            if v.rec is not None and v.l is not None:
                self._rec_close(v, at)
            v.rec = None
        self.lp_open = []
        self._lead_cap_end(at)
        self.lp_rec = None
        self.lp_state = None
        self._bump(self.lp_rec_p)

    def _release_track(self, p, k, fade=0.03):
        at = self.t
        key = (p, k)
        for v in self.voices:
            if v.tag == "loop" and v.trk == key and (v.rel_at is None or v.rel_at > at):
                v.rel_at, v.rel_len = at, int(fade * self.sr)
        for v in self.gvoices:
            if v.trk == key:
                v.rel_at, v.rel_n, v.pend = at, int(fade * self.sr) or 64, None

    def _start_transport(self, row=None):
        step = self._step_len()
        if self.song_on and self.song:
            self.song_row = (row if row is not None else self.song_row) % len(self.song)
            self.song_rep = 0
            old = self._sel_chain()
            self.cur = self.song[self.song_row][0]
            self._route_changed(old)
        self.lp_step_at = int(self.next16 - step)
        # start on the next bar line when the beat is on, else on the next step
        self.lp_pos = -((16 - self.step16 % 16) % 16) - 1 if self.drums_on else -1
        self.lp_abs = self.lp_pos
        self.lp_on = True

    def c_lp(self, op, *a):
        if op == "sel":
            old = self._sel_chain()
            self.sel = int(a[0])
            self._route_changed(old)
        elif op == "route":
            old = self._sel_chain()
            self.route = bool(a[0])
            self._route_changed(old)
        elif op == "pat":
            p = int(a[0]) % NPATS
            if self.lp_on:
                self.cue = None if p == self.cur else p
            else:
                old = self._sel_chain()
                self.cur, self.cue = p, None
                self._route_changed(old)
            self.lp_ver += 1
        elif op == "len":
            p, n = int(a[0]), int(a[1])
            pat = self.pats[p]
            pat.len = max(4, min(256, n))
            for tr in pat.tracks:
                self._index(pat, tr)
            self._bump(p)
        elif op == "arm":
            k = a[0]
            count = int(a[1]) if len(a) > 1 and a[1] else 0
            if self.lp_state:
                self._lp_rec_stop(self.t)
            if k is not None:
                self.lp_rec = int(k)
                if count:
                    # count-in: clicks, then recording starts on the one. If the
                    # transport is already running, it starts at the next pattern start.
                    self.lp_state = "count"
                    if not self.lp_on:
                        self._start_transport()
                        self.lp_pos = self.lp_abs = -count - 1
                else:
                    self.lp_state = "armed"         # starts on the first note you play
                    if self._has() and not self.lp_on:
                        self._start_transport()
            self.lp_ver += 1
        elif op in ("clear", "clearpat"):
            p = int(a[0])
            ks = [int(a[1])] if op == "clear" else range(LOOP_TRACKS)
            if self.lp_state and self.lp_rec_p == p and (op == "clearpat" or self.lp_rec in ks):
                self._lp_rec_stop(self.t)
            if self._has(p):
                self._snap_undo(p)
            for k in ks:
                tr = self.pats[p].tracks[k]
                tr.ev, tr.by, tr.snd = [], {}, {}
                self._release_track(p, k)
            self._bump(p)
        elif op == "copy":
            src, dst = self.pats[int(a[0])], self.pats[int(a[1])]
            dst.len = src.len
            for ts, td in zip(src.tracks, dst.tracks):
                td.ev = [list(e[:7]) + [False] for e in ts.ev]
                td.snd = dict(ts.snd)
                td.mute, td.vol, td.pan, td.rs, td.ds, td.bus = ts.mute, ts.vol, ts.pan, ts.rs, ts.ds, ts.bus
                for f in DRUM_ATTRS:
                    setattr(td, f, getattr(ts, f))
                td.lanes = {n: list(v) for n, v in ts.lanes.items()}
                td.locks = {st: dict(v) for st, v in ts.locks.items()}
                td.ch.rack = dict(ts.ch.rack)
                td.ch.flt_base = ts.ch.flt_base
                self._apply_flt(td.ch, False)
                self._index(dst, td)
            self._bump(int(a[1]))
        elif op == "play":
            on = bool(a[0])
            row = a[1] if len(a) > 1 else None
            if on and not self.lp_on:
                self._start_transport(row)
            elif not on and self.lp_on:
                if self.lp_state:
                    self._lp_rec_stop(self.t)
                self.lp_on = False
                self.cue = None
                for v in self.voices:
                    if v.tag == "loop" and (v.rel_at is None or v.rel_at > self.t):
                        v.rel_at, v.rel_len = self.t, int(0.03 * self.sr)
                for v in self.gvoices:
                    v.rel_at, v.rel_n, v.pend = self.t, int(0.03 * self.sr), None
            self.lp_ver += 1
        elif op == "song":
            self.song = [[int(r[0]) % NPATS, max(1, int(r[1]))] for r in a[0]] or [[0, 1]]
            self.song_on = bool(a[1])
            self.song_row %= len(self.song)
            self.lp_ver += 1
        elif op == "mix":
            p, k, d = int(a[0]), int(a[1]), a[2]
            tr = self.pats[p].tracks[k]
            for name in ("vol", "pan", "rs", "ds", "mute"):
                if name in d:
                    setattr(tr, name, d[name])
            if "bus" in d:
                tr.bus = 1 if int(d["bus"]) else 0
            if d.get("mute"):
                self._release_track(p, k, 0.05)
        elif op == "fx":
            p, k, rack, flt = int(a[0]), int(a[1]), a[2], a[3]
            ch = self.pats[p].tracks[k].ch
            ch.rack = {n: tuple(v) for n, v in rack.items()}
            ch.flt_base = (max(0.0, min(1.0, flt[0])), max(0.0, min(1.0, flt[1])))
            self._apply_flt(ch, ch is self._sel_chain())
        elif op == "snd":
            p, k, snd, replace = int(a[0]), int(a[1]), a[2], (a[3] if len(a) > 3 else False)
            tr = self.pats[p].tracks[k]
            if replace:
                tr.snd = dict(snd)
                self._release_track(p, k, 0.08)
            else:
                tr.snd.update(snd)
            self._bump(p)
        elif op == "locks":                   # (p, k, {step: {"flt": (f, r), "slide": bool}})
            tr = self.pats[int(a[0])].tracks[int(a[1])]
            tr.locks = {int(st): dict(v) for st, v in (a[2] or {}).items() if v}
        elif op == "load":
            p, n, tracks = int(a[0]), int(a[1]), a[2]
            pat = self.pats[p]
            pat.len = n
            for tr, evs in zip(pat.tracks, tracks):
                tr.ev = [list(e[:7]) + [False] for e in (evs or [])]
                self._index(pat, tr)
            self._bump(p)
        elif op == "undo":
            if self.lp_state:
                self._lp_rec_stop(self.t)
            if self.lp_undo:
                p, n, data = self.lp_undo
                self._snap_undo(p)                    # undo again = redo
                pat = self.pats[p]
                pat.len = n
                for k, (tr, (ev, snd)) in enumerate(zip(pat.tracks, data)):
                    tr.ev, tr.snd = [list(e) for e in ev], snd
                    self._index(pat, tr)
                    self._release_track(p, k)
                self._bump(p)
        elif op == "ed":
            self._edit(*a)
        elif op == "drum":
            p, k, d = int(a[0]), int(a[1]), a[2]
            tr = self.pats[p].tracks[k]
            tr.drum = bool(d.get("on", True))
            tr.kit = d.get("kit")
            tr.lanes = {n: [float(v[0]), bool(v[1]), int(v[2]) if len(v) > 2 else 0]
                        for n, v in (d.get("lanes") or {}).items()}
            tr.swing = max(0.0, min(0.5, float(d.get("swing", 0.0))))
            tr.swres = 8 if int(d.get("swres", 16)) == 8 else 16
            tr.acc = max(1.0, min(2.5, float(d.get("acc", ACCENT_G))))
            tr.ghost = max(0.05, min(1.0, float(d.get("ghost", GHOST_G))))
            tr.human = max(0.0, min(1.0, float(d.get("human", 0.0))))
            tr.choke = bool(d.get("choke", True))
            for n, v in tr.lanes.items():
                if v[2]:
                    self._drum_snd(tr, n, audition=True)     # resample now, not on the first hit

    def _edit(self, what, p, k, *a):
        """Step-grid edits on one track. Every edit can be undone."""
        pat = self.pats[p]
        tr = pat.tracks[k]
        self._snap_undo(p)
        if what == "add":
            for e in a[0]:
                ev = list(e[:7]) + [False]
                ev[0] = float(ev[0]) % pat.len
                tr.ev.append(ev)
        elif what == "del":
            step = int(a[0])
            tr.ev = [e for e in tr.ev if int(e[0]) != step]
            self._release_track(p, k)
        elif what == "shift":
            step, d = int(a[0]), int(a[1])
            for e in tr.ev:
                if int(e[0]) != step:
                    continue
                if e[1] in ("n", "b"):
                    e[2] = max(12, min(115, e[2] + d))
                elif e[2] in DRUM_ORDER:
                    e[2] = DRUM_ORDER[(DRUM_ORDER.index(e[2]) + (1 if d > 0 else -1)) % len(DRUM_ORDER)]
        elif what == "len":
            step, d = int(a[0]), float(a[1])
            for e in tr.ev:
                if int(e[0]) == step:
                    e[5] = max(0.25, min(float(pat.len), (e[5] or 1.0) + d))
        elif what == "quant":                # snap every step to the grid: (grid in 16ths,)
            q = float(a[0]) if a and a[0] else 1.0
            for e in tr.ev:
                e[0] = float((round(e[0] / q) * q) % pat.len)
        elif what == "dtog":                 # drum step on/off: (step, part, gain, pan)
            step, part = int(a[0]), a[1]
            hit = [e for e in tr.ev if e[1] == "d" and e[2] == part and int(round(e[0])) % pat.len == step]
            if hit:
                tr.ev = [e for e in tr.ev if not any(e is h for h in hit)]
            else:
                tr.ev.append([float(step), "d", part, float(a[2]), float(a[3]), None, 0.02, False])
        elif what == "nvel":                 # note velocity on a step: (step, delta)
            step, dl = int(a[0]), float(a[1])
            for e in tr.ev:
                if e[1] in ("n", "b") and int(round(e[0])) % pat.len == step:
                    e[3] = round(max(0.1, min(1.2, e[3] + dl)), 2)
        elif what == "dvel":                 # set a drum step's level: (step, part, gain)
            step, part = int(a[0]), a[1]
            for e in tr.ev:
                if e[1] == "d" and e[2] == part and int(round(e[0])) % pat.len == step:
                    e[3] = float(a[2])
        elif what == "dlane":                # clear one drum lane: (part,)
            tr.ev = [e for e in tr.ev if not (e[1] == "d" and e[2] == a[0])]
            self._release_track(p, k)
        elif what == "dset":                 # replace the whole track (a preset beat)
            tr.ev = [list(e[:7]) + [False] for e in a[0]]
            self._release_track(p, k)
        self._index(pat, tr)
        self._bump(p)

    def _next_pattern(self, at):
        old_p, old_ch = self.cur, self._sel_chain()
        if self.song_on and self.song:
            self.song_rep += 1
            row = self.song[self.song_row % len(self.song)]
            if self.song_rep >= max(1, row[1]):
                self.song_rep = 0
                self.song_row = (self.song_row + 1) % len(self.song)
            self.cur = self.song[self.song_row][0]
            self.cue = None
        elif self.cue is not None:
            self.cur, self.cue = self.cue, None
        if self.cur != old_p:
            if self.lp_state == "rec":
                self._lp_rec_stop(at)
            self._route_changed(old_ch)
            self.lp_ver += 1

    def _lp_step(self, at):
        if not self.lp_on:
            return
        step = self._step_len()
        pos = self.lp_pos + 1
        self.lp_abs += 1
        self.lp_step_at = at
        if self.lp_state == "rec" and self.lp_abs >= self.lp_rec_end:
            self._lp_rec_stop(int(at - (self.lp_abs - self.lp_rec_end) * step))
        if pos >= self.pats[self.cur].len:
            pos = 0
            self._next_pattern(at)
        self.lp_pos = pos
        if pos < 0:
            if self.lp_state == "count" and pos % 4 == 0:
                lvl = self.metro_lvl
                self.metro_lvl = max(lvl, 0.5)            # the count-in always clicks
                self._click(at, pos % 16 == 0)
                self.metro_lvl = lvl
            return
        if pos == 0 and self.lp_state == "count":
            self.lp_rec_p = self.cur
            self._snap_undo(self.cur)
            self.lp_rec_start = float(self.lp_abs)
            self.lp_rec_end = self.lp_rec_start + self.pats[self.cur].len
            self.lp_state = "rec"
            self.lp_ver += 1
        if pos % 4 == 0 and self.metro_lvl > 0 and (
                self.metro == "on" or (self.metro == "rec" and self.lp_state in ("rec", "armed", "count"))):
            self._click(at, pos % 16 == 0)
        p = self.cur
        self._nocap = True
        try:
            for k, tr in enumerate(self.pats[p].tracks):
                lk = tr.locks.get(pos) if tr.locks else None
                if lk and lk.get("flt") is not None:
                    tr.ch.flt_t = (round(float(lk["flt"][0]), 2), round(float(lk["flt"][1]), 2))
                    tr.lock_flt = True
                elif tr.lock_flt:
                    fu = tr.ch.flt_user
                    tr.ch.flt_t = (round(fu[0], 2), round(fu[1], 2))
                    tr.lock_flt = False
                evs = tr.by.get(pos)
                if not evs:
                    continue
                for ev in evs:
                    if ev[7]:
                        ev[7] = False          # recorded just now and still sounding live
                        continue
                    if not tr.mute:
                        self._lp_play((p, k), tr, ev, at + (ev[0] - pos) * step, step)
        finally:
            self._nocap = False

    def _glide_play(self, key, tr, ident, snd, gain, pan, dur, rel, start, step, slide, pos=0.0):
        """A track with slide locks plays mono: a slide step glides the sounding
        voice to the new note (303 style); any other step starts a fresh voice.
        A note followed by a slide step holds until that step, so it can glide."""
        cur = next((v for v in self.gvoices if v.trk == key and not v.rel), None)
        end = int(start + (dur if dur else 1.0) * step)
        L = max(1, self.pats[key[0]].len)
        later = sorted(((e[0] - pos) % L, e[0]) for e in tr.ev if e[1] == "n" and (e[0] - pos) % L > 0.01)
        if later:
            gap, nxt = later[0]
            if tr.locks.get(int(round(nxt)) % L, {}).get("slide"):
                end = max(end, int(start + gap * step) + 256)
        if cur is not None and slide:
            cur.pend = (int(start), ident, self.slide_time, end)
            cur.end_at = max(cur.end_at, int(start) + 64)
            return
        if cur is not None:
            cur.rel_at = int(start)
        v = self._Lead()
        v.trk = key
        v.a, v.l = snd
        v.base = v.target = ident
        v.ratio, v.glide, v.pos, v.env = 1.0, 0.0, 0.0, 0.0
        v.rel, v.rel_n, v.rel_at = False, max(64, int(rel * self.sr)), None
        v.start, v.end_at, v.pend = int(start), end, None
        v.gain = gain
        v.lg, v.rg = min(1.0, 1.0 - pan), min(1.0, 1.0 + pan)
        self.gvoices.append(v)

    def _glide_render(self, tb, N, sr):
        T0 = self.t
        keep = []
        for v in self.gvoices:
            b = tb.get(v.trk)
            if b is None:
                b = tb[v.trk] = np.zeros((N, 2), np.float32)
            if v.start >= T0 + N:
                keep.append(v)
                continue
            if v.pend is not None and v.pend[0] < T0 + N:
                _, tgt, gl, end = v.pend
                v.target, v.glide, v.end_at, v.pend = tgt, gl, end, None
            if not v.rel and ((v.rel_at is not None and v.rel_at < T0 + N) or
                              (v.pend is None and v.end_at < T0 + N)):
                v.rel = True
            off = max(0, v.start - T0)
            n = N - off
            rt = 2.0 ** ((v.target - v.base) / 12.0)
            if v.target == v.base and v.ratio == 1.0 and float(v.pos).is_integer():
                p0 = int(v.pos)                            # not sliding: a plain slice
                seg = self._lead_window(v, p0, p0 + n - 1)
                v.pos = float(p0 + n)
            else:
                i = np.arange(n, dtype=np.float64)
                if v.glide > 0.005 and abs(v.ratio - rt) > 1e-5:
                    cc = math.exp(-1.0 / (v.glide * 0.35 * sr))
                    r = rt + (v.ratio - rt) * cc ** (i + 1)
                else:
                    r = np.full(n, rt)
                v.ratio = float(r[-1])
                pos = v.pos + np.concatenate(([0.0], np.cumsum(r[:-1])))
                v.pos = float(pos[-1] + r[-1])
                seg = self._lead_interp(v, pos)
            if v.rel:
                env = v.env - np.arange(1, n + 1, dtype=np.float32) / v.rel_n
            else:
                env = v.env + np.arange(1, n + 1, dtype=np.float32) / 64.0
            env = np.clip(env, 0, 1)
            v.env = float(env[-1])
            seg *= (env * v.gain)[:, None]
            seg[:, 0] *= v.lg
            seg[:, 1] *= v.rg
            b[off:] += seg
            if not (v.rel and v.env <= 0.0) and v.pos < len(v.a) + (1e12 if v.l is not None else 0):
                keep.append(v)
        self.gvoices = keep

    def _lp_play(self, key, tr, ev, start, step):
        pos, kind, ident, gain, pan, dur, rel = ev[:7]
        if kind == "n" and tr.locks and any(l.get("slide") for l in tr.locks.values()):
            snd = tr.snd.get(ident)
            if snd is not None:
                st = int(round(pos)) % max(1, self.pats[key[0]].len)
                slide = bool(tr.locks.get(st, {}).get("slide"))
                self._glide_play(key, tr, ident, snd, gain, max(-1.0, min(1.0, pan)), dur, rel, start, step, slide,
                                 pos)
                return
        if kind == "n":
            snd = tr.snd.get(ident)
        elif kind == "b":
            snd = self.bass_bank.get(ident)
        elif tr.drum:
            snd, lv = self._drum_snd(tr, ident)
            base = DRUM_GAIN.get(ident, 0.75)
            if gain > base * 1.1:
                gain *= tr.acc / ACCENT_G
            elif gain < base * 0.9:
                gain *= tr.ghost / GHOST_G
            gain *= lv
            if tr.swing and pos == int(pos):
                if tr.swres == 8:
                    if int(pos) % 4 == 2:
                        start += tr.swing * 2 * step
                elif int(pos) % 2:
                    start += tr.swing * step
            if tr.human:
                start += random.uniform(-1.0, 1.0) * tr.human * 0.012 * self.sr
                gain *= 1.0 + random.uniform(-1.0, 1.0) * 0.15 * tr.human
                start = max(start, self.t)
            if snd is not None and tr.choke and ident == "hat":
                self._choke(key, int(start))
        else:
            snd = self.kit.get(ident)
        if snd is None:
            return
        if dur is None:
            gate = int(self.pats[key[0]].len * step) if snd[1] is not None else None
        else:
            gate = max(64, int(dur * step))
        v = self._voice(snd, gain, max(-1.0, min(1.0, pan)), int(start), "loop", ident if kind != "d" else None,
                        gate, int(rel * self.sr), srev=0, sdly=0)
        v.trk = key
        if kind == "d":
            v.part = ident

    def c_params(self, bpm=None, rel=None, sustains=None, spread=None, mode=None, quantize=None, rec_quant=None):
        if quantize is not None:
            self.quantize = quantize
        if rec_quant is not None:
            self.rec_quant = int(rec_quant)
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

    def c_delay_type(self, name, bus=0):
        self.buses[int(bus)].dly_type = name

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

    def _darken(self, b, y, key, lo, hi):
        L = 63
        frame = np.concatenate([b.tape_hist, y])
        b.tape_hist = frame[-(L - 1):]
        Y = np.fft.rfft(frame, 2048, axis=0)
        return np.fft.irfft(Y * self._lp_fir(key, lo, hi)[:, None], 2048, axis=0)[L - 1:L - 1 + len(y)].astype(np.float32)

    def _delay(self, b, x, N, sr):
        """Read the delay line, write input + feedback. Returns the wet signal."""
        typ = b.dly_type
        size = b.dbuf_len
        idx = np.arange(N)
        widx = (b.dw + idx) % size
        beat = 60.0 / self.bpm * sr

        def tap(samples):
            dd = int(max(N, min(samples, size - N)))
            return b.dbuf[(b.dw - dd + idx) % size]

        amt = float(self.dly_t)
        if typ == "Slapback":
            y = tap(0.105 * sr)
            fb_sig = y * 0.12
            wet = y * 1.1
        elif typ == "Multi-Tap":
            d = beat * b.dly_beats
            t1, t2, t3 = tap(d), tap(d * 1.5), tap(d * 2)
            wet = t1 * np.array([0.9, 0.35], np.float32) + t2 * np.array([0.35, 0.9], np.float32) + t3 * 0.55
            fb_sig = t3 * (0.15 + 0.35 * amt)
            y = wet
        else:
            y = tap(beat * b.dly_beats)
            if typ == "Straight":
                fb_sig = y * (0.3 + 0.45 * amt)
            elif typ == "Tape":
                fb_sig = np.tanh(self._darken(b, y, "tape", 90.0, 2600.0) * 1.6) / 1.6 * (0.35 + 0.47 * amt)
            elif typ == "Dub":
                fb_sig = np.tanh(self._darken(b, y, "dub", 220.0, 1500.0) * 2.0) / 2.0 * (0.55 + 0.33 * amt)
            else:                                   # Ping-Pong
                fb_sig = y[:, ::-1] * (0.3 + 0.45 * amt)
            wet = y
        b.dbuf[widx] = x + fb_sig
        b.dw = (b.dw + N) % size
        return wet

    def c_fx(self, rev, dly, beats, master):
        self.rev_t, self.dly_t, self.master_t = rev, dly, master
        self.buses[0].dly_beats = float(beats)

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

    def _pluck_wave(self, midi):
        """The harp note for midi, built once and kept: building it while you strum
        cost a block of audio per note on the Brick, which stuttered."""
        cache = self.__dict__.setdefault("_pluck_cache", {})
        w = cache.get(midi)
        if w is not None:
            return w
        sr = self.sr
        env = self.__dict__.get("_pluck_env")
        if env is None:
            n = int(1.8 * sr)
            t = (np.arange(n) / sr).astype(np.float32)
            env = self._pluck_env = (t, [np.exp(-t * k).astype(np.float32) for k in (1.6, 3.2, 5.5, 9.0)],
                                     np.minimum(1.0, t / 0.002).astype(np.float32))
        t, (e1, e2, e3, e4), att = env
        ph = (2 * np.pi * 440.0 * 2 ** ((midi - 69) / 12.0)) * t
        x = (np.sin(ph) * e1 + 0.45 * np.sin(2 * ph) * e2 + 0.18 * np.sin(3 * ph) * e3
             + 0.08 * np.sin(4.02 * ph) * e4)
        k = int(0.012 * sr)
        x[:k] += np.random.RandomState(int(midi)).uniform(-0.25, 0.25, k).astype(np.float32) * np.linspace(1, 0, k,
                                                                                                         dtype=np.float32)
        x = (x * att * 0.16).astype(np.float32)
        w = cache[midi] = np.ascontiguousarray(np.repeat(x[:, None], 2, 1))
        return w

    def c_pluck_warm(self, midis):
        """Queue harp notes to build ahead, one per audio block, so the first strum
        is as smooth as the rest."""
        todo = self.__dict__.setdefault("_pluck_todo", [])
        cache = self.__dict__.setdefault("_pluck_cache", {})
        for m in midis:
            if int(m) not in cache and int(m) not in todo:
                todo.append(int(m))

    def c_pluck(self, midi, vel=0.8, pan=0.0):
        """One harp-like plucked note, for the strum, through the reverb and delay."""
        w = self._pluck_wave(int(midi))
        self._voice((w, None), float(vel), float(pan), self.t, "pluck", srev=1.0, sdly=0.7,
                    rel=int(0.05 * self.sr))

    def c_click(self):
        lvl = self.metro_lvl
        self.metro_lvl = max(lvl, 0.3)
        self._click(self.t, True)
        self.metro_lvl = lvl

    def c_chord(self, notes, snd, revoice=False):
        mode = self.mode
        q = self.quantize and (self.drums_on or self.lp_on) and not revoice
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

    def _drum_track_playing(self):
        if not (self.route and self.lp_on):
            return False
        return any(tr.drum and tr.ev and not tr.mute for tr in self.pats[self.cur].tracks)

    def _on_step(self, s, at):
        if self.drums_on and self.drum_pat and not self._drum_track_playing():
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
        todo = self.__dict__.get("_pluck_todo")
        if todo:
            self._pluck_wave(todo.pop(0))                 # one harp note built ahead per block
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

        t1 = time.perf_counter()
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
            if v.tag != "drone" and (v.rel_at is None or v.rel_at >= t + N):
                # the common case, no release in this block: gain and pan in one multiply
                seg *= np.array((v.gain * v.lg, v.gain * v.rg), np.float32)
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
                continue
            g = np.full(n, v.gain, np.float32)
            if v.rel_at is not None and v.rel_at < t + N:
                x = (T[o:] - v.rel_at) / max(1, v.rel_len)
                env = np.clip(1 - x, 0, 1)
                g *= np.where(x < 0, 1.0, env * env)
                if v.rel_at + v.rel_len <= t + N:
                    v.done = True
            if v.tag == "drone":
                de = self._drone_env(v, T[o:], n)
                if de is not None:
                    g = g * de[0]
                    seg *= g[:, None]
                    seg[:, 0] *= v.lg * de[1]
                    seg[:, 1] *= v.rg * de[2]
                else:
                    seg *= g[:, None]
                    seg[:, 0] *= v.lg
                    seg[:, 1] *= v.rg
            else:
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
        t1b = time.perf_counter()
        if self.leads:
            if self.route and not self._seltr().drum:
                key = (self.cur, self.sel)
                b = tb.get(key)
                if b is None:
                    b = tb[key] = np.zeros((N, 2), np.float32)
                self._lead_render(b, N, sr)
            else:
                self._lead_render(mix, N, sr)
        if self.gvoices:
            self._glide_render(tb, N, sr)
        if self.amb:
            self._amb_render(mix, N, sr)
        if self.dvoices:
            if self.route and not self._seltr().drum:
                key = (self.cur, self.sel)
                b = tb.get(key)
                if b is None:
                    b = tb[key] = np.zeros((N, 2), np.float32)
                self._drone_render(b, N, sr)
            else:
                self._drone_render(mix, N, sr)

        # smoothed fx amounts (linear ramp across the block = no zipper noise)
        ramp = self._ramp(N)
        rv = self.rev + (self.rev_t - self.rev) * ramp
        dv = self.dly + (self.dly_t - self.dly) * ramp
        mv = self.master + (self.master_t - self.master) * ramp
        self.rev, self.dly, self.master = self.rev_t, self.dly_t, self.master_t

        t2 = time.perf_counter()
        # live synth: its rack, then its filter, then sends to the shared delay/reverb
        x = self._filter(self.live, self._rack(self.live, mix, N, sr))
        t3 = time.perf_counter()
        out = x.copy()
        rsend = [x * rv, np.zeros((N, 2), np.float32)]
        dsend = [x * dv, np.zeros((N, 2), np.float32)]
        # tracks: each through its own rack and filter, then level, pan, sends.
        # The selected track uses the live sends (Settings reverb/delay + right stick).
        selkey = (self.cur, self.sel) if self.route else None
        self._tails |= set(tb)
        self._ntracks = sum(1 for key in self._tails if tb.get(key) is not None)   # chains actually running
        for key in list(self._tails):
            tr = self.pats[key[0]].tracks[key[1]]
            b = tb.get(key)
            if b is None:
                tr.idle += 1
                if tr.idle > 2 and key != selkey and not self._cloud_alive(tr.ch):
                    self._tails.discard(key)
                    continue
                b = np.zeros((N, 2), np.float32)
            else:
                tr.idle = 0
            y = self._filter(tr.ch, self._rack(tr.ch, b, N, sr))
            p = tr.pan
            g = tr.vol
            y[:, 0] *= g * min(1.0, 1.0 - p)
            y[:, 1] *= g * min(1.0, 1.0 + p)
            out += y
            bi = tr.bus
            if key == selkey:
                rsend[bi] += y * rv
                dsend[bi] += y * dv
            else:
                if tr.rs:
                    rsend[bi] += y * tr.rs
                if tr.ds:
                    dsend[bi] += y * tr.ds
        self.rack_beat += N * self.bpm / 60.0 / sr
        t4 = time.perf_counter()
        # delay (type chosen in Settings), tempo synced except Slapback
        t5 = t4
        rin = [None, None]
        for bi, b in enumerate(self.buses):
            fed = bool(np.any(rsend[bi]) or np.any(dsend[bi]))
            if fed:
                b.tail = int(6.0 * sr / N)          # keep the tails ringing after the last send
            elif b.tail <= 0:
                continue                             # a silent bus costs nothing
            else:
                b.tail -= 1
            y = self._delay(b, dsend[bi], N, sr)
            out += y
            rin[bi] = rsend[bi] + y * 0.35
        t5 = time.perf_counter()
        b0, b1 = self.buses[0], self.buses[1]
        if b0.rev_name and b0.rev_name == b1.rev_name and rin[1] is not None:
            # both buses use the same reverb: one reverb hears both sends (same sound,
            # half the work); bus B's own reverb only rings out what it already held
            out += self._reverb(b0, rin[1] if rin[0] is None else rin[0] + rin[1]) * 1.1
            b0.tail = max(b0.tail, b1.tail)
            if getattr(b1, "rv_drain", 0) > 0:
                b1.rv_drain -= 1
                out += self._reverb(b1, np.zeros((N, 2), np.float32)) * 1.1
        else:
            for bi, b in enumerate(self.buses):
                if rin[bi] is not None:
                    out += self._reverb(b, rin[bi]) * 1.1
                    b.rv_drain = int(6.0 * sr / N)
        t6 = time.perf_counter()
        frame = np.concatenate([self.drum_hist, dmix])
        self.drum_hist = frame[N:]
        out = np.tanh((out + frame[:N]) * mv)

        self.t += N
        self.active = frozenset(v.midi for v in self.voices if v.rel_at is None and v.midi is not None)
        el = time.perf_counter() - t0
        nt = max(1, getattr(self, "_ntracks", 0))
        st = (("cmds+clock", t1 - t0), ("voices", t1b - t1), ("resampled", t2 - t1b), ("live fx", t3 - t2),
              ("tracks", t4 - t3),
              ("per_track", (t4 - t3) / nt), ("delay", t5 - t4), ("reverb", t6 - t5), ("total", el))
        pa = getattr(self, "_pacc", None)
        self._pacc = [(k, v * 1000 if pa is None else pa[i][1] * 0.97 + v * 1000 * 0.03) for i, (k, v) in enumerate(st)]
        self.prof = [(k, round(v, 2)) for k, v in self._pacc]
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
                # the loop: copy in slices and wrap, instead of building an index array
                ll = len(l)
                st = (pos + k - la) % ll
                while k < n:
                    c = min(n - k, ll - st)
                    out[k:k + c] = l[st:st + c]
                    k += c
                    st = 0
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
