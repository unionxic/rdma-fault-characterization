#!/usr/bin/env python3
"""summarize_v21.py - tables for the v2.1 section of V2.md, recomputed from rows_v2.py output.

usage: summarize_v21.py lap|trip|early|amo|mcta|cells <trials.csv>
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


def amo(rows):
    """v2.1 third review, item 2: what the fetch-ADDs of the failing kernel returned."""
    print('| cell | n | fault surfaced (kernel rc -1) | fetches returned after the FT status was set | '
          'of those: stale (dup) | poison | fresh | stale before the status | device poison count | '
          'hang (watchdog) | pe0/pe1 rc |')
    print('|---|--:|---|---|---|---|---|---|---|---|---|')
    for c, rs in groups(rows).items():
        g = lambda k: sum(int(r.get(k) or 0) for r in rs)
        rc = defaultdict(int)
        for r in rs:
            rc['%s/%s' % (r['pe0_rc'], r['pe1_rc'])] += 1
        fk = sum(1 for r in rs if int(r.get('amo_fail_kernels') or 0) > 0)
        per = lambda k: mm([f(r.get(k)) for r in rs], '%.0f')
        print('| %s | %d | %d/%d | %s (sum %d) | %s (sum %d) | %s (sum %d) | %d | %d | %s | %d/%d | %s |' % (
            c, len(rs), fk, len(rs), per('amo_after_err'), g('amo_after_err'), per('amo_after_err_dup'),
            g('amo_after_err_dup'), per('amo_after_err_poison'), g('amo_after_err_poison'),
            g('amo_after_err_fresh'), g('amo_before_err_dup'),
            ','.join(r.get('fetch_poisoned_dev') or '-' for r in rs)[:40],
            sum(int(r.get('watchdog_any') or 0) for r in rs), len(rs),
            ', '.join('%s:%d' % kv for kv in sorted(rc.items()))))


def mcta(rows):
    """v2.1 third review, item 1: park from another kernel (sentinel) or CTA while 4 CTAs post."""
    print('| cell | n | root cause recorded | recorded (and parked) by | posted after root | rung after root | '
          'parked | recovered 300/300 exact | prod_before / parked_before (REC) | pe0/pe1 rc |')
    print('|---|--:|---|---|---|---|---|---|---|---|')
    for c, rs in groups(rows).items():
        want = ROOT.get(rs[0]['fault'], '')
        ok = sum(1 for r in rs if r.get('fr_class') == want)
        by = defaultdict(int)
        for r in rs:
            p = r.get('recby_path') or r.get('fr_path') or '-'
            name = {'4': 'sentinel', '1': 'poster wait', '3': 'bounded'}.get(p, p)
            if p == '1':
                name += ' (CTA %s)' % (r.get('recby_by_cta') or '?')
            by[name] += 1
        rc = defaultdict(int)
        for r in rs:
            rc['%s/%s' % (r['pe0_rc'], r['pe1_rc'])] += 1
        rec = sum(1 for r in rs if r['recover'] == '1' and r['pe0_rc'] == '0' and r['pe1_rc'] == '0'
                  and r.get('s1_final_sig') == r.get('s1_expected_sig') and r.get('s0_ok_iters') == r.get('s1_ok_iters')
                  and r.get('s1_ok_iters') not in ('', '0'))
        pb = [r.get('rec_prod_before', '') + '/' + r.get('rec_parked_before', '') for r in rs if r.get('rec_prod_before')]
        print('| %s | %d | **%d/%d** | %s | %s | %s | %d | %s | %s | %s |' % (
            c, len(rs), ok, len(rs), ', '.join('%s %d' % kv for kv in sorted(by.items())),
            mm([f(r.get('bd_posted_after_root')) for r in rs], '%.0f'),
            mm([f(r.get('bd_rung_after_root')) for r in rs], '%.0f'),
            sum(1 for r in rs if r.get('bd_parked') == '1'),
            ('%d/%d' % (rec, len(rs))) if rs[0]['recover'] == '1' else '-',
            ' '.join(pb[:3]) + (' ...' if len(pb) > 3 else ''),
            ', '.join('%s:%d' % kv for kv in sorted(rc.items()))))


def cells(rows):
    for c, rs in groups(rows).items():
        rc = defaultdict(int)
        for r in rs:
            rc['%s/%s' % (r['pe0_rc'], r['pe1_rc'])] += 1
        print(c, len(rs), dict(rc), 'classes', dict((k, sum(1 for r in rs if (r.get('fr_class') or 'NONE') == k))
                                                    for k in set((r.get('fr_class') or 'NONE') for r in rs)))


if __name__ == '__main__':
    globals()[sys.argv[1]](list(csv.DictReader(open(sys.argv[2]))))
