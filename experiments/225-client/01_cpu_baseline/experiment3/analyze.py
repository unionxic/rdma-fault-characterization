#!/usr/bin/env python3
"""
analyze.py - Experiment 3: QP Recovery Overhead Analysis

Reads the client CSV and produces per-stage statistics for:
  detection, drain, T1 (ERR->RESET), T2 (RESET->INIT), coord1,
  T3 (INIT->RTR), T4 (RTR->RTS), coord2, T5 (write->CQE),
  total_local (T1+T2+T3+T4+T5), total_with_coord.

Usage:
  python3 analyze.py <results.csv> [--latex]
"""

import sys
import csv
import math
import argparse


STAGE_FIELDS = [
    ("detection_ns",         "Detection",           True),
    ("drain_ns",             "Drain flush CQEs",    True),
    ("T1_ns",                "T1: ERR->RESET",      False),
    ("T2_ns",                "T2: RESET->INIT",     False),
    ("coord1_ns",            "coord1 (TCP barrier)", True),
    ("T3_ns",                "T3: INIT->RTR",       False),
    ("T4_ns",                "T4: RTR->RTS",        False),
    ("coord2_ns",            "coord2 (TCP barrier)", True),
    ("T5_ns",                "T5: write->CQE",      False),
    ("total_local_ns",       "Local sum (T1..T5)",  False),
    ("total_with_coord_ns",  "Total w/ coord",      False),
]


def read_csv(path):
    rows = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for k, v in row.items():
                if v == "":
                    continue
                try:
                    row[k] = int(v)
                except ValueError:
                    pass
            rows.append(row)
    return rows


def stats(values):
    if not values:
        return None
    n = len(values)
    s = sorted(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / (n - 1) if n > 1 else 0.0
    return dict(
        n=n,
        mean=mean,
        stddev=math.sqrt(variance),
        median=s[n // 2],
        p99=s[min(int(n * 0.99), n - 1)],
        min=s[0],
        max=s[-1],
    )


def fmt_us(ns):
    return ns / 1000.0


def fmt_ms(ns):
    return ns / 1_000_000.0


def print_stage_table(rows):
    print()
    print("=" * 100)
    print("  Experiment 3: Per-Stage Recovery Overhead")
    print("=" * 100)

    header = (f"{'Stage':<26} {'N':>4} {'Mean (us)':>12} {'Std (us)':>11} "
              f"{'P50 (us)':>11} {'P99 (us)':>11} {'Min (us)':>10} {'Max (us)':>10}")
    print(header)
    print("-" * len(header))

    for field, label, _aux in STAGE_FIELDS:
        vals = [r[field] for r in rows if isinstance(r.get(field), int)]
        st = stats(vals)
        if not st:
            print(f"{label:<26} {'0':>4} {'N/A':>12}")
            continue
        print(f"{label:<26} {st['n']:>4} "
              f"{fmt_us(st['mean']):>12.2f} {fmt_us(st['stddev']):>11.2f} "
              f"{fmt_us(st['median']):>11.2f} {fmt_us(st['p99']):>11.2f} "
              f"{fmt_us(st['min']):>10.2f} {fmt_us(st['max']):>10.2f}")
    print()


def print_breakdown(rows):
    """Show each transition's contribution as a fraction of total_local."""
    print("=" * 100)
    print("  Recovery Stage Contribution (% of Local Recovery Time)")
    print("=" * 100)
    print()

    totals = [r["total_local_ns"] for r in rows
              if isinstance(r.get("total_local_ns"), int) and r["total_local_ns"] > 0]
    if not totals:
        print("  (no valid rows)")
        return

    total_sum = sum(totals)
    mean_total = total_sum / len(totals)

    print(f"  Mean total_local = {fmt_us(mean_total):.2f} us "
          f"(N={len(totals)})")
    print()

    per_stage = {}
    for field, label, _ in STAGE_FIELDS:
        if field in ("detection_ns", "drain_ns", "coord1_ns", "coord2_ns",
                     "total_local_ns", "total_with_coord_ns"):
            continue
        vals = [r[field] for r in rows if isinstance(r.get(field), int)]
        per_stage[label] = sum(vals) / len(vals) if vals else 0

    header = f"{'Stage':<22} {'Mean (us)':>12} {'% of local':>12}"
    print(header)
    print("-" * len(header))

    stage_sum = sum(per_stage.values())
    for label, val in per_stage.items():
        pct = 100.0 * val / stage_sum if stage_sum > 0 else 0
        print(f"{label:<22} {fmt_us(val):>12.2f} {pct:>11.1f}%")

    # coord separately
    for field, label in [("coord1_ns", "coord1"), ("coord2_ns", "coord2")]:
        vals = [r[field] for r in rows if isinstance(r.get(field), int)]
        if vals:
            mean = sum(vals) / len(vals)
            print(f"{'  + ' + label:<22} {fmt_us(mean):>12.2f} {'(additional)':>12}")
    print()


def print_latex_table(rows):
    print("--- LaTeX table ---")
    print()
    print(r"\begin{table}[t]")
    print(r"\centering")
    print(r"\caption{QP recovery overhead broken down by ibv\_modify\_qp stage. "
          r"All measurements are in microseconds over N iterations on ConnectX-5 "
          r"(mlx5\_0, RoCEv2). In-place transitions (same QPN, same MR); no "
          r"destroy/create. Coordination rows reflect TCP round-trips synchronizing "
          r"the two endpoints at post-INIT and post-RTS barriers.}")
    print(r"\label{tab:qp-recovery-breakdown}")
    print(r"\begin{tabular}{lrrrrr}")
    print(r"\toprule")
    print(r"Stage & N & Mean ($\mu s$) & Std ($\mu s$) & P50 ($\mu s$) & P99 ($\mu s$) \\")
    print(r"\midrule")

    for field, label, _aux in STAGE_FIELDS:
        vals = [r[field] for r in rows if isinstance(r.get(field), int)]
        st = stats(vals)
        if not st:
            continue
        safe_label = label.replace("->", r"$\to$").replace("_", r"\_")
        print(f"{safe_label} & {st['n']} & "
              f"{fmt_us(st['mean']):.2f} & "
              f"{fmt_us(st['stddev']):.2f} & "
              f"{fmt_us(st['median']):.2f} & "
              f"{fmt_us(st['p99']):.2f} \\\\")

    print(r"\bottomrule")
    print(r"\end{tabular}")
    print(r"\end{table}")
    print()


def print_error_distribution(rows):
    from collections import Counter

    names = {
        5:  "IBV_WC_WR_FLUSH_ERR",
        12: "IBV_WC_RETRY_EXC_ERR",
        13: "IBV_WC_RNR_RETRY_EXC_ERR",
    }
    statuses = [r.get("detect_error_status") for r in rows
                if isinstance(r.get("detect_error_status"), int)]
    if not statuses:
        return
    print("--- First-CQE error status distribution ---")
    for status, cnt in Counter(statuses).most_common():
        print(f"  {names.get(status, f'status={status}')}: {cnt}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Analyze Experiment 3 recovery CSV")
    parser.add_argument("csv_file", help="Client recovery CSV")
    parser.add_argument("--latex", action="store_true", help="Emit LaTeX table")
    args = parser.parse_args()

    rows = read_csv(args.csv_file)
    if not rows:
        print("ERROR: No data", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(rows)} rows from {args.csv_file}")
    print_stage_table(rows)
    print_breakdown(rows)
    print_error_distribution(rows)
    if args.latex:
        print_latex_table(rows)


if __name__ == "__main__":
    main()
