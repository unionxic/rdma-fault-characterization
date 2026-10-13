#!/usr/bin/env python3
"""summ_mf.py <resultsdir> | --selftest <scratch dir> - readings of gin-mirror's feasibility checks (EXPERIMENT.md 9.8;
DRAFT stage, never scored) from the raw files of run_mf.sh. Prints one table per check and writes <resultsdir>/SUMMARY.txt.

Pass criteria (draft, 9.8, written before the runs):
  check 1 (vis): no wrong word in path a2 (READ fence, then the CPU) nor in a3 (READ on a third QP) in either direction (host
    node rain, host node sunny), over every valid run; each direction needs a valid run of each fixed size (4k, 256k, 2m),
    else it is open. a1 (the CPU at once) is reported: it says whether the run could have seen a late write at all. A run
    with an error key, a missing or inconsistent kv has no verdict and is listed.
  check 3 (store): WRITE p99 <= 10 ms in both arms (no other traffic; background bursts), READ p99 <= 100 ms, per direction,
    on the latest valid run; theta (READ bytes / READ p50) printed for EXPERIMENT.md 3 (train_restore_parts). p50, p99 and
    max are recomputed from the timing file with the rank rule of mirror_feas.cu and compared with the kv.
  check 4 (bar1): rain's BAR1 Free after all three processes registered (stage pd1, and pd2 when it ran) >= 64 MiB; whether
    the second PD's registration used BAR1 (Used at pd2 - Used at pd1, against the window bytes of one process).
  check 2 (COSTMAN): per node and metric the median of each arm (one, man-self, man-peer) over its valid runs (a reading
    needs >= 5 of 6), the difference against one, and the draft thresholds of EXPERIMENT.md 3 as a reading only (4 KiB
    +2.5 us; bandwidth ratio of man-peer 0.40-0.60); no verdict (9.8: the thresholds are set again before the
    pre-registration if they disagree).
"""
import glob
import os
import re
import sys

OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


def kv(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, errors="replace"):
        for m in re.finditer(r"(\w+)=(\"[^\"]*\"|\S+)", line):
            d[m.group(1)] = m.group(2).strip('"')
    return d


def num(d, k, default=-1.0):
    try:
        return float(d.get(k, default))
    except ValueError:
        return default


def rank(v, p):  # the rank rule of mirror_feas.cu pct(): v[(size_t)(p * (n - 1) + 0.5)]
    if not v:
        return None
    v = sorted(v)
    return v[int(p * (len(v) - 1) + 0.5)]


def median(v):
    v = sorted(v)
    n = len(v)
    return None if n == 0 else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0)


def runs(R, base, extra=()):
    """<base>, then <base>_run2, _run3, ..., then the extra prefixes (e.g. vis_one1, vis_one2): every folder that exists"""
    def bynum(prefix):
        ds = [d for d in glob.glob(os.path.join(R, prefix + "*")) if re.fullmatch(r"\d+", os.path.basename(d)[len(prefix):])]
        return sorted(ds, key=lambda d: int(os.path.basename(d)[len(prefix):]))
    out = [os.path.join(R, base)] + bynum(base + "_run")
    for e in extra:
        out += bynum(e)
    return [d for d in out if os.path.isdir(d)]


ERRKEYS = ("setup_error", "nic_error", "cuda_error", "nccl_error")


def errlabel(d):
    for k in ERRKEYS:
        if k in d:
            return "%s=%s" % (k, d[k])
    if d.get("watchdog") == "1":
        return "watchdog=1"
    return None


# ---------------------------------------------------------------- check 1
FIXED = ("4k", "256k", "2m")


