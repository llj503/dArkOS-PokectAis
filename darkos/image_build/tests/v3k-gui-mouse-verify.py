#!/usr/bin/env python3
"""End-to-end verification of the Vita3K GUI mouse mode on dArkOS.

Creates a clone of the handheld pad BEFORE the launcher starts (the mapper
binds the newest rk3562-joystick node), opens the Vita3K GUI via
psvita-launch.sh with no ROM, then listens on the `vita3k-mouse` uinput node
while injecting stick / d-pad / A / B events on the clone.
"""
import ctypes
import fcntl
import os
import select
import struct
import subprocess
import sys
import threading
import time

import evdev

OUT = "/home/ark/vita3k-install"
RT = "/run/vita3k"
SOCK = "wayland-vita3k"
BTN = {"a": 304, "b": 305, "x": 307, "y": 308, "l1": 310, "r1": 311,
       "select": 314, "start": 315, "up": 544, "down": 545,
       "left": 546, "right": 547}
ABS_BITS = {0: 32767, 1: 32767, 3: 32767, 4: 32767, 16: 1, 17: 1}
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EV_SYN, EV_KEY, EV_ABS, EV_REL = 0x00, 0x01, 0x03, 0x02
BTN_LEFT, BTN_RIGHT = 0x110, 0x111


class UInputUserDev(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char * 80),
                ("id", ctypes.c_uint16 * 4),
                ("ff_effects_max", ctypes.c_uint32),
                ("absmax", ctypes.c_int32 * 64),
                ("absmin", ctypes.c_int32 * 64),
                ("absfuzz", ctypes.c_int32 * 64),
                ("absflat", ctypes.c_int32 * 64)]


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", " ".join(str(x) for x in a), flush=True)


def sh(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def sudo(*cmd):
    return sh("sudo", *cmd)


def make_clone(info):
    before = set(evdev.list_devices())
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    for bit in (EV_KEY, EV_ABS, EV_SYN):
        fcntl.ioctl(fd, UI_SET_EVBIT, bit)
    for c in BTN.values():
        fcntl.ioctl(fd, UI_SET_KEYBIT, c)
    for c in ABS_BITS:
        fcntl.ioctl(fd, UI_SET_ABSBIT, c)
    dev = UInputUserDev()
    dev.name = b"rk3562-joystick"
    dev.id = (info.bustype, info.vendor, info.product, info.version)
    for c, mx in ABS_BITS.items():
        dev.absmax[c] = mx
        dev.absmin[c] = -mx
    os.write(fd, bytes(dev))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.8)
    new = [p for p in evdev.list_devices() if p not in before]
    return fd, new


def find_mouse():
    for p in evdev.list_devices():
        try:
            d = evdev.InputDevice(p)
        except OSError:
            continue
        if d.name == "vita3k-mouse":
            return d
        d.close()
    return None


def shot(name):
    for f in os.listdir(OUT):
        if f.startswith("wayland-screenshot-"):
            os.remove(os.path.join(OUT, f))
    sh("sudo", "-u", "ark", "env", "HOME=/home/ark", f"XDG_RUNTIME_DIR={RT}",
       f"WAYLAND_DISPLAY={SOCK}", "weston-screenshooter", cwd=OUT)
    time.sleep(1)
    shots = sorted((f for f in os.listdir(OUT) if f.startswith("wayland-screenshot-")),
                   key=lambda f: os.path.getmtime(os.path.join(OUT, f)))
    if shots:
        os.replace(os.path.join(OUT, shots[-1]), os.path.join(OUT, name))
        log("shot", name)
    else:
        log("shot FAILED", name)


