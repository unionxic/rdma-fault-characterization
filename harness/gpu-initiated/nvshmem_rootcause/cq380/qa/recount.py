#!/usr/bin/env python3
"""qa/recount.py [results_dir] - independent recount of the cq380 main run from the raw files.

Written for QA without reading score.py, SCORE.md or trials_scored.csv. Inputs, per trial tag
<stock|fix>_<gpu|cpu_host_memory>_kill<0|1>_t<n>:
  <tag>.pe0.log      program output of PE 0 (CQSCAN prep/result lines, iteration lines)
  <tag>.pe1.log      program output of PE 1 (only the last signal is used)
  <tag>.row          run.sh result row (compared with trials.csv)
  <tag>.cudagdb.txt  cuda-gdb x/<n>xb of each CQ buffer; decoded here byte by byte
  <tag>.cqdump.txt   the authors' decode; read only to compare with this decode
plus trials.csv and run_all.out. Default results_dir: ../results/20261007 next to this file.

CQE (mlx5, 64 bytes): byte 63 op_own, opcode = byte63 >> 4 (0xf never written, 0x0 requester
success, 0xd requester error, 0xe responder error); byte 55 syndrome, byte 54 vendor syndrome
(meaningful for error CQEs only); bytes 57-59 QP number; bytes 60-61 wqe_counter (big-endian).
"""
import collections
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "results", "20261007"))
SLOW_MS = 100.0  # an iteration slower than this is "slow" (normal iterations take 1-3 ms)

CELLS = [  # (cell id, variant, handler, kill)
    ("C1", "stock", "cpu_host_memory", 1),
    ("C2", "stock", "gpu", 1),
    ("C3", "fix", "cpu_host_memory", 1),
    ("C4-cpu", "stock", "cpu_host_memory", 0),
    ("C4-gpu", "stock", "gpu", 0),
]
TRIALS = range(1, 6)
OPNAME = {0x0: "REQ (success)", 0x1: "RESP_WR_IMM", 0x2: "RESP_SEND", 0x3: "RESP_SEND_IMM",
          0x4: "RESP_SEND_INV", 0x5: "RESIZE_CQ", 0xd: "REQ_ERR", 0xe: "RESP_ERR", 0xf: "INVALID"}
TAG_RE = re.compile(r"^((stock|fix)_(gpu|cpu_host_memory)_kill([01])_t(\d+))\.(.+)$")

problems = []  # consistency failures (strings)


def check(cond, msg):
    if not cond:
        problems.append(msg)
    return cond


def tag_of(v, h, k, t):
    return f"{v}_{h}_kill{k}_t{t}"


