# cq380 independent recount (QA)

Recount of the 25 main-run trials in this folder from the raw files, done 2026-10-07 without reading
`score.py`, `SCORE.md` or `trials_scored.csv`. Script: [qa/recount.py](../../qa/recount.py)
(`python3 qa/recount.py` from the cq380 folder; it prints the per-trial table, the per-CQE table, the
per-cell verdicts and every failed consistency check). Markers: `[측정]` read from the raw files,
`[추론]` inference, `[미확인]` not checked.

## Method

- **Trial set.** Listed every file in this folder by tag and compared with the pre-registered 5 cells x
  5 trials; checked `trials.csv` (25 rows) and each `<tag>.row` against each other and against
  `pe0.log`, and the 25 "done" lines in `run_all.out`.
- **Own scan (kernel path).** Parsed the `CQSCAN cq=...` and `CQSCAN queues=... path=kernel` lines in
  `pe0.log` and matched each queue to its `CQSCAN prep` line by type, QP number and size.
- **cuda-gdb path.** Parsed `<tag>.cudagdb.txt` byte by byte: one block per `CQBEGIN i`/`CQEND i`,
  addresses checked to start at the `prep` line's `cqe=` address and to advance 8 bytes per line,
  1024 x 64 bytes per buffer. Opcode = byte 63 >> 4 (0xf unwritten, 0xd/0xe error), syndrome byte 55,
  vendor byte 54, QP number bytes 57–59, wqe_counter bytes 60–61 big-endian. `cqdump.txt` was only
  compared with this decode, never used for scoring.
- **Scoring.** Per the frozen rules: no-kill controls and the CPU proxy kill case need no error CQE in
  any queue; the CPU proxy kill case also needs at least one written CQE in the RC queue (none written =
  not observable, section 8); the GPU handler kill and fixed-proxy kill cases need at least one error
  CQE in the RC queue. 5/5 per cell (per variant for the controls); any trial outside the prediction
  makes the cell wrong. Reading (a) uses the cuda-gdb decode where the own scan failed (DEVIATIONS item
  3); reading (b) counts a failed own scan as not observable (section 8 literally).

## Result per cell

n = 25 main-run trials, 5 per row. Smoke runs (`../20261007_smoke/`, 10 trial logs) were not read or
scored. "written/error" = written CQEs / error CQEs in that queue, identical in all 5 trials of a row.

| Condition (key) | Predicted | n | Read path | DCI queue | RC queue | PE 0 wait | (a) cuda-gdb substituted | (b) section 8 literal |
|---|---|--:|---|---|---|---|---|---|
| CPU proxy, stock, peer killed (C1) | no error CQE anywhere, RC queue has a success CQE | 5 | own scan failed 5/5, cuda-gdb read 5/5 | 1/0 | 1/0, success (opcode 0x0) | stuck at iteration 5, "has not returned after 30 s" 5/5 | **5/5 as predicted** | **0/5 observable, not decidable** |
| GPU handler, stock, peer killed (C2) | error CQE in the RC queue | 5 | kernel 5/5 | 1/0 | 1/1, syndrome 0x05, vendor 0xf9 | all 40 returned; iteration 5 took 3535.9, 3577.0, 3578.9, 3642.1, 3655.0 ms (t1–t5) | 5/5 as predicted | 5/5 as predicted |
| CPU proxy with the two-line fix, peer killed (C3) | error CQE in the RC queue | 5 | kernel 5/5 | 1/0 | 1/1, syndrome 0x05, vendor 0xf9 | all 40 returned; iteration 5 took 3526.4, 3531.7, 3775.9, 3538.1, 3535.9 ms (t1–t5) | 5/5 as predicted | 5/5 as predicted |
| CPU proxy, stock, no kill (C4) | no error CQE | 5 | kernel 5/5 | 1/0 | 1/0 | all 40 returned, none slower than 2.2 ms | 5/5 as predicted | 5/5 as predicted |
| GPU handler, stock, no kill (C4) | no error CQE | 5 | kernel 5/5 | 1/0 | 1/0 | all 40 returned, none slower than 2.1 ms | 5/5 as predicted | 5/5 as predicted |

`[측정]` All values from `*.pe0.log` (kernel path) or the recount's own decode of `*.cudagdb.txt`. In
every kill trial PE 1 received signals for iterations 0–4 only (`*.pe1.log`); every iteration other
than iteration 5 took 1.0–2.2 ms (range over all 25 trials). Under (a) all five predictions hold;
under (b) the CPU proxy kill prediction cannot be scored and the other four hold.

## cuda-gdb reads (CPU proxy, stock, peer killed; 5 trials)

