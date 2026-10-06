#!/usr/bin/env python3
"""Read-only recount of the NCCL net_ib (Stage 1/2), perf and transparent_probe raw data.
Extracts the Stage 2 / perf log archives into this script's directory (x/), never into the repo.
usage: python3 recount_nccl.py
"""
import csv, collections, glob, os, re, statistics as st, subprocess, tarfile

REPO = os.path.expanduser("~/rdma-error/harness")
NI = f"{REPO}/nccl-integration"
S2R = f"{NI}/stage2/results/20260925"
PRF = f"{NI}/perf/results/20260925"
PROBE = f"{REPO}/gpu-initiated/transparent_probe/results"
X = os.path.join(os.path.dirname(os.path.abspath(__file__)), "x")


def ts(l):
    try:
        return float(l.split()[0])
    except Exception:
        return None


def extract():
    for base, sub in ((S2R, ""), (PRF, "perf")):
        for d in sorted(glob.glob(f"{base}/*/logs.tar.gz")):
            out = os.path.join(X, sub, os.path.basename(os.path.dirname(d)))
            if not os.path.isdir(out):
                os.makedirs(out)
                with tarfile.open(d) as t:
                    t.extractall(out)


def verdicts():
    print("## Stage 2 results.csv verdicts and recovery medians")
    for f in sorted(glob.glob(f"{S2R}/*/results.csv")):
        by = collections.OrderedDict()
        for r in csv.DictReader(open(f)):
            by.setdefault(r["test"], []).append(r)
        for t, rs in by.items():
            xs = [float(x) for r in rs for x in r["rec_ms"].split(";") if x]
            vc = dict(collections.Counter(r["verdict"] for r in rs))
            med = f"{st.median(xs):.3f} [{min(xs):.3f}-{max(xs):.3f}] n={len(xs)}" if xs else "-"
            print(f"  {os.path.basename(os.path.dirname(f))} {t}: runs={len(rs)} {vc} rec_ms={med}")


def recoveries():
    print("## Stage 2 send-comm recoveries (executed prefix, replay)")
    pat = re.compile(r"send comm: recovered \(epoch (\d+), round (\d+)\): first error (\S+) via (\w+); "
                     r"R_done=(\d+) fifoHead=(\d+) peerFifoTail=(\d+); completed (\d+) group\(s\) R had, replayed (\d+)")
    n = comp = rounds = 0
    depth = collections.Counter()
    for f in glob.glob(f"{X}/*/*.log"):
        for l in open(f, errors="replace"):
            m = pat.search(l)
            if m:
                ep, rd, fe, via, rdn, fh, ft, c, rep = m.groups()
                n += 1
                comp += int(c) > 0
                rounds += int(rd) > 1
                depth[(int(fh) - int(rdn), int(ft) - int(rdn))] += 1
                if int(c) > 0:
                    print(f"  executed-but-unacked groups completed without resend: {f.split('/')[-2]}/{os.path.basename(f)} {fe} completed={c} replayed={rep}")
    print(f"  total={n} with_completed>0={comp} round>1={rounds}")
    print(f"  (fifoHead-R_done, peerFifoTail-R_done) histogram: {sorted(depth.items())}")


def t8_latency():
    print("## T8: survivor's first FAULT-RECOVERY2 line minus peer's last IT line (runner clock, ms)")
    for camp in ("C5", "A4", "A5", "C7"):
        out = []
        for f0 in sorted(glob.glob(f"{X}/{camp}/T8_*_r0.log")):
            last1 = None
            for l in open(f0.replace("_r0", "_r1"), errors="replace"):
                if re.match(r"^\d+\.\d+ IT ", l):
                    last1 = ts(l)
            err = next((ts(l) for l in open(f0, errors="replace") if "FAULT-RECOVERY2" in l and ts(l)), None)
            out.append(None if err is None or last1 is None else round((err - last1) * 1e3, 2))
        print(f"  {camp}: {out}")


def flap():
    print("## Address flap: GID_CHANGE events (type 18) and RETRY_EXC after re-add (s)")
    for camp in ("D2", "D2ctl", "A4", "A5"):
        for f1 in sorted(glob.glob(f"{X}/{camp}/T7*_r1.log")):
            f0 = f1.replace("_r1", "_r0")
            ev = [ts(l) for l in open(f1, errors="replace") if "unknown event type (18)" in l]
            first = lambda f: next((ts(l) for l in open(f, errors="replace") if re.search(r"status=12", l) and ts(l)), None)
            moved = sum("local GID moved" in l for l in open(f1, errors="replace"))
            r0, r1 = first(f0), first(f1)
            if ev and r0 and r1:
                print(f"  {camp} {os.path.basename(f1)[:6]} events={len(ev)} cut={ev[-1]-ev[0]:.3f}s "
                      f"RETRY_EXC-after-readd rain={r0-ev[-1]:.2f} sunny={r1-ev[-1]:.2f} gid_moved_lines={moved}")


def api_strings():
    print("## distinct API-level error strings (Stage 2 logs)")
    c = collections.Counter()
    for f in glob.glob(f"{X}/*/*.log"):
        for l in open(f, errors="replace"):
            m = re.search(r"(async NCCL error[^:]*: |ncclAllReduce -> )(.*)", l)
            if m:
                c[(m.group(1).split()[0], m.group(2).strip())] += 1
    print(f"  {dict(c)}")
    hang = len([f for f in glob.glob(f"{X}/**/*.log", recursive=True) if "ABORT-HANG" in open(f, errors="replace").read()])
    ret = len([f for f in glob.glob(f"{X}/**/*.log", recursive=True) if "ncclCommAbort returned" in open(f, errors="replace").read()])
    print(f"  ABORT-HANG files={hang} abort-returned files={ret}")


def probe():
    print("## transparent_probe Q1")
    for run in ("run1", "run2"):
        q = [l for f in glob.glob(f"{PROBE}/{run}/*.req.log") for l in open(f) if "what=Q1" in l]
        print(f"  {run}: Q1 lines={len(q)} match={sum('Q1_MATCH=1' in l for l in q)} "
              f"ERR={sum('resp_state=6' in l for l in q)} RTS={sum('resp_state=3' in l for l in q)}")
        for f in sorted(glob.glob(f"{PROBE}/{run}/r[ab]_s*.req.log")):
            s = open(f).read()
            g = lambda k: (re.search(k + r"=(\S+)", s) or [None, "-"])[1]
            print(f"    {os.path.basename(f)} completed={g('completed')} err={g('err')} my_nsp={g('my_nsp')} "
                  f"next_rcv_psn={g('next_rcv_psn')} rmsn={g('rmsn')} replayed={g('replayed')}")


if __name__ == "__main__":
    extract()
    verdicts()
    recoveries()
    t8_latency()
    flap()
    api_strings()
    probe()
    print("## perf (existing summarizer)")
    subprocess.run(["python3", f"{NI}/perf/summarize.py"] + sorted(glob.glob(f"{PRF}/*/")))
