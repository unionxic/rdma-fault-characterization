#!/usr/bin/env python3
"""score.py <results_dir> - score the measured rows of predictions.csv (tag prereg/live-boundary-v1).

Applies the frozen acceptance expressions exactly as written, with the grammar of EXPERIMENT.md 3.0:
  acceptance := clause ("; " clause)*        every clause must hold
  clause     := [scope ":"] expr
  scope      := ["pooled "] cell ("," cell)* [" where " condition]
                no scope -> the cells of the row's `cells` column (keys before the first ':'), each apart
                "pooled" -> the listed cells' trials as one set; without it each listed cell apart
                "where"  -> keep only the trials for which the condition is true
  expr       := ALL(e) | MOST(e) | NONE(e) | COUNT(e) | N() | MAX(e) | MIN(e) combined with and, or,
                comparisons and arithmetic
  ALL(e)  e true in every trial of the scope (a trial whose fields are missing counts as false)
  MOST(e) e true in at least ceil(0.9 n) trials and false in no trial whose fields are all recorded
  NONE(e) e true in no trial
  COUNT(e) trials with e true (missing fields: not counted); N() trials in the scope;
  MAX(e), MIN(e) over the trials where e can be computed
  n = trials left after the section-8 exclusions (fault not applied, runner failure)
A scope with n = 0 gives "자료 없음". Source rows are not scored.

Input (run_points.sh): <dir>/CP/runs/lb_cp<ms>_t<n>/, <dir>/CG/runs/lb_cg<ms>_t<n>/ (CSV + .srv.log),
<dir>/G/logs/rec1_F3_timeout_g<ms>_t<n>_{r0.kv,r1.kv,meta.txt}.
Output: <dir>/SCORE.md, <dir>/trials_scored.csv, <dir>/score.json
"""
import ast, csv, glob, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.abspath(sys.argv[1])
PRED = os.path.join(HERE, "predictions.csv")
CP_KEYS = ["CP0", "CP900", "CP990", "CP1008", "CP1024", "CP1040", "CP1100"]
CG_KEYS = ["CG4300", "CG4600", "CG5000"]
G_KEYS = ["G2900", "G2985", "G2992", "G2995", "G2998", "G3010", "G3100"]
ALL_KEYS = CP_KEYS + CG_KEYS + G_KEYS
INT_FIELDS = {"status", "detect_ns", "cqe_ns", "t_post_mono_ns", "peer_alive", "verify_ok", "truth_alive",
              "resync_ms", "stale_lines", "auto_recoverable"}
FLOAT_FIELDS = {"probe_ms"}

CELL_LABEL = {**{k: f"CPU, PROBE 받을 때 {k[2:]} ms 정지" for k in CP_KEYS},
              **{k: f"CPU, 장애 순간부터 {k[2:]} ms 정지" for k in CG_KEYS},
              **{k: f"GIN, 복구 요청 때 {k[1:]} ms 정지" for k in G_KEYS}}
