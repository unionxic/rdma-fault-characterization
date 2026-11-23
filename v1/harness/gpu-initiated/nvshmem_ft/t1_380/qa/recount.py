#!/usr/bin/env python3
"""recount.py - independent recount of the t1_380 main run (results/20261008) from the raw logs.

Written for the QA step without reading score.py, SCORE.md or trials_scored.csv and without running
rows_t1.py. The field meanings follow EXPERIMENT.md section 3 ("the fields are the output of
rows_t1.py"), so the per-trial fields are re-derived here from the raw .meta, .pe0.log and .pe1.log
with a separate parser; the acceptance rules are the frozen ones of predictions.csv.

usage: python3 qa/recount.py [--md]    (from t1_380/, or any directory; paths are relative to this file)

Prints: frozen-file checks, the trial set against section 7, build groups, exclusions, every
prediction with n, hits and verdict, the latency per-run values with a leave-one-run-out check, and
the safety records of every hold. Reads only; writes nothing.
"""
import csv, glob, hashlib, os, re, statistics, subprocess, sys
from collections import Counter, OrderedDict, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)                       # .../nvshmem_ft/t1_380
REPO = os.path.abspath(os.path.join(STUDY, '../../../..'))
REL = os.path.relpath(STUDY, REPO)                  # harness/gpu-initiated/nvshmem_ft/t1_380
RES = os.path.join(STUDY, 'results', '20261008')
TAG = 'prereg/nvshmem-t1-380-v1'
HOME = '/home/unionxic'
B_P = HOME + '/gi-bundle/nvshmem_t1_380'

# build groups (section 3 table; P and the S driver from the section 12 build/deploy rows, 8-hex prefixes)
GROUPS = {
    'P': {'transport': 'd6ae3699', 'host': '825443f8', 'bin': 'e309d516'},
    'D': {'transport': 'b4b4115ed0e5', 'host': '3d63030802d5', 'bin': '278089a4eeda'},
    'V': {'transport': '6913dea69930', 'host': '54a9d23acf0e', 'bin': 'f1d4d304bd29'},
    'S': {'transport': '4aa4dda2a490', 'host': '80eea986b645', 'bin': '4dae151f'},
}
CELL_GROUP = {'d_inflight': 'D', 'lat4k_stock': 'S', 'lat256k_stock': 'S', 'lat4k_dv22off': 'V',
              'lat256k_dv22off': 'V', 'lat4k_dt1off': 'D', 'lat4k_dt1on': 'D', 'lat256k_dt1off': 'D',
              'lat256k_dt1on': 'D'}  # every other cell: P


def out(*a):
    print(*a)


# ---------------------------------------------------------------- frozen files
def git(*args):
    return subprocess.run(['git', '-C', REPO] + list(args), capture_output=True, text=True).stdout


def sections(text, nums):
    """the body of the '## <n>.' sections of a Markdown text, by number"""
    res = {}
    parts = re.split(r'(?m)^(## \d+\..*)$', text)
    for i in range(1, len(parts), 2):
        n = int(re.match(r'## (\d+)\.', parts[i]).group(1))
        if n in nums:
            res[n] = parts[i] + parts[i + 1]
    return res


def frozen_checks():
    out('## frozen files')
    pc = open(os.path.join(STUDY, 'predictions.csv'), 'rb').read()
    h = hashlib.sha256(pc).hexdigest()
    pre = open(os.path.join(STUDY, 'PREREG.txt')).read()
    out(f'predictions.csv sha256 {h[:16]}... in PREREG.txt: {h in pre}')
    for f in ('predictions.csv', 'PREREG.txt'):
        d = git('diff', TAG, '--', f'{REL}/{f}')
        out(f'git diff {TAG} -- {f}: {"empty" if not d else "%d lines" % len(d.splitlines())}')
    old = git('show', f'{TAG}:{REL}/EXPERIMENT.md')
    new = open(os.path.join(STUDY, 'EXPERIMENT.md')).read()
    so, sn = sections(old, {2, 3, 7, 8}), sections(new, {2, 3, 7, 8})
    for n in (2, 3, 7, 8):
        out(f'EXPERIMENT.md section {n}: {"unchanged" if so.get(n) == sn.get(n) and so.get(n) else "CHANGED"}'
            f' ({len(sn.get(n, "").splitlines())} lines)')
    out(f'tag commit: {git("rev-parse", TAG + "^{commit}").strip()[:8]}')
    rows = list(csv.DictReader(open(os.path.join(STUDY, 'predictions.csv'))))
    out(f'predictions.csv rows: {len(rows)} kinds {dict(Counter(r["kind"] for r in rows))}')
    # spec files = the code block of section 7
    block = re.search(r'```\n(.*?)```', sn[7], re.S).group(1)
    sec7 = [l.strip() for l in block.splitlines() if l.strip() and not l.startswith('#')]
    files = []
    for h_ in 'ABC':
        files += [l.strip() for l in open(os.path.join(STUDY, 'specs', f'hold{h_}.txt'))
                  if l.strip() and not l.startswith('#')]
    out(f'specs/hold[ABC].txt cell lines == section 7 block: {files == sec7} ({len(files)} lines)')
    return rows, sec7


