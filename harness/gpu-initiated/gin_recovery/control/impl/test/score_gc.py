#!/usr/bin/env python3
"""score_gc.py - gin-control, test side: applies predictions_gc.csv to a results folder and writes <resultsdir>/SCORE.md and
<resultsdir>/trials_scored.csv in gin-mirror's shape (../../../mirror/impl/test/score.py). Standard library only; CPU only.

usage: score_gc.py <resultsdir>

Steps (../../EXPERIMENT.md 3, 7, 8):
  1. rows_gc.all_rows(): one row per trial (raw/: the gc cells and gin-mirror's cells at @gct and @gc; reg/: gin-remaining's
     runner; cost*/: the probe cost family; local/: the CPU program gate_fenced).
  2. a status per trial. Smoke trials (a subfolder smoke*, or a trial of hold P0) and pilot trials (a subfolder pilot* or
     costpilot*, or a trial of another hold P*) are counted apart and never scored. The gc cells' exclusions of section 8
     (gin-mirror's and these): void, config_driver, workload, config (the trial ran another build, witness, fence, policy or
     restore setting than its cell, another launcher env than the cell's launcher_env, a W or READ period other than
     cells_gc.json "prereg", or its Resume was refused where the cell expects the restore), launcher_not_ready (the start
     check), launcher_changed (a launcher ended or changed during the trial, or a launcher QP loss outside the test-switch
     cells), not_applied (the injection's record is missing), inject_late (the runner's injection more than 1 s from its
     plan, a stop's length more than 1 s off, or the spare-absent cell's two kills more than 5 ms apart), spare_start_fail,
     foreign_gpu, restore_not_live, kill_before_ckpt (the kill, DIE_RST, STOP or FREEZE_PAGE before the subject's first
     stable checkpoint, in every cell with a spare), spareabsent_disarmed (a stable checkpoint between the spare's kill and
     the rank's), surplus. A second death is never excluded: a second kill before the re-arm, a first restore that failed or
     a re-arm that never came counts as a failed condition (gin-mirror's section 8, pre-registered; the coordinator's
     decision of 2026-10-17 for @gct and @gc). gin-mirror's regression rows take gin-mirror's own statuses (its score.py)
     plus the launcher exclusions here.
  3. per key cell@build the first PLANNED candidates by trial number are scored; "자료 부족" when a key of this study (its
     own cells and the regression cells its own formulas read) has fewer scored trials than planned (section 8 refills the
     exclusions; REVIEW_TEST fix 11), when a pooled key "build:<b>" has a cell with trials below its plan, or when a library
     column its formula reads (LIB_COLS: from TODO lines and the runner's new readings) is empty in every scored trial.
     gin-mirror's own predictions ("mirror:") keep that study's rule (its score.py).
  4. the acceptance grammar is gin-mirror's (s2_close 3.2: count(<expr>), N_SCORED, median) with these forms:
       <expr>                          on the first key of the cells column
       per cell: <expr>                on every key
       <key>: <expr> ;; <key>: <expr>  each part on its key; every part must hold
       subset(<cond>): <expr>          the key's scored rows where cond holds (N_SCORED their number); none -> "자료 없음"
       mirror: <id,...|all>@<build>    gin-mirror's predictions_mi.csv rows (cost rows left out) with @mi -> @<build>,
                                       judged by gin-mirror's score.py; every one 맞음 -> 맞음
       cost: rule=within:<pct>         the cost family per receiving node (cells "cost:<family>:<arms>:<metrics>")
     keys "build:<b>" pool every scored gin-control-runner trial of build b (no_tcp_control, long_hold_lane), "local:<x>" the
     local rows.
  5. STOP: the results folder's STOP_* files (their line counts) and every trial's "(STOP_launcher)" and
     "(STOP_launcher: ...)" lines (section 8's scoring rule: a FENCE_NAK's refusal counts) are listed in SCORE.md.
"""
import csv, hashlib, importlib.util, json, math, os, re, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
GR = os.path.join(HERE, "..", "..", "..")
sys.path.insert(0, HERE)
import rows_gc  # noqa: E402
_spec = importlib.util.spec_from_file_location("mi_score", os.path.join(GR, "mirror", "impl", "test", "score.py"))
msc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(msc)  # gin-mirror's scorer as a library (unchanged): s2 grammar, status_rs, status_reg, evaluate_pred
s2 = msc.s2

