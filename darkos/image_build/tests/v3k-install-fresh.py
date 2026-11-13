#!/usr/bin/env python3
"""Install the previously compiled Vita3K-Plus port on a fresh dArkOS device.

Usage: python3 v3k-install-fresh.py [host] [--cards]   (default 192.168.0.176)

Deploys over SSH/SFTP (password auth, no GitHub interaction):
  * CI bundle  pocketAis-Vita3KPlus-armv8a-20261112g.tar.zst -> /opt/vita3k
  * WSI layer  pocketAis-vita3k-wsi-a53-20261111.tar.zst    -> /opt/vita3k-wsi
  * launcher / pad mapper / language+option backends / console-detect wrapper
  * Wayland OSD + handheld game-grid frontend compiled on-device
    (vita3k-osd-wl.c / vita3k-frontend-wl.c + xdg-shell.xml)
  * EmulationStation psvita system and psvita theme art. Option cards are NOT
    deployed by default (the psvita list must show games only); pass --cards to
    add them, or run v3k-es-cards-toggle.py restore on an installed device.
"""
import base64
import hashlib
import io
import os
import sys
import time

import paramiko
from PIL import Image, ImageDraw, ImageFont

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
HOST = ARGS[0] if ARGS else "192.168.0.176"
INSTALL_CARDS = "--cards" in sys.argv
USER, PASSWORD = "ark", "ark"
WORK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(WORK, "packages")
SRC = os.path.join(WORK, "scripts")
REMOTE = "/home/ark/vita3k-install"
THEME_DIR = "/roms/themes/es-theme-nes-box"

BUNDLE = "pocketAis-Vita3KPlus-armv8a-20261112g.tar.zst"
WSI = "pocketAis-vita3k-wsi-a53-20261111.tar.zst"
BIG = [BUNDLE, BUNDLE + ".sha256", WSI, WSI + ".sha256"]
# A complete config.yml (194 keys) avoids Vita3K's first-run default rewrite,
# which otherwise brings back the modal Welcome page and resets the key map.
TEMPLATE = "vita3k-config-template.yml"
SCRIPTS = [
    "install_vita3k.sh", "install_vita3k_wsi.sh", "psvita-launch.sh",
    "vita3k-pad.py", "patch_es_vita.py",
    "make_psvita_theme.py", "psvita-lang.py", "psvita-option.py",
    "console-detect", "vita3k-osd-wl.c", "vita3k-frontend-wl.c",
]
EXTRA = ["psvita-lang.py", "psvita-option.py", "console-detect"]

CARDS = [
    ("选项 · 系统语言", "选项 · 系统语言 = 简体中文", "sys-lang", "11", False),
    ("选项 · 系统语言", "选项 · 系统语言 = English", "sys-lang", "1", True),
    ("选项 · 画面倍率", "选项 · 画面倍率 = 1x 流畅", "resolution-multiplier", "1", True),
    ("选项 · 画面倍率", "选项 · 画面倍率 = 2x 清晰", "resolution-multiplier", "2", False),
    ("选项 · 性能", "选项 · 性能 = 省电 2核", "guest-cores", "2", False),
    ("选项 · 性能", "选项 · 性能 = 平衡 3核", "guest-cores", "3", True),
]
GUI_CARD = "Vita3K 高级设置（鼠标模式）"

CFG_AND_CARDS = """
import pathlib, os
D = pathlib.Path('/roms/psvita')
CARDS = %r
GUI_CARD = %r
p = pathlib.Path('/etc/emulationstation/es_systems.cfg')
t = p.read_text(encoding='utf-8')
old = '<extension>.vpk .VPK .zip .ZIP</extension>'
new = '<extension>.vpk .VPK .zip .ZIP .sh .SH</extension>'
if new in t:
    print('ESCFG_ALREADY_PATCHED')
elif old in t:
    pathlib.Path(str(p) + '.bak-psvita-cards-20261113').write_text(t, encoding='utf-8')
    p.write_text(t.replace(old, new, 1), encoding='utf-8')
    print('ESCFG_PATCHED')
else:
    print('ESCFG_PATTERN_NOT_FOUND')
for f in D.glob('*.sh'):
    f.unlink()
for group, stem, key, value, star in CARDS:
    name = stem + (' ★' if star else '') + '.sh'
    body = '#!/bin/bash\\nexec /usr/local/bin/psvita-option.py %%r %%r %%r %%r\\n' %% (group, stem, key, value)
    (D / name).write_text(body, encoding='utf-8')
    os.chmod(D / name, 0o755)
(D / (GUI_CARD + '.sh')).write_text('#!/bin/bash\\nexec /usr/local/bin/psvita-launch.sh\\n', encoding='utf-8')
os.chmod(D / (GUI_CARD + '.sh'), 0o755)
print('CARDS_WRITTEN', len(list(D.glob('*.sh'))))
""" % (CARDS, GUI_CARD)


