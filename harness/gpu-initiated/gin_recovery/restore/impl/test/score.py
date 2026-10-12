#!/usr/bin/env python3
"""gin-restore work package 10 scorer (DRAFT until the pre-registration): applies predictions_rs.csv to a results folder
and writes <resultsdir>/SCORE.md and trials_scored.csv.

usage: score.py <resultsdir>
       score.py --selftest        the CPU-only synthetic self-test (no results folder, no cluster)

Steps (EXPERIMENT.md 3 and 8), as ../../../../gpu-detect/score.py (master) does:
  1. rows_rs.all_rows(): one row per trial (raw/: the restore cells; reg/: gin-remaining's 4-rank runner; cost*/).
     Regression rows get gin-remaining's own columns (its score.py imported as a library, unchanged: rows_of, extra_pq4,
     extra_hr4) and its status4 for the cell they repeat (cells_rs.json regression_orig), with the build checked as hr
     and the driver as hr: our gin_mr is gin-remaining's gin_mr.cu unchanged, built against this layer's headers.
  2. a status per trial: scored, or an exclusion of section 8 (void, not_applied, spare_start_fail, spare_not_killed,
     config, foreign_gpu, kill_before_ckpt), or
     restore_not_live (the cells that need the restore reaction, while the library layer is not integrated), or surplus.
     Excluded trials are not refilled by the scorer (the hold refills them, section 8).
  3. per key cell@build the first PLANNED candidates by trial number are scored. A prediction is "자료 부족" when a cell
     it names has fewer scored trials than ceil(0.75 x planned), or when a library-only column its formula reads is
     empty in every scored trial (the restore layer does not emit it yet).
  4. the acceptance formulas are evaluated with the grammar of ../../../s2_close/EXPERIMENT.md 3.2 (its score.py
     functions, unchanged). The cost rows ("cost: rule=...") use 9.15.6's method per receiving node: an arm is
     "separated" from the family's base arm when every valid run of one is worse than every valid run of the other (equal
     values do not separate); fewer than 5 valid runs in an arm on a node: "자료 부족" (9.15.6's 미완). rule=report: the
     threshold is fixed after the pilot (PILOT.md), so the verdict is "문턱 대기"; rule=not_separated: 맞음 iff no metric on
     no node separates.
"""
import csv, hashlib, importlib.util, json, math, os, re, statistics, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GR = os.path.join(HERE, "..", "..", "..")  # gin_recovery/
_spec = importlib.util.spec_from_file_location("s2_score", os.path.join(GR, "s2_close", "score.py"))
s2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s2)  # the section 3.2 grammar: evaluate, keys_of, NIL
_spec = importlib.util.spec_from_file_location("grm_score", os.path.join(GR, "remaining", "score.py"))
rem = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rem)  # gin-remaining's scorer as a library: rows_of, extra_pq4, extra_hr4, status4
sys.path.insert(0, HERE)
import rows_rs  # noqa: E402

CELLS = os.path.join(HERE, "cells_rs.json")
PREDS = os.path.join(HERE, "predictions_rs.csv")
# @rs: the restore reaction must be live (rs4_kill3_nospare is not here: no spare registered, never armed, hk's reaction)
NEEDS_LIVE = {"rs4_kill3", "rs4_kill3_ckpt", "rs4_kill1", "rs4_kill3_spareabsent"}
LIB_COLS = set(rows_rs.LIBCOLS)
EXCL = {"void": "시작 실패(생존 rank가 교환 전에 끝남)", "not_applied": "장애 미적용(kill 기록 없음)",
        "config": "설정 확인 실패(셀이 요구한 정책/복원 설정 아님)",
        "restore_not_live": "복원 계층 미통합(Step hook이 실행되지 않음; 통합 뒤에만 채점)",
        "kill_before_ckpt": "kill이 첫 확정 체크포인트 전", "spare_start_fail": "예비 프로세스가 활성화 전에 시작에 실패함",
        "foreign_gpu": "시행 시작 때 GPU에 다른 프로세스",
        "spare_not_killed": "예비 프로세스가 rank보다 먼저 꺼지지 않음(예비 프로세스 없음 셀)", "cost_invalid": "비용 실행 무효(오류, 값 없음, win_flags나 tx_done이 다름)",
        "surplus": "계획 수를 넘은 시행"}
EXCL.update(getattr(rem, "EXCL_LABEL", {}))


def load_cells():
    return json.load(open(CELLS))


def planned(c):
    p = {}
    for h, cl in c["holds"].items():
        if h.startswith("P"):
            continue  # pilot holds are never scored
        for e in cl:
            k = "%s@%s" % (e["cell"], e["build"])
            p[k] = max(p.get(k, 0), e["n"])
    cost = c["cost"]
    for fam in cost["families"].values():
        for m in fam["metrics"]:
            for a in fam["arms"]:
                lib = fam["lib"][a] if isinstance(fam["lib"], dict) else fam["lib"]
                p["cost_%s_%s@%s" % (m, a, lib)] = cost["n_per_arm"] * len(cost["nodes"])
    return p


