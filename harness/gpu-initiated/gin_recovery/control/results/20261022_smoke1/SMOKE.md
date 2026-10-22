# gin-control 첫 하드웨어 smoke (2026-10-22, 채점 안 함)

장애 없는 대조 셀 `gc4_none_ow@gc`(4 KiB, mirror 켬, 덮어쓰기 workload, 체크포인트 20 step마다)를 실제 RNIC에서 돌린 smoke다. 시행마다 n 1이고,
본 실험과 pilot에 들지 않는다. 시도는 여섯 번(a1–a6)이고, 모두 `harness/gpu-initiated/common/cluster_run.sh` 안에서 돌았다.
빌드, 배포, md5, 고친 것의 자세한 내용은 [../../impl/notes_smoke.md](../../impl/notes_smoke.md), 고친 diff는
[../../impl/gc_layer_smokefix.diff](../../impl/gc_layer_smokefix.diff)다.

- 트리: 스크래치 `agent_gc_p2a2/nccl-src`의 커밋 `acfede7` "gin-control 2a-2-C step 1 (gc_layer_int.diff 3219c376)"을 그대로 복사(작업 트리는 쓰지 않음).
  고친 것은 호스트 파일 하나, 장치 코드 0줄.
- rank 수: 맡김 글은 "2-rank"였으나 실행기 `run_gc.sh`는 4 rank만 받는다(`N=4`가 아니면 거절). 노드마다 2 rank, 모두 4 rank로 돌렸다.
- 실행 길: `cells_gc.sh` → `run_gc.sh`(a1–a4), a5–a6은 그 스크래치 사본(아래). `hold_gc.sh`는 쓰지 않았다: smoke hold P0에는 kill 시행이 함께 있고,
  P hold는 이름이 `smoke`나 `pilot`으로 시작하는 결과 폴더만 받는데 이 폴더는 `<날짜>_smoke1`이다. 그래서 hold의 앞뒤 스냅숏과 STOP 검사는 돌지 않았고,
  같은 STOP 규칙(`rows_gc.py --stops`)만 시행마다 손으로 돌렸다.
- 로그는 모두 `sed -E 's/([0-9]{1,3}\.){3}[0-9]{1,3}/<addr>/g'`를 거쳐 이 폴더에 옮겼다. 관리망 주소 문자열은 이 폴더에 0건이다 `[측정: grep]`.

## 시도마다

| 시도 | 라이브러리(md5 앞 8) | 셀 env 밖의 것 | 결과 | 근거 |
|---|---|---|---|---|
| a1 | `4bc785f8`(step 1 그대로) | – | 실패. 네 rank 모두 Resume 거절(`resume_rc=5`, `xchg=refused`), 조건 41. 셋업, UD 짝 맺기, 링 live, launcher 짝 맺기는 됨 | [a1/raw/](a1/raw/) |
| a2 | `a9c6b0d6`(고침 1) | – | 통과. 네 rank `resume_rc=0`, 600 step, `xchg=ok`, `sig_exact=1`, `x_match=1`. 생존 READ 요약 줄이 하나도 없음 | [a2/raw/](a2/raw/) |
| a3 | `97980dfb`(고침 1 + 2) | – | 통과(위와 같음). READ 요약 줄 12개(rank 넷 × 상대 셋) | [a3/raw/](a3/raw/) |
| a4 | `97980dfb` | `SPARE=1 SPARE_RANK=3` | 네 rank는 통과. sunny의 따뜻한 예비 프로세스가 HELLO 전에 네 번 `exit 2`, launcher의 다시 띄우기 한도 줄(STOP_launcher) | [a4/raw/](a4/raw/) |
| a5 | `97980dfb` | 진단 실행기 사본 | 시작 못 함: 내 스크래치 사본의 따옴표 실수(`SPAREEXEC: unbound variable`). launcher와 rank는 뜨지 않았고 남은 프로세스 0 | [a5/run.out](a5/run.out) |
| a6 | `97980dfb` | 진단 실행기 사본, `SPARE=1 SPARE_RANK=3` | 네 rank는 통과. 예비 프로세스는 HELLO와 `spare_ready`까지 가고, 자기 Resume에서 조건 41로 거절, launcher가 SIGKILL, 다시 띄우기 한도(STOP_launcher) | [a6/raw/](a6/raw/), [run_gc_smokediag.diff](run_gc_smokediag.diff) |

- 셀 그대로의 시행(a1–a3)의 끝 상태: a3이 깨끗이 통과했다 `[측정, n 1]`. a2도 통과했으나 READ 요약이 없었다.
- a4와 a6은 셀에 없는 예비 프로세스를 더한 시행이다(장애 주입 없음). 맡김 글의 "warm spare HELLO"를 보려고 더했다.
- 시도 수: 여섯 번을 다 써서 멈췄다. 넷째 결함(예비 프로세스의 조건 41)은 고치지 않았다.

