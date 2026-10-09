#!/usr/bin/env python3
"""apprun.py - gpu-detect's runner for the two unmodified examples (a copy of ../blind/blindrun.py, adapted; that file is
not changed). One trial = one example run on rain (rank 0) and sunny (rank 1) with one fault (or none) of a cell of
cells.json, on one build. Run only inside hold.sh, itself inside ../gpu-initiated/common/cluster_run.sh (chain.sh).

    apprun.py plan    --seed HEX [--cells cells.json] [--out schedule.json]   (writes the trial list; no cluster action)
    apprun.py hold    --results R --hold H [--schedule schedule.json] [--budget-s 800]
    apprun.py pending --results R --hold H [--schedule schedule.json]         (prints how many trials of H have no result)

Differences from blindrun.py (EXPERIMENT.md 9):
  - not blind: the trial list (schedule.json) is generated from cells.json with a recorded seed and committed before the
    main run (it is pre-registered with its sha256); trial ids name the cell, the build and the number;
  - builds: gin hq (the blind study's binary and gin-peer's libnccl), hr (gin-remaining's libnccl) and hw (this study's
    libnccl), the last two with gd_gin_ring (built against the hw headers, which equal hr's); nvs t1_380 (the blind
    study's binary, plugin and libraries) and t1w (this study's libraries, gd_nvs_rr, gd_nvs_boot.so). Paths: BUILDS;
  - a cell may add environment variables to both ranks (env in cells.json): the watch period, the fail-stop policy;
  - faults: none, qperr (gin, nvs), remacc (nvs), kill, stop. No management cut: this study adds no iptables rule;
  - ports 29000-30999 (rendezvous, and gin's 16-port helper block), checked unused on both nodes;
  - wall and grace times per workload from cells.json (a cell may set its own wall_s).
Safety (EXPERIMENT.md 8), as blindrun.py: processes are only signalled through the agents (by the PID they started; the
agent kills its own process group when its stdin closes); nothing changes a link, an address, a driver or a firewall.
Outputs per trial: <R>/raw/<id>/{r0.log,r1.log,a0.log,a1.log,trial.meta}. Log lines are "<rain CLOCK_MONOTONIC at
receipt> <line>"; trial.meta (JSON) holds the cell, build, fault parameters, exits and agent acknowledgements.
"""
import argparse, base64, hashlib, json, os, random, re, secrets, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
CUDA_LIB = "/usr/local/cuda-12.8/lib64"
HCA = {0: "mlx5_1", 1: "mlx5_0"}
PORT_LO, PORT_HI = 29000, 30999
AGENT = "~/gd-bundle/agent/node_agent.py"  # a byte copy of ../blind/node_agent.py (deploy_gd.sh)
DEFAULT_SCHEDULE = os.path.join(HERE, "schedule.json")
DEFAULT_CELLS = os.path.join(HERE, "cells.json")
# per build: library directory, executable, working directory (and the bootstrap plugin for nvs); "~" is expanded by the
# agent on its node. hq and t1_380 are the blind study's deployed files (read only); hr is gin-remaining's library.
BUILDS = {
    ("gin", "hq"): {"lib": "~/gi-bundle/gin_ts2/hq", "bin": "~/blind-bundle/hq/blind_gin_ring", "cwd": "~/blind-bundle/hq"},
    ("gin", "hr"): {"lib": "~/gi-bundle/gin_ts2/hr", "bin": "~/gd-bundle/gin/gd_gin_ring", "cwd": "~/gd-bundle/gin"},
    ("gin", "hw"): {"lib": "~/gi-bundle/gin_ts2/hw", "bin": "~/gd-bundle/gin/gd_gin_ring", "cwd": "~/gd-bundle/gin"},
    ("nvs", "t1_380"): {"lib": "~/blind-bundle/nvs/lib", "bin": "~/blind-bundle/nvs/blind_nvs_rr",
                        "plugin": "~/blind-bundle/nvs/blind_nvs_boot.so", "cwd": "~/blind-bundle/nvs"},
    ("nvs", "t1w"): {"lib": "~/gd-bundle/nvs/lib", "bin": "~/gd-bundle/nvs/gd_nvs_rr",
                     "plugin": "~/gd-bundle/nvs/gd_nvs_boot.so", "cwd": "~/gd-bundle/nvs"},
}
# every file a trial may use, md5-compared between the nodes once per hold (a mismatch writes STOP_md5)
MD5_FILES = ["gi-bundle/gin_ts2/hq/libnccl.so.2.32.3", "gi-bundle/gin_ts2/hr/libnccl.so.2.32.3",
             "gi-bundle/gin_ts2/hw/libnccl.so.2.32.3", "blind-bundle/hq/blind_gin_ring", "gd-bundle/gin/gd_gin_ring",
             "blind-bundle/nvs/blind_nvs_rr", "blind-bundle/nvs/blind_nvs_boot.so",
             "blind-bundle/nvs/lib/nvshmem_transport_ibgda.so.7.0.0", "blind-bundle/nvs/lib/libnvshmem_host.so.3.8.0",
             "gd-bundle/nvs/gd_nvs_rr", "gd-bundle/nvs/gd_nvs_boot.so", "gd-bundle/nvs/lib/nvshmem_transport_ibgda.so.7.0.0",
             "gd-bundle/nvs/lib/libnvshmem_host.so.3.8.0", "gd-bundle/agent/node_agent.py"]

