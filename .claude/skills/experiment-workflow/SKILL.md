---
name: experiment-workflow
description: rdma-error 저장소의 실험 작업 절차. 실험을 새로 시작하거나, 이어서 하거나, 실행 기록이나 결과, QA, 결론을 쓰거나, 어떤 실험의 EXPERIMENT.md를 고칠 때 사용한다. 실험 하나에 EXPERIMENT.md 하나로 기획부터 결론까지 관리한다.
---

# 실험 작업 절차 (single-file)

이 문서는 상태를 넘기는 절차만 적는다. 공통 원칙, 읽는 순서, 표시 규칙, 안전 규칙은 루트
[CLAUDE.md](../../../CLAUDE.md)에, 작성 틀과 고정 절 표시는 [템플릿](../../../docs/templates/EXPERIMENT.md)에,
Git 명령의 세부는 [docs/GIT_WORKFLOW.md](../../../docs/GIT_WORKFLOW.md)에 있다.

## 0. 작업을 시작할 때

1. CLAUDE.md "작업 시작 때 읽는 순서"의 시작 확인을 한다: 머리 표와 맨 앞 현재 상태 안내, 사전 등록 여부,
   안전과 변경 제약, 11절의 해당 항목. 전체를 읽는 것은 사전 등록 검토, 실험 전체 감사, 최종 QA 때다.
2. 사전 등록 태그가 있으면 고정 범위(CLAUDE.md 규칙 2)가 바뀌지 않았는지 저장소 루트에서 확인한다.

   ```
   git diff prereg/<study>-v<n> -- <PREREG.txt에 적힌 파일>   # 빈 출력이어야 함
   sha256sum -c <(grep -v '^#' <폴더>/PREREG.txt)            # sha256sum 형식일 때
   git diff prereg/<study>-v<n> -- <폴더>/EXPERIMENT.md     # 2, 3, 7, 8절에 바뀐 줄이 없어야 함
   ```

   옛 `PREREG.txt`는 형식이 달라 `sha256sum -c`가 읽지 못한다. 그때는 적힌 해시를 `sha256sum <파일>`과 비교한다.

3. 체크아웃 상태를 확인한다. 하나라도 있으면 CLAUDE.md "Git"대로 그 체크아웃에서 브랜치를 바꾸지 않고
   (`git switch`, `git checkout <branch>`, `git reset` 모두), 다른 브랜치 작업은 별도 worktree에서 한다.
   - 실행 중인 프로세스: `pgrep -af cluster_run.sh`, 결과 폴더의 `trials.log`
   - 수정 파일과 untracked 파일: `git status --short --untracked-files=all`
4. 그다음 작업에 닿는 절, 코드, 원자료, 13절의 변경 기록(링크된 `DEVIATIONS.md` 포함)을 읽는다.

## 1. 새 실험 시작 (`DRAFT`)

1. 최신 master에서 새 worktree와 브랜치를 만든다. 현재 체크아웃에서 `git switch -c`로 만들지 않는다.

   ```
   git -C ~/rdma-error fetch origin
   git -C ~/rdma-error worktree add --no-track -b exp/<study> ~/rdma-error-wt/<study> origin/master
   ```

   이후 작업은 모두 `~/rdma-error-wt/<study>` 안에서 한다.
2. 실험 폴더를 정하고 템플릿을 복사한다: `cp docs/templates/EXPERIMENT.md <폴더>/EXPERIMENT.md`.
3. 머리 표, 현재 상태 안내, 1–10절을 채운다. 기존 결과를 쓸 때는 원자료에서 다시 세고, 아니면 `[미확인]`으로
   둔다.
4. 상태 `DRAFT`로 커밋한다. 파일을 하나씩 지정해 `git add`한다. PR을 draft로 연다.
5. 구현, 빌드, smoke, pilot은 `DRAFT`에서 해도 된다. 그 결과는 채점하지 않고, 사전 등록 때 무엇을 보고
   정했는지 12절에 남긴다.

## 2. 사전 등록 (`DRAFT` → `PREREGISTERED`)

사전 등록은 **커밋 하나**로 고정하고, 태그는 **바로 그 커밋**에 단다. 이 단계는 `EXPERIMENT.md` 전체를
읽고 한다.

1. 고정 절을 완성한다: 2절 가설, 3절 예측, 7절 셀과 반복 수, 8절 제외와 중단 기준. 예측이 많으면 표 파일로
   둔다.
