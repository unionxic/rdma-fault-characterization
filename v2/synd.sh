#!/bin/bash
# synd.sh [reps]: runs every synd case on this host's active port; one log per run under runs/synd-<host>-<time>/, with the kernel log lines added during that run (the ring buffer is full, so they are found by the last line seen before the run).
R=$HOME/rdma-recovery; N=${1:-3}; case $(hostname) in rain) D=mlx5_1 G=4;; sunny) D=mlx5_0 G=3;; esac
gcc -O2 -o $R/repro/synd $R/repro/synd.c -libverbs -lmlx5 2>/dev/null || exit 1
OUT=$R/runs/synd-$(hostname)-$(date +%Y%m%d-%H%M%S); mkdir -p $OUT
for c in ok bad_lkey sge_len loc_perm bad_rkey rem_range rem_perm qp_no_write atomic_align read_req0 read_resp0 recv_small recv_bad_lkey recv_ro no_recv peer_gone peer_err peer_reset local_err flush_after mw_bind mw_range mw_len mw_other_pd atomic_len zero_sge_read imm_bad_rkey imm_recv_bad_lkey sge_inline_bit burst_ok burst_bad burst_peer_err; do
  for i in $(seq $N); do k=$(dmesg 2>/dev/null | tail -1); timeout 30 $R/repro/synd $D $G $c > $OUT/$c-$i.log 2>&1 || echo "case=$c exit=$?" >> $OUT/$c-$i.log
    dmesg 2>/dev/null | awk -v m="$k" 'f; $0==m{f=1}' | sed -E 's/^\[[^]]*\] /  dmesg: /; s/QP [0-9]+/QP N/' >> $OUT/$c-$i.log; done
  cat $OUT/$c-*.log | sort | uniq -c
done; echo $OUT
