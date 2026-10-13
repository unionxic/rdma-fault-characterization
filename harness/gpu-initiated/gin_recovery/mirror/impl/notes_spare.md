# 갈래 기록: exp/gin-mirror-spare (복원 길, 끝점 갱신)

[PARALLEL.md](PARALLEL.md)의 `exp/gin-mirror-spare` 행이다. 통합 때 메인 세션이 아래 "12절 행"을 [../EXPERIMENT.md](../EXPERIMENT.md) 12절로
옮기고 이 파일을 지운다. 이 갈래는 `EXPERIMENT.md`를 고치지 않았다.

- 바탕: 빌드 트리 `agent_mi_spare/`(세션 스크래치), `build_mi.sh setup`이 i5(rs_layer.diff `f005bb67`, libnccl `4811f28f`,
  `be91b270`)를 확인하고 복사함. 갈래 diff는 [mi_layer_spare.diff](mi_layer_spare.diff)(인터페이스 붙이기 포함, 아래 md5).
- 줄 번호: 따로 적지 않으면 그 트리의 `gin_host_gdaki.cc` 줄이 아니라 영역과 함수 이름으로 적는다(통합 뒤 줄이 바뀜).

## 12절 행

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-13 | spare 갈래 구현(복원 길, 끝점 갱신). 충돌 검토: 맡은 묶음의 인터페이스와 rs_layer.diff의 해당 줄을 대조, 설계 충돌 없음, 인터페이스가 비워 둔 입구(아래 "인터페이스 틈" 1–8, 리뷰 뒤 9)는 자리표시와 메모로 두고 구현. 붙인 것: (1) 생존 rank의 hold 시작에 mirror 읽기(d로 가는 mirror QP의 X, M, 쓰임; 짝으로 가는 길의 M_mir와 쓰임; d 칸의 segment, 커서, 깨짐, 유효를 NIC으로; 닫힌 segment는 host 기록) → HOLDING의 쓰지 않던 칸(pad 깃발 `GDAKI_HOLD_F_MIRROR`), 짝 자신은 제 몫을 그 자리에서 보관; (2) 복원 라운드의 X 확인 뒤 mirror QP만 다시 봄, 움직이면 그 lane 깨짐(`gdakiMiAbsorbQp`), fallback 없음; (3) 짝의 drain(새 영역, helper 걸음마다 조각): 모든 HOLDING 몫이 있고 쓸 만한지(`gdakiMiHoldingVerdict`), K 뒤 바이트가 있는 보내는 rank마다 누적 실행 수 ≥ M_mir(무효 셈이면 거절), 자기 lane은 자기 루프 응답 QP의 MSN, 한도 `NCCL_GIN_RESTORE_DRAIN_MS`와 `_DRAIN_QUERIES`, 그다음 루프백 쌍의 8바이트 READ 울타리, 줄 "drain for rank"; (4) 활성화 판 2: 짝은 기록 + 덩어리(주소와 화신 표, 저장소 자리, pool, K 뒤 extent, FETCH QP 끝점), ACCEPTED 뒤 FETCH 끝점, RTS, READY, 연결과 QP를 기다림 스레드에 넘김; 예비 프로세스는 덩어리를 읽고 검사(모자라거나 깨졌으면 REFUSED), ACCEPTED 뒤 FETCH QP, READY를 받은 뒤에만 READ(저장소 자리, extent 차례), DONE, 이미지를 window에 씀, 첫 REJOIN 전; FETCH 버퍼는 driver 시작에서 등록; (5) 끝점 갱신: 표의 주소(화신 > 0은 표, 0은 기록 유지와 WARN), REJOIN의 QPN 비교(mirror QP 뺌, 자기 화신 0일 때만), TOKEN QPN(화신 > 0과 mirror QP는 TOKEN에서, 0은 기록과 견줌), mirror QP의 rq.exch는 사용자 문맥 0의 끝점 + TOKEN QPN; (6) rkey 목록에 pool(종류 4), 생존 rank의 `gdakiRsSwapRkeys`가 pool 항목으로 맡은 rank들의 칸에 `gdakiMiPoolRekey`; (7) 내보내기 판 2(80 B 항목, 단계와 segment, 원본 바이트 없음, 끝에 자기 rkey 목록), `gdakiHoldTransferStep`에서 mirror 켬이면 부름, 줄 "export to rank"; (8) TCP FETCH 자리(`gdakiCkptSpareFetch`)에서 mirror 켬이면 RDMA FETCH의 머리와 덩어리를 넘겨받음. mirror 끔이면 v1 길 그대로 | 빌드 트리 `agent_mi_spare/`, 이 파일, [mi_layer_spare.diff](mi_layer_spare.diff), [mi_unit_spare.cc](mi_unit_spare.cc) |
| 2026-10-13 | 빌드와 시험(이 갈래가 돌림, 클러스터 없음): 마지막 소스로 `build_mi.sh mi`(`mi_spare_c2`), `mip`(`mip_spare_c2`), 경고 0; `api` 통과; `unit` `mi_unit_spare` 185 checks, 0 failed(ASan, UBSan). 라이브러리는 "빌드됨"이고 GPU와 RDMA에서는 돌리지 않음. 다른 갈래 진입 함수가 자리표시(`gdakiMiOn` false)라 빌드된 라이브러리에서 mirror 길은 닿지 않음 | 아래 "빌드와 시험", `agent_mi_spare/out/build_info.txt` |
| 2026-10-13 | 독립 코드 리뷰(같은 모델의 다른 에이전트, 읽기만, 대상: 리뷰 전 소스): 찾은 것 14와 통합 확인 다섯. 고친 것 10, 기록만 한 것 4(아래 "독립 리뷰"). 고친 뒤 다시 빌드하고 단위 시험을 늘림(160 → 185 checks) | 이 파일 |