def vis(R):
    folders = runs(R, "vis", ("vis_one",))
    rows = []
    for d in folders:
        for f in sorted(glob.glob(os.path.join(d, "vis_*_host.kv"))):
            cell = os.path.basename(f)[:-len("_host.kv")]
            m = re.fullmatch(r"vis_(4k|256k|2m|rand)_(rain|sunny)", cell)
            if not m:
                continue
            h, w = kv(f), kv(os.path.join(d, cell + "_writer.kv"))
            why = [x for x in (errlabel(h), errlabel(w) and "writer " + errlabel(w)) if x]
            if h.get("result") not in ("PASS", "FAIL", "INCOMPLETE"):
                why.append("host result=%s" % h.get("result", "none"))
            if w.get("result") != "WRITER_DONE":
                why.append("writer result=%s" % w.get("result", "none"))
            done = int(num(h, "iterations_done", 0))
            ns = [int(num(h, p + "_n", 0)) for p in ("a1", "a2", "a3")]
            if not why and sum(ns) != done:
                why.append("a1_n + a2_n + a3_n = %d != iterations_done %d" % (sum(ns), done))
            if not why and done == 0:
                why.append("no iteration")
            rows.append(dict(folder=os.path.basename(d), cell=cell, size=m.group(1), node=m.group(2), h=h, why=why))
    if not rows:
        return None
    say("== check 1 (vis): host MR visibility after the responder's completion (every run)")
    say("folder | cell | signal | iterations (budget stop) | a1 n bad stale/corrupt | a2 n bad | a3 n bad | edge a1/a2/a3 | "
        "after-fence bad | reach p50 us | QUERY_QP (polls/iter) | fence p50 us | result")
    for r in rows:
        h = r["h"]
        if r["why"]:
            say("%s | %s | no verdict: %s" % (r["folder"], r["cell"], "; ".join(r["why"])))
            continue
        g = lambda p, k: h.get("%s_%s" % (p, k), "?")
        say("%s | %s | %s | %s (%s) | %s %s %s/%s | %s %s | %s %s | %s/%s/%s | %s/%s/%s | %s | %s (%s) | %s | %s" % (
            r["folder"], r["cell"], h.get("signal", "?"), h.get("iterations_done"), h.get("budget_stop", "?"),
            g("a1", "n"), g("a1", "bad"), g("a1", "stale_words"), g("a1", "corrupt_words"), g("a2", "n"), g("a2", "bad"),
            g("a3", "n"), g("a3", "bad"), g("a1", "edge"), g("a2", "edge"), g("a3", "edge"), g("a1", "after_fence_bad"),
            g("a2", "after_fence_bad"), g("a3", "after_fence_bad"), h.get("reach_p50_us", "?"), h.get("query_qp_total", "?"),
            h.get("polls_per_iter_mean", "?"), h.get("fence_p50_us", "?"), h.get("result")))
        if int(num(h, "a1_after_fence_bad", 0)) or int(num(h, "a2_after_fence_bad", 0)) or int(num(h, "a3_after_fence_bad", 0)):
            say("  NOTE %s/%s: a word was still wrong after one more fence (not a late write: report)" % (r["folder"], r["cell"]))
    verdict = {}
    for node in ("rain", "sunny"):
        valid = [r for r in rows if r["node"] == node and not r["why"]]
        n = {p: sum(int(num(r["h"], p + "_n", 0)) for r in valid) for p in ("a1", "a2", "a3")}
        bad = {p: sum(int(num(r["h"], p + "_bad", 0)) for r in valid) for p in ("a1", "a2", "a3")}
        missing = [s for s in FIXED if not any(r["size"] == s for r in valid)]
        if bad["a2"] or bad["a3"]:
            v = "FAIL"
        elif missing or not valid:
            v = "open (no valid run of %s)" % ", ".join(missing or FIXED)
        else:
            v = "PASS"
        verdict[node] = v
        bound = lambda p: ("; 95%% upper bound of the per-iteration rate %.4f%%" % (300.0 / n[p])) if n[p] and not bad[p] else ""
        say("host node %s (written from %s): %s; valid runs %d; a2 bad %d of %d%s; a3 bad %d of %d%s; a1 bad %d of %d (%s)" % (
            node, "sunny" if node == "rain" else "rain", v, len(valid), bad["a2"], n["a2"], bound("a2"), bad["a3"], n["a3"],
            bound("a3"), bad["a1"], n["a1"], "the runs could see a late write" if bad["a1"] else
            "no late write seen even without a fence: the check cannot show that the fence is needed"))
    vs = list(verdict.values())
    concl = "PASS (both directions)" if all(v == "PASS" for v in vs) else "FAIL" if "FAIL" in vs else "open"
    say("check 1 conclusion: %s" % concl)
    say()
    return concl


