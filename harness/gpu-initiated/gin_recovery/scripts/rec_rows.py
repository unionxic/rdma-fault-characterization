#!/usr/bin/env python3
"""rec_rows.py - turn gin_rec trial logs into CSVs.

usage: rec_rows.py <logdir> [<logdir> ...] --trials trials.csv --events events.csv

Per trial (one <stem>_meta.txt each): outcome of both ranks, recoveries, final signal check,
teardown, faults fired (NCCL hook WARN lines), and fault -> recovered times.
Per recovery event (sender KV 'rec ev=...' lines): timing breakdown, joined with the fault shot
it belongs to (the last hook fire before the kernel return, on rank 0's clock; F3 fires on
rank 1 are converted with the measured clock offset).
"""
import argparse, csv, glob, os, re, statistics

KVRE = re.compile(r'(\w+)=("[^"]*"|\S+)')


# values printed with ncclGetErrorString contain spaces: take them up to the next known key
SPACED = [('host_error', 'host_error_ms='), ('final_async', 'rec_events='), ('abort_ret', None),
          ('async_after_commit', 'prep_us=')]


def kvline(line):
    d = {k: v.strip('"') for k, v in KVRE.findall(line)}
    for k, nxt in SPACED:
        m = re.search(r'(?:^|\s)' + k + r'=(.*?)' + (r'\s' + re.escape(nxt) if nxt else r'$'), line)
        if m:
            d[k] = m.group(1)
    return d


def read_kv(path):
    """flat dict of the last value of each key, plus the list of raw lines"""
    flat, lines = {}, []
    if not os.path.exists(path):
        return flat, lines
    for ln in open(path, errors='replace'):
        ln = ln.rstrip('\n')
        lines.append(ln)
        flat.update(kvline(ln))
    return flat, lines


def fires(logpath):
    out = []
    if not os.path.exists(logpath):
        return out
    for ln in open(logpath, errors='replace'):
        if 'GDAKI fault fired' in ln:
            m = re.search(r'fire_mono_ms=([\d.]+)', ln)
            if m:
                out.append(float(m.group(1)))
    return out


