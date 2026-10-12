#!/usr/bin/env python3
# ptx_cmp.py <dir>: for every <name>_<arch>_hk.ptx / _rs.ptx pair, compare the PTX (before register allocation) instruction
# by instruction. Comment and debug lines are dropped. Every differing line must be the same instruction whose only change
# is an immediate 96 -> 104 or 0x60 -> 0x68 (sizeof(struct ncclGinGdakiGPUContext), the context stride), and the line
# counts must match: then NCCL's own kernels compute the same thing on contexts of the new size.
import glob, os, re, sys
d = sys.argv[1]
ok = {('96', '104'), ('0x60', '0x68'), ('96U', '104U')}
def lines(p):
    out = []
    for l in open(p):
        l = l.split('//')[0].strip()
        if not l or l.startswith('.loc') or l.startswith('.file') or l.startswith('.section') or l.startswith('@@DWARF'):
            continue
        # the compiler names internal-linkage symbols with a hash of the compilation (_INTERNAL_<hash>_, and
        # __nv_static_<n>__<hash>_): it differs between any two compilations of the same source; drop it
        l = re.sub(r'_INTERNAL_[0-9a-f]{8}_', '_INTERNAL_x_', l)
        l = re.sub(r'__nv_static_(\d+)__[0-9a-f]{8}_', r'__nv_static_\1__x_', l)
        l = re.sub(r'(_cu_)[0-9a-f]{8}_\d{6}', r'\1x_', l)  # the same hash in a file's own empty globals
        out.append(l)
    return out
tok = re.compile(r'(0x[0-9a-fA-F]+U?|\b\d+U?\b)')
strdecl = re.compile(r'\.global \.align 1 \.b8 (\$str\$\d+)\[\d+\] = \{([0-9, ]+)\};')
files = sorted(glob.glob(os.path.join(d, '*_hk.ptx')))
bad_total = 0
for h in files:
    r = h[:-len('_hk.ptx')] + '_rs.ptx'
    a, b = lines(h), lines(r)
    name = os.path.basename(h)[:-len('_hk.ptx')]
    if len(a) != len(b):
        print(f'{name}: line counts differ ({len(a)} vs {len(b)})'); bad_total += 1; continue
    n = bad = paths = 0
    for x, y in zip(a, b):
        if x == y: continue
        # a string constant (an assertion's file name) holds the build tree's path: agent_gd/gin_hk/ in hk, agent_rs/ here
        mx, my = strdecl.match(x), strdecl.match(y)
        if mx and my and mx.group(1) == my.group(1):
            sx = bytes(int(v) for v in mx.group(2).split(',')).decode('latin-1').replace('/agent_gd/gin_hk/', '/agent_rs/')
            sy = bytes(int(v) for v in my.group(2).split(',')).decode('latin-1')
            if sx == sy:
                paths += 1
                continue
        tx, ty = tok.split(x), tok.split(y)
        diffs = [(u, v) for u, v in zip(tx, ty) if u != v]
        if len(tx) == len(ty) and len(diffs) == 1 and diffs[0] in ok:
            n += 1
        else:
            bad += 1
            if bad <= 3: print(f'  UNEXPECTED {name}: {x}  |  {y}')
    bad_total += bad
    print(f'{name}: {len(a)} PTX lines, {n} differ only in the context stride, {paths} only in the build path, unexpected {bad}')
print(f'pairs {len(files)}; unexpected lines total {bad_total}')
sys.exit(1 if bad_total else 0)
