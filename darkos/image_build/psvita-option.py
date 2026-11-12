#!/usr/bin/env python3
"""Backend for the ES psvita option cards.

Usage: psvita-option.py <group> <card-stem> <config-key> <value>

- rewrites one flat key in /roms/vita3k/config.yml
- marks the chosen card with a star so ES shows which option is active
- restarts ES (no-block) so the renamed card is visible

Never runs while a Vita3K session is active: Vita3K rewrites config.yml on exit.
"""
import os
import pathlib
import re
import subprocess
import sys
import time

CFG = "/roms/vita3k/config.yml"
CARD_DIR = pathlib.Path("/roms/psvita")
LOG = "/roms/vita3k/es-option.log"
PENDING = pathlib.Path("/roms/vita3k/.osd-pending")
MANUAL_LANG = pathlib.Path("/roms/vita3k/.lang-manual")

# key/value chosen in the in-game OSD -> ES card group + card stem
CARD_MAP = {
    ("sys-lang", "11"): ("选项 · 系统语言", "选项 · 系统语言 = 简体中文"),
    ("sys-lang", "1"): ("选项 · 系统语言", "选项 · 系统语言 = English"),
    ("resolution-multiplier", "1"): ("选项 · 画面倍率", "选项 · 画面倍率 = 1x 流畅"),
    ("resolution-multiplier", "2"): ("选项 · 画面倍率", "选项 · 画面倍率 = 2x 清晰"),
    ("guest-cores", "2"): ("选项 · 性能", "选项 · 性能 = 省电 2核"),
    ("guest-cores", "3"): ("选项 · 性能", "选项 · 性能 = 平衡 3核"),
}


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def mark_group(group, stem):
    """Star the chosen ES card and clear the star from its group siblings."""
    for p in CARD_DIR.glob("*.sh"):
        name = p.name
        if not name.startswith(group):
            continue
        clean = name.replace(" ★.sh", ".sh")
        target = clean[:-3] + (" ★.sh" if clean.startswith(stem) else ".sh")
        if target != name:
            try:
                p.rename(CARD_DIR / target)
            except OSError as ex:
                log(f"WARN: cannot rename {name}: {ex}")


def apply_pending():
    """Apply settings picked in the in-game OSD.

    Called from psvita-launch.sh cleanup AFTER Vita3K exits: Vita3K rewrites
    config.yml on shutdown, so writing it while the game runs would be lost.
    No ES restart here -- the launcher starts ES right after this call.
    """
    if not PENDING.exists():
        return 0
    pairs = []
    for line in PENDING.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            pairs.append((k.strip(), v.strip()))
    if not pairs:
        PENDING.unlink(missing_ok=True)
        return 0

    text = pathlib.Path(CFG).read_text(encoding="utf-8")
    for key, value in pairs:
        pat = re.compile(rf"^{re.escape(key)}:.*$", re.M)
        text = pat.sub(f"{key}: {value}", text, count=1) if pat.search(text) \
            else text.rstrip() + f"\n{key}: {value}\n"
    tmp = CFG + ".tmp"
    pathlib.Path(tmp).write_text(text, encoding="utf-8")
    os.replace(tmp, CFG)

    for key, value in pairs:
        if key == "sys-lang":
            MANUAL_LANG.touch()   # explicit OSD choice beats ES auto-detection
        entry = CARD_MAP.get((key, value))
        if entry:
            mark_group(*entry)
        log(f"OSD setting applied: {key} = {value}")
    PENDING.unlink(missing_ok=True)
    return 0


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--apply-pending":
        return apply_pending()
    if len(sys.argv) != 5:
        print("usage: psvita-option.py <group> <card-stem> <key> <value>", file=sys.stderr)
        return 2
    group, stem, key, value = sys.argv[1:5]

    state = subprocess.run(["systemctl", "is-active", "psvita-session.service"],
                           capture_output=True, text=True).stdout.strip()
    if state == "active":
        log(f"ABORT: Vita3K session active, cannot edit {key}")
        return 1

    try:
        text = pathlib.Path(CFG).read_text(encoding="utf-8")
    except OSError as ex:
        log(f"ABORT: cannot read {CFG}: {ex}")
        return 1

    pat = re.compile(rf"^{re.escape(key)}:.*$", re.M)
    if pat.search(text):
        new_text = pat.sub(f"{key}: {value}", text, count=1)
    else:
        new_text = text.rstrip() + f"\n{key}: {value}\n"
    tmp = CFG + ".tmp"
    pathlib.Path(tmp).write_text(new_text, encoding="utf-8")
    os.replace(tmp, CFG)

    if key == "sys-lang":
        MANUAL_LANG.touch()   # explicit card choice beats ES auto-detection
    mark_group(group, stem)

    log(f"{key} = {value}  [{stem}]")
    subprocess.run(["sudo", "systemctl", "restart", "--no-block", "emulationstation"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
