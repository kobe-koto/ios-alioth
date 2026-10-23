# HackiOS on Redmi K40 (alioth) — 会话上下文与交接

> 最后更新：2026-10-23 19:10 (GMT+8)
> 工作区：交付包根目录（下文的 `<workdir>` 即指此目录）
> 本地 git 仓库已建立（提交 `8da7167`，13.4 MB），源码与文档都在里面；产物（镜像、固件、日志）不入库。
> 上手说明见仓库根目录的 `README.md`；本文件是**给下一个会话/agent 看的完整上下文**。

---

## 0. 一句话现状

**iOS 16.5 主屏已经在 K40 上真机显示出来了**（`k40-build/shots/01-springboard.png`），
iOS 用户态（launchd / runningboardd / backboardd / SpringBoard）全部在跑，无 panic；
**程序注入的点击可用**（`shots/03-appstore-by-simulated-tap.png` 是模拟点击打开的 App Store）；
**真实手指触摸已通**（2026-10-22 23:30，`k40-build/r6.png` 是手指点开「设置」后的截图，
`r4/r6` 日志里 `focaltech: finger 0 down/move …`，240 报文/秒、0 bad）。
根因是 TLMM tile 基址，见 §5；开机背光也是亮的，不需要先按侧键。
**电源键、音量加、音量减全部真机可用**（§5.3）：电源能锁屏/亮屏，音量键会出音量条。
**电量显示正常**（§5.5）：PM8150B fg-gen4 读出 95% / 充电中，SpringBoard 已显示真实电量。
注意事项：音量条的**音量本身还没有真实音频**（mediaserverd 未启动），电平由 userland 维持；
音量条画在屏幕左侧是 iPhone X 的原生布局（K40 按键在右侧，所以看着“反”），见 §5.4。

**2026-10-23 新增：GPU（Adreno 650）真机验证到 step 20 的入口，且已定位到唯一阻塞点**（§9）。
`adreno_soc=a650 adreno=22` 在 K40 上：step 1–17 全过（GMU 固件运行、HFI 队列起来、
3D 核上电且时钟实测 524999528 Hz ≈ 525 MHz）；step 18 在把 3D 核流经 SMMU context 0 时
发现 K40 的流掩码是 `0x401`（不是 `0x400`），修正后通过；**step 19 的 zap 已修好并真机通过**
（`pil_gpu_region` 在 loader 给内核的物理窗口之外，改为两页内核自有连续内存）。
**step 20 仍卡在 `CP_SQE_CNTL=1` 这一条写：写下去的瞬间内核不再输出任何一行，随后整机复位**
（§9.5）。已用真机排除：微码地址（`adreno_blind=1`）、zap 顺序（跳过 step 19）、
SMMU 拒绝取指（`adreno_direct=1` bypass）、寄存器偏移（与 K40 厂商 `a6xx_reg.h` 逐条一致）、
空闲掉电（编核后空闲 2.5–3 s 无复位）、SPTPRAC（控制寄存器写不进）、GMU OOB（两种中断位都不被确认）、
`CP_RB_RPTR_ADDR`/bit27（`adreno_rptr=1`）。**控制实验证明同一寄存器写 0 完全无害**：致命的是
“启动命令处理器”这个动作本身。**剩余只有重活**：补齐厂商 `a6xx_start()` 其余写、或换到 UEFI 环境里
用同一顺序启动 CP 以分辨是否是 XNU 侧（SError/中断）引起的复位，见 §9.5/§10。

---

## 1. 用户诉求与约束

- 把 HackiOS（Apple XNU + iOS 用户态跑在 Android 手机上）移植到用户的 **Redmi K40 / POCO F3（alioth）**。
- **硬约束（用户明确要求）**：“严禁损坏原系统，原系统还能正常启动”。
  → 全程只用 `fastboot boot` 与 `fastboot stage`（纯 RAM），**不写任何分区**；
  唯一会写的是 loader 每次内核返回时写 `logdump` 分区（小米自己的崩溃日志分区，不影响启动，已验证多次）。
  绝不执行 `fastboot flash` / `fastboot erase` / `fastboot -w` / 刷整包。
- 用户希望**自主推进**，无需逐项确认；第三方依赖优先取 GitHub 上的官方开源库。

## 2. 项目本质

```
fastboot boot → Mu-Silicium UEFI → xnuloader (EFI 应用，常驻，提供 USB fastboot 通道)
             → XNU (BCM2837 配置为底 + 自有平台代码) → iOS launchd → SpringBoard
```

- 内核：Apple 开源 `xnu-8796.121.2`（= iOS 16.5 内核），**编的时候换掉硬件地址与驱动**。
- 用户态：**未改一个字节**的 iOS 16.5（从用户提供的 IPSW 里提取 rootfs + dyld shared cache）。
- 原项目目标机是 POCO X5 Pro 5G（redwood / 骁龙 782G / kodiak），本工作区是把它移植到 alioth。

---

## 3. 已核实的 alioth 硬件事实（全部有出处）

| 项 | 值 | 出处 |
|---|---|---|
| codename / SoC | alioth / SM8250-AC (kona)，骁龙 870 | 手机 `getprop`、设备树 |
| DRAM | `0x80000000 + 0x3BB00000`，`0xC0000000 + 0x1C0000000` | 设备树 |
| GIC | v3：distributor `0x17A00000`，redistributor `0x17A60000` | 设备树、实测 `gic: v3, distributor …` |
| CPU | 8 个，MPIDR shift 8；0–3 = A55(cap 0x400)，4–7 = A77(0x766) → `small_cores=0x0f` | 设备树 |
| EPSS 调频 | `0x18591000`，三域（与 redwood 相同） | 实测 1804/2419/3187 MHz |
| UFS | `0x1d84000` | 设备树 |
| GCC | `0x00100000`，大小 `0x60000`；vote 寄存器 `0x52008` | 上游 gcc-sm8250.c |
| 触摸 | FocalTech FTS，SPI 在 **GENI SE4 @ `0x990000`**（QUPV3 wrap0） | 设备树 `spi@990000` |
| 触摸引脚 | 总线 gpio 8/9/10（MISO/MOSI/CLK）、CS gpio 11、IRQ gpio 39、reset gpio 33 | 设备树 |
| 触摸芯片 ID | `0x5652`（**不是** redwood 的 FT3680） | Android dmesg |
| 触摸分辨率 | 报告空间 8640 × 19200（`getevent` 上限 8639/19199，10 点） | `getevent -pl` |
| 面板 | `qcom,mdss_dsi_k11a_38_08_0a_dsc_cmd`，1080×2400，60/90/120 Hz | 设备树 |
| 马达 | aw8697，I2C `0xa8c000`，SDA gpio60 / SCL gpio61 / reset gpio130 / int gpio129 | 设备树 |
| 按键 | 音量加 = PM8150 **GPIO6**；电源键与音量减 = PM8150 的 PON 块（type 0x01 **subtype 0x04**） | Android `getevent -pl`（`qpnp_pon` / `gpio-keys`） |
| UEFI | FD_BASE `0x9FC00000`，FD_SIZE `0x300000`（redwood 是 `0x9FD00000`/`0x200000`） | `Resources/Configs/alioth.toml` |
| XBL/ABL | SBL1/UEFI 编译于 **2024-05-27**，UEFI 4.1，Change 16743401 | `xbl_a.img` 字符串 |
| `fb_base` | **`0x9C000000`**（实测，loader 打印 `display 1080 x 2400 at 9c000000`） | 真机 |

**从 xbl_a.img 抽出的 ABL AddMem 表（21 条）**：`FD_BASE=0x9FC00000/0x300000`（表里就叫 "UEFI FD"）、
`Display Reserved = 0x9C000000 + 0x2400000`（→ `fb_base` 由此推定，且被实测证实）、
`AOP CMD DB = 0x80860000`、`SMEM = 0x80900000`、
`PAYLOAD_BASE = 0xF0000000` 落在 System RAM 且避开 ABL 给内核留的 `0xA0000000+0x10000000`。

---

## 4. 今天完成的工作（全部真机验证）

### 4.1 构建环境（WSL2 Ubuntu）

- clang 21 / lld 21 / dtc / 7-Zip 26（≥23 才能读 APFS）/ qemu / fastboot / adb / gcc / nasm。
- theos 工具链：`L1ghtmann/llvm-project` 的 `iOSToolchain-x86_64.tar.xz`（589 MB，含 `ld`/`nm`/`otool`/`lipo`）。
- iOS SDK：`theos/sdks` 稀疏克隆只取 `iPhoneOS16.5.sdk`（233 MB）——Linux 上唯一可行来源。
- EDK2 依赖：stuart 要下 `Mu-Basetools`（GitHub release 直连超时）→ 经 `gh-proxy.com` 下载并**核对 sha256**，
  再把 `basetoolsbin_ext_dep.yaml` 的 `source:` 改成 `file://`。
- GitHub 在国内不稳：`xnu-deps/setup.sh` 的 `fetch()` 加了**重试 3 次 + `GH_PROXY` 前缀**（实测 `gh-proxy.com` 可用）。
- 坑：用 Python 改脚本会把整文件转成 CRLF，bash 立刻报 `set: -: invalid option`。改脚本后一律查 `CRLF: 0`。
- 坑：WSL 的 `/tmp` 会被清掉，日志要放家目录。
- 坑：1005 个文件的 mtime 落在未来 → `userland/build.sh` 认为 `select-system.py` 比 `.done-rootfs` 新，
  拒绝生成 `system.apfs`。修法：把未来时间戳改成过去（**必须用 epoch 表达**，`touch -d "18:00"` 在 WSL 里是 UTC）。

### 4.2 自编 alioth 的 UEFI

Mu-Silicium 上游已有 `Platforms/Xiaomi/aliothPkg`，但**仍需自己编一次**：

```bash
cd Mu-Silicium && python3 build_uefi.py -d alioth -r RELEASE
# → Build/aliothPkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd = 3,145,728 B = 0x300000（与 alioth.conf 逐字节一致）
```

- 必须 `rm -rf Build` 后再编（`build_uefi.py` 见到 `Build/` 就跳过 setup/update）。
- nasm 依赖要 Mono，按 README 用系统 nasm 顶替（`mu_nasm_extdep/Linux-x86-64` 里软链 `nasm`/`ndisasm`）。
- 主动放弃递归子模块（libspdm / openssl / cloudflare-quiche，数 GB），确认 `aliothPkg` 不依赖它们。

### 4.3 内核与系统镜像

- 内核：`mach.development.bcm2837`，15,128,488 B，31 个 `redwood_*.o` 全部编过。
  `xnu-build.sh` 打印 `xnu-build: device alioth -> -DPLATFORM_ALIOTH`；二进制里能找到只有 alioth 分支才有的字符串
  （`no avdd switch`、`this phone has only one touch part`），证明 `#ifdef` 切换机制生效。
- `xnu-deps/host/bin/xnu-clang` 加了：`-DPLATFORM_<DEVICE>=1`（按 `XNU_DEVICE`）。
- 用户态：rootfs 3.0 G + dyld shared cache 2.6 G → `userland/system.apfs` 2,492,223,488 B（608453 块）。
  用用户提供的 `firmware/iPhone10,3,iPhone10,6_16.5_20F66_Restore.ipsw`（6,165,698,198 B，与项目硬编码的
  CDN 文件大小完全一致，同一个 build 20F66）**离线提取**：
  `fetch.sh` 加了 `LOCAL_IPSW=` 参数，用 7z 直接从本地 IPSW 取 DMG（镜像里这三个 DMG 是**不压缩存储**的，7z 纯拷贝）。
- 决策记录：不起本地 http server 骗 `fetch-from-ipsw.py`（Python 的 `http.server` **不支持 Range**，脚本第一行就崩）；
  也不改 `fetch-from-ipsw.py` 支持 `file://`（内部全是 urllib Range 语义，改动更大）。

