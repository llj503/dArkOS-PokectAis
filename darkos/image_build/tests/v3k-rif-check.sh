#!/bin/bash
# Short boot check: remove stale .rif cache, boot by title, watch for decrypt
# errors, then restore ES. Bounded so it cannot hang the session.
set -u
RIF=/roms/vita3k/fs/ux0/license/PCSE00328/UP4352-PCSE00328_00-NNBLASTBUNNIESUS.rif
if [ -f "$RIF" ]; then cp -a "$RIF" "$RIF.bak-20261112"; rm -f "$RIF"; echo RIF_REMOVED; fi
sudo systemctl reset-failed psvita-session.service 2>/dev/null
PSVITA_WESTON_DEBUG=1 /usr/local/bin/psvita-launch.sh "/roms/psvita/Blast Em Bunnies (PCSE00328).zip" &
LP=$!
sleep 25
echo "===DECRYPT-CHECK==="
sudo journalctl -u psvita-session.service --since "-40s" --no-pager 2>/dev/null | grep -E "Invalid SELF|Failed to decrypt|decrypt_fself|load_app_impl|core_lock|Controllers" | head -12
echo "===STOP==="
sudo kill -9 "$(pidof Vita3K)" 2>/dev/null
sudo systemctl stop psvita-session.service 2>/dev/null
sudo kill -9 "$(pidof weston)" 2>/dev/null
sleep 2
sudo systemctl start emulationstation
echo CHECK_DONE