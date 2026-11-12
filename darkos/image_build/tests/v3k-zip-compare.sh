#!/bin/bash
# Read-only: compare the device zip's eboot vs the installed app eboot, and look
# for any decrypted-SELF cache Vita3K may have written. No writes.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ZIP="/roms/psvita/Blast Em Bunnies (PCSE00328).zip"
APP=/roms/vita3k/fs/ux0/app/PCSE00328
echo "===ZIP_META==="
ls -la "$ZIP"; stat -c 'size=%s' "$ZIP"; sha256sum "$ZIP" 2>/dev/null
echo "===ZIP_EBOOT==="
unzip -p "$ZIP" "*/app/PCSE00328/eboot.bin" 2>/dev/null | tee /tmp/zb.$$ | head -c 16 | od -An -tx1
echo "zip_eboot_sha256:"; sha256sum /tmp/zb.$$ 2>/dev/null; rm -f /tmp/zb.$$
echo "===APP_EBOOT==="
head -c 16 "$APP/eboot.bin" | od -An -tx1; sha256sum "$APP/eboot.bin"
echo "===CACHE_DIRS==="
ls -la /roms/vita3k/ 2>/dev/null
echo "--- any decrypted self/cache ---"
find /roms/vita3k -maxdepth 3 -iname "*cache*" -o -iname "*self*" 2>/dev/null | head -20
ls -la /roms/vita3k/fs/ux0/app/PCSE00328/sce_sys/ 2>/dev/null
echo "===INSTALL_LOG_HINTS==="
sudo journalctl -u psvita-session.service --since "-3days" --no-pager 2>/dev/null \
    | grep -iE "decrypt_selfs|decrypt self|self_path|Main executable|loaded|Installing archive" | tail -12
echo DEVICE_ZIPCHECK_DONE