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

5. ``vita3k/gui-qt/src/main_window.cpp``: the PS button only showed a static
   "Emulation Paused" overlay. Replace ``on_ps_button()`` with a parentless
   ``QInputDialog`` combo box: one screen holding the same options as the ES
   cards (system language, resolution scale, guest cores), plus Resume and
   Exit to app list. It is a Qt toplevel so kiosk-shell stacks it over the game,
   and the combo box works with d-pad + A/B (Enter/Escape). Selected settings
   are written to ``emuenv.cfg`` and serialized immediately; they take effect
   on the next game boot. Exit is deferred with QTimer to avoid the Qt crash
   caused by deleting the game window inside a nested dialog loop.

6. ``vita3k/gui-qt/src/apps_list_table.cpp`` (plus a few headers): the desktop
   GUI sets ``Qt::NoFocus`` on the app list and the settings category lists,
   so a gamepad's arrow keys cannot select anything -- the only way to drive
   it was a pointer, which is painful on a 3.5" handheld. Give those widgets
   ``Qt::StrongFocus``, enlarge the icons and the selected-row highlight, and
   focus the app list on startup / after a game closes. ``Enter`` already
   boots the selected row (``AppsListTable::keyPressEvent``).

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

    // One screen for the settings that used to be separate ES cards.
    // Parentless: with MainWindow as parent Qt embeds the dialog behind the
    // fullscreen game window under kiosk-shell.
    QStringList items;
    items << tr("继续游戏 / Resume")
          << tr("系统语言：简体中文")
          << tr("系统语言：English")
          << tr("画面倍率：1x 流畅")
          << tr("画面倍率：2x 清晰")
          << tr("性能：省电 2 核")
          << tr("性能：平衡 3 核")
          << tr("退出到应用列表");

    // getItem(nullptr, ...) creates a standalone Wayland toplevel; a dialog
    // parented to MainWindow is hidden behind the fullscreen game window.
    bool accepted = false;
    const QString choice_text = QInputDialog::getItem(
        nullptr, tr("Vita3K 快捷设置"),
        tr("方向键选择，A 确认，B 返回（设置下次启动游戏生效）"),
        items, 0, false, &accepted);
    const int choice = accepted ? items.indexOf(choice_text) : -1;
    menu_open = false;

    switch (choice) {
    case 1: emuenv.cfg.sys_lang = 11; break;              // Chinese (Simplified)
    case 2: emuenv.cfg.sys_lang = 1; break;               // English (US)
    case 3: emuenv.cfg.resolution_multiplier = 1.0f; break;
    case 4: emuenv.cfg.resolution_multiplier = 2.0f; break;
    case 5: emuenv.cfg.guest_cores = 2; break;
    case 6: emuenv.cfg.guest_cores = 3; break;
    case 7:
        // Deferred: deleting the game window from inside a nested dialog loop
        // crashed Qt with the old Exit-to-app-list button.
        QTimer::singleShot(0, this, [this] { on_stop_triggered(); });
        return;
    default: break;
    }
    if (choice >= 1 && choice <= 6)
        config::serialize_config(emuenv.cfg, emuenv.cfg.config_path);

    // Resume (also covers Escape / B / a second PS press).
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
    if "#include <QInputDialog>" not in t:
        t = t.replace("#include <QMessageBox>",
                      "#include <QMessageBox>\n#include <QInputDialog>", 1)
    if "#include <QTimer>" not in t:
        t = t.replace("#include <QStandardPaths>",
                      "#include <QStandardPaths>\n#include <QTimer>", 1)
    t = t.replace(old, "void MainWindow::on_ps_button() {\n" + PAUSE_MENU_BODY, 1)
    p.write_text(t, encoding="utf-8")
    print(f"patched {p} (in-game quick settings menu)")


HANDHELD_MARKER = "// pocketAis: handheld keyboard navigation"

