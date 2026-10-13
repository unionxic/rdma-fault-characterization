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
| 마지막 갱신 | 2026-10-13, 사용자 결정 반영(셋째): 앞서 되살린 rank를 생존 rank로 만나는 예비 프로세스의 충돌을 (가)로 닫음: 끝점을 ACTIVATE 연결의 표, TOKEN의 QPN, STATE의 rkey 목록으로 줌(9.4절 끝점 갱신, 9.7절). 열린 충돌 없음. 그 전(같은 날): 열린 충돌 둘을 닫음(원본은 local 완료 뒤에만 다시 씀; 복원 뒤 전체 이미지 다시 받기), 둘째 죽음 셀을 판정 셀로; 초안(1–11절, 설계, 충돌 표). 구현과 빌드 없음 |

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

## 2. 가설

DRAFT다. 사전 등록 때 고정한다.

| 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|
| 덮어써도 정확한 복원: 재실행에 들어가는 모든 put 내용이 pool에서 오면, 보낸 버퍼를 local 완료 직후 다시 쓰는 workload의 최종 데이터가 장애 없는 실행과 비트 단위로 같다 | mirror 켠 kill 셀에서 어느 rank의 최종 상태나 받은 칸이 기준과 다른 시행이 있다, 또는 내보내기가 원본 바이트를 실은 시행이 있다 |
| 대조: 같은 workload를 mirror 없이 되살리면 틀린다(checksum 끔) 또는 거절된다(checksum 켬) | mirror 끈 덮어쓰기 kill 셀에서 데이터가 같거나 fallback 없이 끝난다 |
| 복원 시간은 gin-restore의 복원 시간 + 짝의 drain + 가져오는 segment 바이트 / 자료 소켓의 처리량이다 | segment가 클수록 복원 시간이 줄거나, 가장 큰 segment 셀에서 2 000 ms를 넘는다 |
| 정상 경로 비용은 mirror 쓰기 하나다: 4 KiB 지연은 로그 켬 팔보다 수백 ns 늘고, 묶음 대역은 보내는 쪽이 두 배를 읽고 보내므로 많아야 절반으로 준다 | 4 KiB 지연 증가가 문턱(초안 0.5 µs)을 넘거나 묶음 대역이 로그 켬 팔의 50% 아래다 |
| pool 메모리는 체크포인트 간격 × 단계당 바이트에 비례하고 살아 있는 segment는 둘(늦은 확정이면 셋)이다 | 간격을 두 배로 했을 때 lane 최대 채움의 비가 2와 ±25% 넘게 다르다, 또는 넷째 segment가 쓰인다 |
| 당기기가 넘침을 막는다: 단계 하나가 lane에 들어가면 DISARM 없이 지나간다 | 당기기 셀에서 DISARM 줄이 나오거나 kill 시행이 fallback한다 |
| 회귀 없음: mirror를 끄면 gin-restore의 비용 밖 예측이 원래 기준대로 맞고, 켜도(덮어쓰지 않는 workload) 같다 | 그 예측 가운데 원래 판정식을 어기는 것이 있다 |
| 복원 뒤 보호를 되찾음: 짝 b가 되살아나면 b가 맡은 rank d의 다음 올리기가 전체 이미지가 되어 확정되고, 그 멈춤에서 lane이 다시 켜져 d가 다시 무장되며, 그 뒤 d가 죽어도 되살아난다 | d의 RESTORED 뒤 체크포인트가 둘 넘게 void가 되거나, d가 다시 무장되지 않거나, 다시 무장된 뒤 d의 kill이 fallback하거나 데이터가 기준과 다르다 |

## 3. 사전 예측 (측정 전에 작성)

DRAFT다. 문턱과 n은 pilot 뒤 고정한다. 판정은 유효한 시행만으로 센다(8절). "≥ k/n"은 유효 시행 n개 가운데 조건이 참인 것이 k개 이상이라는 뜻이다.

| 무엇을 예측했나 | 셀 | 시행마다의 조건 | 판정식(초안) | 근거 | 찾는 키 |
|---|---|---|---|---|---|
| 덮어쓰는 workload에서 생존 rank의 대기가 붙잡힘 | `mi4_kill3_ow` | 모든 생존 rank의 `waitSignal`이 문턱 이상으로 돌아옴, 비동기 오류 0, 거절 줄 0 | ≥ 9/10 | gin-restore 9.2절 | `ow_wait_held` |
| 같은 셀: 최종 데이터가 기준과 같음 | `mi4_kill3_ow`, `mi4_kill1_ow`, `mi4_kill3_ckpt_ow` | 모든 rank의 최종 상태, 받은 칸, 신호 값이 호스트 기준과 비트 단위로 같음 | ≥ 9/10, ≥ 4/5, ≥ 4/5 | 9.4절 | `ow_data_equal` |
| 생존 rank는 다시 실행하지 않음, 되살린 rank가 끝까지 감 | `mi4_kill3_ow` | 생존 rank 단계 실행 수 모두 1, 되살린 rank exit 0 | 10/10, ≥ 9/10 | gin-restore 9.6절 | `ow_no_reexec`, `ow_revived_done` |
| 다시 보내기 억제가 정확함 | `mi4_kill3_ow` | 사용자 문맥 통로마다 억제 수 = 누적 실행 수 − 체크포인트 때 실행 수, mirror 통로의 예산 0 | ≥ 9/10 | 9.2절 완료 세기 | `ow_suppress_exact` |
| 재실행의 내용은 모두 pool에서 옴 | `mi4_kill3_ow` | 내보내기가 실은 원본 바이트 0, 절단점 뒤의 내용 있는 put 항목이 모두 MIRROR 표시, 가져오기가 pool에서 쓴 바이트 = 그 항목들의 바이트 합 | ≥ 9/10 | 9.4절 | `ow_from_pool` |
| 복원 시간이 한도 안 | `mi4_kill3_ow` | 첫 죽음 판정 줄 → 마지막 생존 rank의 복원 완료 줄 ≤ 2 000 ms | ≥ 9/10 | gin-restore의 2 000 ms 문턱 | `ow_restore_time` |
| 대조: mirror 없이 덮어쓰면 데이터가 틀림 | `mi4_kill3_ow_nomirror` | 복원은 끝나고(대기 붙잡힘) 되살린 rank의 받은 칸이나 상태가 기준과 다름 | ≥ 4/5 | 1절 문제 `[추론]` | `nomirror_corrupt` |
| 대조: checksum 표본이면 찾아서 fallback | `mi4_kill3_ow_sampled` | 내보내기 꼬리에 "source buffer changed", fallback 줄, 대기가 fallback + 2 000–2 500 ms에 오류로 풀림 | ≥ 4/5 | gin-restore 9.5절 | `nomirror_detect` |
| 복원 시간이 segment 바이트와 함께 늚 | `mi4_seg_4k`, `mi4_seg_32k`, `mi4_seg_128k` | 셀마다 복원 시간, 가져온 segment 바이트, drain 시간 | 중앙값이 바이트 순서대로 늘고 모두 ≤ 2 000 ms; 기울기(ms/MiB)는 보고 | 9.4절 끝의 어림 | `seg_restore_slope` |
| pool 메모리는 간격에 비례 | `mi4_int_10`, `_20`, `_40` | lane마다 segment 최대 채움 | 간격이 두 배일 때 채움의 비 2 ± 25%; pool 바이트는 보고 | 9.3절 | `pool_vs_interval` |
| 당기기가 넘침을 막음 | `mi4_pull` | 20단계마다 당기기 ≥ 1, DISARM 0; kill 시행은 위 대기와 데이터 조건 | 장애 없음 3/3, kill ≥ 4/5 | 9.3절 | `pull_no_disarm` |
| 넘치면 DISARM하고 fail-fast | `mi4_overflow` | lane 깨짐 줄과 DISARM 줄, hold 시작 줄 없음, 대기가 죽음 판정 + 2 000–2 500 ms에 오류로 풀림 | ≥ 4/5 | 9.3절 끝 수단 | `overflow_failfast` |
| 장애 없음: 데이터 같음, 복원 0, 멈춤이 짧음 | `mi4_none_ow` | 데이터 같음, 복원 0, 입력 멈춤 ≤ 10 ms, BUSY(segment 참) 0 | 5/5 | gin-restore `none_clean` | `ow_none_clean` |
| 켤 수 없는 mirror 설정은 모든 rank가 같은 이유의 오류 | `mi4_refuse_csum`, `mi4_refuse_mirror1` | 모든 rank의 Resume 오류, 이유 문자열이 같음 | 셀마다 3/3 | 9.7절 Resume 조건 | `refuse_mirror` |
| 짝이 되살아난 뒤 맡은 rank가 보호를 되찾음 | `mi4_kill2_kill3_ow` | rank 2의 복원이 `mi4_kill3_ow`의 대기와 억제 조건을 채우고, RESTORED(2) 뒤 rank 3이 처음 멈춤에 성공한 체크포인트의 올리기가 전체 이미지(`baseCkpt = ~0`)이며 되살린 rank 2에서 확정됨, 그 사이 확정되지 못하고 버려진 rank 3의 체크포인트 ≤ 1, 둘째 kill 전에 모든 생존 rank에서 rank 3이 다시 무장되고 보내는 rank마다 rank 3의 lane이 다시 켜짐 | ≥ 4/5 | 9.6절 | `reimage_after_restore` |
| 그다음 맡은 rank의 죽음도 되살림(둘째 죽음) | `mi4_kill2_kill3_ow` | 두 죽음 모두 생존 rank의 대기 붙잡힘과 비동기 오류 0, 생존 rank의 단계 실행 수 모두 1, 복원마다 ≤ 2 000 ms, 끝에 모든 rank의 데이터가 기준과 같음, 둘째 복원의 이미지와 segment가 되살린 rank 2에서 옴. 다시 무장되기 전에 둘째 kill이 나면 조건 불충족으로 셈(제외 아님) | ≥ 4/5 | 9.4절(끝점 갱신), 9.6절 | `second_death_restored` |
| 회귀(mirror 끔) | gin-restore 7절의 복원, 거절, 회귀 셀 `@mi` | 그 실험의 원래 판정식 | 원래 기준 | 9.7절 회귀 행 | `regression_restore_off` |
| 회귀(mirror 켬, 덮어쓰지 않는 workload) | `rs4_kill3`, `rs4_none` `@mi`, mirror 켬 | 같은 판정식 | 원래 기준 | 같음 | `regression_restore_on` |
| mirror의 4 KiB 지연 | 비용 가족 mirror, 지표 `lat4k`, 노드 둘 | 팔 `mirror-self`, `mirror-peer` 대 `on`(로그 켬)의 중앙값 차이 | 노드마다 +0.5 µs 안(사용자 예상 "수백 ns"; 9.7절 장치 게이트 행의 어림은 더 클 수 있음) | 9.2절 | `cost_mirror_lat4k` |
| mirror의 256 KiB 지연 | 같은 가족 `lat256k` | 같은 차이 | 보고만 | 9.2절 | `cost_mirror_lat256k` |
| mirror의 묶음 대역 | 같은 가족 `bw256k` | `mirror-*` / `on` | 노드마다 ≥ 50% | 9.2절 | `cost_mirror_bw` |
| 매크로 없는 프로그램은 그대로 | fail-fast 기계어 비교 | 매크로 없는 프로그램 넷의 SASS 전체와 자원, 라이브러리 장치 객체가 `rs`와 같음 | 같음 | 9.5절 | `ff_identical` |

