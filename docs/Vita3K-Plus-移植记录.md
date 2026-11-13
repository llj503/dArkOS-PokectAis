# Vita3K-Plus → dArkOS 移植：状态 2026-11-12 21:12（真机闪退已修）

设备 `ark@192.168.0.23`（办公室网段，ark/ark），bundle `pocketAis-Vita3KPlus-armv8a-20261111c`。
仓库最新提交 `d8040b5`（main 已推送）；本次未改仓库代码，只改设备与工作区脚本副本。

## 一句话状态

**已跑通：ES 选 zip → 直接启动（不重装）→ 实时 3D 画面稳定 5 分钟 → Select+Start → 回 ES。**
昨天卡住的 `Invalid SELF / Failed to start game threads` 已定位并修复；
20:58/20:59 用户真机从 ES 进游戏闪退，根因是 logind 的 `XDG_RUNTIME_DIR`
随 SSH 会话消失导致 Weston fatal，也已修复（见下第 7 条）。

## 2026-11-12 完成的事

1. **根因**：`/roms/psvita/*.zip` 不是解密的 NoNpDrm dump，而是 PFS 加密包：
   app/eboot.bin 头 `d3 d0 b7 a9`、熵 8.0、无 `SCE\0` magic，
   `sce_pfs/files.db`、`sce_sys/package/work.bin`、`keystone` 齐备。
   Vita3K 安装时 `interface.cpp:is_nonpdrm → decrypt_install_nonpdrm` 才把整个目录
   PFS 解密（work.bin → zRIF → F00D），产出合法 SELF。
   11-11 09:08 在 exFAT 上重跑安装（1766 文件 × 解压/解密/复制）触发写风暴并中断，
   只留下加密 eboot；之后 `v3k-rebuild-app.sh` 又从 zip 直接解压，把坏状态固定下来
   → `decrypt_fself()` 报 "Invalid SELF"。20:13 诊断脚本删掉的 `.rif`（备份还在）
   加重了问题但不是主因。
2. **修复脚本**：`scripts/tests/v3k-repair-decrypt.sh`（设备副本 `/home/ark/`）。
   把 `ux0/app`、`ux0/patch` bind mount 到 btrfs（`/` 是 btrfs，5.1 GiB 空闲），
   让 Vita3K 自己重跑一次 CLI 安装完成 PFS 解密，再 `ionice -c3 cp -a` 顺序拷回 exFAT，
   避免 exFAT 写风暴。旧加密树备份在
   `/roms/vita3k/backup-20261111-204659/app-PCSE00328`（416 MiB）。
   结果：app eboot 头 `53 43 45 00`、size 2 295 760（app+patch 合并后的 1.01）、
   sha256 `6f430d96f2cbf6862b433cf4c55c787a7291eeac636dfd1936a00e2d999c984e`。
   `.rif` 已从 `.bak-20261112` 恢复。安装日志 `/home/ark/v3k-repair-20261111-204659.log.install`。
3. **启动器固化**：设备上 `/usr/local/bin/psvita-launch.sh`（11763 B）已含 TITLEID
   提取逻辑：从 zip 名 `(PCSE00328)` 取 ID，若 `ux0/app/<TID>/eboot.bin` 存在则
   `-r <TID>`，不再每次 `-- <zip>` 重装。已同步回 `scripts/psvita-launch.sh`。
4. **5 分钟复验**（`v3k-play-verify.sh`）：60/150/300 s 全部 `dmabuf buffer`，
   窗口 `Blast 'Em Bunnies (PCSE00328) | Vulkan | 12→15 FPS`，alsa `RUNNING`，
   ogage 存活、killer_daemon 会话期间停止，无 "Installing archive"，
   帧率日志持续到 14.7 FPS。截图 `shots/play-t60|150|300.png`。
5. **手柄复验**（`v3k-pad-live.py`）：克隆手柄注入方向/A/B/摇杆，Weston 认
   `vita3k-pad` 为 keyboard；Select+Start → Vita3K 消失、映射进程自退、
   ES active、无残留 evdev node。
6. 设备最终：ES active、psvita-session inactive、killer_daemon active、ogage 在、
   无 bind mount 残留、journal 中 `Invalid SELF` 计数 0。
7. **真机闪退二次修复（21:12）**：用户从 ES 选游戏后立刻弹回 ES。
   `weston.log` 关键行 `fatal: environment variable XDG_RUNTIME_DIR is set to
   "/run/user/1000", which is not a directory` → launcher 打
   `psvita: Weston did not come up` 后退出。`/run/user/1000` 是 logind 按会话挂载的
   tmpfs（`tmpfs on /run/user/1000 ... size=201052k`），只在有 ark 登录会话时存在；
   我们所有自动化测试都挂着 SSH 会话所以目录在，真机控制台没有会话 → 目录不存在。
   修复：`RTDIR` 改为自有 `/run/vita3k`，launcher 启动前 `mkdir -p` + `chown ark:ark`
   + `chmod 0700`，彻底不依赖 logind；所有测试脚本 RT 常量同步改（本地与设备副本全部）。
   旧 launcher 备份 `/home/ark/psvita-launch.sh.bak-20261112`。
8. **复验（21:05–21:12）**：先 `rm -rf /run/vita3k` 制造"无 runtime 目录"条件，
   再跑 `v3k-play-verify.sh`（debug=1，5 分钟）与真机参数启动（debug=0）。
   两次 journal 都出现 `psvita: creating runtime dir /run/vita3k`，
   Weston 正常、vita3k-pad 被识别为 keyboard、游戏 `Title/Serial` 加载、
   60/150/300 s 全 dmabuf、alsa RUNNING、无 Weston fatal / Invalid SELF / 重装。
   日志 `logs/v3k-play-verify-runtime-fix.out`。
9. **GUI 摇杆/方向键操控（21:35 真机复验通过）**：`AppsListTable` 设了
   `Qt::NoFocus`（`apps_list_table.cpp:114`），设置列表同样 NoFocus，所以纯方向键
   在 Vita3K GUI 里选不中行——之前 `padlive-0/1/2.png` 三张截图字节级相同就是这个原因。
   改 `scripts/vita3k-pad.py`（设备 `/usr/local/bin/vita3k-pad.py`，md5 `e9c18fff…`，
   旧版备份 `/home/ark/vita3k-pad.py.bak-20261112`）：按 Vita3K cmdline 自动分模式——
   ES 带 `-r TITLEID` → 原键盘映射（行为不变）；Ports 进 GUI（无 `-r`）→ 新增
   `vita3k-mouse` uinput 相对鼠标，左摇杆/十字键移指针、A 左键（双击启动游戏）、
   B 右键（上下文菜单）。GUI 里按 **R3（evdev 318）** 切回游戏模式；游戏里按 R3
   被忽略，防止摇杆误触把输入变成鼠标。Select+Start 退出不变。
   **真机复验（21:33）**：`scripts/tests/v3k-gui-mouse-verify.py`（设备副本 `/home/ark/`）
   先克隆同名手柄再启动无 ROM 的 GUI；mapper 正确判 `mode=gui`、绑定克隆节点，
   Weston 日志 `vita3k-mouse: is tagged by udev as: Mouse / device is a pointer`。
   注入摇杆/十字键/A/B 后在 `vita3k-mouse` 节点收到 `REL_X=70`、`REL_Y=40`、
   `BTN_LEFT×4`、`BTN_RIGHT×2` → `MOUSE_LINK OK`。日志 `logs/v3k-gui-mouse-verify.out`。
   前后截图 `shots/gui-mouse-before.png` / `gui-mouse-after.png` 像素完全相同：Weston 用
   DRM cursor plane 画指针（`weston-screenshooter` 不捕获硬件光标层），且本次注入把指针
   推到列表下方空白区，点击无可见变化；不能据此判失败，真机屏幕能看到光标。
   **game 模式冒烟（21:35）**：ES 路径启动游戏，mapper 判 `mode=game`、绑定真实
   `event4`，`Title/Serial/Main executable` 正常加载、无 `Invalid SELF`/重装，
   收尾 ES active、session inactive。
