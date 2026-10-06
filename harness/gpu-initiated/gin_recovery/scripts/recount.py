#!/usr/bin/env python3
"""recount.py - recount GIN GDAKI recovery outcomes straight from the raw trial logs.

usage: recount.py [<results dir>] > results/RECOUNT.md
       (default results dir: ../results relative to this script)

Reads only the per-trial raw files (<stem>_meta.txt, <stem>_r0.kv, <stem>_r1.kv, <stem>_r0.log,
<stem>_r1.log) of the result sets 20260924/ and 20260924_gpudb/. It does not use trials.csv /
events.csv / summary.md, except as a cross-check at the end (per-trial round and decline counts
compared with the rec_rows.py output where one exists).

Definitions (also printed in the output):
  round            one completed Prepare -> handshake (REQ/ACK) -> Commit -> replay cycle on the
                   initiator: a rank-0 'rec ev=' line with outcome=recovered or outcome=replay_failed.
                   With d = 1 the replay is the put + signal ADD; with d = 0 nothing is replayed.
  round after a fault   a round whose 'fault ev=' record has a classified error (class != FORCED_TEST).
  forced round     a D0 round (class FORCED_TEST): no fault, recovery forced after a completed
                   operation to exercise d = 0. Not "after a detected fault"; reported separately.
  recovered round  outcome=recovered (replay succeeded, or d = 0).
  replay-failed round   outcome=replay_failed (the replay met a QP in ERR; the next round reads V again,
                   or the initiator declines if the replay error is not ncclRemoteError).
  decline          a rank-0 'rec ev=' line with outcome=declined, grouped by where it happened:
                     before handshake - policy or guard, no REQ sent (class_*, retry_exc_peer_dead,
                                        prepare_failed, fault_query_failed, no_classified_record,
                                        too_many_attempts, oob_send_failed)
                     handshake declined - REQ sent, no usable ACK/commit (handshake_timeout, peer_nack,
                                        peer_fail, peer_closed_during_handshake, bad_delta, commit_failed)
                     after a round   - Commit done, the replay failed with a non-remote error
                                        (replay_error, replay_host_timeout); that round is also
                                        counted as a replay-failed round.
  recovered run    rank 0 and rank 1 both completed every iteration (init_outcome=ok, iters_ok = iters),
                   no decline, and at least one round after a fault.
  forced-only run  completed, all rounds forced (D0).
  no-fault run     completed, no rounds and no shots fired.
  declined run     rank 0 declined (init_outcome=declined).
  bit-exact        rank 1 checks every iteration: all bytes equal the pattern AND the signal equals
                   base + iteration + 1 ('okit' on rank 1). "ops verified" = rank-1 okit count.
                   "run exact" = ops verified = iters, data_check=ok and final signal_exact=1.
  V + d = expected checked on every responder ACK line ('rxrec ... outcome=ack V= expected= d=').
"""
import csv, glob, os, re, sys
from collections import Counter, OrderedDict

KVRE = re.compile(r'(\w+)=("[^"]*"|\S+)')

PRE_HANDSHAKE = ('retry_exc_peer_dead', 'prepare_failed', 'fault_query_failed', 'no_classified_record',
                 'too_many_attempts', 'oob_send_failed')
HANDSHAKE = ('handshake_timeout', 'peer_nack', 'peer_fail', 'peer_closed_during_handshake', 'bad_delta',
             'commit_failed')
AFTER_ROUND = ('replay_error', 'replay_host_timeout')

DIAG = {'keepgpupi': 'keep_gpu_pi', 'keepgpudbr': 'keep_gpu_dbr', 'docarsvd': 'doca_cqe_rsvd',
        'keepdb': 'keep_proxy_db'}