## 4. 범위

**포함.** 9절의 설계(mirror 쓰기, pool, segment와 당기기, 복원 경로, 기존 장치와의 충돌 표), gin-restore 계층 위의 구현(충돌이 닫힌 뒤), 덮어쓰는 시험
workload, 7절의 셀.

**제외.**
- 동시에 둘 이상 죽는 것, 짝과 그 짝(서로의 짝)이 함께 죽는 것, 복원 중의 둘째 죽음: 단일 실패 범위(사용자 결정 5).
- 원격 완료(받는 쪽이 되보낸 신호)만 보고 보낸 버퍼를 다시 쓰는 application: 지원하지 않는다(2026-10-13 사용자 결정, 9.5절의 application 요구).

복원 뒤 되살린 rank가 맡은 rank의 체크포인트와 pool을 다시 세우는 것(전체 이미지 다시 받기, 9.6절)과 그 뒤의 둘째 죽음은 2026-10-13 사용자 결정으로 범위에
넣었다. 둘째 죽음은 첫 복원이 끝나고 보호를 되찾은 뒤의 차례 실패라 단일 실패 범위 안이다.
- 노드 고장, 실제 link down과 flap, 재부팅, 드라이버 재적재.
- NVSHMEM, GIN 밖의 NCCL 통신(gin-restore 4절과 같음).

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드, NIC, GPU, CUDA | gin-restore와 같다: rain(Quadro RTX 5000), sunny(RTX A4000), ConnectX-6, CUDA 12.8 | gin-restore 5절(이 문서에서 다시 확인하지 않음) |
| 랭크 배치 | 랭크 4개, GPU마다 둘(rain에 0과 2, sunny에 1과 3). 짝은 p xor 1(`gdakiHoldBuddyOf` 4308)이라 rank 3의 짝은 rank 2. rank 3의 예비 프로세스는 sunny GPU의 셋째 프로세스. 둘째 죽음 셀은 rank 2의 예비 프로세스도 rain GPU의 셋째 프로세스로 띄움(rain BAR1에 세 프로세스가 드는지 `[미확인]`, pilot이 BAR1 Free를 봄) | 계획 |
| 라이브러리 | gin-restore `rs` + 9절의 mirror 계층(`mi`). 이 라이브러리와 쓰는 모든 프로그램은 이 계층의 헤더로 빌드 | 구현 전 |
| 자료 소켓의 처리량 | helper 소켓과 같은 관리망 주소의 TCP. 처리량은 `[미확인]`(pilot이 FETCH 시간으로 잼) | 계획 |

이 배치의 짝 규칙에서는 노드를 건너는 put의 mirror가 보내는 rank와 같은 노드의 짝으로 가고(NIC 루프백, 선 위의 바이트는 그대로), 같은 노드 안의 put의
mirror가 선을 건넌다 `[추론: 짝 규칙과 배치]`. 그래서 비용 셀은 재기만 하는 모드의 두 팔(9.7절 재기만 하는 모드 행)로 두 경우를 따로 잰다.

## 6. 변수

- **독립변수.** mirror 켬과 끔(`NCCL_GIN_RESTORE_MIRROR`), 덮어쓰기 workload 켬과 끔(`RS_OVERWRITE`), 장애(rank 3, rank 1 kill, 체크포인트 멈춤 중 kill, rank 2
  kill 뒤 rank 3 kill), put 크기(4 KiB, 32 KiB, 128 KiB), 체크포인트 간격(10, 20, 40단계), lane 크기와 당기기 문턱, checksum 방식(대조 셀).
- **종속변수.** gin-restore의 종속변수 전부(대기 결과, 데이터 비교, 단계 실행 수, 억제 수, 복원 단계별 시각, 입력 멈춤 시간)와 더해서: mirror 쓰기 수와
  바이트, lane마다 segment 채움, 살아 있는 segment 수, 당기기 수, lane 깨짐 수와 까닭, DISARM 수, 짝의 drain 시간과 QUERY_QP 수, FETCH의 segment 바이트와
  시간, 내보내기의 원본 바이트, put 지연과 묶음 대역, pool 바이트, BAR1 Used 앞뒤, 시행마다 QUERY_QP 증가.
- **통제변수.** gin-restore 6절의 hold 프로세스 고정 설정 전부. 더해서: `NCCL_GIN_RESTORE_MIRROR`는 모든 rank가 같음(다르면 9.7절의 Resume 거절 셀만),
  segment 자리 3(`NCCL_GIN_RESTORE_MIRROR_SLOTS`), lane 1 MiB(`NCCL_GIN_RESTORE_MIRROR_LANE`, pilot 자리값), 당기기 50%(`NCCL_GIN_RESTORE_MIRROR_PULL`),
  checksum 끔(대조 셀 밖), 시행마다 프로세스를 새로 띄움.

## 7. 실험 셀, 반복 수, 대조군

DRAFT다(반복 수는 초안, pilot 뒤 고정). 배치와 빌드는 5절, 단계 사이 5 000 µs, 복원 시한 20 000 ms는 gin-restore와 같다. 덮어쓰기 workload(`RS_OVERWRITE=1`,
9.8절)는 받는 rank마다 보내는 칸 하나를 단계마다 다시 쓰고 flush가 돌아온 바로 뒤 그 칸을 단계에 따라 다른 독 값으로 덮는다.

| 셀 | 조건 | 빌드와 반복 수(초안) | 종류 |
|---|---|---|---|
| `mi4_none_ow` | 장애 없음, 덮어쓰기, mirror 켬 | `@mi` 5 | 대조, pool 사용량 |
| `mi4_kill3_ow` | rank 3 SIGKILL(단계 중간), 덮어쓰기, mirror 켬, 예비 프로세스 있음 | `@mi` 10 | 새 셀 |
| `mi4_kill1_ow` | rank 1 kill(같은 GPU의 다른 rank) | `@mi` 5 | 일반성 |
| `mi4_kill3_ckpt_ow` | 체크포인트 입력 멈춤 중 kill(gin-restore의 라이브러리 시험 스위치) | `@mi` 5 | 새 셀 |
| `mi4_kill2_kill3_ow` | 덮어쓰기, mirror 켬, 단계 600. rank 2(rank 3의 짝)를 단계 200 근처에서 kill하고 되살린 뒤, rank 3을 단계 400 근처에서 kill(그 사이 간격 20단계로 열 번의 체크포인트 기회). 예비 프로세스 둘(rank 2와 rank 3) | `@mi` 5 | 새 셀(판정), 9.6절 |
| `mi4_kill3_ow_nomirror` | 덮어쓰기, mirror 끔, checksum 끔(gin-restore 방식) | `@mi` 5 | 음성 대조 |
| `mi4_kill3_ow_sampled` | 덮어쓰기, mirror 끔, checksum 표본 | `@mi` 5 | 음성 대조 |
| `mi4_seg_4k`, `mi4_seg_32k`, `mi4_seg_128k` | rank 3 kill, put 4 KiB(600단계), 32 KiB(200단계), 128 KiB(60단계; 받는 window가 rain BAR1의 window 한도 24 MiB 안), 확정 체크포인트 뒤 15단계째 kill | `@mi` 각 5 | 복원 시간 대 segment |
| `mi4_int_10`, `mi4_int_20`, `mi4_int_40` | 장애 없음, 간격 10, 20, 40단계 | `@mi` 각 3 | pool 대 간격 |
| `mi4_pull` | lane 48 KiB(간격 하나에 rank마다 80 KiB를 보냄), 당기기 50% | `@mi` 장애 없음 3 + rank 3 kill 5 | 당기기 |
| `mi4_overflow` | lane 2 KiB(put 4 KiB보다 작음), rank 3 kill | `@mi` 5 | DISARM 끝 수단 |
| `mi4_refuse_csum`, `mi4_refuse_mirror1` | mirror와 checksum 표본을 함께 켬; rank 하나만 mirror 끔 | `@mi` 각 3 | 명시적 오류 |
| gin-restore 회귀(mirror 끔) | gin-restore 7절의 복원, 거절, 회귀 셀 | `@mi` 그 실험의 n | 회귀 |
| gin-restore 회귀(mirror 켬) | `rs4_kill3`, `rs4_none`(덮어쓰지 않는 workload) | `@mi` 5 + 5 | 회귀 |
| 비용 가족 mirror | 지표 `lat4k`, `lat256k`, `bw256k`, 노드 둘; 팔 `off`(fail-fast), `on`(로그 켬), `mirror-self`, `mirror-peer`(재기만 하는 모드, 9.7절); gin-restore 9.15.6의 섞기 틀 | `@mip` 팔마다 6 | 비용 |
| fail-fast 기계어 | 매크로 없는 프로그램 넷과 라이브러리 장치 객체를 `rs`와 비교 | 빌드 검사 | 회귀 |

