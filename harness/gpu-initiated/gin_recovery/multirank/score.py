#!/usr/bin/env python3
"""gin-multirank scorer: applies the frozen acceptance rules of predictions.csv to the main run and writes
<resultsdir>/SCORE.md and <resultsdir>/trials_scored.csv. The pilot (its own results directory) is never passed here.

usage: score.py <resultsdir>          (e.g. results/<date>)

Steps (EXPERIMENT.md 3 and 8):
  1. every hold subdirectory with *_meta.txt files (h1/ ... h7/, fill subdirectories) -> rows_mr.rows_of() per trial;
  2. each trial gets its cell key cell@build (build = the recovery build key LIB) and a status: scored, excluded (bind
     failure, fault not applied, no kill in the traffic, rounds not overlapping in the stalled cells), config (a
     configuration check failed) or surplus (non-excluded trials beyond the planned count; the first ones by trial
     number are scored). Trials whose devComm was not created on every rank skip the configuration checks (I1 scores them);
  3. every prediction is evaluated on the scored trials with the grammar of ../s2_close/EXPERIMENT.md 3.2, using the
     evaluation functions of ../s2_close/score.py unchanged; a prediction whose cells have fewer scored trials than
     planned is "자료 부족".
"""
import csv, glob, hashlib, importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
S2C = os.path.join(HERE, "..", "s2_close")
_spec = importlib.util.spec_from_file_location("s2close_score", os.path.join(S2C, "score.py"))
s2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s2)  # grammar: evaluate, val, NIL, keys_of
sys.path.insert(0, HERE)
from rows_mr import rows_of  # noqa: E402

MAIN = "hd"  # the recovery build of the main run (EXPERIMENT.md 5); the pilot's build is never scored
# section 7: planned scored trials per cell (latency cells: runs)
PLAN = {"mr4_none": 10, "mr4_none_peer": 5, "mr2_none": 5, "mr3_none": 5, "mr3_f1_01": 5,
        "mr2_lat": 5, "mr4_lat_solo": 5, "mr4_lat": 5,
        "mr4_f1_01": 10, "mr4_f1_02": 10, "mr4_f3_01": 10, "mr4_f1_01_23": 10, "mr4_f1_10_30": 10, "mr4_f1all0": 10,
        "mr4_kill3": 10, "mr4_kill3_peer": 10, "mr4_cyc_stall": 5, "mr4_chain_stall": 5}
PLANNED = {f"{c}@{MAIN}": n for c, n in PLAN.items()}
# section 8: the hook fires each cell must show (rank:context, "all" = every context), the kill cells, the stalled cells
FIRES = {"mr4_f1_01": "0:0", "mr4_f1_02": "0:1", "mr4_f3_01": "1:0", "mr4_f1_01_23": "0:0;2:8", "mr4_f1_10_30": "1:3;3:9",
         "mr4_f1all0": "0:all", "mr4_cyc_stall": "0:0;1:4;2:6", "mr4_chain_stall": "0:0;1:4", "mr3_f1_01": "0:0"}
KILL = {"mr4_kill3", "mr4_kill3_peer"}
STALLED = {"mr4_cyc_stall": "0:300;1:300;2:300", "mr4_chain_stall": "0:300;1:300"}
PEER_FLUSH = {"mr4_none_peer", "mr4_kill3_peer"}
# build marker lines: every rank of a trial of that build must show them (n_<marker> == n); a build not listed has none.
# hd (gin-harden) keeps gin-oneway's start line and adds "GIN/TS: harden=1 rank=<r> ..." (gin_host_gdaki.cc gdakiTsStart).
BUILD_MARK = {"ow": ["n_ow"], "hd": ["n_ow", "n_hd"]}

