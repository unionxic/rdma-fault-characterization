# gin-control 채점 결과 (시험 쪽)

`score_gc.py`가 원자료에서 만들었다. 손으로 고친 값은 없다. 판정식 원문은 `predictions_gc.csv`, 문법은 gin-mirror의 `score.py`(s2_close 3.2)와 이 파일 머리의 꼴이다.

- 예측 파일 sha256: `de6bf8ec70ca7cb16818be540fb530c12be576f73d186c436874703aa72ce4a8`. `PREREG.txt`의 값과 다르다(사전 등록한 파일이 아니거나 아직 사전 등록 전).
- 시행 수: 3. 판정한 시행: 3. smoke: 0, pilot: 0(따로 셈, 채점 안 함).
- STOP 파일: 없음.
- `(STOP_launcher)`와 `(STOP_launcher: …)` 줄(launcher 로그와 rank, 예비 프로세스 로그; rank 쪽의 launcher Unix 소켓 끊김 줄 0개 포함; 8절 채점 규칙, FENCE_NAK 포함): 0줄, 시행 없음.
- 링이 live가 되지 않은 시행(REVIEW_INT3 F7; 설정 탓이면 config 제외, 아니면 준비 실패로 셈): 0개.
- 준비 실패(설정이 맞는데 Resume 거절이나 링 live 실패; 계획 n 안의 자리를 차지하고 채우지 않음; Codex 리뷰 4): 0개.
- 예비 프로세스 없음 셀의 예상된 다시 띄우기 한도 줄(실행기가 끝낸 예비 프로세스를 launcher가 다시 띄우지 않음; STOP으로 세지 않음): 1줄.
- launcher가 뜨지 않았거나 낡은 launcher 소켓이나 프로세스가 남아 돌지 않은 시행(8절, STOP_launcher): 없음.

## 판정 요약

안전 예측(kind safety)은 판정한 시행에서 실패 0일 때만 맞음, 성능 예측(perf)은 판정식의 문턱 그대로다(Codex 리뷰 5). 다만 성능 예측의 판정식 안의 안전성 항(`data_equal`, `ow_data_equal`, `no_reexec`, `rec_lost_n`, `rec_dup_n`, `rejoin_accept_dup_n`, `fence_order_ok`, `fence_names_ok`, `win_verified`, `win_changed_after`, `wait_held`, `revived_done`, `subject_fenced`)이 판정한 시행 하나에서라도 거짓이면 그 예측은 문턱과 상관없이 재검토(안전성 항 어긋남 k/n)다(8절, 2026-10-23). 안전성 항은 그 항이 지키는 동작(펜스, 복원)이 있었던 시행에서만 보고, 복원 시도 없이 fallback으로 끝난 시행은 성능 실패로만 센다(fallback(복원 없음), 8절, 2026-10-27). 판정식이 읽는 필수 요약 열(제어 요약, READ 요약)이 빈 시행은 그 예측에서 자료 부족 시행이다(통과도 실패도 아님). 판정은 나머지 시행으로 사전 등록 문턱 k에 견주고(`>= N_SCORED`의 k는 계획 n), 자료 있는 시행이 k보다 적으면 자료 부족(n<k)이다(8절, 2026-10-23, 2026-10-27).

| 예측 | 종류 | 셀 | n | 판정 |
|---|---|---|--:|---|
| kill의 죽음 판정이 FIN 하나에 기대지 않고 1 s 안 (kill_judge_rdma) | perf | `gc4_kill3_ow@gc`, `mi4_kill3_ow@gc`, `mi4_kill1_ow@gc`, `mi4_kill3_ckpt_ow@gc`, `mi4_seg_4k@gc`, `mi4_seg_32k@gc`, `mi4_seg_128k@gc`, `mi4_pull@gc`, `rs4_kill3_mion@gc` | 0 / 0 / 0 / 0 / 0 / 0 / 0 / 0 / 0 | 자료 부족 |
| RST로 죽어도 1 s 늦지 않음(rdma) (rst_judge_rdma) | perf | `gc4_rst_kill3@gc` | 0 | 자료 부족 |
| 살아 있는 상대의 RST와 포트 닫힘은 rdma에서 판정 없음 (rstgap_live_rdma) | safety | `gc4_rstgap_live300@gc` | 0 | 자료 부족 |
| FIN 없는 죽음, launcher 보고 (finless_exit_report) | perf | `gc4_fdhold_sock_kill3@gc` | 0 | 자료 부족 |
| FIN 없는 죽음, READ 실패 (finless_read_fail) | perf | `gc4_kill3_noreport_nofdhold@gc` | 0 | 자료 부족 |
| fd 보관 자식이 물려받은 매핑으로 죽은 rank의 자원을 쥔 죽음은 호스트 박동 멈춤으로 판정 (fdhold_sock_helper_stall) | perf | `gc4_fdhold_sock_kill3_noreport@gc` | 0 | 자료 부족 |
| 자식이 uverbs fd까지 쥐면 거절만 (fdhold_uverbs_refuse) | safety | `gc4_fdhold_uverbs_kill3@gc` | 1 | 자료 부족(n<k) |
| 짧은 멈춤은 투명 (stop_transparent) | perf | `gc4_stop1500@gc`, `gc4_stop4000@gc`, `gc4_stop8000@gc` | 0 / 0 / 0 | 자료 부족 |
| 느린 상대는 판정 없음 (slow_no_judge) | safety | `gc4_slow_duty@gc` | 0 | 자료 부족 |
| 긴 멈춤은 펜스 뒤 복원 (stall_fence_restore) | perf | `gc4_stop12000_fence@gc` | 0 | 자료 부족 |
| 긴 멈춤, 펜스 끔 (stall_none_refuse) | safety | `gc4_stop12000_none@gc` | 1 | 자료 부족(n<k) |
| 살아서 도는 프로세스의 펜스 (freeze_fence_restore) | perf | `gc4_freeze12000_fence@gc` | 0 | 자료 부족 |
| helper만 멈춘 rank의 펜스 (helper_stall_fence) | perf | `gc4_helper_freeze12000@gc` | 0 | 자료 부족 |
| 멈춘 GPU의 펜스(호스트는 삶) (gpuhang_fence_restore) | perf | `gc4_gpuhang12000_fence@gc`, `gc4_gpuhang12000_waitpend_fence@gc` | 0 / 0 | 자료 부족 |
| 문맥 0 밖 GPU 멈춤의 펜스(반례) (gpuhang_ctx1_fence_restore) | perf | `gc4_gpuhang12000_ctx1_fence@gc` | 0 | 자료 부족 |
| 조용한 긴 계산은 판정하지 않음(반례) (quiet_compute_no_judge) | safety | `gc4_quiet12000@gc` | 0 | 자료 부족 |
| 멈춘 rank를 기다리는 정상 rank는 판정하지 않음(의존 대기자 규칙) (waiter_not_judged) | safety | `gc4_gpuhang12000_waitpend_fence@gc` | 0 | 자료 부족 |
| 관리망 끊김의 투명 (mgmt_mute_transparent) | perf | `gc4_mgmt_mute8@gc` | 0 | 자료 부족 |
| 같은 끊김의 옛 길 (mgmt_mute_tcp) | safety | `gct4_mgmt_mute8@gct` | 0 | 자료 부족 |
| 기록 QP 오류의 다시 짝 맺기 (qp_err_repair) | perf | `gc4_qperr_record@gc` | 0 | 자료 부족 |
| 잃은 REJOIN datagram (ud_drop_rejoin) | safety | `gc4_ud_drop_rejoin@gc` | 0 | 자료 부족 |
| credit 멈춤에도 기록 잃음 없음 (credit_stall_no_loss) | safety | `gc4_credit_stall@gc` | 0 | 자료 부족 |
| 무장됐으나 활성화 때 예비 프로세스가 없음의 곧바른 fallback (spare_absent_refused) | perf | `gc4_kill3_ow_spareabsent@gc` | 1 | 자료 부족(n<k) |
| 증인 없는 kill (kill_no_witness) | perf | `gc4_kill3_ow_nowitness@gc` | 0 | 자료 부족 |
| 복원 시간과 관문(rdma 빌드의 gin-mirror 한 죽음 복원 셀, 증인 켬) (restore_time_rdma) | perf | `mi4_kill3_ow@gc`, `mi4_kill1_ow@gc`, `mi4_kill3_ckpt_ow@gc`, `mi4_seg_4k@gc`, `mi4_seg_32k@gc`, `mi4_seg_128k@gc`, `mi4_pull@gc`, `rs4_kill3_mion@gc`, `mi4_train_kill3@gc` | 0 / 0 / 0 / 0 / 0 / 0 / 0 / 0 / 0 | 자료 부족 |
| 장애 없음: 생존 확인이 조용함 (none_probe_clean) | perf | `gc4_none_probe@gc`, `gc4_none_ow@gc`, `mi4_train_none@gc` | 0 / 0 / 0 | 자료 부족 |
| 제어가 관리망에 없음 (no_tcp_control) | safety | `gc4_none_ow@gc`, `gc4_none_probe@gc`, `build:gc` | 0 / 0 / 3 | 자료 부족 |
| 상태 페이지 READ의 비용 (cost_probe_lat4k) | cost | `cost:probe:probe-on:lat4k` | - | 자료 부족 |
| 긴 hold의 lane(사용자 결정 14: 문서화한 한계) (long_hold_lane) | safety | `build:gc` | 3 | 자료 없음(실패 아님) |
| FENCED 관문은 마지막 thread를 기다림 (gate_fenced) | safety | `local:gate_fenced` | 0 | 자료 부족 |
| 회귀(tcp 빌드, 대조 셀 하나) (regression_tcp) | perf | `mirror:ow_wait_held,ow_data_equal,ow_no_reexec,ow_revived_done,ow_suppress_exact,ow_from_pool,ow_restore_time@gct` | - | 자료 부족 |
| 회귀(rdma 빌드, 제어와 무관한 예측) (regression_rdma) | perf | `mirror:ow_wait_held,ow_data_equal,ow_no_reexec,ow_revived_done,ow_suppress_exact,ow_from_pool,ckpt_kill_ow,kill_other_ow,reimage_after_restore,second_death_restored,train_data_equal,train_second_death@gc` | - | 자료 부족 |
| 회귀(rdma 빌드, mirror 끈 길이 RDMA 저장소로) (regression_rdma_mirror_off) | safety | `mirror:rg_data_equal,rg_no_reexec@gc`, `rs4_kill3@gc`, `rs4_kill3_ckpt@gc`, `rs4_kill1@gc`, `rs4_none@gc` | 0 / 0 / 0 / 0 | 자료 부족 |

