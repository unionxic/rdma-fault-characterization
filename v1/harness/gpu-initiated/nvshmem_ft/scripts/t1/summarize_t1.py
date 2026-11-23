#!/usr/bin/env python3
"""summarize_t1.py - tables for TRANSPARENT_T1.md from trials_t1.csv / rounds_t1.csv (rows_t1.py).

usage: summarize_t1.py outcomes <trials.csv> [<rounds.csv>]
       summarize_t1.py rounds <trials.csv> <rounds.csv>
       summarize_t1.py lat <trials.csv>
       summarize_t1.py flap <trials.csv> [<rounds.csv>]
       summarize_t1.py timing <trials.csv> <rounds.csv>
       summarize_t1.py incommit <trials.csv> <rounds.csv>   (run in the results dir, per-trial logs unpacked)
       summarize_t1.py fetch <trials.csv> [<rounds.csv>]
Cells are keyed by (fault, mode, TAG part of the tag). Numbers are median [min-max].
"""
import csv, re, statistics as st, sys
from collections import defaultdict, OrderedDict


def load(p):
    with open(p) as f:
        return list(csv.DictReader(f))


def cell(t):
    m = re.match(r'^(\w+?)_(loop|mt|lat)_ft\d_t1\d_?(.*)_t\d+$', t['tag'])
    return (t['dir'] + ':', t['fault'], t['mode'], m.group(3) if m else '')


def med(xs, fmt='%.2f'):
    xs = [float(x) for x in xs if x not in ('', None)]
    if not xs:
        return '-'
    return (fmt + ' [' + fmt + '-' + fmt + ']') % (st.median(xs), min(xs), max(xs))


def outcomes(trials, rounds):
    by = OrderedDict()
    for t in trials:
        by.setdefault(cell(t), []).append(t)
    rby = defaultdict(list)
    for r in rounds:
        rby[(r['dir'], r['tag'])].append(r)
    print('| cell | n | transparent | declined | failed | void | rounds (init/resp) | re-posted per initiator round (0/1/2/>2) | status_bad | slots bad (GPU/host) | signal exact | leftovers |')
    print('|---|--:|---|---|---|---|---|---|---|---|---|---|')
    for c, ts in by.items():
        n = len(ts)
        cnt = defaultdict(int)
        for t in ts:
            cnt[t['outcome']] += 1
        ri = sum(int(t.get('rounds_init') or 0) for t in ts)
        rr = sum(int(t.get('rounds_resp') or 0) for t in ts)
        rep = defaultdict(int)
        for t in ts:
            for r in rby[(t['dir'], t['tag'])]:
                if r['role'] == 'initiator':
                    k = int(r['reposted'] or 0)
                    rep['>2' if k > 2 else str(k)] += 1
        sb = sum(int(t.get('status_bad') or 0) > 0 for t in ts)
        gb = sum(int(t.get('gpu_bad') or 0) > 0 for t in ts)
        hb = sum(int(t.get('host_bad') or 0) > 0 for t in ts)
        se = sum(t.get('sig_exact') == '1' for t in ts)
        lo = sum(int(t.get('leftover_rain') or 0) + int(t.get('leftover_sunny') or 0) for t in ts)
        print(f"| {' '.join(c)} | {n} | {cnt['transparent']} | {cnt['declined']} | {cnt['failed']} | {cnt['void']} | {ri}/{rr} | "
              f"{rep['0']}/{rep['1']}/{rep['2']}/{rep['>2']} | {sb} | {gb}/{hb} | {se}/{n} | {lo} |")


def rounds_table(trials, rounds):
    tt = {(t['dir'], t['tag']): t for t in trials}
    by = OrderedDict()
    for r in rounds:
        if r['role'] != 'initiator':
            continue
        by.setdefault(cell(tt[(r['dir'], r['tag'])]), []).append(r)
    print('| cell | rounds | total ms | quiesce | prepare | handshake | commit | finish |')
    print('|---|--:|---|---|---|---|---|---|')
    for c, rs in by.items():
        print(f"| {' '.join(c)} | {len(rs)} | {med([r['total_ms'] for r in rs])} | {med([r['quiesce_ms'] for r in rs], '%.3f')} | "
              f"{med([r['prepare_ms'] for r in rs], '%.3f')} | {med([r['handshake_ms'] for r in rs])} | {med([r['commit_ms'] for r in rs])} | "
              f"{med([r['finish_ms'] for r in rs], '%.3f')} |")


