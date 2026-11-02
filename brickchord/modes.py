# Brickchord instrument modes, mixed into the App class (see main.py).
#
#   Play       chords (the original Brickchord)
#   Lead       single-note melodies: buttons = scale notes, glide, stick bend/vibrato
#   Drone      sustained root/fifth/octave layer that keeps going under the others
#   Drums      buttons are drum pads
#   Sequencer  8 tracks x 16/32 steps, step edit or live record from the other modes
#   Effects    stackable effects rack with randomize
#
# Click the left stick (L3) for the mode wheel; tilt to pick, let go to choose.
import math
import random
import sys
import time

import pygame

import engine
import synth

IMODES = ["Play", "Lead", "Drone", "Drums", "Sequencer", "Effects"]   # clockwise from the top
FX_ROWS = engine.Engine.FX_ORDER + ["Glide"]
RATES = engine.Engine.RATES
FX_DEFAULTS = {"Drive": (0.4, 3), "Lo-fi": (0.4, 3), "Chorus": (0.5, 5), "Flanger": (0.5, 6),
               "Vibrato": (0.3, 0), "Tremolo": (0.5, 1), "Gate": (0.7, 0), "Auto-Pan": (0.6, 4),
               "Wide": (0.6, 3), "Filter LFO": (0.6, 5), "Glide": (0.3, 0)}
DRUM_PADS = {"LEFT": "kick", "UP": "snare", "RIGHT": "hat", "DOWN": "ohat", "X": "clap", "A": "tom",
             "B": "rim", "Y": "shk"}
PAD_LABEL = {"kick": "KICK", "snare": "SNARE", "hat": "HAT", "ohat": "OPEN", "clap": "CLAP", "tom": "TOM",
             "rim": "RIM", "shk": "SHAKE"}
SEQ_TRACKS = ["Chords", "Lead", "Kick", "Snare", "Hat", "Open Hat", "Clap", "Perc"]
SEQ_DRUM = {"Kick": "kick", "Snare": "snare", "Hat": "hat", "Open Hat": "ohat", "Clap": "clap", "Perc": "rim"}
SEQ_MAX = 32


def M():
    return sys.modules["main"]


def new_pattern():
    return {"len": 16, "tracks": {t: [None] * SEQ_MAX for t in SEQ_TRACKS}}


