#!/bin/bash
# build_image_20261025.sh -- runs ON the Pocket AIS device as root.
# Builds a sanitized, bootable, Windows-clean dArkOS TF image.
#
# Fixes vs the 20261020 image:
#   * p3 (dArkOS_Fat) FAT32 dirty bit is CLEARED (main+backup boot sector 0x41),
#     so Windows no longer pops "Scan and fix / repair partition" after flashing.
#   * p4 rootfs sanitized in place (SSH keys, WiFi PSK, machine-id, password
#     hashes, logs, histories, RetroArch netplay pw) and free space zero-scrubbed
#     so deleted secrets are not recoverable; p4 btrfs grown to fill the partition
#     (absorbs the ~3.95 GiB slack, no stale data).
#   * GPT rebuilt to match the running device byte-for-byte (disk/part GUIDs,
#     p1/p2 Rockchip type GUIDs, p3 LegacyBIOSBootable attr) via fix_gpt python.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

IMG=/roms/pocketAis-dArkOS-20261025-autoexpand-sanitized.img
LOG=/roms/pocketais-image-build-20261025.log
STATUS=/roms/pocketais-image-build-20261025.status
SRC=/dev/mmcblk1

# fix_gpt_20261020.py: prefer the copy next to this script, else /roms.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXGPT="$SCRIPT_DIR/fix_gpt_20261020.py"
[ -f "$FIXGPT" ] || FIXGPT=/roms/fix_gpt_20261020.py

# ---- geometry (sectors), matches the running device ----
P3_START=32768;  P3_END=235519
P4_START=237568
P5_START=24903680
P5_SECTORS=524288                       # 256 MiB placeholder for p5
P5_END=$((P5_START + P5_SECTORS - 1))
IMG_SECTORS=$((P5_END + 1 + 34))
IMG_BYTES=$((IMG_SECTORS * 512))
COPY_SECTORS=$P5_START                  # dd p1..p4
COUNT=$((COPY_SECTORS / 8192))          # 4 MiB blocks
P3_OFF=$((P3_START * 512)); P3_LEN=$(((P3_END - P3_START + 1) * 512))
P4_OFF=$((P4_START * 512)); P4_LEN=$(((P5_START - P4_START) * 512))

DISK_GUID=380FCF94-BE32-4881-B5D0-4364F086DE7F
P1_GUID=4CE8F710-D8AA-4B64-8A23-A61CB6C0652F
P2_GUID=7959A2C4-2DE1-4451-9303-FA5D83AEE2F3
P3_GUID=8D14D6BA-FE8D-4971-A653-058337B876FB
P4_GUID=14A2F32A-21F1-4513-8BB8-1066C69CEA6F
P5_GUID=0693D428-8F6D-4481-8BB1-7FDA1A3F8FFE

exec >>"$LOG" 2>&1
echo RUNNING > "$STATUS"
log(){ echo "[$(date '+%F %T')] $*"; }
finish(){ rc=$?; trap - EXIT
  if [ "$rc" -eq 0 ]; then echo DONE > "$STATUS"; else echo "FAILED rc=$rc" > "$STATUS"; fi
  sync; systemctl start emulationstation >/dev/null 2>&1 || true
  /sbin/losetup -D >/dev/null 2>&1 || true
  log "exit rc=$rc"; exit "$rc"; }
trap finish EXIT

log "=== Pocket AIS image build 20261025 ==="
log "img_bytes=$IMG_BYTES copy_sectors=$COPY_SECTORS p4_off=$P4_OFF p4_len=$P4_LEN"

[ $((COUNT * 8192)) -eq "$COPY_SECTORS" ] || { log "ERROR: p5 start not 4M aligned"; exit 1; }
[ -x /usr/sbin/sgdisk ] || { log "ERROR: sgdisk missing"; exit 1; }
[ -f "$FIXGPT" ] || { log "ERROR: fix_gpt script missing at $FIXGPT"; exit 1; }
command -v python3 >/dev/null || { log "ERROR: python3 missing"; exit 1; }

# RESUME=1 skips dd+sgdisk (steps 1-3) when a correctly-sized raw already exists,
# so a failed run can be finished without re-copying 12.7 GiB or needing free space.
RESUME_MODE=0
if [ "${RESUME:-0}" = "1" ] && [ -f "$IMG" ] && [ "$(stat -c %s "$IMG" 2>/dev/null)" -eq "$IMG_BYTES" ]; then
  RESUME_MODE=1
  log "=== RESUME mode: existing image is correct size ($IMG_BYTES); skipping steps 1-3 ==="
