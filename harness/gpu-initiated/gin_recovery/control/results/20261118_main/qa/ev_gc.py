#!/usr/bin/env python3
"""ev_gc.py: independent event reader for the gin-control main run (QA recount; does not use rows_gc.py/score_gc.py).
load(raw, stem) -> dict(meta, ev, kv, files). Times: ms on rain's CLOCK_MONOTONIC; sunny mono_ms - OFF where OFF is the
node clock difference of the lower-RTT of the two meta measurements (mono_off_sunny_ms / mono_off_after_ms)."""
import re, os, glob

MONO = re.compile(r"\bmono_ms=([0-9.]+)")
STRIP = re.compile(r"\[2026[^]]*\] [a-z]+:[0-9:]+ \[[0-9]\] \S+ ")

PATS = [
 # injections
 ("inj_killed", re.compile(r"GINRS killed rank=(\d+) node=(\w+) pid=\d+(?: which=(\S+))?")),
 ("inj_stop", re.compile(r"GINRS stop rank=(\d+) pid=\d+ stop_ms=(\d+)")),
 ("inj_cont", re.compile(r"GINRS cont rank=(\d+) pid=\d+ present=(\d+) stopped_ms=([0-9.]+)")),
 ("inj_duty", re.compile(r"GINRS duty (start|end) rank=(\d+)")),
 ("inj_gpuhang", re.compile(r"GINRS gpuhang rank=(\d+) step=(\d+) spin=(\d+) ctx=(\S+)")),
 ("inj_quiet_end", re.compile(r"GINRS quiet end rank=(\d+) step=(\d+) ms=(\d+) done=(\d+) took_ms=([0-9.]+)")),
 ("inj_quiet", re.compile(r"GINRS quiet rank=(\d+) step=(\d+) ms=(\d+) spin=(\d+)")),
 ("inj_die", re.compile(r"GINRS die rank=(\d+) step=(\d+) where=(\S+)")),
 ("waitpend_end", re.compile(r"GINRS waitpend end rank=(\d+) step=(\d+) dest=(\d+) result=(\w+) wait_ms=([0-9.]+)")),
 ("waitpend", re.compile(r"GINRS waitpend rank=(\d+) step=(\d+) dest=(\d+) wait_ms=([0-9.]+)")),
 ("inj_switch", re.compile(r"rank (\d+): test switch (DIE_RST|FREEZE_PAGE=\S+|CREDIT_STALL|QP_ERR|RST_GAP|DROP_UD|FD_HOLDER=\w+|NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT)[: ](.*?) ?mono_ms")),
 ("inj_mute", re.compile(r"TEST socket mute (on|off) rank=(\d+)")),
 ("released_step", re.compile(r"GINRS step rank=(\d+) step=(\d+) released=1 .*?tx_err=(\d+)")),
 ("end", re.compile(r"GINRS end rank=(\d+) xchg=(\S+) steps_done=(\d+)")),
 # judgement
 ("suspect", re.compile(r"GIN/RC: rank (\d+): rank (\d+) suspected \(kind=(\w+) stale_ms=([0-9.]+)(?: ctx=(\d+))?\)")),
 ("waiting", re.compile(r"GIN/RC: rank (\d+): rank (\d+) waiting \(peer=([0-9,]+)\)")),
 ("wait_ended", re.compile(r"GIN/RC: rank (\d+): rank (\d+) wait ended \(([^;]*);")),
 ("probe_to", re.compile(r"GIN/RC: rank (\d+): probe of rank (\d+) timed out \(no CQE in (\d+) ms\)")),
 ("readfail", re.compile(r"GIN/RC: rank (\d+): liveness READ of rank (\d+)( \(device line\))?: (retry exceeded|probe QP broken)")),
 ("fin", re.compile(r"GIN/TS: rank (\d+): socket to rank (\d+) closed cause=(\w+)")),
 ("dead", re.compile(r"GIN/TS: rank (\d+): rank (\d+) judged dead \(cause=([^)]*)\)")),
 ("stalled", re.compile(r"GIN/RC: rank (\d+): rank (\d+) \(incarnation (\d+)\) judged stalled \(liveness stall judged \((\w+)\)\)")),
 ("stalled_rx", re.compile(r"GIN/RC: rank (\d+): STALLED\(rank (\d+), incarnation (\d+)\) from rank (\d+)")),
 ("ended_row", re.compile(r"GIN/RC: rank (\d+): rank (\d+) \(incarnation (\d+)\) ended by the judgement table \((?:table )?row (\d+)")),
 ("held_instead", re.compile(r"GIN/RS: rank (\d+): rank (\d+) \(incarnation \d+\) is held for a restore instead of a decline")),
 ("nohold", re.compile(r"GIN/RS: rank (\d+): armed rank (\d+) \(incarnation \d+\) declined without a hold")),
 ("hold", re.compile(r"GIN/RS: rank (\d+): hold of rank (\d+) started")),
 ("given_up", re.compile(r"GIN/RS: rank (\d+): the restore of rank (\d+) \(incarnation \d+\) is given up \((.*?)\)")),
 ("declined", re.compile(r"GIN/TS: declined rank=(\d+) peer=(\d+) reason=\"([^\"]*)\"")),
 ("degraded_now", re.compile(r"GIN/TS: rank (\d+): communicator degraded in (\d+) ms: rank (\d+) was judged dead")),
 ("degraded_ad", re.compile(r"GIN/TS: rank (\d+): communicator degraded in ([0-9.]+) ms: a confirmed abort decision about rank (\d+)")),
 ("waits_released", re.compile(r"GIN/TS: user devComm waits released rank=(\d+) why=(\w+)")),
 ("ad_decided", re.compile(r"GIN/RC: rank (\d+): confirmed abort decision no\. (\d+) \(incarnation \d+\): rank (\d+)")),
 ("ad_rx", re.compile(r"GIN/RC: rank (\d+): ABORT_DECIDED\(rank (\d+), incarnation \d+, no\. \d+, cause (\S+)\) of rank (\d+) \(incarnation \d+\) from rank \d+ via [^:]*: (applied|late)")),
 # fence / restore
 ("fence_sent", re.compile(r"GIN/RC: rank (\d+): rank (\d+) \(incarnation (\d+)\) fence FENCING: FENCE sent")),
 ("fence_fenced", re.compile(r"GIN/RC: rank (\d+): rank (\d+) \(incarnation (\d+)\) fence FENCED")),
 ("window", re.compile(r"GIN/RC: rank (\d+): window check after the (\w+) of rank (\d+): changed=(\d+).*?unreadable=(\d+)")),
 ("rejoin", re.compile(r"GIN/RS: rank (\d+): rank (\d+)'s spare rejoined as incarnation (\d+)")),
 ("published", re.compile(r"GIN/RS: rank (\d+): restore round with rank (\d+) published")),
 ("restored", re.compile(r"GIN/RS: rank (\d+): rank (\d+) restored as incarnation (\d+)")),
 ("spare_activating", re.compile(r"GIN/RS: spare rank (\d+): activating incarnation (\d+)")),
 ("spare_restored", re.compile(r"GIN/RS: spare rank (\d+): restored as incarnation (\d+)")),
 ("disarm", re.compile(r"GIN/RS: rank (\d+): DISARM")),
 # launcher
 ("la_fence", re.compile(r"GIN/LA: node (\d+): FENCE of rank (\d+) incarnation (\d+) from rank (\d+): (.*?) mono_ms")),
 ("la_fenced", re.compile(r"GIN/LA: node (\d+): rank (\d+) incarnation (\d+) FENCED: (.*?) mono_ms")),
 ("la_exited", re.compile(r"GIN/LA: node (\d+): rank (\d+) incarnation (\d+) (EXITED|exited; EXITED not sent)")),
 ("la_act", re.compile(r"GIN/LA: node (\d+): activation of rank (\d+) incarnation (\d+) for rank (\d+): (LATER|ACCEPTED|REFUSED)( \(([^)]*)\))?")),
 ("la_act_fail", re.compile(r"GIN/LA: node (\d+): activation of rank (\d+) incarnation (\d+) (could not hand over to the spare|.*?spare exited.*?)( mono_ms|$)")),
 ("la_left", re.compile(r"GIN/LA: node (\d+): rank (\d+) incarnation (\d+) left")),
]


