# alioth (Redmi K40 / POCO F3) 的 kona 地址对照表

> 生成：2026-10-22
> 目的：把 redwood（SD778G / sc7280）代码里的每一个"这台手机的地址"列出来，给出 kona（SM8250-AC / SD870）
> 上对应的值，标明来源和可信度。改的时候只照这张表替换常量，不动逻辑。
>
> 数据来源：
> - `D` = `.analysis/alioth.dts`（Mu-Silicium `Resources/DTBs/alioth.dts`，1.5 MB，行号已标）
> - `L` = Linux 上游驱动（`gcc-sm8250.c` / `pinctrl-sm8250.c`），已逐条核对
> - `R` = 仓库现有 `redwood_*.c` 的取值（对照用）
> - `?` = 尚未确定，必须真机或另取源码

---

## 0. 一句话结论

K40 相对 redwood 的差异**集中在触摸和供电/引脚**：TLMM 基址不同、SPI 换到另一个串行引擎、引脚全换、
触摸的两路 LDO 取代了"一路 LDO + 一个 GPIO 开关"。**UFS / SMEM / cmd-db / RPMh RSC / SPMI 仲裁器 /
EPSS 调频这六块的地址完全相同**，一行都不用改。GPIO 的 qup 复用号在 kona 上恰好仍是 1，也不用改。

---

## 1. Loader / platform（`xnuloader/loader.c`、`common/devices/alioth.platform.c`）

| 字段 | redwood | alioth (kona) | 来源 | 状态 |
|---|---|---|---|---|
| `io_base` / `io_size` | `0x00400000` / `0x3FC00000` | 同 | R | ✅ 草稿已填 |
| `gic_dist` | `0x17A00000` | `0x17A00000`（窗口 `0x10000`） | D:2775 | ✅ 已填 |
| `gic_redist` | `0x17A60000` | `0x17A60000`（`0x100000`，stride `0x20000`） | D:2774-2775 | ✅ 已填 |
| `cores` | 8 | 8（`cpu@0`…`cpu@700`） | D | ✅ 已填 |
| `core_shift` | 8 | 8（MPIDR 第二亲和域 0…7） | D | ✅ 已填 |
| `small_cores` | `0x0f` | `0x0f`（0-3 A55 `capacity 0x400`，4-7 A77 `0x766`） | D | ✅ 已填 |
| `uart` | 0（走 USB） | 0 | — | ✅ |
| `log_other_cpu` | 1 | 1 | — | ✅ |
| `timeout_scale` | 0 | 0 | — | ✅ |
| `fb_base` | `0xE1000000` | **`0x9C000000`** | D: `cont_splash_region@9c000000` + ABL "Display Reserved"（11.2 节） | ✅ 双重印证 |

`fb_base` 的取法：第一次 `./xl run` 之后，loader 的日志里有一行
`display 1080 x 2400 at 0x........` —— 那个地址就是。它同时是 loader 认设备的依据
（`platforms[]` 里按 `fb_base` 匹配），所以必须填对。

---

## 2. 触摸（`xnu/files/bsd/dev/redwood_goodix.c`）—— 改动最多的一块

K40 只有 FocalTech（`spi@990000/focaltech@0`，`compatible="focaltech,fts"`），没有 Goodix 变体。

> 下面表里括号中的行号是**改造之前**那一版 `redwood_goodix.c` 的行号（改造后每个常量块外面多了
> `#if defined(PLATFORM_ALIOTH)`，行号会漂）。按常量名 grep 更可靠。

### 2.1 基址

