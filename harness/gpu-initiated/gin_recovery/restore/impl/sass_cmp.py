#!/usr/bin/env python3
# Compare two cuobjdump -sass dumps line by line (same programs compiled against the hk and the rs headers).
# Every differing line must be the same instruction whose only change is an immediate multiplier 0x60 -> 0x68 (the
# GPU context stride, 96 -> 104 bytes) or 0x10 -> 0x18 (its part after the compiler split 0x60 into 0x50 + 0x10).
import re, sys
def instr(l):
    m = re.match(r'\s*/\*[0-9a-f]+\*/\s+(.*?)\s*;', l)
    return m.group(1) if m else None
ok = {('0x60', '0x68'), ('0x10', '0x18')}
total = 0
for prog in sys.argv[1:]:
    a = open(prog + '_hk.sass').read().split('\n'); b = open(prog + '_rs.sass').read().split('\n')
    assert len(a) == len(b), prog
    n = bad = 0
    pairs = {}
    for x, y in zip(a, b):
        if x == y: continue
        ix, iy = instr(x), instr(y)
        if ix is None or iy is None:   # the encoding comment line under an instruction differs with its immediate
            if re.fullmatch(r'\s*/\* 0x[0-9a-f]+ \*/\s*', x) and re.fullmatch(r'\s*/\* 0x[0-9a-f]+ \*/\s*', y): continue
            bad += 1; print('UNEXPECTED', prog, repr(x), repr(y)); continue
        tx, ty = re.split(r'(0x[0-9a-f]+)', ix), re.split(r'(0x[0-9a-f]+)', iy)
        diffs = [(u, v) for u, v in zip(tx, ty) if u != v]
        if len(tx) != len(ty) or len(diffs) != 1 or diffs[0] not in ok:
            bad += 1; print('UNEXPECTED', prog, ix, '|', iy); continue
        n += 1; pairs[diffs[0]] = pairs.get(diffs[0], 0) + 1
    total += bad
    print(f'{prog}: {len(a)} lines, {n} instructions differ, all a context-stride immediate {dict(pairs)}; unexpected {bad}')
sys.exit(1 if total else 0)
