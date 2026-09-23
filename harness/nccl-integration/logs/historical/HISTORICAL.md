# Historical logs (superseded builds, do not cite as evidence for the current patch)

These files were produced on 2026-09-17 by builds that no longer exist and whose code
has been replaced:

| File | Produced by | Why it is not evidence for the current patch |
|---|---|---|
| `baseline_rank0.log`, `p2_baseline_rank0.log` | stock-path runs of the earlier builds | Old test driver: it read only `rbuf[0]` on rank 0 and printed "ok" whatever the value, with the same input every iteration. |
| `fault_recovery_OFF_rank0.log`, `fault_recovery_ON_rank0.log` | first patch (classification + *unilateral* QP re-drive) | That code was removed. It re-drove only the local QP, with no PSN handshake and no replay. |
| `evidence_responder.txt`, `phase123_inject_rank0.log`, `phase123_inject_rank1.log` | "phase 1-3" patch (net_ib.cc hash 8f693b8) | That code had verified defects: C1 (acted on the tested request instead of the one `wc->wr_id` named), C2 (a reset discarded other in-flight receives, CTS writes and completions), and M1-M6. Its one successful run happened to hit the only safe case (a single outstanding receive). The driver's check was also insufficient (see above). |
| `control_prockill_rank0.log` | "phase 1-3" patch | That patch's responder failed on a FIN from the peer socket. The current patch does not do this (see README, proc-kill). |

The current patch (`../../net_ib_fault_recovery.diff`) has **not been run** on the
2-node GPU setup yet. `../autorun_recovery_test.sh` is the validation to run.