def main():
    os.makedirs(OUT, exist_ok=True)
    if sh("systemctl", "is-active", "psvita-session.service").stdout.strip() == "active":
        log("ABORT: psvita-session is active")
        return 1

    real = None
    for p in evdev.list_devices():
        try:
            d = evdev.InputDevice(p)
        except OSError:
            continue
        if d.name == "rk3562-joystick":
            real = d
            break
        d.close()
    if real is None:
        log("NO_REAL_PAD")
        return 1
    log("real pad", real.path)
    sudo("chmod", "666", "/dev/uinput")
    fd, new_paths = make_clone(real.info)
    log("clone paths", new_paths)

    def ev(t, c, v):
        os.write(fd, struct.pack("qqHHi", 0, 0, t, c, v))

    def press(name, hold=0.08):
        ev(EV_KEY, BTN[name], 1); ev(EV_SYN, 0, 0)
        time.sleep(hold)
        ev(EV_KEY, BTN[name], 0); ev(EV_SYN, 0, 0)
        time.sleep(0.35)
        log("pressed", name)

    def axis(a, v):
        ev(EV_ABS, a, v); ev(EV_SYN, 0, 0)

    try:
        env = dict(os.environ, PSVITA_WESTON_DEBUG="1")
        log("== launching Vita3K GUI (no ROM) ==")
        subprocess.Popen(["/usr/local/bin/psvita-launch.sh"], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pid = ""
        for _ in range(90):
            pid = sh("pidof", "Vita3K").stdout.strip()
            if pid:
                break
            time.sleep(1)
        if not pid:
            log("VITA3K_NOT_RUNNING")
            return 1
        log("Vita3K pid", pid)
        time.sleep(4)
        try:
            log("mapper log:", open("/roms/vita3k/vita3k-pad.log").read().strip()[-400:])
        except OSError as ex:
            log("mapper log unreadable", ex)

        mouse = None
        for _ in range(30):
            mouse = find_mouse()
            if mouse:
                break
            time.sleep(0.5)
        if mouse is None:
            log("NO_MOUSE_NODE")
            return 1
        log("mouse node", mouse.path, mouse.name)
        os.set_blocking(mouse.fd, False)
        events = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                r, _, _ = select.select([mouse.fd], [], [], 0.1)
                if not r:
                    continue
                while True:
                    try:
                        e = mouse.read_one()
                    except BlockingIOError:
                        break
                    except OSError:
                        return
                    if e is None:
                        break
                    events.append((e.type, e.code, e.value))

        th = threading.Thread(target=reader, daemon=True)
        th.start()
        shot("gui-mouse-before.png")

        log("== injecting stick / dpad / A / B on the clone pad ==")
        axis(0, 22000); time.sleep(0.8); axis(0, 0); time.sleep(0.2)   # stick right
        axis(1, 22000); time.sleep(0.8); axis(1, 0); time.sleep(0.2)   # stick down
        ev(EV_KEY, 547, 1); ev(EV_SYN, 0, 0)                            # dpad right hold
        time.sleep(0.6)
        ev(EV_KEY, 547, 0); ev(EV_SYN, 0, 0); time.sleep(0.2)
        press("a"); time.sleep(0.6); press("a")                          # two single clicks
        press("b")                                                        # right click
        time.sleep(0.6)
        stop.set(); th.join(timeout=1)

        rel = [e for e in events if e[0] == EV_REL]
        left = [e for e in events if e[0] == EV_KEY and e[1] == BTN_LEFT]
        right = [e for e in events if e[0] == EV_KEY and e[1] == BTN_RIGHT]
        log("REL_X=", sum(1 for e in rel if e[1] == 0),
            "REL_Y=", sum(1 for e in rel if e[1] == 1))
        log("REL sample", rel[:8])
        log("BTN_LEFT events", len(left), "BTN_RIGHT events", len(right))
        ok = len(rel) > 5 and len(left) >= 2 and len(right) >= 1
        log("MOUSE_LINK", "OK" if ok else "FAIL")
        shot("gui-mouse-after.png")
        wl = subprocess.run(["grep", "-i", "vita3k-mouse", "/roms/vita3k/weston.log"],
                            capture_output=True, text=True).stdout.strip().splitlines()
        log("weston mouse lines:", wl[-6:])
        return 0 if ok else 1
    finally:
        sudo("systemctl", "stop", "psvita-session.service")
        sudo("systemctl", "reset-failed", "psvita-session.service")
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(fd)
        real.close()
        time.sleep(2)
        if sh("systemctl", "is-active", "emulationstation").stdout.strip() != "active":
            sudo("systemctl", "start", "emulationstation")
        log("post: ES", sh("systemctl", "is-active", "emulationstation").stdout.strip(),
            "session", sh("systemctl", "is-active", "psvita-session.service").stdout.strip(),
            "V3K", sh("pidof", "Vita3K").stdout.strip() or "none")


sys.exit(main())