def reg_columns(stem, r):
    """gin-remaining's columns of one 4-rank trial (its own row code, unchanged). The self-test replaces this."""
    out = {k: ("" if v is None else v) for k, v in rem.rows_of(stem).items()}
    out.update({k: ("" if v is None else v) for k, v in rem.extra_pq4(stem, out).items()})
    out.update({k: ("" if v is None else v) for k, v in rem.extra_hr4(stem, out).items()})
    return out


def status_rs(r):
    if int(r.get("void") or 0):
        return "void"
    if str(r.get("kill_rank", "")).isdigit() and int(r.get("applied") or 0) == 0:
        return "not_applied"
    if str(r.get("spare_start_fail")) == "1":
        return "spare_start_fail"  # section 8: the spare failed to start before its activation (counted apart)
    if str(r.get("spare_killed_first")) == "0":
        return "spare_not_killed"  # the spare-absent cell: the spare was not killed before its rank died
    if int(r.get("config_ok") or 0) == 0:
        return "config"
    if str(r.get("foreign_gpu")) == "1":
        return "foreign_gpu"  # section 8: another user's compute app on a GPU when the trial started
    if r["cell"] in NEEDS_LIVE and r.get("build") == "rs":
        if int(r.get("restore_live") or 0) == 0:
            return "restore_not_live"
        if str(r.get("ckpt_stable_before_kill")) == "0":
            return "kill_before_ckpt"  # section 8: no confirmed checkpoint before the kill
    return "candidate"


def status_reg(r, orig):
    if not orig:
        return "config"
    mk = str(r.get("mrkey") or "")
    ours = mk.endswith("rs-bundle/mr/ff") or mk.endswith("rs-bundle/mr/hold") or mk == "hr"
    return rem.status4(dict(r, build="hr", cell=orig, mrkey="hr" if ours else mk))


def val_empty(v):
    return v is None or v == ""


def evaluate_pred(p, scored, PLANNED):
    acc = p["acceptance"]
    keys = s2.keys_of(p["cells"])
    per_cell = acc.startswith("per cell:")
    a = acc[len("per cell:"):].strip() if per_cell else acc
    use = keys if per_cell else keys[:1]
    short = [k for k in keys if PLANNED.get(k, 0) == 0 or len(scored.get(k, [])) < math.ceil(0.75 * PLANNED.get(k, 0))]
    refs = sorted(c for c in LIB_COLS if re.search(r"\b" + c + r"\b", a))
    for k in use:  # a library-only column empty in every scored trial: the library does not emit it (yet)
        rows = scored.get(k, [])
        if rows and any(all(val_empty(r.get(c)) for r in rows) for c in refs):
            short.append(k)
    evals = []
    for k in use:
        ak = re.sub(r"\bN_SCORED\b", str(len(scored.get(k, []))), a)
        evals.append((k,) + s2.evaluate(ak, scored, k, s2.NIL))
    ok = all(e[1] for e in evals)
    return keys, evals, ("자료 부족" if short else ("맞음" if ok else "틀림")), sorted(set(short))


def cost_eval(p, rows, cells):
    """9.15.6's 6-vs-6 reading per receiving node; returns (verdict, table lines)."""
    fam_name = p["cells"].split(":", 1)[1].strip()
    rule = p["acceptance"].split("rule=", 1)[1].strip()
    fam = cells["cost"]["families"][fam_name]
    base = fam["base"]
    lines, short, sep = [], False, False
    for node in cells["cost"]["nodes"]:
        for m in fam["metrics"]:
            vals = {}
            for a in fam["arms"]:
                v = [float(r["value"]) for r in rows if r["runner"] == "cost" and r["status"] == "scored"
                     and r["metric"] == m and r["arm"] == a and r["rx"] == node]
                vals[a] = sorted(v)
            if any(len(v) < 5 for v in vals.values()):
                short = True
            bv = vals.get(base, [])
            for a in fam["arms"]:
                v = vals[a]
                if not v:
                    lines.append("| %s | %s | %s | 0 | - | - | - |" % (node, m, a))
                    continue
                med = statistics.median(v)
                if a == base or not bv:
                    lines.append("| %s | %s | %s | %d | %.3f | - | 기준 |" % (node, m, a, len(v), med))
                    continue
                bmed = statistics.median(bv)
                worse_hi = m != "bw256k"  # latency: higher is worse; bandwidth: lower is worse
                if worse_hi:
                    s_worse, s_better = min(v) > max(bv), max(v) < min(bv)
                    d = med - bmed
                else:
                    s_worse, s_better = max(v) < min(bv), min(v) > max(bv)
                    d = bmed - med
                tag = "갈림(나쁨)" if s_worse else "갈림(좋음)" if s_better else "차이를 잴 수 없음"
                if s_worse or s_better:
                    sep = True
                lines.append("| %s | %s | %s | %d | %.3f | %+.3f (%+.1f%%) | %s |" % (
                    node, m, a, len(v), med, d, 100.0 * d / bmed if bmed else 0.0, tag))
    if short:
        verdict = "자료 부족"
    elif rule == "report":
        verdict = "문턱 대기(pilot 뒤)"
    else:
        verdict = "틀림" if sep else "맞음"
    return verdict, lines