| 常量（行） | redwood | alioth (kona) | 来源 |
|---|---|---|---|
| `TLMM_PHYS`（73） | `0x0F100000` | **`0x0F000000`** | D:12100 `pinctrl@f000000 reg = <0xf000000 0x1000000>` |
| `TLMM_SIZE`（74） | `0x100000` | **`0x1000000`** | D:12100 |
| `SE_PHYS`（354） | `0x00A94000`（SE13） | **`0x00990000`**（SE4） | D:33222 `spi@990000`，别名 `qupv3_se4_spi` |
| `SE_SIZE`（355） | `0x4000` | 同 | D:33222 |
| `CMD_DB_PHYS`（118） | `0x80860000` / `0x20000` | 同 | D:39518 |
| `RSC_PHYS`（120） | `0x18220000`（DRV 2）/ `0xD00` TCS | 同 | D:5964 `reg-names="drv-2"`、`qcom,tcs-offset=0xd00` |
| `GCC_PHYS`（265） | `0x00100000` | 同 | D:3731 `qcom,gcc@100000` |
| `GCC_SIZE`（266） | `0x60000` | 保持（用到最高 `0x1756c`，够） | 计算 |

### 2.2 引脚

| 常量（行） | redwood | alioth (kona) | 来源 |
|---|---|---|---|
| `PIN_MISO`（80） | 52 | **8** | D:16628 `qupv3_se4_spi_active pins="gpio8","gpio9","gpio10"` |
| `PIN_MOSI`（81） | 53 | **9** | 同上 |
| `PIN_CLK`（82） | 54 | **10** | 同上 |
| `PIN_CS`（83） | 55 | **11** | D:18142 `ts_cs_active pins="gpio11" function="qup4"` |
| `PIN_INT`（84） | 81 | **39** | D:33251 `focaltech,irq-gpio = <&tlmm 0x27 0x2008>` |
| `PIN_RESET`（85） | 105 | **33** | D:33250 `focaltech,reset-gpio = <&tlmm 0x21 0>` |
| `PIN_AVDD`（86） | 107 | **删除**（供电全走 RPMh，见 2.4） | D:33248-33249 只有两路 supply，无 GPIO 开关 |
| `PIN_FOCALTECH_ID`（87） | 68 | **删除**（无 Goodix 变体，恒走 FT 路径） | D |
| `PIN_GOODIX_ID`（88） | 96 | **删除** | D |
| `PIN_FUNCTION_SPI`（89） | 1 | **1**（kona 的 qup4 在该引脚的 mux 表里正好是 1） | L: `PINGROUP(8, NORTH, qup4, …)` → gpio=0, qup4=1 |

> 引脚角色：`gpio8/9/10` 是 SE4 的 data/clock 三根，`gpio11` 是独立 mux 的 CS。
> 同一 SE 的 I2C 组是 `gpio8(SDA)/gpio9(SCL)`（D:16356），所以 **gpio8 = data0、gpio9 = data1**。
> GENI 模式下谁驱动谁由硬件决定，只有走"手工四条线"兜底时才需要 MISO/MOSI 对调试验。

### 2.3 GCC 时钟（QUPV3_WRAP0 第 5 个 SE，即 SE4）

kona 的 GCC 与 sc7280 是两个不同的时钟控制器，**偏移完全不同**，必须整组替换：

