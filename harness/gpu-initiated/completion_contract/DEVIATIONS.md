# Deviations and clarifications after pre-registration

`predictions.csv` and sections 2, 3, 7 and 8 of `EXPERIMENT.md` are fixed by tag
`prereg/completion-contract-v1` (2026-10-07 09:12:55 +0900). Nothing below edits them. Items 1 to 3
were written on 2026-10-07 at 14:18, after the first NVSHMEM 3.4.5 smoke run (which failed at
start, item 2) and before the second smoke run's result and before any main run.

1. **"First iteration after the kill" (P1, P2).** The runner sends SIGKILL to PE 1 once PE 0 has
   printed iteration 3. On 3.8.0 the next iteration still returned in about 1 ms in every trial,
   because the kill takes effect only after the ssh round trip; the first iteration that met a
   dead peer was iteration 5 (`../nvshmem_rootcause/cq380/`). `score.py` therefore takes the first
   iteration after iteration 3 that does not return within 100 ms, and requires every earlier
   iteration to have returned within 100 ms. A kill trial with no such iteration had no fault
   during communication and is counted apart (section 8). This is how
   `../nvshmem_rootcause/official380/` read "the first iteration after death".
2. **RC map setting.** `../nvshmem_rootcause/official380/run.sh` sets `NVSHMEM_IBGDA_RC_MAP_BY=none`,
   3.8.0's default. NVSHMEM v3.4.5-0 does not know "none" (only cta, sm, warp, dct). In the first
   smoke run every PE logged `IBGDA_RC_MAP_BY is not valid`, the IBGDA device was not initialized,
   and the first barrier failed with an illegal memory access (3/3, `results/20261007_smoke/nvs/`).
   The runner now takes the value from `RC_MAP_BY` (default still "none"), and `run_cells.sh` sets
   "cta" for the 3.4.5 cells. With one RC per PE and a one-block kernel, every mapping picks the
   same RC `[추론]`.
3. **IB timeout and retry count in 3.4.5.** Section 6 fixes IB timeout 14 and retry 7, and P1 and
   P2 predict a return "after the retries run out (3-5 s)" with "no trial that does not return
   within 30 s". NVSHMEM v3.4.5-0 has no `NVSHMEM_IB_TIMEOUT` or `NVSHMEM_IB_RETRY_CNT`; it writes
   ack timeout 20 and retry 7 into every IBGDA QP (`src/modules/transport/ibgda/ibgda.cpp`, lines
   1453-1455 of the v3.4.5-0 tarball). The 3-5 s window and the 30 s bound were derived from
   timeout 14, so they cannot be met on 3.4.5 whatever the completion behaviour is.
   - On this testbed, timeout 20 with retry 7 runs out after 58.46-58.79 s in fresh processes
     (`../../ack_timeout/README.md`).
   - For the 3.4.5 cells the reproducer's wait bound (`HANG_S`) is 90 s instead of 30 s.
   - `score.py` reports two readings for P1 and P2:
     (a) **as written**: 3-5 s, none beyond 30 s. It is expected to fail on the timeout alone.
     (b) **timeout substituted**: the same rule with the window that timeout 20 gives, 50-70 s,
     and no trial that does not return within the 90 s bound. This window is set here, from the
     ack_timeout measurement, before I had seen the result of any 3.4.5 kill trial.
   - P3 (no kill) is unaffected.
4. **The 3.4.5 CPU proxy cells run on 3.4.5 with one initialization line added.** Written 14:22,
   after the second smoke run and before any main run.
   - In the second smoke run (`results/20261007_smoke/nvs2/`) the GPU handler ran (P2: the first
     iteration after the kill returned after 57583.3 ms, all 40 returned). With `cpu_host_memory`
     both trials (P1, P3) failed at start: PE 1 on sunny logged `Unable to create ah` while
     creating the shared DCT, then `create DCT share err` and `nvshmem setup connections failed`
     (2/2).
   - In v3.4.5-0 that function fills a stack `struct ibv_ah_attr` field by field without zeroing it
     (`ibgda.cpp` lines 2157 and 2184-2185 of the tarball); 3.8.0 zeroes it first. Fields left
     unset hold whatever was on the stack, which differs between handler modes `[추론]`.
   - `patches/v3.4.5-0_dct_ah_attr_init.diff` adds that one `memset`. `build_345_ahinit.sh`
     builds the IBGDA plugin with it into `lib_ahinit` (the rest of `lib_stock` unchanged).
     The CPU proxy's doorbell-record code, the subject of P1, is not touched.
   - P1 and P3 use `lib_ahinit` (variant name `ahinit` in the rows); P2 stays on `lib_stock`.
     The results are reported as "3.4.5 with the DCT initialization fix", not as unmodified 3.4.5.
