### RDMA subsystem fault characterization 실험

한 줄 목적: RDMA RC QP의 failure/error behavior를 CQE·vendor_err·HW counter로 실측해 분류 체계와 최소 비용 recovery를 세우고, 같은 틀을 SSD 경계와 GPU-initiated RDMA(NCCL GIN, NVSHMEM IBGDA)로 확장한다.

## 현재 테스트베드 (2026-09~)

| 노드 | 역할 | RDMA dev / netdev | NIC | fw | GPU | OS / kernel |
| --- | --- | --- | --- | --- | --- | --- |
| rain | client / requester / rank0 | `mlx5_1` / ens4f1np1 | ConnectX-6 VPI (MCX653106A-ECAT) | 20.43.4100 | Quadro RTX 5000 (sm_75) | Ubuntu 20.04 / 5.15 |
| sunny | server / responder / rank1 | `mlx5_0` / enp23s0f0np0 | ConnectX-6 VPI (MCX653106A-ECAT) | 20.43.4100 | RTX A4000 (sm_86) | Ubuntu 22.04 / 6.8 |

- 100 GbE RoCE v2 직결, PMTU 4096(netdev MTU 9000).
- 이 링크는 사용자의 NVMe-oF 스토리지(rain이 export, sunny가 mount)와 공유된다. 그래서 sunny 포트 카운터에는 배경 트래픽이 섞이고(5 s당 14–16 packets), 실제 link down과 mlx5 driver reload는 실행하지 않는다.
- PeerMappingOverride=1이 2026-09-24 13:53부터 양쪽에 영구 적용돼 있다. 그 전의 GPU-initiated 실험은 `gpu_doorbell/`의 짧은 창 두 번을 빼면 CPU-doorbell fallback(GPU가 WQE를 쓰고 CPU 스레드가 doorbell을 울림)에서 돌았다.
- NIC 표기: 2026-09-24까지의 문서는 "ConnectX-6 Dx"라고 적었지만, PCI ID(15b3:101b, MT28908)와 VPD 기준으로 두 NIC 모두 ConnectX-6 VPI다(Dx였다면 15b3:101d에 fw 22.x). 2026-09-25에 모든 문서를 고쳤다.

옛 클러스터: 225(ConnectX-6, fw 20.40.1000) ↔ 224(ConnectX-5, fw 16.35.8002), 100 Gbps RoCE v2 직결, Ubuntu 24.04, GPU 없음. `docs/experiments/` 01–08과 `experiments/`의 수치는 모두 이 클러스터에서 나왔다.

## 핵심 결론

### (a) 원 연구 — 옛 클러스터(225↔224)

- 3.7s detection의 정체는 하드웨어 한계가 아니라 firmware 설정(min_ack_timeout_limit)이다. 해제하면 12.26 ms, 약 297배 단축.
- recovery 결정은 CQE(ibv_wc_status + vendor_err)만으로 끝난다. counter는 critical path 밖 — 사후 진단과 조기 감지용.
- counter 감시(roce_adp_retrans)로 같은 fault를 18.4 ms에 감지·복구했다. passive 대비 203배.
- 10개 fault 시나리오를 9개 fingerprint로 구분했다. status만으로 6/10, vendor_err를 더하면 8/10, 0x81 쌍을 process liveness로 가르면 9/10이다. 남은 한 쌍은 invalid rkey ≡ 주소 범위 초과(0x88)다. counter·vendor_err는 N=100(timeout 2종은 N=30) 반복에서 전부 deterministic이었다. latency는 host jitter 탓에 분류 신호로 부적합.
- recovery 방법 선택만으로 2,845배 차이가 난다(QP-only 2.8 ms vs driver reload 7.9 s). **옛 클러스터 한정**이며 새 테스트베드에서는 재측정하지 않았다. QP-only는 정상 QP 영향 0%.
- partial write는 NAK 경로만 sq_psn으로 100% 복원된다. silent failure는 requester-invisible — 대응은 read-back 전략.
- SSD 경계에서는 관측성이 역전된다. 명시적 storage 에러는 RDMA 무결, silent 장애만 RDMA counter가 발화(앱 에러보다 54배 조기).

#### 대표 측정표 (옛 클러스터 225↔224)

에러 유형별 detect + recover(QP-only) + retry, N=10. detection이 전체를 지배한다.

