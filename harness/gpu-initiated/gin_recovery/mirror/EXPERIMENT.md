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
| 마지막 갱신 | 2026-10-15, 다섯 갈래의 병렬 구현과 통합: `exp/gin-mirror-int`에서 하나의 계층([impl/mi_layer.diff](impl/mi_layer.diff), md5 `e27998db`)으로 합침, 빌드됨(연구 `1b50d11b`, 운영 `a34db6e6`), CPU 단위 시험함(넷, 0 failed), 매크로 없는 장치 코드가 hk와 i5에 SASS와 자원까지 같음, 시험 드라이버를 통합 헤더로 다시 빌드, 독립 리뷰 둘 반영(12절). pilot 전([impl/test/PILOT_MI.md](impl/test/PILOT_MI.md)). 그 전: 2026-10-13, 공유 인터페이스(impl/의 헤더 여섯, [impl/PARALLEL.md](impl/PARALLEL.md), build_mi.sh 뼈대)와 실행 가능성 확인 1, 3, 4의 결과(9.8절, `[측정]`; 9.3, 9.4, 9.5절의 수치). 그 전(같은 날): 재검토가 연 충돌 → (가) INJECTED(9.4절), 올리기 꼴 확인; 재검토의 고칠 것 여섯; RDMA 저장소, 단계 맞춤 가져오기, 첫 검토, 결정 여덟; 학습 모양; 초안. 라이브러리 구현과 빌드 없음 |

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
| 복원 시간은 gin-restore의 복원 시간 + 짝의 drain + 가져오는 바이트 / RDMA READ 처리량이다 | segment가 클수록 FETCH 시간이 줄거나, FETCH 시간이 바이트 / θ와 ±30% 넘게 다르거나, 어느 셀에서 복원이 2 000 ms를 넘는다 |
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
| FETCH 시간이 segment 바이트와 함께 늚 | `mi4_seg_4k`, `mi4_seg_32k`, `mi4_seg_128k` | 셀마다 FETCH 시간(줄), 가져온 바이트, drain 시간, 전체 복원 시간 | FETCH 시간(첫 READ를 낸 때부터 마지막 완료까지)의 중앙값이 바이트 순서대로 늘고 각 시행이 a + 바이트 / θ의 ±30% 안(절편 a와 θ는 9.8절 확인 3: rank 3 kill 배치에서 a 0.005 ms, θ 11.88 GB/s `[측정]`; 작은 F에서는 READ 지연이 a에 들어감); 전체 복원은 모두 ≤ 2 000 ms(RDMA에서 FETCH는 수 ms라 전체 시간의 기울기는 잡음에 묻힘 `[추론]`) | 9.4절 시간 어림 | `seg_restore_slope` |
| pool 메모리는 간격에 비례 | `mi4_int_10`, `_20`, `_40` | lane마다 segment 최대 채움 | 간격이 두 배일 때 채움의 비 2 ± 25%; pool 바이트는 보고 | 9.3절 | `pool_vs_interval` |
| 당기기가 넘침을 막음 | `mi4_pull` | 20단계마다 당기기 ≥ 1, DISARM 0; kill 시행은 위 대기와 데이터 조건 | 장애 없음 3/3, kill ≥ 4/5 | 9.3절 | `pull_no_disarm` |
| 넘치면 DISARM하고 fail-fast | `mi4_overflow` | lane 깨짐 줄과 DISARM 줄, hold 시작 줄 없음, 대기가 죽음 판정 + 2 000–2 500 ms에 오류로 풀림 | ≥ 4/5 | 9.3절 끝 수단 | `overflow_failfast` |
| 장애 없음: 데이터 같음, 복원 0, 멈춤이 짧음 | `mi4_none_ow` | 데이터 같음, 복원 0, 입력 멈춤 ≤ 10 ms(멈춤 안 D2H 포함), segment 다시 시작 0 | 5/5 | gin-restore `none_clean` | `ow_none_clean` |
| 켤 수 없는 mirror 설정은 모든 rank가 같은 이유의 오류 | `mi4_refuse_csum`, `mi4_refuse_mirror1` | 모든 rank의 Resume 오류, 이유 문자열이 같음 | 셀마다 3/3 | 9.7절 Resume 조건 | `refuse_mirror` |
| 짝이 되살아난 뒤 맡은 rank가 보호를 되찾음 | `mi4_kill2_kill3_ow` | rank 2의 복원이 `mi4_kill3_ow`의 대기와 억제 조건을 채우고, RESTORED(2) 뒤 rank 3이 처음 멈춤에 성공한 체크포인트의 올리기가 전체 이미지(RDMA 저장소는 늘 전체; mirror 끔 길은 `baseCkpt = ~0`)이며 되살린 rank 2에서 확정됨, 그 사이 확정되지 못하고 버려진 rank 3의 체크포인트 ≤ 1, 둘째 kill 전에 모든 생존 rank에서 rank 3이 다시 무장되고 보내는 rank마다 rank 3의 lane이 다시 켜짐 | ≥ 4/5 | 9.6절 | `reimage_after_restore` |
| 그다음 맡은 rank의 죽음도 되살림(둘째 죽음) | `mi4_kill2_kill3_ow` | 두 죽음 모두 생존 rank의 대기 붙잡힘과 비동기 오류 0, 생존 rank의 단계 실행 수 모두 1, 복원마다 ≤ 2 000 ms, 끝에 모든 rank의 데이터가 기준과 같음, 둘째 복원의 이미지와 segment가 되살린 rank 2에서 옴. 다시 무장되기 전에 둘째 kill이 나면 조건 불충족으로 셈(제외 아님) | ≥ 4/5 | 9.4절(끝점 갱신), 9.6절 | `second_death_restored` |
| 회귀(mirror 끔) | gin-restore 7절의 복원, 거절, 회귀 셀 `@mi` | 그 실험의 원래 판정식 | 원래 기준 | 9.7절 회귀 행 | `regression_restore_off` |
| 회귀(mirror 켬, 덮어쓰지 않는 workload) | `rs4_kill3`, `rs4_none` `@mi`, mirror 켬 | 같은 판정식 | 원래 기준 | 같음 | `regression_restore_on` |
| mirror의 4 KiB 지연 | 비용 가족 mirror, 지표 `lat4k`, 노드 둘 | 팔 `mirror-self`, `mirror-peer` 대 `on`(로그 켬)의 중앙값 차이 | 노드마다 +2.5 µs 안. 어림: hold 길은 서로 기다리는 L2 왕복 3–4번에 1.0–1.5 µs였고(gin-restore 15, 18절) mirror가 4–5번(칸 읽기, 커서, 게이트, rkey, SQ 자리)을 더해 +1.2–2.0 µs `[추론]`. 사용자의 첫 예상(수백 ns)과 앞 초안 +0.5 µs는 이 어림과 어긋나 고침(검토) | 9.2절 | `cost_mirror_lat4k` |
| mirror의 256 KiB, 2 MiB 지연 | 같은 가족 `lat256k`, `lat2m` | 같은 차이 | 보고만. 어림: peer 팔은 put 하나의 직렬 시간까지 늚(2 MiB에서 off 팔 대역 5.5–6.4로 0.33–0.38 ms `[추론]`) | 9.2, 9.8절 | `cost_mirror_lat` |
| mirror의 묶음 대역 | 같은 가족 `bw256k`, `bw2m` | peer 팔의 `mirror-peer` / `on` | 노드마다 0.40–0.60(보내는 쪽이 GPU 읽기와 선을 모두 두 번 씀). self 팔의 비는 보고(GPU 읽기만 두 번) | 9.2절 | `cost_mirror_bw` |
| 매크로 없는 프로그램은 그대로 | fail-fast 기계어 비교 | 매크로 없는 프로그램 넷의 SASS 전체와 자원, 라이브러리 장치 객체가 `rs`와 같음 | 같음 | 9.5절 | `ff_identical` |