## 예측별 세부

### kill_judge_rdma: 자료 부족

- 판정식: `gc4_kill3_ow@gc: count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))) >= 9 ;; mi4_kill3_ow@gc: count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))) >= 9 ;; mi4_kill1_ow@gc: count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))) >= 4 ;; mi4_kill3_ckpt_ow@gc: count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))) >= 4 ;; mi4_seg_4k@gc: count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))) >= 4 ;; mi4_seg_32k@gc: count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))) >= 4 ;; mi4_seg_128k@gc: count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))) >= 4 ;; mi4_pull@gc: count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))) >= 4 ;; rs4_kill3_mion@gc: count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))) >= 4`
- 표시: 셀마다 따로 k = n − 1(n 10은 9, n 5는 4; 리뷰 D7, 2026-10-24 pilot 2 뒤 확정). 노드 사이 간격은 실행기가 잰 시계 차로 바꾼 mono(kill_judge_clock). W 20 ms(2026-10-24 pilot 1). pilot 2의 증인 켠 kill 시행 20개 모두 FIN+STALE, kill → 판정 20.462–22.824 ms [측정: results/20261023_pilot2/PILOT.md, n 1씩, 채점 아님]. EXITED 띠 40–200 ms: pilot 1, 2와 smoke 3, 4, 6의 launcher 보고 판정 60.8, 62, 77, 102–106, 110.9, 127, 129.5 ms를 덮음(finless_exit_report와 같은 근거)
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_kill3_ow@gc, mi4_kill3_ow@gc, mi4_kill1_ow@gc, mi4_kill3_ckpt_ow@gc, mi4_seg_4k@gc, mi4_seg_32k@gc, mi4_seg_128k@gc, mi4_pull@gc, rs4_kill3_mion@gc
- `gc4_kill3_ow@gc`: 판정한 시행 0회, 대입한 식 `0 >= 9` → 거짓
  - `count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200)))` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 9 → 자료 부족(n<k)
- `mi4_kill3_ow@gc`: 판정한 시행 0회, 대입한 식 `0 >= 9` → 거짓
  - `count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200)))` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 9 → 자료 부족(n<k)
