# 갈래 기록: exp/gin-mirror-store (RDMA 저장소)

[PARALLEL.md](PARALLEL.md)의 `exp/gin-mirror-store` 행이다. 통합 때 메인 세션이 아래 "12절 행"을 [../EXPERIMENT.md](../EXPERIMENT.md) 12절로
옮기고 이 파일을 지운다. 이 갈래는 `EXPERIMENT.md`와 공유 헤더 여섯을 고치지 않았다.

- 바탕: 빌드 트리 `agent_mi_store/`(세션 스크래치). `build_mi.sh setup`이 i5(rs_layer.diff `f005bb67`, libnccl `4811f28f`, `be91b270`)를
  확인하고 복사했다. 갈래 diff는 [mi_layer_store.diff](mi_layer_store.diff)(인터페이스 붙이기 포함; md5는 아래 "빌드와 시험").
- 줄 번호: 따로 적지 않으면 [rs_layer.diff](../../restore/impl/rs_layer.diff)(md5 `f005bb67`)의 줄이다. 이 갈래 트리의 줄은 통합 뒤
  바뀌므로 영역과 함수 이름으로 적는다.

## 12절 행

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-13 | store 갈래 구현(RDMA 저장소). 충돌 검토: rs_store_api.h의 경계 목록을 rs_layer.diff의 해당 줄(8410–8574, 8232–8285, 8629–8751, 9259–9361, 7039–7083)과 대조, 설계 충돌 없음. 인터페이스 틈 넷(아래)은 경계 밖 한 줄 hook 셋과 STORE_REQ 뒤 바이트로 메우고 표시함. 붙인 것: (1) 새 영역 "gin-mirror (store): declarations", "pure", "the RDMA checkpoint store": GIN PD의 호스트 RC QP 도구(만들기 INIT, 잇기 RTR/RTS timeout 12 retry_cnt 7 rnr_retry 7, 조각 전송과 CQ 걷기, 한도 넘으면 ERR로), 짝 쪽 저장소(맡은 rank마다 자리 둘의 MR, 0 기준, RO 없음, 세대, 앞 MR이 확정 자리를 쥐면 다음 확정까지 유지), STORE_REQ(50)/STORE_ACK(51)의 양쪽, 올리는 쪽 요청 기계(처음, 배치 바뀜, QP 실패, 짝 화신, 답 없음 5 s, 거절 뒤 1 s), 고정 D2H 버퍼(자리 꼴, GIN PD 등록), 멈춤 안 D2H와 머리와 덩어리, 멈춤 밖 WRITE(application 스레드, `NCCL_GIN_RESTORE_STORE_WRITE_MS` 500), 확정 자리의 판정, 활성화용 `gdakiStoreActInfoOf`, 정리. (2) 체크포인트 기계의 경계 줄: IDLE 거절 "the checkpoint store is not ready", COPYING의 arm, CONFIRMING의 쓰기 상태와 CKPT_STABLE 칸(짝과 나머지 모두), 기반 블록은 TCP 길만, `gdakiCkptOnStable`의 짝 갈래, `gdakiCkptTake` 첫 줄. (3) mirror 끔 TCP 길(9.6): `gdakiCkptUploadOne`의 모든 끝에서 OK ack가 아니면 기반 지움, `gdakiHoldApplyRestored`에서 짝의 RESTORED면 기반 지움 | 빌드 트리 `agent_mi_store/`, [mi_layer_store.diff](mi_layer_store.diff), [mi_unit_store.cc](mi_unit_store.cc), 이 파일 |
| 2026-10-13 | 빌드와 시험(이 갈래가 돌림, 클러스터 없음): 아래 "빌드와 시험" | 이 파일 |
| 2026-10-13 | 독립 코드 리뷰(같은 모델의 다른 에이전트, 읽기만): 아래 "독립 리뷰" 1 | 이 파일 |
| 2026-10-14 | 리뷰 1, 2의 고침: 호스트 QP와 CQ의 문맥에 `ncclIbStats`(비동기 치명 이벤트를 전송 실패로 셈), STORE_ACK 뒤 바이트(짝의 확정 자리)와 소켓 재설치 뒤 새 요청, RESTORED 한 번 규칙, 줄 끝 `mono_ms`, 멈춘 뒤 상태 재생성 막기, arm 기다림 한도. unit에 소켓 규칙 대조 모델 | [mi_unit_store.cc](mi_unit_store.cc), 아래 "인터페이스 밖에서 정함" 10–14 |
| 2026-10-15 | 리뷰 1의 확인(net_ib 소스), 다시 리뷰(높음 0, 중간 1, 낮음 4)와 그 고침: hold 중 앞 MR 미루기, `NCCL_GIN_RESTORE_STORE_MAX_MB`, declined와 붙잡힌 rank의 요청 버리기와 declined rank 저장소 놓기, 실패한 verbs 호출 때 메모리 남기기. 빌드와 시험 다시 | 아래 "빌드와 시험", "독립 리뷰" 2, "인터페이스 밖에서 정함" 15–18 |

