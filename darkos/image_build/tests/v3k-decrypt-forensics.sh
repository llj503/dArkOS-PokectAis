#!/bin/bash
# Read-only forensics on the decrypt failure. No writes, no launch.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
APP=/roms/vita3k/fs/ux0/app/PCSE00328
echo "===EBOOT_HEAD (first 64 bytes)==="
od -A x -t x1z -v "$APP/eboot.bin" 2>/dev/null | head -4
echo "===EBOOT_SIZE==="
stat -c '%s %n' "$APP/eboot.bin" 2>/dev/null
echo "===PKG_DIR==="
ls -la "$APP/sce_sys/package/" 2>/dev/null
echo "===WORK_BIN_HEAD==="
od -A x -t x1z -v "$APP/sce_sys/package/work.bin" 2>/dev/null | head -4
echo "===KEYSTONE_HEAD==="
od -A x -t x1z -v "$APP/sce_sys/package/keystone" 2>/dev/null | head -2
echo "===PARAM_SFO==="
ls -la "$APP/sce_sys/param.sfo" 2>/dev/null
echo "===APP_TOP==="
ls -la "$APP/" 2>/dev/null | head -20
echo "===VITA3K_LOG_TAIL (decrypt sequence)==="
sudo journalctl -u psvita-session.service --since "-8min" --no-pager 2>/dev/null \
    | grep -iE "decrypt|self|license|rif|work.bin|keystone|klicensee|npdrm|fail|error|invalid" | tail -30
echo "===FW_CHECK==="
ls /roms/vita3k/fs/vs0/sys/external/ 2>/dev/null | wc -l
ls -la /roms/vita3k/fs/os0/ 2>/dev/null | head -5
echo FORENSICS_DONE