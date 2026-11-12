# Vita3K-Plus 移植文件同步说明

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
  gcc -O2 -Wall -o vita3k-osd vita3k-osd-wl.c xdg-shell-protocol.c \
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
