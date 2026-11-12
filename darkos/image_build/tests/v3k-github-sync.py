#!/usr/bin/env python3
"""Sync the Vita3K-Plus port artefacts into the dArkOS-PokectAis checkout.

Usage: python3 v3k-github-sync.py [repo-checkout]
Default checkout: /tmp/darkos-probe

Only source, tests, docs and small evidence files are copied. Release bundles
(already on GitHub Releases), the upstream Vita3K source snapshot, git bundles,
.workbuddy data and __pycache__ are intentionally excluded.
"""
import pathlib
import shutil
import sys

WORK = pathlib.Path(__file__).resolve().parents[2]
REPO = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/darkos-probe")
IB = REPO / "darkos" / "image_build"
TESTS = IB / "tests"
DOCS = REPO / "docs"
IMAGES = DOCS / "images"
EVIDENCE = DOCS / "vita3k-logs"

# patch_vita3k.py already lives in darkos/image_build (CI reads it there) and
# is byte-identical to the workspace copy.
EXCLUDE_NAMES = {"__pycache__", "v3k-github-sync.py", "patch_vita3k.py"}

SCRIPT_EXTS = {".sh", ".py", ".c", ".h"}
SCRIPT_EXTRA = {"console-detect"}


def norm_copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes().replace(b"\r\n", b"\n")
    if dst.exists() and dst.read_bytes() == data:
        return False
    dst.write_bytes(data)
    return True


