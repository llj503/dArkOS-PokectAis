#!/usr/bin/env python3
"""Verify vita3k-pad.py: clone pad -> mapper -> uinput keyboard keys, and the
Select+Start combo killing a dummy process named Vita3K."""
import os
import select
import struct
import subprocess
import sys
import time

import evdev

BTN = {"a": 304, "b": 305, "x": 307, "y": 308, "l1": 310, "r1": 311,
       "select": 314, "start": 315, "up": 544, "down": 545}
ABS = {0: 32767, 1: 32767, 3: 32767, 4: 32767, 16: 1, 17: 1}
import ctypes
import fcntl
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
    print(" ".join(str(x) for x in a), flush=True)


def make_clone(info):
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    for bit in (EV_KEY, 0x03, EV_SYN):
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
    time.sleep(0.6)
    return fd


def main():
    real = next(evdev.InputDevice(p) for p in evdev.list_devices()
                if evdev.InputDevice(p).name == "rk3562-joystick")
    fd = make_clone(real.info)
    log("clone up")
    subprocess.run(["sudo", "cp", "/bin/sleep", "/tmp/Vita3K"], check=True)
    dummy = subprocess.Popen(["/tmp/Vita3K", "600"])
    log("dummy pid", dummy.pid)
    mp = subprocess.Popen(["python3", "/home/ark/vita3k-pad.py", "Vita3K"],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(1.5)
    log("mapper alive", mp.poll() is None)
    sinks = []
    for p in evdev.list_devices():
        d = evdev.InputDevice(p)
        caps = d.capabilities()
        if EV_KEY in caps and 28 in caps[EV_KEY] and not d.phys:
            sinks.append((p, d.name, os.open(p, os.O_RDONLY | os.O_NONBLOCK)))
    log("sinks:", [(p, n) for p, n, _ in sinks])

    def ev(t, c, v):
        os.write(fd, struct.pack("qqHHi", 0, 0, t, c, v))

    def drain(tag):
        time.sleep(0.25)
        for p, n, sfd in sinks:
            r, _, _ = select.select([sfd], [], [], 0.2)
            if not r:
                continue
            data = os.read(sfd, 4096)
            for off in range(0, len(data) - 23, 24):
                _, _, t, c, v = struct.unpack_from("qqHHi", data, off)
                if t == EV_KEY:
                    log(f"  [{tag}] {n}: key={c} val={v}")

    def press(name):
        ev(EV_KEY, BTN[name], 1); ev(EV_SYN, 0, 0)
        time.sleep(0.07)
        ev(EV_KEY, BTN[name], 0); ev(EV_SYN, 0, 0)
        log("pressed", name)
        drain(name)

    for b in ("a", "b", "r1", "up"):
        press(b)
    log("stick left")
    ev(0x03, 0, -30000); ev(EV_SYN, 0, 0)
    drain("stick")
    ev(0x03, 0, 0); ev(EV_SYN, 0, 0)
    drain("stick-center")
    log("combo select+start")
    ev(EV_KEY, BTN["select"], 1); ev(EV_SYN, 0, 0)
    time.sleep(0.1)
    ev(EV_KEY, BTN["start"], 1); ev(EV_SYN, 0, 0)
    time.sleep(1.0)
    log("dummy alive", dummy.poll() is None, "mapper alive", mp.poll() is None)
    out = mp.stdout.read() if mp.poll() is not None else ""
    log("mapper output:", out.strip())
    dummy.kill()
    mp.kill()
    subprocess.run(["sudo", "rm", "-f", "/tmp/Vita3K"])
    fcntl.ioctl(fd, UI_DEV_DESTROY)
    os.close(fd)
    for _, _, s in sinks:
        os.close(s)
    log("PADMAP_TEST_DONE")


main()