#!/usr/bin/env python3
"""analyze.py - per-attempt timeline of RETRY_EXC detection from ackt trials + counter events.

usage: analyze.py <dir> [<dir> ...] [--attempts out.csv] [--md out.md]

Each <dir> holds trials.csv and events.csv written by ackt (scripts/run_cpu.sh).
Per trial, from the counter-change events (times relative to t0 = post of the faulted WRITE,
event time = midpoint of its [lo, hi] bracket, bracket width reported):
  adp   = increments of hw_counters/roce_adp_retrans     (adaptive retransmissions)
  lat   = increments of hw_counters/local_ack_timeout_err (ACK timeouts of the regular timer)
  xmit  = increments of counters/port_xmit_packets that are NOT within +-1 ms of a
          port_rcv_packets increment (background traffic on this port comes in xmit+rcv
          pairs; our retransmissions get no answer because the responder QP is in ERR)
Derived per trial: n_adp, n_lat, t of last adp, t of first lat, regular interval (median
lat-to-lat gap), final lat vs completion time, own retransmissions.
"""
import csv
import statistics as st
import sys
from collections import defaultdict


def tag_runs(rows):
    """Each ackt invocation appends one contiguous block per (label, T, R) to trials.csv and to
    events.csv. A cell that was run twice (e.g. on/14/0 in holds A2 and A3) reuses trial numbers,
    so a run index is derived from the order: a new run starts when the key reappears after other
    rows, or when the trial number goes down."""
    last_key, last_trial, runs = None, {}, defaultdict(int)
    for r in rows:
        k = (r["label"], r["T"], r["R"])
        t = int(r["trial"])
        if k != last_key and k in last_trial or (k in last_trial and t < last_trial[k]):
            runs[k] += 1
        r["run"] = str(runs[k])
        last_trial[k] = t
        last_key = k
    return rows


def with_runs(rows):
    """Files written by ackt >= the run_id version carry the process's run_id; older files get a
    run index from tag_runs()."""
    if rows and "run_id" in rows[0]:
        for r in rows:
            r["run"] = r["run_id"]
        return rows
    return tag_runs(rows)


def load(d):
    trials = with_runs(list(csv.DictReader(open(f"{d}/trials.csv"))))
    ev = defaultdict(list)
    try:
        for r in with_runs(list(csv.DictReader(open(f"{d}/events.csv")))):
            ev[(r["label"], r["T"], r["R"], r["run"], r["trial"])].append(r)
    except FileNotFoundError:
        pass
    return trials, ev


def expand(evs, name, lo_lim=None, hi_lim=None):
    out = []
    for e in evs:
        if e["counter"] != name:
            continue
        k = int(e["new"]) - int(e["old"])
        t = float(e["mid_us"]) / 1000.0
        w = (float(e["hi_us"]) - float(e["lo_us"])) / 1000.0
        if lo_lim is not None and t < lo_lim:
            continue
        if hi_lim is not None and t > hi_lim:
            continue
        out += [(t, w, k)] * max(k, 0)
    return sorted(out)


def med(x):
    return st.median(x) if x else float("nan")


def fmt(x, nd=1):
    return "-" if x is None or x != x else f"{x:.{nd}f}"


def per_trial(tr, evs):
    det = float(tr["detect_ns"]) / 1e6 if tr["detect_ns"] != "-1" else None
    hi = (det + 50.0) if det is not None else None
    adp = expand(evs, "roce_adp_retrans", 0.0, hi)
    lat = expand(evs, "local_ack_timeout_err", 0.0, hi)
    rcv = [t for t, _, _ in expand(evs, "port_rcv_packets", -1e9, hi)]
    xm = [(t, w) for t, w, _ in expand(evs, "port_xmit_packets", -1e9, hi)]
    own = [t for t, w in xm if t >= -1.0 and not any(abs(t - r) <= 1.0 for r in rcv)]
    bg_pairs = sum(1 for t, w in xm if t >= 0 and any(abs(t - r) <= 1.0 for r in rcv))
    lat_t = [t for t, _, _ in lat]
    adp_t = [t for t, _, _ in adp]
    gaps = [b - a for a, b in zip(lat_t, lat_t[1:])]
    width = [w for _, w, _ in adp + lat]
    return {
        "label": tr["label"], "T": int(tr["T"]), "R": int(tr["R"]), "trial": int(tr["trial"]), "run": int(tr["run"]),
        "nominal_ms": float(tr["nominal_us"]) / 1000.0,
        "detect_ms": det, "status": tr["status"], "vendor": tr["vendor_err"],
        "d_lat": int(tr["d_local_ack_timeout_err"]) if "d_local_ack_timeout_err" in tr else None,
        "d_adp": int(tr["d_roce_adp_retrans"]) if "d_roce_adp_retrans" in tr else None,
        "bg_lat": int(tr.get("bg_local_ack_timeout_err", 0) or 0),
        "bg_adp": int(tr.get("bg_roce_adp_retrans", 0) or 0),
        "sampler": tr["sampler"], "max_round_ms": float(tr["max_round_us"]) / 1000.0,
        "n_adp": len(adp_t), "n_lat": len(lat_t),
        "adp_times": adp_t, "lat_times": lat_t, "own_xmit": own, "bg_pairs": bg_pairs,
        "t_last_adp": adp_t[-1] if adp_t else None,
        "t_first_lat": lat_t[0] if lat_t else None,
        "gap_adp_to_lat": (lat_t[0] - adp_t[-1]) if (adp_t and lat_t) else None,
        "lat_gap_med": med(gaps) if gaps else None,
        "lat_gap_min": min(gaps) if gaps else None, "lat_gap_max": max(gaps) if gaps else None,
        "final_lat_minus_det": (lat_t[-1] - det) if (lat_t and det is not None) else None,
        "max_bracket_ms": max(width) if width else None,
    }


