# gin-control pilot 6 (2026-10-27 14:41–14:43, 채점 안 함)

pilot 5의 라이브러리(wp2, gc `54e7ddec`)는 짝 맺은 뒤 9 800 ms가 안 된 "어린 보기"를 분할 막이의 증인에서 뺀다([../../impl/notes_waitpeer.md](../../impl/notes_waitpeer.md) "어린 보기").
두 죽음 셀에서는 둘째 kill이 첫 복원 직후, 즉 되살린 화신의 짝 맺기가 어린 동안에 온다. 이 pilot은 그 셀에서 둘째 판정과 복원이 pilot 3(라이브러리 pf2)보다 늦어지거나 길이 바뀌는지 본 하드웨어 확인이다.
셀은 `mi4_kill2_kill3_ow@gc` n 2, `mi4_train_kill2_kill3@gc` n 1이다. pilot은 본 실험에 들지 않고 채점하지 않는다. 판과 셀 env는 [VERSIONS.md](VERSIONS.md)다.

표시: `[측정]` 원자료에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. 시각은 그 시행의 첫 kill 줄(`GINRS die rank=2`) 뒤 ms이고 rain 시계다(sunny 줄은 meta의 노드 시계 차로 옮김).
사건 목록은 [events/](events/)(만든 스크립트 [twodeath.py](twodeath.py), 요약 [summ.py](summ.py) → [events/summary.txt](events/summary.txt))다. pilot 3의 같은 목록은 그 폴더의 원자료에서 같은 스크립트로 다시 셌다([events/pilot3/](events/pilot3/)).

## 시도

`harness/gpu-initiated/common/cluster_run.sh` 안에서 `chain_gc.sh` → `hold_gc.sh`로 hold `PRC-gc-mi4_kill2_kill3_ow+mi4_kill2_kill3_ow+mi4_train_kill2_kill3` 하나를 돌렸고 STOP 규칙이 켜져 있었다.
시도 1번(한도 4), 클러스터 시간 14:41:18–14:43:30(약 2분 12초, hold 100 s; 한도 1 h) `[측정: chain.out, attempts.txt]`.

- STOP 0, 새 mlx5 커널 줄 0, rain 펌웨어 명령 실패 합 31 그대로, rain mlx5 cmd_err 2 그대로, 남은 프로세스 0, QUERY_QP 상한 넘음 0(`qp_over.txt` 없음) `[측정: a1/snap_*, a1/mlx5_new_PRC.txt]`.
- 세 시행 모두 `r0rc=0 r1rc=0 r2rc=137 r3rc=137 sparerc=0 spare_2ndrc=0`, `wall_s` 11.0 s, 11.1 s, 34.6 s로 끝까지 돌았다 `[측정: a1/run_PRC.out]`.
- 실행기, 채점기, 셀 파일, 라이브러리는 고치지 않았다.

## 시행마다 (4 KiB n 2, 학습 n 1)

| 시행 | 첫 판정(원인, 관측자 시각) | 첫 복원 | 둘째 kill (첫 복원 뒤) | 둘째 판정(원인, 누가, kill 뒤) | 둘째 복원 | 데이터 같음 |
|---|---|---|---|---|---|---|
| 4 KiB n1 | FIN+STALE ×3: r3 20.8, r1 21.0, r0 21.2 | 179.1 ms (`restored` 줄 199.9–200.1) | 1 779.3 (**1 579.2**) | FIN+STALE ×3: r1 20.6, r0 20.9, rank 2 화신 1 22.0 | **172.6 ms** | 1 |
| 4 KiB n2 | FIN+STALE ×3: r3 20.9, r1 20.9, r0 21.1 | 180.8 ms (201.7–202.4) | 1 964.2 (**1 761.8**) | FIN+STALE ×3: r0 21.0, rank 2 화신 1 21.1, r1 21.8 | **175.7 ms** | 1 |
| 학습 n1 | FIN+STALE ×3: r0 20.3, r1 20.6, r3 21.0 | 258.3 ms (278.5) | 8 160.6 (**7 882.1**) | FIN+STALE ×3: r0 20.8, r1 21.0, rank 2 화신 1 21.7 | **277.9 ms** | 1 |

