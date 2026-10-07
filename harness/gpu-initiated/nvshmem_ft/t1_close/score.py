#!/usr/bin/env python3
"""score.py <results dir> - apply the frozen acceptance rules of predictions.csv (tag
prereg/nvshmem-t1-close-v1) to every trial under <results dir>.

Trials are read with ../scripts/t1/rows_t1.py (parse_trial; trials and rounds) and, for the FT v2.2
cells, ../scripts/v2/rows_v2.py (parse_trial). A cell is the TAG part of the trial tag. Writes
<results dir>/SCORE.md and <results dir>/trials_scored.csv.

Exclusion (EXPERIMENT.md section 8): a trial is counted apart, not scored, when it is void, when the
fault was not applied (the per-row validity rule) or when its build md5 differs from the study build
(t1 cells), from the v2.2 latency baseline (cells *_v22off) or from the FT v2.2 bundle (R13, R14).
"""
import csv, glob, os, re, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts', 't1'))
import rows_t1  # noqa: E402
sys.path.insert(0, os.path.join(HERE, '..', 'scripts', 'v2'))
import rows_v2  # noqa: E402

# deployed md5 (12-character prefixes, as the runners write them): t1_close/deploy.sh, EXPERIMENT.md 12
STUDY = ('b4b4115ed0e5', '3d63030802d5', '278089a4eeda')     # transport, host, nvt1_drv (build b2, DEVIATIONS 1)
V22LAT = ('6913dea69930', '54a9d23acf0e', 'f1d4d304bd29')    # v22ref libraries, nvt1v22_drv
V22FT = ('6913dea6', '54a9d23a')                             # FT v2.2 bundle (lib_rain, host_rain)

PLANNED = {'N1': 10, 'C4': 5, 'R1': 5, 'R3': 5, 'R4': 5, 'R5': 5, 'R6': 5, 'R7': 5, 'R8': 5, 'C1': 5,
           'N2': 10, 'N3': 10, 'N4': 10, 'C2': 5, 'C3': 5, 'R12': 40, 'R13': 5, 'R14': 5,
           'R11': 5, 'N6': 10, 'N7': 10, 'N8': 10, 'R9': 5, 'R10': 5, 'N5': 10}
TAGS = {'N1': 'n1_round', 'C4': 'c4_sleep', 'R1': 'r1_none', 'R3': 'r3_inflight', 'R4': 'r4_f3', 'R5': 'r5_x5',
        'R6': 'r6_mt', 'R7': 'r7_f2a', 'R8': 'r8_f4', 'C1': 'c1_t1off', 'N2': 'n2_fetch_f3',
        'N3': 'n3_fetch_gap15', 'N4': 'n4_fetch_gap0', 'C2': 'c2_fetch_old', 'C3': 'c3_fetch_exec',
        'R13': 'r13_v22f3', 'R14': 'r14_v22f4', 'R11': 'r11_fill', 'N6': 'n6_fill32', 'N7': 'n7_atexit',
        'N8': 'n8_mqp', 'R9': 'r9_sock', 'R10': 'r10_sock1', 'N5': 'n5_sockA'}
LATCELLS = ['lat4k_v22off', 'lat4k_t1off', 'lat4k_ring', 'lat4k_t1on',
            'lat256k_v22off', 'lat256k_t1off', 'lat256k_ring', 'lat256k_t1on']
NEED = {i: (8 if i.startswith('N') else 4) for i in PLANNED}
LABEL = {  # plain Korean names; ids go in parentheses
    'N1': '로컬 QP 오류, 새 빌드 복구 시간', 'C4': '같은 셀, 옛 대기 방식', 'R1': '장애 없음',
    'R3': '진행 중 로컬 QP 오류', 'R4': '상대 QP 오류', 'R5': '로컬 QP 오류 다섯 번', 'R6': '4 CTA, RC QP 1개',
    'R7': '앱의 heap 밖 쓰기, 거절', 'R8': '상대 kill, 거절', 'C1': '투명 스위치 끔, 로컬 QP 오류',
    'N2': '상대 QP 오류 + 매 반복 fetch', 'N3': '연산 사이 로컬 QP 오류 + 매 반복 fetch',
    'N4': '진행 중 로컬 QP 오류 + 매 반복 fetch', 'C2': '상대 QP 오류 + fetch, 옛 fetch 규칙',
    'C3': '진행 중 로컬 QP 오류 + fetch, 실행된 fetch도 다시 보냄', 'R12': '장애 없는 지연 8칸',
    'R13': 'FT v2.2, 상대 QP 오류 복구', 'R14': 'FT v2.2, 상대 kill 거절', 'R11': '꽉 찬 GPU, 기본 연결',
    'N6': '꽉 찬 GPU, 연결 32개', 'N7': 'finalize 없는 종료', 'N8': '상대당 RC QP 4개',
    'R9': '소켓 양방향 끊김', 'R10': '소켓 끊김 뒤 로컬 QP 오류', 'N5': '받는 방향만 끊김 뒤 로컬 QP 오류'}


