#!/bin/bash
# Rebuild the PFS-decrypted PCSE00328 install without hammering exFAT.
#
# Root cause: /roms/psvita/*.zip is a PFS-encrypted NoNpDrm dump. Vita3K
# decrypts it during install (interface.cpp -> decrypt_install_nonpdrm);
# eboot.bin in the zip is NOT a SELF (head d3 d0 b7 a9, entropy 8.0).
# The 3 x 1766-file extract/decrypt/copy storm on exFAT hard-locked the
# device, leaving the encrypted eboot in ux0/app -> decrypt_fself() reports
# "Invalid SELF: file is either not a SELF or is still encrypted".
#
# Fix: bind-mount ux0/app + ux0/patch onto btrfs for the install, let Vita3K
# do its own decryption there, then copy the decrypted tree back to exFAT in
# one idle-priority sequential pass. The old encrypted tree is kept as backup.
set -u
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

ZIP="/roms/psvita/Blast Em Bunnies (PCSE00328).zip"
DATA=/roms/vita3k
WORK=/home/ark/v3k-repair
TITLE=PCSE00328
RIF=UP4352-PCSE00328_00-NNBLASTBUNNIESUS.rif
TS=$(date +%Y%m%d-%H%M%S)
LOG=/home/ark/v3k-repair-$TS.log
MOUNTS=()

say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
die() { say "ABORT: $*"; exit 1; }

unbind() {
    local d
    for d in "${MOUNTS[@]}"; do sudo umount "$d" 2>/dev/null || true; done
    MOUNTS=()
}
trap unbind EXIT

# SCE_MAGIC = 0x00454353 -> little endian bytes 53 43 45 00 ("SCE\0")
sce_magic() { [ "$(head -c4 "$1" 2>/dev/null | od -An -tx1 | tr -d ' \n')" = "53434500" ]; }
hex4() { head -c4 "$1" 2>/dev/null | od -An -tx1 | tr -d '\n'; }

[ "$(systemctl is-active psvita-session.service)" = "inactive" ] || die "psvita-session is active, refusing to touch a running game"
[ -r "$ZIP" ] || die "zip missing: $ZIP"
[ -x /opt/vita3k/Vita3K ] || die "Vita3K binary missing"
[ -x /usr/local/bin/psvita-launch.sh ] || die "launcher missing"

if sce_magic "$DATA/fs/ux0/app/$TITLE/eboot.bin"; then
    say "ALREADY_DECRYPTED app eboot; nothing to do"
    exit 0
fi
say "current app eboot head: $(hex4 "$DATA/fs/ux0/app/$TITLE/eboot.bin") (encrypted PFS)"

# 1. btrfs staging area. / is btrfs with 5 GiB free; exFAT cannot symlink.
sudo rm -rf "$WORK"
mkdir -p "$WORK/app" "$WORK/patch" || die "cannot create $WORK"
sudo chown -R ark:ark "$WORK"
for d in app patch; do
    sudo mount --bind "$WORK/$d" "$DATA/fs/ux0/$d" || die "bind mount $d failed"
    MOUNTS+=("$DATA/fs/ux0/$d")
done
say "bind mounts up: ${MOUNTS[*]}"

# 2. patch has no work.bin; Vita3K needs the app .rif to derive its klicensee.
LIC="$DATA/fs/ux0/license/$TITLE"
if [ ! -f "$LIC/$RIF" ]; then
    if [ -f "$LIC/$RIF.bak-20261112" ]; then
        cp -a "$LIC/$RIF.bak-20261112" "$LIC/$RIF" && say "restored $RIF from backup"
    else
        say "WARN: no .rif; app install should recreate it from work.bin"
    fi
fi

# 3. Run Vita3K's own installer through the normal ES launcher. Its CLI path
# installs app (gd) then patch (gp), decrypting both, and auto-boots at the end.
SINCE=$(date '+%Y-%m-%d %H:%M:%S')
sudo systemctl reset-failed psvita-session.service 2>/dev/null || true
PSVITA_WESTON_DEBUG=0 /usr/local/bin/psvita-launch.sh "$ZIP" >/dev/null 2>&1 &
say "install started, waiting for 'Content installed, will auto-boot'"

ok=0
for _ in $(seq 1 100); do
    if sudo journalctl -u psvita-session.service --since "$SINCE" --no-pager 2>/dev/null \
        | grep -q "Content installed, will auto-boot"; then
        ok=1
        break
    fi
    sleep 3
done
sudo journalctl -u psvita-session.service --since "$SINCE" --no-pager >"$LOG.install" 2>&1 || true
sudo systemctl stop psvita-session.service 2>/dev/null || true
sleep 3
[ "$ok" = 1 ] || die "install did not finish in 300s; see $LOG.install"
say "install done; install journal: $LOG.install"

# 4. Verify decryption happened before touching the real install.
APP="$WORK/app/$TITLE/eboot.bin"
PATCH="$WORK/patch/$TITLE/eboot.bin"
sce_magic "$APP" || die "app eboot still not a SELF: $(hex4 "$APP")"
say "app decrypted eboot: head=$(hex4 "$APP") sha256=$(sha256sum "$APP" | cut -d' ' -f1)"
if [ -f "$PATCH" ] && sce_magic "$PATCH"; then
    say "patch decrypted eboot: head=$(hex4 "$PATCH") sha256=$(sha256sum "$PATCH" | cut -d' ' -f1)"
    HAVE_PATCH=1
else
    say "WARN: patch eboot missing or still encrypted ($(hex4 "$PATCH")) -- app only"
    HAVE_PATCH=0
fi

# 5. Unmount first, then deploy. Nothing in Vita3K is running now.
unbind
trap - EXIT
say "bind mounts released"

BK="$DATA/backup-$TS"
mkdir -p "$BK" || die "cannot create backup dir"
for d in app patch; do
    [ "$d" = patch ] && [ "$HAVE_PATCH" = 0 ] && continue
    SRC="$WORK/$d/$TITLE"
    DST="$DATA/fs/ux0/$d"
    [ -d "$SRC" ] || die "missing staged $SRC"
    if [ -d "$DST/$TITLE" ]; then
        mv "$DST/$TITLE" "$BK/$d-$TITLE" || die "cannot back up $DST/$TITLE"
    fi
    if ! ionice -c3 cp -a "$SRC" "$DST/"; then
        rm -rf "$DST/$TITLE"
        [ -d "$BK/$d-$TITLE" ] && mv "$BK/$d-$TITLE" "$DST/$TITLE"
        die "copy $d failed, rolled back"
    fi
    say "$d deployed: files=$(find "$DST/$TITLE" -type f | wc -l) eboot=$(hex4 "$DST/$TITLE/eboot.bin")"
done
sync

# 6. Byte-level verification + ES back up.
sce_magic "$DATA/fs/ux0/app/$TITLE/eboot.bin" || die "final app eboot verification failed"
say "final app sha256=$(sha256sum "$DATA/fs/ux0/app/$TITLE/eboot.bin" | cut -d' ' -f1)"
say "backup of encrypted tree: $BK"
systemctl is-active emulationstation >/dev/null 2>&1 || systemctl start emulationstation
say "ES=$(systemctl is-active emulationstation) session=$(systemctl is-active psvita-session.service)"
say "REPAIR_DONE"
