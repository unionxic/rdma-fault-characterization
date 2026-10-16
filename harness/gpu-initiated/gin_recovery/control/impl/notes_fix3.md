# gin-control 1단계 감시 스레드 고침 3 (REVIEW_FIX12_P2B 막는 문제 1–3과 같은 자리의 고칠 것)

기준: 커밋 `2efebe3` "gin-control + 2b"를 `agent_gc_fix3/`에 복사(nccl-src와 빌드 넷, 경로 바꿈). 헤더는 커밋된 헤더 + `rs_ctrl_api_p2b.diff`(트리의 블록과 같아 다시 붙여도 바뀜 없음). 호스트 파일 하나, 장치 코드 0줄. 클러스터, ssh, verbs 장치, GPU 실행 없음. 표시: `[측정]` 돌려서 봄, `[추론]` 해석, `[미확인]` 확인 안 함.

## 걸음 (하나씩, 걸음마다 syn과 unitp1)

1. 막는 문제 3: helper 정체에서 데이터 경로 거부권을 뺌, 시험과 `gc4_helper_freeze12000` 장면 → 통과, 670 158 검사 `[측정: logs_fix3/step1_*.log]`
2. 고칠 것 2: `staleMs` "본 적 없음" 표시값, 분할 막이가 그 k를 쓰지 않음, 장면 → 통과, 670 164 `[측정: step2]`
3. 막는 문제 1, 2(창): REMACC가 창을 정함, 늦은 읽는 쪽, 판정 시각, 한 걸음에 행동 하나, QP 꼴 시험 모형 → 통과, 824 679 `[측정: step3]`
4. 막는 문제 2(넘기기), 고칠 것 1, 4, 9: 펌웨어 명령을 helper로, drain 걸음 기계, hold 시작 뒤 CONNECT 거절 → 첫 판 5 실패(drain을 포기한 QP가 거절 뒤 그대로 남음) → 거절에도 새 QP로 고침 → 통과, 10 248 970 `[측정: step4b, step4]`
5. 고칠 것 3: 연결된 적 없는 세대의 −1을 지움(ring 모형 두 곳), `gc_unit_p2.cc`의 기대값과 장면 → unitp2 첫 판 4 실패(옛 기대 "바뀜마다 −1") → 기대 고침 → 통과 `[측정: step5_unitp2.log]`
6. 싼 nit와 고칠 것 6, 그다음 네 빌드와 검사 전부 → 아래 표

## 항목마다 (고침, 따른 설계 행)