def lat(trials):
    """per cell: 5 runs x 5 reps (each rep = N operations, one p50/p99). Runs are bimodal on this
    cluster (e.g. 12.4 vs 14.1 us), so the headline is the median over all reps, with the range of
    the per-run medians next to it."""
    by = OrderedDict()
    for t in trials:
        if t['mode'] != 'lat':
            continue
        by.setdefault(cell(t)[3], []).append(t)
    print('| cell | runs x reps | p50 us (median of all reps) | per-run median p50, range | p99 us (median of all reps) |')
    print('|---|--:|---|---|---|')
    for c, ts in by.items():
        ts = [t for t in ts if t.get('lat_p50')]
        a50 = [float(x) for t in ts for x in t['lat_p50'].split(';')]
        a99 = [float(x) for t in ts for x in t['lat_p99'].split(';')]
        r50 = [st.median([float(x) for x in t['lat_p50'].split(';')]) for t in ts]
        print(f"| {c} | {len(ts)} x {len(a50) // max(len(ts), 1)} | {st.median(a50):.3f} | {min(r50):.3f}-{max(r50):.3f} | {st.median(a99):.3f} |")


def flap(trials, rounds):
    rby = defaultdict(list)
    for r in rounds:
        rby[(r['dir'], r['tag'])].append(r)
    by = OrderedDict()
    for t in trials:
        if t['fault'] != 'FLAP':
            continue
        by.setdefault(t['dir'] + ':' + cell(t)[3], []).append(t)
    print('| cell | n | transparent | declined | failed | RETRY_EXC after the cut start (s) | slowest operation (s) | recovery rounds | sunny GID index before->after | GID re-lookup moves |')
    print('|---|--:|---|---|---|---|---|---|---|---|')
    for c, ts in by.items():
        cnt = defaultdict(int)
        det = []
        moves = defaultdict(int)
        for t in ts:
            cnt[t['outcome']] += 1
            if t.get('first_record_mono0') and t.get('cut_start_rain_mono_ms'):
                det.append((float(t['first_record_mono0']) - float(t['cut_start_rain_mono_ms'])) / 1e3)
            for g in (t.get('gid_moves0', ''), t.get('gid_moves1', '')):
                for x in g.split(';'):
                    mm = re.search(r'index (\d+) -> (\d+)', x)
                    if mm:
                        moves[f'{mm.group(1)}->{mm.group(2)}'] += 1
        rr = sum(int(t.get('rounds_init') or 0) for t in ts)
        sm = defaultdict(int)
        for t in ts:
            sm[f"{t.get('gid_s', '')}->{t.get('gid_s_after', '')}"] += 1
        print(f"| {c} | {len(ts)} | {cnt['transparent']} | {cnt['declined']} | {cnt['failed']} | {med(det)} ({len(det)}) | {med([float(t['max_op_us']) / 1e6 for t in ts if t.get('max_op_us')])} | {rr} | "
              f"{', '.join(f'{k} x{v}' for k, v in sm.items())} | {', '.join(f'{k} x{v}' for k, v in moves.items()) or '-'} |")


