"""Runs the audio engine and the note renderer in their own processes.

Python threads share one interpreter lock, so on a slow handheld a busy
UI or a note render can starve the audio callback (silence + ALSA
underruns). Separate processes each get their own lock and their own CPU
time, so the audio thread only ever competes with itself.

Falls back to in-process threads if multiprocessing is unavailable.
"""
import collections
import json

import numpy as np
import os
import queue
import sys
import threading
import time
import traceback


# your own drum kits: samples/<kit name>/kick.wav, snare.wav, hat.wav ... next to the app
SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


def _log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- engine process
def _engine_main(cmd_q, req_q, sh, sr, block):
    try:
        import engine
        import synth
        try:
            os.nice(-5)
        except Exception:
            pass
        eng = engine.Engine(sr, block, synth.reverb_ir(1.2))
        cache = collections.OrderedDict()
        eng.post("drums", False, None, synth.kit_arrays())
        eng.post("kits", synth.all_kits(SAMPLES))
        eng.start("stream")
        sh["sink"].value = 1 if eng.sink == "callback" else 2
        _log("engine process: sink", eng.sink, "block", block)
        parent = os.getppid()
        while True:
            try:
                msg = cmd_q.get(timeout=0.03)
            except queue.Empty:
                msg = None
            sh["load"].value = eng.load
            sh["step"].value = eng.step16
            sh["under"].value = eng.underruns
            if os.getppid() != parent:
                break
            if msg is None:
                continue
            name = msg[0]
            if name == "quit":
                break
            if name == "snd":
                cache[msg[1]] = (msg[2], msg[3])
                while len(cache) > 260:
                    cache.popitem(last=False)
                continue
            if name == "chord":
                notes, keys, revoice = msg[1]
                snd, missing = {}, []
                for m, k in keys.items():
                    if k in cache:
                        snd[m] = cache[k]
                        cache.move_to_end(k)
                    else:
                        missing.append(k)
                if missing:
                    req_q.put(("force", missing))
                eng.post("chord", notes, snd, revoice)
                continue
            eng.post(name, *msg[1])
        eng.stop()
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()


# ---------------------------------------------------------------- renderer process
def _render_main(req_q, cmd_q, sh):
    try:
        import synth
        try:
            os.nice(5)
        except Exception:
            pass
        pending = collections.OrderedDict()
        done = set()
        parent = os.getppid()
        while True:
            try:
                msg = req_q.get(timeout=0.3) if not pending else req_q.get_nowait()
            except queue.Empty:
                msg = None
            if os.getppid() != parent:
                return
            if msg is not None:
                pri, keys = msg
                if pri == "quit":
                    return
                if pri == "reset":
                    pending.clear()
                for k in (reversed(keys) if pri in ("front", "force") else keys):
                    if pri == "force" or k not in done:
                        if pri == "lo":
                            if k not in pending:
                                pending[k] = 1
                        else:
                            pending[k] = 1
                            pending.move_to_end(k, last=False)
                sh["left"].value = len(pending)
                continue
            if pending:
                k, _ = pending.popitem(last=False)
                a, l = synth.render_note(k[0], json.loads(k[1]), arrays=True)
                cmd_q.put(("snd", k, a, l))
                done.add(k)
                sh["left"].value = len(pending)
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()


