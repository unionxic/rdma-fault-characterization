#!/bin/bash
# ============================================================================
# [한국어 요약] Phase 1 (SSD × RDMA) 메인 orchestrator — 225(initiator)에서 실행
#
# 한 트라이얼의 흐름 (run_trial 함수):
#   ssh로 224에 fault 스택 구성(target_setup) → nvme connect (원격 SSD가
#   /dev/nvmeXnY로 붙음) → dmesg 마커 + 양쪽 RDMA 카운터 스냅샷(before)
#   → 시나리오별 워크로드(fio / nvme read / dd) → 스냅샷(after)
#   → disconnect → teardown → CSV 한 행 기록 ("row written"이 완료 신호).
#
# 관측 tuple = (NVMe status/errno, dmesg 델타, RDMA HW counter 델타, latency).
#   wc_status/vendor_err 컬럼이 없는 이유: NVMe-oF의 QP는 커널(nvme-rdma)
#   소유라 유저스페이스가 CQE를 못 봄 — 구현 레이어 제약(1_이론 7절)의 실증.
#
# 하드닝 원칙 (수정 7회의 교훈, agent-memory project_storage_rdma.md 참고):
#   모든 외부 호출에 timeout 상한 / ssh는 SUDO_USER로 강등(키가 사용자 소유)
#   / grep 빈 매치의 pipefail 즉사 방지(|| true) / 실패 경로에서 disconnect
#   보장(stale 컨트롤러가 다음 connect를 전부 막음).
#
# 사용: sudo ./run_storage_experiment.sh <시나리오|all> [trials]
#       FAIL_SLOW_ONLY=<ms> 로 sweep 한 단계만 재실행 가능.
# ============================================================================
# run_storage_experiment.sh — Phase-1 (SSD x RDMA) orchestrator. Runs from the
# INITIATOR (225). For each (scenario, trial): drives the target over SSH to
# build the fault, connects the nvme-rdma namespace, snapshots RDMA counters +
# dmesg on BOTH nodes, runs the scenario workload, collects the observation
# tuple, disconnects, tears the target down, and appends one CSV row.
#
# Observation tuple (kernel-consumer CQE is INVISIBLE — see README):
#   (NVMe status/errno) + (initiator dmesg delta) + (RDMA HW-counter delta, both
#    nodes) + (latency distribution).  There is NO wc_status/vendor_err column:
#   the NVMe-oF initiator QP is kernel-owned, so userspace cannot read its CQEs.
#
# Usage: sudo ./run_storage_experiment.sh <SCENARIO|all> [trials]
#   SCENARIO : a full-name label, or 'all' for the whole sweep
#   trials   : measured trials per scenario (default 5). FAIL_SLOW multiplies
#              this by the delay sweep (1/10/100/1000/5000/35000 ms).
#
# ROOT REQUIRED: /dev/kmsg marker, dmesg, nvme connect/disconnect, debugfs.
#
# See README.md for hypotheses (H1/H2/H3 + partial), per-scenario detail, and
# how to read the CSV.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_storage.sh
source "${HERE}/lib_storage.sh"

SCENARIO_ARG="${1:-}"
TRIALS="${2:-5}"
[ -n "$SCENARIO_ARG" ] || die "usage: $0 <SCENARIO|all> [trials]"
[ "$(id -u)" = "0" ] || die "must run as root (sudo): needs /dev/kmsg, dmesg, nvme connect, debugfs"

RESULTS="${HERE}/results/raw"
CSV="${RESULTS}/storage_rdma.csv"
mkdir -p "$RESULTS"
TMP="$(mktemp -d /tmp/storage_rdma.XXXXXX)"
trap 'rm -rf "$TMP"; nvme disconnect -n "$NQN" >/dev/null 2>&1 || true; ssh_target "sudo -n ${REMOTE_DIR}/target_teardown.sh" >/dev/null 2>&1 || true' EXIT

readonly CSV_HEADER="scenario,param,trial,nvme_status_or_errno,latency_us_p50,latency_us_p99,latency_us_max,counter_deltas,dmesg_signature,detect_ms,valid_prefix_bytes,notes"
[ -f "$CSV" ] || echo "$CSV_HEADER" > "$CSV"

# ---------------------------------------------------------------------------
# build the partial-read checker once
# ---------------------------------------------------------------------------
if [ ! -x "${HERE}/check_partial_read" ]; then
  log "compiling check_partial_read ..."
  cc -O2 -o "${HERE}/check_partial_read" "${HERE}/check_partial_read.c"
fi

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
csv_clean() { # strip commas/quotes/newlines so free-text is CSV-safe
  printf '%s' "$1" | tr ',\n"' '   ' | tr -s ' '
}

# All target hops go through ssh_target (lib_storage.sh): the harness runs as
# root but the SSH keys belong to $SUDO_USER, so the hop is made as that user.
# `sudo -n` on the remote side fails loudly (instead of hanging on a password
# prompt) if the passwordless-sudo whitelist is missing — see README.
remote_setup()    { ssh_target "sudo -n ${REMOTE_DIR}/target_setup.sh $1 ${2:-}"; }
remote_teardown() { ssh_target "sudo -n ${REMOTE_DIR}/target_teardown.sh" >/dev/null 2>&1 || true; }
remote_crash()    { ssh_target "sudo -n ${REMOTE_DIR}/target_crash.sh"; }
# Phase 1b E3(TARGET_RECOVERY): crash가 지운 nvmet 포트를 재생성(crash의 역연산).
# sudoers 화이트리스트에 target_restore.sh 한 줄이 필요하다(README 참고).
remote_restore()  { ssh_target "sudo -n ${REMOTE_DIR}/target_restore.sh"; }

