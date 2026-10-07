# 완료 계약의 일반성 (completion_contract)

**목적:** `MODEL.md` 규칙 1(오류 상태의 NIC는 doorbell record 값까지만 완료를 만든다)이 NVSHMEM 버그 하나가
아니라 여러 GPU 스택에 적용되는 규칙인지 확인한다. 스택마다 record를 어떻게 쓰는지 소스에서 먼저 읽어
"장애가 보인다 / 사라진다 / 조건부"를 예측하고, 이 테스트베드에서 새로 잴 수 있는 곳만 측정한다.

| 항목 | 값 |
|---|---|
| 상태 | `RUNNING` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-06 |
| 기준 브랜치와 커밋 | `exp/completion-contract` @ `31098a9d` (master) |
| 사전 등록 태그 | `prereg/completion-contract-v1` (이 상태로 바꾼 커밋) |
| 마지막 갱신 | 2026-10-07 14:30, smoke 끝, 본 실행 시작 |

표시: `[측정]` 원자료에서 확인, `[추론]` 해석, `[미확인]` 확인 안 함. 소스에서 읽은 예측은 `[소스]`로 표시한다.

## 1. 배경과 연구 질문

- 규칙 1의 근거는 지금까지 NVSHMEM CPU 프록시(record의 엉뚱한 칸에 씀) 하나와 NIC 측정 225회다
  ([../nvshmem_rootcause/README.md](../nvshmem_rootcause/README.md)). 그래서 "버그 보고 하나"로 읽힐 수 있다.
- 질문:
  1. GPU가 시작하는 RDMA 스택과 CPU verbs 경로는 record의 송신 칸을 게시한 작업 수까지 올리는가.
  2. 올리지 않거나 늦게 올리는 경로가 있다면, 규칙 1이 예측하는 대로 장애가 사라지는가.
  3. 규칙 1이 적용되지 않는 경우(record를 아예 읽지 않는 QP 설정 등)는 어디인가.

## 2. 가설

- record 값이 게시한 작업 수에 결국 닿는 경로에서는 장애가 CQE 계층에 보인다. 닿지 않는 경로에서는 그
  차이만큼 완료가 사라진다.
- 다음 중 하나가 관측되면 가설은 틀린 것이다.
  - 소스상 record가 닿지 않는 경로에서 오류 완료가 나온다.
  - 소스상 record가 닿는 경로에서 오류 완료가 나오지 않는다.

## 3. 사전 예측

예측 원문은 [predictions.csv](predictions.csv)(측정 P1–P7, 소스 S1–S14), 해시는 [PREREG.txt](PREREG.txt).

### 3.1 소스 예측 (스택 열네 가지) `[소스]`

소스를 읽어 세운 예측이다. 근거 줄 번호, 버전, 커밋은 `audit/`의 네 보고서에 있다. "보인다"는 오류 상태에서
게시된 모든 작업이 오류나 flush 완료를 받는다는 뜻이다.

