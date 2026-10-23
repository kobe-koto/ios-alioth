# 从 UniXNU 学到的：对照、可借鉴项与本项目的改进清单

> 写于 2026-10-22。对照对象：<https://github.com/UniXNU/UniXNU>（文档站 <https://unixnu.com>）。
> 结论先放这里：**两者是同一条技术路线的两个独立实现**（都用 Mu-Silicium 的 UEFI、都把 XNU 编成
> BCM2837 机器配置跑 4 KiB 页），但 UniXNU 在**页面/物理地址的正确性**、**设备抽象的可扩展性**和
> **GPU 用户态**三件事上比我们走得远；其中前两项对 K40 是**真 bug 级别的风险**，第三项是我们
> GPU 从 0 开始的最大捷径。

---

## 1. 两者是什么关系

| | HackiOS（本项目） | UniXNU |
|---|---|---|
| 目标 | 把 iOS 16.5 用户态跑在 Android 手机上 | 同一件事，另外还要跑 macOS |
| UEFI | Mu-Silicium 端口（redwood / alioth） | 同样基于 Mu-Silicium，每机型一个 `uefi-<device>` 仓库 |
| 内核 | XNU 8796.121.2，`MACHINE_CONFIGS=BCM2837`（4 KiB 布局） | 同样 BCM2837 + 一整套 4 KiB 补丁 |
| 设备组织 | 单棵树，`common/devices/<name>.conf` + `#ifdef PLATFORM_<DEV>` | 内核仓 + 设备仓（`board.toml`、defconfig、drivers/kits/patches/package），**同名 module 覆盖** |
| 用户态 | 未改动的 iOS 16.5（IPSW 里取） | 同 + NativePrelink + Data seed |
| GPU | 自己写 `redwood_adreno.c`（183 KB） | NativeMetal + metal2vulkan + Turnip(IR3) + NativeAdreno |
| 已知可用机型 | 准备上 alioth（本项目） | Xiaomi Pad 6S Pro（sheng，Adreno 740，含桌面合成） |

**关键共性**：都用 `MACHINE_CONFIGS=BCM2837` —— 也就是都吃 4 KiB 页这套布局。所以 UniXNU 踩过的
坑，我们大概率也会踩，只是还没走到那一步。

---

## 2. 必须抄的三件事（对 K40 是真风险）

### 2.1 物理地址超过 4 GiB 的 32 位截断（`zzx-pmap-sync-64bit-pa`）

XNU 的 `pmap_sync_page_attributes_phys()` 里原来是：

```c
flush_dcache((vm_offset_t)(pp << PAGE_SHIFT), PAGE_SIZE, TRUE);   /* pp 是 32 位，左移前就截断了 */
```

改成：

```c
flush_dcache((vm_offset_t)ptoa(pp), PAGE_SIZE, TRUE);            /* ptoa() 先加宽再移位 */
```

**为什么对我们是要害**：K40 的 DRAM 是 `0x80000000 + 0x3BB00000` 和 `0xC0000000 + 0x1C0000000`，
上界 `0x280000000` = **10 GiB**。凡是落在 4 GiB 以上的物理页，`pp << 12` 会丢掉高位，
`flush_dcache` 就刷到错误的地址 —— 表现为随机数据损坏、DMA 读回旧内容、偶发 panic，
而且极难定位（看起来像驱动 bug）。XNU 里凡是拿 `pp`（page number）直接移位的都要过一遍。

### 2.2 启动页表的容量（`native-4k-bootstrap-capacity`）

`osfmk/arm64/start.s` 在开 MMU 之前自己建页表，池子大小 `BOOTSTRAP_TABLE_SIZE` 是给 Apple 设备
（≤ 4 GiB 左右）算的。UniXNU 的补丁把它按"每 6 GiB 映射最多 7 个 L2 页"重算：

```asm
#elif !defined(APPLE_ARM64_ARCH_FAMILY) && !__ARM_16K_PG__
#define BOOTSTRAP_TABLE_SIZE (ARM_PGBYTES * 16)
```