### 4.4 真机跑通（里程碑）

| 步骤 | 结果 |
|---|---|
| `fastboot boot alioth-boot.img` | 6 秒后 `getvar product` → `xnuloader` |
| loader 日志 | `display 1080 x 2400 at 9c000000`、`platform alioth` |
| `oem ramdisk` + `stage system.apfs` | 2.4 GB 上传 96 秒（25 MB/s） |
| `stage run-payload.bin` + `oem run` | 内核启动 |
| `fastboot reboot` | **Android 正常启动，原系统无损** |

内核内部：`apfs: volume 0 "System" … 45143 files, 16548 directories`、`BSD root: md0`、
`MiniIOMobileFramebuffer: display 1125x2436 on a panel of 1080x2400`、
`launchd.ios` → `runningboardd` → `backboardd` → `SpringBoard`(pid 7)。
`cpufreq: group 0/1/2 … 1804/2419/3187 MHz`、`on core 7 a loop ran at 167, now at 563`（3.4 倍）。
`buttons: step 1: map the PMIC arbiter (0xc440000, 0xc40a000, 0xe600000)` → SPMI 地址正确。

**关键坑（差点让整个项目停在这里）**：`redwood_goodix.c` 里 alioth 的 `TLMM_SIZE` 写成了 dts 的 **16 MB**，
而内核给 device memory 的子映射只有 **8 MB** → `io_map()` 的 `kmem_alloc(16 MB)` 失败 →
`__kmem_invalid_object_panic` → 触摸线程在 `bsd_utaskbootstrap` 阶段把整机打挂。
改成 1 MB（够到 pin 255）后主屏立刻就出来了。

**而这个 panic 一开始完全看不到**：panic 正文只交给调试器（既不上屏也不进 msgbuf），
是加了 `xnu/patches/panic-to-loader-log.patch`（在 `panic_trap_to_debugger` 里把正文写进 loader 日志）才读到的。

### 4.5 新增工具

| 工具 | 用途 |
|---|---|
| `k40-build/boot-one.sh` | 一键跑完一轮真机：进 BL → `fastboot boot` → `oem ramdisk` → `stage system.apfs` → `stage` 载荷 → `oem run` → 连拍截图（`SHOTS`/`GAP`）→ 取日志 → 回 Android |
| `k40-build/symbolize.py` | 用 `.dSYM` 的 DWARF 把 panic 里的地址反查成函数名。**内核主体只有数据符号，函数符号只在 dSYM 里**；`llvm-nm` 对主体无效 |
| `k40-build/pngcrop.py` | 从原始 BGRX 帧缓冲裁剪并放大存 PNG，用来读屏幕上的小字 |
| `tools/fdt_dump.py` | 纯 Python 的 FDT 解析器（这台机器没有 dtc） |
| `hackios-xnu-kernel-main/tools/check-constants.py` | 源码常量与设备树/ABL 表的一致性检查（19 项） |

---

## 5. 触摸：模拟点击为什么能用、手动为什么不行

**两条路径只在前半段不同**：

```
手动触摸：面板 → 触摸芯片(FTS) → SPI(QUPV3 SE4) → 引脚复用 → 内核队列 → backboardd → SpringBoard
模拟点击：                                          内核队列 → backboardd → SpringBoard
```

模拟点击从「内核队列」直接进入，**跳过了前四格**。所以模拟能用、手动不能用，
断点必然在前四格。逐格结果：

| 格子 | 状态 | 证据 |
|---|---|---|
| ① 面板→芯片 | ✓ **已修** | `focaltech: runtime ID 5652 valid after 1 attempt(s)`（§5.2） |
| ② 芯片→SPI | ✓ **已修** | `serial engine: firmware 0x101 … source clock 16000000 Hz` |
| ③ 引脚复用 | ✓ **已修** | `pins cs/clk/mosi/miso cfg 0x84 0x84 0x84 0x84, reset 0x2c3/0, int 0xc3/1`（§5.1） |
| ④ 队列→SpringBoard | ✓ 正常 | 模拟点击能打开 App Store |

**② 已修**：kona 的 QUPV3 wrap0 **没有 `m_ahb`/`s_ahb` 分支**（那是 sc7280/redwood 的）。
上游 `drivers/clk/qcom/gcc-sm8250.c` 实测：wrap0 只有 `core_2x`(halt_reg `0x23008`, vote bit 9)、
`core`(`0x23000`, bit 8)、`s0..s7`；`s4` 的 halt_reg `0x174cc`、cmd_rcgr `0x174d0`、vote bit 14 —— 都对。
我们却拿 sc7280 的 `0x17004/0x17008` 去判断那两个不存在的分支，永远读到一个「关着的别的时钟」，
于是误判「时钟打不开」→ 退化成手搓引脚（此时引脚还复用在引擎功能上，推不动）。
改法：`QUP_AHB_CLOCKS=0`（alioth），只等引擎自己的时钟。修完日志：
`goodix: serial engine: firmware 0x101, interface 0, parameters 0x20102864, source clock 16000000 Hz (select 1)`。
RCG 父频率 kona = 300 MHz(GPLL0_OUT_MAIN) / 150 MHz(GPLL0_OUT_EVEN)（`gcc_parent_map_0`）。

### 5.1 ③ 已修：kona 的 TLMM tile 基址（2026-10-22 深夜，真机验证）

iPhone 侧的 `ml_io_map` 没问题，问题在**物理基址**。不要用「index × 4 MB」推算；
以小米官方 K40 内核为准（MiCode/Xiaomi_Kernel_OpenSource，分支 `alioth-r-oss`，
`drivers/pinctrl/qcom/pinctrl-kona.c` 顶部）：

```
#define WEST  0x00100000      // 相对 TLMM 基址 0x0F000000
#define SOUTH 0x00500000
#define NORTH 0x00900000
```

即 `NORTH = 0x0F900000`、`SOUTH = 0x0F500000`、`WEST = 0x0F100000`，pin 寄存器 = `tile + 0x1000 × 全局 GPIO 号`。
之前按 `0x0F800000/0x0F400000` 映射，读写落在 tile 之间的空洞里（iomem 里整块 16 MB 都算 pinctrl，但空洞
未实现、读回 0），所以「引脚全 0、芯片没有时钟」。

`redwood_goodix.c`：`TLMM_NORTH_PHYS 0x0f900000`、`TLMM_SOUTH_PHYS 0x0f500000`（`TLMM_TILE_SIZE 0x90000`，
`gpio_base()`：pin ≤ 11 → north，其余 → south）。`redwood_haptic.c` 的 `TLMM_PHYS` 同步改成 `0x0f500000`。
真机证据（`k40-build/r4.log.txt` / `r6.log.txt`）：

```
goodix: pins as they are: miso 0x1 mosi 0x1 clk 0x1 cs 0x1 reset 0x1 int 0x1
goodix: as found: … pins cs/clk/mosi/miso cfg 0x1 0x1 0x1 0x1, reset 0x1/0, int 0x1/0
goodix: powered, on the serial engine: … pins cs/clk/mosi/miso cfg 0x84 0x84 0x84 0x84, reset 0x2c3/0, int 0xc3/1
```

### 5.2 ① 已修：本机芯片是 0x5652，而且自带固件

Android dmesg 里 `fts_wait_tp_to_valid: TP Ready, Device ID:0x5652`，不是 redwood 的 FT3680（0x5662）。
K40 的 FTS 芯片把固件放在自己的 flash 里，**复位释放后直接跑应用**，不会停在 boot ROM 等下载，所以
`focaltech_probe()` 在 alioth 上先 `gpio_set(PIN_RESET,true); sleep_ms(300);` 再读运行态 ID（0xA3/0x9F），
`focaltech_id_ok()` 同时接受 `0x56/0x62` 与 `0x56/0x52`。日志：

```
focaltech: runtime ID 5652 valid after 1 attempt(s)
goodix: focaltech touch screen ready; the interrupt line is looked at every 8000 us
focaltech: so far 547 reports in 547 looks (0 bad), 125 finger positions …  reports 240 a second
```

### 5.3 电源键/音量减：PON 是 gen2（subtype 0x04）

PM8150 的 PON 块 type 0x01 / subtype 0x04 = vendor 驱动的 `PON_GEN2_PRIMARY`（`qpnp-power-on.c`）。
gen2 的状态位与分体式 PMK8350 完全不同：**KPDPWR = bit0，RESIN = bit1，CBLPWR = bit2**（分体式是 0x80/0x40）。
本机空载 `status = 0x04`（CBLPWR 位常置），如果还用 0x80/0x40 就永远判成「松开」。
`redwood_buttons.c` 的 alioth 分支已改成 `0x01/0x02`，subtype 接受 0x04。
**真机已验证**（2026-10-22 深夜 `k40-build/r7.log.txt`、2026-10-23 `r9/r13`）：
电源、音量加、音量减都能读到按/放（`power PRESSED`、`volume up PRESSED`、`volume down PRESSED`，
`so far 2 presses of power, 5 of volume up, 6 of volume down`）。

### 5.4 音量键到 SpringBoard 的完整链路（已通）

```
PM8150 PON/GPIO6 → redwood_buttons.c → /dev/redwood-touch
  → libredwood.dylib（backboardd 内，inject.c）发 HID Consumer 0xE9/0xEA
  → backboardd: "[Button] VolumeIncrement/Decrement page:0xC usage:0xE9"（确认收到）
  → Darwin 通知 com.redwood.button.volume_up/down
  → libredwood-sb.dylib（SpringBoard 内，inject_sb.c）抓到的 SBVolumeControl 实例
  → -increaseVolume / -decreaseVolume + -_presentVolumeHUDWithVolume:（type encoding `v20@0:8f16`）
```

关键坑（**会让 SpringBoard 崩溃、屏幕变成黑屏加载页**）：

- `SBVolumeControl` **没有 `+sharedInstance`**。`objc_getClass("SBVolumeControl")` 后直接发未声明的
  selector 会抛 `NSInvalidArgumentException`，SpringBoard 直接 SIGABRT，用户看到的就是黑屏转圈。
- 正确做法：hook `-initWithHUDController:ringerControl:telephonyManager:conferenceManager:` 抓住
  SpringBoard 自己创建的那个实例；它只有实例方法 `-increaseVolume`/`-decreaseVolume`/`-volumeStepUp`
  /`-volumeStepDown` 等。方法可以用 `class_copyMethodList` 打印确认，不要靠猜。
- **真正的 HUD 卡点**：`mediaserverd` 没有启动（`mkjobs.py` 注明「没有声音也没有相机就不启它」），
  日志里 `com.apple.audio.AudioSession` / `SystemSoundServer-iOS` 都是 `No such process`，
  于是 `_isHUDDisplayableWithReason:` 判 NO，HUD 不出现、音量也不变。
  当前方案是直接调 `-_presentVolumeHUDWithVolume:` 把 HUD 拉起来，电平由 userland 自己维持
  （0.5 起步，每按一步 ±1/16），**没有真实音频**；真音量要等音频里程碑（adsp=1 + sound=4 + mediaserverd）。
- 外观已知差异：iPhone X 的音量键在左侧、iOS 把音量条画在屏幕左侧；K40 按键在右侧，所以看起来「反了」。
  这是 iOS 原生布局，不是移植 bug；若要镜像到右侧，需要另 hook HUD 视图布局（暂未做）。

### 5.5 电量：PM8150B fg-gen4 硬件电量计（已通）

