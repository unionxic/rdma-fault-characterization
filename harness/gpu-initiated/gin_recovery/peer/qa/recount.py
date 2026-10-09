#!/usr/bin/env python3
"""gin-peer: independent recount of the main run (results/20261009) from the raw per-trial files.

Read-only: it opens the per-trial files, the hold logs, the snapshots, EXPERIMENT.md, predictions.csv, PREREG.txt and
cells.sh, and runs `git rev-parse` and `git cat-file -p <tag>:<path>` (no filter is applied by either). It writes
nothing and prints the report to stdout.

Independence. Nothing is imported from this study's score.py or rows_pq.py, or from the scorers and row extractors of
gin-harden, gin-handoff, gin-multirank, gin-s2-close or ../scripts/ts2; none of them was opened while writing this file.
Every column is parsed again from the logs and kv files. The definitions come from EXPERIMENT.md 3.1 (this study),
../harden/EXPERIMENT.md 3.1, ../handoff/EXPERIMENT.md 3.1, ../multirank/EXPERIMENT.md 3.1, ../s2_close/EXPERIMENT.md 3.1
and 3.2 (grammar), the drivers ../gin_ts2.cu and gin_mr.cu (kv keys), and the library source (log formats). Where a
document only says "as rows.py" the column is re-derived from the driver (see COLUMN NOTES at the end of the report).

usage: python3 qa/recount.py [--pilots]      (from the study folder or anywhere)
"""
import ast
import glob
import gzip
import hashlib
import os
import re
import statistics
import subprocess
import sys
from collections import Counter, OrderedDict, defaultdict

STUDY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(STUDY, "results", "20261009")
PILOTS = [os.path.join(STUDY, "results", "20261009_pilot"), os.path.join(STUDY, "results", "20261009_pilot2")]
TAG = "prereg/gin-peer-v1"

OUT = []


def p(s=""):
    OUT.append(s)


# ----------------------------------------------------------------------------------------------------------------------
# readers
# ----------------------------------------------------------------------------------------------------------------------
KV_KEY = re.compile(r"(?:^| )([A-Za-z_][A-Za-z0-9_]*)=")


def parse_kv_line(line):
    """key=value pairs; a value runs, blanks included, up to the next ' <word>='."""
    out = []
    ms = list(KV_KEY.finditer(line))
    for i, m in enumerate(ms):
        start = m.end()
        end = ms[i + 1].start() if i + 1 < len(ms) else len(line)
        out.append((m.group(1), line[start:end]))
    return out


def read_kv(path):
    d = {}
    if not os.path.exists(path):
        return None
    with open(path, errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            for k, v in parse_kv_line(line):
                if k not in d:  # first occurrence wins (no key repeats in these drivers' kv except by design)
                    d[k] = v
                else:
                    d.setdefault("__dup__" + k, []).append(v)
    return d


def read_meta(path):
    d = {}
    with open(path) as f:
        txt = f.read().strip()
    for tok in txt.split(" "):
        if "=" in tok:
            k, v = tok.split("=", 1)
            d[k] = v
    return d


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


TS_RE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]")
MSG_RE = re.compile(r"NCCL (?:WARN|INFO) (.*)$")

R = {
    "round": re.compile(r"^GIN/TS: rank (\d+): round (\d+) peer (\d+) scope=(\S+) qps=(\d+) reason=(\S+) mono_ms=([\d.]+)"),
    "rec": re.compile(r"^GIN/TS: recovered rank=(\d+) peer=(\d+) role=(initiator|responder) round=(\d+)"),
    "decl": re.compile(r'^GIN/TS: declined rank=(\d+) peer=(\d+) reason="(.*)" class=(-?\d+) mono_ms=([\d.]+)'),
    "cause": re.compile(r"^GIN/TS: rank (\d+): GIN error raised for rank (\d+) cause=(\S+)( \(firmware overrun\))? mono_ms=([\d.]+)"),
    "uapeer": re.compile(r"^GIN/TS: user devComm waits on rank (\d+) released rank=(\d+) why=(\S+) mono_ms=([\d.]+)"),
    "ua": re.compile(r"^GIN/TS: user devComm waits released rank=(\d+) why=(\S+) mono_ms=([\d.]+)"),
    "wd_new": re.compile(r"^GIN/TS: watchdog rank=(\d+): firmware command phase (\S+) has run (\d+) ms, more than "
                         r"NCCL_GIN_TS_FW_MS=(\d+); device waits on rank (\d+) are released.*?mono_ms=([\d.]+)"),
    "wd_old": re.compile(r"^GIN/TS: watchdog rank=(\d+): firmware command phase (\S+) has run (\d+) ms, more than "
                         r"NCCL_GIN_TS_FW_MS=(\d+); device waits are released"),
    "wd_any": re.compile(r"^GIN/TS: watchdog rank=(\d+):"),
    "surface": re.compile(r"^GIN/TS: watchdog rank=(\d+): (.*); the fault surfaces"),
    "planok": re.compile(r"^GIN/TS: rank (\d+): re-post plan to rank (\d+) validated: (\d+) qp\(s\), (\d+) WQE\(s\), "
                         r"role=(\w+), before this rank's commit mono_ms=([\d.]+)"),
    "planrej": re.compile(r"^GIN/TS: rank (\d+): re-post plan to rank (\d+) rejected at qp (\d+) of (\d+) \((.*)\); "
                          r"nothing re-posted mono_ms=([\d.]+)"),
    "failans": re.compile(r"^GIN/TS: rank (\d+): answered a (re-dial|probe) of declined rank (\d+) with FAIL mono_ms=([\d.]+)"),
    "peerfail": re.compile(r"^GIN/TS: rank (\d+): rank (\d+) declined this pair \(FAIL on (re-dial|probe)\) mono_ms=([\d.]+)"),
    "cancel": re.compile(r"^GIN/TS: rank (\d+): round (\d+) with rank (\d+) cancelled \(([^,]+), socket (\S+)\) before the "
                         r"commit.*mono_ms=([\d.]+)"),
    "cancel_resp": re.compile(r"^GIN/TS: rank (\d+): round (\d+) from rank (\d+) cancelled before the commit"),
    "muteon": re.compile(r"^GIN/TS: TEST socket mute on rank=(\d+) peers=(\d+) mono_ms=([\d.]+)"),
    "muteoff": re.compile(r"^GIN/TS: TEST socket mute off rank=(\d+) peers=(\d+) mono_ms=([\d.]+)"),
    "judged": re.compile(r"^GIN/TS: rank (\d+): rank (\d+) judged dead \(cause=(\S+)\) mono_ms=([\d.]+)"),
    "left": re.compile(r"^GIN/TS: rank (\d+): rank (\d+) left the communicator \(BYE\) mono_ms=([\d.]+)"),
    "copyto": re.compile(r"^GIN/TS: rank (\d+): device-state copy \(.*\) not complete after (\d+) ms \(NCCL_GIN_TS_COPY_MS\)"),
    "orphan": re.compile(r"^GIN/TS: communicator teardown rank=(\d+): the recovery helper did not stop within"),
    "hoff_ok": re.compile(r"^GIN/TS: rank (\d+): aborting shrink proceeds past the parent's GIN error, raised for "
                          r"rank\(s\) (\S+), all excluded"),
    "hoff_keep": re.compile(r"^GIN/TS: rank (\d+): aborting shrink keeps the parent's error \((.*)\) mono_ms=([\d.]+)\s*$"),
    "fired": re.compile(r"^GIN/FAULT: GDAKI fault fired.*?(?:context=(\d+) )?fire_mono_ms=([\d.]+)"),
    "trigmiss": re.compile(r"^GIN/FAULT: shot \d+ trigger not reached"),
    "ts_on": re.compile(r"^GIN/TS: transparent recovery ON rank=(\d+)"),
    "hd_on": re.compile(r"^GIN/TS: harden=1 rank=(\d+) .*production=(\d)"),
    "hf_on": re.compile(r"^GIN/TS: handoff=1 rank=(\d+) shrink_handoff=(\d)"),
    "pq_on": re.compile(r"^GIN/TS: peer=1 rank=(\d+) per_peer_words=1 fw_watchdog=per_round plan_before_commit=1 "
                        r"fail_on_reconnect=1 handoff_rule=cause refusal_forget_ms=5000"),
    "uaflag": re.compile(r"^GIN/TS: user devComm abort flag set rank=(\d+)"),
    "knobs_hd": re.compile(r"^GIN/TS: TEST harden knobs rank=(\d+) listen_gap=(\S+) bad_nonce=(\S+) fw_delay=(\S+) "
                           r"copy_stall=(\S+) bad_repost=(\S+)"),
    "knobs": re.compile(r"^GIN/TS: TEST knobs rank=(\d+) .*sock_mute=(\S+)"),
    "forgot": re.compile(r"^GIN/TS: rank (\d+): refusal by rank (\d+) from"),
    "everypeer": re.compile(r"^GIN/TS: rank (\d+): every peer of this rank is declined"),
}
CUDA_BAD = re.compile(r"illegal address|illegal memory access|unspecified launch failure", re.I)
# parse coverage: lines that contain the substring, against lines the regex parsed
COVER = [("decl", ("GIN/TS: declined rank=",)), ("cause", ("GIN error raised for rank",)),
         ("uapeer", ("user devComm waits on rank",)), ("ua", ("user devComm waits released rank=",)),
         ("planok", ("validated:",)), ("planrej", ("rejected at qp",)), ("failans", ("with FAIL mono_ms",)),
         ("peerfail", ("declined this pair (FAIL on", ") mono_ms=")), ("wd_any", ("GIN/TS: watchdog rank=",)),
         ("hoff_ok", ("aborting shrink proceeds",)), ("hoff_keep", ("aborting shrink keeps",)),
         ("fired", ("GDAKI fault fired",)), ("rec", ("GIN/TS: recovered rank=",)), ("round", (": round ", " peer ", "reason=")),
         ("cancel", ("before the commit; the fault is retried",)), ("muteoff", ("TEST socket mute off",)),
         ("judged", ("judged dead (cause=",)), ("copyto", ("(NCCL_GIN_TS_COPY_MS)",)), ("pq_on", ("GIN/TS: peer=1 rank=",)),
         ("uaflag", ("abort flag set rank=",)), ("ts_on", ("transparent recovery ON rank=",))]
COVER_RAW = Counter()
COVER_PARSED = Counter()


class Log:
    """Every parsed event of one rank's log, in order."""

    def __init__(self, path):
        self.path = path
        self.exists = os.path.exists(path)
        self.ev = defaultdict(list)
        self.first_ts = None
        self.last_ts = None
        self.bind = 0
        self.cuda_bad = 0
        self.watchdog_exit = []
        self.done = None
        self.n_lines = 0
        self.raw = Counter()
        if not self.exists:
            return
        with open(path, errors="replace") as f:
            for line in f:
                self.n_lines += 1
                if line[:1] == "[":
                    m = TS_RE.match(line)
                    if m:
                        if self.first_ts is None:
                            self.first_ts = m.group(1)
                        self.last_ts = m.group(1)
                if "bind" in line and "Address already in use" in line:
                    self.bind += 1
                if line.startswith("WATCHDOG:"):
                    self.watchdog_exit.append(line.strip())
                if "DONE outcome=" in line and line.startswith("[rank"):
                    self.done = line.strip()
                if "GIN/" not in line:
                    if CUDA_BAD.search(line):
                        self.cuda_bad += 1
                    continue
                if CUDA_BAD.search(line):
                    self.cuda_bad += 1
                m = MSG_RE.search(line)
                if not m:
                    continue
                msg = m.group(1).rstrip()
                for k, rx in R.items():
                    mm = rx.match(msg)
                    if mm:
                        self.ev[k].append(mm.groups())
                for k, subs in COVER:
                    if all(s in msg for s in subs):
                        self.raw[k] += 1

    def n(self, k):
        return len(self.ev[k])


def kvf(kv, key):
    if kv is None:
        return None
    v = kv.get(key)
    return v


# ----------------------------------------------------------------------------------------------------------------------
# section 7: the plan (cell key -> planned trials), the hook and kill ranks, and cells.sh's arguments
# ----------------------------------------------------------------------------------------------------------------------
PLAN2 = OrderedDict([
    ("pq_repost_r1_b@hq", 10), ("pq_repost_r1_b@hf", 5), ("hd_repost_f1_b@hq", 5), ("hd_fwslow_f1_b@hq", 5),
    ("pq_ackrace_f1_b@hq", 10), ("pq_ackrace_f1_b@hf", 5), ("pq_ackrace_f1r1_b@hq", 5), ("pq_ackrace_f1r1_b@hf", 5),
    ("pq_copystall_shrink_b@hq", 10), ("pq_copystall_shrink_b@hf", 5), ("pq_copystall1_shrink_b@hq", 5),
    ("hd_shrink_b@hq", 5), ("pq_rdv_b@hq", 5),
    ("f1_b@hq", 5), ("f3_b@hq", 5), ("bidirf_sym_b@hq", 5), ("f4_b@hq", 5), ("f2rel_b@hq", 5), ("hd_rxdeath_b@hq", 5),
    ("hdp_kill_b@hqp", 5),
    ("lat_4k@hqp", 5), ("lat_4k@hfp", 5), ("lat_256k@hqp", 5), ("lat_256k@hfp", 5),
])
PLAN4 = OrderedDict([
    ("mr4_kill3_peer@hq", 10), ("mr4_kill3_peer@hf", 5), ("mr4_kill3@hq", 5), ("pq4_fwslow@hq", 10), ("pq4_fwslow@hf", 5),
    ("pq4_kill3_shrink@hq", 10), ("pq4_local_shrink@hq", 5), ("pq4_local_shrink@hf", 5), ("pq4_rdv@hq", 3),
    ("mr4_none@hq", 5), ("mr4_f1_01@hq", 5),
])
PLAN = OrderedDict(list(PLAN2.items()) + list(PLAN4.items()))
FW_CELLS = {"hd_fwslow_f1_b", "pq4_fwslow"}
FIRES4 = {"mr4_f1_01": "0:0", "pq4_local_shrink": "0:0", "pq4_fwslow": "0:0;2:6"}
COPY_RANK = {"pq_copystall_shrink_b": 0, "pq_copystall1_shrink_b": 1, "pq4_local_shrink": 0}
RACE = {"pq_ackrace_f1_b": (0, 1), "pq_ackrace_f1r1_b": (1, 0)}  # (muted rank = initiator, responder)


