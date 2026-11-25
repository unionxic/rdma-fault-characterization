#!/bin/bash
# xnode.sh <case> [n] [dir] [timeout]: runs one case of repro/xnode.c n times between rain and sunny (one process each) and
# prints one summary line per run: every field of the replies, prefixed by the step. dir rs: Q on rain, P on sunny; sr: the
# reverse. Builds xnode on both hosts first (sunny gets this host's source). Logs: runs/xnode-<case>-<dir>-<time>/.
# Both sides stream at once: Q (host of dir's first letter) to P is the forward stream, P to Q the reverse one, which P posts
# when the first forward request has landed (for reads, the driver posts it first), so a rebuilt side's responder half
# has the peer's requests in flight too. Cases <op>-<fault><variants>. op w: 64 B writes x8192 (the largest send queue the
# NIC accepts); m: 64 KiB writes x512; a: fetch-adds x8192; x: 64 B write + fetch-add x4096 (put + signal); r: 64 KiB reads
# x1024. fault a: Q's QP to ERR once k of its WRs completed (reads: once its read k landed); b: P's QP to ERR once forward
# message (or count) k landed; c: P reads its record and RESETs once k landed. Recovery rounds (at most 3; 8 for m, where a round needs no timeout): every side whose
# QP is not RTS is rebuilt alone from its own record (sq_psn = acked+1, rq_psn = rcv), a rebuilt side re-posts from its first
# WR without a successful CQE, both wait; a healthy side does nothing (its NIC retransmits). Variants: R P is moved to ERR and
# rebuilt too (fault a); H P rebuilds itself at once in the fault (fault b, Q stays healthy); M every rebuild (both sides, all
# rounds) restarts at the first PSN of the first incomplete WR instead of acked+1; S Q's first rebuild restarts S at that PSN + j, 1 <= j <= min(15, packets P placed from there),
# as if acked+1 fell inside the message; X as M, and P's first rebuild restarts at the first PSN of the message holding its
# rcv_psn (needs Q's message boundaries); W the PSNs start near 2^24 and wrap inside the burst. No variant: both records are
# read again 1 s later. psn_a, psn_a0, psn_both: synd.c's loopback cases between the hosts.
# timeout: QP ack timeout, default 14 (a side retrying towards a QP that is down or drops it has to give up within seconds;
# NCCL GIN uses 20, about 56 s here). k: Q's in 10-80% of the burst, P's in 5-55% (2-45% for 64 B writes: P's modify takes
# ~0.25 ms, ~4000 such writes).
R=$HOME/rdma-recovery; C=$1; N=${2:-30}; DIR=${3:-rs}; M24=16777215
S=${TMPDIR:-/tmp}/xnode-fifo-$$
case $C in
  psn_a|psn_a0|psn_both) OP=w SZ=16 NW=16 F=- ;;
  [wmaxr]-[abc]*) OP=${C%%-*}; F=${C:2:1}; V=${C:3}
    case $OP in w) SZ=64 NW=8192 NM=8192 RK=2;; m) SZ=65536 NW=512 NM=512;; a) SZ=8 NW=8192 NM=8192;; x) SZ=64 NW=8192 NM=4096;; r) SZ=65536 NW=1024 NM=1024;; esac ;;
  *) echo "unknown case $C"; exit 1 ;;
esac
XOP=${OP/m/w}; TMO=${4:-$([[ $F == - && $C != psn_a0 ]] && echo 20 || echo 14)}
[ $DIR = rs ] && RQ=rain RP=sunny || RQ=sunny RP=rain
OUT=$R/runs/xnode-$C-$DIR-$(date +%Y%m%d-%H%M%S); mkdir -p $OUT $S
gcc -O2 -o $R/repro/xnode $R/repro/xnode.c -libverbs -lmlx5 2>/dev/null && scp -q $R/repro/xnode.c sunny:rdma-recovery/repro/ &&
  ssh sunny 'cd rdma-recovery/repro && gcc -O2 -o xnode xnode.c -libverbs -lmlx5 2>/dev/null' || { echo "build failed" >&2; exit 1; }
cleanup() { exec 3>&- 5>&- 2>/dev/null; kill $(jobs -p) 2>/dev/null; pkill -x xnode; ssh sunny 'pkill -x xnode'; rm -rf $S; }
trap cleanup EXIT

