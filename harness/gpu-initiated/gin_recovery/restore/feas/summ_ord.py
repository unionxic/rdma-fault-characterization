#!/usr/bin/env python3
"""summ_ord.py <resultsdir> - the normal-path comparison of strict and relaxed windows (EXPERIMENT.md 9.15.6) from its raw
files: per receiving node and cell, the valid runs of each arm, their medians, the difference, each arm's range, whether the
two arms are completely separated, and the readings fixed before the run. Writes <resultsdir>/SUMMARY_ORD.txt. Reads only
the kv and meta files that run_ord.sh writes. DRAFT stage, never scored; the forcing itself is decided (9.10.8).
The deciding folder of a node is its latest ord_<node>[_run<k>] folder that holds all 36 runs (each with a meta file);
earlier or incomplete folders are printed for information only (fixed before the run, review K23).
Values: lat4k, lat256k: rank 0's lat_p50_us (one put + signal atomic + flush of one thread, us); bw256k: 16 x 256 KiB / rank 0's lat_p50_us (thread 0's
iteration: 16 puts + signal + flush), in GB/s (1e9 bytes/s). "worse" for strict means a higher latency or a lower bandwidth.
"""
import glob
import os
import re
import sys

R = sys.argv[1] if len(sys.argv) > 1 else "."
OUT = []
CELLS = ("lat4k", "lat256k", "bw256k")
ITERS = {"lat4k": 3000, "lat256k": 3000, "bw256k": 200}
WANT_FLAGS = {"strict": "0x3", "relaxed": "0x1"}


def say(s=""):
    print(s)
    OUT.append(s)


def kv(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, errors="replace"):
        for m in re.finditer(r"(\w+)=(\"[^\"]*\"|\S+)", line):
            d[m.group(1)] = m.group(2).strip('"')
    return d


def median(v):
    v = sorted(v)
    n = len(v)
    return None if n == 0 else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0)


def value(metric, k0):
    p50 = float(k0["lat_p50_us"])
    return p50 if metric != "bw256k" else 16 * 262144 / (p50 * 1e-6) / 1e9


def folders(node):
    base = os.path.join(R, "ord_" + node)
    tail = lambda d: d[len(base) + len("_run"):]
    runs = sorted((d for d in glob.glob(base + "_run*") if tail(d).isdigit()), key=lambda d: int(tail(d)))
    return ([base] if os.path.isdir(base) else []) + runs


def one_folder(d, node):
    """returns {cell: {arm: [values]}}, the invalid runs, and whether RO was on in every run"""
    vals, invalid, ro_missing = {}, [], []
    for mf in sorted(glob.glob(os.path.join(d, "ord_*_meta.txt"))):
        stem = os.path.basename(mf)[:-len("_meta.txt")]
        meta = kv(mf)
        metric, arm = meta.get("metric"), meta.get("arm")
        k0 = kv(os.path.join(d, stem + "_r0.kv"))
        k1 = kv(os.path.join(d, stem + "_r1.kv"))
        why = []
        for name, k in (("r0", k0), ("r1", k1)):
            if not k:
                why.append("%s kv missing" % name)
            elif k.get("exit") != "0":
                why.append("%s exit=%s" % (name, k.get("exit", "none")))
            for bad in ("nccl_error", "cuda_error"):
                if bad in k:
                    why.append("%s %s=%s" % (name, bad, k[bad]))
            if k and k.get("win_flags") != WANT_FLAGS.get(arm):
                why.append("%s win_flags=%s (want %s)" % (name, k.get("win_flags"), WANT_FLAGS.get(arm)))
        if k0 and k0.get("tx_done") != str(ITERS.get(metric)):
            why.append("tx_done=%s" % k0.get("tx_done"))
        if k0 and "lat_p50_us" not in k0:
            why.append("no lat_p50_us")
        if why:
            invalid.append("%s: %s" % (stem, "; ".join(why)))
            continue
        # RO is judged on valid runs only (review K19)
        if k0.get("ro_requested") != "1" or k1.get("ro_requested") != "1":
            ro_missing.append(stem)
            continue
        vals.setdefault(metric, {}).setdefault(arm, []).append(value(metric, k0))
    metas = set(os.path.basename(m)[:-len("_meta.txt")] for m in glob.glob(os.path.join(d, "ord_*_meta.txt")))
    orphans = sorted(set(re.sub(r"_r[01]\.kv$", "", os.path.basename(k)) for k in glob.glob(os.path.join(d, "ord_*_r[01].kv"))) - metas)
    return vals, invalid, ro_missing, orphans, len(metas)