# ---------------------------------------------------------------- check 3
def store(R):
    out = {}
    for d in runs(R, "store"):
        for f in sorted(glob.glob(os.path.join(d, "store_*_src.kv"))):
            cell = os.path.basename(f)[:-len("_src.kv")]
            m = re.fullmatch(r"store_(rain|sunny)", cell)
            if m:
                out.setdefault(m.group(1), []).append((d, cell, kv(f), kv(os.path.join(d, cell + "_host.kv"))))
    if not out:
        return None
    say("== check 3 (store): 30 MiB WRITE GPU -> host MR, 150 MiB READ of a host MR (latest valid run per direction)")
    say("direction | folder | WRITE none p50/p99/max ms | WRITE bg p50/p99/max ms (bg GiB/s) | READ p50/p99/max ms | theta "
        "GB/s (GiB/s) | data checks | timing file | verdict")
    res = {}
    for node in ("rain", "sunny"):
        label = "%s GPU -> %s host%s" % ("sunny" if node == "rain" else "rain", node,
                                         " (rank 3 kill layout: buddy rank 2 on rain, spare on sunny)" if node == "rain" else "")
        cand = out.get(node, [])
        valid, notes = [], []
        for d, cell, s, h in cand:
            e = errlabel(s) or (errlabel(h) and "host " + errlabel(h))
            if e or s.get("result") != "DONE" or h.get("result") != "HOST_DONE":
                notes.append("%s: no verdict (%s)" % (os.path.basename(d), e or "result %s/%s" % (s.get("result"), h.get("result"))))
            else:
                valid.append((d, cell, s, h))
        for x in notes:
            say("%s | %s" % (label, x))
        if not valid:
            res[node] = "open"
            say("%s | no valid run | open" % label)
            continue
        d, cell, s, h = valid[-1]
        vals, tnote = {"write_none": [], "write_bg": [], "read_none": []}, "missing"
        tf = os.path.join(d, cell + "_timing.tsv")
        if os.path.exists(tf):
            for line in list(open(tf))[1:]:
                p = line.split()
                if len(p) == 4:
                    vals.setdefault("%s_%s" % (p[0], p[1]), []).append(float(p[3]))
            diffs = []
            for key, kk in (("write_none", "write_none"), ("write_bg", "write_bg"), ("read_none", "read")):
                for q, name in ((0.5, "p50"), (0.99, "p99"), (1.0, "max")):
                    a, b = rank(vals[key], q), num(s, "%s_%s_ms" % (kk, name))
                    if a is None or abs(a - b) > 0.0015:
                        diffs.append("%s_%s tsv %s kv %s" % (kk, name, a, b))
            tnote = "recomputed, same as kv" if not diffs else "DIFFERS: " + "; ".join(diffs)
        w99 = max(num(s, "write_none_p99_ms"), num(s, "write_bg_p99_ms"))
        r99 = num(s, "read_p99_ms")
        ok = 0 <= w99 <= 10.0 and 0 <= r99 <= 100.0
        data = "read %s, store %s bad words" % (s.get("read_bad_words", "?"), h.get("store_check_bad_words", "?"))
        if s.get("read_bad_words") != "0" or h.get("store_check_bad_words") != "0":
            data += " (NOT 0: report)"
        res[node] = "PASS" if ok else "FAIL"
        say("%s | %s | %s/%s/%s | %s/%s/%s (%s) | %s/%s/%s | %s (%s) | %s | %s | %s (rule: WRITE p99 %.3f <= 10 ms, READ p99 %.3f <= 100 ms)" % (
            label, os.path.basename(d), s.get("write_none_p50_ms"), s.get("write_none_p99_ms"), s.get("write_none_max_ms"),
            s.get("write_bg_p50_ms"), s.get("write_bg_p99_ms"), s.get("write_bg_max_ms"), s.get("bg_gibps"),
            s.get("read_p50_ms"), s.get("read_p99_ms"), s.get("read_max_ms"), s.get("theta_gbps"), s.get("theta_gibps"), data,
            tnote, res[node], w99, r99))
        say("  n: WRITE none %s, bg %s, READ %s; earlier valid runs of this direction: %d" % (
            s.get("write_none_n"), s.get("write_bg_n"), s.get("read_n"), len(valid) - 1))
    vs = list(res.values())
    concl = "PASS (both directions)" if all(v == "PASS" for v in vs) and len(vs) == 2 else "FAIL" if "FAIL" in vs else "open"
    say("check 3 conclusion: %s; theta for train_restore_parts: the rank 3 kill layout's READ (host rain), %s GB/s" % (
        concl, next((s.get("theta_gbps") for d, c, s, h in out.get("rain", [])[::-1] if s.get("result") == "DONE"), "none")))
    say()
    return concl


