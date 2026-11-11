#!/usr/bin/env bash
# Bundle a Vita3K-Plus Qt build into a relocatable tarball for dArkOS.
#
#   package_vita3k.sh <build-dir> <qtdir> <out-name> [source-dir]
#
# The tarball unpacks into /opt/vita3k and contains the emulator, its static
# assets (data/, shaders-builtin/, translations/, icons/), the Qt 6.11 runtime
# and the Qt plugins. Everything is patched to $ORIGIN-relative RPATHs so the
# bundle does not depend on the build host's library layout.
set -euo pipefail

BUILD=${1:?build dir}
QTDIR=${2:?qt dir}
NAME=${3:?output name}
SRC=${4:-}

PKG=$PWD/pkg
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

BIN=$(find "$BUILD/bin" -maxdepth 1 -type f -iname vita3k 2>/dev/null | head -1)
[ -n "$BIN" ] || BIN=$(find "$BUILD" -type f -iname vita3k | head -1)
[ -n "$BIN" ] || { echo "vita3k binary not found under $BUILD" >&2; exit 1; }
BINDIR=$(dirname "$BIN")
# CMake sets OUTPUT_NAME Vita3K, so the executable is bin/Vita3K on Linux.
EXE=$(basename "$BIN")
echo "== binary: $BIN"
file "$BIN"

rm -rf "$PKG"
mkdir -p "$PKG/lib" "$PKG/qtplugins"

# CMake's POST_BUILD already put data/, shaders-builtin/, translations/, icons/
# and any shared SDL3 next to the executable.
cp -a "$BINDIR"/. "$PKG/"
cp -a "$QTDIR"/plugins/. "$PKG/qtplugins/"

# --- prune the plugin set ----------------------------------------------------
# The full Qt install carries designer/assistant/QML tooling and the SQL,
# printing and GTK platform-theme plugins. Vita3K uses none of them, and each
# would drag in another Qt module (Quick, Help, Sql, PrintSupport, QmlCompiler)
# plus cups/mysql/postgresql/odbc on the device. Drop them before the closure
# walk so they cannot pull anything in.
for d in designer help qmllint qmlls qmltooling sqldrivers printsupport \
         platformthemes xcbglintegrations egldeviceintegrations; do
    rm -rf "$PKG/qtplugins/$d"
done
# Only the Wayland platform is used; keep offscreen/minimal for headless runs.
find "$PKG/qtplugins/platforms" -maxdepth 1 -type f -name '*.so' \
    ! -name 'libqwayland.so' ! -name 'libqoffscreen.so' ! -name 'libqminimal.so' \
    -delete
# Qt's GStreamer media backend needs libgstplay/libgstphotography/libgstgl,
# which neither the builder nor dArkOS installs. The FFmpeg backend ships its
# own libraries inside the Qt install, so keep that one.
rm -f "$PKG/qtplugins/multimedia/libgstreamermediaplugin.so"

# --- collect the shared-library closure -------------------------------------
# Only libraries that are not guaranteed to exist on dArkOS (Debian 13) are
# bundled: everything from the Qt install, plus ICU / pcre2-16 /
# double-conversion (Qt private deps), the C++ runtime and the GLVND desktop-GL
# trio (dArkOS ships the Mali blob, which has no libGL/libGLX/libGLdispatch).
mkdir -p "$TMP/seen"
: > "$TMP/work"
: > "$TMP/external"
printf '%s\n' "$PKG/$EXE" >> "$TMP/work"
find "$PKG" -maxdepth 1 -type f -name '*.so*' >> "$TMP/work"
find "$PKG/qtplugins" -type f -name '*.so' >> "$TMP/work"

# The copied plugins carry $ORIGIN-relative RPATHs that now point into the
# still-incomplete bundle, so without this LD_LIBRARY_PATH ldd reports every
# not-yet-copied Qt module as "not found" and it silently drops out of the
# closure. That is how libQt6WaylandClient went missing: at runtime the plugin
# then bound to the device's own Qt 6.8 and died on a Qt_6_PRIVATE_API symbol.
export LD_LIBRARY_PATH="$QTDIR/lib:$PKG/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

deps_of() {
    ldd "$1" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i ~ /^\//) print $i}'
}

# A dependency ldd cannot resolve would silently disappear from the closure.
MISSING=$TMP/missing
: > "$MISSING"
check_missing() {
    ldd "$1" 2>/dev/null | grep "not found" | sed "s|^|$(basename "$1"): |" >> "$MISSING" || true
}

