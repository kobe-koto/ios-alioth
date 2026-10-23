# The Redmi K40 (alioth): what is known, and what the phone still has to say

The GPU driver (`xnu/files/bsd/dev/redwood_adreno.c`) was written for the POCO X5 Pro (redwood,
Adreno 642L). The K40 is the same GPU family -- Adreno 650, a6xx -- at the same block addresses,
so it is a second row of numbers in `struct adreno_soc` (`adreno_soc=a650`) and not a second
driver. Everything that can be settled without the phone has been; this page is the list of what
has to be read from it, and where each answer goes.

## Settled without the phone

From Mu-Silicium's `alioth.dtb` (parsed by `tools/alioth.py dt alioth.dtb`), from Linux's
`sm8250.dtsi`, `a6xx_catalog.c`, `gpucc-sm8250.c` and `gcc-sm8250.c`, and from Mesa
(`fd_devices.py`, `GPUId(650)`):

| What | Value | Where it is now |
|---|---|---|
| chip id | `0x06050002` | `soc_a650.chip_id`, DT `qcom,chipid` agrees |
| GMEM | 1 MB + 128 KB | `soc_a650.gmem` |
| speed bin fuse | qfprom `0x4000 + 0x19b`, 3 bits from bit 5 | `soc_a650.speed_bin_fuse` |
| speeds | 305 / 400 / 441.6 / 490 / 525 / 587 / 670 MHz | `alioth_speeds[]` (the DT lists all seven) |
| RPMh levels | 64 / 128 / 144 / 192 / 224 / 256 / 320 | `alioth_speeds[]` (from Linux's OPP table) |
| default speed | 525 MHz -- the fastest the slowest of the DT's speed bins is fused for | `soc_a650.default_speed` |
| UBWC highest bank bit | 16 (LPDDR5) | `soc_a650.highest_bank_bit` |
| zap memory | `0x8681a000`, 0x2000 (`reserved-memory` `pil_gpu_region`) | `soc_a650.zap_memory` |
| block addresses | 3d00000 / 3d6a000 / 3d90000 / 3da0000 / 3de0000 | unchanged from redwood |
| SMMU streams | 0 (3D core), 5 (GMU) | unchanged |
| LCD | 1080 x 2400, `cont_splash_region@9c000000` | `alioth.conf` `FB_BASE` |
| UEFI FD | `0x9FC00000`, 0x300000 | `alioth.conf` `FD_BASE`/`FD_SIZE` |
| Wi-Fi | QCA6390 on PCIe (MHI), not the redwood's WCN6750 | `alioth.conf` `WIFI_ATH11K=0` |

## Read from this phone (2026-10-23, Android booted, KernelSU root)

Commands and their output are in `evidence/device/` (the collection is read-only: `props.txt`,
`kgsl.txt`, `kgsl2.txt`, `fuse2.txt`, `dt-*.txt`, `dmesg-gpu.txt`, `iommu`/`pci-iommu.txt`,
`fw/` with the four firmware files, `fdt.dtb` the running device tree). The phone: alioth,
`SM8250` soc_id 356 rev 2.1, HyperOS `OS4.0.0.30.XPCCNXM`, Linux 4.19.325.

| What | Value on this phone | Verdict |
|---|---|---|
| chip id | `0x06050002` (`qcom,chipid`, and `kgsl-3d0/gpu_model` = `Adreno650v3`) | agrees with `soc_a650.chip_id` |
| speeds | `gpu_available_frequencies` = 670 / 587 / 525 / 490 / 441.6 / 400 / 305 MHz; `num_pwrlevels` 7, `max_clock_mhz` 670 | agrees with `alioth_speeds[]`; 525 as the default is conservative -- this unit is allowed 670 |
| speed bin fuse | qfprom cell `gpu_speed_bin` (corrected copy, `0x419b`, `bits = <5 3>`) reads `0x02`; Linux's `a6xx_catalog.c` swaps bins 2 and 3 for the a650 (`{2,3},{3,2}`), which is why the fitted table is the one with 670 | the value the driver prints at step 2 is diagnostic only; nothing selects speeds by it |
| GMEM | 1 MB + 128 KB (Linux catalog; `qcom,gpu-mempools` is in the device tree) | `soc_a650.gmem` |
| UBWC | `qcom,highest-bank-bit` = 16, `qcom,ubwc-mode` = 4 | `soc_a650.highest_bank_bit` = 16 |
| block addresses | kgsl `reg` 0x3d00000+0x400000 (then 0x3d61000, 0x3de0000, 0x3d8b000, 0x6900000); gmu `reg` 0x3d6a000+0x30000, PDC cfg 0xb290000, PDC seq 0xb490000; gpucc 0x3d90000+0x9000; smmu 0x3da0000 | all of them as the driver has them |
| SMMU streams | `gfx3d_user` 0, `gfx3d_secure` 2, `gmu_user` 4, `gmu_kernel` 5 | 0 (core) and 5 (GMU), as the driver has them |
| zap memory | the phone's own tree: `pil_gpu_region@8c41a000`, 0x2000. Mu-Silicium's `alioth.dtb` -- the tree an iOS run boots with -- reserves `pil_gpu_region@8681a000`, and the vendor boot loads `a650_zap` at 0xea100000 (its own dynamic choice). The address only has to be memory that is reserved in the map in use | the driver keeps `0x8681a000` (Mu-Silicium's map); `adreno_zap_mem=` overrides it |
| zap header size | `a650_zap.mdt` is 0x1acc bytes (0x94 header + 0x1a38 hashes): **two pages**; `a650_zap.b02` 0x68c | `zap_header()` now allocates `round_page(size)` and passes that size to TrustZone |
| SQE version | `a650_sqe.fw` 31988 bytes, word at offset 4 = `0x16dd114`, bits 0..11 = `0x114` | passes the a650's 0.95 floor (the first word is not the version; Linux copies from +4 as well) |
| GMU firmware | `a650_gmu.bin` 41548 bytes, 16 blocks; the four requests outside the GMU's own memory are 0x4000/0x8000, 0x144000/0x13000, 0x157000/0x9000, 0x60000000/0x1000 -- page-aligned, none over 0x100000; versions core/power `0x20010008`, HFI `0x20000001` | the driver makes exactly those four blocks |
| firmware location | all of it in `/vendor/firmware` (there is no `/vendor/firmware_mnt/image/a650_*`); gmu sha256 `df79fa84...`, sqe `d8c75ba0...`, mdt `e768fe57...`, b02 `a415e545...` | the four files the driver needs: gmu, sqe, mdt, b02 (b01 is the hashes already inside the mdt) |
| LCD | `cont_splash_region@9c000000`, 0x2300000; the loader prints `display 1080 x 2400 at 9c000000` | `FB_BASE` = 0x9C000000 |
| GPU rails | `gpu_cx_gdsc` <- `pm8150_s3_level`; `gpu_gx_gdsc` <- `pm8150a_s1_level` (dmesg). The driver's `gfx.lvl` comment ("PM8350C S7") is the redwood's | the GMU votes these itself once its RPMh interface is on; the rails must be up for step 3 to answer |
| Wi-Fi | PCI `17cb:1101` (QCA6390 WLAN, cnss) and `17cb:0306` (BT over MHI); `cnss` loads `qca6390/amss20.bin` | `WIFI_ATH11K=0` is right; no iOS driver |
| GPU interrupts | SPI 0x130 (`kgsl_hfi_irq`), 0x131 (`kgsl_gmu_irq`) | the driver polls the registers instead |

Still open after this: the RPMh level enumeration (`gfx.lvl`, `cx.lvl`, `mx.lvl`) -- the vendor tree
has no `qcom,level`/`opp-level`, so `alioth_speeds[]` still carries Linux's OPP levels;
`step_outside` prints the boot loader's own list from cmd-db (memory at 0x80860000) when it runs.
And everything the list below ("To try on the phone") names: SMMU under the hypervisor, the GMU's
HFI answers, the PDC/RSCC program, and the picture.

The same folders carry the other redwood-specific drivers: touch (`redwood_goodix.c`), buttons and
CPU frequency (`redwood_input.c`, `redwood_cpufreq.c`), sound (`redwood_audio.c`). They are not
adapted and the first run should leave them off (`touchscreen=1` out, `cpufreq=1` out).

## The driver's steps on this phone (2026-10-23)

Run with `adreno_soc=a650 adreno=N adreno_return=1 adreno_watch=10 bootcpu=7 cpus=8`
(`SYS=` in `boot-one.sh`: kernel only, no `system.apfs`). Steps 1 to 19 pass; step 20 ends the run at the
command processor's start.

| Step | Answer | What it changed |
|---|---|---|
| 1 | `gcc pll votes 0x1206d7f`; RPMh `gfx.lvl@0x30050`, `cx.lvl@0x30000`, `mx.lvl@0x30010` | nothing |
| 2 | `speed bin 2: an Adreno 650`; the DT has only the error-corrected qfprom cell | nothing |
| 3 | every GPUCC register reads as the boot loader left it | nothing |
| 4 | writing `cx_gdscr` `0x222000` collapses nothing; reads back `0xf8222000`; `CX is on` | nothing |
| 5 | `cxo 19200144 Hz`, `cx_gmu 200000396 Hz`, `cxo_aon 19199560 Hz`, `gx_gmu 0`, `ahb 47086216 Hz` | **the counter table**: the K40's `xo_div4_cbcr` is `0x4300c` (not `0x6200c`), GCC's debug mux takes `0x163` (not `0x146`), and the GPU controller's post-divider field is 2 bits (`0x3`) -- the value written is `post_div_val - 1` = 1 |
| 6, 7 | the GMU's counter at 19199091 Hz, the crystal; `THE GPU BLOCK IS ALIVE`; RSCC answers | nothing |
| 8, 9 | `idr0 0x4c017e06`, `idr1 0x20000005` -- 6 SMRs, 5 contexts, 8 pages; the DT's `0x20000` is room to spare over the `0x10000` these need | `smmu_layout()` now fails only if the registers would not fit, not if the sizes differ |
| 10-12 | the GMU's DTCM reads and writes; TrustZone answers 0 to `0x42000201` with the zap header | nothing |
| 13-15 | the GMU's firmware in and running: core `0x20010008`, HFI `0x20000001` | nothing |
| 16 | the HFI queues come up; the hidden RSCC word `0x80000021` is accepted | nothing -- Linux's `0x80000000` is not needed here |
| 17 | speed table, bus table, "start" and 525 MHz all accepted; `THE 3D CORE HAS POWER AND ANSWERS`; 3D clock `524999528 Hz` | nothing |
| 18 | with `core_mask` 0x400 the SMR write read back 0; with the DT's `0x401`, SMR0 = `0x84010000` and SMR2 = `0x84010001` are accepted; `rbbm_status 0x1` | **`soc->core_mask`**: `sm8250.dtsi` says `iommus = <&adreno_smmu 0 0x401>` for the 3D core, `5 0x400` for the GMU |
| 19 | give-up (`0x42000206`), signature (`0x42000201`) and `SCM_PAS_MEM_SETUP` (`0x42000202`) all return 0, then `TRUSTZONE HAS AUTHENTICATED AND STARTED THE ZAP SHADER` | **`soc_a650.zap_memory = 0`**: the driver takes two contiguous pages of its own (`kmem_alloc_contig()` + `kvtophys()`) instead of the device tree's `0x8681a000`, which is outside the physical window the loader gives the kernel |
| 20 | up to and including `cp_sqe_cntl`'s write, everything answers (`cp_apriv_cntl 0x6e`, `rbbm_status 0x1`); **the start itself is the end of the run: not one line after it, and the phone resets within a second** | nothing yet. Two controls settle what is fatal: the same register written with 0 is harmless (the write returns, nine reads follow, the ring command is submitted), and the programmed core is left idle for 2.5-3 s without a reset, so neither the register nor an idle power collapse ends it -- the start does. Ruled out on the phone: the microcode's address (`adreno_blind=1`), the zap's order (`adreno_skip=524288`), an SMMU refusal of the first fetch (`adreno_direct=1`, bypass), register offsets (they agree with the phone's `a6xx_reg.h`), `SCTLR`/PTE attributes (they agree with `arm-smmu-qcom.c`/`io-pgtable-arm.c`), `SPTPRAC` (its control register reads back 0 when written, so the write is not taken), `GMU_OOB_GPU_SET` (both interrupt bit sets are never acknowledged), and `CP_RB_RPTR_ADDR` with `CP_RB_CNTL` bit 27 clear (`adreno_rptr=1`). What remains is the rest of the vendor's `a6xx_start()` (`RBBM_CLOCK_*`, VBIF, the a650 `TPL1` weights, `CP_PROTECT`, GMU counters). |
| 21-22 | not run | |

## Reading it again, when the phone's build changes

The four files are already in `evidence/device/fw` (from `/vendor/firmware`), and the running
tree in `evidence/device/fdt.dtb`. To repeat it on a new build, with the phone booted in Android
and root available:

```sh
adb shell 'cat /sys/class/kgsl/kgsl-3d0/gpu_available_frequencies'    # 670..305 MHz
adb shell 'cat /sys/class/kgsl/kgsl-3d0/freq_table_mhz; cat /sys/class/kgsl/kgsl-3d0/num_pwrlevels'
adb shell 'cat /sys/bus/nvmem/devices/qfprom0/gpu_speed_bin | od -An -tx1'   # 0x419b, bits <5 3>
adb shell 'cat /sys/firmware/fdt' > fdt.dtb
adb pull /vendor/firmware/a650_gmu.bin
adb pull /vendor/firmware/a650_sqe.fw
adb pull /vendor/firmware/a650_zap.mdt
adb pull /vendor/firmware/a650_zap.b02
```

Then, on this machine, the three files the driver will refuse without:

```sh
tools/alioth.py gmu a650_gmu.bin    # requests outside the GMU's own memory page-aligned, none over 0x100000
tools/alioth.py sqe a650_sqe.fw     # word at offset 4 & 0xfff >= 0x095
tools/alioth.py zap a650_zap.mdt    # 32-bit ELF, >= 2 segments, header + hashes
tools/alioth.py dt  fdt.dtb         # zap region, chip id, speeds, SMMU, Wi-Fi
```

Each prints `FAIL` with the reason; a file that fails here would stop the driver at steps 14, 18
or 12 respectively, and the driver's own step log would be the only other place to find out.
(The K40's own four files pass: `0 failures`.)

The framebuffer: the loader prints `display 1080 x 2400 at 9c000000`, which is the phone's
`cont_splash_region@9c000000`; `platform_alioth` in `xnuloader/loader.c` carries the same address.

## The questions this page waited for (answered above)

Boot with `adreno_soc=a650 adreno=1`, then one step further at a time; each step prints what it is
about to touch and what it found. These were the answers wanted, and the section above has them:

| Step | What it settled |
|---|---|
| 3 | whether the GPUCC registers read back as the boot loader left them -- they do |
| 2 | the speed bin the fuses give -- `0x02`, an Adreno 650 |
| 8, 9 | whether the hypervisor lets us at the SMMU's contexts -- reads yes; writes only with the DT's own stream mask |
| 15 | whether the GMU's firmware reports `0x100` (`GMU_STARTED_MASK`) -- it does |
| 16 | whether the two PDC writes and the RSCC program are enough, and whether the hidden command's last word wants `0x80000000` -- `0x80000021` is accepted |
| 17 | which RPMh level the GMU accepts for 525 MHz -- level 5, and the 3D clock then measures `524999528 Hz` |
| 18 | whether `a650_sqe.fw`'s microcode is accepted from offset 4 -- yes |
| 19 | whether the zap shader can be loaded -- **open**: the SCM calls answer, the write to `0x8681a000` hangs |
| 20, 21 | whether the command processor starts and leaves secure mode -- not reached |
| 22 | whether the picture reaches the panel -- not reached |

The values that turn out wrong go back into `struct adreno_soc` and `alioth_speeds[]`; the
`adreno_*=` boot-args exist so that a run can try one without a rebuild.

Not attempted: Bluetooth. iOS's stack is Apple's `IOBluetoothFamily` and there is no open
replacement; the K40's QCA6390 would need that as well as the same MHI work Wi-Fi needs.
