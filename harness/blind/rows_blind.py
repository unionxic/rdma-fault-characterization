#!/usr/bin/env python3
"""rows_blind.py - blind-apps: one row per trial from the raw files (EXPERIMENT.md 3.1). Pre-registered with the
predictions: the regexes and the outcome rule below are the definitions the scorer uses.

    rows_blind.py <results dir> [--out trials.csv]   all trials, with the truth (only after the evaluator's judgments
                                                      are committed: the rows contain the fault class)
    rows_blind.py <results dir> --progress            per hold: trials done, trials without the start line, leftovers;
                                                      no fault class or outcome (safe to read while the study is blind)

Times are rain CLOCK_MONOTONIC seconds at line receipt (blindrun.py). A rank's log is r<r>.log, the agent's a<r>.log,
the runner's record trial.meta.

Outcome of a trial (survivors = the ranks the schedule did not kill):
  HUNG          a survivor was ended by the harness (grace or wall cap), or the first error line of the survivors is a
                timeout-type line (TIMEOUT below)
  SILENT_WRONG  not HUNG, the result is wrong, no survivor printed an error line and every survivor exited 0
  DECLINED      not HUNG and not SILENT_WRONG, and a survivor printed an error line or exited non-zero
  TRANSPARENT   every survivor exited 0, no error line, and the result is correct
  OTHER         anything else (e.g. exit 0 without a result)
Result: ddp correct iff every survivor printed its final sha256 and it equals that rank's sha256 in the fault-free
reference runs of the same results directory (ref-ddp-*; the oracle is valid only if those agree, else "unknown");
gin correct iff rank 0 printed "GIN Ring Exchange result: PASSED" and no rank printed a mismatch line, wrong if
FAILED or a mismatch line; nvs correct iff PE 0 printed all three size lines and no PE printed a validation line
("error, data["), wrong if any validation line.
"""
import argparse, csv, glob, json, os, re, statistics, sys

ERR = {
    "ddp": [r"Watchdog caught collective operation timeout", r"ProcessGroupNCCL.*(Exception|[Ee]rror)",
            r"DistBackendError", r"NCCL error", r"nccl(Remote|System|Internal|UnhandledCuda|InvalidUsage)Error",
            r"terminate called", r"Traceback \(most recent call last\)", r"RuntimeError",
            r"\[FAULT-RECOVERY2\] .*FAILED in", r"peer process gone", r"NET/IB ?: Got completion from peer"],
    "gin": [r"GIN/TS: declined rank=", r"judged dead", r"why=(declined|peer-dead|fw-watchdog)",
            r"the fault surfaces \(ncclRemoteError\)", r"NCCL (failure|error)", r"nccl(Remote|System|Internal|UnhandledCuda|InvalidUsage)Error",
            r"(?i)\bcuda (failure|error)\b", r"^Failed[,:] ", r"Failed to execute NCCL operations", r"^ERROR:|\bERROR: rank",
            r"GIN/REC: (commit failed|recovery aborted|prepare declined)", r"escalated rank=",
            r"NET/IB ?: Got completion from peer", r"Segmentation fault|Aborted"],
    "nvs": [r"\[nvshmem-t1\] PE\d+ [0-9.]+ DECLINE", r"\[nvshmem-ft\] PE\d+ marked failed", r"transparent mode (stays )?off",
            r"cuda failed with", r"NVSHMEM.*(ERROR|[Ee]rror)", r"nvshmem.*failed", r"CUDA error",
            r"Segmentation fault|Aborted"],
}
NOT_ERR = r"error, data\["  # the example's own validation line: the oracle, not an error signal
TIMEOUT = {"ddp": r"Watchdog caught collective operation timeout|ran for \d+ milliseconds before timing out|WAIT_?REQ",
           "gin": r"(?!x)x", "nvs": r"(?!x)x"}
REC = {"ddp": r"\[FAULT-RECOVERY2\] (send|recv) comm: recovered", "gin": r"GIN/TS: recovered rank=",
       "nvs": r"\[nvshmem-t1\] PE\d+ [0-9.]+ RECOVERED"}
DEATH = {"ddp": r"peer process gone|closed its OOB socket \(FIN\)", "gin": r"judged dead|why=peer-dead",
         "nvs": r"peer_fin=1|library socket closed \(FIN\)"}
MGMT = {"ddp": r"OOB socket lost", "gin": r"socket to rank \d+ closed cause=",
        "nvs": r"library socket lost|re-dialed|re-accepted"}
