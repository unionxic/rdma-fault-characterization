# 살아 있지만 준비 안 된 상대 (live_peer)

**목적:** `MODEL.md` 규칙 3의 남은 두 항목을 한 실험으로 닫는다. 첫째, 상대 프로세스가 살아 있는데 분류기나
복구 경로가 "죽음" 또는 "복구 불가"로 판정하는 경우(오판)를 처음으로 잰다. 둘째, 혼잡 알림 처리 카운터
(`rp_cnp_handled`)가 재시도 초과와 상대 kill에서만 오르는 이유를 확인한다.

| 항목 | 값 |
|---|---|
| 상태 | `QA` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-07 |
| 기준 브랜치와 커밋 | `exp/live-peer` @ `3dbf995e` (master) |
| 사전 등록 태그 | `prereg/live-peer-v1` (이 상태로 바꾼 커밋) |
| 마지막 갱신 | 2026-10-07 20:45, 본 실행 125회, 채점, 결과 요약(14, 15절). 16–19절은 독립 재계산 뒤 |

표시: `[측정]` 원자료에서 확인, `[소스]` 코드나 문서에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. 이 문서를 쓰는
동안 클러스터에서 아무것도 실행하지 않았고 빌드도 하지 않았다. 측정값은 기존 원자료와 rain의 로컬 sysfs 읽기에서만
왔다.

## 1. 배경과 연구 질문

### 1.1 오판은 아직 재지 않았다

- `[소스]` `MODEL.md:116`: "살아 있지만 준비가 안 된 상대를 죽었다고 잘못 판정하는 경우(오판)는 아직 재지
  않았다." `MODEL.md:182`도 같다.
- 지금까지 "살아 있는 상대"로 잰 것은 두 가지다. 둘 다 오판을 만들 조건이 아니었다.
  - CPU 하네스의 상대 QP 오류: 프로세스가 살아 있고 제어 연결도 응답한다. `[측정]` 2026-09-23 30회와 2026-10-06
    10회 모두 생존 확인 결과가 "살아 있음, QP 오류"(`sub_cause=server_qp_err`)였다
    (`harness/results/retry_server_qp_err_20260923_123945.csv`, Release `data-20261006`의 propagation 캠페인 묶음
    `cpu/csv/`).
  - teardown_order의 살아 있는 상대: MR 해제는 10/0x88이 90/90, QP 파괴는 12/0x81이 20/20이었다
    (`harness/teardown_order/NOTES.md:59-60`). 제어 소켓은 닫지 않았다.
- `[소스]` 기존 탐지기는 모두 프로세스가 아니라 제어 연결을 본다(3.1의 표). 제어 연결이 닫히면 죽음, 마감 안에 답이
  없으면 복구 불가나 미확정으로 판정한다. 그래서 오판이 생길 조건은 "살아 있는 프로세스가 제어 연결을 닫는다"와
  "살아 있는 프로세스가 마감보다 오래 응답하지 않는다" 두 가지로 좁혀진다. 이 실험은 그 두 조건을 소프트웨어로
  만들고, 오판이 생기지 않아야 할 조건(QP만 준비 안 됨)과 함께 잰다.

### 1.2 혼잡 알림 처리 카운터

- 출처: `harness/gpu-initiated/propagation/EXPERIMENT.md:279-282`, 같은 폴더 `README.md:54-55`, 다음 작업 2번
  (`EXPERIMENT.md:465`). 독립 검증 표 `results/20261006_campaign/qa/layers_qa_TABLE.md:31`에 CPU 하네스의 재시도
  초과와 상대 kill에서 오른 카운터 이름이 있다.
- 카운터: `/sys/class/infiniband/<dev>/ports/1/hw_counters/rp_cnp_handled`(rain `mlx5_1`, sunny `mlx5_0`).
  evrec가 시행 시작과 끝에만 읽었다(`harness/gpu-initiated/propagation/evrec/evrec.c:241-242, 282-283`).
- `[측정]` Release `data-20261006`의 propagation 캠페인 묶음과 상대 kill 재실행 묶음을 받아 `SHA256SUMS`로 확인하고
  (둘 다 OK), evrec 기록 650개(325회 x 두 노드. 무효였던 GIN 프록시와 GDAKI의 상대 kill 20회 대신 재실행 20회)에서
  다시 셌다. 재계산 스크립트는 구현 단계에서 `qa/`에 넣는다.
  - rain: 재시도 초과와 상대 kill 115회 중 105회에서 올랐다. 나머지 10회는 GIN 프록시의 상대 kill로, 원격 접근
    오류(10/0x88)로 끝난 시행이다. 다른 장애와 장애 없음 210회에서는 0회다. 문서의 105/115와 같다.
  - verbs로 만든 QP(CPU 하네스 20회, GIN 프록시 10회): 30/30에서 `rp_cnp_handled` 증가량이 `roce_slow_restart_cnps`
    증가량과 같고(9–13), `roce_adp_retrans` 증가량 + 5와도 같다. `local_ack_timeout_err`는 30/30에서 +6이다.
  - DEVX로 만든 QP(GDAKI, NVSHMEM): `rp_cnp_handled`만 9–12 오르고 `roce_slow_restart_cnps`, `local_ack_timeout_err`는
    +0이다.
  - `np_cnp_sent`, `np_ecn_marked_roce_packets`, `rp_cnp_ignored`는 650/650에서 +0이다.
- `[측정]` rain 누적값(2026-10-07 로컬 sysfs 읽기): `np_cnp_sent` 0, `np_ecn_marked_roce_packets` 0, `rp_cnp_ignored` 0,
  `rp_cnp_handled` 81,629, `roce_slow_restart_cnps` 65,275. RoCE netdev `ens4f1np1`의 DCQCN 반응 쪽
  (`ecn/roce_rp/enable/0`–`7`)과 알림 쪽(`ecn/roce_np/enable/0`–`7`)은 모두 1이다.
- `[소스]` 리눅스 6.10.8 mlx5 소스(`/usr/src/linux-6.10.8.tar.xz`. 두 노드의 OFED 판 소스는 로컬에 없어 `[미확인]`):
  - `drivers/infiniband/hw/mlx5/counters.c:66-74`, `:398-418`: `rp_cnp_handled`, `rp_cnp_ignored`,
    `np_ecn_marked_roce_packets`, `np_cnp_sent`는 혼잡 통계 명령(`QUERY_CONG_STATISTICS`)으로 읽는 장치 단위 값이다.
  - 같은 파일 `:378-383`: 나머지 q 카운터(`local_ack_timeout_err`, `roce_slow_restart_cnps` 등)는 포트 기본 카운터
    세트만 읽는다. `qp.c:4300-4313`: verbs QP는 RESET에서 INIT으로 갈 때 커널이 그 세트에 묶는다. DEVX QP는 사용자
    공간이 QP 문맥을 직접 쓰므로 이 경로를 거치지 않는다.
- `[추론]` 다음 설명이 원자료와 모두 맞는다. NIC는 재전송 타임아웃 뒤 전송률을 낮추는 기능(slow restart)이
  재전송마다 혼잡 알림을 내부에서 하나 만들고(`roce_slow_restart_cnps`), 반응 쪽 혼잡 제어가 그것을 처리했다고
  센다(`rp_cnp_handled`). 실제 혼잡이나 상대가 보낸 혼잡 알림 패킷이 아니다.
  - 두 노드는 직결이라 선 위의 혼잡 알림은 sunny NIC만 보낼 수 있는데, sunny의 `np_cnp_sent`는 +0이다.
  - `[소스]` 재시도 초과까지 NIC는 적응 재전송(`roce_adp_retrans`) 뒤 정규 타임아웃 R-1번을 겪고, 마지막 정규
    타임아웃은 재전송하지 않고 오류 완료를 만든다(`harness/ack_timeout/NOTES.md:39-42`). 재시도 7에서 정규 타임아웃은
    6이고 재전송은 적응 재전송 + 5다. 이것이 `rp_cnp_handled` = `roce_adp_retrans` + 5와 맞는다.
  - DEVX QP에서도 오르는 것은 혼잡 통계가 장치 단위이고 q 카운터는 세트 단위이기 때문이다.
- 지금 원자료에는 "타임아웃은 났지만 오류는 없는" 시행이 없다. 그래서 카운터가 재전송 타임아웃을 세는지, 재시도
  초과라는 사건을 세는지 아직 가를 수 없다. 이 실험의 일시 장애 셀(A6)이 이것을 가른다.

### 1.3 기존 결과와 충돌한 것

원자료를 따른다. 다른 실험의 문서는 고치지 않는다(`CLAUDE.md` 규칙 14). 고칠지는 사용자가 정한다.

