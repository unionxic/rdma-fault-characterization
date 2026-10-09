#!/usr/bin/env python3
"""Judge the 41 predictions of gpu-detect from the independent recount (app_rows.csv, reg_rows.csv).
Each check restates the acceptance formula of predictions.csv over this recount's own columns; text-only conditions
are checked separately where the text says more than the formula."""
import csv, math, statistics, sys

A = list(csv.DictReader(open("app_rows.csv")))
G = list(csv.DictReader(open("reg_rows.csv")))


def cell(rows, key):
    return [r for r in rows if r["key"] == key and r.get("valid", "1") == "1"]


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def nonempty(x):
    return x not in ("", None)


out = []


def judge(pid, key, rows, pred, need, extra=""):
    n = len(rows)
    ok = [r["id"] for r in rows if pred(r)]
    bad = [r["id"] for r in rows if not pred(r)]
    req = n if need == "all" else n - 1
    v = "holds" if len(ok) >= req and n >= 1 else "fails"
    out.append((pid, key, "%d/%d (need %s)" % (len(ok), n, "N" if need == "all" else "N-1"), v, ",".join(bad), extra))


def med(rows, col):
    v = [f(r[col]) for r in rows if f(r.get(col)) is not None]
    return (statistics.median(v) if v else None), len(v), (min(v) if v else None), (max(v) if v else None)


qk = cell(A, "gin_qperr@hk")
judge("GD1", "gin_qperr@hk", qk, lambda r: r["outcome"] == "TRANSPARENT" and int(r["n_rec"]) >= 1 and r["result"] == "correct", "n1")
judge("GD2", "gin_qperr@hk", qk, lambda r: r["det_by"] in ("watch", "device") and f(r["det_ms"]) is not None and 0 <= f(r["det_ms"]) <= 100, "n1",
      "det_ms median %.3f n=%d range %.3f..%.3f" % med(qk, "det_ms"))
judge("GD3", "gin_qperr@hk", qk, lambda r: f(r["rec_ms"]) is not None and f(r["rec_ms"]) <= 1000, "n1",
      "rec_ms median %.3f n=%d range %.3f..%.3f" % med(qk, "rec_ms"))
for k, lim in (("gin_qperr_w1@hk", 70), ("gin_qperr_w100@hk", 200)):
    rr = cell(A, k)
    judge("GD4", k, rr, lambda r, lim=lim: r["outcome"] == "TRANSPARENT" and f(r["det_ms"]) is not None and f(r["det_ms"]) <= lim, "n1",
          "det_ms median %.3f n=%d range %.3f..%.3f; rec_ms median %.3f n=%d range %.3f..%.3f" % (med(rr, "det_ms") + med(rr, "rec_ms")))
m = {}
for k in ("gin_qperr_w1@hk", "gin_qperr@hk", "gin_qperr_w100@hk"):
    m[k] = med(cell(A, k), "det_wcq_ms")
gd5 = m["gin_qperr_w1@hk"][0] < m["gin_qperr@hk"][0] < m["gin_qperr_w100@hk"][0]
out.append(("GD5", "w1<w10<w100", "medians", "holds" if gd5 else "fails", "",
            "; ".join("%s median %.3f n=%d" % (k, v[0], v[1]) for k, v in m.items())))


def gc(r):
    d1, rx = f(r["det1_s"]), f(r["rec_rx_s"])
    return int(r["n_watch"]) == 0 and not (d1 is not None and d1 <= 0.1) and not (rx is not None and rx <= 1.0)


for k in ("gin_qperr@hr", "gin_qperr@hq"):
    rr = cell(A, k)
    judge("GC1", k, rr, gc, "n1", "outcomes %s" % sorted(set(r["outcome"] + "/" + r["end0"] + r["end1"] for r in rr)))
rr = cell(A, "gin_qperr_w0@hk")
judge("GC2", "gin_qperr_w0@hk", rr, gc, "n1", "outcomes %s" % [(r["id"], r["outcome"], r["det1_s"], r["det1_by"], r["rec_rx_s"]) for r in rr])
rr = cell(A, "gin_kill@hk")
judge("GR1", "gin_kill@hk", rr, lambda r: r["outcome"] in ("DECLINED", "HUNG") and f(r["dt_err"]) is not None and f(r["dt_err"]) <= 5 and int(r["n_watch"]) == 0, "n1",
      "dt_err range %.4f..%.4f; outcomes %s" % (med(rr, "dt_err")[2], med(rr, "dt_err")[3], sorted(set(r["outcome"] for r in rr))))
