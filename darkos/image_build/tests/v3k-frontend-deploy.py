#!/usr/bin/env python3
"""Deploy the handheld Vita3K-Plus frontend on an installed dArkOS device.

  python3 v3k-frontend-deploy.py [host]        (default 192.168.0.176)

Builds scripts/vita3k-frontend-wl.c on the device (wl_shm + xdg-shell + libpng
+ FreeType + gamepad evdev), installs /usr/local/bin/vita3k-frontend and
updates psvita-launch.sh / vita3k-pad.py. No Ports/PortMaster entry is used:
the /roms/ports/Vita3K*.sh scripts are removed. The in-game settings OSD is
deployed separately by v3k-osd-grid-deploy.py.

No upstream rebuild and no GitHub interaction.
"""
import hashlib
import io
import os
import sys
import time

import paramiko

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.176"
WORK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(WORK, "scripts")
PKG = os.path.join(WORK, "packages")
REMOTE = "/home/ark/vita3k-install"

FILES = {
    "vita3k-frontend-wl.c": os.path.join(SRC, "vita3k-frontend-wl.c"),
    "psvita-launch.sh": os.path.join(SRC, "psvita-launch.sh"),
    "vita3k-pad.py": os.path.join(SRC, "vita3k-pad.py"),
    "xdg-shell.xml": os.path.join(PKG, "xdg-shell.xml"),
}

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="ark", password="ark", timeout=15,
          banner_timeout=15, auth_timeout=15,
          allow_agent=False, look_for_keys=False)


def run(cmd, t=120):
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
    log("md5 OK:", len(md5s), "files")

    build = (
        "cd %s && "
        "wayland-scanner private-code xdg-shell.xml xdg-shell-protocol.c && "
        "wayland-scanner client-header xdg-shell.xml xdg-shell-client-protocol.h && "
        "gcc -O2 -Wall -o /tmp/vita3k-frontend vita3k-frontend-wl.c "
        "xdg-shell-protocol.c -I. "
        "$(pkg-config --cflags --libs wayland-client freetype2 libpng) -lrt -lm && "
        "sudo -n install -m 0755 /tmp/vita3k-frontend /usr/local/bin/vita3k-frontend && "
        "echo FRONTEND_BUILT" % REMOTE
    )
    out, err = run(build, t=180)
    log("=== build ===\n" + out + "\nERR " + err[:1200])

    cmds = [
        "sudo -n install -m 0755 %s/psvita-launch.sh /usr/local/bin/psvita-launch.sh" % REMOTE,
        "sudo -n install -m 0755 %s/vita3k-pad.py /usr/local/bin/vita3k-pad.py" % REMOTE,
        "sudo -n install -m 0755 %s/vita3k-pad.py /usr/local/bin/vita3k-pad.py" % REMOTE,
        "mkdir -p /home/ark/vita3k-scripts",
        "cp %s/psvita-launch.sh %s/vita3k-pad.py %s/vita3k-frontend-wl.c "
        "/home/ark/vita3k-scripts/" % (REMOTE, REMOTE, REMOTE),
        "sudo -n cp /usr/local/bin/psvita-launch.sh /home/ark/vita3k-scripts/psvita-launch.sh",
        "sudo -n cp /usr/local/bin/vita3k-pad.py /home/ark/vita3k-scripts/vita3k-pad.py",
        "rm -f /roms/vita3k/.frontend-active /roms/vita3k/.osd-active",
        "sudo -n rm -f '/roms/ports/Vita3K.sh' '/roms/ports/Vita3K 高级设置.sh'",
    ]
    for cmd in cmds:
        out, err = run(cmd)
        if out or err:
            log(">", cmd.split(" && ")[0][:70], "|", (out or err)[:150])

    # The system hotkey daemon from the previous iteration is not wanted:
    # settings must be an in-game OSD, not an ES-time hotkey launcher.
    out, err = run("sudo -n systemctl disable --now vita3k-frontend.service 2>/dev/null; "
                   "sudo -n rm -f /etc/systemd/system/vita3k-frontend.service "
                   "/usr/local/bin/vita3k-frontend-daemon.py; "
                   "sudo -n systemctl daemon-reload; echo OLD_DAEMON_REMOVED", t=60)
    log("=== remove old daemon ===\n", out, err[:200])

    # Restarting ES on this image blanks the DSI backlight; restore it.
    bl_before, _ = run("cat /sys/class/backlight/backlight/brightness")
    bl_val = int(bl_before) if bl_before.isdigit() and int(bl_before) > 0 else 179
    out, err = run("sudo -n systemctl restart emulationstation", t=60)
    time.sleep(5)
    run("echo %d | sudo -n tee /sys/class/backlight/backlight/brightness >/dev/null" % bl_val)
    log("backlight restored to", bl_val)

    checks = {
        "syntax": "bash -n /usr/local/bin/psvita-launch.sh && echo BASH_OK; "
                  "python3 -c \"compile(open('/usr/local/bin/vita3k-pad.py').read(),'pad','exec');print('PY_OK')\"",
        "binary": "test -x /usr/local/bin/vita3k-frontend && echo FRONTEND_OK; "
                  "ldd /usr/local/bin/vita3k-frontend | grep 'not found' || echo LDD_OK",
        "launcher": "grep -nE 'NATIVE_GUI|vita3k-frontend|frontend-active' /usr/local/bin/psvita-launch.sh",
        "mapper": "grep -n 'FRONTEND_ACTIVE' /usr/local/bin/vita3k-pad.py",
        "old daemon": "echo UNIT=$(test -e /etc/systemd/system/vita3k-frontend.service && echo present || echo absent); "
                      "echo SCRIPT=$(test -e /usr/local/bin/vita3k-frontend-daemon.py && echo present || echo absent)",
        "ports": "ls -1 /roms/ports/Vita3K* 2>/dev/null || echo NO_PORTS_ENTRIES",
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
