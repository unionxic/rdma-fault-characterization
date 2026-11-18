#!/usr/bin/env python3
"""twodeath.py <raw dir> <stem>: pilot 6's per-trial two-death timeline. Times in ms after the first kill line (GINRS die rank=2),
on rain's CLOCK_MONOTONIC (sunny mono_ms minus the meta's sunny-rain offset with the smaller round trip). Sources: r0, r1
(both deaths), r3 (rank 3 incarnation 0: first death), spare (rank 2 incarnation 1: second death), spare_2nd (rank 3
incarnation 1), launcher_rain/sunny. Also the guard lines: suspected, partition guard, no witness, young, SELF."""
import re, sys, os
raw, stem = sys.argv[1], sys.argv[2]
meta = open(os.path.join(raw, stem + "_meta.txt")).read()
mv = lambda k: (re.search(r"\b%s=(\S+)" % k, meta) or [None, None])[1]
OFF = min([(float(mv("mono_off_rtt_ms")), float(mv("mono_off_sunny_ms"))), (float(mv("mono_off_after_rtt_ms")), float(mv("mono_off_after_ms")))])[1]
SRC = {"r0": "rain", "r1": "sunny", "r2": "rain", "r3": "sunny", "spare": "rain", "spare_2nd": "sunny",
       "launcher_rain": "rain", "launcher_sunny": "sunny"}
MONO = re.compile(r"\bmono_ms=([0-9.]+)")
PATS = [
 ("die", re.compile(r"GINRS die rank=(\d+) step=(\d+)")),
 ("fin", re.compile(r"socket to rank (\d+) closed cause=(\w+)")),
 ("confirm", re.compile(r"confirm window for rank (\d+) closed: (\w+) \(opened by (\w+) at [0-9.]+, READ1 ([^,]*), READ2 ([^,]*),")),
 ("dead", re.compile(r"GIN/TS: rank (\d+): rank (\d+) judged dead \(cause=([^)]*)\)")),
 ("stalled", re.compile(r"rank (\d+) \(incarnation \d+\) judged stalled \(([^)]*)\)")),
 ("row", re.compile(r"rank (\d+) \(incarnation (\d+)\) ended by the judgement table \(table row (\d+)")),
 ("suspect", re.compile(r"rank (\d+) suspected \(([^)]*)\)( \(partition guard: [^)]*\))?")),
 ("guard", re.compile(r"(partition guard[^)]*|no witness[^;)]*|young[^;)]*|\bSELF\b[^;)]*)")),
 ("held", re.compile(r"rank (\d+) \(incarnation (\d+)\) is held for a restore")),
 ("fence", re.compile(r"FENCE of rank (\d+)[^;]*?(SIGKILL sent|sent)")),
 ("fenced", re.compile(r"FENCED[: ].*?rank (\d+)|FENCED: (the group ended [0-9.]+ ms after SIGKILL)")),
 ("win", re.compile(r"window check after the (\w+) of rank (\d+): changed=(\d+)")),
 ("rejoin_acc", re.compile(r"the REJOIN of rank (\d+) \(incarnation (\d+)\) taken over UD")),
 ("repaired", re.compile(r"liveness READ QP to rank (\d+) (re-paired|paired) \(gen (\d+)\)")),
 ("published", re.compile(r"restore round with rank (\d+) published")),
 ("restored", re.compile(r"rank (\d+) restored as incarnation (\d+) \(on time; ([0-9.]+) ms after the hold start")),
 ("spare_restored", re.compile(r"spare rank (\d+): ncclGinRestoreResume: restored as incarnation (\d+) from checkpoint (\d+)")),
 ("declined", re.compile(r"\bdeclined? (?:rank|the hold)|degraded raise|FALLBACK\b")),
 ("spawn_refused", re.compile(r"refused SPAWN of rank (\d+)")),
 ("close", re.compile(r"hold at close: .*?holds=(\d+) restored=(\d+) fallbacks=(\d+) timeouts=(\d+)")),
]
ev = []
for src, node in SRC.items():
    p = os.path.join(raw, "%s_%s.log" % (stem, src))
    if not os.path.exists(p):
        continue
    for line in open(p, errors="replace"):
        m = MONO.search(line)
        for name, pat in PATS:
            g = pat.search(line)
            if not g:
                continue
            if name == "guard" and "self_loop" in line:
                continue
            if name == "fenced" and "launcher" not in src:
                continue
            t = float(m.group(1)) if m else None
            if t is not None and node == "sunny":
                t -= OFF
            ev.append((t, src, name, " ".join(x for x in g.groups() if x)))
t0 = min(t for t, s, n, a in ev if n == "die" and a.startswith("2 "))
ev.sort(key=lambda e: (e[0] is None, e[0] or 0))
print("# %s  t0 = GINRS die rank=2 (rain mono %.3f); offset %.3f" % (stem, t0, OFF))
for t, s, n, a in ev:
    print("%10s  %-14s %-14s %s" % ("-" if t is None else "%.1f" % (t - t0), s, n, a))