GID_PROBE = r'''d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done
exit 1'''


def mono():
    return time.clock_gettime(time.CLOCK_MONOTONIC)


def sunny_ssh():
    s = os.environ.get("SUNNY_SSH", "")
    if "@" not in s:
        sys.exit("SUNNY_SSH is not set (hold.sh sets it)")
    return s


def ssh(cmd, timeout=30):
    return subprocess.run(["ssh", "-n", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", sunny_ssh(), cmd],
                          capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------- per-hold facts
class Site:
    """Read once per hold: rain's management address (from the route to sunny), GID indices, bundle md5s."""

    def __init__(self):
        host = sunny_ssh().split("@", 1)[1]
        r = subprocess.run(["ip", "-4", "route", "get", host], capture_output=True, text=True).stdout
        m = re.search(r" src ([0-9.]+)", r)
        if not m:
            sys.exit("cannot find rain's management address")
        self.rain_mgmt = m.group(1)
        g0 = subprocess.run(["bash", "-s", "--", HCA[0]], input=GID_PROBE, capture_output=True, text=True).stdout.strip()
        g1 = subprocess.run(["ssh", "-o", "BatchMode=yes", sunny_ssh(), "bash", "-s", "--", HCA[1]], input=GID_PROBE,
                            capture_output=True, text=True, timeout=30).stdout.strip()
        if not g0 or not g1:
            sys.exit("GID detection failed: rain=%r sunny=%r" % (g0, g1))
        self.gid = {0: g0, 1: g1}
        cmd = "cd ~ && md5sum %s" % " ".join(MD5_FILES)
        self.md5 = {"rain": subprocess.run(["bash", "-c", cmd], capture_output=True, text=True).stdout.strip(),
                    "sunny": ssh(cmd).stdout.strip()}
        self.md5_match = int(self.md5["rain"] == self.md5["sunny"] and self.md5["rain"].count("\n") == len(MD5_FILES) - 1)


# ---------------------------------------------------------------- ports below 32768, unused on both nodes
def _ss_filter(lo, hi):
    return "( sport >= :%d and sport <= :%d ) or ( dport >= :%d and dport <= :%d )" % (lo, hi, lo, hi)


def range_busy(lo, hi):
    """True if a TCP socket in any state uses a port in lo..hi on rain or on sunny (or sunny cannot be asked)."""
    f = _ss_filter(lo, hi)
    if subprocess.run(["ss", "-Htan", f], capture_output=True, text=True).stdout.strip():
        return True
    try:
        r = ssh("ss -Htan '%s'; echo SS_DONE" % f, timeout=15).stdout
    except subprocess.TimeoutExpired:
        return True
    return r.strip() != "SS_DONE"


def pick_ports(width, avoid=()):
    """A block of `width` consecutive ports in PORT_LO..PORT_HI unused on both nodes; at most 32 candidates."""
    span = PORT_HI - PORT_LO + 1 - width
    c = PORT_LO + random.randrange(span)
    tried = []
    for _ in range(32):
        if not any(c <= a <= c + width - 1 for a in avoid) and not range_busy(c, c + width - 1):
            return c, tried
        tried.append(c)
        c = PORT_LO + (c - PORT_LO + width) % span
    raise RuntimeError("no free port block of %d in %d..%d" % (width, PORT_LO, PORT_HI))


# ---------------------------------------------------------------- workloads
NVS_ARGS = ["-b", "16M", "-e", "64M", "-n", "150", "-w", "2"]  # the blind study's arguments (its EXPERIMENT.md 6)
ANCHOR = {"gin": (0, r"=== Comparing GIN ring-exchange implementations ==="),
          "nvs": (0, r"^\[nvshmem-t1\] PE0 [0-9.]+ enabled:")}
SUPPRESS = {"gin": [["mismatch", r"mismatch at CTA"]], "nvs": [["validation", r"error, data\["]]}
HOOKS = {("gin", "qperr"), ("nvs", "qperr"), ("nvs", "remacc")}


def rank_spec(wl, build, rank, site, ports, nonce, hook_env, cell_env, tag):
    """argv, env and cwd of one rank (paths with ~ are expanded by the agent on its node)."""
    b = BUILDS[(wl, build)]
    env = {"BLIND_TAG": tag, "LD_LIBRARY_PATH": b["lib"] + ":" + CUDA_LIB, "BLIND_RANK": str(rank), "BLIND_NRANKS": "2",
           "BLIND_RDV_ADDR": site.rain_mgmt, "BLIND_RDV_PORT": str(ports["rdv"]), "BLIND_RDV_NONCE": nonce}
    if wl == "gin":  # the blind study's GIN environment (its blindrun.py rank_spec)
        env.update({"NCCL_DEBUG": "WARN", "NCCL_DEBUG_SUBSYS": "INIT,NET", "NCCL_SOCKET_IFNAME": "eno1",
                    "NCCL_GIN_TYPE": "3", "NCCL_GIN_ENABLE": "1", "NCCL_IB_TIMEOUT": "14",
                    "NCCL_GIN_FAULT_CLASSIFY": "1", "NCCL_GIN_FAULT_RECOVERY": "1", "NCCL_GIN_FAULT_TRANSPARENT": "1",
                    "NCCL_GIN_TS_PORT": str(ports["helper"]), "NCCL_IB_HCA": HCA[rank],
                    "NCCL_IB_GID_INDEX": site.gid[rank]})
        argv = [b["bin"]]
    else:  # nvs: the blind study's NVSHMEM environment (t1_380's env_t1.sh settings, the 160M heap)
        env.update({"NVSHMEM_BOOTSTRAP": "plugin", "NVSHMEM_BOOTSTRAP_PLUGIN": b["plugin"],
                    "NVSHMEM_IB_ENABLE_IBGDA": "1", "NVSHMEM_IBGDA_NIC_HANDLER": "auto",
                    "NVSHMEM_REMOTE_TRANSPORT": "none", "NVSHMEM_DISABLE_CUDA_VMM": "1",
                    "NVSHMEM_CUMEM_GRANULARITY": "2097152", "NVSHMEM_MAX_TEAMS": "4", "NVSHMEM_G_BUF_SIZE": "262144",
                    "NVSHMEM_G_COALESCING_BUF_SIZE": "4194304", "NVSHMEM_IBGDA_NUM_RC_PER_PE": "1",
                    "NVSHMEM_IBGDA_RC_MAP_BY": "none", "NVSHMEM_IBGDA_NUM_DCI": "1", "NVSHMEM_SYMMETRIC_SIZE": "160M",
                    "NVSHMEM_BOOTSTRAP_UID_SOCK_IFNAME": "eno1", "NVSHMEM_IB_ADDR_FAMILY": "AF_INET",
                    "NVSHMEM_DEBUG": "WARN", "NVSHMEM_IB_TIMEOUT": "14", "NVSHMEM_IB_RETRY_CNT": "7",
                    "NVSHMEM_IBGDA_FT_POLL_US": "50", "NVSHMEM_IBGDA_FT": "1", "NVSHMEM_IBGDA_FT_RING_CQ": "1",
                    "NVSHMEM_IBGDA_FT_TRANSPARENT": "1", "NVSHMEM_HCA_LIST": HCA[rank] + ":1",
                    "NVSHMEM_ENABLE_NIC_PE_MAPPING": "1", "NVSHMEM_IB_GID_INDEX": site.gid[rank]})
        argv = [b["bin"]] + NVS_ARGS
    env.update(cell_env)
    env.update(hook_env)
    return {"tag": tag, "argv": argv, "env": env, "cwd": b["cwd"], "suppress": SUPPRESS[wl], "cap": 200}


def hook_env(wl, cls, t_ms):
    if wl == "gin" and cls == "qperr":
        return {"NCCL_GIN_FAULT_INJECT": "local_err:%d" % t_ms}
    if wl == "nvs" and cls == "qperr":
        return {"NVSHMEM_IBGDA_FAULT_INJECT": "local_err:%d" % t_ms}
    if wl == "nvs" and cls == "remacc":
        return {"NVSHMEM_IBGDA_FAULT_INJECT": "rem_access:%d" % t_ms}
    return {}


def lerp(rng, u):
    return rng[0] + u * (rng[1] - rng[0])


def derive(entry, cells):
    """The fault's parameters from the drawn fractions of a trial (cells.json timing and durations)."""
    wl, cls, out = entry["workload"], entry["cls"], {}
    c = cells["timing"][wl]
    if (wl, cls) in HOOKS:
        out["t_ms"] = int(round(lerp(c["hook_ms"], entry["u_t"])))
    if cls in ("kill", "stop"):
        out["t_after_anchor_s"] = round(lerp(c["anchor_window_s"], entry["u_t"]), 3)
    if cls == "stop":
        out["d_s"] = round(lerp(cells["durations_s"]["stop"][wl], entry["u_d"]), 3)
    return out


# ---------------------------------------------------------------- one rank's agent (as blindrun.py)
class Agent:
    def __init__(self, rank, spec, rawdir, watch=()):
        self.rank = rank
        b64 = base64.b64encode(json.dumps(spec).encode()).decode()
        if rank == 0:
            argv = ["python3", os.path.expanduser(AGENT), "--spec", b64]
        else:
            argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", sunny_ssh(),
                    "python3 %s --spec %s" % (AGENT, b64)]
        self.log = open(os.path.join(rawdir, "r%d.log" % rank), "w")
        self.alog = open(os.path.join(rawdir, "a%d.log" % rank), "w")
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, errors="replace", bufsize=1)
        self.app_pid = None
        self.app_rc = None
        self.t_exit = None
        self.acks = []
        self.watch = list(watch)
        self.lock = threading.Lock()
        self.t1 = threading.Thread(target=self._out, daemon=True)
        self.t2 = threading.Thread(target=self._err, daemon=True)
        self.t1.start()
        self.t2.start()

    def _out(self):
        for line in self.p.stdout:
            now = mono()
            line = line.rstrip("\n")
            self.log.write("%.6f %s\n" % (now, line))
            for rx, ev, hold in self.watch:
                if not ev.is_set() and rx.search(line):
                    hold.append(now)
                    ev.set()
        self.log.flush()

    def _err(self):
        for line in self.p.stderr:
            now = mono()
            line = line.rstrip("\n")
            self.alog.write("%.6f %s\n" % (now, line))
            self.alog.flush()
            m = re.match(r"AGENT start pid=(\d+)", line)
            if m:
                self.app_pid = int(m.group(1))
            m = re.match(r"AGENT exit pid=\d+ rc=(-?\d+)", line)
            if m:
                self.app_rc = int(m.group(1))
                self.t_exit = now
            if line.startswith("AGENT sig="):
                with self.lock:
                    self.acks.append((now, line))

    def send(self, cmd):
        try:
            self.p.stdin.write(cmd + "\n")
            self.p.stdin.flush()
            return True
        except (BrokenPipeError, ValueError, OSError):
            return False

    def wait_ack(self, cmd, after, timeout=5.0):
        end = mono() + timeout
        while mono() < end:
            with self.lock:
                for t, l in self.acks:
                    if t >= after and l.startswith("AGENT sig=%s " % cmd):
                        return t, l
            time.sleep(0.002)
        return None, None

    def exited(self):
        return self.app_rc is not None or self.p.poll() is not None

    def close(self, timeout=15):
        self.send("EXIT")
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.p.kill()  # our own local agent or ssh client process
            self.p.wait()
        self.t1.join(5)
        self.t2.join(5)
        self.log.close()
        self.alog.close()


