#!/usr/bin/env bash
# hold.sh <outdir> <part> [<part> ...] - one cluster hold of the t1_close study. Run it inside
# ../../common/cluster_run.sh -w 10800 -t t1c-<hold>. Parts run in order:
#   t1:<spec>:<interleave 0|1>:<stop_after_s>[:gate_test]   ../scripts/t1/hold_generic.sh with the t1_close bundle
#   v2:<spec>:<stop_after_s>                                  ../scripts/v2/run_matrix_v2.sh (FT v2.2 bundle, unchanged)
# Each part writes to <outdir>/<spec basename>. Around the parts the hold keeps the full dmesg of rain
# and sunny (sudo on sunny), writes the new lines and counts new mlx5 command errors, removes any
# iptables rule with comment t1sock (this study's PE 0 T1 socket port only) and counts what is left.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
FT="$(cd "$HERE/.." && pwd)"
OUT=$1; shift
mkdir -p "$OUT"
B=$HOME/gi-bundle/${T1C_BUNDLE_NAME:-nvshmem_t1close}
snap() {  # snap <tag>
  dmesg > "$OUT/dmesg_rain_$1.txt" 2>&1
  ssh -n -o ConnectTimeout=8 sunny "sudo -n dmesg" > "$OUT/dmesg_sunny_$1.txt" 2>&1
}
snap before
echo "hold start $(date '+%F %T')" | tee "$OUT/hold.log"
cd "$FT"
for part in "$@"; do
  IFS=: read -r kind spec a b c <<< "$part"
  name=$(basename "$spec" .txt)
  echo "part $kind $spec start $(date '+%F %T')" | tee -a "$OUT/hold.log"
  case "$kind" in
    t1) env BUNDLE="$B" BUNDLE_V22="$B/v22ref" INTERLEAVE="$a" STOP_AFTER_S="$b" \
          bash scripts/t1/hold_generic.sh "$spec" "$OUT/$name" ${c:-} 2>&1 | tee -a "$OUT/hold.log" ;;
    v2) env -u BUNDLE STOP_AFTER_S="$a" bash scripts/v2/run_matrix_v2.sh "$spec" "$OUT/$name" 2>&1 | tee -a "$OUT/hold.log" ;;
    *) echo "unknown part $part" | tee -a "$OUT/hold.log" ;;
  esac
  echo "part $kind $spec end $(date '+%F %T')" | tee -a "$OUT/hold.log"
done
# iptables: this study's rules carry the comment t1sock; remove any that is left, then count
sudo -n iptables -S | grep t1sock | sed 's/^-A/-D/' | while read -r r; do sudo -n iptables $r; done
left=$(sudo -n iptables -S | grep -c t1sock)
snap after
python3 - "$OUT" <<'PY' | tee -a "$OUT/hold.log"
import re, sys
out = sys.argv[1]
pat = re.compile(r'mlx5', re.I)
cmd = re.compile(r'(cmd|command)', re.I)
bad = re.compile(r'(timeout|fail|error|leak|no done)', re.I)
for node in ('rain', 'sunny'):
    before = set(open(f'{out}/dmesg_{node}_before.txt', errors='replace').read().splitlines())
    new = [l for l in open(f'{out}/dmesg_{node}_after.txt', errors='replace').read().splitlines() if l not in before]
    open(f'{out}/dmesg_{node}_new.txt', 'w').write('\n'.join(new) + ('\n' if new else ''))
    errs = [l for l in new if pat.search(l) and cmd.search(l) and bad.search(l) and 'FWTracer' not in l]
    print(f'dmesg_new_{node}={len(new)} mlx5_cmd_errors_{node}={len(errs)}')
    for l in errs[:5]:
        print('  ', l[:160])
PY
echo "iptables_t1sock_left=$left" | tee -a "$OUT/hold.log"
echo "hold end $(date '+%F %T')" | tee -a "$OUT/hold.log"