借的是 Gsjsjzhznsz/ios-raphael 的 `docs/FLASH-T13.md`（同一代 PM8150B，`qcom,fg-gen4`）。
本机设备树里同样有 `qcom,pm8150b@2/qpnp,fg/{qcom,fg-batt-soc@4000, qcom,fg-batt-info@4100, …}`。
`redwood_battery.c` 在 alioth 分支自己走 SPMI（PMIC arbiter，channel 编码 sid+peripheral，仍复用
`redwood_spmi_lock`），默认开启（`battery=0` 可关）。寄存器与换算全部按 raphael 文档：

| 量 | 位置 | 换算 |
|---|---|---|
| SOC | `fg-batt-soc+0x09`，影子 `+0x0A` | 255→100、0→0、其余 `(raw-1)*98/253+1` |
| 电压 | `fg-batt-info+0xA0`（16 bit） | `uV = raw × 122070 / 1000` |
| 电流 | `fg-batt-info+0xA2`（15 bit 补码） | `uA = raw × 488281 / 1000`，放电为正 |
| 电池在位 | `fg-batt-info+0x07` | bit0..2 任一置位 = 缺电池 |
| 充电状态 | SMB5 `chgr+0x06` | 1–4 充电中、5 充满 |
| 外部电源 | SMB5 `usb+0x10` bit4 | USBIN_PLUGIN |

读到后填 `struct redwood_battery_state` → `redwood_battery_report()` → sysctl `kern.redwood.battery_*`
→ SpringBoard（`inject_sb.c` 里读这些 sysctl 并 `battery_post_notifications()`）。真机证据（`r9/r12/r13`）：

```
redwood: battery: SOC=95% battery=1 charger=1 charging=1
```

**背光/数字化仪**（之前开机被 SpringBoard 判成 `backlight-off; digitizerEnabled: NO`，触摸全被丢弃）。
2026-10-22 23:40 的 `r6` 轮里，开机 50 秒时屏幕已经是亮的、用户已经在「设置」里点按（`k40-build/r6.png`），
没有先按侧键——说明这一轮没有触发 `backlight-off`。**待确认**是否稳定（可能和这一轮用户提前触摸/按键有关）；
如果复现，线索仍在 `MiniIOMobileFramebuffer.cpp` 的亮度/显示状态上报。

**第三个问题（侧键对 iOS 不可见）**：

```
buttons: the PM8150's power-on block says type 0x1, subtype 0x4
        ... which is not what this driver knows (type 0x1, subtype 0x9): left alone
```

PM8150 的 PON 块 subtype 是 **0x4**（redwood 的 PMK8350 是 0x9），驱动以前直接放弃了整块。
已改为接受 subtype 0x4，并按 gen2 用 bit0/bit1（详见 §5.3）。寄存器转储（空载）：
`buttons: power-on block's registers 0x00..0x0f: 01 01 11 00 01 04 00 00 03 00 00 00 00 00 00 00`，
`status = 0x4` 就是 CBLPWR 位常置，不是按键。
旁注：SPMI 偶发 `the transfer was dropped`（一轮 1258 次里 1–2 次），不影响按键识别，但说明读超时偏短。

---

## 6. 外部参考：Gsjsjzhznsz/ios-raphael

- **Redmi K20 Pro（raphael，SM8150/骁龙 855）**上跑 Apple XNU + iOS 16.7.16，
  基于 `dipa-studio/ios-sweet`，`fastboot boot` 临时启动，已到 **iOS 锁屏**（未证明解锁后的主屏），
  GPU 无驱动用 CPU 软渲染。**机型与我们不同（SM8150 vs SM8250）**。
- 关键补丁：**`0093-raphael-touch-tlmm-south.patch`** —— 标题就是「TLMM south tile / 触摸供电根因定位」。
  原文（SM8150）：TLMM 拆成 per-tile 块，
  `SOUTH 0x00D00000, NORTH 0x00900000, EAST 0x00500000, WEST 0x00100000`（相对 TLMM 基址 `0x03000000`），
  「映射 TLMM 基址本身会把每次 mux/output/rail-power/reset 写进未实现区域：
  触摸 IC 从未上电、SDA/SCL 从未复用成 qup19 —— 正是 t10 日志里『总线空闲/全零』的特征」。
  → **这段知识直接命中我们 ③ 号断点**，但**基址数值与机型强相关**：SM8150 的 tile 顺序是
  {west, east, north, south}，kona 是 {west, south, north}，我们按 index×0x400000 推算后实测仍全 0，
  说明还差一步（kona 的 CAF 布局与上游 pinctrl-msm 的命名资源布局未必一致）。
- 其它可借鉴的：他们的 `NOTES.md`/`WORKLOG.md` 记录了「**45 秒重启 = 触摸线程倒计时在卡死的系统上触发**」，
  与我们 21:41 那次「模拟侧键后约 4 秒整机复位」现象同类，值得对照读。
  另有 `0104 fix: one unbalanced paren in the PON classifier ternary chain` —— 他们也写了 PON 分类器，
  说明 PM8150 的 PON 处理是有坑的，值得抄。

---

## 7. 现在能跑什么、怎么跑

> 交付包的入口是**包根目录**的 `boot-one.bat`（Windows，双击即可）/ `boot-one.sh`（Git Bash）
> ——镜像在 `boot/`，产物在 `runs/`；直接启动不需要下载固件。本节保留的是当时工作区（`k40-build/`）的原始记录。

```bash
cd ~/k40                                       # WSL2
DEVICE=alioth ./xnu-build.sh -j$(nproc) -k      # 只编内核
./common/build.sh alioth                       # 内核 + loader + 系统镜像 + boot.img
```

改过 `hackios-xnu-kernel-main/xnu/files/**` 之后要手工同步：`cp -a xnu/files/. xnu-src/xnu-8796.121.2/`

**改 GPU 驱动的瘟疫点（2026-10-23 实测）**：`bsd/dev/redwood_adreno.c` 有**两份**，
`xnu/files/bsd/dev/`（overlay 源）和 `xnu-src/xnu-8796.121.2/bsd/dev/`（真正的构建树，`apply.sh` 只在
目录**不存在**时才拷 overlay）。两份都改，否则编出来的内核还是旧的。`xnu-build.sh` 单独跑时必须带
`XNU_DEVICE=alioth`（否则没有 `-DPLATFORM_ALIOTH`，地址全是 redwood 的）：

```bash
cd ~/k40 && XNU_DEVICE=alioth ./xnu-build.sh -j$(nproc)    # 日志重定向到 out/*.log
```

编完 `grep -c "error:"` 应为 0；日志末尾 `exported name not in import list ... Private.symbolset Error 1`
是**既有噪声**（10-22 的旧日志里就有 222 条），`mach.development.bcm2837` 照常生成。改完把
`BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837` 拷成 `k40-build/kernel.bin`，
再用 `strings` 确认新字符串（`adreno_soc`、`a650_gmu.bin`…）在里面。

**GPU 固件进启动卷**：驱动从 RAM 盘的 `fw/` 读固件，`userland/build.sh` 只有检测到 `~/k40/fw-gpu/`
才把内容拷进 `root/fw/`（**`fw-gpu` 目录本身不会自动创建**）。手工最小路线（4 MB，不碰 2.4 GB 的 `system.apfs`）：

```bash
cd ~/k40/userland && mkdir -p root/fw && cp ~/k40/fw-gpu/* root/fw/
python3 ../tools/apfs/mkapfs.py -z --plain fw -o root.apfs redwood=root   # --plain fw: fw/ 下不压缩
cp root.apfs <workdir>/k40-build/root.apfs
```

真机（**必须在 Git Bash 里跑**；如 `C:\Program Files\Git\bin\bash.exe`。用 WSL 的 `bash` 会因为
`/d/...` 路径不存在而落到 WSL 的 adb，看不到设备——2026-10-23 复核：WSL 里 `adb devices` 是空列表，
fastboot 更是直接没有 USB 通道，只能走 Windows）：

```bash
cd k40-build && SECS=45 SHOTS=3 GAP=5 bash boot-one.sh
# 留在 iOS 不自动退出：加 KEEP=1（脚本拷完日志就退出，内核继续跑 loader_return_after 秒）
# 只跑内核（不 stage 2.4 GB system.apfs）：SYS= bash boot-one.sh   → 载荷自己的 root.apfs 就是根
```

PowerShell 里等价的调用（本会话验证可用）：

```powershell
$env:TAG="s1ios"; $env:SECS="45"; $env:SHOTS="2"; $env:GAP="10"
& "C:\Program Files\Git\bin\bash.exe" "<workdir>\k40-build\boot-one.sh"
```

**生成载荷（2026-10-22 的教训）**：不要用 `wsl -lc "… --cmdline \"…\""`，引号会被剥掉。
用 Windows 的 Python 直接跑：

```powershell
# 先把内核和 root.apfs 放到 k40-build（kernel.bin / root.apfs）
& python.exe `
  \\wsl$\<发行版>\home\<用户>\k40\xnuloader\mkpayload.py `
  -o k40-build\run-payload.bin kernel=k40-build\kernel.bin ramdisk=k40-build\root.apfs `
  --cmdline "loader_return_after=1800 epoch=<epoch> sb_delay=8 touchscreen=1 buttons=1 touch_stat=5 cpufreq=1 bootcpu=7 cpus=8"
# 校验：k40-build\inspect_payload.py 会打印 cmdline 全文
```

改过 **userland**（`hackios-xnu-userland-main/userland/src/inject.c`、`inject_sb.c` 等）只需要重建
**启动卷** `root.apfs`（4 MB，payload 的 `ramdisk=`），不用碰 2.4 GB 的 `system.apfs`：

```powershell
wsl -d Ubuntu -- bash -lc 'bash <workdir>/k40-build/build-dylibs.sh'
```

脚本编译 `libredwood.dylib` / `libredwood-sb.dylib`，拷进 `userland/root/lib/`，再 `mkapfs.py` 生成
`root.apfs` 并复制回 `k40-build/root.apfs`。随后重新生成 `run-payload.bin`（`ramdisk=root.apfs`）即可。

**稳定的启动参数组合**（不要带 `tlmm_scan` 和 `demo_lock`，见 §8）：
`touchscreen=1 buttons=1 touch_stat=5 cpufreq=1 bootcpu=7 cpus=8 loader_return_after=600`。
调试时可以加 `-v`；只是使用/演示时**不要加**，否则内核日志会叠在 iOS 界面上（§8）。

**GPU 调试用的两组参数**（2026-10-23）：

```
# 只跑内核步骤、不启动 iOS（日志最短，GPU 步骤就在末尾）
adreno_soc=a650 adreno=1 adreno_return=1 adreno_watch=20 bootcpu=7 cpus=8 loader_return_after=90