remote_snapshot() { # -> "name,value" lines from target sysfs (no lib sourcing)
  ssh_target 'd=$(ls /sys/class/infiniband 2>/dev/null | head -1); \
    for f in /sys/class/infiniband/$d/ports/1/hw_counters/* /sys/class/infiniband/$d/ports/1/counters/*; do \
      [ -f "$f" ] && echo "$(basename "$f"),$(cat "$f" 2>/dev/null)"; done'
}

# Build the TARGET_CRASH connect flags from what THIS nvme-cli actually
# understands (probed via --help): flag spellings vary across versions and one
# unknown flag rejects the whole command — which silently dropped BOTH timeouts
# and let a crashed target pin dd in D-state for ctrl_loss_tmo (600s default).
# ctrl-loss-tmo alone still bounds error surfacing at ~30s if fast-io-fail is
# unavailable.
crash_connect_flags() {
  local help flags=""
  help="$(nvme connect --help 2>&1 || true)"
  printf '%s' "$help" | grep -q 'ctrl-loss-tmo'     && flags="--ctrl-loss-tmo=30"
  if   printf '%s' "$help" | grep -q 'fast_io_fail_tmo'; then flags="$flags --fast_io_fail_tmo=10"
  elif printf '%s' "$help" | grep -q 'fast-io-fail-tmo'; then flags="$flags --fast-io-fail-tmo=10"
  fi
  [ -n "$flags" ] || log "WARN: this nvme-cli exposes no loss-timeout flags — TARGET_CRASH error surfacing may take minutes"
  echo "$flags"
}

# Phase 1b: 시나리오별로 다른 연결 레버가 필요해 파라미터화한 버전.
# crash_connect_flags(기존 시나리오 전용)는 손대지 않고 별도로 둔다.
#   <ctrl_loss_tmo|""> <fast_io_fail|"">  (둘 다 초 단위, 빈 값이면 미적용)
# 알 수 없는 플래그 하나가 connect 전체를 거부시키므로 --help로 실제 철자를 확인.
build_connect_flags() {
  local clt="$1" fif="$2" help flags=""
  help="$(nvme connect --help 2>&1 || true)"
  if [ -n "$clt" ] && printf '%s' "$help" | grep -q 'ctrl-loss-tmo'; then flags="--ctrl-loss-tmo=${clt}"; fi
  if [ -n "$fif" ]; then
    if   printf '%s' "$help" | grep -q 'fast_io_fail_tmo'; then flags="$flags --fast_io_fail_tmo=${fif}"
    elif printf '%s' "$help" | grep -q 'fast-io-fail-tmo'; then flags="$flags --fast-io-fail-tmo=${fif}"
    else log "WARN: nvme-cli has no fast-io-fail flag — hang may persist despite io_timeout tuning"
    fi
  fi
  echo "$flags"
}

# Phase 1b 공용: 단일 4KiB read의 왕복 시간(µs)과 rc를 반환. good-LBA latency
# (E1)나 재개 프로브(E3)에 쓴다. bs=4k 기준 skip은 4KiB 블록 단위.
#   <dev> <byte_offset> [timeout_s]  ->  "<rc> <us>"
timed_read_us() {
  local dev="$1" off="$2" tmo="${3:-30}" t0 t1 rc
  t0="$(date +%s%N)"
  if timeout "$tmo" dd if="$dev" of=/dev/null bs=4k count=1 skip=$(( off / 4096 )) iflag=direct >/dev/null 2>&1; then rc=0; else rc=$?; fi
  t1="$(date +%s%N)"
  echo "$rc $(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.0f",(b-a)/1e3}')"
}

# Phase 1b E4 공용: 초기자 RDMA 에러 카운터를 EARLY_DETECT_POLL_MS 간격으로 폴링,
# EARLY_DETECT_COUNTERS 중 하나라도 시작값(baseline)을 넘긴 첫 시각(ns)을 outfile에
# 기록하고 종료. deadline(초) 안에 아무 이상이 없으면 "NONE"을 기록. 백그라운드로
# 실행하고 트라이얼 끝에서 kill한다(자체 deadline으로도 반드시 종료됨).
#   <outfile> <deadline_s>
poll_counters_until_anomaly() {
  local out="$1" deadline_s="$2"
  local hw; hw="/sys/class/infiniband/$(rdma_device)/ports/1/hw_counters"
  local c cur names="$EARLY_DETECT_COUNTERS"
  # baseline 스냅샷 (연관 배열 — 함수 로컬)
  local -A base
  for c in $names; do base["$c"]="$(cat "${hw}/${c}" 2>/dev/null || echo 0)"; done
  local poll_s; poll_s="$(awk -v m="$EARLY_DETECT_POLL_MS" 'BEGIN{printf "%.3f", m/1000}')"
  local end=$(( SECONDS + deadline_s ))
  while [ "$SECONDS" -lt "$end" ]; do
    for c in $names; do
      cur="$(cat "${hw}/${c}" 2>/dev/null || echo 0)"
      case "$cur" in ''|*[!0-9]*) cur=0;; esac
      if [ "$cur" -gt "${base[$c]:-0}" ]; then
        printf '%s %s\n' "$(date +%s%N)" "$c" > "$out"
        return 0
      fi
    done
    sleep "$poll_s"
  done
  echo "NONE none" > "$out"
}

