#!/usr/bin/env python3
"""gin-mirror test-branch scorer (DRAFT until the pre-registration): applies predictions_mi.csv to a results folder and
writes <resultsdir>/SCORE.md and trials_scored.csv. gin-restore's score.py (../../../restore/impl/test/score.py), with the
mirror cells, the mirror exclusions and a cost_eval that judges some metrics of a family with five rules.

usage: score.py <resultsdir>
       score.py --selftest        the CPU-only synthetic self-test (no results folder, no cluster)

Steps (../../EXPERIMENT.md 3, 8), as gin-restore does:
  1. rows_mi.all_rows(): one row per trial (raw/: the mirror cells and gin-restore's cells at @mi; reg/: gin-remaining's
     runner, mirror off; cost*/: the mirror cost family). Regression rows get gin-remaining's own columns.
  2. a status per trial: scored, or an exclusion of section 8: void, config_driver, workload (the trial ran another
     OVERWRITE/TRAIN, mirror or checksum setting than its cell names), not_applied, spare_start_fail (either spare),
     config (a refused Resume outside the refusal cells, or gin-restore's config check), foreign_gpu, restore_not_live,
     kill_before_ckpt (the first kill before a stable checkpoint: the whole trial, also in the second-death cells),
     cost_invalid, surplus. The refusal cells (mi4_refuse_*, rs4_refuse_*) skip the workload, kill and Resume checks.
  3. per key cell@build the first PLANNED candidates by trial number are scored; "자료 부족" when a cell has fewer scored
     trials than ceil(0.75 x planned) or a library-only column its formula reads is empty in every scored trial.
  4. the acceptance formulas use gin-restore's section 3.2 grammar (s2_close; median(col, "cell@build") outside count()).
     The cost rows ("cost: rule=...") read the mirror family per receiving node over the metrics the cells spec names
     (cost:<family>:<arms>:<metrics>, each judged arm against the family's base arm):
       report             no verdict
       not_separated      맞음 iff no judged arm separates from the base (every run of one worse than every run of the other)
       within:<pct>       the judged arm's median within pct% of the base's in the worse direction
       within_us:<x>      the judged arm's median at most x (the metric's unit, µs for latency) worse than the base's
       ratio:<lo>-<hi>    median(arm) / median(base) within [lo, hi] (bandwidth: section 3's 0.40-0.60)
     Fewer than 5 valid runs of a shown arm in a judged metric on a node: 자료 부족.
"""
import csv, hashlib, importlib.util, json, math, os, re, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
GR = os.path.join(HERE, "..", "..", "..")  # gin_recovery/
_spec = importlib.util.spec_from_file_location("s2_score", os.path.join(GR, "s2_close", "score.py"))
s2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s2)  # the section 3.2 grammar: evaluate, keys_of, NIL
_spec = importlib.util.spec_from_file_location("grm_score", os.path.join(GR, "remaining", "score.py"))
rem = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rem)  # gin-remaining's scorer as a library: rows_of, extra_pq4, extra_hr4, status4
sys.path.insert(0, HERE)
import rows_mi  # noqa: E402
rows_rs = rows_mi.rows_rs

CELLS = os.path.join(HERE, "cells_mi.json")
PREDS = os.path.join(HERE, "predictions_mi.csv")
# the restore reaction must be live (the kill cells that revive; gin-restore's at @mi too)
NEEDS_LIVE = {"mi4_kill3_ow", "mi4_kill1_ow", "mi4_kill3_ckpt_ow", "mi4_kill2_kill3_ow", "mi4_pull", "mi4_seg_4k",
              "mi4_seg_32k", "mi4_seg_128k", "mi4_train_kill3", "mi4_train_kill2_kill3", "rs4_kill3", "rs4_kill3_ckpt",
              "rs4_kill1", "rs4_kill3_spareabsent", "rs4_kill3_mion"}
REFUSAL = ("mi4_refuse", "rs4_refuse")
# the library-only columns a formula may read (empty in every scored trial -> 자료 부족, the layer does not emit them yet)
LIB_COLS = set(rows_rs.LIBCOLS) | {"from_pool_ok", "export_source_bytes", "import_pool_bytes", "fetch_us", "fetch_bytes",
                                   "pool_max_bytes", "restarts", "pulls_sent", "broken_total", "inj_sent_step",
                                   "inj_from_n", "paced_ok", "tcp_image_bytes", "tcp_segment_bytes", "nomirror_detect",
                                   "restore_time_ms_1", "restore_time_ms_2"}
EXCL = {"void": "시작 실패(생존 rank가 교환 전에 끝남)", "not_applied": "장애 미적용(kill 기록 없음)",
        "config": "설정 확인 실패(셀이 요구한 정책/복원 설정 아님, 또는 거절 셀 밖에서 Resume 거절)",
        "workload": "workload(덮어쓰기, 학습 모양)나 mirror, checksum 설정이 셀과 다름",
        "restore_not_live": "복원 계층 미통합(Step hook이 실행되지 않음; 통합 뒤에만 채점)",
        "kill_before_ckpt": "kill이 첫 확정 체크포인트 전", "spare_start_fail": "예비 프로세스가 활성화 전에 시작에 실패함",
        "foreign_gpu": "시행 시작 때 GPU에 다른 프로세스",
        "cost_invalid": "비용 실행 무효(오류, 값 없음, win_flags나 tx_done이 다름, mirror 팔은 mirror summary 없음이나 깨짐)",
        "config_driver": "셀이 정한 빌드가 아닌 프로그램으로 돎", "surplus": "계획 수를 넘은 시행"}
EXCL.update(getattr(rem, "EXCL_LABEL", {}))


def load_cells():
    return json.load(open(CELLS))


def expected_drivers(c):
    e = {}
    for h, cl in c["holds"].items():
        for x in cl:
            e["%s@%s" % (x["cell"], x["build"])] = x.get("driver", "")
    for fam in c["cost"]["families"].values():
        for m in fam["metrics"]:
            for a in fam["arms"]:
                lib = fam["lib"][a] if isinstance(fam["lib"], dict) else fam["lib"]
                e["cost_%s_%s@%s" % (m, a, lib)] = fam.get("drivers", {}).get(a, "gin_ts2_mi")
    return e


def planned(c):
    p = {}
    for h, cl in c["holds"].items():
        if h.startswith("P"):
            continue
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
    out = {k: ("" if v is None else v) for k, v in rem.rows_of(stem).items()}
    out.update({k: ("" if v is None else v) for k, v in rem.extra_pq4(stem, out).items()})
    out.update({k: ("" if v is None else v) for k, v in rem.extra_hr4(stem, out).items()})
    return out


