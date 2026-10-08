#!/usr/bin/env python3
"""nccl-builtin scorer: applies the frozen acceptance rules of predictions.csv to the main run and writes
<resultsdir>/SCORE.md and <resultsdir>/trials_scored.csv. Never run on a pilot folder (pilot trials are not scored).

usage: score.py <resultsdir>          (e.g. results/<date>; its subfolders off/, rec/, fo/, forec/, s2on/, s2off/)

Steps (EXPERIMENT.md 3 and 8):
  1. rows_nb.rows() makes one row per trial (the section 3.1 columns) from every subfolder's *_meta.txt;
  2. each trial gets its cell key cell@cfg and a status: scored, excluded (launch failure, fault not applied, kill not
     done or done before the survivor's loop ran), config (a section 8 configuration check failed, cells.config_status),
     or surplus (non-excluded trials beyond the planned count; the first ones by trial number are scored);
  3. every prediction is evaluated on the scored trials with the grammar of
     ../../gpu-initiated/gin_recovery/s2_close/EXPERIMENT.md 3.2, using the evaluation functions of
     ../../gpu-initiated/gin_recovery/s2_close/score.py unchanged; a prediction whose cells have fewer scored trials
     than planned is "자료 부족".
"""
import csv, hashlib, importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
S2C = os.path.join(HERE, "..", "..", "gpu-initiated", "gin_recovery", "s2_close")
_spec = importlib.util.spec_from_file_location("s2close_score", os.path.join(S2C, "score.py"))
s2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s2)  # grammar: evaluate, keys_of, val, NIL
sys.path.insert(0, HERE)
import rows_nb  # noqa: E402
from cells import CELLS, KEYS, config_status  # noqa: E402

# section 7: planned scored trials per cell key (overhead cells: runs)
PLANNED = {k: 5 for k in KEYS}
PLANNED.update({"sqp@fo": 10, "sqp@forec": 10, "rqp@fo": 10, "rqp@forec": 10})

LABEL = {
    "B1": "2.32.3 기본: 송신 QP 오류가 rank 0에서 1 s 안에 ncclRemoteError로 올라옴(원본 오류 경로, WR_FLUSH_ERR)",
    "B2": "2.32.3 기본: 수신 QP 오류가 rank 1 자신에게서 1 s 안에 ncclRemoteError로 올라옴",
    "B3": "2.32.3 기본: 상대 SIGKILL 뒤 받는 중인 생존 rank는 12 s 반복 제한까지 오류를 보지 못함",
    "B4": "2.32.3 기본: 조용한 수신 QP 오류도 rank 1 자신이 1 s 안에 ncclRemoteError로 올림",
    "R1": "port recovery만 켜면 데이터 경로가 그대로임(원본 오류 경로, 복원력 줄과 복구 동작 없음)",
    "F1": "port failover(와 recovery): 송신 QP 오류를 곧바로 치명으로 판정하고 rank 0에 1 s 안에 ncclRemoteError, 복구 동작 없음",
    "F2": "port failover(와 recovery): 수신 QP 오류도 rank 1에서 곧바로 치명, 1 s 안에 ncclRemoteError",
    "F3": "port failover(와 recovery): 상대 SIGKILL 뒤 생존 rank는 12 s 반복 제한까지 오류를 보지 못함",
    "F4": "port failover(와 recovery): 조용한 수신 QP 오류를 rank 1 자신이 치명으로 판정해 1 s 안에 올림",
    "F5": "port failover를 켠 모든 시행에서 두 rank가 연결 때 '넘겨 갈 다른 장치가 없다'고 경고함",
    "F6": "2.32.3의 어느 설정도 네 장애 중 어느 것도 투명하게 만들지 못함",
    "F7": "2.32.3의 어느 시행에서도 장치 실패 표시, QP 교체, 확인 읽기, port recovery가 시작되지 않음",
    "S1": "다중 요청 복구(켬)가 주입한 송신, 수신 QP 오류를 그대로 투명하게 복구함",
    "S2": "다중 요청 복구 시간 중앙값이 두 셀 모두 1.8–3.0 ms",
    "S3": "다중 요청 복구(켬)는 상대 SIGKILL을 OOB 소켓의 FIN으로 알아 1 s 안에 생존 rank에 오류를 올림",
    "S4": "다중 요청 복구(켬)는 조용한 오류를 rank 1에서 조용히 둠(1 s 안 오류 없음). 작업은 투명 복구 또는 멈춤",
    "S5": "다중 요청 복구(켬)의 256 KiB all-reduce 조용한 오류는 12 s 반복 제한까지 멈춤",
    "S6": "다중 요청 복구 끔: 송신 QP 오류가 rank 0에서 1 s 안에 ncclRemoteError, 복구 없음",
    "S7": "다중 요청 복구 끔: 수신 QP 오류가 rank 1에서 1 s 안에 ncclRemoteError, 복구 없음",
    "S8": "다중 요청 복구 끔: 상대 SIGKILL 뒤 생존 rank는 12 s 반복 제한까지 오류를 보지 못함",
    "I1": "어느 셀의 어느 시행도 틀린 결과를 내지 않음(MISMATCH 없음)",
    "O1": "장애 없는 16 MiB all-reduce: port failover가 rank 0 반복 시간 중앙값을 2 % 넘게 바꾸지 않음",
    "O2": "장애 없는 64 KiB all-reduce: port failover가 5 % 넘게 바꾸지 않음",
    "O3": "failover에 port recovery를 더해도 두 크기 모두 2 % 넘게 바뀌지 않음",
    "O4": "다중 요청 복구 켬이 끔 대비 16 MiB 2 %, 64 KiB 3 % 안",
    "O5": "장애 없는 실행은 모두 두 rank가 모든 반복을 bit 단위로 맞게 마침",
}
EXCL_LABEL = {"launch": "시작 실패(두 rank 중 하나가 통신기 준비 전에 끝남)", "no_fault": "장애 미적용(훅 줄 없음)",
              "no_kill": "kill 미적용(PID 확인 실패)",
              "kill_early": "kill 시점 미달(생존 rank가 1000회를 마치기 전)", "surplus": "계획 수를 넘은 시행"}


