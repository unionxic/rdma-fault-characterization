# 병렬 구현 분담 (2026-10-12, 사용자 결정)

사용자 결정(2026-10-12): (1) 송신 쪽 로그는 rank마다 고리 **하나**(항목에 상대 QP 번호를 적고, 상대마다
다른 체크포인트 시점은 항목 표시로 지운다). 메모리는 상대 수가 아니라 "체크포인트 사이에 보내는 연산 수"에
비례해야 한다. (2) fail-fast 커널의 레지스터 증가는 **빌드 때 켜는 방식**으로 막는다: 복원을 쓰는 프로그램만
빌드 매크로를 켜고, 안 켠 프로그램은 hk와 같은 레지스터 수를 가지며 복원 포인터를 만나면 멈춘다(trap).
(3) 구현은 Opus 에이전트 넷이 병렬로 하고 메인 세션이 감독만 한다.

## 브랜치와 소유

| 브랜치(worktree) | 맡는 묶음 | 소유 파일(이 안에서만 고친다) |
|---|---|---|
| `exp/gin-restore-dev` (`~/rdma-error-wt/gin-restore-dev`) | 4(다시: rank마다 고리 하나, 빌드 매크로), 6(로그 관리), 9(다시 넣기와 억제) | 장치 헤더 둘, 호스트 파일의 로그·억제·재실행 함수(표시한 구역), `impl/rs_log_api.h` |
| `exp/gin-restore-host` (`~/rdma-error-wt/gin-restore-host`) | 7(붙잡기 상태 기계) 먼저, 그다음 5(체크포인트) | 호스트 파일의 hold 분기·상태 기계·체크포인트 구역, `gin/gin_host.cc`와 공개 헤더의 Step 본문 |
| `exp/gin-restore-spare` (`~/rdma-error-wt/gin-restore-spare`) | 8(예비 프로세스: 초기화 재생, REJOIN, 끝점 바꾸기) | `bootstrap.cc`, `init.cc`, `transport/net_ib/gin.cc`, `dev_runtime.cc`, `gin/gin_host.cc`의 재생 hook, 호스트 파일의 REJOIN·끝점 구역 |
| `exp/gin-restore-test` (`~/rdma-error-wt/gin-restore-test`) | 10(시험 프로그램 `gin_rs.cu`, 실행기, 셀, 채점기, pilot 준비) | `impl/test/` 아래 새 파일만 |

모두 `exp/gin-restore` 커밋 `57eaf4e1` 이후의 같은 바탕에서 갈라진다. 빌드 트리는 브랜치마다 세션 스크래치의
`agent_rs_<이름>/`(`agent_rs/`의 복사본)이고, 출력은 새 폴더에만 둔다. 다른 브랜치의 소유 파일은 읽기만 한다.

## 공유 인터페이스

- 측 표와 로그 고리의 새 레이아웃, 호스트가 쓰는 로그 함수(머리 위치 읽기, 상대의 확정 위치로 지우기, 항목
  훑기)는 `dev` 브랜치가 **먼저** `impl/rs_log_api.h`에 선언과 주석으로 공개하고 커밋한다. `host` 브랜치의
  체크포인트(5)는 그 선언만 보고 코딩한다. 그래서 `host`는 7을 먼저 한다.
- `spare` 브랜치는 REJOIN을 받아들이는 진입 함수와 끝점 바꾸기 함수의 이름과 인자를 `impl/rs_spare_api.h`에
  공개하고, `host` 브랜치의 상태 기계는 그 함수를 "붙잡은 상대"에서만 부른다. 반대로 상태 칸을 읽는 함수는
  `host`가 `impl/rs_hold_api.h`에 공개한다.
- `test` 브랜치는 공개 API(`nccl.h.in`의 Resume, Step, Register)와 9.8절의 workload만 본다.

## 기록

- 각 브랜치는 `EXPERIMENT.md`를 고치지 않는다. 12절에 들어갈 행(날짜, 무엇을, 근거)은 `impl/notes_<이름>.md`에
  쌓는다. 통합 때 메인 세션이 그 행을 12절로 옮기고 이 파일들을 지운다(문서는 끝내 `EXPERIMENT.md` 하나).
- 묶음마다 충돌 검토 → 구현 → 빌드(두 아키텍처, 0 경고) → CPU 단위 시험 → 독립 리뷰(같은 모델, 읽기만) →
  기록. "빌드됨"과 "시험함"을 구분한다. 클러스터 실행은 없다.
- 통합: 네 브랜치를 `exp/gin-restore`로 차례로 rebase하고, 합친 트리를 다시 빌드해 모든 단위 시험과 fail-fast
  기계어 비교를 다시 한 뒤 독립 리뷰를 받는다. 그다음 pilot(메인 세션, `cluster_run.sh`).
