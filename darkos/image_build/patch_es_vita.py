#!/usr/bin/env python3
"""Add the PlayStation Vita system (Vita3K-Plus) to es_systems.cfg."""
import sys
import xml.etree.ElementTree as ET

p = sys.argv[1]
t = open(p, encoding="utf-8").read()
if "<name>psvita</name>" in t:
    print("psvita system already present")
    sys.exit(0)

block = '''\t<system>
\t\t<name>psvita</name>
\t\t<fullname>Sony PlayStation Vita</fullname>
\t\t<path>/roms/psvita</path>
\t\t<extension>.vpk .VPK .zip .ZIP</extension>
\t\t<command>/usr/local/bin/psvita-launch.sh %ROM%</command>
\t\t<platform>psvita</platform>
\t\t<theme>psvita</theme>
\t\t<manufacturer>Sony</manufacturer>
\t\t<release>2011</release>
\t\t<hardware>console</hardware>
\t</system>
'''

idx = t.rfind("</systemList>")
if idx < 0:
    sys.exit("systemList closing tag not found")

t = t[:idx] + block + t[idx:]
open(p, "w", encoding="utf-8").write(t)
ET.parse(p)
print("psvita system added")