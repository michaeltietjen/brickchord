"""Render a Bricklab song file to audio without the app: no screen, no sound card,
no worker processes. The same engine and synth as the handheld, fed the same
commands the app sends when it opens a song and presses START, so a song sounds
the same here as it does on the Brick.

Used by the web editor (in the browser, through Pyodide) and from a computer:

    python3 songrender.py song.json out.wav [seconds]

render(data) returns a float32 array, shape (n, 2), at 22050 Hz."""
import json
import os
import sys

import numpy as np

import engine
import synth

SR = 22050
BLOCK = 1024
NP, NT, DT = 16, 6, 0          # patterns, tracks, the drum track (as in song.py)
BUSES = ((0, "Hall", "Ping-Pong", 0.75), (1, "Plate", "Tape", 1.0))   # the app's defaults


def song_seconds(data):
    """How long the song (or the first pattern, when song mode is off) lasts."""
    bpm = float(data.get("bpm") or 120)
    bars = data.get("bars") or [2] * NP
    step = 60.0 / bpm / 4
    if data.get("song_on") and data.get("song"):
        steps = sum(int(bars[int(p) % NP]) * 16 * max(1, int(n)) for p, n in data["song"])
    else:
        steps = int(bars[int(data.get("cur", 0)) % NP]) * 16
    return steps * step


def _tracks(data, p):
    pats = data.get("pats") or []
    trs = ((pats[p] if p < len(pats) else None) or {}).get("tracks") or []
    return [trs[k] if k < len(trs) and isinstance(trs[k], dict) else {} for k in range(NT)]


_KITS, _NOTES, _BASS = {}, {}, {}      # caches: re-rendering after an edit only makes what changed


def _note(m, pj):
    k = (m, pj)
    if k not in _NOTES:
        _NOTES[k] = synth.render_note(m, json.loads(pj), arrays=True)
    return _NOTES[k]


def forget_samples():
    """After the sample folder changes: kits and sample notes are made again."""
    _KITS.clear()
    for k in [k for k in _NOTES if '"sample"' in k[1]]:
        del _NOTES[k]


def build(data, samples_dir=None, sr=SR, block=BLOCK, log=None):
    """An engine with the song loaded and playing from the top."""
    say = log or (lambda *a: None)
    eng = engine.Engine(sr, block, synth.reverb_ir(1.2))
    folder = samples_dir or synth.SAMPLE_DIR
    if folder not in _KITS:
        _KITS[folder] = (synth.kit_arrays(), synth.all_kits(folder))
    eng.post("drums", False, None, _KITS[folder][0])
    eng.post("kits", _KITS[folder][1])
    bpm = float(data.get("bpm") or 120)
    eng.post("params", bpm, 1.4, True, 0, "Chord", True, 1)
    eng.post("fx", 0.0, 0.0, 0.75, 0.8)
    for b in BUSES:
        eng.post("busfx", *b)
    eng.post("bass", "Synth", 1.0)
    bars = data.get("bars") or [2] * NP
    bass = set()
    for p in range(NP):
        n = int(bars[p] if p < len(bars) else 2) * 16
        eng.post("lp", "len", p, n)
        trs = _tracks(data, p)
        evs = [list(t.get("ev") or []) for t in trs]
        if any(evs):
            eng.post("lp", "load", p, n, evs)
        for k, t in enumerate(trs):
            if k == DT and isinstance(t.get("drum"), dict):
                d = t["drum"]
                eng.post("lp", "drum", p, DT, {
                    "on": True, "kit": d.get("kit", "Classic"), "swing": d.get("swing", 0.0),
                    "swres": d.get("swres", 16), "acc": d.get("acc", 1.35), "ghost": d.get("ghost", 0.4),
                    "human": d.get("human", 0.0), "choke": d.get("choke", True),
                    "lanes": {nm: tuple(v) for nm, v in (d.get("lanes") or {}).items()}})
            eng.post("lp", "mix", p, k, {"vol": t.get("vol", 0.85), "pan": t.get("pan", 0.0),
                                         "rs": t.get("rs", 0.25), "ds": t.get("ds", 0.0),
                                         "bus": t.get("bus", 0), "mute": t.get("mute", False)})
            if t.get("rack"):
                eng.post("lp", "fx", p, k, {nm: tuple(v) for nm, v in t["rack"].items() if nm != "Glide"},
                         tuple(t.get("flt") or (0.0, 0.0)))
            eng.post("lp", "locks", p, k, t.get("locks") or {})
            bass.update(e[2] for e in evs[k] if e[1] == "b")
            pj = t.get("pj")
            midis = sorted({e[2] for e in evs[k] if e[1] == "n"})
            if pj and midis:
                snd = {m: _note(m, pj) for m in midis}
                eng.post("lp", "snd", p, k, snd, True)
                say("pattern %d track %d: %d notes" % (p + 1, k + 1, len(snd)))
    if bass:
        for m in bass:
            if 20 <= m <= 90 and m not in _BASS:
                _BASS[m] = synth.render_bass(m, sr)
        eng.post("bass", None, None, {m: _BASS[m] for m in sorted(bass) if m in _BASS})
    rows = data.get("song") or [[0, 1]]
    song_on = bool(data.get("song_on"))
    eng.post("lp", "song", [[int(r[0]) % NP, max(1, int(r[1]))] for r in rows], song_on)
    eng.post("lp", "pat", int(data.get("cur", 0)) % NP)
    if song_on:
        eng.post("lp", "play", True, 0)
    else:
        eng.post("lp", "play", True)
    return eng


