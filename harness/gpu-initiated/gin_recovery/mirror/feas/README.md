# gin-mirror 실행 가능성 확인 도구

[../EXPERIMENT.md](../EXPERIMENT.md) 9.8절의 "실행 가능성 확인 넷"을 돌리는 도구다. 채점하지 않는다(DRAFT 단계). 클러스터 실행은 메인 세션이
`cluster_run.sh` 안에서 한다. 이 폴더의 도구는 빌드만 했고 아직 한 번도 돌리지 않았다.

## 확인과 통과 기준(초안, 실행 전에 적음)

| 확인 | 무엇을 재나 | 통과 기준 | 도구 |
|---|---|---|---|
| 1. 호스트 MR에 쓴 것이 보이는가 | 한 노드의 GPU 버퍼(cuMem, dmabuf MR)에서 다른 노드의 호스트 MR(iova 0, relaxed ordering 없음, 다른 MR과 같은 PD)로 RC WRITE 4 KiB, 256 KiB, 2 MiB를 크기마다 10 000번. 응답 쪽 QUERY_QP의 rmsn이 보낸 수에 닿은 뒤 반복마다 길 하나: (a1) CPU가 바로 읽음, (a2) 같은 PD의 루프백 QP 쌍으로 pool 낱말 하나를 READ한 뒤 CPU가 읽음, (a3) 셋째 QP의 RDMA READ로 읽음 | (a2)와 (a3)에서 틀린 낱말 0, 두 방향 모두. (a1)은 보고 | `mirror_feas vis` |
| 2. 손으로 하는 mirror의 비용 | gin_ts2에서 put 뒤 문맥 1로 같은 원본을 한 번 더 put하고 둘 다 flush(팔 `man-self`, `man-peer`) 대 한 번 put(`one`). 4 KiB, 256 KiB, 2 MiB 지연과 256 KiB × 8, 2 MiB × 8 대역 | 판정 없음. 3절 초안(4 KiB +2.5 µs, 대역 비 0.40–0.60)과 견줌 | gin_ts2에 더할 팔은 [cost_man.md](cost_man.md) |
| 3. RDMA 저장소의 시간 | GPU 30 MiB를 다른 노드의 호스트 MR로 WRITE 100번(다른 QP가 2 MiB × 8 묶음을 보낼 때와 아닐 때, 10번씩 번갈아), 호스트 MR 150 MiB를 다른 노드가 READ 100번(30 MiB씩 다섯) | WRITE p99 ≤ 10 ms(두 팔), READ p99 ≤ 100 ms. θ = 150 MiB / READ p50을 3절 `train_restore_parts`에 넘김 | `mirror_feas store` |
| 4. rain BAR1 예산 | rain GPU에 프로세스 셋(rank 0, rank 2, rank 2의 예비 프로세스 자리)이 window 6 MiB와 24 MiB를 한 PD에 dmabuf로 등록, 그중 하나는 둘째 PD에도 등록. 단계마다 `nvidia-smi` BAR1을 읽기만 | 세 프로세스 등록 뒤 BAR1 Free ≥ 64 MiB. 둘째 PD 등록이 BAR1을 더 쓰는지 기록 | `mirror_feas bar1` |

## 파일

| 파일 | 내용 |
|---|---|
| [mirror_feas.cu](mirror_feas.cu) | CUDA + libibverbs 프로그램 하나(NCCL 없음), 모드 `vis`, `store`, `bar1`. 모드마다 watchdog과 kv |
| [build_mf.sh](build_mf.sh) | 세션 스크래치의 새 폴더에 빌드(sm_75, sm_86, 경고를 오류로) |
| [deploy_mf.sh](deploy_mf.sh) | 두 노드의 새 디렉터리 `~/rs-bundle/mf/`(또는 `mfcm/`)에 배포, md5 확인, 있으면 거절 |
| [run_mf.sh](run_mf.sh) | 실행 하나(셀, 반복 수). `timeout -s KILL`, 포트 고르기, 받은 시각 찍기, IPv4 가림 |
| [hold_mf.sh](hold_mf.sh) | hold 하나(`VIS`, `STORE`, `BAR1`, `COSTMAN-*`). 앞뒤 스냅숏, 시작 검사, STOP 규칙 |
| [summ_mf.py](summ_mf.py) | 원자료에서 확인마다 읽기와 통과 여부. `--selftest <빈 폴더>`는 가짜 원자료로 CPU에서만 스스로 시험 |
| [cost_man.md](cost_man.md) | 확인 2: gin_ts2에 더할 팔의 명세(시험 작업 묶음이 만듦) |

