#!/bin/bash
set -u

MARKER=/boot/pocketais-autoexpand.done
[ -e "$MARKER" ] && exit 0

root_src=$(/usr/bin/findmnt -n -o SOURCE /)
disk_name=$(/usr/bin/lsblk -no PKNAME "$root_src" | head -n1)
[ -n "$disk_name" ] || exit 1
disk=/dev/$disk_name
p5_sys=/sys/class/block/${disk_name}p5
p5dev=/dev/${disk_name}p5
[ -e "$p5_sys/start" ] || exit 1

start=$(cat "$p5_sys/start")
p5_size=$(cat "$p5_sys/size")
disk_size=$(cat "/sys/class/block/${disk_name}/size")
free_sectors=$((disk_size - start - p5_size))
p5_fstype=$(/usr/bin/lsblk -no FSTYPE "$p5dev" 2>/dev/null || true)

# Already a populated filesystem and no room to grow: only mark done.
if [ "$free_sectors" -lt 131072 ] && [ -n "$p5_fstype" ]; then
    # p5 already fills the disk (reused card): keep its data, but reconcile the
    # /roms UUID in fstab with this exFAT's real UUID so /roms actually mounts.
    uuid=$(/usr/bin/lsblk -no UUID "$p5dev")
    if [ -n "$uuid" ] && /usr/bin/grep -qE '^[^#]*[[:space:]]/roms[[:space:]]' /etc/fstab; then
        /usr/bin/sed -i -E "s#^[^#]*[[:space:]]/roms[[:space:]].*#UUID=${uuid} /roms exfat defaults,noatime,uid=1000,gid=1000,umask=000,nofail 0 0#" /etc/fstab
    fi
    /usr/bin/touch "$MARKER"
    /usr/bin/sync
    exit 0
fi

/usr/bin/umount /roms 2>/dev/null || true

# A smaller image flashed to a larger card leaves the backup GPT in the middle.
# -e relocates it to the end of the real card and exposes the remaining space.
/usr/sbin/sgdisk -e "$disk" >/dev/null 2>&1 || true

/usr/sbin/sgdisk \
    --delete=5 \
    --new=5:${start}:0 \
    --typecode=5:0700 \
    --change-name=5:ROMS \
    "$disk" || exit 1

/usr/bin/partx -u "$disk" >/dev/null 2>&1 || true
/usr/bin/udevadm settle

new_size=$(cat "$p5_sys/size" 2>/dev/null || echo "$p5_size")
if [ "$new_size" -le "$p5_size" ]; then
    /usr/bin/partx -d --nr 5 "$disk" >/dev/null 2>&1 || true
    /usr/bin/partx -a --nr 5 "$disk" >/dev/null 2>&1 || true
    /usr/bin/udevadm settle
    new_size=$(cat "$p5_sys/size" 2>/dev/null || echo "$p5_size")
    [ "$new_size" -gt "$p5_size" ] || exit 1
fi

# Refuse to continue if the GPT was not extended to the card.
if [ "$new_size" -lt $((disk_size - start - 131072)) ]; then
    exit 1
fi

/usr/sbin/mkfs.exfat -n ROMS "$p5dev" || exit 1

uuid=$(/usr/bin/lsblk -no UUID "$p5dev")
[ -n "$uuid" ] || exit 1

if /usr/bin/grep -qE '^[^#]*[[:space:]]/roms[[:space:]]' /etc/fstab; then
    /usr/bin/sed -i -E "s#^[^#]*[[:space:]]/roms[[:space:]].*#UUID=${uuid} /roms exfat defaults,noatime,uid=1000,gid=1000,umask=000,nofail 0 0#" /etc/fstab
else
    printf 'UUID=%s /roms exfat defaults,noatime,uid=1000,gid=1000,umask=000,nofail 0 0\n' "$uuid" >> /etc/fstab
fi

/usr/bin/mount /roms || exit 1
/usr/bin/touch "$MARKER"
/usr/bin/sync
exit 0
