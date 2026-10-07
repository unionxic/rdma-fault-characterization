#!/usr/bin/env python3
"""Independent recount of completion_contract P1-P7 from the raw logs.

    python3 qa/recount.py [results/20261007]

Reads only run_all.out, P*/trials.csv, P*/gin.csv, the per-trial PE / rank logs and .kv files, and
the run_trial.sh .out files. It does not read score.py, SCORE.md or trials_scored.csv. Every value
used for a verdict is taken from the logs; trials.csv and gin.csv are only compared against them.
Acceptance rules: predictions.csv and EXPERIMENT.md 3.2, 7, 8 (tag prereg/completion-contract-v1),
read with DEVIATIONS.md 1, 3, 4, 5. Prints a report to stdout; writes nothing.
"""
import csv
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, '..', 'results', '20261007')
SMOKE = ROOT + '_smoke'

PLAN = {'P1': 10, 'P2': 5, 'P3': 5, 'P4': 10, 'P5': 5, 'P6': 15, 'P7': 5}
NVS_CELLS = {  # cell: (variant, handler env, kill, expected handler text in log)
    'P1': ('ahinit', 'cpu_host_memory', 1, 'CPU with host memory backend'),
    'P2': ('stock', 'gpu', 1, 'GPU'),
    'P3': ('ahinit', 'cpu_host_memory', 0, 'CPU with host memory backend'),
}
GIN_CELLS = {'P4': ['none'], 'P5': ['none'], 'P6': ['F1', 'F2', 'F3'], 'P7': ['none']}
GIN_HANDLER = {'P4': '6', 'P5': 'default', 'P6': '1', 'P7': '1'}   # from run_cells.sh only
SLOW_MS = 100.0          # DEVIATIONS 1
KILL_AFTER = 3           # run.sh default, DEVIATIONS 1
WIN_A = (3000.0, 5000.0); BOUND_A_S = 30   # as written
WIN_B = (50000.0, 70000.0); BOUND_B_S = 90  # DEVIATIONS 3 (b)
POLL_PHRASE = 'falling back to polling-based errors'

issues = []   # (where, text)


def note(where, text):
    issues.append((where, text))


def read(path):
    with open(path, errors='replace') as f:
        return f.read()


def fmt_range(vals, unit='', nd=1):
    vals = [v for v in vals if v is not None]
    if not vals:
        return '-'
    lo, hi = min(vals), max(vals)
    f = '%.' + str(nd) + 'f'
    return (f % lo) + ('' if lo == hi else '–' + (f % hi)) + unit


# ---------------------------------------------------------------- 1. trial set
def check_trial_set():
    print('== 1. Trial set')
    lines = read(os.path.join(ROOT, 'run_all.out')).splitlines()
    prog = []
    for ln in lines:
        m = re.match(r'^(P\d)(?: (none|F\d))? t(\d+) (\d\d:\d\d:\d\d)$', ln)
        if m:
            prog.append((m.group(1), m.group(2) or '-', int(m.group(3)), m.group(4)))
    print('run_all.out: %d lines, %d progress lines' % (len(lines), len(prog)))
    start = next((ln.split()[1:] for ln in lines if ln.startswith('start ')), None)
    end = next((ln.split()[1:] for ln in lines if ln.startswith('end ')), None)
    print('  start %s, end %s, wrapper rc line: %s' % (start, end,
          next((ln[20:] for ln in lines if 'command exited' in ln), '?')))
    seen = {}
    for c, f, t, _ in prog:
        seen.setdefault((c, f), []).append(t)
    for c, n in PLAN.items():
        keys = [k for k in seen if k[0] == c]
        tot = sum(len(seen[k]) for k in keys)
        detail = []
        for k in sorted(keys):
            ts = seen[k]
            dup = len(ts) != len(set(ts))
            gap = sorted(ts) != list(range(1, len(ts) + 1))
            detail.append('%s:%d%s%s' % (k[1], len(ts), ' DUP' if dup else '', ' GAP' if gap else ''))
            if dup or gap:
                note('run_all.out', '%s %s trial numbers %s' % (c, k[1], ts))
        ok = 'ok' if tot == n else 'MISMATCH (plan %d)' % n
        print('  %s: %d progress lines [%s] %s' % (c, tot, ', '.join(detail), ok))
        if tot != n:
            note('run_all.out', '%s has %d progress lines, plan %d' % (c, tot, n))
    print('  total progress lines %d (plan %d)' % (len(prog), sum(PLAN.values())))
    # smoke folders: listed, not scored
    if os.path.isdir(SMOKE):
        parts = []
        for d in sorted(os.listdir(SMOKE)):
            rows = 0
            for p in glob.glob(os.path.join(SMOKE, d, '*', 'trials.csv')):
                rows += sum(1 for ln in read(p).splitlines() if ln.strip())
            for p in glob.glob(os.path.join(SMOKE, d, '*', 'gin.csv')):
                rows += sum(1 for ln in read(p).splitlines()[1:] if ln.strip())
            parts.append('%s %d rows' % (d, rows))
        print('  smoke (not scored): ' + ', '.join(parts))
    return prog