X() { [ $1 = rain ] && echo "$R/repro/xnode mlx5_1 4 $NW $SZ $TMO 7" || echo "ssh -T sunny exec rdma-recovery/repro/xnode mlx5_0 3 $NW $SZ $TMO 7"; }
v() { [[ " $2" =~ \ $1=([^ ]*) ]] && echo ${BASH_REMATCH[1]}; }  # first value of key $1 in line $2
peer() { echo $(v qpn "$1") $(v gid "$1") $(v base "$1") $(v rkey "$1"); }
q() { echo "$*" >&3; L=; read -t 150 -u 4 L; echo "Q $* > $L" >> $LOG; }  # a command to the requester, its reply in L
p() { echo "$*" >&5; L=; read -t 150 -u 6 L; echo "P $* > $L" >> $LOG; }  # to the responder
tag() { local t=$1 x; shift; for x in $*; do [[ $x == *=* ]] && printf ' %s.%s' $t $x; done; }
rnd() { echo $(( $1 * $2 / 100 + RANDOM % ($1 * ($3 - $2) / 100) )); }  # k in [$2%, $3%) of $1
start() {
  rm -f $S/*; mkfifo $S/qi $S/qo $S/pi $S/po
  $(X $RQ) <$S/qi >$S/qo 2>>$LOG.err & $(X $RP) <$S/pi >$S/po 2>>$LOG.err &
  exec 3>$S/qi 4<$S/qo 5>$S/pi 6<$S/po
  read -t 30 -u 4 IQ; read -t 30 -u 6 IP; echo "Q $IQ" >> $LOG; echo "P $IP" >> $LOG
  [[ $IQ == info* && $IP == info* ]]
}
stop() { echo quit >&3; echo quit >&5; exec 3>&- 4<&- 5>&- 6<&-; wait; }

done_of() { [ "$(v pend "$1")" = 0 ] && [ "$(v ok "$1")" = $NW ]; }  # every WR completed successfully
run_fault() {
  PK=$(( (SZ + $(v mtu "$IQ") - 1) / $(v mtu "$IQ") )); J=0; BASE=$(( (RANDOM << 15 | RANDOM) & M24 ))
  [[ $V == *W* ]] && BASE=$(( (M24 - RANDOM % (NW * PK / 2)) & M24 ))
  q conn $(peer "$IP") $BASE $BASE; p conn $(peer "$IQ") $BASE $BASE; q cnt; p cnt
  [ $OP != r ] && p watch 1 p $XOP $NW
  if [ $F = a ]; then K=$(rnd $NW 10 80)
    if [ $OP = r ]; then p post r 0 $NW; q watch $K e; q post r 0 $NW; else q post $XOP 0 $NW $K; fi; PO=$L
    q wait $NW 5000; W1=$L; p wait $NW 0; PW1=$L
  else K=$(rnd $NM ${RK:-5} $((${RK:-5} == 2 ? 45 : 55))); A=e; [ $F = c ] && A=r; [[ $V == *H* ]] && A=b
    p watch $K $A; [ $OP = r ] && p post r 0 $NW; q post $XOP 0 $NW; PO=$L
    q wait $NW 120000; W1=$L; p wait $NW 5000; PW1=$L
  fi
  FM=p RM=q; [ $OP = r ] && FM=q RM=p  # who holds the forward stream's data (reads land at the reader)
  q q; Q1=$L; p q; P1=$L; $FM mem $XOP $NW; M1=$L; $RM mem $XOP $NW; QM1=$L; Q1b=; P1b=
  [ -z "$V" ] && { sleep 1; q q; Q1b=$L; p q; P1b=$L; }
  RQR=own SQR=own SQL=own; [[ $V == *[MX]* ]] && SQR=msg SQL=msg  # SQL: the sq rule of every later rebuild
  [[ $V == *X* ]] && RQR=$(( (BASE + (($(v rcv "$P1") - BASE) & M24) / PK * PK) & M24 ))
  if [[ $V == *S* ]]; then fpsn=$(v fpsn "$W1"); d=$(( ($(v exec "$M1") - fpsn) & M24 )); [ $d -gt 8388608 ] && d=0; [ $d -gt $((PK - 1)) ] && d=$((PK - 1))
    SQR=msg; [ $d -ge 1 ] && J=$(( 1 + RANDOM % d )) && SQR=$(( (fpsn + J) & M24 )); fi
  NRMAX=3; [ $OP = m ] && NRMAX=8
  WQ=$W1 WP=$PW1 RT= NR=$NRMAX
  for r in $(seq 0 $((NRMAX - 1))); do
    q q; QS=$(v st "$L"); p q; PS=$(v st "$L")
    done_of "$WQ" && done_of "$WP" && [ "$QS$PS" = 33 ] && { NR=$r; break; }
    [ $r = 0 ] && [[ $V == *R* ]] && [ "$PS" = 3 ] && { p err; PS=6; }
    RB= PB= QB=
    if [ "$PS" != 3 ]; then [ "$PS" = 6 ] && { p wait $NW 5000; WP=$L; }; p rebuild $SQL $([ $r = 0 ] && echo $RQR || echo own); PB=$L RB=p; fi
    if [ "$QS" != 3 ]; then [ "$QS" = 6 ] && { q wait $NW 5000; WQ=$L; }; q rebuild $([ $r = 0 ] && echo $SQR || echo $SQL) own; QB=$L RB+=q; fi
    { [[ $RB == *p* ]] || { [ "$(v pend "$WP")" = 0 ] && [ "$(v ok "$WP")" -lt $NW ]; }; } && p resend $XOP $NW
    { [[ $RB == *q* ]] || { [ "$(v pend "$WQ")" = 0 ] && [ "$(v ok "$WQ")" -lt $NW ]; }; } && q resend $XOP $NW
    q wait $NW 120000; WQ=$L; p wait $NW 120000; WP=$L
    RT+="$(tag PB$r $PB)$(tag QB$r $QB)$(tag WQ$r $WQ)$(tag WP$r $WP)"
  done
  $FM mem $XOP $NW; M2=$L; $RM mem $XOP $NW; QM2=$L; q res $XOP $NW; R2=$L; p res $XOP $NW; PR2=$L
  q q; Q2=$L; p q; P2=$L; q cnt; QC=$L; p cnt; PC=$L
  echo "case=$C dir=$DIR run=$i base=$BASE k=$K shift=$J tmo=$TMO rounds=$NR$(tag PO $PO)$(tag W1 $W1)$(tag PW1 $PW1)$(tag Q1 $Q1)$(tag P1 $P1)$(tag M1 $M1)$(tag QM1 $QM1)$(tag Q1b $Q1b)$(tag P1b $P1b)$RT$(tag WQF $WQ)$(tag WPF $WP)$(tag M2 $M2)$(tag QM2 $QM2)$(tag R2 $R2)$(tag PR2 $PR2)$(tag Q2 $Q2)$(tag P2 $P2)$(tag QC $QC)$(tag PC $PC)"
}

# synd.c's psn_a (A to ERR idle, rebuilt alone from its record), psn_a0 (rebuilt at PSN 0), psn_both (a bad rkey fails both,
# each rebuilt from its own record): 8 writes A->B and 4 B->A, the fault, then 8 more each way. A = requester host.
run_psn() {
  BASE=0; K=0; J=0
  q conn $(peer "$IP") 0 0; p conn $(peer "$IQ") 0 0; q cnt; p cnt
  q post w 0 8; p post w 0 4; q wait 8 10000; W0=$L; p wait 4 10000; PW0=$L
  if [ $C = psn_both ]; then q post b 8 1; q wait 9 10000; else q err; q wait 8 10000; fi; W1=$L
  q q; Q1=$L; p q; P1=$L
  q rebuild $([ $C = psn_a0 ] && echo init init || echo own own); QB=$L; PB=
  [ $C = psn_both ] && { p rebuild own own; PB=$L; }
  q post w 8 8; p post w 4 8; q wait 16 120000; W2=$L; p wait 12 120000; PW2=$L
  q mem w 12; QM=$L; p mem w 16; M2=$L; q q; Q2=$L; p q; P2=$L; q cnt; QC=$L; p cnt; PC=$L
  echo "case=$C dir=$DIR run=$i base=0 k=0 shift=0 tmo=$TMO$(tag W0 $W0)$(tag PW0 $PW0)$(tag W1 $W1)$(tag Q1 $Q1)$(tag P1 $P1)$(tag QB $QB)$(tag PB $PB)$(tag W2 $W2)$(tag PW2 $PW2)$(tag QM $QM)$(tag M2 $M2)$(tag Q2 $Q2)$(tag P2 $P2)$(tag QC $QC)$(tag PC $PC)"
}

for i in $(seq $N); do
  LOG=$OUT/run$i.log
  if ! start; then echo "case=$C dir=$DIR run=$i start_failed" | tee -a $OUT/summary.txt; stop; continue; fi
  if [ $F = - ]; then run_psn; else run_fault; fi | tee -a $OUT/summary.txt
  stop
done
echo "# $OUT"
