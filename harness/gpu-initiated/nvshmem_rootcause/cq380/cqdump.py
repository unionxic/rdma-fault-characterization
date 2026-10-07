#!/usr/bin/env python3
"""cqdump.py <pe0.log> <cudagdb.txt> - decode the CQ buffers that trace_trial.sh read with cuda-gdb.

Each queue appears between "CQBEGIN <i>" and "CQEND <i>" as cuda-gdb x/xb output (8 bytes per line).
Prints one CQSCAN-style line per queue, in the same form as the program's own scan, and a summary.
opcode = op_own >> 4 (byte 63 of each 64-byte CQE): 0xf never written, 0xd REQ_ERR, 0xe RESP_ERR;
syndrome at byte 55, vendor syndrome at byte 54.
"""
import re, sys

log = open(sys.argv[1], errors="replace").read()
types = {m.group(1): m.group(2) for m in re.finditer(r"CQSCAN prep cq=(\d+) type=(\w+)", log)}
gdb = open(sys.argv[2], errors="replace").read()
total = n = 0
for m in re.finditer(r"CQBEGIN (\d+)\n(.*?)CQEND \1", gdb, re.S):
    i, body = m.group(1), m.group(2)
    b = bytes(int(x, 16) for x in re.findall(r"\t0x([0-9a-f]{2})", body))
    valid = err = 0
    first = None
    last = 0
    for j in range(len(b) // 64):
        e = b[64 * j:64 * j + 64]
        op = e[63] >> 4
        if op == 0xf:
            continue
        valid += 1
        last = op
        if op in (0xd, 0xe):
            if first is None:
                first = (j, e[55], e[54])
            err += 1
    line = f"CQSCAN cq={i} type={types.get(i, '?')} bytes={len(b)} valid={valid} err={err}"
    if first:
        line += f" first_err_at={first[0]} syndrome=0x{first[1]:02x} vendor=0x{first[2]:02x}"
    print(line + f" last_opcode=0x{last:x}")
    total += err
    n += 1
print(f"CQSCAN queues={n} total_err={total} path=cuda-gdb")
