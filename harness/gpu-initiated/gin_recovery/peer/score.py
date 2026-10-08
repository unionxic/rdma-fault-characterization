#!/usr/bin/env python3
"""gin-peer scorer: applies the acceptance rules of predictions.csv to a results folder and writes
<resultsdir>/SCORE.md and <resultsdir>/trials_scored.csv. The pilot (its own results folder) is never passed here.

usage: score.py <resultsdir>          (e.g. results/<date>)

Steps (EXPERIMENT.md 3 and 8):
  1. two-rank trial folders (hq/, hf/, hqp/, hfp/): ../scripts/ts2/rows.py -> trials_<sub>.csv, then the columns of
     ../s2_close/rows_extra.py, ../pair_check/rows_pc.py, ../oneway/rows_ow.py, ../harden/rows_hd.py,
     ../handoff/rows_hf.py and this folder's rows_pq.extra_pq2(); N-rank trial folders (mr_hq/, mr_hf/):
     ../multirank/rows_mr.rows_of() per trial, then rows_pq.extra_pq4();
  2. each trial gets its cell key cell@build (N-rank: build = the libnccl key, LIB) and a status: scored, excluded
     (section 8), config (a section 8 configuration check failed: the block stops) or surplus (non-excluded trials
     beyond the planned count; the first ones by trial number are scored);
  3. every prediction is evaluated on the scored trials with the grammar of ../s2_close/EXPERIMENT.md 3.2, using the
     evaluation functions of ../s2_close/score.py unchanged; a prediction whose cells have fewer scored trials than
     planned is "자료 부족". The pseudo cell all@all holds every trial of the folder, whatever its status (Q1).
"""
import csv, glob, hashlib, importlib.util, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
UP = os.path.join(HERE, "..")
ROWS = os.path.join(UP, "scripts", "ts2", "rows.py")
_spec = importlib.util.spec_from_file_location("s2close_score", os.path.join(UP, "s2_close", "score.py"))
s2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s2)  # grammar: evaluate, val, NIL, keys_of (also puts ../s2_close on sys.path for rows_extra)
from rows_extra import extra  # noqa: E402  (../s2_close/rows_extra.py)
for sub in ("pair_check", "oneway", "harden", "handoff", "multirank"):
    sys.path.insert(0, os.path.join(UP, sub))
from rows_pc import extra_pc  # noqa: E402
from rows_ow import extra_ow  # noqa: E402
from rows_hd import extra_hd  # noqa: E402
from rows_hf import extra_hf  # noqa: E402
from rows_mr import rows_of  # noqa: E402
sys.path.insert(0, HERE)
from rows_pq import extra_pq2, extra_pq4  # noqa: E402

# section 7: planned scored trials per cell key (latency cells: runs)
PLANNED = {
    "pq_repost_r1_b@hq": 10, "pq_repost_r1_b@hf": 5, "hd_repost_f1_b@hq": 5, "hd_fwslow_f1_b@hq": 5,
    "pq_ackrace_f1_b@hq": 10, "pq_ackrace_f1_b@hf": 5, "pq_ackrace_f1r1_b@hq": 5, "pq_ackrace_f1r1_b@hf": 5,
    "pq_copystall_shrink_b@hq": 10, "pq_copystall_shrink_b@hf": 5, "pq_copystall1_shrink_b@hq": 5, "hd_shrink_b@hq": 5,
    "pq_rdv_b@hq": 5, "hdp_kill_b@hqp": 5,
    "mr4_kill3_peer@hq": 10, "mr4_kill3_peer@hf": 5, "mr4_kill3@hq": 5, "pq4_fwslow@hq": 10, "pq4_fwslow@hf": 5,
    "pq4_kill3_shrink@hq": 10, "pq4_local_shrink@hq": 5, "pq4_local_shrink@hf": 5, "pq4_rdv@hq": 3,
    "mr4_none@hq": 5, "mr4_f1_01@hq": 5, "all@all": 0}
for c in ("f1_b", "f3_b", "bidirf_sym_b", "f4_b", "f2rel_b", "hd_rxdeath_b"):
    PLANNED[f"{c}@hq"] = 5
for sz in ("4k", "256k"):
    for b in ("hqp", "hfp"):
        PLANNED[f"lat_{sz}@{b}"] = 5
# section 8: hooks that must fire, kills that must happen (two ranks)
HOOK_R0 = {"f1_b", "pq_repost_r1_b", "hd_repost_f1_b", "hd_fwslow_f1_b", "pq_ackrace_f1_b", "pq_copystall_shrink_b",
           "pq_copystall1_shrink_b", "pq_rdv_b"}