- `mi4_kill1_ow@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200)))` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `mi4_kill3_ckpt_ow@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200)))` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `mi4_seg_4k@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200)))` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `mi4_seg_32k@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200)))` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `mi4_seg_128k@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200)))` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `mi4_pull@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200)))` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `rs4_kill3_mion@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200)))` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_kill3_ow@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))` | 0/0 | 0/0 |
| `mi4_kill3_ow@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))` | 0/0 | 0/0 |
| `mi4_kill1_ow@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))` | 0/0 | 0/0 |
| `mi4_kill3_ckpt_ow@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))` | 0/0 | 0/0 |
| `mi4_seg_4k@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))` | 0/0 | 0/0 |
| `mi4_seg_32k@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))` | 0/0 | 0/0 |
| `mi4_seg_128k@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))` | 0/0 | 0/0 |
| `mi4_pull@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))` | 0/0 | 0/0 |
| `rs4_kill3_mion@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and weak_cause_n == 0 and n_judge_confirm + n_judge_exited == n_judge and (n_judge_confirm == 0 or (0 <= fin_judge_dev_min_ms and fin_judge_dev_max_ms <= 2)) and (n_judge_exited == 0 or (40 <= kill_judge_exited_min_ms and kill_judge_exited_max_ms <= 200))` | 0/0 | 0/0 |

### rst_judge_rdma: 자료 부족

- 판정식: `count(n_rst_surv >= 1 and weak_cause_n == 0 and n_rst_confirm + n_rst_exited == n_rst_surv and (n_rst_confirm == 0 or (0 <= rst_judge_dev_min_ms and rst_judge_dev_max_ms <= 2)) and (n_rst_exited == 0 or (40 <= rst_exited_kill_judge_min_ms and rst_exited_kill_judge_max_ms <= 200)) and wait_held == 1 and ow_data_equal == 1 and revived_done == 1) >= 9`
- 표시: n_rst_surv >= 1(RST 줄이 하나도 없으면 이 셀의 주입이 시험되지 않음)은 이 파일이 더한 조건이다
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_rst_kill3@gc
- `gc4_rst_kill3@gc`: 판정한 시행 0회, 대입한 식 `0 >= 9` → 거짓
  - `count(n_rst_surv >= 1 and weak_cause_n == 0 and n_rst_confirm + n_rst_exited == n_rst_surv and (n_rst_confirm == 0 or (0 <= rst_judge_dev_min_ms and rst_judge_dev_max_ms <= 2)) and (n_rst_exited == 0 or (40 <= rst_exited_kill_judge_min_ms and rst_exited_kill_judge_max_ms <= 200)) and wait_held == 1 and ow_data_equal == 1 and revived_done == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 9 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_rst_kill3@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_rst_surv >= 1 and weak_cause_n == 0 and n_rst_confirm + n_rst_exited == n_rst_surv and (n_rst_confirm == 0 or (0 <= rst_judge_dev_min_ms and rst_judge_dev_max_ms <= 2)) and (n_rst_exited == 0 or (40 <= rst_exited_kill_judge_min_ms and rst_exited_kill_judge_max_ms <= 200)) and wait_held == 1 and ow_data_equal == 1 and revived_done == 1` | 0/0 | 0/0 |

### rstgap_live_rdma: 자료 부족

- 판정식: `count(judge_any_n == 0 and decline_n == 0) >= 5`
- 표시: 2026-10-28 사용자 결정(EXPERIMENT 12절 그날 "kind 경계 행과 부하 셀" 행): kind perf → safety(규칙이 판정 0과 데이터 같음뿐이라 quiet_compute_no_judge, waiter_not_judged와 같은 꼴; 규칙, 셀, n, k는 그대로)
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_rstgap_live300@gc
- `gc4_rstgap_live300@gc`: 판정한 시행 0회, 대입한 식 `0 >= 5` → 거짓
  - `count(judge_any_n == 0 and decline_n == 0)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 5 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_rstgap_live300@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `judge_any_n == 0 and decline_n == 0` | 0/0 | 0/0 |

### finless_exit_report: 자료 부족

- 판정식: `count(n_judge == n_surv and n_judge_exited == n_judge and 40 <= kill_judge_ms_min and kill_judge_ms_max <= 200 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1) >= 9`
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_fdhold_sock_kill3@gc
- `gc4_fdhold_sock_kill3@gc`: 판정한 시행 0회, 대입한 식 `0 >= 9` → 거짓
  - `count(n_judge == n_surv and n_judge_exited == n_judge and 40 <= kill_judge_ms_min and kill_judge_ms_max <= 200 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 9 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_fdhold_sock_kill3@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and n_judge_exited == n_judge and 40 <= kill_judge_ms_min and kill_judge_ms_max <= 200 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1` | 0/0 | 0/0 |

### finless_read_fail: 자료 부족

- 판정식: `count(n_judge == n_surv and n_judge_noresp == n_judge and 3500 <= kill_judge_ms_min and kill_judge_ms_max <= 4500 and timeout_judge_n == 0 and probe_timeout_n >= 1 and fence_names_ok == 1 and fence_order_ok == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1) >= 4`
- 표시: '곧바로 FENCED'는 수치가 없어 보고 열 fence_sent_to_fenced_ms로만 둔다
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_kill3_noreport_nofdhold@gc
- `gc4_kill3_noreport_nofdhold@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and n_judge_noresp == n_judge and 3500 <= kill_judge_ms_min and kill_judge_ms_max <= 4500 and timeout_judge_n == 0 and probe_timeout_n >= 1 and fence_names_ok == 1 and fence_order_ok == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_kill3_noreport_nofdhold@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and n_judge_noresp == n_judge and 3500 <= kill_judge_ms_min and kill_judge_ms_max <= 4500 and timeout_judge_n == 0 and probe_timeout_n >= 1 and fence_names_ok == 1 and fence_order_ok == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1` | 0/0 | 0/0 |

### fdhold_sock_helper_stall: 자료 부족

- 판정식: `count(n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= kill_judge_ms_min and kill_judge_ms_max <= 10500 and probe_fail_n == 0 and fence_names_ok == 1 and fence_order_ok == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1) >= 4`
- 표시: READ 시한 줄(probe_timeout_n)은 보고만; 띠 10 000–10 500 ms는 2026-10-24 pilot 2 뒤 확정(pilot 1 a5, smoke 4 a4, smoke 5 a3, a4의 kill → 판정 10 025.2–10 094.9 ms, n 4, 채점 아님)
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_fdhold_sock_kill3_noreport@gc
- `gc4_fdhold_sock_kill3_noreport@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= kill_judge_ms_min and kill_judge_ms_max <= 10500 and probe_fail_n == 0 and fence_names_ok == 1 and fence_order_ok == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_fdhold_sock_kill3_noreport@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= kill_judge_ms_min and kill_judge_ms_max <= 10500 and probe_fail_n == 0 and fence_names_ok == 1 and fence_order_ok == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1` | 0/0 | 0/0 |

### fdhold_uverbs_refuse: 자료 부족(n<k)

- 판정식: `count(n_judge + n_judge_taken == n_surv and n_judge_exited + n_judge_stall_helper + n_judge_stall == n_judge and restore_count == 0 and decline_n >= 1 and surv_released == n_surv) >= 4`
- 표시: 'fail-fast로 끝남'을 모든 생존 rank의 대기가 풀림(surv_released == n_surv)으로 읽었다; 박동 정체 길의 원인(STALL_HELPER 또는 STALL)은 3절이 [미확인]으로 적어 둘 다 조건에 넣었다
- `gc4_fdhold_uverbs_kill3@gc`: 판정한 시행 1회, 대입한 식 `1 >= 4` → 거짓
  - `count(n_judge + n_judge_taken == n_surv and n_judge_exited + n_judge_stall_helper + n_judge_stall == n_judge and restore_count == 0 and decline_n >= 1 and surv_released == n_surv)` = 1/1. 만족하지 않은 시행: 없음
  - 채점 n 1, 자료 부족 n 0, 자료 있는 n 1, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_fdhold_uverbs_kill3@gc` | 1 | 1 | 0 | 0 | 1 | 0 | `n_judge + n_judge_taken == n_surv and n_judge_exited + n_judge_stall_helper + n_judge_stall == n_judge and restore_count == 0 and decline_n >= 1 and surv_released == n_surv` | 1/1 = 100.0 % | 1/1 = 100.0 % |

### stop_transparent: 자료 부족

- 판정식: `gc4_stop1500@gc: count(judge_any_n == 0 and data_equal == 1 and ow_data_equal == 1) >= 9 ;; gc4_stop4000@gc: count(judge_any_n == 0 and data_equal == 1 and ow_data_equal == 1 and suspect_n >= 1 and 2000 <= suspect_stale_ms_min and suspect_stale_ms_max <= 2200) >= 9 ;; gc4_stop8000@gc: count(judge_any_n == 0 and data_equal == 1 and ow_data_equal == 1 and suspect_n >= 1 and 2000 <= suspect_stale_ms_min and suspect_stale_ms_max <= 2200) >= 9`
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_stop1500@gc, gc4_stop4000@gc, gc4_stop8000@gc
- `gc4_stop1500@gc`: 판정한 시행 0회, 대입한 식 `0 >= 9` → 거짓
  - `count(judge_any_n == 0 and data_equal == 1 and ow_data_equal == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 9 → 자료 부족(n<k)
- `gc4_stop4000@gc`: 판정한 시행 0회, 대입한 식 `0 >= 9` → 거짓
  - `count(judge_any_n == 0 and data_equal == 1 and ow_data_equal == 1 and suspect_n >= 1 and 2000 <= suspect_stale_ms_min and suspect_stale_ms_max <= 2200)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 9 → 자료 부족(n<k)
- `gc4_stop8000@gc`: 판정한 시행 0회, 대입한 식 `0 >= 9` → 거짓
  - `count(judge_any_n == 0 and data_equal == 1 and ow_data_equal == 1 and suspect_n >= 1 and 2000 <= suspect_stale_ms_min and suspect_stale_ms_max <= 2200)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 9 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_stop1500@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `judge_any_n == 0 and data_equal == 1 and ow_data_equal == 1` | 0/0 | 0/0 |
| `gc4_stop4000@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `judge_any_n == 0 and data_equal == 1 and ow_data_equal == 1 and suspect_n >= 1 and 2000 <= suspect_stale_ms_min and suspect_stale_ms_max <= 2200` | 0/0 | 0/0 |
| `gc4_stop8000@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `judge_any_n == 0 and data_equal == 1 and ow_data_equal == 1 and suspect_n >= 1 and 2000 <= suspect_stale_ms_min and suspect_stale_ms_max <= 2200` | 0/0 | 0/0 |

### slow_no_judge: 자료 부족

- 판정식: `count(suspect_n == 0 and judge_any_n == 0) >= 5`
- 표시: 2026-10-28 사용자 결정(EXPERIMENT 12절 그날 "kind 경계 행과 부하 셀" 행): kind perf → safety(규칙이 판정 0과 데이터 같음뿐이라 quiet_compute_no_judge, waiter_not_judged와 같은 꼴; 규칙, 셀, n, k는 그대로)
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_slow_duty@gc
- `gc4_slow_duty@gc`: 판정한 시행 0회, 대입한 식 `0 >= 5` → 거짓
  - `count(suspect_n == 0 and judge_any_n == 0)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 5 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_slow_duty@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `suspect_n == 0 and judge_any_n == 0` | 0/0 | 0/0 |

### stall_fence_restore: 자료 부족

- 판정식: `count(n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10300 and judge_spread_ms <= 200 and fence_order_ok == 1 and fence_names_ok == 1 and judge_to_publish_ms <= 1500 and cont_target_present == 0 and win_verified == 1 and ow_data_equal == 1) >= 9`
- 표시: 9.9절 끝의 채점하지 않는 pilot 셀 gc4_stop12000_pilot은 pilot 1 a6에서 한 번 돎: 12 000 ms 멈춤 셋(a3 펜스, a3 펜스 끔, a6 pilot)에서 생존 rank가 판정(10 005–10 089 ms)까지 hold 한도 줄 없이 기다렸고 a6은 판정 뒤 거절, xchg=released [측정: results/20261023_pilot1/PILOT.md 9.9절 끝의 물음, n 1씩, 채점 아님]. 이 셀의 사전 등록은 그 pilot 셀에 기대지 않음(셀, 띠, k는 2026-10-24 pilot 2 뒤 확정 그대로; 2026-10-27 사전 등록 전 kind 확인에서 이 메모를 정리). 10–12 s 장치 대기를 n 1씩만 본 것은 받아들인 한계(9.9절 끝, 18절)
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_stop12000_fence@gc
- `gc4_stop12000_fence@gc`: 판정한 시행 0회, 대입한 식 `0 >= 9` → 거짓
  - `count(n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10300 and judge_spread_ms <= 200 and fence_order_ok == 1 and fence_names_ok == 1 and judge_to_publish_ms <= 1500 and cont_target_present == 0 and win_verified == 1 and ow_data_equal == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 9 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_stop12000_fence@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10300 and judge_spread_ms <= 200 and fence_order_ok == 1 and fence_names_ok == 1 and judge_to_publish_ms <= 1500 and cont_target_present == 0 and win_verified == 1 and ow_data_equal == 1` | 0/0 | 0/0 |

### stall_none_refuse: 자료 부족(n<k)

- 판정식: `count(n_judge_stall_helper >= 1 and decline_n >= 1 and surv_released >= n_surv and subject_fenced == 0) >= 4`
- `gc4_stop12000_none@gc`: 판정한 시행 1회, 대입한 식 `1 >= 4` → 거짓
  - `count(n_judge_stall_helper >= 1 and decline_n >= 1 and surv_released >= n_surv and subject_fenced == 0)` = 1/1. 만족하지 않은 시행: 없음
  - 채점 n 1, 자료 부족 n 0, 자료 있는 n 1, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_stop12000_none@gc` | 1 | 1 | 0 | 0 | 1 | 0 | `n_judge_stall_helper >= 1 and decline_n >= 1 and surv_released >= n_surv and subject_fenced == 0` | 1/1 = 100.0 % | 1/1 = 100.0 % |

### freeze_fence_restore: 자료 부족

- 판정식: `count(n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10300 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and win_verified == 1 and ow_data_equal == 1) >= 4`
- 표시: 시작 시각은 라이브러리의 FREEZE_PAGE 줄(멈춤 시작); 2026-10-24부터 셀 값 FREEZE_PAGE=12000@2000으로 무장 2 s 뒤 시작하고 줄은 그 실제 시작 때 나므로 기준은 그대로 그 줄
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_freeze12000_fence@gc
- `gc4_freeze12000_fence@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10300 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and win_verified == 1 and ow_data_equal == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_freeze12000_fence@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10300 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and win_verified == 1 and ow_data_equal == 1` | 0/0 | 0/0 |

### helper_stall_fence: 자료 부족

- 판정식: `count(n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10300 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and win_verified == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1) >= 4`
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_helper_freeze12000@gc
- `gc4_helper_freeze12000@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10300 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and win_verified == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_helper_freeze12000@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and n_judge_stall_helper == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10300 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and win_verified == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1` | 0/0 | 0/0 |

### gpuhang_fence_restore: 자료 부족

- 판정식: `per cell: count(n_judge == n_surv and n_judge_stall == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10500 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and fence_order_ok == 1 and win_verified == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1) >= 4`
- 표시: 시작 시각은 driver의 GINRS gpuhang 줄(spin=1); GC_GPUHANG_IT 155 그대로. 띠 10 000–10 500 ms는 2026-10-24 pilot 2 뒤 확정(pilot 1, smoke 4, 6의 GPU hang 시행 다섯 hang 줄 → 판정 10 028.9–10 086.8 ms, 채점 아님); 2026-10-27: 셀 B를 더함. 2026-10-27 pilot 5 뒤: 의존 대기자 규칙에서 rank 1은 판정되지 않으므로(waiter_not_judged) 셀 B의 이 행은 기다리는 정상 rank가 있어도 rank 3이 펜스되고 복원되는지를 잰다(옛 규칙의 pilot 4는 0/2 fallback). 일반 count는 첫 셀만 보므로(score_gc.eval_part의 keys[:1]) per cell 꼴로 두 셀 모두 채점한다
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_gpuhang12000_fence@gc, gc4_gpuhang12000_waitpend_fence@gc
- `gc4_gpuhang12000_fence@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and n_judge_stall == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10500 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and fence_order_ok == 1 and win_verified == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `gc4_gpuhang12000_waitpend_fence@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and n_judge_stall == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10500 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and fence_order_ok == 1 and win_verified == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_gpuhang12000_fence@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and n_judge_stall == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10500 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and fence_order_ok == 1 and win_verified == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1` | 0/0 | 0/0 |
| `gc4_gpuhang12000_waitpend_fence@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and n_judge_stall == n_judge and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10500 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and fence_order_ok == 1 and win_verified == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1` | 0/0 | 0/0 |

### gpuhang_ctx1_fence_restore: 자료 부족

- 판정식: `count(n_judge == n_surv and n_judge_stall == n_judge and stall_ctx == 1 and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10500 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and fence_order_ok == 1 and win_verified == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1) >= 4`
- 표시: 시작 시각은 driver의 GINRS gpuhang 줄(spin=1 ctx=1); stall_ctx는 라이브러리의 판정 줄이나 의심 줄의 ctx=에서 읽음; GC_GPUHANG_IT 155 그대로. 띠 10 000–10 500 ms는 2026-10-24 pilot 2 뒤 확정(GPU hang 시행 다섯 10 028.9–10 086.8 ms, 그 가운데 이 셀 pilot 1과 smoke 6 a5 10 028.9–10 034.3 ms, 채점 아님)
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_gpuhang12000_ctx1_fence@gc
- `gc4_gpuhang12000_ctx1_fence@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and n_judge_stall == n_judge and stall_ctx == 1 and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10500 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and fence_order_ok == 1 and win_verified == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_gpuhang12000_ctx1_fence@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and n_judge_stall == n_judge and stall_ctx == 1 and 10000 <= stop_judge_ms_min and stop_judge_ms_max <= 10500 and la_fence_sigkill_n >= 1 and la_fenced_n >= 1 and fence_order_ok == 1 and win_verified == 1 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1` | 0/0 | 0/0 |

### quiet_compute_no_judge: 자료 부족

- 판정식: `count(suspect_any_n == 0 and judge_any_n == 0 and decline_n == 0 and hold_any_n == 0 and spare_used == 0 and quiet_periods >= 100 and ow_data_equal == 1) >= N_SCORED`
- 표시: quiet_periods = 관측자(rank 3이 아닌 rank마다, 그 프로세스의 rank 3 쪽 probe summary) 가운데 가장 작은 max(0, P_w − (dev_ctx × reads − dev_quiet)). P_w = floor((quiet end 줄 − quiet 시작 줄의 mono_ms) / probe_ms) − 1(창 안의 온전한 주기 하한), dev_ctx × reads − dev_quiet는 그 실행 전체에서 조용하다고 세지 않은 문맥 READ(남은 일, 실패, 빠진 READ)의 수라 창 안의 주기 하나를 많아야 하나씩 망침: 하한. 항상 조용한 받는 문맥이 수를 부풀리지 않는다(한 주기에 모든 문맥이 조용해야 셈). quiet end 줄이 없으면 0(창이 끝나지 않음: 측정된 실패), 관측자의 summary가 없으면 빈칸(자료 부족, probe_missing). 예상 값은 약 119 − 5(pilot 4가 잼)
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_quiet12000@gc
- `gc4_quiet12000@gc`: 판정한 시행 0회, 대입한 식 `0 >= 1` → 거짓
  - `count(suspect_any_n == 0 and judge_any_n == 0 and decline_n == 0 and hold_any_n == 0 and spare_used == 0 and quiet_periods >= 100 and ow_data_equal == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 1 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_quiet12000@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `suspect_any_n == 0 and judge_any_n == 0 and decline_n == 0 and hold_any_n == 0 and spare_used == 0 and quiet_periods >= 100 and ow_data_equal == 1` | 0/0 | 0/0 |

### waiter_not_judged: 자료 부족

- 판정식: `count(waiter_judge_n == 0 and waiter_fenced == 0 and wait_peer == 3 and wait_ended_progress == 1 and revived_done == 1 and ow_data_equal == 1) >= N_SCORED`
- 표시: 2026-10-27 pilot 5 뒤 waiter_old_rule(옛 규칙의 연쇄 판정을 재던 perf 행; 고친 라이브러리에서 설계대로 0/2)을 이 안전성 행으로 바꿈. 주입 기록과 제외는 그 행과 같다(rank 3의 hang 줄, rank 1의 kv waitpend=1; 하나라도 없으면 8절 제외). 주장의 조건 셋(기다리는 상대 = 남은 일을 둔 상대, 상대가 남은 일을 둔 채 멈춤, 복원 뒤 G 안에 다시 씀)이 이 셀에서 성립한다 [추론: 셀의 driver 스위치]. pilot 5 셀 B 두 시행에서 항 모두 참(wait_peer 3, wait_ended_progress 1, waiter_judge_n 0, waiter_fenced 0) [측정: 로컬 실행, 채점 아님]. 대조 셀은 WAITER_RANK가 없어 waiter 열이 비고 이 행에 들지 않음
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_gpuhang12000_waitpend_fence@gc
- `gc4_gpuhang12000_waitpend_fence@gc`: 판정한 시행 0회, 대입한 식 `0 >= 1` → 거짓
  - `count(waiter_judge_n == 0 and waiter_fenced == 0 and wait_peer == 3 and wait_ended_progress == 1 and revived_done == 1 and ow_data_equal == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 1 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_gpuhang12000_waitpend_fence@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `waiter_judge_n == 0 and waiter_fenced == 0 and wait_peer == 3 and wait_ended_progress == 1 and revived_done == 1 and ow_data_equal == 1` | 0/0 | 0/0 |

### mgmt_mute_transparent: 자료 부족

- 판정식: `count(judge_any_n == 0 and rec_lost_n == 0 and rec_repair_n == 0 and ckpt_stable_in_mute >= 1 and ow_data_equal == 1) >= 5`
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_mgmt_mute8@gc
- `gc4_mgmt_mute8@gc`: 판정한 시행 0회, 대입한 식 `0 >= 5` → 거짓
  - `count(judge_any_n == 0 and rec_lost_n == 0 and rec_repair_n == 0 and ckpt_stable_in_mute >= 1 and ow_data_equal == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 5 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_mgmt_mute8@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `judge_any_n == 0 and rec_lost_n == 0 and rec_repair_n == 0 and ckpt_stable_in_mute >= 1 and ow_data_equal == 1` | 0/0 | 0/0 |

### mgmt_mute_tcp: 자료 부족

- 판정식: `count(judge_any_n == 0 and ow_data_equal == 1) >= 5`
- 표시: 2026-10-28 사용자 결정(EXPERIMENT 12절 그날 "kind 경계 행과 부하 셀" 행): kind perf → safety(규칙이 판정 0과 데이터 같음뿐이라 quiet_compute_no_judge, waiter_not_judged와 같은 꼴; 규칙, 셀, n, k는 그대로)
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gct4_mgmt_mute8@gct
- `gct4_mgmt_mute8@gct`: 판정한 시행 0회, 대입한 식 `0 >= 5` → 거짓
  - `count(judge_any_n == 0 and ow_data_equal == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 5 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gct4_mgmt_mute8@gct` | 0 | 0 | 0 | 0 | 0 | 0 | `judge_any_n == 0 and ow_data_equal == 1` | 0/0 | 0/0 |

### qp_err_repair: 자료 부족

- 판정식: `count(judge_any_n == 0 and qperr_pair_sent_by_target == 1 and qperr_rec_gen_delta == 1 and qperr_probe_gen_delta == 0 and qperr_pair_read_fail == 0 and qperr_records_after >= 1 and ow_data_equal == 1) >= 4`
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_qperr_record@gc
- `gc4_qperr_record@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(judge_any_n == 0 and qperr_pair_sent_by_target == 1 and qperr_rec_gen_delta == 1 and qperr_probe_gen_delta == 0 and qperr_pair_read_fail == 0 and qperr_records_after >= 1 and ow_data_equal == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_qperr_record@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `judge_any_n == 0 and qperr_pair_sent_by_target == 1 and qperr_rec_gen_delta == 1 and qperr_probe_gen_delta == 0 and qperr_pair_read_fail == 0 and qperr_records_after >= 1 and ow_data_equal == 1` | 0/0 | 0/0 |

### ud_drop_rejoin: 자료 부족

- 판정식: `count(rejoin_dropped >= 1 and rejoin_resent >= 1 and rejoin_accept_n == n_surv and rejoin_accept_dup_n == 0 and fail_to_spare_n == 0 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1) >= 4`
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_ud_drop_rejoin@gc
- `gc4_ud_drop_rejoin@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(rejoin_dropped >= 1 and rejoin_resent >= 1 and rejoin_accept_n == n_surv and rejoin_accept_dup_n == 0 and fail_to_spare_n == 0 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_ud_drop_rejoin@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `rejoin_dropped >= 1 and rejoin_resent >= 1 and rejoin_accept_n == n_surv and rejoin_accept_dup_n == 0 and fail_to_spare_n == 0 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1` | 0/0 | 0/0 |

### credit_stall_no_loss: 자료 부족

- 판정식: `count(rnr_n == 0 and rec_lost_n == 0 and rec_dup_n == 0 and n_judge == 0 and surv_unfinished == 0 and ow_data_equal == 1) >= 5`
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_credit_stall@gc
- `gc4_credit_stall@gc`: 판정한 시행 0회, 대입한 식 `0 >= 5` → 거짓
  - `count(rnr_n == 0 and rec_lost_n == 0 and rec_dup_n == 0 and n_judge == 0 and surv_unfinished == 0 and ow_data_equal == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 5 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_credit_stall@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `rnr_n == 0 and rec_lost_n == 0 and rec_dup_n == 0 and n_judge == 0 and surv_unfinished == 0 and ow_data_equal == 1` | 0/0 | 0/0 |

### spare_absent_refused: 자료 부족(n<k)

- 판정식: `count((has(la_act_refused_why, "the spare exited") or has(la_act_refused_why, "could not hand over")) and fenced_to_fallback_ms <= 100 and surv_released == n_surv) >= 4`
- 표시: 까닭 둘은 launcher의 경쟁이다: pilot 1은 예비 프로세스의 끝을 먼저 보고 'the spare exited'(GL_R_SPARE_EXITED), pilot 2는 넘김이 먼저 실패해 'could not hand over to the spare'(GL_R_SEND_FAILED)였고 끝 줄은 그 81 ms 뒤 [측정: results/20261023_pilot2/a1 launcher_sunny.log; 소스: impl/launcher/launcher_msg.h]
- `gc4_kill3_ow_spareabsent@gc`: 판정한 시행 1회, 대입한 식 `1 >= 4` → 거짓
  - `count((has(la_act_refused_why, "the spare exited") or has(la_act_refused_why, "could not hand over")) and fenced_to_fallback_ms <= 100 and surv_released == n_surv)` = 1/1. 만족하지 않은 시행: 없음
  - 채점 n 1, 자료 부족 n 0, 자료 있는 n 1, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_kill3_ow_spareabsent@gc` | 1 | 1 | 0 | 0 | 1 | 0 | `(has(la_act_refused_why, "the spare exited") or has(la_act_refused_why, "could not hand over")) and fenced_to_fallback_ms <= 100 and surv_released == n_surv` | 1/1 = 100.0 % | 1/1 = 100.0 % |

### kill_no_witness: 자료 부족

- 판정식: `count(n_judge == n_surv and n_judge_exited == n_judge and 40 <= kill_judge_ms_min and kill_judge_ms_max <= 200 and 68.4 <= judge_to_publish_ms <= 74.4 and hold_other_n == 0 and hold_after_restore_n == 0 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1) >= 4`
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_kill3_ow_nowitness@gc
- `gc4_kill3_ow_nowitness@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(n_judge == n_surv and n_judge_exited == n_judge and 40 <= kill_judge_ms_min and kill_judge_ms_max <= 200 and 68.4 <= judge_to_publish_ms <= 74.4 and hold_other_n == 0 and hold_after_restore_n == 0 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_kill3_ow_nowitness@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `n_judge == n_surv and n_judge_exited == n_judge and 40 <= kill_judge_ms_min and kill_judge_ms_max <= 200 and 68.4 <= judge_to_publish_ms <= 74.4 and hold_other_n == 0 and hold_after_restore_n == 0 and wait_held == 1 and ow_data_equal == 1 and revived_done == 1` | 0/0 | 0/0 |

### restore_time_rdma: 자료 부족

- 판정식: `mi4_kill3_ow@gc: count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1) >= 9 ;; mi4_kill1_ow@gc: count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1) >= 4 ;; mi4_kill3_ckpt_ow@gc: count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1) >= 4 ;; mi4_seg_4k@gc: count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1) >= 4 ;; mi4_seg_32k@gc: count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1) >= 4 ;; mi4_seg_128k@gc: count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1) >= 4 ;; mi4_pull@gc: count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1) >= 4 ;; rs4_kill3_mion@gc: count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1) >= 4 ;; mi4_train_kill3@gc: count(195 <= judge_to_publish_ms <= 286 and 229.6 <= kill_to_publish_ms <= 318.0 and restore_time_ms <= 1000 and fence_order_ok == 1 and la_later_n <= 1) >= 9`
- 표시: n 10 셀 ≥ 9/10, n 5 셀(kill1, ckpt, seg 셋, pull, rs4_kill3_mion) ≥ 4/5(리뷰 D3). 띠는 3절 값 그대로(2026-10-24 pilot 2 뒤 확정): pilot 2 RG-gc의 이 셀들 4 KiB 여덟이 판정 → 게시 154.7–186.8 ms, kill → 게시 175.2–207.7 ms, 학습 250.1, 270.8 ms로 모두 띠 안 [측정: results/20261023_pilot2/PILOT.md, n 1씩, 채점 아님]
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): mi4_kill3_ow@gc, mi4_kill1_ow@gc, mi4_kill3_ckpt_ow@gc, mi4_seg_4k@gc, mi4_seg_32k@gc, mi4_seg_128k@gc, mi4_pull@gc, rs4_kill3_mion@gc, mi4_train_kill3@gc
- `mi4_kill3_ow@gc`: 판정한 시행 0회, 대입한 식 `0 >= 9` → 거짓
  - `count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 9 → 자료 부족(n<k)