빌드 `[측정]`: `mirror_feas` md5 `8b0d258abfbe9428b948f74dfcad524f`(소스 `mirror_feas.cu` md5 `d0b0d512`, 경고 0, SASS sm_75와 sm_86), 세션 스크래치
`mirror_feas/mf1/`. 빌드됨이고 실행하지 않았다. `summ_mf.py --selftest`는 통과했다(가짜 원자료 두 벌: 다 통과하는 것, 확인 1, 3, 4가 틀리게 만든 것).

## 메인 세션 명령

`SUNNY_SSH`는 관리망 env 파일에서 셸에 넣은 값을 쓴다(어느 파일에도 적지 않는다). `R`는 이번 결과 폴더다(원자료는 뒤에 Release로).

```bash
F=harness/gpu-initiated/gin_recovery/mirror/feas
C=harness/gpu-initiated/common/cluster_run.sh
R=harness/gpu-initiated/gin_recovery/mirror/results/20261013_feas
# 배포(두 노드에 새 ~/rs-bundle/mf/mirror_feas)
WANT_MF=8b0d258abfbe9428b948f74dfcad524f bash $F/deploy_mf.sh <scratch>/mirror_feas/deploy_mf1.txt mf
# 확인 1, 3, 4 (hold마다 cluster_run.sh 안)
$C -w 10800 -t mf-VIS -- timeout -s KILL 880 bash $F/hold_mf.sh $R VIS
$C -w 10800 -t mf-STORE -- timeout -s KILL 880 bash $F/hold_mf.sh $R STORE
$C -w 10800 -t mf-BAR1 -- timeout -s KILL 880 bash $F/hold_mf.sh $R BAR1
python3 $F/summ_mf.py $R
# 확인 2 (cost_man.md의 gin_ts2가 빌드되고 배포된 뒤)
CM_SRC=<빌드> WANT_MFCM=<md5> bash $F/deploy_mf.sh <scratch>/mirror_feas/deploy_mfcm.txt mfcm
$C -w 10800 -t mf-COSTMAN -- timeout -s KILL 880 bash $F/hold_mf.sh $R COSTMAN-rain-lat4k   # 노드 둘 × 지표 다섯
```

STOP 규칙과 시작 검사는 [hold_mf.sh](hold_mf.sh) 머리에 있다: STOP 파일이 있으면 hold 거절, 실행마다 오류 키나 빠진 kv면 `STOP_nic`, 남은
프로세스면 `STOP_left`, rain 펌웨어 명령 실패가 늘거나 실행 하나에 rain QUERY_QP가 40 000 넘게 늘면 `STOP_mlx5`, hold 뒤 CUDA 메모리 오류면
`STOP_cuda`. 시작 검사는 rain BAR1 Free ≥ 128 MiB(BAR1 hold는 192 MiB), 두 노드 MemAvailable ≥ 2 GiB. 확인 1의 틀린 낱말과 확인 4의 등록 실패는
읽기이지 멈춤이 아니다.

## 실행 전에 알 수 없는 것 `[미확인]`

- 확인 1: QUERY_QP 한 번이 수십 µs라 (a1)도 늦은 쓰기를 한 번도 못 볼 수 있다. 그러면 이 확인은 (a2)와 (a3)이 충분함만 보이고 울타리가 필요함은 보이지
  못한다(gin-restore B3에서 READ 없는 대조 길도 실패 0이었던 것과 같은 한계). summ_mf.py가 그 문장을 찍는다.
- 확인 1: 2 MiB 셀의 QUERY_QP 수. 반복마다 첫 질의를 도착 추정의 0.9배 뒤에 내므로 반복당 1–3번으로 어림하고 `[추론]`, 30 000에서 반복 경계에 멈춘다
  (`budget_stop=1`, 그때까지의 n으로 셈). rain이 받는 쪽인 셀은 hold의 실행당 상한 40 000 안이다.
- 확인 3: 두 노드의 memlock 한도(kv `memlock_kib`, meta)와 호스트 MR 180 MiB 등록이 되는지.
- 확인 4: 다른 사용자의 GPU 작업이 읽기 사이에 BAR1을 바꿀 수 있다. hold 앞뒤의 GPU 사용자 목록과 meta의 `gpu_apps_before`로 본다.
- 확인 2: GDAKI의 자기 rank put과 문맥 1의 존재([cost_man.md](cost_man.md) 끝).
