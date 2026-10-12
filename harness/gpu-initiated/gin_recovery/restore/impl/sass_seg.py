#!/usr/bin/env python3
# sass_seg.py <a.sass> <b.sass> [--show N]: the work package 4 machine-code comparison for whole-program builds, where a
# kernel's listing also holds the not inlined device functions it calls (cuobjdump prints them inside the kernel's
# "Function :" block, reached with CALL.REL). Each kernel's listing is cut into segments at the CALL.REL targets: the
# kernel body (from address 0) and one segment per called function. Segments of b are matched to segments of a by the
# best similarity of their instructions (registers and code addresses masked, as sass_diff.py). Reported per kernel:
#   body: the instruction blocks that differ between a's body and b's body (insert = only in b);
#   each a-segment with its b match: identical, or the differing blocks;
#   b-segments without a match: functions that exist only in b (work package 4: the hold path), with their sizes;
#   a "net" line: over the body and the matched functions, the instructions only in b minus those only in a, by class
#   (global and local memory, atomics, fences and barriers, control flow, compares, moves, other), and how many pointer
#   checks were added (a 64-bit load at offset 0x60 of the GPU context: the side-table pointer).
import difflib, re, sys, collections
sys.path.insert(0, __import__('os').path.dirname(__file__))
from sass_diff import norm  # noqa: E402

def parse(path):
    funcs = collections.OrderedDict()  # (arch, name) -> [(addr, normalized, raw)]
    arch, cur = None, None
    for line in open(path, errors='replace'):
        m = re.match(r'\s*code for (sm_\d+\w*)', line)
        if m:
            arch = m.group(1)
            continue
        m = re.match(r'\s*Function : (\S+)', line)
        if m:
            cur = funcs.setdefault((arch, m.group(1)), [])
            continue
        m = re.match(r'\s*/\*([0-9a-f]{4,})\*/\s+(.*?)\s*;', line)
        if m and cur is not None:
            cur.append((int(m.group(1), 16), norm(m.group(2)), m.group(2)))
    return funcs

def segments(ins):
    starts = {0}
    for _, _, raw in ins:
        m = re.search(r'CALL\.REL\S*\s+0x([0-9a-f]+)', raw)
        if m:
            starts.add(int(m.group(1), 16))
    starts = sorted(starts)
    segs = collections.OrderedDict((s, []) for s in starts)
    k = 0
    for addr, n, _ in ins:
        while k + 1 < len(starts) and addr >= starts[k + 1]:
            k += 1
        segs[starts[k]].append(n)
    return segs

def blocks(x, y):
    sm = difflib.SequenceMatcher(None, x, y, autojunk=False)
    return [op for op in sm.get_opcodes() if op[0] != 'equal']

def show_blocks(x, y, bl, show, indent='    '):
    for t, i1, i2, j1, j2 in bl[:show]:
        print(f'{indent}{t:7s} a[{i1}:{i2}] b[{j1}:{j2}]')
        for s in x[i1:i2]:
            print(f'{indent}    - {s}')
        for s in y[j1:j2]:
            print(f'{indent}    + {s}')
    if len(bl) > show:
        print(f'{indent}... {len(bl) - show} more blocks')

CLASSES = [
    ('local', ('LDL', 'STL')),
    ('global', ('LDG', 'STG', 'LD', 'ST', 'LDS', 'STS')),
    ('atomic', ('ATOM', 'ATOMG', 'ATOMS', 'RED')),
    ('fence', ('MEMBAR', 'FENCE', 'ERRBAR', 'BAR', 'CCTL', 'NANOSLEEP', 'WARPSYNC')),
    ('control', ('BRA', 'CALL', 'RET', 'BSSY', 'BSYNC', 'BMOV', 'JMP', 'BRX', 'EXIT', 'BREAK')),
    ('compare', ('ISETP', 'UISETP', 'PLOP3', 'P2R', 'R2P', 'FSETP', 'DSETP')),
    ('move', ('MOV', 'IMAD.MOV', 'UMOV', 'CS2R', 'S2R', 'S2UR', 'PRMT', 'SEL', 'R2UR')),
]

def iclass(ins):
    t = ins.split(' ')
    op = t[1] if t[0].startswith('@') and len(t) > 1 else t[0]
    for name, ops in CLASSES:
        for o in ops:
            if op == o or op.startswith(o + '.'):
                return name
    return 'other'

