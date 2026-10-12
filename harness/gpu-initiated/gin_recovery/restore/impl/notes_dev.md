# dev 브랜치 기록 (12절에 옮길 행)

[PARALLEL.md](PARALLEL.md)의 규칙대로 이 브랜치는 `EXPERIMENT.md`를 고치지 않고, 12절에 들어갈 행을 여기에 쌓는다. 통합 때 메인 세션이 12절로
옮기고 이 파일을 지운다. 표시: `[측정]` 시험 출력이나 빌드 출력에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. "빌드됨"은
컴파일만, "시험함"은 CPU 단위 시험을 돌린 것이다. 클러스터 실행은 없다.

빌드 트리는 세션 스크래치 `agent_rs_dev/`(작업 묶음 4 마지막 상태 `agent_rs/`의 복사, 작업 트리 diff md5 `922b2859`, 경로만 고쳐 씀)이고 빌드는
[build_rs_dev.sh](build_rs_dev.sh)로 한다.

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-12 | 공유 인터페이스 [rs_log_api.h](rs_log_api.h) 공개(코드 전): 측 표와 고리의 배치, 빌드 매크로, 호스트 함수(멈춤 읽기, 확정 덮기, 머리, 메시지 수, 덮인 위치와 확정 단계, 넘침 훑기, 상대 항목 모으기와 내보내기, 누적 실행 수, 억제 예산, 모든 옛 WQE를 실행된 것으로 하는 계획). 그 뒤 host 브랜치가 정한 나눔에 따라 이 브랜치의 helper 소켓 레코드 번호를 21–31로 고침(아직 쓰지 않음), host 브랜치의 요청으로 억제 예산과 get 수를 읽는 함수, QP마다 get 수 칸, 훑기의 get 규칙을 더함 | 커밋 `3335928f`, `3902031b`, `ca4fea6e` |
| 2026-10-12 | 작업 묶음 4 다시 하기의 충돌 확인(코딩 전; 사용자 결정 둘: rank마다 고리 하나, 빌드 때 켜는 장치 복원 길). 결과: 설계가 풀지 못한 충돌 없음. 아래 (1)–(13) | 9.4, 9.5, 9.6, 9.7, 9.10.4, 9.10.6, 9.11.5, 9.11.9절, [PARALLEL.md](PARALLEL.md) |
| 2026-10-12 | 작업 묶음 4 다시 하기 구현. (가) 장치와 호스트가 함께 쓰는 헤더: 측 표 머리 128 B(뒤 64 B가 고리의 머리, 꼬리, 넘친 수), QP 항목 128 B(메시지 수, 억제 예산, QP마다 넘친 수와 넘친 때의 머리, 로그 켬, get 거절, get 수), 항목 64 B(첫 8 B가 정체 낱말: 위치의 아래 32비트, QP 번호 24비트, 종류 2비트, 표시 6비트; 신호는 window 번호로, 메시지 수 칸은 빼고 종류, 표시, 크기에서 셈). (나) 장치 헤더: hold 함수들을 `NCCL_GIN_RESTORE_DEVICE`가 있을 때만 두고, 없을 때는 put, putValue, get의 hk 본문 앞에 측 표 포인터 읽기와 술어 trap(PTX의 `setp.ne.u64`와 `@p trap`; 소스와 PTX에는 분기가 없고 ptxas는 trap 명령 둘레에 짧은 분기 `@!P BRA`를 냄)만 둔다. 매크로 빌드의 로그 쓰기는 고리 하나에서 머리를 CAS로, 들어갈 때만 잡는다(넘치면 자리를 쓰지 않고 고리와 QP의 넘친 수를 더함). API 특수화의 내부 인자(신호 키 주소, 신호 window 번호)도 매크로가 있을 때만. (다) 호스트 파일: 측 표 배치(고리 하나, QP 번호 칸에 들어가는 QP 수만), 측 표 설정의 고리 부분, 재기만 하는 모드의 helper 걸음과 문맥 끝의 읽어 내기를 고리 하나로. 처음 쓴 분기와 `__trap()` 꼴은 기계어 비교에서 몇 커널의 레지스터 수를 최대 16 바꿔(아래 비교 행) 술어 trap으로 바꿈 | [rs_layer_dev.diff](rs_layer_dev.diff) |
| 2026-10-12 | 작업 묶음 4 다시 하기 빌드됨(rain, nice 19, ionice idle; sm_75와 sm_86; 실행 안 함). 연구 `agent_rs_dev/out/rs_d4b` libnccl `109454d6086a91b227ee2ee53dce123e`, 운영 `rsp_d4b` `040cfec39f330c82929694264ddfde22`, 각각 389개 컴파일(장치 헤더 요약이 바뀌어 장치 객체 모두 다시), 이 계층의 파일에서 경고 0(경고는 NCCL 자신의 `scheduler/symmetric_sched.cc:327` 하나, 앞 묶음과 같음) `[측정]`. 앞 빌드 `rs_d4a`/`rsp_d4a`(`044b2dd7`/`c59f9c75`, 분기와 `__trap()` 꼴)는 쓰지 않음(폴더에 그대로) | 세션 스크래치 `agent_rs_dev/out/`, `build_rs_d4b.log` |
| 2026-10-12 | 작업 묶음 4 다시 하기 시험함(CPU 단위 시험, rain, g++ 8.4 ASan과 UBSan): `rs_unit_dev: 3713730 checks, 0 failed`(스레드 시험의 반복 수가 실행마다 달라 검사 수가 조금씩 다름) `[측정]`. [rs_unit_dev.cc](rs_unit_dev.cc)는 rs_unit.cc의 사본이고 작업 묶음 4 부분을 고침: 측 표 배치(4 rank에서 문맥 1이든 4든 266 240 B, QP 번호 칸의 한계), 항목과 측 표 칸의 자리, 정체 낱말의 꾸림과 풀림 20 000회, 항목의 메시지 수가 억제 계획의 낸 메시지 수와 같음, 고리 모형(장치의 자리 잡기와 같은 규칙: 머리 읽고 꼬리 읽고 들어갈 때만 CAS; 한 스레드 500회, 보내는 스레드 넷과 꼬리를 옮기는 호스트 스레드 하나 40회: 모든 자리가 정확히 한 번 쓰임, 넘침은 자리를 쓰지 않음, 지키는 항목을 덮지 않음), 읽어 내기의 합. checksum과 억제 계획 시험은 그대로 | `agent_rs_dev/out/unit/` |
| 2026-10-12 | 작업 묶음 4 다시 하기의 기계어 비교(GPU에서 돌리지 않음; [ff_cmp_dev.sh](ff_cmp_dev.sh), [opc_cmp.py](opc_cmp.py), [ptx_mk_dev.sh](ptx_mk_dev.sh), [ptx_cmp_dev.py](ptx_cmp_dev.py); 출력은 스크래치 `agent_rs_dev/sass_d4b/`, `ptx/`). 견준 것: 작업 묶음 4의 기준(`agent_rs/sass4/`의 hk 헤더와 작업 묶음 3의 헤더, 읽기만). 결과 `[측정]`: (1) 매크로 없이 빌드한 프로그램(연산 커널 11개, gin_ts2, gin_mr, ring 예제; 커널과 아키텍처 짝 54개): 48개는 레지스터 수가 hk와 같고 6개가 −2에서 +2(ff `k_get_cta` sm_86 46 → 48, `k_get` sm_86 46 → 45, gin_ts2 `txBurstKernel` 210 → 208과 128 → 126, ring `ctaCooperativePutKernel` 138 → 136과 126 → 124), stack과 local은 모두 같음. 부르는 자리(자원 나눔 방식 셋)마다 측 표 포인터의 64비트 읽기 하나, 비교 둘, trap을 건너는 분기 하나와 trap 하나가 더해진다(`sass_seg.py` 비교, 작업 묶음 3의 헤더 대비). 그 밖의 메모리, 원자, fence 명령은 수가 같다. 다만 ring의 cta 커널 둘에 `WARPSYNC`가 아키텍처마다 둘 늘고, gin_mr의 `mrKernel`과 gin_ts2의 `dualTxKernel`에서 원자 더하기 하나가 술어 꼴에서 술어 없는 꼴로 바뀐다(수는 같음; 검토 지적 4). 처음의 분기 꼴은 ring 커널 넷이 +2, +16, +8, +2였다. (2) 매크로로 빌드한 같은 프로그램: 연산 커널 sm_75 52–94, sm_86 47–96, 프로그램 sm_86 156–205, sm_75 160–240(작업 묶음 4의 `rs_p4d`와 비슷한 크기; 복원을 쓰는 프로그램만 치름). (3) 라이브러리(매크로 없음) `rs_d4b`의 `cuobjdump -res-usage`: 함수 1 492개 모두 hk와 레지스터, stack, local이 같음(1 472개는 이름도 같고 20개는 `onerank.cu`의 컴파일 해시 이름이라 해시를 가리면 같음). 작업 묶음 4(`rs_p4d`) 대비로는 symmetric GIN 커널 36개의 stack이 hk 값으로 돌아옴. (4) NCCL의 symmetric GIN 소스 31개를 이 헤더로 compute_75와 compute_86 PTX로 만들어 hk의 PTX(작업 묶음 3의 기준)와 견줌: 62쌍 모두 다른 줄은 문맥 간격(작업 묶음 3)과 넣은 확인(64비트 읽기와 술어 trap 꾸러미; GIN 파일마다 9개나 12개)뿐, 그 밖 0. 62쌍 가운데 34쌍은 이 아키텍처에서 빈 파일에 가깝고(fp8 변형과 분기 파일), 내용이 있는 것은 28쌍이다(검토 지적 4). SASS 수준에서는 이 커널들(128 레지스터 상한)이 다시 컴파일되며 명령 차례와 수가 바뀐다(예: AllGather RailRing sm_75 34 128 → 35 088 명령; 작업 묶음 4는 43 904) | `agent_rs_dev/sass_d4b/`, `agent_rs_dev/ptx/cmp.txt` |
| 2026-10-12 | 작업 묶음 4 다시 하기의 독립 코드 검토(읽기 전용 에이전트, 같은 모델, 고정한 사본 `agent_rs_dev/review_d4/`, diff md5 `4149b456`; 검토자가 diff를 hk에 다시 적용해 사본과 같음, 단위 시험을 사본에서 한 번 빌드해 두 번 돌려 0 failed, 기계어 비교의 수를 원자료에서 다시 셈). 판정: "no blocking issue". 기준마다: 매크로 없는 소스는 hk에 포인터 읽기와 술어 trap뿐이고 trap은 어떤 WQE와 doorbell보다 앞(인라인 PTX의 술어 범위, 64비트 피연산자, memory clobber 맞음); 매크로 빌드의 고리(들어갈 때만 CAS, 넘침은 자리를 쓰지 않음, 정체 낱말 한 번의 8바이트 쓰기, 32비트 위치에 ABA 없음: 칸에는 p나 p − n만 있음); 호스트의 고리 하나 배치, 설정, 읽어 내기, 재기만 하는 걸음은 맞고 fail-fast는 새로 하는 일이 없음; 메인 세션의 확인(문맥이 둘 이상이면 Resume 거절: `nUserCtx != 1`, `nConn != 1`)은 그대로이고 이 묶음이 약하게 하지 않음. 고칠 것과 메모: (1) 고리가 0으로 시작해 0으로 채운 칸이 위치 0의 항목으로 읽힘 → `ncclGinRsIdIs`가 종류 0을 받지 않게 고치고 시험 모형도 0으로 채움, `!IdIs(0, 0)` 시험; (2) 매크로 없이 빌드한 프로그램은 Resume을 부르지 않아도 복원을 요청한 모든 프로세스에서 trap(측 표 포인터는 문맥을 만들 때 섬) → `nccl.h`의 "no hold reaction yet: the communicator stays fail-fast" 문장과 9.10.4절의 "Resume을 부르지 않는 communicator는 fail-fast"와 어긋남, 아래 통합 항목으로 넘김(nccl.h.in은 host 브랜치와 같이 쓰는 파일), 7절의 비용 셀(`lat_4k`, `lat_256k`, `lat_hold_unarmed`, `lat_ff_branch`)과 회귀의 hold 행은 드라이버의 빌드 꼴(매크로 있음, 없음)을 셀 이름에 적어야 함(test 브랜치에 넘김); (3) 사용자 결정 (나)의 "hk와 같은 레지스터 수"에서 남은 차이(프로그램 54쌍 중 6쌍 −2에서 +2, 라이브러리 symmetric GIN 커널은 레지스터, stack, local이 같고 PTX는 hk에 확인만 더한 것이나 SASS 명령 수는 바뀜: 예 AllGather RailRing sm_75 34 128 → 35 088, 함수 밖으로 낸 몸체 셋이 늘었음 `[추론, 검토자]`)를 사용자 확인 대기로 적음; (4) 글 다듬기(분기 없음은 PTX까지, `WARPSYNC`와 원자 술어 꼴, 내용 있는 PTX 28쌍) → 반영; (5) rs_log_api.h의 "찢어지지 않음"은 추론이라 적고, API 덩어리를 호스트 파일에 넣는 것은 작업 묶음 6이라 적음 → 반영; (6) 항목의 둘째, 셋째 낱말 꾸림을 함께 쓰는 헤더의 함수(`ncclGinRsWord1`, `ncclGinRsWord2`)로 떼어 시험 → 반영; (7) 매크로를 섞은 번역 단위가 `-rdc`로 묶이면 조용히 합쳐짐(어느 쪽이든 안전: 하나는 trap, 하나는 로그) → 주석과 기록만; (8) 이 브랜치가 바꾼 호스트 코드 가운데 dev 구역 밖(`gdakiRecHost`의 칸, `gdakiRsStart`, 공용 순수 구역의 `gdakiRsSideLayoutOf`와 `gdakiRsSumsOf`) → 아래 소유 목록; (9) Resume 뒤에 두 번째 사용자 투명 복구 문맥이 생기면 "rank마다 고리 하나"가 깨짐(`nUserCtx`는 Resume 때만 셈) → 작업 묶음 6, 7에서 DISARM 조건으로; (10) 출처: 비교한 헤더와 사본의 차이는 주석뿐, 행 12에 커밋 `ca4fea6e` 빠짐, (7)의 줄 7223은 7219 → 반영 | 세션 스크래치 `agent_rs_dev/review_d4/`, `review_d4_report.md` |
| 2026-10-12 | 검토 반영 뒤 마지막 빌드(rain, nice 19, ionice idle; sm_75와 sm_86; 실행 안 함): 연구 `out/rs_d4c` libnccl `5b75ef3761cac95daa64462e24bdcf91`, 운영 `out/rsp_d4c` `f80fc7c217ccce118402d212b2140f8f`, 각각 389개 컴파일, 이 계층의 파일에서 경고 0(NCCL 자신의 `symmetric_sched.cc:327` 하나). 시험함: `rs_unit_dev: 3714108 checks, 0 failed`. 기계어 비교(`sass_d4c/`)는 d4b와 같음: 프로그램 54쌍의 레지스터, stack, local이 d4b와 모두 같고(두 꼴 모두) hk 대비 차이는 위 행과 같은 6쌍, 라이브러리 함수 1 492개의 자원이 hk와 같음(해시 이름 20개는 해시를 가려 같음), symmetric GIN PTX 62쌍의 뜻밖의 줄 0 `[측정]`. 이 빌드는 d4b와 소스가 `ncclGinRsIdIs`의 종류 검사, 둘째와 셋째 낱말의 함수, 주석만 다르다. diff는 아래 커밋의 [rs_layer_dev.diff](rs_layer_dev.diff) | 세션 스크래치 `agent_rs_dev/out/`, `sass_d4c/` |
| 2026-10-12 | 검토 반영의 재확인(같은 에이전트, 고정한 사본 `agent_rs_dev/review_d4b/`, diff md5 `912fe83e`; 사본의 체크섬 모두 맞음, diff를 hk에 다시 적용해 사본과 같음, 단위 시험을 사본에서 한 번 빌드해 두 번 돌려 0 failed, d4c의 기계어 비교 수를 다시 셈: 프로그램 덤프가 두 꼴 모두 d4b와 바이트까지 같음, 라이브러리 자원이 hk와 같음, PTX 뜻밖의 줄 0). 판정: "no blocking issue". (1), (4), (5), (6), (10)의 고침이 맞고 (2), (3), (8), (9)의 기록이 맞음. 메모 둘: rs_log_api.h의 글 고침이 아직 커밋되지 않았음(아래 커밋으로 넣음), 검토 행의 "두 번 다시 빌드"는 "한 번 빌드해 두 번 돌림"(고침) | 세션 스크래치 `review_d4b_report.md` |
| 2026-10-12 | 작업 묶음 6(보낸 쪽 로그의 호스트 관리)의 충돌 확인(호스트 파일에 넣기 전, 세션 스크래치 초안 단계). 결과: 설계가 풀지 못한 충돌 없음. 아래 "작업 묶음 6의 충돌 확인" (1)–(12) | 9.4, 9.5, 9.6, 9.10.4절, host 브랜치 `rs_hold_api.h`, `rs_ckpt_api.h`(커밋 `a3478d84`, `2fb250fd`, 읽기만) |
| 2026-10-12 | 작업 묶음 6 구현. (가) [rs_log_api.h](rs_log_api.h)의 선언 덩어리를 호스트 파일 앞쪽에 그대로 넣음(`build_rs_dev.sh api`가 같은지 봄). (나) 순수 구역 "gin-restore (dev): log, suppress and replay, pure": 고리 하나의 호스트 상태(QP마다 로그 켬, 확정 여부, 절단점, 모두 덮음, 그 절단점의 넘친 수와 get 수, 마지막 멈춤의 기록; 칸마다 읽은 정체 낱말), 멈춤, 확정(늦게 온 옛 확정은 무시), 넘침(마지막 멈춤 뒤로 잃은 것이 없으면 그 멈춤부터 지키고 아니면 다음 멈춤까지 모두 덮음), get 규칙, 꼬리 옮기기(덮인 항목만, 아직 쓰는 칸에서 멈춤), 상대 항목 고르기, 내보내기 가능 판단(절단점 이상의 어느 위치에서든, 그 뒤 잃은 것과 get이 없을 때), 확정 단계. (다) 호스트 구역 "gin-restore (dev): log, suppress and replay": 멈춤 읽기(logOn을 NIC으로 쓰고 다시 읽음), 확정, 머리 읽기(helper는 NIC, application은 자기 stream의 CUDA 복사), QP마다 메시지 수, 억제 예산, get 수 읽기, 덮인 위치, 훑기(host 브랜치가 10 ms마다 부름: 넘침, get, 두 번째 사용자 문맥을 DISARM할 상대로 돌려주고 꼬리를 옮기며 사용량 표본), 상대 항목 모으기, 사용량, 해제된 window 수. 측 표를 만들 때(재기만 하는 모드가 아니고 고리가 있을 때) 상태를 만들고 문맥이 끝날 때 지우며, 문맥 끝 줄에 꼬리, 옮긴 수, 쓰는 칸에서 멈춘 수, 표본 사용량의 평균과 최대를 더함. fail-fast 프로세스는 상태가 없어 하는 일이 없음 `[소스]` | [rs_layer_dev.diff](rs_layer_dev.diff) |
| 2026-10-12 | 작업 묶음 6 빌드됨(rain, nice 19, ionice idle; 실행 안 함): 연구 `out/rs_d6a` libnccl `79dca00cf08c691d1d106902c3f6f593`, 운영 `out/rsp_d6a` `77dbdcf8f6880d69fbca63ce658ad089`. 장치 헤더가 d4c와 같아 호스트 파일 하나만 다시 컴파일(장치 객체는 d4c 그대로), 경고 0(NCCL의 `-Wno-unused-function` 아래: 선언만 하고 아직 정의하지 않은 작업 묶음 9의 함수가 경고되지 않음) `[측정]`. diff md5 `e18e43a2`, 다시 적용 확인 통과. 검토 반영 뒤의 마지막 빌드는 아래 검토 행 | 세션 스크래치 `agent_rs_dev/out/`, `build_rs_d6a.log` |
| 2026-10-12 | 작업 묶음 6 시험함(CPU 단위 시험, ASan과 UBSan): `rs_unit_dev: 9699172 checks, 0 failed` `[측정]`. 더한 시험: 고리와 호스트의 모형(장치의 자리 잡기와 아직 쓰지 않은 칸, 상대마다 멈춤, 늦거나 차례가 바뀐 확정, 넘침과 get, 꼬리 옮기기를 무작위로 600번 × 1 500걸음; 셋 가운데 하나는 모든 상대가 자주 멈추고 확정되는 경우): (1) 꼬리는 덮이지 않았거나 아직 쓰는 항목을 넘지 않음, (2) 완전한 상대는 절단점 뒤의 항목이 모두 고리에 남고 상대 고르기가 그것을 정확히 찾으며 내보내기 판단이 절단점과 머리에서 참, 절단점 − 1, 넘침, get에서 거짓, (3) 덮인 위치 아래의 항목은 모두 덮임, (4) 모든 상대가 확정되는 경우 꼬리가 머리를 따라감. 완전한 상대 확인 53만 번, 늦은 확정 6천 번, 넘침 2만 번, get 5천 번. 시험이 실제로 잡는지 바꿔 본 판 둘(늦은 옛 확정을 무시하지 않음, 아직 쓰는 칸을 넘음)은 실패 2만여 개씩을 냄 `[측정, 스크래치 p6scratch]`. 확정 단계 함수. NIC으로 읽고 쓰는 호스트 쪽은 GPU 없이 시험할 수 없음 `[미확인]` | [rs_unit_dev.cc](rs_unit_dev.cc) |
| 2026-10-12 | 작업 묶음 6의 독립 코드 검토(읽기 전용 에이전트, 같은 모델, 고정한 사본 `agent_rs_dev/review_d6/`, diff md5 `e18e43a2`; 검토자가 diff를 다시 적용해 사본과 같음, 단위 시험을 사본에서 빌드해 두 번 돌려 0 failed, host 브랜치의 부르는 자리를 읽음). 판정: "no blocking issue". 기준마다: 꼬리는 쓰이고 덮인 항목만 넘음(0으로 채운 칸, 위치 0, 칸 캐시의 `~0`도 안전), 늦은 옛 확정 무시, 넘침의 처리, get 규칙, 절단점 이상 어느 위치에서든 내보내기 판단(host의 확인한 절단점과 맞음), 스레드 규칙, fail-fast는 새로 하는 일 없음, 시험이 라이브러리의 글을 씀. 고칠 것: (1) 넘침을 멈춤이나 옛 확정이 먼저 보면(넘친 수를 그쪽이 먼저 올림) 훑기가 끊김으로 보고하지 않아 그 상대가 DISARM되지 않고 완전으로 남음(검토자의 모형에서 861번) → 끊김 검사를 본 수와 상관없이 하게 고침; (2) 확정에서 찾은 끊김을 다음 훑기까지 미뤄 host가 그 사이 무장함 → `gdakiRsLogStable`이 끊김이면 이유와 함께 ncclInvalidUsage를 돌려줌(host는 실패면 무장하지 않음, 그 자리를 읽어 확인), rs_log_api.h 주석. 메모: (3) 훑기가 오류로 끝나면 DISARM 목록을 버림 → 측 표를 못 읽으면 목록을 남기고 오류, 꼬리 쓰기 실패는 세기만 하고 목록을 넘김; (4) 모으기의 범위 검사가 꼬리가 `to`를 넘었을 때 넘쳐 빈 내보내기를 거절 → 고침(빈 결과); (5) 덮어 넘기는 항목(모두 덮인 QP)이 정체 낱말만 보이고 나머지가 아직일 때 그 칸이 n번 뒤에야 다시 쓰인다는 가정 → 순수 구역 주석; (6) 내보내기에서 QP마다 항목의 메시지 수 합 = hold 시작의 M − 절단점의 M을 확인 → 작업 묶음 9; (7) application 스레드의 머리 읽기가 문맥의 CUDA 장치를 고르지 않음 → 고름; (8) host 브랜치의 자리 표시 가운데 `gdakiRsExecRead`, `gdakiRsPlanAllExecuted`, `gdakiRsLogExport`는 작업 묶음 9까지 남겨야 함 → 통합 항목; (9) 시험의 완전 상대 확인이 바로 그 경우를 건너뜀, 모으기가 시험한 고르기 함수를 쓰지 않음 → 훑기 뒤 불변식(완전한 상대는 절단점 뒤로 넘침과 get이 없음)을 더하고 모으기가 `gdakiRsLogStatePeerPositions`를 씀; (10) 기록의 글 → 반영. 고친 뒤: `rs_unit_dev: 10161568 checks, 0 failed`; 바꾼 판 넷(늦은 옛 확정, 아직 쓰는 칸을 넘음, 절단점 아래 내보내기, 본 수에 걸린 끊김 검사)이 각각 1만 4천에서 54만 개 실패를 냄(스크래치 `mut6/`); 마지막 빌드 연구 `out/rs_d6c` libnccl `6a679379d4890e09c3070c649113cca7`, 운영 `out/rsp_d6c` `e6252966c1604c0ba07fb45c5f9391ea`(호스트 파일 하나, 경고 0), diff md5 `5320871a`, 다시 적용 확인 통과 `[측정]` | 세션 스크래치 `review_d6/`, `review_d6_report.md`, `mut6/` |
| 2026-10-12 | 사용자 방향(메인 세션이 전함): 매크로 없이 빌드한 프로그램이 첫 put에서 멈추는 규칙과 레지스터 −2에서 +2의 차이를 받아들이지 않음. 작업 묶음 6을 멈추고 먼저 고침. 설계: (1) 측 표 포인터는 `ncclGinRestoreResume`이 성공할 때만 장치에 줌(문맥을 만들 때는 모든 프로세스에서 0; strict 강제와 루프백 MR 등록은 그대로 만들 때), (2) `ncclGinRestoreResume`은 `nccl.h.in`의 static inline 래퍼가 되어 부르는 번역 단위의 매크로 유무를 라이브러리의 입구에 넘기고, 없으면 지역 판정이 "program not built with NCCL_GIN_RESTORE_DEVICE"로 거절(교환으로 모든 rank가 같음; 번역 단위를 섞는 것은 지원하지 않음), (3) 매크로 없이 빌드한 장치 코드는 포인터 읽기도 비교도 trap도 없이 hk와 바이트까지 같음(레지스터, stack, local, SASS 명령; 모든 커널, 라이브러리와 프로그램). 같은 날 더함(측정 셀): `NCCL_GIN_RESTORE_LOG_MEASURE=<ms>`는 문맥을 만들 때 포인터를 줌(비용 드라이버는 Resume을 부르지 않음; 매크로 빌드 프로그램이 필요), `NCCL_GIN_RESTORE_LOG_MEASURE_LOG=0|1`(기본 1): 0은 포인터만 주고 로그 끔(무장 전 hold 길의 비용: 게이트, 억제 예산 읽기, 키 다시 읽기, 메시지 수), 1은 로그 켬(`NCCL_GIN_RESTORE_CHECKSUM`의 방식) | 메인 세션의 전달 |
| 2026-10-12 | 위 방향의 충돌 확인(코딩 전). 막는 충돌 하나를 찾아 메인 세션에 올림: (1)의 "장치 배열의 모든 문맥에 씀"(작업 묶음 3의 사용자 결정 (가), GPU 문맥 끝의 포인터)과 (3)의 "hk와 바이트까지 같음"은 함께 될 수 없다. hk의 `ncclGinGdakiGPUContext`는 96 B이고 틈은 3 B뿐이라 포인터를 넣으면 문맥 간격이 0x60에서 0x68로 바뀌고, 그 간격은 NCCL 자신의 symmetric 커널을 포함한 모든 GIN 커널에 들어간다(작업 묶음 3에서 잼: PTX 292줄, SASS 556곳) `[소스, 측정]`. 메인 세션의 확인(같은 날): 포인터를 분류 블록(`struct ncclGinGdakiQ4`, 라이브러리가 GDAKI 문맥마다 할당하고 모든 GPU 문맥이 `fault`로 가리킴) 끝에 둔다(작업 묶음 3의 고를 길 (나)). **작업 묶음 3의 (가)는 철회**: 사용자의 새 방향(trap 없음, 매크로 없는 코드는 hk와 같음)이 그 앞 선택을 대신하고, 메인 세션이 사용자에게 까닭을 전함. 작업 묶음 3의 행은 기록으로 남는다. 나머지 확인은 아래 "trap 없는 빌드 선택의 충돌 확인" (1)–(12) | [rs_log_api.h](rs_log_api.h) |
| 2026-10-12 | trap 없는 빌드 선택 구현. (가) 함께 쓰는 헤더: 측 표 포인터를 `ncclGinGdakiGPUContext` 끝에서 빼고 `ncclGinGdakiQ4` 끝에 둠(GPU 문맥은 hk의 배치와 간격). (나) 장치 헤더: 매크로가 없으면 put, putValue, get과 API 특수화가 hk와 토큰까지 같음(주석과 줄 바꿈만 다름; 토큰 12 165개 같음 `[측정]`). 매크로가 있으면 `rsSideOf`(분류 블록의 포인터)를 읽고 0이 아니면 hold 함수. (다) 호스트 파일: 측 표 설정에서 포인터를 쓰지 않음(`rsPtrSet`은 이제 "측 표 준비됨"), `gdakiRsPublish`(분류 블록에 8바이트 동기 쓰기, 자기 stream, 문맥의 장치)와 `gdakiRsPublishFor`, Resume 판정 바로 뒤의 게시(성공일 때), 측정 모드는 문맥을 만들 때 게시하고 `NCCL_GIN_RESTORE_LOG_MEASURE_LOG`(기본 1)로 logOn을 정함, Resume 지역 판정 끝의 조건 "program not built with NCCL_GIN_RESTORE_DEVICE", 입력 멈춤은 게시 전이면 거절. (라) `nccl.h.in`: `ncclGinRestoreResumeBuilt` 선언과 static inline 래퍼 `ncclGinRestoreResume`, `NCCL_GIN_RESTORE_DEVICE_BUILT`, 빌드 선택과 측정 모드의 주석, Resume 주석 끝 문장. (마) `gin/gin_host.cc`: 입구 이름 `ncclGinRestoreResumeBuilt`와 깃발, (바) `include/gin/gin_host.h`: 사실 칸 `deviceBuilt`. 이 변경은 작업 묶음 6의 고친 판(아직 커밋하지 않음) 위에 함 | [rs_layer_dev.diff](rs_layer_dev.diff) |
| 2026-10-12 | 빌드됨(rain, nice 19, ionice idle; sm_75와 sm_86; 실행 안 함): 연구 `out/rs_d4f` libnccl `1ad323d2ed06a0e9dcdd8df915a24cfa`, 운영 `out/rsp_d4f` `e76e7f9c49b52d1dd224cd174f977b30`, 각각 389개 컴파일, 이 계층의 파일에서 경고 0(NCCL 자신의 `symmetric_sched.cc:327` 하나) `[측정]`. 시험함: `rs_unit_dev: 10161735 checks, 0 failed`(새 지역 조건 포함). 중간에 멈춘 빌드(`rs_d4e`, 측정 모드를 바꾸기 전)는 끝나지 않아 산출물이 없음 | 세션 스크래치 `agent_rs_dev/out/`, `build_rs_d4f.log` |
| 2026-10-12 | 매크로 없는 꼴의 정확한 비교([exact_cmp_dev.sh](exact_cmp_dev.sh), [ff_cmp_dev.sh](ff_cmp_dev.sh); GPU에서 돌리지 않음). 처음 판은 `cuobjdump -sass` 출력에서 오프셋이 네 자리인 명령 줄만 골랐다. 그래서 0x10000 이상의 명령과 인코딩의 둘째 낱말(스케줄 비트)을 빠뜨렸고, 그 판정은 버리고 덤프 전체(모든 줄)로 다시 했다(출력 `sass_d4f/exact2/`). (1) 프로그램 넷(연산 커널 11개의 ff_ops, gin_ts2, gin_mr, ring 예제)을 이 헤더(매크로 없음)와 hk의 설치된 헤더로 같은 깃발로 컴파일: 프로그램과 아키텍처 짝 8개 모두 SASS 덤프 전체와 `cuobjdump -res-usage`(레지스터, stack, shared, local)가 hk와 같음(예: ff sm_75 81 288 명령, 162 640줄) `[측정]`. (2) 라이브러리 `rs_d4f`(NCCL 커널은 매크로 없이 빌드)의 장치 객체 207개를 hk 빌드 트리의 객체와: 183개는 덤프 전체가 같고, 2개는 컴파일 해시 이름을 가리면 같고, 22개(symmetric GIN 커널)는 다르다. 이 22개는 명령 수도 다르다(예: AllGather 객체 68 560 대 70 392). 처음 판의 "명령 수는 같음"은 잘린 덤프에서 나온 틀린 기록이다. 라이브러리 전체의 자원(1 748 함수 항목)은 해시를 가리면 hk와 같음 `[측정]`. 22개의 까닭은 다음 행. (3) 22개를 만드는 symmetric GIN 소스 31개의 PTX(compute_75와 86, 62쌍)는 컴파일 해시와 단언 문자열 속 빌드 경로만 가리면 hk의 소스에서 만든 PTX와 줄까지 같음 `[측정]` | 세션 스크래치 `agent_rs_dev/sass_d4f/exact2/`, `sass_d4f/exact2.out`, `agent_rs_dev/ptx/` |
| 2026-10-12 | 매크로 꼴의 비용(같은 비교, hk 대비; 측정 모드의 로그 켬과 끔 팔은 이 꼴의 같은 코드를 돌고 로그 끔 팔은 로그 함수를 부르지 않음). 연산 커널: 부르는 자리(자원 나눔 셋)마다 64비트 읽기 하나(`fault->restore`; `fault` 읽기는 hk의 것과 합쳐짐), 비교와 분기, hold 함수의 호출 덩어리가 더해지고 hold에만 있는 함수 3–6개(2 210–8 086 명령)가 호출 그래프에 듦; VA 신호 put은 신호 window 번호 읽기 하나 더. 레지스터: 연산 커널 sm_75 41–64 → 54–92, sm_86 40–64 → 56–96; 프로그램 sm_75 136–234 → 160–240, sm_86 124–168 → 156–203; stack과 local은 같음 `[측정]` | 세션 스크래치 `agent_rs_dev/sass_d4f/` |
| 2026-10-12 | 다른 22개의 까닭(검토자가 찾고 다시 셈). (가) hk 빌드 트리(`agent_gd/gin_hk/build`)의 이 22개 객체는 2026-10-09 01:01–01:03에 컴파일됐고, hk 트리의 장치 헤더는 그 뒤에 바뀌었다(`gin_gdaki.h` 수정 13:28, hr 커밋 16:24). NCCL의 의존성 처리는 GIN 장치 헤더를 보지 않아 이 객체들은 다시 컴파일되지 않았다(`build_rs.sh`의 devsync 규칙이 이 때문에 있음) `[측정: 파일 시각]`. (나) 22개 모두를 NCCL 자신의 명령으로 hk 트리(오늘의 소스)와 이 트리(빌드 경로 길이를 hk와 같게 하는 심볼릭 링크)에서 다시 컴파일하면 덤프 전체가 같다: 22/22([samelen_dev.sh](samelen_dev.sh)의 규칙; 이 기록의 실행은 같은 규칙의 스크래치 스크립트를 셋씩 병렬로 돌림). 그 가운데 21개는 병렬 실행에서, 1개는 따로 다시 돌린 것이다(병렬 `make -n`이 생성 소스를 다시 쓰는 사이에 그 컴파일이 실패함, 내 스크립트의 경합) `[측정]`. (다) 이 빌드의 객체(이 트리의 경로, 3글자 짧음)는 같은 길이 경로의 다시 컴파일과 다르다: 10개는 상수 뱅크 오프셋(빌드 경로 문자열의 자리) 줄만(48줄이나 256줄), 12개는 코드 배치까지(그 가운데 2개는 명령 수가 8 다름) `[측정]`. 이 트리의 경로에서 다시 빌드한 d4g의 장치 코드는 d4f와 같으므로(아래 d4g 행) 다름은 빌드 경로의 길이에서 온다 `[추론: 경로 말고는 같은 명령]`. 그래서 hk의 소스에 대해 매크로 없는 라이브러리는 같은 길이 경로에서 SASS가 바이트까지 같다. 앞 기록 바로잡기: 행 17의 "AllGather RailRing sm_75 34 128 → 35 088"에서 34 128은 오래된 hk 객체의 값이다. hk의 실제 소스로는 35 040이라 작업 묶음 4 다시 하기(d4b)의 차이는 +48 명령이다(+960 아님). 아래 통합 목록의 "사용자 확인 대기" 항목도 같은 까닭으로 풀림. 이 연구 밖의 사실(해석하지 않음): gpu-detect가 기록한 hk 라이브러리(`agent_gd/gin_hk/build/lib`, md5 `2913c777`)에 이 오래된 객체가 들어 있다. 그 셀이 NCCL의 symmetric GIN 커널을 썼는지는 `[미확인]` | 세션 스크래치 `agent_rs_dev/samelen2/run.out`, `samelen2/rerun.out`, `review_d4f_report.md`; 첫 판 `samelen/run.out`은 잘린 덤프라 버림 |
| 2026-10-12 | trap 없는 빌드 선택과 작업 묶음 6 고침의 독립 코드 검토(읽기 전용 에이전트, 같은 모델, 고정한 사본 `agent_rs_dev/review_d4f/`, diff md5 `d3958ac5`; 검토자가 diff를 다시 적용해 사본과 같음, `rs_d4f`와 `rsp_d4f`의 md5 맞음, 단위 시험을 사본에서 ASan과 UBSan으로 빌드해 `10160300 checks, 0 failed`). 판정: "no blocking issue". 기준마다: 매크로 없는 장치 헤더는 전처리 뒤 hk와 같음(빈 매크로 둘만 다름); 프로그램 8쌍은 검토자 자신의 덤프 전체 비교로도 같음(자원도); 라이브러리 재셈 183, 2, 22(위 행과 같음); 엄격한 PTX 62/62; 게시는 한 번, application 스레드, 문맥의 장치와 자기 stream, Resume이 돌아가기 전에 끝나고 ENABLE일 때만(실패하면 그 rank의 멈춤이 거절; 측정 모드는 생성 때; 블록은 0으로 시작하고 통째로 다시 쓰이지 않으며 측 표보다 뒤에 풀림); 래퍼는 C99, C11, gnu89, C++로 컴파일되고 깃발은 0과 1; Resume 고침은 최소(새 조건이 맨 끝, 게시는 ENABLE 바로 뒤); 매크로 빌드의 `rsSideOf`와 비용 기록 맞음; 작업 묶음 6 고침 모두 확인(옛 끊김 검사를 되넣으면 새 불변식이 수천 번 실패, mut6 넷이 14 676, 22 085, 540 997, 21 338개 실패). 지적: (1) should-fix: 라이브러리 SASS 기록이 잘린 덤프와 오래된 hk 기준에 기댐 → 위 두 행으로 바로잡음(행 17과 통합 목록의 확인 대기 항목 포함); (2) `deviceBuilt`는 Resume을 부르는 번역 단위를 말하지 커널의 단위를 말하지 않는다. Resume 단위에만 매크로가 있으면 포인터가 게시되고 커널은 로그 밖으로 보낸다. host 브랜치의 drain 확인이 모든 체크포인트를 버려 이를 잡는다 `[검토자, 소스]` → nccl.h에 규칙과 직접 부르는 바인딩의 의무를 적음, drain 확인의 이유에 섞인 빌드를 적는 것은 통합 목록; (3) 공개 기호가 바뀌어 test 브랜치 드라이버와 shim은 다시 빌드해야 함 → 통합 목록; (4) 게시가 실패해도 Resume은 성공을 돌려주고 WARN만 낸다 → 그대로 둠(판정은 모든 rank가 이미 같이 내림, 그 rank의 멈춤이 거절해 안전), `ncclGetLastError` 줄은 통합 목록의 제안; (5) `gdakiRsPublishFor`가 전역 `gdakiRecRegMu`를 잡은 채 CUDA를 부름(짧고 다른 stream을 기다리지 않음) → 기록만; (6) 게시 전에도 `gdakiRsLogReady`가 참이라 Resume이 성공하지 않은 hold 프로세스에서 helper가 10 ms마다 측 표를 NIC으로 읽음 → `gdakiRsLogPoll`이 게시 전에는 읽지 않고 돌아가게 고침; (7) 글: Resume 성공 줄의 "the communicator stays fail-fast" → "a fault still fails fast"로 고침, host 브랜치 OnStable의 "could not be trimmed"는 통합 목록, 토큰 12 165는 펼친 수 | 세션 스크래치 `review_d4f/`, `review_d4f_report.md` |
| 2026-10-12 | 검토 반영(d4g): `gdakiRsLogPoll`이 게시 전에는 돌아감(지적 6), Resume 성공 줄의 글(지적 7, 공유 구역의 한 줄), `nccl.h.in` 주석(지적 2: 깃발이 말하는 단위, 직접 부르는 바인딩). 빌드됨(rain, nice 19, ionice idle; sm_75와 sm_86; 실행 안 함): 연구 `out/rs_d4g` libnccl `013fe90218c45b336658493b849e65d0`, 운영 `out/rsp_d4g` `c3193857b94bd90717ee13ca23e84004`, 이 계층의 파일에서 경고 0(NCCL 자신의 `symmetric_sched.cc:327` 하나) `[측정]`. 장치 헤더 둘은 d4f와 같고(diff로 확인) 라이브러리 넷(`rs_d4f`, `rs_d4g`, `rsp_d4f`, `rsp_d4g`)의 `cuobjdump -sass` 전체가 같다(md5 `9f32ba1d`, 장치 객체를 모두 다시 컴파일한 뒤) `[측정]`. 그래서 위의 정확한 비교는 d4g에도 맞다. 시험함: `rs_unit_dev: 10139269 checks, 0 failed` `[측정]`. diff md5 `f4d096e6`(3504줄), hk에 다시 적용하면 트리와 같음 `[측정]`. 이 상태가 작업 묶음 6과 trap 없는 빌드 선택의 커밋이다 | 세션 스크래치 `agent_rs_dev/out/`, `build_rs_d4g.log`, `build_rsp_d4g.log`; [rs_layer_dev.diff](rs_layer_dev.diff) |
| 2026-10-12 | 작업 묶음 9 구현(충돌 확인은 아래 절). (가) 순수 구역: QP마다 누적 실행 수(24비트 감기, 기준선 다시 잡기), 억제 예산 B = X − P, 항목 검사(종류, window 번호, 크기), 항목의 checksum 방식, 덩어리로 세는 checksum(장치의 걷기와 같은 낱말과 갈래), 내보내기 스트림 만들기(머리, 항목과 put의 데이터, 꼬리; 출처가 바뀌거나 읽지 못하면 그 자리에서 꼬리를 ok = 0으로)와 풀기(꼬리를 먼저 읽음), QP마다 메시지 확인(항목의 메시지 합 = hold 시작의 M − 절단점 멈춤의 M), 가져오기 계획(모든 내보내기를 먼저 검사; 데이터 복사는 생존 rank 차례, 그다음 위치 차례; 신호 더하기는 대상마다 합침; put 대상이 신호 낱말과 겹치면 거절), 로그 상태에 멈춤마다의 M(절단점부터 1024개). (나) 호스트 구역: `gdakiRsExecObserve`, `Rebase`, `Read`(opMu, watch처럼), `SetBase`, `gdakiRsSuppressSet`(application 스레드의 CUDA 복사, 다시 읽어 확인), 억제 줄(WARN, QP마다 한 번: 예산을 다 쓴 때 훑기에서, 아니면 문맥 끝에서), `gdakiRsLogReadGetRefused`, `gdakiRsPlanAllExecuted`(U = S, n = 0, 계획 앞 검사 셋), `gdakiRsLogExport`(모으기, 메시지 확인, 출처를 NIC으로 덩어리마다 window 등록부 잠금 아래 읽음), `gdakiRsSpareImport`(계획, window 등록부 잠금, 로그 상태의 stream에서 복사와 신호 더하기, 예산과 msgs, 실행 수 기준). host 브랜치 공유 글이 없는 이 브랜치의 빌드에는 `gdakiCkptPeerP`의 같은 기록을 `#ifndef GDAKI_CKPT_MAGIC` 아래 둠. (다) 앞 코드 자리: `gdakiRsStart`가 window의 데이터 범위를 루프백 MR에 더함, 문맥 끝 줄이 억제 줄을 부름, 선언 덩어리 뒤 선언 하나, 로그 상태를 만들 때 실행 수를 설정의 rmsn0으로 시작. (라) [rs_log_api.h](rs_log_api.h)의 작업 묶음 9 부분 확정(getRefused 읽기 더함, SuppressSet은 application 스레드, 내보내기의 돌려줌 값, 가져오기의 검사와 억제 줄의 뜻, 연결). 장치 코드는 바뀌지 않음 | [rs_layer_dev.diff](rs_layer_dev.diff) |
| 2026-10-12 | 작업 묶음 9 빌드됨(rain, nice 19, ionice idle; sm_75와 sm_86; 실행 안 함): 연구 `out/rs_d9a` libnccl `875430b63a88d2dbae2e00bdb07b5217`, 운영 `out/rsp_d9a` `ad9bb58703240ff71db09c6288159f1f`, 호스트 파일만 다시 컴파일, 경고 0 `[측정]`. 시험함(CPU 단위 시험, ASan과 UBSan): `rs_unit_dev: 12458088 checks, 0 failed` `[측정]`. 더한 시험: (1) 실행 수(24비트 감기, 두 읽기 사이 최대 2^23 − 1, 기준선 다시 잡기; 200 × 300걸음)와 예산; (2) 항목 검사와 checksum 방식; (3) 덩어리로 센 checksum이 장치의 걷기와 같음(3 000 데이터, 덩어리 크기와 차례 무작위); (4) 내보내기 스트림: 만들고 풀면 같음 400번, 출처가 바뀌면 거절 242번(FULL은 아무 바이트, SAMPLED는 첫 바이트), 읽기 실패와 put 실패, 망가진 스트림 여섯 가지; 메시지 확인(맞음, 하나 많음, 거꾸로, 항목 빠짐); (5) 가져오기 계획 300번: 계획대로 적용한 메모리가 항목을 차례로 바로 적용한 메모리와 같음, 거절 열세 가지(incarnation, nonce, 받는 rank, 내보내기 없음, 뜻밖의 내보내기, 생존 쪽 거절, P 없음, P 둘, X < P, window 밖, 신호 정렬, 없는 신호 window, 데이터와 신호 낱말 겹침)와 같은 번호의 window 둘, 겹치지 않으면 받음; (6) 로그 상태 모형에 M: 완전한 상대의 절단점 M이 지켜지고 절단점 뒤 항목 수 = 지금 M − 그때 M(1 099 456번). NIC과 CUDA로 읽고 쓰는 호스트 쪽(ExecRead, SuppressSet, 내보내기의 읽기, 가져오기의 복사)은 GPU 없이 시험할 수 없음 `[미확인]`. diff md5 `68449289`(4 334줄), hk에 다시 적용하면 트리와 같음 `[측정]` | 세션 스크래치 `agent_rs_dev/out/`, `build_rs_d9a.log`, `build_rsp_d9a.log`; [rs_unit_dev.cc](rs_unit_dev.cc) |
| 2026-10-12 | 작업 묶음 9의 독립 코드 검토(읽기 전용 에이전트, 같은 모델, 고정한 사본 `agent_rs_dev/review_d9a/`, diff md5 `68449289`; 검토자가 diff를 다시 적용해 사본과 같음, d4g 대비 바뀐 파일은 호스트 파일 하나(장치 헤더 그대로), API 덩어리 같음, `rs_d9a`와 `rsp_d9a`의 md5 맞음, 단위 시험을 사본에서 빌드해 두 번 돌려 0 failed, 바꾼 판 열 개를 모두 잡음(1–2 198 912개 실패, 하나는 ASan)). 판정: "blocking: B1". 기준마다: PlanAllExecuted는 `gdakiTsRepostPlanAll`과 같은 검사와 칸(U = S, n = 0)이고 `gdakiTsRepostApply`는 U만 옮김; 내보내기의 규칙, 덩어리 읽기, 돌려줌 값이 host 브랜치의 부르는 자리에 맞음; 가져오기의 검사, 차례, 신호 합, 겹침 거절, putValue와 신호 주소가 장치와 맞음; 억제 줄의 형식과 시점; 잠금 차례에 거꾸로 없음, host 브랜치의 ExecRead 네 자리는 opMu 밖; fail-fast는 새로 하는 일 없음; window MR은 `reserve` 앞. 지적: (B1, 막음, 통합 차례) 가져오기의 신호 더하기는 호스트의 읽고 더하고 쓰기인데, spare 브랜치의 한 번에 생존 rank 하나 차례(`rs_spare_api.h`)에서는 모든 내보내기가 모일 때 앞 생존 rank들이 이미 게시해 예비 프로세스의 신호에 RDMA 원자 더하기를 보낸다. 그 사이에 닿은 원자는 오류 없이 잃고 끝나지 않는 기다림이 된다 → 이 브랜치 안에서 고칠 수 없음(공유 장치: spare 브랜치의 차례나 루프백 QP와 MR의 원자 접근), 메인 세션의 결정 대기로 API 주석과 통합 목록에 적음; (S1) 이미지의 pageable `cudaMemcpy`가 끝나기 전에 가져오기의 non-blocking stream이 읽을 수 있음 → 가져오기 처음에 `cudaDeviceSynchronize`; (S2) 내보내기와 복원한 체크포인트를 묶는 것이 없음 → 머리에 체크포인트 칸, 내보내기와 가져오기에 인자, 가져오기가 견줌(인터페이스 바뀜: host 브랜치의 두 부르는 자리, 통합 목록); (S3) 출처 읽기 오류가 NIC 복사 경로를 끌 수 있음(`gdakiLbXfer`의 오류 완료 길): 9.6절의 "끄지 않음"과 어긋남, 오류 완료 뒤 루프백 QP는 이미 ERR이라 다시 만들지 않으면 지킬 수 없음 → 어긋남으로 기록(복원은 fallback); (S4) 실행 수 연결 셋이 아직 어느 브랜치에도 없고, 하나라도 빠지면 X가 작아져 신호가 두 번 더해짐 → 통합의 막는 조건으로 적고, 기준선 읽기가 실패하면 그 QP의 수를 버리는 `gdakiRsExecInvalidate`를 더함(그 뒤 ExecRead가 거절); host 브랜치에 체크포인트를 받는 rank가 PAUSED의 P를 자기 msgs와 견주는 확인을 제안; (N1) 사본 MD5SUMS에 빈 임시 파일 줄 → 스크래치 스크립트만; (N2) API 글의 "import calls SuppressSet"(실제는 같은 값을 직접 씀), SuppressSet과 getRefused 읽기를 부르는 곳이 아직 없음 → 글 고침, 통합 목록; (N3) 행 36의 거절 수 → 고침; (N4) 실행 수는 읽은 차례대로 접혀야 하는데 ExecRead가 opMu를 놓은 뒤 접음 → opMu 안에서 접고 API를 helper로; (N5) 시험이 절단점의 M만 봄 → 확인했지만 아직 확정되지 않은 뒤의 멈춤도 봄; (N6) window 데이터 MR의 비용과 수명, 자원 window 출처는 내보내기가 거절; (N7) put의 출처는 문맥 collComm의 window 번호로 찾음: 다른 communicator의 window가 출처면 같은 번호의 다른 window를 읽음(checksum이 꺼져 있으면 조용함) → application 규칙으로 통합 목록; (N8) 매크로 없이 빌드한 커널의 보내기(앞서 있던 것); (N9) 예비 프로세스는 QP를 잇고 나서 Rebase, nonce; (N10) 자리 표시 지움 | 세션 스크래치 `review_d9a/`, `review_d9a_report.md`, `review_d9a_work/mut/` |
| 2026-10-12 | 검토 반영(d9b): S1, S2(`gdakiRsLogXHdr::ckpt`, `gdakiRsLogExport(..., ckpt, ...)`, `gdakiRsSpareImport(..., ckpt, ...)`, 계획의 견줌), S4(`gdakiRsExecInvalidate`, ExecRead의 거절), N2와 B1(API 글), N3, N4(ExecRead가 opMu 안에서 접음), N5(시험). 빌드됨(rain, nice 19, ionice idle; 실행 안 함): 연구 `out/rs_d9b` libnccl `362e88695717d77e631f0b6588d55fb6`, 운영 `out/rsp_d9b` `367afbb6390902936762c702d7fdc956`, 경고 0 `[측정]`. 시험함: `rs_unit_dev: 13213846 checks, 0 failed`(뒤 멈춤의 M 확인 759 132번, 다른 체크포인트의 내보내기 거절 더함) `[측정]`. diff md5 `de133d86`(4 365줄), 다시 적용 확인 `[측정]`. B1은 열림(메인 세션의 결정) | 세션 스크래치 `build_rs_d9b.log`, `build_rsp_d9b.log`; [rs_layer_dev.diff](rs_layer_dev.diff) |
| 2026-10-12 | 검토 반영의 재확인(같은 에이전트, 고정한 사본 `agent_rs_dev/review_d9b/`, diff md5 `de133d86`; 사본과 다시 적용, API 덩어리, `rs_d9b`와 `rsp_d9b`의 md5, 단위 시험 두 번 0 failed, 바꾼 판 열둘을 모두 잡음: 앞의 열 개와 체크포인트 검사를 뺀 판(300개 실패), 첫 멈춤의 M만 지키는 판(1 658 283개 실패)). 판정: S1, S2, S4, N2–N5는 맞고 빠짐없음, 새 막는 문제나 고칠 것 없음; B1은 열린 채(메인 세션의 결정), 그 글은 맞음. 메모와 처리: (d1) 실행 수의 Observe와 Rebase는 예비 프로세스의 handshake(application 스레드, helper 전)에서도 부름 → API 글 고침; (d2) Invalidate는 영구이고 QP의 두 rank에 다 미침(그 rank의 drain, 상대의 멈춤에 BUSY) → API 글에 적음; (d3) 가져오기의 기다림 순서 글 → 고침; (d4) 이미지를 받는 쪽의 `cudaMemcpy`도 문맥의 장치에서 하거나 스스로 동기화 → 통합 목록; (d5) 머리가 8바이트 늘었으나 version은 1 그대로 → 그대로 둠(이 스크래치 밖에 version 1 스트림 없음); 선택지 (나)에는 HCA의 `atomic_cap`이 `IBV_ATOMIC_HCA` 이상이어야 함 → 통합 목록 | 세션 스크래치 `review_d9b/`, `review_d9b_report.md`, `review_d9b_work/mut/` |
| 2026-10-12 | 재확인 반영(d9c, API 글만; 호스트 파일의 API 덩어리도 같이 바뀜). 빌드됨(rain, nice 19, ionice idle; 실행 안 함): 연구 `out/rs_d9c` libnccl `8e3073372498dd7004ebf91cebbd36f4`, 운영 `out/rsp_d9c` `7a7d4528f4e4a04e1080a54d3b2d88b2`, 경고 0 `[측정]`. 시험함: `rs_unit_dev: 13213560 checks, 0 failed` `[측정]`. diff md5 `fe4b47d8`(4 370줄), 다시 적용 확인 `[측정]`. 작업 묶음 9의 커밋은 이 상태다. B1은 열린 채 | 세션 스크래치 `build_rs_d9c.log`, `build_rsp_d9c.log`; [rs_layer_dev.diff](rs_layer_dev.diff) |
| 2026-10-12 | 메인 세션의 결정(B1): 선택지 (나). 가져오기의 신호 더하기를 호스트의 읽고 더하고 쓰기 대신 루프백 QP의 RDMA fetch-and-add로 한다. 두 선택지: (가) spare 브랜치의 driver가 모든 생존 rank의 REJOIN과 STATE를 먼저 받고 가져오기를 한 뒤 TOKEN, READY, Commit을 차례로 함(한 번에 하나 차례를 바꿈); (나) 신호 더하기를 NIC 원자 연산으로. (나)를 고른 까닭(이 브랜치가 적음, 결정은 메인 세션): 경합이 생기는 자리(같은 HCA가 실행하는 원자 연산끼리)에서 원자성으로 막으므로 spare 브랜치의 차례와 생존 rank의 시한 계산을 건드리지 않고, 하드웨어 보장(`atomic_cap` ≥ `IBV_ATOMIC_HCA`이면 그 HCA의 모든 QP의 원자 연산이 서로 원자적)에 기댄다 `[추론: verbs의 atomic_cap 뜻]`. 요구된 것: 신호 표와 VA 신호 window의 루프백 MR에 REMOTE_ATOMIC(복원을 요청한 프로세스만), 루프백 QP의 원자 속성, Resume 지역 조건 "HCA atomic capability below IBV_ATOMIC_HCA"(교환으로 모든 rank가 같은 이유로 거절), 쓰는 합이 항목의 합과 같은지 보는 CPU 쪽 확인(단위 시험). 데이터 복사는 그대로 | 메인 세션의 전달 |
| 2026-10-12 | (나) 구현(d9e). (가) 호스트 파일 dev 구역: `gdakiRsLbAddAtomic`(gdakiLbAddRange와 같은 등록에 `IBV_ACCESS_REMOTE_ATOMIC`; NIC 복사 경로의 목록에도 넣어 경로와 함께 PD보다 먼저 풀림), `gdakiRsLbAtomicRkey`, `gdakiRsLbFetchAdd`(staging 버퍼로 옛 값을 받는 fetch-and-add 하나, `NCCL_GIN_TS_COPY_MS` 한도, 실패나 오류 완료면 경로를 끔: QP가 ERR이 되므로 `gdakiLbXfer`와 같음), `gdakiRsLbAtomicSetup`(측 표 설정에서 일반 MR보다 먼저: 측 표, 신호 표, 문맥 전에 등록한 이 collComm의 모든 window(어느 것이 VA 신호인지 미리 모름)를 원자 MR로; 루프백 QP 둘에 RTS에서 RTS로 원자 접근; 측 표 fence 낱말에 +1을 더해 1로 읽히는지(호스트 바이트 차례), −1로 0으로 되돌리는 자기 시험; 실패면 `rsLbOk`가 거짓이 되어 Resume이 이유와 함께 거절, `atomic_cap`이 낮으면 아무것도 등록하지 않고 Resume의 새 조건이 거절). 순수 구역: `gdakiRsImportSigCheck`(모든 내보내기를 다시 풀어 신호 값을 따로 더하고 계획의 더하기와 대상마다, 합으로, 개수로 견줌). 가져오기: 계획 → 신호 합 확인 → 원자 경로와 대상(8바이트 정렬, 원자 MR 안) 확인, 여기까지 아무것도 쓰지 않음 → 장치 동기화 → (1) 데이터 복사와 그 끝 기다림 → (2) 신호 더하기를 fetch-and-add로 하나씩 완료, 낸 합 = 항목 합 → (3) 예산, msgs, 실행 수 기준. 호스트의 읽고 더하고 쓰기는 없앰. (나) 함께 쓰는 구역(통합 목록): 공용 순수 구역의 `GDAKI_RS_ATOMIC_HCA`, `gdakiRsLocalIn::atomicCap`, 지역 판정 맨 끝 조건 한 줄, Resume의 사실 한 줄(`in.atomicCap = ... ib_dev_attr.atomic_cap`). (다) [rs_log_api.h](rs_log_api.h)의 가져오기 글: 차례, 까닭, 전제(가져오기 동안 NIC 복사 경로의 사용자는 하나) | [rs_layer_dev.diff](rs_layer_dev.diff) |
| 2026-10-12 | (나)의 데이터 복사 경합 확인(메인 세션의 요청: 경합이 없음을 까닭과 함께 적고, 있는 window가 있으면 적을 것). 전제 "어느 생존 rank도 DONE_RS 전에 예비 프로세스의 window에 데이터를 쓰지 않는다"는 그대로는 맞지 않다: host 브랜치에서 생존 rank의 게이트는 게시 때 열리고(PUBLISHED: "gates even, QPs RTS with the spare", `rs_hold_api.h` 82) 게시는 DONE_RS보다 앞이며(`rs_spare_api.h` 8단계), spare는 생존 rank를 하나씩 받으므로 앞 생존 rank들의 새 put은 가져오기보다 먼저 예비 프로세스의 window에 닿을 수 있다 `[소스]`. 그래도 데이터 복사에는 경합이 없다: 9.7절 3번(체크포인트에서 재실행 끝까지 다른 rank가 쓰는 window 자리는 한 번만 쓰임)에 따라 로그의 put(절단점과 hold 사이)과 게시 뒤의 새 put은 같은 자리를 쓰지 않는다. 로그의 put이 신호 낱말과 겹치면 계획이 거절하고, 새 신호 원자 연산이 로그의 데이터 자리에 닿지 않는 것은 계획의 겹침 거절과 단일 대입(9.7절 3번)에서 온다 `[추론]`(검토 d9e의 n6으로 근거를 고침; 처음에는 9.7절 9번을 들었음). 3번을 어기는 application(고리 버퍼)에서는 경합이 생기나, 그때는 재실행이 덮인 입력을 읽어 복원 자체가 틀리므로(v1 범위 밖) 복사의 차례로 더 나빠지지 않는다. 그래서 경합이 있는 window는 이 요구를 지키는 application에는 없다 `[추론]` | `rs_hold_api.h`, `rs_spare_api.h`(읽기만), EXPERIMENT.md 9.7절 |
| 2026-10-12 | (나) 빌드됨(rain, nice 19, ionice idle; 실행 안 함): 연구 `out/rs_d9e` libnccl `94a1251c13c92ada0478e841eeaf38c1`, 운영 `out/rsp_d9e` `5b0bdb2d8bdeec28eb93116e5c957591`, 경고 0 `[측정]`(바로 앞 `rs_d9d`, `rsp_d9d`는 새 snprintf 둘의 잘림 경고 둘이 있어 고쳐 다시 빌드함). 시험함: `rs_unit_dev: 13210756 checks, 0 failed` `[측정]`. 더한 시험: 지역 판정의 새 조건(이유와 번호), 계획 300개마다 신호 합 확인이 맞고 항목의 합과 같음, 조작한 계획(더하기 하나 +1, 대상 하나 빠짐, 대상 하나를 둘로 나눔, 대상을 다른 낱말로, 두 대상의 값 바꿈, 개수) 299개가 모두 거절됨. 루프백 원자 연산, RTS에서 RTS로의 접근 변경, 자기 시험, HCA의 바이트 차례는 GPU와 NIC 없이 시험할 수 없음 `[미확인]`. diff md5 `e4670656`(4 831줄), 다시 적용 확인 `[측정]` | 세션 스크래치 `build_rs_d9e.log`, `build_rsp_d9e.log`; [rs_unit_dev.cc](rs_unit_dev.cc) |
| 2026-10-12 | (나)의 독립 코드 검토(같은 에이전트, 이 변경만, 고정한 사본 `agent_rs_dev/review_d9e/`, diff md5 `e4670656`; 사본과 다시 적용, d9c 대비 바뀐 파일은 호스트 파일 하나, API 덩어리, `rs_d9e`와 `rsp_d9e`의 md5, 단위 시험 두 번 0 failed). 판정: 코드에 막는 문제 없음, (나)는 맞게 구현됨(verbs의 요청 칸, QP 속성, RTS에서 RTS로의 접근 변경, VA iova, 자기 시험의 바이트 차례 논리, outstanding 처리, 같은 HCA: 루프백과 GIN QP가 같은 ibv context, 문턱 `IBV_ATOMIC_HCA`, 차례, 잠금, fail-fast와 측정 모드는 새로 하는 일 없음). 바꾼 판 열 개: 대상별 비교 끔, 합만 비교, 개수 비교 끔, 조건이 0을 받음, 조건 뺌은 잡힘; 차례, 합, 남은 항목, 빈 대상 검사를 끈 넷은 살아남으나 검토자의 모형(무작위 2 000 000가지)에서 다른 검사에 이미 들어 있거나 값 0의 더하기만 다른 계획만 받음(메모리 결과 같음); GLOB(2)를 거절하는 판은 시험 빈틈 → GLOB 받음 시험을 더함. 고칠 것: (A1) 원자성 논증이 QP는 덮으나 등록은 덮지 않는다: 생존 rank의 신호 원자 연산은 GIN MR(`cComm->ib.pd`, 0 기준)로, 가져오기의 것은 루프백 PD에 다시 등록한 MR로 닿는다. 두 번째 등록이 GPU 페이지를 다른 PCIe/BAR1 주소로 매핑하면 HCA가 둘을 한 자리로 직렬화하는지 확인되지 않았다(9.6절의 두 번째 등록 BAR1도 `[미확인]`); 아니면 B1과 같은 결과(끝나지 않는 기다림) → 이 브랜치에서 고치지 않고 메인 세션의 결정으로 올림(지시한 설계를 바꾸는 것이라서), 권하는 길: 가져오기 전용 루프백 QP 한 쌍을 GIN PD에 만들고 생존 rank가 쓰는 바로 그 GIN MR(신호 표의 `signals_table->mr`, window의 `gdaki_mem_handle::mr`)의 rkey와 0 기준 오프셋으로 fetch-and-add(두 번째 등록이 없어짐, 자기 시험 실패가 hk의 복사 경로를 끄지 않음), 다른 길: pilot에서 생존 rank의 원자 연산과 루프백의 것을 한 낱말에 겹쳐 잃은 더하기를 셈(클러스터 실행); 복원 셀 전에 정해야 함; (S-img) 이미지를 쓰는 pageable `cudaMemcpy`가 DMA 전에 돌아올 수 있고, (나)에서는 생존 rank가 가져오기 전에 게시하므로 가져오기의 장치 동기화가 이미지를 그들의 쓰기보다 앞에 두지 못한다 → host 브랜치의 이미지 받기 끝에 동기화(통합 목록). 메모: (n1) GLOB 시험 → 더함; (n2) 자기 시험은 측 표의 MR만 씀(신호 표와 window의 원자 MR은 가져오기에서 처음 쓰임, 실패면 fallback); (n3) 자기 시험의 오류 완료는 복원을 요청한 모든 hold 프로세스의 NIC 복사 경로를 끔(기록함; A1의 길이면 없어짐); (n4) devComm 자원 window의 VA 신호는 원자 MR이 없어 가져오기가 거절(fallback; NCCL 자신의 헤더는 VA 신호를 만들지 않음) → 통합 목록; (n5) "데이터 먼저"의 까닭은 꼭 필요하지 않음(읽는 쪽이 아직 없음) → 차례는 그대로; (n6) 근거 인용 → 고침; (n7) 자기 시험이 값 불일치로 끝나면 fence 낱말이 0이 아닐 수 있음(해 없음) | 세션 스크래치 `review_d9e/`, `review_d9e_report.md`, `review_d9e_work/mut/` |
| 2026-10-12 | 검토 반영(d9e, 시험과 기록만): GLOB 받음 시험, 근거 인용, 통합 목록(A1, S-img, n4). 호스트 파일은 그대로(diff md5 `e4670656`). 시험함: `rs_unit_dev: 13240670 checks, 0 failed` `[측정]`. A1은 열림(메인 세션의 결정) | [rs_unit_dev.cc](rs_unit_dev.cc) |

