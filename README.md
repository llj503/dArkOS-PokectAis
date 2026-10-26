# dArkOS-PokectAis

Pocket AIS（RK3562）掌机的 **dArkOS（Linux）** 移植与维护仓库，包含镜像组装/修复脚本、
设备树源文件、rootfs shim 和移植记录。

> 仓库名沿用创建时的拼写 `PokectAis`；设备正式名称为 **Pocket AIS**。

![dArkOS EmulationStation](docs/images/darkos-es.png)

## 设备信息

| 项目 | 规格 |
| --- | --- |
| SoC | Rockchip RK3562（4×Cortex-A53） |
| 内存 | 2 GB |
| 屏幕 | 1024×768 DSI |
| WiFi | AIC8800D80，SDIO，D80 固件 |
| PMIC / Codec | RK817；扬声器走 HP 输出 + 外部功放（`hp-ctl` GPIO 115） |
| 输入 | `play_joystick` 驱动，左摇杆需要 `left-stick-invert` |
| 启动 | eMMC 内置 U-Boot 加载 TF 卡 p3 的 `extlinux.conf` |
| 存储 | 内置 eMMC AisOS（保留）；TF 卡运行 dArkOS |

TF dArkOS 与内置 eMMC AisOS 互不覆盖；仓库不包含 eMMC 镜像，也不修改 eMMC 的 U-Boot。

## 当前状态

dArkOS 已验证：

- 面板、背光、DSI 时序正常；屏幕方向正确。
- 左摇杆方向正确（DTB `left-stick-invert`），按键/肩键/摇杆可用。
- AIC8800D80 SDIO WiFi，图形化 WiFi 与 SSH 设置可用。
- EmulationStation 中文菜单、主题、色温/BCSH 面板调节。
- RetroArch 简体中文与 CJK 字体；退出/热键正常。
- EmulationStation 单游戏高级菜单：进入游戏前可切换模拟器/核心。
- 电池图标裁剪修复；RK817“永远 Charging”假状态用 shim 修正。
- 关机充电/USB host 角色切换；睡眠/背光恢复修复。
- RK817 扬声器：开机恢复 ALSA 状态后重新置位 HP 路由（Headphone on、HP gain 3），
  ES/RetroArch/Ports 都有声。
- 首次启动自动扩展 `/roms` 分区（exFAT）。
- 镜像 p3(FAT) 出厂即干净：清除 dirty 位、主/备份引导扇区一致，Windows 烧录后**不再弹
  “修复/扫描 dArkOS_Fat”**（20261025 修复了 20261020 版的这个问题）。

仍待处理/已知限制：

- 内置 eMMC AisOS 未修改；eMMC 阶段的第一个启动 logo 不属于 TF 镜像。
- 若重新打包镜像后只启动内置系统，检查 p3 的 GPT 可启动标志（0x4）以及 p1/p2 的
  分区类型 GUID；见 `darkos/image_build/fix_gpt_20261020.py`。
- 镜像构建脚本是在运行中的 dArkOS 设备上执行的参考脚本（固定 `/roms`、`/dev/mmcblk1`
  等路径），不是可在 PC 上直接交叉构建整个发行版的脚本。

## 镜像与校验

dArkOS 镜像通过 GitHub Releases **分卷发布**，不放进 Git 仓库：

<https://github.com/llj503/dArkOS-PokectAis/releases/tag/dArkOS-20261026>

| 文件 | 大小 | SHA-256 |
| --- | --- | --- |
| `pocketAis-dArkOS-20261026-autoexpand-sanitized.img` | 13,019,137,024 B | `bd3043e745393cb4f580afb11c9a4f809096fa1b325e6cac88cf343201feafa3` |
| `pocketAis-dArkOS-20261026-autoexpand-sanitized.img.xz` | 3,555,008,556 B | `48b7eae785968ebf328c54ffa0f16ead5583ac47312ea7366cb936c20e4378d3` |

分卷为 `.part-00`（1,887,436,800 B）、`.part-01`（1,667,571,756 B）和 `SHA256SUMS.txt`。

这版主要修声音：上次关机保存的 ALSA 状态里 `Headphone Switch` 是关的，开机恢复后
扬声器不响（ES、RetroArch、Ports 全静音）。现在 `spktoggle.sh` 会在恢复后再设一遍
HP 路由和 Headphone/Gain。PortMaster 也更新到最新版，GUI 改成 A 确认、B 返回。
上一版的 p3 dirty 位、p4 扩容、SSH host key 修复都在。

20261025 的 Release 少了 part-01，已删除。