rr = cell(A, "gin_stop@hk")
judge("GF1", "gin_stop@hk", rr, lambda r: r["outcome"] == "TRANSPARENT" and int(r["n_death"]) == 0 and int(r["n_decl"]) == 0 and int(r["n_watch"]) == 0, "n1")
rr = cell(A, "gin_none@hk")
judge("GF2", "gin_none@hk", rr, lambda r: r["outcome"] == "TRANSPARENT" and int(r["n_watch"]) == 0 and int(r["n_decl"]) == 0, "all")
rr = cell(A, "nvs_kill@t1w")
judge("ND1", "nvs_kill@t1w", rr, lambda r: r["outcome"] == "DECLINED" and int(r["n_fin_verdict"]) >= 1 and r["surv_rc"] == "70" and int(r["n_harness_end"]) == 0
      and f(r["verdict_s"]) is not None and f(r["verdict_s"]) <= 0.1 and f(r["dt_end"]) <= 1.0, "n1",
      "verdict_s %.6f..%.6f; dt_end %.4f..%.4f" % (med(rr, "verdict_s")[2], med(rr, "verdict_s")[3], med(rr, "dt_end")[2], med(rr, "dt_end")[3]))
rr = cell(A, "nvs_remacc@t1w")
judge("ND2", "nvs_remacc@t1w", rr, lambda r: r["outcome"] == "DECLINED" and r["rc0"] == "70" and r["rc1"] == "70" and int(r["n_harness_end"]) == 0
      and f(r["dt_end"]) is not None and f(r["dt_end"]) <= 2.0, "n1", "dt_end %.4f..%.4f" % (med(rr, "dt_end")[2], med(rr, "dt_end")[3]))
rr = cell(A, "nvs_kill@t1_380")
judge("NC1", "nvs_kill@t1_380", rr, lambda r: r["outcome"] == "HUNG" and int(r["n_death"]) == 0, "n1",
      "text check (survivor has no error line): %d/%d; ended by %s" % (sum(1 for r in rr if int(r["n_err_surv"]) == 0), len(rr), sorted(set(r["end0"] + r["end1"] for r in rr))))
rr = cell(A, "nvs_remacc@t1_380")
judge("NC2", "nvs_remacc@t1_380", rr, lambda r: r["outcome"] == "HUNG" and int(r["n_declines"]) >= 1, "n1",
      "text check (both PEs decline and both end at the wall cap): %d/%d" % (sum(1 for r in rr if r["decl_pe"] == "PE0:1;PE1:1" and r["end0"] == "wall" and r["end1"] == "wall"), len(rr)))
for k in ("nvs_kill_rel@t1w", "nvs_remacc_rel@t1w"):
    rr = cell(A, k)
    judge("NR1", k, rr, lambda r: int(r["n_released"]) >= 1 and int(r["n_harness_end"]) == 0, "n1",
          "released per PE %s; exits %s" % ([r["released_pe"] for r in rr], [r["exit_dt"] for r in rr]))
rr = cell(A, "nvs_stop@t1w")
judge("NF1", "nvs_stop@t1w", rr, lambda r: r["outcome"] == "TRANSPARENT" and int(r["n_death"]) == 0 and int(r["n_declines"]) == 0, "n1")
rr = cell(A, "nvs_none@t1w")
judge("NF2", "nvs_none@t1w", rr, lambda r: r["outcome"] == "TRANSPARENT" and int(r["n_declines"]) == 0 and int(r["n_fin_verdict_all"]) == 0 and int(r["n_bye_sent"]) >= 1, "n1",
      "bye_sent per trial %s" % sorted(set(r["n_bye_sent"] for r in rr)))
a, b = med(cell(A, "nvs_none@t1w"), "ms_64m"), med(cell(A, "nvs_none@t1_380"), "ms_64m")
out.append(("NO1", "nvs_none t1w vs t1_380", "medians", "holds" if a[0] <= 1.10 * b[0] else "fails", "",
            "t1w median %.6f n=%d; t1_380 median %.6f n=%d; ratio %.5f" % (a[0], a[1], b[0], b[1], a[0] / b[0])))
rr = cell(A, "nvs_qperr@t1w")
judge("NQ1", "nvs_qperr@t1w", rr, lambda r: r["outcome"] == "TRANSPARENT" and int(r["n_rec"]) >= 1, "n1")
for k in ("f1_b@hk", "f3_b@hk", "bidirf_sym_b@hk"):
    judge("RG1", k, cell(G, k), lambda r: r["transparent_ok"] == "1", "all")
