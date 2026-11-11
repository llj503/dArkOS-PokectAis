#!/usr/bin/env python3
"""Make the Vita3K-Plus v1.4-Corrected tag build against its own pinned submodules.

Two defects in the tag (both are "tag is out of sync with what the author built"):

1. ``vita3k/util/include/util/fork_build.h`` is a generated header that was never
   committed, but ``vita3k/util/src/logging.cpp`` includes it.  Recreate it.
   Do *not* define RELEASE_VERSION here -- logging.cpp already defines it.

2. ``vita3k/codec/src/atrac9.cpp`` calls ``Atrac9DecodeBounded()``, which only
   exists in a newer LibAtrac9 than the gitlink the tag pins (82767fe3, whose
   master is identical).  Rather than bumping the submodule, add a bounded
   wrapper around the pinned ``Atrac9Decode()``.  LibAtrac9's BitReaderCxt has no
   length field, so the wrapper decodes from a private zero-padded copy of at
   most ``available`` bytes and rejects a frame that claims to consume more than
   the caller said was there.

Usage: patch_vita3k.py <vita3k-source-root>
Idempotent: safe to run twice.
"""
import sys
from pathlib import Path

FORK_BUILD_H = """#pragma once
#define FORK_BUILD_SEQ 1
#define FORK_BUILD_CHANGES "v1.4-Corrected"
"""

SHIM_MARKER = "// pocketAis: bounded Atrac9Decode shim"

SHIM = SHIM_MARKER + """
// The v1.4-Corrected tag calls Atrac9DecodeBounded(), which the pinned LibAtrac9
// (82767fe3) does not export. Emulate it on top of Atrac9Decode(): the decoder's
// BitReaderCxt carries no buffer length, so give it a private zero-padded copy of
// at most `available` bytes and fail if it reports consuming more than that.
// Returns -1 for shim-level rejections; otherwise the At9Status from the decoder.
static int Atrac9DecodeBounded(void *handle, const uint8_t *data, int available, short *pcm, int *used) {
    if (used)
        *used = 0;
    if (!handle || !data || !pcm || available <= 0)
        return -1;

    Atrac9CodecInfo info{};
    if (Atrac9GetCodecInfo(handle, &info) != At9Status::ERR_SUCCESS)
        return -1;

    // Never smaller than one superframe: the decoder may read a little past the
    // current frame while unpacking it. Zero padding keeps that in bounds.
    int capacity = info.superframeSize > 0 ? info.superframeSize : 4096;
    if (capacity < available)
        capacity = available;

    static thread_local std::vector<uint8_t> scratch;
    scratch.assign(static_cast<size_t>(capacity), 0);
    std::memcpy(scratch.data(), data, static_cast<size_t>(available));

    int consumed = 0;
    const int res = Atrac9Decode(handle, scratch.data(), pcm, &consumed);
    if (used)
        *used = consumed;
    if (res != At9Status::ERR_SUCCESS)
        return res;
    return consumed > available ? -1 : res;
}

"""


def patch_fork_build_h(root: Path) -> None:
    p = root / "vita3k" / "util" / "include" / "util" / "fork_build.h"
    if p.exists():
        print(f"fork_build.h already present: {p}")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(FORK_BUILD_H, encoding="utf-8")
    print(f"wrote {p}")


def patch_atrac9(root: Path) -> None:
    p = root / "vita3k" / "codec" / "src" / "atrac9.cpp"
    t = p.read_text(encoding="utf-8")

    if SHIM_MARKER in t:
        print("atrac9.cpp already patched")
        return
    if "Atrac9DecodeBounded" not in t:
        print("atrac9.cpp does not call Atrac9DecodeBounded; nothing to do")
        return

    anchor = "bool Atrac9DecoderState::send("
    idx = t.find(anchor)
    if idx < 0:
        sys.exit(f"anchor not found in {p}")
    t = t[:idx] + SHIM + t[idx:]

    if "#include <vector>" not in t:
        t = t.replace("#include <algorithm>\n", "#include <algorithm>\n#include <cstring>\n#include <vector>\n", 1)
    if "#include <cstring>" not in t:
        t = t.replace("#include <algorithm>\n", "#include <algorithm>\n#include <cstring>\n", 1)

    p.write_text(t, encoding="utf-8")
    print(f"patched {p}")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1])
    if not (root / "vita3k").is_dir():
        sys.exit(f"{root} does not look like a Vita3K source tree")
    patch_fork_build_h(root)
    patch_atrac9(root)


if __name__ == "__main__":
    main()