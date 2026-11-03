#!/usr/bin/env python3
"""Patch bmdhacks/pcsx2 SDL frontend for Simplified Chinese UI and a safe pause menu.

Usage: patch_pcsx2sa_zh.py <source-root>
"""
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])


def replace_once(rel, old, new, count=1):
    path = root / rel
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        sys.exit(f"patch point not found in {rel}: {old[:80]!r}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


# ---- translation loader ----
main = "pcsx2-sdl/Main.cpp"
replace_once(main, "#include <deque>\n", "#include <deque>\n#include <fstream>\n")
replace_once(main, "#include <thread>\n", "#include <thread>\n#include <unordered_map>\n")
replace_once(main, "// Load Roboto for OSD / FullscreenUI (font is bundled in resources).",
             "// Load Noto Sans CJK SC for the Chinese OSD / FullscreenUI.")
replace_once(main, '"fonts" FS_OSPATH_SEPARATOR_STR "Roboto-Regular.ttf"',
             '"fonts" FS_OSPATH_SEPARATOR_STR "NotoSansCJK-Regular.ttc"')
replace_once(main, "\t\tfi.face_name = nullptr;", '\t\tfi.face_name = "Noto Sans CJK SC";')

old_trans = '''s32 Host::Internal::GetTranslatedStringImpl(
	const std::string_view context, const std::string_view msg, char* tbuf, size_t tbuf_space)
{
	if (msg.size() > tbuf_space)
		return -1;
	if (msg.empty())
		return 0;

	std::memcpy(tbuf, msg.data(), msg.size());
	return static_cast<s32>(msg.size());
}'''
new_trans = '''static const std::unordered_map<std::string, std::string>& GetZhTranslationMap()
{
	static std::once_flag once;
	static std::unordered_map<std::string, std::string> map;
	std::call_once(once, []() {
		const std::string path =
			EmuFolders::GetOverridableResourcePath("translations" FS_OSPATH_SEPARATOR_STR "zh-CN.tsv");
		std::ifstream in(path, std::ios::binary);
		std::string line;
		while (std::getline(in, line))
		{
			if (!line.empty() && line.back() == '\\r')
				line.pop_back();
			const size_t t1 = line.find('\\t');
			const size_t t2 = (t1 == std::string::npos) ? t1 : line.find('\\t', t1 + 1);
			if (t1 == std::string::npos || t2 == std::string::npos)
				continue;
			map.emplace(line.substr(0, t1) + '\\x1f' + line.substr(t1 + 1, t2 - t1 - 1), line.substr(t2 + 1));
		}
	});
	return map;
}

s32 Host::Internal::GetTranslatedStringImpl(
	const std::string_view context, const std::string_view msg, char* tbuf, size_t tbuf_space)
{
	if (msg.size() > tbuf_space)
		return -1;
	if (msg.empty())
		return 0;

	static const auto& map = GetZhTranslationMap();
	const std::string key = std::string(context) + '\\x1f' + std::string(msg);
	const auto it = map.find(key);
	const std::string_view out = (it != map.end()) ? std::string_view(it->second) : msg;
	if (out.size() > tbuf_space)
		return -1;

	std::memcpy(tbuf, out.data(), out.size());
	return static_cast<s32>(out.size());
}'''
replace_once(main, old_trans, new_trans)

# ImGui 1.92's dynamic font atlas (RendererHasTextures) loads CJK glyphs on
# demand from the replacement font; no glyph-range API is needed (and it is
# compiled out by IMGUI_DISABLE_OBSOLETE_FUNCTIONS).

# ---- pause menu vs frontend main loop ----
# A CLI-booted game runs with start_in_fsui=false. Opening the pause menu sets
# the VM to Paused, and the old main loop treated Paused as "game over, no FSUI
# to return to" and exited the whole app. Keep running while a FSUI window
# (the pause menu) is active.
main_path = root / main
main_text = main_path.read_text(encoding="utf-8")
if ('#include "ImGui/FullscreenUI.h"' not in main_text and
        '#include "pcsx2/ImGui/FullscreenUI.h"' not in main_text):
    for inc, full in (
        ('#include "ImGui/ImGuiManager.h"\n', '#include "ImGui/FullscreenUI.h"\n'),
        ('#include "pcsx2/ImGui/ImGuiManager.h"\n', '#include "pcsx2/ImGui/FullscreenUI.h"\n'),
    ):
        if inc in main_text:
            main_path.write_text(main_text.replace(inc, inc + full, 1), encoding="utf-8")
            break
    else:
        sys.exit("ImGuiManager include not found for FullscreenUI include")
replace_once(
    main,
    "\t\t\t\tif (!start_in_fsui)\n"
    "\t\t\t\t{\n"
    "\t\t\t\t\ts_shutdown_requested.store(true, std::memory_order_release);\n"
    "\t\t\t\t\tbreak;\n"
    "\t\t\t\t}\n",
    "\t\t\t\tif (!start_in_fsui && !FullscreenUI::HasActiveWindow())\n"
    "\t\t\t\t{\n"
    "\t\t\t\t\ts_shutdown_requested.store(true, std::memory_order_release);\n"
    "\t\t\t\t\tbreak;\n"
    "\t\t\t\t}\n",
)

# ---- pause menu: force Resume focus and debounce close/exit ----
ui = "pcsx2/ImGui/FullscreenUI.cpp"
text = (root / ui).read_text(encoding="utf-8")
if "#include <atomic>" not in text:
    first_include = text.find("#include ")
    text = text[:first_include] + "#include <atomic>\n" + text[first_include:]
(root / ui).write_text(text, encoding="utf-8")

replace_once(
    ui,
    '#include "fmt/chrono.h"\n',
    '#include "fmt/chrono.h"\n\nstatic std::atomic<bool> s_force_pause_resume_focus{false};\n',
)
replace_once(
    ui,
    "\t\tPauseForMenuOpen(true);\n\t\tForceKeyNavEnabled();\n\t\ts_current_main_window = MainWindowType::PauseMenu;",
    "\t\tPauseForMenuOpen(true);\n\t\tForceKeyNavEnabled();\n\t\ts_force_pause_resume_focus.store(true, std::memory_order_relaxed);\n"
    "\t\ts_current_main_window = MainWindowType::PauseMenu;",
)
replace_once(
    ui,
    "\t\tconst bool just_focused = ResetFocusHere();\n",
    "\t\tconst bool just_focused = ResetFocusHere();\n"
    "\t\tconst bool force_resume_focus = s_force_pause_resume_focus.exchange(false, std::memory_order_relaxed);\n"
    "\t\tstatic double s_pause_menu_open_time = 0.0;\n"
    "\t\tif (just_focused || force_resume_focus)\n"
    "\t\t\ts_pause_menu_open_time = ImGui::GetTime();\n",
)
# ARMSX2 adds "+ GetArcadePauseMenuItemCount(...)" to the item count, so match
# the call generically instead of by exact text.
pause_ui_path = root / ui
pause_ui = pause_ui_path.read_text(encoding="utf-8")
if "const bool pause_input_ready" not in pause_ui:
    btn_match = re.search(
        r"\t\tBeginMenuButtons\(submenu_item_count\[static_cast<u32>\(s_current_pause_submenu\)\][^\n]*\n"
        r"\t\t\tImGuiFullscreen::LAYOUT_MENU_BUTTON[^\n]*\n",
        pause_ui,
    )
    if not btn_match:
        sys.exit("pause menu BeginMenuButtons block not found")
    pause_ui = (
        pause_ui[:btn_match.end()]
        + "\n"
        + "\t\t// Debounce the opening combo only; navigation must stay live.\n"
        + "\t\tconst bool pause_input_ready = (ImGui::GetTime() - s_pause_menu_open_time) > 0.35;\n"
        + pause_ui[btn_match.end():]
    )
    pause_ui_path.write_text(pause_ui, encoding="utf-8")

replace_once(
    ui,
    "\t\t\t\tif (just_focused)\n"
    "\t\t\t\t\tImGui::SetFocusID(ImGui::GetID(FSUI_ICONSTR(ICON_FA_PLAY, \"Resume Game\")), ImGui::GetCurrentWindow());\n"
    "\n"
    "\t\t\t\tif (ActiveButton(FSUI_ICONSTR(ICON_FA_PLAY, \"Resume Game\"), false) || WantsToCloseMenu())\n"
    "\t\t\t\t\tClosePauseMenu();\n",
    "\t\t\t\tif (just_focused || force_resume_focus)\n"
    "\t\t\t\t\tImGui::SetFocusID(ImGui::GetID(FSUI_ICONSTR(ICON_FA_PLAY, \"Resume Game\")), ImGui::GetCurrentWindow());\n"
    "\n"
    "\t\t\t\tif (pause_input_ready && (ActiveButton(FSUI_ICONSTR(ICON_FA_PLAY, \"Resume Game\"), false) || WantsToCloseMenu()))\n"
    "\t\t\t\t\tClosePauseMenu();\n",
)
replace_once(
    ui,
    "\t\t\t\tif (ActiveButton(FSUI_ICONSTR(ICON_FA_POWER_OFF, \"Close Game\"), false))",
    "\t\t\t\tif (pause_input_ready && ActiveButton(FSUI_ICONSTR(ICON_FA_POWER_OFF, \"Close Game\"), false))",
)
replace_once(
    ui,
    "\t\t\t\t{\n"
    "\t\t\t\t\t// skip submenu when we can't save anyway\n"
    "\t\t\t\t\tif (!can_save_state)\n"
    "\t\t\t\t\t\tRequestShutdown(false);\n"
    "\t\t\t\t\telse\n"
    "\t\t\t\t\t\tOpenPauseSubMenu(PauseSubMenu::Exit);\n"
    "\t\t\t\t}\n",
    "\t\t\t\t{\n"
    "\t\t\t\t\t// The handheld exits with Select+Start; never let a menu button terminate the VM.\n"
    "\t\t\t\t\tHost::AddIconOSDMessage(\"pause_menu_exit\", ICON_FA_POWER_OFF, \"请按 Select+Start 退出游戏\", 5.0f);\n"
    "\t\t\t\t}\n",
)

print(f"patched {root}")