| 常量（行） | redwood | alioth (kona) | 来源 |
|---|---|---|---|
| `GCC_VOTE`（267） | `gcc + 0x52008` | `gcc + 0x52008`（同） | L: 所有 qup 分支的 `enable_reg` |
| `VOTE_..._CORE_2X`（268） | `1<<18` | **`1<<9`** | L: `gcc_qupv3_wrap0_core_2x_clk` |
| `VOTE_..._CORE`（269） | `1<<19` | **`1<<8`** | L: `gcc_qupv3_wrap0_core_clk` |
| `VOTE_..._M_AHB`（270） | `1<<20` | **`1<<6`** | L: `gcc_qupv3_wrap0_m_ahb_clk` |
| `VOTE_..._S_AHB`（271） | `1<<21` | **`1<<7`** | L: `gcc_qupv3_wrap0_s_ahb_clk` |
| `VOTE_..._SE5`（272） | `1<<27` | **`1<<14`** | L: `gcc_qupv3_wrap0_s4_clk` |
| `GCC_QUP1_M_AHB_CBCR`（273） | `gcc+0x18004` | **`gcc+0x17004`** | L: halt_reg |
| `GCC_QUP1_S_AHB_CBCR`（274） | `gcc+0x18008` | **`gcc+0x17008`** | L: halt_reg |
| `GCC_QUP1_SE5_CBCR`（275） | `gcc+0x185FC` | **`gcc+0x174CC`** | L: halt_reg（= cmd_rcgr − 4） |
| `GCC_QUP1_SE5_CMD`（276） | `gcc+0x18600` | **`gcc+0x174D0`** | L: `cmd_rcgr` |
| `GCC_QUP1_SE5_CFG`（277） | `gcc+0x18604` | **`gcc+0x174D4`** | cmd_rcgr + 4 |
| `GCC_QUP1_SE5_DFSR`（278） | `gcc+0x18614` | **`gcc+0x174E4`** | cmd_rcgr + 0x14 |
| `..._PERF_CFG(l)`（279） | `+0x1861C` | **`gcc+0x174EC + 4l`** | cmd_rcgr + 0x1C |
| `..._PERF_M(l)`（280） | `+0x1865C` | **`gcc+0x1752C + 4l`** | cmd_rcgr + 0x5C |
| `..._PERF_N(l)`（281） | `+0x1869C` | **`gcc+0x1756C + 4l`** | cmd_rcgr + 0x9C |
| `rcg_rate()` 父表（290） | `{XO, 600M, …, 300M}` | **`{XO, 300M, …, 150M}`** | L: `gcc_parent_map_0` = 0:bi_tcxo, 1:GPLL0_OUT_MAIN(300M), 6:GPLL0_OUT_EVEN(150M) |
| `XO_HZ`（283） | 19200000 | 同 | D |

注意 `rcg_rate()` 的父表：sc7280 的 GPLL0 是 600 MHz，kona 是 300 MHz。**这一条不改，算出来的
`se_source_hz` 会大一倍，分频器跟着错一倍**，SPI 会读回全 0xFF。

### 2.4 供电（`io_supply_on()`，241–260 行）

| 项 | redwood | alioth (kona) | 来源 |
|---|---|---|---|
| I/O 电源 | `ldoc2`（PM8350C）1.8 V | **`ldoc10` 3.0 V** + **`ldoc1` 1.8 V**，两路都要 | D:33248 `vdd-supply=<&pm8150a_l10>`；33249 `vcc_i2c-supply=<&pm8150a_l1>` |
| 模拟电源开关 | `PIN_AVDD`（GPIO107） | **无**，也走 RPMh | D |

`rpmh_write()` 一次最多 3 条命令，正好一路 regulator（电压/使能/模式），所以改成连着调两次：
`rpmh_address("ldoc10")` 写 3000 mV，再 `rpmh_address("ldoc1")` 写 1800 mV。
`(base >> 16 & 0xf) != 4` 这条 regulator 判据对两路都成立，不用改。

### 2.5 报告坐标

| 常量（行） | redwood | alioth (kona) | 来源 |
|---|---|---|---|
| `max_x/max_y`（607） | 10800 / 24000 | **8640 / 19200** | D:33253 `display-coords = <0 0 0x21c0 0x4b00>` |
| `focaltech_max_x/y`（1246） | 10800 / 24000 | **8640 / 19200** | 同上 |

两者都是 1080×2400 面板，只是芯片给出的"超高分"单位不同（redwood ×10，K40 ×8）。
驱动按 `max_report_x` 归一化，所以填 dts 里的原始值即可，不用自己换算。

---

## 3. 按键（`redwood_buttons.c`）

