# gin-control 첫 하드웨어 smoke: 빌드, 배포, 고침 (작업 기록, 2026-10-22)

결과와 본 줄은 [../results/20261022_smoke1/SMOKE.md](../results/20261022_smoke1/SMOKE.md), 고친 diff는 [gc_layer_smokefix.diff](gc_layer_smokefix.diff)
(커밋 "gin-control 2a-2-C step 1" 대비, 106줄, 호스트 파일 하나 60줄 더함, 장치 코드 0줄, `__device__`/`__global__` 더한 줄 0, 거꾸로 적용 확인). 스크래치 작업 폴더는
`agent_gc_smoke/`(세션 스크래치)다. 표시: `[측정]` 돌려서 봄, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

## 단계

1. 디스크 확인(`/` 457G 중 남은 것 137G).
2. 트리: `agent_gc_p2a2/nccl-src`를 `cp -a`로 복사하고 커밋 `acfede7`로 맞춤(그 작업 트리의 고침은 버림, 브랜치 `smoke`). 빌드 디렉터리 `build`는 ln4의 `agent_mi_fix/build`
   사본에 경로를 다시 씀(`build_gc.sh` setup의 규칙). 스크립트는 `build_gc.sh`의 스크래치 사본 `agent_gc_smoke/build_gc_smoke.sh`(키 `smoke`: setup, head 이름, `tree`가 적용 없이 작업 트리를 빌드).
3. 빌드: `gc`(연구, rdma), driver `gin_mi`(`build_mi_test_smoke.sh`: gin-mirror `build_mi_test.sh` 사본, 머리와 라이브러리는 이 트리의 `build/`), launcher
   (`launcher/build_launcher.sh all`: 27 장면 692 검사 실패 0 `[측정, n 1]`).
4. 배포: 두 노드의 새 폴더 `~/gi-bundle/gin_ts2/<set>/{lib/gc,gctest}`와 링크 `~/rs-bundle/<set>` → 그 폴더(실행기가 `~/rs-bundle/<RS_SET>/`를 읽음; `deploy_gc.sh`는
   `~/rs-bundle` 밖을 쓰지 않아 스크래치 `deploy_smoke.sh`로 함). 두 노드 md5 같음, `ldd`는 libnccl이 묶음의 것, launcher는 libibverbs.so.1 `[측정]`.
5. 실행: `cluster_run.sh -w 3600 -t gc-smoke-<시도> -- timeout -s KILL 500 bash test/cells_gc.sh <로그> gc4_none_ow gc rs 1 1 DRIVER=gin_mi OVERWRITE=1 MIRROR=1 CKPT_STEPS=20`
   (`RS_SET`, `LAUNCHER_ENV=-`; 스크래치 `run_smoke.sh`). a5, a6은 `run_gc.sh`의 스크래치 사본 `run_gc_smokediag.sh`를 직접 부름. 시행마다 `rows_gc.py --stops`.
6. 고침 둘(아래), 빌드, 새 묶음, 다시 실행. 시도 여섯에서 멈춤.

## 빌드와 배포 표 (md5 전체)

| 무엇 | md5 | 비고 |
|---|---|---|
| libnccl `gc_smoke1` | `4bc785f8e3a42db0ec501ee9261c0076` | step 1 그대로; 묶음 `gc_smoke`(a1) |
| libnccl `gc_smoke2` | `a9c6b0d6dc8d920c928382966fec7556` | + 고침 1; 묶음 `gc_smoke_a2`(a2) |
| libnccl `gc_smoke3` | `97980dfb058b2a9b2c3e5e24e3d00d01` | + 고침 2; 묶음 `gc_smoke_a3`(a3, a4, a6). 주석만 고친 뒤 다시 빌드해도 같은 md5 `[측정]` |
| `gin_mi` | `0179377e619073134723b4e40873ff9c` | `gin_mi.cu` 556804c0, 매크로 켬, 머리 digest 65fdf19b; 세 묶음 같음 |
| `gin_launcher` | `3344ee19203a3b82f813f5c46732c61b` | `gin_launcher.c` c31e1601(커밋 10bc65af), `launcher_msg.h` fb11b235 = 트리에 붙인 launcher wire `[측정]` |
| `launcher_unit` | `6d2d8c7429a6159db7502dae1f99e84c` | 위 단위 시험 |
| `gc_layer_smokefix.diff` | `10f7e810bb07fdb482b398f2f4d0afe4` | 106줄 |
| 스크래치 스크립트 | `build_gc_smoke.sh` a626f16d, `build_mi_test_smoke.sh` 9dc11add, `deploy_smoke.sh` 8b2a6f45, `run_smoke.sh` 8ed339d9, `run_gc_smokediag.sh` 303bb7a8 | 저장소 밖 |

