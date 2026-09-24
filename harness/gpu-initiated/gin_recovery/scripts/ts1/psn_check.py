#!/usr/bin/env python3
"""Cross-check the two executed-prefix authorities read by the same responder QUERY_QP, on the first
recovery round of every run (epoch 0: the responder's receive PSN started at 0 at connect).

  rmsn (messages)       -> executed WQEs E (what S1 uses to decide what to re-post)
  next_rcv_psn (packets) -> must equal the PSNs of those E WQEs: every op is WRITE(bytes) + ATOMIC_FA,
                           a WRITE takes ceil(bytes / PMTU) packets, an ATOMIC one packet.
usage: psn_check.py <trials.csv> <runsdir> [pmtu=4096]
"""
import csv, glob, math, os, re, sys


def main():
    trials = {r["stem"]: r for r in csv.DictReader(open(sys.argv[1]))}
    runs = sys.argv[2]
    pmtu = int(sys.argv[3]) if len(sys.argv) > 3 else 4096
    n = agree = 0
    bad = []
    for stem, t in sorted(trials.items()):
        log = os.path.join(runs, stem + "_r0.log")
        if not os.path.exists(log):
            continue
        first = None
        for line in open(log, errors="replace"):
            if "GIN/TS: recovered" in line and "role=initiator" in line:
                first = line
                break
        if first is None:
            continue
        m = re.search(r"rmsn_peer0=(\d+) nrp_peer0=(0x[0-9a-f]+|\d+)", first)
        if not m:
            continue
        E = int(m.group(1))
        nrp = int(m.group(2), 0)
        wpk = math.ceil(int(t["bytes"]) / pmtu)
        expect = (E // 2) * (wpk + 1) + (wpk if E % 2 else 0)
        n += 1
        if nrp == expect:
            agree += 1
        else:
            bad.append((stem, E, nrp, expect))
    print(f"first-round rmsn vs next_rcv_psn (PMTU {pmtu}): {agree}/{n} agree")
    for b in bad[:20]:
        print("  mismatch", b)


if __name__ == "__main__":
    main()