| 常量（行） | redwood | alioth (kona) | 来源 |
|---|---|---|---|
| `ARB_CORE_PHYS`（96） | `0x0C440000` | 同 | D:4174 `reg = <0xc440000 0x1100 …>` |
| `ARB_CNFG_PHYS`（98） | `0x0C40A000` | 同 | D:4174 `cnfg` |
| `ARB_OBSERVER_PHYS`（100） | `0x0E600000` | 同 | D:4174 `obsrvr` |
| `ARB_SYSTEM`（102） | 0 | 0 | D:4178 `qcom,ee = <0x00>` |
| PON 外设 id（152） | `0x013`（PMK8350 @0x1300，SID 0） | **`0x008`**（PM8150 `power-on@800`，SID 0） | D:4192-4193、reg `<0x800 0x100>` |
| 音量+ 引脚 id（153） | `0x18D`（PM7325 GPIO6） | **`0x0C5`**（PM8150 GPIO6） | D:4266 `pinctrl@c000 reg=<0xc000 0xa00>`；每个 GPIO 占 0x100 → GPIO6 = 0xc500，MODE 在 +0x40 |
| `PON_KPDPWR` / `PON_RESIN`（251/252） | `0x80` / `0x40` | 保持（同一 PON IP，真机日志复核） | ? |
| `POLL_MS` | 16 | 同 | — |

K40 的按键拓扑与 redwood 一模一样：电源 = KPDPWR_N、音量− = RESIN_N、音量+ = PMIC GPIO6 上拉输入
（D:4319-4329 `key_vol_up`，D:39122-39130 `vol_up` active-low）。所以这个驱动的结构不用动。

> `0x0C5` 的推法：驱动约定"外设 id = 寄存器地址的高字节"，GPIO6 的寄存器块在 `0xc500`，
> 于是 id = `0xc5`，读的时候 `id<<8 | 0x40` = `0xc540`（GPIO6_MODE）。
> PM8150 的 PON 在 `0x800` → id `0x08`，`0x810` 就是 RT_STS。

---

## 4. 马达（`redwood_haptic.c`，aw8697，I2C 手工时序）

| 常量（行） | redwood | alioth (kona) | 来源 |
|---|---|---|---|
| `TLMM_PHYS`（127） | `0x0F100000` | **`0x0F000000`** | D:12100 |
| `PIN_SDA`（134） | 36 | **60** | D:16866 `qupv3_se11_i2c_active pins="gpio60","gpio61"` |
| `PIN_SCL`（135） | 37 | **61** | 同上 |
| `PIN_RESET`（136） | 35 | **130** | D:33440 `reset-gpio = <&tlmm 0x82 0>` |
| `PIN_INT`（137） | 18 | **129** | D:33441 `irq-gpio = <&tlmm 0x81 0>` |
| `AW_ADDRESS`（279） | `0x5A` | `0x5A`（同） | D:33439 `reg = <0x5a>` |

芯片挂在 `i2c@a8c000`（SE11），驱动是 GPIO 位翻转模拟 I2C，所以只要引脚对，
不需要 GENI/时钟。**固件同名 `aw8697_haptic.bin`**，可以从 K40 的 `/vendor/firmware` 直接拿。

---

## 5. CPU 调频（`redwood_cpufreq.c`）—— 一行都不用改

| 项 | redwood | alioth (kona) | 来源 |
|---|---|---|---|
| EPSS 基址 | `0x18591000` | `0x18591000` | D:352 |
| 域 | 3 × `0x1000`（`18591000/2000/3000`） | 同，三域 | D:352-353 |
| `lut-row-size` | 4 | 4 | D:356 |
| `skip-enable-check` | 有 | 有 | D:357 |
| `EPSS_FREQ_TABLE` / `EPSS_PERF_STATE` | `0x100` / `0x320` | 同（kona 的 epss 布局与 sc7280 一致） | L: `qcom-cpufreq-hw.c` epss 变体 |
| `domain_of()` 映射 | `core<4 → 0`, `<7 → 1`, `else 2` | 同（silver 0-3 / gold 4-6 / prime 7） | D |

唯一要现场核对的：日志里三域各自读到的频率表条数与最高档（`raise_domain` 会打印）。
K40 的 A77 最高 3.2 GHz，silver 1.8 GHz。

---

## 6. 六块完全相同的地址（照抄，不要改）