connect_nvme() {  # [extra-flags] -> connect and return the fabric namespace device
  # TARGET_CRASH passes short ctrl-loss/fast-io-fail timeouts: without them the
  # kernel requeues I/O during reconnect for ctrl_loss_tmo (default 600s) and a
  # blocked dd would ignore our deadline entirely (D-state). Fall back to a
  # plain connect if this nvme-cli doesn't know the flags.
  local extra="${1:-}"
  if [ -n "$extra" ]; then
    # shellcheck disable=SC2086
    nvme connect -t rdma -a "$RDMA_IP" -s "$RDMA_SVCID" -n "$NQN" $extra >/dev/null 2>&1 || \
      { log "connect with '$extra' failed — falling back to plain connect"; extra=""; }
  fi
  if [ -z "$extra" ]; then
    nvme connect -t rdma -a "$RDMA_IP" -s "$RDMA_SVCID" -n "$NQN" >/dev/null 2>&1 || \
      { log "nvme connect failed"; return 1; }
  fi
  local dev="" i
  for i in $(seq 1 50); do            # up to ~10s for the namespace to appear
    dev="$(find_fabric_namespace || true)"
    [ -n "$dev" ] && break
    sleep 0.2
  done
  # If the namespace never shows, DISCONNECT before failing: leaving the
  # controller behind blocks every later `nvme connect` in this run (this is
  # exactly what turned one bad trial into a failed whole BASELINE run).
  [ -n "$dev" ] || { log "namespace never appeared after connect — disconnecting"; \
                     nvme disconnect -n "$NQN" >/dev/null 2>&1 || true; return 1; }
  assert_not_boot_disk "$dev"         # HARD GATE: never the boot disk
  echo "$dev"
}

# timeout 30: `nvme disconnect` can block in the kernel while a controller is
# mid-reset/reconnect with requeued I/O — never let cleanup itself hang a trial.
disconnect_nvme() { timeout 30 nvme disconnect -n "$NQN" >/dev/null 2>&1 || true; }

dmesg_signature() { # <marker>  -> condensed unique keyword lines after marker
  # `|| true` is load-bearing: on a HEALTHY trial (BASELINE, small FAIL_SLOW)
  # there are no matching lines, grep exits 1, and pipefail would turn that
  # into a silent set -e death right before the CSV row is written.
  local marker="$1" out
  out="$(dmesg -t 2>/dev/null | awk -v m="$marker" 'index($0,m){seen=1;next} seen{print}' \
    | grep -iE 'nvme|nvmet|I/O error|blk_update|EIO|timeout|reset|reconnect|retry|keep-?alive|rdma|abort|controller' \
    | sort -u | tr '\n' ';' | cut -c1-280 || true)"
  echo "${out:-none}"
}

nvme_read_status() { # <dev> <slba> <nlb0based> <bytes> -> NVMe status/errno string
  local dev="$1" slba="$2" nlb="$3" bytes="$4" out rc
  # capture stderr (nvme-cli prints the NVMe status line there); discard data.
  # `if` guards set -e: these reads are EXPECTED to fail in fault scenarios.
  # timeout 60: a wedged namespace must not hang the harness (rc=124 recorded).
  if out="$(timeout 60 nvme read "$dev" -s "$slba" -c "$nlb" -z "$bytes" 2>&1 >/dev/null)"; then rc=0; else rc=$?; fi
  if [ "$rc" = 0 ]; then echo "Success"; else
    # keep the human-readable status line if present, else the errno rc.
    # (|| true: no matching line must not kill the harness via pipefail.)
    local s; s="$(printf '%s' "$out" | grep -iE 'status|error' | head -1 || true)"
    echo "${s:-rc=$rc}"
  fi
}

fio_latency() { # <dev> <bs> <io_size> [rw] -> "p50 p99 max errcode"
  local dev="$1" bs="$2" size="$3" rw="${4:-read}"
  # timeout 120: hard upper bound — the slowest legitimate workload here is
  # FAIL_SLOW 5000ms x 4 I/Os (~20s); anything past 120s is a wedge, not data.
  timeout 120 fio --name=st --filename="$dev" --direct=1 --rw="$rw" --bs="$bs" \
      --io_size="$size" --ioengine=psync --iodepth=1 --numjobs=1 \
      --group_reporting --output-format=json > "${TMP}/fio.json" 2>/dev/null || true
  # NA fallback: a killed/errored fio leaves truncated JSON; the parser must
  # not turn that into empty CSV fields or a set -e death.
  python3 "${HERE}/parse_fio.py" "${TMP}/fio.json" "$rw" 2>/dev/null || echo "NA NA NA 124"
}