## 빌드와 시험

모두 이 worktree와 `agent_mi_spare/`에서, 2026-10-13. GPU, RDMA, 클러스터 실행 없음.

| 단계 | 결과 | 근거 |
|---|---|---|
| `setup` | i5 확인(rs_layer.diff `f005bb67`, libnccl `4811f28f`, `be91b270`), 복사, i5 커밋 `9af58c7` | 출력 한 줄 |
| `paste` | 블록 다섯과 멤버 한 줄, hold 공유 글은 v1 | 첫 커밋 `140e51fe`(인터페이스 커밋, mi_layer_spare.diff `a1beff20`) |
| `mi` | `mi_spare_c2` libnccl `d53d0f51`, 경고 0 | `agent_mi_spare/build_mi_c2.log` |
| `mip` | `mip_spare_c2` libnccl `3df3b40c`, 경고 0 | `agent_mi_spare/build_mip_c2.log` |
| `api` | 붙인 블록 다섯이 헤더와 바이트 단위로 같음, 헤더 여섯 함께 컴파일 | 출력 |
| `unit` | `mi_unit_spare` 185 checks, 0 failed(ASan, UBSan) | 출력 한 줄 |
| `diff` | `mi_layer_spare.diff` `3b4b6bb8`(작업 트리 diff md5와 같음) | `build_info.txt` |

- 앞선 빌드(`mi_spare_p0` 붙이기만, `mi_spare_c1`, `mip_spare_p0`)는 중간 결과다. `mip_spare_p0`는 빌드 중에 소스를 한 줄 고쳐 어느 소스인지
  분명하지 않다. 쓰지 않는다.
- 첫 전체 빌드(`p0` 둘)에는 경고 하나가 있다: 바뀌지 않은 `scheduler/symmetric_sched.cc:327`(`-Wextra`). 공통 헤더가 바뀌어 다시 컴파일됐을
  뿐이고, gin-restore의 첫 전체 빌드 `agent_rs_int/build_rs_i1.log`에도 같은 줄이 있다 `[측정: 두 로그]`. 이 갈래 파일의 경고는 0이다.
