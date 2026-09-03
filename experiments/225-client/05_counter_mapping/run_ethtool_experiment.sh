#!/bin/bash
# run_ethtool_experiment.sh — Measure ethtool -S counter deltas per fault scenario
#
# Reuses existing client/server binaries. Wraps each trial with ethtool snapshots
# on both client (225) and server (224).
#
# Usage:
#   ./run_ethtool_experiment.sh              # Run all 10 scenarios
#   ./run_ethtool_experiment.sh 1            # Run only scenario 1 (LOC_PROT_LEN)
#   ./run_ethtool_experiment.sh 1 5          # Scenario 1, 5 trials
#
# Run from 225. Server (224) must be accessible via SSH.
# Results go to results/ethtool/ — existing sysfs results in results/raw/ are NOT touched.

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/05_counter_mapping"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIC="enp1s0f0np0"
NUM_TRIALS=${2:-3}
RESULT_DIR="$SCRIPT_DIR/results/ethtool"

# Temp CWD for client so it writes sysfs CSVs there (not in results/raw/)
CLIENT_WORK_DIR=$(mktemp -d /tmp/ethtool_client.XXXXXX)
mkdir -p "$CLIENT_WORK_DIR/results/raw"

TMPDIR_SNAP=$(mktemp -d /tmp/ethtool_snap.XXXXXX)

# ---- Scenario mapping ----
declare -A NAMES=(
    [1]="LOC_PROT_LEN"
    [2]="LOC_PROT_LKEY"
    [3]="LOC_PROT_PERM"
    [4]="WR_FLUSH"
    [5]="REM_INV_REQ"
    [6]="REM_ACCESS_RKEY"
    [7]="RNR_RETRY_EXC"
    [8]="RETRY_EXC_QP_ERR"
    [9]="RETRY_EXC_PROC_KILL"
    [11]="REM_ACCESS_ADDR"
)

# ---- ethtool counters to track ----
ETHTOOL_COUNTERS=(
    # RDMA traffic
    rx_vport_rdma_unicast_packets
    rx_vport_rdma_unicast_bytes
    tx_vport_rdma_unicast_packets
    tx_vport_rdma_unicast_bytes
    # General traffic
    rx_vport_unicast_packets
    rx_vport_unicast_bytes
    tx_vport_unicast_packets
    tx_vport_unicast_bytes
    # Error / steering
    rx_steer_missed_packets
    rx_out_of_buffer
    rx_if_down_packets
    rx_wqe_err
    tx_cqe_err
    # PHY errors
    rx_crc_errors_phy
    rx_symbol_err_phy
    rx_discards_phy
    tx_discards_phy
    tx_errors_phy
    # PCIe
    rx_pci_signal_integrity
    tx_pci_signal_integrity
    outbound_pci_stalled_rd
    outbound_pci_stalled_wr
    outbound_pci_stalled_rd_events
    outbound_pci_stalled_wr_events
    # PFC
    rx_pause_ctrl_phy
    tx_pause_ctrl_phy
    rx_global_pause_duration
    tx_global_pause_duration
    # Link
    link_down_events_phy
    # Other
    rx_oversize_pkts_buffer
)

# ---- Helper functions ----

build_grep_pattern() {
    local pattern=""
    for c in "${ETHTOOL_COUNTERS[@]}"; do
        [ -z "$pattern" ] && pattern="$c:" || pattern="$pattern|$c:"
    done
    echo "$pattern"
}

GREP_PATTERN=$(build_grep_pattern)

# Parse ethtool output → "counter_name,value" per line
parse_ethtool() {
    grep -E "$GREP_PATTERN" | sed 's/^[[:space:]]*//' | sed 's/: /,/' | sort
}

take_snapshots() {
    local prefix=$1
    # Client: local (we're running on 225)
    ethtool -S $NIC 2>/dev/null | parse_ethtool > "${prefix}_client" &
    local pid_c=$!
    # Server: SSH
    ssh "$REMOTE" "ethtool -S $NIC 2>/dev/null" | parse_ethtool > "${prefix}_server" &
    local pid_s=$!
    wait $pid_c $pid_s
}

compute_delta() {
    local scenario=$1 trial=$2 before_prefix=$3 after_prefix=$4 csv=$5

    for side in client server; do
        local bf="${before_prefix}_${side}"
        local af="${after_prefix}_${side}"
        [ ! -f "$bf" ] || [ ! -f "$af" ] && continue

        while IFS=, read -r name val_before; do
            val_after=$(grep "^${name}," "$af" 2>/dev/null | cut -d, -f2)
            if [ -n "$val_after" ]; then
                delta=$((val_after - val_before))
                echo "${scenario},${trial},${side},${name},${val_before},${val_after},${delta}"
            fi
        done < "$bf"
    done >> "$csv"
}

run_client() {
    local sc=$1 trials=${2:-1}
    pushd "$CLIENT_WORK_DIR" > /dev/null
    "$SCRIPT_DIR/client" "$sc" "$trials" 2>&1
    popd > /dev/null
}

start_daemon() {
    ssh "$REMOTE" "pkill -f counter_daemon.sh" 2>/dev/null || true
    ssh "$REMOTE" "pkill -f 'socat.*18516'" 2>/dev/null || true
    sleep 1
    ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup bash counter_daemon.sh > /tmp/counter_daemon.log 2>&1 < /dev/null & exit"
    sleep 1
    echo "[ethtool] counter_daemon started on 224"
}

stop_daemon() {
    ssh "$REMOTE" "pkill -f counter_daemon.sh" 2>/dev/null || true
    ssh "$REMOTE" "pkill -f 'socat.*18516'" 2>/dev/null || true
}

