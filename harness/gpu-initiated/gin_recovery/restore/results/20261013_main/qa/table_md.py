#!/usr/bin/env python3
"""Per-trial Markdown tables from out/trials_recount.csv (recount_rs.py), for recount.md. usage: table_md.py <csv>"""
import csv
import sys

rows = list(csv.DictReader(open(sys.argv[1])))


def n_of(stem):
    return stem.rsplit("_n", 1)[1]


def tab(title, key, cols, hdr):
    rs = sorted([r for r in rows if r["key"] == key], key=lambda r: int(n_of(r["stem"])))
    print("\n**%s** (`%s`, n=%d)\n" % (title, key, len(rs)))
    print("| " + " | ".join(["시행"] + hdr) + " |")
    print("|" + "---|" * (len(hdr) + 1))
    for r in rs:
        vals = []
        for c in cols:
            if callable(c):
                vals.append(c(r))
            else:
                vals.append(r.get(c, "") or "-")
        print("| n%s | %s |" % (n_of(r["stem"]), " | ".join(vals)))


def supp(r):
    out = []
    for part in r.get("suppress_detail", "").split("; "):
        q, rest = part.split(":", 1)
        f = dict(x.split("=") for x in rest.split())
        out.append("%s %s/%s" % (q.replace("q", "r"), f["supp"], f["exp"]))
    return ", ".join(out)


def yn(c):
    return lambda r: "예" if r.get(c) == "1" else ("아니오" if r.get(c) == "0" else "-")


def later(r):
    return "%s / %s" % (r.get("later_n", "-"), r.get("later_ms", "-"))


def ck(r):
    return "%s / %s / %s" % (r.get("ckpt_used", "-"), r.get("kr_last_step", "-"), r.get("replayed_dup_steps", "-"))


restore_cols = [yn("wait_held"), yn("data_equal"), yn("no_reexec"), yn("revived_done"), supp, "restore_time_ms",
                "act_after_hold_ms", later, ck, "ckpt_fetch_ms", "pause_max_ms"]
restore_hdr = ["대기 붙잡힘", "데이터 같음", "재실행 없음", "되살린 rank 끝", "억제 rank별 (셈/예상)", "복원 시간 ms",
               "활성화 ms(hold 시작 뒤)", "'later' 수 / ms", "체크포인트 / 죽은 rank 마지막 단계 / 다시 낸 단계",
               "체크포인트 가져오기 ms", "입력 멈춤 최대 ms"]
tab("rank 3 kill, 예비 프로세스 있음", "rs4_kill3@rs", restore_cols, restore_hdr)
tab("rank 1 kill (같은 GPU의 다른 rank)", "rs4_kill1@rs", restore_cols, restore_hdr)
tab("체크포인트 멈춤 중 kill", "rs4_kill3_ckpt@rs",
    ["die_ckpt", "die_in_pause", "pause_start_minus_dead_ms", yn("ckpt_before"), "stable_before_n"] + restore_cols,
    ["죽은 체크포인트", "멈춤 안 생존 rank 수", "멈춤 시작 - 자기 죽음 판정 ms", "앞 체크포인트 확정", "앞 확정 수"] + restore_hdr)
tab("예비 프로세스 등록 안 함", "rs4_kill3_nospare@rs",
    ["n_hold_lines", "n_surv_declined", "n_surv_released_kv", "rel_after_dead_ms", "rel_after_dead_rc_ms", yn("nospare_failfast_ok")],
    ["hold 줄 수", "거절 줄 있는 생존 rank", "풀린 생존 rank(kv)", "풀림 - 자기 죽음 판정 ms (r0,r1,r2)",
     "수신 시각: 풀림 - 첫 죽음 판정 ms", "조건"])
tab("예비 프로세스 등록 뒤 먼저 없어짐", "rs4_kill3_spareabsent@rs",
    [yn("spare_killed_first"), "n_hold_lines", "fb_after_hold_ms", "rel_after_fb_ms", "rel_after_dead_ms", yn("spare_absent_ok")],
    ["예비 프로세스 먼저 kill", "hold 줄 수", "fallback - hold 시작 ms (r0,r1,r2)", "풀림 - fallback ms",
     "풀림 - 죽음 판정 ms", "조건"])
tab("복원 없는 빌드 대조", "rs4_kill3@hk",
    ["n_hold_lines", "n_surv_declined", "n_surv_released_kv", "rel_after_dead_ms", "rel_after_dead_rc_ms", yn("degraded_release")],
    ["hold 줄 수", "거절 줄 있는 생존 rank", "풀린 생존 rank(kv)", "풀림 - 자기 죽음 판정 ms (r0,r1,r2)",
     "수신 시각: 풀림 - 첫 죽음 판정 ms", "조건"])
tab("장애 없음, 복원 켬", "rs4_none@rs",
    [yn("data_equal"), "restore_count", "pause_n", "pause_max_ms", "strict_forced", "strict_notforced", "strict_bad",
     "mr_lines_per_rank"],
    ["데이터 같음", "복원 수", "입력 멈춤 줄", "입력 멈춤 최대 ms", "강제 strict MR", "강제 아님 MR", "어긋난 MR",
     "rank별 MR 줄"])