CELL_LABEL["CP0"] = "CPU, PROBE 정지 없음"
LABEL = {
    "CPa": "PROBE 정지 0, 900, 990 ms: 모두 살아 있음, 답은 정지 끝 뒤 0–5 ms",
    "CPb": "PROBE 정지 1008 ms: 10회 중 4회 이상 살아 있음",
    "CPc": "PROBE 정지 1024 ms: 10회 중 6회 이하 살아 있음",
    "CPd": "PROBE 정지 1040, 1100 ms: 모두 응답 없음, 대기 1000–1033 ms",
    "CPe": "PROBE 정지 셀 전체: 답과 대기 끝 중 먼저 오는 쪽이 판정을 정한다",
    "CPf": "응답 없음 시행 전체: 대기 끝 1000–1033 ms, 퍼짐 16 ms 이상",
    "CGa": "장애 순간 정지 4300 ms는 모두 살아 있음, 5000 ms는 모두 응답 없음",
    "CGb": "장애 순간 정지: 첫 CQE 뒤 남은 정지 995 ms 이하면 살아 있음, 1034 ms 이상이면 응답 없음",
    "CGc": "장애 순간 정지, 살아 있음 시행: 답은 PROBE 뒤 (x - 1)–(x + 6) ms",
    "Ga": "GIN 정지 2900, 2985, 2992 ms: 모두 복구, ACK는 정지 끝 뒤 4.0–5.5 ms",
    "Gb": "GIN 정지 2995 ms: 뒤 끝 거절 0, 5회 이상 복구, 복구 ACK는 Prepare 뒤 3001.2 ms 안",
    "Gc": "GIN 정지 2998, 3010, 3100 ms: 모두 핸드셰이크 시간 초과로 거절, rank 0 종료 코드 9",
    "Gd": "GIN 거절 전체: 장애 조회 뒤 2998.8–3002.8 ms, 두 끝 사이는 10% 이하",
    "Ge": "GIN 2998 ms 뒤 끝 거절에서 rank 1은 거절 전에 깨어 있음, 거절마다 rank 1이 요청 처리",
}
EXCL_LABEL = {"runner_fail": "실행기 실패", "not_applied": "장애 미적용"}
FUNCS = {"ALL", "MOST", "NONE", "COUNT", "N", "MAX", "MIN"}


class Unobs(Exception):
    pass


class NS(dict):
    def __missing__(self, k):
        raise Unobs(k)


def kvtok(line):
    return {m.group(1): m.group(2) for m in re.finditer(r"(\w+)=(\S+)", line)}


def num(v):
    try:
        return int(v)
    except ValueError:
        return float(v)


trials = []


def load_cpu(series):
    for d in sorted(glob.glob(os.path.join(R, series, "runs", f"lb_{series.lower()}*_t*"))):
        tag = os.path.basename(d)
        m = re.match(rf"lb_{series.lower()}(\d+)_t(\d+)$", tag)
        ms, tn = int(m.group(1)), int(m.group(2))
        fault = "live_stop_probe" if series == "CP" else "live_stop_err"
        t = dict(part="CPU", cell=f"{series}{ms}", tag=tag, trial=tn, excl="", fields={})
        csvs = glob.glob(os.path.join(d, f"{fault}_*.csv"))
        srvs = glob.glob(os.path.join(d, f"{fault}_*.srv.log"))
        srv = open(srvs[0], errors="replace").read() if srvs else ""
        rows = list(csv.DictReader(open(csvs[0]))) if csvs else []
        f = t["fields"]
        if not rows:
            t["excl"] = "runner_fail"
        else:
            for k, v in rows[0].items():
                if v is None or v == "":
                    continue
                if k == "vendor_err":
                    f[k] = v.lower()
                elif k in INT_FIELDS:
                    try:
                        f[k] = int(v)
                    except ValueError:
                        pass
                elif k in FLOAT_FIELDS:
                    f[k] = float(v)
                else:
                    f[k] = v
        st = re.search(r"stall_end mono_ns=\d+ measured_ms=([\d.]+)", srv)
        if ms == 0:
            f["stall_meas_ms"] = 0.0
        elif st:
            f["stall_meas_ms"] = float(st.group(1))
        if not t["excl"]:
            if f"fault_applied fault={fault}" not in srv or (ms > 0 and not st):
                t["excl"] = "not_applied"
        if "stall_meas_ms" in f and "cqe_ns" in f:
            f["x_ms"] = f["stall_meas_ms"] - f["cqe_ns"] / 1e6
        trials.append(t)