| 에러 (status / vendor_err) | Detect | Recover | Total |
| --- | ---: | ---: | ---: |
| RNR_RETRY_EXC_ERR (13 / 0x87) | 245 us | 1,416 us | 1,671 us |
| REM_ACCESS_ERR (10 / 0x88) | 480 us | 1,342 us | 1,830 us |
| REM_INV_REQ_ERR (9 / 0x8a) | 489 us | 1,310 us | 1,818 us |
| RETRY_EXC_ERR (12 / 0x81) | 3,738,010 us | 2,773 us | 3,740,787 us |

RETRY_EXC_ERR detection 단축 경로 비교 (옛 클러스터).

| 방식 | Detection | Passive 대비 | 오탐 |
| --- | ---: | ---: | --- |
| Passive (CQE 대기, default firmware) | 약 3.7 s | 기준 | 없음 |
| local_ack_timeout_err 감시 | 1,053 ms | 3.5배 | 거의 없음 |
| roce_adp_retrans 감시 | 16.6 ms | 203배 | threshold 필요 |
| firmware floor 해제 (R=7) | 12.26 ms | 약 297배 | 없음 |

#### 해석과 한계 (원 연구)

- vendor_err hex는 mlx5 전용이다. 옛 클러스터에서 ConnectX-5와 ConnectX-6를 swap해 실측한 값은 동일했고, 새 테스트베드(ConnectX-6, fw 20.43.4100)도 0xf5 / 0x8a / 0x88 / 0x87 / 0x81을 그대로 재현했다. CX-7과 타 벤더는 미검증이다. status는 driver-stable이라 방법론은 vendor-agnostic.
- RETRY_EXC_ERR(0x81)의 두 원인(서버 QP ERR vs 프로세스 종료)은 **RDMA counter로 갈리지 않는다.**
  - 원 연구의 8/10 → 9/10은 ethtool이 센 **non-RDMA TCP sideband** 패킷 수(서버 생존 시 FIN, kill 시 RST)에서 나왔다. 두 원인의 RDMA 패킷은 똑같이 15개였다. 따라서 이 단계를 올린 것은 RDMA counter가 아니라 process liveness였다.
  - harness 재검증(`harness/VERIFICATION_0x81.md`, 원인별 N=5)에서도 responder RDMA port counter의 범위가 두 원인 사이에 겹쳤다.
    - 첫 측정: `port_rcv_packets` 40–57 vs 44–52, `port_xmit_packets`는 둘 다 0.
    - 2026-09-23 재측정: 각각 26–28 vs 23–30, 14 vs 12–16. 이때는 NVMe-oF 배경 트래픽이 섞였다.
  - 판별자는 TCP 사이드채널에서 보이는 liveness다. harness는 제어 채널 PROBE에 응답이 오는지로 판단하고, NCCL 패치는 소켓에 FIN/RST가 보이는지(아니면 증거 없음)로 판단한다.
- tc netem은 RDMA에 무효(kernel bypass). fault 주입은 QP 상태 조작·프로세스 kill·link down·device-mapper로 수행.
- A/B 실험의 A recover 42.7 ms는 TCP_NODELAY 아티팩트로 판명됐다. 수정은 끝났고 재실행은 대기 중이다. B 우위 결론은 불변.
- latency 절대값은 CPU pinning 없이 측정한 값이라 host 환경 의존.
- firmware 토글은 mlxreg 수동 조작이며, 스크립트의 관리망 주소는 placeholder로 치환되어 있다.

### (b) 새 테스트베드 harness 결과

`harness/`는 옛 01–09의 RDMA 측 fault 8종(그중 7종 측정)을 requester/responder 한 쌍에 모은 장치다. trial마다 fault 주입 → detection → CQE 분류 → QP 복구 → 4 KiB WRITE+READ-back 검증을 거쳐 CSV 한 줄을 남긴다.

- 포함하지 않은 것: LOC_PROT 3종과 invalid-rkey REM_ACCESS. 그래서 vendor_err가 6/10을 8/10으로 올리는 단계는 이 장치로 재현하지 않는다.
- `retry_link_down`은 구현만 됐다. 공유 NVMe-oF 때문에 dry run만 돌렸고, 지문은 아직 측정하지 않았다.

확인 런 `harness/results/*_20260923_123945.csv`: N=30, CPU 2 pinning, QP timeout 14 / retry_cnt 7, `rnr_retry=6`.

