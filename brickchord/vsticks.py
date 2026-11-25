# No-sticks mode: two buttons stand in for the analog sticks, for the original
# TrimUI Brick and every other handheld without sticks.
#
#   F1 tap            = click the left stick (L3)
#   F1 held + D-pad   = push the left stick that way (8 directions, diagonals too)
#   F2 tap            = click the right stick (R3)
#   F2 held + D-pad   = push the right stick
#
# A held direction starts at 60% of a full push and grows to 100% over 0.8 s, so a
# short press is gentle and a long one is strong, like pushing a stick further.
# Some controls work better from a D-pad in their own way:
#   Brickchord / Bricklab chord types latch: F1 + a direction picks the chord type and
#     it stays until you pick the same direction again, so the D-pad is free to play.
#   The L3 mode wheel steers with the plain D-pad while it is open.
#   Brickglide's strum sweeps: F1 + LEFT or RIGHT strums across the whole chord.
#   Brickchop's Quick Edit (SELECT held): X / B pick, Y / A change, no F button needed.
# F1 and F2 are learned like the other buttons, so any spare button can be used.
import math
import re
import time

import edition

DIRS = ("UP", "DOWN", "LEFT", "RIGHT")
FKEYS = {"F1": "L", "F2": "R"}
CLICK = {"F1": "L3", "F2": "R3"}
DIAMOND = {"X": "UP", "B": "DOWN", "Y": "LEFT", "A": "RIGHT"}
STICK_MODES = ["Auto", "Analog", "Buttons"]
TAP_SECS = 0.4
RELEASE_GRACE = 0.12       # a diagonal let go one half at a time still counts as the diagonal

# On-screen text: what the sticks are called on a handheld that has them, and what to
# press instead. Ordered: longer phrases first.
_TEXT = [
    (r"click (?:the )?right stick(?: \(R3\))?", "tap F2"),
    (r"click (?:the )?left stick(?: \(L3\))?", "tap F1"),
    (r"click R stick", "tap F2"),
    (r"\s*\(press the left stick in\)", ""),
    (r"push (?:the )?left stick", "hold F1 + D-pad"),
    (r"push (?:the )?right stick", "hold F2 + D-pad"),
    (r"stick \^v pick  <> change", "X/B pick  Y/A change"),
    (r"stick \^v picks, <> changes", "X/B picks, Y/A changes"),
    (r"\bL[- ]stick\b", "F1+pad"),
    (r"\bR[- ]stick\b", "F2+pad"),
    (r"\bleft stick\b", "F1 + D-pad"),
    (r"\bright stick\b", "F2 + D-pad"),
    (r"\bL3\b", "F1"),
    (r"\bR3\b", "F2"),
]
_TEXT = [(re.compile(p, re.I), r) for p, r in _TEXT]


def _swap(s):
    for rx, rep in _TEXT:
        s = rx.sub(lambda m, rep=rep: rep.upper() if m.group(0).isupper() and rep else rep, s)
    return s


