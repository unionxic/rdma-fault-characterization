# RDMA 장애 특성화와 복구

RDMA 통신에서 장애가 났을 때 그 정보가 NIC에서 application까지 전달되는지 측정하고, 전달되지 않는 곳을 고친다.
대상은 GPU가 직접 통신을 시작하는 NVIDIA NCCL GIN과 NVSHMEM IBGDA다.

| 폴더 | 내용 |
|---|---|
| [`v2/`](v2) | 지금 작업. NCCL v2.32.6-1과 NVSHMEM v3.8.0-0에 대한 패치, 재현 프로그램, 기록 |
| [`v1/`](v1) | 1차 작업의 기록(2026-09 – 2026-11-18). 장애 전파 측정과 사전 등록 실험 |

## 지금까지 (2026-11-23)

- **보고한 이슈 네 건을 고쳤다.** NVIDIA/nvshmem [#117](https://github.com/NVIDIA/nvshmem/issues/117),
  [#120](https://github.com/NVIDIA/nvshmem/issues/120), NVIDIA/nccl [#2483](https://github.com/NVIDIA/nccl/issues/2483),
  [#2480](https://github.com/NVIDIA/nccl/issues/2480). 실패한 요청이 이제 원인과 함께 application에 전달된다.
- **원인을 잃지 않는다.** 뒤따른 flush가 CQE의 원인을 덮어써도, NIC가 QP context에 보관하는 첫 오류를 읽어 되찾는다.
- **오류 분류의 근거.** 드라이버가 정의한 CQE syndrome 13개 중 10개를 재현했고, 두 라이브러리가 낼 수 있는 6개를 분류에 남겼다.
- **정상 경로 비용.** NCCL +0.1–1.2%, NVSHMEM +1–2%.
- **복구는 아직 없다.** 규칙만 제안한 상태다.

자세한 내용과 한계는 [`v2/README.md`](v2/README.md), 측정 기록은 [`v2/RECORD.md`](v2/RECORD.md).

환경: 노드 2개, ConnectX-6(펌웨어 20.43.4100) RoCE 직결. 구현과 문서 작업에 AI 코딩 도구(Claude Code)를 썼다.

[MIT](LICENSE). NCCL과 NVSHMEM에 대한 패치는 각 프로젝트의 라이선스를 따른다.
