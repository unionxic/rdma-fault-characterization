# 10_storage_rdma — Phase 1 (SSD × RDMA) : target 쪽 (224)

이 디렉토리는 Phase-1 실험의 **target/responder(224)** 쪽 스크립트다. 실제
orchestration과 결과 수집은 전부 225의 같은 이름 디렉토리에서 이뤄지고, 여기
스크립트들은 225의 `run_storage_experiment.sh`가 **SSH(225→224)로** 호출한다.
설계 배경은 맥북 `~/Desktop/Netsys/gpu-fault-recovery/4_확장방향_cross_resource.md`
(§3 Phase 1, §6 Fable 검토 노트) 참고. 전체 가설/해석은 225의 `README.md`에 있다.

## 안전 원칙 (가장 중요)

224의 **유일한 디스크는 부팅 디스크 `nvme0n1`**이다. 이 디렉토리의 어떤 코드도
실디스크를 export하지 않는다. 오직 파일(`/home/gustlr/nvmet_backing/ns1.img`)을
`losetup`으로 붙인 **loop 디바이스만** dm 타겟/ nvmet namespace에 도달한다.
`lib_storage.sh`의 필수 검사 함수가 이를 강제한다(하나라도 어기면 중단):

- `assert_not_real_disk` — `nvme0*`, 임의의 실 NVMe/SATA 네임스페이스, 그리고
  `/`를 담은 루트 디스크(및 그 자식)를 이름·`lsblk PKNAME` 두 방식으로 거부.
- `assert_loop_device` — export/dm 대상이 `lsblk -no TYPE == loop`가 아니면 abort.
- `assert_dm_on_loop` — dm 디바이스의 `/sys/block/<dm>/slaves`가 전부 loop인지 확인.

## 파일

| 파일 | 역할 |
|---|---|
| `lib_storage.sh` | 공용: 시나리오 라벨 상수, 안전 assert, RDMA sysfs 카운터 스냅샷, 경로 상수. 단독 실행 X (source 전용) |
| `target_precheck.sh` | 읽기 전용 환경 점검(모듈 nvmet/nvmet-rdma, dm-dust/flakey/delay, configfs, nvme/fio/cc). 표로 PASS/FAIL 출력, 변경 없음 |
| `target_setup.sh <SCENARIO> [param]` | 백킹 이미지→loop→(시나리오별 dm)→configfs로 nvmet subsystem/ns/port(rdma, `10.0.0.3:4420`) 구성. 상태를 `.storage_rdma_state`에 기록 |
| `target_teardown.sh` | 역순 해제(configfs→dm→loop). 멱등, 상태파일 기반 |
| `target_crash.sh` | TARGET_CRASH용 — nvmet 포트 제거로 즉사 모사. 트리거 시각(ns) 출력 + `/dev/kmsg` 마커 |
| `target_restore.sh` | **(Phase 1b)** TARGET_RECOVERY용 — crash가 지운 nvmet **포트만 재생성**(subsystem/ns/loop/dm 무변경 = crash의 역연산). 트리거 시각(ns) 출력 + `/dev/kmsg` 마커. subsystem이 없으면 실패(빈 포트 방지) |
| `pattern.h` | 오프셋 식별 패턴 스펙 (225 사본과 **byte-identical**). 4KB 블록마다 `[magic|block_index]` 16B 레코드 256개 |
| `pattern_write.c` | 백킹 loop에 위 패턴을 기록 (MEDIA_ERROR_PARTIAL_READ 셋업 시 setup 스크립트가 `cc`로 빌드·실행) |

## 시나리오별 target 구성

| 시나리오 | dm 스택 | 비고 |
|---|---|---|
| `BASELINE` | 없음 (loop 직결) | 대조군 |
| `MEDIA_ERROR_READ` | dm-dust + addbadblock + enable | bad block byte offset(param, 기본 32768) → 4KB 단위 블록 번호로 환산 |
| `MEDIA_ERROR_PARTIAL_READ` | dm-dust (bad block = 읽기 중간) + **패턴 기록** | 대형 순차 read 중간에 bad block. initiator가 유효 prefix 측정 |
| `FULL_IO_FAIL` | dm-flakey `up=0 down=3600` | trial 동안 전 I/O 실패 |
| `FAIL_SLOW` | dm-delay `<ms>` | read+write 지연. ms는 param |
| `TARGET_CRASH` | 없음 (loop 직결) | I/O 중 `target_crash.sh`로 포트 제거 |
| `INITIATOR_STATUS_INJECT` | 없음 (loop 직결) | initiator debugfs 통제 실험 — target은 정상 export만 제공 |
| `FAULT_ISOLATION` (1b) | dm-dust (=MEDIA_ERROR_READ) | 초기자가 불량 read 격리 + 정상 read 생존을 실증 |
| `TIMEOUT_TUNING` (1b) | dm-delay (=FAIL_SLOW, param=지연 ms, 보통 35000) | 초기자가 io_timeout/fast_io_fail로 time-to-error 측정 |
| `TARGET_RECOVERY` (1b) | 없음 (loop 직결) | I/O 중 `target_crash.sh`(死) → `target_restore.sh`(부활) |
| `COUNTER_EARLY_DETECT` (1b) | 없음 (loop 직결, crash 모드) | 초기자 카운터 폴링 lead time. fail-slow 모드는 초기자가 FAIL_SLOW 라벨을 직접 요청 |

## dm 좌표 계산 메모 (직접 검증 필요 항목)

- dm sector 단위는 항상 **512B**. `blockdev --getsz`가 512-sector 개수를 준다.
- dm-dust 테이블: `0 <sectors> dust <loopdev> 0 <blksz_bytes>` (여기 blksz=4096B).
  bad block 번호는 **blksz(4096B) 단위** → `offset_bytes / 4096`.
  메시지 순서: `addbadblock <n>` → `enable`(이때부터 해당 블록 read가 EIO).
- dm-flakey: `0 <sectors> flakey <dev> 0 <up> <down>`. up=0 → 항상 down(전 I/O 에러).
- dm-delay: `0 <sectors> delay <dev> 0 <ms>` — read/write 모두 지연.

## 실행 (사용자가 직접, 224에서는 거의 실행할 일 없음)

```bash
# 225가 ssh로 호출하지만, 수동 점검은 224에서:
sudo ./target_precheck.sh
sudo ./target_setup.sh MEDIA_ERROR_PARTIAL_READ 2097152
sudo ./target_teardown.sh
```

모든 setup/teardown/crash/**restore**은 **root(sudo)** 필요 (loop/dm/configfs/kmsg).

**Phase 1b sudoers 추가 (필수)**: orchestrator가 `target_restore.sh`를 ssh로
passwordless 호출하려면 `/etc/sudoers.d/storage_rdma`에 기존 3줄 옆에 한 줄 추가:

```
gustlr ALL=(root) NOPASSWD: /home/gustlr/Desktop/gpu_fault_recovery/10_storage_rdma/target_restore.sh
```