def num(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def inum(x, d=None):
    v = num(x)
    return int(v) if v is not None else d


def load(rdir):
    t1, rounds, v2 = [], [], []
    for meta in sorted(glob.glob(os.path.join(rdir, '**', '*.meta'), recursive=True)):
        txt = open(meta, errors='replace').read()
        if 'lib_rain=' in txt:
            row = rows_v2.parse_trial(meta)
            row['_path'] = os.path.relpath(meta, rdir)
            v2.append(row)
        else:
            row, rr = rows_t1.parse_trial(meta)
            row['_path'] = os.path.relpath(meta, rdir)
            t1.append(row)
            rounds.extend(rr)
    return t1, rounds, v2


def cell(rows, tag):
    pat = re.compile(r'_%s_t\d+$' % re.escape(tag))
    return [r for r in rows if pat.search(r['tag'])]


def init_rounds(rounds, tag):
    return [x for x in rounds if x['tag'] == tag and x['role'] == 'initiator']


# ---- validity ---------------------------------------------------------------------------------
def build_ok_t1(r, lat_v22=False):
    want = V22LAT if lat_v22 else STUDY
    return (r.get('md5_transport'), r.get('md5_host'), r.get('md5_bin')) == want


def v_f1(r):
    return r['outcome'] != 'void' and inum(r.get('shots0'), 0) >= 1 and inum(r.get('n_records0'), 0) >= 1


def v_f3(r):
    return r['outcome'] != 'void' and inum(r.get('shots1'), 0) >= 1 and inum(r.get('n_records0'), 0) >= 1


def v_any(r):
    return r['outcome'] != 'void'


def sock_ok(r):
    return r.get('sock_port', '') not in ('', 'none')


VALID = {
    'N1': v_f1, 'C4': v_f1, 'N3': v_f1, 'N4': v_f1, 'C3': v_f1, 'N7': v_f1, 'R3': v_f1, 'R6': v_f1, 'C1': v_f1,
    'N2': v_f3, 'C2': v_f3, 'R4': v_f3,
    'N5': lambda r: v_any(r) and sock_ok(r) and inum(r.get('shots0'), 0) >= 1 and inum(r.get('n_records0'), 0) >= 1,
    'N6': lambda r: v_any(r) and r.get('fill_ctas', '') != '' and inum(r.get('shots0'), 0) >= 1 and inum(r.get('n_records0'), 0) >= 1,
    'R11': lambda r: v_any(r) and r.get('fill_ctas', '') != '' and inum(r.get('shots0'), 0) >= 1 and inum(r.get('n_records0'), 0) >= 1,
    'N8': lambda r: v_f1(r) and r.get('rc_per_pe') == '4',
    'R1': v_any, 'R7': v_any,
    'R5': lambda r: v_any(r) and inum(r.get('shots0'), 0) == 5 and inum(r.get('n_records0'), 0) >= 1,
    'R8': lambda r: v_any(r) and r.get('kill_mono1_s', '') != '' and inum(r.get('n_records0'), 0) >= 1,
    'R9': lambda r: v_any(r) and sock_ok(r),
    'R10': lambda r: v_any(r) and sock_ok(r) and inum(r.get('shots0'), 0) >= 1 and inum(r.get('n_records0'), 0) >= 1,
}


# ---- per-trial conditions ---------------------------------------------------------------------
def tr(r):
    return r['outcome'] == 'transparent'


def ri(r):
    return inum(r.get('rounds_init'), -1)


def reason(r):
    return r.get('decline_reason0', '') or ''


def fin_ok(r):
    return r.get('finalize_ms0', '') != '' and num(r.get('finalize_ms0'), 1e9) <= 1000


COND = {
    'N1': lambda r: tr(r) and ri(r) == 1,
    'C4': lambda r: tr(r) and ri(r) == 1,
    'N2': lambda r: tr(r) and ri(r) == 1 and inum(r.get('t1_fetch_exec0'), -9) == 0 and inum(r.get('t1_fetch_reposted0'), -9) >= 1,
    'N3': lambda r: tr(r) and ri(r) == 1 and inum(r.get('t1_fetch_exec0'), -9) == 0,
    'N4': lambda r: (tr(r) and inum(r.get('t1_fetch_exec0'), -9) == 0 and inum(r.get('fetch_counter1')) == inum(r.get('fetch_fetches')))
    or (r['outcome'] == 'declined' and inum(r.get('t1_fetch_exec0'), -9) >= 1
        and inum(r.get('fetch_counter1'), -9) == inum(r.get('fetch_exact'), -99) + 1 and 'executed by the responder' in reason(r)),
    'C2': lambda r: r['outcome'] == 'declined' and 'cannot be re-posted' in reason(r) and inum(r.get('fetch_counter1'), -9) == inum(r.get('fetch_exact'), -99),
    'N5': lambda r: tr(r) and inum(r.get('sock_lost0'), 0) >= 1 and inum(r.get('sock_back0'), 0) >= 1 and inum(r.get('sock_back1'), 0) >= 1 and ri(r) == 1 and r.get('iptables_left') == '0',
    'N7': lambda r: tr(r) and ri(r) == 1 and r.get('exit_mono0', '') != '' and r.get('exit_mono1', '') != ''
    and num(r.get('atexit_mono0'), 1e18) - num(r.get('exit_mono0'), 0) <= 5000 and num(r.get('atexit_mono1'), 1e18) - num(r.get('exit_mono1'), 0) <= 5000
    and str(r.get('atexit_detached0')) == '0' and str(r.get('atexit_detached1')) == '0',
    'R1': lambda r: tr(r) and ri(r) == 0,
    'R3': lambda r: tr(r) and ri(r) == 1,
    'R4': lambda r: tr(r) and ri(r) == 1,
    'R5': lambda r: tr(r) and ri(r) == 5,
    'R6': lambda r: tr(r) and ri(r) == 1,
    'R7': lambda r: r['outcome'] == 'declined' and ri(r) == 0 and fin_ok(r),
    'R8': lambda r: r['outcome'] == 'declined' and fin_ok(r),
    'R9': lambda r: tr(r) and ri(r) == 0 and inum(r.get('sock_lost0'), 0) >= 1 and inum(r.get('sock_back0'), 0) >= 1 and inum(r.get('sock_back1'), 0) >= 1 and r.get('iptables_left') == '0',
    'R10': lambda r: tr(r) and inum(r.get('sock_lost0'), 0) >= 1 and ri(r) == 1 and r.get('iptables_left') == '0',
    'R11': lambda r: r['outcome'] == 'declined' and 'did not complete within the bound' in reason(r)
    and num(r.get('decline_mono0'), 1e18) - num(r.get('first_record_mono0'), 0) <= 3000 and num(r.get('finalize_ms0'), 1e9) <= 1000,
    'C1': lambda r: inum(r.get('status_bad'), 0) >= 1 and ri(r) == 0 and r['outcome'] != 'transparent',
}


def score_cell(pid, rows, rounds):
    """-> dict(planned, found, valid, apart(list), hits, missed(list), verdict, note, rowsout)"""
    found = cell(rows, TAGS[pid])
    valid, apart, out = [], [], []
    for r in found:
        why = ''
        if r['outcome'] == 'void':
            why = 'void'
        elif not build_ok_t1(r):
            why = 'build md5'
        elif not VALID[pid](r):
            why = 'fault not applied'
        out.append((r, why))
        (apart if why else valid).append((r, why) if why else r)
    res = {'planned': PLANNED[pid], 'found': len(found), 'valid': len(valid), 'apart': apart, 'note': ''}
    ok_rows, bad_rows = [], []
    if pid == 'N8':
        for r in valid:
            rr = init_rounds(rounds, r['tag'])
            (ok_rows if COND_N8(r, rr) else bad_rows).append(r)
    elif pid == 'N6':
        nt = sum(1 for r in valid if tr(r))
        nd = sum(1 for r in valid if r['outcome'] == 'declined' and 'did not complete within the bound' in reason(r))
        ok_rows = [r for r in valid if tr(r)]
        bad_rows = [r for r in valid if not tr(r)]
        res['note'] = f'투명 {nt}, 복사 상한 거절 {nd}, 그 밖 {len(valid) - nt - nd}'
        res['hits'] = nt
        res['missed'] = [r['tag'] for r in bad_rows]
        if len(valid) < NEED[pid]:
            res['verdict'] = '자료 부족'
        elif nt >= 8:
            res['verdict'] = '맞음'
        elif nd >= 8:
            res['verdict'] = '틀림'
        else:
            res['verdict'] = '판정 불가'
        res['rowsout'] = out
        return res
    elif pid == 'C3':
        a = [r for r in valid if inum(r.get('t1_fetch_exec0'), -9) >= 1]
        b = [r for r in valid if inum(r.get('t1_fetch_exec0'), -9) == 0]
        other = [r for r in valid if inum(r.get('t1_fetch_exec0'), -9) not in (0,) and inum(r.get('t1_fetch_exec0'), -9) < 1]
        aok = [r for r in a if r['outcome'] == 'failed' and inum(r.get('fetch_counter1'), -9) == inum(r.get('fetch_fetches'), -99) + 1
               and str(r.get('sig_exact')) == '1' and ri(r) == 1]
        bok = [r for r in b if tr(r)]
        ok_rows = aok + bok
        bad_rows = [r for r in a if r not in aok] + [r for r in b if r not in bok] + other
        pa = '자료 없음' if not a else ('맞음' if len(aok) == len(a) else '틀림')
        pb = '맞음' if (len(bok) == len(b) and not other) else '틀림'
        res['note'] = f'실행된 fetch가 있는 시행 {len(a)}회(두 번 적용 {len(aok)}), 없는 시행 {len(b)}회(투명 {len(bok)}), 실행 수 기록 없음 {len(other)}회. A부분 {pa}, B부분 {pb}'
        res['hits'] = len(ok_rows)
        res['missed'] = [r['tag'] for r in bad_rows]
        res['verdict'] = '자료 부족' if len(valid) < NEED[pid] else ('맞음' if pb == '맞음' and pa in ('맞음', '자료 없음') else '틀림')
        res['rowsout'] = out
        return res
    else:
        for r in valid:
            (ok_rows if COND[pid](r) else bad_rows).append(r)
    res['hits'] = len(ok_rows)
    res['missed'] = [r['tag'] for r in bad_rows]
    verdict = len(valid) >= NEED[pid] and not bad_rows
    if pid in ('N1', 'C4'):
        tot = [num(x['total_ms']) for r in valid for x in init_rounds(rounds, r['tag']) if num(x['total_ms']) is not None]
        if tot:
            med, mx = statistics.median(tot), max(tot)
            res['note'] = f'시작 쪽 라운드 {len(tot)}개의 total_ms: 중앙값 {med:.2f} ms, 범위 {min(tot):.2f}–{mx:.2f} ms'
            verdict = verdict and ((med <= 5.5 and mx <= 10.0) if pid == 'N1' else med >= 6.5)
        else:
            verdict = False
            res['note'] = '시작 쪽 라운드 없음'
    if pid == 'N4':
        nd = sum(1 for r in valid if r['outcome'] == 'declined')
        res['note'] = f'거절 {nd}/{len(valid)} (보고만, 채점 안 함), failed {sum(1 for r in valid if r["outcome"] == "failed")}'
    if len(valid) < NEED[pid]:
        res['verdict'] = '자료 부족'
    else:
        res['verdict'] = '맞음' if verdict else '틀림'
    res['rowsout'] = out
    return res


def COND_N8(r, rr):
    return tr(r) and ri(r) == 1 and len(rr) >= 1 and all(inum(x.get('nqps'), -1) == 4 for x in rr)


def score_lat(rows):
    best, runs, apart, out = {}, {}, [], []
    for c in LATCELLS:
        found = cell(rows, c)
        ok = []
        for r in found:
            vals = [v for v in (r.get('lat_p50') or '').split(';') if v]
            why = ''
            if r['outcome'] == 'void' or len(vals) != 5:
                why = 'void or not 5 reps'
            elif not build_ok_t1(r, lat_v22=c.endswith('v22off')):
                why = 'build md5'
            out.append((r, why))
            if why:
                apart.append((r, why))
            else:
                ok.append(statistics.median(float(v) for v in vals))
        runs[c] = ok
        best[c] = min(ok) if len(ok) >= 4 else None
    res = {'planned': 40, 'found': sum(len(cell(rows, c)) for c in LATCELLS), 'valid': sum(len(v) for v in runs.values()),
           'apart': apart, 'rowsout': out}
    if any(best[c] is None for c in LATCELLS):
        res.update(verdict='자료 부족', hits=0, missed=[], note='유효 실행이 4회 미만인 칸이 있음')
        return res
    d1 = best['lat4k_t1on'] - best['lat4k_v22off']
    d2 = best['lat4k_t1off'] - best['lat4k_v22off']
    d3 = best['lat256k_t1on'] - best['lat256k_v22off']
    conds = [1.0 <= d1 <= 2.6, 0.2 <= d2 <= 1.2, 0.8 <= d3 <= 2.4]
    res.update(hits=sum(conds), missed=[n for n, c in zip(('4KiB t1on', '4KiB t1off', '256KiB t1on'), conds) if not c],
               verdict='맞음' if all(conds) else '틀림',
               note=(f'best-run p50(µs): ' + ', '.join(f'{c} {best[c]:.3f}' for c in LATCELLS)
                     + f'. 차이: 4 KiB 켬 {d1:+.3f}, 4 KiB 끔 {d2:+.3f}, 256 KiB 켬 {d3:+.3f}'))
    res['best'] = best
    return res


def score_v2(pid, rows):
    found = cell(rows, TAGS[pid])
    valid, apart, out = [], [], []
    for r in found:
        why = ''
        if not (r.get('ft_enabled_line') in (1, '1') and str(r.get('lib_rain', '')).startswith(V22FT[0])
                and str(r.get('host_rain', '')).startswith(V22FT[1])):
            why = 'not enabled or build md5'
        out.append((r, why))
        (apart if why else valid).append((r, why) if why else r)
    if pid == 'R13':
        c = lambda r: (str(r.get('pe0_rc')) == '0' and str(r.get('pe1_rc')) == '0' and r.get('fr_class') == 'RETRY_EXC'
                       and r.get('fr_fp') == '12/0x81' and inum(r.get('s0_rec_rounds'), 0) >= 1 and str(r.get('s0_ok_iters')) == '200'
                       and str(r.get('s1_ok_iters')) == '200' and r.get('s1_final_sig') == r.get('s1_expected_sig')
                       and str(r.get('pe1_notok_lines')) == '0' and str(r.get('td0_returned')) == '1')
    else:
        c = lambda r: (r.get('fr_class') == 'RETRY_EXC' and str(r.get('s0_declined')) == '1' and 'peer dead' in (r.get('decline_reason') or '')
                       and str(r.get('td0_returned')) == '1' and num(r.get('td0_finalize_ms'), 1e9) <= 1000)
    okr = [r for r in valid if c(r)]
    bad = [r for r in valid if not c(r)]
    return {'planned': PLANNED[pid], 'found': len(found), 'valid': len(valid), 'apart': apart, 'hits': len(okr),
            'missed': [r['tag'] for r in bad], 'note': '',
            'verdict': '자료 부족' if len(valid) < NEED[pid] else ('맞음' if not bad else '틀림'), 'rowsout': out}


def main():
    rdir = os.path.abspath(sys.argv[1])
    t1, rounds, v2 = load(rdir)
    order = ['N1', 'C4', 'N2', 'N3', 'N4', 'C2', 'C3', 'N5', 'N6', 'N7', 'N8', 'R1', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8',
             'R9', 'R10', 'R11', 'R12', 'R13', 'R14', 'C1']
    results = {}
    for pid in order:
        if pid == 'R12':
            results[pid] = score_lat(t1)
        elif pid in ('R13', 'R14'):
            results[pid] = score_v2(pid, v2)
        else:
            results[pid] = score_cell(pid, t1, rounds)
    # trials_scored.csv
    cols = ['id', 'tag', 'path', 'counted_apart', 'outcome', 'pe0_rc', 'pe1_rc', 'rounds_init', 'status_bad',
            'decline_reason0', 't1_fetch_cr0', 't1_fetch_exec0', 't1_fetch_reposted0', 'fetch_fetches', 'fetch_exact',
            'fetch_counter1', 'sig_exact', 'sock_lost0', 'sock_back0', 'sock_back1', 'iptables_left', 'fill_ctas',
            'decline_minus_record_ms', 'finalize_ms0', 'exit_mono0', 'atexit_mono0', 'atexit_detached0', 'exit_mono1',
            'atexit_mono1', 'atexit_detached1', 'init_round_total_ms', 'init_round_nqps', 'lat_p50',
            'md5_transport', 'md5_host', 'md5_bin', 'v2_fr_class', 'v2_s0_rec_rounds', 'v2_s0_ok_iters',
            'v2_s0_declined', 'v2_decline_reason', 'v2_td0_finalize_ms']
    with open(os.path.join(rdir, 'trials_scored.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for pid in order:
            for r, why in results[pid]['rowsout']:
                d = {'id': pid, 'tag': r.get('tag'), 'path': r.get('_path'), 'counted_apart': why}
                if pid in ('R13', 'R14'):
                    d.update(outcome='', pe0_rc=r.get('pe0_rc'), pe1_rc=r.get('pe1_rc'), v2_fr_class=r.get('fr_class'),
                             v2_s0_rec_rounds=r.get('s0_rec_rounds'), v2_s0_ok_iters=r.get('s0_ok_iters'),
                             v2_s0_declined=r.get('s0_declined'), v2_decline_reason=r.get('decline_reason'),
                             v2_td0_finalize_ms=r.get('td0_finalize_ms'), md5_transport=r.get('lib_rain'),
                             md5_host=r.get('host_rain'), md5_bin=r.get('md5_rain'))
                else:
                    for k in cols:
                        if k in r:
                            d[k] = r[k]
                    dm, fm = num(r.get('decline_mono0')), num(r.get('first_record_mono0'))
                    d['decline_minus_record_ms'] = '%.1f' % (dm - fm) if dm is not None and fm is not None else ''
                    rr = init_rounds(rounds, r['tag'])
                    d['init_round_total_ms'] = ';'.join(x['total_ms'] for x in rr)
                    d['init_round_nqps'] = ';'.join(x.get('nqps', '') for x in rr)
                w.writerow({k: d.get(k, '') for k in cols})
    # SCORE.md
    L = ['# t1_close 채점', '',
         f'원자료: `{os.path.basename(rdir)}/` 아래 시행 {len(t1) + len(v2)}개(`.meta` 기준). 규칙: [predictions.csv](../../predictions.csv)'
         ' (태그 `prereg/nvshmem-t1-close-v1`). 시행별 값: [trials_scored.csv](trials_scored.csv).', '',
         '| 예측 | 계획 n | 찾은 시행 | 유효 n | 맞은 시행 | 판정 | 따로 센 시행 | 놓친 시행 | 메모 |', '|---|--:|--:|--:|--:|---|---|---|---|']
    for pid in order:
        x = results[pid]
        apart = ', '.join(f'{r.get("tag")}({why})' for r, why in x['apart']) or '-'
        missed = ', '.join(x['missed']) or '-'
        L.append(f'| {LABEL[pid]} ({pid}) | {x["planned"]} | {x["found"]} | {x["valid"]} | {x["hits"]} | {x["verdict"]} | {apart} | {missed} | {x.get("note", "")} |')
    L += ['', '- 지연(R12)의 "맞은 시행"은 세 차이 조건 가운데 맞은 수다. 꽉 찬 GPU 연결 32개(N6)는 투명 시행 수다.',
          '- "따로 센 시행"은 void, 장애 미적용, 빌드 md5 불일치다(EXPERIMENT.md 8절). 계획 n과 찾은 시행의 차이는 실행되지 않은 시행이다.']
    open(os.path.join(rdir, 'SCORE.md'), 'w').write('\n'.join(L) + '\n')
    for pid in order:
        x = results[pid]
        print(f'{pid:4s} planned={x["planned"]:2d} found={x["found"]:2d} valid={x["valid"]:2d} hits={x["hits"]:2d} {x["verdict"]}  {x.get("note", "")}')


if __name__ == '__main__':
    main()
