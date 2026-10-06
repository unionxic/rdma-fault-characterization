# History: builds before the final one, the review, the flag-off bisect

Appended to `summary_t1.md` by `tables_t1.sh`. `TRANSPARENT_T1.md` reports the final build only; this
part keeps the earlier sets, the changes between builds and the per-variant tables.

## Builds and sets

| sets | date (KST) | driver | transport | host lib | build |
|---|---|---|---|---|---|
| smoke1, mainA | 09-30 22:45–22:55 | `ef3e996a` | `dc5813bd` | `f8158c55` | b1: first build after the internal review |
| mainB, neg | 22:58–23:16 | `ef3e996a` | `446e82f6` | `f8158c55` | b2: fault hook only (the in-commit shot fires before the re-post doorbell; in b1 it fired after it and hit the re-post 0/10) |
| neg2, f2a, lat | 23:18–23:26 | `83402302` | `c28f555e` | `f8158c55` | b3: `Uexec` added to the RECOVERED line; driver gets F2A `--bad-at` |
| flap_v22 | 23:26–23:33 | `d90585c8` | `6913dea6` | `54a9d23a` | v2.2 (`~/gi-bundle/nvshmem_ft2` libraries) |
| flap_t1_outlined, reg_outlined, lat_outlined | 23:48–10-01 00:19 | `5f5c9bc9` | `c28f555e` | `c9c6041f` | every T1 device path out of line (reverted: +1.5 µs with T1 on, flag-off cost unchanged) |
| reg_final, flap_t1_final, flap_nogid, lat_final | 10-01 00:38–01:13 | `aabbcf80` | `c28f555e` | `d8883a20` | b3's source, rebuilt: the build the external review looked at |
| bisect, fetch | 10-01 08:12–08:29 | `3b8bc926` (+`--fetch`) | `c28f555e` | `d8883a20` | same libraries; variants varA/varP/varW and mixA/mixB (below) |
| reg_fixed, review, flap_fixed, fetch_fixed, flap_cut25, lat_fixed | 08:48–09:58 | `1489d29a` (+`--fill-sms`) | `c69d6cc4` | `d4692937` | the review fixes, with the wait and `submit_ready` hooks moved after the hot loads (reverted: flag-off cost +0.93 µs instead of +0.5) |
| review2 | 10:17–10:24 | `f066856c` | `c69d6cc4` | `d4692937` | same libraries; the SM filler polls device memory |
| reg_final2, lat_final2, flap_final2 | 10:36–11:11 | `f40cf527` | `c69d6cc4` | `0dcfb0e1` | **final**: the review fixes, hooks at their reviewed positions, `NVSHMEMI_IBGDA_T1_DEVICE` knob |
| review3, review4 | 11:25–12:05 | `7a166d01` (exact-fit filler) | `c69d6cc4` | `0dcfb0e1` | final libraries |
| dci_diag, dci_diag2 | 12:16–14:20 | `7a166d01` | `3cb50f80` | – | final source plus timing logs in the helper (side bundle `diag`, not in the diff) |

The device source of b1, b2, b3 and the reviewed build is the same (builds 8–10 recompiled only
`ibgda.cpp`). The transport builds bit-identically (`c69d6cc4` from `reg_fixed` on); the host library
and the driver do not (two builds of one tree gave host libraries `cb5b120f` and `d8883a20`). The
v2.2 latency baseline driver `nvt1v22_drv` is `nvshmem_t1.cu` built against the v2.2 install:
`d90585c8` (before the `--bad-at` knob) ran in `lat` and `flap_v22`, `f1d4d304` in the later sets.

## The external review and what it changed

| # | finding | fix in the final build | cell |
|---|---|---|---|
| 1 (major) | the DCI reset ran `cudaMemsetAsync` (a kernel) under `rc_endpoint_lock` after the commit point; a non-quiescent DCI declined the RC round | DCIs are reset before the commit point with host copies only, never fatally; a non-quiescent one is retried from the idle scan | `dci_fill` (review, review2, review3): 0/24 recovered, 24/24 declined at the hold bound, see below |
| 2 (minor) | `off` was published after the re-post doorbell | `off` and `xbb` are published before the doorbell, the epoch after | in-commit shot 5/5 (reg_final2) |
| 3 (minor) | `recv() == 0` after ECONNRESET / ETIMEDOUT was taken as FIN, permanently | a socket lost with an error is closed and re-dialed (listener kept open); only a clean FIN is death; a fault while the path is down declines as "OOB path down" | `sock`, `sock1` (review4): 5/5, 5/5 |
| 4 (minor) | `HOLD_MS` did not cover the pre-commit phase (68 s), `ROUND_MS` (25 s) < `GID_WAIT_MS` (30 s) | floors `ROUND_MS` ≥ 73 s, `HOLD_MS` ≥ 78 s | `flap_cut25`: 3/3 |
| 5 (nit) | exit without `nvshmem_finalize` destroyed the static state under the helper | `atexit` hook stops and joins the helper | not tested |
| 6 (optional) | fetch/READ in [C, U_exec) could be accepted | not done: the fetch's local result is ambiguous | – |