def window_for(prog, cell, fault, trial):
    """(previous progress time, this progress time) = the wall-clock window the trial ran in."""
    idx = next((i for i, p in enumerate(prog) if p[:3] == (cell, fault, trial)), None)
    if idx is None:
        return None, None
    return (prog[idx - 1][3] if idx > 0 else '00:00:00'), prog[idx][3]


# ---------------------------------------------------------------- 2. NVSHMEM
IT_RE = re.compile(r'^PE 0 iter (\d+): put \+ signal \+ nvshmem_quiet\(\) returned after ([0-9.]+) ms')
HANG_RE = re.compile(r'^PE 0 iter (\d+): nvshmem_quiet\(\) has not returned after (\d+) s')
FAIL_RE = re.compile(r'^PE 0 iter (\d+): kernel failed')
PLUG_RE = re.compile(r'nv345/(ahinit/)?nvshmem-3\.4\.5-0/src/modules/transport/ibgda/ibgda\.cpp (\d+) '
                     r'NIC handler will be ([^.\n]*)')
PE1_RE = re.compile(r'^PE 1 iter (\d+): signal arrived')


def parse_pe0(path):
    txt = read(path)
    its, hang, fail = {}, None, None
    for ln in txt.splitlines():
        m = IT_RE.match(ln)
        if m:
            its[int(m.group(1))] = float(m.group(2))
            continue
        m = HANG_RE.match(ln)
        if m:
            hang = (int(m.group(1)), int(m.group(2)))
        m = FAIL_RE.match(ln)
        if m:
            fail = int(m.group(1))
    plug = PLUG_RE.search(txt)
    ready = re.search(r'^PE 0 ready: .*hang_s=(\d+)', txt, re.M)
    last_iter_line = [ln for ln in txt.splitlines() if ln.startswith('PE 0 ')]
    return dict(its=its, hang=hang, fail=fail,
                all40=bool(re.search(r'^PE 0: all 40 iterations returned', txt, re.M)),
                plugin=('ahinit' if plug and plug.group(1) else 'stock') if plug else None,
                plugin_line=int(plug.group(2)) if plug else None,
                handler=plug.group(3).strip() if plug else None,
                hang_s=int(ready.group(1)) if ready else None,
                rcmap=(re.search(r'IBGDA_RC_MAP_BY is set to (\w+)', txt) or [None, None])[1],
                marker='=== runner: SIGKILL' in txt,
                last_line=last_iter_line[-1] if last_iter_line else '')


def parse_pe1(path):
    txt = read(path)
    plug = PLUG_RE.search(txt)
    got = [int(m.group(1)) for m in (PE1_RE.match(ln) for ln in txt.splitlines()) if m]
    return dict(plugin=('ahinit' if plug and plug.group(1) else 'stock') if plug else None,
                handler=plug.group(3).strip() if plug else None,
                last_iter=max(got) if got else None, n_sig=len(got),
                all40=bool(re.search(r'^PE 1: all 40 iterations returned', txt, re.M)))


