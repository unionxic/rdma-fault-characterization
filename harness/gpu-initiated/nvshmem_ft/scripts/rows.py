#!/usr/bin/env python3
"""rows.py - per-trial logs (run_trial.sh) -> trials.csv (one row per trial) and events.csv (one row
per fault round seen by the initiator).

usage: rows.py <logdir> [<logdir> ...] --trials T.csv --events E.csv

Times are CLOCK_MONOTONIC ms on rain (PE0). Fault times: F1 = hook shot fire_mono_ms (PE0 log);
F3 = hook shot on sunny converted with the OOB clock offset (CLOCK line, min-RTT of 30 pings);
F2b = the driver's FAULT line (after the rkeys were corrupted, before the put kernel);
F4 = sunny's CLOCK_MONOTONIC right before the SIGKILL (runner), converted with the OOB offset.
Device detection: the mailbox record's %globaltimer mapped to CLOCK_MONOTONIC (driver calibration).
"""
import csv
import glob
import gzip
import os
import re
import sys


def kv(line):
    d = {}
    for m in re.finditer(r'(\w+)=("[^"]*"|\S+)', line):
        d[m.group(1)] = m.group(2).strip('"')
    return d


def fnum(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def parse_trial(meta_path):
    base = meta_path[:-5]
    tag = os.path.basename(base)
    meta = {}
    for line in open(meta_path):
        meta.update(kv(line))

    def readlog(p):  # per-trial logs are gzipped after analysis
        if os.path.exists(p):
            return open(p, errors='replace').read().splitlines()
        if os.path.exists(p + '.gz'):
            return gzip.open(p + '.gz', 'rt', errors='replace').read().splitlines()
        return []
    l0 = readlog(base + '.pe0.log')
    l1 = readlog(base + '.pe1.log')

    clk0 = next((kv(l) for l in l0 if l.startswith('CLOCK rank 0')), {})
    off10 = fnum(clk0.get('off_r1_minus_r0_ms'), 0.0)
    m_minus_r = fnum(clk0.get('mono_minus_real_ms'))

    # fault shots on the rain clock
    shots = []
    for l in l0:
        m = re.search(r'\[nvshmem-fault-inject\] (?:shot \d+|in-commit shot) fire_mono_ms=([\d.]+)', l)
        if m:
            shots.append(('hook0', float(m.group(1))))
        if l.startswith('FAULT F2b'):
            shots.append(('f2b', fnum(kv(l).get('fire_mono_ms'))))
    for l in l1:
        m = re.search(r'\[nvshmem-fault-inject\] (?:shot \d+|in-commit shot) fire_mono_ms=([\d.]+)', l)
        if m:
            shots.append(('hook1', float(m.group(1)) - off10))
    if meta.get('kill_mono1_s'):
        shots.append(('kill', float(meta['kill_mono1_s']) * 1e3 - off10))
    elif 'kill_real_s' in meta and m_minus_r is not None:  # early smoke runs only (ssh latency included)
        shots.append(('kill', float(meta['kill_real_s']) * 1e3 + m_minus_r))
    shots.sort(key=lambda s: s[1])

    events = []
    rec_by_round = {}
    replay_done = {}
    iters0 = []
    for l in l0:
        if l.startswith('ITER ') and ' rank 0 ' in l:
            d = kv(l)
            it = int(l.split()[1])
            rnd = int(l.split()[5])
            iters0.append((it, rnd, d))
            if rnd > 0 and d.get('rc') == '0':
                replay_done[(it, rnd)] = fnum(d.get('t_ret'))
        elif l.startswith('REC '):
            d = kv(l)
            rec_by_round[(int(d['it']), int(d['round']))] = d
    for l in l0:
        if not l.startswith('FAULTREC'):
            continue
        d = kv(l)
        it, rnd = int(d['it']), int(d['round'])
        t_dev = fnum(d.get('t_dev'))
        t_ret = fnum(d.get('t_ret'))
        ref = t_dev if t_dev else t_ret
        fault = [s for s in shots if ref is not None and s[1] <= ref + 0.5]
        t_fault = fault[-1][1] if fault else None
        e = {
            'tag': tag, 'it': it, 'round': rnd, 'kernel_rc': d.get('kernel_rc'), 'have': d.get('have'),
            'class': d.get('class'), 'fp': d.get('fp'), 'syndrome': d.get('syndrome'),
            'path': d.get('path'), 'trailing': d.get('trailing'), 'upgrade': d.get('upgrade'),
            'wqe': d.get('wqe'), 'liveness': d.get('liveness'),
            'fault_src': fault[-1][0] if fault else '',
            't_fault_to_dev_ms': round(t_dev - t_fault, 3) if (t_dev and t_fault) else '',
            't_fault_to_mbx_ms': round(fnum(d.get('t_mbx')) - t_fault, 3) if (fnum(d.get('t_mbx')) and t_fault) else '',
            't_dev_to_mbx_us': round((fnum(d.get('t_mbx')) - t_dev) * 1e3, 1) if (fnum(d.get('t_mbx')) and t_dev) else '',
            't_fault_to_ret_ms': round(t_ret - t_fault, 3) if (t_ret and t_fault) else '',
        }
        itl = next((x[2] for x in iters0 if x[0] == it and x[1] == rnd), {})
        gs, gp = fnum(itl.get('gt_start_mono')), fnum(itl.get('gt_post_mono'))
        if gs and t_dev:
            e['kstart_to_dev_ms'] = round(t_dev - gs, 3)
            if gp:
                e['post_to_dev_ms'] = round(t_dev - gp, 3)
            if t_fault:
                e['fault_to_kstart_ms'] = round(gs - t_fault, 3)
        r = rec_by_round.get((it, rnd))
        if r:
            e.update({
                'd': r.get('d'), 'V': r.get('V'), 'prepare_ms': r.get('prepare_ms'),
                'handshake_ms': r.get('handshake_ms'), 'commit_ms': r.get('commit_ms'),
                'peer_prepare_ms': r.get('peer_prepare_ms'), 'peer_commit_ms': r.get('peer_commit_ms'),
                'ret_to_commit_ms': round(fnum(r.get('t_commit_done')) - t_ret, 3) if t_ret else '',
            })
            rd = replay_done.get((it, rnd + 1))
            if rd and fnum(r.get('t_commit_done')):
                e['commit_to_replayed_ms'] = round(rd - fnum(r.get('t_commit_done')), 3)
            if rd and t_ret:
                e['ret_to_recovered_ms'] = round(rd - t_ret, 3)
                if t_fault:
                    e['fault_to_recovered_ms'] = round(rd - t_fault, 3)
            elif r.get('d') == '0' and t_ret:
                e['ret_to_recovered_ms'] = e['ret_to_commit_ms']
        events.append(e)

    summ0 = next((kv(l) for l in l0 if l.startswith('SUMMARY rank 0')), {})
    summ1 = next((kv(l) for l in l1 if l.startswith('SUMMARY rank 1')), {})
    td0 = next((kv(l) for l in l0 if l.startswith('TEARDOWN rank 0')), {})
    td1 = next((kv(l) for l in l1 if l.startswith('TEARDOWN rank 1')), {})
    rx = [kv(l) for l in l1 if l.startswith('ITER ') and ' rank 1 ' in l]
    data_ok = sum(1 for d in rx if d.get('data_check') == 'ok')
    data_bad = sum(1 for d in rx if d.get('data_check') in ('mismatch',))
    sig_exact = sum(1 for d in rx if d.get('data_check') == 'ok' and d.get('sig') == d.get('expect'))
    decl = [kv(l) for l in l0 if l.startswith('DECLINE')]
    first = events[0] if events else {}
    row = {
        'tag': tag, 'fault': meta.get('fault'), 'mode': meta.get('mode'), 'trial': meta.get('trial'),
        'ft': meta.get('ft'), 'recover': meta.get('recover'), 'burst': meta.get('burst'),
        'qdelay_us': meta.get('qdelay_us'), 'sentinel': meta.get('sentinel'), 'shots': meta.get('shots'),
        'ft_capture': meta.get('ft_capture'),
        'pe0_rc': meta.get('pe0_rc'), 'pe1_rc': meta.get('pe1_rc'),
        'ok_iters0': summ0.get('ok_iters'), 'ok_iters1': summ1.get('ok_iters'),
        'rx_data_ok': data_ok, 'rx_data_bad': data_bad, 'rx_sig_exact': sig_exact,
        'final_sig': summ1.get('final_sig'), 'expected_sig': summ1.get('expected_sig'),
        'faults_fired': len([s for s in shots]),
        'fault_rounds': len(events), 'rec_rounds': summ0.get('rec_rounds'), 'rec_ok_ops': summ0.get('rec_ok_ops'),
        'declined': summ0.get('declined'), 'decline_reason': decl[0].get('reason') if decl else '',
        'first_class': first.get('class', ''), 'first_fp': first.get('fp', ''), 'first_path': first.get('path', ''),
        'first_fault_to_dev_ms': first.get('t_fault_to_dev_ms', ''), 'first_fault_to_mbx_ms': first.get('t_fault_to_mbx_ms', ''),
        'first_dev_to_mbx_us': first.get('t_dev_to_mbx_us', ''),
        'teardown0': 'returned' if td0 else 'no', 'teardown1': 'returned' if td1 else 'no',
        'finalize0_ms': td0.get('finalize_ms', ''), 'finalize1_ms': td1.get('finalize_ms', ''),
        'leftover': '%s/%s' % (meta.get('leftover_rain'), meta.get('leftover_sunny')),
    }
    return row, events


def main():
    args = sys.argv[1:]
    tpath = args[args.index('--trials') + 1]
    epath = args[args.index('--events') + 1]
    dirs = [a for i, a in enumerate(args) if not a.startswith('--') and args[i - 1] not in ('--trials', '--events')]
    rows, evs = [], []
    for d in dirs:
        for mp in sorted(glob.glob(os.path.join(d, '*.meta'))):
            r, e = parse_trial(mp)
            r['dir'] = os.path.basename(os.path.normpath(d))
            rows.append(r)
            for x in e:
                x['dir'] = r['dir']
            evs.extend(e)
    if rows:
        with open(tpath, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['dir'] + [k for k in rows[0] if k != 'dir'])
            w.writeheader()
            w.writerows(rows)
    keys = []
    for e in evs:
        for k in e:
            if k not in keys:
                keys.append(k)
    with open(epath, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(evs)
    print('%d trials, %d fault rounds' % (len(rows), len(evs)))


if __name__ == '__main__':
    main()