| 스택과 경로 | 누가 record를 쓰나 | 예측 | 근거 |
|---|---|---|---|
| CPU verbs(libmlx5), NCCL net_ib, NCCL GIN 프록시 | CPU의 libmlx5, 매 게시마다 송신 칸 | 보인다 | [audit/A_verbs.md](audit/A_verbs.md) |
| UCX CPU 경로(rc, dc, ud) | CPU의 UCX, 매 게시마다 송신 칸 | 보인다 | [audit/D_ucx_rocshmem.md](audit/D_ucx_rocshmem.md) |
| NCCL GIN GDAKI 기본(GPU가 doorbell) | GPU 스레드, 매 게시마다 송신 칸 | 보인다 | [audit/B_gdaki_doca.md](audit/B_gdaki_doca.md) |
| NCCL GIN GDAKI의 CPU 프록시 처리 방식 | CPU 진행 스레드 | 조건부: 진행 스레드가 도는 동안 보인다 | B |
| NCCL GIN GDAKI의 묶음 요청(doorbell 생략 힌트) | 힌트 없는 다음 작업이 씀 | 조건부: 같은 QP에 힌트 없는 작업이 뒤따르면 보인다 | B |
| NCCL GIN GDAKI의 BlueFlame 처리 방식(설정값 6) | 아무도 쓰지 않음 | 사라진다(전부). 장애가 없어도 작업이 NIC에 가지 않는다 | B |
| DOCA의 record 없는 하드웨어 모드 | 쓰지 않음(NIC가 record를 읽지 않게 설정) | 규칙 1의 범위 밖. doorbell을 따른다면 보인다 | B, D |
| NVSHMEM 3.4.5 CPU 프록시 | CPU 프록시, 송신 칸 | 보인다 | [audit/C_nvshmem_deepep.md](audit/C_nvshmem_deepep.md) |
| NVSHMEM 3.5.0부터 3.8.0까지 CPU 프록시(RC와 DCI) | CPU 프록시, 수신 칸(엉뚱한 칸) | 사라진다(전부) | C |
| NVSHMEM GPU 처리(3.4.5, 3.5.x, 3.8.0) | GPU 스레드, 송신 칸 | 보인다 | C |
| NVSHMEM 3.8.0 묶음 전송 구역(선택 기능) | 대기, fence, 구역 끝에서 씀 | 조건부: 그중 하나가 장애 뒤 실행되면 보인다 | C |
| UCX GPU 경로 기본(지연 게시) | GPU, 128개마다 또는 즉시 게시 때 | 조건부: 마지막 1–127개는 즉시 게시가 뒤따라야 보인다 | D |
| rocSHMEM(AMD GPU) | GPU, 송신 칸 | CQE에서는 보인다. 라이브러리가 오류를 검사하지 않아 API에서는 사라진다 | D |
| DeepEP 최신 판 | NCCL GIN에 맡김 | 미정(NCCL GIN 설정에 따름) | C |

### 3.2 측정 예측 (이 테스트베드에서 새로 재는 칸)

| id | 칸 | 예측 | 판정 기준 | 근거 |
|---|---|---|---|---|
| P1 | NVSHMEM 공식 3.4.5, CPU 프록시, 상대 kill | 죽은 뒤 첫 반복이 재시도가 끝난 뒤(3–5 s) 돌아온다 | 10회 중 9회 이상, 30 s 안에 안 돌아오는 시행 0회 | 3.4.5 프록시는 송신 칸에 쓴다 |
| P2 | NVSHMEM 공식 3.4.5, GPU 처리, 상대 kill | P1과 같다 | 5/5 | GPU 처리는 송신 칸에 쓴다 |
| P3 | NVSHMEM 공식 3.4.5, CPU 프록시, 장애 없음 | 모든 반복이 돌아온다 | 5/5 | 대조 |
| P4 | NCCL GIN GDAKI, BlueFlame 처리 방식, 장애 없음 | 첫 반복의 대기가 끝나지 않는다(장치 대기 상한에서 시간 초과). 받는 쪽 데이터가 없다 | 10회 중 9회 이상, 정상 완료 0회 | 이 방식에서는 doorbell도 record도 쓰지 않는다 |
| P5 | NCCL GIN GDAKI, 기본 처리 방식, 장애 없음 | 모든 반복이 정상 완료 | 5/5 | 대조 |
| P6 | NCCL GIN GDAKI, CPU 프록시 처리 방식, 로컬 QP 오류, 원격 접근 오류, 상대 QP 오류 | 호스트 오류(10 s 주기 검사)가 나온다 | 장애마다 5/5 | 진행 스레드가 record를 올린다. 이벤트 방식의 호스트 오류는 오류 CQE가 있어야 나온다 |
| P7 | NCCL GIN GDAKI, CPU 프록시 처리 방식, 장애 없음 | 오류 없이 정상 완료 | 5/5 | 대조 |

## 4. 범위

- **포함:**
  - 소스 조사: 3.1의 스택 열네 가지(공개 저장소, 버전과 커밋은 `audit/`에 기록).
  - 측정: 3.2의 일곱 칸.
