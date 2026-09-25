#!/usr/bin/env python3
"""analyze_n30.py - N30 campaign (2026-09-25): regenerate the per-trial CSVs from the raw logs with each
stack's own, unchanged row extractor, add the per-trial doorbell-mode and driver-config columns, judge
every trial against the cell's success criterion, and print every table of N30_20260925.md.

usage: analyze_n30.py [--sub DIR]   (DIR = results sub-directory name, default 20260925_n30)

Outputs (under each stack's results/<sub>/): the regenerated CSVs, <stack>_n30_trials.csv (one row per
trial with the verdict and the columns it was judged on) and, on stdout, the markdown tables.
Stats: Wilson score interval (z = 1.96) for proportions; percentiles by linear interpolation between
order statistics (numpy's default); times in ms.
"""
import csv, glob, gzip, math, os, re, subprocess, sys
from collections import OrderedDict, Counter

G = '/home/unionxic/rdma-error/harness/gpu-initiated'
SUB = sys.argv[sys.argv.index('--sub') + 1] if '--sub' in sys.argv else '20260925_n30'
Q4R, RECR, NVR = (os.path.join(G, s, 'results', SUB) for s in ('gin_q4', 'gin_recovery', 'nvshmem_ft'))
PY = sys.executable
OUT = []


def p(s=''):
    OUT.append(s)


# ----------------------------------------------------------------------------------------------- stats
def wilson(x, n, z=1.96):
    if n == 0:
        return (float('nan'), float('nan'))
    ph = x / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z / d * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return (max(0.0, c - h), min(1.0, c + h))


