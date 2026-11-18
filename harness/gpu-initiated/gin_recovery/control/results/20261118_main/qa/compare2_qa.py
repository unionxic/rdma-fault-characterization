#!/usr/bin/env python3
"""compare2_qa.py: categorical columns (causes, fence order, wait held, released, taken, refusal reason, stall ctx) mine vs scorer."""
import csv, sys, collections
mine = {r["stem"]: r for r in csv.DictReader(open(sys.argv[1]))}
sc = {r["stem"].rsplit("/", 1)[-1]: r for r in csv.DictReader(open(sys.argv[2]))}
bad = collections.defaultdict(list); n = collections.Counter()
for st, m in sorted(mine.items()):
    s = sc[st]
    # causes: mine 'A+B' set; scorer judge_causes like 'FIN+STALE:3'
    if m["causes"] or s["judge_causes"]:
        n["causes"] += 1
        sc_c = "+".join(sorted(set(x.rsplit(":", 1)[0] for x in s["judge_causes"].split(" ") if x))) if s["judge_causes"] else ""
        mc = m["causes"]
        if sc_c.replace("+", "") != mc.replace("+", "") and set(sc_c.split("|")) != set(mc.split("|")):
            bad["causes"].append((st, mc, s["judge_causes"]))
    if m["fence_order"] or s["fence_order_ok"]:
        n["fence_order"] += 1
        mo = "1" if m["fence_order"].startswith("ok") else ("0" if m["fence_order"] else "")
        if mo != s["fence_order_ok"]:
            bad["fence_order"].append((st, m["fence_order"], s["fence_order_ok"]))
    # wait held: mine 'held' and not released
    mh = "1" if m["wait_outcome"] == "held" else "0"
    if s["wait_held"] != "":
        n["wait_held"] += 1
        if mh != s["wait_held"]:
            bad["wait_held"].append((st, m["wait_outcome"], s["wait_held"]))
    if s["surv_released"] != "":
        n["surv_released"] += 1
        if str(m["released_all_ranks"]) != s["surv_released"]:
            bad["surv_released"].append((st, m["released_all_ranks"], s["surv_released"]))
    if s["n_judge_taken"] not in ("", "0") or (m["judge_n"] != m["judged_or_taken"]):
        n["taken"] += 1
        mt = int(m["judged_or_taken"]) - int(m["judge_n"])
        if str(mt) != (s["n_judge_taken"] or "0"):
            bad["taken"].append((st, mt, s["n_judge_taken"]))
    if s["la_act_refused_why"] or "REFUSED" in m["la_act_res"]:
        n["refused_why"] += 1
        if (s["la_act_refused_why"] or "")[:15] not in m["la_act_res"]:
            bad["refused_why"].append((st, m["la_act_res"], s["la_act_refused_why"]))
    if s["win_verified"] != "":
        n["win_verified"] += 1
        mv = "1" if (m["win_n"] not in ("", "0") and m["win_changed"] == "0" and m["win_unread"] == "0") else "0"
        if mv != s["win_verified"]:
            bad["win_verified"].append((st, m["win_n"], m["win_changed"], s["win_verified"]))
for k in n:
    print(k, "checked", n[k], "differ", len(bad[k]))
    for b in bad[k][:12]:
        print("   ", b)
