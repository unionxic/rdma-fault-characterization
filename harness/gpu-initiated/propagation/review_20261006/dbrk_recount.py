import glob, re, collections, os
root = "/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem_rootcause/results/20260925_dbrk"
tot = collections.Counter(); bad = []
for s in ["s1", "s2", "s3", "s5", "s4"]:
    for p in sorted(glob.glob(f"{root}/{s}/*.req.log")):
        L = open(p, errors="replace").read().splitlines()
        sm = [l for l in L if l.startswith("SUMMARY")]
        kv = dict(re.findall(r"(\w+)=(\S+)", sm[-1]))
        rung = [l for l in L if "what=kbatch_rung" in l][0]
        rk = dict(re.findall(r"(\w+)=(\S+)", rung))
        pib, pi, P = int(rk["pi_before"]), int(rk["pi"]), int(rk["dbr_val"])
        c = pib if kv["fault"] == "kerr" else pib + int(kv["kbad"])
        # error CQEs (op 0xd) after the batch was rung, dedup by wqe (torn re-reads)
        errs = {}
        seen_rung = False
        for l in L:
            if "what=kbatch_rung" in l: seen_rung = True
            if seen_rung and "what=cqe" in l and "op=0xd" in l:
                e = dict(re.findall(r"(\w+)=(\S+)", l)); errs.setdefault(int(e["wqe"]), (e["syndrome"], e["vendor"]))
        late = int(kv.get("klate_ms", "-1")) >= 0
        if late:
            tot["s4"] += 1
            # at transition P=c; after late write, expect [c,pi)
            ok = sorted(errs) == list(range(c, pi))
            tot["s4_ok"] += ok
            continue
        exp = list(range(c, P)) if P > c else []
        ok = sorted(errs) == exp
        sw = int(kv["sw_sq"]) == P
        tot["n"] += 1; tot["ok"] += ok; tot["sw_end"] += sw
        if P <= c: tot["P<=c"] += 1; tot["P<=c_ok"] += ok
        if not ok: bad.append((p, c, P, sorted(errs)))
print(dict(tot)); print(bad[:5])