- 시험한 것은 순수 영역뿐이다. driver, 활성화 연결, FETCH, drain, 내보내기의 실제 흐름은 통합 뒤 pilot이 본다.

## 인터페이스 밖에서 정함

1. 활성화 덩어리의 받는 쪽 순수 도우미(`gdakiMiActHdrSane`, 인코드와 디코드, `GDAKI_MI_ACT_MAX_ADDR` 4096), 주소 규칙
   (`gdakiMiAddrRule`: 화신 0에서 표 주소가 0이어도 기록 유지와 WARN, 화신 > 0에서 주소가 0이면 활성화 REFUSED), 활성화 연결 차례의 상태
   기계(`gdakiMiActStep`, `gdakiMiRejoinAllowed`), FETCH 버퍼 배치(`gdakiMiFetchLayout`: `gdakiMiActCheck`의 합과 같은 식).
2. REFUSED 이유 번호 8–11(덩어리가 있는데 mirror 끔, 없는데 mirror 켬, 상태 없음, 주소 표). 1–7은 `gdakiMiActCheck`의 것.
3. `gdakiMiSendActivate`의 돌려주는 값 `GDAKI_MI_ACT_FETCH_FAILED`(-2): ACCEPTED 뒤 FETCH 끝점, 잇기, READY 중 하나가 실패. 짝은 곧바로 fallback
   (인터페이스는 "answer kind, or -1"만 적음; -1은 v1처럼 "답 없음" 재시도로 가서 이미 활성화된 예비 프로세스에 다시 ACTIVATE를 보냄).
4. 짝의 FETCH QP는 READY 뒤 이 갈래의 기다림 스레드가 쥔다(DONE, FIN, hold의 남은 시간 중 먼저). 인터페이스의 "data (serve) thread"로 넘길
   입구가 없어서다(인터페이스 틈 5). 한 번에 하나, 다음 활성화나 정리 때 join.
5. FETCH 버퍼는 초기화 재생 안이 아니라 예비 프로세스 driver의 시작(활성화 소켓을 열기 전)에서 등록한다. 이 갈래에는 초기화 재생 안의 자리가
   없고, 활성화 전이라 등록 시간이 복원 시간에 들지 않는다. 등록 실패면 용량 0이라 모든 판 2 활성화가 REFUSED(검사 7).
6. 자기 루프 lane의 drain은 10 ms 걸음의 누적 없이 24비트로 판정한다: 요청 쪽 msgs는 0에서, 응답 쪽 MSN은 잇던 때의 기준(`gdakiMiSelfBase`,
   인터페이스 틈 9)에서 세고, 실행 수 − msgs가 (−SQ 깊이, 2^23) 안이라는 가정(QP 깊이 128 `[소스: NCCL_GIN_GDAKI_QP_DEPTH]`, drain까지 그 짝의
   다른 맡은 rank로 새로 낸 WRITE는 2^23보다 훨씬 적음 `[추론]`). 설계(9.4절 2번)의 "helper가 10 ms마다 누적"을 대신한다. 이 갈래에는 helper
   걸음마다 부를 자리가 없다.
7. 생존 rank의 hold 시작 읽기는 `gdakiMiReadMsgsMirror`(dev) 대신 측 표 전체 읽기(`gdakiRsReadSide`, dev의 기존 함수)로 mirror QP의
   msgs와 miUse를 읽고, d 칸은 NIC 복사 경로로 직접 읽는다(9.4절 1번 "장치 값"). X만 `gdakiMiExecReadMirror`(dev).
