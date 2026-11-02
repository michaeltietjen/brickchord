# Bricklab animated logo: a 4x4 step grid (16 steps, one pattern) drops in,
# the wordmark types on, a playhead plays one bar of drums from Bricklab's own
# 808 kit, and the downbeat lands with a chord and latches step 1 in teal.
#
# Outputs (in OUT):
#   Bricklab_logo_overlay_4444.mov  1920x1080 30 fps ProRes 4444 with alpha + 48 kHz audio
#   Bricklab_logo_preview.mp4       same on navy, H.264, for sharing
#   Bricklab_logo_sound.wav         the audio alone
#   bricklab-lockup.png             final frame, transparent
#   bricklab-icon.png               1024x1024 grid mark on cream
#
# Usage: python3 bricklab_logo.py <brickchord app folder> <Inter variable font> <out folder> [--sheet]
import math
import os
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

APP, FONT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
SHEET = "--sheet" in sys.argv
sys.path.insert(0, APP)
import synth  # noqa: E402

W, H, FPS, SEC = 1920, 1080, 30, 5.0
SS = 2                                   # supersampling
NF = int(FPS * SEC)
CREAM = (230, 229, 224)
WORD = (231, 222, 208)
TEAL = (41, 174, 184)
TINT = (190, 228, 231)
NAVY = (22, 36, 76)

KEY, GAP, RAD = 110, 16, 15
GRID = 4 * KEY + 3 * GAP
GX, GY = (W - GRID) // 2, 214
WORD_Y = GY + GRID + 52                  # top of the wordmark box
FONT_PX = 150

STEP0, STEP = 1.25, 0.125                # 120 BPM sixteenths
DOWN = STEP0 + 16 * STEP                 # the downbeat after one bar
HITS = {"kick": [0, 7, 10], "snare": [4, 12], "clap": [12], "hat": [2, 6, 10, 14], "ohat": [14], "rim": [9]}
HIT_STEPS = sorted({s for v in HITS.values() for s in v})


def ease_out_back(x, k=1.6):
    x = min(1.0, max(0.0, x)) - 1.0
    return 1 + (k + 1) * x ** 3 + k * x ** 2


