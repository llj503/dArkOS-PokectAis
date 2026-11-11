#!/bin/bash
# Install the Vita3K-Plus bundle on a running dArkOS device. Run as root.
#
#   install_vita3k.sh <bundle.tar.zst> [scripts-dir]
#
# scripts-dir defaults to the directory holding this script and must contain
# psvita-launch.sh, vita3k-ports-gui.sh and patch_es_vita.py.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

TARBALL=${1:?usage: install_vita3k.sh <bundle.tar.zst> [scripts-dir]}
SCRIPTS=${2:-$(cd "$(dirname "$0")" && pwd)}
BUNDLE=/opt/vita3k
ESCFG=/etc/emulationstation/es_systems.cfg

[ -r "$TARBALL" ] || { echo "cannot read $TARBALL" >&2; exit 1; }
for f in psvita-launch.sh vita3k-ports-gui.sh patch_es_vita.py; do
    [ -r "$SCRIPTS/$f" ] || { echo "missing $SCRIPTS/$f" >&2; exit 1; }
done

if [ -r "$TARBALL.sha256" ]; then
    echo "== verifying checksum =="
    (cd "$(dirname "$TARBALL")" && sha256sum -c "$(basename "$TARBALL").sha256")
fi

echo "== extracting to $BUNDLE =="
mkdir -p "$BUNDLE"
tar --zstd -xf "$TARBALL" -C "$BUNDLE"
chmod +x "$BUNDLE/vita3k.sh" "$BUNDLE/vita3k"
[ -x "$BUNDLE/vita3k" ] || { echo "$BUNDLE/vita3k missing after extract" >&2; exit 1; }

echo "== installing launcher =="
install -m 0755 "$SCRIPTS/psvita-launch.sh" /usr/local/bin/psvita-launch.sh
mkdir -p /roms/psvita /roms/vita3k /roms/ports
chown ark:ark /roms/psvita /roms/vita3k /roms/ports
install -m 0755 -o ark -g ark "$SCRIPTS/vita3k-ports-gui.sh" "/roms/ports/Vita3K.sh"
[ -e "$BUNDLE/portable" ] || ln -s /roms/vita3k "$BUNDLE/portable"

echo "== adding the psvita system to ES =="
if grep -q "<name>psvita</name>" "$ESCFG"; then
    echo "already present"
else
    cp -a "$ESCFG" "$ESCFG.bak-vita3k"
    python3 "$SCRIPTS/patch_es_vita.py" "$ESCFG"
fi

echo "== restarting ES =="
systemctl restart emulationstation
echo "installed. Games: /roms/psvita (.vpk/.zip). GUI: Ports -> Vita3K."
echo "Vita data (firmware, installed apps, config): /roms/vita3k"