| 模块 | 地址 | 来源 |
|---|---|---|
| UFS 控制器 | `0x1D84000` | D:40040 `ufshc@1d84000` |
| SMEM | `0x80900000` + `0x200000` | D:39528-39531 |
| cmd-db | `0x80860000` + `0x20000` | D:39518 |
| RPMh RSC（DRV 2） | `0x18220000`，TCS offset `0xD00` | D:5964 |
| SPMI 仲裁器 | 见第 3 节 | D:4174 |
| EPSS | 见第 5 节 | D:352 |

---

## 7. 第二阶段才碰的两块（这里的数只是"起点"）

### 7.1 ADSP / 音频

| 项 | redwood | alioth (kona) | 来源 |
|---|---|---|---|
| LPASS 基址 | `0x3700000` | **`0x17300000`** | D:7329 `qcom,lpass@17300000` |
| ADSP 固件内存 | `0x86700000` + `0x4000000` | **`0x8BB00000` + `0x2500000`** | D:39614 `pil_adsp_region` |
| SMEM / SMP2P / GLINK / QRTR | `0x80900000` | 同 | — |
| codec | （redwood 是 WCD938x 系） | `bolero` + `wcd938x`（WCD9385）+ `cs35l41@40`（I2C，智能功放） | D:112 |

CS35L41 是**每声道一颗**的智能功放 + DSP，K40 的音频链路比 redwood 多一层，`redwood_speaker.c` /
`redwood_audio.c` 里的路由要重画，不只是改地址。

### 7.2 GPU / Wi-Fi（大工程，本轮不做）

- GPU：Adreno **650**（`a650_gmu.bin` / `a650_sqe.fw` / `a650_zap.*`），redwood 是 642L。
  `redwood_adreno.c` 183 KB，寄存器代际、微码、GMU 固件全不同 → 新增 kona 版本，不是改常量。
- Wi-Fi：**QCA6391（PCIe + MHI）**，`qcom,cnss-qca6390@b0000000`，`wlan-en-gpio = GPIO20`，
  而 redwood 是 WCN6750（AHB）。`redwood_wifi.c` 的窗口寄存器逻辑出自 `ath11k/ahb.c`，
  PCIe 路径是 `ath11k/pci.c` + `mhi`，**不能照搬**。所以 `alioth.conf` 里 `WIFI_ATH11K=0` 是对的。

---

## 8. 未定值清单（4 条里的 2 条已定）

| # | 值 | 状态 |
|---|---|---|
| 1 | `fb_base` | ✅ **已定 `0x9C000000`**：dts 的 `cont_splash_region@9c000000`（`0x9c000000 + 0x2300000`）与 ABL 的 "Display Reserved" 两处印证；首次启动仍以 loader 打印的地址复核 |
| 2 | GPLL0 = 300 MHz 假设 | ⏳ 未定。真机读 `gcc+0x174d4` 的 `[10:8]`，或看 SPI 回读是否正常。错一倍就完全读不到芯片 |
| 3 | PM8150 PON 的 RT_STS 位（0x80 / 0x40） | ⏳ 未定，`buttons_steps=4` 那次日志里看 "power HELD/released" 是否随手指变化（驱动有"一直按住就不采信"的保护，不会误报） |
| 4 | K40 的 FocalTech 报告格式 | 🟡 **型号已定（`0x5652`）**，但报告字节布局未核：redwood 的代码按 FT3680 每点 6 字节写的；X/Y 上限 8639/19199 已由 `getevent` 证实，说明量化是对的 |

---

## 9. 逐文件改造清单（按可执行顺序）

