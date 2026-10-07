#!/usr/bin/env python3
"""gin-s2-close scorer: applies the frozen acceptance rules of predictions.csv (EXPERIMENT.md 3.2 grammar) to the main
run and writes <resultsdir>/SCORE.md and <resultsdir>/trials_scored.csv.

usage: score.py <resultsdir>          (e.g. results/20261007)

Steps:
  1. every hold subdirectory with *_meta.txt files -> ../scripts/ts2/rows.py -> trials_<sub>.csv (rows.py columns);
  2. rows_extra.extra() adds the section 3.1 columns from the per-trial files;
  3. each trial gets its cell key cell@build and a status: scored, excluded (section 8 exclusions: bind failure, fault
     not applied, trigger missed, no kill, fault before the first get), config (a section 8 configuration check failed),
     or surplus (non-excluded trials beyond the planned count of section 7; the first ones by trial number are scored);
  4. every prediction is evaluated on the scored trials with the section 3.2 grammar; a prediction whose cells have
     fewer scored trials than planned is "자료 부족".
gate_pass is the number of result=PASS lines of <resultsdir>/gate_test.txt.
"""
import csv, glob, hashlib, os, re, statistics, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(HERE, "..", "scripts", "ts2", "rows.py")
sys.path.insert(0, HERE)
from rows_extra import extra  # noqa: E402

# section 7: planned scored trials per cell key (latency cells: runs)
PLANNED = {}
for c, b in (("base", "base"), ("s1off", "s1"), ("s1on", "s1"), ("s2off", "s2"), ("s2on", "s2"), ("s2sys", "var_sys")):
    for sz in ("4k", "256k"):
        PLANNED[f"lat_{c}_{sz}@{b}"] = 5
PLANNED.update({"lat_s2r_on_4k@s2r": 5, "lat_s2r_on_256k@s2r": 5,
                "mt16_f1_b@s2": 5, "mt64_f1_b@s2": 5, "bidirf_sym_b@s2": 5, "bidirf_sym_notie_b@s2": 5,
                "f2rel_b@s2r": 10, "ringf2rel_b@s2r": 10, "f2rel_off_b@s2r": 5, "off_f1_b@s2r": 5,
                "f1_b@s2r": 5, "f3_b@s2r": 5, "f1g0_b@s2r": 5, "mt256_f1_b@s2r": 5, "bidirf_f1both_b@s2r": 5,
                "f4_b@s2r": 5, "get_f1_b@s2rget": 10, "get_none_b@s2rget": 5, "mt1024_norescue_b@s2r": 5,
                "mute8_f1_b@s2r": 10, "mute_f3_b@s2r": 10, "mute1_f1_b@s2r": 5})
MUTE_CELLS = {"mute8_f1_b", "mute_f3_b", "mute1_f1_b"}
UA_OFF_CELLS = {"f2rel_off_b"}  # NCCL_GIN_TS_USER_ABORT=0