else
  avail=$(df -B1 --output=avail /roms | tail -n1 | tr -d ' ')
  [ "$avail" -ge $((IMG_BYTES + 1073741824)) ] || { log "ERROR: not enough space avail=$avail"; exit 1; }
  log "avail=$avail"
fi

if [ "$RESUME_MODE" -eq 0 ]; then
  log "=== [1/8] stop EmulationStation + sync ==="
  systemctl stop emulationstation || true
  sync; sleep 2

  log "=== [2/8] dd p1-p4: $COUNT x 4M ==="
  rm -f "$IMG"
  dd if="$SRC" of="$IMG" bs=4M count="$COUNT" conv=fsync status=progress
  [ "$(stat -c %s "$IMG")" -eq $((COPY_SECTORS * 512)) ] || { log "ERROR: short copy"; exit 1; }

  log "=== [2/8] append 256M p5 placeholder + truncate to $IMG_BYTES ==="
  dd if=/dev/zero of="$IMG" bs=4M count=64 seek="$COUNT" conv=fsync status=none
  truncate -s "$IMG_BYTES" "$IMG"
  [ "$(stat -c %s "$IMG")" -eq "$IMG_BYTES" ] || { log "ERROR: image size mismatch"; exit 1; }

  log "=== [3/8] sgdisk rebuild GPT (placeholder types) ==="
  /usr/sbin/sgdisk --clear \
    --disk-guid=$DISK_GUID \
    --new=1:16384:24575   --typecode=1:8300 --change-name=1:uboot     --partition-guid=1:$P1_GUID \
    --new=2:24576:32767   --typecode=2:8300 --change-name=2:resource  --partition-guid=2:$P2_GUID \
    --new=3:$P3_START:$P3_END --typecode=3:0700 --change-name=3:dArkOS_Fat --partition-guid=3:$P3_GUID \
    --new=4:$P4_START:$((P5_START - 1)) --typecode=4:0700 --change-name=4:rootfs --partition-guid=4:$P4_GUID \
    --new=5:$P5_START:$P5_END --typecode=5:0700 --change-name=5:ROMS --partition-guid=5:$P5_GUID \
    "$IMG"
else
  log "=== [1-3/8] skipped (resume): dd + sgdisk already done ==="
fi

log "=== [4/8] sanitize p4 in place (loop, btrfs) ==="
LOOP4=$(/sbin/losetup -f --show -o "$P4_OFF" --sizelimit "$P4_LEN" "$IMG")
log "p4 loop=$LOOP4"
# The image p4 is a byte copy of the live rootfs and therefore shares its btrfs
# FSID; mounting it while the live root is mounted fails ("duplicate device",
# EEXIST). Rewrite the image p4 FSID (LABEL=ROOTFS is preserved). Root is found
# by PATH/LABEL, never by UUID (fstab + extlinux use /dev/mmcblk1p4), and the
# 20261020 sanitize rebuilt p4 with mkfs.btrfs (a brand-new FSID) and still
# boots -- so changing the FSID is boot-safe.
LIVE_FSID=$(btrfs inspect-internal dump-super /dev/mmcblk1p4 2>/dev/null | awk '/^fsid/{print $2; exit}')
IMG_FSID=$(btrfs inspect-internal dump-super "$LOOP4" 2>/dev/null | awk '/^fsid/{print $2; exit}')
log "live_fsid=$LIVE_FSID img_fsid=$IMG_FSID"
if [ -z "$IMG_FSID" ] || [ "$LIVE_FSID" = "$IMG_FSID" ]; then
  log "rewriting image p4 fsid (btrfstune -u) to avoid duplicate-device conflict"
  btrfstune -f -u "$LOOP4"
  IMG_FSID=$(btrfs inspect-internal dump-super "$LOOP4" 2>/dev/null | awk '/^fsid/{print $2; exit}')
  log "new img_fsid=$IMG_FSID"
fi
mkdir -p /mnt/imgp4
mount -o rw,compress=no "$LOOP4" /mnt/imgp4
M=/mnt/imgp4

# grow btrfs to fill the whole p4 partition (absorbs the ~3.95 GiB slack)
btrfs filesystem resize max "$M" && log "p4 btrfs resized to max" || log "WARN resize max failed"
log "p4 usage after resize:"; btrfs filesystem usage "$M" | grep -iE 'Device size|Used:|Free ' | head -4

