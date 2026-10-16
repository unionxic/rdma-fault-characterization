#!/usr/bin/env python3
"""check_cells_gc.py - gin-control, test side: cross-check cells_gc.json (and predictions_gc.csv) against ../../EXPERIMENT.md
sections 3 and 7. CPU only, standard library only; reads files, writes nothing.

    check_cells_gc.py [--doc ../../EXPERIMENT.md]

Checks (each failure is one line "FAIL ..."; exit 1 when any):
  section 7   27 table rows = cells_gc.json "rows" (in order); every row's gc*/gct* cell names and their builds and n (column
              "빌드와 반복 수", parentheses dropped; forms "`@b` n", "`@b` 각 n", "`@b1` n1, `@b2` n2", "`@b` n1, n2" with two
              names) equal the cells of cells_gc.json; no cell in the json outside section 7
  section 3   every search key of the table's last column has at least one cell (a cell@build, the regression, the cost
              family or a local item); every cell of the json feeds at least one key that section 3 names; every gc*/gct*
              cell name in a key's own row feeds that key in the json
  rows        a row without a key must say why (qa_only)
  predictions predictions_gc.csv's ids are exactly section 3's keys, each row's cells column names json cells only
"""
import argparse, csv, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def section(text, num):
    m = re.search(r"^## %d\. .*?$(.*?)(?=^## \d+\. )" % num, text, re.S | re.M)
    return m.group(1) if m else ""


def table_rows(sec):
    out = []
    for line in sec.splitlines():
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= set("-: "):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        out.append(cols)
    return out[1:] if out else []  # drop the header


CELLNAME = re.compile(r"`(gct?4_[a-z0-9_]+)`")


