#!/usr/bin/env python3
"""summ.py <raw dir>: pilot 7's per-trial summary from events.py's list and the raw files: judgements (observer, target,
cause, ms after the first injection line), the confirmed-abort-decision lines (decided, sent, received with the result and
the remaining ms), each process's end (kv exit, xchg, watchdog, revived, steps_done) and its probe-summary ad_* fields
(the last summary line per peer; non-zero fields listed, with the peer)."""
import re, sys, os, glob, subprocess
raw = sys.argv[1]
EV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.py")
stems = sorted(os.path.basename(m)[:-9] for m in glob.glob(os.path.join(raw, "*_meta.txt")))
SUM = re.compile(r"GIN/RC: rank (\d+): probe summary peer=(\d+) .*?(ad_tx=.*?ad_resend=\d+)")
for s in stems:
    print("==", s)
    out = subprocess.run([sys.executable, EV, raw, s], capture_output=True, text=True).stdout.splitlines()
    for l in out:
        f = l.split("\t")
        if f[2] in ("judged", "dead", "declined", "nohold", "given_up", "degraded", "released", "restored", "spare_restored",
                    "la_fence", "la_fenced", "wait_ended", "waitpend_end") or f[2].startswith("ad_"):
            print("  " + l[:240])
    for k in sorted(glob.glob(os.path.join(raw, s + "_*.kv"))):
        src = k[len(os.path.join(raw, s)) + 1:-3]
        kv = open(k).read().split()
        d = dict(x.split("=", 1) for x in kv if "=" in x)
        end = " ".join("%s=%s" % (x, d[x]) for x in ("exit", "xchg", "watchdog", "revived", "steps_done", "tx_err") if x in d)
        print("  end %-10s %s" % (src, end))
    for lg in sorted(glob.glob(os.path.join(raw, s + "_*.log"))):
        src = lg[len(os.path.join(raw, s)) + 1:-4]
        if src.startswith("launcher"): continue
        last = {}
        for l in open(lg, errors="replace"):
            m = SUM.search(l)
            if m: last[int(m.group(2))] = (int(m.group(1)), m.group(3))
        tot = {}
        nz = []
        for p, (me, f) in sorted(last.items()):
            for kv in f.split():
                k, v = kv.split("="); v = int(v); tot[k] = tot.get(k, 0) + v
                if v: nz.append("peer%d:%s=%d" % (p, k, v))
        if last:
            print("  ad  %-10s rank %d summaries %d: %s" % (src, list(last.values())[0][0], len(last), " ".join(nz) or "all ad_* 0"))
