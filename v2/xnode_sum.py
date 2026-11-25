#!/usr/bin/env python3
# xnode_sum.py [summary.txt ...]: tables over xnode.sh summary lines (default: every runs/xnode-*/summary.txt).
# Per case, direction and stream (fwd = Q->P, rev = P->Q): n; runs where that stream was cut by the fault; runs where its
# requester's QP was in ERR when its record was read (else the healthy requester's live record, which no ACK moves while the
# other side is down); unacked = next_send_psn - last_acked_psn - 1 in that record; lag = PSN
# after what the responder executed (its memory) - (last_acked_psn + 1), lag < 0 = acked AHEAD of executed; the responder's
# own record against its memory (not for H's forward stream: P's memory moves on after its immediate rebuild); errors seen in the recovery rounds; the final outcome. Then M4 (are the records frozen) and
# the lag distributions.
import collections, glob, os, statistics, sys

M = 1 << 24
NW = {'w': 8192, 'm': 512, 'a': 8192, 'x': 8192, 'r': 1024}
def s24(x): x %= M; return x - M if x >= M // 2 else x

def parse(line):
    d = {}
    for t in line.split():
        if '=' in t:
            k, v = t.split('=', 1)
            d.setdefault(k, v)  # first occurrence
    return d

def num(d, k, default=None):
    v = d.get(k)
    return default if v is None or v == '' else int(v, 0)

def errs(d, side):  # distinct non-flush CQE errors of one side over the first look and all rounds
    e = set()
    for k in [k for k in d if k.endswith('.err_synd')]:
        t = k[:-len('.err_synd')]
        if (side == 'q') == (t in ('W1', 'WQF') or t.startswith('WQ')):
            e.add('%s/%s' % (d[k], d.get(t + '.err_vendor')))
    return e