def score(R):
    cells = load_cells()
    PLANNED = planned(cells)
    orig = cells.get("regression_orig", {})
    rows = rows_rs.all_rows(R)
    for r in rows:
        if r["runner"] == "mrr":
            r.update(reg_columns(r["stem"], r))
            r["status"] = status_reg(r, orig.get(r["cell"]))
        elif r["runner"] == "cost":
            r["status"] = "candidate" if str(r.get("cost_valid")) == "1" else "cost_invalid"
        else:
            r["status"] = status_rs(r)
    cols = []
    for r in rows:
        for c in r:
            if c not in cols:
                cols.append(c)
    for r in rows:  # every row has every column (an absent one is empty: the 3.2 rule)
        for c in cols:
            r.setdefault(c, "")
    by_key, scored = {}, {}
    for r in sorted(rows, key=lambda x: (x["key"], x.get("tnum") or 0, x["sub"])):
        by_key.setdefault(r["key"], []).append(r)
    for k, rs in by_key.items():
        cand = [r for r in rs if r["status"] == "candidate"]
        if k.startswith("cost_"):  # per receiving node: the first n_per_arm of each node
            per = {}
            for r in cand:
                per.setdefault(r["rx"], []).append(r)
            for node_rows in per.values():
                for i, r in enumerate(node_rows):
                    r["status"] = "scored" if i < cells["cost"]["n_per_arm"] else "surplus"
        else:
            for i, r in enumerate(cand):
                r["status"] = "scored" if i < PLANNED.get(k, 0) else "surplus"
        scored[k] = [r for r in rs if r["status"] == "scored"]
    preds = list(csv.DictReader(open(PREDS)))
    sha = hashlib.sha256(open(PREDS, "rb").read()).hexdigest()
    frozen = open(os.path.join(HERE, "PREREG.txt")).read() if os.path.exists(os.path.join(HERE, "PREREG.txt")) else ""
    results, cost_tables = [], {}
    for p in preds:
        if p["acceptance"].startswith("cost:"):
            v, tbl = cost_eval(p, rows, cells)
            cost_tables[p["id"]] = tbl
            results.append((p, [p["cells"]], [], v, []))
        else:
            results.append((p,) + evaluate_pred(p, scored, PLANNED))
    lead = ["key", "status", "sub", "id", "cell", "build", "runner"]
    with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=lead + [c for c in cols if c not in lead], extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["sub"], x["key"], x.get("tnum") or 0)):
            w.writerow(r)
    L = ["# gin-restore 시험 채점 결과 (work package 10, DRAFT)", "",
         "`score.py`가 원자료에서 만들었다. 손으로 고친 값은 없다. 문턱과 반복 수는 pilot 뒤에 고정한다(PILOT.md).", "",
         "- 예측 파일 sha256: `%s`. `PREREG.txt`의 값과 %s." % (sha, "같다" if sha in frozen else "다르다(사전 등록 전)"),
         "- 시행 수: %d. 판정한 시행: %d." % (len(rows), sum(len(v) for v in scored.values())),
         "- 판정식 원문은 `predictions_rs.csv`, 문법은 `../../../s2_close/EXPERIMENT.md` 3.2.", "",
         "## 판정 요약", "", "| 예측 | 셀 | n | 판정 |", "|---|---|--:|---|"]
    for p, keys, evals, verdict, short in results:
        ns = " / ".join(str(len(scored.get(k, []))) for k in keys) if not p["acceptance"].startswith("cost:") else "-"
        L.append("| %s (%s) | %s | %s | %s |" % (p["predicted"], p["id"], ", ".join("`%s`" % k for k in keys), ns, verdict))
    L += ["", "## 예측별 세부", ""]
    for p, keys, evals, verdict, short in results:
        L += ["### %s: %s" % (p["id"], verdict), "", "- 판정식: `%s`" % p["acceptance"]]
        if short:
            L.append("- 자료 부족 셀(계획의 75%% 미만, 또는 라이브러리 열이 비어 있음): %s" % ", ".join(short))
        for k, ok, det, expr in evals:
            L.append("- 셀 `%s`: 판정한 시행 %d회, 대입한 식 `%s` → %s" % (k, len(scored.get(k, [])), expr, "참" if ok else "거짓"))
            for inner, c, n, fs, ts, tail in det:
                L.append("  - `count(%s)` = %d/%d. 만족하지 않은 시행: %s" % (inner, c, n, ", ".join(fs) if fs else "없음"))
        if p["id"] in cost_tables:
            L += ["", "| 받는 노드 | 크기 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |", "|---|---|---|--:|--:|---|---|"]
            L += cost_tables[p["id"]] or ["| (비용 실행 없음) |  |  |  |  |  |  |"]
        L.append("")
    L += ["## 셀별 시행 수와 따로 센 시행", "", "| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |", "|---|--:|--:|--:|---|"]
    for k in sorted(set(list(by_key) + list(PLANNED))):
        rs = by_key.get(k, [])
        apart = {}
        for r in rs:
            if r["status"] != "scored":
                apart.setdefault(r["status"], []).append(r["id"])
        txt = "; ".join("%s: %s" % (EXCL.get(s, s), ", ".join(v)) for s, v in sorted(apart.items())) or "없음"
        L.append("| `%s` | %d | %d | %d | %s |" % (k, PLANNED.get(k, 0), len(rs), len(scored.get(k, [])), txt))
    L.append("")
    open(os.path.join(R, "SCORE.md"), "w").write("\n".join(L))
    print("\n".join("%s: %s" % (p["id"], v) for p, _, _, v, _ in results))
    return {p["id"]: v for p, _, _, v, _ in results}


