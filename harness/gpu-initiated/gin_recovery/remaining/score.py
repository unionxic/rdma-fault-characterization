#!/usr/bin/env python3
"""gin-remaining scorer: applies the acceptance rules of predictions.csv to a results folder and writes
<resultsdir>/SCORE.md and <resultsdir>/trials_scored.csv. The pilot (its own results folder) is never scored; the same
script may be run on a copy of it to read the columns.

usage: score.py <resultsdir>          (e.g. results/<date>)

Steps (EXPERIMENT.md 3 and 8), as ../peer/score.py:
  1. two-rank trial folders (hr/, hq/, hrp/, hqp/): ../scripts/ts2/rows.py -> trials_<sub>.csv, then the columns of
     ../s2_close/rows_extra.py, ../pair_check/rows_pc.py, ../oneway/rows_ow.py, ../harden/rows_hd.py, ../handoff/rows_hf.py,
     ../peer/rows_pq.extra_pq2() and this folder's rows_hr.extra_hr2(); N-rank trial folders (mr_hr/, mr_hq/):
     ../multirank/rows_mr.rows_of() per trial, then rows_pq.extra_pq4() and rows_hr.extra_hr4(); the benchmark folder
     (bench/): rows_hr.bench_row(); the NIC gate test folder (ngt/): rows_hr.ngt_row();
  2. each trial gets its cell key cell@build (N-rank: build = the libnccl key, LIB) and a status: scored, excluded
     (section 8), config (a section 8 configuration check failed: the block stops) or surplus (non-excluded trials beyond
     the planned count; the first ones by trial number are scored);
  3. every prediction is evaluated on the scored trials with the grammar of ../s2_close/EXPERIMENT.md 3.2, using the
     evaluation functions of ../s2_close/score.py unchanged; a prediction whose cells have fewer scored trials than planned
     is "자료 부족".
"""
import csv, glob, hashlib, importlib.util, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
UP = os.path.join(HERE, "..")
ROWS = os.path.join(UP, "scripts", "ts2", "rows.py")
_spec = importlib.util.spec_from_file_location("s2close_score", os.path.join(UP, "s2_close", "score.py"))
s2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s2)  # grammar: evaluate, val, NIL, keys_of (also puts ../s2_close on sys.path for rows_extra)
from rows_extra import extra  # noqa: E402  (../s2_close/rows_extra.py)
for sub in ("pair_check", "oneway", "harden", "handoff", "multirank", "peer"):
    sys.path.insert(0, os.path.join(UP, sub))
from rows_pc import extra_pc  # noqa: E402
from rows_ow import extra_ow  # noqa: E402
from rows_hd import extra_hd  # noqa: E402
from rows_hf import extra_hf  # noqa: E402
from rows_mr import rows_of  # noqa: E402
from rows_pq import extra_pq2, extra_pq4  # noqa: E402
sys.path.insert(0, HERE)
from rows_hr import extra_hr2, extra_hr4, bench_row, ngt_row  # noqa: E402

# section 7: planned scored trials per cell key (latency cells: runs; the benchmark: runs, each on both nodes)
PLANNED = {
    "rh_hog_f1_b@hr": 10, "rh_hog_f1_b@hq": 5, "rh_hog_copystream_f1_b@hr": 5,
    "hdp_kill_b@hrp": 5,
    "mr4_cyc_stall@hr": 10, "mr4_cyc_stall@hq": 5, "mr4_chain_stall@hr": 5,
    "rm4_kill3_untimed@hr": 10, "rm4_kill3_untimed@hq": 5, "mr4_kill3_peer@hr": 5,
    "mr4_none@hr": 5, "mr4_f1_01@hr": 5, "hm_bench@hr": 5, "nic_gate@hr": 5}
for c in ("load", "malloc", "stream"):
    PLANNED[f"rh_hogcall_{c}_f1_b@hq"] = 5
    PLANNED[f"rh_hogcall_{c}_f1_b@hr"] = 3
for c in ("f1_b", "f3_b", "bidirf_sym_b", "f4_b", "f2rel_b", "hd_rxdeath_b"):
    PLANNED[f"{c}@hr"] = 5