# ---------------------------------------------------------------------------
# one trial
# ---------------------------------------------------------------------------
run_trial() {
  local scenario="$1" param="$2" trial="$3"
  log "=== $scenario param=${param:-none} trial=$trial ==="

  # 1. target setup. 대부분은 scenario/param을 그대로 넘기지만, Phase 1b
  #    COUNTER_EARLY_DETECT는 모드(param)에 따라 기존 target 라벨로 매핑한다:
  #    crash 모드 = loop 직결(COUNTER_EARLY_DETECT), failslow 모드 = FAIL_SLOW 35s.
  local setup_label="$scenario" setup_param="$param"
  case "$scenario" in
    "$SC_TIMEOUT_TUNING")
      # target은 dm-delay 35000ms 고정. param(=io_timeout 초)은 초기자 전용이라
      # target에 넘기지 않는다.
      setup_param="$TIMEOUT_TUNING_DELAY_MS" ;;
    "$SC_COUNTER_EARLY_DETECT")
      if [ "$param" = "failslow" ]; then setup_label="$SC_FAIL_SLOW"; setup_param="$COUNTER_ED_FAILSLOW_MS"
      else setup_label="$SC_COUNTER_EARLY_DETECT"; setup_param=""; fi ;;
  esac
  remote_setup "$setup_label" "$setup_param" >/dev/null || { log "setup failed; skipping"; return; }

  # 2. connect. 시나리오별 에러-표면화/재연결 정책 레버(연결 플래그)가 다르다.
  #    기존 TARGET_CRASH 동작은 그대로 두고 Phase 1b 분기만 additive로 추가.
  local connect_extra=""
  case "$scenario" in
    "$SC_TARGET_CRASH")         connect_extra="$(crash_connect_flags)" ;;
    "$SC_TIMEOUT_TUNING")       connect_extra="$(build_connect_flags '' "$TIMEOUT_TUNING_FAST_IO_FAIL")" ;;
    "$SC_TARGET_RECOVERY")      connect_extra="$(build_connect_flags "$TARGET_RECOVERY_CTRL_LOSS_TMO" '')" ;;
    "$SC_COUNTER_EARLY_DETECT") [ "$param" = "crash" ] && connect_extra="$(crash_connect_flags)" ;;
  esac
  local dev
  dev="$(connect_nvme "$connect_extra")" || { remote_teardown; return; }
  log "connected namespace: $dev"

  # 3. dmesg marker (initiator) + before counters (both nodes)
  local marker="STORAGE_RDMA_MARK ${scenario} ${param:-x} ${trial} $(date +%s%N)"
  echo "$marker" > /dev/kmsg 2>/dev/null || true
  snapshot_counters > "${TMP}/init_before.txt" || true
  remote_snapshot   > "${TMP}/tgt_before.txt"  || true

  # 4. workload (per scenario) -> sets: status, p50 p99 max, detect_ms, valid_prefix
  log "workload running — silence for tens of seconds is NORMAL (fio/nvme in progress); wait for 'row written'"
  local status="" p50="NA" p99="NA" pmax="NA" detect_ms="" valid_prefix="" notes=""
  local lba_sz=512

  case "$scenario" in
    "$SC_BASELINE")
      read -r p50 p99 pmax err <<<"$(fio_latency "$dev" 4k 64M read)" || true
      status="Success"; notes="fio_err=$err"
      ;;

    "$SC_MEDIA_ERROR_READ")
      local slba=$(( MEDIA_BADBLOCK_OFF / lba_sz ))
      status="$(nvme_read_status "$dev" "$slba" 7 4096)"   # 8 LBAs = 4KiB
      # latency of a good read for reference
      read -r p50 p99 pmax err <<<"$(fio_latency "$dev" 4k 16M read)" || true
      notes="badblock_off=${MEDIA_BADBLOCK_OFF} fio_good_err=$err"
      ;;

    "$SC_MEDIA_ERROR_PARTIAL_READ")
      local nlb=$(( PARTIAL_READ_LEN / lba_sz - 1 ))
      status="$(nvme_read_status "$dev" 0 "$nlb" "$PARTIAL_READ_LEN")"
      # the key measurement: how much valid prefix landed in the buffer
      local cpr; cpr="$("${HERE}/check_partial_read" "$dev" 0 "$PARTIAL_READ_LEN" 2>/dev/null || true)"
      valid_prefix="$(printf '%s' "$cpr" | sed -n 's/.*valid_prefix_bytes=\([0-9]*\).*/\1/p')"
      local cerrno; cerrno="$(printf '%s' "$cpr" | sed -n 's/.*errno=\([0-9]*\).*/\1/p')"
      pmax="NA"
      notes="badblock_off=${PARTIAL_BADBLOCK_OFF} read_len=${PARTIAL_READ_LEN} pread_errno=${cerrno} ${cpr}"
      ;;

    "$SC_FULL_IO_FAIL")
      status="$(nvme_read_status "$dev" 0 7 4096)"          # any read errors
      read -r p50 p99 pmax err <<<"$(fio_latency "$dev" 4k 4M read)" || true
      notes="fio_err=$err (all I/O should fail)"
      ;;

    "$SC_FAIL_SLOW")
      # param = delay ms. dm-delay stalls EVERY I/O by param ms, so scale the
      # I/O count down as the delay grows or one trial takes minutes-to-hours
      # (64 x 35s would be ~37min).
      if [ "$param" -ge 35000 ]; then
        # Past io_timeout(30s) the kernel does NOT return an error to the app:
        # it resets the controller, reconnects, REQUEUES the I/O — which hits
        # the 35s delay again -> unbounded reset loop, the read never returns.
        # That unbounded hang IS the observation. Bound it: single background
        # 4k read, 100s deadline, then a forced disconnect fails the stuck I/O.
        local t0 t1 hung=""
        t0="$(date +%s%N)"
        ( dd if="$dev" of=/dev/null bs=4k count=1 iflag=direct >/dev/null 2>&1; \
          echo $? > "${TMP}/failslow_rc" ) &
        local ddpid=$! waited=0
        while kill -0 "$ddpid" 2>/dev/null && [ "$waited" -lt 100 ]; do
          sleep 1; waited=$((waited+1))
        done
        if kill -0 "$ddpid" 2>/dev/null; then
          hung=1
          disconnect_nvme            # force-fail the requeued I/O to free dd
          wait "$ddpid" 2>/dev/null || true
        fi
        t1="$(date +%s%N)"
        pmax="$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.0f",(b-a)/1e3}')"
        local ddrc; ddrc="$(cat "${TMP}/failslow_rc" 2>/dev/null || echo NA)"
        if [ -n "$hung" ]; then
          status="io_never_returns(>100s reset loop; freed by disconnect)"
        else
          status="returned dd_rc=${ddrc} after $(awk -v u="$pmax" 'BEGIN{printf "%.1fs",u/1e6}')"
        fi
        notes="delay_ms=${param} single-io deadline=100s dd_rc=${ddrc}"
      else
        local iosz=256k                     #  64 I/Os for sub-second delays
        [ "$param" -ge 1000 ] && iosz=16k   #   4 I/Os (~4-20s trial)
        read -r p50 p99 pmax err <<<"$(fio_latency "$dev" 4k "$iosz" read)" || true
        status="$( [ "$err" = 0 ] && echo "Success(latency-only)" || echo "errno=$err(timeout/abort?)" )"
        notes="delay_ms=${param} io_size=${iosz} fio_err=$err"
      fi
      ;;

    "$SC_TARGET_CRASH")
      # sustained reader in background; measure time from crash trigger to first
      # I/O error return. Bounded by CRASH_DEADLINE so nvme-rdma reconnect retries
      # (default ctrl_loss_tmo can be very long) cannot hang the harness — the
      # keepalive-vs-RETRY_EXC ORDERING is read from dmesg_signature regardless.
      local CRASH_DEADLINE=60
      local errfile="${TMP}/crash_err.ns"
      # Each dd is wrapped in `timeout`: a single read can block in D-state while
      # nvme-rdma requeues I/O during reconnect, and the deadline check between
      # iterations would never run. timeout(124) also exits the loop.
      ( deadline=$((SECONDS + CRASH_DEADLINE))
        while timeout "$CRASH_DEADLINE" dd if="$dev" of=/dev/null bs=1M count=1 iflag=direct >/dev/null 2>&1; do
          [ "$SECONDS" -lt "$deadline" ] || { echo "DEADLINE" > "${errfile}.flag"; break; }
        done
        date +%s%N > "$errfile" ) &
      local reader_pid=$!
      sleep 0.5                                  # ensure I/O in flight
      local t0; t0="$(date +%s%N)"
      remote_crash >/dev/null 2>&1 || true       # target dies here
      wait "$reader_pid" 2>/dev/null || true
      local t1; t1="$(cat "$errfile" 2>/dev/null || date +%s%N)"
      detect_ms="$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.1f",(b-a)/1e6}')"
      status="io_error_after_crash"
      local hitdl=""; [ -f "${errfile}.flag" ] && hitdl=" DEADLINE_HIT(${CRASH_DEADLINE}s)"
      notes="detect initiator-local; see dmesg_signature for keepalive-vs-RETRY_EXC${hitdl}"
      ;;

    "$SC_INITIATOR_STATUS_INJECT")
      # CONTROL: forge an NVMe status LOCALLY via debugfs fault injection. This
      # does NOT traverse the fabric (Fable note 1) — it is the initiator-error
      # control, deliberately separated from target-origin scenarios.
      local ctrl_ns; ctrl_ns="$(basename "$dev")"          # e.g. nvme1n1
      local fdir="/sys/kernel/debug/${ctrl_ns}/fault_inject"
      if [ -d "$fdir" ]; then
        echo "$INJECT_STATUS"       > "${fdir}/status"       2>/dev/null || true
        echo "$INJECT_DONT_RETRY"   > "${fdir}/dont_retry"   2>/dev/null || true
        echo "$INJECT_TIMES"        > "${fdir}/times"        2>/dev/null || true
        echo "$INJECT_PROBABILITY"  > "${fdir}/probability"  2>/dev/null || true
        status="$(nvme_read_status "$dev" 0 7 4096)"
        echo 0 > "${fdir}/probability" 2>/dev/null || true   # disable after
        notes="CONTROL local inject status=${INJECT_STATUS} (no fabric path)"
      else
        status="NA(no fault_inject dir)"
        notes="CONTROL: ${fdir} absent — need CONFIG_FAULT_INJECTION + nvme fault hooks"
      fi
      ;;

    # ===================== Phase 1b (신호→복구 실증) =====================

    "$SC_FAULT_ISOLATION")
      # NVMe 에러는 per-command로 격리된다 — 불량 read 하나가 실패해도 연결과
      # 다른 블록은 생존(⟷ RDMA는 에러 한 번에 QP 전체가 죽음). 복구 = "재시도
      # 금지(DNR) + 다른 블록 사용". 측정 구간 3개:
      #  (a) 불량 LBA read → 에러 + DNR 비트(nvme read 출력에서 파싱)
      #  (b) 즉시 정상 LBA read → 성공 여부 + latency(BASELINE 대비 열화)
      #  (c) 불량 read를 FAULT_ISO_REPEAT회 반복 후에도 정상 LBA 정상 + reset 없음
      local badlba=$(( MEDIA_BADBLOCK_OFF / lba_sz ))
      # (a) 불량 read 1회 — 출력 원문에서 DNR 토큰과 status 라인 파싱.
      local badout badrc dnr="no" badstat
      if badout="$(timeout 60 nvme read "$dev" -s "$badlba" -c 7 -z 4096 2>&1 >/dev/null)"; then badrc=0; else badrc=$?; fi
      if printf '%s' "$badout" | grep -qi 'DNR'; then dnr="yes"; fi
      badstat="$(printf '%s' "$badout" | grep -iE 'status|error' | head -1 || true)"
      # (b) 즉시 정상 LBA(오프셋 0) read latency — 불량 직후 연결 생존 확인.
      local goodrc goodus
      read -r goodrc goodus <<<"$(timed_read_us "$dev" 0 30)" || true
      # (c) 불량 read 연속 반복 후 정상 LBA 재확인.
      local i
      for i in $(seq 1 "$FAULT_ISO_REPEAT"); do
        timeout 30 nvme read "$dev" -s "$badlba" -c 7 -z 4096 >/dev/null 2>&1 || true
      done
      local good2rc good2us
      read -r good2rc good2us <<<"$(timed_read_us "$dev" 0 30)" || true
      # 컨트롤러 reset/reconnect가 있었는지(있으면 명령-격리 가설 반증).
      local ctrl_reset="no"
      if dmesg -t 2>/dev/null | awk -v m="$marker" 'index($0,m){s=1;next} s' \
           | grep -qiE 'reset|reconnect|resetting controller'; then ctrl_reset="yes"; fi
      status="bad_read:${badstat:-rc=$badrc}|DNR=${dnr}"
      notes="good_read_us=${goodus}(rc=${goodrc}) after_${FAULT_ISO_REPEAT}x_bad:good_read_us=${good2us}(rc=${good2rc}) ctrl_reset=${ctrl_reset} badblock_off=${MEDIA_BADBLOCK_OFF} (detect_ms 미사용)"
      ;;

    "$SC_TIMEOUT_TUNING")
      # 정책 레버로 hang을 유한 에러로 바꾼다. target에 dm-delay 35s가 걸려 있고,
      # 초기자는 io_timeout(param 초)을 낮춰 + fast_io_fail_tmo=5(위 connect_extra)로
      # "표면화 시간이 정책값을 추종하는가"를 본다. 측정 구간: 단일 4k read가
      # 에러를 반환하기까지의 time-to-error(pmax µs).
      local ns_base; ns_base="$(basename "$dev")"
      # blk-mq sysfs queue/io_timeout 단위는 ms(커널 block/blk-sysfs.c
      # queue_io_timeout_show = jiffies_to_msecs(q->rq_timeout)). nvme_core의
      # io_timeout(초, /sys/module/nvme_core/parameters/io_timeout)과 혼동 금지 —
      # 네임스페이스별 ms sysfs를 우선하고, 없으면 모듈 파라미터(초)로 폴백.
      local io_to_ms=$(( param * 1000 )) io_to_where=""
      # multipath head(nvmeXnY)는 bio 기반 큐라 queue/io_timeout이 read-only다
      # (Permission denied — 실측). 실제 blk-mq 타임아웃은 per-path 디바이스
      # (nvmeXcYnZ, /dev에는 안 보이지만 /sys/block에는 있음)의 큐에 산다.
      # 우리 NQN에 속한 path 디바이스를 찾아 그쪽에 ms 단위로 쓴다.
      # (모듈 파라미터 폴백은 "새 큐에만" 적용이라 이미 연결된 우리 ns에 무효
      #  — 폴백으로 부적합해 제거.)
      local pd psub wrote=0
      for pd in /sys/block/nvme*c*n*; do
        [ -e "${pd}/queue/io_timeout" ] || continue
        psub="$(cat "${pd}/device/subsysnqn" 2>/dev/null || true)"
        [ "$psub" = "$NQN" ] || continue
        if echo "$io_to_ms" 2>/dev/null > "${pd}/queue/io_timeout"; then
          wrote=$((wrote+1))
        fi
      done
      if [ "$wrote" -gt 0 ]; then
        io_to_where="path_io_timeout=${io_to_ms}ms(x${wrote})"
      elif echo "$io_to_ms" 2>/dev/null > "/sys/block/${ns_base}/queue/io_timeout"; then
        io_to_where="head_io_timeout=${io_to_ms}ms"
      else
        io_to_where="io_timeout_unwritable(head+paths)"
        log "WARN: io_timeout을 어디에도 못 씀 — 이 트라이얼은 기본 30s 정책으로 돈다"
      fi
      # 단일 4k read, 90s 감시 (정책값 5/10/30s를 크게 넘는 바운드).
      # `timeout N dd`는 못 쓴다 — D-state의 dd는 KILL도 무시해서 timeout이
      # 같이 갇힌다(실측). FAIL_SLOW 35000 분기와 동일하게 백그라운드 + 감시 +
      # disconnect(강제 I/O 실패)로 풀어준다.
      local t0 t1 ttrc="" tt_hung=""
      t0="$(date +%s%N)"
      ( dd if="$dev" of=/dev/null bs=4k count=1 iflag=direct >/dev/null 2>&1; \
        echo $? > "${TMP}/tt_rc" ) &
      local ttpid=$! ttwait=0
      while kill -0 "$ttpid" 2>/dev/null && [ "$ttwait" -lt 90 ]; do
        sleep 1; ttwait=$((ttwait+1))
      done
      if kill -0 "$ttpid" 2>/dev/null; then
        tt_hung=1
        disconnect_nvme
        wait "$ttpid" 2>/dev/null || true
      fi
      t1="$(date +%s%N)"
      pmax="$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.0f",(b-a)/1e3}')"
      local tte_s; tte_s="$(awk -v u="$pmax" 'BEGIN{printf "%.1f",u/1e6}')"
      ttrc="$(cat "${TMP}/tt_rc" 2>/dev/null || echo NA)"
      if [ -n "$tt_hung" ]; then
        # io_timeout만으로는 재큐 루프 때문에 여전히 hang — 그것도 결과
        # (fast_io_fail이 필수 레버라는 발견).
        status="still_hang(>90s despite io_timeout=${param}s — freed by disconnect)"
      elif [ "$ttrc" = "0" ]; then
        status="unexpected_success_after_${tte_s}s"
      else
        status="error_after_${tte_s}s(dd_rc=${ttrc})"
      fi
      notes="io_timeout_set=${io_to_where} fast_io_fail=${TIMEOUT_TUNING_FAST_IO_FAIL}s target_delay_ms=${TIMEOUT_TUNING_DELAY_MS} time_to_error_s=${tte_s}"
      ;;

    "$SC_TARGET_RECOVERY")
      # 죽음이 아니라 부활을 측정. 지속 read 중 crash → T초(param) 후 restore →
      # 초기자 nvme-rdma 자동 재연결로 I/O가 다시 성공하기까지의 시간. 측정 구간:
      #   crash_to_resume = 첫 재개 성공 − crash 시각  (detect_ms에 기록)
      #   restore_to_resume = 첫 재개 성공 − restore 시각 (reconnect_delay 10s 격자와 비교)
      local T="$param" RECOV_DEADLINE=120
      # 지속 read를 백그라운드로(각 dd는 timeout 15로 D-state 바운드).
      ( while timeout 15 dd if="$dev" of=/dev/null bs=1M count=1 iflag=direct >/dev/null 2>&1; do :; done ) &
      local bg=$!
      sleep 0.5
      local tc; tc="$(date +%s%N)"
      remote_crash >/dev/null 2>&1 || true            # target 死(포트 제거)
      sleep "$T"
      local tr; tr="$(date +%s%N)"
      remote_restore >/dev/null 2>&1 || true          # 부활(포트 재생성 = crash 역연산)
      # 재개 폴링: 성공 read가 나올 때까지(또는 deadline). 각 프로브 timeout 15.
      local tres="" endpoll=$(( SECONDS + RECOV_DEADLINE ))
      while [ "$SECONDS" -lt "$endpoll" ]; do
        if timeout 15 dd if="$dev" of=/dev/null bs=4k count=1 iflag=direct >/dev/null 2>&1; then
          tres="$(date +%s%N)"; break
        fi
        sleep 0.5
      done
      kill "$bg" 2>/dev/null || true; wait "$bg" 2>/dev/null || true
      if [ -n "$tres" ]; then
        detect_ms="$(awk -v a="$tc" -v b="$tres" 'BEGIN{printf "%.1f",(b-a)/1e6}')"   # crash→재개(ms)
        local rfr; rfr="$(awk -v a="$tr" -v b="$tres" 'BEGIN{printf "%.1f",(b-a)/1e6}')" # restore→재개(ms)
        status="recovered(${detect_ms}ms_from_crash)"
        notes="T=${T}s restore_to_resume_ms=${rfr} crash_to_resume_ms=${detect_ms} ctrl_loss_tmo=${TARGET_RECOVERY_CTRL_LOSS_TMO}s reconnect_delay=10s(default) hyp=ceil((T-detect)/10)*10"
      else
        status="no_resume(>${RECOV_DEADLINE}s after restore)"
        notes="T=${T}s NO_RESUME within ${RECOV_DEADLINE}s — restore failed or ctrl-loss exceeded"
        disconnect_nvme
      fi
      ;;

    "$SC_COUNTER_EARLY_DETECT")
      # RDMA 카운터가 앱 에러보다 얼마나 먼저 우는가(lead time)를 측정 — 기존
      # 06_recovery/early_detect의 스토리지판. 측정 구간:
      #   counter_first_anomaly = 카운터 첫 이상 − t0
      #   app_error             = 앱 read 에러 − t0  (crash 모드만; failslow는 hang=∞)
      #   lead                  = app_error − counter_first_anomaly
      local ED_DEADLINE=90 t0=""
      local cfile="${TMP}/ed_counter.txt"
      poll_counters_until_anomaly "$cfile" "$ED_DEADLINE" &
      local pollpid=$!
      local app_ms="NA"
      if [ "$param" = "crash" ]; then
        # 지속 read → crash → 실제 앱 에러 시각(파일에 기록).
        local afile="${TMP}/ed_app.txt"
        ( adl=$(( SECONDS + ED_DEADLINE ))
          while timeout 20 dd if="$dev" of=/dev/null bs=1M count=1 iflag=direct >/dev/null 2>&1; do
            [ "$SECONDS" -lt "$adl" ] || break
          done
          date +%s%N > "$afile" ) &
        local apppid=$!
        sleep 0.5
        t0="$(date +%s%N)"
        remote_crash >/dev/null 2>&1 || true
        wait "$pollpid" 2>/dev/null || true
        wait "$apppid" 2>/dev/null || true
        local ats; ats="$(cat "$afile" 2>/dev/null || echo NONE)"
        [ "$ats" != NONE ] && [ -n "$ats" ] && app_ms="$(awk -v a="$t0" -v b="$ats" 'BEGIN{printf "%.1f",(b-a)/1e6}')"
      else
        # failslow: target dm-delay 35s가 이미 걸려 있음. 앱은 reset 루프로 영원히
        # hang(Phase 1에서 앱은 영원히 모름 → lead=∞). 카운터 발화 시각 자체가 결과.
        sleep 0.5
        t0="$(date +%s%N)"
        ( timeout "$ED_DEADLINE" dd if="$dev" of=/dev/null bs=4k count=1 iflag=direct >/dev/null 2>&1 || true ) &
        local hangpid=$!
        wait "$pollpid" 2>/dev/null || true
        if kill -0 "$hangpid" 2>/dev/null; then disconnect_nvme; kill "$hangpid" 2>/dev/null || true; fi
        wait "$hangpid" 2>/dev/null || true
        app_ms="NA(hang)"
      fi
      local canom cts cname
      canom="$(cat "$cfile" 2>/dev/null || echo 'NONE none')"
      cts="$(printf '%s' "$canom" | awk '{print $1}')"
      cname="$(printf '%s' "$canom" | awk '{print $2}')"
      local counter_ms="NA" lead_ms="NA"
      if [ "$cts" != "NONE" ] && [ -n "$cts" ]; then
        counter_ms="$(awk -v a="$t0" -v b="$cts" 'BEGIN{printf "%.1f",(b-a)/1e6}')"
      fi
      if [ "$counter_ms" != "NA" ] && [ "$app_ms" != "NA" ] && [ "$app_ms" != "NA(hang)" ]; then
        lead_ms="$(awk -v c="$counter_ms" -v a="$app_ms" 'BEGIN{printf "%.1f",a-c}')"
      elif [ "$counter_ms" != "NA" ]; then
        lead_ms="inf(app_hang)"
      fi
      [ "$param" = "crash" ] && detect_ms="$app_ms"    # detect_ms = 앱 에러 시각(crash 모드만)
      status="counter_first=${cname}@${counter_ms}ms"
      notes="mode=${param} counter_first_anomaly_ms=${counter_ms} counter=${cname} app_error_ms=${app_ms} lead_ms=${lead_ms}"
      ;;
  esac

  # 5. after counters (both nodes) + dmesg signature
  snapshot_counters > "${TMP}/init_after.txt" || true
  remote_snapshot   > "${TMP}/tgt_after.txt"  || true
  local init_delta tgt_delta
  init_delta="$(counter_delta_summary "${TMP}/init_before.txt" "${TMP}/init_after.txt")"
  tgt_delta="$(counter_delta_summary "${TMP}/tgt_before.txt" "${TMP}/tgt_after.txt")"
  local counter_deltas="INIT:${init_delta} TGT:${tgt_delta}"
  local dsig; dsig="$(dmesg_signature "$marker")"

  # 6. disconnect + teardown
  disconnect_nvme
  remote_teardown

  # 7. append CSV
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "$scenario" "${param:-}" "$trial" \
    "$(csv_clean "$status")" "$p50" "$p99" "$pmax" \
    "$(csv_clean "$counter_deltas")" "$(csv_clean "$dsig")" \
    "${detect_ms:-}" "${valid_prefix:-}" "$(csv_clean "$notes")" >> "$CSV"
  log "row written (status='${status}')"
}