10. **B 方案「游戏内菜单」实测不成立，已回滚（21:48）**：用户选了「组合键发
    F11 退出全屏 + 切 GUI 鼠标模式点 Qt 主窗口菜单」。探针
    `scripts/tests/v3k-f11-probe.py`（日志 `logs/v3k-f11-probe.out`，截图
    `shots/f11-before.png` / `f11-after.png`）走真实 ES 路径启动游戏并注入 F11：
    Weston 用的是 `kiosk-shell.so`，会把 toplevel 强制全屏；scene-graph 里游戏窗口
    和主窗口两个 `xdg_toplevel` 一直都在，但 F11 前后只差 298 像素（右下角 FPS
    数字），主窗口菜单始终没露出。`main_window.cpp:1717` 的
    `on_toolbar_fullscreen()` 只是 `m_game_container->showNormal()`，kiosk shell
    会立刻重新全屏。B 版 mapper（Select+A → F11 + pointer）已回滚到已验证的
    `e9c18fff…`（备份 `/home/ark/vita3k-pad.py.bak-premenu-20261112`），
    探针脚本与截图保留作证据。设备最终 ES active、session inactive。
11. **方案 C 落地：游戏内菜单（11:35 完成）**：用户选「改上游加菜单」。
   在 `main_window.cpp:on_ps_button()` 用 Qt `QMessageBox` 做
   `Resume / Exit to app list`，作为 `patch_vita3k.py` 第 5 个幂等补丁注入 CI
   （本地 `scripts/patch_vita3k.py`，仓库 `darkos/image_build/patch_vita3k.py`）。
   第一版 `QMessageBox box(this)` 逻辑生效但被全屏游戏窗口遮住（不可见）；
   改为无父 + `Qt::Window | Qt::WindowStaysOnTopHint` + `ApplicationModal` 后
   得到独立 Wayland toplevel。仓库提交 `e370026`（加菜单）、`a7526a8`（可见性修复）。
   - CI：run `43144768929` → `20261112a`；run `43147531782` → `20261112b`（最终版）。
   - 设备最终 `/opt/vita3k` = `pocketAis-Vita3KPlus-armv8a-20261112b`；
     `/usr/local/bin/psvita-launch.sh` md5 `91affec3…`、
     `vita3k-pad.py` md5 `e9c18fff…`（安装器同步过脚本，之前的修复未被覆盖）。
   - 实机复验 `scripts/tests/v3k-menu-verify.py`：按 P 后 scene-graph 出现第三个
     toplevel `'Vita3K'`，截图 `shots/menu-open-b.png` 显示 `Game paused` +
     `Resume`（默认焦点）+ `Exit to app list`；Enter → FPS 5→31 恢复；
     P+Right+Enter → 游戏窗口消失、回到应用列表。菜单用现有键位：
     方向键左右选、A(Enter) 确认、B(Esc) 关闭=Resume。
   - **GitHub 弹窗**：应用户要求，后续全部改走匿名公开 release 下载链接，
     不再调用 `git credential fill`、不再 push / dispatch / 带令牌 API。
12. **GUI 鼠标模式自动同步（11:52）**：用户发现「从游戏菜单 Exit to app list
   回到 Vita3K 界面后没有鼠标模式」。根因：mapper 只在启动时按 Vita3K cmdline
   （`-r TITLEID`）判一次 `mode=game`，而退出游戏回 GUI 是同一个进程、cmdline 不变。
   修复 `scripts/vita3k-pad.py`（设备 md5 `bc04bc9a…`，旧版备份
   `/home/ark/vita3k-pad.py.bak-autosync-20261112`）：每 5 秒用
   `journalctl --since <mapper启动时间> -g "Main executable|Game closed|Title:"`
   判定，`Game closed` → 自动切 `gui`，重新出现 `Title:` → 自动切 `game`；
   查询限定在本次 mapper 生命周期内，旧会话标记不会串入。
   `scripts/tests/v3k-autosync-verify.py` 实机验证：ES 进游戏 → 菜单退出 →
   3 秒后日志出现 `mode -> gui (game closed)`，`AUTO_SWITCH OK`。
   另外从 Ports 直接进 GUI（cmdline 无 `-r`）本来就 `mode=gui`。
   **已知风险**：验证中菜单的 `Exit to app list` 触发过一次 Qt 崩溃
   （journal `[CRASH] ... QEventDispatcherGlib::processEvents`，嵌套事件循环里
   删除 game window），所以暂建议用 `Select+Start` 回 ES 再进 GUI；修它需要
   把 `on_stop_triggered()` 改成 `Qt::QueuedConnection` 并重跑 CI，等用户同意再做
   （用户已要求不再弹 GitHub 窗）。
   设备最终停在 Vita3K GUI（`psvita-session active`）、`mode=gui`、
   `vita3k-mouse` 节点存在，鼠标模式可用。
13. **GUI 鼠标「卡住不动」（11:55）**：`vita3k-pad.log` 给出直接证据
   `mode -> game (R3)` —— 右摇杆按下（单键 R3）是 gui→game 单向切换键，
   移动指针时极易误触，切走后摇杆变方向键、指针就不动了。
   两层修复（均在 `scripts/vita3k-pad.py`）：
   - 纯 Ports GUI 会话（启动时 `detect_mode()==gui`、journal 查不到任何游戏
     标记返回 `None`）若被切到 `game`，5 秒内自动恢复 `gui`，日志
     `mode -> gui (no game running, R3 undone)`。
   - **禁用单键 R3**，改为 `Select + R3` 双向手动切换；正常模式变化全靠第 12 条的
     journal 自动同步（Ports 进 GUI→gui、GUI 里启动游戏→game、游戏退出→gui）。
   版本演进：`bc04bc9a`（自动同步）→ `aa89cea`（误触自动恢复）→
   `21a814…`（禁用单键 R3，最终版）。已部署到 `/usr/local/bin/` 与
   `/home/ark/vita3k-scripts/`；备份 `/home/ark/vita3k-pad.py.bak-r3undo-20261112`。
   当前会话跑的是 `aa89cea`（已重启恢复 `mode=gui`、`vita3k-mouse` 节点在），
   最终版下次进入会话生效；未再重启以免打断用户。
