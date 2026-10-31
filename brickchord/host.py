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
        eng.post("chime")
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
    """Single process: audio streams from a dedicated thread; every note is
    rendered up front (behind a loading bar) so nothing heavy runs during play."""
    def __init__(self, sr, block):
        import engine
        import synth
        self.synth = synth
        self.eng = engine.Engine(sr, block, synth.reverb_ir(1.2))
        self.eng.post("drums", False, None, synth.kit_arrays())
        self.eng.post("chime")
        self.eng.start("stream")
        _log("local host: sink", self.eng.sink, "block", block)
        self.cache = {}
        self.todo = []
        self.misses = 0
        self.approx = {}
        self.kind = "local"

    def _render(self, k):
        e = self.cache.get(k)
        if e is None:
            e = self.synth.render_note(k[0], json.loads(k[1]), arrays=True)
            self.cache[k] = e
            while len(self.cache) > 600:
                self.cache.pop(next(iter(self.cache)))
        return e

    def _nearest(self, k):
        """Instant stand-in for a note that was never pre-rendered: the closest
        cached note of the same sound, pitch-shifted by resampling. Rendering a
        note from scratch takes long enough on the handheld to starve the audio
        thread, which is what made sound drop out mid-play."""
        best = None
        for c in self.cache:
            if c[1] == k[1] and (best is None or abs(c[0] - k[0]) < abs(best[0] - k[0])):
                best = c
        if best is None or abs(best[0] - k[0]) > 7:
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

        e = (rs(a, False), None if l is None else rs(l, True))
        self.misses += 1
        if k not in self.todo:
            self.todo.append(k)      # render it properly at the next loading pause
        return e

    def post(self, name, *args):
        self.eng.post(name, *args)

    def chord(self, notes, keys, revoice):
        snd = {}
        for m, k in keys.items():
            e = self.cache.get(k) or self.approx.get(k)
            if e is None:
                e = self._nearest(k)
                if e is not None:
                    self.approx[k] = e
            if e is None:
                e = self._render(k)
            snd[m] = e
        self.eng.post("chord", notes, snd, revoice)

    def request(self, pri, keys):
        if pri == "reset":
            self.todo = []
        self.todo += [k for k in keys if k not in self.cache and k not in self.todo]

    def preload(self, progress=None):
        """Render everything queued; progress(done, total) is called between notes.
        Sounds that are no longer selected are dropped to save memory."""
        if self.todo:
            active = set(k[1] for k in self.todo)
            for k in [k for k in self.cache if k[1] not in active]:
                del self.cache[k]
        self.approx = {}
        total = len(self.todo)
        for i, k in enumerate(list(self.todo)):
            self._render(k)
            if progress:
                progress(i + 1, total)
        self.todo = []

    load = property(lambda self: self.eng.load)
    step16 = property(lambda self: self.eng.step16)
    remaining = property(lambda self: len(self.todo))
    underruns = property(lambda self: self.eng.underruns)
    sink = property(lambda self: self.eng.sink)

    def alive(self):
        return True

    def stop(self):
        self.eng.stop()


def start(sr, block, mode="local"):
    if mode == "process":
        try:
            return ProcHost(sr, block)
        except Exception as e:
            _log("multiprocessing unavailable (%s); using local" % e)
    return LocalHost(sr, block)
