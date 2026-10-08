#!/usr/bin/env python3
"""gin-pair-reset scorer: applies the frozen acceptance rules of predictions.csv to the main run and writes
<resultsdir>/SCORE.md and <resultsdir>/trials_scored.csv.

usage: score.py <resultsdir>          (e.g. results/20261008)

Steps (EXPERIMENT.md 3 and 8):
  1. every hold subdirectory with *_meta.txt files -> ../scripts/ts2/rows.py -> trials_<sub>.csv;
  2. ../s2_close/rows_extra.extra() and rows_pr.extra_pr() add the section 3.1 columns from the per-trial files;
  3. each trial gets its cell key cell@build and a status: scored, excluded (bind failure, fault not applied, trigger
     missed, no kill, condition not met), config (a configuration check failed), or surplus (non-excluded trials beyond
     the planned count; the first ones by trial number are scored);
  4. every prediction is evaluated on the scored trials with the grammar of ../s2_close/EXPERIMENT.md 3.2, using the
     evaluation functions of ../s2_close/score.py unchanged; a prediction whose cells have fewer scored trials than
     planned is "자료 부족".
"""
import csv, glob, hashlib, importlib.util, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
S2C = os.path.join(HERE, "..", "s2_close")
ROWS = os.path.join(HERE, "..", "scripts", "ts2", "rows.py")
_spec = importlib.util.spec_from_file_location("s2close_score", os.path.join(S2C, "score.py"))
s2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s2)  # grammar: evaluate, val, NIL ... (also puts ../s2_close on sys.path for rows_extra)
from rows_extra import extra  # noqa: E402  (../s2_close/rows_extra.py)
sys.path.insert(0, HERE)
from rows_pr import extra_pr  # noqa: E402

# section 7: planned scored trials per cell key (latency cells: runs)
PLANNED = {"pr_dual_f1c0_b@prd": 10, "pr_dual_f3c0_b@prd": 10, "pr_dual_f1all_b@prd": 10, "pr_bidirf_conflict_b@pr": 10,
           "pr_dual_f1c0_full_b@prd": 5, "pr_dual_none_b@prd": 5,
           "f1_b@pr": 5, "f3_b@pr": 5, "bidirf_sym_b@pr": 5, "mt256_f1_b@pr": 5, "f4_b@pr": 5, "f2rel_b@pr": 5,
           "lat_rc_on_4k@rc": 5, "lat_rc_on_256k@rc": 5, "lat_pr_on_4k@pr": 5, "lat_pr_on_256k@pr": 5}
WINDOW_CELLS = {"pr_dual_f1c0_b", "pr_dual_f1c0_full_b", "pr_dual_f3c0_b"}  # section 8: context 1 must outlast the window
STALL_CELLS = {"pr_bidirf_conflict_b"}                                       # section 8: rank 1's record inside the stall
PR_OFF_CELLS = {"pr_dual_f1c0_full_b"}
# section 8: the hook's context per cell and rank ("" = every context; None = not checked)
INJ_CTX = {"pr_dual_f1c0_b": ("0", None), "pr_dual_f1c0_full_b": ("0", None), "pr_dual_f3c0_b": (None, "0"),
           "pr_bidirf_conflict_b": ("0", "1"), "pr_dual_f1all_b": ("", None)}