def meta_of(raw, stem):
    p = os.path.join(raw, stem + "_meta.txt")
    s = open(p).read()
    d = {}
    for tok in s.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            if k not in d:
                d[k] = v
    return d


def kv_of(path):
    d = {}
    if not os.path.exists(path):
        return None
    for l in open(path, errors="replace"):
        for tok in l.split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                d[k] = v
    return d


def off_of(meta):
    c = []
    for r, o in (("mono_off_rtt_ms", "mono_off_sunny_ms"), ("mono_off_after_rtt_ms", "mono_off_after_ms")):
        try:
            c.append((float(meta[r]), float(meta[o])))
        except (KeyError, ValueError):
            pass
    return min(c)[1] if c else None


def load(raw, stem):
    meta = meta_of(raw, stem)
    OFF = off_of(meta)
    ev = []
    files = sorted(glob.glob(os.path.join(raw, stem + "_*.log")) + glob.glob(os.path.join(raw, stem + "_*.out")))
    for f in files:
        src = f[len(os.path.join(raw, stem)) + 1:].rsplit(".", 1)[0]
        if src in ("cleanup", "ss"):
            continue
        for ln, l in enumerate(open(f, errors="replace"), 1):
            if "GINRS step" in l and "released=1" not in l:
                continue
            for name, p in PATS:
                m = p.search(l)
                if not m:
                    continue
                mm = MONO.search(l)
                if mm:
                    t = float(mm.group(1))
                    # node by clock magnitude, checked against the source below
                    sunny = t < 5.6e9
                    if sunny:
                        t = t - OFF
                    clk = "mono"
                else:
                    # runner's receive clock (rain seconds) as fallback
                    t = float(l.split()[0]) * 1000.0
                    sunny = None
                    clk = "recv"
                ev.append(dict(t=t, src=src, name=name, g=m.groups(), file=os.path.basename(f), line=ln, clk=clk, sunny=sunny))
                break
    ev.sort(key=lambda e: e["t"])
    kv = {}
    for f in glob.glob(os.path.join(raw, stem + "_*.kv")):
        kv[f[len(os.path.join(raw, stem)) + 1:-3]] = kv_of(f)
    return dict(meta=meta, ev=ev, kv=kv, off=OFF, stem=stem)


def stems(raw):
    return sorted(os.path.basename(p)[:-9] for p in glob.glob(os.path.join(raw, "*_meta.txt")))
