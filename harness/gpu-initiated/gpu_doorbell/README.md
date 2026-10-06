# gpu_doorbell: GPU가 doorbell을 울릴 때 무엇이 바뀌나

2026-09-24 오후 전까지 다른 GPU 실험은 모두 CPU가 doorbell을 울리는 fallback 모드였다. GPU는 WQE를 쓰고 CQ를 읽지만,
NIC에 알리는 doorbell은 CPU 스레드가 울렸다. 여기서는 nvidia 드라이버의 PeerMappingOverride 설정을 켜서
GPU가 doorbell을 직접 울리게 하고, 같은 장애에서 NVSHMEM IBGDA와 NCCL GIN GDAKI가 어떻게 달라지는지 봤다.

## 무엇을 쟀나

- **짧은 시간 창 2개.** 2026-09-24 11:16–11:26(창 1)과 12:00–12:06(창 2)에만 설정을 켜고, 끝나면 되돌렸다.
  같은 날 13:53부터는 사용자 결정으로 두 노드에서 상시 켜져 있다.
- **NVSHMEM IBGDA, GPU NIC handler (창 2).** 로컬 QP 오류, 잘못된 rkey, 상대 QP 오류 각 3회,
  장애 없음 2회, 잘못된 rkey를 blocking quiet로 1회.
- **NCCL GIN GDAKI (창 1, 2).** 장치 분류 빌드(`../gin_q4/`)로 로컬 QP 오류, 원격 접근 오류(MR 밖 주소에 쓰기),
  상대 QP 오류, 장애 없음. 분류를 끈 stock으로 로컬 QP 오류 blocking 2회. 장애 없는 지연 측정.
- **조건.** rain과 sunny, ConnectX-6 RoCE, IB 타임아웃 14. CPU doorbell 때와 같은 바이너리와 실행기.

## 결론

- **NVSHMEM은 GPU handler에서 오류 CQE를 받는다.** 로컬 QP 오류, 잘못된 rkey, 상대 QP 오류 각 3/3회 CQ 슬롯에 원인 CQE가 있었다.
  - 로컬 QP 오류 WR_FLUSH 0x05/0xf5, 잘못된 rkey REM_ACCESS 0x13/0x88, 상대 QP 오류 RETRY_EXC 0x15/0x81 (syndrome/vendor_err).
  - CPU handler에서는 같은 장애에서 1024개 CQ 항목 어디에도 오류 CQE가 없었다(`../nvshmem/`).
  - 그래서 원인은 collapsed CQ가 아니라 CPU proxy doorbell 경로다. 정확한 원인은 `../nvshmem_rootcause/`에서 찾았다.
- **NVSHMEM blocking quiet는 실패를 성공으로 보고했다.** 잘못된 rkey blocking 1회에서 슬롯은 이미 뒤따른 flush
  0x05/0xf9로 덮였고, quiet는 성공을 돌려줬다.
- **GIN 분류는 doorbell 경로와 무관하다.** 로컬 QP 오류 LOCAL_QP_ERR 5/0xf5, 원격 접근 오류 REM_ACCESS 10/0x88,
  상대 QP 오류 RETRY_EXC 12/0x81로 모두 맞았다. 호스트가 아는 시간은 로컬 QP 오류와 상대 QP 오류에서
  CPU doorbell 결과와 같은 범위였다. 원격 접근 오류는 ring 4.3 ms, collapsed 3.8 ms(각 1회)로 CPU doorbell(2.8 ms, 3.2 ms)보다 0.6–1.5 ms 길었다. 원인은 확인하지 않았다.
- **stock GDAKI의 조용한 성공도 그대로다.** 로컬 QP 오류 blocking 2/2회에서 보내는 쪽이 실패한 쓰기를 완료로 셌다.
  호스트는 9.4 s 뒤 "QP가 ERR"만 알았다.
- **GPU doorbell 지연은 조금 낮았지만 근거가 약하다.** GIN 256 KiB put, signal, flush(timeout 대기) 중앙값이
  36.74 µs(분류 끔), 36.86 µs(켬)로, CPU doorbell의 약 37.4 µs보다 약 0.6 µs 낮다.
  각 1회 실행이고, CPU doorbell의 실행 간 편차(36.9–37.8 µs)와 거의 겹친다.