EXPECT_DRIVER = {}


def driver_ok(r):
    want = EXPECT_DRIVER.get(r["key"], "")
    return not want or str(r.get("driver", "")) == want


def cell_env(cells, cell, build):
    for h, cl in cells["holds"].items():
        for e in cl:
            if e["cell"] == cell and e["build"] == build:
                return e.get("env", {})
    return {}


def status_rs(r, cells):
    if int(r.get("void") or 0):
        return "void"
    if not driver_ok(r):
        return "config_driver"
    if str(r["cell"]).startswith(REFUSAL):  # misconfigured on purpose; the refusal is the result
        return "foreign_gpu" if str(r.get("foreign_gpu")) == "1" else "candidate"
    env = cell_env(cells, r["cell"], r.get("build", "mi"))
    # section 8: the trial ran the cell's workload and mirror/checksum setting (empty kv values: a driver without them)
    want_train = int(env.get("TRAIN", "0"))
    want_ow = int(env.get("OVERWRITE", "1" if want_train else "0"))
    if r.get("overwrite") not in ("", None) and (int(r.get("overwrite") or 0) != want_ow or
                                                 int(r.get("train") or 0) != want_train):
        return "workload"
    if str(r.get("mirror_env", "")) not in ("", "unset") and str(r.get("mirror_env")) != env.get("MIRROR", "1"):
        return "workload"
    if str(r.get("checksum_env", "")) not in ("", "unset") and str(r.get("checksum_env")) != env.get("CHECKSUM", "off"):
        return "workload"
    if str(r.get("kill_rank", "")).isdigit() and int(r.get("applied") or 0) == 0:
        return "not_applied"
    if str(r.get("spare_start_fail")) == "1" or str(r.get("spare2_start_fail")) == "1":
        return "spare_start_fail"
    if str(r.get("resume_refused")) == "1" or int(r.get("config_ok") or 0) == 0:
        return "config"
    if str(r.get("foreign_gpu")) == "1":
        return "foreign_gpu"
    if r["cell"] in NEEDS_LIVE:
        if int(r.get("restore_live") or 0) == 0:
            return "restore_not_live"
        if str(r.get("ckpt_stable_before_kill")) == "0":
            return "kill_before_ckpt"
    return "candidate"


def ours_mrkey(mk):
    return bool(re.search(r"rs-bundle/(?:[A-Za-z0-9][^/]*/)?mr/(?:ff|hold)/?$", mk)) or mk == "hr"


def status_reg(r, orig):
    if not orig:
        return "config"
    if not driver_ok(r):
        return "config_driver"
    mk = str(r.get("mrkey") or "")
    return rem.status4(dict(r, build="hr", cell=orig, mrkey="hr" if ours_mrkey(mk) else mk))


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
    for k in use:
        rows = scored.get(k, [])
        if rows and any(all(val_empty(r.get(c)) for r in rows) for c in refs):
            short.append(k)
    evals = []
    for k in use:
        ak = re.sub(r"\bN_SCORED\b", str(len(scored.get(k, []))), a)
        evals.append((k,) + s2.evaluate(ak, scored, k, s2.NIL))
    ok = all(e[1] for e in evals)
    return keys, evals, ("자료 부족" if short else ("맞음" if ok else "틀림")), sorted(set(short))


def parse_rule(rule):
    """(kind, a, b): report | not_separated | within (pct) | within_us (x) | ratio (lo, hi)"""
    if rule in ("report", "not_separated"):
        return rule, None, None
    kind, _, arg = rule.partition(":")
    if kind == "within":
        return kind, float(arg), None
    if kind == "within_us":
        return kind, float(arg), None
    if kind == "ratio":
        lo, _, hi = arg.partition("-")
        return kind, float(lo), float(hi)
    raise ValueError("unknown cost rule %r" % rule)


def cost_eval(p, rows, cells):
    """see the head comment (rules); returns (verdict, table lines)"""
    parts = [x.strip() for x in p["cells"].split(":")]
    fam_name = parts[1]
    kind, ra, rb = parse_rule(p["acceptance"].split("rule=", 1)[1].strip())
    fam = cells["cost"]["families"][fam_name]
    base = fam["base"]
    named = [a for a in parts[2].split(",") if a] if len(parts) >= 3 else []
    judge_metrics = [m for m in parts[3].split(",") if m] if len(parts) >= 4 else list(fam["metrics"])
    for a in named:
        if a not in fam["arms"]:
            raise ValueError("arm %r is not in cost family %s (prediction %s)" % (a, fam_name, p.get("id")))
    for m in judge_metrics:
        if m not in fam["metrics"]:
            raise ValueError("metric %r is not in cost family %s (prediction %s)" % (m, fam_name, p.get("id")))
    shown = [a for a in fam["arms"] if not named or a == base or a in named]
    judged = (set(named) - {base}) if named else set(fam.get("judged", fam["arms"]))
    lines, short, bad = [], False, False
    for node in cells["cost"]["nodes"]:
        for m in judge_metrics:
            vals = {}
            for a in shown:
                vals[a] = sorted(float(r["value"]) for r in rows if r["runner"] == "cost" and r["status"] == "scored"
                                 and r["metric"] == m and r["arm"] == a and r["rx"] == node)
            if any(len(v) < 5 for v in vals.values()):
                short = True
            bv = vals.get(base, [])
            for a in shown:
                v = vals[a]
                if not v:
                    lines.append("| %s | %s | %s | 0 | - | - | - |" % (node, m, a))
                    continue
                med = statistics.median(v)
                if a == base or not bv:
                    lines.append("| %s | %s | %s | %d | %.3f | - | 기준 |" % (node, m, a, len(v), med))
                    continue
                bmed = statistics.median(bv)
                worse_hi = not m.startswith("bw")  # latency higher is worse; bandwidth lower is worse
                d = (med - bmed) if worse_hi else (bmed - med)  # positive: worse than the base
                pct = 100.0 * d / bmed if bmed else float("inf")
                ratio = med / bmed if bmed else float("inf")
                if kind == "within":
                    ok = pct <= ra
                    tag = "%+.1f%% (≤ %g%%)" % (pct, ra)
                elif kind == "within_us":
                    ok = d <= ra
                    tag = "%+.3f (≤ %g)" % (d, ra)
                elif kind == "ratio":
                    ok = ra <= ratio <= rb
                    tag = "비 %.3f (%g–%g)" % (ratio, ra, rb)
                elif kind == "not_separated":
                    s_worse = (min(v) > max(bv)) if worse_hi else (max(v) < min(bv))
                    s_better = (max(v) < min(bv)) if worse_hi else (min(v) > max(bv))
                    ok = not (s_worse or s_better)
                    tag = "갈림(나쁨)" if s_worse else "갈림(좋음)" if s_better else "차이를 잴 수 없음"
                else:
                    ok, tag = True, "비 %.3f" % ratio
                if a in judged and kind != "report":
                    tag = ("범위 안 " if ok else "범위 밖 ") + tag
                    if not ok:
                        bad = True
                elif kind != "report":
                    tag += "(보고만)"
                lines.append("| %s | %s | %s | %d | %.3f | %+.3f (%+.1f%%) | %s |" % (node, m, a, len(v), med, d,
                                                                                    pct if bmed else 0.0, tag))
    if short:
        verdict = "자료 부족"
    elif kind == "report":
        verdict = "보고만(판정 없음)"
    else:
        verdict = "틀림" if bad else "맞음"
    return verdict, lines


