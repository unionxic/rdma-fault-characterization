# A/B Recovery Strategy 비교: 주소위반(REM_ACCESS_ERR) Partial Write

REM_ACCESS_ERR (NAK, address out of bounds)로 인한 partial RDMA WRITE에 대해 두 가지 recovery 전략을 동일 시나리오에서 비교하는 harness.

## 무엇을 측정하는가

multi-packet WRITE가 서버 MR 경계를 넘으면, 경계 안에 들어가는 PMTU(1024) 정수배 패킷들은 DMA commit되어 서버 메모리에 남고(partial write), 경계 패킷부터 REM_ACCESS_ERR NAK가 돌아온다. 이 partial이 corruption hazard다. 이 사실은 `verify_partial_write.c`에서 이미 검증됨: partial은 항상 whole-PMTU-packet 단위이고, requester가 `sq_psn_delta × PMTU`로 서버에 써진 바이트를 복원할 수 있다.

두 전략을 비교한다.

| | 전략 A (reactive) | 전략 B (proactive) |
|---|---|---|
| 정상 경로 | 경계 체크 없음, 비용 0 | 매 WRITE 직전 로컬 범위 체크(정수 비교) |
| 위반 시 | NAK 수신 → sq_psn 복원 → QP recovery → 통째 재전송 | wire에 안 보냄, 주소 교정 후 write |
| partial 발생 | 발생 (corruption window > 0) | 미발생 (corruption window = 0) |
| 측정 목적 | 에러 1건당 detect+recover+resend 비용, corruption window | 정상 경로마다 체크 오버헤드 누적, partial 회피 |

핵심 가설: 에러율이 낮으면 B의 per-write 체크 오버헤드가 누적되어 A보다 느릴 수 있고, 에러율이 높으면 A의 per-error recovery 비용이 지배해 B가 빨라진다. 둘의 교차점(break-even error rate)을 찾는다.

## 시나리오 (양 전략 공통)

- 서버는 `AB_BUF_SIZE`(1MB) backing buffer를 잡되 MR은 `mr_size` 바이트만 등록한다. `[0, mr_size)`가 유효한 WRITE 대상, `[mr_size, AB_BUF_SIZE)`는 경계 밖.
- 위반 WRITE는 offset `violate_off = mr_size - msg_size/2`에서 시작 → `[violate_off, violate_off+msg_size)`가 MR 경계 `mr_size`를 가로지른다. 경계 앞 `[violate_off, mr_size)`(=in-MR straddle 영역)에 partial이 떨어진다.
- 정상 WRITE / 교정된 WRITE / A의 재전송은 모두 offset 0(`CORRECT_OFFSET`)에 떨어진다. `msg_size <= mr_size`를 강제하므로 항상 in-MR.

single-packet(`msg_size <= 1024`) 위반은 NIC이 전체 range를 먼저 검사해 통째로 거부(NO_WRITE) → `sq_psn_delta=0`, partial 0. 이 경우 A에서도 실제 corruption은 없다(server CHECK_AB가 partial_bytes=0 확인). multi-packet과의 대조군으로 의도된 동작이다.

## 전략 구현 요지

전략 A (`ab_recovery.c`, `strategy=='A'`)
1. 정상 WRITE를 보낸다(경계 체크 안 함).
2. 위반 시 REM_ACCESS_ERR CQE 수신 → `ibv_query_qp(IBV_QP_SQ_PSN)`로 `sq_psn_delta` 측정 → `landed_bytes = sq_psn_delta × PMTU`.
3. recovery 전에 즉시 서버에 `CHECK_AB`를 보내 straddle 영역 `[violate_off, mr_size)`의 실제 기록 바이트(`partial_truth`)를 ground truth로 받는다. `landed_bytes == partial_truth` 여부가 복원 정확도(`recon_match`).
4. QP-only recovery: `reset_qp_to_reset` → 새 PSN → `tcp_exchange_qp_info` → `connect_qp`(server `RECOVER_AB`와 lockstep). 같은 MR/buffer 유지.
5. 전체 메시지를 offset 0으로 통째 재전송, 완료 CQE 대기.

