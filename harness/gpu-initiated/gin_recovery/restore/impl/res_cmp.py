#!/usr/bin/env python3
# res_cmp.py <a.res> <b.res>: compare two `cuobjdump -res-usage` dumps (work package 4, design review finding 6): per
# architecture and function, the registers (REG), stack frame (STACK), local memory (LOCAL) and shared memory (SHARED).
# A not inlined function in the call graph can raise a kernel's registers or stack even when the instructions on its
# path are the same. Prints every function whose numbers differ, the functions only in one dump, and a summary line.
import re, sys, collections

def parse(path):
    out = collections.OrderedDict()
    arch, fn = None, None
    for line in open(path, errors='replace'):
        m = re.search(r'arch = (sm_\d+\w*)', line)
        if m:
            arch = m.group(1)
            continue
        m = re.match(r'\s*Function (\S+):', line)
        if m:
            fn = m.group(1)
            continue
        m = re.match(r'\s*REG:(\d+) STACK:(\d+) SHARED:(\d+) LOCAL:(\d+)', line)
        if m and fn is not None:
            out[(arch, fn)] = tuple(int(x) for x in m.groups())
            fn = None
    return out

a, b = parse(sys.argv[1]), parse(sys.argv[2])
same = diff = 0
for k, v in a.items():
    if k not in b:
        continue
    if v == b[k]:
        same += 1
        continue
    diff += 1
    print(f'{k[0]} {k[1]}: REG {v[0]} -> {b[k][0]}, STACK {v[1]} -> {b[k][1]}, SHARED {v[2]} -> {b[k][2]}, '
          f'LOCAL {v[3]} -> {b[k][3]}')
onlyA = [k for k in a if k not in b]
onlyB = [k for k in b if k not in a]
for k in onlyA:
    print(f'only in {sys.argv[1]}: {k[0]} {k[1]} {a[k]}')
for k in onlyB:
    print(f'only in {sys.argv[2]}: {k[0]} {k[1]} {b[k]}')
print(f'resource usage: same {same}, different {diff}, only in the first {len(onlyA)}, only in the second {len(onlyB)}')
