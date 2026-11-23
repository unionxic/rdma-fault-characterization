#!/usr/bin/env python3
"""score.py <results_dir> - score the measured rows of predictions.csv (tag prereg/live-peer-v1).

Applies the frozen acceptance expressions of predictions.csv exactly as written, with the judgment
functions and field names of EXPERIMENT.md section 3.0:
  ALL(e)  e is true in all n trials of the cell
  MOST(e) e is true in at least ceil(0.9 n) trials, and no trial whose fields are all recorded has e false
  NONE(e) e is true in no trial
  n       scored trials of the cell after the section-8 exclusions; counter rows (K) keep only trials with
          an evrec end record on both nodes, misjudgment rows (O) only trials whose ground truth is known
A clause "per cell over trials with status==12: ..." scores only those trials; a clause "<cells>: ..."
applies to the cells it names. Source rows (kind "source") are not scored.

Input (written by run_cells.sh):
  <results_dir>/A/runs/<tag>/<fault>_<stamp>.csv and .srv.log, <results_dir>/A/evrec/<tag>.evrec.{rain,sunny}
  <results_dir>/B/logs/rec1_<F3|none>_timeout_<tag>_{r0.kv,r1.kv,meta.txt}, <results_dir>/B/evrec/<tag>.evrec.*
Output: <results_dir>/SCORE.md, <results_dir>/trials_scored.csv, <results_dir>/score.json
"""
import ast, csv, glob, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.abspath(sys.argv[1])
PRED = os.path.join(HERE, "predictions.csv")

A_CELLS = {"none": "A0", "retry_server_qp_err": "A1", "retry_proc_sigkill": "A2", "live_qp_reset": "A3",
           "live_qp_init": "A4", "live_qp_rtr": "A5", "live_transient": "A6", "live_stop_err": "A7",
           "live_stop_ok": "A8", "live_ctl_close": "A9", "rnr": "A10", "live_qp_recreate": "A11"}
A_ORDER = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11"]
B_ORDER = ["B0", "B1", "B2", "B3"]
SERVER_SIDE = {"retry_server_qp_err", "live_qp_reset", "live_qp_init", "live_qp_rtr", "live_transient",
               "live_stop_err", "live_stop_ok", "live_ctl_close", "live_qp_recreate"}
INT_FIELDS = {"status", "detect_ns", "cqe_ns", "t_post_mono_ns", "peer_alive", "verify_ok", "truth_alive",
              "resync_ms", "stale_lines", "auto_recoverable", "cnt_delta"}

