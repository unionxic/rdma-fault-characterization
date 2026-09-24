#!/usr/bin/env python3
"""summarize.py - markdown tables from trials.csv / events.csv (rec_rows.py output).

usage: summarize.py <trials.csv> <events.csv> > summary.md
"""
import csv, re, statistics, sys
from collections import OrderedDict


def rows(p):
    try:
        return list(csv.DictReader(open(p)))
    except FileNotFoundError:
        return []


def fl(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def med(vals, fmt='{:.1f}'):
    v = [x for x in (fl(y) for y in vals) if x is not None]
    if not v:
        return '-'
    m = statistics.median(v)
    if len(v) == 1:
        return fmt.format(m)
    return (fmt + ' [' + fmt + '-' + fmt + ']').format(m, min(v), max(v))


DIAG = {'keepgpupi': 'keep_gpu_pi', 'keepgpudbr': 'keep_gpu_dbr', 'docarsvd': 'doca_cqe_rsvd', 'keepdb': 'keep_proxy_db'}


def kind(t):
    inj = t.get('inject') or ''
    k = t['fault']
    if t['fault'] in ('F1', 'F3') and ',' in inj:
        k += ' x' + str(len(inj.split(',')))
    for tag, name in DIAG.items():
        if tag in (t.get('trial') or ''):
            k += ' [DIAG ' + name + ']'
    if t.get('db_mode_r0') == 'CPU_PROXY':
        k += ' [CPU proxy]'
    return k


def main():
    T = rows(sys.argv[1])
    E = rows(sys.argv[2])
    print('## Outcomes\n')
    print('| fault | rec | wait | doorbell (r0/r1; GIN proxy thread r0/r1) | n | shots fired | recovered events | replay failed | '
          'declined | r0 ops ok | r1 data exact | signal exact | final async (r0) | teardown r0/r1 | left |')
    print('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    g = OrderedDict()
    for t in T:
        if t['fault'] == 'lat':
            continue
        g.setdefault((kind(t), t['rec'], t['wait'], t.get('db_mode_r0', '')), []).append(t)
    for (k, rec, w, dbm), ts in g.items():
        db = ','.join(sorted(set(f"{t.get('db_mode_r0') or '?'}/{t.get('db_mode_r1') or '?'}; "
                                 f"{t.get('proxy_thread_r0') or '?'}/{t.get('proxy_thread_r1') or '?'}" for t in ts)))
        n = len(ts)
        shots = ','.join(str(t['shots_fired']) for t in ts)
        recov = ','.join(str(t['recovered']) for t in ts)
        rf = ','.join(str(t['replay_failed']) for t in ts)
        dec = ','.join(str(t['declined']) for t in ts)
        ok0 = ','.join(f"{t['r0_iters_ok']}/{t['iters']}" for t in ts)
        dx = sum(1 for t in ts if t['r1_data'] == 'ok' and t['r1_iters_ok'] == t['iters'])
        se = sum(1 for t in ts if t['signal_exact'] == '1')
        fa = ','.join(sorted(set(t['final_async'] for t in ts)))
        td = ','.join(sorted(set(f"{t['abort0'] or t['teardown0']}/{t['abort1'] or t['teardown1'] or '-'}" for t in ts)))
        left = sum(int(t['left'] or 0) for t in ts)
        print(f'| {k} | {rec} | {w} | {db} | {n} | {shots} | {recov} | {rf} | {dec} | {ok0} | {dx}/{n} | {se}/{n} | {fa} | {td} | {left} |')

    print('\n## Declined runs\n')
    print('| fault | wait | n | reason | root fp / class | r0 exit | r1 outcome | r1 exit | surface (ms) | teardown r0 (ms) |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    g = OrderedDict()
    for t in T:
        if t['declined'] not in ('0', '') or t['r0_outcome'] == 'declined':
            g.setdefault((kind(t), t['wait']), []).append(t)
    for (k, w), ts in g.items():
        reasons = ','.join(sorted(set(t['decline_reason'] for t in ts)))
        fp = ','.join(sorted(set(f"{t['decline_fp']} {t['decline_class']}" for t in ts)))
        e0 = ','.join(t['r0rc'] for t in ts)
        o1 = ','.join(sorted(set(t['r1_outcome'] or '(killed)' for t in ts)))
        e1 = ','.join(t['r1rc'] for t in ts)
        print(f"| {k} | {w} | {len(ts)} | {reasons} | {fp} | {e0} | {o1} | {e1} | {med([t['surface_ms'] for t in ts])} | "
              f"{med([t['teardown0_ms'] for t in ts])} |")

    print('\n## Recovery timing (per recovered event; ms, median [min-max])\n')
    print('| fault | wait | n | detect (fault -> device) | fault -> kernel return | kernel return -> commit | prepare | '
          'handshake (REQ -> ACK) | commit | replay | kernel return -> recovered | fault -> recovered |')
    print('|---|---|---|---|---|---|---|---|---|---|---|---|')
    kindOf = {t['stem']: kind(t) for t in T}
    g = OrderedDict()
    for e in sorted(E, key=lambda e: (kindOf.get(e['stem'], e['fault']), e['wait'])):
        if e['outcome'] not in ('recovered', 'replay_failed'):
            continue
        g.setdefault((kindOf.get(e['stem'], e['fault']), e['wait']), []).append(e)
    for (k, w), es in g.items():
        rec = [e for e in es if e['outcome'] == 'recovered']
        print(f"| {k} | {w} | {len(es)} ({len(rec)} rec) | {med([e['detect_ms'] for e in es], '{:.2f}')} | "
              f"{med([e['kret_ms'] for e in es], '{:.2f}')} | {med([e['kret_to_commit_ms'] for e in es], '{:.2f}')} | "
              f"{med([e['prep_ms'] for e in es], '{:.2f}')} | {med([e['handshake_ms'] for e in es], '{:.2f}')} | "
              f"{med([e['commit_ms'] for e in es], '{:.2f}')} | {med([e['replay_ms'] for e in rec], '{:.2f}')} | "
              f"{med([e['kret_to_recovered_ms'] for e in rec], '{:.2f}')} | "
              f"{med([e['fault_to_recovered_ms'] for e in rec], '{:.2f}')} |")

    print('\n## Library step costs (us, median [min-max]; sender side, receiver side)\n')
    print('| fault | wait | n | QPs | to ERR | drain | prepare total | 2RST | resync | INIT/RTR/RTS | commit total | '
          'rx prepare | rx commit | CQEs err/ok in window |')
    print('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for (k, w), es in g.items():
        ce = ','.join(sorted(set(f"{e['cqe_err']}/{e['cqe_ok']}" for e in es)))
        print(f"| {k} | {w} | {len(es)} | {','.join(sorted(set(e['nqp'] for e in es)))} | {med([e['err_us'] for e in es], '{:.0f}')} | "
              f"{med([e['drain_us'] for e in es], '{:.0f}')} | {med([e['prep_us'] for e in es], '{:.0f}')} | "
              f"{med([e['reset_us'] for e in es], '{:.0f}')} | {med([e['resync_us'] for e in es], '{:.0f}')} | "
              f"{med([e['connect_us'] for e in es], '{:.0f}')} | {med([e['commit_us'] for e in es], '{:.0f}')} | "
              f"{med([e['rx_prep_us'] for e in es], '{:.0f}')} | {med([e['rx_commit_us'] for e in es], '{:.0f}')} | {ce} |")

    print('\n## Signal reconciliation\n')
    print('| fault | wait | events | d=1 (replayed put+ADD) | d=0 (ADD had landed; nothing replayed) | replay failed -> new round |')
    print('|---|---|---|---|---|---|')
    for (k, w), es in g.items():
        d1 = sum(1 for e in es if e['d'] == '1')
        d0 = sum(1 for e in es if e['d'] == '0')
        rf = sum(1 for e in es if e['outcome'] == 'replay_failed')
        print(f'| {k} | {w} | {len(es)} | {d1} | {d0} | {rf} |')

    L = [t for t in T if t['fault'] == 'lat']
    if L:
        print('\n## Overhead (no fault; put+signal+flush per iteration on the GPU)\n')
        print('| bytes | wait | recovery flag | runs | samples | p50 (us) | p99 (us) | CPU (cores) | data |')
        print('|---|---|---|---|---|---|---|---|---|')
        g = OrderedDict()
        for t in L:
            mm = re.search(r'_b(\d+)(?:r|px)\d+$', t['stem'])
            b = mm.group(1) if mm else '?'
            g.setdefault((b, t['wait'], t['rec'] + (' ' + t['db_mode_r0'] if t.get('db_mode_r0') else '')), []).append(t)
        for (b, w, r), ts in sorted(g.items(), key=lambda x: (int(x[0][0]) if x[0][0].isdigit() else 0, x[0][1], x[0][2])):
            cores = [fl(t['lat_cpu_ms']) / fl(t['lat_wall_ms']) for t in ts if fl(t['lat_cpu_ms']) and fl(t['lat_wall_ms'])]
            print(f"| {b} | {w} | {r} | {len(ts)} | {sum(int(t['lat_n'] or 0) for t in ts)} | "
                  f"{med([t['lat_p50_us'] for t in ts], '{:.2f}')} | {med([t['lat_p99_us'] for t in ts], '{:.2f}')} | "
                  f"{med(cores, '{:.2f}')} | {','.join(sorted(set(t['lat_data'] for t in ts)))} |")


if __name__ == '__main__':
    main()