DESC = {
    '20260924/runs/logs': 'main matrix (CPU-doorbell fallback, recovery v1)',
    '20260924/confirm/logs': 'confirmation batch, final v1 build',
    '20260924/smoke': 'first end-to-end smoke',
    '20260924/diag/negative': 'negative controls (v1)',
    '20260924/diag/cancel_phase': 'release-kernel diagnostic, before the warming fix',
    '20260924/diag/f2_before_warm': 'F2 before the kernel-warming fix',
    '20260924/lat/logs': 'no-fault overhead runs',
    '20260924_gpudb/runs/logs': 'v2 matrix under GPU doorbells, incl. forced-proxy regression and negative controls',
    '20260924_gpudb/v1/logs': 'committed v1 under GPU doorbells',
    '20260924_gpudb/smoke/logs': 'v2 smoke',
    '20260924_gpudb/lat/logs': 'no-fault overhead runs',
    '20260924_gpudb/lat/failed': 'lat run that failed in bootstrap (port collision), re-run',
    '20260924_gpudb/q4/logs': 'unchanged `gin_q4` classifier re-run (not the recovery driver)',
}
ORDER = list(DESC)


def kvline(line):
    return {k: v.strip('"') for k, v in KVRE.findall(line)}


def lines(path):
    if not os.path.exists(path):
        return None
    return [ln.rstrip('\n') for ln in open(path, errors='replace')]


def last(ls, prefix):
    """kv dict of the last line starting with prefix"""
    for ln in reversed(ls or []):
        if ln.startswith(prefix):
            return kvline(ln)
    return {}


def count_in(path, needle):
    ls = lines(path)
    return sum(1 for ln in ls if needle in ln) if ls else 0


def dbmode(path):
    mode = ''
    for ln in lines(path) or []:
        if 'GIN/GDAKI: doorbell mode=' in ln:
            m = re.search(r'doorbell mode=(\S+).*user_ctx=(\d)', ln)
            if m and (m.group(2) == '1' or not mode):
                mode = m.group(1)
    return mode


def trial(d, stem):
    meta = kvline(open(os.path.join(d, stem + '_meta.txt')).read())
    k0 = lines(os.path.join(d, stem + '_r0.kv'))
    k1 = lines(os.path.join(d, stem + '_r1.kv'))
    fin0 = last(k0, 'iters_ok=')
    fin1 = last(k1, 'iters_ok=')
    faults = {}
    for ln in k0 or []:
        if ln.startswith('fault ev='):
            kv = kvline(ln)
            faults[kv['ev']] = kv
    recs = [kvline(ln) for ln in (k0 or []) if ln.startswith('rec ev=')]
    rounds = [r for r in recs if r.get('outcome') in ('recovered', 'replay_failed')]
    for r in rounds:
        r['forced'] = faults.get(r['ev'], {}).get('class', r.get('class', '')) == 'FORCED_TEST'
    declines = [r for r in recs if r.get('outcome') == 'declined']
    acks = [kvline(ln) for ln in (k1 or []) if ln.startswith('rxrec ') and 'outcome=ack' in ln]
    nacks = [kvline(ln) for ln in (k1 or []) if ln.startswith('rxrec ') and 'outcome=nack' in ln]
    okit1 = sum(1 for ln in (k1 or []) if re.match(r'okit=\d+$', ln))
    rec_ops0 = sum(1 for ln in (k0 or []) if re.match(r'okit=\d+ rec=1$', ln))
    checkfail1 = [kvline(ln) for ln in (k1 or []) if ' check=' in ln]
    shots = (count_in(os.path.join(d, stem + '_r0.log'), 'GDAKI fault fired') +
             count_in(os.path.join(d, stem + '_r1.log'), 'GDAKI fault fired'))
    sig = last(k1, 'final_signal=')
    lat1 = last(k1, 'lat_data_bad=')
    iters = int(meta.get('iters', 0) or 0)
    t = dict(stem=stem, meta=meta, fault=meta.get('fault', '?'), wait=meta.get('wait', '?'),
             rec=meta.get('rec', '?'), inject=meta.get('inject', ''), iters=iters, bundle=meta.get('bundle', ''),
             out0=fin0.get('init_outcome', 'killed' if k0 is not None else 'missing'),
             out1=fin1.get('init_outcome', 'killed' if k1 is not None else 'missing'),
             ok0=int(fin0.get('iters_ok', 0) or 0), ok1=okit1, data1=fin1.get('data_check', ''),
             sig_exact=sig.get('signal_exact', ''), final_sig=sig.get('final_signal', ''),
             exp_sig=sig.get('expected_final', ''), rounds=rounds, declines=declines, acks=acks, nacks=nacks,
             rec_ops0=rec_ops0, checkfail1=checkfail1, shots=shots,
             db0=dbmode(os.path.join(d, stem + '_r0.log')), db1=dbmode(os.path.join(d, stem + '_r1.log')),
             thr0=meta.get('r0_gin_proxy_thread', ''), lat_bad=lat1.get('lat_data_bad'),
             lat_n=last(k0, 'lat_p50_us=').get('lat_n') or last(k0, 'lat_n=').get('lat_n'),
             left=int(meta.get('left', 0) or 0), r0rc=meta.get('r0rc', ''), r1rc=meta.get('r1rc', ''))
    # consistency checks
    t['vd_ok'] = sum(1 for a in acks if int(a['V']) + int(a['d']) == int(a['expected']))
    t['vd_bad'] = len(acks) - t['vd_ok']
    t['completed'] = (t['out0'] == 'ok' and t['out1'] == 'ok' and t['ok0'] == iters and t['ok1'] == iters)
    t['exact'] = (t['ok1'] == iters and t['data1'] == 'ok' and t['sig_exact'] == '1')
    fr = [r for r in rounds if not r['forced']]
    if t['fault'] == 'lat':
        cat = 'lat'
    elif t['rec'] == '0':
        cat = 'flag off'
    elif t['out0'] == 'declined' or declines:
        cat = 'declined'
    elif t['completed'] and fr:
        cat = 'recovered'
    elif t['completed'] and rounds:
        cat = 'forced-only'
    elif t['completed'] and not rounds and t['shots'] == 0:
        cat = 'no fault'
    else:
        cat = 'other'
    t['cat'] = cat
    return t


