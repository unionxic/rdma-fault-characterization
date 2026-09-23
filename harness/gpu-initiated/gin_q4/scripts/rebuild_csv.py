#!/usr/bin/env python3
"""rebuild_csv.py - regenerate a trial CSV from the saved per-trial logs.

usage: rebuild_csv.py <logs_dir> <out_csv> [stem_glob]

For every <stem>_meta.txt in <logs_dir> (written by run_trial.sh), re-run q4_row.py
on <stem>_r0.kv / _r1.kv / _r0.log / _r1.log / _kill.out, so every CSV row uses the
current column set and parsing rules.
"""
import glob, os, re, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
logs, out = sys.argv[1], sys.argv[2]
pat = sys.argv[3] if len(sys.argv) > 3 else "*"
if os.path.exists(out):
    os.remove(out)
metas = sorted(glob.glob(os.path.join(logs, pat + "_meta.txt")))
for m in metas:
    stem = os.path.basename(m)[:-len("_meta.txt")]
    kv = dict(re.findall(r"(\w+)=(\S+)", open(m).read()))
    b = os.path.join(logs, stem)
    subprocess.run([sys.executable, os.path.join(here, "q4_row.py"), "--csv", out, "--fault", kv["fault"],
                    "--wait", kv["wait"], "--trial", kv["trial"], "--cq", kv["cq"], "--classify", kv["classify"],
                    "--r0kv", b + "_r0.kv", "--r1kv", b + "_r1.kv", "--r0log", b + "_r0.log", "--r1log", b + "_r1.log",
                    "--kill", b + "_kill.out", "--r0rc", kv["r0rc"], "--r1rc", kv["r1rc"], "--left", kv.get("left", ""),
                    "--stem", stem], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("rebuilt %d rows -> %s" % (len(metas), out))
