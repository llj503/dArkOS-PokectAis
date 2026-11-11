#!/usr/bin/env python3
"""Pad -> uinput keyboard mapper for the Vita3K session on dArkOS.

gptokeyb (the PortMaster tool) never creates its uinput keyboard on this device:
the process holds the pad's evdev node but no /dev/uinput fd, so no key ever
reaches Weston/Qt, and its Select+Start handler runs `kill -9 $(pidof -c )` with
an empty name and then exits -- taking the whole session's input with it. This
mapper does the same job with plain evdev + uinput, no SDL and no GUID matching:

  * read the rk3562-joystick evdev node (no EVIOCGRAB, so Vita3K's own SDL pad
    and ogage's hotkeys keep working),
  * emit the keys below as a uinput keyboard. Weston/libinput ignores gamepads,
    so this is the only way the Qt GUI sees the buttons. The same keys also
    drive the emulated Vita pad: CtrlKeyboardFilter is an event filter on the
    game window, so it runs before GameWindow::keyPressEvent's ignore(). Because
    nothing grabs the pad, every button arrives twice (SDL pad + key), so the
    keys are chosen to land on the *same* Vita button as SDL's own mapping;
    psvita-launch.sh primes Vita3K's keyboard bindings to match (cross=Enter,
    circle=Escape, square=Space, triangle=Backspace, start=Insert, select=Delete,
    L1/R1/L2/R2=PageUp/PageDown/Home/End). A=Enter also activates GUI items.
  * Select+Start SIGKILLs Vita3K (it swallows SIGTERM) and exits; the launcher's
    EXIT trap then brings ES back.

Usage: vita3k-pad.py [process-name]   (default Vita3K)
"""
import ctypes
import fcntl
import os
import struct
import subprocess
import sys
import time

import evdev

TARGET = sys.argv[1] if len(sys.argv) > 1 else "Vita3K"
PAD_NAME = "rk3562-joystick"

# evdev button code -> linux key code. Edit here to remap the handheld.
BTN_MAP = {
    304: 28,    # a      -> enter     (Vita Cross)
    305: 1,     # b      -> esc       (Vita Circle)
    307: 57,    # x      -> space     (Vita Square)
    308: 14,    # y      -> backspace (Vita Triangle)
    310: 104,   # l1     -> pageup
    311: 109,   # r1     -> pagedown
    312: 102,   # l2     -> home
    313: 107,   # r2     -> end
    314: 111,   # select -> delete
    315: 110,   # start  -> insert
    544: 103,   # dpup   -> up
    545: 108,   # dpdown -> down
    546: 105,   # dpleft -> left
    547: 106,   # dpright-> right
}
SELECT, START = 314, 315

# left stick -> arrows (digital, with a dead zone)
STICK = {0: (105, 106), 1: (103, 108)}  # abs x -> left/right, abs y -> up/down
STICK_DEAD = 12000

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EV_SYN, EV_KEY = 0x00, 0x01
SYN_REPORT = 0


class UInputUserDev(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char * 80),
                ("id", ctypes.c_uint16 * 4),
                ("ff_effects_max", ctypes.c_uint32),
                ("absmax", ctypes.c_int32 * 64),
                ("absmin", ctypes.c_int32 * 64),
                ("absfuzz", ctypes.c_int32 * 64),
                ("absflat", ctypes.c_int32 * 64)]


def find_pad():
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        if dev.name == PAD_NAME:
            return dev
        dev.close()
    return None


def main():
    keys = sorted(set(BTN_MAP.values()))
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
    for k in keys:
        fcntl.ioctl(fd, UI_SET_KEYBIT, k)
    dev = UInputUserDev()
    dev.name = b"vita3k-pad"
    dev.id = (0x03, 0x1234, 0x5679, 0x0001)
    os.write(fd, bytes(dev))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.4)  # let libinput/Weston pick the keyboard up

    def ev(t, c, v):
        os.write(fd, struct.pack("qqHHi", 0, 0, t, c, v))

    def key(code, down):
        ev(EV_KEY, code, 1 if down else 0)
        ev(EV_SYN, SYN_REPORT, 0)

    stick_state = {}

    def stick(axis, value):
        neg, pos = STICK[axis]
        want = neg if value < -STICK_DEAD else (pos if value > STICK_DEAD else 0)
        old = stick_state.get(axis, 0)
        if want == old:
            return
        if old:
            key(old, False)
        if want:
            key(want, True)
        stick_state[axis] = want

    def kill_target():
        pids = subprocess.run(["pidof", TARGET], capture_output=True, text=True).stdout.split()
        print(f"vita3k-pad: Select+Start, killing {TARGET} {pids}", flush=True)
        for pid in pids:
            subprocess.run(["sudo", "kill", "-9", pid])
        return True

    try:
        warned = False
        while True:
            pad = find_pad()
            if pad is None:
                if not warned:
                    print(f"vita3k-pad: waiting for {PAD_NAME}", flush=True)
                    warned = True
                time.sleep(2)
                continue
            warned = False
            print(f"vita3k-pad: reading {pad.path} ({pad.name})", flush=True)
            try:
                for event in pad.read_loop():
                    if event.type == EV_KEY:
                        if event.code == START and event.value == 1:
                            if SELECT in pad.active_keys():
                                kill_target()
                                return 0
                        if event.code in BTN_MAP:
                            key(BTN_MAP[event.code], event.value == 1)
                    elif event.type == 0x03 and event.code in STICK:
                        stick(event.code, event.value)
            except OSError:
                # pad went away (replug); keep the keyboard and wait for it
                print("vita3k-pad: pad read failed, rescanning", flush=True)
                time.sleep(1)
            finally:
                pad.close()
    except KeyboardInterrupt:
        pass
    finally:
        fcntl.ioctl(fd, UI_DEV_DESTROY)
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())