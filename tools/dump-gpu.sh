#!/system/bin/sh
# Read the GPU's registers as Android's own driver leaves them, then put the knobs back.
# Nothing is written to the GPU: only kgsl's "keep it powered" switches, and they are restored.
D=/sys/class/kgsl/kgsl-3d0

show() {
	for f in force_rail_on force_clk_on force_bus_on force_no_nap gpuclk gpu_busy_percentage; do
		printf '%s=%s\n' "$f" "$(cat $D/$f 2>&1)"
	done
}

echo "== before"
show

for f in force_rail_on force_bus_on force_clk_on force_no_nap; do
	echo 1 > $D/$f 2>/dev/null
done
sleep 1
echo "== after (forced on)"
show

echo "== first read, to see that mmio is allowed here"
devmem 0x3d00840 2>&1

echo "== registers"
while read addr name; do
	case "$addr" in
	0x*) ;;
	*) continue ;;
	esac
	printf '%-34s %-10s = %s\n' "$name" "$addr" "$(devmem $addr 2>&1)"
done <<'EOF'
0x3d00840 rbbm_status
0x3d00058 rbbm_gbif_halt
0x3d0005c rbbm_gbif_halt_ack
0x3d000e0 rbbm_int_0_mask
0x3d002b8 rbbm_clock_cntl
0x3d038e8 uche_gbif_gx_config
0x3d02000 cp_rb_base
0x3d02008 cp_rb_cntl
0x3d02010 cp_rb_rptr_addr_lo
0x3d02014 cp_rb_rptr_addr_hi
0x3d02020 cp_sqe_cntl
0x3d020c0 cp_sqe_instr_base_lo
0x3d020c4 cp_sqe_instr_base_hi
0x3d02084 cp_hw_fault
0x3d0208c cp_interrupt_status
0x3d02090 cp_protect_status
0x3d02110 cp_apriv_cntl
0x3d0213c cp_protect_cntl
0x3d0230c cp_mem_pool_size
0x3d02304 cp_roq_thresholds_1
0x3d02308 cp_roq_thresholds_2
0x3d02340 cp_perfctr_cp_sel_0
0x3d02cd0 cp_lpac_prog_fifo_size
0x3d02108 cp_addr_mode_cntl
0x3d03004 vsc_addr_mode_cntl
0x3d21804 gras_addr_mode_cntl
0x3d23814 rb_addr_mode_cntl
0x3d27804 pc_addr_mode_cntl
0x3d2f814 hlsq_addr_mode_cntl
0x3d29804 vfd_addr_mode_cntl
0x3d25804 vpc_addr_mode_cntl
0x3d03800 uche_addr_mode_cntl
0x3d2b804 sp_addr_mode_cntl
0x3d2d804 tpl1_addr_mode_cntl
0x3d3e040 secvid_tsb_addr_mode_cntl
0x3d27800 pc_dbg_eco_cntl
0x3d23810 rb_dbg_eco_cntl
0x3d2d820 tpl1_bicubic_weights_0
0x3d2d824 tpl1_bicubic_weights_1
0x3d2d828 tpl1_bicubic_weights_2
0x3d2d82c tpl1_bicubic_weights_3
0x3d2d830 tpl1_bicubic_weights_4
0x3d3d000 rbbm_secvid_trust_cntl
0x3d3e000 secvid_tsb_trusted_base_lo
0x3d3e004 secvid_tsb_trusted_base_hi
0x3d3e008 secvid_tsb_trusted_size
0x3d3e00c secvid_tsb_cntl
0x3d69114 gbif_halt
0x3d69118 gbif_halt_ack
0x3d6a204 gmu_gx_sptprac_power_control
0x3d7e340 gmu_sptprac_pwr_clk_status
0x3d7e600 gmu_hfi_ctrl_status
0x3d7e644 gmu2host_intr_clr
0x3d7e648 gmu2host_intr_info
0x3d7e650 host2gmu_intr_set
EOF

echo "== restore"
for f in force_rail_on force_clk_on force_bus_on force_no_nap; do
	echo 0 > $D/$f 2>/dev/null
done
show