# ------------------------------------------------------------------ synthetic self-test (CPU only, no cluster)
def _w(path, text):
    with open(path, "w") as f:
        f.write(text)


def _kvline(**kw):
    return " ".join("%s=%s" % (k, v) for k, v in kw.items()) + "\n"


GOOD = dict(init_rc=0, reg_rc=0, devcomm_rc=0, resume_rc=0, resume_why="none", steps=400, steps_done=400, released=0,
            recv_bad=0, xhist_bad=0, dev_bad=0, x_match=1, sig_exact=1, reexec_any=0, async_n=0, exit=0)


def _rs(d, cell, build, k, *, kill=None, spare=False, spare_addr=False, policy="hold", restore="1", live=True,
        surv=None, sp=None, refuse=None, ff_rank=None, win=None, lib_lines=None, t0=100.0, spare_fail=False, gpu="0/0",
        negs=(), neg_ok=True, strace=None, spare_kill=None):
    """one synthetic restore trial in the run_rs.sh format (stamped logs, kv, meta)"""
    os.makedirs(d, exist_ok=True)
    stem = os.path.join(d, "%s_%s_n%d" % (cell, build, k))
    rcs = {r: 0 for r in range(4)}
    if kill is not None:
        rcs[kill] = 137
    meta = dict(cell=cell, lib=build, n=4, policy=policy, restore=restore, kill_rank=("" if kill is None else kill),
                spare=int(spare), spare_wanted=int(spare), spare_ready=int(spare and not spare_fail), gpu_apps_before=gpu,
                spare_addr_set=int(spare or spare_addr), restore_ms=20000, runner="rsr", wall_s=5.0, negs=",".join(negs),
                spare_kill_first=int(spare_kill is not None))
    meta.update({"r%drc" % r: rcs[r] for r in range(4)})
    _w(stem + "_meta.txt", _kvline(**meta))
    for r in range(4):
        kv = dict(GOOD, rank=r, rs_hooks_live=int(live))
        if refuse is not None:
            kv.update(resume_rc=(0 if r == ff_rank else 3), resume_why=refuse[r] if isinstance(refuse, list) else refuse)
        if kill is not None and r == kill:
            kv = dict(rank=r, init_rc=0, reg_rc=0, devcomm_rc=0, resume_rc=0, steps=400, rs_hooks_live=int(live))
        elif surv:
            kv.update(surv)
        _w(stem + "_r%d.kv" % r, _kvline(**kv))
        lines = ["%.6f GINRS start rank=%d mode=live" % (t0, r)]
        for strict, forced, ro in (win or []):
            lines.append("%.6f host:1:1 [0] NCCL WARN GIN/RS: window MR rank=%d bytes=6291456 strict=%d forced=%d "
                         "flag_strict=0 ro=%d restore_requested=%d" % (t0 + 1, r, strict, forced, ro, forced))
        for t, txt in (lib_lines or {}).get(r, []):
            lines.append("%.6f %s" % (t0 + t, txt))
        if kill is not None and r == kill:
            lines.append("%.6f GINRS step rank=%d step=100 released=0" % (t0 + 2.0, r))
        _w(stem + "_r%d.log" % r, "\n".join(lines) + "\n")
    if kill is not None:
        _w(stem + "_kill.out", "%.6f GINRS killed rank=%d node=sunny pid=999\n" % (t0 + 2.001, kill))
    if spare_kill is not None:  # the spare's recorded-PID kill, spare_kill seconds after t0
        _w(stem + "_spare_kill.out", "%.6f GINRS killed rank=%d node=sunny pid=998\n" % (t0 + spare_kill, kill))
    if spare:
        skv = dict(GOOD, rank=kill, mode="spare", resume_step=100, revived=1, start_step=101, rs_hooks_live=1)
        if sp:
            skv.update(sp)
        _w(stem + "_spare.kv", _kvline(**skv))
        _w(stem + "_spare.log", "%.6f GINRS start rank=%d mode=spare\n%.6f GINRS spare_ready rank=%d rt_s=1.0\n"
           "%.6f GINRS resume rank=%d rc=0 step=100\n" % (t0, kill, t0 + 1.25, kill, t0 + 4.0, kill))
        if strace is not None:
            _w(stem + "_spare_strace.txt", _kvline(**strace))
    for neg in negs:
        if neg_ok:
            _w(stem + "_%s.kv" % neg, _kvline(init_rc=2, exit=2))
            _w(stem + "_%s.log" % neg, "%.6f host WARN GIN/RS: replay ON rank=3 nranks=4 entries=9\n"
               "%.6f host WARN GIN/RS: replay: transcript entry 3 is damaged or cut\n" % (t0, t0 + 0.1))
        else:
            _w(stem + "_%s.kv" % neg, _kvline(init_rc=0, exit=7))
            _w(stem + "_%s.log" % neg, "%.6f GINRS spare_ready rank=3 rt_s=1.0\n" % t0)
        _w(stem + "_%s_strace.txt" % neg, _kvline(peer_connect_before_ready=0, peer_connect_after_ready=0, rt_known=0))