CELLS = os.path.join(HERE, "cells_gc.json")
PREDS = os.path.join(HERE, "predictions_gc.csv")
MPREDS = os.path.join(GR, "mirror", "impl", "test", "predictions_mi.csv")
# columns read from lines the library does not emit yet (rows_gc.py "TODO"): empty in every scored trial -> 자료 부족
LIB_COLS = {"confirm_w_ms", "fin_judge_dev_min_ms", "fin_judge_dev_max_ms", "read_n", "read_ok_n", "read_success_pct",
            "beat_gap_max_ms", "page_torn_n", "tcp_ctrl_bytes", "tcp_data_bytes", "tcp_ctrl_conn_n", "witness_pairs",
            "rec_lost_n", "rec_dup_n", "rec_repair_n", "sendq_deferred", "rnr_n", "async_n", "active_mtu_kv_min",
            "win_changed_after", "fence_order_ok", "fence_names_ok", "fenced_to_fallback_ms", "suspect_n",
            "suspect_stale_ms_min", "suspect_stale_ms_max", "qperr_pair_sent_by_target", "qperr_rec_gen_delta",
            "qperr_probe_gen_delta", "qperr_pair_read_fail", "qperr_records_after", "rejoin_resent", "rejoin_dropped",
            "ckpt_stable_in_mute", "la_fence_sigkill_n", "la_fenced_n", "la_act_refused_why", "stop_judge_ms_min",
            "stop_judge_ms_max", "rst_judge_dev_min_ms", "rst_judge_dev_max_ms", "probe_timeout_n", "witness_expected",
            "probe_ms_page",
            # the runner's new readings (not run on the cluster yet) and the library gate program's real-pid mode
            "ss_tcp_conn_n", "ss_tx_delta_bytes", "ss_rx_delta_bytes", "old_go_ms", "fenced_go_ms",
            "fenced_after_second_ms", "fenced_vs_pidfd_abs_ms"}
EXCL = {"void": "시작 실패(생존 rank가 교환 전에 끝남)", "config_driver": "셀이 정한 빌드가 아닌 프로그램으로 돎",
        "workload": "workload나 mirror 설정이 셀과 다름",
        "config": "셀이 정한 제어 빌드, 증인, 펜스, 정책, 복원 설정과 다르게 돎(또는 복원 셀에서 Resume 거절)",
        "launcher_not_ready": "시행 시작 때 launcher가 두 노드 모두에서 준비되지 않음",
        "launcher_changed": "시행 중 launcher가 끝났거나 바뀜, 또는 시험 스위치 셀 밖의 launcher QP 잃음",
        "not_applied": "주입 기록 없음", "inject_late": "주입이 정한 시각보다 1 s 넘게 어긋남(또는 짝 kill 간격 > 5 ms)",
        "spare_start_fail": "예비 프로세스가 활성화 전에 시작에 실패함", "foreign_gpu": "시행 시작 때 GPU에 다른 프로세스",
        "restore_not_live": "복원 계층 미통합", "kill_before_ckpt": "주입(kill, DIE_RST, STOP, FREEZE_PAGE)이 대상의 첫 확정 체크포인트 전",
        "spareabsent_disarmed": "예비 프로세스를 끝낸 뒤 rank kill 전에 체크포인트가 확정되어 무장이 풀림",
        "cost_invalid": "비용 실행 무효", "surplus": "계획 수를 넘은 시행", "smoke": "smoke(채점 안 함)",
        "pilot": "pilot(채점 안 함)"}
EXCL.update({k: v for k, v in msc.EXCL.items() if k not in EXCL})
TEST_SWITCH_ENV = ("TEST_QP_ERR", "TEST_DROP_UD", "TEST_CREDIT_STALL")


def load_cells():
    return json.load(open(CELLS, encoding="utf-8"))