# ---------------------------------------------------------------- spec
def parse_spec(sec7):
    spec = OrderedDict()
    for h_ in 'ABC':
        for l in open(os.path.join(STUDY, 'specs', f'hold{h_}.txt')):
            l = l.strip()
            if not l or l.startswith('#'):
                continue
            n, fault, mode, *kv = l.split()
            v = dict(x.split('=', 1) for x in kv)
            spec[v['TAG']] = {'n': int(n), 'fault': fault, 'mode': mode, 'vars': v, 'hold': h_}
    return spec


def queue(spec, hold):
    """the interleaved (round-robin) order of run_matrix_t1.sh with INTERLEAVE=1"""
    cells = [(t, s) for t, s in spec.items() if s['hold'] == hold]
    q = []
    for k in range(1, max(s['n'] for _, s in cells) + 1):
        for t, s in cells:
            if k <= s['n']:
                v = s['vars']
                tag = f"{s['fault']}_{s['mode']}_ft{v.get('FT', '1')}_t1{v.get('T1', '1')}_{t}_t{k}"
                q.append(tag)
    return q


# ---------------------------------------------------------------- trial parser
KV = re.compile(r'(\w+)=("[^"]*"|\S+)')


def kv(line):
    return {k: v.strip('"') for k, v in KV.findall(line)}


def parse_pe(path, pe, t):
    t[f'log{pe}'] = os.path.exists(path)
    t[f'shots{pe}'] = 0
    t[f'n_records{pe}'] = 0
    t[f'n_cqe_any{pe}'] = 0         # any line mentioning an error CQE (broader cross-check)
    t[f'declines{pe}'] = []
    t[f't1_enabled{pe}'] = 0
    t[f't1_refused{pe}'] = 0
    t[f'ft_handler{pe}'] = ''
    t[f'kernel_timeout{pe}'] = 0
    if not t[f'log{pe}']:
        return
    for line in open(path, errors='replace'):
        if line.startswith('T1APP '):
            t[f'started{pe}'] = True
        elif line.startswith('T1RESULT '):
            d = kv(line)
            if 'KERNEL_TIMEOUT_OR_ERROR' in line:
                t[f'kernel_timeout{pe}'] = 1
                t[f'kt_after_ms{pe}'] = float(d.get('after_ms', 'nan'))
                if pe == 1:
                    t['final_sig'] = d.get('final_sig')
                    t['expect'] = d.get('expect')
            elif pe == 0:
                t['records'] = d.get('records')
                t['status_bad'] = d.get('status_bad')
                t['host_err0'] = d.get('host_err', '')
            else:
                for k in ('slots', 'gpu_bad', 'host_bad', 'final_sig', 'expect', 'sig_exact'):
                    t[k] = d.get(k)
                t['host_err1'] = d.get('host_err', '')
        elif line.startswith('T1FETCH '):
            d = kv(line)
            if pe == 0:
                for k in ('fetches', 'exact', 'poison', 'stale', 'poison_before_bad'):
                    t['fetch_' + k] = d.get(k)
            else:
                t['fetch_counter1'] = d.get('counter')
        elif line.startswith('T1EXIT '):
            t[f'exit_mono{pe}'] = float(kv(line)['mono_ms'])
        elif line.startswith('T1STATUS '):
            t[f'end_status{pe}'] = kv(line).get('end_status')
        elif line.startswith('T1END '):
            t[f'finalize_ms{pe}'] = float(kv(line)['finalize_ms'])
        elif line.startswith('LAT '):
            t.setdefault('lat_p50', []).append(float(kv(line)['p50_us']))
        elif 'NVSHMEM_ARTIFACT_VERSION=' in line or 'Build Timestamp' in line:
            m = re.search(r'NVSHMEM_ARTIFACT_VERSION=(\S+)', line)
            if m:
                t[f'version{pe}'] = m.group(1)
            m = re.search(r'Build Timestamp\s+(.*\S)', line)
            if m:
                t[f'built{pe}'] = re.sub(r'\s+', ' ', m.group(1))
        else:
            if re.search(r'\[nvshmem-fault-inject\] shot \d+ fire_mono_ms=|in-commit shot.*fire_mono_ms=', line):
                t[f'shots{pe}'] += 1
            if 'device-classified error CQE' in line:
                t[f'n_records{pe}'] += 1
            if re.search(r'error CQE|CQE.*(syndrome|status)', line) and 'fault-inject' not in line:
                t[f'n_cqe_any{pe}'] += 1
            m = re.search(r'\[nvshmem-ft\] PE%d enabled:.*handler=(\S+)' % pe, line)
            if m:
                t[f'ft_handler{pe}'] = m.group(1)
            if '[nvshmem-t1]' in line:
                if 'transparent mode stays off' in line:
                    t[f't1_refused{pe}'] = 1
                elif re.search(r'PE%d [\d.]+ enabled: gates=' % pe, line):
                    t[f't1_enabled{pe}'] = 1
                m = re.search(r'PE%d ([\d.]+) ATEXIT (.*)' % pe, line)
                if m:
                    d = kv(m.group(2))
                    t[f'atexit_mono{pe}'] = float(m.group(1))
                    t[f'atexit_helper{pe}'] = d.get('helper')
                m = re.search(r'PE%d ([\d.]+) RECOVERED (\w+) (.*)' % pe, line)
                if m:
                    d = kv(m.group(3))
                    d.update({'pe': pe, 'role': m.group(2)})
                    t['rounds'].append(d)
                    if pe == 0 and m.group(2) == 'initiator' and t['first0'] is None:
                        t['first0'] = d
                m = re.search(r'PE%d ([\d.]+) DECLINE (.*)' % pe, line)
                if m:
                    d = kv(m.group(2))
                    t[f'declines{pe}'].append(d)
                    if pe == 0 and t['first0'] is None:
                        t['first0'] = d


