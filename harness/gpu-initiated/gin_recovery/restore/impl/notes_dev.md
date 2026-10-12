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
- 사용자 확인 대기: 위 검토 행 (3)의 남은 차이를 사용자 결정 (나)의 "hk와 같은 레지스터 수"로 받아들일지.
