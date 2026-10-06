#!/usr/bin/env python3
"""Recount of the cells containing GP F4 or GG F4 (EV3c, EV4, EV5a, EV5c, D1, D2), with the 20
campaign F4 trials replaced by results/20261006_f4rerun/{gp,gg}. Reuses the parsers of recount.py
(raw files only; score.py / SCORE*.md / score*.json are not read). Writes rerun_table.md.

Acceptance (PREDICTIONS.md Method): >= 9/10 (or 5/5) trials show the predicted outcome AND no trial
shows an outcome outside the predicted class; 'every trial' / 10/10 cells need all trials."""
import os, re
import recount as R

CAMP = R.CAMP
RERUN = f"{R.PROP}/results/20261006_f4rerun"
OUT = os.path.dirname(os.path.abspath(__file__))


def gin(stack, tag):
    is_f4 = "_F4_" in tag and stack in ("gp", "gg")
    R.CAMP = RERUN if is_f4 else CAMP
    try:
        r = R.parse_gin(stack, tag)
        if stack == "gg" and r["fault"] in ("F2", "F3", "F4"):
            r["surface"] = R.gg_surface(r)
        if is_f4:
            base = f"{RERUN}/{stack}/logs/{'proxy' if stack == 'gp' else 'gdaki'}_F4_{r['mode']}_{tag.split('_')[-1]}"
            l0 = open(base + "_r0.log").read()
            r["drain"] = re.search(r"drain_device_rc=(\d+) drain_ms=([\d.]+) drain_outcome=(\w+)",
                                   open(base + "_r0.kv").read()).groups()
            r["r1_done_any"] = "DONE okIters" in open(base + "_r1.log").read()
            r["peer_gone_it"] = int(re.search(r"peer gone at it (\d+)", l0).group(1))
            r["r1_okit"] = r["r1"]["_okit_max"]
            r["r0_okit"] = r["r0"]["_okit_max"]
            r["src"] = "rerun"
        else:
            r["src"] = "campaign"
        return r
    finally:
        R.CAMP = CAMP


