#!/bin/bash
# Read-only hunt for the good (decrypted) eboot that once ran. No writes.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
echo "===CACHE_TREE==="
find /roms/vita3k/cache -maxdepth 4 2>/dev/null | head -40
echo "===VITA3K_LOG_SIZE==="
wc -l /roms/vita3k/vita3k.log 2>/dev/null
echo "===LOG_MAIN_EXECUTABLE==="
grep -n "Main executable" /roms/vita3k/vita3k.log 2>/dev/null | tail -10
echo "===LOG_INVALID_SELF==="
grep -c "Invalid SELF" /roms/vita3k/vita3k.log 2>/dev/null
echo "===LOG_FIRST_BOOT_MARKERS==="
grep -nE "Title: |Serial: |load_app_impl|Installing archive|installed successfully|decrypt_selfs" /roms/vita3k/vita3k.log 2>/dev/null | head -20
echo "===ANY_OTHER_EBOOT_ON_DEVICE==="
find /roms /home/ark -xdev -type f -name "eboot.bin" 2>/dev/null | head -20
echo "===APP_BACKUPS==="
find /roms/vita3k -maxdepth 4 -iname "*PCSE00328*" 2>/dev/null | head -20
ls -la /roms/vita3k/fs/ux0/app/ 2>/dev/null
echo "===INCOMING==="
find /roms/vita3k/incoming -maxdepth 2 2>/dev/null | head -20
echo "===LOG_HEAD_FIRSTLINES==="
head -5 /roms/vita3k/vita3k.log 2>/dev/null
echo SEARCH_DONE