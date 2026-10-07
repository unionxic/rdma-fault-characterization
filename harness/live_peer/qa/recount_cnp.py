#!/usr/bin/env python3
"""recount_cnp.py <extracted_release_root> [out.csv] - recount the congestion-notification counters of
the propagation campaign from its raw evrec records (EXPERIMENT.md section 1.2 and 1.3).

Input: the two Release data-20261006 archives
  harness__gpu-initiated__propagation__results__20261006_campaign.tar.xz
  harness__gpu-initiated__propagation__results__20261006_f4rerun.tar.xz
extracted under <root> (paths harness/gpu-initiated/propagation/results/...). The GIN proxy and GDAKI
peer-kill trials of the campaign (gp/gg *_F4_*) are replaced by the re-run, as in the campaign's own
scoring (propagation DEVIATIONS 10).

Output: one row per (trial, node) with the end-minus-start delta of each counter below, and a summary on
stdout: per stack, fault and node, the range of each delta; the verbs-QP identities
rp_cnp_handled == roce_slow_restart_cnps == roce_adp_retrans + local_ack_timeout_err - 1; and how many
records show any real congestion signal (np_cnp_sent, np_ecn_marked_roce_packets, rp_cnp_ignored).
Read-only on its input.
"""
import collections, csv, glob, os, re, sys

CT = ["rp_cnp_handled", "rp_cnp_ignored", "np_cnp_sent", "np_ecn_marked_roce_packets", "roce_slow_restart_cnps",
      "roce_slow_restart", "roce_slow_restart_trans", "roce_adp_retrans", "roce_adp_retrans_to",
      "local_ack_timeout_err", "req_cqe_error", "packet_seq_err", "out_of_sequence", "duplicate_request",
      "implied_nak_seq_err", "rnr_nak_retry_err"]
RE_CTR = re.compile(r"ctr phase=(start|end) dir=hw_counters name=(\S+) value=(\d+)")


def delta(path):
    st, en = {}, {}
    for line in open(path, errors="replace"):
        m = RE_CTR.match(line)
        if m:
            (st if m.group(1) == "start" else en)[m.group(2)] = int(m.group(3))
    if not en:
        return None
    return {k: en[k] - st[k] for k in CT if k in st and k in en}


def fault_of(stack, tag):
    if stack == "cpu":
        return re.match(r"cpu_(.+)_t\d+$", tag).group(1)
    if stack in ("gp", "gg", "gq", "nvf", "net"):
        return tag.split("_")[1]
    if stack == "nvo":
        return "kill" + tag.split("kill")[1][0] + "_" + tag.split("_")[1]
    if stack == "nvd":
        return "_".join(tag.split("_")[1:-1])
    return tag


def retry_like(stack, tag):
    return any(s in tag for s in ("_F3_", "_F4_", "retry_server_qp_err", "retry_proc_sigkill", "kill1"))


def main():
    root = os.path.join(sys.argv[1], "harness/gpu-initiated/propagation/results")
    out = sys.argv[2] if len(sys.argv) > 2 else None
    rows = []
    for sub in ("20261006_campaign", "20261006_f4rerun"):
        for p in sorted(glob.glob(os.path.join(root, sub, "*", "evrec", "*.evrec.*"))):
            stack = p.split(os.sep)[-3]
            tag, node = os.path.basename(p).rsplit(".evrec.", 1)
            if sub == "20261006_campaign" and stack in ("gp", "gg") and "_F4_" in tag:
                continue
            d = delta(p)
            if d is None:
                print("no end snapshot:", p)
                continue
            rows.append(dict(source=sub, stack=stack, tag=tag, node=node, fault=fault_of(stack, tag), **d))
    if out:
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["source", "stack", "tag", "node", "fault"] + CT)
            w.writeheader()
            w.writerows(rows)
    print(f"records: {len(rows)}")
    g = collections.defaultdict(list)
    for r in rows:
        g[(r["stack"], r["fault"], r["node"])].append(r)

    def rng(v):
        return f"{min(v)}" if min(v) == max(v) else f"{min(v)}-{max(v)}"
    cols = ["rp_cnp_handled", "roce_slow_restart_cnps", "roce_adp_retrans", "local_ack_timeout_err", "np_cnp_sent",
            "np_ecn_marked_roce_packets", "rp_cnp_ignored"]
    print("stack fault node n | " + " | ".join(cols))
    for k in sorted(g):
        print(*k, len(g[k]), "|", " | ".join(rng([r[c] for r in g[k]]) for c in cols))
    rain_retry = [r for r in rows if r["node"] == "rain" and retry_like(r["stack"], r["tag"])]
    rain_other = [r for r in rows if r["node"] == "rain" and not retry_like(r["stack"], r["tag"])]
    print(f"rain retry-exceeded and peer-kill trials: {len(rain_retry)}, rp_cnp_handled > 0 in "
          f"{sum(r['rp_cnp_handled'] > 0 for r in rain_retry)}")
    print(f"rain other trials: {len(rain_other)}, rp_cnp_handled > 0 in {sum(r['rp_cnp_handled'] > 0 for r in rain_other)}")
    sunny_up = sorted({re.sub(r"_t\d+$", "", r["tag"]) for r in rows if r["node"] == "sunny" and r["rp_cnp_handled"] > 0})
    print(f"sunny records with rp_cnp_handled > 0: "
          f"{sum(r['node'] == 'sunny' and r['rp_cnp_handled'] > 0 for r in rows)} ({', '.join(sunny_up)})")
    verbs = [r for r in rain_retry if r["stack"] in ("cpu", "gp") and r["rp_cnp_handled"] > 0]
    print(f"verbs QPs with rp_cnp_handled > 0: {len(verbs)}; rp == slow_restart_cnps in "
          f"{sum(r['rp_cnp_handled'] == r['roce_slow_restart_cnps'] for r in verbs)}; rp == adp + lat - 1 in "
          f"{sum(r['rp_cnp_handled'] == r['roce_adp_retrans'] + r['local_ack_timeout_err'] - 1 for r in verbs)}")
    sig = sum(r["np_cnp_sent"] > 0 or r["np_ecn_marked_roce_packets"] > 0 or r["rp_cnp_ignored"] > 0 for r in rows)
    print(f"records with any real congestion signal: {sig}/{len(rows)}")


if __name__ == "__main__":
    main()