def sec7_cells(cols):
    names = CELLNAME.findall(cols[0])
    c3 = re.sub(r"\([^)]*\)", "", cols[2])
    segs = re.findall(r"`@(\w+)`([^`]*)", c3)
    builds = [(b, re.findall(r"\d+", rest), "각" in rest) for b, rest in segs]
    want = {}
    if not names:
        return want
    if len(builds) == 1:
        b, nums, each = builds[0]
        if len(nums) == 1:
            for n in names:
                want["%s@%s" % (n, b)] = int(nums[0])
        elif len(nums) == len(names):
            for n, k in zip(names, nums):
                want["%s@%s" % (n, b)] = int(k)
    elif len(names) == 1:
        for b, nums, _ in builds:
            want["%s@%s" % (names[0], b)] = int(nums[0])
    elif len(builds) == len(names):
        for n, (b, nums, _) in zip(names, builds):
            want["%s@%s" % (n, b)] = int(nums[0])
    return want


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=os.path.join(HERE, "..", "..", "EXPERIMENT.md"))
    ap.add_argument("--cells", default=os.path.join(HERE, "cells_gc.json"))
    ap.add_argument("--preds", default=os.path.join(HERE, "predictions_gc.csv"))
    a = ap.parse_args()
    text = open(a.doc, encoding="utf-8").read()
    cj = json.load(open(a.cells, encoding="utf-8"))
    fails = []

    def fail(s):
        fails.append(s)
        print("FAIL " + s)

    # ---- section 7
    r7 = table_rows(section(text, 7))
    rows = cj["rows"]
    if len(r7) != len(rows):
        fail("section 7 has %d rows, cells_gc.json %d" % (len(r7), len(rows)))
    want_all = {}
    for i, cols in enumerate(r7):
        w = sec7_cells(cols)
        want_all.update(w)
        if i < len(rows):
            got = set(k for k in rows[i]["keys"] if "@" in k)
            if w and set(w) != got:
                fail("section 7 row %d (%s): cells %s, json %s" % (i + 1, cols[0][:40], sorted(w), sorted(got)))
            if not w and got:
                fail("section 7 row %d names no gc cell but the json row has %s" % (i + 1, sorted(got)))
    for k, n in sorted(want_all.items()):
        c = cj["cells"].get(k)
        if c is None:
            fail("section 7 cell %s missing in cells_gc.json" % k)
        elif c["n"] != n:
            fail("%s: n %d in section 7, %d in cells_gc.json" % (k, n, c["n"]))
    for k in cj["cells"]:
        if k not in want_all:
            fail("cells_gc.json cell %s is not in section 7" % k)
    # ---- section 3
    r3 = table_rows(section(text, 3))
    keys, key_cells = [], {}
    for cols in r3:
        m = re.search(r"`([a-z0-9_]+)`", cols[-1])
        if not m:
            continue
        keys.append(m.group(1))
        key_cells[m.group(1)] = set(CELLNAME.findall(cols[1]))
    feeds = {}
    for k, c in cj["cells"].items():
        for p in c["preds"]:
            feeds.setdefault(p, set()).add(k)
    for b, spec in cj["regression"]["builds"].items():
        for p in spec["preds"]:
            feeds.setdefault(p, set()).add("regression:" + b)
    for f, spec in cj["cost"]["families"].items():
        feeds.setdefault(spec["search_key"], set()).add("cost:" + f)
    for name, spec in cj["local"].items():
        for p in spec.get("preds", []):
            feeds.setdefault(p, set()).add("local:" + name)
    for k in keys:
        if not feeds.get(k):
            fail("section 3 key %s has no cell in cells_gc.json" % k)
        names = {x.split("@")[0] for x in feeds.get(k, set())}
        for n in sorted(key_cells.get(k, set()) - names):
            fail("section 3 key %s names cell %s, which does not feed it in cells_gc.json" % (k, n))
    for k, c in cj["cells"].items():
        if not c["preds"]:
            fail("cell %s feeds no prediction" % k)
        for p in c["preds"]:
            if p not in keys:
                fail("cell %s feeds %s, which is not a section 3 key" % (k, p))
    for r in rows:
        if not r["preds"] and not r.get("qa_only"):
            fail("section 7 row %d feeds no prediction and says no why (qa_only)" % r["row"])
        for p in r["preds"]:
            if p not in keys:
                fail("row %d names %s, which is not a section 3 key" % (r["row"], p))
    # ---- predictions_gc.csv
    if os.path.exists(a.preds):
        pr = list(csv.DictReader(open(a.preds, encoding="utf-8")))
        ids = [p["id"] for p in pr]
        if sorted(ids) != sorted(keys):
            fail("predictions_gc.csv ids differ from section 3: missing %s, extra %s" %
                 (sorted(set(keys) - set(ids)), sorted(set(ids) - set(keys))))
        # the regression cells: gin-mirror's non-cost cells at the regression builds; "mirror:" names gin-mirror's ids
        reg = cj["regression"]
        src = os.path.join(HERE, reg["source"])
        mcells = json.load(open(src, encoding="utf-8"))
        mnames = {e["cell"] for h in reg["holds"] for e in mcells["holds"].get(h, [])}
        mpreds = os.path.join(os.path.dirname(src), "predictions_mi.csv")
        mids = {r["id"] for r in csv.DictReader(open(mpreds, encoding="utf-8"))}
        for p in pr:
            for k in [x.strip() for x in p["cells"].split(";") if x.strip()]:
                if k.startswith("mirror:"):
                    want, _, b = k[len("mirror:"):].rpartition("@")
                    if b not in reg["builds"]:
                        fail("prediction %s: %s names build %s, not a regression build" % (p["id"], k, b))
                    for i in want.split(","):
                        if i != "all" and i not in mids:
                            fail("prediction %s: %s is not a gin-mirror prediction id" % (p["id"], i))
                elif k.startswith(("build:", "cost:", "local:")):
                    head, _, rest = k.partition(":")
                    ok = {"build": rest in cj["builds"], "cost": rest.split(":")[0] in cj["cost"]["families"],
                          "local": rest in cj["local"]}[head]
                    if not ok:
                        fail("prediction %s names %s, unknown" % (p["id"], k))
                elif "@" in k and k not in cj["cells"]:
                    c, _, b = k.rpartition("@")
                    if not (c in mnames and b in reg["builds"]):
                        fail("prediction %s names cell %s, neither in cells_gc.json nor a regression cell" % (p["id"], k))
    else:
        print("note: %s not found (predictions not checked)" % a.preds)
    qa = [r["row"] for r in rows if r.get("qa_only")]
    print("section 7 rows %d, cells %d, section 3 keys %d, rows without a key (qa_only) %s: %s" %
          (len(r7), len(cj["cells"]), len(keys), qa or "none", "FAIL" if fails else "ok"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
