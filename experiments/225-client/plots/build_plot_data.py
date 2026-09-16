#!/usr/bin/env python3
"""Generate plot-ready CSVs from the four experiments' raw data.

Outputs (under plots/data/):
  exp1_distribution.csv     scenario, latency_ms       (per-iteration)
  exp2_sleep_curve.csv      scenario, sleep_us, mean_ms, stddev_ms, n
  exp3_stages.csv           stage, mean_us, stddev_us, p50_us, p99_us, n
  exp4_kill_heatmap.csv     retry_cnt, qp_timeout, timeout_ms, mean_ms, n_ok, n_observed
  exp4_baseline_success.csv retry_cnt, qp_timeout, success_pct, n
  exp4_netem_success.csv    retry_cnt, qp_timeout, loss_pct, success_pct, n
"""

import csv
import math
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "plots", "data")
os.makedirs(DATA, exist_ok=True)


def read(path):
    with open(path, "r") as f:
        return list(csv.DictReader(f))


# -----------------------------------------------------------------------
# Exp 1: per-iteration distribution across A/B/C
# -----------------------------------------------------------------------
def build_exp1():
    out = os.path.join(DATA, "exp1_distribution.csv")
    src = [
        ("results/detection_latency.csv",   "QP_TO_ERR"),
        ("results/detection_latency_b.csv", "KILL_PROCESS"),
        ("results/detection_latency_c.csv", "LINK_DOWN"),
    ]
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "iteration", "detection_latency_ms"])
        for rel, override in src:
            full = os.path.join(ROOT, "experiment1", rel)
            for r in read(full):
                w.writerow([r["scenario"], r["iteration"],
                            int(r["detection_latency_ns"]) / 1e6])
    print(f"  wrote {out}")