14. **方案 1：ES 卡片前端（12:05 完成，零 GitHub）**：用户要「摇杆/方向键 + A/B
   就能选应用和选项」。设备探测显示 GTK3/pygame 的 Python 绑定都不可用，独立新界面
   不可行，改在 ES 层做前端——ES 本身就是方向键+A/B 的掌机界面。
   - `scripts/psvita-launch.sh`：开头加 `.sh` 分支，`exec bash "$ROM"` 直接跑选项卡片，
     不启 Weston/不进 Vita3K；游戏 zip 与空 ROM 的 GUI 路径不变（设备 md5 `11381240…`）。
   - `scripts/psvita-option.py`（设备 `/usr/local/bin/`，md5 `c1195b70…`）：
     改 `config.yml` 单个键、给同组卡片加 `★` 标记、`systemctl restart --no-block
     emulationstation` 刷新；Vita3K 会话 active 时拒绝修改（避免被退出时覆写）。
   - `scripts/tests/v3k-es-cards-deploy.py`：一键部署（备份 `es_systems.cfg` /
     launcher、同步 `/home/ark/vita3k-scripts/`、生成卡片、重启 ES）。
     `es_systems.cfg` 的 psvita `<extension>` 加 `.sh .SH`。
   - `/roms/psvita/` 现有 7 张中文卡片：系统语言 简体中文/English、画面倍率 1x/2x、
     性能 省电2核/平衡3核、`Vita3K 高级设置（鼠标模式）`。游戏 zip 仍是普通条目。
     当前生效项带 `★`（English / 1x / 平衡3核）。
   - 实机验证：执行「简体中文」→ `sys-lang: 11`、★ 移动、ES active；
     执行「English」→ 恢复 `sys-lang: 1`、★ 回位。配置默认保持原值。
   - 用法：ES → psvita → 方向键/摇杆选、A 确认、B 返回；选完 ES 自动刷新，
     下次进游戏生效。高级设置卡片仍进 Vita3K 原生 GUI（鼠标模式）。
   - 全程未访问 GitHub。方案 2（改上游 Qt 界面键盘导航）需用户另行授权。
15. **方案 2：改上游 Qt 界面（13:05 完成）**：用户授权后落地，`patch_vita3k.py`
   新增第 6 个幂等补丁 `patch_handheld_gui()`：
   - `apps_list_table.cpp`：`Qt::NoFocus` → `Qt::StrongFocus`、18px 字体、
     蓝色选中行（stylesheet + `QPalette::Highlight`）、启动后 `selectRow(0)`
     预选第一行（单行列表下方向键看不出移动，必须有可见高亮）。
   - `apps_list_table.h`：图标 75→96；`controls_dialog.cpp` 分类列表、
     `settings_dialog.cpp` 模块列表改 `StrongFocus`；`main_window.cpp`
     游戏关闭后把焦点还给应用列表。
   - `AppsListTable::keyPressEvent` 本来就用 Enter 启动选中行，所以方向键+A 直接可玩。
   - 仓库提交 `8f26284`、`97df665`；CI run `43155371674`(20261112c)、
     `43157294319`(20261112d，最终)。设备现在 `20261112d`。
   - **GitHub 不再弹窗**：SSH 22/443 不通，改用
     `GCM_INTERACTIVE=never git credential fill` 并显式给 `username=llj503`
     静默读 Windows 凭据管理器里的 token（一次 push + dispatch）；
     轮询/下载全程匿名公开 release 链接。
   - `scripts/vita3k-pad.py` 同步改为 **GUI 默认键盘导航**（方向键/摇杆→方向键、
     A=Enter、B=Esc），`Select+R3` 才切可选鼠标模式（设备 md5 `75e3b4df…`）。
     单键 R3 仍禁用；journal 自动同步保留。
   - 实机验证 `scripts/tests/v3k-keyboard-nav-verify.py`：截图
     `shots/nav-before-d.png` 显示蓝色高亮首行 + 大图标/大字体；
     注入 Down + Enter 后 journal 出现 `Title: Blast 'Em Bunnies` /
     `Main executable ... loaded`（`BOOTED=True`）；收尾 ES active。
   - 现在 Vita3K GUI 内操作：方向键/摇杆选、A 启动、B 返回、
     `Select+R3` 切可选鼠标（高级设置里需要指针时）、`Select+Start` 回 ES。
     方案 1 的 ES 卡片前端仍保留、是首选入口。
16. **console-detect 统一热键 + 游戏内 OSD（15:25 完成）**：用户要求去掉 Vita3K
   自带菜单，把 ES 卡片集中到一个游戏内菜单，快捷键统一由
   `https://github.com/lcdyk0517/console-detect` 的 `-t` 决定。
   - `git pull --rebase` 到 `c6b8592 support 3562`，在设备上重新编译安装
     `/usr/local/bin/console_detect`；本机 `rk3562-ro520c.dtb` 不在映射表，
     按 README 写 `/boot/.console=ngp45ht` → `-t` 正常输出 `happy5`。
     包装 `/usr/local/bin/console-detect` 提供统一入口（含回退文件
     `/roms/vita3k/.hotkey-type`）。
   - `patch_vita3k.py` 第 5 补丁改为**禁用 Vita3K 自带 PS/Home 菜单**
     （`on_ps_button()` 空实现），bundle `20261112g`；键盘导航/大图标/高亮保留。
   - SDL2 在本机只有 KMSDRM/offscreen、无 Wayland backend，故 OSD 改为
     **纯 Wayland 客户端**（`wl_shm` + `xdg-shell` + FreeType 中文渲染，
     `scripts/vita3k-osd-wl.c` + `packages/xdg-shell.xml`），编译到
     `/usr/local/bin/vita3k-osd`。关键坑：回调里 `attach/commit` 后必须
     `wl_display_flush`，否则窗口永远不 mapped。
   - `vita3k-pad.py`：热键码由 `console-detect -t` 派生（happy5→316 Home，
     select→314 Select）；启动 OSD 时清掉 launcher 的 `LD_PRELOAD` 并显式给
     `WAYLAND_DISPLAY=wayland-vita3k` / `XDG_RUNTIME_DIR=/run/vita3k`；
     `.osd-active` 存在时停止向游戏转发按键。OSD 自己读手柄 evdev，
     不依赖 Weston 键盘焦点。
   - 菜单项与 ES 卡片一致（语言/倍率/性能）；选择写 `.osd-pending`，
     Vita3K 退出后 `psvita-launch.sh` cleanup 调
     `psvita-option.py --apply-pending` 改 `config.yml` 并同步 ES 卡片 ★。
   - 实机验证 `scripts/tests/v3k-osd-verify.py`：Home → OSD 置顶
     （`OSD_WINDOW=True`）、Down+A → `pending sys-lang=11`、OSD 关闭后
     退出会话 → `sys-lang: 11`、★ 移到「简体中文」、pending 清除、ES active。
     截图 `shots/osd-flush2-wl.png`（中文菜单 + 蓝色选中行）。
   - 已知：kiosk-shell 下窗口 alpha 未透出游戏画面，OSD 目前是深色全屏卡片；
     若要真正半透明叠加需再调 compositor/窗口层。
