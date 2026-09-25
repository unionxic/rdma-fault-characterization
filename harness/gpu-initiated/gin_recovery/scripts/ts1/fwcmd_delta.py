#!/usr/bin/env python3
"""Per-hold firmware-command statistics of rain mlx5_1 from the before/after debugfs snapshots in
results/20260925_ts1/v2_fwcmd/ (fwcmd_snapshot.sh). For each hold and command: commands issued during
the hold (delta n), their mean latency (from n x average, which the driver keeps cumulatively), and new
failures. Also lists every mlx5 kernel message after 06:45:02 that is not a link or protection message.
usage: fwcmd_delta.py <v2_fwcmd dir>"""
import glob, os, re, sys

def load(p):
    d, dm = {}, []
    for l in open(p, errors="replace"):
        m = re.match(r"(\S+) n=(\d+) average_ns=(\d+) failed=(\d+) failed_mbox_status=(\d+) last_failed_errno=(\d+)", l)
        if m:
            d[m.group(1)] = tuple(int(x) for x in m.groups()[1:])
        elif l.startswith("["):
            dm.append(l.strip())
    return d, dm

D = sys.argv[1]
print("| hold | command | issued in hold | mean latency in hold (us) | new failures (mbox status) |")
print("|---|---|---|---|---|")
for b in sorted(glob.glob(os.path.join(D, "*_before.txt"))):
    a = b.replace("_before.txt", "_after.txt")
    if not os.path.exists(a):
        continue
    hold = os.path.basename(b)[: -len("_before.txt")]
    B, _ = load(b); A, dm = load(a)
    for c in ("2ERR_QP", "2RST_QP", "RST2INIT_QP", "INIT2RTR_QP", "RTR2RTS_QP", "QUERY_QP"):
        if c not in A or c not in B:
            continue
        n0, av0, f0, fm0, _ = B[c]; n1, av1, f1, fm1, _ = A[c]
        dn = n1 - n0
        mean = (n1 * av1 - n0 * av0) / dn / 1e3 if dn > 0 else float("nan")
        print(f"| {hold} | {c} | {dn} | {mean:.1f} | {f1 - f0} ({fm1 - fm0}) |")
last = sorted(glob.glob(os.path.join(D, "*_after.txt")), key=os.path.getmtime)
if last:
    _, dm = load(last[-1])
    print("\nmlx5 kernel messages in the last snapshot (tail):")
    for l in dm:
        print("  " + l)