for sz in ("4k", "256k"):
    for b in ("hrp", "hqp"):
        PLANNED[f"lat_{sz}@{b}"] = 5
# section 8: hooks that must fire, kills that must happen (two ranks)
HOG = {"rh_hog_f1_b", "rh_hog_copystream_f1_b", "rh_hogcall_load_f1_b", "rh_hogcall_malloc_f1_b", "rh_hogcall_stream_f1_b"}
HOG_CALLS = {"rh_hog_f1_b": "load,malloc,stream", "rh_hog_copystream_f1_b": "load,malloc,stream",
             "rh_hogcall_load_f1_b": "load", "rh_hogcall_malloc_f1_b": "malloc", "rh_hogcall_stream_f1_b": "stream"}
HOOK_R0 = {"f1_b"} | HOG
HOOK_R1 = {"f3_b"}
HOOK_BOTH = {"bidirf_sym_b"}
KILL_R1 = {"f4_b", "hdp_kill_b"}
KILL_R0 = {"hd_rxdeath_b"}
STREAM_CELLS = {"rh_hog_copystream_f1_b"}  # hr cells whose copy path is the stream (NCCL_GIN_TS_COPY_PATH=stream)
# N ranks: the hook fires each cell must show (rank:context), the kill cells, the stall switch of the cycle and chain
FIRES4 = {"mr4_f1_01": "0:0", "mr4_cyc_stall": "0:0;1:4;2:6", "mr4_chain_stall": "0:0;1:4"}
KILL4 = {"rm4_kill3_untimed", "mr4_kill3_peer"}
STALL4 = {"mr4_cyc_stall": "0:300;1:300;2:300", "mr4_chain_stall": "0:300;1:300"}
ORDER4 = {"mr4_cyc_stall", "mr4_chain_stall"}