# ---------------------------------------------------------------- one trial
LEFT_PAT = "[b]lind_gin_ring|[g]d_gin_ring|[b]lind_nvs_rr|[g]d_nvs_rr"


def leftovers():
    a = subprocess.run(["pgrep", "-f", LEFT_PAT], capture_output=True, text=True).stdout.split()
    try:
        b = ssh("pgrep -f '%s'" % LEFT_PAT, timeout=15).stdout.split()
    except subprocess.TimeoutExpired:
        b = ["?"]
    return len(a), len(b)


def run_trial(results, entry, params, site, cells):
    raw = os.path.join(results, "raw", entry["id"])
    if os.path.exists(os.path.join(raw, "trial.meta")):
        return None
    if os.path.isdir(raw):  # an interrupted earlier attempt: keep it aside, run the trial again
        k = 1
        while os.path.exists("%s.partial%d" % (raw, k)):
            k += 1
        os.rename(raw, "%s.partial%d" % (raw, k))
    os.makedirs(raw)
    wl, cls, target, build = entry["workload"], entry["cls"], entry.get("target"), entry["build"]
    lim = dict(cells["limits"][wl])
    if entry.get("wall_s"):  # a cell's own time cap (the release cells print every wrong element)
        lim["wall_s"] = float(entry["wall_s"])
    rdv, rdv_tried = pick_ports(1)
    ports = {"rdv": rdv}
    if wl == "gin":
        ports["helper"], _ = pick_ports(16, avoid=(rdv,))
    nonce = secrets.token_hex(8)
    tag = "gd-%d-%s" % (os.getpid(), entry["id"])
    henv = hook_env(wl, cls, params.get("t_ms")) if (wl, cls) in HOOKS else {}
    cenv = {k: str(v) for k, v in entry.get("env", {}).items()}
    specs = {r: rank_spec(wl, build, r, site, ports, nonce, henv if target == r else {}, cenv, tag) for r in (0, 1)}
    meta = {"id": entry["id"], "entry": entry, "params": params, "ports": ports, "port_tried": rdv_tried,
            "gid": site.gid, "md5_match": site.md5_match, "date": time.strftime("%F %T"), "runner_pid": os.getpid(),
            "hook_env": henv, "hook_rank": target if henv else None, "cell_env": cenv,
            "bin": BUILDS[(wl, build)]["bin"], "lib": BUILDS[(wl, build)]["lib"]}
    anchor_rank, anchor_rx = ANCHOR[wl]
    anchor_ev, anchor_hold = threading.Event(), []
    done_ev = threading.Event()
    t0 = mono()
    meta["t0"] = t0
    w = [(re.compile(anchor_rx), anchor_ev, anchor_hold)]
    agents = {0: Agent(0, specs[0], raw, w if anchor_rank == 0 else ())}
    time.sleep(0.3)
    agents[1] = Agent(1, specs[1], raw, w if anchor_rank == 1 else ())
    fault = {"applied": 0}
    meta["fault"] = fault

    def controller():
        if cls not in ("kill", "stop"):
            return
        while not anchor_ev.wait(0.02):
            if done_ev.is_set():
                fault["skipped"] = "no_anchor"
                return
        t_fire = anchor_hold[0] + params["t_after_anchor_s"]
        while mono() < t_fire and not done_ev.is_set():
            time.sleep(0.0005)
        if done_ev.is_set():
            fault["skipped"] = "ended_before_fault"
            return
        ag = agents[target]
        if ag.exited():
            fault["skipped"] = "target_gone"
            return
        fault["t_cmd"] = mono()
        ag.send("KILL" if cls == "kill" else "STOP")
        fault["t_ack"], fault["ack"] = ag.wait_ack("KILL" if cls == "kill" else "STOP", fault["t_cmd"])
        fault["applied"] = int(bool(fault["ack"]) and " rc=0 " in fault["ack"])
        if cls == "stop":
            end = fault["t_cmd"] + params["d_s"]
            while mono() < end and not ag.exited():
                time.sleep(0.002)
            fault["t_cont_cmd"] = mono()
            ag.send("CONT")
            fault["t_cont_ack"], fault["cont_ack"] = ag.wait_ack("CONT", fault["t_cont_cmd"])

    ctl = threading.Thread(target=controller, daemon=True)
    ctl.start()
    harness_end = {0: "", 1: ""}
    first_exit = None
    while True:
        now = mono()
        ex = {r: agents[r].exited() for r in (0, 1)}
        if ex[0] and ex[1]:
            break
        if first_exit is None and (ex[0] or ex[1]):
            first_exit = now
        if first_exit is not None and now - first_exit > lim["grace_s"]:
            for r in (0, 1):
                if not ex[r] and not harness_end[r]:
                    harness_end[r] = "grace"
                    agents[r].send("KILL")
        if now - t0 > lim["wall_s"]:
            for r in (0, 1):
                if not ex[r] and not harness_end[r]:
                    harness_end[r] = "wall"
                    agents[r].send("KILL")
            if now - t0 > lim["wall_s"] + 15:
                break
        time.sleep(0.01)
    done_ev.set()
    ctl.join(30)
    t_end = mono()
    for r in (0, 1):
        agents[r].close()
    meta.update({"t_end": t_end, "wall_s": round(t_end - t0, 3), "anchor_t": anchor_hold[0] if anchor_hold else None,
                 "killed_rank": target if (cls == "kill" and fault.get("applied")) else None,
                 "exit": {r: {"rc": agents[r].app_rc, "t_exit": agents[r].t_exit, "harness_end": harness_end[r],
                              "app_pid": agents[r].app_pid, "agent_rc": agents[r].p.returncode} for r in (0, 1)}})
    if (wl, cls) in HOOKS:
        fault["applied"] = -1  # decided by rows_gd.py from the hook's fire line in the target rank's log
    time.sleep(0.3)
    meta["left"] = leftovers()
    with open(os.path.join(raw, "trial.meta"), "w") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
    return meta