- **sunny의 혼잡 알림 처리 카운터.** propagation 문서(`EXPERIMENT.md:279-282`, `README.md:54-55`)는 이 카운터가
  "다른 장애와 장애 없음에서는 한 번도 오르지 않았다"고 적는다. `[측정]` 원자료에서는 sunny에서 NVSHMEM devel의 로컬
  QP 오류 20/20(자동 처리 방식 10, CPU 프록시 처리 방식 10)에서 9–12 올랐다. 이 장애는 rain의 QP를 오류로 만든다
  (`harness/gpu-initiated/nvshmem/run_trial.sh:41`, 3번째 줄 주석: PE0이 rain). 문서의 문장은 요청 쪽 노드(rain)에서만
  맞다. `[추론]` sunny 쪽 PE도 rain으로 RDMA를 보내고, 오류가 된 rain QP가 응답하지 않아 sunny NIC가 재전송했다고 보면
  1.2의 설명과 맞는다.
- **CPU 하네스의 `peer_alive`, `auto_recoverable` 열.** `[측정]` 상대 QP 오류 40/40에서 두 열이 `0, 0`이다. 생존
  확인이 응답을 받아도 `classify()`의 기본값(`harness/common/probe.c:677-680`)을 고치지 않는 라벨 버그다
  (`harness/README.md:41`). 이 열을 그대로 세면 살아 있는 상대가 모두 오판처럼 보인다. 이 실험은 생존 확인의 결정인
  `sub_cause`로만 판정을 읽고, 두 열은 기록만 한다. `classify()`는 고치지 않는다.

### 1.4 연구 질문

1. 소프트웨어로 만들 수 있는 "살아 있지만 준비 안 된" 상대 상태(QP가 RESET, INIT, RTR, 새 QPN, 잠깐 준비 안 됨,
   프로세스 정지, 제어 연결만 닫힘)는 요청 쪽에서 어떤 오류 코드, 시간, 카운터로 보이는가. 죽은 상대와 구분되는가.
2. CPU 하네스의 생존 확인과 GIN GDAKI 복구(장치 쪽 분류기 + 생존 확인 + 핸드셰이크 마감)는 이 상태들에서 상대를
   "죽음" 또는 "복구 불가"로 판정하는가. 판정을 가르는 것은 무엇인가.
3. 오판이 생기는 경계를 소스의 상수(제어 응답 대기 1 s, 핸드셰이크 마감 3 s)만으로 미리 맞힐 수 있는가.
4. `rp_cnp_handled`는 재전송마다 오르는가. 오류 없이 회복된 타임아웃에서도 오르는가.

## 2. 가설

- **데이터 경로는 프로세스 생존을 모른다(가설 1).** 요청을 받을 수 없는 응답 쪽 QP(ERR, RESET, INIT, 없는 QPN)는
  프로세스가 살아 있든 죽었든 같은 12/0x81을 같은 시간(3.40–3.90 s)에 만든다. 요청을 받을 수 있는 QP(RTR, RTS)는
  프로세스가 멈춰 있어도 단방향 쓰기를 정상 완료한다.
  - 반증: QP가 RESET, INIT이거나 새 QPN인 셀에서 12/0x81이 아닌 코드나 범위 밖 시간이 나온다. QP가 RTR인 셀이나
    정상 QP + 정지 셀에서 오류 완료가 나온다.
- **탐지기는 프로세스가 아니라 제어 연결을 본다(가설 2).** "죽음"은 제어 연결이 닫히거나 끊길 때만, "복구 불가"나
  "미확정"은 제어 응답이 탐지기의 마감보다 늦을 때만 나온다. 그래서 살아 있는 상대도 제어 연결을 닫으면 죽음으로,
  마감보다 오래 멈추면 복구 불가로 판정된다. 그 밖의 살아 있는 상대는 오판되지 않는다.
  - 반증: 제어 연결이 열려 있고 마감 안에 응답하는 셀에서 죽음이나 거절이 나온다. 또는 제어 연결을 닫은 셀이나
    마감보다 오래 멈춘 셀에서 오판이 나오지 않는다.
- **혼잡 알림 처리 카운터는 재전송을 센다(가설 3).** `rp_cnp_handled`는 타임아웃으로 생긴 재전송 하나에 하나씩 오르는
  NIC 내부 알림이다. 오류가 나지 않아도 재전송이 있으면 오르고, ACK 타임아웃이 없으면(수신 버퍼 없음의 RNR 재시도
  포함) 오르지 않는다.
  - 반증: ACK 타임아웃이 있는데 +0인 시행. verbs QP에서 `rp_cnp_handled`와 `roce_slow_restart_cnps` 증가량이 다른 시행.
    ACK 타임아웃이 없는 셀에서 증가. 어느 노드에서든 `np_cnp_sent`나 `np_ecn_marked_roce_packets` 증가.

## 3. 사전 예측

예측 원문은 [predictions.csv](predictions.csv)(측정 34줄, 소스 8줄)이고 해시는 [PREREG.txt](PREREG.txt)에 있다. 이
절의 표는 요약이다. 판정은 `predictions.csv`의 `acceptance` 열을 아래 규칙으로 그대로 계산한다.

### 3.0 판정 규칙과 필드

**판정 함수.** `score.py`는 다음을 그대로 구현한다.
- `n`: 셀의 채점 시행 수(8절 제외 뒤). 카운터 줄(K)은 evrec 끝 기록이 있는 시행만, 오판 줄(O)은 실제 생존을 정할 수
  있는 시행만 센다.
- `ALL(식)`: n개 시행 모두에서 식이 참.
- `MOST(식)`: 식이 참인 시행이 ceil(0.9 x n) 이상이고, 식의 필드가 모두 기록됐는데 거짓인 시행이 0. 필드가 비었거나
  파일이 없는 시행은 "관측 불가"로 따로 센다. 5회 셀에서는 5/5다.
- `NONE(식)`: 식이 참인 시행이 0.
- 줄의 판정식이 `and`로 이어지면 모두 참일 때 맞음. 여러 셀에 걸친 줄은 셀마다 따로 계산해 모두 참일 때 맞음.
  "per cell over trials with status==12"는 그 셀에서 `status==12`인 시행만 n으로 센다.
- 결과는 맞음, 틀림, 자료 없음(n=0) 셋이다. 놓친 시행은 모두 목록으로 낸다.
- 비교: 정수 필드는 정수로, `vendor_err`는 소문자 16진 문자열(`0x81`)로, 나머지는 문자열 그대로 비교한다.

**CPU 하네스 필드(1부).** 시행마다 `A/runs/<tag>/`에 `run.sh`가 쓰는 파일 셋이 있다. `tag`는 `lp_<장애 이름>_t<n>`이다.
- `<fault>_<stamp>.csv` 한 줄: `status`, `vendor_err`, `detect_ns`, `sub_cause`, `peer_alive`, `srv_qp_state`, `srv_async`,
  `verify_ok`(기존 열), 그리고 새 열 `cqe_ns`(게시부터 첫 CQE까지, status와 무관, CQE가 없으면 -1), `t_post_mono_ns`
  (게시 시각, CLOCK_MONOTONIC), `truth_alive`(1, 0, 정할 수 없으면 -1), `truth_how`(`ctl`, `alive_q`, `refused`,
  `no_reply`), `resync_ms`, `stale_lines`.
- `<fault>_<stamp>.srv.log`(서버 로그): `[server] fault_applied fault=<f> mono_ns=<n>`, `[server] stall_begin mono_ns=<n>
  ms=<n>`, `[server] stall_end mono_ns=<n>`, `[server] rearm mono_ns=<n> rq_psn=<n>`.
- `truth_alive`: 판정(첫 CQE 뒤 생존 확인, 생존 확인이 없으면 첫 CQE) 뒤에 서버가 기존 제어 연결로 답을 하나라도
  보냈으면 1(`ctl`). 그렇지 않으면 새 TCP 연결로 `ALIVE?`를 보내 같은 서버가 `ALIVE <pid> <QP 상태>`로 답하면
  1(`alive_q`), 연결이 거부되면 0(`refused`), 5 s 안에 답이 없으면 -1(`no_reply`).

**GIN 필드(2부).** 시행마다 `B/logs/rec1_<F3|none>_timeout_<tag>_{r0.kv,r1.kv,meta.txt,r0.log,r1.log}`. `tag`는
`b<k>_t<n>`이다.
- `rec_outcome`, `rec_reason`, `rec_t_prep`, `rec_t_ack`, `rec_t_decl`: r0 kv의 첫 `rec ev=` 기록의 `outcome`, `reason`,
  `t_prep`, `t_ack`, `t_decl`(ms, rank 0 시계).