- **제외:**
  - rocSHMEM: AMD GPU가 없다.
  - DeepEP 옛 판: Hopper GPU가 필요하다.
  - UCX: 이번에는 빌드하지 않는다. 소스 예측만 둔다.
  - DOCA의 소프트웨어 흉내 record 모드: GDRCopy 커널 모듈이 두 노드 모두 올라가 있지 않다. 모듈을 올리는
    것은 시스템 변경이라 하지 않는다.
  - record를 읽지 않는 하드웨어 모드: ConnectX-6가 지원하는지 모른다.
  - 묶음 요청과 묶음 전송 구역의 조건부 경로: doorbell 자체를 미루는 경로라서 record 규칙의 시험이 아니다.
  - 이미 잰 경로(CPU verbs, NCCL net_ib, GIN 프록시, GDAKI 기본, NVSHMEM 3.5–3.8 CPU 프록시, GPU 처리):
    기존 측정을 인용한다(14절).

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(요청, rank 0), sunny(응답, rank 1) | |
| NIC와 펌웨어 | ConnectX-6, fw 20.43.4100 | `[측정]` 2026-10-06 15:40(propagation 캠페인) |
| GPU | rain Quadro RTX 5000, sunny RTX A4000, PeerMappingOverride=1 | 같은 시각 |
| NCCL | 2.32.3 GIN 번들(`~/gi-bundle/gin`). `NCCL_GIN_GDAKI_NIC_HANDLER`, `NCCL_GDAKI_USE_RELIABLE_DB` 설정값이 들어 있다 | `[측정]` 2026-10-06 23:30, 라이브러리 문자열 확인 |
| NVSHMEM | 공식 v3.4.5-0(`131da55f`)을 새로 빌드한다 | `[미확인]` 빌드 전 |
| GDRCopy | rain에 사용자 라이브러리만 있다. 두 노드 모두 커널 모듈(`/dev/gdrdrv`)이 없다 | `[측정]` 2026-10-06 23:30 |

## 6. 변수

- **독립변수:** 스택과 버전(NVSHMEM 3.4.5, NCCL GDAKI), NIC 처리 방식(CPU 프록시, GPU, BlueFlame), 장애(장애
  없음, 로컬 QP 오류, 원격 접근 오류, 상대 QP 오류, 상대 kill).
- **종속변수:** 죽은 뒤 첫 반복이 돌아오는지와 걸린 시간, 대기 결과(정상, 시간 초과), 호스트 오류와 그 시각,
  받는 쪽 데이터.
- **통제변수:** IB 타임아웃 14, 재시도 7, 반복과 메시지 크기는 기존 실행기 기본값, 시행마다 프로세스를 새로
  띄운다.

## 7. 실험 셀, 반복 수, 대조군

| 셀 | 조건 | 반복 수 | 대조군 |
|---|---|--:|---|
| P1 | NVSHMEM 3.4.5, CPU 프록시(`cpu_host_memory`), 상대 kill | 10 | P3 |
| P2 | NVSHMEM 3.4.5, GPU 처리, 상대 kill | 5 | P3 |
| P3 | NVSHMEM 3.4.5, CPU 프록시, 장애 없음 | 5 | 대조 |
| P4 | NCCL GDAKI, 처리 방식 6(BlueFlame), 장애 없음, 시간 제한 대기 | 10 | P5 |
| P5 | NCCL GDAKI, 기본 처리 방식, 장애 없음, 시간 제한 대기 | 5 | 대조 |
| P6 | NCCL GDAKI, 처리 방식 1(CPU 프록시), 로컬 QP 오류, 원격 접근 오류, 상대 QP 오류, 시간 제한 대기 | 각 5 | P7 |
| P7 | NCCL GDAKI, 처리 방식 1, 장애 없음 | 5 | 대조 |

모두 50회다. 반복 수는 사전 등록 규칙(새 칸 10, 재현 칸 5, 대조 5)을 따랐다. P6은 9월 23일에 잰 CPU doorbell
경로의 재현이라 5회다.

## 8. 제외 기준과 중단 기준

