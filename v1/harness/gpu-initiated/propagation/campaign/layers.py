#!/usr/bin/env python3
"""layers.py <campaign_root> --f4-rerun <dir> - per-layer propagation and partition table.

Reads the campaign outputs of cells.sh (one folder per stack: cpu gp gg gq nvo nvd nvf net) and writes
two files into <campaign_root>:
  layers_trials.csv  one row per trial and side (initiator, target), one label per layer, with the
                     field or log string each label came from
  LAYERS.md          propagation rate (arrival) and partition per variant and layer, the comparison
                     with the pre-registered partition of REVIEW_20261006.md, and the core-claim check
--f4-rerun replaces the GP and GG F4 trials with those of the re-run (DEVIATIONS.md item 10).
The smoke folder is never read. Plain Python 3, standard library only.

Layers (REVIEW_20261006.md "Layers"):
  L0_qp     NIC: QP state, only where a log or field records it after the fault
  L0_ctr    NIC: port hw_counters delta of the error counters (evrec, start to end of the trial)
  L1_root   the root-cause CQE the NIC wrote (status/vendor_err)
  L1_read   the CQE the consumer actually read
  L2        what the code polling the CQ derived (proxy thread, device poll, classifier)
  L3        what the application received from the API
  L4_async  the host-side asynchronous error value (ncclCommGetAsyncError, ibv async events)
  L4_log    the library's error log lines (injection markers and known benign lines excluded)
  L5        teardown (abort / finalize / ep_close): returned or hang
A label is "not observed" when the data has no such field for that trial; nothing is inferred.
"""
import csv, glob, math, os, re, sys
from collections import Counter, OrderedDict

NO = "not observed"
LAYERS = ["L0_qp", "L0_ctr", "L1_root", "L1_read", "L2", "L3", "L4_async", "L4_log", "L5"]
ERR_CTRS = ["duplicate_request", "implied_nak_seq_err", "local_ack_timeout_err", "out_of_sequence",
            "packet_seq_err", "req_cqe_error", "req_cqe_flush_error", "req_remote_access_errors",
            "req_remote_invalid_request", "resp_cqe_error", "resp_cqe_flush_error",
            "resp_local_length_error", "resp_remote_access_errors", "rnr_nak_retry_err"]
# mlx5 CQE syndrome -> ibv_wc_status (rdma-core providers/mlx5/cq.c), for the device-read CQE slots
SYN2STATUS = {0x01: 1, 0x02: 2, 0x04: 4, 0x05: 5, 0x06: 6, 0x10: 7, 0x11: 8, 0x12: 9, 0x13: 10,
              0x14: 11, 0x15: 12, 0x16: 13, 0x22: 14}
# ncclResult_t of NCCL 2.32.3 (nccl.h of the GIN bundle build): 6 ncclRemoteError, 8 ncclTimeout
NCCL_RC = {0: "ok", 2: "ncclSystemError", 3: "ncclInternalError", 6: "ncclRemoteError", 7: "ncclInProgress",
           8: "ncclTimeout"}
API_REMOTE = "remote process exited or there was a network error"
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def scrub(s, n=180):
    s = IPV4.sub("<addr>", str(s)).replace("\n", " ")
    return s if len(s) <= n else s[:n - 3] + "..."


def text(path):
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def kv(path):
    """key=value pairs of a driver .kv file; a value runs until the next ' key='. okit lines skipped."""
    d = {}
    for line in text(path).splitlines():
        if line.startswith("okit="):
            continue
        for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line):
            d[m.group(1)] = m.group(2).strip()
    return d


def evrec_ctr(path):
    """(label, evidence) of the error-counter delta in one evrec file."""
    start, end = {}, {}
    try:
        with open(path, errors="replace") as f:
            for line in f:
                m = re.match(r"ctr phase=(start|end) dir=hw_counters name=(\S+) value=(\d+)", line)
                if m:
                    (start if m.group(1) == "start" else end)[m.group(2)] = int(m.group(3))
    except FileNotFoundError:
        return NO, "evrec file missing"
    if not start or not end:
        return NO, "evrec has no start/end hw_counters snapshot"
    d = {c: end[c] - start[c] for c in ERR_CTRS if c in start and c in end and end[c] != start[c]}
    if not d:
        return "+0", "evrec hw_counters: 14 error counters unchanged"
    lab = ",".join("%s+%d" % (c, d[c]) for c in sorted(d))
    return lab, "evrec hw_counters delta"


def scan_big(path, needles, cap=40, head=8 << 20):
    """Lines of a (possibly multi-GB) log that contain any of the needles (str). Streams the whole file
    in chunks; keeps at most `cap` lines per needle. Returns (lines in file order, total bytes)."""
    bneedles = [n.encode() for n in needles]
    found = {n: [] for n in bneedles}
    size = 0
    try:
        f = open(path, "rb")
    except FileNotFoundError:
        return [], 0
    with f:
        carry = b""
        off = 0
        while True:
            chunk = f.read(64 << 20)
            if not chunk:
                break
            size += len(chunk)
            buf = carry + chunk
            cut = buf.rfind(b"\n") + 1
            if cut == 0:
                carry = buf
                continue
            body, carry = buf[:cut], buf[cut:]
            for n in bneedles:
                if len(found[n]) >= cap:
                    continue
                p = body.find(n)
                while p >= 0 and len(found[n]) < cap:
                    a = body.rfind(b"\n", 0, p) + 1
                    b = body.find(b"\n", p)
                    found[n].append((off + a, body[a:b].decode(errors="replace")))
                    p = body.find(n, b)
            off += cut
        if carry:
            for n in bneedles:
                if n in carry and len(found[n]) < cap:
                    found[n].append((off, carry.decode(errors="replace")))
    seen, out = set(), []
    for n in bneedles:
        for pos, line in found[n]:
            if pos not in seen:
                seen.add(pos)
                out.append((pos, line))
    out.sort()
    return [l for _, l in out], size


def st_hex(s, v):
    return "%d/0x%02x" % (int(s), int(v, 0) if isinstance(v, str) else int(v))


def mk(stack, variant, tag, fault, fraw, wait, side, source):
    r = OrderedDict(stack=stack, variant=variant, tag=tag, fault=fault, fault_raw=fraw, wait_mode=wait,
                    side=side)
    for L in LAYERS:
        r[L] = NO
        r[L + "_ev"] = ""
    r["channel"] = NO
    r["channel_ev"] = ""
    r["source"] = source
    return r


def put(r, layer, label, ev):
    r[layer] = label
    r[layer + "_ev"] = scrub(ev)


ROWS = []

# ======================================================================== CPU verbs harness
CPU_FAULT = {"none": "F0", "local_qp_err": "F1", "rem_access": "F2", "retry_server_qp_err": "F3",
             "retry_proc_sigkill": "F4", "rem_inv_req": "X_rem_inv_req", "rnr": "X_rnr",
             "partial_write": "X_partial_write"}


