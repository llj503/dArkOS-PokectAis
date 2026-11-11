#!/usr/bin/env python3
"""Create the uinput pad clone FIRST, then start gptokeyb (so SDL sees the pad at
init), press buttons, and watch both the uinput keyboard gptokeyb creates and the
kill command it runs (via PATH shims). argv[1:] = extra gptokeyb arg variant."""
import ctypes, fcntl, os, select, struct, subprocess, sys, time
import evdev

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
BTN = {"a": 304, "b": 305, "x": 307, "y": 308, "l1": 310, "r1": 311,
       "select": 314, "start": 315}
ABS = {0: 32767, 1: 32767, 3: 32767, 4: 32767, 16: 1, 17: 1}
LOG = "/home/ark/gptk-repro3.log"
CALLS = "/home/ark/gptk-shim-calls.log"


class UInputUserDev(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char * 80),
                ("id", ctypes.c_uint16 * 4),
                ("ff_effects_max", ctypes.c_uint32),
                ("absmax", ctypes.c_int32 * 64),
                ("absmin", ctypes.c_int32 * 64),
                ("absfuzz", ctypes.c_int32 * 64),
                ("absflat", ctypes.c_int32 * 64)]


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def make_clone(info):
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
    return fd


def fds(pid):
    out = []
    for n in sorted(os.listdir(f"/proc/{pid}/fd"), key=int):
        try:
            out.append(os.readlink(f"/proc/{pid}/fd/{n}"))
        except OSError:
            pass
    return [x for x in out if "input" in x or "uinput" in x]


def main():
    open(LOG, "w").close()
    open(CALLS, "w").close()
    real = next(evdev.InputDevice(p) for p in evdev.list_devices()
                if evdev.InputDevice(p).name == "rk3562-joystick")
    info = real.info
    variant = sys.argv[1] if len(sys.argv) > 1 else "current"
    fd = None
    if variant != "late":
        fd = make_clone(info)
        log("clone created before gptokeyb")

    subprocess.run(["sudo", "cp", "/bin/sleep", "/tmp/Vita3K"], check=True)
    dummy = subprocess.Popen(["/tmp/Vita3K", "600"])
    log("dummy pid", dummy.pid)

    base = ["/opt/inttools/gptokeyb"]
    cfg = ["-c", "/usr/local/share/vita3k.gptk"]
    if variant == "current":
        args = base + ["-1", "Vita3K", "-sudokill"] + cfg
    elif variant == "poslast":
        args = base + ["-sudokill"] + cfg + ["Vita3K"]
    elif variant == "no1":
        args = base + ["Vita3K", "-sudokill"] + cfg
    else:
        args = base + variant.split()
    env = dict(os.environ)
    env["PATH"] = "/home/ark/gptk-shim:" + env["PATH"]
    env["SDL_GAMECONTROLLERCONFIG_FILE"] = "/opt/inttools/gamecontrollerdb.txt"
    log("gptokeyb args:", args)
    gp = subprocess.Popen(["stdbuf", "-oL", "-eL"] + args, env=env,
                          stdout=open(LOG, "a"), stderr=subprocess.STDOUT)
    time.sleep(2)
    log("gptokeyb pid", gp.pid, "alive", gp.poll() is None)
    log("gptokeyb input fds:", fds(gp.pid))
    if variant == "late":
        fd = make_clone(info)
        log("clone created after gptokeyb")
        time.sleep(1)
        log("gptokeyb input fds now:", fds(gp.pid))
    log("nodes:", [(p, evdev.InputDevice(p).name) for p in evdev.list_devices()])

    sinks = []
    for p in evdev.list_devices():
        d = evdev.InputDevice(p)
        caps = d.capabilities()
        if EV_KEY in caps and 28 in caps[EV_KEY] and not d.phys:
            sinks.append((p, d.name, os.open(p, os.O_RDONLY | os.O_NONBLOCK)))
    log("keyboard sinks:", [(p, n) for p, n, _ in sinks])

    def ev(t, c, v):
        os.write(fd, struct.pack("qqHHi", 0, 0, t, c, v))

    def drain(tag):
        time.sleep(0.3)
        for p in evdev.list_devices():
            if any(p == sp for sp, _, _ in sinks):
                continue
            d = evdev.InputDevice(p)
            caps = d.capabilities()
            if EV_KEY in caps and 28 in caps[EV_KEY] and not d.phys:
                sinks.append((p, d.name, os.open(p, os.O_RDONLY | os.O_NONBLOCK)))
                log("new keyboard sink:", p, d.name)
        for p, n, sfd in sinks:
            r, _, _ = select.select([sfd], [], [], 0.2)
            if not r:
                continue
            data = os.read(sfd, 4096)
            for off in range(0, len(data) - 23, 24):
                _, _, t, c, v = struct.unpack_from("qqHHi", data, off)
                if t == EV_KEY:
                    log(f"  [{tag}] {n}: key code={c} value={v}")

    def press(name):
        ev(EV_KEY, BTN[name], 1); ev(EV_SYN, SYN_REPORT, 0)
        time.sleep(0.08)
        ev(EV_KEY, BTN[name], 0); ev(EV_SYN, SYN_REPORT, 0)
        log("pressed", name)
        drain(name)

    press("a")
    press("r1")
    log("gptokeyb input fds after presses:", fds(gp.pid))
    log("pressing select+start")
    ev(EV_KEY, BTN["select"], 1); ev(EV_SYN, SYN_REPORT, 0)
    time.sleep(0.1)
    ev(EV_KEY, BTN["start"], 1); ev(EV_SYN, SYN_REPORT, 0)
    time.sleep(0.5)
    ev(EV_KEY, BTN["start"], 0); ev(EV_KEY, BTN["select"], 0); ev(EV_SYN, SYN_REPORT, 0)
    drain("combo")
    time.sleep(0.5)
    log("gptokeyb alive", gp.poll() is None, "dummy alive", dummy.poll() is None)
    log("shim calls:", open(CALLS).read().strip() or "(none)")
    gp.kill()
    dummy.kill()
    subprocess.run(["sudo", "rm", "-f", "/tmp/Vita3K"])
    fcntl.ioctl(fd, UI_DEV_DESTROY)
    os.close(fd)
    for _, _, sfd in sinks:
        os.close(sfd)
    log("REPRO3_DONE")


main()