두 비용 팔은 실제 비용을 위아래로 묶는다: self 팔은 mirror QP의 게이트와 선이 없고(자기 루프), peer 팔은 받는 노드까지 두 배를 받는다. 실제 셋 이상 노드의 비용은 그
사이다 `[추론]`.

**학습 모양 셀의 예측(초안).** gin-restore가 할 수 없던 예측은 첫 줄이다: 보낸 버퍼를 단계마다 다시 쓰고 받는 칸을 고리로 다시 쓰는 전송에서 복원한 데이터가 맞음.

| 무엇을 예측했나 | 셀 | 시행마다의 조건 | 판정식(초안) | 근거 | 찾는 키 |
|---|---|---|---|---|---|
| 덮어쓰는 학습 모양 전송에서 최종 데이터가 기준과 같음 | `mi4_train_kill3` | 모든 rank의 상태 이력 x(0..2 000)와 마지막 받은 칸, 신호 값이 호스트 기준과 비트 단위로 같음; 생존 rank의 대기 붙잡힘, 재실행 없음, 억제 정확 | ≥ 9/10 | 9.4절 | `train_data_equal` |
| 단계 맞춤 가져오기가 단계마다 한 번 | `mi4_train_kill3` | 예비 프로세스가 단계 K+1부터 마지막 표시 단계까지 각 단계의 입력을 그 커널 전에 한 번씩 넣었고(라이브러리 줄), 끝에 남은 입력 0, INJECTED가 마지막 넣은 단계 뒤 한 번이고 생존 rank의 쉬던 put은 그 뒤에 나감(생존 rank 줄) | ≥ 9/10 | 9.4절 | `train_paced_import` |
| 복원 시간의 부분 | `mi4_train_kill3` | FETCH 시간(첫 READ를 낸 때부터 마지막 완료까지)이 a + F / θ의 ±30% 안(F = 이미지 + K 뒤 segment 바이트, a와 θ는 실행 가능성 확인 3: 0.005 ms, 11.88 GB/s `[측정]`), 전체 T ≤ 1 000 ms(gin-restore 중앙값 375.6 ms + drain + FETCH) | ≥ 9/10 | 9.4절 어림 | `train_restore_parts` |
| segment 자리 | `mi4_train_none`, `mi4_train_kill3` | 넷째 자리가 필요해 다시 시작한 멈춤(9.3절 (나)) 수, 셋째 자리를 쓴 멈춤 수, 짝마다 살아 있는 바이트의 최고 | 다시 시작 0; 셋째 자리와 최고 바이트는 보고 | 9.3, 9.8절 | `train_segments` |
| 당기기와 DISARM | `mi4_train_none`, `mi4_train_kill3` | lane 깨짐, DISARM, 당기기 수 | 깨짐 0, DISARM 0; 당기기는 보고(L이 간격 둘이라 0에 가까움 `[추론]`) | 9.3절 | `train_pull_count` |
| 장애 없는 학습 모양 | `mi4_train_none` | 데이터 같음, 복원 0, 입력 멈춤 ≤ 15 ms(멈춤 약 5 ms + 멈춤 안 D2H 2.4 ms `[측정: 확인 3]` + 여유) | 5/5 | 9.4, 9.8절 | `train_none_clean` |
| 체크포인트는 RDMA로 | 학습 셀 모두와 mirror 켠 4 KiB 셀 | helper 소켓으로 보낸 이미지와 segment 바이트 0; 체크포인트마다 올리기 시간은 보고 | 모든 시행 | 9.4절 | `store_rdma` |
| 학습 모양에서 둘째 죽음 | `mi4_train_kill2_kill3` | `reimage_after_restore`와 `second_death_restored`의 조건을 학습 모양에서 | ≥ 4/5 | 9.4, 9.6절 | `train_second_death` |

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
| `mi4_train_kill3` | 학습 모양, rank 3 SIGKILL을 단계 300–1 700 사이의 무작위 단계와 단계 안 지연에(seed는 사전 등록 때 고정) | `@mi` 10 | 새 셀(핵심) |
| `mi4_train_kill2_kill3` | 학습 모양, rank 2 kill(단계 300–900 무작위) 뒤 되살리고, rank 3 kill(단계 1 100–1 700 무작위, 다시 무장 뒤). 예비 프로세스 둘 | `@mi` 5 | 새 셀(둘째 죽음) |
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
| 비용 가족 mirror | 지표 `lat4k`, `lat256k`, `bw256k`, `lat2m`(2 MiB put), `bw2m`(2 MiB × 8 묶음, window 16 MiB), 노드 둘; 팔 `off`(fail-fast), `on`(로그 켬), `mirror-self`, `mirror-peer`(재기만 하는 모드, 9.7절); gin-restore 9.15.6의 섞기 틀 | `@mip` 팔마다 6 | 비용 |
| fail-fast 기계어 | 매크로 없는 프로그램 넷과 라이브러리 장치 객체를 `rs`와 비교 | 빌드 검사 | 회귀 |

