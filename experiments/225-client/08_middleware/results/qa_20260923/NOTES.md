# qa_20260923: 상세 기록

이 문서는 예전 README 본문을 그대로 옮긴 것이다(영문). 빌드 방법과 로그 이름도 여기에 있다. 요약은 [README.md](README.md)에 있다.

> The `08_middleware` and `07_fault_classify` code this page tested (`rdma_conn.c`, `demo_client.c`,
> `demo_server.c`, `librdma_fault`) was removed from the tree on 2026-10-06; it is in tag
> `archive/results-tables-20261006`. The logs are in Release `data-20261006`.

Real-hardware check of the `rdma_conn.c` server control-channel fix (commit f942bdb),
run on the current cluster: rain (client, mlx5_1) and sunny (server, mlx5_0), RoCE v2.

## How the binaries were built

`05_counter_mapping/common.h` hard-codes the old cluster's constants, so the demo was
built from a **scratch copy** of `experiments/` with these overrides only (the repo is
unchanged):

| side | constant | repo value | value used |
|---|---|---|---|
| client (225) | `RDMA_SERVER_IP` | `"10.0.0.3"` | `"30.0.0.4"` |
| client (225) | `IB_DEV_NAME` | `"mlx5_0"` (port DOWN on rain) | `"mlx5_1"` |
| client (225) | `GID_INDEX` | `3` | `4` (rain's RoCE v2 IPv4 GID) |
| server (224) | `RDMA_SERVER_IP` | `"10.0.0.3"` | `"30.0.0.4"` |

`demo_server` was built on rain and copied to sunny's `/tmp`.

## Result 1: the four demo scenarios (`demo_4scenarios.log`)

| scenario | vendor_err | outcome | demo_client exit |
|---|---|---|---|
| rnr | 0x87 | QP recovery, resend succeeded | 0 |
| rem_access | 0x88 | QP recovery + MR refresh, resend succeeded | 0 |
| retry | 0x81 | peer probed, then recovered, resend succeeded | 0 |
| loc_prot | 0x53 | classified as an application bug, no auto-recovery (expected) | 0 |

In this demo the retry scenario is detected in about 3.7 s, which is under the 5 s
control-step timeout, so it does not exercise the idle-timeout bug.

## Result 2: the idle-timeout bug, before vs after the fix

To make the control channel stay idle longer than 5 s during detection, the scratch
client used IB timeout 18 (repo value 14) and a 30 s CQE wait (`CQ_TIMEOUT_MS`, repo value
12 s). RETRY_EXC detection then took about 12-14 s. The same client was run against two
servers: one built from `rdma_conn.c` before the fix (`f942bdb^`), one after.

| server | client outcome | exit |
|---|---|---|
| before the fix (`retry_t18_prefix_client.log`) | `[recover] peer 사망(escalate)`: a live peer was declared dead | 1 |
| after the fix (`retry_t18_fixed_client.log`) | `[recover] OK(복구+재전송 완료)`, resend succeeded | 0 |

Before the fix the server's serve loop returned after 5 s of control-channel idleness,
so when the client probed after detection the server was gone. After the fix the
server keeps serving while idle and completes the recovery.

The link was otherwise idle during these runs: no gdsio / NVMe-oF benchmark traffic
(sampled every 5 s).