def score(R):
    cells = load_cells()
    PLANNED = planned(cells)
    EXPECT_DRIVER.clear()
    EXPECT_DRIVER.update(expected_drivers(cells))
    orig = cells.get("regression_orig", {})
    rows = rows_mi.all_rows(R)
    for r in rows:
        if r["runner"] == "mrr":
            r.update(reg_columns(r["stem"], r))
            r["status"] = status_reg(r, orig.get(r["cell"]))
        elif r["runner"] == "cost":
            r["status"] = ("candidate" if driver_ok(r) else "config_driver") if str(r.get("cost_valid")) == "1" \
                else "cost_invalid"
        else:
            r["status"] = status_rs(r, cells)
    cols = []
    for r in rows:
        for c in r:
            if c not in cols:
                cols.append(c)
    for c in rows_mi.MI_COLS:  # every formula column exists even when no row has it
        if c not in cols:
            cols.append(c)
    for r in rows:
        for c in cols:
            r.setdefault(c, "")
    by_key, scored = {}, {}
    for r in sorted(rows, key=lambda x: (x["key"], x.get("tnum") or 0, x["sub"])):
        by_key.setdefault(r["key"], []).append(r)
    for k, rs in by_key.items():
        cand = [r for r in rs if r["status"] == "candidate"]
        if k.startswith("cost_"):
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
    frozen = ""
    for pr in (os.path.join(HERE, "..", "..", "PREREG.txt"), os.path.join(HERE, "PREREG.txt")):
        if os.path.exists(pr):
            frozen = open(pr).read()
            break
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
    L = ["# gin-mirror 채점 결과 (test 갈래)", "",
         "`score.py`가 원자료에서 만들었다. 손으로 고친 값은 없다. 문턱과 반복 수는 사전 등록으로 고정한다(DRAFT; ../../EXPERIMENT.md 3, 7, 8절).", "",
         "- 예측 파일 sha256: `%s`. `PREREG.txt`의 값과 %s." % (sha, "같다" if sha in frozen else "다르다(사전 등록한 파일이 아님)"),
         "- 시행 수: %d. 판정한 시행: %d." % (len(rows), sum(len(v) for v in scored.values())),
         "- 판정식 원문은 `predictions_mi.csv`, 문법은 `../../../s2_close/EXPERIMENT.md` 3.2.", "",
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
                L.append("  - `count(%s)` = %d/%d. 만족하지 않은 시행: %s" % (
                    inner, c, n, ", ".join(os.path.basename(str(x)) for x in fs) if fs else "없음"))
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
            recv_bad=0, xhist_bad=0, dev_bad=0, x_match=1, sig_exact=1, reexec_any=0, async_n=0, exit=0,
            recv_poison=0, dev_poison=0)


def _mi(d, cell, k, *, kill=None, kill2=None, spare=False, spare2=False, mirror="1", checksum="off", overwrite=1,
        train=0, ring=0, live=True, surv=None, sp=None, refuse=None, ff_rank=None, lib_lines=None, mi_lines=None,
        spare_lines=None, t0=100.0, spare_fail=False, spare2_fail=False, hook=None, gpu="0/0", poison=False,
        store_tcp=False, die2_t=2.5, killed_line=True):
    """one synthetic gin-mirror restore trial (stamped logs, kv, meta). lib_lines[r] / mi_lines[r]: extra lines of rank r
    (offsets from t0); spare_lines["spare" | "spare_2nd"]: extra lines of a spare. With the mirror on (and no refusal) every
    live rank logs a store summary at teardown (tcp bytes 0, or not with store_tcp)."""
    build = "mi"
    os.makedirs(d, exist_ok=True)
    stem = os.path.join(d, "%s_%s_n%d" % (cell, build, k))
    n = 4
    rcs = {r: 0 for r in range(n)}
    for kk in (kill, kill2):
        if kk is not None:
            rcs[kk] = 137
    meta = dict(cell=cell, lib=build, n=n, policy="hold", restore="1", kill_rank=("" if kill is None else kill),
                kill2_rank=("" if kill2 is None else kill2), spare=int(spare), spare2=int(spare2),
                spare_wanted=int(spare), spare2_wanted=int(spare2), spare_ready=int(spare and not spare_fail),
                spare2_ready=int(spare2 and not spare2_fail), gpu_apps_before=gpu, mirror=mirror, overwrite=overwrite,
                train=train, ring=ring, restore_ms=20000, runner="mir", wall_s=5.0, kill_in_hook=int(hook is not None),
                die_switch=("NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT" if hook is not None else "-"), driver="gin_mi")
    meta.update({"r%drc" % r: rcs[r] for r in range(n)})
    _w(stem + "_meta.txt", _kvline(**meta))
    wl = "train" if train else ("overwrite" if overwrite else "gin_rs")
    for r in range(n):
        kv = dict(GOOD, rank=r, rs_hooks_live=int(live), workload=wl, overwrite=overwrite, train=train, ring=ring,
                  mirror_env=mirror, checksum_env=checksum)
        if refuse is not None:
            kv.update(resume_rc=(0 if r == ff_rank else 3), resume_why=refuse[r] if isinstance(refuse, list) else refuse)
        killed = r in (kill, kill2)
        if killed:
            kv = dict(rank=r, init_rc=0, reg_rc=0, devcomm_rc=0, resume_rc=0, steps=400, rs_hooks_live=int(live),
                      workload=wl, overwrite=overwrite, train=train, ring=ring, mirror_env=mirror, checksum_env=checksum)
        elif surv:
            kv.update(surv)
        if poison and not killed:
            kv.update(recv_poison=2, dev_poison=1)
        _w(stem + "_r%d.kv" % r, _kvline(**kv))
        lines = ["%.6f GINRS start rank=%d mode=live" % (t0, r)]
        for t, txt in (lib_lines or {}).get(r, []) + (mi_lines or {}).get(r, []):
            lines.append("%.6f %s" % (t0 + t, txt))
        if not killed and mirror == "1" and refuse is None:
            lines.append("%.6f GIN/MI: rank %d: store summary: writes=5 failed=0 requests=1 tcp_image_bytes=%d "
                         "tcp_segment_bytes=%d mono_ms=1.0" % (t0 + 9.5, r, 100 if store_tcp else 0, 50 if store_tcp else 0))
        if killed:
            lines.append("%.6f GINRS step rank=%d step=100 released=0" % (t0 + 2.0, r))
            if hook is not None and r == kill:
                lines.append("%.6f host NCCL WARN GIN/RS: rank %d: test switch NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT: "
                             "dying %d us after the pause request of checkpoint %d (stable checkpoints before: 2) "
                             "mono_ms=1.0" % (t0 + 2.0005, r, hook[1], hook[0]))
        _w(stem + "_r%d.log" % r, "\n".join(sorted(lines, key=lambda x: float(x.split(" ", 1)[0]))) + "\n")
    kl = ""
    if kill is not None and hook is None and killed_line:
        kl += "%.6f GINRS killed rank=%d node=sunny pid=999\n" % (t0 + 2.001, kill)
    if kill2 is not None:
        kl += "%.6f GINRS die rank=%d step=400 where=kernel delay_us=0 mono_ms=1.0\n" % (t0 + die2_t, kill2)
    if kl:
        _w(stem + "_kill.out", kl)
    for which, krank, on in (("spare", kill, spare), ("spare_2nd", kill2, spare2)):
        if not on:
            continue
        skv = dict(GOOD, rank=krank, mode="spare", resume_step=100, revived=1, start_step=101, rs_hooks_live=1,
                   workload=wl, overwrite=overwrite, train=train, ring=ring, mirror_env=mirror, checksum_env=checksum)
        if sp:
            skv.update(sp)
        _w("%s_%s.kv" % (stem, which), _kvline(**skv))
        sl = [(t0, "GINRS start rank=%d mode=spare" % krank), (t0 + 1.25, "GINRS spare_ready rank=%d rt_s=1.0" % krank),
              (t0 + 4.0, "GINRS resume rank=%d rc=0 step=100" % krank)]
        sl += [(t0 + t, txt) for t, txt in (spare_lines or {}).get(which, [])]
        _w("%s_%s.log" % (stem, which), "\n".join("%.6f %s" % x for x in sorted(sl)) + "\n")


