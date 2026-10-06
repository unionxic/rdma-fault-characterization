#!/usr/bin/env python3
"""Independent cross-check: per-trial layer labels L0-L5 from the raw campaign files.

Read-only on the repo. Writes trials.csv, partitions.csv, arrival.csv, TABLE.md next to this file.
Does not read layers.py, LAYERS.md, layers_trials.csv, SCORE*.md, score*.json or score.py.
"""
import csv, glob, os, re, collections

R = '/home/unionxic/rdma-error/harness/gpu-initiated/propagation/results/'
C = R + '20261006_campaign/'
F4R = R + '20261006_f4rerun/'
OUT = os.path.dirname(os.path.abspath(__file__))
NETF = OUT + '/net_filtered/'   # grep -v of the 1.1 GB rank-1 net logs (repeated "fatal error" lines and IT lines removed)

LAYERS = ['L0', 'L1root', 'L1read', 'L2', 'L3', 'L4async', 'L4log', 'L5']
NO = 'not observed'
SYN2ST = {0x01: 1, 0x02: 2, 0x04: 4, 0x05: 5, 0x06: 6, 0x10: 7, 0x11: 8, 0x12: 9, 0x13: 10, 0x14: 11, 0x15: 12, 0x16: 13, 0x22: 21}

# ---------------------------------------------------------------- L0: port hw_counters via evrec
SKIP_CTR = {'rx_read_requests', 'rx_write_requests', 'rx_atomic_requests'}


def evrec_label(path):
    if not os.path.exists(path):
        return NO, ''
    st, en, ev = {}, {}, 0
    for l in open(path, errors='replace'):
        if l.startswith('ctr '):
            m = re.match(r'ctr phase=(\w+) dir=(\w+) name=(\S+) value=(-?\d+)', l)
            if m and m.group(2) == 'hw_counters':
                (st if m.group(1) == 'start' else en)[m.group(3)] = int(m.group(4))
        elif l.startswith('event '):
            ev += 1
    if not en:
        return NO, ''
    d = {k: en[k] - st[k] for k in st if k in en and k not in SKIP_CTR and en[k] != st[k]}
    lab = '+'.join(sorted(d)) if d else '+0'
    if ev:
        lab += f' events={ev}'
    return lab, ';'.join(f'{k}+{v}' for k, v in sorted(d.items()))


def rd(p):
    try:
        return open(p, errors='replace').read()
    except FileNotFoundError:
        return None


def kvget(txt, key):
    if txt is None:
        return None
    m = re.findall(r'(?:^|\s)' + re.escape(key) + r'=([^\n]*?)(?=\s\w+=|$)', txt, re.M)
    return m[-1].strip() if m else None


rows = []


def add(variant, fault, trial, side, src, lab, extra=''):
    r = {'variant': variant, 'fault': fault, 'trial': trial, 'side': side, 'source': src.replace(R, 'results/')}
    for L in LAYERS:
        r[L] = lab.get(L, NO)
    r['extra'] = extra
    rows.append(r)


# ---------------------------------------------------------------- CPU harness
CPUF = {'none': 'F0', 'local_qp_err': 'F1', 'rem_access': 'F2', 'retry_server_qp_err': 'F3',
        'retry_proc_sigkill': 'F4', 'rem_inv_req': 'X_rem_inv_req', 'rnr': 'X_rnr', 'partial_write': 'X_partial_write'}
for l in open(C + 'cpu/trials.log'):
    tag = l.split()[0]
    m = re.match(r'cpu_(.+)_t(\d+)$', tag)
    f, t = m.group(1), int(m.group(2))
    out = rd(C + f'cpu/logs/{tag}.out')
    tl = re.search(r'^\[trial 0\].*$', out, re.M).group(0)
    st = re.search(r'status=.*?\((\d+)\) vendor=(0x[0-9a-f]+)', tl)
    sub = re.search(r' sub=(\S+?)\(', tl).group(1)
    cli = re.search(r'cli_async=(\S+)', tl).group(1)
    s, v = int(st.group(1)), st.group(2)
    l1 = 'success' if s == 0 else f'{s}/{v}'
    l2 = l1 if sub == '-' else f'{l1} {sub}'
    td = re.search(r'teardown \(ep_close\) returned', out)
    lab = {'L0': evrec_label(C + f'cpu/evrec/{tag}.evrec.rain')[0], 'L1root': l1, 'L1read': l1, 'L2': l2,
           'L3': 'n/a (harness is the app)', 'L4async': 'none' if cli == 'none' else cli,
           'L4log': 'n/a (no library)', 'L5': 'returned' if td else 'no teardown line'}
    add('CPU', CPUF[f], t, 'init', C + f'cpu/logs/{tag}.out', lab,
        'ctr=' + evrec_label(C + f'cpu/evrec/{tag}.evrec.rain')[1])