LABEL = {
    "I1": "랭크 4개(GPU마다 프로세스 2개)가 통신기와 문맥 12개의 devComm을 만들고, 네 랭크 모두 투명 복구가 켜짐",
    "I2": "GPU 하나를 두 프로세스의 커널이 나눠 써도 교착 없이 간선 12개가 모두 정확히 전달됨",
    "I3": "장애가 없으면 복구 라운드, 거절, 감시 줄이 없음",
    "I4": "랭크 3개: 투명하고 랭크마다 게이트 QP 12개(대조)",
    "I5": "새 드라이버를 랭크 2개로 돌리면 투명(대조)",
    "I6": "상대별 flush도 장애 없이 투명(대조)",
    "A1": "간선 0>1의 로컬 QP 오류를 그 QP 하나만 다루는 라운드 하나로 복구",
    "A2": "간선 0>1의 로컬 QP 오류 뒤에도 간선 12개 모두 투명",
    "A3": "라운드를 거친 QP는 그 쌍뿐이고, 훅이 건드린 나머지 두 QP는 끝까지 ERR",
    "B1": "같은 GPU의 두 프로세스 사이(NIC loopback) 간선 0>2의 로컬 QP 오류도 쌍 범위 라운드로 투명하게 복구",
    "B2": "간선 0>2: 라운드를 거친 QP는 그 쌍뿐이고 나머지 두 QP는 ERR",
    "C1": "상대 QP 오류(RETRY_EXC)를 쌍 범위 라운드 하나로 투명하게 복구",
    "C2": "간선 0>1이 묶인 약 3.6 s 동안 rank 0의 다른 두 간선이 각각 100번 이상 진행",
    "C3": "상대 QP 오류: 라운드를 거친 QP는 그 쌍뿐이고 rank 1의 나머지 두 QP는 ERR",
    "C4": "상대 QP 오류의 첫 분류 기록이 훅 3.0-4.5 s 뒤",
    "D1": "겹치지 않는 두 쌍의 동시 장애가 독립된 두 라운드로 투명하게 복구",
    "D2": "겹치지 않는 두 쌍: 라운드를 거친 QP는 두 쌍뿐",
    "E1": "두 시작 쪽이 같은 응답 쪽(rank 0)으로 동시에 와도 둘 다 투명하게 복구",
    "E2": "rank 0의 helper가 두 응답 라운드를 차례로 처리(겹침 없음)",
    "E3": "두 시작 쪽: 라운드를 거친 QP는 두 쌍뿐",
    "F1": "rank 0의 모든 문맥 장애를 상대별 전체 범위 라운드 세 번으로 복구",
    "F2": "rank 0의 모든 문맥 장애 뒤에도 간선 12개 모두 투명",
    "F3": "세 라운드가 겹치지 않고, rank 0과 각 상대 사이의 모든 QP가 라운드 한 번을 거쳐 RTS",
    "K1": "rank 3 kill 뒤 살아남은 세 랭크가 소켓으로 rank 3의 죽음을 바로 판정하고 rank 3만 거절(문맥 전체 flush)",
    "K2": "그 거절이 kill 0–2 s 뒤",
    "K3": "문맥 전체 flush에서는 거절 뒤 살아남은 랭크 사이의 간선 6개도 모두 오류로 멈춤",
    "K4": "상대별 flush에서도 rank 3만 거절",
    "K5": "상대별 flush: 거절 뒤 살아남은 랭크 사이의 받는 쪽 6개는 모두 오류, 보내는 쪽 6개는 끝까지 성공",
    "K6": "살아남은 세 랭크의 앱이 모두 통신기 비동기 오류를 봄",
    "K7": "거절은 rank 3으로 가는 QP 12개만 닫음",
    "R1": "복구 셀에서 라운드 상한, 펌웨어 단계와 복사의 상한 초과, 소켓으로 취소된 라운드, 죽음 판정이 없음",
    "Y1": "순환하는 세 시작 쪽이 서로를 기다려 handshake timeout 거절이 생기고 투명하지 않음",
    "Y2": "첫 handshake timeout이 라운드 시작 24.3-24.8 s 뒤",
    "Y3": "그 한도 전에는 어떤 복구도 끝나지 않고(첫 복구가 첫 라운드 24 s 이상 뒤) 감시 줄도 없음",
    "Z1": "순환이 없는 사슬은 첫 라운드 5 s 안에 두 라운드가 모두 끝나고 투명(대조)",
    "Z2": "사슬에서 rank 1이 rank 0의 쌍 범위 요청을 거부하고(훅이 ERR로 둔 문맥 4의 QP) rank 0이 전체 범위로 다시 연다(대조)",
    "T1": "랭크 3개에서 간선 0>1의 로컬 QP 오류를 쌍 범위 라운드로 투명하게 복구(대조)",
    "L1": "랭크 2개 4 KiB p50이 10.0-12.0 µs(대조)",
    "L2": "같은 두 간선을 랭크 4개 통신기에서 돌려도 p50 차이 1.0 µs 이하(대조)",
    "L3": "탐색: 모든 간선이 돌 때 노드 사이 간선의 p50 중앙값이 혼자일 때의 2배 이하",
    "L4": "탐색: GPU 시분할로 5회 중 4회 이상 어떤 간선에 200 µs 이상 반복",
    "L5": "프로세스가 GPU마다 하나면 5회 중 4회 이상 200 µs 넘는 반복 없음(대조)",
}
EXCL_LABEL = {"bind": "드라이버 랑데부 포트 충돌", "no_fault": "장애 미적용(훅 발사가 셀과 다르거나 트래픽 밖)",
              "no_kill": "kill이 없거나 트래픽 밖", "cond_order": "순서 미적용(멈춘 라운드들이 250 ms 안에 시작하지 않음)",
              "config_ts": "설정 확인 실패: 투명 복구 시작 줄 수", "config_ua": "설정 확인 실패: abort 플래그 줄 수",
              "config_pair": "설정 확인 실패: pair reset/check 줄 수", "config_gq": "설정 확인 실패: 게이트 QP 수",
              "config_build": "설정 확인 실패: 빌드 표시 줄", "config_knob": "설정 확인 실패: 시험 스위치 줄",
              "config_fires": "설정 확인 실패: 장애 없는 셀에 훅 발사", "config_flush": "설정 확인 실패: flush 방식",
              "config_mrge": "설정 확인 실패: 같은 GPU 거부", "surplus": "계획 수를 넘은 시행"}


