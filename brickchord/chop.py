# Brickchop: a K.O. II-style sampler on the Brickchord engine. Load a loop or any
# WAV, it is chopped onto 16 pads, and you play them with your thumbs.
#
#   < ^ v > Y X B A     pads 1 to 8 (the screen shows them in that order)
#   hold L1             pads 9 to 16
#   R1 + pad 1-4        bank A, B, C or D (each bank holds one chopped sample)
#   START               play the whole sample (again: stop)
#   SELECT              Settings: the sample, how it is chopped, pitch, level
#   right stick         filter and space, as in Brickchord
#
# Each bank's slices are cut here, in the UI process, and sent to the engine once;
# a pad press is then just a trigger, so playing never waits on anything.
import json
import math
import os
import time

import numpy as np
import pygame

import synth

BANKS = "ABCD"
PADS = ["LEFT", "UP", "DOWN", "RIGHT", "Y", "X", "B", "A"]
GLYPH = {"LEFT": "<", "UP": "^", "DOWN": "v", "RIGHT": ">", "Y": "Y", "X": "X", "B": "B", "A": "A"}
CHOPS = ["8 equal", "16 equal", "Transients"]


def M():
    import main
    return main


def chop_files():
    """Every WAV the Brick apps can see: Brickchop's own samples and Bricklab's,
    Brickchord's and Brickglide's, so your loops are already here."""
    d = synth.SAMPLE_DIR
    ports = os.path.dirname(os.path.dirname(d))
    dirs = [d] + [os.path.join(ports, a, "samples") for a in ("bricklab", "brickchord", "brickglide")]
    out, seen = [], set()
    for k, sd in enumerate(dirs):
        try:
            files = sorted(os.listdir(sd))
        except OSError:
            continue
        for f in files:
            if f.lower().endswith(".wav") and not f.startswith(".") and f not in seen:
                seen.add(f)
                out.append(f if k == 0 else os.path.join(sd, f))
    return out


def usb_capture_devices():
    """Sound cards that can record (USB audio from an SP-1, an OP-Z, a mixer...),
    from /proc/asound: [(card, device, name)]."""
    out = []
    try:
        names = {}
        with open("/proc/asound/cards") as f:
            for line in f:
                p = line.split("[", 1)
                if len(p) == 2 and p[0].strip().isdigit():
                    names[int(p[0].strip())] = p[1].split("]", 1)[1].split(" - ", 1)[-1].strip()
        with open("/proc/asound/pcm") as f:
            for line in f:
                if "capture" not in line:
                    continue
                cd = line.split(":", 1)[0].strip()
                card, dev = (int(v) for v in cd.split("-"))
                out.append((card, dev, names.get(card, "card %d" % card)))
    except Exception:
        pass
    return out


def short_name(path):
    s = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
    return (s[:26] + "\u2026") if len(s) > 27 else s


def find_onsets(x, n, sr):
    """Where the hits are: rises in short-time energy, the n strongest, kept apart."""
    hop = 256
    if len(x) < hop * 8:
        return [0]
    frames = len(x) // hop
    e = np.sqrt(np.mean(x[:frames * hop].reshape(frames, hop) ** 2, axis=1) + 1e-9)
    flux = np.maximum(0.0, np.diff(np.log(e), prepend=np.log(e[0])))
    flux[: 2] = 0
    gap = max(2, int(0.07 * sr / hop))                    # at least 70 ms apart
    order = np.argsort(flux)[::-1]
    picked = [0]
    for i in order:
        if flux[i] <= 0.05:
            break
        if all(abs(int(i) - p) >= gap for p in picked):
            picked.append(int(i))
        if len(picked) >= n:
            break
    return sorted(p * hop for p in picked)