def load_gin():
    for r0 in sorted(glob.glob(os.path.join(R, "G", "logs", "rec1_F3_timeout_g*_t*_r0.kv"))):
        stem = r0[:-len("_r0.kv")]
        m = re.match(r"rec1_F3_timeout_(g(\d+)_t(\d+))$", os.path.basename(stem))
        tag, ms, tn = m.group(1), int(m.group(2)), int(m.group(3))
        t = dict(part="GIN", cell=f"G{ms}", tag=tag, trial=tn, excl="", fields={})
        f = t["fields"]
        r1p, metap = stem + "_r1.kv", stem + "_meta.txt"
        r0l = open(r0, errors="replace").read().splitlines()
        r1l = open(r1p, errors="replace").read().splitlines() if os.path.exists(r1p) else None
        if not r0l or not r1l:
            t["excl"] = "runner_fail"
        fev = [x for x in r0l if x.startswith("fault ev=")]
        rev = [x for x in r0l if x.startswith("rec ev=")]
        if fev and "t_query" in kvtok(fev[0]):
            f["fault_t_query"] = num(kvtok(fev[0])["t_query"])
        if rev:
            kv = kvtok(rev[0])
            for src, dst in (("outcome", "rec_outcome"), ("reason", "rec_reason")):
                if src in kv:
                    f[dst] = kv[src]
            for src, dst in (("t_prep", "rec_t_prep"), ("t_ack", "rec_t_ack"), ("t_decl", "rec_t_decl")):
                if src in kv:
                    f[dst] = num(kv[src])
        off = [x for x in r0l if x.startswith("clock_offset_ms=")]
        if off:
            f["r0_clock_offset_ms"] = num(kvtok(off[0])["clock_offset_ms"])
        stall_ok = False
        if r1l is not None:
            idx = [i for i, x in enumerate(r1l) if x.startswith("stall on=")]
            if idx:
                kv = kvtok(r1l[idx[0]])
                if "end_mono_ms" in kv:
                    stall_ok = True
                    f["r1_stall_ms"] = num(kv["measured_ms"])
                    if "r0_clock_offset_ms" in f:
                        f["r1_stall_end_r0clock"] = num(kv["end_mono_ms"]) - f["r0_clock_offset_ms"]
                f["r1_n_rxrec_after_stall"] = sum(1 for x in r1l[idx[0] + 1:] if x.startswith("rxrec "))
        if os.path.exists(metap):
            meta = kvtok(open(metap).read())
            for kk in ("r0rc", "r1_alive_at_r0_exit"):
                if kk in meta:
                    f[kk] = int(meta[kk])
        if not t["excl"] and (not fev or not stall_ok):
            t["excl"] = "not_applied"
        if "rec_t_decl" in f and "fault_t_query" in f:
            f["decl_q_ms"] = f["rec_t_decl"] - f["fault_t_query"]
        if "rec_t_ack" in f and "rec_t_prep" in f:
            f["ack_prep_ms"] = f["rec_t_ack"] - f["rec_t_prep"]
        trials.append(t)


load_cpu("CP")
load_cpu("CG")
load_gin()


# ---------------------------------------------------------------- evaluation
def ev(code, t):
    """-> (value, observed)"""
    try:
        return eval(code, {"__builtins__": {}}, NS(t["fields"])), True
    except Unobs:
        return None, False


def call_value(name, arg, ts, calls, text):
    n = len(ts)
    src = ast.get_source_segment(text, arg) if arg is not None else ""
    info = dict(func=name, expr=src, n=n, hits=None, missed=[], value=None)
    if name == "N":
        info["value"] = n
        calls.append(info)
        return n
    code = compile(ast.Expression(body=arg), "<acc>", "eval")
    res = [(t, *ev(code, t)) for t in ts]
    if name in ("MAX", "MIN"):
        vals = [v for _, v, o in res if o and v is not None]
        val = (max(vals) if name == "MAX" else min(vals)) if vals else None
        info["value"] = val
        calls.append(info)
        if val is None:
            raise Unobs(f"{name} over no value")
        return val
    true = [t for t, v, o in res if o and bool(v)]
    false_obs = [t for t, v, o in res if o and not bool(v)]
    unobs = [t for t, v, o in res if not o]
    if name == "COUNT":
        info["value"] = len(true)
        info["hits"] = len(true)
        calls.append(info)
        return len(true)
    if name == "ALL":
        ok = n > 0 and len(true) == n
        info["missed"] = [t["tag"] for t in false_obs] + [t["tag"] + "(관측 불가)" for t in unobs]
        info["hits"] = len(true)
    elif name == "MOST":
        ok = n > 0 and len(true) >= math.ceil(0.9 * n) and not false_obs
        info["missed"] = [t["tag"] for t in false_obs] + [t["tag"] + "(관측 불가)" for t in unobs]
        info["hits"] = len(true)
    else:  # NONE
        ok = len(true) == 0
        info["missed"] = [t["tag"] for t in true]
        info["hits"] = n - len(true)
    info["value"] = ok
    calls.append(info)
    return ok