start_server() {
    ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup ./server > /tmp/server.log 2>&1 < /dev/null & exit"
    sleep 1
}

stop_server() {
    ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true
    sleep 1
}

kill_server() {
    ssh "$REMOTE" "pkill -9 -f './server'" 2>/dev/null || true
}

wait_for_signal() {
    local timeout=${1:-3000}
    local elapsed=0
    while [ ! -f /tmp/ready_to_inject ] && [ $elapsed -lt $timeout ]; do
        sleep 0.1
        elapsed=$((elapsed + 1))
    done
    rm -f /tmp/ready_to_inject
    [ $elapsed -lt $timeout ]
}

# ---- Scenario runners ----

run_standard_scenario() {
    local sc=$1
    local name=${NAMES[$sc]}
    local csv="$RESULT_DIR/ethtool_${name}.csv"

    echo ""
    echo "=========================================="
    echo "  Ethtool: $name (scenario $sc, $NUM_TRIALS trials)"
    echo "=========================================="

    echo "scenario,trial,side,counter,before,after,delta" > "$csv"

    for ((t=0; t<NUM_TRIALS; t++)); do
        echo "--- $name trial $t ---"

        stop_server
        start_server

        # Before snapshot
        take_snapshots "${TMPDIR_SNAP}/before_t${t}"

        # Run one trial
        run_client "$sc" 1 || echo "  (client exited with error — expected for some scenarios)"

        sleep 2

        # After snapshot
        take_snapshots "${TMPDIR_SNAP}/after_t${t}"

        compute_delta "$name" "$t" "${TMPDIR_SNAP}/before_t${t}" "${TMPDIR_SNAP}/after_t${t}" "$csv"

        # Cleanup temp snapshots
        rm -f "${TMPDIR_SNAP}"/before_t${t}_* "${TMPDIR_SNAP}"/after_t${t}_*

        echo "  -> delta recorded"
    done

    echo "  Results: $csv"
}

run_f8b() {
    local sc=9
    local name="RETRY_EXC_PROC_KILL"
    local csv="$RESULT_DIR/ethtool_${name}.csv"

    echo ""
    echo "=========================================="
    echo "  Ethtool: $name ($NUM_TRIALS trials)"
    echo "=========================================="

    echo "scenario,trial,side,counter,before,after,delta" > "$csv"

    for ((t=0; t<NUM_TRIALS; t++)); do
        echo "--- $name trial $t ---"
        rm -f /tmp/ready_to_inject /tmp/inject_done

        stop_server
        start_server

        # Before snapshot
        take_snapshots "${TMPDIR_SNAP}/before_t${t}"

        # Launch client in background
        pushd "$CLIENT_WORK_DIR" > /dev/null
        "$SCRIPT_DIR/client" "$sc" 1 &
        CLIENT_PID=$!
        popd > /dev/null

        if ! wait_for_signal 3000; then
            echo "ERROR: client did not signal readiness"
            kill $CLIENT_PID 2>/dev/null || true
            continue
        fi

        kill_server
        touch /tmp/inject_done
        wait $CLIENT_PID 2>/dev/null || true
        rm -f /tmp/inject_done

        sleep 2

        # After snapshot (server process dead, but NIC counters still readable)
        take_snapshots "${TMPDIR_SNAP}/after_t${t}"

        compute_delta "$name" "$t" "${TMPDIR_SNAP}/before_t${t}" "${TMPDIR_SNAP}/after_t${t}" "$csv"

        rm -f "${TMPDIR_SNAP}"/before_t${t}_* "${TMPDIR_SNAP}"/after_t${t}_*
        echo "  -> delta recorded"
    done

    echo "  Results: $csv"
}

# ---- Summary ----

summarize() {
    echo ""
    echo "=========================================="
    echo "  SUMMARY: Non-zero ethtool deltas"
    echo "=========================================="
    echo ""
    printf "%-28s %-7s %-35s %s\n" "SCENARIO" "SIDE" "COUNTER" "DELTAS (per trial)"
    printf "%s\n" "$(printf '=%.0s' {1..100})"

    for csv in "$RESULT_DIR"/ethtool_*.csv; do
        [ -f "$csv" ] || continue
        # Group by scenario+side+counter, show deltas where any trial is non-zero
        awk -F, 'NR>1 && $7 != 0 {
            key = $1 "," $3 "," $4
            deltas[key] = deltas[key] " " $7
        }
        END {
            for (k in deltas) {
                split(k, a, ",")
                printf "%-28s %-7s %-35s %s\n", a[1], a[2], a[3], deltas[k]
            }
        }' "$csv"
    done | sort

    echo ""
    echo "=========================================="
}

# ---- Main ----

mkdir -p "$RESULT_DIR"

echo "[ethtool] Building on both sides..."
ssh "$REMOTE" "cd $REMOTE_DIR && make" 2>&1 | tail -3
make -C "$SCRIPT_DIR" 2>&1 | tail -3

start_daemon
trap 'set +e; stop_daemon; stop_server; rm -rf "$CLIENT_WORK_DIR" "$TMPDIR_SNAP"' EXIT

if [ -n "$1" ]; then
    sc=$1
    case $sc in
        9)  run_f8b ;;
        *)  run_standard_scenario "$sc" ;;
    esac
else
    for sc in 1 2 3 4 5 6 7 8 11; do
        run_standard_scenario "$sc"
    done
    run_f8b
fi

summarize

echo ""
echo "All ethtool experiments complete."
echo "Results in $RESULT_DIR/"
echo "Run: cat $RESULT_DIR/ethtool_*.csv | awk -F, 'NR==1||(\$7!=0)' to see all non-zero deltas"