class ChopMixin:
    # ------------------------------------------------------------ state
    def chop_init(self):
        st = self.cfg.get("chop") or {}
        self.cfiles = chop_files()
        default = next((f for f in self.cfiles if "drum" in f.lower() or "break" in f.lower()), None)
        if default is None and self.cfiles:
            default = self.cfiles[0]
        self.cbanks = []
        for b in range(4):
            d = {"sample": default if b == 0 else "", "chop": 1 if b == 0 else 0, "pitch": 0, "level": 0.9,
                 "choke": True, "reverse": False}
            if b < len(st.get("banks", [])):
                d.update(st["banks"][b])
            self.cbanks.append(d)
        self.cbank = int(st.get("bank", 0)) % 4
        self.csel = 0                                     # which bank the Pads page edits
        self.cwave = {}                                   # bank -> (min, max) per pixel for the screen
        self.cslices = {}                                 # bank -> [(start, end) in samples]
        self.clit = {}                                    # pad -> time it was hit
        self.caudition = False
        self.crec = None                                  # a recording in progress: {"until", "proc", "path"}
        self.crec_secs = int(st.get("rec_secs", 4))
        import shutil
        caps = usb_capture_devices()
        print("Brickchop: audio inputs %s, arecord %s" % (caps or "none", shutil.which("arecord") or "missing"),
              flush=True)
        for b in range(4):
            self.chop_load(b, quiet=True)

    def chop_state(self):
        return {"bank": self.cbank, "banks": self.cbanks, "rec_secs": self.crec_secs}

    # ------------------------------------------------------------ sampling from USB audio
    def chop_record(self):
        """Record from a USB audio input (whatever the Brick sees as a capture card)
        with arecord, into Brickchop's samples folder, then chop it onto the bank."""
        import shutil
        import subprocess
        caps = usb_capture_devices()
        if not caps:
            self.flash("NO USB AUDIO INPUT FOUND   PLUG ONE IN, THEN TRY AGAIN")
            print("Brickchop: record: no capture device", flush=True)
            return
        if not shutil.which("arecord"):
            self.flash("THIS FIRMWARE HAS NO ARECORD")
            print("Brickchop: record: arecord missing", flush=True)
            return
        card, dev, name = caps[-1]                        # the newest card: the one just plugged in
        os.makedirs(synth.SAMPLE_DIR, exist_ok=True)
        fn = "rec_%s.wav" % time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(synth.SAMPLE_DIR, fn)
        cmd = ["arecord", "-D", "plughw:%d,%d" % (card, dev), "-f", "S16_LE", "-r", "44100", "-c", "2",
               "-d", str(self.crec_secs), path]
        print("Brickchop: record:", " ".join(cmd), flush=True)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except Exception as ex:
            self.flash("COULD NOT START RECORDING: %s" % ex)
            return
        self.crec = {"until": time.perf_counter() + self.crec_secs, "proc": proc, "path": path, "file": fn,
                     "name": name, "bank": self.csel}
        self.menu = False

    def chop_tick(self, now):
        r = self.crec
        if r is None:
            return
        if r["proc"].poll() is None:
            left = max(0, r["until"] - now)
            self.flash("RECORDING FROM %s   %.0f s" % (r["name"].upper(), left + 0.4))
            return
        out = (r["proc"].stdout.read() or b"").decode("utf-8", "replace").strip()
        if out:
            print("Brickchop: arecord says:", out[-400:], flush=True)
        self.crec = None
        ok = os.path.exists(r["path"]) and os.path.getsize(r["path"]) > 4096
        print("Brickchop: recorded %s: %s bytes" % (r["file"], os.path.getsize(r["path"]) if ok else 0), flush=True)
        if not ok:
            self.flash("NOTHING CAME IN   SEE THE LOG")
            return
        self.cfiles = chop_files()
        b = r["bank"]
        self.cbanks[b]["sample"] = r["file"]
        self.cbank = b
        self.chop_load(b)
        self.flash("SAMPLED %s INTO BANK %s   %s" % (r["name"].upper(), BANKS[b], r["file"]))

    # ------------------------------------------------------------ cutting
    def chop_load(self, b, quiet=False):
        """Decode bank b's sample, cut it into 16 slices and send them to the engine."""
        d = self.cbanks[b]
        self.cslices[b], self.cwave[b] = [], None
        if not d.get("sample"):
            self.eng.post("chop_load", b, [], None)
            return
        x = synth._sample_audio(d["sample"])
        if x is None or len(x) < 64:
            if not quiet:
                self.flash("COULD NOT READ %s" % short_name(d["sample"]).upper())
            self.eng.post("chop_load", b, [], None)
            return
        x = np.asarray(x, np.float32)
        if d.get("reverse"):
            x = x[::-1].copy()
        if d.get("pitch"):
            r = 2 ** (d["pitch"] / 12.0)                  # pitch and speed together, like a sampler
            idx = np.arange(0, len(x) - 1, r)
            x = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
        sr = synth.SR
        mode = CHOPS[d.get("chop", 1) % len(CHOPS)]
        n = 8 if mode == "8 equal" else 16
        if mode == "Transients":
            starts = find_onsets(x, 16, sr)
        else:
            starts = [int(len(x) * i / n) for i in range(n)]
        bounds = [(s, starts[i + 1] if i + 1 < len(starts) else len(x)) for i, s in enumerate(starts)]
        bounds = bounds[:16]
        slices = []
        fi, fo = int(0.002 * sr), int(0.008 * sr)
        for s, e in bounds:
            seg = x[s:e].copy()
            if len(seg) > fi + fo:
                seg[:fi] *= np.linspace(0, 1, fi, dtype=np.float32)
                seg[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)
            slices.append(np.ascontiguousarray(np.repeat((seg * float(d.get("level", 0.9)))[:, None], 2, 1)))
        self.cslices[b] = bounds
        full = np.ascontiguousarray(np.repeat((x * float(d.get("level", 0.9)))[:, None], 2, 1))
        self.eng.post("chop_load", b, slices, full)
        # the picture: min and max of each column
        W = 600
        step = max(1, len(x) // W)
        cols = len(x) // step
        xs = x[: cols * step].reshape(cols, step)
        self.cwave[b] = (xs.min(axis=1), xs.max(axis=1), len(x))
        if not quiet:
            self.flash("BANK %s   %s   %s, %d PADS" % (BANKS[b], short_name(d["sample"]).upper(), mode.upper(),
                                                       len(slices)))

    # ------------------------------------------------------------ playing
    def chop_hit(self, pad, vel=1.0):
        b = self.cbank
        if not self.cslices.get(b):
            self.flash("BANK %s IS EMPTY   SELECT > PADS > SAMPLE" % BANKS[b])
            return
        if pad >= len(self.cslices[b]):
            return
        d = self.cbanks[b]
        self.eng.post("chop_hit", b, pad, float(vel), -0.25 + 0.5 * (pad % 8) / 7.0, bool(d.get("choke", True)))
        self.clit[(b, pad)] = time.perf_counter()

    def chop_handle(self, name, down):
        held = self.inp.held
        if name in PADS:
            if not down:
                return True
            i = PADS.index(name)
            if "R1" in held:
                if i < 4:
                    self.cbank = i
                    self.csel = i
                    d = self.cbanks[i]
                    self.flash("BANK %s   %s" % (BANKS[i], short_name(d["sample"]).upper() if d["sample"] else "EMPTY"))
                return True
            self.chop_hit(i + (8 if "L1" in held else 0))
            return True
        if name == "START":
            if down:
                self.caudition = not self.caudition
                self.eng.post("chop_full", self.cbank, self.caudition)
                self.flash("PLAYING BANK %s" % BANKS[self.cbank] if self.caudition else "STOPPED")
            return True
        if name in ("L1", "R1"):
            return True                                   # held as page and bank shifts
        return False

    def chop_midi(self, ev):
        """MIDI in: notes from C2 (36) up play pads 1 to 16, like a drum pad layout."""
        if ev[0] == "on":
            pad = (ev[1] - 36) % 16
            self.chop_hit(pad, max(0.25, ev[2] / 127.0))

    # ------------------------------------------------------------ settings
    def chop_menu_pages(self):
        return ["Pads", "Global", "FX"]

    def chop_menu_items(self, pg):
        d = self.cbanks[self.csel]
        return [("Bank", "%s%s" % (BANKS[self.csel], "  (playing)" if self.csel == self.cbank else "")),
                ("Sample", short_name(d["sample"]) if d["sample"] else "none"),
                ("Chop", CHOPS[d.get("chop", 1) % len(CHOPS)]),
                ("Pitch", "%+d semitones" % d.get("pitch", 0)),
                ("Level", "%d%%" % round(d.get("level", 0.9) * 100)),
                ("Choke", "On" if d.get("choke", True) else "Off"),
                ("Reverse", "On" if d.get("reverse") else "Off"),
                ("Files", "%d samples found" % len(self.cfiles)),
                ("Record", ("A records from %s" % usb_capture_devices()[-1][2]) if usb_capture_devices()
                 else "no USB audio input"),
                ("Record length", "%d s" % self.crec_secs)]

    def chop_menu_change(self, pg, name, d):
        bk = self.cbanks[self.csel]
        if name == "Bank":
            self.csel = (self.csel + d) % 4
            return
        if name == "Sample":
            opts = [""] + self.cfiles
            cur = bk["sample"] if bk["sample"] in opts else ""
            bk["sample"] = opts[(opts.index(cur) + d) % len(opts)]
        elif name == "Chop":
            bk["chop"] = (bk.get("chop", 1) + d) % len(CHOPS)
        elif name == "Pitch":
            bk["pitch"] = max(-12, min(12, bk.get("pitch", 0) + d))
        elif name == "Level":
            bk["level"] = round(max(0.1, min(1.5, bk.get("level", 0.9) + 0.05 * d)), 2)
        elif name == "Choke":
            bk["choke"] = not bk.get("choke", True)
            return
        elif name == "Reverse":
            bk["reverse"] = not bk.get("reverse")
        elif name == "Files":
            self.cfiles = chop_files()
            return
        elif name == "Record":
            return
        elif name == "Record length":
            opts = [2, 4, 8, 12]
            self.crec_secs = opts[(opts.index(self.crec_secs) + d) % len(opts) if self.crec_secs in opts else 1]
            return
        self.chop_load(self.csel)
        if name == "Sample" and bk["sample"]:
            self.cbank = self.csel                        # hear what you just picked
            self.chop_hit(0)

    def chop_menu_activate(self, pg, name):
        if name == "Record":
            self.chop_record()
            return
        if name == "Files":
            self.cfiles = chop_files()
            self.flash("%d SAMPLES FOUND" % len(self.cfiles))
        elif name == "Sample":
            self.cbank = self.csel
            self.chop_hit(0)

    def chop_header_info(self):
        d = self.cbanks[self.cbank]
        return "BANK %s   %s" % (BANKS[self.cbank], short_name(d["sample"]) if d["sample"] else "empty")

    # ------------------------------------------------------------ screen
    def draw_chop(self, c, now):
        mm = M()
        W, L = mm.BASE_W, mm.L
        b = self.cbank
        gx0, gx1, gy0, gy1 = 20, W - 20, 50, L["tiles_y"] - 14
        pygame.draw.rect(c, self.mix(mm.BG, mm.PANEL, 0.55), (gx0 - 8, gy0 - 6, gx1 - gx0 + 16, gy1 - gy0 + 12),
                         border_radius=10)
        wv = self.cwave.get(b)
        page = 8 if "L1" in self.inp.held else 0
        if wv is None:
            self.text(c, "Bank %s is empty" % BANKS[b], self.f_med, mm.DIM, ((gx0 + gx1) // 2, (gy0 + gy1) // 2 - 12),
                      center=True)
            self.text(c, "SELECT > Pads > Sample to load one", self.f_small, mm.DIM,
                      ((gx0 + gx1) // 2, (gy0 + gy1) // 2 + 16), center=True)
        else:
            mn, mx, n = wv
            cols = len(mn)
            cy, hh = (gy0 + gy1) // 2, (gy1 - gy0) // 2 - 6
            sl = self.cslices.get(b, [])
            # the slices: alternate tint, lit when hit, numbered
            for i, (s, e) in enumerate(sl):
                xa = gx0 + int((gx1 - gx0) * s / n)
                xb = gx0 + int((gx1 - gx0) * e / n)
                lv = max(0.0, 1.0 - (now - self.clit.get((b, i), -9)) / 0.35)
                on_page = page <= i < page + 8
                base = self.mix(mm.BG, mm.PANEL, 0.9 if i % 2 else 0.6)
                pygame.draw.rect(c, self.mix(base, mm.ACCENT, 0.55 * lv), (xa, gy0, max(1, xb - xa), gy1 - gy0))
                pygame.draw.line(c, self.mix(mm.BG, mm.DIM, 0.7), (xa, gy0), (xa, gy1), 1)
                if xb - xa > 14:
                    self.text(c, str(i + 1), self.f_small, mm.ACCENT2 if on_page else self.mix(mm.BG, mm.DIM, 0.6),
                              (xa + 4, gy0 + 2))
            pts_top, pts_bot = [], []
            for k in range(cols):
                x = gx0 + int((gx1 - gx0) * k / cols)
                pts_top.append((x, cy - int(mx[k] * hh)))
                pts_bot.append((x, cy - int(mn[k] * hh)))
            if len(pts_top) > 1:
                pygame.draw.polygon(c, mm.INK, pts_top + pts_bot[::-1])
        # pads
        tw, gap = 70, 6
        x0 = (W - (8 * tw + 7 * gap)) // 2
        th = L["tile_h"]
        for k, btn in enumerate(PADS):
            i = k + page
            lv = max(0.0, 1.0 - (now - self.clit.get((b, i), -9)) / 0.25)
            have = i < len(self.cslices.get(b, []))
            r = pygame.Rect(x0 + k * (tw + gap), L["tiles_y"], tw, th)
            pygame.draw.rect(c, self.mix(mm.PANEL if have else mm.BG, mm.ACCENT, lv), r, border_radius=10)
            self.text(c, str(i + 1), self.f_med, self.mix(mm.INK if have else mm.DIM, mm.BG, lv),
                      (r.centerx, r.y + th * 38 // 100), center=True)
            self.text(c, GLYPH[btn], self.f_small, self.mix(mm.DIM, mm.BG, lv), (r.centerx, r.y + th * 76 // 100),
                      center=True)

    def draw_chop_bar(self, c, now):
        """Where the keyboard is in Brickchord: the four banks and all 16 pads at a
        glance, the page you are on (hold L1 for 9-16) and how the bank is chopped."""
        mm = M()
        W, L = mm.BASE_W, mm.L
        ky, kh = L["kb_y"], L["kb_h"]
        pygame.draw.rect(c, mm.BG, (0, ky - 2, W, kh + 4))
        b = self.cbank
        x = 20
        for k in range(4):
            on = k == b
            r = pygame.Rect(x, ky + 4, 34, kh - 8)
            filled = bool(self.cslices.get(k))
            pygame.draw.rect(c, mm.ACCENT if on else self.mix(mm.BG, mm.PANEL, 0.95 if filled else 0.5), r,
                             border_radius=7)
            self.text(c, BANKS[k], self.f_small, mm.BG if on else (mm.INK if filled else mm.DIM), r.center, center=True)
            x += 40
        x += 14
        page = 8 if "L1" in self.inp.held else 0
        n = len(self.cslices.get(b, []))
        cw = (W - 20 - x - 120) / 16.0
        for i in range(16):
            lv = max(0.0, 1.0 - (now - self.clit.get((b, i), -9)) / 0.3)
            r = pygame.Rect(int(x + i * cw) + (6 if i >= 8 else 0), ky + 8, int(cw) - 3, kh - 16)
            on_page = page <= i < page + 8
            base = self.mix(mm.BG, mm.PANEL, 1.0 if i < n else 0.4)
            if on_page and i < n:
                base = self.mix(base, mm.ACCENT2, 0.18)
            pygame.draw.rect(c, self.mix(base, mm.ACCENT, lv), r, border_radius=4)
        d = self.cbanks[b]
        self.text(c, CHOPS[d.get("chop", 1) % len(CHOPS)].upper(), self.f_small, mm.DIM, (W - 20, ky + kh // 2 - 9),
                  right=True)