| fault | status / vendor_err | detect median | QP-only recover median | verify |
| --- | --- | ---: | ---: | ---: |
| local_qp_err | 5 / 0xf5 | 225 µs | 0.79 ms | 30/30 |
| partial_write | 5 / 0xf5 | 338 µs | 0.78 ms | 30/30 |
| rem_inv_req | 9 / 0x8a | 304 µs | 0.77 ms | 30/30 |
| rem_access | 10 / 0x88 | 323 µs | 0.77 ms | 30/30 |
| rnr | 13 / 0x87 | 12.79 ms | 0.78 ms | 30/30 |
| retry_server_qp_err | 12 / 0x81 | 3.749 s | 0.81 ms | 30/30 |
| retry_proc_kill | 12 / 0x81 | 3.732 s | — (프로세스 없음) | — |

- (status, vendor_err) 쌍은 0x81 한 쌍을 빼고 모두 고유하다. 0x81은 liveness로 `server_qp_err`×30과 `proc_kill`×30으로 갈렸다.
- partial_write에서 READ-back으로 잰 도착 바이트는 1,085,440–1,130,496 B였다(4 KiB 패킷 265–276개). PSN으로 구한 송신 바이트와 30/30 일치했고, prefix 밖에서 일치한 바이트는 없었다.
- full_rebuild(QP만 destroy+recreate, CQ/MR/PD 유지)의 중앙값은 1.79–1.81 ms였다(같은 날 `_20260923_114031`, 확인 런은 QP-only만 돌림). 확인 런의 QP-only 중앙값과 비교하면 약 2.3배이고, fault별 중앙값 비는 2.27–2.33이다.
- rem_access와 rem_inv_req의 detection은 bimodal이다. 25/30이 0.30–0.38 ms, 5/30이 1.6–3.0 ms라서 평균 대신 중앙값을 쓴다.
- NCCL IB transport in-tree 패치(`harness/nccl-integration/`, NCCL v2.23.4-1 `net_ib.cc`, `NCCL_RDMA_FAULT_RECOVERY=1`)의 2-node 검증(2026-09-23) 결과는 다음과 같다.
  - flag off base: 60/60 bit-exact.
  - WR_FLUSH 주입(한쪽 rank, 양쪽 rank 동시): bilateral QP reset과 WRITE 1회 replay로 복구했고, deadlock 없이 60/60 bit-exact.
  - pipelined: 깨끗하게 거절.
  - peer kill: `proc_kill`로 분류한 뒤 stock과 같이 실패.
  - 복구 대상은 첫 에러가 WR_FLUSH이고 QP 1개·NIC 1개·in-flight 요청 1개일 때로 한정된다. `ncclCommAbort`는 에러 후 stock 2.23에서도 hang한다.
