#!/usr/bin/env python3
"""Independent QA recount of the propagation campaign (results/20261006_campaign).

Reads only raw per-trial files (trials.log, per-rank logs/kv, evrec snapshots, CPU harness
output) and the pre-registered predictions; it does not import or read campaign/score.py,
SCORE.md or score.json. Writes trials.csv and recount_table.md next to this script.

Usage: recount.py            (paths are fixed below; read-only on the repository)
"""
import csv, glob, os, re, subprocess, sys
from collections import defaultdict, OrderedDict

REPO = "/home/unionxic/rdma-error"
PROP = f"{REPO}/harness/gpu-initiated/propagation"
CAMP = f"{PROP}/results/20261006_campaign"
OUT = os.path.dirname(os.path.abspath(__file__))
OLDGIN = ("/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/"
          "scratchpad/qa_dl/raw/harness/gpu-initiated/gin/results/20260923")
NETC = f"{OUT}/net_condensed"     # grep-condensed copies of the 1+ GB net rank logs

CTR4 = ["req_cqe_error", "req_cqe_flush_error", "local_ack_timeout_err", "req_remote_access_errors"]


def rd(p):
    try:
        with open(p, errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return None


def kv(p):
    """last value of each key in a key=value file (gin_fault / gin_q4 .kv)."""
    d = {}
    t = rd(p)
    if t is None:
        return None
    for line in t.splitlines():
        for m in re.finditer(r"(\w+)=(\S+)", line):
            d[m.group(1)] = m.group(2)
    # host_error value may contain spaces: re-read it from the line
    for line in t.splitlines():
        m = re.search(r"host_error=(.*?) host_error_ms=(\S+)", line)
        if m:
            d["host_error"], d["host_error_ms"] = m.group(1), m.group(2)
    okits = re.findall(r"^okit=(\d+)", t, re.M)
    d["_okit_max"] = max(map(int, okits)) if okits else 0
    return d


def evrec(path):
    """-> (start{name:val}, end{name:val}, events, has_end) for dir=hw_counters."""
    t = rd(path)
    if t is None:
        return None
    st, en = {}, {}
    for m in re.finditer(r"^ctr phase=(start|end) dir=hw_counters name=(\S+) value=(\d+)", t, re.M):
        (st if m.group(1) == "start" else en)[m.group(2)] = int(m.group(3))
    me = re.search(r"^end reason=(\S+) events=(\d+)", t, re.M)
    ev_lines = [l for l in t.splitlines() if l.startswith("event")]
    return dict(start=st, end=en, events=int(me.group(2)) if me else None, has_end=bool(me),
                event_lines=ev_lines)


def ctr_delta(stack, tag):
    out = {}
    for node in ("rain", "sunny"):
        e = evrec(f"{CAMP}/{stack}/evrec/{tag}.evrec.{node}")
        if e is None or not e["start"] or not e["end"]:
            out[node] = None
            continue
        out[node] = {c: e["end"].get(c, 0) - e["start"].get(c, 0) for c in CTR4}
        out[node]["_events"] = e["events"]
    return out


# ---------------------------------------------------------------- trials.log / plan
def plan():
    """expected tags per stack, re-derived by hand from campaign/cells.sh."""
    P = OrderedDict()
    P["cpu"] = [f"cpu_{f}_t{t}" for f in ["none", "local_qp_err", "rem_access", "rem_inv_req", "rnr",
                                          "retry_server_qp_err", "retry_proc_sigkill", "partial_write"]
                for t in range(1, (5 if f == "none" else 10) + 1)]
    gp = [("none", "timeout", 5)] + [(f, "timeout", 10) for f in ["F1", "F2", "F3", "F4"]]
    gg = [("none", "timeout", 5), ("F1", "blocking", 5)] + [(f, "blocking", 10) for f in ["F2", "F3", "F4"]]
    P["gp"] = [f"gp_{f}_{m}_t{t}" for f, m, n in gp for t in range(1, n + 1)]
    P["gg"] = [f"gg_{f}_{m}_t{t}" for f, m, n in gg for t in range(1, n + 1)]
    gq = [("none", "timeout"), ("F1", "blocking"), ("F2", "blocking"), ("F3", "blocking"), ("F4", "timeout")]
    P["gq"] = [f"gq_{f}_{m}_t{t}" for f, m in gq for t in range(1, 6)]
    P["nvo"] = [f"nvo_{v}_kill{k}_t{t}" for k in (0, 1) for v in ("NC", "NG", "NX") for t in range(1, 6)]
    P["nvd"] = [f"nvd_{h}_{f}_t{t}" for h in ("auto", "cpu_host_memory") for f in ("F1", "F2b", "F3")
                for t in range(1, 11)]
    P["nvf"] = [f"nvf_{f}_t{t}" for f in ("none", "F1", "F2b", "F3", "F4") for t in range(1, 6)]
    P["net"] = [f"net_{i}_t{t}" for i, n in (("T0s", 5), ("F2", 10), ("F2stock", 10)) for t in range(1, n + 1)]
    return P


def trials_log(stack):
    rows = []
    for line in (rd(f"{CAMP}/{stack}/trials.log") or "").splitlines():
        m = re.match(r"(\S+) rc=(\d+) (\S+) (\S+)", line)
        if m:
            rows.append(dict(tag=m.group(1), rc=int(m.group(2)), t0=m.group(3), t1=m.group(4)))
    return rows


# ---------------------------------------------------------------- per-stack parsers
CPU_F = {"none": "F0", "local_qp_err": "F1", "rem_access": "F2", "rem_inv_req": "rem_inv_req", "rnr": "rnr",
         "retry_server_qp_err": "F3", "retry_proc_sigkill": "F4", "partial_write": "partial_write"}


def parse_cpu(tag):
    t = rd(f"{CAMP}/cpu/logs/{tag}.out")
    m = re.search(r"^\[trial 0\] (\S+): detect=(-?\d+)ns status=(.*?)\((\d+)\) vendor=(\S+) sub=(\S+?)\(.*?"
                  r"srv_qp=(\S+) srv_async=(\S+) cli_async=(\S+)", t, re.M)
    td = re.search(r"teardown \(ep_close\) returned after ([\d.]+) ms", t)
    f = tag.split("_t")[0][4:]
    r = dict(stack="cpu", tag=tag, fault=CPU_F[f], raw_fault=f)
    if m:
        r.update(status=int(m.group(4)), vendor=m.group(5), sub=m.group(6), srv_qp=m.group(7),
                 srv_async=m.group(8), cli_async=m.group(9), detect_ns=int(m.group(2)))
    r["cli_teardown_ms"] = float(td.group(1)) if td else None
    r["ctr"] = ctr_delta("cpu", tag)
    # effective: any fault trial must show a non-success completion at the requester
    r["effective"] = (r["fault"] == "F0") or (m is not None and r["status"] != 0)
    r["eff_note"] = "" if r["effective"] else "no error completion"
    return r


ASYNC_PAT = re.compile(r"async fatal event|IBV_EVENT_|ncclIbAsyncThreadMain|async event", re.I)


def parse_gin(stack, tag):
    _, f, m, tt = tag.split("_")
    t = int(tt[1:])
    if stack == "gq":
        base = f"{CAMP}/gq/logs/ring_c1_{f}_{m}_t{t}"
    else:
        b = "proxy" if stack == "gp" else "gdaki"
        base = f"{CAMP}/{stack}/logs/{b}_{f}_{m}_t{t}"
    r0, r1 = kv(base + "_r0.kv"), kv(base + "_r1.kv")
    l0, l1 = rd(base + "_r0.log") or "", rd(base + "_r1.log") or ""
    out = rd(f"{CAMP}/{stack}/logs/{tag}.out") or ""
    r = dict(stack=stack, tag=tag, fault="F0" if f == "none" else f, mode=m)
    r["r0"], r["r1"] = r0, r1
    r["r1_async_lines"] = [l for l in l1.splitlines() if ASYNC_PAT.search(l)]
    r["r0_async_lines"] = [l for l in l0.splitlines() if ASYNC_PAT.search(l)]
    r["r1_async_fatal_lav"] = any("async fatal event on QP" in l and "local access violation" in l
                                  for l in l1.splitlines())
    r["r0_gin_error"] = "GIN Error detected" in l0
    r["r1_gin_error"] = "GIN Error detected" in l1
    r["r0_warn_completion"] = re.findall(r"Got completion from peer .*? status=(\d+) .*?vendor err (\d+)", l0)
    r["r1_done120"] = bool(re.search(r"DONE okIters=120 ", l1))
    r["r0_peer_gone"] = bool(re.search(r"peer gone at it", l0))
    km = re.search(r"kill_mono_ms=([\d.]+)", out)
    r["kill_mono_ms"] = float(km.group(1)) if km else None
    r["ctr"] = ctr_delta(stack, tag)
    # fault effectiveness
    ok0 = int(r0.get("iters_ok", 0)) if r0 else 0
    ok1 = int(r1.get("iters_ok", r1.get("_okit_max", 0))) if r1 else 0
    r["ok0"], r["ok1"] = ok0, (r1 or {}).get("_okit_max", 0)
    if r["fault"] == "F0":
        r["effective"], r["eff_note"] = True, ""
    elif r["fault"] == "F4":
        # the kill must land while traffic is running: rank 1 must not have finished all iterations
        # and rank 0 must see the peer go away (or an error) before its last iteration.
        done = r["r1_done120"] or (ok0 >= 120 and not r["r0_peer_gone"])
        r["effective"] = not done
        r["eff_note"] = ("rank1 printed 'DONE okIters=120' before SIGKILL; rank0 120/120 ok, no peer loss"
                         if done else f"kill during traffic (r0 ok={ok0})")
    else:
        err = (r["r0_gin_error"] or r["r0_warn_completion"] or
               (r0 and r0.get("host_error", "none") != "none") or
               (r0 and r0.get("init_outcome") in ("timeout", "error", "hang_killed")))
        r["effective"] = bool(err)
        r["eff_note"] = "" if err else "no error on rank0"
    return r


NVO_MAP = {"NC": "stock_cpu_host_memory", "NG": "stock_gpu", "NX": "fix_cpu_host_memory"}


def parse_nvo(tag):
    _, v, k, tt = tag.split("_")
    base = f"{CAMP}/nvo/runs/{NVO_MAP[v]}_{k}_{tt}"
    l0, l1 = rd(base + ".pe0.log") or "", rd(base + ".pe1.log") or ""
    out = (rd(f"{CAMP}/nvo/logs/{tag}.out") or "").strip().splitlines()
    row = next(csv.reader([out[-1]])) if out else []
    r = dict(stack="nvo", tag=tag, variant=v, fault="F4" if k == "kill1" else "F0", l0=l0, l1=l1)
    r["pe0_rc"], r["pe1_rc"] = (int(row[6]), int(row[7])) if len(row) > 8 else (None, None)
    r["kill_at"] = row[5] if len(row) > 5 else None
    fm = re.search(r"PE 0: nvshmem_finalize returned after ([\d.]+) ms", l0)
    r["pe0_fin_ms"] = float(fm.group(1)) if fm else None
    r["pe0_fin_hang"] = "PE 0: nvshmem_finalize did not return after 30 s" in l0
    fm1 = re.search(r"PE 1: nvshmem_finalize returned after ([\d.]+) ms", l1)
    r["pe1_fin_ms"] = float(fm1.group(1)) if fm1 else None
    its0 = [int(x) for x in re.findall(r"^PE 0 iter (\d+): put", l0, re.M)]
    its1 = [int(x) for x in re.findall(r"^PE 1 iter (\d+): signal arrived", l1, re.M)]
    r["pe0_last_it"], r["pe1_last_it"] = (max(its0) if its0 else -1), (max(its1) if its1 else -1)
    r["async_lines"] = [l for l in (l0 + l1).splitlines() if ASYNC_PAT.search(l)]
    r["err_lines"] = [l for l in (l0 + l1).splitlines()
                      if re.search(r"has not returned|did not return|ERROR|error", l) and "NVLINK SHARP" not in l]
    r["ctr"] = ctr_delta("nvo", tag)
    if r["fault"] == "F4":
        # killed after PE0 iter 3; effective if PE1 stopped before the end of the 40-iteration run
        r["effective"] = r["kill_at"] not in (None, "-") and r["pe1_rc"] == 255 and r["pe1_last_it"] < 39
        r["eff_note"] = f"kill at {r['kill_at']}, PE1 last iter {r['pe1_last_it']}, PE0 last {r['pe0_last_it']}"
    else:
        r["effective"], r["eff_note"] = True, ""
    return r


def parse_nvd(tag):
    m = re.match(r"nvd_(auto|cpu_host_memory)_(F1|F2b|F3)_t(\d+)", tag)
    h, f, t = m.groups()
    base = f"{CAMP}/nvd/runs_{h}/{f}_timeout_t{t}"
    l0, l1 = rd(base + ".pe0.log") or "", rd(base + ".pe1.log") or ""
    r = dict(stack="nvd", tag=tag, handler=h, fault="F2" if f == "F2b" else f)
    r["async_lines"] = [l for l in (l0 + l1).splitlines() if ASYNC_PAT.search(l)]
    fired = ("moved 2 QP(s) to ERR" in (l0 + l1)) or ("F2b corrupted" in l0)
    fail = re.search(r"^ITER \d+ rank 0 .*wait_rc=[12]", l0, re.M)
    r["effective"] = bool(fired and fail)
    r["eff_note"] = "" if r["effective"] else "hook/rkey line or failing PE0 wait missing"
    r["ctr"] = ctr_delta("nvd", tag)
    return r


def parse_nvf(tag):
    m = re.match(r"nvf_(none|F1|F2b|F3|F4)_t(\d+)", tag)
    f, t = m.groups()
    base = f"{CAMP}/nvf/runs/{f}_timeout_ft1_rec1_prop_t{t}"
    l0, l1 = rd(base + ".pe0.log") or "", rd(base + ".pe1.log") or ""
    r = dict(stack="nvf", tag=tag, fault={"none": "F0", "F2b": "F2"}.get(f, f))
    r["async_lines"] = [l for l in (l0 + l1).splitlines() if ASYNC_PAT.search(l)]
    for pe, l in ((0, l0), (1, l1)):
        tm = re.search(rf"^TEARDOWN rank {pe} .*finalize_ms=([\d.]+) returned=1", l, re.M)
        r[f"pe{pe}_fin_ms"] = float(tm.group(1)) if tm else None
        r[f"pe{pe}_abort"] = "marked failed (recovery declined/aborted)" in l
        r[f"pe{pe}_summary"] = (re.search(rf"^SUMMARY rank {pe} .*", l, re.M) or [None])[0]
        # order: ft_abort line before TEARDOWN line
        ia, it = l.find("marked failed (recovery declined/aborted)"), l.find(f"TEARDOWN rank {pe}")
        r[f"pe{pe}_abort_before_td"] = ia >= 0 and it >= 0 and ia < it
    r["pe1_present"] = bool(re.search(r"^SUMMARY rank 1", l1, re.M))
    r["rec"] = bool(re.search(r"^REC it=", l0, re.M))
    r["decline"] = re.findall(r"^DECLINE .*", l0, re.M)
    r["cqe_class"] = (re.search(r"device-classified error CQE .*? class=(\S+)", l0) or [None, None])[1]
    r["err_lines"] = [l for l in (l0 + l1).splitlines()
                      if re.search(r"FAULTREC|DECLINE|error CQE|WATCHDOG|did not return", l)]
    if r["fault"] == "F0":
        r["effective"], r["eff_note"] = True, ""
    else:
        r["effective"] = r["cqe_class"] is not None
        r["eff_note"] = f"class={r['cqe_class']}"
    r["ctr"] = ctr_delta("nvf", tag)
    return r


def ensure_net_condensed():
    os.makedirs(NETC, exist_ok=True)
    for d in sorted(glob.glob(f"{CAMP}/net/runs/*/")):
        name = os.path.basename(d.rstrip("/"))
        for f in sorted(glob.glob(d + "*_r[01].log")):
            o = f"{NETC}/{name}__{os.path.basename(f)}"
            if os.path.exists(o):
                continue
            with open(o, "w") as fo:
                subprocess.run(["grep", "-v", "-E", r"^[0-9.]+ IT [0-9]+ |^[0-9.]+ $|communicator encountered "
                                r"a fatal error|NCCL INFO", f], stdout=fo, env={**os.environ, "LC_ALL": "C"})
                c = subprocess.run(["grep", "-c", "communicator encountered a fatal error", f],
                                   capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"}).stdout.strip()
                fo.write(f"fatal_repeat_count={c}\n")


API_RE = re.compile(r"\[rank([01])\] iter (\d+) async NCCL error: (.*)")


def parse_net(tag):
    _, i, tt = tag.split("_")
    name = f"{i}_{tt}"
    l0 = rd(f"{NETC}/{name}__{i}_0_r0.log") or ""
    l1 = rd(f"{NETC}/{name}__{i}_0_r1.log") or ""
    r = dict(stack="net", tag=tag, fault={"T0s": "F0", "F2": "F2", "F2stock": "F2"}[i], variant=i)
    r["inject"] = "[FAULT-INJECT]" in l0 and "corrupted rkey" in l0
    w = re.search(r"NCCL WARN NET/IB: Got completion from peer .*?status=(\d+) .*?vendor err (\d+)", l0)
    w2 = re.search(r"incident via cqe: status=(\d+)\(\w+\) vendor_err=(0x[0-9a-f]+)", l0)
    r["r0_status"], r["r0_vendor"] = (int(w.group(1)), hex(int(w.group(2)))) if w else \
        ((int(w2.group(1)), w2.group(2)) if w2 else (None, None))
    r["r0_status_src"] = "stock WARN" if w else ("FR2 line" if w2 else None)
    a0, a1 = API_RE.search(l0), API_RE.search(l1)
    r["r0_api"], r["r1_api"] = (a0.group(3).strip() if a0 else None), (a1.group(3).strip() if a1 else None)
    r["r1_async_fatal"] = "async fatal event on QP" in l1
    r["r0_declined_class"] = "fault class not recoverable" in l0 and "incident via cqe: status=10" in l0
    r["r0_fail_reason"] = (re.search(r"send comm FAILED in \S+ \((.*?),", l0) or [None, None])[1]
    r["replay"] = bool(re.search(r"recovered|replay|lead a recovery", l0 + l1, re.I))
    r["abort_hang"] = ("ABORT-HANG" in l0, "ABORT-HANG" in l1)
    s0, s1 = re.search(r"SUMMARY rank=0 rc=(\d+)", l0), re.search(r"SUMMARY rank=1 rc=(\d+)", l1)
    r["rc0"], r["rc1"] = (int(s0.group(1)) if s0 else None), (int(s1.group(1)) if s1 else None)
    # api ordering on rank 1: async-fatal line position vs API error line position
    def ts(pat, text):
        m_ = re.search(r"^([\d.]+) .*" + pat, text, re.M)
        return float(m_.group(1)) if m_ else None
    r["r1_t_cqe"] = ts(r"(Got completion|incident via cqe)", l1)
    r["r1_t_api"] = ts(r"async NCCL error", l1)
    r["r1_t_af"] = ts(r"async fatal event on QP", l1)
    r["r1_api_before_async"] = (r["r1_t_api"] is not None and r["r1_t_af"] is not None
                                and r["r1_t_api"] < r["r1_t_af"])
    r["r1_cqe_before_api"] = (r["r1_t_cqe"] is not None and r["r1_t_api"] is not None
                              and r["r1_t_cqe"] <= r["r1_t_api"])
    r["r1_cqe_status"] = (re.search(r"(?:Got completion .*?status=|incident via cqe: status=)(\d+)", l1) or
                          [None, None])[1]
    res = list(csv.DictReader(open(f"{CAMP}/net/runs/{name}/results.csv")))
    r["wall_s"] = float(res[0]["wall_s"]) if res else None
    r["rcproc"] = (res[0]["rc0"], res[0]["rc1"]) if res else None
    r["effective"] = (r["fault"] == "F0") or (r["inject"] and (r["r0_status"] == 10 or r["r1_async_fatal"]))
    r["eff_note"] = "" if r["effective"] else "no injection or no error"
    r["ctr"] = ctr_delta("net", tag)
    return r


# ---------------------------------------------------------------- scoring helpers
def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return ((c - h) / d, (c + h) / d)


class Cell:
    def __init__(self, cid, wording, observable, rule):
        self.cid, self.wording, self.observable, self.rule = cid, wording, observable, rule
        self.subs = OrderedDict()   # sub-cell -> dict(hits=[], misses=[], na=[(tag, reason)])
        self.notes = []

    def sub(self, name):
        return self.subs.setdefault(name, dict(hits=[], misses=[], na=[], ineff=[]))

    def add(self, name, tag, hit, na_reason=None, ineffective=False):
        """ineffective=True: the fault did not act during traffic. Primary scoring treats the trial as
        not observable; the alternative scoring ('alt') counts it with the outcome `hit`."""
        s = self.sub(name)
        if na_reason:
            s["na"].append((tag, na_reason))
        elif ineffective:
            s["ineff"].append((tag, bool(hit)))
        elif hit:
            s["hits"].append(tag)
        else:
            s["misses"].append(tag)

    def counts(self, s, mode):
        h, m = list(s["hits"]), list(s["misses"])
        if mode == "alt":
            h += [t for t, x in s["ineff"] if x]
            m += [t for t, x in s["ineff"] if not x]
        return h, m

    def verdict_sub(self, s, mode="primary"):
        h, m = self.counts(s, mode)
        n = len(h) + len(m)
        if n == 0:
            return "not testable (n=0)"
        if self.rule == "all":
            return "HOLDS" if not m else "FAILS"
        return "HOLDS" if len(h) >= 0.9 * n else "FAILS"

    def strict_sub(self, s, mode="primary"):
        """strict reading of 'no trial shows an outcome outside the predicted class': any miss fails."""
        h, m = self.counts(s, mode)
        if len(h) + len(m) == 0:
            return "not testable (n=0)"
        return "HOLDS" if not m else "FAILS"

    def verdict(self, mode="primary", strict=False):
        vs = [(self.strict_sub(s, mode) if strict else self.verdict_sub(s, mode)) for s in self.subs.values()]
        if any(v == "FAILS" for v in vs):
            return "FAILS"
        if all(v.startswith("not testable") for v in vs):
            return "not testable"
        if any(v.startswith("not testable") for v in vs):
            return "HOLDS (testable sub-cells only)"
        return "HOLDS"


def short(tag):
    return tag


def main():
    ensure_net_condensed()
    P = plan()
    lines = []
    # ---------------- plan vs trials.log
    plan_rows = []
    for s, tags in P.items():
        tl = trials_log(s)
        got = [r["tag"] for r in tl]
        missing = [t for t in tags if t not in got]
        extra = [t for t in got if t not in tags]
        dup = len(got) - len(set(got))
        rcnz = [r["tag"] for r in tl if r["rc"] != 0]
        nlog = len(glob.glob(f"{CAMP}/{s}/logs/{s}_*.out"))
        nev = len(glob.glob(f"{CAMP}/{s}/evrec/*.evrec.rain")), len(glob.glob(f"{CAMP}/{s}/evrec/*.evrec.sunny"))
        plan_rows.append((s, len(tags), len(got), len(missing), len(extra), dup, len(rcnz), nlog, nev))

    T = {}
    for t in P["cpu"]:
        T[t] = parse_cpu(t)
    for s in ("gp", "gg", "gq"):
        for t in P[s]:
            T[t] = parse_gin(s, t)
    for t in P["nvo"]:
        T[t] = parse_nvo(t)
    for t in P["nvd"]:
        T[t] = parse_nvd(t)
    for t in P["nvf"]:
        T[t] = parse_nvf(t)
    for t in P["net"]:
        T[t] = parse_net(t)

    C = OrderedDict()

    def cell(cid, wording, obs, rule="90"):
        C[cid] = Cell(cid, wording, obs, rule)
        return C[cid]

    cpu = [T[t] for t in P["cpu"]]
    # EV1a/b
    c = cell("EV1a", "CPU responder F2 -> IBV_EVENT_QP_ACCESS_ERR; >=9/10 and no other QP event",
             "cpu/logs/cpu_rem_access_t*.out '[trial 0]' field srv_async (= csv column srv_async)")
    for r in cpu:
        if r["fault"] == "F2":
            c.add("F2", r["tag"], r["srv_async"].startswith("IBV_EVENT_QP_ACCESS_ERR/") and ";" not in r["srv_async"])
    c = cell("EV1b", "CPU responder rem_inv_req -> IBV_EVENT_QP_REQ_ERR; >=9/10 and no other QP event",
             "cpu_rem_inv_req_t*.out field srv_async")
    for r in cpu:
        if r["fault"] == "rem_inv_req":
            c.add("rem_inv_req", r["tag"], r["srv_async"].startswith("IBV_EVENT_QP_REQ_ERR/") and ";" not in r["srv_async"])
    c = cell("EV1c", "CPU responder rnr -> none; 10/10", "cpu_rnr_t*.out field srv_async == none", "all")
    for r in cpu:
        if r["fault"] == "rnr":
            c.add("rnr", r["tag"], r["srv_async"] == "none")
    c = cell("EV1d", "CPU responder F1;F3;F4;F0;partial_write -> none; 10/10 per fault",
             "srv_async == none; srv_async '-' (responder dead, DEVIATIONS 4) = not observable", "all")
    for r in cpu:
        if r["fault"] in ("F1", "F3", "F4", "F0", "partial_write"):
            if r["srv_async"] == "-":
                c.add(r["fault"], r["tag"], None, na_reason="responder SIGKILLed; srv_async '-'")
            else:
                c.add(r["fault"], r["tag"], r["srv_async"] == "none")
    c = cell("EV1e", "CPU requester, all faults -> no QP-affiliated event; 10/10 per fault",
             "field cli_async == none", "all")
    for r in cpu:
        c.add(r["fault"], r["tag"], r["cli_async"] == "none")
    c = cell("EV2a", "CPU responder QP state after F2;rem_inv_req -> ERR; >=9/10", "field srv_qp == ERR")
    for r in cpu:
        if r["fault"] in ("F2", "rem_inv_req"):
            c.add(r["fault"], r["tag"], r["srv_qp"] == "ERR")
    c = cell("EV2b", "CPU responder QP state after rnr;F1 -> RTS; >=9/10", "field srv_qp == RTS")
    for r in cpu:
        if r["fault"] in ("rnr", "F1"):
            c.add(r["fault"], r["tag"], r["srv_qp"] == "RTS")

    gp = [T[t] for t in P["gp"]]
    c = cell("EV3a", "GP r1 F2: '\"async fatal event on QP\" with local access violation'; >=9/10 (new)",
             "gp/logs/proxy_F2_timeout_t*_r1.log line containing 'async fatal event on QP' and "
             "'local access violation'")
    for r in gp:
        if r["fault"] == "F2":
            c.add("F2 new", r["tag"], r["r1_async_fatal_lav"])
    c = cell("EV3b", "GP r1 F2: ncclCommGetAsyncError 'ncclSuccess until its own wait ends'; >=9/10",
             "proxy_F2_*_r1.kv host_error=none (driver polls ncclCommGetAsyncError through the wait and a "
             "15 s post-fault poll) ")
    for r in gp:
        if r["fault"] == "F2":
            c.add("F2", r["tag"], r["r1"].get("host_error") == "none")
    c = cell("EV3c", "GP r1 F1;F3;F4: no NCCL async QP event; 10/10 per fault",
             "no line matching /async fatal event|IBV_EVENT_|ncclIbAsyncThreadMain|async event/i in r1 log", "all")
    for r in gp:
        if r["fault"] in ("F1", "F3", "F4"):
            c.add(r["fault"], r["tag"], not r["r1_async_lines"], ineffective=not r["effective"])

    # EV4
    c = cell("EV4", "GG;GQ;NC;NG;NX;ND;NF both ranks, all faults: no QP-affiliated async error or NCCL async "
             "fatal line; every trial",
             "both rank logs: no /async fatal event|IBV_EVENT_|ncclIbAsyncThreadMain|async event/i; evrec "
             "events=0 on both nodes (DEVIATIONS 9)", "all")
    for s in ("gg", "gq", "nvo", "nvd", "nvf"):
        for t in P[s]:
            r = T[t]
            if s in ("gg", "gq"):
                al = r["r0_async_lines"] + r["r1_async_lines"]
                var = s.upper()
            elif s == "nvo":
                al, var = r["async_lines"], r["variant"]
            else:
                al, var = r["async_lines"], {"nvd": "ND", "nvf": "NF"}[s]
            ev = [(r["ctr"][n] or {}).get("_events") for n in ("rain", "sunny")]
            hit = (not al) and all(e == 0 for e in ev)
            c.add(var, t, hit, ineffective=not r["effective"])

    # EV5
    def zero4(d):
        return d is not None and all(d[k] == 0 for k in CTR4)

    c = cell("EV5a", "GG;GQ;NF;ND both nodes, all faults: the 4 counters +0 each; every trial",
             "evrec <tag>.evrec.{rain,sunny} hw_counters end-start for req_cqe_error, req_cqe_flush_error, "
             "local_ack_timeout_err, req_remote_access_errors", "all")
    for s, var in (("gg", "GG"), ("gq", "GQ"), ("nvf", "NF"), ("nvd", "ND")):
        for t in P[s]:
            r = T[t]
            hit = zero4(r["ctr"]["rain"]) and zero4(r["ctr"]["sunny"])
            c.add(f"{var} {r['fault']}", t, hit, ineffective=not r["effective"])
    c = cell("EV5b", "NC;NG;NX both nodes F4: same counters +0 each; every trial", "as EV5a", "all")
    for t in P["nvo"]:
        r = T[t]
        if r["fault"] == "F4":
            c.add(r["variant"], t, zero4(r["ctr"]["rain"]) and zero4(r["ctr"]["sunny"]))
    c = cell("EV5c", "CPU;GP requester node F3;F4: local_ack_timeout_err >=+6 and req_cqe_error >=+1; >=9/10",
             "evrec <tag>.evrec.rain hw_counters end-start")
    for r in cpu + gp:
        if r["fault"] in ("F3", "F4"):
            d = r["ctr"]["rain"]
            c.add(f"{r['stack'].upper()} {r['fault']}", r["tag"],
                  d["local_ack_timeout_err"] >= 6 and d["req_cqe_error"] >= 1, ineffective=not r["effective"])
    c = cell("EV5d", "CPU;GP requester node F1;F2: req_cqe_error >=+1; >=9/10", "evrec rain hw_counters end-start")
    for r in cpu + gp:
        if r["fault"] in ("F1", "F2"):
            c.add(f"{r['stack'].upper()} {r['fault']}", r["tag"], r["ctr"]["rain"]["req_cqe_error"] >= 1)

    net = [T[t] for t in P["net"]]
    c = cell("NET1a", "NET stock F2 requester: 10/0x88 in WARN; ncclRemoteError; >=9/10",
             "runs/F2stock_t*/F2stock_0_r0.log: 'NCCL WARN NET/IB: Got completion ... status=10 ... vendor err 136' "
             "and '[rank0] iter N async NCCL error: remote process exited or there was a network error'")
    for r in net:
        if r["variant"] == "F2stock":
            c.add("F2stock", r["tag"], r["r0_status"] == 10 and r["r0_vendor"] == "0x88" and r["r0_status_src"] ==
                  "stock WARN" and r["r0_api"] == "remote process exited or there was a network error")
    c = cell("NET1b", "NET stock F2 target: 'async fatal event on QP' WARN and a target API error; >=9/10",
             "F2stock_0_r1.log: 'async fatal event on QP' WARN and '[rank1] iter N async NCCL error: ...'")
    for r in net:
        if r["variant"] == "F2stock":
            c.add("F2stock", r["tag"], r["r1_async_fatal"] and r["r1_api"] is not None)
    rem = "remote process exited or there was a network error"
    c = cell("NET1c-A", "NET stage2 F2 'both': declined (REM_ACCESS); ncclRemoteError; no replay; >=9/10 -- "
             "reading A: decline and API judged on the requester (rank 0)",
             "F2_0_r0.log: 'incident via cqe: status=10(REM_ACCESS_ERR)' + 'fault class not recoverable'; "
             "rank 0 API string = ncclRemoteError; no /recovered|replay|lead a recovery/ on either rank")
    for r in net:
        if r["variant"] == "F2":
            c.add("F2", r["tag"], r["r0_declined_class"] and r["r0_api"] == rem and not r["replay"])
    c = cell("NET1c-B", "same, reading B: ncclRemoteError required on both ranks (csv rank column 'both')",
             "as NET1c-A plus rank 1 API string = ncclRemoteError")
    for r in net:
        if r["variant"] == "F2":
            c.add("F2", r["tag"], r["r0_declined_class"] and r["r0_api"] == rem and r["r1_api"] == rem
                  and not r["replay"])

    gg = [T[t] for t in P["gg"]]
    c = cell("D1", "GG GPU doorbell F2;F3;F4 initiator: -EIO (L2); blocking flush success on failed op (L3); "
             "GIN Error detected at next 10 s tick (L4); >=9/10 per fault",
             "L2 not observable in the stock driver; L3: r0 kv init_outcome=ok and r0 okit > r1 okit; L4: r0 log "
             "'GIN Error detected' and host_error_ms - fault time <= 10.05 s (CSV columns of gg.csv, recomputed "
             "from kv: host_error_ms and fault time)")
    for r in gg:
        if r["fault"] in ("F2", "F3", "F4"):
            r0, r1 = r["r0"], r["r1"] or {}
            l3 = r0.get("init_outcome") == "ok" and r0.get("_okit_max", 0) > r1.get("_okit_max", 0)
            surf = gg_surface(r)
            l4 = r["r0_gin_error"] and surf is not None and 0 < surf <= 10050
            r["d1"] = (l3, l4, surf)
            c.add(r["fault"], r["tag"], l3 and l4, ineffective=not r["effective"])
    c = cell("D2", "GG blocking F4: initiator's flush returns success in the first iteration after the kill; >=9/10",
             "r0 okit beyond r1's last iteration after kill_mono_ms; requires r0 iterations after the kill")
    for r in gg:
        if r["fault"] == "F4":
            # alt scoring: 'r0 flush never reported a failure' (true by default when nothing failed)
            c.add("F4", r["tag"], r["r0"].get("init_outcome") == "ok" and r["r0"].get("host_error") == "none",
                  ineffective=not r["effective"])

    # T1
    c = cell("T1", "every variant F0: no error at any layer on either rank; teardown returns within 5 s on both "
             "ranks; 5/5 per variant",
             "CPU: [trial 0] status=success, srv_qp=RTS, srv_async=none, cli_async=none, client 'teardown (ep_close) "
             "returned after X ms' < 5000 (server teardown not recorded); GP/GG/GQ: both kv init_outcome=ok, "
             "host_error=none, teardown=clean teardown_ms<5000, r1 data_check=ok, no 'GIN Error'/'Got completion' "
             "line; NC/NG/NX kill0: pe0/pe1 rc 0, 40/40 iterations, 'nvshmem_finalize returned after X ms' < 5000 "
             "on both PEs, no error lines; NF none: SUMMARY rc=0 and 'TEARDOWN rank N ... returned=1' both PEs; "
             "NET T0s: SUMMARY rc=0 both ranks, no API error, no ABORT-HANG, whole-run wall_s < 5", "all")
    for r in cpu:
        if r["fault"] == "F0":
            ok = (r["status"] == 0 and r["srv_async"] == "none" and r["cli_async"] == "none" and r["srv_qp"] == "RTS"
                  and r["cli_teardown_ms"] is not None and r["cli_teardown_ms"] < 5000)
            c.add("CPU (client teardown only)", r["tag"], ok)
    for s in ("gp", "gg", "gq"):
        for t in P[s]:
            r = T[t]
            if r["fault"] != "F0":
                continue
            ok = True
            for k in ("r0", "r1"):
                d = r[k]
                ok &= d.get("init_outcome") == "ok" and d.get("host_error") == "none" and d.get("teardown") == "clean" \
                    and float(d.get("teardown_ms", 1e9)) < 5000
            ok &= not r["r0_gin_error"] and not r["r1_gin_error"] and not r["r0_warn_completion"]
            ok &= r["r1"].get("data_check") == "ok"
            c.add(s.upper(), t, ok)
    for t in P["nvo"]:
        r = T[t]
        if r["fault"] == "F0":
            ok = (r["pe0_rc"] == 0 and r["pe1_rc"] == 0 and r["pe0_fin_ms"] is not None and r["pe0_fin_ms"] < 5000
                  and r["pe1_fin_ms"] is not None and r["pe1_fin_ms"] < 5000 and not r["err_lines"]
                  and r["pe0_last_it"] == 39 and r["pe1_last_it"] == 39)
            c.add(r["variant"], t, ok)
    c.sub("ND")["na"].append(("-", "no F0 trial planned for ND (cells.sh nvd runs F1/F2b/F3 only)"))
    for t in P["nvf"]:
        r = T[t]
        if r["fault"] == "F0":
            ok = (r["pe0_fin_ms"] is not None and r["pe0_fin_ms"] < 5000 and r["pe1_fin_ms"] is not None and
                  r["pe1_fin_ms"] < 5000 and not r["err_lines"] and " rc=0 " in (r["pe0_summary"] or "")
                  and " rc=0 " in (r["pe1_summary"] or ""))
            c.add("NF", t, ok)
    for r in net:
        if r["fault"] == "F0":
            ok = (r["rc0"] == 0 and r["rc1"] == 0 and r["r0_api"] is None and r["r1_api"] is None
                  and r["wall_s"] is not None and r["wall_s"] < 5 and not any(r["abort_hang"]))
            c.add("NET (T0s; teardown bounded by whole-run wall_s)", r["tag"], ok)

    c = cell("T2", "NC;NG;NX F4: PE0 nvshmem_finalize does not return within 30 s; 5/5 per variant",
             "nvo/runs/*_kill1_t*.pe0.log 'PE 0: nvshmem_finalize did not return after 30 s'", "all")
    for t in P["nvo"]:
        r = T[t]
        if r["fault"] == "F4":
            c.add(r["variant"], t, r["pe0_fin_hang"])
    c = cell("T3", "GG;GQ blocking F1;F2;F3: r0 ncclCommAbort returns; r1 does not within 30 s; 5/5 per cell",
             "r0 kv teardown=clean; r1 kv 'teardown=hang teardown_bound_s=30'", "all")
    for s in ("gg", "gq"):
        for t in P[s]:
            r = T[t]
            if r["fault"] in ("F1", "F2", "F3") and r["mode"] == "blocking":
                ok = r["r0"].get("teardown") == "clean" and r["r1"].get("teardown") == "hang" and \
                    r["r1"].get("teardown_bound_s") == "30"
                c.add(f"{s.upper()} {r['fault']}", t, ok)
    c = cell("T4", "NF F1;F3: finalize returns on both PEs; F2;F4: return only after the driver's ft_abort; "
             "5/5 per cell", "TEARDOWN rank N ... returned=1; for F2/F4 'marked failed (recovery declined/aborted)' "
             "(printed by nvshmemt_ibgda_ft_abort) before the TEARDOWN line", "all")
    for t in P["nvf"]:
        r = T[t]
        if r["fault"] in ("F1", "F3"):
            c.add(r["fault"], t, r["pe0_fin_ms"] is not None and r["pe1_fin_ms"] is not None)
        elif r["fault"] == "F2":
            c.add("F2", t, r["pe0_fin_ms"] is not None and r["pe1_fin_ms"] is not None and r["pe0_abort_before_td"]
                  and r["pe1_abort_before_td"])
        elif r["fault"] == "F4":
            c.add("F4 (PE0; PE1 killed)", t, r["pe0_fin_ms"] is not None and r["pe0_abort_before_td"])

    # ---------------- blind EV3a on old GIN logs
    blind = OrderedDict()
    for sub in ("logs", "v2/logs", "ref60/logs"):
        fs = sorted(glob.glob(f"{OLDGIN}/{sub}/proxy_F2_*_r1.log"))
        if not fs:
            blind[sub] = None
            continue
        rows = []
        for f in fs:
            l1 = rd(f)
            l0 = rd(f.replace("_r1.log", "_r0.log")) or ""
            hit = any("async fatal event on QP" in l and "local access violation" in l for l in l1.splitlines())
            st10 = bool(re.search(r"status=10\b", l0))
            k1 = kv(f.replace(".log", ".kv")) or {}
            rows.append(dict(f=os.path.basename(f), hit=hit, rem_access_on_r0=st10,
                             r1_host_error=k1.get("host_error"), silent=k1.get("silent_success")))
        blind[sub] = rows
    # blind EV3c for completeness (proxy F1/F3/F4 r1 logs)
    blind3c = OrderedDict()
    for sub in ("logs", "v2/logs", "ref60/logs"):
        fs = sorted(glob.glob(f"{OLDGIN}/{sub}/proxy_F[134]_*_r1.log"))
        blind3c[sub] = [(os.path.basename(f), not any(ASYNC_PAT.search(l) for l in rd(f).splitlines())) for f in fs]

    # ---------------- write trials.csv
    with open(f"{OUT}/trials.csv", "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["stack", "tag", "fault", "effective", "eff_note", "rain_d4", "sunny_d4", "evrec_events"])
        for t, r in T.items():
            d4 = lambda d: "/".join(str(d[k]) for k in CTR4) if d else "NA"
            w.writerow([r["stack"], t, r["fault"], int(bool(r["effective"])), r.get("eff_note", ""),
                        d4(r["ctr"]["rain"]), d4(r["ctr"]["sunny"]),
                        "/".join(str((r["ctr"][n] or {}).get("_events")) for n in ("rain", "sunny"))])

    # ---------------- markdown
    L = []
    L.append("# Independent recount of the propagation campaign (QA)\n")
    L.append("Source: `results/20261006_campaign/` raw files only (smoke excluded); predictions from "
             "`PREDICTIONS.md`/`predictions.csv`. Script: `recount.py` (this folder). Not read: `campaign/score.py`, "
             "`SCORE.md`, `score.json`, EXPERIMENT.md sections 15-16.\n")
    L.append("Rule applied (as given): a cell holds if >=90% of its observable trials match; cells whose acceptance says "
             "10/10, 5/5, 'every' or 'all' need all observable trials to match. Sub-cells are scored separately "
             "and the cell holds only if every testable sub-cell holds.\n")
    L.append("## 1. Trial counts vs plan (cells.sh)\n")
    L.append("| stack | planned | in trials.log | missing | extra | dup | rc!=0 | .out logs | evrec rain/sunny |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|---|")
    for s, npl, ngot, nmiss, nex, dup, rcnz, nlog, nev in plan_rows:
        L.append(f"| {s} | {npl} | {ngot} | {nmiss} | {nex} | {dup} | {rcnz} | {nlog} | {nev[0]}/{nev[1]} |")
    tot = sum(r[1] for r in plan_rows), sum(r[2] for r in plan_rows)
    L.append(f"| total | {tot[0]} | {tot[1]} | | | | | | |\n")

    L.append("## Summary (24 cells; NET1c shown under two readings)\n")
    L.append("| cell | n obs | hits | misses | not obs. | verdict | alt: ineffective counted |")
    L.append("|---|--:|--:|--:|--:|---|---|")
    for cid, cl in C.items():
        n = sum(len(s["hits"]) + len(s["misses"]) for s in cl.subs.values())
        h = sum(len(s["hits"]) for s in cl.subs.values())
        na = sum(len(s["na"]) + len(s["ineff"]) for s in cl.subs.values())
        L.append(f"| {cid} | {n} | {h} | {n - h} | {na} | {cl.verdict()} | {cl.verdict('alt')} |")
    for sub, rows in blind.items():
        if rows:
            h = sum(r["hit"] for r in rows)
            e = sum(r["rem_access_on_r0"] for r in rows)
            L.append(f"| EV3a blind `{sub}` | {len(rows)} | {h} | {len(rows) - h} | - | "
                     f"{'HOLDS' if h == len(rows) else 'FAILS (literal)'} | remote-access fault occurred in "
                     f"{e}/{len(rows)} |")
    L.append("")
    L.append("## 2. Cells\n")
    L.append("Primary scoring: trials whose fault did not act during traffic (section 4) are not observable. "
             "'Alt' counts them with whatever they showed. 'Strict' reads the acceptance clause 'no trial shows an "
             "outcome outside the predicted class' as: any miss fails the cell.\n")
    L.append("| cell | sub-cell | n obs | hits | misses (trial ids) | not observable | verdict | alt (ineffective "
             "counted) | strict |")
    L.append("|---|---|--:|--:|---|---|---|---|---|")
    for cid, cl in C.items():
        first = True
        for name, s in cl.subs.items():
            n = len(s["hits"]) + len(s["misses"])
            na_parts = []
            if s["na"]:
                na_parts.append(f"{len(s['na'])}: {s['na'][0][1]}")
            if s["ineff"]:
                hh = sum(1 for _, x in s["ineff"] if x)
                na_parts.append(f"{len(s['ineff'])}: fault ineffective (would be {hh} hit / "
                                f"{len(s['ineff']) - hh} miss)")
            na_txt = "; ".join(na_parts) if na_parts else "0"
            L.append(f"| {cid if first else ''} | {name} | {n} | {len(s['hits'])} | "
                     f"{', '.join(s['misses']) if s['misses'] else '-'} | {na_txt} | {cl.verdict_sub(s)} | "
                     f"{cl.verdict_sub(s, 'alt')} | {cl.strict_sub(s)} |")
            first = False
        L.append(f"| | **cell verdict** | | | | | **{cl.verdict()}** | **{cl.verdict('alt')}** | "
                 f"**{cl.verdict(strict=True)}** |")
    L.append("")
    L.append("### Observables used\n")
    for cid, cl in C.items():
        L.append(f"- **{cid}**: prediction applied: \"{cl.wording}\". Observable: {cl.observable}.")
    L.append("")

    L.append("## 3. EV3a blind part (2026-09-23 GIN logs)\n")
    for sub, rows in blind.items():
        if rows is None:
            L.append(f"- `{sub}`: no proxy F2 r1 logs.")
            continue
        h = sum(r["hit"] for r in rows)
        eff = sum(r["rem_access_on_r0"] for r in rows)
        L.append(f"- `{sub}`: {h}/{len(rows)} r1 logs carry the line. Rank 0 saw status=10 (remote access) in "
                 f"{eff}/{len(rows)}; r1 silent_success flags: {[r['silent'] for r in rows]}; "
                 f"r1 host_error: {sorted(set(r['r1_host_error'] or '?' for r in rows))}.")
    L.append("")
    L.append("Blind EV3c (proxy F1/F3/F4 r1 logs, no async event line): " + "; ".join(
        f"`{k}` {sum(v for _, v in rows)}/{len(rows)}" for k, rows in blind3c.items()) + "\n")

    L.append("## 4. Fault effectiveness\n")
    ineff = [(t, r) for t, r in T.items() if not r["effective"]]
    L.append(f"Ineffective fault trials: {len(ineff)}\n")
    by = defaultdict(list)
    for t, r in ineff:
        by[(r["stack"], r["fault"], r.get("eff_note", ""))].append(t)
    for (s, f, note), ts in by.items():
        L.append(f"- {s} {f} ({len(ts)}): {', '.join(ts)}. Evidence: {note}.")
    L.append("")

    # detail dumps for the md
    L.append("## 5. Per-trial details used in the verdicts\n")
    L.append("GP/GG F4 kill vs workload (rank 1 finished all 120 iterations before the SIGKILL):\n")
    L.append("| trial | r0 iters ok | r1 'DONE okIters=120' | r0 peer gone | r0 host_error |")
    L.append("|---|--:|---|---|---|")
    for s in ("gp", "gg"):
        for t in P[s]:
            r = T[t]
            if r["fault"] == "F4":
                L.append(f"| {t} | {r['ok0']} | {r['r1_done120']} | {r['r0_peer_gone']} | {r['r0'].get('host_error')} |")
    L.append("")
    L.append("Requester-node (rain) counter deltas, EV5c/EV5d (req_cqe_error/req_cqe_flush_error/local_ack_timeout_err/"
             "req_remote_access_errors):\n")
    for r in cpu + gp:
        if r["fault"] in ("F1", "F2", "F3", "F4"):
            d = r["ctr"]["rain"]
            L.append(f"- {r['tag']}: {d['req_cqe_error']}/{d['req_cqe_flush_error']}/{d['local_ack_timeout_err']}/"
                     f"{d['req_remote_access_errors']}")
    L.append("")
    L.append("Non-zero 4-counter deltas on any node in DEVX trials (EV5a/EV5b):\n")
    nz = 0
    for s in ("gg", "gq", "nvo", "nvd", "nvf"):
        for t in P[s]:
            r = T[t]
            for n in ("rain", "sunny"):
                d = r["ctr"][n]
                if d and any(d[k] for k in CTR4):
                    nz += 1
                    L.append(f"- {t} {n}: " + ", ".join(f"{k}+{d[k]}" for k in CTR4 if d[k]))
    if nz == 0:
        L.append("- none")
    L.append("")
    L.append("NET F2 (Stage 2) per trial: r0 status source / declined-by-class / r0 API / r1 API / r1 async fatal / "
             "replay:\n")
    for r in net:
        if r["fault"] == "F2":
            L.append(f"- {r['tag']}: status={r['r0_status']} ({r['r0_status_src']}), declined_by_class="
                     f"{r['r0_declined_class']}, r0 fail reason='{r['r0_fail_reason']}', r0_api='{r['r0_api']}', "
                     f"r1_api='{r['r1_api']}', r1_async_fatal={r['r1_async_fatal']}, replay={r['replay']}, "
                     f"r1 API before async line={r['r1_api_before_async']}")
    L.append("")
    L.append("NET target (rank 1) ordering, F2stock: own flushed Recv CQE -> API error -> async fatal WARN (us):\n")
    for r in net:
        if r["variant"] == "F2stock":
            L.append(f"- {r['tag']}: r1 CQE status={r['r1_cqe_status']}, API-CQE="
                     f"{round((r['r1_t_api'] - r['r1_t_cqe']) * 1e6)} us, API-asyncWARN="
                     f"{round((r['r1_t_api'] - r['r1_t_af']) * 1e6)} us")
    k = sum(1 for r in net if r["variant"] == "F2stock" and r["r1_api_before_async"])
    L.append(f"\nTarget API error before the async fatal WARN: {k}/10 F2stock trials; own flush CQE before the API "
             f"error: {sum(1 for r in net if r['variant'] == 'F2stock' and r['r1_cqe_before_api'])}/10.\n")
    L.append("GG D1 per trial (L3 silent flush, L4 GIN Error, surface ms):\n")
    for r in gg:
        if "d1" in r:
            L.append(f"- {r['tag']}: L3={r['d1'][0]} L4={r['d1'][1]} surface_ms={r['d1'][2]}")
    L.append("")
    nb = {k: (sum(r["hit"] for r in v), len(v)) for k, v in blind.items() if v}
    L.append("## 6. Ambiguities that change a verdict\n")
    L.append("1. **Ineffective F4 in GP and GG (20 trials).** Excluding them (primary) vs counting them (alt): "
             f"EV5c {C['EV5c'].verdict()} vs {C['EV5c'].verdict('alt')} (GP F4 0/10 on rain counters); "
             f"D1 {C['D1'].verdict()} (F4 untestable) vs {C['D1'].verdict('alt')} (F4 0/10); "
             f"D2 {C['D2'].verdict()} vs {C['D2'].verdict('alt')} (10/10 only because nothing failed). "
             "EV3c F4, EV4 GG F4 and EV5a GG F4 hold either way, but those 30 hits are trivial.")
    L.append("2. **Acceptance clause 'no trial shows an outcome outside the predicted class'.** Read as 'any miss "
             f"fails', NET1c-A goes from {C['NET1c-A'].verdict()} (9/10) to {C['NET1c-A'].verdict(strict=True)}. "
             "No other cell has a 9/10.")
    L.append("3. **NET1c rank scope.** The csv rank column says 'both'. ncclRemoteError on both ranks: "
             f"{C['NET1c-B'].verdict()} (6/10; rank 1 returned 'unhandled system error' in t1, t7, t8, t9). "
             "Requester only: 9/10 (t1 failed through rank 1's async-event FAIL before rank 0 saw REM_ACCESS).")
    L.append("4. **EV3a blind part: which retained logs.** " + "; ".join(
        f"`{k}` {h}/{n}" for k, (h, n) in nb.items()) + ". The `logs/` runs used the old in-MR overrun "
             "(rank 0 saw no status=10, rank 1 reports SILENT-SUCCESS with the signal delivered), so no remote "
             "access fault happened. 'Every retained r1 F2 log' read literally over both folders: 6/12, fails; "
             "with the `logs/` trials as not observable: 6/6, holds.")
    L.append("5. **NET1b mechanism.** Literal prediction ('async fatal WARN and a target API error') holds 10/10. "
             "The stated reason (target API error raised by the fatal-count check) is not what produced it: the "
             "target's API error follows its own flushed Recv CQE (status 5) and precedes the async WARN in 9/10.")
    L.append("6. **Not verdict-changing but untested parts:** D1 L2 (device -EIO) is not observable with the stock "
             "driver and the GPU-doorbell mode is not logged (PeerMappingOverride=1 on rain at QA time); T4 'only "
             "after ft_abort' has no no-abort control; T1 has no ND F0 run, no CPU server teardown time, and NET "
             "teardown is bounded only by the whole-run wall time (<1.6 s); EV1d F4 is not observable "
             "(DEVIATIONS 4); EV4 'async error' means the verbs QP-affiliated event: GG/GQ do raise "
             "ncclCommGetAsyncError ('GIN Error detected'), which D1 itself predicts.")
    L.append("")
    with open(f"{OUT}/recount_table.md", "w") as fo:
        fo.write("\n".join(L) + "\n")
    print("\n".join(L))


def gg_surface(r):
    """host error time minus fault time on rank 0's clock (ms), recomputed from kv/log values."""
    r0, r1 = r["r0"], r["r1"] or {}
    try:
        he = float(r0.get("host_error_ms", -1))
    except ValueError:
        return None
    if he < 0:
        return None
    t0 = float(r0["t0_mono_ms"])
    f = r["fault"]
    stack = r["stack"]
    _, ff, m, tt = r["tag"].split("_")
    base = f"{CAMP}/{stack}/logs/gdaki_{ff}_{m}_{tt}"
    l0, l1 = rd(base + "_r0.log") or "", rd(base + "_r1.log") or ""
    off = float(r0["clock_offset_ms"])
    fa = None
    if f == "F2":
        fa = float(r0["fault_mono_ms"])
    elif f == "F1":
        m1 = re.search(r"fire_mono_ms=([\d.]+)", l0)
        fa = float(m1.group(1)) if m1 else None
    elif f == "F3":
        m1 = re.search(r"fire_mono_ms=([\d.]+)", l1)
        fa = float(m1.group(1)) - off if m1 else None
    elif f == "F4" and r["kill_mono_ms"]:
        fa = r["kill_mono_ms"] - off
    if fa is None:
        return None
    return round(t0 + he - fa, 1)


if __name__ == "__main__":
    main()
