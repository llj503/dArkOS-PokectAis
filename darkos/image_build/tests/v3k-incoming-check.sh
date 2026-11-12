#!/bin/bash
# Read-only: inspect the leftover install staging for a decrypted (SCE) eboot.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
echo "===INCOMING_APP==="
ls -la /roms/vita3k/incoming/PCSE00328/app/PCSE00328/ 2>/dev/null | head -10
echo "head:"; head -c 16 /roms/vita3k/incoming/PCSE00328/app/PCSE00328/eboot.bin 2>/dev/null | od -An -tx1
sha256sum /roms/vita3k/incoming/PCSE00328/app/PCSE00328/eboot.bin 2>/dev/null
stat -c '%s %y' /roms/vita3k/incoming/PCSE00328/app/PCSE00328/eboot.bin 2>/dev/null
echo "===INCOMING_PATCH==="
ls -la /roms/vita3k/incoming/PCSE00328/patch/PCSE00328/ 2>/dev/null | head -10
echo "head:"; head -c 16 /roms/vita3k/incoming/PCSE00328/patch/PCSE00328/eboot.bin 2>/dev/null | od -An -tx1
sha256sum /roms/vita3k/incoming/PCSE00328/patch/PCSE00328/eboot.bin 2>/dev/null
stat -c '%s %y' /roms/vita3k/incoming/PCSE00328/patch/PCSE00328/eboot.bin 2>/dev/null
echo "===INCOMING_GAME==="
find /roms/vita3k/incoming/game -maxdepth 3 2>/dev/null | head -15
echo "===LOG_AROUND_GOOD_BOOT==="
sed -n '120,165p' /roms/vita3k/vita3k.log 2>/dev/null
echo "===LOG_DECRYPT_MENTIONS==="
grep -niE "decrypt|self is not encrypted|not encrypted|install.*archive|archive.*install|patch" /roms/vita3k/vita3k.log 2>/dev/null | head -20
echo INCOMING_DONE