- **NCCL Stage 2**(`harness/nccl-integration/stage2/`, 2026-09-25): 같은 `net_ib.cc` 안에서 요청이 여러 개 비행 중이어도 복구한다. 설계와 QA 두 라운드는 `DESIGN_stage2.md`에 있다.
  - NCCL 기본 설정(2채널, pipelined, 16 MB)에서 send QP ERR 30/30, recv QP ERR 30/30을 복구했다. 최종 빌드 재확인에서도 30/30이었다. Stage 1은 이 설정을 3/3 거절했다. 복구 시간 중앙값은 2.1–2.3 ms다.
  - run당 5회 fault 50/50, 양쪽 rank 동시 fault 20/20(deadlock 없음).
  - **주소 재구성 fault를 복구했다.** 테스트용 보조 RoCE 주소를 sunny에서 지웠다가 다시 붙이면, 주소가 새 GID index로 돌아와 기존 QP의 address vector가 없어진 항목을 가리키게 되고, 원본 QP는 영구히 죽는다. 원본은 0.5 s·6 s 끊김에서 RETRY_EXC 12/0x81 뒤 6/6 실패했고, 타당성 시험에서는 0.3 s 끊김에도 QP가 죽었다. Stage 2는 GID를 값으로 다시 찾아 0.5 s·6 s·15 s 끊김을 15/15 복구했고, 15,000회 반복의 결과가 모두 정확했다. link 자체는 내리지 않으므로 같은 링크의 NVMe-oF는 영향이 없었다.
  - 이 실험이 보인 것은 drain, PSN reset, replay, GID 재탐색이 실제 RETRY_EXC CQE에서 동작한다는 점이다. 패킷만 잃고 GID index는 그대로인 일시 장애(진짜 link flap)에 대한 내성은 보이지 않았다. 그런 flap이 재전송 예산 안이면 원본도 견디고, 예산을 넘으면 port state 이벤트가 끼는데 그 경로는 시험하지 않았다(사용자 결정으로 진짜 link flap은 돌리지 않음).
  - 죽은 peer: 상대 소켓에 FIN·RST가 보이면 수신 대기 중인 생존자에게 50.2 ms 만에 에러를 올린다(10/10; 그 뒤 NCCL 2.23 abort hang 때문에 드라이버 watchdog으로 종료). 원본은 같은 상황에서 아무 경고 없이 멈춘다(3/3).
  - 관리망 장애는 상대 사망으로 보지 않는다(9월 25일 검토 후 수정). keepalive timeout(ETIMEDOUT)은 복구만 끄고 작업은 원본처럼 계속한다. 이 작업의 TCP 연결만 12초 막는 시험(T12b, 1 GiB all-reduce)에서 수정 전 빌드는 멀쩡한 작업을 4.3–4.6초 만에 죽였고(0/3), 수정 후 5/5, 원본 2/2 통과했다. 2차 검토 뒤에는 RST도 사망 증거로 쓰지 않는다. 한쪽 방향만 막힌 장애에서는 먼저 timeout된 쪽의 커널이 RST를 보내는데, 그것을 사망으로 읽은 빌드는 멀쩡한 작업을 죽였다(T12c 0/3, 수정 후 5/5). OOB 상실은 그 comm이 끝날 때까지 유지되고(재연결하지 않음), 그 뒤 fault는 원본처럼 즉시 실패한다(T12d, 0.06–0.07 ms).
  - 오래된 QP의 패킷(stale packet)은 HW counter(`duplicate_request`, `out_of_sequence`, `packet_seq_err`)로 확인했는데, 모든 캠페인에서 0이었다. `implied_nak_seq_err`는 두 캠페인 사이에 rain에서 0→2가 됐고 캠페인 안에서는 변하지 않았다(출처 미상).
  - fault가 없을 때 비용은 flag on에서 −0.2 ~ +0.7 %다. 원본 자체의 반복 간 편차(0.4–1.7 %, n=3) 안이라 약 1 % 이하라는 것까지만 말할 수 있다. flag off는 원본과 같다.
- **NCCL 완료 시간 비교**(`harness/nccl-integration/perf/`): fault 1회가 든 작업 전체의 시간을 비교했다.
  - 제자리 복구는 약 2 ms를 더한다. 실패한 반복부터 재시작하면 약 1.1 s를 더한다. 반복마다 checkpoint가 있고 에러 즉시 재기동한다는, 재시작에 가장 유리한 가정에서다. 1.1 s는 작은 2-rank 작업의 재기동 비용이라 실제 작업에서는 하한이다.
  - NCCL 기본 IB timeout 20에서 주소 재구성 fault는 NIC이 포기하기까지 56–60 s가 걸린다. 그 뒤로는 복구(68.0 s)와 재시작(68.3 s)이 오차 안에서 같다. 이때 병목은 복구가 아니라 detection이다.

### (c) GPU-initiated RDMA (`harness/gpu-initiated/`, 2026-09-23~24)

대상 스택은 NCCL 2.32.3 GIN(proxy, GDAKI)과 NVSHMEM IBGDA(7bb2e99c)다. 달리 적지 않으면 IB timeout은 14다. fault는 네 가지다.

- 로컬 QP 에러: 테스트 훅이 initiator QP를 ERR로 옮긴다.
- 원격 접근 오류: 원격 window/heap 밖에 쓴다. NVSHMEM에서는 등록된 MR 안쪽의 범위 밖 쓰기와 잘못된 rkey로 나눈다.
- 상대 QP 에러: 테스트 훅이 target QP를 ERR로 옮긴다. target 프로세스는 살아 있다.
- 상대 프로세스 사망: target을 SIGKILL한다.

종합과 측정/추론 구분은 `harness/gpu-initiated/RESULTS.md`에 있다.