def mirror_cells():
    c = load_cells()
    return json.load(open(os.path.join(HERE, c["regression"]["source"]), encoding="utf-8"))


def regression_entries(c, mc):
    """{cell@build: mirror entry} of the regression holds at the regression builds"""
    out = {}
    for b in c["regression"]["builds"]:
        for h in c["regression"]["holds"]:
            for e in mc["holds"].get(h, []):
                out["%s@%s" % (e["cell"], b)] = dict(e, build=b)
    return out


def planned(c, reg):
    p = {k: v["n"] for k, v in c["cells"].items()}
    for k, e in reg.items():
        p[k] = max(p.get(k, 0), e["n"])
    cost = c["cost"]
    for fam in cost["families"].values():
        for m in fam["metrics"]:
            for a in fam["arms"]:
                p["cost_%s_%s@%s" % (m, a, fam["lib"][a])] = cost["n_per_arm"] * len(cost["nodes"])
    for name, spec in c["local"].items():
        if spec.get("n"):
            p["local:" + name] = spec["n"]
    return p


def ival(v, default=None):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def launcher_env_of(cell):
    return "+".join("%s=%s" % kv for kv in sorted(cell.get("launcher_env", {}).items()))


def status_gc(r, cell, prereg=None):
    env = cell.get("env", {})
    prereg = prereg or {}
    if ival(r.get("void"), 0):
        return "void"
    if cell.get("driver") and str(r.get("driver", "")) != cell["driver"]:
        return "config_driver"
    want_ow = int(env.get("OVERWRITE", "0"))
    if r.get("overwrite") not in ("", None) and ival(r.get("overwrite"), 0) != want_ow:
        return "workload"
    if str(r.get("mirror_env", "")) not in ("", "unset") and str(r.get("mirror_env")) != env.get("MIRROR", "1"):
        return "workload"
    meta = r.get("_meta", {})
    if meta.get("lib", cell["build"]) != cell["build"]:
        return "config"
    for k, mk, dflt in (("WITNESS", "witness", "1"), ("FENCE", "fence", "lineage"), ("FAULT_POLICY", "policy", "hold"),
                        ("RESTORE", "restore", "1")):
        if meta.get(mk, dflt) != env.get(k, dflt):
            return "config"
    if env.get("RESTORE", "1") == "1" and env.get("FAULT_POLICY", "hold") == "hold" and str(r.get("resume_refused")) == "1":
        return "config"
    # REVIEW_TEST fix 12: the launcher env of the hold, W and the READ period
    if r.get("ctrl") == "rdma":
        want = launcher_env_of(cell)
        for nd in ("rain", "sunny"):
            got = str(meta.get("launcher_env_" + nd, "") or "")
            if (got if got != "-" else "") != want and str(r.get("launcher_ready")) == "1":
                return "config"
    if prereg.get("confirm_ms") is not None and r.get("confirm_w_ms") not in ("", None) and \
            float(r["confirm_w_ms"]) != float(prereg["confirm_ms"]):
        return "config"
    if prereg.get("probe_ms") is not None and r.get("probe_ms_page") not in ("", None) and \
            float(r["probe_ms_page"]) != float(prereg["probe_ms"]):
        return "config"
    if r.get("ctrl") == "rdma":
        if str(r.get("launcher_ready")) != "1":
            return "launcher_not_ready"
        sw = any(s in " ".join(env.values()) for s in TEST_SWITCH_ENV)
        if str(r.get("launcher_same")) == "0" or (not sw and ival(r.get("la_qp_err_n"), 0) > 0):
            return "launcher_changed"
    inj = cell.get("injection", {}).get("kind", "none")
    if inj != "none":
        if str(r.get("inject_ok")) == "0" or (env.get("KILL_RANK") and ival(r.get("applied"), 0) == 0):
            return "not_applied"
        if (ival(r.get("inject_off_ms"), 0) or 0) > 1000 or (ival(r.get("inject_dur_off_ms"), 0) or 0) > 1000:
            return "inject_late"
        if r.get("pair_gap_ms") not in ("", None) and float(r["pair_gap_ms"]) > float(env.get("SPARE_GAP_MS", "5")):
            return "inject_late"
    if str(r.get("spare_start_fail")) == "1" or str(r.get("spare2_start_fail")) == "1":
        return "spare_start_fail"
    if str(r.get("foreign_gpu")) == "1":
        return "foreign_gpu"
    if env.get("SPARE") == "1" and env.get("KILL_RANK"):
        if ival(r.get("restore_live"), 0) == 0:
            return "restore_not_live"
        if str(r.get("ckpt_stable_before_kill")) == "0":
            return "kill_before_ckpt"
    # REVIEW_TEST fix 13: the stop, freeze and self-kill RST cells too (every injected cell with a spare)
    if env.get("SPARE") == "1" and inj != "none" and str(r.get("ckpt_stable_before_inj")) == "0":
        return "kill_before_ckpt"
    if str(r.get("stable_between_pair_kills")) == "1":
        return "spareabsent_disarmed"
    return "candidate"


