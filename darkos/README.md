# dArkOS on Pocket AIS

基于 dArkOS NGP45HT（Trixie）移植到 Pocket AIS 的 Linux 系统。镜像可写入 TF 卡，
由 eMMC 内置 U-Boot 加载 TF 卡 p3 的 `extlinux.conf` 启动。

## 状态

已实现并验证：

- 面板、背光、DSI 时序正常工作；屏幕方向正确。
- 左摇杆方向正确（DTB `left-stick-invert`），按键/肩键/摇杆可用。
- AIC8800D80 SDIO WiFi（RG52 Mini 驱动/固件），图形化 WiFi 与 SSH 设置可用。
- EmulationStation 中文菜单、主题、色温/BCSH 面板调节。
- RetroArch 简体中文与 CJK 字体；退出/热键正常。
- EmulationStation 单游戏高级菜单：进入游戏前可切换模拟器/核心。
- 电池图标裁剪修复；RK817“永远 Charging”假状态用 shim 修正。
- 关机充电/USB host 角色切换；睡眠/背光恢复修复。
- RK817 扬声器：开机恢复 ALSA 状态后重新置位 HP 路由（Headphone on、HP gain 3）。
- 首次启动自动扩展 `/roms` 分区（exFAT）；fstab 用 `LABEL=ROMS` 挂载，换卡或重新格式化后不会因 UUID 变化挂不上。
- 构建镜像时用 `VERSION`（默认 `20261026`）命名镜像并更新 Plymouth 启动画面版本（`dArkOS (YYYYMMDD)`）；p3 的 `pocketais-autoexpand.done` 在构建时清除。

仍待处理/已知限制：

- 内置 eMMC AisOS 未修改；eMMC 阶段的第一个启动 logo 不属于 TF 镜像。
- 若重新打包镜像后只启动内置系统，检查 p3 的 GPT 可启动标志（0x4）以及 p1/p2 的
  分区类型 GUID；`image_build/fix_gpt_20261020.py` 是修复脚本。
- 镜像构建脚本是在运行中的 dArkOS 设备上执行的参考脚本（固定 `/roms`、`/dev/mmcblk1`
  等路径），不是可在 PC 上直接交叉构建整个发行版的脚本。

## 镜像

发布镜像通过 GitHub Release 分卷提供：

<https://github.com/llj503/dArkOS-PokectAis/releases/tag/dArkOS-20261026>

| 文件 | 大小 | SHA-256 |
| --- | --- | --- |
| `pocketAis-dArkOS-20261026-autoexpand-sanitized.img` | 13,019,137,024 B | `bd3043e745393cb4f580afb11c9a4f809096fa1b325e6cac88cf343201feafa3` |
| `pocketAis-dArkOS-20261026-autoexpand-sanitized.img.xz` | 3,555,008,556 B | `48b7eae785968ebf328c54ffa0f16ead5583ac47312ea7366cb936c20e4378d3` |

分卷为 `.img.xz.part-00/01` + `SHA256SUMS.txt`；重组命令见顶层 README。镜像不纳入 Git。
刷写前先解压 xz，使用 Rufus **DD** 模式或 `dd`；刷写后首次启动会扩展 `/roms`（exFAT），并按 `LABEL=ROMS` 挂载。
这版主要修声音（开机恢复 ALSA 状态后重新置位 HP 路由），PortMaster 更新并改了 GUI 的
A/B。上一版的 p3 FAT dirty 位修复还在。20261025 的 Release 已删除。

### 发布清理流程

发布前从 raw 镜像提取 p4，执行 `image_build/sanitize_p4.sh` 生成干净的 BTRFS rootfs；
用 `mdel` 删除 p3 FAT 中的 `authorized_keys`；再执行 `image_build/finalize_release.sh`
锁定账户密码、写入 p3/p4 并校验 raw。清理内容：

- SSH host keys、`/home/ark/.ssh`、`/root/.ssh`、p3 `authorized_keys`
- NetworkManager WiFi 配置与本地状态
- `ark` / `root` 密码哈希及 `shadow-`/`gshadow-` 备份
- `/etc/machine-id`、`/var/lib/dbus/machine-id`
- shell history、日志、缓存、RetroArch netplay 密码

首次启动会由 `sshd-keygen.service` 重新生成 SSH host keys——**注意：这条在 20261025
首测时是坏的**（machine-id 被清空后 systemd 会抢先重建它，`ConditionFirstBoot` 不再成立，
sshd-keygen 被跳过 → sshd 无 host key → `ssh.service` 启动失败并卡住首次启动）。现改为
**镜像里预置一套全新的 host key**（并加了 drop-in 清掉易失效的 ConditionFirstBoot 兜底）；
**默认登录 `ark`/`ark`（首次登录后请务必修改）**，`root` 仍锁定；`ark` 在 `sudo`
组并有免密 sudo，执行 `sudo -i` 即得到 root shell（PortMaster/ES 的提权也依赖它）。
WiFi 需重新配置。
系统已集成 **PortMaster**（`/opt/system/Tools/PortMaster`）：Ports 游戏 SELECT+START 退出、
音频走 softvol 跟随系统音量；GUI 的 A/B 映射已按本机手柄改为 A=确认；
`/opt/system/修改密码.sh` 已改为 `sudo chpasswd`（锁定账号也能设密码）。
WiFi 需重新配置。

