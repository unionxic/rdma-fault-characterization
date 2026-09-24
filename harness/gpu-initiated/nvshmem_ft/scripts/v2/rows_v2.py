#!/usr/bin/env python3
"""rows_v2.py - v2 per-trial logs (run_trial_v2.sh) -> one CSV row per trial, plus LAT rows.

usage: rows_v2.py <logdir> [<logdir> ...] --trials T.csv [--lat L.csv]

Per trial: the .meta knobs (ring, bounds, skip, oob, cq_collapsed, bundle), exit codes, the FIRST
fault record the initiator saw (class, path, fingerprint, kind, wqe, ring_ci, oob fields), how the
run ended (DECLINE reason, recovery rounds, ops verified, final signal), PE1's data checks
(ITER mismatch at the fault, OOBCHECK canary / dbuf), teardown, init phases reached (cc=0 probe),
INITDIAG lines (flattened), leftovers. Nothing is computed from other rows.
"""
import csv
import gzip
import os
import re
import sys


def kv(line):
    d = {}
    for m in re.finditer(r'(\w+)=("[^"]*"|\S+)', line):
        d[m.group(1)] = m.group(2).strip('"')
    return d


def readlog(p):
    if os.path.exists(p):
        return open(p, errors='replace').read().splitlines()
    if os.path.exists(p + '.gz'):
        return gzip.open(p + '.gz', 'rt', errors='replace').read().splitlines()
    return []


def parse_trial(meta_path):
    base = meta_path[:-5]
    meta = {}
    for line in open(meta_path):
        meta.update(kv(line))
    l0 = readlog(base + '.pe0.log')
    l1 = readlog(base + '.pe1.log')
    row = {k: meta.get(k, '') for k in (
        'tag', 'fault', 'mode', 'trial', 'ft', 'recover', 'ring', 'bounds', 'guard', 'skip', 'oob', 'mt',
        'cq_collapsed', 'qdelay_us', 'sentinel', 'burst', 'bin', 'md5_rain', 'lib_rain', 'host_rain',
        'pe0_rc', 'pe1_rc', 'leftover_rain', 'leftover_sunny', 'start')}
    row['dir'] = os.path.basename(os.path.dirname(meta_path))
    # enabled line (PE0)
    en = next((l for l in l0 if '[nvshmem-ft] PE0 enabled:' in l), '')
    row['ft_enabled_line'] = 1 if en else 0
    if en:
        e = kv(en)
        row['classifier'] = e.get('classifier', '')
        row['ring_cq'] = e.get('ring_cq', '')
        row['bounds_on'] = e.get('bounds', '')
    # first fault record + decline + recovery
    fr = next((kv(l) for l in l0 if l.startswith('FAULTREC ')), None)
    if fr:
        for k in ('it', 'class', 'fp', 'syndrome', 'opcode', 'wqe', 'path', 'kind', 'ring_ci', 'oob_op',
                  'oob_off', 'oob_len', 'oob_chunk_end', 'kernel_rc', 't_dev', 't_mbx', 't_ret'):
            row['fr_' + k] = fr.get(k, '')
    dec = next((kv(l) for l in l0 if l.startswith('DECLINE ')), None)
    row['decline_reason'] = dec.get('reason', '') if dec else ''
    row['decline_class'] = dec.get('class', '') if dec else ''
    recs = [kv(l) for l in l0 if l.startswith('REC ')]
    row['rec_lines'] = len(recs)
    row['rec_d'] = ';'.join(r.get('d', '') for r in recs)
    row['rec_ring'] = ';'.join('%s/%s/%s' % (r.get('ring_ci_old', ''), r.get('ring_scan', ''), r.get('ring_pi', ''))
                               for r in recs)
    s0 = next((kv(l) for l in l0 if l.startswith('SUMMARY rank 0')), {})
    s1 = next((kv(l) for l in l1 if l.startswith('SUMMARY rank 1')), {})
    for k in ('rc', 'ok_iters', 'rec_rounds', 'rec_ok_ops', 'declined'):
        row['s0_' + k] = s0.get(k, '')
    for k in ('rc', 'ok_iters', 'final_sig', 'expected_sig'):
        row['s1_' + k] = s1.get(k, '')
    # PE1 data checks
    it1 = [(l.split()[1], kv(l)) for l in l1 if l.startswith('ITER ') and ' rank 1 ' in l]
    row['pe1_iters'] = len(it1)
    bad = [(i, x) for i, x in it1 if x.get('data_check') not in ('ok',)]
    row['pe1_first_notok'] = ('%s:%s:%s:sig=%s/%s' % (bad[0][0], bad[0][1].get('data_check', ''),
                                                      bad[0][1].get('mismatch', ''), bad[0][1].get('sig', ''),
                                                      bad[0][1].get('expect', ''))) if bad else ''
    m = [l for l in l1 if l.startswith('ITER ') and ' rank 1 ' in l and 'data_check=' in l
         and 'data_check=ok' not in l]
    row['pe1_notok_lines'] = len(m)
    oc = next((kv(l) for l in l1 if l.startswith('OOBCHECK ')), None)
    row['canary_bad'] = oc.get('canary_bad', '') if oc else ''
    row['dbuf_vs_prev_bad'] = oc.get('dbuf_vs_prev_bad', '') if oc else ''
    lay = next((kv(l) for l in l0 if l.startswith('LAYOUT rank 0')), {})
    for k in ('dbuf', 'sbuf', 'sig', 'tbuf', 'bad_dst', 'canary', 'heap_size'):
        row['lay_' + k] = lay.get(k, '')
    # bounds record line (host log)
    bl = next((kv(l) for l in l0 if 'device bounds check rejected' in l), None)
    row['bounds_why'] = bl.get('why', '') if bl else ''
    # teardown
    for r, lines in ((0, l0), (1, l1)):
        td = next((kv(l) for l in lines if l.startswith('TEARDOWN rank %d' % r)), None)
        row['td%d_returned' % r] = td.get('returned', '') if td else '0'
        row['td%d_finalize_ms' % r] = td.get('finalize_ms', '') if td else ''
        row['watchdog%d' % r] = int(any('WATCHDOG' in l for l in lines))
    # phases (cc=0 probe)
    for r, lines in ((0, l0), (1, l1)):
        ph = [l.split('PHASE ')[1] for l in lines if 'PHASE ' in l and l.startswith('[PE')]
        row['phase%d' % r] = ph[-1] if ph else 'none'
    row['initdiag0'] = ' | '.join(l[len('INITDIAG '):] for l in l0 if l.startswith('INITDIAG '))
    row['initdiag1'] = ' | '.join(l[len('INITDIAG '):] for l in l1 if l.startswith('INITDIAG '))
    row['cc0_line'] = int(any('CQ created with cc=0' in l for l in l0))
    row['iters0'] = sum(1 for l in l0 if l.startswith('ITER ') and ' rank 0 ' in l)
    return row


