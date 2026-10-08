#!/usr/bin/env python3
"""gin-harden scorer: applies the frozen acceptance rules of predictions.csv to the main run and writes
<resultsdir>/SCORE.md and <resultsdir>/trials_scored.csv.

usage: score.py <resultsdir>          (e.g. results/<date>)

Steps (EXPERIMENT.md 3 and 8):
  1. every hold subdirectory with *_meta.txt files (hd/, ow/, ow2/, hdp/, stk/) -> ../scripts/ts2/rows.py ->
     trials_<sub>.csv;
  2. ../s2_close/rows_extra.extra(), ../pair_check/rows_pc.extra_pc(), ../oneway/rows_ow.extra_ow() and
     rows_hd.extra_hd() add the section 3.1 columns from the per-trial files;
  3. each trial gets its cell key cell@build and a status: scored, excluded (section 8: bind failure, fault not applied,
     trigger missed, no kill, order not met, mute not applied), config (a section 8 configuration check failed: the block
     stops), or surplus (non-excluded trials beyond the planned count; the first ones by trial number are scored);
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
sys.path.insert(0, os.path.join(HERE, "..", "oneway"))
from rows_ow import extra_ow  # noqa: E402  (../oneway/rows_ow.py)
sys.path.insert(0, HERE)
from rows_hd import extra_hd  # noqa: E402

REGRESSION = ["f1_b", "f3_b", "bidirf_sym_b", "f4_b", "f2rel_b", "pc_dual_f1c0_r1c2_b", "rc_mute8_f1_b", "rc_mutekill_b",
              "ow_r1in_f1_b", "ow_r0in_f1r1_b", "ow_kill0_b", "ow_hello_f1_b"]
NEW = ["hd_ref1_f1_b", "hd_ref2_f1_b", "hd_nonce_f1_b", "hd_rround_f1_b", "hd_rxdeath_b", "hd_hog_f1_b", "hd_fwslow_f1_b",
       "hd_copystall_f1_b", "hd_repost_f1_b", "hd_esc_f1_b", "hd_shrink_b"]
# section 7: planned scored trials per cell key (latency cells: runs)
PLANNED = {f"{c}@hd": 5 for c in REGRESSION}
PLANNED.update({f"{c}@hd": 10 for c in NEW})
PLANNED.update({"hd_rround_f1_b@ow": 5, "hd_rxdeath_b@ow": 5, "hd_fwslow_f1_b@ow": 5, "hd_esc_f1_b@ow": 5,
                "hd_shrink_b@ow2": 5, "hdp_kill_b@hdp": 5, "hdp_mute_b@hdp": 5, "to20_f3_b@hd": 5, "to20_f3_t@hd": 3})
for sz in ("4k", "256k"):
    for b in ("hdp", "ow", "stk"):
        PLANNED[f"lat_{sz}@{b}"] = 5
# section 8: which rank's hook must fire, kills, order conditions, switches and mutes each cell must show
HOOK_R0 = {"f1_b", "rc_mute8_f1_b", "ow_r1in_f1_b", "ow_hello_f1_b", "hd_ref1_f1_b", "hd_ref2_f1_b", "hd_nonce_f1_b",
           "hd_rround_f1_b", "hd_hog_f1_b", "hd_fwslow_f1_b", "hd_copystall_f1_b", "hd_repost_f1_b", "hd_esc_f1_b"}
HOOK_R1 = {"f3_b", "ow_r0in_f1r1_b", "to20_f3_b", "to20_f3_t"}
HOOK_BOTH = {"bidirf_sym_b", "pc_dual_f1c0_r1c2_b"}
KILL_R1 = {"f4_b", "rc_mutekill_b", "hd_shrink_b", "hdp_kill_b"}
KILL_R0 = {"ow_kill0_b", "hd_rxdeath_b"}
# old knob lines (uto_r0, refuse_r0, uto_r1, refuse_r1 as (rank0, rank1); None = no line on that rank)
KNOBS = {"ow_r1in_f1_b": (("20000", "0"), None), "ow_r0in_f1r1_b": (None, ("20000", "0")),
         "ow_hello_f1_b": (None, ("5000", "1")), "hd_rround_f1_b": (("20000", "0"), None)}
# gin-harden knob lines (rank, column, value); every other hd cell has no such line on either rank
HKNOBS = {"hd_ref1_f1_b": (1, "hk_gap", "8000:1200"), "hd_ref2_f1_b": (1, "hk_gap", "8000:3000"),
          "hd_nonce_f1_b": (0, "hk_badnonce", "1"), "hd_copystall_f1_b": (0, "hk_copystall", "4000"),
          "hd_repost_f1_b": (0, "hk_badrepost", "1")}
# mute lines: (rank 0 muted, rank 1 muted); cells not listed must show none
MUTES = {"rc_mute8_f1_b": (True, True), "rc_mutekill_b": (True, True), "ow_r1in_f1_b": (False, True),
         "ow_r0in_f1r1_b": (True, False), "ow_kill0_b": (True, True), "ow_hello_f1_b": (True, True),
         "hd_ref1_f1_b": (True, True), "hd_ref2_f1_b": (True, True), "hd_nonce_f1_b": (True, True),
         "hd_rround_f1_b": (False, True)}

LABEL = {
    "A1": "죽은 상대를 바로 거절해 rank 0의 대기가 shrink 전에 오류로 풀리고, 신호 없이 성공한 대기가 없음",
    "A2": "NCCL_SHRINK_ABORT shrink가 1-rank 통신기를 돌려주고 allreduce 결과가 맞음",
    "A3": "대조(ow 라이브러리): shrink 때 옛 커널이 아직 돎",
    "A4": "대조(ow 라이브러리): 마지막 abort가 받는 쪽 대기를 신호 없이 성공으로 풂(또는 shrink가 돌아오지 않음)",
    "A5": "원격 접근 오류 셀: 받는 쪽 대기가 상대 거절 때 오류로 풀리고 abort가 돌아옴(판정 바뀜)",
    "B1": "연결 거부 한 번으로는 살아 있는 상대를 죽음으로 보지 않음",
    "B2": "다음 다시 걸기로 재연결되고 12 s 장애가 투명",
    "B3": "1 s 이상 떨어진 거부 두 번은 죽음이고 바로 거절과 대기 해제로 드러남",
    "B4": "틀린 고유값의 HELLO는 거부되고 받아들여지지 않음으로 남으며 죽음 판정이 없음",
    "B5": "다음 다시 걸기로 끊김 끝 2 s 안에 재연결되고 투명",
    "B6": "라운드 안의 리셋은 라운드를 취소하고 재연결 뒤 다시 돈 라운드로 투명하게 복구",
    "B7": "대조(ow): 같은 리셋에서 REQ 보내기 실패로 거절",
    "B8": "받기만 하는 rank가 죽은 상대를 2 s 안에 죽음으로 보고 대기가 오류로 풀림",
    "B9": "받기만 하는 rank가 2 s 안에 비동기 오류를 받고 abort가 돌아옴",
    "B10": "대조(ow): 받기만 하는 rank가 자기 15 s 기다림 상한까지 기다림",
    "B11": "정상 종료의 FIN은 BYE 뒤라 떠남으로 남고 죽음 줄이 없음",
    "C1": "GPU 전체를 쓰는 커널이 도는 중에도 복구가 투명하고 복사 시간 초과가 없음",
    "C2": "8 s 펌웨어 단계에서 3.0–3.5 s에 감시가 발동해 대기를 오류로 풀고 오류를 드러냄",
    "C3": "helper가 아직 펌웨어 단계 안이어도 rank 0의 abort가 6 s 안에 돌아옴",
    "C4": "rank 1이 거절하고 abort가 돌아옴",
    "C5": "대조(ow): 같은 8 s를 기다린 뒤 복구",
    "C6": "멈춘 복사가 2 s 상한을 넘어 3 s 안에 거절되고 두 rank의 대기가 오류로 끝남",
    "C7": "두 rank의 abort가 돌아옴",
    "D1": "두 QP 중 두 번째의 다시 보내기 계획이 거부되면 어느 QP에도 다시 보내지 않음",
    "D2": "두 rank가 거절",
    "E1": "다섯 장애 중 셋은 복구되고 넷째에서 상한(10 s에 3번)으로 거절",
    "E2": "rank 0이 오류를 드러내고 rank 1이 상대 거절로 거절",
    "E3": "대조(ow): 다섯 번 모두 복구",
    "E4": "통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0을 셈",
    "E5": "kill 뒤 통계 API가 죽음 판정 1, 거절 1을 셈",
    "R1": "복구 재현 셀이 그대로 투명",
    "R2": "상대 QP 오류 뒤 teardown 때 두 rank의 모든 QP가 RTS",
    "R3": "끊김 없는 kill이 죽음 원인으로 거절되고 abort가 돌아옴",
    "R4": "kill 뒤 2 s 안에 거절(죽음이 바로 드러남)",
    "R5": "pair-check 동작(좁은 범위 거부, 전체 재실행)이 그대로",
    "R6": "양쪽 8 s 끊김에서 한 번씩 1.5 s 안에 재연결되고 죽음 줄이 없음",
    "R7": "끊김 중 kill된 rank 1이 1 s 이상 떨어진 거부 두 번 뒤 죽음으로 거절되고 모름 거절이 없음",
    "R8": "rank 0이 리셋을 받는 한쪽 끊김: 모름, 죽음 없음, 1.5 s 안 재연결, 투명",
    "R9": "rank 1이 리셋을 받는 한쪽 끊김: 모름, 재연결 기다림, 죽음 없음, 투명",
    "R10": "끊김 중 kill된 rank 0이 1 s 이상 떨어진 확인 접속 거부 두 번 뒤 죽음으로 판정되고 거절",
    "R11": "거부된 재연결 HELLO가 받아들여지지 않음으로 남고 2 s 안 재연결, 투명",
    "R12": "rank 0이 원격 접근 오류를 복구할 수 없다고 거절",
    "P1": "4 KiB 지연: 운영 빌드와 gin-oneway 차이 0.40 µs 이하",
    "P2": "256 KiB 지연: 운영 빌드와 gin-oneway 차이 0.30 µs 이하",
    "P3": "4 KiB 지연: 운영 빌드가 순정 NCCL보다 0.10–1.00 µs 느림",
    "P4": "256 KiB 지연: 운영 빌드가 순정 NCCL보다 0.10–1.00 µs 느림",
    "P5": "운영 빌드가 kill된 상대를 2 s 안에 죽음으로 거절하고 abort가 돌아옴",
    "P6": "운영 빌드: iptables 8 s 관리망 끊김 뒤 재연결, 죽음과 거절 없음, 투명",
    "P7": "운영 빌드는 WARN 수준에서 정보성 복구 줄을 남기지 않음",
    "T1": "IB 타임아웃 20: 상대 QP 오류의 첫 분류(RETRY_EXC)가 장애 50–70 s 뒤",
    "T2": "IB 타임아웃 20: 막는 flush가 그동안 기다리고 100 ms 이하의 한 라운드로 투명 복구",
    "T3": "IB 타임아웃 20, 장치 쪽 8 s 시간 제한: flush가 시간 초과를 돌려주고 복구도 거절도 없음",
}
EXCL_LABEL = {"bind": "드라이버 랑데부 포트 충돌", "no_fault": "장애 미적용(훅 발사 없음)", "trigger_miss": "트리거 미도달",
              "no_kill": "kill 기록 없음", "no_kill0": "rank 0 kill 기록 없음", "cond_order": "순서 미적용",
              "mute_not_applied": "관리망 끊김 미적용(iptables 규칙을 걸지 못함)",
              "config_build": "설정 확인 실패: 빌드 시작 줄이 빌드와 다름", "config_ts_off": "설정 확인 실패: 투명 복구 시작 줄 없음",
              "config_no_ua": "설정 확인 실패: abort 단어 줄 없음", "config_knobs": "설정 확인 실패: 시험 스위치 줄이 셀과 다름",
              "config_mute": "설정 확인 실패: 끊김 줄이 셀과 다름", "config_inj_ctx": "설정 확인 실패: 훅의 문맥 지정이 셀과 다름",
              "config_rules_left": "설정 확인 실패: iptables 규칙이 시행 뒤 남음", "surplus": "계획 수를 넘은 시행"}


def status_of(r):
    val = s2.val
    cell, build = r["cell"], r["build"]
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
    if cell in KILL_R0 and str(r.get("r0_killed")) != "1":
        return "no_kill0"
    if cell == "ow_r0in_f1r1_b":  # as gin-oneway: rank 1 lost its socket before its fault
        c1, q = val(r.get("close1_ms_r1")), val(r.get("q4_ms_r1"))
        if not isinstance(c1, float) or (isinstance(q, float) and q < c1):
            return "cond_order"
    if cell in ("rc_mutekill_b", "ow_kill0_b"):  # the surviving rank lost its socket in the mute (a fault may never come)
        rk = 0 if cell == "rc_mutekill_b" else 1
        c, q = val(r.get("close1_ms_r%d" % rk)), val(r.get("q4_ms_r%d" % rk))
        if not isinstance(c, float) or (isinstance(q, float) and q < c):
            return "cond_order"
    if cell == "hd_rround_f1_b":  # the peer's reset came inside rank 0's round (after its fault, within the 4 s stall)
        x = val(r.get("r1close_after_q4_ms"))
        if not isinstance(x, float) or not (0 < x < 4000):
            return "cond_order"
    if cell == "hdp_mute_b" and str(r.get("mute_applied")) != "1":
        return "mute_not_applied"
    # ---- configuration (a failure here stops the block, EXPERIMENT.md 8)
    if val(r.get("left_rules")) not in (0.0,) and r.get("left_rules") not in ("", None):
        return "config_rules_left"
    ranks = (0,) if cell in KILL_R1 else (1,) if cell in KILL_R0 else (0, 1)  # the killed rank has no full log
    for rk in ranks:
        hd_on, prod = str(r.get("hd_on_r%d" % rk)), str(r.get("prod_r%d" % rk))
        ow_mode = str(r.get("ow_mode_r%d" % rk))
        if build == "hd" and not (hd_on == "1" and prod == "0" and ow_mode == "1"):
            return "config_build"
        if build == "hdp" and not (hd_on == "0" and str(r.get("rs_api_r%d" % rk)) == "1"
                                   and val(r.get("rs_contexts_r%d" % rk)) >= 1):
            return "config_build"
        if build in ("ow", "ow2") and not (hd_on == "0" and ow_mode == "1"):
            return "config_build"
        if build == "stk" and not (hd_on == "0" and ow_mode == "" and val(r.get("ts_on_r%d" % rk)) == 0):
            return "config_build"
        if build in ("hd", "ow", "ow2"):
            if not val(r.get("ts_on_r%d" % rk)) >= 1:
                return "config_ts_off"
            if not val(r.get("ua_r%d" % rk)) >= 1:
                return "config_no_ua"
    kn = KNOBS.get(cell, (None, None))
    for rk in (0, 1):
        if rk not in ranks:
            continue
        got = (str(r.get("knob_uto_r%d" % rk)), str(r.get("knob_refuse_r%d" % rk)))
        exp = kn[rk]
        if (exp is None and got != ("", "")) or (exp is not None and got != exp):
            return "config_knobs"
    if build == "hd":
        hk = HKNOBS.get(cell)
        for rk in ranks:
            cols = ["hk_gap", "hk_badnonce", "hk_fwdelay", "hk_copystall", "hk_badrepost"]
            want = {c: "" for c in cols}
            if hk and hk[0] == rk:
                want = {c: None for c in cols}  # the line is there: only the named switch is checked
                want[hk[1]] = hk[2]
            if cell == "hd_fwslow_f1_b" and rk == 0:
                want = {c: None for c in cols}
                want["hk_fwdelay"] = "8000@commit"
            for c, v in want.items():
                if v is not None and str(r.get("%s_r%d" % (c, rk))) != v:
                    return "config_knobs"
    if cell in MUTES:
        m0, m1 = MUTES[cell]
        n0, n1 = val(r.get("n_mute_on_r0")), val(r.get("n_mute_on_r1"))
        if (m0 and 0 in ranks and not n0 >= 1) or (not m0 and n0 != 0) or (m1 and 1 in ranks and not n1 >= 1) or \
           (not m1 and n1 != 0):
            return "config_mute"
    elif build in ("hd", "ow", "ow2") and (val(r.get("n_mute_on_r0")) != 0 or val(r.get("n_mute_on_r1")) != 0):
        return "config_mute"
    if cell == "ow_r0in_f1r1_b" and str(r.get("inj_ctx_r1")) != "1":
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
            r.update({k: ("" if v is None else v) for k, v in extra_hd(stem, r.get("fault_mono_r0")).items()})
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
    frozen = open(os.path.join(HERE, "PREREG.txt")).read() if os.path.exists(os.path.join(HERE, "PREREG.txt")) else ""
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
    L = ["# gin-harden 채점 결과", "",
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