def pct(v, q):
    v = sorted(v)
    if not v:
        return None
    k = (len(v) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def fl(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def dist(vals, nd=1):
    v = [x for x in (fl(a) for a in vals) if x is not None]
    if not v:
        return '-'
    f = '%.' + str(nd) + 'f'
    return (f + ' [' + f + '-' + f + '] ' + f) % (pct(v, .5), pct(v, .1), pct(v, .9), max(v)) + ' (n=%d)' % len(v)


def prop(x, n):
    lo, hi = wilson(x, n)
    return '%d/%d [%.1f-%.1f%%]' % (x, n, 100 * lo, 100 * hi)


def load(path):
    try:
        return list(csv.DictReader(open(path)))
    except FileNotFoundError:
        return []


def write_csv(path, rows):
    if not rows:
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def readtext(path):
    if os.path.exists(path):
        return open(path, errors='replace').read()
    if os.path.exists(path + '.gz'):
        return gzip.open(path + '.gz', 'rt', errors='replace').read()
    return ''


def drvcfg(path):
    """'ok' if both nodes report RegistryDwords="PeerMappingOverride=1;" and EnableStreamMemOPs=1"""
    t = readtext(path)
    nodes = re.findall(r'node=(\S+) nvidia=(\S*) RegistryDwords=(\S*) EnableStreamMemOPs=(\S*)', t)
    ok = len(nodes) == 2 and all(rd == '"PeerMappingOverride=1;"' and sm == '1' for _, _, rd, sm in nodes)
    return ('PMO=1,SMO=1 both' if ok else 'CHECK:' + ';'.join('%s:%s:%s' % (n, rd, sm) for n, _, rd, sm in nodes)), \
        ';'.join('%s=%s' % (n, v) for n, v, _, _ in nodes)


BINS = [('timeout', 'blocking')]


def ssum(rows, f):
    return sum(1 for r in rows if f(r))


def grp(rows, key):
    g = OrderedDict()
    for r in rows:
        g.setdefault(key(r), []).append(r)
    return g


# ================================================================ 1. GIN GDAKI + Q4 classifier (gin_q4)
Q4TRUE = {'F1': ('LOCAL_QP_ERR', '5', '0xf5'), 'F2': ('REM_ACCESS', '10', '0x88'),
          'F3': ('RETRY_EXC', '12', '0x81'), 'F4': ('RETRY_EXC', '12', '0x81')}


def q4_load(logdir, csvp, sub):
    """regenerate <csvp> from <logdir> with gin_q4/scripts/rebuild_csv.py (unchanged) and judge each row"""
    out = []
    if not os.path.isdir(logdir):
        return out
    subprocess.run([PY, G + '/gin_q4/scripts/rebuild_csv.py', logdir, csvp], check=True, stdout=subprocess.DEVNULL)
    if True:
        for r in load(csvp):
            stem = os.path.join(logdir, '%s_c%s_%s_%s_t%s' % (r['cq_type'], r['classify'], r['fault'],
                                                              r['wait_mode'], r['trial']))
            pr = readtext(stem + '_probe.txt')
            m0 = re.search(r'^r0 .*gin_proxy_thread=(\S+)', pr, re.M)
            m1 = re.search(r'^r1 .*gin_proxy_thread=(\S+)', pr, re.M)
            l0, l1 = readtext(stem + '_r0.log'), readtext(stem + '_r1.log')
            c0, c1 = l0.count('Enabling CPU proxy mode'), l1.count('Enabling CPU proxy mode')
            p0, p1 = (m0.group(1) if m0 else 'na'), (m1.group(1) if m1 else 'na')
            ind = [x for x in (p0, p1) if x != 'na']
            if all(x == '0' for x in ind) and c0 == 0 and c1 == 0 and l0 and l1:
                door = 'GPU'
            elif all(x == '1' for x in ind) and c0 > 0 and c1 > 0:
                door = 'CPU_PROXY'
            else:
                door = 'MIXED'
            drv, ver = drvcfg(stem + '_drv.txt')
            meta = readtext(stem + '_meta.txt')
            T = Q4TRUE.get(r['fault'])
            v = dict(sub=sub, **r)
            # harness-invalid: a rank never initialised GIN (e.g. the bootstrap port was taken), so no fault ran
            k0t, k1t = readtext(stem + '_r0.kv'), readtext(stem + '_r1.kv')
            inv = ''
            if 'gin_available=1' not in k0t or 'gin_available=1' not in k1t:
                inv = 'rank %s did not initialise (r0 log: %s)' % ('0' if 'gin_available=1' not in k0t else '1',
                                                                  (l0.strip().splitlines() or ['-'])[0][:60])
            v['invalid'] = inv
            v.update(proxy_thread_r0=p0, proxy_thread_r1=p1, doca_proxy_lines_r0=c0, doca_proxy_lines_r1=c1,
                     doorbell=door, driver=drv, nvidia=ver,
                     class_ok=int(bool(T) and (r['q4_class'], r['q4_status'], r['q4_vendor']) == T),
                     dev_rc_err=int(r['device_rc'] == 'remote'),
                     api_err=int(r['host_error'] == 'remote' and r['t_api_ms'] != ''),
                     silent=int(r['silent_success'] == '1' or (fl(r['init_silent_iters']) or 0) > 0),
                     teardown_clean=int(r['teardown'] == 'clean'),
                     left0=int(r['leftover_procs'] == '0'))
            out.append(v)
    return out


def q4_rows():
    out = []
    for sub in ('main', 'stock', 'posctl', 'smoke'):
        d = os.path.join(Q4R, sub)
        out += q4_load(os.path.join(d, 'logs'), os.path.join(d, 'q4.csv'), sub)
    write_csv(os.path.join(Q4R, 'q4_n30_trials.csv'), out)
    return out


def q4_tables(R):
    main = [r for r in R if r['sub'] == 'main' and not r['invalid']]
    inval = [r for r in R if r['sub'] in ('main', 'stock', 'posctl') and r['invalid']]
    p('### 1a. GIN GDAKI + Q4 device classifier (flag on), per CQ type x fault')
    p()
    p('| CQ | fault | wait | N | class + fp correct | device wait returned ncclRemoteError | host API returned error | '
      'silent success | fault -> host API (ms): median [p10-p90] max | fault -> device (ms): median [p10-p90] max | '
      'abort clean / leftover 0 | doorbell (indicators) | driver |')
    p('|---|---|---|--:|---|---|---|---|---|---|---|---|---|')
    for (cq, f), rows in grp(main, lambda r: (r['cq_type'], r['fault'])).items():
        for w, rs in [('both', rows)] + [(w, [r for r in rows if r['wait_mode'] == w]) for w in ('timeout', 'blocking')]:
            n = len(rs)
            if not n:
                continue
            doors = Counter(r['doorbell'] for r in rs)
            drv = Counter(r['driver'] for r in rs)
            p('| %s | %s | %s | %d | %s | %s | %s | %s | %s | %s | %d/%d / %d/%d | %s | %s |' % (
                cq, f, w, n, prop(ssum(rs, lambda r: r['class_ok']), n), prop(ssum(rs, lambda r: r['dev_rc_err']), n),
                prop(ssum(rs, lambda r: r['api_err']), n),
                ('%d/%d' % (ssum(rs, lambda r: r['silent']), n)) if f != 'F4' else
                ('n/a (initiator 1 op ahead of the killed target: %d/%d)' % (ssum(rs, lambda r: r['silent']), n)),
                dist([r['t_api_ms'] for r in rs], 2 if f in ('F1', 'F2') else 0),
                dist([r['t_dev_ms'] for r in rs], 2 if f in ('F1', 'F2') else 0),
                ssum(rs, lambda r: r['teardown_clean']), n, ssum(rs, lambda r: r['left0']), n,
                ','.join('%s %d' % kv for kv in doors.items()), ','.join('%s %d' % kv for kv in drv.items())))
    p()
    if inval:
        p('Harness-invalid trials (excluded from N; a replacement trial was run for each): ' + '; '.join(
            '`%s/%s_c%s_%s_%s_t%s`: %s' % (r['sub'], r['cq_type'], r['classify'], r['fault'], r['wait_mode'], r['trial'],
                                           r['invalid']) for r in inval))
        p()
    st = [r for r in R if r['sub'] == 'stock' and not r['invalid']]
    if st:
        n = len(st)
        p('### 1b. Stock control (classifier off), ring CQ, F1, blocking wait')
        p()
        p('| N | silent success (initiator counted the failed put as done) | device rc | fault -> host API (ms) | host error | '
          'abort clean / leftover 0 | doorbell | driver |')
        p('|--:|---|---|---|---|---|---|---|')
        cf = lambda c: ', '.join('%s %d' % kv for kv in c.items())
        p('| %d | %s | %s | %s | %s | %d/%d / %d/%d | %s | %s |' % (
            n, prop(ssum(st, lambda r: r['silent']), n),
            cf(Counter('success (no error returned)' if not r['device_rc'] else r['device_rc'] for r in st)),
            dist([r['t_api_ms'] for r in st], 1),
            cf(Counter('ncclRemoteError' if r['host_error'] == 'remote' else r['host_error'] for r in st)),
            ssum(st, lambda r: r['teardown_clean']), n, ssum(st, lambda r: r['left0']), n,
            cf(Counter(r['doorbell'] for r in st)), cf(Counter(r['driver'] for r in st))))
        p()
    pc = [r for r in R if r['sub'] == 'posctl']
    if pc:
        p('Positive control for the doorbell indicators (same gin_q4 build, `NCCL_GIN_GDAKI_NIC_HANDLER=1`): %s' % '; '.join(
            '%s: proxy thread r0/r1 %s/%s, DOCA "Enabling CPU proxy mode" lines r0/r1 %s/%s -> %s, class %s' % (
                r['trial'], r['proxy_thread_r0'], r['proxy_thread_r1'], r['doca_proxy_lines_r0'], r['doca_proxy_lines_r1'],
                r['doorbell'], r['q4_class']) for r in pc))
        p()


# ======================================================================= 2. GDAKI recovery (gin_recovery)
def rec_cell(t):
    f, tr, rec = t['fault'], t['trial'], t['rec']
    b = {'v1cpu': 'v1cpu', 'prev_v1_cpufallback': 'v1cpu'}.get(t['sub'], 'v2')
    if tr.startswith('n') or 'keep' in tr:
        return 'diag'
    if tr.startswith('p'):
        b = 'v2proxy'
    if rec == '0':
        return '%s off %s' % (b, f)
    if tr.startswith('m') or tr.startswith('cm') or tr.startswith('pm'):
        return '%s %s x5' % (b, f)
    return '%s %s' % (b, f)


def q4rec(log):
    m = re.search(r'GIN/Q4: device-classified error CQE .*? fp=(\S+) .*? class=(\S+)', readtext(log))
    return (m.group(2), m.group(1)) if m else ('', '')


def rec_load(logdirs, tp, ep, sub):
    """regenerate trials/events CSVs from <logdirs> with gin_recovery/scripts/rec_rows.py (unchanged), judge each trial"""
    T, E = [], []
    logdirs = [x for x in logdirs if os.path.isdir(x)]
    if not logdirs:
        return T, E
    subprocess.run([PY, G + '/gin_recovery/scripts/rec_rows.py'] + logdirs + ['--trials', tp, '--events', ep],
                   check=True, stdout=subprocess.DEVNULL)
    ev = load(ep)
    if True:
        for t in load(tp):
            stem = next(os.path.join(x, t['stem']) for x in logdirs if os.path.exists(os.path.join(x, t['stem'] + '_meta.txt')))
            drv, ver = drvcfg(stem + '_drv.txt')
            cls, fp = q4rec(stem + '_r0.log')
            t = dict(sub=sub, **t)
            t['cell'] = rec_cell(t)
            p0, p1 = t['proxy_thread_r0'], t['proxy_thread_r1']
            w0, w1 = int(t['doca_proxy_warn_r0'] or 0), int(t['doca_proxy_warn_r1'] or 0)
            if t['db_mode_r0'] == 'GPU' and t['db_mode_r1'] == 'GPU' and p0 == '0' and p1 in ('0', '') and w0 == 0 and w1 == 0:
                door = 'GPU (logged mode=GPU)'
            elif p0 == '1' and p1 in ('1', '') and w0 > 0 and (w1 > 0 or t['fault'] == 'F4'):
                door = 'CPU_PROXY' + (' (logged)' if t['db_mode_r0'] == 'CPU_PROXY' else ' (thread+DOCA)')
            else:
                door = 'MIXED'
            t.update(driver=drv, nvidia=ver, doorbell=door, r0_first_class=cls, r0_first_fp=fp)
            # fault -> host API for the first fault event: t_query = ncclGinFaultQuery returned the class (host API),
            # t_mbx = host watcher read the device record. Fault time: F1 hook fire (r0 log), F3 hook fire (r1 log)
            # - clock offset, F2 fault_mono_ms (r0 KV), F4 kill_mono_ms (sunny) - clock offset.
            kv0 = readtext(stem + '_r0.kv')
            off = fl((re.findall(r'clock_offset_ms=(\S+)', kv0) or [None])[0]) or 0.0
            ft = None
            if t['fault'] == 'F1':
                m = re.search(r'GDAKI fault fired.*?fire_mono_ms=([\d.]+)', readtext(stem + '_r0.log'))
                ft = fl(m.group(1)) if m else None
            elif t['fault'] == 'F3':
                m = re.search(r'GDAKI fault fired.*?fire_mono_ms=([\d.]+)', readtext(stem + '_r1.log'))
                ft = fl(m.group(1)) - off if m else None
            elif t['fault'] == 'F2':
                m = re.search(r'fault_mono_ms=([\d.]+)', kv0)
                ft = fl(m.group(1)) if m else None
            elif t['fault'] == 'F4':
                m = re.search(r'kill_mono_ms=([\d.]+)', readtext(stem + '_kill.out'))
                ft = fl(m.group(1)) - off if m else None
            fe = re.search(r'^fault ev=1 .*$', kv0, re.M)
            fe = dict(re.findall(r'(\w+)=(\S+)', fe.group(0))) if fe else {}
            rel = lambda k: ('%.3f' % (fl(fe[k]) - ft)) if (ft is not None and fl(fe.get(k))) else ''
            t.update(fault_abs_ms='' if ft is None else '%.3f' % ft, f_to_dev_ms=rel('t_dev'), f_to_mbx_ms=rel('t_mbx'),
                     f_to_kret_ms=rel('t_kret'), f_to_query_ms=rel('t_query'), first_ev_class=fe.get('class', ''),
                     first_ev_fp=fe.get('fp', ''))
            evs = [e for e in ev if e['stem'] == t['stem']]
            it = t['iters']
            data_ok = (t['r1_data'] == 'ok' and t['r1_iters_ok'] == it and t['signal_exact'] == '1'
                       and t['final_signal'] == t['expected_final'] and t['r0_iters_ok'] == it)
            clean = t['r0rc'] == '0' and t['r1rc'] == '0' and t['left'] == '0' and t['abort0'] == 'no error' \
                and t['abort1'] == 'no error'
            c = t['cell']
            f = t['fault']
            want_cls = {'F1': 'LOCAL_QP_ERR', 'F3': 'RETRY_EXC'}.get(f)
            fault_evs = [e for e in evs if e['outcome'] in ('recovered', 'replay_failed')]
            cls_ok = all(e['cls'] == want_cls for e in fault_evs) if want_cls else True
            d1 = all(e['d'] == '1' for e in fault_evs)
            if t['rec'] == '0':
                ok = (t['r0rc'] == '8' and t['rec_events'] == '0' and cls == want_cls and t['abort0'] == 'no error'
                      and t['left'] == '0')
                why = 'r0rc=%s rec_events=%s class=%s abort0=%s' % (t['r0rc'], t['rec_events'], cls, t['abort0'])
            elif f in ('F1', 'F3') and ' x5' not in c:
                ok = data_ok and clean and t['shots_fired'] == '1' and t['recovered'] == '1' and t['replay_failed'] == '0' \
                    and t['declined'] == '0' and cls_ok and d1
                why = ''
            elif f in ('F1', 'F3'):
                ok = data_ok and clean and t['shots_fired'] == '5' and t['recovered'] == '4' and t['replay_failed'] == '1' \
                    and t['declined'] == '0' and cls_ok and d1
                why = ''
            elif f == 'D0':
                ok = data_ok and clean and t['recovered'] == '3' and t['delta_zero'] == '3' and t['declined'] == '0' \
                    and all(e['d'] == '0' for e in evs)
                why = ''
            elif f == 'F2':
                ok = (t['declined'] == '1' and t['decline_reason'] == 'class_REM_ACCESS' and t['decline_fp'] == '10/0x88'
                      and t['r0rc'] == '9' and t['r1rc'] == '9' and t['abort0'] == 'no error' and t['abort1'] == 'no error'
                      and t['left'] == '0')
                why = ''
            elif f == 'F4':
                ok = (t['declined'] == '1' and t['decline_reason'] == 'retry_exc_peer_dead' and t['decline_fp'] == '12/0x81'
                      and t['r0rc'] == '9' and t['abort0'] == 'no error' and t['left'] == '0')
                why = ''
            else:
                ok, why = False, 'unknown cell'
            if not ok and not why:
                why = ('r0rc=%s r1rc=%s left=%s shots=%s rec=%s rf=%s decl=%s(%s %s) r0ok=%s r1ok=%s/%s data=%s sig=%s %s/%s '
                       'abort=%s/%s cls_ok=%s d1=%s' % (
                           t['r0rc'], t['r1rc'], t['left'], t['shots_fired'], t['recovered'], t['replay_failed'],
                           t['declined'], t['decline_reason'], t['decline_fp'], t['r0_iters_ok'], t['r1_iters_ok'], it,
                           t['r1_data'], t['signal_exact'], t['final_signal'], t['expected_final'], t['abort0'], t['abort1'],
                           cls_ok, d1))
            k1t = readtext(stem + '_r1.kv')
            t['invalid'] = '' if ('gin_available=1' in kv0 and 'gin_available=1' in k1t) else 'a rank did not initialise GIN'
            t.update(ok=int(ok), fail_detail=why, data_ok=int(data_ok))
            T.append(t)
            for e in evs:
                E.append(dict(sub=sub, cell=t['cell'], **e))
    return T, E


def rec_rows():
    T, E = [], []
    for sub in ('v2', 'v1cpu', 'smoke'):
        d = os.path.join(RECR, sub)
        t, e = rec_load([os.path.join(d, 'logs')], os.path.join(d, 'trials.csv'), os.path.join(d, 'events.csv'), sub)
        T += t
        E += e
    write_csv(os.path.join(RECR, 'rec_n30_trials.csv'), T)
    write_csv(os.path.join(RECR, 'rec_n30_events.csv'), E)
    return T, E


REC_ORDER = ['v2 F1', 'v2 F3', 'v2 F1 x5', 'v2 F3 x5', 'v2 D0', 'v2 F2', 'v2 F4', 'v2 off F1', 'v2 off F3',
             'v1cpu F1', 'v1cpu F3']
REC_CRIT = {
    'F1': 'recovered once (d=1), 120/120 ops bit-exact + signal exact each op + final signal exact, both exit 0, aborts return',
    'F3': 'same as F1 (class RETRY_EXC, peer alive)',
    'F1 x5': '5 shots, 4 recovered + 1 replay failed (shot inside the commit), all d=1, 160/160 bit-exact, signals exact',
    'F3 x5': '5 shots, 4 recovered + 1 replay failed, all d=1, 200/200 bit-exact, signals exact',
    'D0': '3 forced recoveries with d=0 (nothing replayed), 120/120 bit-exact, signals exact',
    'F2': 'declined (class_REM_ACCESS, fp 10/0x88), both ranks exit 9, both aborts return',
    'F4': 'declined (retry_exc_peer_dead, fp 12/0x81), initiator exits 9, abort returns',
    'off F1': 'recovery flag off: initiator exits 8 with the Q4 class LOCAL_QP_ERR, no recovery event, abort returns',
    'off F3': 'recovery flag off: initiator exits 8 with the Q4 class RETRY_EXC, no recovery event, abort returns',
}


def rec_tables(T, E):
    p('### 2. GDAKI recovery (v2 = gin_recovery_gpudb, GPU doorbells; v1cpu = gin_recovery with the CPU proxy forced)')
    p()
    p('| cell | wait | N | success (criterion below) | Wilson 95% CI | kernel return -> recovered (ms), per recovered round | '
      'fault -> recovered (ms) | fault -> host API (ms; declines: ncclGinFaultQuery returned, flag off: ncclCommGetAsyncError) | rounds: recovered / replay failed / d=1 / d=0 | doorbell | driver |')
    p('|---|---|--:|---|---|---|---|---|---|---|---|')
    main = [t for t in T if t['sub'] in ('v2', 'v1cpu') and not t['invalid']]
    for c in REC_ORDER:
        rows = [t for t in main if t['cell'] == c]
        if not rows:
            continue
        for w, rs in [('both', rows)] + [(w, [t for t in rows if t['wait'] == w]) for w in ('timeout', 'blocking')]:
            n = len(rs)
            if not n:
                continue
            stems = set(t['stem'] for t in rs)
            ev = [e for e in E if e['sub'] == rs[0]['sub'] and e['stem'] in stems]
            rec = [e for e in ev if e['outcome'] == 'recovered']
            x = ssum(rs, lambda t: t['ok'])
            lo, hi = wilson(x, n)
            nd = 0 if 'F3' in c or 'F4' in c else 2
            p('| %s | %s | %d | %d/%d | %.1f-%.1f%% | %s | %s | %s | %d / %d / %d / %d | %s | %s |' % (
                c, w, n, x, n, 100 * lo, 100 * hi,
                dist([e['kret_to_recovered_ms'] for e in rec], 2),
                dist([e['fault_to_recovered_ms'] for e in rec], nd),
                dist([t['surface_ms'] if 'off' in c else t['f_to_query_ms'] for t in rs], nd) if ('F2' in c or 'F4' in c or 'off' in c) else '-',
                len(rec), ssum(ev, lambda e: e['outcome'] == 'replay_failed'), ssum(ev, lambda e: e['d'] == '1'),
                ssum(ev, lambda e: e['d'] == '0'),
                ','.join('%s %d' % kv for kv in Counter(t['doorbell'] for t in rs).items()),
                ','.join('%s %d' % kv for kv in Counter(t['driver'] for t in rs).items())))
    p()
    p('Success criteria: ' + '; '.join('**%s**: %s' % kv for kv in REC_CRIT.items()) + '.')
    p()
    bad = [t for t in main if not t['ok']]
    if bad:
        p('Trials that did not meet their criterion:')
        p()
        for t in bad:
            p('- `%s/%s`: %s' % (t['sub'], t['stem'], t['fail_detail']))
        p()


# =============================================================================== 3. NVSHMEM IBGDA + FT
NVTRUE = {'F1': ('LOCAL_QP_ERR', '5/0xf5'), 'F2b': ('REM_ACCESS', '10/0x88'), 'F3': ('RETRY_EXC', '12/0x81'),
          'F4': ('RETRY_EXC', '12/0x81')}


def nv_load(root, subdirs, tp, ep, decline_dir='decline'):
    """regenerate trials/events CSVs with nvshmem_ft/scripts/rows.py (unchanged) and judge each trial; <decline_dir>
    is the directory whose F2b/F4 trials ran with recovery on (b2: 'recover')"""
    dirs = [os.path.join(root, s) for s in subdirs if os.path.isdir(os.path.join(root, s))]
    if not dirs:
        return [], []
    subprocess.run([PY, G + '/nvshmem_ft/scripts/rows.py'] + dirs + ['--trials', tp, '--events', ep], check=True,
                   stdout=subprocess.DEVNULL)
    T, E = [], load(ep)
    for t in load(tp):
        base = os.path.join(root, t['dir'], t['tag'])
        if t['dir'] == decline_dir and t['fault'] in ('F2b', 'F4') and t['recover'] == '1':
            t['dir'] = 'decline'
        if t['fault'] == 'none' or t['ft'] != '1' or t.get('ft_capture') or t.get('sentinel') or t.get('burst') not in ('1', '') \
                or t.get('qdelay_us'):
            continue
        l0, l1 = readtext(base + '.pe0.log'), readtext(base + '.pe1.log')
        h0 = len(re.findall(r'NIC handler will be GPU', l0))
        h1 = len(re.findall(r'NIC handler will be GPU', l1))
        m = re.search(r'\[nvshmem-ft\] PE0 enabled: .*? handler=(\S+)', l0)
        fth = m.group(1) if m else ''
        door = 'GPU' if (h0 >= 1 and h1 >= 1 and fth == 'GPU') else 'CHECK h0=%d h1=%d ft=%s' % (h0, h1, fth)
        drv, ver = drvcfg(base + '.drv')
        f = t['fault']
        cls_ok = (t['first_class'], t['first_fp']) == NVTRUE.get(f)
        tr = dict(t)
        evs = [e for e in E if e['tag'] == t['tag']]
        n_it = t.get('ok_iters0')
        full = (t['pe0_rc'] == '0' and t['pe1_rc'] == '0' and t['ok_iters0'] == '200' and t['ok_iters1'] == '200'
                and t['rx_data_ok'] == '200' and t['rx_sig_exact'] == '200' and t['final_sig'] == t['expected_sig'] == '200'
                and t['rx_data_bad'] == '0' and t['declined'] == '0' and t['leftover'] == '0/0'
                and t['teardown0'] == 'returned' and t['teardown1'] == 'returned')
        allcls = all(e['class'] == NVTRUE[f][0] for e in evs) if f in NVTRUE else True
        d1 = all(e.get('d') == '1' for e in evs)
        if t['dir'] == 'classify':
            silent = int((fl(t['ok_iters0']) or 0) > (fl(t['rx_data_ok']) or 0)) if f != 'F4' else ''
            ok = cls_ok and t['declined'] == '1' and t['teardown0'] == 'returned' and t['leftover'] == '0/0' and \
                (t['teardown1'] == 'returned' or f == 'F4') and t['rx_data_bad'] == '0'
            cell = 'classify ' + f
        elif t['dir'] == 'recover':
            silent = ''
            ok = full and t['faults_fired'] == '1' and t['rec_rounds'] == '1' and t['rec_ok_ops'] == '1' and allcls and d1
            cell = 'recover ' + f
        elif t['dir'] == 'multi':
            silent = ''
            ok = full and t['faults_fired'] == '5' and t['rec_rounds'] == '5' and t['rec_ok_ops'] == '4' and allcls and d1
            cell = 'recover %s x5' % f
        elif t['dir'] == 'decline':
            silent = ''
            want = {'F2b': 'class not recoverable', 'F4': 'RETRY_EXC with the peer dead'}[f]
            ok = cls_ok and t['declined'] == '1' and t['decline_reason'] == want and t['pe0_rc'] == '9' and \
                t['teardown0'] == 'returned' and t['leftover'] == '0/0' and t['rec_rounds'] == '0' and \
                (t['teardown1'] == 'returned' or f == 'F4') and t['rx_data_bad'] == '0'
            cell = 'decline ' + f
        else:
            silent, ok, cell = '', False, 'smoke ' + f
        tr.update(cell=cell, doorbell=door, driver=drv, nvidia=ver, class_ok=int(cls_ok), silent=silent, ok=int(ok),
                  handler_lines='%d/%d' % (h0, h1),
                  invalid='' if ('[PE0] ready' in l0 and '[PE1] ready' in l1) else 'a PE did not reach ready')
        if not ok:
            tr['fail_detail'] = ('pe_rc=%s/%s ok_iters=%s/%s rx_ok=%s rx_sig=%s rx_bad=%s sig=%s/%s fired=%s rounds=%s rec_ok=%s '
                                 'declined=%s(%s) class=%s %s td=%s/%s left=%s allcls=%s d1=%s' % (
                                     t['pe0_rc'], t['pe1_rc'], t['ok_iters0'], t['ok_iters1'], t['rx_data_ok'],
                                     t['rx_sig_exact'], t['rx_data_bad'], t['final_sig'], t['expected_sig'],
                                     t['faults_fired'], t['rec_rounds'], t['rec_ok_ops'], t['declined'],
                                     t['decline_reason'], t['first_class'], t['first_fp'], t['teardown0'],
                                     t['teardown1'], t['leftover'], allcls, d1))
        T.append(tr)
    for e in E:
        t = next((x for x in T if x['tag'] == e['tag']), None)
        e['cell'] = t['cell'] if t else ''
        if t:
            e['dir'] = t['dir']
    return T, [e for e in E if e['cell']]


def nv_rows():
    # smoke/ is excluded: its tag F1_timeout_ft1_rec0_t1 collides with classify/ (events are matched by tag)
    T, E = nv_load(NVR, ('classify', 'recover', 'multi', 'decline'), os.path.join(NVR, 'trials.csv'),
                   os.path.join(NVR, 'events.csv'))
    write_csv(os.path.join(NVR, 'nv_n30_trials.csv'), T)
    write_csv(os.path.join(NVR, 'nv_n30_events.csv'), E)
    return T, E


NV_ORDER = ['classify F1', 'classify F2b', 'classify F3', 'classify F4', 'recover F1', 'recover F3', 'recover F1 x5',
            'recover F3 x5', 'decline F2b', 'decline F4']
NV_CRIT = {
    'classify': 'first device record = true class and fp (F1 LOCAL_QP_ERR 5/0xf5, F2b REM_ACCESS 10/0x88, F3/F4 RETRY_EXC 12/0x81), '
                'no op verified wrong on the target, PE0 declines (classification run) and nvshmem_finalize returns (PE1 too unless killed), no leftovers',
    'recover': '1 fault round recovered (d=1, class right), 200/200 ops bit-exact with exact per-op signal, final signal 200, both exit 0, both finalize return',
    'recover x5': '5 shots, 5 rounds, 4 recovered ops + 1 replay hit by the in-commit shot, all d=1, 200/200 bit-exact, final signal 200',
    'decline': 'declined for the right reason (F2b "class not recoverable", F4 "RETRY_EXC with the peer dead"), PE0 exits 9, finalize returns',
}


def nv_tables(T, E):
    p('### 3. NVSHMEM IBGDA + FT patch (GPU NIC handler)')
    p()
    p('| cell | wait | N | success | Wilson 95% CI | class + fp correct | fault -> device (ms) | fault -> host mailbox (ms) | '
      'kernel return -> recovered (ms) | fault -> recovered (ms) | finalize PE0 / PE1 (ms) | silent success | doorbell | driver |')
    p('|---|---|--:|---|---|---|---|---|---|---|---|---|---|---|')
    main = [t for t in T if not t['cell'].startswith('smoke') and not t['invalid']]
    for c in NV_ORDER:
        rows = [t for t in main if t['cell'] == c]
        if not rows:
            continue
        for w, rs in [('both', rows)] + [(w, [t for t in rows if t['mode'] == w]) for w in ('timeout', 'blocking')]:
            n = len(rs)
            if not n:
                continue
            tags = set((t['dir'], t['tag']) for t in rs)
            ev = [e for e in E if (e['dir'], e['tag']) in tags]
            x = ssum(rs, lambda t: t['ok'])
            lo, hi = wilson(x, n)
            nd = 0 if ('F3' in c or 'F4' in c) else 2
            sil = [t['silent'] for t in rs if t['silent'] != '']
            p('| %s | %s | %d | %d/%d | %.1f-%.1f%% | %s | %s | %s | %s | %s | %s / %s | %s | %s | %s |' % (
                c, w, n, x, n, 100 * lo, 100 * hi, prop(ssum(rs, lambda t: t['class_ok']), n),
                dist([t['first_fault_to_dev_ms'] for t in rs], nd), dist([t['first_fault_to_mbx_ms'] for t in rs], nd),
                dist([e.get('ret_to_recovered_ms') for e in ev if e.get('fault_to_recovered_ms')], 2) if 'recover' in c else '-',
                dist([e.get('fault_to_recovered_ms') for e in ev], nd) if 'recover' in c else '-',
                dist([t['finalize0_ms'] for t in rs], 1), dist([t['finalize1_ms'] for t in rs], 1),
                ('%d/%d' % (sum(int(s) for s in sil), len(sil))) if sil else '-',
                ','.join('%s %d' % kv for kv in Counter(t['doorbell'] for t in rs).items()),
                ','.join('%s %d' % kv for kv in Counter(t['driver'] for t in rs).items())))
    p()
    p('Success criteria: ' + '; '.join('**%s**: %s' % kv for kv in NV_CRIT.items()) + '.')
    p()
    bad = [t for t in main if not t['ok']]
    if bad:
        p('Trials that did not meet their criterion:')
        p()
        for t in bad:
            p('- `%s/%s`: %s' % (t['dir'], t['tag'], t.get('fail_detail', '')))
        p()


# ============================================================== 4. comparison with the earlier small-N runs
PREV = '/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_n30/prev'
W1_INVALID = {'ring_c1_none_timeout_t1', 'ring_c1_none_timeout_t2', 'ring_c1_F1_timeout_t1', 'ring_c1_F1_timeout_t2',
              'ring_c1_F2_timeout_t1'}   # gpu_doorbell README: sunny's CUDA broken in window 1


def fisher(a, n1, c, n2):
    """two-sided Fisher exact p for [[a, n1-a], [c, n2-c]]"""
    K, N = a + c, n1 + n2
    def h(k):
        return math.comb(K, k) * math.comb(N - K, n1 - k) / math.comb(N, n1)
    po = h(a)
    return min(1.0, sum(h(k) for k in range(max(0, K - n2), min(K, n1) + 1) if h(k) <= po * (1 + 1e-9)))


def _ranks(v):
    o = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def mwu_p(x, y, draws=20000, seed=1):
    """two-sided Mann-Whitney permutation p (exact enumeration when small, else Monte Carlo)"""
    import itertools, random
    x = [v for v in (fl(a) for a in x) if v is not None]
    y = [v for v in (fl(a) for a in y) if v is not None]
    if len(x) < 2 or len(y) < 2:
        return None
    pool = x + y
    r = _ranks(pool)
    n1 = len(x)
    mean = n1 * (len(pool) + 1) / 2
    obs = abs(sum(r[:n1]) - mean)
    if math.comb(len(pool), n1) <= 200000:
        tot = hit = 0
        for c in itertools.combinations(range(len(pool)), n1):
            tot += 1
            hit += abs(sum(r[i] for i in c) - mean) >= obs - 1e-9
        return hit / tot
    rnd = random.Random(seed)
    idx = list(range(len(pool)))
    hit = 0
    for _ in range(draws):
        rnd.shuffle(idx)
        hit += abs(sum(r[i] for i in idx[:n1]) - mean) >= obs - 1e-9
    return (hit + 1) / (draws + 1)


def mm(vals, nd):
    v = [x for x in (fl(a) for a in vals) if x is not None]
    if not v:
        return '-'
    f = '%.' + str(nd) + 'f'
    return (f + ' [' + f + '-' + f + ']') % (pct(v, .5), min(v), max(v))


CMP = OrderedDict()


def cmp_line(cell, src, old_ok, old_n, old_t, new_ok, new_n, new_t, nd, key=None):
    fp = fisher(old_ok, old_n, new_ok, new_n) if old_n and new_n else None
    mp = mwu_p(old_t, new_t)
    nv = [x for x in (fl(a) for a in new_t) if x is not None]
    ov = [x for x in (fl(a) for a in old_t) if x is not None]
    diff = []
    if fp is not None and fp < 0.05:
        diff.append('success rate')
    if mp is not None and mp < 0.05:
        diff.append('time (N30 median %+.*f ms vs earlier)' % (nd, pct(nv, .5) - pct(ov, .5)) if ov and nv else 'time')
    verdict = ('different: ' + ', '.join(diff)) if diff else 'same (no detectable difference)'
    if key:
        CMP.setdefault(key, []).append(dict(src=src, old='%d/%d' % (old_ok, old_n), old_t=mm(old_t, nd),
                                            verdict=verdict, short='same' if not diff else 'diff: ' + ', '.join(diff)))
    p('| %s | %s | %d/%d | %d/%d | %s | %s | %s | %s | %s |' % (
        cell, src, old_ok, old_n, new_ok, new_n, mm(old_t, nd), mm(new_t, nd),
        '-' if fp is None else '%.3g' % fp, '-' if mp is None else '%.3g' % mp, verdict))


def q4_ok(r):
    return bool(r['class_ok'] and r['dev_rc_err'] and r['api_err'] and r['teardown_clean'] and
                (r['fault'] == 'F4' or not r['silent']))


def compare(Rq, Tr, Er, Tn, En):
    os.makedirs(PREV, exist_ok=True)
    P = lambda *a: os.path.join(G, *a)
    cpuB = q4_load(P('gin_q4/results/20260923/taskB/logs'), PREV + '/q4_taskB.csv', 'prev')
    cpuA = q4_load(P('gin_q4/results/20260923/taskA/logs'), PREV + '/q4_taskA.csv', 'prev')
    gq = q4_load(P('gin_recovery/results/20260924_gpudb/q4/logs'), PREV + '/q4_gpudb.csv', 'prev')
    w1 = q4_load(P('gpu_doorbell/results/20260924/gin_q4/logs'), PREV + '/q4_w1.csv', 'prev')
    w2 = q4_load(P('gpu_doorbell/results/20260924_w2/gin_q4/logs'), PREV + '/q4_w2.csv', 'prev')
    stemof = lambda r: '%s_c%s_%s_%s_t%s' % (r['cq_type'], r['classify'], r['fault'], r['wait_mode'], r['trial'])
    gpu_prev = [r for r in gq if not r['trial'].startswith('px')] + [r for r in w1 if stemof(r) not in W1_INVALID] + w2
    new = [r for r in Rq if r['sub'] == 'main' and not r['invalid']]
    cpuB = [r for r in cpuB if not r['invalid']]
    cpuA = [r for r in cpuA if not r['invalid']]
    gpu_prev = [r for r in gpu_prev if not r['invalid']]
    p('### 4a. GIN GDAKI + Q4: earlier small-N vs N30 (success = class+fp right, device and host API return the error, '
      'no silent success except F4, abort clean; time = fault -> host API, ms)')
    p()
    p('| cell | earlier source (doorbell) | earlier success | N30 success | earlier time median [min-max] | '
      'N30 time median [min-max] | Fisher p | Mann-Whitney p | verdict |')
    p('|---|---|---|---|---|---|---|---|---|')
    for cq in ('ring', 'collapsed'):
        for f in ('F1', 'F2', 'F3', 'F4'):
            nr = [r for r in new if r['cq_type'] == cq and r['fault'] == f]
            nd = 2 if f in ('F1', 'F2') else 0
            for src, rows in (('09-23 CPU doorbell, ' + ('Task B' if cq == 'ring' else 'Task A'),
                               [r for r in (cpuB if cq == 'ring' else cpuA) if r['cq_type'] == cq and r['classify'] == '1']),
                              ('09-24 GPU doorbell (windows + q4 re-run)', [r for r in gpu_prev if r['cq_type'] == cq and r['classify'] == '1'])):
                o = [r for r in rows if r['fault'] == f]
                if not o or not nr:
                    continue
                cmp_line('%s %s' % (cq, f), src + ', n=%d' % len(o), ssum(o, q4_ok), len(o), [r['t_api_ms'] for r in o],
                         ssum(nr, q4_ok), len(nr), [r['t_api_ms'] for r in nr], nd, key=('q4', cq, f))
    ns = [r for r in Rq if r['sub'] == 'stock' and not r['invalid']]
    for src, o in (('09-23 CPU doorbell, Task B', [r for r in cpuB if r['classify'] == '0' and r['fault'] == 'F1' and r['wait_mode'] == 'blocking']),
                   ('09-24 GPU doorbell window 1', [r for r in w1 if r['classify'] == '0' and r['fault'] == 'F1' and r['wait_mode'] == 'blocking'])):
        if o and ns:
            cmp_line('stock F1 blocking: silent success', src + ', n=%d' % len(o), ssum(o, lambda r: r['silent']), len(o),
                     [r['t_api_ms'] for r in o], ssum(ns, lambda r: r['silent']), len(ns), [r['t_api_ms'] for r in ns], 1,
                     key=('q4', 'stock', 'F1'))
    p()

    # ---- recovery
    pv1, pv1e = rec_load([P('gin_recovery/results/20260924/runs/logs'), P('gin_recovery/results/20260924/confirm/logs')],
                         PREV + '/rec_v1_trials.csv', PREV + '/rec_v1_events.csv', 'prev_v1_cpufallback')
    pv2, pv2e = rec_load([P('gin_recovery/results/20260924_gpudb/runs/logs')], PREV + '/rec_v2_trials.csv',
                         PREV + '/rec_v2_events.csv', 'prev_v2_gpu')
    p('### 4b. GDAKI recovery: earlier small-N vs N30 (success = same criterion as table 2; time = kernel return -> recovered '
      'per recovered round; declines: fault -> ncclGinFaultQuery returned; flag off: fault -> ncclCommGetAsyncError; ms)')
    p()
    p('| cell | earlier source | earlier success | N30 success | earlier time median [min-max] | N30 time median [min-max] | '
      'Fisher p | Mann-Whitney p | verdict |')
    p('|---|---|---|---|---|---|---|---|---|')
    newT = [t for t in Tr if t['sub'] in ('v2', 'v1cpu') and not t['invalid']]
    for c in REC_ORDER:
        nt = [t for t in newT if t['cell'] == c]
        if not nt:
            continue
        key = c.split(' ', 1)[1]
        srcs = [('09-24 v2, GPU doorbell', pv2, pv2e)] if c.startswith('v2') else []
        srcs.append(('09-24 v1, CPU-doorbell fallback (before PMO)', pv1, pv1e))
        for src, PT, PE in srcs:
            ot = [t for t in PT if t['cell'].partition(' ')[2] == key and not t['cell'].startswith('v2proxy') and not t['invalid']]
            if not ot:
                continue
            decl = key in ('F2', 'F4') or key.startswith('off')
            def times(T, E):
                if decl:
                    return [t['surface_ms'] if key.startswith('off') else t['f_to_query_ms'] for t in T]
                st = set(t['stem'] for t in T)
                return [e['kret_to_recovered_ms'] for e in E if e['stem'] in st and e['outcome'] == 'recovered']
            cmp_line(c, src + ', n=%d' % len(ot), ssum(ot, lambda t: t['ok']), len(ot), times(ot, PE),
                     ssum(nt, lambda t: t['ok']), len(nt), times(nt, [e for e in Er if e['sub'] == nt[0]['sub']]),
                     0 if (decl and ('F3' in key or 'F4' in key)) else 2, key=('rec', c))
    p()

    # ---- NVSHMEM
    pn, pne = nv_load(P('nvshmem_ft/results/b2'), ('classify', 'recover', 'multi'), PREV + '/nv_b2_trials.csv',
                      PREV + '/nv_b2_events.csv', decline_dir='recover')
    p('### 4c. NVSHMEM FT: earlier small-N (results/b2, 2026-09-24, GPU handler) vs N30 (success = same criterion as table 3; '
      'time = fault -> host mailbox for classify/decline, kernel return -> recovered per recovered round for recover, ms)')
    p()
    p('| cell | earlier source | earlier success | N30 success | earlier time median [min-max] | N30 time median [min-max] | '
      'Fisher p | Mann-Whitney p | verdict |')
    p('|---|---|---|---|---|---|---|---|---|')
    for c in NV_ORDER:
        nt = [t for t in Tn if t['cell'] == c and not t['invalid']]
        ot = [t for t in pn if t['cell'] == c and not t['invalid']]
        if not nt or not ot:
            continue
        if c.startswith('recover'):
            ntag, otag = set(t['tag'] for t in nt), set(t['tag'] for t in ot)
            tn = [e.get('ret_to_recovered_ms') for e in En if e['tag'] in ntag and e.get('fault_to_recovered_ms')]
            to = [e.get('ret_to_recovered_ms') for e in pne if e['tag'] in otag and e.get('fault_to_recovered_ms')]
            nd = 2
        else:
            tn, to = [t['first_fault_to_mbx_ms'] for t in nt], [t['first_fault_to_mbx_ms'] for t in ot]
            nd = 0 if ('F3' in c or 'F4' in c) else 2
        cmp_line(c, 'b2, n=%d' % len(ot), ssum(ot, lambda t: t['ok']), len(ot), to, ssum(nt, lambda t: t['ok']), len(nt), tn, nd,
                 key=('nv', c))
    fo = [t['finalize0_ms'] for t in pn]
    fnw = [t['finalize0_ms'] for t in Tn if not t['cell'].startswith('smoke')]
    cmp_line('nvshmem_finalize PE0, all cells', 'b2, n=%d' % len(fo), len(fo), len(fo), fo, len(fnw), len(fnw), fnw, 1,
             key=('nv', 'finalize'))
    p()


def summary(Rq, Tr, Er, Tn, En):
    """one row per requested cell; must run after compare() (uses CMP)"""
    S = []
    def earlier(key):
        c = CMP.get(key, [])
        return '; '.join('%s: %s, %s' % (x['src'], x['old'], x['old_t']) for x in c) or '-', \
            '; '.join(x['short'] for x in c) or '-'
    def fails(rows, idf, why):
        b = [r for r in rows if not idf(r)]
        return '%d%s' % (len(b), (' (' + ', '.join(why(r) for r in b[:4]) + (', ...' if len(b) > 4 else '') + ')') if b else '')
    main = [r for r in Rq if r['sub'] == 'main' and not r['invalid']]
    for cq in ('ring', 'collapsed'):
        for f in ('F1', 'F2', 'F3', 'F4'):
            rs = [r for r in main if r['cq_type'] == cq and r['fault'] == f]
            if not rs:
                continue
            ninv = ssum(Rq, lambda r: r['sub'] == 'main' and r['invalid'] and r['cq_type'] == cq and r['fault'] == f)
            e, v = earlier(('q4', cq, f))
            n, x = len(rs), ssum(rs, q4_ok)
            lo, hi = wilson(x, n)
            nsil = ssum([r for r in rs if r['wait_mode'] == 'blocking'], lambda r: r['silent'])
            oth = ('class %d/%d; silent success %d/%d (blocking %d/%d)' % (
                ssum(rs, lambda r: r['class_ok']), n, ssum(rs, lambda r: r['silent']), n, nsil,
                ssum(rs, lambda r: r['wait_mode'] == 'blocking')) if f != 'F4' else
                'class %d/%d; initiator 1 op ahead of the killed target %d/%d (last op ACKed before the kill; see §1)' % (
                ssum(rs, lambda r: r['class_ok']), n, ssum(rs, lambda r: r['silent']), n))
            S.append(('GIN Q4 classifier, %s CQ, %s' % (cq, f), n, x,
                      fails(rs, q4_ok, lambda r: '%s_t%s' % (r['wait_mode'], r['trial'])) +
                      ('; %d harness-invalid excluded + replaced' % ninv if ninv else ''), '%.1f-%.1f%%' % (100 * lo, 100 * hi),
                      'fault->host API ' + dist([r['t_api_ms'] for r in rs], 2 if f in ('F1', 'F2') else 0), oth, e, v))
    st = [r for r in Rq if r['sub'] == 'stock' and not r['invalid']]
    if st:
        e, v = earlier(('q4', 'stock', 'F1'))
        n, x = len(st), ssum(st, lambda r: r['silent'])
        lo, hi = wilson(x, n)
        S.append(('GIN stock control (classifier off), ring, F1, blocking: silent success', n, x, '-',
                  '%.1f-%.1f%%' % (100 * lo, 100 * hi), 'fault->host API ' + dist([r['t_api_ms'] for r in st], 1),
                  'success here = the failed put was reported done', e, v))
    newT = [t for t in Tr if t['sub'] in ('v2', 'v1cpu') and not t['invalid']]
    for c in REC_ORDER:
        rs = [t for t in newT if t['cell'] == c]
        if not rs:
            continue
        e, v = earlier(('rec', c))
        n, x = len(rs), ssum(rs, lambda t: t['ok'])
        lo, hi = wilson(x, n)
        k = c.partition(' ')[2]
        if k in ('F2', 'F4') or k.startswith('off'):
            tm = 'fault->host API ' + dist([t['surface_ms'] if k.startswith('off') else t['f_to_query_ms'] for t in rs],
                                           0 if ('F3' in k or 'F4' in k) else 2)
        else:
            st_ = set(t['stem'] for t in rs)
            ev = [q for q in Er if q['sub'] == rs[0]['sub'] and q['stem'] in st_ and q['outcome'] == 'recovered']
            tm = 'kernel return->recovered ' + dist([q['kret_to_recovered_ms'] for q in ev], 2)
        st_ = set(t['stem'] for t in rs)
        evs = [q for q in Er if q['sub'] == rs[0]['sub'] and q['stem'] in st_]
        if k in ('F2', 'F4'):
            oth = 'declined: ' + ', '.join('%s %d' % kv for kv in Counter(t['decline_reason'] for t in rs).items())
        elif k.startswith('off'):
            oth = 'Q4 class ' + ', '.join('%s %d' % kv for kv in Counter(t['r0_first_class'] for t in rs).items()) + \
                  '; recovery events %d' % sum(int(t['rec_events'] or 0) for t in rs)
        else:
            oth = 'rounds: %d recovered, %d replay failed; d=1 %d, d=0 %d' % (
                ssum(evs, lambda q: q['outcome'] == 'recovered'), ssum(evs, lambda q: q['outcome'] == 'replay_failed'),
                ssum(evs, lambda q: q['d'] == '1'), ssum(evs, lambda q: q['d'] == '0'))
        S.append(('GDAKI recovery %s' % c, n, x, fails(rs, lambda t: t['ok'], lambda t: t['stem']),
                  '%.1f-%.1f%%' % (100 * lo, 100 * hi), tm, oth, e, v))
    for c in NV_ORDER:
        rs = [t for t in Tn if t['cell'] == c and not t['invalid']]
        if not rs:
            continue
        e, v = earlier(('nv', c))
        n, x = len(rs), ssum(rs, lambda t: t['ok'])
        lo, hi = wilson(x, n)
        if c.startswith('recover'):
            tags = set(t['tag'] for t in rs)
            tm = 'kernel return->recovered ' + dist([q.get('ret_to_recovered_ms') for q in En if q['tag'] in tags and q.get('fault_to_recovered_ms')], 2)
        else:
            tm = 'fault->host mailbox ' + dist([t['first_fault_to_mbx_ms'] for t in rs], 0 if ('F3' in c or 'F4' in c) else 2)
        S.append(('NVSHMEM FT %s' % c, n, x, fails(rs, lambda t: t['ok'], lambda t: t['tag']), '%.1f-%.1f%%' % (100 * lo, 100 * hi),
                  tm, 'finalize PE0 ' + dist([t['finalize0_ms'] for t in rs], 1), e, v))
    # pooled headline claims (same per-trial verdicts)
    q = [r for r in Rq if r['sub'] == 'main' and not r['invalid']]
    rv = [t for t in Tr if t['sub'] in ('v2', 'v1cpu') and not t['invalid']]
    nv_ = [t for t in Tn if not t['invalid']]
    pools = [
        ('GIN Q4: classification exact (class + fp), all CQ x fault cells', q, lambda r: r['class_ok']),
        ('GIN Q4: all criteria, all CQ x fault cells', q, q4_ok),
        ('GIN Q4: no silent success, F1-F3', [r for r in q if r['fault'] != 'F4'], lambda r: not r['silent']),
        ('GDAKI recovery: fault runs recovered with exact data and signals (v2 F1, F3, x5; v1cpu F1, F3)',
         [t for t in rv if t['cell'] in ('v2 F1', 'v2 F3', 'v2 F1 x5', 'v2 F3 x5', 'v1cpu F1', 'v1cpu F3')], lambda t: t['ok']),
        ('GDAKI recovery: forced d=0 runs exact', [t for t in rv if t['cell'] == 'v2 D0'], lambda t: t['ok']),
        ('GDAKI recovery: F2/F4 declined for the right reason', [t for t in rv if t['cell'] in ('v2 F2', 'v2 F4')], lambda t: t['ok']),
        ('NVSHMEM FT: classification exact, classify cells', [t for t in nv_ if t['cell'].startswith('classify')], lambda t: t['class_ok']),
        ('NVSHMEM FT: recovery runs exact (F1, F3, x5)', [t for t in nv_ if t['cell'].startswith('recover')], lambda t: t['ok']),
        ('NVSHMEM FT: F2b/F4 declined for the right reason', [t for t in nv_ if t['cell'].startswith('decline')], lambda t: t['ok']),
        ('NVSHMEM FT: nvshmem_finalize returned on PE0, all cells', nv_, lambda t: t['teardown0'] == 'returned'),
    ]
    PO = []
    for name, rows, f in pools:
        n, x = len(rows), ssum(rows, f)
        lo, hi = wilson(x, n)
        PO.append('| %s | %d | %d | %.1f-%.1f%% |' % (name, n, x, 100 * lo, 100 * hi))
    p('### 0. Summary: one row per cell (success criteria in the stack sections; times in ms, median [p10-p90] max)')
    p()
    p('| cell | N | success | failures | Wilson 95% CI | time | other | earlier small-N (success, time median [min-max]) | same as earlier? |')
    p('|---|--:|--:|---|---|---|---|---|---|')
    for r in S:
        p('| %s | %d | %d | %s | %s | %s | %s | %s | %s |' % r)
    p()
    p('### 0p. Pooled claims (same per-trial verdicts, pooled over cells)')
    p()
    p('| claim | N | success | Wilson 95% CI |')
    p('|---|--:|--:|---|')
    for l in PO:
        p(l)
    p()


def main():
    R = q4_rows()
    q4_tables(R)
    T, E = rec_rows()
    rec_tables(T, E)
    NT, NE = nv_rows()
    nv_tables(NT, NE)
    compare(R, T, E, NT, NE)
    body = OUT[:]
    OUT.clear()
    summary(R, T, E, NT, NE)
    print('\n'.join(OUT + body))


if __name__ == '__main__':
    main()