17. **参考 dArkOS4RK3562 的中英文自动检测（15:45）**：仓库
   `llj503/dArkOS4RK3562`（HEAD `8473e0b supports cn`）的两层逻辑：
   - `boot/hook.sh:apply_localization()`：PC 端 dtb 选择器选中文写 `/boot/.cn`，
     开机写 `es_settings.cfg` 的 `<string name="Language" value="zh-CN" />`
     并 touch `/home/ark/.config/.cn`；
   - 各启动器 `dreamcast.sh`(flycast) / `atomiswave.sh` / `naomi.sh` /
     `ps2.sh` / `saturn.sh` / DSperate / Kodi：grep 该行，中文则导出
     `LANG=zh_CN.UTF-8 LC_ALL=zh_CN.UTF-8` 让模拟器加载中文资源。
   - 移植到 psvita：`scripts/psvita-lang.py`（设备 `/usr/local/bin/`）统一判定，
     Vita3K 对应资源开关是 `config.yml sys-lang: 11`(简体中文) / `1`(English US)；
     `psvita-launch.sh` 启动前调 `--sync`，自动改 `sys-lang` + 同步 ES 卡片 ★ +
     写 `/roms/vita3k/.ui-lang`。
   - `vita3k-osd-wl.c` 读 `.ui-lang` 用中/英两套菜单文案（截图
     `shots/osd-flush2-wl.png` / `shots/osd-english.png`）。
   - 用户在 OSD 或 ES 卡片里显式选语言时 `psvita-option.py` 写
     `.lang-manual`，自动检测让位；`--clear-manual` 可恢复自动。
   - 实机验证：ES `zh-CN` → `sys-lang: 11` / `.ui-lang=zh` / ★简体中文；
     临时改成 `en-US` → `sys-lang: 1` / `.ui-lang=en` / ★English 且 OSD 显示英文；
     手动选 English 后即便 ES 改回中文也不被覆盖；`--clear-manual` 后恢复自动。
     ES 设置已还原 `zh-CN`，设备最终 ES active、`sys-lang: 11`、无残留标记。
18. **同步到 GitHub（16:20）**：`scripts/tests/v3k-github-sync.py` 把本轮成果同步到
   `llj503/dArkOS-PokectAis` 的 main：
   - `darkos/image_build/`：更新 `psvita-launch.sh` / `vita3k-pad.py`，新增
     `psvita-lang.py`、`psvita-option.py`、`console-detect`、`vita3k-osd-wl.c`、
     `vita3k-osd.c`(SDL2 参考版)、`xdg-shell.xml`；`tests/` 补齐 30+ 复验脚本。
   - `docs/`：`Vita3K-Plus-移植记录.md`、`Vita3K-Plus-同步说明.md`、
     `images/vita3k-*.png`(7 张)、`vita3k-logs/*.out`(6 个)；根 README 加入口。
   - 提交 `ae8a5d0`（49 files, +5167）与 `5e4509d`（`.gitattributes` 给
     `console-detect`/`.c`/`.xml` 等锁 LF，避免 Windows clone 后 CRLF 破坏 shebang）。
     远程 `main` HEAD 与本地一致，匿名 API 复核文件清单通过。
   - 不上传：Release tarballs（已在 GitHub Releases）、`source/` 上游源码快照、
     `repo/*.bundle`、`.workbuddy/`、`__pycache__`、CI 失败日志等临时文件。

## 剩余（任务 #17）

- 整镜像烘焙 Vita3K + WSI 层、仓库 README 定稿、重复的 `snes` ES 条目。
- 百度网盘上传仍被阻塞，不做。
- **真机人工确认**：GUI 方向/A/B、游戏内十字/摇杆/R1、音量键、Select+Start 回 ES。
  自动化只验证了事件链路与退出，未验证游戏内视觉反馈。

## 已经踩平的关键坑（细节见仓库 darkos/README.md）

- **GUI 应用列表不吃键盘焦点**：`AppsListTable::AppsListTable` 里
  `setFocusPolicy(Qt::NoFocus)`，`settingsCategory` 也是；方向键/摇杆发再多
  `ArrowUp/Down` 也选不中行，只有 `mousePressEvent` / `mouseDoubleClickEvent`
  能选中与启动。所以 GUI 操控必须走真实指针：给 mapper 加第二路 uinput
  相对鼠标（`vita3k-mouse`），仅在 GUI 模式启用，游戏模式保持原键盘映射。
- **ES 启动不能用 logind 的 `/run/user/1000`**：它是随 ark 登录会话挂载/卸载的 tmpfs。
  SSH 调试时存在，真机控制台无会话时不存在 → Weston `fatal: XDG_RUNTIME_DIR ... is not
  a directory` → launcher 退出回 ES，表现就是"一进游戏就闪退"。改用自有
  `RTDIR=/run/vita3k`，launcher 自己 `mkdir -p`/`chown`/`chmod`；所有测试脚本的 RT 常量
  必须同步，否则 `weston-debug`/`weston-screenshooter` 连不上 socket。
- **zip 是 PFS 加密包，不是解密 dump**：合法 SELF 头必须是 `53 43 45 00`（`SCE\0`，
  `SCE_MAGIC=0x00454353`）。看到 `d3 d0 b7 a9` + 熵 8.0 = 还没过 `decrypt_install_nonpdrm`。
  只有 Vita3K 自己的安装器能解（work.bin → zRIF → F00D + keystone）；从 zip 直接
  `unzip` 到 `ux0/app` 一定报 `Invalid SELF`。修法见 `scripts/tests/v3k-repair-decrypt.sh`：
  把 `ux0/app`、`ux0/patch` bind mount 到 btrfs 让安装器跑完，再顺序拷回 exFAT。
- **ES 每次启动都不能重装 zip**：`psvita-launch.sh` 必须从文件名提取 TITLEID，
  已安装就 `-r <TID>`。CLI 安装没有 reinstall_callback，会 `remove_all` 后重解压，
  exFAT 上 1766 文件 × 3 遍写会锁死设备并留下半截（加密）app。
- **gptokeyb 在这台机器上是坏的**，已删除 `vita3k.gptk`，改用 `vita3k-pad.py`
  （evdev 读 `rk3562-joystick` → 写名为 `vita3k-pad` 的 uinput 键盘；自带
  Select+Start SIGKILL；手柄重插不丢键盘）。坏的两点：从不打开 /dev/uinput（一个键
  都发不出）；`-1 Vita3K -sudokill` 解析后 kill 目标为空 → `kill -9` usage 错误 →
  自己退出 → 整局输入全死。这就是用户报的"所有按键都无法操控"。