8. HOLDING 몫의 열린 segment 깨짐 = 칸의 누적 깨짐 − host 기록의 `openBroken`(그 segment를 연 때의 누적 값으로 읽음), 닫힌 segment의
   `broken[]`은 "열려 있던 동안의 깨짐"으로 읽는다(인터페이스 틈 6의 해석). 칸의 segment 번호가 host 기록의 열린 번호와 다르면 몫을 쓸 수 없음
   (version 0: 짝이 거절, d는 fallback).
9. 읽기가 실패하면 hold를 끝내지 않고 version 0 몫을 보낸다. 짝이 거절해 d의 복원만 꺼진다(mirror는 보조 길).
10. 예비 프로세스에서 mirror QP의 `rq.exch`는 그 생존 rank의 사용자 문맥 0 QP의 끝점에 TOKEN의 QPN을 넣어 만든다(같은 HCA와 포트, MIRROR_SETUP의
    규칙). mirror 켬에서 마지막 QP가 mirror 문맥이 아니면 그 생존 rank와의 복원을 포기한다.
11. 화신 > 0인 생존 rank의 사용자 QP는 TOKEN QPN을 `rq.exch.qpn`에 써 둔다(뒤의 라운드도 읽음). 표의 화신과 REJOIN_ACK의 화신이 다르면
    REJOIN_ACK의 것을 쓴다(생존 rank 자신의 말).
12. STORE_REQ(RESTORED 뒤): driver는 따로 부르지 않는다. RESTORED를 보낸 바로 뒤 helper가 뜨고, store 갈래의 `gdakiStoreStep`이 helper 걸음마다
    돌므로 차례 "RESTORED → STORE_REQ"가 지켜진다. 헬퍼 전용 함수를 application 스레드에서 미리 부르지 않으려는 선택.
13. 생존 rank 쪽 rkey 쓰기는 인터페이스대로 dev의 `gdakiMiImportPrepare`가 한다. 이 갈래는 화신 0 WARN 규칙을 순수 함수
    `gdakiMiRkeyRule`, `gdakiMiRkeyMerge`(pool 포함)로 내고 시험한다. 가져오기가 이 함수를 쓸지는 통합 때 정할 일.
14. 내보내기의 64비트 위치는 항목의 낮은 32비트와 절단점에서 되살린다(`gdakiMiPos64`; 범위가 2^32 항목보다 훨씬 작음). 단계 쌍이 없으면 마지막
    단계 + 1, 마지막 단계도 없으면(`GDAKI_RS_STEP_UNKNOWN`) 거절.
15. 활성화 차례의 한도 밖 처리: drain 거절은 그 차례 동안 끝(같은 이유를 돌려줌); drain의 QUERY_QP 실패는 한도 안에서 다시 묻고, 무효 셈과
    자기 루프의 RTS 아님은 곧바로 거절; 덩어리를 끝까지 읽지 않은 REFUSED는 반 닫은 뒤 남은 것을 읽고 close; 크기 한도
    `gdakiMiActFits`(REFUSED 7); 짝의 FETCH QP는 fallback 때 없앰(LATER 재시도에는 같은 QP와 끝점).
16. pool rekey(`gdakiRsSwapRkeys`)는 목록에 pool 항목이 없어도 rkey 0(모름)으로 부르고, 자기 rank의 칸은 건너뛴다. rekey 실패는 라운드
    실패(되살린 rank의 거절)로 둔다(리뷰 10).

## 인터페이스 틈 (메인 세션이 헤더를 고칠지 정할 것)

1. **HOLDING 몫의 받기.** 짝이 HOLDING의 칸을 받을 자리가 인터페이스에 없다. host 갈래 함수 `gdakiHoldOnMsg`의 HOLDING 경우(rs_layer.diff
   7120–7121)에 한 줄(`gdakiMiHoldingTake(r, p, from, m)`)을 넣었다. 표에 없는 자리라 통합 때 승인이 필요하다.