LABEL = {
    "CY1": "순환하는 세 시작 쪽(0>1, 1>2, 2>0)이 handshake timeout도 거절도 없이 복구되고, 모든 간선이 정상이며, 세 쌍 모두 시작 쪽 복구 줄을 남김",
    "CY2": "순환의 마지막 복구가 첫 라운드 줄 5000 ms 안에 끝남",
    "CY3": "적어도 한 REQ를 다른 라운드의 ACK 기다림 안에서 답함(순환을 끊은 것이 시간 초과가 아니라 새 규칙)",
    "CY4": "대조(gin-peer 라이브러리): 순환이 여전히 ACK 한도까지 기다려 라운드 시작 24.3-24.8 s 뒤 handshake timeout으로 거절, 투명 아님",
    "CY5": "순환이 없는 사슬(0>1, 1>2)은 그대로 투명하고 5000 ms 안에 끝남(회귀)",
    "DG1": "rank 3 kill, 모든 받기 대기에 시간 제한 없음: 생존 rank마다 rank 3에서 오는 받기가 그 rank의 죽음 판정 2000-3000 ms 뒤 오류로 풀림",
    "DG2": "생존 rank마다 word [0]의 degraded 해제 줄이 하나, 죽음 판정 줄 2000-2500 ms 뒤",
    "DG3": "생존 rank 사이의 상대별 보내기(put + flushAsync(peer) + wait)가 모두 끝나고, 생존 rank의 커널이 모두 끝남",
    "DG4": "대가: 죽음 2 s 뒤에도 기다리던 생존 rank 사이의 받기도 모두 오류로 풀림(waitSignal은 누구의 신호를 기다리는지 모름)",
    "DG5": "대조(gin-peer 라이브러리): rank 3에서 오는 받기가 풀리지 않고, application이 비동기 오류 15 s 뒤 포기할 때까지 생존 rank의 커널이 돎",
    "DG6": "gin-peer의 셀(받기 한도 10 s)을 hr로: 생존 rank의 보내기는 모두 성공, 받기는 한도가 아니라 degraded 단어로 실패, 생존 rank마다 degraded 줄",
    "GR1": "gin-handoff 순서(GIN 실행 뒤 첫 커널 적재, cudaMalloc, 스트림 생성; GPU 가득): 복사가 모두 NIC로 가고 복사 시간 초과 없이 투명하게 복구",
    "GR2": "그래도 CUDA 스트림은 묶여 있었음: 두 rank 모두 새 스트림 확인 복사가 200 ms 안에 하나도 끝나지 않고 GPU 채우기 블록이 하나도 시작하지 않음",
    "GR3": "helper의 장치 상태 복사가 하나도 스트림을 쓰지 않음(정리 때 계수)",
    "GC1": "대조(gin-peer 라이브러리, 같은 드라이버): 라운드의 복사가 시간을 넘겨 거절, 투명 아님",
    "GC2": "hr 안의 대조: NCCL_GIN_TS_COPY_PATH=stream이면 같은 순서에서 복사 시간 초과로 거절",
    "GS1": "GIN 실행 뒤 첫 커널 적재만(cudaMalloc과 스트림은 앞에서): 확인 복사가 묶이고 hq 라운드가 복사 시간 초과로 거절",
    "GS2": "GIN 실행 뒤 cudaMalloc만: 확인 복사가 묶이고 hq 라운드가 복사 시간 초과로 거절",
    "GS3": "GIN 실행 뒤 스트림 생성만: 확인 복사가 200 ms 안에 끝나고 hq 라운드가 투명하게 복구",
    "GS4": "hr은 세 호출 중 어느 하나만 있어도 투명하게 복구",
    "RG1": "복구 재현 셀이 그대로 투명",
    "RG2": "그 라운드들의 장치 상태 복사가 모두 NIC로 감",
    "RG3": "랭크 2개, 상대 kill: 2 s 안에 peer-dead로 거절, 유일한 상대라 word [0]이 바로 peer-dead로 올라감(degraded 예약 없음)",
    "RG4": "랭크 2개, 받기만 하는 rank의 waitSignal이 보내는 쪽 kill 2 s 안에 오류로 풀림",
    "RG5": "원격 접근 오류: rank 0 거절, rank 1 대기 오류 해제, abort 5 s 안",
    "RG6": "운영 빌드, 상대 kill: 2 s 안에 거절, 죽음 1, WARN에 정보성 줄 없음",
    "RG7": "통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0",
    "RG8": "랭크 4개, 장애 없음과 한 쌍의 로컬 QP 오류가 투명",
    "LT1": "4 KiB 지연: 이 실험의 운영 빌드와 gin-peer 운영 빌드 차이 0.40 µs 이하",
    "LT2": "256 KiB 지연: 차이 0.30 µs 이하",
    "HB1": "두 플랫폼 모두 호스트 원자 연산을 기본으로 지원하지 않음(cudaDevAttrHostNativeAtomicSupported = 0)",
    "HB2": "호스트 매핑 메모리의 원자적 더하기가 장치 메모리보다 400 ns 이상 느림(두 GPU 모두)",
    "HB3": "경합 단계가 정상으로 끝나고 개수 절반의 장치 갱신을 잃지 않음",
    "NG1": "NIC 루프백의 4 B 에폭 쓰기와 SM 64비트 원자 연산: 두 GPU 모두 쓰기 손실, 개수 손실, Dekker 위반, 정지 시간 초과가 없음",
}
EXCL_LABEL = {"bind": "드라이버 랑데부 포트 bind 실패", "no_fault": "장애 미적용(훅 발사 없음)", "trigger_miss": "트리거 미도달",
              "no_kill": "kill 기록 없음", "no_kill0": "rank 0 kill 기록 없음", "no_kill4": "kill 없음 또는 트래픽 밖",
              "cond_window": "조건 미적용: rank 0의 장애가 GPU 채우기 커널의 3 s 창 밖",
              "cond_order": "순서 미적용: 순환/사슬 라운드 시작의 퍼짐이 비었거나 250 ms 초과",
              "fw_overrun": "펌웨어 명령 하나가 NCCL_GIN_TS_FW_MS를 넘음(이 실험의 주제가 아님)",
              "bench_fail": "벤치마크 실행이 0이 아닌 코드로 끝남",
              "ngt_fail": "NIC 게이트 시험이 끝나지 못함(준비 실패, NIC 요청 실패, CUDA 오류, 감시 종료)",
              "config_build": "설정 확인 실패: 빌드 시작 줄이 빌드와 다름", "config_ts_off": "설정 확인 실패: 투명 복구 시작 줄 없음",
              "config_no_ua": "설정 확인 실패: abort 단어 줄 없음", "config_knobs": "설정 확인 실패: 시험 스위치나 셀 설정이 셀과 다름",
              "config_copy": "설정 확인 실패: 복사 경로가 셀과 다름",
              "config_ngt": "설정 확인 실패: NIC 게이트 시험의 GPU MR이 dmabuf가 아니거나 루프백 GID가 link-local이 아님",
              "config_driver": "설정 확인 실패: 드라이버 번들이 셀과 다름",
              "surplus": "계획 수를 넘은 시행"}


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
    if cell in HOG:  # rank 0's fault must come while the GPU-filling kernel is meant to run (3 s from its launch)
        f, h = num(r.get("fault_after_launch_r0_ms")), num(r.get("hog_launch_after_launch_ms_r0"))
        if not (f is not None and h is not None and h < f < h + 3000):
            return "cond_window"
    if any((num(r.get(c)) or 0) > 0 for c in ("n_fwover_r0", "n_fwover_r1", "n_fwold_r0", "n_fwold_r1", "rs_fw_overruns_r0",
                                              "rs_fw_overruns_r1")):
        return "fw_overrun"
    # ---- configuration (a failure here stops the block)
    want_drv = "hr" if build in ("hr", "hq") else build
    if str(r.get("drvkey") or "") != want_drv:
        return "config_driver"
    ranks = (0,) if cell in KILL_R1 else (1,) if cell in KILL_R0 else (0, 1)
    for rk in ranks:
        hd_on, prod, hf_on = str(r.get(f"hd_on_r{rk}")), str(r.get(f"prod_r{rk}")), str(r.get(f"hf_on_r{rk}"))
        pq_on = num(r.get(f"pq_on_r{rk}")) or 0
        hr_on = num(r.get(f"hr_on_r{rk}")) or 0
        if build == "hr" and not (hd_on == "1" and prod == "0" and hf_on == "1" and pq_on >= 1 and hr_on >= 1):
            return "config_build"
        if build == "hq" and not (hd_on == "1" and prod == "0" and hf_on == "1" and pq_on >= 1 and hr_on == 0):
            return "config_build"
        if build in ("hrp", "hqp") and not (hd_on == "0" and hf_on == "0" and pq_on == 0 and hr_on == 0 and
                                             str(r.get(f"rs_api_r{rk}")) == "1" and (num(r.get(f"rs_contexts_r{rk}")) or 0) >= 1):
            return "config_build"
        if build in ("hr", "hq"):
            if not (num(r.get(f"ts_on_r{rk}")) or 0) >= 1:
                return "config_ts_off"
            if not (num(r.get(f"ua_r{rk}")) or 0) >= 1:
                return "config_no_ua"
            for c in ("hk_gap", "hk_badnonce", "hk_fwdelay", "hk_copystall", "hk_badrepost"):  # no test switch in any cell
                got = str(r.get(f"{c}_r{rk}") or "")
                if got not in ("", "None", "0", "-1", "-1:0", "0@-"):
                    return "config_knobs"
            if (num(r.get(f"n_mute_on_r{rk}")) or 0) > 0:
                return "config_knobs"
        if build == "hr":
            want = "stream" if cell in STREAM_CELLS else "nic"
            if str(r.get(f"copy_path_r{rk}")) != want or (want == "nic" and (num(r.get(f"lb_off_r{rk}")) or 0) > 0):
                return "config_copy"
        if cell in HOG and str(r.get(f"hog_calls_after_r{rk}") or "") != HOG_CALLS[cell]:
            return "config_knobs"
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
    if cell in ORDER4:
        sp = num(r.get("cyc_spread_ms"))
        if sp is None or sp > 250:
            return "cond_order"
    if ((num(r.get("n_fwover")) or 0) + (num(r.get("n_fwold")) or 0) + (num(r.get("n_fw_over")) or 0)) > 0:
        return "fw_overrun"
    if str(r.get("init_fail")) == "1":
        return "candidate"  # scored as it is (transparent_ok etc. fail)
    if str(r.get("mrkey")) != "hr":
        return "config_driver"
    if not (num(r.get("n_ts_on")) or 0) >= n:
        return "config_ts_off"
    if not (num(r.get("n_ua")) or 0) >= n:
        return "config_no_ua"
    pq_on, hr_on = num(r.get("n_pq_on")) or 0, num(r.get("n_hr_on")) or 0
    if build == "hr" and not (pq_on == n and hr_on == n):
        return "config_build"
    if build == "hq" and not (pq_on == n and hr_on == 0):
        return "config_build"
    if build == "hr" and not ((num(r.get("n_lb_on")) or 0) >= n and (num(r.get("n_lb_off")) or 0) == 0):
        return "config_copy"
    if str(r.get("knob_stall") or "") != STALL4.get(cell, ""):
        return "config_knobs"
    if cell == "rm4_kill3_untimed" and str(r.get("rx_untimed")) != "1":
        return "config_knobs"
    return "candidate"


