#!/usr/bin/env python3
"""gin-oneway post-hoc analysis (NOT pre-registered; defined in DEVIATIONS.md section 3 after the smoke, before the main
run): dead close lines that came before the other rank started its communicator teardown.

usage: posthoc_ow.py <resultsdir>     (reads <resultsdir>/trials_scored.csv written by score.py and the per-trial logs)

For every scored trial: n_dead_live_r0, n_dead_live_r1 = the liveness=dead close lines of that rank earlier than the other
rank's first "GIN/TS: communicator teardown" line (its t0_mono_ms), both on rank 0's clock (rank 1 times minus
clock_offset_ms of rank 0's kv); all dead lines if the other rank has no teardown line. Then the frozen acceptance rules
that use n_dead_r0/n_dead_r1 are evaluated again with those two columns replaced, using ../s2_close/score.py's grammar.
Prints a table; writes nothing. The pre-registered verdicts are those of SCORE.md.
"""
import csv, importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("s2close_score", os.path.join(HERE, "..", "s2_close", "score.py"))
s2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s2)
RE_TD = re.compile(r"GIN/TS: communicator teardown rank=\d+:.*?t0_mono_ms=([\d.]+)")
RE_DEAD = re.compile(r"GIN/TS: rank \d+: socket to rank \d+ closed cause=(\S+) mono_ms=([\d.]+) liveness=dead")


def kvfile(path):
    d = {}
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line.rstrip("\n")):
                d[m.group(1)] = m.group(2).strip().strip('"')
    return d


def live_dead(stem):
    try:
        off = float(kvfile(stem + "_r0.kv").get("clock_offset_ms"))
    except (TypeError, ValueError):
        return None
    td, dead = {}, {0: [], 1: []}
    for r in (0, 1):
        p = "%s_r%d.log" % (stem, r)
        if not os.path.exists(p):
            continue
        for line in open(p, errors="replace"):
            m = RE_TD.search(line)
            if m and r not in td:
                td[r] = float(m.group(1)) - (off if r == 1 else 0.0)
            m = RE_DEAD.search(line)
            if m:
                dead[r].append(float(m.group(2)) - (off if r == 1 else 0.0))
    return {r: sum(1 for t in dead[r] if (1 - r) not in td or t < td[1 - r]) for r in (0, 1)}


def main():
    R = os.path.abspath(sys.argv[1])
    rows = [r for r in csv.DictReader(open(os.path.join(R, "trials_scored.csv"))) if r["status"] == "scored"]
    for r in rows:
        ld = live_dead(os.path.join(R, r["sub"], r["stem"]))
        r["n_dead_live_r0"], r["n_dead_live_r1"] = ("", "") if ld is None else (ld[0], ld[1])
    by = {}
    for r in rows:
        by.setdefault(r["key"], []).append(r)
    print("| 셀 | n | 죽음 줄이 있는 시행(사전 등록 열) | 상대 정리 전 죽음 줄이 있는 시행(사후 열) |")
    print("|---|--:|--:|--:|")
    for k in sorted(by):
        rs = by[k]
        a = sum(1 for r in rs if s2.val(r["n_dead_r0"]) != 0 or s2.val(r["n_dead_r1"]) != 0)
        b = sum(1 for r in rs if s2.val(r["n_dead_live_r0"]) != 0 or s2.val(r["n_dead_live_r1"]) != 0)
        print("| `%s` | %d | %d | %d |" % (k, len(rs), a, b))
    print()
    preds = list(csv.DictReader(open(os.path.join(HERE, "predictions.csv"))))
    print("| 예측 | 사전 등록 열로 센 수 | 사후 열로 다시 센 수 |")
    print("|---|---|---|")
    for p in preds:
        if "n_dead_r" not in p["acceptance"]:
            continue
        keys = s2.keys_of(p["cells"])
        acc = p["acceptance"]
        alt = acc.replace("n_dead_r0", "n_dead_live_r0").replace("n_dead_r1", "n_dead_live_r1")
        e1 = s2.evaluate(acc, by, keys[0], s2.NIL)
        e2 = s2.evaluate(alt, by, keys[0], s2.NIL)
        f = lambda e: ", ".join("%d/%d" % (c, n) for (_, c, n, _, _, _) in e[1]) + (" (참)" if e[0] else " (거짓)")
        print("| %s | %s | %s |" % (p["id"], f(e1), f(e2)))


if __name__ == "__main__":
    main()
