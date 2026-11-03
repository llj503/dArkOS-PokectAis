#!/bin/bash
# Finalize the sanitized dArkOS release image.
#
# Usage (as root):
#   sudo bash finalize_release.sh <dirty-raw.img> <p3-boot.img> <clean-p4.img> <clean-raw.img>
#
# - locks local account passwords and removes password-hash backups in clean p4;
# - writes the sanitized p3/p4 partitions into a copy of the raw image;
# - verifies partition slices and prints the clean raw SHA-256.
#
# The p3 image must already have its authorized_keys removed (mdel).
set -euo pipefail

RAW_SRC=${1:?usage: finalize_release.sh <dirty-raw.img> <p3-boot.img> <clean-p4.img> <clean-raw.img>}
P3_IMG=${2:?}
P4_IMG=${3:?}
RAW_DST=${4:?}

P3_OFFSET_MIB=16
P3_SIZE_MIB=99
P4_OFFSET_MIB=116
P4_SIZE_MIB=12044
RAW_SIZE=13019137024
MNT=/mnt/pocketais-p4-final

VERSION=${VERSION:-20261026}

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ -f "$RAW_SRC" ] || { echo "missing raw source: $RAW_SRC" >&2; exit 1; }
[ -f "$P3_IMG" ] || { echo "missing p3 image: $P3_IMG" >&2; exit 1; }
[ -f "$P4_IMG" ] || { echo "missing p4 image: $P4_IMG" >&2; exit 1; }

[ "$(stat -c %s "$RAW_SRC")" -eq "$RAW_SIZE" ] || { echo "unexpected raw source size" >&2; exit 1; }
[ "$(stat -c %s "$P3_IMG")" -eq $((P3_SIZE_MIB * 1048576)) ] || { echo "unexpected p3 size" >&2; exit 1; }
[ "$(stat -c %s "$P4_IMG")" -eq $((P4_SIZE_MIB * 1048576)) ] || { echo "unexpected p4 size" >&2; exit 1; }

if mdir -i "$P3_IMG" ::/authorized_keys >/dev/null 2>&1; then
    echo "ERROR: p3 still contains authorized_keys" >&2
    exit 1
fi

# The first-boot autoexpand must not be skipped on a freshly flashed card.
if mdir -i "$P3_IMG" ::/pocketais-autoexpand.done >/dev/null 2>&1; then
    mdel -i "$P3_IMG" ::/pocketais-autoexpand.done
fi
if mdir -i "$P3_IMG" ::/pocketais-autoexpand.done >/dev/null 2>&1; then
    echo "ERROR: p3 still contains pocketais-autoexpand.done" >&2
    exit 1
fi

# Lock the local user and root passwords in the clean p4 image.
umount "$MNT" 2>/dev/null || true
mkdir -p "$MNT"
mount -t btrfs -o loop,rw "$P4_IMG" "$MNT"
trap 'umount "$MNT" 2>/dev/null || true' EXIT

# /roms must mount by the exFAT label; the boot splash carries the version.
grep -qE '^LABEL=ROMS[[:space:]]+/roms[[:space:]]' "$MNT/etc/fstab" || { echo "ERROR: /roms is not LABEL=ROMS" >&2; exit 1; }
PLY="$MNT/usr/share/plymouth/themes/text.plymouth"
[ -f "$PLY" ] && sed -i -E "s/^title=.*/title=dArkOS (${VERSION})/" "$PLY"

for u in ark root; do
    if awk -F: -v u="$u" '$1==u{found=1} END{exit found?0:1}' "$MNT/etc/shadow"; then
        awk -F: -v u="$u" 'BEGIN{OFS=":"} $1==u{$2="*"} {print}' \
            "$MNT/etc/shadow" > "$MNT/etc/shadow.tmp"
        chmod 640 "$MNT/etc/shadow.tmp"
        chown 0:42 "$MNT/etc/shadow.tmp"
        mv "$MNT/etc/shadow.tmp" "$MNT/etc/shadow"
    fi
done
rm -f "$MNT/etc/shadow-" "$MNT/etc/gshadow-" "$MNT/etc/passwd-" "$MNT/etc/group-"

if awk -F: '($1=="ark"||$1=="root") && $2!="*" && $2!="!" && $2!="" {found=1} END{exit found?0:1}' "$MNT/etc/shadow"; then
    echo "ERROR: account password hash remains" >&2
    exit 1
fi
sync
umount "$MNT"
trap - EXIT

# Build a clean raw image by copying the source and replacing p3/p4.
rm -f "$RAW_DST"
cp --sparse=always "$RAW_SRC" "$RAW_DST"
dd if="$P3_IMG" of="$RAW_DST" bs=1M seek="$P3_OFFSET_MIB" conv=notrunc status=none
dd if="$P4_IMG" of="$RAW_DST" bs=1M seek="$P4_OFFSET_MIB" conv=notrunc status=none
sync

[ "$(stat -c %s "$RAW_DST")" -eq "$RAW_SIZE" ] || { echo "unexpected clean raw size" >&2; exit 1; }

p3_hash=$(dd if="$RAW_DST" bs=1M skip="$P3_OFFSET_MIB" count="$P3_SIZE_MIB" status=none | sha256sum | awk '{print $1}')
p3_ref=$(sha256sum "$P3_IMG" | awk '{print $1}')
[ "$p3_hash" = "$p3_ref" ] || { echo "p3 slice mismatch" >&2; exit 1; }

p4_hash=$(dd if="$RAW_DST" bs=1M skip="$P4_OFFSET_MIB" count="$P4_SIZE_MIB" status=none | sha256sum | awk '{print $1}')
p4_ref=$(sha256sum "$P4_IMG" | awk '{print $1}')
[ "$p4_hash" = "$p4_ref" ] || { echo "p4 slice mismatch" >&2; exit 1; }

echo "clean_raw=$RAW_DST"
echo "clean_raw_size=$(stat -c %s "$RAW_DST")"
sha256sum "$RAW_DST"