def main():
    if not (REPO / ".git").is_dir():
        raise SystemExit(f"not a git checkout: {REPO}")
    changed = []

    # 1. top-level launcher/build scripts
    for src in sorted((WORK / "scripts").iterdir()):
        if not src.is_file() or src.name in EXCLUDE_NAMES:
            continue
        if src.suffix not in SCRIPT_EXTS and src.name not in SCRIPT_EXTRA:
            continue
        dst = IB / src.name
        if norm_copy(src, dst):
            changed.append(str(dst.relative_to(REPO)))

    # 2. test / verification scripts
    for src in sorted((WORK / "scripts" / "tests").glob("*")):
        if not src.is_file() or src.suffix not in SCRIPT_EXTS:
            continue
        dst = TESTS / src.name
        if norm_copy(src, dst):
            changed.append(str(dst.relative_to(REPO)))

    # 3. Wayland protocol XML needed to build the OSD
    xml = WORK / "packages" / "xdg-shell.xml"
    if xml.exists() and norm_copy(xml, IB / "xdg-shell.xml"):
        changed.append("darkos/image_build/xdg-shell.xml")

    # 4. port status document
    status = WORK / "README-继续移植.md"
    if status.exists() and norm_copy(status, DOCS / "Vita3K-Plus-移植记录.md"):
        changed.append("docs/Vita3K-Plus-移植记录.md")

    # 5. key screenshots
    shots = {
        "osd-flush2-wl.png": "vita3k-osd-zh.png",
        "osd-english.png": "vita3k-osd-en.png",
        "osd-open-done.png": "vita3k-osd-ingame.png",
        "nav-before-d.png": "vita3k-applist-nav.png",
        "gui-mouse-after.png": "vita3k-gui-mouse.png",
        "play-runtimefix-t300.png": "vita3k-game-5min.png",
        "menu-open-b.png": "vita3k-pause-menu.png",
    }
    IMAGES.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in shots.items():
        src = WORK / "shots" / src_name
        if not src.exists():
            continue
        dst = IMAGES / dst_name
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            shutil.copyfile(src, dst)
            changed.append(str(dst.relative_to(REPO)))

    # 6. verification logs
    logs = {
        "v3k-osd-verify-done.out": "osd-verify.out",
        "v3k-keyboard-nav-verify-d.out": "keyboard-nav-verify.out",
        "v3k-gui-mouse-verify.out": "gui-mouse-verify.out",
        "v3k-play-verify-runtime-fix.out": "play-verify.out",
        "v3k-autosync-verify.out": "autosync-verify.out",
        "v3k-menu-verify-20261112b.out": "pause-menu-verify.out",
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in logs.items():
        src = WORK / "logs" / src_name
        if not src.exists():
            continue
        dst = EVIDENCE / dst_name
        if norm_copy(src, dst):
            changed.append(str(dst.relative_to(REPO)))

    # 7. sync index
    index = DOCS / "Vita3K-Plus-同步说明.md"
    text = """# Vita3K-Plus 移植文件同步说明

本目录/脚本由 `v3k-github-sync.py` 从移植工作区同步，对应设备
`192.168.0.23`（dArkOS / RK3562 / 1024x768）上已验证的一套配置。

## 位置对照

| 仓库路径 | 设备路径 | 说明 |
| --- | --- | --- |
| `darkos/image_build/psvita-launch.sh` | `/usr/local/bin/psvita-launch.sh` | ES 启动器；支持 zip/vpk 游戏、空 ROM GUI、`.sh` 设置卡片；自建 `/run/vita3k` runtime 目录 |
| `darkos/image_build/vita3k-pad.py` | `/usr/local/bin/vita3k-pad.py` | 手柄→uinput 键盘/可选鼠标；热键由 `console-detect -t` 派生；journal 自动同步 game/gui 模式 |
| `darkos/image_build/psvita-lang.py` | `/usr/local/bin/psvita-lang.py` | 跟随 ES `Language=zh-CN` 自动设 `sys-lang` 11/1；`.lang-manual` 手动优先 |
| `darkos/image_build/psvita-option.py` | `/usr/local/bin/psvita-option.py` | ES 选项卡片后端；`--apply-pending` 应用游戏内 OSD 选择 |
| `darkos/image_build/console-detect` | `/usr/local/bin/console-detect` | 统一热键入口（回退到 `/roms/vita3k/.hotkey-type`） |
| `darkos/image_build/vita3k-osd-wl.c` | `/usr/local/bin/vita3k-osd`（编译产物） | 纯 Wayland 图形 OSD：wl_shm + xdg-shell + FreeType 中文 |
| `darkos/image_build/xdg-shell.xml` | 编译时用 | `wayland-scanner` 生成协议代码的输入 |
| `darkos/image_build/vita3k-osd.c` | — | 早期 SDL2 版（本机 SDL2 无 Wayland backend，仅作参考） |
| `darkos/image_build/patch_vita3k.py` | CI 使用 | 上游 v1.4-Corrected 的 6 处补丁（含禁用 PS/Home 菜单、应用列表键盘导航） |
| `darkos/image_build/tests/v3k-*` | 验证脚本 | 端到端复验脚本（.py/.sh），非设备运行必需 |
| `docs/Vita3K-Plus-移植记录.md` | — | 完整移植状态与踩坑记录 |
| `docs/images/vita3k-*.png` | — | 关键界面截图（中/英 OSD、应用列表、游戏画面） |
| `docs/vita3k-logs/*.out` | — | 关键复验日志 |

## 依赖与产物

- 二进制 bundle 由 `.github/workflows/build-vita3k.yml` 构建并发布到 GitHub
  Releases（最新 `vita3k-plus-armv8a-20261112g`），**不在仓库内重复存放**。
- `console_detect` 来自 https://github.com/lcdyk0517/console-detect ，
  设备上 `make native && sudo make install`；本机 DTB 不在映射表时写
  `/boot/.console=ngp45ht`，`console-detect -t` 返回 `happy5`。
- OSD 编译（设备上）：
  ```
  wayland-scanner client-header xdg-shell.xml xdg-shell-client-protocol.h
  wayland-scanner private-code  xdg-shell.xml xdg-shell-protocol.c
  gcc -O2 -Wall -o vita3k-osd vita3k-osd-wl.c xdg-shell-protocol.c \\
      $(pkg-config --cflags --libs wayland-client freetype2) -lrt
  ```
- 安装：`install_vita3k.sh <bundle.tar.zst> <scripts-dir>`（会同步 launcher 与
  mapper，其余脚本单独部署）。

## 未同步内容

Release tarballs、`source/`（上游 Vita3K 源码快照，952 文件）、`repo/*.bundle`
（本地 git 备份）、`.workbuddy/`（工作区记忆）、`__pycache__`、CI 失败日志等
临时文件都不上传；Releases 与上游仓库已经是它们的权威来源。

## 操作方式（掌机）

- ES → psvita：方向键选、A 确认、B 返回；游戏与「选项」都是中文卡片。
- 游戏内按 **Home**（`happy5`）→ 图形 OSD：方向键选、A 确认、B 返回；
  设置写入 `.osd-pending`，退出游戏后由 launcher 应用（下次启动生效）。
- Vita3K 原生 GUI：方向键选应用、A 启动、B 返回；`Select+R3` 切可选鼠标模式。
- `Select+Start` 退出回 ES。
"""
    if not index.exists() or index.read_text(encoding="utf-8") != text:
        index.write_text(text, encoding="utf-8")
        changed.append("docs/Vita3K-Plus-同步说明.md")

    # 8. root README pointer
    readme = REPO / "README.md"
    rtext = readme.read_text(encoding="utf-8")
    pointer = "\n## Vita3K-Plus (PS Vita) 移植\n\n详见 [Vita3K-Plus 同步说明](docs/Vita3K-Plus-同步说明.md) 与 [移植记录](docs/Vita3K-Plus-移植记录.md)。\n"
    if "Vita3K-Plus 同步说明" not in rtext:
        readme.write_text(rtext.rstrip() + "\n" + pointer, encoding="utf-8")
        changed.append("README.md")

    print(f"CHANGED {len(changed)} files")
    for p in changed:
        print(" ", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
