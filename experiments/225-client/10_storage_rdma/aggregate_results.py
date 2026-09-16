#!/usr/bin/env python3
# [한국어 요약] storage_rdma.csv의 트라이얼들을 (scenario, param)별로 묶어
# 평균/표준편차/95% CI/개수를 계산한다. Phase 1 원자료는 그룹당 3~5 트라이얼을
# 갖지만 집계(분산/신뢰구간)가 없어 단일값처럼 읽히던 공백을 메운다. 읽기 전용,
# 측정 의미론은 건드리지 않는다 — 기존 숫자 컬럼을 그대로 요약할 뿐.
#
# aggregate_results.py — collapse the per-trial rows of results/raw/storage_rdma.csv
# into per-(scenario, param) summary statistics (mean, stddev, 95% CI half-width,
# n) for each numeric metric column. Read-only; writes results/aggregated.csv.
#
# The raw CSV records 3-5 trials per (scenario, param) but carries no variance or
# confidence interval, so single-trial and multi-trial results looked alike. This
# adds machine-readable dispersion without changing any measured value.
#
# Usage: python3 aggregate_results.py [raw_csv] [out_csv]
#   defaults: results/raw/storage_rdma.csv -> results/aggregated.csv
import csv
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    HERE, "results", "raw", "storage_rdma.csv")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    HERE, "results", "aggregated.csv")

# Numeric columns worth aggregating across trials. Free-text columns
# (nvme_status_or_errno, counter_deltas, dmesg_signature, notes) are skipped.
METRICS = ["latency_us_p50", "latency_us_p99", "latency_us_max",
           "detect_ms", "valid_prefix_bytes"]

# Student-t 0.975 quantiles for small samples (df = n-1); >=30 -> normal ~1.96.
_T = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
      7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 15: 2.131, 20: 2.086,
      25: 2.060, 29: 2.045}


def t975(df):
    if df <= 0:
        return float("nan")
    if df in _T:
        return _T[df]
    if df >= 30:
        return 1.96
    # nearest tabulated df below (conservative-ish); fine for a CI annotation.
    keys = [k for k in _T if k <= df]
    return _T[max(keys)] if keys else 1.96


def to_float(s):
    if s is None:
        return None
    s = s.strip()
    if s == "" or s.upper().startswith("NA"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def summarize(vals):
    n = len(vals)
    if n == 0:
        return None
    mean = sum(vals) / n
    if n == 1:
        return (n, mean, 0.0, float("nan"))
    var = sum((x - mean) ** 2 for x in vals) / (n - 1)
    sd = math.sqrt(var)
    ci_half = t975(n - 1) * sd / math.sqrt(n)   # 95% CI half-width of the mean
    return (n, mean, sd, ci_half)


def main():
    if not os.path.isfile(RAW):
        raise SystemExit(f"aggregate_results: raw CSV not found: {RAW}")
    groups = defaultdict(lambda: defaultdict(list))  # (sc,param) -> metric -> [floats]
    trials = defaultdict(int)   # (sc,param) -> number of raw rows (trials)
    with open(RAW, newline="") as f:
        for r in csv.DictReader(f):
            key = (r.get("scenario", ""), r.get("param", ""))
            trials[key] += 1
            for m in METRICS:
                v = to_float(r.get(m))
                if v is not None:
                    groups[key][m].append(v)

    if not trials:
        raise SystemExit(f"aggregate_results: no rows parsed from {RAW}")

    header = ["scenario", "param", "n_trials"]
    for m in METRICS:
        header += [f"{m}_n", f"{m}_mean", f"{m}_stddev", f"{m}_ci95_half"]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for key in sorted(trials):   # every (scenario,param), incl. status-only
            sc, param = key
            row = [sc, param, trials[key]]
            for m in METRICS:
                s = summarize(groups[key][m])
                if s is None:
                    row += [0, "", "", ""]
                else:
                    n, mean, sd, ci = s
                    row += [n, f"{mean:.3f}", f"{sd:.3f}",
                            "" if ci != ci else f"{ci:.3f}"]  # ci!=ci -> NaN
            w.writerow(row)
    print(f"wrote {OUT} ({len(groups)} (scenario,param) groups)")


if __name__ == "__main__":
    main()