rr = cell(G, "f4_b@hk")
judge("RG3", "f4_b@hk", rr, lambda r: "the peer's socket shows" in r["declwhy_r0"] and r["cause_r0"] == "peer-dead" and f(r["decl_after_kill_ms_r0"]) is not None
      and 0 <= f(r["decl_after_kill_ms_r0"]) <= 2000 and r["teardown_r0"] == "no error" and r["uaerr_why_r0"] == "peer-dead", "all",
      "decl_after_kill_ms_r0 %.3f..%.3f" % (med(rr, "decl_after_kill_ms_r0")[2], med(rr, "decl_after_kill_ms_r0")[3]))
rr = cell(G, "hd_rxdeath_b@hk")
judge("RG4", "hd_rxdeath_b@hk", rr, lambda r: int(r["n_judged_r1"]) >= 1 and r["rx_rc"] == "remote process exited or there was a network error"
      and 0 <= f(r["release_after_kill_ms_r1"]) <= 2000 and 0 <= f(r["async_after_kill_ms_r1"]) <= 2000 and r["teardown_r1"] == "no error", "all",
      "release %.3f..%.3f ms, async %.3f..%.3f ms after kill" % (med(rr, "release_after_kill_ms_r1")[2:] + med(rr, "async_after_kill_ms_r1")[2:]))
rr = cell(G, "f2rel_b@hk")
judge("RG5", "f2rel_b@hk", rr, lambda r: "REM_ACCESS is not recoverable" in r["declwhy_r0"] and r["r1_outcome"] == "device_error"
      and r["rx_rc"] == "remote process exited or there was a network error" and r["rx_phantom_r1"] == "0" and r["teardown_r1"] == "no error"
      and f(r["teardown_ms_r1"]) <= 5000, "all", "teardown_ms_r1 %.1f..%.1f" % med(rr, "teardown_ms_r1")[2:])
rr = cell(G, "f1_b@hk")
judge("RG7", "f1_b@hk", rr, lambda r: r["rs_api_r0"] == "1" and r["rs_rounds_r0"] == "1" and r["rs_recovered_r0"] == "1" and r["rs_declined_r0"] == "0"
      and r["rs_rounds_r1"] == "1" and r["rs_recovered_r1"] == "1", "all")
for k in ("mr4_none@hk", "mr4_f1_01@hk"):
    judge("RG8", k, cell(G, k), lambda r: r["transparent_ok"] == "1", "all")


def rg9(r):
    return (int(r["n_rel_dead"]) == 3 and all(f(r["relms_r%d" % s]) is not None and 2000 <= f(r["relms_r%d" % s]) <= 3000 for s in (0, 1, 2))
            and int(r["n_surv_edges"]) == 6 and int(r["surv_tx_ok"]) == 6 and int(r["n_kdone_surv"]) == 3 and int(r["n_stuck_surv"]) == 0)


def relrange(rr):
    v = [f(r["relms_r%d" % s]) for r in rr for s in (0, 1, 2) if f(r.get("relms_r%d" % s)) is not None]
    return "release after judgment %.1f..%.1f ms (n=%d survivor values)" % (min(v), max(v), len(v)) if v else ""


rr = cell(G, "rm4_kill3_untimed@hk")
judge("RG9", "rm4_kill3_untimed@hk", rr, rg9, "all", relrange(rr))
rr = cell(G, "mr4_cyc_stall@hk")
judge("RG10", "mr4_cyc_stall@hk", rr, lambda r: int(r["n_hs"]) == 0 and r["transparent_ok"] == "1" and int(r["n_decl"]) == 0
      and all(x in r["rec_i"].split(";") for x in ("0-1", "1-2", "2-0")), "n1")
rr = cell(G, "mr4_twolow_stall@hk")
judge("MA1", "mr4_twolow_stall@hk", rr, lambda r: r["transparent_ok"] == "1" and int(r["n_decl"]) == 0 and int(r["n_hs"]) == 0
      and "3-0" in r["served3"].split(";") and "3-1" in r["served3"].split(";"), "n1")