class Fold(ast.NodeTransformer):
    def __init__(self, ts, calls, text):
        self.ts, self.calls, self.text = ts, calls, text

    def visit_Call(self, node):
        assert isinstance(node.func, ast.Name) and node.func.id in FUNCS, ast.dump(node)
        arg = node.args[0] if node.args else None
        return ast.copy_location(ast.Constant(call_value(node.func.id, arg, self.ts, self.calls, self.text)), node)


def eval_clause(expr, ts):
    calls = []
    if not ts:
        return None, calls
    tree = ast.parse(expr, mode="eval")
    try:
        folded = ast.fix_missing_locations(Fold(ts, calls, expr).visit(tree))
        val = eval(compile(folded, "<clause>", "eval"), {"__builtins__": {}}, {})
    except Unobs:
        return None, calls
    return bool(val), calls


def row_cells(row):
    head = row["cells"].split(":", 1)[0]
    return [k for k in re.findall(r"\b((?:CP|CG|G)\d+)\b", head) if k in ALL_KEYS]


def scored(keys):
    return [t for t in trials if t["cell"] in keys and not t["excl"]]


SCOPE = re.compile(r"^(pooled )?((?:CP|CG|G)\d+(?:, (?:CP|CG|G)\d+)*)(?: where (.+?))?: (.+)$")


def score_row(row):
    out = []
    for clause in row["acceptance"].split("; "):
        m = SCOPE.match(clause)
        if m:
            pooled, keys, cond, expr = bool(m.group(1)), m.group(2).split(", "), m.group(3), m.group(4)
        else:
            pooled, keys, cond, expr = False, row_cells(row), None, clause
        groups = [keys] if pooled else [[k] for k in keys]
        ccode = compile(cond, "<where>", "eval") if cond else None
        for g in groups:
            ts = scored(g)
            if ccode:
                ts = [t for t in ts if ev(ccode, t)[1] and bool(ev(ccode, t)[0])]
            v, calls = eval_clause(expr, ts)
            out.append(dict(scope=("pooled " if pooled else "") + ", ".join(g) + (f" where {cond}" if cond else ""),
                            expr=expr, n=len(ts), verdict=v, calls=calls))
    vs = [o["verdict"] for o in out]
    if any(v is False for v in vs):
        final = "틀림"
    elif all(v is None for v in vs):
        final = "자료 없음"
    elif any(v is None for v in vs):
        final = "자료 없음(일부 범위)"
    else:
        final = "맞음"
    return final, out


preds = list(csv.DictReader(open(PRED)))
rows = []
for row in preds:
    if row["kind"] == "source":
        continue
    final, out = score_row(row)
    missed = sorted({m for o in out for c in o["calls"] for m in c["missed"]})
    rows.append(dict(id=row["id"], label=LABEL.get(row["id"], row["predicted"]), verdict=final,
                     n=sum(o["n"] for o in out), missed=missed, detail=out))

# trials_scored.csv
FIELDS = ["status", "vendor_err", "cqe_ns", "sub_cause", "probe_ms", "stall_meas_ms", "x_ms", "srv_qp_state",
          "verify_ok", "truth_alive", "stale_lines", "rec_outcome", "rec_reason", "rec_t_prep", "rec_t_ack",
          "rec_t_decl", "fault_t_query", "ack_prep_ms", "decl_q_ms", "r1_stall_ms", "r1_stall_end_r0clock",
          "r1_n_rxrec_after_stall", "r0rc", "r1_alive_at_r0_exit"]