def status_regression(r, entry, mcells_b):
    s = msc.status_rs(r, mcells_b)
    if s != "candidate":
        return s
    if r.get("ctrl") == "rdma":
        if str(r.get("launcher_ready")) != "1":
            return "launcher_not_ready"
        if str(r.get("launcher_same")) == "0" or ival(r.get("la_qp_err_n"), 0) > 0:
            return "launcher_changed"
    # no second-death exclusion (REVIEW_TEST B3; gin-mirror section 8: a second kill before the re-arm, a failed first
    # restore or a re-arm that never came is a failed condition of its prediction, never an exclusion)
    return "candidate"


def smoke_of(r):
    sub, hold = str(r.get("sub", "")), str(r.get("hold", ""))
    if sub.startswith("smoke") or re.match(r"P0(-r\d+)?$", hold):
        return "smoke"
    if sub.startswith(("pilot", "costpilot")) or hold.startswith(("P", "COSTPILOT")):
        return "pilot"
    return None


def val_empty(v):
    return v is None or v == ""


def eval_part(acc, keys, scored, PLANNED, pooled):
    """one acceptance part on keys; returns (evals, short keys, nodata). A cell key is short below its planned n; a pooled
    key when any cell key in it is short (pooled: {key: [its cell keys]})"""
    per_cell = acc.startswith("per cell:")
    a = acc[len("per cell:"):].strip() if per_cell else acc
    sub = None
    m = re.match(r"subset\((.*?)\):\s*(.*)$", a)
    if m:
        sub, a = m.group(1), m.group(2)
    use = keys if per_cell else keys[:1]
    short, evals, nodata = [], [], False
    for k in use:
        rows = scored.get(k, [])
        if sub is not None:
            rows = [r for r in rows if s2.cond_true(sub, r)]
            if not rows:
                nodata = True
        elif k in pooled:
            if not rows or any(len(scored.get(x, [])) < PLANNED.get(x, 0) for x in pooled[k]):
                short.append(k)
        elif PLANNED.get(k, 0) == 0 or len(rows) < PLANNED.get(k, 0):
            short.append(k)
        refs = sorted(c for c in LIB_COLS if re.search(r"\b" + c + r"\b", a))
        if rows and any(all(val_empty(r.get(c)) for r in rows) for c in refs):
            short.append(k)
        ak = re.sub(r"\bN_SCORED\b", str(len(rows)), a)
        evals.append((k,) + s2.evaluate(ak, {k: rows}, k, s2.NIL))
    return evals, short, nodata


def mirror_part(spec, scored, PLANNED, mpreds):
    want, _, b = spec.rpartition("@")
    ids = [x.strip() for x in want.split(",") if x.strip()]
    sel = [p for p in mpreds if not p["acceptance"].startswith("cost:") and ("all" in ids or p["id"] in ids)]
    missing = [i for i in ids if i != "all" and i not in {p["id"] for p in mpreds}]
    res = []
    for p in sel:
        q = dict(p, cells=p["cells"].replace("@mi", "@" + b))
        keys, evals, verdict, short = msc.evaluate_pred(q, scored, PLANNED)
        res.append((p["id"], verdict, keys, evals, short))
    return res, missing


