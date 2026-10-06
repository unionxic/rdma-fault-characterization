#!/usr/bin/env python3
"""score.py <campaign_root> [--old-gin <dir>] - score the 24 pre-registered predictions.

Reads the campaign outputs of cells.sh (one folder per stack) and writes SCORE.md and score.json
into <campaign_root>. Acceptance follows PREDICTIONS.md: a categorical cell holds if at least 90 %
of its trials show the predicted outcome and no trial shows an outcome outside it. A cell without
trials is "no data". --old-gin points at the retained GIN logs of 2026-09-23 for the blind part
of EV3a.
"""
import csv, glob, json, math, os, re, sys

ROOT = os.path.abspath(sys.argv[1])
OLD_GIN = sys.argv[sys.argv.index("--old-gin") + 1] if "--old-gin" in sys.argv else None
CTRS = ["req_cqe_error", "req_cqe_flush_error", "local_ack_timeout_err", "req_remote_access_errors"]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def evrec_delta(path):
    """{counter: end - start} from one evrec file (hw_counters only)."""
    start, end = {}, {}
    try:
        for line in open(path, errors="replace"):
            m = re.match(r"ctr phase=(start|end) dir=hw_counters name=(\S+) value=(\d+)", line)
            if m:
                (start if m.group(1) == "start" else end)[m.group(2)] = int(m.group(3))
    except FileNotFoundError:
        return None
    if not start or not end:
        return None
    return {k: end[k] - start[k] for k in start if k in end}


def kv(path):
    d = {}
    try:
        for tok in open(path, errors="replace").read().split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                d[k] = v
    except FileNotFoundError:
        pass
    return d


def text(path):
    try:
        return open(path, errors="replace").read()
    except FileNotFoundError:
        return ""


ASYNC_ERR = re.compile(r"async fatal event|IBV_EVENT_(QP_FATAL|QP_REQ_ERR|QP_ACCESS_ERR|CQ_ERR|DEVICE_FATAL)", re.I)
results = []


def score(pid, cells, outcomes, rule="90", note=""):
    """outcomes: list of (tag, True|False|None); None = not observable (not counted)."""
    obs = [(t, o) for t, o in outcomes if o is not None]
    n, k = len(obs), sum(1 for _, o in obs if o)
    if n == 0:
        verdict = "no data"
    elif rule == "all":
        verdict = "holds" if k == n else "fails"
    else:
        verdict = "holds" if k >= math.ceil(0.9 * n) else "fails"
    lo, hi = wilson(k, n)
    misses = [t for t, o in obs if not o]
    results.append(dict(id=pid, cells=cells, n=n, hits=k, rule=rule, verdict=verdict,
                        wilson=[round(lo, 3), round(hi, 3)], misses=misses,
                        not_observable=sum(1 for _, o in outcomes if o is None), note=note))


# ---------------- CPU harness ----------------
def cpu_trials():
    d = os.path.join(ROOT, "cpu")
    by_fault = {}
    for f in sorted(glob.glob(os.path.join(d, "csv", "*.csv"))):
        m = re.match(r"(.+)_(\d{8}_\d{6})\.csv$", os.path.basename(f))
        if not m:
            continue
        rows = list(csv.DictReader(open(f)))
        if rows:
            by_fault.setdefault(m.group(1), []).append(rows[-1])
    out = []
    for fault, rows in by_fault.items():
        for i, r in enumerate(rows, 1):
            tag = f"cpu_{fault}_t{i}"
            out.append((fault, tag, r, evrec_delta(os.path.join(d, "evrec", tag + ".evrec.rain")),
                        text(os.path.join(d, "logs", tag + ".out"))))
    return out


cpu = cpu_trials()
def qp_events(s):
    return [] if s in ("none", "-", "?", "") else [e.split("/")[0] for e in s.split(";")]

def only(ev, name):
    return bool(ev) and all(e == name for e in ev)

