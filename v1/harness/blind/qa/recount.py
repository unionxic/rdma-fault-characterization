#!/usr/bin/env python3
"""qa/recount.py - blind-apps: independent recount of the main run (EXPERIMENT.md 10, "another agent recounts").

    python3 qa/recount.py [--results results/20261009] [--judgments <csv>] [--trials]

Read-only. It writes nothing and changes nothing; it prints the report. It does not import, run or read score.py or
rows_blind.py, nor any table the scorer wrote (SCORE.md, trials_scored.csv). Its own regexes and rules come from
EXPERIMENT.md 3.1 (the definitions) and from looking at the raw logs. It imports strip_hooks.view only to rebuild the
evaluator's view for the leak check (that module is the view generator, not the scorer).

Inputs: the opened seal <results>/schedule.json, raw/<id>/{r0,r1,a0,a1}.log and trial.meta, the reference runs
raw/ref-<wl>-*/, judgments.csv, predictions.csv, calib.json, schedule_config.json, PREREG.txt and the git objects of
the tag prereg/blind-apps-v1 and of the judgments commit (git cat-file, git log; no filters, no hooks).
Every raw line that is printed has its IPv4 addresses masked.

Sections: 1 integrity, 2 exclusions, 3 outcome per class vs truth, 4 predictions, 5 evaluator, 6 leak.
"""
import argparse, csv, datetime, glob, hashlib, json, math, os, random, re, subprocess, sys
from collections import Counter, OrderedDict, defaultdict

sys.dont_write_bytecode = True  # read-only: importing strip_hooks must not write a .pyc

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)                         # harness/blind
TAG = "prereg/blind-apps-v1"
TAG_COMMIT = "7a839ea7"
JUDG_COMMIT = "46419a49"
JUDG_SHA_PREFIX = "afb3ae06"
REL = "harness/blind/"
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


def mask(s):
    return IPV4.sub("<ip>", s)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    with open(p, "rb") as f:
        return sha256_bytes(f.read())