2. **자기 루프 QP.** 자기 루프의 응답 QP를 얻는 입구가 없다. host의 mirror 문맥이 GDAKI 문맥의 문맥 하나 더라고 보고
   `gqps[nContexts × nranks + miCtx]`로 셈했다(`gdakiMiSelfResponder`). 요청 쪽 msgs는 측 표 항목 `miCtx × nranks + 자기 rank`, 그 miUse가
   1이어야 길이 쓰인다고 봤다.
3. **pool 정보.** 자기 pool의 rkey, L, S를 주는 입구가 없다(덩어리, rkey 목록 종류 4, drain 울타리가 씀). 자리표시
   `gdakiMiPoolInfoOf`(host 갈래 몫으로 제안)를 두었다.
4. **FETCH 결과의 넘김.** `gdakiMiFetched`를 dev의 가져오기(rs tree 11152–11157 자리)로 넘기는 입구가 없다. 접근 함수 `gdakiMiSpareFetched(r)`를
   두었다(성공한 FETCH 전에는 null).
5. **짝의 FETCH QP 넘김.** 인터페이스는 READY 뒤 연결을 checkpoint 기계의 serve 스레드가 쥔다고 적었으나 넘길 입구가 없다. 이 갈래의 기다림
   스레드로 했다(위 4).
6. **store 길의 예비 프로세스 등록.** 활성화에는 맡긴 rank의 예비 프로세스 주소, PID, 시작 시각이 필요하다(`gdakiHoldSpareOf`가
   `ck->store[d]`에서 읽음). store 길에서는 이 셋이 저장소 자리의 머리에만 있고 짝은 자리를 읽지 않으며, `gdakiStoreActInfo`에도 없다. 그대로면
   mirror 켬에서 짝은 "no spare process is registered"로 fallback한다. store 갈래가 `ck->store`를 채우거나 `gdakiStoreActInfo`에 셋을 더해야
   한다(이 갈래 코드는 지금 `gdakiHoldSpareOf`를 그대로 부름).
7. **segment 보기의 뜻.** `gdakiMiSegView`의 `broken`, `openBroken`, `openCursor`가 누적 값인지 증분인지 헤더에 없다(위 8의 해석).
   `gdakiCkptStepPairs`가 단계가 하나도 없을 때 `lastStep`을 무엇으로 주는지도 없다(`GDAKI_RS_STEP_UNKNOWN`으로 읽음).
8. **gdakiMiReadMsgsMirror와 자기 rank.** 쓰지 않았다(위 7). 통합 때 dev 함수로 바꾸려면 자기 rank(자기 루프)에서의 뜻이 정해져야 한다.
9. **자기 루프의 MSN 기준.** 자기 루프 응답 QP를 이을 때의 rmsn을 주는 입구가 없다(gin-restore는 어디서도 rmsn0 = 0을 가정하지 않음). 자리표시
   `gdakiMiSelfBase`(0을 돌려줌, host 갈래 몫으로 제안)를 두었다. 기준이 0이 아닌데 0으로 읽으면 drain이 일찍 끝날 수 있다(리뷰 3).

## 줄 형식(test 갈래가 읽는 것)

모두 WARN(연구 빌드와 운영 빌드 둘 다 보임), `GIN/MI: rank %d: `로 시작하고 ` mono_ms=%.3f`로 끝난다.

```
GIN/MI: rank %d: drain for rank %d: senders=%d queries=%d drain_us=%.0f mono_ms=%.3f
GIN/MI: rank %d: fetch for checkpoint %lu from buddy rank %d: image_bytes=%lu segment_bytes=%lu extents=%zu fetch_us=%.0f h2d_us=%.0f mono_ms=%.3f
GIN/MI: rank %d: export to rank %d: entries=%zu mirror_entries=%lu mirror_bytes=%lu source_bytes=0 first_step=%lu last_step=%lu mono_ms=%.3f
```

- drain: 짝이 찍는다. senders = K 뒤 바이트가 있어 기다린 보내는 rank 수(자기 포함), queries = QUERY_QP 수, drain_us = 첫 drain 걸음부터 울타리
  READ 끝까지.
