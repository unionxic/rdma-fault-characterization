#!/bin/bash
# Acceptance matrix for GIN GDAKI recovery, through run_gin_fault.sh. Every run of repro/gin_fault prints one ACCEPT verdict
# line from its own checks; S6 is judged here from the existing lines. Prints scenario x CQ type x counter -> PASS count / runs.
# usage: accept.sh <label> [reps=2] [scenario...]   env: CQS="0 1 2" CTRS="0 1" XTRA="<more mpirun args>" BIN=<test program>
#        accept.sh --table <accept folder>...           (one table over several batches)
#   S1f S1s  the sender's QPs go to ERR mid-run (qperr): flush after every put / stream of puts with one flush at the end
#   S2f S2s  the same on the receiver's QPs (NCCL_IB_TIMEOUT=14, so the sender's retries end in about 4 s)
#   S3       one bad put, then 589 more before the one flush    S3b  the bad put is the first of a burst of 8 before a flush
#   S4       the sender's QPs go to ERR twice in one stream (700 ms apart)
#   S5 S5s   no fault (flush per put / stream)                  S6   rank 1 dies (4 ranks; death WARN, then the run after the shrink)
#   suffix -4: 4 ranks, rain:2 sunny:2.  Recovery promises PASS everywhere; the flush limit is about 10 s, so slow recovery still passes.
# verdicts.txt: one line per run: key, log, fault_ms (first injection or bad put, ms after kernel start), faults_in_run (injections
# before the kernel ended), first_fail_ms, longest_call_ms (flush/wait), then the ACCEPT line. A PASS with an injection after the
# kernel ended tested nothing and becomes INVALID.
R=$HOME/rdma-recovery
if [ "$1" = --table ]; then shift; else
L=$1; REPS=${2:-2}; shift; shift
set -- ${@:-S5 S5s S1f S1s S2f S2s S3 S3b S4 S5-4 S1s-4 S2s-4 S3-4 S6}
ACC=$R/runs/accept-$L-$(date +%Y%m%d-%H%M%S); mkdir -p $ACC
for s in "$@"; do
  np=2 H=rain,sunny X= sn=30000 gap=100000 tmo=90  # gap: the stream lasts about 1.7 s, the injection comes at about 0.95 s
  case $s in *-4) np=4 H=rain:2,sunny:2 X="--map-by node -x NCCL_MULTI_RANK_GPU_ENABLE=1" sn=12000 gap=300000;; esac
  case ${s%-4} in
    S1f) a=inject X="$X -x QPERR_RANK=0";;
    S1s) a=stream X="$X -x QPERR_RANK=0";;
    S2f) a=inject X="$X -x QPERR_RANK=1 -x NCCL_IB_TIMEOUT=14";;
    S2s) a=stream X="$X -x QPERR_RANK=1 -x NCCL_IB_TIMEOUT=14";;
    S3) a=timed X="$X -x N=600 -x CHUNK=1024 -x FLUSH_EVERY=0";;
    S3b) a=timed X="$X -x BURST=8 -x CHUNK=4096";;
    S4) a=stream X="$X -x QPERR_RANK=0 -x QPERR_AGAIN_MS=700" gap=200000;;
    S5) a=control X="$X -x TIMED=1 -x TMO_CYCLES=20000000000";;
    S5s) a=stream;;
    S6) a=control np=4 H=rain:2,sunny:2 tmo=40 X="--enable-recovery --map-by node -x NCCL_MULTI_RANK_GPU_ENABLE=1 -x KILL_RANK=1 -x KILL_AFTER_MS=600 -x STALL_S=5 -x TIMED=1 -x TMO_CYCLES=20000000000";;
    *) echo "unknown scenario $s"; exit 1;;
  esac
  for cq in ${CQS:-0 1 2}; do for c in ${CTRS:-0 1}; do
    RUNS=$ACC NP=$np HOSTS=$H TMO=$tmo SN=$sn GAP=$gap TC=20000000000 EXTRA="$X -x ACCEPT=$s -x NCCL_GIN_GDAKI_CQ_TYPE=$cq -x COUNTER=$c $XTRA" \
      bash $R/run_gin_fault.sh $s.cq$cq.c$c $REPS $a >> $ACC/runner.txt 2>&1
  done; done
done
for f in $ACC/ginfault-*/*.log; do
  k=$(basename $(dirname $f)); k=${k#ginfault-}; k=${k%-*-*}
  # S6: death declared once, the flushes after it fail, no stall, and the run after the shrink passes
  awk -v key="$k $(basename $f .log)" -v s6=$([ ${k%%.*} = S6 ] && echo 1) '
    /QPERR rank=[0-9]+ round=/ {w[++nr] = substr($5, 9)} /is dead/ {d++} /^STALL/ {st = 1} /^ACCEPT/ {acc = $0}
    /^SUMMARY/ && !ns++ {match($0, /non_success_flush=[0-9]+/); nf = substr($0, RSTART + 18, RLENGTH - 18) + 0; st += /stalled=1/}
    /^LAT/ && !nl++ {for (i = 2; i <= NF; i++) {split($i, kv, "="); L[kv[1]] = kv[2]}}
    END {if (s6) acc = sprintf("ACCEPT scenario=S6 expect=death_declared_error_returned dead_warns=%d failed_calls=%d stalled=%d after_shrink=%s => %s",
           d, nf, st > 0, acc ? substr(acc, length(acc) - 3) : "none", d == 1 && nf > 0 && !st && acc ~ /PASS$/ ? "PASS" : "FAIL")
         if (!acc) acc = "ACCEPT no verdict line => FAIL"
         for (i = 1; i <= nr; i++) in_run += w[i] - L["t0_wall_ms"] < L["end_ms"]
         if (in_run < nr) sub(/=> PASS$/, "=> INVALID", acc)
         printf "%s fault_ms=%.1f faults_in_run=%d/%d first_fail_ms=%s longest_call_ms=%s %s\n", key,
           nr ? w[1] - L["t0_wall_ms"] : L["bad_start_ms"], in_run, nr, L["first_fail_ms"], L["longest_call_ms"], acc}' $f
done > $ACC/verdicts.txt
set -- $ACC
fi
cat ${@/%//verdicts.txt} | awk '{split($1, p, "."); c = p[2] "." p[3]; if (!(p[1] in r)) o[++n] = p[1]; r[p[1]]; if (!(c in cs)) co[++m] = c; cs[c]; t[p[1], c]++; ok[p[1], c] += $NF == "PASS"}
  END {printf "%-8s", "PASS/n"; for (j = 1; j <= m; j++) printf " %7s", co[j]; print "";
       for (i = 1; i <= n; i++) {printf "%-8s", o[i]; for (j = 1; j <= m; j++) printf " %7s", (o[i], co[j]) in t ? ok[o[i], co[j]] "/" t[o[i], co[j]] : "-"; print ""}}'
echo "verdict lines: ${@/%//verdicts.txt}"
