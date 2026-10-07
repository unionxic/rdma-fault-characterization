#!/usr/bin/env python3
"""score.py <results_dir> - score the measured cells P1-P7 of predictions.csv (tag
prereg/completion-contract-v1) from the per-cell folders that run_cells.sh writes.

NVSHMEM cells (P1-P3): <cell>/trials.csv (rows of ../nvshmem_rootcause/official380/run.sh) and
<cell>/<tag>.pe0.log. "First iteration after the kill" is the first iteration after KILL_AFTER (3)
that does not return within 100 ms; every earlier iteration returned normally (DEVIATIONS 1).
A kill trial with no such iteration had no fault during communication (section 8, counted apart).
NCCL cells (P4-P7): <cell>/gin.csv (rows of ../gin/scripts/run_trial.sh) and <cell>/logs/.
Writes SCORE.md and trials_scored.csv in <results_dir>.
"""
import csv, glob, os, re, sys

R = os.path.abspath(sys.argv[1])
KILL_AFTER = 3
SLOW_MS = 100.0
POLL = "falling back to polling-based errors"
rows = []


def nvs(cell):
    p = os.path.join(R, cell, "trials.csv")
    if not os.path.exists(p):
        return
    for r in csv.reader(open(p)):
        var, handler, kill, trial, _, kill_at = r[:6]
        tag = f"{var}_{handler}_kill{kill}_t{trial}"
        log = open(os.path.join(R, cell, tag + ".pe0.log"), errors="replace").read()
        its = {}
        for m in re.finditer(r"^PE 0 iter (\d+): (?:put \+ signal \+ nvshmem_quiet\(\) returned after ([\d.]+) ms|"
                             r"nvshmem_quiet\(\) has not returned after (\d+) s)", log, re.M):
            its[int(m.group(1))] = float(m.group(2)) if m.group(2) else None
        all_ret = bool(re.search(r"^PE 0: all \d+ iterations returned", log, re.M))
        row = dict(cell=cell, tag=tag, fault="kill" if kill == "1" else "none", iters=len(its), all_returned=all_ret)
        if kill == "1":
            first = next((i for i in sorted(its) if i > KILL_AFTER and (its[i] is None or its[i] > SLOW_MS)), None)
            early_ok = first is not None and all(its[i] is not None and its[i] <= SLOW_MS for i in its if i < first)
            if kill_at == "-" or first is None:
                row.update(outcome="fault not applied", value="")
            elif not early_ok:
                row.update(outcome="other", value=f"iter {first}")
            elif its[first] is None:
                row.update(outcome="did not return within the wait bound", value=f"iter {first}")
            else:
                row.update(outcome="returned", first_ms=its[first], value=f"iter {first} {its[first]:.1f} ms")
        else:
            row.update(outcome="all returned" if all_ret else "not all returned", value=f"{len(its)} iterations")
        rows.append(row)


def gin(cell):
    p = os.path.join(R, cell, "gin.csv")
    if not os.path.exists(p):
        return
    for r in csv.DictReader(open(p)):
        tag = f"gdaki_{r['fault']}_{r['wait_mode']}_t{r['trial']}"
        logs = "".join(open(f, errors="replace").read() for f in glob.glob(os.path.join(R, cell, "logs", tag + "_r*.log")))
        rows.append(dict(cell=cell, tag=tag, fault=r["fault"], init=r["init_outcome"], target=r["target_outcome"],
                         data=r["data_check"], iters_ok=r["iters_ok_before"], host_error=r["host_error"],
                         host_error_ms=r["host_error_ms"], fault_ms=r["fault_ms"], polling=POLL in logs,
                         outcome="", value=f"init {r['init_outcome']}, data {r['data_check']}, host error {r['host_error']}"))


for c in ("P1", "P2", "P3"):
    nvs(c)
for c in ("P4", "P5", "P6", "P7"):
    gin(c)


def judge(name, rs, hit, need, unobs=lambda r: False, forbid=None, label=""):
    """need: hits required (None = every scored trial); forbid: an outcome that fails the cell at once."""
    ex = [r for r in rs if unobs(r)]
    sc = [r for r in rs if r not in ex]
    hits = [r for r in sc if hit(r)]
    miss = [r["tag"] for r in sc if not hit(r)]
    bad = [r["tag"] for r in sc if forbid and forbid(r)]
    if not sc:
        v = "no data"
    elif bad:
        v = "fails"
    elif need is None:
        v = "fails" if miss else ("holds" if not ex else "not observable")
    else:
        v = "holds" if len(hits) >= need else ("fails" if len(sc) >= need else "not observable")
    return dict(name=name, label=label, n=len(sc), hits=len(hits), verdict=v, miss=miss, excluded=[r["tag"] for r in ex])