# ---------------------------------------------------------------- GIN (gp, gg, gq)
REMOTE = 'remote process exited or there was a network error'


def api_name(s):
    if s is None:
        return None
    if s.startswith(REMOTE):
        return 'ncclRemoteError'
    if s in ('none', 'no error'):
        return s
    return s


def gin_trial(stack, fault, mode, t, base):
    """returns (init_lab, tgt_lab, extra) from one trial's r0/r1 kv+log."""
    if stack == 'gq':
        pre = f'{base}logs/ring_c1_{fault}_{mode}_t{t}'
    else:
        b = 'proxy' if stack == 'gp' else 'gdaki'
        pre = f'{base}logs/{b}_{fault}_{mode}_t{t}'
    r0kv, r1kv, r0log, r1log = rd(pre + '_r0.kv'), rd(pre + '_r1.kv'), rd(pre + '_r0.log'), rd(pre + '_r1.log')
    tag = f'{stack}_{fault}_{mode}_t{t}'
    ev = f'{base}evrec/{tag}'
    I, T = {}, {}
    extra = []
    I['L0'], c0 = evrec_label(ev + '.evrec.rain')
    T['L0'], c1 = evrec_label(ev + '.evrec.sunny')
    extra.append('ctr0=' + c0)
    # ---- QP state (L0 side info)
    qp0 = 'ERR(query)' if re.search(r'host QUERY_QP rank=0 .*state=ERR', r0log or '') else (
        'ERR(hook moved)' if re.search(r'fault fired: moved \d+/\d+ GIN QP', r0log or '') else '-')
    qp1 = 'ERR(hook moved)' if re.search(r'fault fired: moved \d+/\d+ GIN QP', r1log or '') else (
        'ERR(async event state=6)' if re.search(r'async fatal event on QP .*state=6', r1log or '') else '-')
    extra.append(f'qp0={qp0} qp1={qp1}')
    # ---- L1 / L2 initiator
    if stack == 'gp':
        m = re.search(r'Got completion from peer .*? status=(\d+) .*?vendor err (\d+)', r0log)
        I['L1root'] = I['L1read'] = f'{m.group(1)}/0x{int(m.group(2)):02x}' if m else 'no error CQE logged'
        gfd = 'Error on GFD test' in r0log
        I['L2'] = (f'WARN {I["L1root"]} + GFD error' if gfd else 'no error') if m or gfd else 'no error'
        m1 = re.search(r'Got completion from peer .*? status=(\d+) .*?vendor err (\d+)', r1log or '')
        T['L1root'] = T['L1read'] = f'{m1.group(1)}/0x{int(m1.group(2)):02x}' if m1 else 'no error CQE logged'
        T['L2'] = 'GFD error' if 'Error on GFD test' in (r1log or '') else 'no error logged'
    elif stack == 'gg':
        I['L1root'] = I['L1read'] = I['L2'] = NO
        T['L1root'] = T['L1read'] = T['L2'] = NO
    else:  # gq
        m = re.search(r'device-classified error CQE rank=0 .*? fp=(\S+) syndrome=(\S+) .*?class=(\S+) .*?polled\[wqe=\d+ op=(\S+) syn=(\S+) ve=(\S+)\]', r0log or '')
        if m:
            st, ve = m.group(1).split('/')
            I['L1root'] = f'{st}/{ve}'
            syn = int(m.group(5), 16)
            I['L1read'] = f'{SYN2ST.get(syn, "syn" + m.group(5))}/{m.group(6)}'
            I['L2'] = m.group(3)
        else:
            I['L1root'] = I['L1read'] = 'no error CQE logged'
            I['L2'] = 'no error'
        m1 = re.search(r'device-classified error CQE rank=1 .*? fp=(\S+) .*?class=(\S+)', r1log or '')
        T['L1root'] = T['L1read'] = m1.group(1) if m1 else 'no error CQE logged'
        T['L2'] = m1.group(2) if m1 else 'no error'
    # ---- L3 initiator: device wait return
    if r0kv is None:
        I['L3'] = NO
    else:
        drc = kvget(r0kv, 'drain_device_rc')
        dev = kvget(r0kv, 'device_rc')
        if drc is not None:
            I['L3'] = {'8': 'ncclTimeout', '6': 'ncclRemoteError', '0': 'ok'}.get(drc, f'rc={drc}')
            extra.append('L3_from_F4_drain(timeout-mode put after TCP peer-gone)=1')
        elif dev is not None:
            I['L3'] = api_name(dev.split(' device_rc_it')[0].split(' timeout_ms')[0])
        elif kvget(r0kv, 'hang_it') is not None:
            I['L3'] = 'hang'
        else:
            okv = kvget(r0kv, 'init_outcome')
            ok0 = int(kvget(r0kv, 'iters_ok') or 0)
            ok1 = int(kvget(r1kv, 'iters_ok') or 0) if r1kv else 0
            ok1s = re.findall(r'okit=(\d+)', r1kv or '')
            ok1 = int(ok1s[-1]) if ok1s else ok1
            if okv == 'ok' and fault != 'none' and ok0 > ok1:
                I['L3'] = 'ok'
                extra.append(f'silent_success=1(r0 iters {ok0} > r1 iters {ok1})')
            else:
                I['L3'] = 'ok' if okv == 'ok' else okv
        if re.search(r'\[rank0\] peer gone at it', r0log or ''):
            extra.append('r0_tcp_peer_gone=1')
    he = kvget(r0kv, 'host_error')
    I['L4async'] = api_name(he.split(' host_error_ms')[0]) if he else NO
    # L4 log initiator (library WARN lines, minus injection-hook and init noise)
    w = []
    for l in (r0log or '').splitlines():
        if 'NCCL WARN' not in l or 'GIN/FAULT' in l or 'lib wrapper not initialized' in l or 'classification ON' in l:
            continue
        if 'Got completion' in l:
            m = re.search(r'status=(\d+) .*?vendor err (\d+)', l)
            w.append(f'completion {m.group(1)}/0x{int(m.group(2)):02x}')
        elif 'Error on GFD test' in l:
            w.append('GFD error')
        elif 'device-classified error CQE' in l:
            w.append('Q4 class=' + re.search(r'class=(\S+)', l).group(1))
        elif 'host QUERY_QP' in l:
            w.append('QUERY_QP ERR')
        elif 'GIN Error detected' in l:
            w.append('GIN Error detected')
        elif 'async fatal event' in l:
            w.append('async fatal event: ' + l.split(':')[-1].strip())
        else:
            w.append('other:' + l.split('NCCL WARN')[1][:40])
    I['L4log'] = ' | '.join(sorted(set(w))) if w else 'no WARN'
    td = kvget(r0kv, 'teardown')
    I['L5'] = {'clean': 'abort returned', 'hang': 'abort hang (30 s)'}.get(td, NO if td is None else td)
    # ---- target side
    if fault == 'F4':
        for L in ('L3', 'L4async', 'L4log', 'L5'):
            T[L] = 'n/a (killed)'
        for L in ('L1root', 'L1read', 'L2'):
            T[L] = 'n/a (killed)'
    else:
        if r1kv is None:
            T['L3'] = NO
        elif kvget(r1kv, 'hang_it') is not None:
            T['L3'] = 'hang (device wait never returned)'
        elif kvget(r1kv, 'device_rc') is not None:
            T['L3'] = api_name(kvget(r1kv, 'device_rc').split(' timeout_ms')[0].split(' device_rc_it')[0])
        else:
            T['L3'] = kvget(r1kv, 'init_outcome') or NO
        he1 = kvget(r1kv, 'host_error')
        T['L4async'] = api_name(he1.split(' host_error_ms')[0]) if he1 else NO
        w = []
        for l in (r1log or '').splitlines():
            if 'NCCL WARN' not in l or 'GIN/FAULT' in l or 'lib wrapper not initialized' in l or 'classification ON' in l:
                continue
            if 'async fatal event' in l:
                w.append('async fatal event: ' + l.split(':')[-1].strip())
            elif 'Got completion' in l:
                w.append('completion')
            elif 'GIN Error detected' in l:
                w.append('GIN Error detected')
            elif 'device-classified' in l:
                w.append('Q4 class')
            else:
                w.append('other:' + l.split('NCCL WARN')[1][:40])
        T['L4log'] = ' | '.join(sorted(set(w))) if w else 'no WARN'
        td1 = kvget(r1kv, 'teardown')
        T['L5'] = {'clean': 'abort returned', 'hang': 'abort hang (30 s)'}.get(td1, NO if td1 is None else td1)
    return I, T, ' '.join(extra), pre