## 目录

```text
image_build/
  build_image.sh                  # 早期版本的镜像组装脚本
  build_image_20261020.sh         # 20261020 镜像组装（p1-p4 + p5 占位 + GPT + p3 清理）
  build_image_20261026.sh         # 当前镜像组装（音频补丁 + PortMaster A/B）
  spktoggle.sh                    # 开机恢复 HP 路由（Headphone on / HP gain 3）
  fix_gpt_20261020.py             # 恢复 p1/p2 类型 GUID、p3 可启动标志、GPT CRC
  fix_suspend_20261020.py         # 修复 GPU governor 路径、睡眠背光、ES 屏保
  pocketais-autoexpand.sh         # 首次启动扩展 /roms
  spktoggle.sh                    # 开机恢复 HP 路由（Headphone on / HP gain 3）
  pocketais-autoexpand.service
  ps2-launcher                    # PS2 分派：PCSX2 SA / ARMSX2 / ARMSX2+malisx2
  armsx2-PCSX2.ini                # ARMSX2 默认配置（BIOS/存档路径、热键）
  patch_es_ps2.py                 # 给 ES 的 ps2 系统加 ARMSX2 选项
  patch_pcsx2sa_zh.py             # PCSX2 SA 中文 UI + 暂停菜单焦点补丁
  sanitize_p4.sh                  # 清理 rootfs 并重建干净 BTRFS
  finalize_release.sh             # 锁定账户密码、写入 p3/p4、校验 raw
  raw2png.js                      # 调试用帧缓冲转换
dtb/
  ro520c.dts                      # Rockchip RK3562 EVB1 基础 DTS
  tf_patch/ro520c_aic.dts         # Pocket AIS 适配后的 DTS（WiFi/摇杆/音频）
  tf_patch/extlinux.conf          # 指向 rk3562-ro520c.dtb 的启动项
  patch_dtb.py                    # 早期按键映射替换脚本
rootfs/
  pocketais-battery-shim*         # 修正 RK817 电池状态
  pocketais-usb-mode              # 手动切换 OTG host/peripheral
  pocketais-usb-role-*            # 自动探测充电器/USB 设备并切换角色
kernel_config.txt                 # AisOS 内核配置（参考）
*.sha256                          # 镜像校验
```

- GitHub Actions：仓库根目录 `.github/workflows/build.yml`，手动 Run workflow 输入 `VERSION`；以上一版 release 为 base，自动构建、分卷、校验并发布。

## DTB 与启动

- 基础 DTB 来自 RK3562 EVB1（`rk3562-ro520c.dtb`），Pocket AIS 的 dArkOS 使用它。
- 在 DTS 中加入/保留：
  - `left-stick-invert`（左摇杆方向）。
  - AIC8800D80 SDIO WiFi 节点与供电。
  - RK817 codec 的 `use-ext-amplifier`、`hp2extamplifier`、`hp-ctl-gpios`，
    扬声器走 HP 输出 + 外部功放。
- 编译后的 DTB 放在 p3 的 FAT 分区，`extlinux.conf` 的 `FDT` 指向它。
- `.dtb` 二进制不纳入仓库；请用 `dtc` 从 DTS 编译，或从镜像 p3 中提取。
  上游 DTS 的基础来源见顶层 README 的“上游与致谢”。

## 镜像组装要点

`build_image_20261026.sh` 在设备上执行，主要步骤：

1. 读取 p5 起始扇区，确定镜像总大小（p1-p4 + 256 MiB 的 p5 占位 + 备份 GPT）。
2. 停止 EmulationStation，复制 p1-p4，写入 p5 占位并截断镜像。
3. 用 `sgdisk` 重建 GPT，保留 p1-p4 的 GUID/名称，p3 设为可启动。
4. 挂载 p3，删除首次启动标记和日志，确保新卡会执行自动扩容。
5. 在 PC 上压缩为 xz；压缩后校验 SHA-256。

`fix_gpt_20261020.py` 用于修复“镜像启动后进入内置 eMMC 系统”的问题：恢复 p1/p2
的特殊类型 GUID、p3 的 `LegacyBIOSBootable` 属性，并重算主/备份 GPT CRC。

### 20261025 版：修复 Windows 烧录后弹“修复/扫描 dArkOS_Fat”

