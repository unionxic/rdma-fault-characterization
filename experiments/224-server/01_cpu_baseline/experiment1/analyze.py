#!/usr/bin/env python3
"""
analyze.py - Parse CSV results and compute summary statistics

Part of: GPU-Initiated RDMA Fault Recovery Research
Experiment 1: CPU-mediated fault detection baseline latency

Reads the CSV output from the client binary and produces:
  1. Summary statistics per scenario (mean, median, stddev, p99, min, max)
  2. A text table for inclusion in the paper
  3. Optional: histogram data for plotting

Usage:
  python3 analyze.py <results.csv> [--plot]
"""

import sys
import csv
import math
import argparse
from collections import defaultdict


def read_csv(filepath):
    """Read measurement CSV and return list of dicts."""
    rows = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields
            for key in ['iteration', 't_inject_request_ns', 't_ack_ns',
                        'tcp_rtt_ns', 't_error_cqe_ns', 'detection_latency_ns',
                        'error_status']:
                if key in row and row[key]:
                    row[key] = int(row[key])
            rows.append(row)
    return rows


def compute_stats(values):
    """Compute summary statistics for a list of numeric values."""
    if not values:
        return None

    n = len(values)
    sorted_vals = sorted(values)

    mean = sum(values) / n
    if n > 1:
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)
        stddev = math.sqrt(variance)
    else:
        stddev = 0.0

    median = sorted_vals[n // 2]
    p99_idx = min(int(n * 0.99), n - 1)
    p99 = sorted_vals[p99_idx]
    p1_idx = max(int(n * 0.01), 0)
    p1 = sorted_vals[p1_idx]

    return {
        'n': n,
        'mean': mean,
        'stddev': stddev,
        'median': median,
        'min': sorted_vals[0],
        'max': sorted_vals[-1],
        'p1': p1,
        'p99': p99,
    }


def ns_to_us(ns):
    """Convert nanoseconds to microseconds."""
    return ns / 1000.0


def format_us(ns_val):
    """Format nanosecond value as microsecond string."""
    us = ns_to_us(ns_val)
    if us < 1.0:
        return f"{us:.3f}"
    elif us < 100.0:
        return f"{us:.1f}"
    elif us < 10000.0:
        return f"{us:.0f}"
    else:
        return f"{us/1000:.1f}ms"


def print_summary(scenarios):
    """Print formatted summary table."""

    print()
    print("=" * 78)
    print("  RDMA Fault Detection Latency - Detailed Results")
    print("=" * 78)
    print()

    scenario_names = {
        'QP_TO_ERR':     'A: QP -> ERR',
        'KILL_PROCESS':  'B: Process Kill',
        'LINK_DOWN':     'C: Link Down',
    }

    # Summary table
    header = f"{'Scenario':<18} {'N':>4} {'Median':>10} {'Mean':>10} {'StdDev':>10} {'P99':>10} {'Min':>10} {'Max':>10}"
    print(header)
    print("-" * len(header))

    for scenario_key in ['QP_TO_ERR', 'KILL_PROCESS', 'LINK_DOWN']:
        if scenario_key not in scenarios:
            continue

        stats = scenarios[scenario_key]
        if stats is None:
            continue

        name = scenario_names.get(scenario_key, scenario_key)
        print(f"{name:<18} {stats['n']:>4} "
              f"{format_us(stats['median']):>9}us "
              f"{format_us(stats['mean']):>9}us "
              f"{format_us(stats['stddev']):>9}us "
              f"{format_us(stats['p99']):>9}us "
              f"{format_us(stats['min']):>9}us "
              f"{format_us(stats['max']):>9}us")

    print()

    # LaTeX table for paper
    print("--- LaTeX table (copy-paste into paper) ---")
    print()
    print(r"\begin{table}[t]")
    print(r"\centering")
    print(r"\caption{RDMA fault detection latency via CPU-mediated CQ polling}")
    print(r"\label{tab:detection-latency}")
    print(r"\begin{tabular}{lrrrrr}")
    print(r"\toprule")
    print(r"Fault Scenario & N & Median ($\mu$s) & Mean ($\mu$s) & P99 ($\mu$s) & Max ($\mu$s) \\")
    print(r"\midrule")

    for scenario_key in ['QP_TO_ERR', 'KILL_PROCESS', 'LINK_DOWN']:
        if scenario_key not in scenarios:
            continue
        stats = scenarios[scenario_key]
        if stats is None:
            continue
        name = scenario_names.get(scenario_key, scenario_key)
        print(f"{name} & {stats['n']} & "
              f"{ns_to_us(stats['median']):.1f} & "
              f"{ns_to_us(stats['mean']):.1f} & "
              f"{ns_to_us(stats['p99']):.1f} & "
              f"{ns_to_us(stats['max']):.1f} \\\\")

    print(r"\bottomrule")
    print(r"\end{tabular}")
    print(r"\end{table}")
    print()

    # Error status distribution
    print("--- Error status codes observed ---")
    return scenarios


def print_error_distribution(rows):
    """Print distribution of WC error status codes."""
    from collections import Counter

    # ibv_wc_status codes (subset relevant to our experiment)
    status_names = {
        0:  'IBV_WC_SUCCESS',
        1:  'IBV_WC_LOC_LEN_ERR',
        2:  'IBV_WC_LOC_QP_OP_ERR',
        3:  'IBV_WC_LOC_EEC_OP_ERR',
        4:  'IBV_WC_LOC_PROT_ERR',
        5:  'IBV_WC_WR_FLUSH_ERR',
        6:  'IBV_WC_MW_BIND_ERR',
        7:  'IBV_WC_BAD_RESP_ERR',
        8:  'IBV_WC_LOC_ACCESS_ERR',
        9:  'IBV_WC_REM_INV_REQ_ERR',
        10: 'IBV_WC_REM_ACCESS_ERR',
        11: 'IBV_WC_REM_OP_ERR',
        12: 'IBV_WC_RETRY_EXC_ERR',
        13: 'IBV_WC_RNR_RETRY_EXC_ERR',
        14: 'IBV_WC_LOC_RDD_VIOL_ERR',
        15: 'IBV_WC_REM_INV_RD_REQ_ERR',
        16: 'IBV_WC_REM_ABORT_ERR',
        17: 'IBV_WC_INV_EECN_ERR',
        18: 'IBV_WC_INV_EEC_STATE_ERR',
        19: 'IBV_WC_FATAL_ERR',
        20: 'IBV_WC_RESP_TIMEOUT_ERR',
        21: 'IBV_WC_GENERAL_ERR',
    }

    by_scenario = defaultdict(list)
    for row in rows:
        by_scenario[row['scenario']].append(row.get('error_status', -1))

    for scenario, statuses in sorted(by_scenario.items()):
        counter = Counter(statuses)
        print(f"\n  {scenario}:")
        for status, count in counter.most_common():
            name = status_names.get(status, f'UNKNOWN({status})')
            print(f"    {name}: {count}")


def write_histogram_data(scenarios_data, output_prefix):
    """Write per-scenario histogram data for plotting."""
    for scenario, values in scenarios_data.items():
        if not values:
            continue
        fname = f"{output_prefix}_{scenario.lower()}_hist.csv"
        with open(fname, 'w') as f:
            f.write("detection_latency_us\n")
            for v in sorted(values):
                f.write(f"{ns_to_us(v):.3f}\n")
        print(f"  Histogram data: {fname}")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze RDMA fault detection latency results')
    parser.add_argument('csv_file', help='Input CSV file from client')
    parser.add_argument('--plot', action='store_true',
                        help='Generate histogram data files for plotting')
    args = parser.parse_args()

    rows = read_csv(args.csv_file)
    if not rows:
        print("ERROR: No data rows found in CSV", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(rows)} measurements from {args.csv_file}")

    # Group by scenario
    scenario_values = defaultdict(list)
    for row in rows:
        scenario = row['scenario']
        latency = row.get('detection_latency_ns', 0)
        if latency > 0:
            scenario_values[scenario].append(latency)

    # Compute stats per scenario
    scenario_stats = {}
    for scenario, values in scenario_values.items():
        scenario_stats[scenario] = compute_stats(values)

    # Print summary
    print_summary(scenario_stats)

    # Print error distribution
    print_error_distribution(rows)

    # TCP RTT statistics (to validate timing methodology)
    tcp_rtts = [row['tcp_rtt_ns'] for row in rows if row.get('tcp_rtt_ns', 0) > 0]
    if tcp_rtts:
        rtt_stats = compute_stats(tcp_rtts)
        print(f"\n--- TCP control channel RTT ---")
        print(f"  N={rtt_stats['n']}, median={ns_to_us(rtt_stats['median']):.1f} us, "
              f"mean={ns_to_us(rtt_stats['mean']):.1f} us, "
              f"p99={ns_to_us(rtt_stats['p99']):.1f} us")
        print(f"  (This is subtracted/2 from detection latency measurement)")

    # Optional: histogram data
    if args.plot:
        print("\n--- Histogram data ---")
        output_prefix = args.csv_file.rsplit('.', 1)[0]
        write_histogram_data(scenario_values, output_prefix)

    print()


if __name__ == '__main__':
    main()
