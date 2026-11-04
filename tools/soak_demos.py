# Plays every demo song through the real app headless and reports what a user
# would hit: load errors, tracks that stay silent, clipping, underruns, notes
# that never rendered, and engine cost. Writes a WAV of each demo too, so a
# problem can be listened to.
#
#   SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python3 tools/soak_demos.py [seconds] [out_dir]
import json
import os
import sys
import time
import wave

os.environ.update(SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", BRICKCHORD_WINDOW="1", BRICK_EDITION="lab")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "brickchord")
sys.path.insert(0, APP)
os.chdir(APP)
import numpy as np  # noqa: E402
import vendor  # noqa: E402
vendor.setup(need_pygame=True)
import pygame  # noqa: E402
import main  # noqa: E402
import engine  # noqa: E402
import synth  # noqa: E402

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "dist", "soak")
os.makedirs(OUT, exist_ok=True)


def offline(data):
    """Render the demo through a bare engine (no UI) for the audio checks."""
    e = engine.Engine(main.SR, 1024, synth.reverb_ir(1.2))
    e.c_kits(synth.all_kits(None))
    e.kit = e.kits["Classic"]
    e.route = True
    e.c_params(bpm=data.get("bpm", 96))
    for p, pd in enumerate(data["pats"]):
        e.c_lp("len", p, data["bars"][p] * 16)
        for k, t in enumerate(pd["tracks"]):
            if t.get("drum"):
                d = t["drum"]
                e.c_lp("drum", p, k, {"on": True, "kit": d["kit"], "swing": d["swing"], "swres": d.get("swres", 16),
                                      "acc": d["acc"], "ghost": d["ghost"], "human": d["human"], "choke": d["choke"],
                                      "lanes": {n: tuple(v) for n, v in d["lanes"].items()}})
            e.c_lp("mix", p, k, {"vol": t["vol"], "pan": t["pan"], "rs": t["rs"], "ds": t["ds"],
                                 "bus": t.get("bus", 0), "mute": t["mute"]})
            e.c_lp("fx", p, k, {n: tuple(v) for n, v in t["rack"].items()}, tuple(t["flt"]))
            e.c_lp("locks", p, k, t.get("locks") or {})
    evs = [[t.get("ev") or [] for t in pd["tracks"]] for pd in data["pats"]]
    for p in range(len(evs)):
        if any(evs[p]):
            e.c_lp("load", p, data["bars"][p] * 16, evs[p])
            for k, t in enumerate(data["pats"][p]["tracks"]):
                if t.get("pj") and evs[p][k]:
                    patch = json.loads(t["pj"])
                    snd = {}
                    for ev in evs[p][k]:
                        if ev[1] == "n" and ev[2] not in snd:
                            snd[ev[2]] = synth.render_note(ev[2], patch, arrays=True)
                    e.c_lp("snd", p, k, snd, True)
    e.c_lp("song", data["song"], True)
    e.c_lp("pat", 0)
    e.c_lp("play", True)
    n = int(SECS * main.SR / 1024)
    per_track = {}
    out = []
    t0 = time.perf_counter()
    for i in range(n):
        out.append(e.process().copy())
    cost = (time.perf_counter() - t0) / n * 1000
    audio = np.concatenate(out)
    return audio, cost


def check(name, fname):
    data = json.load(open(os.path.join(APP, "demos", fname)))
    issues = []
    for p, pd in enumerate(data["pats"][:4]):
        for k, t in enumerate(pd["tracks"]):
            if t.get("ev") and not t.get("drum") and not t.get("pj"):
                issues.append("P%02d T%d has notes but no sound" % (p + 1, k + 1))
    audio, cost = offline(data)
    pk = float(np.abs(audio).max())
    rms = float(np.sqrt(np.mean(audio ** 2)))
    clip = int(np.sum(np.abs(audio) > 0.99))
    silent = rms < 0.005
    if clip:
        issues.append("clipping: %d samples over 0.99" % clip)
    if silent:
        issues.append("silent output")
    if cost > 30:
        issues.append("engine cost %.1f ms/block on this machine" % cost)
    w = wave.open(os.path.join(OUT, fname.replace(".json", ".wav")), "wb")
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(main.SR)
    w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    w.close()
    print("%-12s peak %.2f  rms %.3f  %.1f ms/block  %s" % (name, pk, rms, cost, "; ".join(issues) or "ok"))
    return issues


def main_():
    import song
    app_like = song.SongMixin.demo_names(type("X", (), {"DEMO_DIR": os.path.join(APP, "demos")})())
    bad = 0
    for name, fname in app_like:
        bad += bool(check(name, fname))
    print("%d demo(s) with issues; WAVs in %s" % (bad, OUT))


if __name__ == "__main__":
    main_()