## 8. 제외 기준과 중단 기준

gin-restore 8절의 규칙을 그대로 쓰고 아래를 더한다(DRAFT).
- **제외(채점에서 빼고 채움).** gin-restore의 제외 전부. 더해서: kill이 모든 lane을 유효하게 만든 첫 확정 체크포인트 전(그때까지는 무장되지 않음); 셀이 정한
  workload 모드(`RS_OVERWRITE`)나 mirror 설정과 다르게 돈 시행; 둘째 죽음 셀에서 첫 kill이 위 제외에 걸린 시행(그 시행 전체). 둘째 kill이 다시 무장보다
  먼저 난 시행은 빼지 않고 조건 불충족으로 센다(3절). smoke와 pilot은 늘 제외.
- **중단(그 hold의 남은 시행을 멈추고 올림).** gin-restore의 STOP 규칙 전부(CUDA 메모리 오류, 새 mlx5 명령 오류, 남은 프로세스, NIC 오류, rain BAR1 Free
  128 MiB 미만이면 시작 안 함). 더해서: 어느 노드에서든 pool 등록이 실패함(모든 rank의 Resume 거절로 보임; 거절 셀 밖); 시행 시작 때 노드의 남은 호스트
  메모리가 (rank 수 × pool 바이트 + 1 GiB)보다 작음. rain QUERY_QP 증가 상한은 mirror 문맥 몫(9.7절 rain 행)을 더해 초안 50 000(복원 시행과 비용 실행)으로
  두고 pilot이 고정한다. 이름으로 끄지 않고 실행기가 기록한 PID만 끈다.

## 9. 설계와 실행 방법

### 9.1 설계 개요

```
 보내는 rank s (GPU)           받는 rank d (GPU)              d의 짝 b (호스트)                    d의 예비 프로세스
 put(d) 하나에 WQE 둘, 둘 다 d의 게이트 안에서:
  ├ (mirror 문맥, b) QP ── WRITE ─────────────────────────▶ pool[d] segment k, lane s
  └ (사용자 문맥 c, d) QP ── WRITE+신호 ─▶ window, 신호 표
 로그 항목(s의 GPU, 64 B): 종류, 대상, 크기, 신호, MIRROR 표시와 lane 안 자리     체크포인트 이미지(지금처럼, TCP)
 s가 flush나 wait로 put의 local 완료를 보면 mirror도 원본을 다 읽음 → application이 원본을 다시 써도 됨
 d의 입력 멈춤마다 s는 d의 segment를 바꿈. d의 체크포인트 K 확정 → segment K 이하를 버림

 d 죽음 → 생존 rank가 d를 붙잡음(지금처럼) → HOLDING(mirror 수, segment 채움)을 b에
          b: 모든 HOLDING 뒤 mirror QP drain과 READ 울타리 → ACTIVATE ──────────────────────▶ FETCH: 이미지 + K 뒤 segment
 생존 rank마다 STATE: 로그 항목(MIRROR 항목은 원본 바이트 없이 segment 번호) ───────────────▶ 가져오기: 내용은 segment에서,
                                                                                            신호와 억제 예산은 지금처럼
```

원칙 `[추론]`:
- 내용은 NIC이 쓴다. GPU 스레드는 복사하지 않는다(사용자 결정 5). 보내는 스레드가 더 하는 일은 lane 커서의 원자 더하기, mirror QP의 WQE 하나, 항목 낱말
  하나다.
- mirror는 받는 rank의 실행 수에 닿지 않는다. 다른 QP(mirror 문맥)로 가므로 d로 가는 사용자 QP의 메시지 수, 체크포인트의 절단점, 억제 예산이 그대로다
  (9.2절).
- mirror가 실패해도 보내기를 막거나 application에 오류를 주지 않는다. 그 lane을 깨짐으로 적고 helper가 d를 DISARM한다(로그 넘침과 같은 길).
- 복원 쪽 기계(붙잡기, REJOIN, 복원 라운드, 억제)는 gin-restore 그대로다. 바뀌는 것은 짝의 활성화 앞 drain, FETCH의 내용, 내보내기와 가져오기에서 내용의 출처다.

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
  재실행 중에 mirror를 내지 않는다. 그 멈춤은 예비 프로세스의 예산이 다 쓰인 뒤에만 온다(억제 예산이 남은 rank는 남의 멈춤에 BUSY, gin-restore 9.10.7절)
  `[소스: BUSY_SUPPRESS 4897]`.
- local 완료: application이 flush나 wait로 put의 완료를 보면 mirror WRITE도 원본을 다 읽었어야 한다. 공용 flush와 wait 코드는 mirror 문맥을 보지 않으므로(flush는
  그 문맥의 상대 QP만 돎) `[소스: rs 트리 gin_gdaki.h 1704–1791, 1196–1255]`, 매크로 빌드에서만 flush와 wait 끝에 mirror QP를 그때의 색인까지 기다리는 hold
  함수를 부른다. 이 기다림은 쉬지 않는다: 게이트가 닫혔거나 에폭이 바뀌었거나 오류 CQE면 그 짝이 맡은 lane을 깨짐으로 적고 돌아간다(application에는 오류
  없음). wait의 요청 구조체에는 표가 하나뿐이라 mirror의 색인은 wait 때 다시 읽는다(더 오래 기다릴 뿐 일찍 끝나지 않음).

### 9.3 pool: 자리, 크기, 등록, 버리기, 당기기

**자리.** 짝 b의 pool은 b가 맡은 rank(짝 규칙에서 보통 하나, 랭크 수가 홀수면 rank 0이 둘)마다 segment 자리 S개 × lane (n − 1)개 × lane 바이트 L이다. lane은
맡은 rank를 뺀 모든 보내는 rank의 몫이고 b 자신의 lane도 있다. segment k는 자리 k mod S를 쓴다.

**등록.** 호스트 메모리(쪽 정렬)를 b의 GIN 보호 영역(GIN QP와 신호 표의 PD)에 `ibv_reg_mr_iova2`로 0 기준(iova 0) 등록한다: 원격 주소가 pool 안 오프셋이
되어 예비 프로세스의 새 pool에서도 자리가 같고 rkey만 바뀐다. 권한은 local write, remote write, remote read(drain의 READ 울타리). relaxed ordering은 켜지
않는다(울타리가 앞의 posted 쓰기를 밀어내야 함). `gdakiRegMr`는 GPU 메모리용 dmabuf 길을 먼저 시도하므로 쓰지 않고 바로 부른다 `[소스: gdakiRegMr 2190–2200]`.
체크포인트 저장소와 같은 등록 영역에 둘 수 없다: 저장소는 등록하지 않은 호스트 벡터이고 올리기마다 새로 만든다 `[소스: gdakiCkptStore 5169–, 받기
8783–8838]`. 같은 PD에 따로 등록하고, 원격 쓰기 권한이 이미지에 닿지 않는 것도 이 분리의 까닭이다.

**보내는 rank가 알아야 하는 것.** 받는 rank d마다 짝 b = buddy(d)(순수 함수, 나눌 것 없음)의 pool rkey와 바이트, lane 배치(S, L, n). 설정 끝의 MIRROR_SETUP
기록으로 나눈다(9.2절). 되살린 rank의 새 pool은 예비 프로세스의 rkey 목록에 새 종류로 실어 생존 rank에 준다. 예비 프로세스가 생존 rank들의 pool을 아는 길은
STATE에 더한 그 생존 rank의 rkey 목록(pool 종류 포함, 9.4절 끝점 갱신)이다.

**측 표의 mirror 칸.** 머리의 빈 칸(40–63)에 mirror 켬, mirror 문맥 번호, mirror 칸 배열의 자리. 받는 rank마다 칸 하나(64 B): 유효, pool rkey, segment 번호,
그 segment에서 이 rank lane의 pool 안 시작, L, 커서(장치 원자 더하기), 깨짐 수(장치). 배열이 QP 항목과 고리 사이에 들어가므로 측 표 magic을 바꾼다(모든
프로그램은 이 계층의 헤더로 빌드) `[소스: 측 표 1176–1205]`.

**segment 바꾸기.** d의 입력 멈춤에서 각 보내는 rank s의 helper가(d로 가는 사용자 QP 게이트 홀수, 개수 0) d 칸의 커서를 NIC으로 읽어 segment k의 채움으로
호스트에 적고, segment k+1, 자리 (k+1) mod S의 lane 시작, 커서 0, 유효를 NIC으로 쓰고 다시 읽은 뒤 멈춤의 짝수 에폭을 게시한다(로그 켬 낱말과 같은 자리와
근거, gin-restore 9.11.9절 송신 쪽 로그 행) `[소스: PauseRead 10065–10115]`. 호스트는 (segment 번호, 그 절단점의 고리 위치, 채움)을 적어 둔다.

**버리기와 살아 있는 segment.** d의 CKPT_STABLE(K)를 받으면 s는 segment K 이하의 자리를 비운다 `[소스: OnStable 8232–8285]`. 살아 있는 segment는 K+1부터
지금 것까지라 보통 둘, 다음 멈춤이 앞 체크포인트의 확정보다 먼저 오면 셋이다. 넷째가 필요한 멈춤에는 s가 BUSY(새 까닭 "mirror segment가 참")로 답하고 d는
그 체크포인트를 건너뛴다 `[소스: BUSY 까닭 4895–4904]`. 버린 자리를 다시 쓸 때 옛 segment의 늦은 WRITE가 새 내용을 덮지 않는다: (s, b) 사이 mirror QP는
하나이고 RC는 차례대로 실행하므로 s의 옛 WRITE가 새 WRITE보다 먼저 실행되며, 투명 복구 라운드의 다시 보내기도 새 보내기보다 먼저다 `[추론]`. 체크포인트가
확정되지 못하고 버려져도(VOIDED) segment 경계는 남는다. 연달아 버려지면 BUSY가 이어지고 결국 lane이 넘쳐 DISARM으로 끝난다(안전하지만 보호를 잃음, 18절 후보).

