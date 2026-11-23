"""nbrun.py - run one 2-rank trial of the nccl-builtin study: rain = rank 0 (local), sunny = rank 1 (ssh).

Orchestration only. The mechanisms under test are inside libnccl (the bundles of deploy_nb.sh); the driver nb_ct is
../perf/nccl_ct.cu unchanged (all-reduce or broadcast, every result buffer checked bit-exactly on the GPU).

Safety (EXPERIMENT.md 8):
  - run only inside a hold of hold.sh, itself inside ../../gpu-initiated/common/cluster_run.sh (chain.sh);
  - every trial is bounded: the driver's per-iteration timeout, its ncclCommAbort watchdog, the grace after one rank
    exits, and a wall cap after which the runner kills both ranks;
  - processes are killed only by PID: rank 0 is our Popen child; rank 1 writes its PID to $HOME/nb-bundle/run/r1.pid
    and is killed only if /proc/<pid>/comm is nb_ct (the binary name used by this study only);
  - nothing here changes a link, an address, a firewall rule or a driver.
Environment set by hold.sh: SUNNY_SSH (rank 1's ssh target), R0_MGMT (rain's eno1 address, the driver's rendezvous).
"""
import json, os, random, shlex, socket, subprocess, threading, time

BUNDLE = "nb-bundle"                        # $HOME/nb-bundle/{n232,s2,run} on both nodes (deploy_nb.sh)
LIBFILE = {"n232": "libnccl.so.2.32.3", "s2": "libnccl.so.2.23.4"}
DRV = "nb_ct"
CUDA_LIB = "/usr/local/cuda-12.8/lib64"
HCA = ("mlx5_1", "mlx5_0")                  # rain, sunny
HOME = os.path.expanduser("~")
GRACE_S = 6.0                               # after a rank exits non-zero, the other gets this long before the kill

GID_PROBE = r'''d=/sys/class/infiniband/$1/ports/$2
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done
exit 1'''


def sunny():
    return os.environ["SUNNY_SSH"]


