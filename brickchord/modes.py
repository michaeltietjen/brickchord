# Brickchord instrument modes, mixed into the App class (see main.py).
#
#   Play       chords (the original Brickchord)
#   Lead       single-note melodies: buttons = scale notes, glide, stick bend/vibrato
#   Drone      sustained root/fifth/octave layer that keeps going under the others
#   Drums      buttons are drum pads
#   Looper     6 tracks that record what you play, each with its own effects
#   Effects    stackable effects rack with randomize
#
# Click the left stick (L3) for the mode wheel; tilt to pick, let go to choose.
import json
import math
import random
import sys
import time

import pygame

import engine
import synth

IMODES = ["Play", "Lead", "Drone", "Drums", "Looper", "Effects"]   # clockwise from the top
FX_ROWS = engine.Engine.FX_ORDER + ["Glide"]
RATES = engine.Engine.RATES
FX_DEFAULTS = {"Drive": (0.4, 3), "Lo-fi": (0.4, 3), "Chorus": (0.5, 5), "Flanger": (0.5, 6),
               "Vibrato": (0.3, 0), "Tremolo": (0.5, 1), "Gate": (0.7, 0), "Auto-Pan": (0.6, 4),
               "Wide": (0.6, 3), "Filter LFO": (0.6, 5), "Glide": (0.3, 0)}
DRUM_PADS = {"LEFT": "kick", "UP": "snare", "RIGHT": "hat", "DOWN": "ohat", "X": "clap", "A": "tom",
             "B": "rim", "Y": "shk"}
PAD_LABEL = {"kick": "KICK", "snare": "SNARE", "hat": "HAT", "ohat": "OPEN", "clap": "CLAP", "tom": "TOM",
             "rim": "RIM", "shk": "SHAKE"}
FX_ORDER = engine.Engine.FX_ORDER
LOOP_N = engine.LOOP_TRACKS
TFX_ROWS = ["Sound", "Level", "Pan", "Reverb", "Delay", "Filter", "Resonance"] + FX_ORDER
TRACK_COLS = [(255, 140, 66), (110, 200, 190), (255, 200, 90), (190, 140, 255), (120, 200, 110), (255, 120, 160)]
DRUM_ROW = {"kick": 0.85, "snare": 0.6, "clap": 0.55, "tom": 0.7, "rim": 0.45, "hat": 0.25, "ohat": 0.2, "shk": 0.35}


def M():
    return sys.modules["main"]


def e_len(app):
    e = app.lp_e()
    return e.lp_len if e else app.lp_bars * 16


def new_track():
    return {"name": None, "patch": None, "pj": None, "vol": 0.85, "pan": 0.0, "rs": 0.25, "ds": 0.0,
            "mute": False, "rack": {k: [False, FX_DEFAULTS[k][0], FX_DEFAULTS[k][1]] for k in FX_ORDER},
            "flt": [0.0, 0.0]}