**根因**：`build_image_20261020.sh` 用 `dd if=/dev/mmcblk1` 在 `/boot`(p3) **挂载读写**
时裸拷扇区。Linux vfat 驱动一旦写过该 FAT，就把 FAT32 引导扇区 offset `0x41` 的
dirty 位置 1；`dd` 把这个“脏”标志原样打进镜像。烧录后插入 Windows，Windows 检测到
FAT 脏 → 弹“扫描并修复 dArkOS_Fat”。此外镜像 p3 的主引导扇区 `0x41=01` 而备份引导
扇区（sector 6）`0x41=00`，主/备份不一致也会被 chkdsk 判定需要修复。（p4 btrfs、
p5 占位虽是 Basic Data 类型，但 Windows 不给盘符、不弹窗，无需改动。）

**修复**（`image_build/build_image_20261026.sh`，在设备上执行；即 20261025 流程）：

1. dd p1–p4 + 256 MiB 的 p5 占位 + 截断，`sgdisk` 重建 GPT（占位类型码）。
2. **p4 净化就地做**：镜像里的 p4 是运行根的文件级副本、btrfs FSID 与活根相同，
   直接挂载会报 `duplicate device`(EEXIST)；先 `btrfstune -f -u` 改写镜像 p4 的
   FSID（**LABEL=ROOTFS 保留**；root 由 fstab/extlinux 的 `/dev/mmcblk1p4` **路径**
   定位，不依赖 UUID，故改 FSID 对启动安全），再 `mount -o rw,compress=no`。
3. `btrfs filesystem resize max` 把 p4 从 7.81 GiB 扩到分区满 11.76 GiB（吃掉尾部
   约 3.95 GiB slack，顺带清除其中可能的陈旧数据），删除 SSH host keys /
   authorized_keys / WiFi 配置 / machine-id / 日志历史 / RetroArch netplay 密码，
   锁定 `ark`/`root` 密码，校验无密钥残留后 **填零擦除全部空闲空间**（`compress=no`
   确保零真的落盘覆盖被删数据的块）。
4. **清理 p3**：loop 挂载删除首次启动标记与 `authorized_keys`，卸载后把 p3 主/备份
   引导扇区 offset `0x41` 都写 `0x00`（清 dirty 位并让主/备份一致），读回校验为 0。
5. `fix_gpt_20261020.py` 恢复 p1/p2 Rockchip 类型 GUID、p3 `LegacyBIOSBootable`(0x4)、
   重算 GPT CRC —— 与运行设备逐字段一致。
6. `sgdisk -v` 校验、只读挂载 p4 复核关键文件、`sha256sum` 出镜像校验。

脚本带 `RESUME=1` 模式：若已存在正确大小的 raw，则跳过 dd+sgdisk，从 p4 净化续跑
（失败重试无需重拷 12.7 GiB，也不额外占空间）。

### 20261026 版：RK817 扬声器音频 + PortMaster A/B

**现象**：开机后 EmulationStation、RetroArch、Ports 全部无声，但 `Playback Path` 已由
`spktoggle.sh` 的 @reboot 任务设为 HP。

**根因**：`spktoggle.sh` 先设置 HP 路径，随后 `alsactl restore` 用上次关机保存的状态
覆盖混音器；保存的状态里 `Headphone Switch=false`、`HP Output Gain=0`，RK817 的 HP
输出被关闭（Pocket AIS 的扬声器由 HP 输出经外部功放驱动，`hp-ctl` GPIO115）。

**修复**：`image_build/spktoggle.sh` 在恢复状态之后重新写入 `Playback Path=HP`、
`Headphone=on`、`HP Output Gain=3`；构建脚本把它安装到镜像的
`/usr/local/bin/spktoggle.sh`，开机与热键调用都会生效。

PortMaster 在构建时下载最新版，构建脚本会把 `pylibs.zip` 内 `pySDL2gui.py` 的 A/B
映射交换为 **A=确认、B=返回**（本机手柄的物理 A 对应 SDL 的 B）。

PortMaster 目录（`/opt/system/Tools/PortMaster`）在镜像里归属 `ark`(1000)：ES 以
`ark` 运行，若保留 root:root 755，GUI 下载/安装 runtimes 会报权限错误；构建末尾的
p4 校验会检查属主和 `PortMaster.sh` 可执行位。root 账号仍锁定，`ark` 用免密 sudo
提权（`sudo -i`）。

Ports 音频：普通端口走 `/etc/asound.conf` 的 softvol → dmix；dmix 在 ES 播放启动音时
偶发 `unable to open slave`。特定端口（如极品飞车 U2）可在启动脚本里用
`ALSA_CONFIG_PATH` 指向仅含 `plug → hw:0,0` 的配置，绕开 dmix。


## PS2：ARMSX2（默认）+ 可选 PCSX2 SA / malisx2

镜像在 `/opt/armsx2` 集成 ARMSX2 SDL/kmsdrm 前端（ARMv8.0 自编，
`-march=armv8-a -moutline-atomics`）。官方 Linux 包按 ARMv8.1/LSE 编译，在
RK3562 的 Cortex-A53 上会因 `casl` 触发 SIGILL，不能直接使用。ARMSX2 的 SDL
主循环已修掉“Paused 当游戏结束退出”的 bug，暂停菜单热键不再闪退。