LABEL = {
    "A0": "장애 없음: 10 ms 안에 정상 완료, 생존 확인 없음",
    "A1": "응답 QP 오류, 프로세스 응답(재현): 12/0x81, 3.40–3.90 s, 살아 있음 판정, QP 상태 ERR",
    "A2": "응답 프로세스 SIGKILL(재현): 12/0x81, 죽음 판정, 실제로 죽음",
    "A3a": "응답 QP RESET: 12/0x81, 3.40–3.90 s",
    "A3b": "응답 QP RESET: 살아 있음 판정, QP 상태 RESET, 응답 쪽 비동기 이벤트 없음",
    "A4a": "응답 QP INIT: 12/0x81, 3.40–3.90 s",
    "A4b": "응답 QP INIT: 살아 있음 판정, QP 상태 INIT, 응답 쪽 비동기 이벤트 없음",
    "A5": "응답 QP를 같은 PSN으로 RTR까지만: 10 ms 안에 정상 완료, QP 상태 RTR",
    "A6": "응답 QP를 1250 ms 동안 준비 안 됨으로 둔 뒤 재무장: 1.25–1.80 s에 정상 완료, QP 상태 RTS",
    "A7a": "응답 QP 오류 + 프로세스 8 s 정지: 12/0x81, 3.40–3.90 s",
    "A7b": "응답 QP 오류 + 프로세스 8 s 정지: 응답 없음 판정(죽음 0), 재개 뒤 복구, 실제로 살아 있음",
    "A8": "정상 QP + 프로세스 8 s 정지: 10 ms 안에 정상 완료, 상태 조회 응답 없음, 판정 없음, 재개 뒤 복구",
    "A9a": "응답 QP 오류 + 제어 연결만 닫음: 12/0x81, 3.40–3.90 s",
    "A9b": "응답 QP 오류 + 제어 연결만 닫음: 죽음 판정, 새 연결의 생존 질의에 같은 프로세스가 답함",
    "A10": "수신 버퍼 없음(재현): 13/0x87, 11.5–13.5 ms, 생존 확인 없음",
    "A11": "응답 QP 파괴 뒤 새 QP INIT(재현): 12/0x81, 3.40–3.90 s, 살아 있음 판정, QP 상태 INIT",
    "B0": "GIN 상대 QP 오류, 정지 없음(재현): 복구, ACK는 Prepare 뒤 500 ms 안",
    "B1": "GIN 상대 QP 오류 + 복구 요청 때 1 s 정지: 복구, ACK는 Prepare 뒤 1000–1500 ms",
    "B2a": "GIN 상대 QP 오류 + 복구 요청 때 6 s 정지: 핸드셰이크 시간 초과로 거절(3000–3500 ms), rank 0 종료 코드 9",
    "B2b": "GIN 상대 QP 오류 + 복구 요청 때 6 s 정지: rank 1이 거절 뒤 재개해 요청을 처리",
    "B3": "GIN 장애 없음 + 반복 60에서 6 s 정지: 장애 기록과 복구 없이 120회 모두 정확",
    "O1": "죽음 오판은 제어 연결만 닫은 셀에만 생긴다",
    "O2": "복구 불가 오판은 정지 + QP 오류 셀과 제어 연결을 닫은 셀에만 생긴다",
    "O3": "GIN 거절 오판은 6 s 정지 셀에만 생긴다",
    "O4": "놓친 정지: 정상 QP + 정지와 GIN 장애 없음 + 정지에서 오류도 판정도 없다",
    "K1": "실제 혼잡 신호(np_cnp_sent, np_ecn_marked_roce_packets, rp_cnp_ignored) 모든 시행 +0",
    "K2": "CPU 하네스 재시도 초과: rp_cnp_handled = roce_slow_restart_cnps = 적응 재전송 + 정규 타임아웃 - 1, 정규 타임아웃 6",
    "K3a": "일시 장애: 오류 완료 없이 rp_cnp_handled가 오르고 roce_slow_restart_cnps와 같다",
    "K3b": "일시 장애: rp_cnp_handled = 적응 재전송 + 정규 타임아웃(재전송마다 하나)",
    "K3c": "일시 장애: 정규 타임아웃 2",
    "K4": "ACK 타임아웃 없는 셀: rp_cnp_handled, roce_slow_restart_cnps, local_ack_timeout_err +0",
    "K5": "1부 sunny: rp_cnp_handled +0",
    "K6": "GIN 상대 QP 오류: rain rp_cnp_handled 8 이상, q 카운터 +0, sunny +0",
    "K7": "50 ms 표본: 두 카운터 차이 1 이하, 게시와 첫 CQE + 100 ms 사이에만 증가",
}
CELL_LABEL = {
    "A0": "장애 없음", "A1": "응답 QP 오류, 프로세스 응답", "A2": "응답 프로세스 SIGKILL", "A3": "응답 QP RESET",
    "A4": "응답 QP INIT", "A5": "응답 QP RTR", "A6": "1250 ms 준비 안 됨 뒤 재무장", "A7": "QP 오류 + 8 s 정지",
    "A8": "정상 QP + 8 s 정지", "A9": "QP 오류 + 제어 연결만 닫음", "A10": "수신 버퍼 없음", "A11": "QP 파괴 뒤 새 QP",
    "B0": "GIN 상대 QP 오류, 정지 없음", "B1": "GIN 상대 QP 오류 + 1 s 정지", "B2": "GIN 상대 QP 오류 + 6 s 정지",
    "B3": "GIN 장애 없음 + 6 s 정지",
}
EXCL_LABEL = {"runner_fail": "실행기 실패", "not_applied": "장애 미적용"}


