#!/usr/bin/env python3
"""blindrun.py - blind-apps runner: one trial = one unmodified application on rain (rank 0) and sunny (rank 1), one
scheduled fault (or none). Run only inside hold.sh, itself inside ../gpu-initiated/common/cluster_run.sh (chain.sh).

    blindrun.py hold     --results R --hold H [--schedule S] [--calib C] [--budget-s 840]
    blindrun.py pending  --results R --hold H [--schedule S]               (prints how many trials of H have no result)
    blindrun.py baseline --results R --workload W --n N [--first K] [--calib C] [--budget-s 840]
    blindrun.py demo     --results R --workload W --cls C [--target r] [--u-t U] [--u-d U] [--dir both|oneway]
                         [--k K] [--t-ms T] [--d-s D] --name NAME [--calib C]           (pilot only, never scored)

Workloads (EXPERIMENT.md 7; bundle ~/blind-bundle and ~/blind-venv on both nodes, deploy_blind.sh):
  ddp  PyTorch 2.4.1 DDP running nanoGPT's train.py unchanged (ddp/ddp_entry.py), NCCL = the Stage 2 libnccl 2.23.4
       (9ed03e1d) by LD_PRELOAD, env:// rendezvous (MASTER_PORT from the port picker), NCCL sockets on eno1
  gin  NCCL 2.32.3 example 09_gin_optimizations/01_ring_exchange (blind_gin_ring) on the gin-peer build hq (c1311625)
  nvs  NVSHMEM 3.8.0 example ring-reduce (blind_nvs_rr) on the t1_380 build, bootstrap plugin blind_nvs_boot.so
Fault classes: none; library hooks (ddp: sqp, rqp, srq; gin: qperr; nvs: qperr, remacc), set in the target rank's
environment only; kill (SIGKILL), stop (SIGSTOP for d s, then SIGCONT) of the target rank's application process, sent
through that rank's node_agent.py; mute (iptables DROP on rain for d s, both ways or sunny->rain only) of this trial's
own management connections. kill/stop/mute start t after the workload's anchor line.

Safety (EXPERIMENT.md 8): processes are only signalled through the agents (by the PID they started); iptables rules
carry the comment blind-<runner pid>-<trial>, are removed at the end of the window, at the end of the trial and at
exit, and are skipped if any socket in the target ports belongs to another process; ports are below 32768 and checked
unused on both nodes; nothing changes a link, an address or a driver.
Outputs per trial: <R>/raw/<id>/{r0.log,r1.log,a0.log,a1.log,trial.meta}. Log lines are "<rain CLOCK_MONOTONIC at
receipt> <line>". trial.meta (JSON) holds the fault truth and must never reach the evaluator (handoff.py reads only
the logs and the exit records).
"""
import argparse, atexit, base64, hashlib, json, os, random, re, secrets, shlex, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE = "~/blind-bundle"
VENV = "~/blind-venv"
CUDA_LIB = "/usr/local/cuda-12.8/lib64"
HCA = {0: "mlx5_1", 1: "mlx5_0"}
PORT_LO, PORT_HI = 30000, 31999
AGENT = BUNDLE + "/agent/node_agent.py"
DEFAULT_SCHEDULE = "~/blind-seal/schedule.json"
DEFAULT_CALIB = os.path.join(HERE, "calib.json")
CONFIG = os.path.join(HERE, "schedule_config.json")

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
    """Facts read once per hold: rain's management address (from the route to sunny), GID indices, bundle md5s."""

    def __init__(self):
        host = sunny_ssh().split("@", 1)[1]
        r = subprocess.run(["ip", "-4", "route", "get", host], capture_output=True, text=True).stdout
        m = re.search(r" src ([0-9.]+)", r)
        if not m:
            sys.exit("cannot find rain's management address")
        self.rain_mgmt = m.group(1)
        self.sunny_host = host
        g0 = subprocess.run(["bash", "-s", "--", HCA[0]], input=GID_PROBE, capture_output=True, text=True).stdout.strip()
        g1 = subprocess.run(["ssh", "-o", "BatchMode=yes", sunny_ssh(), "bash", "-s", "--", HCA[1]], input=GID_PROBE,
                            capture_output=True, text=True, timeout=30).stdout.strip()
        if not g0 or not g1:
            sys.exit("GID detection failed: rain=%r sunny=%r" % (g0, g1))
        self.gid = {0: g0, 1: g1}
        files = ["s2/libnccl.so.2.23.4", "hq/libnccl.so.2.32.3", "hq/blind_gin_ring", "nvs/blind_nvs_rr",
                 "nvs/blind_nvs_boot.so", "nvs/lib/nvshmem_transport_ibgda.so.7.0.0", "nvs/lib/libnvshmem_host.so.3.8.0",
                 "ddp/ddp_entry.py", "agent/node_agent.py"]
        cmd = "cd ~/blind-bundle && md5sum %s; md5sum < ~/blind-venv/MANIFEST.md5" % " ".join(files)
        self.md5 = {"rain": subprocess.run(["bash", "-c", cmd], capture_output=True, text=True).stdout.strip(),
                    "sunny": ssh(cmd).stdout.strip()}
        self.md5_match = int(self.md5["rain"] == self.md5["sunny"] and self.md5["rain"].count("\n") == len(files))


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
NANOGPT_ARGS = ["config/train_shakespeare_char.py", "--compile=False", "--dtype=float32", "--max_iters=300",
                "--lr_decay_iters=300", "--warmup_iters=30", "--eval_interval=1000", "--eval_iters=10",
                "--log_interval=1", "--batch_size=16", "--block_size=128", "--n_layer=4", "--n_head=4",
                "--n_embd=256", "--dropout=0.1", "--gradient_accumulation_steps=2",
                "--always_save_checkpoint=False"]
