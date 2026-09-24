#!/usr/bin/env python3
"""dbrk_table.py - check the dbrk trials (nrc_devx -f kerr|knak, 2026-09-25) against the rule
    "at the error transition the NIC takes the SQ producer from the doorbell record (P) and
     completes, with error/flush, exactly the WQEs in [c, P); nothing if P <= c"
where c = the first WQE not completed OK (kerr: pi_before, knak: pi_before + kbad).

Every trial is recounted from its raw EV lines (<tag>.req.log), independently of the SUMMARY
line, and the two counts must agree. Writes <dir>/dbrk_trials.csv and prints markdown.

usage: dbrk_table.py <results/20260925_dbrk>
"""
import csv
import glob
import os
import re
import sys
from collections import OrderedDict, defaultdict

KV = re.compile(r'(\w+)=("([^"]*)"|\S*)')
CQE = re.compile(r'^EV t_ms=(\S+) what=cqe idx=(\d+) op=0x(\w+) owner=\d+ syndrome=0x(\w+) vendor=0x(\w+) .* wqe=(\d+)')


def kv(line):
    return {m.group(1): (m.group(3) if m.group(3) is not None else m.group(2)) for m in KV.finditer(line)}


def raw_cqes(req_log):
    """CQEs written after the fault, from the EV lines (the observation loop logs only changes
    after the shadow snapshot taken before the fault). Also the late-DBR time if any."""
    out, t_late, faulted = [], None, False
    for line in open(req_log):
        if 'what=fault_injected' in line:
            faulted = True
        if 'what=late_dbr' in line:
            t_late = float(kv(line)['t_ms'])
        m = CQE.match(line)
        if m and faulted:
            out.append(dict(t=float(m.group(1)), idx=int(m.group(2)), op=int(m.group(3), 16), syn=int(m.group(4), 16),
                            ven=int(m.group(5), 16), wqe=int(m.group(6))))
    # a slot can be logged twice when the sweep reads a CQE while the NIC is still writing it
    # (op byte still 0xff from the init pattern): keep each slot's final content, count the rest
    final = {}
    for e in out:
        final[e['idx']] = e
    torn = len(out) - len(final)
    return sorted(final.values(), key=lambda e: e['t']), t_late, torn


def scenario(tag):
    # s1_k0_t3 -> s1 ; s4_late_uar0_s100_t3 -> s4_late_uar0_s100 ; smoke_kerr_k8 -> smoke_kerr
    return re.sub(r'_k(pi|m?-?\d+)(?=_|$)', '', tag.rsplit('_t', 1)[0] if re.search(r'_t\d+$', tag) else tag)