4 KiB 셀(`mi4_*_ow`, 대조, 회귀)은 gin-restore와 같은 크기의 회귀로 그대로 둔다. mirror를 켠 셀은 단계 맞춤 가져오기와 RDMA 저장소를 지나고, mirror를 끈 셀과
gin-restore 회귀는 지금의 한꺼번에 가져오기와 TCP 저장소를 지난다(9.4절). 둘째 죽음 셀의 둘째 kill은 driver의 단계 kill(`GIN_RS_DIE_AT`)로 하고 체크포인트 멈춤
중 kill 시험 스위치는 쓰지 않는다: 그 스위치는 확정 무장 체크포인트를 누적으로 세어(7914) 복원 뒤 다시 무장하기 전에 터진다(검토).

## 8. 제외 기준과 중단 기준

gin-restore 8절의 규칙을 그대로 쓰고 아래를 더한다(DRAFT).
- **제외(채점에서 빼고 채움).** gin-restore의 제외 전부. 더해서: kill이 모든 lane을 유효하게 만든 첫 확정 체크포인트 전(그때까지는 무장되지 않음); 셀이 정한
  workload 모드(`RS_OVERWRITE`)나 mirror 설정과 다르게 돈 시행; 둘째 죽음 셀에서 첫 kill이 위 제외에 걸린 시행(그 시행 전체). 둘째 kill이 다시 무장보다
  먼저 난 시행은 빼지 않고 조건 불충족으로 센다(3절). smoke와 pilot은 늘 제외.
