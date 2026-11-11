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
# Stage first, then swap. Extracting straight over an older bundle leaves stale
# Qt modules behind that can shadow the new ones, and a failed extract would
# leave a half-written install. Vita data lives in /roms/vita3k (portable is a
# symlink into it), so the bundle directory itself is disposable.
STAGE=$(mktemp -d /opt/vita3k.new.XXXXXX)
trap 'rm -rf "$STAGE"' EXIT
tar --zstd -xf "$TARBALL" -C "$STAGE"
chmod +x "$STAGE/vita3k.sh" "$STAGE/Vita3K"
[ -x "$STAGE/Vita3K" ] || { echo "$STAGE/Vita3K missing after extract" >&2; exit 1; }
if [ -d "$BUNDLE" ]; then
    rm -rf "$BUNDLE.old"
    mv "$BUNDLE" "$BUNDLE.old"
fi
mv "$STAGE" "$BUNDLE"
trap - EXIT
# mktemp creates 0700; the GUI runs as ark and has to be able to walk into it.
chmod 0755 "$BUNDLE"
rm -rf "$BUNDLE.old"

echo "== installing launcher =="
install -m 0755 "$SCRIPTS/psvita-launch.sh" /usr/local/bin/psvita-launch.sh
# gptokeyb map: Weston ignores gamepads, so the Qt GUI needs uinput keys.
if [ -r "$SCRIPTS/vita3k.gptk" ]; then
    install -m 0644 "$SCRIPTS/vita3k.gptk" /usr/local/share/vita3k.gptk
fi
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

echo "== theme =="
# es-theme-nes-box has no psvita art, so the carousel row would be blank.
THEMESET=$(sed -n 's/.*<string name="ThemeSet" value="\([^"]*\)".*/\1/p' \
    /home/ark/.emulationstation/es_settings.cfg 2>/dev/null | head -1)
THEME="/home/ark/.emulationstation/themes/${THEMESET:-es-theme-nes-box}"
if [ -d "$THEME" ] && [ ! -d "$THEME/psvita" ] && [ -r "$SCRIPTS/make_psvita_theme.py" ]; then
    python3 "$SCRIPTS/make_psvita_theme.py" "$THEME" \
        || echo "  skipped (Pillow unavailable), the row will have no logo"
    chown -R ark:ark "$THEME/psvita" 2>/dev/null || true
fi

echo "== restarting ES =="
systemctl restart emulationstation
echo "installed. Games: /roms/psvita (.vpk/.zip). GUI: Ports -> Vita3K."
echo "Vita data (firmware, installed apps, config): /roms/vita3k"