FIRE = {("ddp", "sqp"): r"\[FAULT-INJECT\] forced send QP", ("ddp", "rqp"): r"\[FAULT-INJECT\] forced recv QP .*before receive post",
        ("ddp", "srq"): r"\[FAULT-INJECT\] forced recv QP .*\[silent\]", ("gin", "qperr"): r"GIN/FAULT: GDAKI fault fired",
        ("nvs", "qperr"): r"\[nvshmem-fault-inject\] shot 1 fire_mono_ms", ("nvs", "remacc"): r"\[nvshmem-fault-inject\] shot 1 fire_mono_ms"}
FIRE_DONE = {("nvs", "qperr"): r"\[nvshmem-fault-inject\] moved [1-9]\d* QP",
             ("nvs", "remacc"): r"\[nvshmem-fault-inject\] revoked remote access on [1-9]\d* RC QP",
             ("gin", "qperr"): r"GIN/FAULT: GDAKI fault fired.*moved [1-9]\d*/"}
CONFIG = {"ddp": [r"NCCL version 2\.23\.4", r"\[FAULT-RECOVERY2\] recovery on for"],
          "gin": [r"GIN/TS: transparent recovery ON rank="], "nvs": [r"^\[nvshmem-t1\] PE\d+ [0-9.]+ enabled:"]}
CONFIG_OFF = {"ddp": r"\[FAULT-RECOVERY2\] recovery off for this|helper thread not started",
              "gin": r"GIN/TS: transparent recovery OFF|GIN/REC: .*recovery disabled",
              "nvs": r"transparent mode (stays )?off|FT stays off"}  # any of these on any rank: the build is not as planned
ANCHOR = {"ddp": r"^iter 0: loss", "gin": r"=== Comparing GIN ring-exchange implementations ===",
          "nvs": r"^\[nvshmem-t1\] PE0 [0-9.]+ enabled:"}
# a start failure after the anchor line (nvs: the anchor is printed at connect, before the heap is registered)
INIT_FAIL = {"ddp": r"(?!x)x", "gin": r"(?!x)x",
             "nvs": r"nvshmemi_setup_transport failed|heap registration setup failed|nvshmem_init.*failed"}
HASH = re.compile(r"^\[ddp-entry\] rank=(\d) final iter=(\d+) parameters sha256=([0-9a-f]{64})")
NVS_SIZE = re.compile(r"^(\d+)B\s+[0-9.]+ms")
NVS_SIZES = 3
COLS = ["id", "kind", "hold", "workload", "cls", "target", "dir", "k", "t_ms", "t_after_anchor_s", "d_s", "applied",
        "void", "config_ok", "valid", "t_fault_rel_anchor", "killed_rank", "rc0", "rc1", "end0", "end1", "n_err0", "n_err1",
        "err0", "err1", "timeout_first", "n_rec", "n_death", "n_mgmt", "result", "outcome", "dt_err", "dt_end",
        "max_gap0", "wall_s", "left", "mute_rules_on", "mute_rules_left", "mute_skipped", "rerun"]


def read_log(p):
    out = []
    try:
        with open(p, errors="replace") as f:
            for l in f:
                t, _, rest = l.rstrip("\n").partition(" ")
                try:
                    out.append((float(t), rest))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def first_match(lines, rx, start=None):
    r = re.compile(rx)
    for t, l in lines:
        if (start is None or t >= start) and r.search(l):
            return t, l
    return None, None


def err_lines(wl, lines):
    rs = [re.compile(x) for x in ERR[wl]]
    ne = re.compile(NOT_ERR)
    return [(t, l) for t, l in lines if not ne.search(l) and any(r.search(l) for r in rs)]


def ref_hashes(results):
    """Per-rank final sha256 of the fault-free reference runs (ref-ddp-*); (hashes, valid)."""
    seen = {0: set(), 1: set()}
    for d in sorted(glob.glob(os.path.join(results, "raw", "ref-ddp-*"))):
        for r in (0, 1):
            for _, l in read_log(os.path.join(d, "r%d.log" % r)):
                m = HASH.match(l)
                if m:
                    seen[r].add(m.group(3))
    ok = all(len(seen[r]) == 1 for r in (0, 1))
    return ({r: next(iter(seen[r])) for r in (0, 1)} if ok else {}), ok