def _reg(d, cell, k, cols):
    os.makedirs(d, exist_ok=True)
    stem = os.path.join(d, "%s_n%d" % (cell, k))
    mk = "hold" if cell.endswith("_hold") else "ff"
    _w(stem + "_meta.txt", _kvline(cell=cell, lib="../../rs-bundle/mi1/lib/mi", mrkey="../../../rs-bundle/mi1/mr/" + mk,
                                   n=4, runner="mrr", selftest=json.dumps(cols).replace(" ", "")))


def _cost(d, metric, arm, node, k, value, summary_broken=0, summary=True):
    """one synthetic cost run; value is µs (latency) or GB/s (bandwidth: written as the p50 that gives it)"""
    os.makedirs(d, exist_ok=True)
    cell = "cost_%s_%s_%s" % (metric, arm, node)
    stem = os.path.join(d, "%s_k%d" % (cell, k))
    iters = {"bw256k": 12, "bw2m": 24}.get(metric, 3000)
    _w(stem + "_meta.txt", _kvline(cell=cell, metric=metric, arm=arm, rx=node, lib="mip", runner="costmi", iters=iters,
                                   bin="gin_ts2_mi"))
    if metric.startswith("bw"):
        b = 262144 if metric == "bw256k" else 2097152
        p50 = 8 * b / (value * 1e9) * 1e6
        _w(stem + "_r0.kv", _kvline(lat_p50_us=round(p50, 4), burst_K=8, bytes=b, win_flags="0x3", tx_done=iters, exit=0))
    else:
        _w(stem + "_r0.kv", _kvline(lat_p50_us=value, win_flags="0x3", tx_done=iters, exit=0))
    _w(stem + "_r1.kv", _kvline(win_flags="0x3", exit=0))
    if arm.startswith("mirror-") and summary:
        _w(stem + "_r0.log", "host NCCL WARN GIN/MI: rank 0: mirror summary: switches=0 rollbacks=0 restarts=0 "
           "third_slot=0 max_live_bytes=1048576 pulls_sent=0 pulls_taken=0 broken=%d absorbed=0 mono_ms=1.0\n" % summary_broken)


def _mi_dead(r, subject):
    return [(3.0, "host NCCL WARN GIN/TS: rank %d: rank %d judged dead (cause=FIN) mono_ms=1.0" % (r, subject)),
            (3.4, "host NCCL WARN GIN/RS: rank %d: restore round with rank %d published (4 QP(s)) mono_ms=1.0" % (r, subject)),
            (0.5, "host NCCL WARN GIN/RS: rank %d: checkpoint 100 stable at buddy rank %d (ok) mono_ms=1.0" % (subject, subject ^ 1)),
            (0.6, "host NCCL WARN GIN/RS: rank %d: suppress peer=%d qp=%d budget=2 suppressed=2 left=0" % (r, subject, r)),
            (3.9, "host NCCL WARN GIN/RS: rank %d: rank %d restored as incarnation 1 (on time); state armed mono_ms=1.0" % (r, subject))]


def _mi_good(r, subject):
    """a survivor's mirror lines for a clean overwrite restore of `subject` (key=value order shuffled on purpose: the
    parser reads them in any order)"""
    return [(3.5, "GIN/MI: rank %d: export to rank %d: mirror_bytes=163840 entries=50 mirror_entries=40 source_bytes=0 first_step=81 last_step=100 mono_ms=1.0" % (r, subject)),
            (3.6, "GIN/MI: rank %d: drain for rank %d senders=3 queries=5 drain_us=120.0 mono_ms=1.0" % (r, subject)),
            (9.0, "GIN/MI: rank %d: mirror summary: switches=5 rollbacks=1 restarts=0 third_slot=0 max_live_bytes=9437184 pulls_sent=0 pulls_taken=0 broken=0 absorbed=0 mono_ms=1.0" % r),
            (1.0, "GIN/MI: rank %d: checkpoint 100 stored at buddy rank %d: slot=0 bytes=31457280 d2h_us=2390.0 write_us=2610.0 mono_ms=1.0" % (r, r ^ 1))]


