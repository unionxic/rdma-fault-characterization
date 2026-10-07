#!/usr/bin/env python3
"""score.py <results_dir> - score C1-C4 of predictions.csv from the cq380 trial files.

Per trial: <tag>.pe0.log (the program's own CQSCAN lines, path=kernel) or <tag>.cqdump.txt
(cuda-gdb read, path=cuda-gdb, DEVIATIONS 1). Writes SCORE.md and trials_scored.csv.
"""
import csv, glob, os, re, sys

R = os.path.abspath(sys.argv[1])
rows = []
for log0 in sorted(glob.glob(os.path.join(R, "*.pe0.log"))):
    tag = os.path.basename(log0)[:-len(".pe0.log")]
    m = re.match(r"(stock|fix)_(gpu|cpu_host_memory)_kill(\d)_t(\d+)$", tag)
    if not m:
        continue
    log = open(log0, errors="replace").read()
    src = log
    dump = os.path.join(R, tag + ".cqdump.txt")
    if "CQSCAN queues=" not in log and os.path.exists(dump):
        src = open(dump, errors="replace").read()
    summ = re.search(r"CQSCAN queues=(\d+) total_err=(\d+) path=(\S+)", src)
    rc = [l for l in re.findall(r"CQSCAN cq=\d+ type=rc .*", src)]
    rc_valid = sum(int(re.search(r"valid=(\d+)", l).group(1)) for l in rc)
    rc_err = sum(int(re.search(r"err=(\d+)", l).group(1)) for l in rc)
    errs = re.findall(r"syndrome=(0x[0-9a-f]+) vendor=(0x[0-9a-f]+)", src)
    hung = "has not returned" in log
    scan_failed = "CQSCAN failed" in log
    after = re.findall(r"PE 0 iter (\d+): put \+ signal \+ nvshmem_quiet\(\) returned after ([\d.]+) ms", log)
    slow = [f"iter {i} {float(t):.0f} ms" for i, t in after if float(t) > 1000]
    rows.append(dict(tag=tag, var=m.group(1), handler=m.group(2), kill=int(m.group(3)), trial=int(m.group(4)),
                     scanned=bool(summ), path=summ.group(3) if summ else "", total_err=int(summ.group(2)) if summ else None,
                     rc_valid=rc_valid, rc_err=rc_err, errors=";".join("/".join(e) for e in errs),
                     hung=hung, scan_failed=scan_failed, slow=";".join(slow)))


def cell(name, sel, pred, guard=None):
    rs = [r for r in rows if sel(r)]
    unobs = [r["tag"] for r in rs if not r["scanned"] or (guard and not guard(r))]
    seen = [r for r in rs if r["tag"] not in unobs]
    misses = [r["tag"] for r in seen if not pred(r)]
    hits = len(seen) - len(misses)
    verdict = "no data" if not seen else ("holds" if not misses and not unobs else ("fails" if misses else "not observable"))
    # section 8 read strictly: a trial whose in-process scan failed is not observable (DEVIATIONS 3)
    strict = [r for r in seen if not r["scan_failed"]]
    s_miss = [r for r in strict if not pred(r)]
    s_verdict = "not observable" if not strict else ("holds" if not s_miss and len(strict) == len(rs) else
                                                     ("fails" if s_miss else "not observable"))
    return dict(id=name, n=len(seen), hits=hits, misses=misses, unobs=unobs, verdict=verdict,
                strict=f"{s_verdict} (n={len(strict)})")


res = [
    cell("C1 CPU 프록시 공식본, kill", lambda r: r["var"] == "stock" and r["handler"] == "cpu_host_memory" and r["kill"] == 1,
         lambda r: r["total_err"] == 0, guard=lambda r: r["rc_valid"] >= 1),
    cell("C2 GPU 처리 공식본, kill", lambda r: r["var"] == "stock" and r["handler"] == "gpu" and r["kill"] == 1,
         lambda r: r["rc_err"] >= 1),
    cell("C3 CPU 프록시 수정본, kill", lambda r: r["var"] == "fix" and r["kill"] == 1, lambda r: r["rc_err"] >= 1),
    cell("C4 CPU 프록시 공식본, 장애 없음", lambda r: r["var"] == "stock" and r["handler"] == "cpu_host_memory" and r["kill"] == 0,
         lambda r: r["total_err"] == 0),
    cell("C4 GPU 처리 공식본, 장애 없음", lambda r: r["var"] == "stock" and r["handler"] == "gpu" and r["kill"] == 0,
         lambda r: r["total_err"] == 0),
]
keys = ["tag", "path", "scan_failed", "total_err", "rc_valid", "rc_err", "errors", "hung", "slow"]
with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(keys)
    for r in rows:
        w.writerow([r[k] for k in keys])
with open(os.path.join(R, "SCORE.md"), "w") as f:
    f.write("# cq380 score\n\nScored by `score.py` against `predictions.csv` (tag prereg/cq380-v1). "
            "Per-trial values: `trials_scored.csv`.\n\n"
            "`verdict` uses the cuda-gdb read for trials whose own scan failed (DEVIATIONS 1, 3). `strict` reads "
            "section 8 literally and counts those trials as not observable.\n\n"
            "| cell | n | hits | verdict | strict | misses | not observable |\n|---|--:|--:|---|---|---|---|\n")
    for c in res:
        f.write(f"| {c['id']} | {c['n']} | {c['hits']} | **{c['verdict']}** | {c['strict']} | {', '.join(c['misses'])} | {', '.join(c['unobs'])} |\n")
print(open(os.path.join(R, "SCORE.md")).read())