for stack in ('gp', 'gg', 'gq'):
    V = {'gp': 'GP', 'gg': 'GG', 'gq': 'GQ'}[stack]
    for l in open(C + f'{stack}/trials.log'):
        tag = l.split()[0]
        m = re.match(rf'{stack}_(\w+?)_(timeout|blocking)_t(\d+)$', tag)
        f, mode, t = m.group(1), m.group(2), int(m.group(3))
        if f == 'F4' and stack in ('gp', 'gg'):
            continue  # DEVIATIONS item 10: use the re-run
        I, T, ex, pre = gin_trial(stack, f, mode, t, C + f'{stack}/')
        F = 'F0' if f == 'none' else f
        add(V, F, t, 'init', pre + '_r0.log', I, f'mode={mode} ' + ex)
        add(V, F, t, 'target', pre + '_r1.log', T, f'mode={mode} ' + ex)
    if stack in ('gp', 'gg'):
        for l in open(F4R + f'{stack}/trials.log'):
            tag = l.split()[0]
            m = re.match(rf'{stack}_(F4)_(timeout|blocking)_t(\d+)$', tag)
            f, mode, t = m.group(1), m.group(2), int(m.group(3))
            I, T, ex, pre = gin_trial(stack, f, mode, t, F4R + f'{stack}/')
            add(V, 'F4', t, 'init', pre + '_r0.log', I, f'mode={mode} rerun ' + ex)
            add(V, 'F4', t, 'target', pre + '_r1.log', T, f'mode={mode} rerun ' + ex)