HOOK_R1 = {"f3_b", "pq_ackrace_f1r1_b"}
HOOK_BOTH = {"bidirf_sym_b"}
KILL_R1 = {"f4_b", "hd_shrink_b", "hdp_kill_b"}
KILL_R0 = {"hd_rxdeath_b"}
# N ranks: the hook fires each cell must show (rank:context), the kill cells
FIRES4 = {"mr4_f1_01": "0:0", "pq4_fwslow": "0:0;2:6", "pq4_local_shrink": "0:0"}
KILL4 = {"mr4_kill3", "mr4_kill3_peer", "pq4_kill3_shrink"}
# the test switch lines each cell must show (two ranks: ../harden/rows_hd.py hk_* columns, rank: column: value) and
# the cells whose subject is a firmware overrun (excluded from the overrun exclusion)
KNOBS2 = {"pq_repost_r1_b": {(1, "hk_badrepost"): "1"}, "hd_repost_f1_b": {(0, "hk_badrepost"): "1"},
          "hd_fwslow_f1_b": {(0, "hk_fwdelay"): "8000@commit"},
          "pq_copystall_shrink_b": {(0, "hk_copystall"): "4000"}, "pq_copystall1_shrink_b": {(1, "hk_copystall"): "4000"}}
MUTED = {"pq_ackrace_f1_b": 0, "pq_ackrace_f1r1_b": 1}  # the rank whose helper sockets are muted (test switch)
FW_CELLS = {"hd_fwslow_f1_b", "pq4_fwslow"}

