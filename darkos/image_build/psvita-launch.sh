#!/bin/bash
# PS Vita (Vita3K-Plus) entry for dArkOS EmulationStation.
#
# dArkOS has no X/Wayland session and ES owns DRM master, so the Qt frontend
# gets a compositor of its own:
#   leave the ES cgroup -> stop ES -> Weston (DRM, root) -> Vita3K (ark)
#   -> stop Weston -> start ES
#
#   psvita-launch.sh [rom]
#     rom  .vpk/.zip/folder to install and run, an installed TITLEID, or empty
#          for the Vita3K GUI (firmware install, settings, app list).
#
# Installed as /usr/local/bin/psvita-launch.sh; the bundle lives in /opt/vita3k
# and all Vita data (firmware, installed games, config, cache) in /roms/vita3k.
set -u

ROM="${1:-}"
BUNDLE=/opt/vita3k
DATA=/roms/vita3k
RTDIR=/run/user/1000
SOCK=wayland-vita3k

# systemd kills every process in the ES cgroup when the service stops, this
# script included. Re-exec as a transient root service so the session outlives
# ES. Weston needs root: libseat's builtin backend has to open /dev/tty0, and
# there is no logind session on seat0 to borrow.
if [ "${PSVITA_SESSION:-}" != "1" ]; then
    sudo systemctl reset-failed psvita-session.service 2>/dev/null || true
    exec sudo systemd-run --unit=psvita-session --collect \
        --setenv=PSVITA_SESSION=1 \
        --working-directory=/home/ark \
        /usr/local/bin/psvita-launch.sh "$ROM"
fi

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

if [ ! -x "$BUNDLE/vita3k.sh" ]; then
    echo "psvita: $BUNDLE/vita3k.sh is missing" >&2
    systemctl start emulationstation
    exit 1
fi

mkdir -p "$DATA"
chown ark:ark "$DATA" 2>/dev/null || true
# Portable mode keeps config.yml, firmware and installed games out of the small
# rootfs: Vita3K uses <bundle>/portable for everything when it exists.
[ -e "$BUNDLE/portable" ] || ln -s "$DATA" "$BUNDLE/portable"

WESTON_PID=
GOV_CPU=
GOV_GPU=
GOV_DMC=
GPU_DEVFREQ=

set_governors() {
    local cpu=/sys/devices/system/cpu/cpufreq/policy0/scaling_governor
    local dmc=/sys/devices/platform/dmc/devfreq/dmc/governor
    local d
    for d in /sys/class/devfreq/*.gpu; do
        [ -e "$d" ] && GPU_DEVFREQ="$d/governor" && break
    done
    [ -r "$cpu" ] && GOV_CPU=$(cat "$cpu")
    [ -n "$GPU_DEVFREQ" ] && [ -r "$GPU_DEVFREQ" ] && GOV_GPU=$(cat "$GPU_DEVFREQ")
    [ -r "$dmc" ] && GOV_DMC=$(cat "$dmc")
    # Only write a governor the kernel actually offers.
    local target
    for target in "$cpu:performance" "$GPU_DEVFREQ:performance" "$dmc:performance"; do
        local path=${target%%:*} want=${target##*:}
        [ -n "$path" ] && [ -w "$path" ] || continue
        grep -qw "$want" "${path%governor}available_governors" 2>/dev/null || continue
        echo "$want" > "$path" 2>/dev/null || true
    done
}

restore_governors() {
    [ -n "$GOV_CPU" ] && echo "$GOV_CPU" > /sys/devices/system/cpu/cpufreq/policy0/scaling_governor 2>/dev/null
    [ -n "$GOV_GPU" ] && [ -n "$GPU_DEVFREQ" ] && echo "$GOV_GPU" > "$GPU_DEVFREQ" 2>/dev/null
    [ -n "$GOV_DMC" ] && echo "$GOV_DMC" > /sys/devices/platform/dmc/devfreq/dmc/governor 2>/dev/null
    return 0
}

cleanup() {
    if [ -n "$WESTON_PID" ]; then
        kill "$WESTON_PID" 2>/dev/null
        for _ in $(seq 1 20); do
            kill -0 "$WESTON_PID" 2>/dev/null || break
            sleep 0.2
        done
        kill -9 "$WESTON_PID" 2>/dev/null
    fi
    rm -f "$RTDIR/$SOCK" "$RTDIR/$SOCK.lock"
    restore_governors
    systemctl start emulationstation
}
trap cleanup EXIT

systemctl stop emulationstation
# Let ES drop DRM master before Weston asks for it.
sleep 2
set_governors

export XDG_RUNTIME_DIR="$RTDIR"
weston --backend=drm-backend.so --shell=kiosk-shell.so --idle-time=0 \
    --socket="$SOCK" --log="$DATA/weston.log" >"$DATA/weston.out" 2>&1 &
WESTON_PID=$!
for _ in $(seq 1 60); do
    [ -S "$RTDIR/$SOCK" ] && break
    kill -0 "$WESTON_PID" 2>/dev/null || break
    sleep 0.25
done
if [ ! -S "$RTDIR/$SOCK" ]; then
    echo "psvita: Weston did not come up, see $DATA/weston.log" >&2
    exit 1
fi
# Weston runs as root, Vita3K as ark.
chmod 0666 "$RTDIR/$SOCK"

# Select+Start kills the emulator; the EXIT trap then brings ES back.
echo "VAR=vita3k" > /home/ark/.config/KILLIT
systemctl restart killer_daemon.service >/dev/null 2>&1 || true

ARGS=(-F)
if [ -n "$ROM" ]; then
    if [ -e "$ROM" ]; then
        ARGS+=("$ROM")
    else
        ARGS+=(-r "$ROM")
    fi
fi

runuser -u ark -- env \
    HOME=/home/ark USER=ark LOGNAME=ark \
    XDG_RUNTIME_DIR="$RTDIR" WAYLAND_DISPLAY="$SOCK" \
    "$BUNDLE/vita3k.sh" "${ARGS[@]}"