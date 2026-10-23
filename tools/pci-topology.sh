#!/system/bin/sh
for d in /sys/bus/pci/devices/*; do
	b=$(basename $d)
	v=$(cat $d/vendor 2>/dev/null)
	p=$(cat $d/device 2>/dev/null)
	c=$(cat $d/class 2>/dev/null)
	r=$(cat $d/revision 2>/dev/null)
	l=$(readlink $d)
	echo "$b vendor=$v device=$p class=$c rev=$r $l"
	grep -E '^[0-9a-f]+ ' $d/resource 2>/dev/null | sed 's/^/    resource /'
	if [ -f $d/current_link_speed ]; then
		echo "    link $(cat $d/current_link_speed) x$(cat $d/current_link_width)"
	fi
	if [ -f $d/max_link_speed ]; then
		echo "    max link $(cat $d/max_link_speed) x$(cat $d/max_link_width)"
	fi
done
echo "== dmesg pci"
dmesg | grep -iE 'pcie|cnss|qca' | tail -30