- **제외 기준:**
  - smoke 실행은 채점하지 않는다.
  - P4: 통신 초기화가 처리 방식 6을 거부하면, 그 칸은 "이 설정은 쓸 수 없음"으로 따로 보고하고 채점하지
    않는다.
  - P6, P7: NCCL 로그(`NCCL_DEBUG=INFO`, `NCCL_DEBUG_SUBSYS=INIT,NET`)에 "이벤트 방식을 못 써 폴링으로 대체"
    문구(`falling back to polling-based errors`)가 있는 시행은 "관측 불가"로 따로 센다. 폴링 방식의 호스트 오류는
    QP 상태만 보고 나오므로 오류 CQE의 근거가 되지 않는다. 처리 방식(설정값 1)은 로그에 찍히지 않아 설정값으로만
    정한다.
  - 장애가 통신 중에 걸리지 않은 시행(상대가 일을 마친 뒤 kill된 경우 등)은 "장애 미적용"으로 따로 센다.
- **중단 기준:**
  - `cluster_run.sh`가 3600 s 안에 잠금이나 유휴 링크를 얻지 못하면 그 스택을 미룬다.
  - 다른 사용자 작업(`prio-` 등)이 기다리면 양보한다.
  - 실제 link down, 재부팅, 드라이버 재적재, 커널 모듈 적재는 하지 않는다.

## 9. 실행 방법과 경로

- **소스 조사:** 2026-10-06, 공개 저장소 복제본을 읽었다. 보고서 네 건은 [audit/](audit/).
- **배포/빌드:** NVSHMEM 3.4.5와 재현 프로그램을 `../nvshmem_rootcause/official380/build.sh`를 버전만 바꿔
  빌드하고, 두 노드의 `~/gi-bundle/nvshmem_345`에 둔다. 재현 프로그램은 버전마다 따로 링크한다(장치 라이브러리가
  정적이라서). `run.sh`는 묶음 경로를 환경변수로 받게 고친다. NCCL은 배포된 2.32.3 번들을 그대로 쓴다.
- **실행:**
  - NVSHMEM 칸: `../nvshmem_rootcause/official380/run.sh`(공개 API만 쓰는 재현 프로그램).
  - NCCL 칸: `../gin/scripts/run_trial.sh`에 처리 방식 설정값(`NCCL_GIN_GDAKI_NIC_HANDLER`)을 두 rank에
    환경변수로 준다. 이를 위해 실행기에 추가 환경변수를 넘기는 자리를 만든다.
  - 모두 `cluster_run.sh` 안에서 돈다.
- **채점:** [score.py](score.py). 결과는 `results/<날짜>/SCORE.md`.
- **출력:** `results/` 아래 날짜 폴더. 원시 로그는 Release.

## 10. 완료 조건과 QA 기준