- 빌드 경고 0(세 판 모두, 로그 grep) `[측정]`. `gct`, `gcp`는 빌드하지 않았다. 고친 자리는 모두 `#if !NCCL_GIN_CTRL_TCP` 안이라 tcp 빌드의 전처리 결과는 그대로다
  `[소스: 전처리 지시문의 겹침을 셈]`, 다시 돌리지는 않음 `[미확인]`.
- 빌드 함정: `cp -a` 뒤 `git checkout -f <commit> -- src`가 모든 소스를 다시 써 mtime이 새로워졌고, 첫 `gc`가 장치 객체까지 모두 다시 빌드하기 시작했다. 내가 띄운 make를
  process group으로 끄고, ln4와 내용이 같은 1 454 파일의 mtime을 ln4 것으로 되돌리고, `build`를 ln4에서 다시 복사했다. 그 뒤 `gc`는 호스트 파일과 `git_version.cc`만 컴파일했다 `[측정]`.
  장치 객체는 ln4 것 그대로다(다시 빌드하지 않은 사본).

## 고친 것 (호스트 파일만)

1. **Resume 조건 41의 기다림**(`ncclGinGdakiRestoreResume`, 사실 모으기 앞). 그 context에 launcher 링크가 있고 걸쇠(`pg->launcherPaired`)가 아직이면 `NCCL_GIN_CTRL_LATER_MS`
   (기본 1 000 ms)까지 1 ms마다 봄. `gdakiRecRegMu`는 볼 때마다 잡고 자는 동안 놓음. 시간이 지나면 지금처럼 41. 2a-2-C 단계 목록 8("LATER_MS까지 기다린 뒤 답")의 최소판이다.
2. **생존 READ 요약을 communicator teardown에서**(`ncclGinGdakiTsCommTeardown`, `gdakiHoldTeardownLine` 다음). 페이지에 `sumReq`(0 없음, 1 청함, 4 쓰는 중, 2 씀)와 `summarized`.
   teardown이 1을 걸고 500 ms까지 기다림; 감시 스레드의 `gdakiCtrlPageStep`이 박동 뒤 1 → 4로 바꾸고 요약을 쓴 뒤 2, 그 뒤로는 READ 없이 박동만. 감시 스레드가 걷지 않으면
   teardown이 1 → 4를 잡고 씀. `gdakiCtrlPageFree`는 이미 썼으면 쓰지 않음. 까닭: 요약의 주인 counter와 `latUs` vector는 감시 스레드 것이고, 그 스레드(`gdakiQ4Watch`)는 teardown 뒤에도 돈다
   (`gdakiQ4Stop`은 context destroy에만 있음) `[소스]`.

## 2a-2-C 단계 2 이후가 알아야 할 것

- **실제 NIC에서 된 것** `[측정, 시행 n 1씩]`: dlsym한 verbs 기호(UD AH, completion channel, `ibv_is_fork_initialized`: fork=2), UD QP의 RTR/RTS와 AH(GRH, GID index 4/3), Q_Key,
  all-gather의 칸과 준비 합의(경로, `active_mtu`, 문턱), 기록 QP와 생존 READ QP의 UD 짝 맺기(모두 gen 1), 페이지 소비 낱말 묶기, live 전환, 링 위 기록 150–152개씩
  잃음 0, launcher INFO와 REGISTER, launcher 기록 QP 짝 맺기, 걸쇠, LEAVING → LEFT, 생존 READ(100 ms마다, 성공률 100 %), 따뜻한 예비 프로세스의 HELLO와 페이지 예비 자리 낱말에 따른 무장과 해제.
- **고치지 않은 결함 하나(예비 프로세스의 조건 41).** 예비 프로세스는 REJOIN 전 helper가 돌지 않아 걸쇠가 서지 않으므로 자기 Resume에서 41로 거절되고, launcher는 그것을 재생 실패로 받아
  SIGKILL과 다시 띄우기를 되풀이해 한도(STOP_launcher)에 닿는다 `[측정: a6]`. 고침 1의 기다림이 그 Resume을 1 000 ms 늦춘다. 제안(돌리지 않음): `gdakiCtrlResumeFacts`와 고침 1의
  기다림에서 `rsReplaying()`이면 "짝"을 SPARE_HELLO가 받아들여졌는지(launcher 링크의 `registered`)로 읽고 기다리지 않음. 예비 프로세스의 launcher 기록 QP 짝 맺기는 활성화 뒤
  helper가 할 일이다(설계 9.6절 차례 (4)) `[추론]`.