# ---------------------------------------------------------------- NVSHMEM 3.8.0 (NC NG NX)
NVO = {'NC': ('stock', 'cpu_host_memory'), 'NG': ('stock', 'gpu'), 'NX': ('fix', 'cpu_host_memory')}
for l in open(C + 'nvo/trials.log'):
    tag = l.split()[0]
    m = re.match(r'nvo_(N[CGX])_kill(\d)_t(\d+)$', tag)
    vid, k, t = m.group(1), int(m.group(2)), int(m.group(3))
    lib, h = NVO[vid]
    p0 = C + f'nvo/runs/{lib}_{h}_kill{k}_t{t}.pe0.log'
    log0 = rd(p0)
    lat = [float(x) for x in re.findall(r'^PE 0 iter \d+: put \+ signal \+ nvshmem_quiet\(\) returned after ([0-9.]+) ms', log0, re.M)]
    if re.search(r'^PE 0 iter \d+: nvshmem_quiet\(\) has not returned after', log0, re.M):
        l3 = 'hang (quiet > 30 s)'
    elif re.search(r'^PE 0: all \d+ iterations returned', log0, re.M):
        l3 = 'returned'
    else:
        l3 = NO
    warn = [x for x in re.findall(r'NVSHMEM (?:WARN|ERROR)[^\n]*', log0) if 'NVLINK SHARP' not in x]
    if re.search(r'^PE 0: nvshmem_finalize returned', log0, re.M):
        l5 = 'finalize returned'
    elif re.search(r'^PE 0: nvshmem_finalize did not return', log0, re.M):
        l5 = 'finalize hang (30 s)'
    else:
        l5 = NO
    lab = {'L0': evrec_label(C + f'nvo/evrec/{tag}.evrec.rain')[0], 'L1root': NO, 'L1read': NO, 'L2': NO,
           'L3': l3, 'L4async': 'n/a (no async-error API)', 'L4log': 'no WARN' if not warn else 'WARN',
           'L5': l5}
    add(vid, 'F0' if k == 0 else 'F4', t, 'init', p0, lab,
        f'max_quiet_ms={max(lat) if lat else -1:.1f} ctr=' + evrec_label(C + f'nvo/evrec/{tag}.evrec.rain')[1])