```
xnuloader/loader.c
  └ 把 alioth.platform.c 粘进去，platforms[] 加 &platform_alioth     [已备好，缺 fb_base]

common/devices/alioth.conf
  └ FB_BASE 待填；其余见草稿                                        [已备好]

xnu/files/bsd/dev/redwood_goodix.c      ← 主战场
  ├ TLMM_PHYS/SIZE
  ├ SE_PHYS
  ├ PIN_MISO/MOSI/CLK/CS/INT/RESET（+ 删 AVDD、两个变体判别引脚）
  ├ GCC 一整组（VOTE_* 位号、四个 CBCR、RCG 五个寄存器、PERF 三组）
  ├ rcg_rate() 父表（600M→300M / 300M→150M）
  ├ io_supply_on()：ldoc2 → ldoc10(3.0V) + ldoc1(1.8V)
  └ max_x/max_y、focaltech_max_x/y

xnu/files/bsd/dev/redwood_buttons.c
  ├ PON id 0x013 → 0x008
  └ pin id 0x18D → 0x0C5

xnu/files/bsd/dev/redwood_haptic.c
  ├ TLMM_PHYS
  └ PIN_SDA/SCL/RESET/INT → 60/61/130/129

xnu/files/bsd/dev/redwood_cpufreq.c     不动
xnu/files/bsd/dev/redwood_ufshc.c       不动
xnu/files/bsd/dev/redwood_adsp.c        动（第二阶段：0x3700000→0x17300000，RAM 区换 0x8BB00000+0x2500000）
xnu/files/bsd/dev/redwood_adreno.c      重写（Adreno 650）
xnu/files/bsd/dev/redwood_wifi.c        重写（PCIe/MHI）
```

方案已经定了：**`#ifdef` 方案，已实现**（2026-10-22）。接线方式：

1. `xnu-deps/host/bin/xnu-clang`（所有内核编译都走这个包装器）在多出来的位置加一句：
   有 `XNU_DEVICE` 就给每个编译单元加 `-DPLATFORM_<大写的设备名>=1`。
2. `xnu-build.sh` 把 `common/build.sh <device>` 传来的 `DEVICE` 导出成 `XNU_DEVICE`，并在开头打印一行
   `xnu-build: device alioth -> -DPLATFORM_ALIOTH`，这样日志里能确认。
3. 三个驱动文件里，**只把"地址常量块"包进 `#if defined(PLATFORM_ALIOTH) … #else … #endif`**，
   逻辑一行没动：
   - `redwood_goodix.c`：TLMM/SE_PHYS/6 个引脚（另有 3 个引脚在 alioth 上不存在，定义成 `(-1)` 并加 `#if … >= 0` 守着）、
     GCC 一整组（连 RCG 父频率）、两处坐标上限、`io_supply_on()`（改成 `vrm_on(name, mV)`，alioth 连着开两路）
   - `redwood_buttons.c`：PON 外设 id、GPIO 外设 id（顺带把两行硬编码 0x1310/0x8d40 的日志改成按 id 算）
   - `redwood_haptic.c`：TLMM 基址、4 个引脚
4. `xnuloader/loader.c`：`platform_alioth` 直接写进去（loader 是一镜像认全机型，靠 `fb_base` 选），
   `platforms[]` 里加了 `&platform_alioth`。`common/devices/alioth.platform.c` 降级为"对照记录"，两边要一起改。

为什么不走平行文件：`xnu/redwood.patch` 是整目录加进 XNU 树的，`alioth_touch.c` 会和 `redwood_goodix.c`
撞同一批符号（`redwood_goodix_init` / `spi_transfer` / 静态同名变量），还得同步改 patch 的文件清单，
一处漏了就链接失败。`#ifdef` 只影响编译期常量，回退也只是不加那个 `-D`。

建议先走方案 1，把第一批里程碑跑通，再决定要不要拆。

---

## 10. 验证顺序（每步只看一件事）

1. `./xl enter` → loader 起来 → 抄下 `display 1080 x 2400 at 0x…` → 回填 `fb_base`
2. 同一次会话 `./xl log`，确认 `platform_alioth` 被选中（日志里有设备名）
3. `XL_CMDLINE="touchscreen=1"` → 看 `goodix: the bus at …` / `focaltech: chip id …`
4. 加 `touch_lat=1`，手指按屏幕 → 看 `tl: c …` 与 `focaltech: finger 0 down at x, y`
5. `buttons=1 buttons_steps=4` → 看三键的原始状态 → 核对第 8 节第 3 条
6. `cpufreq=1` → 看三域最高档
7. `haptic=1` → 看 `haptic: chip id 0x9270`（aw8697，与 redwood 同）

