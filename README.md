# RDMA 장애 특성화와 복구

RDMA 통신에서 장애가 났을 때, 그 정보가 NIC에서 application까지 어디서 남고 어디서 사라지는지 측정한다. 남은 정보로 원인을
얼마나 구분할 수 있는지, 언제 application을 고치지 않고 안전하게 복구할 수 있는지도 보인다. 대상은 CPU verbs, NCCL, 그리고 GPU가
직접 통신을 시작하는 GPU-initiated RDMA 스택(NVIDIA NCCL GIN, NVSHMEM IBGDA)이다.

## 요약

- **NVIDIA NVSHMEM 버그를 찾아 보고했다.** NVSHMEM 3.5.x–3.8.0의 CPU 프록시 경로가 NIC에 알리는 doorbell record 주소를 잘못
  계산해, 통신 장애가 나도 오류가 전달되지 않고 application이 멈춘다. 공식 3.8.0에서 확인해
  [NVIDIA/nvshmem#117](https://github.com/NVIDIA/nvshmem/issues/117)로 보고했고, NVIDIA 내부 조치가 완료됐다. 같은 방법으로
  release 빌드가 오류 완료를 버리는 문제([NVIDIA/nvshmem#120](https://github.com/NVIDIA/nvshmem/issues/120))와 NCCL GIN이
  지원하지 않는 설정값을 받아 멈추는 문제([NVIDIA/nccl#2480](https://github.com/NVIDIA/nccl/issues/2480))도 보고했다.
- **장애 전파를 규칙 다섯 가지로 정리했다.** 장애 정보가 NIC에서 application까지 올라가며 어디서 사라지는지 재고, 결과를 보기 전에
  세운 예측으로 검증했다.
- **application을 고치지 않고 라이브러리 안에서 복구했다.** NCCL GIN과 NVSHMEM에서 장애 난 연결만 다시 세워 통신을 이어 가게 했고,
  장애를 감지한 뒤 복구에 걸리는 시간을 11.4 ms에서 3.0 ms로 줄였다. 복구할 수 없으면 application에 오류로 알리고, 죽은 rank를 뺀
  communicator로 이어 간다.
- **실제 application에서 blind test로 검증했다.** 장애 일정을 봉인해 두고, 정답을 모르는 에이전트가 출력만 보고 판정했다. PyTorch
  학습은 QP 장애를 모두 결과 변화 없이 복구했다.
- **죽은 rank를 예비 프로세스에 되살렸다.** NCCL GIN에서 rank 하나가 죽어도 살아남은 rank의 대기가 오류 없이 원래 값으로 끝났고,
  최종 데이터가 장애 없는 실행과 같았다. 복원은 죽음 판정 뒤 0.3–0.4 s, 비용은 4 KiB 전송마다 1–1.5 µs다.
- **보낸 버퍼를 곧바로 다시 쓰는 application에서도 죽은 rank를 되살렸다.** 보낸 내용을 NIC이 짝 rank의 호스트 메모리에 한 번 더
  써 두고 복원이 그 사본을 쓰게 해, 짝이 되살아난 뒤의 둘째 죽음과 학습 형태의 전송에서도 최종 데이터가 장애 없는 실행과 비트 단위로
  같았다. 복원은 약 0.2–0.3 s, 비용은 4 KiB 전송마다 put 한 번의 지연보다 조금 작은 7–9 µs이고 2 MiB 전송 지연은 약 1.9배다.

## 연구 질문

1. 장애가 나면 NIC, 완료 기록(CQE), 라이브러리, API, 호스트 중 어디까지 오류가 전달되는가.
2. 남은 정보로 장애 원인을 몇 가지로 구분할 수 있는가.
3. 어떤 장애를 application 수정 없이, 데이터를 잃거나 중복하지 않고 복구할 수 있는가.

## 주요 결과

| 주제 | 결과 | 폴더 |
|---|---|---|
| 정보가 사라지는 지점 | 장애 정보는 위 계층으로 갈수록 줄어든다. GIN은 대기 API에서 장애가 정상과 구분되지 않고, NVSHMEM은 실패한 쓰기를 성공처럼 반환한다 | `harness/gpu-initiated/propagation/` |
| 원인 구분 | 오류 코드만으로는 장애 7가지가 5가지로 구분된다. 상대 프로세스가 살아 있는지 확인하면 6가지로 구분된다 | `harness/`, `harness/teardown_order/` |
| 살아 있는 상대 | 상대가 살아 있어도 QP가 요청을 받을 수 없으면 죽었을 때와 같은 오류가 온다. 탐지기가 살아 있는 상대를 죽었다고 오판하기 시작하는 정지 시간을 미리 맞혔다 | `harness/live_peer/` |
| 완료 계약 | 오류 상태의 NIC는 doorbell record 값까지만 완료를 만든다. 이 규칙이 NVSHMEM 버그와 여러 스택의 동작을 설명한다 | `harness/gpu-initiated/completion_contract/` |
| 감지 시간 | 재전송이 끝나 오류가 보이기까지 IB 타임아웃 14에서 3.5–3.8 s, 기본값 20에서 약 58 s 걸린다. 이 시간을 미리 계산하는 모델을 만들었다 | `harness/ack_timeout/` |
| 복구(CPU, NCCL) | CPU verbs는 장애 난 QP만 다시 세워 약 0.8 ms에, NCCL은 중앙값 2.26 ms에 복구한다. NCCL 2.32.3의 내장 복원력은 포트가 하나인 이 환경에서 동작하지 않았다 | `harness/`, `harness/nccl-integration/` |
| 복구(GPU) | GIN과 NVSHMEM에서 application 수정 없이 복구했고, 장애 난 연결만 다시 세워 감지 뒤 복구 시간을 11.4 ms에서 3.0 ms로 줄였다. 복구할 수 없으면 오류로 알리고 죽은 rank를 뺀 communicator 줄이기가 약 17 ms에 된다. rank 4개에서 한 rank가 죽어도 나머지끼리의 통신이 끝까지 이어진다 | `harness/gpu-initiated/` |
| 실제 application | PyTorch 학습은 QP 장애를 모두 결과 변화 없이 복구했다. GIN과 NVSHMEM의 공식 예제는 application이 완료를 확인하는 호출 밖의 장애를 보지 못해 멈췄다 | `harness/blind/` |
| 호출 밖 감지 | 두 라이브러리에 호출 밖 감지를 더하자 GIN 예제는 멈추던 QP 장애를 모두 복구했고(감지 중앙값 18.6 ms), NVSHMEM 예제는 상대가 죽어도 0.11 s 안에 오류로 끝났다. 거짓 판정은 없었다 | `harness/gpu-detect/` |
| 복원(죽은 rank 되살리기) | 죽은 rank만 예비 프로세스에 되살려, 생존 rank의 대기가 원래 값으로 끝나고 최종 데이터가 장애 없는 실행과 같았다. 복원은 죽음 판정 뒤 278–401 ms, 비용은 4 KiB 전송마다 1.0–1.5 µs | `harness/gpu-initiated/gin_recovery/restore/` |
| 복원(보낸 버퍼 덮어쓰기) | 보낸 내용의 사본을 짝 rank의 호스트 메모리에 두어, application이 보낸 버퍼를 곧바로 덮어써도 죽은 rank를 비트 단위로 같게 되살렸다. 짝이 되살아난 뒤의 둘째 죽음과 학습 형태의 전송도 같았다. 복원은 죽음 판정 뒤 174–298 ms, 비용은 4 KiB 전송마다 7.2–8.8 µs, 2 MiB 전송 지연 1.86–1.93배 | `harness/gpu-initiated/gin_recovery/mirror/` |

## 작업 방식

- **사전 등록:** 2026-10-06부터 실험마다 가설, 예측, 판정 기준, 반복 수를 측정 전에 고정하고 Git 태그(`prereg/...`)와 해시로 남겼다.
  사전 등록 뒤 바뀐 것은 실험 폴더의 `DEVIATIONS.md`에 날짜와 이유를 적었다. 사전 등록 실험은 23건이고 모두 끝났다. 그 전(2026년 9월)의
  결과는 사전 등록 없이 쟀고, 일부는 이후 사전 등록 실험에서 다시 쟀다.
- **Blind test:** 실제 application 시험에서는 장애 일정을 다른 에이전트가 무작위로 정해 봉인했고, 정답을 모르는 에이전트가
  판정을 먼저 커밋한 뒤 봉인을 열었다.
- **검증:** 채점은 고정한 판정식을 그대로 적용하는 스크립트로 했고, 채점 코드를 보지 않는 독립 재집계와 코드 리뷰를 따로 거쳤다.
  예측이 틀린 경우도 그대로 보고했다.
- **데이터:** 원시 로그는 GitHub Release(`data-...`)에 올리고 체크섬을 [`DATA.md`](DATA.md)에 적었다.
- **도구:** 구현, 실행, 문서 작업에 AI 코딩 도구(Claude Code)를 썼다. 그 작업 규칙이 [`CLAUDE.md`](CLAUDE.md)와 `.claude/`에 있다.
  실험 설계와 판단은 연구자가 정했다. 독립 재집계와 코드 리뷰도 채점 코드를 보지 않는 별도의 AI 에이전트가 했다.
- **기록:** 모든 변경은 브랜치와 PR로 합쳤다. 규칙은 [`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md)에 있다.

## 진행 중

- NVIDIA의 #117 수정이 공개되면 그 release로 다시 재기.

## 범위와 한계

- **장비:** 노드 한 쌍과 NIC 한 종류(ConnectX-6)에서만 쟀다. 범위를 mlx5 기반 스택으로 한정한다.
- **장애 종류:** 소프트웨어로 주입했다. 실제 link down은 공유 링크라 시험하지 않았다.
- **GPU:** 소비자용 GPU만 썼다. Hopper(SM90)가 필요한 DeepEP는 돌리지 않았다.
- **복구 수정본:** 시험 코드를 뺀 운영 빌드가 있지만 연구용 패치다. 상대를 지정하지 않는 대기(signal 대기, 배리어)는 상대의 죽음
  판정 2 s 뒤 오류로 풀리는데, 건강한 상대에 대한 그런 대기도 함께 풀린다. GPU가 직접 통신하는 두 라이브러리에 더한 호출 밖
  감지는 원인을 알려 주는 완료 기록이 없으면 50 ms를 기다리고, 상대 쪽만 망가진 장애는 상대의 감지에 기댄다. 4 rank는 GPU 두
  개를 나눠 써서 쟀고, 실제 하드웨어 장애에서는 재지 않았다.
- **기존 기능:** NCCL 2.29.7 이후의 port failover와 port recovery는 다른 포트가 있어야 동작한다. 노드마다 포트가 하나인 이 환경에서만
  비교했다.
- **초기 연구:** `experiments/`와 `docs/`의 내용은 다른 클러스터에서 한 것이고, 일부 수치는 이 실험 환경에서 다시 재지 않았다.

## 실험 환경

| 노드 | 역할 | NIC | GPU |
| --- | --- | --- | --- |
| rain | requester, rank 0 | ConnectX-6 VPI, fw 20.43.4100 | Quadro RTX 5000 (sm_75) |
| sunny | responder, rank 1 | ConnectX-6 VPI, fw 20.43.4100 | RTX A4000 (sm_86) |

100 GbE RoCE v2로 직결했다. 관리망 주소는 문서용 주소(192.0.2.x)로 바꿔 두었다.

## 저장소 구성

| 경로 | 내용 |
| --- | --- |
| [`MODEL.md`](MODEL.md) | 오류 전파 규칙 5가지(분석 틀) |
| `harness/` | CPU verbs 장애 측정과 복구, 오판 측정(`live_peer/`) |
| `harness/nccl-integration/` | NCCL 장애 복구 |
| `harness/gpu-initiated/` | GPU-initiated 스택(GIN, NVSHMEM). 종합은 `RESULTS.md` |
| `harness/ack_timeout/`, `harness/teardown_order/` | 감지 시간과 오류 코드 차이 분석 |
| `harness/blind/` | 실제 application blind test |
| `harness/gpu-detect/` | GPU가 직접 통신하는 라이브러리의 호출 밖 장애 감지 |
| [`DATA.md`](DATA.md) | 원시 데이터 Release 목록과 체크섬 |
| `experiments/`, `docs/` | 초기 연구 |

결과를 인용할 때는 브랜치가 아니라 태그나 커밋을 가리킨다. 사전 등록은 `prereg/...` 태그, 원시 데이터는 `data-...` 태그다.

## 라이선스

[MIT](LICENSE). 단, NCCL, NVSHMEM 등 다른 프로젝트에 대한 패치(`*.diff`)와 그 안의 원래 코드는 각 프로젝트의 라이선스를 따른다.
