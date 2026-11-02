# Brickchord song mode: patterns into songs, Digitone style.
#
#   16 patterns, each 1 to 8 bars, each with 6 tracks. A track records what
#   you play and keeps its own sound and effects, so every pattern can sound
#   different. Live playing always goes through the selected track of the
#   playing pattern: the Effects page, Settings > Sound / Reverb / Delay and
#   the right stick all act on that track, and what you hear while you play
#   is what it records.
#
#   Pages (L1/R1): PATTERN (mixer), GRID (step edit), SONG (chain).
#   Hold SELECT anywhere: +A record, +B undo/redo, +X play/stop, +Y mute,
#   +UP/DOWN track, +LEFT/RIGHT pattern.
import json
import os
import random
import sys
import time

import pygame

import engine
import synth

NP = engine.NPATS
NT = engine.LOOP_TRACKS
FX_ORDER = engine.Engine.FX_ORDER
RATES = engine.Engine.RATES
FX_DEFAULTS = {"Drive": (0.4, 3), "Lo-fi": (0.4, 3), "Chorus": (0.5, 5), "Flanger": (0.5, 6),
               "Vibrato": (0.3, 0), "Tremolo": (0.5, 1), "Gate": (0.7, 0), "Auto-Pan": (0.6, 4),
               "Wide": (0.6, 3), "Filter LFO": (0.6, 5), "Glide": (0.3, 0)}
TFX_ROWS = ["Sound", "Level", "Pan", "Reverb", "Delay", "Filter", "Resonance"] + FX_ORDER
TRACK_COLS = [(255, 140, 66), (110, 200, 190), (255, 200, 90), (190, 140, 255), (120, 200, 110), (255, 120, 160)]
DRUM_ROW = {"kick": 0.85, "snare": 0.6, "clap": 0.55, "tom": 0.7, "rim": 0.45, "hat": 0.25, "ohat": 0.2, "shk": 0.35}
DRUM_ABBR = {"kick": "BD", "snare": "SD", "clap": "CP", "tom": "LT", "rim": "RS", "hat": "CH", "ohat": "OH", "shk": "SH"}
PAGES = ["pattern", "grid", "song"]
BARS = [1, 2, 4, 8]
REC = (230, 70, 70)
SONG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brickchord_song.json")


def M():
    return sys.modules["main"]


def new_track():
    return {"name": None, "patch": None, "tone": 0.0, "res": 0.0, "pj": None, "vol": 0.85, "pan": 0.0,
            "rs": 0.25, "ds": 0.0, "mute": False,
            "rack": {k: [False, FX_DEFAULTS[k][0], FX_DEFAULTS[k][1]] for k in FX_ORDER + ["Glide"]},
            "flt": [0.0, 0.0]}


def copy_track(m):
    t = dict(m)
    t["rack"] = {k: list(v) for k, v in m["rack"].items()}
    t["flt"] = list(m["flt"])
    return t