## 충돌 검토 (구현 전)

- 경계 목록의 줄(IDLE 거절 8440–8446, COPYING 8514, CONFIRMING 8525–8531과 8545–8562, `gdakiCkptOnStable` 8236–8248, `gdakiCkptTake`
  9259–9361, `gdakiCkptUploadOne` 8671–8751, `gdakiHoldApplyRestored` 7076 뒤 한 줄)이 rs_layer.diff에서 인터페이스가 적은 내용과 같음을 확인했다
  `[소스]`. segment 갈래(host)가 고치는 줄(8070–8093, 8109–8174, 8175–8231, 8249, 9383)과 겹치지 않는다.
- 설계 충돌 없음. 인터페이스 틈은 아래 "인터페이스 틈"이다(구현을 막지 않아 표시하고 진행함).

## 인터페이스 틈 (메인 세션이 정할 것)

1. **`gdakiStoreStep`을 부르는 자리.** 인터페이스는 "every helper step"이라 적었으나 경계 목록에 그 자리가 없다. `gdakiCkptStep`(rs_layer.diff
   8619–8623)의 `gdakiCkptPeerStep` 뒤, `gdakiCkptInitStep` 앞에 한 줄을 넣었다(경계 밖 hook 1).
2. **저장소 상태의 정리 자리.** 갈래마다 "자기 teardown"에서 푼다고 했으나 자리가 없다. `gdakiCkptFree`(경계 밖)의 `gdakiCkptStop` 뒤에 한 줄
   (`gdakiStoreFree`)을 넣었다(경계 밖 hook 2). 이때 helper와 데이터 스레드는 멈췄고 GIN PD는 살아 있다(`gdakiRsLogFree`의 루프백 쌍과 같은 때).
3. **store 길의 예비 프로세스 등록.** 활성화(`gdakiHoldActivate`)는 `gdakiHoldSpareOf`로 맡긴 rank의 예비 프로세스 주소, PID, 시작 시각과 확정
   체크포인트를 얻는데, store 길에는 `ck->store`가 비고 짝은 자리를 읽지 않으며 `gdakiStoreActInfo`에도 이 셋이 없다. 그대로면 mirror 켬의
   모든 복원이 "no spare process is registered"로 fallback한다(spare 갈래 notes의 틈 6과 같은 것). 이 갈래는 STORE_REQ의 바이트 80–135에
   `gdakiStoreReqSpare`(magic, 주소, PID, 시작 시각)를 싣고 짝이 맡은 rank의 기록에 두며, `gdakiHoldSpareOf`(경계 밖) 첫 줄에서 store 길이면
   `gdakiStoreSpareOf`를 부른다(경계 밖 hook 3). 헤더로 옮긴다면 `gdakiStoreReq` 뒤 칸 셋과 `gdakiStoreActInfo`의 칸 셋을 제안한다.
4. **serve 스레드에 넘길 입구.** 인터페이스는 짝의 등록을 "data (serve) thread"에 넘긴다고 적었으나 `gdakiCkptServeMain`(8886–8900)은 경계
   밖이고 spare 갈래도 같은 함수를 쓰려 한다(그 notes의 틈 5). 이 갈래는 저장소 스레드를 따로 두었다(아래 "인터페이스 밖에서 정함" 1). serve
   스레드로 옮기려면 작업 함수 `gdakiStoreServe`를 그 루프에서 부르면 된다.