def f(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('logdirs', nargs='+')
    ap.add_argument('--trials', required=True)
    ap.add_argument('--events', required=True)
    a = ap.parse_args()
    trows, erows = [], []
    for d in a.logdirs:
        for meta in sorted(glob.glob(os.path.join(d, '*_meta.txt'))):
            stem = os.path.basename(meta)[:-len('_meta.txt')]
            m = kvline(open(meta).read())
            k0, l0 = read_kv(os.path.join(d, stem + '_r0.kv'))
            k1, l1 = read_kv(os.path.join(d, stem + '_r1.kv'))
            off = f(k0.get('clock_offset_ms'), 0.0)
            fire0 = fires(os.path.join(d, stem + '_r0.log'))
            fire1 = [t - off for t in fires(os.path.join(d, stem + '_r1.log'))]
            fire = sorted(fire0 + fire1)
            kill = None
            kp = os.path.join(d, stem + '_kill.out')
            if os.path.exists(kp):
                mm = re.search(r'kill_mono_ms=([\d.]+)', open(kp).read())
                if mm:
                    kill = float(mm.group(1)) - off
            recs = [kvline(ln) for ln in l0 if ln.startswith('rec ev=')]
            faults = {kvline(ln)['ev']: kvline(ln) for ln in l0 if ln.startswith('fault ev=')}
            rxrecs = [kvline(ln) for ln in l1 if ln.startswith('rxrec ')]
            rx_by_it = {}
            for r in rxrecs:
                rx_by_it.setdefault(r.get('it'), []).append(r)
            # recovered operations and fault -> recovered times
            f2r = []
            used = set()
            for r in recs:
                ev = r.get('ev')
                fq = faults.get(ev, {})
                tk = f(r.get('t_kret'))
                # shot this event belongs to: last fire before the kernel return not yet used
                shot = None
                for i, t in enumerate(fire):
                    if tk is not None and t <= tk and i not in used:
                        shot = i
                shot_t = fire[shot] if shot is not None else None
                if r.get('outcome') == 'recovered' and shot is not None:
                    used.update(i for i, t in enumerate(fire) if t <= tk)
                tdone = f(r.get('t_replay')) if r.get('d') == '1' else f(r.get('t_commit'))
                rx = rx_by_it.get(r.get('it'), [])
                erows.append(dict(
                    stem=stem, fault=m.get('fault'), wait=m.get('wait'), trial=m.get('trial'), ev=ev,
                    it=r.get('it'), attempt=r.get('attempt'), cls=r.get('class', fq.get('class', '')),
                    fp=fq.get('fp', ''), outcome=r.get('outcome'), reason=r.get('reason', ''), d=r.get('d', ''),
                    V=r.get('V', ''), shot=shot, fire_ms=shot_t,
                    detect_ms=(f(fq.get('t_dev')) - shot_t) if (shot_t is not None and f(fq.get('t_dev'), -1) > 0) else '',
                    kret_ms=(tk - shot_t) if (shot_t is not None and tk) else '',
                    kret_to_commit_ms=(f(r.get('t_commit')) - tk) if (r.get('t_commit') and tk) else '',
                    prep_ms=(f(r.get('t_prep')) - f(r.get('t_prep0'))) if r.get('t_prep') else '',
                    handshake_ms=(f(r.get('t_ack')) - f(r.get('t_prep'))) if r.get('t_ack') else '',
                    commit_ms=(f(r.get('t_commit')) - f(r.get('t_ack'))) if r.get('t_commit') else '',
                    replay_ms=(f(r.get('t_replay')) - f(r.get('t_commit'))) if (r.get('d') == '1' and r.get('t_replay')) else '',
                    fault_to_recovered_ms=(tdone - shot_t) if (r.get('outcome') == 'recovered' and shot_t is not None and tdone) else '',
                    kret_to_recovered_ms=(tdone - tk) if (r.get('outcome') == 'recovered' and tdone and tk) else '',
                    prep_us=r.get('prep_us', ''), err_us=r.get('err_us', ''), drain_us=r.get('drain_us', ''),
                    commit_us=r.get('commit_us', ''), reset_us=r.get('reset_us', ''), resync_us=r.get('resync_us', ''),
                    connect_us=r.get('connect_us', ''), nqp=r.get('nqp', ''), epoch_wqes=r.get('epoch_wqes', ''),
                    cqe_err=r.get('cqe_err', ''), cqe_ok=r.get('cqe_ok', ''), rx_prep_us=r.get('rx_prep_us', ''),
                    rx_commit_us=r.get('rx_commit_us', ''), async_after_commit=r.get('async_after_commit', ''),
                    replay_rc=r.get('replay_rc', ''),
                ))
                if r.get('outcome') == 'recovered' and shot_t is not None and tdone:
                    f2r.append(tdone - shot_t)
            n_rec = sum(1 for r in recs if r.get('outcome') == 'recovered')
            n_rf = sum(1 for r in recs if r.get('outcome') == 'replay_failed')
            n_dec = sum(1 for r in recs if r.get('outcome') == 'declined')
            dec = [r for r in recs if r.get('outcome') == 'declined']
            host_err = k0.get('host_error', '')
            first_fault = fire[0] if fire else (kill if kill is not None else f(k0.get('fault_mono_ms')))
            t0_0 = f(k0.get('t0_mono_ms'), 0.0)
            hem = f(k0.get('host_error_ms'), -1.0)
            trows.append(dict(
                stem=stem, fault=m.get('fault'), wait=m.get('wait'), trial=m.get('trial'), rec=m.get('rec'),
                inject=m.get('inject'), iters=m.get('iters'), r0rc=m.get('r0rc'), r1rc=m.get('r1rc'), left=m.get('left'),
                wall_s=m.get('wall_s'), shots_fired=len(fire),
                r0_iters_ok=k0.get('iters_ok'), r0_outcome=k0.get('init_outcome'), r1_iters_ok=k1.get('iters_ok'),
                r1_outcome=k1.get('init_outcome'), r1_data=k1.get('data_check'),
                final_signal=k1.get('final_signal', ''), expected_final=k1.get('expected_final', ''),
                signal_exact=k1.get('signal_exact', ''), rec_events=k0.get('rec_events'), recovered=n_rec,
                replay_failed=n_rf, declined=n_dec, decline_reason=(dec[0].get('reason') if dec else k0.get('decline_reason', '')),
                decline_class=(faults.get(dec[0].get('ev'), {}).get('class', '') if dec else ''),
                decline_fp=(faults.get(dec[0].get('ev'), {}).get('fp', '') if dec else ''),
                replays=k0.get('replays'), delta_zero=k0.get('delta_zero'),
                rx_reqs=len(rxrecs), rx_acks=sum(1 for r in rxrecs if r.get('outcome') == 'ack'),
                rx_nacks=sum(1 for r in rxrecs if r.get('outcome') == 'nack'),
                rx_recovered_iters=k1.get('recovered_iters', ''), rearms=k1.get('rearms', ''),
                rx_cancel_rc=k1.get('rx_cancel_rc', ''), final_async=k0.get('final_async', ''),
                r1_final_async=k1.get('final_async', ''), host_error=host_err,
                surface_ms=((t0_0 + hem) - first_fault) if (hem >= 0 and first_fault) else '',
                teardown0=k0.get('teardown', ''), abort0=k0.get('abort_ret', ''), teardown0_ms=k0.get('teardown_ms', ''),
                teardown1=k1.get('teardown', ''), abort1=k1.get('abort_ret', ''),
                f2r_ms_median=(statistics.median(f2r) if f2r else ''), f2r_ms_max=(max(f2r) if f2r else ''),
                lat_p50_us=k0.get('lat_p50_us', ''), lat_p99_us=k0.get('lat_p99_us', ''),
                lat_n=k0.get('lat_n', ''), lat_cpu_ms=k0.get('lat_cpu_ms', ''), lat_wall_ms=k0.get('lat_wall_ms', ''),
                lat_data=(('ok' if k1.get('lat_data_bad') == '0' else 'bad') if k1.get('lat_data_bad') is not None else '')
                if m.get('fault') == 'lat' else '',
            ))
    for path, rows in ((a.trials, trows), (a.events, erows)):
        if not rows:
            open(path, 'w').close()
            continue
        with open(path, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow(r)
    print(f'{len(trows)} trials -> {a.trials}, {len(erows)} events -> {a.events}')


if __name__ == '__main__':
    main()
