"""Brickchop in the browser: the app's own Brickchop (chop.py) driven by the web
page instead of the handheld's buttons. Pads, groups, KEYS, the sequencer,
recording, quantize, the fader, punch-in FX, commit and the settings pages are
the same code the handheld runs; this file stands in for the app around it.

Sounds are built here, in the audio worker, as on the handheld (in its UI
process), so changing a pad's sound can make the audio pause for a moment."""
import json
import os
import sys
import time
import types

os.environ.setdefault("BRICK_EDITION", "chop")

try:
    import pygame  # noqa: F401  (only the handheld's drawing code uses it)
except ImportError:
    sys.modules["pygame"] = types.ModuleType("pygame")

import theory

if "main" not in sys.modules:
    _m = types.ModuleType("main")
    _m.SCALES, _m.NOTE_NAMES = theory.SCALES, theory.NOTE_NAMES
    _m.DELAY_TIMES = [("1/16", 0.25), ("1/8", 0.5), ("1/8 dotted", 0.75), ("1/4", 1.0), ("1/4 dotted", 1.5),
                      ("1/8 triplet", 1 / 3.0), ("1/4 triplet", 2 / 3.0)]
    _m.DELAY_TYPES = ["Ping-Pong", "Straight", "Tape", "Dub", "Slapback", "Multi-Tap"]
    sys.modules["main"] = _m
SCALES = theory.SCALES          # chop.py's SCALE_STEPS looks for SCALES in the module of the app's class

import edition

edition.EDITION, edition.CHOP, edition.AMBIENT, edition.PLAY, edition.LAB = "chop", True, False, False, False
edition.NAME = "Brickchop"

import chop  # noqa: E402
import synth  # noqa: E402

PAGES = ["Pad", "Group", "Seq", "Master"]
NO_WEB = {"Record", "Record length"}          # USB audio recording: the handheld only, for now


class _Eng:
    def __init__(self, c):
        self.c = c

    def post(self, op, *a):
        self.c.live.e.post(op, *a)


class Chop(chop.ChopMixin):
    def __init__(self, live):
        self.live = live
        self.eng = _Eng(self)
        self.cfg = {"chop_tutorial_done": True}
        self.key, self.scale = 9, "Minor"
        self.inp = types.SimpleNamespace(held=set())
        self.msg, self.msg_t = "", 0.0
        self.menu = False
        self.rev_type, self.dly_type, self.dly_time = "Hall", "Ping-Pong", 2
        self.rev, self.dly, self.volume = 0.25, 0.15, 0.8
        self.base_rev, self.base_dly = 0.25, 0.15
        self.chop_init()
        self.push_types()
        self.push_fx()

    # ---------------- what the app provides
    def flash(self, s):
        self.msg, self.msg_t = s, time.perf_counter()

    def save_cfg(self):
        pass

    def open_menu(self):
        pass

    def push_types(self):
        dt = sys.modules["main"].DELAY_TIMES
        self.eng.post("busfx", 0, self.rev_type, self.dly_type, dt[self.dly_time % len(dt)][1])

    def push_fx(self):
        lv = self.live
        lv.rev, lv.dly, lv.dly_time, lv.volume = self.rev, self.dly, self.dly_time, self.volume
        lv.push_fx()

    # ---------------- the page's controls
    def btn(self, name, down):
        name, down = str(name), bool(down)
        if down:
            self.inp.held.add(name)
        else:
            self.inp.held.discard(name)
        self.chop_handle(name, down)

    def hit(self, i, vel):
        """A pad with a velocity (a MIDI pad, or how hard the page was clicked)."""
        self.chop_hit(int(i) % 12, max(0.1, min(1.0, float(vel))))

    def group(self, g):
        g = int(g) % 4
        self.cgrp = self.cedit_g = g
        grp = self.cgroups[g]
        self.flash("GROUP %s  %s%s" % (chop.GROUPS[g], chop.GROUP_NAMES[g].upper(), "   KEYS" if grp.get("keys") else ""))

    def stick(self, x, y):
        self.chop_stick(float(x), float(y))

    def right(self, x, y):
        self.chop_punch(float(x), float(y))

    def set_key(self, key, scale):
        self.key, self.scale = int(key) % 12, scale if scale in theory.SCALES else "Minor"
        for g, grp in enumerate(self.cgroups):          # chords in KEYS follow the key
            if grp.get("keys") and grp.get("kplay") in ("triads", "sevenths"):
                self.chop_send_group(g)

    def midi(self, kind, note, vel):
        if kind == "on":
            self.chop_midi(("on", int(note), int(vel)))

    def demo(self, i):
        self.chop_song_load(1, chop.demo_by_index(int(i)))

    def add_wav(self, name):
        """A WAV the page just wrote into the samples folder: chop it onto group D."""
        self.cfiles = chop.chop_files()
        self.csrcs = chop.sources()
        self.chop_to_group(3, str(name))
        self.cgrp = self.cedit_g = 3

    def tick(self):
        self.chop_tick(time.perf_counter())

    def want(self):
        return '{"notes": [], "plucks": [], "inst": null}'

    def state(self):
        now = time.perf_counter()
        g = self.cgrp
        grp = self.cgroups[g]
        keys = bool(grp.get("keys"))
        if keys:
            kp = grp["pads"][grp.get("keys_pad", 0)]
            labels = [theory.NOTE_NAMES[(n) % 12] for n in range(12)]
            sub = [chop.src_label(kp.get("src"))] * 12
        else:
            labels = [chop.src_label(p.get("src")) for p in grp["pads"]]
            sub = [""] * 12
        pt = grp["pattern"]
        L = pt["bars"] * 16
        return json.dumps({
            "group": g, "groups": chop.GROUPS, "names": chop.GROUP_NAMES, "keys": keys,
            "kplay": dict(chop.KEY_PLAYS).get(grp.get("kplay", "notes"), "Notes"),
            "labels": labels, "sub": sub, "last": self.clast,
            "lit": [i for i in range(12) if now - self.clit.get((g, i), -9) < 0.15],
            "play": self.cplay, "rec": self.crec_on, "bpm": self.cbpm,
            "pos": (self.chop_pos() % L) if self.cplay else -1, "len": L,
            "hits": [[round(e[0], 3), e[1]] for e in pt["ev"]],
            "busy": [k for k in range(4) if self.cgroups[k]["pattern"]["ev"]],
            "msg": self.msg if now - self.msg_t < 3.0 else "",
            "head": self.chop_header_info(),
            "demos": [d[0] + ": " + d[1] for d in chop.DEMOS]})

    # ---------------- settings, the app's own pages
    def menu_rows(self, pg):
        rows = [(a, b) for a, b in self.chop_menu_items(pg) if a not in NO_WEB]
        return json.dumps([[str(a), str(b)] for a, b in rows])

    def menu_change(self, pg, name, d):
        self.chop_menu_change(pg, name, int(d))
        return self.menu_rows(pg)

    def menu_activate(self, pg, name):
        self.chop_menu_activate(pg, name)
        return self.menu_rows(pg)
