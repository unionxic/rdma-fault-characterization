#!/usr/bin/env python3
"""recount.py - independent recount of the t1_close main run from the raw logs.

usage: recount.py [<results dir>] [--csv <per-trial csv>] [--rounds <rounds csv>]

  <results dir>  default: ../results/20261007 next to this script

Reads only raw files: <tag>.meta, <tag>.pe0.log, <tag>.pe1.log, the hold logs, the dmesg snapshots and
the leftover files under <results dir>/{A,B,C,D,E}. It does not import or run rows_t1.py, rows_v2.py or
score.py and does not read SCORE.md or trials_scored.csv. Field meanings follow the frozen text
(predictions.csv, EXPERIMENT.md section 3 at tag prereg/nvshmem-t1-close-v1); they are re-implemented
here from the log formats in nvshmem_t1.cu (driver lines T1*), nvshmem_ibgda_t1close.diff (library
lines RECOVERED, DECLINE, ATEXIT, socket lines) and the v2 driver (FAULTREC, SUMMARY, TEARDOWN).
The expected cells are read from section 7 of EXPERIMENT.md and from scripts/t1/specs/lat.txt.
The --csv and --rounds outputs are for inspection; they are not results files of the study.
"""
import csv
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
FT_DIR = os.path.dirname(STUDY)

KV = re.compile(r'(\w+)=("[^"]*"|\S+)')


def kv(s):
    return {k: v.strip('"') for k, v in KV.findall(s)}


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------------------------
# raw parsing, T1 driver (nvt1_drv, nvt1v22_drv)


def parse_meta(path):
    m = {}
    for line in open(path, errors='replace'):
        m.update(kv(line))
        mm = re.search(r'\bstart=(\S+ \S+)', line)
        if mm:
            m['start_ts'] = mm.group(1)
        mm = re.search(r'\bend=(\S+ \S+)', line)
        if mm:
            m['end_ts'] = mm.group(1)
    return m


T1LINE = re.compile(r'\[nvshmem-t1\] PE(\d) ([\d.]+) (.*)$')


def parse_pe(path, pe):
    d = {'exists': os.path.exists(path), 'app': False, 'result': None, 'timeout': None, 'fetch': None,
         'status': None, 'end': None, 'exit': None, 'atexit': [], 'recovered': [], 'declines': [],
         'shots': [], 'records': [], 'sock_lost': [], 'sock_back': [], 'fill': None, 'lat': [],
         'first_round': None, 'f2bad': None, 'midline': 0, 'lines': 0}
    if not d['exists']:
        return d
    for line in open(path, errors='replace'):
        line = line.rstrip('\n')
        d['lines'] += 1
        # driver lines start the line; count any that do not (interleaved output)
        for key in ('T1RESULT rank', 'T1END rank', 'T1FETCH rank', 'T1EXIT rank', 'T1APP rank'):
            i = line.find(key)
            if i > 0:
                d['midline'] += 1
        if line.startswith('T1APP rank %d ' % pe):
            d['app'] = True
        elif line.startswith('T1RESULT rank %d ' % pe):
            if 'KERNEL_TIMEOUT_OR_ERROR' in line:
                d['timeout'] = kv(line)
            else:
                d['result'] = kv(line)
        elif line.startswith('T1FETCH rank %d ' % pe):
            d['fetch'] = kv(line)
        elif line.startswith('T1STATUS rank %d ' % pe):
            d['status'] = kv(line).get('end_status')
        elif line.startswith('T1END rank %d ' % pe):
            d['end'] = kv(line)
        elif line.startswith('T1EXIT rank %d ' % pe):
            d['exit'] = num(kv(line).get('mono_ms'))
        elif line.startswith('T1FILL '):
            d['fill'] = kv(line)
        elif line.startswith('F2BAD '):
            d['f2bad'] = kv(line)
        elif line.startswith('LAT rep '):
            d['lat'].append(num(kv(line).get('p50_us')))
        elif '[nvshmem-fault-inject]' in line and 'fire_mono_ms=' in line and (
                '[nvshmem-fault-inject] shot ' in line or 'in-commit shot' in line):
            d['shots'].append(num(re.search(r'fire_mono_ms=([\d.]+)', line).group(1)))
        elif 'device-classified error CQE' in line:
            d['records'].append(num(kv(line).get('mono_ms')))
        else:
            m = T1LINE.search(line)
            if not m:
                continue
            t, rest = num(m.group(2)), m.group(3)
            if rest.startswith('RECOVERED '):
                role = rest.split()[1]
                f = kv(rest)
                rr = {'pe': pe, 'role': role, 'mono': t, 'total_ms': num(f.get('total_ms')),
                      'handshake_ms': num(f.get('handshake_ms')), 'prepare_ms': num(f.get('prepare_ms')),
                      'commit_ms': num(f.get('commit_ms')), 'finish_ms': num(f.get('finish_ms')),
                      'quiesce_ms': num(f.get('quiesce_ms')),
                      'nqps': f.get('nqps'), 'n_qpn': len(re.findall(r' qpn=0x', rest)),
                      'fetch_cr': f.get('fetch_cr'), 'fetch_exec': f.get('fetch_exec'),
                      'fetch_reposted': f.get('fetch_reposted'), 'ops_cr': f.get('ops_cr')}
                d['recovered'].append(rr)
                if role == 'initiator' and d['first_round'] is None:
                    d['first_round'] = rr
            elif rest.startswith('DECLINE '):
                f = kv(rest)
                dd = {'mono': t, 'reason': f.get('reason', ''), 'fetch_cr': f.get('fetch_cr'),
                      'fetch_exec': f.get('fetch_exec'), 'fetch_reposted': f.get('fetch_reposted'),
                      'ops_cr': f.get('ops_cr'), 'class': f.get('class')}
                d['declines'].append(dd)
                if d['first_round'] is None:
                    d['first_round'] = dd
            elif rest.startswith('ATEXIT '):
                f = kv(rest)
                d['atexit'].append({'mono': t, 'helper': f.get('helper'), 'join_ms': num(f.get('join_ms'))})
            elif 'library socket lost' in rest:
                d['sock_lost'].append((t, rest))
            elif 'socket re-dialed' in rest or 'socket re-accepted' in rest:
                d['sock_back'].append((t, rest))
    return d


def outcome_t1(meta, p0, p1):
    """The frozen outcome definition (EXPERIMENT.md section 3 refers to rows_t1.py; its docstring and
    outcome rules are unchanged since the tag): transparent / declined / failed / void."""
    if not p0['app']:
        return 'void', {}
    rc_ok = meta.get('pe0_rc') == '0' and meta.get('pe1_rc') == '0'
    info = {}
    if meta.get('mode') == 'lat':
        ok = rc_ok
    else:
        r0, r1 = p0['result'] or {}, p1['result'] or {}
        ok = (rc_ok and r0.get('status_bad') == '0' and r1.get('gpu_bad') == '0' and r1.get('host_bad') == '0'
              and r1.get('sig_exact') == '1' and r0.get('host_err', '').startswith('0')
              and r1.get('host_err', '').startswith('0') and not p0['declines'] and not p1['declines']
              and (p0['status'] or '0x00000000') == '0x00000000' and (p1['status'] or '0x00000000') == '0x00000000')
    declined = bool(p0['declines'] or p1['declines']) and p0['result'] is not None and p0['end'] is not None
    if meta.get('fetch') == '1':
        f0, f1 = p0['fetch'] or {}, p1['fetch'] or {}
        ex, nf = num(f0.get('exact')), num(f0.get('fetches'))
        c1 = num(f1.get('counter'))
        stale, poison, pbb = num(f0.get('stale')), num(f0.get('poison')), num(f0.get('poison_before_bad'))
        fetch_ok = (ex is not None and ex == nf and stale == 0 and poison == 0 and c1 == ex)
        decl_ok = (stale == 0 and pbb == 0 and poison is not None and poison >= 1 and c1 is not None
                   and ex is not None and c1 in (ex, ex + 1))
        info.update(fetch_ok=fetch_ok, fetch_decl_ok=decl_ok)
        ok = ok and fetch_ok
        declined = declined and decl_ok
    return ('transparent' if ok else 'declined' if declined else 'failed'), info