- **예비 프로세스가 기록보다 먼저 뜸**(실행기나 launcher 쪽, 요청). launcher가 시작 때 띄운 예비 프로세스는 rank의 transcript가 없어 `exit 2`로 끝나고 60 s 안 네 번째에
  STOP_launcher다 `[측정: a4]`. 안: (가) `run_gc.sh`의 `spare_exec.sh`가 go 파일을 기다리고 실행기가 그 rank의 `GINRS resume` 줄 뒤 go 파일을 만들며 `--spare-hello-ms`를 넉넉히
  (a6에서 쓴 사본, 18줄 diff `../results/20261022_smoke1/run_gc_smokediag.diff`), (나) launcher가 같은 rank의 REGISTER 뒤에 띄움, (다) 라이브러리의 재생이 transcript를 기다림
  (`misc/rs_spike.cc`, 이 층의 파일 밖). 첫 HELLO는 띄운 뒤 3 140.7 ms(go 파일 기다림 포함), 다시 띄운 것은 397.9–448.5 ms(셋) `[측정: a6]`.
- **live 전 TCP 기록.** rank마다 `tcp_record_bytes=5616`(1 872 B × 상대 셋)이 helper 소켓으로 갔다 `[측정]`. 링이 live가 되기 전의 기록이다 `[추론]`. 예측 `no_tcp_control`
  ("이 계층의 TCP 보내기 바이트 0, 증인 BYE 빼고")과 맞추려면 그 기록이 무엇인지와 live 전에 링으로 보낼지를 정해야 한다.
- **줄의 글.** `control summary`와 `control setup`의 `active_mtu=5`는 enum 값이다(`(4096 B)`는 setup 줄에만). 시험 쪽 표의 `active_mtu=%u`가 바이트를 뜻한다면 맞출 것.
  첫 짝 맺기 줄의 "(the records stay on the helper socket until phase 2a-2-B)"는 2a-2-B 뒤 낡은 글이다.
- **READ 요약의 자리.** 고침 2 전에는 요약이 context destroy에서만 나와 이 driver에서는 한 번도 나오지 않았다. 다른 끝 줄(제어 요약, 링 요약)은 helper 끝에서 나온다.
  끝낼 때의 줄을 더 둘 때는 teardown이 닿는 자리에 둘 것.
- **지연 꼬리.** READ 중앙값 72.6–78.1 µs, 최대는 12줄 가운데 6줄이 1 ms를 넘어 2.9–30.2 ms(sunny의 rank 1, 3이 넷, rain의 rank 2가 둘; a3) `[측정, n 1]`. W(20 ms)와 시한(500 ms)을 정할 때 pilot의 꼬리를 볼 것.
- **실행 쪽.** `run_gc.sh`는 4 rank만 받는다. smoke P hold는 폴더 이름이 `smoke`/`pilot`으로 시작해야 하고 P0에는 kill 시행이 함께 있어, 장애 없는 셀 하나만의 smoke hold가 없다(요청).
  배포 스크립트 `deploy_gc.sh`는 `~/rs-bundle` 밖을 쓰지 않는다(이번에는 `~/gi-bundle/gin_ts2/<set>`에 두고 링크).
- **아직 실제 NIC에서 돌지 않은 것**: 장애 주입 전부, 판정 표, 확인 창, 펜스, 활성화 중계, UD REJOIN, outbox 전송, 다시 짝 맺기, 시험 스위치 여섯, `gct`/`gcp`.

## 요청 (고치지 않은 폴더)

- `test/`: 위 "예비 프로세스가 기록보다 먼저 뜸"의 (가); 장애 없는 셀 하나만 도는 smoke hold; 4 rank 밖의 rank 수가 필요하면 `run_gc.sh`의 `N=4` 검사.
- `launcher/`: (나)를 고르면 `--spare-after-register` 같은 띄우는 때 선택. 예비 프로세스가 41로 끝날 때의 "reports a replay failure" 줄은 까닭(41)을 싣지 않는다.
