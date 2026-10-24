#!/system/bin/sh
T=/sys/kernel/tracing
K=/sys/class/kgsl/kgsl-3d0
echo 10 > $K/idle_timer
stop surfaceflinger
echo 1 > $T/events/kgsl/kgsl_pwr_set_state/enable
echo 1 > $T/tracing_on
st=""
for i in $(seq 1 15); do
  sleep 1
  st=$(grep kgsl_pwr_set_state $T/trace | tail -1 | grep -oE "state=[A-Z_]+")
  [ "$st" = "state=SLUMBER" ] && break
done
echo "slumber=$st after ${i}s"
# arm HFI + oob + pwr trace
echo 0 > $T/tracing_on; echo > $T/trace
echo 1 > $T/events/kgsl/kgsl_hfi_send/enable
echo 1 > $T/events/kgsl/kgsl_hfi_receive/enable
echo 1 > $T/events/kgsl/kgsl_gmu_oob_set/enable
echo 1 > $T/events/kgsl/kgsl_gmu_oob_clear/enable
echo 1 > $T/events/kgsl/kgsl_pwr_set_state/enable
echo 1 > $T/tracing_on
start surfaceflinger
sleep 2
echo 0 > $T/tracing_on
echo "=== HFI send count ==="; grep -c kgsl_hfi_send $T/trace
echo "=== HFI recv count ==="; grep -c kgsl_hfi_receive $T/trace
cp $T/trace /data/local/tmp/gold-hfi.trace
echo "saved"