score("EV1a", "CPU responder, F2", [(t, only(qp_events(r["srv_async"]), "IBV_EVENT_QP_ACCESS_ERR")) for f, t, r, _, _ in cpu if f == "rem_access"])
score("EV1b", "CPU responder, rem_inv_req", [(t, only(qp_events(r["srv_async"]), "IBV_EVENT_QP_REQ_ERR")) for f, t, r, _, _ in cpu if f == "rem_inv_req"])
score("EV1c", "CPU responder, rnr", [(t, r["srv_async"] == "none") for f, t, r, _, _ in cpu if f == "rnr"])
score("EV1d", "CPU responder, F1 F3 F4 F0 partial_write",
      [(t, None if r["srv_async"] == "-" else r["srv_async"] == "none") for f, t, r, _, _ in cpu
       if f in ("local_qp_err", "retry_server_qp_err", "retry_proc_sigkill", "none", "partial_write")],
      note="F4: responder dead, not observable")
score("EV1e", "CPU requester, all faults", [(t, r["cli_async"] == "none") for f, t, r, _, _ in cpu])
score("EV2a", "CPU responder QP state, F2 rem_inv_req", [(t, r["srv_qp_state"] == "ERR") for f, t, r, _, _ in cpu if f in ("rem_access", "rem_inv_req")])
score("EV2b", "CPU responder QP state, rnr F1", [(t, r["srv_qp_state"] == "RTS") for f, t, r, _, _ in cpu if f in ("rnr", "local_qp_err")])

def d_ok(delta, f):
    if delta is None:
        return None
    return f(delta)

ev5c = [(t, d_ok(dl, lambda d: d.get("local_ack_timeout_err", 0) >= 6 and d.get("req_cqe_error", 0) >= 1))
        for f, t, r, dl, _ in cpu if f in ("retry_server_qp_err", "retry_proc_sigkill")]
ev5d = [(t, d_ok(dl, lambda d: d.get("req_cqe_error", 0) >= 1)) for f, t, r, dl, _ in cpu if f in ("local_qp_err", "rem_access")]

def teardown_ms(txt, who):
    m = re.search(rf"\[{who}\] teardown \(ep_close\) returned after ([\d.]+) ms", txt)
    return float(m.group(1)) if m else None

t1 = []
for f, t, r, _, txt in cpu:
    if f != "none":
        continue
    cl = teardown_ms(txt, "client")
    t1.append((t, r["status_name"] in ("success", "SUCCESS") or r["status"] in ("0", "0x0")) if cl is None
              else (t, cl <= 5000 and r["status"] in ("0", "0x0")))

# ---------------- GIN (gp gg gq) ----------------
def gin_rows(stack, backend_prefix):
    d = os.path.join(ROOT, stack)
    f = os.path.join(d, f"{stack}.csv")
    if not os.path.exists(f):
        return []
    out = []
    for r in csv.DictReader(open(f)):
        base = f"{backend_prefix}_{r['fault']}_{r['wait_mode']}_t{r['trial']}"
        tag = f"{stack}_{r['fault']}_{r['wait_mode']}_t{r['trial']}"
        lg = os.path.join(d, "logs", base)
        out.append(dict(row=r, tag=tag, r0=kv(lg + "_r0.kv"), r1=kv(lg + "_r1.kv"),
                        l0=text(lg + "_r0.log"), l1=text(lg + "_r1.log"),
                        e0=evrec_delta(os.path.join(d, "evrec", tag + ".evrec.rain")),
                        e1=evrec_delta(os.path.join(d, "evrec", tag + ".evrec.sunny"))))
    return out

gp = gin_rows("gp", "proxy")
gg = gin_rows("gg", "gdaki")
gq = gin_rows("gq", "ring_c1")   # gin_q4 names logs <cq_type>_c<classify>_...

def r1_access_event(g):
    return bool(re.search(r"async fatal event on QP.*local access violation", g["l1"]))