# -----------------------------------------------------------------------
# Exp 2: mean ± stddev curves
# -----------------------------------------------------------------------
def build_exp2():
    out = os.path.join(DATA, "exp2_sleep_curve.csv")
    paths = [
        os.path.join(ROOT, "experiment2", "results", "blind_window_a.csv"),
        os.path.join(ROOT, "experiment2", "blind_window_b.csv"),
        os.path.join(ROOT, "experiment2", "blind_window_c.csv"),
    ]
    g = defaultdict(list)
    for p in paths:
        for r in read(p):
            d = int(r["detection_delay_ns"])
            if d > 0:
                g[(r["scenario"], int(r["sleep_us"]))].append(d)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "sleep_us", "mean_ms",
                    "stddev_ms", "p50_ms", "min_ms", "max_ms", "n"])
        for (sc, su), vals in sorted(g.items()):
            n = len(vals)
            mean = sum(vals) / n / 1e6
            sd = math.sqrt(sum((x - sum(vals)/n) ** 2 for x in vals) /
                           max(1, n - 1)) / 1e6
            sv = sorted(vals)
            w.writerow([sc, su, mean, sd, sv[n // 2] / 1e6,
                        sv[0] / 1e6, sv[-1] / 1e6, n])
    print(f"  wrote {out}")


# -----------------------------------------------------------------------
# Exp 3: per-stage statistics
# -----------------------------------------------------------------------
def build_exp3():
    out = os.path.join(DATA, "exp3_stages.csv")
    src = os.path.join(ROOT, "experiment3", "results", "recovery.csv")
    rows = read(src)
    fields = [
        ("detection_ns",        "detection",   "ms"),
        ("drain_ns",            "drain",       "us"),
        ("T1_ns",               "T1_ERR_RESET", "us"),
        ("T2_ns",               "T2_RESET_INIT", "us"),
        ("coord1_ns",           "coord1",      "us"),
        ("T3_ns",               "T3_INIT_RTR", "us"),
        ("T4_ns",               "T4_RTR_RTS",  "us"),
        ("coord2_ns",           "coord2",      "us"),
        ("T5_ns",               "T5_write_cqe", "us"),
        ("total_local_ns",      "total_local",  "us"),
        ("total_with_coord_ns", "total_w_coord", "us"),
    ]
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stage", "n", "mean_us", "stddev_us",
                    "p50_us", "p99_us", "min_us", "max_us"])
        for field, label, _ in fields:
            vals = [int(r[field]) for r in rows if r.get(field)]
            if not vals:
                continue
            n = len(vals)
            mu = sum(vals) / n
            sd = math.sqrt(sum((x - mu) ** 2 for x in vals) /
                           max(1, n - 1))
            sv = sorted(vals)
            p99 = sv[min(int(n * 0.99), n - 1)]
            w.writerow([label, n,
                        mu / 1e3, sd / 1e3,
                        sv[n // 2] / 1e3, p99 / 1e3,
                        sv[0] / 1e3, sv[-1] / 1e3])
    print(f"  wrote {out}")


# -----------------------------------------------------------------------
# Exp 4: heatmap (kill) + success matrices
# -----------------------------------------------------------------------
def build_exp4():
    res = os.path.join(ROOT, "experiment4", "results")
    files = sorted(f for f in os.listdir(res) if f.startswith("exp4_"))
    rows = []
    for f in files:
        rows.extend(read(os.path.join(res, f)))

    # Cast types
    for r in rows:
        for k in ("retry_cnt", "qp_timeout", "loss_pct",
                  "n_attempted", "n_observed", "n_ok"):
            r[k] = int(r[k])
        for k in ("mean_us", "p50_us", "p99_us"):
            r[k] = float(r[k])

    # ---- exp4_kill_heatmap.csv (one row per (R, T)) ----
    kill = [r for r in rows if r["mode"] == "kill"]
    out = os.path.join(DATA, "exp4_kill_heatmap.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["retry_cnt", "qp_timeout", "timeout_ms",
                    "mean_ms", "p50_ms", "p99_ms", "n_ok",
                    "n_observed", "timed_out"])
        for r in kill:
            T = r["qp_timeout"]
            tms = 4.096 * (2 ** T) / 1000.0
            timed_out = 1 if r["n_ok"] == 0 else 0
            w.writerow([r["retry_cnt"], T, tms,
                        r["mean_us"] / 1000.0,
                        r["p50_us"] / 1000.0,
                        r["p99_us"] / 1000.0,
                        r["n_ok"], r["n_observed"], timed_out])
    print(f"  wrote {out}")

    # ---- exp4_baseline_success.csv (no fault, loss=0) ----
    base = [r for r in rows if r["mode"] == "netem" and r["loss_pct"] == 0]
    # Deduplicate by (R, T) keeping the row with largest n_attempted
    best = {}
    for r in base:
        k = (r["retry_cnt"], r["qp_timeout"])
        if k not in best or r["n_attempted"] > best[k]["n_attempted"]:
            best[k] = r
    out = os.path.join(DATA, "exp4_baseline_success.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["retry_cnt", "qp_timeout", "n_observed",
                    "n_ok", "success_pct", "mean_us"])
        for k in sorted(best):
            r = best[k]
            pct = 100.0 * r["n_ok"] / r["n_observed"] if r["n_observed"] else 0
            w.writerow([k[0], k[1], r["n_observed"], r["n_ok"], pct,
                        r["mean_us"]])
    print(f"  wrote {out}")

    # ---- exp4_netem_success.csv (transient netem, all loss>0) ----
    nem = [r for r in rows if r["mode"] == "netem" and r["loss_pct"] > 0]
    best = {}
    for r in nem:
        k = (r["retry_cnt"], r["qp_timeout"], r["loss_pct"])
        if k not in best or r["n_attempted"] > best[k]["n_attempted"]:
            best[k] = r
    out = os.path.join(DATA, "exp4_netem_success.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["retry_cnt", "qp_timeout", "loss_pct",
                    "n_observed", "n_ok", "success_pct"])
        for k in sorted(best):
            r = best[k]
            pct = 100.0 * r["n_ok"] / r["n_observed"] if r["n_observed"] else 0
            w.writerow([k[0], k[1], k[2], r["n_observed"], r["n_ok"], pct])
    print(f"  wrote {out}")


def main():
    print("Building plot data ...")
    # NOTE: the per-experiment source paths below are relative to ROOT
    # (225-client). If a raw-experiment tree has been moved/renamed (e.g. the
    # exp1-4 raw CSVs now live under 01_cpu_baseline/), a builder's inputs will
    # be missing. Report and skip that experiment rather than aborting the whole
    # run, so the still-resolvable outputs are regenerated.
    ok = 0
    for name, fn in (("exp1", build_exp1), ("exp2", build_exp2),
                     ("exp3", build_exp3), ("exp4", build_exp4)):
        try:
            fn()
            ok += 1
        except (FileNotFoundError, NotADirectoryError) as e:
            print(f"  SKIP {name}: missing source ({e})")
    print(f"Done ({ok}/4 built).")


if __name__ == "__main__":
    main()