---

## 11. 真机实测（2026-10-22，K40 / alioth / 序列号已隐去）

设备：`M2012K11AC`，Android 17，`OS4.0.0.30.XPCCNXM`，KernelSU root，BL 已解锁
（`verifiedbootstate=orange`、`fastboot getvar unlocked:yes`、`current-slot:a`）。

### 11.1 固件 / bootloader 版本（从 `xbl_a.img` 里读出来的）

`fastboot getvar version-bootloader` 是**空的**（小米把这项隐藏了），只能从镜像里取：

```
SBL1 BUILD @ 13:50:53 on May 27 2024
UEFI LABEL: UEFI.4.1.$Change: 16743401 $ LABEL DATE: $Date: 2018/07/26 $ FW_VER: 4.1.
BUILD_DATE: May 27 2024  BUILD_TIME: 13:51:32
```

→ **XBL/SBL1 与 ABL 的编译日期 = 2024-05-27，UEFI 标号 4.1，Change 16743401**。
Mu-Silicium 的 `alioth` 驱动如果来自别的固件版本，版本差太远就可能起不来；这是对照的依据。

### 11.2 ABL 内存图（最有价值的一张表）

从 `xbl_a.img` 里抽出的 `AddMem` 表（ABL 自己登记的内存区域，原样照抄）：

| 地址 | 大小 | 名字 | 属性 |
|---|---|---|---|
| `0x805D0000` | `0x20000` | IPC SHM | BsData |
| `0x80600000` | `0x100000` | MPSS EFS | Reserv |
| `0x80700000` | `0x100000` | BOOT INFO | BsData |
| `0x80860000` | `0x20000` | **AOP CMD DB** | Reserv, uncacheable |
| `0x80884000` | `0x10000` | XBL Log Buffer | Reserv |
| `0x80900000` | `0x200000` | **SMEM** | Reserv, uncacheable |
| `0x82400000` | `0x9600000` | TZApps Reserved | Reserv |
| `0x8BC00000` | `0x12E00000` | PIL Reserved | Reserv |
| `0x98900000` | `0x3300000` | DXE Heap | Conv |
| `0x9BC00000` | `0x400000` | Sched Heap | BsData |
| `0x9C000000` | `0x2400000` | **Display Reserved** | Reserv, write-through |
| `0x9F800000` | `0x200000` | FV Region | BsData |
| `0x9FA00000` | `0x200000` | ABOOT FV | Reserv |
| `0x9FC00000` | `0x300000` | **UEFI FD** | BsData |
| `0x9FF00000` | `0x8C000` | SEC Heap | BsData |
| `0x9FF8C000` | `0x1000` | CPU Vectors | BsData |
| `0x9FF8D000` | `0x3000` | MMU PageTables | BsData |
| `0x9FF90000` | `0x40000` | UEFI Stack | BsData |
| `0x9FFF7000` | `0x8000` | Log Buffer | RtData |
| `0x9FFFF000` | `0x1000` | Info Blk | RtData |
| `0xA0000000` | `0x10000000` | **Kernel** | Reserv |

三条直接结论：

1. **`FD_BASE=0x9FC00000` / `FD_SIZE=0x300000` 被逐字证实** —— 表里就叫 "UEFI FD"，大小一模一样。
   (`alioth.conf` 现在的值不用改。)
2. **`fb_base` 候选 `0x9C000000`** —— "Display Reserved" 从 `0x9C000000` 起、到 `0x9E400000` 止，
   GOP 的 framebuffer 就在这块里（redwood 的 `0xE1000000` 同样是它那块 Display Reserved 的起点）。
   真机跑起来后仍以 loader 打印的 `display 1080 x 2400 at 0x…` 为准。