- `fault_t_query`: r0 kv의 첫 `fault ev=` 기록의 `t_query`. `n_fault_ev`, `n_rec_ev`: r0 kv의 두 기록 수.
- `r0_iters_ok`, `r1_iters_ok`, `r1_data_check`: 각 rank kv의 마지막 `iters_ok=` 기록의 `iters_ok`, `data_check`.
- `r0rc`: meta의 `r0rc`. `r1_alive_at_r0_exit`: meta의 새 키(기록만, 판정에 쓰지 않음).
- `r1_stall_end_r0clock` = r1 kv 새 기록 `stall on=<req|iter> it=<n> ms=<n> begin_mono_ms=<x> end_mono_ms=<x>
  measured_ms=<x>`의 `end_mono_ms` - r0 kv의 `clock_offset_ms`.
- `r1_n_rxrec_after_stall`: r1 kv에서 `stall` 기록 뒤에 나온 `rxrec` 기록 수.

**카운터 필드(공통).** `rain.<이름>`, `sunny.<이름>` = 그 시행의 `<tag>.evrec.rain`, `<tag>.evrec.sunny`에서
`hw_counters/<이름>`의 끝 값 - 시작 값. 표본(`smp mono_ns=<n> <이름>=<값> ...`)이 있는 셀은 다음도 계산한다.
- `smp_diff_max`: 표본마다 |(`rp_cnp_handled` - 시작 값) - (`roce_slow_restart_cnps` - 시작 값)|의 최댓값.
- `smp_first_inc_ns`: `rp_cnp_handled`가 시작 값보다 처음 큰 표본의 `mono_ns`.
- `smp_last_inc_ns`: `rp_cnp_handled`가 끝 값에 처음 닿은 표본의 `mono_ns`.

### 3.1 소스 예측: 기존 탐지기가 살아 있는 상대를 어떻게 판정하나 `[소스]`

줄 번호는 2026-10-07에 master `3dbf995e`에서 다시 확인했다. 측정하는 것은 CPU 하네스와 GIN GDAKI 복구 v2 두 줄이다.

| id | 탐지기 | 생존 신호와 죽음 판정 | 복구 불가 판정과 마감 | 예측: 마감보다 오래 멈춘 상대 | 예측: 제어 연결만 닫은 상대 |
|---|---|---|---|---|---|
| S1 | CPU 하네스(`harness/client/probe_client.c:440-465`) | 제어 연결의 PROBE. EOF나 RST면 죽음(`:457-461`) | 1 s 안에 답이 없으면 "응답 없음", `auto_recoverable=0`(`:444`, `:452-456`) | 미확정(복구 불가 라벨) | 죽음(오판) |
| S2 | GIN GDAKI 복구 v2(`gpu-initiated/gin_recovery/gin_rec.cu`) | 관리망 소켓 `peerAlive()`. FIN, ECONNRESET, EPIPE, ETIMEDOUT, ENOTCONN이면 죽음(`:160-169`). 재시도 초과 + 죽음이면 거절(`:444-450`) | ACK 마감 3000 ms를 넘으면 거절(`:461`, `:472`, `:613`). 설계 문서는 "응답 없는 상대는 죽은 것으로 본다"(`RECOVERY_DESIGN.md:37-40`) | 3 s를 넘으면 거절(오판) | 죽음(오판) |
| S3 | NCCL 2.23.4 net_ib 복구 2단계(`nccl-integration/stage2/net_ib_stage2.diff`) | FIN만 죽음(`:528-541`). 소켓 오류는 관리망 상실로 보고 복구를 끈다(`:468-481`, `:568-586`) | ACK 마감 5000 + 30000 ms(`:171-177`, `:1166`, `:1173`) | 35 s를 넘으면 실패(오판) | 죽음(오판) |
| S4 | GIN 투명 복구 1단계(`gin_recovery/gin_transparent_s1.diff`) | FIN이나 EAGAIN 아닌 모든 소켓 오류면 죽음(`:3070-3077`, `:3497-3498`). keepalive 2 s + 1 s x 3, `TCP_USER_TIMEOUT` 5 s(`:3005-3015`). 멈춘 상대의 커널은 keepalive에 답한다 `[추론]` | ACK 마감 3000 + 5000 + 1000 ms(`:2834-2836`, `:3549-3558`) | 9 s를 넘으면 거절(오판) | 죽음(오판) |
| S5 | NVSHMEM 장애 대응판 v2(`nvshmem_ft/nvshmem_ft_v2.cu`) | FIN, RST, EPIPE, ETIMEDOUT, ENOTCONN이면 죽음(`:200-212`, `:1061-1062`) | ACK 마감 5000 ms(`:1093`, `:1107-1108`) | 5 s를 넘으면 거절(오판) | 죽음(오판) |
| S6 | NVSHMEM 투명 복구(`nvshmem_ft/nvshmem_ibgda_transparent.diff`) | FIN만 죽음. RST나 keepalive 시간 초과는 경로 상실로 다시 연결(`:4013-4041`) | ACK 마감 5000 + 30000 ms(`:5085-5092`, `:5447-5448`) | 35 s를 넘으면 거절(오판) | 죽음(오판) |
| S7 | GDAKI 장치 쪽 분류기만(`gin_q4`) | 생존 확인 없음. 12/0x81을 "상대 QP 오류 또는 상대 kill"로 둔다(`gin_q4/NOTES.md:243-246`) | 없음 | 판정 없음 | 판정 없음 |
| S8 | teardown_order가 제안한 분류 규칙(구현 안 됨) | CQE 뒤 1 s 안에 EOF, RST가 오거나 PROBE에 답이 없으면 죽음(`teardown_order/NOTES.md:308-322`) | 없음 | 죽음(오판) | 죽음(오판) |

`[추론]` 공통점: 어느 탐지기도 프로세스 존재를 직접 보지 않는다. 오판의 원인은 제어 연결의 종료를 죽음과 같게 보는
것과, 마감을 넘는 느린 응답을 복구 불가와 같게 보는 것이다(Chandra, Toueg 1996의 정확성 위반). CPU 하네스는
2026-09-25부터 응답 없음을 죽음과 따로 센다(`harness/NOTES.md:84-92`). 상대 프로세스를 멈춰도 오류 완료가 없으면(NIC가
계속 ACK) 어떤 탐지기도 작동하지 않는다.

### 3.2 측정 예측 요약

| id | 셀 | 예측 | 판정 요약(원문은 csv) |
|---|---|---|---|
| A0 | 장애 없음 | 10 ms 안에 정상 완료, 생존 확인 없음 | 모두 |
| A1 | 응답 QP ERR, 프로세스 응답 | 12/0x81, 3.40–3.90 s, "살아 있음, QP 오류", QP 상태 ERR | 모두 |
| A2 | 응답 프로세스 SIGKILL | 12/0x81, 죽음 판정, 실제로 죽음 | 모두 |
| A3a, A3b | 응답 QP RESET | 12/0x81, 3.40–3.90 s, "살아 있음, QP 오류", QP 상태 RESET, 비동기 이벤트 없음 | 90% 이상, 예측 밖 0. 시간과 이벤트는 모두 |
| A4a, A4b | 응답 QP INIT | A3과 같고 QP 상태 INIT | 같음 |
| A5 | 응답 QP를 같은 PSN으로 RTR까지만 | 10 ms 안에 정상 완료, QP 상태 RTR | 완료와 시간은 모두 |
| A6 | 응답 QP를 1250 ms 동안 INIT, 그 뒤 같은 PSN으로 RTS | 오류 없이 1.25–1.80 s에 완료, QP 상태 RTS | 완료와 시간은 모두 |
| A7a, A7b | 응답 QP ERR + 프로세스 8 s 정지 | 12/0x81, 3.40–3.90 s, "응답 없음"(죽음 0회), 재개 뒤 복구와 검증 성공, 실제로 살아 있음 | 90% 이상, 죽음 0, 생존 모두 |
| A8 | 정상 QP + 프로세스 8 s 정지 | 10 ms 안에 정상 완료, 상태 조회 응답 없음, 판정 없음, 재개 뒤 복구 성공 | 완료와 판정 없음은 모두 |
| A9a, A9b | 응답 QP ERR + 살아 있는 프로세스가 제어 연결만 닫음 | 12/0x81, 3.40–3.90 s, 죽음 판정, 새 연결의 생존 질의에 같은 프로세스가 답함 | 90% 이상 |
| A10 | 수신 버퍼 없음 | 13/0x87, 11.5–13.5 ms, 생존 확인 없음 | 모두 |
| A11 | 응답 QP 파괴 뒤 새 QP INIT | 12/0x81, 3.40–3.90 s, "살아 있음, QP 오류", QP 상태 INIT | 모두 |
| B0 | GIN 상대 QP 오류, 정지 없음 | 복구, ACK는 Prepare 뒤 500 ms 안 | 모두 |
| B1 | GIN 상대 QP 오류 + 복구 요청 수신 때 1000 ms 정지 | 복구, ACK는 Prepare 뒤 1000–1500 ms | 90% 이상, 거절 0, 시간은 모두 |
| B2a, B2b | GIN 상대 QP 오류 + 복구 요청 수신 때 6000 ms 정지 | 핸드셰이크 시간 초과로 거절(장애 조회 뒤 3000–3500 ms), rank 0 종료 코드 9. rank 1은 거절 뒤 재개해 요청을 처리 | 90% 이상, 복구 0, 시간은 모두 |
| B3 | GIN 장애 없음 + 반복 60의 장벽 응답 직후 6000 ms 정지 | 장애 기록 없음, 복구 없음, 120회 모두 정확 | 모두 |
| O1 | 1부 전체 | 죽음 오판은 제어 연결만 닫은 셀(A9)에만 | 그 셀 90% 이상, 나머지 0(SIGKILL 셀 제외) |
| O2 | 1부 전체 | 복구 불가 오판은 정지 + QP 오류(A7)와 제어 연결 닫음(A9)에만 | 두 셀 90% 이상, 나머지 0 |
| O3 | 2부 전체 | GIN 거절 오판은 6 s 정지(B2)에만 | 그 셀 90% 이상, 나머지 0 |
| O4 | 정상 QP + 정지, GIN 장애 없음 + 정지 | 놓친 정지: 오류도 판정도 없음 | 모두 |
| K1 | 모든 시행, 두 노드 | 실제 혼잡 신호 +0 | 모두 |
| K2 | 1부의 재시도 초과 시행, rain | `rp_cnp_handled` = `roce_slow_restart_cnps` = 적응 재전송 + 정규 타임아웃 - 1, 정규 타임아웃 6 | 같음은 모두, 나머지 90% 이상 |
| K3a, K3b, K3c | 일시 장애(A6), rain | 오류 없이 `rp_cnp_handled`가 오르고 `roce_slow_restart_cnps`와 같다. 적응 재전송 + 정규 타임아웃과 같다. 정규 타임아웃 2 | 첫째는 모두, 나머지 90% 이상 |
| K4 | ACK 타임아웃 없는 셀(A0, A5, A8, A10, B3), rain | `rp_cnp_handled`, `roce_slow_restart_cnps`, `local_ack_timeout_err` +0 | 모두 |
| K5 | 1부 전체, sunny | `rp_cnp_handled` +0 | 모두 |
| K6 | GIN 상대 QP 오류 셀, rain과 sunny | rain `rp_cnp_handled` 8 이상, q 카운터 +0. sunny +0 | 모두 |
| K7 | QP ERR 재현, QP RESET, 일시 장애(A1, A3, A6), rain 50 ms 표본 | 표본마다 두 카운터 차이 1 이하, 게시와 첫 CQE + 100 ms 사이에만 증가 | 모두 |

