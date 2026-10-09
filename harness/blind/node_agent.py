#!/usr/bin/env python3
"""node_agent.py - blind-apps: start one rank of a trial on this node and act on the runner's signals.

blindrun.py starts one agent per rank: on rain as a local child, on sunny through ssh. The agent
  - starts the application (argv, env, cwd from --spec) in its own session, stdout and stderr merged into one pipe,
    under `stdbuf -oL -eL` so that C stdio lines arrive as they are written; the environment is PATH, HOME, USER,
    LOGNAME, SHELL, LANG, LC_ALL, TMPDIR of the agent plus the spec's variables, and the node's LD_LIBRARY_PATH is
    appended to the spec's (nothing else is inherited); the final LD_LIBRARY_PATH and LD_PRELOAD go to stderr;
  - forwards every application line to its own stdout unchanged, except that lines matching a "suppress" pattern are
    forwarded only up to `cap` times per pattern (the rest are counted): an unmodified example that prints one line per
    wrong element would otherwise send millions of lines;
  - reads commands from stdin, one per line: STOP, CONT, KILL (to the application's PID), EXIT (kill the application's
    process group if it is still alive, then exit); every command is answered on stderr;
  - writes its own status lines on stderr only (prefix "AGENT "), so the application's output stays separate:
        AGENT start pid=<pid> mono=<s>
        AGENT sig=<STOP|CONT|KILL> pid=<pid> rc=<0|errno> mono=<s>
        AGENT suppressed name=<name> count=<n>
        AGENT exit pid=<pid> rc=<returncode, negative = signal> mono=<s>
  - kills the application's process group when stdin reaches EOF (the runner or the ssh connection is gone), on
    SIGTERM/SIGHUP, and at exit, so it never leaves a process behind.
Processes are only ever signalled by the PID (or the process group) this agent created. Standard library only
(rain runs Python 3.8, sunny 3.10).

usage: node_agent.py --spec <base64 of a JSON object {tag, argv, env, cwd, suppress: [[name, regex], ...], cap}>
"~" at the start of argv items, env values and cwd is expanded on this node.
"""
import argparse, base64, json, os, re, signal, subprocess, sys, threading, time

SIGS = {"STOP": signal.SIGSTOP, "CONT": signal.SIGCONT, "KILL": signal.SIGKILL}


def mono():
    return time.clock_gettime(time.CLOCK_MONOTONIC)


def say(msg):
    sys.stderr.write("AGENT %s\n" % msg)
    sys.stderr.flush()


def expand(x):
    return os.path.expanduser(x) if isinstance(x, str) and x.startswith("~") else x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    a = ap.parse_args()
    spec = json.loads(base64.b64decode(a.spec).decode())
    argv = ["stdbuf", "-oL", "-eL"] + [expand(x) for x in spec["argv"]]
    # a small base environment, the same on both nodes whatever shell started the runner; the spec adds the rest
    env = {k: os.environ[k] for k in ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "TMPDIR")
           if k in os.environ}
    for k, v in spec.get("env", {}).items():
        env[k] = expand(str(v))
    # the node's own library path (e.g. GDRCopy) stays behind the spec's, as in the earlier runners (env_t1.sh)
    inherited = os.environ.get("LD_LIBRARY_PATH", "")
    if inherited:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH"] + ":" + inherited if env.get("LD_LIBRARY_PATH") else inherited
    cwd = expand(spec.get("cwd") or "~")
    sup = [(n, re.compile(r)) for n, r in spec.get("suppress", [])]
    cap = int(spec.get("cap", 200))
    counts = {n: 0 for n, _ in sup}
    child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, start_new_session=True)
    pgid = child.pid  # start_new_session: the child leads its own session and process group
    lock = threading.Lock()
    state = {"done": False}

    def kill_group():
        with lock:
            if child.poll() is None:
                try:
                    os.killpg(pgid, signal.SIGCONT)  # a stopped group must not stay stopped
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def on_signal(signum, frame):
        kill_group()
        os._exit(0)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    say("start pid=%d mono=%.6f tag=%s" % (child.pid, mono(), spec.get("tag", "")))
    say("env LD_LIBRARY_PATH=%s LD_PRELOAD=%s" % (env.get("LD_LIBRARY_PATH", ""), env.get("LD_PRELOAD", "")))

    def commands():
        for raw in sys.stdin:
            cmd = raw.strip().upper()
            if cmd in SIGS:
                t = mono()
                rc = 0
                with lock:
                    if child.poll() is None:
                        try:
                            os.kill(child.pid, SIGS[cmd])
                        except OSError as e:
                            rc = e.errno or -1
                    else:
                        rc = -1  # already exited
                say("sig=%s pid=%d rc=%d mono=%.6f" % (cmd, child.pid, rc, t))
            elif cmd == "EXIT":
                break
        # EOF or EXIT: the runner is done with this rank (or gone)
        if not state["done"]:
            kill_group()

    threading.Thread(target=commands, daemon=True).start()
    out = sys.stdout.buffer
    for line in child.stdout:
        text = line.decode("utf-8", "replace")
        hit = None
        for n, r in sup:
            if r.search(text):
                hit = n
                break
        if hit is not None:
            counts[hit] += 1
            if counts[hit] > cap:
                continue
        out.write(line)
        out.flush()
    rc = child.wait()
    state["done"] = True
    for n, c in counts.items():
        if c > cap:
            say("suppressed name=%s count=%d" % (n, c - cap))
    say("exit pid=%d rc=%d mono=%.6f" % (child.pid, rc, mono()))
    kill_group()  # anything the application left in its group
    return 0


if __name__ == "__main__":
    sys.exit(main())
