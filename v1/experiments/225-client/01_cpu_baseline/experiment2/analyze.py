#!/usr/bin/env python3
"""
analyze.py - Experiment 2: CPU Polling Interval Blind Window Analysis

Reads combined CSV and produces:
  1. Primary table: detection delay by (sleep_interval, fault_type) -- for paper
  2. Secondary analysis: breakdown into HCA-retry vs blind-window component
  3. wakeup_to_detection analysis: near-zero when CQE already in CQ
  4. LaTeX table for the paper

Usage:
  python3 analyze.py <results.csv> [--latex] [--plot]
"""

import sys
import csv
import math
import argparse
from collections import defaultdict


def read_csv(filepath):
    rows = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in ['sleep_us', 'iteration',
                        't_inject_request_ns', 't_ack_ns', 'tcp_rtt_ns',
                        't_wakeup_ns', 't_detected_ns',
                        'detection_delay_ns', 'wakeup_to_detection_ns',
                        'error_status']:
                if key in row and row[key]:
                    try:
                        row[key] = int(row[key])
                    except ValueError:
                        pass
            rows.append(row)
    return rows


def compute_stats(values):
    if not values:
        return None

    n = len(values)
    s = sorted(values)
    mean = sum(values) / n
    if n > 1:
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)
        stddev = math.sqrt(variance)
    else:
        stddev = 0.0

    return {
        'n': n,
        'mean': mean,
        'stddev': stddev,
        'median': s[n // 2],
        'p50': s[n // 2],
        'p99': s[min(int(n * 0.99), n - 1)],
        'min': s[0],
        'max': s[-1],
    }


def ns_to_ms(ns):
    return ns / 1_000_000.0


def ns_to_us(ns):
    return ns / 1_000.0


def format_ms(ns_val, precision=1):
    ms = ns_to_ms(ns_val)
    if ms < 0.1:
        return f"{ns_to_us(ns_val):.0f} us"
    elif ms < 10:
        return f"{ms:.2f}"
    elif ms < 100:
        return f"{ms:.1f}"
    else:
        return f"{ms:,.0f}"


def format_sleep(us_val):
    if us_val == 0:
        return "0 (busy)"
    elif us_val < 1000:
        return f"{us_val} us"
    elif us_val < 1_000_000:
        return f"{us_val // 1000} ms"
    else:
        return f"{us_val // 1_000_000} s"


SCENARIO_LABELS = {
    'QP_TO_ERR': 'QP->ERR',
    'KILL_PROCESS': 'Kill',
    'LINK_DOWN': 'Link Down',
}

SCENARIO_ORDER = ['QP_TO_ERR', 'KILL_PROCESS', 'LINK_DOWN']

SLEEP_ORDER = [0, 1000, 10000, 100000, 1_000_000, 5_000_000, 10_000_000]


def group_data(rows):
    """Group rows by (sleep_us, scenario) -> list of measurement dicts."""
    groups = defaultdict(list)
    for row in rows:
        key = (row['sleep_us'], row['scenario'])
        groups[key].append(row)
    return groups


def print_primary_table(groups):
    """Detection delay table: rows=sleep intervals, cols=fault types."""

    print()
    print("=" * 80)
    print("  Primary Table: Detection Delay (ms) by Sleep Interval and Fault Type")
    print("=" * 80)
    print()

    scenarios_present = []
    for s in SCENARIO_ORDER:
        for key in groups:
            if key[1] == s:
                scenarios_present.append(s)
                break

    header = f"{'Sleep Interval':<16}"
    for s in scenarios_present:
        label = SCENARIO_LABELS.get(s, s)
        header += f" | {label + ' (ms)':>16}"
    print(header)
    print("-" * len(header))

    for sleep_us in SLEEP_ORDER:
        row_str = f"{format_sleep(sleep_us):<16}"
        for s in scenarios_present:
            key = (sleep_us, s)
            if key in groups:
                vals = [r['detection_delay_ns'] for r in groups[key]
                        if r.get('detection_delay_ns', 0) > 0]
                stats = compute_stats(vals)
                if stats:
                    mean_ms = ns_to_ms(stats['mean'])
                    std_ms = ns_to_ms(stats['stddev'])
                    row_str += f" | {mean_ms:>9.1f} +/-{std_ms:>4.0f}"
                else:
                    row_str += f" |         {'N/A':>8}"
            else:
                row_str += f" |              {'--':>4}"
        print(row_str)

    print()


def print_wakeup_analysis(groups):
    """Show wakeup_to_detection breakdown to identify CQE-already-in-CQ cases."""

    print("=" * 80)
    print("  Wakeup-to-Detection Time (ms): Time spent polling after wakeup")
    print("  Near-zero = error CQE was already in CQ when CPU woke up")
    print("=" * 80)
    print()

    scenarios_present = []
    for s in SCENARIO_ORDER:
        for key in groups:
            if key[1] == s:
                scenarios_present.append(s)
                break

    header = f"{'Sleep Interval':<16}"
    for s in scenarios_present:
        label = SCENARIO_LABELS.get(s, s)
        header += f" | {label + ' (ms)':>16}"
    print(header)
    print("-" * len(header))

    for sleep_us in SLEEP_ORDER:
        row_str = f"{format_sleep(sleep_us):<16}"
        for s in scenarios_present:
            key = (sleep_us, s)
            if key in groups:
                vals = [r['wakeup_to_detection_ns'] for r in groups[key]
                        if 'wakeup_to_detection_ns' in r]
                stats = compute_stats(vals)
                if stats:
                    mean_ms = ns_to_ms(stats['mean'])
                    row_str += f" | {mean_ms:>16.2f}"
                else:
                    row_str += f" |         {'N/A':>8}"
            else:
                row_str += f" |              {'--':>4}"
        print(row_str)

    print()


def print_regime_analysis(groups):
    """Classify each (sleep, fault) into HCA-dominated vs sleep-dominated."""

    print("=" * 80)
    print("  Regime Analysis: HCA-retry-dominated vs Sleep-dominated")
    print("  HCA-dominated: sleep < HCA_retry_time, detection ~ 3.7s")
    print("  Sleep-dominated: sleep > HCA_retry_time, detection ~ sleep_time")
    print("=" * 80)
    print()

    header = f"{'Sleep':<12} {'Scenario':<14} {'Detection (ms)':>14} {'wakeup->det (ms)':>17} {'Regime':<18}"
    print(header)
    print("-" * len(header))

    for sleep_us in SLEEP_ORDER:
        for s in SCENARIO_ORDER:
            key = (sleep_us, s)
            if key not in groups:
                continue

            det_vals = [r['detection_delay_ns'] for r in groups[key]
                        if r.get('detection_delay_ns', 0) > 0]
            w2d_vals = [r['wakeup_to_detection_ns'] for r in groups[key]
                        if 'wakeup_to_detection_ns' in r]

            det_stats = compute_stats(det_vals)
            w2d_stats = compute_stats(w2d_vals)

            if not det_stats or not w2d_stats:
                continue

            det_ms = ns_to_ms(det_stats['mean'])
            w2d_ms = ns_to_ms(w2d_stats['mean'])

            # Heuristic: if wakeup_to_detection > 100ms, HCA retry is still
            # in progress when CPU wakes up (HCA-dominated).
            # If wakeup_to_detection < 10ms, CQE was already there (sleep-dominated).
            if w2d_ms > 100:
                regime = "HCA-dominated"
            elif w2d_ms < 10:
                regime = "Sleep-dominated"
            else:
                regime = "Transition"

            label = SCENARIO_LABELS.get(s, s)
            print(f"{format_sleep(sleep_us):<12} {label:<14} {det_ms:>14.1f} {w2d_ms:>17.2f} {regime:<18}")

    print()


def print_latex_table(groups):
    """Generate LaTeX table for the paper."""

    scenarios_present = []
    for s in SCENARIO_ORDER:
        for key in groups:
            if key[1] == s:
                scenarios_present.append(s)
                break

    ncols = 1 + len(scenarios_present)
    col_spec = "l" + "r" * len(scenarios_present)

    print("--- LaTeX table (copy-paste into paper) ---")
    print()
    print(r"\begin{table}[t]")
    print(r"\centering")
    print(r"\caption{Detection delay (ms) as a function of CPU polling interval. "
          r"For short intervals the delay is dominated by the HCA transport retry "
          r"timeout ($\approx$3.7\,s); beyond that threshold the blind window dominates "
          r"and delay $\approx$ sleep time.}")
    print(r"\label{tab:blind-window}")
    print(r"\begin{tabular}{" + col_spec + "}")
    print(r"\toprule")

    header_parts = ["Sleep Interval"]
    for s in scenarios_present:
        header_parts.append(SCENARIO_LABELS.get(s, s) + " (ms)")
    print(" & ".join(header_parts) + r" \\")
    print(r"\midrule")

    for sleep_us in SLEEP_ORDER:
        parts = [format_sleep(sleep_us)]
        for s in scenarios_present:
            key = (sleep_us, s)
            if key in groups:
                vals = [r['detection_delay_ns'] for r in groups[key]
                        if r.get('detection_delay_ns', 0) > 0]
                stats = compute_stats(vals)
                if stats:
                    mean_ms = ns_to_ms(stats['mean'])
                    std_ms = ns_to_ms(stats['stddev'])
                    parts.append(f"{mean_ms:.1f} $\\pm$ {std_ms:.0f}")
                else:
                    parts.append("--")
            else:
                parts.append("--")
        print(" & ".join(parts) + r" \\")

    print(r"\bottomrule")
    print(r"\end{tabular}")
    print(r"\end{table}")
    print()

    # Also produce the wakeup-to-detection table
    print(r"\begin{table}[t]")
    print(r"\centering")
    print(r"\caption{Post-wakeup polling time (ms). Near-zero values indicate the error "
          r"CQE was already in the CQ when the CPU woke, confirming sleep-dominated regime.}")
    print(r"\label{tab:wakeup-to-detection}")
    print(r"\begin{tabular}{" + col_spec + "}")
    print(r"\toprule")

    header_parts = ["Sleep Interval"]
    for s in scenarios_present:
        header_parts.append(SCENARIO_LABELS.get(s, s) + " (ms)")
    print(" & ".join(header_parts) + r" \\")
    print(r"\midrule")

    for sleep_us in SLEEP_ORDER:
        parts = [format_sleep(sleep_us)]
        for s in scenarios_present:
            key = (sleep_us, s)
            if key in groups:
                vals = [r['wakeup_to_detection_ns'] for r in groups[key]
                        if 'wakeup_to_detection_ns' in r]
                stats = compute_stats(vals)
                if stats:
                    mean_ms = ns_to_ms(stats['mean'])
                    parts.append(f"{mean_ms:.2f}")
                else:
                    parts.append("--")
            else:
                parts.append("--")
        print(" & ".join(parts) + r" \\")

    print(r"\bottomrule")
    print(r"\end{tabular}")
    print(r"\end{table}")
    print()


def print_summary_stats(groups):
    """Detailed per-group statistics."""

    print("=" * 80)
    print("  Per-Group Detailed Statistics")
    print("=" * 80)
    print()

    header = (f"{'Sleep':>10} {'Scenario':<14} {'N':>3} "
              f"{'Mean(ms)':>10} {'Std(ms)':>9} {'P50(ms)':>9} "
              f"{'P99(ms)':>9} {'Min(ms)':>9} {'Max(ms)':>9}")
    print(header)
    print("-" * len(header))

    for sleep_us in SLEEP_ORDER:
        for s in SCENARIO_ORDER:
            key = (sleep_us, s)
            if key not in groups:
                continue
            vals = [r['detection_delay_ns'] for r in groups[key]
                    if r.get('detection_delay_ns', 0) > 0]
            stats = compute_stats(vals)
            if not stats:
                continue
            label = SCENARIO_LABELS.get(s, s)
            print(f"{format_sleep(sleep_us):>10} {label:<14} {stats['n']:>3} "
                  f"{ns_to_ms(stats['mean']):>10.1f} "
                  f"{ns_to_ms(stats['stddev']):>9.1f} "
                  f"{ns_to_ms(stats['p50']):>9.1f} "
                  f"{ns_to_ms(stats['p99']):>9.1f} "
                  f"{ns_to_ms(stats['min']):>9.1f} "
                  f"{ns_to_ms(stats['max']):>9.1f}")

    print()


def print_error_distribution(rows):
    """Print WC error status distribution."""
    from collections import Counter

    status_names = {
        5:  'IBV_WC_WR_FLUSH_ERR',
        12: 'IBV_WC_RETRY_EXC_ERR',
        13: 'IBV_WC_RNR_RETRY_EXC_ERR',
    }

    by_scenario = defaultdict(list)
    for row in rows:
        by_scenario[row['scenario']].append(row.get('error_status', -1))

    print("--- Error status codes ---")
    for scenario in SCENARIO_ORDER:
        if scenario not in by_scenario:
            continue
        counter = Counter(by_scenario[scenario])
        print(f"\n  {scenario}:")
        for status, count in counter.most_common():
            name = status_names.get(status, f'status={status}')
            print(f"    {name}: {count}")
    print()


def write_plot_data(groups, output_prefix):
    """Write CSV data suitable for plotting detection_delay vs sleep_time."""

    fname = f"{output_prefix}_plot_data.csv"
    with open(fname, 'w') as f:
        f.write("sleep_us,scenario,mean_detection_ms,stddev_ms,"
                "mean_wakeup_to_det_ms,n\n")
        for sleep_us in SLEEP_ORDER:
            for s in SCENARIO_ORDER:
                key = (sleep_us, s)
                if key not in groups:
                    continue
                det_vals = [r['detection_delay_ns'] for r in groups[key]
                            if r.get('detection_delay_ns', 0) > 0]
                w2d_vals = [r['wakeup_to_detection_ns'] for r in groups[key]
                            if 'wakeup_to_detection_ns' in r]

                det_stats = compute_stats(det_vals)
                w2d_stats = compute_stats(w2d_vals)
                if not det_stats:
                    continue

                w2d_mean = ns_to_ms(w2d_stats['mean']) if w2d_stats else 0

                f.write(f"{sleep_us},{s},"
                        f"{ns_to_ms(det_stats['mean']):.3f},"
                        f"{ns_to_ms(det_stats['stddev']):.3f},"
                        f"{w2d_mean:.3f},"
                        f"{det_stats['n']}\n")

    print(f"  Plot data written to: {fname}")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze Experiment 2: Blind Window results')
    parser.add_argument('csv_file', help='Combined CSV from run_experiment.sh')
    parser.add_argument('--latex', action='store_true',
                        help='Generate LaTeX tables')
    parser.add_argument('--plot', action='store_true',
                        help='Write plot-ready CSV data')
    args = parser.parse_args()

    rows = read_csv(args.csv_file)
    if not rows:
        print("ERROR: No data found in CSV", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(rows)} measurements from {args.csv_file}")

    groups = group_data(rows)
    n_groups = len(groups)
    print(f"Found {n_groups} (sleep, scenario) groups")

    print_primary_table(groups)
    print_wakeup_analysis(groups)
    print_regime_analysis(groups)
    print_summary_stats(groups)
    print_error_distribution(rows)

    if args.latex:
        print_latex_table(groups)

    if args.plot:
        output_prefix = args.csv_file.rsplit('.', 1)[0]
        write_plot_data(groups, output_prefix)

    # TCP RTT
    tcp_rtts = [row['tcp_rtt_ns'] for row in rows
                if isinstance(row.get('tcp_rtt_ns'), int) and row['tcp_rtt_ns'] > 0]
    if tcp_rtts:
        rtt_stats = compute_stats(tcp_rtts)
        print(f"--- TCP control channel RTT ---")
        print(f"  N={rtt_stats['n']}, median={ns_to_us(rtt_stats['median']):.1f} us, "
              f"mean={ns_to_us(rtt_stats['mean']):.1f} us, "
              f"p99={ns_to_us(rtt_stats['p99']):.1f} us")
        print()


if __name__ == '__main__':
    main()