## 4. 범위

- **포함:**
  - CPU verbs 하네스(`harness/`)에 응답 쪽 "살아 있지만 준비 안 된" 상태 일곱 가지를 새로 넣고, 재현 네 칸, 대조 한
    칸과 함께 잰다(1부).
  - GIN GDAKI 복구 v2(장치 쪽 분류기 + 복구, 번들 `gin_recovery_gpudb`)에서 상대 정지와 핸드셰이크 마감의 관계를
    잰다(2부).
  - 두 노드의 포트 카운터(시작, 끝, 일부 셀은 50 ms 표본)와 혼잡 통계.
  - 3.1의 소스 예측 표(측정하지 않는 탐지기 포함).
- **제외:**
  - NCCL net_ib 복구 2단계, GIN 투명 복구, NVSHMEM 장애 대응판과 투명 복구의 마감 경계: 소스 예측만 둔다. 마감이
    5–35 s라 셀마다 시행이 길고, 이번 질문에는 측정 탐지기 둘로 충분하다.
  - 관리망 TCP를 RST나 시간 초과로 끊는 경우: 방화벽 같은 호스트 설정 변경이 필요하다.
  - 응답 PSN을 다르게 재무장하는 경우: 요청 PSN이 응답 쪽 창의 앞인지 뒤인지에 따라 결과가 갈려 예측 근거가 부족하다.
  - 실제 link down, 링크 흔들기, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, NIC 펌웨어나 스위치 설정
    변경, 혼잡 제어 매개변수 변경.
  - slow restart나 적응 재전송을 끄는 인과 시험: NIC 펌웨어 레지스터 변경이 필요하다.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(요청, rank 0), sunny(응답, rank 1), 100 GbE RoCE v2 직결 | 루트 `README.md` 테스트베드 |
| NIC와 펌웨어 | ConnectX-6, rain `mlx5_0`, `mlx5_1` 20.43.4100, `mlx5_1` 포트 1 ACTIVE | `[측정]` rain sysfs `fw_ver`, `ports/1/state`, 2026-10-07. sunny는 2026-10-06 propagation 5절의 값, 실행 전 다시 읽는다 |
| 커널, OFED | rain 5.15.0-97, OFED-internal-23.10-7.1.8 / sunny 6.8.0-138, OFED 25.10-1.7.1 | `[측정]` rain `uname -r`, `ofed_info -s`, 2026-10-07. sunny는 2026-10-06 |
| DCQCN 설정 | rain `ens4f1np1` 반응 쪽, 알림 쪽 모두 우선순위 0–7 켜짐 | `[측정]` rain sysfs `ecn/*/enable/*`, 2026-10-07. sunny는 실행 전 읽기만 한다 |
| 커널 로그 | rain `dmesg`는 sudo 없이 읽힌다(`kernel.dmesg_restrict=0`). sunny는 sudo 없이 읽히지 않아 8절대로 rain만 검사한다 | `[측정]` 2026-10-07 19:29 |
| GIN 번들 | `~/gi-bundle/gin_recovery_gpudb`: `gin_rec` md5 `89e72d50`, `libnccl.so.2.32.3` md5 `1ed8e0a1` | `[측정]` rain md5sum, 2026-10-07. N30 기록(`gpu-initiated/N30_20260925.md:42`)과 같다. sunny는 실행 전 확인 |
| 새 GIN 드라이버 | 위 libnccl(md5 `1ed8e0a1`) + 정지 장치를 더한 `gin_rec` md5 `fac97c8c`, `~/gi-bundle/gin_recovery_gpudb_stall` | `[측정]` 두 노드 md5sum, 2026-10-07 19:29 배포 블록. 기존 `gin_rec`과의 차이는 [DEVIATIONS.md](DEVIATIONS.md) 4 |
| 새 evrec | 표본 기능을 더한 evrec md5 `3f93b3a9`, `~/gi-bundle/evrec2/evrec` | `[측정]` 두 노드 md5sum, 같은 배포 블록 |
| CPU 하네스 | rain `probe_client` `4b6c2b10`, `probe_server` `372c820a`(이 worktree에서 빌드) / sunny `probe_client` `486e8913`, `probe_server` `c6f0bd96`(`~/rdma-error-lp/harness`에서 빌드). 소스는 커밋 `f288469e` | `[측정]` md5sum, 같은 배포 블록. `run.sh`가 시행마다 다시 빌드하므로 소스가 같으면 바이너리도 같다 `[추론]` |
| GPU와 CUDA | rain Quadro RTX 5000, sunny RTX A4000, CUDA 12.8 | propagation 5절 |

## 6. 변수

- **독립변수:**
  - 응답 쪽 QP 상태: ERR, RESET, INIT, RTR, 1250 ms 동안 INIT 뒤 RTS, 새 QPN(INIT), 정상.
  - 응답 프로세스 상태: 응답, 8000 ms 정지, 제어 연결만 닫음, SIGKILL.
  - GIN 셀의 정지 시간(0, 1000, 6000 ms)과 정지 시점(복구 요청 수신, 반복 60의 장벽 응답 직후).
- **종속변수:**
  - 요청 쪽 첫 CQE의 status와 vendor_err, 게시부터 첫 CQE까지 시간.
  - 판정: CPU 하네스 `sub_cause`(기록용 `peer_alive`, `auto_recoverable`), GIN rank 0의 복구 결과와 이유, 시각.
  - 실제 생존(3.0의 `truth_alive`, `r1_stall_end_r0clock`, `r1_n_rxrec_after_stall`).
  - 응답 쪽 QP 상태와 비동기 이벤트(`srv_qp_state`, `srv_async`).
  - 두 노드 `hw_counters`와 `counters` 전체의 시작과 끝, 일부 셀의 50 ms 표본.
- **통제변수:** IB 타임아웃 14, 재시도 7, RNR 재시도 6(`harness/common/probe.c:270-272`), PMTU 4096, CPU 하네스는 4 KiB
  쓰기 하나와 복구 방식 `qp_only`. GIN은 v2 번들, 반복 120, 간격 15 ms, `INJECT=600`, 대기 방식 `timeout`,
  `WATCHDOG_S=60`. 시행마다 새 프로세스 쌍. `cluster_run.sh` 락과 유휴 링크.
