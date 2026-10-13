# 손으로 하는 mirror의 비용: gin_ts2에 더할 팔 (실행 가능성 확인 2)

[../EXPERIMENT.md](../EXPERIMENT.md) 9.8절 확인 2를 시험 작업 묶음(9.8절 작업 묶음 표의 "시험과 비용")이 만들 수 있게 적은 명세다. 이 폴더는
gin_ts2를 고치지 않는다. 실행은 [run_mf.sh](run_mf.sh)의 `cm_*` 셀과 [hold_mf.sh](hold_mf.sh)의 `COSTMAN-*` hold가 하고, 읽기는
[summ_mf.py](summ_mf.py)가 한다. 채점하지 않는다.

## 무엇을 재나

application이 put 하나 뒤에 다른 GIN 문맥으로 같은 원본을 한 번 더 put하고 두 문맥을 모두 flush할 때, put 지연과 묶음 대역이 한 번 put보다
얼마나 나빠지는가. 판정은 없다. 장치 쪽 비용(측 표 읽기, lane 커서, 쉬지 않는 게이트)은 이 팔이 재지 않으므로 3절 초안 문턱 가운데 묶음 대역 비
0.40–0.60만 이 확인으로 받치고, 4 KiB 지연 문턱(+2.5 µs)은 pilot이 실제 장치 길로 잰다(9.8절, 커밋 `418e7bae`). 대역 비가 어긋나면 사전 등록 전에
문턱을 다시 정한다.

## 기준 driver와 빌드

- 소스: [../../gin_ts2.cu](../../gin_ts2.cu)(md5 `1779db9d`) + [../../restore/feas/gin_ts2_winflags.diff](../../restore/feas/gin_ts2_winflags.diff)(md5
  `fb9d2d8d`) + 이 문서대로 만든 새 diff. gin-restore 비용 셀의 driver와 같은 소스다 `[소스: ../../restore/impl/test/build_rs_test.sh 61–74]`.
- 빌드: 그 스크립트의 `cost` 단계와 같은 flag, 매크로 켬(`-DNCCL_GIN_RESTORE_DEVICE`), gin-restore 계층 헤더. 새 출력 폴더 하나.
- 라이브러리: `~/rs-bundle/i5/lib/rsp`(gin-restore 운영 빌드 `rsp_i5`, md5 `be91b270`; 읽기만).
- 배포: `CM_SRC=<빌드> WANT_MFCM=<md5> bash deploy_mf.sh <출력 파일> mfcm` → 새 디렉터리 `~/rs-bundle/mfcm/gin_ts2`.

## gin_ts2에 더할 것

줄 번호는 `gin_ts2.cu`(md5 `1779db9d`)의 줄이다 `[소스]`.

1. **환경 변수 `GIN_TS_MAN_MIRROR`**: 없음 또는 `off`(팔 `one`), `self`(팔 `man-self`), `peer`(팔 `man-peer`). rank 0의 모드 `lat`과 `burst`에서만
   켠다. 다른 모드, bidir, dual, get 모드에서 켜면 kv에 `man_error=` 한 줄을 쓰고 exit 2.
2. **둘째 put**: 첫 put 바로 뒤에 같은 스레드가 GIN 문맥 1(`ncclGin gin1{devComm, 1}`)로 같은 원본(sendWin, 같은 오프셋, 같은 바이트)을 put한다.
   원격 신호는 없다(`ncclGin_None`). burst 모드는 첫 put과 같은 coop(thread), scope, opt flag(aggregate)를 쓴다. 문맥 1은 dual 모드가 이미 쓰는 기본
   문맥이다 `[소스: 666–700]`.
   - `self`: 대상 rank 0 자신, 대상 window는 recvWin, 대상 오프셋은 첫 put의 대상 오프셋. 이 모드에서 rank 0의 recvWin은 쓰이지 않는다
     `[소스: 1059–1065, receiver만 씀]`.
   - `peer`: 대상 rank 1, 대상 window는 sendWin, 같은 오프셋. 이 모드에서 rank 1의 sendWin은 put의 대상이 아니다 `[소스: 1028–1045, sender만 채움]`.
   - window 크기는 바꾸지 않는다(rain BAR1: window 하나 24 MiB 이하, gin-restore 9.15.6).
3. **flush**: 반복마다 기존 flush(문맥 0) 뒤에 문맥 1의 flush를 같은 coop와 같은 시한 방식으로 부른다. 반복 시간(`lat[i]`, `lat0[i]`)이 두 flush를
   모두 덮고, 둘 중 하나라도 실패면 그 반복의 rc다.
   - lat 모드 `txBody`(357–397): put(+`WeakSignalInc`) → 둘째 put → flush(문맥 0) → flush(문맥 1).
   - burst 모드 `txBurstKernel`(542–591): K × (put_k, 둘째 put_k) → signal(문맥 0) → flush(문맥 0) → flush(문맥 1).