def _spare_good(subject, *, fetch_us=13.1, image=31457280, seg=125829120, pool=491520):
    """a revived rank's lines: FETCH, the import of step 101 (in Resume), done, INJECTED, then step 101's kernel line.
    pool: the import's pool bytes = the survivors' export mirror_bytes summed (3 x 163840 for a single kill)"""
    return [(0.1, "GIN/MI: rank %d: fetch for checkpoint 100 from buddy rank %d: image_bytes=%d segment_bytes=%d extents=3 fetch_us=%.1f mono_ms=1.0" % (subject, subject ^ 1, image, seg, fetch_us)),
            (0.2, "GIN/MI: rank %d: import step 101: entries=40 pool_bytes=%d signals=3 import_us=50.0 mono_ms=1.0" % (subject, pool)),
            (0.3, "GIN/MI: rank %d: import done: steps=1 pool_bytes=%d left=0 mono_ms=1.0" % (subject, pool)),
            (0.4, "GIN/MI: rank %d: INJECTED sent: step=101 survivors=3 mono_ms=1.0" % subject),
            (4.5, "GINRS step rank=%d step=101 released=0 tx_err=0 hook_rc=0 stable=-1 mono_ms=1.0" % subject)]


def _inj_from(r, subject):
    return [(4.1, "GIN/MI: rank %d: INJECTED from rank %d: step=101 state=armed gate_odd_ms=250.0 mono_ms=1.0" % (r, subject))]


def _ow_kill3(d, cell, nmax, **kw):
    for k in range(1, nmax + 1):
        mi = {r: _mi_good(r, 3) + _inj_from(r, 3) for r in (0, 1, 2)}
        _mi(d, cell, k, kill=3, spare=True, lib_lines={r: _mi_dead(r, 3) for r in (0, 1, 2)}, mi_lines=mi,
            spare_lines={"spare": _spare_good(3)}, **kw)


def _kill2(d, cell, k, *, train=0, rearm=True, **kw):
    """a second-death trial: rank 2 dies at 2.0 and is restored (2.9), rank 3 stores a full image at the revived rank 2
    (3.5, one void at 3.2 before it), every survivor of the second death re-arms rank 3 (3.6), rank 3 dies at 5.0 and is
    restored from the revived rank 2"""
    L = {0: [], 1: [], 2: [], 3: []}
    L[2] += [(1.0, "GIN/RS: rank 2: checkpoint 200 stable at buddy rank 3 (ok) mono_ms=1.0"),
             (2.0, "GINRS die rank=2 step=205 where=kernel delay_us=10 mono_ms=1.0")]
    for r in (0, 1, 3):
        L[r] += [(2.1, "GIN/TS: rank %d: rank 2 judged dead (cause=FIN) mono_ms=1.0" % r),
                 (2.4, "GIN/RS: rank %d: restore round with rank 2 published (4 QP(s)) mono_ms=1.0" % r),
                 (2.9, "GIN/RS: rank %d: rank 2 restored as incarnation 1 (on time); state armed mono_ms=1.0" % r),
                 (0.6, "GIN/RS: rank %d: suppress peer=2 qp=%d budget=2 suppressed=2 left=0" % (r, r))]
    L[3] += [(3.2, "GIN/RS: rank 3: checkpoint 220 is void (no confirmation) mono_ms=1.0"),
             (3.5, "GIN/MI: rank 3: checkpoint 240 stored at buddy rank 2: slot=0 bytes=31457280 d2h_us=2390.0 write_us=2610.0 mono_ms=1.0")]
    second = [(5.1, "GIN/TS: rank %d: rank 3 judged dead (cause=FIN) mono_ms=1.0"),
              (5.4, "GIN/RS: rank %d: restore round with rank 3 published (4 QP(s)) mono_ms=1.0"),
              (5.9, "GIN/RS: rank %d: rank 3 restored as incarnation 1 (on time); state armed mono_ms=1.0")]
    arm = [(3.6, "GIN/RS: rank %d: rank 3 armed at its stable checkpoint 240 mono_ms=1.0")] if rearm else []
    for r in (0, 1):
        L[r] += [(t, x % r) for t, x in arm + second]
    sp1 = [(t, x % 2) for t, x in arm + second] + _spare_good(2)
    sp2 = _spare_good(3)
    _mi(d, cell, k, kill=2, kill2=3, spare=True, spare2=True, train=train, overwrite=1, ring=(4 if train else 0),
        lib_lines=L, spare_lines={"spare": sp1, "spare_2nd": sp2}, die2_t=5.0, **kw)