def row_of(results, d, refs, ref_ok):
    m = json.load(open(os.path.join(d, "trial.meta")))
    e, p = m["entry"], m.get("params", {})
    wl, cls, target = e["workload"], e["cls"], e.get("target")
    logs = {r: read_log(os.path.join(d, "r%d.log" % r)) for r in (0, 1)}
    agent = {r: read_log(os.path.join(d, "a%d.log" % r)) for r in (0, 1)}
    t_anchor, _ = first_match(logs[0], ANCHOR[wl])
    row = {c: "" for c in COLS}
    row.update({"id": m["id"], "kind": m["kind"], "hold": e.get("hold", ""), "workload": wl, "cls": cls,
                "target": "" if target is None else target, "dir": e.get("dir") or "", "k": p.get("k", ""),
                "t_ms": p.get("t_ms", ""), "t_after_anchor_s": p.get("t_after_anchor_s", ""), "d_s": p.get("d_s", ""),
                "wall_s": m.get("wall_s", ""), "left": "%s,%s" % tuple(m.get("left", ("", ""))),
                "rerun": len(glob.glob(d + ".partial*"))})
    f = m.get("fault", {})
    t_fault = None
    if (wl, cls) in FIRE:
        t_fire, _ = first_match(logs[target], FIRE[(wl, cls)])
        done_rx = FIRE_DONE.get((wl, cls))
        applied = t_fire is not None and (done_rx is None or first_match(logs[target], done_rx)[0] is not None)
        t_fault = t_fire if applied else None
    elif cls in ("kill", "stop"):
        applied = bool(f.get("applied"))
        t_fault = f.get("t_ack") if applied else None
    elif cls == "mute":
        mu = f.get("mute", {})
        applied = bool(f.get("applied"))
        t_fault = mu.get("t_on") if applied else None
        row.update({"mute_rules_on": mu.get("rules_on", ""), "mute_rules_left": mu.get("rules_left", ""),
                    "mute_skipped": mu.get("skipped", f.get("skipped", ""))})
    else:
        applied = True
    if cls in ("kill", "stop") and not applied:
        row["mute_skipped"] = f.get("skipped", "")
    row["applied"] = int(applied)
    killed = target if (cls == "kill" and applied) else None
    row["killed_rank"] = "" if killed is None else killed
    survivors = [r for r in (0, 1) if r != killed]
    ex = m.get("exit", {})
    for r in (0, 1):
        x = ex.get(str(r), ex.get(r, {})) or {}
        row["rc%d" % r] = "" if x.get("rc") is None else x["rc"]
        row["end%d" % r] = x.get("harness_end", "")
    # void: the workload never started (no anchor line on rank 0, or a start-failure line on any rank) and no fault
    # was applied before that
    t_init_fail = min([t for r in (0, 1) for t in [first_match(logs[r], INIT_FAIL[wl])[0]] if t is not None],
                      default=None)
    started = t_anchor is not None and t_init_fail is None
    row["void"] = int(not started and not (applied and cls != "none" and t_fault is not None and
                                           (t_init_fail is None or t_fault < t_init_fail)))
    if t_fault is not None and t_anchor is not None:
        row["t_fault_rel_anchor"] = round(t_fault - t_anchor, 3)
    errs = {r: err_lines(wl, logs[r]) for r in (0, 1)}
    for r in (0, 1):
        row["n_err%d" % r] = len(errs[r])
        row["err%d" % r] = errs[r][0][1][:160] if errs[r] else ""
    surv_errs = sorted((t, l) for r in survivors for t, l in errs[r])
    row["timeout_first"] = int(bool(surv_errs) and re.search(TIMEOUT[wl], surv_errs[0][1]) is not None)
    row["n_rec"] = sum(1 for r in (0, 1) for _, l in logs[r] if re.search(REC[wl], l))
    row["n_death"] = sum(1 for r in survivors for _, l in logs[r] if re.search(DEATH[wl], l))
    row["n_mgmt"] = sum(1 for r in (0, 1) for _, l in logs[r] if re.search(MGMT[wl], l))
    if t_fault is not None:
        late = [t for t, _ in surv_errs if t >= t_fault - 0.5]
        row["dt_err"] = round(late[0] - t_fault, 3) if late else ""
        ends = []
        for r in survivors:
            x = ex.get(str(r), ex.get(r, {})) or {}
            if x.get("t_exit") is not None:
                ends.append(x["t_exit"])
        row["dt_end"] = round(max(ends) - t_fault, 3) if ends and len(ends) == len(survivors) else ""
    ts0 = [t for t, _ in logs[0] if t_anchor is not None and t >= t_anchor]
    row["max_gap0"] = round(max((b - a for a, b in zip(ts0, ts0[1:])), default=0.0), 3) if ts0 else ""
    # result (oracle)
    if wl == "ddp":
        got = {}
        for r in (0, 1):
            for _, l in logs[r]:
                mm = HASH.match(l)
                if mm:
                    got[r] = mm.group(3)
        if not ref_ok:
            result = "unknown"
        elif any(r not in got for r in survivors):
            result = "none"
        else:
            result = "correct" if all(got[r] == refs[r] for r in survivors) else "wrong"
    elif wl == "gin":
        res, _ = first_match(logs[0], r"GIN Ring Exchange result: PASSED")
        fail, _ = first_match(logs[0], r"GIN Ring Exchange result: FAILED")
        mis = any(first_match(logs[r], r"mismatch at CTA")[0] is not None for r in (0, 1))
        result = "wrong" if (fail is not None or mis) else ("correct" if res is not None else "none")
    else:
        sizes = {mm.group(1) for _, l in logs[0] for mm in [NVS_SIZE.match(l)] if mm}
        val = any(re.search(NOT_ERR, l) for r in (0, 1) for _, l in logs[r])
        sup = any(re.search(r"AGENT suppressed name=validation", l) for r in (0, 1) for _, l in agent[r])
        result = "wrong" if (val or sup) else ("correct" if len(sizes) >= NVS_SIZES else "none")
    row["result"] = result
    rc_ok = all(row["rc%d" % r] == 0 for r in survivors)
    hung = any(row["end%d" % r] in ("grace", "wall") for r in survivors) or row["timeout_first"] == 1
    any_err = bool(surv_errs)
    if result == "unknown" and not hung and not any_err and rc_ok:
        outcome = "UNKNOWN"
    elif hung:
        outcome = "HUNG"
    elif result == "wrong" and not any_err and rc_ok:
        outcome = "SILENT_WRONG"
    elif any_err or not rc_ok:
        outcome = "DECLINED"
    elif result == "correct":
        outcome = "TRANSPARENT"
    else:
        outcome = "OTHER"
    row["outcome"] = outcome
    # configuration check: every rank that printed anything shows the build's start lines (a rank killed before its
    # start lines were written is not checked)
    row["config_ok"] = int(all(first_match(logs[r], rx)[0] is not None for r in (0, 1) for rx in CONFIG[wl]
                               if logs[r] and not (r == killed and first_match(logs[r], CONFIG[wl][0])[0] is None))
                           and not any(first_match(logs[r], CONFIG_OFF[wl])[0] is not None for r in (0, 1)))
    row["valid"] = int(applied and not row["void"] and row["config_ok"] == 1)
    return row


