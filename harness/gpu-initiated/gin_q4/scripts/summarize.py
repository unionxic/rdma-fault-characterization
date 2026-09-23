#!/usr/bin/env python3
"""summarize.py - Q4 / Task A / overhead tables from the per-trial CSVs.

usage: summarize.py <results_dir>
Reads <results_dir>/taskA/*.csv, <results_dir>/taskB/*.csv, <results_dir>/lat/*.csv (any that
exist) and writes <results_dir>/summary.md. Times: median [min-max] over trials, ms after the fault.
"""
import csv, glob, os, re, statistics, sys
from collections import Counter, defaultdict

ORDER = {"none": 0, "F1": 1, "F2": 2, "F3": 3, "F4": 4, "lat": 5}
TRUTH = {"F1": "LOCAL_QP_ERR (5/0xf5)", "F2": "REM_ACCESS (10/0x88)", "F3": "RETRY_EXC (12/0x81)",
         "F4": "RETRY_EXC or REM_ACCESS"}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def med(rows, k, fmt="%.1f"):
    xs = [x for x in (num(r.get(k)) for r in rows) if x is not None]
    if not xs:
        return "-"
    m = statistics.median(xs)
    return (fmt % m) + (" [" + (fmt % min(xs)) + "-" + (fmt % max(xs)) + "]" if len(xs) > 1 else "")


def cnt(rows, k, f=lambda v: v):
    c = Counter((f(r.get(k, "")) or "-") for r in rows)
    return ", ".join("%s x%d" % (v, n) if len(c) > 1 or n > 1 else v for v, n in sorted(c.items()))


def load(pattern):
    rows = []
    for p in sorted(glob.glob(pattern)):
        rows += list(csv.DictReader(open(p)))
    return rows


def fp(r):
    return "%s/%s" % (r["q4_status"], r["q4_vendor"]) if r.get("q4_status") else "-"


def slot(v):  # "wqe=77;op=0xd;syn=0x5;ve=0xf9" -> "0xd 5/0xf9 @77"
    if not v:
        return "-"
    d = dict(x.split("=", 1) for x in v.split(";") if "=" in x)
    op = d.get("op", "?")
    if op in ("0xd", "0xe"):
        return "%s %s/%s @%s" % (op, d.get("syn", "?"), d.get("ve", "?"), d.get("wqe", "?"))
    return "%s @%s" % (op, d.get("wqe", "?"))


def taskA(rows, out):
    out.append("## Task A: collapsed vs ring CQ inside GIN GDAKI\n")
    out.append("`-EIO seen` = the device poll returned -EIO (error CQE, opcode 0xd) in n trials. `root` = "
               "fingerprint the device classified (ring: first error CQE in [cqe_ci, ticket]; collapsed: slot 0). "
               "`polled/slot` = CQE at the polled index (ring) or slot 0 (collapsed) when the poll returned. "
               "`late` = collapsed slot 0 re-read ~500 us later. `QP ERR` = first host QUERY_QP showing ERR "
               "(100 ms watch). Times in ms after the fault.\n")
    out.append("| cq | classify | fault | wait | n | -EIO seen | root (status/vendor) | class | polled/slot CQE | "
               "window err/ok | late re-read | CQ buffer err | t_dev | t_api | QP ERR (watch) | init / target | "
               "init_silent_iters | teardown |")
    out.append("|" + "---|" * 18)
    cells = defaultdict(list)
    for r in rows:
        cells[(r["cq_type"], r["classify"], r["fault"], r["wait_mode"])].append(r)
    for k in sorted(cells, key=lambda k: (k[0], k[1], ORDER.get(k[2], 9), k[3])):
        rs = cells[k]
        eio = sum(1 for r in rs if int(r.get("q4_nrec") or 0) > 0)
        win = cnt(rs, "q4_window", lambda v: "%s/%s" % (re.search(r"err=(\d+)", v).group(1), re.search(r"ok=(\d+)", v).group(1)) if v else "")
        late = cnt(rs, "late_reread", slot) if any(r.get("late_reread") for r in rs) else "-"
        polled = cnt(rs, "q4_polled", slot) if eio else ("dump: " + cnt(rs, "dump_polled", slot) if any(r.get("dump_polled") for r in rs) else "-")
        out.append("| %s | %s | %s | %s | %d | %d/%d | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s | %s | %s |" % (
            k[0], k[1], k[2], k[3], len(rs), eio, len(rs), cnt(rs, "q4_status", lambda v: v) if not eio else
            ", ".join("%s x%d" % (v, n) for v, n in Counter(fp(r) for r in rs).items()),
            cnt(rs, "q4_class"), polled, win, late, cnt(rs, "q4_buffer_err"), med(rs, "t_dev_ms", "%.2f"),
            med(rs, "t_api_ms", "%.1f"), med(rs, "qpwatch_err_ms", "%.0f"), cnt(rs, "init_outcome"), cnt(rs, "target_outcome"),
            "/".join(r["init_silent_iters"] for r in rs), cnt(rs, "teardown")))
    out.append("")


