#!/usr/bin/env python3
"""summarize.py - turn nrc_devx SUMMARY lines (summary.txt of one or more batch dirs) into
results/all_trials.csv and a markdown table on stdout.

usage: summarize.py <results_dir> [<results_dir> ...]
"""
import csv
import glob
import os
import re
import sys

KV = re.compile(r'(\w+)=("([^"]*)"|\S*)')
COLS = ["batch", "tag", "rc", "fault", "preset", "sets", "ack_timeout", "err_cqe", "t_first_err_ms",
        "first_err_syndrome", "first_err_vendor", "first_err_wqe", "n_cqe_writes", "cq_err", "slot0",
        "qp_state_final", "t_qp_err_ms", "hw_sq", "sw_sq", "cur_retry", "last_acked_psn", "next_send_psn",
        "dbr0", "dbr1", "pi", "t_last_xmit_change_ms", "xmit_pkts", "rcv_pkts", "target_state", "target_signal",
        "hw_local_ack_timeout_err", "hw_req_cqe_error", "hw_req_cqe_flush_error", "hw_req_remote_access_errors"]


def parse(line):
    d = {}
    for m in KV.finditer(line):
        d[m.group(1)] = m.group(3) if m.group(3) is not None else m.group(2)
    return d


def main():
    rows = []
    for rd in sys.argv[1:]:
        for f in sorted(glob.glob(os.path.join(rd, "**", "summary.txt"), recursive=True)):
            batch = os.path.basename(os.path.dirname(f))
            for line in open(f):
                if not line.startswith("tag="):
                    continue
                d = parse(line)
                d["batch"] = batch
                rows.append(d)
    out = os.path.join(sys.argv[1], "all_trials.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"<!-- {len(rows)} trials -> {out} -->")
    print("| tag | fault | preset | sets | error CQE | first error (syn/vendor@wqe, ms) | slot0 | QP final | QP->ERR ms | dbr0/dbr1 | pi | xmit pkts | last xmit change ms |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        fe = "-"
        if r.get("err_cqe") == "1":
            fe = f"{r.get('first_err_syndrome')}/{r.get('first_err_vendor')}@{r.get('first_err_wqe')}, {float(r.get('t_first_err_ms', 0)):.1f}"
        print(f"| {r.get('tag')} | {r.get('fault')} | {r.get('preset')} | {r.get('sets')} | {r.get('err_cqe', 'NA')} | {fe} | "
              f"{r.get('slot0')} | {r.get('qp_state_final')} | {r.get('t_qp_err_ms')} | {r.get('dbr0')}/{r.get('dbr1')} | "
              f"{r.get('pi')} | {r.get('xmit_pkts')} | {r.get('t_last_xmit_change_ms')} |")


if __name__ == "__main__":
    main()


def nvshmem_csv(root):
    """nvshmem.txt KV lines (nv*/) -> <root>/nvshmem_trials.csv"""
    cols = ["batch", "trial", "backend", "fix", "hold", "ok_iters", "fail_iter", "wait_rc", "dt_ms", "cqe_opcode",
            "cqe_syndrome", "cqe_vendor_err", "cqe_wqe", "ready_head", "scan_errs", "errcqe",
            "watch_first_rc_err_ms", "watch_rc_last", "dbr_last", "qp_seq", "xmit_total", "pe0_rc", "pe1_rc"]
    rows = []
    for f in sorted(glob.glob(os.path.join(root, "nv*", "nvshmem.txt"))):
        for line in open(f):
            if line.startswith("trial="):
                d = parse(line.replace(";t_last_xmit_change_ms=", " t_last_xmit_change_ms="))
                d["batch"] = os.path.basename(os.path.dirname(f))
                rows.append(d)
    if rows:
        out = os.path.join(root, "nvshmem_trials.csv")
        with open(out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"<!-- {len(rows)} NVSHMEM trials -> {out} -->")


if len(sys.argv) > 1:
    nvshmem_csv(sys.argv[1])