judge("MC1", "rm4_late01@hk", cell(G, "rm4_late01@hk"), lambda r: int(r["decl01"]) >= 1 and int(r["rec01"]) == 0, "all")
judge("MC2", "rm4_late01_rounds@hk", cell(G, "rm4_late01_rounds@hk"), lambda r: int(r["rec01"]) >= 1 and int(r["decl01"]) == 0, "all")
rr = cell(G, "rm4_gap@hk")
judge("GP1", "rm4_gap@hk", rr, lambda r: r["gap_hit"] == "1" and r["gap_cause"] == "peer-dead" and r["gap_lac"] == "1" and r["gap_judged_r"] == "1"
      and int(r["n_rel_dead"]) == 3 and int(r["n_rel23"]) == 3 and int(r["n_kdone_surv"]) == 3 and int(r["n_stuck_surv"]) == 0, "n1", relrange(rr))
rr = cell(G, "rm4_gap@hw")
judge("GP2", "rm4_gap@hw", rr, lambda r: r["gap_hit"] == "1" and r["gap_cause"] == "unknown" and r["gap_judged_r"] == "0" and r["gap_resp_rel"] == "0"
      and r["gap_resp_stuck"] == "1" and r["gap_others_rel23"] == "2", "n1", relrange(rr) + "; rank0 rc %s" % [r["rc0"] for r in rr])
rr = cell(G, "rm4_gapx@hk")
judge("GP3", "rm4_gapx@hk", rr, lambda r: r["gap_exit_line"] == "1" and r["gap_rc_x"] == "73" and r["gap_hit"] == "1" and r["gap_cause"] == "peer-dead"
      and int(r["n_rel23"]) == 3 and int(r["n_kdone_surv"]) == 3 and int(r["n_stuck_surv"]) == 0, "n1", relrange(rr))
rr = cell(G, "rm4_kill3_hold@hk")
judge("PH1", "rm4_kill3_hold@hk", rr, lambda r: r["pol_n"] == "4" and r["pol_eff_ff"] == "1" and r["hold_warn_ranks"] == "4" and r["n_hold_warn"] == "4" and rg9(r), "all", relrange(rr))
rr = cell(G, "f4_mix_b@hk")
judge("PH2", "f4_mix_b@hk", rr, lambda r: r["pol_agreed_min"] == "0" and r["mix_warn_ranks"] == "2" and r["n_hold_warn"] == "0" and r["pol_eff_ff"] == "1"
      and "the peer's socket shows" in r["declwhy_r0"] and r["cause_r0"] == "peer-dead" and 0 <= f(r["decl_after_kill_ms_r0"]) <= 2000
      and r["teardown_r0"] == "no error" and r["uaerr_why_r0"] == "peer-dead", "all")
rr = cell(A, "gin_none@hk")
judge("LC1", "gin_none@hk", rr, lambda r: f(r["lb_shadow_min"]) is not None and f(r["lb_shadow_min"]) >= 1 and r["lb_ranks"] == "2", "all")
rr = cell(G, "f1_b@hk")
judge("LC1", "f1_b@hk", rr, lambda r: f(r["lb_min"]) is not None and f(r["lb_min"]) >= 1 and r["lb_ranks"] == "2", "all")
rr = cell(A, "gin_none@hk")
judge("WT1", "gin_none@hk", rr, lambda r: r["outcome"] == "TRANSPARENT" and r["wq_lines"] == "2" and f(r["wq_queries"]) is not None and f(r["wq_queries"]) >= 1, "all")
for pid, a, b, lim in (("LT1", "lat_4k_w10@hk", "lat_4k_w0@hk", 0.40), ("LT2", "lat_256k_w10@hk", "lat_256k_w0@hk", 0.30),
                       ("LT3", "lat_4k_w1@hk", "lat_4k_w0@hk", 1.0), ("LT4", "lat_256k_w1@hk", "lat_256k_w0@hk", 1.0)):
    ma, mb = med(cell(G, a), "lat_p50_us_kv"), med(cell(G, b), "lat_p50_us_kv")
    ra, rb = med(cell(G, a), "lat_p50_us_raw_median"), med(cell(G, b), "lat_p50_us_raw_median")
    d = abs(ma[0] - mb[0])
    out.append((pid, "%s vs %s" % (a, b), "medians n=%d,%d" % (ma[1], mb[1]), "holds" if d <= lim else "fails", "",
                "kv p50 medians %.3f vs %.3f (diff %.3f, bound %.2f); from raw csv %.4f vs %.4f" % (ma[0], mb[0], d, lim, ra[0], rb[0])))

w = csv.writer(sys.stdout, delimiter="|")
w.writerow(["id", "cell", "count", "verdict", "failing trials", "numbers"])
for row in out:
    w.writerow(row)
