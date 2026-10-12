#!/usr/bin/env python3
# sass_diff.py <a.sass> <b.sass> [--show N] [--func REGEX] [--mask-stride]: compare two cuobjdump -sass dumps of the same
# program (or library) built against two header sets (work package 4: package 3's headers or hk's, then this package's),
# function by function, per architecture. Instructions are compared after masking register numbers (R, UR, P, UP, B) and
# code addresses (branch, call, BSSY targets); with --mask-stride also the GPU context stride immediates of work package 3
# (0x60 -> 0x68, and 0x10 -> 0x18 where the compiler split 0x60 into 0x50 + 0x10), for a comparison with hk. What remains
# is a difference in what the code does, not in how registers were allocated. Each function's two instruction lists are
# aligned (difflib) and every block that is not equal is printed with its opcodes: 'insert' = only in the rs build,
# 'delete' = only in hk, 'replace' = both. Functions only in one build are listed by name.
# Exit 0 always; the caller reads the report.
import difflib, re, sys, collections

def parse(path):
    funcs = collections.OrderedDict()  # (arch, name) -> [normalized instruction]
    arch, name, cur = None, None, None
    for line in open(path, errors='replace'):
        m = re.match(r'\s*code for (sm_\d+\w*)', line)
        if m:
            arch = m.group(1)
            continue
        m = re.match(r'\s*Function : (\S+)', line)
        if m:
            name = m.group(1)
            cur = funcs.setdefault((arch, name), [])
            continue
        m = re.match(r'\s*/\*[0-9a-f]{4,}\*/\s+(.*?)\s*;', line)
        if m and cur is not None:
            cur.append(norm(m.group(1)))
    return funcs

ADDR_OPS = ('BRA', 'BRX', 'CALL', 'JMP', 'BSSY', 'SSY', 'PBK', 'PCNT', 'JCAL', 'RET', 'BREAK', 'WARPSYNC', 'BMOV')

MASK_STRIDE = False

def norm(ins):
    s = ins
    s = re.sub(r'\bUR\d+\b', 'UR', s)
    s = re.sub(r'\bR\d+\b', 'R', s)
    s = re.sub(r'\bUP\d\b', 'UP', s)
    s = re.sub(r'\bP\d\b', 'P', s)
    s = re.sub(r'\bB\d\b', 'B', s)
    op = s.lstrip('@!PU ').split(' ')[0] if s.startswith('@') else s.split(' ')[0]
    if op.split('.')[0] in ADDR_OPS:
        s = re.sub(r'0x[0-9a-f]+', 'ADDR', s)
    if MASK_STRIDE and ('IMAD' in s or 'LEA' in s or 'IADD' in s):
        s = s.replace('0x68', '0x60').replace('0x18', '0x10')
    return s

def opcode(ins):
    t = ins.split(' ')
    i = 0
    if t[0].startswith('@'):
        i = 1
    return (t[0] + ' ' if i else '') + t[i]

def main():
    global MASK_STRIDE
    show = 40
    freg = None
    args = sys.argv[3:]
    MASK_STRIDE = '--mask-stride' in args
    a, b = parse(sys.argv[1]), parse(sys.argv[2])
    while args:
        if args[0] == '--show':
            show = int(args[1]); args = args[2:]
        elif args[0] == '--func':
            freg = re.compile(args[1]); args = args[2:]
        else:
            args = args[1:]
    onlyA = [k for k in a if k not in b]
    onlyB = [k for k in b if k not in a]
    same = changed = 0
    total = collections.Counter()
    for k in a:
        if k not in b:
            continue
        if freg and not freg.search(k[1]):
            continue
        x, y = a[k], b[k]
        if x == y:
            same += 1
            continue
        changed += 1
        sm = difflib.SequenceMatcher(None, x, y, autojunk=False)
        blocks = [op for op in sm.get_opcodes() if op[0] != 'equal']
        ins = sum(j2 - j1 for t, i1, i2, j1, j2 in blocks if t in ('insert', 'replace'))
        dele = sum(i2 - i1 for t, i1, i2, j1, j2 in blocks if t in ('delete', 'replace'))
        print(f'== {k[0]} {k[1]}: hk {len(x)} rs {len(y)} instructions; {len(blocks)} blocks, +{ins} -{dele}')
        for t, i1, i2, j1, j2 in blocks[:show]:
            total[t] += 1
            print(f'  {t:7s} hk[{i1}:{i2}] rs[{j1}:{j2}]')
            for ins_ in x[i1:i2]:
                print(f'      - {ins_}')
            for ins_ in y[j1:j2]:
                print(f'      + {ins_}')
        if len(blocks) > show:
            print(f'  ... {len(blocks) - show} more blocks')
    print(f'functions: identical {same}, different {changed}, only in hk {len(onlyA)}, only in rs {len(onlyB)}')
    for k in onlyA:
        print(f'  only in hk: {k[0]} {k[1]} ({len(a[k])} instructions)')
    for k in onlyB:
        print(f'  only in rs: {k[0]} {k[1]} ({len(b[k])} instructions)')

if __name__ == '__main__':
    main()
