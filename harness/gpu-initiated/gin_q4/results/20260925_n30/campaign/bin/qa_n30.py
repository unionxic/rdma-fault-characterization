#!/usr/bin/env python3
"""qa_n30.py - independent cross-check of analyze_n30.py: re-derive each trial's verdict and key numbers
directly from the raw logs/KV files with separate, simpler parsing (no use of the stacks' row extractors),
then diff against <stack>_n30_trials.csv. Prints every disagreement; exit 1 if any.
"""
import csv, glob, gzip, os, re, sys

G = '/home/unionxic/rdma-error/harness/gpu-initiated'
SUB = sys.argv[sys.argv.index('--sub') + 1] if '--sub' in sys.argv else '20260925_n30'
Q4R, RECR, NVR = (os.path.join(G, s, 'results', SUB) for s in ('gin_q4', 'gin_recovery', 'nvshmem_ft'))
bad = []


def rt(p):
    if os.path.exists(p):
        return open(p, errors='replace').read()
    if os.path.exists(p + '.gz'):
        return gzip.open(p + '.gz', 'rt', errors='replace').read()
    return ''


def last(pat, text, default=None):
    m = re.findall(pat, text)
    return m[-1] if m else default


def first(pat, text, default=None):
    m = re.search(pat, text, re.M)
    return m.group(1) if m else default


def drv_ok(text):
    lines = re.findall(r'node=(\w+) nvidia=\S+ RegistryDwords="PeerMappingOverride=1;" EnableStreamMemOPs=1', text)
    return sorted(lines) == ['rain', 'sunny']


def cmp(stack, key, field, mine, theirs):
    if str(mine) != str(theirs):
        bad.append('%s %s %s: qa=%r analyze=%r' % (stack, key, field, mine, theirs))


# ------------------------------------------------------------------------------------------------ gin_q4
TRUE = {'F1': ('LOCAL_QP_ERR', '5/0xf5'), 'F2': ('REM_ACCESS', '10/0x88'), 'F3': ('RETRY_EXC', '12/0x81'),
        'F4': ('RETRY_EXC', '12/0x81')}
A = {}
for r in csv.DictReader(open(os.path.join(Q4R, 'q4_n30_trials.csv'))):
    A[(r['sub'], '%s_c%s_%s_%s_t%s' % (r['cq_type'], r['classify'], r['fault'], r['wait_mode'], r['trial']))] = r