# 进 iOS（GPU 步骤跑完继续启动系统）
loader_return_after=1800 epoch=1792659000 sb_delay=8 touchscreen=1 buttons=1 touch_stat=5 \
cpufreq=1 bootcpu=7 cpus=8 adreno_soc=a650 adreno=1 adreno_watch=10
```

驱动注释明确要求 GPU 步骤期间**不要带 `touchscreen=1`**（触摸驱动会插话把日志末尾挤掉）；
用 `adreno_return=1` 时根本不会起用户态，这两条就不冲突。

注入工具（内核侧 `redwood_input.c`）：`touch_demo=1`（定点点击）`2`（竖向扫描）`3`（上滑）
`5`（按键唤醒→上滑解锁→点击）`6`（只唤醒+解锁不点击）；`demo_lock=N`（第 N 次时按侧键）；
`touch_demo_x/y`（0–65535 归一化坐标）、`touch_demo_ms`、`touch_demo_after`、`touch_demo_pressed_ms`。

**取日志的三个办法**

1. 运行中：`fastboot oem log` + `fastboot get_staged x.log`（只有 loader 自己的日志 + 它定时抓的尾部）
2. 运行结束后回 Android：`adb shell "su 0 dd if=/dev/block/by-name/logdump of=/data/local/tmp/ld.bin bs=1M count=2"`
   + `adb pull`（**内核日志在这里**；注意 logdump 里可能混着上一次运行的残留）
3. 屏幕小字：`fastboot oem screenshot` → `get_staged` → `pngcrop.py`

---

## 8. 踩过的坑（别再踩）

| 坑 | 现象 | 处理 |
|---|---|---|
| `fastboot stage` 前没发 `oem ramdisk` | `FAILED (remote: 'bad size')` | 先 `fastboot oem ramdisk`（它把 max-download-size 从 0x3f00000 改成 0xffffffff 并指向驻留区） |
| 内核日志不在 `get_staged` 里 | `oem log` 只能拿到 loader 的 | 内核那份被写进 `logdump` 分区；`compose` 之后 staged 被覆盖成 1 KB |
| panic 正文读不到 | 只有 `cpu_signal failed in DebuggerXCallEnter` | 加 `xnu/patches/panic-to-loader-log.patch` |
| `TLMM_SIZE` 用 dts 的 16 MB | `io_map` 的 kmem_alloc 失败 → panic | device memory 子映射只有 8 MB |
| kona 的 `m_ahb/s_ahb` 不存在 | 误判「时钟打不开」 | 只等引擎自己的 CBCR |
| `tlmm_scan=1` 的 2 MB 额外映射 | loader 卡死 → 看门狗复位 → 回到 Android | 已删除该探针 |
| 模拟侧键（`demo_lock`） | 约 4 秒后整机复位 | 原因未查，会话里不要用 |
| `loader_return_after=90` | 用户以为「进不去苹果系统」 | 那是我设的短超时；长会话用 600–3600 |
| Python 改脚本 | bash 报 `set: -: invalid option` | 会把文件转成 CRLF；改完查 `CRLF: 0` |
| 用 `wsl -lc "... --cmdline \"...\""` 打包 | PowerShell/wsl 的引号被剥掉，cmdline 只剩第一个词（`loader_return_after=1800`），内核缺 `cpus=8 bootcpu=7` → loader 的 USB 服务被饿住，所有 `fastboot` 都 `no link` | 用 **Windows 的 Python 直接跑** `~/k40/xnuloader/mkpayload.py`（kernel/ramdisk 先拷到 `k40-build`），再用 `inspect_payload.py` 校验 cmdline |
| `???????????? fastboot` | 这不是卡死：PnP 里是 `USB\VID_18D1&PID_D00D\XNULOADER`，loader 在线；`no link` 通常是 cmdline 缺参数或僵尸 fastboot 进程占着端点 | 先杀僵尸进程：`Get-Process fastboot \| % { $_.Kill() }`（`Stop-Process` 会报 Access denied）；再 `fastboot reboot` |
| 脚本里的 `fastboot get_staged` 卡住 | 退出后留下 2–3 个 `fastboot.exe`，之后每次 `fastboot` 都 `no link` | 同上，`.Kill()` 清理 |
| cmdline 带 `-v` | 内核控制台日志叠在 iOS 界面上，遮住 UI | 正常使用/演示时去掉 `-v`；日志仍会进 loader log 和 msgbuf |
| 猜 SpringBoard 私有 selector | 未声明的 selector 抛 `NSInvalidArgumentException`，**SpringBoard 直接 SIGABRT**，屏幕变成黑屏加载页（pid 7 → 41） | 先用 `class_copyMethodList` 打印真实方法（`volume_methods()` 的思路），确认后再调用 |
| 音量条不出来 | `mediaserverd` 没启动 → `com.apple.audio.AudioSession` 查无此进程 → `_isHUDDisplayableWithReason:` 为 NO | 暂用 `-_presentVolumeHUDWithVolume:` 直接显示；真音量等音频里程碑 |
| 音量条在屏幕左侧 | iPhone X 的按键在左边，iOS 固定画在左侧 | 非 bug；要镜像到右侧需 hook HUD 视图布局 |
| WSL `/tmp` | 日志莫名消失 | 放家目录 |
| 未来 mtime | `system.apfs` 不生成 | 用 epoch 改时间戳 |
| 只改了一份 `redwood_adreno.c` | 编出来的内核还是旧行为 | overlay（`xnu/files/`）和构建树（`xnu-src/.../bsd/`）两份都要改；`apply.sh` 见目录存在就跳过 |
| `xnu-build.sh` 不带 `XNU_DEVICE` | 内核是 redwood 的地址 | `XNU_DEVICE=alioth ./xnu-build.sh` |
| 构建日志尾部 `Private.symbolset Error 1` | 以为编译失败 | 是既有噪声（旧日志 222 条），`mach.*` 照常生成；看 `grep -c "error:"` 和二进制时间戳 |
| 没有 `~/k40/fw-gpu/` | 内核打印 `the small image has no fw/a650_gmu.bin`，GPU 不启动 | `build.sh` 只**读**这个目录不会建它；建目录放四个 `a650_*` 后重做 `root.apfs` |
| `mkapfs.py` 不带 `--plain fw` | `fw/` 被压缩，驱动按原样读固件会失败 | `mkapfs.py -z --plain fw -o root.apfs redwood=root` |
| 用 WSL 的 bash 跑 `boot-one.sh` | `adb devices` 空、fastboot 看不见设备 | 用 `C:\Program Files\Git\bin\bash.exe`（WSL2 没有 USB 通道） |
| `git diff > patch` 后 `git apply` 全拒 | 补丁里全是 CRLF | 用 Python `subprocess` 写原始字节（`git -C repo diff` 的 stdout），别用 PowerShell 重定向 |
| **`boot-one.sh` 一直停在 Android / 卡住**（2026-10-23 修） | ①`fastboot` 在没有设备时不会退出，永远打印 `< waiting for any device >`；②`adb reboot bootloader` 在多设备（或多台模拟器/旧进程）时会失败，手机留在 Android，脚本随后卡在 `fastboot`；③`SYS=${SYS:-system.apfs}` 让 `SYS=` 空赋值无效，每次白传 2.4 GB | ①所有 `fastboot` 调用包 `timeout`；②只用 `adb devices` 里唯一一台 `device` 状态机，多于/少于 1 台直接报错退出；③`adb reboot` 后 30 s 内轮询 `fastboot devices`，等不到就报 “never reached the bootloader” 并退出，不挂死；④改成 `SYS=${SYS-system.apfs}`（只区分“未设置”与“设为空”）。修后 `SYS= TAG=g9b SECS=60 bash boot-one.sh` 全程约 2 分钟正常结束 |
| K40 频率计数器寄存器与 redwood 不同 | step 5 报 “counter did not finish” | kona：`xo_div4_cbcr 0x4300c`（redwood `0x6200c`）、GCC debug mux 选 GPUCC `0x163`（`0x146`）、GPUCC post-div 字段 `0x3`（`0xf`）；厂商 `clk-debug.c` 写的是 `post_div_val - 1`，即 **1** 不是 2。已参数化进 `struct adreno_soc.counter_*` |
| SMMU SMR 写读回 0（step 18） | GPU 流掩码用 `0x400` 被拒 | K40 设备树 `iommus = <&adreno_smmu 0 0x401>`（GMU 是 `5 0x400`）；加 `soc->core_mask` 参数化后 SMR0 = `0x84010000` 被接受 |
| `smmu_layout()` 尺寸必须相等 | K40 算出 `0x10000`，dt 写 `0x20000` → step 8 失败 | dt 只是富余空间，改成“算出的寄存器总长 > dt 大小”才失败 |
| `logdump` 拿到旧日志 | `g22b.kernel.txt` 与 `g22a.kernel.txt` MD5 相同，其实是上一次运行的内容 | logdump 不清空；要按本次运行独有的字符串（如新的 SMR 值、`step 19`）`rfind` 定位，或改读 loader 环形日志（`k40-build/g2?b.log.txt`） |

---

## 9. GPU（Adreno 650）移植准备：第一阶段完成（离线就绪）

### 9.1 基础工作（全部离线完成，真机就绪）

**目标机已有**：
- Redwood 上游已写好完整的**寄存器级逐步唤醒驱动**（`redwood_adreno.c` 193 KB），专为 POCO X5 Pro（Adreno 642L）；
- Adreno 650（K40/SM8250）是同家族（a6xx），所有块地址/寄存器偏移全相同（kgsl-3d0@3d00000/gmu@3d6a000/gpucc@3d90000/smmu@3da0000）；
- 差异仅在**参数表**，添加第二行 `soc_a650` 即可，无需重写驱动。

**离线已完成**：

| 项 | 完成情况 | 位置 |
|---|---|---|
| 驱动源码（修复接口 + 添加 `a650` 参数表） | ✅ | `alioth-gpu-port/files/xnu/files/bsd/dev/redwood_adreno.c`，已同步到 `hackios-xnu-kernel-main` |
| `redwood_gpu_layout.h` | ✅ | `alioth-gpu-port/files/xnu/files/bsd/sys/` → 内核 build tree |
| `alioth.conf` 参数 | ✅ `FIRMWARE="fw-gpu"` `WIFI_ATH11K=0` | `hackios-xnu-kernel-main/common/devices/` |
| 工具校验：`alioth.py check` `alioth.py dt` | ✅ 0 failures | `alioth-gpu-port/evidence/device/`（DT + 固件提取自真机 Android） |
| `zap_header` 修复：K40 `a650_zap.mdt` = 0x1acc 两页，分配 `round_page` | ✅ 已改接口 `zap_header(phys, size_out)`，传 `header_size` 给 SCM | 驱动 line 1806, 1853, 2815 |
| `zap_header` 不再把 >1 页当失败（K40 正好两页） | ✅ `alioth-gpu-port/files/tools/alioth.py` |
| GMU 固件分配：不再计入 ITCM/DTCM 内的请求 | ✅ `alioth.py` 已修，与驱动分配逻辑一致 |
| SQE 版本读取：从 offset 4 读（Linux 就是这么读的，不是 offset 0） | ✅ `alioth.py` 已修，K40 `a650_sqe.fw` 版本合法 |
| WSL build tree：同步两份源码（overlay + 构建）+ 创建 `fw-gpu` 目录 | ✅ `~/k40/fw-gpu/` 已有四个固件：`a650_gmu.bin/a650_sqe.fw/a650_zap.mdt/a650_zap.b02` |
| 内核编译：符号集警告不影响产出，`kernel.bin` 已生成并含所有 `a650` 字符串 | ✅ `k40-build/kernel.bin` 15.1 MB |
| 重建 `root.apfs`：`root/fw/` 已放进四个固件（驱动从这里读） | ✅ `k40-build/root.apfs` 4 MB |
| 载荷生成：Windows Python 生成，cmdline 完整无截断 | ✅ `k40-build/run-payload.bin`，`inspect_payload.py` 验证 |
| `boot-one.sh` 增强：支持 `SYS=` 空参数，跳过 2.5 GB `system.apfs` staging | ✅ 缩短内核测试时间 |

### 9.2 离线可行性结论

**可行性：高**。所有差异都是数值差异，可以逐步验证；驱动的**逐步设计**（`adreno=N` 停在 N 步）正好适合：
- `adreno=1` 只读外部时钟/RPMh 资源名 → 没问题再推 `adreno=3` → `adreno=8/9` 读 SMMU → `adreno=12` 过 TrustZone/zap 签名 → 再决定 `15/16` 后续；
- 超管放行是最大风险点：SMMU 页表写/TrustZone SMC 调用，如果 hypervisor 不拦截就能过；但上游 redwood 在它的手机上已过，K40 有很大概率过；
- `zap_header` 修复是唯一真缺陷（不修复 K40 一定在 step 12 失败），已经修完。

### 9.3 真机逐步测试方案

| 步数 | Cmdline 片段 | 验证目标 |
|---|---|---|
| 1 | `adreno=1` | RPMh 能列出 `gfx.lvl`/`cx.lvl`/`mx.lvl` 的档位吗？ |
| 3 | `adreno=3` | GPUCC 寄存器能读回 bootloader 留下的值吗？ |
| 8/9 | `adreno=9` | SMMU ID 寄存器读得到吗？上下文分配过得了吗？ |
| 12 | `adreno=12` | TrustZone 接受 zap 签名吗？（到这步就能回答 SMMU/hypervisor 问题） |
| 15 | `adreno=15` | GMU 启动后读得到 `GMU_STARTED_MASK 0x100` 吗？ |
| 16 | `adreno=16` | RSCC 隐藏命令末字用哪个？当前是 `0x80000021`（redwood），Linux a650 是 `0x80000000`；要实测 |
| 17 | `adreno=17 adreno_speed=5` | GMU 能对 `525 MHz` 投票成功吗？ |
| 21/22 | `adreno=22` | 命令处理器退出安全模式，能画出三色帧吗？ |

> 驱动注释说明：`RSCC` 末字 `0x80000021` 有意保留，等真机确认后再改。

#### 9.3.1 真机结果（2026-10-23，`SYS=` 内核-only + logdump 取全量日志）

| 步 | cmdline | 结果 | 关键读数 |
|---|---|---|---|
| 1 | `adreno=1` | ✅ | `gcc pll votes 0x1206d7f`；RPMh `gfx.lvl@0x30050`/`cx.lvl@0x30000`/`mx.lvl@0x30010` |
| 2 | `adreno=3` | ✅ | `speed bin 2: an Adreno 650`；GPUCC 寄存器全可读 |
| 4 | `adreno=9` | ✅ | `cx_gdscr` 写 `0x222000` 回读 `0xf8222000`，`CX is on` |
| 5 | `adreno=9` | ✅（修 K40 计量表后） | `cxo 19200144 Hz`、`cx_gmu 200000396 Hz`、`cxo_aon 19199560 Hz`、`gx_gmu 0`、`ahb 47086216 Hz` |
| 6/7 | `adreno=9` | ✅ | GMU 计数器 `19199091 Hz`（19.2 MHz 晶振）→ “THE GPU BLOCK IS ALIVE”；RSCC 读得到 |
| 8/9 | `adreno=12` | ✅（放宽 dt 尺寸校验后） | `idr0 0x4c017e06`、`idr1 0x20000005`：6 个 SMR、5 个 context、8×0x1000；dt 的 0x20000 是富余空间 |
| 10/11/12 | `adreno=12` | ✅ | GMU DTCM 可读写；`0x42000201(0xd,…)` 返回 0（TrustZone 接受 zap 头） |
| 13/14/15 | `adreno=17` | ✅ | GMU 固件装入并运行；版本 `core 0x20010008`、`HFI 0x20000001` |
| 16 | `adreno=17` | ✅ | GMU HFI 队列起来；RSCC 程序按现有 `0x80000021` 也被接受 |
| 17 | `adreno=17` | ✅ | GMU 接受速度表/总线表/“start”/525 MHz；`THE 3D CORE HAS POWER AND ANSWERS`；3D 时钟 `524999528 Hz` |
| 18 | `adreno=22` | ✅（`core_mask=0x401` 后） | SMR0 写 `0x84010000`、SMR2 写 `0x84010001` 均被接受；`rbbm_status 0x1` |
| 19 | `adreno=20` | ✅（改取内核自有两页连续内存后） | `0x42000206`（give-up）、`0x42000201`（签名）、`0x42000202`（`SCM_PAS_MEM_SETUP`）全返回 0，随后 `TRUSTZONE HAS AUTHENTICATED AND STARTED THE ZAP SHADER` |
| 20 | `adreno=20` | ❌ **整机复位（当前唯一阻塞）** | 写 `CP_SQE_CNTL=1` 之前一切正常（`cp_apriv_cntl 0x6e`、`rbbm_status 0x1`）；写下去之后内核**再无任何输出**，约 0.5–1 s 后整机复位。第二轮已用控制实验确认：**同一寄存器写 0 完全无害、编核后空闲 3 s 也毫无问题，只有“启动”这个动作致命**（§9.5） |
| 21–22 | — | 未执行 | 被 step 20 挡住 |

### 9.4 不确定点：真机回答（2026-10-23）

| 点 | 结论 |
|---|---|
| RPMh 档位枚举（`gfx.lvl`/`cx.lvl`/`mx.lvl`） | ✅ 已答：AOP cmd-db `0x80860000` 能列出三路档位（`gfx.lvl@0x30050`、`cx.lvl@0x30000`、`mx.lvl@0x30010`），step 1 通过 |
| 频率计数器寄存器布局 | ✅ 已答：K40 与 redwood 不同，见 §8 新坑第一条 |
| SMMU 访问权限 | ✅ 已答：hypervisor 放行读；但 **SMR 必须按设备树掩码写**，GPU 是 `0x401`（不是 redwood 的 `0x400`），否则写读回 0 |
| `GMU_STARTED_MASK` | ✅ 已答：`0x100` 位可用，GMU 固件正常运行（`core 0x20010008`、`HFI 0x20000001`） |
| RSCC 末字 | ✅ 已答：`0x80000021` 被 K40 的 GMU 接受，无需改成 `0x80000000` |
| zap 内存地址 | ✅ 已答并修好：Mu-Silicium alioth.dtb 的 `pil_gpu_region`（`0x8681a000`）在 loader 给内核的物理窗口（`0xf4000000+0x180000000`）之外，读它会挂死；驱动改为 `kmem_alloc_contig()` 取两页内核自有连续内存 + `kvtophys()`，step 19 真机通过（`soc_a650.zap_memory = 0`） |

### 9.5 step 20（启动 CP）的排除记录与当前唯一结论（2026-10-23 晚，全部真机验证）

#### 这一轮拿到的关键资料

- **K40 自己的厂商内核源码**（`MiCode/Xiaomi_Kernel_OpenSource`，分支 `alioth-r-oss`，走 jsdelivr 下载，
  直连 GitHub 不通）：`drivers/gpu/msm/{adreno_a6xx.c, adreno_a6xx_gmu.c, kgsl_iommu.c, kgsl_iommu.h,
  a6xx_reg.h, adreno.h}`，已存 `alioth-gpu-port/reference/vendor-msm/`。这是这台机器的**权威顺序依据**。
- Linux 侧补齐 `arm-smmu.c`/`arm-smmu-qcom.c`/`io-pgtable-arm.c`/`a6xx_gpu.c` 到
  `alioth-gpu-port/reference/linux-msm/`。

#### 由厂商源码核实（推翻了两条先前猜测）

1. **寄存器偏移全对**：厂商 `a6xx_reg.h` 是“以 0x3d00000 为基的 dword 偏移”，换算后与本驱动
   `GPU_WORD()/GMU_WORD()` 逐条一致（`CP_SQE_CNTL 0x808`、`CP_APRIV_CNTL 0x844`、`CP_PROTECT_CNTL 0x84F`、
   `RBBM_STATUS 0x210`、`CP_RB_RPTR_ADDR 0x804/0x805`、`GMU_GX_SPTPRAC_POWER_CONTROL` = 本驱动
   `GMU_WORD(0x81)`＝`0x3d6a204`，`SPTPRAC_PWR_CLK_STATUS` = `GMU_WORD(0x50d0)`＝`0x3d7e340`）。
   → **不是写错寄存器地址**。
2. **SMMU 的 SCTLR 已经与厂商 GPU 默认一致**：`kgsl_iommu.h` 里 `HUPCF=BIT(8)`、`CFCFG=BIT(7)`；
   `arm-smmu-qcom.c` 的 `qcom_adreno_smmu_write_sctlr()` 对 GPU **强制 `HUPCF`**（“keep the GPU from
   hanging”），只有 kgsl 显式开 stall 才置 `CFCFG`。本驱动 `SMMU_SCTLR_SERVE_AFTER_FAULT = 1u<<8`
   就是 HUPCF，CFCFG=0。→ **不是“STALL 模式挂死”**（先前判断有误，已作废）。
3. **PTE 权限位与 Linux 一致**：`io-pgtable-arm.c` 的 `arm_lpae_prot_to_pte()` 对非 `IOMMU_PRIV`
   映射置 `ARM_LPAE_PTE_AP_UNPRIV = 1<<6`；本驱动 `PTE_CORE = PTE_GMU|PTE_UNPRIVILEGED`（bit6=1）
   与之相同；`IOMMU_PRIV`（bit6=0）只用于 kgsl 的“privileged”内存。→ **不是 PTE 权限问题**。
4. 厂商 `a6xx_rb_start()` 的顺序：`CP_RB_RPTR_ADDR` → `CP_RB_CNTL` → `CP_RB_BASE` → `CP_APRIV_CNTL`
   → `CP_SQE_INSTR_BASE` → `CP_SQE_CNTL=1` → `a6xx_send_cp_init()`（ring 发 `CP_ME_INIT`）→
   `a6xx_zap_load()` → `adreno_set_unsecured_mode()`（ring 发 `CP_SET_SECURE_MODE=0`）。
   与驱动的 step 20/21 基本一致，差别是：①没有 `CP_RB_RPTR_ADDR`（本驱动把 `CP_RB_CNTL` bit27
   “不写回读指针”置 1，因此不需要）；②厂商 `a6xx_start()` 里还有 `a6xx_hwcg_set`、VBIF reglist、
   TPL1 双三次权重、**`a6xx_protect_init()`（`CP_PROTECT_CNTL=0xB` + 32 条 `CP_PROTECT_REG`）**、
   GMU 计数器等本驱动未写；③厂商在 `a6xx_hw_init` 首尾有 `a6xx_gmu_set_oob(GMU_OOB_GPU_SET)`/`clear_oob`，
   本驱动没有 OOB 握手。
5. K40 的 SMMU 可用表项比预想的少：**SMR/S2CR 的 0 号、4 号、5 号表项写不进（回读 0）**；
   `space_bind()` 的自适应选表项是必需的（实测核心用 2 号）。

#### 这一轮的真机实验（文件名在 `k40-build/`）

| 运行 | cmdline 关键项 | 结果 |
|---|---|---|
| `g25a` | `adreno=20` + step 20 改为**逐条访问、每条前先打印** | 日志最后一行是 `step 20: start the 3D core's command processor`；紧随其后的 `the write to cp_sqe_cntl came back` **没有出现**，整机复位 |
| `g25b` | `adreno=20 adreno_direct=1`（第一版旁路） | 旁路写 S2CR 落在 4/5 号表项上写不进 → step 18 FAILED、CP 未启动、**设备存活**（顺带证实可用表项很少） |
| `g25c` | 第二版旁路（先用 `space_on()` 选到可写表项，再把该表项 S2CR 改成 bypass，ring/微码用物理地址） | step 18 通过（否则 step 20 不会执行）、step 20 **照样复位** → **不是 SMMU 拒绝取指** |
| `g25d` | 同上，但改用**重编的 loader**（note 周期 2 s → 250 ms） | 内核日志长度冻结在 `35056 B`，连续多条 note 都停在 announce；约 0.5–1 s 后复位 → 写下去后内核**再没执行下一条 printf** |

