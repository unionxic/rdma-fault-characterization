# 10_storage_rdma: 상세 기록

이 문서는 예전 README 본문을 그대로 옮긴 것이다. 실행 방법도 여기에 있다. 요약은 [README.md](README.md)에 있다.

Cross-resource 에러 관측 연구의 **Phase 1**. RDMA가 관여하는 데이터 경로 중
**SSD(NVMe-oF over RDMA)** 리소스의 고장 신호가 (a) NVMe/RDMA 계층에서 어떻게
표면화되는지, (b) 어디서 silent하게 새는지를 전수 매핑한다. 설계 근거:
맥북 `~/Desktop/Netsys/gpu-fault-recovery/4_확장방향_cross_resource.md`
(§3 Phase 1 매트릭스 + §6 Fable 검토 노트).

- 이 노드(225, ConnectX-6, RDMA IP 10.0.0.2) = **initiator/requester + orchestrator**.
- 짝 노드(224, ConnectX-5, RDMA IP 10.0.0.3) = **target/responder**. SSH는 225→224만.
- 100Gbps RoCEv2. 모든 실행은 여기서 `run_storage_experiment.sh`로 하고, 이 스크립트가
  ssh로 224의 `target_setup.sh`/`target_teardown.sh`/`target_crash.sh`를 부른다.

## 핵심 관측 제약 — 커널 consumer의 CQE 불가시성

기존 연구(01~09)는 유저스페이스 requester가 QP를 직접 소유해서 `ibv_wc_status`
+ `vendor_err`를 CQE에서 직접 읽었다. **여기서는 다르다.** NVMe-oF의 initiator
QP는 **커널(nvme-rdma)이 소유**한다. 유저스페이스에는 completion이 노출되지
않으므로 `wc_status`/`vendor_err`를 관측할 수 없다. 이건 한계가 아니라 기존 연구
7절(구현 레이어 제약)의 **실증 사례**다: "관측 도구는 QP 소유자에게 종속된다."

그래서 trial당 기록하는 관측 tuple은:

```
(NVMe status/errno) + (initiator dmesg delta) + (양쪽 RDMA HW counter delta, sysfs) + (latency 분포)
```

CSV에 `wc_status` 컬럼이 **없는 이유가 이것**이다.

## 가설

- **H1 (계층 분리)**: target 발 media/IO 에러는 NVMe status(capsule)로 깨끗하게
  올라오고 RDMA 계층은 조용하다. *구조적으로 거의 자명* → 흥미는 partial에.
- **partial (Fable 노트 2, 가장 강한 후보)**: NVMe read의 데이터 전달은 target이
  치는 RDMA WRITE다. 대형 read 도중 media error가 나면 "partial data + error"가
  가능. `MEDIA_ERROR_PARTIAL_READ`가 initiator 버퍼에 **bad block 앞 데이터가
  어디까지 채워졌는지**(valid prefix)를 오프셋 패턴으로 실측한다. 우리의 silent
  partial(sq_psn, 전략 C) 전문성과 직결.
- **nvmet 번역 충실도 (Fable 노트 3)**: dm-dust의 블록계층 EIO를 nvmet이 어떤 NVMe
  SC로 번역하는지(media/integrity vs generic internal)는 스펙이 아니라 구현.
  `MEDIA_ERROR_READ`의 `nvme_status_or_errno` 컬럼이 그 번역을 직접 채집한다.
- **H2 (TARGET_CRASH → RETRY_EXC)**: target 붕괴 시 **NVMe keep-alive timeout(수 초)
  vs RDMA RETRY_EXC(0x81, 3.7s/12.26ms)** 중 어느 신호가 먼저 우는지 — "detection이
  지배" 논지의 스토리지판. `detect_ms` + `dmesg_signature`로 어느 쪽이 먼저인지 판정.
- **H3 (FAIL_SLOW = latency-only)**: dm-delay 지연은 에러 없이 latency로만 보인다.
  단, 지연이 **nvme io_timeout(기본 30s)**를 넘으면 abort/reconnect로 전이. sweep
  `1/10/100/1000/5000/35000 ms`로 그 **경계**를 측정(Fable 노트 5).