# ---------------------------------------------------------------- stop files and the hold loop (as blindrun.py)
def stop_present(results):
    return [f for f in os.listdir(results) if f.startswith("STOP_")] if os.path.isdir(results) else []


def after_trial_checks(results, meta, state):
    raw = os.path.join(results, "raw", meta["id"])
    bad = []
    for r in (0, 1):
        rc = meta["exit"][r]["rc"]
        if rc in (139, -11):
            bad.append("rank %d rc=%s" % (r, rc))
        try:
            txt = open(os.path.join(raw, "r%d.log" % r), errors="replace").read()
        except OSError:
            txt = ""
        if re.search(r"illegal address|illegal memory access|unspecified launch failure", txt, re.I):
            bad.append("rank %d log: CUDA memory fault" % r)
    if bad:
        with open(os.path.join(results, "STOP_cuda"), "a") as f:
            f.write("%s trial %s: %s\n" % (time.strftime("%F %T"), meta["id"], "; ".join(bad)))
    left = sum(x for x in meta["left"] if isinstance(x, int)) + (1 if "?" in map(str, meta["left"]) else 0)
    state["left_streak"] = state.get("left_streak", 0) + 1 if left else 0
    if state["left_streak"] >= 2:
        with open(os.path.join(results, "STOP_left"), "a") as f:
            f.write("%s trial %s: processes left in two trials in a row (%s)\n" % (time.strftime("%F %T"), meta["id"],
                                                                                  meta["left"]))