tab("장애 없음, 복원 끔", "rs4_none_off@rs",
    [yn("data_equal"), "strict_forced", "strict_notforced", "strict_bad", "mr_lines_per_rank"],
    ["데이터 같음", "강제 strict MR", "강제 아님 MR", "어긋난 MR", "rank별 MR 줄"])
for c in ("rs4_refuse_symgin@rs", "rs4_refuse_gintype@rs", "rs4_refuse_restoreoff1@rs", "rs4_refuse_nomacro@rs"):
    cols = ["resume_rc", yn("resume_err_all"), yn("reason_same"), "ff_fallthrough"]
    hdr = ["Resume rc (r0-r3)", "모두 오류", "이유 같음", "오류 없이 넘어간 rank"]
    if c.startswith("rs4_refuse_nomacro"):
        cols += [yn("nomacro_reason"), yn("refused_ran_ok")]
        hdr += ["이유에 매크로", "끝까지 정확히 돎"]
    tab("켤 수 없는 설정", c, cols, hdr)
for c in ("reg_mr4_none@rs", "reg_mr4_none_hold@rs"):
    tab("회귀, 장애 없음", c, ["outcomes", "rcs", yn("transparent_ok")], ["outcome (r0-r3)", "종료 코드", "조건"])
for c in ("reg_rm4_kill3_untimed@rs", "reg_rm4_kill3_untimed_hold@rs"):
    tab("회귀, rank 3 kill", c, ["n_rel_dead", "rel_after_dead_ms", "surv_tx_ok", "n_kdone_surv", "n_stuck_surv",
                                yn("regression_kill3_ok")],
        ["rank 3 받기 오류로 풀린 생존 rank", "풀림 - 자기 죽음 판정 ms (r0,r1,r2)", "생존 rank 사이 보내기 정상 (/6)",
         "커널 끝난 생존 rank", "멈춘 생존 rank", "조건"])


# ---- cost tables (section 6): table_md.py <trials csv> <cost_runs.csv>
if len(sys.argv) > 2:
    cr = [r for r in csv.DictReader(open(sys.argv[2])) if not r["invalid"]]

    def vals(node, metric, arm):
        return sorted(float(r["value"]) for r in cr if r["node"] == node and r["metric"] == metric and r["arm"] == arm)

    def med(v):
        n = len(v)
        return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2

    def worse(metric, b, a):
        return (b - a) / b * 100 if metric == "bw256k" else (a - b) / b * 100

    def cellv(node, metric, arm, base):
        v, bv = vals(node, metric, arm), vals(node, metric, base)
        m, bm = med(v), med(bv)
        sep = min(v) > max(bv) or min(bv) > max(v)
        nd = 3
        return ("%.*f (%.*f–%.*f)" % (nd, m, nd, min(v), nd, max(v)), "%+.2f" % worse(metric, bm, m), "갈림" if sep else "안 갈림", len(v))

    print("\n**log 가족** (받는 노드마다, 팔마다 유효 실행 6개의 중앙값과 범위; 지연 µs, 대역 GB/s; % = 기준 팔 off의 중앙값에 대한 나쁜 쪽 차)\n")
    print("| 노드 | 지표 | off | ua-hold | ua-hold % | on | on % | sampled % | full % |")
    print("|---|---|---|---|---|---|---|---|---|")
    for node in ("rain", "sunny"):
        for m in ("lat4k", "lat256k", "bw256k"):
            b = vals(node, m, "off")
            nd = 3
            bs = "%.*f (%.*f–%.*f)" % (nd, med(b), nd, min(b), nd, max(b))
            u, o, sa, fu = (cellv(node, m, a, "off") for a in ("ua-hold", "on", "sampled", "full"))
            print("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (node, m, bs, u[0], u[1], o[0], o[1], sa[1], fu[1]))
    print("\n**ffbranch 가족** (지연 µs; % = 기준 팔 ffb-hk의 중앙값에 대한 차, 양수가 느림; 갈림 = 한 팔의 6개가 모두 다른 팔의 6개보다 큼)\n")
    print("| 노드 | 지표 | ffb-hk | ffb-rs | ffb-rs % | ffb-rs 갈림 | ffb-rs-macro (보고만) | ffb-rs-macro % | ffb-rs-macro 갈림 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for node in ("rain", "sunny"):
        for m in ("lat4k", "lat256k"):
            b = vals(node, m, "ffb-hk")
            bs = "%.3f (%.3f–%.3f)" % (med(b), min(b), max(b))
            r1, r2 = cellv(node, m, "ffb-rs", "ffb-hk"), cellv(node, m, "ffb-rs-macro", "ffb-hk")
            print("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (node, m, bs, r1[0], r1[1], r1[2], r2[0], r2[1], r2[2]))