ES 的 PS2 系统默认 `armsx2`（ARMSX2 + `/opt/malisx2` 的 malisx2 0.4.0 ICD）；G52 上
**必须** 用 malisx2。`armsx2-stock` 是实验项（系统 Mali Vulkan，GS 初始化会
abort）；`standalone-pcsx2sa` 仍保留为可选。只在该次启动设置
`VK_ICD_FILENAMES`，不覆盖系统 `rk_vk.json`。

`/usr/local/bin/ps2-launcher` 按 `%EMULATOR%` 分派；ARMSX2 的配置、存档和记忆卡
放在 `/roms/ps2/armsx2`。ARMSX2 的 `[Pad1]` 用 SDL3 位置名
（FaceSouth/East/West/North），SDL 映射按印刷键位（A=确认、B=返回），启动时接
killer_daemon，`Select+Start` 可退出。热键（PCSX2 SA 和 ARMSX2 模板一致）：
**Select+L2 暂停菜单、Select+A 截图、Select+L3 全屏**；暂停菜单里的“关闭游戏”
只提示 `Select+Start`。注意开菜单用的是 Select，之后按 Start 前要先松开 Select，
否则会触发 `Select+Start` 退出。

PCSX2 SA 的 SDL/ImGui 前端原本没有翻译层、字体也只有 Roboto；镜像内置在本机
增量重编的中文版（`/opt/pcsx2/bin/pcsx2-sdl`，`zh-CN.tsv` + Noto Sans CJK SC），
并修了 SDL 主循环把 `Paused` 当游戏结束退出的 bug 和暂停菜单焦点/导航。PCSX2 SA
目前在载入游戏数据时会 SIGSEGV（Vulkan 和软件渲染器都复现），暂不建议使用；
PS2 请用 ARMSX2。重编补丁见 `image_build/patch_pcsx2sa_zh.py`，发布资产为
`pcsx2sa-zh-20261103`。

构建：`.github/workflows/build-armsx2.yml` 在 `ubuntu-22.04-arm` 上编译 SDL 前端
（构建时应用 `patch_pcsx2sa_zh.py`：中文 UI、暂停菜单焦点/防误退，并给
`Main.cpp` 打 `HasActiveWindow` 主循环补丁），发布 `armsx2-armv8a-<版本>`
release 资产；`.github/workflows/build-malisx2.yml` 在 `ubuntu-24.04-arm` 上按
`-mcpu=cortex-a53` 编译 malisx2 0.4.0 的 Linux/kbase ICD（上游只发 Android HAL，
ROCKNIX 的 cross 文件是 cortex-a55），发布 `malisx2-a53-<版本>` release 资产。
镜像构建脚本下载它们与 `pcsx2sa-zh-20261103`，并校验 SHA-256。

## PS Vita：Vita3K-Plus（Qt + Weston）

Vita3K 只有 Qt 桌面前端，而 dArkOS 没有 X/Wayland 会话，所以显示层用 Weston 的
DRM 后端临时顶替 ES：`/usr/local/bin/psvita-launch.sh` 先把自己从 ES 的 cgroup
里挪出去（`systemd-run --unit=psvita-session`，否则 `systemctl stop
emulationstation` 会连自己一起杀掉），再停 ES → 起 Weston（root，kiosk-shell）→
以 ark 身份跑 Vita3K → 退出后停 Weston、恢复 ES 和调频策略。Weston 必须用 root：
libseat 的 builtin 后端要打开 `/dev/tty0`，而 seat0 上没有可借用的 logind 会话；
socket 建好后 `chmod 0666` 让 ark 的 Qt 连得上。

ES 里新增 `psvita` 系统（`/roms/psvita`，`.vpk .zip`），Ports 里的 `Vita3K.sh`
打开 GUI（装固件、设置、已安装应用列表）。Vita3K 用 portable 模式，
`/opt/vita3k/portable` 是指向 `/roms/vita3k` 的软链接，固件/游戏/配置/缓存都落在
大分区上，不占 12G 根分区。

装的时候要两个 release 资产，顺序无所谓但缺一不可：
`install_vita3k.sh <pocketAis-Vita3KPlus-armv8a-*.tar.zst>` 装模拟器和 ES 入口，
`install_vita3k_wsi.sh <pocketAis-vita3k-wsi-a53-*.tar.zst>` 装 Wayland WSI 层。
少了后者 GUI 能起来，但一进游戏就建不出 Vulkan surface。固件在 GUI 里装，或者
`vita3k.sh --firmware <PSVUPDAT.PUP>`（字库 PUP 再装一次）。游戏把 `.vpk`/`.zip`
丢进 `/roms/psvita`，ES 里直接启动，装完自动进游戏。

