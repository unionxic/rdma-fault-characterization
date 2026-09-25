#!/usr/bin/env bash
# test_lockcheck.sh - the lock verification of ackfloor_window.sh, every refusal path plus one
# positive control. Run it inside a real cluster_run.sh hold (so that the shared lock is held
# while it runs). No case changes the register:
#   * every case runs with ACKFLOOR_CHECK_ONLY=1, which exits right after the checks, before the
#     first register access, even if the checks pass;
#   * cases A and B are repeated without CHECK_ONLY (the real path) only if their CHECK_ONLY run
#     refused;
#   * the full ROCE_ACCL of 17:00.1 is read (read only) before and after and compared.
# Cases (expected outcome):
#   A no cluster_run.sh ancestor (window re-parented to init)                  -> refuse, check 1
#   B fake "cluster_run.sh" with fd 9 open on a file but no lock taken          -> refuse, check 3
#   C fake "cluster_run.sh" that does hold a flock on its own file              -> refuse, check 4
#   D fake "cluster_run.sh" without fd 9                                        -> refuse, check 2
#   E the real cluster_run.sh with CLUSTER_LOCK=<private file>                  -> refuse, check 5
#   F the real cluster_run.sh (private lock) whose lock file is deleted first   -> refuse, check 2
#   G positive control: directly under the outer (real, shared-lock) hold       -> pass (CHECK_ONLY)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
W=$(realpath "$HERE/../ackfloor_window.sh")
CR=$(realpath "$HERE/../../gpu-initiated/common/cluster_run.sh")
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ack/lockcheck
LOGW=$HERE/../results/20260925/window.log
rm -rf "$SCR"; mkdir -p "$SCR/fake"
dump() { sudo -n mlxreg -d 17:00.1 --reg_name ROCE_ACCL --get 2>&1 | awk -F'|' 'NF==2 && $1 !~ /Field Name/ {n=$1; v=$2; gsub(/[ \t]/,"",n); gsub(/[ \t]/,"",v); print n"="v}'; }
say() { echo "[lockcheck $(date +%T.%3N)] $*"; }
BEFORE=$(dump)
say "register before: $(echo "$BEFORE" | grep -v field_select | tr '\n' ' ')"
NLOG0=$(wc -l < "$LOGW")

# fake wrappers, named cluster_run.sh but not the repository's script
cat > "$SCR/fake/cluster_run.sh" <<'EOF'
#!/usr/bin/env bash
# fake: $1 = nolock | lock | nofd9, rest = command
mode=$1; shift
f=$(dirname "$0")/fake.lock
case "$mode" in
  nolock) exec 9>"$f"; "$@" 9>&- ;;
  lock)   exec 9>"$f"; flock 9; "$@" 9>&- ;;
  nofd9)  "$@" ;;
esac
EOF
chmod +x "$SCR/fake/cluster_run.sh"

run_case() {  # name expected(refuse|pass) check_only(1|0) command...
  local name=$1 exp=$2 co=$3; shift 3
  local out rc
  out=$(ACKFLOOR_CHECK_ONLY=$co "$@" 2>&1); rc=$?
  local line; line=$(printf '%s\n' "$out" | grep -E "REFUSE|lock verified|CHECK_ONLY" | tail -1)
  local got=pass; [ "$rc" = 64 ] && got=refuse
  local ok=FAIL; [ "$got" = "$exp" ] && ok=ok
  say "case $name (check_only=$co): rc=$rc expected=$exp -> $ok | ${line#*] }"
  [ "$ok" = ok ]
}

# A: no cluster_run.sh ancestor: double fork, the window is re-parented to init / a subreaper
caseA() {
  local co=$1 f=$SCR/A_$1.out
  # the detached shell waits until it has been re-parented (its original parent, the subshell,
  # has exited) before it starts the window, so the window never sees this script's ancestors
  ( sp=$BASHPID; ACKFLOOR_CHECK_ONLY=$co setsid bash -c '
      for i in $(seq 1 100); do [ "$(awk "{print \$4}" /proc/$$/stat)" != "$2" ] && break; sleep 0.05; done
      pp=$(awk "{print \$4}" /proc/$$/stat)
      [ "$pp" != "$2" ] || { echo "rc=not-reparented" > "$1"; exit 1; }
      echo "reparented to pid $pp ($(tr "\0" " " < /proc/$pp/cmdline | cut -c1-60))" > "$1.parent"
      "$0" -t lc_A_noancestor -- true > "$1" 2>&1; echo "rc=$?" >> "$1"' "$W" "$f" "$sp" & )
  for i in $(seq 1 100); do grep -q '^rc=' "$f" 2>/dev/null && break; sleep 0.1; done
  local rc; rc=$(sed -n 's/^rc=//p' "$f")
  local line; line=$(grep -E "REFUSE|lock verified|CHECK_ONLY" "$f" | tail -1)
  local ok=FAIL; [ "$rc" = 64 ] && ok=ok
  say "case A (check_only=$co): rc=$rc expected=refuse -> $ok | ${line#*] } | $(cat "$f.parent" 2>/dev/null)"
  [ "$ok" = ok ]
}
A1=0; caseA 1 && A1=1
run_case B refuse 1 "$SCR/fake/cluster_run.sh" nolock "$W" -t lc_B_notheld -- true && B1=1 || B1=0
run_case C refuse 1 "$SCR/fake/cluster_run.sh" lock "$W" -t lc_C_fakescript -- true
run_case D refuse 1 "$SCR/fake/cluster_run.sh" nofd9 "$W" -t lc_D_nofd9 -- true
export CLUSTER_LOG=$SCR/nested_cluster_run.log
run_case E refuse 1 env CLUSTER_LOCK="$SCR/private.lock" "$CR" -w 60 -t lc_E_privatelock -- "$W" -t lc_E_privatelock -- true
run_case F refuse 1 env CLUSTER_LOCK="$SCR/private2.lock" "$CR" -w 60 -t lc_F_deleted -- \
  bash -c 'rm -f "$1"; exec "$2" -t lc_F_deleted -- true' _ "$SCR/private2.lock" "$W"
unset CLUSTER_LOG
run_case G pass 1 "$W" -t lc_G_positive -- true

# the real path (no CHECK_ONLY), only for cases whose CHECK_ONLY run refused
[ "$A1" = 1 ] && caseA 0
[ "$B1" = 1 ] && run_case B refuse 0 "$SCR/fake/cluster_run.sh" nolock "$W" -t lc_B_notheld_real -- true

AFTER=$(dump)
if [ "$BEFORE" = "$AFTER" ]; then say "register after == before (all $(echo "$AFTER" | grep -c =) fields)"; else say "REGISTER CHANGED: $(diff <(echo "$BEFORE") <(echo "$AFTER") | tr '\n' ' ')"; fi
NEW=$(tail -n +"$((NLOG0 + 1))" "$LOGW")
say "window.log lines added: $(echo "$NEW" | grep -c .); SET/BEFORE/RESTORED lines among them: $(echo "$NEW" | grep -cE 'SET |BEFORE |RESTORED')"
