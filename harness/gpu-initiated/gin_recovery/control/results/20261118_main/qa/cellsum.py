#!/usr/bin/env python3
"""cellsum.py <trials_qa.csv> [prefix]: per cell aggregates of recount_gc.py rows."""
import csv, sys, collections


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def rng(vals):
    v = [x for x in (num(y) for y in vals) if x is not None]
    if not v:
        return "-"
    return "%.1f–%.1f (n %d)" % (min(v), max(v), len(v))


def cnt(vals):
    c = collections.Counter(vals)
    return ", ".join("%s×%d" % (k if k != "" else "∅", n) for k, n in sorted(c.items()))


rows = list(csv.DictReader(open(sys.argv[1])))
pre = sys.argv[2] if len(sys.argv) > 2 else ""
by = collections.OrderedDict()
for r in rows:
    if r["cell"].startswith(pre):
        by.setdefault(r["cell"] + "@" + r["build"], []).append(r)
for k, v in by.items():
    v.sort(key=lambda r: int(r["trial"][1:]))
    print("==", k, "n", len(v))
    print("  judge_n:", cnt(r["judge_n"] for r in v), "| causes:", cnt(r["causes"] for r in v))
    print("  judge (inj→판정, 관측자별 첫):", rng([r["judge_min"] for r in v] + [r["judge_max"] for r in v]), "| spread:", rng(r["judge_spread"] for r in v))
    print("  fence_order:", cnt(r["fence_order"] for r in v), "| la_fenced:", rng(r["la_fenced"] for r in v), "| la_exited:", rng(r["la_exited"] for r in v))
    print("  act:", cnt(r["la_act_res"] for r in v))
    print("  restore(첫 판정→마지막 restored):", rng(r["restore_ms"] for r in v), "| restored_n:", cnt(r["restored_n"] for r in v), "| judge→last pub:", rng(r["judge_to_last_pub"] for r in v), "| inj→last restored:", rng(r["kill_to_last_restored"] for r in v))
    print("  win_n:", cnt(r["win_n"] for r in v), "changed:", cnt(r["win_changed"] for r in v), "unread:", cnt(r["win_unread"] for r in v))
    print("  data_equal:", cnt(r["data_equal"] for r in v), "| revived_done:", cnt(r["revived_done"] for r in v), "| xchg:", cnt(r["xchg_set"] for r in v), "| wait:", cnt(r["wait_outcome"] for r in v), "| surv_exit:", cnt(r["surv_exit"] for r in v))
    print("  released:", rng([r["released_ms"].split("-")[0] for r in v if r["released_ms"]] + [r["released_ms"].split("-")[-1] for r in v if r["released_ms"]]), "| fallback(FENCED→첫 released):", rng(r["fallback_ms"] for r in v), "| declined_n:", cnt(r["declined_n"] for r in v), "| degraded_n:", cnt(r["degraded_n"] for r in v))
    print("  suspect_any:", cnt(r["suspect_any_n"] for r in v), "| other_judged:", cnt(r["other_judged"] for r in v), "| hold_n:", cnt(r["hold_n"] for r in v), "| given_up:", cnt(r["given_up_n"] for r in v), "| ad:", cnt(r["ad_decided_n"] + "/" + r["ad_applied_n"] for r in v))
    print("  watchdog:", cnt(r["watchdog_any"] for r in v), "| resume_rcs:", cnt(r["resume_rcs"] for r in v), "| LATER:", cnt(r["la_later_n"] for r in v), "| probe_to/readfail before:", cnt(r["probe_to_before_judge"] + "/" + r["readfail_before_judge"] for r in v))
    if any(r.get("cont_present") for r in v):
        print("  cont present:", cnt(r["cont_present"] for r in v), "stopped_ms:", rng(r["stopped_ms"] for r in v))
    if any(r.get("restore2_ms") for r in v):
        print("  2nd death: judge2", cnt(r["judge2"] for r in v), "restore1", rng(r["restore1_ms"] for r in v), "restore2", rng(r["restore2_ms"] for r in v), "restored2_n", cnt(r["restored2_n"] for r in v))
