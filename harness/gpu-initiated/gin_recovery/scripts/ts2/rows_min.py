#!/usr/bin/env python3
"""gin_bidir_min trial logs -> one CSV row per trial. usage: rows_min.py <logdir> --out trials_min.csv
Per direction (A = rank 0 -> rank 1, B = rank 1 -> rank 0): the sender's tx_done/tx_rc, the receiver's rx_done,
host bad/missing slots and final signal, plus the Q4 error records (class, wqe, reporting rank) of both ranks."""
import argparse, csv, glob, os, re, sys


def kvfile(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, errors="replace"):
        for m in re.finditer(r"(\w+)=(.*?)(?= \w+=|$)", line.rstrip("\n")):
            d[m.group(1)] = m.group(2).strip()
    return d


def q4(path):
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, errors="replace"):
        if "device-classified error CQE" in line:
            d = dict(re.findall(r"(\w+)=(\S+)", line))
            out.append("%s:wqe%s:%s" % (d.get("rank"), d.get("wqe"), d.get("class")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = []
    for d in a.dirs:
        for meta in sorted(glob.glob(os.path.join(d, "*_meta.txt"))):
            stem = meta[: -len("_meta.txt")]
            m = kvfile(meta)
            k = {0: kvfile(stem + "_r0.kv"), 1: kvfile(stem + "_r1.kv")}
            iters = int(m.get("iters", "0"))
            r = {"cell": m.get("cell"), "trial": m.get("trial"), "build": m.get("build"), "mode": m.get("mode"),
                 "bytes": m.get("bytes"), "iters": iters, "same_ctx": m.get("same_ctx"), "r0rc": m.get("r0rc"),
                 "r1rc": m.get("r1rc"), "wall_s": m.get("wall_s"), "left": m.get("left"),
                 "r0env": m.get("r0env"), "r1env": m.get("r1env")}
            ok = True
            for dname, snd, rcv in (("A", 0, 1), ("B", 1, 0)):
                ks, kr = k[snd], k[rcv]
                ran = ks.get("tx_dir") is not None or kr.get("rx_dir") is not None
                r[dname + "_ran"] = int(ran)
                r[dname + "_tx_done"] = ks.get("tx_done")
                r[dname + "_tx_rc"] = ks.get("tx_rc")
                r[dname + "_rx_done"] = kr.get("rx_done")
                r[dname + "_rx_rc"] = kr.get("rx_rc")
                r[dname + "_host_bad"] = kr.get("host_bad_slots")
                r[dname + "_host_missing"] = kr.get("host_missing_slots")
                r[dname + "_first_bad"] = kr.get("host_first_bad")
                r[dname + "_final_signal"] = kr.get("final_signal")
                r[dname + "_signal_exact"] = kr.get("signal_exact")
                r[dname + "_final_signal"] = kr.get("final_signal")
                r[dname + "_tx_kernel_end_ms"] = ks.get("tx_kernel_end_ms")
                r[dname + "_rx_kernel_end_ms"] = kr.get("rx_kernel_end_ms")
                if ran:
                    good = (ks.get("tx_done") in (None, str(iters))) and (ks.get("tx_rc") in (None, "no error")) and \
                           kr.get("rx_rc") in (None, "no error") and kr.get("host_bad_slots") == "0" and kr.get("signal_exact") == "1"
                    r[dname + "_ok"] = int(good)
                    ok = ok and good
            r["ok"] = int(ok)
            r["q4"] = ";".join(q4(stem + "_r0.log") + q4(stem + "_r1.log"))
            rows.append(r)
    keys = []
    for r in rows:
        for x in r:
            if x not in keys:
                keys.append(x)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"{len(rows)} trials", file=sys.stderr)


if __name__ == "__main__":
    main()
