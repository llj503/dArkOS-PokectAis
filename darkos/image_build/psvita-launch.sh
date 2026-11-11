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
        --setenv=PSVITA_WESTON_DEBUG="${PSVITA_WESTON_DEBUG:-0}" \
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
GPTK_PID=
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
    if [ -n "$GPTK_PID" ]; then
        kill "$GPTK_PID" 2>/dev/null
        kill -9 "$GPTK_PID" 2>/dev/null
    fi
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
    systemctl restart killer_daemon.service >/dev/null 2>&1 || true
    systemctl restart ogage.service >/dev/null 2>&1 || true
    systemctl start emulationstation
}
trap cleanup EXIT

systemctl stop emulationstation
# Let ES drop DRM master before Weston asks for it.
sleep 2
set_governors

export XDG_RUNTIME_DIR="$RTDIR"
# PSVITA_WESTON_DEBUG=1 adds --debug, which is what authorises the
# weston-screenshooter / weston-debug protocols. Off by default: it exposes the
# compositor's debug protocol to every client.
WESTON_EXTRA=()
[ "${PSVITA_WESTON_DEBUG:-0}" = "1" ] && WESTON_EXTRA+=(--debug)
weston --backend=drm-backend.so --shell=kiosk-shell.so --idle-time=0 \
    "${WESTON_EXTRA[@]}" \
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
# CMake names the executable Vita3K (OUTPUT_NAME), so that is the process name.
echo "VAR=Vita3K" > /home/ark/.config/KILLIT

# Weston/libinput refuses gamepads, so the Qt GUI would be keyboard-only.
# gptokeyb (the same tool PortMaster uses) turns the pad into uinput keys.
# It owns Select+Start while it runs, so killer_daemon stands down.
# -sudokill: Vita3K's SDL installs a SIGTERM handler the Qt loop never acts on,
# so a plain killall would leave it running; the exit combo has to SIGKILL.
GPTOKEYB=/opt/inttools/gptokeyb
GPTK=/usr/local/share/vita3k.gptk
GPTK_PID=
if [ -x "$GPTOKEYB" ] && [ -r "$GPTK" ]; then
    chmod 666 /dev/uinput 2>/dev/null || true
    systemctl stop killer_daemon.service >/dev/null 2>&1 || true
    # ogage stays up: it is the volume/brightness/mute hotkey listener, and it
    # only reads evdev (no grab, no uinput), so it coexists with gptokeyb exactly
    # like it does under PortMaster. Stopping it would leave the volume keys
    # dead for the whole session; Vita3K's ALSA output goes through softvol, so
    # ogage's volume.sh applies to it.
    SDL_GAMECONTROLLERCONFIG_FILE=/opt/inttools/gamecontrollerdb.txt \
        "$GPTOKEYB" -1 Vita3K -sudokill -c "$GPTK" >/dev/null 2>&1 &
    GPTK_PID=$!
else
    systemctl restart killer_daemon.service >/dev/null 2>&1 || true
fi

# Use the device's own controller mapping so Vita3K's SDL pad and gptokeyb
# agree on which physical button is A.
RK_MAP=$(grep -m1 '^1900a4dd726b333536322d6a6f797300,' \
    /opt/inttools/gamecontrollerdb.txt 2>/dev/null || true)
[ -n "$RK_MAP" ] && export SDL_GAMECONTROLLERCONFIG="$RK_MAP"

# Rockchip's libMali.so statically links libwayland-client/server and exports all
# of their wl_* symbols. Qt6Gui pulls libEGL -> libMali into the global scope
# before the wayland platform plugin is dlopened, so Qt6WaylandClient binds
# wl_display_connect to Mali's copy instead of the real client. That copy cannot
# connect: Qt aborts with "Failed to create wl_display (No such file or
# directory)" while the socket is plainly there and weston clients work.
# LD_DEBUG=bindings shows the binding going to libEGL.so.1. Preloading the real
# libwayland-client puts it ahead of libMali in the global scope.
WL_CLIENT=
for c in /lib/aarch64-linux-gnu/libwayland-client.so.0 \
         /usr/lib/aarch64-linux-gnu/libwayland-client.so.0; do
    [ -e "$c" ] && WL_CLIENT="$c" && break
done
if [ -n "$WL_CLIENT" ]; then
    export LD_PRELOAD="$WL_CLIENT${LD_PRELOAD:+:$LD_PRELOAD}"