def main():
    args = sys.argv[1:]
    att_out = md_out = None
    dirs = []
    i = 0
    while i < len(args):
        if args[i] == "--attempts":
            att_out = args[i + 1]; i += 2
        elif args[i] == "--md":
            md_out = args[i + 1]; i += 2
        else:
            dirs.append(args[i]); i += 1
    rows = []
    for d in dirs:
        trials, ev = load(d)
        for tr in trials:
            rows.append(per_trial(tr, ev[(tr["label"], tr["T"], tr["R"], tr["run"], tr["trial"])]))
    if att_out:
        with open(att_out, "w", newline="") as f:
            cols = ["label", "T", "R", "run", "trial", "nominal_ms", "detect_ms", "status", "vendor", "sampler",
                    "d_lat", "d_adp", "bg_lat", "bg_adp", "n_adp", "n_lat", "t_last_adp", "t_first_lat",
                    "gap_adp_to_lat", "lat_gap_med", "lat_gap_min", "lat_gap_max", "final_lat_minus_det",
                    "n_own_xmit", "bg_pairs", "max_bracket_ms", "max_round_ms", "adp_times_ms", "lat_times_ms",
                    "own_xmit_ms"]
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow([r["label"], r["T"], r["R"], r["run"], r["trial"], fmt(r["nominal_ms"], 3), fmt(r["detect_ms"], 3),
                            r["status"], r["vendor"], r["sampler"], r["d_lat"], r["d_adp"], r["bg_lat"], r["bg_adp"],
                            r["n_adp"], r["n_lat"], fmt(r["t_last_adp"], 2), fmt(r["t_first_lat"], 2),
                            fmt(r["gap_adp_to_lat"], 2), fmt(r["lat_gap_med"], 2), fmt(r["lat_gap_min"], 2),
                            fmt(r["lat_gap_max"], 2), fmt(r["final_lat_minus_det"], 2), len(r["own_xmit"]),
                            r["bg_pairs"], fmt(r["max_bracket_ms"], 2), fmt(r["max_round_ms"], 2),
                            " ".join(f"{t:.2f}" for t in r["adp_times"]),
                            " ".join(f"{t:.2f}" for t in r["lat_times"]),
                            " ".join(f"{t:.2f}" for t in r["own_xmit"])])
    # summary per cell
    cells = defaultdict(list)
    for r in rows:
        cells[(r["label"], r["T"], r["R"])].append(r)
    lines = ["| label | T | R | nominal 4.096us*2^T (ms) | n | RETRY_EXC | detect median [min-max] (ms) | mean (ms) | "
             "n_adp med [range] | t last adp (ms) | n_lat med [range] | first lat (ms) | lat-lat gap median [min-max] (ms) | "
             "gap / nominal | final lat - CQE (ms) | own xmit med | bg timeout ctr in quiet window |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key in sorted(cells, key=lambda k: (k[0], k[1], k[2])):
        rs = cells[key]
        det = [r["detect_ms"] for r in rs if r["detect_ms"] is not None]
        ok = sum(1 for r in rs if r["status"] == "12")
        na = [r["n_adp"] for r in rs]
        nl = [r["n_lat"] for r in rs]
        tla = [r["t_last_adp"] for r in rs if r["t_last_adp"] is not None]
        fl = [r["t_first_lat"] for r in rs if r["t_first_lat"] is not None]
        gaps = [g for r in rs for g in [b - a for a, b in zip(r["lat_times"], r["lat_times"][1:])]]
        fd = [r["final_lat_minus_det"] for r in rs if r["final_lat_minus_det"] is not None]
        ox = [len(r["own_xmit"]) for r in rs]
        bg = sum(r["bg_lat"] + r["bg_adp"] for r in rs)
        nom = rs[0]["nominal_ms"]
        gm = med(gaps) if gaps else float("nan")
        lines.append(
            f"| {key[0]} | {key[1]} | {key[2]} | {nom:.3f} | {len(rs)} | {ok}/{len(rs)} | "
            f"{fmt(med(det), 1)} [{fmt(min(det) if det else None, 1)}-{fmt(max(det) if det else None, 1)}] | "
            f"{fmt(st.mean(det) if det else None, 1)} | {med(na):g} [{min(na)}-{max(na)}] | {fmt(med(tla), 1)} | "
            f"{med(nl):g} [{min(nl)}-{max(nl)}] | {fmt(med(fl), 1)} | "
            f"{fmt(gm, 1)} [{fmt(min(gaps) if gaps else None, 1)}-{fmt(max(gaps) if gaps else None, 1)}] | "
            f"{fmt(gm / nom if gaps else None, 3)} | {fmt(med(fd), 2)} | {med(ox):g} | {bg} |")
    txt = "\n".join(lines)
    print(txt)
    if md_out:
        open(md_out, "w").write(txt + "\n")


if __name__ == "__main__":
    main()