def timing(trials, rounds):
    """per cell: the application's slow operation, fault -> resumed (host CLOCK_MONOTONIC of PE0; a
    fault fired on PE1 is moved to PE0's clock with the measured offset), record -> recovered"""
    rby = defaultdict(list)
    for r in rounds:
        if r['role'] == 'initiator':
            rby[(r['dir'], r['tag'])].append(r)
    by = OrderedDict()
    for t in trials:
        if t['outcome'] != 'transparent' or not rby[(t['dir'], t['tag'])]:
            continue
        by.setdefault(cell(t), []).append(t)
    print('| cell | runs | slow operation (ms) | fault -> resumed (ms) | record -> recovered (ms) | round (ms) |')
    print('|---|--:|---|---|---|---|')
    for c, ts in by.items():
        slow, f2r, r2r, tot = [], [], [], []
        for t in ts:
            slow.append(float(t['max_op_us']) / 1e3)
            end = t.get('max_end_mono0')
            shot = None
            if t.get('first_shot_mono0'):
                shot = float(t['first_shot_mono0'])
            elif t.get('first_shot_mono1') and t.get('off10'):
                shot = float(t['first_shot_mono1']) - float(t['off10'])
            # only for one fault per run in the single-stream loop (else the slowest op need not be
            # the one the first shot hit)
            if end and shot is not None and t['fault'] in ('F1', 'F3') and t['mode'] == 'loop':
                f2r.append(float(end) - shot)
            rs = rby[(t['dir'], t['tag'])]
            if t.get('first_record_mono0'):
                r2r.append(float(rs[0]['end_mono_ms']) - float(t['first_record_mono0']))
            tot.append(float(rs[0]['total_ms']))
        print(f"| {' '.join(c)} | {len(ts)} | {med(slow)} | {med(f2r)} | {med(r2r)} | {med(tot)} |")


def incommit(trials, rounds):
    """F1x5 with an in-commit shot (SHOTS containing -1): did the shot hit the re-post? The round k in
    whose commit it fired re-based to B_k; the next round must find its first unfinished and first
    unexecuted WQE at B_k (C = U = B_k), i.e. it re-posts exactly what round k re-posted. Needs the
    per-trial logs (shot time) next to the CSVs: <dir>/<tag>.pe0.log."""
    import os
    by = defaultdict(list)
    for r in rounds:
        if r['role'] == 'initiator':
            by[(r['dir'], r['tag'])].append(r)
    res = OrderedDict()
    for t in trials:
        if t['fault'] != 'F1x5':
            continue
        lp = os.path.join(t['dir'], t['tag'] + '.pe0.log')
        shot = None
        if os.path.exists(lp):
            for line in open(lp, errors='replace'):
                m = re.search(r'in-commit shot fire_mono_ms=([\d.]+)', line)
                if m:
                    shot = float(m.group(1))
        c = res.setdefault(t['dir'], [0, 0, 0])
        c[0] += 1
        if shot is None:
            continue
        c[1] += 1
        rs = sorted(by[(t['dir'], t['tag'])], key=lambda r: float(r['end_mono_ms']))
        after = [r for r in rs if float(r['end_mono_ms']) > shot]
        if len(after) >= 2 and int(after[1]['C']) == int(after[0]['B']) == int(after[1]['U']):
            c[2] += 1
    print('| set | F1x5 trials | with an in-commit shot | next round re-posts exactly the interrupted re-post |')
    print('|---|--:|--:|--:|')
    for d, c in res.items():
        print(f'| {d} | {c[0]} | {c[1]} | {c[2]} |')


def fetch(trials, rounds):
    """--fetch cells: what happened to the fetching atomic. 'in range -> declined' counts trials whose
    DECLINE reason names the un-re-postable WQE; 'completed -> recovered' counts transparent trials
    with a recovery round (the fault landed after the fetch completed)."""
    by = OrderedDict()
    for t in trials:
        if t.get('fetch') != '1':
            continue
        by.setdefault(cell(t), []).append(t)
    print('| cell | n | transparent | declined | failed | fetch in the unfinished range -> declined | fetch completed -> recovered | poison from the failed iteration on | stale values | PE1 counter = fetches (+1) | finalize ms |')
    print('|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|')
    for c, ts in by.items():
        cnt = defaultdict(int)
        ingap = comp = poisoned = stale = ctr = 0
        fin = []
        for t in ts:
            cnt[t['outcome']] += 1
            rsn = (t.get('decline_reason0', '') + t.get('decline_reason1', ''))
            if 'cannot be re-posted' in rsn:
                ingap += 1
            if t['outcome'] == 'transparent' and int(t.get('rounds_init') or 0) > 0:
                comp += 1
            if t['outcome'] == 'declined':
                poisoned += (t.get('fetch_first_poison') not in ('', '-1') and t.get('fetch_first_poison') == t.get('first_bad')
                             and fnum(t.get('fetch_poison_before_bad'), 1) == 0)
                ctr += t.get('fetch_decl_ok') == '1'
                if t.get('finalize_ms0'):
                    fin.append(float(t['finalize_ms0']))
            stale += fnum(t.get('fetch_stale'), 0) > 0
        print(f"| {' '.join(c)} | {len(ts)} | {cnt['transparent']} | {cnt['declined']} | {cnt['failed']} | {ingap} | {comp} | "
              f"{poisoned}/{cnt['declined']} | {stale} | {ctr}/{cnt['declined']} | {med(fin)} |")


