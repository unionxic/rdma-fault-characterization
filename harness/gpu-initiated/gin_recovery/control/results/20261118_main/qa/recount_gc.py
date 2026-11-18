#!/usr/bin/env python3
"""recount_gc.py <raw dir> <out csv>: one row per trial, recounted from the raw logs with ev_gc.py (independent of rows_gc.py).
Columns: injection, judgements (observer:cause:ms after the injection), fence order, restore time, release, data, outcome."""
import sys, os, csv, json
import ev_gc

INJ = ("inj_killed", "inj_die", "inj_stop", "inj_gpuhang", "inj_quiet", "inj_duty", "inj_mute", "inj_switch")


def f1(x):
    return "" if x is None else "%.1f" % x


def subject_of(meta):
    for k in ("subject_rank", "kill_rank", "stop_rank", "duty_rank"):
        v = meta.get(k, "")
        if v not in ("", "-"):
            return int(v)
    return None


def pick_injection(d, subj):
    cands = []
    for e in d["ev"]:
        n, g = e["name"], e["g"]
        if n not in INJ:
            continue
        if n == "inj_killed":
            if e["src"] == "spare_kill":
                continue
            cands.append(e)
        elif n == "inj_die":
            cands.append(e)
        elif n == "inj_duty" and g[0] != "start":
            continue
        elif n == "inj_mute" and g[0] != "on":
            continue
        elif n == "inj_switch":
            sw = g[1]
            if sw.startswith("FD_HOLDER") or sw == "DROP_UD":
                continue  # not the injection itself (the kill is)
            cands.append(e)
        else:
            cands.append(e)
    return cands


def proc_ok(kv):
    """gin-mirror 'data equal' per process: state, received cells and signals equal to the host reference, no poison."""
    if not kv:
        return None
    try:
        return (kv.get("x_match") == "1" and kv.get("recv_bad") == "0" and kv.get("dev_bad") == "0" and kv.get("xhist_bad") == "0"
                and kv.get("sig_exact") == "1" and kv.get("recv_poison") == "0" and kv.get("dev_poison") == "0" and kv.get("xchg") == "ok")
    except Exception:
        return None