## 무엇이 깨졌고 무엇을 고쳤나

1. **Resume 조건 41이 부를 때의 걸쇠를 읽음(a1, 고침 1).** sunny의 rank 1은 자기 launcher와의 짝 맺기 걸쇠가 서기 전에 Resume을 불렀다고 본다
   `[추론: 걸쇠 줄 mono 2682208507.9가 Resume 끝 줄 mono 2682208527.1보다 앞서지만, 끝 줄 시각에는 다른 rank를 기다린 교환이 들어 있음; 부른 시각은 로그에 없음]`. 그 rank의 41이 교환으로 모든 rank의 거절이 됐다.
   `impl/notes_int2.md`의 "열린 것"에 적힌 그대로다. 고침: 그 context의 launcher 링크가 있으면 걸쇠가 설 때까지 `NCCL_GIN_CTRL_LATER_MS`(기본 1 000)만큼 기다린 뒤 사실을 읽음
   (잠금은 볼 때마다만 잡음). 고친 뒤 rank마다 Resume 시간 0.6–29.2 ms(a2, a3의 rank 여덟을 합친 범위) `[측정]`.
2. **생존 READ 요약이 나오지 않음(a2, 고침 2).** 요약은 `gdakiCtrlPageFree`(context destroy의 `gdakiRecFree`)에서만 나오는데, 이 driver의 끝은 그 destroy에 닿지 않는다
   `[소스: 호스트 파일의 teardown 주석 "gdakiRecFree (ncclDevCommDestroy, if it ever comes)"]`. 고침: communicator teardown이 요약을 청하고, 그 counter와 지연 vector의 주인인
   감시 스레드(`gdakiQ4Watch`)가 다음 걸음에 한 번 쓴 뒤 READ를 멈춤(박동은 계속). 500 ms 안에 감시 스레드가 걷지 않으면 teardown이 쓴다.
3. **따뜻한 예비 프로세스가 기록 파일보다 먼저 뜸(a4, 고치지 않음: 실행기 쪽 요청).** launcher가 시작 때 예비 프로세스를 띄우는데 그때 rank의 초기화 기록(transcript)이 아직 없다.
   예비 프로세스 줄: `GIN/RS: replay: cannot open the transcript (errno 2)`, kv `init_rc=2`, `exit=2`. launcher 줄:
   `spawned spare exited unused (spawn 4, incarnation 1, pid …, before HELLO, exit 2): respawn cap 3 within 60000 ms reached; no more spares (STOP_launcher)`.
   `impl/launcher/README_launcher.md` "실행기 쪽에 필요한 바꿈" 7의 `[미확인]`이 실제로 일어났다. a6은 스크래치 사본 실행기로 이것을 비켜 보았다: `spare_exec.sh`가 go 파일을 기다리고,
   실행기가 rank의 `GINRS resume` 줄 뒤 go 파일을 만들며, launcher에 `--spare-hello-ms 30000`을 줌(사본의 diff는 [run_gc_smokediag.diff](run_gc_smokediag.diff), 18줄).
4. **예비 프로세스의 Resume이 조건 41로 거절됨(a6, 고치지 않음).** 예비 프로세스는 REJOIN 전에는 helper가 돌지 않아 자기 launcher와 기록 QP 짝을 맺지 않으므로 걸쇠가 서지 않는다.
   kv: `resume_rc=5 resume_ms=1001.6 … rank 3: the restore was asked but this rank is not paired with its node's launcher`(고침 1의 기다림 1 000 ms를 다 씀).
   그 뒤 launcher: `spare of rank 3 incarnation 1 reports a replay failure` → `still there after 1000 ms (state 5): SIGKILL through its pidfd` → 다시 띄우기 네 번 → STOP_launcher.
   고침 1 전에도 41이었을 것이다(걸쇠를 기다리지 않을 뿐) `[추론]`. 제안은 notes_smoke.md.

## 본 줄(정확한 글, a3; mono_ms는 줄임)

- 준비 합의(rank 0): `GIN/RC: rank 0: control setup path=rdma active_mtu=5 (4096 B) fork=2 ud_qpn=… qkey=0x…`,
  `GIN/RC: rank 0: setup agreement: control path rdma on every rank, min_active_mtu=5, thresholds equal`. 네 rank 모두 같은 두 줄이고, 시행 앞뒤 두 포트의 `active_mtu`는
  4096/4096(meta) `[측정]`. 줄의 `active_mtu=5`는 enum 값(IBV_MTU_4096)이다.
- Resume 조건: a1 `GIN/RS: ncclGinRestoreResume: the restore cannot be enabled on this communicator: rank 1: the restore was asked but this rank is not paired with its node's launcher`;
  a3 `GIN/RS: rank 0: ncclGinRestoreResume: the restore can be enabled (every rank asks for the restore and can enable it); first incarnation, step 0; the communicator is armed …`.
