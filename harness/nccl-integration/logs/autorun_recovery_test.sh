#!/bin/bash
# 2-node validation of the NCCL_RDMA_FAULT_RECOVERY patch (net_ib_fault_recovery.diff).
# NOT run by the patch author: the 2-node GPU runs are the user's call.
#
#   usage: autorun_recovery_test.sh <outdir> [deploy]
#     deploy : first copy libnccl + nccl_ar2 to the peer ($PEER_DIR) with scp
#
# rank0 = rain (this host, 30.0.0.3, mlx5_1, ens4f1np1)
# rank1 = sunny (30.0.0.4, mlx5_0, enp23s0f0np0), reached with `ssh $PEER`.
#
# Runs (each bounded by the driver's per-iteration timeout AND an outer `timeout`):
#   base      flag OFF on BOTH ranks (genuine stock behaviour), same 1-channel config -> must PASS (rc 0/0)
#   inject    flag ON both, NCCL_RDMA_FAULT_INJECT=$K on rank0 only,
#             1 channel / Ring / Simple / 1 QP                          -> RECOVERED or DECLINED-cleanly
#   symmetric flag ON both, INJECT=$K on BOTH ranks                     -> must not deadlock
#   pipelined flag ON both, default channels/protocols, bigger message,
#             INJECT=$KP on rank0 (lands mid-pipeline)                  -> clean decline or completion, never hang
#   prockill  flag ON both, rank1 killed mid-run                        -> rank0 fails cleanly (RETRY_EXC path)
# Verdicts: RECOVERED  = "[FAULT-RECOVERY] initiator: recovered" and both ranks rc 0, every
#                        iteration bit-exact on every rank (the driver checks the whole rbuf);
#           DECLINED   = a "recovery declined"/"NACK" line, both ranks rc 3 (async NCCL error,
#                        communicator aborted), no MISMATCH, no timeout;
#           FAIL       = any MISMATCH (rc 5), any timeout (rc 4 / 124), or anything else.
set -u
OUT=${1:?usage: $0 <outdir> [deploy]}; mkdir -p "$OUT"
MODE=${2:-}

# ---- paths (adjust) ----------------------------------------------------------
NCCL_LIB=${NCCL_LIB:-$HOME/nccl-fr/nccl/build/lib}   # patched build on rain (libnccl.so.2)
DRV=${DRV:-$HOME/nccl-fr/nccl_ar2}                    # nvcc-built driver on rain
CUDA_LIB=/usr/local/cuda-12.8/lib64
PEER=${PEER:-unionxic@30.0.0.4}
PEER_DIR=${PEER_DIR:-nccl-fr-bundle}                  # on sunny, relative to $HOME: libnccl.so.2 + nccl_ar2
R0_IP=30.0.0.3
K=${K:-40}      # inject on the 40th net send: a multiple of 8, so it is the LAST net send of an
                # all-reduce whether an op has 2, 4 or 8 net sends per rank (1 channel), which is
                # when the peer has exactly one receive posted (see README "choosing k")
KP=${KP:-7}     # pipelined run: deliberately not aligned
ITERS=${ITERS:-60}
COUNT=${COUNT:-65536}          # 256 KB all-reduce
COUNT_P=${COUNT_P:-4194304}    # 16 MB all-reduce for the pipelined run
TMO=${TMO:-60}                 # driver per-iteration timeout (s)
OUTER=${OUTER:-400}            # outer safety net (s)

R0ENV="NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=3 NCCL_SOCKET_IFNAME=ens4f1np1 NCCL_DEBUG=WARN"
R1ENV="NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=3 NCCL_SOCKET_IFNAME=enp23s0f0np0 NCCL_DEBUG=WARN"
# The configuration recovery is designed for (single QP, single NIC, no pipelining across channels).
SINGLE="NCCL_MAX_NCHANNELS=1 NCCL_MIN_NCHANNELS=1 NCCL_ALGO=Ring NCCL_PROTO=Simple NCCL_IB_QPS_PER_CONNECTION=1"
FR="NCCL_RDMA_FAULT_RECOVERY=1 NCCL_RDMA_FAULT_HANDSHAKE_MS=2000"

