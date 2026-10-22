#!/usr/bin/env python3
"""check_cells_gc.py - gin-control, test side: cross-check cells_gc.json (and predictions_gc.csv) against ../../EXPERIMENT.md
sections 3 and 7. CPU only, standard library only; reads files, writes nothing.

    check_cells_gc.py [--doc ../../EXPERIMENT.md]

Checks (each failure is one line "FAIL ..."; exit 1 when any):
  section 7   the table rows = cells_gc.json "rows" (in order; 25 since the 2026-10-22 trim, the count is not hard-coded); every row's gc*/gct* cell names and their builds and n (column
              "빌드와 반복 수", parentheses dropped; forms "`@b` n", "`@b` 각 n", "`@b1` n1, `@b2` n2", "`@b` n1, n2" with two
              names) equal the cells of cells_gc.json; no cell in the json outside section 7
  section 3   every search key of the table's last column has at least one cell (a cell@build, the regression, the cost
              family or a local item); every cell of the json feeds at least one key that section 3 names; every gc*/gct*
              cell name in a key's own row feeds that key in the json
  rows        a row without a key must say why (qa_only)
  predictions predictions_gc.csv's ids are exactly section 3's keys, each row's cells column names json cells only; and the
              two lists agree (REVIEW_TEST fix 19): the gc cells a row's cells column names are exactly the json cells whose
              preds name that row (a row on "build:<b>" takes any cell of build b); a regression cell a row names has the row
              in regression.builds[b].preds, and every row of regression.builds[b].preds names a cell, a "mirror:" or a
              "build:" key at that build; a regression build that lists "cells" (the 2026-10-22 trim: @gct runs only
              mi4_kill3_ow) names gin-mirror regression cells only, and a row's regression cell at that build is one of them
  build keys  every build key a cell, a pilot cell, the regression, the cost family, "builds" or a prediction's "build:"
              names is in the document's build-key table (the header table "빌드 키"; a stray gctc fails)
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


def build_key_table(text):
    """the build keys of the first table whose header's first column is 빌드 키"""
    keys, inside = set(), False
    for line in text.splitlines():
        if not line.startswith("|"):
            if inside:
                break
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if not inside:
            inside = cols[0] == "빌드 키"
            continue
        m = re.fullmatch(r"`(\w+)`", cols[0])
        if m:
            keys.add(m.group(1))
    return keys


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
        bcells = {b: set(spec["cells"]) for b, spec in reg["builds"].items() if "cells" in spec}
        for b, cs in sorted(bcells.items()):
            for n in sorted(cs - mnames):
                fail("regression.builds.%s.cells names %s, not a cell of the regression holds" % (b, n))
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
                    elif b in bcells and c not in bcells[b]:
                        fail("prediction %s names cell %s, but regression.builds.%s.cells leaves %s out" % (p["id"], k, b, c))
        # the two lists agree (REVIEW_TEST fix 19)
        for p in pr:
            ks = [x.strip() for x in p["cells"].split(";") if x.strip()]
            named = {k for k in ks if k in cj["cells"]}
            builds = {k.split(":", 1)[1] for k in ks if k.startswith("build:")}
            json_feed = {k for k, c in cj["cells"].items() if p["id"] in c["preds"]}
            if builds:
                for k in sorted(json_feed - named):
                    if cj["cells"][k]["build"] not in builds:
                        fail("prediction %s: cell %s feeds it in cells_gc.json but is not of build %s" % (p["id"], k, sorted(builds)))
            else:
                for k in sorted(json_feed - named):
                    fail("prediction %s: cells_gc.json cell %s feeds it, its cells column does not name it" % (p["id"], k))
            for k in sorted(named - json_feed):
                fail("prediction %s names cell %s, whose preds in cells_gc.json do not name the prediction" % (p["id"], k))
            for k in ks:
                c, _, b = k.rpartition("@")
                if k not in cj["cells"] and "@" in k and not k.startswith("mirror:") and b in reg["builds"]:
                    if p["id"] not in reg["builds"][b]["preds"]:
                        fail("prediction %s names regression cell %s, but regression.builds.%s.preds lacks it" % (p["id"], k, b))
        rows_by_id = {p["id"]: p for p in pr}
        for b, spec in reg["builds"].items():
            for pid in spec["preds"]:
                p = rows_by_id.get(pid)
                if p is None:
                    continue
                ks = [x.strip() for x in p["cells"].split(";") if x.strip()]
                ok = any((k.endswith("@" + b) and k.split("@")[0] in bcells.get(b, mnames)) or (k.startswith("mirror:") and k.endswith("@" + b))
                         or k == "build:" + b for k in ks)
                if not ok:
                    fail("regression.builds.%s.preds names %s, whose cells column names no %s regression cell" % (b, pid, b))
    else:
        print("note: %s not found (predictions not checked)" % a.preds)
    # ---- build keys (the document's build-key table)
    bkeys = build_key_table(text)
    if not bkeys:
        fail("the document has no build-key table (header 빌드 키)")
    used = {}
    for k, c in list(cj["cells"].items()) + list(cj.get("pilot_cells", {}).items()):
        used.setdefault(c["build"], set()).add(k)
        if "@" in k:
            used.setdefault(k.rpartition("@")[2], set()).add(k)
    for b in cj["regression"]["builds"]:
        used.setdefault(b, set()).add("regression.builds")
    for f, spec in cj["cost"]["families"].items():
        for arm, b in spec["lib"].items():
            used.setdefault(b, set()).add("cost.%s.%s" % (f, arm))
    for b, spec in cj["builds"].items():
        used.setdefault(b, set()).add("builds")
        used.setdefault(spec.get("lib", b), set()).add("builds.%s.lib" % b)
    if os.path.exists(a.preds):
        for p in csv.DictReader(open(a.preds, encoding="utf-8")):
            for k in [x.strip() for x in p["cells"].split(";") if x.strip()]:
                if k.startswith("build:"):
                    used.setdefault(k[len("build:"):], set()).add("prediction " + p["id"])
                elif "@" in k and not k.startswith(("mirror:", "cost:", "local:")):
                    used.setdefault(k.rpartition("@")[2], set()).add("prediction " + p["id"])
    for b in sorted(set(used) - bkeys):
        fail("build key %s (used by %s) is not in the document's build-key table %s" % (b, ", ".join(sorted(used[b])[:4]), sorted(bkeys)))
    qa = [r["row"] for r in rows if r.get("qa_only")]
    print("section 7 rows %d, cells %d, section 3 keys %d, build keys %d used of %d in the table, rows without a key (qa_only) %s: %s" %
          (len(r7), len(cj["cells"]), len(keys), len(used), len(bkeys), qa or "none", "FAIL" if fails else "ok"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