def cost_eval(spec_cells, rule, rows, c):
    parts = [x.strip() for x in spec_cells.split(":")]
    fam = c["cost"]["families"][parts[1]]
    named = [a for a in parts[2].split(",") if a] if len(parts) > 2 else []
    metrics = [m for m in parts[3].split(",") if m] if len(parts) > 3 else list(fam["metrics"])
    kind, _, arg = rule.partition(":")
    base = fam["base"]
    judged = set(fam.get("judged", [])) & (set(named) if named else set(fam["arms"]))
    lines, short, bad = [], False, False
    for node in c["cost"]["nodes"]:
        for m in metrics:
            vals = {a: sorted(float(r["value"]) for r in rows if r["runner"] == "cost" and r["status"] == "scored"
                              and r.get("metric") == m and r.get("arm") == a and r.get("rx") == node)
                    for a in [base] + [x for x in fam["arms"] if x != base and (not named or x in named)]}
            if any(len(v) < 5 for v in vals.values()):
                short = True
            bv = vals.get(base, [])
            for a, v in vals.items():
                if not v:
                    lines.append("| %s | %s | %s | 0 | - | - | - |" % (node, m, a))
                    continue
                med = statistics.median(v)
                if a == base or not bv:
                    lines.append("| %s | %s | %s | %d | %.3f | - | 기준 |" % (node, m, a, len(v), med))
                    continue
                bmed = statistics.median(bv)
                d = (med - bmed) if not m.startswith("bw") else (bmed - med)
                pct = 100.0 * d / bmed if bmed else float("inf")
                tag = "%+.2f%%" % pct
                if a in judged and kind == "within":
                    ok = pct <= float(arg)
                    bad = bad or not ok
                    tag = ("범위 안 " if ok else "범위 밖 ") + "%s (≤ %s%%)" % (tag, arg)
                else:
                    tag += "(보고만)"
                lines.append("| %s | %s | %s | %d | %.3f | %+.3f | %s |" % (node, m, a, len(v), med, d, tag))
    return ("자료 부족" if short else ("틀림" if bad else "맞음")), lines


