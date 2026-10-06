# gpu-initiated: GPU가 직접 내는 RDMA의 장애 대응

GPU 스레드가 직접 RDMA 요청을 내는 스택(NCCL GIN, NVSHMEM IBGDA)에 장애를 넣고, 오류가 어느 층에서
사라지는지 쟀다. 그 위에 장치 쪽 분류와 복구를 붙였고, 앱이 오류를 모르게 복구하는 1단계까지 만들었다.
CPU verbs 실험(`../`)이 기준선이다.

## 무엇을 쟀나

- **스택 3개.** NCCL 2.32.3 GIN의 proxy backend와 GDAKI backend, NVSHMEM IBGDA(devel 7bb2e99, 공식 3.8.0).
- **장애 4가지.** F1 로컬 QP 오류, F2 원격 접근 오류, F3 상대 QP 오류(상대는 살아 있음), F4 상대 SIGKILL.
- **층마다 본 것.** 누가 오류를 알아채는지, 오류 코드가 어디에 남는지, 장치 wait가 성공, 오류, hang 중 무엇으로 끝나는지.
  데이터가 맞는지, 종료가 돌아오는지도 봤다.
- **조건.** 2026-09-23–25(공식 3.8.0은 10-01), rain(시작 쪽)과 sunny(대상), ConnectX-6, RoCE v2, IB 타임아웃 14.
  - 09-24 13:53부터는 GPU가 doorbell을 직접 울리는 설정을 상시로 썼다. 그 전에는 CPU 스레드가 대신 울렸다.
  - 핵심 셀은 09-25에 N=30으로 다시 쟀다(682 trial).

## 결론

- **stock 스택에서는 위층으로 갈수록 오류 정보가 줄어든다.**
  - GIN proxy는 CPU 스레드가 CQE를 읽는다. F1, F2는 장애 뒤 3–11 ms에 호스트가 오류를 받고, 오류 코드 전체는 로그에 남는다.
  - GDAKI는 장치가 오류 종류를 버린다(소스 기준). 호스트는 10 s 주기 검사에서 "QP in ERR"만 본다(장애 뒤 8–10 s).
  - NVSHMEM GPU handler는 CQE에서는 장애 없음을 포함해 4묶음으로 갈리지만, API에서는 모두 1묶음이다.
- **실패를 성공으로 보고하는 경로가 있다.**
  - stock GDAKI의 blocking wait는 실패한 쓰기를 완료로 센다(9/9, N=30 대조 10/10).
  - NVSHMEM GPU handler도 실패한 put 뒤에 정상 반환한다(6/6). 오류 뒤 NVSHMEM finalize는 hang이다.
- **NVSHMEM CPU proxy가 오류 CQE를 못 받는 것은 doorbell record 버그다.**
  - proxy가 send 위치를 doorbell record의 다른 칸에 적는다. 그래서 QP가 ERR로 갈 때 NIC는 보낸 것이 없다고 보고 완료를 쓰지 않는다.
  - CPU verbs 시험: 그 칸이 비어 있으면 오류 CQE 0/35, 채우면 21/21.
  - NVSHMEM 안에서: stock CPU proxy 0/12, GPU handler 16/16, 칸을 고친 CPU proxy 16/16.
- **분류는 읽힌 CQE가 아니라 원인 CQE를 봐야 한다.**
  - NIC는 원인 CQE 약 60 µs 뒤부터 flush(5/0xf9)를 쓴다. GDAKI ring CQ에서 wait가 읽은 CQE는 매번 이 flush였다(33/33).
  - GDAKI 장치 쪽 분류기: N=30에서 240/240 정확, 조용한 성공 0/180. 장치가 감지하고 94 µs 뒤, 호스트에 오류를 알리는 공유 메모리 칸에 닿는다.
    장애가 없을 때 비용은 4 KiB에서 0.1 µs 이하(약 1%)다.
  - NVSHMEM FT: N=30에서 120/120 정확. collapsed CQ(1칸)는 원인 CQE가 올 때 기다리는 스레드가 없으면 원인을 잃는다.
  - FT v2의 ring CQ는 post와 wait 사이에 계산이 끼어도 90/90을 지킨다(collapsed는 0/90).
  - FT v2의 경계 검사는 MR 안에서 범위를 넘는 쓰기를 guard 영역을 둘 때만 잡는다(0/30에서 30/30).