#### 当前唯一结论

`CP_SQE_CNTL=1` 这条 AHB 写下去之后，内核既不报错也不继续（printf 没执行），约 1 s 内整机复位
（PMIC `hw_reset reason1 0x2`）。两种可能，尚未区分：
- **(A) 写在 AHB 上挂住**（没有应答），CPU 停在 store 上；随后的复位来自别处（GPU/XPU/TZ）。
- **(B) 写返回了，但硬件在同一瞬间复位**，printf 来不及执行。

已排除：微码地址、zap 顺序、SMMU 翻译/取指、寄存器偏移、SCTLR 模式、PTE 权限。
**待查（按代价从低到高）**：
1. 厂商 `a6xx_start()` 里本驱动缺的前置写：`CP_PROTECT_CNTL=0xB`+32 条 `CP_PROTECT_REG`、
   `TPL1_BICUBIC_WEIGHTS_*`（a650 专属）、`GMU_CX_GMU_POWER_COUNTER_*`/`GPU_GMU_AO_GPU_CX_BUSY_MASK`、
   `a6xx_hwcg_set()`。
2. **`GMU_OOB_GPU_SET` 握手**（主机告诉 GMU “CPU 正在动 GPU，先别做电源管理”）；缺它时 GMU 可能
   在 CP 启动瞬间做 IFPC/GX collapse。厂商在 hw_init 开头 set、末尾 clear。