- **collapsed CQ 슬롯에는 보통 원인이 아니라 flush가 남는다.**
  - 원인 CQE 뒤로 NIC은 남은 WQE마다 `WR_FLUSH 5/0xf9`를 쓴다. 약 59 µs 뒤에 시작해 9.35 µs 간격이다(CPU에서 측정, `gin_q4/`의 실제 collapsed CQ에서 확인).
  - GPU 분류기 실험의 모든 trial에서 wait가 폴링한 CQE는 뒤따른 flush였다. 분류기는 폴링된 CQE가 아니라 원인 CQE를 찾아야 한다.
- **stock 스택은 에러를 잃거나 숨긴다.**
  - GDAKI의 blocking wait는 실패한 write를 완료로 보고한다(9/9). host는 10 s 주기 QP 상태 점검(`NCCL_GIN_ERROR_QUERY_SEC`) 탓에 fault 후 8.0–10.0 s가 지나서야 "QP in ERR"만 본다.
  - GIN proxy(CPU가 CQ를 폴링)는 전체 지문을 로그로 남기지만, 로컬 QP 에러·원격 접근 오류·상대 QP 에러에서 blocking wait가 hang하고 blocking 모드의 `ncclCommAbort`도 hang한다.
  - NVSHMEM IBGDA를 CPU-proxy handler로 돌리면 QP가 ERR인데도 CQ(1024 entries)에 에러 CQE가 한 번도 오지 않았다. `nvshmem_finalize`는 QP 에러 뒤 hang한다.
  - 등록된 MR 안쪽에서 범위를 벗어난 put은 모든 계층에서 silent corruption이다.
- **NVSHMEM의 에러 CQE 부재는 CPU-proxy handler 버그다(`nvshmem_rootcause/`).**
  - handler가 SQ producer index를 doorbell record word 0(RCV)에 쓴다. word 1에 써야 한다. [소스, doorbell record 값도 측정]
  - CPU 재현에서 에러 CQE를 받은 비율은 word 0에 쓰면 0/35, word 1에 쓰면 21/21이었다. [측정]
  - NIC이 SQ를 비었다고 보고 completion을 쓰지 않는다는 설명은 [추론]이다.
  - 범위: NVSHMEM 3.5.x–3.8.0(커밋 ce9d487, 2025-10에서 생긴 회귀. 3.4.5는 정상), IBGDA를 CPU-proxy handler로 돌리는 경우(PeerMappingOverride가 없는 시스템).
  - upstream 보고는 사용자 결정을 기다린다.
- **같은 원인이 다른 지문으로 나온다.**
  - 죽은 peer는 CPU verbs와 GDAKI에서 12/0x81이지만, GIN proxy에서는 60 ms 안에 10/0x88로 나온다.
  - 원인은 `harness/fingerprint_teardown/`에서 쟀다(SIGKILL 417회). 커널은 죽은 프로세스의 verbs 객체를 가장 나중에 만든 것부터 지운다. 그래서 MR을 QP 뒤에 등록했으면 MR이 먼저 사라져 아직 살아 있는 QP가 NAK를 보낸다(REM_ACCESS, 구조상 불가능한 sunny DEVX 셀을 빼면 111/161, 경합). MR을 QP보다 먼저 등록했으면 한 번도 0x88이 나오지 않았다(0/83). sunny의 OFED 25.10은 DEVX QP(GDAKI, NVSHMEM IBGDA)를 먼저 지워서 0x81이 나온다. 그래서 0x88이라도 상대가 죽었으면 상대 사망으로 봐야 하고, harness 분류기는 REM_ACCESS에도 liveness를 확인한다.
  - GDAKI에서 상대 QP 에러와 상대 프로세스 사망는 같은 0x81이다. 그래서 CPU 경로와 마찬가지로 liveness가 필요하다.