def parse_trial(meta):
    base = meta[:-5]
    t = {'tag': os.path.basename(base), 'hold': os.path.basename(os.path.dirname(meta))[-1],
         'rounds': [], 'first0': None}
    m = {}
    for line in open(meta, errors='replace'):
        m.update(kv(line))
    t['meta'] = m
    for pe in (0, 1):
        parse_pe(f'{base}.pe{pe}.log', pe, t)
    mm = re.match(r'^(\w+?)_(loop|mt|lat)_ft(\d)_t1(\d)_(.+)_t(\d+)$', t['tag'])
    t['cell'], t['k'] = mm.group(5), int(mm.group(6))
    # build group from the .meta md5s (rain's copy)
    t['group'] = 'mismatch'
    for g, mv in GROUPS.items():
        if (m.get('md5_transport', '').startswith(mv['transport']) and m.get('md5_host', '').startswith(mv['host'])
                and m.get('md5_bin', '').startswith(mv['bin'])):
            t['group'] = g
    # fields of the rules
    t['rounds_init'] = sum(1 for r in t['rounds'] if r['role'] == 'initiator')
    f0 = t['first0'] or {}
    for k in ('fetch_exec', 'fetch_reposted'):
        t['t1_' + k + '0'] = f0.get(k, '')
    t['decline_reason0'] = t['declines0'][0].get('reason', '') if t['declines0'] else ''
    rc0, rc1 = m.get('pe0_rc'), m.get('pe1_rc')
    if m.get('mode') == 'lat':
        ok = rc0 == '0' and rc1 == '0'
    else:
        ok = (rc0 == '0' and rc1 == '0' and t.get('status_bad') == '0' and t.get('gpu_bad') == '0'
              and t.get('host_bad') == '0' and t.get('sig_exact') == '1'
              and t.get('host_err0', '').startswith('0') and t.get('host_err1', '').startswith('0')
              and not t['declines0'] and not t['declines1']
              and t.get('end_status0', '0x00000000') == '0x00000000'
              and t.get('end_status1', '0x00000000') == '0x00000000')
    declined = bool(t['declines0'] or t['declines1']) and 'records' in t and 'finalize_ms0' in t
    if m.get('fetch') == '1':
        f = lambda k, d: float(t[k]) if t.get(k) not in (None, '') else d
        ex, nf = f('fetch_exact', -1), f('fetch_fetches', -2)
        c1 = f('fetch_counter1', -1)
        fetch_ok = ex == nf and f('fetch_stale', 1) == 0 and f('fetch_poison', 1) == 0 and c1 == ex
        ok = ok and fetch_ok
        decl_ok = (f('fetch_stale', 1) == 0 and f('fetch_poison_before_bad', 1) == 0
                   and f('fetch_poison', 0) >= 1 and c1 in (ex, ex + 1))
        declined = declined and decl_ok
    t['outcome'] = 'transparent' if ok else ('declined' if declined else 'failed')
    if not t.get('started0'):
        t['outcome'] = 'void'
    return t


