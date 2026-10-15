#!/usr/bin/env python3
"""selftest_mi.py - gin-mirror, test branch: the CPU-only self-tests of the parser (rows_mi.py, also as a command writing
trials.csv) and the scorer (score.py's synthetic cases A-D) on synthetic result folders, plus every rs cell of
cells_mi.json reaching run_mi.sh in its dry mode, and the rs_set_mi.sh check. No cluster, no GPU, no NCCL. Run on this
branch before the pilot; needs nothing deployed.

usage: selftest_mi.py
"""
import csv, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score  # noqa: E402  (its synthetic builders and the scorer self-test)
import rows_mi  # noqa: E402


def parser_command():
    """rows_mi.py as a command on a synthetic folder: the columns score.py reads are present, a clean overwrite kill trial
    reads clean, a cost run keys as cost_<metric>_<arm>@<lib>."""
    d = tempfile.mkdtemp(prefix="mi_parser_")
    raw = os.path.join(d, "raw")
    score._ow_kill3(raw, "mi4_kill3_ow", 1)
    score._mi(raw, "mi4_none_ow", 1)
    score._cost(os.path.join(d, "cost_x"), "bw2m", "mirror-peer", "rain", 1, 3.3)
    subprocess.run([sys.executable, os.path.join(HERE, "rows_mi.py"), d], check=True, stdout=subprocess.DEVNULL)
    rows = list(csv.DictReader(open(os.path.join(d, "trials.csv"))))
    need = ["wait_held", "ow_data_equal", "no_reexec", "revived_done", "from_pool_ok", "export_source_bytes",
            "fetch_us", "fetch_bytes", "import_pool_bytes", "pool_max_bytes", "lane_broken", "disarm_n", "seg_restart_n",
            "inj_from_n", "tcp_image_bytes", "tcp_segment_bytes", "recv_poison", "dev_poison", "nomirror_corrupt",
            "nomirror_detect", "applied2", "reimage_ok", "second_ok", "paced_ok", "restore_time_ms_1",
            "restore_time_ms_2", "resume_refused", "spare2_start_fail", "restarts", "pulls_sent", "value", "mi_summary_ok",
            "lane_broken_designed", "lane_broken_other", "disarm_designed", "disarm_other", "broken_other"]
    miss = [c for c in need if c not in rows[0]]
    out = []
    if miss:
        return ["parser: missing columns %s" % miss]
    byid = {r["id"]: r for r in rows}
    k3 = byid.get("mi4_kill3_ow_mi_n1", {})
    if k3.get("ow_data_equal") != "1":
        out.append("parser: a clean overwrite kill trial did not read ow_data_equal=1")
    if k3.get("from_pool_ok") != "1":
        out.append("parser: from_pool_ok not 1 on a clean mirror restore")
    if k3.get("tcp_image_bytes") != "0":
        out.append("parser: tcp_image_bytes not 0 (store_rdma)")
    # the designed buddy gap (9.6): the hold's two lane breaks toward rank 2 are designed, nothing else breaks
    gap = tuple(k3.get(c) for c in ("lane_broken", "lane_broken_designed", "lane_broken_other", "disarm_other",
                                    "broken_other"))
    if gap != ("2", "2", "0", "0", "0"):
        out.append("parser: the designed buddy gap of a clean kill reads %s, want (2, 2, 0, 0, 0)" % (gap,))
    if byid.get("cost_bw2m_mirror-peer_rain_k1", {}).get("key") != "cost_bw2m_mirror-peer@mip":
        out.append("parser: a cost run's key is not cost_<metric>_<arm>@<lib>")
    return out


# a cell variable -> the key of run_mi.sh's configuration line (RS_DRY_CONFIG=1) that must show it
CELL_KEYS = {"DRIVER": "driver", "CELL_GIN_TYPE": "gin_type", "SYM_GIN": "sym_gin", "RESTORE": "restore",
             "FAULT_POLICY": "policy", "KILL_RANK": "kill_rank", "SPARE": "spare_wanted", "KILL_IN_HOOK": "kill_in_hook",
             "CKPT_STEPS": "ckpt_steps", "SPARE_KILL_FIRST": "spare_kill_first",
             "CONTINUE_AFTER_REFUSAL": "continue_after_refusal", "R0_ENV": "r0_env", "R1_ENV": "r1_env",
             "R2_ENV": "r2_env", "R3_ENV": "r3_env", "MIRROR": "mirror", "MIRROR_SLOTS": "mirror_slots",
             "MIRROR_LANE": "mirror_lane", "MIRROR_PULL": "mirror_pull", "POOL_MAX_MB": "pool_max_mb",
             "FETCH_MB": "fetch_mb", "STORE_WRITE_MS": "store_write_ms", "OVERWRITE": "overwrite", "TRAIN": "train",
             "RING": "ring", "STEPS": "steps", "BYTES": "bytes", "QPWATCH": "qpwatch_ms", "SPARE_WAIT_MS": "spare_wait_ms",
             "KILL_AFTER_STABLE": "kill_after_stable", "DIE_SEED": "die_seed", "KILL2_RANK": "kill2_rank",
             "SPARE2": "spare2_wanted", "CHECKSUM": "checksum", "DIE_US_MAX": "die_us_max"}
# variables run_mi.sh reads but does not echo verbatim (drawn or combined); checked separately below
DRAWN = {"DIE_LO", "DIE_HI", "DIE2_LO", "DIE2_HI"}