score("EV3a", "GP target, F2: async fatal event on QP (access violation) in r1 log",
      [(g["tag"], r1_access_event(g)) for g in gp if g["row"]["fault"] == "F2"])
score("EV3b", "GP target, F2: r1 async error stays success",
      [(g["tag"], g["r1"].get("host_error", "?") == "none") for g in gp if g["row"]["fault"] == "F2"])
score("EV3c", "GP target, F1 F3 F4: no async QP event on r1",
      [(g["tag"], not re.search(r"async fatal event on QP", g["l1"])) for g in gp if g["row"]["fault"] in ("F1", "F3", "F4")])
ev5c += [(g["tag"], d_ok(g["e0"], lambda d: d.get("local_ack_timeout_err", 0) >= 6 and d.get("req_cqe_error", 0) >= 1))
         for g in gp if g["row"]["fault"] in ("F3", "F4")]
ev5d += [(g["tag"], d_ok(g["e0"], lambda d: d.get("req_cqe_error", 0) >= 1)) for g in gp if g["row"]["fault"] in ("F1", "F2")]

def silent(g):
    r = g["row"]
    return r.get("silent_success") == "1" or (r.get("init_silent_iters") not in (None, "", "0", "-1"))

score("D1", "GG GPU doorbell, F2 F3 F4 blocking: flush success on the failed op and a host error",
      [(g["tag"], silent(g) and g["row"].get("host_error", "none") not in ("none", ""))
       for g in gg if g["row"]["fault"] in ("F2", "F3", "F4") and g["row"]["wait_mode"] == "blocking"],
      note="device -EIO is source-only; scored on the flush and the host error")
score("D2", "GG blocking F4: first flush after the kill returns success",
      [(g["tag"], silent(g)) for g in gg if g["row"]["fault"] == "F4" and g["row"]["wait_mode"] == "blocking"])

def td_ok(k, bound=5000):
    return k.get("teardown") == "clean" and float(k.get("teardown_ms", "1e9")) <= bound

for stack, rows in (("gp", gp), ("gg", gg), ("gq", gq)):
    t1 += [(g["tag"], td_ok(g["r0"]) and td_ok(g["r1"])) for g in rows if g["row"]["fault"] == "none"]
t3 = [(g["tag"], g["r0"].get("teardown") == "clean" and g["r1"].get("teardown") == "hang")
      for rows in (gg, gq) for g in rows if g["row"]["fault"] in ("F1", "F2", "F3") and g["row"]["wait_mode"] == "blocking"]

# ---------------- NVSHMEM (nvo nvd nvf) ----------------
def nv_runs(stack, sub_glob):
    d = os.path.join(ROOT, stack)
    out = []
    for log0 in sorted(glob.glob(os.path.join(d, sub_glob, "*.pe0.log"))):
        base = log0[:-len(".pe0.log")]
        out.append(dict(name=os.path.basename(base), pe0=text(log0), pe1=text(base + ".pe1.log"), dir=os.path.dirname(log0)))
    return out

nvo = nv_runs("nvo", "runs")
def nvo_tag(name):
    m = re.match(r"(stock|fix)_(cpu_host_memory|gpu)_kill(\d)_t(\d+)", name)
    vid = {"stock_cpu_host_memory": "NC", "stock_gpu": "NG", "fix_cpu_host_memory": "NX"}[f"{m.group(1)}_{m.group(2)}"]
    return f"nvo_{vid}_kill{m.group(3)}_t{m.group(4)}", vid, int(m.group(3))

def fin(txt, pe):
    m = re.search(rf"PE {pe}: nvshmem_finalize returned after ([\d.]+) ms", txt)
    if m:
        return float(m.group(1))
    return "hang" if re.search(rf"PE {pe}: nvshmem_finalize did not return", txt) else None

