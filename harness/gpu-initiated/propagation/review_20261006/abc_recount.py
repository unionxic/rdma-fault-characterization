import glob, os, re, collections
root = "/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem_rootcause/results/20260924_abc"
res = collections.defaultdict(lambda: [0, 0, [], []])
for cfg in "ABC":
    for p in sorted(glob.glob(f"{root}/{cfg}/*.pe0.log")):
        tag = os.path.basename(p)[:-8]
        fault, wait = tag.split("_")[:2]
        txt = open(p, errors="replace").read()
        err_iter = [l for l in txt.splitlines() if l.startswith("ITER ") and "cqe_opcode=0xd" in l]
        scan_err = [int(m) for m in re.findall(r"^SCAN .* errs=(\d+)", txt, re.M)]
        has = bool(err_iter) or any(s > 0 for s in scan_err)
        k = (cfg, fault, wait)
        res[k][0] += 1
        res[k][1] += has
        if err_iter:
            l = err_iter[0]
            syn = re.search(r"cqe_syndrome=(\S+)", l).group(1); ven = re.search(r"cqe_vendor_err=(\S+)", l).group(1)
            wq = re.search(r"cqe_wqe_counter=(\d+)", l).group(1); dt = re.search(r"dt_ms=(\S+)", l).group(1)
            res[k][2].append(f"{syn}/{ven}@{wq} {dt}ms")
for k in sorted(res):
    n, e, s, _ = res[k]
    print(k, f"{e}/{n}", s)
tot = collections.Counter()
for (cfg, f, w), (n, e, _, _) in res.items():
    kind = "none" if f == "none" else "fault"
    tot[(cfg, kind, "n")] += n; tot[(cfg, kind, "e")] += e
print(dict(tot))
