#!/usr/bin/env python3
"""Pad -> uinput keyboard (game) / uinput mouse (Qt GUI) mapper for dArkOS.

gptokeyb never creates its uinput keyboard on this device: it holds the pad's
evdev node but no /dev/uinput fd, so no key ever reaches Weston/Qt, and its
Select+Start handler runs `kill -9` with an empty pid and exits -- taking the
whole session's input with it. This mapper uses plain evdev + uinput, no SDL
and no GUID matching. It deliberately does NOT EVIOCGRAB the pad, so Vita3K's
own SDL pad and ogage's hotkeys keep working.

Two modes, selected automatically from Vita3K's cmdline AND kept in sync with
the actual game state:

  game  ES launched a title (cmdline contains `-r TITLEID`):
        original keyboard mapping. Buttons land on the same Vita button as
        SDL's own mapping (psvita-launch.sh primes config.yml to match:
        cross=Enter, circle=Escape, square=Space, triangle=Backspace,
        start=Insert, select=Delete, L1/R1/L2/R2=PageUp/PageDown/Home/End).

  gui   Ports -> Vita3K GUI (no `-r`):
        Qt's AppsListTable sets Qt::NoFocus and the settings list does too, so
        arrow keys alone cannot select a row. A real pointer is the only way
        to drive that GUI. Left stick / d-pad move a uinput relative mouse,
        A = left click (double click boots a game), B = right click (context
        menu). Other keys still go out as keyboard keys.

With the upstream handheld patch the Qt app list takes keyboard focus, so the
default GUI mode is plain keyboard navigation: d-pad/stick -> arrows, A -> Enter
(boots the selected title), B -> Escape. Select+R3 toggles an optional pointer
mode for dialogs that still need a mouse. A bare R3 is ignored: a stick click
is far too easy to hit by accident.

The cmdline check alone is not enough: using the in-game menu's "Exit to app
list" leaves the same `-r TITLEID` process running, so the mapper would stay in
game mode while the user is looking at the Qt GUI. Every few seconds it also
reads Vita3K's own journal markers (`Title:` / `Main executable` = game boot,
`Game closed` = back to the GUI) and flips modes automatically. The query is
bounded to this mapper's own start time so markers from older sessions cannot
leak in.

Select+Start always SIGKILLs Vita3K (it swallows SIGTERM) and exits; the
launcher's EXIT trap then brings ES back.

Usage: vita3k-pad.py [process-name]   (default Vita3K)
"""
import ctypes
import fcntl
import os
import select
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
DPAD_CODES = (544, 545, 546, 547)

# left stick -> arrows (digital, with a dead zone) in game mode
STICK = {0: (105, 106), 1: (103, 108)}  # abs x -> left/right, abs y -> up/down
STICK_DEAD = 12000

# GUI pointer mode
MODE_TOGGLE = 318       # R3; with Select held toggles the optional pointer mode
POINTER_DEAD = 8000     # stick dead zone for pointer motion
POINTER_MAX = 16        # px per tick at full deflection
DPAD_STEP = 9           # px per tick while a d-pad direction is held
TICK = 0.02             # 50 Hz pointer updates
STATE_CHECK_INTERVAL = 5.0  # seconds between game-state journal polls
MAPPER_STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
OSD_ACTIVE = "/roms/vita3k/.osd-active"
OSD_BIN = "/usr/local/bin/vita3k-osd"