- **retry 소진 감지는 기본값에서 느리다.**
  - IB timeout 14에서는 모든 스택이 3.6–3.75 s다.
  - NCCL/NVSHMEM 기본값인 20에서는 GIN proxy가 RETRY_EXC를 57–59 s 만에 보고했다(4 trials). 계산값 34 s의 약 1.7배다.
  - 그 이유를 `harness/ack_timeout/`에서 쟀다. 기본 firmware는 재시도 1회분을 쓰는 적응형 재전송 단계를 먼저 돌고, 그다음 R−1번의 timeout을 2 × 4.096 µs × 2^max(T,16) 간격으로 기다린다. 한 run 안에서 이어 도는 시행(첫 시행 제외)에는 detect ≈ R × I − c 식이 맞는다. 식을 세운 42회에 0.9 ms 안, 예측을 먼저 고정하고 새 조건에서 돌린 55회 중 52회가 ±1.5 ms 안이었다. T=20·R=7에서 59.8 s다.
  - 다만 새 프로세스의 첫 시행은 첫 정규 timeout 시점이 이력에 따라 달라 이 식이 정확히 맞지 않는다(T=20에서 약 1 s 짧음). GPU·NCCL 측정은 모두 첫 시행이다. GIN proxy의 57–59 s는 이 식(59.8 s)보다 짧고, GIN과 비슷한 트래픽을 넣은 새 프로세스 CPU 측정(57.7–58.2 s)과 범위가 겹친다. 즉 식은 약 2배가 되는 구조를 설명하지만, 새 프로세스의 정확한 값은 예측하지 못한다.
  - rain NIC의 floor(`min_ack_timeout_limit_disabled`)를 시험 창 안에서만 풀면 T=8·R=7에서 9.49 ms다. GPU 스택에서는 fault부터 호스트가 지문을 받기까지 NVSHMEM 13.3 ms, GIN GDAKI 24.6 ms였다(각 10/10). 설정은 NIC 전체에 적용되고 작은 T는 오탐 위험이 있어서, 레지스터는 창이 끝날 때마다 되돌리고 확인했다.
- **장치측 분류(GPU 분류기, GDAKI)는 싸다.**
  - host는 장치가 감지한 지 94 µs 뒤에 정확한 지문을 받고, `ncclCommGetAsyncError`는 그로부터 190 µs 뒤에 반환한다.
  - 조용한 성공은 0/9로 사라졌다.
  - fault가 없을 때 4 KiB 중앙 latency 증가는 0.1 µs 이하(약 1%)다.
- **GIN GDAKI 복구(`gin_recovery/`).**
  - 로컬 QP 에러와 상대 QP 에러는 모든 trial에서 복구됐다. 데이터는 bit-exact였고 signal도 정확했다. run당 5회 fault, replay 도중 fault를 넣은 경우도 포함한다.
  - 원격 접근 오류와 상대 프로세스 사망는 깨끗하게 거절됐다.
  - kernel이 반환한 뒤 replay가 끝나기까지 중앙값 8.0–8.2 ms가 걸렸다. 그중 약 6 ms는 firmware QP 명령이다.
  - GPU-rung doorbell에서는 `gin_recovery_gpudb.diff`로 같은 결과를 얻었고, 약 8.5 ms가 걸렸다.
  - **투명 복구 1단계**(`gin_recovery/TRANSPARENT_S1.md`, 2026-09-25): 고치지 않은 GIN 프로그램이 로컬 QP 에러와 상대 QP 에러를 에러도 커널 재실행도 없이 넘긴다(복구 가능한 셀 95/95, "WRITE는 실행·ADD는 미실행" 경계 30/30, 비행 중 fault 150/150). 복구 불가 fault는 거절한다(40/40). helper가 commit 전에 멈추거나 죽으면 flush는 device hold가 끝나는 때(시험에서 4.0 s) 에러를 돌려주고, commit 뒤에 멈추면 2 × hold(8.0 s)에 돌려준다. watchdog은 async 에러만 올린다. blocking flush의 상한은 hold(30 s, give-up 경합에서 지면 60 s)뿐이다. **비용: flag를 켜면 4 KiB 지연이 +60 %(10.24 → 16.42 µs)**여서 아직 실용 단계가 아니다. flag를 끄면 +1 %다. 비행 중 op 1개·post 스레드 1개까지만 시험했다.
