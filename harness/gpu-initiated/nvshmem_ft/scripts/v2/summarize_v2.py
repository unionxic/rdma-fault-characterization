#!/usr/bin/env python3
"""summarize_v2.py - tables for V2.md from rows_v2.py output (every number recomputed from the rows).

usage: summarize_v2.py <section> <trials.csv> [<lat.csv>]
  section: capture | oob | knobs | ringrec | lat | cells
"""
import csv
import re
import statistics as st
import sys
from collections import OrderedDict, defaultdict


def cell(tag):
    return re.sub(r'_t\d+$', '', tag)


def load(p):
    return list(csv.DictReader(open(p)))


def groups(rows):
    g = OrderedDict()
    for r in rows:
        g.setdefault(cell(r['tag']), []).append(r)
    return g


def root_class(fault):
    return {'F1': 'LOCAL_QP_ERR', 'F2b': 'REM_ACCESS', 'F3': 'RETRY_EXC', 'F4': 'RETRY_EXC'}.get(fault, '')


def capture(rows):
    print('| cell | n | root cause kept | classes recorded (count) | read by (path) | pe0 rc | leftovers |')
    print('|---|--:|---|---|---|---|---|')
    for c, rs in groups(rows).items():
        want = root_class(rs[0]['fault'])
        ok = sum(1 for r in rs if r.get('fr_class') == want)
        cls = defaultdict(int)
        paths = defaultdict(int)
        for r in rs:
            cls[r.get('fr_class') or 'NONE'] += 1
            paths[r.get('fr_path') or '-'] += 1
        rc = defaultdict(int)
        for r in rs:
            rc[r['pe0_rc']] += 1
        left = sum(int(r['leftover_rain'] or 0) + int(r['leftover_sunny'] or 0) for r in rs)
        print('| %s | %d | **%d/%d** | %s | %s | %s | %d |' % (
            c, len(rs), ok, len(rs), ', '.join('%s %d' % kv for kv in sorted(cls.items())),
            ', '.join('%s:%d' % kv for kv in sorted(paths.items())),
            ', '.join('%s:%d' % kv for kv in sorted(rc.items())), left))


def oob(rows):
    print('| cell | n | detected (OOB record) | why | not posted: canary intact | dbuf intact | PE1 data at fault iter | decline | pe0/pe1 rc | teardown r0/r1 |')
    print('|---|--:|---|---|---|---|---|---|---|---|')
    for c, rs in groups(rows).items():
        det = sum(1 for r in rs if r.get('fr_class', '').startswith('OOB_'))
        why = defaultdict(int)
        for r in rs:
            if r.get('bounds_why'):
                why[r['bounds_why']] += 1
        can_ok = sum(1 for r in rs if r.get('canary_bad') == '0')
        can_n = sum(1 for r in rs if r.get('canary_bad') not in ('', None))
        db_ok = sum(1 for r in rs if r.get('dbuf_vs_prev_bad') == '0')
        db_n = sum(1 for r in rs if r.get('dbuf_vs_prev_bad') not in ('', None))
        notok = defaultdict(int)
        for r in rs:
            x = r.get('pe1_first_notok') or 'all ok'
            notok[x.split(':')[1] if ':' in x else x] += 1
        dec = defaultdict(int)
        for r in rs:
            dec[r.get('decline_reason') or '-'] += 1
        rc = defaultdict(int)
        for r in rs:
            rc['%s/%s' % (r['pe0_rc'], r['pe1_rc'])] += 1
        td = sum(1 for r in rs if r.get('td0_returned') == '1' and r.get('td1_returned') == '1')
        print('| %s | %d | **%d/%d** | %s | %d/%d | %d/%d | %s | %s | %s | %d/%d returned |' % (
            c, len(rs), det, len(rs), ', '.join('%s:%d' % kv for kv in sorted(why.items())) or '-',
            can_ok, can_n, db_ok, db_n, ', '.join('%s %d' % kv for kv in sorted(notok.items())),
            '; '.join('%s %d' % kv for kv in sorted(dec.items())),
            ', '.join('%s:%d' % kv for kv in sorted(rc.items())), td, len(rs)))


def knobs(rows):
    print('| cell | n | recovered runs (200/200 verified, exact signal) | recovery rounds | first class | decline reasons | PE1 first bad iter | pe0/pe1 rc | watchdog r0/r1 | teardown r0/r1 |')
    print('|---|--:|---|---|---|---|---|---|---|---|')
    for c, rs in groups(rows).items():
        good = sum(1 for r in rs if r['pe0_rc'] == '0' and r['pe1_rc'] == '0' and r.get('s1_ok_iters') == '200'
                   and r.get('s1_final_sig') == r.get('s1_expected_sig'))
        rounds = [r.get('s0_rec_rounds') or '?' for r in rs]
        cls = defaultdict(int)
        for r in rs:
            cls[r.get('fr_class') or 'NONE'] += 1
        dec = defaultdict(int)
        for r in rs:
            dec[r.get('decline_reason') or '-'] += 1
        bad = defaultdict(int)
        for r in rs:
            bad[r.get('pe1_first_notok') or '-'] += 1
        rc = defaultdict(int)
        for r in rs:
            rc['%s/%s' % (r['pe0_rc'], r['pe1_rc'])] += 1
        wd = '%d/%d' % (sum(int(r['watchdog0']) for r in rs), sum(int(r['watchdog1']) for r in rs))
        td = '%d/%d' % (sum(1 for r in rs if r.get('td0_returned') == '1'),
                        sum(1 for r in rs if r.get('td1_returned') == '1'))
        print('| %s | %d | **%d/%d** | %s | %s | %s | %s | %s | %s | %s |' % (
            c, len(rs), good, len(rs), ','.join(rounds), ', '.join('%s %d' % kv for kv in sorted(cls.items())),
            '; '.join('%s %d' % kv for kv in sorted(dec.items())),
            '; '.join('%s %d' % kv for kv in sorted(bad.items())),
            ', '.join('%s:%d' % kv for kv in sorted(rc.items())), wd, td))


def ringrec(rows):
    knobs(rows)


def lat(latcsv):
    rows = load(latcsv)
    by = OrderedDict()
    for r in rows:
        by.setdefault((r.get('dir', '') + '/' if r.get('dir') else '') + cell(r['tag']), {}).setdefault(
            r['trial'], []).append(r)
    print('| cell | runs | reps | p50 us: median of run medians [min-max] | p99 us: median of run medians [min-max] | err |')
    print('|---|--:|--:|---|---|---|')
    for c, runs in by.items():
        p50s, p99s, n, err = [], [], 0, 0
        for t, reps in runs.items():
            p50s.append(st.median(float(x['p50_us']) for x in reps))
            p99s.append(st.median(float(x['p99_us']) for x in reps))
            n += len(reps)
            err += sum(int(x['err'] or 0) for x in reps)
        print('| %s | %d | %d | %.3f [%.3f-%.3f] | %.3f [%.3f-%.3f] | %d |' % (
            c, len(runs), n, st.median(p50s), min(p50s), max(p50s), st.median(p99s), min(p99s), max(p99s), err))


def cells(rows):
    for c, rs in groups(rows).items():
        rc = defaultdict(int)
        for r in rs:
            rc['%s/%s' % (r['pe0_rc'], r['pe1_rc'])] += 1
        print(c, len(rs), dict(rc))


if __name__ == '__main__':
    sec = sys.argv[1]
    if sec == 'lat':
        lat(sys.argv[2])
    else:
        globals()[sec](load(sys.argv[2]))
