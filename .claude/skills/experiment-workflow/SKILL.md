---
name: experiment-workflow
description: rdma-error 저장소의 실험 작업 절차. 실험을 새로 시작하거나, 이어서 하거나, 실행 기록이나 결과, QA, 결론을 쓰거나, 어떤 실험의 EXPERIMENT.md를 고칠 때 사용한다. 실험 하나에 EXPERIMENT.md 하나로 기획부터 결론까지 관리한다.
---

# 실험 작업 절차 (single-file)

실험 하나는 폴더 하나이고, 그 폴더의 `EXPERIMENT.md` 하나가 단일 기준 문서다. 규칙의 원문은 루트
`CLAUDE.md`의 "실험 워크플로" 절이고, 템플릿은 `docs/templates/EXPERIMENT.md`다. 단계별 문서
(`spec.md`, `plan.md`, `tasks.md`, `qa.md`)는 만들지 않는다.

## 0. 언제나 먼저

1. 대상 실험 폴더의 `EXPERIMENT.md`를 끝까지 읽는다. 다음 세 가지를 확인한다.
   - 상태
   - 사전 등록 태그
   - 13절 변경 기록과 링크된 `DEVIATIONS.md`
2. 사전 등록 태그가 있으면 고정된 파일이 바뀌지 않았는지 확인한다. 예:
   `git diff <tag> -- <고정 파일>`, `sha256sum -c`.
3. 지금 체크아웃의 상태를 확인한다.
   - 실행 중인 프로세스: `pgrep -af cluster_run.sh`, 결과 폴더의 `trials.log`
   - 수정 파일과 untracked 파일: `git status --short --untracked-files=all`

   셋 중 하나라도 있으면 그 체크아웃에서는 절대로 브랜치를 바꾸지 않는다(`git switch`,
   `git checkout <branch>`, `git reset` 모두 금지). 브랜치를 바꾸면 실행 중인 실험이 쓰는 파일이 바뀌거나
   untracked 파일과 충돌한다. 다른 브랜치 작업은 별도 worktree에서 한다.

## 1. 새 실험 시작 (`DRAFT`)

새 실험은 기본적으로 별도 worktree에서 시작한다. 현재 체크아웃에서 `git switch -c`로 브랜치를 만들지
않는다.

1. 최신 master에서 새 worktree와 브랜치를 만든다.

   ```
   git -C ~/rdma-error fetch origin
   git -C ~/rdma-error worktree add --no-track -b exp/<study> ~/rdma-error-wt/<study> origin/master
   ```

   이후 작업은 모두 `~/rdma-error-wt/<study>` 안에서 한다.
2. 실험 폴더를 정하고 템플릿을 복사한다: `cp docs/templates/EXPERIMENT.md <폴더>/EXPERIMENT.md`.
3. 1~10절을 채운다. 기존 결과를 쓸 때는 원자료에서 다시 세고, 아니면 `[미확인]`으로 둔다.
4. 상태 `DRAFT`로 커밋한다. 파일을 하나씩 지정해 `git add`하고, `git add -A`는 쓰지 않는다. PR을
   draft로 연다.
5. 실험이 끝나 PR이 합쳐지면 `git worktree remove ~/rdma-error-wt/<study>`로 정리한다.

## 2. 사전 등록 (`DRAFT` → `PREREGISTERED`)

사전 등록은 **커밋 하나**로 고정하고, 태그는 **바로 그 커밋**에 단다.

1. 고정 절을 완성한다. 예측이 많으면 표 파일로 둔다.
   - 2절 가설
   - 3절 예측
   - 7절 셀과 반복 수
   - 8절 제외와 중단 기준
2. 같은 작업 안에서 다음 세 가지를 모두 한다.
   - `EXPERIMENT.md`의 상태를 `PREREGISTERED`로 바꾼다.
   - 12절에 사전 등록 기록을 적는다.
   - 고정할 별도 파일(예측 표 파일 등)의 sha256을 `PREREG.txt`에 기록한다. `EXPERIMENT.md`는 이후에도
     진행 기록이 바뀌므로 해시 대신 태그로 고정한다. 나중에 `git diff <tag> -- EXPERIMENT.md`에서 2, 3,
     7, 8절이 바뀌지 않았어야 한다.
