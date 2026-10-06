#!/usr/bin/env python3
"""summarize.py <trials.csv> <events.csv> [lat_dir ...] -> markdown tables on stdout."""
import csv
import glob
import gzip
import os
import re
import statistics as st
import sys
from collections import Counter, OrderedDict

TRUE = {'F1': 'LOCAL_QP_ERR', 'F2b': 'REM_ACCESS', 'F3': 'RETRY_EXC', 'F4': 'RETRY_EXC'}


def load(p):
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def med(vals, nd=2):
    v = [x for x in (f(a) for a in vals) if x is not None]
    if not v:
        return '-'
    m = st.median(v)
    if len(v) == 1:
        return ('%.' + str(nd) + 'f') % m
    return ('%.' + str(nd) + 'f [%.' + str(nd) + 'f-%.' + str(nd) + 'f]') % (m, min(v), max(v))


def grp(rows, keys):
    g = OrderedDict()
    for r in rows:
        g.setdefault(tuple(r[k] for k in keys), []).append(r)
    return g


def main():
    trials = load(sys.argv[1])
    events = load(sys.argv[2])
    ev_by_tag = grp(events, ['tag'])
    out = []
    dirs = []
    for r in trials:
        if r['dir'] not in dirs:
            dirs.append(r['dir'])
    for d in dirs:
        rows = [r for r in trials if r['dir'] == d]
        if not rows:
            continue
        out.append('\n### %s (%d trials)\n' % (d, len(rows)))
        if not any(r['recover'] == '1' for r in rows):
            out.append('| fault | mode | variant | n | recorded class (first record) | status/vendor_err | path | fault -> device (ms) | device -> mailbox (us) | fault -> host API (ms) | target | teardown r0/r1 (finalize ms) | exit r0/r1 |')
            out.append('|---|---|---|--:|---|---|---|---|---|---|---|---|---|')
            for r in rows:
                r['variant'] = re.sub(r'^[A-Za-z0-9]+_(timeout|blocking)_ft\d_rec\d_?', '', r['tag'])
                r['variant'] = re.sub(r'_?t\d+$', '', r['variant']) or '-'
            for (fa, mo, va), rs in grp(rows, ['fault', 'mode', 'variant']).items():
                evs = [ev_by_tag.get((r['tag'],), [{}])[0] for r in rs]
                cls = Counter(e.get('class', '-') or '-' for e in evs)
                fps = Counter(e.get('fp', '-') or '-' for e in evs)
                paths = Counter({'1': 'poll', '2': 'exit', '3': 'bounded', '4': 'sentinel'}.get(e.get('path', ''), '-') for e in evs)
                tgt = Counter(r['pe1_rc'] for r in rs)
                td = '%d/%d returned (%s / %s)' % (sum(r['teardown0'] == 'returned' for r in rs), sum(r['teardown1'] == 'returned' for r in rs),
                                               med([r['finalize0_ms'] for r in rs], 0), med([r['finalize1_ms'] for r in rs], 0))
                ex = '%s / %s' % (','.join(sorted(set(r['pe0_rc'] for r in rs))), ','.join(sorted(set(r['pe1_rc'] for r in rs))))
                out.append('| %s | %s | %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
                    fa, mo, va, len(rs), ', '.join('%s %d' % kv for kv in cls.items()), ', '.join('%s' % k for k in fps),
                    ', '.join('%s %d' % kv for kv in paths.items()),
                    med([e.get('t_fault_to_dev_ms') for e in evs], 3), med([e.get('t_dev_to_mbx_us') for e in evs], 0),
                    med([e.get('t_fault_to_mbx_ms') for e in evs], 3),
                    ', '.join('rc%s %d' % kv for kv in tgt.items()), td, ex))
        else:
            out.append('| fault | mode | variant | n | faults fired | fault rounds | recovered ops | r0 ops ok | r1 data ok | r1 signal exact / final | declined | teardown r0/r1 | exit r0/r1 |')
            out.append('|---|---|---|--:|---|---|---|---|---|---|---|---|---|')
            for r in rows:
                r['variant'] = re.sub(r'^[A-Za-z0-9]+_(timeout|blocking)_ft\d_rec\d_?', '', r['tag'])
                r['variant'] = re.sub(r'_?t\d+$', '', r['variant']) or '-'
            for (fa, mo, va), rs in grp(rows, ['fault', 'mode', 'variant']).items():
                fin = sum(1 for r in rs if r['final_sig'] and r['final_sig'] == r['expected_sig'])
                out.append('| %s | %s | %s | %d | %s | %s | %s | %s | %s | %s | %s | %d/%d | %s |' % (
                    fa, mo, va, len(rs), '/'.join(r['faults_fired'] for r in rs), '/'.join(r['fault_rounds'] for r in rs),
                    '/'.join(r['rec_ok_ops'] or '0' for r in rs), '/'.join(r['ok_iters0'] or '0' for r in rs),
                    '/'.join(str(r['rx_data_ok']) for r in rs), '%s ; final %d/%d' % ('/'.join(str(r['rx_sig_exact']) for r in rs), fin, len(rs)),
                    ', '.join(sorted(set((r['decline_reason'] or '-') for r in rs))),
                    sum(r['teardown0'] == 'returned' for r in rs), sum(r['teardown1'] == 'returned' for r in rs),
                    '%s / %s' % (','.join(sorted(set(r['pe0_rc'] for r in rs))), ','.join(sorted(set(r['pe1_rc'] for r in rs))))))
            # timing
            evs = [e for e in events if e.get('dir') == d and e.get('d') not in (None, '')]
            if evs:
                out.append('\nRecovery rounds (ms, median [min-max]):\n')
                out.append('| fault | mode | variant | rounds | class | d | fault -> device | kernel return -> commit done | prepare / handshake / commit | commit -> replay done | kernel return -> recovered | fault -> recovered |')
                out.append('|---|---|---|--:|---|---|---|---|---|---|---|---|')
                tagmeta = {r['tag']: r for r in rows}
                for e in evs:
                    r = tagmeta.get(e['tag'], {})
                    e['fault'], e['mode'], e['variant'] = r.get('fault'), r.get('mode'), r.get('variant')
                for (fa, mo, va), es in grp(evs, ['fault', 'mode', 'variant']).items():
                    out.append('| %s | %s | %s | %d | %s | %s | %s | %s | %s / %s / %s | %s | %s | %s |' % (
                        fa, mo, va, len(es), ', '.join('%s %d' % kv for kv in Counter(e['class'] for e in es).items()),
                        ', '.join('d=%s %d' % kv for kv in Counter(e['d'] for e in es).items()),
                        med([e.get('t_fault_to_dev_ms') for e in es], 1), med([e.get('ret_to_commit_ms') for e in es]),
                        med([e.get('prepare_ms') for e in es]), med([e.get('handshake_ms') for e in es]), med([e.get('commit_ms') for e in es]),
                        med([e.get('commit_to_replayed_ms') for e in es]), med([e.get('ret_to_recovered_ms') for e in es]),
                        med([e.get('fault_to_recovered_ms') for e in es], 1)))
    # latency
    for ld in sys.argv[3:]:
        lat = OrderedDict()
        for p in sorted(glob.glob(os.path.join(ld, '*.pe0.log')) + glob.glob(os.path.join(ld, '*.pe0.log.gz'))):
            tag = os.path.basename(p).split('.pe0.log')[0]
            cell = re.sub(r'_t\d+$', '', tag.split('rec0_')[-1])
            fh = gzip.open(p, 'rt', errors='replace') if p.endswith('.gz') else open(p, errors='replace')
            for l in fh:
                if l.startswith('LAT rep'):
                    d = dict(re.findall(r'(\w+)=(\S+)', l))
                    lat.setdefault(cell, []).append(d)
        if lat:
            out.append('\n### latency (%s)\n' % ld)
            out.append('| cell | reps | p50 us median [min-max] | p99 us median [min-max] | mean us (median of reps) | errors |')
            out.append('|---|--:|---|---|---|---|')
            for c, ds in lat.items():
                out.append('| %s | %d | %s | %s | %s | %d |' % (c, len(ds), med([d['p50_us'] for d in ds], 2), med([d['p99_us'] for d in ds], 2),
                                                     med([d['mean_us'] for d in ds], 2), sum(int(d['err']) for d in ds)))
    print('\n'.join(out))


if __name__ == '__main__':
    main()
