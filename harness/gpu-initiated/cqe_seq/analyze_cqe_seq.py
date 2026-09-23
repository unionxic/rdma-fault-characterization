#!/usr/bin/env python3
"""analyze_cqe_seq.py - per-cell summary of the Q1 CQE sequences (python3 stdlib only).

usage: analyze_cqe_seq.py <results_dir | raw_*.csv / trials_*.csv files ...>
                          [--out summary.csv] [--md summary.md] [--exclude-run-prefix smoke]

Reads every raw_*.csv (one row per CQE, poll order) and trials_*.csv (one row per
trial) and derives, per trial:
  first CQE, root cause (= first non-SUCCESS CQE), last CQE (= what a single-slot
  collapsed CQ would end up holding), flush count (status 5), whether unsignaled
  WQEs produced CQEs (flush or error), successful CQEs before the root cause,
  whether the WQE indices come in order, whether every WQE after the root cause
  got exactly one flush CQE, and the time from the root-cause CQE to the next and
  to the last CQE (how long the root cause would sit in a collapsed slot).
Then aggregates per cell (fault, wqe_bytes, N, signaling, bad WQE position) into
a CSV and a markdown table.
"""
import csv
import glob
import os
import statistics
import sys
from collections import Counter, defaultdict

STATUS = {0: "SUCCESS", 5: "WR_FLUSH", 9: "REM_INV_REQ", 10: "REM_ACCESS",
          12: "RETRY_EXC", 13: "RNR_RETRY_EXC"}
FAULT_ORDER = ["local_qp_err", "rem_access", "rem_inv_req", "rnr",
               "retry_server_qp_err", "retry_proc_kill"]
KEY = ("fault", "wqe_bytes", "n_wqe", "signaling", "bad_pos")
TRIAL_KEY = ("run_id",) + KEY + ("trial", "trial_uid")


def fp(r):
    """fingerprint string of one CQE row, e.g. REM_ACCESS/0x88"""
    st = int(r["status"])
    return "%s/%s" % (STATUS.get(st, str(st)), r["vendor_err"])


def fp_at(r):
    return "%s@%s" % (fp(r), r["wqe_idx"])


def load(paths):
    raws, trials = [], []
    for p in paths:
        with open(p, newline="") as f:
            rows = list(csv.DictReader(f))
        base = os.path.basename(p)
        if base.startswith("raw_"):
            raws.extend(rows)
        elif base.startswith("trials_"):
            trials.extend(rows)
        else:
            sys.exit("don't know what %s is (expect raw_*.csv / trials_*.csv)" % p)
    return raws, trials


def per_trial(raws, trials):
    seqs = defaultdict(list)
    for r in raws:
        seqs[tuple(r[k] for k in TRIAL_KEY)].append(r)
    out = []
    for t in trials:
        tk = tuple(t[k] for k in TRIAL_KEY)
        cq = sorted(seqs.get(tk, []), key=lambda r: int(r["seq"]))
        n = int(t["n_wqe"])
        d = {"key": tuple(t[k] for k in KEY), "trial": t, "n": n, "cqes": cq}
        d["n_cqes"] = len(cq)
        d["first"] = cq[0] if cq else None
        d["last"] = cq[-1] if cq else None
        errs = [r for r in cq if int(r["status"]) != 0]
        root = errs[0] if errs else None
        d["root"] = root
        d["n_success"] = sum(1 for r in cq if int(r["status"]) == 0)
        d["n_flush"] = sum(1 for r in cq if int(r["status"]) == 5)
        d["n_err_nonflush"] = len(errs) - d["n_flush"]
        root_seq = int(root["seq"]) if root else None
        d["succ_before_root"] = (sum(1 for r in cq if int(r["status"]) == 0 and int(r["seq"]) < root_seq)
                                 if root else d["n_success"])
        d["unsig_flush"] = sum(1 for r in cq if r["wqe_signaled"] == "0" and int(r["status"]) == 5)
        d["unsig_err"] = sum(1 for r in cq if r["wqe_signaled"] == "0" and int(r["status"]) not in (0, 5))
        d["unsig_success"] = sum(1 for r in cq if r["wqe_signaled"] == "0" and int(r["status"]) == 0)
        d["n_unsignaled_wqes"] = 0 if t["signaling"] == "all" else n - 1
        # unsignaled WQEs that were still pending behind the root cause (only WQE
        # N-1 is signaled in "last" mode): did each of them get a flush CQE?
        if root is not None and t["signaling"] == "last":
            ridx = int(root["wqe_idx"])
            first_pending = ridx + 1 if int(root["status"]) != 5 else ridx
            d["unsig_after_root"] = max(0, (n - 1) - first_pending)
            d["unsig_after_root_flushed"] = sum(
                1 for r in cq if r["wqe_signaled"] == "0" and int(r["status"]) == 5
                and first_pending <= int(r["wqe_idx"]) < n - 1)
            d["root_unsignaled"] = (root["wqe_signaled"] == "0")
        else:
            d["unsig_after_root"] = 0
            d["unsig_after_root_flushed"] = 0
            d["root_unsignaled"] = False
        idxs = [int(r["wqe_idx"]) for r in cq]
        d["in_order"] = all(a < b for a, b in zip(idxs, idxs[1:]))
        d["foreign"] = sum(int(r["foreign"]) for r in cq)
        d["late"] = sum(int(r["late"]) for r in cq)
        if root:
            ridx = int(root["wqe_idx"])
            flush_idx = sorted(int(r["wqe_idx"]) for r in cq if int(r["status"]) == 5)
            # every WQE after the root cause got exactly one flush CQE (for
            # local_qp_err the root cause is itself the first flush)
            expect = list(range(ridx + 1, n)) if int(root["status"]) != 5 else list(range(ridx, n))
            d["flush_complete"] = (flush_idx == expect)
            d["last_is_root"] = (d["last"]["seq"] == root["seq"])
            d["last_fp_is_root_fp"] = (fp(d["last"]) == fp(root))
            t_root = int(root["t_ns"])
            d["t_root_us"] = t_root / 1e3
            d["span_us"] = (int(d["last"]["t_ns"]) - t_root) / 1e3
            nxt = [r for r in cq if int(r["seq"]) == root_seq + 1]
            d["gap_next_us"] = (int(nxt[0]["t_ns"]) - t_root) / 1e3 if nxt else None
        else:
            d.update(flush_complete=None, last_is_root=None, last_fp_is_root_fp=None,
                     t_root_us=None, span_us=None, gap_next_us=None)
        out.append(d)
    return out


