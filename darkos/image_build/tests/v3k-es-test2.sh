#!/bin/bash
# ES route, second pass: with the patched binary (emuenv.cfg.run_app_path) the
# archive install must auto-boot instead of parking in the GUI.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
OUT=/home/ark/vita3k-install
RT=/run/vita3k
SOCK=wayland-vita3k
ZIP="/roms/psvita/Blast Em Bunnies (PCSE00328).zip"

say() { echo "[$(date +%H:%M:%S)] $*"; }
stop_all() {
    sudo kill -9 "$(pidof Vita3K)" 2>/dev/null
    sudo systemctl stop psvita-session.service 2>/dev/null
    sudo systemctl reset-failed psvita-session.service 2>/dev/null
    sudo kill -9 "$(pidof weston)" 2>/dev/null
    sudo kill -9 "$(pidof gptokeyb)" 2>/dev/null
    sleep 3
    systemctl start emulationstation 2>/dev/null
    for i in $(seq 1 30); do systemctl is-active emulationstation >/dev/null 2>&1 && break; sleep 1; done
    say "pre: ES=$(systemctl is-active emulationstation) weston=$(pidof weston || echo none)"
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
cleanup() { say "== cleanup =="; stop_all; }
trap cleanup EXIT

stop_all
[ -e "$ZIP" ] || { say "ZIP_MISSING $ZIP"; exit 1; }
say "bundle: $(grep -m1 '^name:' /opt/vita3k/BUILD-INFO.txt)"
say "== launching the ES rom path =="
PSVITA_WESTON_DEBUG=1 /usr/local/bin/psvita-launch.sh "$ZIP"
for i in $(seq 1 90); do pidof Vita3K >/dev/null 2>&1 && break; sleep 1; done
pidof Vita3K >/dev/null 2>&1 || { say VITA3K_NOT_RUNNING; exit 1; }
say "VITA3K pid=$(pidof Vita3K)"

prev=0
for t in 60 120 200; do
    sleep $(( t - prev )); prev=$t
    say "===== t=${t}s ====="
    timeout -s KILL 8 env XDG_RUNTIME_DIR="$RT" WAYLAND_DISPLAY="$SOCK" weston-debug scene-graph 2>/dev/null \
        | grep -E "role xdg_toplevel|dmabuf|SHM" | head -8
    sudo journalctl -u psvita-session.service --since "-${t}s" --no-pager 2>/dev/null \
        | grep -E "install|auto-boot|boot_game|Booting|load_exec|ELF|Framerate|MEMSNAP" | tail -10
    shot "es2-t${t}.png"
    say "alsa: $(grep -h '^state:' /proc/asound/card*/pcm*p/sub*/status 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
    say "ogage=$(pidof ogage || echo DEAD) killer=$(pidof killer_daemon || echo stopped) master=$(amixer sget Master 2>/dev/null | sed -n 's/.*Front Left: Playback \([0-9]*\) \[\([0-9]*%\)\].*/\2/p')"
    pidof Vita3K >/dev/null 2>&1 || { say "VITA3K_EXITED at t=${t}s"; break; }
done
say "== install/auto-boot timeline =="
sudo journalctl -u psvita-session.service --since "-6min" --no-pager 2>/dev/null \
    | grep -E "Installing archive|installed successfully|will auto-boot|Booting|boot_game" | head -12
say ES2_TEST_DONE