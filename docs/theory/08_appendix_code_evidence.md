# 부록 A. 구현 함정과 코드 수준 증거

> [이론 문서 인덱스](README.md)

이 부록은 실험 코드를 구현하면서 마주친 함정들을 다룬다. 각 함정은 단순한 버그 수정이 아니라 RDMA subsystem의 동작에 대한 관찰이며, 재현성에 직결되므로 기록한다. 코드 라인 번호는 초기 연구 때 따로 복사해 둔 커널 소스(`kernel_src/mlx5_ib/cq.c`, `kernel_src/include/device.h`)에서 확인한 값이다. 그 복사본은 이 저장소에 없다. 커널 원본으로는 `drivers/infiniband/hw/mlx5/cq.c`와 `include/linux/mlx5/device.h`이고, 라인 번호는 커널 버전마다 다르다.

### A.1 MR 권한은 두 곳에 모두 설정해야 한다

RDMA WRITE가 서버에서 성공하려면 권한이 두 군데에 독립적으로 존재해야 한다.

| 위치 | 설정 항목 | 함수 |
|---|---|---|
| 서버 QP init 단계 | `qp_access_flags`에 `IBV_ACCESS_REMOTE_WRITE` | `ibv_modify_qp` (INIT 전이) |
| 서버 MR 등록 단계 | MR access flags에 `IBV_ACCESS_REMOTE_WRITE` | `ibv_reg_mr` |

둘 중 하나라도 `REMOTE_WRITE`가 빠지면 RDMA WRITE가 실패한다. 그런데 두 누락은 서로 다른 단계에서 거부되고, 서버 NIC의 responder pipeline에서 거부 시점이 다르다. 이것을 외부 관측으로 구분하는 방법이 서버측 `rx_write_requests` counter의 delta다.

`rx_write_requests`는 QP access capability check를 통과한 직후, MR-level 검증(rkey lookup, 주소 범위 확인) 이전에 카운트된다. 따라서:

| 누락 위치 | 거부 단계 | server `rx_write_requests` delta | 관측된 ibv_wc_status |
|---|---|---|---|
| QP `qp_access_flags`에서 `REMOTE_WRITE` 누락 | QP access check (Stage 1) | 0 | REM_INV_REQ_ERR |
| MR access flags에서 `REMOTE_WRITE` 누락 | MR/rkey check (Stage 2 이후) | +1 | REM_ACCESS_ERR |

구현 중 실제로 MR access flags에서 `IBV_ACCESS_REMOTE_WRITE`를 빠뜨려 모든 RDMA WRITE가 REM_ACCESS_ERR로 실패한 적이 있었다. 이때 어느 단계의 문제인지를 코드 추측 없이 서버 counter delta 하나로 즉시 판별했다 — delta가 0이면 QP access 단계, +1이면 그 이후 MR/rkey 단계. 이것은 4절에서 정리한 responder pipeline 역추론 기법(QP access check → `rx_write_requests` 카운트 → rkey 검증 → 주소 범위 확인)을 디버깅에 그대로 적용한 실증 사례다. counter 위치 자체가 진단 도구가 된다.

### A.2 GID table은 link 상태가 바뀌면 재구성된다

GID(Global Identifier)는 RoCE에서 사용하는 주소로, IP 주소와 NIC MAC을 조합해 만들어지며 table 형태로 관리되고 각 entry가 index를 가진다. 문제는 이 table이 link state 변경, IP 재할당, driver reload 같은 이벤트마다 재구성되면서 같은 GID가 다른 index로 이동한다는 점이다.

```
# ip link set down; ip link set up 실행 전
gid index 3: ::ffff:10.0.0.3   (IPv4-mapped RoCEv2 GID)

# 실행 후
gid index 3: ::0000:0000       (빈 entry)
gid index 2: ::ffff:10.0.0.3   (같은 GID가 index 2로 이동)
```

코드에 `GID_INDEX = 3`처럼 index를 하드코딩하면, link 재연결 후 빈 entry를 참조하게 되어 QP를 RTR로 전이시킬 때 `ibv_modify_qp`가 `EINVAL`을 반환한다. 이것은 장애 자체가 아니라 setup 실패이므로, 실험 결과를 오염시키지 않고 그냥 실험이 시작되지 않게 만든다.

