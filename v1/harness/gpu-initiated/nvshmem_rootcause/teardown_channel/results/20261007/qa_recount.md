# teardown_channel: independent recount (QA)

Source: `results/20261007/` raw files only (pe0/pe1 logs, .capture, .gdb.txt, .cudagdb.txt, .strace.txt,
.gpuutil, trials.csv). score.py, SCORE.md and trials_scored.csv were not opened. Script:
`recount.py` (this folder), parsed rows in `trials_parsed.json`. Smoke excluded.

Exclusions: none were needed. All 15 killed trials applied the fault (PE 1 log stops at iter 4, kill_at set),
and gdb and cuda-gdb both returned rc 0 in all 15.

| Q | cell | n | observable | hits | misses / not observable | verdict |
|---|---|--:|--:|--:|---|---|
| Q1 | GPU handler stock, kill | 5 | 5 | 5 | none | holds |
| Q1 | CPU proxy fix, kill | 5 | 5 | 5 | none | holds |
| Q2 | GPU handler stock, kill | 5 | 5 | 5 | none | holds |
| Q2 | CPU proxy fix, kill | 5 | 5 | 5 | none | holds |
| Q3 | GPU handler stock, kill | 5 | 5 (cuda-gdb) | 5 | none (lane 0 at +0x1ef0 in 5/5) | holds |
| Q3 | CPU proxy fix, kill | 5 | 5 (cuda-gdb) | 5 | none (+0x1ef0 x4, +0x1f40 x1) | holds |
| Q4 | CPU proxy stock, kill | 5 | 5 | 5 | none | holds |
| Q5 | GPU handler stock, no kill | 5 | 5 | 5 | none | holds |
| Q5 | CPU proxy fix, no kill | 5 | 5 | 5 | none | holds |
| Q5 | CPU proxy stock, no kill | 5 | 5 | 5 | none | holds |
| Q6 | GPU handler stock, kill | 5 | 5 | 5 | none | holds |
| Q6 | CPU proxy fix, kill | 5 | 5 | 5 | none | holds |
| Q6 | CPU proxy stock, kill | 5 | 5 | 5 | none | holds |

Details:
- Q1: all 10 PE 0 logs end with "nvshmem_finalize did not return after 30 s", pe0_rc 5.
- Q2/Q4: main thread (LWP = pid) in all 15: cudaStreamSynchronize < nvshmemi_barrier(int) <
  nvshmemid_hostlib_finalize < nvshmemi_finalize < nvshmem_finalize < end_run < main. No
  bootstrap_uid_barrier or nvshmemi_transport_finalize in any thread.
- Q5 (range over the 5 trials of each cell): PE 0 returns in 24.6-26.2 / 28.1-29.5 / 28.5-29.3 ms,
  PE 1 in 280.0-281.3 / 282.3-295.9 / 282.0-283.6 ms (GPU stock / CPU fix / CPU stock).
- Q6: the only syscalls in all 15 strace files are clock_nanosleep, futex, ioctl, poll, restart_syscall.
  No recv/recvfrom/recvmsg/read/accept. ("resuming interrupted read" in restart_syscall is strace's
  label after attach, not a read; those threads are in nanosleep/poll/futex per gdb.)

Sync-step check (SASS, `barrier_on_stream_kernel_threadgroup<WARP>`, sm_75):
- 0x0010-0x00a0: job_connectivity (c[0x3][0x20]) >= 4 -> CALL with (false, 0x8000=PE_ANY, NULL,
  INT_MAX=QP_ALL) = device quiet, a separate function, not inlined.
- 0x0220-0x6fa0: inlined nvshmemi_sync_algo_threadgroup, switch on k = max(min(size, kval), 2).
  The block 0x12d0-0x2230 is the k=2 case (inner bound j >= 2, temp >>= 1).
- 0x1c20-0x1ed0: from_nbr = my_pe - shift (wrap +size), pe_mapping lookup; expected value =
  sync_counter (c[0x3][0x70]) loaded at 0x1e60; address = psync_pool (c[0x3][0x68]) +
  8*(team psync + (counter%2)*0xd800 + from_nbr), and 0xd800 = NVSHMEMI_SYNC_SIZE.
- 0x1ee0-0x1f70: volatile 64-bit load, signed >= compare, leave when >= = `while (*addr < val);`.
- After: j += 32, phase loop, warpsync, lane 0 sync_counter++, enforce-consistency call, EXIT.
- Live cuda-gdb x/4i matches the dump (same instructions, BRA targets +0x1f80/+0x1ee0) in all 10.
Verdict: sync step's wait for the peer's signal. Confidence high (about 95%).
