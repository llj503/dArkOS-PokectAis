#!/usr/bin/env python3
"""Post-install live verification for Vita3K-Plus on dArkOS.

Starts the GUI once, screenshots it through Weston's debug protocol, then
always stops the transient session so EmulationStation comes back.
Usage: python3 v3k-install-verify.py [host] [shot-name]
"""
import os
import sys
import time

import paramiko

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.176"
SHOT = sys.argv[2] if len(sys.argv) > 2 else "fresh-0176-2nd.png"
WORK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_SHOT = os.path.join(WORK, "shots", SHOT)

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="ark", password="ark", timeout=12,
          banner_timeout=12, auth_timeout=12,
          allow_agent=False, look_for_keys=False)


def run(cmd, t=60):
    _, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode(errors="replace").strip(),
            e.read().decode(errors="replace").strip())


o, e = run("python3 /usr/local/bin/psvita-lang.py --sync 2>&1; "
           "grep -E '^sys-lang:' /roms/vita3k/config.yml; "
           "cat /roms/vita3k/.ui-lang")
print("=== language sync ===\n" + o, e[:200])

try:
    o, e = run("PSVITA_WESTON_DEBUG=1 nohup /usr/local/bin/psvita-launch.sh "
               ">/home/ark/v3k-launch-test2.out 2>&1 & echo LAUNCH2", t=15)
    print("=== launch ===", o)
    for t in (10, 20, 30):
        time.sleep(10)
        o, _ = run("echo SESSION=$(systemctl is-active psvita-session.service); "
                   "echo V3K=$(pidof Vita3K || echo none); "
                   "echo WESTON=$(pidof weston || echo none)")
        print("t~%ds" % t, o.replace("\n", " | "))
    o, _ = run("grep -E '^(sys-lang|show-welcome|boot-apps-full-screen):' "
               "/roms/vita3k/config.yml")
    print("=== config during run ===\n" + o)

    o, e = run("cd /home/ark && rm -f wayland-screenshot-*.png; "
               "env XDG_RUNTIME_DIR=/run/vita3k WAYLAND_DISPLAY=wayland-vita3k "
               "weston-screenshooter 2>&1 | tail -2; "
               "ls -1 wayland-screenshot-*.png 2>/dev/null | head -1", t=40)
    print("=== screenshot ===", o, e[:150])
    try:
        s = c.open_sftp()
        fs = [f for f in s.listdir("/home/ark")
              if f.startswith("wayland-screenshot-") and f.endswith(".png")]
        if fs:
            s.get("/home/ark/" + fs[0], LOCAL_SHOT)
            print("SHOT_SAVED", LOCAL_SHOT)
        s.close()
    except Exception as ex:
        print("SHOT_FAIL", repr(ex))
finally:
    o, e = run("sudo -n systemctl stop psvita-session.service 2>&1; echo STOPPED", t=90)
    print("=== stop ===", o, e[:150])
    time.sleep(7)
    o, _ = run("echo ES=$(systemctl is-active emulationstation); "
               "echo SESSION=$(systemctl is-active psvita-session.service); "
               "echo V3K=$(pidof Vita3K || echo none); "
               "echo WESTON=$(pidof weston || echo none)")
    print("=== final state ===\n" + o)
    o, _ = run("grep -E '^(sys-lang|show-welcome|boot-apps-full-screen|resolution-multiplier|guest-cores|keyboard-button-cross):' "
               "/roms/vita3k/config.yml")
    print("=== config after exit ===\n" + o)
c.close()
