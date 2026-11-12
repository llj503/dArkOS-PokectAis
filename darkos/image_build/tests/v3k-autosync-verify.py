#!/usr/bin/env python3
"""Verify game->GUI automatic mouse-mode switching, and leave the device in
the Vita3K GUI so the user can use the pointer immediately.

Flow: stop any stale session -> launch the game through the real ES path ->
inject PS / Right / Enter (in-game menu "Exit to app list") -> wait for the
mapper's journal poll -> assert it flipped to gui mode and the mouse node is
alive. On success the session is intentionally left running.
"""
import ctypes
import fcntl
import os
import struct
import subprocess
import sys
import time

KEYS = {"p": 25, "right": 106, "enter": 28}
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EV_SYN, EV_KEY = 0x00, 0x01
ZIP = "/roms/psvita/Blast Em Bunnies (PCSE00328).zip"
PAD_LOG = "/roms/vita3k/vita3k-pad.log"


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


def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def sudo(*cmd):
    return sh("sudo", *cmd)


def make_keyboard():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
    for k in KEYS.values():
        fcntl.ioctl(fd, UI_SET_KEYBIT, k)
    dev = UInputUserDev()
    dev.name = b"v3k-autosync-verify"
    dev.id = (0x03, 0x1234, 0x5683, 0x0001)
    os.write(fd, bytes(dev))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.6)
    return fd


def send(fd, name):
    k = KEYS[name]
    for v in (1, 0):
        os.write(fd, struct.pack("qqHHi", 0, 0, EV_KEY, k, v))
        os.write(fd, struct.pack("qqHHi", 0, 0, EV_SYN, 0, 0))
        if v:
            time.sleep(0.09)
    log("sent", name)
    time.sleep(0.35)


def main():
    # Leave any stale session behind (the running mapper is the old build).
    sudo("systemctl", "stop", "psvita-session.service")
    sudo("systemctl", "reset-failed", "psvita-session.service")
    time.sleep(3)
    log("stale session stopped, ES =", sh("systemctl", "is-active", "emulationstation").stdout.strip())
    sudo("chmod", "666", "/dev/uinput")
    env = dict(os.environ, PSVITA_WESTON_DEBUG="0")
    log("launching game (real ES path)")
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
    log("mapper log at game:", open(PAD_LOG).read().strip().replace("\n", " | "))

    fd = make_keyboard()
    try:
        log("== in-game menu: PS, Right, Enter (Exit to app list) ==")
        send(fd, "p")
        time.sleep(0.8)
        send(fd, "right")
        send(fd, "enter")
        # mapper polls the journal every 5 s
        for i in range(6):
            time.sleep(3)
            txt = open(PAD_LOG).read()
            if "mode -> gui (game closed)" in txt:
                log("AUTO_SWITCH_DETECTED after", (i + 1) * 3, "s")
                break
        mapper = open(PAD_LOG).read().strip()
        log("mapper log final:", mapper.replace("\n", " | "))
        ok = "mode -> gui (game closed)" in mapper
        log("AUTO_SWITCH", "OK" if ok else "FAIL")
        nodes = sh("python3", "-c",
                   "import evdev;print([evdev.InputDevice(p).name for p in evdev.list_devices()])").stdout.strip()
        log("mouse node alive:", "vita3k-mouse" in nodes, nodes)
        log("JOURNAL:", sudo("journalctl", "-u", "psvita-session.service",
                             "--since", "-3min", "--no-pager", "-o", "cat",
                             "-g", "Main executable|Game closed|Title:").stdout.strip().replace("\n", " | "))
        log("AUTOSYNC_VERIFY_DONE session left running in Vita3K GUI")
        return 0 if ok else 1
    finally:
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(fd)


if __name__ == "__main__":
    rc = main()
    if rc != 0:
        sudo("systemctl", "stop", "psvita-session.service")
        time.sleep(2)
        if sh("systemctl", "is-active", "emulationstation").stdout.strip() != "active":
            sudo("systemctl", "start", "emulationstation")
        log("failed: restored ES")
    sys.exit(rc)