def taskB(rows, out):
    out.append("## Task B (Q4): device classification + host mailbox, ring CQ\n")
    out.append("classify 1 = NCCL_GIN_FAULT_CLASSIFY=1, 0 = same build with the flag off (stock paths). "
               "t_dev = device detection (%globaltimer of the record), t_mbx = host watcher read the record, "
               "t_rc = host saw the kernel return, t_api = first non-success ncclCommGetAsyncError (driver polls "
               "every 200 us); all ms after the fault, median [min-max].\n")
    out.append("| classify | fault | wait | n | init / target | device rc | class (true: fault) | root fp | "
               "t_dev | t_mbx | t_rc | t_api | init_silent_iters | host_error | teardown |")
    out.append("|" + "---|" * 15)
    cells = defaultdict(list)
    for r in rows:
        cells[(r["classify"], r["fault"], r["wait_mode"])].append(r)
    for k in sorted(cells, key=lambda k: (k[0], ORDER.get(k[1], 9), k[2])):
        rs = cells[k]
        cls = cnt(rs, "q4_class")
        out.append("| %s | %s | %s | %d | %s / %s | %s | %s (%s) | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            k[0], k[1], k[2], len(rs), cnt(rs, "init_outcome"), cnt(rs, "target_outcome"), cnt(rs, "device_rc"),
            cls, TRUTH.get(k[1], "-"), ", ".join("%s x%d" % (v, n) for v, n in Counter(fp(r) for r in rs).items()),
            med(rs, "t_dev_ms", "%.2f"), med(rs, "t_mbx_ms", "%.2f"), med(rs, "t_rc_ms", "%.2f"),
            med(rs, "t_api_ms", "%.2f"), "/".join(r["init_silent_iters"] for r in rs), cnt(rs, "host_error"),
            cnt(rs, "teardown")))
    out.append("")


def pooled(logdir, cq, c, wait, bytes_, poll):
    """All raw per-iteration latencies (ns) of one overhead cell, from the *_lat_raw.csv.gz files."""
    import gzip
    xs = []
    tag = ("tb%dr*" % bytes_) if poll == 20 else ("tb%dp%dr*" % (bytes_, poll))
    for p in glob.glob(os.path.join(logdir, "%s_c%s_lat_%s_%s_lat_raw.csv.gz" % (cq, c, wait, tag))):
        with gzip.open(p, "rt") as f:
            xs += [int(l.split(",")[1]) for l in f if "," in l]
    return sorted(xs)


def overhead(rows, out, logdir):
    out.append("## Overhead: put + signal + flush latency, no fault (ring CQ, same build)\n")
    out.append("Each run: 5 x 2000 back-to-back iterations in one kernel, each timed on the GPU (%globaltimer). "
               "Pooled = all iterations of all runs of the cell; per-run = median [min-max] over runs of the "
               "per-run p50 / p99. cpu/wall = process CPU time over wall time of the timed phase (all threads: "
               "GIN CPU-proxy doorbell thread, mailbox watcher when on, main). Latencies in us.\n")
    out.append("| bytes | wait | classify | watcher poll | runs | samples | pooled p50 | pooled p90 | pooled p99 | "
               "pooled p99.9 | pooled mean | per-run p50 | per-run p99 | cpu/wall |")
    out.append("|" + "---|" * 14)
    cells = defaultdict(list)
    for r in rows:
        b = re.match(r"b(\d+)(?:p(\d+))?r", r["trial"])
        if not b:
            continue
        r["_cpu"] = (num(r["lat_cpu_ms"]) / num(r["lat_wall_ms"])) if num(r.get("lat_wall_ms")) else None
        poll = int(b.group(2)) if b.group(2) else 20
        cells[(int(b.group(1)), r["wait_mode"], r["classify"], poll, r["cq_type"])].append(r)
    for k in sorted(cells):
        rs = cells[k]
        xs = pooled(logdir, k[4], k[2], k[1], k[0], k[3])
        q = (lambda p: "%.2f" % (xs[int(p * (len(xs) - 1) + 0.5)] / 1e3)) if xs else (lambda p: "-")
        mean = ("%.2f" % (sum(xs) / len(xs) / 1e3)) if xs else "-"
        out.append("| %d | %s | %s | %s | %d | %d | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            k[0], k[1], k[2], ("%d us" % k[3]) if k[2] == "1" else "-", len(rs), len(xs), q(0.5), q(0.9), q(0.99),
            q(0.999), mean,
            med(rs, "lat_p50_us", "%.2f"), med(rs, "lat_p99_us", "%.2f"), med(rs, "_cpu", "%.2f")))
    out.append("")


def main():
    d = sys.argv[1]
    out = ["# GIN GDAKI Q4 summary", "", "source: `%s`" % d, ""]
    a = load(os.path.join(d, "taskA", "*.csv"))
    if a:
        taskA(a, out)
    b = load(os.path.join(d, "taskB", "*.csv"))
    if b:
        taskB(b, out)
    l = load(os.path.join(d, "lat", "*.csv"))
    if l:
        overhead(l, out, os.path.join(d, "lat", "logs"))
    text = "\n".join(out)
    open(os.path.join(d, "summary.md"), "w").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