# ---------------------------------------------------------------------------
# scenario driver
# ---------------------------------------------------------------------------
run_scenario() {
  local scenario="$1" t ms io Tr mode
  case "$scenario" in
    "$SC_MEDIA_ERROR_READ")
      for t in $(seq 1 "$TRIALS"); do run_trial "$scenario" "$MEDIA_BADBLOCK_OFF" "$t"; done ;;
    "$SC_MEDIA_ERROR_PARTIAL_READ")
      for t in $(seq 1 "$TRIALS"); do run_trial "$scenario" "$PARTIAL_BADBLOCK_OFF" "$t"; done ;;
    "$SC_FAIL_SLOW")
      # FAIL_SLOW_ONLY=<ms> reruns a single sweep step without duplicating the
      # rest (e.g. `sudo FAIL_SLOW_ONLY=35000 ./run_storage_experiment.sh FAIL_SLOW 3`).
      local sweep=("${FAIL_SLOW_SWEEP[@]}")
      [ -n "${FAIL_SLOW_ONLY:-}" ] && sweep=("$FAIL_SLOW_ONLY")
      for ms in "${sweep[@]}"; do
        for t in $(seq 1 "$TRIALS"); do run_trial "$scenario" "$ms" "$t"; done
      done ;;

    # ---------------- Phase 1b ----------------
    "$SC_FAULT_ISOLATION")   # param = 불량 블록 오프셋(MEDIA_ERROR_READ와 동일)
      for t in $(seq 1 "$TRIALS"); do run_trial "$scenario" "$MEDIA_BADBLOCK_OFF" "$t"; done ;;
    "$SC_TIMEOUT_TUNING")    # param = io_timeout 초 스윕 {5,10,30}
      for io in "${TIMEOUT_TUNING_SWEEP[@]}"; do
        for t in $(seq 1 "$TRIALS"); do run_trial "$scenario" "$io" "$t"; done
      done ;;
    "$SC_TARGET_RECOVERY")   # param = restore 지연 T 초 스윕 {5,15,30}
      for Tr in "${TARGET_RECOVERY_SWEEP[@]}"; do
        for t in $(seq 1 "$TRIALS"); do run_trial "$scenario" "$Tr" "$t"; done
      done ;;
    "$SC_COUNTER_EARLY_DETECT")  # param = 모드 {crash, failslow}
      for mode in crash failslow; do
        for t in $(seq 1 "$TRIALS"); do run_trial "$scenario" "$mode" "$t"; done
      done ;;

    *)
      for t in $(seq 1 "$TRIALS"); do run_trial "$scenario" "" "$t"; done ;;
  esac
}