class Unobs(Exception):
    pass


class Ctr:
    def __init__(self, d):
        self._d = d

    def __getattr__(self, k):
        if k.startswith("_") or self._d is None or k not in self._d:
            raise Unobs(k)
        return self._d[k]


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


def evrec(path):
    """-> (delta dict or None, samples list, start dict)"""
    if not os.path.exists(path):
        return None, [], {}
    st, en, smp = {}, {}, []
    for line in open(path, errors="replace"):
        m = re.match(r"ctr phase=(start|end) dir=hw_counters name=(\S+) value=(\d+)", line)
        if m:
            (st if m.group(1) == "start" else en)[m.group(2)] = int(m.group(3))
        elif line.startswith("smp "):
            t = kvtok(line)
            smp.append({k: int(v) for k, v in t.items() if v.isdigit()})
    if not en:
        return None, smp, st
    return {k: en[k] - st[k] for k in st if k in en}, smp, st


def sample_fields(f, smp, st, rain_delta):
    if not smp or "rp_cnp_handled" not in st or rain_delta is None:
        return
    rp0, src0 = st["rp_cnp_handled"], st.get("roce_slow_restart_cnps")
    rp_end = rp0 + rain_delta.get("rp_cnp_handled", 0)
    rows = [s for s in smp if "rp_cnp_handled" in s and "roce_slow_restart_cnps" in s]
    if not rows or src0 is None:
        return
    f["smp_diff_max"] = max(abs((s["rp_cnp_handled"] - rp0) - (s["roce_slow_restart_cnps"] - src0)) for s in rows)
    inc = [s for s in rows if s["rp_cnp_handled"] > rp0]
    if inc:
        f["smp_first_inc_ns"] = inc[0]["mono_ns"]
    if rp_end > rp0:
        reach = [s for s in rows if s["rp_cnp_handled"] >= rp_end]
        if reach:
            f["smp_last_inc_ns"] = reach[0]["mono_ns"]


# ---------------------------------------------------------------- load trials
trials = []


def load_A():
    for d in sorted(glob.glob(os.path.join(R, "A", "runs", "lp_*_t*"))):
        tag = os.path.basename(d)
        m = re.match(r"lp_(.+)_t(\d+)$", tag)
        fault, tn = m.group(1), int(m.group(2))
        t = dict(part="A", cell=A_CELLS.get(fault, "?"), tag=tag, fault=fault, trial=tn, excl="", fields={})
        csvs = glob.glob(os.path.join(d, f"{fault}_*.csv"))
        srvs = glob.glob(os.path.join(d, f"{fault}_*.srv.log"))
        srv = open(srvs[0], errors="replace").read() if srvs else ""
        rows = list(csv.DictReader(open(csvs[0]))) if csvs else []
        if not rows:
            t["excl"] = "runner_fail"
        else:
            for k, v in rows[0].items():
                if v is None or v == "":
                    continue
                if k == "vendor_err":
                    t["fields"][k] = v.lower()
                elif k in INT_FIELDS:
                    try:
                        t["fields"][k] = int(v)
                    except ValueError:
                        pass
                else:
                    t["fields"][k] = v
        if not t["excl"]:
            if fault in SERVER_SIDE and f"fault_applied fault={fault}" not in srv:
                t["excl"] = "not_applied"
            if fault == "retry_proc_sigkill" and "proc_sigkill: raising SIGKILL" not in srv:
                t["excl"] = "not_applied"
            if fault.startswith("live_stop_") and "stall_end" not in srv:
                t["excl"] = "not_applied"
        dr, smp, st = evrec(os.path.join(R, "A", "evrec", tag + ".evrec.rain"))
        ds, _, _ = evrec(os.path.join(R, "A", "evrec", tag + ".evrec.sunny"))
        t["rain"], t["sunny"] = dr, ds
        t["ctr_ok"] = dr is not None and ds is not None
        sample_fields(t["fields"], smp, st, dr)
        ta = t["fields"].get("truth_alive")
        t["truth_ok"] = ta in (0, 1)
        trials.append(t)