LABEL = {
    "A1": "응답 쪽(rank 1)이 커밋과 ACK 전에 다시 보내기 계획을 거부하면(NACK 15) rank 0은 계획도 세우지 않고, 어느 rank도 복구 줄이 없으며 둘 다 거절",
    "A2": "대조(gin-handoff): 응답 쪽은 DONE 뒤에야 거부해, rank 0은 이미 다시 보내고 복구 줄을 남긴 뒤 거절",
    "A3": "시작 쪽(rank 0)이 둘째 QP의 계획을 거부하면 아무도 다시 보내지 않고 둘 다 거절(회귀, 역할 제외 없이)",
    "B1": "랭크 2개, 8 s commit 단계: 감시가 3.0-3.5 s에 한 번 발동해 대기를 오류로 풀고, abort가 6 s 안에 돌아오며 rank 1이 거절(회귀)",
    "B2": "랭크 4개: rank 0의 rank 1 라운드가 commit 단계를 넘기면 그 상대만 거절되고, 뒤의 rank 2와 rank 0 라운드는 복구됨",
    "B3": "그때 올라간 단어는 그 두 rank의 상대별 단어뿐이고 devComm 단어는 아무도 올리지 않음",
    "B4": "간선 0>1, 1>0 말고는 모든 간선이 정상으로 끝남",
    "B5": "대조(gin-handoff): 초과가 영구라 rank 0이 rank 2의 라운드를 \"감시가 이미 드러냄\"으로 거절하고 rank 0의 다른 간선이 실패",
    "K1": "랭크 4개, rank 3 kill, 상대별 flush: 살아남은 세 rank 사이 간선 6개가 모두 정상으로 끝남",
    "K2": "살아남은 rank마다 rank 3만 죽음 원인으로 거절하고 rank 3의 단어만 올리며 devComm 단어는 올리지 않음",
    "K3": "rank 3으로 가는 간선은 보내는 쪽이 실패하고, rank 3에서 오는 받기는 일찍 풀리지 않고 자기 한도로 끝나며, 세 rank 모두 비동기 오류를 봄",
    "K4": "대조(gin-handoff): 살아남은 rank 사이 받는 쪽 6개가 실패하고 보내는 쪽은 끝까지 감(gin-multirank K5)",
    "K5": "문맥 전체 flush: 살아남은 rank의 보내는 쪽 6개는 여전히 실패하고, 받는 쪽 6개는 일찍 풀리지 않고 자기 한도로 끝남",
    "H1": "rank 0의 원인(복사 상한 초과)으로 rank 1을 거절한 뒤, 살아 있는 rank 1을 빼는 중단 shrink는 순정 답을 지키고 원인 local을 적음",
    "H2": "대조(gin-handoff): 같은 shrink가 넘어가 1-rank communicator와 맞는 allreduce를 돌려줌",
    "H3": "원인이 rank 1(응답 쪽 복사)이면 rank 0의 원인은 peer-reported이고 shrink가 넘어감",
    "H4": "상대가 죽은 경우 원인은 peer-dead이고 shrink가 gin-handoff처럼 넘어감(회귀)",
    "H5": "랭크 4개, rank 3 kill: 살아남은 세 rank의 shrink가 모두 넘어가고, 3-rank 아이가 자기 devComm을 열어 간선 6개가 모두 정상",
    "H6": "랭크 4개: rank 0의 원인이 local이면 rank 0의 shrink는 순정 답을 지키고 아이가 생기지 않음",
    "H7": "(한계) 자기 확인을 통과한 rank 2, 3은 rank 0을 기다리다 단계 한도에서 끝남",
    "H8": "대조(gin-handoff): 원인이 local이어도 rank 0이 넘어가고 세 rank 모두 3-rank 아이를 얻음",
    "C1": "ACK를 기다리다 취소한 rank 0의 다시 걸기에, 이미 커밋하고 거절한 rank 1이 FAIL로 답하고 rank 0은 끊김 끝 1.5 s 안에 거절",
    "C2": "대조(gin-handoff): rank 1이 다시 걸기를 닫아 rank 0은 재연결 한도를 다 쓰고 끊김 끝 5 s 이상 뒤 \"모름\"으로 거절",
    "C3": "같은 경합을 rank 1이 시작한 경우: rank 0이 확인 접속에 FAIL로 답하고 rank 1이 끊김 끝 1.5 s 안에 거절",
    "C4": "대조(gin-handoff): rank 0이 확인 접속에 답만 하고 다시 걸지 않아 rank 1은 끊김 끝 5 s 이상 뒤 \"모름\"으로 거절",
    "Q1": "본 실행의 어떤 시행도 랑데부 포트 bind에 실패하지 않음",
    "Q2": "막아 둔 첫 후보 포트를 건너뛰고, rank 1이 가짜 수신 대기에 한 바이트도 보내지 않고 거부하며, 두 rank가 랑데부를 확인하고 투명",
    "Q3": "랭크 4개에서도 같음(rank 1-3이 가짜를 거부, 네 rank 모두 확인, 투명)",
    "R1": "복구 재현 셀이 그대로 투명",
    "R2": "랭크 2개, 상대 kill: 2 s 안에 죽음 원인으로 거절하고, 유일한 상대라 devComm 단어도 peer-dead로 올라가며 abort가 돌아옴",
    "R3": "랭크 2개, 받기만 하는 rank의 waitSignal이 보내는 쪽 kill 2 s 안에 오류로 풀림(모든 상대가 거절되어 devComm 단어)",
    "R4": "원격 접근 오류를 rank 0이 거절하고 받는 쪽 대기가 오류로 풀리며 abort가 5 s 안에 돌아옴",
    "R5": "운영 빌드가 kill된 상대를 2 s 안에 죽음으로 거절하고 죽음 1을 세며 WARN에 정보성 줄이 없음",
    "R6": "랭크 4개, 장애 없음과 한 쌍의 로컬 QP 오류가 투명",
    "R7": "통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0을 셈",
    "P1": "4 KiB 지연: 이 실험의 운영 빌드와 gin-handoff 운영 빌드 차이 0.40 µs 이하",
    "P2": "256 KiB 지연: 차이 0.30 µs 이하",
}
EXCL_LABEL = {"bind": "드라이버 랑데부 포트 bind 실패", "no_fault": "장애 미적용(훅 발사 없음)", "trigger_miss": "트리거 미도달",
              "no_kill": "kill 기록 없음", "no_kill0": "rank 0 kill 기록 없음", "no_kill4": "kill 없음 또는 트래픽 밖",
              "cond_role": "순서 미적용: 계획을 거부한 rank 1이 시작 쪽",
              "cond_race": "순서 미적용: ACK 기다림 중 취소와 응답 쪽의 커밋 뒤 거절이 함께 생기지 않음",
              "cond_copy": "조건 미적용: 셀의 복사 상한 초과가 없음", "cond_fw": "조건 미적용: 펌웨어 단계 초과가 없음",
              "fw_overrun": "펌웨어 명령 하나가 NCCL_GIN_TS_FW_MS를 넘음(이 셀의 주제가 아님)",
              "config_build": "설정 확인 실패: 빌드 시작 줄이 빌드와 다름", "config_ts_off": "설정 확인 실패: 투명 복구 시작 줄 없음",
              "config_no_ua": "설정 확인 실패: abort 단어 줄 없음", "config_knobs": "설정 확인 실패: 시험 스위치 줄이 셀과 다름",
              "config_mute": "설정 확인 실패: 끊김 줄이 셀과 다름", "surplus": "계획 수를 넘은 시행"}


def num(x):
    v = s2.val(x)
    return v if isinstance(v, float) else None


