# GIN 복원의 내용 mirror: 보낸 내용을 받는 rank의 짝 호스트 메모리에 NIC이 한 번 더 써 두어, 보낸 버퍼를 다시 쓰는 application도 되살린다 (gin-mirror)

**목적:** gin-restore의 재실행은 보낸 쪽 원본 버퍼를 다시 읽는다. 이 실험은 보내는 rank의 NIC이 put의 내용을 받는 rank의 짝(buddy) 호스트
메모리에 한 번 더 써 두고 재실행이 그 사본을 쓰게 해, 보낸 버퍼를 곧바로 다시 쓰는 application에서도 죽은 rank를 비트 단위로 같게 되살리는지,
그 정상 경로 비용과 복원 비용이 얼마인지 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `DRAFT` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-13 |
| 기준 브랜치와 커밋 | `exp/gin-mirror` @ `7b21eb58` (master) |
| 사전 등록 태그 | 없음 |
| 마지막 갱신 | 2026-10-15 밤, 사전 등록 전 일관성 고침 여섯(12절): 2절 가설을 pilot에 맞춤(복원 시간은 셀 가족마다의 상한과 FETCH 모형, 비용은 차례 없는 따로 된 QP의 쓰기 하나, 당기기의 반증은 짝 보호 공백 밖만, pool과 버려진 체크포인트는 3절과 같게), 3절 `train_pull_count`의 근거를 잰 당기기 수로, 3절과 7절의 찾는 키와 셀 이름을 고정할 파일대로(`refuse_sl` 더함, `ff_identical`은 빌드 검사로), 8절의 BAR1 검사 자리, QUERY_QP 상한의 단위와 값, 학습 시행 한도 150 s, 9.7절 결함 E 행의 멈춤 시한 거절(사용자 결정 대기), 7절 seed 규칙. 사전 등록 전이고 클러스터 실행 없음. 그 전: 2026-10-15 저녁, pilot 5(set `mi5`, 빌드 ln3, pilot hold P6)의 실행 기록(12절; 7 시행 모두 복원하고 데이터 같음, `lineage_warn` 0, `lane_broken_other` 0, 남긴 당기기 둘이 셋째 시도에 찍힘), ln3 독립 리뷰의 고칠 것 둘(멈춤 시한 거절의 비용과 사용자 결정: 9.3, 18, 19절; 변이 시험의 로그: 12절)과 nit 넷. 그 전: 2026-10-15 저녁, pilot 3(set `mi3`)과 pilot 4(set `mi4`, 빌드 ln2)의 실행 기록(12절; 모든 시행 `lineage_warn` 0, `mi4_pull`의 공백 밖 깨짐 0), 구현 독립 리뷰의 고칠 것 넷(9.7절 결함 E 행, 낡은 글, 9.3절 남긴 당기기의 상한과 pilot 4에서 본 길, 18절 한계)과 nit, 남긴 당기기의 상한을 간격의 절반으로 넓힌 빌드 `ln3`(CPU 단위 시험 다섯 0 failed, 매크로 없는 장치 코드가 hk, i5와 같음; set `mi5`, pilot hold P6), 복원 시간의 두 모드(활성화 관문)와 보고 규칙(3절 끝, 18, 19절). 그 전: 2026-10-15, pilot 3의 결함 E(`mi4_pull`에서 hold가 거절한 체크포인트에 당기기가 쓰여 없어지고 생존 rank 사이 lane이 넘침) 고침과 빌드 `ln2`(계보 + 고침; CPU 단위 시험 다섯 0 failed, 매크로 없는 장치 코드가 hk, i5와 같음), 배포 묶음 set `mi4`와 pilot hold P4, P5(12절, impl/test/PILOT_MI.md). 그 전: 2026-10-15, 계보 구현과 빌드 `ln1`(호스트만; CPU 단위 시험 다섯 0 failed, 새 oracle의 차이는 설계의 다름 목록과 같음, 매크로 없는 장치 코드가 hk, i5와 같음; 12절). 그 전: 2026-10-15, 계보(lineage): 화신 판정을 한 곳으로 모으는 설계 v3, 독립 검토와 재검토, 열린 충돌 셋의 사용자 결정(9.9절, 9.7절의 계보 행, 12절), 구현 시작. 그 전: 2026-10-15, pilot 2(set `mi2`, 빌드 i3)가 결함 A, C, D의 고침을 확인했고 고침 묶음의 독립 리뷰는 막는 문제 없음; 리뷰의 사전 등록 전 항목을 반영: 채점 셈이 설계한 짝 보호 공백을 따로 셈(사용자 결정 대기), `store_rdma`가 체크포인트 닫기 줄을 읽음, A의 호출자 단위 시험, 첫 깨짐 진단, 죽은 프로세스의 늦은 STORE_REQ에 답 없음, magic "RSS5", 학습 hold의 BAR1 읽기, 빌드 i4(연구 `c89ce744`, 운영 `12a0edec`), CPU 단위 시험 넷 0 failed, 매크로 없는 장치 코드가 hk, i5와 같음(12절). 사용자 결정 넷과 사전 등록 숫자는 19절. 그 전: 2026-10-15, pilot 1(set `mi1`)의 결함 넷: 셋을 고치고(되살린 rank의 저장소 요청, mirror 켠 프로세스의 window를 NIC 복사 경로에서 뺌, 비용 peer 팔의 mirror 대상) 하나를 점검(rc 4 셀 셋은 설계 길), 갈래 `exp/gin-mirror-fix`, 빌드 i3(연구 `feefaf6d`, 운영 `2e4008e6`), CPU 단위 시험 넷 0 failed, 매크로 없는 장치 코드가 hk, i5와 같음(12절). 다시 하는 pilot 전. 그 전: 2026-10-15, 다섯 갈래의 병렬 구현과 통합: `exp/gin-mirror-int`에서 하나의 계층([impl/mi_layer.diff](impl/mi_layer.diff), md5 `e27998db`)으로 합침, 빌드됨(연구 `1b50d11b`, 운영 `a34db6e6`), CPU 단위 시험함(넷, 0 failed), 매크로 없는 장치 코드가 hk와 i5에 SASS와 자원까지 같음, 시험 드라이버를 통합 헤더로 다시 빌드, 독립 리뷰 둘 반영(12절). pilot 전([impl/test/PILOT_MI.md](impl/test/PILOT_MI.md)). 그 전: 2026-10-13, 공유 인터페이스(impl/의 헤더 여섯, [impl/PARALLEL.md](impl/PARALLEL.md), build_mi.sh 뼈대)와 실행 가능성 확인 1, 3, 4의 결과(9.8절, `[측정]`; 9.3, 9.4, 9.5절의 수치). 그 전(같은 날): 재검토가 연 충돌 → (가) INJECTED(9.4절), 올리기 꼴 확인; 재검토의 고칠 것 여섯; RDMA 저장소, 단계 맞춤 가져오기, 첫 검토, 결정 여덟; 학습 모양; 초안. 라이브러리 구현과 빌드 없음 |

표시: `[측정]` 원자료나 시행별 표에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. gin-restore 문서의 수치를 옮길 때는 원자료에서 다시
셌는지 함께 적는다.

**줄 번호.** `[소스]`의 줄 번호는 따로 적지 않으면 gin-restore의 계층 diff [../restore/impl/rs_layer.diff](../restore/impl/rs_layer.diff)(md5
`f005bb67`)의 줄이다. diff에 없는 공용 코드(hk 그대로인 장치 대기, flush, QP 생성)는 "rs 트리"로 적고, 그 diff를 적용한 트리(세션 스크래치
`agent_rs_int/nccl-src`; 2026-10-13에 그 트리의 `git diff --diff-algorithm=histogram`이 위 md5와 같음을 확인)의 `gin_gdaki.h`, `gin_host_gdaki.cc` 줄이다.

**말.** gin-restore의 말(논리 rank, 예비 프로세스, 짝, 체크포인트, 입력 멈춤, 절단점, 송신 쪽 로그, 재실행, 중복 억제, 붙잡음, 무장, DISARM)은
[../restore/EXPERIMENT.md](../restore/EXPERIMENT.md) 머리말과 같다. 이 실험에서 더 쓰는 말:
- mirror 쓰기: 보내는 rank의 NIC이 put의 내용을 받는 rank가 아니라 그 rank의 짝의 호스트 pool에 한 번 더 쓰는 RDMA WRITE.
- pool: 짝의 호스트 메모리에 GIN 보호 영역(PD)으로 등록한 영역. 짝이 맡은 rank(그 rank의 체크포인트도 이 짝에 있음)로 들어온 내용만 둔다.
- segment: 받는 rank의 체크포인트 간격 하나(앞 절단점과 다음 절단점 사이)에 그 rank로 들어온 내용. pool은 segment 자리 셋을 돌려 쓴다.
- lane: segment 안에서 보내는 rank 하나의 몫. 보내는 rank가 자기 GPU의 커서 하나로 자리를 잡으므로 rank 사이의 조율이 없다.
- mirror 문맥: 복원 계층이 사용자 GIN 문맥들 뒤에 하나 더 만드는 GIN 문맥. mirror 쓰기만 이 문맥의 QP로 나간다(9.2절).
- 당기기: lane이 차 가면 보내는 rank가 받는 rank에게 다음 체크포인트를 앞당겨 달라고 하는 것.

| 빌드 키 | 내용 | 쓰는 곳 |
|---|---|---|
| `mi` | 이 실험의 연구 빌드: gin-restore `rs` 계층 위에 9절의 mirror 계층 | 새 셀, 회귀 |
| `mip` | 같은 소스의 운영 빌드(`-DNCCL_GIN_TS_PRODUCTION`) | 비용 셀 |
| `rs`, `rsp` | gin-restore의 빌드(대조, 읽기만) | 대조 |

빌드 키, 셀 이름, 예측의 찾는 키는 원자료를 찾는 이름일 뿐이다.

## 1. 배경과 연구 질문

**gin-restore가 보인 것.** 랭크 4개(노드 둘, GPU마다 둘)에서 rank 3을 단계 중간에 SIGKILL하면, 생존 rank의 상대를 모르는 대기가 풀리지 않고 붙잡혔다가
원래 값으로 끝났고 모든 rank의 최종 데이터가 장애 없는 실행과 비트 단위로 같았다(10/10). 복원은 첫 죽음 판정부터 277.7–397.2 ms(중앙값 375.6, n=10),
rank 1 kill은 372.1–400.7 ms(n=5)에 끝났다 `[측정: ../restore/results/20261013_main/trials_scored.csv에서 다시 셈]`. 체크포인트마다 생존 rank의 입력 멈춤은
시행마다의 최대가 5.2–5.6 ms였다(장애 없음 n=5, 같은 표에서 다시 셈) `[측정]`.

**그 결과가 기대는 조건.** 송신 쪽 로그는 연산의 설명(항목 64 B: 종류, 대상 window와 오프셋, 크기, 원본 window와 오프셋, 신호)만 적고 내용은 적지
않는다(gin-restore 9.5절). 재실행 때 생존 rank의 helper가 원본 window를 NIC 복사 경로로 다시 읽어 예비 프로세스에 보낸다 `[소스: 10760–10843
gdakiRsLogExport]`. 그래서 application은 받는 rank의 다음 확정 체크포인트까지 보낸 버퍼를 바꾸지 않아야 한다(gin-restore 9.7절 12번). 시험 workload는
단계마다 보내는 칸을 따로 두어 이 규칙을 지켰다(gin-restore 9.8절 끝의 메모) `[소스: ../restore/impl/test/gin_rs.cu 205]`.

**문제.** 실제 학습 application은 보낸 버퍼(gradient 버퍼 등)를 단계마다 다시 쓴다. 그러면 재실행은 바뀐 내용을 조용히 다시 넣고, 되살린 rank의 상태가
틀린다 `[추론]`. 막는 길은 둘이었으나 둘 다 모자랐다.
- 덮어쓰기 감지(checksum)는 찾기만 하고 지키게 하지 못하며 비싸다. 로그 끔 대비 표본 방식은 4 KiB put 지연 +18.2%(rain) / +46.2%(sunny), 256 KiB 8개 묶음
  대역 −49.8% / −51.6%, 전부 방식은 256 KiB 지연 24.0배 / 25.3배, 대역 −97.5% / −97.7%였다(받는 노드마다 팔마다 6회의 중앙값) `[측정: 같은 표에서 다시
  셈]`. 사용자는 checksum을 기본 끔으로 정했다.
- 확정 단계(`ncclGinRestoreStep`의 stableStep)를 보고 버퍼를 다시 쓰게 하면 application이 보내는 버퍼를 체크포인트 간격과 확정 지연만큼 여러 벌 두어야
  한다(gin-restore 18절). application을 고쳐야 하는 일이다.

**사용자 결정(2026-10-13, 메인 세션이 전함; 이 실험의 고정 전제).**
1. 보낸 내용을 가져서 재실행이 원본 버퍼에 기대지 않게 한다. 내용은 GPU 메모리가 아니라 호스트 메모리에 둔다.
2. 내용은 받는 rank의 짝 호스트 메모리(그 rank의 체크포인트와 같은 곳)에 둔다. 예비 프로세스는 체크포인트와 내용을 한 곳에서 가져온다. 보내는 rank의
   NIC이 같은 내용을 두 번 쓴다: 받는 rank에(지금처럼), 그리고 짝의 pool에.
3. pool은 (받는 rank × 체크포인트 간격)마다 segment 하나로 관리한다. 받는 rank의 체크포인트 K가 확정되면 segment K를 통째로 버린다. 상대마다 살아 있는
   segment는 많아야 둘(늦은 확정이면 셋)이다.
4. 넘칠 것 같으면 먼저 다음 체크포인트를 앞당기고(간격을 움직임), DISARM(지금 동작)은 마지막 수단이다.
5. 정상 경로 비용은 NIC의 쓰기 하나(put마다 WQE 하나 더, 보내는 쪽 링크의 바이트 두 배)여야 하고 GPU 스레드의 복사가 아니어야 한다. 복원 비용은 살아 있는
   segment를 가져오는 것이고 segment 크기 대 복원 시간으로 잰다. 범위는 단일 실패(죽는 rank 하나; 짝과 그 짝이 함께 죽지 않음)다.
6. 이 설계는 "보낸 버퍼를 다시 쓰지 않음" 규칙을 없애고 checksum을 필요 없게 한다. checksum 코드 길은 그대로 둔다.

**질문.**
1. 보낸 버퍼를 put의 local 완료(flush나 wait) 바로 뒤에 다시 쓰는 workload에서, 죽은 rank를 체크포인트와 pool의 내용으로 되살렸을 때 최종 데이터가 장애 없는
   실행과 비트 단위로 같은가. 같은 workload를 mirror 없이(gin-restore 방식) 되살리면 실제로 틀리는가(대조).
2. 복원 시간은 가져오는 segment 바이트에 따라 어떻게 늘어나는가.
3. 정상 경로 비용(4 KiB와 256 KiB put 지연, 256 KiB 묶음 대역)은 로그만 켠 팔보다 얼마나 더 드는가. NIC의 WQE 하나와 보내는 쪽의 두 번째 바이트가 비용의
   전부인가.
4. pool 메모리는 체크포인트 간격에 따라 어떻게 늘고, 당기기가 DISARM 없이 lane 넘침을 막는가.
5. gin-restore의 예측들(비용 제외)이 이 계층에서 mirror를 끄거나 켜도 그대로인가.
6. 짝이 죽었다 되살아난 뒤, 그 짝이 맡은 rank가 전체 이미지 다시 받기와 lane 다시 켜기로 보호를 되찾고, 그다음 그 rank가 죽어도 되살아나는가(2026-10-13 사용자
   결정으로 범위에 넣음, 9.6절).
7. 학습 모양의 전송(rank마다 상대 셋에 단계마다 2 MiB, 보낸 버퍼를 local 완료 직후 덮어씀)에서도 죽은 rank를 비트 단위로 같게 되살리는가. 그때 복원 시간, pool의
   최고 사용량, 당기기 수는 얼마인가(9.8절 학습 모양 모드; 받는 고리는 9.4절의 단계 맞춤 가져오기, 이미지는 RDMA 저장소).

## 2. 가설

DRAFT다. 사전 등록 때 고정한다.

| 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|
| 덮어써도 정확한 복원: 재실행에 들어가는 모든 put 내용이 pool에서 오면, 보낸 버퍼를 local 완료 직후 다시 쓰는 workload의 최종 데이터가 장애 없는 실행과 비트 단위로 같다 | mirror 켠 kill 셀에서 어느 rank의 최종 상태나 받은 칸이 기준과 다른 시행이 있다, 또는 내보내기가 원본 바이트를 실은 시행이 있다 |
| 대조: 같은 workload를 mirror 없이 되살리면 틀린다(checksum 끔) 또는 거절된다(checksum 켬) | mirror 끈 덮어쓰기 kill 셀에서 데이터가 같거나 fallback 없이 끝난다 |
| 복원 시간은 셀 가족마다의 상한 안이고, 가져오기(FETCH)는 RDMA READ의 모형을 따른다. FETCH 시간(첫 READ를 낸 때부터 마지막 완료까지)은 a + 가져온 바이트 / θ(실행 가능성 확인 3의 a 5 µs, θ 11.88 GB/s)이고 segment 바이트와 함께 는다. 복원 시간(첫 죽음 판정 줄 → 마지막 생존 rank의 게시 줄)은 학습 모양 밖의 복원 셀에서 2 000 ms, 학습 모양 셀에서 1 000 ms 안이다(초안 값; 3절이 고정). 2026-10-15 고침: 처음 가설의 더하기 꼴(gin-restore의 복원 시간 + 짝의 drain + 바이트 / θ)은 pilot과 맞지 않아 버렸다. mirror 켬 길은 TCP FETCH와 한꺼번에 가져오기 대신 RDMA FETCH와 단계 맞춤 가져오기(재실행은 게시 뒤)를 지나므로 gin-restore의 TCP 복원보다 짧다. pilot 2–5에서 학습 모양 밖의 mirror 켬 셀(4 KiB 덮어쓰기, segment, 당기기, mirror 켬 회귀)의 죽음 38건은 72.2–206.4 ms, 학습 모양의 죽음 9건은 97.1–294.9 ms, 같은 계층에서 mirror를 끈 gin-restore 회귀(TCP 길, `rs4_kill3`, `rs4_kill3_ckpt`) 7건은 365.5–380.7 ms였다. 활성화 뒤 부분(`post_activate_ms`)은 mirror 켬 학습 모양 밖 48.1–80.4 ms 대 끔 260.8–273.7 ms였다 `[측정: results/20261015_pilot{2,3,4,5}/에서 rows_mi.py로 다시 셈; 네 pilot을 합친 범위, 셀마다 시행 n 1–5]`. 두 모드(활성화 관문)는 3절 끝 | segment가 클수록 FETCH 시간의 중앙값이 줄거나, 어느 시행의 FETCH 시간이 a + 바이트 / θ와 ±30%(초안) 넘게 다르거나, 학습 모양 밖의 복원 셀에서 복원이 2 000 ms, 학습 모양 셀에서 1 000 ms를 넘는다(3절 `ow_restore_time`, `seg_restore_slope`, `second_death_restored`, `train_restore_parts`) |
| 정상 경로 비용은 mirror 쓰기 하나다. mirror 쓰기는 사용자 put과 같은 QP의 둘째 WQE가 아니라 mirror 문맥의 따로 된 QP에 내는 WQE 하나이고, 두 QP 사이 차례는 없으며, flush와 wait 끝에서 mirror QP의 완료를 따로 기다린다(9.2절). 보내는 rank의 NIC은 같은 원본을 GPU 메모리에서 두 번 읽는다. 그래서 로그 켬 팔(on)에 견주어 4 KiB put 지연은 많아야 put 하나의 지연만큼 늘고(두 완료가 겹치지 않는 최악), 2 MiB put 지연은 약 2배(데이터 몫을 두 번 읽음), 묶음 대역은 약 절반이다 `[소스, 추론]`. 2026-10-15 고침: 처음 가설("4 KiB 지연은 수백 ns 늘고 문턱 0.5 µs, 대역은 많아야 절반")은 둘째 완료를 기다리는 몫을 빠뜨렸다. 비용 pilot(pilot 2–4, 받는 노드마다 팔마다 실행 한 번씩, 세 번)에서 mirror-peer 대 on은 4 KiB +8.19 µs(rain), +8.80–8.90 µs(sunny), 2 MiB 1.855–1.872배, 묶음 대역 비 bw256k 0.630–0.635, bw2m 0.552–0.558였고, mirror-self도 같은 크기였다(4 KiB +7.17–8.64 µs, 2 MiB 1.915–1.927배). off 팔의 4 KiB put 지연은 11.26–12.29 µs였다 `[측정: 비용 pilot의 원자료에서 rows_mi.py로 다시 셈; 세 pilot을 합친 범위]` | 4 KiB 지연 증가가 put 하나의 지연을 넘거나, 2 MiB 지연이 두 배를 뚜렷이 넘거나 데이터 몫을 두 번 읽지 않은 만큼 작거나, 묶음 대역이 절반보다 뚜렷이 작다. 판정의 수는 3절의 비용 예측(`cost_mirror_lat4k`, `cost_mirror_lat`, `cost_mirror_bw`)이 정한다. 3절의 초안 수(+2.5 µs, 0.40–0.60)는 위 pilot과 맞지 않아 사전 등록 때 사용자 결정으로 고정한다(19절) |
| pool 메모리는 체크포인트 간격 × 단계당 바이트에 비례하고 살아 있는 segment는 둘(늦은 확정이면 셋)이다 | 간격을 두 배로 했을 때 최고 살아 있는 바이트(`pool_max_bytes`)의 중앙값 비가 2와 ±25% 넘게 다르다, 또는 넷째 자리가 필요해 다시 시작한 멈춤이 있다(3절 `pool_vs_interval`, `train_segments`. 2026-10-15 고침: 처음 글의 "lane 최대 채움"과 "넷째 segment가 쓰인다"를 3절과 채점기의 열에 맞춤) |
| 당기기가 넘침을 막는다: 단계 하나가 lane에 들어가면 DISARM 없이 지나간다. kill 시행에는 설계한 짝 보호 공백(9.6절: 죽은 rank가 맡던 rank 쪽 lane의 깨짐과 그 rank의 DISARM, kill부터 그 rank의 복원 뒤 첫 확정 체크포인트까지)만 남는다. pilot 4, 5(빌드 ln2, ln3)의 `mi4_pull` kill 시행 10건에서 공백 밖 lane 깨짐과 DISARM은 0, 공백의 lane 깨짐은 시행마다 0–2줄이었다(빌드 i4의 pilot 3 시행 1건은 결함 E로 공백 밖 깨짐 6, 9.3절) `[측정: rows_mi.py로 다시 셈]` | 당기기 셀의 장애 없는 시행에서 lane 깨짐이나 DISARM 줄이 나오거나, kill 시행에서 설계한 짝 보호 공백 밖의 lane 깨짐이나 DISARM 줄이 나오거나(3절 `pull_no_disarm_none`, `pull_no_disarm_kill`, 학습 모양은 `train_pull_count`), kill 시행이 fallback한다. 2026-10-15 고침: 처음 글은 공백의 줄까지 셌다(3절, 12절의 채점 셈 고침 행) |
| 회귀 없음: mirror를 끄면 gin-restore의 비용 밖 예측이 원래 기준대로 맞고, 켜도(덮어쓰지 않는 workload) 같다 | 그 예측 가운데 원래 판정식을 어기는 것이 있다 |
| 복원 뒤 보호를 되찾음: 짝 b가 되살아나면 b가 맡은 rank d의 다음 올리기가 전체 이미지가 되어 확정되고, 그 멈춤에서 lane이 다시 켜져 d가 다시 무장되며, 그 뒤 d가 죽어도 되살아난다 | d가 b의 복원을 본 뒤 되살린 b에 전체 이미지를 처음 확정하기까지 d의 체크포인트가 둘 이상 void가 되거나(3절 `reimage_after_restore`의 "버려진 체크포인트 ≤ 1"과 같은 기준. 2026-10-15 고침: 처음 글 "둘 넘게"는 3절과 하나 어긋났음), d가 다시 무장되지 않거나, 다시 무장된 뒤 d의 kill이 fallback하거나 데이터가 기준과 다르다 |

## 3. 사전 예측 (측정 전에 작성)

DRAFT다. 문턱과 n은 pilot 뒤 고정한다. 판정은 유효한 시행만으로 센다(8절). "≥ k/n"은 유효 시행 n개 가운데 조건이 참인 것이 k개 이상이라는 뜻이다.

| 무엇을 예측했나 | 셀 | 시행마다의 조건 | 판정식(초안) | 근거 | 찾는 키 |
|---|---|---|---|---|---|
| 덮어쓰는 workload에서 생존 rank의 대기가 붙잡힘 | `mi4_kill3_ow` | 모든 생존 rank의 `waitSignal`이 문턱 이상으로 돌아옴, 비동기 오류 0, 거절 줄 0 | ≥ 9/10 | gin-restore 9.2절 | `ow_wait_held` |
| 같은 셀: 최종 데이터가 기준과 같음 | `mi4_kill3_ow` | 모든 rank의 최종 상태, 받은 칸, 신호 값이 호스트 기준과 비트 단위로 같고 독 값이 들어가지 않음 | ≥ 9/10 | 9.4절 | `ow_data_equal` |
| 같은 GPU의 다른 rank가 죽어도 같음 | `mi4_kill1_ow` | 대기 붙잡힘, 데이터 같음(위 행의 조건), 생존 rank 재실행 없음, 되살린 rank가 끝까지 감 | ≥ 4/5 | 배치의 대칭 `[추론]`, gin-restore `kill_other` | `kill_other_ow` |
| 체크포인트 입력 멈춤 중 kill도 kill 앞에 확정된 체크포인트에서 비트 단위로 되살림 | `mi4_kill3_ckpt_ow` | 시험 스위치의 죽음 줄이 있고 생존 rank 셋이 모두 그 멈춤 안(`die_in_pause` = 3), 위 행의 넷(대기, 데이터, 재실행 없음, 끝까지)이 참, 쓰인 체크포인트가 kill 앞에 확정된 것 | ≥ 4/5 | 9.4절, gin-restore `ckpt_kill` | `ckpt_kill_ow` |
| 생존 rank는 다시 실행하지 않음, 되살린 rank가 끝까지 감 | `mi4_kill3_ow` | 생존 rank 단계 실행 수 모두 1, 되살린 rank exit 0 | 10/10, ≥ 9/10 | gin-restore 9.6절 | `ow_no_reexec`, `ow_revived_done` |
| 다시 보내기 억제가 정확함 | `mi4_kill3_ow` | 사용자 문맥 통로마다 억제 수 = 누적 실행 수 − 체크포인트 때 실행 수, mirror 통로의 예산 0 | ≥ 9/10 | 9.2절 완료 세기 | `ow_suppress_exact` |
| 재실행의 내용은 모두 pool에서 옴 | `mi4_kill3_ow` | 내보내기가 실은 원본 바이트 0, 절단점 뒤의 내용 있는 put 항목이 모두 MIRROR 표시, 가져오기가 pool에서 쓴 바이트 = 그 항목들의 바이트 합 | ≥ 9/10 | 9.4절 | `ow_from_pool` |
| 복원 시간이 한도 안 | `mi4_kill3_ow` | 첫 죽음 판정 줄 → 마지막 생존 rank의 복원 완료 줄 ≤ 2 000 ms | ≥ 9/10 | gin-restore의 2 000 ms 문턱 | `ow_restore_time` |
| 대조: mirror 없이 덮어쓰면 데이터가 틀림 | `mi4_kill3_ow_nomirror` | 복원은 끝나고(대기 붙잡힘) 되살린 rank의 받은 칸이나 상태가 기준과 다름 | ≥ 4/5 | 1절 문제 `[추론]` | `nomirror_corrupt` |
| 대조: checksum 표본이면 찾아서 fallback | `mi4_kill3_ow_sampled` | 내보내기 꼬리에 "source buffer changed", fallback 줄, 대기가 fallback + 2 000–2 500 ms에 오류로 풀림 | ≥ 4/5 | gin-restore 9.5절 | `nomirror_detect` |
| FETCH 시간이 segment 바이트와 함께 늚 | `mi4_seg_4k`, `mi4_seg_32k`, `mi4_seg_128k` | 셀마다 FETCH 시간(줄), 가져온 바이트, drain 시간, 전체 복원 시간 | FETCH 시간(첫 READ를 낸 때부터 마지막 완료까지)의 중앙값이 바이트 순서대로 늘고 각 시행이 a + 바이트 / θ의 ±30% 안(절편 a와 θ는 9.8절 확인 3: rank 3 kill 배치에서 a 0.005 ms, θ 11.88 GB/s `[측정]`; 작은 F에서는 READ 지연이 a에 들어감); 전체 복원은 모두 ≤ 2 000 ms(RDMA에서 FETCH는 수 ms라 전체 시간의 기울기는 잡음에 묻힘 `[추론]`) | 9.4절 시간 어림 | `seg_restore_slope` |
| pool 메모리는 간격에 비례 | `mi4_int_10`, `mi4_int_20`, `mi4_int_40` | 최고 살아 있는 바이트(`pool_max_bytes`: 모든 프로세스의 "mirror summary" max_live_bytes 가운데 최대), segment 다시 시작 수 | 셀마다 모든 시행에서 다시 시작 0이고 최고 바이트 > 0, 간격이 두 배일 때 최고 바이트 중앙값의 비 2 ± 25%(20/10과 40/20) | 9.3절 | `pool_vs_interval` |
| 당기기가 넘침을 막음(장애 없음) | `mi4_pull_none` | 20단계마다 당기기 ≥ 1(`pulls_sent` ≥ 단계 수 / 20), lane 깨짐 0, DISARM 0 | 3/3 | 9.3절 | `pull_no_disarm_none` |
| 당기기 셀의 kill도 DISARM 없이 붙잡고 되살림 | `mi4_pull` | 위 대기와 데이터 조건, 그리고 설계한 짝 보호 공백 밖의 lane 깨짐과 DISARM 0(공백: 죽은 rank가 맡던 rank 쪽 lane의 깨짐과 그 rank의 DISARM, kill부터 그 rank의 복원 뒤 첫 확정 체크포인트까지, 9.6절. 2026-10-15 DRAFT 중 고침: pilot 1, 2에서 이 공백이 kill 시행마다 깨짐 2줄로 나와 옛 셈으로는 늘 틀림, 12절) | ≥ 4/5 | 9.3절 | `pull_no_disarm_kill` |
| 넘치면 DISARM하고 fail-fast | `mi4_overflow` | lane 깨짐 줄과 DISARM 줄, 그리고 hold 시작 줄 없이 대기가 죽음 판정 + 2 000–2 500 ms에 오류로 풀림, 또는 rank 3이 kill 순간 잠깐 무장돼 있어 hold가 시작되면 fallback으로 끝나고 대기가 fallback + 2 000–2 500 ms에 오류로 풀림(2026-10-15 DRAFT 중 넓힘: pilot 1에서 rank 3이 체크포인트 60에 한 번 무장됨, 12절; 사용자 결정 대기) | ≥ 4/5 | 9.3절 끝 수단 | `overflow_failfast` |
| 장애 없음: 데이터 같음, 복원 0, 멈춤이 짧음 | `mi4_none_ow` | 데이터 같음, 복원 0, 입력 멈춤 ≤ 10 ms(멈춤 안 D2H 포함), segment 다시 시작 0 | 5/5 | gin-restore `none_clean` | `ow_none_clean` |
| 켤 수 없는 mirror 설정은 모든 rank가 같은 이유의 오류: mirror와 checksum 표본을 함께 켬 | `mi4_refuse_csum` | 모든 rank의 Resume 오류, 이유 문자열이 rank 사이에서 같고 조건 36(checksum과 함께)의 글자, 오류 없이 fail-fast로 넘어간 rank 없음 | 3/3 | 9.7절 Resume 조건 | `refuse_csum` |
| 같음: rank 하나만 mirror 끔 | `mi4_refuse_mirror1` | 같은 꼴, 조건 34(합의가 mirror를 끔)의 글자 | 3/3 | 같음 | `refuse_mirror1` |
| 같음: S나 L이 rank 사이에서 다름 | `mi4_refuse_sl` | 같은 꼴, 조건 39(rank 사이에서 다름)의 글자 | 3/3 | 같음 | `refuse_sl` |
| 짝이 되살아난 뒤 맡은 rank가 보호를 되찾음 | `mi4_kill2_kill3_ow` | rank 2의 복원이 `mi4_kill3_ow`의 대기와 억제 조건을 채우고, RESTORED(2) 뒤 rank 3이 처음 멈춤에 성공한 체크포인트의 올리기가 전체 이미지(RDMA 저장소는 늘 전체; mirror 끔 길은 `baseCkpt = ~0`)이며 되살린 rank 2에서 확정됨, 그 사이 확정되지 못하고 버려진 rank 3의 체크포인트 ≤ 1, 둘째 kill 전에 모든 생존 rank에서 rank 3이 다시 무장되고 보내는 rank마다 rank 3의 lane이 다시 켜짐 | ≥ 4/5 | 9.6절 | `reimage_after_restore` |
| 그다음 맡은 rank의 죽음도 되살림(둘째 죽음) | `mi4_kill2_kill3_ow` | 두 죽음 모두 생존 rank의 대기 붙잡힘과 비동기 오류 0, 생존 rank의 단계 실행 수 모두 1, 복원마다 ≤ 2 000 ms, 끝에 모든 rank의 데이터가 기준과 같음, 둘째 복원의 이미지와 segment가 되살린 rank 2에서 옴. 다시 무장되기 전에 둘째 kill이 나면 조건 불충족으로 셈(제외 아님) | ≥ 4/5 | 9.4절(끝점 갱신), 9.6절 | `second_death_restored` |
| 회귀(mirror 끔): gin-restore의 복원과 거절 셀 | gin-restore 7절의 셀을 이름과 env 그대로 `@mi`: `rs4_kill3`, `rs4_kill3_ckpt`, `rs4_kill1`, `rs4_kill3_nospare`, `rs4_kill3_spareabsent`, `rs4_none`, `rs4_none_off`, `rs4_refuse_symgin`, `rs4_refuse_gintype`, `rs4_refuse_restoreoff1`, `rs4_refuse_nomacro` | gin-restore의 원래 판정식 그대로 | 원래 기준(그 실험의 k/n) | 9.7절 회귀 행 | `rg_wait_held`, `rg_data_equal`, `rg_no_reexec`, `rg_revived_done`, `rg_suppress_exact`, `rg_restore_time`, `rg_ckpt_kill`, `rg_kill_other`, `rg_nospare_failfast`, `rg_spare_absent_fallback`, `rg_none_clean`, `rg_strict_forced`, `rg_strict_notforced`, `rg_refuse_reason`, `rg_refuse_nomacro_clean` |
| 회귀(mirror 끔): gin-remaining 실행기의 회귀 셀 | `reg_mr4_none`, `reg_mr4_none_hold`(장애 없음), `reg_rm4_kill3_untimed`, `reg_rm4_kill3_untimed_hold`(rank 3 kill) `@mi` | 그 실험의 원래 판정식(장애 없음은 투명, kill은 degraded 해제 2 000–3 000 ms와 생존 rank 셋의 전송) | 셀마다 5/5 | 같음 | `regression_restore_off`, `regression_kill3_off` |
| 회귀(mirror 켬, 덮어쓰지 않는 workload): 장애 없음 | `rs4_none_mion` `@mi` | 데이터 같음, 복원 0 | 5/5 | 같음 | `regression_none_on` |
| 회귀(mirror 켬, 덮어쓰지 않는 workload): rank 3 kill | `rs4_kill3_mion` `@mi` | 대기 붙잡힘, 데이터 같음, 재실행 없음, 되살린 rank가 끝까지 감 | ≥ 4/5 | 같음 | `regression_kill3_on` |
| mirror의 4 KiB 지연 | 비용 가족 mirror, 지표 `lat4k`, 노드 둘 | 팔 `mirror-self`, `mirror-peer` 대 `on`(로그 켬)의 중앙값 차이 | 노드마다 +2.5 µs 안. 어림: hold 길은 서로 기다리는 L2 왕복 3–4번에 1.0–1.5 µs였고(gin-restore 15, 18절) mirror가 4–5번(칸 읽기, 커서, 게이트, rkey, SQ 자리)을 더해 +1.2–2.0 µs `[추론]`. 사용자의 첫 예상(수백 ns)과 앞 초안 +0.5 µs는 이 어림과 어긋나 고침(검토) | 9.2절 | `cost_mirror_lat4k` |
| mirror의 256 KiB, 2 MiB 지연 | 같은 가족 `lat256k`, `lat2m` | 같은 차이 | 보고만. 어림: peer 팔은 put 하나의 직렬 시간까지 늚(2 MiB에서 off 팔 대역 5.5–6.4로 0.33–0.38 ms `[추론]`) | 9.2, 9.8절 | `cost_mirror_lat` |
| mirror의 묶음 대역 | 같은 가족 `bw256k`, `bw2m` | peer 팔의 `mirror-peer` / `on` | 노드마다 0.40–0.60(보내는 쪽이 GPU 읽기와 선을 모두 두 번 씀). self 팔의 비는 보고(GPU 읽기만 두 번) | 9.2절 | `cost_mirror_bw` |

**표에서 뺀 행**(2026-10-15, DRAFT 중): "매크로 없는 프로그램은 그대로"(fail-fast 기계어: 매크로 없는 프로그램 넷의 SASS 전체와 자원, 라이브러리 장치 객체가
`rs`와 같음; 찾는 키 `ff_identical`)는 시행의 원자료가 아니라 빌드 검사라 예측 표 파일([impl/test/predictions_mi.csv](impl/test/predictions_mi.csv))에도
채점기에도 없었다. 그래서 이 표에서 빼고 7절의 빌드 검사와 10절의 QA 항목으로 둔다. 본 실행 빌드 ln3에서는 이미 확인했다(12절 ln3 행: `build_mi.sh ident`
8/8이 hk, i5와 같음) `[측정]`.

두 비용 팔은 실제 비용을 위아래로 묶는다: self 팔은 mirror QP의 게이트와 선이 없고(자기 루프), peer 팔은 받는 노드까지 두 배를 받는다. 실제 셋 이상 노드의 비용은 그
사이다 `[추론]`.

**학습 모양 셀의 예측(초안).** gin-restore가 할 수 없던 예측은 첫 줄이다: 보낸 버퍼를 단계마다 다시 쓰고 받는 칸을 고리로 다시 쓰는 전송에서 복원한 데이터가 맞음.

| 무엇을 예측했나 | 셀 | 시행마다의 조건 | 판정식(초안) | 근거 | 찾는 키 |
|---|---|---|---|---|---|
| 덮어쓰는 학습 모양 전송에서 최종 데이터가 기준과 같음 | `mi4_train_kill3` | 모든 rank의 상태 이력 x(0..2 000)와 마지막 받은 칸, 신호 값이 호스트 기준과 비트 단위로 같음; 생존 rank의 대기 붙잡힘, 재실행 없음, 억제 정확 | ≥ 9/10 | 9.4절 | `train_data_equal` |
| 단계 맞춤 가져오기가 단계마다 한 번 | `mi4_train_kill3` | 예비 프로세스가 단계 K+1부터 마지막 표시 단계까지 각 단계의 입력을 그 커널 전에 한 번씩 넣었고(라이브러리 줄), 끝에 남은 입력 0, INJECTED가 마지막 넣은 단계 뒤 한 번이고 생존 rank의 쉬던 put은 그 뒤에 나감(생존 rank 줄) | ≥ 9/10 | 9.4절 | `train_paced_import` |
| 복원 시간의 부분 | `mi4_train_kill3` | FETCH 시간(첫 READ를 낸 때부터 마지막 완료까지)이 a + F / θ의 ±30% 안(F = 이미지 + K 뒤 segment 바이트, a와 θ는 실행 가능성 확인 3: 0.005 ms, 11.88 GB/s `[측정]`), 전체 T ≤ 1 000 ms(gin-restore 중앙값 375.6 ms + drain + FETCH) | ≥ 9/10 | 9.4절 어림 | `train_restore_parts` |
| segment 자리 | `mi4_train_none`, `mi4_train_kill3` | 넷째 자리가 필요해 다시 시작한 멈춤(9.3절 (나)) 수, 셋째 자리를 쓴 멈춤 수, 짝마다 살아 있는 바이트의 최고 | 다시 시작 0; 셋째 자리와 최고 바이트는 보고 | 9.3, 9.8절 | `train_segments` |
| 당기기와 DISARM | `mi4_train_none`, `mi4_train_kill3` | lane 깨짐, DISARM, 당기기 수 | 설계한 짝 보호 공백(9.6절, 위 `pull_no_disarm_kill` 행) 밖의 깨짐 0, DISARM 0(2026-10-15 DRAFT 중 고침, 12절: kill 시행의 공백 깨짐은 빼고 셈); 당기기(`pulls_sent`, `pulls_taken`)는 보고만 하고 판정식에 없음. 2026-10-15 고침: 처음 글 "L이 간격 둘이라 0에 가까움 `[추론]`"은 틀렸다. L(80 MiB)이 보내는 rank 하나가 간격 하나에 보내는 바이트(2 MiB × 20 = 40 MiB)의 두 배라 당기기 문턱 50%가 간격 하나의 바이트와 같고, 커서는 segment를 바꾸는 입력 멈춤 무렵 문턱에 닿는다 `[추론]`. 네 rank 합 `pulls_sent`는 장애 없는 시행 847, 834(pilot 2, 3; 보내는 rank와 받는 rank의 쌍 12 × 간격 100 = 1 200의 약 70%), kill 시행 655–698(pilot 2–5, n 6)이었다 `[측정: rows_mi.py로 다시 셈]` | 9.3절 | `train_pull_count` |
| 장애 없는 학습 모양 | `mi4_train_none` | 데이터 같음, 복원 0, 입력 멈춤 ≤ 15 ms(멈춤 약 5 ms + 멈춤 안 D2H 2.4 ms `[측정: 확인 3]` + 여유) | 5/5 | 9.4, 9.8절 | `train_none_clean` |
| 체크포인트는 RDMA로 | 학습 셀 셋과 mirror 켠 4 KiB 덮어쓰기 셀 다섯(`mi4_none_ow`, `mi4_kill3_ow`, `mi4_kill1_ow`, `mi4_kill3_ckpt_ow`, `mi4_kill2_kill3_ow`) | helper 소켓으로 보낸 이미지와 segment 바이트 0; 체크포인트마다 올리기 시간은 보고 | 모든 시행 | 9.4절 | `store_rdma` |
| 학습 모양에서 둘째 죽음 | `mi4_train_kill2_kill3` | `reimage_after_restore`와 `second_death_restored`의 조건을 학습 모양에서 | ≥ 4/5 | 9.4, 9.6절 | `train_second_death` |

**복원 시간의 두 모드와 보고 규칙**(2026-10-15, DRAFT 중 더함; 분석은 세션 스크래치 `mi_restore_time_modes.md`, 죽음마다의 표
`mi_rt_modes.csv`). pilot 2–4의 죽음 52건(복원 시간이 있는 것 49건)에서 복원 시간이 두 덩어리로 갈렸다 `[측정]`. 빠른 6건(72.2–99.8 ms, 모두 첫 죽음)은
예비 프로세스의 첫 `/proc` 검사(죽음 판정 뒤 4.9–11.2 ms)가 원래 프로세스를 zombie로 보아 'later' 0번에 활성화했고, 느린 46건은 첫 검사가 state R이라
20 ms마다 'later'를 5–10번 답한 뒤 "/proc absent"로 활성화했다. 감지는 52건 모두 FIN, 같은 셀의 빠른 시행과 느린 시행은 같은 체크포인트에서 같은 바이트를
가져왔고, 활성화 뒤 마지막 게시까지는 두 모드가 같았다: 차이는 활성화 관문의 기다림뿐이고 측정 착시가 아니다. 활성화 뒤 부분을 짝의 활성화 줄에서 다시
재면(`post_activate_ms`, 이 작업에서 더한 열) 4 KiB mirror 켬 첫 죽음 24건이 빠른 3건 65.3–70.2 ms, 느린 21건 48.1–70.5 ms다 `[측정: pilot 2–4 원자료에서
rows_mi.py로 다시 셈]`. 관문의 뜻은 18절. 보고 규칙(판정식은 바꾸지 않음):
- 정의는 그대로 둔다: 첫 죽음 판정 줄 → 마지막 생존 rank의 게시 줄.
- 판정은 위 상한으로만 한다(4 KiB ≤ 2 000 ms, 학습 ≤ 1 000 ms). pilot 2–4의 최대는 mirror 켬 294.9 ms, 끔 380.7 ms라 두 모드 모두 통과와 실패를 바꾸지
  않는다.
- 셀마다 n, 최소, 중앙값, 최대와, 'later' 0번(첫 검사 zombie)과 1번 이상의 수, 모드마다의 범위를 따로 보고한다. 평균이나 한 모드의 값 하나를 "복원
  시간"으로 쓰지 않는다.
- 관문 기다림(`activate_ms`, `later_n`, `later_ms`, gin-restore의 rows_rs 열)과 활성화 뒤 부분(`post_activate_ms`, 두 죽음 셀은 `_1`, `_2`; rows_mi.py)은
  보고만 하는 열로 따로 적는다. 셀 사이와 gin-restore와의 비교는 활성화 뒤 부분으로 한다.
- 모드로 제외하지 않는다(원래 프로세스가 끝나는 차례에서 오는 것이고 실패가 아니다; 빠른 6건의 데이터 열은 모두 맞음).

## 4. 범위

**포함.** 9절의 설계(mirror 쓰기, pool, segment와 당기기, 복원 경로, 기존 장치와의 충돌 표), gin-restore 계층 위의 구현(충돌이 닫힌 뒤), 덮어쓰는 시험
workload, 7절의 셀.

**제외.**
- 동시에 둘 이상 죽는 것, 짝과 그 짝(서로의 짝)이 함께 죽는 것, 복원 중의 둘째 죽음: 단일 실패 범위(사용자 결정 5).
- 원격 완료(받는 쪽이 되보낸 신호)만 보고 보낸 버퍼를 다시 쓰는 application: 지원하지 않는다(2026-10-13 사용자 결정, 9.5절의 application 요구).
- 노드 고장, 실제 link down과 flap, 재부팅, 드라이버 재적재.
- NVSHMEM, GIN 밖의 NCCL 통신(gin-restore 4절과 같음).

복원 뒤 되살린 rank가 맡은 rank의 체크포인트와 pool을 다시 세우는 것(전체 이미지 다시 받기, 9.6절)과 그 뒤의 둘째 죽음은 2026-10-13 사용자 결정으로 범위에
넣었다. 둘째 죽음은 첫 복원이 끝나고 보호를 되찾은 뒤의 차례 실패라 단일 실패 범위 안이다.

**학습 모양의 뜻(2026-10-13 사용자 요청).** 실제 PyTorch 학습은 범위 밖이다: 복원을 쓰는 application은 `ncclGinRestoreResume`과 `ncclGinRestoreStep`을 불러야
하고(gin-restore 9.4절), GIN 장치 API로 보내야 하므로 PyTorch의 NCCL backend를 고쳐야 한다. "학습 모양"은 전송의 모양(rank마다 상대 셋에 단계마다 2 MiB,
2 000단계, 신호 둘)과 덮어쓰기 차례(보낸 버퍼를 local 완료 직후 다시 씀)만을 뜻하고, 계산, collective, 실제 gradient 값은 흉내 내지 않는다.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드, NIC, GPU, CUDA | gin-restore와 같다: rain(Quadro RTX 5000), sunny(RTX A4000), ConnectX-6, CUDA 12.8 | gin-restore 5절(이 문서에서 다시 확인하지 않음) |
| 랭크 배치 | 랭크 4개, GPU마다 둘(rain에 0과 2, sunny에 1과 3). 짝은 p xor 1(`gdakiHoldBuddyOf` 4308)이라 rank 3의 짝은 rank 2. rank 3의 예비 프로세스는 sunny GPU의 셋째 프로세스. 둘째 죽음 셀은 rank 2의 예비 프로세스도 rain GPU의 셋째 프로세스로 띄움(rain BAR1에 세 프로세스의 window 등록이 듦: 9.8절 확인 4에서 Free 155 MiB `[측정]`; 실제 바이너리로는 pilot이 BAR1 Free를 다시 봄) | 계획 |
| 라이브러리 | gin-restore `rs` + 9절의 mirror 계층(`mi`). 이 라이브러리와 쓰는 모든 프로그램은 이 계층의 헤더로 빌드 | 구현 전 |
| helper 소켓과 데이터망 | helper 소켓은 관리망 1 GbE의 TCP(사용자가 전함). mirror를 켜면 그 소켓에는 제어 기록과 STATE(항목, rkey 목록)만 싣고, 체크포인트 이미지와 segment는 데이터망(ConnectX-6)의 RDMA로 옮김(9.4절). 호스트끼리 RDMA READ θ 11.9–12.0 GB/s, 30 MiB WRITE 무부하 2.6 ms, 다른 QP의 묶음과 함께 19–24 ms `[측정: 9.8절 확인 3]` | 사용자, 계획 |

이 배치의 짝 규칙에서는 노드를 건너는 put의 mirror가 보내는 rank와 같은 노드의 짝으로 가고(NIC 루프백, 선 위의 바이트는 그대로), 같은 노드 안의 put의
mirror가 선을 건넌다 `[추론: 짝 규칙과 배치]`. 그래서 비용 셀은 재기만 하는 모드의 두 팔(9.7절 재기만 하는 모드 행)로 두 경우를 따로 잰다.

## 6. 변수

- **독립변수.** mirror 켬과 끔(`NCCL_GIN_RESTORE_MIRROR`), 덮어쓰기 workload 켬과 끔(`RS_OVERWRITE`), 학습 모양 모드(`RS_TRAIN`, 9.8절), 장애(rank 3, rank 1 kill, 체크포인트 멈춤 중 kill, rank 2
  kill 뒤 rank 3 kill), put 크기(4 KiB, 32 KiB, 128 KiB), 체크포인트 간격(10, 20, 40단계), lane 크기와 당기기 문턱, checksum 방식(대조 셀).
- **종속변수.** gin-restore의 종속변수 전부(대기 결과, 데이터 비교, 단계 실행 수, 억제 수, 복원 단계별 시각, 입력 멈춤 시간)와 더해서: mirror 쓰기 수와
  바이트, lane마다 segment 채움, 살아 있는 segment 수, 당기기 수, lane 깨짐 수와 까닭, DISARM 수, 짝의 drain 시간과 QUERY_QP 수, FETCH의 segment 바이트와
  시간, 내보내기의 원본 바이트, put 지연과 묶음 대역, pool 바이트, BAR1 Used 앞뒤, 시행마다 QUERY_QP 증가.
- **통제변수.** gin-restore 6절의 hold 프로세스 고정 설정 전부. 더해서: `NCCL_GIN_RESTORE_MIRROR`는 모든 rank가 같음(다르면 9.7절의 Resume 거절 셀만),
  segment 자리 3(`NCCL_GIN_RESTORE_MIRROR_SLOTS`), lane 1 MiB(`NCCL_GIN_RESTORE_MIRROR_LANE`, pilot 자리값), 당기기 50%(`NCCL_GIN_RESTORE_MIRROR_PULL`),
  checksum 끔(대조 셀 밖), 시행마다 프로세스를 새로 띄움. 학습 모양 셀만: QP 감시 50 ms(2026-10-13 사용자 결정; 4 KiB 셀과 회귀는 10 ms 그대로),
  lane 80 MiB(= 2 × 2 MiB × 간격 20), 예비 프로세스의 활성화 기다림 ≥ 120 s(`NCCL_GIN_RESTORE_SPARE_WAIT_MS`).

## 7. 실험 셀, 반복 수, 대조군

DRAFT다(반복 수는 초안, pilot 뒤 고정). 배치와 빌드는 5절, 단계 사이 5 000 µs, 복원 시한 20 000 ms는 gin-restore와 같다. 덮어쓰기 workload(`RS_OVERWRITE=1`,
9.8절)는 받는 rank마다 보내는 칸 하나를 단계마다 다시 쓰고 flush가 돌아온 바로 뒤 그 칸을 단계에 따라 다른 독 값으로 덮는다.

| 셀 | 조건 | 빌드와 반복 수(초안) | 종류 |
|---|---|---|---|
| `mi4_none_ow` | 장애 없음, 덮어쓰기, mirror 켬 | `@mi` 5 | 대조, pool 사용량 |
| `mi4_kill3_ow` | rank 3 SIGKILL(단계 중간), 덮어쓰기, mirror 켬, 예비 프로세스 있음 | `@mi` 10 | 새 셀 |
| `mi4_kill1_ow` | rank 1 kill(같은 GPU의 다른 rank) | `@mi` 5 | 일반성 |
| `mi4_kill3_ckpt_ow` | 체크포인트 입력 멈춤 중 kill(gin-restore의 라이브러리 시험 스위치) | `@mi` 5 | 새 셀 |
| `mi4_train_none` | 학습 모양(9.8절), 장애 없음, mirror 켬 | `@mi` 5 | 대조, pool과 당기기 |
| `mi4_train_kill3` | 학습 모양, rank 3 SIGKILL을 단계 300–1 700 사이의 무작위 단계와 단계 안 지연에(seed는 표 아래 문단) | `@mi` 10 | 새 셀(핵심) |
| `mi4_train_kill2_kill3` | 학습 모양, rank 2 kill(단계 300–900 무작위) 뒤 되살리고, rank 3 kill(단계 1 100–1 700 무작위, 다시 무장 뒤). 예비 프로세스 둘 | `@mi` 5 | 새 셀(둘째 죽음) |
| `mi4_kill2_kill3_ow` | 덮어쓰기, mirror 켬, 단계 600. rank 2(rank 3의 짝)를 단계 200 근처(seed 무작위 180–220)에서 kill하고 되살린 뒤, rank 3을 단계 400 근처(380–420)에서 kill(그 사이 간격 20단계로 열 번의 체크포인트 기회). 예비 프로세스 둘(rank 2와 rank 3) | `@mi` 5 | 새 셀(판정), 9.6절 |
| `mi4_kill3_ow_nomirror` | 덮어쓰기, mirror 끔, checksum 끔(gin-restore 방식) | `@mi` 5 | 음성 대조 |
| `mi4_kill3_ow_sampled` | 덮어쓰기, mirror 끔, checksum 표본 | `@mi` 5 | 음성 대조 |
| `mi4_seg_4k`, `mi4_seg_32k`, `mi4_seg_128k` | rank 3 kill, put 4 KiB(600단계), 32 KiB(200단계), 128 KiB(60단계; 받는 window가 rain BAR1의 window 한도 24 MiB 안), 확정 체크포인트 뒤 15단계째 kill | `@mi` 각 5 | 복원 시간 대 segment |
| `mi4_int_10`, `mi4_int_20`, `mi4_int_40` | 장애 없음, 간격 10, 20, 40단계 | `@mi` 각 3 | pool 대 간격 |
| `mi4_pull_none` | lane 48 KiB(간격 하나에 rank마다 80 KiB를 보냄), 당기기 50%, 장애 없음 | `@mi` 3 | 당기기 |
| `mi4_pull` | 같고 rank 3 kill | `@mi` 5 | 당기기 |
| `mi4_overflow` | lane 2 KiB(put 4 KiB보다 작음), rank 3 kill | `@mi` 5 | DISARM 끝 수단 |
| `mi4_refuse_csum`, `mi4_refuse_mirror1`, `mi4_refuse_sl` | mirror와 checksum 표본을 함께 켬; rank 3만 mirror 끔; rank 3만 segment 자리 수가 다름(`NCCL_GIN_RESTORE_MIRROR_SLOTS` 2, 다른 rank 3) | `@mi` 각 3 | 명시적 오류 |
| gin-restore 회귀(mirror 끔) | gin-restore 7절의 복원과 거절 셀을 이름과 env 그대로: `rs4_none`, `rs4_none_off`, `rs4_kill3`, `rs4_kill3_ckpt`, `rs4_kill1`, `rs4_kill3_nospare`, `rs4_kill3_spareabsent`, `rs4_refuse_symgin`, `rs4_refuse_gintype`, `rs4_refuse_restoreoff1`, `rs4_refuse_nomacro`; gin-remaining 실행기의 회귀 셀 `reg_mr4_none`, `reg_mr4_none_hold`, `reg_rm4_kill3_untimed`, `reg_rm4_kill3_untimed_hold`(gin-restore의 `rs4_kill3@hk` 대조와 비용 셀은 되풀이하지 않음) | `@mi` 그 실험의 n(`rs4_kill3` 10, 거절 셀 각 3, 나머지 각 5) | 회귀 |
| gin-restore 회귀(mirror 켬) | `rs4_none_mion`, `rs4_kill3_mion`(gin-restore의 `rs4_none`, `rs4_kill3`에 mirror 켬, 덮어쓰지 않는 workload) | `@mi` 5 + 5 | 회귀 |
| 비용 가족 mirror | 지표 `lat4k`, `lat256k`, `bw256k`, `lat2m`(2 MiB put), `bw2m`(2 MiB × 8 묶음, window 16 MiB), 노드 둘; 팔 `off`(fail-fast), `on`(로그 켬), `mirror-self`, `mirror-peer`(재기만 하는 모드, 9.7절); gin-restore 9.15.6의 섞기 틀 | `@mip` 팔마다 6 | 비용 |
| fail-fast 기계어 | 매크로 없는 프로그램 넷과 라이브러리 장치 객체를 `rs`와 비교 | 빌드 검사(예측 표 밖, 3절의 뺀 행과 10절 QA; ln3에서 확인함, 12절) | 회귀 |

**seed와 n**(2026-10-15, DRAFT). 무작위 kill은 `run_mi.sh`의 draw가 sha256("gin-mirror|seed|셀|시행|first 또는 second")에서 단계와 단계 안 지연을
뽑는다: `mi4_train_kill3` 단계 300–1 700과 0–8 000 µs, `mi4_train_kill2_kill3` 첫 kill 300–900과 둘째 1 100–1 700(각 0–8 000 µs), `mi4_kill2_kill3_ow`
180–220과 380–420(각 0–4 000 µs). 같은 seed, 셀, 시행이면 같은 kill이다(`selftest_mi.py`가 확인). pilot 1–5는 자리값 `DIE_SEED=mi-v1`로 돌았고 시행
번호가 같으면 kill도 같았다(`mi4_train_kill3` n1은 pilot 2, 3, 5 모두 단계 1 689의 6 085 µs, `mi4_train_kill2_kill3` n1은 pilot 2, 3, 4 모두 496의
5 875 µs와 1 245의 2 999 µs) `[측정: 시행 meta의 die_at, die2_at]`. 그래서 사전 등록 커밋에서 [impl/test/cells_mi.json](impl/test/cells_mi.json)의 본 실행
hold(G1, T1, T2)에 있는 `DIE_SEED`를 pilot에서 쓰지 않은 새 문자열(사전 등록 때 정함; pilot hold P1–P6의 값은 그대로)로 바꿔, 본 실행이 pilot의 kill 지점을
다시 쓰지 않게 한다. 새 문자열은 고정된 cells_mi.json에 있고 그 sha256이 `PREREG.txt`에 있다. 다른 kill 셀은 seed를 쓰지 않는다(gin-restore처럼 실행기가
기록한 PID로 트래픽 중 kill, 확정 체크포인트 뒤 15단계째 kill, 라이브러리의 시험 스위치). n은 위 표의 초안 값이고 cells_mi.json의 G1, G3, T1, T2, G2,
R1, R2, R3과 같다(사전 등록에서 고정).

4 KiB 셀(`mi4_*_ow`, 대조, 회귀)은 gin-restore와 같은 크기의 회귀로 그대로 둔다. mirror를 켠 셀은 단계 맞춤 가져오기와 RDMA 저장소를 지나고, mirror를 끈 셀과
gin-restore 회귀는 지금의 한꺼번에 가져오기와 TCP 저장소를 지난다(9.4절). 둘째 죽음 셀의 둘째 kill은 driver의 단계 kill(`GIN_RS_DIE_AT`)로 하고 체크포인트 멈춤
중 kill 시험 스위치는 쓰지 않는다: 그 스위치는 확정 무장 체크포인트를 누적으로 세어(7914) 복원 뒤 다시 무장하기 전에 터진다(검토).

## 8. 제외 기준과 중단 기준

gin-restore 8절의 규칙을 그대로 쓰고 아래를 더한다(DRAFT).
- **제외(채점에서 빼고 채움).** gin-restore의 제외 전부. 더해서: kill이 모든 lane을 유효하게 만든 첫 확정 체크포인트 전(그때까지는 무장되지 않음); 셀이 정한
  workload 모드(`RS_OVERWRITE`)나 mirror 설정과 다르게 돈 시행; 둘째 죽음 셀에서 첫 kill이 위 제외에 걸린 시행(그 시행 전체). 둘째 kill이 다시 무장보다
  먼저 난 시행은 빼지 않고 조건 불충족으로 센다(3절). smoke와 pilot은 늘 제외.
- **중단(그 hold의 남은 시행을 멈추고 올림).** gin-restore의 STOP 규칙 전부(CUDA 메모리 오류, 새 mlx5 명령 오류나 rain 펌웨어 명령 실패의 증가, 시행 뒤
  남은 프로세스, kv의 설정 오류나 NIC 오류, 아래 QUERY_QP 상한). 더해서: 어느 노드에서든 pool 등록이 실패함(모든 rank의 Resume 거절로 보임; 거절 셀 밖);
  시행 시작 때 노드의 남은 호스트 메모리가 (rank 수 × pool 바이트 + 1 GiB)보다 작음(`run_mi.sh` exit 5, STOP_mem). 이름으로 끄지 않고 실행기가 기록한
  PID만 끈다.
- **rain BAR1 시작 검사(어디서 읽나; 2026-10-15 DRAFT 중 고침).** rain BAR1 Free가 128 MiB보다 작으면 그 hold를 시작하지 않는다(`refused.txt`). 읽는 곳은
  hold 시작 문이다: `hold_mi.sh`가 hold의 첫 시행 전에 읽고, 그때 이 실험의 시험 프로세스는 없다(바로 뒤의 남은 프로세스 검사가 0을 확인하고, 있으면
  STOP_left). pilot 2–5의 hold 15개 앞뒤 스냅숏 30개가 모두 Free 251 MiB였다 `[측정: snap_before-*, snap_after-*]`. 학습 hold(T1, T2)가 시행마다 시작 문에서
  읽는 값(`BAR1_AT_GATE`, 시행 meta의 `bar1_gate_used_mib`, `bar1_gate_free_mib`)은 그 시행의 프로세스 둘이나 셋이 이미 살아 있을 때의 값이라 보고만 하고
  이 검사에 쓰지 않는다. pilot 3–5에서 그 값은 프로세스 둘이면 Free 133 MiB(학습)와 173 MiB(4 KiB), 셋(둘째 죽음 셀, 예비 프로세스 포함)이면 74 MiB(학습)와
  134 MiB(4 KiB)였고, Free 74 MiB였던 학습 둘째 죽음 시행 둘(pilot 3, 4)도 정상으로 끝났다 `[측정: 시행 meta]`.
- **rain QUERY_QP 상한(단위와 값; 2026-10-15 DRAFT 중 고침).** 단위는 시행 하나다: `hold_mi.sh`의 `after_trial`이 시행(비용 hold에서는 비용 실행 하나)이
  끝날 때마다 rain의 펌웨어 명령 셈 QUERY_QP를 읽어 앞 읽기와의 차(그 시행과 앞 시행 뒤의 틈)를 상한과 견준다. 상한은 복원 시행과 비용 실행 50 000,
  gin-remaining 실행기의 회귀 시행 150 000(gin-restore 그대로)이고, 넘으면 STOP_mlx5다(pilot hold는 `qp_over.txt`에 적기만). hold 앞뒤 값은 스냅숏에 남고
  hold 하나의 합은 보고만 한다. 근거 `[측정: 스냅숏 앞뒤의 차, qp_over.txt 없음]`: pilot 2–5의 pilot hold 15개(복원 hold의 시행 80, 비용 실행 120)에
  `qp_over.txt`가 없어 상한을 넘은 시행이 없었다. 시행마다의 값은 상한 밑이면 남지 않아 `[미확인]`이고, hold의 차를 시행 수로 나눈 평균은 P1(4 KiB와 거절
  셀 15시행) 18 155, 18 253, P2(학습 셀 3시행) 27 135, 27 341, P4(4 KiB 14시행과 학습 1) 27 430, P6(`mi4_pull` 5, `mi4_kill3_ow` 1, `mi4_train_kill3` 1;
  hold 합 232 181) 33 169였다. 회귀 시행이 든 P3은 293 864, 297 170(7시행, 그 가운데 회귀 2), P5는 218 341(8시행, 회귀 1). 비용 hold는 20 실행에 370(실행마다
  약 19; 비용 실행에는 QP 감시가 없음). 가장 큰 평균(P6)도 상한의 약 0.66배라 50 000을 그대로 둔다(gin-restore는 pilot의 시행마다 값 22 092–23 608에
  40 000, 약 1.7배를 두었다). 처음 초안의 "학습 셀은 시행마다 약 16 000번 `[추론]`"은 작았다(위 P2).
- **시행 시간 한도(2026-10-15 DRAFT 중 고침).** `run_mi.sh`로 도는 학습 모양 밖의 셀 60 s(`RS_TRIAL_BOUND_S`; pilot 3–5에서 그 시행의 wall 2.0–17.8 s, 가장
  긴 것은 예비 프로세스 기다림 15 000 ms의 `mi4_overflow`), gin-remaining 실행기의 회귀 시행 150 s(`fits 150`; pilot 17.5–17.6 s), 학습 모양 셀 150 s
  (`RS_TRAIN_BOUND_S`; 처음 초안 120 s에, fallback한 학습 시행은 예비 프로세스가 120 s를 기다려 약 125–130 s가 됨을 더함 `[추론]`). pilot 2–5의 학습 시행
  wall은 장애 없음 30.2 s(n 2), rank 3 kill 34.2 s(n 3), 두 죽음 34.6 s(n 3)였다 `[측정: hold 출력의 wall, rows_mi.py로 다시 셈]`(9.8절의 어림 26–29 s와
  처음 이 절의 24–28 s는 짧았다). 학습 셀의 hold는 둘로 나눈다(9.8절: T1 = `mi4_train_none` + `mi4_train_kill3`, T2 = `mi4_train_kill2_kill3`). 시작 검사의
  남은 호스트 메모리는 (pool + 저장소를 가진 프로세스 수) × 약 0.8 GiB + 1 GiB로 본다.

## 9. 설계와 실행 방법

### 9.1 설계 개요

```
 보내는 rank s (GPU)           받는 rank d (GPU)              d의 짝 b (호스트)                    d의 예비 프로세스
 put(d) 하나에 WQE 둘, 둘 다 d의 게이트 안에서:
  ├ (mirror 문맥, b) QP ── WRITE ─────────────────────────▶ pool[d] segment k, lane s
  └ (사용자 문맥 c, d) QP ── WRITE+신호 ─▶ window, 신호 표
 로그 항목(s의 GPU, 64 B): 종류, 대상, 크기, 신호, MIRROR 표시와 lane 안 자리     체크포인트 이미지(멈춤 안 RDMA WRITE로 저장소에)
 s가 flush나 wait로 put의 local 완료를 보면 mirror도 원본을 다 읽음 → application이 원본을 다시 써도 됨
 d의 입력 멈춤마다 s는 d의 segment를 바꿈. d의 체크포인트 K 확정 → segment K 이하를 버림

 d 죽음 → 생존 rank가 d를 붙잡음(지금처럼) → HOLDING(mirror 수, segment 채움)을 b에
          b: 모든 HOLDING 뒤 mirror QP drain과 READ 울타리 → ACTIVATE ──────────────────────▶ FETCH(RDMA READ): 이미지 + segment
 생존 rank마다 STATE: 로그 항목(보낸 단계, MIRROR 항목은 segment 번호), rkey 목록 ──────────▶ 단계 맞춤 가져오기: 내용은 segment,
                                                                                            단계 t+1의 입력을 Step(t) 전에
```

원칙 `[추론]`:
- 내용은 NIC이 쓴다. GPU 스레드는 복사하지 않는다(사용자 결정 5). 보내는 스레드가 더 하는 일은 lane 커서의 원자 더하기, mirror QP의 WQE 하나, 항목 낱말
  하나다.
- mirror는 받는 rank의 실행 수에 닿지 않는다. 다른 QP(mirror 문맥)로 가므로 d로 가는 사용자 QP의 메시지 수, 체크포인트의 절단점, 억제 예산이 그대로다
  (9.2절).
- mirror는 보조 길이다: 어떤 실패도 보내기를 막거나 application, 짝, 다른 rank에 닿지 않고 그 받는 rank의 복원만 끈다(lane 깨짐과 DISARM; 9.3절의 불변식).
- 복원 쪽 기계(붙잡기, REJOIN, 복원 라운드, 억제)는 gin-restore 그대로다. 바뀌는 것은 짝의 활성화 앞 drain, 체크포인트와 FETCH의 길(RDMA), 내보내기와 가져오기다.

### 9.2 두 번 쓰기: QP, WQE, 차례, 완료 세기

**어느 QP로 내나.** 세 길을 견줬다.

| 견줄 것 | (가) 같은 사용자 문맥의 짝 QP (c, b) | (나) mirror 문맥의 짝 QP (cm, b) | (다) 복원 계층이 따로 만든 QP |
|---|---|---|---|
| 받는 rank d의 실행 수 | 그대로 | 그대로 | 그대로 |
| 보내는 rank s를 되살릴 때 (s → b) 통로의 억제 예산 | b의 실행 수 X와 체크포인트 때 P에 mirror가 섞임. 억제는 "프로그램 차례로 앞의 B개"를 세므로(gin-restore 9.7절 5번) b로 가는 put과 b가 짝인 rank로 가는 put이 다른 스레드에서 오면 진짜 put을 빼먹거나 두 번 보냄 `[추론]` | mirror QP는 예산 계산에서 뺌. 사용자 QP의 예산 그대로 | 따로 셈 |
| b의 체크포인트 입력 멈춤 | (c, b) 게이트가 멈춤마다 닫힘 → d로 가는 put이 b의 멈춤을 기다리거나 mirror를 빼먹어 d가 b의 체크포인트마다 DISARM됨 | mirror 문맥을 멈춤에서 빼면 닿지 않음 | 닿지 않음 |
| application의 flush | flush(문맥 c)는 (c, b)를 이미 기다림. flushAsync(peer)와 wait는 아님 | flush와 wait 모두 mirror QP를 따로 기다려야 함 | 같음 |
| 짝 b가 되살아날 때 다시 잇기 | 복원 라운드가 함께 함 | 복원 라운드가 함께 함(rec QP) | 새 길이 필요 |
| QP 감시, 투명 복구 라운드 | 그대로 덮음 | 그대로 덮음 | 덮지 않음, 새 오류 처리 |
| 초기화와 기록 | 바뀜 없음 | QP를 만들기만 하면 바뀜 없음(아래) | QP 생성과 교환이 새로 생김 |
| 자원 | 없음 | rank마다 QP n + 1개(상대 n − 1과 자기 루프 쌍) | 같거나 더 큼 |

(나)를 고른다. (가)는 보내는 rank를 되살릴 때의 정확성과 짝의 체크포인트마다의 DISARM이라는 두 문제를 풀 길이 없다. (다)는 (나)가 공짜로 얻는 감시,
라운드, 복원 라운드를 모두 새로 만들어야 한다.

**mirror 문맥을 만드는 길.** GDAKI 문맥은 지금 사용자 문맥마다 QP 묶음 하나를 만들고 문맥마다 GIN collComm의 allToAll로 QP 정보를 나눈다 `[소스: rs 트리
gin_host_gdaki.cc 16404–16411, 16682–16693]`. mirror 문맥을 같은 길로 만들면 `NCCL_GIN_RESTORE_MIRROR`가 rank마다 다를 때 allToAll 수가 어긋나 멈춘다
`[추론]`. 그래서 mirror QP는 문맥을 만들 때 만들기만 하고(집합 교환 없음, GPU 문맥 배열에 문맥 하나를 더하고 rec QP 목록에 넣음, 자기 루프 쌍은 지금처럼
그 자리에서 이음), QPN과 pool 정보는 설정 합의(`gdakiTsSetup`의 all-gather) 뒤 설치된 helper 소켓으로 쌍마다 한 번 나눈 뒤 잇는다(새 기록 MIRROR_SETUP,
helper 스레드가 뜨기 전). 설정 기록의 policyPad에 mirror 비트를 더하고 모든 rank가 청했고 복원 결정이 "켤 수 있음"일 때만 잇는다. 아니면 mirror QP는
잇지 않고 쓰지 않음으로 표시한다(감시와 라운드에서 빠짐) `[소스: 설정 기록 9531–9536, 결정 9572–9596]`. 초기화 기록에는 바뀜이 없다(9.7절 재생 행).

**WQE 모양.** RDMA WRITE 하나(1 GiB 넘는 put은 DOCA처럼 조각마다 하나). 원격 주소는 pool 안 오프셋(pool MR을 0 기준으로 등록, 9.3절), rkey는 짝 b의 pool
rkey, 원본은 put과 같은 원본 window의 오프셋과 lkey(같은 GIN 보호 영역이라 그대로 쓸 수 있음) `[소스: rsPutHold의 laddr 675]`. mirror 문맥 하나를 모든
사용자 문맥이 나눠 쓰므로 GPU 범위 공유 모드로 낸다(SQ 자리를 원자 연산으로 잡음). s가 곧 b이면(rank 2 → rank 3) mirror 문맥의 자기 루프 QP로 낸다(게이트
없음, hk의 자기 put과 같음) `[소스: rs 트리 16735–16756]`.

**보내는 스레드의 차례**(hold 보내기 함수 `rsPutHold` 627–717 안, 매크로로 빌드한 프로그램만):
1. d로 가는 QP의 게이트 진입, 억제 예산(지금 그대로). 예산이 연산 전체를 덮으면 mirror도 없이 돌아감.
2. mirror 조건: 측 표의 mirror 켬, 내용 있는 put(크기 > 0, 데이터를 냄), d의 mirror 칸이 유효(9.3절). 아니면 3–5를 건너뜀.
3. d의 lane 커서에 바이트(64 B 올림)를 원자 더하기로 잡음. lane을 넘으면 mirror 없이 깨짐 수를 하나 더함.
4. mirror QP의 게이트에 쉬지 않고 한 번 들어감. 열려 있지 않으면(라운드, 짝의 hold, 실패) 깨짐 수를 더하고 mirror 없이 계속. 열려 있으면 pool rkey를 시스템
   범위로 다시 읽고(rkey 바꾸기를 따르려고, gin-restore 9.6절 결정 (나)와 같은 규칙), mirror QP의 메시지 수에 조각 수를 더하고 WRITE를 낸 뒤 나감.
5. 본 put(+신호)를 지금처럼 냄. d의 QP 메시지 수는 지금처럼 본 put만 셈.
6. 로그 항목: mirror를 냈으면 MIRROR 표시와 lane 안 자리(9.5절). 떠남.

mirror를 본 put보다 먼저 내는 것은 mirror WRITE가 일찍 시작하게 하려는 것이고 정확성에는 필요 없다. 신호와의 차례도 필요 없다: 복원은 hold 시작의 게이트
개수 0(모든 mirror가 나갔음)과 짝의 drain(모든 mirror가 짝에서 실행됨)에만 기댄다(9.4절) `[추론]`. putValue(값이 항목에 있음), 신호만, 0바이트 put, get은
mirror하지 않는다.

**완료 세기(억제 장부가 정확하게 남는 까닭).**
- 메시지 수: mirror WRITE는 mirror QP의 측 표 항목(`ncclGinRsQp::msgs`)에만 더한다. d로 가는 사용자 QP의 M(입력 멈춤의 PAUSED), P(절단점의 실행 수), X(죽음
  뒤 실행 수)는 그대로다 → 받는 rank의 실행 수는 mirror 때문에 바뀌지 않는다 `[소스: msgs 1194–1205, rs_log_api.h 28–31]`.
- mirror QP는 입력 멈춤, PAUSED의 QP별 M과 P, drain 확인, 억제 예산에서 뺀다. mirror는 받는 쪽(짝)의 이미지에 들지 않기 때문이다. 누적 실행 수는 다른 QP처럼
  감시의 QUERY_QP가 접는다(짝의 drain이 씀).
- 예비 프로세스(되살린 s)의 가져오기는 mirror QP에 msgs = X만 쓰고 예산은 0이다. 예비 프로세스의 mirror 칸은 각 받는 rank의 다음 입력 멈춤까지 무효라
  재실행 중에 mirror를 내지 않는다. 그 멈춤은 예비 프로세스의 예산과 넣을 입력이 다 쓰인 뒤에만 온다(그동안 남의 멈춤에 BUSY; gin-restore 9.10.7절, 9.4절)
  `[소스: BUSY_SUPPRESS 4897]`.
- local 완료: application이 flush나 wait로 put의 완료를 보면 mirror WRITE도 원본을 다 읽었어야 한다. 공용 flush와 wait 코드는 mirror 문맥을 보지 않으므로(flush는
  그 문맥의 상대 QP만 돎) `[소스: rs 트리 gin_gdaki.h 1704–1791, 1196–1255]`, 매크로 빌드에서만 flush와 wait 끝에 mirror QP를 그때의 색인까지 기다리는 hold
  함수를 부른다. 이 기다림은 쉬지 않는다: 게이트가 닫혔거나 에폭이 바뀌었거나 오류 CQE면 그 짝이 맡은 lane을 깨짐으로 적고 돌아간다(application에는 오류
  없음). wait의 요청 구조체에는 표가 하나뿐이라 mirror의 색인은 wait 때 다시 읽는다(더 오래 기다릴 뿐 일찍 끝나지 않음). 이 기다림은 그 flush나 wait의 시한과
  abort 단어를 따른다(gin-remaining의 시한 flush 꼴): 시한이 끝나면 그 lane을 깨짐으로 하고 application에는 그 flush가 원래 돌려줄 결과를 준다. 쓰지 않음으로
  표시한 mirror QP(9.5절)는 기다리지 않는다. QP마다 넣고 빼는 자리는 9.4절의 표다.

### 9.3 pool: 자리, 크기, 등록, segment, 당기기

**불변식(2026-10-13 사용자 결정).** mirror는 보조 길이다. mirror의 어떤 실패(lane 넘침, 닫힌 게이트, 확인하지 못한 flush, mirror QP의 장애 기록, 자기 루프 오류,
셈 무효)도 그 받는 rank d의 복원만 끈다(lane 깨짐, d의 DISARM). application의 보내기와 완료, 짝 b, 다른 rank의 보호에는 닿지 않는다.

**자리.** 짝 b의 pool은 b가 맡은 rank(짝 규칙에서 보통 하나, 랭크 수가 홀수면 rank 0이 둘)마다 segment 자리 S개 × lane (n − 1)개 × lane 바이트 L이다. lane은
맡은 rank를 뺀 모든 보내는 rank의 몫이고 b 자신의 lane도 있다. segment 번호 k는 자리 k mod S를 쓴다.

**등록.** 호스트 메모리(쪽 정렬)를 b의 GIN 보호 영역(GIN QP와 신호 표의 PD)에 `ibv_reg_mr_iova2`로 0 기준(iova 0) 등록한다: 원격 주소가 pool 안 오프셋이
되어 예비 프로세스의 새 pool에서도 자리가 같고 rkey만 바뀐다. 권한은 local write, remote write, remote read(drain 울타리와 FETCH). relaxed ordering은 켜지 않는다.
`gdakiRegMr`는 GPU 메모리용 dmabuf 길을 먼저 시도하므로 쓰지 않는다 `[소스: 2190–2200]`. 체크포인트 저장소(9.4절)와는 따로 된 MR이다. 등록 때는 문맥을 만들 때(설정
전)이고 MIRROR_SETUP이 설정 끝에 그 rkey를 싣는다. 예비 프로세스는 초기화 재생 때 등록한다(재검토 반영).

**보내는 rank가 알아야 하는 것.** 받는 rank d마다 짝 b = buddy(d)(순수 함수)의 pool rkey. S와 L은 모든 rank가 같아야 하고 Resume이 모아 견주므로(조건 39) 배치는
(맡은 rank 수, S, L, n)으로 정해지고 rkey만 나누면 된다. 설정 끝의 MIRROR_SETUP으로 나누고(9.2절), 되살린 rank의 새 pool rkey는 예비 프로세스의 rkey 목록(pool
종류)으로 준다. 예비 프로세스가 아는 생존 rank의 pool rkey는 화신과 상관없이 늘 STATE의 rkey 목록에서 온다(MIRROR_SETUP은 기록 밖). 그래서 예비 프로세스에서는
Resume 조건 38(짝들의 pool 정보가 옴)을 보지 않는다.

**측 표의 mirror 칸.** 머리의 빈 칸(40–63)에 mirror 켬, mirror 문맥 번호, 칸 배열의 자리. 받는 rank마다 칸 하나(64 B): 유효, pool rkey, segment 번호, 그 segment에서
이 rank lane의 pool 안 시작, L, 커서(장치 원자 더하기), 깨짐 수(장치). 배열이 QP 항목과 고리 사이에 들어가므로 측 표 magic을 바꾼다 `[소스: 측 표 1176–1205]`.

**segment 번호와 바꾸기.** 보내는 rank s는 받는 rank d마다 segment 번호 열을 둔다: d의 입력 멈춤에서 바꿀 때마다 1 더한다. 멈춤에서 s의 helper는(d로 가는 사용자
QP 게이트 홀수, 개수 0) d 칸의 번호, lane 시작, 커서를 NIC으로 읽어 호스트에 적고, 번호 + 1, 새 자리의 lane 시작, 커서 0, 유효를 NIC으로 쓰고 다시 읽은 뒤
짝수 에폭을 게시한다(로그 켬 낱말과 같은 자리) `[소스: PauseRead 10065–10115]`. 호스트는 (d의 체크포인트 번호 → 그 멈춤에서 닫은 segment 번호, 그 절단점의 고리
위치, 채움)을 적고, CKPT_STABLE(K)를 "K의 멈춤에서 닫은 segment 이하를 버림"으로 읽는다. hold가 진행 중인 멈춤을 넘겨받으면 장치의 번호와 커서를 다시 읽는다(9.4절
1번).

**되돌리기와 다시 시작**(2026-10-13 사용자 결정, 검토의 충돌 첫째 (가)와 (나); 첫 초안의 "넷째 자리면 BUSY"는 없앰).
- **되돌리기.** 멈춤이 버려지거나(CKPT_RESUME pad 1, 4887) 그 멈춤이 버텨지지 않아 VOIDED로 끝나면, s는 짝수 에폭을 게시하기 전에 바꾸기 때 읽어 둔 번호, lane
  시작, 커서를 NIC으로 되써 넣고 다시 읽는다. 게이트가 홀수이고 개수 0이라 그 사이 장치 쓰기가 없다. 멈춤 안의 D2H가 실패하면 r이 pad 1로 알려 게시 전에
  되돌린다. 멈춤 밖 WRITE의 실패는 게시 뒤라 아래 다시 시작이 받는다(9.4절).
- **다시 시작.** 게시 뒤에 버려진 체크포인트(다른 rank의 VOIDED로 r이 버림, "no confirmation or upload in time" 8537)는 되돌릴 수 없어 경계가 남는다. 다음 멈춤에서
  넷째 자리가 필요하면 BUSY로 답하지 않고 d를 모두에게 DISARM하고, d의 살아 있는 segment를 모두 버리고, 이 멈춤부터 다시 시작한다. d는 그다음 확정 체크포인트에서
  다시 무장된다: 이 DISARM이 이 멈춤의 PAUSED 뒤에 오므로 `gdakiHoldArm`은 이 멈춤의 확정으로는 무장하지 않는다(4586, 8155; 재검토 반영).

**버리기와 살아 있는 segment.** 멈춤 밖 WRITE가 부하에서도 멈춤 뒤 약 20–25 ms에 끝나 확정이 곧 오므로(`[측정]` 9.8절 확인 3) 멈춤 사이에는 보통 하나,
멈춤부터 확정까지 둘이고, 셋은 확정이 늦거나 버려진 뒤다. 버린 자리를
다시 쓸 때 옛 segment의 늦은 WRITE가 새 내용을 덮지 않는다: (s, b) 사이 mirror QP는 하나이고 RC는 차례대로 실행하며, 투명 복구 라운드의 다시 보내기도 새 보내기보다
먼저다 `[추론]`.

**크기.** L ≥ 보내는 rank 하나가 간격 하나에 d로 보내는 바이트의 2배(pilot이 잼), 최소는 가장 큰 put 하나. 짝마다 pool = 맡은 rank 수 × S × (n − 1) × L. 4 KiB
workload(S 3, n 4, L 1 MiB 자리값)에서 9 MiB, 간격 하나에 lane마다 80 KiB. 학습 모양은 9.8절(L 80 MiB, 720 MiB).

**당기기(동적 간격).** s의 helper가 10 ms마다(`gdakiRsLogPoll` 10225의 걸음) d 칸의 커서를 읽어 L의 문턱(기본 50%)을 넘으면 그 segment에 한 번 CKPT_PULL(d)를
보낸다. d의 다음 `ncclGinRestoreStep`은 간격이 차지 않았어도 체크포인트를 찍는다(`gdakiCkptDue` 4989에 "당겨짐"). 단계 하나가 lane을 넘으면 당기기로 막을 수 없다.
d의 칸이 무효인 동안은 커서가 움직이지 않아 당기기도 없다.

**당겨진 체크포인트가 찍히지 않을 때**(2026-10-15, pilot 3의 결함 E로 정함; DRAFT라 고침, 12절). 위 글은 그 체크포인트가 찍히지 않는 경우(복원이 도는 중
"a restore runs", 생존 rank의 BUSY, 저장소 준비 전, 멈춤 시한)를 정하지 않았고 구현은 당기기를 그 Step에서 써 버렸다. 보내는 rank는 segment마다 한 번만
당기므로 다음 체크포인트는 간격에야 오고, L이 간격 하나의 바이트보다 작은 셀(`mi4_pull`: L 48 KiB, 간격 80 KiB)에서는 그 사이 lane이 넘친다. pilot 3
`mi4_pull`에서 rank 0과 1이 kill 2.2–9.5 ms 전에 받은 당기기를 Step(130)이 "checkpoint 130 not taken: a restore runs"로 써 버렸고, 다음 체크포인트는
143(간격)이었으며 복원 뒤 단계 136부터 생존 rank 사이 lane 넷(0 → 1, 1 → 0, 2 → 0, 2 → 1)이 넘쳤다 `[측정: results/20261015_pilot3/raw/mi4_pull_mi_n1_*;
분석은 세션 스크래치 mi_defect_e.md, 읽기만]`. 정한 규칙:
- 당기기는 그 Step에서 DRAINED가 된 체크포인트에만 쓰인다. 아니면 당기기가 남고 다음 Step에 다시 시도한다(back-off는 간격의 4분의 1이 아니라 1단계).
  남기는 것은 처음 시도 뒤 간격의 절반 번 더까지다: 간격 20이면 시도는 s, s + 1, …, s + 10의 열한 번이고 열한째도 거절되면 쓴다(빌드 ln3, 2026-10-15에
  넓힘, 아래 "pilot 4에서 본 길". ln2는 처음 뒤 4분의 1 번 더, 시도 여섯 번이었고, 이 글은 처음에 그것을 "간격의 4분의 1만큼의 Step까지"라고 적었다). 그
  뒤에는 당기기를 쓰고 지금의 back-off로 돌아간다(오래가는 거절, 예를 들어 application에 이미 알려진 장애나 끝내 준비되지 않는 저장소에서 Step마다 다시 묻지
  않게). 같은 당기기를 다시 꺼낸 것은 요약의 `pulls_taken`에 다시 세지 않고, 남긴 동안 새 CKPT_PULL이 와 같은 꺼냄에 합쳐지면 그 새 당기기는 센다(ln3:
  대기 당기기를 "새로 옴"과 "남김" 비트 둘로 둠; ln2는 합쳐진 새 당기기를 세지 않아 하나 덜 셌다. `pulls_taken`은 보고만 하는 열). 줄은 처음 남길 때 하나("a
  pulled checkpoint at step N did not drain: the pull is kept for the next Step"), 남긴 채 다 쓸 때 하나("... the pull is spent").
  `pulls_taken`의 단위는 받은 당기기가 아니라 새 당기기가 하나 이상 든 꺼냄이다: 여러 보내는 rank의 당기기가 한 꺼냄 앞에 오면 하나로 합쳐진다(라이브러리
  주석의 "pulls_taken counts the CKPT_PULLs taken"도 이 뜻; ln3 독립 리뷰 nit 1; `rows_mi.py` 머리 설명에도 적음). `mi4_train_none` 네 rank의 합이 pilot 2에서 보냄 847 대 꺼냄 460, pilot
  3에서 834 대 458이다 `[측정: results/20261015_pilot{2,3}/raw/mi4_train_none_mi_n1_r{0..3}.log의 "mirror summary" 줄에서 다시 셈]`.
- 되돌리기가 당긴 segment를 되살리면 그 segment에서 한 번 더, 둘째 문턱((문턱 + 100)/2, 기본 75%)에서 당길 수 있다(받는 쪽도 당기기를 남기므로 보조).
  이어지는 BUSY에서 남긴 당기기와 겹치면 시도 빈도는 상한에 묶이지 않는다(18절).
- 폴링: 바로 앞 segment의 burst가 이미 DISARM했고 그 뒤 바꾸기가 한 번 있었으면(열린 segment = burst segment + 1; ln3), 바꾸기가 읽은 열림 값(`brokenOpen`)까지의
  깨짐은 그 burst의 꼬리로 흡수한다(같은 넘침을 두 번 세지 않고 다시 무장이 한 체크포인트 밀리지 않음). 폴링이 보지 못한 깨짐은 지금처럼 DISARM한다. 두 폴링
  사이에 바꾸기가 둘 이상이었으면 가운데 segment의 깨짐을 꼬리와 가를 수 없으므로 흡수하지 않고 DISARM한다(ln2는 이때도 흡수해 가운데 segment의 넘침에
  DISARM이 없을 수 있었다; 닫힌 segment의 깨짐 수는 남아 내보내기 검사가 보므로 복원 데이터는 그때도 지켜졌다 `[소스]`; 독립 리뷰의 nit).

**pilot 4에서 본 길과 상한을 넓힌 까닭**(2026-10-15, 독립 리뷰 고칠 것 F3; 원자료 `results/20261015_pilot4/raw/mi4_pull_mi_n{1..5}_{r0,r1,r2,spare}.log`,
`mi4_train_kill2_kill3_mi_n1_spare.log`에서 다시 셈; 줄 시각은 rain 수신 시각) `[측정]`:
- 당기기가 남은 시행 다섯(`mi4_pull` n1, n2, n4, n5와 `mi4_train_kill2_kill3` n1)에서 남긴 rank는 모두 rank 2, 곧 죽은 rank 3의 짝이 맡은 rank였다(학습
  셀은 앞서 되살린 rank 2). 생존 rank 0, 1에서 남은 당기기는 없었다.
- 당기기의 출처: kill 앞뒤 약 10 ms 안(−9.4 – +8.7 ms)에 rank 0, 1, 또는 죽기 직전의 rank 3이 rank 2로 보낸 CKPT_PULL이다. rank 2는 hold 동안 Step이 없어 그
  당기기를 hold로 거절되는 Step(n2)이나 INJECTED 뒤 첫 Step(n1, n4, n5)에 처음 쓴다.
- n2(길 가): Step(130)이 kill 2.9 ms 뒤 hold로 "a restore runs" 거절 → 남김 → INJECTED 뒤 첫 Step(131)에 찍힘(둘째 시도; 그때는 저장소가 이미 준비됨).
- n1, n4, n5(길 나): rank 2는 INJECTED 뒤 2.7–2.8 ms에 되살린 rank 3에 STORE_REQ(reason=buddy)를 보냈고 "store ready at buddy rank 3"까지 31.0, 30.8, 35.9 ms가
  걸렸다. 그동안 Step이 "the checkpoint store is not ready"로 3, 3, 4번 거절되고 132, 133, 135에 찍혔다(넷째, 넷째, 다섯째 시도).
- 학습 셀: Step(1245) "a restore runs"로 남김, INJECTED 뒤 1246–1248이 저장소 준비 전(요청 → 준비 35.5 ms, slot 36.8 MB), 1249에 찍힘(다섯째 시도).
- 4분의 1 상한(시도 여섯)과의 여유가 n5와 학습 셀에서 한 번이었다. "the pull is spent"는 0줄.
- 왜 준비 전인가 `[소스, 측정]`: 올리는 쪽은 붙잡힌 짝에게 저장소를 청하지 않고(`gdakiStoreUpStep`의 "the buddy not held"; mirror 켬에서 PUBLISHED는
  INJECTED까지 붙잡힌 상태), 그래서 STORE_REQ는 INJECTED 뒤 2.5–3.0 ms에 나간다(pilot 2–4의 다시 청함 40건 가운데 39건; 나머지 하나는 INJECTED가 없는
  pilot 2 `mi4_kill3_ckpt_ow`). 되살린 짝은 새 프로세스라 그 rank의 저장소를 이 첫 요청에서 만든다(`gdakiStoreServe`: 메모리 할당과 0 채우기, MR 등록, 올리기
  QP). 같은 요청이 오래된 짝으로 가면(되살린 rank 3의 첫 요청을 rank 2가 받음) 그 짝이 MR을 가지고 있어 2.6–3.6 ms다(pilot 4 `mi4_pull` n 5).
- 이 다시 청함(STORE_REQ reason=buddy → store ready)은 pilot 2–4의 40건에서 13.2–47.5 ms였다(세 pilot을 합친 범위; slot 15.8–36.8 MB, 가장 긴 47.5 ms는
  pilot 2 `mi4_seg_128k`, slot 32.6 MB; `mi4_pull`의 slot 15.8 MB에서는 7건 15.3–35.9 ms).
- 4 KiB 셀의 Step 간격은 INJECTED 뒤 첫 간격이 11–12 ms, 그 뒤 약 7.3 ms였다(n1, n4, n5). 그러면 4분의 1 상한의 마지막 시도 s + 5는 요청 뒤 약 49 ms이고,
  절반 상한의 s + 10은 약 86 ms다 `[추론: 위 간격으로 셈]`. 47.5 ms가 앞의 것에 거의 닿으므로 상한을 간격의 절반으로 넓혔다(빌드 ln3, `gdakiMiPullKeepOk`의
  상수 하나, 호스트만). 학습 셀(Step 약 11.6 ms)에서는 처음 시도 s 뒤 각각 약 58 ms와 116 ms다.
- 상한을 다 써도 넘침은 아니다: 그때 rank 2 쪽 lane은 쓰이지 않는다. rank 3의 hold 시작이 rank 3으로 가는 mirror QP를 멈추고 ERR로 옮기므로 그동안의
  mirror는 깨짐이 되고(n1, n2, n4, n5의 설계한 깨짐 2줄; n3은 0줄), 복원 라운드는 그 칸을 rank 2의 다음 입력 멈춤까지 무효로 쓴다(9.4절 7번). 그래서 당기기를 쓰면 rank 2의 다음 체크포인트가 간격으로 밀려 설계한 짝 보호 공백(9.6절)이 그만큼
  길어질 뿐이다. 당기기가 없던 n3이 그 경우다: rank 2는 INJECTED(단계 131) 뒤 16 Step 동안(마지막 확정 127의 간격인 147까지) 체크포인트가 없었고, 그
  사이 rank 0, 1에서 rank 2로 가는 CKPT_PULL도 lane 깨짐도 없었다. 다섯 시행 모두 `lane_broken_other` 0, `disarm_other` 0이다. 이 셀의 rank 2는 자기 예비
  프로세스가 없어 처음부터 무장되지 않는다("not armable"), 그래서 공백이 길어져도 잃는 보호가 없다.
- 넓힌 상한의 비용 `[소스, 추론]`: 오래가는 거절에서 시도가 여섯에서 열하나로 는다. 앞의 거절 까닭 다섯(hold, 이미 알린 장애, 재실행 억제가 남음, 저장소
  준비 전, 앞 올리기 진행 중)은 CKPT_PAUSE를 보내기 전에 거절하므로 시도마다 helper 걸음 하나와 "not taken" 줄 하나뿐이고, 멈춤을 보낸 뒤의 BUSY만 시도마다
  다른 rank에 빈 멈춤 라운드 하나를 시킨다(9.7절의 결함 E 행).
- 멈춤 시한 거절의 비용(2026-10-15, ln3 독립 리뷰의 고칠 것 1; 위 글이 빠뜨림) `[소스: ln3 호스트 파일 gin_host_gdaki.cc(md5 35357895) 7416–7419, 14157,
  14163–14164, 14895, 17562–17569]`: 멈춤을 보낸 뒤의 다른 거절 "no PAUSED from every peer within NCCL_GIN_RESTORE_PAUSE_MS"는 helper가 멈춤 시한(기본
  2 000 ms; drain 상한 500 ms보다 작게 주면 500 ms)까지 기다린 뒤에 SKIPPED를 준다. 그동안 application thread는 `gdakiStoreTake`의 `wait_for`(상한 시한 + drain +
  1 000 ms)에 묶인다. 남긴 당기기는 이 거절도 다음 Step에 다시 시도하므로("the pause's bound"), 시한 거절이 이어지면 application이 최대 열한 번(ln2는 여섯 번)
  연달아 약 2 s씩, 모두 약 22 s(ln2 약 12 s) 선다 `[추론]`. 지금 셀에서는 닿지 않는다 `[추론]`: kill은 FIN으로 곧 판정되고, hold 중이거나 억제 중인 상대는
  BUSY로 곧 답한다. 시한 거절에서는 당기기를 남기지 않게 좁힐지는 사용자 결정이다(19절). 한계는 18절.

**끝 수단(DISARM).** 장치가 적은 깨짐(lane 넘침, 닫힌 mirror 게이트, 확인하지 못한 flush)과 helper가 적은 깨짐(mirror QP 장애 기록, 자기 루프 오류, 셈 무효)은
helper의 걸음이 d를 DISARM한다(그 깨짐 뒤 멈춤의 확정 체크포인트까지; `gdakiHoldDisarm` 6991–7010). 내보내기는 hold 시작에서 깨짐 수를 다시 읽어 절단점 뒤 깨짐이
있으면 거절한다.

### 9.4 복원 경로, 단계 맞춤 가져오기, RDMA 저장소

1. **생존 rank s의 hold 시작**(`gdakiHoldStart` 6825–6917; 지금 그대로 d로 가는 사용자 QP와 mirror QP를 멈추고 ERR로): 게이트 개수 0이면 d로 가는 put의 mirror가
   모두 나갔다. s는 NIC으로 mirror QP (cm, b)의 msgs(M_mir)와 d 칸의 segment 번호, 커서, 깨짐 수를 읽는다(hold가 멈춤을 넘겨받았으면 호스트 기록이 아니라 이
   장치 값). 앞 segment들의 (번호, 채움)과 함께 HOLDING(d)의 쓰지 않던 칸에 실어 b에 보낸다 `[소스: 6903, rs_hold_api.h 47–59]`.
2. **짝 b의 drain**: 모든 HOLDING 뒤(`gdakiHoldHoldersComplete` 4770) b는 보내는 rank마다 자기 mirror 응답 QP의 누적 실행 수가 M_mir 이상일 때까지 QUERY_QP로
   기다린다(펌웨어 가드 밖, `NCCL_GIN_RESTORE_DRAIN_MS`와 QUERY_QP 수 한도). 그 QP의 셈이 무효(`gdakiRsExecInvalidate` 10352)면 drain은 거절한다. 자기 lane은 rec
   밖의 자기 루프 응답 QP라 감시가 접지 않으므로 helper가 10 ms 걸음마다 그 rmsn을 읽어 24비트 감기로 누적하고(걸음 사이 메시지는 2^23보다 훨씬 적음; 되살린
   rank는 새 QP라 기준 0부터) drain 때 한 번 더 읽는다. 자기 루프 QP의 오류는 그 lane을 실행이 끝날 때까지 깨짐으로 둔다(라운드가 없음). 그다음 GIN PD의 루프백 쌍으로 pool의 낱말 하나를 READ해
   앞의 posted 쓰기가 닿았음을 확인한다(9.8절 확인 1: 어긋남 0, 울타리 없는 읽기도 0이라 울타리의 필요는 보이지 못함 `[측정]`) `[소스: 10502–10581]`. 깨짐이나 한도 초과면 지금의 fallback. 그다음 ACTIVATE와 활성화
   덩어리(아래).
3. **FETCH**: mirror 켬이면 예비 프로세스가 RDMA READ로 짝의 저장소에서 확정 이미지를, pool에서 K 뒤 segment를 자기 호스트 버퍼로 읽는다(아래 RDMA 저장소). mirror
   끔이면 지금의 TCP FETCH(9027–9153) 그대로. 어느 쪽이든 어느 생존 rank의 STATE보다 먼저다.
4. **STATE**(내보내기 판 2): 항목마다 항목과 보낸 단계(아래), MIRROR 항목은 원본 바이트 대신 segment 번호. 생존 rank는 원본을 읽지 않는다. mirror가 켜진 통로에
   MIRROR 없는 내용 있는 put 항목이 절단점 뒤에 있으면 거절. 머리에 mirror QP의 X, 뒤에 rkey 목록(window, 신호와 카운터 표, pool)을 붙인다. 남은 소켓 전송(STATE,
   활성화 덩어리)은 기록마다 handshake 한도 3 000 ms 안에 드는 크기다(항목 64 B와 단계 8 B, 목록 KiB 단위) `[추론]` `[소스: 10760–10843, rs_log_api.h 219–231]`.
5. **가져오기**: mirror 끔이면 지금 그대로 재실행 전에 한꺼번에(10844–). mirror 켬이면 단계 맞춤(아래). 사용자 QP의 msgs = X, 예산 X − P, 응답 쪽 기준 M은
   그대로. mirror QP는 msgs = X, 예산 0, 응답 쪽 기준 M(뒤에 이 rank가 짝으로서 drain할 때 쓰임).
6. **재실행과 억제**: gin-restore 그대로다.
7. **생존 rank의 복원 라운드**: d로 가는 모든 QP(mirror 문맥 포함)를 다시 잇고 옛 WQE는 실행된 것으로(`U = S`). mirror 켬이면 사용자 문맥 QP의 게이트는 게시
   뒤에도 INJECTED까지 홀수다(아래). 예비 프로세스의 새 pool rkey를 측 표의 해당
   칸에 NIC으로 쓰고(게이트 홀수 동안), 그 칸은 d가 맡은 rank e의 다음 입력 멈춤까지 무효, 호스트의 그 segment 기록을 비운다.
8. **RESTORED 뒤**: e는 되살린 d에게 저장소를 다시 청하고(STORE_REQ), 되살린 d도 자기 짝에게 청한다. 저장소 길은 늘 전체 이미지다(mirror 끔 길은 9.6절의 기반
   지우기). 그 체크포인트의 멈춤에서 lane이 다시 켜지고 확정되면 e는 다시 무장된다.

**mirror QP를 넣고 빼는 자리**(검토 반영; 틀리면 복원이 셈 어긋남으로 거절됨):

| 자리 | mirror QP | 까닭 |
|---|---|---|
| hold 시작의 정지와 X, M 읽기(6880–6891), 복원 라운드(Prepare, 끝점 바꿈, Commit, Baseline, 게시) | 넣음 | 죽은 rank로 가는 QP라 ERR와 다시 잇기가 필요 |
| REJOIN, TOKEN, READY의 QP 목록 | 넣음(QPN은 TOKEN에서, 비교에서는 뺌) | 기록에 mirror QPN이 없음 |
| 가져오기의 msgs와 응답 쪽 기준 | 넣음(예산 0) | 뒤의 drain 셈 |
| 입력 멈춤의 정지, PAUSED의 M과 P, drain 확인 | 뺌 | mirror는 이미지에 들지 않음 |
| 내보내기의 "QP별 항목 메시지 합 = m − M" 검사, 억제 예산 | 뺌 | mirror WRITE에는 로그 항목이 없고, 예비 프로세스는 그동안 mirror를 내지 않음 |

QP 묶음은 둘로 나눈다(재검토 반영): `gdakiRsQpsOfPeer`의 "사용자만"(입력 멈춤 8147, PauseRead 10073, 내보내기 10767의 M과 P)과 "mirror 포함"(hold 시작 6884의 X와
M, 복원 라운드 7375). `gdakiRsExecRead`는 묶음의 한 QP라도 셈이 무효면 거절하므로(10380–10383) 사용자 복원은 사용자 묶음으로 읽고, mirror QP의 셈 무효는 그 lane만
깨짐으로 한다(9.3절 불변식).

**활성화 덩어리와 끝점 갱신**(2026-10-13 사용자 결정): 짝은 ACTIVATE 기록(판 2) 뒤 같은 연결에 (1) 생존 rank마다 (rank, 화신, listen 주소), (2) 확정 이미지의
저장소 자리와 배치, pool의 K 뒤 (segment, lane)마다 자리와 채움, 저장소와 pool의 rkey, (3) 짝이 만든 FETCH QP의 끝점을 보낸다. 예비 프로세스는 답(ACCEPTED) 뒤 자기
FETCH QP의 끝점을 돌려준다. 덩어리가 없거나 깨졌으면 REFUSED(끝 답).
- 주소: 예비 프로세스는 활성화하면 모든 생존 rank의 `pe.addr`를 표로 덮는다. REJOIN(6388–6395)과 뒤의 다시 걸기가 모두 지금 주소를 쓴다(검토 반영). 표는
  활성화 덩어리에만 있으므로 mirror 켬에서만 쓴다. mirror 끔 길(TCP FETCH 9042, REJOIN)은 gin-restore처럼 기록 주소를 쓰고, mirror 끈 작업의 둘째 복원은 범위
  밖이다(공유 인터페이스에서 정함, 12절).
- QPN: 화신이 0보다 큰 생존 rank는 TOKEN의 QPN으로 잇고(지금은 기록과 견줌, 6441), 생존 rank의 REJOIN 검사(3817–3840)는 자기 화신이 0일 때만 QPN을 견준다.
  mirror QP의 QPN은 늘 TOKEN에서 오고 두 비교에서 빠진다.
- rkey: STATE의 rkey 목록을 가져오기 때 그 rank의 칸(window rkey 표, 신호와 카운터 표의 rkey 표, 장치와 호스트 사본, 측 표 mirror 칸의 pool rkey)에 쓴다. 그
  전에 예비 프로세스는 생존 rank로 아무것도 보내지 않는다.
- **기록 재생 길에서 바꾸지 않는 것.** 초기화 재생과 Resume 모음의 재생은 그대로다(bootstrap과 GIN collComm의 대답, 자기 칸 비교와 허용 칸, 기록된 정책과
  policyPad, salt와 nonce, RESET QP, 기록의 `gated`와 `addr`) `[소스: 9537–9568, 9617–9626]`. 화신 0인 생존 rank에는 지금 검사가 모두 남고(REJOIN에 기록된 QPN,
  생존 rank의 비교, TOKEN QPN이 기록과 같음), 새 비교(표의 주소, STATE rkey 목록과 재생 값)는 다르면 WARN 한 줄만 쓰고 기록 값을 쓴다: gin-restore의 결정이 글자
  그대로 같다(검토 반영). pool rkey만은 기록에 없으므로 늘 목록 값이다.

**단계 맞춤 가져오기**(2026-10-13 사용자 결정; mirror 켬 길).
- 까닭: 학습 모양의 받는 고리(R = 4)에 절단점 뒤의 입력을 한꺼번에 쓰면 뒤 단계가 앞 단계를 덮는다(gin-restore 9.7절 3번의 단일 대입).
- 단계 표: 보내는 rank는 `ncclGinRestoreStep(t)`마다 고리의 머리를 이미 적는다(확정 단계 셈). 내보낼 때 항목 위치를 이 (단계, 머리) 쌍과 견주어 항목마다 보낸
  단계를 붙인다(마지막 Step 뒤의 항목은 마지막 + 1). 장치 바뀜 없음. 쌍은 가장 오래 살아 있는 절단점까지 지킨다.
- 넣는 때: Resume 안에서 모든 검사(지금 것과, MIRROR 항목의 segment가 K 뒤이고 (segment, lane, 자리 + 바이트)가 FETCH한 채움 안), 예산, msgs, 기준, rkey 쓰기, 그리고
  단계 K+1의 입력(데이터 CUDA 복사, 신호 더하기 NIC 원자 연산)을 넣는다. 재실행 중 application이 부르는 `ncclGinRestoreStep(t)`는 돌아오기 전에 단계 t+1의 입력을
  넣고 기다린다. 넣을 입력이 다하면 Step은 지금 그대로.
- 새 application 요구 14: "rank의 단계 t 커널은 다른 rank가 단계 t에 낸 put과 신호만 읽고 기다린다." 검사하지 않는다. 단계 표는 요구 7(Step은 그 단계의 커널과
  마지막 flush 뒤, 다음 커널을 띄우기 전에 부름)에 기댄다. mirror에서 3번(단일 대입)은 "단계 t의 입력이
  들어간 자리는 단계 t 커널이 읽기 전까지 다른 쓰기가 없다"로 약해지고 받는 고리는 R ≥ 3이면 된다 `[추론]`.
- **게이트를 INJECTED까지 홀수로**(2026-10-13 사용자 결정, 재검토 충돌 (가)). hold 동안 d로 가는 put은 게이트에서 쉬고 아직 내지 않아 로그에 없다(항목은 낸
  뒤에 씀, 645–715). 그대로 게시 때 풀리면 예비 프로세스의 가져오기보다 먼저 닿아(gin-restore 9.1절 그림, 9.3절 끝의 메모) 받는 고리(R = 4)에서 아직 넣을 칸을
  덮는다. 그래서 mirror 켬에서 생존 rank의 복원 라운드는 게시 때 lbase와 계획을 지금처럼 쓰되, 되살린 rank로 가는 사용자 문맥 QP의 게이트 에폭은 홀수로 둔다(mirror
  문맥 QP는 지금처럼 짝수; 칸이 무효라 쓰이지 않음). 예비 프로세스는 마지막 표시 단계의 입력을 넣은 Step에서(표시 단계가 K+1뿐이면 Resume 끝에서) helper를 통해
  INJECTED(새 helper 기록 38, 예비 프로세스 갈래의 범위; round = 마지막 넣은 단계, pad = 화신)를 모든 생존 rank에 보낸다. 생존 rank는 그것을 받으면 그 게이트에
  짝수 에폭을 쓴다(빈 라운드와 같은 쓰기). 쉬던 put은 그때 나가 아직 읽지 않은 단계의 칸에 닿는다: 넣은 마지막 단계가 t이면 예비 프로세스는 커널 t를 돌거나 그
  앞이고, 쉬던 put은 단계 t 또는 t+1이라 R ≥ 3에서 읽을 칸을 덮지 않는다 `[추론]`.
- **바뀌는 규칙**(gin-restore 9.2절 끝의 메모, 9.10.7절). (1) PUBLISHED의 끝이 RESTORED가 아니라 INJECTED다: RESTORED는 받아 적되(화신, 체크포인트 기록 비우기,
  스스로 DISARM) PUBLISHED → ARMED/OFF의 이동은 INJECTED 때 한다. "RESTORED가 PUBLISHED의 시한을 이김"(Q2)은 INJECTED에 대해 같은 꼴이다. (2) "PUBLISHED에서는
  게이트가 짝수라 장치 대기가 붙잡혀 있지 않으므로 시한에 hold 한도 항이 없다"는 전제가 깨지므로, INJECTED 전 PUBLISHED의 시한은 min(지금 PUBLISHED 시한, D)다.
  D = 게이트가 처음 홀수가 된 때 + `NCCL_GIN_TS_HOLD_MS` − 몫 − 1 000 ms(HELD와 같은 장치 한도). 넘으면 지금처럼 감시 스레드가 상태만 바꾸고 helper가 2ERR 먼저
  거절한다(fallback). INJECTED가 시한 안에 오지 않을 때도 같다. (3) 그 밖(PUBLISHED의 QP 감시, 장애 기록의 fallback, 낡은 기록 검사, RESTORED와 FALLBACK의
  엇갈림)은 그대로다. 쉬는 시간은 hold 시작부터 INJECTED까지(hold와 복원 약 0.4 s + 재실행 약 0.2–0.4 s)이고 `NCCL_GIN_TS_HOLD_MS` 30 s가 이를 묶는다 `[추론]`.
- **4 KiB 셀.** mirror 끈 셀과 gin-restore 회귀는 이 규칙을 지나지 않는다(가져오기가 RESTORED 전에 끝나고 INJECTED가 없음; 지금 규칙 그대로). mirror 켠 4 KiB
  셀은 받는 칸이 단계마다 따로라 데이터에는 영향이 없고 생존 rank의 쉼이 재실행 길이만큼 는다. 복원 시간(마지막 생존 rank의 복원 완료 줄, 게시)은 그대로 재고
  INJECTED 시각을 따로 적는다.
- RESTORED와 helper는 Resume 몫 뒤에 시작한다. 루프백 쌍은 가져오기(application 스레드)와 짝 drain(helper)이 잠금 하나로 나눈다. 넣을 입력이 남은 동안 예비
  프로세스는 억제 예산이 남았을 때처럼 남의 멈춤에 BUSY로 답하고 자기 체크포인트를 찍지 않는다(gin-restore 억제 BUSY의 넓힘).
- FETCH한 segment는 가져오기가 끝날 때까지 호스트에 둔다(학습 모양에서 많아야 약 150 MiB).

**RDMA 체크포인트 저장소**(2026-10-13 사용자 결정; mirror 켬 길, 끔이면 지금의 TCP 길 그대로).
- 저장소: 짝이 맡은 rank마다 호스트 메모리에 자리 둘(확정, 받는 중) × (이미지 바이트 + 덩어리 한도 1 MiB)을 GIN PD에 0 기준, RO 없이 등록한다(pool과 같은 꼴, 따로
  MR). 학습 모양에서 약 2 × 31 MiB.
- 설정과 rkey: 맡긴 rank가 Resume 뒤 이미지 배치를 STORE_REQ(새 helper 기록 50)로 보내고, 짝은 serve 스레드에서 등록하고 올리기 QP를 만들어 STORE_ACK(51: rkey, 자리
  배치, QP 끝점)로 답하고, 두 쪽이 잇는다. 기록 밖. 배치가 바뀌면 다시 청하고 그 사이 체크포인트는 void. STORE_ACK 전에는 무장 표시를 달지 않는다.
- QP: mirror QP는 GPU가 내는 DOCA QP라 호스트가 그 SQ에 내면 장치와 다툰다. 그래서 맡긴 rank → 짝의 호스트 RC QP 하나(GIN PD). rec QP가 아니라 감시, 라운드,
  억제, 누적 실행 수 밖이다.
- 올리기(2026-10-13 사용자 확인: 멈춤 안 D2H, 멈춤 밖 WRITE). 입력 멈춤 안에서(drain과 울타리 뒤, 자기 커널 없음) application 스레드가 window, 신호와 카운터
  표, `ncclGinRestoreRegister` 버퍼를 고정 호스트 버퍼(rank마다 이미지 크기, 학습 모양 30 MiB; GIN PD에 등록)로 D2H 복사하고(30 MiB p50 2.39 ms, 13.1 GB/s `[측정: 확인 3]`)
  덩어리를 붙인 뒤 CKPT_RESUME으로 멈춤을 끝낸다. 그다음 멈춤 밖에서 같은 스레드가 Step 훅의 복사 단계 안에서 그 호스트 버퍼로부터 저장소의 받는 중 자리로 WRITE를
  내고 CQ를 걷는다(helper를 막지 않음; 재검토 반영). Step은 WRITE가 끝난 뒤 돌아오므로 그 rank의 단계가 WRITE 시간만큼 길다(30 MiB WRITE p50 무부하
  2.61–2.64 ms, 다른 QP의 2 MiB × 8 묶음과 함께 19.1–19.4 ms, p99 20.1–24.1 ms; 그동안 올리기는 약 1.4–1.5 GiB/s를 얻음 `[측정: 확인 3]`). NIC이 GPU 메모리를 읽지 않으므로 BAR1과
  GPU 읽기 대역에 닿지 않는다. 장치 사본과 블록 해시는 없다(늘 전체). D2H가 실패하거나 한도를 넘으면 pad 1(생존 rank가 segment 바꾸기를 되돌림, 9.3절). WRITE의
  실패와 한도(초안 500 ms)는 게시 뒤라 그 체크포인트를 버리고 9.3절의 다시 시작 규칙이 받는다. QP 속성 초안: timeout 12(약 17 ms), retry_cnt 7(약 120 ms에 ERR).
  ERR이면 다음 체크포인트 전에 STORE_REQ를 다시 해 새 QP를 잇는다(그 사이 체크포인트는 void).
- 확정: 모든 WRITE의 local 완료 뒤(멈춤 뒤, 부하에서 약 20–25 ms `[측정: 확인 3]`) CKPT_STABLE을 짝에게 먼저 그다음 모두에게(지금 차례). CKPT_STABLE에 (자리, 이미지 바이트, 배치 해시, 덩어리
  바이트)를 실어 짝은 저장소를 CPU로 읽지 않고 확정 자리를 바꾼다. WRITE with immediate는 쓰지 않는다(짝의 RQ와 CQ 걸음이 생기고 얻는 것이 없음).
- 증분을 없앤다. 30 MiB의 D2H 2.39 ms와 호스트에서의 WRITE 무부하 2.6 ms다(`[측정]` 확인 3; 부하에서 WRITE는 19–24 ms로 선을 application과 나눔). 해시가 더 비싸고 받는 고리는 어차피 다 바뀐다. 늘 전체이므로
  복원 뒤 "기반이 확정 이미지가 아님"(9.6절)이 이 길에는 없다.
- FETCH: 짝이 활성화 때 FETCH용 호스트 QP를 만들어 끝점을 덩어리에 싣고, 예비 프로세스가 자기 QP를 그 끝점으로 RTR/RTS로 이은 뒤 자기 끝점을 돌려주고, 짝이
  자기 QP를 RTR/RTS로 이은 뒤 같은 연결로 READY를 보낸다. 예비 프로세스는 READY를 받은 뒤에만 READ를 낸다(한도 handshake 3 000 ms; 없으면 짝의 QP가 RTR 전이라
  READ가 버려져 ACK 시간 초과까지 감; 재검토 반영). 받을 호스트 버퍼(약 270 MiB: 이미지 30 MiB + segment 둘 × lane 셋 × 40 MiB, GIN PD)는 초기화 재생 때 등록한다
  (활성화 뒤 등록은 고정에 시간이 걸려 복원 시간에 든다: 1 082 MiB 호스트 등록 30 ms `[측정: 확인 4]`). 끝나면 두 쪽이 QP를 없앤다. 짝이 쓰는 길보다 READ를 고른 까닭은 생존 rank의 일을 줄이는 것이다(gin-restore 9.1절 원칙).
- 실행 수가 움직이지 않는 까닭: 이 READ는 FETCH QP의 응답 쪽 MSN만 올린다. 억제 예산과 Baseline이 쓰는 누적 실행 수는 rec QP(사용자 문맥과 mirror 문맥)의
  QUERY_QP에서만 접히고(10340–10398, 감시 hook 5481–5490) FETCH QP는 rec 목록에도 측 표에도 없다. gin-restore 18절이 걱정한 것은 예비 프로세스가 생존 rank와 이은
  사용자 QP로 READ하는 길이었다.
- READ와 앞선 WRITE: 짝 NIC의 READ 요청은 같은 NIC이 앞서 낸 posted 쓰기를 앞지르지 않는다(PCIe 차례; 저장소와 pool은 RO 없음) `[추론]`. 9.8절 확인 1에서
  울타리 뒤 읽기와 셋째 QP의 READ 모두 어긋남이 0이었다 `[측정]`. 다만 울타리 없이 곧바로 읽은 값도 0이라 울타리가 필요한지는 보이지 못했다. 울타리는
  설계대로 둔다.

**시간 어림** `[추론]`, 확인 3의 `[측정]` 값으로. 멈춤은 D2H 2.4 ms만큼 늘어 약 8 ms이고, 체크포인트를 찍는 rank의 Step은 멈춤 밖 WRITE만큼 더 길다(무부하
약 2.6 ms, 부하 19–24 ms). FETCH = 이미지 30 MiB + segment(살아 있는 segment는 보통 하나: ≤ 3 lane × 2 MiB × 20단계 = 120 MiB) ≈ 150 MiB를 READ θ
11.9–12.0 GB/s로 13.1–13.3 ms(확인 3의 150 MiB p50). 복원 시간 T = 375.6 ms(gin-restore 중앙값; 277.7–397.2 ms) + drain + FETCH + 이미지 H2D(약 3 ms): 4 KiB
셀은 T0와 거의 같고 학습 모양은 +20–30 ms.

### 9.5 기존 부분이 어떻게 바뀌나

- **로그 고리.** 그대로 필요하다(차례, 대상, 신호, 억제의 메시지 단위). 항목에 표시 비트 0x20(여섯 표시 비트의 마지막 빈 비트) MIRROR와 lane 안 자리(64 B 단위,
  8–11 바이트 낱말; checksum 방식이 켜졌을 때만 checksum)를 둔다 `[소스: 1222–1246]`. segment 번호는 내보낼 때 절단점의 고리 위치로 정한다 `[추론]`.
- **checksum.** mirror에서는 쓰지 않는다(재실행이 원본을 읽지 않음). 코드 길은 그대로 두고(mirror 끈 대조 셀이 씀), 둘을 함께 켜면 Resume이 거절한다(조건 36).
- **"보낸 버퍼를 다시 쓰지 않음" 규칙.** mirror에서는 없앤다(gin-restore 9.7절 12번). 남는 것은 GIN의 원래 계약이다(2026-10-13 사용자 결정, 비용 없음): put의 원본은
  그 put의 local 완료(그 문맥의 flush, 또는 그 상대의 flushAsync와 wait)를 본 뒤에만 다시 쓴다. 매크로 빌드의 이 둘은 mirror WRITE가 원본을 다 읽을 때까지
  기다린다(9.2절). 받는 쪽이 되보낸 신호 같은 원격 완료는 local 완료가 아니다. `ncclGinRestoreStep`의 확정 단계 출력은 그대로 두되 mirror에서는 볼 필요가 없다.
- **application 요구(mirror를 켠 프로세스; gin-restore 9.7절 목록을 이렇게 고쳐 씀).** 1–11번과 13번 그대로(13번의 까닭은 이제 mirror의 lkey가 같은 GIN PD여야
  한다는 것). 3번은 9.4절의 약한 꼴. 12번: "put의 원본은 그 put을 낸 문맥의 flush나 그 상대의 flushAsync와 wait가 돌아온 뒤에만 다시 쓴다. 원격 완료만 보고 다시
  쓰지 않는다." 14번(새): "rank의 단계 t 커널은 다른 rank가 단계 t에 낸 put과 신호만 읽고 기다린다." 라이브러리는 12번과 14번을 검사하지 않는다(18절).
- **mirror QP의 장애 기록**(2026-10-13 사용자 결정, 검토의 충돌 둘째 (가)). helper는 살아 있는 상대의 회복할 수 없는 분류(RETRY_EXC, LOCAL_QP_ERR 밖)의 기록이면
  그 상대를 거절한다(QP 번호 = 상대 + 문맥 × nranks; rs 트리 gin_host_gdaki.cc 9598, 9610–9613). 복원 계층의 기록 hook(gin-restore의 기록 흡수 자리, 5492)은 mirror
  문맥(문맥 번호 = 사용자 문맥 수)의 기록을 분류와 상관없이 흡수해 그 mirror QP가 가는 짝 b가 맡은 rank들의 lane을 깨짐으로 하고 DISARM하며 그 mirror QP를 쓰지
  않음으로 표시한다(측 표 칸 무효, flush와 wait의 mirror 기다림도 건너뜀). b는 거절하지 않고 라운드도 열지 않는다. 그 QP는 b가 되살아나 복원 라운드가 다시 이을 때만
  다시 쓴다(9.6절의 다시 무장). 사용자 QP의 라운드가 그 QP를 함께 다시 이어도 칸이 무효라 쓰지 않는다. 재검토 반영: 흡수는 `gdakiHoldRoute`보다 먼저다(PUBLISHED인
  상대의 QP 기록은 지금 fallback, rs 트리 11019–11024). 흡수할 때 `qs[qi].handled`를 그 기록의 에폭 + 2로 올린다(`gdakiHoldRoute`가 하는 대로, 11014): 그래야
  훑기(`gdakiTsScan`)가 "reported > handled 두 번"으로 그 상대를 거절하지 않는다(10082, 거절 10085). 장치의 mirror 길은 쉬지 않으므로 abandoned, poison,
  DEV_FAILED, sticky를 세우지 않고, 훑기는 mirror QP에서 거절 대신 이 흡수를 한다(10079–10085).
- **rain의 BAR1과 레지스터.** pool과 저장소는 호스트 메모리라 BAR1을 쓰지 않는다. 새 GPU 쪽 상태는 mirror 문맥 QP n + 1개의 고리와 측 표 칸으로 KiB 단위다 `[추론;
  QP 깊이 rs 트리 gin_host_gdaki.cc 90]`. mirror를 켠 프로세스는 원본 window를 NIC 복사 경로에 두 번째로 등록하지 않는다(내보내기가 원본을 읽지 않음, 검토 반영).
  그 등록은 BAR1을 더 쓴다(9.8절 확인 4: 30 MiB를 둘째 PD에 다시 등록하자 BAR1 Free 155 → 125 MiB `[측정]`). 건너뛰므로 rain에서 프로세스마다 약 30 MiB를
  아끼고, 둘째 죽음 셀의 세 프로세스가 들어간다(세 프로세스의 등록 뒤 Free 155 MiB). 시작 검사 128 MiB Free는 그대로 둔다. mirror 부분은 인라인하지 않는 따로 된 함수로 두고 `cuobjdump -res-usage`를 `rs`와 견준다.
- **fail-fast 빌드와 회귀.** mirror 쓰기, flush와 wait 끝의 mirror 기다림은 `NCCL_GIN_RESTORE_DEVICE`로 빌드한 프로그램의 hold 길에만 있다. 매크로 없는 프로그램과
  NCCL 자신의 커널은 바이트까지 같아야 한다. 매크로 빌드의 flush와 wait는 측 표 읽기 하나와 분기 하나가 더해진다(비용 가족의 `ffb-rs-macro` 꼴로 잼). 호스트는
  `NCCL_GIN_RESTORE_MIRROR`가 없으면 mirror 문맥, pool, 저장소, 새 기록을 만들지 않고 가져오기와 체크포인트는 gin-restore의 길 그대로다.

### 9.6 짝 보호 공백과 전체 이미지 (gin-restore 18절; 2026-10-13 사용자 결정으로 범위 안)

**공백.** gin-restore 본 실행에서 되살린 rank는 짝 rank의 증분 체크포인트를 "기반이 확정 이미지가 아님"으로 모두 거절했고 짝 rank의 남은 체크포인트 23–26개가
void였다 `[측정: gin-restore 16절, qa_recount.md 2번; 다시 세지 않음]` `[소스: 5174–5185]`. 까닭은 둘이다 `[소스, 추론; 검토가 확인]`: 짝은 거절한 머리 뒤 블록을
읽지 않고 닫아 큰 이미지의 올리기가 "ack 없음"(8734–8737)으로 끝나 기반이 남고(거절 ack에서만 지움, 8738–8742), 올리는 쪽은 저장 표시의 성공과 상관없이
CKPT_STABLE을 보낸다(8552). rank b가 죽으면 b가 맡던 rank e의 이미지와 pool lane도 함께 사라진다.

**고침.** 저장소 길(mirror 켬)은 늘 전체 이미지라 기반 문제가 없고, e는 RESTORED(b) 뒤 STORE_REQ로 되살린 b의 새 저장소를 받는다. TCP 길(mirror 끔)은 RESTORED(짝)
적용에서 기반을 지우고 OK ack 없이 끝난 모든 올리기 뒤에도 지운다(두 까닭을 모두 덮음). 붙잡기 상태 기계는 그대로다: e는 RESTORED 적용에서 이미 자기를 다음 확정
체크포인트까지 DISARM하고(`gdakiHoldDisarmSelf` 7082), 되살린 b는 억제 예산이나 넣을 입력이 남은 동안 e의 멈춤에 BUSY로 답하므로 전체 이미지 체크포인트는 그 뒤
e의 첫 성공한 멈춤이다. 그 멈춤에서 보내는 rank들이 e의 칸을 새 pool에 다시 켜고(되살린 b는 자기 루프 lane을), 확정되면 e는 다시 ARMED다. 실패하면 void이고 다음
체크포인트가 다시 한다. e가 보호받지 못하는 창은 b의 hold + b의 억제와 가져오기 + 간격 하나 + 올리기 시간이고, 그 안에서 e가 죽는 것은 범위 밖이다.

**둘째 죽음.** `mi4_kill2_kill3_ow`와 `mi4_train_kill2_kill3`가 위 차례와 그 뒤 e = rank 3의 복원을 잰다(둘째 kill은 driver의 단계 kill, 7절).

### 9.7 기존 장치와의 충돌 표

열: 기존 장치 / 무엇이 부딪칠 수 있나 / 이 설계가 피하는 길 / 상태 / 근거(`[소스]`, rs_layer.diff 줄; "rs 트리"는 9절 머리의 트리). "결정"은 2026-10-13 사용자 결정.

| 기존 장치 | 무엇이 부딪칠 수 있나 | 이 설계가 피하는 길 | 상태 | 근거 |
|---|---|---|---|---|
| 붙잡기 상태 기계와 시한(차례마다 늘림, 장치 한도 D) | 짝의 drain과 FETCH가 시간을 더함 | 새 상태 없음. drain은 HOLDING 모음과 ACTIVATE 사이의 helper 걸음(조각), FETCH는 RDMA로 수십 ms라 지금 시한이 덮음. 넘으면 fallback | 닫힘 | 4187–4867, 6593–7754(시작 6825, 활성화 7297, 감시 7683) |
| HOLDING 모음과 짝의 활성화 | HOLDING에 mirror 수, segment 번호와 채움 | 고정 크기 기록의 쓰지 않던 칸. hold가 멈춤을 넘겨받으면 장치의 번호와 커서를 다시 읽음 | 닫힘 | 7121, 4758–4770, rs_hold_api.h 47–59 |
| TCP 체크포인트 올리기와 FETCH(serve 스레드 하나) | 1 GbE에서 학습 모양 이미지를 못 실음 | 결정: mirror 켬이면 RDMA 저장소와 READ(9.4절), 끔이면 TCP 그대로(회귀). serve 스레드는 저장소 등록만 더 함 | 닫힘(결정) | 8886–8900, 8839–8885, 9027–9153 |
| 짝의 체크포인트 저장소 | 등록 수명 | STORE_REQ에 등록, 배치가 바뀌면 다시 등록(그 사이 void), 되살린 짝에는 RESTORED 뒤 새로 청함, 정리 때 QP를 없앤 뒤 MR 해제 | 닫힘 | 5169–, 8783–8838 |
| 저장소 rkey와 QP 끝점 | 기록 밖의 교환 | helper 기록 50, 51(설정 뒤), 예비 프로세스는 활성화 덩어리. 초기화 재생과 무관 | 닫힘 | 9.4절 |
| 올리기 QP와 mirror QP | 호스트가 GPU QP의 SQ에 내면 장치와 다툼; 사용자 QP 장부; 누가 내고 걷나 | 따로 된 호스트 RC QP(GIN PD), rec 밖. 멈춤 밖 WRITE를 고정 호스트 버퍼로부터 application 스레드가 Step 훅의 복사 단계에서 내고 걷음(helper를 막지 않음; 사용자 확인), timeout 12, retry_cnt 7, ERR이면 그 체크포인트를 버리고 다시 STORE_REQ | 닫힘 | 9.4절 |
| FETCH QP와 실행 수 기준, 잇는 차례 | 예비 프로세스의 READ가 짝의 실행 수를 움직임; 짝이 RTR 전이면 READ가 버려짐 | READ는 rec 밖 FETCH QP의 MSN만 올림. 짝이 RTR/RTS 뒤 READY를 보내고 예비 프로세스는 그 뒤에만 READ(한도 3 000 ms). 받는 버퍼는 초기화 재생 때 등록(재검토) | 닫힘 | 10340–10398, 5481–5490 |
| drain 울타리와 저장소 | 짝 CPU나 예비 프로세스가 아직 닿지 않은 쓰기를 읽음 | 짝 CPU는 저장소를 읽지 않음(배치는 CKPT_STABLE에). READ는 같은 NIC의 앞선 posted 쓰기를 앞지르지 않음, RO 없음 | 닫힘 `[측정: 확인 1, 어긋남 0; 울타리 없는 읽기도 0이라 필요는 보이지 못함, 울타리는 둠]` | 9.4절 |
| 올리기 중 죽음 | 받는 중 자리가 반쯤 쓰임; 짝이 죽어 WRITE가 멈춤 | 맡긴 rank의 죽음: 확정 자리 그대로, hold가 멈춤을 넘겨받음(WRITE 중이면 받는 중 자리만 반쯤). 짝의 죽음: 멈춤 밖 WRITE가 한도에서 실패해 그 체크포인트를 버림(게시 뒤라 다시 시작 규칙), RESTORED 뒤 다시 청함. 다른 rank의 죽음: hold 시작이 멈춤을 끝냄(gin-restore) | 닫힘 | 9.3, 9.4절 |
| 입력 멈춤이 길어짐 | 멈춤 안 D2H 2.4 ms(학습 모양, `[측정: 확인 3]`)가 생존 rank의 입력 멈춤에 더해짐; WRITE(부하 19–24 ms `[측정]`)는 멈춤 밖이라 그 rank의 단계에만 더해짐 | 멈춤 한도(4 × `NCCL_GIN_RESTORE_PAUSE_MS`)와 장치 hold 한도보다 훨씬 짧음. 비용은 `train_none_clean`이 잼 | 닫힘 | gin-restore 9.4절 메모 |
| rain BAR1과 고정 메모리 | 저장소, pool, FETCH 버퍼 | 모두 호스트라 BAR1 밖. 고정 메모리는 프로세스마다 pool + 저장소 + D2H 버퍼(학습 모양 약 0.8 GiB), 둘째 죽음 셀의 rain 약 2.7 GiB(예비 프로세스의 FETCH 버퍼 포함). 확인 4에서 812, 812, 1 082 MiB가 모두 등록됨, rain memlock 무제한 `[측정]`; RAM은 8절 시작 검사 | 닫힘 | 9.8절 |
| strict window 강제와 window 보고 | pool과 저장소 MR이 RO로 등록되거나 window로 세어짐 | `RegMrSym`을 거치지 않고 RO 없이 등록, window 보고(16/16) 밖. 올리기 원본은 고정 호스트 버퍼(window MR을 NIC이 읽지 않음) | 닫힘 | 2190–2200, 2621, 11513–11549, 4118– |
| 입력 멈춤, drain 확인, PAUSED의 무장 가능 | mirror QP를 멈춤에 넣으면 짝의 체크포인트마다 막힘 | mirror 문맥을 멈춤, M과 P, drain에서 뺌(9.4절 표). segment 번호 열과 바꾸기, 무장 가능에 "칸 유효, 깨짐 없음, 짝의 pool, 저장소 준비" | 닫힘 | 7932–7997, 8109–8174, 8325–8371, 10065–10115 |
| 버려진 멈춤과 체크포인트가 segment 자리를 채움(검토) | pad 1(4887)과 버림(8537)이 자리를 먹어 셋이 차면 영영 막힘 | 결정 (가)+(나): 게시 전 되돌리기, 넷째가 필요하면 DISARM하고 다 버리고 다시 시작, 다시 무장은 그다음 확정 체크포인트(재검토; 9.3절). BUSY(segment 참) 없음 | 닫힘(결정) | 4887, 8537, 4586, 8155 |
| 송신 쪽 로그 고리, 넘침, DISARM, 확정 단계 | 항목에 pool 자리 | 표시 0x20과 8–11 바이트 낱말(checksum과 함께 켜지 않음), 단계는 (단계, 머리) 쌍에서. lane 깨짐은 넘침과 같은 길 | 닫힘 | 1222–1246, 575–620, 10225–10313 |
| 억제 예산, 누적 실행 수(mod 2^24), msgs | 같은 QP에 섞으면 예산이 mirror를 셈 | mirror는 mirror QP의 msgs에만, 사용자 QP의 M, P, X 그대로. 넣고 빼는 자리는 9.4절 표 | 닫힘 | 521–534, 10340–10469 |
| 무효가 된 mirror QP 셈(검토) | 셈이 무효인 mirror QP로 drain하면 틀린 M_mir 비교 | `gdakiRsExecInvalidate`된 mirror QP가 있으면 그 lane의 drain이 거절(그 받는 rank의 복원만 꺼짐) | 닫힘 | 10352 |
| QP 묶음 둘(재검토) | `gdakiRsExecRead`가 묶음의 한 QP라도 무효면 거절해 mirror 셈 하나가 사용자 복원을 막음 | `gdakiRsQpsOfPeer`를 "사용자만"(멈춤, PauseRead, 내보내기)과 "mirror 포함"(hold 시작, 복원 라운드)으로 나눔(9.4절) | 닫힘 | 10380–10383, 8147, 6884, 7375, 10073, 10767 |
| 단계 맞춤 가져오기 대 hold 동안 게이트에서 쉰 생존 rank의 put(재검토) | 쉰 put은 로그에 없고 생존 rank의 게시 때 풀려 예비 프로세스의 가져오기보다 먼저 닿음. 학습 모양 R = 4에서 아직 넣을 칸을 덮어 `train_data_equal`이 틀림 | 결정 (가): mirror 켬이면 게시 뒤에도 되살린 rank로 가는 사용자 QP 게이트를 INJECTED(기록 38)까지 홀수(9.4절) | 닫힘(결정) | 645–715; gin-restore 9.1, 9.3절 끝의 메모, 9.10.7절 |
| PUBLISHED의 전제와 시한(gin-restore 9.2절 끝의 메모, 9.10.7절) | INJECTED 전 게이트가 홀수라 장치 대기가 붙잡혀 있음; RESTORED 뒤 상태 이동 | 결정에 따름: PUBLISHED는 INJECTED에 끝남, 그 전 시한 min(지금, D), 감시 스레드는 상태만, helper가 2ERR 먼저 거절. HOLD_MS 30 s가 쉼을 묶음. mirror 끈 길은 그대로 | 닫힘(결정) | 6593–7754, 7039–7083, 7683 |
| 복원 라운드(Prepare, 끝점 바꿈, Commit, Baseline, rkey 바꿈, 게시) | mirror QP와 pool rkey | mirror QP는 rec QP라 함께 다룸. 새 pool rkey는 rkey 목록으로, 게이트 홀수 동안 측 표에 NIC으로 씀 | 닫힘 | 7359–7413, 6054–, 10715–10759 |
| 살아 있는 상대와의 투명 복구 라운드 | mirror QP의 다시 보내기가 원본을 다시 읽음 | 다시 보내기는 새 보내기보다 먼저. 원본이 이미 바뀌었을 수 있는 경우는 flush가 확인 못 한 경우뿐이고 그때 lane은 깨짐 | 닫힘 | 6529–6547 |
| 장치 게이트 | b의 게이트에서 쉬면 d로의 보내기가 멈춤 | mirror 게이트는 쉬지 않는 한 번 들어가기. 남는 결합은 mirror QP의 SQ 자리 기다림 | 닫힘 | 627–717; rs 트리 gin_gdaki.h 303–336 |
| 장치 flush, flushAsync, wait | application의 flush가 mirror를 기다리지 않음 | 매크로 빌드만 끝에 mirror 기다림(쉬지 않음, 그 flush의 시한과 abort 단어를 따름, 실패는 깨짐, 쓰지 않는 QP는 건너뜀) | 닫힘 | rs 트리 gin_gdaki.h 1196–1255, 1601–, 1704–1791 |
| 원격 완료만 보고 원본을 다시 쓰는 application | mirror가 아직 안 읽음 | 결정 (가): local 완료 뒤에만 다시 씀(9.5절 12번) | 닫힘(결정) | 9.5절 |
| 장치 오류 분류와 sticky 오류 | mirror QP 오류가 application의 sticky나 flush 실패가 됨 | mirror 길은 mirror 문맥 번호로 보고(그 sticky는 application이 읽지 않음), 실패를 돌려주지 않음 | 닫힘 | rs 트리 gin_gdaki.h 1504–1510, 2047 |
| helper의 장애 기록 처리(검토) | mirror QP의 회복 못 하는 분류 기록이 짝 b 전체를 거절해 사용자 put이 실패 | 결정 (가): 복원 계층의 기록 hook이 mirror 문맥 기록을 분류와 상관없이 흡수, lane 깨짐 + DISARM + 그 QP를 쓰지 않음. b는 거절하지 않음. 흡수는 `gdakiHoldRoute` 앞, `handled`를 올려 훑기의 거절을 막고, 훑기는 mirror QP를 거절하지 않음(재검토; 9.5절) | 닫힘(결정) | rs 트리 gin_host_gdaki.cc 9598, 9610–9613, 10079–10085, 11014, 11019–11024; 5492 |
| 측 표 포인터의 게시 | mirror 칸이 게시 뒤 바뀜 | 머리의 mirror 켬, 문맥 번호, 칸 자리는 게시 전에 씀. 칸의 값은 그 뒤 멈춤에서만 NIC으로 | 닫힘 | 9693–9812, 9954–9997, 507 |
| Resume 합의(지역 판정 1–33과 모음) | 새 조건 | 34 mirror를 청했으나 합의가 mirror를 껐음, 35 pool 등록 실패, 36 checksum과 함께, 37 L이 0이거나 64의 배수가 아니거나 pool이 한도를 넘음, 38 짝들의 pool 정보가 오지 않았거나 mirror QP를 잇지 못함(예비 프로세스는 보지 않음), 39 S와 L이 rank 사이에서 다름, 40 사용자 문맥 수 + 1 > 64. 모음: mirror 비트가 다름 | 닫힘 | 2780–2838, 2915– |
| 설정 all-gather와 대칭 전제, 설정 때 MSN 기준 | allToAll 수가 rank마다 다르면 멈춤; mirror QP는 그때 RESET | mirror QP는 만들기만, 합의 뒤 helper 소켓으로 잇고 이은 뒤 기준. 합의가 끄면 쓰지 않음 | 닫힘 | 9495–9677, 9518–9530, rs 트리 16682–16693 |
| GIN PD의 루프백 QP 쌍 | 가져오기와 짝 drain 울타리가 함께 씀 | 잠금 하나로 나눔(단계 맞춤 가져오기는 helper 뒤에도 돎) | 닫힘 | 10502–10703 |
| 단계 맞춤 가져오기의 때 | 지금은 helper와 RESTORED 전에 모두 넣음 | 결정: Resume 몫(검사, 예산, rkey, 단계 K+1) 뒤 RESTORED와 helper, 나머지는 Step마다. 넣을 입력이 남은 동안 BUSY와 체크포인트 없음 | 닫힘(결정) | 10844–, 11119– |
| 받는 쪽 단일 대입과 학습 모양의 받는 고리 | 한꺼번에 넣으면 뒤 단계가 앞 단계를 덮음(R = 4) | 결정: 단계 맞춤으로 R ≥ 3. 요구 14 "단계 t 커널은 단계 t의 put만 읽음"(검사 안 함). 게이트에서 쉰 생존 rank의 put은 INJECTED 뒤에 나가 겹치지 않음(아래 행; 처음 적은 "살아 있는 put은 kd+2부터"는 틀린 추론이라 고침) | 닫힘(결정) | gin-restore 9.7절 3번 |
| 단계 표의 출처 | 항목에 단계가 없음 | 보내는 쪽 Step의 (단계, 머리) 쌍에서 내보낼 때 붙임, 장치 바뀜 없음 | 닫힘 | gin-restore 9.4절 확정 단계 |
| NIC 복사 경로(원본 window의 두 번째 등록) | 원본 읽기, BAR1 두 배일 수 있음 | mirror 켠 프로세스는 그 등록을 건너뜀(내보내기가 원본을 읽지 않음). 끈 셀은 그대로 | 닫힘 `[측정: 확인 4, 둘째 PD 등록이 BAR1 +30 MiB; 건너뛰어 아낌]` | 10760–10843 |
| 예비 프로세스의 초기화 재생과 기록 | 기록에 없는 mirror QPN, pool rkey, 앞서 되살린 rank의 끝점 | 결정: 활성화 덩어리의 주소 표로 모든 `pe.addr`를 덮음(REJOIN, TCP FETCH 9042, 다시 걸기), 화신 > 0은 TOKEN QPN, pool rkey는 늘 STATE 목록. 화신 0의 새 비교는 WARN만 | 닫힘(결정) | 9537–9568, 6372, 6388–6395, 6441, 3817–3840, 9042 |
| gpu-detect의 QP 감시와 rain QUERY_QP 상한 | mirror QP가 감시를 늘림; 긴 학습 시행 | rec QP라 감시. 결정: 학습 셀만 50 ms(무장 조건은 "> 0", Resume 조건 19; 감기 한도 2^23은 QP마다 50 ms에 10개 안팎이라 멂), 시행마다 약 16 000번 | 닫힘(결정) | 2812, 5481–5490, gin-restore 9.10.4절 |
| 자기 루프 lane | 자기 루프 QP는 rec 밖이라 감시, 라운드, 누적 셈이 없음 | helper가 멈춤마다 그 응답 QP의 rmsn을 읽어 누적, drain 때 다시 읽음. 오류는 그 lane을 실행 끝까지 깨짐 | 닫힘 `[추론]` | rs 트리 16697–16756 |
| helper 기록 종류와 미룸 | 새 종류 | 48 MIRROR_SETUP, 49 CKPT_PULL, 50 STORE_REQ, 51 STORE_ACK(호스트 갈래 범위 밖의 빈 번호), 38 INJECTED(예비 프로세스 갈래 범위 32–47). 11–63은 지금 규칙이 덮음 | 닫힘 | rs_hold_api.h 39–43, 67–75 |
| 남은 소켓 전송 | 1 GbE에서 큰 기록 | STATE와 활성화 덩어리는 KiB 단위라 기록마다 handshake 한도 3 000 ms 안(검토 반영) | 닫힘 | rs_ckpt_api.h 54–55 |
| 재기만 하는 모드와 비용 팔 | Resume 없이 mirror를 잼 | MIRROR_SETUP은 이 모드에도 있음. `NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR`(0, self, peer). 두 팔이 실제 비용을 위아래로 묶음(3절) | 닫힘 | 2142–2147, 9732–9858 |
| checksum | 같은 항목 낱말 | mirror와 함께 켜면 Resume 거절(조건 36), 코드 그대로 | 닫힘(가정 유지) | 1222–1246, 3341 |
| 체크포인트 멈춤 중 kill 시험 스위치(검토) | 확정 무장 체크포인트를 누적으로 세어 복원 뒤 다시 무장 전에 터짐 | 둘째 죽음 셀에서 쓰지 않음, driver의 단계 kill(7절) | 닫힘 | 7914 |
| fail-fast 기계어, 회귀 셀 | 장치 코드 변경; 매크로 빌드 flush와 wait의 읽기와 분기 | mirror 길은 모두 매크로 안. mirror 끔은 gin-restore 길 그대로. 매크로 빌드 비용은 다시 잼 | 닫힘(검사) | gin-restore 9.9절 끝의 메모 |
| 정리와 해제 | 늦은 mirror 쓰기, 저장소 WRITE | mirror, 올리기, FETCH QP를 없앤 뒤 MR 해제, 그 뒤 메모리 해제 | 닫힘 | 2551–2557, 7744– |
| mirror 문맥 하나를 모든 사용자 문맥이 나눔 | EXCLUSIVE, CTA 공유 모드로는 못 냄 | GPU 범위 공유 모드 | 닫힘(가정 유지) | rs 트리 gin_gdaki.h 1804–1815 |
| 복원 뒤 짝 보호 공백, RESTORED 적용 | 되살린 짝에 이미지와 pool이 없음 | 결정: 저장소 길은 늘 전체 이미지와 STORE_REQ, TCP 길은 기반 지우기(두 까닭), 다시 무장은 지금 규칙(9.6절) | 닫힘(결정) | 5183–5195, 8552, 8697–8742, 7039–7083 |
| 계보: 상태 조건(HELD만, 거절된 rank에 FAIL, PUBLISHED류, 무장 조건) | 국면이 HELD와 TIMED_OUT_HELD, COMMITTING과 PUBLISHED를 지워 TIMED_OUT_HELD에서 ACTIVATE나 REJOIN 받아들임이 생김(검토가 찾음) | 계보는 화신 비교만 바꾸고 상태 조건은 그대로(9.9절 규칙 표의 열) | 닫힘 | H:9213–9218, 13264, 13411, 12578–12581(9.9절의 `H:`) |
| 계보: 저장소 요청 버림 | 입력 셋(거절 여부, 칸 화신, known)을 따로 읽어 출처를 잘못 고를 수 있음(결함 A) | CURRENT만 serve; FUTURE와 CANCELLED만 지금과 다름(둘 다 닿지 않음) | 닫힘 | H:15952–15959, 16535–16549 |
| 계보: serve 끝의 답, STORE_ACK | 죽을 때 serve 중이던 요청의 답이 새 프로세스의 소켓으로; 받는 쪽은 seq만 봄 | 보내기 직전에 요청 화신을 다시 가르고 CURRENT만 보냄, wire 그대로 | 닫힘(결정 2026-10-15 (나)) | H:16620–16647, 15640 |
| 계보: REJOIN 받아들임 | HELD, known + 1, 거절된 rank에 FAIL, 단계 REJOIN, 받아들인 뒤 H:13421 | 상태 조건 그대로 + FUTURE이고 x = dead + 1 + 받아들임 순간의 park 검사 | 닫힘 | H:4600, 9213–9227, 13411–13421 |
| 계보: hold 칸의 수명 | 승격까지 죽은 화신, known은 REJOIN에서 | 두 출처 그대로, 국면으로 읽음; H:13421은 BAD 판정(fallback) | 닫힘 | H:5571–5960 |
| 계보: 예비 프로세스의 생존 rank 칸 | OFF(0)으로 남아 known과 어긋남(BAD); 다시 무장된 rank의 둘째 hold에서 짝의 세기가 차지 않음 | REJOIN_ACK에서 CAS OFF(0) → OFF(그 rank의 화신), classify와 한 커밋 | 닫힘 | H:5579, 9845–9850, 12853, 6058–6073 |
| 계보: 활성화와 'later' | 죽은 화신마다 차례, 20 ms 다시 묻기, 답은 magic만 봄 | 차례 그대로; 답의 되울림(rank, 화신 = dead + 1)과 등록 화신 = dead 검사를 더함 | 닫힘 | H:13260–13345, 9599, 9680–9740 |
| 계보: 체크포인트 무장, 되살린 rank는 무장 안 됨 | 예비 주소가 없으면 무장 표시 없음; 승격 뒤 OFF | 같음; 다시 무장은 설계만(9.9절) | 닫힘(결정 2026-10-15 (가)) | H:14581, 15278 |
| 계보: segment와 세대 | INJECTED에서 닫힌 segment를 버리고 hold 끝에서 절단점 표를 비움 | 같음 | 닫힘 | H:7233–7247, 14641–14645 |
| 계보: 저장소 세대와 소켓 세대 | 짝 화신과 짝지어 씀 | 같음 | 닫힘 | H:16300, 16424, 16733 |
| 계보: FETCH, mirror 켬 | 활성화 차례마다 QP, ACCEPTED 뒤에만, READY 뒤 기다림 스레드 | 같음 | 닫힘 | H:20313–20326, 20643–20652 |
| 계보: FETCH와 UPLOAD, mirror 끔(TCP) | 체크포인트 번호만 봄; fallback 뒤 예비 프로세스에 이미지를 줄 수 있음 | 그대로(그 예비 프로세스의 REJOIN에 거절된 생존 rank가 FAIL); 틈은 18절 | 닫힘(결정 2026-10-15 (가)) | H:14832–14945, 9213–9216 |
| 계보: mirror lane의 맡은 rank 뜻(9.6절) | 짝 b가 붙잡히면 b가 맡은 rank 쪽 lane이 깨지고 DISARM | 같음("그 lane은 b의 화신이 CURRENT일 때만 유효"로 설명), 코드와 줄 그대로 | 닫힘 | H:22233–22250 |
| 계보: 둘째 복원의 끝점 표 | 표 화신 = 짝의 known | 표 화신 = view.cur(같은 값) | 닫힘 | H:20530–20541, 8682, 8700 |
| 계보: 재연결 펜싱 | known = 0이거나 pad = known | view.cur와 견줌(같은 결과; ENDED도 cur와 견줌) | 닫힘 | H:9110–9114 |
| 계보: 시험 스위치 | 확정 무장 체크포인트 누적 수 | 그대로; 둘째 죽음 셀에서 쓰지 않음 | 닫힘 | H:13917–13919 |
| 계보: 채점기 열 | 줄 글자로 셈 | 그대로; 새 열 `lineage_warn`(`GIN/LN` 줄 수, 0이어야) | 닫힘 | impl/test/rows_mi.py |
| 결함 E 고침: 남긴 당기기 대 체크포인트 back-off(간격의 4분의 1, gin-restore) | 남긴 동안 back-off를 1단계로 덮어 거절이 이어지면 Step마다 체크포인트를 물음 | 남긴 동안만 `retryAtStep = step + 1`, 쓴 뒤(DRAINED이거나 상한)에는 `gdakiCkptTake`, `gdakiStoreTake`의 4분의 1 back-off가 그대로 남음. 상한은 처음 시도 뒤 간격의 절반 번(빌드 ln3; ln2는 4분의 1, 9.3절) | 닫힘(2026-10-15) | `ncclGinRestoreStep`, `gdakiMiPullAfterStep`, `gdakiMiPullKeepOk`(9.3절) |
| 결함 E 고침: 남긴 당기기 대 체크포인트 거절 까닭(hold의 "a restore runs", 이미 알린 장애, 재실행 억제가 남음, 저장소 준비 전, 앞 올리기 진행 중; 멈춤을 보낸 뒤의 BUSY와 멈춤 시한 "no PAUSED from every peer within NCCL_GIN_RESTORE_PAUSE_MS") | 다시 묻는 시도마다 다른 rank에 비용이 듦; 멈춤 시한 거절은 시도마다 application thread를 시한만큼 세움 | 앞의 다섯은 helper가 CKPT_PAUSE를 보내기 전에 거절하므로 다른 rank의 멈춤 비용이 없음(시도마다 helper 걸음 하나와 "not taken" 줄 하나). BUSY만 시도마다 다른 rank에 빈 멈춤 라운드 하나. hold 동안 생존 rank의 Step은 멈추므로 "a restore runs"는 INJECTED 뒤 첫 Step에서 풀림(pilot 4 `mi4_pull` n2). 멈춤 시한 거절(2026-10-15 이 행에 더함, ln3 독립 리뷰의 고칠 것 1): helper가 시한(기본 2 000 ms; drain 상한 500 ms보다 작게 주면 500 ms)까지 기다린 뒤 SKIPPED를 주고, 그동안 application thread는 `gdakiStoreTake`의 기다림(시한 + drain + 1 000 ms)에 묶임. 남긴 당기기는 이 거절도 다음 Step에 다시 물으므로 이어지면 최대 열한 번(ln2는 여섯 번) 약 2 s씩, 모두 약 22 s 섬 `[추론]`. 지금 셀에서는 닿지 않음 `[추론]`: kill은 FIN으로 곧 판정되고 hold 중이거나 억제 중인 상대는 BUSY로 곧 답함(9.3절) | 다섯과 BUSY는 닫힘(2026-10-15). 멈춤 시한 거절은 사용자 결정 대기(19절): 시한 거절에서는 당기기를 남기지 않게 좁히면 라이브러리 변경이라 충돌 표 행과 독립 리뷰가 먼저(사전 등록 태그 전), 그대로 두면 18절의 한계로 닫음 | `gdakiCkptInitStep` IDLE의 거절 차례 `[소스]`; 멈춤 시한은 ln3 호스트 파일 `gin_host_gdaki.cc`(md5 `35357895`) 7416–7419, 14157, 14163–14164, 14895, 17562–17569 `[소스]`; pilot 4 `[측정]` |
| 결함 E 고침: 남긴 당기기 대 짝이 되살아난 뒤의 저장소 다시 청함 | 죽은 rank의 짝이 맡은 rank e는 INJECTED 뒤에야 STORE_REQ를 보내고(PUBLISHED는 INJECTED까지 붙잡힌 상태라 올리는 쪽이 청하지 않음) 새 프로세스가 저장소를 처음 만들어 답할 때까지 "the checkpoint store is not ready"로 거절됨(pilot 2–4에서 요청 → 준비 13.2–47.5 ms, 40건). 상한이 그보다 짧으면 당기기를 씀 | 상한을 간격의 절반으로(ln3; 4 KiB 셀의 걸음에서 요청 뒤 약 86 ms까지 덮음, 9.3절). 그 사이 e 쪽 lane은 짝의 hold부터 e의 다음 입력 멈춤까지 무효라(9.4절 7번) 넘치지 않음: 당기기를 써도 설계한 짝 보호 공백(9.6절)이 e의 간격 체크포인트까지 길어질 뿐 | 닫힘(2026-10-15) | `gdakiStoreUpStep`의 "buddy not held", `gdakiStoreServe`의 첫 MR `[소스]`; pilot 4 `mi4_pull` n3(당기기 없이 INJECTED 뒤 16 Step, 깨짐 0) `[측정]` |
| 결함 E 고침: 폴링 흡수 대 새 segment의 진짜 넘침 | 바꾸기 뒤 앞 burst의 꼬리를 흡수하다 새 segment의 넘침을 숨김 | 흡수는 바꾸기가 읽은 열림 값(`brokenOpen`)까지만, 그 뒤 깨짐은 DISARM. ln3부터 열린 segment가 burst segment 바로 다음일 때만 흡수: 두 폴링 사이 바꾸기가 둘 이상이면 가운데 segment의 깨짐을 꼬리와 가를 수 없어 흡수하지 않고 DISARM(ln2는 흡수해 가운데 segment의 넘침을 놓칠 수 있었음, 리뷰 nit) | 닫힘(2026-10-15) | `gdakiMiPollStep`, 단위 장면 10 |
| 결함 E 고침: 폴링 흡수 대 DISARM과 다시 무장 | 같은 넘침을 두 번 세면 DISARM이 두 번이고 다시 무장이 체크포인트 하나 밀림 | 바꾸기 한 번이면 흡수가 막음. 바꾸기 둘 이상이면 DISARM 한 번 더(보수적, 18절) | 닫힘(2026-10-15) | 같음 |
| 결함 E 고침 1b(되돌린 segment에서 75%에 한 번 더) 대 segment마다 한 번 당기기, 되돌리기, 3자리 제한 | 되돌리기마다 당기기가 늘거나 자리를 더 씀 | 되돌린 segment를 이미 당겼을 때만 둘째 문턱에서 한 번. 되돌리기는 segment 목록을 바꾸기 전 사본으로 되돌리므로 자리를 쓰지 않고, 더한 당기기는 버려진 체크포인트를 대신할 뿐. 남긴 당기기와 겹친 이어지는 BUSY에서는 시도 빈도가 상한에 묶이지 않음(18절) | 닫힘(한계는 18절) | `gdakiMiPollRolledBack`, `gdakiMiLedgerRolledBack` |
| 결함 E 고침: 요약의 `pulls_taken` 대 채점기 열 | 다시 꺼낸 당기기를 다시 세면 열이 부풂; 남긴 당기기에 새 CKPT_PULL이 합쳐지면 하나 덜 셈(ln2) | 남긴 당기기는 처음 꺼낼 때만, 새 CKPT_PULL이 든 꺼냄은 셈(ln3: 대기 당기기를 비트 둘로). 예측은 `pulls_sent`만 읽고 `pulls_taken`은 보고만 | 닫힘(2026-10-15) | `gdakiMiPullTake`, `gdakiMiPullTakeCounts`; predictions_mi.csv |

**결정으로 닫은 충돌**(모두 2026-10-13, 메인 세션이 전함): (1) 원격 완료 → local 완료 규칙(9.5절); (2) 복원 뒤 짝 보호 공백 → 범위 안(9.6절); (3) 앞서 되살린 rank의
낡은 끝점 → 활성화 덩어리, TOKEN QPN, STATE rkey(9.4절); (4) 받는 쪽 단일 대입과 rain BAR1 → 단계 맞춤 가져오기, 2 MiB 그대로(9.4절); (5) rain QUERY_QP 상한 → 학습
셀만 QP 감시 50 ms(무장 조건은 켜져 있음뿐이라 바꿀 것 없음; gin-restore 6절의 "10 ms"는 그 실험의 설정 값); (6) TCP 처리량 → RDMA 저장소와 READ(9.4절); (7) 버려진
멈춤과 체크포인트 → 되돌리기와 다시 시작(9.3절); (8) mirror QP 장애 기록 → 흡수, 짝을 거절하지 않음(9.5절); (9) 단계 맞춤 가져오기 대 게이트에서 쉰 생존 rank의
put → 게이트를 INJECTED까지 홀수, PUBLISHED의 끝과 시한이 바뀜(9.4절). 계보(9.9절)의 열린 충돌 셋(2026-10-15 사용자 결정, 메인 세션이 전함): (10) serve 중이던
낡은 요청의 답 → (나) 보내기 직전 다시 가름, wire 그대로(STORE_ACK의 `wardInc`는 다시 무장 작업으로 미룸); (11) mirror 끈 TCP 데이터 길 → (가) 그대로(18절);
(12) 다시 무장의 범위 → (가) 계보만, 다시 무장은 설계로만(19절). 결함 E 고침의 행 일곱(2026-10-15)은 사용자 결정 없이 설계로
닫았다: 고침 뒤 독립 리뷰(세션 스크래치 `lineage/IMPL_REVIEW.md` 질문 4, 고칠 것 F1)가 표가 없음을 찾아 이 행들을 더했고, 상한과 폴링 흡수의 조건은 그 리뷰와
pilot 4로 고쳤다(빌드 ln3, 12절). 다만 거절 까닭 행의 멈춤 시한 거절(ln3 독립 리뷰가 찾음, 2026-10-15 그 행에 더함)은 사용자 결정 대기다(19절).

**가정(사용자가 그대로 둠).** mirror 문맥 하나를 GPU 범위 공유 모드로, mirror와 checksum 함께 켜면 Resume 거절, 재기만 하는 모드의 self와 peer 팔, 초안 값. 결정 (6)으로
segment FETCH는 TCP가 아니라 RDMA READ가 됐다.

**결정의 범위 안에서 고른 설계 여섯**(독립 검토가 볼 것):

| 설계 | 상태 |
|---|---|
| 올리기: 멈춤 안 D2H(고정 호스트 버퍼, 학습 모양 30 MiB), 멈춤 밖 WRITE를 application 스레드가 Step의 복사 단계에서 | 사용자 확인(2026-10-13) |
| 증분 없앰(늘 전체 이미지) | 이 문서의 선택 |
| 예비 프로세스의 RDMA READ(짝이 쓰지 않음) | 이 문서의 선택 |
| 따로 된 호스트 올리기 QP(mirror QP 아님) | 이 문서의 선택 |
| CKPT_STABLE에 배치를 실음(WRITE with immediate 아님) | 이 문서의 선택 |
| 학습 셀 L 80 MiB(S 3이면 pool 720 MiB, S 2면 480 MiB) | 이 문서의 선택 |

**열린 충돌 없음**(2026-10-13, 아홉째 결정 뒤; 2026-10-15 계보의 셋도 결정으로 닫힘). 결정 대기 하나(2026-10-15): 결함 E 거절 까닭 행의 멈춤 시한
거절(19절; 지금 셀에서는 닿지 않고, 그대로 두면 18절의 한계로 닫음). 다음은 9.8절의 실행 가능성 확인 넷과 공유 인터페이스 작성, 그 뒤 작업 묶음의 병렬 구현이다.

### 9.8 구현 계획과 실행 방법 (구현 전)

열린 충돌은 없다(9.7절 끝). 실행 가능성 확인 1, 3, 4는 끝났고(2026-10-13, 표 아래의 결과) 확인 2는 test 묶음의 gin_ts2 팔을 기다린다. 공유 인터페이스는
[impl/](impl/)의 헤더 여섯이고, 갈래 분담과 규칙은 [impl/PARALLEL.md](impl/PARALLEL.md)다(2026-10-13, 12절). 그다음 작업 묶음을 병렬로 구현한다.

**실행 가능성 확인 넷**(채점 안 함; 메인 세션이 `cluster_run.sh` 안에서; 라이브러리 바꿈 없이 돌 수 있는 작은 프로그램):

| 확인 | 무엇을 재나 | 통과 기준(초안) | 가장 작은 프로그램 |
|---|---|---|---|
| 1. 호스트 MR에 쓴 것이 보이는가 | GPU 메모리(dmabuf MR)에서 다른 노드의 호스트 MR(RO 없음)로 RC WRITE를 4 KiB–2 MiB 무작위 크기, 단계 번호 무늬로 10 000번. 응답 쪽 MSN이 닿은 뒤 (a) 바로 CPU가 읽은 값, (b) 루프백 READ 울타리 뒤 CPU가 읽은 값, (c) 셋째 QP의 RDMA READ로 읽은 값 | (b)와 (c)에서 어긋남 0(두 방향). (a)는 보고 | CUDA + ibverbs 도구 하나(NCCL 없음), 노드마다 하나 |
| 2. 손으로 하는 mirror의 비용 | 9.15.6의 비용 틀(gin_ts2)에서 application이 put(d) 뒤 다른 사용자 문맥으로 같은 원본을 셋째 rank의 window에 한 번 더 put하고 둘을 flush. 4 KiB, 256 KiB, 2 MiB 지연과 256 KiB × 8, 2 MiB × 8 대역을 한 번 put과 견줌 | 판정 없음. 장치 쪽 비용(측 표 읽기, 커서, 쉬지 않는 게이트)은 재지 않으므로 대역 문턱(0.40–0.60)만 받치고, 4 KiB 지연 문턱은 pilot이 실제 장치 길로 잰다 | gin_ts2에 팔 하나(둘째 put), `rsp` 운영 빌드 |
| 3. RDMA 저장소의 시간 | 두 노드 모두에서: window 크기 30 MiB의 D2H(고정 호스트 버퍼)를 100번, 그 호스트 버퍼에서 다른 노드의 호스트 MR로 WRITE 30 MiB를 100번(같은 NIC에서 다른 rank가 2 MiB × 8을 보내는 동안과 아닐 때), 호스트 MR에서 RDMA READ를 크기 4–150 MiB로 100번씩(첫 READ를 낸 때부터 마지막 완료까지) | D2H p99 ≤ 4 ms(학습 모양 멈춤 ≤ 15 ms가 되게), 부하에서 WRITE ≤ 간격 / 4(학습 모양 간격 20단계를 단계 사이 5 ms로만 세어 100 ms; 2026-10-13 고침: 처음 기준 "WRITE p99 ≤ 10 ms"는 WRITE가 멈춤 밖으로 간 뒤 맞지 않음), READ p99 ≤ 100 ms. 절편 a와 θ를 3절 `seg_restore_slope`와 `train_restore_parts`에 넘김 | 1의 도구의 두 모드 |
| 4. rain BAR1 예산 | rain GPU에 프로세스 셋(rank 0, rank 2, rank 2의 예비 프로세스 자리)이 각각 window 6 MiB + 24 MiB를 GIN PD에 dmabuf로 등록하고, 한 프로세스는 같은 window를 둘째 PD(NIC 복사 경로 자리)에도 등록. 단계마다 `nvidia-smi` BAR1 Used/Free를 읽기만 | 세 프로세스 등록 뒤 BAR1 Free ≥ 64 MiB. 둘째 PD 등록이 BAR1을 더 쓰는지 기록(9.5절의 `[미확인]`). 같이 `ulimit -l`과 고정 호스트 메모리 합(pool, 저장소, FETCH 버퍼; GIN PD의 호스트 등록은 BAR1에 들지 않음)이 들어가는지 봄. 등록 버퍼와 mirror QP 고리는 빠지므로 pilot이 실제 바이너리로 BAR1을 다시 봄 | 1의 도구의 모드 하나 |

**확인 결과**(2026-10-13 15:04–15:08, 메인 세션이 `cluster_run.sh` 안에서, 채점 안 함; 도구 [feas/](feas/), 원자료 `results/20261013_feas/`(release 전),
요약 `results/20261013_feas/SUMMARY.txt`. 확인 3의 백분위는 이 문서를 고치며 timing 파일 둘에서 다시 셌고 요약과 같다):
- **확인 1, 통과(두 방향).** 크기 4 KiB, 256 KiB, 2 MiB, 무작위를 각 10 000번. 울타리 뒤 읽기 방향마다 13 332번 중 어긋남 0, 셋째 QP의 READ 13 336번 중 0,
  울타리 없이 곧바로 읽기도 13 332번 중 0 `[측정]`. 곧바로 읽기도 0이라 울타리가 필요한지는 보이지 못했다. 울타리는 설계대로 둔다.
- **확인 3, 고친 기준으로 통과.** 두 방향(rank 3 kill 배치: sunny가 rain에 올리고 읽음, 그 반대). D2H 30 MiB p50/p99 2.393/2.397 ms와 2.393/2.395 ms(13.1 GB/s).
  WRITE 30 MiB p50 무부하 2.613, 2.637 ms; 다른 QP의 2 MiB × 8 묶음과 함께 p50 19.08, 19.41 ms, p99 20.11, 24.13 ms(그동안 올리기는 1.43–1.52 GiB/s). READ p50
  4 MiB 0.354–0.358 ms, 150 MiB 13.09–13.25 ms, 맞춤 a 0.005–0.007 ms, θ 11.88–12.02 GB/s. 데이터 검사 모두 0. n은 방향마다 D2H 100, WRITE 100 + 100, READ 크기마다
  100 `[측정]`. 처음 기준 "WRITE p99 ≤ 10 ms"로는 부하에서 실패지만 올리기는 멈춤 밖이라 볼 것은 확정이 간격 안에 오는가다. 20–24 ms는 간격 100 ms의 약 1/4이라
  기준을 "부하에서 ≤ 간격 / 4"로 고쳐 통과로 닫는다(메인 세션 판단). 따라오는 것: 부하에서 CKPT_STABLE은 멈춤 뒤 약 25 ms에 옴(segment 수명과 당기기, 9.3절),
  올리기는 보내는 rank의 선을 application의 묶음과 나눔(mirror 쓰기처럼), 복원 시간 식의 θ ≈ 12 GB/s(150 MiB FETCH ≈ 13 ms, 9.4절), 학습 모양 시행 시간(아래).
- **확인 4, 통과.** rain BAR1 Free 251 MiB → CUDA 문맥 셋 245 → 세 프로세스의 6 + 24 MiB window 등록 155(+90 MiB) → p0이 30 MiB를 둘째 PD에 다시 등록 125
  (+30 MiB) → 끝난 뒤 251 `[측정]`. 기준 ≥ 64 MiB. 고정 호스트 메모리 812, 812, 1 082 MiB가 모두 등록됨(VmPin 일치, rain memlock 무제한), 1 082 MiB 등록 30 ms.
  둘째 PD 등록이 BAR1을 쓰므로 mirror 켠 프로세스가 NIC 복사 경로 등록을 건너뛰는 설계가 rain에서 프로세스마다 약 30 MiB를 아낀다(9.5절). 시작 검사 128 MiB는
  그대로.
- 모든 hold: 새 mlx5 커널 줄 0, 펌웨어 명령 실패 수 그대로(전후 failed 16, mailbox status 15), STOP 없음 `[측정]`.

**작업 묶음과 갈래**(갈래, 소유, 붙이기와 기록 규칙은 [impl/PARALLEL.md](impl/PARALLEL.md); 공유 인터페이스를 먼저 고정하고 갈래마다 worktree 하나; 크기는 바뀌는 줄의 어림
`[추론]`, 합 약 4 700–5 800줄). 공유 인터페이스에서 먼저 고정할 것(재검토와 결정 (9)): QP 묶음 둘(사용자만, mirror 포함), CKPT_STABLE 칸과 무장 가능 판정, BUSY 판정(가져오기와
segment 묶음이 모두 8125–8175를 만짐), hook 차례(mirror 흡수 → `gdakiHoldRoute` → 훑기), 측 표 magic과 mirror 칸 배치, 기록 번호 38과 48–51, 활성화 덩어리 판 2(주소 표,
저장소와 pool 자리, FETCH 끝점, READY), 내보내기 판 2(단계 표, MIRROR 항목, pool을 포함한 rkey 목록), PUBLISHED와 INJECTED의 상태 규칙. 저장소와 segment 묶음은 모두 8486–8560을 만지므로
함수 경계를 미리 나눈다(2026-10-13: [impl/rs_store_api.h](impl/rs_store_api.h)의 경계 목록과 BUSY 판정 한 곳, [impl/rs_mirror_api.h](impl/rs_mirror_api.h)의 넣고 빼는 자리 표):

| 작업 묶음 | 갈래 | 파일 | 인터페이스(내는 것 / 받는 것) | 크기 |
|---|---|---|---|---|
| 공유 인터페이스(2026-10-13 작성) | 메인 세션 | 새 [impl/rs_mirror_api.h](impl/rs_mirror_api.h)(측 표 v4와 mirror 칸, MIRROR 표시, 기록 48–49, HOLDING 칸, 9.4절의 넣고 빼는 자리 표, QP 묶음 둘, hook 차례, segment 규칙), 새 [impl/rs_store_api.h](impl/rs_store_api.h)(기록 50–51, 저장소 자리, CKPT_STABLE 칸, 활성화 덩어리 판 2, 체크포인트 기계의 함수 경계와 BUSY 판정 한 곳), [impl/rs_hold_api.h](impl/rs_hold_api.h) 판 2(기록 38 INJECTED, PUBLISHED의 끝과 시한), [impl/rs_log_api.h](impl/rs_log_api.h) 판 2(내보내기 판 2, 단계, rkey 목록, 가져오기), rs_ckpt_api.h와 rs_spare_api.h 판 2(머리 주석), [impl/build_mi.sh](impl/build_mi.sh) 뼈대 | 모든 갈래가 받음 | S(새 헤더 둘 약 820줄과 넷의 v2) |
| 장치 mirror | dev | `gin_gdaki.h`의 hold 영역(`rsPutHold`의 mirror 함수, flush와 wait 끝의 mirror 기다림), `gin_gdaki_device_host_common.h` | 측 표 mirror 칸을 읽음 / 깨짐 수를 냄 | M, 400–600 |
| mirror 설정, pool, 장애 기록 | host | `gin_host_gdaki.cc`: 문맥 만들기(mirror QP만), 설정 끝 MIRROR_SETUP과 잇기와 기준, pool 등록, policyPad 비트, Resume 조건 34–40, 기록 hook의 mirror 흡수, 정리 | pool rkey와 칸 배치를 냄 | M, 500–700 |
| segment와 당기기 | host | 체크포인트 기계 영역: segment 번호 열, 바꾸기, 되돌리기, 다시 시작, 확정 때 버리기, CKPT_PULL, 깨짐 → DISARM | segment 기록을 복원 길에 냄 | M, 400–500 |
| RDMA 저장소 | store(새 갈래) | 새 영역: 저장소 MR, STORE_REQ/ACK, 올리기 QP, 멈춤 안 D2H와 고정 호스트 버퍼, 멈춤 밖 WRITE(application 스레드, 복사 단계), CKPT_STABLE 칸, 한도와 버림, 정리. mirror 끔 TCP 길은 9.6절의 기반 지우기만(공유 인터페이스에서 이 갈래로 정함) | 저장소 자리를 활성화 덩어리에 냄 | L, 700–900 |
| 복원 길 | spare | hold 시작 HOLDING 칸, 짝 drain(자기 루프 셈, 무효 셈 거절)과 울타리, 활성화 덩어리 판 2, FETCH QP와 READ, 내보내기 판 2(단계 표, rkey 목록) | 저장소와 segment 기록을 받음 | L, 800–1 000 |
| 단계 맞춤 가져오기 | dev | 가져오기 영역: Resume 몫과 Step 몫, 쌍 잠금, 넣을 입력이 남은 동안 BUSY, 마지막 단계 뒤 INJECTED 깃발 | 내보내기 판 2를 받음 / INJECTED를 냄 | M, 400–500 |
| PUBLISHED와 INJECTED | host | 붙잡기 기계: mirror 켬이면 게시 때 사용자 QP 게이트 홀수 유지, INJECTED를 받으면 짝수 에폭, PUBLISHED의 끝(INJECTED)과 시한 min(지금, D) | INJECTED를 받음 | S–M, 200–300 |
| 끝점 갱신 | spare | 예비 프로세스 driver: `pe.addr` 덮기, TOKEN QPN으로 잇기, 화신 0 검사와 WARN, rkey 목록 쓰기, RESTORED 뒤 STORE_REQ | 활성화 덩어리를 받음 | S–M, 300 |
| 시험과 비용 | test | `impl/test/gin_rs.cu`(`RS_OVERWRITE`, `RS_TRAIN` 받는 고리 R = 4), 비용 driver(`lat2m`, `bw2m`, mirror 팔), 셀 파일, 실행기(예비 프로세스 둘, seed 무작위 kill, hold 나눔, 학습 셀 QP 감시 50 ms, 예비 프로세스 기다림 ≥ 120 s), 채점기 열 | 라이브러리 줄 형식을 받음 | M, 600–800 |
| 통합과 검사 | 메인 세션 | 갈래 합치기, CPU 단위 시험(`impl/mi_unit_<이름>.cc`), 기계어 비교, 독립 코드 검토, 확인 넷의 도구 | 모두 | M |
| 계보(lineage, 2026-10-15; 9.9절) | 갈래 없이 `exp/gin-mirror-fix`(빌드 트리 `agent_mi_fix/`, 이름 `ln1`) | 새 [impl/rs_lineage_api.h](impl/rs_lineage_api.h)(국면, 보기, classify, 줄 머리), `gin_host_gdaki.cc`의 화신 비교 자리와 새 영역 "gin-mirror (lineage): pure", REJOIN_ACK 칸 쓰기, park 검사, serve 끝 다시 가름; 새 `impl/mi_unit_lineage.cc`, `impl/mi_unit_store.cc` 모형, `impl/test/rows_mi.py` 열 `lineage_warn`, `build_mi.sh` `BR=ln` | 보기를 냄 / 칸과 known을 받음 | L, 1 700–2 200 |

**학습 모양 모드(`RS_TRAIN=1`; 셀은 7절).**
- 전송: 단계마다 rank마다 상대 셋에 2 MiB put과 신호 1(단계 짝에 따른 신호 둘), rank마다 단계당 6 MiB, 2 000단계, 단계 사이 5 000 µs. 상대별 flush가 돌아온 바로 뒤
  보내는 칸을 단계에 따른 독 값으로 덮고 다음 단계가 진짜 값을 쓴다(결정 1의 규칙). 원본을 다시 읽는 재실행이면 독 값이 들어가 비교에서 틀린다.
- window와 rain BAR1(256 MiB, window 하나 24 MiB 이하, gin-restore 9.15.6): 보내는 window 6 MiB(상대마다 칸 하나), 받는 고리 R = 4로 24 MiB, rank마다 30 MiB. rain은
  두 rank 60 MiB, 둘째 죽음 셀은 rank 2의 예비 프로세스가 더해 90 MiB(NIC 복사 경로 등록을 건너뛸 때) `[추론: 계산]`. 단계 맞춤 가져오기는 R ≥ 3이면 되므로 맞는다.
- pool: 식은 짝마다 잡는 크기 = S × (n − 1) × L, 살아 있는 내용 ≤ (1–2) × (n − 1) × B × I(WRITE가 부하에서도 멈춤 뒤 약 20–25 ms에 끝나 확정이 곧 옴 `[측정: 확인 3]`). B = 2 MiB, I = 20, L = 2 × B × I =
  80 MiB, S = 3이면 잡는 크기 720 MiB, 살아 있는 내용은 많아야 2 × 3 × 40 MiB = 240 MiB이고, 당기기 문턱 50%(40 MiB)는 간격 하나의 바이트와 같다(2026-10-15 고침: 처음 글 "확정이 늦을 때만 당긴다"는 틀렸다. pilot의 장애 없는 학습 시행은 네 rank 합 당기기 834–847번이었다 `[측정]`, 3절 `train_pull_count`).
  저장소 약 2 × 31 MiB, D2H 버퍼 30 MiB. 둘째 죽음 셀의 rain은 프로세스 셋(pool + 저장소 + D2H 버퍼 약 0.8 GiB씩)과 예비 프로세스의 FETCH 버퍼 약 270 MiB로 고정
  호스트 메모리 약 2.7 GiB `[추론: 계산]`. 확인 4에서 812, 812, 1 082 MiB가 모두 등록되고 rain memlock은 무제한이었다 `[측정]`; RAM은 8절 시작 검사가 본다.
- 체크포인트: 멈춤 안 D2H 2.4 ms `[측정: 확인 3]`로 멈춤 약 8 ms, 멈춤 밖 WRITE(부하 19–24 ms `[측정]`)는 그 rank의 Step에만 더해짐. 20단계(약 200 ms)마다라 생존 rank 입력의 약 4%가 멈춤 `[추론]`.
- 복원: T ≈ 375.6 ms + drain + FETCH(약 150 MiB를 약 13 ms, 확인 3의 θ) + 이미지 H2D 약 3 ms ≈ 0.4 s `[추론]`.
- 시행 시간: 단계 사이 5 ms만 세면 2 000 × 5 ms = 10 s + 체크포인트 100번 × (멈춤 약 8 ms + WRITE 19–24 ms) ≈ 2.7–3.2 s + 시작과 초기화 재생 3–5 s = 16–18 s. 복원 때
  생존 rank는 INJECTED까지 재실행 길이(약 0.2–0.4 s)만큼 더 쉰다. 전송까지 세면 노드의 NIC이 단계마다 두
  rank의 12 MiB와 그 mirror 12 MiB, 곧 24 MiB를 보내 약 4 ms가 더해져 단계 약 10 ms, 시행 26–29 s, 둘째 죽음 셀 27–30 s `[추론]`(확인 3의 부하 WRITE로 고침). QP 감시 50 ms면 rain의 30 QP가
  초당 600번이라 시행마다 약 16 000번이다.
- hold: 실행기 몫을 시행마다 약 5 s로 보면 20시행이 625–685 s라 840 s 안이지만 여유가 작아 나눈다: `mi4_train_none` + `mi4_train_kill3`(15시행, 465–510 s) 하나,
  `mi4_train_kill2_kill3`(5시행, 160–175 s) 하나. pilot이 잰 시행 시간으로 다시 정한다.

- **배포/빌드:** [impl/build_mi.sh](impl/build_mi.sh)(뼈대, 아직 돌리지 않음; 갈래마다 세션 스크래치의 `agent_mi_<이름>/`, i5 위의 diff). 배포 꼴은 pilot 전에 정한다.
- **실행:** `harness/gpu-initiated/common/cluster_run.sh` 안에서 메인 세션이 한다.
- **채점:** 3절 예측의 표 파일과 채점기(사전 등록 때 만듦).
- **출력:** `results/<날짜>_<이름>/`, 원자료는 Release.

### 9.9 계보(lineage): 화신 판정을 한 곳으로 (2026-10-15 사용자 결정, 사전 등록 전)

설계 원문은 세션 스크래치 `lineage/DESIGN.md`(v3, 494줄: 구현 중 정한 것 한 항목을 더한 뒤; 1절이 화신을 적는 곳과 견주는 자리 약 50곳의 목록), 독립 검토는
`lineage/REVIEW.md`(375줄: v1 검토와 v2 재검토)다. 이 절의 `H:N`은 `lineage/snap_host.cc`(md5 `cc4eea3d`, 24 020줄 = 빌드 i4의
`gin_host_gdaki.cc`)의 줄이다. 이 절은 측정을 새로 하지 않았다(`[소스]`, `[추론]`).

**왜.** 복원 계층은 rank d의 화신(d를 맡은 프로세스의 번호; 처음 0, 죽음 i의 복원이 i + 1을 만듦, H:5485–5487)을 두 곳에 적는다:
생존 rank가 상대마다 두는 hold 칸의 화신(승격에서만 + 1, H:5954)과 REJOIN 받아들임이 올리는 아는 화신 `knownInc`(H:9251). 두 출처는
REJOIN 받아들임부터 승격(mirror 끔 RESTORED, mirror 켬 INJECTED)까지 일부러 한 칸 다르다. pilot 1의 결함 A(12절)는 저장소 요청의 버림
판정이 잘못된 출처를 고른 것이었다. 계보는 두 출처를 한 번에 읽어 국면과 보기를 만들고, 메시지에 실린 화신 x를 넷으로 가르는 함수
`gdakiLnClassify` 하나로 화신 비교를 모은다. **화신 비교만 바꾸고 상태 조건(HELD만, 거절된 rank에 FAIL, PUBLISHED류, 무장 조건)은 그대로
둔다.** wire, 장치 코드, 측 표, 채점기와 손 검사가 읽는 줄은 바꾸지 않는다. 새 공유 헤더 `impl/rs_lineage_api.h`는 호스트 파일에만 붙는다.

**국면과 보기**(`gdakiLnViewOf(칸 상태, 칸 화신, known, 거절 여부)`). 국면은 화신 축만 나타내고 HELD와 TIMED_OUT_HELD, COMMITTING과
PUBLISHED의 구별은 상태 조건으로 따로 읽는다.

| 국면 | 조건 | cur | dead |
|---|---|---|---|
| LIVE | 칸 OFF/ARMED, known = 칸 화신 | 칸 화신 | 없음 |
| HOLD_WAIT | 칸이 붙잡은 상태, known = 칸 화신 | 칸 화신 | 칸 화신 |
| HOLD_SUCC | 칸이 붙잡은 상태, known = 칸 화신 + 1 | known | 칸 화신 |
| ENDED | 칸 FALLBACK/CANCELLED, 또는 그 rank가 거절됨 | known | 칸 화신 |
| BAD | 그 밖(불변식 1을 어김) | known | 칸 화신 |

- 자기 자신과 hold 상태가 없는 프로세스(fail-fast, 재기만 하는 모드)의 보기는 `{LIVE, 자기 known}`이다. 보기를 읽는 `gdakiLnOf`는 helper
  스레드 것이고(예비 프로세스의 driver는 helper가 뜨기 전 같은 스레드), 다른 스레드는 자기 known만 읽는다(H:17060, 15218, 22721).
- 불변식: (1) 칸 화신 ≤ known ≤ 칸 화신 + 1이고, known = 칸 화신 + 1은 붙잡은 상태나 그 hold가 끝난 FALLBACK, CANCELLED에서만; (2) 칸
  화신은 승격에서만, known은 REJOIN 받아들임에서만(예비 프로세스는 ACTIVATE와 REJOIN_ACK에서 정해짐) 오른다; (3) 짝에서 d의 후계가
  CURRENT이면 그 후계의 FETCH는 끝났다(H:9748–9766); (4) REJOIN 받아들임 순간 d의 park에는 화신을 싣지 않는 기록(11–15, 48–51)이 없다.

**classify**(`gdakiLnClassify(보기, x)`):

| 국면 | x < 하한 | x = dead | x = cur(≠ dead) | x > cur |
|---|---|---|---|---|
| LIVE | STALE(x < cur) | – | CURRENT | FUTURE |
| HOLD_WAIT | STALE(x < dead) | HELD_OLD | (cur = dead) | FUTURE |
| HOLD_SUCC | STALE(x < dead) | HELD_OLD | CURRENT | FUTURE |
| ENDED | STALE | STALE | STALE | STALE |
| BAD | LIVE처럼 cur = known으로 가름, 그 rank에 한 번 `GIN/LN` WARN; 칸이 붙잡은 상태면 지금처럼 fallback(H:13421 자리) | | | |

**호출자 규칙.** "상태 조건" 열은 지금 코드 그대로이고 호출자는 그 조건을 먼저 본 뒤 classify한다. 마지막 열은 지금 코드와 견준 것이다.

| 결정(H:줄) | x | 상태 조건(그대로) | CURRENT | HELD_OLD | STALE | FUTURE | 지금과 |
|---|---|---|---|---|---|---|---|
| HOLDING 세기(13077–13079, 6056–6063, 20289) | round | 이 rank가 d의 짝 | 셈 | 셈 | 버림 | 새 화신으로 다시 셈 + `GIN/LN` | 같음(뒤의 활성화가 같음) |
| 짝 자신의 세기(12853) | view.dead | hold 시작 6단계, 칸 HELD | – | 셈 | – | – | 같음 |
| hold 시작(12770–12860) | view.cur | `gdakiHoldDeclineAction` 전부 | HELD(x), HOLDING(d, x) | – | – | – | 같음 |
| 활성화(13260–13345) | `holders.inc` | 칸 HELD만(TIMED_OUT_HELD 아님), 모두 HOLDING, 아직 활성화 안 됨 | – | ACTIVATE(dead + 1), 차례 열쇠 dead | – | – | 같음 |
| 활성화 답(9599, 20581–) | 답의 화신 | 같은 연결 | 답의 rank = d, 화신 = dead + 1이면 받음; 어긋나면 "답 없음"으로 세어 두 번 규칙(H:13337–13343) | | | | 다름(새, 셀에서 늘 통과) |
| 활성화의 예비 등록(15262–15276, 16960–16968) | 등록 화신(TCP 확정 이미지 머리 H:14689, 저장소 `rec.inc` H:15876) | 짝만 | – | 씀 | "등록 없음" fallback | "등록 없음" fallback | 다름(새, 셀에서 늘 같음) |
| REJOIN 받기(4600, 9213–9227) | pad | 거절된 rank면 FAIL(먼저); HELD만; 구동은 HELD와 단계 REJOIN에서만(H:13411–13416), 받아들인 뒤 보기가 HOLD_SUCC가 아니면 BAD로 fallback(H:13421) | 거절 | 거절 | 거절 | x = dead + 1이면 park 검사 뒤 받음, 아니면 거절 | 같음 |
| 예비 프로세스의 되울림(9838, 9861, 9922) | pad | 임시 소켓 | 받음(자기 보기) | – | 지금처럼(REJOIN_ACK는 다시 걺, TOKEN과 DONE_RS는 끝) | 같은 처리 + `GIN/LN` | 같음 |
| READY(9297), rkey 목록(9447) | pad, 화신 | READY: 받아들인 REJOIN이 있음 | 받음 | 거절 | 거절 | 거절 | 같음 |
| RESTORED(5731, 9517, 13008, 22445–22448) | pad | PUBLISHED, TIMED_OUT_PUBLISHED; mirror 켬은 `restoredPad`만 적음 | 적용 | 무시 | 무시 | 무시 | 같음 |
| INJECTED(7351–7359) | pad | 형식 검사, PUBLISHED류, `restoredPad` = x | 적용(LIVE면 되풀이라 무시) | 무시 | 무시 | 무시 | 같음 |
| FALLBACK(d, x)(5745–5752) | round | 칸 상태, `revivedFrom` | LIVE: ARMED면 OFF; HOLD_SUCC: 무시 | 이 hold의 fallback | x = `revivedFrom`이고 칸 화신 = x + 1(칸 화신: 붙잡은 중이면 view.dead, 아니면 view.cur): 붙잡지 않았고 칸 OFF/ARMED면 cur 거절(gin-restore 9.10.7절 P2), 붙잡은 중이면 그 hold의 fallback; 그 밖 무시 | 무시 | 같음 |
| NOHOLD(d, x)(5739–5742) | round | 칸 상태 | LIVE: ARMED면 OFF | fallback | 무시 | 무시 | 같음 |
| DISARM(5736–5738, 12952) | 안 봄 | ARMED → OFF, 붙잡음 → `disarmDuringHold` | 모든 갈래 적용 | | | | 같음 |
| 무장(12926–12943, 14303–14309) | view.cur | `gdakiHoldArmOk`의 조건, CKPT_STABLE의 ARMABLE | ARMED(cur) | – | – | – | 같음 |
| 화신 없는 체크포인트 기록 11–15(13611–13616) | 없음 | HELD에서 붙잡은 rank의 기록 처리 | 받아들임 뒤는 새 프로세스 것 | HELD에서 처리 | – | – | 같음(받아들임 때 park 검사가 둘을 가름) |
| 자기에 대한 FALLBACK(13530–13538) | round + 1 | 되살린 프로세스, 아직 자기 끝 아님 | 자기 끝 | – | 버림 | 버림 | 같음 |
| STORE_REQ(16535–16549, 16600) | 요청 화신 | serve 판정(seq, 크기, H:15611–15612)은 그대로 뒤에 | serve | 버림 | 버림 | 버림 + `GIN/LN` | 같음; FUTURE와 CANCELLED만 다름(지금은 serve; 닿지 않음) |
| serve 끝의 답(16620–16647) | 요청 화신 | helper 스레드, 보내기 직전 | 보냄 | 버림 | 버림 | 버림 | 다름(새, 열린 충돌 1의 답) |
| 올리는 쪽(15722, 16747–16751) | 짝의 cur | 짝 소켓 있음, 거절 안 됨, 붙잡히지 않음 | 청함 | – | – | – | 같음 |
| 짝 복원 뒤 저장소(16977–16992) | 짝의 cur | 짝일 때, RESTORED 적용 때 | 화신마다 한 번 | | | | 같음 |
| 주소 표, QPN, rkey, TOKEN QPN(8682, 8700–8775, 9227, 9867–9892, 20530–20541) | q의 cur | – | "앞서 되살아남" = cur > 0 | | | | 같음 |
| 재연결 펜싱(9110–9114) | pad | `gdakiRsRequested`일 때만; 거절된 rank에는 hk가 먼저 FAIL | x = cur면 받음 | HOLD_WAIT 받음(cur = dead), HOLD_SUCC 거절 | 거절(ENDED는 x = cur면 받음) | 거절 | 같음(cur = 0이면 모두 받음) |

**보내는 쪽.** 싣는 값은 지금과 같고 보기의 칸으로 읽는다: HOLDING과 FALLBACK의 round는 view.dead(HELD로 CAS한 뒤의 보기), NOHOLD는 ARMED의
cur, ACTIVATE 화신과 활성화 차례 열쇠는 view.dead + 1과 view.dead, TOKEN과 DONE_RS의 pad와 STATE와 내보내기 머리의 화신은 view(p).cur,
주소 표의 생존 rank 화신은 view(q).cur, 자기 known을 싣는 것(INJECTED, RESTORED, STORE_REQ, 체크포인트 머리, REJOIN_ACK의 자기 화신,
HELLO와 PROBE)은 자기 cur. 화신 없이 상태만 읽는 자리(`gdakiMiKeepGatesOdd`, `gdakiStoreWardHeld`, armable의 FALLBACK/CANCELLED, CONFIRMING의
"declined or held", 올리기의 "buddy not held", `gdakiRsHoldIsHeld`, PAUSED와 BUSY)는 그대로다.

**찾은 숨은 문제 둘** `[소스, 추론]`:
- 예비 프로세스의 생존 rank 칸이 OFF(0)으로 남는다(H:5579; REJOIN_ACK 처리 H:9845–9850에 칸 쓰기가 없음). `mi4_kill2_kill3_ow`,
  `mi4_train_kill2_kill3`에서 되살린 rank 3은 rank 2를 칸 OFF(0), known 1로 둔다(BAD). rank 2가 다시 무장되고 죽으면 rank 3(rank 2의 짝)은
  자기를 칸 화신 0으로 세고(H:12853) 다른 rank의 HOLDING(2, 1)과 어긋나 세기가 차지 않는다(H:6058–6073): 활성화 없이 시한 fallback이고 줄은
  "the restore deadline passed"뿐이다. 지금 셀에서는 rank 2가 다시 무장되지 않아 닿지 않는다. 계보는 REJOIN_ACK에서 칸을 CAS로 OFF(0) →
  OFF(s)로 쓰고(OFF(0)이 아니면 `GIN/LN` WARN) 이 쓰기를 classify 사용과 한 커밋에 넣는다. 그 쓰기 없이 BAD를 STALE로 다루면 둘째 복원 뒤
  rank 2의 STORE_REQ("reason=buddy")가 버려져 결함 A 꼴이 다시 나므로, BAD는 known을 cur로 쓴다.
- 죽을 때 serve 중이던 STORE_REQ의 답이 REJOIN 받아들임 뒤 새 프로세스의 소켓으로 나갈 수 있다(H:16620–16647; 받는 쪽은 seq만 봄,
  H:15640). 무장된 프로세스의 serve 중 요청은 seq ≥ 2라 새 프로세스(seq 1부터)에 사실상 받아지지 않는다. 답을 보내기 직전에 다시 가른다(아래
  열린 충돌 1).

**받아들임 순간의 park 검사.** REJOIN 받아들임이 소켓을 설치하기(H:9269) 직전에 d의 park에 11–15, 48–51형 기록이 남아 있으면 `GIN/LN` WARN을
쓰고 그 기록을 버린다(있는 `takeIf`). 같은 helper 걸음에서 이 기록들은 받아들임보다 먼저 꺼내지고(H:13611–13616, 13649, 13658) 죽은
프로세스의 소켓은 닫혀 있으므로 정상 실행에서는 줄이 없다 `[추론]`. `impl/rs_hold_api.h`와 park의 서명은 그대로다.

**줄.** 새 줄은 머리 `GIN/LN:` 하나이고 BAD, 예상 밖의 FUTURE(HOLDING, STORE_REQ, 되울림), REJOIN_ACK 칸 쓰기의 어긋남, park 검사의 위반만
쓴다(구현에서 더한 셋: 활성화 답의 되울림이 어긋남, 예비 등록의 화신이 dead가 아님, 보기를 helper 밖에서 읽음; 모두 맞는 실행에서는 나지 않음, 12절의 `ln1` 행). 받아들인 REJOIN과 'later' 동안의 FUTURE는 정상이라 쓰지 않는다. `GIN/LN` 줄에는 `why=`를 쓰지 않는다(gin-restore 채점기의 거절 줄
정규식이 줄 어디서든 `why=(declined|peer-dead|degraded)`를 찾음). 채점기 열 `lineage_warn`(rows_mi.py)은 시행의 `GIN/LN` 줄 수이고 0이어야
한다. 채점기와 손 검사가 읽는 줄("restored as incarnation", "is given up", "armed at its stable checkpoint", "disarmed", "lane to rank ...
broken", "hold of rank ... started", "store request ... dropped", "store ready at buddy")의 글자는 그대로다.

**지금 코드와 다른 것**(다름 목록; 다른 행은 모두 같아야 함): 활성화 답의 되울림, 예비 등록 화신 = dead, STORE_REQ의 FUTURE와 CANCELLED,
serve 끝의 답의 다시 가름. 지금 셀에서는 넷 다 지금과 같은 결과다 `[추론]`.

**열린 충돌 셋과 답**(2026-10-15 사용자 결정, 메인 세션이 전함; 9.7절):
1. serve 중이던 낡은 요청의 답 → (나): 짝이 답을 보내기 직전에 요청 화신을 다시 가르고 CURRENT만 보낸다. wire와 공유 인터페이스 그대로.
   STORE_ACK의 늘 0인 `pad`를 `wardInc`로 쓰는 (가)는 다시 무장 작업(화신이 여럿 이어지는 때)으로 미룬다.
2. mirror 끈 TCP 데이터 길(FETCH와 UPLOAD가 체크포인트 번호만 봄) → (가) 그대로. 틈은 18절.
3. 다시 무장의 범위 → (가) 계보만. 다시 무장은 아래 설계로만 두고 19절 다음 작업.

**다시 무장(설계만, 구현하지 않음).**
- 등록: 화신 c(≥ 1)의 예비 등록은 c의 프로세스가 직접 한다. `NCCL_GIN_RESTORE_SPARE_ADDR`를 읽는 곳은 `gdakiCkptSelfOf` 하나이고(H:13859–13884)
  `gdakiCkptCreate`가 원래 프로세스와 예비 프로세스 모두에서 부른다(H:15481). 그래서 예비 프로세스에 그 변수를 주면 코드 바뀜 없이 등록된다
  `[소스]`. 실행기가 환경을 넘기는지, 둘째 예비 프로세스의 초기화 재생이 첫 예비 프로세스가 도는 동안 같은 기록으로 되는지는 `[미확인]`.
- 짝은 등록 화신 = dead를 본다(계보가 더함). 잘못 간 ACTIVATE는 포트 분리, 생존 rank의 REJOIN 검사(HELD만, known + 1), 짝의 등록 화신 검사가
  막는다. 남는 것은 생존성: 원래 PID를 실은 ACTIVATE가 잘못으로 둘째 예비 프로세스에 닿으면 그것이 소모된다. 다시 무장 전에 예비 프로세스가
  ACTIVATE 화신을 기대 값과 견주게 하기를 권한다.
- 시험 스위치 `NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT`의 상속(누적 수, H:13917–13919), 실행기의 몫(같은 노드와 GPU의 예비 프로세스 둘, 둘째의 포트,
  늦은 띄우기), rain BAR1(넷째 등록이면 약 125 MiB로 8절의 시작 검사 128 MiB 아래 `[추론]`), hk 라운드의 QPN이 바뀌는지 `[미확인]`.
- 범위 밖: 동시 다중 죽음, 복원 중의 죽음, 다른 노드의 예비 프로세스, mirror 끈 길의 둘째 복원, 넷째 화신부터.

**시험.** 새 `impl/mi_unit_lineage.cc`(ASan, UBSan):
1. 보기 표(칸 상태 9 × 칸 화신 0–3 × known 범위 × 거절 여부)와 classify 표(국면 5 × x 창);
2. oracle: 행마다 지금 호출자의 판단 전체를 사본 줄에서 옮긴 `old_<행>`(공유와 순수 영역의 옛 함수 여섯 `gdakiHoldInjectedAction`,
   `gdakiHoldMsgAction`, `gdakiHoldArmOk`, `gdakiMiInjectedCheck`, `gdakiStoreDropReq`, `gdakiStoreDropOldInc`는 바이트 그대로 남아 그대로
   부름)과 계보 구현 `new_<행>`을 정당한 보기 전부 × x 창에서 견주고, 다른 (행, 국면, 갈래) 칸의 집합이 다름 목록과 정확히 같아야 한다.
   정의역의 도달 가능 조건: COMMITTING, PUBLISHED, TIMED_OUT_PUBLISHED이면 known = 칸 + 1; HELD, TIMED_OUT_HELD에서 단계 REJOIN이면 known
   = 칸이고 그 역도; `restoredPad`는 0이거나 ≤ known; `revivedFromValid`이면 `revivedFrom` < 칸 화신; 거절된 rank의 칸은 OFF, FALLBACK,
   CANCELLED; LIVE의 x 창 아래 끝은 cur 기준; FALLBACK이면 거절됨(구현 중 더함: `gdakiHoldFallback`과 `gdakiHoldDeclineRevived`가 CAS 바로 뒤
   거절한다). BAD 정의역은 따로;
3. 호출자 변이: 결함 A 꼴(칸 화신을 cur로, 또는 dead 대신 known)로 보기를 만든 호출자는 시험이 틀려야 한다;
4. 장면: 첫 죽음(mirror 끔, 켬), 결함 A, 짝과 짝 아닌 rank의 세기, 늦은 CKPT_STABLE, 짝 복원 뒤 둘째 죽음(REJOIN_ACK 칸 쓰기), REJOIN 뒤
   fallback, 활성화 답 없음, 죽은 프로세스의 park된 STORE_REQ, 낡은 STORE_ACK(seq ≥ 2 합성), park 검사, 셋째 화신, TIMED_OUT_HELD,
   TIMED_OUT_PUBLISHED, CANCELLED, NOHOLD, hold 중 DISARM, 국면이 다른 생존 rank, 되살린 프로세스의 자기 끝, HOLD_SUCC의 재연결 펜싱.
`impl/mi_unit_store.cc`의 모형은 hold 칸과 known 대신 계보 보기를 쓰고 새 짝 프로세스의 칸을 REJOIN_ACK 칸 쓰기로 만든다(전에는 OFF(wardInc)를
가정해 숨은 문제를 잡지 못함). 다른 단위 시험은 고치지 않고 그대로 통과해야 한다.

**pilot 4**(set `mi4`, 채점 제외; 메인 세션이 `cluster_run.sh` 안에서; 계보와 결함 E 고침의 빌드 `ln2`. 2026-10-15 고침: 처음에는 "계보 빌드
`ln1`"이라 적었으나 ln1은 배포하지 않았다, 12절의 ln2 행). 모든 셀에서 pilot 2와 같은 판정, `lineage_warn` 0,
"store request ... dropped"는 죽은 프로세스 것만, mirror 끈 회귀의 줄 수와 판정이 pilot 2와 같음을 본다.

| 셀 | n | 지나는 전이 |
|---|---|---|
| `mi4_kill3_ow` | 2 | LIVE → HOLD_WAIT('later') → HOLD_SUCC → PUBLISHED 중 STORE_REQ(1) CURRENT → INJECTED 승격 |
| `mi4_kill3_ckpt_ow` | 2 | 멈춤 중 죽음: HELD에서 죽은 화신의 체크포인트 기록 처리 |
| `mi4_kill2_kill3_ow` | 2 | 짝 승격 뒤 저장소 다시 청함, 예비 프로세스의 칸 OFF(1), 주소 표 TAKE, 둘째 복원 |
| `mi4_train_kill2_kill3` | 1 | 가장 긴 HOLD_SUCC(단계 맞춤 가져오기), INJECTED 되풀이 |
| `rs4_kill3`, `rs4_kill3_ckpt` | 2, 1 | mirror 끔: RESTORED 승격, TCP 길 그대로 |
| `rs4_kill3_mion` | 1 | mirror 켠 gin-restore 회귀: 저장소와 INJECTED 길 |
| `rs4_kill3_spareabsent` | 1 | HOLD_WAIT → ENDED(활성화 답 없음), FALLBACK 방송 |
| `mi4_kill3_ow_sampled` | 1 | REJOIN 뒤 fallback(내보내기 거절): HOLD_SUCC → ENDED, 예비 프로세스의 자기 끝, 거절된 rank의 REJOIN에 FAIL |
| `rs4_kill3_nospare`, `mi4_overflow` | 1, 1 | 무장 안 된 죽음: fail-fast ENDED |
| `mi4_none_ow`, `rs4_none` | 1, 1 | LIVE만 |
| `reg_rm4_kill3_untimed_hold` | 1 | gpu-detect 회귀 그대로 |
| `mi4_pull` | 5 | 결함 E의 고침(9.3절 "당겨진 체크포인트가 찍히지 않을 때"): kill이 당기기 창(시간의 약 30%)에 떨어지면 당기기가 남아 INJECTED 뒤 1–2 Step 안에 당겨진 체크포인트가 찍힘(pilot 4 전에 적은 예상; pilot 4의 주된 길은 아래 문단의 길 (나)) |

이 셀들은 `impl/test/cells_mi.json`의 pilot hold P4(mirror 셀과 `mi4_pull`)와 P5(회귀)다(2026-10-15). `mi4_pull`의 kill 시행은 `lane_broken_other` 0,
`disarm_other` 0이어야 하고, kill이 당기기 창에 떨어진 시행에서는 "a pulled checkpoint at step N did not drain" 줄 뒤 같은 rank가 INJECTED 뒤 1–2 Step 안에 그
체크포인트를 찍어야 한다(간격까지 기다리지 않음). n 5에서 창에 하나라도 들 확률은 약 0.83이다 `[추론: 창 비율 0.27–0.33]`.

pilot 4 결과와 그 뒤의 예상(2026-10-15, F3; 12절의 pilot 4 행, 9.3절의 "pilot 4에서 본 길") `[측정]`: 모든 시행 `lineage_warn` 0, `mi4_pull` 다섯 모두
`lane_broken_other` 0과 `disarm_other` 0. 위 예상은 당기기가 남는 길을 하나만 적었고 pilot 4에서는 둘이 보였다. (가) 생존 rank의 hold 창: Step이 hold로
"a restore runs" 거절, INJECTED 뒤 첫 Step에 찍힘(n2). (나) 짝 rank의 저장소 준비: 죽은 rank 3의 짝이 맡은 rank 2가 kill 앞뒤에 받은 당기기를 INJECTED
뒤에 쓰려 하나, 되살린 rank 3의 새 프로세스가 저장소를 만들 때까지(요청 → 준비 30.8–35.9 ms) "the checkpoint store is not ready"로 3–4번 거절되고 "store
ready at buddy" 뒤 첫 Step에 찍힘(n1, n4, n5와 학습 둘째 죽음 셀; pilot 4의 주된 길). 길 (나)에서는 "INJECTED 뒤 1–2 Step"이 맞지 않는다. 그 뒤의 pilot(빌드
ln3, hold P6)과 본 실행에서 볼 것: 남긴 당기기는 길 (가)에서 INJECTED 뒤 첫 Step, 길 (나)에서 "store ready at buddy" 뒤 첫 Step에 찍히고 "the pull is spent"는
없다(넓힌 상한은 4 KiB 셀에서 요청 뒤 약 86 ms까지 덮음 `[추론]`). 상한을 다 쓰는 시행이 나와도 길 (나)에서는 넘침이 아니라 설계한 짝 보호 공백이 길어진
것이므로 `lane_broken_other`와 `disarm_other`는 여전히 0이어야 한다.

단위 시험으로만 보는 전이: RESTORED 뒤의 FALLBACK, CANCELLED, TIMED_OUT_HELD와 TIMED_OUT_PUBLISHED, NOHOLD, hold 중 DISARM, 국면이 다른
생존 rank, HOLD_SUCC의 재연결 펜싱, 셋째 화신, serve 중 죽음의 낡은 답, park 검사 위반.

## 10. 완료 조건과 QA 기준

- [ ] 모든 셀이 계획한 n만큼 실행됐다(제외와 실패를 따로 센 표 포함).
- [ ] 예측마다 판정(맞음/틀림/자료 없음)과 놓친 시행 목록이 있다.
- [ ] 핵심 수치를 원자료에서 다시 계산했다: 덮어쓰기 셀의 데이터 비교, 내보내기의 원본 바이트 0과 pool 바이트 합, 억제 수, 복원 시간과 segment 바이트, 비용
  중앙값.
- [ ] 다른 에이전트가 채점기를 보지 않고 원자료에서 kill 셀, 대조 셀, 둘째 죽음 셀의 판정을 다시 셌다(둘째 죽음 셀은 전체 올리기, 다시 무장, 둘째 kill의
  차례를 줄의 시각으로 확인).
- [ ] 매크로 없는 프로그램의 기계어가 `rs`와 같음을 다시 확인했다.
- [ ] mirror 켠 셀에서 helper 소켓으로 보낸 이미지와 segment 바이트가 0임을 원자료에서 확인했다(`store_rdma`).
- [ ] gin-restore 회귀 예측을 그 실험의 판정식 그대로 다시 채점했다.
- [ ] smoke, pilot, 제외 시행이 결과에 섞이지 않았다. 여러 실행의 범위와 대표 실행의 범위를 섞지 않았다.
- [ ] 원자료를 Release에 올리고 DATA.md에 적었다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀, 설계, 충돌 표 초안 (`DRAFT`, 2026-10-13)
- [x] 열린 충돌 둘의 사용자 결정과 이 문서의 가정 확인(2026-10-13, 12절)
- [x] 둘째 결정이 연 충돌(앞서 되살린 rank를 만나는 예비 프로세스)의 사용자 결정(2026-10-13, 12절)
- [x] 학습 모양이 연 충돌 셋과 독립 검토의 충돌 둘의 사용자 결정(2026-10-13, 12절)
- [x] 이번 반영분(RDMA 저장소, 단계 맞춤 가져오기, 검토 고침)의 독립 검토(재검토, 2026-10-13, 12절)
- [x] 재검토가 연 충돌(단계 맞춤 가져오기 대 게이트에서 쉰 put)의 사용자 결정, 올리기 꼴(멈춤 안 D2H) 사용자 확인(2026-10-13, 12절)
- [x] 공유 인터페이스 헤더 여섯, 갈래 분담(impl/PARALLEL.md), build_mi.sh 뼈대(2026-10-13, 메인 세션, 12절)
- [x] 충돌 표의 독립 검토(2026-10-13, 다른 Opus 에이전트, 12절)
- [x] 실행 가능성 확인 1, 3, 4(2026-10-13, 채점 안 함; 9.8절의 결과, 12절)
- [ ] 실행 가능성 확인 2(손으로 하는 mirror 비용; test 묶음의 gin_ts2 팔 뒤)
- [x] 계층 구현, 빌드, CPU 단위 시험, 기계어 비교, 독립 코드 검토(갈래 넷, 2026-10-13–15, 12절)
- [x] 시험 workload의 덮어쓰기 모드와 비용 팔, 셀 파일, 채점기(test 갈래, 2026-10-13, 12절; DRAFT 값)
- [x] 갈래 다섯의 통합: 저장소와 소스 합치기, 자리표시 이음, 통합 판단, 다시 빌드, CPU 단위 시험, 기계어 비교, 드라이버 다시 빌드, 독립 리뷰 둘(2026-10-15, 12절)
- [x] pilot 1(set `mi1`)의 결함 넷: 셋 고침, 하나 점검, 빌드 i3, CPU 단위 시험, 기계어 비교, 드라이버 다시 빌드(2026-10-15, 12절; 클러스터 실행 없음)
- [x] pilot 1(set `mi1`)과 pilot 2(set `mi2`) 실행(2026-10-15, 채점 제외, 12절): pilot 2가 결함 A, C, D의 고침을 확인
- [x] 고침 묶음 리뷰의 사전 등록 전 항목: 채점 셈 둘, 단위 시험, 진단 고침, 작은 고침, 빌드 i4, CPU 단위 시험, 기계어 비교, 드라이버 다시 빌드(2026-10-15, 12절; 클러스터 실행 없음)
- [x] 계보(lineage) 설계 v1, 독립 검토(막는 문제 2), v2, 재검토(막는 문제 없음, 조건 셋), v3, 열린 충돌 셋의 사용자 결정(2026-10-15, 9.9절, 12절)
- [x] 계보 구현, 빌드(`ln1`), CPU 단위 시험(새 `mi_unit_lineage.cc` 포함), 기계어 비교, 드라이버 다시 빌드(2026-10-15, 12절; 클러스터 실행 없음)
- [x] pilot 3(set `mi3`, 빌드 i4, 채점 제외) 실행(2026-10-15 16:00–16:14, 12절): 결함 E를 찾음, rain BAR1 시작 문의 첫 측정
- [x] pilot 3의 결함 E 고침(당겨진 체크포인트가 찍히지 않을 때 당기기를 남김, 폴링의 burst 꼬리, 되돌린 segment의 둘째 당기기), CPU 단위 장면, 빌드 `ln2`,
  기계어 비교, 드라이버(2026-10-15, 9.3절, 12절; 클러스터 실행 없음)
- [x] pilot 4(set `mi4`, 빌드 ln2, 채점 제외) 실행(2026-10-15 17:52–18:05, 12절): 9.9절의 셀(pilot hold P4, P5)과 비용 pilot, 모든 시행
  `lineage_warn` 0, `mi4_pull` kill 시행 `lane_broken_other` 0과 `disarm_other` 0
- [x] 구현 독립 리뷰의 고칠 것 F1–F4와 nit, pilot 4의 상한 분석, 빌드 `ln3`, CPU 단위 시험, 기계어 비교, 드라이버, pilot hold P6(2026-10-15, 9.3, 9.7,
  18절, 12절; 클러스터 실행 없음)
- [x] pilot 5(set `mi5`, 빌드 ln3, pilot hold P6, 채점 제외) 실행(2026-10-15 19:00–19:03, 12절): 7 시행 모두 복원하고 데이터 같음, 남긴 당기기 둘이 셋째
  시도에 찍힘(쓴 것 0), 모든 시행 `lane_broken_other` 0과 `lineage_warn` 0
- [x] ln3 독립 리뷰(막는 문제 없음, 고칠 것 2, nit 4)와 반영: 멈춤 시한 거절의 비용과 사용자 결정, 변이 시험의 로그, nit(2026-10-15, 9.3, 12, 18, 19절,
  시험 파일의 주석과 머리 설명; 클러스터 실행 없음)
- [x] 사전 등록 전 일관성 고침 여섯(2, 3, 7, 8, 9.7절; 2026-10-15, 12절; 수치는 pilot 2–5의 원자료에서 다시 셈, 클러스터 실행 없음)
- [ ] smoke와 pilot(채점 제외), 문턱과 n 고정
- [ ] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/gin-mirror-v1` 태그
- [ ] 본 실행 (`RUNNING`)
- [ ] 채점과 재계산 (`QA`)
- [ ] 결과 정리, 원자료 release, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-13 | 초안 작성(DRAFT): 1–11절, 설계 9.1–9.6절, 충돌 표 9.7절. 구현, 빌드, 클러스터 실행 없음. 가정한 결정(사용자 확인 대기): mirror 문맥 하나를 GPU 범위 공유 모드로 나눠 씀, mirror와 checksum을 함께 켜면 Resume 거절, segment 자리 3과 넷째가 필요하면 BUSY, mirror QP의 정보는 설정 합의 뒤 helper 소켓으로, 자료는 TCP FETCH(RDMA READ 아님), 비용은 재기만 하는 모드의 self와 peer 두 팔 | 이 파일, 브랜치 `exp/gin-mirror` |
| 2026-10-13 | 사용자 결정(메인 세션이 전함) 반영: (1) 원격 완료만 보고 원본을 다시 쓰는 것 → (가) 원본은 put의 local 완료(flush, 또는 flushAsync와 wait) 뒤에만 다시 씀, GIN의 원래 계약, 비용 없음(9.5절 규칙과 application 요구 12번, 4절). (2) 복원 뒤 짝 보호 공백 → (가) 범위 안: RESTORED 적용에서 맡은 rank가 올리기 기반을 지워 다음 올리기가 전체 이미지(`baseCkpt = ~0`, 받는 코드 있음), 그 멈춤에서 lane 다시 켜기, 확정되면 다시 무장(9.4절 8번, 9.6절); 둘째 죽음 셀 `mi4_kill2_kill3_ow`를 판정 셀로(3, 7절; 예측 `reimage_after_restore`, `second_death_restored`, 각 ≥ 4/5 초안). (3) 앞 행의 가정은 가정대로 둠. 반영 중 찾은 것: 지금 올리는 쪽의 거절 뒤 되돌림이 큰 이미지에서 듣지 않는 길(9.6절), 둘째 죽음에서 예비 프로세스가 앞서 되살린 rank의 낡은 끝점을 쓰는 새 열린 충돌(9.7절 끝). 상태는 DRAFT 그대로, 구현과 빌드 없음 | 이 파일 |
| 2026-10-13 | 사용자 결정(메인 세션이 전함) 반영: 둘째 결정이 연 충돌(앞서 되살린 rank 2를 생존 rank로 만나는 rank 3의 예비 프로세스가 기록 속 옛 끝점을 씀) → (가). 짝이 ACTIVATE 연결에 생존 rank마다 (listen 주소, 화신) 표를 보내고, 화신이 0보다 큰 생존 rank는 예비 프로세스가 TOKEN의 QPN으로 잇고 그 생존 rank의 REJOIN 검사는 자기 화신이 0일 때만 QPN을 견주며, 생존 rank는 STATE에 rkey 목록을 붙이고 예비 프로세스가 가져오기 때 씀(9.4절 끝점 갱신). 기록 재생 길과 처음 화신의 검사는 그대로(같은 곳). 함께 고침: mirror QP를 처음 화신의 QPN 비교에서 뺌, 가져오기에서 mirror QP의 응답 쪽 기준 M. 9.7절 닫음, 열린 충돌 없음. 상태 DRAFT, 구현과 빌드 없음 | 이 파일 |
| 2026-10-13 | 사용자 요청("구현하고 실제 환경급으로 실험", 메인 세션이 전함) 반영: 학습 모양 모드 `RS_TRAIN`(rank마다 상대 셋에 2 MiB, 2 000단계, local 완료 직후 덮어쓰기, 신호 둘; 9.8절), 셀 `mi4_train_none`(5), `mi4_train_kill3`(10, 단계 300–1 700 무작위, seed는 사전 등록 때), `mi4_train_kill2_kill3`(5), 비용 팔 `lat2m`, `bw2m`(7절), 예측 여덟 줄(3절), 범위에 PyTorch 제외와 학습 모양의 뜻(4절), 시행 시간 한도 120 s와 hold 나눔(8절). 계산: pool 360 MiB(짝마다, I = 20, S = 3), BAR1 rank마다 30 MiB(받는 고리 R = 4), 시행 25–35 s(5 ms 단계만 세면 15–17 s), 20시행 600–800 s라 hold를 둘로. 이 추가가 연 충돌 셋(9.7절 끝): 받는 쪽 단일 대입과 rain BAR1(막음), rain QUERY_QP 상한, TCP 처리량. 4 KiB 설계와 셀에는 열린 충돌 없음. 상태 DRAFT, 구현 없음 | 이 파일 |
| 2026-10-13 | 사용자 결정(메인 세션이 전함) 반영, 학습 모양이 연 충돌 셋: (1) 받는 고리 → 단계 맞춤 가져오기(항목에 보낸 단계, Step(t) 전에 단계 t+1만 넣음, 새 요구 14, 가져오기를 helper 뒤로; 2 MiB 그대로). (2) QP 감시 → 학습 셀만 50 ms; 무장 조건은 "> 0"(Resume 조건 19)이라 바꿀 것 없음. (3) TCP 처리량 → 체크포인트 올리기와 FETCH를 데이터망 RDMA로(짝의 저장소 MR, 따로 된 호스트 올리기 QP, 멈춤 안 전체 WRITE, CKPT_STABLE에 배치, 예비 프로세스의 RDMA READ). 숫자 다시: 올리기 2.5–5 ms, FETCH 약 150 MiB 13–30 ms, pool 720 MiB(L 80 MiB), 시행 24–27 s, hold 둘. 9.4, 9.7, 9.8절(작업 묶음 열) | 이 파일 |
| 2026-10-13 | 독립 검토(다른 Opus 에이전트, 읽기만, 대상 커밋 `da21dfa2`). 새 충돌 둘(버려진 멈춤과 체크포인트가 segment 자리를 채움; mirror QP의 회복 못 하는 장애 기록이 짝을 거절)과 결정 없이 고칠 것 열넷: 예비 프로세스의 TCP FETCH가 기록 주소로 검(9042), pool rkey는 화신과 상관없이 STATE에서, S와 L의 Resume 조건, 예비 프로세스에서 조건 38 건너뜀, mirror QP를 넣고 빼는 자리 표, segment 번호 열과 hold의 다시 읽기, 자기 루프 lane의 셈과 오류, 무효 셈의 drain 거절, 체크포인트 멈춤 중 kill 스위치를 둘째 죽음 셀에서 쓰지 않음(7914), NIC 복사 경로 등록의 BAR1, 처음 화신의 새 비교는 WARN, Resume 조건 40과 조건 38 넓힘과 매크로 flush의 회귀, 비용 팔과 문턱(+2.5 µs, 0.40–0.60), 예측의 반증 꼴(T0 375.6 ms, 넷째 자리, 기다림 ≥ 120 s), 남은 소켓 전송의 한도. 확인된 것: 두 번 쓰기가 맞음(mirror는 자기 QP의 msgs에만, 사용자 X와 P 그대로, 죽는 순간들 안전), FETCH 차례와 M 기준 맞음, void 체크포인트의 진단이 코드로 받쳐짐(둘째 길 8552도), 처음 화신의 결정 그대로, 매크로 없는 장치 코드 바뀜 없음. 열넷을 모두 반영(3, 6, 7, 8, 9.2–9.8절) | 검토 결과는 메인 세션이 전함 |
| 2026-10-13 | 사용자 결정(메인 세션이 전함), 검토의 충돌 둘: (1) segment 자리 → (가)와 (나) 함께: 버려진 멈춤과 게시 전에 아는 버림은 짝수 에폭 게시 전에 segment 바꾸기를 되돌리고(그 사이 장치 쓰기 없음), 그래도 넷째 자리가 필요하면 BUSY 없이 그 받는 rank를 DISARM하고 살아 있는 segment를 모두 버리고 그 멈춤부터 다시 시작, 확정되면 다시 무장(9.3절). (2) mirror QP 장애 기록 → (가): 기록 hook이 mirror 문맥 기록을 분류와 상관없이 흡수해 lane 깨짐 + DISARM + 그 QP를 쓰지 않음, 짝은 거절하지 않음(9.5절). 불변식: mirror는 보조 길이고 그 실패는 그 받는 rank의 복원만 끈다(9.3절). 9.7절 닫음, 열린 충돌 없음. 상태 DRAFT, 구현과 빌드 없음 | 이 파일 |
| 2026-10-13 | 재검토(다른 Opus 에이전트, 읽기만, 대상 커밋 `2886ef79`). 열린 충돌 하나: 단계 맞춤 가져오기 대 hold 동안 게이트에서 쉰 생존 rank의 put(9.7절 끝, 고를 길 (가) 게시 뒤에도 그 게이트를 홀수로, (나) R ≥ 간격 + 3은 2 MiB에서 안 됨). 고칠 것 여섯 반영: mirror 흡수를 `gdakiHoldRoute` 앞에, `handled`를 올려 훑기의 거절을 막음(9.5절); 올리기 QP를 application 스레드가 Step의 복사 단계에서 내고 걷음, QP 속성과 ERR 뒤 다시 STORE_REQ; FETCH QP의 잇는 차례와 READY, 받는 버퍼는 초기화 재생 때 등록; QP 묶음 둘(사용자만, mirror 포함); 다시 시작 뒤 다시 무장은 그다음 확정 체크포인트; pool 등록은 문맥을 만들 때(예비 프로세스는 초기화 재생 때). 메모 반영: 자기 루프 lane의 기준과 10 ms 걸음, 단계 표와 요구 7, FETCH 시간의 정의와 절편, memlock 확인, 확인 3은 두 노드, 확인 4의 빠진 것은 pilot이, 확인 2는 대역 문턱만, 공유 헤더에서 먼저 고정할 것과 함수 경계. 사용자 확인 대기(메인 세션 권함): 멈춤 안 D2H와 멈춤 밖 WRITE(9.4절에 글만 준비) | 재검토 결과는 메인 세션이 전함 |
| 2026-10-13 | 사용자 결정(메인 세션이 전함): 재검토가 연 충돌 → (가). mirror 켬이면 생존 rank의 복원 라운드가 게시한 뒤에도 되살린 rank로 가는 사용자 QP 게이트를 홀수로 두고, 예비 프로세스가 마지막 표시 단계의 입력을 넣은 뒤 INJECTED(새 helper 기록 38)를 보내면 짝수로 함. 바뀌는 규칙: PUBLISHED의 끝이 RESTORED에서 INJECTED로, INJECTED 전 PUBLISHED 시한은 min(지금, D), 감시 스레드는 상태만; 오지 않으면 지금의 시한과 fallback. 쉼은 HOLD_MS 30 s가 묶음. mirror 끈 셀과 gin-restore 회귀는 그대로, mirror 켠 4 KiB 셀은 데이터 영향 없음. 올리기 꼴 확인: 멈춤 안 D2H(고정 호스트 버퍼 30 MiB, 약 2.7 ms), 멈춤 밖 WRITE를 application 스레드가 복사 단계에서; 멈춤 약 8 ms, 고정 메모리 rain 약 2.7 GiB, 확인 3을 D2H와 호스트에서의 WRITE로. 9.7절 닫음, 열린 충돌 없음. 상태 DRAFT, 구현과 빌드 없음 | 이 파일 |
| 2026-10-13 15:04–15:08 | 실행 가능성 확인 1, 3, 4(메인 세션이 `cluster_run.sh` 안에서 돌림, 채점 안 함; 결과는 메인 세션이 전함, 확인 3의 백분위는 이 문서를 고치며 timing 파일 둘에서 다시 셈, 같음). 확인 1 통과(어긋남 0; 울타리 없는 읽기도 0이라 울타리의 필요는 보이지 못함, 울타리는 둠). 확인 3: D2H 30 MiB 2.39 ms, WRITE 무부하 2.6 ms와 다른 QP의 묶음과 함께 19–24 ms, READ θ 11.9–12.0 GB/s; 처음 기준 "WRITE p99 ≤ 10 ms"를 "부하에서 WRITE ≤ 간격 / 4"로 고쳐 통과(메인 세션 판단). 확인 4: 세 프로세스 등록 뒤 BAR1 Free 155 MiB, 둘째 PD 등록이 +30 MiB, 고정 메모리 모두 등록, memlock 무제한. 이 결과로 9.3, 9.4, 9.5, 9.7, 9.8절, 3절의 a와 θ, 18절의 수치를 고침(학습 모양 시행 26–29 s, hold 465–510 s와 160–175 s). 확인 2는 test 묶음의 gin_ts2 팔 뒤 | `results/20261013_feas/`(원자료, release 전: SUMMARY.txt, store/store_*_timing.tsv, bar1/bar1_rain_bar1.txt), 도구 [feas/](feas/) |
| 2026-10-13 | 공유 인터페이스(메인 세션): [impl/](impl/)의 헤더 여섯(새 rs_mirror_api.h, rs_store_api.h; gin-restore의 넷을 그대로 복사한 뒤 판 2로 넓힘), [impl/PARALLEL.md](impl/PARALLEL.md)(갈래 다섯, 소유한 줄, 붙이기 표, 기록과 리뷰 규칙), [impl/build_mi.sh](impl/build_mi.sh) 뼈대(돌리지 않음). 설계가 열어 둔 것을 인터페이스에서 정함: mirror QP는 GIN 문맥 차례의 마지막(사용자 묶음은 그 앞부분; mirror QP의 셈은 따로 읽고 무효면 그 lane만 깨짐); 측 표 판 4의 배치(32 짝 시험 낱말, 40–63 mirror 칸, QP 항목 48 miUse, cell 64 B: 유효, pool rkey, segment, lane 시작, L, 커서, 누적 깨짐); lane 차례와 pool 오프셋 식, S는 2–4; segment 번호는 1부터, 되돌리기는 자기 게시 전에 끝나는 멈춤(gdakiCkptEndPause)에서만 하고 라운드나 hold가 끝낸 멈춤은 바꾸기를 남김(게시 뒤 void로 셈; 설계의 "VOIDED면 되돌림"은 그때 이미 라운드가 게시해 할 수 없음); 다시 시작한 멈춤의 PAUSED는 무장 가능 아님(다음 확정에서 다시 무장하게 하는 장치); INJECTED 때 생존 rank가 되살린 rank의 닫힌 segment를 버림(다시 시작이 잘못 세지지 않게); HOLDING, MIRROR_SETUP, CKPT_PULL, STORE_REQ/ACK, CKPT_STABLE 칸의 배치; 저장소 자리 = gdakiCkptHdr(64 KiB 자리) + 이미지 + 덩어리, 끝 해시 없음(크기와 배치 해시로 확인), 저장소 준비 전에는 체크포인트 없음; 활성화 덩어리 판 2의 차례(ACCEPTED 뒤 끝점, READY, DONE)와 예비 프로세스의 FETCH는 첫 REJOIN 전, FETCH 버퍼 크기 변수(모자라면 REFUSED); 주소 표는 mirror 켬에만; 내보내기 판 2(항목 80 B, 원본 바이트 없음, 생존 rank의 rkey 목록에 pool 종류 4); 가져오기의 단계 실패는 no-BYE 끝; BUSY는 억제 BUSY를 넓힘(새 이유 없음); 갈래 상태는 gdakiRecHost 멤버 하나; 새 변수(`NCCL_GIN_RESTORE_MIRROR_POOL_MAX_MB`, `_FETCH_MB`, `NCCL_GIN_RESTORE_STORE_WRITE_MS`), Resume 이유 글자, test가 읽는 줄 키; mirror 끔 TCP 기반 지우기는 store 갈래. 같이 고친 글: 9.4절 주소 항목(표는 mirror 켬에만), 9.8절 store 행(TCP 기반 지우기), 9.7절 받는 고리 행의 틀린 추론("kd+2"). 확인: 헤더 여섯을 함께 g++ -fsyntax-only(선언 있고 없이), pool과 segment 순수 도우미를 CPU에서 돌림, paste를 i5 두 파일의 사본에 해 보고 host 파일을 g++ -fsyntax-only(경고 0; host 갈래 변형은 판 2 선언 셋의 예상 경고). 라이브러리 구현, 빌드, 클러스터 실행 없음 | 커밋 `6cde95d6`(복사), `656855d1`, `9ca9118e`, `e10dbf05` |
| 2026-10-13–15 | 병렬 구현 다섯 갈래의 기록(아래 행들): dev(장치 mirror, 단계 맞춤 가져오기), host(mirror 설정과 pool과 장애 기록, segment와 당기기, PUBLISHED와 INJECTED), store(RDMA 저장소), spare(복원 길, 끝점 갱신), test(시험과 비용) 갈래가 [impl/PARALLEL.md](impl/PARALLEL.md)의 나눔대로 각자 `impl/notes_<갈래>.md`에 쌓은 행을 갈래마다 그 차례로 옮기고, 행이 아닌 절(리뷰, 인터페이스 밖에서 정함, 인터페이스 틈, 줄 형식, 통합 때 할 일)은 줄여 행으로 옮겼다(통합 뒤 그 파일들은 지움; 원문은 통합 브랜치의 커밋 `f95617d5`(dev), `3e26c05f`(host), `1fd83641`(store), `8e4e224b`(spare), `9badf2e9`(test)의 `impl/notes_<갈래>.md`). 행 안의 커밋 해시는 갈래 브랜치의 것이고(통합 브랜치에서는 cherry-pick이라 다름, 아래 통합 행의 대응표), 줄 번호는 따로 적지 않으면 rs_layer.diff(`f005bb67`)의 줄, 빌드 트리는 세션 스크래치의 `agent_mi_<갈래>/`. "빌드됨"은 컴파일만, "시험함"은 CPU 단위 시험; 갈래들은 클러스터, GPU, RDMA 프로그램을 돌리지 않음 | 원문 커밋 다섯 |
| 2026-10-13 15:33 | dev 갈래: `build_mi.sh setup`: i5를 `agent_mi_dev/`로 복사, rs 계층을 커밋 "gin-restore i5 (rs_layer.diff f005bb67)"로 | `[측정]` 복사한 libnccl이 i5의 md5와 같음(setup이 검사) |
| 2026-10-13 15:48 | dev 갈래: 인터페이스 커밋: `build_mi.sh paste`(hold shared text는 v1), `api` 통과 | 커밋 `9434a824`, `mi_layer_dev.diff` md5 `a1beff20`(712줄, 인터페이스만) |
| 2026-10-13 15:48–16:10 | dev 갈래: 장치 mirror 구현: `rsMiPut`(hold 보내기 길의 둘째 put), `rsLogPut`의 lane 낱말과 MIRROR 표시, `rsMiWait`와 flush, wait 끝의 기다림; 측 표 v4(`gdakiMiSideLayoutOf`, `gdakiRsStart`의 머리와 칸); QP 묶음 함수와 루프백 쌍 잠금; 가져오기 영역 첫 판; 한 줄 고침 셋; 자리표시 셋 | `[소스]` 작업 트리 diff(아래 `mi_layer_dev.diff`). 첫 빌드 `mi_d1` libnccl `f9422c3c`(16:10), `mip_d1` `b06620e0`(16:24); 이 계층의 세 파일에 경고 0(`build_mi_d1.log`, `build_mip_d1.log`; 남은 경고 1은 i5에도 있는 `symmetric_sched.cc:327`) → **빌드됨** |
| 2026-10-13 16:16–16:30 | dev 갈래: 독립 리뷰 1(같은 모델, 읽기만; `agent_mi_dev/review1/`): 장치 길과 가져오기 첫 판 | 찾은 것을 접음(아래 행 "리뷰 1에서 고친 것"). 리뷰의 본문은 앞 세션이 한도에 걸려 남지 않았고 고친 diff만 남았다(`review2/fixes.diff`, 431줄) `[소스]` |
| 2026-10-13 16:47–16:51 | dev 갈래: 리뷰 1 반영: 자기 루프의 오류 CQE 확인, rkey 0은 깨짐, `rsMiWait`의 끝 조건 셋(miUse 0, swErr, 창 밖에서 멈춘 소비 색인), 가져오기의 Prepare와 Step을 통째로 다시 씀(잠금 밖 INJECTED, 실패한 Step은 helper가 끝냄, rkey 목록의 자리 검사, FETCH 결과 검사, 측 표 머리에서 칸 자리) | `[소스]` `review2/fixes.diff`. `build_mi.sh unit`: `mi_unit_dev` 568 994 checks, 0 failed(ASan, UBSan) → **시험함**(16:51) |
| 2026-10-13 17:02–17:14 | dev 갈래: 둘째 빌드 | `mi_d2` libnccl `df76e815`(17:08), `mip_d2` `96be0696`(17:14); 세 파일에 경고 0(`build_mi_d2.log`, `build_mip_d2.log`) → **빌드됨** |
| 2026-10-13 17:16–17:34 | dev 갈래: `build_mi.sh ident`(`ff_cmp_mi.sh`, `exact_cmp_mi.sh`: gin-restore의 `ff_cmp_dev.sh`, `exact_cmp_dev.sh`를 새 이름으로 옮겨 hk와 i5 둘 다와 견줌) | `[측정]` `ident_d2.log`(rc 0): 매크로 없는 프로그램 넷 × sm_75, sm_86 = 8/8이 hk와도 i5와도 SASS 전체와 -res-usage 같음; 라이브러리 장치 객체 207개가 i5와 같음(205 그대로, 2는 컴파일 해시만 다름, 다른 것 0; 연구와 운영 둘 다); hk와는 183 + 2 같고 22 다름(gin-restore 12절에 적힌 hk 트리의 낡은 symmetric 객체 22개, i5도 같음); libnccl -res-usage는 i5, hk와 같음. 매크로 변형(m)은 경고 0으로 컴파일되고 자원이 i5의 m과 다름(ff 22 중 11, gin_ts2 20 중 4, gin_mr 4 중 1, ring 8 중 8): mirror 기다림의 비용, test 갈래의 비용 팔이 잼 |
| 2026-10-14 15:50–16:00 | dev 갈래: 이어서(앞 세션이 한도에 걸림): 작업 트리가 d2 빌드의 원본임을 확인(파일 mtime 16:50 < 빌드 17:08), `api` 다시 통과, `unit` 다시 568 994 / 0 | `[측정]` 그 세션의 출력 |
| 2026-10-14 16:04–16:19 | dev 갈래: 독립 리뷰 3(같은 모델, 읽기만; 입력 `review2/dev_only.diff` = d2의 원본): MUST-FIX 0, SHOULD-FIX 4, NOTE 10 | 본문 `agent_mi_dev/review3/review.txt`(31줄; 2026-10-15에 세션 기록에서 옮겨 둠). 접은 것은 아래 행 "리뷰 3에서 고친 것", 넘긴 것은 "통합 때 할 일" `[소스]` |
| 2026-10-14 16:19–16:29 | dev 갈래: 리뷰 3 반영(아래). 호스트 파일 문법 검사(`hostsyn.sh`) 통과, 매크로 장치 프로그램 `ff_ops.cu`를 sm_75, sm_86에서 매크로 있음과 없음으로 컴파일해 경고 0(`devchk/run.sh`), `unit` 568 999 checks, 0 failed(ASan, UBSan; 검사 5개 더함) | `[측정]` 그 세션의 출력 → **시험함** |
| 2026-10-14 16:29–16:45 | dev 갈래: 셋째 빌드, `diff` | `mi_d3` libnccl `728b8f08`(16:37), `mip_d3` `c753116f`(16:45); 경고는 각 1(i5에도 있는 `symmetric_sched.cc:327`), 이 계층의 세 파일에 0(`build_mi_d3.log`, `build_mip_d3.log`) → **빌드됨**. `mi_layer_dev.diff` md5 `b9ecd9fa`(2 261줄). 그 세션은 기록을 쓰기 전에 한도에 걸림 |
| 2026-10-15 07:02–07:06 | dev 갈래: 이어서: 작업 트리가 d3의 원본임을 확인(파일 mtime 16:26–16:27 < 빌드 시작; 트리의 diff md5 = 저장한 `mi_layer_dev.diff` `b9ecd9fa`), `api` 통과(붙인 블록 다섯이 헤더와 바이트까지 같음, 여섯 헤더가 함께 컴파일됨), `unit` 568 999 checks, 0 failed(ASan, UBSan) | `[측정]` 이 세션의 출력 → **시험함** |
| 2026-10-15 07:05–07:24 | dev 갈래: `build_mi.sh ident`(`MIOUT=mi_d3`, 운영은 `mip_d3`) | `[측정]` `agent_mi_dev/ident_d3.log`(rc 0), d2와 같은 결과: 매크로 없는 프로그램 넷 × sm_75, sm_86 = 8/8이 hk와도 i5와도 SASS 전체와 -res-usage 같음; 라이브러리 장치 객체가 i5와 205 그대로, 2(`device_glue.o`, `onerank.cu.o`)는 컴파일 해시만 다름, 다른 것 0(연구와 운영 둘 다); hk와는 183 + 2 같고 22 다름(모두 `genobj/symmetric`, i5도 같음); libnccl -res-usage(해시 가린 이름)는 i5, hk와 같음(1 472 같음, 다름 0). 매크로 변형(m)은 경고 0, 자원이 i5의 m과 다름(ff 22 중 11, gin_ts2 20 중 4, gin_mr 4 중 1, ring 8 중 8) |
| 2026-10-15 07:24 | dev 갈래: `build_mi.sh info` | `[측정]` `agent_mi_dev/out/build_info.txt`: 바탕 `8ffb609`(i5 커밋의 diff md5 `f005bb67` = `rs_layer.diff`), 작업 트리 diff `b9ecd9fa` = `mi_layer_dev.diff`, `mi_unit_dev.cc` `10d3ffa8`, 공유 헤더 여섯과 `PARALLEL.md`, `build_mi.sh`의 md5 |
| 2026-10-13–14 | dev 갈래: "리뷰 1에서 고친 것"과 "리뷰 3에서 고친 것"(MUST-FIX 0, SHOULD-FIX 4, NOTE 10). 리뷰 1: `rsMiPut`의 자기 루프(게이트 없음)는 내기 전에 가장 오래된 미완료 완료를 한 번 폴링해 오류면 깨짐, 게이트 진입 뒤 pool rkey 0은 깨짐; `rsMiWait`의 끝 조건(miUse 0, swErr, 창 밖에서 멈춘 소비 색인), 시한은 `timeoutCycles`가 0이 아닐 때만; 가져오기의 Prepare를 잠금(`gdakiRsWinMu` → `appMu`) 안 `gdakiMiImportPrepareLocked`와 잠금 밖 INJECTED 알림으로 나누고, 실패한 Step은 `endAsked`만 세워 helper의 `gdakiMiImportHelperStep`이 `gdakiHoldSelfEnd`로 끝냄, rkey 목록 자리 검사(화신 > 0 거절, 0 WARN), FETCH 결과 검사, 칸 자리는 측 표 머리(`miCellsOff`, `miNCells`)에서. 리뷰 3: (1) 자기 루프의 예약이 CQ 창을 벗어나면(`rsvd + chunks > ci + sq_wqe_num + cqe_num`) 내지 않고 깨짐(리뷰가 글자로 낸 조건은 첫 고리 뒤 모든 mirror를 깨뜨려 쓰지 않음), (2) "창 밖에서 멈춘 소비 색인"은 `NCCL_GIN_MI_STUCK_NS`(20 ms) 동안 그대로일 때만, (3) 되살린 rank의 mirror QP는 생존 rank의 셈이 무효일 때만 `miUse 0`, 그 결정을 `gdakiMiImportMirrorUnusable(r, peer)`로 읽게 함, (4) 열쇠 줄 "import step", "import done"을 두 빌드 모두 WARN으로; NOTE 5 WARN 넷에 ` mono_ms`, NOTE 6 `gdakiMiReadMsgsMirror(r, 자기 rank)`는 자기 루프 QP 항목, NOTE 14 단위 시험 추가. NOTE 7–10, 12는 통합으로 넘김 `[소스]` | `agent_mi_dev/review2/fixes.diff`, `agent_mi_dev/review3/review.txt`(세션 스크래치), notes 원문(커밋 `f95617d5`) |
| 2026-10-14 | dev 갈래: 인터페이스 밖에서 정함. 측 표 v4 배치(칸 배열은 QP 항목 바로 뒤 `128 + 128 × nqp`, 고리는 256 B 정렬, 전체 4 KiB 올림, 칸 0이면 v1과 바이트까지 같음); mirror QP는 로그 집합(`nLogged`)에서 뺌; 머리의 mirror 칸은 `gdakiRsStart`에서 `gdakiMiOn(r) && r->mi.ctx >= 0`일 때만; `rsMiPut`은 L보다 큰 put을 깨짐으로, 커서는 `ncclGinMiRound64`, 돌려주는 값 `1 << 32 \| (off >> 6)`; `rsMiWait`는 1 024걸음마다 끝 조건, 10 000걸음마다 abort 낱말, 오류 CQE는 에폭마다 한 번 `q4Report`; 가져오기는 FETCH의 `ckpt`가 다르면 거절, 화신 0의 rkey 차이와 자리 없음은 WARN만, 화신 > 0은 거절(`gdakiMiRkeyVerdict`), pool rkey는 그 생존 rank가 맡은 rank의 칸에 `valid 0`과 함께, 신호와 카운터 표의 rkey는 장치 사본만; 잠금 차례 `gdakiRsWinMu` → `appMu` → `atMu`, `opMu` → `execMu`(Step이 그 잠금을 CUDA 복사와 NIC 원자 연산 동안 쥐어 helper 일부가 그만큼 기다림, 순환 없음); `gdakiMiExecReadMirror`는 QUERY 실패 `ncclSystemError`, 셈 무효 `*valid = false`; `gdakiRsQpsOfPeerAll`은 mirror QP를 마지막에 | notes 원문(커밋 `f95617d5`) |
| 2026-10-14 | dev 갈래: 줄 형식(두 빌드 모두 WARN): `GIN/MI: rank %d: import step %lu: entries=%lu pool_bytes=%lu value_bytes=%lu signals=%lu signal_targets=%zu import_us=%.0f mono_ms=%.3f`(입력이 있는 단계마다), `GIN/MI: rank %d: import done: steps=%d pool_bytes=%lu left=%zu last_step=%lu failed=%d mono_ms=%.3f`(한 번). `GIN_TS_NOTE`: "import plan", "side table v4". 거절 사유는 Resume의 FALLBACK 줄에 실림. 통합 때 할 일(아래 통합 행이 처리): 자리표시 셋, helper 걸음의 `gdakiMiImportHelperStep`, miUse 1을 쓰는 쪽이 `gdakiMiImportMirrorUnusable` QP를 건너뜀, 화신 0 rkey 규칙을 spare의 `gdakiMiRkeyMerge`와 하나로, 되살린 rank 자신의 맡은 rank 칸의 pool rkey, 헤더 글자 "t + 1"과 test의 이어진 단계 가정, 통합 트리에서 `api` 다시. 열린 항목: 자기 루프의 CQ 폴링과 창 검사는 DOCA의 의미에 기댐(`[소스; 실행하지 않음]`), 창 밖 정지 20 ms의 거짓 깨짐 `[추론]` | notes 원문(커밋 `f95617d5`) |
| 2026-10-13 | host 갈래: 구현(갈래 트리 `agent_mi_host/`, i5 위). (1) mirror 문맥: 문맥을 만들 때 사용자 문맥 뒤에 GIN 문맥 하나(QP, GPU 문맥, 자기 루프 쌍; allToAll 없음), pool(호스트 메모리, GIN PD, iova 0, RO 없음), 설정 기록 policyPad의 mirror 비트, 합의 뒤 helper 소켓으로 MIRROR_SETUP(48)과 mirror QP 잇기와 응답 쪽 기준, Resume 조건 34–40(지역 판정과 교환의 모음), mirror 문맥 장애 기록의 흡수(G4에서 `gdakiHoldRoute` 앞, 훑기), 정리(QP 뒤 pool 해제), 변수. (2) 체크포인트 기계의 segment: 멈춤 안 바꾸기, 자기 게시 없이 끝난 멈춤의 되돌리기, 넷째 자리면 다시 시작(PAUSED 뒤 DISARM), CKPT_STABLE, INJECTED, 짝의 새 pool 때 버리기, 10 ms 걸음의 깨짐 → DISARM과 CKPT_PULL(49), Step에서 당기기. (3) 붙잡기 기계: mirror 켬이면 복원 라운드의 게시가 사용자 QP 게이트를 홀수로 남김, RESTORED는 기록만, INJECTED(38)에서 짝수 에폭과 상태 이동, PUBLISHED 시한 min(v1, D), 되살린 rank의 INJECTED 보내기. mirror 끔이면 gin-restore의 길 그대로 | `impl/mi_layer_host.diff`, `impl/mi_unit_host.cc`, notes 원문; 커밋은 아래 행 "커밋" |
| 2026-10-13 | host 갈래: 빌드(`mi`, `mip`)와 `api`, CPU 단위 시험 | 빌드됨: `mi_host2` `2a3fe39f`, `mip_host2` `a882eed5`, 경고 0(이 갈래 파일). 시험함: 16함수, 1 561 826검사, 실패 0. `agent_mi_host/out/build_info.txt`, `impl/mi_unit_host.cc` |
| 2026-10-13 | host 갈래: 독립 리뷰(다른 Opus 에이전트, 읽기만)와 반영 | 11개 중 10개 고침, 1개 해당 없음(위 표). 반영 뒤 다시 빌드와 시험(위 행) |
| 2026-10-13 | host 갈래: 독립 리뷰가 찾은 11개(중간 2, 낮음 9)와 반영. (1, 중간) MIRROR_SETUP 뒤 짝의 mirror QP 묶음 비대칭 → 잇지 않은 쪽이 on = 0인 둘째 기록, 받은 쪽은 helper에서 그 QP를 내림(`gdakiMiSetupConnects`, `SendsOff`, `Demotes`, 두 쪽 사실 4 096 조합 시험); (2, 중간) mirror 켬에서 v1의 "restored as incarnation" 줄이 없음 → RESTORED 때 v1 줄을 글자 그대로; (3) 흡수에 G6 낡은 기록 검사; (4) `gdakiRecRegister` 실패 길 둘의 누수 → `gdakiMiFree`; (5) `gdakiMiTakePool`은 `poolTaken`만; (6) 이미 due인 Step이 당기기를 먹음(`gdakiMiPullConsumes`); (7) INJECTED 보내기의 잃음과 다시 보내기(20 ms마다 50번까지); (8) 걸린 바꾸기 동안 호스트 깨짐의 장부(`gdakiMiLedger*`, 무작위 칸 모델); (9) 해당 없음(INJECTED와 v1 RESTORED는 OFF로 가고 다음 확정에서 무장); (10) 조건 40의 한도 31과 R40 글자 "64"(통합이 헤더 글자를 고침); (11) 시험 보강. 리뷰가 확인한 것: mirror 끔에서 회귀 없음, 장치 대기와 홀수 게시와 INJECTED의 commit이 `tsParkStable`, `tsGiveUp`과 맞음, 다른 갈래 소유 침범 없음. 커밋: 인터페이스 `3fff14a0`, 계층 `da2b4f30`(갈래 브랜치) | notes 원문(커밋 `3e26c05f`), `agent_mi_host/review/mi_host_wip.diff` |
| 2026-10-13 | host 갈래: 인터페이스 밖에서 정함(22). policyPad의 mirror 비트 `1u << 16`(합의 = 모든 rank의 비트 + 복원 결정 "켤 수 있음" + rank 둘 이상, `gdakiRsDecide`는 이 비트를 보지 않음); 조건 37에 S(2–4 밖); 조건 40의 실제 한도는 사용자 문맥 31(32비트 라운드 범위 마스크); Resume 교환 기록에 칸 셋(`miReq`, `miSlots`, `miLane`, magic "GRS3"), 지역 판정 차례 34, 35, 36, 37, 38, (39 모음), 40; MIRROR_SETUP은 모든 rank가 먼저 보내고 읽음(한도 `NCCL_GIN_TS_HANDSHAKE_MS`), 두 기록 모두 on일 때만 잇고 상대 끝점은 상대 문맥 0의 교환 정보 + MIRROR_SETUP의 QPN; miUse는 바꾸기 때 이 rank가 이은 QP면 1, 흡수는 0, 그 짝의 복원 라운드 게시 뒤 1; 다시 시작의 DISARM은 PAUSED를 보낸 뒤; RESTORED(mirror 켬)는 기록만(`gdakiMiApplyRestored`: pad, `gdakiCkptPeerReset`, 짝이면 `gdakiStoreOnBuddyRestored`, 스스로 DISARM); INJECTED의 짝수 쓰기는 사용자 범위의 `gdakiCkptEmptyRound`; 게시의 홀수는 hk `gdakiTsRepostApply`의 게시 쓰기 한 줄을 `eNew \| 1`로(mirror 켬, COMMITTING, 사용자 QP만); INJECTED 줄의 `gate_odd_ms` = 적용 때 − 게이트가 처음 홀수가 된 때; `gdakiMiPoolRekey`는 라운드를 실패시키지 않음(칸을 못 쓰면 lane 깨짐, 자기 rank면 아무것도 안 함); 자기 루프는 100 ms마다 QUERY_QP, RTS가 아니면 그 lane들 끝까지 깨짐; `gdakiMiPoll`은 helper 걸음마다(칸 읽기 10 ms마다, DISARM은 깨짐 묶음마다 한 번, 당기기는 segment마다 한 번); 당기기는 체크포인트 기계가 쉴 때만 먹음; 재기만 하는 모드의 mirror 팔(`NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR`=self\|peer); `struct gdakiMiSegView`를 host 파일에 정의(`openBroken` = 열린 segment가 열릴 때의 누적 깨짐); 요약 줄의 뜻(`max_live_bytes`, `third_slot`, `broken`, `absorbed`); 둘째 MIRROR_SETUP 기록, INJECTED 줄의 `unsent=`; mirror 켬 RESTORED는 v1 줄. 알린 것: dev의 측 표 머리와 `rsLogged`, `gdakiRsQpsOfPeer` 좁힘, 가져오기의 `gdakiMiInjectedReady`; spare의 `gdakiMiPoolRekey`, `gdakiMiAbsorbQp`; store의 `gdakiStoreOnBuddyRestored` 자리표시; 남는 위험: 둘째 MIRROR_SETUP 기록조차 못 보낸 짝은 비대칭(Resume은 38로 거절) | notes 원문(커밋 `3e26c05f`) |
| 2026-10-13 | store 갈래: 구현(RDMA 저장소). 충돌 검토: rs_store_api.h의 경계 목록을 rs_layer.diff의 해당 줄(8410–8574, 8232–8285, 8629–8751, 9259–9361, 7039–7083)과 대조, 설계 충돌 없음. 인터페이스 틈 넷(아래)은 경계 밖 한 줄 hook 셋과 STORE_REQ 뒤 바이트로 메우고 표시함. 붙인 것: (1) 새 영역 "gin-mirror (store): declarations", "pure", "the RDMA checkpoint store": GIN PD의 호스트 RC QP 도구(만들기 INIT, 잇기 RTR/RTS timeout 12 retry_cnt 7 rnr_retry 7, 조각 전송과 CQ 걷기, 한도 넘으면 ERR로), 짝 쪽 저장소(맡은 rank마다 자리 둘의 MR, 0 기준, RO 없음, 세대, 앞 MR이 확정 자리를 쥐면 다음 확정까지 유지), STORE_REQ(50)/STORE_ACK(51)의 양쪽, 올리는 쪽 요청 기계(처음, 배치 바뀜, QP 실패, 짝 화신, 답 없음 5 s, 거절 뒤 1 s), 고정 D2H 버퍼(자리 꼴, GIN PD 등록), 멈춤 안 D2H와 머리와 덩어리, 멈춤 밖 WRITE(application 스레드, `NCCL_GIN_RESTORE_STORE_WRITE_MS` 500), 확정 자리의 판정, 활성화용 `gdakiStoreActInfoOf`, 정리. (2) 체크포인트 기계의 경계 줄: IDLE 거절 "the checkpoint store is not ready", COPYING의 arm, CONFIRMING의 쓰기 상태와 CKPT_STABLE 칸(짝과 나머지 모두), 기반 블록은 TCP 길만, `gdakiCkptOnStable`의 짝 갈래, `gdakiCkptTake` 첫 줄. (3) mirror 끔 TCP 길(9.6): `gdakiCkptUploadOne`의 모든 끝에서 OK ack가 아니면 기반 지움, `gdakiHoldApplyRestored`에서 짝의 RESTORED면 기반 지움 | 빌드 트리 `agent_mi_store/`, [mi_layer_store.diff](mi_layer_store.diff), [mi_unit_store.cc](mi_unit_store.cc), notes 원문 |
| 2026-10-13 | store 갈래: 빌드와 시험(이 갈래가 돌림, 클러스터 없음): 아래 행 "빌드와 시험" | notes 원문 |
| 2026-10-13 | store 갈래: 독립 코드 리뷰(같은 모델의 다른 에이전트, 읽기만): 아래 행 "독립 리뷰" 1 | notes 원문 |
| 2026-10-14 | store 갈래: 리뷰 1, 2의 고침: 호스트 QP와 CQ의 문맥에 `ncclIbStats`(비동기 치명 이벤트를 전송 실패로 셈), STORE_ACK 뒤 바이트(짝의 확정 자리)와 소켓 재설치 뒤 새 요청, RESTORED 한 번 규칙, 줄 끝 `mono_ms`, 멈춘 뒤 상태 재생성 막기, arm 기다림 한도. unit에 소켓 규칙 대조 모델 | [mi_unit_store.cc](mi_unit_store.cc), 아래 행 "인터페이스 밖에서 정함" 10–14 |
| 2026-10-15 | store 갈래: 리뷰 1의 확인(net_ib 소스), 다시 리뷰(높음 0, 중간 1, 낮음 4)와 그 고침: hold 중 앞 MR 미루기, `NCCL_GIN_RESTORE_STORE_MAX_MB`, declined와 붙잡힌 rank의 요청 버리기와 declined rank 저장소 놓기, 실패한 verbs 호출 때 메모리 남기기. 빌드와 시험 다시 | 아래 행 "빌드와 시험", "독립 리뷰" 2, "인터페이스 밖에서 정함" 15–18 |
| 2026-10-13 | store 갈래: 충돌 검토(구현 전)와 "인터페이스 틈". 경계 목록의 줄(IDLE 거절 8440–8446, COPYING 8514, CONFIRMING 8525–8531과 8545–8562, `gdakiCkptOnStable` 8236–8248, `gdakiCkptTake` 9259–9361, `gdakiCkptUploadOne` 8671–8751, `gdakiHoldApplyRestored` 7076 뒤)가 인터페이스의 내용과 같고 host의 segment 줄과 겹치지 않음 `[소스]`. 틈 넷을 경계 밖 한 줄 hook 셋(주석 "hook outside the boundary list: notes_store.md")과 STORE_REQ 뒤 바이트로 메움: (1) `gdakiStoreStep`을 `gdakiCkptStep`의 `gdakiCkptPeerStep` 뒤에, (2) `gdakiStoreFree`를 `gdakiCkptFree`의 `gdakiCkptStop` 뒤에, (3) `gdakiHoldSpareOf` 첫 줄에서 store 길이면 `gdakiStoreSpareOf`(STORE_REQ 80–135 B의 `gdakiStoreReqSpare`: magic "GRSP", 주소, PID, 시작 시각; 되살린 짝은 맡긴 rank의 다음 STORE_REQ `reason=buddy`에서 받음), (4) serve 스레드 대신 저장소 스레드. 통합 순서: (3)은 spare의 활성화 v2와 함께여야 함. 알린 것: FETCH 버퍼와 호스트 QP의 PD가 같아야 함(모두 `collComm->ib.pd`); 기반 계층의 노출 둘 `[추론]`: gin-restore의 GIN PD 루프백 QP 쌍의 빈 qp_context(net_ib 비동기 이벤트 스레드의 널 역참조), `gdakiCkptOnStable`이 붙잡힌 보낸 rank의 CKPT_STABLE도 처리(늦은 기록이 생존 rank의 로그를 활성화가 보낸 단계 너머로 자를 수 있음) | notes 원문(커밋 `1fd83641`) |
| 2026-10-13–15 | store 갈래: "인터페이스 밖에서 정함"(18). 저장소 스레드(문맥마다 하나, 처음 쓸 때 만들고 `gdakiStoreFree`에서 join; 한 맡은 rank의 요청은 하나씩); STORE_REQ 뒤 바이트(`GDAKI_STORE_SPARE_OFF` 80, 56 B); 세대와 앞 MR(확정 자리를 쥐면 다음 확정까지 남김); 올리는 쪽의 확정 자리 보기(CKPT_STABLE을 보낸 뒤); 요청의 때(Resume 뒤, 체크포인트 IDLE, WRITE 없음, 짝 소켓 있고 붙잡히지 않음; 답 없으면 5 s, 실패 뒤 1 s); application 스레드의 차례(배치 → 고정 버퍼 → ASKED → DRAINED → P 복사 → D2H → COPIED → arm 기다림 → WRITE → 쓰기 상태); 호스트 QP(max_send_wr 64, CQ 128, WRITE 조각 ≤ 1 GiB, READ 조각 ≤ 32 MiB, PSN 24비트 무작위, traffic class는 GIN과 같은 차례, 한도 넘으면 ERR와 200 ms 걷기); 줄 수준(키 줄 셋은 `GIN_TS_NOTE`, "store summary"는 두 빌드 모두 WARN, `served=` 더함); summary의 tcp 바이트; 호스트 QP의 qp_context와 cq_context에 `ncclIbStats`; RESTORED 적용은 짝의 화신마다 한 번; STORE_ACK 뒤 바이트(160, 32 B, magic "GRSS")와 소켓 재설치 뒤 새 요청(`reason=socket`); 창이 없으면 250 ms 뒤; `gdakiCkptStop` 뒤 상태 재생성 막기; `NCCL_GIN_RESTORE_STORE_MAX_MB`(4096); hold 중 앞 MR 미루기; declined와 붙잡힌 rank의 요청 버리기; 실패한 verbs 호출 때 메모리 남기기 | notes 원문(커밋 `1fd83641`) |
| 2026-10-15 | store 갈래: 줄 형식, "빌드와 시험", "독립 리뷰". 줄(`GIN/MI: rank %d: ` … ` mono_ms=%.3f`): `checkpoint %lu stored at buddy rank %d slot=%u bytes=%lu d2h_us=%.0f write_us=%.0f`, `store request to buddy rank %d seq=%lu slot_bytes=%lu reason=%s`, `store ready at buddy rank %d gen=%lu stable_slot=%d`, `store summary writes=%lld failed=%lld requests=%lld tcp_image_bytes=%lld tcp_segment_bytes=0 served=%lld`. 빌드와 시험(rain, 2026-10-15): `api` 통과, `mi` `mi_store_v4` libnccl `8b30536d`, `mip` `mip_store_v4` `c9a49f84`, 이 갈래 파일 경고 0, `unit` 6 531 610 checks 0 failed(ASan, UBSan; 모델 200 실행, 불변식 검사 800 000에서 위반 0, 소켓 규칙을 뺀 대조 모델은 불변식을 깸), `mi_layer_store.diff` `50733a4a`; 앞 빌드 v1–v3은 쓰지 않음. 리뷰 1(원문은 사용 한도로 남지 않음 `[미확인]`): 호스트 QP의 빈 qp_context(고침, net_ib 소스로 확인), 다시 놓인 소켓의 읽히지 않은 CKPT_STABLE(고침). 리뷰 2(높음 0, 중간 1, 낮음 4): R1 hold 중 앞 MR 해제(고침), R2 메모리 상한(고침), R3 declined rank 저장소(고침), R4 통합 순서(기록), R5 실패한 destroy와 dereg(고침) | `agent_mi_store/out/build_info.txt`, `unit_v4.log`, notes 원문(커밋 `1fd83641`) |
| 2026-10-13 | spare 갈래: 구현(복원 길, 끝점 갱신). 충돌 검토: 맡은 묶음의 인터페이스와 rs_layer.diff의 해당 줄을 대조, 설계 충돌 없음, 인터페이스가 비워 둔 입구(아래 행 "인터페이스 틈" 1–8, 리뷰 뒤 9)는 자리표시와 메모로 두고 구현. 붙인 것: (1) 생존 rank의 hold 시작에 mirror 읽기(d로 가는 mirror QP의 X, M, 쓰임; 짝으로 가는 길의 M_mir와 쓰임; d 칸의 segment, 커서, 깨짐, 유효를 NIC으로; 닫힌 segment는 host 기록) → HOLDING의 쓰지 않던 칸(pad 깃발 `GDAKI_HOLD_F_MIRROR`), 짝 자신은 제 몫을 그 자리에서 보관; (2) 복원 라운드의 X 확인 뒤 mirror QP만 다시 봄, 움직이면 그 lane 깨짐(`gdakiMiAbsorbQp`), fallback 없음; (3) 짝의 drain(새 영역, helper 걸음마다 조각): 모든 HOLDING 몫이 있고 쓸 만한지(`gdakiMiHoldingVerdict`), K 뒤 바이트가 있는 보내는 rank마다 누적 실행 수 ≥ M_mir(무효 셈이면 거절), 자기 lane은 자기 루프 응답 QP의 MSN, 한도 `NCCL_GIN_RESTORE_DRAIN_MS`와 `_DRAIN_QUERIES`, 그다음 루프백 쌍의 8바이트 READ 울타리, 줄 "drain for rank"; (4) 활성화 판 2: 짝은 기록 + 덩어리(주소와 화신 표, 저장소 자리, pool, K 뒤 extent, FETCH QP 끝점), ACCEPTED 뒤 FETCH 끝점, RTS, READY, 연결과 QP를 기다림 스레드에 넘김; 예비 프로세스는 덩어리를 읽고 검사(모자라거나 깨졌으면 REFUSED), ACCEPTED 뒤 FETCH QP, READY를 받은 뒤에만 READ(저장소 자리, extent 차례), DONE, 이미지를 window에 씀, 첫 REJOIN 전; FETCH 버퍼는 driver 시작에서 등록; (5) 끝점 갱신: 표의 주소(화신 > 0은 표, 0은 기록 유지와 WARN), REJOIN의 QPN 비교(mirror QP 뺌, 자기 화신 0일 때만), TOKEN QPN(화신 > 0과 mirror QP는 TOKEN에서, 0은 기록과 견줌), mirror QP의 rq.exch는 사용자 문맥 0의 끝점 + TOKEN QPN; (6) rkey 목록에 pool(종류 4), 생존 rank의 `gdakiRsSwapRkeys`가 pool 항목으로 맡은 rank들의 칸에 `gdakiMiPoolRekey`; (7) 내보내기 판 2(80 B 항목, 단계와 segment, 원본 바이트 없음, 끝에 자기 rkey 목록), `gdakiHoldTransferStep`에서 mirror 켬이면 부름, 줄 "export to rank"; (8) TCP FETCH 자리(`gdakiCkptSpareFetch`)에서 mirror 켬이면 RDMA FETCH의 머리와 덩어리를 넘겨받음. mirror 끔이면 v1 길 그대로 | 빌드 트리 `agent_mi_spare/`, notes 원문, [mi_layer_spare.diff](mi_layer_spare.diff), [mi_unit_spare.cc](mi_unit_spare.cc) |
| 2026-10-13 | spare 갈래: 빌드와 시험(이 갈래가 돌림, 클러스터 없음): 마지막 소스로 `build_mi.sh mi`(`mi_spare_c2`), `mip`(`mip_spare_c2`), 경고 0; `api` 통과; `unit` `mi_unit_spare` 185 checks, 0 failed(ASan, UBSan). 라이브러리는 "빌드됨"이고 GPU와 RDMA에서는 돌리지 않음. 다른 갈래 진입 함수가 자리표시(`gdakiMiOn` false)라 빌드된 라이브러리에서 mirror 길은 닿지 않음 | 아래 행 "빌드와 시험", `agent_mi_spare/out/build_info.txt` |
| 2026-10-13 | spare 갈래: 독립 코드 리뷰(같은 모델의 다른 에이전트, 읽기만, 대상: 리뷰 전 소스): 찾은 것 14와 통합 확인 다섯. 고친 것 10, 기록만 한 것 4(아래 행 "독립 리뷰"). 고친 뒤 다시 빌드하고 단위 시험을 늘림(160 → 185 checks) | notes 원문 |
| 2026-10-13 | spare 갈래: "빌드와 시험". `setup`(i5 확인, 커밋 `9af58c7`), `paste`(첫 커밋 `140e51fe`, 인터페이스만 `a1beff20`), `mi` `mi_spare_c2` libnccl `d53d0f51`, `mip` `mip_spare_c2` `3df3b40c`, 둘 다 이 갈래 파일 경고 0(바뀌지 않은 `symmetric_sched.cc:327` 하나는 i5 전체 빌드에도 있음), `api` 통과, `unit` 185 checks 0 failed(ASan, UBSan), `diff` `mi_layer_spare.diff` `3b4b6bb8`. 앞 빌드(`mi_spare_p0`, `_c1`, `mip_spare_p0`)는 쓰지 않음. 시험한 것은 순수 영역뿐 → **빌드됨**, **시험함**(단위) | `agent_mi_spare/build_mi_c2.log`, `build_mip_c2.log`, `out/build_info.txt` |
| 2026-10-13 | spare 갈래: 인터페이스 밖에서 정함(16). 활성화 덩어리의 받는 쪽 도우미(`gdakiMiActHdrSane`, 인코드와 디코드, `GDAKI_MI_ACT_MAX_ADDR` 4096), 주소 규칙(`gdakiMiAddrRule`: 화신 0은 기록 유지와 WARN, 화신 > 0에서 주소 0이면 REFUSED), 활성화 차례 상태 기계(`gdakiMiActStep`, `gdakiMiRejoinAllowed`), FETCH 버퍼 배치; REFUSED 이유 8–11; `GDAKI_MI_ACT_FETCH_FAILED`(-2) → 짝이 곧바로 fallback; 짝의 FETCH QP는 READY 뒤 이 갈래의 기다림 스레드가 쥠(DONE, FIN, hold의 남은 시간); FETCH 버퍼는 driver 시작(활성화 소켓 전)에서 등록; 자기 루프 lane의 drain은 연결 때 기준(`gdakiMiSelfBase`)에서 24비트로(10 ms 누적 없이); hold 시작 읽기는 측 표 전체 읽기 + d 칸은 NIC 복사 경로, X만 `gdakiMiExecReadMirror`; HOLDING 몫의 열린 segment 깨짐 = 칸의 누적 − `openBroken`, 닫힌 segment의 `broken[]`은 열려 있던 동안; 읽기 실패면 version 0 몫(짝이 거절, d만 fallback); 예비 프로세스의 mirror QP `rq.exch` = 그 생존 rank의 사용자 문맥 0 끝점 + TOKEN QPN; 화신 > 0인 생존 rank의 사용자 QP는 TOKEN QPN; STORE_REQ는 RESTORED 뒤 helper의 store 걸음; 화신 0 WARN 규칙은 순수 함수 `gdakiMiRkeyRule`, `gdakiMiRkeyMerge`; 내보내기의 64비트 위치(`gdakiMiPos64`); 활성화 한도 밖 처리(drain 거절은 끈적임, 질의 실패는 다시, `gdakiMiActFits`, 반 닫고 읽은 뒤 close); pool rekey는 목록에 pool이 없어도 rkey 0으로, 자기 rank 칸은 건너뜀, rekey 실패는 라운드 실패 | notes 원문(커밋 `8e4e224b`) |
| 2026-10-13 | spare 갈래: "인터페이스 틈"(메인 세션이 정할 것, 아래 통합 행이 처리): (1) HOLDING 몫의 받기는 host의 `gdakiHoldOnMsg` HOLDING 경우에 한 줄(`gdakiMiHoldingTake`); (2) 자기 루프 응답 QP는 `gqps[nContexts × nranks + miCtx]`로 셈; (3) 자기 pool 정보 → 자리표시 `gdakiMiPoolInfoOf`; (4) FETCH 결과 → 접근자 `gdakiMiSpareFetched`; (5) 짝의 FETCH QP는 serve 스레드가 아니라 기다림 스레드; (6) store 길의 예비 프로세스 등록(짝이 주소, PID, 시작 시각을 알 길 없음); (7) `gdakiMiSegView` 깨짐 셈의 뜻, 단계 없을 때 `lastStep`; (8) 자기 rank의 `gdakiMiReadMsgsMirror`; (9) 자기 루프의 MSN 기준 → 자리표시 `gdakiMiSelfBase`(0). 줄 형식(모두 WARN): `drain for rank %d: senders= queries= drain_us=`(짝), `fetch for checkpoint %lu from buddy rank %d: image_bytes= segment_bytes= extents= fetch_us= h2d_us=`(예비 프로세스), `export to rank %d: entries= mirror_entries= mirror_bytes= source_bytes=0 first_step= last_step=`(생존 rank) | notes 원문(커밋 `8e4e224b`) |
| 2026-10-13 | spare 갈래: "독립 리뷰"(14개와 통합 확인 다섯). mirror 끔 동일성 확인(새 길은 모두 `gdakiMiOn` 뒤; 하나만 다름: mirror 끈 예비 프로세스가 판 2 기록에 REFUSED(8), 조건 34의 잘못 설정에서만). 고친 것 10: orphan helper가 쓰는 상태는 `gdakiRecFree`가 지움; 판 2 활성화를 `gdakiTsBusy`로; 자기 루프 drain의 기준을 받음; 복원 라운드에서 움직인 mirror 셈은 `gdakiRsExecInvalidate`도; `gdakiMiActFits`; `gdakiMiCloseAfterAnswer`; drain 거절을 끈적이게; 질의 실패는 다시 묻기; 초기화 안 된 값과 -1 재시도와 끝점; FETCH QP 정리. 기록만 4: 울타리 READ 실패가 루프백 쌍을 깨 같은 rank의 가져오기를 막음(dev의 쌍 잠금이 통합 조건), segment 깨짐의 뜻, READY 뒤 FETCH 실패를 짝이 모름(생존 rank는 시한까지 기다림), pool rekey 실패가 되살린 rank를 거절(의도한 예외). 리뷰의 통합 확인: 예비 프로세스에서 `gdakiMiOn` 참, FETCH 버퍼 MR과 store 호스트 QP가 같은 PD, pool MR에 REMOTE_READ와 RO 없음, 생존 rank의 mirror QP `rq.exch`를 host가 채움, `gdakiMiRkeyMerge`를 부르는 곳 없음 | notes 원문(커밋 `8e4e224b`) |
| 2026-10-13 | test 갈래(시험과 비용): 구현(DRAFT, 빌드됨, CPU 자체 시험함, 클러스터 실행 없음). gin-restore의 `restore/impl/test/`를 바탕으로 `impl/test/`에 새 파일로: 드라이버 `gin_mi.cu`(gin_rs.cu + `RS_OVERWRITE` 4 KiB 덮어쓰기 모드와 `RS_TRAIN` 학습 모양 모드, local 완료 직후 독 값 덮어쓰기, 받는 고리 R, 학습 모양의 상태 이력을 따로 등록), 비용 diff `gin_ts2_mi.diff`(`GIN_TS_MAN_MIRROR` self/peer 둘째 put을 문맥 1로, `GIN_TS_BURST_REUSE`), 실행기 `run_mi.sh`(예비 프로세스 둘, seed kill, 호스트 메모리 시작 검사, KILL_AFTER_STABLE, RS_SET 이름 강제), `cells_mi.sh`·`cells_mi.json`·`hold_mi.sh`·`chain_mi.sh`·`run_cost_mi.sh`·`deploy_mi.sh`·`build_mi_test.sh`·`rs_set_mi.sh`, 채점기 `rows_mi.py`·`score.py`·`predictions_mi.csv`·`selftest_mi.py`, `PILOT_MI.md` | 드라이버는 i5 설치 헤더로 sm_75·sm_86 경고 0 컴파일(md5 아래). `bash -n` 9개 통과, `selftest_mi.py`(파서 명령, 모든 rs 셀의 실행기 dry 설정, seed 결정성, RS_SET 검사, 채점기 A–D) 통과. `impl/test/`, `impl/notes_test.md` |
| 2026-10-13 | test 갈래: 독립 리뷰(같은 모델의 다른 에이전트, 읽기만; 버그 5, 의심 14, 문체 4). 반영: (1) bw2m 비용 값이 지연(µs)으로 남아 대역 판정이 거꾸로 → 모든 bw 지표를 GB/s로 다시 셈. (2) `mi4_seg_32k`, `_128k`의 lane이 1 MiB라 넘침 → 2 MiB, 6 MiB. (3) `nomirror_detect`가 죽음 기준 → 3절대로 FALLBACK + 2 000–2 500 ms. (4) mirror 셀에서 Resume 거절이 제외되지 않음 → `resume_refused`면 `config`. (5) mirror 줄을 고정 순서 정규식으로 읽음 → 키 글자 앞머리만 맞추고 key=value는 순서 없이 읽음. 의심 반영: 둘째 죽음 판정을 3절대로(되살린 짝에 전체 이미지 확정, 그 사이 void ≤ 1, 둘째 kill 전 모든 생존 rank 다시 무장, 죽음마다 복원 ≤ 2 000 ms, 둘째 FETCH가 되살린 짝에서, 되살린 rank 2를 생존 rank로 셈); 둘째 예비 프로세스 시작 실패 제외; mirror와 checksum 설정 불일치 제외; 단계 맞춤 가져오기 차례(`paced_ok`); 비용 규칙 `within_us`, `ratio`(3절의 +2.5 µs와 0.40–0.60 그대로)와 판정 지표만 자료 부족 검사; mirror 팔은 rank 0의 `mirror summary`(broken=0)가 있어야 유효; `pool_vs_interval`의 비 2 ± 25%와 `seg_restore_slope`의 중앙값 증가를 판정식에; `store_rdma`를 학습 셀과 mirror 켠 4 KiB 셀 모두로; 당기기 20단계마다 ≥ 1과 kill 셀의 DISARM 0; gin-restore 7절의 복원과 거절 셀을 그 이름 그대로 mirror 끔 @mi로(R2, R3, 예측 `rg_*`), mirror 켠 회귀는 `_mion`; pilot hold P2, P3; 학습 kill의 단계 안 지연 0–8 ms, `mi4_overflow` 예비 프로세스 기다림 30 s, 학습 시행 한도 150 s; 거절 셀 셋을 이유 글자로 나눔; 문체: 손 mirror 팔의 kv 꼬리표, hold 머리 주석, gin-restore 묶음 재사용 거절 | 리뷰 결과는 이 갈래의 기록. 고친 뒤 자체 시험 다시 통과, 비용 드라이버 다시 빌드(md5 아래) |
| 2026-10-13 | test 갈래: 빌드됨(i5 설치 헤더 digest `6a1a3f29`, sm_75, sm_86, 경고 0): `gin_mi`(매크로) `c382a2db`, `gin_mi_nomacro` `75e15e13`, `gin_ts2_mi` `a0d54cf0`, `mr/ff/gin_mr` `9c56307b`, `mr/hold/gin_mr` `3d2857ae`(통합 헤더로 다시 빌드함: 아래 통합 행). 의존하는 줄: rs_mirror_api.h의 키 11개, rs_store_api.h의 "checkpoint stored", "store summary", gin-restore의 줄(rows_rs.py 그대로); mirror 줄은 키 글자 앞머리만 맞추고 key=value는 순서 없이 읽음. 알림(통합 때 확인할 것, 아래 통합 행): (1) 음성 대조 `mi4_kill3_ow_sampled`의 FALLBACK 이유 "source buffer changed", (2) 재기만 하는 모드의 mirror 팔에 `NCCL_GIN_RESTORE_MIRROR=1`이 필요한지, L보다 훨씬 많이 보내는 측정의 lane 돌려 쓰기, 측정 모드의 teardown "mirror summary", (3) `pool_vs_interval`의 값(`max_live_bytes`), (4) 둘째 죽음 뒤 lane 다시 켜짐은 "armed" 줄로 대신 `[추론]` | notes 원문(커밋 `9badf2e9`) |
| 2026-10-13 | test 갈래: 인터페이스 밖에서 정함(9). 드라이버 독 값 규칙(`poisonWord`, 0xA5); 학습 모양의 상태 이력과 받는 고리(이력은 둘째 등록 버퍼, 요구 14는 구조로: 단계 s 커널은 신호 s % 2와 고리 자리 s mod R만); 비용 드라이버(재기만 하는 모드의 mirror 팔은 라이브러리가 쓰기를 냄, 손 mirror 팔은 feas 폴더의 실행 가능성 확인; 비교는 mirror 가족 안에서만); 셀과 반복 수 초안(`mi4_pull` 나눔, `mi4_refuse_sl` 더함, mirror 끈 회귀는 gin-restore 이름 그대로, 켠 회귀는 `_mion`, `DIE_SEED` `mi-v1`은 자리값, 둘째 죽음 단계 180–220, 380–420); 비용 규칙 `within_us:<x>`, `ratio:<lo>-<hi>`; RS_SET 강제와 `~/rs-bundle/<RS_SET>/{lib/mi,lib/mip,mitest,mr}`; 호스트 메모리 시작 검사(exit 5, `STOP_mem`); 학습 시행 한도 150 s; 당기기 판정은 모든 rank `pulls_sent` 합 ≥ 단계 / 20. 열린 항목: 줄의 실제 꼴, 재기만 하는 모드의 mirror 팔, 단계 맞춤 가져오기의 차례(pilot), 문턱과 seed와 n(사전 등록), 둘째 죽음에서 되살린 rank 2가 rank 3의 예비 프로세스 주소를 아는지 `[미확인]` | notes 원문(커밋 `9badf2e9`), [impl/test/PILOT_MI.md](impl/test/PILOT_MI.md) |
| 2026-10-15 | 다섯 갈래의 통합(메인 세션이 맡김; 감독 메모 `mi_integration.md`, 세션 스크래치). 저장소 수준: `exp/gin-mirror`(`bac72ba6`)에서 새 갈래 `exp/gin-mirror-int`(worktree `~/rdma-error-wt/gin-mirror-int`)를 만들고 갈래 다섯의 커밋 18개를 dev, host, store, spare, test 차례로 그대로 옮김(cherry-pick; 파일이 겹치지 않아 충돌 없음, 작성자와 메시지 그대로, 해시만 바뀜: dev `9434a824`→`a220a1da`, `ed3a2bed`→`ecea219a`, `d125d24b`→`d8453dfb`, `a5a016a0`→`f95617d5`; host `3fff14a0`→`83c76791`, `da2b4f30`→`1474b954`, `e5e61226`→`3e26c05f`; store `a2db9095`→`58610b52`, `89fedcbb`→`59d207e2`, `8b4e70f3`→`1fd83641`; spare `140e51fe`→`bf3178bd`, `667c7523`→`9598f2bf`, `dc4aa29f`→`a292b6d0`, `df4abb8a`→`8e4e224b`; test `49056b67`→`d7e6db98`, `ab39a56d`→`bc00e771`, `986f00a4`→`f633e203`, `e168cec2`→`9badf2e9`). 커밋된 `mi_layer_<갈래>.diff`의 md5가 갈래 빌드 트리의 작업 트리 diff와 같음(dev `b9ecd9fa`, host `7f313c32`, store `50733a4a`, spare `3b4b6bb8`) `[측정]` | 브랜치 `exp/gin-mirror-int` |
| 2026-10-15 | 소스 수준 통합. 통합 빌드 트리 `agent_mi_int/`(세션 스크래치)를 `BR=int build_mi.sh setup`으로 만듦(i5 확인: rs_layer.diff `f005bb67`, libnccl `4811f28f`, `be91b270`; i5 커밋 `aa20f30`). 그 git의 clone `agent_mi_int/merge`에서 갈래마다 i5 + 그 갈래 diff를 i5 위 커밋으로 두고(다시 만든 diff md5가 갈래의 것과 같음) dev 위에 host, store, spare를 3-way로 합침(diff3, `-Xdiff-algorithm=histogram`; 기본 Myers는 정렬이 어긋나 거짓 충돌 일곱 덩어리를 냄). 충돌은 하나: dev의 "gin-mirror (dev): import"와 spare의 "gin-mirror (spare): restore path"가 같은 자리(dev 로그 영역의 끝 표시 뒤)에 들어감 → 둘 다 둠(dev 다음 spare). 확인: 세 파일의 모든 줄 수가 "바탕 + 갈래 넷의 증감 − 인터페이스 붙이기 증감 × 3"(같은 붙이기를 넷이 했으므로)과 같음, 어긋난 줄 0 `[측정]`. host만 붙인 hold 공유 글 v2는 그대로 들어옴 | `agent_mi_int/merge/`(커밋 차례), `agent_mi_int/review_i1/gin_host_gdaki.merged_raw.cc` |
| 2026-10-15 | 이음(자리표시를 지우고 진입 함수를 이음; 손으로 고친 것 전부는 `review_i1/integration_edits.diff`와 그 뒤 리뷰 반영). 지운 자리표시: dev의 셋(`gdakiMiOn`, `gdakiMiInjectedReady`, `gdakiMiSpareFetched`), spare의 열넷(`gdakiMiOn`, `gdakiMiQpOfPeer`, `gdakiMiExecReadMirror`, `gdakiMiAbsorbQp`, `gdakiMiSegViewOf`, `gdakiMiPoolRekey`, `gdakiCkptStepPairs`, `gdakiStoreActInfoOf`, 호스트 QP 도구 넷, `gdakiMiPoolInfoOf`, `gdakiMiSelfBase`)과 겹친 `NCCL_PARAM(GinRestoreMirrorFetchMb)`, spare가 다시 적은 구조체 둘(`gdakiMiSegView`, `gdakiStoreActInfo`), store의 `gdakiMiOn`, host의 `gdakiStoreOnBuddyRestored`. 갈래가 비워 둔 진입 함수 셋을 host 영역에 정의: `gdakiCkptStepPairs`(ck->mu 아래 ck->steps에서 머리가 `from` 위인 (단계, 머리) 쌍, lastStep = 가장 새 쌍의 단계, 모두 정리됐으면 확정 단계, 기록 없으면 `GDAKI_RS_STEP_UNKNOWN`; 확정 체크포인트의 절단점 위 쌍은 정리되지 않아 내보내기 범위가 다 있음), `gdakiMiPoolInfoOf`(자기 pool의 rkey 호스트 순서, L, S), `gdakiMiSelfBase`(자기 루프를 이은 바로 뒤 `gdakiMiContextSetup`에서 읽은 응답 쪽 MSN). `gdakiMiSpareFetched`는 spare의 꼴(포인터, FETCH 성공 전 null)로 하고 `gdakiRsSpareDataFdImport`는 null이면 빈 결과(가져오기가 "이 복원의 것이 아님"으로 거절)를 넘김. helper 걸음(`gdakiHoldStep`)에서 `gdakiMiPoll` 앞에 `gdakiMiImportHelperStep`과 `selfEnded` 돌아감. 갈래가 남의 함수에 넣은 한 줄 hook을 모두 확인(아래 리뷰 행이 다시 셈) `[소스]` | [impl/mi_layer.diff](impl/mi_layer.diff), `agent_mi_int/review_i1/` |
| 2026-10-15 | 통합의 판단(감독 메모의 항목마다; 넘긴 갈래의 메모는 위 행들). (1) 화신 0 rkey 규칙을 하나로: 화신 0이면 차이와 자리 없음 모두 WARN(기록 값 유지), 화신 > 0이면 거절. dev 가져오기(`gdakiMiImportPrepareLocked`, `gdakiMiRkeyVerdict`)가 이미 이 규칙이고, spare의 `gdakiMiRkeyMerge`의 자리 검사(화신과 상관없이 거절하던 것)를 맞춤; 가져오기는 장치 읽기와 함께 자기 구현을 쓰고 merge는 같은 규칙의 순수 기술로 단위 시험이 봄. (2) 되살린 rank 자신이 맡은 rank(자기 루프 lane) 칸의 pool rkey는 host의 segment 바꾸기가 씀: 바꾸기는 짝이 이 rank면 `ownRkey`(예비 프로세스가 초기화 재생 때 등록한 자기 pool)를 칸에 쓰고, 칸은 바꾸기 전에는 유효가 아님(가져오기는 쓰지 않음; dev 메모의 "바꾸기는 rkeyBe를 쓰지 않는다"는 헤더 글에서 온 것이라 헤더 글을 고침). (3) 되살린 rank의 mirror QP에 miUse 1을 쓰는 쪽은 host의 `gdakiMiPathReady`(그 rank의 첫 바꾸기): REJOIN이 이은 QP에 쓰되 `gdakiMiImportMirrorUnusable`이면 쓰지 않고 givenUp으로 두어 그 상대의 복원 라운드가 다시 무장. (4) RESTORED: mirror 켬은 host의 `gdakiMiApplyRestored`가 짝일 때, mirror 끔은 v1 길이 store의 `gdakiStoreOnBuddyRestored`를 부름(한 RESTORED에 한 길만, 그 함수는 짝의 화신마다 한 번). (5) `gdakiHoldSpareOf`의 store hook, spare의 활성화 v2, STORE_REQ 뒤의 예비 프로세스 정보(주소, PID, 시작 시각)가 모두 들어옴: spare 메모의 열린 설계 틈과 test의 열린 항목(되살린 rank 2가 rank 3의 예비 프로세스를 아는지)은 rank 3의 RESTORED 뒤 STORE_REQ(`reason=buddy`)로 풀림 `[소스]`. (6) host의 `gdakiHoldOnMsg` HOLDING 경우의 spare 한 줄(`gdakiMiHoldingTake`, 짝일 때만, inc = m.round) 승인. (7) 생존 rank의 mirror QP `rq.exch`는 host가 문맥 만들 때(상대 문맥 0의 교환 정보)와 MIRROR_SETUP(QPN)에서 채움, 예비 프로세스는 spare가 TOKEN QPN으로. (8) dev의 루프백 쌍 잠금(`atMu`)을 spare의 울타리 READ도 씀; 울타리 READ가 실패하면 쌍이 끈적이게 깨져 그 rank의 뒤 drain이 모두 거절(그 맡은 rank들의 복원 fallback): 고치지 않고 기록. (9) PD: pool, FETCH 버퍼, 저장소 MR과 고정 D2H 버퍼, 호스트 QP, 루프백 쌍, GDAKI QP가 모두 `collComm->ib.pd` `[소스]`. (10) 헤더 글: R40 "64" → "mirror 문맥을 만들지 못함(사용자 문맥은 31까지)"(조건 40은 다른 까닭에도 쓰여 글을 넓힘), switch가 rkey도 씀, `gdakiMiInjectedReady(r, t + 1)` → "마지막으로 넣은 단계", `gdakiMiSegView`의 셈(닫힌 segment의 `broken[]`은 열려 있던 동안, `openBroken`은 열릴 때의 누적 값), `gdakiMiSegStable`의 차례, 측정 팔과 FETCH 버퍼 변수의 글, 진입 함수 선언 셋(`gdakiMiPoolInfoOf`, `gdakiMiSelfBase`, `gdakiMiSpareFetched`), 내보내기 `mirM`의 뜻. (11) "import step" 줄은 dev대로 입력이 있는 단계만(빈 단계는 줄 없음), test의 `rows_mi.py`가 틈을 받게 고침(단계는 start_step부터 늘기만, INJECTED의 단계는 "import done"의 last_step), "import done" 줄 그대로. (12) 체크섬 대조 셀의 FALLBACK 이유: `gdakiRsLogExport`의 "source buffer changed (entry …)"가 생존 rank의 "the log export failed: …"로 `gdakiHoldFallback`의 "is given up (%s)"에 실림, 셀의 정규식 그대로 맞음 `[소스]`. (13) 측정 모드의 mirror 팔: `NCCL_GIN_RESTORE_MIRROR=1`이 필요(mirror 문맥, 합의; 실행기가 줌); lane 돌려 쓰기는 helper 걸음(약 1 ms)마다 L/2를 넘은 커서를 0으로(전에는 측정 주기 50 ms마다라 빠른 팔이 L을 넘음), 기기의 깨짐을 요약의 broken=에 더함, "mirror summary"를 두 빌드 모두 WARN, 측정 팔 줄도 WARN; 비용 실행기의 기본 L 256 MiB, S 2. (14) "checkpoint stored"는 `GIN_TS_NOTE`(연구 빌드 WARN): 복원 셀은 모두 연구 빌드 `mi`, 비용 셀(`mip`)은 WARN인 요약 줄만 읽음. (15) 학습 셀과 덮어쓰기 셀의 둘째 죽음은 드라이버의 단계 kill(`GIN_RS_DIE_AT`, `run_mi.sh` die_env), 예비 프로세스는 그 변수를 받지 않음 `[소스]`. (16) `pool_vs_interval`은 예측의 말대로 `max_live_bytes`(`max_fill=` 키는 더하지 않음; 3절 글과의 맞춤은 사전 등록에서). (17) GIN PD 루프백 원자 쌍(gin-restore i5의 것, mirror가 울타리 READ로 둘째 사용자)에 `ncclIbStats`를 qp_context와 cq_context로(store 리뷰 1과 같은 꼴의 널 역참조 막음). 하지 않은 것(기록): READY 뒤 FETCH 실패를 짝에 알리기(spare 제안; 생존 rank는 지금처럼 시한에 fallback), hk의 NIC 복사 경로 루프백 쌍의 빈 qp_context(hk 코드, 이 계층이 새로 쓰지 않음), `gdakiCkptOnStable`이 붙잡힌 rank의 늦은 CKPT_STABLE을 처리(gin-restore 기반, mirror 켬에서는 내보내기 거절로 끝남), 한쪽만 이은 MIRROR_SETUP의 남는 비대칭(Resume 38) | [impl/mi_layer.diff](impl/mi_layer.diff), 헤더 여섯, [impl/test/rows_mi.py](impl/test/rows_mi.py), [impl/test/run_cost_mi.sh](impl/test/run_cost_mi.sh) |
| 2026-10-15 | 통합의 빌드 스크립트: [impl/build_mi.sh](impl/build_mi.sh)가 `BR=int`의 diff를 `impl/mi_layer.diff`로 씀(diff, info, mi 단계), `impl/mi_unit_dev.cc`의 include 차례를 고침(gin-restore 순수 영역이 이제 host 갈래의 Resume 이유 34–40 매크로를 써서 mirror host API 헤더를 먼저), `impl/mi_unit_spare.cc`에 통합 규칙의 자리 검사 넷(화신 0은 WARN, 1은 거절). 시험 쪽: [impl/test/build_mi_test.sh](impl/test/build_mi_test.sh)의 헤더와 출력이 통합 트리(`agent_mi_int/build/include`, `agent_mi_int/test/out/`), [impl/test/deploy_mi.sh](impl/test/deploy_mi.sh)의 드라이버 폴더 | 커밋(아래) |
| 2026-10-15 | 통합 빌드됨(rain, nice 19, sm_75와 sm_86, GPU와 RDMA 실행 없음). 첫 빌드 `agent_mi_int/out/mi_i1` libnccl `a5cd1f87`, `mip_i1` `1e6c77dc`(공통 헤더가 바뀌어 장치 객체까지 각 390개 컴파일, 4 분 58 초와 5 분 6 초): 경고는 각 하나(i5 전체 빌드에도 있는 바뀌지 않은 `scheduler/symmetric_sched.cc:327`), 이 계층의 세 파일에 0. 리뷰 반영 뒤 마지막 `mi_i2` libnccl `1b50d11b28ca0d827dde07fc2a3d6411`, `mip_i2` `a34db6e65ac75187618cee236010dae9`(호스트 파일 하나만 컴파일, 경고 0). 운영 빌드의 설치 헤더가 연구 빌드와 같음(`mip` 단계 검사). `api`: 붙인 블록 다섯이 헤더와 바이트까지 같음(hold 공유 글 v2, 체크포인트 v1), 헤더 여섯이 함께 컴파일됨(선언 있음과 없음) → **빌드됨** `[측정]` | `agent_mi_int/build_mi_i1.log`, `build_mip_i1.log`, `build_mi_i2.log`, `build_mip_i2.log`, `api_i2.log` |
| 2026-10-15 | 통합 시험함(CPU 단위 시험, rain, g++ 8.4 `-std=c++17 -O1`, ASan과 UBSan, `BR=int build_mi.sh unit`, 마지막 소스): `mi_unit_dev` 568 999 checks 0 failed, `mi_unit_host` 1 561 826 checks 0 failed(16 함수), `mi_unit_store` 6 531 610 checks 0 failed(모델 200 실행, 불변식 검사 800 000에서 위반 0), `mi_unit_spare` 187 checks 0 failed(갈래의 185 + 통합 규칙 2) `[측정]`. test의 `selftest_mi.py` 통과(파서, 실행기 dry 설정, seed, RS_SET, 채점기); 고친 시험 줄을 넣기 전후의 자체 시험 출력 158줄이 같음 `[측정]` | `agent_mi_int/unit_i2.log`, `agent_mi_int/stcmp/` |
| 2026-10-15 | fail-fast 기계어(`BR=int MIOUT=mi_i1 build_mi.sh ident`, dev의 `ff_cmp_mi.sh`, `exact_cmp_mi.sh`; GPU에서 돌리지 않음; rc 0, 19 분 47 초): 매크로 없는 프로그램 넷(`ff_ops`, gin_ts2, gin_mr, ring) × sm_75, sm_86 = 8/8이 hk와도 i5와도 SASS 전체와 -res-usage가 같음; 라이브러리 장치 객체가 i5와 205 그대로 + 2(`device_glue.o`, `onerank.cu.o`)는 컴파일 해시만 다름, 다른 것 0(연구와 운영 둘 다); hk와는 183 + 2 같고 22 다름(모두 hk 트리의 낡은 symmetric 객체, i5도 같음); libnccl -res-usage(해시 가린 이름)가 i5, hk와 같음(1 472 같음, 다름 0, 두 빌드). 매크로 변형(m)은 경고 0, 자원이 i5의 m과 다름(ff 22 중 11, gin_ts2 20 중 4, gin_mr 4 중 1, ring 8 중 8: mirror 기다림의 비용, 비용 팔이 잼). 마지막 빌드 `mi_i2`, `mip_i2`로 다시(rc 0, 19 분 48 초): 같은 결과(8/8; i5와 205 + 2, 다름 0; hk와 183 + 2, 22; -res-usage 1 472 같음, 두 빌드) `[측정]` | `agent_mi_int/ident_i1.log`, `ident_i2.log`, `sass_mi_i1/`, `sass_mi_i2/` |
| 2026-10-15 | 통합 계층 diff와 정보: [impl/mi_layer.diff](impl/mi_layer.diff) md5 `e27998db08ffce272b65992b8ae5634a`, 8 119줄(바뀐 파일 셋: `gin_gdaki.h`, `gin_gdaki_device_host_common.h`, `gin_host_gdaki.cc`; i5 커밋 위 작업 트리, histogram, 거꾸로 적용 확인), `build_mi.sh info` → `agent_mi_int/out/build_info.txt`. 갈래 diff 넷(`mi_layer_<갈래>.diff`)은 그 갈래의 기록으로 남김 | `agent_mi_int/out/build_info.txt` |
| 2026-10-15 | 시험 드라이버 빌드됨(통합 헤더, 설치 헤더 digest `6f79fb99`, `MIOUT=mi1`, 경고 0, `agent_mi_int/test/out/`): `gin_mi`(매크로) `a1b84951026e377170c2da9471571882`, `gin_mi_nomacro` `03fea825857861e7703bd09f704e03bb`, `gin_ts2_mi`(손 mirror 팔 포함, 매크로) `149cb36630ec7c10189299b0c58454cc`, `mr/ff/gin_mr` `878cc130e3f6cfe4b2b0a553c75c9510`, `mr/hold/gin_mr` `b8b50797eb0f90422e39e43b770ae6cc`. 마지막 라이브러리 빌드 뒤 설치 헤더 digest가 같아(동적 링크) 다시 빌드하지 않음 `[측정]`. nvcc 출력은 재현되지 않아 i5 헤더로 만든 갈래의 md5와 다른 것은 뜻이 없음 | `agent_mi_int/test/build_test_mi1.log` |
| 2026-10-15 | 통합의 독립 리뷰 1(라이브러리; 같은 모델의 다른 에이전트, 읽기만, 고정한 사본 `agent_mi_int/review_i1/`, diff md5 `fbf8a726`). 검토자가 단위 시험 넷을 사본에서 다시 빌드해 0 failed, 붙인 블록 다섯이 바이트까지 같음, 자리표시가 남지 않음, 한 줄 hook이 모두 한 번씩 제자리, 판단 (1)–(9)가 맞음, 잠금 순환 없음, 정리 차례, 도중의 죽음은 모두 정해진 되돌림이나 void나 fallback으로 끝남. 판정: "integration: no blocking issue". SHOULD-FIX 1: 생존 rank가 hold 시작에 셈이 무효면 mirror QP의 M을 내보내지 않아, 그 QP를 나중에 다시 무장하면 되살린 rank의 응답 쪽 기준이 0이라 뒤 drain이 거절(갈래 사이의 어긋남, 통합 전부터; 시한 안의 fallback, 자료 손상 없음). NOTE 여섯: 가져오기의 "쓸 수 없음"이 그 상대의 복원 라운드가 바꾸기보다 먼저 게시하면 지워지지 않음(보호 범위만 줄어듦; 4 rank pilot에서는 짝끼리의 쓰지 않는 QP라 무해), 측정 모드 L의 주석, `selfBaseOk`가 Resume 조건이 아님, 넘어온 열린 항목들(울타리 READ, READY 뒤 FETCH 실패, 늦은 CKPT_STABLE, `gdakiRsAtomicOp`의 널 검사), 낡은 주석, 내보내기 `lastStep`의 뜻 | 리뷰 결과는 이 세션이 받음(본문은 세션 기록) |
| 2026-10-15 | 통합의 독립 리뷰 2(impl/test; 같은 모델의 다른 에이전트, 읽기만, 고정한 사본 `review_i1/test/`; 클러스터 명령 없음, 사본에서 `selftest_mi.py` 통과, `bash -n` 여덟). 판정: "test: 1 blocking issue". MUST-FIX: 비용 mirror 팔이 라이브러리 기본 L 1 MiB를 써 모든 팔이 깨짐(고정한 사본; 작업 트리는 이미 고침). SHOULD-FIX: cells가 끝내 유효가 되지 않은 팔도 broken=0이라 유효로 셈; 자체 시험의 합성 줄이 실제 printf와 다름(콜론, 빠진 키, gin-restore 옛 글) 그리고 틈 있는 가져오기 경우가 없음; `export to rank` 정규식이 거절 줄도 잡음; PILOT_MI.md의 배포 경로가 없는 폴더. NOTE: RS_SET 글자 제한, 배포 전 sunny ssh 확인, gin_mr 남은 프로세스를 경로로 세지 않음, `paced_ok`에 failed=0, hold 한도와 예비 프로세스 시행. 확인된 것: 모든 kill은 기록한 PID를 comm과 부모 PID로 확인한 뒤(두 노드, 셋째 경우까지), pkill과 이름 kill 없음, 배포는 있는 대상과 gin-restore 묶음을 거절하고 md5와 기존 파일 전후를 봄, 읽는 줄의 접두와 키가 실제 형식과 맞음(연구 빌드에서 모두 WARN), "source buffer changed"의 길, `paced_ok`가 라이브러리와 맞음, 둘째 죽음은 드라이버 단계 kill | 리뷰 결과는 이 세션이 받음 |
| 2026-10-15 | 리뷰 반영(빌드 i2). 라이브러리: 생존 rank가 hold 시작에 mirror QP의 M을 X의 유효와 상관없이 내보내고 가져오기가 응답 쪽 기준 M을 늘 씀(내보내기 머리 `mirM`의 글도); `selfOk` = 자기 루프를 잇고 그 기준을 읽음(못 읽으면 Resume 38); `gdakiRsAtomicOp`의 로그 상태 널 검사; 측정 팔 줄 WARN; 낡은 주석과 헤더 글. 남긴 것: "쓸 수 없음"이 지워지지 않는 경우(보호 범위만), 넘어온 열린 항목들(위 판단 행). 시험: 비용 실행기의 L 256 MiB(헤드룸 약 10 ms), `mi_summary_ok`에 max_live_bytes > 0, 자체 시험의 GIN/MI 합성 줄을 실제 형식으로(틈 있는 가져오기 101, 103 포함; gin-restore 옛 글의 회귀 합성 줄은 그 실험의 파서가 읽는 그대로 둠), `export to rank (\d+):`, `paced_ok`에 failed=0, RS_SET은 `[A-Za-z0-9._-]`만, 배포 전 sunny ssh 확인, hold의 남은 프로세스 셈에 `/tmp/gin_mrr_`, PILOT_MI.md의 명령과 경로. 다시: `api`, 단위 시험 넷, 자체 시험, 빌드 i2, ident i2(위 행들) | [impl/mi_layer.diff](impl/mi_layer.diff), [impl/test/](impl/test/) |
| 2026-10-15 08:59–09:15 | pilot 1(채점 제외; 메인 세션이 실행, `cluster_run.sh` 안의 `chain_mi.sh`): 배포 묶음 set `mi1`(통합 빌드 i2: `mi_i2` libnccl `1b50d11b`, `mip_i2` `a34db6e6`, `gin_mi` `a1b84951`, `gin_ts2_mi` `149cb366`), hold P1, P2, P3, COSTPILOT-rain, COSTPILOT-sunny 차례로 모두 hold rc 0(08:59:39–09:15:35), STOP 없음, 남은 프로세스 없음. 셀마다 시행 n=1(복원과 거절 셀 23, gin-remaining 회귀 2, 비용 팔마다 노드마다 k1로 40). 생존 rank rc는 0, 다만 설계한 길 셋이 4(`mi4_kill3_ow_nomirror` 데이터 비교 실패, `mi4_kill3_ow_sampled` fallback, `mi4_overflow` fallback, wall 32.8 s), `mi4_train_kill2_kill3`이 4(결함 C, wall 123.1 s), `reg_rm4_kill3_untimed_hold`가 4(device_error, gin-remaining의 원래 결과) `[측정: 각 hold_*.out의 셀 줄]`. 복원 시간(`rows_mi.py`로 다시 셈, ms): kill1_ow 196.4, kill3_ow 198.3, kill3_ckpt_ow 197.0, kill2_kill3_ow 202.7과 206.7, pull 176.6, seg_4k 197.0, seg_128k 197.8, rs4_kill3_mion 198.8, train_kill3 276.2, mirror 끈 회귀 rs4_kill3 391.0, rs4_kill3_ckpt 378.9. 찾은 결함 넷(아래 행들): A 복원 뒤 생존 rank의 lane이 되살린 rank 쪽으로 차서 깨짐(kill 셀마다 12–250줄), B rc 4 셀 셋(점검 결과 설계 길), C 학습 모양 둘째 죽음 실패, D 비용 peer 팔이 mirror를 안 씀(모든 peer 실행 `mi_summary_ok` 0) | 원자료 `../gin-mirror-int`의 `results/20261015_pilot/`(`exp/gin-mirror-int` worktree, release 전; `chain.out`, `hold_*.out`, `raw/`, `reg/`, `costpilot_*/`) |
| 2026-10-15 | pilot 1(set `mi1`; 원자료 `results/20261015_pilot/`, `exp/gin-mirror-int` worktree, release 전)이 찾은 결함 넷을 고치는 갈래 `exp/gin-mirror-fix`(worktree `~/rdma-error-wt/gin-mirror-fix`, `0544a03b`에서 갈라짐). 빌드 트리 `agent_mi_fix/`(세션 스크래치)는 `agent_mi_int/`의 복사(nccl-src, build, build-mip; 의존 파일과 장치 manifest의 절대 경로를 바꿈, mtime 유지). 복사본의 작업 트리 diff md5가 i2의 `e27998db`, 라이브러리가 `1b50d11b`, `a34db6e6`임을 확인. [impl/build_mi.sh](impl/build_mi.sh)가 `BR=fix`를 int처럼 받음(setup은 거절: 복사는 손으로 함). 결함마다 원자료(rank 로그, 예비 프로세스 로그, 비용 로그)와 소스를 대조한 뒤 고침. 클러스터 실행 없음 | 커밋 `84a7522c` |
| 2026-10-15 | 고침: 되살린 rank의 저장소 요청(pilot 1 결함 A, "복원 뒤 생존 rank의 lane이 되살린 rank 쪽으로 L까지 차고 DISARM"). `[측정]` 되살린 rank는 Resume 바로 뒤 짝에게 STORE_REQ를 한 번(seq 1, reason=first) 보냈고 "store ready at buddy"가 끝내 없었다(mi4_kill1_ow, mi4_kill3_ow, mi4_pull, mi4_seg_4k, mi4_seg_128k, mi4_train_kill3, rs4_kill3_mion; 짝 쪽에도 그 요청의 "store for rank N ready" 없음). 그래서 되살린 rank는 끝까지 체크포인트를 "the checkpoint store is not ready"로 찍지 않았고(시행마다 2–110줄), 보내는 rank는 그 rank의 segment를 바꾸지도 버리지도 못해 lane이 50%에서 CKPT_PULL(받는 쪽이 체크포인트를 못 찍음), L에서 깨짐. mi4_kill3_ckpt_ow만 5 000 ms 뒤 다시 청하기(seq 2, reason=retry)로 준비됐다(짝 줄 "store for rank 3 ready (request 2) gen=2", INJECTED 뒤 4.85 s; 그 뒤 체크포인트 451부터 올라감). `[소스]` 짝은 mirror 켬에서 되살린 rank를 INJECTED까지 PUBLISHED(붙잡은 상태)로 두고, `gdakiStoreDropReq`가 요청의 화신을 아는 화신(`gdakiRsPeerInc`; 받아들인 REJOIN이 이미 새 화신으로 바꿈)과 견줘 `reqInc <= knownInc`면 답 없이 버렸다(INFO 줄이라 원자료에 없음). lane 깨짐 줄은 원자료에서 다시 셈: 시행마다 2줄은 hold 동안 죽은 rank를 짝으로 둔 rank 쪽 lane(9.6절 짝 보호 공백, 설계대로; mi4_kill3_ckpt_ow는 0줄), 나머지가 되살린 rank 쪽(15, 13, 125, 250, 18, 23, 12; 합이 메인 세션 메모의 17, 15, 127, 252, 20, 25, 12와 같음). 고침: 버림 판정이 hold 칸의 화신(죽은 프로세스의 것)과 견줌. 되살린 프로세스의 요청은 HELD, COMMITTING, PUBLISHED에서도 받고, 죽은 프로세스의 남은 요청만 버림(그 줄은 연구 빌드 WARN). 단위 시험에 PUBLISHED 경우. 설계 바뀜 없음(9.4절 8번 "되살린 d도 자기 짝에게 청한다"가 설계대로 됨). 영향 셀: mirror 켠 복원 셀 모두(mi4_kill1_ow, mi4_kill3_ow, mi4_kill3_ckpt_ow, mi4_kill2_kill3_ow, mi4_pull, mi4_seg_4k, mi4_seg_32k, mi4_seg_128k, mi4_train_kill3, mi4_train_kill2_kill3, rs4_kill3_mion)과 깨짐 0, DISARM 0 조건의 예측(`pull_no_disarm`, `train_pull_count`). 남는 것 `[소스]`: 되살린 rank는 자기 예비 프로세스가 없어 그 뒤 체크포인트가 "not armable"(gin-restore 규칙, `gdakiCkptSelfOf().haveSpare`)이므로 고친 뒤에도 다시 무장되지 않음. 고침이 되찾는 것은 그 rank의 체크포인트, segment 바꾸기와 버리기, 로그 다듬기, lane 깨짐 없음 | 커밋 `15cb1b0a`; 원자료 `raw/*_spare.log`, `raw/*_r2.log` |
| 2026-10-15 | 점검: rc 4로 끝난 셀 셋(pilot 1 결함 B), 바꾼 것 없음 `[측정]`. (1) `mi4_overflow`(lane 2 KiB < put 4 KiB): 모든 lane이 깨짐(77줄), rank 3은 kill 때 무장되지 않아 hold 없이 거절, 생존 rank의 대기는 죽음 판정 + 2 002.8 ms에 degraded로 풀림(rc 4): `overflow_failfast`의 설계 길. wall 32.8 s는 셀이 정한 `SPARE_WAIT_MS` 30 000이다: 활성화되지 않을 예비 프로세스가 30 s를 기다리고("no usable ACTIVATE within 30000 ms") 실행기가 그 끝을 기다린다. 생존 rank는 예비 프로세스 준비 뒤 약 6.1 s에 끝남. 라이브러리의 기다림 버그 아님. 관찰 `[추론]`: 이 시행에서 rank 3이 체크포인트 60에서 한 번 무장됨(깨짐의 DISARM이 그 확정 뒤에 옴). kill이 그런 때에 나면 hold가 시작되고 내보내기가 깨짐으로 거절해 fallback이므로 예측의 "hold 시작 줄 없음"이 시행에 따라 어긋날 수 있음(사용자 판단). (2) `mi4_kill3_ow_sampled`(mirror 끔, checksum 표본): 내보내기 "source buffer changed (entry 0, window 2, offset 8192, 4096 bytes)", FALLBACK, 대기는 fallback + 2 000.2 ms에 풀림: `nomirror_detect`의 설계 길, lane 깨짐 0(결함 A와 무관), wall 9.0 s. (3) `mi4_kill3_ow_nomirror`(mirror 끔, checksum 끔): 복원 310.6 ms(TCP 길), 600단계를 모두 가고 마지막 데이터 비교가 "xchg=bad"라 모든 rank가 driver의 비교 실패 코드 4로 끝남: 설계한 손상 대조(`nomirror_corrupt` 1) | 원자료 `raw/mi4_overflow_mi_n1_*`, `raw/mi4_kill3_ow_sampled_mi_n1_*`, `raw/mi4_kill3_ow_nomirror_mi_n1_*` |
| 2026-10-15 | 고침: mirror 켠 프로세스의 window를 NIC 복사 경로에서 뺌(pilot 1 결함 C, 학습 모양 둘째 죽음 `mi4_train_kill2_kill3` 실패). `[측정]` rank 2의 예비 프로세스(rain의 셋째 프로세스)가 시작에서 "restore_buffers_in_nic_path=0 why=cannot register the GPU memory of the window (errno 14)"로 Resume을 거절했고(rc 5, kill보다 먼저), rank 2가 단계 496에서 죽자 짝 rank 3이 "the peer's spare does not answer the activation"으로 fallback, 생존 rank가 단계 497에 degraded(rc 4). 다른 모든 프로세스는 "restore_buffers_in_nic_path=1". rain BAR1 Total 256 MiB, sunny 16 384 MiB(`hold_P2.out` 7–8줄). wall 123.1 s는 둘째 예비 프로세스(rank 3)의 활성화 기다림 120 000 ms(활성화되지 않음). `[소스]` side table 시작이 restore를 청한 모든 프로세스에서 window를 NIC 복사 경로의 자기 PD에 한 번 더 등록했다(gin-restore 내보내기의 원본 읽기용). 9.5절과 9.7절 "NIC 복사 경로" 행은 mirror 켠 프로세스가 이 등록을 건너뛴다고 정했으나 계층이 따르지 않았다. 그 등록이 rain BAR1을 프로세스마다 window만큼(학습 모양 6 + 24 + 2 MiB) 더 써서 셋째 프로세스에서 모자랐다고 본다 `[추론]`: errno 14는 dmabuf 실패 뒤 peermem 등록의 것이라 BAR1을 직접 보이지 않음. 같은 등록이 window가 작은 4 KiB 둘째 죽음 셀과 예비 프로세스가 sunny인 `mi4_train_kill3`에서는 됐고, 9.8절 확인 4에서 둘째 PD 등록이 BAR1을 30 MiB 더 씀. 고침: mirror 켬(`gdakiMiOn`, side table 전에 정해짐)이면 window를 이 경로에 넣지 않음(rkey 표는 넣음). 이 경로로 window를 읽는 것은 v1 내보내기뿐이고(내보내기는 같은 `gdakiMiOn`으로 v2를 고르며 원본을 읽지 않음), 저장소 D2H와 모든 가져오기 쓰기는 CUDA 복사 `[소스]`. 새 줄(연구 빌드) "the windows stay out of the NIC copy path (the export reads no source) windows= bytes=". 설계 바뀜 없음(설계대로 구현). 영향 셀: mirror 켠 모든 셀(rain BAR1 사용이 프로세스마다 window만큼 줄어듦), 특히 `mi4_train_kill2_kill3`. mirror 끈 셀과 gin-restore 회귀는 그대로 | 커밋 `5ebd24fe`; 원자료 `raw/mi4_train_kill2_kill3_mi_n1_spare.log`(71, 121–122줄), `raw/mi4_train_kill2_kill3_mi_n1_r3.log`(1104줄) |
| 2026-10-15 | 고침: 재기만 하는 모드의 peer 팔(pilot 1 결함 D). `[측정]` 비용 pilot의 mirror-peer 팔은 모든 실행에서 보내는 rank의 "mirror summary"가 max_live_bytes=0, broken = put 수(지연 3 000, 묶음 192와 96)였고 받는 rank도 max_live_bytes=0: mirror가 한 바이트도 안 써졌고 peer 팔 값은 on 팔과 같음(rain lat2m on 223.2 µs, peer 224.3 µs). self 팔은 정상(max_live_bytes 140 509 184, broken 0). `[소스]` 호스트의 peer 팔은 d 칸을 d 자신의 pool(MIRROR_SETUP의 rkey)로 쓰고 d로 가는 mirror QP에 miUse 1을 썼으나, 장치는 모드와 상관없이 buddy(d)로 가는 mirror QP를 썼다. 두 rank에서 buddy(d)는 보내는 rank 자신(자기 루프, miUse 0)이라 모든 put이 cursor 더하기 전에 깨졌다. self 팔은 대상이 그 자기 루프라 맞았다. rkey 교환, QP 연결, WQE의 lkey와 rkey는 문제가 아니었다. 고침(공유 인터페이스 바뀜, [impl/rs_mirror_api.h](impl/rs_mirror_api.h)의 device layout과 helpers 블록, 트리와 바이트까지 같음): side table 머리 60번 낱말 `miRsv` → `miMode`(0 복원의 buddy 규칙, 1 self, 2 peer; 재기만 하는 모드에서만, 게시 전에 씀), helpers에 `ncclGinMiTargetOf`. 장치의 mirror WRITE, flush와 wait 끝의 mirror 기다림, 깨짐 세기가 그 대상을 씀. 칸의 예비 낱말 48–55에 장치가 마지막 깨짐의 까닭과 QP의 rank(`brkWhy`, `brkPeer`, 진단)를 적고, helper가 lane마다 처음 본 장치 깨짐에 WARN 한 줄(두 빌드): "first mirror break toward rank %d (measurement\|restore): why= mirror_qp_peer= qpn= qp_state= mi_use= rkey= cell_valid= lane_base= lane_bytes= cursor= broken= mode=". 두 번 쓰기의 꼴 `[소스]`: 같은 QP의 둘째 WQE가 아니라 mirror 문맥의 따로 된 QP(대상 rank로)의 WQE이고 사용자 put보다 먼저 냄, 두 QP 사이 차례 없음(9.2절). 복원 길(miMode 0)의 동작은 그대로이고, 장치 바뀜은 매크로로 빌드한 프로그램에만 있음(`rsMiPut`, `rsMiWait`, `rsMiAfterWait`). 영향 셀: 비용 가족 mirror의 mirror-peer 팔 전부(pilot 값은 무효), 매크로 빌드 드라이버 다시 빌드. 9.2절과 9.7절의 재기만 하는 모드 설계를 장치가 따르게 한 것 | 커밋 `567ed3c2`; 원자료 `costpilot_rain/cost_*_mirror-peer_rain_k1_r0.log`, `costpilot_sunny/` |
| 2026-10-15 | 고친 계층(i3) 빌드됨(rain, nice 19, sm_75, sm_86, GPU와 RDMA 실행 없음): [impl/mi_layer.diff](impl/mi_layer.diff) md5 `dfaddae8`, 8 279줄(커밋 `15cb1b0a`, `5ebd24fe`의 diff는 그때까지의 누적이고 빌드는 마지막 상태만); `mi_i3` libnccl `feefaf6d2623b9047903017850283695`, `mip_i3` `2e4008e6d433832dd68bccf5e42735f0`(공통 헤더가 바뀌어 장치 객체까지 다시 컴파일; 경고는 바뀌지 않은 `symmetric_sched.cc:327` 하나씩). `BR=fix build_mi.sh api` 통과. CPU 단위 시험(ASan, UBSan, `BR=fix build_mi.sh unit`): `mi_unit_dev` 568 999, `mi_unit_host` 1 563 414(16 함수), `mi_unit_store` 6 531 621, `mi_unit_spare` 187 checks, 모두 0 failed `[측정]`. 기계어 비교(`BR=fix MIOUT=mi_i3 build_mi.sh ident`): 매크로 없는 프로그램 넷 × sm_75, sm_86 = 8/8이 hk와도 i5와도 SASS 전체와 자원까지 같음; 라이브러리 장치 객체가 i5와 205 그대로 + 2(`device_glue.o`, `onerank.cu.o`)는 컴파일 해시만 다름, 다른 것 0(연구와 운영 둘 다); hk와는 183 + 2 같고 22 다름(hk 트리의 낡은 symmetric 객체, i2와 같은 모양); libnccl `-res-usage`(해시 가림)가 i5, hk와 같음; 매크로 변형 컴파일 경고 0. i2의 결과와 같은 모양 `[측정]`. 시험 드라이버 다시 빌드(`MITREE=agent_mi_fix MIOUT=mi_i3 build_mi_test.sh`, 설치 헤더 digest `f6b39af0`, 경고 0): `gin_mi` `7e522afd84f9546baa60091981616715`, `gin_mi_nomacro` `e84d9168eb736491c708b735a9e96578`, `gin_ts2_mi` `ad0908442a8b687c242ba806a6f54069`, `mr/ff/gin_mr` `0b26cf49f4be1c57b220d88786613b45`, `mr/hold/gin_mr` `0bfac5da7ce90cd652320ef3dea5876e`. `selftest_mi.py` 통과. 클러스터 실행 없음: 고침이 결함을 없애는지는 다시 하는 pilot(set `mi2`, `deploy_mi.sh`에 `MITREE=agent_mi_fix`)이 본다 | `agent_mi_fix/out/build_info.txt`, `unit_i3.log`, `ident_i3.log`, `test/build_test_i3.log`(세션 스크래치); 커밋 `3f3cf3b0`(MITREE) |
| 2026-10-15 14:28–14:42 | pilot 2(채점 제외; 메인 세션이 실행, 같은 `chain_mi.sh`): 배포 묶음 set `mi2`(고친 빌드 i3: `mi_i3` `feefaf6d`, `mip_i3` `2e4008e6`, `gin_mi` `7e522afd`, `gin_ts2_mi` `ad090844`; `deploy_mi.sh`에 `MITREE=agent_mi_fix`), hold P1, P2, P3, COSTPILOT-rain, COSTPILOT-sunny 모두 hold rc 0(14:28:10–14:42:39), STOP 없음. 셀과 n은 pilot 1과 같음(23 + 2 + 40). 생존 rank rc는 설계한 셋(nomirror, sampled, overflow wall 32.7 s)과 `reg_rm4_kill3_untimed_hold`만 4, 나머지 0 `[측정]`. 고침 확인 `[측정]`(원자료에서 `rows_mi.py`로 다시 셈, 아래 셈 고침 행의 열): A: kill 셀의 lane 깨짐이 설계한 짝 보호 공백만 남음(kill1_ow 17 → 2, kill3_ow 15 → 2, pull 127 → 2, seg_4k 20 → 2, train_kill3 252 → 2, rs4_kill3_mion 25 → 2, kill3_ckpt_ow 12 → 0, kill2_kill3_ow 3 → 2, seg_128k 2 → 1), 모든 kill 셀 `lane_broken_other` 0, 장애 없는 셀 0. C: `mi4_train_kill2_kill3` 두 죽음 모두 복원(294.9 ms, 266.5 ms), `ow_data_equal` 1, `second_ok` 1, `reimage_ok` 1, wall 34.6 s(pilot 1 123.1 s); mirror 켠 모든 프로세스 로그에 "the windows stay out of the NIC copy path"(로그 109개 가운데 77개, 나머지 32개는 mirror 끈 셀과 거절 셀), 둘째 예비 프로세스 "restore_buffers_in_nic_path=1". D: mirror 팔 20 실행 모두 summary broken=0, max_live_bytes > 0(peer 팔 lat4k 12 288 000, lat2m 140 509 184, bw2m 144 703 488–150 994 944), `mi_summary_ok` 1, 비용 40 실행 모두 `cost_valid` 1. 비용 p50(µs, k1, 실행 하나씩) peer 대 on: lat4k rain 21.50 대 13.31, sunny 22.69 대 13.79; lat256k 69.63 대 43.01, 69.92 대 41.66; lat2m 417.79 대 223.23, 414.21 대 222.75; 묶음 대역 peer/on bw256k 0.634, 0.632, bw2m 0.557, 0.552(초안 판정식 `cost_mirror_lat4k` +2.5 µs와 `cost_mirror_bw` 0.40–0.60의 bw256k는 이 값으로는 벗어남; 사전 등록 전에 다시 정함, 19절). 복원 시간(ms): kill1_ow 196.0, kill3_ow 199.0, kill3_ckpt_ow 176.3, kill2_kill3_ow 197.3과 206.4, pull 197.4, seg_4k 76.1(활성화 관문의 빠른 모드: 예비 프로세스의 첫 `/proc` 검사가 원래 프로세스를 zombie로 보아 'later' 0번에 활성화, 활성화 뒤 부분은 다른 셀과 같음; 2026-10-15 분석 `mi_restore_time_modes.md`(세션 스크래치), 3절 끝의 보고 규칙. 처음 적을 때는 `[미확인]` 까닭 보지 않음), seg_128k 198.8, rs4_kill3_mion 178.7, train_kill3 257.1, mirror 끈 회귀 rs4_kill3 380.7, rs4_kill3_ckpt 374.8. B는 그대로(overflow 32.7 s fallback, sampled fallback, nomirror 손상). "first mirror break" 줄은 31개: kill 셀의 19개는 why=mirror_wait qp_state=6(죽은 rank로 가는 mirror QP, 맡던 rank 쪽 lane), overflow의 12개는 why=lane_full qp_state=3(메인 세션 메모의 "5개"와 다름: 원자료를 따름). rain BAR1은 hold 앞뒤 Used 5 MiB만 있고 세 프로세스가 살아 있을 때의 값은 없음(아래 진단 행) | 원자료 `results/20261015_pilot2/`(이 worktree, release 전; `chain.out`, `hold_*.out`, `raw/`, `reg/`, `costpilot_*/`); 고침 묶음 리뷰 `mi_fix_review.md`(세션 스크래치, 막는 문제 없음) |
| 2026-10-15 | 채점 셈 고침(사전 등록 전 DRAFT라 판정식을 고칠 수 있음; pilot 1 고침 묶음 리뷰의 "사전 등록 전 필수" 1, 고침 보고의 사용자 결정 1의 제안대로, 사용자 결정은 대기): `pull_no_disarm_kill`과 `train_pull_count`의 kill 셀이 목적지와 때를 가리지 않고 모든 lane 깨짐과 DISARM을 세어(`rows_mi.py`의 `lane_broken`, `disarm_n`) 설계한 짝 보호 공백(9.6절)까지 셌다. 그래서 결함 A를 고친 뒤에도 kill 시행에서 늘 틀림 `[측정]`. [impl/test/rows_mi.py](impl/test/rows_mi.py)에 열 다섯 `lane_broken_designed`, `lane_broken_other`, `disarm_designed`, `disarm_other`, `broken_other`(옛 열은 그대로). 공백은 죽은 rank b마다 하나: 맡던 rank e는 hold 줄 "GIN/RS: rank R: hold of rank b started: ... HOLDING to buddy rank e, ..."가 이름 댐(hold 줄이 없으면 공백 없음); 시작은 b의 kill 기록("GINRS killed rank=b", "GINRS die rank=b")과 그 hold 줄 가운데 이른 것; 끝은 e 자신의 "GIN/RS: rank e: rank b restored as incarnation" 줄 뒤 첫 "GIN/RS: rank e: checkpoint K stable" 줄(둘째 죽음 셀에서 e가 첫 죽음의 rank면 되살린 예비 프로세스의 로그; 그런 줄이 없으면 시행 끝). 그 창 안의 생존 rank 줄 "lane to rank e broken"과 "rank e disarmed"만 설계로 셈. `broken_other` = `broken_total` − `lane_broken_designed`: 복원 모드에서 "mirror summary"의 broken=은 그 프로세스가 쓴 깨짐 줄 수다 `[소스: gdakiMiPoll, gdakiMiLaneBroken의 nBroken]`. 판정식: `pull_no_disarm_kill`은 `disarm_other == 0 and lane_broken_other == 0`, `train_pull_count`는 `lane_broken_other == 0 and broken_other == 0 and disarm_other == 0`([impl/test/predictions_mi.csv](impl/test/predictions_mi.csv) 16, 30줄), 3절 두 행의 글. `overflow_failfast`(hold 없음)와 `pull_no_disarm_none`(장애 없음)은 그대로. 검증 `[측정]`(원자료에서 `rows_mi.py`로 다시 셈, 셀마다 시행 n=1): pilot 2(`results/20261015_pilot2/`)의 kill 셀 모두 `lane_broken_other` 0, `disarm_other` 0, `broken_other` 0이고 설계 깨짐은 kill1_ow, kill3_ow, kill2_kill3_ow, pull, seg_4k, train_kill3, rs4_kill3_mion 2, seg_128k 1, train_kill2_kill3 4(두 죽음), kill3_ckpt_ow 0. pilot 1(`../gin-mirror-int`의 `results/20261015_pilot/`)의 결함 A는 `lane_broken_other`에 그대로 남음: kill1_ow 15, kill3_ow 13, kill3_ckpt_ow 12, pull 125, seg_4k 18, train_kill3 250, rs4_kill3_mion 23(위 결함 A 행의 다시 센 값과 같음; `disarm_other`는 그 두 배, `broken_other`는 같음); kill2_kill3_ow 0(설계 3), seg_128k 0(설계 2), train_kill2_kill3 0(설계 4: 첫 복원이 fallback이라 창이 시행 끝까지). `mi4_overflow`는 hold가 없어 모두 other(pilot 1 77, pilot 2 74). 합성 시험: score.py의 kill 시행에 공백 줄, C에 공백 밖 깨짐 둘(되살린 rank 쪽, 맡던 rank의 다음 확정 뒤)이 틀림, D에 열 검사 넷(둘째 죽음의 두 창 포함); `selftest_mi.py` 통과, 옛 판정식으로는 A가 틀림 | 이 행과 같은 커밋; [impl/test/rows_mi.py](impl/test/rows_mi.py) 머리 주석 |
| 2026-10-15 | 단위 시험: 결함 A의 호출자 경우(고침 묶음 리뷰의 고칠 것 3: A의 시험은 순수 판정 `gdakiStoreDropReq`만 봐서 고치기 전 코드도 통과했을 것; 결함은 호출자가 넘긴 값에 있었다). [impl/mi_unit_store.cc](impl/mi_unit_store.cc)의 모델(6번)에 짝의 hold 칸(`gdakiHoldPack`)과 `gdakiStoreDropNow`의 버림을 넣음: 맡은 rank의 죽음은 죽은 화신 i의 HELD, 복원은 INJECTED까지 PUBLISHED(i)이고 받아들인 REJOIN이 이미 i + 1을 아는 화신으로 둠(mirror 켬). 죽은 프로세스의 요청은 어느 seq든(PUBLISHED 동안 늦게 읽힌 것도) 버리고 되살린 프로세스의 요청은 그때 받음을 모든 걸음에서 검사. 정해진 차례(새 `testDropWindow`, i = 0..3): STORE_REQ(i + 1, seq 1)를 PUBLISHED(i)에서 받고 INJECTED 전에 저장소가 준비됨, STORE_REQ(i, seq 2)(죽을 때 소켓에 있던 것)와 STORE_REQ(i, seq 1, 5)(늦게 읽힌 것)는 버림. 고치기 전 호출자(아는 화신을 hold의 화신으로 넘김)는 같은 차례에서 되살린 프로세스의 첫 요청을 답 없이 버려야 함(4/4; 아니면 이 차례가 결함을 못 보는 것이라 시험 실패). CPU에서 시험함(ASan, UBSan, i3 트리의 순수 영역): `mi_unit_store` 6 513 372 checks 0 failed(모델이 바뀌어 수가 i3의 6 531 621과 다름; 무작위 모델 200 실행에서 hold 동안 버린 요청 1 435, hold 동안 받은 요청 468, INJECTED 1 974) `[측정]`. 라이브러리는 바뀌지 않음 | 이 행과 같은 커밋 |
| 2026-10-15 | 진단 고침(고침 묶음 리뷰의 고칠 것 4, 5, 6; 라이브러리 바뀜, 빌드는 아래 i4 행). (1) 장치 `rsMiNoteBreak`(`gin_gdaki.h`, 매크로 빌드의 mirror 길에만): 깨짐의 까닭 `brkWhy`와 QP의 rank `brkPeer`를 먼저 쓰고 `__threadfence_system()` 뒤 `broken`을 더함. 전에는 `broken`을 먼저 더해 호스트가 늘어난 broken과 옛 까닭(첫 깨짐이면 0 = none, rank 0)을 함께 읽을 수 있었음 `[소스]`. (2) 첫 깨짐 줄("first mirror break toward rank d"): 목적지마다 프로세스에 한 번이던 것(위 결함 D 행의 "lane마다"는 틀린 말; 리뷰가 찾음)을 segment 바꾸기가 그 칸을 유효로 쓸 때마다 다시 켬(`gdakiMiSegSwitch`가 `brkLined`를 지움): 복원 모드에서는 목적지와 유효한 segment마다 한 번, 재기만 하는 모드는 바꾸기가 없어 목적지마다 프로세스에 한 번(주석에 적음). hold 동안의 설계된 깨짐이 줄을 써 버려 그 뒤 예상 밖 깨짐에 까닭이 없던 것을 막음. 줄에 `seg=` 더함(rows_mi.py는 이 줄을 읽지 않음). `mi4_overflow`처럼 segment마다 깨지는 셀은 깨짐 줄만큼 이 줄도 남 `[추론]`. (3) 결함 C의 원인 확인(BAR1): [impl/test/run_mi.sh](impl/test/run_mi.sh)가 `BAR1_AT_GATE=1`이면 시행의 모든 프로세스가 뜬 뒤(원하는 예비 프로세스 준비, 또는 그 기다림이 끝남) 시작 문을 열기 전에 rain의 BAR1 Total, Used, Free와 rain GPU의 프로세스 수를 읽어(`nvidia-smi` 질의, 읽기만) hold 출력 줄과 meta(`bar1_gate_total_mib`, `bar1_gate_used_mib`, `bar1_gate_free_mib`, `gpu_procs_gate_rain`)에 적음. [impl/test/hold_mi.sh](impl/test/hold_mi.sh)가 학습 hold(P2, T1, T2)에서 켬: `mi4_train_kill2_kill3`에서 rain 세 프로세스가 살아 있을 때의 값이 처음 남음(pilot 2의 `hold_P2.out`에는 hold 앞뒤 Used 5 MiB만). 클러스터에서 돌리지 않음(문법 검사와 표본 출력의 해석만) | 이 행과 같은 커밋; [impl/mi_layer.diff](impl/mi_layer.diff) md5 `ec2a74f3`(8 288줄, 빌드하지 않은 중간 상태) |
| 2026-10-15 | 작은 고침(고침 묶음 리뷰의 nit; 라이브러리 바뀜, 빌드는 아래 i4 행). (1) 짝이 hold가 끝난 뒤 읽은 죽은 프로세스의 STORE_REQ(아는 화신보다 옛 화신)를 답 없이 버림(`gdakiStoreDropOldInc`, `gdakiStoreDropNow`): 전에는 OLD_INC 거절 답을 보냈고 STORE_ACK에는 화신이 없어(seq만) 되살린 프로세스가 같은 seq의 자기 요청 답으로 읽을 수 있었음(back-off 한 번; 고치기 전부터, 거의 닿지 않음) `[소스]`. 버림 줄의 까닭에 "restored since". 단위 시험에 그 판정, 모델의 버림, `testDropWindow`에 INJECTED 뒤 늦은 요청. (2) side table magic "RSS4" → "RSS5"(`0x35535352`; 공유 인터페이스 [impl/rs_mirror_api.h](impl/rs_mirror_api.h)의 device layout 블록과 트리의 공통 헤더, 바이트까지 같음; `mi_unit_dev`의 상수, [impl/rs_log_api.h](impl/rs_log_api.h) 머리 주석). 결함 D의 고침이 머리 낱말 60과 칸 48–55를 바꿨으므로 판을 올림. 다만 magic은 라이브러리만 쓰고 읽으며 장치는 읽지 않아(`[소스]`: 비교는 호스트 `gdakiMiSide`가 자기가 쓴 표를 다시 읽을 때 하나), 옛 헤더로 빌드한 드라이버를 막는 것은 이 낱말이 아니라 배포의 md5 검사(`deploy_mi.sh`의 `WANT_*`)임을 주석과 [impl/test/deploy_mi.sh](impl/test/deploy_mi.sh) 머리에 적음(리뷰의 "섞임이 시끄럽게 드러남"은 장치가 읽지 않아 맞지 않음). (3) 주석: side table 머리 `head`의 주석 칸(공통 헤더와 rs_mirror_api.h), PUBLISHED 중 serve가 옛 MR을 바로 풀어도 되는 까닭(예비 프로세스의 FETCH는 Resume 안, 되살린 프로세스의 첫 요청은 그 뒤), "windows stay out" 줄의 bytes=는 window 범위 합이고 앞선 등록 실패 뒤에도 찍힘, `deploy_mi.sh` 머리의 낡은 "agent_mi_int에서" 문장을 `MITREE`로. CPU 단위 시험 넷(ASan, UBSan, 이 상태): dev 568 999, host 1 563 414, store 6 521 768, spare 187 checks, 모두 0 failed `[측정]` | 이 행과 같은 커밋; [impl/mi_layer.diff](impl/mi_layer.diff) md5 `4dd2927a`(8 303줄) |
| 2026-10-15 | 채점 셈 고침 둘째(이 작업에서 찾음, 리뷰 목록 밖; 사전 등록 전 DRAFT): `store_rdma`가 읽는 `tcp_image_bytes`, `tcp_segment_bytes`가 pilot 1, 2의 모든 시행에서 비어 있었다 `[측정]`: "store summary" 줄이 pilot 2 로그 109개 어디에도 없음(pilot 1도 0줄). 그 줄은 `gdakiStoreFree`가 문맥을 풀 때(`gdakiRecFree` → `gdakiHoldFree` → `gdakiCkptFree`) 찍는데 로그는 그 앞의 "checkpoints at close" 줄(`gdakiCkptTeardownLine`)에서 끝남 `[소스, 측정]`(그 뒤가 왜 로그에 없는지는 `[미확인]`). 이대로면 `store_rdma`가 본 실행에서 늘 자료 부족(라이브러리 열이 모든 시행에서 빔). 고침([impl/test/rows_mi.py](impl/test/rows_mi.py)): summary 줄이 없으면 모든 프로세스의 "GIN/RS: rank R checkpoints at close: ... upload_bytes=N"(summary와 같은 셈 `ck->nUploadBytes`)를 더해 `tcp_image_bytes`로, `tcp_segment_bytes`는 0(summary도 상수 0을 찍음: segment를 소켓으로 보내는 저장소 길이 없음 `[소스]`), 둘 다 없으면 빈 값. 판정식과 라이브러리는 그대로(줄을 앞으로 옮기는 라이브러리 고침은 하지 않음). 검증 `[측정]`(원자료에서 `rows_mi.py`로): pilot 2의 mirror 켠 셀 모두 0/0, mirror 끈 셀은 TCP 올리기 바이트(rs4_kill3 210 230 792, rs4_none 197 384 968, nomirror 130 351 840, sampled 53 645 368), pilot 1도 같은 꼴. 합성 시험 D에 셋(올림 없음 0/0, 올림 10 000/0, 줄 없음 빈 값), `selftest_mi.py` 통과 | 이 행과 같은 커밋 |
| 2026-10-15 | 고친 계층(i4) 빌드됨(rain, nice 19, sm_75, sm_86, GPU와 RDMA 실행 없음; 위 진단 고침과 작은 고침의 마지막 상태): [impl/mi_layer.diff](impl/mi_layer.diff) md5 `4dd2927ab86be878eb3f6b534340b359`, 8 303줄; `mi_i4` libnccl `c89ce744312b1af057c85f6eac975baf`, `mip_i4` `12a0edeca10b491458a86471e9903e53`(공통 헤더가 바뀌어 장치 객체까지 다시 컴파일, 각 8 분; 경고는 바뀌지 않은 `symmetric_sched.cc:327` 하나씩). `BR=fix build_mi.sh api` 통과. CPU 단위 시험(ASan, UBSan): `mi_unit_dev` 568 999, `mi_unit_host` 1 563 414(16 함수), `mi_unit_store` 6 521 768(호출자 경우 4/4), `mi_unit_spare` 187 checks, 모두 0 failed `[측정]`. 기계어 비교(`BR=fix MIOUT=mi_i4 build_mi.sh ident`, 19 분 50 초): 매크로 없는 프로그램 넷 × sm_75, sm_86 = 8/8이 hk와도 i5와도 SASS 전체와 자원까지 같음; 라이브러리 장치 객체가 i5와 205 그대로 + 2(컴파일 해시만), 다른 것 0(연구, 운영); hk와 183 + 2, 22 다름(hk의 낡은 symmetric 객체); libnccl `-res-usage`(해시 가림) i5, hk와 같음; 매크로 변형 컴파일 경고 0. 요약 줄이 i3과 모두 같음. 매크로 변형의 자원은 i3과 ff, gin_ts2, gin_mr이 같고 ring 예제의 커널 하나만 레지스터 162 → 164(`rsMiNoteBreak`의 울타리; 매크로 빌드만) `[측정]`. 시험 드라이버(`MITREE=agent_mi_fix MIOUT=mi_i4 COSTOUT=cost_i4 MROUT=mr_i4 build_mi_test.sh mi nomacro cost mr`, 설치 헤더 digest `65fdf19b`, 경고 0; i3 드라이버는 그대로 둠): `gin_mi` `5887dfeacdde2ed96de0de9105e6eb88`, `gin_mi_nomacro` `5cd7246b79c7da5913e001dd1e88e4af`, `gin_ts2_mi` `05093a694d01979b638121555dbdf637`, `mr_i4/ff/gin_mr` `2b18db83fb5c7e46333868a85523ddde`, `mr_i4/hold/gin_mr` `6debbb6db79ead05d040afc22726493a`. `selftest_mi.py` 통과. 다음 배포 묶음 set `mi3`의 명령은 [impl/test/PILOT_MI.md](impl/test/PILOT_MI.md). 클러스터 실행 없음 | `agent_mi_fix/out/build_info_i4.txt`, `build_mi_i4.log`, `build_mip_i4.log`, `unit_i4.log`, `ident_i4.log`, `selftest_i4.log`, `test/build_test_i4.log`(세션 스크래치); 이 행과 같은 커밋 |
| 2026-10-15 | `mi4_overflow`(고침 보고의 사용자 결정 2를 제안대로 구현, 따로 된 커밋; 사용자 결정 대기, 거절이면 이 커밋을 뺌). (1) 예비 프로세스의 활성화 기다림 `SPARE_WAIT_MS` 30 000 → 15 000 ms([impl/test/cells_mi.json](impl/test/cells_mi.json)의 P1과 G3 두 곳; `cells_mi.sh`에는 그 값이 없음): 활성화되지 않는 셀이라 시행 wall이 약 33 s에서 약 18 s로 줄어 G3에서 약 75 s를 아낌 `[추론: pilot 2의 32.7 s, 생존 rank는 시작 뒤 약 6 s에 끝남]`. (2) 예측 `overflow_failfast`를 넓힘(사전 등록 전 DRAFT라 고칠 수 있음): hold 시작 줄 없이 degraded 해제, 또는 hold가 시작되면 fallback으로 끝나 fallback + 2 000–2 500 ms에 해제(rank 3이 kill 순간 잠깐 무장돼 있으면 hold가 시작되고 내보내기가 깨진 lane으로 거절해 fallback; pilot 1에서 rank 3이 체크포인트 60에 한 번 무장됨 `[측정]`). 새 열 `fallback_release`([impl/test/rows_mi.py](impl/test/rows_mi.py): 첫 "is given up" 줄 뒤 2 000–2 500 ms에 모든 생존 rank가 풀림, 까닭을 가리지 않음; `nomirror_detect`는 이 열과 "source buffer changed"). 판정식 `count(lane_broken >= 1 and ((hold_started == 0 and degraded_release == 1) or (hold_started >= 1 and fallback_release == 1))) >= 4`. 원자료에서 다시 셈 `[측정]`: pilot 1, 2의 overflow 시행은 둘 다 hold 없이 degraded 해제(옛 식과 새 식 모두 참). 합성 시험: A의 시행 하나가 hold 길, D에 두 길의 열과 식 검사; `selftest_mi.py` 통과 | 이 행과 같은 커밋 |
| 2026-10-15 | 사용자 결정(메인 세션이 전함): 사전 등록 전에 복원 계층의 화신 판정을 계보(lineage) 하나로 모은다. 설계 v1(세션 스크래치 `lineage/DESIGN.md`): 화신을 적는 곳과 견주는 자리 약 50곳의 목록(빌드 i4의 호스트 파일 사본 `lineage/snap_host.cc`, md5 `cc4eea3d`, 24 020줄의 줄), 국면과 보기, classify, 호출자 규칙 표, 보내는 쪽, 숨은 문제 둘(예비 프로세스의 생존 rank 칸이 OFF(0)으로 남음; serve 중 죽음의 낡은 답), 열린 충돌 셋, 다시 무장 설계. 구현, 빌드, 클러스터 실행 없음 | 설계 원문(세션 스크래치) |
| 2026-10-15 | 독립 검토(다른 Opus 에이전트, 읽기만, `lineage/REVIEW.md` 1–3절): 막는 문제 둘(국면만 쓴 규칙 표가 지금 코드의 상태 조건을 잃음: TIMED_OUT_HELD의 ACTIVATE와 REJOIN, 거절된 rank의 REJOIN에 FAIL 대신 닫기; "옛 판정과 같음" 시험이 순수 함수끼리만 견주어 결함 A 꼴의 호출자 차이를 못 잡음), 고칠 것 11(숨은 문제 둘의 원인과 닿음, 받는 쪽 도장 대신 받아들임 순간의 park 검사, BAD의 기본 행동은 known을 cur로, `lineage_warn`은 예상 밖의 FUTURE와 BAD만, pilot 셀에 `rs4_kill3_mion` 등), nit 9. 열린 충돌 1에 (나)를 권함. 설계 v2가 모두 반영 | `lineage/REVIEW.md`(세션 스크래치) |
| 2026-10-15 | 재검토(같은 검토자, 읽기만, `lineage/REVIEW.md` 4절): 막는 문제 없음, 구현 go. 조건: oracle 정의역의 도달 가능 조건과 REJOIN의 구동 단계 조건(V1), FALLBACK 행의 화신 출처(V2), 공유와 순수 영역의 옛 함수를 고치지 않는 규칙(V3), 그리고 질문 1의 사용자 재확인 | `lineage/REVIEW.md` 4절 |
| 2026-10-15 | 사용자 결정(최종, 메인 세션이 전함): 열린 충돌 1 → (나) 짝이 serve 끝의 답을 보내기 직전에 다시 가름, wire 그대로, STORE_ACK의 `wardInc`는 다시 무장 작업으로 미룸; 2와 3 → (가) mirror 끈 TCP 길 그대로(18절), 다시 무장은 설계로만(19절). 설계 v3: V1–V3, nit 둘, 사용자 결정, 구현 자리(메인 세션 지시: 갈래 `exp/gin-mirror-fix`, 빌드 트리 `agent_mi_fix/`, 새 이름 `ln1`; i4 출력은 그대로), 구현 전에 정한 것 둘(재연결 펜싱은 모든 국면에서 view.cur와 견줌, HOLDING 세기의 oracle은 뒤의 활성화를 견줌). 이 문서에 9.9절, 9.7절의 계보 행 17개와 결정 (10)–(12), 9.8절의 작업 묶음 행, 11절, 18절, 19절. 구현 시작(중간 커밋은 빌드하거나 배포하지 않음) | `lineage/DESIGN.md` v3(그때 490줄, 구현 메모를 더해 494줄); 이 행과 같은 커밋 |
| 2026-10-15 | 계보 구현(빌드 `ln1`; 빌드됨, 시험함: CPU만, 클러스터 실행 없음). 호스트만 바뀜: [impl/mi_layer.diff](impl/mi_layer.diff) md5 `2b5bda0638f42ef469ed5662d2394c48`, 8 977줄(i4 `4dd2927a` 위; 장치 파일 둘의 diff는 i4와 바이트까지 같음), 새 공유 헤더 [impl/rs_lineage_api.h](impl/rs_lineage_api.h)(호스트 파일에만 붙음, `BR=ln build_mi.sh api`가 바이트까지 견줌; `impl/rs_hold_api.h`와 `impl/rs_store_api.h`는 그대로, git diff 0). 바뀐 자리: 보기(`gdakiLnOf`)와 classify를 화신 비교 자리마다(9.9절 규칙 표; 공유와 순수 영역의 옛 함수 여섯은 바이트 그대로 두고 입력을 보기에서 고름), REJOIN_ACK의 칸 쓰기(CAS OFF(0) → OFF(s))는 classify와 같은 커밋, 받아들임 순간의 park 검사, serve 끝의 답을 보내기 직전에 다시 가름, 활성화 답의 되울림과 예비 등록 화신 검사(`gdakiHoldSpareOf`가 등록 화신을 돌려줌), BAD는 known을 cur로 + `GIN/LN` 줄. `GIN/LN` 줄 9곳에 `why=`와 채점기가 읽는 글자 없음(grep). 설계와 다른 것: 위 셋의 `GIN/LN` 줄을 더함(9.9절 "줄"), oracle 정의역에 "FALLBACK이면 거절됨"을 더함(구현 중 찾음: 없으면 FALLBACK이고 거절 안 된 점에서 STORE_REQ가 목록 밖으로 다르나 그 점은 닿지 않음), `build_mi.sh`의 `BR=ln`은 새 트리 없이 `agent_mi_fix/`를 씀(메인 세션 지시). 빌드: `mi_ln1` libnccl `e9c2c0e9b19b06cf8f406a3bde99bdef`, `mip_ln1` `d8e7152c50730d1ab08dacaad8548f34`(호스트 파일 하나만 컴파일, 경고 0; 장치 객체 다시 컴파일 없음). CPU 단위 시험(ASan, UBSan, `BR=ln build_mi.sh unit`): `mi_unit_dev` 568 999, `mi_unit_host` 1 563 414(16 함수), `mi_unit_store` 6 543 999(모형이 계보 보기와 REJOIN_ACK 칸 쓰기로; 모형의 셈은 i4와 같음), `mi_unit_spare` 187, 새 `mi_unit_lineage` 3 365 checks, 모두 0 failed `[측정]`. oracle: 도달 가능한 점 623 230개에서 다른 (행, 국면, 갈래) 칸 25개가 모두 다름 목록의 넷(활성화 답, 예비 등록, STORE_REQ, serve 끝의 답) 안이고 각 행의 새 검사가 걸린 점과 정확히 같음(목록 밖 0); STORE_REQ의 다른 칸은 {LIVE, HOLD_WAIT, HOLD_SUCC} × FUTURE와 ENDED(CANCELLED이고 거절 안 됨)뿐; 출처를 잘못 고른 호출자 둘(칸 화신을 cur로, known을 dead로)은 oracle이 목록 밖 차이 1 957개, 4 185개로 잡고 결함 A 장면도 잡음; 장면 20개 통과 `[측정]`. `selftest_mi.py` 통과(새 열 `lineage_warn`과 그 고정 자료). 기계어 비교(`BR=ln MIOUT=mi_ln1 build_mi.sh ident`, 19 분 52 초, rc 0): 매크로 없는 프로그램 넷 × sm_75, sm_86 = 8/8이 hk와도 i5와도 SASS 전체와 자원까지 같음; 라이브러리 장치 객체가 i5와 205 + 2(컴파일 해시만), 다른 것 0(연구, 운영); hk와 183 + 2, 22 다름(hk의 낡은 symmetric 객체); libnccl `-res-usage`(해시 가림) i5, hk와 같음; 매크로 변형 컴파일 경고 0, 자원이 다른 수는 i4와 같음(ff 11, gin_ts2 4, gin_mr 1, ring 8) `[측정]`. 시험 드라이버(`MITREE=agent_mi_fix MIOUT=mi_ln1 COSTOUT=cost_ln1 MROUT=mr_ln1 build_mi_test.sh mi nomacro cost mr`, 설치 헤더 digest `65fdf19b`(i4와 같음), 경고 0): `gin_mi` `76a326000ba35d53edb8c7fb0a65770c`, `gin_mi_nomacro` `6c7be9116fdac0ba98083c2b9e9a2ed1`, `gin_ts2_mi` `f539411f3007481d544dbd80e900f19f`, `mr_ln1/ff/gin_mr` `90d4ec640326c25d8252254c1c1d2181`, `mr_ln1/hold/gin_mr` `adccde3b4b7f6a3a873352702c3eb56f`. 배포 묶음은 이 빌드가 아니라 결함 E 고침을 더한 빌드로 만든다(12절의 그 뒤 행). 클러스터 실행 없음 | `agent_mi_fix/out/build_info_ln1.txt`, `build_mi_ln1_compile.log`, `build_mi_ln1.log`, `build_mip_ln1.log`, `unit_ln1.log`, `ident_ln1.log`, `selftest_ln1.log`, `test/build_test_ln1.log`(세션 스크래치); 커밋 `49cdf110`, `65398f10`, `cd7d8d54`, `4062c0a9`와 이 행의 커밋 |
| 2026-10-15 16:00–16:14 | pilot 3(채점 제외; 메인 세션이 실행, `cluster_run.sh` 안의 `chain_mi.sh`): 배포 묶음 set `mi3`(빌드 i4: `mi_i4` `c89ce744`, `mip_i4` `12a0edec`, `gin_mi` `5887dfea`, `gin_ts2_mi` `05093a69`), hold P1, P2, P3, COSTPILOT-rain, COSTPILOT-sunny 모두 hold rc 0(16:00:01–16:14:18), STOP 없음. 셀과 n은 pilot 2와 같음(65 시행: 4 KiB, 학습, 거절, 회귀 23 + gin-remaining 실행기 2 + 비용 40) `[측정: chain.out]`. 원자료에서 `rows_mi.py`로 다시 셈 `[측정]`: 설계한 짝 보호 공백 밖의 lane 깨짐(`lane_broken_other`)은 kill 셀 모두 0, 다만 `mi4_pull` 6(결함 E, 다음 행)과 `mi4_overflow` 78(hold 없음, 설계상 모두 공백 밖). 복원 시간(ms, 시행 하나씩): kill1_ow 78.3, kill3_ow 178.4, kill3_ckpt_ow 196.9, kill2_kill3_ow 200.5와 186.1(죽음마다), pull 176.0, seg_4k 178.3, seg_128k 196.9, train_kill3 256.6, train_kill2_kill3 97.1과 263.6, mirror 끈 회귀 rs4_kill3 371.4, rs4_kill3_ckpt 371.8, rs4_kill3_mion 198.0. 100 ms 아래 둘(78.3, 97.1)은 예비 프로세스의 활성화 관문이 첫 검사에서 열린 빠른 모드다(3절 끝, 18절; 처음 적을 때는 까닭 `[미확인]`). overflow wall 17.8 s(예비 프로세스 기다림 15 000 ms; pilot 2 32.7 s). rain BAR1 시작 문(새 측정, 학습 셀 `_meta.txt`의 `bar1_gate_*`): 프로세스 0개(train_none) Used 5 MiB, 2개(train_kill3의 rank 0과 2) Used 123 MiB, Free 133 MiB, 3개(train_kill2_kill3, 예비 프로세스 포함) Used 182 MiB, Free 74 MiB `[측정]`; 프로세스 하나에 약 59 MiB라 rain에서 넷째 프로세스(다시 무장의 둘째 예비 프로세스)는 들지 않는다 `[추론]`. 비용 peer 대 on p50(µs, k1): lat4k rain 21.50 대 13.31, sunny 22.56 대 13.76; lat2m 417.79 대 223.23, 414.91 대 222.88; 묶음 대역 peer/on bw256k 0.635, 0.631, bw2m 0.558, 0.553(pilot 2와 같은 크기) `[측정]` | 원자료 `results/20261015_pilot3/`(이 worktree, release 전: `chain.out`, `hold_*.out`, `raw/`, `reg/`, `costpilot_*/`); 메인 세션 메모 `pilot_mi3_notes.md`(세션 스크래치) |
| 2026-10-15 | pilot 3의 결함 E 고침(메인 세션의 읽기 전용 분석 `mi_defect_e.md`, 세션 스크래치; pilot 3은 set `mi3`, 빌드 i4). `[측정]` `mi4_pull`(rank 3 kill)에서 rank 0과 1이 kill 2.2–9.5 ms 전에 받은 CKPT_PULL을 Step(130)이 "checkpoint 130 not taken: a restore runs"로 써 버렸고 (당기기 표시는 물을 때 지워짐, 거절된 체크포인트는 5단계 back-off만 남김), 보내는 쪽은 segment마다 한 번만 당기므로 다음 체크포인트는 간격(143)이었으며, L 48 KiB < 간격 80 KiB인 이 셀에서 복원 뒤 단계 136부터 lane 넷(0 → 1, 1 → 0, 2 → 0, 2 → 1)이 넘쳤다. 둘은 바꾸기 뒤 첫 폴링이 같은 넘침을 다시 센 줄. i4와 무관하고 kill 시행마다 약 0.3으로 난다 `[추론]`. 판정은 설계 공백(9.3절이 정하지 않음). 고침(호스트만, 장치 바뀜 없음; 9.3절 "당겨진 체크포인트가 찍히지 않을 때"): (1) `ncclGinRestoreStep`에서 당겨진 체크포인트가 그 Step에 DRAINED가 아니면(`haveLast && lastCkpt == step`이 거짓) 당기기를 다시 걸고 `retryAtStep = step + 1`; 간격의 4분의 1만큼의 Step까지만(오래가는 거절에 Step마다 다시 묻지 않게; 분석 제안에 더한 것), 다시 쓴 당기기는 `pulls_taken`에 다시 세지 않음, 줄 둘("the pull is kept for the next Step", "the pull is spent"); (2) `gdakiMiPollStep`이 열린 segment의 `brokenOpen`을 받아, 앞 burst가 DISARM한 뒤 바뀐 segment에서는 그 값까지의 깨짐을 앞 burst의 꼬리로 흡수(폴링이 못 본 깨짐은 지금처럼 DISARM); (1b) 되돌리기가 당긴 segment를 되살리면 `pulledSeg`를 지우고 그 segment에서 한 번 더 둘째 문턱((문턱 + 100)/2 = 75%)에서 당김. CPU 단위 장면(`mi_unit_host.cc` 10번): mi4_pull 모형(L 12 put, 간격 20, 당기기 50%)에서 Step(130), Step(131)이 거절되면 고침은 Step(132)에 찍고 lane 최고 8 put, 옛 규칙은 143에 찍고 단계 136에 넘침(pilot의 자취와 같음: 변이를 잡음); 거절이 이어지면 시도는 130–135와 간격의 143, 148뿐; 폴링의 흡수와 놓치지 않음; 둘째 당기기 한 번. pilot 4 예상은 9.9절 | 분석 `mi_defect_e.md`(세션 스크래치); 원자료 `results/20261015_pilot3/raw/mi4_pull_mi_n1_*`(release 전); 커밋 `cf1a94be` |
| 2026-10-15 | 빌드 `ln2`(계보 + 결함 E 고침; 빌드됨, 시험함: CPU만, 클러스터 실행 없음): [impl/mi_layer.diff](impl/mi_layer.diff) md5 `23e5407b427fde5fb5b0d2f1d3c74e2d`, 9 071줄(장치 파일 둘의 diff는 i4와 바이트까지 같음; `impl/rs_hold_api.h`, `impl/rs_store_api.h`, `impl/rs_mirror_api.h`는 `c7a1c426`과 같음). `mi_ln2` libnccl `dac86bed7dc86afc5386d06f56f3d9e1`, `mip_ln2` `2bb1a973de4c0210093f85c7fb3106b3`(호스트 파일 하나만 컴파일, 경고 0). `BR=ln build_mi.sh api` 통과. CPU 단위 시험(ASan, UBSan): `mi_unit_dev` 568 999, `mi_unit_host` 1 563 442(17 함수), `mi_unit_store` 6 543 999, `mi_unit_spare` 187, `mi_unit_lineage` 3 365 checks, 모두 0 failed `[측정]`. `selftest_mi.py` 통과(P4, P5의 셀 설정 포함). 기계어 비교(`BR=ln MIOUT=mi_ln2 build_mi.sh ident`, 19 분 50 초, rc 0): `ln1`과 같은 결과(매크로 없는 프로그램 8/8이 hk, i5와 SASS 전체와 자원까지 같음; 장치 객체 i5와 205 + 2, 다른 것 0; hk와 183 + 2, 22 다름; libnccl `-res-usage` 같음; 매크로 변형 경고 0) `[측정]`. 시험 드라이버(`MIOUT=mi_ln2 COSTOUT=cost_ln2 MROUT=mr_ln2`, 헤더 digest `65fdf19b`, 경고 0): `gin_mi` `0603ac4dc0c8d67a6470726dd2e85489`, `gin_mi_nomacro` `dfa85845ce22fb14dec63fe33b22f4d7`, `gin_ts2_mi` `faaac703c02f88acbb9152f2783e2524`, `mr_ln2/ff/gin_mr` `e4b4fc3f24486c9c372f3044acc982d2`, `mr_ln2/hold/gin_mr` `70ab3f3a771c6895862834b84a18c4eb`. 배포 묶음 set `mi4`와 pilot 4(pilot hold P4, P5)의 명령은 [impl/test/PILOT_MI.md](impl/test/PILOT_MI.md). 클러스터 실행 없음 | `agent_mi_fix/out/build_info_ln2.txt`, `build_mi_ln2.log`, `build_mip_ln2.log`, `api_ln2.log`, `unit_ln2.log`, `ident_ln2.log`, `selftest_ln2.log`, `test/build_test_ln2.log`(세션 스크래치); 커밋 `cf1a94be`, `856f320b`와 이 행의 커밋 |
| 2026-10-15 17:52–18:05 | pilot 4(채점 제외; 메인 세션이 실행, 같은 `chain_mi.sh`): 배포 묶음 set `mi4`(빌드 ln2: `mi_ln2` `dac86bed`, `mip_ln2` `2bb1a973`, `gin_mi` `0603ac4d`, `gin_ts2_mi` `faaac703`), hold P4(17:52:37–17:57:33), P5(–18:00:03), COSTPILOT-rain, COSTPILOT-sunny(–18:05:37) 모두 hold rc 0, STOP 없음; 63 시행(P4 15, P5 8, 비용 40) `[측정: chain.out]`. 원자료에서 다시 셈(`rows_mi.py`, 이 행 뒤 커밋의 열 포함) `[측정]`: `raw/`와 `reg/`의 로그 114개 어디에도 `GIN/LN: ` 줄이 없고 모든 시행 `lineage_warn` 0(gin-remaining 실행기의 행 포함); "dropped after its serve" 0줄. kill 셀 모두 `lane_broken_other` 0, `disarm_other` 0(`mi4_overflow` 63은 hold 없이 설계상 공백 밖); 복원한 셀 모두 `ow_data_equal` 1, `wait_held` 1(sampled, nospare, spareabsent는 설계한 fallback). 회귀: `rs4_none`, `rs4_kill3`(2), `rs4_kill3_ckpt`, `rs4_kill3_mion`은 pilot 2와 같은 열 값(`wait_held`, `data_equal`, `no_reexec`, `revived_done`, `suppress_ok` 1), `rs4_kill3_spareabsent`의 `spare_absent_ok` 1, `rs4_kill3_nospare`의 `nospare_failfast_ok` 1(이 둘은 pilot 2에 없음). 결함 E: `mi4_pull` n 5 모두 `lane_broken_other` 0과 `disarm_other` 0이고, "the pull is kept" 줄이 그 가운데 넷(n1, n2, n4, n5; 모두 rank 2)과 `mi4_train_kill2_kill3`의 되살린 rank 2에서 하나, "the pull is spent" 0줄. 남긴 당기기가 찍힌 차례와 그 까닭(죽은 rank 3의 짝인 rank 2가 INJECTED 뒤 저장소 준비 전으로 거절됨)은 9.3절이다. 상한과의 여유가 한 번인 시행이 둘이라 상한을 넓혔다(빌드 ln3, 다음 행). 복원 시간(ms): kill3_ow 198.0, 195.2; kill3_ckpt_ow 196.8, 72.2; kill2_kill3_ow 200.2와 186.0, 74.8과 189.1(죽음마다); train_kill2_kill3 99.8과 288.5; pull 196.6, 176.7, 195.6, 175.5, 175.4; rs4_kill3 365.5, 380.4; rs4_kill3_ckpt 373.3; rs4_kill3_mion 199.1. 100 ms 아래 셋은 활성화 관문의 빠른 모드(3절 끝). 비용 peer 대 on p50(µs, k1): lat4k rain 21.50 대 13.31, sunny 22.56 대 13.76; lat2m 416.77 대 223.23, 414.02 대 223.20; 묶음 대역 peer/on bw256k 0.632, 0.630, bw2m 0.557, 0.552(pilot 2, 3과 같음) `[측정]` | 원자료 `results/20261015_pilot4/`(release 전); 메인 세션 메모 `pilot_mi4_notes.md`, 독립 리뷰 `lineage/IMPL_REVIEW.md`(막는 문제 없음, 고칠 것 F1–F4; 세션 스크래치) |
| 2026-10-15 | 빌드 `ln3`(ln2 + 구현 독립 리뷰와 pilot 4의 고침; 빌드됨, 시험함: CPU만, 클러스터 실행 없음). 구현 독립 리뷰(다른 에이전트, 읽기만, 세션 스크래치 `lineage/IMPL_REVIEW.md`): 막는 문제 0, 사전 등록 전 고칠 것 넷(F1 결함 E 고침의 충돌 행 → 9.7절; F2 낡은 글과 pilot 3, 4 기록 → 9.9, 11, 12, 19절; F3 `mi4_pull` 예상과 상한 → 9.3, 9.9절; F4 결함 E 한계 → 18절), nit 아홉. 라이브러리 고침(호스트만, 장치 바뀜 없음): (1) 남긴 당기기의 상한을 처음 뒤 간격의 4분의 1 번에서 절반 번으로(`gdakiMiPullKeepOk`의 상수; 까닭은 9.3절 "pilot 4에서 본 길"); (2) 폴링 흡수는 열린 segment가 burst segment 바로 다음일 때만(nit N5); (3) 계보의 helper 밖 읽기 검사를 `ts->th.get_id()` 대신 helper가 먼저 세우는 thread_local(`gdakiTsInHelper`, `gdakiTsOwner`)로(nit N1: `std::thread` 이동 대입과의 data race; 단위 장면이 없어 소스 읽기로만 확인, ln3 독립 리뷰 nit 2); (4) 대기 당기기를 비트 둘(새로 옴, 남김)로 두어 `pulls_taken`이 남긴 당기기에 합쳐진 새 당기기를 셈(nit N4; 순수 함수 `gdakiMiPullTakeCounts`. 단위 장면은 이 순수 셈 규칙만 보고 연결(helper의 새로 옴 비트, Take의 꺼냄, AfterStep의 남김 비트)은 보지 않는다: 장면에 그 주석을 더함, 커밋 `4ade864c`, ln3 독립 리뷰 nit 3). [impl/mi_layer.diff](impl/mi_layer.diff) md5 `3e559c866f7a480ed2ac7ce017f8b3f8`, 9 085줄(장치 파일 둘의 diff는 i4와 바이트까지 같음; 공유 헤더 일곱 그대로), 호스트 파일 md5 `35357895fb9b72b500c5893e9ffb9962`(24 487줄). `mi_ln3` libnccl `e927457a4986a8314ce911259beff51c`, `mip_ln3` `58d7ff3f47d89205661a65b90a419298`(호스트 파일 하나만 컴파일, 경고 0). `BR=ln build_mi.sh api` 통과. CPU 단위 시험(ASan, UBSan): `mi_unit_dev` 568 999, `mi_unit_host` 1 563 450(17 함수; 장면 10에 절반 상한, 여섯 번 거절에서 136에 찍히고 lane 최고가 L, 이어지는 거절의 시도 130–140, 145, 150, 당기기 셈 규칙, 두 바꾸기의 DISARM, 모형이라는 머리 주석), `mi_unit_store` 6 543 999, `mi_unit_spare` 187, `mi_unit_lineage` 3 365 checks, 모두 0 failed `[측정]`. 변이 둘(옛 4분의 1 상한, 옛 흡수 조건)을 넣으면 새 장면이 4개, 1개 실패로 잡는다 `[측정]`(이 주장에는 처음에 로그가 없었다: ln3 독립 리뷰의 고칠 것 2. 같은 날 다시 돌려 로그를 남김: 빌드 트리는 읽기만 하고, 그 호스트 파일에서 잘라 낸 순수 영역 사본의 상수 하나만 ln2의 것으로 되돌려 `build_mi.sh` unit 단계와 같은 컴파일 줄로 `mi_unit_host`만 돌림, 커밋 `4ade864c`의 시험 파일. 변이 없음 1 563 450 checks 0 failed, 4분의 1 상한 4 failed(`mi_unit_host.cc` 1145, 1146, 1147, 1156줄), 옛 흡수 조건 1 failed(1201줄, `6f699903`의 줄로는 1199); 세션 스크래치 `agent_mi_fix/unit_ln3_mutation_{none,quarter,absorb}.log`, 스크립트 `agent_mi_fix/unit_ln3_mutation.sh`). 시험 쪽: `rows_mi.py`가 gin-remaining 실행기의 행에도 `lineage_warn`을 셈(nit N3; pilot 4의 `reg_rm4` 행 0), 보고만 하는 열 `post_activate_ms`(`_1`, `_2`; 3절 끝), `selftest_mi.py` 통과(P6 셀 포함); oracle 정의역 주석 (c)와 단계 모양(nit N2). 남긴 nit: N6(9.3절과 18절에 적음), N7(장면 10 머리 주석으로), N8(9.3절 글 고침), N9(`mi_unit_store.cc`의 칸 쓰기 흉내는 설명으로 둠). 기계어 비교(`BR=ln MIOUT=mi_ln3 build_mi.sh ident`, 19 분 54 초, rc 0): ln2와 요약 줄이 모두 같음(매크로 없는 프로그램 넷 × sm_75, sm_86 = 8/8이 hk, i5와 SASS 전체와 자원까지 같음; 장치 객체 i5와 205 + 2, 다른 것 0(연구, 운영); hk와 183 + 2, 22 다름; libnccl `-res-usage`(해시 가림) i5, hk와 같음; 매크로 변형 경고 0, 자원이 다른 수 ff 11, gin_ts2 4, gin_mr 1, ring 8) `[측정]`. 시험 드라이버(`MITREE=agent_mi_fix MIOUT=mi_ln3 COSTOUT=cost_ln3 MROUT=mr_ln3 build_mi_test.sh mi nomacro cost mr`, 설치 헤더 digest `65fdf19b`, 경고 0): `gin_mi` `0d0dd90b4ad740905ce49a9f76043080`, `gin_mi_nomacro` `9fcc9ab4ddab6367c259cc62ef2e5d11`, `gin_ts2_mi` `7e3a2ef6ca4a771e29b39acc7d58d4a1`, `mr_ln3/ff/gin_mr` `00adb957eb65e38b183918817b435fd8`, `mr_ln3/hold/gin_mr` `d914df6def6cce8590e69a953a49d222`. 배포 묶음 set `mi5`와 pilot 5(pilot hold P6: `mi4_pull` n 5, `mi4_kill3_ow` n 1, `mi4_train_kill3` n 1)의 명령은 [impl/test/PILOT_MI.md](impl/test/PILOT_MI.md). ln3의 네 고침은 독립 리뷰를 아직 거치지 않았다. 클러스터 실행 없음 | `agent_mi_fix/out/build_info_ln3.txt`, `build_mi_ln3.log`, `build_mip_ln3.log`, `api_ln3.log`, `unit_ln3.log`, `ident_ln3.log`, `selftest_ln3.log`, `test/build_test_ln3.log`(세션 스크래치); 커밋 `6f699903`, `4068b13f`, `94b91fb6`와 이 행의 커밋 |
| 2026-10-15 19:00–19:03 | pilot 5(채점 제외; 메인 세션이 실행, `cluster_run.sh` 안의 `chain_mi.sh`): 배포 묶음 set `mi5`(빌드 ln3: `mi_ln3` `e927457a`, `mip_ln3` `58d7ff3f`, `gin_mi` `0d0dd90b`, `gin_ts2_mi` `7e3a2ef6`; 시행 meta 7개 모두 `lib_md5` `e927457a`, `driver_md5` `0d0dd90b`), pilot hold P6 하나(19:00:02–19:02:53, hold rc 0, STOP 없음, hold 중 새 mlx5 커널 줄 0, rain QUERY_QP는 hold 전체에서 232 181 늘어남): `mi4_pull` n 5, `mi4_kill3_ow` n 1, `mi4_train_kill3` n 1, 7 시행 `[측정: chain.out, hold_P6.out, raw/*_meta.txt]`. 원자료에서 다시 셈 `[측정]`: `rows_mi.py`로 새로 만든 표가 메인 세션의 `pilot5_mi_rows.csv`와 7행 × 147열 모두 같고, raw에서 따로 센 값(복원 시간, 활성화 뒤 부분, `later_n`, kv의 데이터 열, kept와 spent 줄, `GIN/LN` 줄, 깨짐 줄의 대상)도 같다. 7 시행 모두 rank 3 kill(r3 rc 137) 뒤 복원했고 `wait_held` 1, `ow_data_equal` 1(생존 셋과 되살린 rank의 `x_match`, `sig_exact` 1, 독 값 0), `no_reexec`, `revived_done`, `suppress_ok` 1. 로그 어디에도 `GIN/LN: ` 줄이 없다(`lineage_warn` 0). lane 깨짐은 시행마다 2줄(rank 0과 1에서 rank 2 쪽, 곧 죽은 rank 3의 짝이 맡은 rank: 설계한 짝 보호 공백)이고 `lane_broken_other` 0, `disarm_other` 0. 남긴 당기기: "the pull is kept" 2줄(`mi4_pull` n2의 step 133, n4의 step 131; 둘 다 rank 2), "the pull is spent" 0줄. 둘 다 INJECTED 뒤 "the checkpoint store is not ready"로 두 번 거절되고 셋째 시도(n2 135, n4 133)에 찍혔다(INJECTED → 다시 "store ready" 34.9, 34.7 ms, rank 2 로그의 시각). 셋째 시도라 ln2의 4분의 1 상한(시도 여섯) 안이기도 하다: 이 pilot은 넓힌 상한이 필요한 경우를 만나지 않았고, ln3에서 이 셀들의 회귀가 없음을 보였다 `[추론]`. 복원 시간(ms): 4 KiB 셀 6 시행의 범위 175.7–197.3(kill3_ow 196.2; pull 177.9, 175.7, 176.0, 176.8, 197.3), train_kill3 252.1. 활성화 뒤 부분(`post_activate_ms`): 4 KiB 6 시행 67.3–70.0, train 79.0. 'later' 답 수(`later_n`)는 4 KiB 5–6, train 8로 7 시행 모두 느린 모드(3절 끝). `mi4_pull`의 네 rank 당기기 합은 시행마다 보냄 742–789, 꺼냄 363–390(9.3절의 `pulls_taken` 단위). rain BAR1 시작 문의 Free는 4 KiB 173 MiB, train 133 MiB | 원자료 `results/20261015_pilot5/`(release 전, raw 83 파일); 다시 센 표 `pilot5_recount/rows_mi_recount.csv`, 메인 세션의 표 `pilot5_mi_rows.csv`(세션 스크래치) |
| 2026-10-15 | ln3 독립 리뷰(다른 에이전트, 읽기만; 수정, 빌드, 클러스터, ssh 없음; 세션 스크래치 `lineage/LN3_REVIEW.md`, 146줄): 막는 문제 없음. 범위 확인 `[측정]`: 커밋 `6f699903`이 고친 파일은 `mi_layer.diff`와 `mi_unit_host.cc` 둘이고 장치 파일 둘과 공유 헤더는 그대로, 채점기가 읽는 로그 문장도 그대로; ln2와 ln3의 호스트 차이는 기준 blob에 두 diff를 적용해 다시 만들었고 다시 만든 ln3 호스트 파일이 적용 트리와 바이트까지 같음(md5 `35357895`). 네 고침 모두 맞음 `[소스]`: (1) 상한(간격 20에서 시도 열한 번; 이어지는 BUSY와 1b가 겹칠 때 약 15 Step마다 11번이라는 18절 글이 맞음), (2) 흡수 조건(pilot 3 모양은 그대로 흡수, seg N+2의 진짜 넘침은 숨기지 않음), (3) thread_local 검사(ln2의 `ts->th` data race가 없어지고, detach된 helper의 거짓 WARN도 없어짐), (4) 비트 둘(세 접근 모두 한 원자 변수의 RMW, 장애 없는 셀에서는 ln2와 같은 셈). 고칠 것 2: 9.3절 비용 글과 18절에 멈춤 시한 거절이 빠짐, 12절 ln3 행의 변이 시험에 로그가 없음. nit 4: `pulls_taken`의 단위, thread_local 검사에 단위 장면 없음, 비트 둘의 장면은 연결을 시험하지 않음, 18절 마지막 항목의 "다시 세지 않음"은 남긴 당기기에만 맞음. 반영(문서와 시험 파일의 주석만; 라이브러리와 빌드는 바뀌지 않음): 9.3, 18, 19절의 멈춤 시한(커밋 `8f15b189`), `mi_unit_host.cc` 주석(`4ade864c`), `rows_mi.py` 머리 설명(`bf182d8a`; pilot 5의 표 출력이 고치기 전과 바이트까지 같고 `selftest_mi.py` 통과 `[측정]`), 12절 ln3 행의 변이 로그와 9.3, 18절의 nit(`00409df1`) | `lineage/LN3_REVIEW.md`, `agent_mi_fix/unit_ln3_mutation_{none,quarter,absorb}.log`(세션 스크래치); 위 커밋과 이 행의 커밋 |
| 2026-10-15 | 사전 등록 전 일관성 고침 1(DRAFT라 고칠 수 있음; 2절 가설, 메인 세션 지시): pilot과 맞지 않거나 3절과 어긋난 가설 다섯 행. (1) 복원 시간: 더하기 꼴(gin-restore의 복원 + drain + 바이트 / θ)을 버리고 셀 가족마다의 상한(학습 모양 밖 2 000 ms, 학습 모양 1 000 ms; 초안)과 FETCH 모형(a + 바이트 / θ)으로 씀. mirror 켬 길은 RDMA FETCH와 단계 맞춤 가져오기라 TCP 길보다 짧다(pilot 2–5: 학습 모양 밖 mirror 켬 죽음 38건 72.2–206.4 ms, mirror 끈 gin-restore 회귀 7건 365.5–380.7 ms). (2) 비용: 차례 없는 따로 된 QP의 WQE 하나라 4 KiB는 많아야 put 하나의 지연, 2 MiB 약 2배, 묶음 대역 약 절반(pilot 2–4 mirror-peer 대 on +8.19–8.90 µs, 1.855–1.872배, 0.552–0.635); 판정의 수는 3절이 정하고 사용자 결정 대기(19절). (3) 당기기: 반증은 설계한 짝 보호 공백 밖의 깨짐과 DISARM만(3절, 채점 셈 고침 행과 같음). (4) pool: 3절과 채점기의 열(`pool_max_bytes`, 다시 시작)에 맞춤. (5) 버려진 체크포인트 "둘 넘게" → "둘 이상"(3절의 ≤ 1과 같게). 수치는 pilot 2–5의 원자료에서 `rows_mi.py`로 다시 셈(세션 스크래치 `prereg_recount/p{2,3,4,5}.csv`) `[측정]` | 이 행의 커밋 |
| 2026-10-15 | 사전 등록 전 일관성 고침 2(DRAFT; 3절 `train_pull_count`의 근거 칸과 9.8절 학습 모양의 pool 문장): "당기기는 L이 간격 둘이라 0에 가까움 `[추론]`"과 "확정이 늦을 때만 당긴다"는 pilot과 반대였다. L이 간격 하나 바이트의 두 배라 문턱 50%가 간격 하나와 같아 간격마다 문턱에 닿는다 `[추론]`. 장애 없는 학습 시행의 네 rank 합 `pulls_sent` 847, 834(pilot 2, 3), kill 시행 655–698(n 6) `[측정: rows_mi.py로 다시 셈]`. 당기기는 그대로 보고만 하는 열이고 판정식(predictions_mi.csv 30줄)은 바뀌지 않음 | 이 행의 커밋 |
| 2026-10-15 | 사전 등록 전 일관성 고침 3(DRAFT; 3절과 7절의 찾는 키와 셀 이름을 고정할 파일 [impl/test/predictions_mi.csv](impl/test/predictions_mi.csv), [impl/test/cells_mi.json](impl/test/cells_mi.json)의 이름에 맞춤; 파일은 바뀌지 않음). 3절: `ow_data_equal`의 셀 셋을 파일대로 셋으로 나눔(`ow_data_equal` `mi4_kill3_ow`, `kill_other_ow` `mi4_kill1_ow`, `ckpt_kill_ow` `mi4_kill3_ckpt_ow`); `pull_no_disarm` → `pull_no_disarm_none`(`mi4_pull_none`)과 `pull_no_disarm_kill`(`mi4_pull`); `refuse_mirror` → `refuse_csum`, `refuse_mirror1`, `refuse_sl`(빠졌던 `mi4_refuse_sl` 셀과 그 예측을 더함); `regression_restore_off`(mirror 끔) → gin-restore 셀의 `rg_*` 열다섯과 gin-remaining 실행기의 `regression_restore_off`, `regression_kill3_off`; `regression_restore_on` → `regression_none_on`(`rs4_none_mion`), `regression_kill3_on`(`rs4_kill3_mion`); `pool_vs_interval`과 `store_rdma`의 열과 셀을 파일대로. `ff_identical`은 파일에 없었다: 시행의 원자료가 아닌 빌드 검사라 예측 표에서 빼고 7절 빌드 검사와 10절 QA로 둠(ln3에서 8/8 확인, 12절 ln3 행). 7절: `mi4_pull` 한 행 → `mi4_pull_none` 3과 `mi4_pull` 5, `mi4_refuse_sl` 3을 더함, mirror 켠 회귀 `rs4_none_mion`, `rs4_kill3_mion`, mirror 끈 회귀의 셀 이름과 n을 파일대로 적음. 판정식과 n은 바뀌지 않음(모두 파일에 이미 있던 값) | 이 행의 커밋 |
| 2026-10-15 | 사전 등록 전 일관성 고침 4(DRAFT; 8절). (1) rain BAR1 128 MiB 검사를 읽는 곳을 적음: hold 시작 문(첫 시행 전, 시험 프로세스 없음; pilot 2–5 hold 15개 앞뒤 30번 모두 Free 251 MiB). 학습 hold의 시행 시작 문 값은 프로세스 둘이나 셋이 살아 있을 때라(pilot 3–5: 둘 133, 173 MiB, 셋 74, 134 MiB) 보고만. (2) QUERY_QP 상한의 단위를 시행 하나로 적음(`hold_mi.sh`의 `after_trial`이 시행마다 앞 읽기와의 차를 견줌; 실행기는 hold 단위로 견주지 않으므로 그대로) 그리고 값 50 000을 pilot으로 정함: 15 hold에 `qp_over.txt` 없음, hold 평균 18 155–33 169(가장 큰 P6이 상한의 약 0.66배), 시행마다의 최대는 기록되지 않아 `[미확인]`. (3) 시행 시간 한도: 학습 모양 150 s(`hold_mi.sh` 기본값과 같게; 처음 120 s), 잰 학습 시행 30.2–34.6 s(n 8)로 어림 24–28 s를 고침; 회귀 실행기 150 s, 그 밖 60 s. 수치는 pilot 2–5의 스냅숏, 시행 meta, hold 출력에서 다시 셈 `[측정]` | 이 행의 커밋 |
| 2026-10-15 | 사전 등록 전 일관성 고침 5(DRAFT; 9.7절 결함 E의 거절 까닭 행): ln3 독립 리뷰의 고칠 것 1이 9.3절과 18절에만 더한 멈춤 시한 거절("no PAUSED from every peer within NCCL_GIN_RESTORE_PAUSE_MS")이 충돌 표 행에 없었다. 행에 그 거절과 비용(application thread가 시도마다 시한만큼, 이어지면 열한 번 약 22 s `[추론]`), 근거 줄(ln3 호스트 파일 `35357895`)을 더하고, 상태를 9.3, 18, 19절과 같게 "다섯과 BUSY는 닫힘, 멈춤 시한 거절은 사용자 결정 대기(그대로 두면 18절 한계로 닫음)"로 적음. 9.7절 끝의 두 문단(결함 E 행을 설계로 닫은 글, "열린 충돌 없음")에 그 결정 대기를 적음. 라이브러리와 빌드는 바뀌지 않음 | 이 행의 커밋 |
| 2026-10-15 | 사전 등록 전 일관성 고침 6(DRAFT; 7절 seed와 n): `mi4_train_kill3` 행의 "seed는 사전 등록 때 고정"을 규칙으로 적음(표 아래 문단): draw(sha256, seed, 셀, 시행, first/second)와 셀마다의 범위, pilot 1–5가 자리값 `mi-v1`로 돌아 시행 번호가 같으면 kill이 같았다는 것(`mi4_train_kill3` n1은 pilot 2, 3, 5 모두 단계 1 689의 6 085 µs) `[측정: 시행 meta]`, 그래서 사전 등록 커밋에서 본 실행 hold(G1, T1, T2)의 `DIE_SEED`를 새 문자열로 바꿈(문자열은 사전 등록 때 정함). `mi4_kill2_kill3_ow`의 kill 범위(180–220, 380–420)를 적음. n은 초안 그대로(cells_mi.json과 같음, "초안" 표시 유지). 같은 커밋: 머리의 마지막 갱신 줄, 11절 체크리스트 | 이 행의 커밋 |

## 13. 사전 등록 이후 변경

없음(사전 등록 전).

## 14. 원자료와 결과표

없음(실행 전).

## 15. 결과 요약

`[미확인]` 실행 전.

## 16. QA와 재현성

실행 전. 기준 계층은 [../restore/impl/rs_layer.diff](../restore/impl/rs_layer.diff)(md5 `f005bb67`).

## 17. 결론

실행 전.

## 18. 한계

설계 단계의 한계(구현 뒤 다시 씀):
- 원격 완료만 보고 원본을 다시 쓰는 application은 지원하지 않는다(2026-10-13 사용자 결정). 라이브러리가 검사하지 않으므로 어긴 application은 그 뒤의 복원이
  조용히 틀릴 수 있다.
- 짝이 되살아난 뒤 맡은 rank는 짝의 hold, 억제, 체크포인트 간격 하나, 전체 올리기 시간 동안 보호받지 못한다(9.6절).
- 끝점 갱신은 되살린 rank가 같은 노드와 NIC에 있다고 보고 GID, LID를 기록 그대로 쓴다(9.4절). 예비 프로세스가 다른 노드에 있는 경우는 gin-restore처럼 재지
  않았다. 같은 rank의 두 번째 복원도 재지 않는다.
- 체크포인트가 게시 뒤 연달아 버려지면 넷째 자리에서 그 받는 rank를 DISARM하고 다시 시작하므로 그 확정까지 보호가 없다(9.3절).
- 단계 맞춤 가져오기의 요구 14(단계 t 커널은 단계 t의 put만 읽음)는 검사하지 않는다. 어기면 재실행이 조용히 틀릴 수 있다.
- 멈춤 안 D2H만큼 생존 rank의 입력 멈춤이 길고(학습 모양 2.4 ms, 멈춤 약 8 ms), 멈춤 밖 WRITE만큼 체크포인트를 찍는 rank의 Step이 길다(부하에서 19–24 ms,
  9.8절 확인 3). 올리기는 그 rank의 선을 application과 나눈다.
- 자기 루프 lane의 오류와 mirror QP의 장애 기록은 그 받는 rank의 보호를 (짝이 되살아날 때까지) 끈다.
- 이 testbed의 짝 규칙에서는 노드를 건너는 put의 mirror가 선을 건너지 않는다(5절). 셋 이상 노드의 비용은 재기만 하는 모드의 peer 팔로 대신 잰다.
- 호스트 메모리의 drain 울타리: 확인 1에서 울타리 없이 곧바로 읽어도 어긋남이 없어(9.8절) 울타리가 필요한지는 보이지 못했다. 울타리는 설계대로 둔다.
- 학습 모양은 전송 모양과 덮어쓰기 차례만 흉내 낸다. 실제 학습(PyTorch, collective, 계산)은 재지 않는다(4절).

구현과 통합 뒤 알려진 것(2026-10-15, 실행 전; `[소스]`와 `[추론]`, 12절의 통합 행):
- drain의 울타리 READ가 실패하면 GIN PD 루프백 쌍이 끈적이게 깨져, 그 rank가 짝인 뒤의 drain이 모두 거절된다(그 맡은 rank들의 복원은 fallback).
- 예비 프로세스가 READY 뒤 FETCH에 실패하면 짝은 알리지 않는다. 생존 rank는 hold 시한까지 기다린 뒤 fallback한다.
- 되살린 rank의 가져오기가 "쓸 수 없음"(생존 rank의 mirror 셈이 무효)으로 둔 mirror QP는 그 상대의 다음 복원 라운드까지 쓰지 않는다. 그 QP로 가는 lane의 보호가 그동안 꺼진다.
- 재기만 하는 모드의 mirror 팔은 helper 걸음(약 1 ms)마다 커서를 되돌린다. helper가 L/2를 채울 만큼 늦으면 그 실행은 깨짐으로 무효가 된다.
- hk의 NIC 복사 경로 루프백 QP 쌍은 qp_context가 비어 있다(hk 코드, 이 계층이 고치지 않음). net_ib 비동기 이벤트가 그 QP에 오면 널 역참조가 날 수 있다 `[추론]`.
- 자기 루프 lane의 CQ 폴링과 창 검사, `rsMiWait`의 20 ms 정지 판정은 DOCA의 자리 기다림 의미에 기댄다. 실제 HCA에서는 pilot이 처음 본다.

pilot 뒤 알려진 것(2026-10-15, pilot 1–4; 12절):
- 되살린 rank는 자기 예비 프로세스가 없어 다시 무장되지 않는다(gin-restore 규칙 `gdakiCkptSelfOf().haveSpare`; 복원 뒤 그 rank의 체크포인트는 "not armable" `[측정: pilot 2 raw/mi4_kill3_ow_mi_n1_spare.log, 23줄 모두]`). 그 rank가 다시 죽으면 되살리지 못하고 fallback한다. 그 rank가 맡은 rank의 보호는 되찾는다(9.6절, 둘째 죽음 셀). 되살린 rank까지 보호하려면 예비 프로세스를 다시 등록하는 장치가 필요하고, 이 실험의 범위 밖으로 둔다(2026-10-15 제안, 사용자 결정 대기, 19절).
- 예비 프로세스의 활성화 관문(gin-restore의 `gdakiRsActExamine`)은 원래 프로세스의 `/proc/<pid>/stat` 상태가 Z(zombie)면 "끝남"으로 친다 `[소스]`.
  다중 thread 프로세스에서 main thread가 먼저 끝나면 다른 thread가 정리(CUDA context와 RDMA 자원 해제)를 하는 동안에도 Z로 보이므로, 예비 프로세스는 원래
  프로세스가 다 끝나기 전에 활성화될 수 있다 `[추론]`. pilot 2–4의 52건 가운데 6건이 그랬고 데이터 문제는 없었다(6건 모두 데이터 열 1; hold 시작이 죽은
  rank 쪽 QP를 ERR로 옮겨 옛 프로세스가 생존 rank에 쓸 길이 없음 `[추론]`) `[측정]`. 실제로 언제 다 끝났는지 보여 주는 줄은 원자료에 없다 `[미확인]`.
  관문을 좁히는 것(`/proc/<pid>/status`의 `Threads:`가 1인 Z만, 또는 pidfd로 그룹이 빌 때)은 라이브러리 변경이라 충돌 표 행과 독립 리뷰가 먼저이고, 사용자
  결정으로 남긴다(19절).

계보 설계 뒤 알려진 것(2026-10-15, 9.9절; `[소스]`, `[추론]`):
- mirror 끈 TCP 길의 FETCH와 UPLOAD는 화신을 보지 않고 체크포인트 번호만 본다. 짝의 확정 이미지는 승격에서 지우지 않아 셋째 화신이 이 길에 있으면 옛
  화신의 같은 번호 이미지를 줄 수 있다. fallback 뒤 예비 프로세스가 이미지를 받아도 그 REJOIN에 거절된 생존 rank가 FAIL로 답해 끝난다. 사용자
  결정(2026-10-15)으로 이 길은 그대로 둔다.
- 되살린 rank는 다시 무장되지 않는다(위 항목). 사용자 결정(2026-10-15)으로 범위 밖이고 설계만 9.9절에 둔다. 같은 rank의 두 번째 복원(셋째 화신)은
  단위 시험으로만 본다.
- 빌드 i4까지는 예비 프로세스의 생존 rank 칸이 OFF(0)으로 남아, 되살린 rank가 다시 무장된다면 그 rank의 둘째 hold가 진단 줄 없이 시한 fallback으로
  끝났을 것이다(지금 셀에서는 닿지 않음). 계보 빌드는 REJOIN_ACK에서 칸을 쓴다.
- 계보의 BAD(불변식 어김)는 known을 그 rank의 지금 화신으로 쓰고 `GIN/LN` 줄 하나를 남긴다. 원인은 그 줄만으로는 알 수 없다.

결함 E 고침 뒤 알려진 것(2026-10-15, 9.3절과 9.7절의 결함 E 행; 빌드 ln3; `[소스]`, `[추론]`):
- 남긴 당기기는 처음 시도 뒤 간격의 절반 번까지만 다시 묻는다(간격 20에서 시도 열한 번, 4 KiB 셀의 걸음으로 요청 뒤 약 86 ms). 그보다 오래가는 거절에서는
  당기기를 쓰고 다음 체크포인트가 간격과 4분의 1 back-off로 밀린다. 짝이 되살아난 뒤 맡은 rank의 "저장소 준비 전" 거절에서는 그 rank 쪽 lane이 무효라
  넘치지 않고 설계한 짝 보호 공백이 길어질 뿐이지만, lane이 유효한 채 거절이 오래가면(예: 올리기 QP의 ERR 뒤 다시 청한 저장소가 늦음, 이어지는 BUSY) L이 간격
  하나의 바이트보다 작은 셀(`mi4_pull`)에서는 lane이 넘쳐 그 rank가 DISARM된다(설계한 마지막 수단). 이 경우는 셀이 지나지 않는다.
- 멈춤 시한 거절("no PAUSED from every peer within NCCL_GIN_RESTORE_PAUSE_MS")도 남긴 당기기가 다음 Step에 다시 묻는다. 이 거절은 helper가 시한(기본
  2 000 ms)까지 기다린 뒤에 오고 그동안 application thread가 `gdakiStoreTake`의 기다림에 묶이므로, 시한 거절이 이어지면 application이 최대 열한 번(ln2는
  여섯 번) 연달아 약 2 s씩 선다(9.3절, ln3 독립 리뷰의 고칠 것 1) `[소스, 추론]`. 지금 셀에서는 닿지 않는다 `[추론]`. 시한 거절을 남기지 않게 좁힐지는 사용자
  결정이다(19절).
- 폴링 흡수는 두 폴링(10 ms) 사이에 바꾸기가 한 번이라고 본다. 둘 이상이면 흡수하지 않으므로 앞 burst의 꼬리가 DISARM을 한 번 더 내고 그 rank의 다시 무장이
  체크포인트 하나 밀린다(보수적). 확정 체크포인트 둘이 10 ms 안에 오려면 새 segment가 그 사이 문턱을 넘어야 해 지금 셀에서는 닿지 않는다.
- 남긴 당기기와 1b(되돌린 segment의 둘째 당기기)가 겹친 이어지는 BUSY에서는 시도 빈도가 상한에 묶이지 않는다: 시도마다의 되돌리기가 새 당기기를 걸어, 상한을
  다 쓴 뒤 4분의 1 back-off가 끝나면 다시 시작한다. 간격 20에서 약 15 Step마다 11번(ln2는 10 Step마다 6번)이고, 시도마다 다른 rank가 빈 멈춤 라운드를 한 번
  한다. BUSY가 끝나면 멎는다.
- 남긴 당기기의 시도 횟수와 거절 까닭은 처음 남길 때와 다 쓸 때의 줄 둘과 "not taken" 줄로만 보인다. 요약의 `pulls_taken`은 남긴 당기기를 다시 세지 않는다.
  이 "다시 세지 않음"과 시도 빈도의 상한(간격의 절반)은 남긴 당기기에만 걸린다(ln3 독립 리뷰 nit 4) `[소스, 추론]`: 이어지는 BUSY에 1b가 겹치면 시도마다의
  되돌리기가 새 CKPT_PULL을 걸고 그것은 새로 옴 비트로 와서 세므로, `pulls_taken`이 시도마다 늘 수 있다. 보고만 하는 열이라 채점에는 닿지 않는다.

## 19. 다음 작업

- 사용자 결정 넷(2026-10-15, 메인 세션이 물음; 답을 받으면 메인 세션이 이 항목과 12절을 고침):
  1. 채점 셈: `pull_no_disarm_kill`과 `train_pull_count`에서 설계한 짝 보호 공백(9.6절)의 lane 깨짐과 DISARM을 빼고 셈. 제안대로 구현함(12절의 셈 고침 행), 결정 대기.
  2. `mi4_overflow`: 예비 프로세스의 활성화 기다림 30 000 → 15 000 ms, 판정식에 "hold가 시작되면 fallback으로 끝남"도 받음. 따로 된 커밋으로 구현(12절의 그 행; 거절이면 그 커밋을 뺌), 결정 대기.
  3. 결함 D 고침(공유 인터페이스를 바꿈)의 독립 리뷰: 했음(`mi_fix_review.md`, 세션 스크래치; 막는 문제 없음). 사전 등록 전 항목은 12절의 그 뒤 행들.
  4. 되살린 rank의 다시 무장(예비 프로세스 다시 등록): 범위 밖으로 두는 제안(18절 한계). 닫힘(2026-10-15, 계보의 열린 충돌 3의 답 (가): 계보만, 다시 무장은 설계로만).
- 닫힘(2026-10-15): 빌드 i4의 set `mi3`로 pilot 3을 돌렸다(12절). rain BAR1은 세 프로세스가 살아 있을 때 Used 182 MiB, Free 74 MiB였다. pilot 3이
  찾은 결함 E는 고쳤고(빌드 ln2) pilot 4에서 `mi4_pull`의 공백 밖 깨짐이 0이었다.
- 사전 등록: pilot 2의 값에서 문턱(복원 시간, 입력 멈춤, 비용), seed, n, 제외와 중단 규칙을 정함(초안 `prereg_mi_draft.md`, 세션 스크래치). 비용 예측의 꼴은 사용자 결정: peer 팔은 따로 된 mirror QP의 두 번째 쓰기라 2 MiB에서 on의 약 1.9배이고 4 KiB에서 +8–9 µs여서(pilot 2, k1) 3절 초안의 한도(+2.5 µs, 0.40–0.60)와 맞지 않음. 그 뒤 `prereg/gin-mirror-v1`.
- 실행 가능성 확인 2(손으로 하는 mirror 비용)는 같은 `gin_ts2_mi`로(남음).
- 사용자 결정(2026-10-15 제안): 예비 프로세스의 활성화 관문을 "모든 thread가 끝남"으로 좁힐지(18절). 좁히면 빠른 모드가 없어지고 4 KiB 복원은 약 175–200 ms
  한 모드가 될 것이다 `[추론]`. 그대로 두면 사전 등록에 두 모드를 예상으로 적고 3절 끝의 보고 규칙을 쓴다. 고친다면 사전 등록 태그 전에, 충돌 표 행과 독립
  리뷰 뒤에 한다.
- 사용자 결정(2026-10-15, ln3 독립 리뷰의 고칠 것 1에서): 멈춤 시한 거절("no PAUSED from every peer within NCCL_GIN_RESTORE_PAUSE_MS")에서는 남긴
  당기기를 다시 묻지 않고 쓰게 좁힐지(9.3절, 18절). 좁히면 그 거절 뒤에는 지금의 4분의 1 back-off로 돌아가, 남긴 당기기 때문에 application이 약 2 s씩 더
  서는 일이 없어진다 `[추론]`. 라이브러리 변경이라 충돌 표 행과 독립 리뷰가 먼저이고, 고친다면 사전 등록 태그 전에 한다. 그대로 두면 18절의 한계로 둔다.
- 계보(9.9절)와 결함 E 고침: 빌드 `ln2`와 pilot 4까지 끝남, 그 뒤 리뷰와 pilot 4의 고침이 빌드 `ln3`(12절). 닫힘(2026-10-15): set `mi5`로 pilot 5(pilot
  hold P6)를 돌렸고(12절; 남긴 당기기 둘이 셋째 시도에 찍힘, 공백 밖 깨짐 0), ln3의 네 고침(상한 상수, 흡수 조건, thread_local 검사, 당기기 셈)은 독립 리뷰를
  거쳤다(막는 문제 없음; 고칠 것 둘과 nit 넷은 문서와 시험 주석으로 반영, 12절의 리뷰 행). 남은 것은 위 멈춤 시한의 사용자 결정. 사전 등록은 그
  뒤(본 실행 빌드의 계획은 ln3, pilot 5가 확인하지 못하면 ln2였다).
- 이 실험 뒤의 작업: 되살린 rank의 다시 무장(9.9절의 설계; 예비 프로세스가 ACTIVATE 화신을 기대 값과 견주는 검사를 먼저). STORE_ACK의 `wardInc`(계보의 열린
  충돌 1의 (가))도 그때.

## 20. 참고자료

- [../restore/EXPERIMENT.md](../restore/EXPERIMENT.md) 9.2–9.11절(설계와 상호작용 표), 15절(결과), 18–19절(한계와 다음 작업)
- [../restore/impl/rs_log_api.h](../restore/impl/rs_log_api.h), [rs_ckpt_api.h](../restore/impl/rs_ckpt_api.h),
  [rs_hold_api.h](../restore/impl/rs_hold_api.h), [rs_spare_api.h](../restore/impl/rs_spare_api.h)
- [../restore/results/20261013_main/](../restore/results/20261013_main/)(SCORE.md, trials_scored.csv, qa_recount.md)