ev5b, t2 = [], []
for r in nvo:
    tag, vid, k = nvo_tag(r["name"])
    e0 = evrec_delta(os.path.join(ROOT, "nvo", "evrec", tag + ".evrec.rain"))
    e1 = evrec_delta(os.path.join(ROOT, "nvo", "evrec", tag + ".evrec.sunny"))
    if k == 1:
        ev5b.append((tag, None if e0 is None or e1 is None else all(e0.get(c, 0) == 0 and e1.get(c, 0) == 0 for c in CTRS)))
        t2.append((tag, fin(r["pe0"], 0) == "hang"))
    else:
        f0, f1 = fin(r["pe0"], 0), fin(r["pe1"], 1)
        t1.append((tag, isinstance(f0, float) and isinstance(f1, float) and f0 <= 5000 and f1 <= 5000))

nvd = []
for h in ("auto", "cpu_host_memory"):
    for r in nv_runs("nvd", f"runs_{h}"):
        m = re.match(r"(F\w+?)_timeout_t(\d+)", r["name"])
        tag = f"nvd_{h}_{m.group(1)}_t{m.group(2)}" if m else r["name"]
        r["tag"] = tag
        nvd.append(r)
nvf = nv_runs("nvf", "runs")
for r in nvf:
    m = re.match(r"(\w+?)_timeout_ft1_rec1_prop_t(\d+)", r["name"])
    r["tag"] = f"nvf_{m.group(1)}_t{m.group(2)}" if m else r["name"]
    r["fault"] = m.group(1) if m else "?"

def tdn(txt, rank):
    m = re.search(rf"TEARDOWN rank {rank} \S* ?finalize_ms=([\d.]+) returned=(\d)", txt) or \
        re.search(rf"TEARDOWN rank {rank} .*finalize_ms=([\d.]+) returned=(\d)", txt)
    return (float(m.group(1)), m.group(2) == "1") if m else None

t4 = []
for r in nvf:
    a, b = tdn(r["pe0"], 0), tdn(r["pe1"], 1)
    if r["fault"] == "none":
        t1.append((r["tag"], bool(a and b and a[1] and b[1] and a[0] <= 5000 and b[0] <= 5000)))
    elif r["fault"] in ("F1", "F3"):
        t4.append((r["tag"], bool(a and b and a[1] and b[1])))
    elif r["fault"] in ("F2b", "F4"):
        t4.append((r["tag"], bool(a and a[1])))

# EV4: no QP-affiliated async error on any DEVX stack, either rank
ev4 = []
for g in gg + gq:
    ev4.append((g["tag"], not ASYNC_ERR.search(g["l0"] + g["l1"])))
for r in nvo:
    ev4.append((nvo_tag(r["name"])[0], not ASYNC_ERR.search(r["pe0"] + r["pe1"])))
for r in nvd + nvf:
    ev4.append((r["tag"], not ASYNC_ERR.search(r["pe0"] + r["pe1"])))
score("EV4", "GG GQ NC NG NX ND NF, both ranks: no QP-affiliated async error", ev4, rule="all")

# EV5a: DEVX stacks, counters +0 on both nodes, every trial
ev5a = []
def zero(e0, e1):
    if e0 is None or e1 is None:
        return None
    return all(e0.get(c, 0) == 0 and e1.get(c, 0) == 0 for c in CTRS)
for g in gg + gq:
    ev5a.append((g["tag"], zero(g["e0"], g["e1"])))
for st, rows in (("nvd", nvd), ("nvf", nvf)):
    for r in rows:
        ev5a.append((r["tag"], zero(evrec_delta(os.path.join(ROOT, st, "evrec", r["tag"] + ".evrec.rain")),
                                    evrec_delta(os.path.join(ROOT, st, "evrec", r["tag"] + ".evrec.sunny")))))
score("EV5a", "GG GQ NF ND, both nodes: 4 error counters +0", ev5a, rule="all")
score("EV5b", "NC NG NX F4, both nodes: 4 error counters +0", ev5b, rule="all")
score("EV5c", "CPU GP requester, F3 F4: local_ack_timeout_err >= 6 and req_cqe_error >= 1", ev5c)
score("EV5d", "CPU GP requester, F1 F2: req_cqe_error >= 1", ev5d)

