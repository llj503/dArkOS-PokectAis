#!/usr/bin/env python3
# Emit a key through uinput, the same way gptokeyb does for the pad's A button.
import ctypes, os, struct, sys, time

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EV_SYN, EV_KEY = 0x00, 0x01
SYN_REPORT = 0

KEYS = {
    "enter": 28, "esc": 1, "space": 57, "backspace": 14,
    "up": 103, "down": 108, "left": 105, "right": 106,
    "tab": 15, "home": 102, "end": 107, "pageup": 104, "pagedown": 109,
    "x": 45, "c": 46, "z": 44, "v": 47, "q": 16, "e": 18,
    "a": 30, "s": 31, "d": 32, "w": 17, "p": 25,
    "leftshift": 42, "rightshift": 54,
}

class UInputUserDev(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char * 80),
                ("id", ctypes.c_uint16 * 4),
                ("ff_effects_max", ctypes.c_uint32),
                ("absmax", ctypes.c_int32 * 64),
                ("absmin", ctypes.c_int32 * 64),
                ("absfuzz", ctypes.c_int32 * 64),
                ("absflat", ctypes.c_int32 * 64)]

def main():
    names = sys.argv[1:] or ["enter"]
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    import fcntl
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
    for n in names:
        fcntl.ioctl(fd, UI_SET_KEYBIT, KEYS[n])
    dev = UInputUserDev()
    dev.name = b"v3k-test-inject"
    dev.id = (0x03, 0x1234, 0x5678, 0x0001)
    os.write(fd, bytes(dev))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.6)  # let libinput/Weston pick the new device up

    def ev(t, c, v):
        os.write(fd, struct.pack("qqHHi", 0, 0, t, c, v))

    for n in names:
        k = KEYS[n]
        ev(EV_KEY, k, 1); ev(EV_SYN, SYN_REPORT, 0)
        time.sleep(0.08)
        ev(EV_KEY, k, 0); ev(EV_SYN, SYN_REPORT, 0)
        print("sent", n, flush=True)
        time.sleep(0.4)
    time.sleep(0.4)
    fcntl.ioctl(fd, UI_DEV_DESTROY)
    os.close(fd)

main()