# ---------------------------------------------------------------- NVSHMEM devel + hooks (ND), timeout mode = driver's own CQ poll
for l in open(C + 'nvd/trials.log'):
    tag = l.split()[0]
    m = re.match(r'nvd_(auto|cpu_host_memory)_(F1|F2b|F3)_t(\d+)$', tag)
    h, f, t = m.group(1), m.group(2), int(m.group(3))
    p0 = C + f'nvd/runs_{h}/{f}_timeout_t{t}.pe0.log'
    log0 = rd(p0)
    fl = None
    for x in re.findall(r'^ITER \d+ rank 0 [^\n]*', log0, re.M):
        if re.search(r'wait_rc=[12]', x):
            fl = x
            break
    err = re.search(r'ERRCQE which=\d+ idx=\d+ op=(\S+) syn=0x(\S+) ven=(\S+)', log0)
    l1root = f'{SYN2ST.get(int(err.group(2), 16))}/{err.group(3)}' if err else 'no error CQE in CQ scan'
    if fl:
        op = re.search(r'cqe_opcode=(\S+)', fl).group(1)
        syn = int(re.search(r'cqe_syndrome=0x(\S+)', fl).group(1), 16)
        ven = re.search(r'cqe_vendor_err=(\S+)', fl).group(1)
        l1read = f'{SYN2ST.get(syn)}/{ven}' if op in ('0xd', '0xD') else 'no new CQE (slot unchanged)'
        wrc = re.search(r'wait_rc=(\d)', fl).group(1)
        l2 = {'1': 'timeout (driver poll)', '2': 'REQ_ERR seen (driver poll)'}[wrc]
    else:
        l1read, l2 = 'no error CQE', 'ok'
    warn = [x for x in re.findall(r'NVSHMEM (?:WARN|ERROR)[^\n]*', log0) if 'NVLINK SHARP' not in x]
    l5 = 'finalize hang (15 s watchdog)' if 'WATCHDOG: kernel/quiet did not return' in log0 else 'returned'
    qp = 'ERR(hook query)' if re.search(r'post-2ERR QUERY_QP .*DEVX_state=6', log0) else '-'
    lab = {'L0': evrec_label(C + f'nvd/evrec/{tag}.evrec.rain')[0], 'L1root': l1root, 'L1read': l1read, 'L2': l2,
           'L3': 'not observed (timeout mode bypasses the library API)', 'L4async': 'n/a (no async-error API)',
           'L4log': 'no WARN' if not warn else 'WARN', 'L5': l5}
    add('ND-GPU' if h == 'auto' else 'ND-CPU', 'F2' if f == 'F2b' else f, t, 'init', p0, lab,
        f'qp0={qp} ctr=' + evrec_label(C + f'nvd/evrec/{tag}.evrec.rain')[1])