class ModesMixin:
    # ------------------------------------------------------------ setup
    def modes_init(self):
        s = self.cfg.get("settings", {})
        self.imode = s.get("imode", "Play") if s.get("imode") in IMODES else "Play"
        if self.imode == "Effects":
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
        sq = self.cfg.get("seq")
        self.seq = sq if (isinstance(sq, dict) and "tracks" in sq) else new_pattern()
        for t in SEQ_TRACKS:
            row = self.seq["tracks"].setdefault(t, [None] * SEQ_MAX)
            row.extend([None] * (SEQ_MAX - len(row)))
        self.seq_on = False
        self.seq_rec = False
        self.seq_row = 0
        self.seq_col = 0

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
        if im == "Sequencer":
            return self.seq_input(name, down)
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
        h = self.inp.held
        self.seq_record("Lead", [deg, (1 if "Y" in h else 0) - (1 if "L1" in h else 0), 1 if "R1" in h else 0])

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
        lane = next((t for t, p in SEQ_DRUM.items() if p == part), "Perc")
        self.seq_record(lane, [part, min(1.0, gain)])

    # ------------------------------------------------------------ sequencer
    def seq_now_step(self):
        e = getattr(self.eng, "eng", None)
        n = self.seq["len"]
        if not (e and self.seq_on):
            return None
        idx = (e.seq_i - 1) % n
        step = 60.0 / e.bpm / 4 * e.sr
        frac = (e.t - (e.next16 - step)) / step
        if frac > 0.5:
            idx = (idx + 1) % n
        return idx

    def seq_record(self, track, value):
        if not (self.seq_rec and self.seq_on):
            return
        i = self.seq_now_step()
        if i is None:
            return
        self.seq["tracks"][track][i] = value
        self.seq_push()

    def record_chord(self, deg, mods):
        self.seq_record("Chords", [deg, sorted(k for k, v in mods.items() if v)])

    def seq_push(self):
        """Turn the pattern into timed notes with sounds and hand it to the engine."""
        if not hasattr(self, "seq") or not hasattr(self.eng, "resolve"):
            return
        mm = M()
        n = self.seq["len"]
        tr = self.seq["tracks"]
        sc = mm.SCALES[self.scale]
        steps = [{"drums": []} for _ in range(n)]
        need = set()
        roots = set()

        def dur_until(row, i, cap):
            for d in range(1, n + 1):
                if row[(i + d) % n] is not None or d >= cap:
                    return d
            return n

        prev = []
        crow = tr["Chords"][:n]
        for i, v in enumerate(crow):
            if v is None:
                continue
            deg, ml = v
            pc, iv, _ = mm.build_chord(self.key, self.scale, deg, {k: True for k in ml})
            notes, prev = mm.voice(pc, iv, prev, self.octave)
            steps[i]["chord"] = (notes, dur_until(crow, i, n))
            need.update(notes)
            r = notes[0] - 12
            while r < 28:
                r += 12
            roots.add(r)
        lrow = tr["Lead"][:n]
        for i, v in enumerate(lrow):
            if v is None:
                continue
            deg, oc, sh = v
            m = 60 + self.key + sc[deg] + 12 * (self.octave + oc) + sh - (12 if self.key >= 7 else 0)
            steps[i]["lead"] = (m, dur_until(lrow, i, 4))
            need.add(m)
        for t, part in SEQ_DRUM.items():
            for i, v in enumerate(tr[t][:n]):
                if v is not None:
                    steps[i]["drums"].append((v[0], v[1]))
        if roots and synth.BASS_MODES[self.bass] not in ("Patch", "Off"):
            self.ensure_bass(sorted(roots))
        self.eng.post("seq", {"len": n, "steps": steps, "snd": self._snd(sorted(need))}, None, False)

    def seq_toggle(self):
        self.seq_on = not self.seq_on
        if self.seq_on:
            self.seq_push()
        self.eng.post("seq", None, self.seq_on, True)
        self.flash("SEQUENCER " + ("PLAY" if self.seq_on else "STOP"))

    def seq_input(self, name, down):
        if not down:
            return name not in ("SELECT", "R3")
        n = self.seq["len"]
        tname = SEQ_TRACKS[self.seq_row]
        row = self.seq["tracks"][tname]
        c = self.seq_col
        changed = False
        if name == "UP":
            self.seq_row = (self.seq_row - 1) % len(SEQ_TRACKS)
        elif name == "DOWN":
            self.seq_row = (self.seq_row + 1) % len(SEQ_TRACKS)
        elif name == "LEFT":
            self.seq_col = (c - 1) % n
        elif name == "RIGHT":
            self.seq_col = (c + 1) % n
        elif name == "A":
            if tname in SEQ_DRUM:
                row[c] = None if row[c] else [SEQ_DRUM[tname], 1.0]
            elif row[c] is None:
                last = self.anim.get("_seq_last_" + tname, 0)
                row[c] = [last, []] if tname == "Chords" else [last, 0, 0]
            else:
                row[c][0] = (row[c][0] + 1) % 7
            if row[c] and tname not in SEQ_DRUM:
                self.anim["_seq_last_" + tname] = row[c][0]
                self.seq_preview(tname, row[c])
            changed = True
            self.seq_col = (c + 1) % n if tname in SEQ_DRUM else c
        elif name == "B":
            row[c] = None
            changed = True
        elif name in ("L1", "R1") and row[c] is not None:
            d = -1 if name == "L1" else 1
            if tname in SEQ_DRUM:
                levels = [0.45, 0.75, 1.0]
                k = min(range(3), key=lambda j: abs(levels[j] - row[c][1]))
                row[c][1] = levels[(k + d) % 3]
            elif tname == "Lead" and "Y" in self.inp.held:
                row[c][1] = max(-1, min(1, row[c][1] + d))          # Y + L1/R1 = octave
            else:
                row[c][0] = (row[c][0] + d) % 7
                self.seq_preview(tname, row[c])
            changed = True
        elif name == "X":
            self.seq_rec = not self.seq_rec
            self.flash("RECORD " + ("ON: play in Play, Lead or Drums" if self.seq_rec else "OFF"))
        elif name == "Y":
            if not any(k in self.inp.held for k in ("L1", "R1")):
                self.seq["len"] = {8: 16, 16: 32, 32: 8}[n]
                self.seq_col %= self.seq["len"]
                changed = True
        elif name == "START":
            self.seq_toggle()
        else:
            return False
        if changed:
            self.seq_push()
        return True

    def seq_preview(self, track, v):
        mm = M()
        if track == "Chords":
            pc, iv, _ = mm.build_chord(self.key, self.scale, v[0], {k: True for k in v[1]})
            notes, _ = mm.voice(pc, iv, [], self.octave)
            self.eng.chord(notes, {m: self.ckey(m) for m in notes}, False)
            self.audition_until = time.perf_counter() + 0.5
        elif track == "Lead":
            sc = mm.SCALES[self.scale]
            m = 60 + self.key + sc[v[0]] + 12 * (self.octave + v[1]) + v[2] - (12 if self.key >= 7 else 0)
            self.eng.post("lead_on", m, self._snd([m]).get(m), 0.0)
            self.anim["_lead_preview"] = time.perf_counter()

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
        if self.seq_on or self.seq_rec:
            t = ("REC " if self.seq_rec else "") + ("SEQ" if self.seq_on else "")
            w = self.f_small.size(t)[0] + 14
            col = (230, 70, 70) if self.seq_rec else mm.ACCENT2
            pygame.draw.rect(c, col, (x, y, w, 20), border_radius=10)
            self.text(c, t.strip(), self.f_small, mm.BG, (x + w // 2, y + 10), center=True)
            x += w + 6
        return x

    def mode_hint(self):
        return {"Lead": "Y oct+  L1 oct-  R1 sharp  L-stick bend/vibrato  L3 modes",
                "Drone": "tap a degree to drone, again to stop  Y adds 3rd  L3 modes",
                "Drums": "8 pads  L1 soft  R1 accent  L3 modes",
                "Sequencer": "A set  B clear  L1/R1 value  X rec  Y length  START play",
                "Effects": "A on/off  LEFT/RIGHT amount  L1/R1 rate  X random  Y all off  B back"}.get(self.imode)

    def mode_pills(self, h):
        if self.imode == "Lead":
            return [("Y  OCT UP", "Y" in h), ("L1  OCT DOWN", "L1" in h), ("R1  SHARP", "R1" in h),
                    ("GLIDE %s" % ("ON" if self.glide_time() else "OFF"), bool(self.glide_time()))]
        if self.imode == "Drone":
            return [("Y  ADD 3RD", "Y" in h), ("TAP = ON/OFF", False), ("PLAY ON TOP", False),
                    ("L3  LEAD/PLAY", False)]
        if self.imode == "Drums":
            return [("Y  SHAKER", "Y" in h), ("L1  SOFT", "L1" in h), ("R1  ACCENT", "R1" in h),
                    ("X REC IN SEQ", self.seq_rec)]
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

    def draw_page(self, c):
        if self.imode == "Sequencer":
            self.draw_seq(c)
        else:
            self.draw_fx_page(c)

    def draw_seq(self, c):
        mm = M()
        e = getattr(self.eng, "eng", None)
        n = self.seq["len"]
        top = 48
        bottom = mm.L["tiles_y"] + mm.L["tile_h"]
        title = "SEQUENCER   %d steps   %s%s" % (n, "PLAYING" if self.seq_on else "stopped",
                                                 "   REC" if self.seq_rec else "")
        self.text(c, title, self.f_small, mm.ACCENT if self.seq_on else mm.DIM, (20, top))
        top += 20
        rh = (bottom - top) // len(SEQ_TRACKS)
        lw = 92
        page = self.seq_col // 16
        vis = min(16, n)
        cw = (mm.BASE_W - 20 - lw - 10) / vis
        play = ((e.seq_i - 1) % n) if (e and self.seq_on) else -1
        sc = mm.SCALES[self.scale]
        for r, t in enumerate(SEQ_TRACKS):
            y = top + r * rh
            sel_row = r == self.seq_row
            self.text(c, t.upper(), self.f_small, mm.ACCENT if sel_row else mm.DIM, (20, y + rh // 2 - 7))
            row = self.seq["tracks"][t]
            for k in range(vis):
                i = page * 16 + k
                if i >= n:
                    break
                x = int(20 + lw + k * cw)
                rect = pygame.Rect(x, y + 2, int(cw) - 3, rh - 4)
                base = mm.PANEL if (i // 4) % 2 == 0 else self.mix(mm.PANEL, mm.BG, 0.45)
                v = row[i]
                col = base
                if v is not None:
                    col = mm.ACCENT if t in SEQ_DRUM else (mm.ACCENT2 if t == "Lead" else mm.MOD_ON)
                    if t in SEQ_DRUM:
                        col = self.mix(base, col, 0.35 + 0.65 * v[1])
                if i == play:
                    col = self.mix(col, (255, 255, 255), 0.35)
                pygame.draw.rect(c, col, rect, border_radius=4)
                if v is not None and t not in SEQ_DRUM and rh > 22:
                    if t == "Chords":
                        pc, iv, _ = mm.build_chord(self.key, self.scale, v[0], {kk: True for kk in v[1]})
                        lab = mm.roman_for(v[0], iv)
                    else:
                        lab = mm.NOTE_NAMES[(self.key + sc[v[0]] + v[2]) % 12]
                    self.text(c, lab, self.f_small, mm.BG, rect.center, center=True)
                if sel_row and i == self.seq_col:
                    pygame.draw.rect(c, mm.INK, rect.inflate(4, 4), 2, border_radius=5)
        if n > 16:
            self.text(c, "page %d/%d" % (page + 1, n // 16), self.f_small, mm.DIM, (mm.BASE_W - 20, 48), right=True)

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