def status2(r):  # two ranks
    cell, build = r["cell"], r["build"]
    if r.get("bind_fail") in ("1", 1):
        return "bind"
    n0, n1 = num(r.get("n_fires_r0")), num(r.get("n_fires_r1"))
    if cell in HOOK_R0 and not n0:
        return "no_fault"
    if cell in HOOK_R1 and not n1:
        return "no_fault"
    if cell in HOOK_BOTH and not (n0 and n1):
        return "no_fault"
    if (num(r.get("trigger_miss")) or 0) > 0:
        return "trigger_miss"
    if cell in KILL_R1 and str(r.get("killed")) != "1":
        return "no_kill"
    if cell in KILL_R0 and str(r.get("r0_killed")) != "1":
        return "no_kill0"
    if cell == "pq_repost_r1_b" and (num(r.get("n_init_round_r1")) or 0) > 0:
        return "cond_role"
    if cell in MUTED:  # the initiator cancelled while waiting for the ACK, the responder declined after its commit
        i = MUTED[cell]
        rsp = 1 - i
        w = str(r.get(f"declwhy_r{rsp}") or "")
        if not ((num(r.get(f"n_cancel_ack_r{i}")) or 0) >= 1 and
                (w.startswith("peer closed the socket before DONE") or w.startswith("DONE timeout") or
                 w.startswith("cannot send ACK"))):
            return "cond_race"
    if cell == "pq_copystall_shrink_b" and not (num(r.get("n_copyto_r0")) or 0) >= 1:
        return "cond_copy"
    if cell == "pq_copystall1_shrink_b" and not (num(r.get("n_copyto_r1")) or 0) >= 1:
        return "cond_copy"
    if cell == "hd_fwslow_f1_b" and not ((num(r.get("n_fwover_r0")) or 0) + (num(r.get("n_fwold_r0")) or 0)) >= 1:
        return "cond_fw"
    if cell not in FW_CELLS and any((num(r.get(c)) or 0) > 0 for c in ("n_fwover_r0", "n_fwover_r1", "n_fwold_r0",
                                                                         "n_fwold_r1", "rs_fw_overruns_r0", "rs_fw_overruns_r1")):
        return "fw_overrun"
    # ---- configuration (a failure here stops the block)
    ranks = (0,) if cell in KILL_R1 else (1,) if cell in KILL_R0 else (0, 1)
    for rk in ranks:
        hd_on, prod, hf_on = str(r.get(f"hd_on_r{rk}")), str(r.get(f"prod_r{rk}")), str(r.get(f"hf_on_r{rk}"))
        pq_on = num(r.get(f"pq_on_r{rk}")) or 0
        if build == "hq" and not (hd_on == "1" and prod == "0" and hf_on == "1" and pq_on >= 1):
            return "config_build"
        if build == "hf" and not (hd_on == "1" and prod == "0" and hf_on == "1" and pq_on == 0):
            return "config_build"
        if build in ("hqp", "hfp") and not (hd_on == "0" and hf_on == "0" and pq_on == 0 and
                                             str(r.get(f"rs_api_r{rk}")) == "1" and (num(r.get(f"rs_contexts_r{rk}")) or 0) >= 1):
            return "config_build"
        if build in ("hq", "hf"):
            if not (num(r.get(f"ts_on_r{rk}")) or 0) >= 1:
                return "config_ts_off"
            if not (num(r.get(f"ua_r{rk}")) or 0) >= 1:
                return "config_no_ua"
            want = KNOBS2.get(cell, {})
            for c in ("hk_gap", "hk_badnonce", "hk_fwdelay", "hk_copystall", "hk_badrepost"):
                got = str(r.get(f"{c}_r{rk}") or "")
                exp = want.get((rk, c), "")
                if got in ("None",):
                    got = ""
                if got != exp and not (exp == "" and got in ("", "0", "-1", "-1:0", "0@-")):  # unset values of the line
                    return "config_knobs"
            muted = (num(r.get(f"n_mute_on_r{rk}")) or 0) > 0
            if muted != (MUTED.get(cell) == rk):
                return "config_mute"
    return "candidate"


