#!/usr/bin/env python3
"""qa_crosscheck.py - recount every trial from the raw logs and check it against trials.csv.

usage: qa_crosscheck.py <session_dir> [...]

For each session directory (the <out_dir> given to run_session.sh):
  * every requester log logs/req_<SID>_<variant>_<i>.log must hold exactly one "[req]"
    summary line, and its (variant, trial, trigger, first_err, status code, vendor_err,
    err ms, last_ok ms, OOB close) must equal the CSV row with that variant and trial;
  * the victim's own log (logs/victim*/<variant>_<i>.log) must show the configuration
    the variant name claims (qp=verbs|devx, mem=host|gpu|dmabuf, order, cuda placement),
    a registered MR, and for dmabuf "supported=1 get_handle rc=0";
  * no CSV row may lack a requester log and vice versa.
Prints a per-variant fingerprint count recomputed from the requester logs alone.
Exit status 0 when everything matches, 1 otherwise.
"""
import csv
import glob
import os
import re
import sys
from collections import Counter, defaultdict

REQ = re.compile(r"\[req\] (\S+) #(\d+) (\S+): first_err=(\S+)\((-?\d+)\) vendor=0x([0-9a-f]+) after (-?[\d.]+) ms; "
                 r"last_ok (-?[\d.]+) ms; ok_after=(\d+) flush=(\d+); OOB (\S+) at (-?[\d.]+) ms; reaped (-?[\d.]+) ms")
VIC = re.compile(r"\[resp\] pid \d+ qp=(\S+) mem=(\S+) order=(\S+) cuda=(\S+)")


def expect_from_name(v):
    """configuration implied by the variant name (None = not encoded)"""
    e = {}
    e["qp"] = "devx" if "devx" in v else "verbs"
    for m in ("dmabuf", "gpu", "host"):
        if m in v:
            e["mem"] = m
            break
    if "qpfirst" in v:
        e["order"] = "qp_first"
    elif "mrfirst" in v:
        e["order"] = "mr_first"
    if "ibvfirst" in v:
        e["cuda"] = "ibv_first"
    elif "cudafirst" in v:
        e["cuda"] = "cuda_first"
    return e


def check_session(d):
    bad = 0
    rows = {}
    csvp = os.path.join(d, "trials.csv")
    if os.path.exists(csvp):
        for r in csv.DictReader(open(csvp)):
            rows[(r["variant"], int(r["trial"]))] = r
    seen = set()
    counts = defaultdict(Counter)
    for p in sorted(glob.glob(os.path.join(d, "logs", "req_*.log"))):
        txt = open(p).read()
        ms = REQ.findall(txt)
        if len(ms) != 1:
            print("BAD %s: %d [req] lines" % (p, len(ms)))
            bad += 1
            continue
        (v, n, trig, name, code, ven, err, lok, okafter, flush, oob, oobt, reap) = ms[0]
        key = (v, int(n))
        seen.add(key)
        counts[v]["%s %s/0x%s" % (name, code, ven) if name != "none" else "none"] += 1
        r = rows.get(key)
        if r is None:
            print("BAD %s: no CSV row for %s" % (p, key))
            bad += 1
            continue
        pairs = [("trigger", trig, r["trigger"]), ("status", code, r["status"]),
                 ("status_name", name, r["status_name"]), ("vendor", "0x" + ven, r["vendor_err"]),
                 ("oob", oob, r["oob_close"])]
        for f, a, b in pairs:
            if a != b:
                print("BAD %s: %s log=%s csv=%s" % (key, f, a, b))
                bad += 1
        for f, a, b in (("err_ms", err, r["err_ms"]), ("last_ok_ms", lok, r["last_ok_ms"]),
                        ("oob_ms", oobt, r["oob_close_ms"]), ("reap_ms", reap, r["reap_ms"])):
            if abs(float(a) - float(b)) > 0.0015:
                print("BAD %s: %s log=%s csv=%s" % (key, f, a, b))
                bad += 1
        # victim log
        vl = glob.glob(os.path.join(d, "logs", "victim*", "%s_%s.log" % (v, n)))
        if len(vl) != 1:
            print("BAD %s: %d victim logs" % (key, len(vl)))
            bad += 1
            continue
        vt = open(vl[0]).read()
        m = VIC.search(vt)
        if not m:
            print("BAD %s: victim log has no config line" % (key,))
            bad += 1
            continue
        got = dict(zip(("qp", "mem", "order", "cuda"), m.groups()))
        for k, want in expect_from_name(v).items():
            if got[k] != want:
                print("BAD %s: victim %s=%s, name implies %s" % (key, k, got[k], want))
                bad += 1
        if "[resp] MR lkey=" not in vt:
            print("BAD %s: victim registered no MR" % (key,))
            bad += 1
        if got["mem"] == "dmabuf" and "supported=1 get_handle rc=0" not in vt:
            print("BAD %s: dmabuf not used" % (key,))
            bad += 1
    for key in rows:
        if key not in seen:
            print("BAD %s: CSV row without requester log" % (key,))
            bad += 1
    return bad, counts


def main(dirs):
    total_bad = 0
    allc = defaultdict(Counter)
    for d in dirs:
        b, c = check_session(d)
        total_bad += b
        for v, cc in c.items():
            allc[v].update(cc)
    for v, cc in allc.items():
        print("%-28s N=%-3d %s" % (v, sum(cc.values()), ", ".join("%s x%d" % kv for kv in cc.most_common())))
    print("mismatches: %d" % total_bad)
    return 1 if total_bad else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
