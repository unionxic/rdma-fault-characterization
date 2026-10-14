# 병렬 구현 분담 (gin-mirror, 2026-10-13)

**통합 완료(2026-10-15).** 다섯 갈래를 `exp/gin-mirror-int`에서 하나의 계층으로 합쳤다([../EXPERIMENT.md](../EXPERIMENT.md) 12절의 통합 행, [mi_layer.diff](mi_layer.diff)). 저장소 수준에서는 갈래 커밋을 차례로 그대로 옮겼고(cherry-pick, 파일이 겹치지 않음), 소스는 i5 커밋을 바탕으로 갈래 diff 넷을 3-way로 합친 뒤 자리표시를 지우고 진입 함수를 이었다. 갈래마다의 `notes_<이름>.md`는 12절로 옮기고 지웠다. 아래 표와 규칙은 그때의 나눔으로 남긴다.

**상태(나눌 때): 공유 인터페이스 고정, 구현 전.** 설계는 [../EXPERIMENT.md](../EXPERIMENT.md) 9절(열린 충돌 없음), 작업 묶음은 9.8절의 표다. 이 파일은
갈래를 나누는 규칙이고, 인터페이스의 글자는 아래 헤더 여섯이다. gin-restore의 [PARALLEL.md](../../restore/impl/PARALLEL.md)와 같은 꼴이다.

## 바탕

- mirror 계층은 gin-restore 마지막 계층 [rs_layer.diff](../../restore/impl/rs_layer.diff)(md5 `f005bb67`, 빌드 i5: 연구 libnccl `4811f28f`,
  운영 `be91b270`) **위의** diff다. 헤더와 이 파일의 줄 번호는 따로 적지 않으면 그 diff의 줄이다.
- 바탕 트리는 메인 세션 스크래치의 `agent_rs_int/`(i5)이고 읽기만 한다. 갈래마다 [build_mi.sh](build_mi.sh) `setup`이 i5의 md5를 확인한
  뒤 `agent_mi_<이름>/`로 복사하고, 복사본에서 rs 계층을 커밋 하나("gin-restore i5 (rs_layer.diff f005bb67)")로 만든다. 갈래의 mirror
  diff는 그 커밋 위의 working tree이고 `impl/mi_layer_<이름>.diff`에 둔다(`build_mi.sh diff`가 씀).
- 출력은 갈래 트리의 `out/` 아래 새 이름에만 둔다(있는 폴더는 거절). `agent_rs_int/`, `agent_gd/`, 다른 갈래의 트리는 읽기만 한다.

## 브랜치와 소유

모든 갈래는 `exp/gin-mirror`에서 이 파일을 더한 커밋 뒤에 갈라진다. worktree는 `~/rdma-error-wt/gin-mirror-<이름>`이다.

| 브랜치 | 작업 묶음(9.8절) | 소유(이 안에서만 고친다) |
|---|---|---|
| `exp/gin-mirror-dev` | 장치 mirror, 단계 맞춤 가져오기 | `gin_gdaki.h`의 hold 영역(`rsPutHold` 627–717에서 부르는 mirror 함수, flush와 wait 끝의 mirror 기다림); 측 표 만들기(`gdakiRsSideLayoutOf` 2844–, `gdakiRsStart` 9693–9812: magic, mirror 칸, cell 배열); dev의 log 영역(9897–10987)에서 QP 묶음 함수(`gdakiRsQpsOfPeer` 9940 좁힘, `gdakiRsQpsOfPeerAll`, `gdakiMiQpOfPeer`, `gdakiMiExecReadMirror`, `gdakiMiReadMsgsMirror`)와 루프백 쌍의 잠금(`gdakiRsAtomicOp` 10502); 새 영역 "gin-mirror (dev): import"; 한 줄 고침 셋(`gdakiCkptSuppressLeft` 8096–8107, `ncclGinGdakiRestoreStep` 9370 뒤, `gdakiRsSpareDataFdImport` 11152–11157); 기계어 비교 도구; `impl/mi_unit_dev.cc` |
| `exp/gin-mirror-host` | mirror 설정, pool, 장애 기록; segment와 당기기; PUBLISHED와 INJECTED | 문맥 만들기의 mirror 문맥(QP를 만들기만), `gdakiTsSetup`의 policyPad 비트, MIRROR_SETUP 교환, 잇기와 기준, pool 등록, Resume 조건 34–40(`gdakiRsLocalCheck` 2780–2838과 모음), G4(5489–5495)와 훑기(rs 트리 10065–10085)의 흡수, 정리; 체크포인트 기계의 segment 자리([rs_store_api.h](rs_store_api.h)의 경계 목록), CKPT_PULL(9383), `gdakiMiPoll`; 붙잡기 기계의 PUBLISHED와 INJECTED(게시 7403–7404의 게이트 홀수, `gdakiHoldAfterPublish` 7205–7219의 시한, `gdakiHoldApplyRestored` 7039–7083, `gdakiHoldOnMsg` 7085–7128과 `gdakiHoldDrain` 7129–7141의 거름, INJECTED 보내기); mirror의 NCCL_PARAM; 새 영역 "gin-mirror (host): ..."; `impl/mi_unit_host.cc` |
| `exp/gin-mirror-store` | RDMA 저장소 | 새 영역 "gin-mirror (store)"(저장소 MR, STORE_REQ/ACK, 올리기 QP와 host QP 도구, 고정 D2H 버퍼); 체크포인트 기계의 저장소 자리(경계 목록: `gdakiCkptInitStep` 8440–8446, 8514, 8525–8531, 8545–8562; `gdakiCkptOnStable` 8236–8248; `gdakiCkptTake` 9259–9361; TCP 기반 지우기 `gdakiCkptUploadOne` 8671–8751과 `gdakiHoldApplyRestored` 7076 뒤 한 줄); `impl/mi_unit_store.cc` |
| `exp/gin-mirror-spare` | 복원 길, 끝점 갱신 | hold 시작(6891 뒤 mirror 읽기, 6900–6909 HOLDING 칸); `gdakiHoldCommitRound` 7383 뒤 mirror 확인; 짝 drain과 울타리(새 영역, `gdakiHoldActivate` 앞에서 부름); 활성화 v2(`gdakiHoldActivate` 7297–7358, `gdakiRsSpareRun` 6264–); REJOIN, TOKEN, READY(5644–6497); `gdakiRsSwapRkeys` 6072–의 pool 종류; 내보내기 v2(새 함수, `gdakiHoldTransferStep` 8939–9019에서 부름); FETCH QP와 READ, FETCH 버퍼(초기화 재생); `impl/mi_unit_spare.cc` |
| `exp/gin-mirror-test` | 시험과 비용 | `impl/test/` 아래 새 파일만(gin-restore의 `gin_rs.cu`, 실행기, 채점기는 복사해 새 이름으로; `restore/` 아래는 읽기만). 라이브러리를 빌드하지 않는다. 시험 프로그램은 i5의 설치 헤더로 컴파일만 확인한다 |