해결: index를 하드코딩하지 말고, GID table을 순회하며 `::ffff:` 형태의 IPv4-mapped GID(즉 RoCEv2 over IPv4 entry)를 런타임에 자동 탐색한다. 이 함정은 recovery 실험(link을 흔드는 시나리오), swap 실험(NIC 재구성), multi-QP 실험(반복 setup) 모두의 재현성에 직결되었다. link을 의도적으로 내렸다 올리는 시나리오에서는 특히 매 반복마다 index가 바뀔 수 있으므로 자동 탐색이 사실상 필수다.

### A.3 kernel-bypass로 인해 무효인 fault injection 3종

RoCE RDMA의 data path는 user-space(libibverbs)에서 NIC hardware에 직접 접근하고 커널 네트워크 스택을 우회한다. 따라서 커널 네트워크 스택 위에서 동작하는 fault injection 도구들은 RDMA 트래픽에 아무 영향을 주지 못한다. 셋 다 실험으로 확인했다.

| 도구 | 의도한 장애 | 동작 계층 | RDMA data path 영향 |
|---|---|---|---|
| `tc netem` | 패킷 지연/손실 주입 | 커널 qdisc (네트워크 스택) | 무효 |
| `iptables` | 방화벽 차단 | 커널 netfilter (네트워크 스택) | 무효 |
| `ip link set <if> down` | 인터페이스 비활성화 | 커널 net device | 무효 (RDMA WRITE 계속 성공) |

```
일반 TCP/IP:
    프로그램 → 소켓 API → 커널 네트워크 스택 → 커널 NIC 드라이버 → NIC hardware
                              ↑ tc netem / iptables / ip link 가 개입하는 지점

RoCE RDMA:
    프로그램 → libibverbs (user-space) → NIC hardware 직접
                              ↑ 커널 스택을 통째로 건너뜀
```

`ip link set down`은 커널의 net device를 내릴 뿐, NIC hardware의 RDMA 엔진과 이미 RTS 상태인 QP의 data path에는 반영되지 않는다. 이것은 negative finding으로 정리한다: RoCE에서 실제 링크 장애를 재현하려면 커널 계층이 아니라 물리 케이블을 뽑거나 스위치 포트를 내리는 차원이라야 한다. RETRY_EXC_ERR 같은 timeout 계열 장애를 link 조작으로 재현하려던 시도가 실패한 근본 원인이 이것이다.

### A.4 vendor_err 0xf5 (WR_FLUSH_ERR)의 두 출처

`vendor_err`는 일반적으로 NIC firmware가 보고한 raw syndrome 값이지만, WR_FLUSH_ERR의 경우 driver가 직접 상수를 대입하는 경로가 따로 있다. cq.c를 열어 두 경로를 라인 번호로 구분한다.

경로 1 — 일반 error completion (firmware raw passthrough). 하드웨어가 생성한 error CQE를 처리하는 `mlx5_handle_error_cqe()`는 CQE의 `syndrome` 바이트로 ibv_wc_status를 분기한 뒤, `vendor_err`에는 CQE의 `vendor_err_synd` 바이트를 그대로 복사한다.

```c
// cq.c:299-302  (mlx5_handle_error_cqe 내부 switch)
case MLX5_CQE_SYNDROME_WR_FLUSH_ERR:
    dump = NULL;
    wc->status = IB_WC_WR_FLUSH_ERR;
    break;
...
// cq.c:339
wc->vendor_err = cqe->vendor_err_synd;   // firmware가 채운 raw 값 그대로
```

이 경로에서 `wc->vendor_err`는 firmware가 CQE에 써넣은 값이다. 우리 실험에서 관측한 0xf5는 이 경로를 통해 firmware가 보고한 raw syndrome일 가능성이 높다 (단, 0xf5와 driver 상수의 일치 여부는 아래 참조).

경로 2 — SW-flush (driver 상수 대입). QP가 ERR/RESET 상태이거나 device가 internal error 상태일 때, 남은 WQE는 wire로 나가지 않고 소프트웨어가 직접 flush completion을 생성한다. 이 경로에서는 `vendor_err`에 firmware 값이 아니라 `MLX5_CQE_SYNDROME_WR_FLUSH_ERR`라는 driver 상수를 대입한다. 두 곳에 있다.