nq = 0
for sub in ('main', 'stock', 'posctl'):
    for meta in sorted(glob.glob(os.path.join(Q4R, sub, 'logs', '*_meta.txt'))):
        stem = os.path.basename(meta)[:-9]
        b = meta[:-9]
        f = re.search(r'fault=(\S+)', rt(meta)).group(1)
        l0, k0, k1 = rt(b + '_r0.log'), rt(b + '_r0.kv'), rt(b + '_r1.kv')
        rec = re.search(r'GIN/Q4: device-classified error CQE .*? fp=(\S+) .*? class=(\S+)', l0)
        cls, fp = (rec.group(2), rec.group(1)) if rec else ('', '')
        ok0 = len(re.findall(r'^okit=', k0, re.M))
        ok1 = len(re.findall(r'^okit=', k1, re.M))
        dev_rc = last(r'\bdevice_rc=(\S+)', k0, '')
        herr = last(r'host_error=(\S+)', k0, '')
        herr1 = last(r'host_error=(\S+)', k1, '')
        td = last(r'teardown=(\S+)', k0, '')
        probe = rt(b + '_probe.txt')
        pthr = re.findall(r'gin_proxy_thread=(\S+)', probe)
        cpl = l0.count('Enabling CPU proxy mode') + rt(b + '_r1.log').count('Enabling CPU proxy mode')
        door = 'GPU' if (all(x == '0' for x in pthr) and cpl == 0) else ('CPU_PROXY' if all(x == '1' for x in pthr) and cpl > 0 else 'MIXED')
        a = A.get((sub, stem))
        nq += 1
        if a is None:
            bad.append('q4 %s/%s missing from analyze CSV' % (sub, stem))
            continue
        inv = not (re.search(r'^gin_available=1', k0, re.M) and re.search(r'^gin_available=1', k1, re.M))
        cmp('q4', stem, 'invalid', int(inv), int(bool(a['invalid'])))
        if inv:
            print('q4 harness-invalid: %s/%s (r0 log: %s)' % (sub, stem, l0.strip()[:60]))
            continue
        cmp('q4', stem, 'class_ok', int((cls, fp) == TRUE.get(f, ('?', '?'))), a['class_ok'])
        cmp('q4', stem, 'init_silent_iters', ok0 - ok1, a['init_silent_iters'])
        cmp('q4', stem, 'dev_rc_err', int(dev_rc == 'remote'), a['dev_rc_err'])
        cmp('q4', stem, 'api_err', int('remote' in (herr, herr1)), a['api_err'])
        cmp('q4', stem, 'teardown_clean', int(td == 'clean'), a['teardown_clean'])
        cmp('q4', stem, 'doorbell', door, a['doorbell'])
        cmp('q4', stem, 'driver_ok', int(drv_ok(rt(b + '_drv.txt'))), int(a['driver'] == 'PMO=1,SMO=1 both'))
        # independent t_api for the rank that surfaced first (r0 only if r1 had none)
        t0 = float(first(r't0_mono_ms=(\S+)', k0))
        hem = float(last(r'host_error_ms=(\S+)', k0, '-1'))
        if f == 'F1':
            ft = float(first(r'fire_mono_ms=([\d.]+)', l0))
        elif f == 'F2':
            ft = float(first(r'fault_mono_ms=([\d.]+)', k0))
        elif f == 'F3':
            ft = float(first(r'fire_mono_ms=([\d.]+)', rt(b + '_r1.log'))) - float(first(r'clock_offset_ms=(\S+)', k0))
        else:
            ft = float(first(r'kill_mono_ms=([\d.]+)', rt(b + '_kill.out'))) - float(first(r'clock_offset_ms=(\S+)', k0))
        if hem >= 0 and a['surface_by'] == 'r0':
            # host_error_ms is printed with 0.1 ms resolution by the driver; allow for rounding
            if abs((t0 + hem - ft) - float(a['t_api_ms'])) > 0.01:
                cmp('q4', stem, 't_api_ms', '%.3f' % (t0 + hem - ft), a['t_api_ms'])
print('q4: %d trials checked' % nq)

# ------------------------------------------------------------------------------------------ gin_recovery
A = {}
for r in csv.DictReader(open(os.path.join(RECR, 'rec_n30_trials.csv'))):
    A[(r['sub'], r['stem'])] = r
