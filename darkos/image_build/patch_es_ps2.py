#!/usr/bin/env python3
"""Add ARMSX2 choices to the ES ps2 system without reformatting the file."""
import re
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    text = f.read()

m = re.search(r"<system>\s*<name>ps2</name>.*?</system>", text, re.S)
if not m:
    sys.exit("ps2 system not found")

block = m.group(0)
old_cmd = "/usr/local/bin/standalone-pcsx2sa %EMULATOR% %ROM%"
new_cmd = "/usr/local/bin/ps2-launcher %EMULATOR% %ROM%"
if old_cmd in block:
    block = block.replace(old_cmd, new_cmd)
elif new_cmd not in block:
    sys.exit("ps2 command not recognized")

if 'name="armsx2"' not in block:
    emu_re = re.compile(r'(<emulator\s+name="standalone-pcsx2sa"\s*>\s*</emulator>)', re.S)
    extra = (
        '\n\t\t\t<emulator name="armsx2">\n\t\t\t</emulator>'
        '\n\t\t\t<emulator name="armsx2-stock">\n\t\t\t</emulator>'
    )
    block, n = emu_re.subn(lambda mo: mo.group(1) + extra, block, count=1)
    if n != 1:
        sys.exit("standalone-pcsx2sa emulator entry not recognized")

text = text[:m.start()] + block + text[m.end():]
with open(path, "w", encoding="utf-8") as f:
    f.write(text)

ET.parse(path)
if new_cmd not in text or 'name="armsx2"' not in text or 'name="armsx2-stock"' not in text:
    sys.exit("ps2 patch verification failed")
print("ES ps2: ARMSX2 + armsx2-stock entries added")
