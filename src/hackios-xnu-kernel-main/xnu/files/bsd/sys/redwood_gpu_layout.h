/*
 * The GPU driver's arithmetic: the values the SoC's tables and the GPU's firmware are turned
 * into, in one place, so that the machine that builds the kernel can check them
 * (tools/gpu-test) and so that both phones' rows (struct adreno_soc, bsd/dev/redwood_adreno.c)
 * go through one expression. What is not here is the register sequences: those need the phone.
 *
 * Only <stdint.h> types are used, so that this header does not care what the kernel's own
 * headers call a word.
 */
#ifndef _SYS_REDWOOD_GPU_LAYOUT_H_
#define _SYS_REDWOOD_GPU_LAYOUT_H_

#include <stdbool.h>
#include <stdint.h>

/*
 * The chip id the GMU's firmware is told: the same upper 16 bits, then minor and patch id
 * packed in four bits each with the lower 8 bits unused (a6xx_gmu.c: a6xx_gmu_fw_start).
 * 0x06030500 becomes 0x06035000, 0x06050002 becomes 0x06050200.
 */
static inline uint32_t
redwood_gmu_chip_id(uint64_t chip_id)
{
	uint32_t id = (uint32_t)chip_id;

	return (id & 0xffff0000u) | (id << 4 & 0xf000u) | (id << 8 & 0x0f00u);
}

/*
 * A vote for a level of a supply: the level, its place in RPMh's list for the rail, and the place
 * of the level the memories' rail must have with it (vendor's setup_volt_dependency_tbl).
 * A level below the rail's first is rounded up to it; a level above its last cannot be voted for.
 */
static inline bool
redwood_rail_vote(uint32_t level, const uint16_t *rail, unsigned rail_levels, const uint16_t *mx,
    unsigned mx_levels, uint32_t *vote)
{
	unsigned at, with = 0;

	for (at = 0; at < rail_levels && rail[at] < level; at++) {
	}
	if (at == rail_levels || mx_levels == 0) {
		return false;
	}
	while (with + 1 < mx_levels && mx[with] < rail[at]) {
		with++;
	}
	*vote = (uint32_t)rail[at] << 16 | with << 8 | at;
	return true;
}

/*
 * UBWC's highest bank bit as the four registers take it (a6xx_gpu.c: a6xx_set_ubwc_config):
 * the low two bits go to hbb_lo, the rest to hbb_hi. 14 (LPDDR4X) is 1 and 0; 16 (LPDDR5) is
 * 3 and 0; 17 is 0 and 1.
 */
static inline void
redwood_ubwc_bits(uint32_t highest_bank_bit, uint32_t *lo, uint32_t *hi)
{
	uint32_t hbb = highest_bank_bit - 13;

	*lo = hbb & 3;
	*hi = hbb >> 2;
}

/* The first word of every message to the GMU: its id, its length in words, and its number. */
static inline uint32_t
redwood_hfi_header(uint32_t id, uint32_t words, uint32_t number)
{
	return id | words << 8 | number << 20;
}

#endif /* _SYS_REDWOOD_GPU_LAYOUT_H_ */
