#!/usr/bin/env python3
"""finjudge.py <raw>: per kill cell, survivor's witness FIN/RST line -> its own judgement line (ms), and kill -> judgement."""
import sys, collections, ev_gc
raw = sys.argv[1]
cells = ["gc4_kill3_ow_gc", "gc4_rst_kill3_gc", "gc4_ud_drop_rejoin_gc", "gc4_kill3_ow_spareabsent_gc", "mi4_kill3_ow_gc", "mi4_kill1_ow_gc", "mi4_kill3_ckpt_ow_gc",
         "mi4_seg_4k_gc", "mi4_seg_32k_gc", "mi4_seg_128k_gc", "mi4_pull_gc", "rs4_kill3_mion_gc"]
for c in cells:
    st = [s for s in ev_gc.stems(raw) if s.rsplit("_n", 1)[0] == c]
    d1, causes, fin_causes, ok = [], collections.Counter(), collections.Counter(), 0
    tot = 0
    for s in st:
        d = ev_gc.load(raw, s)
        subj = int(d["meta"]["subject_rank"]) if d["meta"].get("subject_rank") not in (None, "", "-") else int(d["meta"]["kill_rank"])
        for k in range(4):
            if k == subj: continue
            src = "r%d" % k
            f = [e for e in d["ev"] if e["src"] == src and e["name"] == "fin" and int(e["g"][1]) == subj]
            j = [e for e in d["ev"] if e["src"] == src and e["name"] == "dead" and int(e["g"][1]) == subj]
            if not j: continue
            tot += 1
            causes[j[0]["g"][2]] += 1
            if f:
                fin_causes[f[0]["g"][2]] += 1
                x = j[0]["t"] - f[0]["t"]
                d1.append(x)
                ok += (20 <= x <= 22)
    print("%-32s trials %2d judgements %2d causes %s witness %s FIN->judge %.3f-%.3f ms (in W..W+2: %d/%d)" % (c, len(st), tot, dict(causes), dict(fin_causes), min(d1), max(d1), ok, len(d1)))
