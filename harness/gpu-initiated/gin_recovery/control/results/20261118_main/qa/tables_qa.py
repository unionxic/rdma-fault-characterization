#!/usr/bin/env python3
"""tables_qa.py <trials_qa.csv> <cells_gc.json>: Markdown tables for qa_recount.md (n, judgement, fence/restore, data/outcome)."""
import csv, sys, json, collections
rows = list(csv.DictReader(open(sys.argv[1])))
cj = json.load(open(sys.argv[2]))
plan = {v["cell"] + "@" + v["build"]: v["n"] for v in cj["cells"].values()}
by = collections.OrderedDict()
for r in sorted(rows, key=lambda r: (r["cell"], r["build"], int(r["trial"][1:]))):
    by.setdefault(r["cell"] + "@" + r["build"], []).append(r)
def num(x):
    try: return float(x)
    except: return None
def rng(v, nd=1):
    v = [x for x in (num(y) for y in v) if x is not None]
    if not v: return "-"
    f = "%%.%df" % nd
    return (f % min(v)) if min(v) == max(v) else (f % min(v) + "–" + f % max(v))
def cnt(v):
    c = collections.Counter(v)
    return ", ".join(("%s %d" % (k, n)) for k, n in sorted(c.items()) if k != "") or "-"
print("### 표 1. 시행 수\n")
print("| 셀 | 계획 n | 실행 n | 시행 | hold | 링 live(rank 4개) | 주입 줄 | Resume 거절 |")
print("|---|--:|--:|---|---|---|---|---|")
for k, v in by.items():
    if not k.startswith(("gc4", "gct4")): continue
    tr = sorted(int(r["trial"][1:]) for r in v)
    live = sum(1 for r in v if r["ring_live_ranks"] == "4")
    inj = sum(1 for r in v if r["inj_n"] != "0")
    res = sum(1 for r in v if r["resume_rcs"])
    print("| `%s` | %s | %d | n%d–n%d | %s | %d/%d | %s | %d |" % (k, plan.get(k, "-"), len(v), tr[0], tr[-1], "+".join(sorted(set(r["hold"] for r in v))), live, len(v), ("%d/%d" % (inj, len(v))) if inj else "없음(장애 없는 셀)", res))
print("\n### 표 2. 대상 판정\n")
print("| 셀 | 판정한 생존 rank(시행 수) | 원인 | 주입 → 판정 ms (관측자별 첫 판정, 최소–최대) | 퍼짐 ms | 주입 줄 |")
print("|---|---|---|---|---|---|")
for k, v in by.items():
    if not any(r["judge_n"] != "0" for r in v): continue
    print("| `%s` | %s | %s | %s | %s | %s |" % (k, cnt("%s명" % r["judge_n"] for r in v), cnt(r["causes"] for r in v), rng([r["judge_min"] for r in v] + [r["judge_max"] for r in v]), rng(r["judge_spread"] for r in v), v[0]["inject"].split(":")[0].replace("inj_", "")))
print("\n### 표 3. 펜스 순서와 복원\n")
print("| 셀 | 펜스 순서 | 주입 → FENCED ms | 활성화 | 첫 판정 → 마지막 restored ms | 첫 판정 → 마지막 published ms | 주입 → 마지막 published ms | 창 검사(줄 3, 바뀐 칸 0) |")
print("|---|---|---|---|---|---|---|---|")
for k, v in by.items():
    if not any(r["fence_order"] or r["la_exited"] or r["la_act_res"] for r in v): continue
    win = sum(1 for r in v if r["win_n"] == "3" and r["win_changed"] == "0" and r["win_unread"] == "0")
    fo = cnt(r["fence_order"].replace("ok:", "").replace(">", " → ") if r["fence_order"] else ("EXITED(펜스 없음)" if r["la_exited"] else "") for r in v)
    print("| `%s` | %s | %s | %s | %s | %s | %s | %d/%d |" % (k, fo, rng(r["la_fenced"] for r in v), cnt(r["la_act_res"].replace("(accepted by the spare)", "").replace("(the spare exited)", " the spare exited") for r in v), rng(r["restore_ms"] for r in v), rng(r["judge_to_last_pub"] for r in v), rng(r["kill_to_last_pub"] for r in v), win, len(v)))
print("\n### 표 4. 데이터와 대기 결과\n")
print("| 셀 | 데이터 같음 | 되살린 rank 끝까지 | 대기 결과 | 끝 xchg | 생존 rank 풀림 시각(주입 뒤 ms) | FENCED → 첫 fallback 줄 ms |")
print("|---|---|---|---|---|---|---|")
for k, v in by.items():
    if not k.startswith(("gc4", "gct4")): continue
    de = sum(1 for r in v if r["data_equal"] == "1")
    rd = [r["revived_done"] for r in v if r["revived_done"] != "" and r["spare_act"] != ""]
    rel = [x for r in v if r["released_ms"] for x in r["released_ms"].split("-")]
    print("| `%s` | %d/%d | %s | %s | %s | %s | %s |" % (k, de, len(v), ("%d/%d" % (rd.count("1"), len(rd))) if rd else "-(예비 안 씀)", cnt(r["wait_outcome"].replace("heldreleased3", "held → released 3").replace("released3", "released 3") or "없음(장애 없음, 판정 없음)" for r in v), cnt(r["xchg_set"] for r in v), rng(rel), rng(r["fenced_to_fallback"] for r in v)))
