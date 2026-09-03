# Storage(SSD)×RDMA 경계 실험 (Case 1)

> [실험 인덱스와 canonical 수치 기준](README.md)

### 8.1 왜 이 실험인가

여기부터는 연구의 확장 축이다(2026-07-15 교수 미팅에서 정한 cross-resource 확장 방향). 질문은 "외부 리소스(SSD)에서 시작된 오류가 RDMA 경계를 지날 때 어떤 신호로 변환되거나 소실되는가"이고, SSD는 오류가 NVMe status로 번역된 뒤 RDMA가 운반하는 protocol 경계라서 "명시적 오류는 RDMA에 직접 안 보일 것"(H1)이 예측이었다. Phase 1/1b 합계 72 trial을 수집했다(2026-07-15–17).

### 8.2 셋업 — 부팅 디스크를 건드리지 않는 가짜 스토리지 스택

224(target)의 유일한 디스크가 부팅 디스크이므로 직접 export하지 않고 파일 기반 스택을 만들었다.

```text
실제 부팅 디스크의 파일시스템
  └─ 8 GiB sparse image
      └─ loop device
          └─ device-mapper fault layer (dm-error / dm-flakey / dm-delay)
              └─ nvmet namespace
                  └─ RDMA port (nvmet-rdma, 4420)
```

부팅 디스크 보호는 3중이다: 이름 패턴(nvme0/sd 거부), lsblk TYPE=loop만 export, dm slave 전수 loop 확인. initiator(225)쪽도 findmnt로 루트 디스크 계열이면 거부한다. NVMe-oF의 QP는 커널 소유라 유저스페이스에서 raw CQE를 poll할 수 없으므로, 관측 채널은 NVMe status/errno, dmesg, 양쪽 RDMA sysfs counter, latency 네 가지다(wc_status 없음). fault는 tc netem이 아니라 target 블록 계층(dm)에 주입 — kernel-bypass 제약을 구조적으로 우회한다.

코드: 225 `10_storage_rdma/`(orchestrator + lib_storage.sh + check_partial_read.c), 224 `10_storage_rdma/`(target_setup/teardown/crash/restore). 상세 canonical 문서: `10_storage_rdma/results/PHASE1_FINDINGS.md`, raw: `results/raw/storage_rdma.csv`.

### 8.3 Phase 1 결과 — 관측성 역전

| SSD 상황 | 관측 결과 | 분류 |
|---|---|---|
| backend 명시적 오류 (N=15) | NVMe Internal Error 반환, RDMA counter 변화 0 | 캡슐화된 전달 (RDMA 무결) |
| fail-slow, 지연 5s 이하 (N=15) | 성공 status, latency만 증가 (주입 1ms→실측 1.042ms … 5000ms→5133.828ms) | 미관측 |
| fail-slow, io_timeout(30s) 초과 (N=2) | 에러 반환 없이 무한 hang (reset→재연결→재큐 루프), 강제 disconnect로만 해제. RDMA resp_cqe_error +7,839 | 간접 탐지 |
| target 붕괴 (N=5) | 33.36s ± 0.03 후 EIO, resp_cqe_error 등 counter 증가 | 직접 탐지 (transport) |
| partial read (N=5) | pread EIO 실패했으나 buffer 앞 2MiB(bad block 경계) 유효 착지 | data-plane 부수 관측 |

headline은 관측성 역전이다. 명시적 storage 오류(media/전체 실패)는 NVMe status로만 오고 RDMA 에러 counter는 완전 무결한 반면, silent 장애(timeout 초과 fail-slow, target crash)는 앱이 에러를 못 보는데 RDMA counter만 발화한다. 두 신호 축이 상호보완적이라는 것 — cross-layer 관측이 필수라는 실증이다.

세부 관측:

- target crash의 33.36s는 물리 고장 감지 시간이 아니라 재연결 정책(3회 × 10s 간격)이 정한 시간이다. RDMA 자체 연구의 "3.7s = firmware retry 정책 지배" 발견의 스토리지판이다.
- nvmet 번역 손실: dm 주입 오류가 media든 backend 전체 실패든 동일한 generic Internal Error(SCT 0x0 / SC 0x6)로 뭉개져 initiator에서 원인 구분이 원리적으로 불가하다. 단 주장 범위 확정(커널 소스 검토, 2026-07-17): nvmet의 blk_to_nvme_status 매핑상 BLK_STS_MEDIUM은 SCT 0x2(Media) / SC 0x86으로 media 타입은 살아남고 세부 원인(0x81 Unrecovered Read 등)만 손실된다. 우리 실측이 전부 Internal Error였던 것은 dm 주입이 BLK_STS_IOERR을 내기 때문이다. 정리하면 "타입 보존 / 원인 손실 — 중간 언어(blk_status_t)의 어휘만큼 뭉개짐"이 정확한 서술이다.
- partial read의 2MiB prefix는 실패(EIO)가 buffer 무변경을 뜻하지 않는다는 관측이다. 단 통째 재독이 값싸고(100Gbps에서 2MiB는 무시 수준) LBA granularity를 노출·복원하는 것도 아니므로 load-bearing 발견이 아니라 부수 관측으로만 다룬다(partial write의 sq_psn 복원과는 별개).

### 8.4 Phase 1b 결과 — 신호에서 복구로

| 실험 | 결과 |
|---|---|
| E1 fault isolation | 불량 블록 20연속 에러에도 정상 LBA I/O 성공, controller reset 없음 → NVMe 오류는 명령 단위 격리(RDMA의 QP 전멸과 대비), 복구 = 블록 회피. 원시 status 0x6006 = DNR+MORE 비트 세트 |
| E2 timeout tuning | path 디바이스 io_timeout 5/10/30s 적용은 성공했으나 9/9 still_hang — io_timeout은 reset 주기만 바꾸고 hang을 못 끊는다. 유일한 레버는 fast_io_fail_tmo인데 이 환경의 nvme-cli에 플래그가 없음(레버 가용성 = 환경 의존). 강제 disconnect 해제도 reset 위상에 따라 6–98s 변동 |
| E3 target recovery | crash 후 재개 시간 = 다운시간 T + 다음 reconnect 슬롯(10s 격자) + 약 7s(재연결+재스캔). T=5→17.4s / 15→27.8s / 30→38.0s로 모델 정확 일치 → reconnect_delay 튜닝 = 복구 시간 튜닝 |
| E4 counter 조기 감지 | resp_cqe_error가 crash에서 0.6s 발화(앱 EIO는 33.36s — lead 33s, 54배), timeout 초과 fail-slow에서 4.6s 발화(앱은 영원히 hang — lead 무한대) → 스토리지판 early-detection 감시 counter 확정 |

### 8.5 Case 1 결론

SSD 오류의 의미는 NVMe 계층에 남고 RDMA 계층에는 대부분 보존되지 않는다. RDMA는 SSD 자체의 오류보다 연결 붕괴를 더 잘 관측한다(protocol 경계 예측 H1과 일치). 식별 가능성은 낮다 — 같은 resp_cqe_error가 crash와 timeout 초과 fail-slow를 구분하지 못한다. 탐지 시점은 물리 고장이 아니라 정책(io_timeout, reconnect_delay)이 지배하고, 복구 범위 판단에는 신호의 종류보다 발생 순서가 더 유용해 보인다(순서 가설의 첫 근거). 다음 경계는 Memory×RDMA(설계 완료, feasibility 확인 대기)와 GPU×RDMA(GPU 노드 확보 후)다.
