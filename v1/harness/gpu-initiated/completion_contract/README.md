# completion_contract: 완료 계약은 여러 스택에 맞나

오류 전파 규칙 1은 "오류 상태의 NIC는 doorbell record 값까지만 완료를 만든다"이다. 이 규칙의 근거가 NVSHMEM
버그 하나뿐인지, 여러 GPU 스택에 통하는 규칙인지 확인했다. 스택마다 record를 누가 언제 쓰는지 소스로 먼저
읽어 결과를 예측하고, 이 테스트베드에서 잴 수 있는 칸만 쟀다. 예측은 측정 전에 고정했다(태그
`prereg/completion-contract-v1`).

## 무엇을 쟀나

- **소스 예측:** 스택 14개(verbs, NCCL, NCCL GIN, DOCA, NVSHMEM 여러 버전, UCX, rocSHMEM, DeepEP). 다른 agent가
  근거 줄을 원본 커밋에서 다시 확인했다.
- **측정:** 일곱 칸, 55회.
  - NVSHMEM 3.4.5: 상대 kill(CPU 프록시, GPU 처리), 장애 없음.
  - NCCL GIN GDAKI: BlueFlame 처리 방식, 기본 처리 방식, CPU 프록시 처리 방식(장애 세 가지와 장애 없음).

## 결론

- **소스로 예측한 결과 방향이 일곱 칸 모두 맞았다.** record가 게시한 작업 수에 닿는 경로에서는 장애가 보였다.
  - NVSHMEM 3.4.5의 CPU 프록시는 송신 칸에 쓴다. 상대 kill 뒤 대기가 재전송이 끝나자 매번 돌아왔다. 같은
    프록시가 엉뚱한 칸에 쓰는 3.8.0에서는 오류 완료가 없었다.
  - NCCL GIN의 CPU 프록시 처리 방식은 진행 스레드가 record를 올린다. 장애 세 가지에서 매번 호스트 오류가 나왔다.
- **record도 doorbell도 쓰지 않는 경로에서는 작업이 아예 NIC에 가지 않았다.** NCCL GIN의 BlueFlame 처리
  방식은 장애가 없어도 첫 반복이 매번 시간 초과였고 받는 쪽에 데이터가 없었다.
- **시간 예측은 틀렸다.** NVSHMEM 3.4.5는 IB 타임아웃을 20으로 고정해서, 대기는 예측한 3–5 s가 아니라
  57.0–58.5 s 뒤에 돌아왔다. 결과를 보기 전에 정해 둔 타임아웃 20 기준 창(50–70 s)으로는 맞다.
- **규칙 1은 버그 하나의 설명이 아니라 스택을 미리 가르는 질문으로 쓸 수 있다.** 잰 칸에서는 "record 값이
  게시한 작업 수를 따라가나"만 소스에서 보고 결과 방향을 맞혔다.

## 결과

| 칸 | 결과 | 예측 |
|---|---|---|
| NVSHMEM 3.4.5 CPU 프록시, 상대 kill | 10/10 돌아옴, 56970–58474 ms | 시간 창 그대로는 틀림, 타임아웃 20 기준은 맞음 |
| NVSHMEM 3.4.5 GPU 처리, 상대 kill | 5/5 돌아옴, 56968–57013 ms | 같음 |
| NVSHMEM 3.4.5 CPU 프록시, 장애 없음 | 5/5 모두 돌아옴 | 맞음 |
| NCCL GIN BlueFlame 처리 방식, 장애 없음 | 10/10 첫 반복 시간 초과, 데이터 없음 | 맞음 |
| NCCL GIN 기본 처리 방식, 장애 없음 | 5/5 정상 | 맞음 |
| NCCL GIN CPU 프록시 처리 방식, 장애 세 가지 | 15/15 호스트 오류, 장애 뒤 9402–10001 ms | 맞음 |
| NCCL GIN CPU 프록시 처리 방식, 장애 없음 | 5/5 정상 | 맞음 |
| 비교: NVSHMEM 3.8.0 CPU 프록시, 상대 kill (다른 실험) | 오류 완료 0/5 | - |

시간 범위는 칸마다 모든 시행의 범위다.

## 한계

- **수정하지 않은 3.4.5는 CPU 프록시 방식으로 시작하지 못했다.** 주소 핸들 구조체를 0으로 비우지 않는 초기화
  문제였다. 3.8.0처럼 그 한 줄을 더한 빌드로 쟀다. doorbell record 코드는 그대로다.
- **3.4.5 칸은 오류 완료를 직접 읽지 않았다.** 대기가 돌아오는 것으로 완료가 생겼다고 봤다.
- UCX, rocSHMEM, DeepEP, DOCA의 record 없는 모드는 소스 예측만 있다. record를 읽지 않게 설정한 QP는 규칙 1의
  범위 밖이다.
- 노드 한 쌍, NIC 한 종류, RC QP다.

## 파일

| 파일 | 내용 |
|---|---|
| [EXPERIMENT.md](EXPERIMENT.md) | 기획부터 결론까지 진행 기록. 소스 예측 14줄과 근거는 3.1절 |
| [predictions.csv](predictions.csv), [PREREG.txt](PREREG.txt) | 사전 등록 예측과 해시 |
| [DEVIATIONS.md](DEVIATIONS.md) | 사전 등록 뒤 바뀐 것. 3.4.5 초기화 수정은 4번 |
| [audit/](audit/) | 스택별 소스 조사 네 건과 재확인([RECHECK.md](audit/RECHECK.md)) |
| [results/20261007/](results/20261007/) | 채점표([SCORE.md](results/20261007/SCORE.md)), 시행별 값, 독립 재계산 |
| `run_cells.sh`, `score.py`, `build_345.sh`, `build_345_ahinit.sh`, `patches/` | 실행, 채점, 3.4.5 빌드와 초기화 수정 |
| [MODEL.md](../../../MODEL.md) | 오류 전파 규칙. 규칙 1이 이 실험의 대상 |
| `../nvshmem_rootcause/cq380/` | 비교한 NVSHMEM 3.8.0 CPU 프록시 측정 |
| Release `data-20261007` | 원자료(칸별 로그). 목록과 체크섬은 [DATA.md](../../../DATA.md) |
