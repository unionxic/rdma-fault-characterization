# notes_pilot1fix.md: tcp 빌드의 전처리 동일성 고침 (2026-10-23, pilot 1)

표시: `[측정]` 출력에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석.

## 무엇

[gc_layer_pilot1fix.diff](gc_layer_pilot1fix.diff)(md5 `ac764734`, `39545f5` 대비): `gin_host_gdaki.cc`의 `gdakiMiUserCtxOf` 정의(ctxall이 더함, 고친 뒤 35230–35235행) 앞뒤에
`#if !NCCL_GIN_CTRL_TCP`와 `#endif` 두 줄을 넣었다. 다른 바꿈은 없다. 스크래치 트리 `agent_gc_p2a2/nccl-src`의 커밋 `725254b`
"gin-control: guard gdakiMiUserCtxOf for the tcp build"(작성자 build). [gc_layer_int.diff](gc_layer_int.diff)는 ln4 커밋 `f53e5d2` 대비 patience diff로 다시 냈다:
md5 `f4819515` → `1b0a40c8`, 거꾸로 적용 검사 통과 `[측정]`.

## 왜

pilot 1의 첫 `pre` 단계에서 `gct`(`-DNCCL_GIN_CTRL_TCP=1`)의 호스트 파일 전처리 결과가 ln4와 정규화 뒤 1 hunk, 6줄 달랐다(`gctp`도 같은 hunk) `[측정]`.
그 6줄이 이 정의다. 전방 선언과 부르는 곳(`gdakiCtrlDevCtxCount`)은 이미 tcp 스위치 뒤에 있어서, tcp 빌드에서는 부르는 곳 없는 정의만 남았다 `[소스]`.
EXPERIMENT.md 빌드 키 표와 9.8, 10절은 `gct`의 전처리 결과가 ln4와 같기를 요구한다. ctxall 전(`s7`까지)의 `pre` 로그는 모두 0 hunk였다 `[측정: logs_p2a2/pre_*.log]`.

## 고친 뒤 검사 (스크래치 사슬 `agent_gc_p2a2/chain_pf1.sh`, 로그 `logs_p2a2/*_pf1.log`)

| 단계 | 결과 `[측정]` |
|---|---|
| 빌드(컴파일만, 경고 0) | `gc_pf1` `cd4ee767eef3ce7a4c467e9caf2363bd`, `gct_pf1` `0e31fa0c4350ef968327c913e6752713`, `gcp_pf1` `5cffdcd6d80a22fe599c1b4b262a90fb`; `gctp`는 빌드 안 함(쓰는 셀 없음) |
| `pre` | `gct` 0 hunk, `gctp` 0 hunk, `gctc` 2 hunk 3줄(RST 간격 매개변수만, 9.8절대로), `gc`의 정규화 결과 md5 `fd96b323`는 고치기 전과 같음 |
| `sites` | 149행, 트리 밖 `#if NCCL_GIN_CTRL_TCP` 갈래 49개가 ln4 줄 그대로 |
| `api` | 통과 |
| `unit` | rdma와 tcp 모두 실패 0(예: `gc_unit_p1` 10 376 867 검사, `gc_unit_livectx` 1 078 020 검사, `gate_fenced` 10/10) |
| `ident` | 매크로 없는 프로그램 16/16이 ln4와 같음, 장치 객체 `gc`, `gct`, `gcp` 각 207/207이 SASS와 바이트까지 같음, 자원 사용 같음, 설치 헤더가 ln4와 같음 |

`gc`의 정규화 전처리가 그대로이므로 rdma 빌드의 동작은 바뀌지 않았다고 본다 `[추론]`. libnccl md5가 바뀐 것은 `__LINE__` 값이 두 줄 밀렸기 때문이다 `[추론]`.
