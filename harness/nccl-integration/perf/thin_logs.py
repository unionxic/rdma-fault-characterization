#!/usr/bin/env python3
"""thin_logs.py - shrink a logs.tar.gz of nccl_ct runs for the repository (analysis only).

Every line that is not a per-iteration "IT <it> <ms>" line is kept (NCCL warnings, recovery lines,
SUMMARY, errors). Of the IT lines, kept are: the first and last KEEP_EDGE, every EVERY-th, and
CONTEXT lines on each side of any IT line whose gap to the previous one is more than STALL times
the log's median gap (a stall: the fault, the recovery, a hang). The verdicts and counts in
results.csv come from the SUMMARY lines, which are kept whole.

usage: thin_logs.py <logs.tar.gz> [<more.tar.gz> ...]   (rewrites each archive in place)
"""
import io, re, statistics, sys, tarfile

KEEP_EDGE, EVERY, CONTEXT, STALL = 20, 1000, 5, 5.0
IT = re.compile(r"^(\d+\.\d+) IT (\d+) ")


def thin(text):
    lines = text.splitlines(keepends=True)
    its = [(i, float(m.group(1))) for i, l in enumerate(lines) if (m := IT.match(l))]
    if len(its) < 4 * KEEP_EDGE:
        return text, 0
    gaps = [b[1] - a[1] for a, b in zip(its, its[1:])]
    med = statistics.median(gaps) or 1e-9
    keep = set(i for i, _ in its[:KEEP_EDGE] + its[-KEEP_EDGE:])
    keep.update(i for k, (i, _) in enumerate(its) if k % EVERY == 0)
    for k, g in enumerate(gaps, start=1):
        if g > STALL * med:
            for j in range(max(0, k - CONTEXT), min(len(its), k + CONTEXT + 1)):
                keep.add(its[j][0])
    it_idx = set(i for i, _ in its)
    out, dropped = [], 0
    for i, l in enumerate(lines):
        if i in it_idx and i not in keep:
            dropped += 1
            continue
        out.append(l)
    return "".join(out), dropped


for path in sys.argv[1:]:
    members = []
    with tarfile.open(path, "r:gz") as tf:
        for m in tf.getmembers():
            data = tf.extractfile(m).read() if m.isfile() else None
            members.append((m, data))
    total = 0
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as out:
        for m, data in members:
            if data is not None and m.name.endswith(".log"):
                text, dropped = thin(data.decode("utf-8", "replace"))
                if dropped:
                    text += f"# thin_logs.py: {dropped} per-iteration IT lines removed (see thin_logs.py)\n"
                    total += dropped
                data = text.encode()
                m.size = len(data)
            out.addfile(m, io.BytesIO(data) if data is not None else None)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    print(f"{path}: {total} IT lines removed, {len(buf.getvalue())} bytes")