# ---------------------------------------------------------------- check 4
def bar1(R):
    folders = [d for d in runs(R, "bar1") if os.path.exists(os.path.join(d, "bar1_rain_bar1.txt"))]
    if not folders:
        return None
    say("== check 4 (bar1): rain BAR1 with three processes (6 + 24 MiB windows each; p0 also in a second PD)")
    concl = "open"
    for d in folders:
        st = {}
        for line in open(os.path.join(d, "bar1_rain_bar1.txt")):
            x = kv_line(line)
            if "stage" in x:
                st[x["stage"]] = x
        meta = kv(os.path.join(d, "bar1_rain_meta.txt"))
        ks = {p: kv(os.path.join(d, "bar1_rain_%s.kv" % p)) for p in ("p0", "p2", "sp")}
        errs = ["%s %s" % (p, errlabel(k)) for p, k in ks.items() if errlabel(k)] + \
               ["%s kv missing" % p for p, k in ks.items() if not k]
        regs = {p: {k: v for k, v in x.items() if k.startswith("reg_")} for p, x in ks.items()}
        failed = ["%s %s errno %s" % (p, k[:-3], r.get(k[:-3] + "_errno")) for p, r in regs.items() for k, v in r.items()
                  if k.endswith("_ok") and v != "1"]
        win = sum(int(x) for x in ks["p0"].get("windows_mib", "6,24").split(","))
        f = lambda s, k: int(st[s][k]) if s in st and st[s].get(k, "").isdigit() else None
        say("folder %s: stages %s; note %s; gpu apps before (rain/sunny) %s" % (
            os.path.basename(d), " ".join("%s used %s free %s" % (s, st[s].get("used_mib"), st[s].get("free_mib"))
                                          for s in ("before", "ctx", "pd1", "pd2", "after") if s in st),
            meta.get("note", "-"), meta.get("gpu_apps_before", "?")))
        if errs:
            say("  no verdict: %s" % "; ".join(errs))
            continue
        if failed:
            say("  registrations failed: %s (a reading)" % "; ".join(failed))
        free1, free2 = f("pd1", "free_mib"), f("pd2", "free_mib")
        if free1 is None:
            say("  no pd1 reading: open")
            continue
        ok = free1 >= 64 and (free2 is None or free2 >= 64) and not failed
        say("  BAR1 Free after the three registrations: %d MiB%s -> %s (rule: >= 64 MiB)" % (
            free1, "" if free2 is None else ", after the second PD %d MiB" % free2, "PASS" if ok else "FAIL"))
        u0, uc, u1, u2 = f("before", "used_mib"), f("ctx", "used_mib"), f("pd1", "used_mib"), f("pd2", "used_mib")
        if uc is not None and u0 is not None and u1 is not None:
            say("  BAR1 Used: three CUDA contexts and allocations +%d MiB, three processes' registrations +%d MiB (windows %d MiB "
                "each)" % (uc - u0, u1 - uc, win))
        if u2 is None:
            say("  second PD: not measured (%s)" % meta.get("note", "no pd2 stage"))
        else:
            dlt = u2 - u1
            ans = "yes" if dlt >= win / 2 else "no" if dlt <= 2 else "partly (unclear)"
            say("  second PD registration of p0's %d MiB used %d MiB of BAR1: %s (other GPU users can move BAR1 between "
                "readings; see the gpu snapshots)" % (win, dlt, ans))
        concl = "PASS" if ok else "FAIL"
    say("check 4 conclusion (the latest folder): %s" % concl)
    say()
    return concl


def kv_line(line):
    return {m.group(1): m.group(2) for m in re.finditer(r"(\w+)=(\S+)", line)}


# ---------------------------------------------------------------- check 2
CM = {"lat4k": (3000, 4096, None), "lat256k": (3000, 262144, None), "lat2m": (3000, 2097152, None),
      "bw256k": (12, 262144, 8), "bw2m": (24, 2097152, 8)}
ARMS = ("one", "man-self", "man-peer")
MANKEY = {"one": "off", "man-self": "self", "man-peer": "peer"}


