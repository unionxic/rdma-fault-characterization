#!/usr/bin/env python3
"""summarize.py - re-derive the teardown-fingerprint table from raw trials.csv files.

usage: summarize.py <trials.csv> [...]   (rows from several sessions are merged by variant)

Per variant: N, fingerprint counts (status/vendor_err), time trigger -> first error CQE,
time trigger -> last successful completion, OOB close kind/time, victim reap time, and
where the responder stopped answering relative to the marker fds' release times.

Marker windows: each marker is a socket the victim opened right after a setup step
(start, after_cuda, after_ibv, after_mr, after_qp, last). At exit the kernel releases
fds; the launcher timestamps each marker's FIN. `stop_window` names the two markers
whose release times bracket the moment the responder stopped acknowledging
(last_ok_ms for RETRY_EXC, err_ms for a NAK), i.e. which files were being released
at that moment.
"""
import csv
import statistics
import sys
from collections import OrderedDict, Counter


def fnum(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v < 0 and v == -1 else v


def med(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    return "%.1f [%.1f-%.1f]" % (statistics.median(vals), min(vals), max(vals))


def parse_markers(s):
    out = []
    for part in (s or "").split("|"):
        if "@" not in part:
            continue
        label, rest = part.split("@", 1)
        fd, t = rest.split(":", 1)
        out.append((label, int(fd[2:]), float(t)))
    return out


def window(markers, t):
    """names of the markers released just before and just after time t"""
    if t is None or not markers:
        return "-"
    before = [m for m in markers if m[2] <= t]
    after = [m for m in markers if m[2] > t]
    b = before[-1][0] if before else "(kill)"
    a = after[0][0] if after else "(end)"
    return "%s..%s" % (b, a)


def main(paths):
    rows = []
    for p in paths:
        with open(p) as f:
            rows += list(csv.DictReader(f))
    by = OrderedDict()
    for r in rows:
        by.setdefault(r["variant"], []).append(r)
    print("| variant | trigger | N | error code (status/vendor_err) | err_ms | last_ok_ms | OOB close | reap_ms | stop window (marker release) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for v, rs in by.items():
        fp = Counter()
        wins = Counter()
        oob = Counter()
        for r in rs:
            st = r["status_name"]
            fp[st if st == "none" else "%s %s/%s" % (st, r["status"], r["vendor_err"])] += 1
            oob[r["oob_close"]] += 1
            mk = parse_markers(r["markers_close_order"])
            is_nak = st not in ("RETRY_EXC", "none")
            t = fnum(r["err_ms"]) if is_nak else fnum(r["last_ok_ms"])
            if r["trigger"] == "kill":
                wins[window(mk, t)] += 1
        fps = ", ".join("%s x%d" % (k, n) for k, n in fp.most_common())
        oobs = ", ".join("%s x%d" % (k, n) for k, n in oob.most_common())
        if rs[0]["trigger"] == "kill":
            oobs += " @ " + med([fnum(r["oob_close_ms"]) for r in rs])
        ws = ", ".join("%s x%d" % (k, n) for k, n in wins.most_common()) if wins else "-"
        print("| %s | %s | %d | %s | %s | %s | %s | %s | %s |" % (
            v, rs[0]["trigger"], len(rs), fps,
            med([fnum(r["err_ms"]) for r in rs]),
            med([fnum(r["last_ok_ms"]) for r in rs]),
            oobs,
            med([fnum(r["reap_ms"]) for r in rs]) if rs[0]["trigger"] == "kill" else "-",
            ws))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1:])