경계 밖 hook 셋은 모두 한 줄이고 주석 "hook outside the boundary list: notes_store.md"를 달았다. 통합 때 받아들이거나 다른 자리로 옮긴다.
mirror 켬의 RESTORED는 host 갈래가 `gdakiMiApplyRestored`로 돌리며 그 안에서 `gdakiStoreOnBuddyRestored`를 부른다(host notes 8). 이 갈래가
7076 뒤에 넣은 한 줄은 그 분기 뒤의 v1 길, 곧 mirror 끔 TCP 길(9.6)을 위한 것이다. 함수는 두 길을 모두 받는다. 통합 뒤 두 길이 같은 RESTORED에
대해 이 함수를 두 번 부르더라도 둘째 호출은 아무것도 바꾸지 않는다(짝의 화신 `gdakiRsPeerInc`로 한 번만 적용; "인터페이스 밖에서 정함" 11).
하나만 남기려면 7076 뒤의 한 줄을 지우고 `gdakiMiApplyRestored`의 호출만 두면 된다(mirror 끔 길은 그 함수가 v1 길이라 함께 받아야 함).

메인 세션에 알릴 것(다른 갈래의 조건):
- spare 갈래: FETCH 버퍼 MR과 이 갈래의 호스트 QP는 같은 PD여야 한다. 이 갈래의 호스트 QP와 저장소 MR, 고정 D2H 버퍼의 MR은 모두 GIN PD
  (`collComm->ib.pd`)에 있다(`gdakiMiHostQpCreate`, `gdakiStoreServe`, `gdakiStoreStage`). spare가 FETCH 버퍼를 같은 PD에 등록하면 맞는다.
- spare 갈래의 "store 길에서 짝이 예비 프로세스의 주소, PID, 시작 시각을 알 길이 없음": 이 갈래가 STORE_REQ 뒤 바이트(틈 3)로 싣고
  `gdakiHoldSpareOf`의 첫 줄 hook으로 돌려준다. 되살린 짝은 맡긴 rank의 다음 STORE_REQ(RESTORED 뒤 `reason=buddy`)에서 받는다. 헤더에 넣으려면
  `gdakiStoreReq` 뒤 칸 셋(haveSpare, spareAddr[32], pid, pidStart)과 `gdakiStoreActInfo`의 칸 셋을 제안한다.
- host 갈래: `gdakiStoreOnBuddyRestored`의 v1 본문은 위 문단처럼 두 번 불려도 안전하다.
- 기반 계층의 노출(이 갈래가 고치지 않음, rs_layer.diff의 범위): gin-restore의 GIN PD 루프백 QP 쌍(`gdakiRsAtomicOp`의 쌍과 drain 울타리의 쌍)도
  qp_context와 cq_context가 비어 있어 같은 ibv_context의 net_ib 비동기 이벤트 스레드가 그 QP의 QP_FATAL, QP_REQ_ERR, QP_ACCESS_ERR, CQ_ERR을
  받으면 널 역참조한다(아래 "독립 리뷰" 1과 같은 꼴). 메인 세션이 gin-restore 쪽에 적을지 정한다.
- 통합 순서(다시 리뷰 R4, `[추론]`): `gdakiHoldSpareOf`의 store hook(경계 밖 hook 3)은 spare 갈래의 활성화 v2(`gdakiMiSendActivate`, RDMA
  FETCH)와 함께 들어가야 한다. 이 갈래만으로 mirror를 켜면 v1 활성화가 예비 프로세스를 깨우지만 짝의 TCP FETCH가 읽을 `ck->store`는 비어
  있어, 전처럼 "no spare process is registered"로 곧바로 fallback하지 않고 예비 프로세스를 깨운 뒤 실패한다. FETCH serve 쪽 동작은 리뷰어도
  확인하지 않았다 `[미확인]`.
