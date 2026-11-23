# v1: 1차 작업의 기록 (2026-09 – 2026-11-18)

RDMA 장애 정보가 NIC에서 application까지 어디서 남고 어디서 사라지는지에 대한 1차 측정. 현재 작업은 [`../v2`](../v2).

| 경로 | 내용 |
|---|---|
| [`MODEL.md`](MODEL.md) | 장애 전파 규칙 5가지 |
| `harness/` | CPU verbs 장애 측정, 감지 시간(`ack_timeout/`), 종료 순서(`teardown_order/`), 오판 측정(`live_peer/`) |
| `harness/gpu-initiated/` | GPU가 직접 보내는 스택(NCCL GIN, NVSHMEM)의 장애 전파 측정, NVSHMEM #117 원인 분석(`nvshmem_rootcause/`) |
| `harness/nccl-integration/`, `harness/blind/`, `harness/gpu-detect/` | NCCL 장애 분류, 실제 application blind test, 호출 밖 장애 감지의 측정 결과 |
| `experiments/`, `docs/` | 초기 연구(다른 클러스터) |
| [`DATA.md`](DATA.md) | 원시 데이터 Release 목록과 체크섬 |
| [`ERRATA.md`](ERRATA.md) | 남은 문서의 틀리거나 낡은 대목 |

- 2026-11-23 정리에서 732개 파일 삭제: 쓸모없거나 틀린 파일 96개, 당시의 복구 구현(설계 문서와 패치) 636개
- 삭제한 내용은 그 전 커밋과 태그(`prereg/...`, `data-...`)에 보존
- 복구는 v2에서 release 소스로부터 재작성
- 사전 등록 실험 24건의 예측과 판정은 태그와 각 실험 폴더의 문서
- 스크립트의 주소는 문서용 예시 값