- [ ] 3.2의 일곱 칸이 계획한 반복 수만큼 실행됐다(제외와 실패를 따로 센 표 포함).
- [ ] 예측마다 판정과 놓친 시행 목록이 있다.
- [ ] 소스 예측 표의 줄 번호를 다른 에이전트가 원본에서 다시 확인했다.
- [ ] 핵심 수치를 원자료에서 다시 셌다.
- [ ] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [ ] `MODEL.md` 규칙 1의 "맞힌 것"과 "한계"를 결과에 맞게 고쳤다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] NVSHMEM 3.4.5 빌드와 배포
- [x] smoke 실행(채점 제외)
- [ ] 본 실행 (`RUNNING`)
- [ ] 채점과 재계산 (`QA`)
- [ ] 결과 정리, 원자료 릴리스, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거 |
|---|---|---|
| 2026-10-06 22:20–23:20 | 에이전트 네 개가 스택별 소스 조사(읽기만, 빌드와 실행 없음) | [audit/](audit/) |
| 2026-10-06 23:30 | 배포된 NCCL 번들의 설정값과 GDRCopy 상태 확인 | 5절 |
| 2026-10-06 23:45 | 실험 문서 초안 | 이 문서 |
| 2026-10-07 09:12:55 | 제외 기준(폴링 대체 문구)과 실행 방법을 다듬고 사전 등록. 예측 원문은 [predictions.csv](predictions.csv) | [PREREG.txt](PREREG.txt), 태그 `prereg/completion-contract-v1` |
| 2026-10-07 09:14–09:19 | NVSHMEM 공식 v3.4.5-0 빌드(GDRCopy 끔)와 두 노드 배포. 플러그인과 재현 프로그램 md5가 두 노드에서 같음 | [build_345.sh](build_345.sh) |
| 2026-10-07 09:16–09:19 | NCCL 칸 smoke, 칸마다 1회(장애 칸은 장애마다 1회), 6회. 예측과 어긋난 시행 없음 | `results/20261007_smoke/gin/` |
| 2026-10-07 14:14 | NVSHMEM 3.4.5 smoke 1차, 3회. 모두 시작 단계 실패: 3.4.5가 RC 배정 값 "none"을 모름 | `results/20261007_smoke/nvs/`, [DEVIATIONS.md](DEVIATIONS.md) 2 |
| 2026-10-07 14:17 | 3.4.5가 IB 타임아웃 20, 재시도 7을 소스에 고정한 것을 확인. 대기 상한 90 s와 대체 판정 창 50–70 s를 결과 보기 전에 적음 | [DEVIATIONS.md](DEVIATIONS.md) 3 |
| 2026-10-07 14:18 | smoke 2차, 3회. GPU 처리는 죽은 뒤 첫 반복이 57.6 s에 돌아옴. CPU 프록시 2회는 sunny에서 주소 핸들 생성 실패로 시작 못 함 | `results/20261007_smoke/nvs2/`, [DEVIATIONS.md](DEVIATIONS.md) 4 |
| 2026-10-07 14:22 | 주소 핸들 구조체 초기화 한 줄(3.8.0과 같음)을 더한 3.4.5 플러그인 빌드, 두 노드 배포. smoke 3차, 3회: CPU 프록시 kill 59.9 s에 돌아옴, 장애 없음 40회 모두 돌아옴 | [patches/](patches/), [build_345_ahinit.sh](build_345_ahinit.sh), `results/20261007_smoke/nvs3/` |

## 13. 사전 등록 이후 변경

[DEVIATIONS.md](DEVIATIONS.md)에 적었다. 요점: 3.4.5는 타임아웃을 20으로 고정해서 예측의 3–5 s 창을 그대로 쓸 수 없다(쓴 그대로 판정과
타임아웃 20 창 판정을 함께 낸다). CPU 프록시 칸은 초기화 한 줄을 더한 3.4.5로 잰다. 예측과 판정 기준 원문은 바꾸지 않았다.

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 소스 조사 보고서 | [audit/](audit/) | 4 |
| 이미 잰 경로(인용) | [../propagation/results/20261006_campaign/LAYERS.md](../propagation/results/20261006_campaign/LAYERS.md), [../nvshmem_rootcause/README.md](../nvshmem_rootcause/README.md), [../nvshmem_rootcause/official380/README.md](../nvshmem_rootcause/official380/README.md) | |
| 측정 결과 | `[미확인]` 아직 없음 | |

## 15. 결과 요약

`[미확인]` 아직 측정 전이다.

## 16. QA와 재현성

`[미확인]`

## 17. 결론

`[미확인]`

## 18. 한계

- 소스 예측은 소스를 읽은 것이고, 실행하지 않았다. 닫힌 DOCA SDK 코드는 읽지 못했다.
- NIC 규칙은 ConnectX-6 한 종류, RC QP의 송신 쪽에서만 쟀다. 수신 쪽 flush가 같은 규칙을 따르는지는 모른다.
- record를 읽지 않는 QP 설정이 새로 생겼다. 이 설정을 쓰는 QP에는 규칙 1이 그대로 적용되지 않는다.

## 19. 다음 작업

1. 측정 칸을 확정하고 사전 등록한다.
2. NVSHMEM 3.4.5를 빌드한다.
3. 2026-10-07 오전의 정리 단계 실험이 끝난 뒤 클러스터에서 실행한다.

## 20. 참고자료

- [../../../MODEL.md](../../../MODEL.md) 규칙 1.
- Mellanox Adapters Programmer's Reference Manual, Rev 0.40, 7.4.2–7.4.3절.
