#!/usr/bin/env python3
"""summarize.py - medians of the completion-time CSVs (analysis only; the measurement is nccl_ct.cu).

usage: summarize.py <results dir>...   (each dir holds overhead_*.csv and/or fault_*.csv)
"""
import csv, glob, os, statistics as st, sys
from collections import defaultdict


def med(xs):
    return st.median(xs) if xs else float('nan')


def rng(xs):
    return f"{min(xs):.3g}-{max(xs):.3g}" if xs else "-"


def overhead(path):
    rows = list(csv.DictReader(open(path)))
    by = defaultdict(list)
    for r in rows:
        if r['rc0'] != '0' or r['rc1'] != '0':
            continue
        by[(int(r['bytes']), r['build'], r['fr'])].append(float(r['med_ms0']))
    stock = {b: med(v) for (b, build, fr), v in by.items() if build == 'stock'}
    print(f"\n### {os.path.basename(os.path.dirname(path))}/{os.path.basename(path)}\n\n| bytes | build | flag | n | median of per-run median (ms) | vs stock |\n|---|---|---|---|---|---|")
    for (b, build, fr), v in sorted(by.items()):
        m = med(v)
        rel = f"{(m / stock[b] - 1) * 100:+.1f} %" if b in stock and build != 'stock' else ""
        print(f"| {b} | {build} | {fr} | {len(v)} | {m:.4f} | {rel} |")


def fault(path):
    rows = list(csv.DictReader(open(path)))
    by = defaultdict(list)
    for r in rows:
        by[r['mode']].append(r)
    print(f"\n### {os.path.basename(os.path.dirname(path))}/{os.path.basename(path)}\n\n| mode | n | rc 0/0 | wall s (median, range) | detail |\n|---|---|---|---|---|")
    for mode in ('baseline', 'recover', 'restart'):
        rs = by.get(mode, [])
        if not rs:
            continue
        ok = sum(r['rc0'] == '0' and r['rc1'] == '0' for r in rs)
        w = [float(r['wall_s']) for r in rs]
        if mode == 'restart':
            # the job's own time = both segments; older CSVs put the runner's wall (with its cleanup
            # between segments) in wall_s, so recompute it from the segment columns
            w = [float(r['seg1_wall_s']) + float(r['seg2_wall_s'] or 0) for r in rs]
        detail = ""
        if mode == 'recover':
            rec = [float(r['t_recover_ms']) for r in rs if r.get('t_recover_ms')]
            nrec = sum(r.get('recovered') == '1' for r in rs)
            detail = f"recovered {nrec}/{len(rs)}"
            if rec:
                detail += f", recovery {med(rec):.2f} ms ({rng(rec)})"
            if ok < len(rs):
                fi = sorted({r['fail_iter0'] for r in rs})
                detail += f", failed at iteration {','.join(fi)}"
        if mode == 'restart':
            s1 = [float(r['seg1_wall_s']) for r in rs if r.get('seg1_wall_s')]
            s2 = [float(r['seg2_wall_s']) for r in rs if r.get('seg2_wall_s')]
            ri = sorted({r['resume_iter'] for r in rs})
            rw = [float(r.get('runner_wall_s') or r['wall_s']) for r in rs]
            detail = (f"first segment {med(s1):.2f} s, relaunch segment {med(s2):.2f} s, resumed at iteration "
                      f"{','.join(ri)}; runner wall incl. its cleanup {med(rw):.2f} s")
        print(f"| {mode} | {len(rs)} | {ok} | {med(w):.3f} ({rng(w)}) | {detail} |")


for d in sys.argv[1:]:
    for p in sorted(glob.glob(os.path.join(d, 'overhead_*.csv'))):
        overhead(p)
    for p in sorted(glob.glob(os.path.join(d, 'fault_*.csv'))):
        fault(p)