def status4(r):  # N ranks
    cell, build = r["cell"], r["build"]
    n = int(r.get("n") or 0)
    if str(r.get("bind_fail")) == "1":
        return "bind"
    if cell in FIRES4 and (r.get("fires") != FIRES4[cell] or str(r.get("fire_in_traffic")) != "1"):
        return "no_fault"
    if cell in KILL4 and not (str(r.get("killed")) == "1" and str(r.get("kill_in_traffic")) == "1"):
        return "no_kill4"
    if cell == "pq4_local_shrink" and not (num(r.get("n_copy_to")) or 0) >= 1:
        return "cond_copy"
    if cell == "pq4_fwslow" and not ((num(r.get("n_fwover")) or 0) + (num(r.get("n_fwold")) or 0)) >= 1:
        return "cond_fw"
    if cell not in FW_CELLS and ((num(r.get("n_fwover")) or 0) + (num(r.get("n_fwold")) or 0) +
                                 (num(r.get("n_fw_over")) or 0)) > 0:
        return "fw_overrun"
    if str(r.get("init_fail")) == "1":
        return "candidate"  # scored as it is (transparent_ok etc. fail)
    if not (num(r.get("n_ts_on")) or 0) >= n:  # >= n: a child devComm adds its own lines
        return "config_ts_off"
    if not (num(r.get("n_ua")) or 0) >= n:
        return "config_no_ua"
    pq_on = num(r.get("n_pq_on")) or 0
    if build == "hq" and pq_on != n:
        return "config_build"
    if build == "hf" and pq_on != 0:
        return "config_build"
    return "candidate"


def main():
    R = os.path.abspath(sys.argv[1])
    subs = sorted(d for d in os.listdir(R) if os.path.isdir(os.path.join(R, d)) and glob.glob(os.path.join(R, d, "*_meta.txt")))
    trials = []
    for sub in subs:
        if sub.startswith("mr_"):
            for meta in sorted(glob.glob(os.path.join(R, sub, "*_meta.txt"))):
                stem = meta[: -len("_meta.txt")]
                r = {k: ("" if v is None else v) for k, v in rows_of(stem).items()}
                r.update({k: ("" if v is None else v) for k, v in extra_pq4(stem, r).items()})
                r["build"] = r.get("lib", "")
                r["sub"] = sub
                r["kind"] = "n"
                trials.append(r)
            continue
        out = os.path.join(R, f"trials_{sub}.csv")
        subprocess.run([sys.executable, ROWS, os.path.join(R, sub), "--out", out], check=True, stderr=subprocess.DEVNULL)
        for r in csv.DictReader(open(out)):
            stem = os.path.join(R, sub, r["stem"])
            r.update({k: ("" if v is None else v) for k, v in extra(r, stem).items()})
            r.update({k: ("" if v is None else v) for k, v in extra_pc(stem).items()})
            r.update({k: ("" if v is None else v) for k, v in extra_ow(stem).items()})
            r.update({k: ("" if v is None else v) for k, v in extra_hd(stem, r.get("fault_mono_r0")).items()})
            r.update({k: ("" if v is None else v) for k, v in extra_hf(stem).items()})
            r.update({k: ("" if v is None else v) for k, v in extra_pq2(stem).items()})
            r["sub"] = sub
            r["kind"] = "2"
            trials.append(r)
    for r in trials:
        r["key"] = f'{r["cell"]}@{r["build"]}'
        m = re.search(r"n(\d+)$", r.get("trial") or "")
        r["tnum"] = int(m.group(1)) if m else 0
        r["status"] = status4(r) if r["kind"] == "n" else status2(r)
    by_key = {}
    for r in sorted(trials, key=lambda x: (x["key"], x["tnum"], x["sub"])):
        by_key.setdefault(r["key"], []).append(r)
    scored = {}
    for k, rs in by_key.items():
        cand = [r for r in rs if r["status"] == "candidate"]
        for i, r in enumerate(cand):
            r["status"] = "scored" if i < PLANNED.get(k, 0) else "surplus"
        scored[k] = [r for r in rs if r["status"] == "scored"]
    scored["all@all"] = list(trials)  # Q1: every trial of the folder, whatever its status
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
    cols = ["key", "status", "kind", "sub", "stem", "cell", "build", "trial"]
    for r in trials:
        for c in r:
            if c not in cols:
                cols.append(c)
    with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(trials, key=lambda x: (x["sub"], x["key"], x["tnum"])):
            w.writerow(r)
    L = ["# gin-peer 채점 결과", "",
         f"`score.py`가 원자료(`{os.path.relpath(R, HERE)}/`의 시행 파일)에서 만들었다. 손으로 고친 값은 없다.", "",
         f"- 예측 파일 sha256: `{sha}`. `PREREG.txt`의 값과 {'같다' if sha in frozen else '다르다(확인 필요)'}.",
         f"- 시행 수(모든 hold): {len(trials)}. 판정한 시행: {sum(len(v) for k, v in scored.items() if k != 'all@all')}.",
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
    for k in sorted(set(list(by_key.keys()) + [x for x in PLANNED.keys() if x != "all@all"])):
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
