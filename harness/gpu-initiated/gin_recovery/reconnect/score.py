#!/usr/bin/env python3
"""gin-reconnect scorer: applies the frozen acceptance rules of predictions.csv to the main run and writes
<resultsdir>/SCORE.md and <resultsdir>/trials_scored.csv.

usage: score.py <resultsdir>          (e.g. results/20261008)

Steps (EXPERIMENT.md 3 and 8):
  1. every hold subdirectory with *_meta.txt files -> ../scripts/ts2/rows.py -> trials_<sub>.csv;
  2. ../s2_close/rows_extra.extra() and rows_rc.extra_rc() add the section 3.1 columns from the per-trial files;
  3. each trial gets its cell key cell@build and a status: scored, excluded (bind failure, fault not applied, trigger
     missed, no kill, order not met), config (a configuration check failed), or surplus (non-excluded trials beyond the
     planned count; the first ones by trial number are scored);
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
from rows_rc import extra_rc  # noqa: E402

# section 7: planned scored trials per cell key (latency cells: runs)
PLANNED = {"rc_mute8_f1_b@rc": 10, "rc_mutef3s_b@rc": 10, "rc_mutef3l_b@rc": 10, "rc_mutekill_b@rc": 10,
           "f1_b@rc": 5, "f3_b@rc": 5, "f1g0_b@rc": 5, "mt256_f1_b@rc": 5, "bidirf_f1both_b@rc": 5,
           "bidirf_sym_b@rc": 5, "f4_b@rc": 5, "f2rel_b@rc": 5, "rc_mute1_f1_b@rc": 5, "rc_mute8off_b@rc": 5,
           "lat_s2r_on_4k@s2r": 5, "lat_s2r_on_256k@s2r": 5, "lat_rc_on_4k@rc": 5, "lat_rc_on_256k@rc": 5}
MUTE_CELLS = {"rc_mute8_f1_b", "rc_mutef3s_b", "rc_mutef3l_b", "rc_mutekill_b", "rc_mute1_f1_b", "rc_mute8off_b"}
ORDER_CELLS = {"rc_mutef3s_b", "rc_mutef3l_b", "rc_mutekill_b"}
RC_OFF_CELLS = {"rc_mute8off_b"}

LABEL = {
    "M1a": "8 s 끊김 뒤 로컬 QP 오류가 투명하게 복구됨",
    "M1b": "소켓이 시간 초과로 닫히고 '모름'으로 분류됨",
    "M1c": "끊김이 끝난 뒤 1.5 s 안에 다시 연결됨",
    "M1d": "끊김과 재연결이 장애 전까지 앱에 알려지지 않음",
    "M2a": "상한 안에 끝나는 끊김 중 상대 QP 오류가 투명하게 복구됨",
    "M2b": "시작 쪽이 재연결을 기다렸고 기다림이 재연결로 끝남",
    "M3a": "상한을 넘는 끊김 중 상대 QP 오류가 '상대 생존 모름'으로 거절됨",
    "M3b": "긴 끊김에서 죽음 원인 문구로 거절된 시행 없음",
    "M3c": "긴 끊김의 거절이 첫 분류 기록 뒤 10.0–11.5 s",
    "M3d": "긴 끊김의 거절 시각에 상대가 살아 있음",
    "M4a": "끊김 중 kill된 상대가 재연결 거부(ECONNREFUSED)로 죽음 판정",
    "M4b": "끊김 중 kill: '모름' 거절과 복구가 없음",
    "M4c": "끊김 중 kill의 거절이 첫 분류 기록 뒤 2 s 안",
    "G1": "회귀 셀 여섯 개가 그대로 투명",
    "G2": "끊김 없는 kill은 죽음 원인으로 거절되고 abort가 돌아옴",
    "G3": "받는 쪽 abort 해제가 그대로",
    "C1": "1 s 끊김: 닫힘과 재연결 없이 투명(대조)",
    "C2": "재연결을 끄면 8 s 끊김 뒤 'no helper socket'으로 거절(대조)",
    "L1": "4 KiB 지연 차이 0.40 µs 이하(대조)",
    "L2": "256 KiB 지연 차이 0.30 µs 이하(대조)",
}
EXCL_LABEL = {"bind": "드라이버 랑데부 포트 충돌", "no_fault": "장애 미적용(훅 발화 없음)", "trigger_miss": "트리거 미도달",
              "no_kill": "kill 기록 없음", "order": "순서 미적용(소켓 닫힘 전 분류 기록 또는 닫힘 없음)",
              "config_ts_off": "설정 확인 실패: 투명 복구 시작 줄 없음", "config_no_ua": "설정 확인 실패: abort 플래그 줄 없음",
              "config_rc_mode": "설정 확인 실패: 재연결 설정 줄이 셀과 다름", "config_no_mute": "설정 확인 실패: 끊김 시작 줄 없음",
              "surplus": "계획 수를 넘은 시행"}


def status_of(r):
    val = s2.val
    f = r.get("fault")
    if r.get("bind_fail") == "1":
        return "bind"
    if f in ("F1", "F1both") and val(r.get("n_fires_r0")) == 0:
        return "no_fault"
    if f == "F3" and val(r.get("n_fires_r1")) == 0:
        return "no_fault"
    tm = val(r.get("trigger_miss"))
    if isinstance(tm, float) and tm > 0:
        return "trigger_miss"
    if f == "F4" and str(r.get("killed")) != "1":
        return "no_kill"
    if r["cell"] in ORDER_CELLS:
        sc, q4 = val(r.get("sock_close_ms_r0")), val(r.get("q4_mono_r0"))
        if not isinstance(sc, float) or (isinstance(q4, float) and q4 < sc):
            return "order"
    if r["build"] in ("rc", "s2r") and r.get("ts") == "1":
        if not (val(r.get("ts_on_r0")) >= 1 and val(r.get("ts_on_r1")) >= 1):
            return "config_ts_off"
        if not (val(r.get("ua_r0")) >= 1 and val(r.get("ua_r1")) >= 1):
            return "config_no_ua"
        if r["build"] == "rc":
            want = "0" if r["cell"] in RC_OFF_CELLS else "1"
            if r.get("rc_mode_r0") != want or r.get("rc_mode_r1") != want:
                return "config_rc_mode"
        if r["cell"] in MUTE_CELLS and not val(r.get("n_mute_on_r0")) >= 1:
            return "config_no_mute"
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
            r.update({k: ("" if v is None else v) for k, v in extra_rc(stem).items()})
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
    L = ["# gin-reconnect 채점 결과", "",
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