def status_of(r):
    if r["launch_fail"]:
        return "launch"
    fault = CELLS[r["cell"]]["fault"]
    if fault == "inject0" and r["inj_r0"] == 0 or fault == "inject1" and r["inj_r1"] == 0:
        return "no_fault"
    if fault == "kill1":
        if r["kill_ok"] != "1":
            return "no_kill"
        ok = s2.val(r["ok_r0"])
        if not (isinstance(ok, float) and ok >= 1000):
            return "kill_early"
    why = config_status(r)
    if why:
        return "config:" + why
    return "candidate"


CONFIG_LABEL = {"config_version": "NCCL 버전이 설정과 다름", "config_lib_r1": "rank 1의 라이브러리가 설정과 다름",
                "config_failover": "failover 문맥 줄이 설정과 다름", "config_recovery_thread": "recovery 스레드 줄이 설정과 다름",
                "config_recovery_ctx": "recovery 문맥 줄이 설정과 다름", "config_stage2_flag": "다중 요청 복구 켬 줄이 설정과 다름",
                "config_hook_fired": "훅이 없어야 할 셀에서 발사", "config_hook_rank": "훅이 다른 rank에서 발사",
                "config_hook_kind": "훅 종류가 셀과 다름"}
for _k, _v in CONFIG_LABEL.items():
    EXCL_LABEL["config:" + _k] = "설정 확인 실패: " + _v


def main():
    R = os.path.abspath(sys.argv[1])
    if R.rstrip("/").endswith("_pilot"):
        sys.exit("pilot trials are never scored (EXPERIMENT.md 3)")
    subs = sorted(d for d in os.listdir(R) if os.path.isdir(os.path.join(R, d)))
    trials = rows_nb.rows([os.path.join(R, d) for d in subs])
    for r in trials:
        r["key"] = f'{r["cell"]}@{r["cfg"]}'
        r["tnum"] = int(r["trial"][1:])
        r["status"] = status_of(r)
    by_key, scored = {}, {}
    for r in sorted(trials, key=lambda x: (x["key"], x["tnum"])):
        by_key.setdefault(r["key"], []).append(r)
    for k, rs in by_key.items():
        cand = [r for r in rs if r["status"] == "candidate"]
        for i, r in enumerate(cand):
            r["status"] = "scored" if i < PLANNED.get(k, 0) else "surplus"
        scored[k] = [r for r in rs if r["status"] == "scored"]
    preds = list(csv.DictReader(open(os.path.join(HERE, "predictions.csv"))))
    sha = hashlib.sha256(open(os.path.join(HERE, "predictions.csv"), "rb").read()).hexdigest()
    pre = os.path.join(HERE, "PREREG.txt")
    frozen = open(pre).read() if os.path.exists(pre) else ""
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
    cols = ["key", "status", "stem", "cell", "cfg", "trial"]
    for r in trials:
        for c in r:
            if c not in cols:
                cols.append(c)
    with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(trials, key=lambda x: (x["key"], x["tnum"])):
            w.writerow(r)
    L = ["# nccl-builtin 채점 결과", "",
         f"`score.py`가 원자료(`{os.path.relpath(R, HERE)}/`의 설정별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.", "",
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
