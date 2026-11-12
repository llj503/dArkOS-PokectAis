#!/usr/bin/env python3
"""End-to-end pad test through the real ES launcher.

Creates a clone of the handheld pad (same evdev name), starts psvita-launch.sh
with no ROM (the Vita3K GUI), then drives the GUI with the clone and finally
presses Select+Start to check the whole exit path brings ES back.
"""
import ctypes
import fcntl
import os
import struct
import subprocess
import sys
import time

import evdev

OUT = "/home/ark/vita3k-install"
RT = "/run/vita3k"
SOCK = "wayland-vita3k"
BTN = {"a": 304, "b": 305, "x": 307, "y": 308, "l1": 310, "r1": 311,
       "select": 314, "start": 315, "up": 544, "down": 545,
       "left": 546, "right": 547}
ABS = {0: 32767, 1: 32767, 3: 32767, 4: 32767, 16: 1, 17: 1}
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03


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


def nodes():
    out = {}
    for p in evdev.list_devices():
        try:
            d = evdev.InputDevice(p)
        except OSError:
            continue
        out[p] = d.name
        d.close()
    return out


def make_clone(info):
    before = set(nodes())
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    for bit in (EV_KEY, EV_ABS, EV_SYN):
        fcntl.ioctl(fd, UI_SET_EVBIT, bit)
    for c in BTN.values():
        fcntl.ioctl(fd, UI_SET_KEYBIT, c)
    for c in ABS:
        fcntl.ioctl(fd, UI_SET_ABSBIT, c)
    dev = UInputUserDev()
    dev.name = b"rk3562-joystick"
    dev.id = (info.bustype, info.vendor, info.product, info.version)
    for c, mx in ABS.items():
        dev.absmax[c] = mx
        dev.absmin[c] = -mx
    os.write(fd, bytes(dev))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.8)
    new = [p for p in nodes() if p not in before]
    return fd, new


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
    real = None
    for p, n in nodes().items():
        if n == "rk3562-joystick":
            real = evdev.InputDevice(p)
            break
    if real is None:
        log("NO_REAL_PAD")
        return 1
    log("real pad", real.path, "list order:", list(nodes()))
    sudo("chmod", "666", "/dev/uinput")
    fd, clone_paths = make_clone(real.info)
    log("clone paths", clone_paths)

    clone = None
    for p in clone_paths:
        try:
            clone = evdev.InputDevice(p)
        except OSError:
            pass
    if clone is None:
        log("CLONE_NOT_FOUND")
        return 1

    def ev(t, c, v):
        os.write(fd, struct.pack("qqHHi", 0, 0, t, c, v))

    def press(name, hold=0.08):
        ev(EV_KEY, BTN[name], 1)
        ev(EV_SYN, 0, 0)
        time.sleep(hold)
        ev(EV_KEY, BTN[name], 0)
        ev(EV_SYN, 0, 0)
        time.sleep(0.35)
        log("pressed", name)

    env = dict(os.environ, PSVITA_WESTON_DEBUG="1")
    log("== launching GUI via psvita-launch.sh ==")
    proc = subprocess.Popen(["/usr/local/bin/psvita-launch.sh"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(90):
            if sh("pidof", "Vita3K").stdout.strip():
                break
            time.sleep(1)
        pid = sh("pidof", "Vita3K").stdout.strip()
        if not pid:
            log("VITA3K_NOT_RUNNING")
            print(sudo("journalctl", "-u", "psvita-session.service", "-n", "30",
                       "--no-pager").stdout, flush=True)
            return 1
        log("Vita3K pid", pid)
        time.sleep(6)
        log("mapper pid", sh("pgrep", "-f", "vita3k-pad.py").stdout.strip() or "DEAD")
        log("ogage", sh("pidof", "ogage").stdout.strip() or "DEAD",
            "killer_daemon", sh("pidof", "killer_daemon").stdout.strip() or "stopped")
        log("-- mapper log --")
        print(open("/roms/vita3k/vita3k-pad.log").read().strip(), flush=True)
        log("-- input nodes --")
        for p, n in nodes().items():
            log("  ", p, n)
        log("-- weston input lines --")
        wl = open("/roms/vita3k/weston.log", errors="replace").read().splitlines()
        for line in wl:
            if "event" in line or "keyboard" in line or "ignoring" in line:
                log("  ", line.strip())
        shot("padlive-0.png")

        log("== driving the GUI with the clone pad ==")
        for b in ("down", "down", "right", "a", "b"):
            press(b)
        shot("padlive-1.png")
        log("stick left")
        ev(EV_ABS, 0, -30000)
        ev(EV_SYN, 0, 0)
        time.sleep(0.5)
        ev(EV_ABS, 0, 0)
        ev(EV_SYN, 0, 0)
        time.sleep(0.5)
        shot("padlive-2.png")

        log("== Select+Start ==")
        ev(EV_KEY, BTN["select"], 1)
        ev(EV_SYN, 0, 0)
        time.sleep(0.15)
        ev(EV_KEY, BTN["start"], 1)
        ev(EV_SYN, 0, 0)
        for _ in range(40):
            if not sh("pidof", "Vita3K").stdout.strip():
                break
            time.sleep(0.5)
        log("Vita3K after combo:", sh("pidof", "Vita3K").stdout.strip() or "GONE")
        log("-- mapper log tail --")
        print(open("/roms/vita3k/vita3k-pad.log").read().strip()[-600:], flush=True)
        for _ in range(60):
            if sh("systemctl", "is-active", "emulationstation").stdout.strip() == "active":
                break
            time.sleep(1)
        log("ES", sh("systemctl", "is-active", "emulationstation").stdout.strip(),
            "weston", sh("pidof", "weston").stdout.strip() or "gone",
            "mapper", sh("pgrep", "-f", "vita3k-pad.py").stdout.strip() or "gone",
            "session", sh("systemctl", "is-active", "psvita-session.service").stdout.strip())
        log("ogage", sh("pidof", "ogage").stdout.strip() or "DEAD",
            "killer_daemon", sh("pidof", "killer_daemon").stdout.strip() or "DEAD")
        left = [p for p, n in nodes().items() if n == "vita3k-pad"]
        log("leftover vita3k-pad nodes:", left or "none")
        log("PAD_LIVE_DONE")
        return 0
    finally:
        if sh("pidof", "Vita3K").stdout.strip():
            sudo("kill", "-9", *sh("pidof", "Vita3K").stdout.split())
        sudo("systemctl", "stop", "psvita-session.service")
        sudo("systemctl", "reset-failed", "psvita-session.service")
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(fd)
        clone.close()
        real.close()
        time.sleep(2)
        if sh("systemctl", "is-active", "emulationstation").stdout.strip() != "active":
            sudo("systemctl", "start", "emulationstation")


sys.exit(main())