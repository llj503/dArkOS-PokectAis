#!/usr/bin/env python3
"""Fix 'black screen when launching a psvita game' on a fresh dArkOS install.

Root cause on 192.168.0.176 (2026-11-13):
  1. No PS Vita firmware: fs/vs0 (main firmware) and fs/sa0 (font package) empty.
  2. First launch of a .zip makes Vita3K install 1766 files in the background
     with no rendering -> looks like a black screen; killing it mid-install
     leaves a half-written app with no eboot.bin, so every launch repeats it.
  3. Weston/ogage can leave the DSI backlight at 0 after the session, so even a
     successful exit looks like a black screen (fixed in psvita-launch.sh by
     saving/restoring brightness).

This script downloads the three official PUPs, installs them headlessly with
`--firmware`, moves a partial app aside, then performs a headless full install
of the game zip. The 1.01 patch content can hang on exFAT, so the installer is
stopped as soon as eboot.bin (with SCE\\0 magic) exists; the base game is then
bootable. Afterwards ES launches with -r TITLEID: boot, no install, no black
screen.

Usage: python3 v3k-fix-game-boot.py [host]
"""
import sys
import time

import paramiko

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.176"
ZIP = "/roms/psvita/*.zip"
BASE = "/roms/vita3k"
ENV = ("HOME=/home/ark XDG_RUNTIME_DIR=/run/vita3k QT_QPA_PLATFORM=offscreen "
       "SDL_VIDEODRIVER=offscreen ")

# (path, url, expected size, what it populates)
PUPS = [
    (BASE + "/PSP2UPDAT-374-pre.PUP", "https://bit.ly/4hlePsX",
     128798720, "pd0 pre-installed package"),
    (BASE + "/PSP2UPDAT-373-font.PUP", "https://bit.ly/2P2rb0r",
     56768512, "sa0 font package"),
    (BASE + "/PSVUPDAT-374-full.PUP",
     "http://dus01.psv.update.playstation.net/update/psv/image/"
     "2022_0209/rel_f2c7b12fe85496ec88a0391b514d6e3b/PSVUPDAT.PUP",
     133834240, "vs0 main firmware 3.74"),
]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="ark", password="ark", timeout=15,
          banner_timeout=15, auth_timeout=15,
          allow_agent=False, look_for_keys=False)


def run(cmd, t=90):
    _, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode(errors="replace").strip(),
            e.read().decode(errors="replace").strip())


def log(*a):
    print(*a, flush=True)


def fw_state():
    o, _ = run("for d in os0 pd0 sa0 vs0; do echo -n \"$d=\"; "
               "find %s/fs/$d -type f 2>/dev/null | wc -l; done" % BASE)
    return o.replace("\n", " | ")


def main():
    state, _ = run("systemctl is-active psvita-session.service")
    if state == "active":
        log("ABORT: Vita3K session is running")
        return
    run("sudo -n mkdir -p /run/vita3k; sudo -n chown ark:ark /run/vita3k")

    # ---- 1. official PUPs ------------------------------------------------
    for path, url, want, label in PUPS:
        size, _ = run("stat -c %%s %s 2>/dev/null || echo 0" % path)
        if size.isdigit() and int(size) == want:
            log("already downloaded", path, size, label)
            continue
        log("downloading", label, "->", path)
        o, e = run("curl -fLsS --retry 2 --max-time 600 -o %s '%s'; "
                   "echo RC=$?; stat -c %%s %s 2>/dev/null || echo 0" %
                   (path, url, path), t=660)
        log("  ->", o.replace("\n", " | ")[:200], e[:150])
        size, _ = run("stat -c %%s %s 2>/dev/null || echo 0" % path)
        if not size.isdigit() or int(size) != want:
            log("ABORT: bad PUP size", path, size, "expected", want)
            return

    # ---- 2. install firmware headlessly ---------------------------------
    log("firmware before:", fw_state())
    for path, _url, _want, label in PUPS:
        o, e = run("cd /home/ark && %s/opt/vita3k/vita3k.sh --firmware %s "
                   "2>&1 | tail -6" % (ENV, path), t=420)
        log("=== install %s ===\n%s\nERR %s" % (label, o[-500:], e[:200]))
        log("firmware state:", fw_state())

    # ---- 3. move the half-installed app aside ---------------------------
    o, _ = run("if [ -d %s/fs/ux0/app/PCSE00328 ]; then "
               "mv %s/fs/ux0/app/PCSE00328 %s/fs/ux0/app/PCSE00328.partial-$(date +%%Y%%m%%d) && "
               "echo MOVED; else echo NO_PARTIAL; fi" % (BASE, BASE, BASE))
    log("partial app:", o)

    # ---- 4. full headless install of the game zip -----------------------
    zip_path, _ = run("ls -1 %s 2>/dev/null | head -1" % ZIP)
    if not zip_path:
        log("ABORT: no game zip in /roms/psvita")
        return
    log("installing", zip_path)
    # </dev/null is essential: otherwise the background process keeps the SSH
    # channel open and exec_command never returns.
    o, e = run("cd /home/ark && nohup env %s /opt/vita3k/vita3k.sh -z -- '%s' "
               ">%s/game-install.out 2>&1 </dev/null & echo LAUNCHED" %
               (ENV.strip(), zip_path, BASE), t=20)
    log("launch:", o, e[:150])

    done = False
    for i in range(48):
        time.sleep(5)
        o, _ = run("echo PROC=$(pidof Vita3K || echo none); "
                   "echo FILES=$(find %s/fs/ux0/app/PCSE00328 -type f 2>/dev/null | wc -l); "
                   "echo EBOOT=$(test -f %s/fs/ux0/app/PCSE00328/eboot.bin && echo yes || echo no)" %
                   (BASE, BASE))
        if i % 6 == 0 or "EBOOT=yes" in o:
            log("t=%3ds" % ((i + 1) * 5), o.replace("\n", " | ")[:200])
        if "EBOOT=yes" in o:
            # Give the app content a moment to settle, patch content can hang.
            time.sleep(8)
            done = True
            break
        if "PROC=none" in o and i > 2:
            break
    log("APP_INSTALLED=", done)

    # The 1.01 patch extraction can wedge on exFAT; stop the installer once
    # the base app is complete, and move any partial patch aside.
    o, _ = run("sudo -n kill -TERM $(pidof Vita3K) 2>/dev/null; sleep 2; "
               "sudo -n kill -KILL $(pidof Vita3K) 2>/dev/null; "
               "if [ -d %s/fs/ux0/patch/PCSE00328 ]; then "
               "mv %s/fs/ux0/patch/PCSE00328 %s/fs/ux0/patch/PCSE00328.partial-$(date +%%Y%%m%%d) && "
               "echo PATCH_MOVED; else echo NO_PATCH_DIR; fi" % (BASE, BASE, BASE), t=40)
    log("cleanup:", o)

    o, _ = run("echo EBOOT_MAGIC=$(xxd -l 4 -p %s/fs/ux0/app/PCSE00328/eboot.bin 2>/dev/null || echo missing); "
               "echo APP_FILES=$(find %s/fs/ux0/app/PCSE00328 -type f 2>/dev/null | wc -l); "
               "echo SFO=$(test -f %s/fs/ux0/app/PCSE00328/sce_sys/param.sfo && echo yes || echo no); "
               "echo BL=$(cat /sys/class/backlight/backlight/brightness); "
               "echo ES=$(systemctl is-active emulationstation)" % (BASE, BASE, BASE))
    log("=== result ===\n" + o)
    log("firmware:", fw_state())
    c.close()


if __name__ == "__main__":
    main()
