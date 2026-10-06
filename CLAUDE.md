# rdma-error: Claude Code 작업 규칙

RDMA 장애가 NIC에서 응용까지 어디서 남고 어디서 사라지는지 재는 연구 저장소다. 이 파일은 이
저장소에서 일하는 Claude Code가 따를 규칙이다.

## 먼저 볼 문서

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 연구 질문과 주요 결과 |
| [docs/GIT_WORKFLOW.md](docs/GIT_WORKFLOW.md) | 브랜치, 커밋, 추적 범위, 데이터 릴리스, 태그 |
| [DATA.md](DATA.md) | 원자료가 있는 Release 자산과 체크섬 |
| [docs/templates/EXPERIMENT.md](docs/templates/EXPERIMENT.md) | 실험 문서 템플릿 |
| [.claude/skills/experiment-workflow/SKILL.md](.claude/skills/experiment-workflow/SKILL.md) | 실험 작업 절차(skill) |

## 실험 워크플로: 실험 하나에 `EXPERIMENT.md` 하나

- **문서 하나로 관리한다.** 실험 하나는 폴더 하나이고, 그 폴더의 `EXPERIMENT.md` 하나가 단일 기준
  문서다. 다음 과정을 모두 이 파일에서 관리한다.
  - 연구 질문과 기획
  - 사전 예측
  - 구현과 실행
  - 진행 기록
  - QA
  - 결론
- **단계별 문서를 따로 만들지 않는다.** `spec.md`, `plan.md`, `tasks.md`, `qa.md`는 없다. 원자료,
  코드, CSV, 기존 문서는 복사하지 않고 링크한다.
- **상태는 여섯 가지다.**

  | 상태 | 뜻 |
  |---|---|
  | `DRAFT` | 질문, 가설, 셀을 정하는 중이다 |
  | `PREREGISTERED` | 예측, 셀, 반복 수, 제외 기준이 고정됐다. 고정 절, 이 상태, 해시를 담은 커밋 하나에 `prereg/<study>-v<n>` 태그를 단다 |
  | `RUNNING` | 본 실험을 실행 중이다 |
  | `QA` | 실행이 끝나 채점과 재계산, 검토를 하는 중이다 |
  | `COMPLETE` | QA까지 끝났다 |
  | `BLOCKED` | 진행할 수 없다. 이유와 풀 조건을 적는다 |

- **절차는 skill에 있다.** 새 실험을 시작하는 방법과 상태를 넘기는 방법은
  `.claude/skills/experiment-workflow/SKILL.md`에 있다.

### 반드시 지킬 규칙

1. 실험 작업을 시작하기 전에 해당 실험의 `EXPERIMENT.md`를 먼저 읽는다.
2. `PREREGISTERED` 이후에는 가설, 예측, 실험 셀, 반복 수, 제외 기준을 조용히 고치지 않는다.
3. 사전 등록 이후의 변경은 기존 문장을 덮어쓰지 않는다. 변경 기록에 다음을 남긴다.
   - 날짜, 이유, 영향 범위
   - 관련 커밋
4. 측정값, 추론, 미확인 사항을 구분해 표시한다. 예: `[측정]`, `[추론]`, `[미확인]`.
5. 문서에 적힌 집계값을 그대로 옮기지 않는다. 가능하면 원자료에서 다시 계산하고, 다시 계산했는지
   적는다.
6. 테스트나 실험을 실행하지 않았으면 성공했다고 쓰지 않는다. 컴파일만 했으면 "빌드됨"이라고 쓴다.
7. 결과마다 근거를 하나 이상 링크한다. 원자료 경로, 실행 ID나 태그, 커밋 중 하나다.
8. 표본 수(n)를 적는다. 실패, 제외, smoke 실행은 본 실험과 따로 센다.
9. 여러 실행을 합친 범위와 대표 실행 하나의 범위를 섞지 않는다. 범위마다 무엇의 범위인지 적는다.
10. 기존 숫자나 설명이 원자료와 다르면 원자료를 따르고, 충돌했다는 사실을 기록한다.
11. 긴 로그와 원자료를 Markdown에 복사하지 않는다. 경로와 줄 수, 필요한 한두 줄만 적는다.
12. 진행할 때마다 다음을 함께 갱신한다.
    - 작업 체크박스
    - 실행 기록
    - 결과 링크
    - 상태