전략 B (`ab_recovery.c`, `strategy=='B'`)
1. 연결 시 서버가 qp_info 교환 직후 `mr_base,mr_size` 한 줄을 추가로 보낸다(아래 "MR 경계 교환" 참고). 클라이언트가 캐시.
2. 매 WRITE 직전 `remote_addr + len <= mr_base + mr_size` 체크. 통과하면 그대로 write.
3. 위반 예정이면 wire에 안 보내고 주소를 `CORRECT_OFFSET`으로 교정해 write. partial 미발생 → corruption window = 0.

## 설계상 주의점

MR 경계 교환 (전략 B)
`struct qp_info`(common.h)는 `rkey`와 `raddr`만 나르고 MR length를 나르지 않는다. 기존 구조체를 건드리면 모든 실험이 영향받으므로, server가 qp_info 교환과 `connect_qp` 직후 별도 control line `"<mr_base>,<mr_size>"`를 보내는 방식으로 additive하게 확장했다(`server.c: send_ab_bounds`). 클라이언트는 `recv_ab_bounds`로 읽는다. QP-only recovery 후에도 MR이 그대로이므로 server가 같은 bounds를 다시 보낸다.

Corruption window 측정
task 정의 그대로 "partial이 서버 메모리에 남은 시점 ~ 올바른 데이터 재전송 완료 시점"을 잰다. 시작 = 위반 WRITE를 `ibv_post_send`한 직후(`t_partial`; partial이 실제 land하기 직전이라 약간 conservative), 끝 = 재전송 완료 CQE(`t_corr_end`). B는 partial이 없으므로 0으로 기록.
주의: A의 재전송은 offset 0에 떨어지고 stale partial은 `[violate_off, mr_size)`에 남아 둘이 겹치지 않는다(default 설정). 따라서 재전송이 끝나도 stale corrupt 바이트는 별도로 지워야 한다. harness는 측정 직후 `INIT_AB`로 서버 버퍼를 zero해 다음 trial을 오염시키지 않게 한다. 실제 시스템이라면 recovery가 corrupt 영역도 덮어쓰거나 0으로 만들어야 한다는 점을 명시.

복원 정확도 검증
A는 매 에러 trial마다 recovery 전에 ground truth(`partial_truth`)를 받아 `landed_bytes`와 비교(`recon_match`). recovery/resend 전에 측정하므로 작은 `mr_size`에서 재전송 영역 `[0, msg_size)`이 straddle 영역과 겹쳐 ground truth를 망치는 것을 피한다.

측정 jitter (기존 발견 반영)
busy-poll jitter에 민감하므로 (1) warmup trial(`warmup`, default 200)을 측정에서 분리하고, (2) 정상 WRITE latency는 mean/p50/p99로 보고하며, (3) 에러 주입은 deterministic interval(`i % interval == 0`)로 재현 가능하게 한다.

디바이스 이름
하드코딩 없음. `common.h`의 `open_ib_device(IB_DEV_NAME)`가 이름이 안 맞으면 IB_PORT가 ACTIVE인 첫 디바이스로 fallback한다(225=`rocep1s0f0`, 224=`mlx5_0` 모두 동작).

## 실험 변수 (sweep)

run script 기본값:
- 에러율 p: 0%, 1%, 10% (`i % round(100/p)` 주입)
- 메시지 크기: 1024B(single-packet), 4096B(multi-packet)
- 서버 MR 크기: 65536B (인자로 1종; 필요시 추가)
- 전략: A, B

에러율–총시간 곡선(`total_wall_us` vs `err_pct`)을 A/B에 대해 그리면 break-even을 볼 수 있다.

## CSV 스키마

출력: `results/raw/ab_recovery.csv`. 18 컬럼. `phase`로 행 종류 구분.

