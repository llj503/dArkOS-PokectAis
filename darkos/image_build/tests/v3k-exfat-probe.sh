#!/bin/bash
# Tiny exFAT health probe: 200 small files + sync, timed. Safe, self-cleaning.
T=/roms/.exfat-probe
rm -rf "$T"; mkdir -p "$T"
start=$(date +%s)
for i in $(seq 1 200); do echo data > "$T/f$i"; done
sync
end=$(date +%s)
echo "files=$(ls "$T" | wc -l) elapsed=$((end-start))s"
rm -rf "$T"
echo PROBE_DONE