NVS_ARGS = ["-b", "16M", "-e", "64M", "-n", "150", "-w", "2"]  # pilot: -n 30 gave too short a run (EXPERIMENT.md 12)

WL = {
    "ddp": {"anchor": (0, r"^iter 0: loss"), "wall_s": 150.0, "grace_s": 45.0, "rdv": "MASTER_PORT",
            # NCCL 2.23.4 at INFO prints one "<file>:<line> -> <code>" trace line per failing proxy call after an
            # error (88 247 lines in 0.4 s in the pilot's kill demo); the agent keeps 200 and counts the rest
            "suppress": [["nccl-trace", r"NCCL INFO \S+:\d+ -> \d+\s*$"]]},
    "gin": {"anchor": (0, r"=== Comparing GIN ring-exchange implementations ==="), "wall_s": 60.0, "grace_s": 20.0,
            "suppress": [["mismatch", r"mismatch at CTA"]], "rdv": "BLIND_RDV_PORT"},
    "nvs": {"anchor": (0, r"^\[nvshmem-t1\] PE0 [0-9.]+ enabled:"), "wall_s": 60.0, "grace_s": 20.0,
            "suppress": [["validation", r"error, data\["]], "rdv": "BLIND_RDV_PORT"},
}
HOOKS = {("ddp", "sqp"), ("ddp", "rqp"), ("ddp", "srq"), ("gin", "qperr"), ("nvs", "qperr"), ("nvs", "remacc")}