## 결과

| 스택 | 장애 | 결과 | 시간 |
|---|---|---|--:|
| NVSHMEM GPU handler | 로컬 QP 오류 | 0x05/0xf5, 3/3 | 1.7–1.8 ms |
| NVSHMEM GPU handler | 잘못된 rkey | 0x13/0x88, 3/3 | 8.7–9.9 ms |
| NVSHMEM GPU handler | 상대 QP 오류 | 0x15/0x81, 3/3 | 3.54–3.72 s |
| NVSHMEM GPU handler | 잘못된 rkey, blocking quiet | 슬롯 0x05/0xf9, quiet 성공 | - |
| GIN 분류 (ring 2, collapsed 1) | 로컬 QP 오류 | LOCAL_QP_ERR 5/0xf5 | 14.6–15.7 ms |
| GIN 분류 (ring 1, collapsed 1) | 원격 접근 오류 | REM_ACCESS 10/0x88 | 3.8–4.3 ms |
| GIN 분류 (ring 2, collapsed 1) | 상대 QP 오류 | RETRY_EXC 12/0x81 | 3.54–3.73 s |
| GIN stock | 로컬 QP 오류, blocking | 성공으로 보고 2/2 | 9.4 s |

NVSHMEM 시간은 post에서 장치 감지까지, GIN 시간은 장애에서 호스트 비동기 오류 조회까지다.
GIN 장애 없음(ring 2, collapsed 1)은 모두 정상이었고 데이터가 정확했다.

## 한계와 주의

- **창 1의 일부는 무효다.** 드라이버를 다시 올린 뒤 sunny의 CUDA가 깨졌다(장치 번호 불일치).
  창 1의 NVSHMEM 전부와 GIN 처음 5회는 버렸다. 표는 유효한 실행만 담았다.
- **GIN이 GPU doorbell을 썼다는 것은 추정이다.** NCCL과 DOCA가 doorbell 모드를 기록하지 않는다.
  같은 창에서 NVSHMEM의 doorbell 매핑이 성공했고 지연이 0.6 µs 낮다는 것이 근거다.
  모드를 기록하는 빌드는 나중에 `../gin_recovery/`에서 나왔다.
- **NVSHMEM 시간은 장애 시점 기준이 아니다.** post에서 감지까지다. 같은 GPU handler를 쓴 다른 측정
  (`../nvshmem_rootcause/` 3자 비교의 GPU handler 칸)은 로컬 QP 오류 2.0–2.3 ms, 잘못된 rkey 10.3–10.7 ms였다.
- **표본이 작다.** 칸마다 1–3회다. GIN 분류는 이후 GPU doorbell에서 칸마다 30회씩 다시 쟀다(`../gin_q4/`, `../N30_20260925.md`).
- **이 폴더에서 재지 않은 것.** 상대 프로세스 kill, GIN stock의 장애 세 가지(원격 접근 오류, 상대 QP 오류,
  상대 프로세스 kill), GIN proxy backend.
- **창 2의 NVSHMEM 잘못된 rkey 1회는 다른 실행과 15 s 겹쳤다.** 복구 작업의 짧은 시험 실행이었다. 오류 CQE는 나머지 2회와 같았다.
- **설정은 노드의 보안 범위를 넓힌다.** PeerMappingOverride는 관리자 전용 검사 없이 다른 장치의 MMIO를 GPU에 매핑하게 한다.
  노드의 어느 CUDA 프로세스든 매핑할 수 있는 범위가 넓어진다. 두 노드는 공유 노드이고, 사용자가 상시 켜 두기로 했다.
  09-24 13:53 이전 결과와 이후 결과는 doorbell 경로가 다르다.

## 파일

| 파일 | 내용 |
|---|---|
| [NOTES.md](NOTES.md) | 상세 기록 (시간 창 절차와 사고 기록 포함) |
| 결과 폴더 | 저장소에 없다. 표와 로그(`results/20260924/`, `results/20260924_w2/`, 창 로그)는 모두 Release `data-20261006` |
| `../nvshmem_rootcause/` | NVSHMEM CPU proxy에서 오류 CQE가 없던 원인 |
| `../gin_q4/`, `../gin_recovery/` | GIN 분류의 30회 재실행, GPU doorbell에서의 복구 |