def outcome(d, op, fwd):
    n = NW[op]
    nmsg = {'w': n, 'm': n, 'a': 0, 'x': n // 2, 'r': n}[op]
    nat = {'w': 0, 'm': 0, 'a': n, 'x': n // 2, 'r': 0}[op]
    w, mem, res = ('WQF', 'M2', 'R2') if fwd else ('WPF', 'QM2', 'PR2')
    o = []
    if num(d, w + '.pend') or num(d, w + '.ok') < n: o.append('not_complete')
    if num(d, mem + '.corrupt'): o.append('corrupt')
    if num(d, mem + '.reexec'): o.append('reexec')
    ctr = num(d, mem + '.ctr')
    if nat and ctr > nat: o.append('atomic_double+%d' % (ctr - nat))
    if num(d, res + '.mismatch'): o.append('atomic_value')
    if num(d, mem + '.msgs') < nmsg or (nat and ctr < nat): o.append('lost' if 'not_complete' not in o else 'missing')
    return ' '.join(o) or 'exact'

def psn_outcome(d):
    r = []
    for name, ok, n, mem in (('A>B', 'W2', 16, 'M2'), ('B>A', 'PW2', 12, 'QM')):
        if num(d, ok + '.other') or num(d, ok + '.pend'):
            r.append('%s:error(%s/%s)' % (name, d.get(ok + '.err_synd'), d.get(ok + '.err_vendor')))
        elif num(d, mem + '.msgs') < n: r.append('%s:lost%d' % (name, n - num(d, mem + '.msgs')))
        elif num(d, mem + '.reexec') or num(d, mem + '.corrupt'): r.append('%s:dup' % name)
        else: r.append('%s:exact' % name)
    return ' '.join(r)

def stream(d, case, fwd):  # (requester record acked, next, in ERR?, exec, responder record rcv, cut by the fault)
    op, f, v = case[0], case[2], case[3:]
    if fwd:
        acked, nxt, err = num(d, 'Q1.acked'), num(d, 'Q1.next'), num(d, 'Q1.st') == 6
        rcv = num(d, {'a': 'P1.rcv', 'b': 'P1.e_rcv', 'c': 'P1.r_rcv'}[f]) if 'H' not in v else num(d, 'P1.b_rcv')
        cut = num(d, 'W1.ok') < NW[op] if 'H' not in v else num(d, 'P1.b_landed') + num(d, 'P1.b_ctr') < NW[op]  # H: Q stays healthy
        return acked, nxt, err, num(d, 'M1.exec'), rcv, cut, num(d, 'W1.fpsn')
    pre = 'P1.b_' if 'H' in v else 'P1.r_' if f == 'c' else 'P1.'
    err = 'H' in v or f in 'bc' or num(d, 'P1.st') == 6
    return num(d, pre + 'acked'), num(d, pre + 'next'), err, num(d, 'QM1.exec'), num(d, 'Q1.rcv'), num(d, 'PW1.ok') < NW[op], None

files = sys.argv[1:] or sorted(glob.glob(os.path.expanduser('~/rdma-recovery/runs/xnode-*/summary.txt')))
groups = collections.OrderedDict()
for f in files:
    for line in open(f):
        if line.startswith('case=') and ('rounds=' in line or 'psn_' in line or 'start_failed' in line):
            d = parse(line)
            groups.setdefault((d['case'], d['dir'], d.get('tmo', '?')), []).append(d)

print('| case | dir | tmo | stream | n | cut by fault | req QP in ERR | unacked>0 | lag>0 | acked AHEAD | lag min/med/max | resp record = memory | acked+1 inside a WR | rounds | errors seen (runs) | final outcome |')
print('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
lags, m4 = collections.OrderedDict(), collections.OrderedDict()
for (case, dr, tmo), runs in sorted(groups.items()):
    ok = [d for d in runs if 'start_failed' not in d]
    bad = len(runs) - len(ok)
    if case.startswith('psn_'):
        c = collections.Counter(psn_outcome(d) for d in ok)
        print('| %s | %s | %s | both | %d%s | - | - | - | - | - | - | - | - | - | - | %s |' % (case, dr, tmo, len(ok), ' (+%d start fail)' % bad if bad else '',
              '; '.join('%s x%d' % kv for kv in c.items())))
        continue
    op = case[0]
    for fwd in (True, False):
        cut = inerr = una = lagp = ahead = rcvok = midwr = 0
        L, rounds, es, oc = [], collections.Counter(), collections.Counter(), collections.Counter()
        for d in ok:
            acked, nxt, err, exe, rcv, c, fpsn = stream(d, case, fwd)
            cut += c; inerr += err
            if op != 'r' and acked is not None and not (fwd and 'H' in case[3:]):  # H: Q's record moves on, no lag at the fault
                una += (nxt - acked - 1) % M > 0
                lag = s24(exe - acked - 1)
                L.append(lag); lagp += lag > 0; ahead += lag < 0
            if op != 'r' and rcv is not None and not (fwd and 'H' in case[3:]): rcvok += rcv == exe
            if fwd and c and fpsn is not None and err: midwr += (acked + 1) % M != fpsn
            rounds[num(d, 'rounds')] += 1
            for e in errs(d, 'q' if fwd else 'p'): es[e] += 1
            oc[outcome(d, op, fwd)] += 1
        lags[(case, dr, tmo, 'fwd' if fwd else 'rev')] = L
        st = '%d/%d/%d' % (min(L), statistics.median(L), max(L)) if L else '-'
        print('| %s | %s | %s | %s | %d | %d | %d | %d | %d | %d | %s | %s | %s | %s | %s | %s |' % (
            case, dr, tmo, 'fwd' if fwd else 'rev', len(ok), cut, inerr, una, lagp, ahead, st, rcvok if op != 'r' else '-',
            midwr if fwd else '-', ' '.join('%s:%d' % kv for kv in sorted(rounds.items())),
            ', '.join('%s x%d' % kv for kv in sorted(es.items())) or '-', '; '.join('%s x%d' % kv for kv in sorted(oc.items()))))
    # M4: the failed QP's record read at the transition, again after the flush, and 1 s later (runs without variant)
    for d in ok:
        if case[3:] or 'Q1b.acked' not in d: continue
        f = case[2]
        if f == 'a':
            r0 = 'Q1.e_' if op == 'r' else 'PO.rec0_'  # reads: Q's watch failed it
            same = (num(d, r0 + 'acked'), num(d, r0 + 'next')) == (num(d, 'Q1.acked'), num(d, 'Q1.next')) == (num(d, 'Q1b.acked'), num(d, 'Q1b.next'))
            rfz = num(d, 'Q1.rcv') == num(d, 'Q1b.rcv') == (num(d, 'QM1.exec') if op != 'r' else num(d, 'Q1.rcv'))
        else:
            same = (num(d, 'Q1.acked'), num(d, 'Q1.next')) == (num(d, 'Q1b.acked'), num(d, 'Q1b.next'))
            k = 'P1.e_rcv' if f == 'b' else 'P1.r_reset_rcv'
            rfz = num(d, k) == num(d, 'P1.rcv') == num(d, 'P1b.rcv') == num(d, 'M1.exec')
        c = m4.setdefault((case, dr), [0, 0, 0])
        c[0] += 1; c[1] += same; c[2] += rfz

print('\nM4: n | requester acked/next equal at the transition, after the flush and 1 s later | responder rcv equal at the transition (b: ERR; c: after RESET), later, 1 s later and = memory')
for k, c in m4.items(): print('%s %s: n=%d acked_final=%d rcv_frozen_and_exact=%d' % (k[0], k[1], *c))
print('\nlag (packets the responder executed whose ACK the requester had not seen), value:count')
for k, L in lags.items():
    if L: print('%s %s tmo=%s %s: %s' % (*k, ' '.join('%d:%d' % kv for kv in sorted(collections.Counter(L).items()))))

print('\nC3: forward outcome by where acked+1 fell (64 KiB writes; Q failed, its record in ERR), runs')
for (case, dr, tmo), runs in sorted(groups.items()):
    if case[0] != 'm': continue
    c = collections.Counter()
    for d in runs:
        if 'start_failed' in d or num(d, 'Q1.st') != 6: continue
        inside = (num(d, 'Q1.acked') + 1) % M != num(d, 'W1.fpsn') and num(d, 'W1.ok') < NW['m']
        c[('acked+1 inside WR' if inside else 'acked+1 at WR start', outcome(d, 'm', True))] += 1
    print('%s %s tmo=%s: %s' % (case, dr, tmo, '; '.join('%s -> %s x%d' % (k[0], k[1], n) for k, n in sorted(c.items()))))

print('\nC4: atomics per stream: runs | runs with executed-but-unacked (lag>0) | double executions (sum) | runs short of executions | runs with a wrong returned value | runs not complete')
for (case, dr, tmo), runs in sorted(groups.items()):
    if case[0] not in 'ax': continue
    nat = NW[case[0]] if case[0] == 'a' else NW['x'] // 2
    for fwd, mem, res, w in ((True, 'M2', 'R2', 'WQF'), (False, 'QM2', 'PR2', 'WPF')):
        ok = [d for d in runs if 'start_failed' not in d]
        lagp = sum(1 for d in ok if (lambda s: s[0] is not None and s24(s[3] - s[0] - 1) > 0)(stream(d, case, fwd)))
        dbl = sum(max(0, num(d, mem + '.ctr') - nat) for d in ok)
        short = sum(1 for d in ok if num(d, mem + '.ctr') < nat)
        val = sum(1 for d in ok if num(d, res + '.mismatch'))
        nc = sum(1 for d in ok if num(d, w + '.ok') < NW[case[0]])
        print('%s %s tmo=%s %s: n=%d lag>0=%d double=%d short=%d wrong_value=%d not_complete=%d' % (case, dr, tmo, 'fwd' if fwd else 'rev', len(ok), lagp, dbl, short, val, nc))