## 시나리오 (라벨 = 전체 이름, F1/F2 코드 금지)

| 라벨 | 주입 | 관측 초점 | 워크로드 |
|---|---|---|---|
| `BASELINE` | 없음 | 대조 latency 분포 | fio randread 4k/64M |
| `MEDIA_ERROR_READ` | dm-dust bad block → 소형 read | NVMe SC 번역 | `nvme read` 4KB |
| `MEDIA_ERROR_PARTIAL_READ` | 대형 read 중간 bad block | **valid_prefix_bytes** + SC | `nvme read` 4MB + `check_partial_read` |
| `FULL_IO_FAIL` | dm-flakey down | error/abort | `nvme read` + fio |
| `FAIL_SLOW` | dm-delay (sweep) | latency-only→timeout 경계 | fio 소량 read |
| `TARGET_CRASH` | nvmet 포트 제거 | keep-alive vs RETRY_EXC, `detect_ms` | 지속 dd + ssh crash |
| `INITIATOR_STATUS_INJECT` | nvme fault_inject (debugfs) | **통제 실험** (fabric 미경유) | debugfs 설정 후 read |

`INITIATOR_STATUS_INJECT`는 상태 코드를 **initiator 로컬에서 위조**하는 것이라
fabric(RDMA) 경로를 지나지 않는다. target 유래 시나리오와 **명시적으로 분리된
control**이다(Fable 노트 1).

## 파일

| 파일 | 역할 |
|---|---|
| `lib_storage.sh` | 공용: 시나리오 상수, FAIL_SLOW sweep, 안전 assert(`find_fabric_namespace`=subsysnqn/transport로 우리 컨트롤러만 선택, 부팅 디스크 거부), sysfs 카운터 스냅샷/델타 |
| `initiator_precheck.sh` | 읽기 전용: nvme-rdma 모듈, nvme-cli/fio/cc/python3, debugfs fault_inject(+CONFIG_FAULT_INJECTION), RDMA sysfs, ssh 도달성 |
| `run_storage_experiment.sh <SCENARIO\|all> [trials]` | 메인 orchestrator (아래 흐름) |
| `check_partial_read.c` | partial read 검증 C 소품: O_DIRECT 단일 pread → errno + `valid_prefix_bytes`(패턴 대조로 유효 prefix 산출) |
| `pattern.h` | 오프셋 식별 패턴 스펙 (224 사본과 byte-identical) |
| `parse_fio.py` | fio JSON → `p50 p99 max errcode`(us) |
| `results/raw/storage_rdma.csv` | 결과 (스키마 아래) |

## orchestrator 흐름 (trial당)

1. `ssh 224 target_setup <scenario> [param]`
2. `nvme connect -t rdma -a 10.0.0.3 -s 4420 -n <NQN>` → **subsysnqn/transport로**
   우리 네임스페이스 자동 선택(부팅 디스크 `nvme0n1`과 절대 안 겹침, 겹치면 중단하는 필수 검사)
3. `/dev/kmsg` 마커 기록 + **양쪽** 카운터 before 스냅샷
4. 시나리오별 워크로드 실행 → NVMe status/errno, latency, (partial) valid_prefix,
   (crash) detect_ms 수집
5. **양쪽** 카운터 after 스냅샷 + 마커 이후 dmesg 시그니처
6. `nvme disconnect` → `ssh 224 target_teardown`
7. CSV 1행 append

## CSV 스키마

```
scenario,param,trial,nvme_status_or_errno,latency_us_p50,latency_us_p99,
latency_us_max,counter_deltas,dmesg_signature,detect_ms,valid_prefix_bytes,notes
```

- `counter_deltas`: `INIT:<name=+d;...> TGT:<name=+d;...>` (nonzero 델타만, 콤마 없음)
- `dmesg_signature`: 마커 이후 nvme/nvmet/timeout/reconnect/RETRY 등 키워드 라인 요약
- `detect_ms`: TARGET_CRASH에서 crash 트리거→I/O 에러 반환(초기자 로컬 시계)
- `valid_prefix_bytes`: MEDIA_ERROR_PARTIAL_READ에서 버퍼 유효 prefix 바이트

