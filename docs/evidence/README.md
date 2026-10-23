# 证据日志（2026-10-22）

这些是当天真机运行的原始日志，仓库里留一份，方便任何人不看手机也能复核结论。

| 文件 | 内容 | 关键行 |
|---|---|---|
| `2026-10-22-first-boot-kernel.log` | 第一次跑通内核的完整日志 | `apfs: volume 0 "System" … 45143 files`、`BSD root: md0`、`cpufreq: … 1804/2419/3187 MHz` |
| `2026-10-22-panic-16MB-io-map.log` | 触摸线程把整机打挂的那次 | `panic(cpu 1 …): kmem_alloc(…, 16777216, …) failed with 3 @vm_kern.c:178`（TLMM 申请 16 MB > 子映射 8 MB） |
| `2026-10-22-buttons-and-userspace.log` | iOS 用户态与按键链路 | `launchd.ios` / `SpringBoard` / `buttons: volume up PRESSED` → `redwood: input: sample type 4` |
| `2026-10-22-simulated-tap-appstore.log` | 模拟点击打开 App Store 那次 | `demo: tap N at 36660, 20640` → `presence: touching` → App Store 起来 |
| `2026-10-22-touch-tlmm-tiles.log` | 按 TLMM 分 tile 改造后的最新一次 | `pin controller: north at …, south at …`、`pins cs/clk/mosi/miso cfg 0 0 0 0`（引脚仍读 0，尚未修通） |

日志来源：`fastboot oem log` + `fastboot get_staged`（loader 侧），
或 Android 下 `su 0 dd if=/dev/block/by-name/logdump`（内核侧）。