def git(*a, binary=False):
    r = subprocess.run(["git", "-C", STUDY] + list(a), capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout if binary else r.stdout.decode().strip()


def blob(rev, path):
    """Raw blob bytes at rev:path (git cat-file runs no filter)."""
    return git("cat-file", "blob", "%s:%s" % (rev, path), binary=True)


# ===================================================================== raw parsing
def read_log(p):
    out = []
    try:
        with open(p, errors="replace") as f:
            for l in f:
                t, _, rest = l.rstrip("\n").partition(" ")
                try:
                    out.append((float(t), rest))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def first(lines, rx):
    for t, l in lines:
        if rx.search(l):
            return t, l
    return None, None


# ===================================================================== my own definitions (EXPERIMENT.md 3.1)
ANCHOR = {"ddp": re.compile(r"^iter 0: loss"),
          "gin": re.compile(r"=== Comparing GIN ring-exchange implementations ==="),
          "nvs": re.compile(r"^\[nvshmem-t1\] PE0 [0-9.]+ enabled:")}
START_FAIL = {"nvs": re.compile(r"nvshmemi_setup_transport failed|heap registration setup failed")}
BUILD_OK = {"ddp": [re.compile(r"NCCL version 2\.23\.4"), re.compile(r"\[FAULT-RECOVERY2\] recovery on for")],
            "gin": [re.compile(r"GIN/TS: transparent recovery ON rank=")],
            "nvs": [re.compile(r"^\[nvshmem-t1\] PE%d [0-9.]+ enabled:")]}      # %d = the rank
RECOVERY_OFF = {"ddp": re.compile(r"recovery off for this"),
                "gin": re.compile(r"transparent recovery OFF"),
                "nvs": re.compile(r"transparent mode off")}
# hook fire lines on the target rank: (fire-time line, applied line, group with the moved-QP count or None)
FIRE = {("ddp", "sqp"): (r"\[FAULT-INJECT\] forced send QP", None),
        ("ddp", "rqp"): (r"\[FAULT-INJECT\] forced recv QP .*before receive post", None),
        ("ddp", "srq"): (r"\[FAULT-INJECT\] forced recv QP .*\[silent\]", None),
        ("gin", "qperr"): (r"GIN/FAULT: GDAKI fault fired", r"GIN/FAULT: GDAKI fault fired .*moved (\d+)/\d+ GIN QP"),
        ("nvs", "qperr"): (r"\[nvshmem-fault-inject\] shot \d+ fire_mono_ms", r"\[nvshmem-fault-inject\] moved (\d+) QP\(s\) to ERR"),
        ("nvs", "remacc"): (r"\[nvshmem-fault-inject\] shot \d+ fire_mono_ms",
                            r"\[nvshmem-fault-inject\] revoked remote access on (\d+) RC QP")}
# error lines (3.1 "오류 줄"); the gin list adds the example's and NCCL's own failure lines next to the listed ones
ERR = {
    "ddp": re.compile(r"Watchdog caught collective operation timeout|ProcessGroupNCCL.*(Exception|[Ee]rror)|"
                      r"DistBackendError|NCCL error|nccl(Remote|System|Internal|InvalidUsage|InvalidArgument|"
                      r"UnhandledCuda)Error|terminate called|Traceback \(most recent call last\)|FAILED in|"
                      r"peer process gone|Got completion from peer|WAITREQ"),
    "gin": re.compile(r"GIN/TS: declined rank=|judged dead|why=(declined|peer-dead|fw-watchdog)|"
                      r"watchdog (fired|surfaced|exposed|expired)|Failed, NCCL error|Failed: Cuda error|ERROR:|"
                      r"GIN/REC: (commit failed|recovery aborted|prepare declined)|Got completion from peer|"
                      r"GIN Error detected|GIN error raised|Failed NCCL operation"),
    "nvs": re.compile(r"DECLINE|marked failed|transparent mode off|[Cc][Uu][Dd][Aa] (error|failed)|CUDA_ERROR|"
                      r"cudaError|error status: \d+ \(|non-zero status:|NVSHMEM ERROR"),
}
TIMEOUT = {"ddp": re.compile(r"Watchdog caught collective operation timeout|WAITREQ")}
RECOV = {"ddp": re.compile(r"\[FAULT-RECOVERY2\] (send|recv) comm: recovered"),
         "gin": re.compile(r"GIN/TS: recovered rank="),
         "nvs": re.compile(r"RECOVERED (initiator|responder)")}
DEATH = {"ddp": re.compile(r"peer process gone|peer dead"),
         "gin": re.compile(r"judged dead|liveness=dead"),
         "nvs": re.compile(r"FAULT .*peer_fin=1")}
MGMT = {"ddp": re.compile(r"OOB socket lost"),
        "gin": re.compile(r"GIN/TS: .*(socket .*(lost|timed out|re-?connected|re-?dial)|liveness=suspect)"),
        "nvs": re.compile(r"library socket (lost|re-dialed|re-accepted)")}
DDP_HASH = re.compile(r"^\[ddp-entry\] rank=(\d) final iter=(\d+) parameters sha256=([0-9a-f]{64})")
GIN_PASS = re.compile(r"GIN Ring Exchange result: PASSED")
GIN_FAIL = re.compile(r"GIN Ring Exchange result: FAILED|mismatch at CTA")
NVS_SIZE = re.compile(r"^(16777216|33554432|67108864)B\s+[0-9.]+ms")
NVS_VAL = re.compile(r"error, data\[")


# ===================================================================== schedule re-derivation (schedule_gen.py format)
def draw(cfg, seed_hex):
    rng = random.Random(int(seed_hex, 16))
    nhex = int(cfg.get("trial_id_hex_digits", 8))
    used, trials = set(), []
    for wl in sorted(cfg["workloads"]):
        w = cfg["workloads"][wl]
        lst = [c for c in sorted(w["classes"]) for _ in range(int(w["classes"][c]))]
        rng.shuffle(lst)
        per = int(w["per_hold"])
        for i, c in enumerate(lst):
            while True:
                tid = "%0*x" % (nhex, rng.getrandbits(4 * nhex))
                if tid not in used:
                    used.add(tid)
                    break
            target = rng.choice([0, 1]) if c in w["targeted"] else None
            u_t, u_d = rng.random(), rng.random()
            d = rng.choice(cfg["mute_directions"]) if c == "mute" else None
            trials.append({"id": tid, "workload": wl, "order": i, "hold": "%s%d" % (w["hold_prefix"], i // per + 1),
                           "cls": c, "target": target, "u_t": round(u_t, 6), "u_d": round(u_d, 6), "dir": d})
    return trials


HOOKS = {("ddp", "sqp"), ("ddp", "rqp"), ("ddp", "srq"), ("gin", "qperr"), ("nvs", "qperr"), ("nvs", "remacc")}


def my_derive(e, calib, cfg):
    """EXPERIMENT.md 7 'time mapping', written from the text (lo + u_t (hi - lo), rounded as the runner records)."""
    wl, cls, out = e["workload"], e["cls"], {}
    c = calib[wl]
    lerp = lambda r, u: r[0] + u * (r[1] - r[0])
    if wl == "ddp" and cls in ("sqp", "rqp", "srq"):
        out["k"] = int(round(lerp(c[{"sqp": "k_send", "rqp": "k_recv", "srq": "k_silent"}[cls]], e["u_t"])))
    elif (wl, cls) in HOOKS:
        out["t_ms"] = int(round(lerp(c["hook_ms"], e["u_t"])))
    if cls in ("kill", "stop", "mute"):
        if wl == "ddp":
            out["at_iter"] = int(round(lerp(c["iter_window"], e["u_t"])))
            out["t_after_anchor_s"] = 0.0
        else:
            out["t_after_anchor_s"] = round(lerp(c["anchor_window_s"], e["u_t"]), 3)
    if cls in ("stop", "mute"):
        out["d_s"] = round(lerp(cfg["durations_s"][cls][wl], e["u_d"]), 3)
    return out


def my_hook_env(wl, cls, p):
    if (wl, cls) == ("ddp", "sqp"):
        return {"NCCL_RDMA_FAULT_INJECT": str(p["k"])}
    if (wl, cls) == ("ddp", "rqp"):
        return {"NCCL_RDMA_FAULT_INJECT_RECV": str(p["k"])}
    if (wl, cls) == ("ddp", "srq"):
        return {"NCCL_RDMA_FAULT_INJECT_RECV": str(p["k"]), "NCCL_RDMA_FAULT_INJECT_RECV_SILENT": "1"}
    if (wl, cls) == ("gin", "qperr"):
        return {"NCCL_GIN_FAULT_INJECT": "local_err:%d" % p["t_ms"]}
    if (wl, cls) == ("nvs", "qperr"):
        return {"NVSHMEM_IBGDA_FAULT_INJECT": "local_err:%d" % p["t_ms"]}
    if (wl, cls) == ("nvs", "remacc"):
        return {"NVSHMEM_IBGDA_FAULT_INJECT": "rem_access:%d" % p["t_ms"]}
    return {}


# ===================================================================== 1. integrity
def integrity(R, seal, judg_path):
    res = []

    def ok(name, cond, detail=""):
        res.append((name, bool(cond), detail))

    tag_commit = git("rev-parse", TAG + "^{commit}") or ""
    ok("tag %s -> commit %s" % (TAG, TAG_COMMIT), tag_commit.startswith(TAG_COMMIT), tag_commit[:12])
    prereg_wt = open(os.path.join(STUDY, "PREREG.txt"), "rb").read()
    prereg_tag = blob(TAG, REL + "PREREG.txt")
    ok("PREREG.txt: working tree == tag", prereg_tag == prereg_wt)
    entries = re.findall(r"^(\S+) sha256 ([0-9a-f]{64})$", prereg_wt.decode(), re.M)
    bad_wt, bad_tag = [], []
    seal_rec = None
    for f, h in entries:
        if f == "schedule.json":
            seal_rec = h
            continue
        if sha256_file(os.path.join(STUDY, f)) != h:
            bad_wt.append(f)
        b = blob(TAG, REL + f)
        if b is None or sha256_bytes(b) != h:
            bad_tag.append(f)
    ok("PREREG.txt: %d tool/config sha256 == working tree" % (len(entries) - 1), not bad_wt, " ".join(bad_wt))
    ok("PREREG.txt: %d tool/config sha256 == blobs at the tag" % (len(entries) - 1), not bad_tag,
       ("differ: " + " ".join(bad_tag)) if bad_tag else "")
    if bad_tag:
        # explain a difference without printing it: equal once every IPv4 address is masked?
        expl = []
        for f in bad_tag:
            wt = open(os.path.join(STUDY, f), "rb").read().decode().splitlines()
            tb = (blob(TAG, REL + f) or b"").decode().splitlines()
            diff = [i + 1 for i, (x, y) in enumerate(zip(wt, tb)) if x != y]
            same = len(wt) == len(tb) and all(mask(x) == mask(y) for x, y in zip(wt, tb))
            expl.append("%s: %d line(s) differ (line %s), equal after masking IPv4 addresses: %s; working-tree "
                        "mtime before the tag: %s" % (f, len(diff), ",".join(map(str, diff)), same,
                                                     os.stat(os.path.join(STUDY, f)).st_mtime < int(git("log", "-1", "--format=%ct", TAG))))
        ok("  -> tag-blob difference is only an IPv4 address (committed copy masked, PREREG hashed the file that ran)",
           all("equal after masking IPv4 addresses: True; working-tree mtime before the tag: True" in e for e in expl),
           " | ".join(expl))

    seal_path = os.path.join(R, "schedule.json")
    seal_sha = sha256_file(seal_path)
    ok("seal sha256 == PREREG.txt", seal_sha == seal_rec, seal_sha[:16])
    side = open(os.path.join(R, "schedule.json.sha256")).read().split()[0]
    ok("seal sha256 == schedule.json.sha256", side == seal_sha)
    holds_logged = re.findall(r"hold (\S+) schedule sha256 ([0-9a-f]{64})", open(os.path.join(R, "schedule_sha256.txt")).read())
    ok("runner's per-hold seal sha256 (schedule_sha256.txt, %d lines) == PREREG.txt" % len(holds_logged),
       holds_logged and all(h == seal_rec for _, h in holds_logged), " ".join(sorted(set(x for x, _ in holds_logged))))

    h = seal["header"]
    cfg_wt = json.load(open(os.path.join(STUDY, "schedule_config.json")))
    ok("seal header config == schedule_config.json", h["config"] == cfg_wt)
    ok("seal header config_sha256 == schedule_config.json", h["config_sha256"] == sha256_file(os.path.join(STUDY, "schedule_config.json")))
    ok("seal header predictions_sha256 == predictions.csv", h["predictions_sha256"] == sha256_file(os.path.join(STUDY, "predictions.csv")))
    ok("seal header generator_sha256 == schedule_gen.py", h["generator_sha256"] == sha256_file(os.path.join(STUDY, "schedule_gen.py")))
    gh = h["git_head"]
    same = all(blob(gh, REL + f) == blob(TAG, REL + f) for f in ("predictions.csv", "schedule_config.json", "schedule_gen.py"))
    anc = subprocess.run(["git", "-C", STUDY, "merge-base", "--is-ancestor", gh, TAG], capture_output=True).returncode == 0
    ok("seal git_head %s is an ancestor of the tag; predictions, config, generator unchanged from it to the tag" % gh[:8],
       same and anc)
    tag_time = int(git("log", "-1", "--format=%ct", TAG) or 0)
    tag_iso = datetime.datetime.fromtimestamp(tag_time).isoformat(timespec="seconds")
    ok("seal created (%s) before the tag commit" % h["created"], tag_time and h["created"] < tag_iso, "tag %s" % tag_iso)
    redraw = draw(h["config"], h["seed_hex"])
    ok("seal trials re-derive from the recorded seed (%d trials)" % len(redraw), redraw == seal["trials"])

    # every trial's recorded entry and parameters
    calib = json.load(open(os.path.join(STUDY, "calib.json")))
    trials = {t["id"]: t for t in seal["trials"]}
    dirs = sorted(os.listdir(os.path.join(R, "raw")))
    blind_dirs = [d for d in dirs if not d.startswith("ref-")]
    partial = [d for d in dirs if ".partial" in d]
    ok("raw/: one folder per seal trial, no extra, no .partial", sorted(blind_dirs) == sorted(trials) and not partial,
       "raw blind %d, seal %d, partial %d" % (len(blind_dirs), len(trials), len(partial)))
    bad_e, bad_p, bad_h, bad_k = [], [], [], []
    for tid, t in trials.items():
        m = json.load(open(os.path.join(R, "raw", tid, "trial.meta")))
        if m.get("entry") != t:
            bad_e.append(tid)
        p = my_derive(t, calib, h["config"])
        if m.get("params") != p:
            bad_p.append(tid)
        he = my_hook_env(t["workload"], t["cls"], p) if (t["workload"], t["cls"]) in HOOKS else {}
        if m.get("hook_env") != he or (he and m.get("hook_rank") != t["target"]):
            bad_h.append(tid)
        if m.get("kind") != "blind" or m.get("id") != tid:
            bad_k.append(tid)
    ok("trial.meta entry == seal entry (all %d)" % len(trials), not bad_e, " ".join(bad_e))
    ok("trial.meta params == params re-derived from the seal, calib.json, config", not bad_p, " ".join(bad_p))
    ok("trial.meta hook env and hook rank == the seal's class and target", not bad_h, " ".join(bad_h))
    ok("trial.meta kind == blind, id == folder", not bad_k, " ".join(bad_k))
    refs = [d for d in dirs if d.startswith("ref-")]
    ok("reference runs: 4 per workload (B0 3 + B9 1), kind baseline",
       Counter(d.split("-")[1] for d in refs) == Counter({"ddp": 4, "gin": 4, "nvs": 4}) and
       all(json.load(open(os.path.join(R, "raw", d, "trial.meta")))["kind"] == "baseline" for d in refs))

    # judgments
    jb = open(judg_path, "rb").read()
    jsha = sha256_bytes(jb)
    ok("judgments.csv sha256 starts %s" % JUDG_SHA_PREFIX, jsha.startswith(JUDG_SHA_PREFIX), jsha[:16])
    jc = blob(JUDG_COMMIT, REL + "results/20261009/judgments.csv")
    ok("judgments.csv == blob in commit %s" % JUDG_COMMIT, jc == jb)
    files = (git("diff-tree", "--no-commit-id", "--name-only", "-r", JUDG_COMMIT) or "").split()
    ok("commit %s changes only judgments.csv" % JUDG_COMMIT, files == [REL + "results/20261009/judgments.csv"], " ".join(files))
    par = git("rev-parse", JUDG_COMMIT + "^") or ""
    ok("commit %s's parent is the tagged commit" % JUDG_COMMIT, par.startswith(TAG_COMMIT), par[:8])
    ct = int(git("log", "-1", "--format=%ct", JUDG_COMMIT) or 0)
    reflog = git("log", "-g", "--format=%H %gd", "--date=unix", "exp/blind-apps") or ""
    jfull = git("rev-parse", JUDG_COMMIT)
    rt = [int(re.search(r"@\{(\d+)\}", l).group(1)) for l in reflog.splitlines() if l.startswith(jfull)]
    st_seal = os.stat(seal_path).st_mtime
    st_side = os.stat(os.path.join(R, "schedule.json.sha256")).st_mtime
    ok("judgments commit time and reflog time precede the seal copy's mtime",
       ct and rt and max(ct, max(rt)) < min(st_seal, st_side),
       "commit %d, reflog %s, seal mtime %.2f (%.1f s later)" % (ct, rt, st_seal, min(st_seal, st_side) - max([ct] + rt)))
    raw_m = max(os.stat(p).st_mtime for p in glob.glob(os.path.join(R, "raw", "*", "*")))
    ok("every raw file predates the judgments commit", raw_m < ct, "last raw mtime %.0f" % raw_m)
    jrows = list(csv.DictReader(open(judg_path)))
    ok("judgments: one row per seal trial, workload matches",
       sorted(r["trial_id"] for r in jrows) == sorted(trials) and
       all(trials[r["trial_id"]]["workload"] == r["workload"] for r in jrows), "%d rows" % len(jrows))

    # frozen sections of EXPERIMENT.md
    def sections(b):
        out, cur = {}, None
        for l in b.decode().splitlines(True):
            m = re.match(r"^## (\d+)\.", l)
            if l.startswith("## "):
                cur = m.group(1) if m else None
            if cur:
                out[cur] = out.get(cur, "") + l
        return out
    s_wt = sections(open(os.path.join(STUDY, "EXPERIMENT.md"), "rb").read())
    s_tag = sections(blob(TAG, REL + "EXPERIMENT.md"))
    for k in ("2", "3", "7", "8"):
        ok("EXPERIMENT.md section %s byte-identical to the tag" % k, k in s_wt and s_wt[k] == s_tag.get(k),
           "%d bytes" % len(s_wt.get(k, "").encode()))
    ok("EXPERIMENT.md whole file == tag (informational)", open(os.path.join(STUDY, "EXPERIMENT.md"), "rb").read() ==
       blob(TAG, REL + "EXPERIMENT.md"))
    stops = [f for f in os.listdir(R) if f.startswith("STOP_")]
    ok("no STOP_* file in the results folder", not stops, " ".join(stops))
    new_mlx = [f for f in glob.glob(os.path.join(R, "mlx5_new_*.txt")) if os.path.getsize(f) > 0]
    ok("mlx5 new-line files empty (10 holds)", not new_mlx and len(glob.glob(os.path.join(R, "mlx5_new_*.txt"))) == 10)
    return res


# ===================================================================== per-trial recount
def agent_info(alog):
    rc = t_exit = None
    sigs = []
    for t, l in alog:
        m = re.match(r"AGENT exit pid=\d+ rc=(-?\d+)", l)
        if m:
            rc, t_exit = int(m.group(1)), t
        m = re.match(r"AGENT sig=(\w+) pid=\d+ rc=(-?\d+)", l)
        if m:
            sigs.append((t, m.group(1), int(m.group(2))))
    return rc, t_exit, sigs


def ref_hashes(R):
    hs = defaultdict(set)
    for d in sorted(glob.glob(os.path.join(R, "raw", "ref-ddp-*"))):
        for r in (0, 1):
            for t, l in read_log(os.path.join(d, "r%d.log" % r)):
                m = DDP_HASH.match(l)
                if m:
                    hs[int(m.group(1))].add(m.group(3))
    return {r: (next(iter(v)) if len(v) == 1 else None) for r, v in hs.items()}, hs


def recount_trial(R, tid, refh, kind_override=None):
    d = os.path.join(R, "raw", tid)
    m = json.load(open(os.path.join(d, "trial.meta")))
    e = m["entry"]
    wl, cls, target = e["workload"], e["cls"], e.get("target")
    L = {r: read_log(os.path.join(d, "r%d.log" % r)) for r in (0, 1)}
    A = {r: agent_info(read_log(os.path.join(d, "a%d.log" % r))) for r in (0, 1)}
    row = OrderedDict(id=tid, kind=m["kind"], hold=e.get("hold", ""), workload=wl, cls=cls,
                      target="" if target is None else target, dir=e.get("dir") or "")
    fault = m.get("fault", {})
    # --- applied and fault time
    t_fault = None
    applied = 0
    why = ""
    if cls == "none":
        applied, why = 1, "no fault to apply"
    elif (wl, cls) in FIRE:
        fire_rx, app_rx = FIRE[(wl, cls)]
        tf, _ = first(L[target], re.compile(fire_rx))
        if app_rx:
            ta, la = first(L[target], re.compile(app_rx))
            applied = int(ta is not None and int(re.search(app_rx, la).group(1)) >= 1)
        else:
            applied = int(tf is not None)
        t_fault = tf
        why = "fire line" if applied else "no fire line"
    elif cls in ("kill", "stop"):
        # the agent's acknowledgement of the scheduled signal: the first sig of that kind in the target's agent log
        acks = [(t, rc) for t, s, rc in A[target][2] if s == ("KILL" if cls == "kill" else "STOP")]
        if acks and acks[0][1] == 0 and fault.get("t_ack") is not None and abs(acks[0][0] - fault["t_ack"]) < 1e-3:
            applied, t_fault = 1, acks[0][0]
            why = "ack rc=0"
        else:
            why = "no ack rc=0 (%s)" % (fault.get("skipped") or "")
    elif cls == "mute":
        mu = fault.get("mute") or {}
        if mu.get("t_on") is not None and mu.get("rules_on", 0) > 0:
            applied, t_fault = 1, mu["t_on"]
            why = "%d rules" % mu["rules_on"]
        else:
            why = "skipped (%s)" % (mu.get("skipped") or fault.get("skipped") or "?")
    row["applied"] = applied
    row["applied_why"] = why
    # --- void, config_ok
    t_anchor, _ = first(L[0], ANCHOR[wl])
    sf = [first(L[r], START_FAIL[wl])[0] for r in (0, 1)] if wl in START_FAIL else [None, None]
    sf = [x for x in sf if x is not None]
    fail_evident = (t_anchor is None) or bool(sf)
    t_fail = min(sf) if sf else None
    earlier_fault = applied and t_fault is not None and cls != "none" and (t_fail is None or t_fault < t_fail)
    row["void"] = int(fail_evident and not earlier_fault)
    cfg_ok = True
    for r in (0, 1):
        if not L[r]:
            continue
        txt = [l for _, l in L[r]]
        for rx in BUILD_OK[wl]:
            rx2 = re.compile(rx.pattern % r) if "%d" in rx.pattern else rx
            if not any(rx2.search(l) for l in txt):
                cfg_ok = False
        if any(RECOVERY_OFF[wl].search(l) for l in txt):
            cfg_ok = False
    row["config_ok"] = int(cfg_ok)
    row["valid"] = int(applied == 1 and row["void"] == 0 and cfg_ok)
    # --- exits
    killed = target if (cls == "kill" and applied) else None
    surv = [r for r in (0, 1) if r != killed]
    row["killed_rank"] = "" if killed is None else killed
    for r in (0, 1):
        rc, t_exit, _ = A[r]
        mrc = m["exit"][str(r)]["rc"]
        if rc != mrc:
            row.setdefault("notes", []).append("rank %d rc agent-log %s vs meta %s" % (r, rc, mrc))
        row["rc%d" % r] = rc
        row["end%d" % r] = m["exit"][str(r)]["harness_end"] or ""
    # --- error, recovery, death, mgmt lines
    errs = []
    for r in surv:
        for t, l in L[r]:
            if ERR[wl].search(l):
                errs.append((t, r, l))
    errs.sort()
    row["n_err0"] = sum(1 for _, r, _ in errs if r == 0)
    row["n_err1"] = sum(1 for _, r, _ in errs if r == 1)
    row["err_first"] = mask("r%d %s" % (errs[0][1], errs[0][2][:160])) if errs else ""
    row["timeout_first"] = int(bool(errs) and wl in TIMEOUT and bool(TIMEOUT[wl].search(errs[0][2])))
    row["n_rec"] = sum(1 for r in (0, 1) for _, l in L[r] if RECOV[wl].search(l))
    row["n_death"] = sum(1 for r in surv for _, l in L[r] if DEATH[wl].search(l))
    row["n_mgmt"] = sum(1 for r in (0, 1) for _, l in L[r] if MGMT[wl].search(l))
    # --- result check
    if wl == "ddp":
        if any(v is None for v in refh.values()) or set(refh) != {0, 1}:
            result = "unknown"
        else:
            got = {}
            for r in surv:
                for t, l in L[r]:
                    mm = DDP_HASH.match(l)
                    if mm and int(mm.group(1)) == r:
                        got[r] = mm.group(3)
            if any(r not in got for r in surv):
                result = "none"
            else:
                result = "correct" if all(got[r] == refh[r] for r in surv) else "wrong"
    elif wl == "gin":
        passed = any(GIN_PASS.search(l) for _, l in L[0])
        failed = any(GIN_FAIL.search(l) for r in (0, 1) for _, l in L[r])
        result = "wrong" if failed else ("correct" if passed else "none")
    else:
        sizes = set(NVS_SIZE.match(l).group(1) for _, l in L[0] if NVS_SIZE.match(l))
        nval = sum(1 for r in (0, 1) for _, l in L[r] if NVS_VAL.search(l))
        row["n_val"] = nval
        result = "wrong" if nval else ("correct" if len(sizes) == 3 else "none")
    row["result"] = result
    # --- outcome (3.1 rules, first match)
    hung = any(row["end%d" % r] for r in surv) or row["timeout_first"] == 1
    nonzero = any(row["rc%d" % r] != 0 for r in surv)
    has_err = bool(errs)
    if result == "unknown" and not hung and not has_err and not nonzero:
        oc = "UNKNOWN"
    elif hung:
        oc = "HUNG"
    elif result == "wrong" and not has_err and not nonzero:
        oc = "SILENT_WRONG"
    elif has_err or nonzero:
        oc = "DECLINED"
    elif result == "correct":
        oc = "TRANSPARENT"
    else:
        oc = "OTHER"
    row["outcome"] = oc
    # --- times
    row["dt_err"] = round(errs[0][0] - t_fault, 3) if (errs and t_fault is not None) else ""
    t_ends = [A[r][1] for r in surv if A[r][1] is not None]
    row["dt_end"] = round(max(t_ends) - t_fault, 3) if (t_ends and t_fault is not None and len(t_ends) == len(surv)) else ""
    after = [t for t, _ in L[0] if t_anchor is not None and t >= t_anchor]
    row["max_gap0"] = round(max((b - a for a, b in zip(after, after[1:])), default=0.0), 3) if after else ""
    row["t_fault"] = t_fault
    row["t0"] = m["t0"]
    row["t_anchor"] = t_anchor
    return row, L


# ===================================================================== prediction grammar (3.2), my own evaluator
class Blank:
    """An empty cell: every comparison is false, arithmetic fails (EXPERIMENT.md 3.2)."""
    def _false(self, other):
        return False
    __eq__ = __ne__ = __lt__ = __le__ = __gt__ = __ge__ = _false
    __hash__ = None

    def _fail(self, *a):
        raise TypeError("arithmetic on an empty cell")
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _fail
    __neg__ = __abs__ = __float__ = __int__ = _fail

    def __bool__(self):
        return False

    def __repr__(self):
        return "<blank>"


def env_of(row):
    return {k: (Blank() if v == "" or v is None else v) for k, v in row.items()}


def select(rows, spec):
    keep = []
    parts = [p.split(":") for p in spec.split("+")]
    for r in rows:
        if any((w in ("*", r["workload"])) and (c in ("*", r["cls"])) for w, c in parts):
            keep.append(r)
    return keep


def split_counts(expr):
    """['count(', inner, ')'] pieces: returns the expression with count(...) replaced by {0}, {1}, ... and the inners."""
    out, inners, i = "", [], 0
    while True:
        j = expr.find("count(", i)
        if j < 0:
            out += expr[i:]
            break
        out += expr[i:j]
        k, depth = j + len("count("), 1
        while depth:
            ch = expr[k]
            depth += (ch == "(") - (ch == ")")
            k += 1
        inners.append(expr[j + len("count("):k - 1])
        out += "{%d}" % (len(inners) - 1)
        i = k
    return out, inners


def evaluate(pred, rows):
    sel = select(rows, pred["select"])
    n = len(sel)
    templ, inners = split_counts(pred["acceptance"])
    counts, false_ids = [], []
    for inner in inners:
        c, fids = 0, []
        for r in sel:
            try:
                v = bool(eval(inner, {"__builtins__": {}}, env_of(r)))
            except Exception:
                v = False
            c += v
            if not v:
                fids.append(r["id"])
        counts.append(c)
        false_ids.append(fids)
    expr = templ.format(*counts)
    val = bool(eval(expr, {"__builtins__": {}}, {"n": n, "ceil": math.ceil}))
    reasons = []
    if n < int(pred["n_min"]):
        reasons.append("n %d < n_min %s" % (n, pred["n_min"]))
    if any(r["outcome"] == "UNKNOWN" for r in sel):
        reasons.append("UNKNOWN in selection")
    if pred["kind"] == "E" and any(r.get("j_class", "") == "" or r.get("j_outcome", "") == "" for r in sel):
        reasons.append("trial without a judgment")
    verdict = "INSUFFICIENT" if reasons else ("HOLDS" if val else "FAILS")
    return {"id": pred["id"], "kind": pred["kind"], "select": pred["select"], "n": n, "n_planned": int(pred["n_planned"]),
            "n_min": int(pred["n_min"]), "counts": counts, "expr": expr, "verdict": verdict, "why": "; ".join(reasons),
            "false_ids": false_ids, "acceptance": pred["acceptance"]}


# ===================================================================== 6. leak
def leak_scan(R, rows, Ls):  # noqa: C901
    sys.path.insert(0, STUDY)
    from strip_hooks import HOOK, view  # the evaluator's view generator (not the scorer)
    per = {}
    for row in rows:
        tid = row["id"]
        L = Ls[tid]
        d = {}
        for r in (0, 1):
            raw = L[r]
            # ground truth: blank raw lines whose next raw line is a stripped hook line ("orphan" blanks)
            orphan = [i for i in range(len(raw) - 1) if raw[i][1].strip() == "" and HOOK.search(raw[i + 1][1])]
            stripped = [i for i in range(len(raw)) if HOOK.search(raw[i][1])]
            stripped_real = [i for i in stripped if "blind_ddp_out" not in raw[i][1]]
            v = view(raw, row["t0"])
            # what the evaluator can see: a blank line not followed by a WARN line (double blank, trailing blank,
            # blank before plain text)
            seen = []
            for i, (t, l) in enumerate(v):
                if l.strip() == "":
                    nxt = v[i + 1][1] if i + 1 < len(v) else None
                    if nxt is None or "WARN" not in nxt:
                        seen.append((round(t, 3), "trailing" if nxt is None else ("double" if nxt.strip() == "" else "before-text")))
            d[r] = {"orphan": len(orphan), "orphan_t": [round(raw[i][0] - row["t0"], 3) for i in orphan],
                    "stripped": len(stripped), "stripped_hook": len(stripped_real), "seen": seen}
        per[tid] = d
    return per


# ===================================================================== report
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(STUDY, "results", "20261009"))
    ap.add_argument("--judgments", default=None)
    ap.add_argument("--trials", action="store_true", help="also print one line per trial")
    a = ap.parse_args()
    R = os.path.abspath(a.results)
    jpath = a.judgments or os.path.join(R, "judgments.csv")
    seal = json.load(open(os.path.join(R, "schedule.json")))
    P = print

    P("blind-apps independent recount (qa/recount.py), results %s" % os.path.relpath(R, STUDY))
    P("=" * 100)
    P("1. INTEGRITY")
    res = integrity(R, seal, jpath)
    for name, good, detail in res:
        P("  [%s] %s%s" % ("ok" if good else "FAIL", name, (" -- " + detail) if detail else ""))
    P("  integrity: %d/%d checks pass" % (sum(g for _, g, _ in res), len(res)))

    refh, refsets = ref_hashes(R)
    P("\n  DDP reference hashes per rank (ref-ddp-1..3 = B0, ref-ddp-4 = B9): %s" %
      {r: ("%d distinct: %s" % (len(v), ",".join(x[:12] for x in sorted(v)))) for r, v in sorted(refsets.items())})
    ref_rows = []
    for d in sorted(glob.glob(os.path.join(R, "raw", "ref-*"))):
        rr, _ = recount_trial(R, os.path.basename(d), refh)
        ref_rows.append(rr)
    P("  reference runs: %s" % ", ".join("%s %s/%s err=%d rec=%d" % (r["id"], r["outcome"], r["result"],
                                                                      r["n_err0"] + r["n_err1"], r["n_rec"]) for r in ref_rows))

    trials = {t["id"]: t for t in seal["trials"]}
    rows, Ls = [], {}
    for tid in sorted(trials, key=lambda x: (trials[x]["workload"], trials[x]["hold"], trials[x]["order"])):
        row, L = recount_trial(R, tid, refh)
        rows.append(row)
        Ls[tid] = L
    J = {r["trial_id"]: r for r in csv.DictReader(open(jpath))}
    for row in rows:
        j = J.get(row["id"], {})
        row["j_class"] = j.get("fault_class", "").strip()
        row["j_target"] = j.get("target_rank", "").strip()
        row["j_outcome"] = j.get("outcome", "").strip().upper()
        row["j_ok_outcome"] = int(row["j_outcome"] == row["outcome"]) if row["j_outcome"] else ""
        row["j_ok_class"] = int(row["j_class"] == row["cls"]) if row["j_class"] else ""

    # sanity: the error regex never fires on fault-free runs
    ff = [r for r in rows if r["cls"] == "none"] + ref_rows
    P("  fault-free runs (8+8+8 blind none, 12 references): error lines %d, recovery %d, death %d, mgmt %d, outcomes %s" % (
        sum(r["n_err0"] + r["n_err1"] for r in ff), sum(r["n_rec"] for r in ff), sum(r["n_death"] for r in ff),
        sum(r["n_mgmt"] for r in ff), dict(Counter(r["outcome"] for r in ff))))

    P("\n" + "=" * 100)
    P("2. EXCLUSIONS (EXPERIMENT.md 8): not applied, start failure, build check")
    exc = [r for r in rows if not r["valid"]]
    for r in exc:
        P("  %s %s:%s target=%s applied=%d (%s) void=%d config_ok=%d" % (r["id"], r["workload"], r["cls"], r["target"],
                                                                        r["applied"], r["applied_why"], r["void"], r["config_ok"]))
    P("  excluded %d of %d; valid %d" % (len(exc), len(rows), len(rows) - len(exc)))
    valid = [r for r in rows if r["valid"]]

    P("\n" + "=" * 100)
    P("3. OUTCOME PER CLASS vs TRUTH (valid trials; planned / valid / excluded)")
    OUT = ["TRANSPARENT", "DECLINED", "HUNG", "SILENT_WRONG", "OTHER", "UNKNOWN"]
    P("  %-12s %4s %4s %4s | %s | rec>=1 death>0" % ("cell", "plan", "val", "exc", " ".join("%-6s" % o[:6] for o in OUT)))
    cells = sorted(set((t["workload"], t["cls"]) for t in seal["trials"]))
    for wl, c in cells:
        allc = [r for r in rows if (r["workload"], r["cls"]) == (wl, c)]
        v = [r for r in allc if r["valid"]]
        oc = Counter(r["outcome"] for r in v)
        P("  %-12s %4d %4d %4d | %s | %6d %5d" % ("%s:%s" % (wl, c), len(allc), len(v), len(allc) - len(v),
                                                 " ".join("%-6d" % oc.get(o, 0) for o in OUT),
                                                 sum(1 for r in v if r["n_rec"] >= 1), sum(1 for r in v if r["n_death"] > 0)))
    tot = Counter(r["outcome"] for r in valid)
    P("  %-12s %4d %4d %4d | %s |" % ("all", len(rows), len(valid), len(exc), " ".join("%-6d" % tot.get(o, 0) for o in OUT)))
    P("  result check, valid trials: %s" % dict(Counter((r["workload"], r["result"]) for r in valid)))
    for r in valid:
        if r["outcome"] in ("SILENT_WRONG", "OTHER", "UNKNOWN"):
            P("  ! %s %s:%s target=%s outcome=%s result=%s rc=%s/%s n_val=%s" % (r["id"], r["workload"], r["cls"], r["target"],
                                                                               r["outcome"], r["result"], r["rc0"], r["rc1"], r.get("n_val", "")))

    P("\n" + "=" * 100)
    P("4. PREDICTIONS (predictions.csv; my own evaluator of the 3.2 grammar on valid trials)")
    preds = list(csv.DictReader(open(os.path.join(STUDY, "predictions.csv"))))
    ev = [evaluate(p, valid) for p in preds]
    P("  %-3s %-36s %3s %4s %-14s %-12s %s" % ("id", "select", "n", "plan", "counts", "verdict", "substituted"))
    for x in ev:
        P("  %-3s %-36s %3d %4d %-14s %-12s %s%s" % (x["id"], x["select"], x["n"], x["n_planned"],
                                                  "/".join(map(str, x["counts"])), x["verdict"], x["expr"],
                                                  ("  [" + x["why"] + "]") if x["why"] else ""))
    vc = Counter(x["verdict"] for x in ev)
    P("  verdicts: HOLDS %d, FAILS %d, INSUFFICIENT %d (S: %s; E: %s)" % (
        vc["HOLDS"], vc["FAILS"], vc["INSUFFICIENT"],
        dict(Counter(x["verdict"] for x in ev if x["kind"] == "S")), dict(Counter(x["verdict"] for x in ev if x["kind"] == "E"))))
    P("  per count() term, the smaller of the true and false trial sets:")
    for x in ev:
        sel = set(r["id"] for r in select(valid, x["select"]))
        for i, f in enumerate(x["false_ids"]):
            tr = sorted(sel - set(f))
            if f and len(f) <= len(tr):
                P("    %s term %d false (%d): %s" % (x["id"], i + 1, len(f), " ".join(f)))
            elif tr and len(tr) < len(f):
                P("    %s term %d true (%d): %s" % (x["id"], i + 1, len(tr), " ".join(tr)))
    P("  timing detail (valid trials of the timed predictions):")
    for sel in ("ddp:kill", "ddp:srq", "gin:kill", "nvs:remacc", "nvs:kill"):
        ss = select(valid, sel)
        P("    %-10s dt_err %s; dt_end %s" % (sel, sorted([r["dt_err"] for r in ss if r["dt_err"] != ""]) +
                                              ["blank"] * sum(1 for r in ss if r["dt_err"] == ""),
                                              sorted([r["dt_end"] for r in ss if r["dt_end"] != ""])))

    P("\n" + "=" * 100)
    P("5. EVALUATOR vs MACHINE (all %d valid trials)" % len(valid))
    P("  outcome agreement %d/%d, class agreement %d/%d, target agreement (targeted classes) %d/%d" % (
        sum(r["j_ok_outcome"] == 1 for r in valid), len(valid), sum(r["j_ok_class"] == 1 for r in valid), len(valid),
        sum(1 for r in valid if r["target"] != "" and r["j_target"] == str(r["target"])),
        sum(1 for r in valid if r["target"] != "")))
    conf = Counter((r["outcome"], r["j_outcome"]) for r in valid)
    P("  outcome confusion (machine -> evaluator): %s" % ", ".join("%s->%s %d" % (a_, b_, c_) for (a_, b_), c_ in sorted(conf.items())))
    cconf = Counter((r["workload"] + ":" + r["cls"], r["j_class"]) for r in valid if r["j_class"] != r["cls"])
    P("  class confusion (truth -> evaluator, wrong only): %s" % ", ".join("%s->%s %d" % (a_, b_, c_) for (a_, b_), c_ in sorted(cconf.items())))
    for r in valid:
        if r["j_ok_outcome"] != 1:
            P("    outcome differs: %s %s:%s machine %s, evaluator %s" % (r["id"], r["workload"], r["cls"], r["outcome"], r["j_outcome"]))
    fe = []
    for r in valid:
        j = J[r["id"]].get("first_error_s", "").strip()
        mine = (r["t_fault"] + r["dt_err"] - r["t0"]) if r["dt_err"] != "" else None
        if mine is None:
            # no fault time (none) or no error: take the survivors' first error line directly
            mine = None if not r["err_first"] else "?"
        fe.append((r["id"], j, mine))
    both = [(i, float(j), m) for i, j, m in fe if j and isinstance(m, float)]
    P("  first_error_s: evaluator blank where I find no error after the fault: %d/%d; both present %d, |diff| <= 0.05 s %d; "
      "evaluator gives a time where I find none: %s" % (
          sum(1 for i, j, m in fe if not j and m is None), sum(1 for i, j, m in fe if m is None), len(both),
          sum(1 for i, j, m in both if abs(j - m) <= 0.05), [i for i, j, m in fe if j and m is None]))
    jx = [r for r in rows if not r["valid"]]
    P("  excluded trials' judgments (not scored): %s" % ", ".join("%s %s->%s/%s" % (r["id"], r["cls"], r["j_class"], r["j_outcome"]) for r in jx))

    P("\n" + "=" * 100)
    P("6. BLINDING LEAK (strip_hooks.view rebuilds the evaluator's r<k>.txt; handoff.py adds nothing else to those lines)")
    leak = leak_scan(R, rows, Ls)
    ev = [evaluate(p, valid) for p in preds]
    by = defaultdict(lambda: [0, 0, 0])   # cell -> [trials, trials with an artifact on the target rank only, any artifact]
    vis = Counter()
    exposed = []
    for r in rows:
        lk = leak[r["id"]]
        has = {k: lk[k]["orphan"] > 0 for k in (0, 1)}
        seen = {k: len(lk[k]["seen"]) > 0 for k in (0, 1)}
        cell = "%s:%s" % (r["workload"], r["cls"])
        by[cell][0] += 1
        if any(has.values()):
            by[cell][2] += 1
            if r["target"] != "" and has[r["target"]] and not has[1 - r["target"]]:
                by[cell][1] += 1
            exposed.append(r)
        if any(any(k_ in ("double", "trailing") for _, k_ in lk[k]["seen"]) for k in (0, 1)):
            vis[cell] += 1
    P("  orphan blank = a blank raw line kept in the view whose next raw line was a stripped hook line (ground truth)")
    P("  visible pattern = a double blank or a trailing blank in the view (what the evaluator cited)")
    P("  %-12s %6s %24s %13s %22s" % ("cell", "trials", "orphan on target only", "any orphan", "visible pattern"))
    for cell in sorted(by):
        P("  %-12s %6d %24d %13d %22d" % (cell, by[cell][0], by[cell][1], by[cell][2], vis[cell]))
    refL = {rr["id"]: (read_log(os.path.join(R, "raw", rr["id"], "r0.log")), read_log(os.path.join(R, "raw", rr["id"], "r1.log")))
            for rr in ref_rows}
    rleak = leak_scan(R, ref_rows, {k: {0: v[0], 1: v[1]} for k, v in refL.items()})
    P("  references: orphan blanks %d; visible pattern in %s of 4 per workload" % (
        sum(rleak[k][r]["orphan"] for k in rleak for r in (0, 1)),
        dict(Counter(k.split("-")[1] for k in rleak if any(any(k_ in ("double", "trailing") for _, k_ in rleak[k][r]["seen"])
                                                            for r in (0, 1))))))
    for wl in ("ddp", "gin", "nvs"):
        hk = [r for r in rows if r["workload"] == wl and any(leak[r["id"]][k]["orphan"] for k in (0, 1))]
        nh = [r for r in rows if r["workload"] == wl and not any(leak[r["id"]][k]["orphan"] for k in (0, 1))]
        visf = lambda r: [k for k in (0, 1) if any(k_ in ("double", "trailing") for _, k_ in leak[r["id"]][k]["seen"])]
        P("  %s: visible pattern in %d/%d trials with an orphan (on the target rank only: %d), in %d/%d trials without" % (
            wl, sum(1 for r in hk if visf(r)), len(hk), sum(1 for r in hk if visf(r) == [r["target"]]),
            sum(1 for r in nh if visf(r)), len(nh)))
    # which of the evaluator's class and target calls coincide with exposure
    for wl in ("gin", "ddp"):
        ex = [r for r in exposed if r["workload"] == wl]
        P("  %s exposed trials: %d; evaluator class right %d, target right %d; outcome machine %s" % (
            wl, len(ex), sum(r["j_ok_class"] == 1 for r in ex), sum(r["j_target"] == str(r["target"]) for r in ex),
            dict(Counter(r["outcome"] for r in ex))))
    e2 = [x for x in ev if x["id"] == "E2"][0]
    art_only = [r for r in rows if r["valid"] and r["workload"] == "gin" and r["cls"] == "qperr" and r["outcome"] == "HUNG"
                and not (r["n_rec"] or r["n_err0"] + r["n_err1"] or r["n_death"])]
    k_ = e2["counts"][0]
    P("  E2 sensitivity: %d/%d (needs %d). Counting the %d artifact-only gin qperr trials as misses: %d/%d -> %s; "
      "dropping them: %d/%d (needs %d) -> %s" % (
          k_, e2["n"], math.ceil(0.8 * e2["n"]), len(art_only), k_ - sum(r["j_ok_class"] == 1 for r in art_only), e2["n"],
          "HOLDS" if k_ - sum(r["j_ok_class"] == 1 for r in art_only) >= math.ceil(0.8 * e2["n"]) else "FAILS",
          k_ - sum(r["j_ok_class"] == 1 for r in art_only), e2["n"] - len(art_only), math.ceil(0.8 * (e2["n"] - len(art_only))),
          "HOLDS" if k_ - sum(r["j_ok_class"] == 1 for r in art_only) >= math.ceil(0.8 * (e2["n"] - len(art_only))) else "FAILS"))
    gq = [r for r in rows if r["workload"] == "gin" and r["cls"] == "qperr"]
    P("  gin qperr: trials %d, hung %d; hung trials with a recovery, error or death line: %d (the artifact is their only "
      "class evidence)" % (len(gq), sum(r["outcome"] == "HUNG" for r in gq),
                           sum(1 for r in gq if r["outcome"] == "HUNG" and (r["n_rec"] or r["n_err0"] + r["n_err1"] or r["n_death"]))))
    P("  per exposed trial (rank: view times of the orphan blanks, s since trial start; anchor):")
    for r in exposed:
        lk = leak[r["id"]]
        P("    %s %s:%s target=%s outcome=%s | r0 %s | r1 %s | anchor %.3f | judged %s/%s" % (
            r["id"], r["workload"], r["cls"], r["target"], r["outcome"], lk[0]["orphan_t"], lk[1]["orphan_t"],
            (r["t_anchor"] - r["t0"]) if r["t_anchor"] else float("nan"), r["j_class"], r["j_target"]))
    P("  over-strip: lines removed by HOOK that are not hook lines ('Overriding: out_dir = /tmp/blind_ddp_out', BLIND_ "
      "matched case-insensitively): %d lines in %d ddp trials (every ddp trial and reference, both ranks)" % (
          sum(leak[r["id"]][k]["stripped"] - leak[r["id"]][k]["stripped_hook"] for r in rows for k in (0, 1)),
          sum(1 for r in rows if any(leak[r["id"]][k]["stripped"] > leak[r["id"]][k]["stripped_hook"] for k in (0, 1)))))
    # gin kill timing
    gk = [r for r in rows if r["workload"] == "gin" and r["cls"] == "kill" and r["valid"]]
    P("  gin kill: killed rank's exit and survivor's first error after the anchor line (s):")
    for r in gk:
        d = os.path.join(R, "raw", r["id"])
        _, t_exit_k, _ = agent_info(read_log(os.path.join(d, "a%d.log" % r["killed_rank"])))
        terr = r["t_fault"] + r["dt_err"] if r["dt_err"] != "" else None
        P("    %s target=%s kill ack %+.3f, killed exit %+.3f, survivor first error %s, survivor end %s rc=%s -> %s; judged %s/%s %s" % (
            r["id"], r["target"], r["t_fault"] - r["t_anchor"], t_exit_k - r["t_anchor"],
            "%+.3f" % (terr - r["t_anchor"]) if terr else "-", r["end%d" % (1 - r["target"])] or "self",
            r["rc%d" % (1 - r["target"])], r["outcome"], r["j_class"], r["j_target"], r["j_outcome"]))
    ut = {tg: sorted(trials[r["id"]]["u_t"] for r in gk if r["target"] == tg) for tg in (0, 1)}
    k0, k1 = len(ut[0]), len(ut[1])
    P("  gin kill u_t by target (seal): rank 0 %s, rank 1 %s; the generator draws target and u_t independently, so the "
      "chance that the %d rank-0 kills are the %d earliest of %d is 1/%d" % (ut[0], ut[1], k0, k0, k0 + k1,
                                                                          math.factorial(k0 + k1) // (math.factorial(k0) * math.factorial(k1))))
    for cls in ("stop", "mute"):
        ss = [r for r in rows if r["workload"] == "gin" and r["cls"] == cls and r["valid"]]
        P("  gin %s: fault after anchor (s) %s; judged class %s; target right %d/%d" % (
            cls, sorted(round(r["t_fault"] - r["t_anchor"], 3) for r in ss), dict(Counter(r["j_class"] for r in ss)),
            sum(1 for r in ss if r["target"] != "" and r["j_target"] == str(r["target"])), sum(1 for r in ss if r["target"] != "")))

    if a.trials:
        P("\n" + "=" * 100)
        P("TRIALS")
        for r in rows:
            P("  %s %-3s %s:%-6s t=%-2s app=%d valid=%d rc=%s/%s end=%s/%s err=%d/%d to=%d rec=%d death=%d mgmt=%d res=%-7s %-12s "
              "dt_err=%s dt_end=%s | J %s/%s/%s | first err: %s" % (
                  r["id"], r["hold"], r["workload"], r["cls"], r["target"], r["applied"], r["valid"], r["rc0"], r["rc1"],
                  r["end0"] or "-", r["end1"] or "-", r["n_err0"], r["n_err1"], r["timeout_first"], r["n_rec"], r["n_death"],
                  r["n_mgmt"], r["result"], r["outcome"], r["dt_err"], r["dt_end"], r["j_class"], r["j_target"], r["j_outcome"],
                  r["err_first"][:110]))


if __name__ == "__main__":
    main()
