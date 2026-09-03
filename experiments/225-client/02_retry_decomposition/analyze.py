#!/usr/bin/env python3
"""
analyze.py - 3.7s Retry Decomposition Analysis

Reads per-iteration raw CSV and produces:
  1. Detection latency table per (retry_cnt, timeout)
  2. Delta table: cost of each additional retry
  3. Backoff pattern identification (linear vs exponential)
  4. Theoretical model fit (IBA fixed-timeout vs exponential backoff)

Raw CSV schema:
  retry_cnt, qp_timeout, timeout_ms, iteration, detection_ms, status
"""

import sys
import csv
import argparse
import math
from collections import defaultdict


def load_raw(path):
    """Load per-iteration raw data, return list of dicts."""
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append({
                "retry_cnt": int(r["retry_cnt"]),
                "qp_timeout": int(r["qp_timeout"]),
                "timeout_ms": float(r["timeout_ms"]),
                "iteration": int(r["iteration"]),
                "detection_ms": float(r["detection_ms"]),
                "status": int(r["status"]),
            })
    return rows


def group_by_config(rows):
    """Group rows by (retry_cnt, qp_timeout) → list of detection_ms."""
    groups = defaultdict(list)
    for r in rows:
        key = (r["retry_cnt"], r["qp_timeout"])
        groups[key].append(r["detection_ms"])
    return groups