- `mi4_kill1_ow@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `mi4_kill3_ckpt_ow@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `mi4_seg_4k@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `mi4_seg_32k@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `mi4_seg_128k@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `mi4_pull@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `rs4_kill3_mion@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `mi4_train_kill3@gc`: 판정한 시행 0회, 대입한 식 `0 >= 9` → 거짓
  - `count(195 <= judge_to_publish_ms <= 286 and 229.6 <= kill_to_publish_ms <= 318.0 and restore_time_ms <= 1000 and fence_order_ok == 1 and la_later_n <= 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 9 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `mi4_kill3_ow@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1` | 0/0 | 0/0 |
| `mi4_kill1_ow@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1` | 0/0 | 0/0 |
| `mi4_kill3_ckpt_ow@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1` | 0/0 | 0/0 |
| `mi4_seg_4k@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1` | 0/0 | 0/0 |
| `mi4_seg_32k@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1` | 0/0 | 0/0 |
| `mi4_seg_128k@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1` | 0/0 | 0/0 |
| `mi4_pull@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1` | 0/0 | 0/0 |
| `rs4_kill3_mion@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `120 <= judge_to_publish_ms <= 197 and 154.5 <= kill_to_publish_ms <= 240.5 and restore_time_ms <= 2000 and fence_order_ok == 1 and la_later_n <= 1` | 0/0 | 0/0 |
| `mi4_train_kill3@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `195 <= judge_to_publish_ms <= 286 and 229.6 <= kill_to_publish_ms <= 318.0 and restore_time_ms <= 1000 and fence_order_ok == 1 and la_later_n <= 1` | 0/0 | 0/0 |

### none_probe_clean: 자료 부족

- 판정식: `gc4_none_probe@gc: count(read_success_pct == 100 and beat_gap_max_ms < 300 and suspect_n == 0 and judge_any_n == 0 and ckpt_pause_ms <= 20) >= 10 ;; gc4_none_ow@gc: count(read_success_pct == 100 and beat_gap_max_ms < 300 and suspect_n == 0 and judge_any_n == 0 and ckpt_pause_ms <= 20) >= 5 ;; mi4_train_none@gc: count(suspect_any_n == 0 and judge_any_n == 0 and hold_any_n == 0 and read_success_pct == 100 and ckpt_pause_ms <= 20) >= 5`
- 표시: 상한 16 → 20 ms: pilot 2 gc4_none_probe 16.526 ms(n 1), 같은 hold들의 장애 없는 셀 5.378–9.181 ms [측정: results/20261023_pilot2/PILOT.md 문제 7]; 학습 모양의 따로 된 상한은 이 두 셀에 학습 모양이 없어 쓰지 않음. 2026-10-28 사용자 결정(EXPERIMENT 12절 그날 "kind 경계 행과 부하 셀" 행): 부하 아래 판정 없음을 회귀 셀 mi4_train_none@gc로 잼(pilot 없음). 입력 멈춤 항 ckpt_pause_ms <= 20은 gin-mirror의 이 셀 규칙 train_none_clean의 상한이고(그 키는 regression_rdma의 열둘에 없어 rdma 빌드에서 따로 채점되지 않음, 3절 "장애 없음의 입력 멈춤 상한" 메모), 상태 페이지 READ를 켠 학습 모양에서 잰 값은 없음 [미확인]
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_none_probe@gc, gc4_none_ow@gc, mi4_train_none@gc
- `gc4_none_probe@gc`: 판정한 시행 0회, 대입한 식 `0 >= 10` → 거짓
  - `count(read_success_pct == 100 and beat_gap_max_ms < 300 and suspect_n == 0 and judge_any_n == 0 and ckpt_pause_ms <= 20)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 10 → 자료 부족(n<k)
- `gc4_none_ow@gc`: 판정한 시행 0회, 대입한 식 `0 >= 5` → 거짓
  - `count(read_success_pct == 100 and beat_gap_max_ms < 300 and suspect_n == 0 and judge_any_n == 0 and ckpt_pause_ms <= 20)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 5 → 자료 부족(n<k)
- `mi4_train_none@gc`: 판정한 시행 0회, 대입한 식 `0 >= 5` → 거짓
  - `count(suspect_any_n == 0 and judge_any_n == 0 and hold_any_n == 0 and read_success_pct == 100 and ckpt_pause_ms <= 20)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 5 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_none_probe@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `read_success_pct == 100 and beat_gap_max_ms < 300 and suspect_n == 0 and judge_any_n == 0 and ckpt_pause_ms <= 20` | 0/0 | 0/0 |
| `gc4_none_ow@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `read_success_pct == 100 and beat_gap_max_ms < 300 and suspect_n == 0 and judge_any_n == 0 and ckpt_pause_ms <= 20` | 0/0 | 0/0 |
| `mi4_train_none@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `suspect_any_n == 0 and judge_any_n == 0 and hold_any_n == 0 and read_success_pct == 100 and ckpt_pause_ms <= 20` | 0/0 | 0/0 |

### no_tcp_control: 자료 부족

- 판정식: `gc4_none_ow@gc: count(tcp_ctrl_bytes == 0 and ss_tx_delta_bytes == 0 and witness_pairs == witness_expected and active_mtu_rain == 4096 and active_mtu_sunny == 4096 and active_mtu_kv_min == 4096) >= N_SCORED ;; gc4_none_probe@gc: count(tcp_ctrl_bytes == 0 and ss_tx_delta_bytes == 0 and witness_pairs == witness_expected and active_mtu_rain == 4096 and active_mtu_sunny == 4096 and active_mtu_kv_min == 4096) >= N_SCORED ;; build:gc: count(tcp_ctrl_bytes == 0 and witness_pairs == witness_expected and active_mtu_rain == 4096 and active_mtu_sunny == 4096 and active_mtu_kv_min == 4096) >= N_SCORED`
- 표시: ss_tx_delta_bytes 0은 복원이 없을 때만 뜻이 있다(2026-10-24 pilot 2 뒤 결정): pilot 2 이른 kill 셀 여섯에서 죽은 rank에 이은 소켓이 닫혀 음수(넷)이거나 둘째 스냅숏이 없었고(둘), 그 가운데 셋에서 sunny 생존 rank가 되살린 화신과의 새 소켓으로 +1 873 B를 보냄 [측정: results/20261023_pilot2 사본, rows_gc.py ss_deltas; 증인 인사라는 것은 추론]. 그래서 ss 항은 장애 없는 두 셀의 규칙에만 두고 build:gc 전체는 tcp_ctrl_bytes, 증인 쌍, MTU로 판정; ss_excluded와 음수 빈칸 규칙(자료 부족)은 그대로. NCCL bootstrap 소켓 수(pilot 1 34)는 보고만(ss_tcp_conn_n); TODO(lib): 제어 요약에 tcp_record_bytes_live=와 tcp_data_bytes_live=(live 뒤에 보낸 바이트)가 있어야 (가)가 판정됨(REVIEW_INT3 B3, 2026-10-22 조율 세션 결정)
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): gc4_none_ow@gc, gc4_none_probe@gc
- `gc4_none_ow@gc`: 판정한 시행 0회, 대입한 식 `0 >= 1` → 거짓
  - `count(tcp_ctrl_bytes == 0 and ss_tx_delta_bytes == 0 and witness_pairs == witness_expected and active_mtu_rain == 4096 and active_mtu_sunny == 4096 and active_mtu_kv_min == 4096)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 1 → 자료 부족(n<k)
- `gc4_none_probe@gc`: 판정한 시행 0회, 대입한 식 `0 >= 1` → 거짓
  - `count(tcp_ctrl_bytes == 0 and ss_tx_delta_bytes == 0 and witness_pairs == witness_expected and active_mtu_rain == 4096 and active_mtu_sunny == 4096 and active_mtu_kv_min == 4096)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 1 → 자료 부족(n<k)
- `build:gc`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(tcp_ctrl_bytes == 0 and witness_pairs == witness_expected and active_mtu_rain == 4096 and active_mtu_sunny == 4096 and active_mtu_kv_min == 4096)` = 3/3. 만족하지 않은 시행: 없음
  - 채점 n 3, 자료 부족 n 0, 자료 있는 n 3, 문턱 k 3

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `gc4_none_ow@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `tcp_ctrl_bytes == 0 and ss_tx_delta_bytes == 0 and witness_pairs == witness_expected and active_mtu_rain == 4096 and active_mtu_sunny == 4096 and active_mtu_kv_min == 4096` | 0/0 | 0/0 |
| `gc4_none_probe@gc` | 0 | 0 | 0 | 0 | 0 | 0 | `tcp_ctrl_bytes == 0 and ss_tx_delta_bytes == 0 and witness_pairs == witness_expected and active_mtu_rain == 4096 and active_mtu_sunny == 4096 and active_mtu_kv_min == 4096` | 0/0 | 0/0 |
| `build:gc` | 3 | 3 | 0 | 0 | 3 | 0 | `tcp_ctrl_bytes == 0 and witness_pairs == witness_expected and active_mtu_rain == 4096 and active_mtu_sunny == 4096 and active_mtu_kv_min == 4096` | 3/3 = 100.0 % | 3/3 = 100.0 % |

### cost_probe_lat4k: 자료 부족

- 판정식: `cost: rule=within:2 judged_nodes=sunny`
- 표시: 문턱 2 %(2026-10-24 pilot 2 뒤 확정): max(2 %, sunny 수신 probe-off 두 묶음 사이 차 0.76 % × 2 = 1.52 %) = 2 %(probe-on 두 묶음 사이 0.50 %; pilot 2 팔 차 +1.14 %; 두 묶음뿐이라 퍼짐은 어림) [측정: results/20261023_pilot2/PILOT.md 비용 팔]; 판정은 한쪽(느려짐만: score_gc.py cost_eval)

| 받는 노드 | 지표 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |
|---|---|---|--:|--:|---|---|
| rain | lat4k | probe-off | 0 | - | - | - |
| rain | lat4k | probe-on | 0 | - | - | - |
| sunny | lat4k | probe-off | 0 | - | - | - |
| sunny | lat4k | probe-on | 0 | - | - | - |

### long_hold_lane: 자료 없음(실패 아님)

- 판정식: `subset(hold_ms_max > 1000): count(ow_data_equal == 1) >= N_SCORED`
- `build:gc`: 판정한 시행 3회, 대입한 식 `0 >= 1` → 거짓
  - `count(ow_data_equal == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 1 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `build:gc` | 3 | 3 | 0 | 0 | 3 | 0 | `ow_data_equal == 1` | 0/0 | 0/0 |

### gate_fenced: 자료 부족

- 판정식: `count(gate_real == 1 and old_go_ms < second_thread_ms and 0 <= fenced_after_second_ms <= 5 and fenced_vs_pidfd_abs_ms <= 5) >= 10`
- 표시: 2026-10-24 pilot 2 뒤 확정: 관문 시각은 gate_fenced.cc의 줄(gate_src unit)에서 읽는다(rows_gc.py GATEU; 그 전 정규식은 옛 시간표 모형의 줄 꼴이라 pilot 2 local 행이 0이었음). 실제 pid 모드(--pid)는 만들지 않음: gate_fenced.cc가 스스로 실제 자식 프로세스를 띄움. pilot 2 local 10/10, FENCED GO − 마지막 thread 끝 0.7–1.7 ms [측정: results/20261023_pilot2/local/gate_fenced_n1.log]
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): local:gate_fenced
- `local:gate_fenced`: 판정한 시행 0회, 대입한 식 `0 >= 10` → 거짓
  - `count(gate_real == 1 and old_go_ms < second_thread_ms and 0 <= fenced_after_second_ms <= 5 and fenced_vs_pidfd_abs_ms <= 5)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 10 → 자료 부족(n<k)

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `local:gate_fenced` | 10 | 0 | 0 | 0 | 0 | 0 | `gate_real == 1 and old_go_ms < second_thread_ms and 0 <= fenced_after_second_ms <= 5 and fenced_vs_pidfd_abs_ms <= 5` | 0/0 | 0/0 |

### regression_tcp: 자료 부족

- 판정식: `mirror: ow_wait_held,ow_data_equal,ow_no_reexec,ow_revived_done,ow_suppress_exact,ow_from_pool,ow_restore_time@gct`
- 표시: 2026-10-22 셀 줄임: tcp 회귀는 gin-mirror hold G1의 mi4_kill3_ow 하나(cells_gc.json regression.builds.gct.cells). 여러 셀을 보는 store_rdma는 넣지 않음. TODO(code): hold_gc.sh와 score_gc.py가 builds.gct.cells를 읽어야 함
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): mirror: ow_wait_held,ow_data_equal,ow_no_reexec,ow_revived_done,ow_suppress_exact,ow_from_pool,ow_restore_time@gct
- gin-mirror `ow_wait_held` (mi4_kill3_ow@gct): 자료 부족
- gin-mirror `ow_data_equal` (mi4_kill3_ow@gct): 자료 부족
- gin-mirror `ow_no_reexec` (mi4_kill3_ow@gct): 자료 부족
- gin-mirror `ow_revived_done` (mi4_kill3_ow@gct): 자료 부족
- gin-mirror `ow_suppress_exact` (mi4_kill3_ow@gct): 자료 부족
- gin-mirror `ow_from_pool` (mi4_kill3_ow@gct): 자료 부족
- gin-mirror `ow_restore_time` (mi4_kill3_ow@gct): 자료 부족

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `mi4_kill3_ow@gct` | 10 | 0 | 0 | 0 | 0 | 0 | `wait_held == 1` | 0/0 | 0/0 |
| `mi4_kill3_ow@gct` | 10 | 0 | 0 | 0 | 0 | 0 | `ow_data_equal == 1` | 0/0 | 0/0 |
| `mi4_kill3_ow@gct` | 10 | 0 | 0 | 0 | 0 | 0 | `no_reexec == 1` | 0/0 | 0/0 |
| `mi4_kill3_ow@gct` | 10 | 0 | 0 | 0 | 0 | 0 | `revived_done == 1` | 0/0 | 0/0 |
| `mi4_kill3_ow@gct` | 10 | 0 | 0 | 0 | 0 | 0 | `suppress_ok == 1` | 0/0 | 0/0 |
| `mi4_kill3_ow@gct` | 10 | 0 | 0 | 0 | 0 | 0 | `from_pool_ok == 1 and export_source_bytes == 0` | 0/0 | 0/0 |
| `mi4_kill3_ow@gct` | 10 | 0 | 0 | 0 | 0 | 0 | `restore_time_ms <= 2000` | 0/0 | 0/0 |

### regression_rdma: 자료 부족

- 판정식: `mirror: ow_wait_held,ow_data_equal,ow_no_reexec,ow_revived_done,ow_suppress_exact,ow_from_pool,ckpt_kill_ow,kill_other_ow,reimage_after_restore,second_death_restored,train_data_equal,train_second_death@gc`
- 표시: ID 목록은 3절에 그대로(리뷰 D5); store_rdma와 train_paced_import는 넣지 않음(2026-10-24 pilot 2 뒤 확정); second_death_restored와 train_second_death의 시간 몫(≤ 2 000, ≤ 1 000 ms)은 gin-mirror 원래 기준. pilot 2 RG-gc에서 자료 있는 규칙 열하나가 1/1, 두 죽음 규칙 셋은 그 셀의 둘째 죽음이 복원되지 않아 거짓(라이브러리 고칠 것)
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): mirror: ow_wait_held,ow_data_equal,ow_no_reexec,ow_revived_done,ow_suppress_exact,ow_from_pool,ckpt_kill_ow,kill_other_ow,reimage_after_restore,second_death_restored,train_data_equal,train_second_death@gc
- gin-mirror `ow_wait_held` (mi4_kill3_ow@gc): 자료 부족
- gin-mirror `ow_data_equal` (mi4_kill3_ow@gc): 자료 부족
- gin-mirror `ow_no_reexec` (mi4_kill3_ow@gc): 자료 부족
- gin-mirror `ow_revived_done` (mi4_kill3_ow@gc): 자료 부족
- gin-mirror `ow_suppress_exact` (mi4_kill3_ow@gc): 자료 부족
- gin-mirror `ow_from_pool` (mi4_kill3_ow@gc): 자료 부족
- gin-mirror `ckpt_kill_ow` (mi4_kill3_ckpt_ow@gc): 자료 부족
- gin-mirror `kill_other_ow` (mi4_kill1_ow@gc): 자료 부족
- gin-mirror `reimage_after_restore` (mi4_kill2_kill3_ow@gc): 자료 부족
- gin-mirror `second_death_restored` (mi4_kill2_kill3_ow@gc): 자료 부족
- gin-mirror `train_data_equal` (mi4_train_kill3@gc): 자료 부족
- gin-mirror `train_second_death` (mi4_train_kill2_kill3@gc): 자료 부족

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `mi4_kill3_ow@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `wait_held == 1` | 0/0 | 0/0 |
| `mi4_kill3_ow@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `ow_data_equal == 1` | 0/0 | 0/0 |
| `mi4_kill3_ow@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `no_reexec == 1` | 0/0 | 0/0 |
| `mi4_kill3_ow@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `revived_done == 1` | 0/0 | 0/0 |
| `mi4_kill3_ow@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `suppress_ok == 1` | 0/0 | 0/0 |
| `mi4_kill3_ow@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `from_pool_ok == 1 and export_source_bytes == 0` | 0/0 | 0/0 |
| `mi4_kill3_ckpt_ow@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `die_in_pause == 3 and wait_held == 1 and ow_data_equal == 1 and no_reexec == 1 and revived_done == 1 and ckpt_before == 1` | 0/0 | 0/0 |
| `mi4_kill1_ow@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `wait_held == 1 and ow_data_equal == 1 and no_reexec == 1 and revived_done == 1` | 0/0 | 0/0 |
| `mi4_kill2_kill3_ow@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `reimage_ok == 1` | 0/0 | 0/0 |
| `mi4_kill2_kill3_ow@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `second_ok == 1 and restore_time_ms_1 <= 2000 and restore_time_ms_2 <= 2000 and wait_held == 1 and ow_data_equal == 1 and no_reexec == 1` | 0/0 | 0/0 |
| `mi4_train_kill3@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `ow_data_equal == 1 and wait_held == 1 and no_reexec == 1 and revived_done == 1` | 0/0 | 0/0 |
| `mi4_train_kill2_kill3@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `reimage_ok == 1 and second_ok == 1 and restore_time_ms_1 <= 1000 and restore_time_ms_2 <= 1000 and wait_held == 1 and ow_data_equal == 1 and no_reexec == 1` | 0/0 | 0/0 |

### regression_rdma_mirror_off: 자료 부족

- 판정식: `mirror: rg_data_equal,rg_no_reexec@gc ;; rs4_kill3@gc: count(tcp_image_bytes == 0 and tcp_data_bytes == 0) >= N_SCORED ;; rs4_kill3_ckpt@gc: count(data_equal == 1 and no_reexec == 1) >= 4 ;; rs4_kill3_ckpt@gc: count(tcp_image_bytes == 0 and tcp_data_bytes == 0) >= N_SCORED ;; rs4_kill1@gc: count(data_equal == 1 and no_reexec == 1) >= 4 ;; rs4_kill1@gc: count(tcp_image_bytes == 0 and tcp_data_bytes == 0) >= N_SCORED ;; rs4_none@gc: count(data_equal == 1) >= N_SCORED ;; rs4_none@gc: count(tcp_image_bytes == 0 and tcp_data_bytes == 0) >= N_SCORED`
- 표시: rs4_kill3, rs4_kill3_ckpt, rs4_kill1(데이터 같음, 재실행 없음), rs4_none(데이터 같음)은 gin-mirror의 원래 k; 이미지 바이트 0은 구조적 성질이라 모든 유효 시행(리뷰 D6, 2026-10-24 pilot 2 뒤 확정). pilot 2에서 네 셀 모두 1/1
- 자료 부족(판정한 시행이 계획 n 미만, 묶음 키 안의 셀이 계획 미만, 라이브러리 열이 비어 있음, 또는 gin-mirror 예측의 자료 부족): mirror: rg_data_equal,rg_no_reexec@gc, rs4_kill3@gc, rs4_kill3_ckpt@gc, rs4_kill3_ckpt@gc, rs4_kill1@gc, rs4_kill1@gc, rs4_none@gc, rs4_none@gc
- `rs4_kill3@gc`: 판정한 시행 0회, 대입한 식 `0 >= 10` → 거짓
  - `count(tcp_image_bytes == 0 and tcp_data_bytes == 0)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 10 → 자료 부족(n<k)
- `rs4_kill3_ckpt@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(data_equal == 1 and no_reexec == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `rs4_kill3_ckpt@gc`: 판정한 시행 0회, 대입한 식 `0 >= 5` → 거짓
  - `count(tcp_image_bytes == 0 and tcp_data_bytes == 0)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 5 → 자료 부족(n<k)
- `rs4_kill1@gc`: 판정한 시행 0회, 대입한 식 `0 >= 4` → 거짓
  - `count(data_equal == 1 and no_reexec == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 4 → 자료 부족(n<k)
- `rs4_kill1@gc`: 판정한 시행 0회, 대입한 식 `0 >= 5` → 거짓
  - `count(tcp_image_bytes == 0 and tcp_data_bytes == 0)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 5 → 자료 부족(n<k)
- `rs4_none@gc`: 판정한 시행 0회, 대입한 식 `0 >= 5` → 거짓
  - `count(data_equal == 1)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 5 → 자료 부족(n<k)
- `rs4_none@gc`: 판정한 시행 0회, 대입한 식 `0 >= 5` → 거짓
  - `count(tcp_image_bytes == 0 and tcp_data_bytes == 0)` = 0/0. 만족하지 않은 시행: 없음
  - 채점 n 0, 자료 부족 n 0, 자료 있는 n 0, 문턱 k 5 → 자료 부족(n<k)
- gin-mirror `rg_data_equal` (rs4_kill3@gc): 자료 부족
- gin-mirror `rg_no_reexec` (rs4_kill3@gc): 자료 부족

| 키 | 계획 | 실행 | 제외(사유) | 준비 실패 | 판정 n | 자료 부족 n | 조건 | 조건부 성공(판정 n − 자료 부족) | 전체 성공(판정 n + 준비 실패) |
|---|--:|--:|---|--:|--:|--:|---|--:|--:|
| `rs4_kill3@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `tcp_image_bytes == 0 and tcp_data_bytes == 0` | 0/0 | 0/0 |
| `rs4_kill3_ckpt@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `data_equal == 1 and no_reexec == 1` | 0/0 | 0/0 |
| `rs4_kill3_ckpt@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `tcp_image_bytes == 0 and tcp_data_bytes == 0` | 0/0 | 0/0 |
| `rs4_kill1@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `data_equal == 1 and no_reexec == 1` | 0/0 | 0/0 |
| `rs4_kill1@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `tcp_image_bytes == 0 and tcp_data_bytes == 0` | 0/0 | 0/0 |
| `rs4_none@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `data_equal == 1` | 0/0 | 0/0 |
| `rs4_none@gc` | 5 | 0 | 0 | 0 | 0 | 0 | `tcp_image_bytes == 0 and tcp_data_bytes == 0` | 0/0 | 0/0 |
| `rs4_kill3@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `data_equal == 1` | 0/0 | 0/0 |
| `rs4_kill3@gc` | 10 | 0 | 0 | 0 | 0 | 0 | `no_reexec == 1` | 0/0 | 0/0 |

## 비용 보고(판정 없음)

| 받는 노드 | 지표 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |
|---|---|---|--:|--:|---|---|
| rain | lat4k | probe-off | 0 | - | - | - |
| rain | lat4k | probe-on | 0 | - | - | - |
| sunny | lat4k | probe-off | 0 | - | - | - |
| sunny | lat4k | probe-on | 0 | - | - | - |

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `cost_lat4k_probe-off@gcp` | 12 | 0 | 0 | 없음 |
| `cost_lat4k_probe-on@gcp` | 12 | 0 | 0 | 없음 |
| `gc4_credit_stall@gc` | 0 | 0 | 0 | 없음 |
| `gc4_fdhold_sock_kill3@gc` | 0 | 0 | 0 | 없음 |
| `gc4_fdhold_sock_kill3_noreport@gc` | 0 | 0 | 0 | 없음 |
| `gc4_fdhold_uverbs_kill3@gc` | 1 | 1 | 1 | 없음 |
| `gc4_freeze12000_fence@gc` | 0 | 0 | 0 | 없음 |
| `gc4_gpuhang12000_ctx1_fence@gc` | 0 | 0 | 0 | 없음 |
| `gc4_gpuhang12000_fence@gc` | 0 | 0 | 0 | 없음 |
| `gc4_gpuhang12000_waitpend_fence@gc` | 0 | 0 | 0 | 없음 |
| `gc4_helper_freeze12000@gc` | 0 | 0 | 0 | 없음 |
| `gc4_kill3_noreport_nofdhold@gc` | 0 | 0 | 0 | 없음 |
| `gc4_kill3_ow@gc` | 0 | 0 | 0 | 없음 |
| `gc4_kill3_ow_nowitness@gc` | 0 | 0 | 0 | 없음 |
| `gc4_kill3_ow_spareabsent@gc` | 1 | 1 | 1 | 없음 |
| `gc4_mgmt_mute8@gc` | 0 | 0 | 0 | 없음 |
| `gc4_none_ow@gc` | 0 | 0 | 0 | 없음 |
| `gc4_none_probe@gc` | 0 | 0 | 0 | 없음 |
| `gc4_qperr_record@gc` | 0 | 0 | 0 | 없음 |
| `gc4_quiet12000@gc` | 0 | 0 | 0 | 없음 |
| `gc4_rst_kill3@gc` | 0 | 0 | 0 | 없음 |
| `gc4_rstgap_live300@gc` | 0 | 0 | 0 | 없음 |
| `gc4_slow_duty@gc` | 0 | 0 | 0 | 없음 |
| `gc4_stop12000_fence@gc` | 0 | 0 | 0 | 없음 |
| `gc4_stop12000_none@gc` | 1 | 1 | 1 | 없음 |
| `gc4_stop1500@gc` | 0 | 0 | 0 | 없음 |
| `gc4_stop4000@gc` | 0 | 0 | 0 | 없음 |
| `gc4_stop8000@gc` | 0 | 0 | 0 | 없음 |
| `gc4_ud_drop_rejoin@gc` | 0 | 0 | 0 | 없음 |
| `gct4_mgmt_mute8@gct` | 0 | 0 | 0 | 없음 |
| `local:gate_fenced` | 10 | 0 | 0 | 없음 |
| `mi4_int_10@gc` | 3 | 0 | 0 | 없음 |
| `mi4_int_20@gc` | 3 | 0 | 0 | 없음 |
| `mi4_int_40@gc` | 3 | 0 | 0 | 없음 |
| `mi4_kill1_ow@gc` | 5 | 0 | 0 | 없음 |
| `mi4_kill2_kill3_ow@gc` | 5 | 0 | 0 | 없음 |
| `mi4_kill3_ckpt_ow@gc` | 5 | 0 | 0 | 없음 |
| `mi4_kill3_ow@gc` | 10 | 0 | 0 | 없음 |
| `mi4_kill3_ow@gct` | 10 | 0 | 0 | 없음 |
| `mi4_kill3_ow_nomirror@gc` | 5 | 0 | 0 | 없음 |
| `mi4_kill3_ow_sampled@gc` | 5 | 0 | 0 | 없음 |
| `mi4_none_ow@gc` | 5 | 0 | 0 | 없음 |
| `mi4_overflow@gc` | 5 | 0 | 0 | 없음 |
| `mi4_pull@gc` | 5 | 0 | 0 | 없음 |
| `mi4_pull_none@gc` | 3 | 0 | 0 | 없음 |
| `mi4_refuse_csum@gc` | 3 | 0 | 0 | 없음 |
| `mi4_refuse_mirror1@gc` | 3 | 0 | 0 | 없음 |
| `mi4_refuse_sl@gc` | 3 | 0 | 0 | 없음 |
| `mi4_seg_128k@gc` | 5 | 0 | 0 | 없음 |
| `mi4_seg_32k@gc` | 5 | 0 | 0 | 없음 |
| `mi4_seg_4k@gc` | 5 | 0 | 0 | 없음 |
| `mi4_train_kill2_kill3@gc` | 5 | 0 | 0 | 없음 |
| `mi4_train_kill3@gc` | 10 | 0 | 0 | 없음 |
| `mi4_train_none@gc` | 5 | 0 | 0 | 없음 |
| `reg_mr4_none@gc` | 5 | 0 | 0 | 없음 |
| `reg_mr4_none_hold@gc` | 5 | 0 | 0 | 없음 |
| `reg_rm4_kill3_untimed@gc` | 5 | 0 | 0 | 없음 |
| `reg_rm4_kill3_untimed_hold@gc` | 5 | 0 | 0 | 없음 |
| `rs4_kill1@gc` | 5 | 0 | 0 | 없음 |
| `rs4_kill3@gc` | 10 | 0 | 0 | 없음 |
| `rs4_kill3_ckpt@gc` | 5 | 0 | 0 | 없음 |
| `rs4_kill3_mion@gc` | 5 | 0 | 0 | 없음 |
| `rs4_kill3_nospare@gc` | 5 | 0 | 0 | 없음 |
| `rs4_kill3_spareabsent@gc` | 5 | 0 | 0 | 없음 |
| `rs4_none@gc` | 5 | 0 | 0 | 없음 |
| `rs4_none_mion@gc` | 5 | 0 | 0 | 없음 |
| `rs4_none_off@gc` | 5 | 0 | 0 | 없음 |
| `rs4_refuse_gintype@gc` | 3 | 0 | 0 | 없음 |
| `rs4_refuse_nomacro@gc` | 3 | 0 | 0 | 없음 |
| `rs4_refuse_restoreoff1@gc` | 3 | 0 | 0 | 없음 |
| `rs4_refuse_symgin@gc` | 3 | 0 | 0 | 없음 |