def costman(R):
    bases = sorted(set(re.sub(r"_run\d+$", "", os.path.basename(d)) for d in glob.glob(os.path.join(R, "costman_*"))))
    if not bases:
        return None
    say("== check 2 (COSTMAN): manual mirror cost, arm medians over valid runs (no verdict)")
    for base in bases:
        m = re.fullmatch(r"costman_(rain|sunny)_(lat4k|lat256k|lat2m|bw256k|bw2m)", base)
        if not m:
            continue
        node, met = m.groups()
        it, by, k = CM[met]
        for d in runs(R, base):
            vals, invalid = {a: [] for a in ARMS}, []
            for mf in sorted(glob.glob(os.path.join(d, "cm_*_meta.txt"))):
                stem = os.path.basename(mf)[:-len("_meta.txt")]
                arm = stem.split("_")[2]
                k0, k1 = kv(os.path.join(d, stem + "_r0.kv")), kv(os.path.join(d, stem + "_r1.kv"))
                why = []
                for name, x in (("r0", k0), ("r1", k1)):
                    if not x:
                        why.append(name + " kv missing")
                    elif x.get("exit") != "0" or errlabel(x):
                        why.append("%s exit=%s %s" % (name, x.get("exit", "none"), errlabel(x) or ""))
                if k0 and (k0.get("iters") != str(it) or k0.get("bytes") != str(by) or (k and k0.get("burst_K") != str(k))):
                    why.append("configuration iters=%s bytes=%s K=%s" % (k0.get("iters"), k0.get("bytes"), k0.get("burst_K")))
                if k0 and k0.get("man_mirror", "off") != MANKEY.get(arm):
                    why.append("man_mirror=%s (want %s)" % (k0.get("man_mirror", "absent"), MANKEY.get(arm)))
                if k0 and k0.get("tx_done") != str(it):
                    why.append("tx_done=%s" % k0.get("tx_done"))
                if k0 and "lat_p50_us" not in k0:
                    why.append("no lat_p50_us")
                if why or arm not in vals:
                    invalid.append("%s: %s" % (stem, "; ".join(why) or "unknown arm"))
                    continue
                p50 = float(k0["lat_p50_us"])
                vals[arm].append(p50 if k is None else k * by / (p50 * 1e-6) / 1e9)
            unit = "us" if k is None else "GB/s"
            say("%s (receiving node %s, metric %s, %s):" % (os.path.basename(d), node, met, unit))
            for x in invalid:
                say("  invalid (not counted): " + x)
            med = {a: median(v) if len(v) >= 5 else None for a, v in vals.items()}
            for a in ARMS:
                v = vals[a]
                say("  %s: n %d, median %s, range %s-%s" % (a, len(v), "%.3f" % med[a] if med[a] is not None else "-",
                                                             "%.3f" % min(v) if v else "-", "%.3f" % max(v) if v else "-"))
            if med["one"] is None:
                say("  reading: incomplete (fewer than 5 valid runs of the arm one)")
                continue
            for a in ("man-self", "man-peer"):
                if med[a] is None:
                    say("  %s: incomplete (fewer than 5 valid runs)" % a)
                elif k is None:
                    dl = med[a] - med["one"]
                    draft = "; draft +2.5 us: %s" % ("within" if dl <= 2.5 else "OUTSIDE") if met == "lat4k" else ""
                    say("  %s - one: %+.3f us (%+.1f%%)%s" % (a, dl, 100.0 * dl / med["one"], draft))
                else:
                    ratio = med[a] / med["one"]
                    draft = "; draft 0.40-0.60: %s" % ("within" if 0.40 <= ratio <= 0.60 else "OUTSIDE") if a == "man-peer" else ""
                    say("  %s / one: %.3f%s" % (a, ratio, draft))
    say()
    return "reported"


def summarize(R):
    del OUT[:]
    got = {"check1": vis(R), "check3": store(R), "check4": bar1(R), "check2": costman(R)}
    if all(v is None for v in got.values()):
        say("no feasibility folder found in %s" % R)
    with open(os.path.join(R, "SUMMARY.txt"), "w") as f:
        f.write("\n".join(OUT) + "\n")
    return got