def statusb(r):  # the benchmark
    return "candidate" if r.get("rc_rain") == "0" and r.get("rc_sunny") == "0" else "bench_fail"


def statusg(r):  # the NIC gate test: a run that ended with a verdict (exit 0 PASS or 1 FAIL) on both nodes is scored
    ok = all(str(r.get(f"rc_{n}")) in ("0", "1") and r.get(f"ng_result_{n}") in ("PASS", "FAIL") for n in ("rain", "sunny"))
    if not ok:
        return "ngt_fail"
    # configuration (a failure stops the block): the GPU memory registered as the library registers it (dmabuf) and the
    # loopback on the GID the library chose in the pilot (link-local), on both nodes
    if not all(r.get(f"ng_mr_{n}") == "dmabuf" and r.get(f"ng_gid_kind_{n}") == "link-local" for n in ("rain", "sunny")):
        return "config_ngt"
    return "candidate"


def main():
    R = os.path.abspath(sys.argv[1])
    subs = sorted(d for d in os.listdir(R) if os.path.isdir(os.path.join(R, d)) and glob.glob(os.path.join(R, d, "*_meta.txt")))
    trials = []
    for sub in subs:
        if sub in ("bench", "ngt"):
            for meta in sorted(glob.glob(os.path.join(R, sub, "*_meta.txt"))):
                fn = bench_row if sub == "bench" else ngt_row
                r = {k: ("" if v is None else v) for k, v in fn(meta[: -len("_meta.txt")]).items()}
                r["sub"] = sub
                r["kind"] = "b" if sub == "bench" else "g"
                trials.append(r)
            continue
        if sub.startswith("mr_"):
            for meta in sorted(glob.glob(os.path.join(R, sub, "*_meta.txt"))):
                stem = meta[: -len("_meta.txt")]
                r = {k: ("" if v is None else v) for k, v in rows_of(stem).items()}
                r.update({k: ("" if v is None else v) for k, v in extra_pq4(stem, r).items()})
                r.update({k: ("" if v is None else v) for k, v in extra_hr4(stem, r).items()})
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
            r.update({k: ("" if v is None else v) for k, v in extra_hr2(stem).items()})
            r["sub"] = sub
            r["kind"] = "2"
            trials.append(r)
    for r in trials:
        r["key"] = f'{r["cell"]}@{r["build"]}'
        m = re.search(r"n(\d+)$", r.get("trial") or "")
        r["tnum"] = int(m.group(1)) if m else 0
        r["status"] = {"n": status4, "b": statusb, "g": statusg}.get(r["kind"], status2)(r)
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
    L = ["# gin-remaining 채점 결과", "",
         f"`score.py`가 원자료(`{os.path.relpath(R, HERE)}/`의 시행 파일)에서 만들었다. 손으로 고친 값은 없다.", "",
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