while [ -s "$TMP/work" ]; do
    f=$(head -1 "$TMP/work")
    tail -n +2 "$TMP/work" > "$TMP/work.next"
    mv "$TMP/work.next" "$TMP/work"
    [ -f "$f" ] || continue
    check_missing "$f"
    while read -r dep; do
        [ -e "$dep" ] || continue
        base=$(basename "$dep")
        [ -e "$TMP/seen/$base" ] && continue
        : > "$TMP/seen/$base"
        bundle=0
        case "$dep" in
            "$QTDIR"/*) bundle=1 ;;
            */libicu*|*/libpcre2-16*|*/libdouble-conversion*) bundle=1 ;;
            */libstdc++.so*|*/libgcc_s.so*) bundle=1 ;;
            */libGL.so*|*/libGLX.so*|*/libGLdispatch.so*) bundle=1 ;;
        esac
        if [ "$bundle" = 1 ]; then
            if [ ! -e "$PKG/lib/$base" ]; then
                cp -L "$dep" "$PKG/lib/$base"
                echo "  bundled $base"
            fi
            printf '%s\n' "$PKG/lib/$base" >> "$TMP/work"
        else
            printf '%s\t%s\n' "$base" "$dep" >> "$TMP/external"
        fi
    done < <(deps_of "$f")
done

echo "== system libraries left to the device =="
sort -u "$TMP/external" | tee "$TMP/external.sorted"
if [ -s "$MISSING" ]; then
    echo "::error::unresolved dependencies, the bundle would be incomplete:"
    sort -u "$MISSING"
    exit 1
fi
# The Wayland client module is the one the platform plugin binds to; if it is
# absent the plugin falls back to the device's own Qt and aborts on a private
# API symbol. Fail loudly rather than shipping that.
[ -e "$PKG/lib/libQt6WaylandClient.so.6" ] || {
    echo "::error::libQt6WaylandClient.so.6 was not bundled" >&2; exit 1; }

# --- RPATHs ------------------------------------------------------------------
# patchelf 0.18 segfaults on some of the Qt FFmpeg stub libraries. The launcher
# puts lib/ on LD_LIBRARY_PATH, which is searched before DT_RUNPATH, so a file
# whose RPATH could not be rewritten still resolves correctly through it. Warn
# and carry on instead of losing the whole build, then verify the closure below.
RPATH_FAILED=$TMP/rpath-failed
: > "$RPATH_FAILED"
set_rpath() {
    local want=$1 f=$2
    if ! patchelf --set-rpath "$want" "$f" 2>/dev/null; then
        echo "  WARNING: patchelf failed on $(basename "$f"), relying on LD_LIBRARY_PATH"
        printf '%s\n' "$(basename "$f")" >> "$RPATH_FAILED"
    fi
}

set_rpath '$ORIGIN/lib' "$PKG/$EXE"
for f in "$PKG"/lib/*.so*; do
    [ -f "$f" ] || continue
    set_rpath '$ORIGIN' "$f"
done
for f in "$PKG"/*.so*; do
    [ -f "$f" ] || continue
    set_rpath '$ORIGIN/lib' "$f"
done
while read -r f; do
    rel=$(realpath --relative-to="$(dirname "$f")" "$PKG/lib")
    set_rpath "\$ORIGIN/$rel" "$f"
done < <(find "$PKG/qtplugins" -type f -name '*.so')

strip --strip-unneeded "$PKG/$EXE" 2>/dev/null || true
find "$PKG/lib" "$PKG/qtplugins" -type f -name '*.so*' -exec strip --strip-unneeded {} + 2>/dev/null || true

# --- final dependency check --------------------------------------------------
# Same environment the launcher sets up. Anything unresolved here would make
# the platform plugin fall back to the device's own Qt, so refuse to ship it.
echo "== final ldd check (launcher environment) =="
: > "$TMP/final-missing"
# Bundle only: with $QTDIR/lib on the path a missing module would silently
# resolve against the builder's Qt install instead of the shipped one.
for f in "$PKG/$EXE" "$PKG"/lib/*.so* "$PKG"/qtplugins/*/*.so; do
    [ -f "$f" ] || continue
    LD_LIBRARY_PATH="$PKG/lib:$PKG" ldd "$f" 2>/dev/null \
        | grep "not found" | sed "s|^|$(basename "$f"): |" >> "$TMP/final-missing" || true
done
if [ -s "$TMP/final-missing" ]; then
    echo "::error::the bundle does not resolve its own dependencies:"
    sort -u "$TMP/final-missing"
    exit 1
fi
echo "  all dependencies resolve"

