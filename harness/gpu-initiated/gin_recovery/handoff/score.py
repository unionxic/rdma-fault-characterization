#!/usr/bin/env python3
"""gin-handoff scorer: applies the acceptance rules of predictions.csv to a results folder and writes
<resultsdir>/SCORE.md and <resultsdir>/trials_scored.csv.

usage: score.py <resultsdir>          (e.g. results/<date>)

Steps (EXPERIMENT.md 3 and 8):
  1. every build subdirectory with *_meta.txt files (hf/, hfp/, hd/, hdp/) -> ../scripts/ts2/rows.py -> trials_<sub>.csv;
  2. ../s2_close/rows_extra.extra(), ../pair_check/rows_pc.extra_pc(), ../oneway/rows_ow.extra_ow(),
     ../harden/rows_hd.extra_hd() and rows_hf.extra_hf() add the section 3.1 columns from the per-trial files;
  3. each trial gets its cell key cell@build and a status: scored, excluded (section 8: bind failure, fault not applied,
     trigger missed, no kill, the fault outside the GPU-filling kernel's window, a firmware-command overrun), config (a
     section 8 configuration check failed: the block stops), or surplus (non-excluded trials beyond the planned count;
     the first ones by trial number are scored);
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
sys.path.insert(0, os.path.join(HERE, "..", "harden"))
from rows_hd import extra_hd  # noqa: E402  (../harden/rows_hd.py)
sys.path.insert(0, HERE)
from rows_hf import extra_hf  # noqa: E402

# section 7: planned scored trials per cell key (latency cells: runs)
PLANNED = {"hd_shrink_b@hf": 10, "hd_shrink_b@hd": 5, "hd_shrink_b@hfp": 5, "hf_shrinkoff_b@hf": 5,
           "hf_hog_f1_b@hf": 5, "hf_hogslack_f1_b@hf": 10, "hdp_kill_b@hfp": 5}
for c in ("f1_b", "f3_b", "bidirf_sym_b", "f4_b", "f2rel_b", "hd_rxdeath_b"):
    PLANNED[f"{c}@hf"] = 5
for sz in ("4k", "256k"):
    for b in ("hfp", "hdp", "hd"):
        PLANNED[f"lat_{sz}@{b}"] = 5
# section 8: which rank's hook must fire, kills
HOOK_R0 = {"f1_b", "hf_hog_f1_b", "hf_hogslack_f1_b"}
HOOK_R1 = {"f3_b"}
HOOK_BOTH = {"bidirf_sym_b"}
KILL_R1 = {"f4_b", "hd_shrink_b", "hf_shrinkoff_b", "hdp_kill_b"}
KILL_R0 = {"hd_rxdeath_b"}
HOG = {"hf_hog_f1_b", "hf_hogslack_f1_b"}

LABEL = {
    "S1": "죽은 rank를 뺀 중단 shrink가 1-rank 통신기를 돌려주고, 그 allreduce가 맞고, 새 통신기에 비동기 오류가 없음",
    "S2": "넘김 줄이 rank 1만 적고, 유지 줄이 없으며, 부모는 shrink 뒤에도 GIN 오류를 그대로 보고함",
    "S3": "shrink가 5 s 안에 돌아오고 새 통신기 해제와 부모 abort가 오류 없이 끝남",
    "S4": "대조(gin-harden 라이브러리): shrink가 부모의 GIN 오류로 바로 실패함",
    "S5": "대조(스위치 끔): shrink가 부모의 GIN 오류로 실패하고 유지 줄이 스위치를 사유로 적음",
    "S6": "운영 빌드도 같은 shrink를 넘기고, 넘김 줄은 WARN에 보이지 않음",
    "S7": "상대를 적지 않은 GIN 오류(감시가 드러낸 오류)가 있으면 순정 판정을 유지함",
    "G1": "대조: GPU를 다 채우는 크기의 커널에서 pilot의 실패(복사 시간 초과, 복구 없음)가 재현됨",
    "G2": "그 커널의 블록 하나는 GIN 커널이 끝날 때까지 시작하지 못함",
    "G3": "새 스트림 P개의 4 B 복사 중 일부만 200 ms 안에 끝나고, 나머지는 GIN 커널이 끝난 뒤 끝남",
    "G4": "200 ms 안에 끝나지 않은 복사는 GPU를 채우는 커널의 스트림 뒤 P번째 스트림의 것 하나뿐임",
    "G5": "블록 하나를 줄인 커널에서는 모든 블록이 시작하고, 복사 시간 초과 없이 투명하게 복구됨",
    "G6": "블록 하나를 줄인 커널에서는 새 스트림 P개의 복사가 모두 200 ms 안에 끝남",
    "R1": "복구 재현 셀이 그대로 투명",
    "R2": "끊김 없는 kill이 2 s 안에 죽음 원인으로 거절되고 abort가 돌아옴",
    "R3": "원격 접근 오류를 rank 0이 거절하고, 받는 쪽 대기가 오류로 풀리며 abort가 5 s 안에 돌아옴",
    "R4": "받기만 하는 rank가 죽은 상대를 2 s 안에 죽음으로 보고 대기와 비동기 오류로 드러내고 abort가 돌아옴",
    "R5": "운영 빌드가 kill된 상대를 2 s 안에 죽음으로 거절하고 abort가 돌아옴",
    "R6": "통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0을 셈",
    "R7": "kill 뒤 통계 API가 죽음 판정 1, 거절 1을 셈",
    "P1": "4 KiB 지연: 이 실험의 운영 빌드와 gin-harden 운영 빌드 차이 0.40 µs 이하",
    "P2": "256 KiB 지연: 같은 두 빌드 차이 0.30 µs 이하",
    "P3": "4 KiB 지연: 이 실험의 운영 빌드와 gin-harden 연구 빌드 차이 0.40 µs 이하",
    "P4": "256 KiB 지연: 같은 두 빌드 차이 0.30 µs 이하",
}
EXCL_LABEL = {"bind": "드라이버 랑데부 포트 충돌", "no_fault": "장애 미적용(훅 발사 없음)", "trigger_miss": "트리거 미도달",
              "no_kill": "kill 기록 없음", "no_kill0": "rank 0 kill 기록 없음",
              "cond_window": "순서 미적용: 장애가 GPU를 채우는 커널이 도는 3 s 창 밖",
              "fw_overrun": "펌웨어 명령 하나가 NCCL_GIN_TS_FW_MS를 넘음",
              "config_build": "설정 확인 실패: 빌드 시작 줄이 빌드와 다름", "config_ts_off": "설정 확인 실패: 투명 복구 시작 줄 없음",
              "config_no_ua": "설정 확인 실패: abort 단어 줄 없음", "config_switch": "설정 확인 실패: 넘김 스위치 값이 셀과 다름",
              "config_knobs": "설정 확인 실패: 시험 스위치 줄이 있음", "config_mute": "설정 확인 실패: 끊김 줄이 있음",
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
    if cell in HOG:  # rank 0's fault must come while the GPU-filling kernel is meant to run (3 s from its launch)
        f, h = val(r.get("fault_after_launch_r0_ms")), val(r.get("hog_launch_after_launch_ms_r0"))
        if not (isinstance(f, float) and isinstance(h, float) and h < f < h + 3000):
            return "cond_window"
    # one firmware command over NCCL_GIN_TS_FW_MS trips the watchdog for good (as ../harden/score.py: a testbed event)
    if any(isinstance(val(r.get(c)), float) and val(r.get(c)) > 0
           for c in ("n_fwdog_r0", "n_fwdog_r1", "rs_fw_overruns_r0", "rs_fw_overruns_r1")):
        return "fw_overrun"
    # ---- configuration (a failure here stops the block, EXPERIMENT.md 8)
    if val(r.get("left_rules")) not in (0.0,) and r.get("left_rules") not in ("", None):
        return "config_rules_left"
    ranks = (0,) if cell in KILL_R1 else (1,) if cell in KILL_R0 else (0, 1)  # the killed rank has no full log
    for rk in ranks:
        hd_on, prod, hf_on = str(r.get("hd_on_r%d" % rk)), str(r.get("prod_r%d" % rk)), str(r.get("hf_on_r%d" % rk))
        ow_mode = str(r.get("ow_mode_r%d" % rk))
        if build == "hf" and not (hd_on == "1" and prod == "0" and ow_mode == "1" and hf_on == "1"):
            return "config_build"
        if build == "hd" and not (hd_on == "1" and prod == "0" and ow_mode == "1" and hf_on == "0"):
            return "config_build"
        if build in ("hfp", "hdp") and not (hd_on == "0" and hf_on == "0" and str(r.get("rs_api_r%d" % rk)) == "1"
                                             and val(r.get("rs_contexts_r%d" % rk)) >= 1):
            return "config_build"
        if build in ("hf", "hd"):
            if not val(r.get("ts_on_r%d" % rk)) >= 1:
                return "config_ts_off"
            if not val(r.get("ua_r%d" % rk)) >= 1:
                return "config_no_ua"
        if build == "hf":
            want = "0" if (cell == "hf_shrinkoff_b" and rk == 0) else "1"
            if str(r.get("hf_switch_r%d" % rk)) != want:
                return "config_switch"
        # no test switch of gin-harden or earlier studies in any cell of this study
        if build in ("hf", "hd"):
            for c in ("hk_gap", "hk_badnonce", "hk_fwdelay", "hk_copystall", "hk_badrepost", "knob_uto", "knob_refuse"):
                if str(r.get("%s_r%d" % (c, rk))) not in ("", "None"):
                    return "config_knobs"
            if val(r.get("n_mute_on_r%d" % rk)) != 0:
                return "config_mute"
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
            r.update({k: ("" if v is None else v) for k, v in extra_hf(stem).items()})
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
    L = ["# gin-handoff 채점 결과", "",
         f"`score.py`가 원자료(`{os.path.relpath(R, HERE)}/`의 빌드별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.", "",
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
