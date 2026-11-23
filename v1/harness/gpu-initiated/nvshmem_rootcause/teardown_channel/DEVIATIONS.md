# Deviations and clarifications after pre-registration

`predictions.csv` and sections 2, 3, 7 and 8 of `EXPERIMENT.md` are fixed by tag
`prereg/teardown-channel-v1`. Nothing below changes a prediction or an acceptance rule.

## 2026-10-07

1. **How Q3's "sync step" is judged.** The pre-registration says the GPU kernel should be the barrier
   kernel "in the sync step (waiting for the peer's signal)". The library has no line information, so
   cuda-gdb reports only the kernel and an instruction address.
   - After the smoke trial and before the main run (08:05), `trace_trial.sh` was extended to print
     the instruction at the stopped address with its offset in the kernel (`x/4i $pc`, and lane 1's
     address).
   - The loop range below was read from the machine code after the first main trial's offset had
     been seen (08:07), so the judging rule was set after one result was known. It was written into
     this file at 08:18, when 8 of the 10 Q3 trials had been captured. The independent recount
     confirmed the reading from the source and the machine code on its own (`qa/recount.py`,
     `results/20261007/qa_recount.md`).
   - The offset is mapped onto the kernel's machine code, dumped with
     `cuobjdump -sass -arch sm_75` from `lib_stock/libnvshmem_host.so.3.8.0` (the stock and fix host
     libraries are byte-identical). See `results/20261007/sass_wait_loop.md`.
   - A trial counts as "sync step" when lane 0 stops inside the loop that reloads a 64-bit value from
     the constant-bank array base plus an index and compares it with the expected count. The loop
     spans offsets 0x1ee0 to 0x1f70 of `barrier_on_stream_kernel_threadgroup<WARP>`. Device quiet
     polls completion entries instead, so it would show up as a different loop.
2. **Correction of the pre-registration time.** `PREREG.txt` and the EXPERIMENT.md header say the
   predictions were fixed at 08:10. The commit `a6a447ec` and the tag were made at 2026-10-07
   08:02:59 +0900 (`git log`, `git for-each-ref`). The smoke run took the cluster lock at 08:03:45
   and the main run at 08:05:47, so the order "predictions, then runs" holds. The frozen files are
   left as they are.