- 통합과 검사는 메인 세션이 `exp/gin-mirror`에서 한다.
- 남의 함수 안에서 고칠 수 있는 곳은 [rs_mirror_api.h](rs_mirror_api.h)의 넣고 빼는 자리 표와 [rs_store_api.h](rs_store_api.h)의 경계 목록에
  적힌 줄뿐이다. 다른 갈래 함수 안의 한 줄 호출은 그 표가 적은 갈래가 넣는다. 그 밖은 읽기만 한다.
- 갈래마다의 상태는 `struct gdakiRecHost`의 멤버 하나(`struct gdakiMiState mi;`) 아래 자기 포인터에만 둔다(rs_mirror_api.h).

## 공유 인터페이스

메인 세션이 고정한 헤더 여섯이다. 고칠 일이 생기면 갈래는 고치지 않고 notes에 적어 메인 세션에 알린다. 메인 세션이 헤더를 고쳐 커밋하고 모든
갈래에 알린다(충돌 먼저).

| 헤더 | 붙이는 곳(원본 트리) | 붙이는 갈래 |
|---|---|---|
| [rs_mirror_api.h](rs_mirror_api.h) "device layout" | `gin_gdaki_device_host_common.h`, diff 1168–1215 자리에 바꿔 넣음 | 모두 |
| 같은 파일 "device helpers" | 같은 헤더, `ncclGinRsCsumBuf`(1452) 뒤 | 모두 |
| 같은 파일 "host API" | `gin_host_gdaki.cc`, log API 블록 끝 표시(2417) 뒤 | 모두 |
| `gdakiRecHost`의 멤버 한 줄 | `rsLog` 멤버(2471) 뒤: `  struct gdakiMiState mi;  // gin-mirror (impl/rs_mirror_api.h): the mirror layer's per-context state` | 모두 |
| [rs_store_api.h](rs_store_api.h) "store API" | `gin_host_gdaki.cc`, 둘째 shared text의 끝(4978) 뒤 | 모두 |
| [rs_log_api.h](rs_log_api.h) v2의 log API 블록 | v1 블록(2218–2417)을 바꿔 넣음 | 모두 |
| [rs_hold_api.h](rs_hold_api.h) v2의 shared text | v1의 첫 shared text(4191–4357)를 바꿔 넣음 | host만(새 진입 함수 선언이 있어 다른 갈래 트리에서는 "정의 없음" 경고가 남) |
| [rs_ckpt_api.h](rs_ckpt_api.h) v2 | shared text는 v1 그대로(머리 주석만 v2) | 없음 |
| [rs_spare_api.h](rs_spare_api.h) v2 | 붙이지 않음(선언을 다시 적은 파일) | 없음 |