def first_after_kill(its, hang):
    """DEVIATIONS 1: first iteration after KILL_AFTER that took > 100 ms or did not return."""
    for i in range(KILL_AFTER + 1, 40):
        if i in its:
            if its[i] > SLOW_MS:
                return i, its[i], 'returned'
        elif hang and hang[0] == i:
            return i, None, 'not returned (%d s bound)' % hang[1]
        else:
            return i, None, 'no line'
    return None, None, 'none'


def nvshmem(prog):
    print('\n== 2. NVSHMEM cells (P1-P3), PE 0 / PE 1 logs')
    out = {}
    for cell, (var, henv, kill, htext) in NVS_CELLS.items():
        rows = list(csv.reader(open(os.path.join(ROOT, cell, 'trials.csv'))))
        hdr = rows and rows[0][0] == 'variant'
        if hdr:
            rows = rows[1:]
        trials = []
        nums = [int(r[3]) for r in rows]
        if sorted(nums) != list(range(1, PLAN[cell] + 1)):
            note(cell + '/trials.csv', 'trial numbers %s' % nums)
        print('%s (%s, %s, kill=%d): %d rows in trials.csv%s' % (cell, var, henv, kill, len(rows),
              '' if hdr else ' (no header row)'))
        print('  t  plugin(pe0/pe1)  line  handler(pe0/pe1)        hang_s  first-slow  ms        '
              'earlier<100ms  pe1_last  all40  marker  kill_at       csv_ok')
        for r in rows:
            v, h, k, t = r[0], r[1], int(r[2]), int(r[3])
            tag = '%s_%s_kill%d_t%d' % (v, h, k, t)
            p0 = parse_pe0(os.path.join(ROOT, cell, tag + '.pe0.log'))
            p1 = parse_pe1(os.path.join(ROOT, cell, tag + '.pe1.log'))
            fi, fms, how = first_after_kill(p0['its'], p0['hang']) if kill else (None, None, '-')
            earlier = all(p0['its'].get(j, 1e9) < SLOW_MS for j in range(fi)) if fi is not None else None
            # trials.csv vs logs
            bad = []
            if (v, h, k) != (var, henv, kill):
                bad.append('row variant/handler/kill %s/%s/%d' % (v, h, k))
            if r[4] != p0['handler']:
                bad.append('handler_log %r vs log %r' % (r[4], p0['handler']))
            if r[9] != p0['last_line']:
                bad.append('last line differs')
            if (r[5] == '-') != (kill == 0):
                bad.append('kill_at %r with kill=%d' % (r[5], kill))
            if r[6] != '0' and p0['all40']:
                bad.append('pe0_rc %s but all 40 returned' % r[6])
            if r[8] != '0;0;0;0;':
                bad.append('counter deltas %s' % r[8])
            lo, hi = window_for(prog, cell, '-', t)
            if kill and r[5] != '-' and lo and not (lo <= r[5][:8] <= hi):
                bad.append('kill_at %s outside run window %s-%s' % (r[5], lo, hi))
            for b in bad:
                note('%s t%d' % (cell, t), b)
            print('  %-2d %-6s/%-6s  %4s  %-22s  %-6s  %-10s  %-8s  %-13s  %-8s  %-5s  %-6s  %-12s  %s' % (
                t, p0['plugin'], p1['plugin'], p0['plugin_line'], (p0['handler'] or '?')[:10] + '/' + (p1['handler'] or '?')[:10],
                p0['hang_s'], ('iter %s' % fi) if fi is not None else '-', ('%.1f' % fms) if fms else how if kill else '-',
                earlier if kill else '-', p1['last_iter'], p0['all40'], p0['marker'], r[5], 'yes' if not bad else 'NO'))
            trials.append(dict(t=t, p0=p0, p1=p1, fi=fi, fms=fms, how=how, earlier=earlier, row=r))
            if p0['plugin'] != var or p1['plugin'] != var:
                note('%s t%d' % (cell, t), 'plugin build in log %s/%s, expected %s' % (p0['plugin'], p1['plugin'], var))
            if p0['handler'] != htext or p1['handler'] != htext:
                note('%s t%d' % (cell, t), 'handler in log %s/%s, expected %s' % (p0['handler'], p1['handler'], htext))
            if p0['rcmap'] != 'cta' or p0['hang_s'] != 90:
                note('%s t%d' % (cell, t), 'rc map %s, hang_s %s' % (p0['rcmap'], p0['hang_s']))
        if kill:
            nm = [tr['t'] for tr in trials if not tr['p0']['marker']]
            if nm:
                note(cell, 'runner line "=== runner: SIGKILL PE 1 at ..." absent from PE 0 log in trials %s '
                     '(kill time only in trials.csv)' % nm)
        ctr = sorted(set(tr['row'][8] for tr in trials))
        note(cell, 'NIC counter deltas (ack timeout; CQE error; flush; remote access) in trials.csv: %s' % ctr)
        if not hdr:
            note(cell + '/trials.csv', 'no header row')
        allits = [ms for tr in trials for i, ms in tr['p0']['its'].items() if not (tr['fi'] is not None and i == tr['fi'])]
        print('  every other PE 0 iteration (all trials of %s, n=%d): %s ms' % (cell, len(allits), fmt_range(allits)))
        out[cell] = trials
    return out