def cell(t, setname):
    k = t['fault']
    if k in ('F1', 'F3') and ',' in (t['inject'] or ''):
        k += ' x' + str(len(t['inject'].split(',')))
    if t['rec'] == '0':
        k += ' [flag off]'
    for tag, name in DIAG.items():
        if tag in t['stem']:
            k += ' [DIAG ' + name + ']'
    if setname.startswith('20260924_gpudb'):
        if t['bundle'] == 'gin_recovery':
            k += ' [v1]'
        if t['db0'] == 'CPU_PROXY' or (not t['db0'] and t['thr0'] == '1'):
            k += ' [CPU proxy forced]'
    return k


TSRE = re.compile(r'^\[(2026-\d\d-\d\d \d\d:\d\d:\d\d)\]')


def time_range(d, stems):
    """first and last NCCL log timestamp over the rank-0 logs of a set (wall clock of rain)"""
    lo = hi = None
    for st in stems:
        for ln in lines(os.path.join(d, st + '_r0.log')) or []:
            m = TSRE.match(ln)
            if m:
                ts = m.group(1)
                lo = ts if lo is None or ts < lo else lo
                hi = ts if hi is None or ts > hi else hi
    return (lo, hi)


def dmode(ts, setname):
    modes = Counter()
    for t in ts:
        if t['db0'] or t['db1']:
            modes[f"{t['db0'] or '?'}/{t['db1'] or '?'}"] += 1
        elif t['thr0'] in ('0', '1'):
            modes['GPU (no proxy thread)' if t['thr0'] == '0' else 'CPU_PROXY (proxy thread)'] += 1
        elif t['thr0'] != '':
            modes['not probed (r0 thread probe: ' + t['thr0'] + ')'] += 1
        elif setname.startswith('20260924/'):
            modes['not logged (pre-override)'] += 1
        else:
            modes['not logged'] += 1
    return ', '.join(f'{m}' + (f' x{n}' if len(modes) > 1 else '') for m, n in modes.items())


def reasons(ts):
    c = Counter(r.get('reason', '?') for t in ts for r in t['declines'])
    return ', '.join(f'{k} x{v}' for k, v in sorted(c.items())) or '-'