- **중단(그 hold의 남은 시행을 멈추고 올림).** gin-restore의 STOP 규칙 전부(CUDA 메모리 오류, 새 mlx5 명령 오류, 남은 프로세스, NIC 오류, rain BAR1 Free
  128 MiB 미만이면 시작 안 함). 더해서: 어느 노드에서든 pool 등록이 실패함(모든 rank의 Resume 거절로 보임; 거절 셀 밖); 시행 시작 때 노드의 남은 호스트
  메모리가 (rank 수 × pool 바이트 + 1 GiB)보다 작음. rain QUERY_QP 증가 상한은 mirror 문맥 몫(9.7절 rain 행)을 더해 초안 50 000(복원 시행과 비용 실행)으로
  두고 pilot이 고정한다. 이름으로 끄지 않고 실행기가 기록한 PID만 끈다.
- **학습 모양 셀(초안).** 시행 하나의 시간 한도는 60 s 대신 120 s(9.8절의 어림 24–28 s). hold를 둘로 나눈다(9.8절). QP 감시 50 ms라 rain QUERY_QP는 시행마다 약
  16 000번으로 상한 50 000 안이다 `[추론]`. 시작 검사의 남은 호스트 메모리는 (pool + 저장소를 가진 프로세스 수) × 약 0.8 GiB + 1 GiB로 본다.

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