- 모든 갈래의 첫 커밋은 `build_mi.sh paste`로 위 표를 한 번에 붙인 "인터페이스 커밋"이다. 갈래마다 같은 글자, 같은 자리라 합칠 때 겹치지 않는다.
  `build_mi.sh api`가 붙인 글자와 헤더를 바이트 단위로 견주고, 헤더 여섯을 함께 `g++ -fsyntax-only`로 컴파일한다.
- 블록 안에는 형, 상수, 순수 `static inline` 함수만 둔다. 진입 함수는 블록 밖에 선언을 다시 적고 [주인]을 단다. 다른 갈래의 진입 함수를 부르는
  갈래는 통합 전까지 자기 영역에 중립 값을 돌려주는 자리표시 정의를 두고 `// placeholder (integration replaces)`를 단다. 통합 때 지운다.
- 순수 함수는 갈래마다 "gin-mirror (<이름>): pure" 영역(시작과 끝 표시)에 모은다. `build_mi.sh unit`이 그 영역을 잘라 CPU에서 시험한다.

## 기록

- 갈래는 `EXPERIMENT.md`를 고치지 않는다. 12절에 들어갈 행(날짜, 무엇을, 근거)은 `impl/notes_<이름>.md`에 쌓는다. 통합 때 메인 세션이 그
  행을 12절로 옮기고 notes 파일을 지운다(문서는 끝내 `EXPERIMENT.md` 하나).
- 인터페이스가 정하지 않은 것을 정했으면 notes에 "인터페이스 밖에서 정함"으로 따로 적는다.

## 묶음마다의 차례

1. 충돌 검토: 맡은 묶음의 인터페이스와 `rs_layer.diff`의 해당 줄을 대조한다. 충돌이 남으면 구현하지 않고 메인 세션에 알린다.
2. 구현(소유한 곳만), `build_mi.sh paste`는 첫 커밋에 한 번.
3. 빌드: `build_mi.sh mi`, `mip`(sm_75, sm_86, 경고 0). 여기까지 했으면 "빌드됨"이라고 쓴다.
4. `build_mi.sh api`, `build_mi.sh unit`(ASan, UBSan). 돌린 시험의 이름과 개수를 적을 때만 "시험함"이라고 쓴다.
5. 기계어 비교(dev 갈래, `build_mi.sh ident`): 아래 fail-fast 동일성.
6. 독립 리뷰: 같은 모델의 다른 에이전트가 읽기만 하고 묶음마다 따로 본다. 찾은 것과 고친 것을 notes에 적는다.
7. `build_mi.sh diff`, `info`, notes 기록, 커밋(Conventional Commits, 파일을 하나씩 add, 표기 줄 없음). push와 PR은 하지 않는다.

클러스터 실행, GPU나 RDMA 프로그램 실행, `~/rs-bundle`, `~/gi-bundle`, `~/gd-bundle` 아래 작업은 없다. pilot은 메인 세션이 `cluster_run.sh` 안에서 한다.

## fail-fast 동일성 (9.5절)

- 매크로(`NCCL_GIN_RESTORE_DEVICE`) 없는 프로그램(`ff_ops.cu`와 `prog_sass.sh`의 셋)과 NCCL 자신의 장치 객체는 SASS 전체와 `-res-usage`가
  hk(`agent_gd/gin_hk`)와 i5(`agent_rs_int`)에 같아야 한다. 연구 빌드와 운영 빌드 둘 다다. dev 갈래가 gin-restore의 `exact_cmp_dev.sh`,
  `ff_cmp_dev.sh`를 새 이름(`exact_cmp_mi.sh`, `ff_cmp_mi.sh`)으로 옮겨 `build_mi.sh ident`에 잇는다.
- 매크로 빌드의 flush와 wait는 측 표 읽기 하나와 분기 하나가 더해진다. 그 비용은 test 갈래의 비용 팔(`ffb-rs-macro` 꼴)이 잰다.
- 호스트는 `NCCL_GIN_RESTORE_MIRROR`가 없으면 mirror 문맥, pool, 저장소, 새 기록을 만들지 않고 gin-restore의 길 그대로다(TCP 길의 9.6절 기반
  지우기만 다름). 각 갈래의 CPU 단위 시험은 mirror 끈 값에서 v1의 판정이 그대로인지도 시험한다. 실제 회귀는 pilot의 회귀 셀이 본다.

## 통합 (메인 세션)

갈래를 `exp/gin-mirror`로 합친다. 저장소 수준에서는 갈래마다 파일이 다르다(`mi_layer_<이름>.diff`, `mi_unit_<이름>.cc`, `notes_<이름>.md`).
소스는 i5 커밋을 바탕으로 갈래 diff를 3-way로 합친다(인터페이스 커밋은 같은 글자라 겹치지 않음). 자리표시 정의를 지우고, 합친 트리에서 `mi`,
`mip`, `api`, 모든 `unit`, `ident`를 다시 하고, 합친 계층 `mi_layer.diff`를 쓰고, 독립 리뷰를 받는다. 그다음 pilot이다.
