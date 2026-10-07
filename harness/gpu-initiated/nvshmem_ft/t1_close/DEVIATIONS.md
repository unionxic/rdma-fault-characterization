# t1_close: 사전 등록 이후 변경

사전 등록은 태그 `prereg/nvshmem-t1-close-v1`(커밋 `9cdc27a5`, 2026-10-07 18:57:27 +0900)이다. 아래 변경은 모두 그 뒤에 했다.
[predictions.csv](predictions.csv), [PREREG.txt](PREREG.txt), [EXPERIMENT.md](EXPERIMENT.md)의 2, 3, 7, 8절은 바꾸지 않았다.

표시: `[측정]` 원자료에서 확인, `[소스]` 코드에서 확인, `[추론]` 해석.

## 1. finalize 없는 종료에서 FT 감시 스레드도 join한다 (빌드 b2)

- **시각:** 2026-10-07 19:07(결정과 수정), 19:09:07(배포 끝).
- **무엇을:**
  - 라이브러리 atexit 훅이 투명 복구 helper를 join한 뒤 FT 감시 스레드도 멈추고 join한다(`ibgda.cpp`, 한 곳).
  - 이 빌드(b2)를 새 묶음 `~/gi-bundle/nvshmem_t1close_b2`에 배포했다.
    - md5: transport `b4b4115e`, host `3d630308`(그대로), `nvt1_drv` `278089a4`.
  - 9절에 적은 묶음 `~/gi-bundle/nvshmem_t1close`에는 첫 빌드 b1(transport `31fa3a87`, `nvt1_drv` `d4b78b17`)이 남아 있다.
    b1은 smoke 1에만 쓰였다. 기존 묶음 파일은 어느 것도 바꾸지 않았다 `[측정]`(`deploy.sh`의 앞뒤 md5 비교: rain과 sunny 모두 0건).
- **이유:**
  - smoke 1의 finalize 없는 종료 시행에서 두 PE가 모두 `ATEXIT helper=joined join_ms=2.1`을 찍었다.
  - 그 뒤 "terminate called without an active exception"으로 abort했다(rc 134/255) `[측정]`.
  - 원인은 FT v1 감시 스레드다. 정적 객체 `ibgda_ft`의 `std::thread` 멤버이고, join되지 않은 채 정적 소멸자가 돌면 `std::terminate`를 부른다 `[소스]`.
  - 이 셀이 시험하는 장치(finalize 없이 끝날 때 라이브러리 스레드를 정리하는 훅)가 빠뜨린 스레드다.
- **영향:**
  - 본 실행의 모든 칸은 b2로 돈다. 채점기는 b2 md5를 기준으로 한다(8절의 빌드 확인).
  - finalize 없는 종료 칸(N7)의 예측과 판정 규칙은 그대로다. ATEXIT 줄 형식도 그대로이고, `join_ms`에는 감시 스레드 join 시간이 더해진다.
  - 9절의 `nvshmem_t1close`는 본 실행에서 `nvshmem_t1close_b2`로 읽는다.
- **어떤 자료를 본 뒤인가:** smoke 1(채점 제외)의 finalize 없는 종료 시행 하나를 본 뒤 정했다. 본 실행 자료는 없을 때다.

## 2. smoke를 두 번 했다

- **시각:** smoke 1 2026-10-07 19:05:35–19:06:59(b1), smoke 2 19:10:43–19:12:07(b2). 본 실행은 19:21:22에 시작했다.
- **무엇을:** smoke 1은 `results/20261007_smoke/smoke/`, smoke 2는 `results/20261007_smoke/b2/smoke/`. 둘 다 채점하지 않는다.
- **이유:** 1의 수정으로 빌드가 바뀌어, 본 실행 전에 같은 smoke를 b2로 다시 돌렸다.
- **영향:** 없음(채점 제외).
- **어떤 자료를 본 뒤인가:** smoke 1을 본 뒤.

## 3. 실행 방법의 세부 (사전 등록에 없던 구현)

- **시각:** 2026-10-07 19:00–19:05, smoke 1 전.
- **무엇을:**
  - 모든 hold는 `t1_close/hold.sh`로 돈다. hold 앞뒤로 rain dmesg 전체와 sunny dmesg 전체(`sudo -n dmesg`, sunny는 일반
    사용자에게 dmesg를 막아 둠 `[측정]`)를 남긴다.
  - 새 줄에서 mlx5 명령 오류(`mlx5`와 `cmd`/`command`와 `timeout`/`fail`/`error`/`leak`/`no done`이 함께 있고 FWTracer가 아닌 줄)를 센다.
  - `t1sock` iptables 규칙을 지우고 남은 수를 센다.
  - cluster 명령의 바깥 시간 상한은 9절 예시의 880 s 대신 900 s다(dmesg 수집 몇 초).
  - hold C의 v2 부분은 `STOP_AFTER_S=400`이다.
- **이유:** 8절의 중단 기준(두 노드 dmesg, iptables 확인)을 hold마다 기계적으로 하기 위해서다.
- **영향:** 판정 규칙과 셀은 그대로다.
- **어떤 자료를 본 뒤인가:** 측정 자료를 보기 전.
