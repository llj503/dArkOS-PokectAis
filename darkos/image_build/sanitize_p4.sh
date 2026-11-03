#!/bin/bash
# Sanitize the extracted dArkOS p4 rootfs image and produce a clean BTRFS image.
#
# Usage (as root):
#   sudo bash sanitize_p4.sh <p4-rootfs.img> <clean-output.img>
#
# The source image is a BTRFS filesystem image (the p4 partition), not the whole
# disk image. The script:
#   1. mounts the source read/write and removes device-specific secrets;
#   2. verifies the active tree no longer contains the WiFi PSK/SSID or SSH keys;
#   3. creates a fresh BTRFS filesystem of the same size and copies the sanitized
#      tree into it, so old free-space data is not carried over;
#   4. checks the new image and prints its SHA-256.
set -euo pipefail

SRC=${1:?usage: sanitize_p4.sh <p4-rootfs.img> <clean-output.img>}
DST=${2:?usage: sanitize_p4.sh <p4-rootfs.img> <clean-output.img>}
MNT=/mnt/pocketais-p4-src
NEW=/mnt/pocketais-p4-new

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ -f "$SRC" ] || { echo "source not found: $SRC" >&2; exit 1; }

cleanup() {
    umount "$NEW" 2>/dev/null || true
    umount "$MNT" 2>/dev/null || true
}
trap cleanup EXIT

umount "$MNT" 2>/dev/null || true
umount "$NEW" 2>/dev/null || true
mkdir -p "$MNT" "$NEW"
mount -t btrfs -o loop,rw "$SRC" "$MNT"

# /roms must mount by the exFAT label; the UUID is card-specific.
if grep -qE '^[^#]*[[:space:]]/roms[[:space:]]' "$MNT/etc/fstab"; then
    sed -i -E 's#^[^#]*[[:space:]]/roms[[:space:]].*#LABEL=ROMS /roms exfat defaults,noatime,uid=1000,gid=1000,umask=000,nofail 0 0#' "$MNT/etc/fstab"
else
    printf 'LABEL=ROMS /roms exfat defaults,noatime,uid=1000,gid=1000,umask=000,nofail 0 0\n' >> "$MNT/etc/fstab"
fi
echo "fstab /roms set to LABEL=ROMS"

# Capture the WiFi profile secret for verification, without printing it.
NM_FILE=$(find "$MNT/etc/NetworkManager/system-connections" -maxdepth 1 -type f -name '*.nmconnection' 2>/dev/null | head -1 || true)
PSK_VALUE=""
SSID_BASE=""
if [ -n "$NM_FILE" ]; then
    PSK_VALUE=$(awk -F= '/^psk=/{print substr($0,5)}' "$NM_FILE" | head -1 || true)
    SSID_BASE=$(basename "$NM_FILE" .nmconnection)
fi

# Remove SSH host keys and user key material.
rm -f "$MNT"/etc/ssh/ssh_host_* || true
find "$MNT/home" "$MNT/root" -type d -name .ssh -prune -exec rm -rf {} + 2>/dev/null || true
find "$MNT/home" "$MNT/root" -type f \( -name authorized_keys -o -name known_hosts -o -name id_rsa -o -name id_ed25519 \) -print -delete 2>/dev/null || true

# Remove saved WiFi/network profiles and local secrets.
rm -f "$MNT"/etc/NetworkManager/system-connections/*.nmconnection || true
rm -rf "$MNT/var/lib/NetworkManager" "$MNT/var/lib/connman" "$MNT/var/lib/bluetooth"

# Remove shell histories, caches and logs.
for d in "$MNT"/home/* "$MNT/root"; do
    [ -d "$d" ] || continue
    rm -rf "$d/.cache" "$d/.thumbnails" 2>/dev/null || true
    rm -f "$d/.bash_history" "$d/.zsh_history" "$d/.lesshst" "$d/.viminfo" 2>/dev/null || true
    rm -f "$d/.local/share/recently-used.xbel" 2>/dev/null || true
done
rm -rf "$MNT"/var/log/* "$MNT"/tmp/* "$MNT"/var/tmp/*

# Reset the machine identity; systemd regenerates /etc/machine-id on boot.
if [ -e "$MNT/etc/machine-id" ]; then
    chmod 644 "$MNT/etc/machine-id"
    : > "$MNT/etc/machine-id"
fi
rm -f "$MNT/var/lib/dbus/machine-id"
ln -s /etc/machine-id "$MNT/var/lib/dbus/machine-id"

# Do not ship RetroArch netplay credentials.
RAG="$MNT/home/ark/.config/retroarch/retroarch.cfg"
if [ -f "$RAG" ] && grep -qE '^[[:space:]]*netplay_password[[:space:]]*=' "$RAG"; then
    sed -i -E 's/^[[:space:]]*netplay_password[[:space:]]*=.*/netplay_password = ""/' "$RAG"
    echo "cleared RetroArch netplay_password"
