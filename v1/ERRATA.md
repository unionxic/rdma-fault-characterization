# v1 정오표

2026-11-23에 v1 전체(1,560개 파일)를 다시 읽어 정리한 결과다. 지운 것은 732개다: 쓸모없거나 틀린 파일 96개와, 옛 복구
구현(설계 문서와 패치, `gin_recovery/` 전체) 636개. 목록은 이 커밋의 삭제 내역에 있고, 내용은 그 전 커밋과 태그에 남아 있다.
여기에는 **남겨 둔 문서 안의 틀리거나 낡은 대목**을 적는다. 본문은 고치지 않았다. 사전 등록된
파일과 그 판정 기록을 바꾸지 않기 위해서다.

- 줄 번호는 이 폴더로 옮긴 시점 기준이다.
- "v2 기록"은 [`../v2/RECORD.md`](../v2/RECORD.md) 4절(오류 분류의 근거)이다.
- 검토는 파일 전체를 한 줄씩 읽은 것이 아니라 오류 코드, 원인 분류, 이슈 상태에 관한 서술을 찾아 대조한 것이다. 아래
  목록에 없다고 해서 맞다는 뜻은 아니다.

## 여러 문서에 되풀이되는 것

| 서술 | 왜 틀렸거나 낡았나 |
|---|---|
| "collapsed CQ에서는 원인이 사라진다", "오류 코드가 없어졌다" | CQ 칸에서만 사라진다. NIC는 QP마다 첫 오류를 QP context에 보관하고, 뒤따른 flush가 그것을 지우지 않는다(v2 기록). |
| "status와 vendor_err만으로 복구 방법을 정할 수 있다", "오류 NAK를 받았으면 상대가 살아 있다" | 상대가 죽어도 `0x13/0x88`과 `0x15/0x81`이 나온다. 생사는 따로 확인해야 한다([`MODEL.md`](MODEL.md) 94–108줄, v2 기록). |
| "구분되는 원인 9가지(10개 중 9개)" | 넣어 본 장애를 묶은 목록이다. v2는 드라이버가 정의한 CQE syndrome 13개를 기준으로 다시 잡았다(v2 기록). |
| "process kill은 0x81을 준다" | 종료 순서에 따라 `10/0x88`도 나온다(`docs/theory/README.md` 16줄, `MODEL.md` 105–108줄). |
| "NVIDIA의 #117 수정은 아직 공개되지 않았다" | 수정이 NVSHMEM devel 브랜치에 공개됐다. release 3.8.0에는 없다(v2 기록 3절). |
| vendor_err 값을 "rdma-core 표"로 분류한다는 서술 | vendor_err는 드라이버 헤더에 정의가 없다. 값의 뜻은 이 프로젝트가 측정으로 정한 것이다(v2 기록). |

## 문서별

