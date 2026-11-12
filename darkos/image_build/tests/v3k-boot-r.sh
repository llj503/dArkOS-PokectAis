#!/bin/bash
# Boot the already-installed title directly (-r) so we can see whether the WSI
# layer lets Vita3K's Vulkan renderer present under Weston.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
OUT=/home/ark/vita3k-install
RT=/run/vita3k
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
cleanup() {
    say "== cleanup =="
    stop_all
}
trap cleanup EXIT

stop_all
say "== launching -r $TITLE =="
PSVITA_WESTON_DEBUG=1 /usr/local/bin/psvita-launch.sh "$TITLE"
for i in $(seq 1 60); do pidof Vita3K >/dev/null 2>&1 && break; sleep 1; done
pidof Vita3K >/dev/null 2>&1 || { say VITA3K_NOT_RUNNING; exit 1; }
say "VITA3K_RUNNING pid=$(pidof Vita3K)"

prev=0
for t in 20 45 90 150 240; do
    sleep $(( t - prev )); prev=$t
    say "===== t=${t}s ====="
    scene
    sudo journalctl -u psvita-session.service --since "-${t}s" --no-pager 2>/dev/null \
        | grep -vE "connectSlotsByName|pw.conf" | tail -20
    shot "boot-t${t}.png"
    pidof Vita3K >/dev/null 2>&1 || { say "VITA3K_EXITED at t=${t}s"; break; }
done
say BOOT_TEST_DONE