- 기반 계층의 노출(다시 리뷰 R1에서 나옴, `[추론]`): gin-restore의 `gdakiCkptOnStable`은 보낸 rank가 붙잡혀 있어도 CKPT_STABLE을 처리한다.
  ward가 CKPT_STABLE을 보낸 직후 죽고 그 기록이 hold가 열린 뒤에 읽히면, 활성화가 보낸 step(K_old)과 달리 생존 rank의 log가 K_new로 잘릴 수
  있다(TCP 길도 같음). 이 갈래는 저장소 메모리만 지킨다(인터페이스 밖 16).

## 인터페이스 밖에서 정함

1. **저장소 스레드.** 짝 쪽 등록(메모리 할당과 0 채움, MR 등록, 응답 QP 만들기와 잇기)과 바뀐 MR의 해제는 문맥마다 하나인 저장소 스레드가
   한다(mirror 켬에서 처음 쓸 때 만듦, `gdakiStoreFree`에서 join). helper는 STORE_REQ를 넘기고, 끝난 것의 STORE_ACK를 보낸다(helper 소켓은
   helper만). 한 맡은 rank의 요청은 하나씩, 그동안 온 새 요청은 하나만 남겨 다음에 처리한다(앞의 답은 보내지 않음).
2. **STORE_REQ 뒤 바이트**(틈 3): `GDAKI_STORE_SPARE_OFF` = 80부터 `struct gdakiStoreReqSpare` 56 B(magic "GRSP"). 짝만 읽는다.
3. **세대**: 짝의 문맥마다 하나인 카운터(1부터), 처리한 요청마다 하나씩. 같은 크기면 MR을 다시 쓰고(QP만 새로) 확정 자리도 남는다. 자리가
   더 커야 하면 새 MR을 등록하고, 지금 MR이 확정 자리를 쥐면 "앞 MR"로 남겨 활성화가 그것을 읽게 하고, 새 MR에 다음 확정 자리가 생기면
   저장소 스레드가 앞 MR을 푼다. 맡은 rank의 새 화신의 요청은 확정 자리를 버린다(gin-restore P5: 되살린 rank는 자기 다음 확정에서 다시 무장).
4. **올리는 쪽의 확정 자리 보기**: CKPT_STABLE을 짝에게 보낸 뒤(`gdakiStoreStableSent`, 8551–8556 자리의 store 분기) 그 자리를 확정으로 보고
   다음 WRITE는 다른 자리에 한다. 짝이 그 CKPT_STABLE을 거절했으면 짝이 DISARM을 모두에게 보내므로 무장된 rank가 없는 동안 옛 확정 자리를
   덮는다. 짝의 화신이 바뀌거나 RESTORED면 보기를 지운다(새 짝 프로세스는 아무것도 없음).
5. **요청의 때**: Resume 뒤(`gdakiHoldCommArmedNow`), 이 rank의 체크포인트가 IDLE이고 WRITE가 없을 때, 짝의 helper 소켓이 있고 짝이 붙잡혀 있지
   않을 때만. 처음 요청의 배치는 application이 아직 알리지 않았으면 helper가 `gdakiCkptRegions`로 셈한다. 답이 5 s 없으면 새 요청(새 QP),
   거절, 보내기 실패, 잇기 실패 뒤 1 s 쉼. 같은 실패 줄은 첫 번째와 30번째마다 찍는다.
6. **application 스레드의 차례**(`gdakiStoreTake`): 배치를 알림 → 고정 버퍼(필요하면 다시 할당, `cudaHostAlloc` + GIN PD 등록) → ASKED →
   DRAINED를 기다림(gin-restore와 같은 한도) → PAUSED의 P를 복사 → D2H(복사 stream)와 머리와 덩어리 → COPIED → helper의 arm을 1 ms 조각으로
   기다림(한도 max(멈춤 한도 × 3, `NCCL_GIN_RESTORE_DRAIN_MS` + 200 ms × rank 수) + 1 s: helper의 COPYING 한도(멈춤 시작부터 멈춤 한도의 3배)와
   drain 재확인, 상대마다 CKPT_RESUME 보내기를 덮음; 그 전에 helper가 IDLE로 가거나 req가 바뀌면 그만) → WRITE → 쓰기 상태. 기다림을 그만둔 뒤의 arm은 "실패"로 셈해 CONFIRMING이 곧바로 void한다. 짝이 거절됐거나
   (declined) 소켓이 없거나 붙잡혀 있으면 요청하지 않는다.
