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

Weston/libinput 直接忽略手柄（`device is a joystick or a gamepad, ignoring`），
Qt 前端本来只能键盘操作，所以 GUI 期间用 gptokeyb（PortMaster 同一个工具，
映射在 `/usr/local/share/vita3k.gptk`）把按键转成 uinput 键盘事件，Weston 再交给
Qt。`Select+Start` 是 gptokeyb 自己的退出组合，这段时间 killer_daemon 和 ogage
停掉，退出后再拉起来。必须带 `-sudokill`：Vita3K 里 SDL 装了 SIGTERM handler 而
Qt 主循环从不处理它（`pump_sdl_events()` 没有 `SDL_EVENT_QUIT` 分支），普通
`killall` 杀不动，只有 SIGKILL 有效。游戏窗口本身忽略按键事件
（`GameWindow::keyPressEvent` 直接 `ignore()`），不会和被模拟的 Vita 手柄重复。

构建：`.github/workflows/build-vita3k.yml` 在 `ubuntu-24.04-arm` 上用 gcc-14 编
`nckstwrt/Vita3K-Plus` 的 `v1.4-Corrected`，Qt 6.11.0 走官方 `linux_arm64`
（`linux_gcc_arm64`）在线仓库，发行版都没有这么新的 Qt。`-march=armv8-a
-moutline-atomics`，发布 `vita3k-plus-armv8a-<版本>` release 资产。

`v1.4-Corrected` 这个 tag 和它自己不同步，`image_build/patch_vita3k.py` 修三处：

1. 补没提交的生成头 `vita3k/util/include/util/fork_build.h`（`logging.cpp` 要用；
   不要在里面定义 `RELEASE_VERSION`）；
2. `codec/src/atrac9.cpp` 调 `Atrac9DecodeBounded()`，但 tag 钉住的 LibAtrac9
   gitlink（`82767fe3`，master 也一样）只导出 `Atrac9Decode()`。不动子模块，改为
   在本地加一个带上界的包装：拷一份不超过 `superframe_data_left` 字节、零填充的
   私有缓冲再解码，消费超出上界就判失败（LibAtrac9 的 BitReaderCxt 没有长度字段）；
3. `renderer/src/vulkan/surface_cache.cpp` 里 `copy.imageOffset = { ... }` 在
   C++23 + 钉住的 Vulkan-Headers 下二义（`operator=(VkOffset3D const&)` 和隐式
   拷贝/移动赋值），显式写出 `vk::Offset3D{ ... }` / `vk::Extent3D{ ... }`。

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

验证：`weston-screenshooter` 和 `weston-debug` 只有在 Weston 带 `--debug` 时才
授权（否则 `unauthorized`），所以 `psvita-launch.sh` 认 `PSVITA_WESTON_DEBUG=1`，
默认关闭。截图文件名由 screenshooter 自己定（`wayland-screenshot-<时间>.png`，
落在当前目录），命令行参数会被忽略；`weston-debug scene-graph` 能直接看到
toplevel 的 PID、app_id 和已提交的 buffer，是比截图更硬的渲染证据。

状态：**Qt 前端已在设备上跑通**。走真实的 ES 入口启动，`weston-debug scene-graph`
看到 `View 0 (role xdg_toplevel, PID …, top-level window 'Welcome to Vita3K' of
Vita3K)`，1024x768 全不透明 SHM buffer；截图是正确的欢迎对话框，日志里有
`Loaded stylesheet 'light'` 和 `[CTRL] 'rk3562-joystick' connected on port 0`。
输入链路也验证过：用 uinput 注入 Tab/方向键后截图里的焦点框从
"Commercial Compatibility List" 移到了 "Show next time"，即
手柄 → gptokeyb/uinput → Weston → Qt 全程通。退出后 ES、ogage、killer_daemon
都正常恢复。

**但实际游戏还跑不起来，卡在 GPU 驱动的 WSI 上。** 设备的
`libmali-bifrost-g52-g29p1.so`（内核 DDK g25p0，`arm,mali-bifrost` kbase，
`/dev/mali0`）是 gbm winsys 变体：`NEEDED` 里只有 libdrm，没有 wayland 库，EGL 也
只有 `EGL_WL_bind_wayland_display`（合成器侧）而没有 `EGL_KHR_platform_wayland`。
它的 Vulkan 实例扩展一共 13 个，WSI 相关只有：

```
VK_KHR_surface   VK_KHR_display   VK_EXT_headless_surface
```

`VK_KHR_wayland_surface` **不存在**（`vkEnumerateInstanceExtensionProperties` 实测，
不是字符串猜测）。Vita3K 默认后端就是 Vulkan
（`config.h` 的 `backend_renderer = "Vulkan"`），设备侧必需扩展
`VK_KHR_swapchain`/`VK_KHR_storage_buffer_storage_class`/`VK_KHR_maintenance1`
都在，唯独缺这个呈现用的实例扩展，所以在 Weston 下建不出 surface。OpenGL 后端也
不行：`game_window.cpp` 的 `create_gl_context()` 要桌面 GL 4.4+ CoreProfile，Mali
只有 GLES 3.2。另外**还没有 PS Vita 固件和游戏**，`--firmware <PUP>` 和 `.vpk`
安装都待测。

可行的补法（按代价排序）：

1. `vulkan-wsi-layer`（ARM 上游 / ginkage 分支）——一个 Vulkan 隐式层，自己用
   dma-buf 建 swapchain 再通过 linux-dmabuf 交给 Wayland，对外补出
   `VK_KHR_wayland_surface`。设备条件已经齐了：`/dev/dma_heap/system-uncached`、
   `VK_KHR_external_memory_fd`、`VK_EXT_queue_family_foreign`、
   `VK_KHR_bind_memory2` 都在，gcc 12 / cmake 3.31 / wayland+gbm+libdrm 头文件也
   都有（只缺 `vulkan/vulkan.h`）。用 `VK_ADD_LAYER_PATH` 只对 Vita3K 生效，
   不动系统 libMali。
2. 换 wayland winsys 的 libmali 变体（上游有 `-wayland-gbm` 包），但要么整体替换
   系统 blob（影响 ES/Weston/所有 GLES 程序），要么在同一进程里塞两份 libMali
   （EGL 和 `wl_*` 符号会再打一次架），风险都比第 1 条大。
3. 切 panfrost/panvk：要换内核 GPU 驱动，且 G52 上的 panvk 还不成熟。
4. lavapipe 软件渲染：A53 上跑 Vita 模拟不现实。
5. 给 Vita3K 打 `VK_KHR_display` 补丁：改动大，而且 Weston 已经占着 DRM master。

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