3. `a6xx_gmu_sptprac_enable()`：`GMU_GX_SPTPRAC_POWER_CONTROL(0x3d6a204)=0x00778000`，等
   `SPTPRAC_PWR_CLK_STATUS` bit3。本驱动从未写过（只读过状态，bit2 为 0 看似已开）。
4. 用 `adreno_sqe0` 之类的小开关做**控制实验**：把 `CP_SQE_CNTL` 写成 0（而不是 1），看是否也复位
   ——能立刻区分“这条写/此寄存器被 TZ 保护”还是“启动动作本身”。

#### 这一轮新增的工具与产物（重要）

- **loader 的日志节奏已可调并已重编**：`loader.c` 的 note 周期从 2 s 改成 **250 ms**（`hc_ms_since()`），
  `NOTE_SECONDS` 仍是 24，tail 仍 240 B（`k40-build/loader.c` 是可编辑副本，原件备份
  `~/k40/xnuloader/loader.c.bak`）。重编/重打包命令：
  ```bash
  wsl bash -lc 'bash ~/k40/xnuloader/build.sh && \
    python3 ~/k40/xnuloader/mkpayload.py -o ~/k40/out/usb-payload.bin \
      loader.efi=~/k40/xnuloader/loader.efi --usb && \
    cd ~/k40 && FD_BASE=0x9FC00000 FD_SIZE=0x300000 PAYLOAD_BASE=0xF0000000 UEFI_TARGET=alioth \
      python3 mkxnuimg.py -p out/usb-payload.bin -o out/alioth-boot2.img'
  ```
  **boot-one.sh 用 `IMG=alioth-boot2.img` 才会带上新 loader**；原镜像已备份为 `alioth-boot.orig.img`。
  注意：loader 在镜像的 XNUP payload 里，不是编 UEFI FD，所以改 loader 不需要重编 Mu-Silicium。
- 驱动新增 boot-arg：`adreno_direct=1`（step 18 用 `kmem_alloc_contig()` 给 3D 核的 ring/微码/scratch，
  地址用 `kvtophys()`，再把该流的 S2CR 改成 bypass=1<<16），用于把 SMMU 排除在外。
- step 20 的打印已改成逐条 `get()`（每条前有 `about to read ... at 0x...`），配合 250 ms note 即可定位
  “停在哪一条访问上”。
- **启动前 3 s 分步暂停**：step 20 在写 `CP_SQE_CNTL` 之前，每 500 ms 打印一次
  `rbbm_status / sptprac / gmu2host intr`。这样“写之前的状态”一定能被 loader 记下，并把
  “空闲的核被拿掉”和“启动动作本身”分开。

#### 第二次实验（2026-10-23 19:00–19:35，低代价项已全部试完）

| 运行 | 开关 | 结果 |
|---|---|---|
| `g26a` | `adreno_sqe=0`（控制：只写寄存器、不启动） | **设备存活 8 s 以上**：写返回、随后 9 条寄存器读全部成功、ring 命令发出（CP 未跑所以 FAILED），整机无复位 → **寄存器与写通路本身没问题；“启动”这个动作才是致命的** |
| `g26c` | `adreno_sptprac=1`（厂商的 SPTPRAC 上电）+ 400 ms 暂停 | 仍复位；且 `GMU_GX_SPTPRAC_POWER_CONTROL` 写 `0x00778000` **回读 0（写不进）**；`SPTPRAC_PWR_CLK_STATUS` 读 0（按位义=GX 电/时钟都在、SPTPRAC 未报 off） |
| `g26d` | `adreno_oob=1`（新中断位 30/31）+ 3 s 分步暂停 | 编核后**空闲存活 ≥2.5 s**（`rbbm_status 0x1`、`sptprac 0`、`gmu2host intr 0`），随后在启动那一步复位 → **不是“空闲核被 GMU 收走”** |
| `g26e` | 同上，暂停行加打印 `GMU2HOST_INTR_INFO` | 全程 `0x0`：**GMU 从不确认 OOB（GPU_SET）** |
| `g26f` | `adreno_oob=2`（旧中断位 16/24） | 同样从不确认（`intr 0`）→ OOB 这条路在本机不通（或被 hyp 拦），不能作为修复手段 |
| `g26g` | `adreno_rptr=1`（厂商对 APRIV GPU 的写法：给 `CP_RB_RPTR_ADDR` 一页、清 `CP_RB_CNTL` bit27） | 仍复位 |

#### 结论（第二轮之后）

- 使整机复位的就是 **`CP_SQE_CNTL=1` 这条“启动命令处理器”的写**；写成 0 完全无害。
- 编核之后**空闲 2.5–3 s 毫无问题**，所以不是空闲掉电/IFPC/GX collapse。
- SPTPRAC 的控制寄存器在本机**写不进**（回读 0），OOB 握手**不被确认** —— 这两条厂商路径在
  hypervisor 下走不通，也说明它们不是缺失的原因。
- 已排除项合计：微码地址、zap 顺序、SMMU 翻译与取指（含 bypass）、寄存器偏移、SCTLR 模式、
  PTE 权限、空闲电源、SPTPRAC、GMU OOB、`CP_RB_RPTR_ADDR`/bit27。
- **剩下的只有重活**：①把厂商 `a6xx_start()` 其余部分补齐（`a6xx_hwcg_set` 的约 20 个
  `RBBM_CLOCK_*`、VBIF reglist、a650 的 TPL1 双三次权重、`CP_PROTECT_CNTL=0xB`+32 条 protect、
  GMU 计数器/`GPU_GMU_AO_GPU_CX_BUSY_MASK`）；②设法看到“启动后那一瞬间”的硬件状态
  （CP_HW_FAULT / SMMU SGFSR 都读不到，因为核已复位；可考虑用 GPU 的 `CP_SQE_STAT_*` 或
  coresight/DBGBUS 在写之前布好、复位前轮询，但都要求另一次完整尝试）；③换一条验证路径：
  在 UEFI 环境（loader 里）用同一套寄存器顺序启动 CP，绕开 XNU 的异常/中断环境，判断是否
  XNU 侧（SError/中断）导致的复位。

#### 第三轮：Android 侧“金标准”对照（2026-10-23 19:40，结论：本机取不到运行中的寄存器）

目标：在 Android 里读 kgsl 正在使用的 GPU 寄存器值，做“已知正确”的对照。结果：

- **`/dev/mem` 不存在**（内核没开 `CONFIG_DEVMEM`），用 `mknod` 造出来也返回
  “No such device or address”；`devmem` 因此读不到任何 MMIO。已删掉造出来的节点。
- **没有 kgsl debugfs**（`/sys/kernel/debug/kgsl` 不存在，`CONFIG_DEBUG_FS` 关闭）；
  `kgsl-3d0/snapshot/dump` 是空的（没有发生过 fault）。
- 能拿到的是 kgsl 的**特性开关**（`/sys/class/kgsl/kgsl-3d0/`，全部有值，已记录）：
  `ifpc=1`、`hwcg=1`、`lm=1`、`acd=1`、`popp=0`、`bus_split=1`、**`sptp_pc=0`**（SPTP 掉电关闭，
  说明厂商根本不用 SPTPRAC —— 与第二轮的“该寄存器写不进”一致）、`preemption=1`、
  `skipsaverestore=1`、`idle_timer=80`、`default/min_pwrlevel=6`（空闲 305 MHz）、`reset_count=65`、
  `ft_policy=0xC2`、`temp=31800`。
- Android 的 `dmesg` 提供了两条有用事实：SMMU **“stream matching with 6 register groups”**
  （与 idr0 的 6 个 SMR 一致）；**`a650_zap: loading from 0xea100000 to 0xea101000` 并在 14 s
  “Brought out of reset”**（即厂商在开机 14 s、首次启动 GPU 时由 PIL 把 zap 放到 0xea100000；
  该地址在 loader 给内核的物理窗口之外，不能直接用）。

#### 第三轮之后：还能做的只有重活，决定暂停

`adreno_zap_first=1`（把 step 19 提到 step 17 之前，唯一没试过的顺序）已实现并真机试过：
`step_zap_load()` 开头就要求 `core_is_on`（3D 核已上电），在 step 17 之前它必然失败，
所以这条顺序在硬件上大概率也不成立（zap 要在 GPU 上跑）。

**结论：低代价 + 中等代价的手段已经用尽，GPU 暂停。** 若要回来，只剩：
①补齐厂商 `a6xx_start()` 的剩余写；②在 loader/UEFI 里重放同一顺序启动 CP（绕开 XNU）；
③在写之前布好 `CP_SQE_STAT`/DBGBUS 的轮询点。三者都要求整轮改造，不再是“一跑一看”。

---

## 10. 下一步（按优先级）

> **2026-10-23 晚的用户决定：GPU 先按“修不好”处理，转向 Wi-Fi；GPU 的实验清单保留在 §9.5，随时可回来。**

1. **Wi-Fi（当前主线）**：QCA6390 走 PCIe（`17cb:1101` WLAN + `17cb:0306` BT over MHI），
   与 redwood 的 WCN6750（AHB）不是同一条路。`alioth.conf` 已置 `WIFI_ATH11K=0`。
   开工顺序建议：①先在内核里把 PCIe 总线/控制器枚举到设备（读 vendor/device、BAR）；
   ②再决定是移植 `ath11k` 的 `pci.c`/MHI 路径还是走 firmware 下载的 “QMI over MHI” 最小链；
   ③固件在手机 `/vendor/firmware/qca6390/`（`amss20.bin`、`bdwlan.*`、`wlanmdsp.mbn`）。
2. **GPU step 20（暂停）**：低代价实验已在 19:00–19:35 试完（§9.5 第二轮表：控制实验、SPTPRAC、OOB 新旧位、
   `CP_RB_RPTR_ADDR` 全部无效）。回来时只剩重活：①补齐厂商 `a6xx_start()` 的其他写（`RBBM_CLOCK_*`、
   VBIF reglist、a650 的 `TPL1` 双三次权重、`CP_PROTECT_CNTL=0xB`+32 条 protect、GMU 计数器）；
   ②在 loader（UEFI）里用同一套顺序启动 CP，绕开 XNU 的异常/中断环境，判断复位是不是 XNU 侧引起；
   ③在写之前布好 `CP_SQE_STAT`/DBGBUS 之类能在复位前轮询的状态点。
3. **音频里程碑（音量键的真音量就等它）**：起 `mediaserverd`（`mkjobs.py` 当前不启它）+
   `adsp=1` + `sound=4`，接通 DSP/TDM/功放。之后 `SBVolumeControl` 的 `_isHUDDisplayableWithReason:`
   才会放行，`increaseVolume/decreaseVolume` 也才有真实效果；届时可以去掉 `_presentVolumeHUDWithVolume:`
   的替代调用。参考 raphael 的 `FLASH-T21`（SMB5/充电）与 `redwood_sound.c` 的 `sound=` 步骤。
4. **FTS 0x5652 报告格式**：10 点、每点 6 字节已被真机证明可用（0 bad、坐标跟着手指走），
   但多点/边缘/滑动手势还要实测；如果出现坐标跳变，再核对 5 字节布局与 CRC。
