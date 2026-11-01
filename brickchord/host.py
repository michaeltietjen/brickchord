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
        self.root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
        self.kind = "local"

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
        a, l = self.cache[best]
        r = 2.0 ** ((k[0] - best[0]) / 12.0)

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

        self.misses += 1
        return (rs(a, False), None if l is None else rs(l, True))

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
        return got

    # ---------------- host interface
    def post(self, name, *args):
        self.eng.post(name, *args)

    def chord(self, notes, keys, revoice):
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
        self.eng.post("chord", notes, snd, revoice)
        busy = any(w.poll() is None for w in self.workers)
        if missing and not busy and self.job_patch != missing[0][1]:
            self._start_workers([k for k in missing if k not in self.cache])

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


def start(sr, block, mode="local"):
    if mode == "process":
        try:
            return ProcHost(sr, block)
        except Exception as e:
            _log("multiprocessing unavailable (%s); using local" % e)
    return LocalHost(sr, block)
