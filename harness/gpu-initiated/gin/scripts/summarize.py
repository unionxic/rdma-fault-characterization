#!/usr/bin/env python3
# summarize.py - collapse per-trial GIN CSV rows into a backend x fault x wait_mode
# (x trial-kind: matrix vs ref) summary table. Prints markdown; writes
# <csv_dir>/summary.md.
#
# surface_ms = host time-to-surface (first non-success ncclCommGetAsyncError minus
# fault fire time, both on rank0's CLOCK_MONOTONIC); shown as median [min-max].
# init_silent_iters = rank0 okIters - rank1 okIters per trial (iterations the
# initiator reported done whose data rank1 never received intact); shown as the
# per-trial values.
import csv, sys, os, statistics
from collections import defaultdict, Counter

ORDER = {'none': 0, 'F1': 1, 'F2': 2, 'F3': 3, 'F4': 4}

def cnt(rows, k):
    return ",".join(f"{v}:{n}" for v, n in sorted(Counter(r.get(k, '') or '-' for r in rows).items()))

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def main(path, title="NCCL GIN fault matrix summary"):
    rows = list(csv.DictReader(open(path)))
    cells = defaultdict(list)
    for r in rows:
        kind = 'ref' if 'ref' in r['trial'] else 'mx'
        cells[(r['backend'], r['fault'], r['wait_mode'], kind)].append(r)

    hdr = ("| backend | fault | wait | kind | n | init_outcome | target_outcome | data | init_silent_iters | "
           "host_error | surface_ms med [min-max] | surface_by | fp_where | status/ve | teardown |")
    lines = [hdr, "|" + "---|" * 15]
    for key in sorted(cells, key=lambda k: (k[0], ORDER.get(k[1], 9), k[2], k[3])):
        rs = cells[key]
        sm = [x for x in (num(r.get('surface_ms')) for r in rs) if x is not None]
        smt = f"{statistics.median(sm):.0f} [{min(sm):.0f}-{max(sm):.0f}]" if sm else "-"
        sil = "/".join((r.get('init_silent_iters') or '-') for r in rs)
        sv = cnt([{'x': f"{r.get('status') or '-'}/{r.get('vendor_err') or '-'}"} for r in rs], 'x')
        lines.append(f"| {key[0]} | {key[1]} | {key[2]} | {key[3]} | {len(rs)} | {cnt(rs,'init_outcome')} | "
                     f"{cnt(rs,'target_outcome')} | {cnt(rs,'data_check')} | {sil} | {cnt(rs,'host_error')} | "
                     f"{smt} | {cnt(rs,'surface_by')} | {cnt(rs,'fp_where')} | {sv} | {cnt(rs,'teardown')} |")
    out = "\n".join(lines)
    print(out)
    with open(os.path.join(os.path.dirname(path) or '.', 'summary.md'), 'w') as f:
        f.write(f"# {title}\n\nsource: `{os.path.basename(path)}` ({len(rows)} trials)\n\n")
        f.write("surface_ms = host time-to-surface after the fault fired (rank0 CLOCK_MONOTONIC); "
                "init_silent_iters = rank0 okIters - rank1 okIters per trial.\n\n")
        f.write(out + "\n")

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'gin_results.csv')