HANDHELD_APPS_LIST = HANDHELD_MARKER + """
    // A gamepad is the only input on the handheld: let the list take keyboard
    // focus so d-pad/stick moves the selection and Enter boots the title.
    setFocusPolicy(Qt::StrongFocus);
    setStyleSheet(QStringLiteral(
        "QTableView { font-size: 18px; outline: 0; }"
        "QTableView::item:selected { background: #2d7ff9; color: white; }"));
    // The icon delegate paints the row background itself, so drive the
    // highlight through the palette as well as the stylesheet.
    QPalette handheld_pal = palette();
    handheld_pal.setColor(QPalette::Highlight, QColor(45, 127, 249));
    handheld_pal.setColor(QPalette::HighlightedText, QColor(Qt::white));
    setPalette(handheld_pal);
    QTimer::singleShot(0, this, [this] {
        setFocus();
        // With only one installed title a d-pad press cannot visibly move the
        // selection, so preselect the first row on startup.
        if (rowCount() > 0 && selectionModel() && !selectionModel()->hasSelection())
            selectRow(currentRow() >= 0 ? currentRow() : 0);
    });"""


def patch_handheld_gui(root: Path) -> None:
    """Make the Qt GUI navigable with d-pad + A/B instead of a mouse."""
    qt = root / "vita3k" / "gui-qt"

    p = qt / "src" / "apps_list_table.cpp"
    t = p.read_text(encoding="utf-8")
    if HANDHELD_MARKER not in t:
        old = "    setFocusPolicy(Qt::NoFocus);"
        if old not in t:
            print(f"WARNING: app list focus line not found in {p}")
        else:
            t = t.replace(old, "    " + HANDHELD_APPS_LIST, 1)
            p.write_text(t, encoding="utf-8")
            print(f"patched {p} (app list keyboard focus + highlight)")
    else:
        print("apps_list_table.cpp handheld navigation already patched")

    p = qt / "include" / "gui-qt" / "apps_list_table.h"
    t = p.read_text(encoding="utf-8")
    if "pocketAis: larger handheld icons" not in t:
        old = "    QSize m_icon_size{ 75, 75 };"
        if old in t:
            t = t.replace(old, "    // pocketAis: larger handheld icons\n    QSize m_icon_size{ 96, 96 };", 1)
            p.write_text(t, encoding="utf-8")
            print(f"patched {p} (larger icons)")
        else:
            print(f"WARNING: icon size line not found in {p}")

    for rel, old, new in [
        ("src/controls_dialog.cpp",
         "m_ui->settingsCategory->setFocusPolicy(Qt::NoFocus);",
         "m_ui->settingsCategory->setFocusPolicy(Qt::StrongFocus); // pocketAis: pad navigation"),
        ("src/settings_dialog.cpp",
         "m_ui->modules_list->setFocusPolicy(Qt::NoFocus);",
         "m_ui->modules_list->setFocusPolicy(Qt::StrongFocus); // pocketAis: pad navigation"),
        ("src/settings_dialog.cpp",
         "m_ui->tracy_modules_list->setFocusPolicy(Qt::NoFocus);",
         "m_ui->tracy_modules_list->setFocusPolicy(Qt::StrongFocus); // pocketAis: pad navigation"),
    ]:
        p = qt / rel
        t = p.read_text(encoding="utf-8")
        if new in t:
            continue
        if old not in t:
            print(f"WARNING: focus line not found in {p}")
            continue
        p.write_text(t.replace(old, new, 1), encoding="utf-8")
        print(f"patched {p} (focus)")

    p = qt / "src" / "main_window.cpp"
    t = p.read_text(encoding="utf-8")
    old = """    if (!m_is_app_closing) {
        raise();
        activateWindow();
    }"""
    new = """    if (!m_is_app_closing) {
        raise();
        activateWindow();
        // pocketAis: hand keyboard focus back to the app list
        if (m_apps_list_widget)
            m_apps_list_widget->setFocus();
    }"""
    if "// pocketAis: hand keyboard focus back" in t:
        pass
    elif old not in t:
        print(f"WARNING: raise block not found in {p}")
    else:
        p.write_text(t.replace(old, new, 1), encoding="utf-8")
        print(f"patched {p} (focus restore after game closes)")


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
    patch_handheld_gui(root)


if __name__ == "__main__":
    main()