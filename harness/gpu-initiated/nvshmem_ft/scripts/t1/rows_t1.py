#!/usr/bin/env python3
"""rows_t1.py - per-trial and per-round CSV rows from the raw T1 logs (<tag>.meta, .pe0.log, .pe1.log).

usage: rows_t1.py <dir> [<dir> ...] --trials trials.csv [--rounds rounds.csv]

A trial is "transparent" only if all of these hold: both processes exited 0; PE0's kernel ran every
iteration and no iteration's nvshmemx_ibgda_ft_status (read by the kernel after its quiet) was set;
every slot was bit-exact on PE1's GPU and again on PE1's host; the final signal was exact; the
library's host error view (nvshmemt_ibgda_ft_query) and the device status after the run were clean on
both PEs; no DECLINE line. "declined" = a DECLINE line and PE0's kernel returned (bounded) and PE0's
nvshmem_finalize returned. In lat mode (no fault) "transparent" only means both processes exited 0.
"void" = PE0 never started its kernel (setup error: nvshmem_init, nvshmem_malloc or heap
registration failed). Everything else is "failed".
"""
import csv, glob, os, re, sys


def kv(line):
    return dict(re.findall(r'(\w+)=("[^"]*"|\S+)', line))


def fnum(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def parse_trial(meta_path):
    base = meta_path[:-5]
    tag = os.path.basename(base)
    m = {}
    for line in open(meta_path, errors='replace'):
        m.update({k: v.strip('"') for k, v in kv(line).items()})
    r = {'dir': os.path.basename(os.path.dirname(meta_path)), 'tag': tag}
    for k in ('fault', 'mode', 'trial', 'ft', 't1', 't1skip', 'skip', 'fetch', 'fetch_every', 'fill', 'sock_s', 'sock_at_ms', 'sock_port', 'sock_start_rain_mono_ms',
              'sock_end_rain_mono_ms', 'iptables_left', 'iters', 'bytes', 'gap_us', 'ctas', 'threads',
              'burst', 'reps', 'fault_ms', 'shots', 'kill_ms', 'cut_s', 'cut_at_ms', 'hold_ms', 'gid_r', 'gid_s',
              'bin', 'md5_bin', 'md5_transport', 'md5_host', 'pe0_rc', 'pe1_rc', 'leftover_rain', 'leftover_sunny',
              'kill_mono1_s', 'cut_start_rain_mono_ms', 'cut_end_rain_mono_ms', 'start',
              'nofin', 'rc_per_pe', 'rc_map', 'xenv', 'sock_dir', 'bundle'):  # t1_close: last six
        r[k] = m.get(k, '')
    # t1_close: fetch counts of PE0's first round line (RECOVERED initiator or DECLINE), the exit
    # without nvshmem_finalize (T1EXIT) and the library's atexit hook (ATEXIT)
    for k in ('t1_fetch_cr0', 't1_fetch_exec0', 't1_fetch_reposted0'):
        r[k] = ''
    first_round0 = None
    rounds = []
    for pe in (0, 1):
        p = f'{base}.pe{pe}.log'
        if not os.path.exists(p):
            continue
        rec_t, shots, declines, faults, gid_moves = [], [], [], [], []
        wd = 0
        sock_lost, sock_back, dci_lines = [], [], []
        for line in open(p, errors='replace'):
            if line.startswith('T1APP '):
                d = kv(line)
                r[f'start_mono{pe}'] = d.get('start_mono_ms', '')
                if pe == 0:
                    r['off10'] = d.get('off_r1_minus_r0_ms', '')
            elif line.startswith('CALIB '):
                r[f'gtoff{pe}'] = kv(line).get('gt_minus_mono_ms', '')
            elif line.startswith('T1RESULT '):
                d = kv(line)
                if 'KERNEL_TIMEOUT_OR_ERROR' in line:
                    r[f'kernel_timeout{pe}'] = 1
                    if pe == 1:
                        r['final_sig'] = d.get('final_sig', '')
                        r['expect'] = d.get('expect', '')
                    continue
                if pe == 0:
                    for k in ('records', 'status_bad', 'first_bad', 'status_first', 'median_op_us', 'max_op_us',
                              'max_at', 'max_t1_gt', 'slow_ops_gt1ms', 'kernel_ms'):
                        r[k] = d.get(k, '')
                    r['host_err0'] = d.get('host_err', '')
                else:
                    for k in ('slots', 'gpu_bad', 'host_bad', 'first_host_bad', 'final_sig', 'expect', 'sig_exact'):
                        r[k] = d.get(k, '')
                    r['kernel_ms1'] = d.get('kernel_ms', '')
                    r['host_err1'] = d.get('host_err', '')
            elif line.startswith('T1FETCH '):
                d = kv(line)
                if pe == 0:
                    for k in ('fetches', 'exact', 'poison', 'stale', 'first_poison', 'first_stale', 'poison_before_bad'):
                        r['fetch_' + k] = d.get(k, '')
                else:
                    r['fetch_counter1'] = d.get('counter', '')
            elif line.startswith('T1ARRIVE '):
                d = kv(line)
                r.setdefault('arrive1', [])
                r['arrive1'].append('%s:%s' % (d.get('it'), d.get('gt')))
            elif line.startswith('T1EXIT '):
                r[f'exit_mono{pe}'] = kv(line).get('mono_ms', '')
            elif line.startswith('T1STATUS '):
                r[f'end_status{pe}'] = kv(line).get('end_status', '')
            elif line.startswith('T1END '):
                d = kv(line)
                r[f'finalize_ms{pe}'] = d.get('finalize_ms', '')
                r[f'end_rc{pe}'] = d.get('rc', '')
            elif line.startswith('LAT '):
                d = kv(line)
                r.setdefault('lat_p50', [])
                r['lat_p50'].append(d.get('p50_us'))
                r.setdefault('lat_p99', [])
                r['lat_p99'].append(d.get('p99_us'))
            elif '[nvshmem-fault-inject] shot' in line or 'in-commit shot' in line:
                mm = re.search(r'fire_mono_ms=([\d.]+)', line)
                if mm:
                    shots.append(float(mm.group(1)))
            elif 'device-classified error CQE' in line:
                d = kv(line)
                rec_t.append((d.get('mono_ms'), d.get('class'), d.get('fp')))
            elif '[nvshmem-t1]' in line:
                if ' ATEXIT ' in line:
                    d = kv(line)
                    mm = re.search(r'PE\d ([\d.]+) ATEXIT', line)
                    r[f'atexit_mono{pe}'] = mm.group(1) if mm else ''
                    r[f'atexit_join_ms{pe}'] = d.get('join_ms', '')
                    r[f'atexit_detached{pe}'] = 1 if d.get('helper') == 'detached' else 0
                elif ' RECOVERED ' in line:
                    d = kv(line)
                    if pe == 0 and first_round0 is None and ' RECOVERED initiator ' in line:
                        first_round0 = d
                    mm = re.search(r'PE(\d) ([\d.]+) RECOVERED (\w+)', line)
                    rr = {'dir': r['dir'], 'tag': tag, 'pe': pe, 'role': mm.group(3), 'end_mono_ms': mm.group(2)}
                    for k in ('peer', 'class', 'round', 'total_ms', 'quiesce_ms', 'prepare_ms', 'handshake_ms',
                              'commit_ms', 'gid_ms', 'sgid', 'finish_ms', 'qpn', 'C', 'U', 'Uexec', 'P', 'R', 'V', 'reposted',
                              'B', 'exec_by_peer', 'epoch', 'dci_reset', 'dci_pending', 'dci_failed',
                              'nqps', 'fetch_cr', 'fetch_exec', 'fetch_reposted'):
                        rr[k] = d.get(k, '')
                    rounds.append(rr)
                elif ' DECLINE ' in line:
                    d = kv(line)
                    if pe == 0 and first_round0 is None:
                        first_round0 = d
                    mm = re.search(r'PE(\d) ([\d.]+) DECLINE', line)
                    declines.append((mm.group(2) if mm else '', d.get('class', ''), d.get('reason', '')))
                elif ' FAULT ' in line:
                    mm = re.search(r'PE(\d) ([\d.]+) FAULT', line)
                    faults.append(mm.group(2) if mm else '')
                elif 'GID re-lookup' in line:
                    gid_moves.append(line.strip().split('GID re-lookup:')[-1].strip())
                elif 'WATCHDOG' in line:
                    wd += 1
                elif 'library socket lost' in line:
                    mm = re.search(r'PE\d ([\d.]+) peer (\d) library socket lost \((.*?)\)', line)
                    sock_lost.append((mm.group(1), mm.group(3)) if mm else ('', ''))
                elif 'socket re-dialed' in line or 'socket re-accepted' in line:
                    mm = re.search(r'PE\d ([\d.]+) ', line)
                    sock_back.append(mm.group(1) if mm else '')
                elif re.search(r'\] PE\d [\d.]+ DCI 0x', line):
                    dci_lines.append(line.split('] PE', 1)[1].split(' ', 2)[2].strip()[:80])
            elif line.startswith('T1FILL '):
                r['fill_ctas'] = kv(line).get('ctas', '')
        r[f'n_records{pe}'] = len(rec_t)
        r[f'first_record_mono{pe}'] = rec_t[0][0] if rec_t else ''
        r[f'first_record_class{pe}'] = rec_t[0][1] if rec_t else ''
        r[f'shots{pe}'] = len(shots)
        r[f'first_shot_mono{pe}'] = shots[0] if shots else ''
        r[f'declines{pe}'] = len(declines)
        r[f'decline_reason{pe}'] = declines[0][2] if declines else ''
        r[f'decline_mono{pe}'] = declines[0][0] if declines else ''
        r[f'first_fault_mono{pe}'] = faults[0] if faults else ''
        r[f'gid_moves{pe}'] = ';'.join(gid_moves)
        r[f'watchdog{pe}'] = wd
        r[f'sock_lost{pe}'] = len(sock_lost)
        r[f'sock_lost_errno{pe}'] = sock_lost[0][1] if sock_lost else ''
        r[f'sock_lost_mono{pe}'] = sock_lost[0][0] if sock_lost else ''
        r[f'sock_back{pe}'] = len(sock_back)
        r[f'sock_back_mono{pe}'] = sock_back[-1] if sock_back else ''
        r[f'dci_lines{pe}'] = ';'.join(dci_lines)
    # FLAP: GID indices of the secondary addresses after the trial (flap_hold.log in the same dir)
    fh = os.path.join(os.path.dirname(meta_path), 'flap_hold.log')
    mm = re.search(r'_cut([\d.]+)_t(\d+)$', tag)
    if r['fault'] == 'FLAP' and mm and os.path.exists(fh):
        pat = re.compile(r'^trial %s cut %s gids_after (\d*) ?(\d*)' % (mm.group(2), re.escape(mm.group(1))))
        for line in open(fh, errors='replace'):
            m2 = pat.match(line)
            if m2:
                r['gid_r_after'], r['gid_s_after'] = m2.group(1), m2.group(2)
    if first_round0 is not None:
        for k in ('fetch_cr', 'fetch_exec', 'fetch_reposted'):
            r['t1_' + k + '0'] = first_round0.get(k, '')
    for pe in (0, 1):
        for k in ('exit_mono', 'atexit_mono', 'atexit_join_ms', 'atexit_detached'):
            r.setdefault(f'{k}{pe}', '')
    r['rounds_init'] = sum(1 for x in rounds if x['role'] == 'initiator')
    r['rounds_resp'] = sum(1 for x in rounds if x['role'] == 'responder')
    r.pop('arrive1', None)  # per-iteration arrival times stay in the raw logs (T1ARRIVE lines)
    if 'lat_p50' in r:
        r['lat_p50'] = ';'.join(x for x in r['lat_p50'] if x)
        r['lat_p99'] = ';'.join(x for x in r['lat_p99'] if x)
    # slow iteration end on the host clock (PE0): %globaltimer -> CLOCK_MONOTONIC
    g = fnum(r.get('max_t1_gt')), fnum(r.get('gtoff0'))
    if g[0] is not None and g[1] is not None:
        r['max_end_mono0'] = '%.3f' % (g[0] / 1e6 - g[1])
    # outcome
    ok = (r['pe0_rc'] == '0' and r['pe1_rc'] == '0' and r.get('status_bad') == '0' and r.get('gpu_bad') == '0'
          and r.get('host_bad') == '0' and r.get('sig_exact') == '1' and r.get('host_err0', '').startswith('0')
          and r.get('host_err1', '').startswith('0') and r.get('declines0', 0) == 0 and r.get('declines1', 0) == 0
          and r.get('end_status0', '0x00000000') == '0x00000000' and r.get('end_status1', '0x00000000') == '0x00000000')
    if r['mode'] == 'lat':
        ok = r['pe0_rc'] == '0' and r['pe1_rc'] == '0'
    # --fetch: every fetch returned its iteration number (exactly once) and PE1's counter equals the
    # number of iterations; a declined trial must show the poison value from the failed iteration on
    # and never a stale value, and the counter must be the exact count or one more (the declined
    # fetch may have executed at the responder)
    if r.get('fetch') == '1':
        ex = fnum(r.get('fetch_exact'), -1)
        nf = fnum(r.get('fetch_fetches'), fnum(r.get('iters'), -2))
        r['fetch_ok'] = int(ex == nf and fnum(r.get('fetch_stale'), 1) == 0
                           and fnum(r.get('fetch_poison'), 1) == 0 and fnum(r.get('fetch_counter1'), -1) == ex)
        ok = ok and r['fetch_ok'] == 1
        c1 = fnum(r.get('fetch_counter1'), -1)
        r['fetch_decl_ok'] = int(fnum(r.get('fetch_stale'), 1) == 0 and fnum(r.get('fetch_poison_before_bad'), 1) == 0
                                and fnum(r.get('fetch_poison'), 0) >= 1 and c1 in (ex, ex + 1))
    declined = (r.get('declines0', 0) or r.get('declines1', 0)) and 'records' in r and 'finalize_ms0' in r
    if declined and r.get('fetch') == '1' and r.get('fetch_decl_ok') != 1:
        declined = False
    r['outcome'] = 'transparent' if ok else ('declined' if declined else 'failed')
    # void: the application never started (PE0 printed no T1APP line: nvshmem_init/malloc/heap
    # registration failed, a setup error of the trial, not a result of the mechanism)
    if 'start_mono0' not in r:
        r['outcome'] = 'void'
    return r, rounds


def main():
    args = sys.argv[1:]
    out_t = out_r = None
    dirs = []
    i = 0
    while i < len(args):
        if args[i] == '--trials':
            out_t = args[i + 1]; i += 2
        elif args[i] == '--rounds':
            out_r = args[i + 1]; i += 2
        else:
            dirs.append(args[i]); i += 1
    trials, rounds = [], []
    for d in dirs:
        for mp in sorted(glob.glob(os.path.join(d, '*.meta'))):
            t, rr = parse_trial(mp)
            trials.append(t)
            rounds.extend(rr)
    if out_t:
        keys = []
        for t in trials:
            for k in t:
                if k not in keys:
                    keys.append(k)
        with open(out_t, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for t in trials:
                w.writerow(t)
    if out_r and rounds:
        with open(out_r, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rounds[0].keys()))
            w.writeheader()
            for x in rounds:
                w.writerow(x)
    for t in trials:
        print(f"{t['tag']:40s} {t['outcome']:12s} rc={t['pe0_rc']}/{t['pe1_rc']} rounds={t['rounds_init']}/{t['rounds_resp']} "
              f"status_bad={t.get('status_bad','')} gpu_bad={t.get('gpu_bad','')} host_bad={t.get('host_bad','')} "
              f"sig={t.get('final_sig','')}/{t.get('expect','')} max_op_us={t.get('max_op_us','')} "
              f"decl={t.get('decline_reason0','') or t.get('decline_reason1','')}")


if __name__ == '__main__':
    main()