def t1_trial(meta_path):
    base = meta_path[:-5]
    meta = parse_meta(meta_path)
    p0 = parse_pe(base + '.pe0.log', 0)
    p1 = parse_pe(base + '.pe1.log', 1)
    out, info = outcome_t1(meta, p0, p1)
    rounds = p0['recovered'] + p1['recovered']
    init = [r for r in rounds if r['role'] == 'initiator']
    fr0 = p0['first_round'] or {}
    f0, f1 = p0['fetch'] or {}, p1['fetch'] or {}
    r0, r1 = p0['result'] or {}, p1['result'] or {}
    at0 = p0['atexit'][0] if p0['atexit'] else {}
    at1 = p1['atexit'][0] if p1['atexit'] else {}
    t = {
        'kind': 't1', 'tag': os.path.basename(base), 'dir': os.path.relpath(os.path.dirname(meta_path)),
        'meta': meta, 'p0': p0, 'p1': p1, 'outcome': out, 'rounds': rounds, 'init_rounds': init,
        'rounds_init': len(init), 'rounds_resp': sum(1 for r in rounds if r['role'] == 'responder'),
        'shots0': len(p0['shots']), 'shots1': len(p1['shots']),
        'n_records0': len(p0['records']), 'first_record_mono0': p0['records'][0] if p0['records'] else None,
        'declines0': len(p0['declines']), 'declines1': len(p1['declines']),
        'decline_reason0': p0['declines'][0]['reason'] if p0['declines'] else '',
        'decline_mono0': p0['declines'][0]['mono'] if p0['declines'] else None,
        't1_fetch_cr0': fr0.get('fetch_cr', ''), 't1_fetch_exec0': fr0.get('fetch_exec', ''),
        't1_fetch_reposted0': fr0.get('fetch_reposted', ''), 'ops_cr0': fr0.get('ops_cr', ''),
        'fetch_fetches': num(f0.get('fetches')), 'fetch_exact': num(f0.get('exact')),
        'fetch_poison': num(f0.get('poison')), 'fetch_stale': num(f0.get('stale')),
        'fetch_counter1': num(f1.get('counter')),
        'status_bad': r0.get('status_bad', ''), 'sig_exact': r1.get('sig_exact', ''),
        'final_sig': r1.get('final_sig', (p1['timeout'] or {}).get('final_sig', '')),
        'finalize_ms0': num((p0['end'] or {}).get('finalize_ms')),
        'finalize_ms1': num((p1['end'] or {}).get('finalize_ms')),
        'exit_mono0': p0['exit'], 'exit_mono1': p1['exit'],
        'atexit_mono0': at0.get('mono'), 'atexit_mono1': at1.get('mono'),
        'atexit_helper0': at0.get('helper'), 'atexit_helper1': at1.get('helper'),
        'atexit_join0': at0.get('join_ms'), 'atexit_join1': at1.get('join_ms'),
        'n_atexit0': len(p0['atexit']), 'n_atexit1': len(p1['atexit']),
        'sock_lost0': len(p0['sock_lost']), 'sock_lost1': len(p1['sock_lost']),
        'sock_back0': len(p0['sock_back']), 'sock_back1': len(p1['sock_back']),
        'fill_ctas': (p0['fill'] or {}).get('ctas', ''),
        'lat_p50': [x for x in p0['lat'] + p1['lat'] if x is not None],
        'pe1_timeout': p1['timeout'] is not None, 'pe0_timeout': p0['timeout'] is not None,
        'midline': p0['midline'] + p1['midline'],
    }
    t.update(info)
    return t


# ----------------------------------------------------------------------------------------------
# raw parsing, v2 driver (nvft2_drv, FT v2.2 bundle)


def v2_trial(meta_path):
    base = meta_path[:-5]
    meta = parse_meta(meta_path)
    l0 = open(base + '.pe0.log', errors='replace').read().splitlines() if os.path.exists(base + '.pe0.log') else []
    l1 = open(base + '.pe1.log', errors='replace').read().splitlines() if os.path.exists(base + '.pe1.log') else []
    fr = next((kv(l) for l in l0 if l.startswith('FAULTREC ')), {})
    dec = next((kv(l) for l in l0 if l.startswith('DECLINE ')), {})
    s0 = next((kv(l) for l in l0 if l.startswith('SUMMARY rank 0')), {})
    s1 = next((kv(l) for l in l1 if l.startswith('SUMMARY rank 1')), {})
    td0 = next((kv(l) for l in l0 if l.startswith('TEARDOWN rank 0')), {})
    td1 = next((kv(l) for l in l1 if l.startswith('TEARDOWN rank 1')), {})
    it1 = [l for l in l1 if l.startswith('ITER ') and ' rank 1 ' in l]
    notok = [l for l in it1 if 'data_check=' in l and 'data_check=ok' not in l]
    return {
        'kind': 'v2', 'tag': os.path.basename(base), 'dir': os.path.relpath(os.path.dirname(meta_path)),
        'meta': meta, 'ft_enabled_line': any('[nvshmem-ft] PE0 enabled:' in l for l in l0),
        'fr_class': fr.get('class', ''), 'fr_fp': fr.get('fp', ''), 'n_faultrec': sum(l.startswith('FAULTREC ') for l in l0),
        'decline_reason': dec.get('reason', ''), 's0': s0, 's1': s1,
        'pe1_iter_lines': len(it1), 'pe1_notok_lines': len(notok),
        'td0_returned': td0.get('returned', '0'), 'td0_finalize_ms': num(td0.get('finalize_ms')),
        'td1_returned': td1.get('returned', '0'), 'td1_finalize_ms': num(td1.get('finalize_ms')),
        'rec_lines': sum(l.startswith('REC ') for l in l0),
        'peergone': any(l.startswith('PEERGONE ') for l in l0),
    }


# ----------------------------------------------------------------------------------------------
# expected cells (EXPERIMENT.md section 7 code block, scripts/t1/specs/lat.txt)

DEFAULTS = {'ITERS': '160', 'BYTES': '262144', 'GAP_US': '15000', 'T1SKIP': '', 'FETCH': '0', 'FILL': '0',
            'XENV': '', 'NOFIN': '0', 'RC_PER_PE': '1', 'RC_MAP': 'none', 'SOCK_DIR': 'both', 'SOCK_S': '',
            'SOCK_AT_MS': '', 'CTAS': '', 'THREADS': '', 'BURST': '', 'REPS': '', 'KILL_MS': '', 'T1': '1',
            'FT': '1', 'RING': '1', 'BIN': 'nvt1_drv'}
