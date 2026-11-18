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
     cells_gc.json "prereg", or its Resume was refused where the cell expects the restore for a reason that names a
     configuration: rows_gc.CONFIG_REFUSALS), launcher_stale (a stale
     launcher socket or process on a node at the trial's start: nothing ran; section 8's per-trial launcher rule of
     2026-10-22), launcher_not_ready (the start check: a launcher of the trial did not come up), launcher_changed (a launcher
     ended or changed during the trial, or a launcher QP loss outside the test-switch cells), a ring that never went live
     within the setup bound (REVIEW_INT3 F7) is config when a rank's setup agreement turned recovery off for an MTU or a
     control path that differ, not_applied (the injection's record is missing), inject_late (the runner's injection more than 1 s from its
     plan, a stop's length more than STOP_LEN_TOL_MS (50) off, or the spare-absent cell's two kills more than PAIR_GAP_LIMIT_MS
     (10) apart; both fixed 2026-10-24 from pilot 1, EXPERIMENT 8), spare_start_fail,
     (also: a second death's spare that is not the launcher's, rows_gc.py spare2_daemon_ok 0: the same rank's second restore
     needs the daemon's next spare, incarnation 2; another rank's, that node's own warm spare), foreign_gpu, restore_not_live, kill_before_ckpt (the kill, DIE_RST, STOP or FREEZE_PAGE before the subject's first
     stable checkpoint, in every cell with a spare), spareabsent_disarmed (a stable checkpoint between the spare's kill and
     the rank's), surplus. A second death is never excluded: a second kill before the re-arm, a first restore that failed or
     a re-arm that never came counts as a failed condition (gin-mirror's section 8, pre-registered; the coordinator's
     decision of 2026-10-17 for @gct and @gc). gin-mirror's regression rows take gin-mirror's own statuses (its score.py)
     plus the launcher exclusions here.
     Codex review 2026-10-23 item 4: a Resume refusal for any other reason and a ring that did not go live under the
     cell's configuration are prep_failure: not an exclusion; among the first PLANNED trials (candidates and prep failures
     by trial number) a prep failure keeps its place and is never refilled; SCORE.md and the output give per prediction and
     key the plan, the run, the exclusions by reason, the prep failures, the scored n, the conditional (over the scored)
     and the whole-run (over the scored and the prep failures) success rates.
  3. per key cell@build the first PLANNED candidates by trial number are scored (a key is short when its scored trials
     and prep failures are fewer than planned); "자료 부족" when a key of this study (its
     own cells and the regression cells its own formulas read) has fewer scored trials than planned (section 8 refills the
     exclusions; REVIEW_TEST fix 11), when a pooled key "build:<b>" has a cell with trials below its plan, or when a library
     column its formula reads (LIB_COLS: from TODO lines and the runner's new readings) is empty in every scored trial.
     gin-mirror's own predictions ("mirror:") keep that study's rule (its score.py).
  4. the acceptance grammar is gin-mirror's (s2_close 3.2: count(<expr>), N_SCORED, median) with these forms:
       <expr>                          on the first key of the cells column (check_cells_gc.py fails a row with two or
                                       more keys and such a part, 2026-10-27: write "per cell:" or "<key>:")
       per cell: <expr>                on every key (each key against the same k; gpuhang_fence_restore since 2026-10-27)
       <key>: <expr> ;; <key>: <expr>  each part on its key; every part must hold
       subset(<cond>): <expr>          the key's scored rows where cond holds (N_SCORED their number); none -> "자료 없음"
       mirror: <id,...|all>@<build>    gin-mirror's predictions_mi.csv rows (cost rows left out) with @mi -> @<build>,
                                       judged by gin-mirror's score.py; every one 맞음 -> 맞음
       cost: rule=within:<pct> [judged_nodes=<n,...>]   the cost family per receiving node (cells
                                       "cost:<family>:<arms>:<metrics>"); with judged_nodes only those receiving nodes are
                                       judged and the others reported (2026-10-24: rain's receive latency is quantized to
                                       1 024 ns, so cost_probe_lat4k judges sunny's only)
     predictions_gc.csv kind (item 5): safety predictions hold only when every count() part is true on every scored
     trial (0 failures); perf keep their rule's threshold, but every safety term of the rule (SAFETY_TERMS, in the rule's
     own parts and in the gin-mirror rules a "mirror:" part names) is evaluated on every scored trial of its part's keys:
     one false term on one trial turns a 맞음 or 틀림 into "재검토(안전성 항 어긋남 k/n)" (k the scored trials with a false
     term, n the scored trials the terms were evaluated on; EXPERIMENT 8, 2026-10-23), and SCORE.md lists the trials and
     their terms; cost is the cost family. EXPERIMENT 8, 2026-10-27 after pilot 4 (user decision 2): a term is read only
     on the trials where the action it guards happened (term_applies: the fence terms FENCE_TERMS when a FENCE was sent,
     FENCED reported or a restore attempted, the restore terms RESTORE_TERMS unless the trial ended in fallback without a
     restore); a fallback trial (fallback_trial) is a perf failure of the rule, never a 안전성 어긋남, and SCORE.md lists it
     as "fallback(복원 없음)".
     EXPERIMENT 8 (2026-10-23, DRAFT; data_gaps): a scored trial on which a count() is false only because it read an empty
     required summary column (REQUIRED_COLS: the control and probe summaries, with rows_gc.py's marker of the gap) is
     "자료 부족" for that prediction, neither a pass nor a fail, and SCORE.md lists it with the columns; the count is judged
     over the other scored trials against the pre-registered k (since 2026-10-27, user decision 1: "count(..) >= N_SCORED"
     takes k = the key's planned n less its preparation failures, EFF; before, the trials with data): fewer trials with
     data than k -> "자료 부족(n<k)"; a safety prediction's 0-failure rule runs over the trials with data (a measured
     failure there is 틀림 even when the key is 자료 부족(n<k), and since 2026-11-18 also when the key is short, 자료 부족:
     fewer scored trials than planned, e.g. after a STOP; never 자료 없음(실패 아님)); a perf rule's safety term on such a
     column is 자료 부족 on that trial, not a failure.
     keys "build:<b>" pool every scored gin-control-runner trial of build b (no_tcp_control, long_hold_lane), "local:<x>" the
     local rows.
  5. STOP: the results folder's STOP_* files (their line counts), every trial's "(STOP_launcher)" and
     "(STOP_launcher: ...)" lines, the launchers' and the rank and spare processes' (with the rank side's "launcher Unix
     socket closed" lines; REVIEW_INT3 F6), (section 8's scoring rule: a FENCE_NAK's refusal counts; the spare-absent cells' one
     expected respawn-cap line apart, rows_gc.py) and the trials whose launcher did not come up or found a stale launcher
     socket or process (section 8's per-trial launcher rule) are listed in SCORE.md.
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
            "win_changed_after", "win_verified", "fence_order_ok", "fence_names_ok", "fenced_to_fallback_ms", "suspect_n",
            "suspect_stale_ms_min", "suspect_stale_ms_max", "qperr_pair_sent_by_target", "qperr_rec_gen_delta",
            "qperr_probe_gen_delta", "qperr_pair_read_fail", "qperr_records_after", "rejoin_resent", "rejoin_dropped",
            "ckpt_stable_in_mute", "la_fence_sigkill_n", "la_fenced_n", "la_act_refused_why", "stop_judge_ms_min",
            "stop_judge_ms_max", "rst_judge_dev_min_ms", "rst_judge_dev_max_ms", "probe_timeout_n", "witness_expected",
            "probe_ms_page", "ring_live_pairs",
            # the runner's new readings (not run on the cluster yet) and the library gate program's real-pid mode
            "ss_tcp_conn_n", "ss_tx_delta_bytes", "ss_rx_delta_bytes", "old_go_ms", "fenced_go_ms",
            "fenced_after_second_ms", "fenced_vs_pidfd_abs_ms",
            # 2026-10-27: the counterexample cells' page-dependent and probe-summary columns (rows_gc.py)
            "suspect_any_n", "quiet_periods"}
EXCL = {"void": "시작 실패(생존 rank가 교환 전에 끝남)", "config_driver": "셀이 정한 빌드가 아닌 프로그램으로 돎",
        "workload": "workload나 mirror 설정이 셀과 다름",
        "config": "셀이 정한 제어 빌드, 증인, 펜스, 정책, 복원 설정과 다르게 돎(또는 복원 셀에서 Resume 거절)",
        "launcher_not_ready": "시행 시작 때 launcher가 두 노드 모두에서 준비되지 않음",
        "launcher_stale": "시행 시작 때 앞 launcher의 소켓이나 프로세스가 노드에 남아 있음(아무것도 돌지 않음)",
        "launcher_changed": "시행 중 launcher가 끝났거나 바뀜, 또는 시험 스위치 셀 밖의 launcher QP 잃음",
        "not_applied": "주입 기록 없음", "inject_late": "주입이 정한 시각보다 1 s 넘게, 멈춤 길이가 50 ms 넘게 어긋남(또는 짝 kill 간격 > 10 ms)",
        "spare_start_fail": "예비 프로세스가 활성화 전에 시작에 실패함", "foreign_gpu": "시행 시작 때 GPU에 다른 프로세스",
        "restore_not_live": "복원 계층 미통합", "kill_before_ckpt": "주입(kill, DIE_RST, STOP, FREEZE_PAGE)이 대상의 첫 확정 체크포인트 전",
        "spareabsent_disarmed": "예비 프로세스를 끝낸 뒤 rank kill 전에 체크포인트가 확정되어 무장이 풀림",
        "cost_invalid": "비용 실행 무효", "surplus": "계획 수를 넘은 시행", "smoke": "smoke(채점 안 함)",
        "pilot": "pilot(채점 안 함)"}
EXCL.update({k: v for k, v in msc.EXCL.items() if k not in EXCL})
TEST_SWITCH_ENV = ("TEST_QP_ERR", "TEST_DROP_UD", "TEST_CREDIT_STALL")
# EXPERIMENT 8, fixed 2026-10-24 before the pre-registration (pilot 1): a SIGSTOP's measured length (SIGCONT - SIGSTOP) may
# be this far from the cell's STOP_MS (pilot 1: +1.7 to +12.2 ms over six trials; before: 1 s), and the spare-absent cell's
# spare kill -> rank kill gap this long (the runner's target stays SPARE_GAP_MS 5; pilot 1 measured 5.032 ms; before: 5 ms)
STOP_LEN_TOL_MS = 50.0
PAIR_GAP_LIMIT_MS = 10.0
EXCL["no_gate"] = "관문 프로그램 없이 돈 시험 장치(gate_proc_gc.py) 시행: 관문 열 없음, 보고만"
EXCL["prep_failure"] = "준비 실패(설정이 맞는데 Resume 거절이나 링 live 실패; 따로 세고 채우지 않음)"
KINDS = ("safety", "perf", "cost")
# item 5 and EXPERIMENT 8 (2026-10-23): the safety terms of section 3's rules, by their rows_gc.py / gin-mirror columns:
# data equality (data_equal, ow_data_equal), no re-execution (no_reexec), no lost or duplicate record or REJOIN
# (rec_lost_n, rec_dup_n, rejoin_accept_dup_n), FENCED before the activation (fence_order_ok; there is no separate
# "fenced before activate" column) with both phase names (fence_names_ok), the window checked complete and unchanged after
# the fence (win_verified; win_changed_after for a rule that still names it), the survivors' wait held and the revived
# rank done (wait_held, revived_done), the subject ended by the fence (subject_fenced). Inside a perf prediction one false
# term on one scored trial makes the verdict 재검토 (perf_review)
SAFETY_TERMS = ("data_equal", "ow_data_equal", "no_reexec", "rec_lost_n", "rec_dup_n", "rejoin_accept_dup_n",
                "fence_order_ok", "fence_names_ok", "win_verified", "win_changed_after", "wait_held", "revived_done",
                "subject_fenced")
SAFETY_TERM = re.compile(r"\b(%s)\s*==\s*(\d+)\b" % "|".join(SAFETY_TERMS))
# EXPERIMENT 8, 2026-10-27 after pilot 4 (user decision 2): a perf rule's safety term is read only on the trials where the
# action it guards happened. Pilot 4's waiting-survivor cell ended twice in a fallback with no fence and no restore, and
# its empty fence_order_ok, wait_held 0, revived_done 0, ow_data_equal 0 and win_verified empty or 0 then read as a
# safety violation (RECHECK.md 3 (나)) where nothing was activated or restored. The predicates use existing rows_gc.py
# columns only; a row without any of a predicate's columns keeps the term (unknown is never "not applicable")
FENCE_TERMS = ("fence_order_ok", "fence_names_ok", "win_verified", "win_changed_after", "subject_fenced")
RESTORE_TERMS = ("wait_held", "revived_done", "ow_data_equal", "data_equal")
_RESTORE_COLS = ("spare_used", "restore_count", "t_publish_ms")
_FENCE_COLS = ("fence_sent", "fenced", "la_fence_sigkill_n", "la_fenced_n")


def restore_tried(r):
    """a restore was attempted or published: a spare used (rows_gc.py spare_used: a spare's restored line, a survivor's
    "restored as incarnation" line or the launcher's ACCEPTED activation), a restored line (restore_count) or a survivor's
    "published" line (t_publish_ms); None when the row has none of these columns"""
    if all(val_empty(r.get(c)) for c in _RESTORE_COLS):
        return None
    return (ival(r.get("spare_used"), 0) or 0) >= 1 or (ival(r.get("restore_count"), 0) or 0) >= 1 or \
        not val_empty(r.get("t_publish_ms"))


def fallback_trial(r):
    """a trial that ended in fallback without a restore: no restore attempted (restore_tried false) and at least one
    survivor's wait let go (surv_released >= 1)"""
    return restore_tried(r) is False and (ival(r.get("surv_released"), 0) or 0) >= 1


def fence_acted(r):
    """a FENCE was sent or FENCED reported for the subject (the buddy's FENCING or FENCED line, the launcher's fence
    SIGKILL or FENCED line), or a restore attempted (an activation without a fence keeps the fence terms, so a missing
    fence still shows); True when the row has none of these columns"""
    if all(val_empty(r.get(c)) for c in _FENCE_COLS + _RESTORE_COLS):
        return True
    return bool(restore_tried(r)) or any((ival(r.get(c), 0) or 0) >= 1 for c in _FENCE_COLS)


def term_applies(term, r):
    """whether a perf rule's safety term (its text, e.g. "fence_order_ok == 1") is read on row r: the fence terms when
    fence_acted and the trial is no fallback trial, the restore terms unless it is a fallback trial, the others always"""
    name = term.split("==")[0].strip()
    if name in FENCE_TERMS:
        return fence_acted(r) and not fallback_trial(r)
    if name in RESTORE_TERMS:
        return not fallback_trial(r)
    return True
APART = ("scored", "prep_failure", "surplus", "smoke", "pilot")


def kind_of(p):
    """predictions_gc.csv kind: safety, perf or cost (a cost: rule is cost; an empty kind reads as perf)"""
    k = (p.get("kind") or "").strip()
    return k if k in KINDS else ("cost" if p["acceptance"].strip().startswith("cost:") else "perf")


def all_evals(det):
    """(key, details) of every count() evaluation of a prediction: its own parts and gin-mirror's"""
    out = [(k, dd) for k, ok, dd, expr in det["evals"]]
    for _, _, _, mev, _ in det["mirror"]:
        out += [(e[0], e[2]) for e in mev]
    return out


def safety_fails(det):
    """[(key, inner, true count, n)] of the count() parts that failed a scored trial (item 5's 0-failure rule), n the
    trials with data (a 자료 부족 trial of data_gaps is neither a pass nor a fail; EXPERIMENT 8, 2026-10-23)"""
    gn = {(k, inner): len(g) for k, inner, g, *_ in det.get("gaps", [])}
    return [(k, inner, cnt, n - gn.get((k, inner), 0)) for k, dd in all_evals(det) for inner, cnt, n, *_ in dd
            if cnt != n - gn.get((k, inner), 0)]


def safety_parts(p, keys, mpreds=()):
    """[(key, rule text)]: each count() part of a rule with the keys it is evaluated on (a "<key>:" part on that key, a
    "per cell:" part on every key, a plain part on the first key, a "mirror:" part as each named gin-mirror rule on its
    first key with @mi -> @<build>); a subset() part's terms are read on the subset's rows only (safety_rows)"""
    out = []
    for part in [x.strip() for x in p["acceptance"].split(";;") if x.strip()]:
        if part.startswith("mirror:"):
            want, _, b = part[len("mirror:"):].strip().rpartition("@")
            ids = [x.strip() for x in want.split(",") if x.strip()]
            for q in mpreds:
                if q["acceptance"].startswith("cost:") or not ("all" in ids or q["id"] in ids):
                    continue
                qk = [x.strip().replace("@mi", "@" + b) for x in q["cells"].split(";") if x.strip()]
                qa = q["acceptance"]
                for k in (qk if qa.startswith("per cell:") else qk[:1]):
                    out.append((k, qa))
            continue
        m = re.match(r"([A-Za-z0-9_]+@[a-z]+|build:[a-z]+|local:[a-z_]+):\s*(.*)$", part)
        if m:
            out.append((m.group(1), m.group(2)))
        elif part.startswith("per cell:"):
            out += [(k, part[len("per cell:"):]) for k in keys]
        elif keys:
            out.append((keys[0], part))
    return out


def perf_safety_terms(p, det, scored, mpreds=()):
    """[(key, term, failing trial ids, n, 자료 부족 trial ids, 해당 없음 trial ids)]: a perf rule's safety terms
    (SAFETY_TERMS, each part on its own keys) on the scored trials of those keys (the subset's rows for a subset() part)
    where the action the term guards happened (term_applies; the others are 해당 없음, a fallback trial among them); a term
    on an empty required column (data_gaps) is 자료 부족 on that trial, not a failure, and n counts the trials read with data"""
    out = {}
    keys = [x.strip() for x in p["cells"].split(";") if x.strip()]
    for k, text in safety_parts(p, keys, mpreds):
        rows = scored.get(k, [])
        m = re.search(r"subset\((.*?)\):", text)
        if m:
            rows = [r for r in rows if s2.cond_true(m.group(1), r)]
        for t in sorted({x.group(0) for x in SAFETY_TERM.finditer(text)}):
            if rows and (k, t) not in out:
                use = [r for r in rows if term_applies(t, r)]
                na = sorted(r["id"] for r in rows if not term_applies(t, r))
                g = data_gaps(t, use)
                out[(k, t)] = ([r["id"] for r in use if r["id"] not in g and not s2.cond_true(t, r)], len(use) - len(g),
                               sorted(g), na)
    return [(k, t, fs, n, gs, na) for (k, t), (fs, n, gs, na) in sorted(out.items())]


def perf_fallbacks(p, scored, mpreds=()):
    """the scored trials of a perf rule's keys that ended in fallback without a restore (fallback_trial), when the rule
    has a fence or restore term: listed in SCORE.md as "fallback(복원 없음)" (a perf failure, not a 안전성 어긋남)"""
    keys = [x.strip() for x in p["cells"].split(";") if x.strip()]
    ids = set()
    for k, text in safety_parts(p, keys, mpreds):
        if any(x.group(1) in FENCE_TERMS + RESTORE_TERMS for x in SAFETY_TERM.finditer(text)):
            ids.update(r["id"] for r in scored.get(k, []) if fallback_trial(r))
    return sorted(ids)


def perf_review(ps):
    """(k, n, {trial id: [terms]}) of a perf prediction's safety terms: k scored trials with a false term among the n
    scored trials the terms were read on (per key the most any term had data on)"""
    bad, nk = {}, {}
    for k, t, fs, n, *_ in ps:
        nk[k] = max(nk.get(k, 0), n)
        for i in fs:
            bad.setdefault(i, []).append(t)
    return len(bad), sum(nk.values()), bad


def key_counts(k, by_key, scored, prep, PLANNED, pooled):
    """(planned, run, {excluded reason: n}, prep failures, scored) of one key (a pooled key: its cells summed)"""
    ks = pooled.get(k, [k])
    rs = [r for x in ks for r in by_key.get(x, []) if r["status"] not in ("smoke", "pilot")]
    exc = {}
    for r in rs:
        if r["status"] not in APART:
            exc[r["status"]] = exc.get(r["status"], 0) + 1
    return (sum(PLANNED.get(x, 0) for x in ks), len(rs), exc, sum(prep.get(x, 0) for x in ks), len(scored.get(k, [])))


def load_cells():
    return json.load(open(CELLS, encoding="utf-8"))


def mirror_cells():
    c = load_cells()
    return json.load(open(os.path.join(HERE, c["regression"]["source"]), encoding="utf-8"))


def regression_entries(c, mc):
    """{cell@build: mirror entry} of the regression holds at the regression builds (only builds.<b>.cells when listed)"""
    out = {}
    for b, spec in c["regression"]["builds"].items():
        keep = spec.get("cells")  # the 2026-10-22 trim: @gct plans only these cells
        for h in c["regression"]["holds"]:
            for e in mc["holds"].get(h, []):
                if keep is not None and e["cell"] not in keep:
                    continue
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
    # Codex review 2026-10-23 item 4: a Resume refusal is a configuration exclusion only when its reason names a
    # configuration (rows_gc.CONFIG_REFUSALS: resume_refusal "config"); any other refusal is a preparation failure of the
    # library under the cell's configuration (prep_failure below: counted, never refilled)
    refused = env.get("RESTORE", "1") == "1" and env.get("FAULT_POLICY", "hold") == "hold" and str(r.get("resume_refused")) == "1"
    if refused and r.get("resume_refusal") != "prep":
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
        if r.get("launcher_stale") not in ("", None, "-"):
            return "launcher_stale"
        if str(r.get("launcher_ready")) != "1":
            return "launcher_not_ready"
        sw = any(s in " ".join(env.values()) for s in TEST_SWITCH_ENV)
        if str(r.get("launcher_same")) == "0" or (not sw and ival(r.get("la_qp_err_n"), 0) > 0):
            return "launcher_changed"
        if str(r.get("ring_live_all")) == "0":  # REVIEW_INT3 F7: no live line within the setup bound on some rank
            return ring_status(r)
    if refused:
        return "prep_failure"
    inj = cell.get("injection", {}).get("kind", "none")
    if inj != "none":
        if str(r.get("inject_ok")) == "0" or (env.get("KILL_RANK") and ival(r.get("applied"), 0) == 0):
            return "not_applied"
        if (ival(r.get("inject_off_ms"), 0) or 0) > 1000:
            return "inject_late"
        pre = prereg or {}
        if r.get("inject_dur_off_ms") not in ("", None) and \
                float(r["inject_dur_off_ms"]) > float(pre.get("stop_len_tol_ms", STOP_LEN_TOL_MS)):
            return "inject_late"
        if r.get("pair_gap_ms") not in ("", None) and \
                float(r["pair_gap_ms"]) > float(pre.get("pair_gap_limit_ms", PAIR_GAP_LIMIT_MS)):
            return "inject_late"
    if str(r.get("spare_start_fail")) == "1" or str(r.get("spare2_start_fail")) == "1" or spare2_not_daemon(r):
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


def ring_status(r):
    """a ring that did not go live (REVIEW_INT3 F7): config when a rank's setup agreement turned recovery off for an MTU
    or a control path that differ (rows_gc ring_not_live_class), else a preparation failure (item 4)"""
    return "config" if r.get("ring_not_live_class") == "config" else "prep_failure"


def spare2_not_daemon(r):
    """a second death with a second spare wanted, in an rdma build: its spare is not the launcher's (rows_gc.py)"""
    return r.get("ctrl") == "rdma" and r.get("_meta", {}).get("spare2_wanted") == "1" and str(r.get("spare2_daemon_ok")) == "0"


def status_regression(r, entry, mcells_b):
    if r.get("ctrl") == "rdma" and r.get("launcher_stale") not in ("", None, "-"):
        return "launcher_stale"
    # item 4: gin-mirror's status_rs takes every Resume refusal as config; a preparation refusal is not one here
    prep = (str(r.get("resume_refused")) == "1" and r.get("resume_refusal") == "prep" and
            not str(r.get("cell", "")).startswith(msc.REFUSAL))
    s = msc.status_rs(dict(r, resume_refused=0) if prep else r, mcells_b)
    if s != "candidate":
        return s
    if spare2_not_daemon(r):
        return "spare_start_fail"
    if r.get("ctrl") == "rdma":
        if str(r.get("launcher_ready")) != "1":
            return "launcher_not_ready"
        if str(r.get("launcher_same")) == "0" or ival(r.get("la_qp_err_n"), 0) > 0:
            return "launcher_changed"
        if str(r.get("ring_live_all")) == "0":  # REVIEW_INT3 F7
            return ring_status(r)
    if prep:
        return "prep_failure"
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


# EXPERIMENT 8 (2026-10-23, DRAFT): the summary columns every scored trial must carry, with the rows_gc.py columns that name
# a missing summary or counter. Such a column is empty only through a data gap (rows_gc.py: "an absent counter is never 0");
# an event column (a judgement time, a launcher line) stays a measurement when empty
_CTRL_MARK = ("ctrlsum_missing", "ctrlsum_fields_missing")
_PROBE_MARK = ("probe_missing",)
REQUIRED_COLS = dict([(c, _CTRL_MARK) for c in (
    "tcp_ctrl_bytes", "tcp_data_bytes", "tcp_record_bytes_sum", "tcp_record_bytes_prelive", "tcp_record_bytes_unsplit",
    "tcp_conns_lib", "witness_conns_lib", "tcp_ctrl_conn_n", "witness_pairs", "witness_expected", "rec_lost_n", "rec_dup_n",
    "rec_repair_n", "sendq_deferred", "sendq_max", "async_n", "rnr_n")] + [(c, _PROBE_MARK) for c in (
    "read_n", "read_ok_n", "dev_read_n", "dev_read_ok_n", "read_page_success_pct", "read_dev_success_pct",
    "read_success_pct", "page_torn_n", "read_lat_med_us_max", "read_lat_max_us", "beat_gap_max_ms")])
# 2026-10-24 after pilot 2: the runner's ss delta over the processes alive at both reads; empty with ss_excluded set when
# a live process's delta was negative (a socket closed between the reads) or the second snapshot is missing (rows_gc.py
# ss_deltas): 자료 부족 for that trial, never a 0 and never a fail
REQUIRED_COLS["ss_tx_delta_bytes"] = ("ss_excluded",)
# 2026-10-27: quiet_periods reads every observer's probe summary for the subject: empty only when one is missing (rows_gc.py;
# probe_missing names it), so such a trial is 자료 부족 for quiet_compute_no_judge (a missing end line is 0, a measured fail)
REQUIRED_COLS["quiet_periods"] = _PROBE_MARK


class _Unknown(s2.Nil):
    """an empty required column read by a rule (data_gaps): every use records its name and holds (an optimistic reading:
    a rule that is false even so failed on the measured columns)"""
    def __init__(self, name, used):
        self.name, self.used = name, used

    def _use(self, *a):
        self.used.add(self.name)
        return True

    def _same(self, *a):
        self.used.add(self.name)
        return self

    __eq__ = __ne__ = __lt__ = __le__ = __gt__ = __ge__ = __bool__ = _use
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = __abs__ = _same
    __and__ = __rand__ = _same

    def __hash__(self):
        return 0


class _GapNS(dict):
    def __init__(self, row, used):
        super().__init__()
        self.row, self.used = row, used

    def __missing__(self, k):
        if k not in self.row:
            raise KeyError(k)
        v = self.row[k]
        if k in REQUIRED_COLS and val_empty(v) and any(not val_empty(self.row.get(m)) for m in REQUIRED_COLS[k]):
            return _Unknown(k, self.used)
        return s2.val(v)


def data_gaps(inner, rows):
    """EXPERIMENT 8 (2026-10-23, DRAFT): {trial id: (empty required columns, the gap markers)} of the rows where count(inner)
    is false only because it read an empty required column (REQUIRED_COLS, with its marker set): false as read, true with
    those columns unknown. Such a trial is 자료 부족 for the rule, neither a pass nor a fail; a rule false on its measured
    columns whatever the missing ones hold is a fail. nonempty(<col>) is a presence test, a measurement"""
    out = {}
    for r in rows:
        if s2.cond_true(inner, r):
            continue
        used = set()
        try:
            hold = bool(eval(inner, {"__builtins__": {}, "has": s2.has, "nonempty": s2.nonempty, "maskbit": s2.maskbit,
                                     "abs": abs}, _GapNS(r, used)))
        except (TypeError, ValueError):
            hold = False
        if used and hold:
            marks = sorted({m for c in used for m in REQUIRED_COLS[c] if not val_empty(r.get(m))})
            out[r["id"]] = (sorted(used), " ".join("%s=%s" % (m, r[m]) for m in marks), r.get("stem"))
    return out


def with_data_n(a, rows, n_planned=None):
    """an acceptance text's count() parts on rows with their data gaps: (the text with each "count(..) >= N_SCORED" taking
    k, [(inner, gaps, trials with data, k)]); k the pre-registered threshold of ">= <k>", for N_SCORED the key's planned
    n less its preparation failures (n_planned: EFF; the scored rows when not given), at least 1 (EXPERIMENT 8,
    2026-10-27 after pilot 4, user decision 1: a data gap no longer shrinks N_SCORED to the trials with data, so a gap
    makes the count 자료 부족(n<k) instead of passing on the remaining trials); None for another form"""
    kn = max(len(rows) if n_planned is None else n_planned, 1)
    parts, info, pos = [], [], 0
    for s, e, inner in s2.split_counts(a):
        g = data_gaps(inner, rows)
        nd = len(rows) - len(g)
        m = re.match(r"\s*>=\s*(N_SCORED\b|\d+)", a[e:])
        k = None
        parts.append(a[pos:e])
        pos = e
        if m and m.group(1) == "N_SCORED":
            parts.append(a[e:e + m.end()].replace("N_SCORED", str(kn)))
            pos, k = e + m.end(), kn
        elif m:
            k = int(m.group(1))
        info.append((inner, g, nd, k))
    parts.append(a[pos:])
    return "".join(parts), info


def eval_part(acc, keys, scored, PLANNED, pooled):
    """one acceptance part on keys; returns (evals, short keys, nodata, gaps). A cell key is short below its planned n; a
    pooled key when any cell key in it is short (pooled: {key: [its cell keys]}). gaps: [(key, inner, {trial id: (columns,
    markers, stem)}, scored n, n with data, k)] per count() (data_gaps; EXPERIMENT 8, 2026-10-23)"""
    per_cell = acc.startswith("per cell:")
    a = acc[len("per cell:"):].strip() if per_cell else acc
    sub = None
    m = re.match(r"subset\((.*?)\):\s*(.*)$", a)
    if m:
        sub, a = m.group(1), m.group(2)
    use = keys if per_cell else keys[:1]
    short, evals, nodata, gaps = [], [], False, []
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
        # a library column empty in every scored trial is 자료 부족 (the line is not emitted); a fence or restore term's
        # column is looked for only in the trials where its action happened (term_applies; 2026-10-27, user decision 2):
        # a key whose trials all ended in fallback is then judged (its count fails), not 자료 부족
        if rows and any((lambda rs: rs and all(val_empty(r.get(c)) for r in rs))(
                [r for r in rows if term_applies(c + " ==", r)]) for c in refs):
            short.append(k)
        # N_SCORED's k: the planned n less preparation failures (EFF; a pooled key its cells' sum), a subset its scored rows
        kn = len(rows) if sub is not None else (sum(PLANNED.get(x, 0) for x in pooled[k]) if k in pooled
                                                else PLANNED.get(k, 0))
        ak, info = with_data_n(a, rows, kn)
        ak = re.sub(r"\bN_SCORED\b", str(len(rows)), ak)
        evals.append((k,) + s2.evaluate(ak, {k: rows}, k, s2.NIL))
        gaps += [(k, inner, g, len(rows), nd, kk) for inner, g, nd, kk in info]
    return evals, short, nodata, gaps


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
    words = rule.split()
    kind, _, arg = (words[0] if words else rule).partition(":")
    opts = dict(w.split("=", 1) for w in words[1:] if "=" in w)
    jnodes = set(x for x in opts.get("judged_nodes", "").split(",") if x) or set(c["cost"]["nodes"])
    base = fam["base"]
    judged = set(fam.get("judged", [])) & (set(named) if named else set(fam["arms"]))
    lines, short, bad = [], False, False
    for node in c["cost"]["nodes"]:
        for m in metrics:
            vals = {a: sorted(float(r["value"]) for r in rows if r["runner"] == "cost" and r["status"] == "scored"
                              and r.get("metric") == m and r.get("arm") == a and r.get("rx") == node)
                    for a in [base] + [x for x in fam["arms"] if x != base and (not named or x in named)]}
            if node in jnodes and any(len(v) < 5 for v in vals.values()):
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
                if a in judged and kind == "within" and node in jnodes:
                    ok = pct <= float(arg)
                    bad = bad or not ok
                    tag = ("범위 안 " if ok else "범위 밖 ") + "%s (≤ %s%%)" % (tag, arg)
                elif a in judged and kind == "within":
                    tag += "(보고만: 이 수신 노드는 판정 밖)"
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
            # gate_proc_gc.py without --gate-bin times no gate: the harness's own readings, reported only (2026-10-24)
            r["status"] = ("no_gate" if r.get("gate_src") == "proc" and val_empty(r.get("fenced_go_ms"))
                           else "candidate")
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
    by_key, scored, prep = {}, {}, {}
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
        else:  # item 4: a preparation failure takes its trial's place among the planned and is never refilled
            pool = [r for r in rs if r["status"] in ("candidate", "prep_failure")]
            for i, r in enumerate(pool):
                if i >= PLANNED.get(k, 0):
                    r["status"] = "surplus"
                elif r["status"] == "candidate":
                    r["status"] = "scored"
        scored[k] = [r for r in rs if r["status"] == "scored"]
        prep[k] = sum(1 for r in rs if r["status"] == "prep_failure")
    pooled = {}
    for b in c["builds"]:
        ks = sorted(k for k, rs in by_key.items() if "@" in k and not k.startswith("cost_")
                    and any(r.get("build") == b and r.get("runner") == "gcr" and r["status"] in ("scored", "surplus")
                            for r in rs))
        pooled["build:" + b] = ks
        scored["build:" + b] = [r for k in ks for r in scored.get(k, [])]
        prep["build:" + b] = sum(prep.get(k, 0) for k in ks)
    # the plan less the preparation failures in it: a key is short only when scored + prep failures < planned
    EFF = {k: max(0, v - prep.get(k, 0)) for k, v in PLANNED.items()}
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
        det = {"evals": [], "short": [], "mirror": [], "cost": [], "nodata": False, "missing": [], "gaps": []}
        if acc.startswith("cost:"):
            v, det["cost"] = cost_eval(keys[0], acc.split("rule=", 1)[1].strip(), rows, c)
            results.append((p, keys, v, det))
            continue
        ok_all = True
        for part in [x.strip() for x in acc.split(";;")]:
            if part.startswith("mirror:"):
                res, missing = mirror_part(part[len("mirror:"):].strip(), scored, EFF, mpreds)
                det["mirror"] += res
                det["missing"] += missing
                if any(v == "자료 부족" for _, v, _, _, _ in res) or missing or not res:
                    det["short"].append(part)
                ok_all = ok_all and all(v == "맞음" for _, v, _, _, _ in res)
                continue
            m = re.match(r"([A-Za-z0-9_]+@[a-z]+|build:[a-z]+|local:[a-z_]+):\s*(.*)$", part)
            pk, pa = ([m.group(1)], m.group(2)) if m else (keys, part)
            ev, sh, nd, gp = eval_part(pa, pk, scored, EFF, pooled)
            det["evals"] += ev
            det["short"] += sh
            det["nodata"] = det["nodata"] or nd
            det["gaps"] += gp
            ok_all = ok_all and all(e[1] for e in ev)
        # EXPERIMENT 8 (2026-10-23, DRAFT): the 자료 부족 trials are neither passes nor fails; a count() whose trials with
        # data are fewer than its pre-registered k cannot be judged (never 맞음 by a smaller denominator)
        det["below_k"] = [(k, inner, nd, kk) for k, inner, g, n, nd, kk in det["gaps"] if kk is not None and nd < kk]
        if det["nodata"]:
            v = "자료 없음(실패 아님)"
        elif det["short"]:
            v = "자료 부족"
        elif det["below_k"]:
            v = "자료 부족(n<k)"
        else:
            v = "맞음" if ok_all else "틀림"
        # item 5: a safety prediction holds only with no failure over its scored trials (every count() part n of n)
        det["safety_fail"] = safety_fails(det)
        # a measured failure on a trial with data is a fail even when gaps leave the key 자료 부족(n<k) (2026-10-27) or the key
        # is short, fewer scored trials than planned (자료 부족, e.g. after a STOP; 2026-11-18 review); never 자료 없음
        if kind_of(p) == "safety" and v in ("맞음", "자료 부족", "자료 부족(n<k)") and det["safety_fail"]:
            v = "틀림"
        det["perf_safety"] = perf_safety_terms(p, det, scored, mpreds) if kind_of(p) == "perf" else []
        det["fallback"] = perf_fallbacks(p, scored, mpreds) if kind_of(p) == "perf" else []
        # EXPERIMENT 8 (2026-10-23): a perf rule whose safety term fails on any scored trial is re-examined, whatever its
        # count threshold says (a short or no-data verdict stays; its failing trials are listed all the same)
        k_bad, n_read, det["perf_bad"] = perf_review(det["perf_safety"])
        if k_bad and v in ("맞음", "틀림"):
            v = "재검토(안전성 항 어긋남 %d/%d)" % (k_bad, n_read)
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
    la_cap = sum(ival(r.get("la_spare_cap_expected_n"), 0) for r in rows)
    not_live = sorted("%s(%s)" % (r["id"], r["status"]) for r in rows if r.get("runner") == "gcr" and str(r.get("ring_live_all")) == "0")
    prep_ids = sorted(r["id"] for r in rows if r.get("status") == "prep_failure")

    def rate(a, b):
        return "%d/%d = %.1f %%" % (a, b, 100.0 * a / b) if b else "%d/0" % a

    def count_rows(det):
        """item 4: per key and count() of a prediction: planned, run, excluded by reason, prep failures, scored, the
        conditional (over the scored with data) and the whole-run (over scored + prep failures) success rates, and the
        scored trials that are 자료 부족 for the count() (data_gaps; EXPERIMENT 8, 2026-10-23)"""
        out = []
        gn = {(k, inner): len(g) for k, inner, g, *_ in det.get("gaps", [])}
        for k, dd in all_evals(det):
            pl, run, exc, pf, sc = key_counts(k, by_key, scored, prep, PLANNED, pooled)
            ex = ", ".join("%s %d" % kv for kv in sorted(exc.items())) or "0"
            for inner, cnt, n, *_ in dd:
                g = gn.get((k, inner), 0)
                out.append((k, pl, run, ex, pf, sc, g, inner, rate(cnt, n - g), rate(cnt, n + pf)))
        return out
    la_down = [(r["id"], "낡은 소켓이나 프로세스 %s" % r["launcher_stale"] if r.get("launcher_stale") else "뜨지 않음")
               for r in rows if r.get("ctrl") == "rdma" and r.get("runner") == "gcr" and
               (r.get("launcher_stale") or str(r.get("launcher_ready")) == "0")]
    L = ["# gin-control 채점 결과 (시험 쪽)", "",
         "`score_gc.py`가 원자료에서 만들었다. 손으로 고친 값은 없다. 판정식 원문은 `predictions_gc.csv`, 문법은 gin-mirror의 `score.py`(s2_close 3.2)와 이 파일 머리의 꼴이다.", "",
         "- 예측 파일 sha256: `%s`. `PREREG.txt`의 값과 %s." % (sha, "같다" if sha in frozen else "다르다(사전 등록한 파일이 아니거나 아직 사전 등록 전)"),
         "- 시행 수: %d. 판정한 시행: %d. smoke: %d, pilot: %d(따로 셈, 채점 안 함)." % (
             len(rows), sum(len(v) for k, v in scored.items() if not k.startswith("build:")),
             sum(1 for r in rows if r["status"] == "smoke"), sum(1 for r in rows if r["status"] == "pilot")),
         "- STOP 파일: %s." % (", ".join("`%s`(%d줄)" % (x, sum(1 for _ in open(os.path.join(R, x)))) for x in stops) or "없음"),
         "- `(STOP_launcher)`와 `(STOP_launcher: …)` 줄(launcher 로그와 rank, 예비 프로세스 로그; rank 쪽의 launcher Unix 소켓 끊김 줄 %d개 포함; 8절 채점 규칙, FENCE_NAK 포함): %d줄, 시행 %s." % (
             sum(ival(r.get("rank_la_sock_lost_n"), 0) for r in rows), sum(n for _, n in la_stop),
             ", ".join("%s(%d)" % x for x in la_stop) or "없음"),
         "- 링이 live가 되지 않은 시행(REVIEW_INT3 F7; 설정 탓이면 config 제외, 아니면 준비 실패로 셈): %d개%s." % (
             len(not_live), (": " + ", ".join(not_live)) if not_live else ""),
         "- 준비 실패(설정이 맞는데 Resume 거절이나 링 live 실패; 계획 n 안의 자리를 차지하고 채우지 않음; Codex 리뷰 4): %d개%s." % (
             len(prep_ids), (": " + ", ".join(prep_ids)) if prep_ids else ""),
         "- 예비 프로세스 없음 셀의 예상된 다시 띄우기 한도 줄(실행기가 끝낸 예비 프로세스를 launcher가 다시 띄우지 않음; STOP으로 세지 않음): %d줄." % la_cap,
         "- launcher가 뜨지 않았거나 낡은 launcher 소켓이나 프로세스가 남아 돌지 않은 시행(8절, STOP_launcher): %s." % (
             ", ".join("%s(%s)" % x for x in la_down) or "없음"), "",
         "## 판정 요약", "", "안전 예측(kind safety)은 판정한 시행에서 실패 0일 때만 맞음, 성능 예측(perf)은 판정식의 문턱 그대로다(Codex 리뷰 5). "
         "다만 성능 예측의 판정식 안의 안전성 항(%s)이 판정한 시행 하나에서라도 거짓이면 그 예측은 문턱과 상관없이 "
         "재검토(안전성 항 어긋남 k/n)다(8절, 2026-10-23). 안전성 항은 그 항이 지키는 동작(펜스, 복원)이 있었던 시행에서만 보고, "
         "복원 시도 없이 fallback으로 끝난 시행은 성능 실패로만 센다(fallback(복원 없음), 8절, 2026-10-27). 판정식이 읽는 필수 요약 열(제어 요약, READ 요약)이 빈 시행은 그 예측에서 "
         "자료 부족 시행이다(통과도 실패도 아님). 판정은 나머지 시행으로 사전 등록 문턱 k에 견주고(`>= N_SCORED`의 k는 계획 n), 자료 있는 시행이 k보다 적으면 "
         "자료 부족(n<k)이다(8절, 2026-10-23, 2026-10-27)." % ", ".join("`%s`" % t for t in SAFETY_TERMS), "",
         "| 예측 | 종류 | 셀 | n | 판정 |", "|---|---|---|--:|---|"]
    for p, keys, v, det in results:
        gk = {}
        for k, _, g, *_ in det.get("gaps", []):
            gk.setdefault(k, set()).update(g)
        ns = " / ".join(str(len(scored.get(k, []))) + (" (자료 부족 %d)" % len(gk[k]) if gk.get(k) else "")
                        for k in keys if not k.startswith(("mirror:", "cost:")))
        L.append("| %s (%s) | %s | %s | %s | %s |" % (p["predicted"], p["id"], kind_of(p), ", ".join("`%s`" % k for k in keys),
                                                  ns or "-", v))
    L += ["", "## 예측별 세부", ""]
    for p, keys, v, det in results:
        L += ["### %s: %s" % (p["id"], v), "", "- 판정식: `%s`" % p["acceptance"]]
        if p.get("todo"):
            L.append("- 표시: %s" % p["todo"])
        if det["short"]:
            L.append("- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): %s" % ", ".join(det["short"]))
        gmap = {(k, inner): (g, nd, kk) for k, inner, g, n, nd, kk in det.get("gaps", [])}
        for k, ok, dd, expr in det["evals"]:
            L.append("- `%s`: 판정한 시행 %d회, 대입한 식 `%s` → %s" % (k, len(scored.get(k, [])), expr, "참" if ok else "거짓"))
            for inner, cnt, n, fs, ts, tail in dd:
                g, nd, kk = gmap.get((k, inner), ({}, n, None))
                gst = {x[2] for x in g.values()}
                fs = [x for x in fs if x not in gst]
                L.append("  - `count(%s)` = %d/%d. 만족하지 않은 시행: %s" % (
                    inner, cnt, nd, ", ".join(os.path.basename(str(x)) for x in fs) if fs else "없음"))
                L.append("  - 채점 n %d, 자료 부족 n %d, 자료 있는 n %d, 문턱 k %s%s" % (
                    n, len(g), nd, "-" if kk is None else kk, " → 자료 부족(n<k)" if kk is not None and nd < kk else ""))
                if g:
                    L.append("  - 자료 부족 시행(빈 필수 열; 통과도 실패도 아님, 8절): %s" % "; ".join(
                        "`%s` (%s%s)" % (i, ", ".join(cs), "; " + mk if mk else "") for i, (cs, mk, _) in sorted(g.items())))
        for mid, mv, mkeys, mev, msh in det["mirror"]:
            L.append("- gin-mirror `%s` (%s): %s" % (mid, ", ".join(mkeys), mv))
        if det["missing"]:
            L.append("- gin-mirror 예측 표에 없는 ID: %s" % ", ".join(det["missing"]))
        if det.get("safety_fail") and kind_of(p) == "safety":
            L.append("- 안전 예측의 실패(실패 0 규칙): %s" % "; ".join("`%s` `count(%s)` %d/%d" % x for x in det["safety_fail"]))
        for k, t, fs, n, gs, na in det.get("perf_safety", []):
            L.append("- 성능 예측 안의 안전성 항(어긋나면 재검토, 8절) `%s` `%s`: 실패 %d/%d%s%s%s" % (
                k, t, len(fs), n, (" (" + ", ".join(fs) + ")") if fs else "",
                ", 자료 부족 %d (%s)" % (len(gs), ", ".join(gs)) if gs else "",
                ", 해당 없음 %d (%s)" % (len(na), ", ".join(na)) if na else ""))
        if det.get("fallback"):
            L.append("- fallback(복원 없음) 시행(복원 시도 없이 생존 rank가 풀림; 성능 실패로만 세고 안전성 어긋남으로 세지 않음, 8절): %s" % (
                ", ".join("`%s`" % i for i in det["fallback"])))
        if det.get("perf_bad"):
            L.append("- 안전성 항 어긋남(재검토): %s" % "; ".join(
                "`%s` (%s)" % (i, ", ".join("`%s`" % t for t in ts)) for i, ts in sorted(det["perf_bad"].items())))
        cr = count_rows(det)
        if cr:
            L += ["", "| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |",
                  "|---|--:|--:|---|--:|--:|--:|---|--:|--:|"]
            L += ["| `%s` | %d | %d | %s | %d | %d | %d | `%s` | %s | %s |" % x for x in cr]
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
    for p, _, v, det in results:
        print("%s: %s" % (p["id"], v))
        for k, pl, run, ex, pf, sc, g, inner, cr_, wr in count_rows(det):
            print("  [%s] %s planned=%d run=%d excluded=%s prep_failure=%d scored=%d cond=%s whole=%s data_gap=%d" % (
                kind_of(p), k, pl, run, ex.replace(" ", ":").replace(",:", ","), pf, sc, cr_.split(" =")[0], wr.split(" =")[0], g))
    return {p["id"]: v for p, _, v, _ in results}, rows


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    score(os.path.abspath(sys.argv[1]))
