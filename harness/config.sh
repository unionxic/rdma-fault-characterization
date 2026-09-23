# config.sh - environment for the unified RDMA fault harness.
# Sourced by run.sh. Nothing is hardcoded in the binaries; set it all here.
# Current cluster: rain (client, mlx5_1, 30.0.0.3) -> sunny (server, mlx5_0, 30.0.0.4).

# --- server (responder) ---
# Control channel runs over the MANAGEMENT IP so it survives the retry_link_down
# fault (which downs the RoCE netdev). RDMA itself uses the RoCE GID, not this IP.
SERVER_IP="${SERVER_IP:-192.0.2.194}"      # mgmt IP of the responder (TCP control channel)
SERVER_SSH="${SERVER_SSH:-unionxic@192.0.2.194}"  # ssh target that runs probe_server
SERVER_DEV="${SERVER_DEV:-mlx5_0}"        # responder RDMA device (its ACTIVE port)
SERVER_IFACE="${SERVER_IFACE:-enp23s0f0np0}"   # responder RoCE netdev (toggled for retry_link_down; needs NOPASSWD sudo for ip)
SERVER_DIR="${SERVER_DIR:-~/rdma-error/harness}"  # harness dir on the responder
SERVER_LOG="${SERVER_LOG:-/tmp/probe_srv.log}"     # probe_server stderr on the responder
# 1 = retry_link_down only LOGS "[server] DRYRUN link down/up" (no sudo, link untouched):
# exercises the protocol and every restore path. 0 = really toggle SERVER_IFACE.
PROBE_LINK_DRYRUN="${PROBE_LINK_DRYRUN:-0}"

# --- client (requester, this node) ---
CLIENT_DEV="${CLIENT_DEV:-mlx5_1}"        # requester RDMA device (its ACTIVE port)

# --- shared RDMA params ---
IB_PORT="${IB_PORT:-1}"
# RoCEv2 GID index per side. "auto" (default) = run.sh picks the RoCE v2 IPv4-mapped
# GID on each node; the index can differ per node and can move after an address
# re-add (rain's moved 3 -> 4 by 2026-09-23). GID_INDEX=N forces N on both sides.
CLIENT_GID_INDEX="${CLIENT_GID_INDEX:-${GID_INDEX:-auto}}"
SERVER_GID_INDEX="${SERVER_GID_INDEX:-${GID_INDEX:-auto}}"
CTRL_PORT="${CTRL_PORT:-18580}"

# --- experiment params ---
ITERS="${ITERS:-30}"
CLIENT_CPU="${CLIENT_CPU:--1}"            # pin requester to a core (>=0) for latency stability
SERVER_CPU="${SERVER_CPU:--1}"
COUNTER="${COUNTER:-roce_adp_retrans}"    # hw_counter sampled around each trial
MSG_SIZE="${MSG_SIZE:-4194304}"           # trigger size for local_qp_err / partial_write
DETECT_TIMEOUT_MS="${DETECT_TIMEOUT_MS:-10000}"
# Safety-net lifetime of each probe_server (normally it exits on BYE / is stopped
# by run.sh). Sized from ITERS so long runs are never cut off mid-run:
# per trial <= detect timeout + 25 s (PROBE, recovery, link re-train, verify).
SERVER_TIMEOUT="${SERVER_TIMEOUT:-$(( 120 + ITERS * (DETECT_TIMEOUT_MS / 1000 + 25) ))}"

# faults to run by default (space-separated). Also available: retry_proc_kill
# (server restarted per trial) and retry_link_down (passwordless sudo for `ip` on
# the server, or PROBE_LINK_DRYRUN=1).
FAULTS="${FAULTS:-local_qp_err rem_inv_req rem_access rnr retry_server_qp_err partial_write}"
RECOVERY="${RECOVERY:-qp_only}"

RESULTS_DIR="${RESULTS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/results}"