class ModesMixin:
    # ------------------------------------------------------------ setup
    def modes_init(self):
        s = self.cfg.get("settings", {})
        self.imode = s.get("imode", "Play") if s.get("imode") in IMODES else "Play"
        if self.imode in ("Effects", "Looper"):
            self.imode = "Play"
        self.prev_imode = "Play"
        self.wheel_open = False
        self.wheel_sel = 0
        self.wheel_moved = False
        self.lead_stack = []
        self.lead_note = None
        self.lead_mod_last = (0.0, 0.0)
        self.drone_deg = None
        self.drone_notes = []
        self.pad_hit = {}
        self.last_pad = None
        self.fx_i = 0
        rack = self.cfg.get("rack") or {}
        self.rack = {}
        for k in FX_ROWS:
            amt, rate = FX_DEFAULTS[k]
            v = rack.get(k)
            self.rack[k] = [bool(v[0]), float(v[1]), int(v[2])] if v and len(v) == 3 else [False, amt, rate]
        lp = self.cfg.get("loop") or {}
        self.lp_bars = lp.get("bars", 2) if lp.get("bars") in (1, 2, 4, 8) else 2
        saved = lp.get("tracks") or []
        self.lp_meta = []
        for k in range(LOOP_N):
            t = new_track()
            if k < len(saved) and isinstance(saved[k], dict):
                for f in t:
                    if f in saved[k] and f != "rack":
                        t[f] = saved[k][f]
                for n, v in (saved[k].get("rack") or {}).items():
                    if n in t["rack"] and len(v) == 3:
                        t["rack"][n] = [bool(v[0]), float(v[1]), int(v[2])]
            self.lp_meta.append(t)
        self.lp_sel = 0
        self.lp_page = "tracks"
        self.tfx_i = 0
        self.lp_loaded = False
        self.lp_pending = {}
        self.lp_retry_t = 0.0
        self.lp_resolve_after = None
        self.lp_last_state = None
        self.lp_watch = None
        self.lp_arm_pj = None
        self.lp_was_empty = False
        self.lp_return = "Play"
        self.lp_clear_ask = None
        self.lp_clear_t = 0.0
        self.lp_dirty = False
        self.lp_save_t = 0.0
        self.lp_lane_cache = {}

    # ------------------------------------------------------------ mode wheel
    def wheel_toggle(self):
        if self.wheel_open:
            self.wheel_open = False
            return
        self.wheel_open = True
        self.wheel_sel = IMODES.index(self.imode)
        self.wheel_moved = False
        self.eng.post("click")

    def wheel_stick(self, x, y):
        mag = math.hypot(x, y)
        if mag > 0.6:
            ang = math.degrees(math.atan2(y, x))
            sel = int(round((90 - ang) / 60.0)) % len(IMODES)
            if sel != self.wheel_sel:
                self.wheel_sel = sel
                self.eng.post("click")
            self.wheel_moved = True
        elif mag < 0.3 and self.wheel_moved:
            self.wheel_open = False
            self.set_mode(IMODES[self.wheel_sel])

    def set_mode(self, new):
        if new == self.imode:
            return
        if self.imode == "Play":
            self.stop_chord()
            self.cur = None
            self.cur_btn = None
        elif self.imode == "Lead":
            self.lead_all_off()
        if new == "Effects":
            self.prev_imode = self.imode
        if new == "Looper" and self.imode != "Looper":
            self.lp_return = self.imode
            self.lp_page = "tracks"
        self.imode = new
        self.stick_mod = None
        self.flash(new.upper())

    # ------------------------------------------------------------ input routing
    def mode_input(self, name, down):
        """Handle a button in the non-Play modes. Returns True if it was used."""
        im = self.imode
        if im == "Lead":
            if name in M().CHORD_BUTTONS:
                (self.lead_press if down else self.lead_release)(name)
                return True
            return name in ("Y", "L1", "R1")
        if im == "Drone":
            if name in M().CHORD_BUTTONS:
                if down:
                    self.drone_toggle(M().CHORD_BUTTONS.index(name))
                return True
            return name in ("Y", "L1", "R1")
        if im == "Drums":
            if name in DRUM_PADS:
                if down:
                    self.pad(name)
                return True
            return name in ("L1", "R1")
        if im == "Looper":
            return self.lp_input(name, down)
        if im == "Effects":
            return self.fx_input(name, down)
        return False

    def mode_stick(self, x, y):
        if self.imode != "Lead":
            return
        bend = x * 2.0 if abs(x) > 0.15 else 0.0
        vib = min(1.0, (y - 0.2) / 0.7) if y > 0.2 else 0.0
        b0, v0 = self.lead_mod_last
        if abs(bend - b0) > 0.04 or abs(vib - v0) > 0.04 or (bend == 0 and b0 != 0) or (vib == 0 and v0 != 0):
            self.lead_mod_last = (bend, vib)
            self.eng.post("lead_mod", bend, vib)

    # ------------------------------------------------------------ lead
    def glide_time(self):
        g = self.rack["Glide"]
        return g[1] * 0.4 if g[0] else 0.0

    def lead_midi(self, btn):
        deg = M().CHORD_BUTTONS.index(btn)
        sc = M().SCALES[self.scale]
        h = self.inp.held
        m = 60 + self.key + sc[deg] + 12 * self.octave
        if self.key >= 7:
            m -= 12
        m += 12 if "Y" in h else 0
        m -= 12 if "L1" in h else 0
        m += 1 if "R1" in h else 0
        return m, deg

    def _snd(self, midis):
        if not hasattr(self.eng, "resolve"):
            return {}
        return self.eng.resolve({m: self.ckey(m) for m in midis})

    def lead_press(self, btn):
        m, deg = self.lead_midi(btn)
        snd = self._snd([m]).get(m)
        self.eng.post("lead_on", m, snd, self.glide_time())
        self.lead_stack = [e for e in self.lead_stack if e[0] != btn] + [(btn, m)]
        self.lead_note = m
        self.sounding = [m] + self.drone_notes
        self.hit_t, self.hit_big = time.perf_counter(), True

    def lead_release(self, btn):
        was_top = bool(self.lead_stack) and self.lead_stack[-1][0] == btn
        self.lead_stack = [e for e in self.lead_stack if e[0] != btn]
        if not was_top:
            return
        if self.lead_stack:                     # fall back to the note still held
            m = self.lead_stack[-1][1]
            self.eng.post("lead_on", m, self._snd([m]).get(m), self.glide_time())
            self.lead_note = m
            self.sounding = [m] + self.drone_notes
        else:
            self.eng.post("lead_off")
            self.lead_note = None
            self.sounding = list(self.drone_notes)

    def lead_all_off(self):
        self.lead_stack = []
        self.lead_note = None
        self.eng.post("lead_off")
        self.eng.post("lead_mod", 0.0, 0.0)
        self.lead_mod_last = (0.0, 0.0)

    # ------------------------------------------------------------ drone
    def drone_toggle(self, deg):
        if self.drone_deg == deg:
            self.drone_off()
            return
        sc = M().SCALES[self.scale]
        root = 36 + (self.key + sc[deg]) % 12 + 12 * max(0, self.octave)
        notes = [root, root + 7, root + 12, root + 19]
        if "Y" in self.inp.held:
            third = (sc[(deg + 2) % 7] - sc[deg]) % 12
            notes.append(root + 12 + third)
        self.eng.post("drone", notes, self._snd(notes))
        self.drone_deg = deg
        self.drone_notes = notes
        self.sounding = list(notes)
        self.hit_t, self.hit_big = time.perf_counter(), True

    def drone_off(self):
        self.eng.post("drone", [], {})
        self.drone_deg = None
        self.drone_notes = []
        self.sounding = []

    # ------------------------------------------------------------ drum pads
    def pad(self, btn):
        part = DRUM_PADS[btn]
        h = self.inp.held
        gain = 0.45 if "L1" in h else (1.25 if "R1" in h else 1.0)
        self.eng.post("hit", part, gain)
        self.pad_hit[btn] = time.perf_counter()
        self.last_pad = part
        self.hit_t, self.hit_big = time.perf_counter(), False

    # ------------------------------------------------------------ looper
    def lp_e(self):
        return getattr(self.eng, "eng", None)

    def patch_json(self, i):
        p = synth.edited_patch(synth.PATCHES[i], self.edits.get(str(i)))
        p["cutoff"] = p["cutoff"] * (2 ** self.tone)
        p["res"] = max(0.5, p["res"] + self.res)
        return json.dumps(p, sort_keys=True)

    def lp_push_track(self, k):
        m = self.lp_meta[k]
        self.eng.post("lp", "mix", k, {"vol": m["vol"], "pan": m["pan"], "rs": m["rs"], "ds": m["ds"],
                                       "mute": m["mute"]})
        self.eng.post("lp", "fx", k, {n: tuple(v) for n, v in m["rack"].items()}, tuple(m["flt"]))

    def lp_load(self):
        """Hand the saved tracks to the engine once it is running."""
        self.lp_loaded = True
        e = self.lp_e()
        if e is None:
            return
        self.eng.post("lp", "len", self.lp_bars * 16)
        saved = (self.cfg.get("loop") or {}).get("tracks") or []
        bass = set()
        for k in range(LOOP_N):
            self.lp_push_track(k)
            evs = saved[k].get("ev") if k < len(saved) else None
            if evs:
                self.eng.post("lp", "load", k, evs)
                bass.update(ev[2] for ev in evs if ev[1] == "b")
        if bass:
            self.ensure_bass(sorted(bass))
        self.lp_resolve_after = time.perf_counter() + 0.3     # once the engine has the events

    def lp_resolve(self, k, replace=False):
        pj = self.lp_meta[k]["pj"]
        if pj and hasattr(self.eng, "lp_sound"):
            self.eng.lp_sound(k, pj, replace)

    def looper_combo(self, name, down):
        """SELECT held + a button: run the looper without leaving your instrument."""
        if name in ("START", "L3", "R3"):
            return False
        if not down or name not in ("A", "B", "X", "Y", "UP", "DOWN"):
            return True                      # swallow the rest while SELECT is held
        e = self.lp_e()
        if e is None:
            self.flash("LOOPER NEEDS THE LOCAL AUDIO ENGINE")
            return True
        k = self.lp_sel
        if name == "A":
            self.lp_arm(k, stay=True)
        elif name == "B":
            if e.lp_undo:
                self.eng.post("lp", "undo")
                self.lp_dirty = True
                self.flash("UNDO / REDO TRACK %d" % (e.lp_undo[0] + 1))
            else:
                self.flash("NOTHING TO UNDO")
        elif name == "X":
            self.lp_toggle_play()
        elif name == "Y":
            m = self.lp_meta[k]
            m["mute"] = not m["mute"]
            self.lp_push_track(k)
            self.lp_dirty = True
            self.flash("TRACK %d %s" % (k + 1, "MUTED" if m["mute"] else "ON"))
        else:
            self.lp_sel = (k + (1 if name == "DOWN" else -1)) % LOOP_N
            tr = e.lp_tracks[self.lp_sel]
            nm = (self.lp_meta[self.lp_sel]["name"] or "") if tr.ev else "empty"
            self.flash("TRACK %d  %s" % (self.lp_sel + 1, nm.upper()))
        return True

    def lp_arm(self, k, stay=False):
        e = self.lp_e()
        if e is None:
            self.flash("LOOPER NEEDS THE LOCAL AUDIO ENGINE")
            return
        if e.lp_rec == k and e.lp_state:
            self.eng.post("lp", "arm", None)
            self.flash("RECORDING STOPPED")
            return
        m = self.lp_meta[k]
        live_pj = self.ckey(0)[1]
        if not e.lp_tracks[k].ev:
            # a new track starts with the sound and effects you hear right now
            m.update(name=synth.PATCHES[self.patch]["name"], patch=self.patch, pj=live_pj,
                     rack={n: list(self.rack[n]) for n in FX_ORDER}, flt=[round(x, 2) for x in e.live.flt_user],
                     rs=round(min(1.0, e.rev_t), 2), ds=round(min(1.0, e.dly_t), 2), mute=False)
            self.lp_push_track(k)
        self.lp_arm_pj = live_pj
        self.lp_watch = k
        self.lp_was_empty = not e.lp_tracks[k].ev
        self.eng.post("lp", "arm", k)
        if not stay:
            back = self.lp_return if self.lp_return in ("Play", "Lead", "Drone", "Drums") else "Play"
            self.set_mode(back)
        self.flash("TRACK %d %s: PLAY TO RECORD" % (k + 1, "ARMED" if self.lp_was_empty else "OVERDUB"))

    def lp_set_sound(self, k, d):
        m = self.lp_meta[k]
        i = ((m["patch"] if m["patch"] is not None else self.patch) + d) % len(synth.PATCHES)
        m.update(patch=i, name=synth.PATCHES[i]["name"], pj=self.patch_json(i))
        self.lp_resolve(k, replace=True)
        self.lp_dirty = True

    def lp_randomize(self, k):
        rack = self.lp_meta[k]["rack"]
        names = list(FX_ORDER)
        pick = random.sample(names, random.randint(1, 3))
        for n in names:
            rack[n][0] = n in pick
            if n in pick:
                rack[n][1] = round(random.uniform(0.25, 0.9), 2)
                rack[n][2] = random.randrange(len(RATES))
        self.lp_push_track(k)
        self.flash("TRACK %d: %s" % (k + 1, " + ".join(pick)))

    def lp_input(self, name, down):
        if not down:
            return name not in ("SELECT", "R3")
        if self.lp_page == "fx":
            return self.tfx_input(name)
        e = self.lp_e()
        k = self.lp_sel
        m = self.lp_meta[k]
        has = bool(e and e.lp_tracks[k].ev)
        any_has = bool(e and any(t.ev for t in e.lp_tracks))
        if name == "UP":
            self.lp_sel = (k - 1) % LOOP_N
        elif name == "DOWN":
            self.lp_sel = (k + 1) % LOOP_N
        elif name in ("LEFT", "RIGHT"):
            m["vol"] = round(max(0.0, min(1.0, m["vol"] + (0.05 if name == "RIGHT" else -0.05))), 2)
            self.lp_push_track(k)
            self.nudge = (time.perf_counter(), 1 if name == "RIGHT" else -1)
        elif name == "A":
            self.lp_arm(k)
            return True
        elif name == "B":
            now = time.perf_counter()
            if not has:
                return True
            self.eng.post("lp", "clear", k)
            self.lp_pending.pop(k, None)
            self.lp_dirty = True
            self.flash("TRACK %d CLEARED   SELECT+B UNDOES" % (k + 1))
        elif name == "Y":
            m["mute"] = not m["mute"]
            self.lp_push_track(k)
        elif name == "X":
            self.lp_page = "fx"
            self.tfx_i = 0
        elif name in ("L1", "R1"):
            d = 1 if name == "R1" else -1
            if not any_has and not (e and e.lp_state):
                opts = [1, 2, 4, 8]
                self.lp_bars = opts[(opts.index(self.lp_bars) + d) % len(opts)] if self.lp_bars in opts else 2
                self.eng.post("lp", "len", self.lp_bars * 16)
                self.flash("LOOP %d BAR%s" % (self.lp_bars, "" if self.lp_bars == 1 else "S"))
            elif has:
                self.lp_set_sound(k, d)
                self.flash("TRACK %d: %s" % (k + 1, m["name"].upper()))
        elif name == "START":
            self.lp_toggle_play()
        else:
            return False
        self.lp_dirty = True
        return True

    def lp_toggle_play(self):
        e = self.lp_e()
        if e is not None:
            on = not e.lp_on
            self.eng.post("lp", "play", on)
            self.flash("LOOP " + ("PLAY" if on else "STOP"))

    def tfx_value(self, k, row):
        m = self.lp_meta[k]
        if row == "Sound":
            return m["name"] or synth.PATCHES[self.patch]["name"]
        if row == "Level":
            return m["vol"]
        if row == "Pan":
            return m["pan"]
        if row == "Reverb":
            return m["rs"]
        if row == "Delay":
            return m["ds"]
        if row == "Filter":
            return m["flt"][0]
        if row == "Resonance":
            return m["flt"][1]
        return m["rack"][row]

    def tfx_input(self, name):
        k = self.lp_sel
        m = self.lp_meta[k]
        row = TFX_ROWS[self.tfx_i]
        fx = row in FX_ORDER
        if name == "UP":
            self.tfx_i = (self.tfx_i - 1) % len(TFX_ROWS)
            return True
        if name == "DOWN":
            self.tfx_i = (self.tfx_i + 1) % len(TFX_ROWS)
            return True
        if name == "B":
            self.lp_page = "tracks"
            return True
        if name == "START":
            self.lp_toggle_play()
            return True
        if name in ("L1", "R1"):
            d = 1 if name == "R1" else -1
            if fx:
                v = m["rack"][row]
                v[2] = (v[2] + d) % len(RATES)
            else:
                self.lp_sel = (k + d) % LOOP_N        # next / previous track
                return True
        elif name in ("LEFT", "RIGHT"):
            d = 1 if name == "RIGHT" else -1
            self.nudge = (time.perf_counter(), d)
            if row == "Sound":
                if self.lp_e() and self.lp_e().lp_tracks[k].ev:
                    self.lp_set_sound(k, d)
                return True
            if fx:
                v = m["rack"][row]
                v[1] = round(max(0.0, min(1.0, v[1] + 0.1 * d)), 2)
                v[0] = v[1] > 0.0
            elif row == "Level":
                m["vol"] = round(max(0.0, min(1.0, m["vol"] + 0.05 * d)), 2)
            elif row == "Pan":
                m["pan"] = round(max(-1.0, min(1.0, m["pan"] + 0.1 * d)), 2)
            elif row == "Reverb":
                m["rs"] = round(max(0.0, min(1.0, m["rs"] + 0.05 * d)), 2)
            elif row == "Delay":
                m["ds"] = round(max(0.0, min(1.0, m["ds"] + 0.05 * d)), 2)
            elif row == "Filter":
                m["flt"][0] = round(max(0.0, min(1.0, m["flt"][0] + 0.05 * d)), 2)
            elif row == "Resonance":
                m["flt"][1] = round(max(0.0, min(1.0, m["flt"][1] + 0.05 * d)), 2)
        elif name == "A":
            if fx:
                m["rack"][row][0] = not m["rack"][row][0]
            elif row == "Pan":
                m["pan"] = 0.0
            else:
                m["mute"] = not m["mute"]
        elif name == "X":
            self.lp_randomize(k)
            self.lp_dirty = True
            return True
        elif name == "Y":
            for n in FX_ORDER:
                m["rack"][n][0] = False
            self.flash("TRACK %d: EFFECTS OFF" % (k + 1))
        else:
            return False
        self.lp_push_track(k)
        self.lp_dirty = True
        return True

    def lp_tick(self, now):
        if not self.lp_loaded:
            self.lp_load()
        e = self.lp_e()
        if e is None:
            return
        if self.lp_resolve_after and now > self.lp_resolve_after:
            self.lp_resolve_after = None
            for k in range(LOOP_N):
                self.lp_resolve(k, replace=True)
        st = e.lp_state
        if st != self.lp_last_state:
            if st == "rec":
                self.flash("RECORDING TRACK %d" % ((e.lp_rec or 0) + 1))
            elif st is None and self.lp_last_state == "rec":
                k = self.lp_watch
                if k is not None and e.lp_tracks[k].ev:
                    self.lp_resolve(k, replace=self.lp_meta[k]["pj"] != self.lp_arm_pj)
                    nxt = None
                    if self.lp_was_empty and self.lp_sel == k:
                        # next layer: move to the next empty track so SELECT+A records it
                        for d in range(1, LOOP_N):
                            j = (k + d) % LOOP_N
                            if not e.lp_tracks[j].ev:
                                nxt = j
                                break
                    if nxt is not None:
                        self.lp_sel = nxt
                        self.flash("TRACK %d RECORDED   NEXT: TRACK %d" % (k + 1, nxt + 1))
                    else:
                        self.flash("TRACK %d RECORDED" % (k + 1))
                self.lp_dirty = True
            self.lp_last_state = st
        if self.lp_dirty and not st and now - self.lp_save_t > 3.0:
            self.lp_save_t = now
            self.lp_dirty = False
            self.save_cfg()

    def lp_snapshot(self):
        e = self.lp_e()
        tracks = []
        for k in range(LOOP_N):
            t = dict(self.lp_meta[k])
            t["ev"] = [ev[:7] for ev in list(e.lp_tracks[k].ev)] if e else []
            tracks.append(t)
        return {"bars": self.lp_bars, "tracks": tracks}

    # ------------------------------------------------------------ effects
    def push_rack(self):
        self.eng.post("rack", {k: tuple(v) for k, v in self.rack.items() if k != "Glide"})

    def fx_randomize(self):
        names = list(engine.Engine.FX_ORDER)
        pick = random.sample(names, random.randint(1, 4))
        for k in names:
            self.rack[k][0] = k in pick
            if k in pick:
                self.rack[k][1] = round(random.uniform(0.25, 0.9), 2)
                self.rack[k][2] = random.randrange(len(RATES))
        self.push_rack()
        self.flash("RANDOM: " + " + ".join(pick))

    def fx_input(self, name, down):
        if not down:
            return name not in ("SELECT", "START", "R3")
        k = FX_ROWS[self.fx_i]
        v = self.rack[k]
        if name == "UP":
            self.fx_i = (self.fx_i - 1) % len(FX_ROWS)
        elif name == "DOWN":
            self.fx_i = (self.fx_i + 1) % len(FX_ROWS)
        elif name == "A":
            v[0] = not v[0]
        elif name in ("LEFT", "RIGHT"):
            v[1] = round(max(0.0, min(1.0, v[1] + (0.1 if name == "RIGHT" else -0.1))), 2)
            v[0] = v[1] > 0.0
            self.nudge = (time.perf_counter(), 1 if name == "RIGHT" else -1)
        elif name in ("L1", "R1"):
            v[2] = (v[2] + (1 if name == "R1" else -1)) % len(RATES)
        elif name == "X":
            self.fx_randomize()
            return True
        elif name == "Y":
            for kk in self.rack:
                self.rack[kk][0] = False
            self.flash("ALL EFFECTS OFF")
        elif name == "B":
            self.set_mode(self.prev_imode if self.prev_imode != "Effects" else "Play")
            return True
        else:
            return False
        self.push_rack()
        return True

    def modes_tick(self, now):
        self.lp_tick(now)
        t = self.anim.get("_lead_preview")
        if t and now - t > 0.45:
            self.anim["_lead_preview"] = None
            if self.imode != "Lead" or not self.lead_stack:
                self.eng.post("lead_off")

    # ------------------------------------------------------------ drawing
    def draw_mode_chip(self, c, x, y):
        mm = M()
        label = self.imode.upper()
        w = self.f_small.size(label)[0] + 16
        pygame.draw.rect(c, mm.ACCENT if self.imode != "Play" else mm.BG, (x, y, w, 20), border_radius=10)
        self.text(c, label, self.f_small, mm.BG if self.imode != "Play" else mm.INK, (x + w // 2, y + 10), center=True)
        x += w + 6
        if self.drone_notes:
            t = "DRONE " + mm.NOTE_NAMES[self.drone_notes[0] % 12]
            w = self.f_small.size(t)[0] + 14
            b = 0.5 + 0.5 * math.sin(time.perf_counter() * 2.5)
            pygame.draw.rect(c, self.mix(mm.PANEL, mm.ACCENT2, 0.4 + 0.4 * b), (x, y, w, 20), border_radius=10)
            self.text(c, t, self.f_small, mm.BG, (x + w // 2, y + 10), center=True)
            x += w + 6
        e = self.lp_e()
        if e is not None and (e.lp_on or e.lp_state):
            if e.lp_state:
                t = "REC %d" % ((e.lp_rec or 0) + 1)
                blink = e.lp_state == "rec" or int(time.perf_counter() * 3) % 2 == 0
                col = (230, 70, 70) if blink else mm.PANEL
            else:
                t, col = "LOOP T%d" % (self.lp_sel + 1), mm.ACCENT2
            w = self.f_small.size(t)[0] + 14
            pygame.draw.rect(c, col, (x, y, w, 20), border_radius=10)
            self.text(c, t, self.f_small, mm.BG, (x + w // 2, y + 10), center=True)
            x += w + 6
        return x

    def mode_hint(self):
        return {"Lead": "Y oct+  L1 oct-  R1 sharp  L-stick bend/vibrato  L3 modes",
                "Drone": "tap a degree to drone, again to stop  Y adds 3rd  L3 modes",
                "Drums": "8 pads  L1 soft  R1 accent  L3 modes",
                "Looper": self.lp_hint(),
                "Effects": "A on/off  LEFT/RIGHT amount  L1/R1 rate  X random  Y all off  B back"}.get(self.imode)

    def mode_pills(self, h):
        if self.imode == "Lead":
            return [("Y  OCT UP", "Y" in h), ("L1  OCT DOWN", "L1" in h), ("R1  SHARP", "R1" in h),
                    ("GLIDE %s" % ("ON" if self.glide_time() else "OFF"), bool(self.glide_time()))]
        if self.imode == "Drone":
            return [("Y  ADD 3RD", "Y" in h), ("TAP = ON/OFF", False), ("PLAY ON TOP", False),
                    ("L3  LEAD/PLAY", False)]
        if self.imode == "Drums":
            e = self.lp_e()
            return [("Y  SHAKER", "Y" in h), ("L1  SOFT", "L1" in h), ("R1  ACCENT", "R1" in h),
                    ("LOOP REC", bool(e and e.lp_state))]
        return None

    def mode_tile(self, i, btn):
        mm = M()
        sc = mm.SCALES[self.scale]
        if self.imode == "Lead":
            name = mm.NOTE_NAMES[(self.key + sc[i]) % 12]
            return str(i + 1), name, any(e[0] == btn for e in self.lead_stack)
        if self.imode == "Drone":
            pc, iv, _ = mm.build_chord(self.key, self.scale, i, {})
            return mm.roman_for(i, iv), mm.NOTE_NAMES[pc % 12], self.drone_deg == i
        if self.imode == "Drums":
            part = DRUM_PADS[btn]
            return "PAD", PAD_LABEL[part], time.perf_counter() - self.pad_hit.get(btn, -9) < 0.15
        return None

    def mode_hero(self, c, now):
        mm = M()
        x = self.since(self.hit_t, 0.32)
        if self.imode == "Lead":
            if self.lead_note is not None:
                nm = mm.NOTE_NAMES[self.lead_note % 12] + str(self.lead_note // 12 - 1)
                self.draw_name(c, nm, self.f_huge, mm.BASE_W // 2 - 10, mm.L["name_y"], x)
                bend, vib = self.lead_mod_last
                sub = "lead" + ("  bend %+.1f" % bend if bend else "") + ("  vibrato" if vib else "")
                self.text(c, sub, self.f_big, mm.ACCENT, (mm.BASE_W // 2, mm.L["roman_y"]), center=True)
            else:
                self.text(c, "Lead", self.f_huge, mm.PANEL, (mm.BASE_W // 2, mm.L["name_y"]), center=True)
                self.text(c, "play a melody", self.f_med, mm.DIM, (mm.BASE_W // 2, mm.L["roman_y"]), center=True)
            return True
        if self.imode == "Drone":
            if self.drone_notes:
                nm = mm.NOTE_NAMES[self.drone_notes[0] % 12]
                b = 0.5 + 0.5 * math.sin(now * 1.6)
                self.text(c, nm, self.f_huge, self.mix(mm.INK, mm.ACCENT2, b * 0.5), (mm.BASE_W // 2 - 10, mm.L["name_y"]),
                          center=True)
                self.text(c, "drone" + ("  + 3rd" if len(self.drone_notes) > 4 else ""), self.f_big, mm.ACCENT2,
                          (mm.BASE_W // 2, mm.L["roman_y"]), center=True)
            else:
                self.text(c, "Drone", self.f_huge, mm.PANEL, (mm.BASE_W // 2, mm.L["name_y"]), center=True)
                self.text(c, "pick a root", self.f_med, mm.DIM, (mm.BASE_W // 2, mm.L["roman_y"]), center=True)
            return True
        if self.imode == "Drums":
            if self.last_pad and x < 1:
                self.draw_name(c, PAD_LABEL[self.last_pad], self.f_huge, mm.BASE_W // 2 - 10, mm.L["name_y"], x)
            else:
                self.text(c, "Drums", self.f_huge, mm.PANEL, (mm.BASE_W // 2, mm.L["name_y"]), center=True)
            self.text(c, "tap the pads", self.f_med, mm.DIM, (mm.BASE_W // 2, mm.L["roman_y"]), center=True)
            return True
        return False

    def lp_hint(self):
        if self.lp_page == "fx":
            return "LEFT/RIGHT value  A on/off  L1/R1 rate  X random  Y fx off  B back"
        e = self.lp_e()
        if e is not None and not any(t.ev for t in e.lp_tracks):
            return "A record  L1/R1 loop length  hold SELECT: +A rec  +X play  anywhere"
        return "A rec  B clear  Y mute  X fx  <> level  L1/R1 sound  SEL+B undo"

    def draw_page(self, c):
        if self.imode == "Looper":
            self.draw_looper(c)
        else:
            self.draw_fx_page(c)

    def lp_playpos(self, e):
        if not e.lp_on or e.lp_cur < 0:
            return None
        step = 60.0 / e.bpm / 4 * e.sr
        return (e.lp_cur + max(0.0, min(1.0, (e.t - e.lp_step_at) / step))) % e.lp_len

    def lp_lane(self, k, tr, w, h):
        """Cached picture of a track's notes (rebuilt only when it changes)."""
        mm = M()
        n = len(tr.ev)
        key = (n, w, h, e_len(self), self.lp_meta[k]["mute"])
        hit = self.lp_lane_cache.get(k)
        if hit and hit[0] == key:
            return hit[1]
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        L = float(e_len(self))
        col = TRACK_COLS[k % len(TRACK_COLS)]
        if self.lp_meta[k]["mute"]:
            col = mm.DIM
        evs = list(tr.ev)
        notes = [ev for ev in evs if ev[1] in ("n", "b")]
        if notes:
            lo = min(ev[2] for ev in notes)
            hi = max(ev[2] for ev in notes)
            span = max(12, hi - lo)
        for ev in evs[-400:]:
            x = int(ev[0] / L * w)
            if ev[1] == "d":
                yy = int(h * DRUM_ROW.get(ev[2], 0.5))
                pygame.draw.rect(surf, col, (x, yy - 2, 3, 4))
            else:
                yy = int(h - 3 - (ev[2] - lo) / span * (h - 6))
                ln = max(2, int((ev[5] or 0.5) / L * w))
                c2 = self.mix(col, mm.INK, 0.25) if ev[1] == "b" else col
                if x + ln > w:                                   # wraps around the loop
                    pygame.draw.rect(surf, c2, (x, yy - 1, w - x, 3))
                    pygame.draw.rect(surf, c2, (0, yy - 1, min(x, x + ln - w), 3))
                else:
                    pygame.draw.rect(surf, c2, (x, yy - 1, ln, 3))
        self.lp_lane_cache[k] = (key, surf)
        return surf

    def draw_looper(self, c):
        mm = M()
        e = self.lp_e()
        top = 46
        bottom = mm.L["tiles_y"] + mm.L["tile_h"]
        if e is None:
            self.text(c, "Looper needs the local audio engine", self.f_med, mm.DIM, (mm.BASE_W // 2, 200), center=True)
            return
        if self.lp_page == "fx":
            self.draw_track_fx(c, e)
            return
        playing = e.lp_on
        st = "PLAYING" if playing else "stopped"
        self.text(c, "LOOPER", self.f_med, mm.ACCENT, (20, top))
        self.text(c, "%d bar%s   %s" % (self.lp_bars, "" if self.lp_bars == 1 else "s", st), self.f_small,
                  mm.INK if playing else mm.DIM, (122, top + 6))
        top += 28
        rh = (bottom - top) // LOOP_N
        x0, x1 = 176, mm.BASE_W - 92
        lw = x1 - x0
        pp = self.lp_playpos(e)
        now = time.perf_counter()
        ty = self.sm("lp_sel", top + self.lp_sel * rh, 24)
        pygame.draw.rect(c, mm.PANEL, (10, int(ty) + 1, mm.BASE_W - 20, rh - 2), border_radius=8)
        nt, nd = self.nudge
        for k in range(LOOP_N):
            y = top + k * rh
            tr = e.lp_tracks[k]
            m = self.lp_meta[k]
            sel = k == self.lp_sel
            col = TRACK_COLS[k % len(TRACK_COLS)]
            rec = e.lp_rec == k and e.lp_state
            badge = pygame.Rect(18, y + rh // 2 - 13, 26, 26)
            if rec:
                blink = e.lp_state == "rec" or int(now * 3) % 2 == 0
                pygame.draw.rect(c, (230, 70, 70) if blink else mm.PANEL, badge, border_radius=13)
            else:
                pygame.draw.rect(c, col if tr.ev and not m["mute"] else mm.BG, badge, border_radius=13)
            self.text(c, str(k + 1), self.f_small, mm.BG if (rec or (tr.ev and not m["mute"])) else mm.DIM,
                      badge.center, center=True)
            nm = (m["name"] or "empty") if tr.ev else ("armed" if rec else "empty")
            self.text(c, nm[:14], self.f_small, mm.INK if (sel or tr.ev) else mm.DIM, (54, y + rh // 2 - 16))
            if rec:
                sub = "REC" if e.lp_state == "rec" else "play to start"
            elif tr.ev:
                kinds = set(ev[1] for ev in list(tr.ev))
                sub = " + ".join(x for x, f in (("notes", "n" in kinds), ("bass", "b" in kinds),
                                                ("drums", "d" in kinds)) if f)
                nfx = sum(1 for v in m["rack"].values() if v[0])
                sub += ("   fx %d" % nfx) if nfx else ""
            else:
                sub = "A to record" if sel else ""
            self.text(c, sub, self.f_small, (230, 90, 90) if rec else mm.DIM, (54, y + rh // 2 + 2))
            lane = pygame.Rect(x0, y + 5, lw, rh - 10)
            pygame.draw.rect(c, self.mix(mm.BG, mm.PANEL, 0.5), lane, border_radius=4)
            for b in range(1, self.lp_bars):
                bx = x0 + int(lw * b / self.lp_bars)
                pygame.draw.line(c, mm.PANEL, (bx, lane.top + 2), (bx, lane.bottom - 2))
            if tr.ev:
                c.blit(self.lp_lane(k, tr, lw, rh - 10), lane.topleft)
            if rec and e.lp_state == "rec" and pp is not None:
                a0 = e.lp_rec_start % e.lp_len
                done = min(1.0, max(0.0, (e.lp_cur - e.lp_rec_start) / e.lp_len))
                pygame.draw.rect(c, (230, 70, 70), (x0 + int(lw * a0 / e.lp_len), lane.bottom - 3,
                                                    max(2, int(lw * done)), 3))
            # level + mute
            vx = mm.BASE_W - 84
            pygame.draw.rect(c, mm.BG, (vx, y + rh // 2 - 4, 46, 8), border_radius=4)
            kick = int(4 * nd * (1 - self.since(nt, 0.18)) ** 2) if sel else 0
            fill = int(46 * self.sm("lpvol%d" % k, m["vol"], 18))
            if fill:
                pygame.draw.rect(c, mm.DIM if m["mute"] else col, (vx + kick, y + rh // 2 - 4, fill, 8),
                                 border_radius=4)
            if m["mute"]:
                self.text(c, "M", self.f_small, (230, 90, 90), (mm.BASE_W - 26, y + rh // 2 - 7))
        if pp is not None:
            px = x0 + int(lw * pp / e.lp_len)
            pygame.draw.line(c, mm.INK, (px, top + 2), (px, top + rh * LOOP_N - 2), 2)

    def draw_track_fx(self, c, e):
        mm = M()
        k = self.lp_sel
        m = self.lp_meta[k]
        top = 46
        bottom = mm.L["tiles_y"] + mm.L["tile_h"]
        col = TRACK_COLS[k % len(TRACK_COLS)]
        self.text(c, "TRACK %d" % (k + 1), self.f_med, col, (20, top))
        self.text(c, "effects, level and sends, after recording   L1/R1 track", self.f_small, mm.DIM,
                  (136, top + 6))
        y0 = top + 32
        rh = 24
        vis = max(6, (bottom - y0) // rh)
        first = max(0, min(self.tfx_i - vis // 2, len(TFX_ROWS) - vis))
        nt, nd = self.nudge
        ty = self.sm("tfx_sel", y0 + (self.tfx_i - first) * rh, 24)
        pygame.draw.rect(c, mm.PANEL, (14, int(ty) - 2, mm.BASE_W - 28, rh), border_radius=6)
        for r in range(first, min(len(TFX_ROWS), first + vis)):
            row = TFX_ROWS[r]
            y = y0 + (r - first) * rh
            sel = r == self.tfx_i
            fx = row in FX_ORDER
            v = self.tfx_value(k, row)
            on = v[0] if fx else True
            self.text(c, row, self.f_small if len(row) > 9 else self.f_med, mm.ACCENT if sel else (mm.INK if on else mm.DIM),
                      (28, y + 1))
            kick = int(6 * nd * (1 - self.since(nt, 0.18)) ** 2) if sel else 0
            if row == "Sound":
                self.text(c, "< %s >" % v, self.f_med, mm.INK, (300 + kick, y + 1))
                continue
            if fx:
                pill = pygame.Rect(170, y + 3, 42, rh - 8)
                pygame.draw.rect(c, mm.MOD_ON if on else mm.BG, pill, border_radius=8)
                self.text(c, "ON" if on else "off", self.f_small, mm.BG if on else mm.DIM, pill.center, center=True)
                amt = v[1]
            else:
                amt = v
            bx, bw = 230, 230
            pygame.draw.rect(c, mm.BG, (bx, y + rh // 2 - 4, bw, 8), border_radius=4)
            if row == "Pan":
                cx = bx + bw // 2
                px = int(cx + amt * bw / 2)
                pygame.draw.rect(c, mm.ACCENT, (min(cx, px), y + rh // 2 - 4, max(3, abs(px - cx)), 8), border_radius=4)
                val = "C" if abs(amt) < 0.05 else ("L%d" % round(-amt * 100) if amt < 0 else "R%d" % round(amt * 100))
            else:
                fill = int(bw * self.sm("tfx_%d_%s" % (k, row), amt, 18))
                if fill:
                    pygame.draw.rect(c, mm.ACCENT if on else mm.DIM, (bx, y + rh // 2 - 4, fill, 8), border_radius=4)
                val = RATES[v[2]][0] if fx and row not in ("Drive", "Lo-fi", "Wide") else "%d%%" % round(amt * 100)
            self.text(c, val, self.f_small, mm.INK if sel else mm.DIM, (mm.BASE_W - 28 + kick, y + 5), right=True)
        if first + vis < len(TFX_ROWS):
            self.text(c, "more", self.f_small, mm.DIM, (mm.BASE_W // 2, bottom - 4), center=True)

    def draw_fx_page(self, c):
        mm = M()
        top = 50
        self.text(c, "EFFECTS", self.f_med, mm.ACCENT, (20, top))
        self.text(c, "stack as many as you like", self.f_small, mm.DIM, (130, top + 6))
        bottom = mm.L["tiles_y"] + mm.L["tile_h"]
        rh = min(30, (bottom - top - 34) // len(FX_ROWS))
        y0 = top + 34
        ty = self.sm("fx_sel", y0 + self.fx_i * rh, 24)
        pygame.draw.rect(c, mm.PANEL, (14, int(ty) - 2, mm.BASE_W - 28, rh), border_radius=6)
        nt, nd = self.nudge
        for r, k in enumerate(FX_ROWS):
            on, amt, ri = self.rack[k]
            y = y0 + r * rh
            sel = r == self.fx_i
            self.text(c, k, self.f_med, mm.ACCENT if sel else (mm.INK if on else mm.DIM), (28, y + 2))
            pill = pygame.Rect(190, y + 3, 46, rh - 8)
            pygame.draw.rect(c, mm.MOD_ON if on else mm.BG, pill, border_radius=8)
            self.text(c, "ON" if on else "off", self.f_small, mm.BG if on else mm.DIM, pill.center, center=True)
            bx, bw = 254, 220
            pygame.draw.rect(c, mm.BG, (bx, y + rh // 2 - 4, bw, 8), border_radius=4)
            kick = int(6 * nd * (1 - self.since(nt, 0.18)) ** 2) if sel else 0
            fill = int(bw * self.sm("fxamt_" + k, amt, 18))
            if fill:
                pygame.draw.rect(c, mm.ACCENT if on else mm.DIM, (bx, y + rh // 2 - 4, fill, 8), border_radius=4)
            val = ("%.2fs" % (amt * 0.4)) if k == "Glide" else (RATES[ri][0] if k not in ("Drive", "Lo-fi", "Wide") else "")
            self.text(c, val, self.f_small, mm.INK if sel else mm.DIM, (mm.BASE_W - 28 + kick, y + 6), right=True)

    def draw_wheel(self, c):
        mm = M()
        a = self.sm("wheel", 1.0 if self.wheel_open else 0.0, 18)
        if a < 0.02:
            return
        self._ov.set_alpha(int(200 * a))
        c.blit(self._ov, (0, 0))
        cx, cy = mm.BASE_W // 2, mm.BASE_H // 2
        rad = int(150 * (0.7 + 0.3 * a))
        pygame.draw.circle(c, self.mix(mm.BG, mm.PANEL, a), (cx, cy), rad + 40)
        for i, nm in enumerate(IMODES):
            ang = math.radians(90 - i * 60)
            x, y = cx + math.cos(ang) * rad, cy - math.sin(ang) * rad
            sel = i == self.wheel_sel
            lv = self.sm("wsel%d" % i, 1.0 if sel else 0.0, 22)
            r = int(38 + 8 * lv)
            pygame.draw.circle(c, self.mix(mm.PANEL, mm.ACCENT, lv * a), (int(x), int(y)), r)
            self.text(c, nm, self.f_small if len(nm) > 6 else self.f_med, self.mix(mm.DIM, mm.BG, lv) if lv > 0.5 else mm.INK,
                      (int(x), int(y)), center=True)
        sx, sy = self.stick_xy
        pygame.draw.circle(c, mm.ACCENT, (int(cx + sx * 40), int(cy - sy * 40)), 9)
        self.text(c, "tilt to pick, let go to choose", self.f_small, mm.DIM, (cx, cy + 34), center=True)
