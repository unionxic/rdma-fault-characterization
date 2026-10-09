#!/usr/bin/env python3
"""gpu-detect scorer: applies the acceptance rules of predictions.csv to a results folder and writes
<resultsdir>/SCORE.md and <resultsdir>/trials_scored.csv. The pilot (its own results folder) is never scored; the same
script may be run on a copy of it to read the columns.

usage: score.py <resultsdir>          (e.g. results/<date>)

Steps (EXPERIMENT.md 3 and 8):
  1. app trials (raw/<id>/): rows_gd.all_rows(); status scored when valid (rows_gd.py), else the exclusion reason.
  2. regression trials (reg/hw/, two ranks): gin-remaining's columns, made by its own code unchanged
     (../gpu-initiated/gin_recovery/remaining/score.py imports: ../scripts/ts2/rows.py, rows_extra, rows_pc, rows_ow,
     rows_hd, rows_hf, rows_pq.extra_pq2, rows_hr.extra_hr2), then rows_gd.extra_gd2(); status: gin-remaining's status2
     with the build checked as hr (hw carries every hr start line) plus the hw start line with the cell's qpwatch_ms.
     reg/mr_hw/ (four ranks): rows_mr.rows_of, rows_pq.extra_pq4, rows_hr.extra_hr4, rows_gd.extra_gd4; status:
     gin-remaining's status4 (as hr) for its cells, status4_new() for this study's two new cells.
  3. per cell key (cell@build), the first PLANNED scored trials in trial order are scored, later ones are surplus.
     Excluded trials are not refilled. A prediction is "자료 부족" when a cell it names has fewer scored trials than
     ceil(0.75 x planned).
  4. every prediction is evaluated with the grammar of ../gpu-initiated/gin_recovery/s2_close/EXPERIMENT.md 3.2 (its
     score.py functions, unchanged); N_SCORED in an acceptance outside count() is the cell's number of scored trials.
"""
import csv, glob, hashlib, importlib.util, json, math, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REMD = os.path.join(HERE, "..", "gpu-initiated", "gin_recovery", "remaining")
_spec = importlib.util.spec_from_file_location("grm_score", os.path.join(REMD, "score.py"))
rem = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rem)  # gin-remaining's scorer as a library: its row code, status2/status4 and the grammar (rem.s2)
s2 = rem.s2
sys.path.insert(0, HERE)
import rows_gd  # noqa: E402

CELLS = json.load(open(os.path.join(HERE, "cells.json")))
PLANNED = {}
for h, cl in CELLS["holds"].items():
    if h.startswith("P"):
        continue  # pilot holds are never scored
    for c in cl:
        k = "%s@%s" % (c["cell"], c["build"])
        PLANNED[k] = PLANNED.get(k, 0) + c["n"]
for c in ("f1_b", "f3_b", "bidirf_sym_b", "f4_b", "f2rel_b", "hd_rxdeath_b"):
    PLANNED[c + "@hw"] = 5
for sz in ("4k", "256k"):
    for w in (0, 1, 10, 100):
        PLANNED["lat_%s_w%d@hw" % (sz, w)] = 5
for c in ("mr4_none", "mr4_f1_01", "rm4_kill3_untimed", "mr4_cyc_stall", "mr4_twolow_stall"):
    PLANNED[c + "@hw"] = 5
PLANNED["rm4_late01@hw"] = 3
PLANNED["rm4_late01_rounds@hw"] = 3
OLD4 = {"mr4_none", "mr4_f1_01", "rm4_kill3_untimed", "mr4_cyc_stall"}
FIRES_NEW = {"mr4_twolow_stall": "0:2;1:5;2:7;3:11", "rm4_late01": "0:0", "rm4_late01_rounds": "0:0"}
STALL_NEW = {"mr4_twolow_stall": "0:300;1:300;2:300;3:300", "rm4_late01": "", "rm4_late01_rounds": ""}
LABEL = {}
EXCL = {"not_applied": "장애 미적용", "void": "시작 실패", "config": "설정 확인 실패(블록을 멈춤)", "surplus": "계획 수를 넘은 시행",
        "config_detect": "설정 확인 실패: hw 시작 줄(detect=1, 셀의 qpwatch_ms) 없음"}
EXCL.update(getattr(rem, "EXCL_LABEL", {}))


def watch_of(cell):
    m = re.match(r"lat_\w+_w(\d+)$", cell)
    return m.group(1) if m else "10"


def status_app(r):
    if not r["applied"]:
        return "not_applied"
    if r["void"]:
        return "void"
    if not r["config_ok"]:
        return "config"
    return "candidate"