def rank_spec(wl, rank, site, ports, nonce, hook_env, tag):
    """argv, env and cwd of one rank (paths with ~ are expanded by the agent on its node)."""
    env = {"BLIND_TAG": tag}
    if wl == "ddp":
        env.update({"RANK": str(rank), "LOCAL_RANK": "0", "WORLD_SIZE": "2", "MASTER_ADDR": site.rain_mgmt,
                    "MASTER_PORT": str(ports["rdv"]), "LD_PRELOAD": BUNDLE + "/s2/libnccl.so.2.23.4",
                    "NCCL_SOCKET_IFNAME": "eno1", "NCCL_IB_HCA": HCA[rank], "NCCL_IB_GID_INDEX": site.gid[rank],
                    "NCCL_IB_TIMEOUT": "14", "NCCL_RDMA_FAULT_RECOVERY": "1", "NCCL_DEBUG": "INFO",
                    "NCCL_DEBUG_SUBSYS": "INIT,NET", "TORCH_NCCL_ASYNC_ERROR_HANDLING": "3",
                    "TORCH_NCCL_DUMP_ON_TIMEOUT": "0", "CUBLAS_WORKSPACE_CONFIG": ":4096:8", "BLIND_PG_TIMEOUT_S": "30",
                    "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "4"})
        argv = [VENV + "/py310/bin/python3.10", BUNDLE + "/ddp/ddp_entry.py", VENV + "/nanoGPT/train.py"] + \
            NANOGPT_ARGS + ["--out_dir=/tmp/blind_ddp_out"]  # created (empty) by rank 0 only; no checkpoint is written
        cwd = BUNDLE + "/run"
    elif wl == "gin":
        env.update({"LD_LIBRARY_PATH": BUNDLE + "/hq:" + CUDA_LIB, "BLIND_RANK": str(rank), "BLIND_NRANKS": "2",
                    "BLIND_RDV_ADDR": site.rain_mgmt, "BLIND_RDV_PORT": str(ports["rdv"]), "BLIND_RDV_NONCE": nonce,
                    "NCCL_DEBUG": "WARN", "NCCL_DEBUG_SUBSYS": "INIT,NET", "NCCL_SOCKET_IFNAME": "eno1",
                    "NCCL_GIN_TYPE": "3", "NCCL_GIN_ENABLE": "1", "NCCL_IB_TIMEOUT": "14",
                    "NCCL_GIN_FAULT_CLASSIFY": "1", "NCCL_GIN_FAULT_RECOVERY": "1", "NCCL_GIN_FAULT_TRANSPARENT": "1",
                    "NCCL_GIN_TS_PORT": str(ports["helper"]), "NCCL_IB_HCA": HCA[rank],
                    "NCCL_IB_GID_INDEX": site.gid[rank]})
        argv = [BUNDLE + "/hq/blind_gin_ring"]
        cwd = BUNDLE + "/hq"
    else:  # nvs: ../gpu-initiated/nvshmem_ft/scripts/t1/env_t1.sh settings, the GID index found at run time
        env.update({"LD_LIBRARY_PATH": BUNDLE + "/nvs/lib:" + CUDA_LIB, "NVSHMEM_BOOTSTRAP": "plugin",
                    "NVSHMEM_BOOTSTRAP_PLUGIN": BUNDLE + "/nvs/blind_nvs_boot.so", "BLIND_RANK": str(rank),
                    "BLIND_NRANKS": "2", "BLIND_RDV_ADDR": site.rain_mgmt, "BLIND_RDV_PORT": str(ports["rdv"]),
                    "BLIND_RDV_NONCE": nonce, "NVSHMEM_IB_ENABLE_IBGDA": "1", "NVSHMEM_IBGDA_NIC_HANDLER": "auto",
                    "NVSHMEM_REMOTE_TRANSPORT": "none", "NVSHMEM_DISABLE_CUDA_VMM": "1",
                    "NVSHMEM_CUMEM_GRANULARITY": "2097152", "NVSHMEM_MAX_TEAMS": "4", "NVSHMEM_G_BUF_SIZE": "262144",
                    "NVSHMEM_G_COALESCING_BUF_SIZE": "4194304", "NVSHMEM_IBGDA_NUM_RC_PER_PE": "1",
                    "NVSHMEM_IBGDA_RC_MAP_BY": "none", "NVSHMEM_IBGDA_NUM_DCI": "1", "NVSHMEM_SYMMETRIC_SIZE": "160M",  # BAR1 is 256 MiB: 256M failed (12)
                    "NVSHMEM_BOOTSTRAP_UID_SOCK_IFNAME": "eno1", "NVSHMEM_IB_ADDR_FAMILY": "AF_INET",
                    "NVSHMEM_DEBUG": "WARN", "NVSHMEM_IB_TIMEOUT": "14", "NVSHMEM_IB_RETRY_CNT": "7",
                    "NVSHMEM_IBGDA_FT_POLL_US": "50", "NVSHMEM_IBGDA_FT": "1", "NVSHMEM_IBGDA_FT_RING_CQ": "1",
                    "NVSHMEM_IBGDA_FT_TRANSPARENT": "1", "NVSHMEM_HCA_LIST": HCA[rank] + ":1",
                    "NVSHMEM_ENABLE_NIC_PE_MAPPING": "1", "NVSHMEM_IB_GID_INDEX": site.gid[rank]})
        argv = [BUNDLE + "/nvs/blind_nvs_rr"] + NVS_ARGS
        cwd = BUNDLE + "/nvs"
    env.update(hook_env)
    return {"tag": tag, "argv": argv, "env": env, "cwd": cwd, "suppress": WL[wl]["suppress"], "cap": 200}


def hook_env(wl, cls, k=None, t_ms=None):
    if wl == "ddp":
        if cls == "sqp":
            return {"NCCL_RDMA_FAULT_INJECT": str(k)}
        if cls == "rqp":
            return {"NCCL_RDMA_FAULT_INJECT_RECV": str(k)}
        if cls == "srq":
            return {"NCCL_RDMA_FAULT_INJECT_RECV": str(k), "NCCL_RDMA_FAULT_INJECT_RECV_SILENT": "1"}
    if wl == "gin" and cls == "qperr":
        return {"NCCL_GIN_FAULT_INJECT": "local_err:%d" % t_ms}
    if wl == "nvs" and cls == "qperr":
        return {"NVSHMEM_IBGDA_FAULT_INJECT": "local_err:%d" % t_ms}
    if wl == "nvs" and cls == "remacc":
        return {"NVSHMEM_IBGDA_FAULT_INJECT": "rem_access:%d" % t_ms}
    return {}


def lerp(rng, u):
    return rng[0] + u * (rng[1] - rng[0])


def derive(entry, calib, cfg):
    """Turn the drawn fractions of a schedule entry into the fault's parameters (calib.json, schedule_config.json)."""
    wl, cls, out = entry["workload"], entry["cls"], {}
    c = calib[wl]
    if wl == "ddp" and cls in ("sqp", "rqp", "srq"):
        key = {"sqp": "k_send", "rqp": "k_recv", "srq": "k_silent"}[cls]
        out["k"] = int(round(lerp(c[key], entry["u_t"])))
    elif (wl, cls) in HOOKS:
        out["t_ms"] = int(round(lerp(c["hook_ms"], entry["u_t"])))
    if cls in ("kill", "stop", "mute"):
        if wl == "ddp" and "iter_window" in c:
            # DDP: the fault starts when rank 0 prints "iter <n>: loss" (training progress, not seconds: the pilot's
            # 300 iterations took 5.2-15.0 s)
            out["at_iter"] = int(round(lerp(c["iter_window"], entry["u_t"])))
            out["t_after_anchor_s"] = 0.0
        else:
            out["t_after_anchor_s"] = round(lerp(c["anchor_window_s"], entry["u_t"]), 3)
    if cls in ("stop", "mute"):
        out["d_s"] = round(lerp(cfg["durations_s"][cls][wl], entry["u_d"]), 3)
    return out


# ---------------------------------------------------------------- one rank's agent
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
        self.acks = []  # (rain mono, agent line)
        self.watch = list(watch)  # (regex, event, holder): set before the reader threads start
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


# ---------------------------------------------------------------- management mute (iptables on rain)
_LIVE_RULES = []  # [(chain, spec list)] currently installed by this process


def ipt(op, chain, spec):
    return subprocess.run(["sudo", "-n", "iptables", "-w", "5", op, chain] + spec, capture_output=True, text=True)


def ipt_remove_all():
    while _LIVE_RULES:
        chain, spec = _LIVE_RULES.pop()
        for _ in range(3):
            if ipt("-D", chain, spec).returncode != 0:
                break


atexit.register(ipt_remove_all)


def own_ports(app_pid, sunny_host):
    """Local ports of the established TCP connections between rank 0's application and sunny's management address."""
    out = subprocess.run(["ss", "-tnpH", "state", "established", "dst", sunny_host], capture_output=True,
                         text=True).stdout
    ports = set()
    for line in out.splitlines():
        if "pid=%d," % app_pid in line:
            local = line.split()[2]  # with a state filter the columns are Recv-Q Send-Q Local Peer Process
            ports.add(int(local.rsplit(":", 1)[1]))
    return sorted(ports)


def foreign_sockets(app_pid, lo, hi):
    """Live sockets on rain with a local or remote port in lo..hi that do not belong to app_pid."""
    out = subprocess.run(["ss", "-tanpH"], capture_output=True, text=True).stdout
    n = 0
    for line in out.splitlines():
        f = line.split()
        if len(f) < 5 or f[0] not in ("LISTEN", "ESTAB", "SYN-SENT", "SYN-RECV", "CLOSE-WAIT"):
            continue
        lp = int(f[3].rsplit(":", 1)[1])
        rp = f[4].rsplit(":", 1)[1]
        rp = int(rp) if rp.isdigit() else -1
        if (lo <= lp <= hi or lo <= rp <= hi) and "pid=%d," % app_pid not in line:
            n += 1
    return n


def mute(wl, site, ports, app_pid, direction, d_s, tag, done_ev, rec):
    """Drop sunny<->rain packets of this trial's own management connections for d_s seconds (or until the trial ends)."""
    if subprocess.run(["sudo", "-n", "iptables", "-w", "5", "-S", "INPUT"], capture_output=True).returncode != 0:
        rec["skipped"] = "no_iptables"
        return
    host = site.sunny_host
    specs = []
    if wl == "gin":  # the recovery helpers' sockets: NCCL_GIN_TS_PORT .. +15 (gin-harden rule shape)
        lo, hi = ports["helper"], ports["helper"] + 15
        nf = foreign_sockets(app_pid, lo, hi)
        if nf:
            rec["skipped"] = "foreign_socket:%d" % nf
            return
        rng = "%d:%d" % (lo, hi)
        specs += [("INPUT", ["-s", host, "-p", "tcp", "--sport", rng]), ("INPUT", ["-s", host, "-p", "tcp", "--dport", rng])]
        if direction == "both":
            specs += [("OUTPUT", ["-d", host, "-p", "tcp", "--sport", rng]),
                      ("OUTPUT", ["-d", host, "-p", "tcp", "--dport", rng])]
        rec["ports"] = rng
    else:  # ddp, nvs: every established connection of rank 0's process to sunny (stage 2 T12 rule shape)
        lps = own_ports(app_pid, host)
        if not lps:
            rec["skipped"] = "no_connection"
            return
        for lp in lps:
            nf = foreign_sockets(app_pid, lp, lp)
            if nf:
                rec["skipped"] = "foreign_socket:%d@%d" % (nf, lp)
                return
        for lp in lps:
            specs.append(("INPUT", ["-s", host, "-p", "tcp", "--dport", str(lp)]))
            if direction == "both":
                specs.append(("OUTPUT", ["-d", host, "-p", "tcp", "--sport", str(lp)]))
        rec["ports"] = ",".join(map(str, lps))
    tail = ["-m", "comment", "--comment", tag, "-j", "DROP"]
    try:
        rec["t_on"] = mono()
        for chain, s in specs:
            r = ipt("-I", chain, s + tail)
            if r.returncode == 0:
                _LIVE_RULES.append((chain, s + tail))
        rec["rules_on"] = len(_LIVE_RULES)
        done_ev.wait(d_s)
    finally:
        ipt_remove_all()
        rec["t_off"] = mono()
        rec["rules_left"] = subprocess.run(["bash", "-c", "sudo -n iptables -w 5 -S | grep -c -- '%s' || true" % tag],
                                           capture_output=True, text=True).stdout.strip()


# ---------------------------------------------------------------- one trial
LEFT_PAT = "[b]lind_gin_ring|[b]lind_nvs_rr|[d]dp_entry.py"


def leftovers():
    a = subprocess.run(["pgrep", "-f", LEFT_PAT], capture_output=True, text=True).stdout.split()
    try:
        b = ssh("pgrep -f '%s'" % LEFT_PAT, timeout=15).stdout.split()
    except subprocess.TimeoutExpired:
        b = ["?"]
    return len(a), len(b)


def run_trial(results, tid, entry, params, site, kind):
    """kind: blind (sealed schedule), baseline, demo. Returns the meta dict."""
    raw = os.path.join(results, "raw", tid)
    if os.path.exists(os.path.join(raw, "trial.meta")):
        return None
    if os.path.isdir(raw):  # an interrupted earlier attempt: keep it aside, run the trial again
        k = 1
        while os.path.exists("%s.partial%d" % (raw, k)):
            k += 1
        os.rename(raw, "%s.partial%d" % (raw, k))
    os.makedirs(raw)
    wl, cls, target = entry["workload"], entry["cls"], entry.get("target")
    W = WL[wl]
    rdv, rdv_tried = pick_ports(1)
    ports = {"rdv": rdv}
    if wl == "gin":
        ports["helper"], _ = pick_ports(16, avoid=(rdv,))
    nonce = secrets.token_hex(8)
    tag = "blind-%d-%s" % (os.getpid(), tid)
    henv = hook_env(wl, cls, params.get("k"), params.get("t_ms")) if (wl, cls) in HOOKS else {}
    specs = {r: rank_spec(wl, r, site, ports, nonce, henv if target == r else {}, tag) for r in (0, 1)}
    meta = {"id": tid, "kind": kind, "entry": entry, "params": params, "ports": ports, "port_tried": rdv_tried,
            "gid": site.gid, "md5_match": site.md5_match, "date": time.strftime("%F %T"), "runner_pid": os.getpid(),
            "hook_env": henv, "hook_rank": target if henv else None}
    anchor_rank, anchor_rx = W["anchor"]
    if "at_iter" in params:  # DDP kill, stop, mute: the iteration line is the anchor
        anchor_rx = r"^iter %d: loss" % params["at_iter"]
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
        if cls not in ("kill", "stop", "mute"):
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
        if cls == "mute":
            pid0 = agents[0].app_pid
            if pid0 is None or agents[0].exited():
                fault["skipped"] = "rank0_gone"
                return
            rec = {}
            fault["mute"] = rec
            mute(wl, site, ports, pid0, entry.get("dir") or "both", params["d_s"], tag, done_ev, rec)
            fault["applied"] = int("t_on" in rec and rec.get("rules_on", 0) > 0)
            return
        ag = agents[target]
        if ag.exited():
            fault["skipped"] = "target_gone"
            return
        if cls == "kill":
            fault["t_cmd"] = mono()
            ag.send("KILL")
            fault["t_ack"], fault["ack"] = ag.wait_ack("KILL", fault["t_cmd"])
            fault["applied"] = int(bool(fault["ack"]) and " rc=0 " in fault["ack"])
        else:  # stop
            fault["t_cmd"] = mono()
            ag.send("STOP")
            fault["t_ack"], fault["ack"] = ag.wait_ack("STOP", fault["t_cmd"])
            fault["applied"] = int(bool(fault["ack"]) and " rc=0 " in fault["ack"])
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
    killed_rank = target if cls == "kill" else None
    while True:
        now = mono()
        ex = {r: agents[r].exited() for r in (0, 1)}
        if ex[0] and ex[1]:
            break
        if first_exit is None and (ex[0] or ex[1]):
            first_exit = now
        if first_exit is not None and now - first_exit > W["grace_s"]:
            for r in (0, 1):
                if not ex[r] and not harness_end[r]:
                    harness_end[r] = "grace"
                    agents[r].send("KILL")
        if now - t0 > W["wall_s"]:
            for r in (0, 1):
                if not ex[r] and not harness_end[r]:
                    harness_end[r] = "wall"
                    agents[r].send("KILL")
            if now - t0 > W["wall_s"] + 15:
                break
        time.sleep(0.01)
    done_ev.set()
    ctl.join(30)
    t_end = mono()
    for r in (0, 1):
        agents[r].close()
    ipt_remove_all()
    meta.update({"t_end": t_end, "wall_s": round(t_end - t0, 3), "anchor_t": anchor_hold[0] if anchor_hold else None,
                 "killed_rank": killed_rank if fault.get("applied") else None,
                 "exit": {r: {"rc": agents[r].app_rc, "t_exit": agents[r].t_exit, "harness_end": harness_end[r],
                              "app_pid": agents[r].app_pid, "agent_rc": agents[r].p.returncode} for r in (0, 1)}})
    if (wl, cls) in HOOKS:
        fault["applied"] = -1  # decided by rows_blind.py from the hook's fire line in the target rank's log
    time.sleep(0.3)
    meta["left"] = leftovers()
    with open(os.path.join(raw, "trial.meta"), "w") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
    return meta


# ---------------------------------------------------------------- stop files and the hold loop
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


def load_schedule(path):
    path = os.path.expanduser(path)
    s = json.load(open(path))
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    prereg = os.path.join(HERE, "PREREG.txt")
    m = re.search(r"schedule\.json sha256 ([0-9a-f]{64})", open(prereg).read()) if os.path.exists(prereg) else None
    if m is None:
        sys.exit("no pre-registered schedule sha256 in %s: blind holds run only after the pre-registration" % prereg)
    if m.group(1) != digest:
        sys.exit("the schedule's sha256 %s is not the pre-registered one %s" % (digest[:12], m.group(1)[:12]))
    return s, digest


def run_list(results, items, calib, cfg, budget_s, kind):
    os.makedirs(results, exist_ok=True)
    site = Site()
    t_start = mono()
    state = {}
    log = open(os.path.join(results, "runner.log"), "a")
    log.write("%s start kind=%s trials=%d md5_match=%d\n" % (time.strftime("%F %T"), kind, len(items), site.md5_match))
    log.flush()
    if not site.md5_match:
        log.write("bundle md5 differs between the nodes: no trial runs\n%s\n" % json.dumps(site.md5))
        with open(os.path.join(results, "STOP_md5"), "a") as f:
            f.write("%s bundle md5 differs between rain and sunny\n" % time.strftime("%F %T"))
        return
    for i, (tid, entry, params) in enumerate(items):
        if stop_present(results):
            log.write("%s STOP file present: %s; stopping\n" % (time.strftime("%F %T"), stop_present(results)))
            break
        if os.path.exists(os.path.join(results, "raw", tid, "trial.meta")):
            continue
        if mono() - t_start + WL[entry["workload"]]["wall_s"] + 15 > budget_s:
            log.write("%s hold budget reached; %d trial(s) left for a later pass\n" % (time.strftime("%F %T"),
                                                                                       len(items) - i))
            break
        meta = run_trial(results, tid, entry, params, site, kind)
        if meta is None:
            continue
        after_trial_checks(results, meta, state)
        log.write("%s trial %s (%d/%d) wall=%.1fs left=%s\n" % (time.strftime("%F %T"), tid, i + 1, len(items),
                                                                meta["wall_s"], meta["left"]))
        log.flush()


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    for n in ("hold", "pending", "baseline", "demo"):
        p = sp.add_parser(n)
        p.add_argument("--results", required=True)
        p.add_argument("--calib", default=DEFAULT_CALIB)
        p.add_argument("--budget-s", type=float, default=840.0)
        if n in ("hold", "pending"):
            p.add_argument("--hold", required=True)
            p.add_argument("--schedule", default=DEFAULT_SCHEDULE)
        if n == "baseline":
            p.add_argument("--workload", required=True, choices=sorted(WL))
            p.add_argument("--n", type=int, required=True)
            p.add_argument("--first", type=int, default=1)
        if n == "demo":
            p.add_argument("--workload", required=True, choices=sorted(WL))
            p.add_argument("--cls", required=True)
            p.add_argument("--target", type=int, default=None)
            p.add_argument("--u-t", type=float, default=0.5)
            p.add_argument("--u-d", type=float, default=0.5)
            p.add_argument("--dir", default="both")
            p.add_argument("--k", type=int, default=None)
            p.add_argument("--t-ms", type=int, default=None)
            p.add_argument("--t-after-anchor-s", type=float, default=None)
            p.add_argument("--at-iter", type=int, default=None)
            p.add_argument("--d-s", type=float, default=None)
            p.add_argument("--name", required=True)
    a = ap.parse_args()
    calib = json.load(open(a.calib))
    cfg = json.load(open(CONFIG))
    results = os.path.abspath(a.results)
    if a.cmd in ("hold", "pending"):
        s, digest = load_schedule(a.schedule)
        items = [(t["id"], t, derive(t, calib, s["header"]["config"])) for t in s["trials"] if t["hold"] == a.hold]
        if a.cmd == "pending":
            print(sum(1 for tid, _, _ in items if not os.path.exists(os.path.join(results, "raw", tid, "trial.meta"))))
            return
        with open(os.path.join(results, "schedule_sha256.txt") if os.path.isdir(results) else os.devnull, "a") as f:
            f.write("%s hold %s schedule sha256 %s\n" % (time.strftime("%F %T"), a.hold, digest))
        run_list(results, items, calib, cfg, a.budget_s, "blind")
    elif a.cmd == "baseline":
        items = []
        for k in range(a.first, a.first + a.n):
            e = {"id": "ref-%s-%d" % (a.workload, k), "workload": a.workload, "cls": "none", "target": None,
                 "u_t": 0.0, "u_d": 0.0, "dir": None}
            items.append((e["id"], e, {}))
        run_list(results, items, calib, cfg, a.budget_s, "baseline")
    else:
        e = {"id": "demo-" + a.name, "workload": a.workload, "cls": a.cls, "target": a.target, "u_t": a.u_t,
             "u_d": a.u_d, "dir": a.dir if a.cls == "mute" else None}
        params = derive(e, calib, cfg)
        for k, v in (("k", a.k), ("t_ms", a.t_ms), ("t_after_anchor_s", a.t_after_anchor_s), ("d_s", a.d_s),
                     ("at_iter", a.at_iter)):
            if v is not None:
                params[k] = v
        run_list(results, [(e["id"], e, params)], calib, cfg, a.budget_s, "demo")


if __name__ == "__main__":
    main()
