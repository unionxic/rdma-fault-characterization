#!/usr/bin/env python3
"""summarize_v21.py - tables for the v2.1 section of V2.md, recomputed from rows_v2.py output.

usage: summarize_v21.py lap|trip|early|cells <trials.csv>
"""
import csv
import re
import statistics as st
import sys
from collections import OrderedDict, defaultdict

ROOT = {'F1': 'LOCAL_QP_ERR', 'F2b': 'REM_ACCESS', 'F3': 'RETRY_EXC', 'F4': 'RETRY_EXC'}


def cell(tag):
    return re.sub(r'_t\d+$', '', tag)


def groups(rows):
    g = OrderedDict()
    for r in rows:
        g.setdefault(cell(r['tag']), []).append(r)
    return g


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def mm(v, fmt='%.2f'):
    v = [x for x in v if x is not None]
    if not v:
        return '-'
    return (fmt + ' [' + fmt + '-' + fmt + ']') % (st.median(v), min(v), max(v))


def lap(rows):
    print('| cell | n | root cause recorded | posted after root (WQEs) | rung after root (WQEs) | root CQE still in its slot | '
          'recorded during the burst (prod at record < final ready) | parked | pe0/pe1 rc | recovered 300/300 | decline reasons |')
    print('|---|--:|---|---|---|---|---|---|---|---|---|')
    for c, rs in groups(rows).items():
        want = ROOT.get(rs[0]['fault'], '')
        ok = sum(1 for r in rs if r.get('fr_class') == want)
        parked = sum(1 for r in rs if r.get('bd_parked') == '1')
        posted = [f(r.get('bd_posted_after_root')) for r in rs]
        rung = [f(r.get('bd_rung_after_root')) for r in rs]
        still = sum(1 for r in rs if r.get('bd_root_cqe_still_in_slot') == '1')
        still_n = sum(1 for r in rs if r.get('bd_root_cqe_still_in_slot') in ('0', '1'))
        # recorded while posting was still going on: prod at the record < WQEs made ready in total
        during = sum(1 for r in rs if f(r.get('rec_prod')) is not None and f(r.get('bd_ready')) is not None
                     and f(r.get('rec_prod')) < f(r.get('bd_ready')))
        rc = defaultdict(int)
        for r in rs:
            rc['%s/%s' % (r['pe0_rc'], r['pe1_rc'])] += 1
        rec = sum(1 for r in rs if r['recover'] == '1' and r['pe0_rc'] == '0' and r['pe1_rc'] == '0'
                  and r.get('s1_final_sig') == r.get('s1_expected_sig') and r.get('s1_ok_iters') == '300')
        dec = defaultdict(int)
        for r in rs:
            d = r.get('decline_reason') or '-'
            dec[re.sub(r'\(hw_sq.*', '(...)', d)] += 1
        print('| %s | %d | **%d/%d** | %s | %s | %d/%d | %d/%d | %d | %s | %s | %s |' % (
            c, len(rs), ok, len(rs), mm(posted, '%.0f'), mm(rung, '%.0f'), still, still_n, during, len(rs), parked,
            ', '.join('%s:%d' % kv for kv in sorted(rc.items())),
            ('%d/%d' % (rec, len(rs))) if rs[0]['recover'] == '1' else '-',
            '; '.join('%s %d' % kv for kv in sorted(dec.items()))))


def trip(rows):
    print('| cell | n | first class | kernel rc | invariant record (path, d) | decline reason | kernel time (ms) | pe0/pe1 rc | watchdog r0 |')
    print('|---|--:|---|---|---|---|---|---|---|')
    for c, rs in groups(rows).items():
        cls = defaultdict(int)
        krc = defaultdict(int)
        inv = defaultdict(int)
        dec = defaultdict(int)
        rc = defaultdict(int)
        for r in rs:
            cls[r.get('fr_class') or 'NONE'] += 1
            krc[r.get('fr_kernel_rc') or '-'] += 1
            inv['%s,d=%s' % (r.get('inv_path') or '-', r.get('inv_d') or '-')] += 1
            dec[r.get('decline_reason') or '-'] += 1
            rc['%s/%s' % (r['pe0_rc'], r['pe1_rc'])] += 1
        km = [f(r.get('fail_kernel_ms')) for r in rs]
        print('| %s | %d | %s | %s | %s | %s | %s | %s | %d/%d |' % (
            c, len(rs), ', '.join('%s %d' % kv for kv in sorted(cls.items())),
            ', '.join('%s:%d' % kv for kv in sorted(krc.items())),
            ', '.join('%s:%d' % kv for kv in sorted(inv.items())),
            '; '.join('%s %d' % kv for kv in sorted(dec.items())), mm(km, '%.1f'),
            ', '.join('%s:%d' % kv for kv in sorted(rc.items())),
            sum(int(r['watchdog0']) for r in rs), len(rs)))


def early(rows):
    print('| cell | n | root cause recorded | read by (path: 1 wait, 4 sentinel) | fault -> host mailbox (ms) | '
          'post -> host mailbox (ms) | post -> device record (ms) |')
    print('|---|--:|---|---|---|---|---|')
    for c, rs in groups(rows).items():
        want = ROOT.get(rs[0]['fault'], '')
        ok = sum(1 for r in rs if r.get('fr_class') == want)
        paths = defaultdict(int)
        for r in rs:
            paths[r.get('fr_path') or '-'] += 1
        fm, pm, pd = [], [], []
        for r in rs:
            mbx, dev, flt, post = f(r.get('fr_t_mbx')), f(r.get('fr_t_dev')), f(r.get('fault_t')), f(r.get('fail_post_t'))
            if mbx and flt:
                fm.append(mbx - flt)
            if mbx and post:
                pm.append(mbx - post)
            if dev and post:
                pd.append(dev - post)
        print('| %s | %d | **%d/%d** | %s | %s | %s | %s |' % (
            c, len(rs), ok, len(rs), ', '.join('%s:%d' % kv for kv in sorted(paths.items())),
            mm(fm, '%.3f'), mm(pm, '%.3f'), mm(pd, '%.3f')))


def cells(rows):
    for c, rs in groups(rows).items():
        rc = defaultdict(int)
        for r in rs:
            rc['%s/%s' % (r['pe0_rc'], r['pe1_rc'])] += 1
        print(c, len(rs), dict(rc), 'classes', dict((k, sum(1 for r in rs if (r.get('fr_class') or 'NONE') == k))
                                                    for k in set((r.get('fr_class') or 'NONE') for r in rs)))


if __name__ == '__main__':
    globals()[sys.argv[1]](list(csv.DictReader(open(sys.argv[2]))))
