#!/usr/bin/env python3
"""abc_table.py - the 3-way NVSHMEM comparison (A GPU handler, B CPU proxy stock, C CPU proxy +
NVSHMEM_IBGDA_PROXY_SQ_DBR=1). Reads <root>/{A,B,C}/nvshmem.txt and the per-trial logs, writes
<root>/abc_trials.csv and prints a per-cell markdown table.

usage: abc_table.py <root>      e.g. results/20260924_abc
"""
import csv
import os
import re
import statistics
import sys

KV = re.compile(r'(\w+)=("([^"]*)"|\S*)')


def kv(line):
    return {m.group(1): (m.group(3) if m.group(3) is not None else m.group(2)) for m in KV.finditer(line)}


def per_trial(d, tag):
    """extra fields from the logs"""
    out = {}
    p0 = os.path.join(d, tag + ".pe0.log")
    p1 = os.path.join(d, tag + ".pe1.log")
    it0 = [kv(l) for l in open(p0, errors="replace") if l.startswith("ITER ") and " rank 0 " in l] if os.path.exists(p0) else []
    it1 = [kv(l) for l in open(p1, errors="replace") if l.startswith("ITER ") and " rank 1 " in l] if os.path.exists(p1) else []
    out["pe0_iters_logged"] = len(it0)
    out["pe0_dt_ms_per_iter"] = " ".join(x.get("dt_ms", "") for x in it0)
    out["pe1_iters_ok"] = sum(1 for x in it1 if x.get("data_check") == "ok")
    out["pe1_iters_logged"] = len(it1)
    handler = ""
    if os.path.exists(p0):
        for l in open(p0, errors="replace"):
            if "NIC handler will be" in l:
                handler = l.split("NIC handler will be", 1)[1].strip().rstrip(".")
                break

    out["handler_log"] = handler
    qp = [l for l in open(p0, errors="replace") if "fault-watch" in l and " RC " in l and "QUERY_QP" in l] if os.path.exists(p0) else []
    out["qp_final"] = re.sub(r".*(state=\d+ hw_sq_wqebb=\d+ sw_sq_wqebb=\d+).*", r"\1", qp[-1].strip()) if qp else ""
    return out


def main():
    root = sys.argv[1]
    rows = []
    for cfg in ("A", "B", "C"):
        d = os.path.join(root, cfg)
        f = os.path.join(d, "nvshmem.txt")
        if not os.path.exists(f):
            continue
        for line in open(f):
            if not line.startswith("trial="):
                continue
            r = kv(line.replace(";t_last_xmit_change_ms=", " t_last_xmit_change_ms="))
            r["config"] = cfg
            parts = r["trial"].split("_")
            r["fault"], r["wait"] = parts[0], parts[1]
            r.update(per_trial(d, r["trial"]))
            rows.append(r)
    cols = ["config", "trial", "fault", "wait", "handler_req", "handler_log", "fix", "ok_iters", "fail_iter", "wait_rc",
            "dt_ms", "cqe_opcode", "cqe_syndrome", "cqe_vendor_err", "cqe_wqe", "ready_head", "scan_errs", "errcqe",
            "watch_first_rc_err_ms", "qp_final", "dbr_final", "pe0_dt_ms_per_iter", "pe1_iters_ok", "xmit_total",
            "pe0_rc", "pe1_rc"]
    with open(os.path.join(root, "abc_trials.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"<!-- {len(rows)} trials -> {os.path.join(root, 'abc_trials.csv')} -->")
    print("| config | fault | wait | n | handler (log) | app sees (wait_rc / quiet) | error CQE in slot at end of wait (op/syn/ven@wqe) | full-scan errs | detection ms (median, range) | QP (watch, end) | DBR word1 (final) | target iters ok | teardown (pe0 rc) |")
    print("|---|---|---|--:|---|---|---|---|---|---|---|---|---|")
    order = {"none": 0, "F1": 1, "F2b": 2, "F3": 3, "F4": 4}
    cells = {}
    for r in rows:
        cells.setdefault((r["config"], r["wait"], r["fault"]), []).append(r)
    for key in sorted(cells, key=lambda k: (k[0], k[1] != "timeout", order.get(k[2], 9))):
        rs = cells[key]
        cfg, wait, fault = key
        handlers = ",".join(sorted(set(x["handler_log"] for x in rs)))
        if wait == "timeout":
            app = ",".join(sorted(set({"0": "ok", "1": "timeout", "2": "error"}.get(x.get("wait_rc", ""), x.get("wait_rc", "?")) for x in rs)))
        else:
            app = ",".join(sorted(set(f"quiet returned {x['ok_iters']}/8" for x in rs)))
        cqe = ",".join(sorted(set(f"{x.get('cqe_opcode')}/{x.get('cqe_syndrome')}/{x.get('cqe_vendor_err')}@{x.get('cqe_wqe')}"
                                   if x.get("cqe_opcode") == "0xd" else f"{x.get('cqe_opcode')} (last ok)" for x in rs)))
        errs = ",".join(sorted(set(x.get("scan_errs", "") for x in rs)))
        det = []
        for x in rs:
            if wait == "timeout" and x.get("wait_rc") == "2":
                det.append(float(x["dt_ms"]))
            if wait == "blocking":
                dts = [float(v) for v in x["pe0_dt_ms_per_iter"].split() if v]
                fi = 4 if fault == "F2b" else 6
                if len(dts) > fi:
                    det.append(dts[fi])
        dets = f"{statistics.median(det):.1f} ({min(det):.1f}-{max(det):.1f})" if det else "-"
        qp = ",".join(sorted(set(re.sub(r"state=(\d+) hw_sq_wqebb=(\d+) sw_sq_wqebb=(\d+)", lambda m: {"3": "RTS", "6": "ERR"}.get(m.group(1), m.group(1)) + f" hw {m.group(2)} sw {m.group(3)}", x.get("qp_final", "")) for x in rs)))
        dbr = ",".join(sorted(set(re.sub(r".*word1\(sq\)=(\d+).*", r"\1", x.get("dbr_final", "")) for x in rs)))
        tgt = ",".join(sorted(set(str(x["pe1_iters_ok"]) for x in rs)))
        td = ",".join(sorted(set(x.get("pe0_rc", "") for x in rs)))
        print(f"| {cfg} | {fault} | {wait} | {len(rs)} | {handlers} | {app} | {cqe} | {errs} | {dets} | {qp} | {dbr} | {tgt} | {td} |")


if __name__ == "__main__":
    main()
