#!/usr/bin/env python3
"""score.py - blind-apps scorer (EXPERIMENT.md 3.2, 9 step 8). Run only after the evaluator's judgments are committed.

    score.py <results dir> [--judgments judgments.csv] [--schedule ~/blind-seal/schedule.json]

  1. checks the seal: the schedule's sha256 equals PREREG.txt's, schedule_gen.py verify re-derives it from its seed,
     and every blind trial's recorded entry equals the schedule's entry with the same id;
  2. rows_blind.all_rows(): one row per trial with the mechanical outcome (the truth comes from trial.meta);
  3. joins the judgments (if given; their sha256 is printed and must match the one committed before this step);
  4. evaluates every prediction of predictions.csv on the valid blind trials of its selection and writes
     <results>/SCORE.md and <results>/trials_scored.csv.

Prediction grammar (predictions.csv, column acceptance): a Python expression over
  n                  the number of valid trials in the selection
  count(<expr>)      how many of them make <expr> true; inside, every column of trials_scored.csv is a name, and an
                     empty field compares false and makes arithmetic fail (the trial then does not count)
  ceil(x)
Selection (column select): "<workload>:<class>" joined by "+", "*" for any. A prediction is "자료 부족" when the
selection has fewer valid trials than n_min, or when a trial of it has outcome UNKNOWN (the DDP oracle was not
valid), or (evaluator predictions) when a trial has no judgment.
"""
import argparse, csv, hashlib, json, math, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rows_blind import COLS, all_rows  # noqa: E402

JCOLS = ["j_class", "j_target", "j_outcome", "j_result_ok", "j_first_error_s", "j_confidence", "j_ok_outcome",
         "j_ok_class", "j_ok_target"]


class Nil:
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
    def __repr__(self): return "<empty>"


NIL = Nil()


def val(x):
    if x is None or x == "":
        return NIL
    if isinstance(x, (int, float)):
        return x
    try:
        return int(x)
    except ValueError:
        try:
            return float(x)
        except ValueError:
            return x


class RowNS(dict):
    def __init__(self, row):
        super().__init__()
        self.row = row

    def __missing__(self, k):
        if k in self.row:
            return val(self.row[k])
        raise KeyError(k)


def cond(expr, row):
    try:
        return bool(eval(expr, {"__builtins__": {}}, RowNS(row)))
    except (TypeError, ValueError, ZeroDivisionError):
        return False


def split_counts(acc):
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


def selected(rows, sel):
    keys = [s.strip().split(":") for s in sel.split("+")]
    return [r for r in rows if any((w in ("*", r["workload"])) and (c in ("*", r["cls"])) for w, c in keys)]


def evaluate(pred, rows):
    rs = [r for r in selected(rows, pred["select"]) if r["valid"] == 1 and r["kind"] == "blind"]
    n = len(rs)
    if n < int(pred["n_min"]) or any(r["outcome"] == "UNKNOWN" for r in rs):
        return "자료 부족", n, [], ""
    if pred["kind"] == "E" and any(r.get("j_outcome", "") == "" for r in rs):
        return "자료 부족", n, [], ""
    acc = pred["acceptance"]
    parts, pos, details = [], 0, []
    for s, e, inner in split_counts(acc):
        t = [r for r in rs if cond(inner, r)]
        details.append((inner, len(t), [r["id"] for r in rs if not cond(inner, r)]))
        parts += [acc[pos:s], str(len(t))]
        pos = e
    parts.append(acc[pos:])
    expr = "".join(parts)
    try:
        ok = bool(eval(expr, {"__builtins__": {}}, {"n": n, "ceil": math.ceil}))
    except (TypeError, ValueError):
        ok = False
    return ("맞음" if ok else "틀림"), n, details, expr