`[측정]` Each buffer: 65536 bytes (1024 x 64) in 8192 contiguous lines starting at the `prep` address;
exactly one written CQE, in slot 0; the other 1023 slots are all 0xff. Each file ends `cudagdb_rc 0`,
and cuda-gdb stopped PE 0 inside `nvshmemi_transfer_quiet`.

| Trial | DCI queue: QPN, slot, opcode, wqe_counter | RC queue: QPN, slot, opcode, wqe_counter | cudagdb_rc |
|---|---|---|--:|
| t1 | 0x1279f, 0, 0x0 success, 4 | 0x127a0, 0, 0x0 success, 24 | 0 |
| t2 | 0x127bd, 0, 0x0 success, 4 | 0x127be, 0, 0x0 success, 24 | 0 |
| t3 | 0x127db, 0, 0x0 success, 4 | 0x127dc, 0, 0x0 success, 24 | 0 |
| t4 | 0x127f9, 0, 0x0 success, 4 | 0x127fa, 0, 0x0 success, 24 | 0 |
| t5 | 0x12817, 0, 0x0 success, 4 | 0x12818, 0, 0x0 success, 24 | 0 |

## Trial set and cross-file checks

- `[측정]` The 25 tags are exactly the pre-registered set (5 conditions x t1–t5), no duplicates, none
  missing, no extra tags; each has `pe0.log`, `pe1.log`, `.row` and an empty `runner.err`. `trials.csv`
  has 25 rows with 11 fields, one per tag; each row equals its `.row` plus the dump column; handler,
  PE 0 exit code (3 for the stuck wait, 0 otherwise), kill time (set only for kill trials) and last
  "PE 0" line agree with `pe0.log`. `run_all.out` has 25 "done" lines for the same set.
- `[측정]` `cqdump.txt` agrees with the recount in all 10 decoded queues (type, bytes, written, error,
  last opcode, summary line), and the `trials.csv` dump column equals its last line.
- `[측정]` The cuda-gdb process ID equals PE 0's process ID in `pe0.log`'s NVSHMEM lines in all 5 reads.
  The QP number inside each decoded CQE (bytes 57–59) equals the queue's QP number from the `prep` line
  in all 10, so the read returned real CQ contents, not zeros.
- `[측정]` Kernel-path queue lines match the `prep` lines (type, QP number, 1024 entries); the RC queue is
  `cq=1` there and `cq=2` in the cuda-gdb read, as DEVIATIONS item 6 says.
- `[측정]` Frozen files: `predictions.csv` sha256 equals `PREREG.txt`; `predictions.csv` and
  `PREREG.txt` have no diff against tag `prereg/cq380-v1`, nor do sections 2, 3, 7 and 8 of
  `EXPERIMENT.md` (its status, checklists and run log changed, as expected). The program binary on rain has md5
  `e65c967e` and file time 09:36:37, as DEVIATIONS item 4 states; sunny's copy `[미확인]`.

## Discrepancies and notes

1. **No conflict found** between `pe0.log`, `cudagdb.txt` and `cqdump.txt`. `cqdump.py` itself does not
   check the start address, line continuity or byte count; the recount did, and all passed.
2. **Kill marker missing.** `[측정]` The runner's "SIGKILL PE 1 at" line is in none of the 25
   `pe0.log` files; the kill time exists only in `.row` and `trials.csv`. `[추론]` PE 0's later output
   overwrote it (the runner appends to a file PE 0 writes without append mode). Scoring is unaffected.
3. **NIC counter deltas are all zero.** `[측정]` The counter column in `trials.csv` is `0;0;0;0;` in all
   25 rows, including the 10 kill trials whose RC queue holds an error CQE; the counters on rain's
   mlx5_1 are readable and non-zero now. `[미확인]` Why; `[추론]` the IBGDA QPs may not be attached to the
   port counter set. Not a scoring input.
4. **"First error" is the only written CQE.** `[측정]` All 50 queues (25 trials x 2) have exactly one
   written CQE; slot 0 is shown for the 10 cuda-gdb queues and the 10 error queues (`first_err_at=0`),
   not for the 30 kernel-path success queues `[미확인]`. `[추론]` With one slot, the reported error
   (syndrome 0x05, work request flushed, 10/10) is the last CQE written; an earlier error such as retry
   exceeded would have been overwritten.
5. **Read time.** `[측정]` In the 5 cuda-gdb trials, `pe0.log` was last written 35.1–35.2 s after the
   kill and `cudagdb.txt` finished 38.3–38.5 s after it (file times, range over the 5 trials), inside
   the 40 s hold.
6. `[추론]` The RC success CQE at wqe_counter 24 fits five completed iterations (0–4) of five WQEs each,
   with nothing completing for iteration 5; WQEs per iteration `[미확인]`.
