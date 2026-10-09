#!/usr/bin/env python3
"""handoff.py - blind-apps: build the evaluator's folder from the main run (EXPERIMENT.md 9, step 7).

    handoff.py --results <results dir> --out <new folder outside the repository>

What the folder holds, per trial (blind trials under trials/<workload>/<id>/, the fault-free reference runs under
references/<workload>/<id>/):
  r0.txt, r1.txt   each rank's application and library output through strip_hooks.view(): fault-hook and test-switch
                   lines removed, times in seconds since the trial's start; a final note when the agent did not keep
                   repeated validation lines (count only)
  exit.txt         per rank: exit code or terminating signal, and whether the harness ended it (grace or wall cap)
plus README.txt (the evaluator brief, copied from EXPERIMENT.md between the evaluator-brief markers),
judgments_template.csv and MANIFEST.sha256.
From trial.meta it reads only: id, kind, entry.workload, t0, exit.<rank>.rc, exit.<rank>.harness_end. It never reads
the schedule, the fault fields, the agents' command lines or the runner's log. It refuses (exit 1, nothing written) if
the output exists, if a kept line matches strip_hooks.LEAK, or if a trial has no meta.
"""
import argparse, glob, hashlib, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from strip_hooks import leaks, view  # noqa: E402

START, END = "<!-- evaluator-brief:start -->", "<!-- evaluator-brief:end -->"


def read_log(p):
    out = []
    try:
        for l in open(p, errors="replace"):
            t, _, rest = l.rstrip("\n").partition(" ")
            try:
                out.append((float(t), rest))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def exit_text(x):
    rc, end = x.get("rc"), x.get("harness_end") or ""
    if rc is None:
        s = "no exit status recorded"
    elif rc < 0:
        s = "terminated by signal %d" % (-rc)
    else:
        s = "exit code %d" % rc
    return s + ("; ended by the harness (%s)" % ("grace period after the other rank ended" if end == "grace" else
                                                 "wall-clock cap") if end else "; not ended by the harness")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--experiment", default=os.path.join(HERE, "EXPERIMENT.md"))
    ap.add_argument("--include-demo", action="store_true", help="pilot only: also stage demo trials (leak audit test)")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    if os.path.exists(out):
        sys.exit("refused: %s exists" % out)
    for repo in (os.path.join(HERE, "..", ".."), os.path.expanduser("~/rdma-error"), os.path.expanduser("~/rdma-error-wt")):
        if (out + os.sep).startswith(os.path.abspath(repo) + os.sep):
            sys.exit("refused: the evaluator's folder must be outside the repository and its worktrees")
    doc = open(a.experiment).read()
    if START not in doc or END not in doc:
        sys.exit("refused: no evaluator brief in %s" % a.experiment)
    brief = doc.split(START, 1)[1].split(END, 1)[0].strip() + "\n"
    staged, bad, n = {}, [], {}
    for meta in sorted(glob.glob(os.path.join(os.path.abspath(a.results), "raw", "*", "trial.meta"))):
        d = os.path.dirname(meta)
        m = json.load(open(meta))
        kind = m.get("kind")
        if kind not in ("blind", "baseline") and not (a.include_demo and kind == "demo"):
            continue
        tid, wl, t0 = m["id"], m["entry"]["workload"], m["t0"]
        sub = os.path.join({"blind": "trials", "baseline": "references"}.get(kind, "demo"), wl, tid)
        files = {}
        for r in (0, 1):
            v = view(read_log(os.path.join(d, "r%d.log" % r)), t0)
            bad += ["%s r%d: %s" % (tid, r, l[:120]) for l in leaks(v)]
            txt = "".join("%9.3f %s\n" % (t, l) for t, l in v)
            for t, l in read_log(os.path.join(d, "a%d.log" % r)):
                mm = re.match(r"AGENT suppressed name=([\w-]+) count=(\d+)", l)
                if mm:
                    what = {"validation": 'validation lines ("error, data[")', "mismatch": 'mismatch lines',
                            "nccl-trace": 'NCCL INFO error-trace lines ("<file>:<line> -> <code>")'}.get(mm.group(1),
                                                                                                    mm.group(1))
                    txt += "(note: %s further %s were not kept; the first 200 are above)\n" % (mm.group(2), what)
            files["r%d.txt" % r] = txt
        ex = m.get("exit", {})
        files["exit.txt"] = "".join("rank %d: %s\n" % (r, exit_text(ex.get(str(r), ex.get(r, {})) or {}))
                                    for r in (0, 1))
        staged[sub] = files
        if kind == "blind":
            n[wl] = n.get(wl, 0) + 1
    if bad:
        sys.exit("refused: %d kept line(s) match the leak audit, e.g. %s" % (len(bad), bad[:3]))
    if not n and not a.include_demo:
        sys.exit("refused: no blind trial found")
    os.makedirs(out)
    for sub, files in staged.items():
        os.makedirs(os.path.join(out, sub))
        for name, txt in files.items():
            with open(os.path.join(out, sub, name), "w") as f:
                f.write(txt)
    with open(os.path.join(out, "README.txt"), "w") as f:
        f.write(brief)
    with open(os.path.join(out, "judgments_template.csv"), "w") as f:
        f.write("trial_id,workload,fault_class,target_rank,outcome,result_ok,first_error_s,confidence,evidence\n")
        for sub in sorted(staged):
            parts = sub.split(os.sep)
            if parts[0] == "trials":
                f.write("%s,%s,,,,,,,\n" % (parts[2], parts[1]))
    man = []
    for root, _, fs in os.walk(out):
        for fn in sorted(fs):
            p = os.path.join(root, fn)
            man.append("%s  %s" % (hashlib.sha256(open(p, "rb").read()).hexdigest(), os.path.relpath(p, out)))
    with open(os.path.join(out, "MANIFEST.sha256"), "w") as f:
        f.write("\n".join(sorted(man, key=lambda x: x.split("  ", 1)[1])) + "\n")
    digest = hashlib.sha256(open(os.path.join(out, "MANIFEST.sha256"), "rb").read()).hexdigest()
    print("evaluator folder: %s" % out)
    print("blind trials: %s; references: %d" % (n, sum(1 for s in staged if s.startswith("references"))))
    print("MANIFEST.sha256 sha256: %s" % digest)


if __name__ == "__main__":
    main()
