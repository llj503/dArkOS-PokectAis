#!/usr/bin/env python3
"""Show/hide the ES-PSVITA option cards.

  python3 v3k-es-cards-toggle.py hide    [host]
  python3 v3k-es-cards-toggle.py restore [host]

`hide` moves every /roms/psvita/*.sh into a local backup directory, removes
.sh/.SH from the psvita <extension> list and drops any stale <game> entries
for those cards from gamelist.xml, then restarts EmulationStation. Nothing is
deleted, so `restore` puts everything back.

The option backends (psvita-option.py, psvita-lang.py) and the in-game OSD stay
installed: they only rename cards that exist, they never create new ones.
"""
import base64
import os
import sys
import time

import paramiko

MODE = sys.argv[1] if len(sys.argv) > 1 else "hide"
HOST = sys.argv[2] if len(sys.argv) > 2 else "192.168.0.176"
BACKUP = "/home/ark/vita3k-scripts/es-cards-backup-20261113"
CFGBAK = "/etc/emulationstation/es_systems.cfg.bak-no-cards-20261113"

EXT_WITH = "<extension>.vpk .VPK .zip .ZIP .sh .SH</extension>"
EXT_WITHOUT = "<extension>.vpk .VPK .zip .ZIP</extension>"

GAMELIST_CLEAN = """
import pathlib, xml.etree.ElementTree as ET
for p in (pathlib.Path('/roms/psvita/gamelist.xml'),
          pathlib.Path('/home/ark/.emulationstation/gamelists/psvita/gamelist.xml')):
    if not p.exists():
        continue
    try:
        root = ET.parse(p).getroot()
    except Exception as ex:
        print('GAMELIST_PARSE_FAIL', p, ex)
        continue
    removed = 0
    for g in list(root):
        path = g.findtext('path') or ''
        if path.lower().endswith('.sh'):
            root.remove(g)
            removed += 1
    if removed:
        bak = pathlib.Path(str(p) + '.bak-no-cards-20261113')
        if not bak.exists():
            bak.write_bytes(p.read_bytes())
        ET.ElementTree(root).write(p, encoding='utf-8', xml_declaration=True)
        print('GAMELIST_CLEANED', p, removed)
    else:
        print('GAMELIST_CLEAN', p, 'no card entries')
"""


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="ark", password="ark", timeout=15,
              banner_timeout=15, auth_timeout=15,
              allow_agent=False, look_for_keys=False)

    def run(cmd, t=60):
        _, o, e = c.exec_command(cmd, timeout=t)
        return (o.read().decode(errors="replace").strip(),
                e.read().decode(errors="replace").strip())

    state, _ = run("systemctl is-active psvita-session.service")
    if state == "active":
        print("ABORT: a Vita3K session is running, exit it first")
        return

    if MODE == "hide":
        o, e = run("mkdir -p %s && mv /roms/psvita/*.sh %s/ 2>/dev/null; "
                   "echo MOVED=$(ls -1 %s/*.sh 2>/dev/null | wc -l)" % (BACKUP, BACKUP, BACKUP))
        print("=== cards moved to", BACKUP, "===\n", o, e[:200])

        script = """
import pathlib
p = pathlib.Path('/etc/emulationstation/es_systems.cfg')
t = p.read_text(encoding='utf-8')
old, new = %r, %r
if new in t:
    print('EXT_ALREADY_CLEAN')
elif old in t:
    pathlib.Path(%r).write_text(t, encoding='utf-8')
    p.write_text(t.replace(old, new, 1), encoding='utf-8')
    print('EXT_PATCHED')
else:
    print('EXT_PATTERN_NOT_FOUND')
""" % (EXT_WITH, EXT_WITHOUT, CFGBAK)
        b64 = base64.b64encode(script.encode("utf-8")).decode()
        o, e = run("printf '%%s' '%s' | base64 -d | sudo -n python3 -" % b64)
        print("=== extension ===\n", o, e[:200])

        b64 = base64.b64encode(GAMELIST_CLEAN.encode("utf-8")).decode()
        o, e = run("printf '%%s' '%s' | base64 -d | python3 -" % b64)
        print("=== gamelist ===\n", o, e[:200])

    elif MODE == "restore":
        o, e = run("mv %s/*.sh /roms/psvita/ 2>/dev/null; "
                   "echo RESTORED=$(ls -1 /roms/psvita/*.sh 2>/dev/null | wc -l)" % BACKUP)
        print("=== cards restored ===\n", o, e[:200])
        script = """
import pathlib
p = pathlib.Path('/etc/emulationstation/es_systems.cfg')
t = p.read_text(encoding='utf-8')
old, new = %r, %r
if new in t:
    print('EXT_ALREADY_WITH_CARDS')
elif old in t:
    p.write_text(t.replace(old, new, 1), encoding='utf-8')
    print('EXT_RESTORED')
else:
    print('EXT_PATTERN_NOT_FOUND')
""" % (EXT_WITHOUT, EXT_WITH)
        b64 = base64.b64encode(script.encode("utf-8")).decode()
        o, e = run("printf '%%s' '%s' | base64 -d | sudo -n python3 -" % b64)
        print("=== extension ===\n", o, e[:200])
    else:
        print("usage: v3k-es-cards-toggle.py hide|restore [host]")
        return

    o, e = run("sudo -n systemctl restart emulationstation", t=60)
    print("=== ES restart ===", o, e[:150])
    time.sleep(6)
    checks = {
        "extension": "grep '<extension>' /etc/emulationstation/es_systems.cfg | grep -A0 -B0 '' | tail -3; "
                     "grep -A4 '<name>psvita</name>' /etc/emulationstation/es_systems.cfg | grep extension",
        "cards in /roms/psvita": "ls -1 /roms/psvita/ 2>/dev/null | head -15; echo SH_COUNT=$(ls -1 /roms/psvita/*.sh 2>/dev/null | wc -l)",
        "backup": "ls -1 %s/*.sh 2>/dev/null | sed 's|.*/||' | head -10" % BACKUP,
        "ES": "echo ES=$(systemctl is-active emulationstation); "
              "sudo -n fuser /dev/dri/card0 2>/dev/null | head -1; "
              "echo BL=$(cat /sys/class/backlight/backlight/brightness)",
        "session": "echo SESSION=$(systemctl is-active psvita-session.service); "
                   "echo V3K=$(pidof Vita3K || echo none); echo WESTON=$(pidof weston || echo none)",
    }
    for name, cmd in checks.items():
        o, e = run(cmd)
        print("--- %s ---\n%s%s" % (name, o, ("\nERR " + e[:150]) if e else ""))
    c.close()


if __name__ == "__main__":
    main()