else
    echo "psvita: libwayland-client.so.0 not found, Qt may bind to libMali's copy" >&2
fi

# The blob is the gbm winsys variant: its Vulkan instance extensions are only
# VK_KHR_surface / VK_KHR_display / VK_EXT_headless_surface, so there is no
# VK_KHR_wayland_surface and Vita3K's Vulkan renderer cannot create a surface
# under Weston. vulkan-wsi-layer supplies the missing WSI on top of the blob
# (dma-buf backed swapchain handed over linux-dmabuf). It is an implicit layer,
# so VK_ADD_IMPLICIT_LAYER_PATH is the switch -- VK_ADD_LAYER_PATH only covers
# explicit layers and silently does nothing here. Scoped to this process tree,
# the rest of the system keeps using the blob directly.
WSI_DIR=/opt/vita3k-wsi
if [ -r "$WSI_DIR/VkLayer_window_system_integration.json" ]; then
    export VK_ADD_IMPLICIT_LAYER_PATH="$WSI_DIR${VK_ADD_IMPLICIT_LAYER_PATH:+:$VK_ADD_IMPLICIT_LAYER_PATH}"
else
    echo "psvita: $WSI_DIR missing, Vita3K's Vulkan renderer has no Wayland WSI" >&2
fi

# The Welcome dialog is modal and runs before app.exec() (main_window.cpp:
# welcome.exec()), so it blocks the QTimer::singleShot(0) that auto-boots
# run_app_path -- with the default show-welcome=true a game never starts on its
# own. Prime the two GUI options a console entry wants; Vita3K keeps every other
# key at its default, and rewrites the file itself on exit.
CFG="$DATA/config.yml"
prime_config() {
    local key=$1 val=$2
    if [ ! -f "$CFG" ]; then
        printf -- '---\n' > "$CFG"
        chown ark:ark "$CFG" 2>/dev/null || true
    fi
    if grep -q "^$key:" "$CFG"; then
        grep -q "^$key: $val\$" "$CFG" || sed -i "s|^$key:.*|$key: $val|" "$CFG"
    else
        sed -i "0,/^---\$/s//---\n$key: $val/" "$CFG"
    fi
}
prime_config show-welcome false
prime_config boot-apps-full-screen true

# gptokeyb does not EVIOCGRAB the pad, so Vita3K's SDL and the uinput keys both
# see every button. Make the keyboard bindings agree with vita3k.gptk so the two
# paths press the same Vita button instead of A meaning Cross *and* Start.
# Done once: after this the user can remap in Vita3K's own controls dialog.
if [ ! -e "$DATA/.darkos-controls" ]; then
    prime_config keyboard-button-cross Enter
    prime_config keyboard-button-circle Escape
    prime_config keyboard-button-square Space
    prime_config keyboard-button-triangle Backspace
    prime_config keyboard-button-start Insert
    prime_config keyboard-button-select Delete
    prime_config keyboard-button-l1 PageUp
    prime_config keyboard-button-r1 PageDown
    prime_config keyboard-button-l2 Home
    prime_config keyboard-button-r2 End
    touch "$DATA/.darkos-controls"
    chown ark:ark "$DATA/.darkos-controls" 2>/dev/null || true
fi

ARGS=(-F)
if [ -n "$ROM" ]; then
    if [ -e "$ROM" ]; then
        # An extracted NoNpDrm folder is named after the title. main.cpp only
        # auto-boots a directory install when install_contents() returns exactly
        # 1, and an app+patch folder returns 2, so the first launch installs and
        # then sits in the GUI. Once it is installed, boot it by title instead.
        TITLE=$(basename "$ROM")
        if [ -d "$ROM" ] && [ -d "$DATA/fs/ux0/app/$TITLE" ]; then
            ARGS+=(-r "$TITLE")
        else
            # The "--" is required: Vita3K's CLI11 treats a leading "/" as a
            # Windows-style option, so a bare /roms/... path is swallowed and
            # content-path stays empty (no install, no auto-boot, just the GUI).
            ARGS+=(-- "$ROM")
        fi
    else
        ARGS+=(-r "$ROM")
    fi
fi

runuser -u ark -- env \
    HOME=/home/ark USER=ark LOGNAME=ark \
    XDG_RUNTIME_DIR="$RTDIR" WAYLAND_DISPLAY="$SOCK" \
    "$BUNDLE/vita3k.sh" "${ARGS[@]}"