def ease_out(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def mix(a, b, t):
    t = min(1.0, max(0.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def key_state(i, t):
    """(dy, scale, alpha, colour) for grid key i at time t."""
    r, c = divmod(i, 4)
    t_in = 0.05 + 0.04 * i
    p = (t - t_in) / 0.30
    if p <= 0:
        return None
    dy = (1 - ease_out_back(p)) * -70
    alpha = min(1.0, p / 0.55)
    scale = 1.0
    col = CREAM
    # the playhead: each step tints as it passes, hit steps flash teal and pop
    if STEP0 <= t < DOWN + 0.4:
        st = STEP0 + i * STEP
        age = t - st
        if 0 <= age < 0.45:
            if i in HIT_STEPS:
                col = mix(TEAL, CREAM, age / 0.32)
                scale = 1.0 + 0.10 * (1 - ease_out(age / 0.22))
            else:
                col = mix(TINT, CREAM, age / 0.22)
    # the downbeat: a ripple from step 1, and step 1 latches teal
    if t >= DOWN:
        d = math.hypot(r, c)
        age = t - DOWN - 0.035 * d
        if age > 0:
            scale *= 1.0 + 0.07 * math.sin(min(1.0, age / 0.32) * math.pi) * (1 - age / 1.2 if age < 1.2 else 0)
        if i == 0:
            col = mix(TINT, TEAL, ease_out((t - DOWN) / 0.12))
    return dy, scale, alpha, col


def load_font(px):
    f = ImageFont.truetype(FONT, px)
    try:
        f.set_variation_by_axes([32, 700])
    except Exception:
        pass
    return f


FONT_BIG = load_font(FONT_PX * SS)
WORDMARK = "bricklab"
WB = FONT_BIG.getbbox(WORDMARK)
WX = (W * SS - (WB[2] - WB[0])) // 2 - WB[0]


def frame(t, bg=None):
    im = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0) if bg is None else bg + (255,))
    d = ImageDraw.Draw(im)
    keys = []
    for i in range(16):
        s = key_state(i, t)
        if s is None:
            continue
        dy, scale, alpha, col = s
        r, c = divmod(i, 4)
        cx = GX + c * (KEY + GAP) + KEY / 2
        cy = GY + r * (KEY + GAP) + KEY / 2 + dy
        h = KEY * scale / 2
        keys.append((alpha, (cx - h, cy - h, cx + h, cy + h), col, scale))
    # draw keys on their own layer so alpha fades work over any background
    lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    for alpha, box, col, scale in keys:
        ld.rounded_rectangle([v * SS for v in box], radius=RAD * SS * scale, fill=col + (int(255 * alpha),))
    im = Image.alpha_composite(im, lay)
    # wordmark, typed on
    t_type = 0.78
    n = max(0, min(len(WORDMARK), int((t - t_type) / 0.06) + 1)) if t >= t_type else 0
    if n:
        d = ImageDraw.Draw(im)
        part = WORDMARK[:n]
        d.text((WX, WORD_Y * SS - WB[1]), part, font=FONT_BIG, fill=WORD + (255,))
        if t < 1.65 and (n < len(WORDMARK) or int(t * 6) % 2 == 0):
            x1 = WX + FONT_BIG.getlength(part) + 10 * SS
            d.rectangle([x1, WORD_Y * SS + 4 * SS, x1 + 9 * SS, WORD_Y * SS + (WB[3] - WB[1])],
                        fill=TEAL + (255,))
    return im.resize((W, H), Image.LANCZOS)


# ---------------------------------------------------------------- audio
def to48(x):
    n = int(len(x) * 48000 / synth.SR)
    return np.interp(np.arange(n) * synth.SR / 48000.0, np.arange(len(x)), x).astype(np.float32)


def audio():
    sr = 48000
    out = np.zeros((int(SEC * sr), 2), np.float32)
    kit = synth.builtin_kit("808")
    pans = {"hat": 0.25, "ohat": 0.25, "rim": -0.2, "clap": -0.1}
    gains = {"kick": 0.9, "snare": 0.7, "clap": 0.55, "hat": 0.5, "ohat": 0.45, "rim": 0.45}

    def put(x, at, g, pan=0.0):
        i = int(at * sr)
        j = min(len(out), i + len(x))
        if j <= i:
            return
        out[i:j, 0] += x[:j - i] * g * min(1.0, 1 - pan)
        out[i:j, 1] += x[:j - i] * g * min(1.0, 1 + pan)

    for part, steps in HITS.items():
        x = to48(kit[part])
        for s in steps:
            put(x, STEP0 + s * STEP + (0.012 if s % 2 else 0.0), gains[part], pans.get(part, 0.0))
    # the downbeat: kick, open hat and a Cmaj9 chord on Saw Pluck with a bell on top
    put(to48(kit["kick"]), DOWN, 1.0)
    put(to48(kit["ohat"]), DOWN, 0.35, 0.25)
    pluck = next(p for p in synth.PATCHES if p["name"] == "Saw Pluck")
    bell = next(p for p in synth.PATCHES if p["name"] == "Glass Bells")
    for k, (m, p, g) in enumerate([(48, pluck, 0.30), (55, pluck, 0.26), (59, pluck, 0.24), (62, pluck, 0.24),
                                   (64, pluck, 0.22), (76, bell, 0.16)]):
        a, _ = synth.render_note(m, p, arrays=True)
        x = np.stack([to48(a[:, 0]), to48(a[:, 1])], 1)
        i = int((DOWN + 0.008 * k) * sr)
        j = min(len(out), i + len(x))
        out[i:j] += x[:j - i] * g
    # gentle tail fade and a soft limit
    fade = int(0.6 * sr)
    out[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    out = np.tanh(out * 1.1) / np.tanh(1.1)
    out *= 0.89 / max(1e-6, float(np.abs(out).max()))
    return (np.clip(out, -1, 1) * 32767).astype(np.int16)


def main():
    os.makedirs(OUT, exist_ok=True)
    if SHEET:
        ts = [0.2, 0.45, 0.9, 1.3, 1.85, 2.6, 3.32, 3.6, 4.9]
        th = [frame(t, NAVY).resize((640, 360)) for t in ts]
        sheet = Image.new("RGB", (640 * 3, 360 * 3))
        for k, im in enumerate(th):
            sheet.paste(im.convert("RGB"), ((k % 3) * 640, (k // 3) * 360))
        sheet.save(os.path.join(OUT, "sheet.png"))
        return
    wav = os.path.join(OUT, "Bricklab_logo_sound.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(audio().tobytes())
    fdir = os.path.join(OUT, "_frames")
    os.makedirs(fdir, exist_ok=True)
    for f in range(NF):
        frame(f / FPS).save(os.path.join(fdir, "f%04d.png" % f), compress_level=1)
        if f % 30 == 0:
            print("frame", f, flush=True)
    last = frame(SEC - 1.0 / FPS)
    last.crop(last.getbbox()).save(os.path.join(OUT, "bricklab-lockup.png"))
    # the mark alone, on cream with dark keys, like brickchord-icon
    icon = Image.new("RGB", (1024 * SS, 1024 * SS), (233, 231, 226))
    di = ImageDraw.Draw(icon)
    k, g = 180, 28
    x0 = (1024 - (4 * k + 3 * g)) // 2
    for i in range(16):
        r, c = divmod(i, 4)
        x, y = x0 + c * (k + g), x0 + r * (k + g)
        di.rounded_rectangle([v * SS for v in (x, y, x + k, y + k)], radius=22 * SS,
                             fill=TEAL if i == 0 else (21, 21, 21))
    icon.resize((1024, 1024), Image.LANCZOS).save(os.path.join(OUT, "bricklab-icon.png"))
    ff = os.environ.get("FFMPEG", "ffmpeg")
    pat = os.path.join(fdir, "f%04d.png")
    subprocess.check_call([ff, "-v", "error", "-y", "-framerate", str(FPS), "-i", pat, "-i", wav,
                           "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
                           "-vendor", "apl0", "-c:a", "pcm_s16le", "-shortest",
                           os.path.join(OUT, "Bricklab_logo_overlay_4444.mov")])
    subprocess.check_call([ff, "-v", "error", "-y", "-f", "lavfi", "-i",
                           "color=c=0x%02x%02x%02x:s=%dx%d:r=%d:d=%g" % (NAVY + (W, H, FPS, SEC)),
                           "-framerate", str(FPS), "-i", pat, "-i", wav,
                           "-filter_complex", "[0][1]overlay=format=auto", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                           "-crf", "16", "-c:a", "aac", "-b:a", "192k", "-shortest",
                           os.path.join(OUT, "Bricklab_logo_preview.mp4")])
    for f in os.listdir(fdir):
        os.remove(os.path.join(fdir, f))
    os.rmdir(fdir)
    print("done", flush=True)


if __name__ == "__main__":
    main()