- **오판의 정의:** 실제 생존이 1인데
  - 죽음 오판: CPU 하네스 `sub_cause=proc_kill`, GIN 거절 이유 `retry_exc_peer_dead` 또는 `peer_closed_during_handshake`.
  - 복구 불가 오판: CPU 하네스 `sub_cause`가 `proc_kill`이나 `no_answer`, GIN 복구 결과 `declined`(이유 무관).
  - `peer_alive`, `auto_recoverable` 열은 라벨 버그 때문에 쓰지 않는다(1.3).
- **놓친 정지:** 응답 프로세스가 멈췄는데 요청 쪽 어느 계층에도 오류나 판정이 없음.

## 7. 실험 셀, 반복 수, 대조군

반복 규칙은 새 칸 10, 재현 칸 5, 대조 5다. 모든 시행은 새 프로세스 쌍이다.

| 셀 | 조건 | 반복 수 | 대조군 여부 |
|---|---|--:|---|
| A0 | 장애 없음(`none`) | 5 | 대조 |
| A1 | 응답 QP ERR, 프로세스 응답(`retry_server_qp_err`) | 5 | 재현 |
| A2 | 응답 프로세스 SIGKILL(`retry_proc_sigkill`) | 5 | 재현, 죽은 상대 대조 |
| A3 | 응답 QP RESET(`live_qp_reset`) | 10 | 새 칸 |
| A4 | 응답 QP RESET 뒤 INIT(`live_qp_init`) | 10 | 새 칸 |
| A5 | 응답 QP를 같은 PSN으로 RTR까지만(`live_qp_rtr`) | 10 | 새 칸 |
| A6 | 응답 QP 1250 ms 동안 INIT, 그 뒤 같은 PSN으로 RTS(`live_transient`) | 10 | 새 칸 |
| A7 | 응답 QP ERR + 프로세스 8000 ms 정지(`live_stop_err`) | 10 | 새 칸 |
| A8 | 정상 QP + 프로세스 8000 ms 정지(`live_stop_ok`) | 10 | 새 칸 |
| A9 | 응답 QP ERR + 제어 연결만 닫음(`live_ctl_close`) | 10 | 새 칸 |
| A10 | 수신 버퍼 없음(`rnr`) | 5 | 재현 |
| A11 | 응답 QP 파괴 뒤 새 QP INIT(`live_qp_recreate`) | 5 | 재현(teardown_order의 살아 있는 QP 파괴) |
| B0 | GIN 상대 QP 오류(F3), 정지 없음 | 5 | 재현 |
| B1 | GIN 상대 QP 오류 + 복구 요청 수신 때 1000 ms 정지 | 10 | 새 칸 |
| B2 | GIN 상대 QP 오류 + 복구 요청 수신 때 6000 ms 정지 | 10 | 새 칸 |
| B3 | GIN 장애 없음 + 반복 60의 장벽 응답 직후 6000 ms 정지 | 5 | 대조(정지 장치 자체 검사) |

합계: 1부 95회, 2부 30회, 모두 125회. smoke는 셀마다 1회(16회)이고 채점하지 않는다.

## 8. 제외 기준과 중단 기준

- **제외 기준:**
  - smoke 실행(`results/<날짜>_smoke/`)은 채점하지 않는다.
  - **장애 미적용:** 1부에서 서버 쪽 장애 셀(A1, A3–A9, A11)의 서버 로그에 `fault_applied` 기록이 없거나, SIGKILL 셀
    (A2)에 기존 `[server] proc_sigkill` 줄이 없는 시행. 정지 셀(A7, A8)에 `stall_end` 기록이 없는 시행. 2부에서 상대 QP 오류 셀(B0–B2)의
    r0 kv에 `fault ev=` 기록이 없거나, 정지 셀(B1–B3)의 r1 kv에 `stall` 기록이 없는 시행. 따로 센다.
  - **실행기 실패:** ssh 실패, 서버 시작 실패 등 예측 대상이 아닌 이유로 CSV 행이나 kv가 없는 시행. 따로 센다.
  - 장애 미적용과 실행기 실패를 채우는 추가 시행: 실행기가 셀 끝에서 자동으로, 위 두 조건만 보고(결과 필드를 보지
    않고) 같은 설정으로 셀마다 계획 n의 30%(올림)까지 더 돌린다. 추가 수와 이유는 12절에 적는다.
  - **카운터 관측 불가:** evrec 끝 기록이 없으면 그 시행은 카운터 줄(K)의 분모에서만 뺀다.
  - **실제 생존 미정:** `truth_alive=-1`이거나 r1 kv가 없으면 오판 줄(O)의 분모에서만 뺀다.
- **중단 기준과 안전 규칙:**
  - 모든 클러스터 명령(배포, smoke, 본 실행)은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다.
    이 세션의 다른 실험 두 개가 같은 락을 쓰므로 대기 상한을 10800 s로 둔다. 상한 안에 락이나 유휴 링크를 얻지
    못하면 그 부를 미룬다. `prio-` 작업이 기다리면 양보한다.
  - 하지 않는 일: 실제 link down이나 링크 흔들기, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, NIC
    펌웨어나 스위치 설정 변경.
  - 프로세스는 우리가 띄운 것만, 정확한 이름(`probe_server`, `probe_client`, `gin_rec`, `lp_stall`, `evrec`) 일치나
    PID로 끈다. 시행을 끝내기 전에 두 노드에서 그 이름의 프로세스 중 정지 상태(`ps` 상태 `T`)인 것에 `kill -CONT`를
    먼저 보낸다. 다른 사용자의 작업(gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 작업)은 건드리지 않는다.
  - 시행이 끝난 뒤에도 우리 프로세스가 남아 있으면(정리 뒤 5 s) 캠페인을 멈춘다. 그 PID에만 `kill -CONT`, `kill`을
    보내고 원인을 13절에 적은 뒤 재개 여부를 정한다.
  - 커널 로그: 캠페인 시작 전과 시행마다 rain의 `dmesg`에서 mlx5 명령 오류 줄 수를 센다(정규식
    `mlx5.*(mlx5_cmd_out_err|mlx5_cmd_check|wait_func|cmd_work_handler|failed, status|Will cause a leak)`). 줄 수가
    늘면 즉시 멈춘다. sunny는 sudo 없이 `dmesg`가 읽히면 같은 검사를 하고, 읽히지 않으면 12절에 적고 rain만 검사한다.
  - 포트가 ACTIVE가 아니게 되면 즉시 멈춘다.
  - 복구 뒤 검증 실패(`verify_ok=0`)나 GIN `data_check` 실패가 나오면 멈춘다. 그 시행은 그대로 채점한다.
  - 멈춘 뒤 재개는 13절에 날짜, 이유, 영향 범위를 적은 뒤에만 한다.

## 9. 실행 방법과 경로

### 9.0 원칙

- 1부는 기존 CPU 하네스(`harness/run.sh`, `probe_client`, `probe_server`)를 확장하고, 시행 감싸기는 propagation의
  `campaign/evrec_pair.sh`를 쓴다. 셀 실행 방식은 propagation `campaign/cells.sh:34-41`과 같다(시행마다 `run.sh`를
  `ITERS=1`로 부른다).
- 2부는 `gpu-initiated/gin_recovery/gin_rec.cu`와 `scripts/run_trial.sh`를 확장한다. libnccl은 바꾸지 않는다.
- 기존 동작은 기본값에서 그대로다. 새 동작은 새 장애 이름과 새 환경변수에서만 켜진다. 끝난 실험의 코드(evrec,
  `evrec_pair.sh`, GIN `run_trial.sh`)를 바꾸는 것은 13절에 적는다.
- 정지는 신호를 받을 프로세스가 직접 만든 도우미 자식 프로세스(이름 `lp_stall`, `prctl(PR_SET_NAME)`)가 부모에게
  `SIGSTOP`과 `SIGCONT`를 보내 만든다. 도우미는 장치, CUDA, 파일을 열기 전에 `fork`하고, 읽기, 쓰기, `nanosleep`,
  `kill`, `_exit`만 쓴다. 파이프가 닫히거나 부모가 바뀌면 끝난다.

### 9.1 CPU 하네스 변경(1부)

1. `harness/common/probe.h`, `probe.c`
   - `fault_type_t`의 `FAULT__COUNT` 앞에 새 장애 여덟 개를 더한다(기존 번호 유지): `live_qp_reset`, `live_qp_init`,
     `live_qp_rtr`, `live_transient`, `live_stop_err`, `live_stop_ok`, `live_ctl_close`, `live_qp_recreate`.
   - `ep_query_psns()`: `ibv_query_qp(IBV_QP_SQ_PSN | IBV_QP_RQ_PSN)`. `[소스]` mlx5는 QP 문맥의 `next_rcv_psn`,
     `next_send_psn`을 돌려준다(리눅스 6.10.8 `qp.c:4958-4959`).
   - `ep_rearm(remote, rq_psn, sq_psn, to_rts)`: RESET, INIT, 저장한 상대 정보의 PSN만 `rq_psn`으로 바꾼 RTR,
     `to_rts`면 RTS. `[소스]` RESET에서 RESET으로도 갈 수 있다(`qp.c:4110-4113`).
   - `stall_helper_start()`, `stall_self(ms)`: 9.0의 도우미. `stall_self`는 명령을 쓰고 응답(정지, 재개 시각)을 읽을 때까지
     막힌다. `EINTR`이면 다시 읽는다.
   - `classify()`는 고치지 않는다.
