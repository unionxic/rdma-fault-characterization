#!/usr/bin/env python3
"""score.py <results dir> - apply the frozen acceptance rules of predictions.csv (tag
prereg/nvshmem-t1-380-v1) to every trial under <results dir>.

Trials are read with ../scripts/t1/rows_t1.py (parse_trial). A cell is the TAG part of the trial tag.
Writes <results dir>/SCORE.md and <results dir>/trials_scored.csv.

Counted apart (EXPERIMENT.md section 8), not scored: void trials, trials whose fault was not applied (the
row's validity rule), and trials whose build md5 differs from the cell's build group (EXPERIMENT.md
section 3 and the deployed md5 of section 12).
"""
import csv, glob, os, re, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts', 't1'))
import rows_t1  # noqa: E402

# build groups: (md5_transport, md5_host, md5_bin), 12-character prefixes as the runner writes them
GROUP = {
    'P': ('d6ae3699f95b', '825443f85d59', 'e309d5164c01'),   # port, ~/gi-bundle/nvshmem_t1_380 (deploy 2026-10-08)
    'D': ('b4b4115ed0e5', '3d63030802d5', '278089a4eeda'),   # devel b2, ~/gi-bundle/nvshmem_t1close_b2
    'V': ('6913dea69930', '54a9d23acf0e', 'f1d4d304bd29'),   # devel v2.2 baseline, nvshmem_t1close_b2/v22ref
    'S': ('4aa4dda2a490', '80eea986b645', '4dae151fdc76'),   # unmodified v3.8.0-0 + nvt1st_drv, nvshmem_t1_380/stock380
}
CELLS = {  # id -> (TAG, build group, planned n)
    'R1': ('r1_none', 'P', 5), 'R2': ('p_inflight', 'P', 10), 'R3': ('d_inflight', 'D', 10),
    'R4': ('r4_f3', 'P', 5), 'R5': ('r5_fetch_f3', 'P', 5), 'R6': ('r6_fetch_gap15', 'P', 5),
    'R7': ('r7_fetch_gap0', 'P', 5), 'R8': ('r8_f2a', 'P', 5), 'R9': ('r9_f4', 'P', 5),
    'R10': ('r10_atexit', 'P', 5), 'R11': ('r11_mqp', 'P', 5), 'C1': ('c1_t1off', 'P', 5),
    'N2': ('n2_cpuproxy', 'P', 10), 'N3': ('n2_cpuproxy', 'P', 10),
}
LAT = {'stock': 'S', 't1off': 'P', 't1on': 'P', 'dv22off': 'V', 'dt1off': 'D', 'dt1on': 'D'}
LABEL = {
    'R1': '장애 없음', 'R2': '진행 중 로컬 QP 오류, 옮긴 빌드', 'R3': '진행 중 로컬 QP 오류, devel 빌드',
    'N1': '진행 중 로컬 QP 오류 복구 시간, 옮긴 빌드 대 devel', 'R4': '상대 QP 오류',
    'R5': '상대 QP 오류 + 매 반복 fetch', 'R6': '연산 사이 로컬 QP 오류 + 매 반복 fetch',
    'R7': '진행 중 로컬 QP 오류 + 매 반복 fetch', 'R8': '앱의 heap 밖 쓰기, 거절', 'R9': '상대 kill, 거절',
    'R10': 'finalize 없는 종료', 'R11': '상대당 RC QP 4개', 'C1': '투명 스위치 끔',
    'N2': 'CPU 프록시, 투명 복구 거부', 'N3': 'CPU 프록시, 오류 완료가 장치에 오지 않음',
    'N4': '장애 없는 지연, 공식 3.8.0 그대로 대 devel v2.2 기준', 'N5': '장애 없는 지연, 옮긴 빌드 대 devel 빌드',
    'R12': '옮긴 빌드의 지연 비용, 공식 3.8.0 그대로 대비'}
