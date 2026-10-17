# gin-control 2단계 2c: mirror 끈 rank의 더러운 segment만 체크포인트 (0단계 확인과 설계 안; 구현은 다음 주)

2026-10-17. 사용자 지시로 구현을 다음 주로 미뤘다. 이 문서는 0단계(소스 확인)와 고를 설계, 어림한 줄 수만 담는다. 트리 복사, 빌드, 코드, 시험은 하지 않았다(0단계를 읽으려고 `agent_gc_p2c/nccl-src`에 e3faf02를 잠깐 꺼냈고, 계획이 바뀐 뒤 지웠다). 표시: [소스] 코드를 읽어 확인, [측정] 기존 로그의 값, [추론] 해석이나 셈, [미확인] 확인 안 함.

줄 번호의 바탕: 호스트 파일 `src/transport/net_ib/gdaki/gin_host_gdaki.cc`는 커밋 e3faf02("gin-control + 2b (gc_layer_p2b.diff fa3f1b48)", md5 `78653573`, 29 979줄), 장치 헤더 `src/include/nccl_device/gin/gdaki/gin_gdaki.h`와 `gin_gdaki_device_host_common.h`도 e3faf02의 것. 시험 프로그램은 worktree의 `../../mirror/impl/test/gin_mi.cu`.

## 단계 목록

1. 0단계: mirror 끈 rank에 바뀐 segment의 기록이 있는지, 2b 모형의 멈춤에 무엇이 드는지 (끝)
2. 설계 고르기와 줄 수 어림 (끝)
3. 이후(다음 주): 트리 복사와 빌드 디렉터리, 구현, `gc_unit_p2c.cc`, 빌드 넷, `pre`, `sites`, `api`, 장치 diff 확인

## 0단계 결과

### 1. mirror 끈 rank에는 바뀐 segment의 기록이 없다 [소스]

- 장치: mirror 쓰기는 `rsPutHold`(gin_gdaki.h 748–)의 811행 조건 `loadConst(&rs->miOn) != 0`일 때만 `rsMiPut`을 부르고, `rsMiPut`이 쓰는 것은 받는 rank 칸의 `cursor`(681행 원자 더하기)와 `broken`뿐이다. 칸은 `rsMiCellOf`(669행)로 찾는데 칸 배열이 없으면 null이다.
- 호스트: 측 표의 mirror 칸은 `gdakiMiOn(r)`일 때만 만든다. 24101행 `miCtx = gdakiMiOn(r) && r->mi.ctx >= 0 ? r->mi.ctx : -1`, 24102행 `nCells = miCtx >= 0 ? r->nranks : 0`, 24135–24138행에서 칸이 있을 때만 `miOn = 1`과 `miCellsOff`를 적는다. 장치 배치 주석도 "mirror 없으면 miOn 0, miCellsOff 0, 칸 없음"이다(gin_gdaki_device_host_common.h 243–245행).
- 그래서 mirror 끈 rank의 장치에는 어떤 쓰기의 표시도 없다. buddy pool에 쓰는 것은 mirror 켠 장치뿐이다.
- 쓸 만한 다른 출처: gin-restore TCP 길의 블록 해시(16323–16337행: `gdakiCkptHash`, `gdakiCkptChanged`)가 있다. 그러나 이 해시는 전체 이미지를 호스트로 옮긴 뒤 호스트에서 세므로 멈춤 안의 D2H를 줄이지 못한다. 게다가 rdma 빌드에서는 `gdakiStoreOn`이 복원 켬 전체로 넓혀져(18019–18027행) 그 길에 닿지 않는다. 결론: 멈춤을 줄일 더러운 출처는 지금 없다.
- gin-mirror의 "segment"는 바이트 단위가 아니라 시간 단위다. 받는 rank의 입력 멈춤마다 바뀌는 lane 번호이고(gin-mirror EXPERIMENT.md 9.3 "segment 번호와 바꾸기"), 이미지 안의 바이트 구획이 아니다. 이미지의 바이트 구획으로 이미 있는 것은 `GDAKI_CKPT_BLOCK` 64 KiB(6241행)뿐이다. 그래서 2c의 segment 크기는 64 KiB 블록으로 잡는다.

