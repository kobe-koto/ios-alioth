/*
 * Tests of the GPU driver's arithmetic (bsd/sys/redwood_gpu_layout.h) on the machine that builds
 * the kernel; tools/gpu-test/run.sh compiles and runs this. Nothing here needs the phone: these
 * are the values that go into registers, and a wrong one is a write the phone may not survive.
 *
 * What is checked:
 *   1. the GMU's chip id, against the two known GPUs and against the way the bits are laid out;
 *   2. RPMh votes, from tables like the phone's, including a level between two of the rail's,
 *      one above its last, and the "with" index the memories' rail takes;
 *   3. the two halves of UBWC's highest bank bit, and the four registers they end up in, for the
 *      redwood's LPDDR4X (14) and the K40's LPDDR5 (16);
 *   4. the first word of a message to the GMU, at the edges of its three fields.
 */
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include <sys/redwood_gpu_layout.h>

static int checks, failures;

static void
check(bool ok, const char *format, ...)
{
	va_list list;

	checks++;
	if (ok) {
		return;
	}
	failures++;
	printf("FAIL: ");
	va_start(list, format);
	vprintf(format, list);
	va_end(list);
	printf("\n");
}

/* ---- the GMU's chip id ---------------------------------------------------------------------- */

static void
test_chip_id(void)
{
	uint32_t redwood = redwood_gmu_chip_id(0x06030500), alioth = redwood_gmu_chip_id(0x06050002);

	check(redwood == 0x06035000u, "a660 0x06030500 packs to %#x, not 0x06035000", redwood);
	check(alioth == 0x06050200u, "a650 0x06050002 packs to %#x, not 0x06050200", alioth);
	check((redwood & 0xffff0000u) == 0x06030000u, "the upper 16 bits of the a660's id are not kept");
	check((alioth & 0xffff0000u) == 0x06050000u, "the upper 16 bits of the a650's id are not kept");
	check((redwood >> 12 & 0xf) == 5 && (redwood >> 8 & 0xf) == 0, "the a660's minor/patch are not 5/0");
	check((alioth >> 12 & 0xf) == 0 && (alioth >> 8 & 0xf) == 2, "the a650's minor/patch are not 0/2");
	check((alioth & 0xff) == 0, "the lower 8 bits of the a650's chip id are not left unused");
	/* every chip id gives back its own upper half only, whatever the lower one is */
	for (uint64_t id = 0x06000000u; id < 0x06000010u; id++) {
		check((redwood_gmu_chip_id(id) & 0xffff0000u) == ((uint32_t)id & 0xffff0000u),
		    "the upper half of %#llx is not kept", id);
	}
}

/* ---- RPMh votes ----------------------------------------------------------------------------- */

static void
test_rail_vote(void)
{
	static const uint16_t gfx[] = { 0, 64, 128, 192 };
	static const uint16_t cx[] = { 0, 48, 96, 144 };
	static const uint16_t mx[] = { 0, 16, 32, 48, 64 };
	static const uint16_t mx_short[] = { 0, 16 };
	uint32_t vote = 0xdeadbeef;

	/* a level of the rail's own: the level, its index, and the highest memories' level not above it */
	check(redwood_rail_vote(0, gfx, 4, mx, 5, &vote) && vote == 0x00000000u, "level 0 of the GPU's rail: %#x", vote);
	check(redwood_rail_vote(64, gfx, 4, mx, 5, &vote) && vote == 0x00400401u, "level 64: %#x", vote);
	check(redwood_rail_vote(128, gfx, 4, mx, 5, &vote) && vote == 0x00800402u, "level 128: %#x", vote);
	check(redwood_rail_vote(192, gfx, 4, mx, 5, &vote) && vote == 0x00c00403u, "level 192: %#x", vote);
	/* between two levels: the next one up, as the vendor's tables do */
	check(redwood_rail_vote(96, gfx, 4, mx, 5, &vote) && vote == 0x00800402u, "level 96 rounds to 128: %#x", vote);
	check(redwood_rail_vote(1, gfx, 4, mx, 5, &vote) && vote == 0x00400401u, "level 1 rounds to 64: %#x", vote);
	/* above the last: no vote, and the word is left alone */
	vote = 0xdeadbeef;
	check(!redwood_rail_vote(193, gfx, 4, mx, 5, &vote) && vote == 0xdeadbeef, "level 193 is votable");
	check(!redwood_rail_vote(128, gfx, 0, mx, 5, &vote), "an empty rail votes");
	check(!redwood_rail_vote(128, gfx, 4, mx, 0, &vote), "a missing memories' rail votes");
	/* the memories' rail: the highest of its levels that is not above the rail's */
	check(redwood_rail_vote(48, cx, 4, mx, 5, &vote) && vote == 0x00300301u, "cx 48 with mx 64: %#x", vote);
	check(redwood_rail_vote(128, cx, 4, mx, 5, &vote) && vote == 0x00900403u, "cx 128 rounds to 144: %#x", vote);
	check(redwood_rail_vote(96, cx, 4, mx_short, 2, &vote) && vote == 0x00600102u, "cx 96 with mx 16: %#x", vote);
	/* the memories' rail never reaches that far: its last level is the one */
	check(redwood_rail_vote(192, gfx, 4, mx_short, 2, &vote) && vote == 0x00c00103u, "gfx 192 with mx 16: %#x", vote);
}

