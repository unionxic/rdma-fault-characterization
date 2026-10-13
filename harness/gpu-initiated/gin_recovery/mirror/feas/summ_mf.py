#!/usr/bin/env python3
"""summ_mf.py <resultsdir> | --selftest <scratch dir> - readings of gin-mirror's feasibility checks (EXPERIMENT.md 9.8;
DRAFT stage, never scored) from the raw files of run_mf.sh. Prints one table per check and writes <resultsdir>/SUMMARY.txt.

Pass criteria (draft, 9.8, written before the runs):
  check 1 (vis): no wrong word in path a2 (READ fence, then the CPU) nor in a3 (READ on a third QP) in either direction (host
    node rain, host node sunny), over every valid run; each direction needs a valid run of each fixed size (4k, 256k, 2m),
    else it is open. a1 (the CPU at once) is reported: it says whether the run could have seen a late write at all. A run
    with an error key, a missing or inconsistent kv has no verdict and is listed.
  check 3 (store): per direction, on the latest valid run: D2H p99 <= 4 ms (the image into the pinned staging buffer, inside
    the input pause in the design), WRITE p99 <= 10 ms in both arms (no other traffic; background bursts), READ p99 <= 100 ms
    at every size; the intercept a and theta of the fit a + bytes / theta over the per-size READ p50 are printed for
    EXPERIMENT.md 3 (seg_restore_slope, train_restore_parts). p50, p99, max and the fit are recomputed from the timing file
    with the rank rule of mirror_feas.cu and compared with the kv.
  check 4 (bar1): rain's BAR1 Free after the three processes registered their windows (stage pd1, and pd2 when it ran) >= 64
    MiB; whether the second PD's registration used BAR1 (Used at pd2 - Used at pd1, against one process's window bytes); and,
    recorded, whether every process could pin its host memory (pool, store, D2H staging, FETCH buffer) under its memlock
    limit, with the BAR1 and MemAvailable change of that stage.
  check 2 (COSTMAN): per node and metric the median of each arm (one, man-self, man-peer) over its valid runs (a reading
    needs >= 5 of 6) and the difference or ratio against one. No verdict: only the bandwidth ratio of man-peer is read against
    the draft 0.40-0.60; the 4 KiB latency threshold is measured by the pilot on the real device path (EXPERIMENT.md 9.8).
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
def fit(points):
    """least squares t = a + b x over (x bytes, t ms); returns (a ms, theta GB/s) or (None, None)"""
    n = len(points)
    sx, sy = sum(x for x, _ in points), sum(y for _, y in points)
    sxx, sxy = sum(x * x for x, _ in points), sum(x * y for x, y in points)
    den = n * sxx - sx * sx
    if n < 2 or den <= 0:
        return None, None
    b = (n * sxy - sx * sy) / den
    return (sy - b * sx) / n, (1e-6 / b if b > 0 else None)


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
    say("== check 3 (store): D2H 30 MiB, WRITE 30 MiB host -> host MR, READ of a host MR at several sizes (latest valid run "
        "per direction)")
    res, theta_kill = {}, None
    MiB = 1 << 20
    for node in ("rain", "sunny"):
        label = "%s uploads and reads %s%s" % ("sunny" if node == "rain" else "rain", node,
                                              " (rank 3 kill layout: buddy rank 2 on rain, spare on sunny)" if node == "rain" else "")
        valid = []
        for d, cell, sk, hk in out.get(node, []):
            e = errlabel(sk) or (errlabel(hk) and "host " + errlabel(hk))
            if e or sk.get("result") != "DONE" or hk.get("result") != "HOST_DONE":
                say("%s | %s: no verdict (%s)" % (label, os.path.basename(d), e or "result %s/%s" % (sk.get("result"), hk.get("result"))))
            else:
                valid.append((d, cell, sk, hk))
        if not valid:
            res[node] = "open"
            say("%s | no valid run | open" % label)
            continue
        d, cell, sk, hk = valid[-1]
        sizes = [int(x) for x in sk.get("read_sizes_mib", "").split(",") if x.isdigit()]
        ser = {"d2h": [], "write_none": [], "write_bg": []}
        rd = {z: [] for z in sizes}
        notes, tf = [], os.path.join(d, cell + "_timing.tsv")
        if os.path.exists(tf):
            for line in list(open(tf))[1:]:
                p = line.split()
                if len(p) != 5:
                    continue
                if p[0] == "d2h":
                    ser["d2h"].append(float(p[4]))
                elif p[0] == "write":
                    ser["write_" + p[1]].append(float(p[4]))
                elif p[0] == "read" and int(p[2]) in rd:
                    rd[int(p[2])].append(float(p[4]))
            checks = [(k, ser[k]) for k in ("d2h", "write_none", "write_bg")] + [("read_%dm" % z, rd[z]) for z in sizes]
            for k, v in checks:
                for q, name in ((0.5, "p50"), (0.99, "p99"), (1.0, "max")):
                    a_, b_ = rank(v, q), num(sk, "%s_%s_ms" % (k, name))
                    if a_ is None or abs(a_ - b_) > 0.0015:
                        notes.append("%s_%s tsv %s kv %s" % (k, name, a_, b_))
            a_ms, th = fit([(z * MiB, rank(rd[z], 0.5)) for z in sizes if rd[z]])
            if a_ms is None or abs(a_ms - num(sk, "read_fit_a_ms")) > 0.002 or th is None or \
                    abs(th - num(sk, "read_fit_theta_gbps")) > 0.006 * max(1.0, th):
                notes.append("fit tsv a %s theta %s, kv a %s theta %s" % (a_ms, th, sk.get("read_fit_a_ms"), sk.get("read_fit_theta_gbps")))
            tnote = "recomputed, same as kv" if not notes else "DIFFERS: " + "; ".join(notes)
        else:
            a_ms, th, tnote = num(sk, "read_fit_a_ms"), num(sk, "read_fit_theta_gbps"), "timing file missing (kv values)"
        d99, w99, r99 = num(sk, "d2h_p99_ms"), max(num(sk, "write_none_p99_ms"), num(sk, "write_bg_p99_ms")), num(sk, "read_p99_worst_ms")
        ok = 0 <= d99 <= 4.0 and 0 <= w99 <= 10.0 and 0 <= r99 <= 100.0
        res[node] = "PASS" if ok else "FAIL"
        bad = [k for k in ("d2h_bad_words", "read_bad_words") if sk.get(k) != "0"] + \
              (["store_check_bad_words"] if hk.get("store_check_bad_words") != "0" else [])
        say("%s | folder %s | %s (rule: D2H p99 %.3f <= 4 ms, WRITE p99 %.3f <= 10 ms, READ p99 worst %.3f <= 100 ms)" % (
            label, os.path.basename(d), res[node], d99, w99, r99))
        say("  D2H p50/p99/max %s/%s/%s ms (%s GB/s at p50); WRITE none %s/%s/%s ms, with bursts %s/%s/%s ms (bursts %s GiB/s)" % (
            sk.get("d2h_p50_ms"), sk.get("d2h_p99_ms"), sk.get("d2h_max_ms"), sk.get("d2h_gbps_at_p50"), sk.get("write_none_p50_ms"),
            sk.get("write_none_p99_ms"), sk.get("write_none_max_ms"), sk.get("write_bg_p50_ms"), sk.get("write_bg_p99_ms"),
            sk.get("write_bg_max_ms"), sk.get("bg_gibps")))
        say("  READ p50/p99 ms by size: %s" % ", ".join("%d MiB %s/%s" % (z, sk.get("read_%dm_p50_ms" % z), sk.get("read_%dm_p99_ms" % z))
                                                        for z in sizes))
        say("  fit over the per-size p50: a %.3f ms, theta %.2f GB/s; n D2H %s, WRITE %s + %s, READ per size %s; timing file: %s; "
            "data checks: %s; earlier valid runs: %d" % (a_ms if a_ms is not None else -1, th if th is not None else -1,
                                                         sk.get("d2h_n"), sk.get("write_none_n"), sk.get("write_bg_n"),
                                                         sk.get("read_%dm_n" % sizes[-1]) if sizes else "?", tnote,
                                                         "all 0" if not bad else "NOT 0: " + ", ".join(bad), len(valid) - 1))
        if node == "rain":
            theta_kill = (a_ms, th)
    vs = list(res.values())
    concl = "PASS (both directions)" if all(v == "PASS" for v in vs) and len(vs) == 2 else "FAIL" if "FAIL" in vs else "open"
    say("check 3 conclusion: %s; for seg_restore_slope and train_restore_parts (the rank 3 kill layout, host rain): %s" % (
        concl, "a %.3f ms, theta %.2f GB/s" % theta_kill if theta_kill and None not in theta_kill else "none"))
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
                  if k.endswith("_ok") and v != "1" and not k.startswith("reg_host_")]
        win = sum(int(x) for x in ks["p0"].get("windows_mib", "6,24").split(","))
        f = lambda s, k: int(st[s][k]) if s in st and st[s].get(k, "").isdigit() else None
        say("folder %s: stages %s; note %s; gpu apps before (rain/sunny) %s" % (
            os.path.basename(d), " ".join("%s used %s free %s" % (s, st[s].get("used_mib"), st[s].get("free_mib"))
                                          for s in ("before", "ctx", "pd1", "host", "pd2", "after") if s in st),
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
        uh, mh, m1 = f("host", "used_mib"), f("host", "mem_avail_mib"), f("pd1", "mem_avail_mib")
        hosts = {p: (k.get("host_mib"), k.get("reg_host_%smib_ok" % k.get("host_mib")), k.get("vm_pin_kib"), k.get("memlock_kib"))
                 for p, k in ks.items()}
        pinned = all(h[1] == "1" for h in hosts.values() if h[0] not in (None, "0"))
        say("  pinned host memory (pool, store, D2H staging, FETCH buffer): %s; %s; BAR1 Used change %s MiB, MemAvailable change "
            "%s MiB" % ("fits" if pinned and "host" in st else "does NOT fit" if "host" in st else "not measured",
                        ", ".join("%s %s MiB ok=%s VmPin %s KiB memlock %s KiB" % ((p,) + hosts[p]) for p in ("p0", "p2", "sp")),
                        "?" if uh is None or u1 is None else uh - u1, "?" if mh is None or m1 is None else mh - m1))
        if u2 is None:
            say("  second PD: not measured (%s)" % meta.get("note", "no pd2 stage"))
        else:
            dlt = u2 - u1
            ans = "yes" if dlt >= win / 2 else "no" if dlt <= 2 else "partly (unclear)"
            say("  second PD registration of p0's %d MiB used %d MiB of BAR1: %s (other GPU users can move BAR1 between "
                "readings; see the gpu snapshots)" % (win, dlt, ans))
        concl = "PASS" if ok else "FAIL"
    say("check 4 conclusion (the latest folder; BAR1 rule only, the pinned host memory is a recorded reading): %s" % concl)
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
                elif k is None:  # 9.8: the 4 KiB threshold is the pilot's (real device path); latency is reported only
                    dl = med[a] - med["one"]
                    say("  %s - one: %+.3f us (%+.1f%%)" % (a, dl, 100.0 * dl / med["one"]))
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
        cell, sizes, MiB = "store_" + node, (4, 8, 16, 32, 64, 128, 150), 1 << 20
        r4 = lambda v: [float("%.4f" % x) for x in v]
        dd = r4([rnd.uniform(2.6, 3.2) for _ in range(100)])
        wn = r4([rnd.uniform(3.0, 5.0) for _ in range(100)])
        wb = r4([rnd.uniform(4.0, wmax) for _ in range(100)])
        rd = {z: r4([0.05 + z * MiB / 10e9 * 1e3 * rnd.uniform(0.99, 1.04) for _ in range(100)]) for z in sizes}  # 10 GB/s
        rows = ["phase\tarm\tmib\trep\tms"] + ["d2h\tnone\t30\t%d\t%.4f" % (i, x) for i, x in enumerate(dd)] + \
               ["write\tnone\t30\t%d\t%.4f" % (i, x) for i, x in enumerate(wn)] + \
               ["write\tbg\t30\t%d\t%.4f" % (i, x) for i, x in enumerate(wb)] + \
               ["read\tnone\t%d\t%d\t%.4f" % (z, i, x) for z in sizes for i, x in enumerate(rd[z])]
        w(os.path.join(d, cell + "_timing.tsv"), "\n".join(rows) + "\n")
        p3 = lambda v: "%.3f/%.3f/%.3f" % (rank(v, .5), rank(v, .99), rank(v, 1))
        line = lambda k, v: "%s_n=%d %s_p50_ms=%s %s_p99_ms=%s %s_max_ms=%s" % ((k, len(v)) + sum(
            ((k, x) for x in p3(v).split("/")), ()))
        a_ms, th = fit([(z * MiB, rank(rd[z], .5)) for z in sizes])
        w(os.path.join(d, cell + "_src.kv"), "mode=store role=src reps=100 read_sizes_mib=%s\n%s d2h_gbps_at_p50=11.0 d2h_bad_words=0\n%s\n%s\n"
          "bg_rounds=900 bg_gibps=9.1\n%s\nread_fit_points=7 read_fit_a_ms=%.3f read_fit_theta_gbps=%.2f read_p99_worst_ms=%.3f "
          "read_bad_words=0\nrun_s=9.0 result=DONE exit=0\n" % (
              ",".join(map(str, sizes)), line("d2h", dd), line("write_none", wn), line("write_bg", wb),
              "\n".join(line("read_%dm" % z, rd[z]) for z in sizes), a_ms, th, max(rank(rd[z], .99) for z in sizes)))
        w(os.path.join(d, cell + "_host.kv"), "store_check_bad_words=0\nrun_s=9.0 result=HOST_DONE exit=0\n")
        w(os.path.join(d, cell + "_meta.txt"), "cell=%s kind=store left=0\n" % cell)

    def bar1run(d, used, host_fail=None, pd2=True):
        stages = ["before", "ctx", "pd1", "host"] + (["pd2"] if pd2 else []) + ["after"]
        w(os.path.join(d, "bar1_rain_bar1.txt"), "".join("stage=%s total_mib=256 used_mib=%d free_mib=%d mem_avail_mib=%d t_mono=%d\n" % (
            s_, used[s_], 256 - used[s_], 60000 - (2706 if s_ in ("host", "pd2") else 0), i) for i, s_ in enumerate(stages)))
        for p_, mib in (("p0", 812), ("p2", 812), ("sp", 1082)):
            ok = 0 if p_ == host_fail else 1
            w(os.path.join(d, "bar1_rain_%s.kv" % p_), "memlock_kib=unlimited hard_bound_s=300\nmode=bar1 tag=%s pd2=%d windows_mib=6,24 "
              "host_mib=%d\nreg_pd1_6mib_ok=1 reg_pd1_6mib_errno=0\nreg_pd1_24mib_ok=1 reg_pd1_24mib_errno=0\nreg_host_%dmib_ok=%d "
              "reg_host_%dmib_errno=%d vm_pin_kib=%d\nregistrations_failed=%d result=%s exit=%d\n" % (
                  p_, p_ == "p0", mib, mib, ok, mib, 0 if ok else 12, mib * 1024 if ok else 0, 1 - ok, "DONE" if ok else "REG_FAIL",
                  0 if ok else 8))
        w(os.path.join(d, "bar1_rain_meta.txt"), "cell=bar1_rain kind=bar1 left=0 gpu_apps_before=0/0%s\n" % (
            "" if pd2 else " note=pd2_skipped_free=60"))

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
    bar1run(os.path.join(A, "bar1"), {"before": 5, "ctx": 11, "pd1": 101, "host": 101, "pd2": 131, "after": 5})
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
    assert re.search(r"man-peer - one: \+1\.\d+ us \(\+1\d\.\d%\)", text), "costman reading"
    assert re.search(r"a 0\.0\d\d ms, theta (9\.[5-9]|10\.[0-4])\d GB/s", text), "READ fit"
    assert "pinned host memory (pool, store, D2H staging, FETCH buffer): fits" in text, "pinned host memory"
    # scenario B: a wrong word in a2, a WRITE p99 over 10 ms, BAR1 below 64 MiB, one sizeless direction
    B = os.path.join(S, "B")
    for size in FIXED:
        visrun(os.path.join(B, "vis"), size, "rain", a2bad=1 if size == "256k" else 0)
    visrun(os.path.join(B, "vis"), "4k", "sunny")
    storerun(os.path.join(B, "store"), "rain", 14.0)
    bar1run(os.path.join(B, "bar1"), {"before": 100, "ctx": 106, "pd1": 196, "host": 196, "after": 100}, host_fail="sp", pd2=False)
    got = summarize(B)
    assert got["check1"] == "FAIL", got
    assert got["check3"] == "FAIL", got
    assert got["check4"] == "FAIL", got
    text = "\n".join(OUT)
    assert "host node sunny (written from rain): open (no valid run of 256k, 2m)" in text, "open direction"
    assert "second PD: not measured (pd2_skipped_free=60)" in text, "skipped second PD"
    assert "does NOT fit" in text and "sp 1082 MiB ok=0" in text, "a failed host pinning"
    print("selftest: ok (scenario A passes, scenario B fails as built; files under %s)" % S)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
    elif len(sys.argv) == 2:
        summarize(sys.argv[1])
    else:
        sys.exit(__doc__)