def all_rows(results):
    refs, ok = ref_hashes(results)
    rows = []
    for meta in sorted(glob.glob(os.path.join(results, "raw", "*", "trial.meta"))):
        rows.append(row_of(results, os.path.dirname(meta), refs, ok))
    return rows, refs, ok


def progress(results):
    """Per hold: trials done, trials whose rank 0 never printed the workload's start line, leftovers. No truth."""
    out = {}
    for meta in sorted(glob.glob(os.path.join(results, "raw", "*", "trial.meta"))):
        m = json.load(open(meta))
        e = m["entry"]
        h = e.get("hold") or m["kind"]
        o = out.setdefault(h, {"done": 0, "no_start": 0, "left": 0})
        o["done"] += 1
        if first_match(read_log(os.path.join(os.path.dirname(meta), "r0.log")), ANCHOR[e["workload"]])[0] is None:
            o["no_start"] += 1
        o["left"] += int(any(str(x) not in ("0", "") for x in m.get("left", [])))
    for h in sorted(out):
        print("%s: %s" % (h, out[h]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--out", default=None)
    ap.add_argument("--progress", action="store_true")
    a = ap.parse_args()
    if a.progress:
        progress(a.results)
        return
    rows, refs, ok = all_rows(a.results)
    out = a.out or os.path.join(a.results, "trials.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print("%d rows -> %s; ddp reference hashes %s (%s)" % (len(rows), out, "agree" if ok else "DISAGREE or missing",
                                                         {r: v[:12] for r, v in refs.items()}))


if __name__ == "__main__":
    main()