7. **호스트 QP**: max_send_wr 64, CQ 128, 모든 조각 signaled. WRITE 조각 ≤ 1 GiB(한 번에 8개까지), READ 조각 ≤ 32 MiB(max_rd_atomic까지
   동시). INIT의 접근 권한은 두 쪽 모두 LOCAL_WRITE | REMOTE_WRITE | REMOTE_READ(같은 함수가 올리기와 FETCH 양쪽에 쓰임). PSN 24비트 무작위.
   RoCE의 traffic class는 GIN과 같은 차례(`NCCL_GIN_IB_TC`, 없으면 `NCCL_IB_TC`, 없으면 0; communicator 설정의 trafficClass는 보지 않음), hop limit 255,
   IB는 `NCCL_IB_SL`. 짝 쪽 올리기 QP도 RTS까지 올린다(인터페이스의 "RTR"을 포함). 한도를 넘긴 전송은 QP를 ERR로 옮기고 flush된 완료를 200 ms까지
   걷는다(그 뒤 NIC이 버퍼를 읽지 않음).
8. **줄의 수준**: 키 줄 "checkpoint %lu stored at", "store request to", "store ready at"은 gin-restore의 규칙대로 `GIN_TS_NOTE`(연구 빌드 WARN,
   운영 빌드 INFO). "store summary"는 두 빌드 모두 WARN(store_rdma 예측의 근거라 어느 빌드에서도 보이게). summary에 키 `served=`(짝으로서 받아들인
   요청 수)를 더했다.
9. **summary의 tcp 바이트**: `tcp_image_bytes`는 이 rank가 데이터 소켓으로 보낸 UPLOAD 바이트(gin-restore의 `nUploadBytes`; mirror 켬이면 그
   길을 타지 않으므로 0이어야 함). `tcp_segment_bytes`는 이 갈래의 어떤 길도 segment 바이트를 소켓으로 보내지 않아 늘 0을 찍는다(잰 값이
   아님). 내보내기의 원본 바이트는 spare 갈래의 "export" 줄 `source_bytes=`가 잰다.
10. **호스트 QP의 qp_context와 cq_context**(독립 리뷰 1): 호스트 QP마다 `struct ncclIbStats`를 하나 두고 QP의 qp_context와 CQ의 cq_context로
    넘긴다. net_ib의 비동기 이벤트 스레드(`ncclIbAsyncThreadMain`, 같은 `ibv_context`)가 그 QP나 CQ의 치명 이벤트를 받으면 그 수를 올린다.
    전송(`gdakiMiHostQpXfer`)은 시작할 때와 CQ를 걷을 때마다 그 수가 0이 아니면 실패로 보고 QP를 ERR로 옮긴다(교체 대상).
11. **RESTORED 적용의 한 번 규칙**: `gdakiStoreOnBuddyRestored`는 짝의 화신(`gdakiRsPeerInc`)마다 한 번만 요청 기계를 되돌린다. 같은 화신의
    둘째 호출은 아무것도 하지 않는다(통합 때 host 갈래의 mirror 켬 길과 v1 길이 모두 부를 수 있음).
12. **STORE_ACK 뒤 바이트와 소켓 규칙**(독립 리뷰 2): `GDAKI_STORE_ACKS_OFF` = 160부터 `struct gdakiStoreAckStable` 32 B(magic "GRSS"; 짝이
    쥔 이 rank의 확정 자리, 세대, 체크포인트). 올리는 쪽은 받아들인 답마다 확정 자리 보기를 이것으로 바꾼다. 저장소가 준비된 뒤 짝으로 가는
    helper 소켓이 다시 놓이면(`r->ts->peers[b].gen`이 바뀜) 새 요청(`reason=socket`)을 낸다. 잃은 소켓에 묶여 짝이 읽지 못한 CKPT_STABLE이
    있었다면 올리는 쪽의 보기만 움직였으므로, 다음 WRITE가 짝의 실제 확정 자리를 덮을 수 있었다.