**작업 묶음 4 다시 하기의 충돌 확인(2026-10-12, 코딩 전).**

1. 고리의 단위. 측 표는 GDAKI 문맥(`gdakiRecHost`)마다 하나이고 그 문맥의 모든 GPU 문맥이 같은 측 표를 가리킨다 `[소스: rs_layer.diff의 gdakiRsStart]`.
   복원은 communicator마다 투명 복구 GDAKI 문맥 하나를 요구하고 Resume의 지역 판정이 이미 거절한다(`nUserCtx != 1`: "the communicator has %d GDAKI
   contexts with transparent recovery, the restore needs one"; GIN 연결도 하나, `nConn != 1`) `[소스]`. 그래서 문맥마다 고리 하나는 복원할 수 있는
   communicator에서 rank마다 고리 하나다. 메인 세션이 검토에 넣으라고 한 확인("그 가정이 깨지면 Resume이 거절")은 이 두 조건이다.
2. 절단점(9.4절 2단계의 `L_q`)은 고리의 머리다. 입력 멈춤은 r로 가는 QP만 멈추므로 머리 아래에 다른 상대의 항목이 아직 쓰이는 중일 수 있다. 그래서 항목의
   첫 8바이트를 한 번의 쓰기로 둔다: 위치의 아래 32비트, QP 번호(24비트), 종류와 표시. 호스트는 이 낱말로 그 칸이 그 위치의 항목인지, 누구의 항목인지를
   본다. 정렬된 8바이트 쓰기는 NIC의 읽기에 찢어져 보이지 않는다고 본다 `[추론]`. 그 상대의 항목은 멈춤의 개수 0과 떠날 때의 release로 모두 다 쓰여
   있다(작업 묶음 4와 같은 근거).
3. 덮인 표시. 사용자 결정의 "항목 표시"는 호스트 메모리에 둔다: 칸마다 읽은 위치와 QP 번호, QP마다 확정 절단점. 항목의 위치가 그 QP의 절단점보다 작으면
   덮였다. 장치 메모리에 쓰지 않는 까닭: 장치는 그 표시를 읽지 않고, 항목마다 NIC 쓰기가 들며, 이웃 칸을 장치가 쓰는 중에 덮어쓸 수 있다.
4. 넘침. 원자 더하기로 자리를 잡으면 넘친 자리가 쓰이지 않은 채 남고, 호스트는 그 자리가 아직 쓰는 중인지 넘친 것인지 가를 수 없어 꼬리가 넘지 못한다.
   그래서 자리는 들어갈 때만 CAS로 잡는다(넘치면 자리를 쓰지 않음). 머리 아래의 모든 자리는 언젠가 쓰인다. 비용: 한 rank의 보내는 스레드가 머리 하나를
   두고 CAS를 다시 할 수 있다(경합) `[추론]`; pilot이 잰다. 넘침은 QP마다의 수(측 표 QP 항목, 넘친 길에서만 더함)로 호스트가 알고 그 상대를 DISARM한다
   (작업 묶음 6). 멈춤 때 넘친 수를 함께 적어 "확정 절단점 뒤로 잃은 것이 없음"을 판단한다(넘친 위치만으로는 멈춤 앞인지 뒤인지 가를 수 없음).
5. 고리 하나의 대가. 꼬리는 가장 오래된 덮이지 않은 항목에서 멈추므로 체크포인트가 늦거나 건너뛰는(BUSY) 상대 하나가 모든 상대의 고리를 채울 수 있고, 그러면
   다른 상대도 넘쳐 DISARM된다. 줄이는 길: 넘친 상대의 항목은 그 상대의 다음 입력 멈춤까지 덮인 것으로 친다(작업 묶음 6). 메모리는 상대 수가 아니라 체크포인트
   사이의 연산 수에 비례한다(사용자 요구). 한계로 적는다.
6. 항목 크기 64 B. 32 B에는 안 들어간다(window 번호 셋, 오프셋 둘, 크기, 값, checksum, 위치와 QP). 메시지 수 칸을 빼고 종류, 표시, 크기에서 같은 단위
   함수로 센다. 신호의 이름은 보낸 rank의 rkey 칸 주소 대신 window 번호(0은 문맥의 신호 표)로 장치가 적는다. 9.5절은 작업 묶음 9에서 helper가 바꾸기로
   했으나 칸이 모자라 앞당긴다. 그러려면 매크로 빌드의 API 특수화가 신호 window의 번호를 내부 인자로 하나 더 넘긴다.
7. 빌드 매크로(사용자 결정 (나)). `NCCL_GIN_RESTORE_DEVICE` 없이 빌드한 프로그램의 put, putValue, get은 hk의 본문 앞에 측 표 포인터 읽기와 비교, 분기,
   `__trap()`만 가진다. 내부 인자(신호 키 주소, 신호 window 번호)와 hold 함수는 매크로가 있을 때만 생긴다. NCCL 라이브러리는 매크로 없이 빌드되므로 그
   커널의 레지스터 수는 hk와 같아야 한다(기계어 비교로 확인). NCCL 안의 문맥은 측 표 포인터를 받지 않는다: `gdakiTsSetup`은 사용자 문맥
   (`ncclGinFaultUserCtx`)에서만 투명 복구를 켜고(gin_host_gdaki.cc 7219) 측 표는 투명 복구 문맥에만 생긴다 `[소스]`.
8. 매크로 없이 빌드한 프로그램이 복원을 요청한 프로세스에서 돌면 첫 GIN 연산에서 trap하고 그 CUDA 문맥은 끝난다. 틀린 복원(로그 없는 보내기)은 생기지 않는다.
   라이브러리는 프로그램이 매크로로 빌드됐는지 알 길이 없다(Resume이 미리 거절할 수 없음). 그래서 `nccl.h`와 장치 헤더의 주석에 적고, 7절 회귀 셀의 hold 행
   (복원 요청, Resume 없음)은 매크로로 빌드한 드라이버를 써야 한다(test 브랜치에 넘김).
9. 한 장치 link 단위의 모든 번역 단위는 매크로가 같아야 한다: API 특수화의 멤버 함수가 매크로로 달라지는 inline 함수다(ODR). 주석에 적는다.
10. 억제 예산, get 거절 표시, 메시지 수는 QP마다 그대로다(측 표 QP 항목). 9.4절의 drain 기다림과 9.6절의 예산 단위는 바뀌지 않는다.
11. 재기만 하는 변수(`NCCL_GIN_RESTORE_LOG_MEASURE`): helper가 고리 하나의 꼬리를 머리로 옮기고 사용량(머리 − 꼬리)을 표본으로 적는다. 꼬리 옮김 사이 늦게
    쓰는 보내기는 작업 묶음 4와 같은 까닭으로 해가 없다.
12. `ncclGinRestoreStep`의 확정 단계: 단계마다 QP마다의 머리가 아니라 고리의 머리 하나를 적는다(9.4절의 셈은 같음; 몸체는 host 브랜치의 작업 묶음 5).
13. 소유(PARALLEL.md). 장치 헤더 둘은 이 브랜치의 것이다. 호스트 파일에서 바꾸는 것: 측 표 배치 함수, 측 표 설정의 고리 부분, 문맥 끝의 읽어 내기, 재기만
    하는 모드의 helper 걸음(모두 로그), `gdakiRecHost`의 rs 칸 묶음(공용 구조체의 줄이라 통합에서 줄 충돌이 날 수 있음). host 브랜치는 rs_log_api.h만 보고,
    spare 브랜치의 rkey 목록은 같은 window 번호(`rsWinId`)를 쓴다. `NCCL_GIN_RESTORE_LOG_ENTRIES`는 QP마다가 아니라 rank마다의 항목 수가 된다(기본 4 096은
    pilot의 자리값).

**통합에서 할 일(작업 묶음 4 다시 하기에서 생김).**

- `nccl.h.in`(host 브랜치와 같이 쓰는 파일)의 Resume 주석 끝 문장 "This build has no hold reaction yet: the communicator stays fail-fast"를 고칠 것.
  매크로 없이 빌드한 프로그램은 복원을 요청한 프로세스(`NCCL_GIN_FAULT_POLICY=hold`, `NCCL_GIN_RESTORE` ≠ 0, 예비 프로세스)에서 첫 put, putValue,
  get에서 trap한다(Resume을 부르든 말든). 넣을 문장의 안: "A program that runs in a process that asks for the restore must be compiled with
  -DNCCL_GIN_RESTORE_DEVICE (every translation unit of one device link unit alike); compiled without it, its first GIN put, putValue or get traps there,
  whether or not it calls ncclGinRestoreResume. NCCL's own kernels are built without it and never see the side table." 9.10.4절의 "Resume을 부르지 않는
  communicator는 fail-fast"도 같은 단서가 필요하다(장치 코드의 빌드 꼴은 프로세스의 변수를 따라야 함).
- test 브랜치: 드라이버를 빌드할 때 매크로를 셀마다 정하고 셀 이름에 적을 것(복원 셀과 회귀의 hold 행은 매크로 있음, fail-fast 비용 `lat_ff_branch`는
  매크로 없음과 있음 둘 다 재면 사용자 결정 (나)의 값을 잼).
- 이 브랜치가 바꾼 호스트 코드 가운데 dev 구역 표시 밖의 것(소유는 이 브랜치): `gdakiRecHost`의 rs 칸 묶음(`rsNqp`, `rsLogged`, `rsEntries`,
  `rsMeasure*`, `rsOcc*`), `gdakiRsStart`의 측 표와 고리 부분, `gdakiRsReadSide`, `gdakiRsMeasureStep`, `gdakiRsTeardownLine`, 공용 순수 구역의
  `gdakiRsSideLayoutOf`, `gdakiRsSumsOf`.
- 사용자 확인 대기: 위 검토 행 (3)의 남은 차이를 사용자 결정 (나)의 "hk와 같은 레지스터 수"로 받아들일지. → 풀림(2026-10-12): 사용자 방향이 trap을 없앴고, 남은 SASS 차이는 오래된 hk 객체에서 온 것이었다(위 "다른 22개의 까닭" 행).

**작업 묶음 6의 충돌 확인(2026-10-12, 호스트 파일에 넣기 전).**

1. 부르는 쪽(host 브랜치, 읽기만): 멈춤에서 `gdakiRsLogPauseRead`, CKPT_STABLE에서 `gdakiRsLogStable`, helper 걸음에서 10 ms마다 `gdakiRsLogPoll`(돌려준 상대를
   모두 DISARM), Step의 `gdakiRsLogReadHeadApp`과 `gdakiRsLogCoveredUpTo`, 멈춤 응답의 BUSY에 `gdakiRsLogReadSuppress`, 복원의 내보내기 `gdakiRsLogExport`.
   모두 helper 스레드(NIC 복사 경로는 한 번에 한 사용자, 9.11.4절 T5)이고 `ReadHeadApp`만 application 스레드(그 스레드는 단계 hook에서 CUDA를 부를 수 있음,
   9.4절)라 겹치지 않는다. 훑기는 그 걸음에서만 부른다(메인 세션의 요청: 다른 곳에서 부르지 않음).
2. 내보내기의 `from`: host 브랜치는 확정을 받지 못한 체크포인트의 절단점으로도 내보낸다(그 rank가 확인한 멈춤마다 절단점을 지킴, `rs_ckpt_api.h`). 그
   위치는 이 rank의 확정 절단점 이상이고 그 사이의 상대 항목은 덮이지 않아 고리에 남는다. 그래서 모으기와 내보내기는 "지킨 절단점 이상의 어느 위치에서든"
   받고, 그 뒤로 잃은 것(넘친 수)과 get(get 수)이 없는지를 지금 읽은 값으로 본다.
3. 넘침(9.5절 "넘친 통로의 상대는 다음 확정 체크포인트까지 ARMED 아님"): 그 상대를 훑기가 돌려주고 host가 DISARM한다(누가 넘친 수를 먼저 읽든;
   검토 지적 1로 고침). 확정 때 찾으면 `gdakiRsLogStable`이 거절해 host가 무장하지 않는다(검토 지적 2). 로그 쪽은 그 상대의 항목을 다음
   멈춤까지 덮인 것으로 쳐 꼬리를 막지 않는다(고리 하나라 다른 상대를 지키려고). 마지막 멈춤 뒤로 잃은 것이 없으면 그 멈춤부터 다시 지킨다(그 체크포인트가
   확정되면 바로 쓸 수 있음).
4. get 규칙(9.7절 8번, 9.10.4절): 생존 rank가 상대에게 get을 내면 그 상대를 DISARM. 장치의 QP마다 get 수(작업 묶음 4 다시 하기)를 확정 절단점의 멈춤 때 값과
   견준다. 같은 절단점에서 한 번만 돌려준다.
5. 두 번째 사용자 투명 복구 문맥(메인 세션의 요청): 훑기가 이 communicator의 설정 결정 수(Resume이 센 것과 같은 등록부)를 보고 둘 이상이면 모든 상대를 한 번
   돌려준다(한 번의 DISARM; 그 뒤 무장을 막는 것은 host 브랜치의 communicator 검사 `gdakiHoldCommCheck`).
6. 멈춤의 logOn: 멈춤 안(게이트 홀수, 개수 0)에서 NIC으로 쓰고(쓰기 뒤의 READ가 닿음을 보장) 측 표를 다시 읽어 1인지 본다. 짝수 에폭을 내기 전이라 로그의
   시작이 절단점과 같다(9.11.9절 C2).
7. 확정의 덮기와 꼬리 쓰기: 꼬리는 늘기만 하고 helper만 쓴다. 장치는 시스템 범위로 읽는다(작업 묶음 4). 쓰기가 실패하면 호스트의 꼬리도 그대로 둔다(다음에
   다시).
8. 덮인 위치(Step의 확정 단계): 꼬리와 로그하는 QP의 가장 낮은 절단점 가운데 큰 것. 로그하지 않는 QP와 모두 덮인 QP는 막지 않는다(9.4절의 셈과 같음).
9. 재기만 하는 모드(`NCCL_GIN_RESTORE_LOG_MEASURE`): 로그 상태를 만들지 않는다(그 모드는 helper가 꼬리를 옮기고 Resume이 거절함). 두 모드가 같은 꼬리를
   쓰지 않는다.
10. 예비 프로세스도 복원을 요청하므로 측 표와 고리, 로그 상태를 가진다. 그 rank의 로그는 RESTORED 뒤 helper가 돌 때 같은 규칙으로 쓰인다.
11. fail-fast: 측 표가 없어 로그 상태도 없고, 새로 부르는 곳(문맥의 해제, 끝 줄)은 포인터가 null이면 돌아간다. 호스트의 fail-fast 동작은 hk와 같다
    `[소스]`.
12. 소유: 선언 덩어리(앞쪽), 순수 구역, 호스트 구역은 dev 표시 안. 측 표 설정(`gdakiRsStart`)의 한 줄, `gdakiRecFree`의 한 줄, `gdakiRecHost`의 칸 하나,
    문맥 끝 줄은 이 브랜치의 앞 코드 자리다. host 브랜치의 자리 표시(placeholder) 덩어리는 통합에서 지운다(그 덩어리가 남으면 정의가 겹쳐 컴파일되지 않음).
    작업 묶음 9가 끝나기 전에 통합한다면 아직 정의하지 않은 함수(`gdakiRsExecRead`, `gdakiRsPlanAllExecuted`, `gdakiRsLogExport`)의 자리 표시는 남긴다.
- (작업 묶음 6) host 브랜치의 "integration placeholders, dev branch" 덩어리: 이 브랜치가 정의한 함수의 자리 표시는 지우고, 작업 묶음 9 전이면
  `gdakiRsExecRead`, `gdakiRsPlanAllExecuted`, `gdakiRsLogExport`의 것은 남긴다(작업 묶음 9 뒤에는 덩어리 전체를 지움). `gdakiRsLogStable`은 끊김이면
  ncclInvalidUsage를 돌려준다: host의 OnStable이 그 경우 무장하지 않는 것을 이미 함 `[소스: rs_layer_host.diff]`.

**trap 없는 빌드 선택의 충돌 확인(2026-10-12, 코딩 전; 사용자 방향과 메인 세션의 확인은 위 행).**

1. 포인터의 자리: 분류 블록 끝(`ncclGinGdakiQ4::restore`). 투명 복구는 분류를 요구하므로 측 표가 있는 문맥에는 늘 블록이 있다. 블록은 `ncclCudaCalloc`이라
   처음에는 0이고, 장치 코드는 블록의 크기를 쓰지 않으며(장치 헤더를 grep) 다른 칸의 자리는 그대로다 `[소스]`. GPU 문맥은 hk의 배치와 간격 그대로다.
2. 게시: Resume이 성공한 뒤(교환으로 모든 rank가 같은 결론) 그 rank가 자기 블록에 8바이트 하나를 동기로 씀(자기 stream, 문맥의 장치). application 스레드이고
   첫 실행 전이다(nccl.h의 요구; 그때 도는 커널은 포인터를 중간에 읽을 수 있음, 문서). 게시가 실패한 rank는 WARN을 내고 그 rank의 입력 멈춤이 거절해
   (`gdakiRsLogPauseRead`, BUSY) 어느 상대도 그 rank의 로그에 기대어 무장되지 않는다.
3. 측정 모드: 문맥을 만들 때(application 스레드, 생성 안) 게시. 그 communicator의 Resume은 여전히 거절. `..._MEASURE_LOG=0`은 QP의 logOn을 0으로 둔다.
4. nccl.h의 래퍼: `static inline`이 매크로를 헤더를 읽는 때 본다. 그래서 매크로는 명령줄에서(헤더 앞) 정의해야 하고, 한 프로그램 안에서 번역 단위를 섞으면
   매크로 없는 커널이 로그 밖으로 보낼 수 있다(지원하지 않음, 문서). 라이브러리의 입구는 `ncclGinRestoreResumeBuilt`(공개 기호가 바뀜: 이 헤더로 다시 빌드한
   프로그램만 지원, 작업 묶음 3의 규칙과 같음).
5. Resume 지역 판정의 새 조건은 고정 차례의 맨 끝에 둔다(앞 조건의 번호와 시험이 그대로). host 브랜치의 작업 묶음 5도 이 함수에 조건을 더했으므로 통합에서
   같은 자리의 줄이 만날 수 있다(아래 통합 목록).
6. 공유 파일의 최소 줄: `gin/gin_host.cc`(입구 이름과 깃발 한 줄, 주석), `include/gin/gin_host.h`(사실 칸 하나), `nccl.h.in`(새 선언, 래퍼, 주석 둘),
   호스트 파일의 Resume(사실 → 판정 한 줄, 조건 한 줄, 게시 두 줄). 측 표 설정(`gdakiRsStart`)과 장치 헤더 둘은 이 브랜치의 것.
7. 결정 (나)(키 다시 읽기, 2026-10-09)와 상태 기계: 게시 전에는 hold 프로세스도 hk의 보내기 길(키를 게이트 앞에서 읽음)이고, 게시 뒤에 hold 갈래가 된다.
   무장은 Resume이 성공한 뒤에만 되므로(host 브랜치) 붙잡을 수 있는 상대의 보내기는 늘 hold 갈래다 `[추론]`.
8. 예비 프로세스의 Resume도 성공하면 같은 게시를 지나야 한다(spare 브랜치의 Resume 길; 통합 확인 항목).
9. 무장 전 hold의 비용(7절 `cost_unarmed`): 앞에는 문맥을 만든 때부터 들었으나 이제 Resume 성공 뒤부터다. 비용 셀은 측정 모드의 `..._LOG=0`으로 잰다.
10. 7절의 회귀 셀: 매크로 없는 드라이버는 hk와 같은 장치 코드라 회귀가 그 자체로 hk다. hold 행(복원 요청, Resume 없음)은 매크로와 상관없이 게시가 없어 hk의
    보내기 길을 지난다.
11. 기계어: 매크로 없는 프로그램과 라이브러리는 hk와 바이트까지 같아야 한다(잼, 아래 행). 창 handle 끝의 칸 둘(`rsWinId`는 hk의 틈, `rsBase`는 끝에 더함)과
    함께 쓰는 헤더의 inline 함수는 장치 명령을 바꾸지 않아야 한다(같은 측정이 확인함).
12. 매크로 빌드의 비용: `fault` 읽기(hk가 게이트 근처에서 이미 읽음), `fault->restore` 읽기, 비교와 분기, hold 함수의 호출 덩어리.

**통합 목록에 더함(trap 없는 빌드 선택).**

- `nccl.h.in`: `ncclGinRestoreResume` 선언을 `ncclGinRestoreResumeBuilt`(+ `pncclGinRestoreResumeBuilt`)와 static inline 래퍼, `NCCL_GIN_RESTORE_DEVICE_BUILT`로
  바꿈. Resume 주석의 "This build has no hold reaction yet: the communicator stays fail-fast" 문장을 "Until it succeeds the side table is not given to the
  device ..."로 바꿈(앞서 제안한 trap 문장은 쓰지 않음; trap이 없어짐). 빌드 선택 주석 한 덩어리.
- `gin/gin_host.cc`: `NCCL_API(... ncclGinRestoreResume ...)`과 정의의 이름을 `ncclGinRestoreResumeBuilt`로, 인자 `int deviceBuilt`, `f.deviceBuilt = ...` 한 줄.
- `include/gin/gin_host.h`: `ncclGinRestoreCommFacts` 끝에 `int deviceBuilt`.
- 호스트 파일의 Resume(공유 구역): `gdakiRsLocalIn` 끝의 `deviceBuilt`, `gdakiRsLocalCheck`의 맨 끝 조건 한 줄(이유 "program not built with
  NCCL_GIN_RESTORE_DEVICE ..."), `in.deviceBuilt = f->deviceBuilt != 0;` 한 줄, 판정 바로 뒤의 게시 두 줄(`gdakiRsPublishFor`). 측 표 설정에서 포인터를 쓰던
  (3) 걸음은 없앰(측정 모드의 게시 세 줄로 바꿈).
- 예비 프로세스의 Resume이 성공할 때도 판정 뒤의 게시 줄을 지나는지 확인(spare 브랜치).
- (d4f 검토) test 브랜치: `ncclGinRestoreResume`과 `pncclGinRestoreResume`이 라이브러리 기호에서 빠지고 `...Built`가 됨. 드라이버와 profiler shim은 이 nccl.h로 다시 빌드한다.
- (d4f 검토) host 브랜치: drain 확인이 "count went wrong"으로 체크포인트를 버릴 때 이유에 섞인 빌드(Resume 단위에만 매크로)를 가능한 까닭으로 적을 것. OnStable이 `gdakiRsLogStable`의 끊김 거절에 "could not be trimmed"라 적는 글(꼬리는 옮겨졌음)을 끊김으로 고칠 것.
- (d4f 검토, 제안) 게시가 실패한 rank는 WARN만 낸다. `ncclGetLastError(comm)`에 그 줄을 남길지 정할 것.
- 호스트 파일 Resume 공유 구역: 성공 줄의 "the communicator stays fail-fast"를 "a fault still fails fast"로 바꿈(host 브랜치가 반응을 넣으면 같은 줄이 만남).
- 오래된 hk 기준 객체: 이 연구의 앞 작업 묶음(3, 4)에서 hk 빌드 트리의 객체와 견준 라이브러리 SASS 기록이 있으면 같은 까닭으로 다시 볼 것 `[미확인]`.

**작업 묶음 9의 충돌 확인(2026-10-12, 호스트 파일에 넣기 전).**

1. 부르는 쪽(host 브랜치, 읽기만). `gdakiRsExecRead`: 입력 멈춤(P), hold 시작(2ERR 뒤의 X, M, 머리), Commit 전(X가 그대로인지), 확정 확인의 고리(모든
   rank). 모두 helper이고 opMu를 잡지 않은 자리다(`gdakiTsQuiesce`는 안에서 잡고 놓음) `[소스: rs_layer_host.diff]`. ExecRead는 watch의 QUERY_QP처럼
   opMu를 잡으므로, 부르는 쪽이 잡고 있으면 교착이다(API 주석에 적음). `gdakiRsPlanAllExecuted`: 복원 round의 Commit 전(hk가 계획을 Commit 전에
   검사하듯). `gdakiTsRepostApply`는 n = 0 계획이면 아무것도 다시 내지 않고 U만큼 논리 기준을 옮긴다 `[소스]`. `gdakiRsLogExport`: STATE를 보낼 때
   helper가 이 rank가 확인한 그 체크포인트의 멈춤 머리, hold 시작의 머리와 X, M을 준다. 바이트 수를 먼저 보내므로 벡터에 모은다. 실패면 STATE를
   보내지 않고 fallback한다. 그래서 "source buffer changed"는 끝까지 쓴 스트림과 함께 ncclInvalidUsage로 돌려준다. `gdakiRsSpareImport`: 예비 프로세스의
   Resume 안, application 스레드, 커널과 helper 전.
2. 연결(공유 코드라 이 브랜치가 고치지 않음): G7의 hold 본문(`gdakiPolicyObserveRmsn`), `gdakiTsExecuted`, `gdakiTsBaseline`. 로그 상태가 없는
   프로세스(fail-fast 포함)에서는 세 함수가 바로 돌아가므로 hk의 호스트 동작은 함수 호출 하나 말고 같다. 설정의 rmsn0 기준선은 로그 상태를 만들 때
   `ts->qs[i].rmsn0`에서 받는다(`gdakiTsSetup`이 `gdakiTsStart`보다 먼저) `[소스]`.
3. 잠금 차례. 내보내기: `gdakiRsWinMu` → `lb->mrsMu`(`gdakiLbFind`). 가져오기: `gdakiRsWinMu` → `appMu` → `execMu`. SuppressSet: `appMu` → `execMu`.
   억제 줄: `execMu`만. 파일 안에 거꾸로 잡는 곳은 없다: Resume은 `gdakiRsWinMu`를 놓은 뒤 `gdakiRecRegMu` → `mrsMu`를 잡는다 `[소스]`.
4. `gdakiRsWinMu`를 잡은 채 NIC으로 읽는다(덩어리 하나, 1 MiB 이하). 가져오기는 그 전체 동안 잡는다. 그 사이 같은 프로세스의 window 등록과 해제가
   기다린다. 해제가 기다리는 것은 의도다(읽는 동안 그 메모리가 풀리지 않음).
5. NIC 복사 경로는 helper 한 사용자 규칙 그대로다: 내보내기만 쓴다. 가져오기와 SuppressSet은 예비 프로세스의 application 스레드에서 CUDA 복사를 쓴다
   (helper 전).
6. `gdakiRsStart`가 window의 데이터 범위를 루프백 MR에 더한다(할당마다 MR 하나 더). 실패하면 `rsLbOk`가 거짓이 되어 Resume이 거절한다. 앞에는 rkey
   표만 넣었으므로 거절 조건이 조금 넓어진다. fail-fast 프로세스는 이 함수에서 바로 돌아간다(hk와 같음). 문맥 뒤에 등록한 window는 Resume이 이미
   거절하고(`winsAfter`) `[소스]`, devComm의 자원 window가 put의 출처가 되면 그 읽기가 실패해 내보내기가 거절한다(fallback).
7. 순수 상태가 바뀐다: 멈춤마다 QP의 M을 절단점부터 1024개까지 지킨다. `gdakiRsLogStateNotePause`의 인자가 하나 는다(부르는 곳은 PauseRead와 단위
   시험뿐). 절단점 멈춤의 M을 지키지 못했으면 내보내기가 거절한다(틀린 데이터 대신 fallback).
8. 억제 줄: WARN, 예비 프로세스에서 가져오기가 예산을 둔 QP마다 한 번(B = 0 포함). gpu-detect 채점 문구 넷(`noScorerPhrase`)과 겹치지 않는다. window MR
   줄은 그대로다. 형식은 test 브랜치에 공개한 그대로이고 qp가 측 표의 QP 번호(문맥 × nranks + 상대)라는 것만 덧붙인다.
9. helper 소켓 메시지 번호(21..31)는 쓰지 않는다. 내보내기는 host 브랜치의 data socket STATE에 실린다.
10. nonce: 가져오기는 내보낸 쪽의 nonce를 이 문맥의 `ts->nonce`와 견준다. 예비 프로세스의 문맥이 생존 rank와 같은 nonce를 가져야 한다(spare 브랜치의
    REJOIN; 통합 확인). 다르면 모든 가져오기가 거절한다(fallback, 틀린 적용 없음).
11. 신호: hold 길의 신호는 모두 더하기다(Inc는 1로 풀림) `[소스: 장치 헤더]`. 가져오기는 데이터를 먼저, 신호를 나중에 더한다. put의 대상이 신호 낱말과
    겹치면 차례가 결과를 바꾸므로 거절한다(single assignment, 9.7절 3번).
12. 장치 코드는 바뀌지 않는다. 그래서 매크로 없는 꼴이 hk와 같다는 측정은 그대로다(장치 헤더 diff 없음으로 확인).
13. 예비 프로세스의 msgs = X: 그 뒤 체크포인트의 P와 M 셈(9.4절)이 생존 쪽과 이어진다 `[추론]`.
14. host 브랜치의 자리 표시(`gdakiRsExecRead`, `gdakiRsPlanAllExecuted`, `gdakiRsLogExport`)와 이 브랜치의 `gdakiCkptPeerP` 대용 정의
    (`#ifndef GDAKI_CKPT_MAGIC`, host 브랜치의 공유 글이 그 정의를 앞에 둠)는 통합에서 지운다.

**통합 목록에 더함(작업 묶음 9).**

- 연결(공유 코드, 이 브랜치가 고치지 않음): G7의 hold 본문(`gdakiPolicyObserveRmsn`)에서 `gdakiRsExecObserve(r, qpIdx, rmsn)`; `gdakiTsExecuted`가
  읽은 rmsn마다 `gdakiRsExecObserve(r, rq.qpIdx, rmsn)`; `gdakiTsBaseline`이 rmsn0를 둘 때 `gdakiRsExecRebase(r, rq.qpIdx, rmsn)`. 로그 상태가 없는
  프로세스(fail-fast 포함)에서는 셋 다 바로 돌아간다.
- host 브랜치의 "integration placeholders, dev branch" 덩어리는 통째로 지운다(이제 모든 함수가 이 브랜치에 정의됨). 이 브랜치의 `gdakiCkptPeerP` 대용
  정의(`#ifndef GDAKI_CKPT_MAGIC`)도 지운다: host 브랜치의 공유 글(`rs_ckpt_api.h`)이 이 구역보다 앞에 와야 한다.
- `gdakiRsExecRead`는 watch처럼 opMu를 잡는다: 부르는 쪽이 opMu를 잡고 있으면 안 된다(host 브랜치의 네 자리는 잡지 않음).
- spare 브랜치: 예비 프로세스 GIN 문맥의 nonce가 생존 rank와 같아야 가져오기가 받는다(`hdr.nonce == ts->nonce`). 예비 프로세스의 Resume 안에서
  이미지를 쓴 뒤, 커널과 helper 전에 `gdakiRsSpareImport`를 부르고, 거절이면 복원을 fallback한다.
- host 브랜치: `gdakiRsLogExport`가 ncclInvalidUsage(출처가 바뀜, 로그가 온전하지 않음)나 ncclSystemError면 STATE를 보내지 않는다(이미 그렇게 함).
- test 브랜치: 억제 줄 형식은 공개한 그대로이고 qp는 측 표의 QP 번호(문맥 × nranks + 상대)다. 예산이 0인 QP도 한 줄을 낸다.
- **(B1, 2026-10-12 결정됨: (나), 이 브랜치에서 구현함, 위 행)** 가져오기의 신호 더하기는 호스트의 읽고 더하고 쓰기였다. 그 사이 어느 생존 rank도 이 프로세스로 게시하지 않았어야 한다. spare
  브랜치의 한 번에 하나 차례는 이를 어긴다. 고를 길: (가) 모든 생존 rank의 REJOIN과 STATE를 먼저 받고 가져오기를 한 뒤 TOKEN, READY, Commit을 차례로
  (spare 브랜치의 driver를 바꿈); (나) 신호 더하기를 루프백 QP의 원자 fetch-and-add로(같은 HCA의 원자끼리는 원자적; 신호 표와 VA 신호 window의 루프백
  MR에 REMOTE_ATOMIC, 루프백 QP의 원자 속성: gin-remaining의 공유 코드를 바꿈, 복원을 요청한 프로세스에서만; HCA의 `atomic_cap`이 `IBV_ATOMIC_HCA`
  이상인지 설정에서 보고 아니면 거절). 결정 전에는 통합하지 않는다.
- (d4) host 브랜치: 예비 프로세스가 이미지를 쓰는 `cudaMemcpy`도 문맥의 장치를 고른 뒤에 하거나, 끝에 스스로 동기화한다(가져오기의 동기화는 문맥의
  장치만 덮음).
- ((나), 함께 쓰는 구역) 공용 순수 구역: `#define GDAKI_RS_ATOMIC_HCA 1`과 `gdakiRsLocalIn::atomicCap`(기본 `GDAKI_RS_ATOMIC_HCA`), 지역 판정 맨 끝
  조건 "the HCA's atomic capability is below IBV_ATOMIC_HCA (atomic_cap %d)". Resume: `in.atomicCap = (int)rFound->ctx->ib_dev_attr.atomic_cap;` 한 줄.
  host 브랜치의 Resume 조건과 같은 자리에서 만날 수 있다.
- ((나)) 가져오기 동안 NIC 복사 경로의 사용자는 예비 프로세스의 application 스레드 하나여야 한다(spare 브랜치의 driver가 같은 스레드에서 부름, helper 전).
- ((나)) 루프백 QP의 원자 자기 시험이 오류 완료로 끝나면 그 문맥의 NIC 복사 경로가 꺼진다(복원을 요청한 프로세스에서만; 그 뒤 hk의 복사는 stream). 원자 MR은
  NIC 복사 경로의 목록에 들어가 경로와 함께 풀린다.
- **((나), A1, 복원 셀 전에 결정)** 가져오기의 원자 연산은 루프백 PD에 다시 등록한 MR로, 생존 rank의 것은 GIN MR로 닿는다. 두 등록이 같은 GPU 메모리를 다른
  버스 주소로 매핑하면 HCA의 원자 직렬화가 둘을 한 자리로 보는지 `[미확인]`. 권하는 길: 가져오기 전용 루프백 QP 한 쌍을 GIN PD(`cComm->ib.pd`)에 만들고 생존
  rank가 쓰는 GIN MR(`signals_table->mr`, window의 `gdaki_mem_handle::mr`)의 rkey와 0 기준 오프셋으로 fetch-and-add. 다른 길: pilot에서 잃은 더하기를 잼.
- ((나), S-img) host 브랜치: 예비 프로세스의 이미지 받기(`gdakiCkptSpareFetch`) 끝에 장치 동기화. (나)에서는 생존 rank가 가져오기보다 먼저 게시하므로, 늦은
  이미지 DMA가 생존 rank의 새 put이나 신호를 덮지 않게 하려면 첫 STATE에 답하기 전에 이미지가 닿아 있어야 한다.
- ((나), n4) devComm 자원 window에 VA 신호를 두는 application은 복원되지 않는다(그 window는 문맥 뒤에 등록되어 원자 MR이 없음, 가져오기가 거절).
- ((나), pilot) 새로 확인할 것: 루프백 QP의 RTS에서 RTS로의 원자 접근 변경과 자기 시험이 통과하는지(GIN 설정 줄 `restore_buffers_in_nic_path=1`), 가져오기
  줄의 `signal_sum`, 생존 rank가 게시한 뒤 가져오기가 더한 신호의 값.
- (S2) host 브랜치: `gdakiRsLogExport`에 체크포인트(`a.round`)를, 예비 프로세스의 `gdakiRsSpareImport`에 복원한 체크포인트(`hdr[0].ckpt`)를 넘긴다.
- (S4) 실행 수의 연결 셋(위)은 복원 셀 전에 막는 조건이다. `gdakiTsBaseline`이 Commit 뒤에 실패하면 그 QP들에 `gdakiRsExecInvalidate`를 부른다. host 브랜치
  제안: 체크포인트를 받는 rank가 PAUSED의 P_q를 자기의 q 쪽 msgs와 견준다(9.7절 7번으로 같아야 함).
- (S3) 9.6절의 "출처 읽기 오류가 NIC 복사 경로를 끄지 않음"은 지킬 수 없다: 오류 완료 뒤 루프백 QP는 이미 ERR이다. 미리 하는 검사(등록부, 범위, MR 찾기)는
  끄지 않고 거절한다. 오류 완료가 나면 경로가 꺼지고 그 복원은 fallback이다(12절의 어긋남 기록).
- (N2) 예비 프로세스의 helper가 `gdakiRsLogReadGetRefused`를 읽어 get 거절이면 fallback한다(9.11.3절 M2 (c)): 부르는 자리를 정할 것.
- (N7) application 규칙: put의 출처 window는 그 GIN 문맥의 communicator에 등록한 것이어야 한다(내보내기는 그 communicator의 window 번호로 찾음).
- (N9) 예비 프로세스: QP를 RTR/RTS로 이은 뒤 `gdakiRsExecRebase`로 실행 수의 `last`를 이은 QP의 MSN으로 둔다.
- (N6) 복원을 요청한 프로세스는 문맥을 만들 때 모든 window를 루프백 PD에 한 번 더 등록한다(시간; BAR1은 `[미확인]`). 해제한 window의 MR은 문맥 끝까지
  남는다(내보내기는 등록부의 해제 표시를 봄).

## 이 연구 밖의 사실

메인 세션의 요청(2026-10-12)으로 적는 사실뿐이다. 어느 연구의 결과에 영향이 있었는지는 해석하지 않는다(메인 세션이 셀의 로그로 따로 확인함).
모두 rain의 세션 스크래치에서 읽었고 GPU와 클러스터에서는 아무것도 돌리지 않았다.

- **오래된 객체 22개**: `build/obj/device/genobj/symmetric/` 아래 `all_gather_gin.cu.o`, `all_gather_gin_profile.cu.o`,
  `reduce_scatter_gin_{avg,sum}_{bf16,f16,f32}.cu.o`와 그 `_profile.cu.o`(12개),
  `reduce_scatter_gin_{avg,sum}_{f8e4m3,f8e5m2}_RailA2A_LsaLDMC.cu.o`와 그 `_profile.cu.o`(8개). 목록 파일: 세션 스크래치
  `agent_rs_dev/samelen2/list.txt`.
- **객체의 시각**: 2026-10-09 01:02:12–01:03:20(객체마다: 가장 이른 것 `reduce_scatter_gin_avg_f8e5m2_RailA2A_LsaLDMC.cu.o` 01:02:12, 가장 늦은
  것 `reduce_scatter_gin_sum_f16_profile.cu.o` 01:03:20). 같은 시각의 같은 객체가 빌드 트리 `agent_ts2hd`, `agent_ts2hf`, `agent_ts2hq`,
  `agent_ts2hr`, `agent_gd/gin`(hw), `agent_gd/gin_hk`(hk)에 있다(트리 복사로 옮겨진 것으로 보임 `[추론]`) `[측정: stat]`.
- **이 객체가 앞선 장치 헤더 바뀜**:
  - hd: `src/include/nccl_device/gin/gdaki/gin_gdaki.h`(+31줄)와 `gin_gdaki_device_host_common.h`(+3, −1). `agent_ts2hd`에서 두 파일의 수정 시각은
    2026-10-09 01:44:49이고, 커밋은 `4965c2a` "gin-harden hd (libnccl e2090323)" 2026-10-09 04:02:31이다. hd의 다른 장치 헤더 바뀜(`impl/gin__funcs.h`
    00:36:42, `utility.h` 00:36:28)은 객체보다 앞이다.
  - hq: 같은 두 파일. `agent_ts2hq`의 수정 시각은 07:41:12와 07:41:41, 커밋은 `7b7d12f` "gin-peer hq (libnccl c1311625)" 12:44:30.
  - hr: 같은 두 파일. 수정 시각은 12:56:46과 13:28:24, 커밋은 `382bbb4` "gin-remaining hr (libnccl 2dee2b5b)" 16:24:54.
  - gpu-detect hw(`acd1fcd`, 20:47:56)는 장치 헤더를 바꾸지 않았다(`git show --stat`).
- **이 객체를 담은 라이브러리**(세션 스크래치에 기록된 빌드 출력): hd `e2090323`, hdp `4818e30b`, hf `b6372d86`, hfp `1ae4ce9a`, hq `c1311625`, hqp
  `4fa076e1`, hr `2dee2b5b`, hrp `786f70bc`, hw `efc48ca1`, hwp `d3b4a2fe`, hk `2913c777`, hkp `84209c03`.
  - 확인한 방법: 커널 둘(`ncclSymkDevKernel_AllGather_RailRing_LsaSTMC`, `ncclSymkDevKernel_ReduceScatter_RailA2A_LsaLD_sum_f16`)의 명령과 인코딩
    두 낱말(오프셋을 뺀 `cuobjdump -sass -fun`)이 12개 라이브러리와 01:02–01:03 객체에서 모두 같다(md5 `3973e971`, `aeac90ac`) `[측정]`.
  - hk 트리를 오늘 다시 컴파일한 커널은 다르다: AllGather sm_75 34 128 → 35 040 명령, sm_86 34 432 → 35 352; ReduceScatter sm_75 52 856 → 53 784, sm_86
    53 192 → 54 072 `[측정]`.
  - 확인하지 않은 것: 각 라이브러리에서 나머지 20개 객체의 커널(같은 시각의 같은 객체 파일이라 같다고 봄 `[추론]`); ow `b4af65c5`, pcm `cd72f67a`,
    stock `b380e622`(코드가 다름; ow 트리의 객체 시각은 2026-09-24 12:00:00이고, 그 트리의 헤더와 견주어 오래됐는지는 보지 않음); 노드에 배포된
    사본이 이 md5와 같은지(클러스터 접근 없음).
- **근거 경로**(세션 스크래치): `agent_gd/out/*/`, `agent_ts2h{d,f,q,r}/out/*/`, 각 트리의 `build/obj/device/genobj/symmetric/`,
  `agent_rs_dev/samelen2/`(오늘 hk 트리에서 다시 컴파일한 객체), `agent_rs_dev/review_d4f_report.md`(검토자가 처음 찾음).
