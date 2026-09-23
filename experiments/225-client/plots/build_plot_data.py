#!/usr/bin/env python3
"""Generate plot-ready CSVs from the four experiments' raw data.

Raw inputs live under 225-client/01_cpu_baseline/experiment{1..4}/results/.

Outputs (under plots/data/):
  exp1_distribution.csv     scenario, latency_ms       (per-iteration)
  exp2_sleep_curve.csv      scenario, sleep_us, mean_ms, stddev_ms, n
  exp3_stages.csv           stage, mean_us, stddev_us, p50_us, p99_us, n
  exp4_kill_heatmap.csv     retry_cnt, qp_timeout, timeout_ms, mean_ms, n_ok, n_observed
  exp4_baseline_success.csv retry_cnt, qp_timeout, success_pct, n
  exp4_netem_success.csv    retry_cnt, qp_timeout, loss_pct, success_pct, n

Each builder only computes its rows; outputs are written to a temp file and
atomically renamed into place after the builder succeeded, so a builder whose
inputs are missing (e.g. exp1's raw CSVs are git-ignored and not in the repo)
or unreadable leaves its committed output untouched. Exit status is non-zero
if any builder was skipped or failed (--allow-missing: skipped-for-missing-
inputs alone does not fail the run).
"""

import argparse
import csv
import math
import os
import stat
import sys
import tempfile
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 225-client
RAW = os.path.join(ROOT, "01_cpu_baseline")    # experiment{1..4}/ raw trees
DATA = os.path.join(ROOT, "plots", "data")


class MissingInputs(Exception):
    def __init__(self, paths):
        super().__init__(", ".join(paths))
        self.paths = paths


def require(*paths):
    """Raise MissingInputs listing every path that is not an existing file."""
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        raise MissingInputs(missing)


def raw(exp, *parts):
    return os.path.join(RAW, exp, *parts)


def read(path):
    with open(path, "r", newline="") as f:
        return list(csv.DictReader(f))


# -----------------------------------------------------------------------
# Exp 1: per-iteration distribution across A/B/C
# -----------------------------------------------------------------------
def build_exp1():
    src = [
        raw("experiment1", "results", "detection_latency.csv"),
        raw("experiment1", "results", "detection_latency_b.csv"),
        raw("experiment1", "results", "detection_latency_c.csv"),
    ]
    require(*src)
    rows = []
    for full in src:
        for r in read(full):
            rows.append([r["scenario"], r["iteration"],
                         int(r["detection_latency_ns"]) / 1e6])
    return [(os.path.join(DATA, "exp1_distribution.csv"),
             ["scenario", "iteration", "detection_latency_ms"], rows)]


