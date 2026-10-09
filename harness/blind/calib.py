#!/usr/bin/env python3
"""calib.py - blind-apps: turn the pilot's fault-free runs and DDP hook probes into calib.json (EXPERIMENT.md 9).

    calib.py <pilot results dir> [--out calib.json]

calib.json maps a schedule entry's drawn fraction u_t onto the run (blindrun.py derive()): a fault lands at
lo + u_t (hi - lo). The rule is fixed here, before the pilot:
  window T per workload = median over the pilot's fault-free runs of (end line - anchor line) on rank 0:
    ddp  anchor "iter 0: loss", end = the last "iter <n>: loss" line
    gin  anchor "=== Comparing GIN ring-exchange implementations ===", end "GIN Ring Exchange result:"
    nvs  anchor "[nvshmem-t1] PE0 <t> enabled:", end = the last "<bytes>B <tab> <ms>ms" size line
  anchor_window_s = [F_LO, F_HI] x T  (kill, stop, mute: seconds after the anchor line)
  hook_ms (gin, nvs) = the same window in ms (the hooks count from GDAKI context creation / NVSHMEM connect, both
    within the same second as the anchor line; the pilot's demo hooks show the offset)
  ddp k_send, k_recv, k_silent: a straight line k(t) = a + b t through the two probes of each hook (demo trials
    named ddp-<sqp|rqp|srq>-k<K>), t = fire line - anchor line on the target rank; range = [k(F_LO T), k(F_HI T)]
A workload without the needed runs keeps the values of the input calib.json and is reported as "kept".

Changed after pilot P1 (EXPERIMENT.md 12), for DDP only. The pilot's 300 iterations took 5.2-15.0 s from run to run,
so a window in seconds does not stay inside the run (k_send by time reached iteration 512 of 300). DDP now uses
training progress for the same fractions: iter_window = [F_LO, F_HI] x ITERS (kill, stop, mute start when rank 0
prints "iter <n>: loss"), and each hook's k is a straight line k(i) through its two probes, i = the last
"iter <n>" line rank 0 printed before the target rank's fire line; range = [k(F_LO ITERS), k(F_HI ITERS)].
"""
import argparse, glob, json, os, re, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from blindrun import NANOGPT_ARGS  # noqa: E402

DDP_ITERS = int([x.split("=", 1)[1] for x in NANOGPT_ARGS if x.startswith("--max_iters=")][0])
F = {"ddp": (0.05, 0.80), "gin": (0.02, 0.85), "nvs": (0.10, 0.85)}
ANCHOR = {"ddp": r"^iter 0: loss", "gin": r"=== Comparing GIN ring-exchange implementations ===",
          "nvs": r"^\[nvshmem-t1\] PE0 [0-9.]+ enabled:"}
END = {"ddp": r"^iter \d+: loss", "gin": r"GIN Ring Exchange result:", "nvs": r"^\d+B\s+[0-9.]+ms"}
FIRE = {"sqp": r"\[FAULT-INJECT\] forced send QP", "rqp": r"\[FAULT-INJECT\] forced recv QP .*before receive post",
        "srq": r"\[FAULT-INJECT\] forced recv QP .*\[silent\]"}


def lines(p):
    out = []
    try:
        for l in open(p, errors="replace"):
            t, _, rest = l.rstrip("\n").partition(" ")
            out.append((float(t), rest))
    except (OSError, ValueError):
        pass
    return out


def first(ls, rx, last=False):
    hits = [t for t, l in ls if re.search(rx, l)]
    return (hits[-1] if last else hits[0]) if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pilot")
    ap.add_argument("--out", default=os.path.join(HERE, "calib.json"))
    a = ap.parse_args()
    cal = json.load(open(a.out))
    report = {}
    metas = {}
    for m in glob.glob(os.path.join(a.pilot, "raw", "*", "trial.meta")):
        metas[os.path.basename(os.path.dirname(m))] = json.load(open(m))
    for wl in ("ddp", "gin", "nvs"):
        Ts = []
        for tid, m in metas.items():
            if m["entry"]["workload"] != wl or m["entry"]["cls"] != "none":
                continue
            r0 = lines(os.path.join(a.pilot, "raw", tid, "r0.log"))
            t_a, t_e = first(r0, ANCHOR[wl]), first(r0, END[wl], last=True)
            if t_a is not None and t_e is not None and t_e > t_a:
                Ts.append(t_e - t_a)
        if not Ts:
            report[wl] = "kept (no fault-free run with both lines)"
            continue
        T = statistics.median(Ts)
        lo, hi = F[wl]
        cal[wl]["anchor_window_s"] = [round(lo * T, 3), round(hi * T, 3)]
        if wl in ("gin", "nvs"):
            cal[wl]["hook_ms"] = [int(round(lo * T * 1000)), int(round(hi * T * 1000))]
        report[wl] = "T=%.3f s from %d run(s) %s" % (T, len(Ts), [round(x, 3) for x in Ts])
        if wl == "ddp":
            report[wl] += "; iter_window over %d iterations" % DDP_ITERS
        if wl == "ddp":
            cal["ddp"]["iter_window"] = [int(round(lo * DDP_ITERS)), int(round(hi * DDP_ITERS))]
            for cls, key in (("sqp", "k_send"), ("rqp", "k_recv"), ("srq", "k_silent")):
                pts = []
                for tid, m in metas.items():
                    e = m["entry"]
                    if not re.match(r"^demo-ddp-%s-k\d+$" % cls, tid) or "k" not in m["params"]:
                        continue  # only the probes (hold.sh P1), not other demos that set k
                    raw = os.path.join(a.pilot, "raw", tid)
                    t_f = first(lines(os.path.join(raw, "r%d.log" % e["target"])), FIRE[cls])
                    its = [(t, int(re.match(r"iter (\d+):", l).group(1))) for t, l in lines(os.path.join(raw, "r0.log"))
                           if re.match(r"iter \d+: loss", l)]
                    done = [i for t, i in its if t_f is not None and t <= t_f]
                    if t_f is not None and done:
                        pts.append((m["params"]["k"], done[-1]))
                pts.sort()
                if len(pts) >= 2 and pts[-1][1] != pts[0][1]:
                    (k1, i1), (k2, i2) = pts[0], pts[-1]
                    b = (k2 - k1) / (i2 - i1)
                    a0 = k1 - b * i1
                    cal["ddp"][key] = [max(1, int(round(a0 + b * lo * DDP_ITERS))), int(round(a0 + b * hi * DDP_ITERS))]
                    report["ddp " + key] = "probes (k, iteration) %s -> k(i) = %.1f + %.2f i" % (pts, a0, b)
                else:
                    report["ddp " + key] = "kept (probes %s)" % pts
    cal["source"] = "calib.py %s" % os.path.abspath(a.pilot)
    with open(a.out, "w") as f:
        json.dump(cal, f, indent=1, sort_keys=True)
        f.write("\n")
    for k in sorted(report):
        print("%s: %s" % (k, report[k]))
    print(json.dumps({k: v for k, v in cal.items() if k != "about"}, sort_keys=True))


if __name__ == "__main__":
    main()
