# remote_gc.sh - gin-control, test side: sourced by run_gc.sh, hold_gc.sh, launcher_gc.sh and run_cost_gc.sh. One way to hand
# a script to sunny's shell (REVIEW_TEST B1: a value with its own single quotes, wrapped again in single quotes, was split by
# the remote shell into other words). Nothing here runs anything by itself; no address is read or written.
#
#   shq <word>                    the word in POSIX single quotes (every ' becomes '\'')
#   rcmd <script> [arg ...]       one remote command line: bash -c '<script>' _ '<arg>' ...  (each piece quoted once)
#   pcmd <python> [arg ...]       one remote command line: python3 -u -c '<python>' '<arg>' ...
#   sunny_sh <script> [arg ...]   run <script> with its args under bash on sunny (ssh -n, LogLevel=ERROR)
#   sunny_py <python> [arg ...]   run <python> on sunny the same way
#   node_sh <node> <script> [arg ...] / node_py <node> <python> [arg ...]   rain: locally; sunny: as above
# The read-only queries the scripts share: MTU_Q (the GIN port's active_mtu from ibv_devinfo, digits only), RNR_Q (the RNR port
# counter), GID_PROBE (the RoCE v2 GID index of run_mi.sh's probe), and MASK (the IPv4 masking sed expression).
shq() { local s=${1//\'/\'\\\'\'}; printf "'%s'" "$s"; }
rcmd() {
  local s=$1 a out; shift
  out="bash -c $(shq "$s") _"
  for a in "$@"; do out="$out $(shq "$a")"; done
  printf '%s' "$out"
}
pcmd() {
  local s=$1 a out; shift
  out="python3 -u -c $(shq "$s")"
  for a in "$@"; do out="$out $(shq "$a")"; done
  printf '%s' "$out"
}
sunny_sh() { ssh -n -o LogLevel=ERROR "${SUNNY_SSH:?set SUNNY_SSH}" "$(rcmd "$@")"; }
sunny_py() { ssh -n -o LogLevel=ERROR "${SUNNY_SSH:?set SUNNY_SSH}" "$(pcmd "$@")"; }
node_sh() { local nd=$1; shift; if [ "$nd" = sunny ]; then sunny_sh "$@"; else bash -c "$1" _ "${@:2}"; fi; }
node_py() { local nd=$1; shift; if [ "$nd" = sunny ]; then sunny_py "$@"; else python3 -u -c "$1" "${@:2}"; fi; }
# shellcheck disable=SC2016  # expanded by the shell that runs the query, not here
MTU_Q='ibv_devinfo -d "$1" -i 1 2>/dev/null | sed -n "s/^[[:space:]]*active_mtu:[[:space:]]*\([0-9][0-9]*\).*/\1/p" | head -n 1'
# shellcheck disable=SC2016
RNR_Q='cat "/sys/class/infiniband/$1/ports/1/hw_counters/rnr_nak_retry_err" 2>/dev/null || echo -'
# shellcheck disable=SC2016
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:1e00:00*) echo "$g"; exit 0;; esac
done; exit 1'
MASK='s/[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}/<ip>/g'
