#!/usr/bin/env python3
"""recount.py <results/20261007> [predictions.csv] - independent recount of the live_peer main run.

Written for the QA step of harness/live_peer/EXPERIMENT.md without reading score.py, SCORE.md, score.json
or trials_scored.csv. It reads only raw files:
  A/runs/<tag>/<fault>_<stamp>.csv and .srv.log, A/evrec/<tag>.evrec.{rain,sunny}, A/logs/<tag>.out and
  .pstate, A/trials.log, A/runner.log;
  B/logs/rec1_<F3|none>_timeout_<tag>_{r0.kv,r1.kv,meta.txt}, B/logs/<tag>.out, B/evrec/<tag>.evrec.*,
  B/trials.log, B/runner.log.
Fields follow EXPERIMENT.md 3.0 and the exclusions follow section 8 (tag prereg/live-peer-v1).
Acceptance: the quantifier bodies are taken verbatim from predictions.csv and evaluated as Python
expressions on each trial's fields, with the 3.0 semantics:
  ALL(e)  every scored trial has e true (a trial whose fields are not all recorded is not true);
  MOST(e) true in at least ceil(0.9 n) trials and false in 0 trials whose fields are all recorded;
  NONE(e) true in 0 trials.
Multi-cell rows are evaluated per cell; only the cell scoping of the segmented rows (K2, O1-O4) is written
out here (CELLS_OF and SEGMENTS). K rows drop trials without an evrec end record of the node(s) the row
reads; O rows drop trials whose ground truth is undetermined (truth_alive -1, or no r1 kv).
Prints the trial-set checks, per-prediction verdicts with misses, value ranges, the misjudgment tables and
the safety records. Read-only on its input.
"""
import ast, csv, glob, hashlib, math, os, re, sys, types, collections

PREREG_SHA = "877aa1d48b614ee14ec3ef55cc17dc9c38b51c9adc68aa6b2378f1b3548a27bd"

CELLS_A = [("A0", 5, "none"), ("A1", 5, "retry_server_qp_err"), ("A2", 5, "retry_proc_sigkill"),
           ("A3", 10, "live_qp_reset"), ("A4", 10, "live_qp_init"), ("A5", 10, "live_qp_rtr"),
           ("A6", 10, "live_transient"), ("A7", 10, "live_stop_err"), ("A8", 10, "live_stop_ok"),
           ("A9", 10, "live_ctl_close"), ("A10", 5, "rnr"), ("A11", 5, "live_qp_recreate")]
# key, n, fault, stall ms (0 = none), stall on
CELLS_B = [("B0", 5, "F3", 0, None), ("B1", 10, "F3", 1000, "req"), ("B2", 10, "F3", 6000, "req"),
           ("B3", 5, "none", 6000, "iter")]