LABEL = {
    "P1a": "두 문맥에 트래픽이 있을 때 문맥 0의 로컬 QP 오류가 투명하게 복구됨",
    "P1b": "라운드가 한 번이고 두 rank 모두 문맥 0 하나로 좁혀짐",
    "P1c": "문맥 1 게이트는 두 rank에서 그대로, 문맥 0은 한 번 공개",
    "P1d": "문맥 0이 묶인 동안 문맥 1이 계속 돌고 1 ms를 넘는 반복이 없음",
    "P2a": "문맥 0 쌍의 상대 QP 오류가 투명하게 복구됨",
    "P2b": "재시도 초과 라운드도 두 rank에서 문맥 0으로 좁혀지고 문맥 1 게이트는 그대로",
    "P2c": "재시도 기다림과 라운드 동안 문맥 1이 계속 돌고 1 ms를 넘는 반복이 없음",
    "T1": "시작 쪽 Commit 중앙값이 같은 hold의 전체 재설정의 절반 이하",
    "T2": "시작 쪽 라운드 전체 중앙값이 같은 hold의 전체 재설정의 0.6 이하",
    "B1a": "rank 0의 모든 문맥 QP가 고장 나도 두 문맥 모두 투명하게 복구됨",
    "B1b": "모든 문맥 고장은 전체 재설정 한 번으로 돌아감",
    "B2a": "두 rank가 다른 범위로 동시에 시작해도 둘 다 복구되고 거절이 없음",
    "B2b": "높은 rank가 충돌을 한 번 보고, 문맥 0 라운드에 응답한 뒤 자기 장애를 전체 재설정으로 돔",
    "C1a": "스위치를 끄면 전체 재설정(QP 4개씩)이고 투명함(대조)",
    "C1b": "전체 재설정에서는 문맥 1도 묶여 1 ms 이상인 반복이 나옴(대조)",
    "C2": "장애 없는 두 문맥 모드는 투명하고 라운드가 없으며 문맥 1의 최장 반복이 1 ms 이하(대조)",
    "G1": "주요 복구 셀 네 개가 그대로 투명",
    "G2": "기존 훅이 그 rank의 QP를 모두 고장 내는 셀은 두 rank 모두 전체 재설정",
    "G3": "기존 상대 QP 오류 셀이 문맥 0으로 좁혀짐",
    "G4": "끊김 없는 kill은 죽음 원인으로 거절되고 abort가 돌아옴",
    "G5": "받는 쪽 abort 해제가 그대로",
    "L1": "4 KiB 지연 차이 0.40 µs 이하(대조)",
    "L2": "256 KiB 지연 차이 0.30 µs 이하(대조)",
}
EXCL_LABEL = {"bind": "드라이버 랑데부 포트 충돌", "no_fault": "장애 미적용(훅 발화 없음)", "trigger_miss": "트리거 미도달",
              "no_kill": "kill 기록 없음", "cond_window": "조건 미적용(문맥 1이 묶인 창보다 먼저 끝남)",
              "cond_stall": "조건 미적용(rank 1의 장애가 rank 0의 멈춤 안에 오지 않음)",
              "config_ts_off": "설정 확인 실패: 투명 복구 시작 줄 없음", "config_no_ua": "설정 확인 실패: abort 플래그 줄 없음",
              "config_pr_mode": "설정 확인 실패: 범위 스위치 줄이 셀과 다름", "config_dual": "설정 확인 실패: 두 문맥 모드 아님",
              "config_inj_ctx": "설정 확인 실패: 훅의 문맥 지정이 셀과 다름", "surplus": "계획 수를 넘은 시행"}


def status_of(r):
    val = s2.val
    f = r.get("fault")
    if r.get("bind_fail") == "1":
        return "bind"
    if f in ("F1", "F1both") and val(r.get("n_fires_r0")) == 0:
        return "no_fault"
    if f in ("F3", "F1both") and val(r.get("n_fires_r1")) == 0:
        return "no_fault"
    tm = val(r.get("trigger_miss"))
    if isinstance(tm, float) and tm > 0:
        return "trigger_miss"
    if f == "F4" and str(r.get("killed")) != "1":
        return "no_kill"
    if r["cell"] in WINDOW_CELLS and str(r.get("dual_c1_end_after_win")) != "1":
        return "cond_window"
    if r["cell"] in STALL_CELLS and str(r.get("r1_q4_in_stall")) != "1":
        return "cond_stall"
    if r.get("ts") == "1":
        if not (val(r.get("ts_on_r0")) >= 1 and val(r.get("ts_on_r1")) >= 1):
            return "config_ts_off"
        if not (val(r.get("ua_r0")) >= 1 and val(r.get("ua_r1")) >= 1):
            return "config_no_ua"
    if r["build"] in ("pr", "prd"):
        want = "0" if r["cell"] in PR_OFF_CELLS else "1"
        if r.get("pr_mode_r0") != want or r.get("pr_mode_r1") != want:
            return "config_pr_mode"
    if r["build"] == "prd" and not (r.get("dual_r0") == "1" and r.get("dual_r1") == "1"):
        return "config_dual"
    if r["cell"] in INJ_CTX:
        w0, w1 = INJ_CTX[r["cell"]]
        if (w0 is not None and str(r.get("inj_ctx_r0")) != w0) or (w1 is not None and str(r.get("inj_ctx_r1")) != w1):
            return "config_inj_ctx"
    return "candidate"