MEMCLS = ('global', 'local', 'atomic', 'fence')

def memkey(ins):
    # the same access whatever register file holds its base (UR or R, .64 pair) and however the offset is folded
    k = re.sub(r'\[(U?R)(\.64)?(\+0x[0-9a-f]+)?\]', '[ADDR]', ins)
    if PRED_FREE:  # --pred-free: also whether it is predicated (the compiler if-converts differently around a new branch)
        k = re.sub(r'^@!?U?P\s+', '', k)
    return re.sub(r'\bUR\b', 'R', k)

PRED_FREE = '--pred-free' in sys.argv

def net(x, y, bl, acc, mem=None):
    for t, i1, i2, j1, j2 in bl:
        for s_ in y[j1:j2]:
            if mem is not None and iclass(s_) in MEMCLS:
                mem[memkey(s_)] += 1
            acc[iclass(s_)] += 1
            if iclass(s_) == 'global' and s_.startswith('LDG.E.64') and '+0x60]' in s_:
                acc['ptr-check loads'] += 1
        for s_ in x[i1:i2]:
            if mem is not None and iclass(s_) in MEMCLS:
                mem[memkey(s_)] -= 1
            acc[iclass(s_)] -= 1
            if iclass(s_) == 'global' and s_.startswith('LDG.E.64') and '+0x60]' in s_:
                acc['ptr-check loads'] -= 1

def main():
    a, b = parse(sys.argv[1]), parse(sys.argv[2])
    show = int(sys.argv[sys.argv.index('--show') + 1]) if '--show' in sys.argv else 30
    for k in a:
        if k not in b:
            print(f'== {k[0]} {k[1]}: only in a')
            continue
        sa, sb = segments(a[k]), segments(b[k])
        body_a, body_b = sa.pop(0), sb.pop(0)
        bl = blocks(body_a, body_b)
        ins = sum(j2 - j1 for t, i1, i2, j1, j2 in bl)
        dele = sum(i2 - i1 for t, i1, i2, j1, j2 in bl)
        print(f'== {k[0]} {k[1]}: body a {len(body_a)} b {len(body_b)}: {len(bl)} blocks, +{ins} -{dele}; '
              f'called functions a {len(sa)} b {len(sb)}')
        show_blocks(body_a, body_b, bl, show)
        acc = collections.Counter()
        mem = collections.Counter()  # memory, atomic and fence instructions only in b minus only in a, by exact text
        net(body_a, body_b, bl, acc, mem)
        free = dict(sb)
        for s, x in sa.items():
            best, br = None, -1.0
            for t, y in free.items():
                if y == x:
                    best, br = t, 2.0
                    break
                r = difflib.SequenceMatcher(None, x, y, autojunk=False).quick_ratio()
                if r > br:
                    best, br = t, r
            if best is None:
                print(f'  a function at {s:#x} ({len(x)} instructions): no match in b')
                continue
            y = free.pop(best)
            if x == y:
                print(f'  a function at {s:#x} ({len(x)} instructions): identical in b')
            else:
                bl2 = blocks(x, y)
                net(x, y, bl2, acc, mem)
                print(f'  a function at {s:#x} ({len(x)}) ~ b at {best:#x} ({len(y)}): {len(bl2)} blocks differ')
                show_blocks(x, y, bl2, show, '      ')
        newf = 0
        for t, y in free.items():
            newf += len(y)
            print(f'  only in b: function at {t:#x} ({len(y)} instructions)')
        keys = ['ptr-check loads', 'global', 'local', 'atomic', 'fence', 'control', 'compare', 'move', 'other']
        print(f'  net {k[0]} {k[1]}: ' + ', '.join(f'{c} {acc[c]:+d}' for c in keys) +
              f'; functions only in b: {len(free)} ({newf} instructions)')
        # moved instructions cancel (also one whose base moved between the uniform and the regular register file, or whose
        # offset was folded into the base differently); what is left was added or removed
        left = {i: c for i, c in mem.items() if c != 0}
        print(f'  memory, atomic and fence instructions added or removed (not moved) {k[0]} {k[1]}: ' +
              ('; '.join(f'{c:+d} x {i}' for i, c in sorted(left.items())) or 'none'))

if __name__ == '__main__':
    main()
