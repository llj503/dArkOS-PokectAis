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
- 首次启动自动扩展 `/roms` 分区（exFAT）。

仍待处理/已知限制：

- 内置 eMMC AisOS 未修改；eMMC 阶段的第一个启动 logo 不属于 TF 镜像。
- 若重新打包镜像后只启动内置系统，检查 p3 的 GPT 可启动标志（0x4）以及 p1/p2 的
  分区类型 GUID；`image_build/fix_gpt_20261020.py` 是修复脚本。
- 镜像构建脚本是在运行中的 dArkOS 设备上执行的参考脚本（固定 `/roms`、`/dev/mmcblk1`
  等路径），不是可在 PC 上直接交叉构建整个发行版的脚本。

## 镜像

发布镜像通过 GitHub Release 分卷提供：

<https://github.com/llj503/dArkOS-PokectAis/releases/tag/dArkOS-20261025>

| 文件 | 大小 | SHA-256 |
| --- | --- | --- |
| `pocketAis-dArkOS-20261025-autoexpand-sanitized.img` | 13,019,137,024 B | `a7e446fc1cc47d76d894655f96410665e86b633ecce65fe35a20549d307567e7` |
| `pocketAis-dArkOS-20261025-autoexpand-sanitized.img.xz` | 3,418,479,516 B | `782d2f3ae5329a32472d873ae81fae262e3333a7c8993812c55d18111b46918f` |

分卷为 `.img.xz.part-00/01` + `SHA256SUMS.txt`；重组命令见顶层 README。镜像不纳入 Git。
刷写前先解压 xz，使用 Rufus **DD** 模式或 `dd`；刷写后首次启动会扩展 `/roms`。
**20261025 取代 20261020**：修复烧录后 Windows 弹“修复/扫描 dArkOS_Fat”（p3 FAT dirty 位），
详见下面“镜像组装要点”的 20261025 小节。

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
**默认登录 `ark`/`ark`（首次登录后请务必修改）**，`root` 仍锁定。WiFi 需重新配置。
系统已集成 **PortMaster**（`/opt/system/Tools/PortMaster`）：Ports 游戏 SELECT+START 退出、
音频走 softvol 跟随系统音量；`/opt/system/修改密码.sh` 已改为 `sudo chpasswd`（锁定账号也能设密码）。
WiFi 需重新配置。

## 目录

```text
image_build/
  build_image.sh                  # 早期版本的镜像组装脚本
  build_image_20261020.sh         # 最终镜像组装（p1-p4 + p5 占位 + GPT + p3 清理）
  fix_gpt_20261020.py             # 恢复 p1/p2 类型 GUID、p3 可启动标志、GPT CRC
  fix_suspend_20261020.py         # 修复 GPU governor 路径、睡眠背光、ES 屏保
  pocketais-autoexpand.sh         # 首次启动扩展 /roms
  pocketais-autoexpand.service
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

`build_image_20261020.sh` 在设备上执行，主要步骤：

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

**修复**（`image_build/build_image_20261025.sh`，在设备上执行）：

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