- 복원 시간은 `rows_gc.py`가 원자료에서 다시 셈한 `restore_time_ms_1`, `restore_time_ms_2`(그 죽음의 첫 판정 → 생존 rank의 마지막 게시 줄)다 `[측정: a1/trials.csv]`. "첫 복원 뒤"는 마지막 `restored as incarnation 1` 줄에서 잰다.
- 판정 줄마다 확인 창이 FIN으로 열려 STALE로 닫혔다(READ1 +0.10–0.21 ms, READ2 +10.08–10.24 ms, 판정 표 4행) `[측정: events/]`. 둘째 판정 관측자 셋에 되살린 rank 2 화신 1이 들어 있고, 그 화신이 hold를 세우고(`holds=1 restored=1`) rank 3 복원을 게시했다.
- 세 시행 모두 `second_ok` 1, `reimage_ok` 1, `wait_held` 1, `ow_data_equal` 1, `no_reexec` 1, `win_verified` 1(창 줄 셋, changed=0), `la_qp_err_n` 0, `la_stop_n` 0, `tcp_ctrl_bytes` 0, READ 성공 100 %, `probe_timeout_n` 0이다. r0, r1의 `hold at close`는 `holds=2 restored=2 fallbacks=0 timeouts=0`이다 `[측정]`.
- gin-mirror 규칙의 시행 조건: 다시 이미지 2/2, 둘째 죽음 복원 2/2, 학습 둘째 죽음 1/1. 판정 "틀림"은 gin-mirror의 k(≥ 4)를 n 2, n 1에 댄 것이라 뜻이 없다(pilot 3과 같음) `[측정: mirror_check.txt]`.

## 어린 보기와 막이

**세 시행 모두 둘째 kill 때 rank 3을 보는 보기가 어렸지만, 판정 길과 시각은 바뀌지 않았다** `[측정]`.

| 시행 | rank 2 화신 1이 rank 3을 짝 맺은 뒤(둘째 kill 때) | r0, r1이 rank 3을 짝 맺은 뒤(셋업) |
|---|--:|--:|
| 4 KiB n1 | 1 607 ms (어림) | 4 186 ms (어림) |
| 4 KiB n2 | 1 790 ms (어림) | 4 218 ms (어림) |
| 학습 n1 | 7 908 ms (어림) | 16 699 ms |

- 나이는 `liveness READ QP to rank 3 (re-)paired` 줄에서 둘째 kill까지다. 라이브러리의 원점은 그 짝 맺기 뒤 첫 READ라 probe 한 주기(100 ms) 안에서 더 늦다 `[추론: notes_waitpeer.md 정의]`. "(어림)"은 9 800 ms 미만, 곧 어린 보기다.
  4 KiB 두 시행에서는 생존 관측자 셋 모두의 보기가 어렸다(첫 죽음 때도 셋업 뒤 약 2.4 s라 모두 어렸다).
- 30개 rank와 예비 프로세스 로그 전부에서 `suspected` 0줄, `partition guard` 0줄, `no witness` 0줄, `young` 0줄, `SELF` 0줄, `judged stalled` 0줄, `waiting (peer=` 0줄이다 `[측정: grep]`. 의심 없이 FIN과 확인 창으로 바로 판정됐기 때문에 막이가 결정할 일이 없었다.
- 막이는 GPU 줄과 호스트 박동의 정체 길에만 들어가고 FIN과 확인 창의 길(판정 표 4행)에는 들어가지 않는다 `[소스: pilot 5 PILOT.md "kill과 SIGSTOP", gin_host_gdaki.cc gdakiCtrlRDerive]`. 이번 결과는 그 소스 읽기와 맞는다.

## pilot 3과 비교 (같은 kill 위치, 라이브러리만 다름)

