import glob, gzip, re, os, collections
root = "/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem_ft/results/b2"
truth = {"F1": "LOCAL_QP_ERR", "F2b": "REM_ACCESS", "F3": "RETRY_EXC", "F4": "RETRY_EXC"}
cnt = collections.Counter(); fin = collections.Counter(); mbx = []
for d in ["classify", "recover"]:
    for p in sorted(glob.glob(f"{root}/{d}/*.pe0.log.gz")):
        tag = os.path.basename(p)[:-11]; fault = tag.split("_")[0]
        if fault == "none": continue
        L = gzip.open(p, "rt", errors="replace").read().splitlines()
        rec = [l for l in L if "device-classified error CQE seq=1 " in l]
        cls = re.search(r"class=(\S+)", rec[0]).group(1) if rec else None
        ok = cls == truth.get(fault)
        cnt[(d, ok)] += 1
        fr = [l for l in L if l.startswith("FAULTREC") and "round=0" in l]
        if fr and d == "classify":
            kv = dict(re.findall(r"(\w+)=(\S+)", fr[0]))
            mbx.append((float(kv["t_mbx"]) - float(kv["t_dev"])) * 1000)
print(cnt)
mbx.sort(); print("dev->mbx us (classify) n=", len(mbx), "median", mbx[len(mbx)//2], "min", mbx[0], "max", mbx[-1])
# flagoff
for p in sorted(glob.glob(f"{root}/flagoff/*.pe0.log.gz")):
    L = gzip.open(p, "rt", errors="replace").read()
    m = open(p.replace(".pe0.log.gz", ".meta")).read()
    print(os.path.basename(p), re.findall(r"pe0_rc=\S+|pe1_rc=\S+", m)[:2], len(re.findall("device-classified", L)))