def load_B():
    for r0 in sorted(glob.glob(os.path.join(R, "B", "logs", "rec1_*_timeout_b*_t*_r0.kv"))):
        stem = r0[:-len("_r0.kv")]
        m = re.match(r"rec1_(\w+?)_timeout_(b(\d)_t(\d+))$", os.path.basename(stem))
        fault, tag, k, tn = m.group(1), m.group(2), m.group(3), int(m.group(4))
        t = dict(part="B", cell="B" + k, tag=tag, fault=fault, trial=tn, excl="", fields={})
        f = t["fields"]
        r1p, metap = stem + "_r1.kv", stem + "_meta.txt"
        r0l = open(r0, errors="replace").read().splitlines()
        r1l = open(r1p, errors="replace").read().splitlines() if os.path.exists(r1p) else None
        if not r0l or not r1l:
            t["excl"] = "runner_fail"
        fev = [x for x in r0l if x.startswith("fault ev=")]
        rev = [x for x in r0l if x.startswith("rec ev=")]
        f["n_fault_ev"], f["n_rec_ev"] = len(fev), len(rev)
        if fev:
            tq = kvtok(fev[0]).get("t_query")
            if tq is not None:
                f["fault_t_query"] = num(tq)
        if rev:
            kv = kvtok(rev[0])
            for src, dst in (("outcome", "rec_outcome"), ("reason", "rec_reason")):
                if src in kv:
                    f[dst] = kv[src]
            for src, dst in (("t_prep", "rec_t_prep"), ("t_ack", "rec_t_ack"), ("t_decl", "rec_t_decl")):
                if src in kv:
                    f[dst] = num(kv[src])
        fin0 = [x for x in r0l if x.startswith("iters_ok=")]
        if fin0:
            f["r0_iters_ok"] = int(kvtok(fin0[-1])["iters_ok"])
        off = [x for x in r0l if x.startswith("clock_offset_ms=")]
        if off:
            f["r0_clock_offset_ms"] = num(kvtok(off[0])["clock_offset_ms"])
        stall_ok = False
        if r1l is not None:
            fin1 = [x for x in r1l if x.startswith("iters_ok=")]
            if fin1:
                kv = kvtok(fin1[-1])
                f["r1_iters_ok"] = int(kv["iters_ok"])
                f["r1_data_check"] = kv.get("data_check")
            idx = [i for i, x in enumerate(r1l) if x.startswith("stall on=")]
            if idx:
                kv = kvtok(r1l[idx[0]])
                if "end_mono_ms" in kv:
                    stall_ok = True
                    f["r1_stall_end_mono_ms"] = num(kv["end_mono_ms"])
                    if "r0_clock_offset_ms" in f:
                        f["r1_stall_end_r0clock"] = f["r1_stall_end_mono_ms"] - f["r0_clock_offset_ms"]
                f["r1_n_rxrec_after_stall"] = sum(1 for x in r1l[idx[0] + 1:] if x.startswith("rxrec "))
        if os.path.exists(metap):
            meta = kvtok(open(metap).read())
            for kk in ("r0rc", "r1_alive_at_r0_exit"):
                if kk in meta:
                    f[kk] = int(meta[kk])
        if not t["excl"]:
            if fault == "F3" and not fev:
                t["excl"] = "not_applied"
            if t["cell"] in ("B1", "B2", "B3") and not stall_ok:
                t["excl"] = "not_applied"
        dr, smp, st = evrec(os.path.join(R, "B", "evrec", tag + ".evrec.rain"))
        ds, _, _ = evrec(os.path.join(R, "B", "evrec", tag + ".evrec.sunny"))
        t["rain"], t["sunny"] = dr, ds
        t["ctr_ok"] = dr is not None and ds is not None
        t["truth_ok"] = r1l is not None
        trials.append(t)