ORDER = ['R1', 'R2', 'R3', 'N1', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9', 'R10', 'R11', 'C1', 'N2', 'N3', 'N4', 'N5', 'R12']


def num(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def inum(x, d=None):
    v = num(x)
    return int(v) if v is not None else d


def load(rdir):
    t, rr = [], []
    for meta in sorted(glob.glob(os.path.join(rdir, '**', '*.meta'), recursive=True)):
        row, rounds = rows_t1.parse_trial(meta)
        row['_path'] = os.path.relpath(meta, rdir)
        t.append(row)
        rr.extend(rounds)
    return t, rr


def cell(rows, tag):
    pat = re.compile(r'_%s_t\d+$' % re.escape(tag))
    return [r for r in rows if pat.search(r['tag'])]


def init_rounds(rounds, tag):
    return [x for x in rounds if x['tag'] == tag and x['role'] == 'initiator']


def build_ok(r, g):
    return (r.get('md5_transport'), r.get('md5_host'), r.get('md5_bin')) == GROUP[g]


def tr(r):
    return r['outcome'] == 'transparent'


def ri(r):
    return inum(r.get('rounds_init'), -1)


def f1(r):
    return inum(r.get('shots0'), 0) >= 1 and inum(r.get('n_records0'), 0) >= 1


def f3(r):
    return inum(r.get('shots1'), 0) >= 1 and inum(r.get('n_records0'), 0) >= 1


def fin_ok(r):
    return r.get('finalize_ms0', '') != '' and num(r.get('finalize_ms0'), 1e9) <= 1000


VALID = {  # beyond "build group ok and outcome != void"
    'R1': lambda r: True, 'R2': f1, 'R3': f1, 'R4': f3, 'R5': f3, 'R6': f1, 'R7': f1, 'R8': lambda r: True,
    'R9': lambda r: r.get('kill_mono1_s', '') != '' and inum(r.get('n_records0'), 0) >= 1,
    'R10': f1, 'R11': lambda r: f1(r) and r.get('rc_per_pe') == '4', 'C1': f1,
    'N2': lambda r: inum(r.get('shots0'), 0) >= 1 and r.get('ft_handler0') == 'CPU-proxy',
    'N3': lambda r: inum(r.get('shots0'), 0) >= 1 and r.get('ft_handler0') == 'CPU-proxy',
}
COND = {
    'R1': lambda r, rr: tr(r) and ri(r) == 0,
    'R2': lambda r, rr: tr(r) and ri(r) == 1,
    'R3': lambda r, rr: tr(r) and ri(r) == 1,
    'R4': lambda r, rr: tr(r) and ri(r) == 1,
    'R5': lambda r, rr: tr(r) and ri(r) == 1 and inum(r.get('t1_fetch_exec0'), -9) == 0 and inum(r.get('t1_fetch_reposted0'), -9) >= 1,
    'R6': lambda r, rr: tr(r) and ri(r) == 1 and inum(r.get('t1_fetch_exec0'), -9) == 0,
    'R7': lambda r, rr: (tr(r) and inum(r.get('t1_fetch_exec0'), -9) == 0 and inum(r.get('fetch_counter1')) == inum(r.get('fetch_fetches')))
    or (r['outcome'] == 'declined' and inum(r.get('t1_fetch_exec0'), -9) >= 1
        and inum(r.get('fetch_counter1'), -9) == inum(r.get('fetch_exact'), -99) + 1
        and 'executed by the responder' in (r.get('decline_reason0') or '')),
    'R8': lambda r, rr: r['outcome'] == 'declined' and ri(r) == 0 and fin_ok(r),
    'R9': lambda r, rr: r['outcome'] == 'declined' and fin_ok(r),
    'R10': lambda r, rr: tr(r) and ri(r) == 1 and r.get('exit_mono0', '') != '' and r.get('exit_mono1', '') != ''
    and num(r.get('atexit_mono0'), 1e18) - num(r.get('exit_mono0'), 0) <= 5000
    and num(r.get('atexit_mono1'), 1e18) - num(r.get('exit_mono1'), 0) <= 5000
    and str(r.get('atexit_detached0')) == '0' and str(r.get('atexit_detached1')) == '0',
    'R11': lambda r, rr: tr(r) and ri(r) == 1 and len(rr) >= 1 and all(inum(x.get('nqps'), -1) == 4 for x in rr),
    'C1': lambda r, rr: inum(r.get('status_bad'), 0) >= 1 and ri(r) == 0 and r['outcome'] != 'transparent',
    'N2': lambda r, rr: str(r.get('t1_refused0')) == '1' and str(r.get('t1_refused1')) == '1'
    and str(r.get('t1_enabled0')) == '0' and str(r.get('t1_enabled1')) == '0' and ri(r) == 0 and r['outcome'] != 'transparent',
    'N3': lambda r, rr: inum(r.get('n_records0'), -1) == 0 and str(r.get('kernel_timeout0')) == '1',
}


def score_cell(pid, rows, rounds):
    tag, grp, planned = CELLS[pid]
    found = cell(rows, tag)
    need = 8 if pid.startswith('N') else 4
    valid, apart, out, okr, bad = [], [], [], [], []
    for r in found:
        why = ''
        if r['outcome'] == 'void':
            why = 'void'
        elif not build_ok(r, grp):
            why = 'build md5'
        elif not VALID[pid](r):
            why = 'fault not applied'
        out.append((r, why))
        if why:
            apart.append((r, why))
            continue
        valid.append(r)
        (okr if COND[pid](r, init_rounds(rounds, r['tag'])) else bad).append(r)
    verdict = '자료 부족' if len(valid) < need else ('맞음' if not bad else '틀림')
    note = ''
    if pid == 'R7':
        note = f'거절 {sum(1 for r in valid if r["outcome"] == "declined")}/{len(valid)}(보고만), failed {sum(1 for r in valid if r["outcome"] == "failed")}'
    tot = [num(x['total_ms']) for r in valid for x in init_rounds(rounds, r['tag']) if num(x['total_ms']) is not None]
    if tot and pid in ('R2', 'R3', 'R4', 'R11'):
        note = f'시작 쪽 라운드 {len(tot)}개 total_ms 중앙값 {statistics.median(tot):.2f}, 범위 {min(tot):.2f}–{max(tot):.2f} ms'
    return {'planned': planned, 'found': len(found), 'valid': len(valid), 'valid_rows': valid, 'apart': apart,
            'hits': len(okr), 'missed': [r['tag'] for r in bad], 'verdict': verdict, 'note': note, 'rowsout': out}


def score_n1(res, rounds):
    a, b = res['R2'], res['R3']
    ta = [num(x['total_ms']) for r in a['valid_rows'] for x in init_rounds(rounds, r['tag'])]
    tb = [num(x['total_ms']) for r in b['valid_rows'] for x in init_rounds(rounds, r['tag'])]
    if a['valid'] < 8 or b['valid'] < 8 or not ta or not tb:
        return {'planned': 20, 'found': a['found'] + b['found'], 'valid': a['valid'] + b['valid'], 'apart': [],
                'hits': 0, 'missed': [], 'verdict': '자료 부족', 'note': '', 'rowsout': []}
    ma, mb = statistics.median(ta), statistics.median(tb)
    ok = abs(ma - mb) <= 1.0
    return {'planned': 20, 'found': a['found'] + b['found'], 'valid': a['valid'] + b['valid'], 'apart': [],
            'hits': int(ok), 'missed': [], 'verdict': '맞음' if ok else '틀림', 'rowsout': [],
            'note': f'중앙값: 옮긴 빌드 {ma:.2f} ms(라운드 {len(ta)}), devel {mb:.2f} ms(라운드 {len(tb)}), 차이 {ma - mb:+.2f} ms'}


def score_lat(rows):
    best, nval, apart, out = {}, {}, [], []
    for size in ('4k', '256k'):
        for c, g in LAT.items():
            name = f'lat{size}_{c}'
            ok = []
            for r in cell(rows, name):
                vals = [v for v in (r.get('lat_p50') or '').split(';') if v]
                why = ''
                if r['outcome'] == 'void' or len(vals) != 5:
                    why = 'void or not 5 reps'
                elif not build_ok(r, g):
                    why = 'build md5'
                out.append((r, why))
                if why:
                    apart.append((r, why))
                else:
                    ok.append(statistics.median(float(v) for v in vals))
            nval[name] = len(ok)
            best[name] = min(ok) if ok else None
    return best, nval, apart, out


def lat_rows(best, nval, apart, out):
    names = list(best)
    found = sum(1 for r, _ in out)
    def res(pid, need, conds, note):
        if any(nval[n] < need for n in names_for[pid]):
            v = '자료 부족'
        else:
            v = '맞음' if all(conds) else '틀림'
        return {'planned': 10 * len(names_for[pid]), 'found': sum(1 for r, _ in out if any(re.search(r'_%s_t\d+$' % n, r['tag']) for n in names_for[pid])),
                'valid': sum(nval[n] for n in names_for[pid]), 'apart': [(r, w) for r, w in apart if any(re.search(r'_%s_t\d+$' % n, r['tag']) for n in names_for[pid])],
                'hits': sum(bool(c) for c in conds), 'missed': [], 'verdict': v, 'note': note, 'rowsout': []}
    names_for = {'N4': ['lat4k_stock', 'lat4k_dv22off', 'lat256k_stock', 'lat256k_dv22off'],
                 'N5': ['lat4k_t1off', 'lat4k_dt1off', 'lat4k_t1on', 'lat4k_dt1on', 'lat256k_t1off', 'lat256k_dt1off', 'lat256k_t1on', 'lat256k_dt1on'],
                 'R12': ['lat4k_t1on', 'lat4k_stock', 'lat4k_t1off', 'lat256k_t1on', 'lat256k_stock']}
    b = lambda n: best[n] if best[n] is not None else float('nan')
    d = lambda x, y: b(x) - b(y)
    n4 = [abs(d('lat4k_stock', 'lat4k_dv22off')) <= 0.5, abs(d('lat256k_stock', 'lat256k_dv22off')) <= 0.5]
    n5 = [abs(d('lat4k_t1off', 'lat4k_dt1off')) <= 0.5, abs(d('lat4k_t1on', 'lat4k_dt1on')) <= 0.5,
          abs(d('lat256k_t1off', 'lat256k_dt1off')) <= 0.5, abs(d('lat256k_t1on', 'lat256k_dt1on')) <= 0.5]
    r12 = [1.0 <= d('lat4k_t1on', 'lat4k_stock') <= 2.6, 0.2 <= d('lat4k_t1off', 'lat4k_stock') <= 1.2,
           0.8 <= d('lat256k_t1on', 'lat256k_stock') <= 2.4]
    bl = ', '.join(f'{n} {b(n):.3f}' for n in names)
    return {
        'N4': res('N4', 8, n4, f'공식 그대로 − devel v2.2 기준: 4 KiB {d("lat4k_stock", "lat4k_dv22off"):+.3f}, 256 KiB {d("lat256k_stock", "lat256k_dv22off"):+.3f} µs'),
        'N5': res('N5', 8, n5, f'옮긴 빌드 − devel: 4 KiB 끔 {d("lat4k_t1off", "lat4k_dt1off"):+.3f}, 켬 {d("lat4k_t1on", "lat4k_dt1on"):+.3f}; 256 KiB 끔 {d("lat256k_t1off", "lat256k_dt1off"):+.3f}, 켬 {d("lat256k_t1on", "lat256k_dt1on"):+.3f} µs'),
        'R12': res('R12', 4, r12, f'공식 그대로 대비 비용: 4 KiB 켬 {d("lat4k_t1on", "lat4k_stock"):+.3f}, 끔 {d("lat4k_t1off", "lat4k_stock"):+.3f}; 256 KiB 켬 {d("lat256k_t1on", "lat256k_stock"):+.3f} µs. best-run p50(µs): {bl}'),
    }


def main():
    rdir = os.path.abspath(sys.argv[1])
    rows, rounds = load(rdir)
    res = {pid: score_cell(pid, rows, rounds) for pid in CELLS}
    res['N1'] = score_n1(res, rounds)
    best, nval, apart, out = score_lat(rows)
    res.update(lat_rows(best, nval, apart, out))
    cols = ['id', 'tag', 'path', 'counted_apart', 'outcome', 'pe0_rc', 'pe1_rc', 'rounds_init', 'status_bad', 'n_records0',
            'kernel_timeout0', 'decline_reason0', 't1_fetch_cr0', 't1_fetch_exec0', 't1_fetch_reposted0', 'fetch_fetches',
            'fetch_exact', 'fetch_counter1', 'sig_exact', 'finalize_ms0', 'exit_mono0', 'atexit_mono0', 'atexit_detached0',
            'exit_mono1', 'atexit_mono1', 'atexit_detached1', 't1_enabled0', 't1_enabled1', 't1_refused0', 't1_refused1',
            'ft_handler0', 'ft_handler1', 'handler', 'init_round_total_ms', 'init_round_nqps', 'lat_p50', 'bundle',
            'md5_transport', 'md5_host', 'md5_bin']
    with open(os.path.join(rdir, 'trials_scored.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        seen = set()
        groups = [(pid, res[pid]['rowsout']) for pid in CELLS if pid != 'N3'] + [('lat', out)]
        for pid, ro in groups:
            for r, why in ro:
                if r['tag'] in seen:
                    continue
                seen.add(r['tag'])
                d = {k: r.get(k, '') for k in cols}
                d.update(id=('N2,N3' if pid == 'N2' else pid), path=r.get('_path'), counted_apart=why)
                rr = init_rounds(rounds, r['tag'])
                d['init_round_total_ms'] = ';'.join(x['total_ms'] for x in rr)
                d['init_round_nqps'] = ';'.join(x.get('nqps', '') for x in rr)
                w.writerow(d)
    L = ['# t1_380 채점', '',
         f'원자료: `{os.path.basename(rdir)}/` 아래 시행 {len(rows)}개(`.meta` 기준). 규칙: [predictions.csv](../../predictions.csv)'
         ' (태그 `prereg/nvshmem-t1-380-v1`). 시행별 값: [trials_scored.csv](trials_scored.csv).', '',
         '| 예측 | 계획 n | 찾은 시행 | 유효 n | 맞은 시행 | 판정 | 따로 센 시행 | 놓친 시행 | 메모 |', '|---|--:|--:|--:|--:|---|---|---|---|']
    for pid in ORDER:
        x = res[pid]
        ap = ', '.join(f'{r.get("tag")}({w})' for r, w in x['apart']) or '-'
        L.append(f'| {LABEL[pid]} ({pid}) | {x["planned"]} | {x["found"]} | {x["valid"]} | {x["hits"]} | {x["verdict"]} | {ap} | {", ".join(x["missed"]) or "-"} | {x["note"]} |')
    L += ['', '- 복구 시간 비교(N1)와 지연 세 줄(N4, N5, R12)의 "맞은 시행"은 맞은 조건 수다. N2와 N3은 같은 10회를 다르게 채점한다.',
          '- "따로 센 시행"은 void, 장애 미적용, 빌드 md5가 칸의 묶음과 다른 시행이다(EXPERIMENT.md 8절).']
    open(os.path.join(rdir, 'SCORE.md'), 'w').write('\n'.join(L) + '\n')
    for pid in ORDER:
        x = res[pid]
        print(f'{pid:4s} planned={x["planned"]:3d} found={x["found"]:3d} valid={x["valid"]:3d} hits={x["hits"]:2d} {x["verdict"]}  {x["note"]}')


if __name__ == '__main__':
    main()