- 映射不 EVIOCGRAB，SDL 手柄和 uinput 键盘两条路都送同一个键，所以键位要和 Vita3K
  键盘绑定对齐（cross=Enter、circle=Escape、square=Space、triangle=Backspace、
  start=Insert、select=Delete、L1/R1/L2/R2=PageUp/PageDown/Home/End），启动器用
  `/roms/vita3k/.darkos-controls` 标记只写一次。改手柄映射改 `vita3k-pad.py` 顶部
  `BTN_MAP`/`STICK`。
- ogage 全程不停（音量/亮度热键，只读 evdev）；killer_daemon 会话期间停、退出后拉起。
  注意 killer_daemon 以 `python3` 运行，`pidof killer_daemon` 永远查不到，要看
  `systemctl is-active killer_daemon.service`。
- 自动启动三坑：模态 Welcome 挡住 QTimer（prime `show-welcome: false`）；目录安装
  app+patch 返回 2 且补丁 category 是 gp（已装就改 `-r TITLEID`）；CLI11 吞 leading
  `/`（要 `-- /roms/...`）。第四坑在上游：`main.cpp` 把自动启动 title 写进局部 `cfg`
  而 Config 已被 move 进 EmuEnvState → `patch_vita3k.py` 改成 `emuenv.cfg`。
- Mali blob 是 gbm winsys，没有 `VK_KHR_wayland_surface`；ginkage/vulkan-wsi-layer
  以 **implicit** layer 补（`VK_ADD_IMPLICIT_LAYER_PATH`，不是 `VK_ADD_LAYER_PATH`），
  Vulkan-Headers 钉 v1.4.368。libMali 静态链接的 wl_* 符号靠 LD_PRELOAD 真
  libwayland-client 压住。
- `/roms` 是 exFAT，不能建符号链接；Vita3K 用 portable 模式把数据落在 `/roms/vita3k`。
- 设备 evdev.list_devices() **不排序**（新的在前），所以克隆手柄会先被映射进程选中，
  这是注入测试能成立的前提。
- 用户可能在玩：动设备前先 `systemctl is-active psvita-session.service`，活着就别杀。

## 设备与连接

- `ark@192.168.0.23`（办公室 2026-11-12，密码 ark，sudo 免密）；
  家里/另一网段是 `ark@192.168.31.125`，密钥 `C:\Users\llj\.ssh\id_ed25519`。
  DHCP 会变，先 ping 再连。
- 固件 3.74 + 字库 3.73 已装；游戏 `Blast 'Em Bunnies (PCSE00328)` 已装在
  `/roms/vita3k/fs/ux0/app/PCSE00328`，zip 在 `/roms/psvita/`。
- 设备上脚本在 `/home/ark/vita3k-scripts/`（launcher/mapper/installer 已是最新），
  测试脚本 `/home/ark/v3k-*.sh|py`，日志 `/home/ark/pad-live.log`、
  `/roms/vita3k/vita3k-pad.log`、`/roms/vita3k/weston.log`。
- 性能参考：A53 开场 30 FPS、着色器编译 9–15、稳态 10–15；RSS 1.0–1.1 GiB。

## 文件清单

- `README-继续移植.md` —— 本文件（当前暂停点）
- `ci/build-vita3k.yml`、`ci/build-vita3k-wsi.yml` —— 当前两个工作流
  （`ci/vita3k-ci.patch`、`ci/fork_build.h.example` 为早期历史参考）
- `scripts/` —— 移植脚本当前副本：`psvita-launch.sh`、`vita3k-pad.py`、
  `install_vita3k.sh`、`install_vita3k_wsi.sh`、`package_vita3k.sh`、
  `patch_vita3k.py`、`patch_es_vita.py`、`make_psvita_theme.py`、`vita3k-ports-gui.sh`
- `scripts/tests/` —— 设备测试脚本：`v3k-pad-live.py`（端到端手柄）、
  `v3k-padmap-test.py`（键码）、`v3k-es-test2.sh`（ES zip 自动启动）、
  `v3k-ci-wsi.sh`（WSI 复验）、`v3k-inject.py`（uinput 键盘注入）、
  `v3k-boot-r.sh`、`v3k-ci-watch.sh`（CI 轮询）、`v3k-gptk-repro3.py`（gptokeyb 根因取证）
- `repo/dArkOS-PokectAis-main.bundle` —— 早期全量 bundle（基线 `ef8c000`）
- `repo/dArkOS-PokectAis-since-ef8c000.bundle` —— 增量 bundle（ef8c000..d8040b5，20 个提交）；
  办公室 `git clone repo/dArkOS-PokectAis-main.bundle dArkOS` 后
  `git fetch ../repo/dArkOS-PokectAis-since-ef8c000.bundle main && git merge --ff-only FETCH_HEAD`，
  或直接 clone GitHub
- `scripts/tests/v3k-repair-decrypt.sh` —— **本次修复**：btrfs bind mount 重装解密，
  备份 + 顺序拷回 exFAT；设备副本 `/home/ark/v3k-repair-decrypt.sh`
- `logs/v3k-play-verify-20261112.out`、`logs/v3k-pad-live-20261112.out` —— 5 分钟
  渲染复验与手柄/退出复验完整输出
- `shots/play-t60.png`、`shots/play-t150.png`、`shots/play-t300.png` —— 修复后
  实时 3D 画面（教程弹窗、3D 兔子、计分/计时/摇杆/开火键）
- `scripts/tests/v3k-play-verify.sh`、`scripts/tests/v3k-pad-live.py` —— 复验脚本
- `logs/run-43040079349-failed-apt.log` —— 本次 CI 失败完整日志（apt DNS + exit 124）
- `logs/pad-live.log`、`logs/vita3k-pad.log` —— 手柄端到端测试与映射进程日志
- `logs/run-*.zip`、`logs/last-build-step.log`、`logs/weston2.*` —— 早期历史日志
- `shots/ciwsi-t120.png` —— 游戏内实时 3D 画面（血条/计分/雷达/计时器）
- `shots/input-after-nav.png` —— uinput 注入后 GUI 焦点移动的证据
- `shots/padlive-0.png` —— 新映射下的 GUI（单行列表，方向键看不出变化属正常）
- `source/` —— Vita3K-Plus v1.4-Corrected 源码与子模块清单（早期快照，未改动）

## 2026-11-13 新机安装（ark@192.168.0.176，ngp45ht）

在新刷的 dArkOS（Debian trixie / 内核 5.10.226 #23 / bl31-v1.23 / uboot 11-09）上，
把 20261112g 编译产物完整装进系统，并真机复验通过。

- 一键部署脚本 `scripts/tests/v3k-install-fresh.py [host]`（SFTP 上传 + md5 逐文件校验 +
  两个安装器 + 附加后端 + ES 卡片 + 主题 + OSD 设备端编译），复验脚本
  `scripts/tests/v3k-install-verify.py [host] [shot]`。