2. `harness/server/probe_server.c`
   - `main` 맨 앞(장치 열기 전)에 `stall_helper_start()`.
   - `connect_qp_server`가 받은 상대 정보를 정적 변수에 저장한다.
   - GO 처리에 새 장애를 넣고, 모든 서버 쪽 장애(기존 `retry_server_qp_err` 포함)에서 `fault_applied` 기록을 쓴다.
     - RESET: `ep_to_reset`. INIT: RESET 뒤 `ep_to_init`. 새 QP: `ep_destroy_qp`, `ep_create_qp`, `ep_to_init`.
     - RTR: `ep_query_psns` 뒤 `ep_rearm(to_rts=false)`.
     - 일시 장애: `ep_query_psns`, RESET, INIT, GOACK, GOACK 시각에서 `LIVE_TRANSIENT_MS`(1250) 뒤 `ep_rearm(to_rts=true)`,
       `rearm` 기록.
     - 정지 + QP 오류: `ep_to_err`, GOACK, `stall_self(LIVE_STOP_MS)`(8000). 정지 + 정상 QP: GOACK, `stall_self`.
     - 제어 연결 닫음: `ep_to_err`, GOACK, `shutdown`, `close`. 듣기 소켓은 열어 둔 채 20 s까지 새 연결을 받아
       `ALIVE?`에 `ALIVE <pid> <QP 상태>`로 답하고 정상 종료한다.
   - 시행 안 명령 루프에 `RESYNC <n>`에 `RESYNCED <n>`으로 답하는 줄을 더한다(지금은 모르는 줄이면 시행을 끝낸다).
3. `harness/client/probe_client.c`
   - 새 장애는 장애 없음처럼 4 KiB 쓰기 하나를 게시하고 `poll_one`으로 첫 CQE를 status와 무관하게 받는다. 게시 시각을
     `t_post_mono_ns`로, 첫 CQE까지를 `cqe_ns`로 남긴다(모든 장애에서).
   - 생존 확인과 상태 조회 코드는 그대로 둔다. 측정 대상이다.
   - 정지 셀: 상태 조회 뒤 `RESYNC`를 보내고 `RESYNCED`가 올 때까지(최대 20 s) 늦게 온 줄을 읽어 버린다. 버린 줄 수와
     걸린 시간을 `stale_lines`, `resync_ms`에 쓴다.
   - `sub_cause=proc_kill`이면 복구와 검증을 건너뛴다(지금은 장애 종류로만 건너뛴다).
   - 행을 쓰기 전에 `truth_alive`, `truth_how`를 3.0의 규칙대로 정한다(새 연결 재시도 5 s, 응답 대기 5 s).
   - CSV 끝에 새 열 여섯 개(`cqe_ns,t_post_mono_ns,resync_ms,stale_lines,truth_alive,truth_how`)를 더한다. 기존 열은 그대로.
4. `harness/run.sh`, `harness/config.sh`
   - `LIVE_STOP_MS`(8000), `LIVE_TRANSIENT_MS`(1250)를 config 기본값으로 두고 서버 시작 명령에 넘긴다.
   - 장애마다 클라이언트가 끝나면 서버 로그를 `$RESULTS_DIR/<fault>_<stamp>.srv.log`로 가져온다.
   - `kill_server`의 첫 줄에 `pkill -CONT -x probe_server`를 더한다.

### 9.2 GIN 복구 변경(2부)

1. `gin_rec.cu`
   - `main` 맨 앞, kv 파일과 감시 스레드(`:632`)와 `cudaSetDevice`(`:695`) 전에 정지 도우미를 `fork`한다.
   - `GIN_REC_TEST_STALL_MS`(기본 0 = 끔), `GIN_REC_TEST_STALL_ON` = `req` 또는 `iter:<k>`. rank 1에서만 쓴다.
     - `req`: `receiverHandleReq`(`:517`) 첫 줄, Prepare 전에, 첫 요청에서 한 번만 정지한다.
     - `iter:<k>`: rank 1이 반복 k의 장벽 응답을 보내고 대기 커널을 띄운 직후(`:957-961` 뒤) 한 번 정지한다. 그래서 rank
       0의 반복 k 쓰기는 rank 1이 멈춘 동안 도착한다.
     - 끝나면 kv에 `stall on=<req|iter> it=<n> ms=<n> begin_mono_ms=<x> end_mono_ms=<x> measured_ms=<x>`를 쓴다(kv는 기록마다
       flush한다, `:76-83`).
   - 빌드는 `scripts/build_driver.sh`를 기존 빌드 트리(`NCCL_BUILD=<scratchpad>/gi/gin_recovery/build_gpudb`)와 새 출력
     이름으로 부른다. `[측정]` 이 빌드 트리의 `include`가 있다(2026-10-07). 배포는 `scripts/deploy.sh`를
     `B=gi-bundle/gin_recovery_gpudb_stall`과 기존 libnccl로 부르고, 두 노드 md5가 같은지와 libnccl md5 `1ed8e0a1`을
     확인한다. 기존 번들은 건드리지 않는다.
2. `scripts/run_trial.sh`
   - rank 0이 끝난 직후(`R0RC=$?` 다음 줄), sunny의 `pgrep -x gin_rec`로 `r1_alive_at_r0_exit`를 정해 meta에 쓴다.
   - 정리 단계의 `kill -9` 전에 같은 PID에 `kill -CONT`를 보내고, 두 노드에서 `pkill -x lp_stall`을 부른다.
   - 정지 설정은 기존 `EXTRA_ENV`로 두 rank에 넘긴다.

### 9.3 카운터 기록 변경(evrec)

- `gpu-initiated/propagation/evrec/evrec.c`에 `-s <ms>`(표본 간격)와 `-c <이름,...>`(최대 16개)를 더한다. 기다림 루프의
  `ppoll` 제한 시간을 다음 표본까지로 줄이고, 표본마다 지정한 `hw_counters` 파일만 읽어 `smp mono_ns=<n> <이름>=<값> ...`
  한 줄을 쓴다. 기본값은 표본 없음이라 기존 출력과 같다. 읽기만 한다.
- 표본은 QP ERR 재현, QP RESET, 일시 장애 셀(A1, A3, A6)에서만 50 ms 간격으로 켠다. 이름: `rp_cnp_handled`, `roce_slow_restart_cnps`, `roce_adp_retrans`,
  `local_ack_timeout_err`.
- `campaign/evrec_pair.sh:8`을 `E=${EVREC_BIN:-$HOME/gi-bundle/evrec/evrec}`로 바꾸고 `${EVREC_ARGS:-}`를 두 노드
  명령에 넘긴다.

### 9.4 실행과 채점

- 새 파일(구현 단계): `run_cells.sh`, `score.py`, `qa/`(1.2의 재계산 스크립트와 독립 재계산), `results/`.
- `run_cells.sh <A|B> <outroot>`: 셀과 반복을 돌고, 시행마다 `evrec_pair.sh`로 감싸고, `trials.log`에
  `<tag> rc=<rc> <시작> <끝>`을 쓴다. 시행마다 `timeout`(1부 90 s, 2부 `WATCHDOG_S`+60 s)을 걸고, 시행 뒤 8절의 정리와
  검사(정지 프로세스, 남은 프로세스, `dmesg`, 포트 상태)를 한다. `N_OVERRIDE=1`이면 smoke다.
  - 1부 시행: `env RESULTS_DIR=<out>/A/runs/<tag> ITERS=1 COUNTER=rp_cnp_handled bash harness/run.sh <fault>`.
  - 2부 시행: `env BUNDLE=$HOME/gi-bundle/gin_recovery_gpudb_stall REC=1 CLASSIFY=1 INJECT=600 WATCHDOG_S=60
    EXTRA_ENV="GIN_REC_TEST_STALL_MS=<ms> GIN_REC_TEST_STALL_ON=<req|iter:60>" bash
    harness/gpu-initiated/gin_recovery/scripts/run_trial.sh <F3|none> timeout <tag> <out>/B/logs 120 14`.
- 실행(모두 락 안):
  - 배포: `harness/gpu-initiated/common/cluster_run.sh -w 10800 -t live-peer-deploy -- <배포 명령>`
  - smoke: `cluster_run.sh -w 10800 -t live-peer-smoke -- env N_OVERRIDE=1 bash harness/live_peer/run_cells.sh A harness/live_peer/results/<날짜>_smoke`, 2부도 같다.
  - 본 실행: `cluster_run.sh -w 10800 -t live-peer-A -- bash harness/live_peer/run_cells.sh A harness/live_peer/results/<날짜>`, 2부는 `-t live-peer-B`와 `B`.