def row(raw, stem):
    d = ev_gc.load(raw, stem)
    m = d["meta"]
    ev = d["ev"]
    subj = subject_of(m)
    nr = int(m.get("n", "4"))
    inj = pick_injection(d, subj)
    t0 = inj[0]["t"] if inj else None
    inj_desc = ("%s:%s" % (inj[0]["name"], "/".join(x for x in inj[0]["g"] if x))) if inj else ""
    r = dict(stem=stem, cell=m.get("cell"), build=m.get("lib"), trial=m.get("trial"), hold=m.get("hold"), subject=subj,
             inject=inj_desc, inj_n=len(inj), inj_src=(inj[0]["file"] + ":%d" % inj[0]["line"]) if inj else "",
             left=m.get("left"), left_stopped=m.get("left_stopped"), left_fdhold=m.get("left_fdhold"),
             rcs=" ".join("%s=%s" % (k, m.get(k)) for k in ("r0rc", "r1rc", "r2rc", "r3rc", "sparerc") if m.get(k) not in (None, "")),
             wall_s=m.get("wall_s"))
    # ring live per rank log (gc builds)
    live = 0
    for k in range(nr):
        p = os.path.join(raw, "%s_r%d.log" % (stem, k))
        if os.path.exists(p) and "the records go on the ring from now (live)" in open(p, errors="replace").read():
            live += 1
    r["ring_live_ranks"] = live
    # judgements of the subject by original-rank observers (r* logs, not the spare)
    judg = []
    for e in ev:
        if e["name"] in ("dead", "stalled") and e["src"].startswith("r") and len(e["src"]) == 2:
            obs, tgt = int(e["g"][0]), int(e["g"][1])
            cause = e["g"][2] if e["name"] == "dead" else e["g"][3]
            judg.append((e["t"], obs, tgt, cause, e["name"], e))
    js = [j for j in judg if j[2] == subj]
    others = [j for j in judg if j[2] != subj]
    first_by_obs = {}
    for j in js:
        first_by_obs.setdefault(j[1], j)
    r["judge_n"] = len(first_by_obs)
    r["judges"] = " ".join("r%d:%s:%s" % (o, j[3], f1(j[0] - t0) if t0 is not None else "?") for o, j in sorted(first_by_obs.items(), key=lambda x: x[1][0]))
    jt = [j[0] - t0 for j in first_by_obs.values()] if t0 is not None else []
    r["judge_min"] = f1(min(jt)) if jt else ""
    r["judge_max"] = f1(max(jt)) if jt else ""
    r["judge_spread"] = f1(max(jt) - min(jt)) if jt else ""
    r["causes"] = "+".join(sorted(set(j[3] for j in first_by_obs.values())))
    r["other_judged"] = " ".join("r%d->%d:%s:%s" % (j[1], j[2], j[3], f1(j[0] - t0) if t0 else "?") for j in others)
    r["stalled_rx_n"] = sum(1 for e in ev if e["name"] == "stalled_rx" and int(e["g"][1]) == (subj if subj is not None else -1))
    # suspicion
    sus = [e for e in ev if e["name"] == "suspect"]
    r["suspect_any_n"] = len(sus)
    r["suspect_subj_n"] = sum(1 for e in sus if int(e["g"][1]) == subj)
    r["suspect_kinds"] = "+".join(sorted(set("%s->%s:%s" % (e["g"][0], e["g"][1], e["g"][2]) for e in sus)))
    # READ fail / timeout before the first judgement
    tj = min(j[0] for j in js) if js else None
    r["probe_to_before_judge"] = sum(1 for e in ev if e["name"] == "probe_to" and int(e["g"][1]) == subj and (tj is None or e["t"] < tj))
    r["readfail_before_judge"] = sum(1 for e in ev if e["name"] == "readfail" and int(e["g"][1]) == subj and (tj is None or e["t"] < tj))
    # fence and activation
    lf = [e for e in ev if e["name"] == "la_fence" and int(e["g"][1]) == subj]
    lfd = [e for e in ev if (e["name"] == "la_fenced" and int(e["g"][1]) == subj)
           or (e["name"] == "la_fence" and int(e["g"][1]) == subj and "already ended; FENCED" in e["g"][4])]
    sfd = [e for e in ev if e["name"] == "fence_fenced" and int(e["g"][1]) == subj]
    lex = [e for e in ev if e["name"] == "la_exited" and int(e["g"][1]) == subj]
    lact = [e for e in ev if e["name"] == "la_act" and int(e["g"][1]) == subj]
    sact = [e for e in ev if e["name"] == "spare_activating"]
    pub = [e for e in ev if e["name"] == "published" and int(e["g"][1]) == subj]
    rest = [e for e in ev if e["name"] == "restored" and int(e["g"][1]) == subj and e["src"].startswith("r")]
    fsent = [e for e in ev if e["name"] == "fence_sent" and int(e["g"][1]) == subj]
    win = [e for e in ev if e["name"] == "window" and int(e["g"][2]) == subj]
    def rel(es):
        return f1(es[0]["t"] - t0) if es and t0 is not None else ""
    r["fence_sent"] = rel(fsent)
    r["la_fence"] = rel(lf)
    r["la_fence_n"] = len(lf)
    r["la_fenced"] = rel(lfd)
    r["la_fenced_txt"] = (lfd[0]["g"][3] if lfd[0]["name"] == "la_fenced" else lfd[0]["g"][4]) if lfd else ""
    r["surv_fenced_line"] = rel(sfd)
    r["la_fence_sigkill"] = sum(1 for e in lf if "SIGKILL sent" in e["g"][4])
    r["la_exited"] = rel(lex)
    r["la_exited_kind"] = lex[0]["g"][3] if lex else ""
    r["la_act"] = rel(lact)
    r["la_act_res"] = "+".join("%s(%s)" % (e["g"][4], e["g"][6] or "") for e in lact)
    r["spare_act"] = rel(sact)
    r["pub_first"] = rel(pub)
    r["pub_last"] = f1(pub[-1]["t"] - t0) if pub and t0 is not None else ""
    # order: FENCE < FENCED < activation(ACCEPTED) <= spare activating < first publish
    order = ""
    if lf or lfd:
        seq = []
        ok = True
        tf = lf[0]["t"] if lf else None
        tfd = lfd[0]["t"] if lfd else None
        ta = [e["t"] for e in lact if e["g"][4] == "ACCEPTED"]
        ta = ta[0] if ta else None
        tp = pub[0]["t"] if pub else None
        chain = [("FENCE", tf), ("FENCED", tfd), ("ACT", ta), ("PUB", tp)]
        present = [(n, t) for n, t in chain if t is not None]
        for (a, x), (b, y) in zip(present, present[1:]):
            if not x <= y:
                ok = False
        order = ("ok:" if ok else "BAD:") + ">".join(n for n, t in present)
        # activation before FENCED?
        if tfd is not None and any(e["t"] < tfd for e in lact if e["g"][4] == "ACCEPTED"):
            order += ":ACT_BEFORE_FENCED"
    r["fence_order"] = order
    r["win_n"] = len(win)
    r["win_changed"] = sum(int(e["g"][3]) for e in win) if win else ""
    r["win_unread"] = sum(int(e["g"][4]) for e in win) if win else ""
    # restore time: first judgement -> last original-rank 'restored as incarnation'
    r["restored_n"] = len(set(e["src"] for e in rest))
    if js and rest:
        r["restore_ms"] = f1(max(e["t"] for e in rest) - min(j[0] for j in js))
        r["kill_to_last_restored"] = f1(max(e["t"] for e in rest) - t0) if t0 is not None else ""
        r["judge_to_last_pub"] = f1(max(e["t"] for e in pub) - min(j[0] for j in js)) if pub else ""
        r["kill_to_last_pub"] = f1(max(e["t"] for e in pub) - t0) if pub and t0 is not None else ""
    else:
        r["restore_ms"] = r["kill_to_last_restored"] = r["judge_to_last_pub"] = r["kill_to_last_pub"] = ""
    # release / degraded / decline
    dec = [e for e in ev if e["name"] == "declined" and int(e["g"][1]) == subj]
    deg = [e for e in ev if e["name"] in ("degraded_now", "degraded_ad")]
    relst = [e for e in ev if e["name"] == "released_step" and e["src"].startswith("r") and len(e["src"]) == 2]
    r["declined_n"] = len(set(e["src"] for e in dec))
    r["nohold_n"] = sum(1 for e in ev if e["name"] == "nohold")
    r["hold_n"] = sum(1 for e in ev if e["name"] == "hold")
    r["given_up_n"] = sum(1 for e in ev if e["name"] == "given_up")
    r["degraded_n"] = len(set(e["src"] for e in deg))
    r["released_procs"] = len(set(e["src"] for e in relst))
    r["released_ms"] = (f1(min(e["t"] for e in relst) - t0) + "-" + f1(max(e["t"] for e in relst) - t0)) if relst and t0 is not None else ""
    r["fallback_ms"] = ""
    fb = [e for e in ev if e["name"] in ("given_up", "declined") and e["src"].startswith("r")]
    r["fenced_to_fallback"] = f1(min(e["t"] for e in fb) - lfd[0]["t"]) if lfd and fb else ""
    r["fallback_why"] = "|".join(sorted(set(e["g"][2][:60] for e in fb)))
    r["refused_to_fallback"] = ""
    ref = [e for e in lact if e["g"][4] == "REFUSED"]
    if ref and fb:
        r["refused_to_fallback"] = f1(min(e["t"] for e in fb) - ref[0]["t"])
    if lfd and relst:
        r["fallback_ms"] = f1(min(e["t"] for e in relst) - lfd[0]["t"])
    r["released_all_ranks"] = len(set(e["src"] for e in relst))
    r["judged_or_taken"] = len(set([j[1] for j in js] + [int(e["g"][0]) for e in ev if e["name"] == "ad_rx" and e["g"][4] == "applied" and int(e["g"][1]) == subj and e["src"].startswith("r")]))
    # abort decisions
    r["ad_decided_n"] = sum(1 for e in ev if e["name"] == "ad_decided")
    r["ad_applied_n"] = sum(1 for e in ev if e["name"] == "ad_rx" and e["g"][4] == "applied")
    # kv: outcome per process
    kvs = d["kv"]
    outs = []
    data_ok = []
    for k in sorted(kvs):
        kv = kvs[k]
        if not kv:
            continue
        outs.append("%s:%s/%s" % (k, kv.get("xchg", "-"), kv.get("exit", "-") + ("/wd" if kv.get("watchdog") == "1" else "")))
    r["outcomes"] = " ".join(outs)
    # data equal: every process that finished (survivors + the revived spare(s)), the subject's original incarnation excluded
    fin = []
    for k, kv in kvs.items():
        if not kv:
            continue
        if k == "r%d" % (subj if subj is not None else -1) and kv.get("xchg") in (None, "") and kv.get("exit") in (None, ""):
            continue
        fin.append((k, kv))
    finished = [(k, kv) for k, kv in fin if kv.get("xchg") not in (None, "")]
    r["finished"] = " ".join(sorted(k for k, kv in finished))
    oks = [proc_ok(kv) for k, kv in finished]
    r["data_equal"] = int(bool(oks) and all(oks)) if oks else ""
    r["xchg_set"] = "+".join(sorted(set(kv.get("xchg") for k, kv in finished)))
    r["revived_done"] = ""
    sp = kvs.get("spare")
    if sp is not None:
        r["revived_done"] = int(sp.get("xchg") == "ok" and sp.get("steps_done") == m.get("steps"))
    r["resume_rcs"] = "+".join(sorted(set("%s:%s" % (k, kv.get("resume_rc")) for k, kv in kvs.items() if kv and kv.get("resume_rc") not in (None, "0"))))
    r["watchdog_any"] = int(any(kv and kv.get("watchdog") == "1" for kv in kvs.values()))
    # wait outcome: held = a hold started and restored; released = released=1 lines; error = exit != 0 among survivors
    surv = [kvs.get("r%d" % k) for k in range(nr) if k != subj]
    rel1 = sum(1 for kv in surv if kv and kv.get("released") == "1")
    r["wait_outcome"] = ("held" if r["hold_n"] and r["restored_n"] else "") + ("released%d" % rel1 if rel1 else "")
    r["surv_exit"] = "+".join(sorted(set((kv or {}).get("exit", "-") for kv in surv)))
    r["surv_x_match"] = "+".join(sorted(set((kv or {}).get("x_match", "-") for kv in surv)))
    # cont line (stop cells)
    cont = [e for e in ev if e["name"] == "inj_cont"]
    r["cont_present"] = cont[0]["g"][1] if cont else ""
    r["stopped_ms"] = cont[0]["g"][2] if cont else ""
    # wait/peer lines (cell B), quiet end
    r["waiting_peers"] = "+".join(sorted(set(e["g"][2] for e in ev if e["name"] == "waiting")))
    r["wait_ended"] = "|".join(sorted(set(e["g"][2][:40] for e in ev if e["name"] == "wait_ended")))
    wpe = [e for e in ev if e["name"] == "waitpend_end"]
    r["waitpend_result"] = wpe[0]["g"][3] if wpe else ""
    qe = [e for e in ev if e["name"] == "inj_quiet_end"]
    r["quiet_end"] = qe[0]["g"][4] if qe else ""
    # two-death: judgements of the second subject
    k2 = m.get("kill2_rank", "")
    if k2 not in ("", "-"):
        k2 = int(k2)
        dies = [e for e in ev if e["name"] == "inj_die"]
        dd = {int(e["g"][0]): e["t"] for e in dies}
        j2 = [e for e in ev if e["name"] in ("dead", "stalled") and int(e["g"][1]) == k2]
        rest2 = [e for e in ev if e["name"] == "restored" and int(e["g"][1]) == k2]
        rest1 = [e for e in ev if e["name"] == "restored" and int(e["g"][1]) == subj]
        r["die1"] = f1(dd.get(subj) - t0) if subj in dd else ""
        r["die2"] = f1(dd.get(k2) - t0) if k2 in dd else ""
        r["judge2"] = f1(min(e["t"] for e in j2) - dd[k2]) + "-" + f1(max(e["t"] for e in j2) - dd[k2]) if j2 and k2 in dd else ""
        r["restore2_ms"] = f1(max(e["t"] for e in rest2) - min(e["t"] for e in j2)) if j2 and rest2 else ""
        r["restored2_n"] = len(set(e["src"] for e in rest2))
        r["restore1_ms"] = f1(max(e["t"] for e in rest1) - min(j[0] for j in js)) if js and rest1 else ""
    # LATER count
    r["la_later_n"] = sum(1 for e in ev if e["name"] == "la_act" and e["g"][4] == "LATER")
    return r


def main():
    raw, out = sys.argv[1], sys.argv[2]
    rows = [row(raw, s) for s in ev_gc.stems(raw)]
    keys = []
    for x in rows:
        for k in x:
            if k not in keys:
                keys.append(k)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for x in rows:
            w.writerow(x)
    print(len(rows), "rows ->", out)


if __name__ == "__main__":
    main()