def expected_args2(cell, k):
    """the arguments cells.sh gives trial n<k> of a two-rank cell (only the ones the meta line records)"""
    inj = 500 + (k * 137) % 700
    BIDIR = "GIN_TS_BIDIR_FUSED=1"
    e = {}
    if cell == "f1_b":
        e = dict(app="default", fault="F1", iters="120", bytes="262144", inject=str(inj), r0env="", r1env="", extra="")
    elif cell == "f3_b":
        e = dict(app="default", fault="F3", iters="120", bytes="262144", inject=str(inj), r0env="", r1env="", extra="")
    elif cell == "bidirf_sym_b":
        i0 = 60 + (k * 7) % 50
        e = dict(app="bidir", fault="F1both", iters="8000", bytes="4096", inject=str(i0), inject1=str(i0 - 1 - k % 2),
                 extra=BIDIR, gap_us="0", r0env="", r1env="")
    elif cell in ("f4_b", "hdp_kill_b"):
        e = dict(app="default", fault="F4", iters="200", bytes="262144", gap_us="30000",
                 kill_delay_ms=str(3500 + (k * 211) % 900), r0env="", r1env="", extra="")
    elif cell == "f2rel_b":
        e = dict(app="default", fault="F2", iters="120", bytes="262144",
                 extra="GIN_TS_RX_WAIT_S=20+GIN_TS_POST_ABORT_WAIT_S=3+NCCL_GIN_TS_USER_ABORT=1", r0env="", r1env="")
    elif cell == "hd_rxdeath_b":
        e = dict(app="default", fault="none", iters="1000", bytes="16384", kill_r0="1", kill_delay_ms="3000",
                 extra="GIN_TS_RX_WAIT_S=15", r0env="", r1env="")
    elif cell in ("lat_4k", "lat_256k"):
        e = dict(app="default", fault="lat", iters="3000", bytes="4096" if cell == "lat_4k" else "262144", gap_us="0",
                 r0env="", r1env="", extra="")
    elif cell == "pq_repost_r1_b":
        e = dict(app="bidir", fault="F1", iters="400", bytes="16384", inject=str(inj),
                 extra=BIDIR + "+NCCL_GIN_TS_PAIR_RESET=0+GIN_TS_RX_WAIT_S=10", r0env="", r1env="NCCL_GIN_TS_TEST_BAD_REPOST=1")
    elif cell == "hd_repost_f1_b":
        e = dict(app="bidir", fault="F1", iters="400", bytes="16384", inject=str(inj),
                 extra=BIDIR + "+NCCL_GIN_TS_PAIR_RESET=0+GIN_TS_RX_WAIT_S=10", r0env="NCCL_GIN_TS_TEST_BAD_REPOST=1", r1env="")
    elif cell == "hd_fwslow_f1_b":
        e = dict(app="default", fault="F1", iters="120", bytes="262144", inject=str(inj),
                 r0env="NCCL_GIN_TS_TEST_FW_DELAY=8000@commit", r1env="", extra="")
    elif cell == "pq_ackrace_f1_b":
        e = dict(app="default", fault="F1", iters="1000", bytes="16384", inject="1500", extra="GIN_TS_RX_WAIT_S=10",
                 r0env="NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000", r1env="GIN_TS_END_WAIT_S=12")
    elif cell == "pq_ackrace_f1r1_b":
        e = dict(app="bidir", fault="none", iters="1000", bytes="16384", gap_us="15000", extra=BIDIR + "+GIN_TS_RX_WAIT_S=30",
                 r0env="GIN_TS_END_WAIT_S=12",
                 r1env="NCCL_GIN_FAULT_INJECT=local_err:1500+NCCL_GIN_FAULT_INJECT_CTX=1+NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000")
    elif cell == "pq_copystall_shrink_b":
        e = dict(app="default", fault="F1", iters="120", bytes="262144", inject=str(inj),
                 r0env="NCCL_GIN_TS_TEST_COPY_STALL=4000+GIN_TS_SHRINK=1+GIN_TS_HO_WAIT_S=3", r1env="", extra="")
    elif cell == "pq_copystall1_shrink_b":
        e = dict(app="default", fault="F1", iters="120", bytes="262144", inject=str(inj),
                 r0env="GIN_TS_SHRINK=1+GIN_TS_HO_WAIT_S=3", r1env="NCCL_GIN_TS_TEST_COPY_STALL=4000", extra="")
    elif cell == "hd_shrink_b":
        e = dict(app="bidir", fault="F4", iters="400", bytes="16384", kill_delay_ms="3500",
                 extra=BIDIR + "+GIN_TS_RX_WAIT_S=60",
                 r0env="GIN_TS_SHRINK=1+GIN_TS_HO_WAIT_S=3+GIN_TS_POST_ABORT_WAIT_S=10", r1env="")
    elif cell == "pq_rdv_b":
        e = dict(app="default", fault="F1", iters="120", bytes="262144", inject=str(inj), r0env="", r1env="", extra="")
    e["ts"] = "1"
    return e


def expected_args4(cell, k):
    BASE = "GIN_TS_RX_WAIT_S=10"
    hook0 = "NCCL_GIN_FAULT_INJECT=local_err:6000+NCCL_GIN_FAULT_INJECT_CTX=0"
    e = dict(n="4", iters="1000", bytes="4096", mode="none", edges="all", r0env="", r1env="", r2env="", r3env="",
             kill_rank="", kill_delay_ms="", flush="ctx")
    if cell == "mr4_kill3_peer":
        e.update(kill_rank="3", kill_delay_ms="9000", flush="peer", extra=BASE + "+GIN_MR_GRACE_S=40")
    elif cell == "mr4_kill3":
        e.update(kill_rank="3", kill_delay_ms="9000", extra=BASE + "+GIN_MR_GRACE_S=40")
    elif cell == "pq4_fwslow":
        e.update(flush="peer", extra=BASE + "+GIN_MR_GRACE_S=40", r0env=hook0 + "+NCCL_GIN_TS_TEST_FW_DELAY=4000@commit",
                 r2env="NCCL_GIN_FAULT_INJECT=local_err:11500+NCCL_GIN_FAULT_INJECT_CTX=6")
    elif cell == "pq4_kill3_shrink":
        e.update(kill_rank="3", kill_delay_ms="9000", flush="peer",
                 extra=BASE + "+GIN_MR_GRACE_S=40+GIN_MR_SHRINK=3+GIN_MR_CHILD=1+GIN_MR_PHASE_S=40")
    elif cell == "pq4_local_shrink":
        e.update(flush="peer", extra=BASE + "+GIN_MR_GRACE_S=40+GIN_MR_SHRINK=1+GIN_MR_PHASE_S=12",
                 r0env=hook0 + "+NCCL_GIN_TS_TEST_COPY_STALL=4000")
    elif cell == "pq4_rdv":
        e.update(extra=BASE)
    elif cell == "mr4_none":
        e.update(extra=BASE)
    elif cell == "mr4_f1_01":
        e.update(extra=BASE, r0env=hook0)
    e["ts"] = "1"
    return e


# ----------------------------------------------------------------------------------------------------------------------
# two-rank trials
# ----------------------------------------------------------------------------------------------------------------------
def first(lst, i=None):
    if not lst:
        return None
    return lst[0] if i is None else lst[0][i]


def env_has(meta, r, s):
    return s in (meta.get("r%denv" % r, "") or "")


def hooked_ranks2(meta):
    f = meta.get("fault", "")
    hr = set()
    if f in ("F1",):
        hr.add(0)
    if f == "F3":
        hr.add(1)
    if f == "F1both":
        hr |= {0, 1}
    for r in (0, 1):
        if env_has(meta, r, "NCCL_GIN_FAULT_INJECT="):
            hr.add(r)
    return hr