```c
// cq.c:418-419  (sw_comp: QP가 ERR/RESET일 때 남은 WQE flush)
wc->status     = IB_WC_WR_FLUSH_ERR;
wc->vendor_err = MLX5_CQE_SYNDROME_WR_FLUSH_ERR;   // driver 상수

// cq.c:599-600  (poll_soft_wc: device internal error 시 soft WC를 강제 flush)
soft_wc->wc.status     = IB_WC_WR_FLUSH_ERR;
soft_wc->wc.vendor_err = MLX5_CQE_SYNDROME_WR_FLUSH_ERR;   // driver 상수
```

따라서 같은 WR_FLUSH_ERR라도 `vendor_err`의 출처가 다르다. firmware가 생성한 error CQE를 통과한 flush(경로 1)는 firmware raw 값을, driver가 자체 생성한 flush(경로 2)는 컴파일 타임 driver 상수를 담는다.

syndrome과 vendor_err_synd는 별개 바이트 필드. 이 구분이 가능한 근거는 CQE 구조체에서 두 값이 서로 다른 바이트로 저장되기 때문이다. device.h의 `struct mlx5_err_cqe`를 보면 두 필드가 인접하지만 독립적인 `u8`이다.

```c
// device.h:809-819
struct mlx5_err_cqe {
    u8     rsvd0[32];
    __be32 srqn;
    u8     rsvd1[18];
    u8     vendor_err_synd;   // device.h:813  → wc->vendor_err 로 패스스루
    u8     syndrome;          // device.h:814  → wc->status 분기에 사용
    __be32 s_wqe_opcode_qpn;
    __be16 wqe_counter;
    u8     signature;
    u8     op_own;
};
```

`mlx5_handle_error_cqe()`의 switch는 `cqe->syndrome`(device.h:814)으로 분기하고(cq.c:288), 값 복사는 `cqe->vendor_err_synd`(device.h:813)에서 가져온다(cq.c:339). 즉 ibv_wc_status를 만드는 바이트와 vendor_err를 만드는 바이트가 물리적으로 분리되어 있어, 하나의 status code가 여러 vendor_err로 세분화될 수 있다는 본문의 관찰(LOC_PROT_ERR가 0x53/0x52/0x33으로 갈라지는 것)이 구조적으로 성립한다. 참고로 cq.c:530-531의 디버그 로그도 `err_cqe->syndrome`과 `err_cqe->vendor_err_synd`를 별개 값으로 함께 출력한다.

0xf5와 driver 상수 값의 일치 여부. 경로 2가 대입하는 `MLX5_CQE_SYNDROME_WR_FLUSH_ERR`의 실제 enum 숫자값은 그 소스 복사본에 들어 있지 않았다. 복사본의 어떤 헤더(device.h 포함)에도 `MLX5_CQE_SYNDROME_*` enum 정의가 없으며, cq.c가 참조만 할 뿐이다(복사본 전역 grep 결과 정의 없음, 사용처 3곳뿐). 이 enum은 커널의 `<linux/mlx5/cq.h>`에 정의되어 있다.

따라서 실험에서 관측한 0xf5가 경로 1(firmware raw)에서 온 것인지 경로 2(driver 상수)에서 온 것인지, 그리고 driver 상수 자체가 0xf5와 같은지는 그 복사본만으로 확정할 수 없다.

[TODO: 확인 필요] 서버에서 `grep -rn "MLX5_CQE_SYNDROME_WR_FLUSH_ERR" /usr/src/linux-headers-*/include/linux/mlx5/cq.h` 또는 `<linux/mlx5/cq.h>`를 직접 열어 enum 숫자값을 확인하고 0xf5와 일치하는지 대조할 것. 일치한다면 4절의 "QP→ERR 강제 전환 후 post" 시나리오에서 관측된 0xf5는 경로 2(driver 상수)일 가능성이 높고, 일치하지 않는다면 경로 1(firmware raw)로 해석해야 한다.
