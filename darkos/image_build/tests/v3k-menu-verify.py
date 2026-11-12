#!/usr/bin/env python3
"""Verify the new in-game pause menu (patch #5) on the device.

Launches the game with weston --debug, injects PS (P) through a uinput
keyboard, screenshots the menu, then exercises Resume and Exit to app list.
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
KEYS = {"p": 25, "enter": 28, "right": 106, "left": 105, "down": 108, "esc": 1, "tab": 15}
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


def make_keyboard():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
    for k in KEYS.values():
        fcntl.ioctl(fd, UI_SET_KEYBIT, k)
    dev = UInputUserDev()
    dev.name = b"v3k-menu-verify"
    dev.id = (0x03, 0x1234, 0x5682, 0x0001)
    os.write(fd, bytes(dev))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.6)
    return fd


def send(fd, name, hold=0.09):
    k = KEYS[name]
    for v in (1, 0):
        os.write(fd, struct.pack("qqHHi", 0, 0, EV_KEY, k, v))
        os.write(fd, struct.pack("qqHHi", 0, 0, EV_SYN, 0, 0))
        if v:
            time.sleep(hold)
    log("sent", name)
    time.sleep(0.35)


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


def scene(label):
    r = sh("timeout", "-s", "KILL", "8", "env", f"XDG_RUNTIME_DIR={RT}",
           f"WAYLAND_DISPLAY={SOCK}", "weston-debug", "scene-graph")
    lines = [l.strip() for l in r.stdout.splitlines() if "top-level window" in l]
    log(f"scene {label}:", lines[:6] or "(none)")
    return lines


def main():
    os.makedirs(OUT, exist_ok=True)
    if sh("systemctl", "is-active", "psvita-session.service").stdout.strip() == "active":
        log("ABORT: psvita-session active")
        return 1
    sudo("chmod", "666", "/dev/uinput")
    sudo("systemctl", "reset-failed", "psvita-session.service")
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
    fd = make_keyboard()
    try:
        shot("menu-before.png")
        scene("before")
        log("== press PS (P) ==")
        send(fd, "p")
        time.sleep(1)
        shot("menu-open.png")
        menu_lines = scene("menu-open")
        has_dialog = any("'Vita3K'" in l and "Vita3K+ v1.4" not in l for l in menu_lines)
        log("DIALOG_VISIBLE_IN_SCENE_GRAPH=", has_dialog)
        log("== Enter (Resume) ==")
        send(fd, "enter")
        time.sleep(1)
        scene("resumed")
        log("== PS again, Right, Enter (Exit to app list) ==")
        send(fd, "p")
        time.sleep(0.8)
        send(fd, "right")
        send(fd, "enter")
        time.sleep(3)
        shot("menu-after-exit.png")
        after = scene("after-exit")
        log("GAME_WINDOW_GONE=", not any("Blast 'Em Bunnies" in l for l in after))
        log("MENU_VERIFY_DONE")
        return 0
    finally:
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
        log("post: ES", sh("systemctl", "is-active", "emulationstation").stdout.strip(),
            "session", sh("systemctl", "is-active", "psvita-session.service").stdout.strip())
