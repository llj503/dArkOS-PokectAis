#!/bin/bash
# Install the Wayland WSI layer for Vita3K on a running dArkOS device. Run as root.
#
#   install_vita3k_wsi.sh <vita3k-wsi.tar.zst>
#
# The RK3562 Mali blob is the gbm winsys variant: its Vulkan exposes
# VK_KHR_display and VK_EXT_headless_surface but not VK_KHR_wayland_surface, so
# Vita3K's Vulkan renderer cannot present under Weston. This layer supplies the
# missing WSI from a dma-buf backed swapchain. psvita-launch.sh enables it with
# VK_ADD_IMPLICIT_LAYER_PATH, scoped to the Vita3K process tree.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

TARBALL=${1:?usage: install_vita3k_wsi.sh <vita3k-wsi.tar.zst>}
DEST=/opt/vita3k-wsi
LIB=libVkLayer_window_system_integration.so
JSON=VkLayer_window_system_integration.json

[ -r "$TARBALL" ] || { echo "cannot read $TARBALL" >&2; exit 1; }
if [ -r "$TARBALL.sha256" ]; then
    echo "== verifying checksum =="
    (cd "$(dirname "$TARBALL")" && sha256sum -c "$(basename "$TARBALL").sha256")
fi

echo "== extracting to $DEST =="
STAGE=$(mktemp -d /opt/vita3k-wsi.new.XXXXXX)
trap 'rm -rf "$STAGE"' EXIT
tar --zstd -xf "$TARBALL" -C "$STAGE"
[ -r "$STAGE/vita3k-wsi/$LIB" ] || { echo "$LIB missing after extract" >&2; exit 1; }
[ -r "$STAGE/vita3k-wsi/$JSON" ] || { echo "$JSON missing after extract" >&2; exit 1; }

# The manifest's library_path is baked in at build time; rewrite it so the
# install location does not have to match the builder's.
python3 - "$STAGE/vita3k-wsi/$JSON" "$DEST/$LIB" <<'PY'
import json, sys
path, lib = sys.argv[1], sys.argv[2]
j = json.load(open(path))
j["layer"]["library_path"] = lib
json.dump(j, open(path, "w"), indent=3)
PY

if [ -d "$DEST" ]; then
    rm -rf "$DEST.old"
    mv "$DEST" "$DEST.old"
fi
mv "$STAGE/vita3k-wsi" "$DEST"
trap - EXIT
rm -rf "$STAGE" "$DEST.old"
chmod 0755 "$DEST"
chmod 0644 "$DEST"/*

echo "== checking the layer resolves =="
# ldd on the layer itself: it must find libwayland-client and libstdc++.
if ldd "$DEST/$LIB" 2>&1 | grep -q "not found"; then
    ldd "$DEST/$LIB" >&2
    echo "unresolved dependencies, the layer will not load" >&2
    exit 1
fi
grep -q "VK_ADD_IMPLICIT_LAYER_PATH" /usr/local/bin/psvita-launch.sh \
    || echo "warning: psvita-launch.sh does not enable the layer" >&2

echo "installed to $DEST"
echo "enable per process with: VK_ADD_IMPLICIT_LAYER_PATH=$DEST"