def _rg_build(raw, *, slow_fb=False):
    """gin-restore's restore and refusal cells at @mi with the mirror off: gin-restore's own synthetic builder
    (restore/impl/test/score.py _rs) with build mi and the gin-mirror drivers, as its _build_A lays them out"""
    spec = importlib.util.spec_from_file_location("rs_score", os.path.join(GR, "restore", "impl", "test", "score.py"))
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    W = [(1, 1, 0), (1, 1, 0), (1, 1, 0)]
    dead = lambda: {r: [(3.0, "host:1:1 [0] NCCL WARN GIN/TS: rank %d: peer 3 judged dead (FIN without a goodbye)" % r),
                        (3.4, "host:1:1 [0] NCCL WARN GIN/RS: rank %d: hold peer=3 published epoch=4" % r),
                        (0.5, "host:1:1 [0] NCCL WARN GIN/RS: rank 3: checkpoint 100 stable"),
                        (0.6, "host:1:1 [0] NCCL WARN GIN/RS: rank %d: suppress peer=3 ctx=%d budget=2 suppressed=2" % (r, r))]
                    for r in (0, 1, 2)}
    for k in range(1, 11):
        rs._rs(raw, "rs4_kill3", "mi", k, kill=3, spare=True, lib_lines=dead(), driver="gin_mi")
    for k in range(1, 6):
        ck = {r: dead()[r] + [(2.0012, "GIN/RS: rank %d: input pause for rank 3's checkpoint 120 ended (a hold of that "
                                       "rank took its gates) pause_us=900" % r),
                              (0.51, "GIN/RS: rank %d: rank 3 armed at its stable checkpoint 100" % r)] for r in (0, 1, 2)}
        rs._rs(raw, "rs4_kill3_ckpt", "mi", k, kill=3, spare=True, lib_lines=ck, hook=(120, 300), driver="gin_mi")
        rs._rs(raw, "rs4_kill1", "mi", k, kill=1, spare=True, driver="gin_mi",
               lib_lines={r: [(0.5, "GIN/RS: rank 1: checkpoint 100 stable")] for r in (0, 2, 3)})
        nsp = {r: [(3.0, "GIN/TS: rank %d: peer 3 judged dead" % r), (3.0, "GIN/TS: declined rank=3 why=peer-dead"),
                   (5.3, "GINRS step rank=%d step=120 released=1 got=1 want=2" % r)] for r in (0, 1, 2)}
        rs._rs(raw, "rs4_kill3_nospare", "mi", k, kill=3, surv=dict(released=1, steps_done=120), lib_lines=nsp,
               driver="gin_mi")
        fb = {r: [(3.0, "GIN/TS: rank %d: peer 3 judged dead" % r),
                  (3.01, "GIN/RS: rank %d: hold of rank 3 started: gates odd since 0.4 ms before the start" % r),
                  (4.01, "GIN/RS: rank %d: the restore of rank 3 (incarnation 1) is given up (no spare) in state HELD" % r),
                  (6.31 + (1.5 if slow_fb else 0.0), "GINRS step rank=%d step=120 released=1 got=1 want=2" % r),
                  (0.5, "GIN/RS: rank 3: checkpoint 100 stable")] for r in (0, 1, 2)}
        rs._rs(raw, "rs4_kill3_spareabsent", "mi", k, kill=3, spare=True, spare_kill=1.5,
               surv=dict(released=1, steps_done=120), lib_lines=fb, driver="gin_mi")
        rs._rs(raw, "rs4_none", "mi", k, win=W, driver="gin_mi",
               lib_lines={r: [(1.0, "GIN/RS: rank %d: checkpoint 20 input pause peer=0 pause_us=2300" % r)] for r in range(4)})
        rs._rs(raw, "rs4_none_off", "mi", k, restore="0", win=[(0, 0, 1), (0, 0, 1)], driver="gin_mi")
    for k in range(1, 4):
        rs._rs(raw, "rs4_refuse_symgin", "mi", k, live=False, refuse="rank_0:_symmetric_kernel_GIN_devComm", driver="gin_mi")
        rs._rs(raw, "rs4_refuse_gintype", "mi", k, live=False, refuse="the_devComm_is_not_GDAKI", driver="gin_mi")
        rs._rs(raw, "rs4_refuse_restoreoff1", "mi", k, live=False, refuse="NCCL_GIN_RESTORE_differs", driver="gin_mi")
        rs._rs(raw, "rs4_refuse_nomacro", "mi", k, live=False, driver="gin_mi_nomacro", ran_after_refusal=True,
               refuse="program_not_built_with_NCCL_GIN_RESTORE_DEVICE")


REG_OK_NONE = dict(transparent_ok=1, n_ts_on=4, n_ua=4, n_pq_on=4, n_hr_on=4, n_lb_on=4, n_lb_off=0, knob_stall="", mrkey="hr")
REG_OK_KILL = dict(n_rel_dead=3, rel_after_dead_ms_r0=2400, rel_after_dead_ms_r1=2450, rel_after_dead_ms_r2=2500,
                   n_surv_edges=6, surv_tx_ok=6, n_kdone_surv=3, n_stuck_surv=0, killed=1, kill_in_traffic=1,
                   rx_untimed=1, n_ts_on=4, n_ua=4, n_pq_on=4, n_hr_on=4, n_lb_on=4, n_lb_off=0, knob_stall="", mrkey="hr")
REFUSE_WHY = {"mi4_refuse_csum": "NCCL_GIN_RESTORE_MIRROR_and_NCCL_GIN_RESTORE_CHECKSUM_are_both_on",
              "mi4_refuse_mirror1": "the_mirror_was_asked_but_the_setup_agreement_turned_it_off",
              "mi4_refuse_sl": "NCCL_GIN_RESTORE_MIRROR_SLOTS_or_NCCL_GIN_RESTORE_MIRROR_LANE_differs_between_ranks"}