def status2(r):
    st = rem.status2(dict(r, build="hr"))  # hw carries every start line of hr; drivers are hr's (DRVKEY=hr)
    if st != "candidate":
        return st
    cell = r["cell"]
    ranks = (0,) if cell in rem.KILL_R1 else (1,) if cell in rem.KILL_R0 else (0, 1)
    if not all(int(r.get("det_on_r%d" % k) or 0) >= 1 for k in ranks) or str(r.get("det_ms_cfg")) != watch_of(cell):
        return "config_detect"
    return "candidate"


def status4_new(r):
    cell, n = r["cell"], int(r.get("n") or 0)
    if str(r.get("bind_fail")) == "1":
        return "bind"
    if r.get("fires") != FIRES_NEW[cell] or str(r.get("fire_in_traffic")) != "1":
        return "no_fault"
    if cell.startswith("rm4_late01") and not (str(r.get("killed")) == "1" and str(r.get("kill_in_traffic")) == "1"):
        return "no_kill4"
    if cell == "mr4_twolow_stall":
        sp = rem.num(r.get("cyc_spread_ms"))
        if sp is None or sp > 250:
            return "cond_order"
    if ((rem.num(r.get("n_fwover")) or 0) + (rem.num(r.get("n_fwold")) or 0) + (rem.num(r.get("n_fw_over")) or 0)) > 0:
        return "fw_overrun"
    if str(r.get("init_fail")) == "1":
        return "candidate"
    if str(r.get("mrkey")) != "hr":
        return "config_driver"
    if not (rem.num(r.get("n_ts_on")) or 0) >= n or not (rem.num(r.get("n_ua")) or 0) >= n:
        return "config_ts_off"
    if not ((rem.num(r.get("n_pq_on")) or 0) == n and (rem.num(r.get("n_hr_on")) or 0) == n):
        return "config_build"
    if not ((rem.num(r.get("n_lb_on")) or 0) >= n and (rem.num(r.get("n_lb_off")) or 0) == 0):
        return "config_copy"
    if str(r.get("knob_stall") or "") != STALL_NEW[cell]:
        return "config_knobs"
    return "candidate"


def status4(r):
    if r["cell"] in OLD4:
        st = rem.status4(dict(r, build="hr"))
    else:
        st = status4_new(r)
    if st == "candidate" and (rem.num(r.get("n_det_on")) or 0) < int(r.get("n") or 0):
        return "config_detect"
    return st


def reg_rows(R):
    out = []
    sub = os.path.join(R, "reg", "hw")
    if glob.glob(os.path.join(sub, "*_meta.txt")):
        csvp = os.path.join(R, "trials_reg_hw.csv")
        subprocess.run([sys.executable, rem.ROWS, sub, "--out", csvp], check=True, stderr=subprocess.DEVNULL)
        for r in csv.DictReader(open(csvp)):
            stem = os.path.join(sub, r["stem"])
            for fn in (lambda: rem.extra(r, stem), lambda: rem.extra_pc(stem), lambda: rem.extra_ow(stem),
                       lambda: rem.extra_hd(stem, r.get("fault_mono_r0")), lambda: rem.extra_hf(stem),
                       lambda: rem.extra_pq2(stem), lambda: rem.extra_hr2(stem), lambda: rows_gd.extra_gd2(stem)):
                r.update({k: ("" if v is None else v) for k, v in fn().items()})
            r["sub"], r["kind"] = "reg/hw", "2"
            out.append(r)
    sub = os.path.join(R, "reg", "mr_hw")
    for meta in sorted(glob.glob(os.path.join(sub, "*_meta.txt"))):
        stem = meta[: -len("_meta.txt")]
        r = {k: ("" if v is None else v) for k, v in rem.rows_of(stem).items()}
        r.update({k: ("" if v is None else v) for k, v in rem.extra_pq4(stem, r).items()})
        r.update({k: ("" if v is None else v) for k, v in rem.extra_hr4(stem, r).items()})
        r.update({k: ("" if v is None else v) for k, v in rows_gd.extra_gd4(stem, int(r.get("n") or 4)).items()})
        r["build"] = r.get("lib", "")
        r["sub"], r["kind"] = "reg/mr_hw", "4"
        out.append(r)
    for r in out:
        m = re.search(r"n(\d+)$", r.get("trial") or "")
        r["tnum"] = int(m.group(1)) if m else 0
        r["key"] = "%s@%s" % (r["cell"], r["build"])
        r["status"] = status4(r) if r["kind"] == "4" else status2(r)
    return out


def evaluate(p, scored):
    acc = p["acceptance"]
    keys = s2.keys_of(p["cells"])
    per_cell = acc.startswith("per cell:")
    a = acc[len("per cell:"):].strip() if per_cell else acc
    short = [k for k in keys if len(scored.get(k, [])) < math.ceil(0.75 * PLANNED.get(k, 0)) or PLANNED.get(k, 0) == 0]
    evals = []
    for k in (keys if per_cell else keys[:1]):
        ak = re.sub(r"\bN_SCORED\b", str(len(scored.get(k, []))), a)
        evals.append((k,) + s2.evaluate(ak, scored, k, s2.NIL))
    ok = all(e[1] for e in evals)
    return keys, evals, ("자료 부족" if short else ("맞음" if ok else "틀림")), short


