import glob, re, collections
root = "/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem_rootcause/results/20260924"
c = collections.Counter(); qperr = collections.Counter(); nosum = 0; evcount = collections.Counter()
for p in sorted(glob.glob(f"{root}/b[1-4]/*.req.log")):
    txt = open(p, errors="replace").read()
    s = [l for l in txt.splitlines() if l.startswith("SUMMARY")]
    if not s: nosum += 1; continue
    kv = dict(re.findall(r"(\w+)=(\S+)", s[-1]))
    if kv["fault"] == "none": c["none"] += 1; continue
    word = 1 if kv["dbr1"] != "0" else 0
    # raw cross-check: any EV line reporting an error CQE (opcode 0xd/0xe)
    ev_err = len(re.findall(r"^EV .*what=cqe\S* .*op=0x(?:d|e)\b", txt, re.M))
    c[(word, "err" if kv["err_cqe"] != "0" else "noerr")] += 1
    qperr[(word, kv["qp_state_final"])] += 1
    evcount[(word, ev_err > 0)] += 1
print("nosummary", nosum); print(c); print(qperr); print("EV-based", evcount)