- **일시 장애(F1, F3)는 잃거나 겹치는 것 없이 복구된다. F2와 F4는 거절된다.**
  - 두 스택 모두 연산 하나가 in flight일 때 쟀다. 앱이 오류를 받은 뒤 다시 보내고, 데이터와 신호 값이 모두 정확했다.
  - GDAKI: N=30 묶음 100/100 복구. kernel 반환부터 복구까지 셀별 중앙값 8.3–8.9 ms. 거절 60/60.
  - NVSHMEM FT: 80/80 복구. kernel 반환부터 복구까지 중앙값은 F1 3.16 ms, F3 3.25 ms다.
    장애를 5번 낸 실행에서는 F1 2.82 ms, F3 4.77 ms다. 거절 20/20.
  - FT v2.2는 완료가 실패한 fetch의 값에 오염 표시를 한다.
  - F3와 F4는 CQE 코드가 같다(12/0x81). 상대 소켓의 FIN을 봐야 갈린다.
- **GIN 투명 복구 1단계에서는 앱이 오류를 보지 않는다.**
  - GDAKI F1, F3 95/95가 오류 없이 끝났고 데이터도 정확했다. 연산 하나가 in flight이고 poster가 하나인 경우다.
  - 기능을 켜면 장애가 없어도 4 KiB 지연(p50)이 +60%다(후속 빌드, 10.24에서 16.42 µs). 1단계 첫 빌드는 +66%였다.

## 결과

| 변형 | 오류 정보가 남는 곳 | 앱이 받는 것 | 종료 |
|---|---|---|---|
| GIN proxy (stock) | CPU 스레드 로그, 오류 코드 전체 | 오류 1종(timeout) 또는 hang(blocking) | blocking F1–F3에서 양쪽 rank hang |
| GIN GDAKI (stock) | 호스트는 10 s 주기로 "QP in ERR"만 | blocking에서 실패를 완료로 보고(9/9) | blocking F1–F3에서 대상 rank hang |
| GDAKI + 장치 쪽 분류기 | 로그와 호스트 알림 칸, 오류 코드 전체 | 오류 1종, 조용한 성공 0/180 | blocking F1–F3에서 대상 rank hang |
| GDAKI + 복구 | 위와 같음, 상대 생존 여부 추가 | 오류 뒤 원인 조회, F1, F3 복구, F2, F4 거절 | 양쪽 반환 |
| GDAKI 투명 복구 1단계 | 로그에만 | F1, F3는 오류 없이 성공(95/95) | 대상 rank가 F2에서 hang |
| NVSHMEM CPU proxy (stock) | 없음(오류 CQE가 안 생김) | 무한 대기 | finalize hang |
| NVSHMEM GPU handler 또는 버그 수정 | CQE에 잠깐 남았다가 flush로 덮임 | 실패한 put도 정상 반환(6/6) | finalize hang |
| NVSHMEM FT v1, v2.2 | 호스트 알림 칸, 오류 코드 전체 | 상태 조회로 오류, F1, F3 복구 | FT abort를 불러야 반환 |

IB 타임아웃 14에서 F3, F4의 RETRY_EXC CQE는 장애 뒤 3.5–3.8 s에 생긴다.
기본값 20에서는 GIN proxy가 57.1–58.4 s 걸렸다(4회, 장애 시각은 추정).
N=30 재측정 682 trial은 분류, 복구, 거절 셀이 모두 100%였다. Wilson 95% 하한은 N=30 셀 88.6%, N=10 셀 72.2%다.

## 한계와 주의

- **"GDAKI 종료는 깨끗하다"는 시작 rank만 맞다.** blocking F1–F3에서 대상 rank의 abort는 돌아오지 않았다.
  - stock 9/9, 장치 쪽 분류기 N=30 90/90, stock N=30 10/10이다.
  - GIN proxy의 abort hang은 F1–F3에만 있고, 양쪽 rank 모두다.
- **대상 rank는 오류를 받지 못한다.** stock GIN의 F1–F3에서 대상 rank에 비동기 오류가 한 번도 없었다(backend마다 18/18).
  자기 QP가 ERR인 F3도 그렇다. 원인은 아직 모른다.