load_A()
load_B()
ALL_CELLS = A_ORDER + B_ORDER


# ---------------------------------------------------------------- expression evaluation
def trial_ns(t):
    ns = NS(t["fields"])
    ns["rain"] = Ctr(t["rain"])
    ns["sunny"] = Ctr(t["sunny"])
    return ns


def eval_trial(code, t):
    try:
        return bool(eval(code, {"__builtins__": {}}, trial_ns(t))), True
    except Unobs:
        return False, False


def func_result(name, code, ts):
    n = len(ts)
    res = [(t, *eval_trial(code, t)) for t in ts]
    true = [t for t, v, o in res if v]
    false_obs = [t for t, v, o in res if o and not v]
    unobs = [t for t, v, o in res if not o]
    if n == 0:
        return None, dict(n=0, hits=0, missed=[], unobs=[])
    if name == "ALL":
        ok = len(true) == n
        missed = [t["tag"] for t in false_obs] + [t["tag"] + "(관측 불가)" for t in unobs]
    elif name == "MOST":
        ok = len(true) >= math.ceil(0.9 * n) and not false_obs
        missed = [t["tag"] for t in false_obs] + [t["tag"] + "(관측 불가)" for t in unobs]
    else:  # NONE
        ok = len(true) == 0
        missed = [t["tag"] for t in true]
    hits = len(true) if name != "NONE" else n - len(true)
    return ok, dict(n=n, hits=hits, missed=missed, unobs=[t["tag"] for t in unobs])


def eval_clause(expr, ts):
    """expr: ALL/MOST/NONE calls joined by 'and'. -> (verdict, [(func_src, info)])"""
    tree = ast.parse(expr, mode="eval").body
    calls = tree.values if isinstance(tree, ast.BoolOp) and isinstance(tree.op, ast.And) else [tree]
    out, verdicts = [], []
    for c in calls:
        assert isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in ("ALL", "MOST", "NONE"), \
            ast.dump(c)
        code = compile(ast.Expression(body=c.args[0]), "<acc>", "eval")
        v, info = func_result(c.func.id, code, ts)
        verdicts.append(v)
        info["verdict"] = v
        out.append((ast.get_source_segment(expr, c), info))
    if any(v is False for v in verdicts):
        return False, out
    if any(v is None for v in verdicts):
        return None, out
    return True, out


def cells_of(row):
    rid, cells = row["id"], row["cells"]
    m = re.match(r"^([AB]\d+)\b", cells)
    if rid[0] in "AB" and m:
        return [m.group(1)]
    if cells.startswith("every trial of every cell"):
        return ALL_CELLS
    if cells.startswith("every Part A cell"):
        return A_ORDER
    return [c for c in re.findall(r"\b([AB]\d{1,2})\b", cells) if c in ALL_CELLS]


def spec_cells(spec, mentioned):
    m = re.match(r"every other Part A cell except (.+)$", spec)
    if m:
        ex = set(re.findall(r"\b([AB]\d{1,2})\b", m.group(1))) | set(mentioned)
        return [c for c in A_ORDER if c not in ex]
    return [c for c in re.findall(r"\b([AB]\d{1,2})\b", spec) if c in ALL_CELLS]


def scored(cell, rid):
    ts = [t for t in trials if t["cell"] == cell and not t["excl"]]
    if rid.startswith("K"):
        ts = [t for t in ts if t["ctr_ok"]]
    if rid.startswith("O"):
        ts = [t for t in ts if t["truth_ok"]]
    return ts


