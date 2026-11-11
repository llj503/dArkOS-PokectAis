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

BIN=$(find "$BUILD" -type f -name vita3k | head -1)
[ -n "$BIN" ] || { echo "vita3k binary not found under $BUILD" >&2; exit 1; }
BINDIR=$(dirname "$BIN")
echo "== binary: $BIN"
file "$BIN"

rm -rf "$PKG"
mkdir -p "$PKG/lib" "$PKG/qtplugins"

# CMake's POST_BUILD already put data/, shaders-builtin/, translations/, icons/
# and any shared SDL3 next to the executable.
cp -a "$BINDIR"/. "$PKG/"
cp -a "$QTDIR"/plugins/. "$PKG/qtplugins/"

# --- collect the shared-library closure -------------------------------------
# Only libraries that are not guaranteed to exist on dArkOS (Debian 13) are
# bundled: everything from the Qt install, plus ICU / pcre2-16 /
# double-conversion (Qt private deps) and the C++ runtime.
mkdir -p "$TMP/seen"
: > "$TMP/work"
: > "$TMP/external"
printf '%s\n' "$PKG/vita3k" >> "$TMP/work"
find "$PKG" -maxdepth 1 -type f -name '*.so*' >> "$TMP/work"
find "$PKG/qtplugins" -type f -name '*.so' >> "$TMP/work"

deps_of() {
    ldd "$1" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i ~ /^\//) print $i}'
}

while [ -s "$TMP/work" ]; do
    f=$(head -1 "$TMP/work")
    tail -n +2 "$TMP/work" > "$TMP/work.next"
    mv "$TMP/work.next" "$TMP/work"
    [ -f "$f" ] || continue
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

# --- RPATHs ------------------------------------------------------------------
patchelf --set-rpath '$ORIGIN/lib' "$PKG/vita3k"
for f in "$PKG"/lib/*.so*; do
    [ -f "$f" ] || continue
    patchelf --set-rpath '$ORIGIN' "$f"
done
for f in "$PKG"/*.so*; do
    [ -f "$f" ] || continue
    patchelf --set-rpath '$ORIGIN/lib' "$f"
done
while read -r f; do
    rel=$(realpath --relative-to="$(dirname "$f")" "$PKG/lib")
    patchelf --set-rpath "\$ORIGIN/$rel" "$f"
done < <(find "$PKG/qtplugins" -type f -name '*.so')

strip --strip-unneeded "$PKG/vita3k" 2>/dev/null || true
find "$PKG/lib" "$PKG/qtplugins" -type f -name '*.so*' -exec strip --strip-unneeded {} + 2>/dev/null || true

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

exec "$HERE/vita3k" "$@"
EOF
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