Weston/libinput 直接忽略手柄（`device is a joystick or a gamepad, ignoring`），
Qt 前端本来只能键盘操作，所以用 `image_build/vita3k-pad.py`（装到
`/usr/local/bin/vita3k-pad.py`）把按键转成 uinput 键盘事件：evdev 读
`rk3562-joystick`，写一个名为 `vita3k-pad` 的 uinput 键盘，Weston 当普通键盘收下
（日志 `device is a keyboard`）再交给 Qt。`Select+Start` 由它自己处理：SIGKILL
Vita3K 后自行退出，启动器的 EXIT trap 再把 ES 拉回来；这段时间 killer_daemon 停
掉、退出后再拉起来。ogage **不停**——它是音量/亮度/静音的热键监听，只读 evdev、不
grab 也不写 uinput，和映射进程并存没问题（PortMaster 里就是这么共存的），停掉它整
局游戏音量键就死了。Vita3K 走 ALSA softvol，ogage 的 `volume.sh` 对它生效。必须
SIGKILL：Vita3K 里 SDL 装了 SIGTERM handler 而 Qt 主循环从不处理它
（`pump_sdl_events()` 没有 `SDL_EVENT_QUIT` 分支），普通 `killall` 杀不动。

**为什么不用 PortMaster 的 gptokeyb。** 在这台机器上它根本不建 uinput 键盘：进程
拿着手柄的 evdev node，但 `/proc/<pid>/fd` 里没有 `/dev/uinput`，也不见新 evdev
node，按键一个都到不了 Qt。更糟的是 `-1 Vita3K -sudokill` 的参数解析把 kill 目标
留空，Select+Start 时执行 `kill -9 $(pidof -c )`，shell 报 usage 错误后 gptokeyb
自己退出——整局输入随之全死（"所有按键都无法操控"就是这个）。用 PATH shim 录到的
调用序列证实了这两点。映射表因此直接写在 `vita3k-pad.py` 顶部（`BTN_MAP`/`STICK`，
左摇杆按死区转方向键），改键改那里；原来的 `vita3k.gptk` 已删除。手柄掉线重插时
映射进程保留键盘、重新扫描 evdev，不会跟着死。

验证到哪一步：`vita3k-pad` 键盘被 Weston 收下、Select+Start 杀 Vita3K 并回到 ES
已端到端跑通（`image_build/tests/v3k-pad-live.py`，克隆一个同名手柄注入）；evdev
层每个按键的键码也逐个对过（`tests/v3k-padmap-test.py`）。GUI 的应用列表只有一行
时方向键看不出焦点变化，游戏内手柄待带自动启动修复的新 bundle 装上后复验。

**这些按键在游戏里也有效，而且每个按键会到两次。** `GameWindow::keyPressEvent`
确实直接 `ignore()`，但 `CtrlKeyboardFilter` 是装在同一个窗口上的 event filter
（`main_window.cpp`），跑在 `keyPressEvent` 之前，所以键盘照样能驱动被模拟的 Vita
手柄。同时映射进程**没有** `EVIOCGRAB` 独占手柄——`/proc/<pid>/fd` 里它
和 Vita3K 打开的是同一个 `/dev/input/event4`——于是 SDL 手柄和 uinput 键盘两条路
都会送同一个物理按键。原来的映射 `a = enter` 配 Vita3K 默认的
`keyboard-button-start: Enter`，等于 A 键同时按下 Cross 和 Start。

修法是让两条路落在同一个 Vita 按键上：`vita3k-pad.py` 保持 GUI 好用的
`a=enter / b=esc / x=space / y=backspace`，`start=insert / back=delete`，
`l1/r1/l2/r2=pageup/pagedown/home/end`；`psvita-launch.sh` 首次运行时把 Vita3K 的
键盘绑定改成对应的 `cross=Enter / circle=Escape / square=Space /
triangle=Backspace / start=Insert / select=Delete / L1=PageUp …`，用
`/roms/vita3k/.darkos-controls` 标记只做一次，之后用户在 Vita3K 自己的控制设置里
改键不会被覆盖。这样 A 在 GUI 里是"确定"，在游戏里是 Cross，两边都对。

构建：`.github/workflows/build-vita3k.yml` 在 `ubuntu-24.04-arm` 上用 gcc-14 编
`nckstwrt/Vita3K-Plus` 的 `v1.4-Corrected`，Qt 6.11.0 走官方 `linux_arm64`
（`linux_gcc_arm64`）在线仓库，发行版都没有这么新的 Qt。`-march=armv8-a
-moutline-atomics`，发布 `vita3k-plus-armv8a-<版本>` release 资产。

`v1.4-Corrected` 这个 tag 和它自己不同步，`image_build/patch_vita3k.py` 修四处：

1. 补没提交的生成头 `vita3k/util/include/util/fork_build.h`（`logging.cpp` 要用；
   不要在里面定义 `RELEASE_VERSION`）；