def lat_rows(meta_path):
    base = meta_path[:-5]
    meta = {}
    for line in open(meta_path):
        meta.update(kv(line))
    out = []
    for l in readlog(base + '.pe0.log'):
        if l.startswith('LAT rep'):
            d = kv(l)
            d['rep'] = l.split()[2]
            d.update({k: meta.get(k, '') for k in ('tag', 'trial', 'ft', 'ring', 'bounds', 'bin', 'bundle')})
            d['dir'] = os.path.basename(os.path.dirname(meta_path))
            out.append(d)
    return out


def main():
    args = sys.argv[1:]
    tout = args[args.index('--trials') + 1] if '--trials' in args else None
    lout = args[args.index('--lat') + 1] if '--lat' in args else None
    dirs = [a for i, a in enumerate(args) if not a.startswith('--') and (i == 0 or not args[i - 1].startswith('--'))]
    rows, lats = [], []
    for d in dirs:
        for f in sorted(os.listdir(d)):
            if f.endswith('.meta'):
                rows.append(parse_trial(os.path.join(d, f)))
                lats += lat_rows(os.path.join(d, f))
    if tout:
        keys = []
        for r in rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        with open(tout, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print('wrote %s (%d trials)' % (tout, len(rows)))
    if lout:
        keys = ['dir', 'tag', 'trial', 'rep', 'ft', 'ring', 'bounds', 'bin', 'bytes', 'n', 'p50_us', 'p90_us', 'p99_us',
                'max_us', 'mean_us', 'err']
        with open(lout, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=keys, extrasaction='ignore')
            w.writeheader()
            for r in lats:
                w.writerow(r)
        print('wrote %s (%d LAT rows)' % (lout, len(lats)))


if __name__ == '__main__':
    main()
