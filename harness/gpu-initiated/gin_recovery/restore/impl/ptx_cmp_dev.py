#!/usr/bin/env python3
# ptx_cmp_dev.py <hk dir> <dev dir>: NCCL's symmetric GIN kernels (the library, built without NCCL_GIN_RESTORE_DEVICE)
# against hk's, in PTX (before register allocation): for every <name>_<arch>_hk.ptx in <hk dir> (package 3's references)
# and <name>_<arch>_dev.ptx in <dev dir>, the lines are aligned after dropping comments and debug lines and masking
# virtual register numbers, declared register counts, whitespace and compilation hashes. Allowed differences: an immediate 96 -> 104 (the context stride of
# work package 3), the build path in an assertion string, and inserted lines that are the side-table check of work package
# 4 redone (a 64-bit load at offset 96 of a context and the predicated-trap block: "{", ".reg .pred p;", "setp.ne.u64",
# "@p trap;", "}"; the load's offset may be partly folded into its base). Anything else is printed as unexpected. Exit 1
# on an unexpected line.
import difflib, glob, os, re, sys
hd, dd = sys.argv[1], sys.argv[2]
strdecl = re.compile(r'\.global \.align 1 \.b8 (\$str\$\d+)\[\d+\] = \{([0-9, ]+)\};')
def norm(l):
    l = re.sub(r'_INTERNAL_[0-9a-f]{8}_', '_INTERNAL_x_', l)
    l = re.sub(r'__nv_static_(\d+)__[0-9a-f]{8}_', r'__nv_static_\1__x_', l)
    l = re.sub(r'(_cu_)[0-9a-f]{8}_\d+', r'\1x_', l)
    l = re.sub(r'_ZN\d+_INTERNAL_', '_ZNn_INTERNAL_', l)  # its length prefix follows the hash's digits
    l = re.sub(r'%(rd|r|p|f|fd|rs|h|hh|b)\d+', r'%\1', l)
    l = re.sub(r'\$L__BB\d+_\d+', '$L', l)
    l = re.sub(r'\s+', ' ', l)
    l = re.sub(r'^(\.reg \.\w+ %\w+)<\d+>;$', r'\1<n>;', l)  # the count of virtual registers declared
    m = strdecl.match(l)
    if m:
        s = bytes(int(v) for v in m.group(2).split(',')).decode('latin-1')
        s = s.replace('/agent_gd/gin_hk/', '/X/').replace('/agent_rs_dev/', '/X/')
        l = '.global .align 1 .b8 %s = "%s";' % (m.group(1), s)
    return l
def lines(p):
    out = []
    for l in open(p):
        l = l.split('//')[0].strip()
        if not l or l.startswith(('.loc', '.file', '.section', '@@DWARF')):
            continue
        out.append(norm(l))
    return out
# the check: the side-table pointer's 64-bit load (the compiler may fold part of offset 96 into the base) right before the
# predicated-trap block; an inserted run of lines must be made of whole checks
LOAD = re.compile(r'^ld(\.global)?\.u64 %rd, \[%rd(\+\d+)?\];$')
BLOCK = ['{', '.reg .pred p;', 'setp.ne.u64 p, %rd, 0;', '@p trap;', '}']
def checks(ls):  # the number of whole checks the lines are, or -1
    n, i = 0, 0
    while i < len(ls):
        if LOAD.match(ls[i]) and ls[i + 1:i + 6] == BLOCK:
            n += 1; i += 6
        else:
            return -1
    return n
def isCheck(l):
    return LOAD.match(l) is not None or l in BLOCK
tok = re.compile(r'(0x[0-9a-fA-F]+U?|\b\d+U?\b)')
bad_total = pairs = 0
for h in sorted(glob.glob(os.path.join(hd, '*_hk.ptx'))):
    name = os.path.basename(h)[:-len('_hk.ptx')]
    d = os.path.join(dd, name + '_dev.ptx')
    if not os.path.exists(d):
        print(f'{name}: no dev PTX'); bad_total += 1; continue
    pairs += 1
    a, b = lines(h), lines(d)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    stride = inserted = bad = 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        if op == 'insert' and checks(b[j1:j2]) > 0:
            inserted += checks(b[j1:j2]); continue
        if op == 'replace' and i2 - i1 == j2 - j1:
            okb = True
            for x, y in zip(a[i1:i2], b[j1:j2]):
                tx, ty = tok.split(x), tok.split(y)
                df = [(u, v) for u, v in zip(tx, ty) if u != v]
                if len(tx) == len(ty) and len(df) == 1 and df[0] in {('96', '104'), ('0x60', '0x68'), ('96U', '104U')}:
                    stride += 1
                else:
                    okb = False
            if okb: continue
        # a replace that mixes stride lines and inserted check lines: try line by line
        rest_a, rest_b = a[i1:i2], [l for l in b[j1:j2] if not isCheck(l)]
        if len(rest_a) == len(rest_b):
            okb = True
            for x, y in zip(rest_a, rest_b):
                tx, ty = tok.split(x), tok.split(y)
                df = [(u, v) for u, v in zip(tx, ty) if u != v]
                if x == y: continue
                if len(tx) == len(ty) and len(df) == 1 and df[0] in {('96', '104'), ('0x60', '0x68'), ('96U', '104U')}:
                    stride += 1
                else:
                    okb = False
            if okb and checks([l for l in b[j1:j2] if isCheck(l)]) >= 0:
                inserted += checks([l for l in b[j1:j2] if isCheck(l)]); continue
        bad += 1
        if bad <= 3:
            print(f'  UNEXPECTED {name} {op}: hk {a[i1:i2][:4]} | dev {b[j1:j2][:6]}')
    bad_total += bad
    print(f'{name}: {len(a)} -> {len(b)} PTX lines; stride {stride}, checks inserted {inserted}, unexpected {bad}')
print(f'pairs {pairs}; unexpected blocks total {bad_total}')
sys.exit(1 if bad_total else 0)