def _build_A(d, *, bad_data=False, reg_bad=False, peer_bw2m=0.5):
    raw, reg, cost = os.path.join(d, "raw"), os.path.join(d, "reg"), os.path.join(d, "cost")
    _ow_kill3(raw, "mi4_kill3_ow", 10, surv=(dict(recv_bad=1) if bad_data else None))
    for k in range(1, 6):
        _mi(raw, "mi4_none_ow", k,
            mi_lines={r: [(1.0, "GIN/RS: rank %d: input pause for rank 0's checkpoint 20 ended (ok) pause_us=2300 mono_ms=1.0" % r),
                          (9.0, "GIN/MI: rank %d: mirror summary: switches=30 rollbacks=0 restarts=0 third_slot=0 max_live_bytes=9437184 pulls_sent=0 pulls_taken=0 broken=0 absorbed=0 mono_ms=1.0" % r)] for r in range(4)})
        _mi(raw, "mi4_kill1_ow", k, kill=1, spare=True, lib_lines={r: _mi_dead(r, 1) for r in (0, 2, 3)},
            mi_lines={r: _mi_good(r, 1) + _inj_from(r, 1) for r in (0, 2, 3)}, spare_lines={"spare": _spare_good(1)})
        ckmi = {r: _mi_dead(r, 3) + [(2.0012, "GIN/RS: rank %d: input pause for rank 3's checkpoint 120 ended (a hold of that rank took its gates) pause_us=900 mono_ms=1.0" % r),
                                     (0.51, "GIN/RS: rank %d: rank 3 armed at its stable checkpoint 100 mono_ms=1.0" % r)] for r in (0, 1, 2)}
        _mi(raw, "mi4_kill3_ckpt_ow", k, kill=3, spare=True, hook=(120, 300), lib_lines=ckmi,
            mi_lines={r: _mi_good(r, 3) + _inj_from(r, 3) for r in (0, 1, 2)}, spare_lines={"spare": _spare_good(3)})
        _mi(raw, "mi4_kill3_ow_nomirror", k, kill=3, spare=True, mirror="0", lib_lines={r: _mi_dead(r, 3) for r in (0, 1, 2)},
            surv=dict(recv_bad=1), poison=True)
        det = {r: [(3.0, "GIN/TS: rank %d: rank 3 judged dead (cause=FIN) mono_ms=1.0" % r),
                   (3.5, "GIN/RS: rank %d: the restore of rank 3 (incarnation 1) is given up (the log export failed: source buffer changed) in state HELD mono_ms=1.0" % r),
                   (5.8, "GINRS step rank=%d step=120 released=1 got=1 want=2" % r)] for r in (0, 1, 2)}
        _mi(raw, "mi4_kill3_ow_sampled", k, kill=3, spare=True, mirror="0", checksum="sampled",
            surv=dict(released=1, steps_done=120), lib_lines=det)
        for cell, img, seg in (("mi4_seg_4k", 31457280, 2457600), ("mi4_seg_32k", 31457280, 19660800),
                               ("mi4_seg_128k", 31457280, 78643200)):
            _mi(raw, cell, k, kill=3, spare=True, lib_lines={r: _mi_dead(r, 3) for r in (0, 1, 2)},
                mi_lines={r: _mi_good(r, 3) + _inj_from(r, 3) for r in (0, 1, 2)},
                spare_lines={"spare": _spare_good(3, fetch_us=5.0 + (img + seg) / 11880.0, image=img, seg=seg)})
        ov = {r: [(3.0, "GIN/TS: rank %d: rank 3 judged dead (cause=FIN) mono_ms=1.0" % r),
                  (3.1, "GIN/MI: rank %d: lane to rank 3 broken (full lane): DISARM mono_ms=1.0" % r),
                  (5.3, "GINRS step rank=%d step=120 released=1 got=1 want=2" % r)] for r in (0, 1, 2)}
        _mi(raw, "mi4_overflow", k, kill=3, spare=True, surv=dict(released=1, steps_done=120), lib_lines=ov)
        _mi(raw, "rs4_none_mion", k, overwrite=0)
        _mi(raw, "rs4_kill3_mion", k, kill=3, spare=True, overwrite=0, lib_lines={r: _mi_dead(r, 3) for r in (0, 1, 2)},
            mi_lines={r: _mi_good(r, 3) for r in (0, 1, 2)}, spare_lines={"spare": _spare_good(3)})
        _mi(raw, "mi4_pull", k, kill=3, spare=True, lib_lines={r: _mi_dead(r, 3) for r in (0, 1, 2)},
            mi_lines={r: _mi_good(r, 3) + _inj_from(r, 3) +
                      [(5.0, "GIN/MI: rank %d: CKPT_PULL to rank 3: seg=3 fill_pct=55 mono_ms=1.0" % r)] for r in (0, 1, 2)},
            spare_lines={"spare": _spare_good(3)})
        _kill2(raw, "mi4_kill2_kill3_ow", k)
        _kill2(raw, "mi4_train_kill2_kill3", k, train=1)
    for k in range(1, 4):
        for cell, live_b in (("mi4_int_10", 4718592), ("mi4_int_20", 9437184), ("mi4_int_40", 18874368)):
            _mi(raw, cell, k, mi_lines={r: [(9.0, "GIN/MI: rank %d: mirror summary: switches=10 rollbacks=0 restarts=0 third_slot=0 max_live_bytes=%d pulls_sent=0 pulls_taken=0 broken=0 absorbed=0 mono_ms=1.0" % (r, live_b))] for r in range(4)})
        _mi(raw, "mi4_pull_none", k,
            mi_lines={r: [(5.0, "GIN/MI: rank %d: CKPT_PULL to rank 0: seg=3 fill_pct=55 mono_ms=1.0" % r),
                          (9.0, "GIN/MI: rank %d: mirror summary: switches=30 rollbacks=0 restarts=0 third_slot=0 max_live_bytes=49152 pulls_sent=10 pulls_taken=10 broken=0 absorbed=0 mono_ms=1.0" % r)] for r in range(4)})
        for cell, why in REFUSE_WHY.items():
            _mi(raw, cell, k, live=False, mirror="1", checksum=("sampled" if cell == "mi4_refuse_csum" else "off"), refuse=why)
    for k in range(1, 6):
        _mi(raw, "mi4_train_none", k, train=1, overwrite=1, ring=4,
            mi_lines={r: [(1.0, "GIN/RS: rank %d: input pause for rank 0's checkpoint 20 ended (ok) pause_us=8000 mono_ms=1.0" % r),
                          (9.0, "GIN/MI: rank %d: mirror summary: switches=100 rollbacks=0 restarts=0 third_slot=1 max_live_bytes=251658240 pulls_sent=1 pulls_taken=1 broken=0 absorbed=0 mono_ms=1.0" % r)] for r in range(4)})
    for k in range(1, 11):
        img, seg = 31457280, 125829120
        _mi(raw, "mi4_train_kill3", k, train=1, overwrite=1, ring=4, kill=3, spare=True,
            lib_lines={r: _mi_dead(r, 3) for r in (0, 1, 2)}, mi_lines={r: _mi_good(r, 3) + _inj_from(r, 3) for r in (0, 1, 2)},
            spare_lines={"spare": _spare_good(3, fetch_us=5.0 + (img + seg) / 11880.0, image=img, seg=seg)})
    _rg_build(raw)
    for k in range(1, 6):
        _reg(reg, "reg_mr4_none", k, REG_OK_NONE)
        _reg(reg, "reg_mr4_none_hold", k, REG_OK_NONE)
        _reg(reg, "reg_rm4_kill3_untimed", k, dict(REG_OK_KILL, n_stuck_surv=(1 if reg_bad and k == 1 else 0)))
        _reg(reg, "reg_rm4_kill3_untimed_hold", k, REG_OK_KILL)
    lat = {"lat4k": (10.4, 10.5, 12.0, 12.0), "lat256k": (38.8, 38.9, 50.0, 60.0), "lat2m": (320.0, 330.0, 500.0, 650.0)}
    bw = {"bw256k": (6.5, 6.4, 5.0, 3.2), "bw2m": (6.1, 6.0, 4.8, 6.0 * peer_bw2m)}
    for node in ("rain", "sunny"):
        for k in range(6):
            for m, vs in list(lat.items()) + list(bw.items()):
                for a, v in zip(("off", "on", "mirror-self", "mirror-peer"), vs):
                    _cost(cost, m, a, node, k, round(v + 0.001 * k, 4))