## 해석 가이드

- **H1 확인**: media/full-io 행에서 `nvme_status_or_errno`는 값이 있고
  `counter_deltas`의 INIT 쪽 RDMA 에러 카운터는 0(정상 트래픽 카운터만 증가).
- **번역 충실도**: `MEDIA_ERROR_READ`의 status가 media/integrity 계열이면 정보 보존,
  generic internal이면 "계층 경계 진단 정보 손실" 논점.
- **partial**: `valid_prefix_bytes`가 bad block 오프셋(2MiB=2097152) 근처면 "앞
  데이터가 실제로 initiator 버퍼에 도달"(partial data+error) 실증. `pread_errno`도
  같이 봄(EIO 예상). notes에 `first_bad_block`/`last_block_valid_bytes` 원문 포함.
- **H2**: `detect_ms`와 `dmesg_signature`에서 "keep-alive timeout"이 먼저 찍히는지
  "RETRY_EXC/transport error/reconnecting"이 먼저인지 판정.
- **H3 + 경계**: FAIL_SLOW 행을 param(ms)로 정렬. 작은 ms는 `Success(latency-only)` +
  `latency_us_max ≈ delay`; 35000ms 근처에서 `errno=...` + dmesg에 timeout/abort/
  reconnect가 등장하면 그게 **경계**.
- **control**: INITIATOR_STATUS_INJECT는 `counter_deltas`가 사실상 없어야(로컬 위조)
  — target 유래 에러와 신호 형태가 다름을 대조로 보여줌.

## Phase 1b — 에러 시그널의 복구 활용 (신호→복구 실증)

Phase 1이 "어떤 신호가 뜨는가"(신호 지도)였다면, Phase 1b는 **"그 신호로 어떻게
복구하는가"**를 실증한다. 4개 시나리오 모두 실명 라벨이며, `all`(=Phase 1)에는
넣지 않았다 — **개별 실행** 또는 **`phase1b` 메타 인자**(4개 순차)로만 돈다.
같은 CSV(`results/raw/storage_rdma.csv`, 스키마 동일)에 append된다.

| 라벨 | 주입(target) | 측정 구간 | 가설 |
|---|---|---|---|
| `FAULT_ISOLATION` | dm-dust 불량블록 (=MEDIA_ERROR_READ) | (a)불량 read+DNR, (b)즉시 정상 read latency, (c)20회 반복 후 정상 read+reset 없음 | NVMe 에러는 **명령 단위 격리** — 연결 생존(⟷ RDMA는 에러 한 번에 QP 전멸). 복구 = 재시도 금지(DNR)+다른 블록 |
| `TIMEOUT_TUNING` | dm-delay 35000ms (=FAIL_SLOW) | io_timeout∈{5,10,30}s × 단일 4k read의 **time-to-error**(pmax µs) | time-to-error ≈ f(io_timeout, fast_io_fail) — "표면화 시간은 정책 산술"의 능동 실증 |
| `TARGET_RECOVERY` | loop 직결 (=TARGET_CRASH) | crash → T∈{5,15,30}s 후 restore → **I/O 재개까지** 시간(detect_ms=crash→재개, notes=restore→재개) | 재개 시간 ≈ ceil((T−감지)/reconnect_delay)×reconnect_delay 격자 — 복구 시간도 정책 산술 |
| `COUNTER_EARLY_DETECT` | crash 모드=loop 직결 / failslow 모드=dm-delay 35s | 카운터 0.2s 폴링 첫 이상 vs 앱 에러 → **lead time**(notes=counter_first_anomaly_ms, lead) | 카운터가 앱보다 먼저 발화. failslow는 앱이 영원히 hang → lead=∞, 카운터 발화 시각 자체가 결과 |

### 측정 구간 정의 (정확히)