- **막는 문제 1** (설계 4.2 판정 차례 "READ1이나 READ2가 원격 접근 오류면 REMACC", 6행): 두 안 가운데 "READ1의 REMACC로 창이 정해짐"을 골랐다. 차례가 REMACC를 맨 앞에 두므로 READ2는 판정을 바꿀 수 없다. REMACC를 본 창은 READ2를 내지 않고, 그 뒤 QP를 잃는 일(그 오류가 부른 다시 짝 맺기, READ2 flush, hold 시작의 ERR, 거절된 post)이 `countable`을 지우지 않는다(`gdakiCtrlWindowQpLost`). 판정은 그대로 t_F + W. 다시 짝 맺기를 곧바로 해 새 세대에서 READ2를 내는 안은 고르지 않았다(펌웨어 시간이 W/2 안이라는 보장이 없음) `[추론]`.
- **막는 문제 2** (설계 4.2 확인 창, 3.4 표, 4.3 W의 근거): 한 걸음에 창 행동 하나(POST1, POST2, JUDGE가 다른 걸음). 첫 걸음이 t_F + W/2 뒤면 확인 못함(`lateReader`, NORESP 아님). 판정 시각은 max(t_F + W, READ2를 낸 때 + W/2)라서 NORESP는 늘 "W/2 이상 나가 있던 READ가 안 끝남"이다(리뷰의 고침 안 그대로). 창 닫힘 줄에 `step_gap_max_ms`와 `late reader`. drain은 잠 없는 걸음 기계(한 걸음에 poll 한 번, 한도 100 ms, 넘으면 새 QP). 펌웨어 명령(`modify_qp`, QP 만들기와 없애기)은 모두 helper로: 넘기기 `struct gdakiCtrlProbeHand`(NEW → ERR → DRAIN → FW → BACK)가 순수 영역에 있고, FW 동안 감시 스레드는 그 QP를 만지지 않는다. hold 시작의 ERR도 helper가 낸다(`gdakiProbeToErr`).
- **막는 문제 3** (설계 4.2 R (8), (9), 15행): 거부권은 watchBeat 쪽만. `gc4_helper_freeze12000` 장면(4 rank, helperBeat만 12 000 ms 멈춤, watchBeat와 GPU는 돎, 거부권 늘 섬)에서 15행(STALL_HELPER)이 멈춤 뒤 10 000 ms, 옛 규칙이면 끝까지 18행 `[측정: final_unit.log]`.
- **고칠 것 1** (설계 4.4 끝 불변식): hold 시작이 진행 중인 요청을 취소해 "hold started"로 답하고 QP는 ERR에 남는다. CONNECT 때 helper가 계보를 본다(`gdakiLnClassify(…, 화신) == CURRENT`가 아니면 거절, QP는 ERR).
- **고칠 것 2** (설계 3.4 분할 막이): 페이지 낱말 `staleMs[q]`의 "본 적 없음"은 `GDAKI_CTRL_STALE_UNSEEN`(UINT64_MAX), 읽은 쪽은 −1로 두고 막이가 그 k를 건너뛴다. 설계에 올릴 문장: 생존 rank가 넷 가운데 셋이 멈춘 것으로 보이면 읽을 k가 없어 SELF로 영영 판정하지 않는다.
- **고칠 것 3** (설계 2.4 −1의 뜻): 끝 표시에 "연결됐거나 대기열을 버림"을 싣고, 그것도 아니고 바뀐 뒤 받은 기록도 없는 세대는 −1 없이 끝난다. 잃은 지금 세대도 연결된 적 없고 대기열이 비면 −1 없음.
- **고칠 것 9의 두 장면**(열린 창 중 자기 다시 짝 맺기, `hasQp`): 넘기기 장면이 창, `gdakiCtrlProbeIo`, 넘기기, QP 모형을 함께 돌린다. 자기 다시 짝 맺기나 hold 시작 뒤 판정된 창 802개 가운데 NORESP 0, REMACC로 남은 것 174. QP 만들기 실패 10번 모두 답이 갔고, 그 가운데 8번은 뒤 요청이 QP를 만들었다(`hasQp`는 setup 때 고정, 그 상대는 계속 걸음) `[측정]`.
- **싼 nit와 고칠 것 6**: nit 1(자기 화신을 10 ms마다만 읽음), nit 6(SQ가 찬 장면), nit 8(창 READ 성공도 `okGen`), nit 9(hold 시작 때 `preparedGen` 지움), 고칠 것 6(`NCCL_GIN_CTRL_PAGE=1`인데 감시 스레드가 없으면 WARN과 함께 페이지 끔). nit 3, 4, 10은 남김.

## 수 (한 실행, rdma 빌드, `logs_fix3/final_unit.log`) `[측정]`