并在分配新 L2 表之前加容量检查，越界就停在 `Lbootstrap_tables_exhausted` 的自旋里
（此时 MMU 还没开，调试器能直接看寄存器）。

**为什么对我们是要害**：我们 `platform_alioth.io_size = 0x3FC00000` 只覆盖 1 GiB，XNU 还要映射
物理内存与 framebuffer；K40 有 8 GB 内存。池子不够就是在 `start.s` 里静默跑飞 ——
没有串口、没有日志，看起来像"loader 交棒后立刻死"。

### 2.3 代码签名的 16 KiB CodeDirectory（`native-4k-signature-hash-cache`）

Apple 内核缓存里的 CodeDirectory 用 16 KiB 哈希页，4 KiB 内核按 4 KiB 校验 —— 对不上。
UniXNU 的做法是读原始 16 KiB 块、验原哈希、再派生出每 4 KiB 页的摘要表挂到 `cs_blob` 上。

**对本项目的判断**：我们**自己编内核**、不用 Apple 的 kernelcache，所以内核侧大概率不触发；
但用户态二进制仍走 `cs_validate_page`（本项目靠注入库 + 改标志绕过）。**先确认 `xnu/redwood.patch`
里对 `cs_validate_page` / `csblob` 做了什么**，如果只是关掉校验，那这条可以先不做；
如果走的是"派生哈希"的路子，就要按 4 KiB 改。

---

## 3. 值得改的工程做法

### 3.1 设备抽象：`#ifdef` → 模块覆盖（中期）

我们现在的做法是"一个文件里两套常量，`-DPLATFORM_ALIOTH` 二选一"。UniXNU 的做法是
**内核仓 + 设备仓**：设备仓里的同名 module 覆盖内核仓的，`package/` 变成 kit。
好处是：加到第 3、4 台机器时不会变成 `#if defined(A) || defined(B) ...` 的意大利面；
坏处是要有 module 解析器。

**建议**：K40 跑通之前别动。跑通之后如果要支持第二台 kona 机器（比如 haydn/munch 或 POCO F3 的兄弟），
再把"常量块"抽成 `platform_<dev>.h` + `module` 清单，逻辑代码保持一份。

### 3.2 把"不变量"写成脚本（立刻可做）

UniXNU 有一整套 `scripts/check-*.py`：编一遍 `TCR_EL1_BOOT` 看 TG0/TG1 字段、把页大小策略在
RAM 边界上跑一遍、编译 `cs_validate_codedirectory` 的门禁逻辑验证八种组合、检查 PGZ 对齐……

对应到我们这边，等价物是"**代码里的常量必须和设备树/ABL 内存图一致**"。这个不需要编译器，
现在就能写：读 `k40-dump/fdt.txt` 和 `k40-dump/xbl_a.img` 里的 AddMem 表，断言
`TLMM_PHYS / GCC_PHYS / SE_PHYS / EPSS / UFD FD_BASE / fb_base / gic_dist / cmd-db / SMEM`
与源码里的 `#define` 一致。改错一个地址就当场报错，而不是等开机黑屏。
（本项目已加 `tools/fdt_dump.py`，是这套检查的底座。）

### 3.3 分阶段 bring-up 清单（已对齐）

UniXNU 的顺序：firmware → menu → payload → kernel entry → platform expert → storage → root → userland。
我们的里程碑（loader 画面+USB 日志 → 内核 verbose → SpringBoard）与它同构，可以在
`docs/checks.md` 里照这个粒度补齐"每阶段看什么日志、什么算过"。

### 3.4 调试手段

UniXNU 用 QEMU + gdb 停在内核 entry 检查 `TCR_EL1`（TG0=0、TG1=2）、`SCTLR_EL1.M`、`TTBR0/1`、
`_page_shift*` 四个符号。我们已经有 `qemu-virt` 目标，**在碰真机之前应当先在 QEMU 里
用 gdb 对这五个值做一次断言**——尤其 `_page_shift` 必须是 12。这条几乎零成本，能挡掉
"页大小错→用户态全崩"这一类问题。

---

