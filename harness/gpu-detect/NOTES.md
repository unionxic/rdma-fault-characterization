# gpu-detect 구현과 실행 메모

[README.md](README.md)의 연구 내용 밖에 있는 구현, 빌드, 실행을 짧게 모았다. 자세한 설명은 [EXPERIMENT.md](EXPERIMENT.md)의 해당 절에 있다.

## 계층

| 빌드 | 파일 | 무엇을 | 자세히 |
|---|---|---|---|
| GIN `hw` | [hw_layer.diff](hw_layer.diff)(`gin_host_gdaki.cc` 하나, gin-remaining `hr` 기준) | QP 상태 감시(`NCCL_GIN_TS_QPWATCH_MS`, `_GRACE_MS`, `_NOCQE_MS`), 기다림 안 응답의 중첩 하나(M-A), NIC만 쓰는 자체 시험(L-C), degraded 뒤 게시 전 확인(M-C, `NCCL_GIN_TS_DEGRADED_ROUNDS`) | 9.1절 (a)–(e) |
| GIN `hk` | [hk_layer.diff](hk_layer.diff)(같은 파일, `hw` 위) | 정책 hook G1–G9(`NCCL_GIN_FAULT_POLICY`), 응답 쪽 Commit 뒤 손실의 죽음 판정과 `pe.lostAfterCommit`, 시험 스위치 `NCCL_GIN_TS_TEST_EXIT_AFTER_ACK`(연구 빌드만), 정리 때 감시 줄 | 9.1절 (f)–(h) |
| NVSHMEM `t1w` | [t1w_layer.diff](t1w_layer.diff)(파일 셋, t1_380 기준) | 작별 메시지(`T1_M_BYE`)와 FIN 판정(`NVSHMEM_IBGDA_FT_T1_FIN_DEATH`), fail-stop(`NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS`, `_CODE`), 장치 대기 단어(release) | 9.2절 |

- 재현: GIN은 순정 NCCL v2.32.3-1 + `../gpu-initiated/gin_recovery/remaining/gin_transparent_hr.diff` + `hw_layer.diff` + `hk_layer.diff`. NVSHMEM은
  9.4절 끝의 diff 넷 + `t1w_layer.diff`. 운영 빌드는 같은 소스에 `-DNCCL_GIN_TS_PRODUCTION`(빌드만 했다).
- 빌드 md5와 기준 트리는 EXPERIMENT.md 5절, 빌드 단계는 9.4절.
- 예제 둘(`09_gin_optimizations/01_ring_exchange`, `ring-reduce`)은 소스를 그대로 두고 새 헤더로 다시 빌드했다(`gd_gin_ring`, `gd_nvs_rr`).
  부트스트랩 대체는 blind-apps의 것(`../blind/boot/`)이다.

## 스크립트

| 파일 | 하는 일 |
|---|---|
| [build_gd.sh](build_gd.sh) | 세션 스크래치의 빌드 단계(`gin-setup`, `gin-hw`, `gin-hwp`, `gin-app`, `nvs-setup`, `nvs-lib`, `nvs-app`, `hk-setup`, `gin-hk`, `gin-hkp`, `info`) |
| [make_diff_gd.sh](make_diff_gd.sh) | diff 셋을 쓰고 기준 커밋에 다시 적용해 트리와 같은지 확인 |
| [deploy_gd.sh](deploy_gd.sh) | 두 노드의 새 디렉터리에 배포하고 md5 확인([deploy_check.txt](deploy_check.txt), [deploy_check_hk.txt](deploy_check_hk.txt)) |
| [apprun.py](apprun.py), [cells.json](cells.json), [schedule.json](schedule.json) | 예제 시행 실행기(blind-apps 실행기를 고친 사본), app 셀, 시드로 만든 시행 목록 |
| [cells_reg.sh](cells_reg.sh) | 드라이버 셀(gin-remaining의 실행기를 그대로 부름) |
| [hold.sh](hold.sh), [chain.sh](chain.sh) | hold 하나(스냅숏, 남은 프로세스, STOP 규칙), hold 사슬(`../gpu-initiated/common/cluster_run.sh` 안에서, hold마다 880 s 한도) |
| [rows_gd.py](rows_gd.py), [score.py](score.py) | 시행별 열(3.1절)과 채점 |
| [qa/app_recount.py](qa/app_recount.py), [qa/reg_recount.py](qa/reg_recount.py), [qa/verdicts.py](qa/verdicts.py) | 독립 재계산(사용법은 [results/20261009/qa_recount.md](results/20261009/qa_recount.md) 1절) |

## 본 실행과 채점

```
D=harness/gpu-detect; R=$D/results
bash $D/chain.sh $R/20261009 G1 G2 N1 N2 R1 R2 R3 R4
python3 $D/score.py $R/20261009
```

배포와 pilot을 포함한 전체 순서는 EXPERIMENT.md 9.6절이다. 본 실행은 2026-10-09 21:35:03–22:20:41에 돌았다(12절).

## 출력

- `results/20261009/raw/<id>/`: 예제 시행마다 `r0.log`, `r1.log`, `a0.log`, `a1.log`, `trial.meta`(줄마다 rain 수신 시각).
- `results/20261009/reg/hk/`, `reg/mr_hk/`, `reg/mr_hw/`: 드라이버 시행의 kv, 로그, meta, `kill.out`, 원시 지연.
- hold마다 `snap_*`, `mlx5_*`, `fwcmd_*`, `hold_*_p1.out`, 그리고 `chain.out`, `runner.log`, `schedule_sha256.txt`.
- 원자료는 Release `data-20261009`의 `harness__gpu-detect__results__20261009.tar.xz`(pilot은 `_pilot`, `_pilot2`)에 있다. 저장소에는 `SCORE.md`,
  `trials_scored.csv`, `qa_recount.md`만 둔다.
