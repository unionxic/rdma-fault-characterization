#!/usr/bin/env bash
# Read-only snapshot of rain mlx5_1 (0000:17:00.1) firmware-command statistics from debugfs, and the
# mlx5 kernel messages, so the runs can be tied to the state of the command interface (one command
# slot has been leaked since 06:45:02 by a 2ERR_QP that never completed).
D=/sys/kernel/debug/mlx5/0000:17:00.1/commands
echo "# $(date '+%F %T') $1"
for c in 2ERR_QP 2RST_QP RST2INIT_QP INIT2RTR_QP RTR2RTS_QP QUERY_QP; do
  printf "%s n=%s average_ns=%s failed=%s failed_mbox_status=%s last_failed_errno=%s\n" "$c" \
    "$(sudo -n cat $D/$c/n)" "$(sudo -n cat $D/$c/average)" "$(sudo -n cat $D/$c/failed)" \
    "$(sudo -n cat $D/$c/failed_mbox_status)" "$(sudo -n cat $D/$c/last_failed_errno)"
done
echo "dmesg mlx5 (not 'local protection error'), last 5:"
sudo -n dmesg -T | grep -i mlx5 | grep -v "local protection error" | tail -5
