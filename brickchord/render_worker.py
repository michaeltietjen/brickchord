# Brickchord background note renderer.
# Runs as its own process (its own CPU core, its own interpreter lock), so
# rendering never steals time from the audio thread. Each finished note is
# written to the disk cache; the app picks it up and swaps it in while you play.
import json
import os
import sys

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
import vendor  # noqa: E402
vendor.setup(need_pygame=False)


def main():
    job = json.load(open(sys.argv[1]))
    parent = int(job["parent"])
    try:
        os.nice(15)
    except Exception:
        pass
    import numpy as np
    import synth
    p = json.loads(job["patch"])
    d = job["dir"]
    for m in job["notes"]:
        if os.getppid() != parent:          # app quit or crashed
            return
        out = os.path.join(d, "%d.npz" % m)
        if os.path.exists(out):
            continue
        a, l = synth.render_note(m, p, arrays=True)
        save_note(np, out, a, l)


def save_note(np, out, a, l):
    tmp = out[:-4] + ".part"
    with open(tmp, "wb") as f:
        np.savez(f, a=a.astype(np.float16),
                 l=(l if l is not None else np.zeros((0, 2), np.float32)).astype(np.float16))
    os.replace(tmp, out)                     # appears all at once, never half-written


if __name__ == "__main__":
    main()
