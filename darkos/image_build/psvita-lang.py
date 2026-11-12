#!/usr/bin/env python3
"""CN/EN auto-detection for the psvita port, mirroring dArkOS4RK3562.

Reference: dArkOS4RK3562 boot/hook.sh apply_localization() writes
`<string name="Language" value="zh-CN" />` into es_settings.cfg (and touches
/home/ark/.config/.cn) when the PC dtb selector chose Chinese; launchers such
as dreamcast.sh (flycast), ps2.sh and saturn.sh then grep that entry and export
zh_CN.UTF-8 so the emulator loads its Chinese resources.

For Vita3K the equivalent resource switch is config.yml `sys-lang`:
11 = Chinese (Simplified), 1 = English (US). This module is the single place
that decides it. A user choice made in the OSD / ES option cards wins until
--clear-manual is called.

Usage:
  psvita-lang.py --detect          print zh / en
  psvita-lang.py --sync            auto-apply (skipped when manually set)
  psvita-lang.py --ui-lang         print current UI language for the OSD
  psvita-lang.py --mark-manual     remember an explicit user choice
  psvita-lang.py --clear-manual    go back to auto detection
"""
import pathlib
import re
import sys
import time

ES_CFG = pathlib.Path("/home/ark/.emulationstation/es_settings.cfg")
CFG = pathlib.Path("/roms/vita3k/config.yml")
CARD_DIR = pathlib.Path("/roms/psvita")
UI_LANG = pathlib.Path("/roms/vita3k/.ui-lang")
MANUAL = pathlib.Path("/roms/vita3k/.lang-manual")
LOG = pathlib.Path("/roms/vita3k/es-option.log")

LANG_GROUPS = {
    "zh": ("选项 · 系统语言", "选项 · 系统语言 = 简体中文", "11"),
    "en": ("选项 · 系统语言", "选项 · 系统语言 = English", "1"),
}


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] psvita-lang: {msg}\n")


def detect():
    """Same test as flycast/ps2 launchers, plus hook.sh's legacy markers."""
    try:
        text = ES_CFG.read_text(encoding="utf-8")
        if re.search(r'<string\s+name="Language"\s+value="zh-CN"', text):
            return "zh"
    except OSError:
        pass
    if pathlib.Path("/home/ark/.config/.cn").exists() or pathlib.Path("/boot/.cn").exists():
        return "zh"
    return "en"


def current_sys_lang():
    try:
        for line in CFG.read_text(encoding="utf-8").splitlines():
            if line.startswith("sys-lang:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "1"


def mark_group(group, stem):
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
                log(f"cannot rename {name}: {ex}")


def apply(lang):
    group, stem, value = LANG_GROUPS[lang]
    try:
        text = CFG.read_text(encoding="utf-8")
    except OSError:
        return
    pat = re.compile(r"^sys-lang:.*$", re.M)
    text = pat.sub(f"sys-lang: {value}", text, count=1) if pat.search(text) \
        else text.rstrip() + f"\nsys-lang: {value}\n"
    tmp = str(CFG) + ".tmp"
    pathlib.Path(tmp).write_text(text, encoding="utf-8")
    pathlib.Path(tmp).replace(CFG)
    mark_group(group, stem)
    UI_LANG.write_text(lang + "\n", encoding="utf-8")
    log(f"auto language = {lang} -> sys-lang: {value}")


def sync():
    if MANUAL.exists():
        lang = "zh" if current_sys_lang() == "11" else "en"
        UI_LANG.write_text(lang + "\n", encoding="utf-8")
        log("manual override active, auto detection skipped")
        return
    detected = detect()
    if current_sys_lang() != LANG_GROUPS[detected][2]:
        apply(detected)
    else:
        UI_LANG.write_text(detected + "\n", encoding="utf-8")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "--detect"
    if arg == "--detect":
        print(detect())
    elif arg == "--sync":
        sync()
    elif arg == "--ui-lang":
        try:
            print(UI_LANG.read_text(encoding="utf-8").strip() or detect())
        except OSError:
            print(detect())
    elif arg == "--mark-manual":
        MANUAL.touch()
        log("manual language override set")
    elif arg == "--clear-manual":
        MANUAL.unlink(missing_ok=True)
        sync()
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