- UD 짝 맺기: `GIN/RC: rank 0: the ring's consumed words are the status page's rxConsumed[4]; first pairing over UD started with 3 of 3 gated rank(s) …`,
  `GIN/RC: rank 0: liveness READ QP to rank 2 paired (gen 1) via UD`(답하는 쪽은 `… via UD (the answering side)`). 생존 READ QP 짝 여섯(rank 쌍마다 한 번, 양쪽 줄 12개) 모두 gen 1 `[측정]`.
- 링 live: `GIN/RC: rank 0: the records go on the ring from now (live): 3 peer(s), record and liveness READ QPs paired; the helper sockets are the witness's`(네 rank 모두).
  끝에 `ring summary peer=1 gen=1 sent=152 received=152 lost=0 dup=0`(rank 0; 상대마다 150–152, 잃음과 겹침 0) `[측정]`.
- 생존 READ: `GIN/RC: rank 0: probe summary peer=1 reads=50 ok=50 remacc=0 noresp=0 timeout=0 gen=1 lat_med_us=73.3 lat_max_us=76.1 beat_gap_max_ms=1.073 torn=0 …`.
  12줄 모두 reads 50, ok 50. 중앙값 72.6–78.1 µs, 최대 75.2–30 159.7 µs(12줄의 범위; 1 ms를 넘은 것은 6줄: sunny의 rank 1, 3이 넷, rain의 rank 2가 둘) `[측정, n 1 시행]`. a4(78.6 s 시행)는 12줄 모두 769/769.
- 제어 요약(rank 3): `control summary tcp_record_bytes=5616 tcp_data_bytes=0 tcp_conns=0 witness_conns=3 records_lost=0 records_dup=0 repairs=0 sendq_deferred=0 sendq_max=0 rnr=0 async=0 active_mtu=5 … tcp_late_records=0 live=1`.
  `tcp_record_bytes=5616`은 rank마다 같고 1 872 B × 3(상대마다 기록 하나)이다: 링이 live가 되기 전 helper 소켓으로 간 기록이다 `[측정; 무엇인지는 추론]`.
- launcher: `GIN/LA: node 0: INFO of rank 2 answered`, `rank 0 incarnation 0 registered (pid …)`, `paired (record) with rank 1 (incarnation 0, generation 1)`(launcher마다 rank 넷),
  rank 쪽 `paired with the launcher of node 0, which holds incarnation 0: the activation gate requires FENCED`, 끝에 `rank 0 incarnation 0 is leaving`과
  `rank 0 incarnation 0 left (LEAVING, then the group ended)`. `rows_gc.py --stops`: a1–a3 `la_stop_n=0 la_qp_err_n=0`, a4와 a6 `la_stop_n=1`(위 3, 4) `[측정]`.
- 따뜻한 예비 프로세스(a6): `GIN/LA: node 1: spawned spare said HELLO (spawn 1, incarnation 1, pid …, hello pid …, rank 3 incarnation 1, after 3140.734 ms)`(go 파일을 기다린 시간 포함;
  다시 띄운 셋은 397.9–448.5 ms), rank 쪽 `GIN/RC: rank 3: spare said HELLO as incarnation 1 at the launcher of node 1 (page slot 1)`, 예비 프로세스의 `GINRS spare_ready rank=3`.
  생존 rank는 예비 프로세스가 있는 동안 `rank 3 armed at its stable checkpoint K`(rank 0, 1, 2 각 11줄), 예비 프로세스가 죽은 뒤 `rank 3 disarmed (its stable checkpoint is not armable …)` `[측정]`.
- `GIN/` 경고와 STOP: 판정, 의심, 확인 창, 다시 짝 맺기, local ERR 줄은 a1–a6 어디에도 0줄. RNR 카운터는 시행 앞뒤 같음(rain 156 717, sunny 0; rain 값은 다른 사용자의 몫도 셈).
  남은 프로세스 0(meta `left=0`) `[측정]`.

## 아직 돌지 않은 것

- 장애 주입 셀 전부(kill, SIGSTOP, RST, fd 자식, 관리망 끊김, 시험 스위치 `QP_ERR`, `DROP_UD`, `CREDIT_STALL`), 그래서 판정 표, 확인 창, 펜스, 활성화 중계, UD REJOIN,
  outbox 전송, 다시 짝 맺기는 실제 NIC에서 아직 한 번도 돌지 않았다.
- 예비 프로세스의 활성화 대기(조건 41 때문에 Resume에서 끝남, 위 4).
- `gct`, `gcp` 빌드, `hold_gc.sh`의 hold 앞뒤 검사, 채점(`score_gc.py`). 이 smoke는 채점하지 않는다.