def render(data, secs=None, samples_dir=None, tail=2.0, log=None):
    """The whole song (or the current pattern), plus a reverb tail, as float32 (n, 2)."""
    eng = build(data, samples_dir, log=log)
    secs = song_seconds(data) if secs is None else float(secs)
    total = int((secs + tail) * eng.sr)
    out, have = [], 0
    while have < total:
        if have >= int(secs * eng.sr) and eng.lp_on:
            eng.post("lp", "play", False)          # stop at the end, let the tail ring
        out.append(np.array(eng.process(), np.float32))
        have += eng.N
    return np.concatenate(out)[:total]


MACHINES = ("drums", "chord", "lead", "bass", "drone", "macro", "sample")


def catalog():
    """What the editor offers: each machine's sound names, the drum kits, the samples."""
    out = {mc: [p["name"] for p in synth.machine_bank(mc)] for mc in MACHINES if mc not in ("drums", "sample")}
    out["kits"] = synth.kit_names()
    out["samples"] = synth.sample_files()
    out["lanes"] = list(engine.DRUM_ORDER)
    out["fx"] = [n for n in engine.Engine.FX_ORDER if n != "Glide"]
    out["drum_gain"] = engine.DRUM_GAIN
    out["drum_pan"] = engine.DRUM_PAN
    return json.dumps(out)


def patch_json(machine, i, tone=0.0, res=0.0, smp=None):
    """A track's sound as the app stores it (song.py patch_json, without Sound
    Editor edits): returns (pj, name)."""
    if machine == "sample":
        files = synth.sample_files()
        base = synth.sample_patch(files[i % len(files)]) if files else dict(synth.SAMPLE_PATCH, name="no samples")
        base.update({k: v for k, v in (smp or {}).items() if k in synth.SAMPLE_PATCH})
        return json.dumps(base, sort_keys=True), base.get("name") or base.get("sample")
    bank = synth.machine_bank(machine)
    if machine == "macro":
        base = dict(bank[i % len(bank)])
        return json.dumps(base, sort_keys=True), base["name"]
    p = synth.edited_patch(bank[i % len(bank)], None)
    p["cutoff"] = p["cutoff"] * (2 ** tone)
    p["res"] = max(0.5, p["res"] + res)
    return json.dumps(p, sort_keys=True), p["name"]


def to_wav_bytes(a, sr=SR):
    import io
    import wave
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes((np.clip(a, -1, 1) * 32767).astype("<i2").tobytes())
    w.close()
    return buf.getvalue()


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src) as f:
        song = json.load(f)
    a = render(song, float(sys.argv[3]) if len(sys.argv) > 3 else None, log=print)
    with open(dst, "wb") as f:
        f.write(to_wav_bytes(a))
    print("wrote %s, %.1f s, peak %.2f" % (dst, len(a) / SR, float(np.abs(a).max())))
