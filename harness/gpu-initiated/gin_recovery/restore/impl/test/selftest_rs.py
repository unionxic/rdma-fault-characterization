#!/usr/bin/env python3
"""selftest_rs.py - gin-restore work package 10: the CPU-only self-tests of the parser (rows_rs.py, also as a command
writing trials.csv) and the scorer (score.py's synthetic cases A-D) on synthetic result folders. No cluster, no GPU, no
NCCL: synthetic kv/meta/receipt-clock files go to a temp dir. Run on this branch before the pilot; needs nothing deployed.

usage: selftest_rs.py
"""
import csv, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score  # noqa: E402  (its synthetic builders and the scorer self-test)


def parser_command():
    """rows_rs.py as a command on a synthetic folder: the columns score.py reads are present, a clean trial reads clean."""
    d = tempfile.mkdtemp(prefix="rs_parser_")
    raw = os.path.join(d, "raw")
    score._rs(raw, "rs4_none", "rs", 1, win=[(1, 1, 0)])
    score._rs(raw, "rs4_kill3", "rs", 1, kill=3, spare=True)
    score._cost(os.path.join(d, "cost_x"), "lat4k", "on", "rain", 1, 10.6)
    subprocess.run([sys.executable, os.path.join(HERE, "rows_rs.py"), d], check=True, stdout=subprocess.DEVNULL)
    rows = list(csv.DictReader(open(os.path.join(d, "trials.csv"))))
    need = ["wait_held", "data_equal", "no_reexec", "revived_done", "strict_forced", "strict_bad", "resume_err_all",
            "reason_same", "ff_fallthrough", "restore_live", "suppress_ok", "restore_time_ms", "ckpt_pause_ms", "value"]
    miss = [c for c in need if c not in rows[0]]
    if miss:
        return ["parser: missing columns %s" % miss]
    byid = {r["id"]: r for r in rows}
    out = []
    if byid.get("rs4_none_rs_n1", {}).get("data_equal") != "1":
        out.append("parser: a clean rs4_none trial did not read data_equal=1")
    if byid.get("rs4_kill3_rs_n1", {}).get("revived_done") != "1":
        out.append("parser: a revived spare did not read revived_done=1")
    if byid.get("cost_lat4k_on_rain_k1", {}).get("key") != "cost_lat4k_on@rsp":
        out.append("parser: a cost run's key is not cost_<metric>_<arm>@<lib>")
    return out


def main():
    fails = parser_command()
    if fails:
        print("PARSER SELFTEST FAILED:")
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PARSER SELFTEST: passed")
    sys.exit(score.selftest())


if __name__ == "__main__":
    main()