3. **`PAYLOAD_BASE=0xF0000000` 安全** —— 不在上表任何保留区里；`/proc/iomem` 显示
   `c0000000-ffbfffff : System RAM`，且避开了 ABL 给内核留的 `0xA0000000 + 0x10000000`。
   顺带：`max-download-size = 0x30000000`（768 MB），整个 boot.img 必须小于这个数。

另外 `/proc/iomem` 里 `0xffc00000-0xffc1ffff` 是空洞（`ffc20000` 之后才又是 System RAM），
说明这块 128 KB 被谁留了 —— 离 `0xF0000000` 很远，不影响。

### 11.3 触摸（实测，替代第 8 节第 4 条的不确定）

| 项 | 实测值 | 来源 |
|---|---|---|
| 驱动 | `focaltech_touch`（日志前缀 `[FTS_TS]`），输入设备名 `fts_ts` | `dmesg`、`getevent -pl` |
| **芯片 ID** | **`0x5652`**（不是 redwood 的 FT3680） | `fts_wait_tp_to_valid: TP Ready,Device ID:0x5652` |
| X 范围 | `min 0, max 8639` | `getevent -pl` |
| Y 范围 | `min 0, max 19199` | 同上 |
| 触点数 | 10（`ABS_MT_SLOT` max 9；dts `max-touch-number=0xa`） | 同上 |
| 上电后的状态 | `fts_tp_state_recovery` → `Device ID` → `update game mode cmd: C1,00,03,0A,0A,0A,0A` | `dmesg` |

`0x5652` 这颗的 FTS 帧格式/报告布局要和 FT3680 逐字节比过才能确定（**见第 8 节第 4 条**）。
但 X/Y 上限 8639/19199 与 dts 的 `display-coords = <0 0 0x21c0 0x4b00>`（8640×19200）完全吻合，
所以 `focaltech_max_x/y = 8640/19200` 这一条**已经确定**。

### 11.4 面板

| 项 | 值 | 来源 |
|---|---|---|
| 面板名（cmdline） | `qcom,mdss_dsi_k11a_38_08_0a_dsc_cmd` | `/proc/cmdline` `msm_drm.dsi_display0=` |
| 分辨率 | 1080×2400，DSI **cmd** 模式 | `/sys/class/drm/card0-DSI-1/modes` |
| 刷新率档 | 60 / 90 / 120 Hz（`1080x2400x60x183357cmd` …） | 同上 |
| 显示控制器 | `ae00000.qcom,mdss_mdp` | dmesg |

与 redwood 同为 1080×2400，所以 XNU 侧的 framebuffer 分辨率、SpringBoard 缩放都不用改。

### 11.5 按键（实测，替代第 8 节第 3 条的一半）

`getevent -pl` 里 `qpnp_pon` 暴露的键正是 `KEY_VOLUMEDOWN` + `KEY_POWER` —— 证明
"电源 = KPDPWR_N、音量− = RESIN_N" 的假设成立（两者都在 PON 里）。音量+ 仍是 PM8150 GPIO6。

### 11.6 已采到的文件

`k40-dump/`（PC 侧，21 MB 固件 + 2.6 MB 文本）：

```
fdt.dtb                 930722 B   真实设备树（本文件所有地址的最终依据）
fdt.txt                 1.8 MB     上面那份的完整文本（tools/fdt_dump.py 转的，Windows 没 dtc）
cmdline.txt / iomem.txt / dmesg.txt / getprop.txt / partitions.txt / block-sizes.txt
fastboot-getvar.txt     275 行     hw-revision 20001 / unlocked yes / slot a / kernel:uefi
xbl_a.img               8 MB       XBL 原镜像（11.1 的版本号、11.2 的内存图都出自这里）
fw/                     61 个      a650_gmu/sqe/zap、adsp.mdt+b00..b19、aw8697_haptic、cs35l41 全套
```

`/data` 已用 **18 GB**（总量 106 GB，可用 88 GB），想备份随时可以 `bash backup-k40-userdata.sh`。