/* ---- UBWC ----------------------------------------------------------------------------------- */

/* The four registers a6xx_set_ubwc_config writes, with this driver's other bits (a660 family). */
static void
ubwc_registers(uint32_t hbb, uint32_t *rb, uint32_t *tpl1, uint32_t *sp, uint32_t *uche)
{
	uint32_t lo, hi;

	redwood_ubwc_bits(hbb, &lo, &hi);
	*rb = 1u << 11 | hi << 10 | 1u << 4 | lo << 1;
	*tpl1 = hi << 4 | lo << 1;
	*sp = hi << 10 | 2u << 4 | lo << 1;
	*uche = lo << 21;
}

static void
test_ubwc(void)
{
	uint32_t lo = 0xdead, hi = 0xdead, rb, tpl1, sp, uche;

	redwood_ubwc_bits(14, &lo, &hi);
	check(lo == 1 && hi == 0, "highest bank bit 14 splits as %u/%u, not 1/0", lo, hi);
	redwood_ubwc_bits(16, &lo, &hi);
	check(lo == 3 && hi == 0, "highest bank bit 16 splits as %u/%u, not 3/0", lo, hi);
	redwood_ubwc_bits(17, &lo, &hi);
	check(lo == 0 && hi == 1, "highest bank bit 17 splits as %u/%u, not 0/1", lo, hi);

	ubwc_registers(14, &rb, &tpl1, &sp, &uche);
	check(rb == 0x812u && tpl1 == 0x2u && sp == 0x22u && uche == 0x200000u,
	    "the redwood's (14) registers are %#x %#x %#x %#x, not 812 2 22 200000", rb, tpl1, sp, uche);
	ubwc_registers(16, &rb, &tpl1, &sp, &uche);
	check(rb == 0x816u && tpl1 == 0x6u && sp == 0x26u && uche == 0x600000u,
	    "the K40's (16) registers are %#x %#x %#x %#x, not 816 6 26 600000", rb, tpl1, sp, uche);
}

/* ---- messages to the GMU -------------------------------------------------------------------- */

static void
test_hfi_header(void)
{
	check(redwood_hfi_header(0x0a, 4, 0xabc) == 0xabc0040au, "a plain message: %#x", redwood_hfi_header(0x0a, 4, 0xabc));
	check(redwood_hfi_header(0, 0, 0) == 0, "an empty message is not zero");
	check(redwood_hfi_header(0x12, 0xff, 0xfff) == 0xfff0ff12u, "all fields full: %#x",
	    redwood_hfi_header(0x12, 0xff, 0xfff));
	check(redwood_hfi_header(0xff, 0, 0) == 0xffu, "an id of 0xff spreads: %#x", redwood_hfi_header(0xff, 0, 0));
	check(redwood_hfi_header(0, 1, 0) == 0x100u, "one word is not bit 8: %#x", redwood_hfi_header(0, 1, 0));
	check(redwood_hfi_header(0, 0, 1) == 0x100000u, "number 1 is not bit 20: %#x", redwood_hfi_header(0, 0, 1));
}

int
main(void)
{
	test_chip_id();
	test_rail_vote();
	test_ubwc();
	test_hfi_header();
	printf("gpu-test: %d checks, %d failures\n", checks, failures);
	return failures == 0 ? 0 : 1;
}
