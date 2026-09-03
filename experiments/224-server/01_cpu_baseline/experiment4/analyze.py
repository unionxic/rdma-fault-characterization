#!/usr/bin/env python3
"""
analyze.py - Experiment 4: NIC Retry Boundary

CSV schema (from client.c):
  mode, retry_cnt, qp_timeout, rnr_retry, loss_pct,
  n_attempted, n_observed, n_ok,
  n_retry_exc, n_rnr_retry_exc, n_wr_flush, n_other,
  mean_us, p50_us, p99_us, min_us, max_us

Produces:
  1. Per-mode success-rate matrices (retry × timeout, faceted by loss%)
  2. Persistent-fault detection latency table (retry × timeout)
  3. Summary of dominant error codes per regime
"""

import sys
import csv
import argparse
from collections import defaultdict


def timeout_ms(x):
    return 4.096 * (2 ** x) / 1000.0


def load(path):
    rows = []
    with open(path, "r") as f:
        for r in csv.DictReader(f):
            for k in ("retry_cnt", "qp_timeout", "rnr_retry", "loss_pct",
                     "n_attempted", "n_observed", "n_ok",
                     "n_retry_exc", "n_rnr_retry_exc", "n_wr_flush",
                     "n_other"):
                if k in r and r[k] != "":
                    r[k] = int(r[k])
            for k in ("mean_us", "p50_us", "p99_us", "min_us", "max_us"):
                if k in r and r[k] != "":
                    r[k] = float(r[k])
            rows.append(r)
    return rows


def fmt_pct(ok, total):
    if total == 0:
        return "  -  "
    p = 100.0 * ok / total
    return f"{p:>5.1f}"


def fmt_us(v):
    if v >= 1_000_000:
        return f"{v/1e6:>7.2f}s"
    if v >= 1000:
        return f"{v/1e3:>7.2f}ms"
    return f"{v:>7.1f}us"


def matrix_success(rows, mode, loss_pct):
    """Return dict[(R,T)] -> (n_ok, n_observed)"""
    m = {}
    for r in rows:
        if r["mode"] != mode:
            continue
        if mode == "netem" and r["loss_pct"] != loss_pct:
            continue
        m[(r["retry_cnt"], r["qp_timeout"])] = (r["n_ok"], r["n_observed"])
    return m


def print_success_matrix(rows, mode, loss_pct, retries, timeouts, label):
    print()
    print(f"--- {label} (success %) ---")
    header = f"{'retry\\timeout':<14}"
    for T in timeouts:
        header += f" | {T:>2} (~{timeout_ms(T):>7.2f}ms)"
    print(header)
    print("-" * len(header))

    m = matrix_success(rows, mode, loss_pct)
    for R in retries:
        line = f"retry_cnt={R:<3}"
        for T in timeouts:
            ok, total = m.get((R, T), (0, 0))
            line += f" | {fmt_pct(ok, total):>16}"
        print(line)


def print_kill_latency_matrix(rows, retries, timeouts):
    print()
    print("--- Persistent fault (process kill): mean detection latency ---")
    header = f"{'retry\\timeout':<14}"
    for T in timeouts:
        header += f" | {T:>2} (~{timeout_ms(T):>7.2f}ms)"
    print(header)
    print("-" * len(header))

    by_key = {}
    for r in rows:
        if r["mode"] == "kill":
            by_key[(r["retry_cnt"], r["qp_timeout"])] = r

    for R in retries:
        line = f"retry_cnt={R:<3}"
        for T in timeouts:
            r = by_key.get((R, T))
            if r is None or r["n_ok"] == 0:
                line += f" | {'   --   ':>16}"
            else:
                line += f" | {fmt_us(r['mean_us']):>16}"
        print(line)


def print_error_breakdown(rows, retries, timeouts, loss_values):
    print()
    print("--- Error code distribution per (mode, R, T, loss) ---")
    header = (f"{'mode':<7} {'R':>2} {'T':>2} {'loss%':>5} "
              f"{'ok':>5} {'retry':>5} {'rnr':>5} {'flush':>5} {'other':>5}")
    print(header)
    print("-" * len(header))
    for r in rows:
        line = (f"{r['mode']:<7} {r['retry_cnt']:>2} {r['qp_timeout']:>2} "
                f"{r.get('loss_pct', 0):>5} "
                f"{r['n_ok']:>5} {r['n_retry_exc']:>5} "
                f"{r['n_rnr_retry_exc']:>5} {r['n_wr_flush']:>5} "
                f"{r['n_other']:>5}")
        print(line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", help="Combined exp4 CSV")
    parser.add_argument("--breakdown", action="store_true",
                        help="Print full per-row error breakdown")
    args = parser.parse_args()

    rows = load(args.csv)
    if not rows:
        print("ERROR: No data", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(rows)} configurations from {args.csv}")

    retries  = sorted(set(r["retry_cnt"] for r in rows))
    timeouts = sorted(set(r["qp_timeout"] for r in rows))
    losses   = sorted(set(r["loss_pct"] for r in rows
                          if r["mode"] == "netem" and r["loss_pct"] > 0))

    # Baseline: netem with loss=0
    baseline_rows = [r for r in rows
                     if r["mode"] == "netem" and r.get("loss_pct", 0) == 0]
    if baseline_rows:
        print_success_matrix(rows, "netem", 0, retries, timeouts,
                             "BASELINE (no fault, loss=0%)")

    # Per-loss matrices
    for L in losses:
        print_success_matrix(rows, "netem", L, retries, timeouts,
                             f"TRANSIENT (netem loss={L}%)")

    # Kill matrix (latency)
    if any(r["mode"] == "kill" for r in rows):
        print_kill_latency_matrix(rows, retries, timeouts)

    if args.breakdown:
        print_error_breakdown(rows, retries, timeouts, losses)


if __name__ == "__main__":
    main()