### 2. put만 보는 표시로는 이미지가 맞지 않는다 [소스]

이 확인이 지시의 설계(보내는 쪽 put 경로의 비트맵과 링의 dirty set 기록)를 뒤집는다.

- 체크포인트 이미지에는 window만 있지 않다. `gdakiCkptRegions`(16894–16914행)는 window(16899–16901행), `ncclGinRestoreRegister` 버퍼(16905–16906행), 신호 표(16909–16910행), 카운터 표(16911–16912행)를 모두 담는다.
- 그 가운데 상당 부분은 원격 put이 아니라 자기 커널이 쓴다. 학습 모양 커널(`gin_mi.cu`)에서 보내는 window의 칸을 채우고(329행) put 뒤에 poison으로 덮고(343행), 등록 버퍼 `xHist`와 `execCnt`를 쓴다(382, 384행). 4 KiB 커널도 같다(253, 266행).
- put 경로의 비트는 다른 rank가 이 rank에 쓴 바이트만 표시한다. 자기 커널의 쓰기는 장치 헤더 밖의 application 코드라 라이브러리가 볼 수 없다. 그러니 put만 보는 비트로 고른 segment만 옮기면 등록 버퍼와 window의 로컬 쓰기를 놓쳐 저장소 칸이 틀린 이미지를 갖는다.
- 맞추는 길은 둘뿐이다. 하나는 "이 window는 다른 rank의 put만 쓴다"는 새 application 요구다. 이 요구는 시험 프로그램부터 어긴다(보내는 window). 다른 하나는 쓴 쪽과 상관없이 내용으로 바뀜을 찾는 것이다.

### 3. 2b의 멈춤에 드는 것 [소스, 측정, 추론]

- 2b의 저장소 길(`gdakiStoreTake` 18823–18992행): 입력 멈춤 안(DRAINED 뒤)에서 모든 영역을 고정 호스트 staging으로 통째 D2H하고(18894–18896행), header와 blob을 붙인 뒤 한 번 동기화한다(18897–18900행). 멈춤 밖에서는 받는 칸으로 `used` 바이트를 통째 WRITE한다(18967행, `used = gdakiStoreUsedBytes` 18848행 = 64 KiB header + 4 KiB 올림 이미지 + blob, 6358–6370행).
- 받는 칸은 두 칸을 번갈아 쓴다(`recvSlot` 17416행, `gdakiStoreRecvSlot` 17188행). 칸 하나는 늘 두 체크포인트 전의 내용이다.
- 2b 단위 모형(`gc_unit_p2b.cc` 680–689행)도 같다: staging에 이미지 전체를 넣고 `storeBytes += used`. 그 로그는 체크포인트 125개에 store 94 806 977 B(늘 전체 칸), TCP 42 042 638 B(바뀐 블록)였다 `[측정: agent_gc_p2b/logs_p2b/unit_p2b.log 102행]`.
- 20 MiB 이미지에서 2b의 체크포인트 하나: 멈춤 안 D2H 20 971 520 B, 멈춤 밖 WRITE 21 037 056 B + blob `[추론: 위 식으로 셈]`. 시간은 gin-mirror 확인 3의 D2H 13.1 GB/s(30 MiB p50 2.39 ms) `[측정, gin-mirror]`로 셈하면 D2H 약 1.60 ms다 `[추론]`.

## 고를 설계: 라이브러리 안 내용 검사 커널 (put 경로 비트맵 대신)

까닭: 0단계 2가 보이듯 put 경로의 비트는 로컬 쓰기를 놓쳐 맞지 않는다. 내용 검사는 누가 썼든 찾는다.