def status_of(r):
    val = s2.val
    cell, n = r["cell"], int(r.get("n") or 0)
    if r.get("bind_fail") in ("1", 1):
        return "bind"
    if cell in FIRES and (r.get("fires") != FIRES[cell] or str(r.get("fire_in_traffic")) != "1"):
        return "no_fault"
    if cell in KILL and (str(r.get("killed")) != "1" or str(r.get("kill_in_traffic")) != "1"):
        return "no_kill"
    if cell in STALLED:
        sp = val(r.get("cyc_spread_ms"))
        if not isinstance(sp, float) or sp > 250:
            return "cond_order"
    if str(r.get("init_fail")) == "1":
        return "candidate"  # I1 scores it; the checks below need every rank's devComm
    if val(r.get("n_ts_on")) != n:
        return "config_ts"
    if val(r.get("n_ua")) != n:
        return "config_ua"
    if val(r.get("n_pr")) != n or val(r.get("n_pc")) != n:
        return "config_pair"
    want_gq = (n - 1) * n * (n - 1)
    if val(r.get("gq_min")) != want_gq or val(r.get("gq_max")) != want_gq:
        return "config_gq"
    for mark in BUILD_MARK.get(r.get("build", ""), []):
        if val(r.get(mark)) != n:
            return "config_build"
    if (r.get("knob_stall") or "") != STALLED.get(cell, ""):
        return "config_knob"
    if cell not in FIRES and str(r.get("n_fires")) not in ("", "0"):
        return "config_fires"
    if r.get("flush") != ("peer" if cell in PEER_FLUSH else "ctx"):
        return "config_flush"
    if str(r.get("mrge_err")) == "1":
        return "config_mrge"
    return "candidate"


def main():
    R = os.path.abspath(sys.argv[1])
    subs = sorted(d for d in os.listdir(R) if os.path.isdir(os.path.join(R, d)) and glob.glob(os.path.join(R, d, "*_meta.txt")))
    trials = []
    for sub in subs:
        for meta in sorted(glob.glob(os.path.join(R, sub, "*_meta.txt"))):
            r = {k: ("" if v is None else v) for k, v in rows_of(meta[: -len("_meta.txt")]).items()}
            r = {k: str(v) for k, v in r.items()}
            r["sub"] = sub
            r["key"] = f'{r["cell"]}@{r["build"]}'
            m = re.search(r"n(\d+)$", r.get("trial") or "")
            r["tnum"] = int(m.group(1)) if m else 0
            trials.append(r)
    allcols = set()
    for r in trials:
        allcols.update(r.keys())
    for r in trials:  # a column a trial lacks (a rank that never logged it) is an empty field, never a missing name
        for c in allcols:
            r.setdefault(c, "")
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
    L = ["# gin-multirank 채점 결과", "",
         f"`score.py`가 원자료(`{os.path.relpath(R, HERE)}/`의 hold별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.", "",
         f"- 예측 파일 sha256: `{sha}`. `PREREG.txt`의 값과 {'같다' if sha in frozen else '다르다(확인 필요)'}.",
         f"- 시행 수(모든 hold): {len(trials)}. 판정한 시행: {sum(len(v) for v in scored.values())}.",
         "- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.", "",
         "## 판정 요약", "", "| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |", "|---|---|--:|---|---|"]
    for p, keys, evals, verdict, short in results:
        ns = " / ".join(str(len(scored.get(k, []))) for k in keys)
        hits = "; ".join(", ".join(f"{c}/{n}" for (_, c, n, _, _, _) in det) if det else expr for (_, _, det, expr) in evals)
        cells = ", ".join(f"`{k}`" for k in keys)
        L.append(f"| {LABEL.get(p['id'], p['id'])} ({p['id']}) | {cells} | {ns} | {hits} | {verdict} |")
    L += ["", "## 예측별 세부", ""]
    for p, keys, evals, verdict, short in results:
        L += [f"### {LABEL.get(p['id'], p['id'])} ({p['id']}): {verdict}", "", f"- 판정식: `{p['acceptance']}`"]
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