## 4. GPU：从 0 到 1 的捷径（对本项目价值最大）

UniXNU 在 Adreno 740 上已经跑通完整链路，而且**每一层都是独立公开仓库**：

```
Metal 应用
  → NativeMetal        Metal 前端 + metal2vulkan(AIR→SPIR-V) + IOSurface/扫描输出客户端
  → Turnip (Mesa)      SPIR-V → NIR → IR3（a6xx/a7xx 都支持，含 Darwin KMD 对接）
  → NativeAdreno       内核侧：GMU 上电/HFI、CP 环、BO、GPU 地址、fence、SMMU 上下文
  → AdrenoPM4 kit      A740 的 PM4 状态包/常量/光栅化
  → ArmSmmu4K kit      4 KiB 阶段 1/2 页表
```

**对 K40（Adreno 650 = a6xx gen2）的可复用度**：

| 组件 | 能否直接用 | 说明 |
|---|---|---|
| NativeMetal（前端 + metal2vulkan） | ✅ 基本通用 | 与 GPU 代际无关，只和 Metal 版本/驱动能力有关 |
| Turnip (Mesa freedreno) | ✅ 已支持 a6xx | Adreno 650 是 Turnip 的主力目标之一 |
| ArmSmmu4K | ✅ 通用 | 我们 K40 的 SMMU 也是 4 KiB |
| NativeAdreno 内核服务 | 🟡 改寄存器 | GMU/CP 启动流程同构，`a6xx` 与 `a7xx` 的 GMU 寄存器/HFI 版本不同 |
| AdrenoPM4 kit | 🔴 要新写 | A740 的 PM4 常量不能给 a650 用，需要 a650 的一套（Linux `freedreno` 里有现成来源） |

**结论**：`redwood_adreno.c`（183 KB，针对 642L 从零写的寄存器级驱动）不必继续投入。
更划算的路线是：**移植 UniXNU 的 NativeMetal + Turnip + NativeAdreno 骨架，再补一份 a650 的
AdrenoPM4**。这条路线还有一个额外好处：shader 不用我们操心（Metal → SPIR-V → IR3 全自动）。

风险：UniXNU 是 BSD-2-Clause-Patent，兼容我们的用法；但它的驱动依赖 `NativePrelink`/`Data seed`
这套打包方式，接到 HackiOS 的 `userland/build.sh` 里要改镜像构建。属于"第二阶段的大工程"。

---

## 5. 本项目自身的改进项（与 UniXNU 无关，但顺路发现）

1. **`xnu/apply.sh` 不能增量更新**：树已存在就退出，改了 `xnu/files/**` 必须手工 `cp -a`。
   建议加 `--update`：只 `cp -a files/.` 并 `git apply` 新增的 patch 段。
2. **`ios165/fetch.sh` 只支持从 Apple CDN 拉**：已加 `LOCAL_IPSW=`（见本次改动），
   有本地 IPSW 时用 7z 直接取成员，离线可用。
3. **GitHub 不可靠时没有退路**：`xnu-deps/setup.sh` 的 `fetch()` 现在会重试 3 次并支持
   `GH_PROXY=https://gh-proxy.com/` 前缀代理（本次改动）。
4. **缺不变量检查脚本**（见 3.2），建议新增 `tools/check-constants.py`。
5. **`prebuilt/` 与源码可能失配**：一旦源码改过，`build.sh` 在没装 theos 时会静默用 prebuilt，
   容易"改了没生效"。建议在 `build.sh` 里对比 `xnu/files/**` 的 mtime 与 `prebuilt/mach.*`，
   源码更新时明确警告。

---

## 6. 参考

- UniXNU 总览 <https://unixnu.com/guide/overview>
- 4 KiB 页补丁 <https://unixnu.com/xnu/four-k-page-tables>
- 移植流程 <https://unixnu.com/porting/>
- Adreno 740 原生驱动 <https://unixnu.com/drivers/native-adreno>
- 设备仓示例 <https://github.com/UniXNU/UniXNU-sheng>、UEFI 示例 <https://github.com/UniXNU/uefi-sheng>