def load(path):
    path = os.path.expanduser(path)
    return json.load(open(path)), hashlib.sha256(open(path, "rb").read()).hexdigest()


def run_list(results, items, cells, budget_s):
    os.makedirs(results, exist_ok=True)
    site = Site()
    t_start = mono()
    state = {}
    log = open(os.path.join(results, "runner.log"), "a")
    log.write("%s start trials=%d md5_match=%d\n" % (time.strftime("%F %T"), len(items), site.md5_match))
    log.flush()
    if not site.md5_match:
        log.write("bundle md5 differs between the nodes: no trial runs\n%s\n" % json.dumps(site.md5))
        with open(os.path.join(results, "STOP_md5"), "a") as f:
            f.write("%s bundle md5 differs between rain and sunny\n" % time.strftime("%F %T"))
        return
    for i, (entry, params) in enumerate(items):
        if stop_present(results):
            log.write("%s STOP file present: %s; stopping\n" % (time.strftime("%F %T"), stop_present(results)))
            break
        if os.path.exists(os.path.join(results, "raw", entry["id"], "trial.meta")):
            continue
        if mono() - t_start + float(entry.get("wall_s") or cells["limits"][entry["workload"]]["wall_s"]) + 15 > budget_s:
            log.write("%s hold budget reached; %d trial(s) left for a later pass\n" % (time.strftime("%F %T"),
                                                                                       len(items) - i))
            break
        meta = run_trial(results, entry, params, site, cells)
        if meta is None:
            continue
        after_trial_checks(results, meta, state)
        log.write("%s trial %s (%d/%d) wall=%.1fs left=%s\n" % (time.strftime("%F %T"), entry["id"], i + 1, len(items),
                                                                meta["wall_s"], meta["left"]))
        log.flush()