# Korean labels for SCORE.md (the condition in words; ids go in parentheses)
LABEL = {
    "RA1": "16, 64 스레드 로컬 QP 오류가 최종 빌드에서 투명",
    "RA2a": "실제 양방향 동시 시작이 최종 빌드에서 투명",
    "RA2b": "동시 시작에서 두 helper가 함께 시작해 한쪽이 양보",
    "RA3": "동시 시작 처리를 끄면 대부분 양쪽 거절(대조)",
    "RA4a": "4 KiB 지연: 2단계 켬 − 끔이 0.30–1.20 µs",
    "RA4b": "256 KiB 지연: 2단계 켬 − 끔이 0.10–1.00 µs",
    "RA4c": "게이트 미세 시험 14/14 통과",
    "RB1a": "거절 뒤 받는 쪽 abort가 5 s 안에 돌아옴",
    "RB1b": "abort 전에는 받는 쪽 커널이 풀리지 않음",
    "RB1c": "보내는 쪽 결정(원격 접근 오류로 거절)은 그대로",
    "RB2": "burst 받는 쪽 abort가 8 s 안에 돌아옴",
    "RB3": "abort 플래그를 끄면 받는 쪽 abort가 자기 대기를 기다림(대조)",
    "RB4a": "abort 플래그를 이어도 복구 결과는 그대로",
    "RB4b": "abort 플래그를 이어도 상대 kill은 거절되고 abort가 돌아옴",
    "RB5": "투명 복구를 끄면 플래그를 잇지 않음(대조)",
    "RB6a": "abort 플래그의 4 KiB 지연 비용 0.40 µs 이하(대조)",
    "RB6b": "abort 플래그의 256 KiB 지연 비용 0.30 µs 이하(대조)",
    "RC1a": "get이 낀 라운드는 READ 표식으로 거절",
    "RC1b": "get이 낀 라운드: 조용한 실패 0, 투명 복구 1 이하",
    "RC2": "장애 없는 get 모드는 투명하고 get 데이터가 맞음(대조)",
    "RC3a": "사본 영역을 끄면 거절되고 조용한 실패 없음(대조)",
    "RC3b": "사본 영역을 끈 거절의 사유가 덮인 WQE(대조)",
    "RD1a": "8 s 끊김에서 소켓이 시간 초과로 2.5–7.0 s 안에 닫힘",
    "RD1b": "끊김이 다음 장애 전까지 앱에 알려지지 않음",
    "RD1c": "끊김 뒤 로컬 QP 오류는 helper 소켓이 없어 거절",
    "RD1d": "끊김 뒤 받는 쪽은 비동기 오류를 받지 못함",
    "RD2": "끊김 중 상대 QP 오류를 살아 있는 상대인데 FIN/RST 사유로 거절",
    "RD3": "1 s 끊김은 소켓을 닫지 않고 복구는 투명(대조)",
}
EXCL_LABEL = {"bind": "드라이버 랑데부 포트 충돌", "no_fault": "장애 미적용(훅 발화 없음)", "trigger_miss": "트리거 미도달",
              "no_kill": "kill 기록 없음", "fault_before_get": "첫 get 전에 장애",
              "config_ts_off": "설정 확인 실패: 투명 복구 시작 줄 없음",
              "config_no_ua": "설정 확인 실패: abort 플래그 줄 없음", "config_no_mute": "설정 확인 실패: 끊김 시작 줄 없음",
              "surplus": "계획 수를 넘은 시행"}


# ---- values with the section 3.2 None rule ----
class Nil:
    """An empty field: every comparison is false and arithmetic raises (so the enclosing condition is false)."""
    def __eq__(self, o): return False
    def __ne__(self, o): return False
    def __lt__(self, o): return False
    def __le__(self, o): return False
    def __gt__(self, o): return False
    def __ge__(self, o): return False
    def __bool__(self): return False
    def __hash__(self): return 0
    def _err(self, *a): raise TypeError("empty field")
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = __abs__ = _err
    __and__ = __rand__ = _err
    def __repr__(self): return "<empty>"


NIL = Nil()


def val(x):
    if x is None or x == "":
        return NIL
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(x)
    except ValueError:
        return x


def has(f, s):
    return isinstance(f, str) and s in f


def nonempty(f):
    return not isinstance(f, Nil)


def maskbit(f, b):
    if not isinstance(f, str):
        return False
    m = re.search(r"mask 0x([0-9a-fA-F]+)", f)
    return bool(m) and (int(m.group(1), 16) & int(b)) != 0


class RowNS(dict):
    def __init__(self, row):
        super().__init__()
        self.row = row

    def __missing__(self, k):
        if k in self.row:
            return val(self.row[k])
        raise KeyError(k)  # not a column: fall back to the functions (has, nonempty, ...); a typo stays a NameError


def cond_true(expr, row):
    try:
        return bool(eval(expr, {"__builtins__": {}, "has": has, "nonempty": nonempty, "maskbit": maskbit, "abs": abs},
                         RowNS(row)))
    except (TypeError, ValueError):
        return False


def split_counts(acc):
    """Find every count(<expr>) with balanced parentheses; returns [(start, end, inner)]."""
    out, i = [], 0
    while True:
        j = acc.find("count(", i)
        if j < 0:
            return out
        k, depth = j + len("count("), 1
        while depth:
            ch = acc[k]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == '"':
                k = acc.index('"', k + 1)
            k += 1
        out.append((j, k, acc[j + len("count("):k - 1]))
        i = k