A_KEYS = [c[0] for c in CELLS_A]
B_KEYS = [c[0] for c in CELLS_B]
SERVER_SIDE = {"A1", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A11"}   # section 8: fault_applied needed
STALL_A = {"A7", "A8"}

INT_COLS = {"iter", "detect_ns", "status", "peer_alive", "auto_recoverable", "recover_ns", "verify_ok",
            "cnt_delta", "cqe_ns", "t_post_mono_ns", "resync_ms", "stale_lines", "truth_alive", "mtu_bytes"}


def die(msg):
    print("ERROR:", msg)
    sys.exit(1)


# ---------------------------------------------------------------- raw readers
RE_CTR = re.compile(r"^ctr phase=(start|end) dir=(\S+) name=(\S+) value=(-?\d+)$")
RE_SMP = re.compile(r"^smp mono_ns=(\d+) (.*)$")


def read_evrec(path):
    r = {"exists": os.path.exists(path), "start": {}, "end": {}, "smp": [], "has_end": False, "ports": []}
    if not r["exists"]:
        return r
    for line in open(path, errors="replace"):
        line = line.rstrip("\n")
        m = RE_CTR.match(line)
        if m:
            (r["start"] if m.group(1) == "start" else r["end"])[(m.group(2), m.group(3))] = int(m.group(4))
            continue
        m = RE_SMP.match(line)
        if m:
            vals = {k: int(v) for k, v in (t.split("=") for t in m.group(2).split())}
            r["smp"].append((int(m.group(1)), vals))
            continue
        if line.startswith("end "):
            r["has_end"] = True
        elif line.startswith("port "):
            r["ports"].append(line)
    # "end record": the end line and the end snapshot of hw_counters
    r["has_end"] = r["has_end"] and any(k[0] == "hw_counters" for k in r["end"])
    return r


def deltas(ev):
    if not ev["has_end"]:
        return None
    d = {}
    for (dr, name), v in ev["end"].items():
        if dr == "hw_counters" and (dr, name) in ev["start"]:
            d[name] = v - ev["start"][(dr, name)]
    return d


def kv_tokens(line):
    """'a=1 b=two words c=3' -> {'a': '1', 'b': 'two words', 'c': '3'} (first word may be a record name)."""
    out, last = {}, None
    for tok in line.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
            last = k
        elif last is not None:
            out[last] += " " + tok
    return out


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def inum(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- part A
def load_A(root):
    trials, problems = [], []
    runs = sorted(glob.glob(os.path.join(root, "A", "runs", "*")))
    fault_to_key = {f: k for k, _, f in CELLS_A}
    for d in runs:
        tag = os.path.basename(d)
        m = re.match(r"^lp_(.+)_t(\d+)$", tag)
        if not m or m.group(1) not in fault_to_key:
            problems.append(f"unexpected run dir {tag}")
            continue
        fault, tn = m.group(1), int(m.group(2))
        key = fault_to_key[fault]
        t = {"part": "A", "cell": key, "tag": tag, "tn": tn, "fault": fault}
        csvs = glob.glob(os.path.join(d, f"{fault}_*.csv"))
        srvs = glob.glob(os.path.join(d, f"{fault}_*.srv.log"))
        t["n_csv"], t["n_srv"] = len(csvs), len(srvs)
        rows = list(csv.DictReader(open(csvs[0]))) if csvs else []
        t["n_rows"] = len(rows)
        f = {}
        if rows:
            for k, v in rows[0].items():
                if v is None or v == "":
                    f[k] = None
                elif k in INT_COLS:
                    f[k] = inum(v)
                elif k == "vendor_err":
                    f[k] = v.lower()
                else:
                    f[k] = v
        t["f"] = f
        srv = open(srvs[0]).read() if srvs else ""
        t["srv"] = srv
        mp = re.search(r"\[server\] pid (\d+)", srv)
        t["srv_pid"] = int(mp.group(1)) if mp else None
        mfa = re.search(r"\[server\] fault_applied fault=(\S+) mono_ns=(\d+)", srv)
        t["fault_applied"] = mfa.group(1) if mfa else None
        t["fault_applied_ns"] = int(mfa.group(2)) if mfa else None
        t["sigkill_line"] = "[server] proc_sigkill" in srv
        msb = re.search(r"\[server\] stall_begin mono_ns=(\d+) ms=(\d+)", srv)
        mse = re.search(r"\[server\] stall_end mono_ns=(\d+) measured_ms=([\d.]+)", srv)
        t["stall_ms_cfg"] = int(msb.group(2)) if msb else None
        t["stall_measured_ms"] = float(mse.group(2)) if mse else None
        t["stall_end"] = mse is not None
        mra = re.search(r"\[server\] rearm mono_ns=(\d+)", srv)
        t["rearm_after_fault_ms"] = (int(mra.group(1)) - t["fault_applied_ns"]) / 1e6 if mra and mfa else None
        mcfg = re.search(r"LIVE_STOP_MS=(\d+) LIVE_TRANSIENT_MS=(\d+)", srv)
        t["cfg"] = (int(mcfg.group(1)), int(mcfg.group(2))) if mcfg else None
        mal = re.search(r"\[server\] answered 'ALIVE (\d+) (\S+)'", srv)
        t["srv_alive_pid"] = int(mal.group(1)) if mal else None
        # independent liveness from the server log: it handled a command after the fault
        after = srv.split("fault_applied", 1)[1] if mfa else srv
        t["srv_handled_after"] = bool(re.search(r"\[server\] (QUERIED|RESYNCED|bye|answered 'ALIVE)", after))
        t["srv_last_line"] = [l for l in srv.splitlines() if l.strip()][-1] if srv.strip() else ""
        out_p = os.path.join(root, "A", "logs", tag + ".out")
        out = open(out_p, errors="replace").read() if os.path.exists(out_p) else ""
        mca = re.search(r"ALIVE\? -> 'ALIVE (\d+) (\S+)'", out)
        t["cli_alive_pid"] = int(mca.group(1)) if mca else None
        t["out_warn_noquery"] = "no QUERIED answer" in out
        ps_p = os.path.join(root, "A", "logs", tag + ".pstate")
        if os.path.exists(ps_p):
            ps = open(ps_p).read()
            mps = re.search(r"^(\d+)\s+(T\S*)\s+probe_server", ps, re.M)
            t["pstate_T"] = "state T seen" in ps
            t["pstate_pid"] = int(mps.group(1)) if mps else None
        else:
            t["pstate_T"] = None
            t["pstate_pid"] = None
        t["ev"] = {n: read_evrec(os.path.join(root, "A", "evrec", f"{tag}.evrec.{n}")) for n in ("rain", "sunny")}
        trials.append(t)
    return trials, problems


# ---------------------------------------------------------------- part B
def load_B(root):
    trials, problems = [], []
    metas = sorted(glob.glob(os.path.join(root, "B", "logs", "rec1_*_timeout_*_meta.txt")))
    key_of = {k: (k, n, f, ms, on) for k, n, f, ms, on in CELLS_B}
    seen = set()
    for mp in metas:
        m = re.match(r"^rec1_(F3|none)_timeout_(b(\d+)_t(\d+))_meta\.txt$", os.path.basename(mp))
        if not m:
            problems.append(f"unexpected meta {mp}")
            continue
        fault, tag, k, tn = m.group(1), m.group(2), "B" + m.group(3), int(m.group(4))
        seen.add(tag)
        if k not in key_of:
            problems.append(f"unknown cell {tag}")
            continue
        stem = mp[:-len("_meta.txt")]
        t = {"part": "B", "cell": k, "tag": tag, "tn": tn, "fault": fault}
        meta = kv_tokens(open(mp).read())
        t["meta"] = meta
        r0p, r1p = stem + "_r0.kv", stem + "_r1.kv"
        t["r0_exists"] = os.path.exists(r0p) and os.path.getsize(r0p) > 0
        t["r1_exists"] = os.path.exists(r1p) and os.path.getsize(r1p) > 0
        r0 = open(r0p).read().splitlines() if t["r0_exists"] else []
        r1 = open(r1p).read().splitlines() if t["r1_exists"] else []
        f = {}
        fault_ev = [l for l in r0 if l.startswith("fault ev=")]
        rec_ev = [l for l in r0 if l.startswith("rec ev=")]
        f["n_fault_ev"] = len(fault_ev) if t["r0_exists"] else None
        f["n_rec_ev"] = len(rec_ev) if t["r0_exists"] else None
        fe = kv_tokens(fault_ev[0]) if fault_ev else {}
        re_ = kv_tokens(rec_ev[0]) if rec_ev else {}
        f["fault_t_query"] = fnum(fe.get("t_query"))
        f["rec_outcome"] = re_.get("outcome")
        f["rec_reason"] = re_.get("reason")
        f["rec_t_prep"] = fnum(re_.get("t_prep"))
        f["rec_t_ack"] = fnum(re_.get("t_ack"))
        f["rec_t_decl"] = fnum(re_.get("t_decl"))
        t["rec_t_kret"] = fnum(re_.get("t_kret"))
        t["fault_fp"] = fe.get("fp")
        t["fault_class"] = fe.get("class")

        def last_iters(lines):
            l = [x for x in lines if x.startswith("iters_ok=")]
            return kv_tokens(l[-1]) if l else {}
        i0, i1 = last_iters(r0), last_iters(r1)
        f["r0_iters_ok"] = inum(i0.get("iters_ok"))
        f["r1_iters_ok"] = inum(i1.get("iters_ok"))
        f["r1_data_check"] = i1.get("data_check")
        f["r0rc"] = inum(meta.get("r0rc"))
        f["r1_alive_at_r0_exit"] = inum(meta.get("r1_alive_at_r0_exit"))
        off = [l for l in r0 if l.startswith("clock_offset_ms=")]
        t["clock_offset_ms"] = fnum(kv_tokens(off[0]).get("clock_offset_ms")) if off else None
        st_idx = next((i for i, l in enumerate(r1) if l.startswith("stall ")), None)
        if st_idx is not None:
            s = kv_tokens(r1[st_idx])
            t["stall"] = s
            end = fnum(s.get("end_mono_ms"))
            beg = fnum(s.get("begin_mono_ms"))
            off = t["clock_offset_ms"]
            f["r1_stall_end_r0clock"] = end - off if end is not None and off is not None else None
            t["r1_stall_begin_r0clock"] = beg - off if beg is not None and off is not None else None
            f["r1_n_rxrec_after_stall"] = sum(1 for l in r1[st_idx + 1:] if l.startswith("rxrec "))
        else:
            t["stall"] = None
            f["r1_stall_end_r0clock"] = None
            t["r1_stall_begin_r0clock"] = None
            f["r1_n_rxrec_after_stall"] = None
        t["r1_rxrec_total"] = sum(1 for l in r1 if l.startswith("rxrec "))
        t["r1_rx_declined"] = any(l.startswith("rx_declined") for l in r1)
        t["f"] = f
        t["ev"] = {n: read_evrec(os.path.join(root, "B", "evrec", f"{tag}.evrec.{n}")) for n in ("rain", "sunny")}
        trials.append(t)
    return trials, problems


# ---------------------------------------------------------------- acceptance evaluation
def quantifiers(text):
    out, i = [], 0
    while True:
        m = re.compile(r"\b(ALL|MOST|NONE)\(").search(text, i)
        if not m:
            break
        j, depth, q = m.end(), 1, None
        while depth:
            c = text[j]
            if q:
                if c == q:
                    q = None
            elif c in "'\"":
                q = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        out.append((m.group(1), text[m.end():j - 1]))
        i = j
    return out


def fields_of(body):
    names = set()
    for node in ast.walk(ast.parse(body, mode="eval")):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            names.add(node.value.id + "." + node.attr)
        elif isinstance(node, ast.Name) and node.id not in ("rain", "sunny"):
            names.add(node.id)
    return names


def namespace(t):
    ns = dict(t["f"])
    for node in ("rain", "sunny"):
        d = t.get("d_" + node) or {}
        ns[node] = types.SimpleNamespace(**d)
    ns.update(t.get("smpf", {}))
    return ns


def value(t, name):
    if "." in name:
        node, c = name.split(".")
        d = t.get("d_" + node)
        return None if d is None else d.get(c)
    if name in t.get("smpf", {}):
        return t["smpf"][name]
    return t["f"].get(name)


def eval_q(kind, body, ts):
    need = fields_of(body)
    code = compile(body, "<acceptance>", "eval")
    n = len(ts)
    true, false_rec, unobs, misses = 0, 0, 0, []
    for t in ts:
        if any(value(t, x) is None for x in need):
            unobs += 1
            if kind != "NONE":
                misses.append(t["tag"] + "(unobservable)")
            continue
        ok = bool(eval(code, {}, namespace(t)))
        if ok:
            true += 1
            if kind == "NONE":
                misses.append(t["tag"])
        else:
            false_rec += 1
            if kind in ("ALL", "MOST"):
                misses.append(t["tag"])
    if n == 0:
        res = None
    elif kind == "ALL":
        res = true == n
    elif kind == "MOST":
        res = true >= math.ceil(0.9 * n) and false_rec == 0
    else:
        res = true == 0
    return {"kind": kind, "n": n, "true": true, "false": false_rec, "unobs": unobs, "pass": res, "misses": misses}


ALL_A_EXCEPT_A2 = [k for k in A_KEYS if k != "A2"]
CELLS_OF = {"A0": ["A0"], "A1": ["A1"], "A2": ["A2"], "A3a": ["A3"], "A3b": ["A3"], "A4a": ["A4"], "A4b": ["A4"],
            "A5": ["A5"], "A6": ["A6"], "A7a": ["A7"], "A7b": ["A7"], "A8": ["A8"], "A9a": ["A9"], "A9b": ["A9"],
            "A10": ["A10"], "A11": ["A11"], "B0": ["B0"], "B1": ["B1"], "B2a": ["B2"], "B2b": ["B2"], "B3": ["B3"],
            "K1": A_KEYS + B_KEYS, "K2": ["A1", "A2", "A3", "A4", "A7", "A9", "A11"], "K3a": ["A6"], "K3b": ["A6"],
            "K3c": ["A6"], "K4": ["A0", "A5", "A8", "A10", "B3"], "K5": A_KEYS, "K6": ["B0", "B1", "B2"],
            "K7": ["A1", "A3", "A6"]}
# segmented rows: (label in predictions.csv, cells)
SEGMENTS = {
    "O1": {"A9": ["A9"], "every other Part A cell except A2": [k for k in ALL_A_EXCEPT_A2 if k != "A9"]},
    "O2": {"A7 and A9": ["A7", "A9"],
           "every other Part A cell except A2": [k for k in ALL_A_EXCEPT_A2 if k not in ("A7", "A9")]},
    "O3": {"B2": ["B2"], "B0, B1, B3": ["B0", "B1", "B3"]},
    "O4": {"A8": ["A8"], "B3": ["B3"]},
}


def scored(trials, cell, row_id, body):
    ts = [t for t in trials if t["cell"] == cell and not t["excluded"]]
    if row_id.startswith("K"):
        need = fields_of(body)
        nodes = {x.split(".")[0] for x in need if "." in x}
        if any(x.startswith("smp_") for x in need):
            nodes.add("rain")
        ts = [t for t in ts if all(t.get("d_" + nd) is not None for nd in nodes)]
        if row_id == "K2":
            ts = [t for t in ts if t["f"].get("status") == 12]
    if row_id.startswith("O"):
        ts = [t for t in ts if t["truth_known"]]
    return ts


def evaluate(pred, trials):
    rid, acc = pred["id"], pred["acceptance"]
    parts = []   # (cells, text)
    if rid in SEGMENTS:
        for seg in acc.split(";"):
            label, text = seg.split(":", 1)
            label = label.strip()
            if label not in SEGMENTS[rid]:
                die(f"{rid}: unknown segment label {label!r}")
            parts.append((SEGMENTS[rid][label], text))
    elif rid == "K2":
        prefix, text = acc.split(":", 1)
        assert prefix.strip() == "per cell over trials with status==12"
        parts.append((CELLS_OF[rid], text))
    else:
        parts.append((CELLS_OF[rid], acc))
    res = []
    for cells, text in parts:
        qs = quantifiers(text)
        rest = re.sub(r"\b(ALL|MOST|NONE)\((?:[^()]|\([^()]*\))*\)", "", text)
        if re.sub(r"\band\b", "", rest).strip():
            die(f"{rid}: unparsed text {rest!r}")
        for cell in cells:
            for kind, body in qs:
                ts = scored(trials, cell, rid, body)
                r = eval_q(kind, body, ts)
                r.update(cell=cell, body=body.strip())
                res.append(r)
    if all(r["pass"] is None for r in res):
        verdict = "no data"
    elif all(r["pass"] for r in res):
        verdict = "holds"
    else:
        verdict = "fails"
    return verdict, res


# ---------------------------------------------------------------- helpers for ranges
def rng(vals, scale=1.0, fmt="{:.1f}"):
    v = [x for x in vals if x is not None]
    if not v:
        return "-"
    lo, hi = min(v) / scale, max(v) / scale
    return (fmt.format(lo) if lo == hi else fmt.format(lo) + "–" + fmt.format(hi)) + f" (n={len(v)})"


def main():
    if len(sys.argv) < 2:
        die(__doc__)
    root = sys.argv[1].rstrip("/")
    here = os.path.dirname(os.path.abspath(__file__))
    pred_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "..", "predictions.csv")
    sha = hashlib.sha256(open(pred_path, "rb").read()).hexdigest()
    print(f"predictions.csv sha256 {sha} {'== PREREG.txt' if sha == PREREG_SHA else '!= PREREG.txt'}")
    preds = list(csv.DictReader(open(pred_path)))
    measured = [p for p in preds if p["kind"] in ("N", "R", "C")]
    print(f"prediction rows: {len(preds)}, measured {len(measured)} "
          f"({collections.Counter(p['kind'] for p in measured)}), source {sum(p['kind'] == 'source' for p in preds)}")

    A, pa = load_A(root)
    B, pb = load_B(root)
    trials = A + B
    for p in pa + pb:
        print("PROBLEM:", p)

    # ---------------------------------------------------- 1. trial set
    print("\n== 1. trial set (section 7) and exclusions (section 8)")
    plan = {k: n for k, n, _ in CELLS_A}
    plan.update({k: n for k, n, *_ in CELLS_B})
    tl = {}
    for part in ("A", "B"):
        for line in open(os.path.join(root, part, "trials.log")):
            w = line.split()
            if w and w[0] != "STOP":
                tl.setdefault(w[0], []).append(w[1])
            elif w:
                print("trials.log STOP line:", line.strip())
    dup = [k for k, v in tl.items() if len(v) > 1]
    badrc = [k for k, v in tl.items() if any(x != "rc=0" for x in v)]
    print(f"trials.log entries {sum(len(v) for v in tl.values())}, unique tags {len(tl)}, duplicates {dup}, rc!=0 {badrc}")
    tags = {t["tag"] for t in trials}
    print(f"tags in trials.log without raw files: {sorted(set(tl) - tags)}; raw without trials.log: {sorted(tags - set(tl))}")
    for k in A_KEYS + B_KEYS:
        tn = sorted(t["tn"] for t in trials if t["cell"] == k)
        gaps = tn != list(range(1, plan[k] + 1))
        print(f"  {k}: planned {plan[k]}, found {len(tn)}, t-numbers {'contiguous 1..' + str(plan[k]) if not gaps else tn}")
    print(f"  total part A {len(A)}, part B {len(B)}, all {len(trials)}")

    for t in trials:
        f = t["f"]
        why = []
        if t["part"] == "A":
            if t["n_csv"] != 1 or t["n_rows"] != 1 or t["n_srv"] != 1:
                why.append(f"runner failure (csv {t['n_csv']}, rows {t['n_rows']}, srv {t['n_srv']})")
            if t["cell"] in SERVER_SIDE and t["fault_applied"] != t["fault"]:
                why.append(f"fault not applied ({t['fault_applied']})")
            if t["cell"] == "A2" and not t["sigkill_line"]:
                why.append("no proc_sigkill line")
            if t["cell"] in STALL_A and not t["stall_end"]:
                why.append("no stall_end")
            if f.get("fault") != t["fault"]:
                why.append(f"csv fault {f.get('fault')}")
        else:
            if not (t["r0_exists"] and t["r1_exists"]):
                why.append("runner failure (kv missing)")
            if t["fault"] == "F3" and not f["n_fault_ev"]:
                why.append("no fault ev record")
            if t["cell"] in ("B1", "B2", "B3") and t["stall"] is None:
                why.append("no stall record")
        t["excluded"] = bool(why)
        t["why"] = why
        for nd in ("rain", "sunny"):
            t["d_" + nd] = deltas(t["ev"][nd])
        if t["part"] == "A":
            t["truth_known"] = f.get("truth_alive") in (0, 1)
        else:
            t["truth_known"] = t["r1_exists"]
        # sample fields (3.0) on rain
        ev = t["ev"]["rain"]
        if ev["smp"] and ev["has_end"]:
            s0 = ev["start"][("hw_counters", "rp_cnp_handled")]
            r0 = ev["start"][("hw_counters", "roce_slow_restart_cnps")]
            e0 = ev["end"][("hw_counters", "rp_cnp_handled")]
            diffs = [abs((v["rp_cnp_handled"] - s0) - (v["roce_slow_restart_cnps"] - r0)) for _, v in ev["smp"]]
            first = next((ns for ns, v in ev["smp"] if v["rp_cnp_handled"] > s0), None)
            last = next((ns for ns, v in ev["smp"] if v["rp_cnp_handled"] == e0), None)
            t["smpf"] = {"smp_diff_max": max(diffs), "smp_first_inc_ns": first, "smp_last_inc_ns": last}
            t["n_smp"] = len(ev["smp"])
            t["smp_end_reached"] = ev["smp"][-1][1]["rp_cnp_handled"] == e0
        else:
            t["smpf"] = {}
    exc = [(t["tag"], t["why"]) for t in trials if t["excluded"]]
    print(f"excluded (fault not applied / runner failure): {len(exc)} {exc}")
    noend = [(t["tag"], nd) for t in trials for nd in ("rain", "sunny") if t["d_" + nd] is None]
    print(f"evrec records without end record: {len(noend)} {noend}")
    unk = [t["tag"] for t in trials if not t["truth_known"]]
    print(f"ground truth undetermined: {len(unk)} {unk}")

    # configuration checks
    print("\n-- configuration and fault evidence")
    for k in A_KEYS:
        ts = [t for t in A if t["cell"] == k]
        cfg = collections.Counter(t["cfg"] for t in ts)
        rec = collections.Counter(t["f"].get("recovery") for t in ts)
        line = f"  {k}: srv cfg {dict(cfg)}, recovery {dict(rec)}"
        if k in SERVER_SIDE:
            line += f", fault_applied {sum(t['fault_applied'] == t['fault'] for t in ts)}/{len(ts)}"
        if k == "A2":
            line += f", proc_sigkill line {sum(t['sigkill_line'] for t in ts)}/{len(ts)}"
        if k in STALL_A:
            line += (f", stall ms {sorted({t['stall_ms_cfg'] for t in ts})}, measured "
                     f"{rng([t['stall_measured_ms'] for t in ts], fmt='{:.3f}')} ms, pstate T {sum(bool(t['pstate_T']) for t in ts)}"
                     f"/{len(ts)}, pstate pid == server pid {sum(t['pstate_pid'] == t['srv_pid'] for t in ts)}/{len(ts)}")
        if k == "A6":
            line += f", rearm after fault_applied {rng([t['rearm_after_fault_ms'] for t in ts], fmt='{:.1f}')} ms"
        print(line)
    for k, n, fault, ms, on in CELLS_B:
        ts = [t for t in B if t["cell"] == k]
        meta = collections.Counter((t["meta"].get("fault"), t["meta"].get("inject"), t["meta"].get("wait"),
                                    t["meta"].get("iters"), t["meta"].get("bundle"), t["meta"].get("left")) for t in ts)
        st = collections.Counter((t["stall"] or {}).get("ms", "none") + "/" + (t["stall"] or {}).get("on", "-") +
                                 "/it=" + (t["stall"] or {}).get("it", "-") for t in ts)
        meas = [fnum((t["stall"] or {}).get("measured_ms")) for t in ts]
        fev = collections.Counter((t["fault_class"], t["fault_fp"]) for t in ts)
        print(f"  {k}: meta (fault, inject, wait, iters, bundle, left) {dict(meta)}; stall {dict(st)} measured "
              f"{rng(meas, fmt='{:.3f}')} ms; fault ev {dict(fev)}")

    # ---------------------------------------------------- 2. predictions
    print("\n== 2. measured predictions")
    summary = []
    for p in measured:
        verdict, res = evaluate(p, trials)
        summary.append((p["id"], verdict))
        print(f"\n[{p['id']}] {verdict.upper()}  ({p['kind']}) {p['acceptance']}")
        for r in res:
            mark = {True: "ok", False: "MISS", None: "n=0"}[r["pass"]]
            print(f"   {r['cell']:>4} {r['kind']:<4} n={r['n']:<3} true={r['true']:<3} false={r['false']:<3} "
                  f"unobs={r['unobs']:<2} {mark:<4} {r['body']}" + (f"  misses: {r['misses']}" if r["misses"] else ""))
    print("\nverdicts:", ", ".join(f"{i} {v}" for i, v in summary))
    print("holds", sum(v == "holds" for _, v in summary), "fails", sum(v == "fails" for _, v in summary),
          "no data", sum(v == "no data" for _, v in summary))

    # ---------------------------------------------------- values
    print("\n== values (per cell, over the scored trials of that cell)")
    for k in A_KEYS:
        ts = [t for t in A if t["cell"] == k and not t["excluded"]]
        sv = collections.Counter(f"{t['f']['status']}/{t['f']['vendor_err']}" for t in ts)
        sc = collections.Counter(t["f"]["sub_cause"] for t in ts)
        qs = collections.Counter(t["f"]["srv_qp_state"] for t in ts)
        sa = collections.Counter(re.sub(r"/qpn=.*", "", t["f"]["srv_async"] or "") for t in ts)
        ta = collections.Counter(f"{t['f']['truth_alive']}({t['f']['truth_how']})" for t in ts)
        vo = collections.Counter(t["f"]["verify_ok"] for t in ts)
        pa = collections.Counter(t["f"]["peer_alive"] for t in ts)
        ar = collections.Counter(t["f"]["auto_recoverable"] for t in ts)
        print(f"  {k} n={len(ts)}: status {dict(sv)}; detect_ns {rng([t['f']['detect_ns'] for t in ts if t['f']['detect_ns'] not in (None, -1)], 1e6, '{:.2f}')} ms; "
              f"cqe_ns {rng([t['f']['cqe_ns'] for t in ts], 1e6, '{:.4f}')} ms; sub_cause {dict(sc)}; srv_qp_state {dict(qs)}; "
              f"srv_async {dict(sa)}; truth {dict(ta)}; verify_ok {dict(vo)}; peer_alive {dict(pa)}; auto_recoverable {dict(ar)}; "
              f"resync_ms {rng([t['f']['resync_ms'] for t in ts if t['f']['resync_ms'] not in (None, -1)], 1, '{:.0f}')}; "
              f"stale_lines {dict(collections.Counter(t['f']['stale_lines'] for t in ts))}; "
              f"srv handled a command after the fault {sum(t['srv_handled_after'] for t in ts)}/{len(ts)}; "
              f"'no QUERIED answer' warning {sum(t['out_warn_noquery'] for t in ts)}")
        if k == "A9":
            print(f"      A9 ALIVE answer pid == server pid: srv log {sum(t['srv_alive_pid'] == t['srv_pid'] for t in ts)}/{len(ts)}, "
                  f"client log {sum(t['cli_alive_pid'] == t['srv_pid'] for t in ts)}/{len(ts)}")
        if k == "A2":
            print(f"      A2 server log ends at the SIGKILL line: {sum('proc_sigkill' in t['srv_last_line'] for t in ts)}/{len(ts)}")
    for k in A_KEYS:
        ts = [t for t in A if t["cell"] == k and t["d_rain"] is not None and t["d_sunny"] is not None]
        def c(nd, name):
            return rng([t["d_" + nd].get(name) for t in ts], 1, "{:.0f}")
        print(f"  {k} counters n={len(ts)}: rain rp_cnp_handled {c('rain', 'rp_cnp_handled')}, roce_slow_restart_cnps "
              f"{c('rain', 'roce_slow_restart_cnps')}, roce_adp_retrans {c('rain', 'roce_adp_retrans')}, local_ack_timeout_err "
              f"{c('rain', 'local_ack_timeout_err')}, req_cqe_error {c('rain', 'req_cqe_error')}, rnr_nak_retry_err "
              f"{c('rain', 'rnr_nak_retry_err')}; sunny rp_cnp_handled {c('sunny', 'rp_cnp_handled')}, "
              f"sunny roce_slow_restart_cnps {c('sunny', 'roce_slow_restart_cnps')}, sunny local_ack_timeout_err "
              f"{c('sunny', 'local_ack_timeout_err')}")
        if any(t["smpf"] for t in ts):
            print(f"      samples: n_smp {rng([t.get('n_smp') for t in ts], 1, '{:.0f}')}, smp_diff_max "
                  f"{rng([t['smpf'].get('smp_diff_max') for t in ts], 1, '{:.0f}')}, first inc - post "
                  f"{rng([t['smpf']['smp_first_inc_ns'] - t['f']['t_post_mono_ns'] for t in ts if t['smpf'].get('smp_first_inc_ns')], 1e6, '{:.1f}')} ms, "
                  f"post+cqe+100ms - last inc "
                  f"{rng([t['f']['t_post_mono_ns'] + t['f']['cqe_ns'] + 100000000 - t['smpf']['smp_last_inc_ns'] for t in ts if t['smpf'].get('smp_last_inc_ns')], 1e6, '{:.1f}')} ms, "
                  f"last inc - (post+cqe) "
                  f"{rng([t['smpf']['smp_last_inc_ns'] - t['f']['t_post_mono_ns'] - t['f']['cqe_ns'] for t in ts if t['smpf'].get('smp_last_inc_ns')], 1e6, '{:.1f}')} ms")
        # identities
        idt = [(t["d_rain"]["rp_cnp_handled"], t["d_rain"]["roce_slow_restart_cnps"], t["d_rain"]["roce_adp_retrans"],
                t["d_rain"]["local_ack_timeout_err"]) for t in ts]
        if any(x[0] for x in idt):
            print(f"      rp==slow {sum(a == b for a, b, _, _ in idt)}/{len(idt)}, rp==adp+late-1 {sum(a == c + d - 1 for a, _, c, d in idt)}"
                  f"/{len(idt)}, rp==adp+late {sum(a == c + d for a, _, c, d in idt)}/{len(idt)}, tuples (rp, slow, adp, late) "
                  f"{sorted(collections.Counter(idt).items())}")
    for k in B_KEYS:
        ts = [t for t in B if t["cell"] == k and not t["excluded"]]
        f = lambda t: t["f"]
        oc = collections.Counter(f"{f(t)['rec_outcome']}/{f(t)['rec_reason']}" for t in ts)
        print(f"  {k} n={len(ts)}: outcome {dict(oc)}; r0rc {dict(collections.Counter(f(t)['r0rc'] for t in ts))}; "
              f"r1rc {dict(collections.Counter(t['meta'].get('r1rc') for t in ts))}; "
              f"r1_alive_at_r0_exit {dict(collections.Counter(f(t)['r1_alive_at_r0_exit'] for t in ts))}; "
              f"iters r0 {dict(collections.Counter(f(t)['r0_iters_ok'] for t in ts))} r1 {dict(collections.Counter(f(t)['r1_iters_ok'] for t in ts))}; "
              f"r1 data_check {dict(collections.Counter(f(t)['r1_data_check'] for t in ts))}; n_fault_ev "
              f"{dict(collections.Counter(f(t)['n_fault_ev'] for t in ts))}, n_rec_ev {dict(collections.Counter(f(t)['n_rec_ev'] for t in ts))}")
        ack = [f(t)["rec_t_ack"] - f(t)["rec_t_prep"] for t in ts if f(t)["rec_t_ack"] is not None]
        dq = [f(t)["rec_t_decl"] - f(t)["fault_t_query"] for t in ts if f(t)["rec_t_decl"] is not None]
        dk = [f(t)["rec_t_decl"] - t["rec_t_kret"] for t in ts if f(t)["rec_t_decl"] is not None]
        se = [f(t)["r1_stall_end_r0clock"] - f(t)["rec_t_decl"] for t in ts
              if f(t)["rec_t_decl"] is not None and f(t)["r1_stall_end_r0clock"] is not None]
        sb = [t["r1_stall_begin_r0clock"] - f(t)["fault_t_query"] for t in ts
              if t["r1_stall_begin_r0clock"] is not None and f(t)["fault_t_query"] is not None]
        db = [f(t)["rec_t_decl"] - t["r1_stall_begin_r0clock"] for t in ts
              if t["r1_stall_begin_r0clock"] is not None and f(t)["rec_t_decl"] is not None]
        print(f"      t_ack - t_prep {rng(ack, 1, '{:.1f}')} ms; t_decl - t_query {rng(dq, 1, '{:.1f}')} ms; "
              f"t_decl - t_kret {rng(dk, 1, '{:.1f}')} ms; stall end (r0 clock) - t_decl {rng(se, 1, '{:.1f}')} ms; "
              f"stall begin (r0 clock) - t_query {rng(sb, 1, '{:.2f}')} ms; t_decl - stall begin (r0 clock) {rng(db, 1, '{:.1f}')} ms; "
              f"rxrec after stall {dict(collections.Counter(f(t)['r1_n_rxrec_after_stall'] for t in ts))}; "
              f"clock rtt ok")
        if k == "B2":
            for t in sorted(ts, key=lambda x: x["tn"]):
                print(f"      {t['tag']}: t_decl - t_query {f(t)['rec_t_decl'] - f(t)['fault_t_query']:.3f} ms, "
                      f"t_decl - t_kret {f(t)['rec_t_decl'] - t['rec_t_kret']:.3f} ms, stall end - t_decl "
                      f"{f(t)['r1_stall_end_r0clock'] - f(t)['rec_t_decl']:.3f} ms")
    for k in B_KEYS:
        ts = [t for t in B if t["cell"] == k and t["d_rain"] is not None and t["d_sunny"] is not None]
        def c(nd, name):
            return rng([t["d_" + nd].get(name) for t in ts], 1, "{:.0f}")
        print(f"  {k} counters n={len(ts)}: rain rp_cnp_handled {c('rain', 'rp_cnp_handled')}, roce_slow_restart_cnps "
              f"{c('rain', 'roce_slow_restart_cnps')}, roce_adp_retrans {c('rain', 'roce_adp_retrans')}, local_ack_timeout_err "
              f"{c('rain', 'local_ack_timeout_err')}; sunny rp_cnp_handled {c('sunny', 'rp_cnp_handled')}, "
              f"sunny roce_slow_restart_cnps {c('sunny', 'roce_slow_restart_cnps')}, sunny local_ack_timeout_err "
              f"{c('sunny', 'local_ack_timeout_err')}")
    cong = ["np_cnp_sent", "np_ecn_marked_roce_packets", "rp_cnp_ignored"]
    nz = [(t["tag"], nd, x, t["d_" + nd][x]) for t in trials for nd in ("rain", "sunny") if t["d_" + nd]
          for x in cong if t["d_" + nd].get(x)]
    print(f"  congestion counters non-zero: {nz} over {sum(1 for t in trials for nd in ('rain', 'sunny') if t['d_' + nd])} records")
    # sunny: which counters moved at all
    mv = collections.Counter()
    for t in trials:
        if t["d_sunny"]:
            for x, v in t["d_sunny"].items():
                if v and not x.startswith(("rx_", "resp_")):
                    mv[(t["cell"], x)] += 1
    print(f"  sunny hw_counters that moved (cell, name): count {dict(sorted(mv.items()))}")

    # ---------------------------------------------------- misjudgment tables
    print("\n== misjudgment (section 6 definitions)")
    for k in A_KEYS:
        ts = [t for t in A if t["cell"] == k and not t["excluded"] and t["truth_known"]]
        dm = sum(t["f"]["truth_alive"] == 1 and t["f"]["sub_cause"] == "proc_kill" for t in ts)
        um = sum(t["f"]["truth_alive"] == 1 and t["f"]["sub_cause"] in ("proc_kill", "no_answer") for t in ts)
        tab = collections.Counter((t["f"]["truth_alive"], t["f"]["sub_cause"]) for t in ts)
        print(f"  {k}: n={len(ts)} truth x sub_cause {dict(tab)}; death misjudgment {dm}, unrecoverable misjudgment {um}")
    others1 = [t for t in A if t["cell"] not in ("A2", "A9") and t["truth_known"]]
    others2 = [t for t in A if t["cell"] not in ("A2", "A7", "A9") and t["truth_known"]]
    print(f"  pooled: death misjudgment outside A9 (A2 left out) {sum(t['f']['truth_alive'] == 1 and t['f']['sub_cause'] == 'proc_kill' for t in others1)}/{len(others1)}; "
          f"unrecoverable misjudgment outside A7, A9 (A2 left out) "
          f"{sum(t['f']['truth_alive'] == 1 and t['f']['sub_cause'] in ('proc_kill', 'no_answer') for t in others2)}/{len(others2)}")
    for k in B_KEYS:
        ts = [t for t in B if t["cell"] == k and t["truth_known"]]
        dec = sum(t["f"]["rec_outcome"] == "declined" for t in ts)
        mis = sum(t["f"]["rec_outcome"] == "declined" and t["f"]["r1_stall_end_r0clock"] is not None
                  and t["f"]["r1_stall_end_r0clock"] > t["f"]["rec_t_decl"] for t in ts)
        print(f"  {k}: n={len(ts)} declined {dec}, declined while rank 1 resumed after the decline {mis}")
    a8 = [t for t in A if t["cell"] == "A8"]
    b3 = [t for t in B if t["cell"] == "B3"]
    print(f"  missed stall: A8 {sum(t['f']['status'] == 0 and t['f']['sub_cause'] == '-' for t in a8)}/{len(a8)}, "
          f"B3 {sum(t['f']['n_fault_ev'] == 0 and t['f']['n_rec_ev'] == 0 and t['f']['r0rc'] == 0 for t in b3)}/{len(b3)}")

    # ---------------------------------------------------- 3. safety
    print("\n== 3. safety records")
    for part in ("A", "B"):
        rl = open(os.path.join(root, part, "runner.log")).read().splitlines()
        flag = [l for l in rl if re.search(r"SIGCONT|STOP|left after", l)]
        print(f"  {part} runner.log: {rl[0]}; SIGCONT/STOP lines {flag if flag else 'none'}; last: {rl[-1]}")
    lefts = collections.Counter(t["meta"].get("left") for t in B)
    print(f"  B meta left= {dict(lefts)}")
    ports = collections.Counter()
    for t in trials:
        for nd in ("rain", "sunny"):
            for p in t["ev"][nd]["ports"]:
                ports[(nd, re.sub(r"phase=\S+ ", "", p))] += 1
    print(f"  evrec port lines: {dict(ports)}")
    pst = [t for t in A if t["pstate_T"] is not None]
    print(f"  pstate files {len(pst)}: state T seen {sum(t['pstate_T'] for t in pst)}")
    vf = [t["tag"] for t in A if t["f"].get("verify_ok") == 0]
    dc = [t["tag"] for t in B if t["f"]["r1_data_check"] not in ("ok", None)]
    print(f"  stop criteria: verify_ok==0 {vf}; r1 data_check not ok {dc}")

    smoke = root.rstrip("/") + "_smoke"
    if os.path.isdir(smoke):
        na = len(glob.glob(os.path.join(smoke, "A", "runs", "*")))
        nb = len(glob.glob(os.path.join(smoke, "B", "logs", "*_meta.txt")))
        print(f"\nsmoke runs present, not scored: {smoke} A {na}, B {nb}")


if __name__ == "__main__":
    main()