def score_kill(cell, trials, need, win, bound_s, extra_bound):
    n = len(trials)
    apart = [tr['t'] for tr in trials if tr['fi'] is None]
    scored = [tr for tr in trials if tr['fi'] is not None]
    hits = [tr['t'] for tr in scored if tr['fms'] is not None and tr['earlier'] and win[0] <= tr['fms'] <= win[1]]
    beyond = [tr['t'] for tr in scored if tr['fms'] is None or tr['fms'] > bound_s * 1e3]
    misses = [tr['t'] for tr in scored if tr['t'] not in hits]
    ok = len(hits) >= need and (not extra_bound or not beyond)
    return dict(n=n, scored=len(scored), apart=apart, hits=hits, misses=misses, beyond=beyond, ok=ok)


# ---------------------------------------------------------------- 3. NCCL
def kv_parse(path):
    d = {'okit': 0}
    if not os.path.exists(path):
        return None
    for ln in read(path).splitlines():
        if ln.startswith('okit='):
            d['okit'] += 1
            continue
        m = re.search(r'host_error=(.*?) host_error_ms=(\S+)', ln)
        if m:
            d['host_error'], d['host_error_ms'] = m.group(1), float(m.group(2))
            ln = ln[:m.start()]
        for k, v in re.findall(r'(\w+)=(\S+)', ln):
            d[k] = v
    return d


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def nccl(prog):
    print('\n== 3. NCCL GIN GDAKI cells (P4-P7), rank logs and .kv')
    out = {}
    for cell, faults in GIN_CELLS.items():
        rows = list(csv.DictReader(open(os.path.join(ROOT, cell, 'gin.csv'))))
        print('%s (handler %s from run_cells.sh): %d rows in gin.csv' % (cell, GIN_HANDLER[cell], len(rows)))
        for f in faults:
            nums = [int(r['trial']) for r in rows if r['fault'] == f]
            if sorted(nums) != list(range(1, 6 if cell != 'P4' else 11)):
                note(cell + '/gin.csv', 'fault %s trial numbers %s' % (f, nums))
        print('  fault t  it_ok(r0/r1) dev_wait(r0/r1 ms)  init     data(r1)  host_err(r0|r1)            '
              'he_ms    fault_ms  surf_ms  moved  poll  initOK  nOK  ib_to  csv_ok')
        trials = []
        for r in rows:
            f, t = r['fault'], int(r['trial'])
            base = os.path.join(ROOT, cell, 'logs', 'gdaki_%s_timeout_t%d' % (f, t))
            k0, k1 = kv_parse(base + '_r0.kv'), kv_parse(base + '_r1.kv')
            l0, l1 = read(base + '_r0.log'), read(base + '_r1.log')
            outf = read(os.path.join(ROOT, cell, 'gdaki_%s_timeout_t%d.out' % (f, t)))
            poll = (POLL_PHRASE in l0) or (POLL_PHRASE in l1)
            init_ok = all(('Init COMPLETE' in l and 'devComm created' in l) for l in (l0, l1))
            dw0 = [float(x) for x in re.findall(r'device wait returned ncclTimeout \(([0-9.]+) ms\)', l0)]
            dw1 = [float(x) for x in re.findall(r'device wait returned ncclTimeout \(([0-9.]+) ms\)', l1)]
            n_ok_lines = len(re.findall(r'^\[rank0\] it +\d+ ok', l0, re.M))
            cyc = re.search(r'\[rank0\] devComm created \(clock=(\d+) kHz, timeoutCycles=(\d+)\)', l0)
            bound_ms = int(cyc.group(2)) / int(cyc.group(1)) if cyc else None
            ibto = (re.search(r'ib_timeout=(\d+)', outf) or [None, None])[1]
            fire0 = re.search(r'fire_mono_ms=([0-9.]+)', l0)
            fire1 = re.search(r'fire_mono_ms=([0-9.]+)', l1)
            moved = (re.search(r'moved (\d+/\d+)', l0 + l1) or [None, '-'])[1]
            t0r0, t0r1 = fnum(k0.get('t0_mono_ms')), fnum(k1.get('t0_mono_ms'))
            off = fnum(k0.get('clock_offset_ms'))
            fault_abs = None
            if f == 'F1' and fire0:
                fault_abs = float(fire0.group(1))
            elif f == 'F3' and fire1 and off is not None:
                fault_abs = float(fire1.group(1)) - off
            elif f == 'F2':
                fault_abs = fnum(k0.get('fault_mono_ms'))
            fault_ms = fault_abs - t0r0 if fault_abs is not None else None
            he0, he0ms = k0.get('host_error', 'none'), k0.get('host_error_ms', -1.0)
            he1, he1ms = k1.get('host_error', 'none'), k1.get('host_error_ms', -1.0)
            cands = []
            if he0 != 'none' and he0ms >= 0:
                cands.append((he0ms, 'r0', he0))
            if he1 != 'none' and he1ms >= 0 and t0r1 is not None and off is not None:
                cands.append((t0r1 + he1ms - off - t0r0, 'r1', he1))
            he = min(cands) if cands else None
            surf = he[0] - fault_ms if (he and fault_ms is not None) else None
            gin_err = ('GIN Error detected' in l0, 'GIN Error detected' in l1)
            # gin.csv vs raw
            bad = []

            def cmp(name, csvv, raw, tol=0.15):
                if isinstance(raw, float) or raw is None:
                    cv = fnum(csvv)
                    if (cv is None) != (raw is None) or (cv is not None and abs(cv - raw) > tol):
                        bad.append('%s csv %r vs raw %r' % (name, csvv, None if raw is None else round(raw, 1)))
                elif str(csvv) != str(raw):
                    bad.append('%s csv %r vs raw %r' % (name, csvv, raw))
            cmp('iters_ok_before', r['iters_ok_before'], k0.get('iters_ok'))
            cmp('init_outcome', r['init_outcome'], k0.get('init_outcome'))
            cmp('data_check', r['data_check'], k1.get('data_check'))
            cmp('host_error', r['host_error'], he[2].split()[0] if he else 'none')
            cmp('host_error_ms', r['host_error_ms'], he[0] if he else None)
            cmp('fault_ms', r['fault_ms'], fault_ms)
            cmp('surface_ms', r['surface_ms'], surf)
            cmp('surface_by', r['surface_by'], he[1] if he else '-')
            mv = re.search(r'qps_moved=([^;]*)', r['notes']).group(1)
            cmp('qps_moved', mv, moved)
            rc0 = re.search(r'r0rc=(\d+)', r['notes']).group(1)
            ex0 = (re.search(r'\[rank0\] DONE .*exit=(\d+)', l0) or [None, None])[1]
            cmp('r0rc vs DONE exit', rc0, ex0)
            if k0.get('okit') != int(k0.get('iters_ok', -1)):
                bad.append('r0 okit lines %d vs iters_ok %s' % (k0['okit'], k0.get('iters_ok')))
            lo, hi = window_for(prog, cell, f, t)
            stamps = re.findall(r'^\[2026-10-07 (\d\d:\d\d:\d\d)\] rain', l0, re.M)
            if stamps and lo and not (lo <= stamps[0] and stamps[-1] <= hi):
                bad.append('r0 log stamps %s-%s outside run window %s-%s' % (stamps[0], stamps[-1], lo, hi))
            for b in bad:
                note('%s %s t%d' % (cell, f, t), b)
            print('  %-5s %-2d %3s/%-3s     %-8s/%-8s     %-8s %-9s %-26s %-8s %-9s %-8s %-6s %-5s %-6s %-4d %-5s  %s' % (
                f, t, k0.get('iters_ok'), k1.get('iters_ok'),
                ('%.1f' % dw0[0]) if dw0 else '-', ('%.1f' % dw1[0]) if dw1 else '-',
                k0.get('init_outcome'), k1.get('data_check'),
                (he0.split()[0] if he0 != 'none' else 'none') + '|' + (he1.split()[0] if he1 != 'none' else 'none'),
                ('%.1f' % he[0]) if he else '-', ('%.1f' % fault_ms) if fault_ms is not None else '-',
                ('%.1f' % surf) if surf is not None else '-', moved, poll, init_ok, n_ok_lines, ibto,
                'yes' if not bad else 'NO'))
            trials.append(dict(f=f, t=t, k0=k0, k1=k1, poll=poll, init_ok=init_ok, dw0=dw0, dw1=dw1,
                               n_ok_lines=n_ok_lines, bound_ms=bound_ms, fault_ms=fault_ms, he=he,
                               he_r1=he1, surf=surf, moved=moved, gin_err=gin_err, ibto=ibto,
                               rc=(rc0, re.search(r'r1rc=(\d+)', r['notes']).group(1))))
        out[cell] = trials
    return out