2. 같은 작업 안에서 다음을 모두 한다.
   - 머리 표와 현재 상태 안내의 상태를 `PREREGISTERED`로 바꾼다.
   - 12절에 사전 등록 기록을 적는다.
   - 고정할 별도 파일(예측 표, 셀 파일 등)의 sha256을 `PREREG.txt`에 적는다. `EXPERIMENT.md`는 진행 기록이
     계속 바뀌므로 해시 대신 태그로 고정한다.
3. 아직 측정 전인지 확인하고, 위 변경 전부를 **커밋 하나**로 만든다.
4. 그 커밋에 annotated 태그를 달고 push한다.

   ```
   git tag -a prereg/<study>-v<n> -m "<무엇을 고정했나, sha256>" <그 커밋>
   git push origin prereg/<study>-v<n>
   ```

5. 태그 뒤에 상태만 바꾸는 커밋을 따로 만들지 않는다. PR을 rebase로 합치면 master에는 같은 내용의 다른
   커밋이 생기지만 태그는 원래 커밋에 둔다(합친 뒤 확인은 5절).

이후 고정 범위를 바꿀 일이 생기면 13절에 날짜, 이유, 영향 범위, 커밋을 덧붙인다(CLAUDE.md 규칙 2, 3).

## 3. 구현과 실행 (`RUNNING`)

1. 데이터 경로나 판정에 닿는 구현 변경은 사전 등록 뒤라면 13절에 적는다.
2. 빌드만 했으면 "빌드됨"이라고 쓴다. 어디까지 확인했는지(코드 수정 완료, 로컬 검증 완료, 하드웨어 검증
   대기)를 11절 항목에 적는다.
3. smoke 실행은 별도 결과 폴더에 두고 채점에서 뺀다. 사전 등록 뒤라면 13절에도 적는다.
4. 본 실행은 `harness/gpu-initiated/common/cluster_run.sh` 안에서 한다.
5. 진행할 때마다 다음을 함께 갱신한다.
   - 머리 표의 상태와 "마지막 갱신", 맨 앞 현재 상태 안내
   - 11절 작업 목록(지금 할 일은 여기 한 곳)
   - 12절 실행 기록: 한 행에 변경, 검증(무엇을 어디까지), 남은 일, 증거 링크를 짧게
   - 14절 원자료 링크

## 4. QA (`RUNNING` → `QA`)

1. 채점기를 돌려 예측마다 판정, n, 놓친 시행을 얻는다. 사전 등록한 판정 기준을 그대로 쓴다.
2. 핵심 수치를 원자료에서 다시 계산한다. 문서에 이미 적힌 숫자를 옮기지 않는다.
3. n, smoke와 제외 시행의 분리, 여러 실행의 범위와 대표 실행의 범위의 분리를 확인한다(CLAUDE.md 규칙 8, 9).
4. 원자료와 기존 문서가 다르면 원자료를 따르고 충돌을 16절에 적는다.
5. 가능하면 다른 에이전트나 사람이 채점 코드를 보지 않고 독립적으로 다시 센다.

## 5. 완료 (`QA` → `COMPLETE`): 마지막 PR에 모두 넣고 합친다

최종 QA는 `EXPERIMENT.md` 전체와 고정 파일을 읽고 한다. 다음은 모두 **마지막 PR 안에서, 합치기 전에** 한다.
커밋은 내용별로 나눈다(결과 문서, release, 상태).

1. 원자료를 Release에 올리고 `DATA.md`를 갱신한다(`tools/pack_release.py`, GIT_WORKFLOW "What is tracked").
2. 15절 결과 요약(수치마다 n과 근거), 16절 QA, 17절 결론, 18절 한계, 19절 후속 연구를 쓴다.
3. 폴더 README를 형식에 맞게 고치고(CLAUDE.md "README"), 루트 README의 요약과 결과 표에 새 결과를 반영한다.
4. 0절 2의 고정 범위 확인을 PR 머리 커밋에 대해 하고 결과를 12절에 적는다.
5. QA가 끝났으면 머리 표, 현재 상태 안내, 11절을 `COMPLETE`로 바꾼다.
6. PR을 "Rebase and merge"로 합친다. 합친 뒤 `git diff prereg/<study>-v<n> <master 커밋> -- <고정 파일>`로
   다시 확인하고 그 결과를 12절에 적는 짧은 후속 커밋을 PR로 올린다(gin-restore, gin-mirror가 한 방식). 다르면
   고치는 PR을 새로 열고 13절에 적는다.
7. `git worktree remove ~/rdma-error-wt/<study>`로 정리한다.

## 막혔을 때 (`BLOCKED`)

머리 표와 현재 상태 안내의 상태를 `BLOCKED`로 바꾸고, 이유, 풀리는 조건, 그때까지 하지 않을 일을 현재
상태 안내와 12절에 적는다.
