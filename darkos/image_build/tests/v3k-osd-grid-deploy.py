#!/usr/bin/env python3
"""Deploy the in-game grid-card settings OSD on an installed dArkOS device.

  python3 v3k-osd-grid-deploy.py [host]       (default 192.168.0.176)

The settings panel is opened DURING A GAME by the console hotkey
(vita3k-pad.py -> console-detect -t), navigated with d-pad / stick + A/B,
and applies its choice on game exit through psvita-option.py --apply-pending.

In --setup mode (psvita-launch.sh when firmware/font are missing before a game
boots) the same panel adds "install firmware" / "install font" cards with a
controller-driven .PUP file browser, so Vita3K's modal Qt dialog never appears.

This script builds scripts/vita3k-osd-wl.c into /usr/local/bin/vita3k-osd,
syncs psvita-launch.sh, and removes the ES-time hotkey daemon from the
previous iteration (not wanted). No upstream rebuild / GitHub interaction.
"""
import hashlib
import io
import os
import sys

import paramiko

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.176"
WORK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(WORK, "scripts")
PKG = os.path.join(WORK, "packages")
REMOTE = "/home/ark/vita3k-install"

FILES = {
    "vita3k-osd-wl.c": os.path.join(SRC, "vita3k-osd-wl.c"),
    "xdg-shell.xml": os.path.join(PKG, "xdg-shell.xml"),
    "install_vita3k.sh": os.path.join(SRC, "install_vita3k.sh"),
    "psvita-launch.sh": os.path.join(SRC, "psvita-launch.sh"),
}

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="ark", password="ark", timeout=15,
          banner_timeout=15, auth_timeout=15,
          allow_agent=False, look_for_keys=False)


def run(cmd, t=180):
    _, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode(errors="replace").strip(),
            e.read().decode(errors="replace").strip())


def log(*a):
    print(*a, flush=True)


def main():
    state, _ = run("systemctl is-active psvita-session.service")
    if state == "active":
        log("ABORT: a Vita3K session is running")
        return

    sftp = c.open_sftp()
    try:
        sftp.mkdir(REMOTE)
    except IOError:
        pass
    md5s = {}
    for name, local in FILES.items():
        data = open(local, "rb").read().replace(b"\r\n", b"\n")
        sftp.putfo(io.BytesIO(data), REMOTE + "/" + name)
        md5s[name] = hashlib.md5(data).hexdigest()
        log("uploaded", name, len(data), "bytes", md5s[name])
    sftp.close()

    for name, want in md5s.items():
        out, _ = run("md5sum %s/%s" % (REMOTE, name))
        got = out.split()[0] if out else "MISSING"
        if got != want:
            log("ABORT: md5 mismatch", name, want, got)
            return
    log("md5 OK")

    build = (
        "cd %s && "
        "wayland-scanner private-code xdg-shell.xml xdg-shell-protocol.c && "
        "wayland-scanner client-header xdg-shell.xml xdg-shell-client-protocol.h && "
        "gcc -O2 -Wall -o /tmp/vita3k-osd vita3k-osd-wl.c xdg-shell-protocol.c -I. "
        "$(pkg-config --cflags --libs wayland-client freetype2) -lrt -lm && "
        "sudo -n install -m 0755 /tmp/vita3k-osd /usr/local/bin/vita3k-osd && "
        "echo OSD_BUILT" % REMOTE
    )
    out, err = run(build, t=180)
    log("=== build ===\n" + out + "\nERR " + err[:1200])

    # The ES-time hotkey daemon was a wrong turn: settings belong in-game.
    out, err = run("sudo -n install -m 0755 %s/psvita-launch.sh "
                   "/usr/local/bin/psvita-launch.sh && "
                   "bash -n /usr/local/bin/psvita-launch.sh && echo LAUNCHER_OK" % REMOTE)
    log("=== launcher ===\n", out, err[:200])
    out, err = run("sudo -n systemctl disable --now vita3k-frontend.service 2>/dev/null; "
                   "sudo -n rm -f /etc/systemd/system/vita3k-frontend.service "
                   "/usr/local/bin/vita3k-frontend-daemon.py; "
                   "sudo -n systemctl daemon-reload; "
                   "rm -f /roms/vita3k/.osd-active /roms/vita3k/.osd-pending; "
                   "cp %s/install_vita3k.sh /home/ark/vita3k-scripts/install_vita3k.sh; "
                   "echo OLD_DAEMON_REMOVED" % REMOTE, t=60)
    log("=== cleanup ===\n", out, err[:200])

    # This image can blank the DSI backlight when systemd units change.
    bl_before, _ = run("cat /sys/class/backlight/backlight/brightness")
    bl_val = int(bl_before) if bl_before.isdigit() and int(bl_before) > 0 else 179
    run("echo %d | sudo -n tee /sys/class/backlight/backlight/brightness >/dev/null" % bl_val)
    log("backlight restored to", bl_val)

    checks = {
        "binary": "test -x /usr/local/bin/vita3k-osd && echo OSD_OK; "
                  "ldd /usr/local/bin/vita3k-osd | grep 'not found' || echo LDD_OK",
        "mapper": "grep -nE 'OSD_BIN|osd_hotkey|console-detect|OSD_ACTIVE' "
                  "/usr/local/bin/vita3k-pad.py | head -12",
        "hotkey": "/usr/local/bin/console-detect -t",
        "apply chain": "grep -n 'apply-pending' /usr/local/bin/psvita-launch.sh; "
                       "grep -n 'firmware_ok\\|setup_panel\\|--setup' /usr/local/bin/psvita-launch.sh | head -8; "
                       "test -x /usr/local/bin/psvita-option.py && echo OPTION_BACKEND_OK",
        "no daemon": "echo UNIT=$(test -e /etc/systemd/system/vita3k-frontend.service && echo present || echo absent); "
                     "echo PORTS=$(ls /roms/ports/Vita3K* 2>/dev/null | wc -l)",
        "state": "echo ES=$(systemctl is-active emulationstation); "
                 "echo SESSION=$(systemctl is-active psvita-session.service); "
                 "echo BL=$(cat /sys/class/backlight/backlight/brightness)",
    }
    log("\n================ VERIFY ================")
    for name, cmd in checks.items():
        out, err = run(cmd)
        log("--- %s ---\n%s%s" % (name, out, ("\nERR " + err[:200]) if err else ""))
    c.close()
    log("\nDONE on", HOST)


if __name__ == "__main__":
    main()