fi

# Ensure missing SSH host keys are generated on the first boot.
if [ -f "$MNT/lib/systemd/system/sshd-keygen.service" ] || [ -f "$MNT/usr/lib/systemd/system/sshd-keygen.service" ]; then
    mkdir -p "$MNT/etc/systemd/system/multi-user.target.wants"
    ln -sf /lib/systemd/system/sshd-keygen.service "$MNT/etc/systemd/system/multi-user.target.wants/sshd-keygen.service"
fi

# Fail if the active tree still contains the captured WiFi secret or device keys.
fail=0
if [ -n "$PSK_VALUE" ]; then
    matches=$(grep -rIlF -- "$PSK_VALUE" "$MNT" 2>/dev/null || true)
    count=$(printf '%s\n' "$matches" | grep -c . || true)
    echo "source_psk_matches=$count"
    if [ "$count" -ne 0 ]; then
        printf '%s\n' "$matches" | head -10
        fail=1
    fi
fi
if [ -n "$SSID_BASE" ]; then
    matches=$(grep -rIlF -- "$SSID_BASE" "$MNT" 2>/dev/null || true)
    count=$(printf '%s\n' "$matches" | grep -c . || true)
    echo "source_ssid_matches=$count"
    if [ "$count" -ne 0 ]; then
        printf '%s\n' "$matches" | head -10
        fail=1
    fi
fi
if find "$MNT/etc" "$MNT/home" "$MNT/root" -type f -name 'ssh_host_*' 2>/dev/null | grep -q .; then
    echo "ERROR: SSH host keys remain" >&2
    fail=1
fi
if [ "$fail" -ne 0 ]; then
    echo "ERROR: sanitization verification failed" >&2
    exit 1
fi

# Create a fresh BTRFS image and copy only the sanitized tree into it.
SIZE=$(stat -c %s "$SRC")
rm -f "$DST"
truncate -s "$SIZE" "$DST"
mkfs.btrfs -f -L ROOTFS "$DST" >/dev/null
mount -t btrfs -o loop,rw "$DST" "$NEW"
rsync -aHAXS --numeric-ids --exclude=/lost+found "$MNT"/ "$NEW"/
sync

# Verify the new filesystem.
if find "$NEW/etc" "$NEW/home" "$NEW/root" -type f -name 'ssh_host_*' 2>/dev/null | grep -q .; then
    echo "ERROR: SSH host keys in new image" >&2
    exit 1
fi
if find "$NEW/etc/NetworkManager/system-connections" -type f -name '*.nmconnection' 2>/dev/null | grep -q .; then
    echo "ERROR: WiFi profile in new image" >&2
    exit 1
fi
if [ -n "$PSK_VALUE" ]; then
    count=$(grep -rIlF -- "$PSK_VALUE" "$NEW" 2>/dev/null | grep -c . || true)
    echo "new_psk_matches=$count"
    [ "$count" -eq 0 ] || { echo "ERROR: PSK in new image" >&2; exit 1; }
fi
if [ -n "$SSID_BASE" ]; then
    count=$(grep -rIlF -- "$SSID_BASE" "$NEW" 2>/dev/null | grep -c . || true)
    echo "new_ssid_matches=$count"
    [ "$count" -eq 0 ] || { echo "ERROR: SSID in new image" >&2; exit 1; }
fi
count=$(grep -rIl -E 'BEGIN .*PRIVATE KEY' "$NEW/etc" "$NEW/home" "$NEW/root" 2>/dev/null | grep -c . || true)
echo "new_private_key_headers=$count"
[ "$count" -eq 0 ] || { echo "ERROR: private key material in new image" >&2; exit 1; }

sync
umount "$NEW"
umount "$MNT"
trap - EXIT

echo "clean_image=$DST"
echo "clean_size=$(stat -c %s "$DST")"
sha256sum "$DST"