# capture WiFi secret for verification (never printed)
NM_FILE=$(find "$M/etc/NetworkManager/system-connections" -maxdepth 1 -type f -name '*.nmconnection' 2>/dev/null | head -1 || true)
PSK_VALUE=""; SSID_BASE=""
if [ -n "$NM_FILE" ]; then
  PSK_VALUE=$(awk -F= '/^psk=/{print substr($0,5)}' "$NM_FILE" | head -1 || true)
  SSID_BASE=$(basename "$NM_FILE" .nmconnection)
fi

rm -f "$M"/etc/ssh/ssh_host_* || true
find "$M/home" "$M/root" -type d -name .ssh -prune -exec rm -rf {} + 2>/dev/null || true
find "$M/home" "$M/root" -type f \( -name authorized_keys -o -name known_hosts -o -name id_rsa -o -name id_ed25519 \) -print -delete 2>/dev/null || true
rm -f "$M"/etc/NetworkManager/system-connections/*.nmconnection || true
rm -rf "$M/var/lib/NetworkManager" "$M/var/lib/connman" "$M/var/lib/bluetooth"
for d in "$M"/home/* "$M/root"; do
  [ -d "$d" ] || continue
  rm -rf "$d/.cache" "$d/.thumbnails" 2>/dev/null || true
  rm -f "$d/.bash_history" "$d/.zsh_history" "$d/.lesshst" "$d/.viminfo" 2>/dev/null || true
  rm -f "$d/.local/share/recently-used.xbel" 2>/dev/null || true
done
rm -rf "$M"/var/log/* "$M"/tmp/* "$M"/var/tmp/*
if [ -e "$M/etc/machine-id" ]; then chmod 644 "$M/etc/machine-id"; : > "$M/etc/machine-id"; fi
rm -f "$M/var/lib/dbus/machine-id"; ln -s /etc/machine-id "$M/var/lib/dbus/machine-id"
for RAG in "$M/home/ark/.config/retroarch/retroarch.cfg" "$M/home/ark/.config/retroarch32/retroarch.cfg"; do
  if [ -f "$RAG" ] && grep -qE '^[[:space:]]*netplay_password[[:space:]]*=' "$RAG"; then
    sed -i -E 's/^[[:space:]]*netplay_password[[:space:]]*=.*/netplay_password = ""/' "$RAG"
    log "cleared netplay_password in $RAG"
  fi
done
# Distribution default login: ark / ark (convenient after flashing); root stays
# locked. ARK_HASH is a yescrypt hash of "ark".
ARK_HASH='$y$j9T$4w5B4LAPVIf7jlWZ.wsgj.$O.N6vUQYWh0bnsrG7CWE6VPDD.juaE5YhXqb50TtFv/'
awk -F: -v h="$ARK_HASH" 'BEGIN{OFS=":"} $1=="ark"{$2=h} $1=="root"{$2="*"} {print}' "$M/etc/shadow" > "$M/etc/shadow.tmp"
chmod 640 "$M/etc/shadow.tmp"; chown 0:42 "$M/etc/shadow.tmp"; mv "$M/etc/shadow.tmp" "$M/etc/shadow"
log "default login set: ark/ark (root locked)"
rm -f "$M/etc/shadow-" "$M/etc/gshadow-" "$M/etc/passwd-" "$M/etc/group-"
if [ -f "$M/lib/systemd/system/sshd-keygen.service" ] || [ -f "$M/usr/lib/systemd/system/sshd-keygen.service" ]; then
  mkdir -p "$M/etc/systemd/system/multi-user.target.wants"
  ln -sf /lib/systemd/system/sshd-keygen.service "$M/etc/systemd/system/multi-user.target.wants/sshd-keygen.service"
fi
sync

# verify secrets gone from the active tree
fail=0
if [ -n "$PSK_VALUE" ]; then c=$(grep -rIlF -- "$PSK_VALUE" "$M" 2>/dev/null | grep -c . || true); log "psk_matches=$c"; [ "$c" -eq 0 ] || fail=1; fi
if [ -n "$SSID_BASE" ]; then c=$(grep -rIlF -- "$SSID_BASE" "$M" 2>/dev/null | grep -c . || true); log "ssid_matches=$c"; [ "$c" -eq 0 ] || fail=1; fi
awk -F: '$1=="root" && $2!="*" && $2!="!" && $2!="" {f=1} END{exit f?0:1}' "$M/etc/shadow" && { log "ERROR: root password not locked"; fail=1; }
awk -F: '$1=="ark" && ($2=="*" || $2=="!" || $2=="") {f=1} END{exit f?0:1}' "$M/etc/shadow" && { log "ERROR: ark default password missing"; fail=1; }
[ -s "$M/etc/machine-id" ] && { log "ERROR: machine-id not empty"; fail=1; }
[ "$fail" -eq 0 ] || { log "ERROR: sanitize verification failed"; exit 1; }

