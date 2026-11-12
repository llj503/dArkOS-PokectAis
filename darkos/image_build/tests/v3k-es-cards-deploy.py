#!/usr/bin/env python3
"""Deploy the ES "option card" frontend for Vita3K-Plus on dArkOS.

Run from the workspace on Windows; talks to the handheld over SSH.
No GitHub, no upstream rebuild, no new dependencies on the device.
"""
import base64
import hashlib
import os
import time

import paramiko

HOST = "192.168.0.23"
USER = "ark"
PASSWORD = "ark"
WORK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# (group, card stem, config key, value, marked current at deploy time)
CARDS = [
    ("选项 · 系统语言", "选项 · 系统语言 = 简体中文", "sys-lang", "11", False),
    ("选项 · 系统语言", "选项 · 系统语言 = English", "sys-lang", "1", True),
    ("选项 · 画面倍率", "选项 · 画面倍率 = 1x 流畅", "resolution-multiplier", "1", True),
    ("选项 · 画面倍率", "选项 · 画面倍率 = 2x 清晰", "resolution-multiplier", "2", False),
    ("选项 · 性能", "选项 · 性能 = 省电 2核", "guest-cores", "2", False),
    ("选项 · 性能", "选项 · 性能 = 平衡 3核", "guest-cores", "3", True),
]
GUI_CARD = "Vita3K 高级设置（鼠标模式）"

CARDS_SCRIPT = """
import pathlib, os
D = pathlib.Path('/roms/psvita')
CARDS = %r
GUI_CARD = %r
# remove stale cards only, never the game zip/vpk
for p in D.glob('*.sh'):
    p.unlink()
for group, stem, key, value, star in CARDS:
    name = stem + (' ★' if star else '') + '.sh'
    body = '#!/bin/bash\\nexec /usr/local/bin/psvita-option.py %%r %%r %%r %%r\\n' %% (group, stem, key, value)
    (D / name).write_text(body, encoding='utf-8')
    os.chmod(D / name, 0o755)
(D / (GUI_CARD + '.sh')).write_text('#!/bin/bash\\nexec /usr/local/bin/psvita-launch.sh\\n', encoding='utf-8')
os.chmod(D / (GUI_CARD + '.sh'), 0o755)
print('CARDS_WRITTEN', len(list(D.glob('*.sh'))))
""" % (CARDS, GUI_CARD)

ESCFG_SCRIPT = """
import pathlib
p = pathlib.Path('/etc/emulationstation/es_systems.cfg')
t = p.read_text(encoding='utf-8')
old = '<extension>.vpk .VPK .zip .ZIP</extension>'
new = '<extension>.vpk .VPK .zip .ZIP .sh .SH</extension>'
if new in t:
    print('ESCFG_ALREADY_PATCHED')
elif old not in t:
    print('ESCFG_PATTERN_NOT_FOUND')
    raise SystemExit(1)
else:
    pathlib.Path(str(p) + '.bak-psvita-cards-20261112').write_text(t, encoding='utf-8')
    p.write_text(t.replace(old, new, 1), encoding='utf-8')
    print('ESCFG_PATCHED')
"""


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=8,
              look_for_keys=False, allow_agent=False)

    def run(cmd, t=60):
        i, o, e = c.exec_command(cmd, timeout=t)
        return o.read().decode(errors="replace").strip(), e.read().decode(errors="replace").strip()

    def upload(local, remote, root=False):
        data = open(local, "rb").read().replace(b"\r\n", b"\n")
        b64 = base64.b64encode(data).decode()
        tmp = "/tmp/_v3k_card_upload"
        cmd = "printf '%%s' '%s' | base64 -d > %s && " % (b64, tmp)
        if root:
            cmd += "sudo -n cp %s %s && sudo -n chmod 755 %s" % (tmp, remote, remote)
        else:
            cmd += "cp %s %s && chmod 755 %s" % (tmp, remote, remote)
        out, err = run(cmd)
        return hashlib.md5(data).hexdigest(), err

    print("pre:", run("systemctl is-active psvita-session.service; systemctl is-active emulationstation")[0].replace("\n", " | "))
    run("sudo -n cp -a /etc/emulationstation/es_systems.cfg /etc/emulationstation/es_systems.cfg.bak-precards-20261112")
    run("sudo -n cp -a /usr/local/bin/psvita-launch.sh /home/ark/psvita-launch.sh.bak-precards-20261112")

    md5_launcher, err = upload(os.path.join(WORK, "scripts/psvita-launch.sh"), "/usr/local/bin/psvita-launch.sh", root=True)
    print("launcher md5", md5_launcher, "err", err[:100])
    # keep the installer script directory in sync so a later bundle install
    # does not put the old launcher back
    run("sudo -n cp /usr/local/bin/psvita-launch.sh /home/ark/vita3k-scripts/psvita-launch.sh")
    md5_option, err = upload(os.path.join(WORK, "scripts/psvita-option.py"), "/usr/local/bin/psvita-option.py", root=True)
    print("option backend md5", md5_option, "err", err[:100])
    print("syntax:", run("bash -n /usr/local/bin/psvita-launch.sh && python3 -c \"compile(open('/usr/local/bin/psvita-option.py').read(),'x','exec');print('SYNTAX_OK')\"")[0])

    for script in (ESCFG_SCRIPT, CARDS_SCRIPT):
        b64 = base64.b64encode(script.encode("utf-8")).decode()
        sudo = "sudo -n " if "es_systems" in script else ""
        out, err = run("printf '%%s' '%s' | base64 -d | %spython3 -" % (b64, sudo))
        print(out, "err", err[:150])

    print("stop stale Vita3K session:", run("sudo -n systemctl stop psvita-session.service; sleep 3; echo STOPPED", t=40)[0])
    print("restart ES:", run("sudo -n systemctl restart emulationstation; sleep 3; systemctl is-active emulationstation", t=60)[0])

    print("--- verify ---")
    print("extension:", run("grep -A4 '<name>psvita</name>' /etc/emulationstation/es_systems.cfg | grep extension")[0])
    print("cards:", run("ls -1 /roms/psvita/*.sh | sed 's|.*/||'")[0])
    print("config untouched:", run("grep -E 'sys-lang|resolution-multiplier|guest-cores' /roms/vita3k/config.yml")[0].replace("\n", " | "))
    print("state:", run("systemctl is-active emulationstation; systemctl is-active psvita-session.service")[0].replace("\n", " | "))
    c.close()


if __name__ == "__main__":
    main()
