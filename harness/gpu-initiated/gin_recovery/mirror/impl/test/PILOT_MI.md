# gin-mirror pilot 준비 (test 갈래)

이 문서는 pilot이 셀마다 무엇을 보여야 하는지와 pilot이 고정하는 문턱, 반복 수를 미리 적는다. pilot은 모든 셀을 작은
n으로 돌려(hold `P1` 4 KiB 셀과 거절, `P2` 학습 모양, `P3` 회귀, 그리고 비용은 `COSTPILOT-<노드>`) 2, 3, 7, 8절의 초안 값을 정하고 그 뒤 사전 등록한다. 지금은
DRAFT다. 실행은 메인 세션이 `../../../../common/cluster_run.sh` 안에서 한다.

표시: `[측정]` 원자료에서 확인, `[미확인]` 아직 확인하지 않음, `[추론]` 해석.

## 상태 (2026-10-15, pilot 4 뒤; set `mi5` 준비)

- 다음 묶음 set `mi5`(빌드 ln3, 2026-10-15 저녁): ln2에 구현 독립 리뷰(세션 스크래치 `lineage/IMPL_REVIEW.md`)와 pilot 4의 고침을 더함. 남긴 당기기의
  상한이 간격의 4분의 1에서 절반으로(pilot 4에서 죽은 rank의 짝이 맡은 rank가 "the checkpoint store is not ready"로 3–4번 거절되어 상한과의 여유가 한 번인
  시행이 둘; [../../EXPERIMENT.md](../../EXPERIMENT.md) 9.3절), 폴링 흡수는 바로 다음 segment에서만, 계보의 helper 밖 읽기 검사를 thread_local로,
  `pulls_taken`이 남긴 당기기에 합쳐진 새 당기기를 셈. 호스트만 바뀜: 계층 diff md5 `3e559c866f7a480ed2ac7ce017f8b3f8`(9 085줄; 장치 파일 둘의 diff는
  i4와 같음), 연구 `F/out/mi_ln3/libnccl.so.2.32.3` md5 `e927457a4986a8314ce911259beff51c`, 운영 `F/out/mip_ln3/libnccl.so.2.32.3` md5
  `58d7ff3f47d89205661a65b90a419298`; 드라이버(설치 헤더 digest `65fdf19b`; `MITREE=agent_mi_fix MIOUT=mi_ln3 COSTOUT=cost_ln3 MROUT=mr_ln3
  build_mi_test.sh mi nomacro cost mr`) `mi_ln3/gin_mi` `0d0dd90b4ad740905ce49a9f76043080`, `mi_ln3/gin_mi_nomacro` `9fcc9ab4ddab6367c259cc62ef2e5d11`,
  `cost_ln3/gin_ts2_mi` `7e3a2ef6ca4a771e29b39acc7d58d4a1`, `mr_ln3/ff/gin_mr` `00adb957eb65e38b183918817b435fd8`, `mr_ln3/hold/gin_mr`
  `d914df6def6cce8590e69a953a49d222`. pilot 5는 새 pilot hold P6(`mi4_pull` n 5, `mi4_kill3_ow` n 1, `mi4_train_kill3` n 1; `cells_mi.json`)다.
- pilot 4(set `mi4`, 빌드 ln2, 17:52–18:05)를 돌렸다: 모든 시행 `lineage_warn` 0, `mi4_pull` n 5의 `lane_broken_other` 0([../../EXPERIMENT.md](../../EXPERIMENT.md)
  12절). pilot 3(set `mi3`, 빌드 i4, 16:00–16:14)은 결함 E를 찾았다(같은 곳).
