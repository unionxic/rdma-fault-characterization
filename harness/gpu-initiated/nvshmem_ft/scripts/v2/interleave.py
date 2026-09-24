#!/usr/bin/env python3
"""interleave.py <cells.txt> <first> <last> - print a run_matrix_v2.sh spec that runs trial k of every
cell before trial k+1 of any (k = first..last), so that slow drifts spread over all cells.
cells.txt: '<fault> <mode> VAR=value ...' per line ('#' comments)."""
import sys
cells = [l.split() for l in open(sys.argv[1]) if l.strip() and not l.lstrip().startswith('#')]
for k in range(int(sys.argv[2]), int(sys.argv[3]) + 1):
    for c in cells:
        print(' '.join([c[0], c[1], '1'] + c[2:] + ['TFIRST=%d' % k]))