| 시험 | n |
|---|---|
| `gc_unit_p1` | 검사 10 248 976, 실패 0 (전에 669 740) |
| 창 장면(QP 모형, 늦고 서는 읽는 쪽) | 20 000: 살아 있음 4 866, STALE 821, NORESP 7 602, REMACC 1 185, 확인 못함 5 526; 늦은 읽는 쪽 1 653 모두 확인 못함; 걸음 간격 > W/4인 살아 있는 상대 3 873, NORESP 0; READ1 REMACC로 정해진 창 898 |
| 넘기기 장면 | 3 000 실행(hold 시작이 CONNECT 요청 바로 뒤 751); 답 23 154; 계획 재사용 11 566, 리셋 10 585, drain 1 038; drain 포기 130; 거절 hold 11, 계보 3 361; 감시 스레드 펌웨어 0, FW 중 접근 0, 잡힌 화신으로 RTS 0; 가장 느린 답 161 ms |
| `gc_unit_p2` | 검사 3 993 471, 실패 0; credit 110 바뀜에서 −1 220(쪽마다 연결된 세대마다 하나), 다시 시작 장면 −1 쪽마다 1 |

## 검사

| 검사 | 결과 | 근거 |
|---|---|---|
| `api` | 통과 | `logs_fix3/final_api.log` |
| `syn` | 통과, 경고 0 | `final_syn.log` |
| 빌드 gc, gcp, gct, gctp | 빌드됨, 경고 0. libnccl `a97b7d77`, `609d839c`, `939067c9`, `abdd26ff` | `final_g*.log` |
| `pre` | gct 0 hunk, gctp 0 hunk, gctc 2 hunk 3줄(RST 간격, 그대로) | `final_pre.log` |
| `sites` | 통과, MISMATCH 0, `#if NCCL_GIN_CTRL_TCP` 갈래 39개 ln4 글 그대로 | `final_sites.log` |
| `unit` 두 빌드 | 통과(위 수; tcp는 1단계 0 검사) | `final_unit.log` |
| `ident` | 프로그램 16/16 같음, 장치 객체 207 × 4 빌드 SASS와 바이트 같음, 자원 같음 | `final_ident2.log` (첫 판 `final_ident.log`는 디스크가 찼을 때 돌아 SASS 차 56–43이 났지만 객체 바이트는 207 같음; 다시 돌린 판을 씀) |
| `diff` | `gc_layer_fix3.diff` `2f469461`, 839줄, hunk 28, 호스트 파일 하나 | `final_diff.log` |

## 합칠 때 볼 것

1. `gc_unit_p2.cc`도 바꿨다(−1 기대값과 `testRestart`). 2a-2가 고정해 둔 옛 `gc_unit_p2.cc`는 이 트리에서 4 실패한다: 이쪽을 받는다.
2. ring 모형의 두 hunk(`gdakiCtrlRingNewGen`의 끝 표시 `ackSeq`, `gdakiCtrlRingPop`)는 "[2] ring" 영역이다. 2a-2의 링 만들기와 글자로 겹치는지 본다.
3. `GDAKI_CTRL_PO_*`를 순수 영역으로 옮겼다. `gdakiCtrlProbeAsk/Answer`는 그대로이나 Answer가 helper의 펌웨어를 돈다: 2a-2의 UD 링크도 helper에서만 부른다. 요청 하나가 drain 한도(100 ms)와 걸음만큼 걸릴 수 있어 링크의 50 ms 기다림(고칠 것 5)이 그대로 열려 있다.
4. 판정 시각이 max(t_F + W, READ2 + W/2)가 됐다: 설계 4.2 "판정은 늘 t_F + W" 문장과 4.6 예측을 고칠 때 READ2를 낸 걸음의 지연만큼 늦음을 적는다 `[추론: 보통 1 ms 안]`.
5. 줄: probe summary에 `helper_fw watch_fw=0 drain_giveup refused_hold refused_lineage`, 창 닫힘 줄에 `step_gap_max_ms`와 `late reader`. `rows_gc.py`와 9.8절 표는 아직 맞추지 않았다(고칠 것 7).
6. 작업 중 worktree의 `gc_sites.tsv`가 다른 에이전트 손으로 바뀌어 있었다. 이 작업은 고치지 않았고 `sites`는 고정본(`agent_gc_fix3/pin/`)으로 돌렸다.
7. 모든 것이 CPU 모형이다. 장치에서는 한 번도 돌지 않았다 `[미확인]`.
