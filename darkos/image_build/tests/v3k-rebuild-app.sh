#!/bin/bash
# Rebuild the Vita app install without Vita3K's installer (whose exFAT write
# storm hard-locked the device). Extract to btrfs, then a single idle-priority
# sequential copy onto exFAT. Self-contained; leaves the zip untouched.
set -u
ZIP="/roms/psvita/Blast Em Bunnies (PCSE00328).zip"
APP=/roms/vita3k/fs/ux0/app/PCSE00328
STAGE=/home/ark/vita-rebuild
rm -rf "$STAGE"; mkdir -p "$STAGE"
echo "== extract to btrfs stage =="
unzip -q -o "$ZIP" -d "$STAGE" || { echo UNZIP_FAIL; exit 1; }
SRC=$(find "$STAGE" -type d -name PCSE00328 -path "*/app/*" | head -1)
echo "SRC=$SRC"
[ -n "$SRC" ] || { echo NO_SRC; exit 1; }
echo "== remove partial app =="
rm -rf "$APP"; mkdir -p "$APP"
echo "== copy to exFAT (ionice idle) =="
ionice -c3 cp -a "$SRC/." "$APP/" || { echo CP_FAIL; exit 1; }
sync
echo "== verify =="
if [ -f "$APP/eboot.bin" ]; then echo EBOOT_OK; else echo EBOOT_MISSING; fi
echo "files=$(find "$APP" -type f | wc -l)"
rm -rf "$STAGE"
echo REBUILD_DONE