13. QA가 끝나기 전에는 상태를 `COMPLETE`로 바꾸지 않는다.
14. 다른 실험의 `EXPERIMENT.md`를 고칠 때 그 실험의 결과나 사전 등록 내용을 새로 해석하지 않는다.
    고친 것은 링크와 상태 같은 사실뿐이어야 한다.

## 이미 정해진 문서 규칙

- **README**
  - 연구 내용만 쓴다: 무엇을 쟀나, 결론, 결과, 한계, 파일.
  - 한글로 1쪽 안에 쓴다.
  - 실행 방법과 구현 설명은 넣지 않는다. 그런 내용과 긴 원문은 같은 폴더의 `NOTES.md`에 둔다.
- **용어**
  - "fingerprint"는 쓰지 않는다. "오류 코드" 또는 "status와 vendor_err 조합"으로 쓴다.
  - 내부 단계 암호(Q4, S1/S2, T1 등)는 문서 본문에서 기능 이름으로 풀어 쓴다. 폴더, 파일, 환경변수
    이름은 그대로 둔다.
  - gate, park, poison, sentinel, mailbox는 README에서 기능을 풀어 쓴다.
  - 예측 ID(EV1a, D2 등), 장애 기호(F0~F4), 스택 약어(gp, gg 등)는 원자료를 찾는 키로만 쓴다. 결과 표와
    결과 문장, 사용자에게 하는 보고에서는 무엇을 예측했고 무엇이 나왔는지 풀어 쓰고, ID는 괄호나 별도 열에
    둔다.
- **사전 등록 파일은 고치지 않는다.** 태그와 해시로 고정된 파일이 대상이다. 예:
  `harness/gpu-initiated/propagation/PREDICTIONS.md`, `predictions.csv`, `REVIEW_20261006.md`,
  `PREREG.txt`, `review_20261006/`.

## Git

- master에는 직접 push하지 않는다. force push와 삭제는 저장소 규칙으로 막혀 있다.
- 작업은 브랜치에서 하고 PR로 합친다. 합칠 때는 "Rebase and merge"를 쓴다.
- 커밋 메시지는 Conventional Commits 형식이다. 작성자는 저장소에 설정된 noreply 주소다.
- Co-Authored-By나 도구 표기 줄을 넣지 않는다.
- 원자료(로그, 시행별 기록, 압축본)는 커밋하지 않고 Release에 올린다. 결과 폴더에는 해설 `.md`와
  문서가 인용한 표만 둔다.
- 관리망 실제 주소는 저장소 밖 `~/.config/rdma-error/mgmt.env`에만 있다. 어떤 표기로도 커밋하지
  않는다. push 전 훅이 검사한다.
- 실행 중인 프로세스, 수정 파일, untracked 파일이 하나라도 있는 체크아웃에서는 절대로 브랜치를
  바꾸지 않는다. 새 실험과 다른 브랜치 작업은 별도 `git worktree`에서 한다.
- 그런 체크아웃에서는 `git add -A`도 쓰지 않는다. 파일을 하나씩 지정해서 add한다.

## 클러스터 안전

- 모든 클러스터 실행은 `harness/gpu-initiated/common/cluster_run.sh` 안에서 한다. 락을 잡고, 링크가
  한가할 때 시작하는 스크립트다.
- 다음은 하지 않는다.
  - 실제 link down이나 link flap
  - 재부팅, 드라이버 재적재
- 다른 사용자의 작업은 건드리지 않는다. 예: gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 태그 작업.
- 프로세스를 끌 때는 내가 띄운 것만 PID나 `pkill -x <정확한 이름>`으로 끈다.