def evaluate(acc, rows_by_key, cell_key, gate_pass):
    """Evaluate one acceptance expression for one cell (rows = scored trials of cell_key). Returns
    (ok, details) where details lists (inner expression, count, n, stems where false, stems where true)."""
    rows = rows_by_key.get(cell_key, [])
    parts, details, pos = [], [], 0
    for s, e, inner in split_counts(acc):
        t = [r for r in rows if cond_true(inner, r)]
        f = [r for r in rows if not cond_true(inner, r)]
        details.append((inner, len(t), len(rows), [r["stem"] for r in f], [r["stem"] for r in t], acc[e:e + 12]))
        parts.append(acc[pos:s])
        parts.append(str(len(t)))
        pos = e
    parts.append(acc[pos:])
    expr = "".join(parts)

    def median(field, key):
        v = [val(r.get(field)) for r in rows_by_key.get(key, [])]
        v = [x for x in v if isinstance(x, float)]
        return statistics.median(v) if v else NIL

    class FieldNames(dict):  # outside count(), a bare name is a column name (the first argument of median)
        def __missing__(self, k):
            return k

    try:
        ok = bool(eval(expr, {"__builtins__": {}},
                       FieldNames({"abs": abs, "median": median, "gate_pass": gate_pass})))
    except TypeError:
        ok = False
    # for SCORE.md only: the expression with every median and gate_pass replaced by its value
    shown = re.sub(r'median\((\w+),\s*"([^"]+)"\)',
                   lambda m: (lambda v: "%.3f" % v if isinstance(v, float) else "(빈 값)")(median(m.group(1), m.group(2))), expr)
    shown = shown.replace("gate_pass", str(gate_pass))
    return ok, details, shown


def keys_of(cells):
    return [c.strip() for c in cells.split(";") if "@" in c]