META_KEY = {'ITERS': 'iters', 'BYTES': 'bytes', 'GAP_US': 'gap_us', 'T1SKIP': 't1skip', 'FETCH': 'fetch',
            'FILL': 'fill', 'XENV': 'xenv', 'NOFIN': 'nofin', 'RC_PER_PE': 'rc_per_pe', 'RC_MAP': 'rc_map',
            'SOCK_DIR': 'sock_dir', 'SOCK_S': 'sock_s', 'SOCK_AT_MS': 'sock_at_ms', 'CTAS': 'ctas',
            'THREADS': 'threads', 'BURST': 'burst', 'REPS': 'reps', 'KILL_MS': 'kill_ms', 'T1': 't1', 'FT': 'ft',
            'RING': 'ring', 'BIN': 'bin', 'FAULT_MS': 'fault_ms'}


def expected_cells():
    txt = open(os.path.join(STUDY, 'EXPERIMENT.md'), encoding='utf-8').read()
    sec = txt.split('## 7.')[1].split('## 8.')[0]
    block = sec.split('```')[1]
    cells, hold = [], None
    for line in block.splitlines():
        line = line.strip()
        m = re.match(r'# hold (\w)', line)
        if m:
            hold = m.group(1)
            continue
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if parts[0].isdigit():  # "<n> <fault> <mode> VAR=..."
            n, fault, mode, knobs = int(parts[0]), parts[1], parts[2], dict(p.split('=', 1) for p in parts[3:])
            cells.append({'hold': hold, 'n': n, 'fault': fault, 'mode': mode, 'knobs': knobs, 'kind': 't1'})
        else:  # v2 runner: "<fault> <mode> <n> VAR=..."
            fault, mode, n, knobs = parts[0], parts[1], int(parts[2]), dict(p.split('=', 1) for p in parts[3:])
            cells.append({'hold': hold, 'n': n, 'fault': fault, 'mode': mode, 'knobs': knobs, 'kind': 'v2'})
    for line in open(os.path.join(FT_DIR, 'scripts/t1/specs/lat.txt')):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cells.append({'hold': 'C', 'n': int(parts[0]), 'fault': parts[1], 'mode': parts[2],
                      'knobs': dict(p.split('=', 1) for p in parts[3:]), 'kind': 't1'})
    for c in cells:
        k = c['knobs']
        if c['kind'] == 't1':
            c['prefix'] = '%s_%s_ft%s_t1%s_%s_t' % (c['fault'], c['mode'], k.get('FT', '1'), k.get('T1', '1'), k['TAG'])
        else:
            c['prefix'] = '%s_%s_ft1_rec%s_%s_t' % (c['fault'], c['mode'], k.get('RECOVER', '0'), k['TAG'])
    return cells


# ----------------------------------------------------------------------------------------------
# helpers for the rules


