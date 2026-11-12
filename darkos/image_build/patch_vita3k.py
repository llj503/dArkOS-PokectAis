#!/usr/bin/env python3
"""Make the Vita3K-Plus v1.4-Corrected tag build against its own pinned submodules.

Four upstream defects plus one pocketAis feature:

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

3. ``vita3k/renderer/src/vulkan/surface_cache.cpp`` assigns a braced-init-list to
   ``vk::Offset3D`` / ``vk::Extent3D`` members.  With the pinned Vulkan-Headers
   and C++23 that is ambiguous between ``operator=(VkOffset3D const &)`` and the
   implicit copy/move assignment, so name the type explicitly.

4. ``vita3k/main.cpp`` records the title to auto-boot after a CLI install on its
   own local ``Config``, which app::init() has already moved into EmuEnvState.
   MainWindow reads ``emuenv.cfg``, so the game never starts.  Write to that one.

5. ``vita3k/gui-qt/src/main_window.cpp``: on the desktop build the PS button
   only shows a static "Emulation Paused / Press PS to continue" overlay, there
   is no in-game menu. Replace ``on_ps_button()`` with a modal QMessageBox
   (Resume / Exit to app list). It is a Qt toplevel so Weston's kiosk shell
   displays it over the game, and Qt's own button focus works with the arrow
   keys + Enter/Esc that the handheld's uinput pad mapper already emits.

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


def patch_surface_cache(root: Path) -> None:
    p = root / "vita3k" / "renderer" / "src" / "vulkan" / "surface_cache.cpp"
    t = p.read_text(encoding="utf-8")
    pairs = [
        ("copy.imageOffset = { sync_x0, sync_y0, 0 };",
         "copy.imageOffset = vk::Offset3D{ sync_x0, sync_y0, 0 };"),
        ("copy.imageExtent = { sync_w, sync_h, 1 };",
         "copy.imageExtent = vk::Extent3D{ sync_w, sync_h, 1 };"),
    ]
    changed = 0
    for old, new in pairs:
        if new in t:
            continue
        if old not in t:
            print(f"WARNING: expected line not found in {p}: {old}")
            continue
        t = t.replace(old, new, 1)
        changed += 1
    if changed:
        p.write_text(t, encoding="utf-8")
        print(f"patched {p} ({changed} assignment(s))")
    else:
        print("surface_cache.cpp already patched")


def patch_cli_autoboot(root: Path) -> None:
    """main.cpp sets run_app_path on the wrong Config after a CLI install.

    app::init() does ``state.cfg = std::move(cfg)``, and EmuEnvState::cfg is a
    reference to a heap Config owned by _cfg -- a different object from main's
    local ``cfg``.  MainWindow's auto-boot reads ``emuenv.cfg.run_app_path``, so
    writing ``cfg.run_app_path`` after installing content from the command line
    logs "Content installed, will auto-boot: <TITLE>" and then never boots.
    Passing -r works because that path is set before app::init().
    """
    p = root / "vita3k" / "main.cpp"
    t = p.read_text(encoding="utf-8")
    old = "cfg.run_app_path = boot_title_id;"
    new = "emuenv.cfg.run_app_path = boot_title_id;"
    if new in t:
        print("main.cpp auto-boot already patched")
        return
    if old not in t:
        print(f"WARNING: expected line not found in {p}: {old}")
        return
    t = t.replace(old, new, 1)
    p.write_text(t, encoding="utf-8")
    print(f"patched {p} (auto-boot writes emuenv.cfg)")


PAUSE_MENU_MARKER = "// pocketAis: in-game pause menu"

PAUSE_MENU_BODY = PAUSE_MENU_MARKER + """
    if (!m_game_window)
        return;

    // QTimer-driven pump_sdl_events() can re-enter while the modal dialog runs.
    static bool menu_open = false;
    if (menu_open)
        return;
    menu_open = true;

    m_app_session.set_pause_reason(app::AppSessionPauseReason::User, true);
    refresh_emulation_actions();

    QMessageBox box(this);
    box.setWindowTitle(tr("Vita3K"));
    box.setText(tr("Game paused"));
    auto *resume_button = box.addButton(tr("Resume"), QMessageBox::AcceptRole);
    auto *exit_button = box.addButton(tr("Exit to app list"), QMessageBox::DestructiveRole);
    box.setDefaultButton(resume_button);
    box.exec();

    menu_open = false;
    if (box.clickedButton() == exit_button) {
        on_stop_triggered();
        return;
    }

    // Escape / B / a second PS press all fall through to Resume.
    m_app_session.set_pause_reason(app::AppSessionPauseReason::User, false);
    refresh_emulation_actions();
}"""


def patch_in_game_menu(root: Path) -> None:
    """Give the PS button a real in-game menu instead of a static pause card."""
    p = root / "vita3k" / "gui-qt" / "src" / "main_window.cpp"
    t = p.read_text(encoding="utf-8")
    if PAUSE_MENU_MARKER in t:
        print("main_window.cpp in-game menu already patched")
        return
    old = "void MainWindow::on_ps_button() {\n    on_pause_triggered();\n}"
    if old not in t:
        print(f"WARNING: expected on_ps_button() not found in {p}")
        return
    t = t.replace(old, "void MainWindow::on_ps_button() {\n" + PAUSE_MENU_BODY, 1)
    p.write_text(t, encoding="utf-8")
    print(f"patched {p} (in-game pause menu)")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1])
    if not (root / "vita3k").is_dir():
        sys.exit(f"{root} does not look like a Vita3K source tree")
    patch_fork_build_h(root)
    patch_atrac9(root)
    patch_surface_cache(root)
    patch_cli_autoboot(root)
    patch_in_game_menu(root)


if __name__ == "__main__":
    main()