def by(cell, fault=None):
    return [r for r in rows if r["cell"] == cell and (fault is None or r["fault"] == fault)]


def gin_normal(r):
    return r["init"] == "ok" and r["target"] == "ok" and r["data"] == "ok" and r["host_error"] == "none"


def within(lo, hi):
    return lambda r: r["outcome"] == "returned" and lo <= r["first_ms"] <= hi


def beyond(bound_ms):
    return lambda r: r["outcome"] == "did not return within the wait bound" or (
        r["outcome"] == "returned" and r["first_ms"] > bound_ms)


skip = lambda r: r["outcome"] == "fault not applied"
# P1 and P2: (a) as written, (b) with the window of 3.4.5's fixed timeout 20 (DEVIATIONS 3)
res = [
    judge("P1 (a)", by("P1"), within(3000, 5000), 9, unobs=skip, forbid=beyond(30000),
          label="NVSHMEM 3.4.5 CPU 프록시, 상대 kill: 죽은 뒤 첫 반복이 3–5 s에 돌아온다(10회 중 9회 이상, 30 s 넘는 시행 0회), 쓴 그대로"),
    judge("P1 (b)", by("P1"), within(50000, 70000), 9, unobs=skip, forbid=beyond(90000),
          label="같은 예측, 3.4.5의 고정 타임아웃 20에 맞춘 창 50–70 s(90 s 넘는 시행 0회)"),
    judge("P2 (a)", by("P2"), within(3000, 5000), None, unobs=skip,
          label="NVSHMEM 3.4.5 GPU 처리, 상대 kill: 같다(5/5), 쓴 그대로"),
    judge("P2 (b)", by("P2"), within(50000, 70000), None, unobs=skip,
          label="같은 예측, 창 50–70 s"),
    judge("P3", by("P3"), lambda r: r["outcome"] == "all returned", None,
          label="NVSHMEM 3.4.5 CPU 프록시, 장애 없음: 모든 반복이 돌아온다(5/5)"),
    judge("P4", by("P4"), lambda r: r["init"] == "timeout" and r["iters_ok"] == "0" and r["data"] == "missing", 9,
          forbid=lambda r: r["init"] == "ok",
          label="NCCL GDAKI BlueFlame 처리 방식, 장애 없음: 첫 반복이 시간 초과, 받는 쪽 데이터 없음(10회 중 9회 이상, 정상 완료 0회)"),
    judge("P5", by("P5"), gin_normal, None, label="NCCL GDAKI 기본 처리 방식, 장애 없음: 모두 정상 완료(5/5)"),
]
names = {"F1": "로컬 QP 오류", "F2": "원격 접근 오류", "F3": "상대 QP 오류"}
for f in ("F1", "F2", "F3"):
    res.append(judge(f"P6 {f}", by("P6", f), lambda r: r["host_error"] != "none", None,
                     unobs=lambda r: r["polling"] or not r["fault_ms"],
                     label=f"NCCL GDAKI CPU 프록시 처리 방식, {names[f]}: 호스트 오류가 나온다(5/5)"))
res.append(judge("P7", by("P7"), gin_normal, None, label="NCCL GDAKI CPU 프록시 처리 방식, 장애 없음: 오류 없이 정상 완료(5/5)"))

keys = ["cell", "tag", "fault", "outcome", "value", "polling", "fault_ms", "host_error_ms"]
with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(keys)
    for r in rows:
        w.writerow([r.get(k, "") for k in keys])
with open(os.path.join(R, "SCORE.md"), "w") as f:
    f.write("# completion_contract score\n\nScored by `score.py` against `predictions.csv` (tag "
            "prereg/completion-contract-v1). Per-trial values: `trials_scored.csv`.\n\n"
            "| 예측 | n | 맞음 | 판정 | 놓친 시행 | 따로 센 시행 |\n|---|--:|--:|---|---|---|\n")
    for c in res:
        f.write(f"| {c['label']} ({c['name']}) | {c['n']} | {c['hits']} | **{c['verdict']}** | "
                f"{', '.join(c['miss'])} | {', '.join(c['excluded'])} |\n")
print(open(os.path.join(R, "SCORE.md")).read())
