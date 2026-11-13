# Vita3K-Plus 移植文件同步说明

本目录/脚本由 `v3k-github-sync.py` 从移植工作区同步，对应 dArkOS 掌机
（RK3562 / 4x Cortex-A53 / 1024x768 DSI / 2GB RAM，Debian trixie，内核
5.10.226）上已真机验证的一套配置。最新验证机 `192.168.0.176`（ark/ark）。

## 位置对照

| 仓库路径 | 设备路径 | 说明 |
| --- | --- | --- |
| `darkos/image_build/psvita-launch.sh` | `/usr/local/bin/psvita-launch.sh` | ES 启动器：zip/vpk 游戏、无 ROM 时网格前端、`--native-gui` 原生 Qt；固件闸门（缺 vs0/sa0 先弹 setup 面板）、自建 `/run/vita3k`、背光保存/恢复、退出应用 OSD pending |
| `darkos/image_build/vita3k-pad.py` | `/usr/local/bin/vita3k-pad.py` | 手柄→uinput 键盘/可选鼠标；热键由 `console-detect -t` 派生；游戏内拉起 OSD；`.frontend-active` 期间让位 |
| `darkos/image_build/vita3k-osd-wl.c` | `/usr/local/bin/vita3k-osd`（编译产物） | 纯 Wayland 图形界面：游戏内 7 项快捷设置网格；`--setup` 模式为 10 卡首次设置页（3 固件卡+状态徽章、文件浏览器、下载区域） |
| `darkos/image_build/vita3k-frontend-wl.c` | `/usr/local/bin/vita3k-frontend`（编译产物） | 无 ROM 时的全屏游戏网格（读 param.sfo + icon0.png，A 启动游戏，B 返回 ES） |
| `darkos/image_build/psvita-lang.py` | `/usr/local/bin/psvita-lang.py` | 跟随 ES `Language=zh-CN` 自动设 `sys-lang` 11/1；手动优先 |
| `darkos/image_build/psvita-option.py` | `/usr/local/bin/psvita-option.py` | 选项后端；`--apply-pending` 应用 OSD/设置选择 |
| `darkos/image_build/console-detect` | `/usr/local/bin/console-detect` | 统一热键入口（回退 `/roms/vita3k/.hotkey-type`） |
| `darkos/image_build/xdg-shell.xml` | 编译时用 | `wayland-scanner` 生成协议代码 |
| `darkos/image_build/vita3k-config-template.yml` | `/roms/vita3k/config.yml` 模板 | 194 键完整配置；避免 Vita3K 首次运行用默认值覆写并弹 Welcome |
| `darkos/image_build/install_vita3k.sh` | — | 设备安装器（bundle + launcher + mapper + ES 条目 + 主题） |
| `darkos/image_build/install_vita3k_wsi.sh` | — | vulkan-wsi-layer 安装器 |
| `darkos/image_build/patch_vita3k.py` | CI 使用 | 上游 v1.4-Corrected 的 6 处补丁（禁用 PS/Home 菜单、应用列表键盘导航等） |
| `darkos/image_build/tests/v3k-*` | 验证脚本 | 端到端复验/一键部署脚本（.py/.sh），非设备运行必需 |
| `docs/Vita3K-Plus-移植记录.md` | — | 完整移植状态与踩坑记录 |
| `docs/images/vita3k-*.png` | — | 关键界面截图（网格前端、快捷设置、首次设置徽章、PUP 浏览器、游戏画面） |
| `docs/vita3k-logs/*.out` | — | 关键复验日志 |

## 依赖与产物

- 二进制 bundle 由 `.github/workflows/build-vita3k.yml` 构建并发布到 GitHub
  Releases（最新 `vita3k-plus-armv8a-20261112g`），**不在仓库内重复存放**。
- WSI 层由 `build-vita3k-wsi.yml` 发布（release `vita3k-wsi-a53-20261111`）。
- `console_detect` 来自 https://github.com/lcdyk0517/console-detect ；
  本机 DTB 不在映射表时写 `/boot/.console=ngp45ht`，`console-detect -t` 返回 `happy5`。
- 设备端编译（需要 `libwayland-dev libfreetype-dev libpng-dev`）：
  ```
  wayland-scanner client-header xdg-shell.xml xdg-shell-client-protocol.h
  wayland-scanner private-code  xdg-shell.xml xdg-shell-protocol.c
  gcc -O2 -Wall -o vita3k-osd vita3k-osd-wl.c xdg-shell-protocol.c -I. $(pkg-config --cflags --libs wayland-client freetype2) -lrt -lm
  gcc -O2 -Wall -o vita3k-frontend vita3k-frontend-wl.c xdg-shell-protocol.c -I. $(pkg-config --cflags --libs wayland-client freetype2 libpng) -lrt -lm
  ```
- 一键部署：`v3k-install-fresh.py`（全新机）、`v3k-osd-grid-deploy.py`（OSD/setup）、
  `v3k-frontend-deploy.py`（网格前端）、`v3k-fix-game-boot.py`（固件+游戏安装）。

## 固件包

Vita3K 判定 `fs/vs0`（主固件）与 `fs/sa0`（字体包）非空；`fs/pd0`（预装包）可选。
设备缺任一项时，启动游戏前会弹出快捷设置面板，用文件浏览器选 `.PUP` 安装，
两项齐全后自动进入游戏。三个官方 PUP 的直链与大小见移植记录。

## 未同步内容

Release tarballs、`source/`（上游 Vita3K 源码快照）、`repo/*.bundle`
（本地 git 备份）、`.workbuddy/`（工作区记忆）、`__pycache__`、CI 失败日志等
临时文件都不上传；Releases 与上游仓库已经是它们的权威来源。
`/roms/ports/` 下不放任何 Vita3K 入口，也不安装系统热键守护服务。

## 操作方式（掌机）

- ES → psvita：只显示游戏；方向键选、A 启动（已装游戏走 `-r TITLEID` 秒开）。
- **游戏内按系统热键**（`console-detect -t`，本机 happy5→Home/Menu）→ 快捷设置面板：
  方向键/摇杆选择、A 确认、B 返回游戏；设置写入 `.osd-pending`，退出游戏后生效。
- 首次设置/缺固件：面板三张固件卡带「已安装/缺失/可选」徽章 → 文件浏览器选 PUP
  → A 安装 → 自动进游戏；B 返回上级、Home 回菜单。
- 无 ROM 打开 Vita3K：全屏游戏网格，A 启动、B 返回 ES、Home/高级设置进原生 Qt GUI。
- `Select+Start` 退出回 ES。
