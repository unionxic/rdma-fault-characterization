#!/usr/bin/env python3
"""extra_qa.py <raw>: input pause max (pause_us) per trial in fault-free cells; waiter cell lines; quiet cell; mgmt mute; qperr; ud drop; credit."""
import sys, re, glob, os, collections
raw = sys.argv[1]
def stems(c):
    return sorted((p[:-9] for p in glob.glob(os.path.join(raw, c + "_n*_meta.txt"))), key=lambda s: int(s.rsplit("_n", 1)[1]))
PA = re.compile(r"input pause for rank \d+'s checkpoint \d+ ended .*?pause_us=(\d+)")
for c in ("gc4_none_ow_gc", "gc4_none_probe_gc", "mi4_train_none_gc"):
    out = []
    for s in stems(c):
        mx = 0
        for f in glob.glob(s + "_r?.log"):
            for l in open(f, errors="replace"):
                m = PA.search(l)
                if m: mx = max(mx, int(m.group(1)))
        out.append(mx / 1000.0)
    print(c, "max input pause ms per trial:", " ".join("%.3f" % x for x in out))
pat = {
 "waiting": re.compile(r"rank (\d): rank (\d) waiting \(peer=([0-9,]+)\)"),
 "wait_ended": re.compile(r"rank (\d): rank (\d) wait ended \((progress[^;]*|its peers[^;]*)"),
 "judge_r1": re.compile(r"rank (\d): rank 1 (\(incarnation \d+\) judged stalled|judged dead)"),
 "la_r1": re.compile(r"FENCE of rank 1 |rank 1 incarnation \d+ FENCED"),
}
for s in stems("gc4_gpuhang12000_waitpend_fence_gc"):
    c = collections.Counter(); peers = set(); ended = set()
    for f in glob.glob(s + "_*.log"):
        for l in open(f, errors="replace"):
            for k, p in pat.items():
                m = p.search(l)
                if m:
                    c[k] += 1
                    if k == "waiting": peers.add(m.group(3))
                    if k == "wait_ended": ended.add(m.group(3)[:30])
    kv = open(s + "_r1.kv").read()
    wp = re.search(r"waitpend=(\d)", kv)
    print(os.path.basename(s), dict(c), "peers", peers, "ended", ended, "r1 kv waitpend", wp.group(1) if wp else None)
# mgmt mute / qperr / ud drop / credit: key lines
keys = {
 "gc4_mgmt_mute8_gc": [r"record QP to rank \d+ re-paired|PAIR\(record", r"checkpoint \d+ stable"],
 "gc4_qperr_record_gc": [r"PAIR\(record, gen (\d+)\)", r"record QP to rank \d+ re-paired \(gen (\d+)\)|record QP.*?gen (\d+)"],
 "gc4_ud_drop_rejoin_gc": [r"REJOIN of rank 3 \(incarnation 1\) taken", r"test switch DROP_UD", r"FAIL"],
 "gc4_credit_stall_gc": [r"RNR", r"records_lost=(\d+)", r"records_dup=(\d+)"],
}
for c, ps in keys.items():
    for s in stems(c):
        cnt = []
        for p in ps:
            rp = re.compile(p); n = 0
            for f in glob.glob(s + "_*.log"):
                for l in open(f, errors="replace"):
                    if rp.search(l): n += 1
            cnt.append(n)
        print(os.path.basename(s), dict(zip(ps, cnt)))