# ---------------- NCCL net_ib ----------------
net = []
for f in sorted(glob.glob(os.path.join(ROOT, "net", "runs", "*", "results.csv"))):
    for r in csv.DictReader(open(f)):
        r["tag"] = "net_" + os.path.basename(os.path.dirname(f))
        net.append(r)
score("NET1a", "NET stock path, F2: requester status 10 / 0x88 and ncclRemoteError",
      [(r["tag"], r.get("r0_rem_access") == "1" and r.get("r0_vendor", "").lower() == "0x88" and r.get("r0_api") == "ncclRemoteError")
       for r in net if r["test"] == "F2stock"])
score("NET1b", "NET stock path, F2: target async fatal event and a target API error",
      [(r["tag"], r.get("r1_async_fatal") == "1" and r.get("r1_api", "") not in ("", "-", "ncclSuccess", "ok"))
       for r in net if r["test"] == "F2stock"])
score("NET1c", "NET Stage 2, F2: declined, ncclRemoteError, no replay",
      [(r["tag"], r.get("verdict") == "DECLINED" and r.get("r0_api") == "ncclRemoteError" and r.get("rec_send", "0") in ("0", ""))
       for r in net if r["test"] == "F2"])
t1 += [(r["tag"], r.get("verdict", "").lower() == "pass") for r in net if r["test"] == "T0s"]

score("T1", "every variant, F0: no error and teardown within 5 s on both ranks", t1)
score("T2", "NC NG NX, F4: PE 0 nvshmem_finalize does not return within 30 s", t2, rule="all")
score("T3", "GG GQ blocking F1-F3: r0 teardown returns, r1 does not", t3)
score("T4", "NF: F1 F3 finalize returns on both PEs; F2 F4 returns after ft_abort", t4)

# ---------------- blind part of EV3a: retained 2026-09-23 GIN proxy F2 r1 logs ----------------
if OLD_GIN:
    old = sorted(glob.glob(os.path.join(OLD_GIN, "**", "proxy_F2_*r1*.log"), recursive=True))
    score("EV3a-blind", "retained 2026-09-23 GIN proxy F2 r1 logs",
          [(os.path.basename(p), bool(re.search(r"async fatal event on QP.*local access violation", text(p)))) for p in old],
          rule="all")

order = ["EV1a", "EV1b", "EV1c", "EV1d", "EV1e", "EV2a", "EV2b", "EV3a", "EV3a-blind", "EV3b", "EV3c", "EV4",
         "EV5a", "EV5b", "EV5c", "EV5d", "NET1a", "NET1b", "NET1c", "D1", "D2", "T1", "T2", "T3", "T4"]
results.sort(key=lambda r: order.index(r["id"]) if r["id"] in order else 99)
json.dump(results, open(os.path.join(ROOT, "score.json"), "w"), indent=1)
with open(os.path.join(ROOT, "SCORE.md"), "w") as f:
    f.write("# Campaign score\n\nScored by `campaign/score.py` against `PREDICTIONS.md` (tag prereg/propagation-v1).\n\n")
    f.write("| id | cells | n | hits | rule | verdict | Wilson 95% | misses | note |\n|---|---|--:|--:|---|---|---|---|---|\n")
    for r in results:
        miss = ", ".join(r["misses"][:6]) + (" ..." if len(r["misses"]) > 6 else "")
        no = f" {r['not_observable']} not observable." if r["not_observable"] else ""
        f.write(f"| {r['id']} | {r['cells']} | {r['n']} | {r['hits']} | {r['rule']} | **{r['verdict']}** | "
                f"{r['wilson'][0]:.2f}-{r['wilson'][1]:.2f} | {miss} | {r['note']}{no} |\n")
print(open(os.path.join(ROOT, "SCORE.md")).read())