13. **창이 아직 없을 때**: 첫 요청의 배치를 셀 수 없으면(등록된 창 없음) 250 ms 뒤 다시 본다(helper 걸음마다 세지 않음).
14. **멈춘 뒤의 상태**: `gdakiCkptStop` 뒤에는 저장소 상태를 새로 만들지 않는다(`gdakiStoreOf`가 `ck->stop`을 봄). 늦게 부른 쪽이 상태와
    저장소 스레드를 다시 만들어 문맥보다 오래 남는 일을 막는다.
15. **짝 쪽 메모리 상한**(다시 리뷰 R2): 새 매개변수 `NCCL_GIN_RESTORE_STORE_MAX_MB`(기본 4096, 0 이하는 상한 없음)는 맡은 rank 하나의 MR(자리
    둘)의 상한이다. 넘는 요청은 할당하지 않고 거절한다(`the store needs %lu MiB > NCCL_GIN_RESTORE_STORE_MAX_MB %ld`). overcommit에서 큰 할당의
    0 채움이 생존 rank를 OOM으로 죽이는 대신 거절되게 하려는 것이다. 학습 모양은 맡은 rank당 약 62 MiB다.
16. **hold 중 앞 MR 미루기**(다시 리뷰 R1): 맡은 rank가 붙잡힌 동안(`gdakiHoldIsHeldState`) 읽힌 CKPT_STABLE이 앞 MR을 놓게 하면, 그 MR은
    바로 풀지 않고 맡은 rank가 붙잡힘에서 벗어날 때(RESTORED나 FALLBACK) 저장소 스레드가 푼다. 활성화가 이미 예비 프로세스에 앞 MR의 rkey를
    넘겼을 수 있어서다. 확정 자리는 gin-restore의 TCP 길처럼 움직인다.
17. **declined와 붙잡힌 rank의 요청**(다시 리뷰 R3): declined(끝) rank의 STORE_REQ는 받지 않고, 붙잡힌 rank의 것은 아는 화신보다 새 화신의
    것(되살린 프로세스가 RESTORED 적용 전에 보낸 것)만 받는다. 답은 보내지 않는다(INFO 줄만). declined rank가 붙잡혀 있지 않으면 그 rank의
    저장소(응답 QP, 그다음 MR 둘과 메모리)를 한 번 놓는다.
18. **실패한 verbs 호출**(다시 리뷰 R5): QP나 CQ를 없애지 못하면 `struct gdakiMiHostQp`를 풀지 않는다(qp_context가 가리키는 `stats`를 남김).
    MR 등록을 풀지 못하면 그 메모리를 풀지 않는다(저장소 MR, 고정 D2H 버퍼 모두). 둘 다 WARN과 함께 새는 쪽을 고른다. ERR로 옮기지 못하면
    WARN만 한다(그 QP는 다음 요청에서 없어지고, 버퍼는 MR을 푼 뒤에만 풀림).

## 줄 형식(test 갈래가 읽는 것)

`GIN/MI: rank %d: `로 시작하고 ` mono_ms=%.3f`로 끝난다.

```
GIN/MI: rank %d: checkpoint %lu stored at buddy rank %d slot=%u bytes=%lu d2h_us=%.0f write_us=%.0f mono_ms=%.3f
GIN/MI: rank %d: store request to buddy rank %d seq=%lu slot_bytes=%lu reason=%s mono_ms=%.3f
GIN/MI: rank %d: store ready at buddy rank %d gen=%lu stable_slot=%d mono_ms=%.3f
GIN/MI: rank %d: store summary writes=%lld failed=%lld requests=%lld tcp_image_bytes=%lld tcp_segment_bytes=0 served=%lld mono_ms=%.3f
```

