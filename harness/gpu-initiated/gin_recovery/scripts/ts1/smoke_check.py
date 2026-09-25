#!/usr/bin/env python3
"""Gate for the follow-up holds: the teardown-fix smoke (v2_smoke2) must show the expected behaviour."""
import csv, os, subprocess, sys
d = sys.argv[1]
out = os.path.join(d, "_rows.csv")
subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "rows.py"), d, "--out", out], check=True)
rs = list(csv.DictReader(open(out)))
by = {}
for r in rs:
    by.setdefault(r["cell"], []).append(r)
bad = []
def need(c, cond, what):
    v = by.get(c, [])
    if not v or not all(cond(r) for r in v):
        bad.append(f"{c}: {what}: " + "; ".join(f"{k}={r.get(k)}" for r in v for k in ("stem", "td_r0", "td_round_r0", "post_abort_state_r0", "transparent_ok", "tx_rc", "r0_async")))
need("abortmid_b", lambda r: r["td_r0"] == "1" and r["td_round_r0"] == "1" and r["post_abort_state_r0"] == "exited", "teardown mid-round, kernel exited")
need("f1_b", lambda r: r["transparent_ok"] == "1" and r["td_r0"] == "1", "transparent + teardown line")
need("none_b", lambda r: r["transparent_ok"] == "1", "transparent")
need("off_f1_b", lambda r: r["td_r0"] == "0" and r["tx_rc"] != "no error", "flag off: no teardown line, error")
need("die_b", lambda r: r["r0_async"] not in ("none", ""), "async error")
need("tmo_t", lambda r: r["tx_rc"] == "timeout", "ncclTimeout")
need("slow_b", lambda r: r["transparent_ok"] == "1" and r["n_watchdog_r0"] == "0", "slow round transparent, no watchdog")
need("f2_b", lambda r: r["tx_rc"] != "no error" and "REM_ACCESS" in r["decl_r0"], "REM_ACCESS declined")
for r in rs:
    if r.get("left") not in ("0",):
        bad.append(f"leftover {r['stem']} left={r.get('left')}")
print("SMOKE_OK" if not bad else "SMOKE_BAD\n" + "\n".join(bad))
sys.exit(0 if not bad else 1)