def row2(folder, stem):
    meta = read_meta(os.path.join(folder, stem + "_meta.txt"))
    kv = [read_kv(os.path.join(folder, "%s_r%d.kv" % (stem, r))) for r in (0, 1)]
    lg = [Log(os.path.join(folder, "%s_r%d.log" % (stem, r))) for r in (0, 1)]
    killf = os.path.join(folder, stem + "_kill.out")
    kill = read_kv(killf) if os.path.exists(killf) else None
    decf = os.path.join(folder, stem + "_decoy.out")
    dec = read_kv(decf) if os.path.exists(decf) else None
    rawf = os.path.join(folder, stem + "_lat_raw.csv.gz")
    x = OrderedDict()
    x["kind"] = 2
    x["folder"] = os.path.basename(folder)
    x["stem"] = stem
    x["cell"] = meta.get("cell")
    x["build"] = meta.get("build")
    x["trial"] = meta.get("trial")
    x["key"] = "%s@%s" % (x["cell"], x["build"])
    x["_meta"], x["_kv"], x["_lg"], x["_kill"] = meta, kv, lg, kill
    x["r0rc"], x["r1rc"] = fnum(meta.get("r0rc")), fnum(meta.get("r1rc"))
    x["left"] = fnum(meta.get("left"))
    x["wall_s"] = fnum(meta.get("wall_s"))
    iters = int(meta.get("iters", "0"))
    # ---- common (rows.py meanings, re-derived from the driver) ----
    x["bind_fail"] = 1 if (lg[0].bind or lg[1].bind) else 0
    x["killed"] = 1 if (kill and kill.get("kill_mono_ms")) else 0
    for r in (0, 1):
        x["n_fires_r%d" % r] = lg[r].n("fired")
        x["ts_on_r%d" % r] = lg[r].n("ts_on")
        x["hd_on_r%d" % r] = 1 if lg[r].n("hd_on") else 0
        x["prod_r%d" % r] = fnum(first(lg[r].ev["hd_on"], 1))
        x["hf_on_r%d" % r] = 1 if lg[r].n("hf_on") else 0
        x["pq_on_r%d" % r] = 1 if lg[r].n("pq_on") else 0
        x["ua_r%d" % r] = lg[r].n("uaflag")
        k = kv[r] or {}
        x["r%d_outcome" % r] = k.get("outcome")
        x["r%d_async" % r] = k.get("async_first")
        x["teardown_r%d" % r] = k.get("abort_ret")
        x["teardown_ms_r%d" % r] = fnum(k.get("teardown_ms"))
        for s in ("api", "rounds", "recovered", "declined", "deaths", "fw_overruns", "contexts", "copy_timeouts",
                  "cancelled", "reconnects"):
            x["rs_%s_r%d" % (s, r)] = fnum(k.get("rs_" + s))
        x["rx_phantom_r%d" % r] = fnum(k.get("rx_phantom"))
        x["rdv_r%d" % r] = k.get("rdv")
        decl = lg[r].ev["decl"]
        x["decl_r%d" % r] = ";".join(d[2] for d in decl) if decl else None
        x["n_decl_r%d" % r] = len(decl)
        x["declwhy_r%d" % r] = decl[0][2] if decl else None
        x["decl_ms_r%d" % r] = float(decl[0][4]) if decl else None
        x["decl_peer_r%d" % r] = decl[0][1] if decl else None
        x["n_init_round_r%d" % r] = lg[r].n("round")
        recs = lg[r].ev["rec"]
        x["rec_init_r%d" % r] = sum(1 for q in recs if q[2] == "initiator")
        x["rec_resp_r%d" % r] = sum(1 for q in recs if q[2] == "responder")
        x["n_planok_r%d" % r] = lg[r].n("planok")
        x["planok_role_r%d" % r] = first(lg[r].ev["planok"], 4)
        x["planok_wqe_r%d" % r] = fnum(first(lg[r].ev["planok"], 3))
        x["n_planrej_r%d" % r] = lg[r].n("planrej")
        x["planrej_qp_r%d" % r] = fnum(first(lg[r].ev["planrej"], 2))
        x["planrej_total_r%d" % r] = fnum(first(lg[r].ev["planrej"], 3))
        wn = lg[r].ev["wd_new"]
        x["n_fwover_r%d" % r] = len(wn)
        x["fwover_phase_r%d" % r] = wn[0][1] if wn else None
        x["fwover_ms_r%d" % r] = fnum(wn[0][2]) if wn else None
        x["fwover_peer_r%d" % r] = wn[0][4] if wn else None
        x["n_fwold_r%d" % r] = lg[r].n("wd_old")
        x["n_wd_any_r%d" % r] = lg[r].n("wd_any")
        x["n_surface_r%d" % r] = lg[r].n("surface")
        ua = lg[r].ev["ua"]
        x["n_uarel_r%d" % r] = len(ua)
        x["uarel_why_r%d" % r] = ua[0][1] if ua else None
        uae = [q for q in ua if q[1] in ("declined", "peer-dead", "fw-watchdog")]
        x["n_uaerr_r%d" % r] = len(uae)
        x["uaerr_why_r%d" % r] = uae[0][1] if uae else None
        up = lg[r].ev["uapeer"]
        x["n_uapeer_r%d" % r] = len(up)
        x["uapeer_r%d" % r] = ";".join("%s-%s" % (q[1], q[0]) for q in up) if up else None
        cs = lg[r].ev["cause"]
        x["causes_r%d" % r] = ";".join("%s:%s" % (q[1], q[2]) for q in cs) if cs else None
        x["cause_r%d" % r] = cs[0][2] if cs else None
        fa = lg[r].ev["failans"]
        x["n_failans_r%d" % r] = len(fa)
        x["failans_r%d" % r] = ";".join(q[1] for q in fa) if fa else None
        pf = lg[r].ev["peerfail"]
        x["n_peerfail_r%d" % r] = len(pf)
        x["peerfail_r%d" % r] = ";".join(q[2] for q in pf) if pf else None
        ca = [q for q in lg[r].ev["cancel"] if q[3] == "waiting for ACK"]
        x["n_cancel_ack_r%d" % r] = len(ca)
        x["cancel_ms_r%d" % r] = float(ca[0][5]) if ca else None
        x["n_cancel_r%d" % r] = lg[r].n("cancel") + lg[r].n("cancel_resp")
        mo = lg[r].ev["muteoff"]
        x["muteoff_ms_r%d" % r] = float(mo[0][2]) if mo else None
        x["decl_after_unmute_ms_r%d" % r] = (x["decl_ms_r%d" % r] - x["muteoff_ms_r%d" % r]
                                              if x["decl_ms_r%d" % r] is not None and x["muteoff_ms_r%d" % r] is not None
                                              else None)
        x["n_judged_r%d" % r] = lg[r].n("judged")
        x["n_copyto_r%d" % r] = lg[r].n("copyto")
        x["n_orphan_r%d" % r] = lg[r].n("orphan")
        x["n_hoff_ok_r%d" % r] = lg[r].n("hoff_ok")
        x["hoff_ranks_r%d" % r] = first(lg[r].ev["hoff_ok"], 1)
        x["n_hoff_keep_r%d" % r] = lg[r].n("hoff_keep")
        x["hoff_why_r%d" % r] = first(lg[r].ev["hoff_keep"], 1)
        kh = lg[r].ev["knobs_hd"]
        x["knobs_hd_r%d" % r] = (" ".join(kh[0][1:]) if kh else None)
        x["hk_fwdelay_r%d" % r] = kh[0][3] if kh else None
        x["hk_copystall_r%d" % r] = kh[0][4] if kh else None
        x["hk_badrepost_r%d" % r] = kh[0][5] if kh else None
        kn = lg[r].ev["knobs"]
        x["sock_mute_r%d" % r] = kn[0][1] if kn else None
        x["end_wait_r%d" % r] = 1 if env_has(meta, r, "GIN_TS_END_WAIT_S=12") else 0
        x["cuda_bad_r%d" % r] = lg[r].cuda_bad
    x["trigger_miss"] = lg[0].n("trigmiss") + lg[1].n("trigmiss")
    x["n_rec_any"] = len(lg[0].ev["rec"]) + len(lg[1].ev["rec"])
    x["uapeer"] = ";".join(v for v in (x["uapeer_r0"], x["uapeer_r1"]) if v) or None
    x["n_uaerr"] = x["n_uaerr_r0"] + x["n_uaerr_r1"]
    x["tx_rc"] = (kv[0] or {}).get("tx_rc")
    x["rx_rc"] = (kv[1] or {}).get("rx_rc")
    x["lat_p50_us"] = fnum((kv[0] or {}).get("lat_p50_us"))
    # shrink hand-off kv (rank 0)
    for k in ("ho_newcomm", "ho_shrink_rc", "ho_newcomm_nranks", "ho_check_ok", "ho_shrink_ms", "ho_parent_async_after",
              "ho_allreduce_rc"):
        v = (kv[0] or {}).get(k)
        x[k] = fnum(v) if k in ("ho_newcomm", "ho_newcomm_nranks", "ho_check_ok", "ho_shrink_ms") else v
    # transparent_ok (driver header: every flush ncclSuccess and all iterations ran, every slot bit-exact on the device and
    # the host, every final signal exact, no host saw an async error)
    tok = 1
    for r in (0, 1):
        k = kv[r]
        if not k:
            tok = 0
            continue
        sender = (r == 0) or meta.get("app") == "bidir"
        receiver = (r == 1) or meta.get("app") == "bidir"
        if sender and not (k.get("tx_done") == str(iters) and k.get("tx_rc") == "no error"):
            tok = 0
        if receiver and not (k.get("rx_done") == str(iters) and k.get("rx_rc") == "no error" and k.get("dev_bad_slots") == "0"
                             and k.get("host_bad_slots") == "0" and k.get("signal_exact") == "1"):
            tok = 0
        if k.get("async_first") != "none":
            tok = 0
    x["transparent_ok"] = tok
    x["transparent_alt"] = 1 if (x["r0rc"] == 0 and x["r1rc"] == 0 and x["r0_outcome"] == "ok" and x["r1_outcome"] == "ok") else 0
    # clocks: rank 0 kv clock_offset_ms = rank 1 - rank 0
    off = fnum((kv[0] or {}).get("clock_offset_ms"))
    x["clock_offset_ms"] = off
    kms = fnum(kill.get("kill_mono_ms")) if kill else None
    x["kill_mono_ms"] = kms
    x["decl_after_kill_ms_r0"] = None
    x["release_after_kill_ms_r1"] = None
    x["async_after_kill_ms_r1"] = None
    if kms is not None and off is not None:
        if meta.get("kill_r0") == "1":  # rank 0 killed (on rain): its kill time on rank 1's clock
            k1 = kv[1] or {}
            k_r1 = kms + off
            la, km, af = fnum(k1.get("launch_mono_ms")), fnum(k1.get("kernel_ms")), fnum(k1.get("async_first_ms_after_launch"))
            if la is not None and km is not None:
                x["release_after_kill_ms_r1"] = la + km - k_r1
            if la is not None and af is not None and k1.get("async_first") not in (None, "none"):
                x["async_after_kill_ms_r1"] = la + af - k_r1
        else:  # rank 1 killed (on sunny): its kill time on rank 0's clock
            k_r0 = kms - off
            if x["decl_ms_r0"] is not None:
                x["decl_after_kill_ms_r0"] = x["decl_ms_r0"] - k_r0
            x["judged_after_kill_ms_r0"] = (float(lg[0].ev["judged"][0][3]) - k_r0) if lg[0].ev["judged"] else None
    # port fix
    x["port"] = fnum(meta.get("port"))
    x["port_tries"] = fnum(meta.get("port_tries"))
    x["port_skipped"] = meta.get("port_skipped")
    x["occupy_port"] = meta.get("occupy_port")
    x["occupy_skipped"] = fnum(meta.get("occupy_skipped"))
    x["decoy_port"] = meta.get("decoy_port")
    x["rdv_decoy_r1"] = (kv[1] or {}).get("rdv_decoy")
    x["rdv_rejected_r1"] = fnum((kv[1] or {}).get("rdv_rejected"))
    x["rdv_foreign_r0"] = fnum((kv[0] or {}).get("rdv_foreign"))
    x["decoy_conns"] = fnum(dec.get("decoy_conns")) if dec else None
    x["decoy_bytes"] = fnum(dec.get("decoy_bytes")) if dec else None
    x["first_ts"] = min([t for t in (lg[0].first_ts, lg[1].first_ts) if t] or [None]) if (lg[0].first_ts or lg[1].first_ts) else None
    x["last_ts"] = max([t for t in (lg[0].last_ts, lg[1].last_ts) if t]) if (lg[0].last_ts or lg[1].last_ts) else None
    # latency raw p50 (driver rule v[int(0.5 (n-1) + 0.5)])
    x["lat_raw_p50_us"] = None
    x["lat_raw_n"] = None
    if os.path.exists(rawf):
        with gzip.open(rawf, "rt") as f:
            v = sorted(int(l.split(",")[1]) for l in f if "," in l)
        if v:
            x["lat_raw_n"] = len(v)
            x["lat_raw_p50_us"] = v[int(0.5 * (len(v) - 1) + 0.5)] / 1e3
    x["hooked"] = sorted(hooked_ranks2(meta))
    x["rc139"] = 1 if ("139" in (meta.get("r0rc"), meta.get("r1rc"))) else 0
    return x