- **NVSHMEM IBGDA 분류+복구(`nvshmem_ft/`, GPU handler).**
  - 분류는 single-fault 48/48, multi-fault 100/100 round에서 정확했다. host mailbox는 캡처 67 µs 뒤에 읽혔다.
  - 로컬 QP 에러와 상대 QP 에러는 모든 run에서 복구됐다(112 rounds, run당 200/200 ops bit-exact). 잘못된 rkey와 상대 프로세스 사망는 거절됐고, `nvshmem_finalize`는 17–29 ms 안에 반환한다.
  - collapsed 슬롯에서 원인을 잡은 비율은 stock wait가 끝나는 지점에서 읽으면 0/24, spin loop 안에서 읽으면 21/30, 상주 sentinel을 쓰면 18/18이었다.
  - v2(`nvshmem_ft/V2.md`, 2026-09-25): ring CQ 모드에서는 sentinel 없이 원인 CQE를 90/90 잡는다(같은 패턴의 collapsed 루프 안 읽기는 0/90). 다만 조기 감지는 대체하지 못한다(fault부터 mailbox까지 ring만 3.2 ms, collapsed+sentinel 1.2 ms). v2.1은 에러 뒤 doorbell이 앞서 나가 burst 복구가 3/5 거절되던 결함을 "park"로 고쳤다(수정 후 ring 5/5, collapsed 3/3). 원인 CQE는 수정 전에도 잃지 않았다(155/155). post 전 범위 검사는 빈 공간·객체 끝·힙 끝을 넘는 쓰기를 모두 막지만, 기존 사례(다음 객체를 정확히 덮는 쓰기)는 red zone을 켜야 잡는다(0/30 → 35/35).
  - fault가 없을 때 비용은 4 KiB에서 +1%, 256 KiB에서 +0.25%다.

한계:

- **소프트웨어 주입이 아닌 fault를 복구한 것은 NCCL Stage 2의 주소 재구성 fault뿐이고, 그것도 패킷 손실형 일시 장애는 아니다.** GPU 스택(GIN, NVSHMEM)에서 복구한 로컬 QP 에러와 상대 QP 에러는 모두 소프트웨어가 QP를 ERR로 옮긴 경우다. 실제 원격 에러(원격 접근 오류)와 죽은 peer(상대 프로세스 사망)는 거절 경로만 검증됐다. 진짜 link down은 공유 NVMe-oF 때문에 돌리지 않았다(`stage2/linkflap_window.sh`는 준비만 됐고 사용자 승인이 필요하다).
- **검증 범위가 좁다.** NVSHMEM FT는 2 PEs, peer당 RC QP 1개, 복구 중 in-flight op 1개로 검증했다. GIN 복구는 2 ranks, QP 쌍당 initiator 1개, in-flight op 1개(lockstep)로 검증했다. NCCL Stage 2만 여러 요청 in flight와 양쪽 동시 fault를 다루고, 그것도 2 ranks·NIC 1개다.
- **[추론, 미시험]:** GPU 스택의 여러 QP·NIC, 3개 이상 PE, 여러 op in flight, 양쪽 동시 initiation, 그리고 모든 스택에서 FIN 없이 죽는 peer host.
- **실험 규모:** 노드 한 쌍, fw 한 종, RoCE v2. GPU 스택의 분류·복구·거절 셀은 2026-09-25에 N=30(다중 fault·대조군은 10)으로 다시 돌렸고 모든 셀이 100 %였다(`harness/gpu-initiated/N30_20260925.md`, N=30 셀의 Wilson 95 % 하한 88.6 %). 그 밖의 셀은 3–10회다.
- `gpu_doorbell/` 창에서 GDAKI가 GPU doorbell을 썼다는 것은 추론이다(NCCL·DOCA 모두 로그하지 않는다). 2026-09-24의 `gin_recovery` GPU-doorbell 재실행에서는 네 지표로 측정했다.
- DeepEP는 SM90이 필요해 이 테스트베드(sm_75/sm_86)에서 돌릴 수 없다.

### 숫자 체계 — 무엇이 어느 질문의 canonical인가

| 질문 | canonical 출처 |
| --- | --- |
| 원 연구(옛 클러스터 225↔224)의 기록 | `docs/experiments/` — 충돌 시 [docs/experiments/README.md](docs/experiments/README.md)의 canonical 표 |
| 현재 테스트베드의 CPU verbs fault 수치 | `harness/results/*_20260923_123945.csv` (full_rebuild만 `_20260923_114031`), `harness/README.md` |
| GPU-initiated 스택의 동작·수치 | `harness/gpu-initiated/RESULTS.md`와 하위 디렉토리 |

두 체계의 수치는 **직접 비교하지 않는다.** 하드웨어도 정의도 다르다.