- fetch: 예비 프로세스가 찍는다. `h2d_us`는 인터페이스 키 밖에 더한 것(이미지를 window에 쓰는 시간). fetch_us = 첫 READ부터 마지막 READ 완료까지.
- export: 생존 rank가 찍는다. first_step, last_step = 항목들의 단계 최소, 최대(항목 없으면 0).

그 밖의 줄(키 아님): WARN `GIN/MI: rank %d: export to rank %d refused: %s (position %lu)`, `... restore round with rank %d: %s; the lanes it
serves are broken`, `... rank %d's spare accepted its activation but the FETCH handshake failed (%s)`, `... the spare's FETCH of checkpoint
%llu failed: %s`, `... the activation table's address of rank %d (incarnation 0) differs from the recorded one; the recorded one is kept`,
`... rank %d's TOKEN QP %d: QPN ...`; 예비 프로세스의 활성화 거절은 v1 줄 `GIN/RS: spare rank %d: activation refused (%s); waiting`에 덩어리
이유를 넣는다. 연구 빌드의 NOTE(운영 빌드는 INFO): hold 시작 읽기, READY, 기다림 스레드의 끝, FETCH 버퍼 등록, 표 주소 사용.

## 독립 리뷰

같은 모델의 다른 에이전트, 읽기만(리뷰 전 소스: `spare_only.diff`, 전체 파일, 단위 시험, rs_layer.diff). mirror 끔 동일성: 바뀐 v1
결정, 기록, 시한, 줄이 없음(새 길은 모두 `gdakiMiOn` 뒤). 하나만 다름: mirror 끈 예비 프로세스가 판 2 기록에 REFUSED(8)로 답함(v1은 PID를
봄). mirror 비트가 rank마다 다른 잘못 설정된 작업(조건 34)에서만 생기므로 그대로 둠. 프로토콜과 형식(기록 + 덩어리 500 ms, 답 셋, 끝점
1000 ms, READY는 handshake 한도, READY 뒤에만 READ, DONE, LATER 재시도에 같은 끝점, mirror QP는 마지막이고 TOKEN에서, 화신별 비교, 주소 표,
내보내기 차례와 크기와 거절): 더 찾은 것 없음. fd 누수, 덜 읽은 값, 초기화 안 된 바이트의 전송: 없음.