def main():
    root = sys.argv[1]
    rows = []
    for f in sorted(glob.glob(os.path.join(root, '*', 'summary.txt'))):
        d_dir = os.path.dirname(f)
        for line in open(f):
            if not line.startswith('tag='):
                continue
            d = kv(line)
            if d.get('fault') not in ('kerr', 'knak'):
                continue
            tag = d['tag']
            cq, t_late, torn = raw_cqes(os.path.join(d_dir, tag + '.req.log'))
            pi_before, P, pi = int(d['pi_before']), int(d['dbr_val']), int(d['pi'])
            kbad = int(d['kbad']) if d['fault'] == 'knak' else 0
            c = pi_before + kbad
            late = int(d['klate_ms']) >= 0
            before = [e for e in cq if t_late is None or e['t'] < t_late]
            after = [e for e in cq if t_late is not None and e['t'] >= t_late]
            ok_w = sorted(e['wqe'] for e in before if e['op'] == 0)
            err = [e for e in before if e['op'] in (0xd, 0xe)]
            err_w = sorted(e['wqe'] for e in err)
            exp_err = list(range(c, P)) if P > c else []
            exp_ok = list(range(pi_before, pi_before + kbad))
            root_e = [e for e in err if e['wqe'] == c]
            rest = [e for e in err if e['wqe'] != c]
            rest_codes = sorted({f"{e['syn']:02x}/{e['ven']:02x}" for e in rest})
            # raw recount must agree with the SUMMARY bookkeeping and with QUERY_CQ's producer counter
            consistent = (int(d['k_n_err']) == sum(1 for e in cq if e['op'] in (0xd, 0xe)) and
                          int(d['k_n_ok']) == sum(1 for e in cq if e['op'] == 0) and
                          int(d['cq_pc_delta']) == len(cq) and all(e['op'] != 0xf for e in cq))
            r = OrderedDict(
                dir=os.path.basename(d_dir), tag=tag, scen=scenario(tag), fault=d['fault'], kdbr=d['kdbr'],
                pi_before=pi_before, pi=pi, c=c, P=P, k2err_ms=d['k2err_ms'], klate_ms=d['klate_ms'],
                klate_uar=d['klate_uar'], n_ok=len(ok_w), n_err=len(err_w),
                err_wqes=' '.join(map(str, err_w)) or '-', exp_err_n=len(exp_err),
                match_err=int(err_w == exp_err), match_ok=int(ok_w == exp_ok),
                root=(f"{root_e[0]['syn']:02x}/{root_e[0]['ven']:02x}" if root_e else '-'),
                rest=','.join(rest_codes) or '-',
                qp_final=d['qp_state_final'], t_qp_err_ms=d['t_qp_err_ms'], err_hw_sq=d['err_hw_sq'],
                err_sw_sq=d['err_sw_sq'], hw_sq_final=d['hw_sq'], sw_sq_final=d['sw_sq'],
                match_sw=int(int(d['err_sw_sq']) == P),
                cq_pc_delta=int(d['cq_pc_delta']), raw_vs_summary=int(consistent), torn_reads=torn,
                n_after_late=len(after), after_late_wqes=' '.join(str(e['wqe']) for e in sorted(after, key=lambda e: e['wqe'])) or '-',
                after_late_codes=','.join(sorted({f"{e['op']:x}/{e['syn']:02x}/{e['ven']:02x}" for e in after})) or '-',
                late_first_ms=(round(min(e['t'] for e in after) - t_late, 3) if after else ''),
                late_last_ms=(round(max(e['t'] for e in after) - t_late, 3) if after else ''),
                dbr1_final=d['dbr1'], t_first_err_ms=d['t_first_err_ms'])
            rows.append(r)
    if not rows:
        print('no dbrk trials found')
        return
    out = os.path.join(root, 'dbrk_trials.csv')
    with open(out, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f'<!-- {len(rows)} trials -> {out} -->')
    groups = defaultdict(list)
    for r in rows:
        groups[(r['scen'], r['fault'], r['kdbr'], r['k2err_ms'], r['klate_ms'], r['klate_uar'])].append(r)
    print('| scen | fault | kdbr | c | P | n | error CQEs (distinct counts) | error wqes (distinct sets) | '
          'rule holds (err set) | ok CQEs as expected | root-cause CQE at c (syn/ven) | other error CQEs | '
          'QP final | sw_sq 1st ERR sample (distinct) | hw_sq 1st ERR sample (distinct) | CQ pc delta (distinct) | '
          'raw=summary | after late write (n; codes) |')
    print('|---|---|---|--:|--:|--:|---|---|---|---|---|---|---|---|---|---|---|---|')

    def dist(g, k):
        return ','.join(sorted({str(r[k]) for r in g}, key=lambda s: (len(s), s)))

    for key in sorted(groups, key=lambda k: (k[0], k[1], k[4], k[5], int(k[2]) if k[2].lstrip('-').isdigit() else 999)):
        g = groups[key]
        scen, fault, kdbr = key[0], key[1], key[2]
        n = len(g)
        if int(key[4]) >= 0:
            lf = sorted(r['late_first_ms'] for r in g if r['late_first_ms'] != '')
            late = f"{dist(g, 'n_after_late')}; {dist(g, 'after_late_codes')}; first CQE +{lf[0]}..{lf[-1]} ms" if lf else \
                f"{dist(g, 'n_after_late')}; -"
        else:
            late = '-'
        print(f"| {scen} | {fault} | {'pi' if int(kdbr) == -100000 else kdbr} | {dist(g, 'c')} | {dist(g, 'P')} | {n} | "
              f"{dist(g, 'n_err')} | {dist(g, 'err_wqes')} | {sum(r['match_err'] for r in g)}/{n} | "
              f"{sum(r['match_ok'] for r in g)}/{n} | {dist(g, 'root')} | {dist(g, 'rest')} | {dist(g, 'qp_final')} | "
              f"{dist(g, 'err_sw_sq')} | {dist(g, 'err_hw_sq')} | {dist(g, 'cq_pc_delta')} | "
              f"{sum(r['raw_vs_summary'] for r in g)}/{n} | {late} |")


if __name__ == '__main__':
    main()