def stats(values):
    """Compute mean, std, median, min, max."""
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": 0, "std": 0, "median": 0, "min": 0, "max": 0}
    s = sorted(values)
    mean = sum(s) / n
    var = sum((x - mean) ** 2 for x in s) / n if n > 1 else 0
    return {
        "n": n,
        "mean": mean,
        "std": var ** 0.5,
        "median": s[n // 2],
        "min": s[0],
        "max": s[-1],
    }


def fmt_ms(v):
    if v >= 1000:
        return f"{v/1000:.2f}s"
    return f"{v:.1f}ms"


def print_detection_table(groups, timeout, retry_values):
    """Print detection latency table for one timeout value."""
    t_ms = 4.096 * (2 ** timeout) / 1000.0
    print(f"\n{'='*70}")
    print(f"Detection Latency — timeout={timeout} ({t_ms:.2f}ms)")
    print(f"{'='*70}")
    print(f"{'retry_cnt':>9} | {'N':>3} | {'Mean':>10} | {'StdDev':>9} | "
          f"{'Median':>10} | {'Min':>10} | {'Max':>10}")
    print("-" * 78)

    means = {}
    for R in retry_values:
        key = (R, timeout)
        if key not in groups:
            print(f"{R:>9} | {'—':>3} |")
            continue
        s = stats(groups[key])
        means[R] = s["mean"]
        print(f"{R:>9} | {s['n']:>3} | {fmt_ms(s['mean']):>10} | "
              f"{fmt_ms(s['std']):>9} | {fmt_ms(s['median']):>10} | "
              f"{fmt_ms(s['min']):>10} | {fmt_ms(s['max']):>10}")
    return means


def print_delta_table(means_by_timeout, retry_values, timeouts):
    """Print delta analysis — per-retry cost increment."""
    print(f"\n{'='*70}")
    print("Per-Retry Cost (Delta = detection[R] - detection[R-1])")
    print(f"{'='*70}")

    header = f"{'R-1→R':>7}"
    for T in timeouts:
        t_ms = 4.096 * (2 ** T) / 1000.0
        header += f" | {'Delta T=' + str(T):>14}"
    header += f" | {'Ratio':>7}"
    print(header)
    print("-" * len(header))

    deltas_by_timeout = {}
    for T in timeouts:
        means = means_by_timeout.get(T, {})
        deltas = []
        for R in retry_values:
            if R == 0:
                continue
            prev = means.get(R - 1)
            curr = means.get(R)
            if prev is not None and curr is not None:
                deltas.append((R, curr - prev))
            else:
                deltas.append((R, None))
        deltas_by_timeout[T] = deltas

    for i, R in enumerate(retry_values):
        if R == 0:
            continue
        line = f"  {R-1}→{R}  "
        prev_delta = None
        for T in timeouts:
            d_list = deltas_by_timeout[T]
            d = d_list[i - 1][1] if i - 1 < len(d_list) else None
            if d is not None:
                line += f" | {fmt_ms(d):>14}"
                if T == timeouts[0]:
                    prev_delta = d
            else:
                line += f" | {'—':>14}"

        if len(timeouts) > 0 and prev_delta is not None:
            d_list = deltas_by_timeout[timeouts[0]]
            if i >= 2:
                prev_d = d_list[i - 2][1]
                if prev_d is not None and prev_d > 0:
                    ratio = prev_delta / prev_d
                    line += f" | {ratio:>6.2f}x"
                else:
                    line += f" | {'—':>7}"
            else:
                line += f" | {'—':>7}"
        else:
            line += f" | {'—':>7}"
        print(line)

    return deltas_by_timeout


def analyze_backoff_pattern(deltas_by_timeout, timeouts):
    """Determine if backoff is linear, exponential, or other."""
    print(f"\n{'='*70}")
    print("Backoff Pattern Analysis")
    print(f"{'='*70}")

    for T in timeouts:
        t_ms = 4.096 * (2 ** T) / 1000.0
        deltas = [d for (_, d) in deltas_by_timeout.get(T, []) if d is not None]
        if len(deltas) < 2:
            print(f"\ntimeout={T} ({t_ms:.2f}ms): insufficient data")
            continue

        ratios = []
        for i in range(1, len(deltas)):
            if deltas[i - 1] > 0:
                ratios.append(deltas[i] / deltas[i - 1])

        mean_delta = sum(deltas) / len(deltas)
        cv = (sum((d - mean_delta) ** 2 for d in deltas) / len(deltas)) ** 0.5 / mean_delta if mean_delta > 0 else 999
        mean_ratio = sum(ratios) / len(ratios) if ratios else 0

        print(f"\ntimeout={T} ({t_ms:.2f}ms):")
        print(f"  Deltas: {', '.join(fmt_ms(d) for d in deltas)}")
        if ratios:
            print(f"  Consecutive ratios: {', '.join(f'{r:.2f}x' for r in ratios)}")
            print(f"  Mean ratio: {mean_ratio:.2f}x")

        if cv < 0.3:
            print(f"  → PATTERN: LINEAR (constant delta ~{fmt_ms(mean_delta)}, CV={cv:.2f})")
            print(f"    Per-retry interval ≈ {fmt_ms(mean_delta)}")
            print(f"    Configured timeout = {t_ms:.2f}ms → effective/configured = {mean_delta/t_ms:.1f}x")
        elif 1.5 < mean_ratio < 2.5 and len(ratios) >= 3:
            print(f"  → PATTERN: EXPONENTIAL BACKOFF (ratio ~{mean_ratio:.2f}x)")
            base = deltas[0]
            print(f"    Base interval ≈ {fmt_ms(base)}, doubling each retry")
        else:
            print(f"  → PATTERN: MIXED/OTHER (CV={cv:.2f}, mean_ratio={mean_ratio:.2f}x)")
            print(f"    Neither purely linear nor exponential")


def print_theoretical_comparison(means_by_timeout, retry_values, timeouts):
    """Compare measured values with IBA theoretical models."""
    print(f"\n{'='*70}")
    print("Theoretical Model Comparison")
    print(f"{'='*70}")

    for T in timeouts:
        t_ms = 4.096 * (2 ** T) / 1000.0
        means = means_by_timeout.get(T, {})
        if 0 not in means:
            continue

        floor = means[0]

        print(f"\ntimeout={T} ({t_ms:.2f}ms), floor (R=0) = {fmt_ms(floor)}")
        print(f"  {'R':>2} | {'Measured':>10} | {'Linear':>10} | {'Err%':>6} | "
              f"{'Exp-backoff':>11} | {'Err%':>6}")
        print("  " + "-" * 66)

        for R in retry_values:
            measured = means.get(R)
            if measured is None:
                continue

            linear = floor + R * t_ms
            if R > 0:
                exp_backoff = floor + t_ms * (2 ** R - 1)
            else:
                exp_backoff = floor

            lin_err = abs(measured - linear) / measured * 100 if measured > 0 else 0
            exp_err = abs(measured - exp_backoff) / measured * 100 if measured > 0 else 0

            print(f"  {R:>2} | {fmt_ms(measured):>10} | {fmt_ms(linear):>10} | "
                  f"{lin_err:>5.1f}% | {fmt_ms(exp_backoff):>11} | {exp_err:>5.1f}%")


def print_latex(means_by_timeout, deltas_by_timeout, retry_values, timeouts):
    """Output LaTeX-ready tables."""
    print(f"\n{'='*70}")
    print("LaTeX Tables")
    print(f"{'='*70}")

    for T in timeouts:
        t_ms = 4.096 * (2 ** T) / 1000.0
        means = means_by_timeout.get(T, {})
        deltas_list = deltas_by_timeout.get(T, [])
        delta_map = {R: d for (R, d) in deltas_list}

        print(f"\n% timeout={T} ({t_ms:.2f}ms)")
        print(r"\begin{tabular}{r r r r}")
        print(r"\toprule")
        print(r"\texttt{retry\_cnt} & Detection (ms) & $\Delta$ (ms) & Ratio \\")
        print(r"\midrule")

        prev_delta = None
        for R in retry_values:
            m = means.get(R)
            d = delta_map.get(R)
            det_str = f"{m:.1f}" if m is not None else "---"
            delta_str = f"{d:.1f}" if d is not None else "---"
            if d is not None and prev_delta is not None and prev_delta > 0:
                ratio_str = f"{d/prev_delta:.2f}$\\times$"
            else:
                ratio_str = "---"
            print(f"  {R} & {det_str} & {delta_str} & {ratio_str} \\\\")
            if d is not None:
                prev_delta = d

        print(r"\bottomrule")
        print(r"\end{tabular}")


def main():
    parser = argparse.ArgumentParser(
        description="3.7s Retry Decomposition Analysis")
    parser.add_argument("csv", help="Raw per-iteration CSV")
    parser.add_argument("--latex", action="store_true",
                        help="Output LaTeX tables")
    args = parser.parse_args()

    rows = load_raw(args.csv)
    if not rows:
        print("ERROR: No data", file=sys.stderr)
        sys.exit(1)

    groups = group_by_config(rows)
    retry_values = sorted(set(r["retry_cnt"] for r in rows))
    timeouts = sorted(set(r["qp_timeout"] for r in rows), reverse=True)

    print(f"Loaded {len(rows)} samples across {len(groups)} configs")
    print(f"retry_cnt: {retry_values}")
    print(f"qp_timeout: {timeouts}")

    means_by_timeout = {}
    for T in timeouts:
        means_by_timeout[T] = print_detection_table(groups, T, retry_values)

    deltas_by_timeout = print_delta_table(means_by_timeout, retry_values, timeouts)
    analyze_backoff_pattern(deltas_by_timeout, timeouts)
    print_theoretical_comparison(means_by_timeout, retry_values, timeouts)

    if args.latex:
        print_latex(means_by_timeout, deltas_by_timeout, retry_values, timeouts)

    print(f"\n{'='*70}")
    print("Summary")
    print(f"{'='*70}")
    for T in timeouts:
        t_ms = 4.096 * (2 ** T) / 1000.0
        means = means_by_timeout.get(T, {})
        if 0 in means and 7 in means:
            total = means[7]
            floor_val = means[0]
            retry_cost = total - floor_val
            print(f"timeout={T} ({t_ms:.2f}ms):")
            print(f"  Total detection (R=7): {fmt_ms(total)}")
            print(f"  Floor (R=0):           {fmt_ms(floor_val)}")
            print(f"  Retry cost (7 retries): {fmt_ms(retry_cost)}")
            print(f"  Per-retry average:     {fmt_ms(retry_cost/7)}")


if __name__ == "__main__":
    main()