def main():
    R = os.path.abspath(sys.argv[1])
    app = rows_gd.all_rows(R)
    for r in app:
        r["stem"], r["sub"], r["kind"] = r["id"], "raw", "a"
        m = re.search(r"\.n(\d+)$", r["id"])
        r["tnum"] = int(m.group(1)) if m else 0
        r["status"] = status_app(r)
    trials = app + reg_rows(R)
    cols = []
    for r in trials:
        for c in r:
            if c not in cols:
                cols.append(c)
    for r in trials:  # every row has every column (an absent one is empty: the 3.2 rule)
        for c in cols:
            r.setdefault(c, "")
    by_key, scored = {}, {}
    for r in sorted(trials, key=lambda x: (x["key"], x["tnum"], x["sub"])):
        by_key.setdefault(r["key"], []).append(r)
    for k, rs in by_key.items():
        cand = [r for r in rs if r["status"] == "candidate"]
        for i, r in enumerate(cand):
            r["status"] = "scored" if i < PLANNED.get(k, 0) else "surplus"
        scored[k] = [r for r in rs if r["status"] == "scored"]
    preds = list(csv.DictReader(open(os.path.join(HERE, "predictions.csv"))))
    sha = hashlib.sha256(open(os.path.join(HERE, "predictions.csv"), "rb").read()).hexdigest()
    frozen = open(os.path.join(HERE, "PREREG.txt")).read() if os.path.exists(os.path.join(HERE, "PREREG.txt")) else ""
    results = [(p,) + evaluate(p, scored) for p in preds]
    lead = ["key", "status", "kind", "sub", "stem", "cell", "build"]
    with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=lead + [c for c in cols if c not in lead], extrasaction="ignore")
        w.writeheader()
        for r in sorted(trials, key=lambda x: (x["sub"], x["key"], x["tnum"])):
            w.writerow(r)
    L = ["# gpu-detect 채점 결과", "",
         "`score.py`가 원자료(`%s/`의 시행 파일)에서 만들었다. 손으로 고친 값은 없다." % os.path.relpath(R, HERE), "",
         "- 예측 파일 sha256: `%s`. `PREREG.txt`의 값과 %s." % (sha, "같다" if sha in frozen else "다르다(확인 필요)"),
         "- 시행 수(모든 hold): %d. 판정한 시행: %d." % (len(trials), sum(len(v) for v in scored.values())),
         "- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.", "",
         "## 판정 요약", "", "| 예측 | 셀 | n | 판정 |", "|---|---|--:|---|"]
    for p, keys, evals, verdict, short in results:
        ns = " / ".join(str(len(scored.get(k, []))) for k in keys)
        L.append("| %s (%s) | %s | %s | %s |" % (p["predicted"], p["id"], ", ".join("`%s`" % k for k in keys), ns, verdict))
    L += ["", "## 예측별 세부", ""]
    for p, keys, evals, verdict, short in results:
        L += ["### %s: %s" % (p["id"], verdict), "", "- 판정식: `%s`" % p["acceptance"]]
        if short:
            L.append("- 계획의 75%%에 못 미친 셀: %s" % ", ".join(short))
        for k, ok, det, expr in evals:
            L.append("- 셀 `%s`: 판정한 시행 %d회, 대입한 식 `%s` → %s" % (k, len(scored.get(k, [])), expr, "참" if ok else "거짓"))
            for inner, c, n, fs, ts, tail in det:
                L.append("  - `count(%s)` = %d/%d. 조건을 만족하지 않은 시행: %s" % (inner, c, n, ", ".join(fs) if fs else "없음"))
        L.append("")
    L += ["## 셀별 시행 수와 따로 센 시행", "", "| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |", "|---|--:|--:|--:|---|"]
    for k in sorted(set(list(by_key) + list(PLANNED))):
        rs = by_key.get(k, [])
        apart = {}
        for r in rs:
            if r["status"] != "scored":
                apart.setdefault(r["status"], []).append(r["stem"])
        txt = "; ".join("%s: %s" % (EXCL.get(s, s), ", ".join(v)) for s, v in sorted(apart.items())) or "없음"
        L.append("| `%s` | %d | %d | %d | %s |" % (k, PLANNED.get(k, 0), len(rs), len(scored.get(k, [])), txt))
    L.append("")
    open(os.path.join(R, "SCORE.md"), "w").write("\n".join(L))
    print("\n".join("%s: %s" % (p["id"], v) for p, _, _, v, _ in results))


if __name__ == "__main__":
    main()