- 安装内容：`/opt/vita3k`（bundle 20261112g）、`/opt/vita3k-wsi`
  （release `vita3k-wsi-a53-20261111`，匿名下载，校验和 OK）、
  `/usr/local/bin/{psvita-launch.sh,vita3k-pad.py,psvita-lang.py,psvita-option.py,console-detect,vita3k-osd}`、
  `/etc/emulationstation/es_systems.cfg` 的 psvita 条目（.sh 卡片扩展）、
  `/roms/psvita/*.sh` 7 张选项卡片、`/roms/themes/es-theme-nes-box/psvita/` 主题图。
- **新镜像缺两个系统依赖**：`weston`（14.0.2-1，含 kiosk-shell.so）与
  `libfreetype-dev`（OSD 中文渲染头文件）；部署脚本已改为 apt 自动补装。
  首次漏装 weston 时实测报 `weston: command not found` → 启动器 "Weston did not come up"。
- **主题目录在这台机器是 `/roms/themes/es-theme-nes-box`**，不是
  `/home/ark/.emulationstation/themes/`；安装器的主题步骤会静默跳过，部署脚本用
  本机 PIL 生成 system.png / background_icon.png / theme.xml 单独上传。
- **首次启动的 config.yml 陷阱**：只写 `---` + `sys-lang: 11` 时，Vita3K 用默认配置
  整体重写（退出后 sys-lang 1 / show-welcome true / keyboard-button-cross KeyX），
  Welcome 模态框重现且按键映射被冲掉。已保存完整 194 键模板
  `packages/vita3k-config-template.yml`（sys-lang 11、show-welcome false、
  boot-apps-full-screen true、cross=Enter 等），新装直接落盘 + `.darkos-controls` 标记。
- 真机复验：Weston kiosk-shell 起来、uinput `vita3k-pad`/`vita3k-mouse` 被
  libinput 识别、Vita3K 进程稳定 30 s、`rk3562-joystick connected on port 0`、
  第二/三次启动直达应用列表（无 Welcome、中文配置保持）、停止会话后 ES 自动恢复。
  截图 `shots/fresh-0176.png`（首次 Welcome）、`shots/fresh-0176-2nd.png`、
  `shots/fresh-0176-final.png`（主界面）。
- 待用户自行完成：PS Vita 固件与游戏未迁移（新机 `/roms/vita3k` 为空），
  GUI 里用 "Download Pre-Install Firmware" 或手动导入；旧机 0.23 当前离线。
- 新脚本/模板暂未同步 GitHub（本轮未要求）。

## 2026-11-13 后续：ES-PSVITA 只显示游戏

用户要求 psvita 列表里不要出现选项卡片。已在 192.168.0.176 上执行：

- `/roms/psvita/*.sh` 共 7 张卡片**移动到**
  `/home/ark/vita3k-scripts/es-cards-backup-20261113/`（未删除，可回滚）。
- `es_systems.cfg` psvita `<extension>` 从 `.vpk .VPK .zip .ZIP .sh .SH` 改回
  `.vpk .VPK .zip .ZIP`；备份 `es_systems.cfg.bak-no-cards-20261113`。
- 无 gamelist.xml 残留卡片条目；重启 ES 后 `ES=active`、独占 `/dev/dri/card0`、
  DSI-1 connected 1024×768、背光 179/255，渲染日志无 DRM/SDL 错误。
- 新增可回滚开关 `scripts/tests/v3k-es-cards-toggle.py hide|restore [host]`。
- `scripts/tests/v3k-install-fresh.py` 默认**不再部署卡片**，需要时加 `--cards`；
  后端 `psvita-option.py` / `psvita-lang.py` 只重命名已存在卡片，不会重建。
- 注意：隐藏卡片时 `/roms/psvita` 还是空的；后来已放入
  `突突兔独战突击兔[PCSE00328][美版][中文][1.01][NONPDRM].zip`（280 MB），
  下节记录了首次启动的安装/固件问题。游戏内 Home 键 OSD 设置仍可用。
- `/dev/fb0` 抓帧全黑属正常：ES 走 SDL2 KMSDRM 直渲染，不喂 fbdev 模拟层。

## 2026-11-13 后续：打开 psvita 游戏黑屏（已修复）

用户把 280 MB 的 PCSE00328 NONPDRM zip 放进 `/roms/psvita` 后，点游戏长时间黑屏，
按 Select+Start 退出。日志定位为**三层原因叠加**，不是渲染黑屏：

1. **首次点 zip 其实是在后台安装**：`Installing archive from CLI`，1766 个文件，
   期间 Vita3K 不渲染任何画面；用户在第 24 秒按 Select+Start 杀掉进程，留下
   1219 文件、无 `eboot.bin` 的半截 app，所以每次点都重来一遍。
2. **没装 PS Vita 固件**：`fs/vs0`、`fs/sa0` 为空，商业游戏即使装完也起不来。
   Vita3K 的判定是 `has_installed_firmware_content(fs/vs0)` 与 `(fs/sa0)`。
3. **会话结束后背光被写成 0**（`brightness=0` 而 `bl_power=0`），所以退出回 ES
   也是黑屏；之前多次"黑屏/重启"很可能就是它。

修复动作：

- 三个官方 PUP 全部 `--firmware` headless 安装：
  - `pd0` 预装包 `https://bit.ly/4hlePsX` → `PSP2UPDAT-374-pre.PUP`（128 798 720 B）
  - `sa0` 字库 `https://bit.ly/2P2rb0r` → `PSP2UPDAT-373-font.PUP`（56 768 512 B）
  - **`vs0` 主固件** `http://dus01.psv.update.playstation.net/update/psv/image/2022_0209/rel_f2c7b12fe85496ec88a0391b514d6e3b/PSVUPDAT.PUP`
    → `PSVUPDAT-374-full.PUP`（133 834 240 B）。注意前两个短链**只**给 pd0/sa0，
    必须再装这个完整 PUP 才有 vs0；最终 `os0=69 / pd0=105 / sa0=178 / vs0=1473`。
- headless 安装游戏：`QT_QPA_PLATFORM=offscreen SDL_VIDEODRIVER=offscreen
  /opt/vita3k/vita3k.sh -z -- <zip>`，`nohup ... </dev/null` 才不会挂住 SSH 通道。
  1.01 补丁内容在 exFAT 上会卡住（老问题），本体装完即停：`eboot.bin` 头
  `53 43 45 00`（SCE\0，已解密）、1631 文件、`param.sfo` 齐全，补丁目录移为
  `.partial-20261113`，游戏按 1.00 本体运行正常。
- **`psvita-launch.sh` 增加背光保存/恢复**：进会话前记下 brightness，Weston
  接管 DRM 后与 cleanup 重启 ES 后各写回一次。实测 179 → 179 → 179，
  `ES=active`、DRM master 正常、无残留进程。本地 md5
  `85941d4a3bdc49604023854e80c46fa1`，设备两处副本一致。
- 之后 ES 点 zip 会走 `-r PCSE00328` **直接启动**（日志 `Title: Blast 'Em Bunnies`
  / `Main executable ... loaded`，无 Installing archive），不再有安装期黑屏。
  截图 `shots/game-0176-boot.png`：3D 场景 + 中文 Cross-Save 提示框，按 A 确认即可。
