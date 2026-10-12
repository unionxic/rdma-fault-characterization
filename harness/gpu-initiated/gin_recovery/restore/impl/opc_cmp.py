#!/usr/bin/env python3
# opc_cmp.py <a.sass> <b.sass>: per function (architecture, name), the instructions only in a and only in b as a multiset
# of opcodes (the mnemonic with its modifiers, predicate guard kept as "@P"), for large kernels where a line alignment is
# too slow (the dev branch's work package 4 redone: NCCL's symmetric GIN kernels in the library, built without the device
# restore path, against hk's). Expected without the macro: per call site one more 64-bit load, compares and a predicated
# trap; nothing else added or removed. Also prints the line count of each function. Exit 0 always.
import collections, re, sys

def parse(path):
    funcs = collections.OrderedDict()
    arch = name = None
    for line in open(path, errors='replace'):
        m = re.match(r'\s*code for (sm_\d+\w*)', line)
        if m:
            arch = m.group(1)
            continue
        m = re.match(r'\s*Function : (\S+)', line)
        if m:
            name = m.group(1)
            funcs[(arch, name)] = collections.Counter()
            continue
        m = re.match(r'\s*/\*[0-9a-f]{4,}\*/\s+(.*?)\s*;', line)
        if m and name is not None:
            ins = m.group(1)
            guard = '@P ' if ins.startswith('@') else ''
            if guard:
                ins = ins.split(None, 1)[1] if ' ' in ins else ''
            opc = ins.split(None, 1)[0] if ins else ''
            funcs[(arch, name)][guard + opc] += 1
    return funcs

a, b = parse(sys.argv[1]), parse(sys.argv[2])
tot = collections.Counter()
for k in a:
    if k not in b:
        print(f'only in a: {k[0]} {k[1]}')
        continue
    da, db = a[k] - b[k], b[k] - a[k]
    if not da and not db:
        print(f'{k[0]} {k[1][:90]}: same opcodes ({sum(a[k].values())} instructions)')
        continue
    print(f'{k[0]} {k[1][:90]}: {sum(a[k].values())} -> {sum(b[k].values())} instructions; only in a: '
          f'{dict(da)}; only in b: {dict(db)}')
    for o, c in db.items():
        tot['+' + o] += c
    for o, c in da.items():
        tot['-' + o] += c
for k in b:
    if k not in a:
        print(f'only in b: {k[0]} {k[1]}')
print(f'total over the functions: {dict(tot)}')
