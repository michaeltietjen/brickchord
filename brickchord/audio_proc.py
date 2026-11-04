# Brickchord audio process.
#
# The audio engine runs here, in its own process with its own interpreter
# lock, so drawing the screen can never make the sound stutter. The UI talks
# to it over a pipe: commands go in, a small state snapshot comes back about
# 30 times a second (playhead, levels, recorded notes for the looper page).
import os
import sys
import time
import traceback

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
import vendor  # noqa: E402
vendor.setup(need_pygame=True)


def resolve_refs(h, args):
    import host as H
    out = []
    for a in args:
        if isinstance(a, H.Ref):
            a = h.resolve({0: tuple(a)}).get(0)
        elif isinstance(a, dict) and a and any(isinstance(v, H.Ref) for v in a.values()):
            a = h.resolve({m: tuple(v) for m, v in a.items()})
        out.append(a)
    return out


def snapshot(h, sent):
    e = h.eng
    sc = getattr(e, "scope", None)
    snap = {"t": e.t, "sr": e.sr, "bpm": e.bpm, "load": e.load, "under": e.underruns, "step16": e.step16,
            "sink": e.sink, "left": len(h.pending), "misses": h.misses, "cache": len(h.cache),
            "nvoices": len(e.voices), "active": e.active, "scope": None if sc is None else sc.copy(),
            "rev_t": e.rev_t, "dly_t": e.dly_t,
            "lp": (e.lp_on, e.lp_state, e.lp_rec, e.lp_rec_p, e.lp_pos, e.lp_abs, e.lp_step_at, e.lp_rec_start,
                   e.lp_rec_end, e.lp_undo[0] if e.lp_undo else None, e.lp_ver, e.cur, e.cue, e.sel,
                   e.song_on, e.song_row, e.song_rep),
            "prof": getattr(e, "prof", None)}
    pats = {}
    for p, pat in enumerate(e.pats):
        if sent.get(p) != pat.ver:
            sent[p] = pat.ver
            pats[p] = (pat.len, [([ev[:7] for ev in list(tr.ev)], sorted(tr.snd)) for tr in pat.tracks])
    if pats:
        snap["pats"] = pats
    return snap


def main():
    from multiprocessing.connection import Connection
    fd, sr, block = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    conn = Connection(fd)
    try:
        os.nice(-5)
    except Exception:
        pass
    import host as H
    h = H.LocalHost(sr, block)
    conn.send(("ready", h.eng.sink))
    print("audio process: pid %d sink %s block %d" % (os.getpid(), h.eng.sink, block), flush=True)
    parent = os.getppid()
    last_snap = last_poll = 0.0
    sent = {}
    try:
        while True:
            if conn.poll(0.015):
                try:
                    msg = conn.recv()
                except EOFError:
                    break
                op = msg[0]
                try:
                    if op == "quit":
                        break
                    elif op == "post":
                        h.eng.post(msg[1], *resolve_refs(h, msg[2]))
                    elif op == "chord":
                        h.chord(msg[1], msg[2], msg[3])
                    elif op == "request":
                        h.request(msg[1], msg[2])
                    elif op == "preload":
                        h.preload(lambda i, n: conn.send(("progress", i, n)))
                        conn.send(("preloaded",))
                    elif op == "lp_sound":
                        h.lp_sound(msg[1], msg[2], msg[3], msg[4])
                    elif op == "rescan_kits":
                        h.rescan_kits()
                except Exception:
                    traceback.print_exc()
                    sys.stdout.flush()
                continue                       # drain commands before the next snapshot
            now = time.perf_counter()
            if now - last_poll > 0.3:
                last_poll = now
                h.poll()
                if os.getppid() != parent:
                    break
                if now - globals().get("_last_rss", 0) > 20:
                    globals()["_last_rss"] = now
                    try:
                        import resource
                        print("audio rss_mb %d" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024), flush=True)
                    except Exception:
                        pass
            if now - last_snap > 0.033:
                last_snap = now
                conn.send(("state", snapshot(h, sent)))
    except (BrokenPipeError, ConnectionResetError, EOFError):
        pass
    except Exception:
        traceback.print_exc()
    finally:
        h.stop()


if __name__ == "__main__":
    main()