def agg(ts):
    a = Counter()
    for t in ts:
        a['runs'] += 1
        a['cat_' + t['cat']] += 1
        a['shots'] += t['shots']
        for r in t['rounds']:
            p = 'forced' if r['forced'] else 'fault'
            a[p] += 1
            a[p + '_' + r['outcome']] += 1
            a[p + '_d' + r.get('d', '?')] += 1
        for r in t['declines']:
            why = r.get('reason', '?')
            a['dec'] += 1
            a['dec_pre' if (why.startswith('class_') or why in PRE_HANDSHAKE) else
              'dec_hs' if why in HANDSHAKE else 'dec_after' if why in AFTER_ROUND else 'dec_other'] += 1
        a['acks'] += len(t['acks'])
        a['nacks'] += len(t['nacks'])
        a['vd_ok'] += t['vd_ok']
        a['vd_bad'] += t['vd_bad']
        a['ops1'] += t['ok1']
        a['ops_exp'] += t['iters']
        a['exact_runs'] += 1 if t['exact'] else 0
        a['checkfail'] += len(t['checkfail1'])
        a['rec_ops0'] += t['rec_ops0']
        a['left'] += t['left']
        a['ack_eq_rounds'] += 1 if len(t['acks']) == len(t['rounds']) else 0
    return a


def rnd(a, p):
    n = a[p]
    if not n:
        return '0'
    s = f"{n} ({a[p + '_recovered']} rec / {a[p + '_replay_failed']} rf"
    return s + (f"; d=1 {a[p + '_d1']}, d=0 {a[p + '_d0']})")


