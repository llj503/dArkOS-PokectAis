#!/bin/bash
# Verify the CI-built WSI layer (/opt/vita3k-wsi, from the release tarball) can
# present a real game, not just the locally built one.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
OUT=/home/ark/vita3k-install
RT=/run/user/1000
SOCK=wayland-vita3k
TITLE=PCSE00328

say() { echo "[$(date +%H:%M:%S)] $*"; }

stop_all() {
    sudo kill -9 "$(pidof Vita3K)" 2>/dev/null
    sudo systemctl stop psvita-session.service 2>/dev/null
    sudo systemctl reset-failed psvita-session.service 2>/dev/null
    sudo kill -9 "$(pidof weston)" 2>/dev/null
    sudo kill -9 "$(pidof gptokeyb)" 2>/dev/null
    for i in $(seq 1 40); do systemctl is-active emulationstation >/dev/null 2>&1 && break; sleep 1; done
    say "pre: ES=$(systemctl is-active emulationstation) weston=$(pidof weston || echo none) v3k=$(pidof Vita3K || echo none)"
}

shot() {
    rm -f "$OUT"/wayland-screenshot-*.png
    (cd "$OUT" && sudo -u ark env HOME=/home/ark XDG_RUNTIME_DIR="$RT" \
        WAYLAND_DISPLAY="$SOCK" weston-screenshooter >/dev/null 2>&1)
    sleep 1
    local n
    n=$(ls -t "$OUT"/wayland-screenshot-*.png 2>/dev/null | head -1)
    [ -n "$n" ] && mv "$n" "$OUT/$1" && say "shot $1"
}
scene() {
    timeout -s KILL 8 env XDG_RUNTIME_DIR="$RT" WAYLAND_DISPLAY="$SOCK" weston-debug scene-graph 2>/dev/null \
        | grep -E "role xdg_toplevel|buffer|dmabuf|SHM|surface ID" | head -14
}
cleanup() { say "== cleanup =="; stop_all; }
trap cleanup EXIT

stop_all
say "== layer in use =="
sudo sha256sum /opt/vita3k-wsi/libVkLayer_window_system_integration.so
say "== launching -r $TITLE =="
PSVITA_WESTON_DEBUG=1 /usr/local/bin/psvita-launch.sh "$TITLE"
for i in $(seq 1 60); do pidof Vita3K >/dev/null 2>&1 && break; sleep 1; done
pidof Vita3K >/dev/null 2>&1 || { say VITA3K_NOT_RUNNING; exit 1; }
PID=$(pidof Vita3K)
say "VITA3K_RUNNING pid=$PID"
say "== layer mapped into the process? =="
sudo grep -c "vita3k-wsi" /proc/$PID/maps
sudo grep -o "/opt/vita3k-wsi/[^ ]*" /proc/$PID/maps | sort -u
say "== env =="
sudo tr '\0' '\n' < /proc/$PID/environ | grep -E "VK_ADD_IMPLICIT_LAYER_PATH|LD_PRELOAD"

prev=0
for t in 25 60 120; do
    sleep $(( t - prev )); prev=$t
    say "===== t=${t}s ====="
    scene
    sudo journalctl -u psvita-session.service --since "-${t}s" --no-pager 2>/dev/null \
        | grep -vE "connectSlotsByName|pw.conf" | tail -14
    shot "ciwsi-t${t}.png"
    say "rss=$(awk '/VmRSS/{print $2}' /proc/$PID/status 2>/dev/null)kB"
    pidof Vita3K >/dev/null 2>&1 || { say "VITA3K_EXITED at t=${t}s"; break; }
done
say CI_WSI_TEST_DONE