- 채점: `score.py <결과 폴더>`가 `predictions.csv`의 판정식을 3.0의 규칙으로 계산해 `SCORE.md`, `score.json`을 쓰고, 오판
  표(실제 생존 x 판정)와 놓친 정지 수를 탐지기마다 낸다. 이어서 다른 에이전트가 채점기를 보지 않고 원자료에서 다시 센다.
- 출력: `results/<날짜>/`에는 해설과 인용한 표만 둔다. CSV, 서버 로그, evrec, kv, 로그는 Release `data-<날짜>`에 올린다.
- 예상 클러스터 시간: 1부 약 13분(`[측정]` propagation CPU 75회가 6분, 재시도 초과와 정지 시간을 더함), 2부 약 15분
  (`[측정]` GIN 복구 주 행렬 64회가 28분, `gin_recovery/results/RECOUNT.md`), smoke 약 5분. 락을 잡는 시간은 모두
  35–40분이고, 락을 기다리는 시간은 따로다.

## 10. 완료 조건과 QA 기준

- [ ] 16셀이 계획한 반복 수만큼 실행됐다. 장애 미적용, 실행기 실패, 추가 시행, 관측 불가를 따로 센 표가 있다.
- [ ] 예측 34줄마다 판정(맞음, 틀림, 자료 없음)과 놓친 시행 목록이 있다.
- [ ] 오판 표와 놓친 정지 수를 다른 에이전트가 원자료에서 다시 계산했다.
- [ ] 혼잡 알림 카운터의 관계식을 시행별 원자료에서 다시 계산했다.
- [ ] 1.3의 두 충돌과 실행 중 새로 찾은 충돌을 16절에 적었다.
- [ ] smoke와 제외 시행이 결과에 섞이지 않았다. 여러 시행의 범위와 대표 시행의 범위를 구분했다.
- [ ] 3.1의 줄 번호를 실행 뒤 다시 확인했다.
- [ ] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [ ] `MODEL.md` 규칙 3의 한계를 결과에 맞게 고칠 초안을 만들었다(고치는 것은 사용자 확인 뒤).

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 계측과 실행기 구현(CPU 하네스, GIN 드라이버, evrec, `run_cells.sh`, `score.py`), 빌드. 독립 리뷰는 하지 않았고 smoke와 채점기 시험으로 확인했다
- [x] 배포
- [x] smoke 실행(채점 제외)
- [x] 본 실행 (`RUNNING`)
- [ ] 채점과 재계산 (`QA`): 채점은 끝남(20:40). 독립 재계산은 다른 에이전트가 한다
- [ ] 결과 정리, 원자료 릴리스, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-07, 18:45까지 | 설계: CPU 하네스, GIN 복구, NCCL 복구 2단계, NVSHMEM 장애 대응판, 투명 복구, ack_timeout, teardown_order의 생존 판정 소스 조사(읽기만, 빌드와 실행 없음) | 3.1 |
| 2026-10-07 18:21–18:30 | Release `data-20261006`의 propagation 캠페인 묶음과 재실행 묶음을 받아 체크섬 확인, evrec 650개에서 혼잡 알림 카운터를 다시 셈 | 1.2, 1.3 |
| 2026-10-07 18:55–19:05 | 다른 에이전트가 읽은 줄 번호(복구 2단계, 장애 대응판, 투명 복구, ack_timeout, teardown_order)를 master `3dbf995e`에서 다시 확인. 인용 줄 범위 세 곳을 고침(복구 2단계의 FIN 판정, ack_timeout의 재전송 설명, teardown_order의 cudaFree 결과). 예측 내용은 바뀌지 않음 | 3.1, [predictions.csv](predictions.csv) |
| 2026-10-07 19:02:12 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/live-peer-v1` |
| 2026-10-07 19:05–19:15 | 구현과 빌드: CPU 하네스(새 장애 여덟 개, 정지 도우미, RESYNC, 실제 생존 기록), evrec 표본, GIN 정지 스위치, 실행기, 배포 스크립트, 채점기, 카운터 재계산. 빌드됨. 정지 도우미는 rain에서 RDMA 없이 따로 시험(500 ms 정지 동안 상태 `T`, `timeout` 아래에서도 같음) | 커밋 `f288469e`, `5e1bd3ce`, `25a771b6`, `f7d70114`. 구현 결정은 [DEVIATIONS.md](DEVIATIONS.md) 1–6 |
| 2026-10-07 19:29:02–19:29:10 | 배포 블록(`lp-deploy`, 락 대기 19:16–19:28). 새 디렉터리에만 배포, 두 노드 md5 일치. 블록 뒤 정지 상태 프로세스 없음, rain dmesg mlx5 명령 오류 줄 2(전부 이전 것) | 5절의 md5 |
| 2026-10-07 19:40:51–19:42:36 | smoke 1부(`lp-smokeA`), 셀마다 1회, 12회. 러너 rc 모두 0, 따로 센 시행 없음, 중단 없음. 블록 뒤 정지 상태와 남은 프로세스 없음, rain dmesg 2에서 그대로, sunny dmesg는 sudo 없이 읽히지 않음 | `results/20261007_smoke/A/`(Release 예정, 채점 제외) |
| 2026-10-07 19:52:45–19:53:38 | smoke 2부(`lp-smokeB`), 셀마다 1회, 4회. 러너 rc 모두 0, 따로 센 시행 없음. 블록 뒤 검사 같음. 채점기를 smoke 사본으로 시험해 판정식이 모두 계산되는 것을 확인(결과는 채점에 쓰지 않음) | `results/20261007_smoke/B/` |
| 2026-10-07 19:54:29 | 본 실행 시작. 1부(`lp-A`)와 2부(`lp-B`)를 각각 `cluster_run.sh -w 10800` 블록으로 대기열에 넣음. 상태 `RUNNING` | `results/20261007/` |
| 2026-10-07 20:04:43–20:18:45 | 본 실행 1부(`lp-A`, 락 대기 19:54–20:04). 95회, 러너 rc 모두 0, 추가 시행 0, 따로 센 시행 0, 중단 없음. 정지 시행 20회 모두 sunny `probe_server` 상태 `T`를 관측. 블록 뒤 정지 상태와 남은 프로세스 없음, rain dmesg mlx5 명령 오류 줄 2에서 그대로 | `results/20261007/A/`(`trials.log`, `runner.log`, Release 예정) |
| 2026-10-07 20:29:23–20:36:11 | 본 실행 2부(`lp-B`, 락 대기 20:18–20:28). 30회, 러너 rc 모두 0, 추가 시행 0, 따로 센 시행 0, 중단 없음. 블록 뒤 검사 같음 | `results/20261007/B/`(Release 예정) |
| 2026-10-07 20:40 | 채점(`score.py results/20261007`): 측정 예측 34줄 중 33줄 맞음, 1줄 틀림(6 s 정지 GIN 셀의 거절 시각). 상태 `QA` | [SCORE.md](results/20261007/SCORE.md), [trials_scored.csv](results/20261007/trials_scored.csv) |

## 13. 사전 등록 이후 변경

변경과 구현 결정은 [DEVIATIONS.md](DEVIATIONS.md)에 있다. 예측, 판정식, 셀, 반복 수, 제외와 중단 기준을 바꾼 항목은 없다.

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 본 실행 1부 원자료: 시행마다 CSV와 서버 로그(`runs/<tag>/`), evrec(`evrec/`), 실행 로그와 정지 상태 기록(`logs/`), `trials.log`, `runner.log` | `results/20261007/A/`(커밋하지 않음, Release 예정) | 95회 |
| 본 실행 2부 원자료: 두 rank의 kv, meta, 로그(`logs/`), evrec(`evrec/`), `trials.log`, `runner.log` | `results/20261007/B/`(Release 예정) | 30회 |
| smoke(채점 제외) | `results/20261007_smoke/A/`, `B/`(Release 예정) | 16회 |
| 채점 결과 | [results/20261007/SCORE.md](results/20261007/SCORE.md) | 34줄 |
| 시행별 값 | [results/20261007/trials_scored.csv](results/20261007/trials_scored.csv) | 125회 |
| 이전 캠페인 카운터 재계산(1.2, 1.3) | [qa/recount_cnp.py](qa/recount_cnp.py), 입력 Release `data-20261006` | 650 기록 |

## 15. 결과 요약

본 실행 125회(1부 95, 2부 30, 2026-10-07 20:04–20:36)의 결과다. 따로 센 시행과 추가 시행은 없다. smoke는 넣지 않았다.
모두 `[측정]`이고 해석에는 `[추론]`을 붙였다. 판정은 [SCORE.md](results/20261007/SCORE.md), 시행별 값은
[trials_scored.csv](results/20261007/trials_scored.csv)에 있다. 시간 범위는 따로 적지 않으면 그 셀 시행들의 최솟값–최댓값이다.
독립 재계산 전 값이다.

**예측 판정: 측정 34줄 중 33줄 맞음, 1줄 틀림.** 근거: SCORE.md
- 틀린 줄은 6 s 정지 GIN 셀의 거절 시각(B2a)이다.
  - 예측: 장애 조회 뒤 3000–3500 ms에 거절. 측정: 2999.2–3002.2 ms(n=10). 두 시행(`b2_t1` 2999.3 ms, `b2_t5` 2999.2 ms)이
    하한보다 0.7–0.8 ms 일렀다.
  - 거절 자체는 예측대로다. 이유 "핸드셰이크 시간 초과" 10/10, rank 0 종료 코드 9 10/10.
  - `[소스]` 드라이버는 남은 대기 시간을 정수 ms로 잘라 `poll`에 넘긴다(`gpu-initiated/gin_recovery/gin_rec.cu`의 핸드셰이크
    대기와 `recv()`). `[추론]` 그래서 실제 대기는 3000 ms보다 1 ms 가까이 짧을 수 있고, 예측은 이것을 빠뜨렸다.

**1. 데이터 경로는 프로세스 생존을 모른다(가설 1).**
- 응답 쪽 QP가 요청을 받을 수 없으면 프로세스가 살아 있어도 SIGKILL 때와 같은 12/0x81이 왔다. RESET 10/10, INIT 10/10,
  새 QP 5/5, QP 오류 + 8 s 정지 10/10, QP 오류 + 제어 연결 닫음 10/10, 재현한 QP 오류 5/5, SIGKILL 5/5. 게시부터 오류 완료까지는
  일곱 셀 55회를 합쳐 3.495–3.756 s였다.
- 응답 QP가 RTR이면(RTS 아님) 쓰기가 정상 완료했다. 10/10, 3.5–4.5 µs.
- 정상 QP + 8 s 정지: 쓰기가 3.7–8.2 µs에 정상 완료했다(10/10). 정지 시행 20회 모두에서 sunny `probe_server`가 상태 `T`로
  관측됐다(`results/20261007/A/logs/*.pstate`). `[추론]` ACK는 프로세스가 아니라 NIC가 만든다.
- 1250 ms 동안 준비 안 됨 뒤 같은 PSN으로 재무장: 오류 없이 1352.5–1513.7 ms에 완료했다(10/10).
- 예측하지 않은 관측: RTR로 재무장한 셀에서 응답 쪽 비동기 이벤트 `IBV_EVENT_COMM_EST`가 10/10 기록됐다. 다른 셀의 응답 쪽
  비동기 이벤트는 없었다(관측한 셀 모두).

**2. 탐지기는 프로세스가 아니라 제어 연결을 본다(가설 2).**
- CPU 하네스:
  - 살아 있는 프로세스가 제어 연결만 닫으면 "죽음"(`proc_kill`)으로 판정됐다(10/10). 새 연결의 생존 질의에는 같은 프로세스가
    답했다(10/10). 죽음 오판 10/10이다.
  - QP 오류 + 8 s 정지는 "응답 없음"(`no_answer`)이었다(10/10, 죽음 0). 재개 뒤 늦은 답 2줄씩을 버리고 복구와 검증이
    10/10 성공했다. 이 판정은 `auto_recoverable=0`이라 복구 불가 오판 10/10으로 센다(6절 정의).
  - QP만 준비 안 된 셀(RESET, INIT, 새 QP, 재현 QP 오류)은 "살아 있음, QP 오류"였다(30/30).
  - SIGKILL은 죽음 판정 5/5, 생존 질의 연결 거부 5/5였다.
  - 오판 집계: 죽음 오판은 제어 연결 닫음 셀 10/10, 그 밖의 살아 있는 셀 0/80. 복구 불가 오판은 정지 + QP 오류와 제어 연결 닫음
    셀 20/20, 그 밖의 살아 있는 셀 0/70.
  - 라벨 버그(1.3)는 그대로다. 살아 있음 판정 30회 모두 `peer_alive=0`이 기록됐다. 판정에 쓰지 않았다.
- GIN GDAKI 복구 v2:
  - 1 s 정지: 복구 10/10. ACK는 Prepare 뒤 1004.5–1005.0 ms. 정지 없는 재현: 복구 5/5, 4.2–4.3 ms.
  - 6 s 정지: 핸드셰이크 시간 초과로 거절 10/10. rank 1은 거절 뒤 2999.2–3002.2 ms에 재개해 요청을 처리했고(10/10), rank 0이
    끝날 때 rank 1 프로세스가 있었다(10/10). 복구 불가 오판 10/10이다.
  - 장애 없음 + 6 s 정지: 장애 기록과 복구 없이 두 rank가 120회를 모두 정확히 마쳤다(5/5). 놓친 정지다.
- `[추론]` 오판의 경계는 소스의 상수로 맞혔다. CPU 하네스는 1 s 안에 답이 없으면 미확정, GIN 복구는 3 s 안에 ACK가 없으면
  거절이다. 1 s 정지는 마감 안이라 복구됐고 6 s 정지는 밖이라 거절됐다.

**3. 혼잡 알림 처리 카운터는 재전송을 센다(가설 3).**
- 실제 혼잡 신호(`np_cnp_sent`, `np_ecn_marked_roce_packets`, `rp_cnp_ignored`)는 125/125 시행, 두 노드 모두에서 +0이었다.
- CPU 하네스의 재시도 초과 55회(rain): `rp_cnp_handled` = `roce_slow_restart_cnps` 55/55, = 적응 재전송(`roce_adp_retrans`)
  + 정규 타임아웃(`local_ack_timeout_err`) - 1 55/55, 정규 타임아웃 6 55/55. `rp_cnp_handled`는 55회를 합쳐 10–13이었다.
- 1250 ms 준비 안 됨(오류 완료 없음, `req_cqe_error` +0 10/10)에서도 `rp_cnp_handled`가 8–10 올랐다. `roce_slow_restart_cnps`와
  같았고(10/10), 적응 재전송 + 정규 타임아웃과 같았다(10/10, 정규 타임아웃 2 10/10).
- ACK 타임아웃이 없는 셀(장애 없음, RTR, 정상 QP + 정지, 수신 버퍼 없음, GIN 장애 없음 + 정지) 35회: 세 카운터 모두 +0.
  RNR 재시도(수신 버퍼 없음)는 이 카운터를 올리지 않았다.
- 50 ms 표본(QP 오류 재현, RESET, 일시 장애 25회): 표본마다 두 카운터의 차이는 0이었고, 증가는 게시 뒤부터 첫 CQE + 100 ms 안에만
  있었다(25/25).
- GIN 상대 QP 오류 25회: rain `rp_cnp_handled` 9–12, q 카운터(`roce_slow_restart_cnps`, `local_ack_timeout_err`) +0, sunny +0.
- 1부 sunny는 95/95에서 +0이었다.
- `[추론]` 이 카운터는 혼잡이 아니라 재전송을 센다. NIC가 재전송할 때마다 slow restart 알림을 내부에서 하나 만들고 반응 쪽 혼잡
  제어가 그것을 처리했다고 센다(1.2). 재시도 초과에서 "- 1"이 붙는 것은 마지막 정규 타임아웃이 재전송 대신 오류 완료를 만들기
  때문이다. DEVX QP에서도 오르는 것은 혼잡 통계가 장치 단위이기 때문이다.

## 16. QA와 재현성

> 누가(사람 또는 에이전트) 무엇을 다시 셌고 무엇이 맞거나 달랐는지. 재현에 필요한 빌드와 커밋.

## 17. 결론

## 18. 한계

## 19. 다음 작업

## 20. 참고자료

- T. D. Chandra, S. Toueg. Unreliable Failure Detectors for Reliable Distributed Systems. JACM 1996.
- W. Chen, S. Toueg, M. K. Aguilera. On the Quality of Service of Failure Detectors. IEEE TC 2002.
- P. Huang et al. Gray Failure: The Achilles' Heel of Cloud-Scale Systems. HotOS 2017.
- Y. Zhu et al. Congestion Control for Large-Scale RDMA Deployments (DCQCN). SIGCOMM 2015.
- 이 저장소: [../../MODEL.md](../../MODEL.md), [../NOTES.md](../NOTES.md), [../ack_timeout/NOTES.md](../ack_timeout/NOTES.md),
  [../teardown_order/NOTES.md](../teardown_order/NOTES.md), [../gpu-initiated/propagation/EXPERIMENT.md](../gpu-initiated/propagation/EXPERIMENT.md),
  [../gpu-initiated/gin_recovery/RECOVERY_DESIGN.md](../gpu-initiated/gin_recovery/RECOVERY_DESIGN.md).
