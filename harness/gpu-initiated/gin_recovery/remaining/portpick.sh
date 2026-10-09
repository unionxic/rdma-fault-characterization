# portpick.sh - sourced by run_trial_hr.sh and run_mr_hr.sh. gin-remaining: a copy of ../peer/portpick.sh (gin-peer, the
# port fix), unchanged below these two lines. Needs SUNNY_SSH and WORK.
#
# The drivers' rendezvous port used to be drawn from 46000-48999, inside the ephemeral range of both nodes
# (32768-60999): 7 "bind: Address already in use" exclusions in gin-harden, gin-handoff and gin-multirank, and a peer rank
# could write its first bytes into a foreign listener on that port. Here:
#   - the port is drawn from PORT_LO..PORT_HI (default 29000-30999, below the ephemeral range, so the kernel never hands
#     it out to an outgoing connection; checked unused by `ss -ltn` on rain when the study was written);
#   - a candidate is taken only if no TCP socket in any state uses it on rain AND on sunny (ss, read-only);
#   - the drivers verify the rendezvous (GIN_RDV_NONCE, a per-trial random nonce): a rank sends nothing before it has
#     read rank 0's greeting with that nonce (gin_ts2.cu, gin_mr.cu).
# Test helpers for the port-fix cell (both are our own processes, bounded by `timeout`, stopped by their recorded PID):
#   start_occupier <port>   a listener on rain that only holds the port (the picker must skip it)
#   start_decoy <port>      a listener on rain that greets every connection with a wrong 16-byte record and counts the
#                           bytes it receives (decoy.out: decoy_conns, decoy_bytes); a verified rank must send it nothing
PORT_LO=${PORT_LO:-29000}
PORT_HI=${PORT_HI:-30999}
[ "$PORT_LO" -ge 1024 ] && [ "$PORT_HI" -lt 32768 ] && [ "$PORT_LO" -le "$PORT_HI" ] ||
  { echo "PORT_LO..PORT_HI must lie in 1024..32767" >&2; exit 1; }

# port_busy <p>: 0 (busy) if a TCP socket of any state uses port <p> on rain or on sunny, or if sunny cannot be asked
port_busy() {
  local p=$1 out
  [ -n "$(ss -Htan "( sport = :$p or dport = :$p )" 2>/dev/null)" ] && return 0
  out=$(ssh -n "$SUNNY_SSH" "ss -Htan '( sport = :$p or dport = :$p )'; echo SS_DONE" 2>/dev/null) || return 0
  case "$out" in SS_DONE) return 1 ;; *) return 0 ;; esac
}

# pick_port [<first candidate>]: sets PORT, PORT_TRIES and PORT_SKIPPED (the busy candidates, comma-separated); at most
# 32 consecutive candidates (wrapping inside the range); exits the runner if none is free
pick_port() {
  local span=$(( PORT_HI - PORT_LO + 1 )) c k
  c=${1:-$(( PORT_LO + ($$ + RANDOM) % span ))}
  PORT=""; PORT_TRIES=0; PORT_SKIPPED=""
  for k in $(seq 0 31); do
    PORT_TRIES=$(( PORT_TRIES + 1 ))
    if port_busy "$c"; then
      PORT_SKIPPED="${PORT_SKIPPED:+$PORT_SKIPPED,}$c"
    else
      PORT=$c; return 0
    fi
    c=$(( c + 1 )); [ "$c" -gt "$PORT_HI" ] && c=$PORT_LO
  done
  echo "no free rendezvous port in $PORT_LO..$PORT_HI after 32 candidates" >&2
  exit 1
}

# a random 64-bit rendezvous nonce (hex) for this trial
new_nonce() { od -An -N8 -tx8 /dev/urandom | tr -d ' \n'; }

# start_occupier <port>: OCC_PID; waits until the port shows LISTEN on rain (at most 2 s)
start_occupier() {
  timeout -s KILL 120 python3 -c 'import socket,sys,time
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("0.0.0.0", int(sys.argv[1]))); s.listen(1)
time.sleep(110)' "$1" &
  OCC_PID=$!
  local i
  for i in $(seq 1 40); do [ -n "$(ss -Hltn "( sport = :$1 )" 2>/dev/null)" ] && return 0; sleep 0.05; done
  return 1
}

# start_decoy <port> <out file>: DECOY_PID; waits until it listens (at most 2 s)
start_decoy() {
  cat > "$WORK/decoy.py" <<'PY'
import signal, socket, sys, time
port, out, life = int(sys.argv[1]), sys.argv[2], float(sys.argv[3])
conns = nbytes = 0
def done(*_):
    with open(out, "w") as f:
        f.write("decoy_conns=%d decoy_bytes=%d decoy_port=%d\n" % (conns, nbytes, port))
    sys.exit(0)
signal.signal(signal.SIGTERM, done)
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("0.0.0.0", port)); s.listen(8)
s.settimeout(0.2)
end = time.time() + life
while time.time() < end:
    try:
        c, _ = s.accept()
    except socket.timeout:
        continue
    conns += 1
    try:
        c.sendall(b"NOTGINRDV0000000")  # 16 bytes: a wrong greeting
        c.settimeout(0.2)
        t = time.time()
        while time.time() - t < 1.0:
            try:
                d = c.recv(4096)
            except socket.timeout:
                continue
            if not d:
                break
            nbytes += len(d)
    except OSError:
        pass
    c.close()
done()
PY
  timeout -s KILL 150 python3 "$WORK/decoy.py" "$1" "$2" 140 &
  DECOY_PID=$!
  local i
  for i in $(seq 1 40); do [ -n "$(ss -Hltn "( sport = :$1 )" 2>/dev/null)" ] && return 0; sleep 0.05; done
  return 1
}

# stop_pid <pid> [TERM|KILL]: <pid> is a `timeout` wrapper this runner started (recorded at its start); signal its
# children (found by parent link, never by name), give it up to 3 s to end, then KILL the wrapper itself; wait for it
stop_pid() {
  local p=$1 sig=${2:-TERM} c i
  [ -n "$p" ] || return 0
  for c in $(pgrep -P "$p" 2>/dev/null); do kill -"$sig" "$c" 2>/dev/null; done
  for i in $(seq 1 60); do kill -0 "$p" 2>/dev/null || break; sleep 0.05; done
  kill -0 "$p" 2>/dev/null && kill -KILL "$p" 2>/dev/null
  wait "$p" 2>/dev/null
  return 0
}