| # | 찾은 것 | 처리 |
|---|---|---|
| 1 | helper가 펌웨어 명령 안에서 orphan이 되면 통신기 정리(`gdakiRsSpareForget`, 두째 자리)가 이 갈래 상태를 지워 helper가 지운 메모리를 씀 | 고침: orphan이고 helper가 끝나지 않았으면 남기고 `gdakiRecFree`가 지움 |
| 2 | 판 2 활성화가 helper를 약 2 s 막아 감시 스레드의 heartbeat 규칙이 거짓 오류를 낼 수 있음 | 고침: mirror 길을 `gdakiTsBusy`로 감쌈. 걸음 나누기는 하지 않음 |
| 3 | 자기 루프 drain이 MSN 기준 0을 확인 없이 가정 | 고침: 기준을 받는 `gdakiMiSelfDrained(mSelf, rmsn, base)`, 입구 `gdakiMiSelfBase`는 자리표시(0), 인터페이스 틈 9 |
| 4 | 복원 라운드에서 mirror 셈이 움직이면 lane만 깨고 셈은 그대로 남아 뒤의 drain이 믿음 | 고침: `gdakiRsExecInvalidate`도 부름 |
| 5 | 울타리 READ가 실패하면 루프백 쌍 전체가 깨져(atomicOk false) 같은 rank의 가져오기까지 막힘; 이 트리의 `gdakiRsAtomicOp`에는 잠금이 없음 | 기록만(열린 항목 1): 메인 세션이 정함. dev의 쌍 잠금은 통합의 조건 |
| 6 | 인터페이스 틈 7(segment 깨짐의 뜻)이 HOLDING 몫과 시험에 박힘 | 기록만(틈 7): 헤더에서 정한 뒤 코드와 시험을 맞춤 |
| 7 | READY 뒤 예비 프로세스의 FETCH 실패를 짝이 알지 못해 생존 rank들이 시한까지 기다림 | 기록만(열린 항목 2): 활성화 뒤 짝의 helper 걸음에서 볼 자리가 host 갈래 쪽 |
| 8 | 검사 안 한 덩어리 수가 FETCH 크기 검사의 합을 넘치게 할 수 있음 | 고침: `gdakiMiActFits`(자리와 lane ≤ 버퍼, 이미지 ≤ 2^40)를 검사 앞에, 시험 추가 |
| 9 | 이른 REFUSED 뒤 읽지 않은 바이트가 남은 채 close하면 RST가 답을 지울 수 있음 | 고침: `gdakiMiCloseAfterAnswer`(반 닫고 남은 것을 읽은 뒤 close) |
| 10 | pool rekey 실패가 되살린 rank를 거절함(불변식 "짝을 거절하지 않음"의 예외) | 그대로 둠, 의도한 예외: 죽은 프로세스의 pool rkey가 남은 칸은 다시 쓰인 mkey에 닿을 수 있음 |
| 11 | drain 거절이 끈적이지 않음(같은 차례의 두째 호출이 범위를 벗어남) | 고침: `drainFailed`와 이유를 남기고 표 크기를 확인 |
| 12 | 질의 실패를 "무효 셈"으로 적음 | 고침: 질의 실패는 한도 안에서 다시 묻고, 무효 셈만 거절 |
| 13 | 실패한 읽기 뒤 초기화 안 된 `an`을 읽음; FETCH QP가 없을 때 -1(재시도); QP가 이미 있으면 덩어리의 끝점이 0 | 고침: memset, `GDAKI_MI_ACT_FETCH_FAILED`, 끝점을 상태에 둠 |
| 14 | FETCH QP가 쓸모를 다한 뒤에도 남음 | 고침: 짝은 fallback 때(`gdakiMiActEnd`), 예비 프로세스는 FETCH 뒤와 실패 때 없앰. 짝의 기다림 스레드는 그대로(DONE, FIN, 시한) |

리뷰가 적은 통합 확인(이 갈래에서 고칠 것 아님): 예비 프로세스에서 `gdakiMiOn`이 참이어야 함(아니면 판 2가 모두 REFUSED이고 FETCH 버퍼가
없음); FETCH 버퍼 MR과 store의 host QP가 같은 PD(`collComm->ib.pd`); pool MR에 REMOTE_READ, relaxed ordering 없음; 생존 rank의 mirror QP
`rq.exch`를 host가 MIRROR_SETUP에서 채움(`gdakiRsSwapEndpoint`와 Commit이 씀); `gdakiMiRkeyMerge`를 부르는 곳이 없음(dev 가져오기가 써야 화신 0의
WARN 규칙이 지켜짐). 단위 시험의 "mirror 끔 = v1" 경우는 순수 도우미만 본다(위 "빌드와 시험").

## 열린 항목 (메인 세션)

1. 울타리 READ의 실패가 루프백 쌍을 끈적하게 깸(리뷰 5). 길: 울타리 READ의 오류는 쌍을 깨지 않게 하거나 따로 된 READ 길. dev의 쌍 잠금이
   통합 조건이다.
2. READY 뒤 FETCH 실패의 알림(리뷰 7). 기다림 스레드가 (d, 화신)별 실패 깃발을 두고, 짝의 helper 걸음(host 갈래의 `gdakiHoldStep`, 활성화 뒤
   `gdakiHoldActivate`는 불리지 않음)이 fallback하는 길을 제안.
3. 인터페이스 틈 1–9(아래 섹션).