nr = 0
for sub in ('v2', 'v1cpu'):
    for meta in sorted(glob.glob(os.path.join(RECR, sub, 'logs', '*_meta.txt'))):
        stem = os.path.basename(meta)[:-9]
        b = meta[:-9]
        m = dict(re.findall(r'(\w+)=(\S+)', rt(meta)))
        k0, k1, l0 = rt(b + '_r0.kv'), rt(b + '_r1.kv'), rt(b + '_r0.log')
        it = m['iters']
        f, rec, tr = m['fault'], m['rec'], m['trial']
        n_rec = len(re.findall(r'^rec ev=\d+ .*outcome=recovered', k0, re.M))
        n_rf = len(re.findall(r'^rec ev=\d+ .*outcome=replay_failed', k0, re.M))
        n_dec = len(re.findall(r'^rec ev=\d+ .*outcome=declined', k0, re.M))
        ds = re.findall(r'^rec ev=\d+ .*? d=(\d) ', k0, re.M)
        fcls = re.findall(r'^fault ev=\d+ .*? class=(\S+)', k0, re.M)
        fired = len(re.findall(r'GDAKI fault fired', l0 + rt(b + '_r1.log')))
        r1_iters = last(r'iters_ok=(\d+)', k1, '')
        r1_data = last(r'iters_ok=\d+ init_outcome=\S+ data_check=(\S+)', k1, '')
        sig = re.search(r'final_signal=(\d+) expected_final=(\d+) signal_exact=(\d)', k1)
        r0_iters = last(r'iters_ok=(\d+)', k0, '')
        abort0 = re.findall(r'abort_ret=([^\n]*)', k0)
        abort1 = re.findall(r'abort_ret=([^\n]*)', k1)
        a0 = abort0[-1].strip() if abort0 else ''
        a1 = abort1[-1].strip() if abort1 else ''
        dreason = first(r'outcome=declined reason=(\S+)', k0, '')
        mfp = re.search(r'^fault ev=1 .*? fp=(\S+)', k0, re.M)
        dfp = mfp.group(1) if mfp else ''
        data_ok = (r1_data == 'ok' and r1_iters == it and r0_iters == it and sig is not None and sig.group(3) == '1'
                   and sig.group(1) == sig.group(2))
        clean = m['r0rc'] == '0' and m['r1rc'] == '0' and m['left'] == '0' and a0 == 'no error' and a1 == 'no error'
        want = {'F1': 'LOCAL_QP_ERR', 'F3': 'RETRY_EXC'}.get(f)
        if rec == '0':
            q = re.search(r'GIN/Q4: device-classified error CQE .*? class=(\S+)', l0)
            ok = m['r0rc'] == '8' and n_rec + n_rf + n_dec == 0 and q is not None and q.group(1) == want and a0 == 'no error' and m['left'] == '0'
        elif f in ('F1', 'F3') and not (tr.startswith('m')):
            ok = data_ok and clean and fired == 1 and n_rec == 1 and n_rf == 0 and n_dec == 0 and all(c == want for c in fcls) and all(d == '1' for d in ds)
        elif f in ('F1', 'F3'):
            ok = data_ok and clean and fired == 5 and n_rec == 4 and n_rf == 1 and n_dec == 0 and all(c == want for c in fcls) and all(d == '1' for d in ds)
        elif f == 'D0':
            ok = data_ok and clean and n_rec == 3 and ds.count('0') == 3 and len(ds) == 3 and n_dec == 0
        elif f == 'F2':
            ok = n_dec == 1 and dreason == 'class_REM_ACCESS' and dfp == '10/0x88' and m['r0rc'] == '9' and m['r1rc'] == '9' and a0 == 'no error' and a1 == 'no error' and m['left'] == '0'
        elif f == 'F4':
            ok = n_dec == 1 and dreason == 'retry_exc_peer_dead' and dfp == '12/0x81' and m['r0rc'] == '9' and a0 == 'no error' and m['left'] == '0'
        else:
            ok = False
        a = A.get((sub, stem))
        nr += 1
        if a is None:
            bad.append('rec %s/%s missing from analyze CSV' % (sub, stem))
            continue
        cmp('rec', sub + '/' + stem, 'ok', int(ok), a['ok'])
        cmp('rec', sub + '/' + stem, 'driver_ok', int(drv_ok(rt(b + '_drv.txt'))), int(a['driver'] == 'PMO=1,SMO=1 both'))
        gpu = sub == 'v2'
        dbl = re.findall(r'doorbell mode=(\S+)', l0)
        pt = [m.get('r0_gin_proxy_thread'), m.get('r1_gin_proxy_thread')]
        cpl = l0.count('Enabling CPU proxy mode')
        door = ('GPU' if (dbl and all(x == 'GPU' for x in dbl) and pt[0] == '0' and cpl == 0) else
                'CPU_PROXY' if (pt[0] == '1' and cpl > 0) else 'MIXED')
        cmp('rec', sub + '/' + stem, 'doorbell', door, a['doorbell'].split(' ')[0])
print('rec: %d trials checked' % nr)

# ----------------------------------------------------------------------------------------------- NVSHMEM
A = {}
for r in csv.DictReader(open(os.path.join(NVR, 'nv_n30_trials.csv'))):
    A[(r['dir'], r['tag'])] = r
nn = 0
NT = {'F1': ('LOCAL_QP_ERR', '5/0xf5'), 'F2b': ('REM_ACCESS', '10/0x88'), 'F3': ('RETRY_EXC', '12/0x81'),
      'F4': ('RETRY_EXC', '12/0x81')}