- **FAULT_ISOLATION**: `status`에 (a)의 불량 read status 라인 + **DNR 여부**(nvme
  read 출력에서 grep). `notes`에 (b) good-read latency(µs)와 (c) 20회 반복 후
  good-read + `ctrl_reset=yes/no`(마커 이후 dmesg에 reset/reconnect 유무). `detect_ms`
  미사용. **해석**: DNR=yes + good-read 성공 + ctrl_reset=no 이면 "명령 격리" 확인.
  이것이 RDMA(QP 전멸)와의 결정적 대비.
- **TIMEOUT_TUNING**: 연결 시 `--fast_io_fail_tmo=5`(지원 시), 연결 후
  `/sys/block/<ns>/queue/io_timeout`에 param×1000 **ms** 기록(blk-mq sysfs 단위=ms,
  커널 `block/blk-sysfs.c` `queue_io_timeout_show`=`jiffies_to_msecs`; 실패 시
  `/sys/module/nvme_core/parameters/io_timeout` **초** 폴백). `pmax`=time-to-error(µs).
  **해석**: `error_after_Xs`면 정책이 hang을 유한 에러로 바꾼 것; time-to-error가
  io_timeout/fast_io_fail을 추종하면 능동 실증 성공. `still_hang(>200s)`이면 io_timeout
  만으로는 재큐 루프를 못 끊는다는 발견(= fast_io_fail이 필수 레버).
- **TARGET_RECOVERY**: `--ctrl-loss-tmo=60`으로 연결(T=30이 attempt 소진 3×10s=30s
  경계를 넘봄 → 여유 확보). `detect_ms`=crash→첫 재개 성공(ms), `notes`의
  `restore_to_resume_ms`를 reconnect_delay(기본 10s) 격자와 비교. `no_resume`이면
  restore 실패 또는 ctrl-loss 초과(둘 다 timeout 바운드로 트라이얼 종료, teardown 보장).
- **COUNTER_EARLY_DETECT**: 백그라운드 폴러가 `resp_cqe_error/req_cqe_error/
  local_ack_timeout_err`를 0.2s 간격 감시. crash 모드는 앱 에러 시각(`detect_ms`)까지
  측정해 `lead`= 앱−카운터. failslow 모드는 앱이 reset 루프로 영원히 hang →
  `app_error_ms=NA(hang)`, `lead=inf` — **카운터 발화 시각 자체가 유일한 신호**(Phase 1
  4.5절의 능동 관측판).

### sudoers 추가 (필수 — 사용자가 224에서 한 줄)

TARGET_RECOVERY는 orchestrator가 ssh로 `target_restore.sh`를 부른다. 기존
setup/teardown/crash와 같은 방식으로 **224의 `/etc/sudoers.d/storage_rdma`에 한 줄**
추가해야 passwordless로 호출된다:

```
gustlr ALL=(root) NOPASSWD: /home/gustlr/Desktop/gpu_fault_recovery/10_storage_rdma/target_restore.sh
```

(기존 3줄 setup/teardown/crash 옆에 추가. 경로는 REMOTE_DIR과 일치해야 함.)

### E5 — nvmet 번역 매핑 확정 (`blk_to_nvme_status`, 웹 코드 검토)

리눅스 커널 `drivers/nvme/target/io-cmd-bdev.c`의 `blk_to_nvme_status()` 전수:

| blk_status_t | NVMe status | (SCT,SC) | DNR |
|---|---|---|---|
| BLK_STS_NOSPC | NVME_SC_CAP_EXCEEDED (0x81) | (0x0 generic, 0x81) | **set** |
| BLK_STS_TARGET | NVME_SC_LBA_RANGE (0x80) | (0x0 generic, 0x80) | **set** |
| BLK_STS_NOTSUPP | NVME_SC_INVALID_OPCODE (0x01) | (0x0 generic, 0x01) | **set** |
| **BLK_STS_MEDIUM** | **NVME_SC_ACCESS_DENIED (0x286)** | **(0x2 Media, 0x86)** | **NOT set** |
| BLK_STS_IOERR / default | NVME_SC_INTERNAL (0x06) | (0x0 generic, 0x06) | **set** |

