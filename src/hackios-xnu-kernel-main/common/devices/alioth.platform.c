/*
 * alioth (Redmi K40 / POCO F3 / Mi 11X, Snapdragon 870 / SM8250-AC, "kona").
 *
 * 这段已经并进 xnuloader/loader.c 的 platforms[]（loader 是一个镜像认所有机型，按 fb_base 选平台，
 * 所以不能放在单独的文件里编译）。本文件留作对照；改值的时候两边一起改。
 *
 * 已核实的值来自真机设备树（k40-dump/fdt.dtb）与 ABL 内存图（k40-dump/xbl_a.img）：
 *   GIC      /soc/interrupt-controller@17a00000: reg = <0x17a00000 0x10000 0x17a60000 0x100000>，stride 0x20000
 *   核       cpu@0/100/.../700，MPIDR 第二亲和域编号 -> core_shift 8
 *            0-3 = Cortex-A55 (capacity-dmips-mhz 0x400)，4-7 = Cortex-A77 (0x766) -> small_cores 0x0f
 *   fb_base  0x9C000000：reserved-memory/cont_splash_region@9c000000 (reg <0 0x9c000000 0 0x2300000>)，
 *            ABL 的 AddMem 表把 0x9c000000+0x2400000 叫 "Display Reserved"
 *
 * 见 docs/alioth-kona-addresses.md 第 1 节与第 11 节。
 */
static const struct platform platform_alioth = {
	/* io_base 必须非零：XNU 把 0 当"没有 SoC"，会跳过时钟初始化。kona 的外设就在这段里。 */
	.name = "alioth", .io_base = 0x00400000, .io_size = 0x3FC00000,
	.gic_dist = 0x17A00000, .gic_redist = 0x17A60000, .uart = 0, .log_other_cpu = 1,
	.cores = 8, .core_shift = 8,
	.small_cores = 0x0f,
	.fb_base = 0x9C000000,
};