def sock(trials, rounds):
    """library-socket outage cells (SOCK: no RDMA fault; SOCK1: F1 after the outage)."""
    by = OrderedDict()
    for t in trials:
        if t['fault'] not in ('SOCK', 'SOCK1'):
            continue
        by.setdefault(cell(t), []).append(t)
    print('| cell | n | transparent | declined | failed | socket lost (PE0/PE1) | errno | back (PE0/PE1) | outage -> back (s) | recovery rounds | iptables rules left |')
    print('|---|--:|--:|--:|--:|---|---|---|---|--:|--:|')
    for c, ts in by.items():
        cnt = defaultdict(int)
        l0 = l1 = b0 = b1 = 0
        err = defaultdict(int)
        back = []
        left = 0
        for t in ts:
            cnt[t['outcome']] += 1
            l0 += int(t.get('sock_lost0') or 0) > 0
            l1 += int(t.get('sock_lost1') or 0) > 0
            b0 += int(t.get('sock_back0') or 0) > 0
            b1 += int(t.get('sock_back1') or 0) > 0
            if t.get('sock_lost_errno0'):
                err[t['sock_lost_errno0']] += 1
            if t.get('sock_back_mono0') and t.get('sock_start_rain_mono_ms'):
                back.append((float(t['sock_back_mono0']) - float(t['sock_start_rain_mono_ms'])) / 1e3)
            left += int(t.get('iptables_left') or 0)
        rr = sum(int(t.get('rounds_init') or 0) for t in ts)
        print(f"| {' '.join(c)} | {len(ts)} | {cnt['transparent']} | {cnt['declined']} | {cnt['failed']} | {l0}/{l1} | "
              f"{', '.join(f'{k} x{v}' for k, v in err.items()) or '-'} | {b0}/{b1} | {med(back)} | {rr} | {left} |")


def dci(trials, rounds):
    """per cell: DCIs reset by the rounds (RECOVERED line), pending or failed."""
    tt = {(t['dir'], t['tag']): t for t in trials}
    by = OrderedDict()
    for r in rounds:
        if r['role'] != 'initiator' or not r.get('dci_reset'):
            continue
        by.setdefault(cell(tt[(r['dir'], r['tag'])]), []).append(r)
    print('| cell | initiator rounds | DCIs reset (cumulative per process, last round) | pending | failed | fill CTAs |')
    print('|---|--:|---|---|---|---|')
    for c, rs in by.items():
        last = rs[-1]
        fills = sorted(set(tt[(r['dir'], r['tag'])].get('fill_ctas', '') for r in rs))
        print(f"| {' '.join(c)} | {len(rs)} | {sorted(set(r['dci_reset'] for r in rs))} | {sorted(set(r['dci_pending'] for r in rs))} | "
              f"{sorted(set(r['dci_failed'] for r in rs))} | {', '.join(f for f in fills if f) or '-'} |")


def fnum(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


if __name__ == '__main__':
    what = sys.argv[1]
    trials = load(sys.argv[2])
    rounds = load(sys.argv[3]) if len(sys.argv) > 3 else []
    {'outcomes': lambda: outcomes(trials, rounds), 'rounds': lambda: rounds_table(trials, rounds),
     'lat': lambda: lat(trials), 'flap': lambda: flap(trials, rounds),
     'timing': lambda: timing(trials, rounds), 'incommit': lambda: incommit(trials, rounds),
     'fetch': lambda: fetch(trials, rounds), 'sock': lambda: sock(trials, rounds),
     'dci': lambda: dci(trials, rounds)}[what]()