def log(*a):
    print(*a, flush=True)


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=12,
              banner_timeout=12, auth_timeout=12,
              allow_agent=False, look_for_keys=False)
    log("connected", HOST)

    def run(cmd, t=60):
        _, o, e = c.exec_command(cmd, timeout=t)
        out = o.read().decode(errors="replace").strip()
        err = e.read().decode(errors="replace").strip()
        return out, err

    def py(script, sudo=True, t=60):
        b64 = base64.b64encode(script.encode("utf-8")).decode()
        pre = "sudo -n " if sudo else ""
        return run("printf '%%s' '%s' | base64 -d | %spython3 -" % (b64, pre), t)

    def md5(data):
        return hashlib.md5(data).hexdigest()

    # ---- preflight -------------------------------------------------------
    out, _ = run("systemctl is-active psvita-session.service; df -h / /roms | tail -2")
    log("preflight:", out.replace("\n", " | "))
    if "active" in out.splitlines()[:1]:
        log("ABORT: a Vita3K session is running")
        return

    sftp = c.open_sftp()
    try:
        sftp.mkdir(REMOTE)
    except IOError:
        pass

    uploaded = {}
    for name in BIG:
        data = open(os.path.join(PKG, name), "rb").read()
        sftp.putfo(io.BytesIO(data), REMOTE + "/" + name)
        uploaded[REMOTE + "/" + name] = md5(data)
        log("uploaded", name, len(data), "bytes", md5(data))
    data = open(os.path.join(PKG, "xdg-shell.xml"), "rb").read()
    sftp.putfo(io.BytesIO(data), REMOTE + "/xdg-shell.xml")
    uploaded[REMOTE + "/xdg-shell.xml"] = md5(data)
    data = open(os.path.join(PKG, TEMPLATE), "rb").read().replace(b"\r\n", b"\n")
    sftp.putfo(io.BytesIO(data), REMOTE + "/" + TEMPLATE)
    uploaded[REMOTE + "/" + TEMPLATE] = md5(data)
    log("uploaded", TEMPLATE, len(data), "bytes", md5(data))
    for name in SCRIPTS:
        data = open(os.path.join(SRC, name), "rb").read().replace(b"\r\n", b"\n")
        sftp.putfo(io.BytesIO(data), REMOTE + "/" + name)
        uploaded[REMOTE + "/" + name] = md5(data)
        log("uploaded", name, len(data), "bytes", md5(data))

    # ---- generated theme art (Pillow on the PC; device has none) --------
    font = "C:/Windows/Fonts/ARIALBI.TTF"
    outdir = os.path.join(PKG, "psvita-theme")
    os.makedirs(outdir, exist_ok=True)

    def wordmark(text, size, canvas, colour):
        f = ImageFont.truetype(font, size)
        im = Image.new("RGBA", canvas, (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        box = d.textbbox((0, 0), text, font=f)
        w, h = box[2] - box[0], box[3] - box[1]
        d.text(((canvas[0] - w) / 2 - box[0], (canvas[1] - h) / 2 - box[1]),
               text, font=f, fill=colour)
        return im

    wordmark("PS VITA", 110, (480, 157), (255, 255, 255, 255)).save(
        os.path.join(outdir, "system.png"))
    wordmark("PS VITA", 200, (960, 540), (255, 255, 255, 60)).save(
        os.path.join(outdir, "background_icon.png"))
    theme_xml = open(os.path.join(SRC, "make_psvita_theme.py"), encoding="utf-8").read()
    theme_xml = theme_xml.split('fh.write("""', 1)[1].split('""")', 1)[0]
    open(os.path.join(outdir, "theme.xml"), "w", encoding="utf-8").write(theme_xml)
    try:
        sftp.mkdir(THEME_DIR + "/psvita")
    except IOError:
        pass
    for name in ("system.png", "background_icon.png", "theme.xml"):
        data = open(os.path.join(outdir, name), "rb").read()
        sftp.putfo(io.BytesIO(data), THEME_DIR + "/psvita/" + name)
        uploaded[THEME_DIR + "/psvita/" + name] = md5(data)
    log("uploaded theme art ->", THEME_DIR + "/psvita")

    # ---- checksums of the uploaded files --------------------------------
    for path, want in uploaded.items():
        out, _ = run("md5sum " + path)
        got = out.split()[0] if out else "MISSING"
        if got != want:
            log("MD5 MISMATCH", path, want, got)
            return
    log("MD5 OK:", len(uploaded), "files")

    # ---- core installers (run as root, offline) -------------------------
    out, err = run("sudo -n bash %s/install_vita3k.sh %s/%s %s" %
                   (REMOTE, REMOTE, BUNDLE, REMOTE), t=300)
    log("=== install_vita3k.sh ===\n" + out + "\nERR: " + err[:600])
    out, err = run("sudo -n bash %s/install_vita3k_wsi.sh %s/%s" %
                   (REMOTE, REMOTE, WSI), t=180)
    log("=== install_vita3k_wsi.sh ===\n" + out + "\nERR: " + err[:600])

    # ---- extra backends + persistent script copies ----------------------
    cmds = []
    for f in EXTRA:
        cmds.append("sudo -n install -m 0755 %s/%s /usr/local/bin/%s" % (REMOTE, f, f))
    cmds += [
        "mkdir -p /home/ark/vita3k-scripts",
        "cp %s/*.sh %s/*.py %s/console-detect %s/*.c /home/ark/vita3k-scripts/ 2>/dev/null || true" %
        (REMOTE, REMOTE, REMOTE, REMOTE),
        "sudo -n cp /usr/local/bin/psvita-launch.sh /home/ark/vita3k-scripts/psvita-launch.sh",
        "sudo -n cp /usr/local/bin/vita3k-pad.py /home/ark/vita3k-scripts/vita3k-pad.py",
        # Full config template: no Welcome dialog, Chinese UI, pad key map.
        "[ -f /roms/vita3k/config.yml ] || cp %s/%s /roms/vita3k/config.yml" %
        (REMOTE, TEMPLATE),
        "touch /roms/vita3k/.darkos-controls",
        "sudo -n chown -R ark:ark /opt/vita3k /opt/vita3k-wsi",
        "printf 'zh\\n' > /roms/vita3k/.ui-lang",
        "printf 'happy5\\n' > /roms/vita3k/.hotkey-type",
        "rm -f /roms/vita3k/.lang-manual /roms/vita3k/.osd-active /roms/vita3k/.osd-pending",
        "python3 /usr/local/bin/psvita-lang.py --sync",
    ]
    for cmd in cmds:
        out, err = run(cmd, t=60)
        if out or err:
            log(">", cmd.split(" && ")[0][:70], "|", (out or err)[:150])

    # ---- ES option cards (opt-in only) ----------------------------------
    if INSTALL_CARDS:
        out, err = py(CFG_AND_CARDS, sudo=True, t=60)
        log("=== ES cards ===\n" + out + ("\nERR: " + err[:400] if err else ""))
    else:
        log("=== ES cards === skipped (--cards to enable); psvita shows games only")

    # ---- OSD: install freetype headers, build the Wayland client --------
    # Fresh dArkOS images ship neither Weston (runtime compositor) nor the
    # FreeType headers (needed to build the Chinese OSD client on-device).
    out, err = run("sudo -n apt-get update -qq && sudo -n DEBIAN_FRONTEND=noninteractive "
                   "apt-get install -y -qq weston libfreetype-dev", t=420)
    log("apt weston + libfreetype-dev:", (out or err)[-350:])
    out, err = run("weston --version 2>&1 | head -1; pkg-config --exists freetype2 && echo FREETYPE_DEV_OK")
    log("toolchain:", out or err)
    build = (
        "cd %s && wayland-scanner private-code xdg-shell.xml xdg-shell-protocol.c && "
        "wayland-scanner client-header xdg-shell.xml xdg-shell-client-protocol.h && "
        "gcc -O2 -o /tmp/vita3k-osd vita3k-osd-wl.c xdg-shell-protocol.c -I. "
        "$(pkg-config --cflags --libs wayland-client freetype2) -lrt -lm && "
        "sudo -n install -m 0755 /tmp/vita3k-osd /usr/local/bin/vita3k-osd && "
        "echo OSD_BUILT" % REMOTE
    )
    out, err = run(build, t=180)
    log("=== OSD build ===\n" + out + "\nERR: " + err[:900])

    # ---- handheld frontend (replaces the desktop Qt app list) ------------
    frontend_build = (
        "cd %s && gcc -O2 -Wall -o /tmp/vita3k-frontend vita3k-frontend-wl.c "
        "xdg-shell-protocol.c -I. "
        "$(pkg-config --cflags --libs wayland-client freetype2 libpng) -lrt -lm && "
        "sudo -n install -m 0755 /tmp/vita3k-frontend /usr/local/bin/vita3k-frontend && "
        "echo FRONTEND_BUILT" % REMOTE
    )
    out, err = run(frontend_build, t=180)
    log("=== frontend build ===\n" + out + "\nERR: " + err[:900])
    # No Ports/PortMaster entry: the settings panel is an in-game OSD opened
    # by the console hotkey, and the installer removes any stale Ports scripts.
    out, err = run("ls -1 /roms/ports/Vita3K* 2>/dev/null || echo NO_PORTS_ENTRIES")
    log("=== no Ports entries ===\n" + out)

    # ---- verification ----------------------------------------------------
    # ES must reload es_systems.cfg after the psvita system was added.
    # Restarting ES blanks the DSI backlight on this image; put it back.
    bl_before, _ = run("cat /sys/class/backlight/backlight/brightness")
    bl_val = int(bl_before) if bl_before.isdigit() and int(bl_before) > 0 else 179
    out, err = run("sudo -n systemctl restart emulationstation", t=60)
    time.sleep(5)
    run("echo %d | sudo -n tee /sys/class/backlight/backlight/brightness >/dev/null" % bl_val)
    verify = {
        "bundle": "ls -l /opt/vita3k/Vita3K /opt/vita3k/vita3k.sh; ls -l /opt/vita3k/portable",
        "wsi": "ls -l /opt/vita3k-wsi/; ldd /opt/vita3k-wsi/libVkLayer_window_system_integration.so | grep 'not found' || echo LDD_OK",
        "launcher": "bash -n /usr/local/bin/psvita-launch.sh && echo BASH_OK; "
                    "for f in vita3k-pad.py psvita-lang.py psvita-option.py; do "
                    "python3 -c \"compile(open('/usr/local/bin/'+'$f').read(),'$f','exec')\" || echo PY_FAIL_$f; done; echo PY_OK",
        "osd": "test -x /usr/local/bin/vita3k-osd && echo OSD_OK; ldd /usr/local/bin/vita3k-osd | grep 'not found' || echo OSD_LDD_OK",
        "frontend": "test -x /usr/local/bin/vita3k-frontend && echo FRONTEND_OK; "
                    "ldd /usr/local/bin/vita3k-frontend | grep 'not found' || echo FRONTEND_LDD_OK; "
                    "ls -1 /roms/ports/Vita3K* 2>/dev/null || echo NO_PORTS_ENTRIES",
        "hotkey": "/usr/local/bin/console-detect -t; cat /roms/vita3k/.hotkey-type /roms/vita3k/.ui-lang",
        "es": "grep -A5 '<name>psvita</name>' /etc/emulationstation/es_systems.cfg | head -6; "
              "systemctl is-active emulationstation",
        "cards": "ls -1 /roms/psvita/*.sh 2>/dev/null | sed 's|.*/||'",
        "config": "grep -E 'sys-lang|show-welcome|boot-apps-full-screen' /roms/vita3k/config.yml 2>/dev/null || echo NO_CFG_YET",
        "theme": "ls -l %s/psvita/" % THEME_DIR,
        "session": "systemctl is-active psvita-session.service; systemctl is-active emulationstation",
    }
    log("\n================ VERIFY ================")
    for name, cmd in verify.items():
        out, err = run(cmd, t=60)
        log("--- %s ---\n%s%s" % (name, out, ("\nERR " + err[:250]) if err else ""))

    sftp.close()
    c.close()
    log("\nDONE: Vita3K-Plus installed on", HOST)


if __name__ == "__main__":
    main()