def sha256(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--judgments", default=None)
    ap.add_argument("--schedule", default="~/blind-seal/schedule.json")
    a = ap.parse_args()
    res = os.path.abspath(a.results)
    sched_p = os.path.expanduser(a.schedule)
    notes = []
    # 1. the seal
    sched = json.load(open(sched_p))
    d = sha256(sched_p)
    pre = open(os.path.join(HERE, "PREREG.txt")).read() if os.path.exists(os.path.join(HERE, "PREREG.txt")) else ""
    m = re.search(r"schedule\.json sha256 ([0-9a-f]{64})", pre)
    notes.append("schedule sha256 %s, PREREG.txt %s: %s" % (d[:16], m.group(1)[:16] if m else "(none)",
                                                           "same" if m and m.group(1) == d else "DIFFERENT OR MISSING"))
    v = subprocess.run([sys.executable, os.path.join(HERE, "schedule_gen.py"), "verify", sched_p], capture_output=True,
                       text=True)
    notes.append("schedule_gen.py verify: %s" % v.stdout.strip())
    by_id = {t["id"]: t for t in sched["trials"]}
    rows, refs, ref_ok = all_rows(res)
    mism = []
    for r in rows:
        if r["kind"] != "blind":
            continue
        meta = json.load(open(os.path.join(res, "raw", r["id"], "trial.meta")))
        if by_id.get(r["id"]) != meta["entry"]:
            mism.append(r["id"])
    notes.append("blind trials whose recorded entry differs from the schedule: %d %s" % (len(mism), mism[:5]))
    missing = sorted(set(by_id) - {r["id"] for r in rows})
    notes.append("scheduled trials without a result: %d %s" % (len(missing), missing[:8]))
    notes.append("DDP reference sha256 per rank: %s (%s)" % ({k: v[:16] for k, v in refs.items()},
                                                             "agree" if ref_ok else "DISAGREE OR MISSING"))
    # 3. judgments
    if a.judgments:
        notes.append("judgments %s sha256 %s" % (a.judgments, sha256(a.judgments)))
        js = {j["trial_id"].strip(): j for j in csv.DictReader(open(a.judgments))}
        for r in rows:
            j = js.get(r["id"])
            if not j:
                continue
            r["j_class"] = j["fault_class"].strip().lower()
            r["j_target"] = j["target_rank"].strip().lower()
            r["j_outcome"] = j["outcome"].strip().lower()
            r["j_result_ok"] = j["result_ok"].strip().lower()
            r["j_first_error_s"] = j["first_error_s"].strip()
            r["j_confidence"] = j["confidence"].strip()
            r["j_ok_outcome"] = int(r["j_outcome"].upper() == r["outcome"])
            r["j_ok_class"] = int(r["j_class"] == r["cls"])
            r["j_ok_target"] = int(r["j_target"] in ("-", "") if r["target"] == "" else r["j_target"] == str(r["target"]))
    # 4. predictions
    preds = list(csv.DictReader(open(os.path.join(HERE, "predictions.csv"))))
    lines = ["# blind-apps 채점", "", "score.py가 만든 파일이다. 손으로 고치지 않는다.", "", "## 봉인과 입력", ""]
    lines += ["- " + x for x in notes]
    lines += ["", "## 예측별 판정", "", "| id | 종류 | 선택 | 판정 | n | 식(값 대입) | 거짓인 시행 |", "|---|---|---|---|--:|---|---|"]
    tally = {}
    for p in preds:
        verdict, n, details, expr = evaluate(p, rows)
        tally[verdict] = tally.get(verdict, 0) + 1
        miss = "; ".join("%s: %s" % (inner, ",".join(ids) or "-") for inner, _, ids in details)
        lines.append("| %s | %s | `%s` | %s | %d | `%s` | %s |" % (p["id"], p["kind"], p["select"], verdict, n, expr,
                                                                 miss.replace("|", "/")))
    lines += ["", "판정 수: %s" % ", ".join("%s %d" % kv for kv in sorted(tally.items())), "",
              "## 제외와 무효(따로 셈)", "", "| 작업 | 장애 | 계획 | 유효 | 미적용 | 시작 실패 |", "|---|---|--:|--:|--:|--:|"]
    for wl, w in sched["header"]["config"]["workloads"].items():
        for c, k in sorted(w["classes"].items()):
            rs = [r for r in rows if r["kind"] == "blind" and r["workload"] == wl and r["cls"] == c]
            lines.append("| %s | %s | %d | %d | %d | %d |" % (wl, c, k, sum(r["valid"] for r in rs),
                                                              sum(1 for r in rs if not r["applied"]),
                                                              sum(1 for r in rs if r["applied"] and r["void"])))
    with open(os.path.join(res, "SCORE.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(res, "trials_scored.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS + JCOLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLS + JCOLS})
    print("\n".join(notes))
    print("verdicts: %s -> %s" % (tally, os.path.join(res, "SCORE.md")))


if __name__ == "__main__":
    main()
