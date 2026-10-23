# HackiOS on Redmi K40 (alioth) — 本地工作仓库

把 Apple 开源的 **XNU 内核**（iOS 16.5 对应的 `xnu-8796.121.2`）跑在 **Redmi K40 / POCO F3（alioth，骁龙 870 / SM8250）** 上，
上面跑**未经修改的 iOS 16.5 用户态**。启动链：

```
fastboot boot  →  Mu-Silicium UEFI  →  xnuloader (EFI 应用)  →  XNU  →  launchd / SpringBoard
```

全程只往 **RAM** 里装，不写任何分区；重启即回原来的 Android/HyperOS。

> 上游项目：[hackios-xnu-kernel](https://github.com/hackios/hackios-xnu-kernel) / [hackios-xnu-userland](https://github.com/hackios/hackios-xnu-userland)
> （原始目标是 POCO X5 Pro 5G，代号 redwood / 骁龙 782G / kodiak）。本仓库是把它移植到 alioth 的工作区。

---

## 1. 现在到哪一步了

**已达成（2026-10-22，真机实测）**

| 里程碑 | 证据 |
|---|---|
| 自编 alioth UEFI + loader 起来 | `fastboot getvar product` → `xnuloader`；`display 1080 x 2400 at 9c000000` |
| XNU 启动、APFS 挂载 root | `apfs: volume 0 "System" … 45143 files`；`BSD root: md0` |
| iOS 用户态起来 | `launchd.ios` → `runningboardd` → `backboardd` → `SpringBoard`(pid 7) |
| **主屏显示** | `k40-build/shots/01-springboard.png` |
| 锁屏 | `k40-build/shots/02-lock-screen.png`（侧键锁屏） |
| **程序注入点击可用** | `k40-build/shots/03-appstore-by-simulated-tap.png`（模拟点击打开了 App Store） |
| 硬件按键链路 | `buttons: volume up PRESSED` → `redwood: input: sample type 4` → backboardd |
| **真实手指触摸** | `k40-build/r6.png`（手指点开「设置」）；日志 `focaltech: runtime ID 5652`、`finger 0 down/move … 0 bad` |
| **电源键 / 音量键** | `buttons: power PRESSED`、`volume up/down PRESSED`；音量条由 SpringBoard `_presentVolumeHUDWithVolume:` 显示 |
| **真实电量** | PM8150B fg-gen4（SPMI SID2）：`redwood: battery: SOC=95% … charger=1 charging=1` |
| EPSS 调频 | 三域分别拉到 1804 / 2419 / 3187 MHz |
| **GPU 上电到 3D 核**（2026-10-23） | `adreno=22` 真机：step 1–18 全过，GMU 固件运行、HFI 队列起来、3D 核上电，3D 时钟实测 `524999528 Hz`；详见 `SESSION-HANDOFF.md` §9 |

**未达成**

- **GPU 画图**：step 19（把 zap 镜像写进 `0x8681a000`）总线挂死，20–22 的画帧还没跑到
- **真实音频**（`mediaserverd` 未启动）：音量条能显示、电平会变，但没有声音，音量本身也还不是真的
- Wi-Fi（QCA6391 PCIe）、相机

---

## 2. 目录

```
hackios-xnu-kernel-main/     内核工程（上游 fork + 本移植的改动）
  common/devices/alioth.*    alioth 的设备 profile 与 loader 的 platform 描述
  xnu/files/                 移植新增/修改的内核源码（会被 xnu/apply.sh 拷进 XNU 树）
  xnu/patches/               打在 Apple 原版 XNU 上的小补丁（如 panic 正文写进 loader 日志）
  xnu/redwood.patch          上游 fork 的主补丁
  xnuloader/                 EFI 启动器（loader.c、mkpayload.py）
  docs/alioth-kona-addresses.md   kona 与 redwood 的地址对照表（每条都注明出处）
hackios-xnu-userland-main/   iOS 用户态（ios165/：从 IPSW 提取 rootfs/dyld cache）
.analysis/                   Mu-Silicium 的 alioth 设备树与配置
k40-dump/                    真机采集结果（设备树、iomem、dmesg、固件）——不入库
k40-build/                   构建产物与脚本（boot-one.sh 等）——不入库
tools/                       本地小工具（fdt_dump.py、check-constants.py）
SESSION-HANDOFF.md           详细交接文档：参数、待办、坑
```

---

## 3. 怎么构建、怎么跑

**构建（Linux x86-64，本工程在 WSL2 里）**

```bash
cd ~/k40
DEVICE=alioth ./xnu-build.sh -j$(nproc) -k        # 只编内核
./common/build.sh alioth                           # 内核 + loader + 系统镜像 + boot.img
```

> 改过 `hackios-xnu-kernel-main/xnu/files/**` 之后，要手工同步到 XNU 树再编：
> `cp -a xnu/files/. xnu-src/xnu-8796.121.2/`

**上真机（只写 RAM）**

```bash
cd k40-build
SECS=45 SHOTS=3 GAP=5 bash boot-one.sh
```

脚本会：进 bootloader → `fastboot boot` → `oem ramdisk` → `stage system.apfs` → `stage` 载荷 →
`oem run` → 连拍若干张截图 → 取日志 → 回 Android。

**常用启动参数**（编进载荷的 cmdline）

| 参数 | 作用 |
|---|---|
| `touchscreen=1` | 触摸芯片驱动 |
| `buttons=1` | 硬件按键（PMIC）驱动 |
| `cpufreq=1` | EPSS 调频 |
| `loader_return_after=N` | N 秒后内核把控制权交回 loader |
| `touch_demo=1..6` | 注入触摸样本（1 定点 / 2 竖扫 / 3 上滑 / 5 唤醒+解锁+点击 / 6 唤醒+解锁） |
| `demo_lock=N` | 第 N 次时按下侧键（唤醒屏幕） |
| `touch_stat=N` | 触摸统计每 N 秒一行 |
| `tlmm_scan=1` | 扫描 TLMM（**会打挂系统，慎用**） |

---

## 4. 已知问题

### 4.1 真实手指触摸：已修（2026-10-22 深夜）

现象（修复前）：面板 → 芯片 → SPI 这条路上断了，引脚寄存器全读 0、芯片不应答。

```
goodix: as found: pins cs/clk/mosi/miso cfg 0 0 0 0, reset 0/0    ← 引脚寄存器全读 0
focaltech: boot ID attempt 0: 00 00 (not 56 62)                  ← 芯片不应答
```

**两个根因，都已修**：

1. kona 的 QUPV3 wrap0 **没有 `m_ahb`/`s_ahb` 分支**（那是 sc7280 的）→ 只等引擎自己的时钟。
2. TLMM 在 kona 上分成 3 个 tile，但**不是均匀的 4 MB**。以小米官方 K40 内核
   `pinctrl-kona.c` 为准：`NORTH=0x0F900000`、`SOUTH=0x0F500000`、`WEST=0x0F100000`
   （相对基址 `0x0F000000`），pin 寄存器 = `tile + 0x1000 × 全局 GPIO 号`。
   之前按 `0x0F800000/0x0F400000` 读写落进了未实现的空洞。
3. 芯片是 **0x5652** 且自带固件（不是 FT3680）：复位释放后先读运行态 ID，不走 boot ROM。

修后日志：`pins … cfg 0x84 0x84 0x84 0x84, reset 0x2c3/0, int 0xc3/1`、
`focaltech: runtime ID 5652 valid after 1 attempt(s)`、`finger 0 down/move … 0 bad`。
详见 `SESSION-HANDOFF.md` §5.1–§5.2。

### 4.2 开机后背光（曾出现 `backlight-off; digitizerEnabled: NO`）

以前开机后 SpringBoard 会把显示判成关闭并停掉数字化仪，需要按一次侧键唤醒。
2026-10-22 23:40 的 `r6` 轮里开机 50 秒屏幕已是亮的、直接在「设置」里可点按，**待多轮确认**是否已消失；
若复现，查 `MiniIOMobileFramebuffer.cpp` 的亮度/显示状态上报。

### 4.3 电量与音量键（已通）

- 电量：PM8150B 的 `qcom,fg-gen4`（SPMI slave 2），SOC/电压/电流/充电状态直接读寄存器，
  不再显示恒定低电量（真机 `SOC=95% charging=1`）。做法见 `SESSION-HANDOFF.md` §5.5。
- 音量键：PMIC → 内核 → `/dev/redwood-touch` → backboardd HID → `SBVolumeControl` → 音量条。
  **没有真实音频**（mediaserverd 未启动），所以音量条的电平由 userland 维持；
  音量条在屏幕左侧是 iPhone X 的原生布局。见 `SESSION-HANDOFF.md` §5.4。

### 4.4 其它

- 7 个核里只有 4 个 online（A55 那三个没起来），不影响使用。
- 内核日志要回 Android 后从 `logdump` 分区读（`su 0 dd if=/dev/block/by-name/logdump`），
  或运行中 `fastboot oem log` + `fastboot get_staged`。
- panic 正文既不上屏也不进 msgbuf，靠 `xnu/patches/panic-to-loader-log.patch` 写进 loader 日志才读得到。

---

## 5. 下一步

1. TLMM tile 化：kona 的 NORTH tile = `0x0F800000`、SOUTH = `0x0F400000`（各 4 MB），
   触摸的 4 根 SPI 线在 NORTH，reset/IRQ 在 SOUTH → 驱动要两段映射。
2. 芯片应答后核对 FTS（0x5652）报告格式：每点字节数、寄存器 0x01 的读命令、CRC。
3. 让背光开机即 1，省掉"按侧键唤醒"。
4. 接受 PM8150 PON 的 subtype 0x4，让侧键对 iOS 可见。
5. 第二阶段：GPU（Adreno 650）与 Wi-Fi（QCA6391 PCIe → ath11k pci.c）。

---

## 6. 本地小工具

| 工具 | 用途 |
|---|---|
| `k40-build/boot-one.sh` | 一键跑完一轮真机（启动、上传、运行、截图、取日志、回收） |
| `k40-build/symbolize.py` | 用 `.dSYM` 的 DWARF 把 panic 里的地址反查成函数名 |
| `k40-build/pngcrop.py` | 从原始 BGRX 帧缓冲裁剪并放大，存 PNG（读屏幕小字） |
| `tools/fdt_dump.py` | 纯 Python 的 FDT 解析器（这台机器没有 dtc） |
| `hackios-xnu-kernel-main/tools/check-constants.py` | 源码常量与设备树/ABL 表的一致性检查 |