| 컬럼 | phase=error 의미 | phase=summary 의미 |
|---|---|---|
| strategy | A 또는 B | 동일 |
| iter | 위반이 발생한 iteration index | -1 |
| msg_size | WRITE 바이트 | 동일 |
| err_pct | 주입 에러율(%) | 동일 |
| mr_size | 서버 등록 MR 바이트 | 동일 |
| phase | `error` | `summary` |
| sq_psn_delta | requester SQ_PSN 증가량(패킷 수); B는 0 | 측정 loop 총 iteration 수 |
| detect_us | post → NAK CQE (A); B는 0 | 0 |
| recover_us | QP recovery 시간(A) / 체크+교정+write(B) | 에러 1건당 평균 recover_us |
| corrupt_us | corruption window(A) / 0(B) | 에러 1건당 평균 corruption window |
| landed_bytes | `sq_psn_delta × PMTU`(복원값) | 에러 1건당 평균 landed_bytes |
| partial_truth_bytes | server straddle 영역 실제 기록 바이트 | 에러 1건당 평균 partial_truth |
| recon_match | `landed_bytes == partial_truth_bytes` (1/0) | 복원이 맞은 trial 수 |
| norm_mean_us | 0 | 정상 WRITE latency 평균(µs) |
| norm_p50_us | 0 | 정상 WRITE p50(µs) |
| norm_p99_us | 0 | 정상 WRITE p99(µs) |
| norm_count | 0 | 측정한 정상 WRITE 수 |
| total_wall_us | 0 | 측정 loop 전체 wall-clock(µs) |

정상 WRITE는 per-row를 안 남기고 summary 행에 분포로 접는다(throughput/latency 비교용). 에러는 per-row를 남긴다.

## 빌드

서버(224)와 클라이언트(225)는 별도 빌드. server.c는 additive 확장(새 CMD_*_AB 핸들러)만 했고 기존 동작 유지.

```
# 서버 (224)
cd ~/Desktop/gpu_fault_recovery/05_counter_mapping
make server

# 클라이언트 (225)
cd ~/Desktop/gpu_fault_recovery/05_counter_mapping
make ab_recovery
```

공유 헤더 `common.h`는 양쪽에 동일 변경(`CMD_SETUP_AB/RECOVER_AB/INIT_AB/CHECK_AB`, `AB_BUF_SIZE`)이 들어갔다. mutagen sync로 전파됨.

## 실행

`run_ab_recovery.sh`가 225에서 orchestration(ssh로 224 server 구동, sweep 루프, CSV header 생성). 서버 빌드/실행도 스크립트가 ssh로 한다.

```
cd ~/Desktop/gpu_fault_recovery/05_counter_mapping
./run_ab_recovery.sh [num_iters=10000] [warmup=200] [mr_size=65536]
```

수동 실행(단일 combo, 디버깅용):
```
# 224: ./server
# 225:
./ab_recovery A 10000 4096 1   65536 200   # 전략 A, 4KB, 1% 에러
./ab_recovery B 10000 4096 1   65536 200   # 전략 B, 동일 조건
```

인자: `A|B  num_iters  msg_size  err_pct  mr_size  warmup`. CSV는 append되므로 수동 실행 전 header가 없으면 직접 만들거나 run script를 쓸 것.

## 환경 (재현용)

| 항목 | Client (225) | Server (224) |
|---|---|---|
| NIC | ConnectX-6 (MT28908) | ConnectX-5 (MT27800) |
| Firmware | 20.40.1000 | 16.35.8002 |
| Kernel | 6.14.0-custom-junseolee | 6.16.2 |
| RDMA IP | 10.0.0.2 | 10.0.0.3 |
| Link | 100 Gbps RoCE v2 | 100 Gbps RoCE v2 |
| PMTU | IBV_MTU_1024 (RTR `path_mtu`) | 동일 |

[TODO: 실험 필요] 실제 측정값(정상 latency, recover_us, corrupt_us, break-even err_pct)은 하드웨어에서 실행 후 채울 것.