def cell_config_cases():
    """every cell variable of cells_mi.json reaches run_mi.sh: no variable starts with NCCL_ or GIN_ (the runner drops
    those of the caller), and for every rs cell, cells_mi.sh -> run_mi.sh in its dry mode (RS_DRY_CONFIG=1) shows each of
    the cell's values; the reg cells' variables are cells_mi.sh's own (MIRROR, MR_*, FAULT_POLICY, RESTORE, DRIVER). Also
    the drawn kills appear (die_at/die2_at) and the memory estimate is positive. The shared RS_SET check (rs_set_mi.sh)."""
    out = []
    cells = json.load(open(os.path.join(HERE, "cells_mi.json")))
    d = tempfile.mkdtemp(prefix="mi_cfg_")
    seen = 0
    for hold, cl in cells["holds"].items():
        for e in cl:
            env = dict(e.get("env", {}))
            for k in env:
                if k.startswith("NCCL_") or k.startswith("GIN_"):
                    out.append("cells: %s/%s: variable %s would be dropped by the runner" % (hold, e["cell"], k))
            if e["kind"] != "rs":
                for k in env:
                    if not (k.startswith("MR_") or k in ("FAULT_POLICY", "RESTORE", "MIRROR")):
                        out.append("cells: %s/%s: %s is not a regression variable" % (hold, e["cell"], k))
                continue
            args = ["bash", os.path.join(HERE, "cells_mi.sh"), os.path.join(d, hold, "raw"), e["cell"], e["build"],
                    "rs", "1", "1", "DRIVER=%s" % e["driver"]] + ["%s=%s" % kv for kv in env.items()]
            os.makedirs(os.path.join(d, hold, "raw"), exist_ok=True)
            run_env = {k: v for k, v in os.environ.items() if not k.startswith(("NCCL_", "GIN_", "RS_"))}
            run_env.update(RS_DRY_CONFIG="1", RS_SET="selftest", SUNNY_SSH="nobody@localhost", GIN_TYPE="7", NCCL_GIN_TYPE="7")
            r = subprocess.run(args, env=run_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            line = [l for l in r.stdout.splitlines() if l.startswith("cell=")]
            if r.returncode != 0 or len(line) != 1:
                out.append("cells: %s/%s: no configuration line (rc %d: %s)" % (hold, e["cell"], r.returncode,
                                                                                r.stderr.strip()[:200]))
                continue
            conf = dict(t.split("=", 1) for t in line[0].split() if "=" in t)
            for k, v in dict(env, DRIVER=e["driver"]).items():
                if k in DRAWN:
                    continue
                key = CELL_KEYS.get(k)
                if key is None:
                    out.append("cells: %s/%s: variable %s has no configuration key in this test" % (hold, e["cell"], k))
                elif conf.get(key) != v.replace(" ", "+"):
                    out.append("cells: %s/%s: %s=%s reached the runner as %s=%s" % (hold, e["cell"], k, v, key, conf.get(key)))
            if "DIE_LO" in env and conf.get("die_at", "-") == "-":
                out.append("cells: %s/%s: the seed kill did not draw a die_at" % (hold, e["cell"]))
            if "KILL2_RANK" in env and conf.get("die2_at", "-") == "-":
                out.append("cells: %s/%s: the second kill did not draw a die2_at" % (hold, e["cell"]))
            try:
                if int(conf.get("need_mb_rain", "0")) < 1024 or int(conf.get("need_mb_sunny", "0")) < 1024:
                    out.append("cells: %s/%s: the memory estimate is below the 1 GiB floor" % (hold, e["cell"]))
            except ValueError:
                out.append("cells: %s/%s: no memory estimate" % (hold, e["cell"]))
            seen += 1
    if seen == 0:
        out.append("cells: no rs cell checked")
    # the seed draw is deterministic: the same seed, cell and trial give the same die_at (run_mi.sh reads CELL from the
    # environment and the trial tag from argv[1])
    def draw(cell, trial):
        renv = {k: v for k, v in os.environ.items() if not k.startswith(("NCCL_", "GIN_", "RS_"))}
        renv.update(RS_SET="selftest", SUNNY_SSH="x", RS_DRY_CONFIG="1", CELL=cell, LIB="mi", DRIVER="gin_mi",
                    KILL_RANK="3", SPARE="1", DIE_SEED="mi-v1", DIE_LO="300", DIE_HI="1700", TRAIN="1")
        a = subprocess.run(["bash", os.path.join(HERE, "run_mi.sh"), trial, "raw"], env=renv,
                           stdout=subprocess.PIPE, universal_newlines=True)
        for l in a.stdout.splitlines():
            if l.startswith("cell="):
                return dict(t.split("=", 1) for t in l.split() if "=" in t).get("die_at")
        return None
    if draw("mi4_train_kill3", "n1") != draw("mi4_train_kill3", "n1"):
        out.append("run_mi.sh: the seed draw is not deterministic")
    if draw("mi4_train_kill3", "n1") == draw("mi4_train_kill3", "n2"):
        out.append("run_mi.sh: the seed draw does not depend on the trial")
    for v, ok in (("", False), ("i5", True), ("I5x", True), ("9a", True), ("-x", False), ("a/b", False), ("..", False),
                  ("lib", False), ("mf", False), ("mr", False)):
        r = subprocess.run(["bash", "-c", '. "$1"; rs_set_check', "_", os.path.join(HERE, "rs_set_mi.sh")],
                           env=dict(os.environ, RS_SET=v), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if (r.returncode == 0) != ok:
            out.append("rs_set_mi.sh: RS_SET=%r read as %s" % (v, "valid" if r.returncode == 0 else "invalid"))
    return out


def main():
    fails = parser_command() + cell_config_cases()
    if fails:
        print("PARSER SELFTEST FAILED:")
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PARSER SELFTEST: passed")
    sys.exit(score.selftest())


if __name__ == "__main__":
    main()