- set `mi4`(빌드 ln2, 2026-10-15): 계보(lineage, [../../EXPERIMENT.md](../../EXPERIMENT.md) 9.9절)와 pilot 3의 결함 E 고침(9.3절 "당겨진
  체크포인트가 찍히지 않을 때"). 호스트만 바뀜: 계층 diff md5 `23e5407b427fde5fb5b0d2f1d3c74e2d`(9 071줄; 장치 파일 둘의 diff는 i4와 같음), 연구
  `F/out/mi_ln2/libnccl.so.2.32.3` md5 `dac86bed7dc86afc5386d06f56f3d9e1`, 운영 `F/out/mip_ln2/libnccl.so.2.32.3` md5 `2bb1a973de4c0210093f85c7fb3106b3`;
  드라이버(설치 헤더 digest `65fdf19b`, i4와 같음; `MITREE=agent_mi_fix MIOUT=mi_ln2 COSTOUT=cost_ln2 MROUT=mr_ln2 build_mi_test.sh mi nomacro cost mr`)
  `mi_ln2/gin_mi` `0603ac4dc0c8d67a6470726dd2e85489`, `mi_ln2/gin_mi_nomacro` `dfa85845ce22fb14dec63fe33b22f4d7`, `cost_ln2/gin_ts2_mi`
  `faaac703c02f88acbb9152f2783e2524`, `mr_ln2/ff/gin_mr` `e4b4fc3f24486c9c372f3044acc982d2`, `mr_ln2/hold/gin_mr` `70ab3f3a771c6895862834b84a18c4eb`.
  계보만의 빌드 ln1(`e9c2c0e9`, `d8e7152c`)은 배포하지 않는다. pilot 4는 새 pilot hold P4(mirror 셀, `mi4_pull` n 5)와 P5(회귀)다(`cells_mi.json`).
  모든 시행에서 `rows_mi.py`의 새 열 `lineage_warn`(`GIN/LN` 줄 수)이 0이어야 한다.

- pilot 1(set `mi1`, 통합 빌드 i2, 08:59–09:15)과 pilot 2(set `mi2`, 고친 빌드 i3, 14:28–14:42)를 돌렸다. 결과와 결함 넷(A–D),
  고침, pilot 2의 확인은 [../../EXPERIMENT.md](../../EXPERIMENT.md) 12절이다. pilot 2가 결함 A, C, D의 고침을 확인했다 `[측정]`.
- 라이브러리(set `mi2`): 고친 계층 [../mi_layer.diff](../mi_layer.diff)(md5 `dfaddae8`, 8 279줄). 트리는 세션 스크래치의
  `agent_mi_fix/`(아래 `F`; `agent_mi_int/`의 복사, 갈래 `exp/gin-mirror-fix`). 빌드됨(sm_75, sm_86): 연구
  `F/out/mi_i3/libnccl.so.2.32.3` md5 `feefaf6d2623b9047903017850283695`, 운영 `F/out/mip_i3/libnccl.so.2.32.3` md5
  `2e4008e6d433832dd68bccf5e42735f0`.
- 드라이버(set `mi2`): 고친 헤더(설치 헤더 digest `f6b39af0`)로 `MITREE=agent_mi_fix MIOUT=mi_i3 build_mi_test.sh mi nomacro cost mr`,
  `F/test/out/`: `mi_i3/gin_mi` `7e522afd84f9546baa60091981616715`, `mi_i3/gin_mi_nomacro` `e84d9168eb736491c708b735a9e96578`,
  `cost/gin_ts2_mi` `ad0908442a8b687c242ba806a6f54069`, `mr/ff/gin_mr` `0b26cf49f4be1c57b220d88786613b45`, `mr/hold/gin_mr`
  `0bfac5da7ce90cd652320ef3dea5876e`. 링크는 동적이고 드라이버는 같은 트리의 라이브러리와만 짝을 이룬다(결함 D의 고침이 side table의
  머리 낱말과 칸을 바꿨다).
- 다음 묶음 set `mi3`(빌드 i4, 2026-10-15; 고침 묶음 리뷰의 사전 등록 전 항목: 첫 깨짐 진단, 죽은 프로세스의 늦은 STORE_REQ에 답 없음, side table magic
  "RSS5"; EXPERIMENT.md 12절의 i4 행): 계층 diff md5 `4dd2927a`(8 303줄), 연구 `F/out/mi_i4/libnccl.so.2.32.3` md5
  `c89ce744312b1af057c85f6eac975baf`, 운영 `F/out/mip_i4/libnccl.so.2.32.3` md5 `12a0edeca10b491458a86471e9903e53`; 드라이버(설치 헤더 digest
  `65fdf19b`, `MITREE=agent_mi_fix MIOUT=mi_i4 COSTOUT=cost_i4 MROUT=mr_i4 build_mi_test.sh mi nomacro cost mr`) `mi_i4/gin_mi`
  `5887dfeacdde2ed96de0de9105e6eb88`, `mi_i4/gin_mi_nomacro` `5cd7246b79c7da5913e001dd1e88e4af`, `cost_i4/gin_ts2_mi`
  `05093a694d01979b638121555dbdf637`, `mr_i4/ff/gin_mr` `2b18db83fb5c7e46333868a85523ddde`, `mr_i4/hold/gin_mr` `6debbb6db79ead05d040afc22726493a`.
  i3 드라이버와 섞지 않는다(헤더가 다름; 배포의 md5 검사가 막음). 학습 hold(P2, T1, T2)는 시행마다 시작 문에서 rain BAR1을 읽는다(읽기만).
- set `mi1`(pilot 1)의 i2 라이브러리와 드라이버(`agent_mi_int/`: `1b50d11b`, `a34db6e6`, `gin_mi` `a1b84951`, `gin_ts2_mi`
  `149cb366`)는 결함 A, C, D가 있어 다시 쓰지 않는다.
- 셀마다의 빌드: 복원, 거절, 회귀 셀(P1, P2, P3, G1–G3, T1, T2, R1–R3)은 모두 연구 빌드 `lib/mi`(`cells_mi.json`의
  `build: mi`)다. 그래서 `GIN_TS_NOTE` 줄("checkpoint stored", "lane ... broken", "CKPT_PULL", "INJECTED ...")이 WARN으로
  보인다. 비용 셀(COSTPILOT, COST-mirror)은 운영 빌드 `lib/mip`이고, 채점이 읽는 "mirror summary"(두 빌드 모두 WARN)와 측정 팔
  줄만 쓴다.
- 비용 팔: `NCCL_GIN_RESTORE_MIRROR=1`이 필요하다(mirror 문맥과 설정 합의가 그것으로 켜짐; 실행기가 준다). lane은 실행기
  기본 256 MiB, S 2(pool 512 MiB/프로세스): 라이브러리가 helper 걸음(약 1 ms)마다 L/2를 넘은 커서를 0으로 되돌리고 L보다 큰
  put은 깨짐으로 센다. 팔은 rank 0의 "mirror summary"가 broken=0이고 max_live_bytes > 0일 때만 유효하다.
- 자체 시험: `selftest_mi.py` 통과(2026-10-15, 채점 셈 고침 뒤) `[측정]`.

## 메인 세션 명령 (배포, 자체 시험, pilot, 본 실행)

변수: `T`는 이 폴더(`mirror/impl/test`)의 절대 경로, `R`은 결과 폴더, `SUNNY_SSH`는 관리망 설정 파일에서(저장소에 적지
않음), `F`는 고친 트리(세션 스크래치의 `agent_mi_fix`), `RS_SET`은 새 배포 묶음 이름(`mi1`, `mi2`는 썼음; gin-mirror는 빈 값,
gin-restore 묶음, 있는 이름을 거절한다).

배포(`deploy_mi.sh`, 메인 세션만)가 하는 일: 고른 산출물마다(그 `WANT_*`를 준 것만) 원본이 있고 md5가 `WANT_*`와 같은지 먼저
보고, 하나라도 다르면 아무것도 쓰지 않고 거절한다. 대상 디렉터리(`~/rs-bundle/<RS_SET>/lib/mi`, `lib/mip`, `mitest`, `mr/ff`,
`mr/hold`)가 어느 노드에든 있거나 그 묶음이 gin-restore 묶음이면 거절한다. rain에 복사하고(라이브러리는 `.so.2`, `.so` 링크)
sunny로 rsync한 뒤, 검사 파일에 두 노드의 새 파일 md5, 원본 = 배포본, ldd, 기존 묶음 파일의 앞뒤 md5(새 디렉터리 빼고)를 적는다.
`MITREE`가 드라이버를 가져올 트리(`$SCR/$MITREE/test/out`), `MIOUT`이 `gin_mi`, `gin_mi_nomacro`의 하위 폴더다. 반드시 이 갈래
(`exp/gin-mirror-fix`)의 스크립트로 한다(`MITREE`는 이 갈래에만 있음).

```
# 0. 드라이버는 빌드됨(위 md5; 다시 빌드할 일은 없음)
# 1. 배포 (set mi2로 한 명령; 새 묶음은 RS_SET만 새 이름으로)
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad; F=$SCR/agent_mi_fix
RS_SET=mi2 MITREE=agent_mi_fix MIOUT=mi_i3 \
  MI_LIB_SRC=$F/out/mi_i3/libnccl.so.2.32.3 MIP_LIB_SRC=$F/out/mip_i3/libnccl.so.2.32.3 \
  WANT_MI=feefaf6d2623b9047903017850283695 WANT_MIP=2e4008e6d433832dd68bccf5e42735f0 \
  WANT_GINMI=7e522afd84f9546baa60091981616715 WANT_GINMI_NOMACRO=e84d9168eb736491c708b735a9e96578 \
  WANT_COST_MI=ad0908442a8b687c242ba806a6f54069 WANT_MR_FF=0b26cf49f4be1c57b220d88786613b45 \
  WANT_MR_HOLD=0bfac5da7ce90cd652320ef3dea5876e bash $T/deploy_mi.sh $F/deploy_check_mi2.txt
grep -E "MISMATCH|CHANGED|not found" $F/deploy_check_mi2.txt     # 아무 줄도 없어야 함
# 2. 자체 시험 (CPU, 클러스터 없음)
python3 $T/selftest_mi.py
# 3. pilot (cluster_run.sh 안에서, 새 결과 폴더; pilot은 채점하지 않음)
RS_SET=mi2 bash $T/chain_mi.sh $R/<날짜>_pilot2 P1 P2 P3 COSTPILOT-rain COSTPILOT-sunny
python3 $T/rows_mi.py $R/<날짜>_pilot2 --out <다른 곳>/trials.csv   # 열을 읽기만(판정 아님)
# 4. pilot 뒤 7절 n, 3절 문턱, cells_mi.json, predictions_mi.csv 고정 -> 사전 등록(커밋 하나, 태그 prereg/gin-mirror-v1)
# 5. 본 실행 (hold를 나눠; 8절; RS_SET은 사전 등록 때 정한 묶음)
RS_SET=<묶음> bash $T/chain_mi.sh $R/<날짜> G1 G3 T1 T2 G2 R1 R2 R3 \
  COST-mirror-rain-lat4k COST-mirror-rain-lat256k COST-mirror-rain-bw256k COST-mirror-rain-lat2m COST-mirror-rain-bw2m \
  COST-mirror-sunny-lat4k COST-mirror-sunny-lat256k COST-mirror-sunny-bw256k COST-mirror-sunny-lat2m COST-mirror-sunny-bw2m \
  G1 G3 T1 T2 G2 R1 R2 R3
# (마지막 줄의 hold들은 시간 한도로 빠진 시행을 잇기 위함; 모두 돌았으면 "already done"으로 지나감)
# 6. 채점
python3 $T/score.py $R/<날짜>
```

pilot 1(set `mi1`)의 배포는 같은 명령에서 `MITREE`를 빼고(기본 `agent_mi_int`) `MIOUT=mi1`, i2의 원본과 md5를 준 것이었다.

다음 묶음 set `mi4`(빌드 ln2: 계보와 결함 E 고침)의 배포와 pilot 4(같은 꼴; 2026-10-15):

```
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad; F=$SCR/agent_mi_fix
RS_SET=mi4 MITREE=agent_mi_fix MIOUT=mi_ln2 COSTOUT=cost_ln2 MROUT=mr_ln2 \
  MI_LIB_SRC=$F/out/mi_ln2/libnccl.so.2.32.3 MIP_LIB_SRC=$F/out/mip_ln2/libnccl.so.2.32.3 \
  WANT_MI=dac86bed7dc86afc5386d06f56f3d9e1 WANT_MIP=2bb1a973de4c0210093f85c7fb3106b3 \
  WANT_GINMI=0603ac4dc0c8d67a6470726dd2e85489 WANT_GINMI_NOMACRO=dfa85845ce22fb14dec63fe33b22f4d7 \
  WANT_COST_MI=faaac703c02f88acbb9152f2783e2524 WANT_MR_FF=e4b4fc3f24486c9c372f3044acc982d2 \
  WANT_MR_HOLD=70ab3f3a771c6895862834b84a18c4eb bash $T/deploy_mi.sh $F/deploy_check_mi4.txt
grep -E "MISMATCH|CHANGED|not found" $F/deploy_check_mi4.txt     # 아무 줄도 없어야 함
RS_SET=mi4 bash $T/chain_mi.sh $R/<날짜>_pilot4 P4 P5   # cluster_run.sh 안에서; 비용 pilot은 필요하면 COSTPILOT-rain COSTPILOT-sunny를 더함
python3 $T/rows_mi.py $R/<날짜>_pilot4 --out <다른 곳>/trials.csv   # lineage_warn 열을 읽기만(판정 아님)
```

pilot 4가 볼 것(9.9절): 모든 시행 `lineage_warn` 0; 셀마다 pilot 2와 같은 판정; "store request ... dropped" 줄은 죽은 프로세스 것만; mirror 끈 회귀(P5)의 줄 수와
판정이 pilot 2와 같음; `mi4_pull` kill 시행은 `lane_broken_other` 0, `disarm_other` 0, kill이 당기기 창에 떨어진 시행에서는 "a pulled checkpoint at step N did
not drain: the pull is kept for the next Step" 줄 뒤 INJECTED 뒤 1–2 Step 안에 그 rank의 체크포인트가 찍힘.

다음 묶음 set `mi5`(빌드 ln3)의 배포와 pilot 5(같은 꼴; 2026-10-15 저녁):

```
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad; F=$SCR/agent_mi_fix
RS_SET=mi5 MITREE=agent_mi_fix MIOUT=mi_ln3 COSTOUT=cost_ln3 MROUT=mr_ln3 \
  MI_LIB_SRC=$F/out/mi_ln3/libnccl.so.2.32.3 MIP_LIB_SRC=$F/out/mip_ln3/libnccl.so.2.32.3 \
  WANT_MI=e927457a4986a8314ce911259beff51c WANT_MIP=58d7ff3f47d89205661a65b90a419298 \
  WANT_GINMI=0d0dd90b4ad740905ce49a9f76043080 WANT_GINMI_NOMACRO=9fcc9ab4ddab6367c259cc62ef2e5d11 \
  WANT_COST_MI=7e3a2ef6ca4a771e29b39acc7d58d4a1 WANT_MR_FF=00adb957eb65e38b183918817b435fd8 \
  WANT_MR_HOLD=d914df6def6cce8590e69a953a49d222 bash $T/deploy_mi.sh $F/deploy_check_mi5.txt
grep -E "MISMATCH|CHANGED|not found" $F/deploy_check_mi5.txt     # 아무 줄도 없어야 함
RS_SET=mi5 bash $T/chain_mi.sh $R/<날짜>_pilot5 P6   # cluster_run.sh 안에서
python3 $T/rows_mi.py $R/<날짜>_pilot5 --out <다른 곳>/trials.csv   # 열을 읽기만(판정 아님)
```

pilot 5가 볼 것([../../EXPERIMENT.md](../../EXPERIMENT.md) 9.3, 9.9절): 모든 시행 `lineage_warn` 0; `mi4_pull` kill 시행 `lane_broken_other` 0, `disarm_other` 0;
"the pull is kept" 줄이 난 시행에서는 "the pull is spent" 없이 같은 rank가 그 체크포인트를 찍음(hold의 "a restore runs" 뒤면 INJECTED 뒤 첫 Step, "the checkpoint
store is not ready" 뒤면 "store ready at buddy" 뒤 첫 Step); `mi4_kill3_ow`, `mi4_train_kill3`는 pilot 2–4와 같은 판정(`ow_data_equal` 1, `wait_held` 1, 공백 밖
깨짐 0). 복원 시간은 두 모드를 따로 읽는다(`later_n`, `post_activate_ms`).

다음 묶음 set `mi3`(빌드 i4)의 배포(같은 꼴; 드라이버의 cost와 gin_mr은 새 하위 폴더 `cost_i4`, `mr_i4`라 `COSTOUT`, `MROUT`을 준다):

```
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad; F=$SCR/agent_mi_fix
RS_SET=mi3 MITREE=agent_mi_fix MIOUT=mi_i4 COSTOUT=cost_i4 MROUT=mr_i4 \
  MI_LIB_SRC=$F/out/mi_i4/libnccl.so.2.32.3 MIP_LIB_SRC=$F/out/mip_i4/libnccl.so.2.32.3 \
  WANT_MI=c89ce744312b1af057c85f6eac975baf WANT_MIP=12a0edeca10b491458a86471e9903e53 \
  WANT_GINMI=5887dfeacdde2ed96de0de9105e6eb88 WANT_GINMI_NOMACRO=5cd7246b79c7da5913e001dd1e88e4af \
  WANT_COST_MI=05093a694d01979b638121555dbdf637 WANT_MR_FF=2b18db83fb5c7e46333868a85523ddde \
  WANT_MR_HOLD=6debbb6db79ead05d040afc22726493a bash $T/deploy_mi.sh $F/deploy_check_mi3.txt
grep -E "MISMATCH|CHANGED|not found" $F/deploy_check_mi3.txt     # 아무 줄도 없어야 함
RS_SET=mi3 bash $T/chain_mi.sh $R/<날짜>_pilot3 P1 P2 P3 COSTPILOT-rain COSTPILOT-sunny   # pilot을 한 번 더 할 때(메인 세션이 정함)
```

실행 가능성 확인 2(손으로 하는 mirror 비용, `feas/cost_man.md`)의 드라이버는 `gin_ts2_mi`다. feas 폴더가
`run_mf.sh`의 `cm_*` 셀과 `COSTMAN-*` hold로 돌리고 `summ_mf.py`가 읽는다. 배포는 `CM_SRC=$F/test/out/cost/gin_ts2_mi
WANT_MFCM=ad0908442a8b687c242ba806a6f54069 bash feas/deploy_mf.sh <출력> mfcm`(i4: `$F/test/out/cost_i4/gin_ts2_mi`,
`05093a694d01979b638121555dbdf637`).

## pilot이 먼저 볼 것 (pilot 1 전에 적음; pilot 1, 2가 본 것은 EXPERIMENT.md 12절)

1. 재기만 하는 모드의 mirror 팔: rank 0 "measurement mode mirror arm ...: N cell(s) valid"의 N ≥ 1, "mirror summary"의
   broken=0과 max_live_bytes > 0. 깨지면 lane(`MIRROR_LANE`)이나 helper 걸음의 늦음이 원인이다.
2. 자기 루프 lane(짝이 자기에게 쓰는 mirror): DOCA의 게이트 없는 자리 기다림과 창 검사, `rsMiWait`의 20 ms 정지 판정이
   거짓 깨짐을 내는지("lane to rank ... broken (device)"가 장애 없는 `mi4_none_ow`, `mi4_train_none`에 없어야 함).
3. 복원 길의 처음 실행: drain("drain for rank"), 활성화 v2와 RDMA FETCH("fetch for checkpoint"), 내보내기 v2("export to rank"
   source_bytes=0), 단계 맞춤 가져오기("import step"은 입력이 있는 단계만, "import done" left=0), INJECTED("INJECTED sent",
   생존 rank의 "INJECTED from rank").
4. 저장소: Resume 뒤 "store ready at buddy rank", 체크포인트마다 "checkpoint ... stored at buddy rank", 체크포인트 거절
   "the checkpoint store is not ready"가 처음 몇 번 뒤 사라지는지.
5. 둘째 죽음(`mi4_kill2_kill3_ow`, `mi4_train_kill2_kill3`): rank 3의 STORE_REQ(`reason=buddy`)가 되살린 rank 2에 가
   rank 3의 예비 프로세스 주소가 등록되는지("store request to buddy rank 2 ... reason=buddy"), 그 뒤 rank 3의 전체 이미지
   확정과 다시 무장.
6. hold 한도: `fits`와 시행 건너뛰기는 시행 한도(4 KiB 60 s)로 세지만 예비 프로세스 시행은 `WATCHDOG_S` + 20 s까지 갈 수 있다.
   hold가 chain의 `timeout -s KILL 880`에 걸리면 남은 프로세스 때문에 다음 hold가 STOP_left로 서고 chain이 멈춘다(안전). 그러면 hold를 나눈다.

## 셀마다 pilot이 보여야 할 것

`cells_mi.json`의 `driver`가 셀마다 돌릴 빌드를 정한다. mirror 셀은 모두 `gin_mi`(매크로), 거절 셀도 `gin_mi`, 회귀
셀은 `mr/ff`(매크로 없음)과 `mr/hold`(매크로), gin-restore 거절 셀 `rs4_refuse_nomacro`는 `gin_mi_nomacro`다. 다른 빌드로 돈 시행은 뺀다(`config_driver`).

- `mi4_none_ow` (@mi): 장애 없이 600단계, exit 0, 데이터 기준과 비트 단위로 같음(`ow_data_equal`), 복원 0, 체크포인트마다
  입력 멈춤 ≤ 10 ms(`ckpt_pause_ms`), segment 다시 시작 0. 받은 독 값 0(`recv_poison`, `dev_poison`).
- `mi4_kill3_ow` (@mi): 생존 rank 대기 붙잡힘(`wait_held`), 모든 rank 데이터 같음(`ow_data_equal`), 재실행 없음, 되살림,
  억제 정확(`suppress_ok`), 복원 ≤ 2 000 ms. 재실행의 내용이 모두 pool에서 옴(`from_pool_ok`: 내보내기 원본 바이트 0,
  가져온 pool 바이트 = 내보낸 mirror 바이트). 체크포인트는 RDMA로(`tcp_image_bytes` 0, `tcp_segment_bytes` 0).
- `mi4_kill1_ow`, `mi4_kill3_ckpt_ow` (@mi): 같은 결과. ckpt 셀은 kill 앞 확정 체크포인트에서 복원(`ckpt_before`),
  생존 셋이 모두 멈춤 안에서 죽음을 맞음(`die_in_pause` = 3; 라이브러리 시험 스위치 `NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT`).
- `mi4_kill3_ow_nomirror` (@mi, mirror 끔): 복원은 끝나되 독 값이나 다른 단계 값이 들어가 데이터가 틀림(`nomirror_corrupt`).
- `mi4_kill3_ow_sampled` (@mi, mirror 끔, checksum 표본): 내보내기가 "source buffer changed"로 거절하고 fallback하며
  생존 rank가 죽음 + 2 000–2 500 ms에 degraded로 풀림(`nomirror_detect`).
- `mi4_seg_4k/_32k/_128k` (@mi): 확정 체크포인트 뒤 15단계째 kill(lane 1 MiB, 2 MiB, 6 MiB: L ≥ 단계당 바이트 × 간격 × 2, 9.3절). FETCH 시간이 가져온 바이트와 함께 a + 바이트/θ의
  ±30% 안이고 중앙값이 바이트 순서대로 는다(`fetch_us`, `fetch_bytes`; a 5 µs, θ 11.88 GB/s). pilot이 절편과 기울기를 실제로 본다.
- `mi4_int_10/_20/_40` (@mi, 장애 없음): 최고 살아 있는 바이트(`pool_max_bytes`, mirror summary의 max_live_bytes)의 비가 간격 두
  배마다 2 ± 25%, 다시 시작 0. 예측(predictions_mi.csv)의 말대로 max_live_bytes로 잰다(통합 판단: `max_fill=` 키는 더하지 않음; 3절 글과의 맞춤은 사전 등록에서).
- `mi4_pull_none` (장애 없음 3), `mi4_pull` (kill 5): lane 48 KiB, 당기기 50%. 당기기 ≥ 1, DISARM 0(`pulls_sent`,
  `disarm_n`). kill은 붙잡고 되살리고, 설계한 짝 보호 공백(9.6절: 죽은 rank가 맡던 rank 쪽 lane이 hold부터 그 rank의 다음 확정
  체크포인트까지 깨짐) 밖의 깨짐과 DISARM 0(`lane_broken_other`, `disarm_other`; pilot 2에서 kill 시행마다 공백 깨짐 2줄).
- `mi4_overflow` (@mi): lane 2 KiB(put보다 작음). lane 깨짐과 DISARM, hold 시작 없음, degraded 해제(`lane_broken`,
  `hold_started`, `degraded_release`).
- `mi4_kill2_kill3_ow` (@mi): rank 2(단계 180–220)를 kill하고 되살린 뒤 rank 3(단계 380–420)을 kill. 예비 프로세스 둘.
  `reimage_ok`: rank 3이 rank 2 복원을 본 뒤 되살린 rank 2에 전체 이미지를 확정(`checkpoint K stored at buddy rank 2`), 그 사이
  void ≤ 1, 둘째 kill 전에 생존 rank(0, 1, 되살린 2) 모두에서 rank 3 다시 무장. `second_ok`: 두 복원 모두 ≤ 2 000 ms, 되살린
  rank 둘, 둘째 예비 프로세스가 rank 2에서 FETCH. 대기 붙잡힘과 재실행 없음은 되살린 rank 2까지 셈. 차례는 QA가 줄의 시각으로 다시 센다(10.8절).
- `mi4_train_none` (@mi, 학습 모양, 장애 없음), `mi4_train_kill3` (@mi, 핵심), `mi4_train_kill2_kill3` (@mi, 둘째 죽음):
  2 MiB × 상대 셋, 2 000단계, local 완료 직후 덮어씀, 받는 고리 R = 4. kill은 seed 무작위 단계와 단계 안 지연 0–8 ms(`DIE_SEED`로 고정).
  `train_data_equal`, `train_paced_import`(가져오기가 start_step부터 단계마다 한 번 그 커널 전, 남은 입력 0, INJECTED는 마지막 단계에
  한 번이고 생존 셋이 받음), `train_restore_parts`,
  `train_segments`(다시 시작 0), `train_pull_count`(설계한 짝 보호 공백 밖의 깨짐 0, DISARM 0), `train_none_clean`(멈춤 ≤ 15 ms), `store_rdma`.
  QP 감시 50 ms, lane 80 MiB, 예비 프로세스 기다림 ≥ 120 s(6, 8절).
- `mi4_refuse_csum`(mirror+checksum 함께, 조건 36), `mi4_refuse_mirror1`(한 rank만 mirror 끔, 조건 34), `mi4_refuse_sl`(S가 다름,
  조건 39) (@mi): 모든 rank Resume 오류, 이유 같음, 그 조건의 이유 글자, fail-fast로 넘어간 rank 없음.
- 회귀(mirror 끔): gin-restore 7절의 복원과 거절 셀을 그 이름과 env 그대로 @mi에서(`rs4_*`, R2, R3; 예측 `rg_*`는 gin-restore의
  판정식 그대로)와 gin-remaining 런너의 `reg_*`(R1). 회귀(mirror 켬, 덮어쓰지 않는 workload): `rs4_none_mion`, `rs4_kill3_mion`(R3).
- 비용(@mip): 팔 `off`(fail-fast), `on`(로그 켬), `mirror-self`, `mirror-peer`(라이브러리 재기만 하는 모드,
  `NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR`). 지표 lat4k, lat256k, lat2m, bw256k, bw2m, 노드 둘. 4 KiB 지연은 `on`보다 2.5 µs 안
  (`within_us:2.5`), 묶음 대역 mirror-peer / on이 0.40–0.60(`ratio:0.40-0.60`), 그 밖은 보고. mirror 팔은 rank 0의 `mirror
  summary`(broken=0)가 있어야 유효한 실행이다(라이브러리가 mirror 쓰기를 냈다는 근거).

## pilot이 고정하는 문턱과 n

pilot 2의 값에서 낸 사전 등록 초안은 세션 스크래치 `prereg_mi_draft.md`다(사용자 결정 전, 숫자는 아직 고정 아님).

- 반복 수(n): 7절의 초안(복원 셀 5–10, 명시적 오류 셀마다 3, 회귀 5, 비용 팔마다 노드마다 6). 한 hold가 840 s 안에 드는지
  보고(`fits`), 넘으면 hold를 나눈다(8절: `mi4_train_none` + `mi4_train_kill3`가 T1, `mi4_train_kill2_kill3`가 T2; 4 KiB는 G1과 G3).
- seed: `mi4_train_kill3`, `mi4_train_kill2_kill3`, `mi4_kill2_kill3_ow`의 무작위 kill을 정하는 `DIE_SEED`를 사전 등록
  때 고정한다(지금 `mi-v1`은 자리값). 같은 seed, 셀, 시행이면 kill 단계와 지연이 같다(`run_mi.sh`의 draw).
- 복원 시간 문턱 T: 초안 2 000 ms(gin-restore 중앙값 375.6 ms의 약 5배). 학습 모양은 ≤ 1 000 ms.
- 입력 멈춤 문턱: 4 KiB 초안 10 ms, 학습 모양 15 ms(멈춤 약 5 ms + D2H 2.4 ms + 여유).
- 비용 문턱: 3절 초안 그대로 `within_us:2.5`(4 KiB 지연)와 `ratio:0.40-0.60`(묶음 대역, mirror-peer). 256 KiB와 2 MiB 지연은
  보고만. pilot의 중앙값을 보고 사전 등록에서 고정한다.
- QUERY_QP 상한: 복원 시행과 비용 실행 초안 50 000(mirror 문맥이 QP n + 1 묶음을 더함, 8절), 회귀 150 000. 시행 한도
  4 KiB 60 s, 학습 모양 150 s(8절 초안 120 s에, fallback한 학습 시행은 예비 프로세스가 120 s를 기다려 약 125–130 s가 됨을 더함).
  `mi4_overflow`는 예비 프로세스 기다림 15 s(활성화되지 않는 셀; 2026-10-15 30 s에서 줄임, 사용자 결정 대기).
- 호스트 메모리 시작 검사: `run_mi.sh`가 노드마다 pool + 저장소 + D2H 버퍼(+ 예비 프로세스의 FETCH 버퍼) + 1 GiB를
  MemAvailable과 견준다. 모자라면 시행을 시작하지 않고 exit 5(hold가 `STOP_mem`). pilot이 실제 바이너리의 고정 메모리로
  이 어림을 다시 본다(9.5절 BAR1 `[미확인]`과 함께).

## 아직 할 수 없는 것 (통합 뒤 pilot이 처음 봄) `[미확인]`

- mirror 라이브러리 줄의 실제 꼴이 `rows_mi.py`의 정규식과 맞는지(줄 키는 impl/rs_mirror_api.h, rs_store_api.h가 정함;
  의존하는 줄은 [../../EXPERIMENT.md](../../EXPERIMENT.md) 12절의 test 갈래 행). 통합에서 소스와 대조했고(12절), pilot이 실제 줄로 다시 본다.
- 재기만 하는 모드의 mirror 팔(`NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR`)이 실제로 mirror 쓰기를 내는지.
- 단계 맞춤 가져오기의 INJECTED와 게이트 홀수 유지가 학습 모양에서 데이터를 지키는지(9.4절).