# ---------------------------------------------------------------- 4. verdicts
def verdicts(nv, gn):
    print('\n== 4. Verdicts')
    res = {}
    for cell in ('P1', 'P2'):
        need = 9 if cell == 'P1' else 5
        tr = nv[cell]
        a = score_kill(cell, tr, need, WIN_A, BOUND_A_S, extra_bound=(cell == 'P1'))
        b = score_kill(cell, tr, need, WIN_B, BOUND_B_S, extra_bound=True)
        if cell == 'P2':   # 5/5 has no separate bound clause in the frozen rule; report it anyway
            a['ok'] = len(a['hits']) >= need
            b['ok'] = len(b['hits']) >= need
        fms = [x['fms'] for x in tr if x['fms'] is not None]
        print('%s first iteration after the kill: iterations %s; duration %s ms (n=%d)' % (
            cell, sorted(set(x['fi'] for x in tr)), fmt_range(fms), len(fms)))
        for lab, s, win, bd in (('(a) as written', a, WIN_A, BOUND_A_S), ('(b) timeout 20', b, WIN_B, BOUND_B_S)):
            print('  %s: window %.0f-%.0f s, bound %d s: n=%d scored=%d apart=%s hits=%d misses=%s '
                  'not-returned-within-bound=%s -> %s' % (
                      lab, win[0] / 1e3, win[1] / 1e3, bd, s['n'], s['scored'], s['apart'], len(s['hits']),
                      s['misses'], s['beyond'], 'HOLDS' if s['ok'] else 'FAILS'))
        res[cell] = (a, b)
    tr = nv['P3']
    h = [x['t'] for x in tr if x['p0']['all40'] and x['p1']['all40'] and len(x['p0']['its']) == 40]
    print('P3 all 40 iterations returned (PE 0 and PE 1): %d/%d -> %s' % (len(h), len(tr), 'HOLDS' if len(h) == 5 else 'FAILS'))
    res['P3'] = (len(h), len(tr))

    tr = gn['P4']
    apart = [x['t'] for x in tr if not x['init_ok']]
    sc = [x for x in tr if x['init_ok']]
    hit = [x['t'] for x in sc if x['k0'].get('init_outcome') == 'timeout' and x['k0'].get('iters_ok') == '0'
           and x['dw0'] and x['k1'].get('data_check') == 'missing']
    normal = [x['t'] for x in sc if x['k0'].get('init_outcome') == 'ok' or x['n_ok_lines'] > 0]
    ok = len(hit) >= 9 and not normal
    print('P4 first wait times out, no data at target: n=%d excluded(init rejected handler 6)=%s hits=%d '
          'normal completions=%s -> %s' % (len(tr), apart, len(hit), normal, 'HOLDS' if ok else 'FAILS'))
    print('   rank0 device wait %s ms, rank1 %s ms, nominal bound %s ms; host error %s' % (
        fmt_range([x['dw0'][0] for x in tr if x['dw0']]), fmt_range([x['dw1'][0] for x in tr if x['dw1']]),
        fmt_range([x['bound_ms'] for x in tr]), sorted(set(str(x['he']) for x in tr))))
    res['P4'] = (len(tr), hit, normal, apart)

    for cell in ('P5', 'P7'):
        tr = gn[cell]
        hit = [x['t'] for x in tr if x['k0'].get('init_outcome') == 'ok' and x['k0'].get('iters_ok') == '120'
               and x['k1'].get('iters_ok') == '120' and x['k1'].get('data_check') == 'ok'
               and (cell == 'P5' or (x['he'] is None and x['he_r1'] == 'none'))]
        print('%s complete normally%s: %d/%d -> %s' % (cell, ' with no host error' if cell == 'P7' else '',
              len(hit), len(tr), 'HOLDS' if len(hit) == 5 else 'FAILS'))
        res[cell] = (len(hit), len(tr))

    tr = gn['P6']
    res['P6'] = {}
    for f in ('F1', 'F2', 'F3'):
        ft = [x for x in tr if x['f'] == f]
        unobs = [x['t'] for x in ft if x['poll']]
        notapp = [x['t'] for x in ft if not x['poll'] and (x['fault_ms'] is None or x['k0'].get('iters_ok') == '120')]
        sc = [x for x in ft if x['t'] not in unobs + notapp]
        hit = [x['t'] for x in sc if x['he'] is not None and x['surf'] is not None and x['surf'] > 0]
        print('P6 %s host error reported: n=%d unobservable(polling)=%s fault-not-applied=%s hits=%d/%d -> %s' % (
            f, len(ft), unobs, notapp, len(hit), len(sc), 'HOLDS' if len(hit) == 5 else 'FAILS'))
        print('   fault at %s ms; host error at %s ms (from rank %s); host error after fault %s ms; '
              'iters before %s; QPs moved %s' % (
                  fmt_range([x['fault_ms'] for x in ft]), fmt_range([x['he'][0] for x in ft if x['he']]),
                  sorted(set(x['he'][1] for x in ft if x['he'])), fmt_range([x['surf'] for x in ft]),
                  sorted(set(x['k0'].get('iters_ok') for x in ft)), sorted(set(x['moved'] for x in ft))))
        res['P6'][f] = (len(ft), hit, unobs, notapp)
    print('P6 all: rank1 host error %s; r0 device wait %s ms; data(r1) %s; init %s' % (
        sorted(set(x['he_r1'] for x in tr)), fmt_range([x['dw0'][0] for x in tr if x['dw0']]),
        sorted(set(x['k1'].get('data_check') for x in tr)), sorted(set(x['k0'].get('init_outcome') for x in tr))))
    allg = [x for c in gn for x in gn[c]]
    print('NCCL all %d trials: polling phrase in %d; init complete in %d; ib_timeout %s; host error strings %s' % (
        len(allg), sum(x['poll'] for x in allg), sum(x['init_ok'] for x in allg), sorted(set(x['ibto'] for x in allg)),
        sorted(set(x['he'][2] for x in allg if x['he']))))
    for c in gn:
        print('  %s "GIN Error detected" in rank0 logs %d, rank1 logs %d of %d; r0rc/r1rc %s' % (
            c, sum(x['gin_err'][0] for x in gn[c]), sum(x['gin_err'][1] for x in gn[c]), len(gn[c]),
            sorted(set('/'.join(x['rc']) for x in gn[c]))))
    return res


def main():
    prog = check_trial_set()
    nv = nvshmem(prog)
    gn = nccl(prog)
    verdicts(nv, gn)
    print('\n== 5. Records that differ from the logs, or other notes (%d)' % len(issues))
    for w, t in issues:
        print('  %s: %s' % (w, t))


if __name__ == '__main__':
    main()