echo "=== Phase-1 SSD x RDMA experiment (initiator 225) ==="
echo "target ssh: $REMOTE_SSH   NQN: $NQN   trials/scenario: $TRIALS"
echo "CSV: $CSV"
echo

if [ "$SCENARIO_ARG" = "all" ]; then
  # `all`은 Phase 1만 돈다(정책 유지). Phase 1b는 `phase1b`로 별도 실행.
  for s in "${SCENARIOS[@]}"; do run_scenario "$s"; done
elif [ "$SCENARIO_ARG" = "phase1b" ]; then
  # Phase 1b 4개(E1~E4)를 순차 실행.
  for s in "${PHASE1B_SCENARIOS[@]}"; do run_scenario "$s"; done
else
  valid=0
  for s in "${SCENARIOS[@]}" "${PHASE1B_SCENARIOS[@]}"; do [ "$s" = "$SCENARIO_ARG" ] && valid=1; done
  [ "$valid" = 1 ] || die "unknown scenario '$SCENARIO_ARG' (valid: ${SCENARIOS[*]} ${PHASE1B_SCENARIOS[*]} all phase1b)"
  run_scenario "$SCENARIO_ARG"
fi

echo
echo "=== DONE. rows in $CSV ==="
echo "columns: $CSV_HEADER"
