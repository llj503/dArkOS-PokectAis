#!/usr/bin/env python3
"""End-to-end verification: console-detect hotkey -> SDL2 OSD -> pending setting.

Creates a clone pad BEFORE the launcher starts (mapper and OSD both bind the
newest rk3562-joystick node), boots a game, presses Home, screenshots the OSD,
picks "简体中文" with d-pad + A, then lets the launcher apply the pending file.
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
ZIP = "/roms/psvita/Blast Em Bunnies (PCSE00328).zip"
CFG = "/roms/vita3k/config.yml"
PENDING = "/roms/vita3k/.osd-pending"
ACTIVE = "/roms/vita3k/.osd-active"

BTN = {"a": 304, "b": 305, "select": 314, "start": 315, "home": 316,
       "up": 544, "down": 545, "left": 546, "right": 547}
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EV_SYN, EV_KEY = 0x00, 0x01


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


def sudo(*cmd, **kw):
    return sh("sudo", *cmd, **kw)


def make_clone():
    before = set(evdev.list_devices())
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
    fcntl.ioctl(fd, UI_SET_EVBIT, 0x03)  # EV_ABS
    for c in BTN.values():
        fcntl.ioctl(fd, UI_SET_KEYBIT, c)
    for a in (0, 1):
        fcntl.ioctl(fd, UI_SET_ABSBIT, a)
    dev = UInputUserDev()
    dev.name = b"rk3562-joystick"
    dev.id = (0x03, 0x1234, 0x5679, 0x0001)
    for a in (0, 1):
        dev.absmax[a] = 32767
        dev.absmin[a] = -32767
    os.write(fd, bytes(dev))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.8)
    new = [p for p in evdev.list_devices() if p not in before]
    log("clone nodes", new)
    return fd, new


def press(fd, name, hold=0.08):
    c = BTN[name]
    for v in (1, 0):
        os.write(fd, struct.pack("qqHHi", 0, 0, EV_KEY, c, v))
        os.write(fd, struct.pack("qqHHi", 0, 0, EV_SYN, 0, 0))
        if v:
            time.sleep(hold)
    log("pressed", name)
    time.sleep(0.45)


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


def scene(label):
    r = sh("timeout", "-s", "KILL", "8", "env", f"XDG_RUNTIME_DIR={RT}",
           f"WAYLAND_DISPLAY={SOCK}", "weston-debug", "scene-graph")
    lines = [l.strip() for l in r.stdout.splitlines() if "top-level window" in l]
    log(f"scene {label}:", lines[:5] or "(none)")
    return lines


def cfg(key):
    for line in open(CFG, encoding="utf-8"):
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return "MISSING"


def main():
    os.makedirs(OUT, exist_ok=True)
    sudo("systemctl", "stop", "psvita-session.service")
    sudo("systemctl", "reset-failed", "psvita-session.service")
    time.sleep(3)
    sudo("chmod", "666", "/dev/uinput")
    sudo("rm", "-f", PENDING, ACTIVE)
    log("hotkey type:", sh("console-detect", "-t").stdout.strip())
    log("sys-lang before =", cfg("sys-lang"))

    fd, _ = make_clone()
    try:
        env = dict(os.environ, PSVITA_WESTON_DEBUG="1")
        log("launching game")
        subprocess.Popen(["/usr/local/bin/psvita-launch.sh", ZIP], env=env,
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
        time.sleep(12)
        log("mapper:", open("/roms/vita3k/vita3k-pad.log").read().strip().replace("\n", " | "))
        shot("osd-before.png")
        scene("before")

        log("== press Home ==")
        press(fd, "home")
        time.sleep(2.5)
        shot("osd-open.png")
        lines = scene("osd-open")
        log("OSD_WINDOW=", any("Vita3K OSD" in l for l in lines))
        log("osd active flag:", os.path.exists(ACTIVE))

        log("== Down + A (系统语言 简体中文) ==")
        press(fd, "down")
        press(fd, "a")
        time.sleep(1.5)
        log("pending:", open(PENDING).read().strip().replace("\n", " | ") if os.path.exists(PENDING) else "(none)")
        log("osd active flag after:", os.path.exists(ACTIVE))
        shot("osd-closed.png")
        scene("closed")
        log("OSD_VERIFY_DONE")
        return 0
    finally:
        # let the launcher exit normally so its cleanup applies the pending file
        out = sh("pidof", "Vita3K").stdout.strip()
        if out:
            sudo("kill", "-9", *out.split())
        time.sleep(4)
        log("sys-lang after cleanup =", cfg("sys-lang"))
        log("pending after cleanup exists =", os.path.exists(PENDING))
        log("star cards:", sh("ls", "-1", "/roms/psvita/*.sh").stdout.strip().replace("\n", " | "))
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(fd)


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        sudo("systemctl", "stop", "psvita-session.service")
        sudo("systemctl", "reset-failed", "psvita-session.service")
        time.sleep(2)
        if sh("systemctl", "is-active", "emulationstation").stdout.strip() != "active":
            sudo("systemctl", "start", "emulationstation")
        log("post ES", sh("systemctl", "is-active", "emulationstation").stdout.strip())