| 파일 | 줄 | 내용 |
|---|---|---|
| `MODEL.md` | 15, 225 | "뒤따른 flush만 보는 코드에서는 원인이 뭉개진다"는 QP context 조회가 알려지기 전의 서술이다. |
| `docs/experiments/README.md` | 21–23, 36 | 위의 되풀이 항목(오류 코드만으로 결정, 9/10 구분). 36줄의 link down N=100은 `docs/theory/04` 29–33줄과 어긋난다. |
| `docs/experiments/NOTES.md` | 27, 35 | 같은 이유. |
| `docs/experiments/01_*.md` | 19, 21, 99, 110 | 99줄의 "커널 정리" 설명은 `harness/ack_timeout/NOTES.md` 34–43, 63–67줄이 대체했다. 21줄의 N=1은 `EXPERIMENT1_RESULTS.md` 71줄(N=100)과 다르다. |
| `docs/experiments/06_*.md` | 6.3절 | 스케줄러 설명은 `harness/gpu-initiated/cqe_seq/README.md` 75줄이 의문을 제기했다. |
| `docs/theory/03_*.md` | 18, 50, 101 | kill/0x81 서술. "status 14개"는 v2의 13개 기준과 맞춰지지 않았다. |
| `docs/theory/04_*.md` | 28–33, 43, 47, 131, 135 | kill/0x81, 원인 6→8→9개 서술, "응답 쪽은 `ibv_query_qp` 없이는 알 수 없다"(응답 쪽에는 비동기 이벤트가 온다). |
| `docs/theory/05_*.md` | 71–75, 115–117 | "`req_cqe_flush_error`는 이름이 잘못됐다"는 `0xf5` 한 경우에서 일반화한 것이다. 이 카운터는 `0xf9`를 센다. |
| `docs/theory/08_*.md` | A.3 | "link down은 효과가 없다"는 응답 쪽 link down 실행과 어긋난다. |
| `docs/theory/README.md` | | 지운 `07`에서 가져온 요약 항목이 남아 있다. |
| `experiments/225-client/06_recovery/README.md` | 12, 26–27, 30 | NAK면 상대가 살아 있다는 서술. |
| `experiments/224-server/06_recovery/REM_INV_REQ/server.c` | 38, 45 | 주석이 같은 파일 56–59줄과 어긋난다. |
| `experiments/225-client/05_counter_mapping/README.md`, `counter_mapping_findings.md` | 21 / 105, 247, 330, 8절 | 9/10 구분 틀. |
| `experiments/224-server/01_cpu_baseline/EXPERIMENT1_RESULTS.md` | 14 | 노드 225를 ConnectX-5로 적었다. |
| `harness/NOTES.md` | 86, 250–252 | 86줄의 111/192는 smoke kill을 포함한 수다(kill 270회만 세면 111/190). 250–252줄의 "0x81 외에는 (status, vendor_err)가 모두 고유"는 틀렸다(`5/0xf5`가 두 장애에서 나온다). 같은 파일 6줄이 이미 바로잡았다. |
| `harness/teardown_order/NOTES.md` | 311 | 제안 규칙이 `5/0xf5`를 `0xf9`처럼 "원인 아님"으로 다룬다. `0xf5`는 로컬 QP가 오류 상태라는 원인이다. |
| `harness/nccl-integration/NOTES.md` | 125, 157 | "Stock control" 표기가 틀렸다(패치된 라이브러리에 옵션만 끈 것). 같은 파일 5–10줄이 바로잡았다. |
| `harness/nccl-integration/stage2/gid_blackhole.sh`, `run_tests.py` | 머리 주석 / MASKED 판정 | 낡았다(`harness/gpu-initiated/propagation/review_20261006/nccl_netib_design.md` 147줄). |
| `harness/gpu-initiated/README.md` | 35, 97–98 | 원인을 잃는다는 서술, 낡은 "진행 중" 상태. |
| `harness/gpu-initiated/RESULTS.md` | 35, 47, 60, 123–124, 183–184 | 35줄 "next_rcv_psn = 실행된 앞부분"에 조건이 빠졌다. 47, 60줄의 1.8 ms와 9 ms는 장애부터가 아니라 post부터 감지까지다. 123–124줄은 과장이다. 183–184줄은 #117 상태가 낡았다. |
| `harness/gpu-initiated/N30_20260925.md` | | 09-25 06:45의 펌웨어 command slot 누수가 빠져 있다(`README.md` 93–95줄). |
| `harness/gpu-initiated/gin/NOTES.md`, `gin_q4/NOTES.md`, `nvshmem/NOTES.md` | 본문 | 옛 README 본문에, 머리말이 이미 바로잡은 서술이 남아 있다. |
| `harness/gpu-initiated/gin/results/20260923/gin_results_v1.csv` | F1–F4 행 | 철회된 첫 실행의 행이다. 기준선(fault=none) 행만 쓰인다. |
| `harness/gpu-initiated/cqe_seq/README.md`, `NOTES.md` | 23 / 37 | "오류 코드가 없어졌다"는 CQ 칸에 한한다. |
| `harness/gpu-initiated/nvshmem_ft/README.md` | 20–23, 92 | CQ 칸 서술, 92줄의 "진행 중"(이후 `t1_close`, `t1_380`에서 끝났다). |
| `harness/gpu-initiated/nvshmem_ft/NOTES.md` | 42, 57–58, 77 | 57–58줄 "살아남은 PE 모두에서 finalize 반환"은 같은 파일 6줄이 바로잡았다. |
| `harness/gpu-initiated/nvshmem_ft/DESIGN.md` | 39–40, 54–58 | rdma-core 표 서술, QP context 조회 이전의 전제. |
| `harness/gpu-initiated/nvshmem_ft/V2.md`, `results/20260925_v2/summary_v21.md` | 993 / 3 | "최종 빌드 = `nvshmem_ibgda_ft_v2.diff`"는 낡았다(커밋된 것은 v2.2). V2.md의 과장은 `NOTES.md` 9–12줄에 정리돼 있다. |
| `harness/gpu-initiated/nvshmem_rootcause/README.md`, `official380/README.md` | 60 / 44 | #117 수정 상태. |
| `harness/gpu-initiated/nvshmem_rootcause/NOTES.md` | 298–299 | "원인이 이미 사라졌다"는 CQ 칸에 한한다. |
| `harness/gpu-initiated/nvshmem_rootcause/UPSTREAM_ISSUE_EVIDENCE.md` | 63–64, 145 | "Expected: quiet가 약 3.7 s 뒤 반환"은 API 수준에서는 조용한 성공이다. `NOTES.md` 7줄이 바로잡았다. |
| `harness/gpu-initiated/nvshmem_rootcause/official380/NOTES.md` | 66 | "클러스터에서 아직 안 돌림"은 낡았다(`teardown_channel/`에서 돌렸다). |

## 정리 뒤 남은 어긋남

- 지운 파일을 가리키던 Markdown 링크 67개는 글자만 남기고 "(v1 정리에서 삭제)"를 붙였다. 표의 행이나 본문의 파일 이름
  언급은 그대로여서, 없는 파일 이름이 남아 있는 곳이 있다.
- `prereg/...` 태그와 Release archive 안의 경로는 `v1/`이 붙기 전 경로다([`DATA.md`](DATA.md) 머리말).
- 원자료를 가리키는 링크 가운데 저장소에 없는 것(Release에만 있는 `raw/` 등)은 원래부터 그랬다.
- 2026-11-23에 스크립트와 문서 66개에서 데이터 망 주소(점 표기, GID 표기, 정규식 표기)와 옛 클러스터의 계정 이름·hostname을
  문서용 예시 값(`198.51.100.x`, `203.0.113.x`, `user`, `node-224/225`)으로 바꿨다. 그래서 스크립트를 그대로 돌리려면 주소를
  자기 환경 값으로 넣어야 한다.
- 남은 문서 여러 곳이 지운 복구 구현(`gin_recovery/`, 복구 패치, 복구 설계 문서)을 이름으로 가리킨다. 그 결과 수치의 근거
  파일은 이 폴더에 없고 Release와 옛 커밋에만 있다.