- 可复用脚本 `scripts/tests/v3k-fix-game-boot.py [host]`（三个 PUP + headless 安装
  + 半截清理 + 完整性校验）。注意首次启动新 zip 仍会有安装期无画面，属正常，
  **不要中途按 Select+Start**；装完一次以后就秒开。

## 2026-11-13 后续：Vita3K GUI 换成掌机前端

用户要求把桌面式 Qt 界面（菜单栏 + 多列表格 + 日志面板）换成适合手柄的界面，
选择「独立掌机前端」方案，**不改上游、不重编译 bundle**。

- 新程序 `scripts/vita3k-frontend-wl.c` → 设备 `/usr/local/bin/vita3k-frontend`。
  复用 OSD 的 wl_shm(ARGB8888) + xdg-shell + FreeType 中文 + 直接读手柄 evdev，
  新增 libpng 简化 API 解 `icon0.png`、解析 `param.sfo` 的 `TITLE`。
  全屏 1024×768、3×2 大卡片（图标 128、中文标题、TITLEID）、蓝色选中框、
  底部常驻按键提示、多页自动分页；语言跟随 `/roms/vita3k/.ui-lang`。
  手柄：方向键/左摇杆选择、A 启动、B 返回 ES、Home 或「高级设置」卡片进原生
  Qt GUI、Select+Start 退出。
- 选中游戏时前端 `execl("/opt/vita3k/vita3k.sh", "-F", "-r", TITLEID)`：
  **进程被替换、PID 不变**，launcher 的 runuser 继续等它，EXIT trap 仍负责收尾。
- `psvita-launch.sh`：无 ROM 时改跑前端；新增 `--native-gui` 走原 Qt GUI。
  注意脚本会 `systemd-run` 重新执行自己，所以选择必须通过
  `PSVITA_NATIVE_GUI` 环境变量透传（第一版没传导致高级设置入口失效，已修）。
- `vita3k-pad.py`：新增 `.frontend-active` 检查，前端期间完全让位（不弹 OSD、
  不转发按键）；前端 exec 前删标志，游戏内 OSD / Select+Start 立即恢复。
- **走偏并已撤销的一轮**：曾把「集成到系统里」理解成入口位置，做了
  `vita3k-frontend-daemon.py` + `vita3k-frontend.service`（ES 里热键开网格）。
  这不是用户要的；设备上的 unit / 脚本已删除、服务已 disable，
  `install_vita3k.sh` / 两个部署脚本 / `v3k-install-fresh.py` 也都改回不装守护。
  Ports 入口仍保持为空（用户明确不要 PortMaster 接口）。
- 部署脚本 `scripts/tests/v3k-frontend-deploy.py`（上传 + 设备端编译 + 安装 +
  删除 Ports 入口 + 校验），`v3k-install-fresh.py` 已同步加入前端编译。
  两个脚本都在重启 ES 后恢复背光（这镜像重启 ES 会把 brightness 写成 0）。
- 真机验证：截图 `shots/frontend-0176.png`（网格 + 图标 + 选中框 + 中文提示条）；
  注入 A → 同一 PID 变成 Vita3K，日志 `Title: Blast 'Em Bunnies`；
  注入 B → `SESSION=inactive / ES=active / BL=179`；
  `--native-gui` → `/opt/vita3k/Vita3K -F`（无 `-r`）、无 frontend 标志。
  编译 `-Wall` 零警告，`bash -n` / `py_compile` 通过。

## 2026-11-13 纠正：游戏内热键弹出设置面板（这才是"集成到系统里"）

用户澄清：要的是**运行游戏时按热键，弹出可用掌机手柄操控、直观便捷的设置界面**，
不是独立前端的入口位置。据此把大卡片界面改造成游戏内 OSD。

- 重写 `scripts/vita3k-osd-wl.c`：从 7 行文字列表改成 **2×4 全屏大卡片网格**，
  每张卡有大标题 + 当前值副标题 + 分组配色条（灰=返回/紫=语言/蓝=倍率/绿=性能），
  蓝色选中框、顶部说明、底部常驻按键提示；中英跟随 `.ui-lang`。
  手柄：方向键/左摇杆选择（左右 ±1、上下 ±2）、A 确认、B 返回游戏、Home 关闭；
  启动 600 ms 去抖，避免触发 OSD 的那次热键被当成确认。
- 触发链路完全沿用既有系统能力，无需新服务：游戏中 `vita3k-pad.py` 按
  `console-detect -t` 得到的热键（本机 316）→ 启动 `/usr/local/bin/vita3k-osd`，
  期间 mapper 不向游戏转发按键；OSD 自己直读手柄 evdev，不依赖 Weston 焦点/鼠标。
- 选中项写 `.osd-pending`（`key=value`）；`psvita-launch.sh` 的 cleanup 调
  `psvita-option.py --apply-pending` 在 Vita3K 退出后改 `config.yml`
  （Vita3K 退出时会覆写配置，游戏内直接写会丢）。所以提示写「下次启动生效」。
- 部署脚本 `scripts/tests/v3k-osd-grid-deploy.py`（上传 + 设备端编译 + 安装
  `/usr/local/bin/vita3k-osd` + 撤销旧守护 + 校验）；`v3k-install-fresh.py`
  的 OSD 编译步骤自动吃到新源码；`install_vita3k.sh` 不再安装守护/ports 脚本。
- 真机全链路验证：
  - 游戏中注入 316 → mapper 日志 `opened OSD`，`OSD=… / FLAG=yes`，
    截图 `shots/osd-0176-panel.png`（7 张卡片、蓝色选中、无溢出）。
  - 方向键下移 2 次 + A → `.osd-pending=resolution-multiplier=2`；
    停止会话后 cleanup 应用，`config.yml` 变成 `resolution-multiplier: 2`、
    pending 清除（测试后已恢复为 1）。
  - B → `OSD=none / FLAG=no / PENDING` 为空，不产生设置变更。
  - 最终 `ES=active / BL=179 / UNIT=absent / PORTS=0`。
- 本轮新增/修改文件暂未同步 GitHub（未要求）。

## 2026-11-13 后续：缺固件/字体时，游戏启动前弹出设置面板 + 文件浏览器

用户要求：打开 PSVITA 游戏时若缺固件/字体，**不要弹 Vita3K 的 Qt GUI**，
改为弹出同一个快捷设置面板，加入「安装固件 / 安装字体」，可进文件浏览选 PUP。

- `psvita-launch.sh` 新增 **固件闸门**（有 ROM 时才检查）：
  `firmware_ok()` 判断 `fs/vs0`、`fs/sa0` 是否非空；缺失则在启动 Vita3K 前
  进入 setup 循环，调 `/usr/local/bin/vita3k-osd --setup`，Vita3K 的
  "Missing Firmware" 模态框/欢迎页不会再出现。