def _reg(d, cell, k, cols):
    os.makedirs(d, exist_ok=True)
    stem = os.path.join(d, "%s_n%d" % (cell, k))
    _w(stem + "_meta.txt", _kvline(cell=cell, lib="../../rs-bundle/lib/rs", mrkey="../../../rs-bundle/mr/ff", n=4,
                                   runner="mrr", selftest=json.dumps(cols).replace(" ", "")))


def _cost(d, metric, arm, node, k, value):
    os.makedirs(d, exist_ok=True)
    cell = "cost_%s_%s_%s" % (metric, arm, node)
    stem = os.path.join(d, "%s_k%d" % (cell, k))
    lib = "hkp" if arm == "ffb-hk" else "rsp"
    iters = 12 if metric == "bw256k" else 3000
    _w(stem + "_meta.txt", _kvline(cell=cell, metric=metric, arm=arm, rx=node, lib=lib, runner="cost", iters=iters))
    if metric == "bw256k":
        _w(stem + "_r0.kv", _kvline(lat_p50_us=value, burst_K=8, bytes=262144, win_flags="0x3", tx_done=iters, exit=0))
    else:
        _w(stem + "_r0.kv", _kvline(lat_p50_us=value, win_flags="0x3", tx_done=iters, exit=0))
    _w(stem + "_r1.kv", _kvline(win_flags="0x3", exit=0))


def _selftest_reg_columns(stem, r):
    meta = rows_rs.read_meta(stem)
    return json.loads(meta.get("selftest", "{}"))


REG_OK_NONE = dict(transparent_ok=1, n_ts_on=4, n_ua=4, n_pq_on=4, n_hr_on=4, n_lb_on=4, n_lb_off=0, knob_stall="",
                   mrkey="hr")
REG_OK_KILL = dict(n_rel_dead=3, rel_after_dead_ms_r0=2400, rel_after_dead_ms_r1=2450, rel_after_dead_ms_r2=2500,
                   n_surv_edges=6, surv_tx_ok=6, n_kdone_surv=3, n_stuck_surv=0, killed=1, kill_in_traffic=1,
                   rx_untimed=1, n_ts_on=4, n_ua=4, n_pq_on=4, n_hr_on=4, n_lb_on=4, n_lb_off=0, knob_stall="", mrkey="hr")


def _all_cost(d, ffb_sep=False):
    for node in ("rain", "sunny"):
        for k in range(1, 7):
            for m in ("lat4k", "lat256k", "bw256k"):
                base = {"lat4k": 10.5, "lat256k": 38.9, "bw256k": 6.4}[m]
                for i, a in enumerate(("off", "on", "sampled", "full")):
                    _cost(d, m, a, node, k, round(base + 0.01 * i + 0.001 * k, 4))
            for m in ("lat4k", "lat256k"):
                base = {"lat4k": 10.5, "lat256k": 38.9}[m]
                for a in ("ua-ff", "ua-hold"):
                    _cost(d, m, a, node, k, round(base + 0.001 * k, 4))
                _cost(d, m, "ffb-hk", node, k, round(base + 0.001 * k, 4))
                _cost(d, m, "ffb-rs", node, k, round(base + (1.0 if ffb_sep else 0.001) * k, 4))


