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
import rows_rs  # noqa: E402


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


def parser_fix_cases():
    """the parser's rules for the two fixes of 2026-10-13 (the pilot P1): the checkpoint-pause kill by the library's test
    switch (its line is the kill time; no _kill.out) and the activation's 'later' answers; the regression paths of a
    deployment set; a spare whose wait ran out is no activation"""
    d = tempfile.mkdtemp(prefix="rs_parser_fix_")
    raw = os.path.join(d, "raw")
    pause = lambda r, k: (2.0012, "GIN/RS: rank %d: input pause for rank 3's checkpoint %d ended (a hold of that rank "
                                  "took its gates) pause_us=900" % (r, k))
    armed = lambda r, k, t: (t, "GIN/RS: rank %d: rank 3 armed at its stable checkpoint %d" % (r, k))
    # 1: the death inside checkpoint 120's pause, restored from checkpoint 100 (armed 1.5 s before the death)
    score._rs(raw, "rs4_kill3_ckpt", "rs", 1, kill=3, spare=True, hook=(120, 300),
              lib_lines={r: [armed(r, 100, 0.5), pause(r, 120),
                             (3.5, "GIN/RS: rank %d: every survivor holds rank 3: its spare activated (incarnation 1, "
                                   "41.7 ms after this rank's hold start), 2 'later' answers over 20.4 ms" % r)]
                         for r in (0, 1, 2)})
    # 2: the restored checkpoint (100) became stable only after the death; the survivors paused for another checkpoint
    score._rs(raw, "rs4_kill3_ckpt", "rs", 2, kill=3, spare=True, hook=(120, 300),
              lib_lines={r: [armed(r, 100, 2.5), pause(r, 140)] for r in (0, 1, 2)})
    # 3: a spare whose activation wait ran out: its Resume line has rc != 0 (no activation time)
    score._rs(raw, "rs4_kill3", "rs", 1, kill=3, spare=True)
    p3 = os.path.join(raw, "rs4_kill3_rs_n1_spare.log")
    open(p3, "w").write("100.000000 GINRS start rank=3 mode=spare\n101.250000 GINRS spare_ready rank=3 rt_s=1.0\n"
                        "161.300000 GINRS resume rank=3 rc=2 step=0\n")
    # 4: the checkpoint-pause cell without the test-switch line (the rank ended by a SIGKILL of its timeout): not applied
    score._rs(raw, "rs4_kill3_ckpt", "rs", 3, kill=3, spare=True, hook=(120, 300))
    p4 = os.path.join(raw, "rs4_kill3_ckpt_rs_n3_r3.log")
    open(p4, "w").write("".join(l for l in open(p4) if "TEST_DIE_IN_CKPT" not in l))
    rows = {r["id"]: r for r in rows_rs.all_rows(d)}
    out = []

    def expect(name, got, want):
        if got != want:
            out.append("parser (fixes): %s: got %r want %r" % (name, got, want))
    r1, r2, r3 = rows["rs4_kill3_ckpt_rs_n1"], rows["rs4_kill3_ckpt_rs_n2"], rows["rs4_kill3_rs_n1"]
    expect("the test-switch line applies the kill", r1["applied"], 1)
    expect("its checkpoint", r1["die_ckpt"], 120)
    expect("every survivor's pause for it was ended by the hold", r1["die_in_pause"], 3)
    expect("the restored checkpoint was stable (armed) before the death", r1["ckpt_before"], 1)
    expect("kill time = the test-switch line (activation 4.0 - 2.0005 s)", r1["spare_activate_ms"], 1999.5)
    expect("the buddy's activation line", (r1["activate_ms"], r1["later_n"], r1["later_ms"]), (41.7, 2, 20.4))
    expect("meta kill_in_hook", r1["kill_in_hook"], "1")
    expect("no test-switch line: not applied (exit 137 alone)", rows["rs4_kill3_ckpt_rs_n3"]["applied"], 0)
    expect("stable only after the death", r2["ckpt_before"], 0)
    expect("no stable checkpoint before the death", r2["ckpt_stable_before_kill"], 0)
    expect("the pause of another checkpoint", r2["die_in_pause"], 0)
    expect("no activation line", r2["later_n"], "")
    expect("a spare's failed Resume is no activation", r3["spare_activate_ms"], "")
    expect("the old kill line keeps its cell", (r3["applied"], r3["die_ckpt"], r3["die_in_pause"]), (1, "", ""))
    for mk, want in (("../../../rs-bundle/mr/ff", True), ("../../../rs-bundle/i4/mr/hold", True),
                     ("../../../rs-bundle/i4/mr/ff/", True), ("hr", True), ("../../../rs-bundle/i4/lib/rs", False),
                     ("../../../gi-bundle/gin_ts2/mr/x", False)):
        expect("regression driver path %s" % mk, score.ours_mrkey(mk), want)
    return out


def main():
    fails = parser_command() + parser_fix_cases()
    if fails:
        print("PARSER SELFTEST FAILED:")
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PARSER SELFTEST: passed")
    sys.exit(score.selftest())


if __name__ == "__main__":
    main()