# ---------------------------------------------------------------- NVSHMEM FT v2.2 (NF)
for l in open(C + 'nvf/trials.log'):
    tag = l.split()[0]
    m = re.match(r'nvf_(none|F1|F2b|F3|F4)_t(\d+)$', tag)
    f, t = m.group(1), int(m.group(2))
    p0 = C + f'nvf/runs/{f}_timeout_ft1_rec1_prop_t{t}.pe0.log'
    log0 = rd(p0)
    fr = re.search(r'^FAULTREC [^\n]*', log0, re.M)
    fail = re.search(r'^ITER \d+ rank 0 round 0 [^\n]*rc=(-\d+)[^\n]*slot=(\w+)/0x(\w+)/(0x\w+)', log0, re.M)
    if fr:
        fr = fr.group(0)
        cls = re.search(r'class=(\S+)', fr).group(1)
        fp = re.search(r' fp=(\S+)', fr).group(1)
        live = re.search(r'liveness=(\S+)', fr).group(1)
        l1root = fp
        l1read = f'{SYN2ST.get(int(fail.group(3), 16))}/{fail.group(4)}' if fail and fail.group(2) == 'd' else 'no error slot'
        l3 = f'rc={fail.group(1) if fail else "?"} FT.query class={cls}'
    else:
        cls, live, l1root, l1read, l3 = None, None, 'no error CQE', 'no error CQE', 'rc=0'
    dc = re.search(r'\[nvshmem-ft\] PE0 device-classified error CQE [^\n]*class=(\S+)', log0)
    l2 = dc.group(1) if dc else 'no error'
    summ = re.search(r'^SUMMARY rank 0 [^\n]*rc=(\d+)[^\n]*declined=(\d)', log0, re.M)
    final = {'0': 'run ok', '9': 'declined'}.get(summ.group(1), 'rc=' + summ.group(1)) if summ else NO
    rec = 'recovered' if re.search(r'^REC it=', log0, re.M) else ''
    w = []
    if dc:
        w.append('ft class=' + dc.group(1))
    if re.search(r'PE0 host QUERY_QP [^\n]*state=6\(ERR\)', log0):
        w.append('QUERY_QP ERR')
    if 'marked failed (recovery declined' in log0:
        w.append('marked failed')
    td = re.search(r'^TEARDOWN rank 0 [^\n]*returned=(\d)', log0, re.M)
    l5 = ('finalize returned' if td.group(1) == '1' else 'finalize not returned') if td else NO
    qp = 'ERR(query)' if 'QUERY_QP ERR' in w else '-'
    lab = {'L0': evrec_label(C + f'nvf/evrec/{tag}.evrec.rain')[0], 'L1root': l1root, 'L1read': l1read, 'L2': l2,
           'L3': l3, 'L4async': 'n/a (no async-error API)', 'L4log': ' | '.join(w) if w else 'no ft line',
           'L5': l5}
    pg = re.search(r'^PEERGONE it=\d+ [^\n]*liveness=(\S+)', log0, re.M)
    add('NF', {'none': 'F0', 'F2b': 'F2'}.get(f, f), t, 'init', p0, lab,
        f'qp0={qp} liveness={live} peergone={pg.group(1) if pg else "-"} final={final} {rec} ctr='
        + evrec_label(C + f'nvf/evrec/{tag}.evrec.rain')[1])

# ---------------------------------------------------------------- NCCL 2.23.4 net_ib (stock path, Stage 2); F0 control = T0s
for l in open(C + 'net/trials.log'):
    tag = l.split()[0]
    m = re.match(r'net_(T0s|F2|F2stock)_t(\d+)$', tag)
    tid, t = m.group(1), int(m.group(2))
    p0 = NETF + f'{tid}_t{t}__{tid}_0_r0.log'
    log0 = rd(p0)
    m1 = re.search(r'incident via cqe: status=(\d+)\(\w+\) vendor_err=(\S+)', log0)
    m2 = re.search(r'Got completion from peer \S+ with status=(\d+) .*?vendor err (\d+)', log0)
    if m1:
        l1 = f'{m1.group(1)}/{m1.group(2)}'
    elif m2:
        l1 = f'{m2.group(1)}/0x{int(m2.group(2)):02x}'
    else:
        l1 = 'no CQE logged'
    if 'fault class not recoverable' in log0 and 'send comm: incident' in log0:
        l2 = 'Stage2: declined by class'
    elif 'peer sent FAIL' in log0:
        l2 = 'Stage2: peer sent FAIL'
    elif m2:
        l2 = 'stock: WARN completion error'
    else:
        l2 = 'no error'
    ae = re.search(r'\[rank0\] iter \d+ async NCCL error: ([^\n]*)', log0)
    l3 = api_name(ae.group(1)) if ae else ('ok' if re.search(r'SUMMARY rank=0 rc=0', log0) else NO)
    w = []
    for x in re.findall(r'NCCL WARN ([^\n]*)', log0):
        if 'FAULT-INJECT' in x:
            continue
        if 'Got completion' in x:
            mm = re.search(r'status=(\d+) .*?vendor err (\d+)', x)
            w.append(f'completion {mm.group(1)}/0x{int(mm.group(2)):02x}')
        elif 'incident via cqe' in x:
            w.append('FR2 incident ' + l1)
        elif 'peer sent FAIL' in x:
            w.append('FR2 peer FAIL')
        elif 'FAILED in' in x:
            w.append('FR2 FAILED')
        else:
            w.append('other')
    l5 = 'abort hang (20 s watchdog)' if 'ABORT-HANG' in log0 else (
        'no abort (destroy, not timed); rc=0' if re.search(r'SUMMARY rank=0 rc=0', log0) else NO)
    lab = {'L0': evrec_label(C + f'net/evrec/{tag}.evrec.rain')[0], 'L1root': l1, 'L1read': l1, 'L2': l2, 'L3': l3,
           'L4async': l3 if ae else 'none', 'L4log': ' | '.join(sorted(set(w))) if w else 'no WARN', 'L5': l5}
    vs = ['NET-S2', 'NET-stock'] if tid == 'T0s' else (['NET-S2'] if tid == 'F2' else ['NET-stock'])
    for v in vs:
        add(v, 'F0' if tid == 'T0s' else 'F2', t, 'init', C + f'net/runs/{tid}_t{t}/{tid}_0_r0.log', lab,
            'ctr=' + evrec_label(C + f'net/evrec/{tag}.evrec.rain')[1])