log(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUT/summary.log"; }
: > "$OUT/summary.log"

if [ "$MODE" = "deploy" ]; then
  ssh "$PEER" "mkdir -p ~/$PEER_DIR" && \
  scp -q "$NCCL_LIB"/libnccl.so.2* "$DRV" "$PEER:$PEER_DIR/" && ssh "$PEER" "cd ~/$PEER_DIR && ln -sf \$(ls libnccl.so.2.* | head -1) libnccl.so.2; ls -l" \
    || { log "deploy failed"; exit 2; }
fi

cleanup(){ pkill -9 -x nccl_ar2 2>/dev/null; ssh "$PEER" 'pkill -9 -x nccl_ar2 2>/dev/null'; sleep 2; }

# run <tag> <extra env rank0> <extra env rank1> <count> <port> <iters> <sleep_ms> <tmo_s> [kill_after_s]
run(){
  local tag=$1 e0=$2 e1=$3 cnt=$4 port=$5 it=$6 slp=$7 tmo=$8 kill=${9:-0}
  cleanup
  ssh "$PEER" "rm -f /tmp/${tag}_r1.log /tmp/${tag}_r1.rc"
  env LD_LIBRARY_PATH=$NCCL_LIB:$CUDA_LIB $R0ENV $e0 \
    timeout $OUTER "$DRV" 0 $R0_IP $port $it $cnt $slp $tmo > "$OUT/${tag}_r0.log" 2>&1 &
  local p0=$!
  sleep 2
  ssh "$PEER" "cd ~/$PEER_DIR && env LD_LIBRARY_PATH=\$PWD:$CUDA_LIB $R1ENV $e1 \
    timeout $OUTER ./nccl_ar2 1 $R0_IP $port $it $cnt $slp $tmo > /tmp/${tag}_r1.log 2>&1; echo \$? > /tmp/${tag}_r1.rc" &
  local p1=$!
  if [ "$kill" != "0" ]; then sleep "$kill"; ssh "$PEER" 'pkill -9 -x nccl_ar2'; log "$tag: killed rank1 after ${kill}s"; fi
  wait $p0; local rc0=$?
  wait $p1
  scp -q "$PEER:/tmp/${tag}_r1.log" "$OUT/${tag}_r1.log" 2>/dev/null
  local rc1; rc1=$(ssh "$PEER" "cat /tmp/${tag}_r1.rc 2>/dev/null" || echo "?")
  echo "$rc0 $rc1" > "$OUT/${tag}.rc"
  verdict "$tag" "$rc0" "$rc1"
}

verdict(){
  local tag=$1 rc0=$2 rc1=$3 v
  local f0="$OUT/${tag}_r0.log" f1="$OUT/${tag}_r1.log"
  local mism; mism=$(cat "$f0" "$f1" 2>/dev/null | grep -c MISMATCH)
  local rec;  rec=$(cat "$f0" "$f1" 2>/dev/null | grep -c "\[FAULT-RECOVERY\] initiator: recovered")
  local decl; decl=$(cat "$f0" "$f1" 2>/dev/null | grep -c -E "recovery declined|responder: NACK|initiator: responder NACK|no ACK/NACK within")
  local inj;  inj=$(cat "$f0" "$f1" 2>/dev/null | grep -c "\[FAULT-INJECT\]")
  local frl;  frl=$(cat "$f0" "$f1" 2>/dev/null | grep -c "\[FAULT-")
  if [ "$mism" != "0" ] || [ "$rc0" = "4" ] || [ "$rc1" = "4" ] || [ "$rc0" = "124" ] || [ "$rc1" = "124" ] || [ "$rc0" = "5" ] || [ "$rc1" = "5" ]; then v=FAIL
  elif [ "$tag" = "base" ]; then { [ "$rc0" = 0 ] && [ "$rc1" = 0 ] && [ "$frl" = 0 ]; } && v=PASS || v=FAIL
  elif [ "$tag" = "prockill" ]; then { [ "$rc0" != 0 ]; } && v=PASS-clean-failure || v=FAIL
  elif [ "$rc0" = 0 ] && [ "$rc1" = 0 ]; then
    if [ "$rec" -gt 0 ]; then v=RECOVERED
    elif [ "$inj" = 0 ]; then v="PASS(no-inject-fired)"
    else v="FAIL(inject fired but neither recovered nor failed)"; fi
  elif [ "$decl" -gt 0 ] && [ "$rc0" = 3 -o "$rc0" = 2 ] && [ "$rc1" = 3 -o "$rc1" = 2 ]; then v=DECLINED-clean
  else v="FAIL(unclassified)"; fi
  log "$tag: rc0=$rc0 rc1=$rc1 ok0=$(grep -c ' ok (' "$f0" 2>/dev/null) ok1=$(grep -c ' ok (' "$f1" 2>/dev/null) mismatch=$mism inject=$inj recovered=$rec declined=$decl -> $v"
}

#   tag       rank0 env                               rank1 env                               count    port  iters   sleep tmo
run base      "$SINGLE"                               "$SINGLE"                               $COUNT   43200 $ITERS  100   $TMO
run inject    "$SINGLE $FR NCCL_RDMA_FAULT_INJECT=$K" "$SINGLE $FR"                           $COUNT   43210 $ITERS  100   $TMO
run symmetric "$SINGLE $FR NCCL_RDMA_FAULT_INJECT=$K" "$SINGLE $FR NCCL_RDMA_FAULT_INJECT=$K" $COUNT   43220 $ITERS  100   $TMO
run pipelined "$FR NCCL_RDMA_FAULT_INJECT=$KP"        "$FR"                                   $COUNT_P 43230 $ITERS  100   $TMO
# proc-kill: long run, rank1 SIGKILLed after 12 s; the survivor's error arrives as RETRY_EXC
# after ~ (4.096us<<NCCL_IB_TIMEOUT) x (NCCL_IB_RETRY_CNT+1) = ~34 s with the defaults.
run prockill  "$SINGLE $FR"                           "$SINGLE $FR"                           $COUNT   43240 400     200   90 12
cleanup
log "ALL DONE (logs in $OUT)"
