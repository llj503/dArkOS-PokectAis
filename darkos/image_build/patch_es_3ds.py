#!/usr/bin/env python3
"""Add the Nintendo 3DS system (Azahar libretro core) to es_systems.cfg."""
import sys

p = sys.argv[1]
t = open(p, encoding="utf-8").read()
if '<name>3ds</name>' in t:
    print("3ds system already present")
    sys.exit(0)

block = '''\t<system>
\t\t<name>3ds</name>
\t\t<fullname>Nintendo 3DS</fullname>
\t\t<path>/roms/3ds</path>
\t\t<extension>.3ds .3DS .3dsx .3DSX .cci .CCI .cxi .CXI .app .APP .cia .CIA .elf .ELF .axf .AXF</extension>
\t\t<command>sudo perfmax %GOVERNOR% %ROM%; nice -n -19 /usr/local/bin/retroarch -L /home/ark/.config/retroarch/cores/azahar_libretro.so %ROM%; sudo perfnorm</command>
\t\t<emulators>
\t\t\t<emulator name="retroarch">
\t\t\t\t<cores>
\t\t\t\t\t<core>azahar</core>
\t\t\t\t</cores>
\t\t\t</emulator>
\t\t</emulators>
\t\t<platform>3ds</platform>
\t\t<theme>3ds</theme>
\t\t<manufacturer>Nintendo</manufacturer>
\t\t<release>2011</release>
\t\t<hardware>console</hardware>
\t</system>
'''

idx = t.rfind("</systemList>")
if idx < 0:
    sys.exit("systemList closing tag not found")

t = t[:idx] + block + t[idx:]
open(p, "w", encoding="utf-8").write(t)
print("3ds system added")
