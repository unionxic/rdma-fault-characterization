# gin-control 구현과 실행 메모

이 파일은 안내만 맡는다: 지금 쓰는 구현 파일, 그리고 빌드, 로컬 검증, 배포와 실행, 채점을 어느 스크립트와 문서로 하는지. 상태와 다음 작업은
[EXPERIMENT.md "현재 상태"](EXPERIMENT.md#현재-상태)와 11.1절, 설계는 9절, 판정식과 셀과 제외 기준은 3, 7, 8절이 기준이다. 인자의 정확한 뜻은 각 스크립트의
머리 주석이 기준이다. 아래는 2026-10-23(커밋 `e1fee5b8`)에 머리 주석과 대조했고, 스크립트는 돌리지 않았다.

## 지금 구현 파일

| 무엇 | 파일 | 자세한 문서 |
|---|---|---|
| 라이브러리 계층(호스트 파일 `gin_host_gdaki.cc` 하나, 장치 코드 0줄) | [impl/gc_layer_int.diff](impl/gc_layer_int.diff)(md5 `3ae8f572`, 2026-10-28 ① 라이브러리; 2026-10-23 당시 `5ed121f4`): gin-mirror ln4([../mirror/impl/mi_layer.diff](../mirror/impl/mi_layer.diff), md5 `dcd30859`) 위의 전체 층. smoke 4와 5가 이것을 돌렸다 | EXPERIMENT 9.1–9.8절, 단계별 작업 기록 `impl/notes_*.md` |
| 공유 헤더와 바꿈 자리 표 | [impl/rs_ctrl_api.h](impl/rs_ctrl_api.h)(호스트 파일에 붙이는 블록 둘), [impl/gc_sites.tsv](impl/gc_sites.tsv) | `impl/build_gc.sh`의 `paste`, `api`, `sites` 단계 |
| 단계별 diff와 단위 시험 | `impl/gc_layer_<단계>.diff`, `impl/rs_ctrl_api_<단계>.diff`, `impl/gc_unit_*.cc`, [impl/gate_fenced.cc](impl/gate_fenced.cc) | 단계마다의 기록이다. 지금 층은 `gc_layer_int.diff` 하나다 |
| launcher(노드마다 하나) | [impl/launcher/](impl/launcher/): `gin_launcher.c`, `launcher_transport_verbs.c`, `launcher_msg.h`, `launcher_unit.cc` | [impl/launcher/README_launcher.md](impl/launcher/README_launcher.md), credit READ 재시도는 [impl/launcher/notes_launcher_credit.md](impl/launcher/notes_launcher_credit.md) |
| 시험 driver | [impl/test/driver/gin_mi.cu](impl/test/driver/gin_mi.cu)(gin-mirror 사본에 GPU hang 스위치 `GC_GPUHANG_IT`) | [impl/test/notes_test.md](impl/test/notes_test.md) "GPU hang 셀과 driver 사본" |
| 셀과 예측 | [impl/test/cells_gc.json](impl/test/cells_gc.json), [impl/test/predictions_gc.csv](impl/test/predictions_gc.csv) | EXPERIMENT 3, 7, 8절 |
| 실행기와 채점기 | `impl/test/*.sh`, `impl/test/*.py` | [impl/test/notes_test.md](impl/test/notes_test.md) |

## 빌드

- **라이브러리:** [impl/build_gc.sh](impl/build_gc.sh). `SCR=<세션 스크래치> BR=<작업 묶음> build_gc.sh <단계>`. 작업 묶음 키는 `prep`부터 `int3`까지,
  단계는 `setup`, `paste`, `repaste`, `api`, 빌드 넷(`gc`, `gcp`, `gct`, `gctp`), `unit`과 단계별 `unit*`, `syn`, `pre`, `sites`, `ident`, `diff`, `info`다.
  트리는 저장소 밖 스크래치 `agent_gc_<BR>/`에 만들고 gin-mirror ln4 트리는 읽기만 한다. 빌드 키의 뜻은 EXPERIMENT 머리 "빌드 키" 표다(셀이 쓰는 것은 `gc`,
  `gct`, `gcp`).
- smoke 4가 빌드한 트리는 스크래치 `agent_gc_p2a2/nccl-src`이고, 그 트리가 ln4 + `gc_layer_int.diff`와 같음을 `cmp`로 확인했다. 빌드를 부른 스크립트는
  저장소 밖에 있다([results/20261023_smoke4/SMOKE.md](results/20261023_smoke4/SMOKE.md) 머리). 새 스크래치에서 ln4 + `gc_layer_int.diff`를 다시 만드는 일이
  `build_gc.sh`의 단계 하나로 되는지는 `[미확인]`이다.
- **launcher:** [impl/launcher/build_launcher.sh](impl/launcher/build_launcher.sh) `OUT=<dir> build_launcher.sh [all|build|unit|clean]`. 프로그램, 헤더 검사,
  단위 시험(ASan, UBSan, 가짜 libibverbs로 verbs 전송까지)을 만들고 돌린다. `gin_launcher` 자체와 verbs 장치는 실행하지 않는다.
- **driver:** [impl/test/driver/build_driver_gc.sh](impl/test/driver/build_driver_gc.sh) `<mi|info>`. 컴파일만 한다. 헤더와 라이브러리는 `RSINC`, `RSLIB`(기본은
  스크래치의 `gc` 빌드 트리).

## 로컬 검증 (클러스터 없음)

- [impl/test/check_cells_gc.py](impl/test/check_cells_gc.py): 3, 7절과 셀 파일, 예측 표의 대조와 drift. 파일만 읽는다. 3, 7, 8절, 셀 파일, 예측 표를 고친 뒤 돌린다.
- [impl/test/test_rows_gc.py](impl/test/test_rows_gc.py): 합성 결과 폴더로 `rows_gc.py`, `score_gc.py`와 셸 조각의 자체 시험("self-test: N checks, F failed").
- [impl/test/gate_proc_gc.py](impl/test/gate_proc_gc.py): 실제 프로세스로 하는 관문 시험(자기 자식만 띄움). `gate_fenced.cc`의 pid 모드는 아직 TODO다.
- 라이브러리 단위 시험은 `build_gc.sh`의 `unit*` 단계, launcher 단위 시험은 `build_launcher.sh unit`.

## 배포와 실행 (조율 세션만)

모든 클러스터 실행은 `harness/gpu-initiated/common/cluster_run.sh` 안에서 한다. 부르는 차례와 각 스크립트의 몫:

| 스크립트 | 몫 |
|---|---|
| [impl/test/deploy_gc.sh](impl/test/deploy_gc.sh) | rain과 sunny의 `~/rs-bundle/<RS_SET>/` 아래 새 폴더에만 라이브러리, driver, launcher를 둔다. 덮어쓰지 않고 md5를 견준다 |
| [impl/test/chain_gc.sh](impl/test/chain_gc.sh) | hold마다 `cluster_run.sh` hold 하나. `STOP_*` 파일이 생기면 다음 hold를 돌리지 않는다 |
| [impl/test/hold_gc.sh](impl/test/hold_gc.sh) | hold 하나(본 실행 C1–C11, pilot과 smoke P0–P4, 회귀 `RG-*`, 비용). `chain_gc.sh` 밖에서는 돌지 않는다. pilot과 smoke hold는 이름이 `pilot`이나 `smoke`로 시작하는 결과 폴더에서만 돈다 |
| [impl/test/cells_gc.sh](impl/test/cells_gc.sh) | 셀 하나를 n번 |
| [impl/test/run_gc.sh](impl/test/run_gc.sh) | 시행 하나: 노드마다 그 시행의 launcher, 기록한 PID에만 주입, 노드 시계 차, `ss` 스냅숏 |
| [impl/test/launcher_gc.sh](impl/test/launcher_gc.sh), [impl/test/remote_gc.sh](impl/test/remote_gc.sh) | 노드 하나의 launcher 시작과 정지, sunny 원격 명령의 따옴표 |
| [impl/test/run_cost_gc.sh](impl/test/run_cost_gc.sh) | 비용 셀 하나 |

smoke 1–5는 저장소 밖 스크래치의 실행 스크립트가 `cells_gc.sh` → `run_gc.sh`를 불렀다(smoke마다 `SMOKE.md` 머리).

## 본 실행 (2026-11-18)

- 배포: `deploy_gc.sh`로 묶음 `gc_main1`(라이브러리 gc `ed13666b`, gcp `55ffb80e`, gct `df1d091b`, driver 다섯, launcher `d1aceaf6`; md5는 `PREREG.txt`)을 두 노드 `~/rs-bundle/gc_main1/`에 두었다(`results/20261118_main/run/deploy.txt`, `md5_both_nodes.txt`).
- 실행: `results/20261118_main/run/run_main.sh <pass> <hold>...`가 `chain_gc.sh`를 `cluster_run.sh` 안에서 불렀다. hold 24개를 세 pass로 돌렸고(`run/attempts.txt`, `run/chain.out`), 840 s 한도로 건너뛴 시행은 같은 hold를 다시 돌려 채웠다(`run/skipped.txt`는 셀마다 첫 줄만). STOP_left 둘은 `run/stops/`에 있고 원인은 EXPERIMENT.md 16절이다.
- 채점: `python3 impl/test/score_gc.py <결과 폴더>`(결과 폴더에 `raw/`, `reg/`, `cost_probe_*/`). 출력 `SCORE.md`, `trials_scored.csv`는 `results/20261118_main/`에 있고 원자료는 Release `data-20261118`에서 같은 경로로 풀린다.
- QA: 독립 재집계 `results/20261118_main/qa_recount.md`(스크립트 `qa/`), 원인 조사 `qa_findings.md`.

## 채점

- [impl/test/rows_gc.py](impl/test/rows_gc.py) `<결과 폴더> [--out trials.csv]`: 원자료에서 시행마다 한 행. `--stops <stem>`은 hold의 launcher STOP 검사.
- [impl/test/score_gc.py](impl/test/score_gc.py) `<결과 폴더>`: 예측 표를 적용해 `SCORE.md`와 `trials_scored.csv`를 쓴다. smoke와 pilot 시행은 따로 세고 채점하지 않는다.
- 판정식은 3절, 제외는 8절, 독립 재계산과 QA 기준은 10절.

## 머리 주석이 문서와 어긋난 곳 (2026-10-23 확인, 고치지 않음)

- `run_gc.sh`, `deploy_gc.sh`, `run_cost_gc.sh`의 머리 주석은 2026-10-22 셀 줄임으로 쓰는 셀이 없어진 빌드 `gctc`, `gctp`(비용 tcp 팔 포함)를 아직 적는다.
- `deploy_gc.sh`의 "driver의 gc 사본은 이 배달물에 없다"는 TODO는 그 뒤 생긴 `impl/test/driver/build_driver_gc.sh`보다 앞선 글이다.
