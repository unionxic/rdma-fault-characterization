"""ctlib.py - run the 2-rank nccl_ct job on rain (rank 0, local) and sunny (rank 1, ssh).

Only orchestration lives here (launch, watch, kill, parse). The mechanism under test is
inside libnccl (net_ib.cc); nccl_ct only generates the workload and checks the data.
"""
import os, re, shlex, subprocess, threading, time

SCRATCH = "/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad"
DRV = f"{SCRATCH}/ct/nccl_ct"
PEER = "unionxic@192.0.2.194"          # sunny, management network
PEER_DIR = "nccl-ct"                        # ~/nccl-ct on sunny: <build>/libnccl.so.2, nccl_ct
R0_MGMT = "192.0.2.193"                 # rain eno1
CUDA_LIB = "/usr/local/cuda-12.8/lib64"
LIBS = {                                    # build name -> lib dir on rain
    "stock": f"{SCRATCH}/n2/stock/build/lib",
    "stage1i": f"{SCRATCH}/n2/stage1i/build/lib",
    "stage2": f"{SCRATCH}/n2/stage2/build/lib",
    "stage2f": f"{SCRATCH}/n2/stage2f/build/lib",   # frozen copy used by the completion-time campaign
    "stage2old": f"{SCRATCH}/n2/stage2_78f/build/lib",   # build 78f96f38, before the OOB-loss fix (T12b control)
    "stage2rst": f"{SCRATCH}/n2/stage2_7b0/build/lib",   # build 7b0d0122, RST still counted as death (T12c control)
}

GID_PROBE = r'''d=/sys/class/infiniband/$1/ports/$2
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done
exit 1'''

SINGLE = {"NCCL_MAX_NCHANNELS": "1", "NCCL_MIN_NCHANNELS": "1", "NCCL_ALGO": "Ring",
          "NCCL_PROTO": "Simple", "NCCL_IB_QPS_PER_CONNECTION": "1"}


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def gid_indices():
    g0 = subprocess.run(["bash", "-s", "--", "mlx5_1", "1"], input=GID_PROBE, capture_output=True, text=True).stdout.strip()
    g1 = subprocess.run(["ssh", "-o", "BatchMode=yes", PEER, "bash", "-s", "--", "mlx5_0", "1"], input=GID_PROBE,
                        capture_output=True, text=True).stdout.strip()
    if not g0 or not g1:
        raise RuntimeError(f"GID detection failed: rain={g0!r} sunny={g1!r}")
    return g0, g1


def deploy(builds):
    """Copy the driver and the given builds' libnccl to sunny:~/nccl-ct/<build>/."""
    for b in builds:
        lib = LIBS[b]
        r = sh(f"ssh -o BatchMode=yes {PEER} 'mkdir -p ~/{PEER_DIR}/{b}' && "
               f"scp -q {lib}/libnccl.so.2.23.4 {PEER}:{PEER_DIR}/{b}/libnccl.so.2 && "
               f"scp -q {DRV} {PEER}:{PEER_DIR}/nccl_ct")
        if r.returncode:
            raise RuntimeError(f"deploy {b} failed: {r.stderr}")
    # verify the copies are byte-identical
    for b in builds:
        local = sh(f"md5sum {LIBS[b]}/libnccl.so.2.23.4").stdout.split()[0]
        remote = sh(f"ssh -o BatchMode=yes {PEER} md5sum {PEER_DIR}/{b}/libnccl.so.2").stdout.split()[0]
        if local != remote:
            raise RuntimeError(f"deploy {b}: md5 mismatch")


def cleanup():
    sh("pkill -9 -x nccl_ct")
    sh(f"ssh -o BatchMode=yes {PEER} 'pkill -9 -x nccl_ct'")
    time.sleep(1)


SUMMARY_RE = re.compile(r"SUMMARY (.*)")
FAIL_RE = re.compile(r"async NCCL error|TIMEOUT after|MISMATCH|ncclAllReduce ->|CUDA error")


def parse_summary(line):
    d = {}
    for kv in line.split():
        k, _, v = kv.partition("=")
        try:
            d[k] = float(v) if "." in v else int(v)
        except ValueError:
            d[k] = v
    return d