**크기.** L ≥ 보내는 rank 하나가 간격 하나에 d로 보내는 바이트의 2배(gin-restore 로그 고리의 크기 규칙과 같은 꼴, pilot이 잼), 최소는 가장 큰 put 하나.
rank마다 pool = 맡은 rank 수 × S × (n − 1) × L. 시험 배치(맡은 rank 1, S 3, n 4, L 1 MiB 자리값)에서 9 MiB이고 시험 workload는 간격 하나에 lane마다 20 ×
4 KiB = 80 KiB를 쓴다 `[추론: 계산]`.

**당기기(동적 간격).** s의 helper가 10 ms마다(로그 고리 표본과 같은 걸음, `gdakiRsLogPoll` 10225) d 칸의 커서를 읽어 L의 문턱(기본 50%)을 넘으면 그 segment에
한 번 CKPT_PULL(d)를 보낸다. d의 helper가 이를 적고, d의 다음 `ncclGinRestoreStep`은 간격이 차지 않았어도 체크포인트를 찍는다(`gdakiCkptDue` 4989에 "당겨짐"을
더함). 체크포인트는 단계 사이에서만 찍히므로 단계 하나가 lane을 넘으면 당기기로 막을 수 없다. 짝이 되살아난 뒤 d의 칸이 무효인 동안(9.6절)은 커서가 움직이지
않으므로 당기기도 없다.

**끝 수단(DISARM).** 장치가 lane 넘침, 닫힌 mirror 게이트, 확인하지 못한 flush를 깨짐 수로 적으면 helper의 걸음이 d를 DISARM한다(그 깨짐 뒤 멈춤의 확정
체크포인트까지; `gdakiHoldDisarm` 6991–7010, 로그 넘침과 같은 길). 내보내기는 hold 시작에서 깨짐 수를 다시 읽어 절단점 뒤 깨짐이 있으면 거절한다(그 사이에
d가 죽어도 fallback).

### 9.4 복원 경로

1. **생존 rank s의 hold 시작**(`gdakiHoldStart` 6825–6917, 지금 그대로 d로 가는 QP를 멈추고 ERR로): 게이트 개수 0이면 d로 가는 put의 mirror가 모두 나갔다.
   s는 NIC으로 mirror QP (cm, b)의 msgs(M_mir), d 칸의 커서와 깨짐 수를 읽고, 앞 segment의 채움과 함께 HOLDING(d)에 실어 b에 보낸다(고정 크기 기록의 쓰지 않던
   칸) `[소스: HOLDING 송신 6903 근처, 기록 형식 rs_hold_api.h 47–59]`.
2. **짝 b의 drain**: 모든 생존 rank의 HOLDING이 모인 뒤(지금 규칙 `gdakiHoldHoldersComplete` 4770) b는 보내는 rank마다 자기 쪽 mirror 응답 QP의 누적 실행 수가
   M_mir 이상일 때까지 QUERY_QP로 기다린다(펌웨어 가드 밖, 체크포인트 drain의 한도 `NCCL_GIN_RESTORE_DRAIN_MS`와 QUERY_QP 수 한도). 자기 lane은 mirror 문맥의
   자기 루프 응답 QP를 묻는다 `[추론]`. 그다음 GIN 보호 영역의 루프백 QP 쌍으로 pool의 낱말 하나를 READ해 앞의 posted 쓰기가 호스트 메모리에 닿았음을
   확인한다(gin-restore 9.15.3절의 실행 가능성 시험이 GPU 메모리에서 확인한 READ 울타리와 같은 근거, 호스트 메모리에서는 아직 재지 않음 `[미확인]`) `[소스: AtomicOp 10502–10581]`. 깨짐이 있거나 drain이 한도를
   넘으면 지금의 fallback. 그다음 ACTIVATE(`gdakiHoldActivate` 7297)와 그 뒤의 끝점 표(아래 끝점 갱신 1).
3. **FETCH**: 예비 프로세스는 지금처럼 첫 자료 단계에서 이미지를 가져오고(`gdakiCkptSpareFetch` 9027–9153), 같은 연결에서 이미지 끝 기록 뒤에 mirror 단락을
   받는다: 머리(K 뒤 segment 수, (segment, lane)마다 채움), 바이트, 해시가 든 끝 기록(판 2). 모든 생존 rank의 STATE보다 먼저, 어느 생존 rank가 게시하기 전에
   예비 프로세스의 호스트 메모리에 들어온다. TCP를 쓰는 까닭: 예비 프로세스가 b와 이은 QP로 READ하면 Baseline 전에 b의 응답 쪽 실행 수가 바뀐다(gin-restore
   18절).
4. **STATE**(내보내기 판 2): 항목마다 항목을 보내고, MIRROR 항목은 원본 바이트 대신 segment 번호(8 B)를 보낸다. 생존 rank는 원본을 읽지 않는다. mirror가 켜진
   통로에 MIRROR 없는 내용 있는 put 항목이 절단점 뒤에 있으면 거절한다. 머리에 mirror QP의 X를 더하고, 내보내기 뒤에 이 생존 rank의 rkey 목록(pool 포함)을 붙인다(끝점 갱신 3) `[소스:
   gdakiRsLogExport 10760–10843, 머리 rs_log_api.h 219–231]`.
5. **가져오기**(`gdakiRsSpareImport` 10844–): 지금의 검사에 더해 MIRROR 항목마다 segment가 K 뒤이고 (segment, lane = 보낸 생존 rank, 자리 + 바이트)가 FETCH한
   채움 안인지 본다. 데이터는 지금처럼 CUDA 복사(생존 rank 차례, 위치 차례)이고 출처만 내보내기 바이트에서 FETCH한 segment로 바뀐다. 신호 더하기(루프백 쌍의
   NIC 원자 연산), 사용자 QP의 msgs = X와 예산 X − P, 응답 쪽 기준 M은 그대로. mirror QP는 msgs = X, 예산 0이고 응답 쪽 기준은 사용자 QP처럼 M이다(이 rank가
   뒤에 짝으로서 drain할 때 보내는 rank의 M_mir과 같은 셈으로 견주게; 둘째 죽음에서 쓰임). 생존 rank의 rkey 목록을 자기 rkey 표에 쓴다(끝점 갱신 3).
6. **재실행과 억제**: gin-restore 그대로다. "재실행이 pool 내용을 쓴다"는 것은 재실행 전에 넣는 입력(5)의 내용이 pool에서 온다는 뜻이다. 되살린 rank 자신이 다시
   내는 put은 체크포인트와 결정적 재실행으로 같은 내용을 만든다(gin-restore 9.7절).
7. **생존 rank의 복원 라운드**: d로 가는 모든 QP(mirror 문맥 포함; d가 짝인 rank의 mirror)를 지금처럼 예비 프로세스에 다시 잇고 옛 WQE는 실행된 것으로 친다
   (`U = S`). 예비 프로세스의 새 pool rkey를 측 표의 해당 칸에 NIC으로 쓰고(게이트 홀수 동안), 그 칸은 d가 맡은 rank의 다음 입력 멈춤까지 무효다. 호스트에
   적어 둔 그 rank의 segment 기록도 비운다(옛 pool과 함께 사라짐).
8. **RESTORED 뒤 전체 이미지 다시 받기**(2026-10-13 사용자 결정, 9.6절): d가 맡은 rank e(= d의 짝)는 RESTORED(d)를 적용할 때 자기 올리기 기반을 지워 다음
   올리기를 전체 이미지로 보내고, 그 체크포인트의 입력 멈춤에서 보내는 rank들이 e의 lane을 새 pool에 다시 켠다. 그 체크포인트가 확정되면 e는 다시 무장된다.

**복원 시간 어림** `[추론]`: gin-restore의 277.7–397.2 ms + drain(QUERY_QP 몇 번, ms 단위) + segment 바이트 / 자료 소켓 처리량. 처리량을 모르므로(5절) 기울기는
`mi4_seg_*`가 잰다. 128 KiB 셀의 가져오는 바이트는 lane 셋 × 15단계 × 128 KiB ≈ 5.6 MiB다.

**끝점 갱신: 앞서 되살린 rank를 생존 rank로 만날 때**(2026-10-13 사용자 결정 (가), 9.7절). 예비 프로세스는 생존 rank의 끝점(helper listen 주소, QPN,
rkey)을 자기 초기화 기록에서 안다 `[소스: 주소 9537–9539, 9622–9626; QPN 6372; rkey는 window 등록과 표 교환의 재생]`. 앞서 되살린 생존 rank(둘째 죽음 셀의
rank 2)는 셋이 모두 바뀌었으므로 세 곳에서 지금 값을 준다.
1. **주소와 화신: ACTIVATE 연결.** 짝은 ACTIVATE 기록(판 2) 바로 뒤 같은 연결에 표를 보낸다: 머리(magic, 개수) 다음 생존 rank마다 (rank, 화신, listen 주소
   32 B). 짝은 이 값을 이미 가진다: 설정 때 모든 상대의 `pe.addr`, 되살린 상대는 그 REJOIN을 받을 때 고친 값, 자기는 자기 listen 주소 `[소스: 5902; rs 트리
   gin_host_gdaki.cc 13659–13713]`. 예비 프로세스는 기록과 표를 모두 읽은 뒤(지금의 한 연결 500 ms 한도 안, 6301–6306) 답한다. 표가 없거나 깨졌으면
   REFUSED(끝 답, 짝은 바로 fallback). 활성화하면 기록 대신 표의 주소로 REJOIN을 건다(6388–6395). LATER 뒤 다시 묻는 연결마다 표가 다시 온다(rank마다 약 40 B).
