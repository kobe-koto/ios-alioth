#!/system/bin/sh
T=/sys/kernel/tracing
K=/sys/class/kgsl/kgsl-3d0
echo 10 > $K/idle_timer
# stop the compositor so nothing uses the GPU -> it falls to SLUMBER
stop surfaceflinger
# wait until SLUMBER (poll trace)
echo 1 > $T/events/kgsl/kgsl_pwr_set_state/enable
echo 1 > $T/tracing_on
reached=no
for i in $(seq 1 15); do
  sleep 1
  st=$(grep kgsl_pwr_set_state $T/trace | tail -1 | grep -oE "state=[A-Z_]+")
  if [ "$st" = "state=SLUMBER" ] || [ "$st" = "state=OFF" ]; then reached=yes; break; fi
done
echo "slumber_reached=$reached last=$st after ${i}s"
# arm the full capture
echo 0 > $T/tracing_on; echo > $T/trace
echo 1 > $T/events/kgsl/kgsl_regwrite/enable
echo 1 > $T/events/kgsl/kgsl_pwr_set_state/enable
echo 1 > $T/events/kgsl/kgsl_gmu_oob_set/enable
echo 1 > $T/tracing_on
# cold start: bring the compositor back -> GPU wakes from SLUMBER, CP restarts
start surfaceflinger
sleep 2
echo 0 > $T/tracing_on
echo "=== pwr states ==="; grep kgsl_pwr_set_state $T/trace | grep -oE "state=[A-Z_]+" | uniq -c
echo "=== SQE_CNTL(0x2020) hits ==="; grep -c "reg=0x2020" $T/trace
echo "=== total regwrite ==="; grep -c kgsl_regwrite $T/trace
# dump full trace for pulling
cp $T/trace /data/local/tmp/gold.trace
echo "saved /data/local/tmp/gold.trace"