def note_name(m):
    return M().NOTE_NAMES[m % 12] + str(m // 12 - 1)


class SongMixin:
    # ------------------------------------------------------------ setup / storage
    def song_init(self):
        self.pm = [[new_track() for _ in range(NT)] for _ in range(NP)]
        self.pbars = [2] * NP
        self.song_rows = [[0, 1]]
        self.song_on = False
        self.song_sel = 0
        self.sg_page = "pattern"
        self.lp_sel = 0
        self.grid_x = 0
        self.tfx_i = 0
        self.y_used = False
        self.lp_loaded = False
        self.lp_return = "Play"
        self.lp_last_state = None
        self.lp_watch = None
        self.lp_was_empty = False
        self.lp_dirty = False
        self.lp_save_t = 0.0
        self.lp_lane_cache = {}
        self.lp_resolve_q = {}
        self.sel_key = None
        self.start_p = 0
        self._saved_ev = None
        data = None
        try:
            with open(SONG_FILE) as f:
                data = json.load(f)
        except Exception:
            data = None
        if data is None and self.cfg.get("loop"):
            # the earlier looper becomes pattern 1
            lp = self.cfg["loop"]
            data = {"bars": [lp.get("bars", 2)], "pats": [{"tracks": lp.get("tracks") or []}]}
        self._saved = data or {}
        for p, b in enumerate((data or {}).get("bars") or []):
            if p < NP and b in BARS:
                self.pbars[p] = b
        for p, pd in enumerate((data or {}).get("pats") or []):
            if p >= NP:
                break
            for k, sv in enumerate((pd or {}).get("tracks") or []):
                if k >= NT or not isinstance(sv, dict):
                    continue
                t = self.pm[p][k]
                for f in t:
                    if f in sv and f != "rack":
                        t[f] = sv[f]
                for n, v in (sv.get("rack") or {}).items():
                    if n in t["rack"] and len(v) == 3:
                        t["rack"][n] = [bool(v[0]), float(v[1]), int(v[2])]
        if data:
            rows = data.get("song") or [[0, 1]]
            self.song_rows = [[int(r[0]) % NP, max(1, int(r[1]))] for r in rows] or [[0, 1]]
            self.song_on = bool(data.get("song_on", False))
            self.start_p = int(data.get("cur", 0)) % NP

    def lp_e(self):
        return getattr(self.eng, "eng", None)

    def song_snapshot(self):
        e = self.lp_e()
        pats = []
        for p in range(NP):
            tr = []
            for k in range(NT):
                t = copy_track(self.pm[p][k])
                t["ev"] = [ev[:7] for ev in list(e.pats[p].tracks[k].ev)] if e else []
                tr.append(t)
            pats.append({"tracks": tr})
        return {"v": 1, "bars": self.pbars, "pats": pats, "song": self.song_rows, "song_on": self.song_on,
                "cur": e.cur if e else 0}

    def song_save(self):
        if not self.lp_loaded or self.lp_e() is None:
            return
        try:
            tmp = SONG_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.song_snapshot(), f, separators=(",", ":"))
            os.replace(tmp, SONG_FILE)
        except Exception as ex:
            print("song save failed", ex, flush=True)

    def patch_json(self, i, tone=None, res=None):
        p = synth.edited_patch(synth.PATCHES[i], self.edits.get(str(i)))
        p["cutoff"] = p["cutoff"] * (2 ** (self.tone if tone is None else tone))
        p["res"] = max(0.5, p["res"] + (self.res if res is None else res))
        return json.dumps(p, sort_keys=True)

    # ------------------------------------------------------------ engine sync
    def lp_push_track(self, p, k):
        m = self.pm[p][k]
        self.eng.post("lp", "mix", p, k, {"vol": m["vol"], "pan": m["pan"], "rs": m["rs"], "ds": m["ds"],
                                          "mute": m["mute"]})
        self.eng.post("lp", "fx", p, k, {n: tuple(v) for n, v in m["rack"].items() if n != "Glide"},
                      tuple(m["flt"]))

    def lp_resolve(self, p, k, replace=False):
        pj = self.pm[p][k]["pj"]
        if pj and hasattr(self.eng, "lp_sound"):
            self.eng.lp_sound(p, k, pj, replace)

    def lp_resolve_later(self, p, k, replace=False, delay=0.15):
        """After an edit command: the engine applies it on its next block."""
        old = self.lp_resolve_q.get((p, k))
        self.lp_resolve_q[(p, k)] = (time.perf_counter() + delay, replace or (old[1] if old else False))

    def lp_load(self):
        """Hand the saved song to the engine once it is running."""
        self.lp_loaded = True
        e = self.lp_e()
        if e is None:
            return
        bass = set()
        for p in range(NP):
            self.eng.post("lp", "len", p, self.pbars[p] * 16)
            saved = self._saved.get("pats") or []
            trs = ((saved[p] if p < len(saved) else None) or {}).get("tracks") or []
            evs = [(trs[k].get("ev") if k < len(trs) and isinstance(trs[k], dict) else None) for k in range(NT)]
            if any(evs):
                self.eng.post("lp", "load", p, self.pbars[p] * 16, evs)
                for ev_l in evs:
                    bass.update(ev[2] for ev in (ev_l or []) if ev[1] == "b")
                for k in range(NT):
                    if evs[k]:
                        self.lp_resolve_later(p, k, True, 0.4)
            for k in range(NT):
                self.lp_push_track(p, k)
        if bass:
            self.ensure_bass(sorted(bass))
        self.eng.post("lp", "song", self.song_rows, self.song_on)
        self.eng.post("lp", "pat", self.start_p)
        self._saved = {}

    def sync_sel(self, preload=True):
        """The selected track of the playing pattern becomes the live instrument:
        its sound, sends and effects rack are what you play and edit."""
        e = self.lp_e()
        p = e.cur if e else 0
        k = self.lp_sel
        m = self.pm[p][k]
        if m["patch"] is None:
            m.update(patch=self.patch, tone=self.tone, res=self.res, pj=self.ckey(0)[1],
                     name=synth.PATCHES[self.patch]["name"], rs=self.base_rev, ds=self.base_dly)
            self.lp_push_track(p, k)
        elif (m["patch"], m["tone"], m["res"]) != (self.patch, self.tone, self.res):
            self.patch, self.tone, self.res = m["patch"], m["tone"], m["res"]
            self._pkey = None
            if preload:
                self.queue_precache()
            self.push_params()
        self.base_rev, self.base_dly = m["rs"], m["ds"]
        self.rev, self.dly = self.base_rev, self.base_dly
        self.push_fx()
        glide = list(self.rack["Glide"]) if hasattr(self, "rack") and "Glide" in self.rack else None
        self.rack = m["rack"]
        if glide and "Glide" not in self.rack:
            self.rack["Glide"] = glide
        self.push_rack()
        self.eng.post("lp", "sel", k)
        self.eng.post("filter", 0.0, 0.0)
        self.sel_key = (p, k)

    def pull_live(self):
        """Settings changes (sound, editor, reverb, delay) land on the selected track."""
        p, k = self.sel_key
        m = self.pm[p][k]
        pj = self.ckey(0)[1]
        if (m["patch"], m["tone"], m["res"], m["pj"]) != (self.patch, self.tone, self.res, pj):
            m.update(patch=self.patch, tone=self.tone, res=self.res, pj=pj, name=synth.PATCHES[self.patch]["name"])
            e = self.lp_e()
            if e and e.pats[p].tracks[k].ev:
                self.lp_resolve(p, k, replace=True)
            self.lp_dirty = True
        if (m["rs"], m["ds"]) != (self.base_rev, self.base_dly):
            m["rs"], m["ds"] = self.base_rev, self.base_dly
            self.lp_push_track(p, k)
            self.lp_dirty = True

    # ------------------------------------------------------------ actions
    def lp_select(self, k):
        self.lp_sel = k % NT
        self.sync_sel()

    def lp_pattern(self, p):
        e = self.lp_e()
        p %= NP
        self.eng.post("lp", "pat", p)
        if e and e.lp_on and p != e.cur:
            self.flash("PATTERN %02d NEXT" % (p + 1))
        else:
            self.flash("PATTERN %02d" % (p + 1))

    def lp_arm(self, k, stay=False):
        e = self.lp_e()
        if e is None:
            self.flash("SONG MODE NEEDS THE AUDIO ENGINE")
            return
        if e.lp_rec == k and e.lp_state:
            self.eng.post("lp", "arm", None)
            self.flash("RECORDING STOPPED")
            return
        if k != self.lp_sel:
            self.lp_select(k)
        self.lp_watch = (e.cur, k)
        self.lp_was_empty = not e.pats[e.cur].tracks[k].ev
        self.eng.post("lp", "arm", k, 16 * self.countin)
        if not stay:
            back = self.lp_return if self.lp_return in ("Play", "Lead", "Drone", "Drums") else "Play"
            self.set_mode(back)
        self.flash("P%02d TRACK %d %s: PLAY TO RECORD" % (e.cur + 1, k + 1, "ARMED" if self.lp_was_empty else "OVERDUB"))

    def lp_toggle_play(self, row=None):
        e = self.lp_e()
        if e is None:
            return
        on = not e.lp_on
        if on and self.song_on:
            self.eng.post("lp", "play", True, self.song_sel if row is None else row)
        else:
            self.eng.post("lp", "play", on)
        self.flash(("SONG " if (on and self.song_on) else "") + ("PLAY" if on else "STOP"))

    def lp_mute(self, p, k):
        m = self.pm[p][k]
        m["mute"] = not m["mute"]
        self.lp_push_track(p, k)
        self.lp_dirty = True
        self.flash("TRACK %d %s" % (k + 1, "MUTED" if m["mute"] else "ON"))

    def pattern_empty(self, p):
        e = self.lp_e()
        return not any(t.ev for t in e.pats[p].tracks)

    def pattern_copy(self, src):
        dst = next((q % NP for q in range(src + 1, src + NP) if self.pattern_empty(q % NP)), None)
        if dst is None:
            self.flash("NO EMPTY PATTERN")
            return
        self.eng.post("lp", "copy", src, dst)
        self.pm[dst] = [copy_track(m) for m in self.pm[src]]
        self.pbars[dst] = self.pbars[src]
        self.lp_dirty = True
        self.lp_pattern(dst)
        self.flash("COPIED P%02d TO P%02d" % (src + 1, dst + 1))

    def set_track_sound(self, p, k, d):
        m = self.pm[p][k]
        i = ((m["patch"] if m["patch"] is not None else self.patch) + d) % len(synth.PATCHES)
        if (p, k) == self.sel_key:
            self.patch = i               # pull_live() carries it to the track
            self.patch_changed()
        else:
            m.update(patch=i, name=synth.PATCHES[i]["name"], pj=self.patch_json(i, m["tone"], m["res"]))
            self.lp_resolve(p, k, replace=True)
        self.lp_dirty = True

    def lp_randomize(self, p, k):
        rack = self.pm[p][k]["rack"]
        pick = random.sample(list(FX_ORDER), random.randint(1, 3))
        for n in FX_ORDER:
            rack[n][0] = n in pick
            if n in pick:
                rack[n][1] = round(random.uniform(0.25, 0.9), 2)
                rack[n][2] = random.randrange(len(RATES))
        self.lp_push_track(p, k)
        self.flash("TRACK %d: %s" % (k + 1, " + ".join(pick)))

    # ------------------------------------------------------------ SELECT combos (any mode)
    def looper_combo(self, name, down):
        if name in ("START", "L3", "R3"):
            return False
        if not down or name not in ("A", "B", "X", "Y", "UP", "DOWN", "LEFT", "RIGHT"):
            return True                      # swallow the rest while SELECT is held
        e = self.lp_e()
        if e is None:
            self.flash("SONG MODE NEEDS THE AUDIO ENGINE")
            return True
        if name == "A":
            self.lp_arm(self.lp_sel, stay=True)
        elif name == "B":
            if e.lp_undo:
                self.eng.post("lp", "undo")
                self.lp_dirty = True
                self.flash("UNDO / REDO P%02d" % (e.lp_undo[0] + 1))
            else:
                self.flash("NOTHING TO UNDO")
        elif name == "X":
            self.lp_toggle_play()
        elif name == "Y":
            self.lp_mute(e.cur, self.lp_sel)
        elif name in ("UP", "DOWN"):
            self.lp_select(self.lp_sel + (1 if name == "DOWN" else -1))
            t = e.pats[e.cur].tracks[self.lp_sel]
            nm = self.pm[e.cur][self.lp_sel]["name"] or ""
            self.flash("TRACK %d  %s" % (self.lp_sel + 1, nm.upper() if t.ev else "EMPTY"))
        else:
            base = e.cue if e.cue is not None else e.cur
            self.lp_pattern(base + (1 if name == "RIGHT" else -1))
        return True

    # ------------------------------------------------------------ page input
    def song_input(self, name, down):
        if name == "Y":
            if down:
                self.y_used = False
            elif not self.y_used and self.sg_page == "pattern":
                e = self.lp_e()
                if e:
                    self.lp_mute(e.cur, self.lp_sel)
            elif not self.y_used and self.sg_page == "song":
                self.song_on = not self.song_on
                self.eng.post("lp", "song", self.song_rows, self.song_on)
                self.lp_dirty = True
                self.flash("SONG MODE " + ("ON" if self.song_on else "OFF"))
            return True
        if not down:
            return name not in ("SELECT", "R3")
        if "Y" in self.inp.held:
            self.y_used = True
        e = self.lp_e()
        if e is None:
            return name not in ("SELECT", "START", "R3")
        if self.sg_page == "fx":
            return self.tfx_input(name)
        if name in ("L1", "R1"):
            i = PAGES.index(self.sg_page)
            self.sg_page = PAGES[(i + (1 if name == "R1" else -1)) % len(PAGES)]
            return True
        if name == "START":
            self.lp_toggle_play()
            return True
        page = getattr(self, "input_" + self.sg_page)
        used = page(name, e, "Y" in self.inp.held)
        if used:
            self.lp_dirty = True
        return used

    def input_pattern(self, name, e, y):
        p, k = e.cur, self.lp_sel
        if name in ("UP", "DOWN"):
            self.lp_select(k + (1 if name == "DOWN" else -1))
        elif name in ("LEFT", "RIGHT"):
            d = 1 if name == "RIGHT" else -1
            if y:
                b = self.pbars[p]
                self.pbars[p] = BARS[(BARS.index(b) + d) % len(BARS)] if b in BARS else 2
                self.eng.post("lp", "len", p, self.pbars[p] * 16)
                self.flash("P%02d LENGTH %d BAR%s" % (p + 1, self.pbars[p], "" if self.pbars[p] == 1 else "S"))
            else:
                base = e.cue if e.cue is not None else e.cur
                self.lp_pattern(base + d)
        elif name == "A":
            if y:
                self.pattern_copy(p)
            else:
                self.lp_arm(k)
        elif name == "B":
            if y:
                self.eng.post("lp", "clearpat", p)
                self.flash("P%02d CLEARED   SELECT+B UNDOES" % (p + 1))
            elif e.pats[p].tracks[k].ev:
                self.eng.post("lp", "clear", p, k)
                self.flash("TRACK %d CLEARED   SELECT+B UNDOES" % (k + 1))
        elif name == "X":
            self.sg_page = "fx"
            self.tfx_i = 0
        else:
            return False
        return True

    def grid_events(self, e, step):
        return [ev for ev in e.pats[e.cur].tracks[self.lp_sel].ev if int(ev[0]) == step]

    def input_grid(self, name, e, y):
        p, k = e.cur, self.lp_sel
        n = e.pats[p].len
        x = self.grid_x % n
        here = self.grid_events(e, x)
        if name in ("LEFT", "RIGHT"):
            d = 1 if name == "RIGHT" else -1
            if y and here:
                self.eng.post("lp", "ed", "len", p, k, x, d)
            else:
                self.grid_x = (x + d) % n
        elif name in ("UP", "DOWN"):
            if here:
                d = (12 if y else 1) * (1 if name == "UP" else -1)
                self.eng.post("lp", "ed", "shift", p, k, x, d)
                self.lp_resolve_later(p, k)
                bm = [ev[2] + d for ev in here if ev[1] == "b"]
                if bm:
                    self.ensure_bass(bm)
                self.grid_preview(here, d)
        elif name == "A":
            evs = self.grid_new(e, x, drum=y)
            self.eng.post("lp", "ed", "add", p, k, evs)
            self.lp_resolve_later(p, k)
            self.grid_preview(evs, 0)
            self.grid_x = (x + 1) % n
        elif name == "B":
            if here:
                self.eng.post("lp", "ed", "del", p, k, x)
        elif name == "X":
            self.eng.post("lp", "ed", "quant", p, k)
            self.flash("TRACK %d QUANTIZED   SELECT+B UNDOES" % (k + 1))
        else:
            return False
        return True

    def grid_new(self, e, x, drum=False):
        """A new trig: a copy of the nearest earlier step on this track, or a
        root note (Y+A: a kick) if the track is empty."""
        tr = e.pats[e.cur].tracks[self.lp_sel]
        n = e.pats[e.cur].len
        if not drum and tr.ev:
            for back in range(1, n + 1):
                s = (x - back) % n
                src = [ev for ev in tr.ev if int(ev[0]) == s]
                if src:
                    return [[x + (ev[0] - s), ev[1], ev[2], ev[3], ev[4], ev[5], ev[6]] for ev in src]
        if drum:
            return [[x, "d", "kick", 0.9, 0.0, None, 0.02]]
        root = 60 + self.key - (12 if self.key >= 7 else 0) + 12 * self.octave
        return [[x, "n", root, 0.9, 0.0, 1.0, 0.3]]

    def grid_preview(self, evs, d):
        notes = sorted(ev[2] + d for ev in evs if ev[1] == "n")
        if notes:
            self.eng.post("lead_on", notes[0], self._snd([notes[0]]).get(notes[0]), 0.0)
            self.anim["_lead_preview"] = time.perf_counter()
        for ev in evs:
            if ev[1] == "d":
                self.eng.post("hit", ev[2], 0.8)

    def input_song(self, name, e, y):
        rows = self.song_rows
        i = self.song_sel % len(rows)
        if name in ("UP", "DOWN"):
            self.song_sel = (i + (1 if name == "DOWN" else -1)) % len(rows)
        elif name in ("LEFT", "RIGHT"):
            rows[i][0] = (rows[i][0] + (1 if name == "RIGHT" else -1)) % NP
        elif name == "A":
            rows.insert(i + 1, list(rows[i]))
            self.song_sel = i + 1
        elif name == "B":
            if len(rows) > 1:
                rows.pop(i)
                self.song_sel = min(i, len(rows) - 1)
        elif name == "X":
            rows[i][1] = rows[i][1] % 16 + 1
        else:
            return False
        self.eng.post("lp", "song", rows, self.song_on)
        return True

    def tfx_value(self, m, row):
        if row == "Sound":
            return m["name"] or synth.PATCHES[self.patch]["name"]
        return {"Level": m["vol"], "Pan": m["pan"], "Reverb": m["rs"], "Delay": m["ds"],
                "Filter": m["flt"][0], "Resonance": m["flt"][1]}.get(row) if row not in FX_ORDER else m["rack"][row]

    def tfx_input(self, name):
        e = self.lp_e()
        p, k = e.cur, self.lp_sel
        m = self.pm[p][k]
        row = TFX_ROWS[self.tfx_i]
        fx = row in FX_ORDER
        sel = (p, k) == self.sel_key
        if name in ("UP", "DOWN"):
            self.tfx_i = (self.tfx_i + (1 if name == "DOWN" else -1)) % len(TFX_ROWS)
            return True
        if name == "B":
            self.sg_page = "pattern"
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
                self.lp_select(k + d)
                return True
        elif name in ("LEFT", "RIGHT"):
            d = 1 if name == "RIGHT" else -1
            self.nudge = (time.perf_counter(), d)
            if row == "Sound":
                self.set_track_sound(p, k, d)
                return True
            if fx:
                v = m["rack"][row]
                v[1] = round(max(0.0, min(1.0, v[1] + 0.1 * d)), 2)
                v[0] = v[1] > 0.0
            elif row == "Level":
                m["vol"] = round(max(0.0, min(1.0, m["vol"] + 0.05 * d)), 2)
            elif row == "Pan":
                m["pan"] = round(max(-1.0, min(1.0, m["pan"] + 0.1 * d)), 2)
            elif row in ("Reverb", "Delay"):
                f = "rs" if row == "Reverb" else "ds"
                m[f] = round(max(0.0, min(1.0, m[f] + 0.05 * d)), 2)
                if sel:
                    self.base_rev, self.base_dly = m["rs"], m["ds"]
                    self.rev, self.dly = self.base_rev, self.base_dly
                    self.push_fx()
            elif row in ("Filter", "Resonance"):
                i = 0 if row == "Filter" else 1
                m["flt"][i] = round(max(0.0, min(1.0, m["flt"][i] + 0.05 * d)), 2)
        elif name == "A":
            if fx:
                m["rack"][row][0] = not m["rack"][row][0]
            elif row == "Pan":
                m["pan"] = 0.0
            else:
                self.lp_mute(p, k)
                return True
        elif name == "X":
            self.lp_randomize(p, k)
            self.lp_dirty = True
            return True
        elif name == "Y":
            return True
        else:
            return False
        self.lp_push_track(p, k)
        self.lp_dirty = True
        return True

    # ------------------------------------------------------------ tick
    def song_tick(self, now):
        if not self.lp_loaded:
            self.lp_load()
        e = self.lp_e()
        if e is None:
            return
        key = (e.cur, self.lp_sel)
        if key != self.sel_key:
            # pattern changed (or first run): the live instrument follows. While the
            # transport runs, don't stop for a full sound preload.
            self.sync_sel(preload=not e.lp_on)
        else:
            self.pull_live()
        for pk, (t, rep) in list(self.lp_resolve_q.items()):
            if now >= t:
                del self.lp_resolve_q[pk]
                self.lp_resolve(pk[0], pk[1], rep)
        st = e.lp_state
        if st != self.lp_last_state:
            if st == "count":
                self.flash("COUNT-IN: RECORDING STARTS ON THE ONE")
            elif st == "rec":
                self.flash("RECORDING P%02d TRACK %d" % (e.cur + 1, (e.lp_rec or 0) + 1))
            elif st is None and self.lp_last_state == "rec":
                w = self.lp_watch
                if w is not None and e.pats[w[0]].tracks[w[1]].ev:
                    p, k = w
                    self.lp_resolve_later(p, k, False, 0.1)
                    nxt = None
                    if self.lp_was_empty and self.lp_sel == k:
                        nxt = next((j % NT for j in range(k + 1, k + NT) if not e.pats[p].tracks[j % NT].ev), None)
                    if nxt is not None:
                        self.lp_sel = nxt
                        self.flash("TRACK %d RECORDED   NEXT: TRACK %d" % (k + 1, nxt + 1))
                    else:
                        self.flash("TRACK %d RECORDED" % (k + 1))
                self.lp_dirty = True
            self.lp_last_state = st
        if self.lp_dirty and not st and now - self.lp_save_t > 4.0:
            self.lp_save_t = now
            self.lp_dirty = False
            self.song_save()

    # ------------------------------------------------------------ drawing
    def song_chip(self, c, x, y):
        mm = M()
        e = self.lp_e()
        if e is None:
            return x
        if e.lp_state:
            t = ("COUNT" if e.lp_state == "count" else "REC") + " P%02d T%d" % (e.cur + 1, (e.lp_rec or 0) + 1)
            col = REC if (e.lp_state == "rec" or int(time.perf_counter() * 3) % 2 == 0) else mm.PANEL
        elif e.lp_on:
            t = ("SONG %d/%d " % (e.song_row + 1, len(self.song_rows)) if e.song_on else "") + "P%02d T%d" % (e.cur + 1, self.lp_sel + 1)
            col = mm.ACCENT2
        else:
            t, col = "P%02d T%d" % (e.cur + 1, self.lp_sel + 1), mm.PANEL
        w = self.f_small.size(t)[0] + 14
        pygame.draw.rect(c, col, (x, y, w, 20), border_radius=10)
        self.text(c, t, self.f_small, mm.BG if col != mm.PANEL else mm.INK, (x + w // 2, y + 10), center=True)
        return x + w + 6

    def song_hint(self):
        pg = self.sg_page
        if pg == "fx":
            return "LEFT/RIGHT value  A on/off  L1/R1 rate  X random  B back"
        if pg == "grid":
            return "A add  B del  UP/DOWN pitch  X quantize  Y+<> length  Y+A kick  L1/R1 page"
        if pg == "song":
            return "<> pattern  X repeats  A add  B del  Y song on/off  START play  L1/R1 page"
        return "A rec  B clear  Y mute  X fx  <> pattern  Y+<> length  Y+A copy  L1/R1 page"

    def playpos(self, e):
        if not e.lp_on or e.lp_pos < 0:
            return None
        step = 60.0 / e.bpm / 4 * e.sr
        return (e.lp_pos + max(0.0, min(1.0, (e.t - e.lp_step_at) / step))) % max(1, e.pats[e.cur].len)

    def draw_song(self, c):
        e = self.lp_e()
        mm = M()
        if e is None:
            self.text(c, "Song mode needs the audio engine", self.f_med, mm.DIM, (mm.BASE_W // 2, 200), center=True)
            return
        if self.sg_page == "fx":
            self.draw_track_fx(c, e)
            return
        # page tabs
        x = 20
        for pg in PAGES:
            on = pg == self.sg_page
            w = self.f_small.size(pg.upper())[0] + 16
            pygame.draw.rect(c, mm.ACCENT if on else mm.PANEL, (x, 46, w, 20), border_radius=10)
            self.text(c, pg.upper(), self.f_small, mm.BG if on else mm.DIM, (x + w // 2, 56), center=True)
            x += w + 6
        st = ("SONG " if e.song_on else "") + ("PLAYING" if e.lp_on else "stopped")
        self.text(c, st, self.f_small, mm.INK if e.lp_on else mm.DIM, (mm.BASE_W - 20, 50), right=True)
        getattr(self, "draw_" + self.sg_page + "_page")(c, e)

    def draw_pattern_strip(self, c, e, y):
        mm = M()
        now = time.perf_counter()
        w = (mm.BASE_W - 40) / NP
        for p in range(NP):
            r = pygame.Rect(int(20 + p * w), y, int(w) - 3, 18)
            has = any(t.ev for t in e.pats[p].tracks)
            col = mm.PANEL
            if has:
                col = self.mix(mm.PANEL, mm.ACCENT2, 0.55)
            if p == e.cur:
                col = mm.ACCENT
            if p == e.cue and int(now * 4) % 2 == 0:
                col = mm.INK
            pygame.draw.rect(c, col, r, border_radius=4)
            self.text(c, str(p + 1), self.f_small, mm.BG if (p == e.cur or has) else mm.DIM, r.center, center=True)

    def lane(self, p, k, tr, w, h, L):
        """Cached picture of a track's notes (rebuilt only when it changes)."""
        mm = M()
        key = (len(tr.ev), w, h, L, self.pm[p][k]["mute"], id(tr.ev))
        hit = self.lp_lane_cache.get((p, k))
        if hit and hit[0] == key:
            return hit[1]
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        col = mm.DIM if self.pm[p][k]["mute"] else TRACK_COLS[k % len(TRACK_COLS)]
        evs = [ev for ev in tr.ev if ev[0] < L]
        notes = [ev for ev in evs if ev[1] in ("n", "b")]
        lo = min((ev[2] for ev in notes), default=48)
        span = max(12, max((ev[2] for ev in notes), default=60) - lo)
        for ev in evs[-500:]:
            x = int(ev[0] / L * w)
            if ev[1] == "d":
                yy = int(h * DRUM_ROW.get(ev[2], 0.5))
                pygame.draw.rect(surf, col, (x, yy - 2, 3, 4))
            else:
                yy = int(h - 3 - (ev[2] - lo) / span * (h - 6))
                ln = max(2, int((ev[5] or 0.5) / L * w))
                c2 = self.mix(col, mm.INK, 0.25) if ev[1] == "b" else col
                pygame.draw.rect(surf, c2, (x, yy - 1, min(ln, w - x), 3))
                if x + ln > w:
                    pygame.draw.rect(surf, c2, (0, yy - 1, x + ln - w, 3))
        self.lp_lane_cache[(p, k)] = (key, surf)
        return surf

    def draw_pattern_page(self, c, e):
        mm = M()
        p = e.cur
        pat = e.pats[p]
        L = max(1, pat.len)
        self.draw_pattern_strip(c, e, 72)
        top = 96
        bottom = mm.L["tiles_y"] + mm.L["tile_h"]
        self.text(c, "P%02d   %d bar%s" % (p + 1, self.pbars[p], "" if self.pbars[p] == 1 else "s") +
                  ("   next P%02d" % (e.cue + 1) if e.cue is not None else ""), self.f_small, mm.DIM, (20, top))
        top += 18
        rh = (bottom - top) // NT
        x0, x1 = 176, mm.BASE_W - 70
        lw = x1 - x0
        pp = self.playpos(e)
        now = time.perf_counter()
        ty = self.sm("lp_sel", top + self.lp_sel * rh, 24)
        pygame.draw.rect(c, mm.PANEL, (10, int(ty) + 1, mm.BASE_W - 20, rh - 2), border_radius=8)
        for k in range(NT):
            y = top + k * rh
            tr = pat.tracks[k]
            m = self.pm[p][k]
            col = TRACK_COLS[k % len(TRACK_COLS)]
            rec = e.lp_rec == k and e.lp_state
            badge = pygame.Rect(18, y + rh // 2 - 12, 24, 24)
            if rec:
                on = e.lp_state == "rec" or int(now * 3) % 2 == 0
                pygame.draw.rect(c, REC if on else mm.PANEL, badge, border_radius=12)
            else:
                pygame.draw.rect(c, col if tr.ev and not m["mute"] else mm.BG, badge, border_radius=12)
            self.text(c, str(k + 1), self.f_small, mm.BG if (rec or (tr.ev and not m["mute"])) else mm.DIM,
                      badge.center, center=True)
            nm = m["name"] or (synth.PATCHES[self.patch]["name"] if k == self.lp_sel else "empty")
            self.text(c, nm[:14], self.f_small, mm.INK if (k == self.lp_sel or tr.ev) else mm.DIM, (50, y + rh // 2 - 15))
            if rec:
                sub = {"rec": "REC", "count": "count-in"}.get(e.lp_state, "play to start")
            else:
                nfx = sum(1 for n, v in m["rack"].items() if v[0] and n != "Glide")
                sub = ("%d notes" % len(tr.ev) if tr.ev else "") + ("  fx %d" % nfx if nfx else "")
                if m["mute"]:
                    sub = "MUTED " + sub
            self.text(c, sub, self.f_small, REC if (rec or m["mute"]) else mm.DIM, (50, y + rh // 2 + 2))
            lane = pygame.Rect(x0, y + 4, lw, rh - 8)
            pygame.draw.rect(c, self.mix(mm.BG, mm.PANEL, 0.5), lane, border_radius=4)
            bars = max(1, L // 16)
            for b in range(1, bars):
                bx = x0 + int(lw * b / bars)
                pygame.draw.line(c, mm.PANEL, (bx, lane.top + 2), (bx, lane.bottom - 2))
            if tr.ev:
                c.blit(self.lane(p, k, tr, lw, rh - 8, L), lane.topleft)
            vx = mm.BASE_W - 62
            pygame.draw.rect(c, mm.BG, (vx, y + rh // 2 - 4, 44, 8), border_radius=4)
            fill = int(44 * self.sm("lpvol%d" % k, m["vol"], 18))
            if fill:
                pygame.draw.rect(c, mm.DIM if m["mute"] else col, (vx, y + rh // 2 - 4, fill, 8), border_radius=4)
        if pp is not None:
            px = x0 + int(lw * pp / L)
            pygame.draw.line(c, mm.INK, (px, top + 2), (px, top + rh * NT - 2), 2)

    def draw_grid_page(self, c, e):
        mm = M()
        p, k = e.cur, self.lp_sel
        pat = e.pats[p]
        L = max(16, pat.len)
        tr = pat.tracks[k]
        col = TRACK_COLS[k % len(TRACK_COLS)]
        x = self.grid_x % L
        page = x // 16
        self.text(c, "P%02d  TRACK %d  %s" % (p + 1, k + 1, (self.pm[p][k]["name"] or "").upper()), self.f_small,
                  col, (20, 74))
        self.text(c, "page %d/%d" % (page + 1, L // 16), self.f_small, mm.DIM, (mm.BASE_W - 20, 74), right=True)
        # piano roll of this page
        top, bottom = 96, mm.L["tiles_y"] - 4
        roll = pygame.Rect(20, top, mm.BASE_W - 40, bottom - top)
        pygame.draw.rect(c, self.mix(mm.BG, mm.PANEL, 0.5), roll, border_radius=6)
        cw = roll.w / 16.0
        s0 = page * 16
        evs = [ev for ev in tr.ev if s0 <= ev[0] < s0 + 16]
        notes = [ev for ev in tr.ev if ev[1] in ("n", "b")]
        lo = min((ev[2] for ev in notes), default=55)
        hi = max((ev[2] for ev in notes), default=lo + 12)
        hi = max(hi, lo + 12)
        for i in range(16):
            if i % 4 == 0:
                pygame.draw.line(c, mm.PANEL, (int(roll.x + i * cw), roll.top + 2), (int(roll.x + i * cw), roll.bottom - 2))
        for ev in evs:
            ex = roll.x + (ev[0] - s0) * cw
            if ev[1] == "d":
                yy = roll.top + int(roll.h * DRUM_ROW.get(ev[2], 0.5))
                pygame.draw.rect(c, col, (int(ex), yy - 4, max(4, int(cw * 0.5)), 8), border_radius=3)
            else:
                yy = roll.bottom - 6 - int((ev[2] - lo) / float(hi - lo) * (roll.h - 12))
                ln = max(4, int((ev[5] or 0.5) * cw))
                pygame.draw.rect(c, self.mix(col, mm.INK, 0.3) if ev[1] == "b" else col,
                                 (int(ex), yy - 3, min(ln, roll.right - int(ex)), 6), border_radius=3)
        pp = self.playpos(e)
        if pp is not None and s0 <= pp < s0 + 16:
            px = int(roll.x + (pp - s0) * cw)
            pygame.draw.line(c, mm.INK, (px, roll.top), (px, roll.bottom), 2)
        # trig row
        ty = mm.L["tiles_y"]
        th = mm.L["tile_h"] // 2
        for i in range(16):
            s = s0 + i
            here = [ev for ev in tr.ev if int(ev[0]) == s]
            r = pygame.Rect(int(20 + i * cw), ty, int(cw) - 3, th)
            base = mm.PANEL if (i // 4) % 2 == 0 else self.mix(mm.PANEL, mm.BG, 0.45)
            pygame.draw.rect(c, col if here else base, r, border_radius=4)
            if s == x:
                pygame.draw.rect(c, mm.INK, r.inflate(4, 4), 2, border_radius=5)
            if here and th > 20:
                lab = DRUM_ABBR.get(here[0][2], "?") if here[0][1] == "d" else M().NOTE_NAMES[min(ev[2] for ev in here) % 12]
                self.text(c, lab, self.f_small, mm.BG, r.center, center=True)
        here = [ev for ev in tr.ev if int(ev[0]) == x]
        if here:
            ns = sorted(set(note_name(ev[2]) if ev[1] != "d" else ev[2].upper() for ev in here))
            info = "step %d:  %s   len %.1f" % (x + 1, " ".join(ns[:6]), max((ev[5] or 0) for ev in here))
        else:
            info = "step %d: empty   A adds a copy of the last trig" % (x + 1)
        self.text(c, info, self.f_small, mm.INK, (20, ty + th + 8))

    def draw_song_page(self, c, e):
        mm = M()
        rows = self.song_rows
        top = 78
        bottom = mm.L["tiles_y"] + mm.L["tile_h"]
        bars = sum(self.pbars[r[0]] * r[1] for r in rows)
        secs = bars * 4 * 60.0 / max(1.0, self.bpm)
        self.text(c, "SONG %s   %d rows   %d bars   %d:%02d" % ("ON" if self.song_on else "OFF", len(rows), bars,
                                                             secs // 60, secs % 60), self.f_small,
                  mm.ACCENT if self.song_on else mm.DIM, (20, top))
        top += 24
        rh = 28
        vis = max(4, (bottom - top) // rh)
        first = max(0, min(self.song_sel - vis // 2, len(rows) - vis))
        for i in range(first, min(len(rows), first + vis)):
            y = top + (i - first) * rh
            p, reps = rows[i]
            sel = i == self.song_sel
            playing = e.lp_on and e.song_on and e.song_row == i
            if sel:
                pygame.draw.rect(c, mm.PANEL, (14, y - 2, mm.BASE_W - 28, rh - 2), border_radius=6)
            self.text(c, "%02d" % (i + 1), self.f_small, mm.DIM, (28, y + 4))
            has = not self.pattern_empty(p)
            r = pygame.Rect(70, y + 1, 70, rh - 8)
            pygame.draw.rect(c, mm.ACCENT if playing else (self.mix(mm.PANEL, mm.ACCENT2, 0.55) if has else mm.BG), r,
                             border_radius=6)
            self.text(c, "P%02d" % (p + 1), self.f_small, mm.BG if (playing or has) else mm.DIM, r.center, center=True)
            self.text(c, "x%d" % reps, self.f_med, mm.INK if sel else mm.DIM, (160, y))
            self.text(c, "%d bar%s" % (self.pbars[p] * reps, "" if self.pbars[p] * reps == 1 else "s"), self.f_small,
                      mm.DIM, (220, y + 4))
            if playing:
                self.text(c, "%d/%d" % (e.song_rep + 1, reps), self.f_small, mm.ACCENT, (mm.BASE_W - 30, y + 4), right=True)

    def draw_track_fx(self, c, e):
        mm = M()
        p, k = e.cur, self.lp_sel
        m = self.pm[p][k]
        top = 46
        bottom = mm.L["tiles_y"] + mm.L["tile_h"]
        col = TRACK_COLS[k % len(TRACK_COLS)]
        self.text(c, "P%02d TRACK %d" % (p + 1, k + 1), self.f_med, col, (20, top))
        self.text(c, "sound, effects, level, sends   L1/R1 track   B back", self.f_small, mm.DIM, (190, top + 6))
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
            v = self.tfx_value(m, row)
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
                fill = int(bw * self.sm("tfx_%d_%d_%s" % (p, k, row), amt, 18))
                if fill:
                    pygame.draw.rect(c, mm.ACCENT if on else mm.DIM, (bx, y + rh // 2 - 4, fill, 8), border_radius=4)
                val = RATES[v[2]][0] if fx and row not in ("Drive", "Lo-fi", "Wide") else "%d%%" % round(amt * 100)
            self.text(c, val, self.f_small, mm.INK if sel else mm.DIM, (mm.BASE_W - 28 + kick, y + 5), right=True)
        if first + vis < len(TFX_ROWS):
            self.text(c, "more", self.f_small, mm.DIM, (mm.BASE_W // 2, bottom - 4), center=True)