# ---------------------------------------------------------------- CPU-only self-test with synthetic files
def selftest(S):
    import random
    rnd = random.Random(7)

    def w(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def visrun(d, size, node, a2bad=0, err=None):
        cell = "vis_%s_%s" % (size, node)
        if err:
            w(os.path.join(d, cell + "_host.kv"), "mode=vis role=host\nnic_error=\"%s\" errno=0 result=ERROR exit=3\n" % err)
        else:
            w(os.path.join(d, cell + "_host.kv"), "mode=vis role=host size=%s iters=9999 signal=msn\n"
              "a1_n=3333 a1_bad=0 a1_stale_words=0 a1_corrupt_words=0 a1_edge=10 a1_after_fence_bad=0\n"
              "a2_n=3333 a2_bad=%d a2_stale_words=%d a2_corrupt_words=0 a2_edge=12 a2_after_fence_bad=0\n"
              "a3_n=3333 a3_bad=0 a3_stale_words=0 a3_corrupt_words=0 a3_edge=9 a3_after_fence_bad=0\n"
              "reach_p50_us=12.0 query_qp_total=14000 polls_per_iter_mean=1.40 fence_p50_us=6.1\n"
              "iterations_done=9999 budget_stop=0 run_s=8.1 result=%s exit=%d\n" % (size, a2bad, 7 * a2bad,
                                                                                    "FAIL" if a2bad else "PASS", 1 if a2bad else 0))
        w(os.path.join(d, cell + "_writer.kv"), "iterations=9999 result=WRITER_DONE exit=0\n")
        w(os.path.join(d, cell + "_meta.txt"), "cell=%s kind=vis left=0\n" % cell)

    def storerun(d, node, wmax):
        cell = "store_" + node
        wn = [rnd.uniform(3.0, 5.0) for _ in range(100)]
        wb = [rnd.uniform(4.0, wmax) for _ in range(100)]
        rd = [rnd.uniform(14.0, 20.0) for _ in range(100)]
        rows = ["phase\tarm\trep\tms"] + ["write\tnone\t%d\t%.4f" % (i, x) for i, x in enumerate(wn)] + \
               ["write\tbg\t%d\t%.4f" % (i, x) for i, x in enumerate(wb)] + ["read\tnone\t%d\t%.4f" % (i, x) for i, x in enumerate(rd)]
        w(os.path.join(d, cell + "_timing.tsv"), "\n".join(rows) + "\n")
        r4 = lambda v: [float("%.4f" % x) for x in v]
        wn, wb, rd = r4(wn), r4(wb), r4(rd)
        p = lambda v, q: rank(v, q)
        w(os.path.join(d, cell + "_src.kv"), "mode=store role=src\n"
          "write_none_n=100 write_none_p50_ms=%.3f write_none_p99_ms=%.3f write_none_max_ms=%.3f\n"
          "write_bg_n=100 write_bg_p50_ms=%.3f write_bg_p99_ms=%.3f write_bg_max_ms=%.3f\nbg_rounds=900 bg_gibps=9.1\n"
          "read_n=100 read_p50_ms=%.3f read_p99_ms=%.3f read_max_ms=%.3f theta_gibps=8.5 theta_gbps=9.1 read_bad_words=0\n"
          "run_s=9.0 result=DONE exit=0\n" % (p(wn, .5), p(wn, .99), p(wn, 1), p(wb, .5), p(wb, .99), p(wb, 1), p(rd, .5),
                                               p(rd, .99), p(rd, 1)))
        w(os.path.join(d, cell + "_host.kv"), "store_check_bad_words=0\nrun_s=9.0 result=HOST_DONE exit=0\n")
        w(os.path.join(d, cell + "_meta.txt"), "cell=%s kind=store left=0\n" % cell)

    os.makedirs(S, exist_ok=True)
    if glob.glob(os.path.join(S, "*")):
        sys.exit("selftest: %s must be empty" % S)
    # scenario A: everything passes
    A = os.path.join(S, "A")
    for size in FIXED:
        for node in ("rain", "sunny"):
            visrun(os.path.join(A, "vis"), size, node)
    visrun(os.path.join(A, "vis_run2"), "2m", "rain", err="QUERY_QP cap of the run reached")
    storerun(os.path.join(A, "store"), "rain", 8.0)
    storerun(os.path.join(A, "store"), "sunny", 9.0)
    b = os.path.join(A, "bar1")
    w(os.path.join(b, "bar1_rain_bar1.txt"), "stage=before total_mib=256 used_mib=5 free_mib=251 t_mono=1.0\n"
      "stage=ctx total_mib=256 used_mib=11 free_mib=245 t_mono=2.0\nstage=pd1 total_mib=256 used_mib=101 free_mib=155 t_mono=3.0\n"
      "stage=pd2 total_mib=256 used_mib=131 free_mib=125 t_mono=4.0\nstage=after total_mib=256 used_mib=5 free_mib=251 t_mono=5.0\n")
    for p in ("p0", "p2", "sp"):
        w(os.path.join(b, "bar1_rain_%s.kv" % p), "mode=bar1 tag=%s pd2=%d windows_mib=6,24\nreg_pd1_6mib_ok=1 reg_pd1_6mib_errno=0\n"
          "reg_pd1_24mib_ok=1 reg_pd1_24mib_errno=0\nregistrations_failed=0 result=DONE exit=0\n" % (p, p == "p0"))
    w(os.path.join(b, "bar1_rain_meta.txt"), "cell=bar1_rain kind=bar1 left=0 gpu_apps_before=0/0\n")
    c = os.path.join(A, "costman_rain_lat4k")
    for k in range(1, 7):
        for a, base in (("one", 11.3), ("man-self", 12.6), ("man-peer", 13.1)):
            stem = "cm_lat4k_%s_rain_k%d" % (a, k)
            w(os.path.join(c, stem + "_meta.txt"), "cell=%s kind=cm left=0\n" % stem)
            w(os.path.join(c, stem + "_r0.kv"), "rank=0 iters=3000 bytes=4096\n%s\ntx_done=3000\nlat_p50_us=%.3f\nexit=0\n" % (
                "" if a == "one" else "man_mirror=%s man_ctx=1" % MANKEY[a], base + rnd.uniform(-0.05, 0.05)))
            w(os.path.join(c, stem + "_r1.kv"), "rank=1\nexit=0\n")
    got = summarize(A)
    assert got["check1"].startswith("PASS"), got
    assert got["check3"].startswith("PASS"), got
    assert got["check4"] == "PASS", got
    text = "\n".join(OUT)
    assert "no verdict: nic_error=QUERY_QP cap of the run reached" in text, "error run not listed"
    assert "recomputed, same as kv" in text, "timing recomputation"
    assert "used 30 MiB of BAR1: yes" in text, "second-PD reading"
    assert re.search(r"man-peer - one: \+1\.\d+ us .*draft \+2\.5 us: within", text), "costman reading"
    # scenario B: a wrong word in a2, a WRITE p99 over 10 ms, BAR1 below 64 MiB, one sizeless direction
    B = os.path.join(S, "B")
    for size in FIXED:
        visrun(os.path.join(B, "vis"), size, "rain", a2bad=1 if size == "256k" else 0)
    visrun(os.path.join(B, "vis"), "4k", "sunny")
    storerun(os.path.join(B, "store"), "rain", 14.0)
    b = os.path.join(B, "bar1")
    w(os.path.join(b, "bar1_rain_bar1.txt"), "stage=before total_mib=256 used_mib=100 free_mib=156 t_mono=1.0\n"
      "stage=ctx total_mib=256 used_mib=106 free_mib=150 t_mono=2.0\nstage=pd1 total_mib=256 used_mib=196 free_mib=60 t_mono=3.0\n"
      "stage=after total_mib=256 used_mib=100 free_mib=156 t_mono=5.0\n")
    for p in ("p0", "p2", "sp"):
        w(os.path.join(b, "bar1_rain_%s.kv" % p), "mode=bar1 tag=%s windows_mib=6,24\nreg_pd1_6mib_ok=1\nreg_pd1_24mib_ok=1\n"
          "result=DONE exit=0\n" % p)
    w(os.path.join(b, "bar1_rain_meta.txt"), "cell=bar1_rain kind=bar1 left=0 note=pd2_skipped_free=60\n")
    got = summarize(B)
    assert got["check1"] == "FAIL", got
    assert got["check3"] == "FAIL", got
    assert got["check4"] == "FAIL", got
    text = "\n".join(OUT)
    assert "host node sunny (written from rain): open (no valid run of 256k, 2m)" in text, "open direction"
    assert "second PD: not measured (pd2_skipped_free=60)" in text, "skipped second PD"
    print("selftest: ok (scenario A passes, scenario B fails as built; files under %s)" % S)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
    elif len(sys.argv) == 2:
        summarize(sys.argv[1])
    else:
        sys.exit(__doc__)