2. `codec/src/atrac9.cpp` 调 `Atrac9DecodeBounded()`，但 tag 钉住的 LibAtrac9
   gitlink（`82767fe3`，master 也一样）只导出 `Atrac9Decode()`。不动子模块，改为
   在本地加一个带上界的包装：拷一份不超过 `superframe_data_left` 字节、零填充的
   私有缓冲再解码，消费超出上界就判失败（LibAtrac9 的 BitReaderCxt 没有长度字段）；
3. `renderer/src/vulkan/surface_cache.cpp` 里 `copy.imageOffset = { ... }` 在
   C++23 + 钉住的 Vulkan-Headers 下二义（`operator=(VkOffset3D const&)` 和隐式
   拷贝/移动赋值），显式写出 `vk::Offset3D{ ... }` / `vk::Extent3D{ ... }`；
4. `main.cpp` CLI 装完内容后把自动启动的 title 写进局部 `cfg`，而 `app::init()`
   早已把它 move 进 `EmuEnvState`，MainWindow 读的是另一份（详见下面"自动启动"）。

打包由 `image_build/package_vita3k.sh` 负责：沿 `ldd` 闭包收 Qt 私有依赖
（ICU、pcre2-16、double-conversion，`libQt6*` 通配会漏），给主程序、库和插件分别
设 `$ORIGIN` 相对 RPATH，并写入 `BUILD-INFO.txt`（源码 commit、子模块、外部系统库
清单）。设备上安装用 `image_build/install_vita3k.sh <bundle.tar.zst>`：先解到
`/opt/vita3k.new.XXXXXX` 再整体换名，失败也不会把正在用的 bundle 弄坏；`mktemp`
建出来是 0700，换名后要 `chmod 0755`，否则以 ark 身份跑的 GUI 进不去目录。

闭包必须对着 Qt 安装目录解析：插件拷进 bundle 后 `$ORIGIN` 相对 RPATH 指向的是
还没填好的 `pkg/lib`，`ldd` 会把尚未拷入的 Qt 模块报成 `not found` 而被静默丢掉。
`libQt6WaylandClient.so.6` 就这么漏过一次，设备上平台插件转去绑系统自带的
Qt 6.8，报 `undefined symbol: _ZTI20QGenericUnixServices, version
Qt_6_PRIVATE_API` 后 abort。现在走闭包时 `LD_LIBRARY_PATH` 指向 `$QTDIR/lib`，
任何解析不到的依赖直接让打包失败，并单独断言 Wayland 客户端模块在包里。

Mali blob 只提供 `libEGL`/`libGLESv2`（都指向 `libMali.so`），没有 GLVND 的
`libGL.so.1`/`libGLX.so.0`/`libGLdispatch.so.0`，而官方 Qt 的 `Qt6Gui` 链接桌面
GL，所以这三个也一起打进 `lib/`；实际渲染仍走设备的 EGL。同时裁掉
designer/assistant/QML 工具、sqldrivers、printsupport、gtk3 平台主题和 GStreamer
媒体后端——它们会再拖进别的 Qt 模块和 cups/mysql/postgresql/odbc/gstreamer。

**Mali blob 抢走了 `wl_*` 符号**，这是 Qt 界面起不来的真正原因。Rockchip 的
`libMali.so` 把 libwayland-client 和 libwayland-server 静态链了进去，还导出了 64
个 `wl_*` 符号（`wl_display_connect`、`wl_proxy_marshal`、`wl_client_*`、
`wl_resource_*` …）。Qt6Gui 先把 `libEGL` → `libMali` 拉进全局作用域，之后才
dlopen wayland 平台插件，于是 `libQt6WaylandClient.so.6` 把 `wl_display_connect`
绑到了 Mali 那一份上，而它连不上：Qt 报 `Failed to create wl_display (No such
file or directory)` 后 abort，socket 明明在，weston 自带客户端也正常。
`LD_DEBUG=bindings` 是决定性证据：