def score(R, planned_override=None):
    c = load_cells()
    mc = mirror_cells()
    reg = regression_entries(c, mc)
    PLANNED = planned(c, reg)
    if planned_override:
        PLANNED.update(planned_override)
    mcells_b = {"holds": {"_": list(reg.values())}}
    msc.EXPECT_DRIVER.clear()
    msc.EXPECT_DRIVER.update({k: e.get("driver", "") for k, e in reg.items()})
    orig = mc.get("regression_orig", {})
    rows = rows_gc.all_rows(R)
    for r in rows:
        r["_meta"] = rows_gc.rows_rs.read_meta(r["stem"]) if r.get("runner") not in ("local",) else {}
        if not r.get("hold"):
            r["hold"] = r["_meta"].get("hold", "")
        sm = smoke_of(r)
        if sm:
            r["status"] = sm
        elif r["runner"] == "local":
            r["status"] = "candidate"
        elif r["runner"] == "cost":
            r["status"] = "candidate" if str(r.get("cost_valid")) == "1" else "cost_invalid"
        elif r["runner"] == "mrr":
            r.update(msc.reg_columns(r["stem"], r))
            r["status"] = msc.status_reg(r, orig.get(r["cell"]))
        elif r["key"] in c["cells"]:
            r["status"] = status_gc(r, c["cells"][r["key"]], c.get("prereg"))
        elif r["key"] in reg:
            r["status"] = status_regression(r, reg[r["key"]], mcells_b)
        else:
            r["status"] = "config"
    by_key, scored = {}, {}
    for r in sorted(rows, key=lambda x: (x["key"], x.get("tnum") or 0, x["sub"])):
        by_key.setdefault(r["key"], []).append(r)
    for k, rs in by_key.items():
        cand = [r for r in rs if r["status"] == "candidate"]
        if k.startswith("cost_"):
            per = {}
            for r in cand:
                per.setdefault(r.get("rx"), []).append(r)
            for nr in per.values():
                for i, r in enumerate(nr):
                    r["status"] = "scored" if i < c["cost"]["n_per_arm"] else "surplus"
        else:
            for i, r in enumerate(cand):
                r["status"] = "scored" if i < PLANNED.get(k, 0) else "surplus"
        scored[k] = [r for r in rs if r["status"] == "scored"]
    pooled = {}
    for b in c["builds"]:
        ks = sorted(k for k, rs in by_key.items() if "@" in k and not k.startswith("cost_")
                    and any(r.get("build") == b and r.get("runner") == "gcr" and r["status"] in ("scored", "surplus")
                            for r in rs))
        pooled["build:" + b] = ks
        scored["build:" + b] = [r for k in ks for r in scored.get(k, [])]
    preds = list(csv.DictReader(open(PREDS, encoding="utf-8")))
    mpreds = list(csv.DictReader(open(MPREDS, encoding="utf-8")))
    sha = hashlib.sha256(open(PREDS, "rb").read()).hexdigest()
    frozen = ""
    for pr in (os.path.join(HERE, "..", "..", "PREREG.txt"), os.path.join(HERE, "PREREG.txt")):
        if os.path.exists(pr):
            frozen = open(pr).read()
            break
    results = []
    for p in preds:
        acc = p["acceptance"].strip()
        keys = [x.strip() for x in p["cells"].split(";") if x.strip()]
        det = {"evals": [], "short": [], "mirror": [], "cost": [], "nodata": False, "missing": []}
        if acc.startswith("cost:"):
            v, det["cost"] = cost_eval(keys[0], acc.split("rule=", 1)[1].strip(), rows, c)
            results.append((p, keys, v, det))
            continue
        ok_all = True
        for part in [x.strip() for x in acc.split(";;")]:
            if part.startswith("mirror:"):
                res, missing = mirror_part(part[len("mirror:"):].strip(), scored, PLANNED, mpreds)
                det["mirror"] += res
                det["missing"] += missing
                if any(v == "자료 부족" for _, v, _, _, _ in res) or missing or not res:
                    det["short"].append(part)
                ok_all = ok_all and all(v == "맞음" for _, v, _, _, _ in res)
                continue
            m = re.match(r"([A-Za-z0-9_]+@[a-z]+|build:[a-z]+|local:[a-z_]+):\s*(.*)$", part)
            pk, pa = ([m.group(1)], m.group(2)) if m else (keys, part)
            ev, sh, nd = eval_part(pa, pk, scored, PLANNED, pooled)
            det["evals"] += ev
            det["short"] += sh
            det["nodata"] = det["nodata"] or nd
            ok_all = ok_all and all(e[1] for e in ev)
        if det["nodata"]:
            v = "자료 없음(실패 아님)"
        elif det["short"]:
            v = "자료 부족"
        else:
            v = "맞음" if ok_all else "틀림"
        results.append((p, keys, v, det))
    # trials_scored.csv
    cols = rows_gc.columns(rows)
    for r in rows:
        for col in cols:
            r.setdefault(col, "")
    lead = ["key", "status", "sub", "id", "cell", "build", "runner", "hold"]
    with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=lead + [x for x in cols if x not in lead], extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["sub"], x["key"], x.get("tnum") or 0)):
            w.writerow(r)
    # SCORE.md
    stops = sorted(x for x in os.listdir(R) if x.startswith("STOP_"))
    la_stop = [(r["id"], ival(r.get("la_stop_n"), 0)) for r in rows if ival(r.get("la_stop_n"), 0) > 0]
    L = ["# gin-control 채점 결과 (시험 쪽)", "",
         "`score_gc.py`가 원자료에서 만들었다. 손으로 고친 값은 없다. 판정식 원문은 `predictions_gc.csv`, 문법은 gin-mirror의 `score.py`(s2_close 3.2)와 이 파일 머리의 꼴이다.", "",
         "- 예측 파일 sha256: `%s`. `PREREG.txt`의 값과 %s." % (sha, "같다" if sha in frozen else "다르다(사전 등록한 파일이 아니거나 아직 사전 등록 전)"),
         "- 시행 수: %d. 판정한 시행: %d. smoke: %d, pilot: %d(따로 셈, 채점 안 함)." % (
             len(rows), sum(len(v) for k, v in scored.items() if not k.startswith("build:")),
             sum(1 for r in rows if r["status"] == "smoke"), sum(1 for r in rows if r["status"] == "pilot")),
         "- STOP 파일: %s." % (", ".join("`%s`(%d줄)" % (x, sum(1 for _ in open(os.path.join(R, x)))) for x in stops) or "없음"),
         "- launcher의 `(STOP_launcher)`와 `(STOP_launcher: …)` 줄(8절 채점 규칙, FENCE_NAK 포함): %d줄, 시행 %s." % (
             sum(n for _, n in la_stop), ", ".join("%s(%d)" % x for x in la_stop) or "없음"), "",
         "## 판정 요약", "", "| 예측 | 셀 | n | 판정 |", "|---|---|--:|---|"]
    for p, keys, v, det in results:
        ns = " / ".join(str(len(scored.get(k, []))) for k in keys if not k.startswith(("mirror:", "cost:")))
        L.append("| %s (%s) | %s | %s | %s |" % (p["predicted"], p["id"], ", ".join("`%s`" % k for k in keys), ns or "-", v))
    L += ["", "## 예측별 세부", ""]
    for p, keys, v, det in results:
        L += ["### %s: %s" % (p["id"], v), "", "- 판정식: `%s`" % p["acceptance"]]
        if p.get("todo"):
            L.append("- 표시: %s" % p["todo"])
        if det["short"]:
            L.append("- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): %s" % ", ".join(det["short"]))
        for k, ok, dd, expr in det["evals"]:
            L.append("- `%s`: 판정한 시행 %d회, 대입한 식 `%s` → %s" % (k, len(scored.get(k, [])), expr, "참" if ok else "거짓"))
            for inner, cnt, n, fs, ts, tail in dd:
                L.append("  - `count(%s)` = %d/%d. 만족하지 않은 시행: %s" % (
                    inner, cnt, n, ", ".join(os.path.basename(str(x)) for x in fs) if fs else "없음"))
        for mid, mv, mkeys, mev, msh in det["mirror"]:
            L.append("- gin-mirror `%s` (%s): %s" % (mid, ", ".join(mkeys), mv))
        if det["missing"]:
            L.append("- gin-mirror 예측 표에 없는 ID: %s" % ", ".join(det["missing"]))
        if det["cost"]:
            L += ["", "| 받는 노드 | 지표 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |", "|---|---|---|--:|--:|---|---|"] + det["cost"]
        L.append("")
    L += ["## 비용 보고(판정 없음)", "", "| 받는 노드 | 지표 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |", "|---|---|---|--:|--:|---|---|"]
    for f, spec in c["cost"]["families"].items():
        _, lines = cost_eval("cost:%s" % f, "report", rows, c)
        L += lines or ["| (비용 실행 없음) |  |  |  |  |  |  |"]
    L += ["", "## 셀별 시행 수와 따로 센 시행", "", "| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |", "|---|--:|--:|--:|---|"]
    for k in sorted(set(list(by_key) + list(PLANNED))):
        rs = by_key.get(k, [])
        apart = {}
        for r in rs:
            if r["status"] != "scored":
                apart.setdefault(r["status"], []).append(r["id"])
        txt = "; ".join("%s: %s" % (EXCL.get(s, s), ", ".join(v)) for s, v in sorted(apart.items())) or "없음"
        L.append("| `%s` | %d | %d | %d | %s |" % (k, PLANNED.get(k, 0), len(rs), len(scored.get(k, [])), txt))
    L.append("")
    open(os.path.join(R, "SCORE.md"), "w", encoding="utf-8").write("\n".join(L))
    print("\n".join("%s: %s" % (p["id"], v) for p, _, v, _ in results))
    return {p["id"]: v for p, _, v, _ in results}, rows


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    score(os.path.abspath(sys.argv[1]))