def num(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


# ---------------------------------------------------------------- trial set
def trial_set(spec, trials):
    out('\n## trial set (section 7)')
    by = defaultdict(list)
    for t in trials:
        by[t['cell']].append(t)
    total_ok = True
    for cell, s in spec.items():
        ts = by.get(cell, [])
        ks = sorted(t['k'] for t in ts)
        holds = {t['hold'] for t in ts}
        dup = [k for k, c in Counter(ks).items() if c > 1]
        gap = sorted(set(range(1, s['n'] + 1)) - set(ks))
        groups = Counter(t['group'] for t in ts)
        exp_g = CELL_GROUP.get(cell, 'P')
        bad = check_params(s, ts)
        ok = len(ts) == s['n'] and not dup and not gap and holds == {s['hold']} and set(groups) == {exp_g} and not bad
        total_ok &= ok
        out(f"{cell:16s} hold {''.join(sorted(holds))} n={len(ts)}/{s['n']} dup={dup or '-'} gap={gap or '-'} "
            f"groups={dict(groups)} (expect {exp_g}) params={'ok' if not bad else bad}")
    extra = set(by) - set(spec)
    out(f'cells not in section 7: {sorted(extra) or "none"}; total trials {len(trials)}; all cells as planned: {total_ok}')
    # md5 sets actually seen
    seen = Counter((t['meta'].get('md5_transport'), t['meta'].get('md5_host'), t['meta'].get('md5_bin'),
                    t['meta'].get('bundle').replace(HOME, '~'), t['meta'].get('bin'), t['group']) for t in trials)
    out('md5 triples seen (transport, host, driver, bundle, bin, group): n')
    for k, c in sorted(seen.items(), key=lambda x: x[0][5]):
        out(f'  {k}: {c}')
    ban = Counter((t['group'], t.get('version0'), t.get('built0')) for t in trials)
    out('PE0 config banner (group, NVSHMEM_ARTIFACT_VERSION, build timestamp): ' + str(dict(ban)))
    # interleaved order from hold.log
    for h in 'ABC':
        log = open(os.path.join(RES, h, 'hold.log')).read()
        ran = re.findall(r'(?m)^(\S+_t\d+) pe0_rc=(\d+) pe1_rc=(\d+)', log)
        q = queue(spec, h)
        rc_ok = all(next(t for t in trials if t['tag'] == tg)['meta'].get('pe0_rc') == a and
                    next(t for t in trials if t['tag'] == tg)['meta'].get('pe1_rc') == b for tg, a, b in ran)
        stop = 'STOP_AFTER_S reached' in log
        out(f'hold {h}: ran {len(ran)} in hold.log, order == round-robin queue: {[x[0] for x in ran] == q}, '
            f'rc in hold.log == .meta: {rc_ok}, STOP_AFTER_S hit: {stop}')


def check_params(s, ts):
    v = s['vars']
    bad = []
    exp = {'fault': s['fault'], 'mode': s['mode'], 'ft': v.get('FT', '1'), 't1': v.get('T1', '1'),
           'iters': v.get('ITERS', '160'), 'bytes': v.get('BYTES', '262144'), 'gap_us': v.get('GAP_US', '15000'),
           'fetch': v.get('FETCH', '0'), 'nofin': v.get('NOFIN', '0'), 'rc_per_pe': v.get('RC_PER_PE', '1'),
           'rc_map': v.get('RC_MAP', 'none'), 'handler': v.get('HANDLER', 'auto'), 'bin': v.get('BIN', 'nvt1_drv'),
           'reps': v.get('REPS', ''), 'ctas': v.get('CTAS', ''), 'threads': v.get('THREADS', ''),
           'burst': v.get('BURST', ''), 'kill_ms': v.get('KILL_MS', '')}
    b = v.get('BUNDLE', B_P)
    if exp['bin'] == 'nvt1v22_drv':
        b = v['BUNDLE_V22']
    if exp['bin'] == 'nvt1st_drv':
        b = B_P + '/stock380'
    exp['bundle'] = b
    lo, hi = int(v.get('FAULT_LO', 900)), int(v.get('FAULT_HI', 1900))
    for t in ts:
        m = t['meta']
        for k, e in exp.items():
            if m.get(k, '') != e:
                bad.append(f"{t['tag']}:{k}={m.get(k)}!={e}")
        if s['fault'] in ('F1', 'F3') and not lo <= int(m['fault_ms']) <= hi:
            bad.append(f"{t['tag']}:fault_ms={m['fault_ms']} not in [{lo},{hi}]")
        if m.get('leftover_rain') != '0' or m.get('leftover_sunny') != '0':
            bad.append(f"{t['tag']}:leftover {m.get('leftover_rain')}/{m.get('leftover_sunny')}")
    return bad


# ---------------------------------------------------------------- rules
def valid_fn(pid):
    def g(t, grp):
        return t['group'] == grp and t['outcome'] != 'void'
    i = lambda t, k: int(num(t.get(k), 0))
    return {
        'R1': lambda t: g(t, 'P'),
        'R2': lambda t: g(t, 'P') and t['shots0'] >= 1 and t['n_records0'] >= 1,
        'R3': lambda t: g(t, 'D') and t['shots0'] >= 1 and t['n_records0'] >= 1,
        'R4': lambda t: g(t, 'P') and t['shots1'] >= 1 and t['n_records0'] >= 1,
        'R5': lambda t: g(t, 'P') and t['shots1'] >= 1 and t['n_records0'] >= 1,
        'R6': lambda t: g(t, 'P') and t['shots0'] >= 1 and t['n_records0'] >= 1,
        'R7': lambda t: g(t, 'P') and t['shots0'] >= 1 and t['n_records0'] >= 1,
        'R8': lambda t: g(t, 'P'),
        'R9': lambda t: g(t, 'P') and t['meta'].get('kill_mono1_s', '') != '' and t['n_records0'] >= 1,
        'R10': lambda t: g(t, 'P') and t['shots0'] >= 1 and t['n_records0'] >= 1,
        'R11': lambda t: g(t, 'P') and t['shots0'] >= 1 and t['n_records0'] >= 1 and t['meta'].get('rc_per_pe') == '4',
        'C1': lambda t: g(t, 'P') and t['shots0'] >= 1 and t['n_records0'] >= 1,
        'N2': lambda t: g(t, 'P') and t['shots0'] >= 1 and t['ft_handler0'] == 'CPU-proxy',
        'N3': lambda t: g(t, 'P') and t['shots0'] >= 1 and t['ft_handler0'] == 'CPU-proxy',
    }[pid]


def eqnum(x, v):
    return num(x) is not None and num(x) == v


def pass_fn(pid):
    return {
        'R1': lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 0,
        'R2': lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 1,
        'R3': lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 1,
        'R4': lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 1,
        'R5': lambda t: (t['outcome'] == 'transparent' and t['rounds_init'] == 1 and eqnum(t['t1_fetch_exec0'], 0)
                         and num(t['t1_fetch_reposted0'], -1) >= 1),
        'R6': lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 1 and eqnum(t['t1_fetch_exec0'], 0),
        'R7': lambda t: t['outcome'] != 'failed' and (
            (t['outcome'] == 'transparent' and eqnum(t['t1_fetch_exec0'], 0)
             and num(t.get('fetch_counter1')) == num(t.get('fetch_fetches')))
            or (t['outcome'] == 'declined' and num(t['t1_fetch_exec0'], -1) >= 1
                and num(t.get('fetch_counter1')) == num(t.get('fetch_exact'), -9) + 1
                and 'executed by the responder' in t['decline_reason0'])),
        'R8': lambda t: (t['outcome'] == 'declined' and t['rounds_init'] == 0 and 'finalize_ms0' in t
                         and t['finalize_ms0'] <= 1000),
        'R9': lambda t: t['outcome'] == 'declined' and 'finalize_ms0' in t and t['finalize_ms0'] <= 1000,
        'R10': lambda t: (t['outcome'] == 'transparent' and t['rounds_init'] == 1 and 'exit_mono0' in t
                          and 'exit_mono1' in t and 'atexit_mono0' in t and 'atexit_mono1' in t
                          and t['atexit_mono0'] - t['exit_mono0'] <= 5000 and t['atexit_mono1'] - t['exit_mono1'] <= 5000
                          and t.get('atexit_helper0') != 'detached' and t.get('atexit_helper1') != 'detached'),
        'R11': lambda t: (t['outcome'] == 'transparent' and t['rounds_init'] == 1
                          and all(r.get('nqps') == '4' for r in t['rounds'] if r['role'] == 'initiator')),
        'C1': lambda t: int(num(t.get('status_bad'), 0)) >= 1 and t['rounds_init'] == 0 and t['outcome'] != 'transparent',
        'N2': lambda t: (t['t1_refused0'] == 1 and t['t1_refused1'] == 1 and t['t1_enabled0'] == 0
                         and t['t1_enabled1'] == 0 and t['rounds_init'] == 0 and t['outcome'] != 'transparent'),
        'N3': lambda t: t['n_records0'] == 0 and t['kernel_timeout0'] == 1,
    }[pid]


CELL_OF = {'R1': 'r1_none', 'R2': 'p_inflight', 'R3': 'd_inflight', 'R4': 'r4_f3', 'R5': 'r5_fetch_f3',
           'R6': 'r6_fetch_gap15', 'R7': 'r7_fetch_gap0', 'R8': 'r8_f2a', 'R9': 'r9_f4', 'R10': 'r10_atexit',
           'R11': 'r11_mqp', 'C1': 'c1_t1off', 'N2': 'n2_cpuproxy', 'N3': 'n2_cpuproxy'}
NEED = {'N2': 8, 'N3': 8}


def rng(xs, fmt='%.3f'):
    xs = [x for x in xs if x is not None]
    if not xs:
        return '-'
    return (fmt % min(xs)) + '–' + (fmt % max(xs))


def detail(pid, ts):
    """value ranges of the observables over the valid trials of the cell, plus context fields"""
    init = [float(r['total_ms']) for t in ts for r in t['rounds'] if r['role'] == 'initiator']
    ctx = (f"\n      context: rc PE0/PE1 {dict(Counter((t['meta']['pe0_rc'], t['meta']['pe1_rc']) for t in ts))}; "
           f"initiator total_ms over {len(init)} rounds {rng(init)}")
    if any(t.get('fetch_fetches') for t in ts):
        ctx += (f"; fetches/exact/poison/stale/counter1 "
                f"{dict(Counter((t.get('fetch_fetches'), t.get('fetch_exact'), t.get('fetch_poison'), t.get('fetch_stale'), t.get('fetch_counter1')) for t in ts))}")
    return detail_(pid, ts) + ctx


def detail_(pid, ts):
    if pid in ('R1', 'R2', 'R3', 'R4', 'R6', 'R11'):
        s = f"outcomes {dict(Counter(t['outcome'] for t in ts))}, initiator rounds per trial {dict(Counter(t['rounds_init'] for t in ts))}"
        if pid == 'R11':
            s += f", nqps of initiator rounds {dict(Counter(r.get('nqps') for t in ts for r in t['rounds'] if r['role'] == 'initiator'))}"
        if pid == 'R6':
            s += f", fetch_exec {dict(Counter(t['t1_fetch_exec0'] for t in ts))}"
        return s
    if pid == 'R5':
        return (f"outcomes {dict(Counter(t['outcome'] for t in ts))}, fetch_exec {dict(Counter(t['t1_fetch_exec0'] for t in ts))}, "
                f"fetch_reposted {dict(Counter(t['t1_fetch_reposted0'] for t in ts))}")
    if pid == 'R7':
        return (f"outcomes {dict(Counter(t['outcome'] for t in ts))}, fetch_exec {dict(Counter(t['t1_fetch_exec0'] for t in ts))}, "
                f"counter==fetches {sum(num(t.get('fetch_counter1')) == num(t.get('fetch_fetches')) for t in ts)}/{len(ts)}, "
                f"fetches {dict(Counter(t.get('fetch_fetches') for t in ts))}")
    if pid in ('R8', 'R9'):
        return (f"outcomes {dict(Counter(t['outcome'] for t in ts))}, rounds_init {dict(Counter(t['rounds_init'] for t in ts))}, "
                f"PE0 finalize_ms {rng([t.get('finalize_ms0') for t in ts], '%.1f')}, "
                f"PE0 decline reasons {dict(Counter(t['decline_reason0'] for t in ts))}")
    if pid == 'R10':
        d0 = [t['atexit_mono0'] - t['exit_mono0'] for t in ts if 'atexit_mono0' in t and 'exit_mono0' in t]
        d1 = [t['atexit_mono1'] - t['exit_mono1'] for t in ts if 'atexit_mono1' in t and 'exit_mono1' in t]
        return (f"outcomes {dict(Counter(t['outcome'] for t in ts))}, ATEXIT-T1EXIT PE0 {rng(d0)} ms, PE1 {rng(d1)} ms, "
                f"helper {dict(Counter((t.get('atexit_helper0'), t.get('atexit_helper1')) for t in ts))}")
    if pid == 'C1':
        return (f"status_bad {rng([num(t.get('status_bad')) for t in ts], '%d')}, rounds_init {dict(Counter(t['rounds_init'] for t in ts))}, "
                f"outcomes {dict(Counter(t['outcome'] for t in ts))}, rc {dict(Counter((t['meta']['pe0_rc'], t['meta']['pe1_rc']) for t in ts))}")
    if pid == 'N2':
        return (f"refused PE0/PE1 {dict(Counter((t['t1_refused0'], t['t1_refused1']) for t in ts))}, enabled PE0/PE1 "
                f"{dict(Counter((t['t1_enabled0'], t['t1_enabled1']) for t in ts))}, handler PE0/PE1 "
                f"{dict(Counter((t['ft_handler0'], t['ft_handler1']) for t in ts))}, rounds (init+resp) "
                f"{dict(Counter(len(t['rounds']) for t in ts))}, outcomes {dict(Counter(t['outcome'] for t in ts))}")
    if pid == 'N3':
        return (f"n_records0 {dict(Counter(t['n_records0'] for t in ts))}, any error-CQE line PE0/PE1 "
                f"{dict(Counter((t['n_cqe_any0'], t['n_cqe_any1']) for t in ts))}, kernel_timeout PE0/PE1 "
                f"{dict(Counter((t['kernel_timeout0'], t['kernel_timeout1']) for t in ts))}, PE0 timeout after "
                f"{rng([t.get('kt_after_ms0') for t in ts], '%.1f')} ms, shots0 {dict(Counter(t['shots0'] for t in ts))}")
    return ''


def score_trials(preds, trials):
    out('\n## predictions (trial cells)')
    by = defaultdict(list)
    for t in trials:
        by[t['cell']].append(t)
    verdicts = {}
    for p in preds:
        pid = p['id']
        if pid not in CELL_OF:
            continue
        ts = sorted(by[CELL_OF[pid]], key=lambda t: t['k'])
        v = [t for t in ts if valid_fn(pid)(t)]
        excl = [t['tag'] for t in ts if not valid_fn(pid)(t)]
        need = NEED.get(pid, 4)
        hits = [t for t in v if pass_fn(pid)(t)]
        miss = [t['tag'] for t in v if not pass_fn(pid)(t)]
        verdict = 'insufficient' if len(v) < need else ('pass' if len(hits) == len(v) else 'FAIL')
        verdicts[pid] = verdict
        out(f"{pid:4s} cell {CELL_OF[pid]:15s} trials {len(ts)} valid {len(v)} (need {need}) hits {len(hits)} -> {verdict}"
            f"{'; excluded ' + str(excl) if excl else ''}{'; missed ' + str(miss) if miss else ''}")
        out(f"      {detail(pid, v)}")
    # N1
    def init_ms(ts):
        return [float(r['total_ms']) for t in ts for r in t['rounds'] if r['role'] == 'initiator']
    p = [t for t in by['p_inflight'] if valid_fn('R2')(t)]
    d = [t for t in by['d_inflight'] if valid_fn('R3')(t)]
    pm, dm = init_ms(p), init_ms(d)
    mp, md = statistics.median(pm), statistics.median(dm)
    ok = len(p) >= 8 and len(d) >= 8
    verdicts['N1'] = 'insufficient' if not ok else ('pass' if abs(mp - md) <= 1.0 else 'FAIL')
    out(f"N1   valid port {len(p)} devel {len(d)} (need 8 each); initiator rounds port {len(pm)} devel {len(dm)}; "
        f"median port {mp:.3f} ms devel {md:.3f} ms, |diff| {abs(mp - md):.3f} ms -> {verdicts['N1']}")
    out(f"      port per-trial initiator total_ms (k order): {[round(x, 3) for x in pm]}, range {rng(pm)}")
    out(f"      devel per-trial initiator total_ms (k order): {[round(x, 3) for x in dm]}, range {rng(dm)}")
    pr = [float(r['total_ms']) for t in p for r in t['rounds'] if r['role'] == 'responder']
    dr = [float(r['total_ms']) for t in d for r in t['rounds'] if r['role'] == 'responder']
    out(f"      (not in the rule) responder total_ms median port {statistics.median(pr):.3f} devel {statistics.median(dr):.3f}; "
        f"means initiator port {statistics.mean(pm):.3f} devel {statistics.mean(dm):.3f}")
    # paired by trial index (interleaved): port - devel per k
    pk = {t['k']: [float(r['total_ms']) for r in t['rounds'] if r['role'] == 'initiator'] for t in p}
    dk = {t['k']: [float(r['total_ms']) for r in t['rounds'] if r['role'] == 'initiator'] for t in d}
    diffs = [round(pk[k][0] - dk[k][0], 3) for k in sorted(pk) if k in dk and len(pk[k]) == 1 and len(dk[k]) == 1]
    out(f"      (not in the rule) paired port-devel by trial index: {diffs}")
    return verdicts


# ---------------------------------------------------------------- latency
LAT_CELLS = ['lat4k_stock', 'lat4k_t1off', 'lat4k_t1on', 'lat4k_dv22off', 'lat4k_dt1off', 'lat4k_dt1on',
             'lat256k_stock', 'lat256k_t1off', 'lat256k_t1on', 'lat256k_dv22off', 'lat256k_dt1off', 'lat256k_dt1on']


def run_med(t):
    return statistics.median(t['lat_p50'])


def lat_valid(t):
    return t['group'] == CELL_GROUP.get(t['cell'], 'P') and t['outcome'] != 'void' and len(t.get('lat_p50', [])) == 5


def latency(trials):
    out('\n## latency (hold C): per-run median of the 5 rep p50 values, us (run k order)')
    by = defaultdict(list)
    for t in trials:
        by[t['cell']].append(t)
    runs = {}
    for c in LAT_CELLS:
        ts = sorted(by[c], key=lambda t: t['k'])
        v = [t for t in ts if lat_valid(t)]
        runs[c] = {t['k']: run_med(t) for t in v}
        meds = [run_med(t) for t in v]
        allp = [x for t in v for x in t['lat_p50']]
        best = min(meds)
        kbest = [t['k'] for t in v if run_med(t) == best]
        out(f"{c:16s} valid {len(v)}/{len(ts)} best {best:.3f} (run {kbest}) median-of-runs {statistics.median(meds):.3f} "
            f"runs {[round(x, 3) for x in meds]}; all rep p50 {rng(allp)}; runs with any rep p50 < 13.0: "
            f"{sum(1 for t in v if min(t['lat_p50']) < 13.0) if '4k' in c else '-'}")
    return runs


def lat_rules(runs):
    best = lambda c, ex=None: min(v for k, v in runs[c].items() if k != ex)
    pairs_n4 = [('lat4k_stock', 'lat4k_dv22off'), ('lat256k_stock', 'lat256k_dv22off')]
    pairs_n5 = [('lat4k_t1off', 'lat4k_dt1off'), ('lat4k_t1on', 'lat4k_dt1on'),
                ('lat256k_t1off', 'lat256k_dt1off'), ('lat256k_t1on', 'lat256k_dt1on')]
    bands = [('lat4k_t1on', 'lat4k_stock', 1.0, 2.6), ('lat4k_t1off', 'lat4k_stock', 0.2, 1.2),
             ('lat256k_t1on', 'lat256k_stock', 0.8, 2.4)]
    out('\n## latency rules')
    verdicts = {}
    for pid, pairs in (('N4', pairs_n4), ('N5', pairs_n5)):
        allok = all(len(runs[c]) >= 8 for pr in pairs for c in pr)
        res = []
        for a, b in pairs:
            d = best(a) - best(b)
            ok = abs(d) <= 0.5
            res.append(ok)
            flips = loo(runs, a, b, lambda x: abs(x) <= 0.5)
            out(f"{pid} {a} {best(a):.3f} - {b} {best(b):.3f} = {d:+.3f} us -> {'hold' if ok else 'MISS'}; "
                f"leave-one-run-out diffs {flips[0]}, verdict flips on {flips[1]} of {flips[2]} drops; "
                f"median-of-runs diff {statistics.median(runs[a].values()) - statistics.median(runs[b].values()):+.3f}")
        verdicts[pid] = 'insufficient' if not allok else ('pass' if all(res) else 'FAIL')
        out(f"{pid} pairs holding {sum(res)}/{len(res)} -> {verdicts[pid]}")
    allok = all(len(runs[c]) >= 4 for a, b, _, _ in bands for c in (a, b))
    res = []
    for a, b, lo, hi in bands:
        d = best(a) - best(b)
        ok = lo <= d <= hi
        res.append(ok)
        flips = loo(runs, a, b, lambda x, lo=lo, hi=hi: lo <= x <= hi)
        # how many port runs, taken alone, would sit in the band against the stock best
        alone = sum(1 for v in runs[a].values() if lo <= v - best(b) <= hi)
        out(f"R12 {a} {best(a):.3f} - {b} {best(b):.3f} = {d:+.3f} us, band [{lo}, {hi}] -> {'hold' if ok else 'MISS'}; "
            f"leave-one-run-out diffs {flips[0]}, verdict flips on {flips[1]} of {flips[2]} drops; port runs in band "
            f"against the stock best {alone}/{len(runs[a])}; median-of-runs diff "
            f"{statistics.median(runs[a].values()) - statistics.median(runs[b].values()):+.3f}")
    verdicts['R12'] = 'insufficient' if not allok else ('pass' if all(res) else 'FAIL')
    out(f"R12 bands holding {sum(res)}/{len(res)} -> {verdicts['R12']}")
    return verdicts


def loo(runs, a, b, ok):
    """drop one run of a or of b at a time: range of the rule's difference and the number of drops that flip it"""
    base = ok(min(runs[a].values()) - min(runs[b].values()))
    ds, flips = [], 0
    for cell in (a, b):
        for k in runs[cell]:
            ra = [v for kk, v in runs[a].items() if not (cell == a and kk == k)]
            rb = [v for kk, v in runs[b].items() if not (cell == b and kk == k)]
            d = min(ra) - min(rb)
            ds.append(d)
            flips += ok(d) != base
    return f'{min(ds):+.3f}..{max(ds):+.3f}', flips, len(ds)


# ---------------------------------------------------------------- safety
def safety(trials):
    out('\n## safety per hold')
    mlx = re.compile(r'mlx5', re.I)
    cmd = re.compile(r'(cmd|command)', re.I)
    bad = re.compile(r'(timeout|fail|error|leak|no done)', re.I)
    for h in 'ABC':
        d = os.path.join(RES, h)
        s = []
        for node in ('rain', 'sunny'):
            b = open(os.path.join(d, f'dmesg_{node}_before.txt'), errors='replace').read().splitlines()
            a = open(os.path.join(d, f'dmesg_{node}_after.txt'), errors='replace').read().splitlines()
            bs = set(b)
            new = [l for l in a if l not in bs]
            errs = [l for l in new if mlx.search(l) and cmd.search(l) and bad.search(l) and 'FWTracer' not in l]
            nf = open(os.path.join(d, f'dmesg_{node}_new.txt')).read().splitlines()
            s.append(f'{node}: before {len(b)} after {len(a)} lines, identical {a == b}, new {len(new)} '
                     f'(new.txt {len(nf)}), mlx5 cmd errors {len(errs)}')
        log = open(os.path.join(d, 'hold.log')).read()
        m = re.search(r'iptables_t1sock_left=(\d+) procs_left_rain=(\d+) procs_left_sunny=(\d+)', log)
        lr = open(os.path.join(d, f'hold{h}', 'leftover_rain.txt')).read().split()
        ls = open(os.path.join(d, f'hold{h}', 'leftover_sunny.txt')).read().split()
        ts = [t for t in trials if t['hold'] == h]
        lt = Counter((t['meta'].get('leftover_rain'), t['meta'].get('leftover_sunny')) for t in ts)
        cr = open(os.path.join(d, 'cluster_run.out')).read()
        lock = re.findall(r'(\d\d:\d\d:\d\d) \[(t1x-\w)\] (lock acquired|idle[^;]*;|command exited rc=\d+)', cr)
        out(f'hold {h}: ' + '; '.join(s))
        out(f'   iptables t1sock left {m.group(1)}, study processes left rain {m.group(2)} sunny {m.group(3)} (hold.log); '
            f'leftover_rain.txt {lr} leftover_sunny.txt {ls}; per-trial .meta leftover (rain, sunny) {dict(lt)}')
        out(f'   cluster_run: {[(x[0], x[1], x[2][:22]) for x in lock]}')


def main():
    preds, sec7 = frozen_checks()
    spec = parse_spec(sec7)
    trials = [parse_trial(m) for h in 'ABC' for m in sorted(glob.glob(os.path.join(RES, h, f'hold{h}', '*.meta')))]
    trial_set(spec, trials)
    out('\n## exclusions (section 8): void %d, build mismatch %d' % (
        sum(t['outcome'] == 'void' for t in trials), sum(t['group'] != CELL_GROUP.get(t['cell'], 'P') for t in trials)))
    out('outcomes by cell: ' + '; '.join(f"{c}: {dict(Counter(t['outcome'] for t in trials if t['cell'] == c))}"
                                          for c in spec))
    v = score_trials(preds, trials)
    runs = latency(trials)
    v.update(lat_rules(runs))
    if '--md' in sys.argv:  # the per-run table of qa_recount.md
        out('\n| cell | ' + ' | '.join(f'run {k}' for k in range(1, 11)) + ' | best |')
        out('|---|' + '--:|' * 11)
        for c in LAT_CELLS:
            b = min(runs[c].values())
            out(f'| `{c}` | ' + ' | '.join(('**%.3f**' if runs[c][k] == b else '%.3f') % runs[c][k]
                                            for k in range(1, 11)) + f' | {b:.3f} |')
    out('\n## verdicts')
    out(', '.join(f"{p['id']}={v.get(p['id'], '?')}" for p in preds))
    out(f"pass {sum(x == 'pass' for x in v.values())}, FAIL {sum(x == 'FAIL' for x in v.values())}, "
        f"insufficient {sum(x == 'insufficient' for x in v.values())}")
    safety(trials)
    sm = sorted(glob.glob(os.path.join(STUDY, 'results', '20261008_smoke*', '**', '*.meta'), recursive=True))
    out(f'\nsmoke (not scored): {len(sm)} .meta files under results/20261008_smoke*/')


if __name__ == '__main__':
    main()