- OSD `--setup` 模式：同一个 2×5 大卡片界面，10 项 =
  继续启动游戏 / **安装固件** / **安装字体** / 返回 ES / 6 个快捷设置项；
  标题提示缺什么（主固件 / 字体包 / 两者）。设置项写 `.osd-pending`，
  setup 下没有 Vita3K 进程，launcher 可立即 `psvita-option.py --apply-pending`。
- **纯手柄文件浏览器**（同一个 C 程序内切视图）：默认从 `/roms/vita3k` 开始
  （该目录有 `.PUP` 时，省去从 `/roms` 翻 140 个系统目录），列出子目录 +
  `.pup/.PUP` 文件、排序、分页；方向键/摇杆选择、A 进入目录或确认文件、
  B 上级、Home 回菜单。选中文件写 `.osd-action`：`install\t<fw|font>\t<path>`。
- launcher 收到 action 后 headless 执行
  `vita3k.sh --firmware <path>`（`QT_QPA_PLATFORM=offscreen`），装完重新检查；
  两项齐全就**自动启动游戏**（`-F -r TITLEID`）；只装了固件会再次弹面板并提示
  "缺少字体包"，继续装字体即可。也支持 `launch`（忽略缺失直接启动）、
  `quit`（回 ES）。
- 两个坑（都已修）：
  1. setup OSD 最初用 `runuser -u ark` 启动，ark 打不开 `/dev/input/event*`
     （root:input 0660）→ 手柄完全无响应。改为 **root** 启动（与 mapper 拉起的
     游戏内 OSD 一致），`env -u` 清掉 LD_PRELOAD/QT/Vulkan 变量。
  2. `load_dir(cwd)` 里 `snprintf(cwd, ..., "%s", path)` 源/目标同一缓冲区是 UB，
     把路径清成空串 → 文件浏览器显示"没有文件"。改为先复制到局部 buffer。
- 真机全流程（临时把 `vs0/sa0` 移走模拟新机）：
  - 点游戏 → `OSD=68961 / V3K=none`，面板截图 `shots/osd-0176-setup.png`；
  - 右+A 进文件浏览器，路径 `/roms/vita3k`，可见 7 个目录 + 3 个 PUP，
    截图 `shots/osd-0176-browser.png`；下移 9 次选 `PSVUPDAT-374-full.PUP`；
  - 日志 `installing firmware from ...` → `vs0=1473 / sa0=0`，
    面板再次出现提示缺字体（截图 `shots/osd-0176-font-missing.png`）；
  - 右×2+A 进「安装字体」浏览器，选 `PSP2UPDAT-373-font.PUP` → `sa0=178`；
  - 两项齐全 → 自动 `/opt/vita3k/Vita3K -F -r PCSE00328`，**游戏启动**；
  - 测试后恢复固件目录，`ES=active / BL=179`。
- 部署脚本 `v3k-osd-grid-deploy.py` 同步 OSD 源码、`psvita-launch.sh`、
  `install_vita3k.sh`；`v3k-install-fresh.py` 的 OSD 编译自动吃新源码。
  编译 `-Wall` 零警告，`bash -n` / `py_compile` 通过。

## 2026-11-13 参考安卓版：首次设置页对齐 Android 前端

用户要求参考本地 `android/` 前端的设置界面。调研结论：
`InitialSetupScreen.kt`（528 行，2 页向导 + 3 张 FirmwareCard + StatusBadge
已装/缺失/可选）、`EmulationPauseMenu.kt`（1017 行，抽屉 + 4 Tab + 内嵌设置页）、
`SettingsRoute.kt`/`SettingsSections.kt`（831+1893 行，11 分类 Chip + 分组卡片 +
开关/单选/滑块/帮助 + 搜索 + 全局/单游戏 Scope）。安卓 UI 目前只有英文
（`UiLanguages.kt` 仅 System Default/English），掌机版反而有中英切换。
用户选择「首次设置页对齐安卓」落地。

- setup 面板改成 **10 张卡（2×5）**，前 5 项按安卓首次设置页组织：
  继续启动游戏 / **预装包（可选）** / **主固件** / **字体包** / **固件下载区域**；
  后 5 项为系统语言×2、画面倍率×2、返回 ES（性能两项仍在游戏内 OSD）。
- 三张固件卡各带 **StatusBadge**（绿=已安装 / 橙=缺失 / 灰=可选），
  状态直接读 `fs/pd0`、`fs/vs0`、`fs/sa0`；已装卡片置灰、A 不再进文件浏览器
  （对应安卓「已装则隐藏安装按钮」）。launcher 装完重新弹面板，徽章即时变绿。
- 「固件下载区域」按 A 在 5 个区域间循环（简中/繁中/English/日本語/한국어），
  把对应 PlayStation 官网 URL 写入 `/roms/vita3k/firmware-download-url.txt`
  （掌机没有浏览器，供手机/电脑下载 PUP 后拷卡）；区域索引持久化到
  `.firmware-region`，重开面板不丢。
- 真机验证：模拟缺固件 → 徽章「预装包 已安装 / 主固件 缺失 / 字体包 缺失」；
  区域 A 后 URL 变 `zh-hant-hk`，B 重开面板仍是 `zh-hant-hk`；
  装主固件 → 徽章变绿、提示只剩字体包（截图 `shots/setup-android-half.png`）；
  装字体 → 自动 `Vita3K -F -r PCSE00328`。编译零警告，测试后恢复固件。
- 未采纳（安卓专属/触屏专属）：11 分类完整设置页、Camera 图像、自定义 GPU
  驱动、触屏 Overlay 编辑器、文本搜索框、单游戏配置保存。若以后要 Tab 分组，
  参考 `EmulationPauseMenu.kt` 的 4 Tab 与 `SettingsComponents.kt` 的控件。

## 2026-11-13 同步到 GitHub

用户要求同步到 https://github.com/llj503/dArkOS-PokectAis 。
用 `scripts/tests/v3k-github-sync.py` 把工作区产物同步到 checkout
（`/tmp/darkos-probe`，origin 已改回 GitHub HTTPS），静默凭据推送，
**未弹任何 GitHub 窗口**。

- 提交 `918a646`（`f79317a..918a646 main -> main`）：**24 个文件**，
  2778 insertions / 178 deletions；远端 `git ls-remote` 与本地 HEAD 一致。
- 新增/更新：`vita3k-osd-wl.c`（游戏内快捷设置 + setup 文件浏览器 +
  安卓式状态徽章）、`vita3k-frontend-wl.c`（游戏网格）、
  `psvita-launch.sh`（固件闸门/背光恢复）、`vita3k-pad.py`、`install_vita3k.sh`、
  `vita3k-config-template.yml`、`xdg-shell.xml`、6 个新部署/验证脚本、
  9 张新截图、移植记录与同步说明。
- 未上传：release tarballs、上游 `source/` 快照、`repo/*.bundle`、
  `.workbuddy/`、`__pycache__`；这些已有权威来源或属临时文件。
- 匿名 API 复核 `darkos/image_build/` 目录：上述源码文件均在 main 上。