def main():
    P = R.plan()
    rerun_tags = {s: [l.split()[0] for l in open(f"{RERUN}/{s}/trials.log")] for s in ("gp", "gg")}
    T = {}
    for s in ("gp", "gg", "gq"):
        for t in P[s]:
            T[t] = gin(s, t)
    for t in P["cpu"]:
        T[t] = R.parse_cpu(t)
    for t in P["nvo"]:
        T[t] = R.parse_nvo(t)
    for t in P["nvd"]:
        T[t] = R.parse_nvd(t)
    for t in P["nvf"]:
        T[t] = R.parse_nvf(t)

    cells = {}

    def add(cid, sub, tag, hit):
        cells.setdefault(cid, {}).setdefault(sub, ([], []))[0 if hit else 1].append(tag)

    for s in ("gp",):
        for t in P[s]:
            r = T[t]
            if r["fault"] in ("F1", "F3", "F4"):
                add("EV3c", r["fault"], t, not r["r1_async_lines"])
    for s, var in (("gg", "GG"), ("gq", "GQ"), ("nvo", None), ("nvd", "ND"), ("nvf", "NF")):
        for t in P[s]:
            r = T[t]
            al = (r["r0_async_lines"] + r["r1_async_lines"]) if s in ("gg", "gq") else r["async_lines"]
            ev = [(r["ctr"][n] or {}).get("_events") for n in ("rain", "sunny")]
            add("EV4", var or r["variant"], t, not al and all(e == 0 for e in ev))
    z = lambda d: d is not None and all(d[k] == 0 for k in R.CTR4)
    for s, var in (("gg", "GG"), ("gq", "GQ"), ("nvf", "NF"), ("nvd", "ND")):
        for t in P[s]:
            r = T[t]
            add("EV5a", f"{var} {r['fault']}", t, z(r["ctr"]["rain"]) and z(r["ctr"]["sunny"]))
    for s in ("cpu", "gp"):
        for t in P[s]:
            r = T[t]
            if r["fault"] in ("F3", "F4"):
                d = r["ctr"]["rain"]
                add("EV5c", f"{s.upper()} {r['fault']}", t, d["local_ack_timeout_err"] >= 6 and d["req_cqe_error"] >= 1)
    for t in P["gg"]:
        r = T[t]
        if r["fault"] in ("F2", "F3", "F4"):
            l3 = r["r0"].get("init_outcome") == "ok" and r["r0"]["_okit_max"] > (r["r1"] or {}).get("_okit_max", 0)
            l4 = r["r0_gin_error"] and r["surface"] is not None and 0 < r["surface"] <= 10050
            r["l3"], r["l4"] = l3, l4
            add("D1", r["fault"], t, l3 and l4)
        if r["fault"] == "F4":
            # first flush after the kill must return success: in the rerun that flush is the drain put
            add("D2", "F4", t, r["drain"][2] not in ("timeout", "error") and r["r0"].get("init_outcome") == "ok")

    rule_all = {"EV3c", "EV4", "EV5a"}
    L = ["# Recount with the 20 re-run F4 trials (GP, GG)\n",
         "Data: `results/20261006_f4rerun/{gp,gg}` for GP/GG F4; everything else from "
         "`results/20261006_campaign`. Script: `rerun.py` (reuses `recount.py` parsers). Rule: PREDICTIONS.md "
         "Method, including 'no trial shows an outcome outside the predicted class'.\n",
         "## 1. Did the kill land during traffic?\n",
         "| trial | r0 okit | r1 okit (of 400) | r1 DONE | r0 'peer gone at it' | kill (ms after r0 start) | first r0 error |",
         "|---|--:|--:|---|--:|--:|---|"]
    for s in ("gp", "gg"):
        for t in rerun_tags[s]:
            r = T[t]
            fe = (f"WARN status={r['r0_warn_completion'][0][0]} vendor err {r['r0_warn_completion'][0][1]}"
                  if r["r0_warn_completion"] else ("GIN Error detected" if r["r0_gin_error"] else "-"))
            km = round(r["kill_mono_ms"] - float(r["r0"]["clock_offset_ms"]) - float(r["r0"]["t0_mono_ms"]), 1)
            L.append(f"| {t} | {r['r0_okit']} | {r['r1_okit']} | {r['r1_done_any']} | "
                     f"{r['peer_gone_it']} | {km} | {fe} |")
    L.append("")
    L.append("## 2. Cells (GP/GG F4 = re-run trials)\n")
    L.append("| cell | sub-cell | n | hits | misses | verdict |")
    L.append("|---|---|--:|--:|---|---|")
    for cid in ("EV3c", "EV4", "EV5a", "EV5c", "D1", "D2"):
        cv = "HOLDS"
        for sub, (h, m) in cells[cid].items():
            n = len(h) + len(m)
            v = "HOLDS" if not m and n else "FAILS"   # 'all' cells and 'no outcome outside the class' coincide
            if v == "FAILS":
                cv = "FAILS"
            L.append(f"| {cid} | {sub} | {n} | {len(h)} | {', '.join(m) if m else '-'} | {v} |")
        L.append(f"| **{cid}** | | | | | **{cv}** |")
    L.append("")
    L.append("## 3. What the F4 trials showed (EV5c, D1, D2)\n")
    L.append("| trial | rain d(local_ack_timeout_err) | rain d(req_cqe_error) | rain d(req_remote_access_errors) | "
             "drain rc / ms / outcome | r0 init_outcome | GIN Error surface ms | D1 L3 / L4 |")
    L.append("|---|--:|--:|--:|---|---|--:|---|")
    for s in ("gp", "gg"):
        for t in rerun_tags[s]:
            r = T[t]
            d = r["ctr"]["rain"]
            L.append(f"| {t} | {d['local_ack_timeout_err']} | {d['req_cqe_error']} | {d['req_remote_access_errors']} | "
                     f"{'/'.join(r['drain'])} | {r['r0'].get('init_outcome')} | {r.get('surface', '-')} | "
                     f"{(str(r['l3']) + ' / ' + str(r['l4'])) if 'l3' in r else '-'} |")
    L.append("")
    L.append("## 4. Notes\n")
    L.append("- Kill landed during traffic in 20/20: rank 1 never printed `DONE` (killed at 162-168 of 400 "
             "iterations, r1 rc 255); rank 0 lost the peer at the next barrier and then drained puts to the dead QP.")
    L.append("- GP F4 rank 0 WARN: `Got completion ... status=10 opcode=4 len=8 vendor err 136 (IPut)` "
             "(REM_ACCESS 0x88), i.e. the F2 class, not RETRY_EXC; hence local_ack_timeout_err +0 (EV5c needs >= +6).")
    L.append("- GG F4: drain_device_rc=8 is ncclTimeout (nccl.h of the gin build: `ncclTimeout = 8`). The drain "
             "put uses the bounded flush (gin_fault.cu: putKernel(..., /*useTimeout=*/1, ...)); in blocking mode "
             "the per-iteration TCP barrier sees the death first, so no blocking flush ran on a post-kill op "
             "(r0 okit = r1 okit in 9/10; t10 r0 counted one more iteration than r1, but whether that op failed "
             "cannot be determined).")
    L.append("- D1 F4 L4 holds 10/10 (GIN Error detected 8.03-8.08 s after the kill, at the ~10.8 s tick); L3 fails "
             "(r0 init_outcome=timeout, not a silent success); L2 not observable with the stock driver.")
    L.append("")
    open(f"{OUT}/rerun_table.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
