# Deviations and clarifications after pre-registration

`PREDICTIONS.md` and `predictions.csv` are fixed by tag `prereg/propagation-v1`. Nothing below
changes a prediction or an acceptance rule. The list records how the campaign implements them,
and every choice made after the tag.

## 2026-10-06, before the campaign

1. **Smoke runs are excluded from scoring.** Two runs checked the instrumentation on the cluster
   before the campaign (`results/20261006_smoke/`):
   - the CPU stack, one trial per fault, 14:03;
   - every GPU and net stack, one trial per cell, from 14:05.
   They are kept as a record, but are not scored. Only the campaign folder is scored.
2. **F4 on the CPU stack is a real SIGKILL.** The responder raises SIGKILL on GO (fault
   `retry_proc_sigkill`). The requester keeps the old proc-kill flow, which waits 300 ms
   before its write. The kernel has then almost always torn the responder down, so the
   0x88 teardown race (`fingerprint_teardown/`, 111/270) is unlikely to appear.
3. **When the responder's state is read (EV1, EV2).** The requester waits 10 ms after detecting
   the fault, then asks the responder for its QP state and its async events since GO. Recovery
   starts after that.
4. **EV1d for F4.** The responder is dead, so its events cannot be observed. That cell is
   reported as "not observable", not as a hit.
5. **The net F0 control is `T0s`** (recovery flag on, no fault). There is no separate stock F0
   run.
6. **GIN teardown bound.** The abort bound is 30 s (`GIN_ABORT_WATCHDOG_S=30`), and the driver
   watchdog is 120 s, so the abort bound is the one that fires.
7. **GQ uses `CLASSIFY=1` with the default CQ type.**
8. **The ND cells run 10 trials each**, as `PREDICTIONS.md` says for new cells. A runner typo
   (5) was fixed before the campaign.
9. **Which observable tests EV4.** evrec sees only port events. For the DEVX stacks, EV4 is
   therefore scored on the libraries' own logs (no async error line), together with evrec's
   port events.