- **장치 쪽(라이브러리 안).** 멈춤 안(DRAINED 뒤)에서 application 스레드가 copy stream에 검사 커널 하나를 띄운다. 이미지 영역의 64 KiB segment마다 64비트 해시를 세어 장치 메모리의 지난 해시와 견주고, 다르면 해시를 고쳐 쓰고 비트맵 낱말에 `atomicOr`로 비트를 세운다. 비트맵(20 MiB에서 320비트 = 40 B)만 D2H하고 동기화한 뒤, 더러운 segment의 이어진 구간만 staging으로 D2H한다.
  - 커널은 `src/device/onerank.cu` 끝에 두고, 해시와 비트 함수는 새 헤더 하나에 둔다(호스트와 장치가 같이 쓰고 단위 시험이 바로 읽음).
  - application 장치 헤더(`gin_gdaki.h`, `nccl_device/`)는 0줄이다. 그래서 매크로 있는 프로그램과 없는 프로그램 16 조합이 ln4와 같고 설치 헤더도 같을 것이다 `[추론]`.
  - 바뀌는 장치 객체는 `obj/device/onerank.cu.o`와 그 device link(`device_glue.o`)다. nvcc는 `NCCL_GIN_CTRL_TCP`를 받지 않으므로 tcp 빌드 둘에도 쓰이지 않는 커널이 든다 `[소스: src/device/Makefile 24–40행, makefiles/common.mk 119행]`.
- **호스트 쪽(rdma 빌드, mirror 끔만, `#if !NCCL_GIN_CTRL_TCP`).** 저장소 상태에 표 하나를 둔다.
  - segment마다 마지막으로 바뀐 체크포인트 순번.
  - 칸 0, 1마다 그 칸이 온전히 가진 순번과 그 칸이 속한 저장소(gen, rkey).
  - staging이 최신 전체 이미지인지의 표시.
  - 멈춤 밖 WRITE는 header, blob, 그리고 "바뀐 순번 > 그 칸의 순번"인 segment만이다. 칸은 늘 최신 전체 이미지를 갖고 배치는 그대로다(FETCH와 CKPT_STABLE은 바뀌지 않음).
  - 다음이면 전체를 옮긴다: 첫 체크포인트, 배치나 영역 포인터가 바뀜, D2H 실패, staging을 다시 잡음, WRITE 실패, 새 STORE_ACK(gen이 바뀜), buddy 복원.
  - 장치 메모리가 아닌 영역(`cudaPointerGetAttributes`가 device가 아님)은 늘 더럽다고 본다.
  - 끄는 스위치 하나(`NCCL_GIN_RESTORE_STORE_DIRTY`, 0이면 2b 그대로)를 둔다. mirror 켬 길과 tcp 빌드는 바뀌지 않는다.
- **위험** `[추론]`: 64비트 해시 충돌(segment 하나를 견줄 때마다 약 2^-64)로 바뀐 segment를 놓칠 수 있다. gin-restore TCP 길의 블록 해시가 이미 받아들인 위험과 같은 꼴이다.
- **put 경로 비트맵을 고르지 않은 까닭.** 위 2절의 로컬 쓰기 때문이다. 더하면 링 기록, 모든 상대의 OR, 잃은 set 처리가 생기는데, 맞음은 오히려 새 application 요구에 기대게 된다.
- **장치 코드 없는 대안**(사용자 결정 거리). gin-restore TCP 길처럼 멈춤 안에서는 D2D 사본만 찍고(16999–17002행), D2H와 해시는 멈춤 밖에서 한다. 장치 코드는 0줄이고 GPU 메모리가 이미지만큼(20 MiB) 더 든다. 멈춤은 D2D 20 MiB(약 0.1–0.2 ms) `[추론, 미확인]`이고, WRITE는 호스트 해시로 줄일 수 있다.

## 멈춤과 WRITE의 어림 (20 MiB 이미지, 실행 없음) [추론]

- 멈춤 = 검사 커널(20 MiB를 GPU가 읽음. 대역은 `[미확인]`이고 300 GB/s로 잡으면 약 0.07 ms) + 띄우기와 비트맵 D2H(약 0.02–0.03 ms) + 더러운 바이트의 D2H(13.1 GB/s).
- WRITE는 칸이 번갈아 쓰이므로 두 간격의 합집합이다. segment가 간격마다 서로 상관없이 비율 p로 바뀌면 1 − (1 − p)²이다.