# ----------------------------------------------------------------------------------------------------------------------
# N-rank trials
# ----------------------------------------------------------------------------------------------------------------------
def row4(folder, stem):
    meta = read_meta(os.path.join(folder, stem + "_meta.txt"))
    N = int(meta.get("n", "4"))
    kv = [read_kv(os.path.join(folder, "%s_r%d.kv" % (stem, r))) for r in range(N)]
    lg = [Log(os.path.join(folder, "%s_r%d.log" % (stem, r))) for r in range(N)]
    killf = os.path.join(folder, stem + "_kill.out")
    kill = read_kv(killf) if os.path.exists(killf) else None
    decf = os.path.join(folder, stem + "_decoy.out")
    dec = read_kv(decf) if os.path.exists(decf) else None
    iters = int(meta.get("iters", "0"))
    gap = float(meta.get("gap_us", "0"))
    x = OrderedDict()
    x["kind"] = 4
    x["folder"] = os.path.basename(folder)
    x["stem"] = stem
    x["cell"] = meta.get("cell")
    x["build"] = meta.get("lib")
    x["trial"] = meta.get("trial")
    x["key"] = "%s@%s" % (x["cell"], x["build"])
    x["_meta"], x["_kv"], x["_lg"], x["_kill"] = meta, kv, lg, kill
    x["n"] = N
    x["iters"] = iters
    x["wall_s"] = fnum(meta.get("wall_s"))
    x["left"] = fnum(meta.get("left"))
    rcs = [fnum(meta.get("r%drc" % r)) for r in range(N)]
    x["rcs"] = rcs
    off = [0.0] * N
    k0 = kv[0] or {}
    for r in range(1, N):
        off[r] = fnum(k0.get("clock_offset_ms_r%d" % r))
    x["bind_fail"] = 1 if any(l.bind for l in lg) else 0
    x["trigger_miss"] = sum(l.n("trigmiss") for l in lg)
    # edges
    def edge_ok(a, b):
        ka, kb = kv[a] or {}, kv[b] or {}
        t = "tx_%d%d_" % (a, b)
        rr = "rx_%d%d_" % (a, b)
        return (ka.get(t + "done") == str(iters) and ka.get(t + "rc") == "no error" and kb.get(rr + "done") == str(iters)
                and kb.get(rr + "rc") == "no error" and kb.get(rr + "devbad") == "0" and kb.get(rr + "hostbad") == "0"
                and kb.get(rr + "sigexact") == "1")
    edges = [(a, b) for a in range(N) for b in range(N) if a != b]
    ok = {e: edge_ok(*e) for e in edges}
    x["_edge_ok"] = ok
    bad = sorted("%d>%d" % e for e in edges if not ok[e])
    x["edges_bad"] = ";".join(bad) if bad else None
    x["n_edges_bad"] = len(bad)
    ar = [r for r in range(N) if kv[r] and kv[r].get("async_first") not in (None, "none")]
    x["async_ranks"] = ",".join("r%d" % r for r in ar) if ar else None
    outs = [(kv[r] or {}).get("outcome") for r in range(N)]
    x["outcomes"] = outs
    x["transparent_ok"] = 1 if (all(ok.values()) and all(o == "ok" for o in outs) and not ar) else 0
    # fires
    fires = []
    fin = 1
    for r in range(N):
        la = fnum((kv[r] or {}).get("launch_mono_ms"))
        for g in lg[r].ev["fired"]:
            fires.append("%d:%s" % (r, g[0] if g[0] is not None else "all"))
            t = float(g[1])
            if la is None or not (la < t < la + iters * gap / 1000.0):
                fin = 0
    x["fires"] = ";".join(sorted(fires)) if fires else None
    x["fire_in_traffic"] = fin if fires else None
    # rounds, recoveries, declines, causes, words
    x["rounds"] = ";".join(sorted("%s>%s:%s:%s" % (g[0], g[2], g[4], g[5]) for l in lg for g in l.ev["round"])) or None
    rec = [(g[0], g[1], g[2]) for l in lg for g in l.ev["rec"]]
    x["rec_i"] = ";".join(sorted("%s-%s" % (a, b) for a, b, c in rec if c == "initiator")) or None
    x["rec_r"] = ";".join(sorted("%s-%s" % (a, b) for a, b, c in rec if c == "responder")) or None
    x["rec_20"] = sum(1 for a, b, c in rec if a == "2" and b == "0" and c == "initiator")
    x["rec_02"] = sum(1 for a, b, c in rec if a == "0" and b == "2" and c == "responder")
    dl = [(g[0], g[1], g[2], float(g[4])) for l in lg for g in l.ev["decl"]]
    x["decl"] = ";".join(sorted("%s-%s" % (a, b) for a, b, _, _ in dl)) or None
    x["decl_reasons"] = ";".join(sorted("%s-%s=%s" % (a, b, w) for a, b, w, _ in dl)) or None
    x["n_decl"] = len(dl)
    x["n_hs"] = sum(1 for d in dl if d[2] == "handshake timeout")
    up = [(g[1], g[0], g[2]) for l in lg for g in l.ev["uapeer"]]
    x["uapeer"] = ";".join(sorted("%s-%s" % (a, b) for a, b, _ in up)) or None
    x["uapeer_why"] = ";".join(sorted("%s-%s:%s" % u for u in up)) or None
    uae = [(g[0], g[1]) for l in lg for g in l.ev["ua"] if g[1] in ("declined", "peer-dead", "fw-watchdog")]
    x["n_uaerr"] = len(uae)
    x["uaerr"] = ";".join(sorted("%s:%s" % u for u in uae)) or None
    wn = [(g[0], g[4], g[1], float(g[2])) for l in lg for g in l.ev["wd_new"]]
    x["fwover"] = ";".join(sorted("%s-%s:%s" % (a, b, c) for a, b, c, _ in wn)) or None
    x["fwover_ms"] = ";".join("%.0f" % w[3] for w in wn) or None
    x["n_fwold"] = sum(l.n("wd_old") for l in lg)
    x["n_wd_any"] = sum(l.n("wd_any") for l in lg)
    x["n_surface"] = sum(l.n("surface") for l in lg)
    cs = [(g[0], g[1], g[2], g[3] is not None) for l in lg for g in l.ev["cause"]]
    x["causes"] = ";".join("%s-%s:%s%s" % (a, b, c, "(fw)" if f else "") for a, b, c, f in cs) or None
    x["n_cause_peerdead"] = sum(1 for c in cs if c[2] == "peer-dead")
    x["n_cause_local"] = sum(1 for c in cs if c[2] == "local")
    x["n_pq_on"] = sum(1 for l in lg if l.n("pq_on"))
    x["n_pq_on_lines"] = sum(l.n("pq_on") for l in lg)
    x["n_ts_on"] = sum(l.n("ts_on") for l in lg)
    x["n_ua"] = sum(l.n("uaflag") for l in lg)
    x["n_hd"] = sum(l.n("hd_on") for l in lg)
    x["n_hf"] = sum(l.n("hf_on") for l in lg)
    x["n_copyto_r0"] = lg[0].n("copyto")
    x["n_judged"] = sum(l.n("judged") for l in lg)
    x["knobs_hd"] = ";".join("%d:%s" % (r, " ".join(lg[r].ev["knobs_hd"][0][1:])) for r in range(N) if lg[r].ev["knobs_hd"]) or None
    # kill
    kms = fnum(kill.get("kill_mono_ms")) if kill else None
    x["killed"] = 1 if kms is not None else 0
    kr = int(meta["kill_rank"]) if meta.get("kill_rank") else None
    x["kill_rank"] = kr
    x["kill_ms0"] = (kms - off[kr]) if (kms is not None and kr is not None and off[kr] is not None) else None
    if x["kill_ms0"] is not None:
        launches = [fnum((kv[r] or {}).get("launch_mono_ms")) for r in range(N)]
        l0 = [launches[r] - off[r] for r in range(N) if launches[r] is not None]
        ends = [launches[r] - off[r] + iters * gap / 1000.0 for r in range(N) if launches[r] is not None]
        x["kill_after_last_launch_ms"] = x["kill_ms0"] - max(l0)
        x["kill_before_traffic_end_ms"] = min(ends) - x["kill_ms0"]
        x["kill_in_traffic"] = 1 if (len(l0) == N and x["kill_ms0"] > max(l0) and min(ends) - x["kill_ms0"] >= 5000) else 0
    else:
        x["kill_in_traffic"] = None
    for r in range(N):
        d = lg[r].ev["decl"]
        x["decl_after_kill_ms_r%d" % r] = (float(d[0][4]) - off[r] - x["kill_ms0"]) if (d and x["kill_ms0"] is not None) else None
        j = lg[r].ev["judged"]
        x["judged_after_kill_ms_r%d" % r] = (float(j[0][3]) - off[r] - x["kill_ms0"]) if (j and x["kill_ms0"] is not None) else None
        # same-clock gap from 'judged dead' to the decline of that peer (rank r's own clock)
        x["decl_after_judged_ms_r%d" % r] = (float(d[0][4]) - float(j[0][3])) if (d and j) else None
        k = kv[r] or {}
        la, km = fnum(k.get("launch_mono_ms")), fnum(k.get("kernel_ms"))
        x["kend_after_kill_ms_r%d" % r] = ((la + km - off[r]) - x["kill_ms0"]) if (
            la is not None and km is not None and x["kill_ms0"] is not None) else None
        af = fnum(k.get("async_first_ms_after_launch"))
        x["async_after_kill_ms_r%d" % r] = ((la + af - off[r]) - x["kill_ms0"]) if (
            la is not None and af is not None and k.get("async_first") not in (None, "none") and x["kill_ms0"] is not None) else None
    # survivors
    if kr is not None:
        se = [e for e in edges if kr not in e]
        x["n_surv_edges"] = len(se)
        x["surv_edges_ok"] = sum(1 for e in se if ok[e])
        x["surv_tx_failed"] = sum(1 for a, b in se if (kv[a] or {}).get("tx_%d%d_rc" % (a, b)) != "no error")
        x["surv_rx_failed"] = sum(1 for a, b in se if (kv[b] or {}).get("rx_%d%d_rc" % (a, b)) != "no error")
        x["surv_rx_timeout"] = sum(1 for a, b in se if (kv[b] or {}).get("rx_%d%d_rc" % (a, b)) == "timeout")
        x["surv_tx_rc"] = ";".join(sorted(set((kv[a] or {}).get("tx_%d%d_rc" % (a, b)) or "-" for a, b in se)))
        x["surv_rx_rc"] = ";".join(sorted(set((kv[b] or {}).get("rx_%d%d_rc" % (a, b)) or "-" for a, b in se)))
        x["dead_tx_failed"] = sum(1 for a in range(N) if a != kr and (kv[a] or {}).get("tx_%d%d_rc" % (a, kr)) != "no error")
        x["dead_rx_timeout"] = sum(1 for b in range(N) if b != kr and (kv[b] or {}).get("rx_%d%d_rc" % (kr, b)) == "timeout")
        x["dead_rx_rc"] = ";".join(sorted(set((kv[b] or {}).get("rx_%d%d_rc" % (kr, b)) or "-" for b in range(N) if b != kr)))
    x["n_bad_0_23"] = sum(1 for e in [(0, 2), (0, 3), (2, 0), (3, 0)] if e in ok and not ok[e])
    # hand-off and the child phase
    x["n_hoff_ok"] = sum(l.n("hoff_ok") for l in lg)
    x["n_hoff_keep"] = sum(l.n("hoff_keep") for l in lg)
    x["keep_why_r0"] = first(lg[0].ev["hoff_keep"], 1)
    chs = [(kv[r] or {}) for r in range(N)]
    x["ch_outcomes"] = ";".join("%d:%s" % (r, chs[r].get("ch_outcome") or "-") for r in range(N))
    x["ch_ok_ranks"] = sum(1 for c in chs if c.get("ch_outcome") == "ok")
    x["ch_created_ranks"] = sum(1 for c in chs if fnum(c.get("ch_nranks")) == N - 1)
    x["ch_timeout_ranks"] = sum(1 for c in chs if c.get("ch_outcome") == "timeout")
    x["ch_shrink_fail_r0"] = 1 if chs[0].get("ch_outcome") == "shrink_failed" else 0
    x["ch_tx_ok_sum"] = sum(int(c["ch_tx_ok"]) for c in chs if c.get("ch_tx_ok") is not None)
    x["ch_rx_ok_sum"] = sum(int(c["ch_rx_ok"]) for c in chs if c.get("ch_rx_ok") is not None)
    x["ch_devcomm_rc"] = ";".join(sorted(set(c.get("ch_devcomm_rc") for c in chs if c.get("ch_devcomm_rc"))))
    x["ch_devcomm_ms"] = [fnum(c.get("ch_devcomm_ms")) for c in chs if c.get("ch_devcomm_ms")]
    x["ch_shrink_ms"] = [fnum(c.get("ch_shrink_ms")) for c in chs if c.get("ch_shrink_ms")]
    x["ch_gin_contexts"] = ";".join(sorted(set(c.get("ch_gin_contexts") for c in chs if c.get("ch_gin_contexts"))))
    x["ch_async"] = ";".join(sorted(set(c.get("ch_async") for c in chs if c.get("ch_async"))))
    x["ch_shrink_rc_r0"] = chs[0].get("ch_shrink_rc")
    # port fix
    x["occupy_skipped"] = fnum(meta.get("occupy_skipped"))
    x["port"] = fnum(meta.get("port"))
    x["port_tries"] = fnum(meta.get("port_tries"))
    x["port_skipped"] = meta.get("port_skipped")
    x["occupy_port"] = meta.get("occupy_port")
    x["decoy_port"] = meta.get("decoy_port")
    x["decoy_conns"] = fnum(dec.get("decoy_conns")) if dec else None
    x["decoy_bytes"] = fnum(dec.get("decoy_bytes")) if dec else None
    x["n_rdv_verified"] = sum(1 for r in range(N) if (kv[r] or {}).get("rdv") == "verified")
    x["n_decoy_rejected"] = sum(1 for r in range(1, N) if (kv[r] or {}).get("rdv_decoy") == "rejected")
    x["rdv_rejected_sum"] = sum(fnum((kv[r] or {}).get("rdv_rejected")) or 0 for r in range(1, N))
    x["rdv_foreign_r0"] = fnum(k0.get("rdv_foreign"))
    ts = [l.first_ts for l in lg if l.first_ts]
    x["first_ts"] = min(ts) if ts else None
    lt = [l.last_ts for l in lg if l.last_ts]
    x["last_ts"] = max(lt) if lt else None
    x["cuda_bad"] = sum(l.cuda_bad for l in lg)
    x["rc139"] = 1 if 139.0 in rcs else 0
    x["watchdog_exit"] = ";".join("%d" % r for r in range(N) if lg[r].watchdog_exit) or None
    return x


# ----------------------------------------------------------------------------------------------------------------------
# section 8: exclusions and setting checks
# ----------------------------------------------------------------------------------------------------------------------
POST_COMMIT = ("peer closed the socket before DONE", "DONE timeout", "cannot send ACK")


def exclusion(x):
    """the first section-8 exclusion that applies, or None"""
    c = x["cell"]
    if x["bind_fail"] == 1:
        return "bind failure"
    if x["kind"] == 2:
        for r in x["hooked"]:
            if x["n_fires_r%d" % r] == 0:
                return "fault not applied (rank %d hook did not fire)" % r
        if x["trigger_miss"] > 0:
            return "fault not applied (trigger miss)"
        if x["_meta"].get("fault") == "F4" or x["_meta"].get("kill_r0") == "1":
            if x["killed"] != 1:
                return "fault not applied (no kill record)"
        if c == "pq_repost_r1_b" and x["n_init_round_r1"] > 0:
            return "condition not applied (rank 1 initiated)"
        if c in RACE:
            mr, other = RACE[c]
            if x["n_cancel_ack_r%d" % mr] == 0:
                return "condition not applied (no cancel while waiting for the ACK)"
            w = x["declwhy_r%d" % other] or ""
            if not any(w.startswith(s) for s in POST_COMMIT):
                return "condition not applied (responder's first decline not after its commit: %r)" % w
        if c in COPY_RANK and x["n_copyto_r%d" % COPY_RANK[c]] == 0:
            return "condition not applied (no copy timeout on the held rank)"
        if c in FW_CELLS and x["n_wd_any_r0"] == 0:
            return "condition not applied (no watchdog line)"
        if c not in FW_CELLS:
            if x["n_wd_any_r0"] or x["n_wd_any_r1"] or (x["rs_fw_overruns_r0"] or 0) or (x["rs_fw_overruns_r1"] or 0):
                return "firmware overrun"
    else:
        exp = FIRES4.get(c)
        if exp is not None:
            if x["fires"] != exp or x["fire_in_traffic"] != 1:
                return "fault not applied (fires %r, in traffic %r)" % (x["fires"], x["fire_in_traffic"])
        elif x["fires"]:
            return "unexpected hook (fires %r)" % x["fires"]
        if x["trigger_miss"] > 0:
            return "fault not applied (trigger miss)"
        if x["_meta"].get("kill_rank"):
            if x["killed"] != 1 or x["kill_in_traffic"] != 1:
                return "fault not applied (kill record %r, in traffic %r)" % (x["killed"], x["kill_in_traffic"])
        if c in COPY_RANK and x["n_copyto_r0"] == 0:
            return "condition not applied (no copy timeout on rank 0)"
        if c in FW_CELLS and x["n_wd_any"] == 0:
            return "condition not applied (no watchdog line)"
        if c not in FW_CELLS and x["n_wd_any"]:
            return "firmware overrun"
    return None


def setting_check(x):
    """section 8 setting checks; returns a list of problems (empty = pass)"""
    bad = []
    b = x["build"]
    c = x["cell"]
    if x["kind"] == 2:
        meta = x["_meta"]
        killed = set()
        if meta.get("fault") == "F4":
            killed.add(1)
        if meta.get("kill_r0") == "1":
            killed.add(0)
        for r in (0, 1):
            if r in killed:
                continue
            if b in ("hq", "hf"):
                if not (x["hd_on_r%d" % r] and x["prod_r%d" % r] == 0):
                    bad.append("r%d harden start line" % r)
                if not x["hf_on_r%d" % r]:
                    bad.append("r%d handoff start line" % r)
                if b == "hq" and not x["pq_on_r%d" % r]:
                    bad.append("r%d peer start line missing" % r)
                if b == "hf" and x["pq_on_r%d" % r]:
                    bad.append("r%d peer start line present on hf" % r)
                if not x["ts_on_r%d" % r]:
                    bad.append("r%d transparent recovery ON missing" % r)
                if not x["ua_r%d" % r]:
                    bad.append("r%d abort word line missing" % r)
            else:  # hqp, hfp
                if x["ts_on_r%d" % r] or x["hd_on_r%d" % r] or x["hf_on_r%d" % r] or x["pq_on_r%d" % r]:
                    bad.append("r%d start line at WARN in a production build" % r)
                if not (x["rs_api_r%d" % r] == 1 and (x["rs_contexts_r%d" % r] or 0) >= 1):
                    bad.append("r%d rs_api/rs_contexts" % r)
            # test switches
            want = {}
            env = meta.get("r%denv" % r, "")
            if "NCCL_GIN_TS_TEST_BAD_REPOST=1" in env:
                want["bad_repost"] = "1"
            m = re.search(r"NCCL_GIN_TS_TEST_FW_DELAY=(\S+?)(?:\+|$)", env)
            if m:
                want["fw_delay"] = m.group(1)
            m = re.search(r"NCCL_GIN_TS_TEST_COPY_STALL=(\d+)", env)
            if m:
                want["copy_stall"] = m.group(1)
            if want:
                if x["knobs_hd_r%d" % r] is None:
                    bad.append("r%d test switch line missing" % r)
                else:
                    if "bad_repost" in want and x["hk_badrepost_r%d" % r] != want["bad_repost"]:
                        bad.append("r%d bad_repost=%s" % (r, x["hk_badrepost_r%d" % r]))
                    if "fw_delay" in want and x["hk_fwdelay_r%d" % r] != want["fw_delay"]:
                        bad.append("r%d fw_delay=%s" % (r, x["hk_fwdelay_r%d" % r]))
                    if "copy_stall" in want and x["hk_copystall_r%d" % r] != want["copy_stall"]:
                        bad.append("r%d copy_stall=%s" % (r, x["hk_copystall_r%d" % r]))
            elif x["knobs_hd_r%d" % r] is not None:
                kh = x["knobs_hd_r%d" % r]
                if not (x["hk_badrepost_r%d" % r] in ("-1", "0") and x["hk_fwdelay_r%d" % r] in ("0@-",)
                        and x["hk_copystall_r%d" % r] == "0"):
                    bad.append("r%d unexpected test switch line %s" % (r, kh))
            mute_want = "500:8000" if "NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000" in env else None
            if (x["sock_mute_r%d" % r] or None) not in (mute_want, "0:0" if mute_want is None else mute_want):
                bad.append("r%d sock_mute=%s" % (r, x["sock_mute_r%d" % r]))
        if c in RACE:
            mr, resp = RACE[c]
            if x["end_wait_r%d" % resp] != 1:
                bad.append("responder r%d has no GIN_TS_END_WAIT_S=12" % resp)
    else:
        N = x["n"]
        if x["n_ts_on"] < N:
            bad.append("transparent recovery ON lines %d < n" % x["n_ts_on"])
        if x["n_ua"] < N:
            bad.append("abort word lines %d < n" % x["n_ua"])
        if b == "hq" and x["n_pq_on"] != N:
            bad.append("peer start line on %d ranks" % x["n_pq_on"])
        if b == "hf" and x["n_pq_on"] != 0:
            bad.append("peer start line on hf")
    return bad