class ProcHost:
    def __init__(self, sr, block):
        import multiprocessing as mp
        ctx = mp.get_context("fork")
        self.cmd_q = ctx.Queue()
        self.req_q = ctx.Queue()
        self.sh = {"load": ctx.Value("d", 0.0, lock=False), "step": ctx.Value("i", 0, lock=False),
                   "under": ctx.Value("i", 0, lock=False), "left": ctx.Value("i", 0, lock=False),
                   "sink": ctx.Value("i", 0, lock=False)}
        self.pe = ctx.Process(target=_engine_main, args=(self.cmd_q, self.req_q, self.sh, sr, block), daemon=True)
        self.pr = ctx.Process(target=_render_main, args=(self.req_q, self.cmd_q, self.sh), daemon=True)
        self.pe.start()
        self.pr.start()
        self.kind = "process"

    def post(self, name, *args):
        self.cmd_q.put((name, args))

    def chord(self, notes, keys, revoice):
        self.req_q.put(("front", list(keys.values())))
        self.cmd_q.put(("chord", (notes, keys, revoice)))

    def request(self, pri, keys):
        self.req_q.put((pri, list(keys)))

    @property
    def load(self):
        return self.sh["load"].value

    @property
    def step16(self):
        return self.sh["step"].value

    @property
    def remaining(self):
        return self.sh["left"].value

    @property
    def underruns(self):
        return self.sh["under"].value

    @property
    def sink(self):
        return {0: "starting", 1: "callback", 2: "stream"}.get(self.sh["sink"].value, "?")

    def alive(self):
        return self.pe.is_alive()

    def stop(self):
        try:
            self.cmd_q.put(("quit", ()))
            self.req_q.put(("quit", []))
            self.pe.join(1.0)
            self.pr.join(0.5)
        except Exception:
            pass
        for p in (self.pe, self.pr):
            if p.is_alive():
                p.terminate()


class Ref(tuple):
    """A note key standing in for its sound: the audio process swaps in the
    actual samples, so the UI never ships sample arrays around."""


def _resample(e, r):
    """Pitch a rendered note by ratio r (attack plays once, loop wraps)."""
    a, l = e

    def rs(x, wrap):
        n = max(2, int(len(x) / r))
        pos = np.arange(n, dtype=np.float64) * r
        i0 = pos.astype(np.int64)
        fr = (pos - i0).astype(np.float32)[:, None]
        i1 = i0 + 1
        if wrap:
            i0 %= len(x)
            i1 %= len(x)
        else:
            i0 = np.minimum(i0, len(x) - 1)
            i1 = np.minimum(i1, len(x) - 1)
        return (x[i0] * (1 - fr) + x[i1] * fr).astype(np.float32)

    return (rs(a, False), None if l is None else rs(l, True))