| 더러운 비율 p | 멈춤 D2H 바이트 (2b 대비) | 멈춤 시간 어림 (2b 1.60 ms 대비) | 멈춤 밖 WRITE 바이트 (2b 대비) |
|---|---|---|---|
| 2 % | 2 % | 약 0.13 ms (약 8 %) | 약 4.0 % |
| 10 % | 10 % | 약 0.26 ms (약 16 %) | 약 19 % |
| 50 % | 50 % | 약 0.90 ms (약 56 %) | 약 75 % |

워크로드별 어림 `[추론: gin_mi.cu 소스로 셈]`:
- 4 KiB 셀: window가 (상대, 단계)마다 칸을 따로 둔다(`regionBytes = bytes × steps`, 658행). 간격 하나(20단계)에 바뀌는 바이트는 window의 약 1 %(2 000단계 중 20)라 이득이 크다.
- 학습 모양: 받는 고리 R = 4는 4단계면 다 덮이고 보내는 window는 단계마다 다시 쓰인다. 간격 20에서는 거의 100 % 더러워 이득이 없다. gin-mirror가 증분을 없앤 까닭 "받는 고리는 어차피 다 바뀐다"(gin-mirror EXPERIMENT.md 9.4)와 같다.

## 어림한 줄 수 (구현 전) [추론]

| 자리 | 줄 |
|---|---|
| 장치: `src/device/onerank.cu` 끝의 검사 커널과 띄우는 함수 | 약 55–70 |
| 장치와 호스트가 같이 쓰는 새 헤더(해시 섞기, segment 항, 비트 세우기, segment 표 구조체) | 약 50–60 |
| application 장치 헤더(`gin_gdaki.h`, `nccl_device/`) | 0 |
| 호스트: 영역 "gin-control (store p2c)"의 순수 부분(segment 계획, 구간 합치기, 칸마다의 WRITE 판정, 전체로 돌아가는 규칙) | 약 110–130 |
| 호스트: 영역의 호스트 부분(장치 버퍼 잡고 풀기, 검사, 구간 D2H, 구간 WRITE, 줄 하나) | 약 140–170 |
| 호스트: ln4 줄 옆의 `#if !NCCL_GIN_CTRL_TCP` 덧붙임(멈춤 안 D2H, 동기화 뒤 확정, WRITE, 상태 칸, 해제; WRITE 자리는 `#else`에 ln4 글 그대로) | 다섯 자리, 약 20–30 |
| `gc_unit_p2c.cc`(비트맵의 동시 세우기, 해시의 호스트 쌍, 판정, 무작위 열 200개의 바이트 같음, 바이트 비율) | 약 500–600 |
| 빌드 스크립트: `GC_FILES`에 파일 둘 더함, `p2c` 키 | 약 20 |

비교: 지시의 put 경로 비트맵이었다면 `gin_gdaki.h`(매크로 뒤)에 약 40–60줄과 측 표 칸 하나, 호스트는 링의 dirty set 기록, OR, 잃은 set까지 약 350줄로 본다. 위 2절 때문에 고르지 않는다.

## EXPERIMENT.md 5절과 9.8절에 넣을 글 (안; 구현과 확인 뒤에 확정)

- 5절: "장치 코드 0줄"을 "장치 변경은 더러운 segment 표시만(라이브러리 안의 검사 커널 하나, `src/device/onerank.cu`; application 장치 헤더는 0줄)"으로 바꾼다. 까닭: mirror 끈 rank의 저장소 길이 멈춤 안에서 이미지를 통째 D2H한다(2b). 바뀐 segment의 기록은 장치에도 호스트에도 없고, 이미지에는 로컬 커널이 쓰는 영역이 있어 put만 보는 표시로는 맞지 않는다. 그래서 내용으로 찾는 커널이 필요하다(2026-10-17 사용자 결정: 호스트 쪽 우회보다 라이브러리 안 변경).
- 9.8절 동일성 확인: "매크로 없는 프로그램과 매크로 프로그램 16 조합은 ln4와 같아야 함, 설치 헤더 같음, 장치 객체는 `onerank.cu.o`와 device link 객체만 다름(네 빌드 모두), 나머지는 SASS 같음"으로 고친다.
