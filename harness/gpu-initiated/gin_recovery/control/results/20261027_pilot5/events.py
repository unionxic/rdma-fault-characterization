#!/usr/bin/env python3
"""events.py <raw dir> <stem>: pilot 5's (pilot 4's, plus the waitpeer lines and the kill/stop records) per-trial event list (suspicion, judgement, hold, decline, fence, waitpend, release),
times in ms after the injection line (GINRS gpuhang or quiet start), on rain's CLOCK_MONOTONIC (sunny's mono_ms - offset)."""
import re, sys, os, glob
raw, stem = sys.argv[1], sys.argv[2]
meta = open(os.path.join(raw, stem + "_meta.txt")).read()
def mv(k):
    m = re.search(r"\b%s=(\S+)" % k, meta); return m.group(1) if m else None
cand = [(float(mv("mono_off_rtt_ms")), float(mv("mono_off_sunny_ms"))), (float(mv("mono_off_after_rtt_ms")), float(mv("mono_off_after_ms")))]
OFF = min(cand)[1]
MONO = re.compile(r"\bmono_ms=([0-9.]+)")
def node(src):
    m = re.match(r"r(\d)$", src)
    if m: return "rain" if int(m.group(1)) % 2 == 0 else "sunny"
    if src.startswith("launcher_"): return src.split("_")[1]
    if src in ("kill", "inject"): return "sunny" if int(mv("subject_rank") or mv("kill_rank") or mv("stop_rank") or 3) % 2 else "rain"
    return "sunny" if mv("spare_rank") and int(mv("spare_rank")) % 2 else "rain"
PATS = [
 ("inject", re.compile(r"GINRS (gpuhang rank=\d+ step=\d+|quiet rank=\d+ step=\d+ ms=\d+|killed rank=\d+|stop rank=\d+)")),
 ("cont", re.compile(r"GINRS cont rank=(\d+) pid=\d+ present=(\d+) stopped_ms=([0-9.]+)")),
 ("published", re.compile(r"GIN/RS: rank (\d+): restore round with rank (\d+) published")),
 ("quiet_end", re.compile(r"GINRS quiet end rank=\d+ step=\d+ ms=\d+ done=1 took_ms=([0-9.]+)")),
 ("suspect", re.compile(r"GIN/RC: rank (\d+): rank (\d+) suspected \(kind=(\w+) stale_ms=([0-9.]+)(?: ctx=(\d+))?\)( \(partition guard: [^)]*\))?")),
 ("waiting", re.compile(r"GIN/RC: rank (\d+): rank (\d+) waiting \(peer=([0-9,]+)\) \(stale_ms=([0-9.]+) ctx=(-?\d+)")),
 ("wait_ended", re.compile(r"GIN/RC: rank (\d+): rank (\d+) wait ended \(([^;]*); waited ([0-9.]+) ms, stale_ms=([0-9.]+)")),
 ("verdict_dropped", re.compile(r"GIN/RC: rank (\d+): stall verdict of rank (\d+) \(incarnation \d+\) dropped")),
 ("own_line", re.compile(r"GIN/RC: rank (\d+): own device line (read locally|not read locally \([^)]*\))")),
 ("judged", re.compile(r"GIN/RC: rank (\d+): rank (\d+) \(incarnation \d+\) judged stalled \((.*?)\);.*?(ctx=\d+)?;")),
 ("dead", re.compile(r"GIN/TS: rank (\d+): rank (\d+) judged dead \(cause=([^)]*)\)")),
 ("stalled_rx", re.compile(r"GIN/RC: rank (\d+): STALLED\(rank (\d+), incarnation \d+\) from rank (\d+)")),
 ("nohold", re.compile(r"GIN/RS: rank (\d+): armed rank (\d+) \(incarnation \d+\) declined without a hold \((.*?)\); NOHOLD")),
 ("held_instead", re.compile(r"GIN/RS: rank (\d+): rank (\d+) \(incarnation \d+\) is held for a restore instead of a decline")),
 ("hold", re.compile(r"GIN/RS: rank (\d+): hold of rank (\d+) started")),
 ("given_up", re.compile(r"GIN/RS: rank (\d+): the restore of rank (\d+) \(incarnation \d+\) is given up \((.*?)\)")),
 ("declined", re.compile(r"GIN/TS: declined rank=(\d+) peer=(\d+) reason=\"([^\"]*)\"")),
 ("window", re.compile(r"GIN/RC: rank (\d+): window check after the (\w+) of rank (\d+).*?changed=(\d+).*?base=(\w+) sample=(\w+)")),
 ("waitpend", re.compile(r"GINRS waitpend rank=(\d+) step=(\d+) dest=(\d+) wait_ms=([0-9.]+)")),
 ("waitpend_end", re.compile(r"GINRS waitpend end rank=(\d+) step=(\d+) dest=(\d+) result=(\w+) wait_ms=([0-9.]+)")),
 ("released", re.compile(r"GINRS step rank=(\d+) step=(\d+) released=1 .*?tx_err=(\d+)")),
 ("degraded", re.compile(r"GIN/TS: rank (\d+): communicator degraded in \d+ ms: rank (\d+) was judged dead")),
 ("la_fence", re.compile(r"GIN/LA: node \d+: FENCE of rank (\d+) .*SIGKILL sent")),
 ("la_fenced", re.compile(r"GIN/LA: node \d+: rank (\d+) incarnation \d+ FENCED")),
 ("la_exited", re.compile(r"GIN/LA: node \d+: rank (\d+) incarnation \d+ EXITED")),
 ("la_act", re.compile(r"GIN/LA: node \d+: activation of rank (\d+) .*: (LATER|ACCEPTED|REFUSED)")),
 ("spare_restored", re.compile(r"GIN/RS: spare rank (\d+): restored as incarnation")),
 ("restored", re.compile(r"GIN/RS: rank (\d+): rank (\d+) restored as incarnation")),
]
ev = []
for f in sorted(glob.glob(os.path.join(raw, stem + "_*.log")) + glob.glob(os.path.join(raw, stem + "_kill.out")) + glob.glob(os.path.join(raw, stem + "_inject.out"))):
    src = f[len(os.path.join(raw, stem)) + 1:-4]
    if src.startswith("spare_") and src != "spare": continue
    nd = node(src)
    for l in open(f, errors="replace"):
        for name, p in PATS:
            m = p.search(l)
            if not m: continue
            mm = MONO.search(l)
            if not mm: continue
            t = float(mm.group(1)) - (OFF if nd == "sunny" else 0.0)
            ev.append((t, src, name, m.groups()))
            break
t0 = [e[0] for e in ev if e[2] == "inject"]
t0 = min(t0) if t0 else min(e[0] for e in ev)  # the first injection line in time
for t, src, name, g in sorted(ev):
    print("%10.1f\t%s\t%s\t%s" % (t - t0, src, name, " ".join(x for x in g if x is not None)))