def ssh(cmd, timeout=30, **kw):
    return subprocess.run(["ssh", "-n", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", sunny(), cmd],
                          capture_output=True, text=True, timeout=timeout, **kw)


def gid_indices():
    """The first RoCE v2 IPv4-mapped GID index on rain mlx5_1 and sunny mlx5_0 (sysfs, read only)."""
    g0 = subprocess.run(["bash", "-s", "--", HCA[0], "1"], input=GID_PROBE, capture_output=True, text=True).stdout.strip()
    g1 = subprocess.run(["ssh", "-o", "BatchMode=yes", sunny(), "bash", "-s", "--", HCA[1], "1"], input=GID_PROBE,
                        capture_output=True, text=True).stdout.strip()
    if not g0 or not g1:
        raise RuntimeError(f"GID detection failed: rain={g0!r} sunny={g1!r}")
    return g0, g1


def free_port(lo=44000, hi=48000):
    for _ in range(200):
        p = random.randint(lo, hi)
        s = socket.socket()
        try:
            s.bind(("0.0.0.0", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError("no free port")


def left_count():
    """nb_ct processes still alive on rain and on sunny (only this study uses that name)."""
    a = subprocess.run(["pgrep", "-x", DRV], capture_output=True, text=True).stdout.split()
    try:
        b = ssh(f"pgrep -x {DRV}", timeout=15).stdout.split()
    except subprocess.TimeoutExpired:
        b = ["?"]
    return len(a), len(b)


def kill_r1():
    """SIGKILL rank 1 by its PID file, only if that PID is an nb_ct process. Returns the remote report."""
    cmd = (f'p=$(cat $HOME/{BUNDLE}/run/r1.pid 2>/dev/null); '
           f'if [ -n "$p" ] && [ "$(cat /proc/$p/comm 2>/dev/null)" = {DRV} ]; then kill -9 "$p" && echo "killed $p"; '
           f'else echo "nokill pid=$p"; fi')
    try:
        return ssh(cmd, timeout=15).stdout.strip()
    except subprocess.TimeoutExpired:
        return "ssh-timeout"


class Rank:
    """One rank's process; every output line is written as '<CLOCK_MONOTONIC of rain at receipt> <line>'."""

    def __init__(self, rank, argv, env, bundle, log_path):
        self.rank, self.lines, self.done_t = rank, [], None
        self.log = open(log_path, "w")
        bdir = f"{BUNDLE}/{bundle}"
        if rank == 1:
            envs = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
            # 2>&1 on the remote side: NCCL's stdout lines and the driver's stderr lines share one pipe, so their
            # order of receipt is their order of writing (rank 0 gets the same from stderr=STDOUT below)
            cmd = (f"cd $HOME/{bdir} && echo $$ > $HOME/{BUNDLE}/run/r1.pid && exec env "
                   f"LD_LIBRARY_PATH=$HOME/{bdir}:{CUDA_LIB} {envs} stdbuf -oL -eL ./{DRV} {' '.join(argv)} 2>&1")
            self.p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", sunny(), cmd], stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, errors="replace")
        else:
            e = dict(os.environ)
            e.update(env)
            e["LD_LIBRARY_PATH"] = f"{HOME}/{bdir}:{CUDA_LIB}"
            self.p = subprocess.Popen(["stdbuf", "-oL", "-eL", f"{HOME}/{bdir}/{DRV}"] + argv, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, errors="replace", env=e)
        self.t = threading.Thread(target=self._read, daemon=True)
        self.t.start()

    def _read(self):
        for line in self.p.stdout:
            now = time.monotonic()
            self.log.write(f"{now:.6f} {line}")
            self.lines.append(now)
        self.done_t = time.monotonic()
        self.log.flush()


def run_trial(logdir, stem, bundle, env0, env1, args, wall_s, kill_at_s=None, gids=None):
    """Run one trial. Writes <stem>_r0.log, <stem>_r1.log, <stem>_meta.txt in logdir; returns the meta dict."""
    os.makedirs(logdir, exist_ok=True)
    g0, g1 = gids or gid_indices()
    base = {"NCCL_SOCKET_IFNAME": "eno1"}
    e0 = {**base, "NCCL_IB_HCA": HCA[0], "NCCL_IB_GID_INDEX": g0, **env0}
    e1 = {**base, "NCCL_IB_HCA": HCA[1], "NCCL_IB_GID_INDEX": g1, **env1}
    left_before = left_count()
    port = free_port()
    a = ["--ip", os.environ["R0_MGMT"], "--port", str(port)] + args
    meta = {"stem": stem, "bundle": bundle, "port": port, "args": " ".join(args), "env0": json.dumps(e0, sort_keys=True),
            "env1": json.dumps(e1, sort_keys=True), "wall_cap_s": wall_s, "kill_at_s": kill_at_s if kill_at_s else "",
            "left_before": "%d,%d" % left_before, "date": time.strftime("%F %T")}
    t0 = time.monotonic()
    meta["t0"] = "%.6f" % t0
    r0 = Rank(0, ["--rank", "0"] + a, e0, bundle, os.path.join(logdir, f"{stem}_r0.log"))
    time.sleep(0.3)
    meta["t_launch1"] = "%.6f" % time.monotonic()
    r1 = Rank(1, ["--rank", "1"] + a, e1, bundle, os.path.join(logdir, f"{stem}_r1.log"))
    killed1 = False
    exit_t = {}
    grace_kill = [0, 0]
    wallcap = 0
    while True:
        now = time.monotonic()
        for i, r in ((0, r0), (1, r1)):
            if i not in exit_t and r.p.poll() is not None:
                exit_t[i] = now
        if len(exit_t) == 2:
            break
        if kill_at_s is not None and not killed1 and now - t0 >= kill_at_s:
            killed1 = True
            meta["t_kill_req"] = "%.6f" % time.monotonic()
            meta["kill_out"] = kill_r1()
            meta["t_kill_done"] = "%.6f" % time.monotonic()
        # grace: a rank that ended non-zero (other than the rank this trial killed) gives the other GRACE_S
        for i, r in ((0, r0), (1, r1)):
            j = 1 - i
            if i in exit_t and j not in exit_t and not (i == 1 and killed1):
                if r.p.returncode != 0 and now - exit_t[i] > GRACE_S:
                    grace_kill[j] = 1
        if grace_kill[0] and 0 not in exit_t:
            r0.p.kill()
        if grace_kill[1] and 1 not in exit_t:
            meta["grace_kill_out_r1"] = kill_r1()
            r1.p.kill()
            exit_t[1] = time.monotonic()
        if now - t0 > wall_s:
            wallcap = 1
            if 0 not in exit_t:
                r0.p.kill()
            if 1 not in exit_t:
                meta["wall_kill_out_r1"] = kill_r1()
                r1.p.kill()
            break
        time.sleep(0.005)
    for r in (r0, r1):
        try:
            r.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            r.p.kill()
    r0.t.join(5)
    r1.t.join(5)
    for r in (r0, r1):   # a reader still blocked on a pipe must not keep its lines from the log
        r.log.flush()
    t1 = time.monotonic()
    meta.update({"t_end": "%.6f" % t1, "wall_s": "%.3f" % (t1 - t0), "rc0": r0.p.returncode, "rc1": r1.p.returncode,
                 "exit_t0": "%.6f" % exit_t.get(0, t1), "exit_t1": "%.6f" % exit_t.get(1, t1),
                 "grace_kill_r0": grace_kill[0], "grace_kill_r1": grace_kill[1], "wallcap": wallcap,
                 "killed_r1": int(killed1), "gid0": g0, "gid1": g1})
    # rank 1 may outlive its ssh client (wall cap, grace, a dropped connection): end this trial's rank 1 by its PID
    # (a no-op report "nokill" when it has already exited), then count what is left on both nodes
    meta["final_kill_out_r1"] = kill_r1()
    time.sleep(0.5)
    meta["left_after"] = "%d,%d" % left_count()
    with open(os.path.join(logdir, f"{stem}_meta.txt"), "w") as f:
        for k, v in meta.items():
            f.write(f"{k}={v}\n")
    return meta