def cpu(root):
    d = os.path.join(root, "cpu")
    for out in sorted(glob.glob(os.path.join(d, "logs", "cpu_*_t*.out"))):
        tag = os.path.basename(out)[:-4]
        m = re.match(r"cpu_(.+)_t(\d+)$", tag)
        fraw = m.group(1)
        txt = text(out)
        mc = re.search(r"wrote \S*/csv/(\S+\.csv)", txt)
        rows = list(csv.DictReader(open(os.path.join(d, "csv", mc.group(1))))) if mc else []
        r = rows[-1] if rows else {}
        f = CPU_FAULT[fraw]
        src = "cpu/logs/%s.out; cpu/csv/%s" % (tag, mc.group(1) if mc else "-")
        a = mk("cpu", "CPU", tag, f, fraw, "poll", "initiator", src)
        b = mk("cpu", "CPU", tag, f, fraw, "poll", "target", src)
        put(a, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.rain")))
        put(b, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.sunny")))
        put(a, "L0_qp", NO, "requester QP state is not recorded")
        if r:
            st = r["status"]
            lab = "none" if st in ("0", "") else st_hex(st, r["vendor_err"])
            put(a, "L1_root", lab, "csv status=%s vendor_err=%s (first CQE the harness polled)" % (st, r["vendor_err"]))
            put(a, "L1_read", lab, "same field: the harness polls its own CQ")
            cause = re.split(r"[:(]", r["cause"])[0].strip()
            cause = "none" if cause == "no error" else cause
            sub = r.get("sub_cause", "-")
            put(a, "L2", cause + ("" if sub in ("-", "") else " [%s]" % sub),
                "csv cause=%s; sub_cause=%s" % (r["cause"], sub))
            put(a, "L4_async", "none" if r["cli_async"] == "none" else r["cli_async"],
                "csv cli_async (requester async-event thread)")
            # liveness/control channel of the harness
            if sub in ("-", ""):
                put(a, "channel", "none", "csv sub_cause=-")
            else:
                a["channel"] = "liveness:" + sub
                a["channel_ev"] = scrub("csv sub_cause=%s peer_rx_delta=%s peer_alive=%s (control connection)"
                                        % (sub, r.get("peer_rx_delta"), r.get("peer_alive")))
            q = r["srv_qp_state"]
            if q == "-":
                put(b, "L0_qp", NO, "csv srv_qp_state=- (responder dead, DEVIATIONS 4)")
            else:
                put(b, "L0_qp", q, "csv srv_qp_state (QUERY_QP 10 ms after detection)")
            s = r["srv_async"]
            if s == "-":
                put(b, "L4_async", NO, "csv srv_async=- (responder dead, DEVIATIONS 4)")
            else:
                ev = "none" if s == "none" else ";".join(sorted(set(e.split("/")[0] for e in s.split(";"))))
                put(b, "L4_async", ev, "csv srv_async=%s" % s)
        put(a, "L3", NO, "the harness is the application; no separate API layer")
        mt = re.search(r"\[client\] teardown \(ep_close\) returned after ([\d.]+) ms", txt)
        if mt:
            put(a, "L5", "returned", "teardown (ep_close) returned after %s ms" % mt.group(1))
        for L in ("L1_root", "L1_read", "L2", "L3", "L4_log", "L5"):
            put(b, L, NO, "responder side not recorded by the harness")
        put(a, "L4_log", NO, "no library log (verbs only)")
        put(b, "channel", NO, "responder side not recorded by the harness")
        ROWS.extend([a, b])


# ======================================================================== NCCL GIN (gp gg gq)
GIN_IGNORE = ("GIN/FAULT:", "lib wrapper not initialized", "device error classification ON")


def gin_log_items(txt):
    """normalized error items of one GIN rank log (library lines only)."""
    items, first_cqe = [], None
    for line in txt.splitlines():
        if any(x in line for x in GIN_IGNORE):
            continue
        m = re.search(r"Got completion from peer .*? with status=(\d+) .*?vendor err (\d+)", line)
        if m:
            c = st_hex(m.group(1), int(m.group(2)))
            first_cqe = first_cqe or c
            items.append("cqe " + c)
            continue
        if "Error on GFD test" in line:
            items.append("proxy GFD error")
        elif "GIN Error detected" in line:
            items.append("GIN Error detected")
        elif "device-classified error CQE" in line:
            m = re.search(r"class=(\w+)", line)
            items.append("Q4 class=" + (m.group(1) if m else "?"))
        elif re.search(r"host QUERY_QP .*state=(\w+)", line):
            items.append("QUERY_QP " + re.search(r"host QUERY_QP .*state=(\w+)", line).group(1))
        elif "async fatal event on QP" in line:
            m = re.search(r"async fatal event on QP.*?: (.*)$", line)
            items.append("async fatal event (%s)" % (m.group(1).strip() if m else "?"))
        elif "NCCL WARN" in line:
            items.append("WARN " + re.sub(r".*NCCL WARN ", "", line)[:40])
    return items, first_cqe


def first_line(txt, pat):
    m = re.search(pat, txt, re.M)
    return m.group(0) if m else ""


def gin(root, rerun, stack):
    prefix = {"gp": "proxy", "gg": "gdaki", "gq": "ring_c1"}[stack]
    variant = stack.upper()
    srcs = [(root, False)]
    if rerun and stack in ("gp", "gg"):
        srcs.append((rerun, True))
    for base, is_rerun in srcs:
        d = os.path.join(base, stack)
        path = os.path.join(d, stack + ".csv")
        if not os.path.exists(path):
            continue
        for r in csv.DictReader(open(path)):
            f = r["fault"]
            if stack in ("gp", "gg") and rerun:
                if is_rerun and f != "F4":
                    continue
                if not is_rerun and f == "F4":
                    continue     # DEVIATIONS 10: the campaign F4 trials of gp and gg are replaced
            fault = "F0" if f == "none" else f
            mode = r["wait_mode"]
            t = r["trial"]
            lb = "%s_%s_%s_t%s" % (prefix, f, mode, t)
            tag = "%s_%s_%s_t%s" % (stack, f, mode, t)
            rel = os.path.relpath(os.path.join(d, "logs", lb), root)
            k0, k1 = kv(os.path.join(d, "logs", lb + "_r0.kv")), kv(os.path.join(d, "logs", lb + "_r1.kv"))
            l0, l1 = text(os.path.join(d, "logs", lb + "_r0.log")), text(os.path.join(d, "logs", lb + "_r1.log"))
            src = rel + "_r{0,1}.{kv,log}"
            a = mk(stack, variant, tag, fault, f, mode, "initiator", src)
            b = mk(stack, variant, tag, fault, f, mode, "target", src)
            put(a, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.rain")))
            put(b, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.sunny")))
            it0, cqe0 = gin_log_items(l0)
            it1, cqe1 = gin_log_items(l1)
            # ---- initiator
            if stack == "gq":
                q = re.search(r"host QUERY_QP .*?state=(\w+)", l0)
                if q:
                    put(a, "L0_qp", q.group(1), "r0.log Q4 host QUERY_QP state=" + q.group(1))
                else:
                    put(a, "L0_qp", NO, "no QUERY_QP line (Q4 queries only after a classified error)")
                m = re.search(r"device-classified error CQE .*?fp=(\d+)/(0x[0-9a-f]+).*?class=(\w+)", l0)
                pol = re.search(r"polled\[[^\]]*syn=(0x[0-9a-f]+) ve=(0x[0-9a-f]+)\]", l0)
                if m:
                    c = st_hex(m.group(1), m.group(2))
                    put(a, "L1_root", c, "r0.log Q4 record fp=%s/%s (root CQE found by scan-back)" % (m.group(1), m.group(2)))
                    pe = ("; polled slot syn=%s ve=%s" % pol.groups()) if pol else ""
                    put(a, "L1_read", c, "Q4 reads the root by scan-back" + pe)
                    put(a, "L2", m.group(3), "r0.log Q4 class=" + m.group(3))
                else:
                    for L in ("L1_root", "L1_read", "L2"):
                        put(a, L, "none", "Q4 classification on, no error record in r0.log")
            elif stack == "gp":
                put(a, "L0_qp", NO, "not recorded")
                m = re.search(r"Got completion from peer .*? with status=(\d+) .*?vendor err (\d+)", l0)
                if m:
                    c = st_hex(m.group(1), int(m.group(2)))
                    put(a, "L1_root", c, "r0.log proxy WARN status=%s vendor err %s (first error CQE)" % m.groups())
                    put(a, "L1_read", c, "same line: the proxy logs the CQE it polled")
                    put(a, "L2", c, "proxy thread WARN with the CQE; it also logs 'Error on GFD test 6' "
                                    "(ncclRemoteError) %d time(s)" % l0.count("Error on GFD test 6"))
                else:
                    for L in ("L1_root", "L1_read", "L2"):
                        put(a, L, "none", "no 'Got completion ... status' WARN in r0.log")
            else:  # gg: stock GDAKI logs no CQE and no device result
                put(a, "L0_qp", NO, "not recorded")
                put(a, "L1_root", NO, "stock GDAKI does not log the CQE")
                put(a, "L1_read", NO, "stock GDAKI does not log the CQE")
                put(a, "L2", NO, "device result (-EIO) is not logged by the stock build")
            # L3 initiator
            if "hang_it" in k0:
                put(a, "L3", "hang", "r0.kv hang_it=%s (blocking wait did not return)" % k0["hang_it"])
            elif "device_rc" in k0:
                v = k0["device_rc"]
                v = "ncclRemoteError" if v.startswith(API_REMOTE) else v
                put(a, "L3", v, "r0.kv device_rc")
            elif "drain_device_rc" in k0:
                v = NCCL_RC.get(int(k0["drain_device_rc"]), "rc=" + k0["drain_device_rc"])
                sil = r.get("init_silent_iters", "0")
                put(a, "L3", v, "r0.kv drain_device_rc=%s drain_outcome=%s (driver drain: bounded wait after "
                                "'peer gone'); init_silent_iters=%s" % (k0["drain_device_rc"], k0.get("drain_outcome"), sil))
            elif k0.get("init_outcome") == "ok":
                sil = r.get("init_silent_iters", "0")
                silent = sil not in ("0", "-1", "", None) or r.get("silent_success") == "1"
                put(a, "L3", "ok (silent)" if silent else "ok",
                    "r0.kv init_outcome=ok iters_ok=%s; init_silent_iters=%s" % (k0.get("iters_ok"), sil))
            else:
                put(a, "L3", NO, "r0.kv has no wait result")
            he = k0.get("host_error")
            if he is None:
                put(a, "L4_async", NO, "r0.kv host_error missing")
            else:
                put(a, "L4_async", "ncclRemoteError" if he.startswith(API_REMOTE) else he,
                    "r0.kv host_error (ncclCommGetAsyncError) at %s ms" % k0.get("host_error_ms"))
            put(a, "L4_log", "; ".join(sorted(set(it0))) or "none", "r0.log library lines")
            td = k0.get("teardown")
            put(a, "L5", {"clean": "returned", "hang": "hang"}.get(td, NO if td is None else td),
                "r0.kv teardown=%s teardown_ms=%s" % (td, k0.get("teardown_ms")))
            pg = re.search(r"\[rank0\] peer gone at it (\d+)", l0)
            if pg:
                a["channel"] = "peer gone (driver TCP)"
                a["channel_ev"] = "r0.log '[rank0] peer gone at it %s' (per-iteration TCP sync of the driver)" % pg.group(1)
            else:
                put(a, "channel", "none", "no 'peer gone' line")
            # ---- target
            put(b, "L0_qp", NO, "not recorded")
            for L in ("L1_root", "L1_read", "L2"):
                put(b, L, NO, "not recorded (one-sided put: the target polls no completion for it)")
            if fault == "F4":
                for L in ("L3", "L4_async", "L4_log", "L5"):
                    put(b, L, NO, "target killed (F4)")
                put(b, "channel", NO, "target killed (F4)")
            else:
                if "hang_it" in k1:
                    put(b, "L3", "hang", "r1.kv hang_it=%s" % k1["hang_it"])
                elif "device_rc" in k1:
                    v = k1["device_rc"]
                    put(b, "L3", "ncclRemoteError" if v.startswith(API_REMOTE) else v,
                        "r1.kv device_rc; data_check=%s" % k1.get("data_check"))
                elif k1.get("init_outcome") == "ok":
                    put(b, "L3", "ok", "r1.kv init_outcome=ok data_check=%s" % k1.get("data_check"))
                else:
                    put(b, "L3", NO, "r1.kv has no wait result")
                he = k1.get("host_error")
                put(b, "L4_async", NO if he is None else ("ncclRemoteError" if he.startswith(API_REMOTE) else he),
                    "r1.kv host_error (ncclCommGetAsyncError) at %s ms" % k1.get("host_error_ms"))
                put(b, "L4_log", "; ".join(sorted(set(it1))) or "none", "r1.log library lines")
                td = k1.get("teardown")
                put(b, "L5", {"clean": "returned", "hang": "hang"}.get(td, NO if td is None else td),
                    "r1.kv teardown=%s" % td)
                pg = re.search(r"\[rank1\] peer gone at it (\d+)", l1)
                put(b, "channel", "peer gone (driver TCP)" if pg else "none",
                    ("r1.log peer gone at it " + pg.group(1)) if pg else "no 'peer gone' line")
            ROWS.extend([a, b])


# ======================================================================== NVSHMEM official 3.8.0 (nvo)
NV_IGNORE = ("NVLINK SHARP", "NVSHMEM INFO", "nvshmem-fault-inject", "PE0 enabled", "PE1 enabled")


def nv_err_lines(txt):
    out = []
    for line in txt.splitlines():
        if any(x in line for x in NV_IGNORE):
            continue
        if re.search(r"WARN|ERROR|[Ee]rror CQE|marked failed|async", line):
            out.append(line)
    return out


def nvo(root):
    d = os.path.join(root, "nvo")
    vids = {"stock_cpu_host_memory": "NC", "stock_gpu": "NG", "fix_cpu_host_memory": "NX"}
    for p0 in sorted(glob.glob(os.path.join(d, "runs", "*.pe0.log"))):
        name = os.path.basename(p0)[:-len(".pe0.log")]
        m = re.match(r"(stock|fix)_(cpu_host_memory|gpu)_kill(\d)_t(\d+)$", name)
        vid = vids["%s_%s" % (m.group(1), m.group(2))]
        k = int(m.group(3))
        tag = "nvo_%s_kill%d_t%s" % (vid, k, m.group(4))
        fault = "F4" if k else "F0"
        t0, t1 = text(p0), text(p0[:-len(".pe0.log")] + ".pe1.log")
        src = "nvo/runs/%s.pe{0,1}.log" % name
        a = mk("nvo", vid, tag, fault, "kill%d" % k, "quiet", "initiator", src)
        b = mk("nvo", vid, tag, fault, "kill%d" % k, "quiet", "target", src)
        put(a, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.rain")))
        put(b, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.sunny")))
        for x in (a, b):
            put(x, "L0_qp", NO, "not recorded")
            for L in ("L1_root", "L1_read", "L2"):
                put(x, L, NO, "the official 3.8.0 build logs no CQE and no consumer result")
            put(x, "L4_async", NO, "no async error API in the driver or library")
        hung = re.search(r"PE 0 iter (\d+): nvshmem_quiet\(\) has not returned after (\d+) s", t0)
        allret = "PE 0: all 40 iterations returned" in t0
        if hung:
            put(a, "L3", "hang", hung.group(0))
        elif allret:
            put(a, "L3", "ok (silent)" if k else "ok",
                "PE 0: all 40 iterations returned" + ("; PE 1 SIGKILLed after iter 3" if k else ""))
        el = nv_err_lines(t0)
        put(a, "L4_log", "none" if not el else "; ".join(sorted(set(l[:50] for l in el))),
            "pe0.log WARN/ERROR lines (NVLINK SHARP and INFO excluded): %d" % len(el))
        ft = re.search(r"PE 0: nvshmem_finalize returned after ([\d.]+) ms", t0)
        if ft:
            put(a, "L5", "returned", ft.group(0))
        elif re.search(r"PE 0: nvshmem_finalize did not return after (\d+) s", t0):
            put(a, "L5", "hang", first_line(t0, r"PE 0: nvshmem_finalize did not return after \d+ s"))
        put(a, "channel", "none", "no liveness channel in the driver")
        if k:
            for L in ("L3", "L4_log", "L5"):
                put(b, L, NO, "PE 1 killed (F4)")
            put(b, "channel", NO, "PE 1 killed (F4)")
        else:
            if "PE 1: all 40 iterations returned" in t1:
                put(b, "L3", "ok", "PE 1: all 40 iterations returned (signal arrived)")
            el = nv_err_lines(t1)
            put(b, "L4_log", "none" if not el else "; ".join(sorted(set(l[:50] for l in el))),
                "pe1.log WARN/ERROR lines: %d" % len(el))
            ft = re.search(r"PE 1: nvshmem_finalize returned after ([\d.]+) ms", t1)
            if ft:
                put(b, "L5", "returned", ft.group(0))
            put(b, "channel", "none", "-")
        ROWS.extend([a, b])


# ======================================================================== NVSHMEM devel + hooks (nvd)
def cqe_from(syn, ven):
    s = SYN2STATUS.get(int(syn, 16))
    return ("%d/%s" % (s, ven.lower())) if s is not None else "syn%s/%s" % (syn, ven)


def nvd(root):
    d = os.path.join(root, "nvd")
    for h in ("auto", "cpu_host_memory"):
        for p0 in sorted(glob.glob(os.path.join(d, "runs_" + h, "*.pe0.log"))):
            name = os.path.basename(p0)[:-len(".pe0.log")]
            m = re.match(r"(F\w+?)_timeout_t(\d+)$", name)
            fraw, t = m.group(1), m.group(2)
            fault = {"F2b": "F2"}.get(fraw, fraw)
            tag = "nvd_%s_%s_t%s" % (h, fraw, t)
            t0, t1 = text(p0), text(p0[:-len(".pe0.log")] + ".pe1.log")
            hm = re.search(r"NIC handler will be ([^.\n]*)", t0)
            handler = hm.group(1).strip() if hm else "?"
            vid = "ND-GPU" if handler == "GPU" else ("ND-CPU" if handler.startswith("CPU") else "ND-" + h)
            src = "nvd/runs_%s/%s.pe{0,1}.log" % (h, name)
            a = mk("nvd", vid, tag, fault, fraw, "timeout", "initiator", src)
            b = mk("nvd", vid, tag, fault, fraw, "timeout", "target", src)
            put(a, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.rain")))
            put(b, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.sunny")))
            put(a, "L0_qp", NO, "only the injection hook's own QUERY_QP (excluded)")
            put(b, "L0_qp", NO, "only the injection hook's own QUERY_QP (excluded)")
            scans = re.findall(r"^SCAN iter \d+ rank 0 .*$", t0, re.M)
            err = re.search(r"^SCAN iter \d+ rank 0 ERRCQE .*?syn=(0x[0-9a-f]+) ven=(0x[0-9a-f]+)", t0, re.M)
            if err:
                put(a, "L1_root", cqe_from(*err.groups()), "pe0.log first 'SCAN ... ERRCQE' (full CQ-buffer scan) syn=%s ven=%s" % err.groups())
            elif scans:
                put(a, "L1_root", "none", "pe0.log: %d SCAN lines, no ERRCQE" % len(scans))
            fl = None
            for line in re.findall(r"^ITER \d+ rank 0 .*$", t0, re.M):
                if re.search(r"wait_rc=[12]\b", line):
                    fl = line
                    break
            if fl:
                g = dict(re.findall(r"(\w+)=(\S+)", fl))
                if g.get("cqe_opcode", "").lower() == "0xd":
                    put(a, "L1_read", cqe_from(g["cqe_syndrome"], g["cqe_vendor_err"]),
                        "pe0.log failing ITER slot opcode=0xd syndrome=%s vendor=%s" % (g["cqe_syndrome"], g["cqe_vendor_err"]))
                else:
                    put(a, "L1_read", "none", "pe0.log failing ITER slot opcode=%s (not an error CQE)" % g.get("cqe_opcode"))
                wrc = g.get("wait_rc")
                put(a, "L2", {"2": "error CQE", "1": "timeout"}.get(wrc, "wait_rc=" + str(wrc)),
                    "pe0.log ITER wait_rc=%s (the driver's own bounded device poll)" % wrc)
            put(a, "L3", NO, "timeout mode: the driver's bounded poll replaces nvshmem_quiet")
            put(b, "L3", NO, "-")
            for x, tx, who in ((a, t0, "pe0"), (b, t1, "pe1")):
                put(x, "L4_async", NO, "no async error API in the driver or library")
                el = nv_err_lines(tx)
                put(x, "L4_log", "none" if not el else "; ".join(sorted(set(l[:50] for l in el))),
                    "%s.log WARN/ERROR lines (injection hook excluded): %d" % (who, len(el)))
                if re.search(r"^SUMMARY rank \d .*\n(?:.*\n)*?WATCHDOG: kernel/quiet did not return", tx, re.M):
                    put(x, "L5", "hang", "%s.log WATCHDOG after SUMMARY (nvshmem_free/finalize under a 15 s alarm)" % who)
                put(x, "channel", "none", "oob=0 (no liveness channel)")
            miss = re.search(r"^ITER (\d+) rank 1 .*data_check=missing.*$", t1, re.M)
            if miss:
                put(b, "L3", "timeout", "pe1.log ITER %s data_check=missing (driver's bounded wait)" % miss.group(1))
            elif re.search(r"^ITER \d+ rank 1 ", t1, re.M):
                put(b, "L3", "ok", "pe1.log every ITER data_check=ok")
            for L in ("L1_root", "L1_read", "L2"):
                put(b, L, NO, "not recorded")
            ROWS.extend([a, b])


# ======================================================================== NVSHMEM FT v2.2 (nvf)
def nvf(root):
    d = os.path.join(root, "nvf")
    for p0 in sorted(glob.glob(os.path.join(d, "runs", "*.pe0.log"))):
        name = os.path.basename(p0)[:-len(".pe0.log")]
        m = re.match(r"(\w+?)_timeout_ft1_rec1_prop_t(\d+)$", name)
        fraw, t = m.group(1), m.group(2)
        fault = {"none": "F0", "F2b": "F2"}.get(fraw, fraw)
        tag = "nvf_%s_t%s" % (fraw, t)
        t0, t1 = text(p0), text(p0[:-len(".pe0.log")] + ".pe1.log")
        src = "nvf/runs/%s.pe{0,1}.log" % name
        a = mk("nvf", "NF", tag, fault, fraw, "timeout", "initiator", src)
        b = mk("nvf", "NF", tag, fault, fraw, "timeout", "target", src)
        put(a, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.rain")))
        put(b, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.sunny")))
        q = re.search(r"\[nvshmem-ft\] PE0 host QUERY_QP .*?state=(\d+)\((\w+)\)", t0)
        put(a, "L0_qp", q.group(2) if q else NO,
            ("pe0.log FT host QUERY_QP state=%s(%s)" % q.groups()) if q else "no FT QUERY_QP line (queried only after an error)")
        put(b, "L0_qp", NO, "not recorded")
        fr = re.search(r"^FAULTREC .*$", t0, re.M)
        frd = dict(re.findall(r"(\w+)=(\S+)", fr.group(0))) if fr else {}
        if fr:
            put(a, "L1_root", frd["fp"].split("/")[0] + "/" + frd["fp"].split("/")[1].lower(),
                "pe0.log FAULTREC fp=%s (FT record: ring walk to the root CQE)" % frd["fp"])
        else:
            put(a, "L1_root", "none", "FT on, no FAULTREC line")
        bad = None
        slots_err = 0
        for line in re.findall(r"^ITER \d+ rank 0 round \d+ .*$", t0, re.M):
            g = dict(re.findall(r"(\w+)=(\S+)", line))
            if g.get("slot", "").startswith("d/"):
                slots_err += 1
            if bad is None and g.get("rc") != "0":
                bad = g
        if bad:
            op, syn, ven = re.match(r"([0-9a-f]+)/(0x[0-9a-f]+)/(0x[0-9a-f]+)", bad["slot"]).groups()
            put(a, "L1_read", cqe_from(syn, ven) if op == "d" else "none",
                "pe0.log first ITER with rc=%s: slot=%s" % (bad["rc"], bad["slot"]))
        else:
            put(a, "L1_read", "none", "no ITER with rc!=0; %d slots with an error opcode" % slots_err)
        dc = re.search(r"\[nvshmem-ft\] PE0 device-classified error CQE .*?class=(\w+)", t0)
        put(a, "L2", dc.group(1) if dc else "none",
            ("pe0.log FT device classifier class=" + dc.group(1)) if dc else "no device-classified line")
        sm = re.search(r"^SUMMARY rank 0 .*? rc=(\d+) .*?declined=(\d+)", t0, re.M)
        outcome = "-"
        if sm:
            outcome = "recovered" if sm.group(1) == "0" and fault != "F0" else ("declined" if sm.group(2) != "0" else "ok")
        if fr:
            put(a, "L3", frd["class"], "ITER rc=%s; FT query class=%s have=%s; app result after policy: %s (SUMMARY rc=%s)"
                % (frd.get("kernel_rc"), frd["class"], frd.get("have"), outcome, sm.group(1) if sm else "?"))
        elif sm:
            put(a, "L3", "ok" if sm.group(1) == "0" else "rc=" + sm.group(1), "SUMMARY rank 0 rc=%s, no FAULTREC" % sm.group(1))
        put(a, "L4_async", NO, "no async error API")
        items = []
        for line in t0.splitlines():
            if "[nvshmem-ft] PE0 device-classified error CQE" in line:
                items.append("FT class=" + re.search(r"class=(\w+)", line).group(1))
            elif "marked failed (recovery declined/aborted)" in line:
                items.append("marked failed")
            elif "[nvshmem-ft] PE0 host QUERY_QP" in line:
                items.append("QUERY_QP " + (q.group(2) if q else "?"))
        put(a, "L4_log", "; ".join(sorted(set(items))) or "none", "pe0.log [nvshmem-ft] lines (enable line excluded)")
        td = re.search(r"^TEARDOWN rank 0 .*returned=1", t0, re.M)
        if td:
            put(a, "L5", "returned", td.group(0))
        if fr:
            a["channel"] = "liveness=" + frd.get("liveness", "?")
            a["channel_ev"] = scrub("FAULTREC liveness=%s (driver TCP peek)%s" % (
                frd.get("liveness"), "; PEERGONE line" if "PEERGONE" in t0 else ""))
        else:
            put(a, "channel", "none", "no FAULTREC")
        # target PE1
        for L in ("L1_root", "L1_read", "L2"):
            put(b, L, NO, "not recorded")
        put(b, "L4_async", NO, "no async error API")
        if fault == "F4":
            for L in ("L3", "L4_log", "L5"):
                put(b, L, NO, "PE 1 killed (F4)")
            put(b, "channel", NO, "PE 1 killed (F4)")
        else:
            s1 = re.search(r"^SUMMARY rank 1 .*? rc=(\d+)", t1, re.M)
            if s1:
                put(b, "L3", "ok" if s1.group(1) == "0" else "rc=" + s1.group(1), "pe1.log SUMMARY rank 1 rc=" + s1.group(1))
            mf = "marked failed (recovery declined/aborted)" in t1
            put(b, "L4_log", "marked failed" if mf else "none", "pe1.log [nvshmem-ft] lines")
            td = re.search(r"^TEARDOWN rank 1 .*returned=1", t1, re.M)
            if td:
                put(b, "L5", "returned", td.group(0))
            if "FAILMSG" in t1:
                put(b, "channel", "peer message: FAIL", first_line(t1, r"^FAILMSG .*$"))
            elif "RXREC" in t1:
                put(b, "channel", "peer message: recovery", "pe1.log RXREC (recovery request from PE 0 over the driver TCP)")
            else:
                put(b, "channel", "none", "-")
        ROWS.extend([a, b])


# ======================================================================== NCCL 2.23.4 net_ib (net)
NET_NEEDLES = ["Got completion from peer", "incident via cqe", "comm FAILED in", "peer sent FAIL",
               "async fatal event on QP", "async NCCL error", "SUMMARY rank=", "ABORT-HANG",
               "ncclCommAbort returned", "communicator encountered a fatal error", "recovered"]


def net_items(lines):
    items, cqe, fail = [], None, None
    for l in lines:
        m = re.search(r"Got completion from peer .*? with status=(\d+) .*?vendor err (\d+) \((\w+)\)", l)
        if m:
            c = st_hex(m.group(1), int(m.group(2)))
            cqe = cqe or (c, "WARN 'Got completion ... status=%s vendor err %s (%s)'" % m.groups())
            items.append("cqe " + c)
            continue
        m = re.search(r"incident via cqe: status=(\d+)\(\w+\) vendor_err=(0x[0-9a-f]+)", l)
        if m:
            c = st_hex(m.group(1), m.group(2))
            cqe = cqe or (c, "WARN '[FAULT-RECOVERY2] ... incident via cqe: status=%s vendor_err=%s'" % m.groups())
            items.append("FR2 incident " + c)
            continue
        m = re.search(r"comm FAILED in (\w+) \(([^,]*),", l)
        if m:
            fail = fail or m.group(2)
            items.append("FR2 failed (%s)" % m.group(2))
        elif "peer sent FAIL" in l:
            items.append("FR2 peer sent FAIL")
        elif "async fatal event on QP" in l:
            items.append("async fatal event")
        elif "communicator encountered a fatal error" in l:
            items.append("fatal error (detected in test)")
    return items, cqe, fail


def net(root):
    d = os.path.join(root, "net")
    for f in sorted(glob.glob(os.path.join(d, "runs", "*", "results.csv"))):
        run = os.path.basename(os.path.dirname(f))
        rows = list(csv.DictReader(open(f)))
        if not rows:
            continue
        r = rows[0]
        test = r["test"]
        fault = "F0" if test == "T0s" else "F2"
        vid = "NET-stock" if test == "F2stock" else "NET-S2"
        tag = "net_" + run
        lg = glob.glob(os.path.join(os.path.dirname(f), "*_r0.log"))
        p0 = lg[0] if lg else ""
        p1 = p0[:-len("_r0.log")] + "_r1.log" if p0 else ""
        src = "net/runs/%s/{results.csv,*_r0.log,*_r1.log}" % run
        a = mk("net", vid, tag, fault, test, "async", "initiator", src)
        b = mk("net", vid, tag, fault, test, "async", "target", src)
        put(a, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.rain")))
        put(b, "L0_ctr", *evrec_ctr(os.path.join(d, "evrec", tag + ".evrec.sunny")))
        for x, p, who, api, rc in ((a, p0, "r0", r.get("r0_api", ""), r.get("rc0")),
                                   (b, p1, "r1", r.get("r1_api", ""), r.get("rc1"))):
            lines, size = scan_big(p, NET_NEEDLES)
            lines = [l for l in lines if "[FAULT-INJECT]" not in l]
            items, cqe, fail = net_items(lines)
            put(x, "L0_qp", NO, "not recorded")
            if cqe:
                put(x, "L1_root", cqe[0], who + ".log first error CQE line: " + cqe[1])
                put(x, "L1_read", cqe[0], "same line: net_ib logs the CQE it polled")
            elif fault == "F0":
                put(x, "L1_root", "none", who + ".log has no error CQE line")
                put(x, "L1_read", "none", who + ".log has no error CQE line")
            else:
                put(x, "L1_root", NO, who + ".log has no CQE line (the comm failed on the peer's FAIL message)")
                put(x, "L1_read", "none", who + ".log has no CQE line before the comm failed")
            if vid == "NET-S2" and fault != "F0":
                if fail:
                    put(x, "L2", "fail: " + fail, who + ".log [FAULT-RECOVERY2] comm FAILED (%s)" % fail)
                else:
                    put(x, "L2", NO, who + ".log no FAILED line")
            else:
                put(x, "L2", cqe[0] if cqe else "none", (who + ".log consumer WARN (stock path)") if cqe
                    else who + ".log no consumer error line")
            if api:
                put(x, "L3", api if api != "" else "ok", "results.csv %s_api (nccl_ct: 'async NCCL error: ...')" % who)
                put(x, "L4_async", api, "same call as L3: nccl_ct polls ncclCommGetAsyncError")
            else:
                ok = rc == "0"
                put(x, "L3", "ok" if ok else NO, "results.csv %s_api empty, rc%s=%s" % (who, who[1], rc))
                put(x, "L4_async", "none" if ok else NO, "no async NCCL error line, rc=%s" % rc)
            put(x, "L4_log", "; ".join(sorted(set(items))) or "none",
                "%s.log library lines (%d MB scanned in full)" % (who, size >> 20))
            if any("ABORT-HANG" in l for l in lines):
                put(x, "L5", "hang", who + ".log ABORT-HANG: ncclCommAbort did not return within the watchdog")
            elif any("ncclCommAbort returned" in l for l in lines):
                put(x, "L5", "returned", who + ".log ncclCommAbort returned")
            elif rc == "0":
                put(x, "L5", "returned", "rc%s=0: ncclCommDestroy path (exit 0), not timed" % who[1])
            liv = [l for l in lines if "peer=" in l]
            if any("peer sent FAIL" in l for l in lines):
                put(x, "channel", "peer FAIL message", "Stage 2 control message from the peer: 'peer sent FAIL'")
            elif liv:
                m = re.search(r"peer=([\w-]+)", liv[0])
                put(x, "channel", "liveness:" + m.group(1), "FR2 incident line peer=" + m.group(1))
            else:
                put(x, "channel", "none", "-")
        ROWS.extend([a, b])


# ======================================================================== analysis
FAULTS = ["F0", "F1", "F2", "F3", "F4", "X_rem_inv_req", "X_rnr", "X_partial_write"]
CORE = ["F0", "F1", "F2", "F3", "F4"]
VARIANTS = ["CPU", "GP", "GG", "GQ", "NC", "NG", "NX", "ND-GPU", "ND-CPU", "NF", "NET-stock", "NET-S2"]
NOERR = {"none", "ok", "returned", "+0", "RTS"}   # baseline when a variant has no no-fault control
CHAIN = ["L1_root", "L1_read", "L2", "L3", "L4_async", "L4_log", "L5"]


def norm(label):
    """the observable value: a silent success shows the same value as success."""
    return label[:-len(" (silent)")] if label.endswith(" (silent)") else label


def trials(variant, side, fault):
    return [r for r in ROWS if r["variant"] == variant and r["side"] == side and r["fault"] == fault]


def control(variant, side):
    """labels of the no-fault control per layer; NET-stock borrows the net T0s control (DEVIATIONS 5)."""
    v = "NET-S2" if variant == "NET-stock" else variant
    rows = trials(v, side, "F0")
    return {L: set(norm(r[L]) for r in rows if r[L] != NO) for L in LAYERS}, len(rows)


def ran(variant, side):
    return [f for f in FAULTS if trials(variant, side, f)]


def fclass(variant, side, fault, L):
    """class of a fault at a layer: ('ok', label) if >= 90 % of its trials show it, ('no', None) if no
    trial is observed, ('split', Counter) otherwise."""
    rows = trials(variant, side, fault)
    if variant == "NET-stock" and fault == "F0":
        rows = trials("NET-S2", side, "F0")
    labs = [norm(r[L]) for r in rows if r[L] != NO]
    if not labs:
        return ("no", None, len(rows))
    c = Counter(labs)
    top, k = c.most_common(1)[0]
    if k >= math.ceil(0.9 * len(rows)):
        return ("ok", top, len(rows))
    return ("split", c, len(rows))


def faults_of(variant, side):
    fs = ran(variant, side)
    if variant == "NET-stock" and "F0" not in fs:
        fs = ["F0"] + fs     # DEVIATIONS 5: the net no-fault control is T0s
    return fs


def partition(variant, side, L, only=None):
    """(classes: list of lists of faults, splits: {fault: Counter}, unobserved: [faults])"""
    groups, splits, unobs = OrderedDict(), {}, []
    for f in faults_of(variant, side):
        if only is not None and f not in only:
            continue
        kind, val, _ = fclass(variant, side, f, L)
        if kind == "no":
            unobs.append(f)
        elif kind == "split":
            splits[f] = val
        else:
            groups.setdefault(val, []).append(f)
    return list(groups.values()), splits, unobs, list(groups.keys())


def arrival(variant, side, fault, L):
    """(k, n_obs, n): trials whose label differs from the no-fault control (or from 'no error')."""
    ctl, nctl = control(variant, side)
    base = ctl[L] if ctl[L] else NOERR
    rows = trials(variant, side, fault)
    obs = [r for r in rows if r[L] != NO]
    k = sum(1 for r in obs if norm(r[L]) not in base)
    return k, len(obs), len(rows), bool(ctl[L])


def splits_between(variant, side, lower, upper):
    """pairs of faults in one class at `lower` but in different classes at `upper`."""
    out = []
    fs = faults_of(variant, side)
    cl = {f: fclass(variant, side, f, lower) for f in fs}
    cu = {f: fclass(variant, side, f, upper) for f in fs}
    for i, a in enumerate(fs):
        for b in fs[i + 1:]:
            if cl[a][0] == cl[b][0] == cu[a][0] == cu[b][0] == "ok":
                if cl[a][1] == cl[b][1] and cu[a][1] != cu[b][1]:
                    out.append((a, b))
    return out


def observed_layer(variant, side, L):
    cls, sp, un, _ = partition(variant, side, L)
    return sum(len(c) for c in cls) + len(sp) >= 2


def core_splits(side="initiator"):
    res = []
    for v in VARIANTS:
        if not ran(v, side):
            continue
        prev = None
        for L in CHAIN:
            if not observed_layer(v, side, L):
                continue
            if prev is not None:
                s = splits_between(v, side, prev, L)
                if s:
                    res.append((v, side, prev, L, s))
            prev = L
    return res


# ---------------------------------------------------------------- pre-registered partitions
# REVIEW_20261006.md "Partition of {F0..F4} per layer, initiator side" plus the two rules of
# PREDICTIONS.md "Predicted partitions". A string "F0|F1|F2,F4|F3" is the predicted classes; None =
# the review cell is not a partition. How each cell is read into a partition is this script's
# reading, written next to it.
R_CPU = "CPU verbs (harness)"
R_GP = "GIN proxy, stock"
R_GG = "GIN GDAKI, stock"
R_GQ = "GDAKI + Q4"
R_NC = "NVSHMEM CPU proxy, stock"
R_NG = "NVSHMEM GPU handler, or CPU + DBR fix"
R_NF = "NVSHMEM FT v2.2 (ring)"
R_NET = "NCCL net_ib, stock"
R_NETS2 = "net_ib + Stage 2"
NOT_RUN_ROWS = ["GDAKI + Q4 + recovery", "GIN S1/S2", "NVSHMEM FT v1"]

NC_ROW = {"L1_root": ("F0,F1,F2,F3,F4", "nothing (no CQE at all)"),
          "L1_read": ("F0,F1,F2,F3,F4", "nothing"),
          "L2": ("F0|F1,F2,F3,F4", "F0 | F1..F4 (spin)"),
          "L3": ("F0|F1,F2,F3,F4", "F0 | F1..F4 (hang)"),
          "L4_log": ("F0,F1,F2,F3,F4", "1 (nothing)"),
          "L5": ("F0|F1,F2,F3,F4", "F1..F4 hang")}
NG_ROW = {"L1_root": ("F0|F1|F2|F3,F4", "F0 | F1 | F2 | F3,F4 (~60 us, then 5/0xf9)"),
          "L1_read": ("F0|F1,F2,F3,F4", "F0 | F1..F4"),
          "L2": ("F0|F1,F2,F3,F4", "F0 | F1..F4"),
          "L3": ("F0,F1,F2,F3,F4", "one class: all silent"),
          "L4_log": ("F0,F1,F2,F3,F4", "1 (nothing)"),
          "L5": ("F0|F1,F2,F3,F4", "F1..F4 hang")}
NONET = (None, "F2 (remote access) is not in the review table (listed there as a gap)")
# Korean gloss of the review cells that are not partitions (printed in LAYERS.md)
NOPRED_KO = {"(harness = app)": "하네스가 곧 앱", "no async events recorded": "비동기 이벤트 기록 없음",
             "not timed": "시간을 재지 않음",
             "blocking F1..F3 hang (this campaign ran GP in timeout mode only)":
                 "blocking 대기의 멈춤만 적혀 있고, 이번에는 timeout 대기만 돌림",
             "target rank hangs (see the target rule)": "상대 쪽 이야기라 상대 쪽 규칙으로 비교함",
             "hangs without ft_abort (flap 6/6)": "ft_abort 없이는 멈춤, 이번 드라이버는 실패 표시 뒤 정리함",
             NONET[1]: "원격 접근 오류가 리뷰 표에 없음, 리뷰가 채울 빈칸으로 적음"}
GIN_TARGET = {"L3": ("F1,F2,F3", "added rule: one class at L3 for F1-F3 (EV4)"),
              "L4_async": ("F1,F2,F3", "added rule: one class at L4 for F1-F3 (EV4)"),
              "L4_log": ("F1,F2,F3", "added rule: one class at L4 for F1-F3 (EV4)"),
              "L5": ("F0|F1,F2,F3", "target rank hangs; blocking F1..F3 abort hangs")}
PRED = OrderedDict([
    (("CPU", "initiator"), (R_CPU, {
        "L1_root": ("F0|F1|F2|F3,F4", "F0 | F1 | F2 | F3,F4 (a real SIGKILL gives 0x88 in 111/270)"),
        "L1_read": ("F0|F1|F2|F3,F4", "same (app polls)"),
        "L2": ("F0|F1|F2|F3|F4", "+liveness: F3 | F4"),
        "L3": (None, "(harness = app)"),
        "L4_async": (None, "no async events recorded"),
        "L5": (None, "not timed")})),
    (("GP", "initiator"), (R_GP, {
        "L1_root": ("F0|F1|F2,F4|F3", "F0 | F1 | F2,F4 | F3"),
        "L1_read": ("F0|F1|F2,F4|F3", "same"),
        "L2": ("F0|F1|F2,F4|F3", "same (WARN)"),
        "L3": ("F0|F1,F2,F3,F4", "F0 | F1..F4 (timeout, or hang when blocking)"),
        "L4_async": ("F0|F1,F2,F3,F4", "async error 2 classes"),
        "L4_log": ("F0|F1|F2,F4|F3", "log 4"),
        "L5": (None, "blocking F1..F3 hang (this campaign ran GP in timeout mode only)")})),
    (("GP", "target"), (R_GP + " (target rule)", {
        "L4_log": ("F0,F1,F3,F4|F2", "added rule: target L4-log splits F2 from the rest (EV3)")})),
    (("GG", "initiator"), (R_GG, {
        "L1_root": ("F0|F1|F2|F3,F4", "F0 | F1 | F2 | F3,F4"),
        "L1_read": ("F0|F1,F2,F3,F4", "F0 | F1..F4 (trailing 5/0xf9)"),
        "L2": ("F0|F1,F2,F3,F4", "F0 | F1..F4 (-EIO)"),
        "L3": ("F0,F1,F2,F3", "blocking: F0..F3 silent (F4 not stated)"),
        "L4_async": ("F0|F1,F2,F3,F4", "F0 | F1..F4 at the 10 s tick"),
        "L4_log": ("F0|F1,F2,F3,F4", "F0 | F1..F4 at the 10 s tick (one L4 cell)"),
        "L5": (None, "target rank hangs (see the target rule)")})),
    (("GG", "target"), (R_GG + " (target rule)", GIN_TARGET)),
    (("GQ", "initiator"), (R_GQ, {
        "L1_root": ("F0|F1|F2|F3,F4", "as stock"),
        "L1_read": ("F0|F1|F2|F3,F4", "root found (scan-back)"),
        "L2": ("F0|F1|F2|F3,F4", "F0 | F1 | F2 | F3,F4"),
        "L3": ("F0|F1,F2,F3,F4", "F0 | F1..F4"),
        "L4_async": ("F0|F1,F2,F3,F4", "API 2"),
        "L4_log": ("F0|F1|F2|F3,F4", "log/mailbox 4"),
        "L5": (None, "target rank hangs (see the target rule)")})),
    (("GQ", "target"), (R_GQ + " (target rule)", GIN_TARGET)),
    (("NC", "initiator"), (R_NC, NC_ROW)),
    (("NG", "initiator"), (R_NG, NG_ROW)),
    (("NX", "initiator"), (R_NG, NG_ROW)),
    (("ND-GPU", "initiator"), (R_NG, NG_ROW)),
    (("ND-CPU", "initiator"), (R_NC, NC_ROW)),
    (("NF", "initiator"), (R_NF, {
        "L1_root": ("F0|F1|F2|F3,F4", "as GPU"),
        "L1_read": ("F0|F1|F2|F3,F4", "root kept"),
        "L2": ("F0|F1|F2|F3,F4", "4 (+OOB with guard)"),
        "L3": ("F0|F1|F2|F3,F4", "4, fetch poisoned"),
        "L4_log": ("F0|F1|F2|F3,F4;F0|F1|F2|F3|F4", "4/5"),
        "L5": (None, "hangs without ft_abort (flap 6/6)")})),
    (("NET-stock", "initiator"), (R_NET, {L: NONET for L in CHAIN})),
    (("NET-S2", "initiator"), (R_NETS2, {L: NONET for L in CHAIN})),
])


def parse_part(s):
    return [[set(c.split(",")) for c in alt.split("|")] for alt in s.split(";")]


def compare(variant, side, L, pstr):
    """(verdict, predicted classes, observed classes, auto-reason)"""
    alts = parse_part(pstr)
    covered = set().union(*alts[0])
    fs = [f for f in faults_of(variant, side) if f in covered]
    if len(fs) < 2:
        return "비교 불가", None, None, "예측이 있는 장애 중 이번에 돌린 것이 %d개" % len(fs)
    cls, sp, un, labs = partition(variant, side, L, only=fs)
    if not cls and not sp:
        return "재지 않음", None, None, ""
    obs_f = [f for f in fs if f not in un]
    obs = [set(c) for c in cls] + [{f} for f in sp]
    best = None
    for alt in alts:
        pred = [c & set(obs_f) for c in alt]
        pred = [c for c in pred if c]
        same = sorted(map(sorted, pred)) == sorted(map(sorted, obs))
        if best is None or same:
            best = (pred, same)
        if same:
            break
    pred, same = best
    reason = []
    if not same:
        def cl_of(part, f):
            for i, c in enumerate(part):
                if f in c:
                    return i
        for i, a in enumerate(obs_f):
            for b in obs_f[i + 1:]:
                p, o = cl_of(pred, a) == cl_of(pred, b), cl_of(obs, a) == cl_of(obs, b)
                if p and not o:
                    reason.append(("merged_pred_split_obs", a, b))
                elif o and not p:
                    reason.append(("split_pred_merged_obs", a, b))
    note = []
    if un:
        note.append(("unobserved", un))
    if sp:
        note.append(("split", list(sp)))
    return ("같음" if same else "다름"), pred, obs, (reason, note)


# ======================================================================== report (Korean)
SHORT = {"F0": "없음", "F1": "로컬", "F2": "원격", "F3": "재시도", "F4": "kill",
         "X_rem_inv_req": "잘못된요청", "X_rnr": "RNR", "X_partial_write": "부분쓰기"}
LONG = {"F0": "장애 없음", "F1": "로컬 QP 오류", "F2": "원격 접근 오류", "F3": "재시도 초과",
        "F4": "상대 kill", "X_rem_inv_req": "원격 잘못된 요청", "X_rnr": "RNR 재시도 초과",
        "X_partial_write": "쓰기 도중 로컬 QP 오류"}
VNAME = OrderedDict([
    ("CPU", "CPU verbs 하네스"), ("GP", "GIN 프록시"), ("GG", "GIN GDAKI"), ("GQ", "GDAKI + 장치 분류기"),
    ("NC", "NVSHMEM 3.8.0 CPU 프록시"), ("NG", "NVSHMEM 3.8.0 GPU 처리"),
    ("NX", "NVSHMEM 3.8.0 CPU 프록시 + doorbell record 수정"), ("ND-GPU", "NVSHMEM devel GPU 처리"),
    ("ND-CPU", "NVSHMEM devel CPU 프록시"), ("NF", "NVSHMEM FT v2.2"), ("NET-stock", "net_ib 원본"),
    ("NET-S2", "net_ib 복구 2단계")])
LNAME = {"L0_qp": "NIC QP 상태", "L0_ctr": "NIC 카운터", "L1_root": "원인 CQE", "L1_read": "읽은 CQE",
         "L2": "CQ 소비자", "L3": "API", "L4_async": "호스트 비동기 오류", "L4_log": "호스트 로그", "L5": "정리"}


def lhead(L):
    """table header: plain name first, the layer code in parentheses."""
    return "%s (%s)" % (LNAME[L], L.split("_")[0])
REVIEW_KO = {R_CPU: "CPU verbs 하네스", R_GP: "GIN 프록시 원본", R_GG: "GIN GDAKI 원본",
             R_GQ: "GDAKI + 장치 분류기", R_NC: "NVSHMEM CPU 프록시 원본",
             R_NG: "NVSHMEM GPU 처리, 또는 CPU 프록시 + doorbell record 수정", R_NF: "NVSHMEM FT v2.2",
             R_NET: "net_ib 원본", R_NETS2: "net_ib + 복구 2단계"}
# why a comparison differs, and where an upper layer splits faults the layer below merged. These are
# this script's interpretation ([추론]); the script checks that every key still matches the data.
DIFF_NOTE = {
    ("ND-GPU", "initiator", "L1_read"):
        "리뷰 칸은 라이브러리가 읽는 자리(뒤따르는 flush 5/0xf9)다. 이번 시행은 timeout 모드라서 드라이버 자신의 "
        "제한 poll이 오류 opcode를 보자마자 멈추고 그 자리를 읽었다. 그래서 원인 CQE가 덮이기 전에 읽혔다 [추론]. "
        "라이브러리 경로(nvshmem_quiet)는 이 셀에서 돌지 않았다.",
}
CORE_NOTE = {
    ("CPU", "initiator", "L1_read", "L2"): ("예",
        "하네스가 제어용 TCP 연결로 상대 생존을 확인한다(csv sub_cause). 재시도 초과와 kill은 CQE가 같고(12/0x81) "
        "이 채널로만 갈린다."),
    ("GP", "initiator", "L4_async", "L4_log"): ("아니오, 우회",
        "로그는 CQ를 poll하는 프록시 스레드(CQ 소비자)가 직접 쓴다. API와 호스트 비동기 오류를 거치지 않으며 CQ 소비자와 "
        "같은 4칸이다."),
    ("GG", "initiator", "L3", "L4_async"): ("아니오, 우회",
        "API는 조용한 성공인데, 호스트가 10 s 주기 검사로 오류를 따로 낸다(리뷰 표 호스트 칸의 'at the 10 s tick'). "
        "정보는 API가 아니라 장치 쪽 오류 상태에서 온다 [추론]. 리뷰가 예측한 CQ 소비자 분할(없음 | 나머지)보다 잘지 않다."),
    ("GQ", "initiator", "L4_async", "L4_log"): ("예 (분류기)",
        "장치 분류기가 원인 CQE를 찾아 로그로 남긴다(CQ 소비자와 같은 4칸). 리뷰가 '손실만 막는 채널'로 분류한 것으로 "
        "원인 CQE의 4칸을 넘지 않는다."),
    ("NC", "initiator", "L4_log", "L5"): ("아니오",
        "로그는 비어 있지만 API(nvshmem_quiet 멈춤)와 같은 분할이다. 정리가 멈춘 것은 API가 이미 멈춘 뒤의 일이다 [추론]."),
    ("NG", "initiator", "L4_log", "L5"): ("아니오",
        "API에서 kill은 성공과 같았는데(0/5) 정리에서 5/5 멈춘다. finalize가 죽은 상대와 다시 통신해야 해서 "
        "상대가 없는 것이 정리 단계에서만 드러난다 [추론]. 우리가 더한 채널은 없다. CQE와 CQ 소비자는 이번에 재지 않았다."),
    ("NX", "initiator", "L4_log", "L5"): ("아니오",
        "GPU 처리 줄과 같다: API 0/5, 정리 5/5 멈춤. 더한 채널 없음, CQE와 CQ 소비자는 재지 않음."),
    ("NF", "initiator", "L3", "L4_log"): ("예",
        "재시도 초과와 kill은 CQE와 FT 분류가 같다(12/0x81, RETRY_EXC). 드라이버가 TCP 연결에서 본 상대 생존(FIN)이 "
        "kill을 복구 거절로 보내고, 그 결과 'marked failed' 줄이 생긴다."),
    ("GP", "target", "L4_async", "L4_log"): ("아니오, 우회",
        "상대 쪽 NIC가 자기 QP 오류를 verbs 비동기 이벤트로 호스트 로그에 바로 낸다. CQE 경로가 아니라 NIC에서 "
        "호스트로 가는 기존 경로이고, 상대 쪽 API와 호스트 비동기 오류에는 가지 않는다."),
    ("GG", "target", "L4_log", "L5"): ("아니오",
        "호스트 로그는 비어 있지만 API(대기 멈춤)와 같은 분할이다. 정리가 멈춘 것은 API 대기가 돌아오지 않은 결과다 [추론]."),
    ("GQ", "target", "L4_log", "L5"): ("아니오", "GIN GDAKI 상대 쪽과 같다."),
}
# upper layers whose layer below was not measured here: compared with the review's predicted partition
PRED_LOWER_NOTE = {
    ("GG", "L3", "L2"): ("예 (드라이버 TCP)",
        "kill만 API에서 ncclTimeout으로 갈린다. 드라이버가 매 회 TCP 동기화로 상대가 죽은 것을 먼저 알고"
        "('peer gone') 시간 제한이 있는 대기로 바꿨기 때문이다(gin_fault.cu의 drain). 라이브러리 경로가 아니다."),
}


def esc(s):
    return s.replace("|", "\\|")


def short_lab(s):
    return s.split(" (run with")[0]


def part_cell(variant, side, L, show_missing=True):
    cls, sp, un, labs = partition(variant, side, L)
    if not cls and not sp:
        return "-"
    parts = []
    for c in cls:
        names = []
        for f in c:
            kind, val, n = fclass(variant, side, f, L)
            k = sum(1 for r in (trials("NET-S2", side, "F0") if variant == "NET-stock" and f == "F0"
                                else trials(variant, side, f)) if r[L] != NO and norm(r[L]) == val)
            names.append(SHORT[f] + ("" if k == n else " (%d/%d)" % (k, n)))
        parts.append(", ".join(names))
    for f, cnt in sp.items():
        parts.append("%s[갈림: %s]" % (SHORT[f], ", ".join("%s %d" % (short_lab(l), k) for l, k in cnt.most_common())))
    s = esc(" | ".join(parts)) + " (%d)" % (len(cls) + len(sp))
    if un and show_missing:
        s += "; 관측 없음: " + ", ".join(SHORT[f] for f in un)
    return s


def pstr(classes):
    return esc(" | ".join(", ".join(SHORT[f] for f in FAULTS if f in c) for c in
                         sorted(classes, key=lambda c: min(FAULTS.index(f) for f in c))))


def arr_cell(variant, side, f, L):
    k, no, n, hasctl = arrival(variant, side, f, L)
    if no == 0:
        return "-"
    return "%d/%d%s" % (k, no, "" if hasctl else "*")


def arr_sum(variants, side, faults, L):
    k = n = 0
    for v in variants:
        for f in faults:
            if trials(v, side, f):
                a, b, _, _ = arrival(v, side, f, L)
                k, n = k + a, n + b
    return k, n


def count(pred, rows=None):
    return sum(1 for r in (ROWS if rows is None else rows) if pred(r))


def arrival_table(side, layers):
    out = ["| 변형 | 장애 | n | " + " | ".join(lhead(L) for L in layers) + " |",
           "|---|---|--:|" + "--:|" * len(layers)]
    for v in VARIANTS:
        rows, cur = [], None
        for f in ran(v, side):
            if f == "F0":
                continue
            cells = [arr_cell(v, side, f, L) for L in layers]
            if all(c == "-" for c in cells[1:]) and side == "target":
                continue     # target killed: only the port counters remain
            n = len(trials(v, side, f))
            if cur and cur[1] == cells and cur[2] == n:
                cur[0].append(f)
            else:
                cur = [[f], cells, n]
                rows.append(cur)
        for fs, cells, n in rows:
            out.append("| %s | %s | %d | %s |" % (VNAME[v], ", ".join(LONG[f] for f in fs), n, " | ".join(cells)))
    return out


def missing_faults(v, side):
    run = set(faults_of(v, side))
    return ", ".join(SHORT[f] for f in CORE if f not in run) or "-"


def write_csv(root, out=None):
    path = os.path.join(out or root, "layers_trials.csv")
    cols = ["stack", "variant", "tag", "fault", "fault_raw", "wait_mode", "side"]
    for L in LAYERS:
        cols += [L, L + "_ev"]
    cols += ["channel", "channel_ev", "source"]
    order = {v: i for i, v in enumerate(VARIANTS)}
    rows = sorted(ROWS, key=lambda r: (order[r["variant"]], FAULTS.index(r["fault"]), r["tag"], r["side"]))
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([scrub(r[c], 400) if c.endswith("_ev") or c == "source" else r[c] for c in cols])
    return path


def write_md(root, rerun, out=None):
    L_ALL = ["L0_ctr", "L0_qp", "L1_root", "L1_read", "L2", "L3", "L4_async", "L4_log", "L5"]
    n_trials = len(ROWS) // 2
    per_stack = Counter(r["stack"] for r in ROWS if r["side"] == "initiator")
    rerun_n = count(lambda r: r["side"] == "initiator" and r["stack"] in ("gp", "gg") and r["fault"] == "F4")
    md = []
    A = md.append
    A("# 계층별 오류 전파와 원인 구분")
    A("")
    A("2026-10-06 전파 캠페인의 핵심 결과표다. `campaign/layers.py`가 원자료에서 다시 세어 만들었다. "
      "시행 하나하나의 값과 근거 문자열은 [layers_trials.csv](layers_trials.csv)에 있다(시행 %d회마다 요청 쪽과 "
      "상대 쪽 한 줄씩, %d줄)." % (n_trials, len(ROWS)))
    A("")
    A("- 자료: `results/20261006_campaign/` 8개 스택(%s). GIN 프록시와 GIN GDAKI의 상대 kill %d회는 "
      "`results/20261006_f4rerun/`의 재실행으로 바꿨다(DEVIATIONS 10). smoke 실행은 읽지 않는다."
      % (", ".join("%s %d" % (s, per_stack[s]) for s in ("cpu", "gp", "gg", "gq", "nvo", "nvd", "nvf", "net")), rerun_n))
    A("- 다시 만드는 명령: `python3 campaign/layers.py results/20261006_campaign --f4-rerun results/20261006_f4rerun`")
    A("- 표의 수는 모두 `[측정]`이다. 해석은 `[추론]`, 확인하지 못한 것은 `[미확인]`으로 적는다.")
    A("")
    # ------------------------------------------------------------ 1
    A("## 1. 읽는 법")
    A("")
    A("장애 정보가 아래에서 위로 여섯 계층을 지나는 동안 얼마나 남는지 본다. 계층은 NIC(L0: QP 상태, 포트 오류 "
      "카운터), CQE(L1: NIC가 쓴 원인 CQE와 소비자가 실제로 읽은 CQE), CQ 소비자(L2: CQ를 poll하는 프록시 스레드나 "
      "장치 코드, 분류기가 얻은 결과), API(L3: 앱이 받은 값), 호스트(L4: 비동기 오류 값과 라이브러리 로그), "
      "정리(L5: abort나 finalize가 돌아오는지 멈추는지)다. L0~L5는 표 머리의 괄호와 CSV 열 이름에만 쓴다. "
      "척도는 둘이다.")
    A("")
    A("- **전파율:** 그 계층이 같은 변형의 장애 없음 대조군과 다른 값을 보인 시행 수 k/n. 대조군에 그 계층 값이 "
      "없으면(`*`) \"오류 없음\"(none, ok, returned, +0, RTS)과 비교한다. 조용한 성공은 성공과 같은 값으로 친다.")
    A("- **분할:** 그 계층에서 서로 구분되는 장애 묶음. 장애의 칸은 그 장애 시행의 90% 이상이 보인 값이다. "
      "칸 수가 클수록 원인을 더 잘 가른다. 90%에 못 미치면 \"갈림\"으로 따로 적는다.")
    A("- **장애 약칭:** 없음(장애 없음, F0), 로컬(로컬 QP 오류, F1), 원격(원격 접근 오류: MR 밖 쓰기나 잘못된 rkey, "
      "F2), 재시도(상대 QP를 오류 상태로 바꿔 재시도 초과, F3), kill(상대 프로세스 kill, F4). CPU 하네스만: "
      "잘못된요청(원격 잘못된 요청), RNR(RNR 재시도 초과), 부분쓰기(쓰기 도중 로컬 QP 오류). 괄호 안 기호는 원자료와 "
      "CSV의 `fault` 열에서 찾는 열쇠다.")
    A("- **값:** `10/0x88`은 status 10과 vendor_err 0x88 조합이다. `-`는 원자료에 그 계층 값이 없다는 뜻이다(추측해 "
      "채우지 않음).")
    A("- **변형과 원자료 폴더:** CPU verbs 하네스(cpu), GIN 프록시(gp, timeout 대기), GIN GDAKI(gg, 장애는 blocking 대기, "
      "대조군은 timeout), GDAKI + 장치 분류기(gq), NVSHMEM 3.8.0의 CPU 프록시, GPU 처리, CPU 프록시 + doorbell record 수정"
      "(nvo, 장애는 상대 kill만), NVSHMEM devel + 주입 훅의 GPU 처리, CPU 프록시(nvd, 대조군 없음), NVSHMEM FT v2.2(nvf, "
      "복구 켬), net_ib 원본과 복구 2단계(net, 대조군은 복구 켠 무장애 실행 하나를 함께 씀, DEVIATIONS 5).")
    A("- **쪽:** 요청 쪽은 rank 0(rain), 상대 쪽은 rank 1(sunny)이다. GIN에서 상대 쪽은 단방향 쓰기를 받기만 한다.")
    A("")
    # ------------------------------------------------------------ 2
    A("## 2. 전파율")
    A("")
    A("### 요청 쪽")
    A("")
    md.extend(arrival_table("initiator", L_ALL))
    A("")
    verbs_f = ["F1", "F2", "F3", "F4", "X_rem_inv_req", "X_rnr", "X_partial_write"]
    k1, n1 = arr_sum(["CPU", "GP", "NET-stock", "NET-S2"], "initiator", verbs_f, "L0_ctr")
    k2, n2 = arr_sum(["GG", "GQ", "NC", "NG", "NX", "ND-GPU", "ND-CPU", "NF"], "initiator", verbs_f, "L0_ctr")
    k3, n3 = arr_sum(["GG"], "initiator", ["F1", "F2", "F3"], "L3")
    k4, n4 = arr_sum(["GG"], "initiator", ["F1", "F2", "F3"], "L4_async")
    k5, n5 = arr_sum(["NG", "NX"], "initiator", ["F4"], "L3")
    k6, n6 = arr_sum(["NG", "NX"], "initiator", ["F4"], "L5")
    k7, n7 = arr_sum(["ND-CPU"], "initiator", ["F1", "F2", "F3"], "L1_root")
    k8, n8 = arr_sum(["ND-GPU"], "initiator", ["F1", "F2", "F3"], "L1_root")
    k9, n9 = arr_sum(["GP", "GG", "GQ"], "initiator", ["F1", "F2", "F3", "F4"], "L5")
    gq_pol = count(lambda r: r["variant"] == "GQ" and r["side"] == "initiator" and r["fault"] != "F0"
                   and "polled slot syn=0x5 ve=0xf9" in r["L1_read_ev"])
    gq_n = count(lambda r: r["variant"] == "GQ" and r["side"] == "initiator" and r["fault"] != "F0")
    gg_f4_to = count(lambda r: r["variant"] == "GG" and r["side"] == "initiator" and r["fault"] == "F4"
                     and r["L3"] == "ncclTimeout")
    gg_f4_pg = count(lambda r: r["variant"] == "GG" and r["side"] == "initiator" and r["fault"] == "F4"
                     and r["L3"] == "ncclTimeout" and r["channel"].startswith("peer gone"))
    gg_f4_n = len(trials("GG", "initiator", "F4"))
    # port-level async events recorded by evrec, over the trials used here (both nodes)
    evrec_events = n_evrec = 0
    for r in ROWS:
        if r["side"] != "initiator":
            continue
        base = rerun if (r["stack"] in ("gp", "gg") and r["fault"] == "F4") else root
        for node in ("rain", "sunny"):
            m = re.search(r"^end .*events=(\d+)", text(os.path.join(base, r["stack"], "evrec",
                                                                   r["tag"] + ".evrec." + node)), re.M)
            if m:
                n_evrec += 1
                evrec_events += int(m.group(1))
    k10, n10 = arr_sum(["NET-stock", "NET-S2"], "initiator", ["F2"], "L5")
    nc_l3 = arr_sum(["NC"], "initiator", ["F4"], "L3")
    # claims written in words below are checked against the data here
    assert k3 == 0 and k5 == 0 and k9 == 0 and k7 == 0 and k8 == n8 and k10 == n10 and nc_l3[0] == nc_l3[1]
    assert all(norm(r["L3"]) == "ok" for v in ("NG", "NX") for r in trials(v, "initiator", "F4"))
    A("- `[측정]` verbs로 QP를 만드는 경로(CPU 하네스, GIN 프록시, net_ib)는 장애 시행 %d/%d에서 포트 오류 카운터가 "
      "올랐다. DEVX로 QP를 만드는 스택(GIN GDAKI, 분류기, NVSHMEM 전부)은 %d/%d에서 올랐다. `[추론]` 포트 카운터가 "
      "DEVX QP를 세지 않기 때문이며(evrec/NOTES.md) 오류가 없었다는 뜻이 아니다." % (k1, n1, k2, n2))
    A("- `[측정]` GIN GDAKI blocking 대기에서 로컬, 원격, 재시도 장애는 API가 %d/%d에서 대조군과 달랐다(모두 "
      "성공으로 돌아옴). 같은 시행의 호스트 비동기 오류는 %d/%d에서 달랐다. kill은 API가 %d/%d에서 ncclTimeout이고, 그중 "
      "%d회는 드라이버가 TCP 동기화로 상대가 죽은 것을 먼저 알고 시간 제한 대기로 바꾼 시행이다(5절)."
      % (k3, n3, k4, n4, gg_f4_to, gg_f4_n, gg_f4_pg))
    A("- `[측정]` NVSHMEM 3.8.0 GPU 처리와 doorbell record 수정본은 kill에서 API가 %d/%d(모두 성공으로 돌아옴), "
      "정리는 %d/%d에서 멈췄다. CPU 프록시 원본은 API(nvshmem_quiet)에서 이미 %d/%d 멈춘다."
      % (k5, n5, k6, n6, nc_l3[0], nc_l3[1]))
    A("- `[측정]` NVSHMEM devel에서 오류 CQE는 GPU 처리 %d/%d, CPU 프록시 %d/%d에서 보였다. CPU 프록시에서는 CQ 전체를 "
      "훑어도 오류 CQE가 없고, 드라이버의 제한 poll이 시간 초과로 끝난다." % (k8, n8, k7, n7))
    A("- `[측정]` 분류기 빌드에서 poll 위치의 CQE는 %d/%d에서 뒤따르는 flush(5/0xf9)였다. 분류기는 거기서 거슬러 "
      "올라가 원인 CQE를 찾는다. `[미확인]` 원본 GDAKI 자체는 CQE를 남기지 않아 이번에 직접 보지 못했다." % (gq_pol, gq_n))
    A("- `[측정]` GIN 세 변형의 요청 쪽 정리는 장애 시행 %d/%d에서 대조군과 달랐다(모두 돌아옴). net_ib는 원격 "
      "접근 오류 %d/%d에서 abort가 멈췄다. 포트 수준 비동기 이벤트는 evrec 파일 %d개에서 %d건이다."
      % (k9, n9, k10, n10, n_evrec, evrec_events))
    A("")
    A("### 상대 쪽")
    A("")
    md.extend(arrival_table("target", L_ALL))
    A("")
    kt = count(lambda r: r["side"] == "target" and r["fault"] == "F4" and r["L0_ctr"] == "+0")
    nt = count(lambda r: r["side"] == "target" and r["fault"] == "F4")
    a1 = arr_sum(["GP"], "target", ["F1", "F2", "F3"], "L3")
    a2 = arr_sum(["GP"], "target", ["F1", "F2", "F3"], "L4_async")
    a3 = arr_sum(["GP"], "target", ["F2"], "L4_log")
    a4 = arr_sum(["GP"], "target", ["F1", "F3"], "L4_log")
    a5 = arr_sum(["GG", "GQ"], "target", ["F1", "F2", "F3"], "L3")
    a6 = arr_sum(["GG", "GQ"], "target", ["F1", "F2", "F3"], "L5")
    a7 = arr_sum(["GG", "GQ"], "target", ["F1", "F2", "F3"], "L4_async")
    s2t = Counter(norm(r["L3"]) for r in trials("NET-S2", "target", "F2"))
    net_t = arr_sum(["NET-stock", "NET-S2"], "target", ["F2"], "L3")
    net_r1 = count(lambda r: r["L1_read"] == "5/0xf9", trials("NET-stock", "target", "F2") + trials("NET-S2", "target", "F2"))
    gp_t = set(norm(r["L3"]) for f in ("F1", "F2", "F3") for r in trials("GP", "target", f))
    assert gp_t == {"ncclTimeout"} and kt == nt
    assert [sorted(c) for c in partition("CPU", "target", "L0_qp")[0]] == [
        ["F0", "F1", "X_partial_write", "X_rnr"], ["F2", "F3", "X_rem_inv_req"]]
    nf_t = {f: Counter(norm(r["L3"]) for r in trials("NF", "target", f)) for f in ("F1", "F2", "F3")}
    nf_ch = Counter(r["channel"] for f in ("F1", "F2", "F3") for r in trials("NF", "target", f))
    A("- 상대 kill 시행(%d회)은 상대 프로세스가 죽어 포트 카운터만 남는다(%d/%d에서 +0). 표에서 뺐다." % (nt, kt, nt))
    A("- `[측정]` 단방향 GIN 프록시의 상대 쪽 API는 원인을 모른다. 로컬, 원격, 재시도에서 API는 %d/%d에서 대조군과 "
      "다르지만 모두 같은 ncclTimeout(신호가 오지 않음)이고, 비동기 오류는 %d/%d에서 달랐다. 원격 접근 오류에서만 상대 "
      "쪽 로그에 QP의 `async fatal event`가 남는다(%d/%d, 다른 장애 %d/%d)." % (a1 + a2 + a3 + a4))
    A("- `[측정]` GDAKI 두 변형의 상대 쪽은 blocking 장애에서 대기가 %d/%d, 정리가 %d/%d 멈췄다. 비동기 오류는 %d/%d에서 "
      "달랐다." % (a5 + a6 + a7))
    A("- `[측정]` 양방향 net_ib는 상대 쪽 API까지 오류가 간다(%d/%d). 상대 쪽 첫 CQE는 %d/%d에서 자기 Recv의 flush"
      "(5/0xf9)였다. 복구 2단계의 상대 쪽 API 값은 %d회 중 %s로 갈렸다."
      % (net_t + (net_r1, len(trials("NET-stock", "target", "F2")) + len(trials("NET-S2", "target", "F2")),
                  sum(s2t.values()), ", ".join("%s %d회" % (short_lab(k), v) for k, v in s2t.most_common()))))
    A("- `[측정]` CPU 하네스 응답 쪽 QP는 원격 접근 오류, 잘못된 요청, 재시도 초과에서 ERR이다(재시도 초과는 주입 자체가 "
      "응답 쪽 QP를 ERR로 바꾼다). 비동기 이벤트는 앞의 두 장애에서만 왔다(각 10/10).")
    A("- `[측정]` NVSHMEM FT의 상대 쪽 API는 원격 접근 오류에서 %s, 로컬과 재시도에서 %s, %s였다. 결과는 요청 쪽이 "
      "드라이버 TCP로 보낸 메시지(거절 %d회, 복구 요청 %d회)와 함께 왔다."
      % ("rc=9(복구 거절) %d/5" % nf_t["F2"]["rc=9"], "성공 %d/5" % nf_t["F1"]["ok"], "%d/5" % nf_t["F3"]["ok"],
         nf_ch["peer message: FAIL"], nf_ch["peer message: recovery"]))
    A("")
    # ------------------------------------------------------------ 3
    A("## 3. 분할")
    A("")
    A("### 요청 쪽")
    A("")
    lay = ["L0_ctr", "L0_qp", "L1_root", "L1_read", "L2", "L3", "L4_async", "L4_log", "L5"]
    A("| 변형 | 돌리지 않은 장애 | " + " | ".join(lhead(L) for L in lay) + " |")
    A("|---|---|" + "---|" * len(lay))
    for v in VARIANTS:
        A("| %s | %s | %s |" % (VNAME[v], missing_faults(v, "initiator"),
                               " | ".join(part_cell(v, "initiator", L) for L in lay)))
    A("")
    A("### 상대 쪽")
    A("")
    lay_t = ["L0_ctr", "L0_qp", "L1_read", "L2", "L3", "L4_async", "L4_log", "L5"]
    A("| 변형 | " + " | ".join(lhead(L) for L in lay_t) + " |")
    A("|---|" + "---|" * len(lay_t))
    for v in VARIANTS:
        if v in ("NC", "NG", "NX"):
            continue
        A("| %s | %s |" % (VNAME[v], " | ".join(part_cell(v, "target", L, show_missing=False) for L in lay_t)))
    A("")
    A("상대 kill에서 상대 쪽은 관측 없음이라 상대 쪽 칸에서 빠진다. NVSHMEM 3.8.0 세 변형의 상대 쪽은 장애 없음만 "
      "관측돼 표에서 뺐다.")
    A("")
    # ------------------------------------------------------------ 4
    A("## 4. 사전 등록 분할과 비교")
    A("")
    A("예측은 `REVIEW_20261006.md`의 \"Partition of {F0..F4} per layer, initiator side\" 표와 `PREDICTIONS.md`의 "
      "상대 쪽 규칙 두 개다. 리뷰 칸을 분할로 읽은 방식은 `layers.py`의 `PRED`에 원문과 함께 있다 `[추론]`. 이번에 돌린 "
      "장애로 좁혀 비교한다.")
    A("")
    A("| 변형 | 계층 | 예측 | 관측 | 판정 | 이유 |")
    A("|---|---|---|---|---|---|")
    not_measured, no_pred, used_diff = [], [], set()
    entries = []
    for (v, side), (row, d) in PRED.items():
        for L in CHAIN:
            if L not in d:
                continue
            p, txt = d[L]
            who = VNAME[v] + (" 상대 쪽" if side == "target" else "")
            if p is None:
                no_pred.append((who, L, txt))
                continue
            verdict, pred, obs, extra = compare(v, side, L, p)
            if verdict == "재지 않음":
                not_measured.append((who, L))
                continue
            if verdict == "비교 불가":
                no_pred.append((who, L, extra))
                continue
            reason, note = extra
            why = []
            if verdict == "다름":
                key = (v, side, L)
                used_diff.add(key)
                pairs = ", ".join("%s/%s" % (SHORT[a], SHORT[b]) for kind, a, b in reason if kind == "merged_pred_split_obs")
                pairs2 = ", ".join("%s/%s" % (SHORT[a], SHORT[b]) for kind, a, b in reason if kind == "split_pred_merged_obs")
                if pairs:
                    why.append("예측은 한 칸, 관측은 갈림: " + pairs)
                if pairs2:
                    why.append("예측은 갈림, 관측은 한 칸: " + pairs2)
                why.append(DIFF_NOTE.get(key, "`[미확인]` 원인 해석 없음"))
            for kind, fs in note:
                if kind == "unobserved":
                    why.append("관측 없음: " + ", ".join(SHORT[f] for f in fs))
                if kind == "split":
                    why.append("갈림: " + ", ".join(SHORT[f] for f in fs))
            if v == "GG" and side == "initiator" and L == "L3":
                why.append("리뷰 칸에 kill이 없다. 관측된 kill은 따로 한 칸(ncclTimeout, 5절)")
            if v == "NF" and L == "L4_log":
                why.append("리뷰 칸이 '4/5'라 5칸을 맞음으로 본다")
            entries.append((who, LNAME[L], pstr(pred), pstr(obs), verdict, "; ".join(why)))

    def merge(items, key_idx, val_idx):
        out = OrderedDict()
        for it in items:
            out.setdefault(tuple(x for i, x in enumerate(it) if i != val_idx), []).append(it[val_idx])
        return [tuple(list(k[:val_idx]) + [", ".join(OrderedDict.fromkeys(v))] + list(k[val_idx:])) for k, v in out.items()]
    rows_cmp = merge(merge(entries, None, 1), None, 0)    # merge layers of one variant, then variants
    for who, ls, ps, os_, verdict, why in rows_cmp:
        A("| %s | %s | %s | %s | %s | %s |" % (who, ls, ps, os_, "**%s**" % verdict if verdict == "다름" else verdict,
                                              esc(why) or "-"))
    A("")
    nm = merge([(w, LNAME[L]) for w, L in not_measured], None, 1)
    nm = merge(nm, None, 0)
    A("- **이번 캠페인에서 재지 않음 (계층):** " + "; ".join("%s의 %s" % (w, ls) for w, ls in nm) + ".")
    np_ = merge(merge([(w, LNAME[L], NOPRED_KO.get(t, t)) for w, L, t in no_pred], None, 1), None, 0)
    A("- **리뷰 칸이 분할이 아니어서 비교하지 않음:** " + "; ".join("%s의 %s(%s)" % (w, ls, t) for w, ls, t in np_) + ".")
    A("- **이번 캠페인에서 재지 않음 (리뷰 표 줄):** GDAKI + 장치 분류기 + 복구, GIN 투명 복구 1, 2단계, NVSHMEM FT v1.")
    A("- `[추론]` 리뷰 표 줄 대응: NVSHMEM 3.8.0 GPU 처리와 doorbell record 수정본, devel GPU 처리는 리뷰 표의 "
      "\"NVSHMEM GPU 처리, 또는 CPU 프록시 + doorbell record 수정\" 줄(원문 \"NVSHMEM GPU handler, or CPU + DBR fix\")에, "
      "3.8.0 CPU 프록시와 devel CPU 프록시는 \"NVSHMEM CPU 프록시 원본\" 줄(원문 \"NVSHMEM CPU proxy, stock\")에 "
      "맞췄다. 상대 쪽 줄은 `PREDICTIONS.md`의 상대 쪽 규칙이다. 나머지는 이름이 같은 줄이다.")
    A("")
    # ------------------------------------------------------------ 5
    A("## 5. 핵심 주장 점검: 위 계층이 아래 계층보다 잘게 나뉜 곳")
    A("")
    A("핵심 주장은 \"채널을 더하지 않으면 어떤 계층도 아래 계층보다 잘게 나뉘지 않는다\"이다. 리뷰 표처럼 원인 CQE부터 위로, "
      "각 계층을 바로 아래의 재어진 계층과 비교해 아래에서 한 칸이던 두 장애가 위에서 갈린 경우를 모두 적는다. "
      "NIC 포트 카운터는 CQE 경로의 입력이 아니라 NIC가 따로 내는 통계여서 사슬에서 뺐다 `[추론]`.")
    A("")
    A("| 변형 | 쪽 | 아래 → 위 | 새로 갈린 장애 쌍 | 채널을 더했나 | 정보가 어디서 왔나 |")
    A("|---|---|---|---|---|---|")
    used_core = set()
    for side in ("initiator", "target"):
        for v, s, lo, up, pairs in core_splits(side):
            key = (v, s, lo, up)
            used_core.add(key)
            added, why = CORE_NOTE.get(key, ("`[미확인]`", "해석 없음"))
            A("| %s | %s | %s → %s | %s | %s | %s |" % (VNAME[v], "요청" if s == "initiator" else "상대", LNAME[lo],
                                                    LNAME[up], ", ".join("%s/%s" % (SHORT[a], SHORT[b]) for a, b in pairs),
                                                    added, esc(why)))
    # upper layer vs the review's predicted partition of an unmeasured lower layer
    for (v, up, lo), (added, why) in PRED_LOWER_NOTE.items():
        p = PRED[(v, "initiator")][1][lo][0]
        pred = parse_part(p)[0]
        cu = {f: fclass(v, "initiator", f, up) for f in faults_of(v, "initiator")}
        pairs = []
        fs = [f for f in faults_of(v, "initiator") if cu[f][0] == "ok"]
        for i, a in enumerate(fs):
            for b in fs[i + 1:]:
                same_lo = any(a in c and b in c for c in pred)
                if same_lo and cu[a][1] != cu[b][1]:
                    pairs.append((a, b))
        A("| %s | 요청 | %s(리뷰 예측, 이번에 재지 않음) → %s | %s | %s | %s |" % (
            VNAME[v], LNAME[lo], LNAME[up], ", ".join("%s/%s" % (SHORT[a], SHORT[b]) for a, b in pairs) or "없음",
            added, esc(why)))
    A("")
    A("- `[측정]` 요청 쪽에서 인접 계층 기준으로 위가 더 잘게 나뉜 곳은 %d곳, 상대 쪽은 %d곳이다."
      % (len(core_splits("initiator")), len(core_splits("target"))))
    A("- `[추론]` 채널을 더한 곳은 넷이다: CPU 하네스의 생존 확인, 장치 분류기의 원인 CQE 읽기, NVSHMEM FT의 TCP 생존 "
      "확인, GIN GDAKI 드라이버의 TCP 동기화. 우회인 곳은 정보가 바로 아래 계층이 아니라 더 아래 계층에서 곧장 온다. "
      "요청 쪽 우회 두 곳(GIN 프록시 로그, GDAKI 비동기 오류)은 그 원천(CQ 소비자, 또는 리뷰가 예측한 CQ 소비자 분할)보다 잘게 나뉘지 "
      "않는다. 상대 쪽 비동기 이벤트의 원천인 상대 쪽 QP 상태는 GIN에서 재지 않았다 `[미확인]`.")
    A("- `[추론]` 설명이 덜 된 곳은 NVSHMEM 3.8.0 GPU 처리와 doorbell record 수정본의 정리 단계다. API와 호스트 계층은 한 칸인데 "
      "정리만 kill을 가른다. 우리가 더한 채널은 없고, 정리 단계가 죽은 상대와 통신하며 생기는 것으로 보인다. 리뷰 표의 "
      "같은 줄도 이 모양(API 한 칸, 정리 두 칸)이었고, 리뷰가 예측한 CQ 소비자 분할(없음 | 나머지)보다 잘지는 않다. 다만 이번에 CQE와 CQ 소비자를 "
      "재지 않아 정리가 어디서 정보를 얻는지는 `[미확인]`이다. 정리 단계 자체의 통신을 채널로 보느냐에 따라 핵심 주장에 "
      "어긋나는 사례가 될 수 있다.")
    A("")
    # ------------------------------------------------------------ 6
    A("## 6. 관측하지 못한 것과 따로 적을 시행")
    A("")
    n_s2 = trials("NET-S2", "initiator", "F2")
    s2_r1 = count(lambda r: r["L1_read"] == "5/0xf9", trials("NET-S2", "target", "F2"))
    A("- `[미확인]` 원본 GIN GDAKI와 NVSHMEM 3.8.0의 CQE와 CQ 소비자: 이 빌드들은 CQE와 장치 결과를 남기지 않는다. GIN "
      "상대 쪽의 CQE와 CQ 소비자도 기록이 없다(단방향 쓰기라 상대는 완료를 poll하지 않음).")
    A("- `[미확인]` NVSHMEM devel의 API: timeout 모드라 드라이버의 제한 poll이 nvshmem_quiet을 대신했다. devel에는 장애 없음 "
      "대조군이 없어 정리 멈춤(10/10)이 장애 때문인지 가를 수 없다.")
    A("- `[미확인]` CPU 하네스: 요청 쪽 QP 상태, 응답 쪽 정리, 라이브러리 로그는 기록되지 않았다. 하네스가 곧 앱이라 API "
      "계층이 따로 없다. kill에서는 응답 쪽이 죽어 그 쪽 이벤트를 볼 수 없다(DEVIATIONS 4).")
    A("- `[미확인]` NVSHMEM에는 비동기 오류 API가 없어 호스트 비동기 오류 칸이 비어 있다. net_ib의 호스트 비동기 오류는 "
      "API와 같은 호출(ncclCommGetAsyncError)이라 같은 값이다.")
    t1 = [r for r in n_s2 if r["L1_root"] == NO]
    t1r = [r for r in trials("NET-S2", "target", "F2") if t1 and r["tag"] == t1[0]["tag"]]
    vrd = ""
    if t1:
        vr = list(csv.DictReader(open(os.path.join(root, "net", "runs", t1[0]["tag"][len("net_"):], "results.csv"))))
        vrd = vr[0]["verdict"] if vr else ""
    assert len(t1) == 1 and len(t1r) == 1 and t1r[0]["L1_root"] == "5/0xf9" and t1[0]["L1_read"] == "none" \
        and t1[0]["L2"] == "fail: peer failed or declined" and vrd.startswith("CLEAN_FAIL")
    A("- `[측정]` 복구 2단계 원격 접근 오류 중 `%s`에서는 받는 쪽(상대 쪽)이 flush(5/0xf9)를 먼저 기록했고, 보내는 "
      "쪽(요청 쪽)은 자기 오류 CQE가 없었다. 보내는 쪽 send comm은 \"peer failed or declined\"로 실패했고 결과는 %s이다"
      "(DEVIATIONS 12). 그래서 요청 쪽 원인 CQE는 이 시행을 관측 없음으로 빼고 %d/%d, 읽은 CQE는 %d/%d로 센다. 받는 쪽 "
      "첫 CQE는 %d/%d 시행에서 모두 이 flush다."
      % ((t1[0]["tag"], vrd) + arr_sum(["NET-S2"], "initiator", ["F2"], "L1_root")
         + arr_sum(["NET-S2"], "initiator", ["F2"], "L1_read") + (s2_r1, len(trials("NET-S2", "target", "F2")))))
    A("")
    missing = [k for k in DIFF_NOTE if k not in used_diff]
    missing += [k for k in CORE_NOTE if k not in used_core]
    if missing:
        raise SystemExit("annotation keys no longer match the data: %s" % missing)
    text_out = "\n".join(md) + "\n"
    if IPV4.search(text_out):
        raise SystemExit("an IPv4 address would be written to LAYERS.md")
    if "·" in text_out or "fingerprint" in text_out.lower():
        raise SystemExit("forbidden character or term in LAYERS.md")
    # layer codes are keys: allowed only in the definition sentence and as "(Ln)" in table headers
    for line in md:
        if line.startswith("장애 정보가 아래에서"):
            continue
        rest = re.sub(r" \(L[0-5]\)", "", line) if line.startswith("| 변형") else line
        if re.search(r"\bL[0-5]\b|S1/S2|\bQ4\b|\bEV\d", rest):
            raise SystemExit("a stage or layer code is used in the text: " + line[:80])
    path = os.path.join(out or root, "LAYERS.md")
    with open(path, "w") as f:
        f.write(text_out)
    return path


# ======================================================================== main
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    root = os.path.abspath(sys.argv[1])
    rerun = os.path.abspath(sys.argv[sys.argv.index("--f4-rerun") + 1]) if "--f4-rerun" in sys.argv else None
    if rerun is None:
        print("--f4-rerun is required (DEVIATIONS 10: the campaign GP and GG F4 trials are invalid)", file=sys.stderr)
        sys.exit(2)
    cpu(root)
    for s in ("gp", "gg", "gq"):
        gin(root, rerun, s)
    nvo(root)
    nvd(root)
    nvf(root)
    net(root)
    c = write_csv(root)
    m = write_md(root, rerun)
    print("wrote %s (%d rows) and %s" % (c, len(ROWS), m))
    for v in VARIANTS:
        print("%-10s %s" % (v, " ".join("%s=%d" % (L, len(partition(v, "initiator", L)[0]) + len(partition(v, "initiator", L)[1]))
                                       for L in CHAIN)))
    if "--debug" in sys.argv:
        c = Counter()
        for r in ROWS:
            for L in LAYERS + ["channel"]:
                c[(r["variant"], r["side"], r["fault"], L, r[L])] += 1
        for k in sorted(c):
            print(c[k], *k, sep=" | ")
        print(len(ROWS), "rows")


if __name__ == "__main__":
    main()