- **API 값은 한 종류다.** 장치 쪽 분류기를 붙여도 API는 ncclRemoteError만 준다. 오류 코드는 로그와 호스트 알림 칸에만 있다.
  "API까지 190 µs"는 알림 칸에 닿은 때가 아니라 장치 감지부터 잰 값이다.
- **NVSHMEM FT의 종료 반환은 조건부다.** 앱의 거절 경로가 FT abort를 불러야 한다.
  - 그것 없이 v2.2로 address flap을 돌리면 6/6 hang이었다(커밋 전 결과).
  - quiet는 여전히 결과를 돌려주지 않고, 오류는 상태 조회로만 보인다. barrier와 collective는 소스만 봤다.
- **doorbell record 버그의 범위.** 3.5.x–3.8.0으로 보지만 잰 것은 devel 7bb2e99와 3.8.0(F4만)이다. 나머지 버전은 소스로 판단했다.
  고치면 CQE는 생기지만, API에서는 hang이 조용한 성공으로 바뀐다.
- **v2.2 숫자의 출처.** v2.1에서 조용히 돌아온 옛 값 510,028개는 40회 중 값을 돌려준 37회에서 나왔다.
  "상주 스레드 없이 90/90"은 v2 빌드에서 쟀다. F3, F4 분류와 복구는 v2.2에서 다시 돌리지 않았다.
- **RESULTS.md 표의 빈칸과 값.** "-"로 된 NVSHMEM GPU handler의 F4와 종료는 실제로 쟀다(F4 12/0x81, finalize hang 16/16).
  - GPU handler 감지 1.8 ms, 9 ms는 n=3 창의 값이다. 다른 측정은 2.0–2.3 ms, 10.3–10.7 ms다(둘 다 post부터).
- **표본과 경합.** stock proxy와 GDAKI의 F2–F4는 셀당 n=3이다.
  - proxy F4의 10/0x88은 경합 결과라서 12/0x81도 나올 수 있다(`../teardown_order/`).
  - GIN에서 MR 안 범위 초과 쓰기가 조용히 사라진다는 주장은 원시 데이터가 남아 있지 않다.
- **N=30 일부는 펌웨어 명령 슬롯이 샌 상태에서 돌았다.** 09-25 06:45 이후 hold다. N=30 문서에는 이 언급이 없다.
- **돌리지 않은 것.** link down(공유 링크라서), DeepEP(SM90이 필요한데 rain은 sm_75), 3 rank 이상, Hopper.
- **진행 중.** GIN 투명 복구 2단계와 NVSHMEM 투명 복구는 draft PR로 두었다. 위 결론에는 넣지 않았다.

## 파일

| 파일 | 내용 |
|---|---|
| [RESULTS.md](RESULTS.md) | 스택별 결과를 합친 표와 결론 |
| [DESIGN.md](DESIGN.md) | 측정 질문 4개와 장애 목록 |
| [N30_20260925.md](N30_20260925.md) | 핵심 셀 N=30 재측정 |
| [TRANSPARENT_RECOVERY_DESIGN.md](TRANSPARENT_RECOVERY_DESIGN.md) | 앱이 모르게 복구하는 설계 |
| `cqe_seq/` | 장애 뒤 NIC가 쓰는 CQE 순서(CPU verbs) |
| `gin/` | NCCL GIN proxy와 GDAKI의 stock 동작 |
| `gin_q4/` | GDAKI 장치 쪽 분류기, collapsed CQ와 ring CQ 비교 |
| `gin_recovery/` | GDAKI 복구와 GIN 투명 복구 1단계 |
| `gpu_doorbell/` | GPU가 doorbell을 직접 울린 실행 |
| `nvshmem/` | NVSHMEM IBGDA의 stock 동작 |
| `nvshmem_rootcause/` | doorbell record 버그의 원인과 범위, 공식 3.8.0 확인 |
| `nvshmem_ft/` | NVSHMEM 분류와 복구, v1부터 v2.2까지 |
| `transparent_probe/` | 투명 복구의 하드웨어 전제 확인(응답 쪽 PSN) |
| `propagation/` | 층별 오류 전파 분석과 사전 등록한 예측 |
| 각 폴더의 `results/` | 결과 표. 원시 로그는 Release `data-20261006` |