# ---------------------------------------------------------------- pe0.log / pe1.log
def parse_pe0(path):
    d = dict(handler=None, prep=[], prep_n=None, iters={}, hang=None, kernel_failed=None,
             all_returned=None, scan=[], summary=None, failed=None, hold=None, pids=collections.Counter(),
             last_pe0_line=None, n_lines=0)
    with open(path, errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            d["n_lines"] += 1
            for m in re.finditer(r"\brain:(\d+):", line):
                d["pids"][int(m.group(1))] += 1
            if line.startswith("PE 0 "):
                d["last_pe0_line"] = line
            m = re.search(r"NIC handler will be ([^.]*)\.", line)
            if m and d["handler"] is None:
                d["handler"] = m.group(1)
            m = re.match(r"CQSCAN prep queues=(\d+) dcis=(\d+)$", line)
            if m:
                d["prep_n"] = (int(m.group(1)), int(m.group(2)))
                continue
            m = re.match(r"CQSCAN prep cq=(\d+) type=(\w+) qpn=0x([0-9a-f]+) ncqes=(\d+) cqe=(0x[0-9a-f]+) "
                         r"ptr_type=(-?\d+) host_ptr=(\w+)$", line)
            if m:
                d["prep"].append(dict(cq=int(m.group(1)), type=m.group(2), qpn=int(m.group(3), 16),
                                      ncqes=int(m.group(4)), addr=int(m.group(5), 16),
                                      ptr_type=int(m.group(6)), host_ptr=m.group(7)))
                continue
            m = re.match(r"PE 0 iter (\d+): put \+ signal \+ nvshmem_quiet\(\) returned after ([0-9.]+) ms$", line)
            if m:
                i = int(m.group(1))
                check(i not in d["iters"], f"{path}: iteration {i} printed twice")
                d["iters"][i] = float(m.group(2))
                continue
            m = re.match(r"PE 0 iter (\d+): nvshmem_quiet\(\) has not returned after (\d+) s", line)
            if m:
                d["hang"] = (int(m.group(1)), int(m.group(2)))
                continue
            m = re.match(r"PE 0 iter (\d+): kernel failed: (.*)$", line)
            if m:
                d["kernel_failed"] = (int(m.group(1)), m.group(2))
                continue
            m = re.match(r"PE 0: all (\d+) iterations returned", line)
            if m:
                d["all_returned"] = int(m.group(1))
                continue
            m = re.match(r"CQSCAN cq=(\d+) type=(\w+) qpn=0x([0-9a-f]+) ncqes=(\d+) valid=(\d+) err=(\d+)"
                         r"(?: first_err_at=(\d+) syndrome=0x([0-9a-f]+) vendor=0x([0-9a-f]+))?"
                         r" last_opcode=0x([0-9a-f]+)$", line)
            if m:
                g = m.groups()
                d["scan"].append(dict(cq=int(g[0]), type=g[1], qpn=int(g[2], 16), ncqes=int(g[3]),
                                      valid=int(g[4]), err=int(g[5]),
                                      first_err_at=None if g[6] is None else int(g[6]),
                                      synd=None if g[7] is None else int(g[7], 16),
                                      vend=None if g[8] is None else int(g[8], 16),
                                      last_op=int(g[9], 16)))
                continue
            m = re.match(r"CQSCAN queues=(\d+) total_err=(\d+) path=(\S+)$", line)
            if m:
                check(d["summary"] is None, f"{path}: more than one CQSCAN summary")
                d["summary"] = (int(m.group(1)), int(m.group(2)), m.group(3))
                continue
            m = re.match(r"CQSCAN failed: (.*)$", line)
            if m:
                d["failed"] = m.group(1)
                continue
            m = re.match(r"CQSCAN hold (\d+) s", line)
            if m:
                d["hold"] = int(m.group(1))
                continue
            if line.startswith("CQSCAN"):
                problems.append(f"{path}: unparsed CQSCAN line: {line}")
    return d


def parse_pe1(path):
    last = None
    nosig = None
    with open(path, errors="replace") as f:
        for line in f:
            m = re.match(r"PE 1 iter (\d+): signal arrived", line)
            if m:
                last = int(m.group(1))
            m = re.match(r"PE 1 iter (\d+): no signal", line)
            if m:
                nosig = int(m.group(1))
    return last, nosig


# ---------------------------------------------------------------- cuda-gdb dump
def parse_cudagdb(path, prep_by_cq):
    """Return dict(blocks={cq: info}, rc, pid, stop) with each CQ buffer decoded from the x/xb text."""
    out = dict(blocks={}, rc=None, pid=None, stop=None, stray=[])
    cur = None
    with open(path, errors="replace") as f:
        lines = f.read().split("\n")
    for ln, line in enumerate(lines, 1):
        m = re.match(r"CQBEGIN (\d+)$", line)
        if m:
            check(cur is None, f"{path}:{ln}: CQBEGIN inside a block")
            cur = dict(cq=int(m.group(1)), addrs=[], data=bytearray(), bad=[], begin=ln)
            continue
        m = re.match(r"CQEND (\d+)$", line)
        if m:
            check(cur is not None and cur["cq"] == int(m.group(1)), f"{path}:{ln}: CQEND without matching CQBEGIN")
            if cur is not None:
                cur["end"] = ln
                out["blocks"][cur["cq"]] = cur
            cur = None
            continue
        if cur is not None:
            m = re.match(r"^(0x[0-9a-f]+):((?:\t0x[0-9a-f]{2})+)$", line)
            if m:
                bs = [int(x, 16) for x in m.group(2).split("\t")[1:]]
                cur["addrs"].append((int(m.group(1), 16), len(bs)))
                cur["data"].extend(bs)
            else:
                cur["bad"].append((ln, line))
            continue
        m = re.match(r"cudagdb_rc (\d+)$", line)
        if m:
            out["rc"] = int(m.group(1))
        m = re.match(r"\[Inferior \d+ \(process (\d+)\) detached\]", line)
        if m:
            out["pid"] = int(m.group(1))
        m = re.match(r"0x[0-9a-f]+ in (.*) \(\)$", line)
        if m and out["stop"] is None:
            out["stop"] = m.group(1)
        if line.strip() and not line.startswith(("[", "Thread ", "Using host", "0x", "cudagdb_rc")):
            out["stray"].append((ln, line))
    check(cur is None, f"{path}: block {cur and cur['cq']} not closed")

    for cq, b in out["blocks"].items():
        p = prep_by_cq.get(cq)
        b["type"] = p["type"] if p else "?"
        b["qpn_expected"] = p["qpn"] if p else None
        b["nbytes"] = len(b["data"])
        b["expect_bytes"] = p["ncqes"] * 64 if p else None
        # addresses: first = prep cqe address, 8 bytes per line, contiguous
        contiguous = all(n == 8 for _, n in b["addrs"]) and all(
            a == b["addrs"][0][0] + 8 * k for k, (a, _) in enumerate(b["addrs"]))
        b["contiguous"] = contiguous
        b["start_ok"] = bool(p) and bool(b["addrs"]) and b["addrs"][0][0] == p["addr"]
        cqes = []
        odd_unwritten = 0
        data = b["data"]
        for j in range(len(data) // 64):
            e = data[64 * j:64 * j + 64]
            op = e[63] >> 4
            if op == 0xf:
                if any(x != 0xff for x in e):
                    odd_unwritten += 1
                continue
            cqes.append(dict(slot=j, op=op, owner=e[63] & 1, wqe_counter=(e[60] << 8) | e[61],
                             qpn=(e[57] << 16) | (e[58] << 8) | e[59], b56=e[56], synd=e[55], vend=e[54],
                             sig=e[62]))
        b["cqes"] = cqes
        b["odd_unwritten"] = odd_unwritten
        b["valid"] = len(cqes)
        errs = [c for c in cqes if c["op"] in (0xd, 0xe)]
        b["err"] = len(errs)
        b["first_err"] = errs[0] if errs else None
        b["last_op"] = cqes[-1]["op"] if cqes else 0
    return out


def parse_cqdump(path):
    qs, summ = {}, None
    with open(path, errors="replace") as f:
        for line in f:
            m = re.match(r"CQSCAN cq=(\d+) type=(\w+) bytes=(\d+) valid=(\d+) err=(\d+)"
                         r"(?: first_err_at=(\d+) syndrome=0x([0-9a-f]+) vendor=0x([0-9a-f]+))?"
                         r" last_opcode=0x([0-9a-f]+)", line)
            if m:
                g = m.groups()
                qs[int(g[0])] = dict(type=g[1], bytes=int(g[2]), valid=int(g[3]), err=int(g[4]),
                                     synd=None if g[6] is None else int(g[6], 16),
                                     vend=None if g[7] is None else int(g[7], 16), last_op=int(g[8], 16))
            m = re.match(r"CQSCAN queues=(\d+) total_err=(\d+) path=(\S+)", line)
            if m:
                summ = (int(m.group(1)), int(m.group(2)), m.group(3))
    return qs, summ


# ---------------------------------------------------------------- main
def main():
    files = sorted(os.listdir(RES))
    found = collections.defaultdict(set)
    other = []
    for fn in files:
        m = TAG_RE.match(fn)
        if m:
            found[m.group(1)].add(m.group(6))
        else:
            other.append(fn)
    expected = [tag_of(v, h, k, t) for t in TRIALS for _, v, h, k in CELLS]
    check(len(set(expected)) == 25, "expected set is not 25 tags")
    missing = [t for t in expected if t not in found]
    extra = [t for t in found if t not in expected]
    check(not missing, f"missing trials: {missing}")
    check(not extra, f"unexpected trial tags in results dir: {extra}")
    for t in expected:
        for ext in ("pe0.log", "pe1.log", "row", "runner.err"):
            check(ext in found.get(t, ()), f"{t}: no .{ext}")

    # trials.csv
    rows = list(csv.reader(open(os.path.join(RES, "trials.csv"))))
    check(len(rows) == 25, f"trials.csv has {len(rows)} rows, expected 25")
    keys = [tag_of(r[0], r[1], r[2], r[3]) for r in rows]
    check(len(set(keys)) == len(keys), "trials.csv has duplicate keys")
    check(set(keys) == set(expected), f"trials.csv keys differ: {set(keys) ^ set(expected)}")
    csv_by_tag = dict(zip(keys, rows))
    for r in rows:
        check(len(r) == 11, f"trials.csv row with {len(r)} fields: {r[:4]}")

    # run_all.out
    ra = open(os.path.join(RES, "run_all.out")).read() if os.path.exists(os.path.join(RES, "run_all.out")) else ""
    done = re.findall(r"^(stock|fix) (gpu|cpu_host_memory) kill([01]) t(\d+) done", ra, re.M)
    done_tags = [tag_of(*x) for x in done]
    check(sorted(done_tags) == sorted(expected), f"run_all.out done lines differ from expected set ({len(done_tags)})")

    trials = {}
    for cell, v, h, k in CELLS:
        for t in TRIALS:
            tag = tag_of(v, h, k, t)
            base = os.path.join(RES, tag)
            p0 = parse_pe0(base + ".pe0.log")
            pe1_last, pe1_nosig = parse_pe1(base + ".pe1.log")
            prep_by_cq = {p["cq"]: p for p in p0["prep"]}
            tr = dict(cell=cell, tag=tag, trial=t, p0=p0, pe1_last=pe1_last, pe1_nosig=pe1_nosig)
            # iterations
            its = p0["iters"]
            tr["n_returned"] = len(its)
            check(sorted(its) == list(range(len(its))), f"{tag}: returned iterations not contiguous from 0")
            slow = [(i, ms) for i, ms in sorted(its.items()) if ms > SLOW_MS]
            tr["slow"] = slow
            tr["max_normal_ms"] = max([ms for i, ms in its.items() if ms <= SLOW_MS] or [0])
            tr["hang"] = p0["hang"]
            # read path
            if p0["summary"] is not None:
                tr["path"] = p0["summary"][2]
            elif p0["failed"] is not None:
                tr["path"] = "own scan failed"
            else:
                tr["path"] = "no scan output"
            # kernel-path self-consistency
            if p0["summary"]:
                nq, tot, _ = p0["summary"]
                check(nq == len(p0["scan"]), f"{tag}: summary queues={nq} but {len(p0['scan'])} cq lines")
                check(tot == sum(q["err"] for q in p0["scan"]), f"{tag}: total_err differs from sum of err")
                usable = [p for p in p0["prep"]]
                check([(q["type"], q["qpn"], q["ncqes"]) for q in p0["scan"]] ==
                      [(p["type"], p["qpn"], p["ncqes"]) for p in usable],
                      f"{tag}: kernel scan queues do not match prep lines (type, qpn, ncqes)")
            # queues used for scoring
            q_kernel = None
            if p0["summary"] and p0["summary"][2] == "kernel":
                q_kernel = [dict(type=q["type"], qpn=q["qpn"], valid=q["valid"], err=q["err"], synd=q["synd"],
                                 vend=q["vend"], last_op=q["last_op"], cqes=None) for q in p0["scan"]]
            q_gdb = None
            tr["gdb"] = None
            if "cudagdb.txt" in found[tag]:
                g = parse_cudagdb(base + ".cudagdb.txt", prep_by_cq)
                tr["gdb"] = g
                ok = (g["rc"] == 0 and set(g["blocks"]) == set(prep_by_cq) and
                      all(b["nbytes"] == b["expect_bytes"] == 1024 * 64 and b["contiguous"] and b["start_ok"]
                          and not b["bad"] for b in g["blocks"].values()))
                check(g["rc"] == 0, f"{tag}: cudagdb_rc {g['rc']}")
                check(set(g["blocks"]) == set(prep_by_cq), f"{tag}: cuda-gdb blocks {sorted(g['blocks'])} "
                      f"!= prep cqs {sorted(prep_by_cq)}")
                for cq, b in g["blocks"].items():
                    check(b["nbytes"] == 65536, f"{tag} cq{cq}: {b['nbytes']} bytes, expected 65536")
                    check(b["contiguous"], f"{tag} cq{cq}: addresses not contiguous 8-byte lines")
                    check(b["start_ok"], f"{tag} cq{cq}: first address differs from prep cqe address")
                    check(not b["bad"], f"{tag} cq{cq}: {len(b['bad'])} non-data lines inside block")
                    check(b["odd_unwritten"] == 0, f"{tag} cq{cq}: {b['odd_unwritten']} slots with opcode 0xf "
                          f"but not all-0xff bytes")
                    for c in b["cqes"]:
                        check(c["qpn"] == b["qpn_expected"], f"{tag} cq{cq} slot {c['slot']}: CQE qpn "
                              f"0x{c['qpn']:x} != queue qpn 0x{b['qpn_expected']:x}")
                check(g["pid"] in p0["pids"], f"{tag}: cuda-gdb pid {g['pid']} not in pe0.log NVSHMEM lines")
                check(g["stray"] == [], f"{tag}: unexpected lines in cudagdb.txt: {g['stray'][:3]}")
                if ok:
                    q_gdb = [dict(type=b["type"], qpn=b["qpn_expected"], valid=b["valid"], err=b["err"],
                                  synd=b["first_err"]["synd"] if b["first_err"] else None,
                                  vend=b["first_err"]["vend"] if b["first_err"] else None,
                                  last_op=b["last_op"], cqes=b["cqes"])
                             for cq, b in sorted(g["blocks"].items())]
                # authors' decode: compare only
                if "cqdump.txt" in found[tag]:
                    cd, cs = parse_cqdump(base + ".cqdump.txt")
                    tr["cqdump"] = (cd, cs)
                    for cq, b in g["blocks"].items():
                        a = cd.get(cq)
                        if check(a is not None, f"{tag}: cqdump has no cq={cq}"):
                            mine = (b["type"], b["nbytes"], b["valid"], b["err"],
                                    b["first_err"]["synd"] if b["first_err"] else None,
                                    b["first_err"]["vend"] if b["first_err"] else None, b["last_op"])
                            theirs = (a["type"], a["bytes"], a["valid"], a["err"], a["synd"], a["vend"], a["last_op"])
                            check(mine == theirs, f"{tag} cq{cq}: cqdump {theirs} != recount {mine}")
                    check(cs == (len(g["blocks"]), sum(b["err"] for b in g["blocks"].values()), "cuda-gdb"),
                          f"{tag}: cqdump summary {cs} differs from recount")
                    check(csv_by_tag[tag][10] == "CQSCAN queues=%d total_err=%d path=%s" % cs if cs else False,
                          f"{tag}: trials.csv dump column differs from cqdump last line")
            else:
                check(csv_by_tag[tag][10] == "none", f"{tag}: trials.csv dump column is not 'none'")
            check(not (q_kernel and q_gdb), f"{tag}: both a kernel scan and a cuda-gdb read")
            check(p0["failed"] is None or "cudagdb.txt" in found[tag], f"{tag}: own scan failed, no cuda-gdb read")
            tr["q_a"] = q_kernel if q_kernel is not None else q_gdb
            tr["src_a"] = "kernel" if q_kernel is not None else ("cuda-gdb" if q_gdb is not None else None)
            tr["q_b"] = q_kernel
            # trials.csv / .row cross-check
            r = csv_by_tag[tag]
            row = next(csv.reader([open(base + ".row").read().strip()]))
            check(row == r[:10], f"{tag}: .row differs from trials.csv")
            check(r[4] == p0["handler"], f"{tag}: handler_log '{r[4]}' != log '{p0['handler']}'")
            check(r[9] == p0["last_pe0_line"], f"{tag}: pe0_last differs from the log's last 'PE 0 ' line")
            exp_rc = "3" if p0["hang"] else "0"
            check(r[6] == exp_rc, f"{tag}: pe0_rc {r[6]}, expected {exp_rc}")
            check((r[5] != "-") == bool(k), f"{tag}: kill_at '{r[5]}' inconsistent with kill={k}")
            tr["csv"] = r
            check(os.path.getsize(base + ".runner.err") == 0, f"{tag}: runner.err not empty")
            trials[tag] = tr
    return trials, other, done_tags


def rc_queues(q):
    return [x for x in q if x["type"] == "rc"]


def judge(cell, q):
    """Return 'pass', 'fail' or 'n/o' (not observable) for one trial's queue list (None = no read)."""
    if q is None:
        return "n/o"
    tot_err = sum(x["err"] for x in q)
    rc = rc_queues(q)
    if cell == "C1":
        if sum(x["valid"] for x in rc) == 0:
            return "n/o"  # section 8: no valid CQE in the RC queue = not read properly
        return "pass" if tot_err == 0 and sum(x["valid"] for x in rc) >= 1 else "fail"
    if cell in ("C2", "C3"):
        return "pass" if sum(x["err"] for x in rc) >= 1 else "fail"
    return "pass" if tot_err == 0 else "fail"


def verdict(js):
    n = len(js)
    obs = [j for j in js if j != "n/o"]
    p = sum(j == "pass" for j in js)
    f = sum(j == "fail" for j in js)
    if f:
        v = "WRONG"
    elif p == n:
        v = "as predicted"
    else:
        v = "not decidable"
    return f"{p}/{n} pass, {f} fail, {n - len(obs)} not observable: {v}"


def fmt_q(q):
    if q is None:
        return "-"
    parts = []
    for x in q:
        s = f"{x['type']} {x['valid']}/{x['err']}"
        if x["err"]:
            s += f" (synd 0x{x['synd']:02x} vend 0x{x['vend']:02x})"
        parts.append(s)
    return "; ".join(parts)


if __name__ == "__main__":
    trials, other, done_tags = main()
    print(f"results dir: {RES}")
    print(f"non-trial files: {other}")
    smoke = os.path.join(os.path.dirname(RES), os.path.basename(RES) + "_smoke")
    if os.path.isdir(smoke):
        print(f"smoke dir exists (not scored): {smoke}, {len(os.listdir(smoke))} files")
    print("\n## per trial (queue: written/error CQEs)")
    print("| cell | trial | read path | DCI | RC | PE 0 wait | slow iteration | PE 1 last signal | kill_at |")
    print("|---|--:|---|---|---|---|---|--:|---|")
    for tag, tr in trials.items():
        q = tr["q_a"]
        dci = fmt_q([x for x in q if x["type"] == "dci"]) if q else "-"
        rc = fmt_q(rc_queues(q)) if q else "-"
        path = tr["path"] + ("" if tr["src_a"] != "cuda-gdb" else ", cuda-gdb read")
        wait = (f"hung at iter {tr['hang'][0]} (not returned after {tr['hang'][1]} s)" if tr["hang"]
                else f"all {tr['p0']['all_returned']} returned")
        slow = ", ".join(f"iter {i}: {ms:.1f} ms" for i, ms in tr["slow"]) or "none"
        print(f"| {tr['cell']} | {tr['trial']} | {path} | {dci} | {rc} | {wait} | {slow} "
              f"(others max {tr['max_normal_ms']:.1f} ms) | {tr['pe1_last']} | {tr['csv'][5]} |")

    print("\n## per CQE, cuda-gdb trials")
    print("| trial | queue (slot) | qpn | bytes | CQE slot | opcode | wqe_counter | owner | cudagdb_rc | stopped in |")
    print("|---|---|---|--:|--:|---|--:|--:|--:|---|")
    for tag, tr in trials.items():
        g = tr["gdb"]
        if not g:
            continue
        for cq, b in sorted(g["blocks"].items()):
            for c in b["cqes"] or [None]:
                cs = (f"{c['slot']} | 0x{c['op']:x} {OPNAME.get(c['op'], '?')} | {c['wqe_counter']} | {c['owner']}"
                      if c else "none | - | - | -")
                print(f"| {tag} | {b['type']} (cq={cq}) | 0x{b['qpn_expected']:x} | {b['nbytes']} | {cs} | "
                      f"{g['rc']} | {g['stop']} |")

    print("\n## per cell")
    print("| cell | n | (a) cuda-gdb read substituted | (b) section 8 literal |")
    print("|---|--:|---|---|")
    for cell, *_ in CELLS:
        trs = [tr for tr in trials.values() if tr["cell"] == cell]
        ja = [judge(cell, tr["q_a"]) for tr in trs]
        jb = [judge(cell, tr["q_b"]) for tr in trs]
        print(f"| {cell} | {len(trs)} | {verdict(ja)} | {verdict(jb)} |")

    first_errs = collections.Counter()
    for tr in trials.values():
        for x in tr["q_a"] or []:
            if x["err"]:
                first_errs[(tr["cell"], x["type"], x["synd"], x["vend"])] += 1
    print("\nfirst error (cell, queue, syndrome, vendor): count")
    for k, v in sorted(first_errs.items()):
        print(f"  {k[0]} {k[1]} 0x{k[2]:02x} 0x{k[3]:02x}: {v}")
    ctr = collections.Counter(tr["csv"][8] for tr in trials.values())
    print(f"\ntrials.csv counter-delta column values: {dict(ctr)}")
    print(f"run_all.out done lines: {len(done_tags)}")
    print("\n## consistency checks")
    if problems:
        for p in problems:
            print("FAIL", p)
    else:
        print("all checks passed")