- stored: application 스레드가 WRITE가 모두 끝난 때 찍는다. bytes = 자리에 쓴 바이트(머리 + 이미지 + 덩어리), d2h_us = 멈춤 안 D2H(머리와
  덩어리 포함), write_us = WRITE를 낸 때부터 마지막 완료까지. `reason=`은 키 밖에 더한 것(first, layout, qp, buddy, retry, refused, socket).
  ready 줄의 `stable_slot=`(키 밖)은 답의 뒤 바이트로 받은 짝의 확정 자리(-1: 없음).
- 그 밖의 줄(키 아님, `GIN_TS_NOTE`): `store for rank %d ready (request %lu) gen= slot_bytes= stable_slot=`(짝), `store request %lu of rank %d refused (%s)`(짝),
  `store request %lu not accepted from buddy rank %d (%s: %s; %d in a row)`, `the upload QP to buddy rank %d could not be connected (%s)`,
  `store request to buddy rank %d not sent (%s; %d in a row) reason=`, `the store WRITE of checkpoint %lu to buddy rank %d failed (%s); the
  checkpoint is void and the store is requested again write_us=`, `CKPT_STABLE %lu of rank %d does not fit its store here (%s)`(짝; 그 뒤
  gin-restore의 "no complete upload of it here" 줄과 DISARM), `buddy rank %d restored: the store is requested again`; mirror 끔 TCP 길은
  `GIN/RS: rank %d: buddy rank %d restored: the next upload carries every block`. WARN: 고정 버퍼의 할당이나 등록 실패, MR 등록 해제나 QP와 CQ 없애기의 실패(그 메모리를 남김), 실패한 전송 뒤 QP를 ERR로
  옮기지 못함. INFO(키 아님): `store request %lu of rank %d (incarnation %u) dropped: the rank is declined|held`, `the store of declined rank %d is let go`.
- 체크포인트를 찍지 않은 까닭은 gin-restore의 줄 `checkpoint %lu not taken: the checkpoint store is not ready`로 보인다.

## 빌드와 시험

이 갈래가 돌렸다(2026-10-15, rain, 클러스터 없음, GPU와 RDMA 프로그램 실행 없음). 빌드 기록 전체는 `agent_mi_store/out/build_info.txt`.

| 단계 | 결과 | 근거 |
|---|---|---|
| `api` | 헤더 여섯이 함께 컴파일됨(진입점 선언 있음과 없음), 붙인 블록이 헤더와 바이트 단위로 같음 | `agent_mi_store/api4.log` |
| `mi`(연구 빌드) | 빌드됨, `gin_host_gdaki.cc` 경고 0 | `out/mi_store_v4` libnccl `8b30536d`, `mi_build5.log` |
| `mip`(운영 빌드) | 빌드됨, 경고 0 | `out/mip_store_v4` libnccl `c9a49f84`, `mip_build4.log` |
| `unit`(g++ 8.4.0 -std=c++17 -O1, ASan과 UBSan) | 시험함: 6 531 610 검사, 실패 0 | `unit_v4.log`, [mi_unit_store.cc](mi_unit_store.cc) md5 `06aae731` |
| `diff` | [mi_layer_store.diff](mi_layer_store.diff) md5 `50733a4a`(작업 트리 diff와 같음, 바뀐 파일 둘: 공통 헤더의 붙이기와 `gin_host_gdaki.cc`) | `build_info.txt` |

- unit의 모델(시험 6, 7) `[측정]`, 시드 고정: 200 실행에서 요청 9 609(소켓 재설치 뒤 135), 답 6 852(거절 253), WRITE 성공 52 239와 실패
  2 291, 확정 50 076(소켓에서 잃음 143), 짝 죽음 4 093, 맡은 rank 죽음 2 016, 배치 바뀜 7 933, 불변식 검사 800 000에서 위반 0, 실패가 멈춘 뒤
  확정이 없는 실행 0. 소켓 규칙을 뺀 대조 모델은 36 757 상태에서 불변식을 깸(규칙이 시험됨). TCP 기반(9.6): v1 규칙은 120 실행 중 116에서
  3번 이상 연속 거절(최대 19), 이 갈래 규칙은 0(최대 0), 실패 2 838 뒤 전체 올리기 3 624.
