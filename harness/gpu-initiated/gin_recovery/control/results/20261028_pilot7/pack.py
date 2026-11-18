#!/usr/bin/env python3
"""pack.py: pilot 7's scratch results (pilot7/) into results/20261028_pilot7/a1/ (one attempt, three holds), IPv4-masked; a rank
log over 5 MB is masked and gzipped; a1/trials.csv is the scratch-copy rule check's (sc/trials_scored.csv) rows; score_v0/ is
the rule check's output (scorer at worktree HEAD 1ad05eb8, unchanged); events/ is events.py's list per trial"""
import os, re, glob, csv, gzip
S = "/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_gc_pilot7"
SRC = S + "/pilot7"
DST = "/home/unionxic/rdma-error-wt/gin-control/harness/gpu-initiated/gin_recovery/control/results/20261028_pilot7"
HOLDS = {"PCELL-gc4_gpuhang12000_waiter_hung+gc4_gpuhang12000_waiter_hung+gc4_gpuhang12000_waitpend_fence+gc4_gpuhang12000_fence+gc4_gpuhang12000_ctx1_fence": "PCELL1",
         "PCELL-gc4_stop12000_fence+gc4_kill3_ow+gc4_quiet12000": "PCELL2", "PRC-gc-mi4_kill2_kill3_ow": "PRC"}
MASK = re.compile(rb"([0-9]{1,3}\.){3}[0-9]{1,3}")
def put(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    b = MASK.sub(b"<addr>", open(src, "rb").read())
    if len(b) > 5 * 1024 * 1024 and src.endswith(".log"):
        with gzip.open(dst + ".gz", "wb") as f:
            f.write(b)
        return
    open(dst, "wb").write(b)
d = os.path.join(DST, "a1")
for h, sh in HOLDS.items():
    for f in ("snap_before-%s.txt" % h, "snap_after-%s.txt" % h, "mlx5_new_%s.txt" % h):
        put(os.path.join(SRC, f), os.path.join(d, f.replace(h, sh)))
    put(os.path.join(SRC, "hold_%s.out" % h), os.path.join(d, "run_%s.out" % sh))
for f in glob.glob(os.path.join(SRC, "raw", "*")):
    put(f, os.path.join(d, "raw", os.path.basename(f)))
def clean(r):
    r = {k: MASK.sub(b"<addr>", v.encode()).decode() if isinstance(v, str) else v for k, v in r.items()}
    if r.get("stem", "").startswith(S):
        r["stem"] = os.path.relpath(r["stem"], S + "/sc")
    return r
rows = [clean(r) for r in csv.DictReader(open(S + "/sc/trials_scored.csv"))]
for path in (os.path.join(d, "trials.csv"), os.path.join(DST, "score_v0", "trials_scored.csv")):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as fo:
        w = csv.DictWriter(fo, fieldnames=list(rows[0].keys())); w.writeheader(); [w.writerow(r) for r in rows]
for f in ("chain.out", "hang_watchdog.txt"):
    put(os.path.join(SRC, f), os.path.join(DST, f))
for f in ("attempts.txt", "deploy.txt", "events.py", "summ.py", "twodeath.py", "summary.txt", "build_drv.log", "hold.sh"):
    put(os.path.join(S, f), os.path.join(DST, f))
for f in ("SCORE.md", "rulecheck.json"):
    put(os.path.join(S, "sc", f), os.path.join(DST, "score_v0", f))
put(os.path.join(S, "sc_out.txt"), os.path.join(DST, "score_v0", "score_out.txt"))
put(os.path.join(S, "score_pilot.py"), os.path.join(DST, "score_v0", "score_pilot.py"))
for f in glob.glob(os.path.join(S, "ev", "*.txt")):
    put(f, os.path.join(DST, "events", os.path.basename(f)))
print("trials", len(rows))