3. 아직 측정 전인지 확인한다. 그다음 위 변경 전부를 **커밋 하나**로 만든다.
4. 그 커밋에 annotated 태그 `prereg/<study>-v<n>`을 달고 push한다.

   ```
   git tag -a prereg/<study>-v<n> -m "<무엇을 고정했나, sha256>" <그 커밋>
   git push origin prereg/<study>-v<n>
   ```

5. 태그 뒤에 상태만 바꾸는 커밋을 따로 만들지 않는다.
   - 상태 변경은 태그된 커밋에 이미 들어 있어야 한다.
   - PR을 rebase로 합치면 master에는 같은 내용의 다른 커밋이 생긴다. 태그는 원래 커밋에 둔다.
   - 두 커밋의 고정 파일이 같은지 `git diff <tag> <master 커밋> -- <고정 파일>`로 확인해 12절에 적는다.

이후 3, 7, 8절과 2절 가설은 고치지 않는다. 바꿀 일이 생기면 13절(또는 `DEVIATIONS.md`)에 날짜,
이유, 영향 범위, 커밋을 덧붙인다.

## 3. 구현과 실행 (`RUNNING`)

1. 계측과 실행기를 만든다. 데이터 경로를 바꾸는 변경은 13절에 적는다.
2. 빌드한다. 실행하지 않았으면 "빌드됨"이라고만 쓴다.
3. smoke 실행은 별도 결과 폴더에 두고 채점에서 뺀다. 13절에 적는다.
4. 본 실행은 `harness/gpu-initiated/common/cluster_run.sh` 안에서 한다. 시작과 끝, 스택이나 셀마다의
   진행을 12절에 시간순으로 적는다.
5. 진행할 때마다 다음을 함께 갱신한다.
   - 11절 체크박스
   - 12절 실행 기록
   - 14절 링크
   - 상태

## 4. QA (`RUNNING` → `QA`)

1. 채점기를 돌려 예측마다 판정, n, 놓친 시행을 얻는다. 사전 등록한 판정 기준을 그대로 쓴다.
2. 핵심 수치를 원자료에서 다시 계산한다. 문서에 이미 적힌 숫자를 옮기지 않는다.
3. 다음을 확인한다.
   - n을 적었는가
   - smoke와 제외 시행을 섞지 않았는가
   - 여러 실행의 범위와 대표 실행의 범위를 섞지 않았는가
4. 원자료와 기존 문서가 다르면 원자료를 따르고 충돌을 16절에 적는다.
5. 가능하면 다른 에이전트나 사람이 독립적으로 다시 센다.

## 5. 완료 (`QA` → `COMPLETE`)

1. 원자료를 Release에 올리고 `DATA.md`를 갱신한다(`tools/pack_release.py`).
2. 다음을 쓴다.
   - 15절 결과 요약: 수치마다 n과 근거
   - 17절 결론
   - 18절 한계
   - 19절 다음 작업
3. 폴더 README를 형식에 맞게 고친다. 연구 내용만 1쪽에 쓰고, 실행 방법은 NOTES.md에 둔다.
4. PR을 합치고, QA가 끝났을 때만 상태를 `COMPLETE`로 바꾼다.

## 막혔을 때 (`BLOCKED`)

이유, 풀리는 조건, 그때까지 하지 않을 일을 12절에 적는다.

## 표시 규칙

- `[측정]` 원자료에서 확인
- `[추론]` 해석
- `[미확인]` 확인 안 함

긴 로그와 원자료는 복사하지 않고 경로만 링크한다. 다른 실험의 `EXPERIMENT.md`를 고칠 때는 그
실험의 결과나 예측을 새로 해석하지 않는다.