def hotkey_code():
    """Single source of truth: hotkey type comes from `console-detect -t`.

    happy5 boards use the Menu/Home key (evdev 316); `select` boards use
    Select (314). Everything else falls back to happy5.
    """
    try:
        kind = subprocess.run(["console-detect", "-t"], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        kind = ""
    return 314 if kind == "select" else 316

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EV_SYN, EV_KEY, EV_ABS, EV_REL = 0x00, 0x01, 0x03, 0x02
SYN_REPORT = 0
REL_X, REL_Y = 0, 1
BTN_LEFT, BTN_RIGHT = 0x110, 0x111


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


def detect_mode():
    """ES passes `-r TITLEID`; the Ports GUI has no `-r`.

    Vita3K starts a few seconds after this mapper, so wait briefly for it.
    Default to game mode if it never shows up (never turn a game's pad into a
    mouse).
    """
    deadline = time.time() + 8
    while time.time() < deadline:
        pids = subprocess.run(["pidof", TARGET], capture_output=True, text=True).stdout.split()
        for pid in pids:
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                continue
            return "game" if "-r" in cmd.split() else "gui"
        time.sleep(0.25)
    return "game"


def game_running_from_journal():
    """True = game running, False = game closed (Qt GUI), None = unknown.

    Vita3K logs `[load_app_impl]: Title:` / `Main executable ... loaded` when a
    game boots and `[on_game_closed]: Game closed` when the user returns to the
    app list. Bound the query to this mapper's start so an older session's
    markers are ignored. journald's --grep keeps the output to a few lines.
    """
    try:
        out = subprocess.run(
            ["journalctl", "-u", "psvita-session.service",
             "--since", MAPPER_STARTED_AT, "--no-pager", "-o", "cat",
             "-g", "Main executable|Game closed|Title:"],
            capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    boot = max(out.rfind("Main executable"), out.rfind("Title: "))
    close = out.rfind("Game closed")
    if boot < 0 and close < 0:
        return None
    return boot > close


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

    # A second uinput node: a plain relative mouse. Always created (libinput
    # just sees an idle pointer), only used while in gui mode.
    mfd = None
    try:
        mfd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(mfd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(mfd, UI_SET_EVBIT, EV_REL)
        fcntl.ioctl(mfd, UI_SET_EVBIT, EV_SYN)
        fcntl.ioctl(mfd, UI_SET_KEYBIT, BTN_LEFT)
        fcntl.ioctl(mfd, UI_SET_KEYBIT, BTN_RIGHT)
        fcntl.ioctl(mfd, UI_SET_RELBIT, REL_X)
        fcntl.ioctl(mfd, UI_SET_RELBIT, REL_Y)
        mdev = UInputUserDev()
        mdev.name = b"vita3k-mouse"
        mdev.id = (0x03, 0x1234, 0x5680, 0x0001)
        os.write(mfd, bytes(mdev))
        fcntl.ioctl(mfd, UI_DEV_CREATE)
    except OSError as ex:
        print(f"vita3k-pad: mouse device unavailable ({ex}), GUI pointer disabled", flush=True)
        if mfd is not None:
            os.close(mfd)
        mfd = None
    time.sleep(0.4)  # let libinput/Weston pick both devices up

    def ev(f, t, c, v):
        os.write(f, struct.pack("qqHHi", 0, 0, t, c, v))

    down_keys = set()
    stick_state = {}
    axis_value = {0: 0, 1: 0}
    held_dpad = set()

    def key(code, down):
        ev(fd, EV_KEY, code, 1 if down else 0)
        ev(fd, EV_SYN, SYN_REPORT, 0)
        if down:
            down_keys.add(code)
        else:
            down_keys.discard(code)

    def mouse_btn(code, down):
        if mfd is None:
            return
        ev(mfd, EV_KEY, code, 1 if down else 0)
        ev(mfd, EV_SYN, SYN_REPORT, 0)

    def mouse_move(dx, dy):
        if mfd is None or (dx == 0 and dy == 0):
            return
        if dx:
            ev(mfd, EV_REL, REL_X, dx)
        if dy:
            ev(mfd, EV_REL, REL_Y, dy)
        ev(mfd, EV_SYN, SYN_REPORT, 0)

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

    def axis_delta(v):
        if abs(v) <= POINTER_DEAD:
            return 0
        sign = 1 if v > 0 else -1
        mag = (abs(v) - POINTER_DEAD) / (32767 - POINTER_DEAD)
        return sign * max(1, int(round(mag * POINTER_MAX)))

    def release_all():
        for k in list(down_keys):
            key(k, False)
        down_keys.clear()
        stick_state.clear()
        held_dpad.clear()
        mouse_btn(BTN_LEFT, False)
        mouse_btn(BTN_RIGHT, False)

    def kill_target():
        pids = subprocess.run(["pidof", TARGET], capture_output=True, text=True).stdout.split()
        print(f"vita3k-pad: Select+Start, killing {TARGET} {pids}", flush=True)
        for pid in pids:
            subprocess.run(["sudo", "kill", "-9", pid])
        return True

    mode = detect_mode()
    osd_hotkey = hotkey_code()
    session_is_gui = (mode == "gui")  # Ports GUI (no -r); no game was ever booted
    pointer_enabled = False           # GUI uses arrow keys + A/B by default
    last_state_check = 0.0
    print(f"vita3k-pad: mode={mode} hotkey={osd_hotkey} (console-detect -t), "
          f"keyboard nav; Select+R3 = pointer; journal auto-sync", flush=True)

    def pointer_tick():
        if mode != "gui" or not pointer_enabled:
            return
        dx = axis_delta(axis_value.get(0, 0))
        dy = axis_delta(axis_value.get(1, 0))
        if 547 in held_dpad:
            dx += DPAD_STEP
        if 546 in held_dpad:
            dx -= DPAD_STEP
        if 545 in held_dpad:
            dy += DPAD_STEP
        if 544 in held_dpad:
            dy -= DPAD_STEP
        mouse_move(dx, dy)

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
                os.set_blocking(pad.fd, False)
                while True:
                    ready, _, _ = select.select([pad.fd], [], [], TICK)
                    if ready:
                        while True:
                            try:
                                event = pad.read_one()
                            except BlockingIOError:
                                break
                            if event is None:
                                break
                            if event.type == EV_KEY:
                                code, val = event.code, event.value
                                if code == START and val == 1 and SELECT in pad.active_keys():
                                    kill_target()
                                    return 0
                                # Home/Menu (or Select on `select` boards) opens
                                # the SDL2 OSD. Vita3K's own PS menu is disabled
                                # by patch_vita3k.py, so there is no conflict.
                                if code == osd_hotkey and val == 1:
                                    if not os.path.exists(OSD_ACTIVE):
                                        # The launcher exports LD_PRELOAD (real
                                        # libwayland-client) for Qt/libMali and a
                                        # few SDL/Vulkan vars. A standalone
                                        # Wayland client must not inherit them.
                                        env = dict(os.environ)
                                        for k in ("LD_PRELOAD", "LD_LIBRARY_PATH",
                                                  "SDL_VIDEODRIVER", "VK_ADD_IMPLICIT_LAYER_PATH",
                                                  "QT_QPA_PLATFORM", "QT_PLUGIN_PATH"):
                                            env.pop(k, None)
                                        # The launcher only passes these to
                                        # Vita3K's runuser env, not to us.
                                        env["XDG_RUNTIME_DIR"] = "/run/vita3k"
                                        env["WAYLAND_DISPLAY"] = "wayland-vita3k"
                                        with open("/roms/vita3k/vita3k-osd.log", "a") as logf:
                                            subprocess.Popen([OSD_BIN], env=env,
                                                             stdout=logf, stderr=logf)
                                        print("vita3k-pad: opened OSD", flush=True)
                                    continue
                                # While the OSD owns the screen, do not forward
                                # pad keys to the game (it reads evdev itself).
                                if os.path.exists(OSD_ACTIVE):
                                    continue
                                # Select+R3: optional pointer mode for Qt
                                # dialogs that still need a mouse. A bare R3
                                # is ignored (easy to hit by accident).
                                if (code == MODE_TOGGLE and val == 1
                                        and SELECT in pad.active_keys()):
                                    pointer_enabled = not pointer_enabled
                                    release_all()
                                    print("vita3k-pad: pointer mode -> "
                                          f"{'on' if pointer_enabled else 'off'} (Select+R3)", flush=True)
                                    continue
                                if mode == "gui" and pointer_enabled:
                                    if code == 304:
                                        mouse_btn(BTN_LEFT, val == 1)
                                        continue
                                    if code == 305:
                                        mouse_btn(BTN_RIGHT, val == 1)
                                        continue
                                    if code in DPAD_CODES:
                                        if val == 1:
                                            held_dpad.add(code)
                                        else:
                                            held_dpad.discard(code)
                                        continue
                                if code in BTN_MAP:
                                    key(BTN_MAP[code], val == 1)
                            elif event.type == EV_ABS and event.code in STICK:
                                axis_value[event.code] = event.value
                                if not os.path.exists(OSD_ACTIVE) and (mode == "game" or not pointer_enabled):
                                    stick(event.code, event.value)
                    # "Exit to app list" keeps the same -r process alive, so
                    # resync from Vita3K's own journal instead of the cmdline.
                    now = time.time()
                    if now - last_state_check >= STATE_CHECK_INTERVAL:
                        running = game_running_from_journal()
                        if running is True and mode == "gui":
                            mode = "game"
                            release_all()
                            print("vita3k-pad: mode -> game (game booted)", flush=True)
                        elif running is False and mode == "game":
                            mode = "gui"
                            release_all()
                            print("vita3k-pad: mode -> gui (game closed)", flush=True)
                        elif running is None and session_is_gui and mode == "game":
                            # An accidental R3 press in the Ports GUI must not
                            # strand the pointer; no game ever booted here.
                            mode = "gui"
                            release_all()
                            print("vita3k-pad: mode -> gui (no game running, restored)", flush=True)
                        last_state_check = now
                    pointer_tick()
            except OSError:
                # pad went away (replug); keep both uinput nodes and rescan
                print("vita3k-pad: pad read failed, rescanning", flush=True)
                release_all()
                axis_value = {0: 0, 1: 0}
                time.sleep(1)
            finally:
                pad.close()
    except KeyboardInterrupt:
        pass
    finally:
        release_all()
        fcntl.ioctl(fd, UI_DEV_DESTROY)
        os.close(fd)
        if mfd is not None:
            fcntl.ioctl(mfd, UI_DEV_DESTROY)
            os.close(mfd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
