#!/usr/bin/env python3
"""gin-oneway scorer: applies the frozen acceptance rules of predictions.csv to the main run and writes
<resultsdir>/SCORE.md and <resultsdir>/trials_scored.csv.

usage: score.py <resultsdir>          (e.g. results/20261008)

Steps (EXPERIMENT.md 3 and 8):
  1. every hold subdirectory with *_meta.txt files (ow/, pcm/, pc/, lat/) -> ../scripts/ts2/rows.py -> trials_<sub>.csv;
  2. ../s2_close/rows_extra.extra(), ../pair_check/rows_pc.extra_pc() and rows_ow.extra_ow() add the section 3.1 columns
     from the per-trial files;
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
sys.path.insert(0, os.path.join(HERE, "..", "pair_check"))
from rows_pc import extra_pc  # noqa: E402  (../pair_check/rows_pc.py)
sys.path.insert(0, HERE)
from rows_ow import extra_ow  # noqa: E402

# section 7: planned scored trials per cell key (latency cells: runs)
PLANNED = {"ow_r1in_f1_b@ow": 10, "ow_r0in_f1r1_b@ow": 10, "ow_kill0_b@ow": 10, "ow_hello_f1_b@ow": 10,
           "ow_r1in_f1_b@pcm": 5, "ow_r0in_f1r1_b@pcm": 5, "ow_kill0_b@pcm": 5, "ow_hello_f1_b@pcm": 5,
           "ow_r0in_nat_f1r1_b@pc": 5, "ow_r0in_nat_f1r1_b@ow": 5,
           "f1_b@ow": 5, "f3_b@ow": 5, "bidirf_sym_b@ow": 5, "f4_b@ow": 5, "f2rel_b@ow": 5,
           "rc_mute8_f1_b@ow": 5, "rc_mutekill_b@ow": 5,
           "lat_pc_on_4k@pc": 5, "lat_pc_on_256k@pc": 5, "lat_ow_on_4k@ow": 5, "lat_ow_on_256k@ow": 5}
# section 8: which rank's hook must fire, the order condition, the switches and mutes each cell must show
HOOK_R0 = {"ow_r1in_f1_b", "ow_hello_f1_b", "f1_b", "rc_mute8_f1_b"}
HOOK_R1 = {"ow_r0in_f1r1_b", "ow_r0in_nat_f1r1_b", "f3_b"}
HOOK_BOTH = {"bidirf_sym_b"}
KILL_R1 = {"f4_b", "rc_mutekill_b"}
ORDER_R1 = {"ow_r0in_f1r1_b", "ow_r0in_nat_f1r1_b", "ow_kill0_b"}
# knob lines: (uto_r0, refuse_r0, uto_r1, refuse_r1); None = no line on that rank
KNOBS = {"ow_r1in_f1_b": (("20000", "0"), None), "ow_r0in_f1r1_b": (None, ("20000", "0")),
         "ow_hello_f1_b": (None, ("5000", "1"))}
# mute lines: (rank 0 muted, rank 1 muted); cells not listed are not checked
MUTES = {"ow_r1in_f1_b": (False, True), "ow_r0in_f1r1_b": (True, False), "ow_r0in_nat_f1r1_b": (True, False),
         "ow_kill0_b": (True, True), "ow_hello_f1_b": (True, True), "rc_mute8_f1_b": (True, True),
         "rc_mutekill_b": (True, True)}

LABEL = {
    "A0": "한쪽 끊김 시험이 의도대로 됨: 끊긴 rank 1이 먼저 시간 초과하고 그 리셋을 rank 0이 받음",
    "A1": "rank 0이 리셋을 모름으로 두고 두 rank 모두 살아 있는 상대를 죽음으로 보지 않음",
    "A2": "두 rank가 한 번씩 다시 연결되고 rank 0은 끊김이 끝난 뒤 1.5 s 안",
    "A3": "12 s의 로컬 QP 오류가 투명하게 복구되고 거절과 장애 전 비동기 오류가 없음",
    "K1": "기준 빌드: rank 0이 리셋을 죽음으로 보고 장애를 ECONNRESET으로 거절함(rank 1은 살아 있고 다시 연결되지 않음)",
    "B0": "거울 방향 시험이 의도대로 됨: 끊긴 rank 0이 먼저 시간 초과하고 그 리셋을 rank 1이 받음",
    "B1": "rank 1이 리셋을 모름으로 두고 두 rank 모두 살아 있는 상대를 죽음으로 보지 않음",
    "B2": "끊김 중 rank 1의 장애가 재연결을 기다리고, 끊김이 끝난 뒤 1.5 s 안에 재연결로 끝남",
    "B3": "그 뒤 rank 1이 시작 쪽으로 복구하고 투명함",
    "K2": "기준 빌드: rank 1이 리셋을 죽음으로 보고 장애를 ECONNRESET으로 거절함",
    "D1": "끊김이 끝난 뒤 rank 1의 확인 접속이 거부되어 죽은 rank 0을 죽음으로 알아냄(끊김 중에는 죽음으로 정하지 않음)",
    "D2": "rank 1의 재시도 초과가 죽음 원인(ECONNREFUSED)으로 거절되고 모름 거절과 복구가 없음",
    "D3": "그 거절이 rank 1의 첫 분류 기록 뒤 2 s 안에 옴",
    "K3": "기준 빌드: rank 1이 죽은 rank 0을 모르고 10 s 상한 뒤 모름으로 거절함",
    "E1": "rank 1이 첫 재연결을 거부해도 rank 0은 받아들여지지 않음으로 남기고 아무도 상대를 죽음으로 보지 않음",
    "E2": "다음 다시 걸기로 두 rank가 한 번씩 다시 연결되고 rank 0은 끊김이 끝난 뒤 2 s 안",
    "E3": "12 s의 로컬 QP 오류가 투명하게 복구됨(재연결 거부 셀)",
    "K4": "기준 빌드: rank 0이 재연결로 센 뒤 거부의 FIN을 읽고 상대를 죽음으로 보며 장애를 FIN으로 거절함",
    "U1": "시간 초과 시험 스위치 없이 배포된 pc가 한쪽 끊김 뒤 살아 있는 rank 0을 ECONNRESET으로 거절함(5회 중 2회 이상)",
    "U2": "같은 경주 조건에서 새 빌드는 투명하고 아무도 상대를 죽음으로 보지 않음",
    "G1": "복구 재현 셀이 그대로 투명",
    "G2": "양쪽 8 s 끊김에서 두 rank가 한 번씩 1.5 s 안에 다시 연결되고 죽음 줄이 없음",
    "G3": "끊김 없는 kill은 죽음 원인(FIN 또는 ECONNREFUSED)으로 거절되고 abort가 돌아옴",
    "G4": "양쪽 끊김 중 kill된 rank 1은 다시 걸기 거부로 죽음 거절되고 모름 거절이 없음",
    "G5": "받는 쪽 abort 해제가 그대로",
    "G6": "상대 QP 오류 뒤 teardown 때 두 rank의 모든 QP가 RTS",
    "L1": "4 KiB 지연 차이 0.40 µs 이하(대조)",
    "L2": "256 KiB 지연 차이 0.30 µs 이하(대조)",
}
EXCL_LABEL = {"bind": "드라이버 랑데부 포트 충돌", "no_fault": "장애 미적용(훅 발사 없음)", "trigger_miss": "트리거 미도달",
              "no_kill": "kill 기록 없음", "no_kill0": "장애 미적용(rank 0 kill 기록이나 rank 1의 첫 분류 기록 없음)",
              "cond_order": "순서 미적용(소켓을 잃기 전에 첫 분류 기록)",
              "config_ts_off": "설정 확인 실패: 투명 복구 시작 줄 없음", "config_no_ua": "설정 확인 실패: abort 플래그 줄 없음",
              "config_pc_mode": "설정 확인 실패: 검사 스위치 줄이 1이 아님", "config_ow_mode": "설정 확인 실패: 생존 규칙 시작 줄이 빌드와 다름",
              "config_knobs": "설정 확인 실패: 시험 스위치 줄이 셀과 다름", "config_mute": "설정 확인 실패: 끊김 줄이 셀과 다름",
              "config_inj_ctx": "설정 확인 실패: 훅의 문맥 지정이 셀과 다름",
              "surplus": "계획 수를 넘은 시행"}


def status_of(r):
    val = s2.val
    cell = r["cell"]
    if r.get("bind_fail") == "1":
        return "bind"
    if cell in HOOK_R0 and val(r.get("n_fires_r0")) == 0:
        return "no_fault"
    if cell in HOOK_R1 and val(r.get("n_fires_r1")) == 0:
        return "no_fault"
    if cell in HOOK_BOTH and (val(r.get("n_fires_r0")) == 0 or val(r.get("n_fires_r1")) == 0):
        return "no_fault"
    tm = val(r.get("trigger_miss"))
    if isinstance(tm, float) and tm > 0:
        return "trigger_miss"
    if cell in KILL_R1 and str(r.get("killed")) != "1":
        return "no_kill"
    if cell == "ow_kill0_b" and (str(r.get("r0_killed")) != "1" or r.get("q4_ms_r1") in (None, "")):
        return "no_kill0"
    if cell in ORDER_R1:
        c1, q = val(r.get("close1_ms_r1")), val(r.get("q4_ms_r1"))
        if not isinstance(c1, float) or (isinstance(q, float) and q < c1):
            return "cond_order"
    if cell == "rc_mutekill_b":
        c0, q0 = val(r.get("close1_ms_r0")), val(r.get("q4_ms_r0"))
        if not isinstance(c0, float) or (isinstance(q0, float) and q0 < c0):
            return "cond_order"
    if r.get("ts") == "1":
        if not (val(r.get("ts_on_r0")) >= 1 and val(r.get("ts_on_r1")) >= 1):
            return "config_ts_off"
        if not (val(r.get("ua_r0")) >= 1 and val(r.get("ua_r1")) >= 1):
            return "config_no_ua"
    if r.get("pc_mode_r0") != "1" or r.get("pc_mode_r1") != "1":
        return "config_pc_mode"
    want = "1" if r["build"] == "ow" else ""
    if str(r.get("ow_mode_r0")) != want or str(r.get("ow_mode_r1")) != want:
        return "config_ow_mode"
    kn = KNOBS.get(cell, (None, None))
    for rk in (0, 1):
        got = (str(r.get("knob_uto_r%d" % rk)), str(r.get("knob_refuse_r%d" % rk)))
        exp = kn[rk]
        if exp is None and got != ("", ""):
            return "config_knobs"
        if exp is not None and got != exp:
            return "config_knobs"
    if cell in MUTES:
        m0, m1 = MUTES[cell]
        n0, n1 = val(r.get("n_mute_on_r0")), val(r.get("n_mute_on_r1"))
        if (m0 and not n0 >= 1) or (not m0 and n0 != 0) or (m1 and not n1 >= 1) or (not m1 and n1 != 0):
            return "config_mute"
    if cell in ("ow_r0in_f1r1_b", "ow_r0in_nat_f1r1_b") and str(r.get("inj_ctx_r1")) != "1":
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
            r.update({k: ("" if v is None else v) for k, v in extra_pc(stem).items()})
            r.update({k: ("" if v is None else v) for k, v in extra_ow(stem).items()})
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
    L = ["# gin-oneway 채점 결과", "",
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
