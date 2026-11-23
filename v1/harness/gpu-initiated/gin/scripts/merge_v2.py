#!/usr/bin/env python3
# merge_v2.py - build results/<date>/gin_results.csv after the lead-QA re-run:
#   * baseline rows      <- v1 matrix (gin_results_v1.csv, fault=none; unchanged
#                           by the QA fixes), with init_silent_iters recomputed from
#                           the v1 per-rank KV logs (iters_ok r0 - r1)
#   * F1-F4 fault rows   <- v2 re-run (v2/gin_faults_v2.csv, new columns native)
#   * IB_TIMEOUT=20 refs <- ref60/ref60.csv + ref60/refblk.csv (lead's re-measure,
#                           older driver: no CLOCK_MONOTONIC stamps, so surface_ms is
#                           an estimate = host_error_ms - median v2 F3 fault_ms,
#                           flagged surface_by=est) + ref60/ref_gdaki_blk.csv (v2 driver)
# usage: merge_v2.py <results/<date> dir>
import csv, os, sys, statistics

D = sys.argv[1]
COLS = ("stack,backend,fault,wait_mode,trial,iters_ok_before,init_outcome,target_outcome,data_check,"
        "silent_success,host_error,host_error_ms,fp_where,status,vendor_err,teardown,notes,"
        "fault_ms,surface_ms,surface_by,init_silent_iters,clock_offset_ms").split(',')

def rd(p):
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []

def kvlast(path, key):
    v = None
    if os.path.exists(path):
        for line in open(path):
            for tok in line.split():
                if tok.startswith(key + '='):
                    v = tok.split('=', 1)[1]
    return v

def silent_from_kv(logdir, r):
    base = f"{r['backend']}_{r['fault']}_{r['wait_mode']}_t{r['trial']}"
    a = kvlast(os.path.join(logdir, base + '_r0.kv'), 'iters_ok')
    b = kvlast(os.path.join(logdir, base + '_r1.kv'), 'iters_ok')
    return str(int(a) - int(b)) if a is not None and b is not None else ''

out = []
for r in rd(os.path.join(D, 'gin_results_v1.csv')):
    if r['fault'] != 'none':
        continue
    r.update(fault_ms='', surface_ms='', surface_by='-', clock_offset_ms='',
             init_silent_iters=silent_from_kv(os.path.join(D, 'logs'), r))
    out.append(r)

v2 = rd(os.path.join(D, 'v2', 'gin_faults_v2.csv'))
out += v2

f3 = [float(r['fault_ms']) for r in v2 if r['backend'] == 'proxy' and r['fault'] == 'F3' and r['fault_ms']]
f3med = statistics.median(f3) if f3 else None
refdir = os.path.join(D, 'ref60')
for name in ('ref60.csv', 'refblk.csv'):
    for r in rd(os.path.join(refdir, name)):
        r['trial'] = r['trial'] if 'ref' in r['trial'] else 'ref' + r['trial']
        est = (float(r['host_error_ms']) - f3med) if (f3med is not None and r['host_error_ms']) else None
        r.update(fault_ms=f"{f3med:.1f}" if f3med is not None else '',
                 surface_ms=f"{est:.1f}" if est is not None else '', surface_by='est', clock_offset_ms='',
                 init_silent_iters=silent_from_kv(os.path.join(refdir, 'logs'), r))
        r['notes'] = r['notes'] + ';ib_timeout=20;lead_remeasure;fault_ms=v2_F3_median(est)'
        out.append(r)
for r in rd(os.path.join(refdir, 'ref_gdaki_blk.csv')):
    r['notes'] = r['notes'] + ';ib_timeout=20'
    out.append(r)

with open(os.path.join(D, 'gin_results.csv'), 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=COLS, extrasaction='ignore')
    w.writeheader()
    for r in out:
        w.writerow({k: r.get(k, '') for k in COLS})
print(f"wrote {len(out)} rows to {os.path.join(D, 'gin_results.csv')} (v2 faults: {len(v2)}, F3 fault_ms median {f3med})")