```
binding file /opt/vita3k/lib/libQt6WaylandClient.so.6 [0] to /lib/aarch64-linux-gnu/libEGL.so.1 [0]: normal symbol `wl_display_connect'
```

修法是 `LD_PRELOAD` 真正的 `/lib/aarch64-linux-gnu/libwayland-client.so.0`，让它排
在 libMali 前面；`psvita-launch.sh` 和包里的 `vita3k.sh` 都做（后者检测到已经
preload 过就跳过）。排查时注意 Qt 是用 `RTLD_DEEPBIND` dlopen 插件的，所以
`LD_PRELOAD` 一个 getenv/connect 的 shim 看不到任何调用，得用 strace 或
`LD_DEBUG`——strace 显示整个 abort 过程里一个 `socket()`/`connect()` 都没有。

**位置参数前面必须加 `--`。** Vita3K 的 CLI11 把以 `/` 开头的参数当成 Windows
风格选项，所以 `Vita3K -F /roms/psvita/game.vpk` 里的路径会被静默吃掉：
`content-path` 是空的，既不装也不自动启动，只弹出 GUI，日志里连
`input-content-path:` 都没有。`Vita3K -F -- /roms/...` 才正常。
`psvita-launch.sh` 已经这么传。排查时还踩到一个坑：Vita3K 吞 SIGTERM，
`timeout 30 Vita3K …` 会一直等下去，必须 `timeout -s KILL`。

**Mali 的 Vulkan 没有 Wayland WSI，用 `vulkan-wsi-layer` 补。** 设备的
`libmali-bifrost-g52-g29p1.so`（`arm_release_ver: g29p1-12eac0, rk_so_ver: 4`，
内核 DDK g25p0，`arm,mali-bifrost` kbase，`/dev/mali0`）是 gbm winsys 变体：
`NEEDED` 里只有 libdrm，没有 wayland 库，EGL 也只有合成器侧的
`EGL_WL_bind_wayland_display`，没有 `EGL_KHR_platform_wayland`。Vulkan 实例扩展
一共 13 个，WSI 相关只有 `VK_KHR_surface`、`VK_KHR_display`、
`VK_EXT_headless_surface`，**没有 `VK_KHR_wayland_surface`**
（`vkEnumerateInstanceExtensionProperties` 实测，不是字符串猜测），所以 Vita3K
默认的 Vulkan 后端在 Weston 下建不出 surface。OpenGL 后端也不行：
`create_gl_context()` 要桌面 GL 4.4+ CoreProfile，Mali 只有 GLES 3.2。

补法是 ARM 的 window system integration layer（这里用 ginkage 分支）：它自己用
dma-buf 建 swapchain，再通过 linux-dmabuf 交给 Wayland，对外补出
`VK_KHR_wayland_surface`。设备条件本来就齐：`/dev/dma_heap/system-uncached`、
`VK_KHR_external_memory_fd`、`VK_EXT_image_drm_format_modifier`、
`VK_EXT_external_memory_dma_buf`、`VK_EXT_queue_family_foreign` 全在。
`.github/workflows/build-vita3k-wsi.yml` 在 `ubuntu-24.04-arm` 上编，
`-DBUILD_WSI_WAYLAND=1 -DBUILD_WSI_X11=0 -DBUILD_WSI_HEADLESS=0
-DBUILD_WSI_DISPLAY=0 -DSELECT_EXTERNAL_ALLOCATOR=dma_buf_heaps
-DWSIALLOC_MEMORY_HEAP_NAME=system-uncached`，同样 `-march=armv8-a
-moutline-atomics`。两个注意点：

- layer 的 main 分支用了 `VK_KHR_present_id2`/`present_wait2`/`EXT_present_timing`，
  Debian trixie 的 Vulkan 头（1.4.309）还没有，必须钉 Khronos 的
  `Vulkan-Headers`（这里 v1.4.368）并用 `-DVULKAN_CXX_INCLUDE` 指过去；
- 它是**隐式层**，开关是 `VK_ADD_IMPLICIT_LAYER_PATH`。`VK_ADD_LAYER_PATH` 只管
  显式层，设了也毫无反应（实测扩展列表纹丝不动）。

装到 `/opt/vita3k-wsi`（`image_build/install_vita3k_wsi.sh`），
`psvita-launch.sh` 只对 Vita3K 这棵进程树导出该变量，系统其它地方照旧直接用 blob。

验证：`weston-screenshooter` 和 `weston-debug` 只有在 Weston 带 `--debug` 时才
授权（否则 `unauthorized`），所以 `psvita-launch.sh` 认 `PSVITA_WESTON_DEBUG=1`，
默认关闭。截图文件名由 screenshooter 自己定（`wayland-screenshot-<时间>.png`，
落在当前目录），命令行参数会被忽略；`weston-debug scene-graph` 能直接看到
toplevel 的 PID、app_id 和已提交的 buffer，是比截图更硬的渲染证据。

状态：**游戏已经在设备上跑起来了**。固件、游戏、渲染、输入、退出全链路验证过。

固件用 `--firmware <PUP>` 装（`QT_QPA_PLATFORM=offscreen` + `SDL_AUDIODRIVER=dummy`
就能无头装，因为 `--firmware` 在进 GUI 前就返回 `QuitRequested`，但 QApplication
还是先构造了）：主固件 3.74 → `vs0` 1473 个文件 296M，字库 3.73 → `sa0` 178 个文件
111M。预装 PUP（`pd0`）没装，用不上。

游戏是 Blast 'Em Bunnies（PCSE00328），NoNpDrm 解包目录（`app/` + `patch/`）走
`-- <目录>` 安装，app 和 1.01 补丁都进了 `ux0/app/PCSE00328`，约 9 秒。注意
**`/roms` 是 exFAT，不能建符号链接**（`ln -s` 直接 `Operation not permitted`），
所以游戏目录只能 `mv` 成 ASCII 名，不能靠软链绕开中文路径。

渲染证据（`weston-debug scene-graph`）：

```
View 0 (role xdg_toplevel, PID …, top-level window 'Blast 'Em Bunnies (PCSE00328)
        | Vulkan | 30 FPS (34 ms) | 960x544 | Bilinear' of Vita3K):
        dmabuf buffer
```

`dmabuf buffer` 就是 WSI layer 的 dma-buf swapchain 经 linux-dmabuf 交给 Weston 的
那条路；GUI 阶段是 SHM buffer，两者一眼能分清。截图是正确的标题画面和 3D 场景，
不是黑屏。A53 上开场 30 FPS，着色器编译期间掉到 9–15 FPS，之后回到 15–30 FPS；
`[MEMSNAP]` 显示进程 RSS 760–960 MiB、dmabuf 3 个 fd 9 MiB，2G 内存够用但没多少余量。

Qt 前端本身也早就跑通了：`Loaded stylesheet 'light'`、
`[CTRL] 'rk3562-joystick' connected on port 0`，用 uinput 注入 Tab/方向键后截图里
焦点框会移动，即手柄 → vita3k-pad/uinput → Weston → Qt 全程通。退出后 ES、ogage、
killer_daemon 都正常恢复（killer_daemon 以 `python3` 跑，`pidof killer_daemon`
查不到它，要看 `systemctl is-active`）。

游戏内输入也验证过：注入 A（enter → Cross）关掉了游戏自己的 PSN 提示框并进入
教学关，R1（pagedown）开局，截图里是带血条/计分/雷达/枪管的实时 3D 画面，计时器
在走、敌人会被打掉。改键前后对比见上面输入映射那一节。

**自动启动有三个坑。** 前两个在 `psvita-launch.sh` 里绕过，第三个是上游 bug，在
`patch_vita3k.py` 里修。

1. Welcome 对话框是模态的，`main_window.cpp` 里 `welcome.exec()` 跑在 `app.exec()`
   之前，而自动启动是 `QTimer::singleShot(0, … boot_game(title_id))`——事件循环没
   起来，定时器永远不触发。所以默认 `show-welcome: true` 时，`-r TITLEID` 明明传
   进去了（日志有 `input-installed-path:`），游戏就是不启动，只停在欢迎框。
   启动器现在把 `show-welcome: false` 和 `boot-apps-full-screen: true` 写进
   `/roms/vita3k/config.yml`。
2. `main.cpp` 判断目录安装是否自动启动用的是 `install_contents(...) == 1`，而
   `install_contents` 返回的是**装成功的条目数**：app + patch 的目录返回 2，条件
   不成立；就算改成 `>= 1` 也没用，因为补丁的 category 是 `gp` 不是 `gd`，
   `app_category == "gd"` 这一半照样过不去。启动器的处理是：目录且
   `ux0/app/<同名 TITLEID>` 已存在时改用 `-r TITLEID`，所以第二次起直接进游戏。
3. **`main.cpp` 把要自动启动的 title 写错了对象。** `app::init()` 里是
   `state.cfg = std::move(cfg)`，而 `EmuEnvState::cfg` 是指向 `_cfg` 这个堆上
   `Config` 的引用，和 main 里的局部 `cfg` 已经是两个对象。CLI 装完内容后
   `cfg.run_app_path = boot_title_id` 写的是局部那份，MainWindow 读的是
   `emuenv.cfg.run_app_path`，于是日志打了
   `Content installed, will auto-boot: PCSE00328`，游戏却永远不启动。
   `-r` 之所以正常，是因为它在 `app::init()` 之前就设好了。
   `patch_vita3k.py` 把这一行改成 `emuenv.cfg.run_app_path`。

## 电池与 USB

- `pocketais-battery-shim` 用 tmpfs 文件 bind-mount 覆盖
  `/sys/class/power_supply/battery/status`，根据 `current_now` 的符号和滞回判断
  Charging/Discharging，解决 ES 不插电也显示闪电图标的问题。
- `pocketais-usb-role-watch` 在无 USB 设备时每 8 秒短暂探测 peripheral；检测到充电器
  则保持 peripheral，否则切回 OTG host。相关 systemd 单元在 `rootfs/` 中。
- 安装时把脚本放到 `/usr/local/sbin/`，单元放到 `/etc/systemd/system/`，`systemctl enable`
  对应服务。注意不要把 `pocketais-usb-role.service` 加 `After=multi-user.target`，
  否则会形成 systemd 顺序环，导致 watcher 不启动、充电只有约 2 W。

## 相关上游

- dArkOS NGP45HT：<https://github.com/llj503/dArkOS_ngp45ht>
- ArkOS4Clone：<https://github.com/lcdyk0517/arkos4clone>
- ROCKNIX distribution：<https://github.com/AveyondFly/distribution_rocknix>
- RetroArch / EmulationStation：各自上游项目。