`dci_fill` runs: `review` (8 trials) launched the filler with one CTA more than fits and polled a
host-mapped flag from every thread; `review2` (8) polled device memory, one CTA more than fits;
`review3` (8) polled device memory with exactly the free capacity (191 CTAs of 256 threads next to the
loop kernel's CTA). All 24 declined the same way ("a device wait gave up (hold bound) with no round in
progress", finalize 29.4 ms [max 29.9]). The `dci_diag`/`dci_diag2` sets timed the helper's copies:
a 64-byte D2H took 83.6 s with F1 (2 trials) and 5.6 s with no fault (2 trials), both the kernel's
lifetime. `fill_copy/` holds the standalone copy test (`tests_t1/fill_copy_test.cu`): with 190, 191 or
192 filler CTAs, from the launching thread and from a second thread, every copy completed in 3–13 µs.

## Earlier-build results

Regression on b1–b3 and the reviewed build (`mainA`, `mainB`, `f2a`, `reg_final`, `reg_outlined`,
`reg_fixed`): every cell matched the final build's outcome table (none 30/30, F1 30/30, F1 × 5
10/10 + 10/10, in-flight 40/40 with 22 rounds where the responder had executed the ADD, F3 15/15,
mt 15/15, F2 30/30 declined (REM_INV_REQ), F2A 30/30 declined, F4 10/10 declined; `reg_final`,
`reg_outlined` and `reg_fixed` 70/70 + 15/15 each). `mainA` also holds 15 void F3 trials (96 MiB heap
too small) and `neg` 10 void `remap` trials (400 MiB heap failed BAR1 registration). Flap: `flap_t1_final`,
`flap_t1_outlined`, `flap_fixed` 15/15 each. Fetch (set `fetch`, b3): F1 no gap 8/8 declined, F1
15 ms gap with a fetch every iteration 8/8 declined (the error surfaces on the next post, which
fetches), F3 8/8 declined, no fault 5/5. The per-set tables are above in this file.

## Fault-free latency of the earlier builds (p50 µs, median of 25 reps)

| set | 4 KiB: v2.2 off / T1 off / FT+ring / T1 on | 256 KiB: same |
|---|---|---|
| lat (b3) | 12.544 / 13.088 / 13.472 / 14.304 | 40.288 / 40.864 / 40.960 / 41.952 |
| lat_outlined | 12.384 / 13.120 / 13.664 / 15.840 | 40.256 / 40.832 / 40.960 / 43.072 |
| lat_final (reviewed build) | 12.416 / 13.344 / 13.472 / 14.304 | 40.352 / 40.832 / 40.960 / 41.920 |
| lat_fixed (hooks moved, best run) | 12.480 / 13.408 / 13.664 / 14.400 | 40.352 / 40.960 / 41.152 / 42.048 |
| lat_final2 (final, best run) | 12.384 / 13.056 / 13.440 / 14.240 | 40.256 / 40.768 / 40.960 / 41.760 |

## Flag-off bisect (set `bisect`; FT off everywhere, 5 runs × 5 reps × 2000 ops, interleaved)

| cell | what runs | 4 KiB, per-run p50 (µs) | best | 256 KiB, per-run p50 | best |
|---|---|---|--:|---|--:|
| v22off | v2.2 libraries and driver | 14.08 12.35 12.38 12.45 12.35 | 12.35 | 39.97 39.97 40.13 40.10 40.10 | 39.97 |
| t1off | T1 build (reviewed) | 12.90 12.86 12.90 13.70 12.93 | 12.86 | 40.70 40.70 40.74 40.77 40.70 | 40.70 |
| mixA | T1 driver (T1 device code) + v2.2 host libraries | 13.31 15.42 13.25 13.41 13.34 | 13.25 | 40.93 40.96 40.96 40.96 40.96 | 40.93 |
| mixB | v2.2 driver (v2.2 device code) + T1 host libraries | 14.30 12.48 12.48 12.58 12.58 | 12.48 | 40.22 40.22 40.32 40.38 40.83 | 40.22 |
| varA | every T1 device hook compiled out (`NVSHMEMI_IBGDA_T1_DEVICE=0`) | 12.35 12.35 12.35 12.32 12.45 | 12.32 | 39.97 39.97 40.10 40.13 40.22 | 39.97 |
| varP | post hooks compiled out (reserve, submit, submit_ready); wait hooks kept (=6) | 12.74 12.70 12.74 12.77 12.77 | 12.70 | 40.35 40.35 40.48 40.48 40.48 | 40.35 |
| varW | wait hooks compiled out (quiet, quiet_status, quiet_with_cst); post hooks kept (=5) | 12.96 13.02 13.06 13.09 14.40 | 12.96 | 40.67 40.67 40.77 40.77 40.77 | 40.67 |

Per-run medians: `bisect_runs.txt`; raw rows: `trials_bisect.csv`. With every hook compiled out the T1
source runs at v2.2's latency; the host side costs ≤ 0.13 µs; post hooks alone +0.6, wait hooks alone
+0.35, both +0.5 µs (4 KiB), not additive. Each hook is one `__constant__` flag load and a branch
(the state is `__constant__` memory, so a dedicated `__constant__` flag is what the code already does);
registers and spills of the put, quiet and AMO functions are unchanged (32 registers, none). Placing
the wait and `submit_ready` hooks after the hot loads (`lat_fixed`) made the flag-off cost +0.93 µs.
The remaining explanation, not verified at SASS level: each branch ends a basic block and stops the
compiler from overlapping the global loads around it.
