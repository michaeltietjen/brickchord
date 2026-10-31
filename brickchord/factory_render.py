"""Pre-render the factory sounds into Brickchord's disk cache (run on a computer,
then copy brickchord/cache to the handheld) so stock sounds load instantly."""
import hashlib, json, os, sys
from multiprocessing import Pool
APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
import numpy as np
import synth, render_worker

NOTES = range(int(os.environ.get("LO", 28)), int(os.environ.get("HI", 119)))          # every note octave -1 .. +1 can reach


def factory_patch(i):
    p = synth.edited_patch(synth.PATCHES[i], None)     # same as App.cur_patch() with no edits
    p["cutoff"] = p["cutoff"] * (2 ** 0.0)
    p["res"] = max(0.5, p["res"] + 0.0)
    return json.dumps(p, sort_keys=True)


def job(args):
    pj, d, m = args
    out = os.path.join(d, "%d.npz" % m)
    if not os.path.exists(out):
        a, l = synth.render_note(m, json.loads(pj), arrays=True)
        render_worker.save_note(np, out, a, l)
    return 1


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(APP, "cache")
    jobs = []
    for i in range(len(synth.PATCHES)):
        pj = factory_patch(i)
        d = os.path.join(root, hashlib.sha1(pj.encode()).hexdigest()[:16])
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "factory"), "w").write(synth.PATCHES[i]["name"] + "\n")
        jobs += [(pj, d, m) for m in NOTES]
    with Pool() as pool:
        n = sum(pool.imap_unordered(job, jobs, chunksize=4))
    print("rendered", n, "notes for", len(synth.PATCHES), "sounds into", root)
