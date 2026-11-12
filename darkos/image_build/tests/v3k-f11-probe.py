#!/usr/bin/env python3
"""Probe: does F11 expose Vita3K's Qt main window under Weston kiosk-shell?

Starts the game through the real ES path with --debug enabled, screenshots
before/after a single F11 key, and dumps weston's scene-graph. If the main
window with the menu/toolbar never appears, in-game menu mode B needs a
different implementation.
"""
import ctypes
import fcntl
import os
import struct
import subprocess
import sys
import time

OUT = "/home/ark/vita3k-install"
RT = "/run/vita3k"
SOCK = "wayland-vita3k"
ZIP = "/roms/psvita/Blast Em Bunnies (PCSE00328).zip"
KEY_F11 = 87
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
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


def send_f11():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
    fcntl.ioctl(fd, UI_SET_KEYBIT, KEY_F11)
    dev = UInputUserDev()
    dev.name = b"v3k-f11-probe"
    dev.id = (0x03, 0x1234, 0x5681, 0x0001)
    os.write(fd, bytes(dev))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.6)
    try:
        for v in (1, 0):
            os.write(fd, struct.pack("qqHHi", 0, 0, EV_KEY, KEY_F11, v))
            os.write(fd, struct.pack("qqHHi", 0, 0, EV_SYN, 0, 0))
            time.sleep(0.08)
        log("F11 sent")
    finally:
        fcntl.ioctl(fd, UI_DEV_DESTROY)
        os.close(fd)


def scene(label):
    r = sh("timeout", "-s", "KILL", "8", "env", f"XDG_RUNTIME_DIR={RT}",
           f"WAYLAND_DISPLAY={SOCK}", "weston-debug", "scene-graph")
    lines = [l.strip() for l in r.stdout.splitlines() if "xdg_toplevel" in l or "SHM buffer" in l or "dmabuf" in l]
    log(f"scene {label}:", lines[:8] or "(no toplevel lines)")
    return lines


def main():
    os.makedirs(OUT, exist_ok=True)
    if sh("systemctl", "is-active", "psvita-session.service").stdout.strip() == "active":
        log("ABORT: psvita-session is active")
        return 1
    sudo("chmod", "666", "/dev/uinput")
    sudo("systemctl", "reset-failed", "psvita-session.service")
    env = dict(os.environ, PSVITA_WESTON_DEBUG="1")
    log("launching game with weston --debug")
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
    time.sleep(12)  # let shaders settle so screenshots are stable
    shot("f11-before.png")
    scene("before")
    send_f11()
    time.sleep(2)
    shot("f11-after.png")
    scene("after")
    log("journal fullscreen hints:")
    j = sudo("journalctl", "-u", "psvita-session.service", "--since", "-3min", "--no-pager").stdout
    for l in j.splitlines():
        if "fullscreen" in l.lower() or "Fullscreen" in l:
            log(" ", l.strip()[:180])
    log("PROBE_DONE compare f11-before.png / f11-after.png; look for the Qt menu/toolbar")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        sudo("systemctl", "stop", "psvita-session.service")
        sudo("systemctl", "reset-failed", "psvita-session.service")
        time.sleep(2)
        if sh("systemctl", "is-active", "emulationstation").stdout.strip() != "active":
            sudo("systemctl", "start", "emulationstation")
        log("post: ES", sh("systemctl", "is-active", "emulationstation").stdout.strip(),
            "session", sh("systemctl", "is-active", "psvita-session.service").stdout.strip())