def _build_A(d, *, live=True, bad_data=False, refuse_ff=False, reg_bad=False, ffb_sep=False, slow_fb=False):
    raw, reg, cost = os.path.join(d, "raw"), os.path.join(d, "reg"), os.path.join(d, "cost_selftest")
    W = [(1, 1, 0), (1, 1, 0), (1, 1, 0)]
    dead = lambda: {r: [(3.0, "host:1:1 [0] NCCL WARN GIN/TS: rank %d: peer 3 judged dead (FIN without a goodbye)" % r),
                        (7.5, "host:1:1 [0] NCCL WARN GIN/RS: rank %d: hold peer=3 published epoch=4" % r),
                        (0.5, "host:1:1 [0] NCCL WARN GIN/RS: rank 3: checkpoint 100 stable"),
                        (0.6, "host:1:1 [0] NCCL WARN GIN/RS: rank %d: suppress peer=3 ctx=%d budget=2 suppressed=2" % (r, r))]
                    for r in (0, 1, 2)}
    for k in range(1, 11):
        _rs(raw, "rs4_kill3", "rs", k, kill=3, spare=True, live=live,
            surv=(dict(recv_bad=1) if bad_data and k <= 2 else None), lib_lines=dead())
    for k in range(1, 6):
        _rs(raw, "rs4_kill3_ckpt", "rs", k, kill=3, spare=True, live=live, lib_lines=dead())
        _rs(raw, "rs4_kill1", "rs", k, kill=1, spare=True, live=live,
            lib_lines={r: [(0.5, "GIN/RS: rank 1: checkpoint 100 stable")] for r in (0, 2, 3)})
        # no spare registered: never armed, no hold start, the decline and the degraded release 2.3 s after the death
        nsp = {r: [(3.0, "GIN/TS: rank %d: peer 3 judged dead" % r), (3.0, "GIN/TS: declined rank=3 why=peer-dead" % ()),
                   (5.3, "GINRS step rank=%d step=120 released=1 got=1 want=2" % r)] for r in (0, 1, 2)}
        _rs(raw, "rs4_kill3_nospare", "rs", k, kill=3, live=live, surv=dict(released=1, steps_done=120), lib_lines=nsp)
        # a spare registered but absent: hold start, the fallback 1.0 s later, the release 2.3 s after the fallback
        fb = {r: [(3.0, "GIN/TS: rank %d: peer 3 judged dead" % r),
                  (3.01, "GIN/RS: rank %d: hold of rank 3 started: gates odd since 0.4 ms before the start" % r),
                  (4.01, "GIN/RS: rank %d: the restore of rank 3 (incarnation 1) is given up (no spare) in state HELD" % r),
                  (6.31 + 0.01 * r * (1 if slow_fb else 0) + (1.5 if slow_fb else 0.0),
                   "GINRS step rank=%d step=120 released=1 got=1 want=2" % r),
                  (0.5, "GIN/RS: rank 3: checkpoint 100 stable")] for r in (0, 1, 2)}
        _rs(raw, "rs4_kill3_spareabsent", "rs", k, kill=3, spare=True, live=live, spare_kill=1.5,
            surv=dict(released=1, steps_done=120), lib_lines=fb)
        _rs(raw, "rs4_none", "rs", k, live=live, win=W,
            lib_lines={r: [(1.0, "GIN/RS: rank %d: checkpoint 20 input pause peer=0 pause_us=2300" % r)] for r in range(4)})
        _rs(raw, "rs4_none_off", "rs", k, restore="0", live=live, win=[(0, 0, 1), (0, 0, 1)])
        dg = {r: [(3.0, "GIN/TS: rank %d: peer 3 judged dead" % r), (5.3, "GINRS step rank=%d step=110 released=1 got=1 want=2" % r)]
              for r in (0, 1, 2)}
        _rs(raw, "rs4_kill3", "hk", k, kill=3, policy="failfast", restore="0", live=False,
            surv=dict(released=1, steps_done=110), lib_lines=dg)
    for k in range(1, 4):
        _rs(raw, "rs4_refuse_symgin", "rs", k, live=False, refuse="rank_0:_symmetric_kernel_GIN_devComm",
            ff_rank=(0 if refuse_ff else None))
        _rs(raw, "rs4_refuse_gintype", "rs", k, live=False, refuse="the_devComm_is_not_GDAKI")
        _rs(raw, "rs4_refuse_restoreoff1", "rs", k, live=False, refuse="NCCL_GIN_RESTORE_differs")
    for k in range(1, 6):
        _reg(reg, "reg_mr4_none", k, REG_OK_NONE)
        _reg(reg, "reg_mr4_none_hold", k, REG_OK_NONE)
        _reg(reg, "reg_rm4_kill3_untimed", k, dict(REG_OK_KILL, n_stuck_surv=(1 if reg_bad and k == 1 else 0)))
        _reg(reg, "reg_rm4_kill3_untimed_hold", k, REG_OK_KILL)
    _all_cost(cost, ffb_sep=ffb_sep)