**결정으로 닫은 충돌**(모두 2026-10-13, 메인 세션이 전함): (1) 원격 완료 → local 완료 규칙(9.5절); (2) 복원 뒤 짝 보호 공백 → 범위 안(9.6절); (3) 앞서 되살린 rank의
낡은 끝점 → 활성화 덩어리, TOKEN QPN, STATE rkey(9.4절); (4) 받는 쪽 단일 대입과 rain BAR1 → 단계 맞춤 가져오기, 2 MiB 그대로(9.4절); (5) rain QUERY_QP 상한 → 학습
셀만 QP 감시 50 ms(무장 조건은 켜져 있음뿐이라 바꿀 것 없음; gin-restore 6절의 "10 ms"는 그 실험의 설정 값); (6) TCP 처리량 → RDMA 저장소와 READ(9.4절); (7) 버려진
멈춤과 체크포인트 → 되돌리기와 다시 시작(9.3절); (8) mirror QP 장애 기록 → 흡수, 짝을 거절하지 않음(9.5절); (9) 단계 맞춤 가져오기 대 게이트에서 쉰 생존 rank의
put → 게이트를 INJECTED까지 홀수, PUBLISHED의 끝과 시한이 바뀜(9.4절).

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

**열린 충돌 없음**(2026-10-13, 아홉째 결정 뒤). 다음은 9.8절의 실행 가능성 확인 넷과 공유 인터페이스 작성, 그 뒤 작업 묶음의 병렬 구현이다.

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

**학습 모양 모드(`RS_TRAIN=1`; 셀은 7절).**
- 전송: 단계마다 rank마다 상대 셋에 2 MiB put과 신호 1(단계 짝에 따른 신호 둘), rank마다 단계당 6 MiB, 2 000단계, 단계 사이 5 000 µs. 상대별 flush가 돌아온 바로 뒤
  보내는 칸을 단계에 따른 독 값으로 덮고 다음 단계가 진짜 값을 쓴다(결정 1의 규칙). 원본을 다시 읽는 재실행이면 독 값이 들어가 비교에서 틀린다.
- window와 rain BAR1(256 MiB, window 하나 24 MiB 이하, gin-restore 9.15.6): 보내는 window 6 MiB(상대마다 칸 하나), 받는 고리 R = 4로 24 MiB, rank마다 30 MiB. rain은
  두 rank 60 MiB, 둘째 죽음 셀은 rank 2의 예비 프로세스가 더해 90 MiB(NIC 복사 경로 등록을 건너뛸 때) `[추론: 계산]`. 단계 맞춤 가져오기는 R ≥ 3이면 되므로 맞는다.
- pool: 식은 짝마다 잡는 크기 = S × (n − 1) × L, 살아 있는 내용 ≤ (1–2) × (n − 1) × B × I(WRITE가 부하에서도 멈춤 뒤 약 20–25 ms에 끝나 확정이 곧 옴 `[측정: 확인 3]`). B = 2 MiB, I = 20, L = 2 × B × I =
  80 MiB, S = 3이면 잡는 크기 720 MiB, 살아 있는 내용은 많아야 2 × 3 × 40 MiB = 240 MiB이고, 당기기 문턱 50%(40 MiB)는 간격 하나와 같아 확정이 늦을 때만 당긴다.
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

## 19. 다음 작업

- pilot: 배포 묶음 `RS_SET=mi1`(통합 빌드 i2와 통합 헤더의 드라이버), hold P1, P2, P3과 비용 pilot([impl/test/PILOT_MI.md](impl/test/PILOT_MI.md)의 명령과 먼저 볼 것). 실행 가능성 확인 2(손으로 하는 mirror 비용)는 같은 `gin_ts2_mi`로.
- pilot 뒤 문턱, seed, n 고정과 사전 등록(`prereg/gin-mirror-v1`).

## 20. 참고자료

- [../restore/EXPERIMENT.md](../restore/EXPERIMENT.md) 9.2–9.11절(설계와 상호작용 표), 15절(결과), 18–19절(한계와 다음 작업)
- [../restore/impl/rs_log_api.h](../restore/impl/rs_log_api.h), [rs_ckpt_api.h](../restore/impl/rs_ckpt_api.h),
  [rs_hold_api.h](../restore/impl/rs_hold_api.h), [rs_spare_api.h](../restore/impl/rs_spare_api.h)
- [../restore/results/20261013_main/](../restore/results/20261013_main/)(SCORE.md, trials_scored.csv, qa_recount.md)