# The device's original SSH host keys were removed above. Stock dArkOS shipped
# pre-generated keys and sshd refuses to start without them, which left
# ssh.service failing and blocked first boot (observed on the first 20261025
# flash). Generate a fresh set, and neutralise sshd-keygen's fragile
# ConditionFirstBoot (it never fires once machine-id has been regenerated) so
# keys can be recreated if they are ever missing.
log "generating fresh SSH host keys"
rm -f "$M"/etc/ssh/ssh_host_*
ssh-keygen -q -t ed25519     -f "$M/etc/ssh/ssh_host_ed25519_key" -N '' -C 'root@pocketais'
ssh-keygen -q -t ecdsa       -f "$M/etc/ssh/ssh_host_ecdsa_key"   -N '' -C 'root@pocketais'
ssh-keygen -q -t rsa -b 3072 -f "$M/etc/ssh/ssh_host_rsa_key"     -N '' -C 'root@pocketais'
chown 0:0 "$M"/etc/ssh/ssh_host_* 2>/dev/null || true
chmod 600 "$M"/etc/ssh/ssh_host_ed25519_key "$M"/etc/ssh/ssh_host_ecdsa_key "$M"/etc/ssh/ssh_host_rsa_key
chmod 644 "$M"/etc/ssh/ssh_host_ed25519_key.pub "$M"/etc/ssh/ssh_host_ecdsa_key.pub "$M"/etc/ssh/ssh_host_rsa_key.pub
mkdir -p "$M/etc/systemd/system/sshd-keygen.service.d"
cat > "$M/etc/systemd/system/sshd-keygen.service.d/10-ensure.conf" <<'DROPIN'
[Unit]
ConditionFirstBoot=
After=systemd-remount-fs.service local-fs.target
DROPIN
log "host keys generated: $(ls "$M"/etc/ssh/ssh_host_*_key 2>/dev/null | wc -l)"

# ---- PortMaster framework + port integration (data-free; user installs ports) ----
PMZIP=/tmp/PortMaster.zip
if curl -fsSL -o "$PMZIP" "https://github.com/PortsMaster/PortMaster-New/releases/latest/download/PortMaster.zip"; then
  log "installing PortMaster -> /opt/system/Tools/PortMaster"
  mkdir -p "$M/opt/system/Tools"
  python3 - "$PMZIP" "$M/opt/system/Tools" <<'PY'
import sys, zipfile
zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])
PY
  CT="$M/opt/system/Tools/PortMaster/control.txt"
  if ! grep -q 'dArkOS additions' "$CT"; then
    cat >> "$CT" <<'PMEOF'

# ---- dArkOS additions: helpers used by modern PortMaster ports ----
CFW_NAME="${CFW_NAME:-dArkOS}"
GPTOKEYB2="$ESUDO $controlfolder/gptokeyb -sudokill"
pm_message() { echo "[PortMaster] $*"; }
pm_finish() { :; }
pm_platform_helper() { :; }
PMEOF
  fi
  log "PortMaster installed; control.txt patched ($(grep -c 'GPTOKEYB2' "$CT") GPTOKEYB2 lines)"
else
  log "WARN: PortMaster.zip download failed; ports may not launch"
fi
# Route ES children (ports) through ALSA softvol so system volume keys work in-game.
mkdir -p "$M/etc/systemd/system/emulationstation.service.d"
cat > "$M/etc/systemd/system/emulationstation.service.d/audio.conf" <<'AUDEOF'
[Service]
Environment="AUDIODEV=default"
AUDEOF
# Allow password login (image default ark/ark).
mkdir -p "$M/etc/ssh/sshd_config.d"
cat > "$M/etc/ssh/sshd_config.d/10-passwordauth.conf" <<'SSHDEOF'
PasswordAuthentication yes
SSHDEOF
log "port-audio + sshd-password drop-ins written"