# ---------------------------------------------------------------- write per-trial CSV
with open(OUT + '/trials.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=['variant', 'fault', 'trial', 'side'] + LAYERS + ['extra', 'source'])
    w.writeheader()
    for r in rows:
        w.writerow(r)

# ---------------------------------------------------------------- partitions and arrival
ORDER = ['CPU', 'GP', 'GG', 'GQ', 'NC', 'NG', 'NX', 'ND-GPU', 'ND-CPU', 'NF', 'NET-stock', 'NET-S2']
FORD = ['F0', 'F1', 'F2', 'F3', 'F4', 'X_rem_inv_req', 'X_rnr', 'X_partial_write']
NOERR = {'+0', 'success', 'ok', 'none', 'no error', 'no error CQE', 'no error CQE logged', 'no WARN', 'no ft line',
         'returned', 'abort returned', 'finalize returned', 'rc=0', 'no error logged', 'no CQE logged',
         'no error CQE in CQ scan', 'no new CQE (slot unchanged)'}
group = collections.defaultdict(list)
for r in rows:
    group[(r['variant'], r['side'], r['fault'])].append(r)

part_rows, arr_rows = [], []
summary = {}
for v in ORDER:
    for side in ('init', 'target'):
        faults = [f for f in FORD if (v, side, f) in group]
        if not faults:
            continue
        for L in LAYERS:
            modal = {}
            for f in faults:
                c = collections.Counter(r[L] for r in group[(v, side, f)])
                n = sum(c.values())
                lab, k = c.most_common(1)[0]
                modal[f] = (lab if k / n >= 0.9 else 'SPLIT[' + '; '.join(f'{a} {b}/{n}' for a, b in c.most_common()) + ']', k, n, c)
            # partition over faults with an observable label
            cls = collections.OrderedDict()
            for f in faults:
                lab = modal[f][0]
                if lab.startswith('n/a') or lab == NO or lab.startswith('not observed'):
                    continue
                cls.setdefault(lab, []).append(f)
            obs = bool(cls)
            part = ' | '.join(','.join(fs) for fs in cls.values()) if obs else NO
            core = [f for f in faults if f in ('F0', 'F1', 'F2', 'F3', 'F4')]
            ccls = collections.OrderedDict()
            for f in core:
                lab = modal[f][0]
                if lab.startswith('n/a') or lab == NO or lab.startswith('not observed'):
                    continue
                ccls.setdefault(lab, []).append(f)
            cpart = ' | '.join(','.join(fs) for fs in ccls.values()) if ccls else NO
            summary[(v, side, L)] = (len(ccls) if ccls else None, cpart, len(cls) if obs else None, part)
            part_rows.append({'variant': v, 'side': side, 'layer': L, 'n_classes_F0F4': len(ccls) if ccls else '-',
                              'partition_F0F4': cpart, 'n_classes_all': len(cls) if obs else '-', 'partition_all': part,
                              'labels': ' || '.join(f'{f}: {modal[f][0]} ({modal[f][1]}/{modal[f][2]})' for f in faults)})
            # arrival: differs from the variant's F0 modal label, else from "no error"
            ctrl = modal.get('F0', (None,))[0]
            for f in faults:
                if f == 'F0':
                    continue
                rs = group[(v, side, f)]
                labs = [r[L] for r in rs]
                if all(x.startswith('n/a') or x == NO or x.startswith('not observed') for x in labs):
                    k = '-'
                elif ctrl and not ctrl.startswith('SPLIT') and not ctrl.startswith('n/a') and ctrl != NO:
                    k = sum(1 for x in labs if x != ctrl)
                else:
                    k = sum(1 for x in labs if x not in NOERR)
                arr_rows.append({'variant': v, 'side': side, 'fault': f, 'layer': L, 'k': k, 'n': len(rs),
                                 'reference': ctrl if ctrl and ctrl != NO else 'no error'})

with open(OUT + '/partitions.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(part_rows[0]))
    w.writeheader()
    w.writerows(part_rows)
with open(OUT + '/arrival.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(arr_rows[0]))
    w.writeheader()
    w.writerows(arr_rows)

# console view
for pr in part_rows:
    print(f"{pr['variant']:9s} {pr['side']:6s} {pr['layer']:7s} {str(pr['n_classes_F0F4']):2s} {pr['partition_F0F4']:28s} || {pr['labels'][:400]}")
print(len(rows), 'rows')

# ---------------------------------------------------------------- higher layer finer than the nearest observed lower layer
def modal_map(v, side, L, core_only=True):
    out = {}
    for f in FORD:
        if (v, side, f) not in group or (core_only and not f.startswith('F')):
            continue
        c = collections.Counter(r[L] for r in group[(v, side, f)])
        lab, k = c.most_common(1)[0]
        n = sum(c.values())
        if lab.startswith('n/a') or lab == NO or lab.startswith('not observed'):
            continue
        out[f] = lab if k / n >= 0.9 else 'SPLIT'
    return out


SEQ = ['L0', 'L1root', 'L1read', 'L2', 'L3', 'L4', 'L5']
finer = []
for v in ORDER:
    for side in ('init', 'target'):
        if not any((v, side, f) in group for f in FORD):
            continue
        mm = {L: modal_map(v, side, L, core_only=False) for L in LAYERS}
        # joint L4 = (async, log)
        j = {}
        for f in set(mm['L4async']) | set(mm['L4log']):
            j[f] = (mm['L4async'].get(f, '-'), mm['L4log'].get(f, '-'))
        mm['L4'] = j
        checks = [(SEQ[i], SEQ[i - 1]) for i in range(1, len(SEQ))] + [('L4async', 'L3'), ('L4log', 'L3'), ('L4async', 'L2'), ('L4log', 'L2')]
        for H, Lo in checks:
            # nearest observed lower layer
            lo_idx = SEQ.index(Lo) if Lo in SEQ else None
            lo = Lo
            while not mm.get(lo) and lo_idx is not None and lo_idx > 0:
                lo_idx -= 1
                lo = SEQ[lo_idx]
            if not mm.get(H) or not mm.get(lo):
                continue
            fs = sorted(set(mm[H]) & set(mm[lo]), key=FORD.index)
            pairs = [(a, b) for i, a in enumerate(fs) for b in fs[i + 1:] if mm[lo][a] == mm[lo][b] and mm[H][a] != mm[H][b]]
            if pairs:
                finer.append({'variant': v, 'side': side, 'higher': H, 'lower': lo,
                              'pairs': ' '.join(f'{a}/{b}' for a, b in pairs),
                              'higher_labels': ' || '.join(f'{f}: {mm[H][f]}' for f in fs if any(f in p for p in pairs)),
                              'lower_label': ' || '.join(f'{f}: {mm[lo][f]}' for f in fs if any(f in p for p in pairs))})
with open(OUT + '/finer.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=['variant', 'side', 'higher', 'lower', 'pairs', 'higher_labels', 'lower_label'])
    w.writeheader()
    w.writerows(finer)
print('\n==== higher finer than lower')
for x in finer:
    print(x['variant'], x['side'], x['higher'], '>', x['lower'], x['pairs'], '\n    H:', x['higher_labels'][:300], '\n    L:', x['lower_label'][:300])
