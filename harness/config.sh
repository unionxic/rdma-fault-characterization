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

# --- client (requester, this node) ---
CLIENT_DEV="${CLIENT_DEV:-mlx5_1}"        # requester RDMA device (its ACTIVE port)

# --- shared RDMA params ---
IB_PORT="${IB_PORT:-1}"
GID_INDEX="${GID_INDEX:-3}"               # RoCEv2 GID index (show_gids to verify)
CTRL_PORT="${CTRL_PORT:-18580}"

# --- experiment params ---
ITERS="${ITERS:-30}"
CLIENT_CPU="${CLIENT_CPU:--1}"            # pin requester to a core (>=0) for latency stability
SERVER_CPU="${SERVER_CPU:--1}"
COUNTER="${COUNTER:-roce_adp_retrans}"    # hw_counter sampled around each trial
MSG_SIZE="${MSG_SIZE:-4194304}"           # trigger size for local_qp_err / partial_write
DETECT_TIMEOUT_MS="${DETECT_TIMEOUT_MS:-10000}"

# faults to run by default (space-separated). retry_link_down needs root on server.
FAULTS="${FAULTS:-local_qp_err rem_inv_req rem_access rnr retry_server_qp_err partial_write}"
RECOVERY="${RECOVERY:-qp_only}"

RESULTS_DIR="${RESULTS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/results}"
