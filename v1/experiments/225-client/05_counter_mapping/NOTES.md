# 05_counter_mapping: 상세 기록

이 문서는 예전 README 본문을 그대로 옮긴 것이다. 실행 방법도 여기에 있다. 요약은 [README.md](README.md)에 있다.

이 디렉토리는 한 쌍의 client/server 인프라(`common.h` 기반)를 공유하는 여러
실험이 모여 있다. 전부 225에서 `run*.sh`로 실행한다 (swap 제외, 아래 참고).

## 하위 실험 인덱스

| 실험 | 코드 | 스크립트 | 결과 | 상태 |
|---|---|---|---|---|
| 카운터 매핑 (장애별 오류 코드와 카운터 변화) | `client.c` + 224 `server.c` | `run_experiment.sh` | 종합: `results/counter_mapping_findings.md`. 시나리오별 `results/raw/<시나리오>.csv`는 저장소에 없음(아래) | 완료 — 9/10 시나리오 유일 식별 |
| ethtool 카운터 버전 | 〃 | `run_ethtool_experiment.sh` | `results/ethtool/`, 저장소에 없음(아래) | 완료 |
| 다중 조건 (MULTI_WR / MULTI_QP / LARGE_MSG) | `multi_client.c`, `multi_common.h`, 224 `multi_server.c` | `run_multi_experiment.sh` | `results/multi/`, 저장소에 없음(아래) | 완료 — 9/9 MATCH(27 trials) |
| 서버 QP 상태 검증 (NAK 후 responder QP가 정말 ERR인가) | `verify_qp_state.c` | `run_verify.sh` | `results/raw/qp_state_verify.csv` | 완료 — 시나리오 5개 × N=10. NAK 3종과 서버 QP ERR 뒤 ERR, RNR 뒤 RTS |
| MR 경계 partial write (경계 침범) | `verify_partial_write.c` | `run_partial.sh` | `results/raw/partial_write_verify.csv` | 완료 — bytes = sq_psn_delta × PMTU |
| mid-transfer interrupted write (전송 도중 QP→ERR) | `verify_interrupted_write.c` | `run_interrupted.sh` | `results/raw/interrupted_write_verify.csv` | 완료 — N=100(2026-06-02). silent 경로의 partial은 sq_psn으로 복원 안 됨(0/52) |
| A/B recovery (reactive 재전송 vs proactive 범위검사) | `ab_recovery.c` | `run_ab_recovery.sh` | `results/raw/ab_recovery.csv` | 완료 — 조합당 N=10000(2026-06-04). A recover 42.7 ms에는 TCP_NODELAY 누락 아티팩트가 섞여 재실행 필요. 상세: `README_ab_recovery.md` |
| 전략 C: silent partial write 대응 (commit-flag vs CRC32 vs read-back diff) | `silent_strategy.c` + 224 `server.c` | `run_silent.sh` | `results/raw/silent_strategy.csv` | 완료(2026-07-15). 상세: `README_silent_strategy.md`, `docs/experiments/07_silent_partial_strategy.md` |
| NIC 세대 swap (vendor_err 일반화) | 224의 `client.c` + 225의 `server.c` | `run_swap.sh` | `results/raw/vendor_err_summary.csv` | 완료 — 에러 종류별 N=10, vendor_err가 세대와 무관. 상세: `docs/theory/06_vendor_err_generalization.md` |

저장소에 없는 결과 표(시나리오별 `results/raw/*.csv`, `results/ethtool/`, `results/multi/`)는 태그
`archive/results-tables-20261006`(Release `data-20261006`의 `results-tables-20261006.tar.xz`)에 있다.

## 주의

- **swap 실험만 역할이 반대다**: `run_swap.sh`를 225에서 돌리면 server가 225(로컬,
  responder=CX-6), client가 224(SSH, requester=CX-5)에서 뜬다. 그래서 이
  디렉토리에는 225인데도 `server.c`가, 224인데도 `client.c`가 있다 — 잔여 파일이
  아니라 swap용이니 지우지 말 것.
- `common.h`는 `06_recovery/`도 include하는 공유 헤더다. 수정 시 그쪽 빌드도 영향받는다.
- 카운터 수집은 224의 `counter_daemon.sh`(sysfs 스냅샷 데몬,
  `224-server/05_counter_mapping/`)를 스크립트들이 SSH로 알아서 띄운다.