| 무엇 | pilot 3 (pf2, n 2 + n 2) | pilot 6 (wp2, n 2 + n 1) |
|---|---|---|
| 둘째 kill → 둘째 판정, 관측자 사이 | 20.5–21.5 ms (네 시행) | 20.6–22.0 ms (세 시행) |
| 둘째 복원 4 KiB (`restore_time_ms_2`) | 195.6, 172.8 ms | 172.6, 175.7 ms |
| 둘째 복원 학습 | 259.3, 261.0 ms | **277.9 ms** |
| 첫 복원 4 KiB / 학습 | 174.3, 176.6 / 252.2, 249.7 ms | 179.1, 180.8 / 258.3 ms |

`[측정: 두 폴더의 a*/trials.csv와 events/]`

- 4 KiB의 둘째 복원은 pilot 3의 띠(172.8–195.6 ms) 안이다(172.6 ms는 아래 끝보다 0.2 ms 작음).
- **학습의 둘째 복원은 pilot 3의 위 끝보다 16.9 ms 길다.** 나눠 보면(둘째 죽음, events/) kill → 판정 20.8 ms(pilot 3 20.5, 20.7), 판정 → SIGKILL 6.5 ms(6.4, 7.1), FENCED → 마지막 게시 95.8 ms(96.9, 100.0)는 같고,
  **SIGKILL → FENCED가 172.1 ms(153.6, 152.0)로 18.5–20.1 ms 길다.** 첫 죽음도 같은 쪽으로 165.8 ms(159.6, 160.0)다 `[측정]`. 늘어난 몫은 launcher가 잰 학습 프로세스 묶음이 끝나는 시간이고 판정 길이나 막이가 아니다 `[추론]`. 왜 길어졌는지는 보지 않았다 `[미확인]`. 학습 시행은 n 1이다.
- `witness_pairs`는 이번에 6/6이다. pilot 3의 5/6(문제 2)은 그 뒤 채점기 고침 `8be0e543`("witness pairs counted per final-generation incarnation")으로 풀린 것으로 본다 `[측정: trials.csv]`, `[소스: git log rows_gc.py]`.

## 문제 (고치지 않음)

1. **[미확인으로 남음] 어린 보기가 판정을 늦추는 길은 이 셀에서 걸리지 않는다.** 두 죽음 셀은 둘 다 kill이라 FIN 길로 판정된다. pilot 5 문제 2(복원 직후 9.8 s 안에 정체 길로 판정 문턱에 닿는 둘째 장애에서 막이가 증인 없이 SELF가 됨)는 여전히 재지 않았다.
   재려면 첫 kill 복원 뒤 9.8 s 안에 다른 rank를 SIGSTOP이나 GPU hang으로 멈추는 셀이 필요하다(셀 파일에 없음, 결정 필요).
2. **[실행기 쪽, 보고만] 학습 셀의 SIGKILL → FENCED가 pilot 3보다 18.5–20.1 ms 길다**(위). n 1이라 흔들림인지 가르지 못했다.
3. **[채점기, pilot 3 문제 3 그대로] 둘째 죽음의 판정 시각 열이 없다.** 위 둘째 판정 시각은 `twodeath.py`로 로그에서 셌다.

## 하지 않은 것

- 다시 돌린 시도 없음(STOP 0). 시도 3번, 약 58분이 남았다.
- 학습 셀 n2(pilot 3에는 있음; 지시가 n 1).

원자료는 [a1/raw/](a1/raw/)(IPv4 가림, 30개 로그, 합 3.7 MB), 시행 표 [a1/trials.csv](a1/trials.csv)(`rows_gc.py` `47260fee`, 세션 스크래치 사본에서 pilot 표시를 끄고 돌린 pilot 5의 `score_pilot.py`와 같은 방식; 실행 뒤 worktree의 커밋 안 된 남의 수정은 VERSIONS.md), 사슬 기록 [chain.out](chain.out), 시도 기록 [attempts.txt](attempts.txt), hold 출력 [a1/run_PRC.out](a1/run_PRC.out)이다.
IPv4 꼴 0건, 관리망 주소 0건 `[측정: grep]`.