order = {k: i for i, k in enumerate(ALL_KEYS)}
with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["part", "cell", "tag", "trial", "excluded"] + FIELDS)
    for t in sorted(trials, key=lambda t: (order.get(t["cell"], 99), t["trial"])):
        w.writerow([t["part"], t["cell"], t["tag"], t["trial"], t["excl"]] + [t["fields"].get(k, "") for k in FIELDS])

# SCORE.md
L = ["# live_boundary 채점 결과\n",
     "`score.py`가 `predictions.csv`(태그 `prereg/live-boundary-v1`)의 판정식을 EXPERIMENT.md 3.0절 규칙 그대로 적용한 결과다. "
     "원자료는 `CP/`, `CG/`, `G/`(Release). 소스 예측 3줄은 채점하지 않는다. 시행별 값은 [trials_scored.csv](trials_scored.csv).\n"]
ok = sum(r["verdict"] == "맞음" for r in rows)
bad = sum(r["verdict"] == "틀림" for r in rows)
L.append(f"측정 예측 {len(rows)}줄 중 맞음 {ok}, 틀림 {bad}, 자료 없음 {len(rows) - ok - bad}.\n")
L.append("## 시행 수\n")
L.append("| 점 | 시행 | 채점 | 장애 미적용 | 실행기 실패 |")
L.append("|---|--:|--:|--:|--:|")
for k in ALL_KEYS:
    ts = [t for t in trials if t["cell"] == k]
    L.append(f"| {CELL_LABEL[k]} ({k}) | {len(ts)} | {sum(not t['excl'] for t in ts)} | "
             f"{sum(t['excl'] == 'not_applied' for t in ts)} | {sum(t['excl'] == 'runner_fail' for t in ts)} |")
excl = [t for t in trials if t["excl"]]
L.append("")
L.append("따로 센 시행: " + (", ".join(f"`{t['tag']}`({EXCL_LABEL[t['excl']]})" for t in excl) if excl else "없음") + ".\n")
L.append("## 예측별 판정\n")
L.append("| 예측 | id | n | 판정 | 놓친 시행 |")
L.append("|---|---|--:|---|---|")
for r in rows:
    miss = ", ".join(f"`{m}`" for m in r["missed"]) if r["missed"] else "-"
    L.append(f"| {r['label']} | ({r['id']}) | {r['n']} | {r['verdict']} | {miss} |")
L.append("")
L.append("n은 줄의 모든 범위에서 센 시행 수의 합이다(같은 시행이 여러 범위에 들어가면 여러 번 센다).\n")
L.append("## 범위와 항목별 값\n")
L.append("| id | 범위 | n | 항목 | 값 | 맞은 시행 | 결과 |")
L.append("|---|---|--:|---|---|--:|---|")
for r in rows:
    for o in r["detail"]:
        res = {None: "자료 없음", True: "맞음", False: "틀림"}[o["verdict"]]
        if not o["calls"]:
            L.append(f"| ({r['id']}) | {o['scope']} | {o['n']} | `{o['expr']}` | - | - | {res} |")
        for c in o["calls"]:
            val = c["value"]
            val = f"{val:.3f}" if isinstance(val, float) else str(val)
            hits = "" if c["hits"] is None else str(c["hits"])
            L.append(f"| ({r['id']}) | {o['scope']} | {o['n']} | `{c['func']}({c['expr']})` | {val} | {hits} | {res} |")
L.append("")
open(os.path.join(R, "SCORE.md"), "w").write("\n".join(L) + "\n")
json.dump([{k: v for k, v in r.items()} for r in rows], open(os.path.join(R, "score.json"), "w"),
          ensure_ascii=False, indent=1, default=str)
print("\n".join(f"{r['id']:4} n={r['n']:3} {r['verdict']}" for r in rows))
