#!/usr/bin/env python3
"""gen_queues.py - write the N30 campaign queues (one trial per line, interleaved by round so that a
partial run still gives balanced cells and slow drift does not align with one cell).

  q4.q   GIN GDAKI + Q4 classifier (bundle gin_q4): {ring,collapsed} x {F1,F2,F3,F4} x
         {timeout,blocking} x 15 rounds (N=30 per CQ x fault), stock control ring/c0/F1/blocking x 10,
         positive control for the doorbell indicators (CPU proxy forced) x 2
  rec.q  GDAKI recovery v2 (gin_recovery_gpudb): F1, F3, D0, F2, F4 x {timeout,blocking} x 15;
         F1x5, F3x5, flag-off F1/F3 x {timeout,blocking} x 5; v1 bundle with the CPU proxy forced
         (NCCL_GIN_GDAKI_NIC_HANDLER=1): F1, F3 x {timeout,blocking} x 5
  nv.q   NVSHMEM IBGDA FT: classify F1, F2b, F3, F4 x {timeout,blocking} x 15; recover F1, F3 x 15;
         x5 F1, F3 x 5; decline F2b, F4 (recovery on) x 5
"""
import os

A = '/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_n30'
G = '/home/unionxic/rdma-error/harness/gpu-initiated'
Q4 = G + '/gin_q4/results/20260925_n30'
REC = G + '/gin_recovery/results/20260925_n30'
NV = G + '/nvshmem_ft/results/20260925_n30'
W = ('timeout', 'blocking')

q4 = []
for r in range(1, 16):
    for cq in ('ring', 'collapsed'):
        for f in ('F1', 'F2', 'F3', 'F4'):
            for w in W:
                q4.append(f'q4-{cq}-c1-{f}-{w}-t{r} q4_one.sh {cq} 1 {f} {w} {r} {Q4}/main/q4.csv')
    if r <= 10:
        q4.append(f'q4-ring-c0-F1-blocking-t{r} q4_one.sh ring 0 F1 blocking {r} {Q4}/stock/q4.csv')
    if r in (1, 8):
        k = 1 if r == 1 else 2
        q4.append(f'q4-posctl-ring-c1-F1-timeout-px{k} q4_one.sh ring 1 F1 timeout px{k} {Q4}/posctl/q4.csv '
                  f'NCCL_GIN_GDAKI_NIC_HANDLER=1')

rec = []
L2 = REC + '/v2/logs'
L1 = REC + '/v1cpu/logs'
for r in range(1, 16):
    for w in W:
        rec.append(f'rec-v2-F1-{w}-t{r} rec_one.sh v2 F1 {w} t{r} 120 {L2} REC=1 INJECT=600 WATCHDOG_S=60')
        rec.append(f'rec-v2-F3-{w}-t{r} rec_one.sh v2 F3 {w} t{r} 120 {L2} REC=1 INJECT=600 WATCHDOG_S=60')
        rec.append(f'rec-v2-D0-{w}-t{r} rec_one.sh v2 D0 {w} t{r} 120 {L2} REC=1 WATCHDOG_S=60')
        rec.append(f'rec-v2-F2-{w}-t{r} rec_one.sh v2 F2 {w} t{r} 120 {L2} REC=1 WATCHDOG_S=60')
        rec.append(f'rec-v2-F4-{w}-t{r} rec_one.sh v2 F4 {w} t{r} 400 {L2} REC=1 GAP_MS=10 KILL_DELAY_MS=2500 WATCHDOG_S=60')
        if r <= 5:
            rec.append(f'rec-v2-F1x5-{w}-m{r} rec_one.sh v2 F1 {w} m{r} 160 {L2} REC=1 INJECT=300,150,-1,200,100 WATCHDOG_S=70')
            rec.append(f'rec-v2-F3x5-{w}-m{r} rec_one.sh v2 F3 {w} m{r} 200 {L2} REC=1 INJECT=600,300,-1,300,300 WATCHDOG_S=100 GIN_POST_POLL_S=5')
            rec.append(f'rec-v2-off-F1-{w}-o{r} rec_one.sh v2 F1 {w} o{r} 120 {L2} REC=0 INJECT=600 WATCHDOG_S=70')
            rec.append(f'rec-v2-off-F3-{w}-o{r} rec_one.sh v2 F3 {w} o{r} 120 {L2} REC=0 INJECT=600 WATCHDOG_S=70')
            rec.append(f'rec-v1cpu-F1-{w}-t{r} rec_one.sh v1 F1 {w} t{r} 120 {L1} REC=1 INJECT=600 WATCHDOG_S=60 EXTRA_ENV=NCCL_GIN_GDAKI_NIC_HANDLER=1')
            rec.append(f'rec-v1cpu-F3-{w}-t{r} rec_one.sh v1 F3 {w} t{r} 120 {L1} REC=1 INJECT=600 WATCHDOG_S=60 EXTRA_ENV=NCCL_GIN_GDAKI_NIC_HANDLER=1')

nv = []
for r in range(1, 16):
    for w in W:
        for f in ('F1', 'F2b', 'F3', 'F4'):
            nv.append(f'nv-classify-{f}-{w}-t{r} nv_one.sh {f} {w} {r} {NV}/classify')
        for f in ('F1', 'F3'):
            nv.append(f'nv-recover-{f}-{w}-t{r} nv_one.sh {f} {w} {r} {NV}/recover RECOVER=1')
        if r <= 5:
            for f in ('F1', 'F3'):
                nv.append(f'nv-multi-{f}-{w}-t{r} nv_one.sh {f} {w} {r} {NV}/multi RECOVER=1 SHOTS=,20,20,-1,20 TAG=x5')
            for f in ('F2b', 'F4'):
                nv.append(f'nv-decline-{f}-{w}-t{r} nv_one.sh {f} {w} {r} {NV}/decline RECOVER=1')

for name, lines in (('q4.q', q4), ('rec.q', rec), ('nv.q', nv)):
    with open(os.path.join(A, 'specs', name), 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    print(name, len(lines))