# -----------------------------------------------------------------------
# Exp 2: mean ± stddev curves
# -----------------------------------------------------------------------
def build_exp2():
    paths = [
        raw("experiment2", "results", "blind_window_a.csv"),
        raw("experiment2", "results", "blind_window_b_combined.csv"),
        raw("experiment2", "results", "blind_window_c_combined.csv"),
    ]
    require(*paths)
    g = defaultdict(list)
    for p in paths:
        for r in read(p):
            d = int(r["detection_delay_ns"])
            if d > 0:
                g[(r["scenario"], int(r["sleep_us"]))].append(d)
    rows = []
    for (sc, su), vals in sorted(g.items()):
        n = len(vals)
        mean = sum(vals) / n / 1e6
        sd = math.sqrt(sum((x - sum(vals)/n) ** 2 for x in vals) /
                       max(1, n - 1)) / 1e6
        sv = sorted(vals)
        rows.append([sc, su, mean, sd, sv[n // 2] / 1e6,
                     sv[0] / 1e6, sv[-1] / 1e6, n])
    return [(os.path.join(DATA, "exp2_sleep_curve.csv"),
             ["scenario", "sleep_us", "mean_ms",
              "stddev_ms", "p50_ms", "min_ms", "max_ms", "n"], rows)]


# -----------------------------------------------------------------------
# Exp 3: per-stage statistics
# -----------------------------------------------------------------------
def build_exp3():
    src = raw("experiment3", "results", "recovery.csv")
    require(src)
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
    out_rows = []
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
        out_rows.append([label, n,
                         mu / 1e3, sd / 1e3,
                         sv[n // 2] / 1e3, p99 / 1e3,
                         sv[0] / 1e3, sv[-1] / 1e3])
    return [(os.path.join(DATA, "exp3_stages.csv"),
             ["stage", "n", "mean_us", "stddev_us",
              "p50_us", "p99_us", "min_us", "max_us"], out_rows)]


# -----------------------------------------------------------------------
# Exp 4: heatmap (kill) + success matrices
# -----------------------------------------------------------------------
def build_exp4():
    res = raw("experiment4", "results")
    files = (sorted(f for f in os.listdir(res)
                    if f.startswith("exp4_") and f.endswith(".csv"))
             if os.path.isdir(res) else [])
    if not files:
        raise MissingInputs([os.path.join(res, "exp4_*.csv")])
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

    outputs = []

    # ---- exp4_kill_heatmap.csv (one row per (R, T)) ----
    kill = [r for r in rows if r["mode"] == "kill"]
    out_rows = []
    for r in kill:
        T = r["qp_timeout"]
        tms = 4.096 * (2 ** T) / 1000.0
        timed_out = 1 if r["n_ok"] == 0 else 0
        out_rows.append([r["retry_cnt"], T, tms,
                         r["mean_us"] / 1000.0,
                         r["p50_us"] / 1000.0,
                         r["p99_us"] / 1000.0,
                         r["n_ok"], r["n_observed"], timed_out])
    outputs.append((os.path.join(DATA, "exp4_kill_heatmap.csv"),
                    ["retry_cnt", "qp_timeout", "timeout_ms",
                     "mean_ms", "p50_ms", "p99_ms", "n_ok",
                     "n_observed", "timed_out"], out_rows))

    # ---- exp4_baseline_success.csv (no fault, loss=0) ----
    base = [r for r in rows if r["mode"] == "netem" and r["loss_pct"] == 0]
    # Deduplicate by (R, T) keeping the row with largest n_attempted
    best = {}
    for r in base:
        k = (r["retry_cnt"], r["qp_timeout"])
        if k not in best or r["n_attempted"] > best[k]["n_attempted"]:
            best[k] = r
    out_rows = []
    for k in sorted(best):
        r = best[k]
        pct = 100.0 * r["n_ok"] / r["n_observed"] if r["n_observed"] else 0
        out_rows.append([k[0], k[1], r["n_observed"], r["n_ok"], pct,
                         r["mean_us"]])
    outputs.append((os.path.join(DATA, "exp4_baseline_success.csv"),
                    ["retry_cnt", "qp_timeout", "n_observed",
                     "n_ok", "success_pct", "mean_us"], out_rows))

    # ---- exp4_netem_success.csv (transient netem, all loss>0) ----
    nem = [r for r in rows if r["mode"] == "netem" and r["loss_pct"] > 0]
    best = {}
    for r in nem:
        k = (r["retry_cnt"], r["qp_timeout"], r["loss_pct"])
        if k not in best or r["n_attempted"] > best[k]["n_attempted"]:
            best[k] = r
    out_rows = []
    for k in sorted(best):
        r = best[k]
        pct = 100.0 * r["n_ok"] / r["n_observed"] if r["n_observed"] else 0
        out_rows.append([k[0], k[1], k[2], r["n_observed"], r["n_ok"], pct])
    outputs.append((os.path.join(DATA, "exp4_netem_success.csv"),
                    ["retry_cnt", "qp_timeout", "loss_pct",
                     "n_observed", "n_ok", "success_pct"], out_rows))
    return outputs


# -----------------------------------------------------------------------
# Atomic output
# -----------------------------------------------------------------------
def commit_outputs(outputs):
    """Write every (path, header, rows) to a temp file in the target dir, then
    rename them all into place. Nothing is replaced unless all temps were
    written; a failure removes the temps and leaves existing outputs as-is."""
    temps = []
    try:
        for path, header, rows in outputs:
            d = os.path.dirname(path)
            fd, tmp = tempfile.mkstemp(
                prefix="." + os.path.basename(path) + ".", suffix=".tmp",
                dir=d)
            temps.append((tmp, path))
            with os.fdopen(fd, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(rows)
            # mkstemp creates 0600; keep the existing file's mode (else 0644).
            mode = (stat.S_IMODE(os.stat(path).st_mode)
                    if os.path.exists(path) else 0o644)
            os.chmod(tmp, mode)
        for tmp, path in temps:
            os.replace(tmp, path)
            print(f"  wrote {path}")
    finally:
        for tmp, _ in temps:
            if os.path.exists(tmp):
                os.unlink(tmp)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--allow-missing", action="store_true",
                    help="exit 0 even if some builders were skipped because "
                         "their raw inputs are missing (their outputs are "
                         "left untouched either way)")
    args = ap.parse_args(argv)

    print("Building plot data ...", flush=True)
    os.makedirs(DATA, exist_ok=True)
    built, missing, failed = [], [], []
    for name, fn in (("exp1", build_exp1), ("exp2", build_exp2),
                     ("exp3", build_exp3), ("exp4", build_exp4)):
        try:
            commit_outputs(fn())
            built.append(name)
        except MissingInputs as e:
            missing.append(name)
            print(f"  SKIP {name}: missing raw input(s); existing output(s) "
                  f"left untouched:", file=sys.stderr)
            for p in e.paths:
                print(f"         {os.path.relpath(p, ROOT)}", file=sys.stderr)
        except Exception as e:  # malformed input, I/O error, ...
            failed.append(name)
            print(f"  FAIL {name}: {type(e).__name__}: {e}; existing "
                  f"output(s) left untouched", file=sys.stderr)
        # keep stdout/stderr lines in order when piped (py3.8 block-buffers both)
        sys.stdout.flush()
        sys.stderr.flush()

    print(f"Done ({len(built)}/4 built"
          + (f"; missing inputs: {', '.join(missing)}" if missing else "")
          + (f"; failed: {', '.join(failed)}" if failed else "") + ").")
    if failed or (missing and not args.allow_missing):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