2. **QPN: TOKEN.** 생존 rank의 TOKEN은 지금도 그 rank의 QPN을 GIN 문맥 차례로 싣는다. 예비 프로세스는 REJOIN_ACK가 알린 그 생존 rank의 화신(6425)이 0보다
   크면 TOKEN의 QPN을 기록과 견주지 않고(지금은 견줌, 6441) 그 QP의 `rq.exch.qpn`에 써서 잇는다. GID, LID, MTU는 같은 노드와 NIC이라 기록 그대로다 `[추론]`.
   생존 rank의 REJOIN 검사는 자기 화신이 0일 때만 "예비 프로세스가 아는 이 rank의 QPN"을 견주고, 0보다 크면 판, nonce, 화신, QP 수만 본다 `[소스: 검사
   3817–3840, 부름 5864]`. mirror 문맥 QP의 QPN은 화신과 상관없이 늘 TOKEN에서 오고 두 비교에서 빠진다: mirror QPN은 설정 끝 helper 소켓으로 나눠 기록에 없다
   (9.2절). 첫 초안의 9.7절 재생 행은 이 비교 제외를 적지 않았고, 여기서 함께 고친다.
3. **rkey: STATE.** 생존 rank는 STATE의 내보내기 뒤에 자기 rkey 목록(window 번호마다, 신호와 카운터 표, pool; 예비 프로세스가 생존 rank에 주는 목록과 같은 꼴,
   rs_spare_api.h 129–145)을 붙인다. 예비 프로세스는 가져오기 때(커널과 helper 전, application 스레드) 그 rank의 칸을 window rkey 표, 신호와 카운터 표의 rkey
   표(장치 표는 CUDA 복사, 호스트 사본도), 측 표 mirror 칸의 pool rkey에 쓴다. 그 전에는 예비 프로세스가 생존 rank로 아무것도 보내지 않으므로(커널이 아직 없음,
   신호 더하기는 자기 신호 표로 가는 루프백) 낡은 rkey가 쓰일 틈이 없다 `[추론]`.

**기록 재생 길에서 바꾸지 않는 것**(모든 생존 rank가 처음 화신인 복원, 곧 gin-restore의 모든 복원 셀이 지금처럼 되게):
- 초기화 재생과 Resume 모음의 재생은 그대로다: bootstrap과 GIN collComm의 대답, 자기 칸의 엄격 비교와 허용 칸, 설정 all-gather의 기록된 정책과 policyPad,
  salt와 nonce, RESET으로 만든 QP, 기록에서 세운 `gated`와 `addr` `[소스: 9537–9568, 9617–9626]`. 예비 프로세스는 초기화 중에 아무 끝점도 새로 배우지 않고, 위의
  세 갱신은 모두 활성화 뒤 handshake에서만 쓴다.
- 화신 0인 생존 rank에는 지금 검사가 모두 남는다: 표의 주소는 기록된 주소와 같아야 하고(다르면 REFUSED), REJOIN은 기록된 QPN을 싣고 그 생존 rank가 견주며,
  TOKEN의 QPN은 기록과 같아야 하고, STATE의 rkey 목록은 재생이 넣은 값과 같아야 한다(다르면 거절; 쓸 것은 없음). 그래서 처음 화신만 있는 복원은 지금과 같은
  결정을 내고 더해지는 것은 표 읽기와 목록 비교뿐이다.
- 기록 파일은 다시 쓰지 않고, 되살린 rank는 새 기록을 남기지 않는다. 같은 rank의 두 번째 복원(되살린 rank 2가 다시 죽음)은 이 실험에서 재지 않는다.

### 9.5 기존 부분이 어떻게 바뀌나

- **로그 고리.** 그대로 필요하다: 차례(위치), 대상, 신호, 억제의 메시지 단위는 항목에서 온다. 항목에 pool 자리가 들어간다: 표시 비트 0x20(여섯 표시 비트의
  마지막 빈 비트)을 MIRROR로, lane 안 자리(64 B 단위)를 8–11 바이트 낱말에 둔다. 이 낱말은 checksum 방식이 켜졌을 때만 checksum이다 `[소스: 항목과 표시
  1222–1246]`. segment 번호는 항목에 없고 내보낼 때 절단점의 고리 위치로 정한다(lane 자리와 고리 위치가 모두 같은 게이트 안에서 잡히므로 같은 멈춤이 둘을
  가른다) `[추론]`. 넘침과 DISARM 규칙은 그대로.
- **checksum.** mirror에서는 쓰지 않는다: 재실행이 원본을 읽지 않으므로 지킬 것이 없다. 코드 길은 그대로 두고(mirror 끈 대조 셀이 씀), 둘을 함께 켜면 Resume이
  이유와 함께 거절한다(같은 낱말을 쓰므로; 9.7절 Resume 조건).
- **"보낸 버퍼를 다시 쓰지 않음" 규칙.** mirror에서는 없앤다(gin-restore 9.7절 12번). 남는 것은 GIN의 원래 계약이고, 2026-10-13 사용자 결정으로 그 계약만
  요구한다(비용 없음): put의 원본은 그 put의 local 완료를 본 뒤에만 다시 쓴다. local 완료는 그 put을 낸 문맥의 flush, 또는 그 상대의 flushAsync와 wait가
  돌아온 것이다. 매크로 빌드의 이 둘은 mirror WRITE가 원본을 다 읽을 때까지 기다리므로(9.2절 완료 세기) 그 뒤 다시 써도 pool 내용이 맞다. 받는 쪽이 되보낸
  신호나 받는 쪽 데이터를 본 것 같은 원격 완료는 local 완료가 아니다: 본 put은 끝났어도 다른 QP의 mirror는 아직 원본을 읽지 않았을 수 있다. `ncclGinRestoreStep`의
  확정 단계 출력은 그대로 두되 mirror에서는 볼 필요가 없다.
- **application 요구(mirror를 켠 프로세스; gin-restore 9.7절 목록을 이렇게 고쳐 씀).** 1–11번과 13번은 그대로다(13번의 까닭은 이제 mirror의 lkey가 같은 GIN
  보호 영역이어야 한다는 것). 12번을 바꾼다: "12. put의 원본은 그 put을 낸 문맥의 flush나 그 상대의 flushAsync와 wait가 돌아온 뒤에만 다시 쓴다. 원격
  완료만 보고 다시 쓰지 않는다." 라이브러리는 이를 검사하지 않는다. 어기면 그 put의 pool 내용이 틀려 그 뒤 받는 rank의 복원이 조용히 틀릴 수 있다(18절).
  시험 workload는 flush가 돌아온 뒤에만 보내는 칸을 덮는다(7절).
- **rain의 BAR1과 레지스터.** pool은 호스트 메모리라 BAR1을 쓰지 않는다. 새 GPU 쪽 상태는 mirror 문맥의 QP n + 1개의 SQ(깊이 128 × 64 B)와 CQ, doorbell, 그
  문맥 몫의 신호와 카운터 표 줄, 측 표의 QP 항목 n × 128 B와 mirror 칸 n × 64 B로 KiB 단위다 `[추론; QP 깊이 rs 트리 gin_host_gdaki.cc 90]`. pilot이 BAR1
  Used를 앞뒤로 적는다. hold 함수가 커져 매크로 빌드 커널의 레지스터가 늘 수 있으므로 mirror 부분은 인라인하지 않는 따로 된 함수로 두고
  `cuobjdump -res-usage`를 `rs`와 견준다.
- **fail-fast 빌드.** mirror 쓰기, flush와 wait 끝의 mirror 기다림은 모두 `NCCL_GIN_RESTORE_DEVICE`로 빌드한 프로그램의 hold 길에만 있다. 매크로 없는
  프로그램과 NCCL 자신의 커널은 바이트까지 같아야 하고 gin-restore의 기계어 비교를 다시 한다. 호스트는 `NCCL_GIN_RESTORE_MIRROR`가 없으면 mirror 문맥, pool,
  새 기록을 만들지 않는다.

### 9.6 짝 보호 공백과 전체 이미지 다시 받기 (gin-restore 18절; 2026-10-13 사용자 결정으로 범위 안)

**공백.** gin-restore 본 실행에서 되살린 rank는 자기 체크포인트만 받았으므로 짝 rank의 증분 체크포인트를 "기반이 확정 이미지가 아님"으로 모두 거절했고 짝
rank의 남은 체크포인트 23–26개가 void였다 `[측정: gin-restore 16절, qa_recount.md 2번; 이 문서에서 다시 세지 않음]` `[소스: 기반 검사 5174–5185]`. rank b가
죽으면 b가 맡던 rank e(= b의 짝)의 체크포인트 이미지와 e의 pool lane이 모두 b의 프로세스와 함께 사라진다. 이 설계만으로는 공백이 체크포인트에서 pool까지
넓어진다 `[추론]`.

**지금 코드의 되돌림이 듣지 않은 까닭** `[소스, 추론]`. 올리는 쪽은 짝이 거절을 ack로 돌려주면 기반을 지워 다음 올리기를 전체로 보낸다(8738–8742). 그러나
짝은 머리를 거절하면 블록을 읽지 않고 ack를 보낸 뒤 닫으므로(8793–8832), 이미지가 소켓 버퍼보다 크면 올리는 쪽의 블록 보내기가 먼저 실패해 "ack 없음"
길(8734–8737)로 가고 기반이 남는다. 그래서 매번 같은 기반의 증분이 다시 거절된 것으로 읽힌다(qa_recount.md 2번의 거절 줄과 맞음; 올리는 쪽 줄은 다시 보지
않음).

**결정(2026-10-13, 사용자, 메인 세션이 전함).** 복원 뒤 되살린 rank가 자기가 맡은 rank에게 다음 올리기를 전체 이미지(`baseCkpt = ~0`)로 하게 하고(받는 코드는
이미 있음), lane을 다시 켜며, 둘째 죽음 셀을 판정 셀로 한다.