# ----------------------------------------------------------------------------------------------------------------------
# the rule grammar of ../s2_close/EXPERIMENT.md 3.2 (my own evaluator)
# ----------------------------------------------------------------------------------------------------------------------
NUM_RE = re.compile(r"^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$")


def conv(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    if s == "":
        return None
    if NUM_RE.match(s):
        return float(s)
    return s


class Ctx:
    def __init__(self, trials, cellsets):
        self.trials = trials        # the judged trials of this rule's cell
        self.cellsets = cellsets    # cell key -> judged trials (for median)
        self.row = None


def truthy(v):
    return bool(v) if v is not None else False


def cmp(op, a, b):
    num = isinstance(a, float) and isinstance(b, float)
    if isinstance(op, ast.Eq):
        return a == b if (num or (isinstance(a, str) and isinstance(b, str))) else False
    if isinstance(op, ast.NotEq):
        return a != b if (num or (isinstance(a, str) and isinstance(b, str))) else True
    if not num:
        return False
    return {ast.Lt: a < b, ast.LtE: a <= b, ast.Gt: a > b, ast.GtE: a >= b}[type(op)]


def ev(node, cx):
    if isinstance(node, ast.Expression):
        return ev(node.body, cx)
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else conv(node.value)
    if isinstance(node, ast.Name):
        if cx.row is None:
            raise ValueError("column %s outside count()" % node.id)
        return conv(cx.row.get(node.id))
    if isinstance(node, ast.BoolOp):
        vals = node.values
        if isinstance(node.op, ast.And):
            return all(truthy(ev(v, cx)) for v in vals)
        return any(truthy(ev(v, cx)) for v in vals)
    if isinstance(node, ast.UnaryOp):
        v = ev(node.operand, cx)
        if isinstance(node.op, ast.USub):
            return -v if isinstance(v, float) else None
        if isinstance(node.op, ast.Not):
            return not truthy(v)
    if isinstance(node, ast.BinOp):
        a, b = ev(node.left, cx), ev(node.right, cx)
        if not (isinstance(a, float) and isinstance(b, float)):
            return None
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return a / b if b else None
    if isinstance(node, ast.Compare):
        left = ev(node.left, cx)
        for op, comp in zip(node.ops, node.comparators):
            right = ev(comp, cx)
            if left is None or right is None:
                return False
            if not cmp(op, left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        fn = node.func.id
        if fn == "count":
            n = 0
            for t in cx.trials:
                cx.row = t
                if truthy(ev(node.args[0], cx)):
                    n += 1
            cx.row = None
            return float(n)
        if fn == "has":
            v = ev(node.args[0], cx)
            s = node.args[1].value
            return False if v is None else (s in (v if isinstance(v, str) else ("%g" % v)))
        if fn == "nonempty":
            return ev(node.args[0], cx) is not None
        if fn == "median":
            col = node.args[0].id
            key = node.args[1].value
            vals = [conv(t.get(col)) for t in cx.cellsets[key]]
            vals = [v for v in vals if isinstance(v, float)]
            return statistics.median(vals) if vals else None
        if fn == "abs":
            v = ev(node.args[0], cx)
            return abs(v) if isinstance(v, float) else None
    raise ValueError("unsupported: %s" % ast.dump(node))


def judge(pred, trials_by_key, all_trials):
    """returns list of (cell key, n judged, count or value, verdict, misses)"""
    acc = pred["acceptance"].strip()
    cells = [c.strip() for c in pred["cells"].split(";")]
    per_cell = acc.startswith("per cell:")
    if per_cell:
        acc = acc[len("per cell:"):].strip()
    tree = ast.parse(acc, mode="eval")
    out = []
    cellsets = {k: v for k, v in trials_by_key.items()}
    if cells == ["all@all"]:
        cx = Ctx(all_trials, cellsets)
        res = ev(tree, cx)
        cnt_node = tree.body.left if isinstance(tree.body, ast.Compare) else None
        cnt = ev(cnt_node, Ctx(all_trials, cellsets)) if cnt_node is not None else None
        out.append(("all@all", len(all_trials), cnt, "holds" if res else "fails", []))
        return out
    if "median(" in acc:
        need = all(len(trials_by_key.get(c, [])) >= PLAN[c] for c in cells)
        cx = Ctx([], cellsets)
        meds = {}
        for c in cells:
            vals = [t["lat_p50_us"] for t in trials_by_key.get(c, []) if t.get("lat_p50_us") is not None]
            meds[c] = statistics.median(vals) if vals else None
        res = ev(tree, cx) if need else None
        val = None
        if meds.get(cells[0]) is not None and meds.get(cells[1]) is not None:
            val = meds[cells[0]] - meds[cells[1]]
        out.append((" vs ".join(cells), "/".join(str(len(trials_by_key.get(c, []))) for c in cells), val,
                    "data insufficient" if not need else ("holds" if res else "fails"), []))
        return out
    groups = [[c] for c in cells] if per_cell else [cells]
    for g in groups:
        trials = [t for c in g for t in trials_by_key.get(c, [])]
        need = all(len(trials_by_key.get(c, [])) >= PLAN[c] for c in g)
        cx = Ctx(trials, cellsets)
        res = ev(tree, cx)
        # the count itself and the trials that miss the condition
        cnode = tree.body
        while isinstance(cnode, ast.Compare):
            cnode = cnode.left
        inner = cnode.args[0]
        misses = []
        cnt = 0
        for t in trials:
            cx.row = t
            if truthy(ev(inner, cx)):
                cnt += 1
            else:
                misses.append(t["stem"])
        cx.row = None
        out.append((";".join(g), len(trials), cnt, ("holds" if res else "fails") if need else "data insufficient", misses))
    return out


# ----------------------------------------------------------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------------------------------------------------------
def load(resdir):
    rows = []
    for sub in sorted(os.listdir(resdir)):
        d = os.path.join(resdir, sub)
        if not os.path.isdir(d):
            continue
        for mf in sorted(glob.glob(os.path.join(d, "*_meta.txt"))):
            stem = os.path.basename(mf)[: -len("_meta.txt")]
            rows.append(row4(d, stem) if sub.startswith("mr_") else row2(d, stem))
    return rows


def git(*args):
    return subprocess.run(["git", "-C", STUDY] + list(args), capture_output=True).stdout


def section(txt, num):
    m = re.search(r"^## %d\. .*?(?=^## \d+\. )" % num, txt, re.S | re.M)
    return m.group(0) if m else None


def rng(vals, fmt="%.1f"):
    v = [a for a in vals if a is not None]
    if not v:
        return "-"
    lo, hi = min(v), max(v)
    return (fmt % lo) if lo == hi else ("%s–%s" % (fmt % lo, fmt % hi))


def med(vals):
    v = [a for a in vals if a is not None]
    return statistics.median(v) if v else None


# ----------------------------------------------------------------------------------------------------------------------
def main():
    repo = git("rev-parse", "--show-toplevel").decode().strip()
    rel = os.path.relpath(STUDY, repo)
    p("# gin-peer independent recount (printed by qa/recount.py)")
    p()
    # ---------------- integrity ----------------
    p("## Integrity")
    tagc = git("rev-parse", TAG + "^{commit}").decode().strip()
    p("- tag %s -> commit %s" % (TAG, tagc[:8]))
    wt = open(os.path.join(STUDY, "predictions.csv"), "rb").read()
    tg = git("cat-file", "-p", "%s:%s/predictions.csv" % (TAG, rel))
    pre = open(os.path.join(STUDY, "PREREG.txt")).read()
    mh = re.search(r"\b([0-9a-f]{64})\s+predictions\.csv", pre)
    h_wt, h_tag = hashlib.sha256(wt).hexdigest(), hashlib.sha256(tg).hexdigest()
    p("- sha256 predictions.csv: working tree %s, tag %s, PREREG.txt %s -> %s" % (
        h_wt[:16], h_tag[:16], mh.group(1)[:16] if mh else None,
        "equal" if (h_wt == h_tag == (mh.group(1) if mh else None)) else "DIFFERENT"))
    pt = git("cat-file", "-p", "%s:%s/PREREG.txt" % (TAG, rel))
    p("- PREREG.txt equals the tag's copy: %s" % (pt == pre.encode()))
    ex_wt = open(os.path.join(STUDY, "EXPERIMENT.md"), encoding="utf-8").read()
    ex_tag = git("cat-file", "-p", "%s:%s/EXPERIMENT.md" % (TAG, rel)).decode("utf-8")
    for s in (2, 3, 7, 8):
        a, b = section(ex_wt, s), section(ex_tag, s)
        p("- EXPERIMENT.md section %d byte-identical to the tag: %s (%d bytes)" % (s, a is not None and a == b,
                                                                                len((a or "").encode())))
    p("- EXPERIMENT.md whole file identical to the tag: %s (sha256 %s)" % (
        ex_wt == ex_tag, hashlib.sha256(ex_wt.encode()).hexdigest()[:16]))
    for f in ("cells.sh", "chain.sh", "portpick.sh", "../gin_ts2.cu", "gin_mr.cu", "run_trial_hq.sh", "run_mr_hq.sh",
              "hold.sh"):
        path = os.path.normpath(os.path.join(rel, f))
        t = git("cat-file", "-p", "%s:%s" % (TAG, path))
        w = open(os.path.join(repo, path), "rb").read()
        same = t == w
        note = ""
        if not same:  # the repository's address filter stores a placeholder in commits; never print the line itself
            tl, wl = t.decode(errors="replace").splitlines(), w.decode(errors="replace").splitlines()
            d = [i for i in range(max(len(tl), len(wl))) if i >= len(tl) or i >= len(wl) or tl[i] != wl[i]]
            only = len(tl) == len(wl) and all(wl[i].startswith("SUNNY_SSH=") for i in d)
            note = " (%d differing line(s) %s%s)" % (len(d), [i + 1 for i in d],
                                                     ", only the SUNNY_SSH default (address filter)" if only else ", OTHER")
        p("- %s identical to the tag: %s%s" % (f, same, note))
    # bundle md5s (deploy_check.txt) against EXPERIMENT.md 5, and the driver sources against the md5 the build recorded
    dc = open(os.path.join(STUDY, "deploy_check.txt"), errors="replace").read()
    want = {"hq/libnccl": "c1311625c7a06c785bc313558504f982", "hqp/libnccl": "4fa076e113e43774a9dc2f46298df43b",
            "hq/gin_ts2": "3e053ff2ab069ec64198ed4e0f6e237a", "mr/hq/gin_mr": "7f0fc272962b293da0bd0d3655aacc4d",
            "hf/libnccl": "b6372d8622f6a7eceb9fd4528c00e707", "hfp/libnccl": "1ae4ce9aecb1727248db7eb3699ad110",
            "hf/gin_ts2": "9493584d5a321277c61863f4ed6ac379"}
    got = {}
    for name, md in want.items():
        pat = re.escape(name).replace("libnccl", r"libnccl\.so\S*")
        found = set(m.group(1) for m in re.finditer(r"([0-9a-f]{32})\s+\S*?" + pat, dc))
        got[name] = "ok" if found == {md} else ("DIFFERENT %s" % found if found else "absent")
    p("- deploy_check.txt md5 vs EXPERIMENT.md 5: %s; 'deployed md5 == source on both nodes': %s; 'existing bundle unchanged': %s" % (
        got, "deployed md5 == source on both nodes" in dc, "existing bundle unchanged on both nodes" in dc))
    for src, key in (("../gin_ts2.cu", "gin_ts2_cu_md5"), ("gin_mr.cu", "gin_mr_cu_md5")):
        m = re.search(key + r"=([0-9a-f]{32})", dc)
        h = hashlib.md5(open(os.path.join(STUDY, src), "rb").read()).hexdigest()
        p("- md5 of %s in the working tree %s; recorded at build %s -> %s" % (src, h[:8], m.group(1)[:8] if m else None,
                                                                            "equal" if m and m.group(1) == h else "DIFFERENT"))
    preds = []
    import csv
    with open(os.path.join(STUDY, "predictions.csv"), newline="") as f:
        for r in csv.DictReader(f):
            preds.append(r)
    p("- predictions.csv rows: %d (kinds %s)" % (len(preds), dict(Counter(r["kind"] for r in preds))))
    p()

    # ---------------- load ----------------
    rows = load(RES)
    by_key = defaultdict(list)
    for x in rows:
        by_key[x["key"]].append(x)
    p("## Trial set (section 7)")
    n2 = sum(1 for x in rows if x["kind"] == 2 and not x["cell"].startswith("lat_"))
    nl = sum(1 for x in rows if x["kind"] == 2 and x["cell"].startswith("lat_"))
    n4 = sum(1 for x in rows if x["kind"] == 4)
    p("- trials: %d (two-rank cell trials %d, latency runs %d, four-rank trials %d)" % (len(rows), n2, nl, n4))
    planned = sum(PLAN.values())
    p("- planned: %d (two-rank %d, latency %d, four-rank %d)" % (
        planned, sum(v for k, v in PLAN2.items() if not k.startswith("lat_")),
        sum(v for k, v in PLAN2.items() if k.startswith("lat_")), sum(PLAN4.values())))
    p("- cell keys present: %d, planned: %d" % (len(by_key), len(PLAN)))
    for k, v in PLAN.items():
        got = by_key.get(k, [])
        tr = sorted(int(x["trial"][1:]) for x in got)
        if len(got) != v or tr != list(range(1, v + 1)):
            p("  - MISMATCH %s: planned %d, got %d trials %s" % (k, v, len(got), tr))
    extra = [k for k in by_key if k not in PLAN]
    if extra:
        p("  - cell keys outside the plan: %s" % extra)
    # folder / bundle / args
    argbad = []
    for x in rows:
        m = x["_meta"]
        k = int(x["trial"][1:])
        if x["kind"] == 2:
            if x["folder"] != x["build"]:
                argbad.append("%s: folder %s build %s" % (x["stem"], x["folder"], x["build"]))
            if not m.get("bundle", "").endswith("/gi-bundle/gin_ts2/" + x["build"]):
                argbad.append("%s: bundle %s" % (x["stem"], m.get("bundle")))
            e = expected_args2(x["cell"], k)
        else:
            if x["folder"] != "mr_" + x["build"]:
                argbad.append("%s: folder %s lib %s" % (x["stem"], x["folder"], x["build"]))
            if not (m.get("libdir", "").endswith("/gi-bundle/gin_ts2/" + x["build"]) and m.get("mrbin", "").endswith(
                    "/gi-bundle/gin_ts2/mr/hq/gin_mr")):
                argbad.append("%s: libdir/mrbin" % x["stem"])
            e = expected_args4(x["cell"], k)
        for kk, vv in e.items():
            if (m.get(kk) or "") != vv:
                argbad.append("%s: %s=%r expected %r" % (x["stem"], kk, m.get(kk), vv))
        if m.get("rdv_nonce_set") != "1":
            argbad.append("%s: rdv_nonce_set" % x["stem"])
    p("- meta arguments that differ from cells.sh: %d %s" % (len(argbad), argbad[:20]))
    miss = []
    for x in rows:
        n = 2 if x["kind"] == 2 else x["n"]
        for r in range(n):
            if x["_kv"][r] is None or not x["_lg"][r].exists:
                miss.append("%s r%d" % (x["stem"], r))
    known = set()
    for x in rows:
        known.add(os.path.join(RES, x["folder"], x["stem"]))
    stray = []
    for sub in ("hq", "hf", "hqp", "hfp", "mr_hq", "mr_hf"):
        for f in os.listdir(os.path.join(RES, sub)):
            st = re.sub(r"_(meta\.txt|r\d\.kv|r\d\.log|kill\.out|decoy\.out|lat_raw\.csv\.gz)$", "", f)
            if os.path.join(RES, sub, st) not in known:
                stray.append(os.path.join(sub, f))
    p("- ranks without a kv or log file: %s; files that belong to no trial: %s" % (miss or "none", stray or "none"))
    p("- exit codes per cell key (r0rc,r1rc[,r2rc,r3rc] -> trials):")
    for k in PLAN:
        c = Counter(",".join("%d" % v for v in ([x["r0rc"], x["r1rc"]] if x["kind"] == 2 else x["rcs"])) for x in by_key.get(k, []))
        p("  - %s: %s" % (k, dict(c)))
    raw, parsed = Counter(), Counter()
    nlog = 0
    for x in rows:
        for l in x["_lg"]:
            if not l.exists:
                continue
            nlog += 1
            for k, _ in COVER:
                raw[k] += l.raw[k]
                parsed[k] += len(l.ev[k])
    p("- parse coverage over %d rank logs (lines with the substring / lines parsed): %s" % (
        nlog, ", ".join("%s %d/%d" % (k, raw[k], parsed[k]) for k, _ in COVER)))
    p("- first log line of the main run: %s; last: %s; pre-registration commit time 2026-10-09 09:00:54" % (
        min(x["first_ts"] for x in rows if x["first_ts"]), max(x["last_ts"] for x in rows if x["last_ts"])))
    p()

    # ---------------- hold logs ----------------
    p("## Hold logs and safety records")
    hold_seq = {}
    def alt21(cell, a, b):
        s = []
        for k in range(1, 6):
            s += [(cell, a, 2 * k - 1), (cell, a, 2 * k), (cell, b, k)]
        return s
    hold_seq["H1"] = ([(x, "hq", k) for x in ("f1_b", "f3_b", "bidirf_sym_b", "f4_b", "f2rel_b", "hd_rxdeath_b")
                       for k in range(1, 6)] + [("hdp_kill_b", "hqp", k) for k in range(1, 6)]
                      + [(x, b, k) for k in range(1, 6) for x in ("lat_4k", "lat_256k") for b in ("hqp", "hfp")])
    hold_seq["H2"] = (alt21("pq_repost_r1_b", "hq", "hf") + [("hd_repost_f1_b", "hq", k) for k in range(1, 6)]
                      + [("hd_fwslow_f1_b", "hq", k) for k in range(1, 6)] + [("pq_rdv_b", "hq", k) for k in range(1, 6)])
    hold_seq["H3"] = alt21("pq_ackrace_f1_b", "hq", "hf") + [(("pq_ackrace_f1r1_b", b, k)) for k in range(1, 6)
                                                             for b in ("hq", "hf")]
    hold_seq["H4"] = (alt21("pq_copystall_shrink_b", "hq", "hf") + [("pq_copystall1_shrink_b", "hq", k) for k in range(1, 6)]
                      + [("hd_shrink_b", "hq", k) for k in range(1, 6)])
    hold_seq["H5"] = alt21("mr4_kill3_peer", "hq", "hf") + [("mr4_kill3", "hq", k) for k in range(1, 6)]
    hold_seq["H6"] = alt21("pq4_fwslow", "hq", "hf")
    hold_seq["H7"] = ([("pq4_kill3_shrink", "hq", k) for k in range(1, 11)] + [("mr4_none", "hq", k) for k in range(1, 6)]
                      + [("mr4_f1_01", "hq", k) for k in range(1, 6)])
    hold_seq["H8"] = [("pq4_local_shrink", b, k) for k in range(1, 6) for b in ("hq", "hf")] + [("pq4_rdv", "hq", k)
                                                                                                for k in range(1, 4)]
    idx = {(x["cell"], x["build"], int(x["trial"][1:])): x for x in rows}
    covered = set()
    holddiff = []
    hold_of = {}
    for h, seq in hold_seq.items():
        txt = open(os.path.join(RES, "hold_%s.out" % h), errors="replace").read().splitlines()
        starts, results, kills = [], [], []
        for line in txt:
            m = re.match(r"^\[([^\]]+)#(n\d+)\] (.*)$", line)
            if not m:
                continue
            tag, tr, rest = m.groups()
            if rest.startswith("r0rc="):
                results.append((tag, tr, rest))
            elif "SIGKILL" in rest:
                kills.append((tag, tr, rest))
            elif "port=" in rest:
                starts.append((tag, tr, rest))
        if len(starts) != len(seq) or len(results) != len(seq):
            holddiff.append("%s: %d starts, %d results, %d planned" % (h, len(starts), len(results), len(seq)))
        snapb = open(os.path.join(RES, "snap_before-%s.txt" % h)).readline().split()[2:4]
        snapa = open(os.path.join(RES, "snap_after-%s.txt" % h)).readline().split()[2:4]
        tb, ta = " ".join(snapb), " ".join(snapa)
        for i, (cell, b, k) in enumerate(seq):
            x = idx.get((cell, b, k))
            if x is None:
                holddiff.append("%s: %s@%s n%d has no trial files" % (h, cell, b, k))
                continue
            covered.add(x["stem"] + "@" + x["folder"])
            hold_of[(cell, b, k)] = h
            if i >= len(starts):
                continue
            tag, tr, rest = starts[i]
            m = x["_meta"]
            if tr != "n%d" % k or not tag.startswith(b + "/"):
                holddiff.append("%s #%d: hold line %s#%s, expected %s@%s n%d" % (h, i, tag, tr, cell, b, k))
            if x["kind"] == 4 and not tag.endswith("/" + cell):
                holddiff.append("%s #%d: tag %s cell %s" % (h, i, tag, cell))
            f = dict(re.findall(r"(\w+)=(\S+)", rest))
            for hk, mk in (("port", "port"), ("tries", "port_tries"), ("decoy", "decoy_port")):
                hv = f.get(hk)
                mv = m.get(mk)
                if hk == "decoy" and hv == "-":
                    hv = "none"
                if hv != mv:
                    holddiff.append("%s %s: hold %s=%s meta %s=%s" % (h, x["stem"], hk, hv, mk, mv))
            sk = f.get("skipped")
            if (sk if sk != "-" else "none") != m.get("port_skipped"):
                holddiff.append("%s %s: hold skipped=%s meta %s" % (h, x["stem"], sk, m.get("port_skipped")))
            tag2, tr2, rest2 = results[i]
            f2 = dict(re.findall(r"(\w+)=(\S+)", rest2.split("::")[0]))
            n = 2 if x["kind"] == 2 else x["n"]
            for r in range(n):
                if f2.get("r%drc" % r) != m.get("r%drc" % r):
                    holddiff.append("%s %s: hold r%drc=%s meta %s" % (h, x["stem"], r, f2.get("r%drc" % r), m.get("r%drc" % r)))
            if f2.get("left") != m.get("left"):
                holddiff.append("%s %s: hold left=%s meta %s" % (h, x["stem"], f2.get("left"), m.get("left")))
            if f2.get("wall", "").rstrip("s") != m.get("wall_s"):
                holddiff.append("%s %s: hold wall=%s meta %s" % (h, x["stem"], f2.get("wall"), m.get("wall_s")))
            if x["first_ts"] and not (tb <= x["first_ts"] <= ta):
                holddiff.append("%s %s: first log line %s outside the hold window %s..%s" % (h, x["stem"], x["first_ts"], tb, ta))
            if x["last_ts"] and not (tb <= x["last_ts"] <= ta):
                holddiff.append("%s %s: last log line %s outside the hold window %s..%s" % (h, x["stem"], x["last_ts"], tb, ta))
    notcov = [x["stem"] + "@" + x["folder"] for x in rows if x["stem"] + "@" + x["folder"] not in covered]
    p("- hold result lines matched to trial files in hold.sh order: %d of %d trials; not covered: %s" % (
        len(covered), len(rows), notcov))
    p("- disagreements between hold lines and meta (port, tries, skipped, decoy, rc, left, wall_s, time window): %d" % len(holddiff))
    for d in holddiff:
        p("  - %s" % d)
    # kill lines in the hold logs vs kill.out
    kl = 0
    kbad = []
    for h in hold_seq:
        for line in open(os.path.join(RES, "hold_%s.out" % h), errors="replace"):
            m = re.match(r"^\[([^\]]+)#(n\d+)\] SIGKILL .*kill_mono_ms=([\d.]+)", line)
            if not m:
                continue
            kl += 1
            tag, tr, km = m.groups()
            cands = [x for x in rows if x["trial"] == tr and x["_kill"] and x["_kill"].get("kill_mono_ms") == km]
            if len(cands) != 1:
                kbad.append(line.strip()[:120])
    p("- SIGKILL lines in the hold logs: %d; each matches one trial's kill.out kill_mono_ms: %s" % (kl, "yes" if not kbad else kbad))
    p("- trials with a kill.out: %d" % sum(1 for x in rows if x["_kill"]))
    # chain.out, STOP files, snapshots
    chain = open(os.path.join(RES, "chain.out")).read()
    rcs = re.findall(r"hold (H\d) rc=(\d+)", chain)
    ipt = re.findall(r"before=(\d+) after=(\d+)", chain)
    p("- chain.out: holds %s; iptables gin- rules before/after %s" % (rcs, sorted(set(ipt))))
    stops = sorted(glob.glob(os.path.join(RES, "STOP_*")))
    p("- STOP files: %s; LEFT_STREAK=%s; stale.txt present: %s" % (
        [os.path.basename(s) for s in stops], open(os.path.join(RES, "LEFT_STREAK")).read().strip(),
        os.path.exists(os.path.join(RES, "stale.txt"))))
    for h in hold_seq:
        sb = open(os.path.join(RES, "snap_before-%s.txt" % h)).read()
        sa = open(os.path.join(RES, "snap_after-%s.txt" % h)).read()
        g = lambda s, k: re.search(k + r": (\d+)", s).group(1)
        newl = open(os.path.join(RES, "mlx5_new_%s.txt" % h)).read().splitlines()
        cmd_new = [l for l in newl if re.search(r"cmd|command", l, re.I) and re.search(r"failed|timeout|leak", l, re.I)]
        p("- %s: cmd_err rain %s->%s sunny %s->%s, fwcmd failed %s->%s, new mlx5 lines %d (command-error lines %d)%s" % (
            h, g(sb, "rain mlx5 cmd_err lines"), g(sa, "rain mlx5 cmd_err lines"), g(sb, "sunny mlx5 cmd_err lines"),
            g(sa, "sunny mlx5 cmd_err lines"), g(sb, "rain fwcmd failed sum"), g(sa, "rain fwcmd failed sum"), len(newl),
            len(cmd_new), (": " + newl[0][:110]) if newl else ""))
    p("- left (meta) > 0: %d trials; rank exit 139: %d; CUDA memory-error lines in logs: %d" % (
        sum(1 for x in rows if (x["left"] or 0) > 0), sum(x["rc139"] for x in rows),
        sum((x.get("cuda_bad_r0", 0) + x.get("cuda_bad_r1", 0)) if x["kind"] == 2 else x["cuda_bad"] for x in rows)))
    kvbad = 0
    for x in rows:
        for k in x["_kv"]:
            if k and any(CUDA_BAD.search(str(v)) for v in k.values()):
                kvbad += 1
    p("- CUDA memory-error strings in kv files: %d" % kvbad)
    p()

    # ---------------- exclusions ----------------
    p("## Exclusions (section 8) and setting checks")
    excl = {}
    for x in rows:
        e = exclusion(x)
        x["excluded"] = e
        if e:
            excl[x["stem"] + "@" + x["folder"]] = e
    judged = defaultdict(list)
    for x in rows:
        if not x["excluded"]:
            judged[x["key"]].append(x)
    p("- trials %d, judged %d, excluded %d %s" % (len(rows), sum(len(v) for v in judged.values()), len(excl), excl))
    sc = {}
    for x in rows:
        b = setting_check(x)
        if b:
            sc[x["stem"] + "@" + x["folder"]] = b
    p("- setting-check problems: %d %s" % (len(sc), sc))
    # what the exclusion inputs looked like
    p("- exclusion inputs: bind failures %d; hooked ranks without a fire %d; trigger misses %d; kill cells without a kill "
      "record %d; four-rank fires not as expected %d; kills outside traffic %d" % (
          sum(x["bind_fail"] for x in rows),
          sum(1 for x in rows if x["kind"] == 2 and any(x["n_fires_r%d" % r] == 0 for r in x["hooked"])),
          sum(x["trigger_miss"] for x in rows),
          sum(1 for x in rows if x["kind"] == 2 and (x["_meta"].get("fault") == "F4" or x["_meta"].get("kill_r0") == "1")
              and not x["killed"]) + sum(1 for x in rows if x["kind"] == 4 and x["_meta"].get("kill_rank") and not x["killed"]),
          sum(1 for x in rows if x["kind"] == 4 and x["cell"] in FIRES4 and (x["fires"] != FIRES4[x["cell"]] or x["fire_in_traffic"] != 1)),
          sum(1 for x in rows if x["kind"] == 4 and x["_meta"].get("kill_rank") and x["kill_in_traffic"] != 1)))
    p("- watchdog lines outside the firmware cells: %d trials; rs_fw_overruns > 0 outside them: %d" % (
        sum(1 for x in rows if x["cell"] not in FW_CELLS and ((x["kind"] == 2 and (x["n_wd_any_r0"] + x["n_wd_any_r1"]))
                                                             or (x["kind"] == 4 and x["n_wd_any"]))),
        sum(1 for x in rows if x["kind"] == 2 and x["cell"] not in FW_CELLS and ((x["rs_fw_overruns_r0"] or 0) + (x["rs_fw_overruns_r1"] or 0)))))
    rk = [x for x in rows if x["kind"] == 4 and x["kill_in_traffic"] is not None]
    p("- four-rank kill timing: kill after the last kernel launch %s ms; before the earliest nominal traffic end %s ms (n=%d)" % (
        rng([x["kill_after_last_launch_ms"] for x in rk]), rng([x["kill_before_traffic_end_ms"] for x in rk]), len(rk)))
    p("- pq_repost_r1_b: rank 1 initiating rounds (n_init_round_r1 > 0): %d trials" % sum(
        1 for x in rows if x["cell"] == "pq_repost_r1_b" and x["n_init_round_r1"] > 0))
    for c, (mr_, rs) in RACE.items():
        xs = [x for x in rows if x["cell"] == c]
        p("- %s: cancel while waiting for the ACK on rank %d in %d/%d; responder's first decline %s" % (
            c, mr_, sum(1 for x in xs if x["n_cancel_ack_r%d" % mr_] >= 1), len(xs),
            dict(Counter(x["declwhy_r%d" % rs] for x in xs))))
    p()

    # ---------------- verdicts ----------------
    p("## Verdicts")
    p()
    p("| id | kind | cell | n judged | hits | verdict | trials that miss |")
    p("|---|---|---|--:|--:|---|---|")
    vc = Counter()
    verdicts = {}
    for pr in preds:
        res = judge(pr, judged, rows)
        overall = "holds"
        for r in res:
            if r[3] == "fails":
                overall = "fails"
            elif r[3] == "data insufficient" and overall != "fails":
                overall = "data insufficient"
        vc[overall] += 1
        verdicts[pr["id"]] = (overall, res)
        for (cell, n, cnt, v, miss) in res:
            cs = ("%.3f" % cnt if isinstance(cnt, float) and "vs" in cell else ("%d" % cnt if cnt is not None else "-"))
            p("| %s | %s | `%s` | %s | %s | %s | %s |" % (pr["id"], pr["kind"], cell, n, cs, v,
                                                     ", ".join(miss) if miss else ""))
    p()
    p("- verdict counts: %s (of %d)" % (dict(vc), len(preds)))
    p()
    # discrimination: each rule's count condition applied to the other build's cell of the same name (it should
    # mostly fail there; this checks that the evaluator and the columns are not vacuous)
    p("### Rule discrimination check (each rule's condition counted on the other build's cell; not a verdict)")
    swap = {"hq": "hf", "hf": "hq", "hqp": "hfp", "hfp": "hqp"}
    for pr in preds:
        cells = [c.strip() for c in pr["cells"].split(";")]
        if len(cells) != 1 or "@" not in cells[0] or cells[0] == "all@all":
            continue
        cell, b = cells[0].split("@")
        alt = "%s@%s" % (cell, swap.get(b, ""))
        if alt not in judged:
            continue
        acc = pr["acceptance"].strip()
        tree = ast.parse(acc, mode="eval")
        node = tree.body
        while isinstance(node, ast.Compare):
            node = node.left
        cx = Ctx(judged[alt], judged)
        cnt = ev(node, cx)
        p("- %s condition on `%s`: %d/%d" % (pr["id"], alt, cnt, len(judged[alt])))
    p()

    # ---------------- key numbers ----------------
    J = judged
    p("## Key numbers")
    p()
    p("### Port fix")
    allbind = sum(x["bind_fail"] for x in rows)
    holdbind = sum(open(os.path.join(RES, "hold_%s.out" % h), errors="replace").read().count("Address already in use")
                   for h in hold_seq)
    p("- bind failures: %d of %d trials (rank logs); 'Address already in use' in hold logs: %d" % (allbind, len(rows), holdbind))
    ports = [x["port"] for x in rows]
    p("- rendezvous ports: %s, all within 29000–30999: %s; distinct %d" % (
        rng(ports, "%.0f"), all(29000 <= q <= 30999 for q in ports), len(set(ports))))
    tries = Counter(x["port_tries"] for x in rows)
    p("- port_tries over all trials: %s; trials whose pick skipped a busy candidate without a held port: %s; skipped "
      "candidates in the held-port trials: %s" % (
          dict(tries), [x["stem"] for x in rows if x["port_skipped"] not in ("none", None) and x["occupy_port"] in ("none", None)],
          ["%s:%s" % (x["stem"], x["port_skipped"]) for x in rows if x["occupy_port"] not in ("none", None)]))
    for c in ("pq_rdv_b@hq", "pq4_rdv@hq"):
        xs = by_key[c]
        p("- %s (n=%d): occupier skipped %s; held port, used port, decoy port: %s; decoy connections %s, decoy bytes %s; "
          "decoy rejected by %s; rendezvous verified on %s" % (
              c, len(xs), [int(x["occupy_skipped"]) for x in xs],
              ["%s/%.0f/%s" % (x["occupy_port"], x["port"], x["decoy_port"]) for x in xs],
              [int(x["decoy_conns"]) for x in xs], [int(x["decoy_bytes"]) for x in xs],
              [x["rdv_decoy_r1"] for x in xs] if c.startswith("pq_") else [x["n_decoy_rejected"] for x in xs],
              ["%s,%s" % (x["rdv_r0"], x["rdv_r1"]) for x in xs] if c.startswith("pq_") else [x["n_rdv_verified"] for x in xs]))
    ver = Counter()
    for x in rows:
        if x["kind"] == 2:
            for r in (0, 1):
                k = x["_kv"][r]
                ver[(x["build"], (k or {}).get("rdv", "absent"))] += 1
        else:
            for r in range(x["n"]):
                ver[("mr/" + x["build"], (x["_kv"][r] or {}).get("rdv", "absent"))] += 1
    p("- rendezvous kv per rank (build, rdv): %s" % dict(ver))
    rej = sum((x.get("rdv_rejected_r1") or 0) for x in rows if x["kind"] == 2) + sum(x["rdv_rejected_sum"] for x in rows if x["kind"] == 4)
    fr = sum((x.get("rdv_foreign_r0") or 0) for x in rows)
    p("- rdv_rejected (ranks > 0) summed: %d; rdv_foreign (rank 0) summed: %d (in the decoy cells the decoy is checked "
      "separately: rdv_decoy)" % (rej, fr))
    p()
    p("### Per-peer release, four ranks (rank 3 killed)")
    for c in ("mr4_kill3_peer@hq", "mr4_kill3_peer@hf", "mr4_kill3@hq", "pq4_kill3_shrink@hq"):
        xs = J[c]
        p("- %s (n=%d): survivor edges ok per trial %s; survivor tx failed %s; survivor rx failed %s (rx rc %s); "
          "rx timeout %s; edges to rank 3 failed at the sender %s; receives from rank 3 rc %s; async ranks %s" % (
              c, len(xs), [x["surv_edges_ok"] for x in xs], [x["surv_tx_failed"] for x in xs],
              [x["surv_rx_failed"] for x in xs], sorted(set(x["surv_rx_rc"] for x in xs)),
              [x["surv_rx_timeout"] for x in xs], [x["dead_tx_failed"] for x in xs], sorted(set(x["dead_rx_rc"] for x in xs)),
              dict(Counter(x["async_ranks"] for x in xs))))
        dak = [x["decl_after_kill_ms_r%d" % r] for x in xs for r in range(3)]
        jak = [x["judged_after_kill_ms_r%d" % r] for x in xs for r in range(3)]
        daj = [x["decl_after_judged_ms_r%d" % r] for x in xs for r in range(3)]
        kek = [x["kend_after_kill_ms_r%d" % r] for x in xs for r in range(3)]
        aak = [x["async_after_kill_ms_r%d" % r] for x in xs for r in range(3)]
        p("  - first decline after the kill (rank 0 clock), pooled over the three survivors and the trials: %s ms "
          "(n=%d); 'judged dead' after the kill %s ms; decline after 'judged dead' (same rank's clock) %s ms; first async "
          "error after the kill %s ms; survivor kernel end after the kill %s ms; decl %s; per-peer words %s; devComm-word "
          "error lines %s; causes %s" % (
              rng(dak), len([d for d in dak if d is not None]), rng(jak), rng(daj), rng(aak, "%.0f"), rng(kek, "%.0f"),
              dict(Counter(x["decl"] for x in xs)),
              dict(Counter(x["uapeer"] for x in xs)), dict(Counter(x["n_uaerr"] for x in xs)),
              dict(Counter(x["causes"] for x in xs))))
    p()
    p("### Plan before commit (two ranks)")
    for c in ("pq_repost_r1_b@hq", "pq_repost_r1_b@hf", "hd_repost_f1_b@hq"):
        xs = J[c]
        p("- %s (n=%d): plan rejected on r0/r1 %s; rejected qp (first) r0 %s r1 %s; plan validated lines r0/r1 %s; "
          "recovered lines r0/r1 %s; rank 0 first decline %s; rank 1 first decline %s; causes r0 %s r1 %s" % (
              c, len(xs), dict(Counter("%d/%d" % (x["n_planrej_r0"], x["n_planrej_r1"]) for x in xs)),
              dict(Counter(x["planrej_qp_r0"] for x in xs)), dict(Counter(x["planrej_qp_r1"] for x in xs)),
              dict(Counter("%d/%d" % (x["n_planok_r0"], x["n_planok_r1"]) for x in xs)),
              dict(Counter("%d/%d" % (x["rec_init_r0"] + x["rec_resp_r0"], x["rec_init_r1"] + x["rec_resp_r1"]) for x in xs)),
              dict(Counter(x["declwhy_r0"] for x in xs)), dict(Counter(x["declwhy_r1"] for x in xs)),
              dict(Counter(x["cause_r0"] for x in xs)), dict(Counter(x["cause_r1"] for x in xs))))
        if c == "pq_repost_r1_b@hf":
            p("  - hf: WQEs in rank 0's re-post (recovered initiator line count %s); rank 0 rounds initiated %s" % (
                [x["rec_init_r0"] for x in xs], [x["n_init_round_r0"] for x in xs]))
    nack = sum(1 for x in J["pq_repost_r1_b@hq"] if x["declwhy_r0"] == "peer NACK (its re-post plan was rejected)")
    p("- NACK 15 decline on rank 0 in pq_repost_r1_b@hq: %d/%d" % (nack, len(J["pq_repost_r1_b@hq"])))
    p()
    p("### Per-round firmware watchdog")
    xs = J["hd_fwslow_f1_b@hq"]
    p("- hd_fwslow_f1_b@hq (n=%d): trips per trial %s, phase %s, trip at %s ms; first devComm-word why %s; "
      "abort %s ms; helper detached %s; rank 1 decline %s" % (
          len(xs), [x["n_fwover_r0"] for x in xs], sorted(set(x["fwover_phase_r0"] for x in xs)),
          rng([x["fwover_ms_r0"] for x in xs], "%.0f"), sorted(set(x["uarel_why_r0"] for x in xs)),
          rng([x["teardown_ms_r0"] for x in xs]), [x["n_orphan_r0"] for x in xs], dict(Counter(x["declwhy_r1"] for x in xs))))
    for c in ("pq4_fwslow@hq", "pq4_fwslow@hf"):
        xs = J[c]
        p("- %s (n=%d): new-format trips %s at %s ms; old-format lines %s; 'surfaces' lines %s; decl %s; reasons %s; "
          "rank 2 initiator recoveries with rank 0 %s, rank 0 responder recoveries with rank 2 %s; per-peer words %s; "
          "devComm-word error lines %s; bad edges %s" % (
              c, len(xs), dict(Counter(x["fwover"] for x in xs)), sorted(set(x["fwover_ms"] for x in xs)),
              [x["n_fwold"] for x in xs], [x["n_surface"] for x in xs], dict(Counter(x["decl"] for x in xs)),
              dict(Counter(x["decl_reasons"] for x in xs)), [x["rec_20"] for x in xs], [x["rec_02"] for x in xs],
              dict(Counter(x["uapeer"] for x in xs)), dict(Counter(x["uaerr"] for x in xs)),
              dict(Counter(x["edges_bad"] for x in xs))))
        # time from rank 0's decline of rank 1 to rank 2's hook
        gaps = []
        for x in xs:
            d0 = [float(d[4]) for d in x["_lg"][0].ev["decl"] if d[1] == "1"]
            f2 = [float(g[1]) for g in x["_lg"][2].ev["fired"]]
            f0 = [float(g[1]) for g in x["_lg"][0].ev["fired"]]
            if d0 and f2 and f0:
                gaps.append((d0[0] - f0[0], f2[0] - d0[0]))
        p("  - rank 0 decline of rank 1 after its hook %s ms; rank 2 hook after that decline %s ms" % (
            rng([g[0] for g in gaps], "%.0f"), rng([g[1] for g in gaps], "%.0f")))
    p()
    p("### FAIL on reconnect")
    for c, r_ in (("pq_ackrace_f1_b@hq", 0), ("pq_ackrace_f1_b@hf", 0), ("pq_ackrace_f1r1_b@hq", 1), ("pq_ackrace_f1r1_b@hf", 1)):
        xs = J[c]
        o = 1 - r_
        p("- %s (n=%d): rank %d decline after its mute end %s ms (median %.0f); decline reason %s; rank %d FAIL answers %s; "
          "cancel→mute end %s ms; responder decline %s" % (
              c, len(xs), r_, rng([x["decl_after_unmute_ms_r%d" % r_] for x in xs], "%.0f"),
              med([x["decl_after_unmute_ms_r%d" % r_] for x in xs]), dict(Counter(x["declwhy_r%d" % r_] for x in xs)), o,
              dict(Counter(x["failans_r%d" % o] for x in xs)),
              rng([x["muteoff_ms_r%d" % r_] - x["cancel_ms_r%d" % r_] for x in xs if x["cancel_ms_r%d" % r_]], "%.0f"),
              dict(Counter(x["declwhy_r%d" % o] for x in xs))))
        car = [x["cancel_ms_r%d" % r_] - float(x["_lg"][r_].ev["round"][0][6]) for x in xs
               if x["cancel_ms_r%d" % r_] and x["_lg"][r_].ev["round"]]
        rta = []
        for x in xs:
            tear = fnum((x["_kv"][o] or {}).get("abort_start_mono_ms"))
            if tear and x["decl_ms_r%d" % o]:
                rta.append(tear - x["decl_ms_r%d" % o])
        pfo = [x["decl_ms_r%d" % r_] - float(x["_lg"][r_].ev["peerfail"][0][3]) for x in xs if x["_lg"][r_].ev["peerfail"]]
        p("  - cancel after the round started %s ms; responder decline -> its abort start %s ms; FAIL received -> decline "
          "%s ms" % (rng(car, "%.0f"), rng(rta, "%.0f"), rng(pfo, "%.1f")))
    p()
    p("### Cause-based shrink hand-off")
    for c in ("pq_copystall_shrink_b@hq", "pq_copystall_shrink_b@hf", "pq_copystall1_shrink_b@hq", "hd_shrink_b@hq"):
        xs = J[c]
        p("- %s (n=%d): cause r0 %s, r1 %s; hand-off pass/keep on r0 %s; keep reason %s; shrink rc %s; new comm %s, "
          "ranks %s, allreduce check %s" % (
              c, len(xs), dict(Counter(x["cause_r0"] for x in xs)), dict(Counter(x["cause_r1"] for x in xs)),
              dict(Counter("%d/%d" % (x["n_hoff_ok_r0"], x["n_hoff_keep_r0"]) for x in xs)),
              dict(Counter(x["hoff_why_r0"] for x in xs)), dict(Counter(x["ho_shrink_rc"] for x in xs)),
              [x["ho_newcomm"] for x in xs], [x["ho_newcomm_nranks"] for x in xs], [x["ho_check_ok"] for x in xs]))
    for c in ("pq4_kill3_shrink@hq", "pq4_local_shrink@hq", "pq4_local_shrink@hf"):
        xs = J[c]
        p("- %s (n=%d): hand-off pass lines %s, keep lines %s; rank 0 keep reason %s; child outcomes %s; child ranks "
          "created %s; ok %s; timeout %s; child tx ok sum %s, rx ok sum %s; child devComm rc %s, GIN contexts %s, "
          "devComm ms %s, shrink ms %s, child async %s; local causes %s" % (
              c, len(xs), [x["n_hoff_ok"] for x in xs], [x["n_hoff_keep"] for x in xs],
              dict(Counter(x["keep_why_r0"] for x in xs)), dict(Counter(x["ch_outcomes"] for x in xs)),
              [x["ch_created_ranks"] for x in xs], [x["ch_ok_ranks"] for x in xs], [x["ch_timeout_ranks"] for x in xs],
              [x["ch_tx_ok_sum"] for x in xs], [x["ch_rx_ok_sum"] for x in xs], sorted(set(x["ch_devcomm_rc"] for x in xs)),
              sorted(set(x["ch_gin_contexts"] for x in xs)), rng([v for x in xs for v in x["ch_devcomm_ms"]]),
              rng([v for x in xs for v in x["ch_shrink_ms"]]), sorted(set(x["ch_async"] for x in xs)),
              [x["n_cause_local"] for x in xs]))
    p()
    p("### Regression cells")
    for c in ("f1_b@hq", "f3_b@hq", "bidirf_sym_b@hq", "mr4_none@hq", "mr4_f1_01@hq"):
        xs = J[c]
        p("- %s (n=%d): transparent %d/%d (outcome-based check %d/%d)" % (
            c, len(xs), sum(x["transparent_ok"] for x in xs), len(xs),
            sum(x.get("transparent_alt", x["transparent_ok"]) for x in xs), len(xs)))
    xs = J["f1_b@hq"]
    p("- f1_b@hq statistics API rounds/recovered/declined r0 %s r1 %s" % (
        ["%g/%g/%g" % (x["rs_rounds_r0"], x["rs_recovered_r0"], x["rs_declined_r0"]) for x in xs],
        ["%g/%g/%g" % (x["rs_rounds_r1"], x["rs_recovered_r1"], x["rs_declined_r1"]) for x in xs]))
    for c in ("f4_b@hq", "hdp_kill_b@hqp"):
        xs = J[c]
        p("- %s (n=%d): decline after kill %s ms; reasons %s; cause r0 %s; devComm-word why %s; abort %s; rs_deaths %s; "
          "ts_on r0/r1 %s" % (c, len(xs), rng([x["decl_after_kill_ms_r0"] for x in xs], "%.2f"),
                             dict(Counter(x["declwhy_r0"] for x in xs)), dict(Counter(x["cause_r0"] for x in xs)),
                             dict(Counter(x["uaerr_why_r0"] for x in xs)), dict(Counter(x["teardown_r0"] for x in xs)),
                             [x["rs_deaths_r0"] for x in xs], sorted(set("%d/%d" % (x["ts_on_r0"], x["ts_on_r1"]) for x in xs))))
    xs = J["hd_rxdeath_b@hq"]
    p("- hd_rxdeath_b@hq (n=%d): rank 1 release after kill %s ms, async after kill %s ms, rx rc %s, judged dead %s, abort %s" % (
        len(xs), rng([x["release_after_kill_ms_r1"] for x in xs], "%.1f"), rng([x["async_after_kill_ms_r1"] for x in xs], "%.1f"),
        dict(Counter(x["rx_rc"] for x in xs)), [x["n_judged_r1"] for x in xs], dict(Counter(x["teardown_r1"] for x in xs))))
    xs = J["f2rel_b@hq"]
    p("- f2rel_b@hq (n=%d): rank 0 declines %s; rank 1 outcome %s; rx rc %s; phantom %s; rank 1 abort %s in %s ms" % (
        len(xs), dict(Counter(x["decl_r0"] for x in xs)), dict(Counter(x["r1_outcome"] for x in xs)),
        dict(Counter(x["rx_rc"] for x in xs)), [x["rx_phantom_r1"] for x in xs], dict(Counter(x["teardown_r1"] for x in xs)),
        rng([x["teardown_ms_r1"] for x in xs], "%.0f")))
    xs = J["hd_shrink_b@hq"]
    p("- hd_shrink_b@hq (n=%d): see the hand-off line above" % len(xs))
    p()
    p("### Latency (p50 of each run, µs; median over the runs of a cell)")
    for size in ("lat_4k", "lat_256k"):
        a, b = J[size + "@hqp"], J[size + "@hfp"]
        va = [x["lat_p50_us"] for x in sorted(a, key=lambda t: int(t["trial"][1:]))]
        vb = [x["lat_p50_us"] for x in sorted(b, key=lambda t: int(t["trial"][1:]))]
        ra = [x["lat_raw_p50_us"] for x in sorted(a, key=lambda t: int(t["trial"][1:]))]
        rb = [x["lat_raw_p50_us"] for x in sorted(b, key=lambda t: int(t["trial"][1:]))]
        p("- %s: hqp runs %s (median %.2f); hfp runs %s (median %.2f); difference of medians %+.2f µs; raw-sample p50 "
          "equals kv p50 in %d/%d runs; samples per run %s" % (
              size, va, statistics.median(va), vb, statistics.median(vb), statistics.median(va) - statistics.median(vb),
              sum(1 for x in a + b if x["lat_raw_p50_us"] is not None and abs(x["lat_raw_p50_us"] - x["lat_p50_us"]) < 0.006),
              len(a + b), sorted(set(x["lat_raw_n"] for x in a + b))))
    p()
    # ---------------- pilot statements (EXPERIMENT.md 12) ----------------
    if "--pilots" in sys.argv:
        p("## Pilot statements of EXPERIMENT.md 12 (pilots are not scored; read only to check the text)")
        for pd in PILOTS:
            pr = load(pd)
            p("- %s: %d trials %s" % (os.path.basename(pd), len(pr), dict(Counter(x["key"] for x in pr))))
            for x in pr:
                c = x["key"]
                if c.startswith("pq_ackrace"):
                    mr_, rs = RACE[x["cell"]]
                    tear = fnum((x["_kv"][rs] or {}).get("abort_start_mono_ms"))
                    p("  - %s: decline after mute end r%d %s ms (%s); responder r%d decline→abort start %s ms; responder "
                      "first decline %r; cancel r%d at %s ms after round; mute end − cancel %s ms; config end_wait %s" % (
                          c, mr_, "%.0f" % x["decl_after_unmute_ms_r%d" % mr_] if x["decl_after_unmute_ms_r%d" % mr_] is not None else "-",
                          x["declwhy_r%d" % mr_], rs,
                          "%.0f" % (tear - x["decl_ms_r%d" % rs]) if tear and x["decl_ms_r%d" % rs] else "-",
                          x["declwhy_r%d" % rs], mr_,
                          "%.0f" % (x["cancel_ms_r%d" % mr_] - float(x["_lg"][mr_].ev["round"][0][6]))
                          if x["cancel_ms_r%d" % mr_] and x["_lg"][mr_].ev["round"] else "-",
                          "%.0f" % (x["muteoff_ms_r%d" % mr_] - x["cancel_ms_r%d" % mr_]) if x["cancel_ms_r%d" % mr_] else "-",
                          x["end_wait_r%d" % rs]))
                elif c.startswith("pq_repost_r1_b"):
                    rd = x["_lg"][0].ev["round"]
                    p("  - %s: rank 0 round -> decline %s ms (%r); rank 0 plan lines %d; recovered lines r0 %d; rank 1 "
                      "plan rejected at qp %s of %s; causes %s/%s" % (
                          c, "%.1f" % (x["decl_ms_r0"] - float(rd[0][6])) if rd and x["decl_ms_r0"] else "-", x["declwhy_r0"],
                          x["n_planok_r0"], x["rec_init_r0"] + x["rec_resp_r0"], x["planrej_qp_r1"], x["planrej_total_r1"],
                          x["cause_r0"], x["cause_r1"]))
                elif c == "pq_rdv_b@hq":
                    p("  - %s: held %s used %.0f decoy %s conns %s bytes %s rdv %s/%s decoy %s transparent %s" % (
                        c, x["occupy_port"], x["port"], x["decoy_port"], x["decoy_conns"], x["decoy_bytes"], x["rdv_r0"],
                        x["rdv_r1"], x["rdv_decoy_r1"], x["transparent_ok"]))
                elif c.startswith("lat_"):
                    p("  - %s: p50 %.2f" % (c, x["lat_p50_us"]))
                elif c == "hd_fwslow_f1_b@hq":
                    p("  - %s: trip %s ms phase %s; abort %s ms; orphan %s; rank 1 decline %r" % (
                        c, x["fwover_ms_r0"], x["fwover_phase_r0"], x["teardown_ms_r0"], x["n_orphan_r0"], x["declwhy_r1"]))
                elif c.startswith("pq4_fwslow"):
                    d0 = [float(d[4]) for d in x["_lg"][0].ev["decl"] if d[1] == "1"]
                    f2 = [float(g[1]) for g in x["_lg"][2].ev["fired"]]
                    f0 = [float(g[1]) for g in x["_lg"][0].ev["fired"]]
                    p("  - %s: rank 0 decline of rank 1 %s ms after its hook; rank 2 hook %s ms after it; decl %s; bad edges %s" % (
                        c, "%.0f" % (d0[0] - f0[0]) if d0 and f0 else "-", "%.0f" % (f2[0] - d0[0]) if d0 and f2 else "-",
                        x["decl"], x["edges_bad"]))
                elif c.startswith("pq4_kill3_shrink") or c.startswith("mr4_kill3_peer"):
                    p("  - %s: decline after kill %s; judged after kill %s; decline after judged %s; shrink ms %s; child "
                      "devComm ms %s; child %s" % (
                        c, rng([x["decl_after_kill_ms_r%d" % r] for r in range(3)]),
                        rng([x["judged_after_kill_ms_r%d" % r] for r in range(3)]),
                        rng([x["decl_after_judged_ms_r%d" % r] for r in range(3)], "%.2f"),
                        x["ch_shrink_ms"], x["ch_devcomm_ms"], x["ch_outcomes"]))
                elif c.startswith("pq4_local_shrink") or c == "pq4_rdv@hq":
                    p("  - %s: children %s; keep %r; rcs %s; decoy %s/%s; skipped %s" % (
                        c, x["ch_outcomes"], x["keep_why_r0"], x["rcs"], x["decoy_conns"], x["decoy_bytes"], x["port_skipped"]))
        p()
    p("## COLUMN NOTES")
    p("- transparent_ok (two ranks): every sender tx_done == iters with tx_rc 'no error'; every receiver rx_done == iters, "
      "rx_rc 'no error', dev_bad_slots 0, host_bad_slots 0, signal_exact 1; async_first 'none' on both ranks (the driver "
      "header's definition). Cross-checked against 'both outcome=ok and both rc 0'.")
    p("- decl_r*: every decline reason of that rank joined with ';'. declwhy/decl_ms: the first. rec_init_r0: rank 0's "
      "'recovered ... role=initiator' lines. n_rec_any: 'recovered' lines on both ranks.")
    p("- lists in four-rank columns are sorted and joined with ';' (multirank 3.1); async_ranks with ','.")
    p("- kill_in_traffic: the kill (rank 0 clock) after every rank's kernel launch and >= 5000 ms before the earliest "
      "nominal traffic end (launch + iters x gap).")
    print("\n".join(OUT))


if __name__ == "__main__":
    main()