class Rank:
    def __init__(self, rank, argv, env, remote, log_path):
        self.rank, self.lines, self.summary, self.first_fail_t, self.done_t = rank, [], None, None, None
        self.log = open(log_path, "w")
        if remote:
            envs = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
            cmd = (f"cd ~/{PEER_DIR} && env LD_LIBRARY_PATH=$HOME/{PEER_DIR}/{env['_BUILD']}:{CUDA_LIB} {envs} "
                   f"stdbuf -oL -eL ./nccl_ct {' '.join(argv)}")
            self.p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", PEER, cmd], stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True)
        else:
            e = dict(os.environ)
            e.update({k: v for k, v in env.items() if not k.startswith("_")})
            e["LD_LIBRARY_PATH"] = f"{LIBS[env['_BUILD']]}:{CUDA_LIB}"
            self.p = subprocess.Popen(["stdbuf", "-oL", "-eL", DRV] + argv, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, env=e)
        self.t = threading.Thread(target=self._read, daemon=True)
        self.t.start()

    def _read(self):
        for line in self.p.stdout:
            now = time.monotonic()
            self.log.write(f"{now:.6f} {line}")
            self.lines.append((now, line.rstrip("\n")))
            m = SUMMARY_RE.search(line)
            if m:
                self.summary = parse_summary(m.group(1))
            if self.first_fail_t is None and (FAIL_RE.search(line) or (m and self.summary.get("rc", 0) != 0)):
                self.first_fail_t = now
        self.done_t = time.monotonic()
        self.log.flush()


def free_port(lo=44000, hi=48000):
    """A TCP port nobody listens on (and nothing is bound to) on rain."""
    import random, socket
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


def run_pair(outdir, tag, build, env_common, env0=None, env1=None, args=None, timeout=600,
             kill_on_fail=False, port=None, early_exit=True):
    """Run one 2-rank job. Returns a dict with rcs, summaries, wall time, failure time.

    kill_on_fail: as soon as either rank reports an error, SIGKILL both ranks (what a job
    manager does before restarting). The failure time is when the first error line appeared.
    """
    os.makedirs(outdir, exist_ok=True)
    g0, g1 = gid_indices() if not hasattr(run_pair, "_gids") else run_pair._gids
    run_pair._gids = (g0, g1)
    base0 = {"NCCL_IB_HCA": "mlx5_1", "NCCL_IB_GID_INDEX": g0, "NCCL_SOCKET_IFNAME": "eno1",
             "NCCL_DEBUG": "WARN", "_BUILD": build}
    base1 = {"NCCL_IB_HCA": "mlx5_0", "NCCL_IB_GID_INDEX": g1, "NCCL_SOCKET_IFNAME": "eno1",
             "NCCL_DEBUG": "WARN", "_BUILD": build}
    e0 = {**base0, **env_common, **(env0 or {})}
    e1 = {**base1, **env_common, **(env1 or {})}
    cleanup()
    port = free_port()
    a = ["--ip", R0_MGMT, "--port", str(port)] + (args or [])
    t0 = time.monotonic()
    r0 = Rank(0, ["--rank", "0"] + a, e0, False, f"{outdir}/{tag}_r0.log")
    time.sleep(0.3)
    r1 = Rank(1, ["--rank", "1"] + a, e1, True, f"{outdir}/{tag}_r1.log")
    killed = False
    while True:
        if r0.p.poll() is not None and r1.p.poll() is not None:
            break
        # a rank that died on its own (setup error, crash) never lets the other finish
        if early_exit and not killed and ((r0.p.poll() not in (None, 0)) or (r1.p.poll() not in (None, 0))):
            time.sleep(0.5)
            if r0.p.poll() is None or r1.p.poll() is None:
                killed = True
                r0.p.kill(); r1.p.kill()
                sh(f"ssh -o BatchMode=yes {PEER} 'pkill -9 -x nccl_ct'")
        if kill_on_fail and not killed and (r0.first_fail_t or r1.first_fail_t):
            killed = True
            r0.p.kill(); r1.p.kill()
            sh(f"ssh -o BatchMode=yes {PEER} 'pkill -9 -x nccl_ct'")
        if time.monotonic() - t0 > timeout:
            r0.p.kill(); r1.p.kill(); cleanup()
            break
        time.sleep(0.005)
    r0.t.join(5); r1.t.join(5)
    t1 = time.monotonic()
    ff = [t for t in (r0.first_fail_t, r1.first_fail_t) if t]
    return {
        "tag": tag, "build": build, "rc0": r0.p.returncode, "rc1": r1.p.returncode,
        "s0": r0.summary, "s1": r1.summary, "t_start": t0, "t_end": t1, "wall_s": t1 - t0,
        "t_fail": min(ff) if ff else None, "killed": killed, "timed_out": (t1 - t0) > timeout,
        "lines0": r0.lines, "lines1": r1.lines,
    }


def grep(res, pattern):
    rx = re.compile(pattern)
    return [(t, r, l) for r, lines in ((0, res["lines0"]), (1, res["lines1"])) for t, l in lines if rx.search(l)]