**차례**(b가 죽었다 되살아남, e = b가 맡은 rank):
1. **b의 hold 동안.** e의 체크포인트는 생존 rank의 BUSY(hold 중)로 건너뛰고, 진행 중이던 e의 올리기는 실패한다. 보내는 rank는 b의 복원 라운드에서 e의 칸을
   무효로 하고 e의 segment 기록을 비운다(9.4절 7번). 그때부터 e로 가는 put의 mirror는 나가지 않는다.
2. **요청.** 되살린 b의 RESTORED는 지금도 모든 생존 rank에 간다(gin-restore 9.3절 끝의 메모). e는 RESTORED를 적용할 때(`gdakiHoldApplyRestored` 7039–7083)
   보낸 rank가 자기 짝이면 올리기 기반을 지운다(`haveBase`, 8697–8708). 이것이 "되살린 rank가 전체 이미지를 청함"이고 새 기록 종류는 없다. 덧붙여 짝에게 한
   올리기가 OK ack 없이 끝나면(거절이든 ack 없음이든) 기반을 지운다. 위의 듣지 않던 길을 막고, 일시 실패 뒤에도 전체를 한 번 더 보내는 값을 치른다.
3. **붙잡기 상태 기계와의 맞물림.** e는 같은 RESTORED 적용에서 이미 자기를 다음 확정 체크포인트까지 DISARM한다(`gdakiHoldDisarmSelf`, 7082) `[소스]`. 그
   "다음 확정 체크포인트"가 이제 전체 이미지 체크포인트다. 되살린 b는 억제 예산이 남은 동안 e의 멈춤에 BUSY로 답하므로(gin-restore 9.10.7절) 전체 이미지
   체크포인트는 b의 억제가 끝난 뒤 e의 첫 성공한 멈춤이다. b 자신의 상태(ARMED(i+1) 또는 OFF)와 다른 생존 rank의 스스로 DISARM은 지금 규칙 그대로다. 새 붙잡기
   상태는 없다.
4. **lane 다시 켜기.** 그 체크포인트의 입력 멈춤에서 보내는 rank마다 e의 칸을 되살린 b의 새 pool(rkey 목록으로 받은 rkey)의 segment로 유효하게 쓴다(9.3절의
   segment 바꾸기와 같은 걸음). PAUSED의 무장 가능은 이 바꾸기 뒤에 본다. 되살린 b도 보내는 rank이므로 자기 lane(자기 루프)을 같은 멈춤에서 켠다.
5. **확정과 다시 무장.** 되살린 b가 전체 이미지를 OK로 받고, e가 CKPT_STABLE을 b에게 먼저 그다음 모두에게 보낸다(지금 차례). 모든 PAUSED가 무장 가능이고 e의
   예비 프로세스 등록이 이미지 머리에 있으면 e는 모든 rank에서 다시 ARMED다. 그 절단점 뒤 e로 들어온 내용은 모두 새 pool에 있으므로 그 뒤 e가 죽으면 9.4절대로
   되살린다.
6. **실패.** 전체 올리기가 거절되거나 실패하면 그 체크포인트는 void이고 다음 체크포인트가 다시 전체를 보낸다. 그동안 e는 DISARM이고 lane은 무효라 당기기도
   없다.

**비용과 남는 창** `[추론]`. 전체 이미지는 증분보다 커서 올리기가 길다(덮어쓰기 workload에서 받는 window만 약 7 MiB). 확정이 늦으면 다음 멈춤이 먼저 와
살아 있는 segment가 셋이 될 수 있다(9.3절의 늦은 확정). e가 보호받지 못하는 창은 b의 hold + b의 억제 + 체크포인트 간격 하나 + 전체 올리기 시간이다. 이 창
안에서 e가 죽는 것은 짝과 그 짝이 잇달아 죽는 것이라 범위 밖이고 fail-fast다.

**둘째 죽음.** 판정 셀 `mi4_kill2_kill3_ow`(3, 7절)가 위 차례와 그 뒤 e = rank 3의 복원을 잰다. 둘째 복원에서 예비 프로세스가 앞서 되살린 rank 2를 생존
rank로 만나는 일은 9.4절의 끝점 갱신이 다룬다(2026-10-13 사용자 결정).

### 9.7 기존 장치와의 충돌 표

열: 기존 장치 / 무엇이 부딪칠 수 있나 / 이 설계가 피하는 길 / 상태 / 근거(`[소스]`, rs_layer.diff 줄; "rs 트리"는 9절 머리의 트리).