class VSticksMixin:
    # ------------------------------------------------------------ on or off
    def vs_mode(self):
        m = self.cfg["settings"].get("stick_mode", "Auto")
        return m if m in STICK_MODES else "Auto"

    def vs_has_analog(self):
        return any(j.get_numaxes() >= 2 for j in self.inp.joys)

    def vs_on(self):
        m = self.vs_mode()
        if m == "Buttons":
            return True
        if m == "Analog":
            return False
        return not self.vs_has_analog()

    def stick_specs(self):
        """What update_sticks reads: the learned analog axes, or the virtual sticks."""
        if self.vs_on():
            return {"lx": ["v", "lx"], "ly": ["v", "ly"], "rx": ["v", "rx"], "ry": ["v", "ry"]}
        return self.cfg.get("sticks") or {}

    def vs_val(self, key):
        return self.__dict__.get("vs_vals", {}).get(key, 0.0)

    def vs_learned(self):
        return {n for n in (self.cfg.get("buttons") or {}).values() if n in FKEYS}

    # ------------------------------------------------------------ events
    def vs_state(self):
        st = self.__dict__.get("_vs")
        if st is None:
            st = self._vs = {"F": {}, "dirs": {"L": [], "R": []}, "t": {"L": 0.0, "R": 0.0},
                             "swallow": set(), "latch": None, "latch_cleared": False, "sweep": None,
                             "new": {"L": False, "R": False}, "prev": {"L": (), "R": ()},
                             "keep": {"L": None, "R": None}}
        return st

    def vs_owner(self, name):
        """Which virtual stick a D-pad (or, in Quick Edit, a face) button is steering now."""
        st = self.vs_state()
        if name in DIRS:
            if "F1" in st["F"]:
                return "L"
            if "F2" in st["F"]:
                return "R"
            if getattr(self, "wheel_open", False) and not (edition.AMBIENT or edition.CHOP):
                return "L"                               # the mode wheel: the plain D-pad steers it
            return None
        if name in DIAMOND and edition.CHOP and getattr(self, "csel_down", False) and not st["F"]:
            return "L"                                   # Quick Edit: X/B pick, Y/A change
        return None

    def vs_filter(self, events):
        """The button events after the virtual sticks have taken theirs."""
        if not self.vs_on():
            return [e for e in events if e[0] not in FKEYS]     # real sticks: F1/F2 do nothing
        st = self.vs_state()
        now = time.perf_counter()
        out = []
        for name, down in events:
            if name in FKEYS:
                if down:
                    st["F"][name] = {"t": now, "used": False, "fwd": False}
                else:
                    b = st["F"].pop(name, None)
                    side = FKEYS[name]
                    if b and b["fwd"]:
                        out.append((CLICK[name], False))
                    elif b and not b["used"] and now - b["t"] < TAP_SECS:
                        out += [(CLICK[name], True), (CLICK[name], False)]
                    if st["dirs"][side]:
                        st["dirs"][side] = []            # their releases are still swallowed
                continue
            if name in st["swallow"] and not down:
                st["swallow"].discard(name)
                for side in ("L", "R"):
                    d = st["dirs"][side]
                    key = DIAMOND.get(name, name)
                    if key in d:
                        d.remove(key)
                continue
            side = self.vs_owner(name) if down else None
            if side:
                key = DIAMOND.get(name, name)
                if not st["dirs"][side]:
                    st["t"][side] = now
                    st["new"][side] = True
                if key not in st["dirs"][side]:
                    st["dirs"][side].append(key)
                st["swallow"].add(name)
                if name in self.inp.held:
                    self.inp.held.discard(name)          # not a chord or pad being held
                    self.inp.ghost.add(name)
                for f, b in st["F"].items():
                    if FKEYS[f] == side:
                        b["used"] = True
                continue
            if down and st["F"]:
                # another button while F is held: no click on release. Brickchop keeps
                # R3 + a pad (erase it from the pattern), so the click is held for it.
                for f, b in st["F"].items():
                    b["used"] = True
                    if edition.CHOP and f == "F2" and not b["fwd"]:
                        b["fwd"] = True
                        out.append(("R3", True))
            out.append((name, down))
        return out

    # ------------------------------------------------------------ per frame
    def vs_style(self, side):
        if side == "R":
            return "hold"
        if getattr(self, "wheel_open", False):
            return "hold"
        if edition.AMBIENT:
            held = self.inp.held
            if (edition.PLAY and "L2" not in held and "R2" not in held
                    and getattr(self, "ascrub", None) is None and not getattr(self, "aexp", None)):
                return "sweep"
            return "hold"
        if edition.CHOP:
            return "hold"
        if getattr(self, "imode", "Play") == "Play":
            return "latch"                               # chord types: pick one, then play
        return "hold"

    def vs_tick(self):
        if not self.vs_on():
            return
        st = self.vs_state()
        now = time.perf_counter()
        vals = self.__dict__.setdefault("vs_vals", {})
        for side, (kx, ky) in (("L", ("lx", "ly")), ("R", ("rx", "ry"))):
            d = st["dirs"][side]
            cur, prev = set(d), set(st["prev"][side])
            st["prev"][side] = tuple(d)
            if cur and cur < prev:                       # half of a diagonal let go: hold it a moment
                st["keep"][side] = (prev, now + RELEASE_GRACE)
            elif cur and not (st["keep"][side] and cur <= st["keep"][side][0]):
                st["keep"][side] = None
            keep = st["keep"][side]
            if cur and keep and now < keep[1]:
                cur = keep[0]
            elif not cur:
                st["keep"][side] = None
            dx = ("RIGHT" in cur) - ("LEFT" in cur)
            dy = ("UP" in cur) - ("DOWN" in cur)
            new = st["new"][side]
            st["new"][side] = False
            style = self.vs_style(side)
            if side == "L" and style != "latch":
                st["latch"] = None
            if side == "L" and style != "sweep":
                st["sweep"] = None
            if style == "latch":
                if dx or dy:
                    u = (dx / math.hypot(dx, dy), dy / math.hypot(dx, dy))
                    if new and st["latch"] is not None and \
                            abs(u[0] - st["latch"][0]) < 1e-6 and abs(u[1] - st["latch"][1]) < 1e-6:
                        st["latch"], st["latch_cleared"] = None, True
                        self.flash("CHORD TYPE OFF")
                    elif not st["latch_cleared"]:
                        st["latch"] = u
                else:
                    st["latch_cleared"] = False
                x, y = st["latch"] if st["latch"] else (0.0, 0.0)
            elif style == "sweep" and dx and not dy:
                sw = st["sweep"]
                if new or sw is None or sw["dir"] != dx:
                    sw = st["sweep"] = {"dir": dx, "t0": now}
                k = min(1.0, (now - sw["t0"]) / 0.28)
                x, y = -dx + 2 * dx * k, 0.0             # across the strings, low to high or back
            else:
                if style == "sweep":
                    st["sweep"] = None
                if dx or dy:
                    m = 0.6 + 0.4 * min(1.0, (now - st["t"][side]) / 0.8)
                    r = math.hypot(dx, dy)
                    x, y = m * dx / r, m * dy / r
                else:
                    x = y = 0.0
            vals[kx], vals[ky] = x, y

    # ------------------------------------------------------------ text
    def vs_text(self, s):
        if not s or getattr(self, "vs_raw", False) or not self.vs_on():
            return s
        c = self.__dict__.setdefault("_vs_tc", {})
        out = c.get(s)
        if out is None:
            if len(c) > 800:
                c.clear()
            out = c[s] = _swap(s)
        return out

    # ------------------------------------------------------------ setup
    def vs_setup(self):
        """On a handheld without sticks: ask once for the two stick buttons."""
        if not self.vs_on() or self.cfg.get("fkeys_asked") or not self.inp.joys:
            return
        if len(self.vs_learned()) < 2:
            self.learn(only=("F1", "F2"))
        self.cfg["fkeys_asked"] = True
        self.save_cfg()