def score_row(row):
    rid, acc = row["id"], row["acceptance"]
    clauses = []   # (cells, filter, expr)
    m = re.match(r"^per cell over trials with (status==\d+): (.+)$", acc)
    if m:
        clauses.append((cells_of(row), m.group(1), m.group(2)))
    elif rid.startswith("O"):
        parts = [p.strip() for p in acc.split("; ")]
        specs = [p.split(": ", 1) for p in parts]
        named = [c for s, _ in specs if not s.startswith("every other") for c in spec_cells(s, [])]
        for s, e in specs:
            clauses.append((spec_cells(s, named), None, e))
    else:
        clauses.append((cells_of(row), None, acc))
    results, verdicts = [], []
    for cells, filt, expr in clauses:
        fcode = compile(filt, "<filter>", "eval") if filt else None
        for c in cells:
            ts = scored(c, rid)
            if fcode:
                ts = [t for t in ts if eval_trial(fcode, t)[0]]
            v, out = eval_clause(expr, ts)
            verdicts.append(v)
            results.append(dict(cell=c, verdict=v, calls=out, n=len(ts)))
    if any(v is False for v in verdicts):
        final = "틀림"
    elif all(v is None for v in verdicts):
        final = "자료 없음"
    elif any(v is None for v in verdicts):
        final = "자료 없음(일부 셀)"
    else:
        final = "맞음"
    return final, results


# ---------------------------------------------------------------- run
preds = list(csv.DictReader(open(PRED)))
scored_rows = []
for row in preds:
    if row["kind"] == "source":
        continue
    final, res = score_row(row)
    n = sum(r["n"] for r in res)
    hits = sum(min(c[1]["hits"] for c in r["calls"]) if r["calls"] else 0 for r in res)
    missed = sorted({m for r in res for c in r["calls"] for m in c[1]["missed"]})
    scored_rows.append(dict(id=row["id"], kind=row["kind"], label=LABEL.get(row["id"], row["predicted"]), n=n,
                            hits=hits, verdict=final, missed=missed, detail=res))

# trials_scored.csv
FIELDS = ["status", "vendor_err", "detect_ns", "cqe_ns", "sub_cause", "peer_alive", "srv_qp_state", "srv_async",
          "verify_ok", "truth_alive", "truth_how", "resync_ms", "stale_lines", "rec_outcome", "rec_reason",
          "rec_t_prep", "rec_t_ack", "rec_t_decl", "fault_t_query", "n_fault_ev", "n_rec_ev", "r0rc",
          "r0_iters_ok", "r1_iters_ok", "r1_data_check", "r1_stall_end_r0clock", "r1_n_rxrec_after_stall",
          "r1_alive_at_r0_exit", "smp_diff_max"]
CTRS = ["rp_cnp_handled", "roce_slow_restart_cnps", "roce_adp_retrans", "local_ack_timeout_err", "req_cqe_error",
        "np_cnp_sent", "np_ecn_marked_roce_packets", "rp_cnp_ignored"]
with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["part", "cell", "tag", "fault", "trial", "excluded"] + FIELDS + [f"rain.{c}" for c in CTRS] +
               ["sunny.rp_cnp_handled", "sunny.np_cnp_sent"])
    for t in sorted(trials, key=lambda t: (ALL_CELLS.index(t["cell"]) if t["cell"] in ALL_CELLS else 99, t["trial"])):
        f = t["fields"]
        w.writerow([t["part"], t["cell"], t["tag"], t["fault"], t["trial"], t["excl"]] +
                   [f.get(k, "") for k in FIELDS] +
                   [(t["rain"] or {}).get(c, "") for c in CTRS] +
                   [(t["sunny"] or {}).get("rp_cnp_handled", ""), (t["sunny"] or {}).get("np_cnp_sent", "")])