def selftest():
    global reg_columns
    real = reg_columns
    reg_columns = _selftest_reg_columns  # synthetic gin-remaining columns (its row code needs real gin_mr output)
    fails = []

    def expect(name, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (name, got, want))
    try:
        # A: the restore layer integrated, every prediction holds
        dA = tempfile.mkdtemp(prefix="rs_self_A_")
        _build_A(dA)
        vA = score(dA)
        for pid in ("wait_held", "data_equal", "no_reexec", "revived_done", "suppress_exact", "restore_time", "ckpt_kill",
                    "kill_other", "nospare_failfast", "spare_absent_fallback", "control_degraded", "none_clean", "strict_forced", "strict_notforced",
                    "refuse_reason", "regression_none", "regression_kill3", "cost_ff"):
            expect("A/" + pid, vA.get(pid), "맞음")
        expect("A/cost_log", vA.get("cost_log"), "문턱 대기(pilot 뒤)")
        expect("A/cost_unarmed", vA.get("cost_unarmed"), "문턱 대기(pilot 뒤)")
        # B: not integrated (the Step hook never ran; no library lines): the kill cells are 자료 부족, the library-column
        # predictions too; strict, refusal, regression and the hk control without its library lines as stated
        dB = tempfile.mkdtemp(prefix="rs_self_B_")
        raw = os.path.join(dB, "raw")
        for k in range(1, 11):
            _rs(raw, "rs4_kill3", "rs", k, kill=3, spare=True, live=False, surv=dict(released=1, steps_done=100))
        for k in range(1, 6):
            _rs(raw, "rs4_none", "rs", k, live=False, win=[(1, 1, 0)])
            _rs(raw, "rs4_none_off", "rs", k, restore="0", live=False, win=[(0, 0, 1)])
        for k in range(1, 4):
            _rs(raw, "rs4_refuse_symgin", "rs", k, live=False, refuse="r")
            _rs(raw, "rs4_refuse_gintype", "rs", k, live=False, refuse="g")
            _rs(raw, "rs4_refuse_restoreoff1", "rs", k, live=False, refuse="o")
        for k in range(1, 6):
            nsp = {r: [(3.0, "GIN/TS: rank %d: peer 3 judged dead" % r), (3.0, "GIN/TS: declined rank=3 why=peer-dead"),
                       (5.4, "GINRS step rank=%d step=120 released=1 got=1 want=2" % r)] for r in (0, 1, 2)}
            _rs(raw, "rs4_kill3_nospare", "rs", k, kill=3, live=False, surv=dict(released=1, steps_done=120), lib_lines=nsp)
            _rs(raw, "rs4_kill3_spareabsent", "rs", k, kill=3, spare=True, live=False, spare_kill=1.5,
                surv=dict(released=1, steps_done=120), lib_lines=nsp)
        vB = score(dB)
        for pid in ("wait_held", "data_equal", "no_reexec", "revived_done", "suppress_exact", "restore_time", "none_clean",
                    "regression_none", "cost_ff", "spare_absent_fallback"):
            expect("B/" + pid, vB.get(pid), "자료 부족")
        for pid in ("strict_forced", "strict_notforced", "refuse_reason", "nospare_failfast"):
            expect("B/" + pid, vB.get(pid), "맞음")
        # C: failures are 틀림: a refusal that fell through on one rank, two trials with a bad received slot (10 scored,
        # 8 good < 9), one regression trial with a stuck survivor, a fail-fast branch arm that separates
        dC = tempfile.mkdtemp(prefix="rs_self_C_")
        _build_A(dC, bad_data=True, refuse_ff=True, reg_bad=True, ffb_sep=True, slow_fb=True)
        vC = score(dC)
        for pid in ("refuse_reason", "data_equal", "regression_kill3", "cost_ff", "spare_absent_fallback"):
            expect("C/" + pid, vC.get(pid), "틀림")
        expect("C/wait_held", vC.get("wait_held"), "맞음")
        # D: the parser's rules
        dD = tempfile.mkdtemp(prefix="rs_self_D_")
        raw = os.path.join(dD, "raw")
        _rs(raw, "rs4_kill3", "rs", 1, kill=3, spare=True,
            lib_lines={0: [(3.0, "NCCL WARN GIN/TS: rank 0: peer 3 judged dead")]})
        _rs(raw, "rs4_kill3", "rs", 2, kill=3, spare=True,
            lib_lines={0: [(3.0, "NCCL WARN GIN/TS: declined rank=3 why=peer-dead")]})
        _rs(raw, "rs4_refuse_symgin", "rs", 1, live=False, refuse=["a", "a", "b", "a"])
        _rs(raw, "rs4_none", "rs", 1, win=[(1, 1, 0), (0, 1, 0)])
        _rs(raw, "rs4_kill3", "rs", 3, kill=3, spare=True, surv=dict(steps_done=399))
        rows = {r["id"]: r for r in rows_rs.all_rows(dD)}
        expect("D/judged-dead not a decline", rows["rs4_kill3_rs_n1"]["wait_held"], 1)
        expect("D/a decline line", rows["rs4_kill3_rs_n2"]["wait_held"], 0)
        expect("D/reasons differ", rows["rs4_refuse_symgin_rs_n1"]["reason_same"], 0)
        expect("D/strict=0 under force (one line per rank)", rows["rs4_none_rs_n1"]["strict_bad"], 4)
        expect("D/an unfinished survivor is not held", rows["rs4_kill3_rs_n3"]["wait_held"], 0)
        expect("D/kill applied by exit 137", rows["rs4_kill3_rs_n1"]["applied"], 1)
        _rs(raw, "rs4_kill3", "rs", 4, kill=3, spare=True, spare_fail=True)
        _rs(raw, "rs4_kill3", "rs", 5, kill=3, spare=True, gpu="1/0")
        _rs(raw, "rs4_none", "rs", 2, refuse="x")
        _rs(raw, "rs4_spare_neg", "rs", 1, negs=("neg_cut", "neg_field"))
        _rs(raw, "rs4_spare_neg", "rs", 2, negs=("neg_cut", "neg_field"), neg_ok=False)
        _rs(raw, "rs4_kill3_strace", "rs", 1, kill=3, spare=True,
            strace=dict(peer_connect_before_ready=0, peer_connect_after_ready=3, uds_own_rank=2, uds_other_rank=0, rt_known=1))
        rows = {r["id"]: r for r in rows_rs.all_rows(dD)}
        expect("D/spare start failure excluded", status_rs(rows["rs4_kill3_rs_n4"]), "spare_start_fail")
        _rs(raw, "rs4_kill3_spareabsent", "rs", 1, kill=3, spare=True, spare_kill=2.5)
        rsa = {r["id"]: r for r in rows_rs.all_rows(dD)}["rs4_kill3_spareabsent_rs_n1"]
        expect("D/spare killed after its rank is excluded", status_rs(rsa), "spare_not_killed")
        expect("D/foreign GPU app excluded", status_rs(rows["rs4_kill3_rs_n5"]), "foreign_gpu")
        expect("D/refusal in a hold cell is config", status_rs(rows["rs4_none_rs_n2"]), "config")
        expect("D/negatives failed", (rows["rs4_spare_neg_rs_n1"]["neg_cut_failed"], rows["rs4_spare_neg_rs_n1"]["neg_field_failed"]), (1, 1))
        expect("D/a negative that reached ready did not fail", rows["rs4_spare_neg_rs_n2"]["neg_cut_failed"], 0)
        _rs(raw, "rs4_spare_neg", "rs", 3, negs=("neg_cut",))
        _w(os.path.join(raw, "rs4_spare_neg_rs_n3_neg_cut.log"), "1.0 host WARN GIN/RS: replay ON rank=3 nranks=4 entries=9\n")
        r3 = {r["id"]: r for r in rows_rs.all_rows(dD)}["rs4_spare_neg_rs_n3"]
        expect("D/an informational replay line is not a replay failure", r3["neg_cut_failed"], 0)
        expect("D/replay and activation times", (rows["rs4_kill3_strace_rs_n1"]["spare_replay_ms"],
                                                 rows["rs4_kill3_strace_rs_n1"]["spare_activate_ms"]), (1250.0, 1999.0))
        expect("D/strace counts", (rows["rs4_kill3_strace_rs_n1"]["spare_peer_before"],
                                   rows["rs4_kill3_strace_rs_n1"]["spare_uds_own"]), (0, 2))
    finally:
        reg_columns = real
    if fails:
        print("SELFTEST FAILED:")
        for x in fails:
            print("  " + x)
        return 1
    print("SELFTEST: all checks passed")
    return 0


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest())
    if len(sys.argv) < 2:
        sys.exit("usage: score.py <resultsdir> | --selftest")
    score(os.path.abspath(sys.argv[1]))


if __name__ == "__main__":
    main()