本版本已清理设备专属数据：设备**原始的** SSH host keys、`authorized_keys`、WiFi 配置、
账户密码哈希、日志/历史、machine-id 和 RetroArch netplay 密码。镜像已**预置全新 SSH host key**；
**默认登录 `ark`/`ark`（首次登录后请务必修改密码）**，`root` 仍锁定；WiFi 需重新配置。
系统已集成 PortMaster（`/opt/system/Tools/PortMaster`）：Ports 支持 SELECT+START 退出，
音频跟随系统音量，GUI 的 A/B 改成 A 确认、B 返回；autoexpand 也修了复用卡时
`/roms` 不挂载的问题。

### 重组分卷

Linux / macOS：

```bash
cat pocketAis-dArkOS-20261026-autoexpand-sanitized.img.xz.part-* \
  > pocketAis-dArkOS-20261026-autoexpand-sanitized.img.xz
sha256sum pocketAis-dArkOS-20261026-autoexpand-sanitized.img.xz
xz -d pocketAis-dArkOS-20261026-autoexpand-sanitized.img.xz
sha256sum pocketAis-dArkOS-20261026-autoexpand-sanitized.img
```

Windows 用 `copy /b part-00+part-01 image.xz`，再用 7-Zip 解压。
校验值见 Release 的 `SHA256SUMS.txt` 和 `darkos/*.sha256`。

## 快速开始

1. 按上面的步骤重组 xz，核对 SHA 后刷写到 TF 卡：
   - Windows：使用 **Rufus**，选择 raw 镜像后务必选 **DD 模式**，目标设备选 TF 卡。
   - Linux：`sudo dd if=<image> of=/dev/sdX bs=4M conv=fsync status=progress`
2. 插入掌机，从 TF 卡启动。首次启动会自动扩展 `/roms` 分区（exFAT）。
3. 若镜像被重新打包后只启动内置系统，检查并修复 p3 的 GPT 可启动标志和分区类型 GUID。
4. WiFi 在 EmulationStation 网络设置中重新配置；SSH 可把公钥放到 FAT 启动分区
   （p3）根目录的 `authorized_keys`，首次启动脚本会安装给 `ark` 用户。
5. 中文界面、核心选择等功能已集成；详细修复项和构建说明见
   [`darkos/README.md`](darkos/README.md)。

## 仓库结构

```text
.
├── darkos/
│   ├── image_build/              # 组装、GPT/睡眠修复、自动扩容、清理/发布
│   ├── dtb/                      # ro520c DTB 源文件与 DTB 补丁
│   ├── rootfs/                   # 电池状态/USB 角色 shim 与 systemd 单元
│   ├── kernel_config.txt         # AisOS 内核配置（参考）
│   └── *.sha256                  # 发布镜像校验
├── docs/images/                  # README 截图
├── 010-wifi-diag                 # dArkOS WiFi/SSH 诊断脚本
└── 020-wifi-connman              # dArkOS WiFi 修复脚本
```

## 安全说明

- 仓库**不包含**完整磁盘镜像、厂商内核模块/固件、APK、日志、SSH/WiFi 主机密钥、
  WiFi 密码或 userdata；发布镜像通过 Release 分卷提供。
- 发布镜像已清理 SSH host keys、`authorized_keys`、WiFi 配置、账户密码哈希、
  日志/历史和 machine-id；镜像**预置全新 host key**，**默认登录 `ark`/`ark`（请首次登录后尽快修改）**，
  `root` 仍锁定。
- 你自己制作/首次启动后的系统镜像会包含设备专属密钥（SSH host keys、WiFi 凭据等）；
  **不要把这种镜像公开分享**，请自行重新生成。
- 仓库不包含直接写物理磁盘的脚本；刷写请使用 Rufus DD 或 `dd`，并再次确认目标设备。
- 修改 `/vendor`、内核模块或 DTB 前请先备份；不要为了启动 logo 修改 eMMC bootloader。

## 上游与致谢

- dArkOS NGP45HT：<https://github.com/llj503/dArkOS_ngp45ht>
- ArkOS4Clone：<https://github.com/lcdyk0517/arkos4clone>
- ROCKNIX distribution：<https://github.com/AveyondFly/distribution_rocknix>

EmulationStation、RetroArch、RK817 音频驱动、AIC8800 驱动/固件等版权归各自作者所有。
仓库仅包含移植脚本、补丁和文档；厂商二进制请从对应上游镜像获取，并遵守其原始许可。

## 许可证

本仓库中的原创脚本、文档和补丁暂未指定开源许可证；使用、修改和再分发前请先联系仓库
维护者。上游组件（EmulationStation、RetroArch、Linux 内核、驱动和固件等）遵循其各自
许可证。

## 免责声明

这是实验性的设备移植项目。刷机、修改分区、替换内核模块和 DTB 都可能导致设备无法启动。
请保留 eMMC 内置系统、原厂恢复镜像和可启动的 TF 卡，风险自负。
