#!/usr/bin/env python3
"""gate_proc_gc.py - gin-control, test side: the CPU test of section 3's gate_fenced on a REAL process (REVIEW_TEST fix 1).
Standard library only; CPU only; no cluster, no GPU, no verbs. It starts only its own child processes and signals none.

    gate_proc_gc.py [--trials 10] [--second-ms 500] [--gate-bin PATH] [--out local/gate_proc.log]

Each trial starts a child Python process whose main thread ends first (a raw exit of that one thread, so the thread-group
leader is a zombie while the group lives) and whose second thread lives SECOND_MS longer and then ends the group. This
program measures, on its own and on the same CLOCK_MONOTONIC:
  z_ms               when /proc/<pid>/stat first shows the leader in state Z (what the old gate, Z = GO, reads)
  pidfd_ms           when a pidfd of the child (pidfd_open) becomes readable (the group ended: what FENCED waits for)
  second_thread_ms   when the child's second thread said it ends (its own clock reading, just before the group exit)
all from the main thread's own end (the child's reading just before its raw exit). With --gate-bin, the library's gate
program is started on the child's pid before the main thread ends: `<gate-bin> --pid <pid>` must print one line
"old GO mono_ms=<ms>" and one line "FENCED GO mono_ms=<ms>" (CLOCK_MONOTONIC) when its two gates say GO; that mode of
../gate_fenced.cc is TODO(gate_fenced.cc's owner: run gdakiRsActExamine and gdakiCtrlActGate on a real pid). Without it the
gate columns stay empty and the prediction is "자료 부족", never a pass from values the program sets itself.

One line per trial (rows_gc.py reads it):
  gate_proc trial K: real=1 pid=P second_thread_ms=.. pidfd_ms=.. z_ms=.. old_go_ms=..|- fenced_go_ms=..|-
"""
import argparse, ctypes, os, platform, select, subprocess, sys, threading, time

CHILD = r'''
import ctypes, os, platform, sys, threading, time
def mono(): return time.clock_gettime(time.CLOCK_MONOTONIC) * 1000.0
sec = float(sys.argv[1])
NR_EXIT = {"x86_64": 60, "aarch64": 93}[platform.machine()]
libc = ctypes.CDLL(None, use_errno=True)
t_main = []
def second():
    while not t_main:
        time.sleep(0.0005)
    while mono() < t_main[0] + sec:
        time.sleep(0.0005)
    sys.stdout.write("second_end %.3f\n" % mono()); sys.stdout.flush()
    os._exit(0)
threading.Thread(target=second).start()
sys.stdout.write("ready\n"); sys.stdout.flush()
sys.stdin.readline()
t = mono()
sys.stdout.write("main_end %.3f\n" % t); sys.stdout.flush()
t_main.append(t)
libc.syscall(NR_EXIT, 0)  # this thread only (not exit_group); ctypes released the GIL for the call
'''


def mono():
    return time.clock_gettime(time.CLOCK_MONOTONIC) * 1000.0


def pidfd_open(pid):
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.syscall(434, pid, 0)  # pidfd_open: 434 on every architecture (Linux 5.3)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "pidfd_open")
    return fd


def one(k, second_ms, gate_bin):
    ch = subprocess.Popen([sys.executable, "-c", CHILD, str(second_ms)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert ch.stdout.readline().strip() == b"ready"
    fd = pidfd_open(ch.pid)
    gate, gl = None, []
    if gate_bin:
        gate = subprocess.Popen([gate_bin, "--pid", str(ch.pid)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        rd = threading.Thread(target=lambda: gl.extend(gate.stdout.read().decode("utf-8", "replace").splitlines()))
        rd.start()
        time.sleep(0.2)  # the gate program's own start (TODO(gate_fenced.cc's owner): a "watching" line instead)
    z = []

    def watch():
        end = mono() + 5000.0
        while mono() < end:
            try:
                st = open("/proc/%d/stat" % ch.pid).read()
            except OSError:
                return
            if st.rsplit(")", 1)[1].split()[0] == "Z":
                z.append(mono())
                return
            time.sleep(0.0002)
    w = threading.Thread(target=watch)
    w.start()
    ch.stdin.write(b"go\n")
    ch.stdin.flush()
    p = select.poll()
    p.register(fd, select.POLLIN)
    t_fd = None
    if p.poll(10000):
        t_fd = mono()
    os.close(fd)
    out = ch.stdout.read().decode().split("\n")
    ch.wait(timeout=10)
    w.join()
    vals = {l.split()[0]: float(l.split()[1]) for l in out if len(l.split()) == 2}
    tm = vals.get("main_end")
    old = fen = None
    if gate is not None:
        gate.wait(timeout=10)
        rd.join()
        for l in gl:
            if l.startswith("old GO mono_ms="):
                old = float(l.split("=", 1)[1])
            elif l.startswith("FENCED GO mono_ms="):
                fen = float(l.split("=", 1)[1])
    rel = lambda x: "-" if (x is None or tm is None) else "%.3f" % (x - tm)
    return ("gate_proc trial %d: real=1 pid=%d second_thread_ms=%s pidfd_ms=%s z_ms=%s old_go_ms=%s fenced_go_ms=%s"
            % (k, ch.pid, rel(vals.get("second_end")), rel(t_fd), rel(z[0] if z else None), rel(old), rel(fen)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--second-ms", type=float, default=500.0)
    ap.add_argument("--gate-bin", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "aarch64"):
        sys.exit("gate_proc_gc.py: Linux x86_64 or aarch64 only")
    lines = [one(k, a.second_ms, a.gate_bin) for k in range(a.trials)]
    txt = "\n".join(lines) + "\n"
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, "w").write(txt)
    sys.stdout.write(txt)


if __name__ == "__main__":
    main()
