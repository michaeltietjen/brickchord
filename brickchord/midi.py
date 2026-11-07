"""USB MIDI in for all three apps: watch for class-compliant MIDI devices (an
Orchid, an OP-Z, a keyboard, the SP-1) and read them on a thread. Events land in
a deque the UI drains every frame:
    ("connect", name)  ("disconnect", name)  ("on", note, velocity)  ("off", note, 0)
Plug in or out at any time; what is found is written to the log. Uses the raw
ALSA ports (/dev/snd/midiC*D*), so no MIDI library is needed."""
import collections
import glob
import os
import select
import threading
import time


def _card_name(path):
    try:
        n = os.path.basename(path)[5:].split("D")[0]
        with open("/proc/asound/card%s/id" % n) as f:
            return f.read().strip()
    except Exception:
        return os.path.basename(path)


def start():
    """Start watching; returns the event deque."""
    q = collections.deque()

    def run():
        fds, status, logged = {}, {}, [0]
        while True:
            try:
                for p in glob.glob("/dev/snd/midiC*D*"):
                    if p not in fds.values():
                        try:
                            fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
                            fds[fd] = p
                            status[fd] = 0
                            nm = _card_name(p)
                            print("MIDI in: opened %s (%s)" % (p, nm), flush=True)
                            q.append(("connect", nm))
                        except OSError as ex:
                            print("MIDI in: cannot open %s: %s" % (p, ex), flush=True)
                if not fds:
                    time.sleep(1.0)
                    continue
                r, _, _ = select.select(list(fds), [], [], 1.0)
                for fd in r:
                    try:
                        data = os.read(fd, 256)
                    except OSError:
                        data = b""
                    if not data:
                        print("MIDI in: %s went away" % fds[fd], flush=True)
                        q.append(("disconnect", _card_name(fds[fd])))
                        os.close(fd)
                        del fds[fd]
                        continue
                    msg = []
                    for b in data:
                        if b >= 0xF8:
                            continue                      # clock and other real-time bytes
                        if b & 0x80:
                            status[fd] = b
                            msg = []
                            continue
                        msg.append(b)
                        st = status[fd] & 0xF0
                        if st in (0x80, 0x90) and len(msg) == 2:
                            note, vel = msg
                            on = st == 0x90 and vel > 0
                            q.append(("on" if on else "off", note, vel))
                            if logged[0] < 40:
                                logged[0] += 1
                                print("MIDI in: note %s %d vel %d" % ("on" if on else "off", note, vel), flush=True)
                            msg = []
                        elif st in (0xA0, 0xB0, 0xE0) and len(msg) == 2:
                            msg = []
                        elif st in (0xC0, 0xD0) and len(msg) == 1:
                            msg = []
            except Exception as ex:
                print("MIDI in: error %s" % ex, flush=True)
                time.sleep(1.0)

    threading.Thread(target=run, daemon=True).start()
    return q