| 기존 장치 | 무엇이 부딪칠 수 있나 | 이 설계가 피하는 길 | 상태 | 근거 |
|---|---|---|---|---|
| 붙잡기 상태 기계(HELD, COMMITTING, PUBLISHED)와 시한(차례마다 늘림, 장치 한도 D) | 짝의 drain과 커진 FETCH가 시간을 더함 | 새 상태 없음. drain은 HOLDING 모음과 ACTIVATE 사이의 helper 걸음(조각, 1 s 안)이고 FETCH는 첫 생존 rank의 자료 단계 안이라 지금의 시한 규칙이 덮음. 한도를 넘으면 지금의 fallback | 닫힘 | hold 상태 4187–4867, hold 기계 6593–7754(시작 6825, 활성화 7297, 감시 스레드 7683) |
| HOLDING 모음과 짝의 활성화 | HOLDING에 mirror 수와 채움을 실어야 함 | 고정 크기 기록의 쓰지 않던 칸에 실음. 짝은 지금처럼 모든 HOLDING 뒤에만 움직이고 그 사이 drain을 한 번 더 함 | 닫힘 | 모음 7121, 4758–4770; 기록 rs_hold_api.h 47–59 |
| 체크포인트 올리기와 FETCH(자료 소켓, serve 스레드 하나) | FETCH가 길어져 다른 연결을 늦춤; 형식이 바뀜 | 짝이 맡은 rank는 보통 하나이고 그 rank가 죽어 있어 기다릴 올리기가 없음. 형식은 이미지 끝 기록 뒤 mirror 단락(판 2) | 닫힘 | serve 8886–8900, 내주기 8839–8885, 받기 9027–9153, rs_ckpt_api.h 36–43 |
| 짝의 체크포인트 저장소 | pool을 같은 등록 영역에 둘 수 있나 | 둘 수 없음(등록 안 한 벡터, 올리기마다 새로 만듦). 같은 GIN PD에 따로 등록 | 닫힘 | 저장소 5169–, 받기 8783–8838 |
| 입력 멈춤, drain 확인, PAUSED의 무장 가능 | mirror QP를 멈춤에 넣으면 b의 체크포인트마다 d의 mirror가 막히거나 빠짐 | mirror 문맥을 멈춤, QP별 M과 P, drain에서 뺌. d의 멈춤에서 segment를 바꿈. 무장 가능에 "d 칸 유효, 깨짐 없음, b의 pool 정보 있음"을 더함. 넷째 segment면 BUSY(새 까닭) | 닫힘 | 멈춤 7932–7997, PAUSED 8109–8174, drain 8325–8371, PauseRead 10065–10115, BUSY 4895–4904 |
| 송신 쪽 로그 고리, 넘침, DISARM, 확정 단계 | 항목에 pool 자리를 둘 칸 | 표시 0x20과 8–11 바이트 낱말(checksum과 함께 켜지 않음), segment는 내보낼 때 절단점으로. lane 깨짐은 넘침과 같은 길로 DISARM. 확정 단계는 그대로 | 닫힘 | 항목 1222–1246, rsLogPut 575–620, LogPoll 10225–10260, Collect 10264–10313 |
| 억제 예산 X − P, 누적 실행 수(화신마다 mod 2^24), msgs | 같은 QP에 섞으면 예산이 mirror를 셈(9.2절 표) | mirror는 mirror QP의 msgs에만. 사용자 QP의 M, P, X 그대로. mirror QP는 예산 0, P 없음, 가져오기는 msgs = X. 예비 프로세스는 예산이 다 쓰일 때까지 mirror를 내지 않음 | 닫힘 | rsTakeBudget 521–534, 누적 10340–10398, 예산 쓰기 10443–10469, 가져오기 10844– |
| 복원 라운드(Prepare, 끝점 바꿈, Commit, Baseline, rkey 바꿈, 옛 WQE 모두 실행으로 게시) | mirror QP와 pool rkey | mirror QP는 rec QP라 라운드가 함께 다룸(옛 mirror WRITE는 죽은 짝의 pool과 함께 사라짐). 새 pool rkey는 rkey 목록의 새 종류로, 생존 rank가 게이트 홀수 동안 측 표에 NIC으로 씀, 장치는 게이트 뒤 시스템 범위로 읽음 | 닫힘 | 복원 라운드 7359–7413, rkey 칸 쓰기 6054–, 계획 10715–10759, rs_spare_api.h 129–154 |
| 살아 있는 상대와의 투명 복구 라운드(실행 안 된 WQE 다시 보내기) | mirror QP 장애 때 다시 보내기가 원본을 다시 읽음 | 다시 보내기는 새 보내기보다 먼저(같은 QP 차례). application이 이미 원본을 다시 썼을 수 있는 경우는 flush가 확인하지 못한 경우뿐이고 그때 lane은 깨짐 | 닫힘 | 게시 hook 6529–6547 |
| 장치 게이트(홀수 에폭, 개수, 쉬기, 포기) | d의 게이트를 쥔 채 b의 게이트에서 쉬면 b의 hold 동안 d로의 보내기와 d의 멈춤이 멈춤 | mirror 게이트는 쉬지 않는 한 번 들어가기(열려 있지 않으면 깨짐, mirror 없이 계속). 남는 결합: mirror QP의 SQ가 차면 DOCA의 자리 기다림(깊이 128) | 닫힘(비용은 7절) | rsPutHold 627–717; 게이트 rs 트리 gin_gdaki.h 303–336 |
| 장치 flush, flushAsync, wait(공용 코드, hk 그대로) | application의 flush가 mirror를 기다리지 않으면 다시 쓴 원본을 mirror가 읽음 | 매크로 빌드만 flush와 wait 끝에 mirror QP를 그때의 색인까지 기다림(쉬지 않음, 실패는 깨짐, application에 오류 없음). 공용 코드는 그대로 | 닫힘 | rs 트리 gin_gdaki.h 1704–1791, 1196–1255, 1601– |
| 원격 완료만 보고 원본을 다시 쓰는 application | 되보낸 신호를 보고 다시 쓰면 mirror가 아직 안 읽었을 수 있음 | 2026-10-13 사용자 결정 (가): 원본은 그 put의 local 완료(flush, 또는 flushAsync와 wait) 뒤에만 다시 씀. GIN의 원래 계약이라 비용 없음. 9.5절의 application 요구 12번을 그렇게 고쳐 씀. 검사하지 않음(18절) | 닫힘(결정) | 9.5절 |
| 장치 오류 분류와 sticky 오류 | mirror QP의 오류가 application 문맥의 sticky나 flush 실패가 됨 | mirror 길은 mirror 문맥 번호로 보고(그 sticky는 application이 읽지 않음), 실패를 돌려주지 않음. 기록은 helper로 가서 짝과 라운드 | 닫힘 | rs 트리 gin_gdaki.h 1504–1510(sticky 문맥마다), 2047 |
| strict window 강제와 window 보고 | pool MR이 RO로 등록되거나 window로 세어짐 | pool은 `RegMrSym`을 거치지 않고 RO 없이 등록, window 보고(16/16)에 들지 않음 | 닫힘 | 2190–2200, 2621, 11513–11549, 보고 4118– |
| 측 표 포인터의 게시(Resume 성공 때 한 번) | mirror 칸이 게시 뒤 바뀜 | 머리의 mirror 켬, 문맥 번호, 칸 배열 자리는 게시 전에 씀. 칸의 유효와 segment는 그 뒤 멈춤에서만 NIC으로 | 닫힘 | 9693–9812, 게시 9954–9997, rsSideOf 507 |
| Resume 합의(지역 판정 1–33과 bootstrap 모음) | 새 조건 | 34 mirror를 청했으나 설정 합의가 mirror를 껐음, 35 pool 등록 실패, 36 checksum과 함께 켬, 37 lane 바이트가 0이거나 64의 배수가 아니거나 pool이 한도(초안: 노드 호스트 메모리의 4분의 1)를 넘음, 38 짝들의 pool 정보가 오지 않음. 모음: mirror 비트가 rank 사이에서 다름. 모두 이유와 함께 모든 rank 같은 오류 | 닫힘(조건 추가) | 지역 판정 2780–2838, 결정 2915– |
| 설정 all-gather와 rank 사이 대칭 전제 | mirror 문맥을 allToAll로 만들면 변수가 다른 rank 사이에서 멈춤 | mirror QP는 만들기만, 정보는 합의 뒤 helper 소켓(9.2절). policyPad의 mirror 비트. 합의가 mirror를 끄면 mirror QP를 쓰지 않음으로 표시(감시와 라운드에서 빠짐) | 닫힘 | 9495–9677, rs 트리 16682–16693 |
| 설정 때의 응답 쪽 MSN 기준(모든 rec QP를 all-gather 전에 QUERY_QP) | mirror QP는 그때 아직 RESET | mirror QP는 그 읽기에서 빼고 이은 바로 뒤(helper 전) 기준을 잡음. 예비 프로세스는 지금처럼 REJOIN 뒤 | 닫힘 | 9518–9530 |
| GIN 보호 영역의 루프백 QP 쌍(신호 가져오기의 원자 연산) | 짝의 drain 울타리 READ를 같은 쌍으로 | 쌍의 사용자는 예비 프로세스의 가져오기(helper 전 application 스레드)와 짝의 drain(helper)으로 같은 프로세스에서 겹치지 않음 | 닫힘 | 10502–10581, 10582–10703 |
| NIC 복사 경로(루프백 PD, 원본 window의 두 번째 등록) | 원본 읽기 | MIRROR 항목은 원본을 읽지 않음. 등록은 그대로(mirror 끈 셀이 씀) | 닫힘 | 내보내기 10760–10843 |
| 예비 프로세스의 초기화 재생과 기록 | 기록에 없는 mirror QPN과 pool | mirror 쪽은 집합 교환이 없어 기록이 그대로. 예비 프로세스는 생존 rank의 mirror QPN을 TOKEN에서 받고 REJOIN과 TOKEN의 QPN 비교에서 mirror QP를 뺌, pool은 STATE의 rkey 목록에서 받음(9.4절 끝점 갱신). 자기 칸 허용 바이트는 늘리지 않음 | 닫힘 | rs_spike.cc 1599–2072, 9553–9568 |
| REJOIN, TOKEN, READY의 QPN 목록과 rkey 목록 | mirror QP가 상대마다 QP 수를 하나 늘림 | 상대마다 QP 수 n문맥 + 1 ≤ 64. rkey 목록에 pool 종류 | 닫힘 | 5644–6497, rs_spare_api.h 50–80 |
| gpu-detect의 QP 감시와 죽음 판정 | mirror QP가 감시 대상과 QUERY_QP를 늘림 | rec QP라 감시됨. b가 죽으면 다른 QP와 함께 붙잡힘 | 닫힘 | 감시 hook 5481–5490 |
| rain의 BAR1과 QUERY_QP 상한 | 새 메모리, 명령 수 | pool은 호스트. GPU 쪽은 KiB 단위. 감시 QUERY_QP가 4문맥에서 5문맥으로 약 25% 늘고 drain이 몇 번 더함. 상한을 다시 정함(8절) | 닫힘(pilot이 잼) | gin-restore 8절 |
| helper 기록 종류와 미룸 규칙 | 새 종류 | 48 MIRROR_SETUP(설정 끝, helper 전), 49 CKPT_PULL. 11–63은 지금의 미룸 규칙이 덮음 | 닫힘 | rs_hold_api.h 39–43, 67–75 |
| 재기만 하는 모드(`NCCL_GIN_RESTORE_LOG_MEASURE`) | Resume 없이 mirror를 재야 함 | MIRROR_SETUP은 이 모드에도 있음. 새 변수 `NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR`(값 0, self, peer)로 칸을 처음부터 유효로 두고 helper가 간격마다 커서를 0으로. 2 rank 비용 driver에서는 짝이 보내는 rank 자신이라 self(자기 pool, 루프백)와 peer(받는 rank의 pool, 선 위 두 배) 두 팔 | 닫힘 | 2142–2147, 9732–9806, 9836–9858 |
| checksum(`NCCL_GIN_RESTORE_CHECKSUM`) | 같은 항목 낱말 | mirror와 함께 켜면 Resume 거절(조건 36). 코드 그대로 | 닫힘(가정; 2026-10-13 사용자가 그대로 둠) | 1222–1246, 3341 |
| fail-fast의 기계어 동일성 | 장치 코드 변경 | mirror와 flush, wait 끝의 기다림은 매크로 안. 다시 비교 | 닫힘(검사) | gin-restore 9.9절 끝의 메모 |
| 회귀 셀(gin-remaining, gpu-detect, gin-restore) | mirror가 꺼진 길의 차이 | mirror 끔: 문맥, pool, 기록 없음. 매크로 빌드 hold 길은 측 표 머리의 mirror 켬 읽기 하나가 더해짐(비용 다시 잼) | 닫힘 | 7절 회귀 행 |
| 정리(abort, destroy)와 pool 해제 | 다른 rank의 늦은 mirror 쓰기 | QP를 없앤 뒤 MR 해제, 그 뒤 메모리 해제 | 닫힘 | 2551–2557, 7744– |
| mirror 문맥 하나를 모든 사용자 문맥이 나눔 | 사용자 문맥의 공유 모드(EXCLUSIVE, CTA)로는 낼 수 없음 | GPU 범위 공유 모드로 냄. 사용자 문맥마다 mirror 문맥을 두는 길은 QP가 두 배(고를 길) | 닫힘(가정; 2026-10-13 사용자가 그대로 둠) | rs 트리 gin_gdaki.h 1804–1815 |
| 보내는 rank가 곧 짝(자기 lane) | 자기 루프 QP는 rec 밖이라 감시, 라운드, 게이트가 없음 | 자기 루프로 냄(hk의 자기 put과 같음). drain은 그 응답 QP의 QUERY_QP | 닫힘 `[추론]` | rs 트리 16697–16756 |
| 복원 뒤 짝 보호 공백 | 되살린 짝이 맡은 rank의 이미지와 pool이 없음, 확정이 없어 segment가 안 버려짐 | 2026-10-13 사용자 결정 (가): 범위 안. 맡은 rank가 RESTORED(짝)를 적용할 때 올리기 기반을 지워 다음 올리기가 전체 이미지, 그 멈춤에서 lane을 새 pool에 다시 켜고, 확정되면 다시 무장(9.6절 차례 1–6). 둘째 죽음 셀이 판정 | 닫힘(결정) | 받는 쪽 `full` 길 5183–5195, 올리는 쪽 기반 8697–8708 |
| RESTORED 적용과 스스로 DISARM(붙잡기 상태 기계) | 전체 이미지 요청과 다시 무장이 상태 전이와 엇갈림 | 새 상태와 새 기록 없음. 기반 지우기는 RESTORED 적용(지금의 상태 검사를 지난 뒤)에 붙이고, 다시 무장은 지금의 "다음 확정 체크포인트" 규칙을 그대로 씀. 되살린 짝의 억제가 끝나기 전 멈춤은 지금처럼 BUSY로 건너뜀 | 닫힘 | 적용 7039–7083(스스로 DISARM 7082), BUSY 4897 |
| 올리기 실패 뒤의 기반(올리는 쪽) | 짝이 거절한 머리 뒤 닫으면 큰 이미지의 올리기는 "ack 없음"으로 끝나 기반이 남음(9.6절) | OK ack 없이 끝난 모든 올리기 뒤에 기반을 지움. 일시 실패 뒤에도 전체를 한 번 더 보내는 값(올리기 시간) | 닫힘 | 8734–8742, 받는 쪽 8793–8832 |
| 앞서 되살린 rank를 생존 rank로 만나는 예비 프로세스(둘째 죽음 셀이 처음 부딪침) | 예비 프로세스는 생존 rank의 listen 주소와 QPN, rkey를 자기 초기화 기록에서 가짐. rank 2가 되살아난 뒤 rank 3이 죽으면 옛 rank 2의 주소로 걸고, 옛 QPN이 되살린 rank 2의 검사에 거절되며, 옛 rkey로 보냄 `[소스, 추론]` | 2026-10-13 사용자 결정 (가): ACTIVATE 연결의 (주소, 화신) 표, 화신이 0보다 큰 생존 rank는 TOKEN의 QPN으로 잇고 REJOIN 검사는 화신 0일 때만 QPN을 견줌, STATE의 rkey 목록을 가져오기 때 씀(9.4절 끝점 갱신). 기록 재생 길과 처음 화신의 검사는 그대로 | 닫힘(결정) | 주소 9537–9539, 9622–9626, 거는 곳 6388–6395, QPN 6372, 6425, 6441, 검사 3817–3840, 5864 |

