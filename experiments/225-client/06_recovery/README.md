# 06_recovery — 에러 유형별 recovery 비용 측정

NAK/에러 유형별로 fault를 일으킨 뒤 QP-only recovery(RESET→INIT→RTR→RTS,
PSN 재협상 포함)의 비용과 동작을 측정한다. 공통 recovery 코드는
`recovery_common.h`에 있고, 각 하위 디렉토리는 client(225)/server(224) 한 쌍이다.

수치 요약과 해석은 **`recovery_results_summary.md`** (canonical) 참고.
핵심 결과: QP-only 2.8ms / full rebuild 9.6ms / driver reload 7.9s.

| 디렉토리 | fault | 비고 |
|---|---|---|
| `REM_ACCESS_ERR/` | 잘못된 rkey/주소로 WRITE → 원격 NAK | |
| `REM_INV_REQ/` | 지원 안 되는 opcode 등 invalid request NAK | |
| `RETRY_EXC_ERR/` | 서버 QP→ERR로 재시도 소진 | `early_detect/`: 카운터 기반 조기 감지(roce_adp_retrans 18.4ms에서 감지) 후 선제 recovery |
| `RNR_RETRY_EXC/` | RQ에 WQE 없음 → RNR NAK 소진 | QP-only vs full rebuild 비교 재실행 대기 |
| `multi_qp/` | QP 2개(QP_A, QP_B). isolation은 QP_B에만 fault, concurrent는 두 QP에 서로 다른 fault | isolation(다른 QP 영향 0%) + per-QP 식별은 CQE만 가능(카운터는 port-level) |

실행: 각 하위 디렉토리에서 `./run.sh` (225에서; 224 server는 스크립트가 SSH로 관리).