def mode_str(values):
    """'<most common> (k/n)' or 'a (k/n); b (j/n)' when they differ"""
    c = Counter(values)
    n = len(values)
    return "; ".join("%s (%d/%d)" % (v, k, n) for v, k in c.most_common())


def rng(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    lo, hi = min(vals), max(vals)
    return str(lo) if lo == hi else "%s-%s" % (lo, hi)


def med(vals, fmt="%.1f"):
    vals = [v for v in vals if v is not None]
    return fmt % statistics.median(vals) if vals else "-"


def mx(vals, fmt="%.1f"):
    vals = [v for v in vals if v is not None]
    return fmt % max(vals) if vals else "-"


def count_true(vals):
    vals = [v for v in vals if v is not None]
    return "%d/%d" % (sum(1 for v in vals if v), len(vals)) if vals else "-"


def cell_sort(k):
    fault, wqe, n, sig, pos = k
    return (FAULT_ORDER.index(fault) if fault in FAULT_ORDER else 99, int(wqe), int(n),
            ["all", "last"].index(sig), ["none", "first", "middle", "last"].index(pos))


def summarize(tr):
    cells = defaultdict(list)
    for d in tr:
        cells[d["key"]].append(d)
    rows = []
    for k in sorted(cells, key=cell_sort):
        ds = cells[k]
        fault, wqe, n, sig, pos = k
        unsig = [d["unsig_flush"] for d in ds]
        rows.append({
            "fault": fault, "wqe_bytes": wqe, "n_wqe": n, "signaling": sig, "bad_pos": pos,
            "bad_idx": ds[0]["trial"]["bad_idx"],
            "trials": len(ds),
            "drain_quiet": sum(1 for d in ds if d["trial"]["drain_end"] == "quiet"),
            "verify_ok": sum(1 for d in ds if d["trial"]["verify_ok"] == "1"),
            "qp_state_after": mode_str([d["trial"]["qp_state_after"] for d in ds]),
            "n_cqes": rng([d["n_cqes"] for d in ds]),
            "first_cqe": mode_str([fp_at(d["first"]) if d["first"] else "none" for d in ds]),
            "root_cqe": mode_str([fp_at(d["root"]) if d["root"] else "none" for d in ds]),
            "last_cqe": mode_str([fp_at(d["last"]) if d["last"] else "none" for d in ds]),
            "n_success": rng([d["n_success"] for d in ds]),
            "succ_before_root": rng([d["succ_before_root"] for d in ds]),
            "n_flush": rng([d["n_flush"] for d in ds]),
            "n_err_nonflush": rng([d["n_err_nonflush"] for d in ds]),
            "unsig_wqes": ds[0]["n_unsignaled_wqes"],
            "unsig_flush_cqes": rng(unsig),
            "unsig_err_cqes": rng([d["unsig_err"] for d in ds]),
            "unsig_success_cqes": rng([d["unsig_success"] for d in ds]),
            "unsig_after_root": rng([d["unsig_after_root"] for d in ds]),
            "unsig_after_root_flushed": rng([d["unsig_after_root_flushed"] for d in ds]),
            # yes = every unsignaled WQE pending behind the root cause got a flush CQE
            "unsig_flush_yes": ("n/a" if all(d["unsig_after_root"] == 0 for d in ds) else
                                ("yes" if all(d["unsig_after_root_flushed"] == d["unsig_after_root"] for d in ds)
                                 else ("no" if all(d["unsig_after_root_flushed"] == 0 for d in ds) else "partly"))),
            "root_unsignaled_cqe": ("n/a" if not any(d["root_unsignaled"] for d in ds) else
                                    count_true([d["root_unsignaled"] for d in ds])),
            "in_order": count_true([d["in_order"] for d in ds]),
            "flush_complete": count_true([d["flush_complete"] for d in ds]),
            "last_is_root": count_true([d["last_is_root"] for d in ds]),
            "last_fp_is_root_fp": count_true([d["last_fp_is_root_fp"] for d in ds]),
            "t_root_us_med": med([d["t_root_us"] for d in ds]),
            "gap_next_us_med": med([d["gap_next_us"] for d in ds], "%.2f"),
            "gap_next_us_max": mx([d["gap_next_us"] for d in ds], "%.2f"),
            "span_us_med": med([d["span_us"] for d in ds], "%.2f"),
            "span_us_max": mx([d["span_us"] for d in ds], "%.2f"),
            "foreign": sum(d["foreign"] for d in ds),
            "late": sum(d["late"] for d in ds),
        })
    return rows


def short(s):
    """compact a mode_str for the markdown table: drop '(5/5)' when unanimous"""
    parts = s.split("; ")
    if len(parts) == 1 and s.endswith(")"):
        v, cnt = s.rsplit(" (", 1)
        a, b = cnt[:-1].split("/")
        if a == b:
            return v
    return s


def markdown(rows):
    hdr = ["fault", "N", "sig", "k", "first CQE", "root cause", "last CQE (collapsed slot)",
           "#CQE", "#flush", "unsig. flush", "succ<root", "last=root", "t0->root us",
           "root->next us", "root->last us", "QP"]
    out = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for r in rows:
        k = r["bad_pos"] if r["bad_pos"] == "none" else "%s(%s)" % (r["bad_pos"], r["bad_idx"])
        f = (r["fault"] if r["wqe_bytes"] == "4096" and r["fault"] != "local_qp_err"
             else "%s (%s B)" % (r["fault"], r["wqe_bytes"]))
        out.append("| " + " | ".join([
            f, r["n_wqe"], r["signaling"], k, short(r["first_cqe"]), short(r["root_cqe"]),
            short(r["last_cqe"]), r["n_cqes"], r["n_flush"],
            r["unsig_flush_yes"] if r["unsig_flush_yes"] == "n/a" else
            "%s (%s of %s)" % (r["unsig_flush_yes"], r["unsig_after_root_flushed"], r["unsig_after_root"]),
            r["succ_before_root"], r["last_is_root"], r["t_root_us_med"],
            "%s (max %s)" % (r["gap_next_us_med"], r["gap_next_us_max"]),
            "%s (max %s)" % (r["span_us_med"], r["span_us_max"]),
            short(r["qp_state_after"])]) + " |")
    return "\n".join(out)


def main(argv):
    out_csv, out_md, excl = None, None, None
    paths = []
    it = iter(argv)
    for a in it:
        if a == "--out":
            out_csv = next(it)
        elif a == "--md":
            out_md = next(it)
        elif a == "--exclude-run-prefix":
            excl = next(it)
        else:
            paths.append(a)
    if not paths:
        sys.exit(__doc__)
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "raw_*.csv")) + glob.glob(os.path.join(p, "trials_*.csv")))
            out_csv = out_csv or os.path.join(p, "summary.csv")
            out_md = out_md or os.path.join(p, "summary.md")
        else:
            files.append(p)
    raws, trials = load(files)
    if excl:
        raws = [r for r in raws if not r["run_id"].startswith(excl)]
        trials = [t for t in trials if not t["run_id"].startswith(excl)]
    tr = per_trial(raws, trials)
    rows = summarize(tr)
    if not rows:
        sys.exit("no trials found")
    if out_csv:
        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    md = markdown(rows)
    if out_md:
        with open(out_md, "w") as f:
            f.write(md + "\n")
    print(md)
    # headline: in how many trials would the collapsed slot still hold the root cause?
    tot = [d for d in tr if d["root"] is not None]
    surv = sum(1 for d in tot if d["last_is_root"])
    fpsurv = sum(1 for d in tot if d["last_fp_is_root_fp"])
    noerr = sum(1 for d in tr if d["root"] is None)
    print("\ntrials: %d (%d without any error CQE); last CQE is the root-cause CQE in %d/%d, "
          "last CQE has the root cause's fingerprint in %d/%d" % (len(tr), noerr, surv, len(tot), fpsurv, len(tot)))
    bad = [d for d in tr if d["trial"]["drain_end"] == "bound" or d["foreign"] or d["late"]]
    if bad:
        print("WARNING: %d trials with drain_end=bound, foreign or late CQEs" % len(bad))
    if out_csv:
        print("wrote %s%s" % (out_csv, (" and " + out_md) if out_md else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