# SCORE.md
L = []
L.append(f"# live_peer 채점 결과\n")
L.append(f"`score.py`가 `predictions.csv`(태그 `prereg/live-peer-v1`)의 판정식을 EXPERIMENT.md 3.0절 규칙 그대로 적용한 "
         f"결과다. 원자료: `{os.path.relpath(R, os.path.dirname(HERE))}` 아래 `A/`, `B/`(Release). 소스 예측 8줄은 "
         f"채점하지 않는다. 시행별 값은 [trials_scored.csv](trials_scored.csv).\n")
ok = sum(r["verdict"] == "맞음" for r in scored_rows)
L.append(f"측정 예측 {len(scored_rows)}줄 중 맞음 {ok}, 틀림 {sum(r['verdict'] == '틀림' for r in scored_rows)}, "
         f"자료 없음 {sum(r['verdict'].startswith('자료 없음') for r in scored_rows)}.\n")
L.append("## 시행 수\n")
L.append("| 셀 | 시행 | 채점 | 장애 미적용 | 실행기 실패 | 카운터 관측 불가 | 실제 생존 미정 |")
L.append("|---|--:|--:|--:|--:|--:|--:|")
for c in ALL_CELLS:
    ts = [t for t in trials if t["cell"] == c]
    sc = [t for t in ts if not t["excl"]]
    L.append(f"| {CELL_LABEL[c]} ({c}) | {len(ts)} | {len(sc)} | {sum(t['excl'] == 'not_applied' for t in ts)} | "
             f"{sum(t['excl'] == 'runner_fail' for t in ts)} | {sum(not t['ctr_ok'] for t in sc)} | "
             f"{sum(not t['truth_ok'] for t in sc)} |")
L.append("")
excl = [t for t in trials if t["excl"]]
if excl:
    L.append("따로 센 시행: " + ", ".join(f"`{t['tag']}`({EXCL_LABEL[t['excl']]})" for t in excl) + "\n")
else:
    L.append("따로 센 시행: 없음.\n")
L.append("## 예측별 판정\n")
L.append("| 예측 | id | n | 맞은 시행 | 판정 | 놓친 시행 |")
L.append("|---|---|--:|--:|---|---|")
for r in scored_rows:
    miss = ", ".join(f"`{m}`" for m in r["missed"]) if r["missed"] else "-"
    L.append(f"| {r['label']} | ({r['id']}) | {r['n']} | {r['hits']} | {r['verdict']} | {miss} |")
L.append("")
L.append("n은 줄이 적용된 셀들의 채점 시행 수 합이고, 맞은 시행은 셀마다 판정식 항목 중 가장 적게 맞은 항목의 수를 더한 값이다. "
         "판정식 항목별 수는 아래에 있다.\n")
L.append("## 판정식 항목별 수\n")
L.append("| 예측 | 셀 | n | 항목 | 맞은 시행 | 결과 |")
L.append("|---|---|--:|---|--:|---|")
for r in scored_rows:
    for d in r["detail"]:
        for src, info in d["calls"]:
            res = {None: "자료 없음", True: "맞음", False: "틀림"}[info["verdict"]]
            L.append(f"| ({r['id']}) | {CELL_LABEL[d['cell']]} ({d['cell']}) | {info['n']} | `{src}` | {info['hits']} | {res} |")
L.append("")
open(os.path.join(R, "SCORE.md"), "w").write("\n".join(L) + "\n")
json.dump([{**{k: v for k, v in r.items() if k != "detail"}, "detail": [
    {"cell": d["cell"], "n": d["n"], "verdict": d["verdict"],
     "calls": [{"expr": s, **i} for s, i in d["calls"]]} for d in r["detail"]]} for r in scored_rows],
          open(os.path.join(R, "score.json"), "w"), ensure_ascii=False, indent=1)
print("\n".join(f"{r['id']:4} n={r['n']:3} hits={r['hits']:3} {r['verdict']}" for r in scored_rows))