def main():
    R = os.path.abspath(sys.argv[1])
    subs = sorted(d for d in os.listdir(R) if os.path.isdir(os.path.join(R, d)) and glob.glob(os.path.join(R, d, "*_meta.txt")))
    trials = []
    for sub in subs:
        out = os.path.join(R, f"trials_{sub}.csv")
        subprocess.run([sys.executable, ROWS, os.path.join(R, sub), "--out", out], check=True, stderr=subprocess.DEVNULL)
        for r in csv.DictReader(open(out)):
            r.update({k: ("" if v is None else v) for k, v in extra(r, os.path.join(R, sub, r["stem"])).items()})
            r["sub"] = sub
            r["key"] = f'{r["cell"]}@{r["build"]}'
            m = re.search(r"n(\d+)$", r.get("trial") or "")
            r["tnum"] = int(m.group(1)) if m else 0
            trials.append(r)
    # statuses
    for r in trials:
        st = "candidate"
        f = r.get("fault")
        n0, n1 = val(r.get("n_fires_r0")), val(r.get("n_fires_r1"))
        if r.get("bind_fail") == "1":
            st = "bind"
        elif f in ("F1", "F1both") and n0 == 0:
            st = "no_fault"
        elif f == "F3" and n1 == 0:
            st = "no_fault"
        elif isinstance(val(r.get("trigger_miss")), float) and val(r.get("trigger_miss")) > 0:
            st = "trigger_miss"
        elif f == "F4" and str(r.get("killed")) != "1":
            st = "no_kill"
        elif r["cell"] == "get_f1_b" and not (isinstance(val(r.get("fault_after_launch_ms")), float)
                                              and val(r.get("fault_after_launch_ms")) > 0):
            st = "fault_before_get"
        elif r["build"] in ("s2r", "s2rget") and r.get("ts") == "1":
            if not (val(r.get("ts_on_r0")) >= 1 and val(r.get("ts_on_r1")) >= 1):
                st = "config_ts_off"
            elif r["cell"] not in UA_OFF_CELLS and not (val(r.get("ua_r0")) >= 1 and val(r.get("ua_r1")) >= 1):
                st = "config_no_ua"
            elif r["cell"] in MUTE_CELLS and not val(r.get("n_mute_on_r0")) >= 1:
                st = "config_no_mute"
        r["status"] = st
    by_key = {}
    for r in sorted(trials, key=lambda x: (x["key"], x["tnum"], x["sub"])):
        by_key.setdefault(r["key"], []).append(r)
    scored = {}
    for k, rs in by_key.items():
        cand = [r for r in rs if r["status"] == "candidate"]
        plan = PLANNED.get(k, 0)
        for i, r in enumerate(cand):
            r["status"] = "scored" if i < plan else "surplus"
        scored[k] = [r for r in rs if r["status"] == "scored"]
    gate = os.path.join(R, "gate_test.txt")
    gate_pass = sum(1 for l in open(gate) if "result=PASS" in l) if os.path.exists(gate) else NIL
    gate_lines = sum(1 for l in open(gate) if "result=" in l) if os.path.exists(gate) else 0
    # predictions
    preds = list(csv.DictReader(open(os.path.join(HERE, "predictions.csv"))))
    sha = hashlib.sha256(open(os.path.join(HERE, "predictions.csv"), "rb").read()).hexdigest()
    frozen = open(os.path.join(HERE, "PREREG.txt")).read()
    results = []
    for p in preds:
        acc = p["acceptance"]
        keys = keys_of(p["cells"])
        per_cell = acc.startswith("per cell:")
        a = acc[len("per cell:"):].strip() if per_cell else acc
        short = [k for k in keys if len(scored.get(k, [])) < PLANNED.get(k, 0)]
        uses_gate = "gate_pass" in a
        if uses_gate and not isinstance(gate_pass, int):
            short.append("gate_test.txt")
        evals = []
        if per_cell:
            for k in keys:
                evals.append((k,) + evaluate(a, scored, k, gate_pass))
        else:
            k = keys[0] if keys else ""
            evals.append((k,) + evaluate(a, scored, k, gate_pass))
        ok = all(e[1] for e in evals)
        verdict = "자료 부족" if short else ("맞음" if ok else "틀림")
        results.append((p, keys, evals, verdict, short))
    # trials_scored.csv
    cols = ["key", "status", "sub", "stem", "cell", "build", "trial"]
    for r in trials:
        for c in r:
            if c not in cols:
                cols.append(c)
    with open(os.path.join(R, "trials_scored.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(trials, key=lambda x: (x["sub"], x["key"], x["tnum"])):
            w.writerow(r)
    # SCORE.md
    L = []
    L.append("# gin-s2-close 채점 결과")
    L.append("")
    L.append(f"`score.py`가 원자료(`{os.path.relpath(R, HERE)}/`의 hold별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.")
    L.append("")
    L.append(f"- 예측 파일 sha256: `{sha}`. `PREREG.txt`의 값과 {'같다' if sha in frozen else '다르다(확인 필요)'}.")
    L.append(f"- 시행 수(모든 hold): {len(trials)}. 판정한 시행: {sum(len(v) for v in scored.values())}. "
             f"게이트 미세 시험 결과 줄: {gate_lines}.")
    L.append("- 판정식과 열은 `EXPERIMENT.md` 3.1–3.2, 판정식 원문은 `predictions.csv`.")
    L.append("")
    L.append("## 판정 요약")
    L.append("")
    L.append("| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |")
    L.append("|---|---|--:|---|---|")
    for p, keys, evals, verdict, short in results:
        ns, hits = [str(len(scored.get(k, []))) for k in keys], []
        for k, ok, det, expr in evals:
            if det:
                hits.append(", ".join(f"{c}/{n}" for (_, c, n, _, _, _) in det))
            else:
                hits.append(expr)
        cells = ", ".join(f"`{k}`" for k in keys) if keys else "게이트 미세 시험"
        L.append(f"| {LABEL[p['id']]} ({p['id']}) | {cells} | {' / '.join(ns) if keys else gate_lines} | "
                 f"{'; '.join(hits)} | {verdict} |")
    L.append("")
    L.append("## 예측별 세부")
    L.append("")
    for p, keys, evals, verdict, short in results:
        L.append(f"### {LABEL[p['id']]} ({p['id']}): {verdict}")
        L.append("")
        L.append(f"- 판정식: `{p['acceptance']}`")
        if short:
            L.append(f"- 계획 수에 못 미친 셀: {', '.join(short)}")
        for k, ok, det, expr in evals:
            L.append(f"- 셀 `{k}`: 판정한 시행 {len(scored.get(k, []))}회, 대입한 식 `{expr}` → {'참' if ok else '거짓'}")
            for inner, c, n, fs, ts, tail in det:
                upper = bool(re.match(r"\s*(<=|<)", tail)) or bool(re.match(r"\s*==\s*0\b", tail))
                miss = ts if upper else fs
                what = "조건을 만족한(예측과 반대인) 시행" if upper else "조건을 만족하지 않은 시행"
                L.append(f"  - `count({inner})` = {c}/{n}. {what}: {', '.join(miss) if miss else '없음'}")
        L.append("")
    L.append("## 셀별 시행 수와 따로 센 시행")
    L.append("")
    L.append("| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |")
    L.append("|---|--:|--:|--:|---|")
    for k in sorted(set(list(by_key.keys()) + list(PLANNED.keys()))):
        rs = by_key.get(k, [])
        apart = {}
        for r in rs:
            if r["status"] != "scored":
                apart.setdefault(r["status"], []).append(r["stem"])
        txt = "; ".join(f"{EXCL_LABEL.get(s, s)}: {', '.join(v)}" for s, v in sorted(apart.items())) or "없음"
        L.append(f"| `{k}` | {PLANNED.get(k, 0)} | {len(rs)} | {len(scored.get(k, []))} | {txt} |")
    L.append("")
    open(os.path.join(R, "SCORE.md"), "w").write("\n".join(L))
    print("\n".join(f"{p['id']}: {v}" for p, _, _, v, _ in results))


if __name__ == "__main__":
    main()