- 시험하지 않은 것 `[미확인]`: 실제 HCA 위의 호스트 QP, MR, WRITE, 비동기 이벤트 경로, hold 중 앞 MR 미루기와 declined rank 놓기(인터페이스
  밖 16, 17의 상태 부분; 판단 함수 `gdakiStoreDropReq`, `gdakiStoreMrFits`만 unit에 있음)는 빌드만 됐다. 클러스터 시험은 통합 뒤 test 갈래가 한다.
- 앞 빌드(`mi_store`, `mi_store_pre`, `mi_store_v2`, `mi_store_v3`과 같은 이름의 `mip_*`)는 고치기 전 상태다. 쓰지 않는다.

## 독립 리뷰

1. **첫 리뷰**(2026-10-13, 같은 모델의 다른 에이전트, 읽기만, 대상은 그때의 작업 트리). 목록 원문은 그것을 받은 에이전트가 사용 한도로
   끊기며 남지 않았다 `[미확인]`. 코드와 이 파일에 번호로 남은 것:
   - 1: 호스트 QP와 CQ의 qp_context, cq_context가 비어 net_ib 비동기 이벤트 스레드가 치명 이벤트 때 널 역참조함. 고침(인터페이스 밖 10).
     확인 `[소스]`: `ncclIbAsyncThreadMain`(net_ib/common.cc 166–)이 `ncclIbQpFatalError`, `ncclIbCqFatalError`(common.h 684–692)로 두 칸을
     `struct ncclIbStats*`로 쓰고, 스레드는 장치 context마다 하나(init.cc 602), GIN의 `cComm->ib.context`가 그 context다(gin.cc 303).
   - 2: 다시 놓인 helper 소켓에 묶여 읽히지 않은 CKPT_STABLE 뒤 올리는 쪽만 확정 자리를 옮겨 다음 WRITE가 짝의 실제 확정 자리를 덮음. 고침
     (인터페이스 밖 12; unit 시험 6의 대조 모델).
   - 그 뒤 함께 고친 것(리뷰의 몇 번이었는지 `[미확인]`): 모든 새 줄 끝의 ` mono_ms=`, 멈춘 뒤 상태 재생성 막기(14), 창이 없을 때 250 ms(13),
     arm 기다림 한도(6), RESTORED 한 번 규칙(11).
2. **다시 리뷰**(2026-10-15, 같은 모델의 다른 에이전트, 읽기만, 대상은 이 고침 직전 작업 트리). 높음 0, 중간 1, 낮음 4:
   - R1(중간): ward가 CKPT_STABLE을 보내고 곧 죽어 그 기록이 hold가 열린 뒤 읽히면, 활성화가 넘긴 앞 MR을 저장소 스레드가 풀어 예비 프로세스의
     READ가 실패할 수 있음. 고침(16).
   - R2(낮음): 짝 쪽 저장소 메모리에 상한이 없음. 고침(15).
   - R3(낮음): declined rank의 저장소가 teardown까지 남고, 붙잡히거나 declined된 rank가 남긴 STORE_REQ도 serve함. 고침(17).
   - R4(낮음, `[추론]`): 이 갈래만으로는 mirror 켬 복원이 예비 프로세스를 깨운 뒤 실패함. 고치지 않고 통합 순서로 적음(위 "메인 세션에 알릴 것").
   - R5(낮음): 실패한 destroy, dereg, ERR 이동을 무시해 해제된 메모리를 가리킬 수 있음. 고침(18).
   - 리뷰어가 맞다고 본 것: WRITE 중 ward나 짝의 죽음(짝은 MR을 바꾸기 전에 옛 QP부터 없앰), 앞 MR 불변식, arm 손잡기와 한도(CONFIRMING 30 s >
     WRITE 0.5 s + 걷기 0.2 s), 쓰는 동안 upQp 교체 막기, `gdakiStoreFree` 순서, 고정 버퍼와 원격 자리의 경계, 잠금 순서, TCP 기반 규칙, 리뷰 1과
     2의 고침, 낡은 답과 pending 처리.