def decl(a):
    if not a['dec']:
        return '0'
    parts = []
    for k, lab in (('dec_pre', 'pre-HS'), ('dec_hs', 'HS'), ('dec_after', 'after round'), ('dec_other', 'other')):
        if a[k]:
            parts.append(f'{lab} {a[k]}')
    return f"{a['dec']} ({', '.join(parts)})"


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results')
    root = os.path.normpath(root)
    sets = OrderedDict()
    for top in ('20260924', '20260924_gpudb'):
        for meta in sorted(glob.glob(os.path.join(root, top, '**', '*_meta.txt'), recursive=True)):
            d = os.path.dirname(meta)
            rel = os.path.relpath(d, root)
            sets.setdefault(rel, []).append(os.path.basename(meta)[:-len('_meta.txt')])
    names = sorted(sets, key=lambda s: (ORDER.index(s) if s in ORDER else 99, s))
    out = []
    P = out.append
    P('# GIN GDAKI recovery: recount from the raw trial logs')
    P('')
    P('Generated by `scripts/recount.py` from the per-trial files only (`*_meta.txt`, `*_r0.kv`, `*_r1.kv`,')
    P('`*_r0.log`, `*_r1.log`) under `results/20260924/` and `results/20260924_gpudb/`. The existing')
    P('`trials.csv` / `events.csv` are used only for the cross-check at the end. `results/20260925_n30/` is')
    P('a later, separate experiment and is not counted here.')
    P('')
    P('## Definitions')
    P('')
    P('- **Round**: one completed Prepare -> handshake (REQ/ACK) -> Commit -> replay cycle on the initiator,')
    P('  i.e. one rank-0 `rec ev=` line with `outcome=recovered` or `outcome=replay_failed`. With d = 1 the replay')
    P('  is the put + signal ADD; with d = 0 nothing is replayed.')
    P('  - **after a fault**: the round\'s `fault ev=` record carries a classified error (LOCAL_QP_ERR, RETRY_EXC).')
    P('  - **forced**: a D0 round (`class=FORCED_TEST`): no fault; recovery forced after a completed operation to')
    P('    exercise d = 0. Not "after a detected fault", so always reported separately.')
    P('  - **rec** = recovered (replay succeeded, or d = 0); **rf** = replay failed (the replay met a QP in ERR;')
    P('    the next round reads V again, or the initiator declines if the replay error is not `ncclRemoteError`).')
    P('- **Decline**: a rank-0 `rec ev=` line with `outcome=declined`. **pre-HS**: before any REQ was sent')
    P('  (policy: `class_*`, `retry_exc_peer_dead`; guard: `prepare_failed`). **HS**: REQ sent but the handshake or')
    P('  commit did not complete (`handshake_timeout`, `peer_nack`, `bad_delta`, `commit_failed`, ...). **after round**:')
    P('  Commit done but the replay failed with a non-remote error (`replay_error`); that round is also counted as rf.')
    P('- **Run categories**: *recovered* = both ranks completed every iteration, no decline, >= 1 round after a')
    P('  fault; *forced-only* = completed, only forced rounds; *no fault* = completed, no rounds, no shot fired;')
    P('  *declined* = rank 0 declined, split into *declined as designed* (a pre-HS decline: the policy refuses')
    P('  the class or a dead peer, or v1\'s guard refuses a non-proxy doorbell mode) and *declined after a failed')
    P('  round* (negative controls whose broken resync made the replay fail, as predicted); *flag off* =')
    P('  `NCCL_GIN_FAULT_RECOVERY` off (classifier only, no recovery); *other* = none of these.')
    P('- **Bit-exact**: rank 1 checks every iteration (all 256 KiB equal the pattern and the signal equals')
    P('  base + it + 1) and logs `okit` only if both hold. *r1 ops verified* = rank-1 `okit` count / iterations')
    P('  configured. *run exact* = all iterations verified, `data_check=ok` and final `signal_exact=1`.')
    P('- **V + d = expected**: checked on every responder ACK (`rxrec ... outcome=ack`).')
    P('- **Ops recovered (r0)**: rank-0 iterations that completed through a recovery after a fault')
    P('  (`okit=N rec=1`); a multi-fault run can need two rounds for one operation.')
    P('')

    totals = OrderedDict()
    for s in names:
        stems = sets[s]
        d = os.path.join(root, s)
        if not stems[0].startswith('rec'):
            # not the recovery driver (gin_q4 re-run): count runs only
            c = Counter(kvline(open(os.path.join(d, st + '_meta.txt')).read()).get('fault', '?') for st in stems)
            P(f'## `{s}/` - {DESC.get(s, "")}')
            P('')
            P(f'{len(stems)} runs ({", ".join(f"{k} x{v}" for k, v in sorted(c.items()))}); gin_q4 driver, no recovery,')
            P('so no rounds. Not included in any recovery count.')
            P('')
            continue
        ts = [trial(d, st) for st in stems]
        g = OrderedDict()
        for t in sorted(ts, key=lambda t: (cell(t, s), t['wait'])):
            g.setdefault((cell(t, s), t['wait']), []).append(t)
        A = agg(ts)
        totals[s] = (ts, A, g)
        lo, hi = time_range(d, stems)
        P(f'## `{s}/` - {DESC.get(s, "")}')
        P('')
        if lo:
            P(f'Rank-0 NCCL log timestamps (rain wall clock): {lo} to {hi}.')
            P('')
        if all(t['fault'] == 'lat' for t in ts):
            bad = sum(1 for t in ts if t['lat_bad'] not in ('0',))
            P(f'{len(ts)} no-fault latency runs; rank-1 data check `lat_data_bad=0` in {len(ts) - bad}/{len(ts)}; '
              f'doorbell: {dmode(ts, s)}. No rounds.')
            if bad:
                P('')
                P('Runs without `lat_data_bad=0`: ' + ', '.join(f"`{t['stem']}` ({t['out0']}/{t['out1']})"
                                                              for t in ts if t['lat_bad'] != '0'))
            P('')
            continue
        cats = Counter(t['cat'] for t in ts)
        P(f"{len(ts)} runs: " + ', '.join(f'{k} {v}' for k, v in cats.most_common()) + '.')
        P('')
        P('| cell | wait | doorbell (r0/r1) | runs | shots | rounds after a fault | forced rounds | declines | '
          'runs recovered / forced-only / declined | r1 ops verified | runs exact | V+d=exp (ACKs) | reasons |')
        P('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
        for (k, w), cts in g.items():
            a = agg(cts)
            P(f"| {k} | {w} | {dmode(cts, s)} | {a['runs']} | {a['shots']} | {rnd(a, 'fault')} | {rnd(a, 'forced')} | "
              f"{decl(a)} | {a['cat_recovered']} / {a['cat_forced-only']} / {a['cat_declined']} | "
              f"{a['ops1']}/{a['ops_exp']} | {a['exact_runs']}/{a['runs']} | {a['vd_ok']}/{a['acks']} | {reasons(cts)} |")
        P(f"| **total** | | | **{A['runs']}** | {A['shots']} | **{rnd(A, 'fault')}** | **{rnd(A, 'forced')}** | "
          f"**{decl(A)}** | {A['cat_recovered']} / {A['cat_forced-only']} / {A['cat_declined']} | "
          f"{A['ops1']}/{A['ops_exp']} | {A['exact_runs']}/{A['runs']} | {A['vd_ok']}/{A['acks']} | |")
        P('')
        odd = [t for t in ts if t['cat'] == 'other']
        notes = []
        if odd:
            notes.append('*other* runs: ' + ', '.join(f"`{t['stem']}` (r0 {t['out0']}, r1 {t['out1']}, "
                                                     f"{len(t['rounds'])} rounds)" for t in odd))
        if A['nacks']:
            notes.append(f"responder NACKs: {A['nacks']}")
        if A['checkfail']:
            notes.append(f"rank-1 per-iteration check failures logged: {A['checkfail']} (" + ', '.join(
                f"`{t['stem']}`: {c.get('check')}" for t in ts for c in t['checkfail1']) + ')')
        if A['vd_bad']:
            notes.append(f"ACKs with V + d != expected: {A['vd_bad']}")
        if A['ack_eq_rounds'] != A['runs']:
            notes.append('runs where responder ACKs != initiator rounds: ' + ', '.join(
                f"`{t['stem']}` ({len(t['acks'])} vs {len(t['rounds'])})" for t in ts if len(t['acks']) != len(t['rounds'])))
        if A['left']:
            notes.append(f"processes left after a run: {A['left']}")
        for n in notes:
            P('- ' + n)
        if notes:
            P('')

    # ---------------------------------------------------------------- headline numbers
    def pick(s, pred=lambda t: True):
        ts = [t for t in totals.get(s, ([],))[0] if pred(t)]
        return ts, agg(ts)

    P('## Headline numbers (what the documents should quote)')
    P('')
    P('| scope | runs | recovered runs (exact) | forced-only runs (exact) | declined runs (as designed / after a '
      'failed round) | rounds after a fault (rec / rf) | forced rounds (d=0) | declines | ops recovered (r0) | '
      'r1 ops verified | V+d=exp |')
    P('|---|---|---|---|---|---|---|---|---|---|---|')

    def dkind(t):
        why = [r.get('reason', '') for r in t['declines']]
        if any(w.startswith('class_') or w in PRE_HANDSHAKE for w in why):
            return 'design'
        if any(w in AFTER_ROUND for w in why):
            return 'after'
        return 'other'

    def row(label, ts, a):
        rex = sum(1 for t in ts if t['cat'] == 'recovered' and t['exact'])
        fex = sum(1 for t in ts if t['cat'] == 'forced-only' and t['exact'])
        dts = [t for t in ts if t['cat'] == 'declined']
        dd = sum(1 for t in dts if dkind(t) == 'design')
        da = sum(1 for t in dts if dkind(t) == 'after')
        do = len(dts) - dd - da
        P(f"| {label} | {a['runs']} | {a['cat_recovered']} ({rex}) | {a['cat_forced-only']} ({fex}) | "
          f"{len(dts)} ({dd} / {da}{f'; other {do}' if do else ''}) | "
          f"{a['fault']} ({a['fault_recovered']} / {a['fault_replay_failed']}) | "
          f"{a['forced']} ({a['forced_d0']}) | {decl(a)} | {a['rec_ops0']} | {a['ops1']}/{a['ops_exp']} | "
          f"{a['vd_ok']}/{a['acks']} |")

    main_s, conf_s, gp = '20260924/runs/logs', '20260924/confirm/logs', '20260924_gpudb/runs/logs'
    ts, a = pick(main_s)
    row('CPU doorbell, main matrix (`20260924/runs`), all 64 trials', ts, a)
    ts, a = pick(main_s, lambda t: t['rec'] == '1')
    row('... recovery flag on only (56 trials)', ts, a)
    ts, a = pick(conf_s)
    row('CPU doorbell, confirmation (`20260924/confirm`)', ts, a)
    ts, a = pick('20260924/diag/negative')
    row('CPU doorbell, negative controls (`20260924/diag/negative`)', ts, a)
    ts, a = pick(gp)
    row('GPU doorbell, all v2 trials (`20260924_gpudb/runs`)', ts, a)
    isdiag = lambda t: any(tag in t['stem'] for tag in DIAG)
    isproxy = lambda t: t['db0'] == 'CPU_PROXY'
    ts, a = pick(gp, lambda t: not isdiag(t) and not isproxy(t))
    row('... v2 matrix in GPU mode (no controls, no forced proxy)', ts, a)
    ts, a = pick(gp, lambda t: isproxy(t))
    row('... v2 with the CPU proxy forced (regression)', ts, a)
    ts, a = pick(gp, isdiag)
    row('... v2 negative controls (GPU mode)', ts, a)
    ts, a = pick('20260924_gpudb/v1/logs')
    row('GPU doorbell, committed v1 (`20260924_gpudb/v1`)', ts, a)
    P('')

    # ---------------------------------------------------------------- cross-check with rec_rows.py output
    P('## Cross-check against the generated CSVs')
    P('')
    for csvp, s in (('20260924/trials.csv', main_s), ('20260924/confirm/trials.csv', conf_s),
                    ('20260924_gpudb/trials.csv', gp)):
        p = os.path.join(root, csvp)
        if not os.path.exists(p) or s not in totals:
            continue
        rows = {r['stem']: r for r in csv.DictReader(open(p))}
        mism = []
        n = 0
        for t in totals[s][0]:
            r = rows.get(t['stem'])
            if r is None:
                mism.append(f"`{t['stem']}` missing from CSV")
                continue
            n += 1
            mine = (sum(1 for x in t['rounds'] if x['outcome'] == 'recovered'),
                    sum(1 for x in t['rounds'] if x['outcome'] == 'replay_failed'), len(t['declines']), t['shots'])
            theirs = (int(r['recovered']), int(r['replay_failed']), int(r['declined']), int(r['shots_fired']))
            if mine != theirs:
                mism.append(f"`{t['stem']}` recount {mine} vs CSV {theirs}")
        P(f"- `{csvp}` vs `{s}/`: {n} trials compared (recovered, replay-failed, declined, shots) - "
          + ('all agree.' if not mism else 'MISMATCH: ' + '; '.join(mism)))
    P('')

    # ---------------------------------------------------------------- numbers quoted in the documents
    _, M = pick(main_s)
    _, C = pick(conf_s)
    gts, G = pick(gp)
    _, GM = pick(gp, lambda t: not isdiag(t) and not isproxy(t))
    P('## How numbers quoted in the documents map onto this recount')
    P('')
    P('Main matrix = `20260924/runs/logs/` (CPU-doorbell fallback, v1).')
    P('')
    P('| quoted | meaning under the definitions above | recount |')
    P('|---|---|---|')
    P(f"| 32/32 recovered runs | runs that recovered from injected faults, all data bit-exact and signal exact | "
      f"{M['cat_recovered']} recovered, {sum(1 for t in totals[main_s][0] if t['cat'] == 'recovered' and t['exact'])} exact |")
    P(f"| 38/38 recovered runs | the 32 above + the {M['cat_forced-only']} forced-only (D0) runs | "
      f"{M['cat_recovered'] + M['cat_forced-only']} |")
    P(f"| 130 recovery rounds | all rounds: after a fault + forced | {M['fault'] + M['forced']} "
      f"({M['fault']} + {M['forced']}) |")
    P(f"| 112 rounds after a fault | rounds after a fault, recovered + replay failed | {M['fault']} "
      f"({M['fault_recovered']} + {M['fault_replay_failed']}) |")
    P(f"| 20 rounds hit by a second fault | replay-failed rounds after a fault | {M['fault_replay_failed']} |")
    P(f"| 18 forced d = 0 rounds | forced rounds | {M['forced']} (d=0 in {M['forced_d0']}) |")
    P(f"| 110 recovery rounds | rounds with outcome=recovered only (after a fault + forced); excludes the "
      f"{M['fault_replay_failed']} replay-failed rounds | {M['fault_recovered'] + M['forced_recovered']} "
      f"({M['fault_recovered']} + {M['forced_recovered']}) |")
    P(f"| confirmation: 22 rounds | recovered rounds after a fault in `confirm/` (the timing sample) | "
      f"{C['fault_recovered']} (of {C['fault']} rounds after a fault; + {C['forced']} forced) |")
    P(f"| GPU doorbell: 62 recovery rounds | all rounds in `20260924_gpudb/runs/`, incl. forced D0, the "
      f"forced-proxy regression and the two negative controls | {G['fault'] + G['forced']} "
      f"({G['fault']} after a fault + {G['forced']} forced) |")
    P(f"| GPU doorbell: 10 declines | declines in `20260924_gpudb/runs/` | {G['dec']} ({G['dec_pre']} policy: F2 "
      f"REM_ACCESS / F4 peer dead; {G['dec_after']} after a failed round: `keep_gpu_pi`) |")
    P(f"| GPU doorbell, v2 matrix proper (GPU mode, no controls) | - | {GM['cat_recovered']} recovered runs, "
      f"{GM['fault']} rounds after a fault ({GM['fault_recovered']} + {GM['fault_replay_failed']} rf), "
      f"{GM['forced']} forced |")
    P('')

    # ---------------------------------------------------------------- limits of the raw data
    P('## What the raw data cannot settle')
    P('')
    rng = [time_range(os.path.join(root, s), [t['stem'] for t in totals[s][0]]) for s in totals
           if s.startswith('20260924/')]
    lo = min(r[0] for r in rng if r[0])
    hi = max(r[1] for r in rng if r[1])
    P('- **Doorbell mode of the 2026-09-24 CPU-doorbell sets.** Those logs carry no doorbell-mode line and no')
    P('  proxy-thread probe (both were added for the GPU-doorbell re-run). Two indirect facts support "CPU-doorbell')
    P(f'  fallback": their rank-0 timestamps span {lo[11:]} to {hi[11:]}, after the second temporary override window')
    P('  (12:00-12:06, driver restored; `harness/gpu-initiated/gpu_doorbell/README.md`) and before the override')
    P('  became permanent at 13:53; and v1 declines at Prepare in any non-proxy mode (`20260924_gpudb/v1/`:')
    P('  "doorbell mode is not CPU proxy"), so every v1 run that completed a round ran with the CPU proxy. Runs')
    P('  that never reached Prepare (none, F2, F4, flag off, lat) are covered only by the timestamps.')
    P('- **Which build ran which batch** in `20260924/`: the per-trial files record no library or driver md5')
    P('  (`20260924_gpudb/` records the bundle name only). The batch-to-build mapping in the README comes from the')
    P('  run notes, not from these files.')
    P('- **Bit-exactness on rank 1 after an F4 kill or a decline**: rank 1 checks only the iterations it completed')
    P('  before it was killed (F4) or released its waiter (declines); "r1 ops verified" counts those. No check exists')
    P('  for operations after that point, by design.')
    ALL = agg([t for s in totals for t in totals[s][0]])
    P(f"- **d = 0 after a real fault**: occurred in {ALL['fault_d0']} of the {ALL['fault']} rounds after a fault in all")
    P('  sets above; d = 0 is covered only by the forced D0 rounds, which are not rounds after a detected fault.')
    P('- **Operations vs rounds in multi-fault runs**: the logs give rounds and recovered operations (rank-0')
    P('  `okit ... rec=1`), not which shot caused which round; that mapping (rec_rows.py) is inferred from timestamps.')
    P('')
    sys.stdout.write('\n'.join(out) + '\n')


if __name__ == '__main__':
    main()