def selftest():
    import tempfile
    global reg_columns
    real = reg_columns

    def _reg_cols(stem, r):
        return json.loads(rows_rs.read_meta(stem).get("selftest", "{}"))
    reg_columns = _reg_cols
    fails = []

    def expect(name, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (name, got, want))
    try:
        # A: the layer integrated, every prediction holds
        dA = tempfile.mkdtemp(prefix="mi_self_A_")
        _build_A(dA)
        vA = score(dA)
        preds = [p["id"] for p in csv.DictReader(open(PREDS))]
        for pid in preds:
            want = "보고만(판정 없음)" if pid == "cost_mirror_lat" else "맞음"
            expect("A/" + pid, vA.get(pid), want)
        # B: not integrated (no library lines, the Step hook not live): the kill cells and the library-column predictions
        # are 자료 부족; the refusals still read
        dB = tempfile.mkdtemp(prefix="mi_self_B_")
        raw = os.path.join(dB, "raw")
        for k in range(1, 11):
            _mi(raw, "mi4_kill3_ow", k, kill=3, spare=True, live=False, surv=dict(released=1, steps_done=100))
            _mi(raw, "mi4_train_kill3", k, kill=3, spare=True, live=False, train=1, ring=4, surv=dict(released=1, steps_done=100))
        for k in range(1, 4):
            for cell, why in REFUSE_WHY.items():
                _mi(raw, cell, k, live=False, mirror="1", checksum=("sampled" if cell == "mi4_refuse_csum" else "off"), refuse=why)
            for cell in ("mi4_int_10", "mi4_int_20", "mi4_int_40"):
                _mi(raw, cell, k)
        vB = score(dB)
        for pid in ("ow_wait_held", "ow_data_equal", "ow_from_pool", "ow_restore_time", "seg_restore_slope",
                    "train_data_equal", "train_paced_import", "pool_vs_interval", "cost_mirror_lat4k", "cost_mirror_bw"):
            expect("B/" + pid, vB.get(pid), "자료 부족")
        for pid in ("refuse_csum", "refuse_mirror1", "refuse_sl"):
            expect("B/" + pid, vB.get(pid), "맞음")
        # C: failures are 틀림
        dC = tempfile.mkdtemp(prefix="mi_self_C_")
        _build_A(dC, bad_data=True, reg_bad=True, peer_bw2m=0.3)
        vC = score(dC)
        expect("C/ow_data_equal", vC.get("ow_data_equal"), "틀림")
        expect("C/regression_kill3_off", vC.get("regression_kill3_off"), "틀림")
        expect("C/cost_mirror_bw", vC.get("cost_mirror_bw"), "틀림")
        expect("C/cost_mirror_lat4k (unchanged)", vC.get("cost_mirror_lat4k"), "맞음")
        # D: the parser's and the status rules
        dD = tempfile.mkdtemp(prefix="mi_self_D_")
        raw = os.path.join(dD, "raw")
        cells = load_cells()
        EXPECT_DRIVER.clear()
        EXPECT_DRIVER.update(expected_drivers(cells))
        _ow_kill3(raw, "mi4_kill3_ow", 1)
        _mi(raw, "mi4_kill3_ow", 2, kill=3, spare=True, overwrite=0, lib_lines={r: _mi_dead(r, 3) for r in (0, 1, 2)})
        _mi(raw, "mi4_kill3_ow", 3, kill=3, spare=True, mirror="0", lib_lines={r: _mi_dead(r, 3) for r in (0, 1, 2)})
        _mi(raw, "mi4_kill3_ow", 4, kill=3, spare=True, refuse="x", lib_lines={r: _mi_dead(r, 3) for r in (0, 1, 2)})
        _kill2(raw, "mi4_kill2_kill3_ow", 1)
        _kill2(raw, "mi4_kill2_kill3_ow", 2, spare2_fail=True)
        _kill2(raw, "mi4_kill2_kill3_ow", 3, rearm=False)
        _mi(raw, "mi4_kill3_ow_nomirror", 1, kill=3, spare=True, mirror="0",
            lib_lines={r: _mi_dead(r, 3) for r in (0, 1, 2)}, surv=dict(recv_bad=1), poison=True)
        cdir = os.path.join(dD, "cost_x")
        _cost(cdir, "bw2m", "on", "rain", 1, 6.0)
        _cost(cdir, "bw2m", "mirror-peer", "rain", 2, 3.0, summary=False)
        _cost(cdir, "bw2m", "mirror-peer", "rain", 3, 3.0, summary_broken=4)
        rows = {r["id"]: r for r in rows_mi.all_rows(dD)}
        k3 = rows["mi4_kill3_ow_mi_n1"]
        expect("D/ow_data_equal clean", k3["ow_data_equal"], 1)
        expect("D/from_pool_ok (keys in any order)", k3["from_pool_ok"], 1)
        expect("D/export_source_bytes 0", k3["export_source_bytes"], 0)
        expect("D/no tcp bytes", (k3["tcp_image_bytes"], k3["tcp_segment_bytes"]), (0, 0))
        expect("D/fetch bytes", k3["fetch_bytes"], 31457280 + 125829120)
        expect("D/paced import", k3["paced_ok"], 1)
        expect("D/inj survivors", k3["inj_from_n"], 3)
        expect("D/workload mismatch excluded", status_rs(rows["mi4_kill3_ow_mi_n2"], cells), "workload")
        expect("D/mirror setting mismatch excluded", status_rs(rows["mi4_kill3_ow_mi_n3"], cells), "workload")
        expect("D/refused Resume excluded", status_rs(rows["mi4_kill3_ow_mi_n4"], cells), "config")
        k2 = rows["mi4_kill2_kill3_ow_mi_n1"]
        expect("D/kill2 columns", (k2["applied2"], k2["restore_time_ms_1"], k2["restore_time_ms_2"], k2["restored_subjects"],
                                   k2["stored_after"], k2["void_between"], k2["rearm_ok"], k2["fetch2_from_buddy"],
                                   k2["reimage_ok"], k2["second_ok"], k2["wait_held"]),
               (1, 300.0, 300.0, 2, 1, 1, 1, 1, 1, 1, 1))
        expect("D/second spare start failure excluded", status_rs(rows["mi4_kill2_kill3_ow_mi_n2"], cells), "spare_start_fail")
        expect("D/no re-arm before the second kill", rows["mi4_kill2_kill3_ow_mi_n3"]["reimage_ok"], 0)
        expect("D/nomirror corrupt", rows["mi4_kill3_ow_nomirror_mi_n1"]["nomirror_corrupt"], 1)
        expect("D/bw2m value in GB/s", round(float(rows["cost_bw2m_on_rain_k1"]["value"]), 3), 6.0)
        expect("D/mirror arm without a summary is invalid", rows["cost_bw2m_mirror-peer_rain_k2"]["cost_valid"], 0)
        expect("D/mirror arm with breaks is invalid", rows["cost_bw2m_mirror-peer_rain_k3"]["cost_valid"], 0)
        expect("D/on arm valid", rows["cost_bw2m_on_rain_k1"]["cost_valid"], 1)
        for rule, ok in (("within:10", True), ("within_us:2.5", True), ("ratio:0.4-0.6", True), ("report", True),
                         ("not_separated", True), ("ratio:0.4", False), ("bogus", False)):
            try:
                parse_rule(rule)
                good = True
            except ValueError:
                good = False
            if good != ok:
                fails.append("D/parse_rule(%r) %s" % (rule, "accepted" if good else "refused"))
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