# ---------------------------------------------------------------- the trial list
def plan(cells, cells_sha, seed_hex):
    """Expand cells.json into trials: per hold, every cell's n trials (id <cell>.<build>.n<k>), the target (0 or 1 drawn,
    or the cell's fixed one), u_t and u_d drawn uniformly; the hold's trials in a random order. The seed is recorded."""
    rng = random.Random(int(seed_hex, 16))
    holds = {}
    for h, cl in cells["holds"].items():
        trials = []
        for c in cl:
            for k in range(1, c["n"] + 1):
                tgt = c.get("target", "random")
                e = {"id": "%s.%s.n%d" % (c["cell"], c["build"], k), "hold": h, "cell": c["cell"],
                     "workload": c["workload"], "cls": c["cls"], "build": c["build"], "env": c.get("env", {}),
                     "target": (rng.randrange(2) if tgt == "random" else tgt) if c["cls"] != "none" else None,
                     "u_t": round(rng.random(), 6), "u_d": round(rng.random(), 6)}
                if c.get("wall_s"):
                    e["wall_s"] = c["wall_s"]
                trials.append(e)
        rng.shuffle(trials)
        holds[h] = trials
    return {"header": {"study": "gpu-detect", "seed": seed_hex, "cells_sha256": cells_sha,
                       "generated": time.strftime("%F %T")}, "holds": holds}


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("plan")
    p.add_argument("--seed", required=True)
    p.add_argument("--cells", default=DEFAULT_CELLS)
    p.add_argument("--out", default=DEFAULT_SCHEDULE)
    for n in ("hold", "pending"):
        p = sp.add_parser(n)
        p.add_argument("--results", required=True)
        p.add_argument("--hold", required=True)
        p.add_argument("--schedule", default=DEFAULT_SCHEDULE)
        p.add_argument("--cells", default=DEFAULT_CELLS)
        p.add_argument("--budget-s", type=float, default=800.0)
    a = ap.parse_args()
    cells, cells_sha = load(a.cells)
    if a.cmd == "plan":
        s = plan(cells, cells_sha, a.seed)
        with open(a.out, "w") as f:
            json.dump(s, f, indent=1, sort_keys=True)
        print("%s: %s" % (a.out, ", ".join("%s %d" % (h, len(t)) for h, t in sorted(s["holds"].items()))))
        return
    s, digest = load(a.schedule)
    if s["header"]["cells_sha256"] != cells_sha:
        sys.exit("schedule.json was made from another cells.json (%s, now %s)" % (s["header"]["cells_sha256"][:12],
                                                                                  cells_sha[:12]))
    items = [(e, derive(e, cells)) for e in s["holds"].get(a.hold, [])]
    if not items:
        sys.exit("hold %s has no app trials in %s" % (a.hold, a.schedule))
    results = os.path.abspath(a.results)
    if a.cmd == "pending":
        print(sum(1 for e, _ in items if not os.path.exists(os.path.join(results, "raw", e["id"], "trial.meta"))))
        return
    os.makedirs(results, exist_ok=True)
    with open(os.path.join(results, "schedule_sha256.txt"), "a") as f:
        f.write("%s hold %s schedule sha256 %s\n" % (time.strftime("%F %T"), a.hold, digest))
    run_list(results, items, cells, a.budget_s)


if __name__ == "__main__":
    main()