def ival(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def rng(xs, fmt='%.2f'):
    xs = [x for x in xs if x is not None]
    if not xs:
        return '-'
    return (fmt + '–' + fmt) % (min(xs), max(xs))


def verdict_all(valid, need, pred):
    """every valid trial satisfies pred; returns verdict, misses"""
    if len(valid) < need:
        return 'insufficient', []
    miss = [t['tag'] for t in valid if not pred(t)]
    return ('pass' if not miss else 'fail'), miss


def v_base(t):
    return t['outcome'] != 'void'


def v_f1(t):
    return v_base(t) and t['shots0'] >= 1 and t['n_records0'] >= 1


def v_f3(t):
    return v_base(t) and t['shots1'] >= 1 and t['n_records0'] >= 1


def sock_ok(t):
    return t['meta'].get('sock_port', '') not in ('', 'none')


def main():
    args = sys.argv[1:]
    csv_out = rounds_out = None
    if '--csv' in args:
        i = args.index('--csv'); csv_out = args[i + 1]; del args[i:i + 2]
    if '--rounds' in args:
        i = args.index('--rounds'); rounds_out = args[i + 1]; del args[i:i + 2]
    R = args[0] if args else os.path.join(STUDY, 'results', '20261007')
    subdirs = {'A': ['A/holdA'], 'B': ['B/holdB'], 'C': ['C/lat', 'C/v22'], 'D': ['D/holdD'], 'E': ['E/holdE']}
    trials = []
    for h, ds in subdirs.items():
        for d in ds:
            p = os.path.join(R, d)
            for f in sorted(os.listdir(p)):
                if f.endswith('.meta'):
                    t = v2_trial(os.path.join(p, f)) if d == 'C/v22' else t1_trial(os.path.join(p, f))
                    t['hold'] = h
                    trials.append(t)
    by_tag = {t['tag']: t for t in trials}
    print('# t1_close independent recount, results dir %s' % R)
    print('trials found: %d (meta files), unique tags %d' % (len(trials), len(by_tag)))

    # ---- 1. trial set against section 7
    print('\n## 1. trial set against section 7')
    cells = expected_cells()
    cell_of = {}
    tot_expected = 0
    problems = []
    for c in cells:
        tot_expected += c['n']
        got = sorted((t for t in trials if t['tag'].startswith(c['prefix']) and re.fullmatch(r'\d+', t['tag'][len(c['prefix']):])),
                     key=lambda t: int(t['tag'][len(c['prefix']):]))
        ks = [int(t['tag'][len(c['prefix']):]) for t in got]
        holds = sorted({t['hold'] for t in got})
        ok_n = ks == list(range(1, c['n'] + 1))
        knob_bad = []
        for t in got:
            m = t['meta']
            cell_of[t['tag']] = c['knobs']['TAG']
            if c['kind'] == 't1':
                for K, mk in META_KEY.items():
                    if K == 'FAULT_MS':
                        if 'FAULT_MS' in c['knobs'] and m.get('fault_ms') != c['knobs']['FAULT_MS']:
                            knob_bad.append('%s fault_ms=%s' % (t['tag'], m.get('fault_ms')))
                        continue
                    want = c['knobs'].get(K, DEFAULTS[K])
                    if m.get(mk, '') != want:
                        knob_bad.append('%s %s=%r want %r' % (t['tag'], mk, m.get(mk, ''), want))
                if 'FAULT_MS' not in c['knobs'] and c['fault'] not in ('none', 'F4', 'SOCK', 'F2A') and c['mode'] != 'lat':
                    lo, hi = int(c['knobs'].get('FAULT_LO', 900)), int(c['knobs'].get('FAULT_HI', 1900))
                    fm = ival(m.get('fault_ms'))
                    if fm is None or not lo <= fm <= hi:
                        knob_bad.append('%s fault_ms=%s outside [%d,%d]' % (t['tag'], m.get('fault_ms'), lo, hi))
                if 'BAD_AT' in c['knobs']:
                    fb = (t['p0']['f2bad'] or {}).get('bad_at')
                    if fb != c['knobs']['BAD_AT']:
                        knob_bad.append('%s F2BAD bad_at=%s' % (t['tag'], fb))
                if 'KTIMEOUT' in c['knobs'] and t['p1']['timeout']:
                    am = num(t['p1']['timeout'].get('after_ms'))
                    if am is None or abs(am - 1000 * int(c['knobs']['KTIMEOUT'])) > 1000:
                        knob_bad.append('%s PE1 after_ms=%s vs KTIMEOUT=%s' % (t['tag'], am, c['knobs']['KTIMEOUT']))
            else:
                if m.get('ring') != c['knobs'].get('RING') or m.get('recover') != c['knobs'].get('RECOVER'):
                    knob_bad.append('%s ring/recover %s/%s' % (t['tag'], m.get('ring'), m.get('recover')))
        if not ok_n or holds != [c['hold']] or knob_bad:
            problems.append((c['knobs']['TAG'], ks, holds, knob_bad))
        print('  %-16s hold %s  expected n=%-2d found %-2d  numbers %s  hold dir %s  knobs %s' % (
            c['knobs']['TAG'], c['hold'], c['n'], len(got), 'ok' if ok_n else ks, ','.join(holds),
            'ok' if not knob_bad else '%d mismatches' % len(knob_bad)))
        for kb in knob_bad[:6]:
            print('      ', kb)
    stray = [t['tag'] for t in trials if t['tag'] not in cell_of]
    print('expected total %d, found %d, trials outside the section 7 cells: %s' % (tot_expected, len(trials), stray or 'none'))

    # build and bundle (section 8)
    print('\n## build check (section 8 and section 12 md5)')
    bad_build = []
    for t in trials:
        m = t['meta']
        if t['kind'] == 'v2':
            ok = (m.get('lib_rain', '').startswith('6913dea6') and m.get('host_rain', '').startswith('54a9d23a')
                  and m.get('md5_rain', '').startswith('3d51a958') and m.get('bundle') == '/home/unionxic/gi-bundle/nvshmem_ft2'
                  and m.get('bin') == 'nvft2_drv')
        elif m.get('bin') == 'nvt1v22_drv':
            ok = (m.get('md5_bin', '').startswith('f1d4d304') and m.get('md5_transport', '').startswith('6913dea6')
                  and m.get('md5_host', '').startswith('54a9d23a')
                  and m.get('bundle') == '/home/unionxic/gi-bundle/nvshmem_t1close_b2/v22ref')
        else:
            ok = (m.get('md5_bin', '').startswith('278089a4') and m.get('md5_transport', '').startswith('b4b4115e')
                  and m.get('md5_host', '').startswith('3d630308') and m.get('bin') == 'nvt1_drv'
                  and m.get('bundle') == '/home/unionxic/gi-bundle/nvshmem_t1close_b2')
        if not ok:
            bad_build.append(t['tag'])
    combos = {}
    for t in trials:
        m = t['meta']
        key = (m.get('bundle'), m.get('bin'), m.get('md5_bin', m.get('md5_rain')), m.get('md5_transport', m.get('lib_rain')),
               m.get('md5_host', m.get('host_rain')))
        combos[key] = combos.get(key, 0) + 1
    for k, v in sorted(combos.items(), key=lambda x: -x[1]):
        print('  %3d trials: bundle=%s bin=%s bin/transport/host md5=%s/%s/%s' % (v, *k))
    print('  trials with a different build: %s' % (bad_build or 'none'))

    # outcome table and separately counted trials
    print('\n## outcomes per cell')
    for c in cells:
        tg = [t for t in trials if cell_of.get(t['tag']) == c['knobs']['TAG']]
        oc = {}
        for t in tg:
            o = t['outcome'] if t['kind'] == 't1' else 'v2'
            oc[o] = oc.get(o, 0) + 1
        print('  %-16s %s' % (c['knobs']['TAG'], ' '.join('%s=%d' % kv_ for kv_ in sorted(oc.items()))))
    midl = sum(t.get('midline', 0) for t in trials)
    print('  driver lines not at the start of a line (interleaved output): %d' % midl)

    def cell(tag):
        return [t for t in trials if cell_of.get(t['tag']) == tag]

    res = []  # (id, n_valid, n_total, hits, verdict, detail)

    def report(pid, tg, valid, verdict, miss, detail):
        hits = len(valid) - len(miss) if verdict in ('pass', 'fail') else None
        res.append((pid, len(valid), len(tg), hits, verdict, miss, detail))

    print('\n## 2. predictions')
    # N1, C4
    for pid, tag, need, lim in (('N1', 'n1_round', 8, None), ('C4', 'c4_sleep', 4, None)):
        tg = cell(tag)
        valid = [t for t in tg if v_f1(t)]
        tot = [r['total_ms'] for t in valid for r in t['init_rounds']]
        hs = [r['handshake_ms'] for t in valid for r in t['init_rounds']]
        pr = [r['prepare_ms'] for t in valid for r in t['init_rounds']]
        cm = [r['commit_ms'] for t in valid for r in t['init_rounds']]
        fi = [r['finish_ms'] for t in valid for r in t['init_rounds']]
        qu = [r['quiesce_ms'] for t in valid for r in t['init_rounds']]
        verdict, miss = verdict_all(valid, need, lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 1)
        med = st.median(tot) if tot else None
        if verdict != 'insufficient':
            if pid == 'N1':
                stat_ok = med is not None and med <= 5.5 and max(tot) <= 10.0
            else:
                stat_ok = med is not None and med >= 6.5
            if not stat_ok:
                verdict = 'fail'
        detail = ('transparent %d/%d, rounds_init=1 %d/%d; initiator rounds n=%d, total_ms median %.3f, range %s, '
                  'mean %.3f; handshake median %.3f range %s; quiesce median %.3f; prepare median %.3f; commit median %.3f; '
                  'finish median %.3f' % (
                      sum(t['outcome'] == 'transparent' for t in valid), len(valid),
                      sum(t['rounds_init'] == 1 for t in valid), len(valid), len(tot), med, rng(tot, '%.3f'),
                      st.mean(tot), st.median(hs), rng(hs, '%.3f'), st.median(qu), st.median(pr), st.median(cm), st.median(fi)))
        report(pid, tg, valid, verdict, miss, detail)
        print('  %s %s: %s' % (pid, verdict, detail))
        print('     per-trial total_ms:', ' '.join('%s:%s' % (t['tag'].rsplit('_', 1)[1], '/'.join('%.3f' % r['total_ms'] for r in t['init_rounds'])) for t in valid))

    # N2
    tg = cell('n2_fetch_f3'); valid = [t for t in tg if v_f3(t)]
    verdict, miss = verdict_all(valid, 8, lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 1
                                and ival(t['t1_fetch_exec0']) == 0 and (ival(t['t1_fetch_reposted0']) or 0) >= 1
                                and ival(t['t1_fetch_reposted0']) is not None)
    detail = ('transparent %d/%d (fetch_ok %d/%d); fetch_exec0 values %s; fetch_reposted0 values %s; fetch_cr0 %s; '
              'fetches/exact/counter1: %s; ops_cr %s' % (
                  sum(t['outcome'] == 'transparent' for t in valid), len(valid), sum(bool(t.get('fetch_ok')) for t in valid), len(valid),
                  sorted({t['t1_fetch_exec0'] for t in valid}), sorted({t['t1_fetch_reposted0'] for t in valid}),
                  sorted({t['t1_fetch_cr0'] for t in valid}),
                  sorted({'%d/%d/%d' % (t['fetch_fetches'], t['fetch_exact'], t['fetch_counter1']) for t in valid}),
                  sorted({t['ops_cr0'] for t in valid})))
    report('N2', tg, valid, verdict, miss, detail); print('  N2 %s: %s' % (verdict, detail))

    # N3
    tg = cell('n3_fetch_gap15'); valid = [t for t in tg if v_f1(t)]
    verdict, miss = verdict_all(valid, 8, lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 1 and ival(t['t1_fetch_exec0']) == 0)
    detail = ('transparent %d/%d; fetch_cr0 %s exec0 %s reposted0 %s; fetches/exact/counter1 %s; ops_cr %s' % (
        sum(t['outcome'] == 'transparent' for t in valid), len(valid), sorted({t['t1_fetch_cr0'] for t in valid}),
        sorted({t['t1_fetch_exec0'] for t in valid}), sorted({t['t1_fetch_reposted0'] for t in valid}),
        sorted({'%d/%d/%d' % (t['fetch_fetches'], t['fetch_exact'], t['fetch_counter1']) for t in valid}),
        sorted({t['ops_cr0'] for t in valid})))
    report('N3', tg, valid, verdict, miss, detail); print('  N3 %s: %s' % (verdict, detail))

    # N4
    def n4_ok(t):
        a = (t['outcome'] == 'transparent' and ival(t['t1_fetch_exec0']) == 0 and t['fetch_counter1'] == t['fetch_fetches'])
        b = (t['outcome'] == 'declined' and (ival(t['t1_fetch_exec0']) or 0) >= 1 and t['fetch_counter1'] is not None
             and t['fetch_exact'] is not None and t['fetch_counter1'] == t['fetch_exact'] + 1
             and 'executed by the responder' in t['decline_reason0'])
        return a or b
    tg = cell('n4_fetch_gap0'); valid = [t for t in tg if v_f1(t)]
    verdict, miss = verdict_all(valid, 8, n4_ok)
    if verdict == 'pass' and any(t['outcome'] == 'failed' for t in valid):
        verdict = 'fail'
    lines = []
    for t in valid:
        lines.append('t%s %s exec0=%s cr0=%s rep0=%s fetches=%s exact=%s counter1=%s ops=%s' % (
            t['tag'].rsplit('_t', 1)[1], t['outcome'], t['t1_fetch_exec0'], t['t1_fetch_cr0'], t['t1_fetch_reposted0'],
            int(t['fetch_fetches']), int(t['fetch_exact']), int(t['fetch_counter1']), t['ops_cr0']))
    detail = 'transparent %d, declined %d, failed %d of %d' % (
        sum(t['outcome'] == 'transparent' for t in valid), sum(t['outcome'] == 'declined' for t in valid),
        sum(t['outcome'] == 'failed' for t in valid), len(valid))
    report('N4', tg, valid, verdict, miss, detail); print('  N4 %s: %s' % (verdict, detail))
    for l in lines:
        print('     ', l)

    # C2
    tg = cell('c2_fetch_old'); valid = [t for t in tg if v_f3(t)]
    verdict, miss = verdict_all(valid, 4, lambda t: t['outcome'] == 'declined' and 'cannot be re-posted' in t['decline_reason0']
                                and t['fetch_counter1'] == t['fetch_exact'])
    detail = 'declined %d/%d; reasons %s; exact/counter1 %s; DECLINE fetch_cr0 %s' % (
        sum(t['outcome'] == 'declined' for t in valid), len(valid),
        sorted({re.sub(r'0x[0-9a-f]+|\d+', '#', t['decline_reason0']) for t in valid}),
        ['%d/%d' % (t['fetch_exact'], t['fetch_counter1']) for t in valid], sorted({t['t1_fetch_cr0'] for t in valid}))
    report('C2', tg, valid, verdict, miss, detail); print('  C2 %s: %s' % (verdict, detail))

    # C3
    tg = cell('c3_fetch_exec'); valid = [t for t in tg if v_f1(t)]
    if len(valid) < 4:
        verdict, miss = 'insufficient', []
    else:
        A = [t for t in valid if (ival(t['t1_fetch_exec0']) or 0) >= 1]
        B = [t for t in valid if ival(t['t1_fetch_exec0']) == 0]
        other = [t for t in valid if t not in A and t not in B]
        missA = [t['tag'] for t in A if not (t['outcome'] == 'failed' and t['fetch_counter1'] == (t['fetch_fetches'] or -9) + 1
                                             and t['sig_exact'] == '1' and t['rounds_init'] == 1)]
        missB = [t['tag'] for t in B if t['outcome'] != 'transparent']
        miss = missA + missB + [t['tag'] for t in other]
        verdict = 'pass' if not miss else 'fail'
    lines = []
    for t in valid:
        lines.append('t%s %s exec0=%s rep0=%s fetches=%s exact=%s counter1=%s sig_exact=%s rounds_init=%d rc=%s/%s' % (
            t['tag'].rsplit('_t', 1)[1], t['outcome'], t['t1_fetch_exec0'], t['t1_fetch_reposted0'], int(t['fetch_fetches']),
            int(t['fetch_exact']), int(t['fetch_counter1']), t['sig_exact'], t['rounds_init'], t['meta'].get('pe0_rc'), t['meta'].get('pe1_rc')))
    detail = 'part A (exec0>=1) n=%d, part B (exec0==0) n=%d' % (
        sum((ival(t['t1_fetch_exec0']) or 0) >= 1 for t in valid), sum(ival(t['t1_fetch_exec0']) == 0 for t in valid))
    report('C3', tg, valid, verdict, miss, detail); print('  C3 %s: %s' % (verdict, detail))
    for l in lines:
        print('     ', l)

    # N5
    tg = cell('n5_sockA'); valid = [t for t in tg if v_f1(t) and sock_ok(t)]
    verdict, miss = verdict_all(valid, 8, lambda t: t['outcome'] == 'transparent' and t['sock_lost0'] >= 1 and t['sock_back0'] >= 1
                                and t['sock_back1'] >= 1 and t['rounds_init'] == 1 and t['meta'].get('iptables_left') == '0')
    detail = ('transparent %d/%d; sock_lost0 %s sock_back0 %s sock_back1 %s; PE1 also logs a lost socket in %d/%d (%s); '
              'rounds_init %s; iptables_left %s; sock_dir %s' % (
                  sum(t['outcome'] == 'transparent' for t in valid), len(valid), sorted({t['sock_lost0'] for t in valid}),
                  sorted({t['sock_back0'] for t in valid}), sorted({t['sock_back1'] for t in valid}),
                  sum(t['sock_lost1'] >= 1 for t in valid), len(valid),
                  sorted({re.search(r'lost \((.*?)\)', x[1]).group(1) for t in valid for x in t['p1']['sock_lost']}),
                  sorted({t['rounds_init'] for t in valid}), sorted({t['meta'].get('iptables_left') for t in valid}),
                  sorted({t['meta'].get('sock_dir') for t in valid})))
    report('N5', tg, valid, verdict, miss, detail); print('  N5 %s: %s' % (verdict, detail))

    # N6
    tg = cell('n6_fill32'); valid = [t for t in tg if v_f1(t) and t['fill_ctas'] != '']
    ntr = sum(t['outcome'] == 'transparent' for t in valid)
    ncb = sum(t['outcome'] == 'declined' and 'did not complete within the bound' in t['decline_reason0'] for t in valid)
    if len(valid) < 8:
        verdict = 'insufficient'
    elif ntr >= 8:
        verdict = 'pass'
    elif ncb >= 8:
        verdict = 'fail'
    else:
        verdict = 'undecided'
    rd = [t['decline_mono0'] - t['first_record_mono0'] for t in valid if t['decline_mono0'] and t['first_record_mono0']]
    detail = ('transparent %d/%d, copy-bound declines %d/%d; record->decline ms %s; xenv %s; fill ctas %s; finalize_ms0 %s' % (
        ntr, len(valid), ncb, len(valid), rng(rd, '%.1f'), sorted({t['meta'].get('xenv') for t in valid}),
        sorted({t['fill_ctas'] for t in valid}), rng([t['finalize_ms0'] for t in valid], '%.1f')))
    res.append(('N6', len(valid), len(tg), ntr, verdict, [t['tag'] for t in valid if t['outcome'] != 'transparent'], detail))
    print('  N6 %s: %s' % (verdict, detail))

    # N7
    def n7_ok(t):
        if not (t['outcome'] == 'transparent' and t['rounds_init'] == 1):
            return False
        if t['exit_mono0'] is None or t['exit_mono1'] is None or t['atexit_mono0'] is None or t['atexit_mono1'] is None:
            return False
        return (t['atexit_mono0'] - t['exit_mono0'] <= 5000 and t['atexit_mono1'] - t['exit_mono1'] <= 5000
                and t['atexit_helper0'] == 'joined' and t['atexit_helper1'] == 'joined')
    tg = cell('n7_atexit'); valid = [t for t in tg if v_f1(t)]
    verdict, miss = verdict_all(valid, 8, n7_ok)
    dj = [x for t in valid for x in ((t['atexit_mono0'] - t['exit_mono0']) if t['atexit_mono0'] and t['exit_mono0'] else None,
                                       (t['atexit_mono1'] - t['exit_mono1']) if t['atexit_mono1'] and t['exit_mono1'] else None)]
    jm = [x for t in valid for x in (t['atexit_join0'], t['atexit_join1'])]
    detail = ('transparent %d/%d, rc %s; ATEXIT-T1EXIT ms over both PEs (n=%d) %s; join_ms %s; helper values %s; '
              'ATEXIT lines per PE %s; T1END lines %d' % (
                  sum(t['outcome'] == 'transparent' for t in valid), len(valid),
                  sorted({'%s/%s' % (t['meta'].get('pe0_rc'), t['meta'].get('pe1_rc')) for t in valid}),
                  len([x for x in dj if x is not None]), rng(dj, '%.3f'), rng(jm, '%.1f'),
                  sorted({(t['atexit_helper0'], t['atexit_helper1']) for t in valid}),
                  sorted({(t['n_atexit0'], t['n_atexit1']) for t in valid}),
                  sum((t['p0']['end'] is not None) + (t['p1']['end'] is not None) for t in valid)))
    report('N7', tg, valid, verdict, miss, detail); print('  N7 %s: %s' % (verdict, detail))

    # N8
    tg = cell('n8_mqp'); valid = [t for t in tg if v_f1(t) and t['meta'].get('rc_per_pe') == '4']
    verdict, miss = verdict_all(valid, 8, lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 1
                                and all(r['nqps'] == '4' for r in t['init_rounds']))
    tot = [r['total_ms'] for t in valid for r in t['init_rounds']]
    detail = ('transparent %d/%d; rounds_init %s; nqps per initiator round %s; qpn fields per round %s; responder nqps %s; '
              'rc_map %s; round total_ms median %.3f range %s (n=%d rounds)' % (
                  sum(t['outcome'] == 'transparent' for t in valid), len(valid), sorted({t['rounds_init'] for t in valid}),
                  sorted({r['nqps'] for t in valid for r in t['init_rounds']}), sorted({r['n_qpn'] for t in valid for r in t['init_rounds']}),
                  sorted({r['nqps'] for t in valid for r in t['rounds'] if r['role'] == 'responder'}),
                  sorted({t['meta'].get('rc_map') for t in valid}), st.median(tot), rng(tot, '%.3f'), len(tot)))
    report('N8', tg, valid, verdict, miss, detail); print('  N8 %s: %s' % (verdict, detail))

    # R1, R3-R8
    simple = [('R1', 'r1_none', v_base, lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 0),
              ('R3', 'r3_inflight', v_f1, lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 1),
              ('R4', 'r4_f3', v_f3, lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 1),
              ('R5', 'r5_x5', lambda t: v_base(t) and t['shots0'] == 5 and t['n_records0'] >= 1,
               lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 5),
              ('R6', 'r6_mt', v_f1, lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 1),
              ('R7', 'r7_f2a', v_base, lambda t: t['outcome'] == 'declined' and t['rounds_init'] == 0
               and t['finalize_ms0'] is not None and t['finalize_ms0'] <= 1000),
              ('R8', 'r8_f4', lambda t: v_base(t) and t['meta'].get('kill_mono1_s', '') != '' and t['n_records0'] >= 1,
               lambda t: t['outcome'] == 'declined' and t['finalize_ms0'] is not None and t['finalize_ms0'] <= 1000)]
    for pid, tag, vf, pf in simple:
        tg = cell(tag); valid = [t for t in tg if vf(t)]
        verdict, miss = verdict_all(valid, 4, pf)
        tot = [r['total_ms'] for t in valid for r in t['init_rounds']]
        detail = 'outcomes %s; rounds_init %s; shots0 %s; initiator round total_ms median %s range %s (n=%d); finalize_ms0 %s; reasons %s' % (
            sorted({t['outcome'] for t in valid}), sorted({t['rounds_init'] for t in valid}), sorted({t['shots0'] for t in valid}),
            '%.3f' % st.median(tot) if tot else '-', rng(tot, '%.3f'), len(tot), rng([t['finalize_ms0'] for t in valid], '%.1f'),
            sorted({re.sub(r'0x[0-9a-f]+|\d+', '#', t['decline_reason0']) for t in valid if t['decline_reason0']}))
        report(pid, tg, valid, verdict, miss, detail); print('  %s %s: %s' % (pid, verdict, detail))

    # R9, R10
    tg = cell('r9_sock'); valid = [t for t in tg if v_base(t) and sock_ok(t)]
    verdict, miss = verdict_all(valid, 4, lambda t: t['outcome'] == 'transparent' and t['rounds_init'] == 0 and t['sock_lost0'] >= 1
                                and t['sock_back0'] >= 1 and t['sock_back1'] >= 1 and t['meta'].get('iptables_left') == '0')
    detail = 'transparent %d/%d; sock_lost0 %s back0 %s back1 %s lost1 %s; iptables_left %s' % (
        sum(t['outcome'] == 'transparent' for t in valid), len(valid), sorted({t['sock_lost0'] for t in valid}),
        sorted({t['sock_back0'] for t in valid}), sorted({t['sock_back1'] for t in valid}), sorted({t['sock_lost1'] for t in valid}),
        sorted({t['meta'].get('iptables_left') for t in valid}))
    report('R9', tg, valid, verdict, miss, detail); print('  R9 %s: %s' % (verdict, detail))
    tg = cell('r10_sock1'); valid = [t for t in tg if v_f1(t) and sock_ok(t)]
    verdict, miss = verdict_all(valid, 4, lambda t: t['outcome'] == 'transparent' and t['sock_lost0'] >= 1 and t['rounds_init'] == 1
                                and t['meta'].get('iptables_left') == '0')
    detail = 'transparent %d/%d; sock_lost0 %s back0 %s back1 %s; rounds_init %s; iptables_left %s' % (
        sum(t['outcome'] == 'transparent' for t in valid), len(valid), sorted({t['sock_lost0'] for t in valid}),
        sorted({t['sock_back0'] for t in valid}), sorted({t['sock_back1'] for t in valid}), sorted({t['rounds_init'] for t in valid}),
        sorted({t['meta'].get('iptables_left') for t in valid}))
    report('R10', tg, valid, verdict, miss, detail); print('  R10 %s: %s' % (verdict, detail))

    # R11
    tg = cell('r11_fill'); valid = [t for t in tg if v_f1(t) and t['fill_ctas'] != '']
    verdict, miss = verdict_all(valid, 4, lambda t: t['outcome'] == 'declined' and 'did not complete within the bound' in t['decline_reason0']
                                and t['decline_mono0'] is not None and t['first_record_mono0'] is not None
                                and t['decline_mono0'] - t['first_record_mono0'] <= 3000
                                and t['finalize_ms0'] is not None and t['finalize_ms0'] <= 1000)
    rd = [t['decline_mono0'] - t['first_record_mono0'] for t in valid if t['decline_mono0'] and t['first_record_mono0']]
    detail = 'declined %d/%d; record->decline ms %s; finalize_ms0 %s; fill ctas %s' % (
        sum(t['outcome'] == 'declined' for t in valid), len(valid), rng(rd, '%.1f'), rng([t['finalize_ms0'] for t in valid], '%.1f'),
        sorted({t['fill_ctas'] for t in valid}))
    report('R11', tg, valid, verdict, miss, detail); print('  R11 %s: %s' % (verdict, detail))

    # R12
    print('  R12 latency cells:')
    best, lat_ok = {}, True
    alt_minmin, alt_medmed = {}, {}
    for tag in ('lat4k_v22off', 'lat4k_t1off', 'lat4k_ring', 'lat4k_t1on', 'lat256k_v22off', 'lat256k_t1off', 'lat256k_ring', 'lat256k_t1on'):
        tg = cell(tag)
        valid = [t for t in tg if t['outcome'] != 'void' and len(t['lat_p50']) == 5]
        meds = [st.median(t['lat_p50']) for t in valid]
        if len(valid) < 4:
            lat_ok = False
        best[tag] = min(meds) if meds else None
        alt_minmin[tag] = min(min(t['lat_p50']) for t in valid) if valid else None
        alt_medmed[tag] = st.median(meds) if meds else None
        print('     %-15s valid %d/%d outcomes %s; per-run median p50 (us) %s; best %.3f' % (
            tag, len(valid), len(tg), sorted({t['outcome'] for t in tg}), ' '.join('%.3f' % x for x in meds), best[tag]))
    d1 = best['lat4k_t1on'] - best['lat4k_v22off']
    d2 = best['lat4k_t1off'] - best['lat4k_v22off']
    d3 = best['lat256k_t1on'] - best['lat256k_v22off']
    ok12 = lat_ok and 1.0 <= d1 <= 2.6 and 0.2 <= d2 <= 1.2 and 0.8 <= d3 <= 2.4
    detail = ('best-run p50 differences (us): 4 KiB on-v22off %.3f [1.0, 2.6]; 4 KiB off-v22off %.3f [0.2, 1.2]; 256 KiB on-v22off %.3f [0.8, 2.4]; '
              'ring-v22off 4 KiB %.3f, 256 KiB %.3f (not scored); v22off best 4 KiB %.3f, 256 KiB %.3f' % (
                  d1, d2, d3, best['lat4k_ring'] - best['lat4k_v22off'], best['lat256k_ring'] - best['lat256k_v22off'],
                  best['lat4k_v22off'], best['lat256k_v22off']))
    alt = ('sensitivity, not the frozen statistic: min-of-all-p50 differences %.3f / %.3f / %.3f; median-of-run-medians differences %.3f / %.3f / %.3f' % (
        alt_minmin['lat4k_t1on'] - alt_minmin['lat4k_v22off'], alt_minmin['lat4k_t1off'] - alt_minmin['lat4k_v22off'],
        alt_minmin['lat256k_t1on'] - alt_minmin['lat256k_v22off'],
        alt_medmed['lat4k_t1on'] - alt_medmed['lat4k_v22off'], alt_medmed['lat4k_t1off'] - alt_medmed['lat4k_v22off'],
        alt_medmed['lat256k_t1on'] - alt_medmed['lat256k_v22off']))
    nvalid = sum(1 for t in trials if t['tag'].startswith('none_lat') and t['outcome'] != 'void' and len(t['lat_p50']) == 5)
    res.append(('R12', nvalid, 40, None, 'pass' if ok12 else 'fail', [], detail + '; ' + alt))
    print('  R12 %s: %s' % ('pass' if ok12 else 'fail', detail))
    print('     ', alt)

    # R13, R14
    def v2_valid(t):
        m = t['meta']
        return t['ft_enabled_line'] and m.get('lib_rain', '').startswith('6913dea6') and m.get('host_rain', '').startswith('54a9d23a')
    tg = cell('r13_v22f3'); valid = [t for t in tg if v2_valid(t)]
    verdict, miss = verdict_all(valid, 4, lambda t: t['meta'].get('pe0_rc') == '0' and t['meta'].get('pe1_rc') == '0'
                                and t['fr_class'] == 'RETRY_EXC' and t['fr_fp'] == '12/0x81' and (ival(t['s0'].get('rec_rounds')) or 0) >= 1
                                and t['s0'].get('ok_iters') == '200' and t['s1'].get('ok_iters') == '200'
                                and t['s1'].get('final_sig') == t['s1'].get('expected_sig') and t['pe1_notok_lines'] == 0
                                and t['td0_returned'] == '1')
    detail = ('rc %s; fault class/fp %s; rec_rounds %s; ok_iters PE0/PE1 %s; PE1 final/expected sig %s; PE1 ITER lines %s, not-ok %s; '
              'teardown returned %s; finalize_ms PE0 %s' % (
                  sorted({'%s/%s' % (t['meta'].get('pe0_rc'), t['meta'].get('pe1_rc')) for t in valid}),
                  sorted({'%s %s' % (t['fr_class'], t['fr_fp']) for t in valid}), sorted({t['s0'].get('rec_rounds') for t in valid}),
                  sorted({'%s/%s' % (t['s0'].get('ok_iters'), t['s1'].get('ok_iters')) for t in valid}),
                  sorted({'%s/%s' % (t['s1'].get('final_sig'), t['s1'].get('expected_sig')) for t in valid}),
                  sorted({t['pe1_iter_lines'] for t in valid}), sorted({t['pe1_notok_lines'] for t in valid}),
                  sorted({t['td0_returned'] for t in valid}), rng([t['td0_finalize_ms'] for t in valid], '%.1f')))
    report('R13', tg, valid, verdict, miss, detail); print('  R13 %s: %s' % (verdict, detail))
    tg = cell('r14_v22f4'); valid = [t for t in tg if v2_valid(t)]
    verdict, miss = verdict_all(valid, 4, lambda t: t['fr_class'] == 'RETRY_EXC' and t['s0'].get('declined') == '1'
                                and 'peer dead' in t['decline_reason'] and t['td0_returned'] == '1'
                                and t['td0_finalize_ms'] is not None and t['td0_finalize_ms'] <= 1000)
    detail = 'rc %s; fault class %s; declined %s; reasons %s; teardown returned %s; finalize_ms PE0 %s; ok_iters before the kill %s' % (
        sorted({'%s/%s' % (t['meta'].get('pe0_rc'), t['meta'].get('pe1_rc')) for t in valid}), sorted({t['fr_class'] for t in valid}),
        sorted({t['s0'].get('declined') for t in valid}), sorted({t['decline_reason'] for t in valid}),
        sorted({t['td0_returned'] for t in valid}), rng([t['td0_finalize_ms'] for t in valid], '%.1f'),
        sorted({t['s0'].get('ok_iters') for t in valid}))
    report('R14', tg, valid, verdict, miss, detail); print('  R14 %s: %s' % (verdict, detail))

    # C1
    tg = cell('c1_t1off'); valid = [t for t in tg if v_f1(t)]
    verdict, miss = verdict_all(valid, 4, lambda t: (ival(t['status_bad']) or 0) >= 1 and t['rounds_init'] == 0
                                and t['outcome'] != 'transparent')
    detail = 'status_bad %s; rounds_init %s; outcomes %s; rc %s; PE0 T1END lines %d; per-trial leftover_rain %s' % (
        rng([ival(t['status_bad']) for t in valid], '%d'), sorted({t['rounds_init'] for t in valid}), sorted({t['outcome'] for t in valid}),
        sorted({'%s/%s' % (t['meta'].get('pe0_rc'), t['meta'].get('pe1_rc')) for t in valid}),
        sum(t['p0']['end'] is not None for t in valid), [t['meta'].get('leftover_rain') for t in valid])
    report('C1', tg, valid, verdict, miss, detail); print('  C1 %s: %s' % (verdict, detail))

    print('\n## summary table')
    order = ['N1', 'C4', 'N2', 'N3', 'N4', 'C2', 'C3', 'N5', 'N6', 'N7', 'N8', 'R1', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9',
             'R10', 'R11', 'R12', 'R13', 'R14', 'C1']
    rd_ = {r[0]: r for r in res}
    for pid in order:
        r = rd_[pid]
        print('  %-4s valid %3d of %3d  hits %-4s verdict %-12s misses %s' % (pid, r[1], r[2], r[3] if r[3] is not None else '-', r[4], r[5] or '-'))
    print('  pass %d, fail %d, other %d' % (sum(rd_[p][4] == 'pass' for p in order), sum(rd_[p][4] == 'fail' for p in order),
                                           sum(rd_[p][4] not in ('pass', 'fail') for p in order)))

    # ---- 3. safety records
    print('\n## 3. safety records')
    pat, cmd, bad = re.compile('mlx5', re.I), re.compile('(cmd|command)', re.I), re.compile('(timeout|fail|error|leak|no done)', re.I)
    for h in 'ABCDE':
        hd = os.path.join(R, h)
        out = []
        for node in ('rain', 'sunny'):
            b = open(os.path.join(hd, 'dmesg_%s_before.txt' % node), errors='replace').read().splitlines()
            a = open(os.path.join(hd, 'dmesg_%s_after.txt' % node), errors='replace').read().splitlines()
            bs = set(b)
            new = [l for l in a if l not in bs]
            gone = len([l for l in b if l not in set(a)])
            errs = [l for l in new if pat.search(l) and cmd.search(l) and bad.search(l) and 'FWTracer' not in l]
            newf = os.path.getsize(os.path.join(hd, 'dmesg_%s_new.txt' % node))
            looks = bool(b) and b[0].startswith('[')
            out.append('%s: before %d lines, after %d, new %d, dropped %d, mlx5 cmd errors %d, new-file %d bytes, dmesg-like %s' % (
                node, len(b), len(a), len(new), gone, len(errs), newf, looks))
        hl = open(os.path.join(hd, 'hold.log'), errors='replace').read()
        ipt = re.findall(r'iptables_t1sock_left=(\S+)', hl)
        lo = []
        for sub in subdirs[h]:
            for f in ('leftover_rain.txt', 'leftover_sunny.txt'):
                p = os.path.join(R, sub, f)
                if os.path.exists(p):
                    lo.append('%s/%s=%s' % (sub, f, ','.join(open(p).read().split())))
                else:
                    lo.append('%s/%s missing' % (sub, f))
        killed = len(re.findall(r'Killed', hl))
        print('  hold %s: %s | %s | iptables_t1sock_left %s | %s | "Killed" lines in hold.log %d' % (h, out[0], out[1], ipt, '; '.join(lo), killed))
    lo_t = [(t['tag'], t['meta'].get('leftover_rain'), t['meta'].get('leftover_sunny')) for t in trials
            if t['meta'].get('leftover_rain') != '0' or t['meta'].get('leftover_sunny') != '0']
    print('  per-trial leftover counts not 0 (meta): %s' % (lo_t or 'none'))
    ipt_t = [(t['tag'], t['meta'].get('iptables_left')) for t in trials if 'sock_port' in t['meta'] or 'iptables_left' in t['meta']]
    print('  per-trial iptables_left (socket trials): %s' % sorted({x[1] for x in ipt_t}), 'n=%d' % len(ipt_t))
    starts = sorted((t['meta'].get('start_ts', ''), t['hold']) for t in trials)
    for h in 'ABCDE':
        s = [x[0] for x in starts if x[1] == h]
        print('  hold %s trial start times %s to %s' % (h, min(s), max(s)))

    if csv_out:
        keys = ['hold', 'tag', 'outcome', 'rounds_init', 'rounds_resp', 'shots0', 'shots1', 'n_records0', 'status_bad', 'sig_exact',
                't1_fetch_cr0', 't1_fetch_exec0', 't1_fetch_reposted0', 'fetch_fetches', 'fetch_exact', 'fetch_counter1',
                'decline_reason0', 'finalize_ms0', 'exit_mono0', 'atexit_mono0', 'exit_mono1', 'atexit_mono1', 'sock_lost0',
                'sock_back0', 'sock_back1', 'sock_lost1', 'fill_ctas']
        with open(csv_out, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(keys + ['pe0_rc', 'pe1_rc', 'md5_transport'])
            for t in trials:
                if t['kind'] != 't1':
                    continue
                w.writerow([t.get(k, '') for k in keys] + [t['meta'].get('pe0_rc'), t['meta'].get('pe1_rc'), t['meta'].get('md5_transport')])
    if rounds_out:
        with open(rounds_out, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['tag', 'pe', 'role', 'total_ms', 'handshake_ms', 'nqps', 'n_qpn', 'fetch_cr', 'fetch_exec', 'fetch_reposted'])
            for t in trials:
                if t['kind'] != 't1':
                    continue
                for r in t['rounds']:
                    w.writerow([t['tag'], r['pe'], r['role'], r['total_ms'], r['handshake_ms'], r['nqps'], r['n_qpn'], r['fetch_cr'],
                                r['fetch_exec'], r['fetch_reposted']])


if __name__ == '__main__':
    main()