def main():
    any_folder = False
    for node in ("rain", "sunny"):
        fl = folders(node)
        counts = [len(glob.glob(os.path.join(d, "ord_*_meta.txt"))) for d in fl]
        complete = [d for d, n in zip(fl, counts) if n == 36]
        deciding = complete[-1] if complete else None
        for d in fl:
            any_folder = True
            vals, invalid, ro_missing, orphans, nmeta = one_folder(d, node)
            role = "DECIDING" if d == deciding else ("information only: %s" % (
                "incomplete (%d of 36 runs)" % nmeta if nmeta != 36 else "an earlier complete folder"))
            say("== %s (receiving node %s; %s)" % (os.path.basename(d), node, role))
            for o in orphans:
                say("kv without a meta file (not counted): " + o)
            if ro_missing:
                say("ro_requested is not 1 in %d run(s) (%s): NCCL did not ask RO for the relaxed arm; 'not comparable'" % (
                    len(ro_missing), ", ".join(ro_missing[:6])))
            for x in invalid:
                say("invalid (not counted, not replaced): " + x)
            say("cell | unit | strict n, median, range | relaxed n, median, range | strict - relaxed (worse +) | % of relaxed | "
                "separated | reading")
            worth, incomplete, notcmp = False, False, bool(ro_missing)
            for c in CELLS:
                a = vals.get(c, {})
                s, r = a.get("strict", []), a.get("relaxed", [])
                unit = "GB/s" if c == "bw256k" else "us"
                if len(s) < 5 or len(r) < 5:
                    incomplete = True
                    say("%s | %s | %d | %d | - | - | - | incomplete (fewer than 5 valid runs in an arm)" % (c, unit, len(s), len(r)))
                    continue
                ms, mr = median(s), median(r)
                worse = (ms - mr) if c != "bw256k" else (mr - ms)
                pct = 100.0 * worse / mr
                sep = min(s) > max(r) or max(s) < min(r)
                if ro_missing:
                    reading = "not comparable (RO not requested)"
                elif not sep:
                    reading = "no measurable difference (ties are not separated)"
                elif worse > 0 and pct >= 2.0:
                    reading = "strict worse by %.3f %s (%.2f%%)" % (worse, unit, pct)
                    worth = True
                elif worse > 0:
                    reading = "strict worse by %.3f %s (%.2f%%): relaxed gain under 2%%" % (worse, unit, pct)
                else:
                    reading = "strict better by %.3f %s (%.2f%%)" % (-worse, unit, -pct)
                say("%s | %s | %d, %.3f, %.3f-%.3f | %d, %.3f, %.3f-%.3f | %+.3f | %+.2f%% | %s | %s" % (
                    c, unit, len(s), ms, min(s), max(s), len(r), mr, min(r), max(r), worse, pct, "yes" if sep else "no", reading))
            if notcmp:
                last = "not comparable (NCCL did not request RO in a valid run)"
            elif worth:
                last = "worth a capability check and an overlap experiment (a separated cell with strict worse by >= 2%)"
            elif incomplete:
                last = "incomplete (a cell has fewer than 5 valid runs in an arm)"
            else:
                last = "no relaxed gain of 2% or more measured on this node (RO requested; whether the NIC sent relaxed writes is not seen)"
            say("%s: later relaxed optimisation (user decision; this decides nothing): %s" % (node, last))
            say()
    if not any_folder:
        say("no ord_<node> folder in %s" % R)
    with open(os.path.join(R, "SUMMARY_ORD.txt"), "w") as f:
        f.write("\n".join(OUT) + "\n")


main()