**결론**: BLK_STS_MEDIUM은 Internal Error로 붕괴하지 **않는다** — SCT=0x2(Media and
Data Integrity Errors) TYPE로 **살아남는다**(단 SC는 "Unrecovered Read 0x81"이 아니라
"Access Denied 0x86"으로 대체 = M:1 역매핑, *타입은 보존/세부 원인은 손실*). 우리가
Phase 1에서 관측한 sct 0x0/sc 0x6(Internal)은 **주입 도구(dm-dust/dm-error/linear+error)가
BLK_STS_IOERR을 내기 때문**이지 nvmet이 media를 못 실어서가 아니다. 즉 "번역 손실"
주장의 정확한 범위: (1) nvmet은 media TYPE을 실을 수 있으나 백엔드가 BLK_STS_MEDIUM을
낼 때만, (2) 우리 dm 주입은 원리적으로 BLK_STS_MEDIUM을 못 내므로 우리 실측은 nvmet의
충실도를 **과소평가**했다, (3) 반전 아이러니: 유일한 media 케이스(MEDIUM)가 **DNR을
안 붙이는 유일한 케이스** — media error는 nvmet이 retryable로 표시하고, generic IOERR은
Do-Not-Retry로 표시한다(E1의 DNR 관측 · E2의 재시도 정책과 직접 연결).

## 실행 순서 (사용자)

```bash
# 0) 양쪽 precheck (한 번)
#    224:  sudo ./target_precheck.sh        (225→224 ssh 또는 콘솔)
#    225:  sudo ./initiator_precheck.sh
# 1) 개별 시나리오 (권장: 처음엔 하나씩)
sudo ./run_storage_experiment.sh BASELINE 5
sudo ./run_storage_experiment.sh MEDIA_ERROR_PARTIAL_READ 5
sudo ./run_storage_experiment.sh FAIL_SLOW 3        # sweep×3 = 18 trials
sudo ./run_storage_experiment.sh TARGET_CRASH 5
# 2) 전체 (Phase 1만 — 정책상 all은 1b를 안 돈다)
sudo ./run_storage_experiment.sh all 5

# 3) Phase 1b (신호→복구). target에 sudoers target_restore 한 줄 추가 후!
sudo ./run_storage_experiment.sh FAULT_ISOLATION 5
sudo ./run_storage_experiment.sh TIMEOUT_TUNING 3        # io_timeout sweep{5,10,30}×3 = 9
sudo ./run_storage_experiment.sh TARGET_RECOVERY 3       # T sweep{5,15,30}×3 = 9
sudo ./run_storage_experiment.sh COUNTER_EARLY_DETECT 3  # {crash,failslow}×3 = 6
sudo ./run_storage_experiment.sh phase1b 3               # 위 4개 순차
```

**root(sudo) 필요**: `/dev/kmsg` 마커, `dmesg`, `nvme connect/disconnect`, debugfs.
224 쪽 setup/teardown/crash도 root라 orchestrator가 `sudo`로 ssh 호출한다(224에서
passwordless sudo 또는 사전 인증 필요).

## 한계 / 실행해봐야 아는 것

- **로컬은 macOS**라 리눅스 도구(nvme-cli/dm/nvmet/fio/debugfs) 실측 불가 — 전부
  데스크 체크. 아래는 실제 실행에서 확인 필요:
  - nvmet가 dm-dust EIO를 어떤 NVMe SC로 번역하는지(번역 충실도 = 발견 후보).
  - partial read에서 nvme-rdma가 실패한 read의 부분 버퍼를 **어디까지 채워 반환**
    하는지 (커널이 실패 시 buffer를 0으로 밀 수도 있음 → 그 경우 valid_prefix=0이
    "silent 손실"의 또 다른 증거).
  - dm-flakey `up=0` 문법을 해당 커널이 수용하는지.
  - TARGET_CRASH에서 keep-alive와 RETRY_EXC의 상대 순서(커널 타이머 값 의존).
  - debugfs `fault_inject` 경로/필드가 이 커널 빌드에 있는지(CONFIG 의존).
  - `nvme read`의 status 문자열 포맷(nvme-cli 버전 의존) — 파싱은 grep 기반이라
    포맷이 달라도 원문 라인을 그대로 저장.