log "=== [4/8] zero-scrub p4 free space (compress=no) ==="
dd if=/dev/zero of="$M/.__zerofill" bs=4M status=none || true
sync
rm -f "$M/.__zerofill"
sync
log "p4 df after scrub:"; df -h "$M" | tail -1
umount "$M"; /sbin/losetup -d "$LOOP4"; rmdir /mnt/imgp4

log "=== [5/8] verify p4 (ro loop) ==="
mkdir -p /mnt/imgroot
LOOPV=$(/sbin/losetup -f --show -o "$P4_OFF" --sizelimit "$P4_LEN" "$IMG")
mount -o ro "$LOOPV" /mnt/imgroot
V=/mnt/imgroot
test -x "$V/usr/bin/emulationstation/emulationstation" || { log "ERROR: ES binary missing"; exit 1; }
ES_SIZE=$(stat -c %s "$V/usr/bin/emulationstation/emulationstation")
[ "$ES_SIZE" -gt 5000000 ] || { log "ERROR: ES binary too small ($ES_SIZE)"; exit 1; }
for f in /opt/ngp-panel/ngp-wifi-gui /opt/ngp-panel/ngp-panel-gui "/opt/system/网络设置.sh" /usr/local/sbin/pocketais-usb-role-watch /usr/local/sbin/pocketais-autoexpand; do
  test -e "$V$f" && log "OK  $f" || { log "ERROR: missing $f in image"; exit 1; }
done
for kt in ed25519 ecdsa rsa; do
  test -s "$V/etc/ssh/ssh_host_${kt}_key" || { log "ERROR: missing ssh host key $kt in final p4"; exit 1; }
done
[ -s "$V/etc/machine-id" ] && { log "ERROR: machine-id non-empty in final p4"; exit 1; }
log "ES size=$ES_SIZE; p4 verify OK"
umount /mnt/imgroot; /sbin/losetup -d "$LOOPV"; rmdir /mnt/imgroot

log "=== [6/8] clean p3 (loop) : rm markers + authorized_keys ==="
mkdir -p /mnt/imgp3
mount -o loop,rw,offset=$P3_OFF,sizelimit=$P3_LEN "$IMG" /mnt/imgp3
rm -f /mnt/imgp3/pocketais-autoexpand.done \
      /mnt/imgp3/pocketais-diag.txt \
      /mnt/imgp3/pocketais-firstboot.log \
      /mnt/imgp3/authorized_keys
sync
if [ -e /mnt/imgp3/pocketais-autoexpand.done ]; then log "ERROR: autoexpand marker still present"; exit 1; fi
if [ -e /mnt/imgp3/authorized_keys ]; then log "ERROR: authorized_keys still present"; exit 1; fi
log "p3 contents:"; ls -la /mnt/imgp3 | head -25
umount /mnt/imgp3; rmdir /mnt/imgp3

log "=== [7/8] clear p3 FAT32 dirty bit (main + backup boot sector, offset 0x41) ==="
printf '\000' | dd of="$IMG" bs=1 seek=$((P3_OFF + 65)) count=1 conv=notrunc status=none
printf '\000' | dd of="$IMG" bs=1 seek=$((P3_OFF + 6*512 + 65)) count=1 conv=notrunc status=none
sync
MAIN41=$(dd if="$IMG" bs=1 skip=$((P3_OFF + 65)) count=1 status=none | od -An -tu1 | tr -d ' ')
BK41=$(dd if="$IMG" bs=1 skip=$((P3_OFF + 6*512 + 65)) count=1 status=none | od -An -tu1 | tr -d ' ')
log "p3 dirty byte main=$MAIN41 backup=$BK41 (expect 0 0)"
{ [ "$MAIN41" = "0" ] && [ "$BK41" = "0" ]; } || { log "ERROR: dirty bit not cleared"; exit 1; }

log "=== [8/8] fix_gpt (p1/p2 Rockchip GUIDs + p3 attr 0x4 + CRCs) ==="
python3 "$FIXGPT" "$IMG"

log "=== final GPT verify ==="
/usr/sbin/sgdisk -v "$IMG" || true
/usr/sbin/sgdisk -p "$IMG"
for n in 1 2 3 4 5; do echo "-- part $n --"; /usr/sbin/sgdisk -i $n "$IMG" | grep -iE 'GUID code|unique GUID|Attribute|name'; done
log "=== ls image ==="; ls -l "$IMG"
log "=== sha256 (may take a few minutes) ==="
sha256sum "$IMG" | tee /roms/pocketAis-dArkOS-20261025-autoexpand-sanitized.img.sha256
log "=== image build complete ==="