# ---------------------------------------------------------------- fallback: threads
class LocalHost:
    """Audio streams from a dedicated thread in this process. Notes come from a
    disk cache when they have been made before; otherwise one note is rendered
    right away and background worker processes render the rest while you play.
    Until a note's real render arrives, a pitch-shifted neighbour stands in."""
    WORKERS = 1
    IDLE_SEC = 4.0              # only render after this long with nothing sounding
    KEEP_SOUNDS = 10            # sound folders kept in the disk cache

    def __init__(self, sr, block):
        import engine
        import synth
        self.synth = synth
        self.eng = engine.Engine(sr, block, synth.reverb_ir(1.2))
        self.eng.post("drums", False, None, synth.kit_arrays())
        self.eng.post("kits", synth.all_kits(SAMPLES))
        self.eng.start("stream")
        _log("local host: sink", self.eng.sink, "block", block)
        self.cache = {}
        self.todo = []
        self.misses = 0
        self.approx = {}
        self.pending = {}           # key -> file path the worker will write
        self.workers = []
        self.job_patch = None
        self.paused = False
        self.last_play = 0.0
        here = os.path.dirname(os.path.abspath(__file__))
        self.root = os.path.join(here, "cache")
        shared = os.path.join(os.path.dirname(here), "brickchord", "cache")
        if os.path.basename(here) != "brickchord" and not os.path.isdir(self.root) and os.path.isdir(shared):
            self.root = shared            # Bricklab next to Brickchord: share its rendered sounds
        self.kind = "local"
        self.lp_pending = {}
        self.lp_retry = 0.0

    # ---------------- disk cache
    def _dir(self, pjson):
        import hashlib
        d = os.path.join(self.root, hashlib.sha1(pjson.encode()).hexdigest()[:16])
        os.makedirs(d, exist_ok=True)
        return d

    def _path(self, k):
        return os.path.join(self._dir(k[1]), "%d.npz" % k[0])

    def _load(self, k):
        try:
            with np.load(self._path(k)) as z:
                a = z["a"].astype(np.float32)
                l = z["l"].astype(np.float32)
            return a, (l if len(l) else None)
        except Exception:
            return None

    def _prune(self, keep_dir):
        try:
            dirs = [os.path.join(self.root, x) for x in os.listdir(self.root)]
            dirs = sorted((x for x in dirs if os.path.isdir(x)), key=os.path.getmtime, reverse=True)
            dirs = [x for x in dirs if not os.path.exists(os.path.join(x, "factory"))]
            for x in dirs[self.KEEP_SOUNDS:]:
                if x != keep_dir:
                    for f in os.listdir(x):
                        os.remove(os.path.join(x, f))
                    os.rmdir(x)
        except Exception as e:
            _log("cache prune:", e)

    # ---------------- rendering
    def _render(self, k):
        e = self.cache.get(k)
        if e is None:
            e = self.synth.render_note(k[0], json.loads(k[1]), arrays=True)
            self.cache[k] = e
            try:
                import render_worker
                render_worker.save_note(np, self._path(k), e[0], e[1])
            except Exception as ex:
                _log("cache write:", ex)
        return e

    def _nearest(self, k):
        """Instant stand-in: the closest real note of the same sound, pitch-shifted
        by resampling. Used until the worker delivers the real render."""
        best = None
        for c in self.cache:
            if c[1] == k[1] and (best is None or abs(c[0] - k[0]) < abs(best[0] - k[0])):
                best = c
        if best is None:
            return None
        self.misses += 1
        return _resample(self.cache[best], 2.0 ** ((k[0] - best[0]) / 12.0))

    def _stop_workers(self):
        for w in self.workers:
            if w.poll() is None:
                w.kill()
        self.workers = []
        self.paused = False

    def _pause_workers(self, pause):
        """Background rendering competes with the audio thread for CPU and memory
        bandwidth, which crackles. So workers are frozen whenever anything is
        sounding and only run while the Brick is quiet."""
        if pause == self.paused:
            return
        import signal
        for w in self.workers:
            if w.poll() is None:
                try:
                    os.kill(w.pid, signal.SIGSTOP if pause else signal.SIGCONT)
                except Exception:
                    pass
        self.paused = pause

    def _start_workers(self, keys):
        """Render keys (all one sound) in background processes, spread-out
        pitches first so stand-ins are never far from a real note."""
        import subprocess
        self._stop_workers()
        if not keys:
            return
        pjson = keys[0][1]
        d = self._dir(pjson)
        by_pitch = sorted(set(k[0] for k in keys))
        first = by_pitch[::4]
        rest = [m for m in by_pitch if m not in first]
        centre = by_pitch[len(by_pitch) // 2]
        order = sorted(first, key=lambda m: abs(m - centre)) + sorted(rest, key=lambda m: abs(m - centre))
        app = os.path.dirname(os.path.abspath(__file__))
        for i in range(self.WORKERS):
            notes = order[i::self.WORKERS]
            if not notes:
                continue
            jf = os.path.join(d, "job%d.json" % i)
            with open(jf, "w") as f:
                json.dump({"patch": pjson, "dir": d, "notes": notes, "parent": os.getpid()}, f)
            self.workers.append(subprocess.Popen([sys.executable, "-B", os.path.join(app, "render_worker.py"), jf]))
        for k in keys:
            self.pending[k] = self._path(k)
        self.job_patch = pjson
        self.paused = False
        if self.eng.voices or time.time() - self.last_play < self.IDLE_SEC:
            self._pause_workers(True)
        _log("background render: %d notes, %d workers" % (len(keys), len(self.workers)))

    def poll(self):
        """Swap in notes the workers have finished. Cheap; call a few times a second."""
        quiet = not self.eng.voices and time.time() - self.last_play > self.IDLE_SEC
        self._pause_workers(not quiet)
        got = 0
        done = bool(self.workers) and all(w.poll() is not None for w in self.workers)
        for k, path in list(self.pending.items()):
            if os.path.exists(path):
                e = self._load(k)
                if e is not None:
                    self.cache[k] = e
                    got += 1
                del self.pending[k]
        if got:
            self.approx = {}        # rebuild stand-ins from the closer real notes
        if self.pending and done:
            _log("background render stopped with %d notes left" % len(self.pending))
            self.pending = {}
        if self.lp_pending and time.time() - self.lp_retry > 1.5:
            self.lp_retry = time.time()
            for (p, k), keys in list(self.lp_pending.items()):
                snd, missing = self.track_sounds(keys, standins=False)
                if snd:
                    self.eng.post("lp", "snd", p, k, snd, False)
                left = {kk[0]: kk for kk in missing}
                if left:
                    self.lp_pending[(p, k)] = left
                else:
                    del self.lp_pending[(p, k)]
        return got

    def rescan_kits(self):
        """Reload the WAV kits in samples/ (new folders show up without a relaunch)."""
        self.eng.post("kits", self.synth.all_kits(SAMPLES))

    def lp_sound(self, p, k, pj, replace=False):
        """Give track k of pattern p its notes in sound pj (stand-ins first if
        needed; the real notes are swapped in by poll() as they arrive)."""
        tr = self.eng.pats[p].tracks[k]
        midis = sorted({ev[2] for ev in list(tr.ev) if ev[1] == "n"})
        if not replace:
            midis = [m for m in midis if m not in tr.snd]
        if not midis or not pj:
            return
        snd, missing = self.track_sounds({m: (m, pj) for m in midis})
        self.eng.post("lp", "snd", p, k, snd, replace)
        if missing:
            self.lp_pending[(p, k)] = {kk[0]: kk for kk in missing}
        else:
            self.lp_pending.pop((p, k), None)

    # ---------------- host interface
    def post(self, name, *args):
        self.eng.post(name, *args)

    def chord(self, notes, keys, revoice):
        self.eng.post("chord", notes, self.resolve(keys), revoice)

    def resolve(self, keys):
        """Sounds for {midi: key}: cached, a resampled stand-in, or rendered now
        if the sound is brand new. Missing notes go to the background renderer."""
        self.last_play = time.time()
        self._pause_workers(True)
        snd = {}
        missing = []
        for m, k in keys.items():
            e = self.cache.get(k) or self.approx.get(k)
            if e is None:
                if not any(c[1] == k[1] for c in self.cache):
                    e = self._render(k)              # first note of a new sound
                else:
                    e = self._nearest(k)
                    self.approx[k] = e
                if k not in self.pending:
                    missing.append(k)
            snd[m] = e
        busy = any(w.poll() is None for w in self.workers)
        if missing and not busy and self.job_patch != missing[0][1]:
            self._start_workers([k for k in missing if k not in self.cache])
        return snd

    def track_sounds(self, keys, standins=True):
        """Notes for a looper track in any sound, {midi: key} -> ({midi: snd}, keys
        still missing). Comes from memory, then the disk cache; anything else gets
        a pitch-shifted stand-in now (if standins) and goes to the background
        renderer when it is free. Ask again later for the real notes."""
        snd, have, missing = {}, {}, []
        for m, k in keys.items():
            e = self.cache.get(k)
            if e is None and os.path.exists(self._path(k)):
                e = self._load(k)
            if e is None:
                missing.append(k)
                continue
            snd[m] = e
            have[k[0]] = e
        if missing and standins:
            if not have:
                k0 = sorted(missing)[len(missing) // 2]
                e = self.synth.render_note(k0[0], json.loads(k0[1]), arrays=True)
                try:
                    import render_worker
                    render_worker.save_note(np, self._path(k0), e[0], e[1])
                except Exception as ex:
                    _log("cache write:", ex)
                snd[k0[0]] = have[k0[0]] = e
                missing.remove(k0)
            for k in missing:
                near = min(have, key=lambda m: abs(m - k[0]))
                snd[k[0]] = _resample(have[near], 2.0 ** ((k[0] - near) / 12.0))
        todo = [k for k in missing if k not in self.pending]
        if todo and not any(w.poll() is None for w in self.workers):
            self._start_workers(todo)
        return snd, missing

    def request(self, pri, keys):
        if pri == "reset":
            self.todo = []
        self.todo += [k for k in keys if k not in self.cache and k not in self.todo]

    def preload(self, progress=None):
        """Get the queued notes ready: load what the disk cache has, render one
        note now if the sound is brand new, and hand the rest to the workers."""
        todo, self.todo = list(self.todo), []
        if not todo:
            return
        pjson = todo[0][1]
        for k in [k for k in self.cache if k[1] != pjson]:
            del self.cache[k]
        self.approx = {}
        self.pending = {}
        d = self._dir(pjson)
        os.utime(d)
        self._prune(d)
        have = [k for k in todo if os.path.exists(self._path(k))]
        for i, k in enumerate(have):
            e = self._load(k)
            if e is not None:
                self.cache[k] = e
            if progress and i % 4 == 0:
                progress(i + 1, len(todo))
        missing = [k for k in todo if k not in self.cache]
        if missing and not any(c[1] == pjson for c in self.cache):
            centre = sorted(missing)[len(missing) // 2]
            self._render(centre)
            missing.remove(centre)
        if progress:
            progress(len(todo), len(todo))
        if missing:
            self._start_workers(missing)
        else:
            self._stop_workers()
            self.job_patch = pjson

    load = property(lambda self: self.eng.load)
    step16 = property(lambda self: self.eng.step16)
    remaining = property(lambda self: len(self.pending))
    underruns = property(lambda self: self.eng.underruns)
    sink = property(lambda self: self.eng.sink)

    def alive(self):
        return True

    def stop(self):
        self._stop_workers()
        self.eng.stop()


# ---------------------------------------------------------------- split: audio in its own process
class _MTrack:
    def __init__(self):
        self.ev = []
        self.snd = set()


class _MPat:
    def __init__(self, n):
        self.len = 32
        self.tracks = [_MTrack() for _ in range(n)]


class Mirror:
    """What the UI can see of the engine in the audio process (refreshed from
    its snapshots). Same attribute names as engine.Engine."""
    def __init__(self, sr):
        import engine
        self.sr, self.t, self.bpm, self.load, self.underruns, self.step16 = sr, 0, 96.0, 0.0, 0, 0
        self.sink, self.voices, self.active, self.scope = "starting", [], frozenset(), None
        self.rev_t = self.dly_t = 0.0
        self.pats = [_MPat(engine.LOOP_TRACKS) for _ in range(engine.NPATS)]
        self.lp_on, self.lp_state, self.lp_rec, self.lp_rec_p, self.lp_pos, self.lp_abs = False, None, None, 0, -1, -1
        self.lp_step_at, self.lp_rec_start, self.lp_rec_end, self.lp_undo, self.lp_ver = 0, 0.0, 0.0, None, 0
        self.cur, self.cue, self.sel, self.song_on, self.song_row, self.song_rep = 0, None, 0, False, 0, 0
        self.left = self.misses = self.ncache = 0
        self.prof = None

    def update(self, s):
        self.t, self.sr, self.bpm, self.load = s["t"], s["sr"], s["bpm"], s["load"]
        self.underruns, self.step16, self.sink = s["under"], s["step16"], s["sink"]
        self.left, self.misses, self.ncache = s["left"], s["misses"], s["cache"]
        self.voices = [None] * s["nvoices"]
        self.active, self.scope = s["active"], s["scope"]
        self.rev_t, self.dly_t = s["rev_t"], s["dly_t"]
        (self.lp_on, self.lp_state, self.lp_rec, self.lp_rec_p, self.lp_pos, self.lp_abs, self.lp_step_at,
         self.lp_rec_start, self.lp_rec_end, u, self.lp_ver, self.cur, self.cue, self.sel,
         self.song_on, self.song_row, self.song_rep) = s["lp"]
        self.lp_undo = None if u is None else [u]
        self.prof = s.get("prof")
        for p, (n, tracks) in (s.get("pats") or {}).items():
            pat = self.pats[p]
            pat.len = n
            for tr, (ev, snd) in zip(pat.tracks, tracks):
                tr.ev, tr.snd = ev, set(snd)


class SplitHost:
    """The audio engine runs in audio_proc.py, a separate process, so the UI's
    drawing can't hold up the audio thread (Python lets only one thread run
    at a time inside a process)."""
    def __init__(self, sr, block):
        import subprocess
        from multiprocessing.connection import Pipe
        self.conn, child = Pipe(True)
        fd = child.fileno()
        app = os.path.dirname(os.path.abspath(__file__))
        self.proc = subprocess.Popen([sys.executable, "-u", "-B", os.path.join(app, "audio_proc.py"),
                                      str(fd), str(sr), str(block)], pass_fds=(fd,))
        child.close()
        if not self.conn.poll(20):
            self.proc.kill()
            raise RuntimeError("audio process did not start")
        msg = self.conn.recv()
        if msg[0] != "ready":
            raise RuntimeError("audio process: %r" % (msg,))
        self.eng = Mirror(sr)
        self.eng.sink = msg[1]
        self.kind = "split"
        self.cache = ()

    def _send(self, *msg):
        try:
            self.conn.send(msg)
        except (BrokenPipeError, OSError) as e:
            _log("audio process gone:", e)

    def pump(self):
        """Read the audio process's snapshots. Call every loop iteration."""
        try:
            while self.conn.poll():
                msg = self.conn.recv()
                if msg[0] == "state":
                    self.eng.update(msg[1])
        except (EOFError, OSError):
            pass

    def post(self, name, *args):
        self._send("post", name, args)

    def chord(self, notes, keys, revoice):
        self._send("chord", notes, keys, revoice)

    def resolve(self, keys):
        return {m: Ref(k) for m, k in keys.items()}

    def request(self, pri, keys):
        self._send("request", pri, list(keys))

    def preload(self, progress=None):
        self._send("preload")
        t0 = time.time()
        while time.time() - t0 < 120:
            if not self.conn.poll(0.1):
                continue
            msg = self.conn.recv()
            if msg[0] == "state":
                self.eng.update(msg[1])
            elif msg[0] == "progress" and progress:
                progress(msg[1], msg[2])
            elif msg[0] == "preloaded":
                return

    def lp_sound(self, p, k, pj, replace=False):
        self._send("lp_sound", p, k, pj, replace)

    def rescan_kits(self):
        self._send("rescan_kits")

    def poll(self):
        self.pump()
        return 0

    load = property(lambda self: self.eng.load)
    step16 = property(lambda self: self.eng.step16)
    remaining = property(lambda self: self.eng.left)
    underruns = property(lambda self: self.eng.underruns)
    misses = property(lambda self: self.eng.misses)
    sink = property(lambda self: self.eng.sink)

    def alive(self):
        return self.proc.poll() is None

    def stop(self):
        self._send("quit")
        try:
            self.proc.wait(2.0)
        except Exception:
            self.proc.kill()


def start(sr, block, mode="split"):
    if mode == "split":
        try:
            return SplitHost(sr, block)
        except Exception as e:
            _log("split audio process unavailable (%s); using local" % e)
    if mode == "process":
        try:
            return ProcHost(sr, block)
        except Exception as e:
            _log("multiprocessing unavailable (%s); using local" % e)
    return LocalHost(sr, block)
