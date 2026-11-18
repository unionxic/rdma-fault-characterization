# notes_gcpsumfix.md: gcp 빌드의 READ 요약 줄을 WARN으로 (2026-10-23, pilot 1 문제 6)

표시: `[측정]` 출력에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석.

상태: **코드 수정 완료 / 로컬 검증 완료 / 하드웨어 검증 대기**

## 무엇

[gc_layer_gcpsumfix.diff](gc_layer_gcpsumfix.diff)(md5 `0ce1c954`, `725254b` 대비, 3줄 바꿈, 줄 수 그대로): `gin_host_gdaki.cc`에서
- READ 요약 줄(`probe summary`, `gdakiCtrlProbeSummary`)의 `GIN_TS_NOTE(`를 `WARN(`으로,
- status page 줄(`status page up`)의 `GIN_TS_NOTE(`를 `WARN(`으로 바꾸고,
- 요약 함수 위 주석 한 줄에 "WARN in every build"를 더했다.

형식 문자열과 인자는 그대로다. 스크래치 트리 `agent_gc_p2a2/nccl-src`의 커밋 `e791639` "gin-control: gcp prints the probe summary at WARN"(작성자 build).
[gc_layer_int.diff](gc_layer_int.diff)는 ln4 커밋 `f53e5d2` 대비 patience diff로 다시 냈다: md5 `1b0a40c8` → `393ed485`. 두 diff 모두 거꾸로 적용 검사 통과 `[측정]`.

## 왜

- `GIN_TS_NOTE`는 `NCCL_GIN_TS_PRODUCTION`이 있으면 `INFO(NCCL_NET, ...)`, 없으면 `WARN(...)`이다 `[소스: gin_host_gdaki.cc 86–90행]`.
  `gcp`만 이 매크로를 켜므로(`build_gc.sh`의 `gcp) lib build-gcp ... "-DNCCL_GIN_TS_PRODUCTION"`) 요약 줄이 INFO로 갔다. `NCCL_GIN_CTRL_PAGE`나 probe 전용 조건문은 이 줄을 가르지 않는다. 두 줄 모두 `#if !NCCL_GIN_CTRL_TCP` 구역(19890–22284행) 안에 있을 뿐이다 `[소스]`.
- **요청보다 한 줄 더 바꿨다.** `rows_gc.py`의 비용 probe-on 증거(`cost_probe_evidence`)는 요약 줄(`PROBESUM`)과 함께 status page 줄(`PAGEUP`: `probe_ms=`, 시작 시각)도 읽는다. 이 줄이 없으면 `r<k>:p<peer>:no_time`이 된다 `[소스: rows_gc.py 1522–1525행]`.
  status page 줄도 같은 매크로라 `gcp`에서 INFO였으므로 함께 WARN으로 바꿨다. 다른 `GIN_TS_NOTE` 줄은 그대로다.
- `run_cost_gc.sh`는 `NCCL_DEBUG=WARN`이다 `[소스: 87행]`.

## 고친 뒤 검사 (스크래치 사슬 `agent_gc_p2a2/chain_sf1.sh`, 로그 `logs_p2a2/*_sf1.log`)

| 단계 | 결과 `[측정]` |
|---|---|
| 빌드(컴파일만, 경고 0) | `gc_sf1` `c128c4c891555f194240d371410c7f68`, `gcp_sf1` `60e5a9f7b219493e0f6430d8f66de8ca`, `gct_sf1` `8ea3e598f9f77122738aabee7e189393`; `gctp`는 빌드 안 함(쓰는 셀 없음) |
| `syn`, `api` | 통과 |
| `pre` | `gct` 0 hunk, `gctp` 0 hunk, `gctc` 2 hunk 3줄(이전과 같음). `gc`의 전처리 결과는 원본 md5 `487b3372`, 정규화 md5 `fd96b323`로 고치기 전(`pf1`)과 같음 |
| `gcp` 전처리(따로 돌림, `gctp.cmd`에서 tcp 정의를 뺌) | 두 줄 모두 `ncclDebugLogInternal(NCCL_LOG_WARN, NCCL_ALL, ...)`. 파일 경로와 `__LINE__`을 가린 뒤 `gc`와 같음(요약 줄 md5 `61141460`, status page 줄 md5 `ae6c7d6d`가 두 빌드에서 같음) |
| `sites` | 149행, 트리 밖 `#if NCCL_GIN_CTRL_TCP` 갈래 49개가 ln4 줄 그대로 |
| `unit` | rdma와 tcp 모두 실패 0. "0 failed" 줄 34개로 `pf1`과 같음(예: `gc_unit_livectx` 1 078 020 검사) |
| `ident` | 매크로 없는 프로그램 16/16이 ln4와 같음. 장치 객체는 `gc`, `gct`, `gcp`, `gctp` 각 207/207이 SASS와 바이트까지 같음. 자원 사용 같음, 설치 헤더 ln4와 같음. 로그가 태그를 빼면 `ident_pf1`과 같음 |

- `gc`의 전처리 결과가 바이트까지 그대로이므로 rdma research 빌드의 동작은 바뀌지 않았다 `[추론]`.
  `gc` libnccl이 `pf1`(`cd4ee767`)과 34바이트 다른 것은 라이브러리에 박힌 커밋 해시(2곳)와 build-id 차이로 본다 `[추론]`.
- 장치 코드는 0줄 바뀌었다.
- `gcp`의 나머지 정보성 줄은 여전히 INFO다.
- 하드웨어에서 비용 probe-on 팔이 요약 줄을 남기는지는 아직 보지 않았다 `[미확인]`.
- kernel 창이 `PROBE_MS`보다 짧은 문제(PILOT.md 문제 6의 둘째 항목)는 이 고침의 범위 밖이다.