def main():
    R = os.path.abspath(sys.argv[1])
    subs = sorted(d for d in os.listdir(R) if os.path.isdir(os.path.join(R, d)) and glob.glob(os.path.join(R, d, "*_meta.txt")))
    trials = []
    for sub in subs:
        out = os.path.join(R, f"trials_{sub}.csv")
        subprocess.run([sys.executable, ROWS, os.path.join(R, sub), "--out", out], check=True, stderr=subprocess.DEVNULL)
        for r in csv.DictReader(open(out)):
            stem = os.path.join(R, sub, r["stem"])
            r.update({k: ("" if v is None else v) for k, v in extra(r, stem).items()})
            r.update({k: ("" if v is None else v) for k, v in extra_pr(stem).items()})
            r["sub"] = sub
            r["key"] = f'{r["cell"]}@{r["build"]}'
            m = re.search(r"n(\d+)$", r.get("trial") or "")
            r["tnum"] = int(m.group(1)) if m else 0
            trials.append(r)
    for r in trials:
        r["status"] = status_of(r)
    by_key = {}
    for r in sorted(trials, key=lambda x: (x["key"], x["tnum"], x["sub"])):
        by_key.setdefault(r["key"], []).append(r)
    scored = {}
    for k, rs in by_key.items():
        cand = [r for r in rs if r["status"] == "candidate"]
        for i, r in enumerate(cand):
            r["status"] = "scored" if i < PLANNED.get(k, 0) else "surplus"
        scored[k] = [r for r in rs if r["status"] == "scored"]
    preds = list(csv.DictReader(open(os.path.join(HERE, "predictions.csv"))))
    sha = hashlib.sha256(open(os.path.join(HERE, "predictions.csv"), "rb").read()).hexdigest()
    frozen = open(os.path.join(HERE, "PREREG.txt")).read()
    results = []
    for p in preds:
        acc = p["acceptance"]
        keys = s2.keys_of(p["cells"])
        per_cell = acc.startswith("per cell:")
        a = acc[len("per cell:"):].strip() if per_cell else acc
        short = [k for k in keys if len(scored.get(k, [])) < PLANNED.get(k, 0)]
        evals = [(k,) + s2.evaluate(a, scored, k, s2.NIL) for k in (keys if per_cell else keys[:1])]
        ok = all(e[1] for e in evals)
        results.append((p, keys, evals, "자료 부족" if short else ("맞음" if ok else "틀림"), short))
    cols = ["key", "status", "sub", "stem", "cell", "build", "trial"]
    for r in trials:
        for c in r:
            if c not in cols:
                cols.append(c)
    with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(trials, key=lambda x: (x["sub"], x["key"], x["tnum"])):
            w.writerow(r)
    L = ["# gin-pair-reset 채점 결과", "",
         f"`score.py`가 원자료(`{os.path.relpath(R, HERE)}/`의 hold별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.", "",
         f"- 예측 파일 sha256: `{sha}`. `PREREG.txt`의 값과 {'같다' if sha in frozen else '다르다(확인 필요)'}.",
         f"- 시행 수(모든 hold): {len(trials)}. 판정한 시행: {sum(len(v) for v in scored.values())}.",
         "- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.", "",
         "## 판정 요약", "", "| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |", "|---|---|--:|---|---|"]
    for p, keys, evals, verdict, short in results:
        ns = " / ".join(str(len(scored.get(k, []))) for k in keys)
        hits = "; ".join(", ".join(f"{c}/{n}" for (_, c, n, _, _, _) in det) if det else expr for (_, _, det, expr) in evals)
        cells = ", ".join(f"`{k}`" for k in keys)
        L.append(f"| {LABEL[p['id']]} ({p['id']}) | {cells} | {ns} | {hits} | {verdict} |")
    L += ["", "## 예측별 세부", ""]
    for p, keys, evals, verdict, short in results:
        L += [f"### {LABEL[p['id']]} ({p['id']}): {verdict}", "", f"- 판정식: `{p['acceptance']}`"]
        if short:
            L.append(f"- 계획 수에 못 미친 셀: {', '.join(short)}")
        for k, ok, det, expr in evals:
            L.append(f"- 셀 `{k}`: 판정한 시행 {len(scored.get(k, []))}회, 대입한 식 `{expr}` → {'참' if ok else '거짓'}")
            for inner, c, n, fs, ts, tail in det:
                upper = bool(re.match(r"\s*(<=|<)", tail)) or bool(re.match(r"\s*==\s*0\b", tail))
                miss = ts if upper else fs
                what = "조건을 만족한(예측과 반대인) 시행" if upper else "조건을 만족하지 않은 시행"
                L.append(f"  - `count({inner})` = {c}/{n}. {what}: {', '.join(miss) if miss else '없음'}")
        L.append("")
    L += ["## 셀별 시행 수와 따로 센 시행", "", "| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |", "|---|--:|--:|--:|---|"]
    for k in sorted(set(list(by_key.keys()) + list(PLANNED.keys()))):
        rs = by_key.get(k, [])
        apart = {}
        for r in rs:
            if r["status"] != "scored":
                apart.setdefault(r["status"], []).append(r["stem"])
        txt = "; ".join(f"{EXCL_LABEL.get(s, s)}: {', '.join(v)}" for s, v in sorted(apart.items())) or "없음"
        L.append(f"| `{k}` | {PLANNED.get(k, 0)} | {len(rs)} | {len(scored.get(k, []))} | {txt} |")
    L.append("")
    open(os.path.join(R, "SCORE.md"), "w").write("\n".join(L))
    print("\n".join(f"{p['id']}: {v}" for p, _, _, v, _ in results))


if __name__ == "__main__":
    main()