**닫은 충돌(2026-10-13 사용자 결정, 메인 세션이 전함).**
1. **원격 완료만 보고 원본을 다시 쓰는 application → (가).** 원본은 그 put의 local 완료(flush, 또는 flushAsync와 wait) 뒤에만 다시 쓴다. GIN의 원래 계약이고
   비용이 없다. 9.5절의 규칙과 application 요구 12번, 4절의 제외로 적었다. 라이브러리는 검사하지 않는다(18절).
2. **복원 뒤 짝 보호 공백 → (가) 범위 안.** 되살린 rank가 맡은 rank의 다음 올리기를 전체 이미지로 하게 하고(RESTORED 적용에서 기반을 지움; 받는 코드는 이미
   있음), 그 멈춤에서 lane을 다시 켜며, 확정되면 다시 무장한다(9.4절 8번, 9.6절). 둘째 죽음 셀 `mi4_kill2_kill3_ow`가 판정 셀이다(3, 7절).
3. **앞서 되살린 rank를 생존 rank로 만나는 예비 프로세스(둘째 결정이 연 충돌) → (가).** 지금 끝점을 세 곳에서 준다: ACTIVATE 연결의 (listen 주소, 화신) 표,
   TOKEN의 QPN(REJOIN 검사는 생존 rank의 화신이 0일 때만 QPN을 견줌), STATE의 rkey 목록(가져오기 때 씀). 9.4절의 끝점 갱신과 "기록 재생 길에서 바꾸지 않는 것"에
   적었다. 이 반영에서 찾아 고친 것 둘(새 충돌 아님): mirror QP의 QPN을 처음 화신의 REJOIN과 TOKEN 비교에서 빼야 한다는 것(첫 초안이 빠뜨림), 가져오기에서
   mirror QP의 응답 쪽 기준도 M으로 둔다는 것(둘째 죽음의 drain이 씀).

이 문서의 가정(mirror 문맥 하나를 GPU 범위 공유 모드로, mirror와 checksum을 함께 켜면 Resume 거절, segment는 TCP FETCH, 재기만 하는 모드의 self와 peer 팔, 초안 값
lane 1 MiB, 당기기 50%, QUERY_QP 상한 50 000, 4 KiB 문턱 +0.5 µs)은 같은 날 사용자가 가정대로 두었다.

**열린 충돌 없음**(2026-10-13, 셋째 반영 뒤). 남은 것은 충돌 표의 독립 검토와 9.8절 1번의 실행 가능성 확인이다.

### 9.8 구현 계획과 실행 방법 (구현 전)

열린 충돌은 없다(9.7절 끝). 충돌 표의 독립 검토를 마친 뒤에만 한다. 차례(초안):
1. 실행 가능성 확인 셋(채점 안 함): 호스트 pool의 drain 뒤 READ 울타리가 CPU에서 본 값과 맞는지, mirror QP를 설정 합의 뒤 helper 소켓으로 잇고 감시가 도는지,
   mirror를 기다리는 flush의 지연.
2. 장치: 측 표 mirror 칸, `rsPutHold`의 mirror 함수, flush와 wait 끝의 mirror 기다림(모두 매크로 안). 호스트: mirror 문맥 만들기, MIRROR_SETUP, pool 등록, 멈춤의
   segment 바꾸기, 당기기, HOLDING과 drain, FETCH 판 2, 내보내기와 가져오기 판 2, rkey 목록의 pool 종류, Resume 조건 34–38. 전체 이미지 다시 받기(9.6절):
   RESTORED 적용의 기반 지우기, OK ack 없는 올리기 뒤 기반 지우기, 복원 라운드의 칸 무효와 segment 기록 비우기, 다시 켠 lane과 다시 무장의 줄. 끝점 갱신(9.4절):
   ACTIVATE 판 2와 주소 표, TOKEN의 QPN으로 잇기와 화신 0일 때만의 QPN 검사(mirror QP는 늘 빼기), STATE의 생존 rank rkey 목록과 가져오기의 쓰기와 비교.
3. 시험: [gin_rs.cu](../restore/impl/test/gin_rs.cu)에 `RS_OVERWRITE=1`(받는 rank마다 보내는 칸 하나, flush 뒤 그 칸을 단계에 따른 독 값으로 덮음; 받는 칸은 지금처럼
   단일 대입), 비용 driver에 mirror 팔, 셀 파일, 채점기의 새 열(내보내기 원본 바이트, pool 바이트, 당기기, 깨짐, RESTORED 뒤 void 수, 전체 올리기와 다시
   무장의 시각). 둘째 죽음 셀의 실행기: 예비 프로세스 둘, kill 둘(기록한 PID로만).
4. 빌드, CPU 단위 시험, 기계어 비교, 독립 검토, pilot, 사전 등록, 본 실행.

- **배포/빌드:** 정하지 않음(gin-restore의 `impl/build_rs.sh` 꼴로 새 디렉터리 하나).
- **실행:** `harness/gpu-initiated/common/cluster_run.sh` 안에서 메인 세션이 한다.
- **채점:** 3절 예측의 표 파일과 채점기(사전 등록 때 만듦).
- **출력:** `results/<날짜>_<이름>/`, 원자료는 Release.

## 10. 완료 조건과 QA 기준

- [ ] 모든 셀이 계획한 n만큼 실행됐다(제외와 실패를 따로 센 표 포함).
- [ ] 예측마다 판정(맞음/틀림/자료 없음)과 놓친 시행 목록이 있다.
- [ ] 핵심 수치를 원자료에서 다시 계산했다: 덮어쓰기 셀의 데이터 비교, 내보내기의 원본 바이트 0과 pool 바이트 합, 억제 수, 복원 시간과 segment 바이트, 비용
  중앙값.
- [ ] 다른 에이전트가 채점기를 보지 않고 원자료에서 kill 셀, 대조 셀, 둘째 죽음 셀의 판정을 다시 셌다(둘째 죽음 셀은 전체 올리기, 다시 무장, 둘째 kill의
  차례를 줄의 시각으로 확인).
- [ ] 매크로 없는 프로그램의 기계어가 `rs`와 같음을 다시 확인했다.
- [ ] gin-restore 회귀 예측을 그 실험의 판정식 그대로 다시 채점했다.
- [ ] smoke, pilot, 제외 시행이 결과에 섞이지 않았다. 여러 실행의 범위와 대표 실행의 범위를 섞지 않았다.
- [ ] 원자료를 Release에 올리고 DATA.md에 적었다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀, 설계, 충돌 표 초안 (`DRAFT`, 2026-10-13)
- [x] 열린 충돌 둘의 사용자 결정과 이 문서의 가정 확인(2026-10-13, 12절)
- [x] 둘째 결정이 연 충돌(앞서 되살린 rank를 만나는 예비 프로세스)의 사용자 결정(2026-10-13, 12절)
- [ ] 충돌 표의 독립 검토(막는 문제가 남으면 구현하지 않음)
- [ ] 실행 가능성 확인 셋(9.8절 1번, 채점 안 함)
- [ ] 계층 구현, 빌드, CPU 단위 시험, 기계어 비교, 독립 코드 검토
- [ ] 시험 workload의 덮어쓰기 모드와 비용 팔, 셀 파일, 채점기
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
- 체크포인트가 연달아 버려지면 segment가 버려지지 않아 BUSY와 DISARM으로 끝난다(9.3절).
- 이 testbed의 짝 규칙에서는 노드를 건너는 put의 mirror가 선을 건너지 않는다(5절). 셋 이상 노드의 비용은 재기만 하는 모드의 peer 팔로 대신 잰다.
- 호스트 메모리의 drain 울타리는 gin-restore가 GPU 메모리에서 한 것처럼 재지 않았다 `[미확인]`.

## 19. 다음 작업

- 충돌 표의 독립 검토, 9.8절 1번의 실행 가능성 확인(열린 충돌 없음).

## 20. 참고자료

- [../restore/EXPERIMENT.md](../restore/EXPERIMENT.md) 9.2–9.11절(설계와 상호작용 표), 15절(결과), 18–19절(한계와 다음 작업)
- [../restore/impl/rs_log_api.h](../restore/impl/rs_log_api.h), [rs_ckpt_api.h](../restore/impl/rs_ckpt_api.h),
  [rs_hold_api.h](../restore/impl/rs_hold_api.h), [rs_spare_api.h](../restore/impl/rs_spare_api.h)
- [../restore/results/20261013_main/](../restore/results/20261013_main/)(SCORE.md, trials_scored.csv, qa_recount.md)
