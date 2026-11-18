#!/usr/bin/env python3
"""compare_qa.py <trials_qa.csv> <trials_scored.csv>: per trial, my recount vs the scorer's columns. Times equal within TOL ms."""
import csv, sys, collections
TOL = 0.15
mine = {r["stem"]: r for r in csv.DictReader(open(sys.argv[1]))}
sc = {}
for r in csv.DictReader(open(sys.argv[2])):
    sc[r["stem"].rsplit("/", 1)[-1]] = r


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# (my column, scorer column, kind)
PAIRS = [
    ("judge_n", "n_judge", "int"),
    ("judge_min", "kill_judge_ms_min|stop_judge_ms_min|rst_judge_ms_min", "ms"),
    ("judge_max", "kill_judge_ms_max|stop_judge_ms_max|rst_judge_ms_max", "ms"),
    ("judge_spread", "judge_spread_ms", "ms"),
    ("restore_ms", "restore_time_ms", "ms"),
    ("judge_to_last_pub", "judge_to_publish_ms", "ms"),
    ("kill_to_last_pub", "kill_to_publish_ms", "ms"),
    ("data_equal", "ow_data_equal", "int"),
    ("revived_done", "revived_done", "int"),
    ("win_changed", "win_changed_after", "int"),
    ("la_fence_sigkill", "la_fence_sigkill_n", "int"),
    ("fenced_to_fallback", "fenced_to_fallback_ms", "ms"),
    ("left", "left", "int"),
    ("suspect_any_n", "suspect_any_n", "int"),
    ("probe_to_before_judge", "probe_timeout_n", "int"),
    ("restore1_ms", "restore_time_ms_1", "ms"),
    ("restore2_ms", "restore_time_ms_2", "ms"),
]
diff = []
checked = collections.Counter()
for stem, m in sorted(mine.items()):
    s = sc.get(stem)
    if s is None:
        diff.append((stem, "-", "missing in scorer", "", ""))
        continue
    for a, bs, kind in PAIRS:
        mv = m.get(a, "")
        b = None
        sv = ""
        for bb in bs.split("|"):
            if s.get(bb, "") not in ("", None):
                b, sv = bb, s[bb]
                break
        if b is None:
            b = bs.split("|")[0]
        if mv in ("", None) and sv in ("", None):
            continue
        checked[(a, b)] += 1
        x, y = num(mv), num(sv)
        if x is None or y is None:
            if (x is None) != (y is None) and not (x == 0 and y is None):
                diff.append((stem, a + " vs " + b, mv, sv, "one empty"))
            continue
        if kind == "int":
            if int(round(x)) != int(round(y)):
                diff.append((stem, a + " vs " + b, mv, sv, ""))
        else:
            if abs(x - y) > TOL:
                diff.append((stem, a + " vs " + b, mv, sv, "%+.1f" % (x - y)))
for k, v in sorted(checked.items()):
    print("checked", k, v)
print("differences:", len(diff))
for d in diff:
    print("\t".join(str(x) for x in d))