# --- launcher ----------------------------------------------------------------
cat > "$PKG/vita3k.sh" <<'EOF'
#!/bin/sh
# Vita3K-Plus launcher for dArkOS. Expects a Wayland compositor (Weston on DRM)
# to be running already; vita3k-launch.sh takes care of that from ES.
HERE=$(cd "$(dirname "$0")" && pwd)

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland}"
export QT_PLUGIN_PATH="$HERE/qtplugins"
export QT_QPA_PLATFORM_PLUGIN_PATH="$HERE/qtplugins/platforms"
export LD_LIBRARY_PATH="$HERE/lib:$HERE${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# Portable mode keeps config.yml, firmware and installed games inside the
# bundle. On dArkOS /opt/vita3k/portable is a symlink to /roms/vita3k so the
# small rootfs is not filled up by Vita content.
if [ ! -e "$HERE/portable" ]; then
    mkdir -p "$HERE/portable" 2>/dev/null || true
fi

# rk3562-joystick (same mapping the PS2 launcher uses).
export SDL_GAMECONTROLLERCONFIG="${SDL_GAMECONTROLLERCONFIG:-1900a4dd726b333536322d6a6f797300,rk3562-joystick,a:b0,b:b1,x:b3,y:b2,back:b8,start:b9,guide:b10,misc1:b17,leftstick:b11,rightstick:b12,dpup:b13,dpdown:b14,dpleft:b15,dpright:b16,leftshoulder:b4,rightshoulder:b5,lefttrigger:a2,righttrigger:a5,leftx:a0,lefty:a1,rightx:a3,righty:a4,platform:Linux,}"
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-alsa}"
export AUDIODEV="${AUDIODEV:-default}"

# Rockchip's libMali.so statically links libwayland-client/server and exports
# their wl_* symbols. Qt6Gui loads libEGL -> libMali into the global scope before
# the wayland platform plugin is dlopened, so Qt6WaylandClient would bind
# wl_display_connect to Mali's copy, which cannot connect: Qt aborts with
# "Failed to create wl_display (No such file or directory)" even though the
# socket exists. Preloading the real client puts it ahead of libMali.
# psvita-launch.sh does the same; skip it if the launcher already did.
case "${LD_PRELOAD:-}" in
    *libwayland-client*) ;;
    *)
        for c in /lib/aarch64-linux-gnu/libwayland-client.so.0 \
                 /usr/lib/aarch64-linux-gnu/libwayland-client.so.0; do
            if [ -e "$c" ]; then
                export LD_PRELOAD="$c${LD_PRELOAD:+:$LD_PRELOAD}"
                break
            fi
        done
        ;;
esac

exec "$HERE/@EXE@" "$@"
EOF
sed -i "s|@EXE@|$EXE|g" "$PKG/vita3k.sh"
chmod +x "$PKG/vita3k.sh"

# --- build provenance --------------------------------------------------------
{
    echo "name: $NAME"
    echo "built: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "qt: $("$QTDIR/bin/qmake" -query QT_VERSION 2>/dev/null || echo 6.11.0)"
    echo "flags: -march=armv8-a -moutline-atomics (Cortex-A53 / ARMv8.0, no LSE)"
    if [ -n "$SRC" ] && [ -d "$SRC/.git" ]; then
        echo "source: $(git -C "$SRC" remote get-url origin 2>/dev/null || echo nckstwrt/Vita3K-Plus)"
        echo "commit: $(git -C "$SRC" rev-parse HEAD)"
        echo "submodules:"
        git -C "$SRC" submodule status --recursive 2>/dev/null | sed 's/^/  /'
    fi
    echo "patches: darkos/image_build/patch_vita3k.py (fork_build.h + Atrac9DecodeBounded shim)"
    if [ -s "$RPATH_FAILED" ]; then
        echo "rpath not rewritten (resolved via LD_LIBRARY_PATH):"
        sed 's/^/  /' "$RPATH_FAILED"
    fi
    echo "external system libraries:"
    sed 's/^/  /' "$TMP/external.sorted"
} > "$PKG/BUILD-INFO.txt"

echo "== bundle size =="
du -sh "$PKG"
du -sh "$PKG/lib" "$PKG/qtplugins"
echo "== wayland platform plugin =="
ls -l "$PKG/qtplugins/platforms/" | sed 's/^/  /'

tar --zstd -cf "$NAME.tar.zst" -C "$PKG" .
sha256sum "$NAME.tar.zst" > "$NAME.tar.zst.sha256"
ls -lh "$NAME.tar.zst"
cat "$NAME.tar.zst.sha256"