for d in ('classify', 'recover', 'multi', 'decline'):
    for meta in sorted(glob.glob(os.path.join(NVR, d, '*.meta'))):
        tag = os.path.basename(meta)[:-5]
        b = meta[:-5]
        m = dict(re.findall(r'(\w+)=(\S+)', rt(meta)))
        l0, l1 = rt(b + '.pe0.log'), rt(b + '.pe1.log')
        f = m['fault']
        s0 = re.search(r'^SUMMARY rank 0 .*$', l0, re.M)
        s1 = re.search(r'^SUMMARY rank 1 .*$', l1, re.M)
        s0 = dict(re.findall(r'(\w+)=(\S+)', s0.group(0))) if s0 else {}
        s1 = dict(re.findall(r'(\w+)=(\S+)', s1.group(0))) if s1 else {}
        rx = re.findall(r'^ITER \d+ rank 1 .*$', l1, re.M)
        rx_ok = sum(1 for x in rx if ' data_check=ok' in x)
        rx_sig = sum(1 for x in rx if ' data_check=ok' in x and re.search(r' sig=(\d+)', x) and re.search(r' sig=(\d+)', x).group(1) == (re.search(r' expect=(\d+)', x).group(1) if re.search(r' expect=(\d+)', x) else None))
        rx_bad = sum(1 for x in rx if ' data_check=mismatch' in x)
        frs = re.findall(r'^FAULTREC .*$', l0, re.M)
        fcls = [first(r' class=(\S+)', x) for x in frs]
        ffp = first(r' fp=(\S+)', frs[0]) if frs else ''
        ds = re.findall(r'^REC .*? d=(\d)', l0, re.M)
        dec = re.findall(r'^DECLINE .*?reason="([^"]*)"', l0, re.M)
        td0 = re.search(r'^TEARDOWN rank 0 .*returned=1', l0, re.M) is not None
        td1 = re.search(r'^TEARDOWN rank 1 .*returned=1', l1, re.M) is not None
        fired = len(re.findall(r'\[nvshmem-fault-inject\] (?:shot \d+|in-commit shot) fire_mono_ms=', l0 + l1)) + (1 if m.get('kill_mono1_s') else 0) \
            + (1 if re.search(r'^FAULT F2b', l0, re.M) else 0)
        left = m.get('leftover_rain') == '0' and m.get('leftover_sunny') == '0'
        cls_ok = bool(frs) and (fcls[0], ffp) == NT[f]
        if d == 'classify':
            ok = cls_ok and len(dec) >= 1 and td0 and left and (td1 or f == 'F4') and rx_bad == 0
        elif d in ('recover', 'multi'):
            nshots = 1 if d == 'recover' else 5
            full = (m['pe0_rc'] == '0' and m['pe1_rc'] == '0' and s0.get('ok_iters') == '200' and s1.get('ok_iters') == '200'
                    and rx_ok == 200 and rx_sig == 200 and rx_bad == 0 and s1.get('final_sig') == '200' and s1.get('expected_sig') == '200'
                    and not dec and left and td0 and td1)
            ok = full and fired == nshots and len(frs) == nshots and s0.get('rec_ok_ops') == str(1 if d == 'recover' else 4) \
                and all(c == NT[f][0] for c in fcls) and all(x == '1' for x in ds) and len(ds) == nshots
        else:
            want = {'F2b': 'class not recoverable', 'F4': 'RETRY_EXC with the peer dead'}[f]
            ok = cls_ok and dec[:1] == [want] and m['pe0_rc'] == '9' and td0 and left and (td1 or f == 'F4') and rx_bad == 0 and not ds
        a = A.get((d, tag))
        nn += 1
        if a is None:
            bad.append('nv %s missing from analyze CSV' % tag)
            continue
        cmp('nv', tag, 'ok', int(ok), a['ok'])
        cmp('nv', tag, 'class_ok', int(cls_ok), a['class_ok'])
        cmp('nv', tag, 'driver_ok', int(drv_ok(rt(b + '.drv'))), int(a['driver'] == 'PMO=1,SMO=1 both'))
        h = int('NIC handler will be GPU' in l0 and 'NIC handler will be GPU' in l1 and 'handler=GPU' in l0)
        cmp('nv', tag, 'gpu_handler', h, int(a['doorbell'] == 'GPU'))
        fin = first(r'^TEARDOWN rank 0 .*?finalize_ms=(\S+)', l0, '')
        cmp('nv', tag, 'finalize0_ms', fin, a['finalize0_ms'])
print('nv: %d trials checked' % nn)

print('\n'.join(bad) if bad else 'QA: no disagreement')
sys.exit(1 if bad else 0)