5. **音量条镜像到右侧**（可选外观）：iPhone X 原生在左侧；若要贴合 K40 按键位置，hook HUD 视图的
   布局/`viewWillAppear:` 后改 frame，注意 SpringBoard 布局可能反复覆盖。
6. **背光开机即 1**：`r6` 轮看起来已经是亮的，需要再跑两轮确认不是偶然；若复现 `backlight-off`，
   查 `MiniIOMobileFramebuffer.cpp` 的亮度/显示状态上报。

---

## 11. 复制给新会话的开场白

```
继续 HackiOS 到 Redmi K40(alioth) 的移植工作。先读
<workdir>/README.md（上手说明）和
<workdir>/SESSION-HANDOFF.md（全部上下文）。

现状：
- iOS 16.5 主屏已在 K40 真机显示；触摸、电源键、音量键、电量显示都已通（§5.1–§5.5）。
  音量条能显示但没有真实音频（mediaserverd 未启动，§5.4），音频是下一个独立里程碑。
- GPU（Adreno 650）真机已验证到 **step 20 的入口**（§9.3.1）：时钟、SMMU、GMU 固件、HFI、
  3D 核上电、zap 认证全部打通（step 1–19 全过）。**唯一阻塞：写 `CP_SQE_CNTL=1` 启动命令处理器
  的那条 AHB 写下去后内核再无输出，约 1 s 内整机复位**；已排除微码地址、zap 顺序、SMMU 翻译/取指、
  寄存器偏移、SCTLR 模式、PTE 权限（§9.5）。
- **用户已决定先转向 Wi-Fi**（QCA6390，PCIe），GPU 的实验清单保留在 §9.5。

接手后第一件事：Wi-Fi。先读 §10 第 1 条与 §3 里 QCA6390 的硬件事实，把 PCIe 枚举做出来
（日志用 `SYS= TAG=w1 SECS=30 bash boot-one.sh`，`IMG=alioth-boot2.img` 才有 250 ms 的 note 节奏）。
如果回来修 GPU：按 §9.5 末尾“待查”的顺序，先加 `CP_SQE_CNTL=0` 的控制实验，再补厂商有、
本驱动没有的前置写（`CP_PROTECT`/`TPL1` 权重/`GMU_OOB_GPU_SET`/`SPTPRAC`）。
载荷必须用 Windows 的 Python 生成并 inspect_payload.py 校验（§7、§8，别再走 wsl -lc）。
注意：`boot-one.sh` 已加超时与单设备校验，不会再卡在 `< waiting for any device >`（§8）。
```

---

## 12. GPU 相关的产物与位置（2026-10-23）

| 产物 | 路径 | 备注 |
|---|---|---|
| 移植包（源码/工具/证据/报告） | `alioth-gpu-port/` | `files/` 是给上游的补丁内容；`evidence/device/` 是真机 dump；`feasibility-report.html` 是中文可行性报告 |
| 驱动（含 `a650` 行） | `alioth-gpu-port/files/xnu/files/bsd/dev/redwood_adreno.c`（193 KB） | 同一份在 `hackios-xnu-kernel-main/xnu/files/bsd/dev/` |
| 布局头 | `.../xnu/files/bsd/sys/redwood_gpu_layout.h` | 内核 `#include <sys/redwood_gpu_layout.h>` |
| 离线校验工具 | `alioth-gpu-port/files/tools/alioth.py`（`check`/`dt`/`gmu`/`sqe`/`zap` 子命令） | 在 `alioth-gpu-port` 目录下运行；K40 四件固件 + 运行中 DT 全是 `0 failures` |
| 主机自测 | `tools/gpu-test/run.sh` | gpu-test 47 checks、gpu-tables 77 checks，0 failures |
| 上游补丁 | `alioth-gpu-port/patch/hackios-kernel.patch`（48.5 KB，4 文件 +315/−164，**0 CRLF**） | 已在 `git archive HEAD` 树上用 `git apply -p1` 逐字节验证 |
| 内核 | `k40-build/kernel.bin`（15,129,416 B，2026-10-23 18:46 版） | 含 `adreno_direct` 与 step 20 逐条访问打印；源码在 `hackios-xnu-kernel-main/xnu/files/bsd/dev/redwood_adreno.c`（两棵 WSL 源码树各一份） |
| 启动镜像（带 250 ms note 节奏的 loader） | `k40-build/alioth-boot2.img`（2,007,040 B） | 原镜像备份 `alioth-boot.orig.img`；`boot-one.sh` 用 `IMG=alioth-boot2.img` 指定 |
| loader 源码（可编辑副本 + 备份） | `k40-build/loader.c`、`~/k40/xnuloader/loader.c.bak` | note 周期已由 2 s 改成 250 ms（`hc_ms_since()`） |
| K40 厂商内核参考 | `alioth-gpu-port/reference/vendor-msm/`（`adreno_a6xx.c`、`adreno_a6xx_gmu.c`、`kgsl_iommu.c/.h`、`a6xx_reg.h`、`adreno.h`） | 来自 `MiCode/Xiaomi_Kernel_OpenSource@alioth-r-oss`，权威顺序/偏移依据 |
| Linux 参考（本轮补齐） | `alioth-gpu-port/reference/linux-msm/`（`arm-smmu.c`、`arm-smmu-qcom.c`、`io-pgtable-arm.c`、`a6xx_gpu.c`、`a6xx_gmu.c`、`a6xx_hfi.c`、`a6xx_catalog.c`、`sm8250.dtsi`） | 直连 GitHub 不通，走 `cdn.jsdelivr.net/gh/torvalds/linux@v5.10|v5.4` |
| 启动卷 | `k40-build/root.apfs`（4 MB） | 内含 `fw/a650_gmu.bin`、`a650_sqe.fw`、`a650_zap.mdt`、`a650_zap.b02` |
| 载荷（GPU 验证） | `k40-build/run-payload.bin` | 当前是 `adreno_soc=a650 adreno=20 adreno_direct=1 adreno_return=1 adreno_watch=15 bootcpu=7 cpus=8 loader_return_after=300` |
| 载荷（回 iOS） | `k40-build/run-payload-ios.bin` | 与上面对调的备份；演示完把两个名字换回来 |
| 真机日志 | `g9b`/`g12b`/`g17a`（早期步骤）、`g22a`/`g22b`（step 18/19）、`g24a`（跳 zap 仍复位）、`g25a`（逐条打印，无输出）、`g25b`（旁路第一版失败）、`g25c`（旁路成立仍复位）、`g25d`（250 ms note，日志冻结实证） | 后 4 个是本轮 step 20 的排除证据，`.ld.bin` 是 64 MB logdump 原件 |
| 厂商计量参考 | `k40-build/debugcc-kona.c` 摘录、`clk-debug-excerpt.txt`、`kona-gpucc-sels.txt`、`kona-dbg.txt`、`kona-priv.txt` | K40 与 redwood 的 `counter_*` 差异依据 |
| 文档 | `alioth-gpu-port/docs/alioth.md`、`docs/PORTING.md` 末尾 | 真机读数表 + 待验证清单；补充材料 |
| 报告 | `alioth-gpu-port/feasibility-report.html`、`README.txt` | 结论「可行·高」，剩余 5 项风险 |

---

## 13. Wi-Fi（QCA6390，PCIe0）：DT 侦察完成 + 第 1 步真机通过（2026-10-23 晚）

### 13.1 硬件事实（全部来自手机自己的 DT 与运行中的 Android）

- 放射是 **QCA6390**：`lspci` 等价物（`/sys/bus/pci/devices`）显示
  `0000:01:00.0 vendor=0x17cb device=0x1101 class=0x028000`（网络控制器），
  挂在 **PCIe0**（`qcom,pcie@1c00000`）的根端口 `0000:00:00.0`（`0x17cb:0x010b`）后面。
- 蓝牙/外置 modem 在 **PCIe2**（`qcom,pcie@1c10000`）：`0002:01:00.0` `0x17cb:0x0306`（MHI，class 0xff0000）。
- **Android 开机约 19 s 就把 WLAN 的 PCIe 链路停掉了**（dmesg：`cnss: Suspending PCI link`、
  `Assert the reset of endpoint of RC0`、五个 `vdd-wlan-*` regulator 关断），所以运行时链路是断的，
  我们必须从零把 PCIe0 拉起来。
- DT（`qcom,pcie@1c00000`）给出的地址：
  `parf 0x1c00000+0x3000`、`phy 0x1c06000+0x1000`、`dm_core 0x60000000+0xf1d`、
  `elbi 0x60000f20+0xa8`、`iatu 0x60001000+0x1000`、`conf 0x60100000+0x100000`；
  ranges：IO `0x60200000+0x100000`、MEM `0x60300000+0x3d00000`（CPU 侧与总线侧同址）；
  `perst-gpio` = TLMM 79、`wake-gpio` = 81；`smmu-sid-base 0x1c00`；
  `qcom,phy-status-offset 0x814`（bit 6 = ready）、`qcom,phy-power-down-offset 0x840`；
  还有一整串 `qcom,phy-sequence`（寄存器/值对）。MAX 链路是 Gen2 ×1（`qcom,no-l0s-supported`、
  `qcom,use-19p2mhz-aux-clk`、`qcom,drv-l1ss-timeout-us=0x2710`）。
- 时钟控制器（`gcc-sm8250.c`，GCC 基址 0x100000）：`pcie_0_gdscr 0x6b004`；
  六路时钟投票都在 `gcc_pcie_0_axi_clk_misc 0x52008`（bit0 slv_axi、1 mstr_axi、2 cfg_ahb、
  3 aux、4 pipe、5 slv_q2a）；`pcie_phy_aux 0x6f004`、`pcie0_phy_refgen 0x6f02c`、
  `aggre_noc_pcie_tbu 0x9000c`；复位 `GCC_PCIE_0_BCR 0x6b000`、`GCC_PCIE_0_PHY_BCR 0x6c01c`。
- 控制器寄存器偏移取自厂商 `pcie-qcom.c`：`PARF_SYS_CTRL 0x00`、`PHY_CTRL 0x40`、
  `PHY_REFCLK 0x4c`、`DBI_BASE 0x168`、`SLV_ADDR_SPACE_SIZE 0x16c`、`Q2A_FLUSH 0x1ac`、
  `LTSSM 0x1b0`、`SID_OFFSET 0x234`、`BDF_TRANSLATE 0x24c`；`ELBI_SYS_CTRL 0x04`（bit0 = 链路使能）。

### 13.2 新驱动 `alioth_pcie.c`（分步，`pcie=N`）

`xnu/files/bsd/dev/alioth_pcie.c`，由 `redwood_input_init()` 在 `redwood_wifi_init()` 之后调用；
不带 `pcie=` 时直接返回（**对 iOS 启动零影响**）。分步计划：
1 只读现状 → 2 上电/给时钟 → 3 PHY 序列 + ready → 4 放 PERST + 等链路 → 5 读配置空间。

**第 1 步已真机通过**（`k40-build/p1a.log.txt` + `p1a.ld.bin`），读数如下（这就是 Android 关机后的起点）：

| 寄存器 | 值 | 含义 |
|---|---|---|
| `gcc pcie_0_gdscr` | `0x22f001` | **bit31=0：控制器断电**；bit0(SW_COLLAPSE)=1 |
| `gcc pcie_0_axi_misc` (0x52008) | `0x4100040` | **六路时钟投票全为 0**（bit0-5 = 0） |
| `pcie_0_slv/mstr_axi_halt` | `0x80000220` | 时钟已停 |
| `pcie_0_cfg_ahb/aux/pipe/q2a_halt` | `0x80000000` | 时钟已停 |
| `pcie_phy_aux` (0x6f004) | `0x80000000` | PHY 辅助时钟关 |
| `pcie0_phy_refgen` (0x6f02c) | `0x1` | **PHY refgen 仍开** |
| `aggre_noc_pcie_tbu` (0x9000c) | `0x4221` | bit0=1：TBU 时钟仍开 |
| `pcie_0_bcr` / `pcie_0_phy_bcr` | `0` / `0` | 两个块复位**都已释放** |