| 항목 | 원 연구 (옛 클러스터) | harness (현재 테스트베드) |
| --- | --- | --- |
| NIC / fw | CX-6 20.40.1000 ↔ CX-5 16.35.8002 | CX-6 ↔ CX-6, 둘 다 20.43.4100 |
| PMTU | 1024 | 4096 |
| CPU pinning | 없음 | CPU 2 pinning |
| RNR 트리거 | `rnr_retry=0` → 즉시 소진 (245 µs) | `rnr_retry=6` (12.79 ms) |
| QP-only | QP 재구동 + PSN 재협상 + 필요 시 MR 재교환 | 양쪽 협조 QP 재구동 + fresh PSN, MR 재교환 없음 |
| full rebuild | PD/CQ/QP/MR 전부 재생성 (6.9–9.6 ms) | QP만 재생성 (≈1.8 ms) |
| driver reload | 7.9 s, QP-only 대비 2,845배 | **미측정** — 공유 NVMe-oF를 끊기 때문에 실행하지 않음. 이 수치는 옛 클러스터 한정 |
| 0x81 판별 | ethtool로 센 TCP sideband 패킷(FIN vs RST) | 제어 채널 PROBE liveness |

#### Directory

| 경로 | 내용 |
| --- | --- |
| `docs/theory/` | 이론 문서 8편 — RDMA 기초, 에러 식별, 분류 체계, counter 관측성, vendor_err 일반화, NCCL 레이어 제약 |
| `docs/experiments/` | 옛 클러스터 실험 문서 01–08(detection 분해부터 Storage×RDMA까지)과 09 GPU×RDMA 계획 |
| `experiments/225-client/` | 옛 클러스터 client(requester) 측 실험 코드(01–10)와 원시 결과 CSV |
| `experiments/224-server/` | 옛 클러스터 server(responder) 측 대응 코드 |
| `harness/` | 통합 측정 장치: `run.sh`·`config.sh`·`analyze.py`·`Makefile`, `VERIFICATION_0x81.md`(+`verify_0x81_counter.sh`), `QA_20260923.md` |
| `harness/common/` | `probe.{h,c}` — 공통 verbs/QP 설정·제어 채널·분류 |
| `harness/client/` | `probe_client.c` — requester(rain) |
| `harness/server/` | `probe_server.c` — responder(sunny) |
| `harness/results/` | fault별 CSV `<fault>_<stamp>.csv`(현재 기준은 `_20260923_123945`), `verify_0x81_20260923.csv` |
| `harness/nccl-integration/` | NCCL v2.23.4-1 `net_ib.cc` in-tree 패치(분류 + bilateral QP 복구), `DESIGN_recovery.md`, 2-rank 드라이버 `nccl_ar2.cu`, `logs/` |
| `harness/gpu-initiated/` | GPU-initiated RDMA 연구: `RESULTS.md`(종합), `DESIGN.md`(질문 네 가지 질문, fault 네 가지 fault) |
| `harness/gpu-initiated/common/` | `cluster_run.sh` — 클러스터 잠금 + 링크 유휴 대기 러너 |
| `harness/gpu-initiated/cqe_seq/` | 에러 뒤 CQE 순서: fault 후 NIC이 쓰는 CQE 순서(CPU verbs) |
| `harness/gpu-initiated/gin/` | 스택별 동작: NCCL 2.32.3 GIN proxy·GDAKI, 네 가지 fault, fault-inject diff |
| `harness/gpu-initiated/nvshmem/` | 스택별 동작·collapsed CQ 읽기: NVSHMEM IBGDA 네 가지 fault, collapsed CQ 읽기, fault-inject diff |
| `harness/gpu-initiated/gin_q4/` | A/B·GPU 분류기: collapsed vs ring CQ, 장치측 분류 + host mailbox |
| `harness/gpu-initiated/nvshmem_rootcause/` | NVSHMEM CPU-proxy doorbell-record 버그 규명(CPU 재현, A/B/C 비교) |
| `harness/gpu-initiated/gpu_doorbell/` | PeerMappingOverride 적용 스크립트와 GPU-rung doorbell 실험 |
| `harness/gpu-initiated/gin_recovery/` | GDAKI 복구 diff(CPU doorbell용과 GPU doorbell용 v2), 설계, 결과 |
| `harness/gpu-initiated/nvshmem_ft/` | NVSHMEM IBGDA 분류 + 복구(`NVSHMEM_IBGDA_FT=1`) |

원 연구 수치의 근거와 전체 기록: [docs/experiments/README.md](docs/experiments/README.md). 현재 테스트베드 수치: [harness/README.md](harness/README.md), [harness/gpu-initiated/RESULTS.md](harness/gpu-initiated/RESULTS.md).