4. **`GIN_TS_BURST_REUSE=1`**(bw2m 셀만; burst 모드): slot 자리를 `((i * P + t) * K + k)` 대신 `(t * K + k)`로, 무늬를 `patW(0, t, k, w)`로 쓴다.
   보내는 쪽 채우기(1035), 받는 쪽 장치 검사(614), 호스트 검사(1622)가 모두 같은 규칙을 따른다. window는 P × K × bytes(2 MiB × 8 = 16 MiB)다.
   무늬가 반복마다 같아서 다음 반복이 slot을 덮어도 검사가 맞다.
5. **kv**(rank 0): `man_mirror=off|self|peer man_ctx=1 man_puts=<낸 둘째 put 수> burst_reuse=0|1`. rank 1: `burst_reuse=0|1`. summ_mf.py는
   `man_mirror`를 셀의 팔과 견주고(없으면 `off`로 읽음) 다르면 그 실행을 세지 않는다.
6. 선택: `peer` 팔에서 rank 1이 끝에 sendWin을 읽어 마지막 둘째 put들의 내용을 무늬와 견준다(`man_peer_bad_slots`).
7. `GIN_TS_MAN_MIRROR`가 없으면 기존 경로를 그대로 지난다(기존 kv 그대로, 팔 `one`).

## 실행

- 환경: gin-restore 비용 틀의 팔 `on`과 같다(로그 켬 측정 모드, checksum 끔, window strict, QP 감시 끔, `NCCL_GIN_NCONNECTIONS=1`)
  `[소스: ../../restore/impl/test/run_cost.sh]`. 세 팔은 `GIN_TS_MAN_MIRROR`만 다르다. 기준이 3절 비용 예측의 `on` 팔과 같다.
- 셀 `cm_<지표>_<팔>_<받는 노드>`:

  | 지표 | 모드 | 반복 | put 크기 | 값 |
  |---|---|---|---|---|
  | `lat4k`, `lat256k`, `lat2m` | lat | 3 000 | 4 KiB, 256 KiB, 2 MiB | rank 0의 `lat_p50_us` |
  | `bw256k` | burst, 스레드 하나, K = 8 | 12 | 256 KiB | K × bytes / `lat_p50_us` |
  | `bw2m` | burst, 스레드 하나, K = 8, slot 다시 씀 | 24 | 2 MiB | 같음 |

- hold: `COSTMAN-<rain|sunny>-<지표>` 하나가 6라운드 × 팔 셋 = 18실행이다. 라운드마다 팔 순서를 `one, man-self, man-peer`와 그 거꾸로 번갈아 쓴다(gin-restore
  9.15.6의 섞기). 노드 둘 × 지표 다섯 = hold 열.
- 읽기: 팔마다 유효 실행(두 rank exit 0, 설정 일치, `man_mirror` 일치)의 중앙값, `one`과의 차이(지연)나 비(대역). `man-peer`의 대역 비만 초안
  0.40–0.60과 나란히 찍고, 지연 차이는 보고만 한다.

## 두 팔이 무엇을 묶나 `[추론]`

- `man-self`는 보내는 NIC의 루프백이다. 원본을 GPU에서 두 번 읽고 선 위 바이트는 그대로다. 4-rank 배치에서 노드를 건너는 put의 mirror(짝이 보내는
  rank와 같은 노드)와 같은 꼴이다(EXPERIMENT.md 5절).
- `man-peer`는 받는 노드로 두 배를 보낸다. 같은 노드 안 put의 mirror와 같은 꼴이다.
- 실제 mirror와 다른 점: (가) 실제 mirror는 짝의 호스트 pool에 쓰지만 이 팔은 GPU window에 쓴다(받는 쪽 PCIe 대상이 다름; 호스트 쪽 시간은 확인 3이
  잰다). (나) 둘째 put은 둘째 게이트 진입, 로그 항목, 문맥 1 flush 고리를 치르고, 실제 mirror의 장치 몫(측 표 읽기, lane 커서 원자 더하기, 쉬지 않는
  게이트, rkey 다시 읽기)은 치르지 않는다. 그래서 이 팔의 지연은 실제 mirror의 지연을 어느 쪽으로도 묶지 못하고 대역 비만 받친다(9.8절). (다) 9.8절 원문의 "셋째 rank의 window"는 2-rank 틀에서 만들 수 없어 두 팔로 위아래를 묶는다.

## 미확인

- `[미확인]` GDAKI에서 자기 rank로의 GIN put(`self`)이 이 빌드에서 받아들여지는지. 9.2절은 자기 루프 QP가 있다고 읽었다 `[소스: rs 트리 16735–16756]`.
  안 되면 `man-self`는 빼고 그 사실을 12절에 적는다.
- `[미확인]` 기본 devComm의 GIN 문맥 수가 이 환경 변수 조합(`NCCL_GIN_NCONNECTIONS=1`, 측정 모드)에서도 2 이상인지. driver가 시작할 때 문맥 수를 kv에
  적고 2 미만이면 exit 2로 끝나게 한다.