因为 GDSC 断电、时钟未投，第 1 步在读出这些之后**不去读 PHY/PARF**（断电时读会挂死）——这是有意为之。

### 13.3 分步结果（2026-10-23 20:00–20:30，第 1–4 步真机通过，第 5 步（PARF）挂死）

| 步 | 做了什么 | 结果 |
|---|---|---|
| 1 | 只读现状 | ✅ 见上表（GDSC 断电、时钟未投、复位已放、phy_refgen/TBU 仍开） |
| 2 | `pcie_0_gdscr` 清 `SW_COLLAPSE` 并等 `POWER_ON` | ✅ 写 `0x22f000` → 1 ms 后读 `0xf822f000`（bit31=1），**控制器上电** |
| 3 | `0x52008 |= 0x2f` 投五路时钟 | ✅ 读回 `0x410006f`；halt 寄存器 bit31 全部清 0（slv/mstr 从 `0x80000220` → `0x220`），**时钟在跑** |
| 4 | PHY：`gcc pcie_phy_aux` bit0 置 1，读/清 `PHY_POWER_DOWN`(0x840)，读 `PHY_STATUS`(0x814) | ✅ PHY 块可访问（power_down=0、status=0）；**但 bit6 "ready" = 0**（还没写 PHY 序列、PERST 未放） |
| 5 | 读 PARF（`0x1c00000`：SYS_CTRL/PHY_CTRL/PHY_REFCLK/DBI_BASE/SLV_SIZE/LTSSM）+ ELBI | ❌ **挂死**：内核日志长度冻结、无 pcie 输出（此后无 `launchd` panic），loader 不判 HUNG（因为别的核还在跑心跳） |

**第 5 步的结论**：控制器上电、六路时钟投票、PHY 时钟都开了之后，**PARF 仍然不可访问**。
按厂商 `pcie-qcom.c` 的顺序，PARF 的第一次写（`PHY_CTRL` bit0、`DBI_BASE=0`、`SYS_CTRL` bit29、
`MHI_CLOCK_RESET_CTRL` bit4、`AXI_MSTR_WR_ADDR_HALT_V2` bit31）发生在 PHY 上电**之前**，
所以 PARF 理论上应该已经能访问——它挂死说明还差一样东西。候选（按代价排序）：
1. **PHY 的 refclk/PHY 序列**：DT 的 `qcom,phy-sequence` 没写、`pcie0_phy_refgen` 虽为 1 但
   `pcie_0_ref_clk_src`（GCC 的 RCG）可能没跑；厂商 `qcom_pcie_phy_power_on()` 先做 PHY 序列再碰 PARF。
2. **`pcie_0_ldo`**（DT 的 clock 名，gcc-sm8250.c 里没直接看到，可能是 RPMh 或 PHY 侧）没开。
3. 上电后需要给 `GCC_PCIE_0_BCR` 一个复位脉冲（先 assert 再 deassert）再访问 PARF。
4. PARF 的 AHB 走 `cfg_ahb`，也许需要 `PARF_SYS_CTRL` 之外的 "PARF_AHB" 时钟（`0x52008` 之外的投票位）。

**下一步就做第 1 条**：把 DT 的 `qcom,phy-sequence`（约 140 对寄存器/值）编进驱动写成第 5 步
（PHY 序列 + 等 `PHY_STATUS` bit6），之后重试 PARF 读。若 PHY ready 后 PARF 仍挂，再试 2/3。

**已做（20:15–20:35）**：`inject-phy.py` 把 DT 的 `qcom,phy-sequence`（**99 对**）注入驱动（第 5 步）。
- 只写序列：设备存活，PHY 仍 **not ready（status 0）**，日志完整（`p5b.ld.bin`）。
- 在序列前加 **PHY 复位脉冲**（`GCC_PCIE_0_PHY_BCR 0x6c01c`、`GCC_PCIE_PHY_BCR 0x6f000`、
  `GCC_PCIE_PHY_COM_BCR 0x6f010` 各 assert→2 ms→deassert→20 ms）后重跑：日志**停在
  `pcie_phy_bcr (release)` 这一条写之后**（`p5c.ld.bin`），即复位释放后的下一步（`COM_BCR` 释放或
  第一次序列写）就把核挂住 → 说明 **PHY 复位/COM 域释放得过早或顺序不对**，下次要把 COM 复位
  放到 PHY 序列之后、或先确认 `pcie_phy_aux` 在复位释放时仍然在跑（复位会把它停掉）。
- 结论：PHY 侧还差“正确的复位/COM 顺序”，PARF 是否可访问仍未知（要等 PHY 起来后再试第 6 步）。

**再修正（20:45–21:00，第 5 步现在不再挂死）**：
- 顺序改为：`pcie_0_phy_bcr`/`pcie_phy_bcr` assert→2 ms→release→20 ms → 重投 `pcie_phy_aux`
  和 `pcie0_phy_refgen` → **等 100 ms**（之前 20 ms 就访问 PHY 会挂死）→ 释放 `pcie_phy_com_bcr`
  (0x6f010) → 写 99 对序列 → 每 10 ms 读一次 `PHY_STATUS`，共 190 ms。
- 结果（`p5e.ld.bin`、`p5f.ld.bin`）：**全程不挂死**，但 `PHY_STATUS` 一直是 **0**，bit6 never set。
- 读数为 0 而不是部分位，说明 PHY 块本身没在跑：怀疑 **refgen 的源 RCG**（`gcc_pcie_phy_refgen_clk_src`，
  或 DT 里的 `pcie_0_ref_clk_src`）没使能，或 PHY 的 "com" 时钟（`gcc_pcie_phy_aux` 只是分支）
  没真正供上。下一步先查这两个源时钟的寄存器（gcc-sm8250.c 的 rcg 表）再访问 PHY。

**找到根因（21:00–21:20）：aux 时钟的源 RCG 是空的**
- 第 6 步把 PCIe0 的整片时钟寄存器读出来，关键几行：`pcie_0_gdscr 0xf822f000`（已上电）、
  `slv/mstr halt 0x220`、`q2a/cfg_ahb/aux halt 0`、`pipe_halt 0x80000000`（PHY 未起，正常）、
  **`aux_clk_src rcgr/cfg/m/n/d 全 0`**、`phy_refgen_src cfg 0x100000` + 分支 1、`axi_misc 0x410006f`。
  → **`gcc_pcie_0_aux_clk_src`（0x6b038）从未被配置/使能**：分支显示“未 halt”，但源头没有时钟，
    这正是 PARF 访问挂死的原因（PARF 的 AHB 走 aux/cfg_ahb）。
- 第 7 步按 gcc 的 RCG 语义配置并打开根：写 `cfg=0`（源 0=晶振、分频 1）、`m/n/d=0`、
  **`rcgr=0x2`（ROOT_EN）** → 读回 `rcgr = 0xf2`，`aux/cfg_ahb halt = 0`，**源时钟已经在跑**。
- 第 8 步（PARF 读）刚跑过一次，但 `logdump` 里没找到本次的 `pcie:` 段（可能被 Android 后续写覆盖），
  需要重跑确认。若 PARF 可读，接着配 iATU/ELBI 放链路。

**线程化（pcie_thread=1）与它的坑（21:30–22:00）**
- `pcie_thread=1` 把各步放到内核线程里跑（`kernel_thread_start`），本意是“卡死的访问只毁掉线程”。
  真机确认线程会启动并执行（`p8d.ld.bin`：`pcie: pcie_thread=1: ... started (0)`，step 1 全部读完、step 2 开始）。
- **坑**：`SYS=` 空（无系统镜像）时，内核在驱动初始化后约 **300 ms** 就在 `launchd` exec 处 panic，
  线程只来得及做两步（日志在 `p8d.ld.bin` 里，最后一行是 step 2 的写），panic 又把整机带走。
- 于是加了 `pcie_wait=MS`（默认 3000）在启动路径上等线程；但 `pcie_wait=4000` 那次（`p8e.ld.bin`）
  **dump 里只有 loader 头部、没有 `== KERNEL LOG ==`**：说明内核既没走到 panic、也没被 loader 判 HUNG
  → 线程与启动路径之间发生了阻塞（最可能是线程挂在某个持锁的路径上，连 panic 打印都进不去）。
- **结论与下一步**：不要再靠 panic 收日志。**把 loader 的 `NOTE_SECONDS` 从 24 改大（例如 300）**
  再重编 `alioth-boot2.img`（流程见 9.5 的“这一轮新增的工具”），让 loader 在**内核运行期间**
  持续把内核日志尾部写进 logdump；配合 `pcie_thread=1`，卡死也能拿到卡死前的打印。

**实测 NOTE_SECONDS=300 不可行（22:00–22:20）**：改成 300 重编（`alioth-boot3.img`）后，
内核日志在 **349 字节**处冻住（只有最早几行+adreno SoC 行），比 24 s 版更早失效——原因正是 loader
源码里那句注释：NOTE_SECONDS 之后它才把中断控制器交给系统；**拖到 300 s 等于让 UEFI 的中断处理
一直和 XNU 抢 GIC**。已改回 24 并重编 `alioth-boot4.img`。
- 另加了 `pcie_delay=MS`（在第 1 步之前等，让各步落在 loader 的 0–24 s note 窗口里）。
- 但 `pcie_thread=1 pcie_delay=2500` + 进 iOS 的那次（`p9b`）内核日志**仍冻在 349 字节**：
  说明**真正的拦路虎是“写核缓存没落盘”**，不是窗口长度。

**下一步（明确的修法）**：在 `osfmk/arm64/loader_return.c` 里加一个
`void loader_log_flush(void)`（对 `loader_log`/`loader_log_len` 用 `dc civac` 逐行清到内存），
在 `alioth_pcie.c` 每条 step 打印后调用它。这样 loader 的 note 读到的永远是真实尾部，
线程/挂死都能留证。之后重跑 `pcie=8`。

> 调试经验（重要）：内核卡死时，`printf` 的最近若干行**可能还在写核的缓存里没落盘**，
> 所以 loader 的 note 会显示一个更早的日志长度（如 349 B）。判断“卡在哪”要靠
> **每步只做一件事 + 让内核正常跑完（panic 也算正常结束）**，日志才会被完整写出；
> 只跑 20 s 是不够的（loader 要 50 s 静默才判 HUNG，而别的核的心跳会阻止它判 HUNG）。

### 13.4 下一步（第 5 步）

按厂商 `gdsc.c` + `pcie-qcom.c` 的顺序：①GDSC 清 `SW_COLLAPSE` 并等 `POWER_ON`(bit31)；
②`0x52008 |= 0x3f` 投六路时钟并确认 halt 状态；③（复位已释放，无需动）；
④再做 PHY 序列（DT 的 `qcom,phy-sequence`）与 `PHY_STATUS` bit6；⑤`ELBI_SYS_CTRL |= 1` 放链路，
轮询 `PARF_LTSSM`；⑥配 iATU 后读 `conf` 空间的 `00:00.0`/`01:00.0` 的 vendor/device。
产物：`k40-build/run-payload-pcie1.bin`…`-pcie5.bin`、`run-payload.bin` 仍是 iOS。
另注：`SYS=` 空（无系统镜像）时内核会在 `launchd` exec 处 panic（`errno 2`），这是正常的“没系统可起”，
不影响驱动日志（日志在 `p1a.ld.bin` 里，21600 字节处）。
