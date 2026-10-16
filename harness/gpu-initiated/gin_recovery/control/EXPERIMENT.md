# GIN 복원의 제어 경로를 RDMA로: 기록은 RC 링, 생존 확인은 상태 페이지 READ, 펜스는 계보 국면, 노드마다 launcher (gin-control)

**목적:** gin-restore와 gin-mirror 계층의 제어(helper 기록, 예비 등록, 활성화, REJOIN, 큰 자료)와 생존 판정을 1 GbE 관리망의 TCP helper 소켓에서 데이터망
RNIC 위 RDMA로 옮기고, 그때 죽음 판정 시간, FIN 없는 죽음, 멈춘 상대, 관리망 끊김의 투명성, 100 ms마다의 상태 페이지 READ의 비용이 어떻게 바뀌는지 잰다.
옛 TCP 제어 길은 빌드 스위치로 회귀용으로만, 관리망 소켓은 "상대 죽음"과 "선 끊김"을 가르는 증인으로만 남긴다.

| 항목 | 값 |
|---|---|
| 상태 | `DRAFT` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-16 |
| 기준 브랜치와 커밋 | `exp/gin-control` @ `bb1b7bde` (origin/master, gin-mirror `COMPLETE` 뒤) |
| 사전 등록 태그 | 없음 |
| 마지막 갱신 | 2026-10-16, 초안: 1–11절, 설계 9.1–9.9절, 충돌 표(사용자 결정 열넷으로 닫음), 제어 경로 설계 독립 리뷰의 막는 문제 다섯을 "설계 v2 반영 대기"로 표시, kill → 판정 시간 예측을 범위로, 12절 첫 행. 구현, 빌드, 클러스터 실행 없음 |

표시: `[측정]` 원자료에서 이 문서가 다시 셈, `[측정: 문서]` QA를 거친 다른 실험 문서의 값을 옮김(이 문서에서 다시 세지 않음), `[소스]` 코드에서 읽음,
`[문헌]` 논문이나 공개 문서, `[추론]` 해석, `[미확인]` 확인 안 함.

**줄 번호.** `[소스]`의 줄 번호는 따로 적지 않으면 gin-mirror 빌드 ln4의 호스트 파일 `gin_host_gdaki.cc`(md5 `0ab4e636`, 24 507줄)의 줄이다. 그 파일은
[../mirror/impl/mi_layer.diff](../mirror/impl/mi_layer.diff)(md5 `dcd30859`)를 적용한 트리의 것이다(재현은 [../mirror/NOTES.md](../mirror/NOTES.md)).

**근거 문서.** 이 초안은 저장소 밖의 설계 문서 셋(제어 경로를 RDMA로 옮기는 설계 초안, 감지 빈틈 셋의 설계 v2, 동적 예비 프로세스 설계)과 리뷰 둘(동적 예비
프로세스 설계의 독립 리뷰, gin-mirror 9.9절의 계보 리뷰)과 장애 문헌 조사에서 왔다. 그 파일들은 링크하지 않고 필요한 내용을 이 문서에 옮겨 적었다. 제어 경로
설계의 독립 리뷰(2026-10-16, 막는 문제 다섯, 고칠 것 스물하나, nit 열하나)는 나왔고 그것을 반영한 설계 v2를 쓰는 중이다. 리뷰가 바꾸는 자리는 이 문서에서 "설계 v2
반영 대기"로 표시하고, kill에서 판정까지의 시간 예측에는 `[초안, 설계 v2 뒤 확정]`를 붙였다.

**말.** gin-restore와 gin-mirror의 말(논리 rank, 예비 프로세스, 짝, 체크포인트, 입력 멈춤, hold, 화신, 계보, 국면, lane, DISARM)은
[../restore/EXPERIMENT.md](../restore/EXPERIMENT.md)와 [../mirror/EXPERIMENT.md](../mirror/EXPERIMENT.md) 머리말, 9.9절과 같다. 이 실험에서 더 쓰는 말:
- 기록: helper가 상대와 주고받는 고정 크기 제어 메시지(`struct gdakiTsMsg`, 1 872 B). 지금은 TCP helper 소켓, 이 실험에서는 RC QP의 SEND/RECV로 간다.
- 링: 받는 rank가 보내는 상대마다 미리 낸 RECV 자리 64개. 기록 하나가 자리 하나를 쓴다.
- 상태 페이지: rank마다 호스트 메모리의 4 KiB 영역. 상대가 RDMA READ로 읽어 생존을 판정한다. 박동은 그 페이지에서 1 ms마다 오르는 칸이다.
- 증인: 관리망에 남기는 TCP 소켓. BYE와 FIN만 보고, 혼자서는 판정하지 않는다.
- launcher: 노드마다 늘 떠 있는 작은 관리 프로세스. RDMA로 rank들과 이어지고, 예비 등록을 대신 받고, 활성화를 중계하고, 펜스를 집행하고(원래 프로세스를
  종료하고 pidfd로 끝남을 확인), 같은 노드 rank의 종료를 알린다.
- 펜스: 살아 있을 수 있는 옛 화신이 생존 rank의 QP와 window에 다시 닿지 않게 하는 차례. 생존 rank의 그 상대 QP를 오류 상태로 → 모든 생존 rank의 보고 →
  launcher의 종료와 확인. 계보의 국면 FENCING, FENCED로 나타낸다(9.4절).

| 빌드 키 | 내용 | 쓰는 곳 |
|---|---|---|
| `gc` | 이 실험의 연구 빌드: gin-mirror ln4 위에 9절의 RDMA 제어 계층(제어 길 rdma) | 새 셀, rdma 회귀 |
| `gct` | 같은 소스를 TCP 제어 빌드 스위치로 빌드(옛 TCP 제어 길; 9.8절) | tcp 회귀, 옛 동작 대조 |
| `gcp`, `gctp` | 위 둘의 운영 빌드(`-DNCCL_GIN_TS_PRODUCTION`) | 비용 셀 |
| `mi` | gin-mirror 빌드 ln4(대조, 읽기만) | 동일성 확인 |

빌드 키, 셀 이름, 예측의 찾는 키는 원자료를 찾는 이름일 뿐이다.

## 1. 배경과 연구 질문

**지금 제어가 가는 길** `[소스]`. 복구 계층의 모든 제어는 쌍마다 TCP helper 소켓 하나에 고정 크기 기록으로 간다(종류 1–19, 32–38, 48–51; 5207–5221, 5459–5466).
그 밖에 TCP 연결 셋이 더 있다: 짝이 예비 프로세스의 활성화 포트에 거는 연결(8889–8901), 자료 소켓(mirror 끈 길의 UPLOAD와 FETCH, 그리고 STATE; 15335–15420),
예비 프로세스가 생존 rank의 수신 대기 소켓에 거는 REJOIN(10142–10213). 이 소켓은 모두 관리망 1 GbE다. 이미 RDMA인 것은 저장소 올리기, mirror 켠 길의 FETCH,
mirror 쓰기, 준비 all-gather(GIN collComm, net_ib의 isend/irecv)뿐이고, 그 QP들의 끝점 교환도 TCP 기록으로 한다.

**지금 생존을 판정하는 길** `[소스]`. 죽음은 BYE 없는 FIN, 그리고 1 000 ms 넘게 떨어진 연결 거절 둘이다(8361–8388). hold의 강한 증거는 원인 이름 "FIN"과
"ECONNREFUSED"뿐이다(5706–5711). 소켓 설정은 keepalive 2 s, 1 s × 3, `TCP_USER_TIMEOUT` 5 000 ms다(8122–8139). 여기서 생기는 빈틈은 넷이다.
1. **RST.** 죽는 프로세스의 소켓에 읽지 않은 자료가 남으면 FIN 대신 RST가 가고, RST는 "모름"이라 거절 둘의 1 000 ms 규칙을 기다린다. gin-mirror 본 실행
   원자료의 소켓 닫힘 줄 669개는 `FIN liveness=dead` 361, `FIN liveness=left` 301, `ECONNRESET` 4, `ECONNREFUSED` 3이었고, RST 넷 가운데 셋이 RST에서 죽음
   판정까지 1 002.9, 1 003.0, 1 003.2 ms를 늦췄다(넷째는 fallback 뒤의 소켓) `[측정: ../mirror/results/20261015_main/raw/*.log에서 다시 셈]`. 그 셋의 복원은
   한도 2 000 ms 안이었지만 RST가 없는 같은 셀의 시행보다 약 1 s 길었다(`mi4_pull`의 한 시행 1 079.0 ms 대 나머지 넷 174.5–176.7 ms) `[측정: trials_scored.csv에서 다시 셈]`.
2. **멈춘 상대.** SIGSTOP이나 호스트 정지에서 커널은 TCP와 keepalive에 답하고 NIC은 데이터 QP에 ACK한다. 그래서 아무도 모른다: gpu-detect의 1.4–7.4 s 멈춤은
   8/8 투명했고 live_peer의 6 s 정지는 5/5 아무도 알아채지 못했다 `[측정: 문서 ../../../gpu-detect/EXPERIMENT.md, ../../../live_peer/EXPERIMENT.md]`. 길게 멈추면
   체크포인트만 2 000 ms마다 버려지고 생존 rank의 입력이 선다 `[소스: 14168, 15016]`.
3. **FIN 없는 죽음.** exec 없이 fork한 자식이 helper 소켓을 물려받은 채 부모가 죽으면 FIN도 RST도 시간 초과도 없다. 생존 rank가 put을 내면 데이터 QP의 재시도
   초과 뒤 약 28 s에 "모름"으로 거절되고, put이 없으면 영영 판정이 없다 `[소스: 8135–8138; 추론, 시행으로 잰 적 없음]`.
4. **옛 화신.** 복원 Commit은 생존 rank의 같은 QP를 RESET으로 옮겨 예비 프로세스의 QPN에 다시 잇는다(3068–3069). RC 요청 패킷에는 보낸 QP 번호가 없어
   깨어난 옛 프로세스의 쓰기를 가리는 것은 PSN뿐이다 `[소스, 추론; ConnectX의 출발지 검사 여부 미확인]`. 지금 활성화 관문은 `/proc`에서 zombie(Z)를 끝남으로
   치므로(4550–4580) 다른 스레드가 자원을 쥔 창이 있다. gin-mirror 본 실행에서 'later'가 0번인 빠른 활성화는 그 열이 있는 시행 95개 가운데 8개였다(모두
   데이터 같음) `[측정: trials_scored.csv에서 다시 셈]`. SIGKILL에서는 옛 QP가 곧 사라져 위험이 작았지만, 살아 있는 상대를 되살리려면 그 창을 닫아야 한다 `[추론]`.

**지금의 시간** `[측정: ../mirror/results/20261015_main/trials_scored.csv에서 다시 셈]`. mirror 켠 4 KiB 한 죽음 셀(`mi4_kill3_ow`, `mi4_kill1_ow`, `mi4_kill3_ckpt_ow`,
`mi4_seg_*`, `mi4_pull`, `rs4_kill3_mion`)의 복원 시간은 RST 시행 하나(1 079.0 ms)를 빼고 174.5–220.5 ms(n 44)였다. 그 가운데 활성화 관문의 기다림
(`activate_ms`, 'later' 1번 이상인 느린 모드)은 105.3–146.6 ms(n 44), 활성화 뒤 부분(`post_activate_ms`)은 67.2–71.4 ms(n 45)였다. 학습 모양 rank 3 kill은
249.6–298.0 ms(n 10, 관문 기다림 168.0–210.4 ms), mirror 끈 TCP 길(`rs4_kill3`)은 369.5–403.4 ms(n 10)였다. 장애 없는 시행의 입력 멈춤 최대는 4 KiB 덮어쓰기
8.151 ms(n 5), 학습 모양 10.227 ms(n 5)였다. 관문 기다림은 원래 프로세스가 `/proc`에서 사라질 때까지이므로, launcher의 pidfd 보고가 올 때의 어림이다 `[추론]`.

**왜 지금 하나** `[문헌]`. 큰 학습 작업을 멈추는 장애 가운데 우리가 이 장비에서 그대로 넣을 수 있는 것은 프로세스 crash(ByteDance ByteRobust 3개월 작업
778 135개에서 CUDA Error 19 968건, 표의 36.1%), 오류 없이 서는 작업(같은 표 Job Hang 5 506건, 9.9%; Llama 3 54일의 NCCL watchdog timeout 7회), 그리고 커널이
연결을 닫지 못하는 호스트 crash의 제어 경로 쪽 모양이다. 앞의 것은 지금 FIN으로 잡지만, 뒤의 둘은 지금 설계가 소켓에 기대어 잡지 못하거나 수십 초 늦게 잡는다.
백엔드 네트워크(링크, 케이블, NIC, 스위치) 장애는 Llama 3에서 예기치 않은 중단 419회 가운데 42회(약 10%; 표의 횟수 합은 문헌 조사가 다시 셈, 이 문서에서 다시 세지 않음)다. 문헌 출처와 우리 주입과의
거리는 9.9절이다.

**사용자 결정(2026-10-16; 이 실험의 고정 전제).** 앞 결정(저녁): 감지 신호는 heartbeat(UDP, TCP)가 아니라 상대 호스트 메모리의 상태 페이지를 RDMA READ로
읽는 것이고, 관리망 소켓은 둘째 증인이다. 멈춘 상대는 펜스 뒤 되살리고(끌 수 있게), 펜스는 계보의 국면 하나이며, 활성화 관문은 "펜스됨"을 요구하고, RST 뒤
거절 간격은 0.1 s, fork 자식의 fd는 한계로 두고, 종료 역할은 launcher가 맡는다. 라이브러리 내부 통신은 RDMA 먼저이고 TCP는 싸거나 이미 있다는 까닭으로
고르지 않는다. 뒤 결정(21시 무렵, 열넷; 메인 세션이 전함):
1. 옛 TCP 제어 길은 빌드 스위치로 회귀용으로 남긴다.
2. launcher는 반드시 있다: 노드마다 늘 떠 있는 관리 프로세스가 RDMA 제어 연결, 예비 등록 대리, 예비 띄우기와 '잠깐만'(LATER) 대리 답, 펜스 집행(원래 프로세스
   종료와 pidfd 확인)을 맡는다.
3. 노드 안 launcher와 rank 사이는 Unix 소켓을 쓴다(fd 전달 때문).
4. 재생이 끝나기 전의 '잠깐만'은 launcher가 한도를 두고 대신 답한다.
5. FIN은 증인으로만 쓴다(FIN 혼자서는 죽음이 아니다).
6. 다시 짝 맺을 때 전달되지 않은 기록이 사라지는 것은 TCP와 같은 뜻으로 둔다.
7. mirror 끈 길의 TCP 자료 소켓도 RDMA 저장소로 옮긴다(회귀는 1번의 스위치로).
8. 소켓 시험 스위치는 증인만 막는다.
9. UD datagram에 필요한 경로 MTU ≥ 2 048은 리뷰 때 확인한다.
10. 예비 등록의 wire는 판 번호를 올린다.
11. 활성화는 launcher가 중계한다.
12. 예비 띄우기 요청은 hold 시작 때 낸다.
13. fork 자식이 fd를 물려받는 셀은 거절만 하고 한계로 적는다.
14. 긴 hold에서 생존 rank 사이 lane이 넘치는 것은 이번에는 한계로 두고(DISARM을 예측), 설계 변경은 gin-dynamic에서 한다.

**질문.**
1. 제어와 생존 확인을 RDMA로 옮기면 SIGKILL과 RST로 죽은 rank의 죽음 판정과 복원 시간은 얼마인가. FIN을 증인으로만 써도 판정이 1 s 안에 남는가.
2. FIN 없는 죽음(자식이 증인 소켓을 쥠)은 launcher의 종료 보고로 몇 ms에, 그 보고가 없을 때 상태 페이지 READ의 실패로 몇 s에 판정되는가. 같은 주입을 옛 TCP
   제어 길에서 하면 얼마인가.
3. 멈춘 상대는 정한 문턱(10 000 ms) 전에는 판정되지 않고(8 000 ms까지 투명), 문턱을 넘으면 펜스 뒤 되살아나는가. 펜스 뒤 옛 화신의 쓰기가 생존 rank의
   window에 닿지 않는가.
4. 관리망이 8 s 끊겨도 기록과 체크포인트가 멈추지 않는가(지금은 helper 소켓을 다시 건다).
5. 상대마다 100 ms마다 하나인 상태 페이지 READ가 4 KiB put 지연과 묶음 대역을 얼마나 바꾸는가.
6. 같은 소스의 TCP 제어 빌드에서 gin-mirror와 gin-restore의 예측이 원래 기준대로 맞는가. RDMA 제어 빌드에서 제어 경로와 무관한 예측(데이터 같음, 재실행 없음,
   억제 정확, 내용이 pool에서 옴)이 그대로 맞는가.

## 2. 가설

초안이다(2026-10-16). 수치는 설계의 어림이고 pilot 뒤 사전 등록에서 고친다.

| 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|
| FIN을 증인으로만 써도 kill의 죽음 판정은 1 s 안이다. 판정은 증인 FIN 때의 READ 하나와 확인 창 W(20–50 ms) 뒤의 READ 하나가 박동 정체를 보거나 W 안에 READ가 끝나지 않을 때, 또는 launcher의 종료 보고(약 105–210 ms)가 먼저 올 때 선다. 죽는 프로세스의 정리 차례 때문에 대개 launcher 보고나 FIN + W로 판정될 것이다 `[추론: 9.3절; 리뷰]` `[초안, 설계 v2 뒤 확정]` | `gc4_kill3_ow`류에서 kill → 첫 생존 rank의 죽음 판정이 20–250 ms 밖인 시행이 있거나, FIN 하나만으로 판정한 줄이 있다 |
| RST는 더 이상 판정을 1 s 늦추지 않는다. rdma 빌드에서는 RST도 증인의 "모름"이고 FIN처럼 확인 창으로 가려진다. tcp 빌드에서 RST 뒤 거절 간격을 100 ms로 두면 RST → 죽음이 100.5–106 ms다 `[추론]` `[초안, 설계 v2 뒤 확정]` | RST 셀에서 RST → 죽음이 rdma 빌드 20–250 ms 밖이거나, 간격 100 ms를 둔 tcp 시행에서 106 ms를 넘는다 |
| FIN 없는 죽음은 launcher의 종료 보고로 원래 프로세스의 정리 시간(4 KiB 105–147 ms 어림)에 판정되고, 그 보고가 없으면 상태 페이지 READ의 재시도 초과로 kill 뒤 약 3.7 s(3.5–4.5 s)에 판정된다. 옛 TCP 길은 20 s 안에 판정하지 못한다 `[추론]` `[초안, 설계 v2 뒤 확정]` | 보고 있는 셀에서 kill → 판정이 100–250 ms 밖이거나, 보고 없는 셀에서 3.5–4.5 s 밖이다(READ 재시도 초과가 아닌 길로 판정) |
| 멈춘 상대는 박동 정체 10 000 ms 전에는 판정되지 않고, 넘으면 모든 생존 rank가 2 × 100 ms 안에 멈춤을 판정하며, 펜스 뒤 되살아나고, 펜스 뒤 옛 화신의 쓰기는 0이다 | 8 000 ms 이하 멈춤에서 판정이 있거나, 12 000 ms 멈춤에서 판정이 10 000–10 300 ms 밖이거나, 펜스 뒤 생존 window에 바뀐 칸이 있거나, 데이터가 기준과 다르다 |
| 관리망 8 s 끊김(증인만 막음)에서 판정 0, 기록 길 다시 짝 맺기 0, 그 사이에도 체크포인트가 확정된다 | 판정이나 기록 길 잃음이 있거나, 끊김 동안 확정된 체크포인트가 0이다 |
| 상태 페이지 READ는 따로 된 QP의 256 B READ라 4 KiB put 지연 중앙값을 2 % 넘게 바꾸지 않는다 `[추론]` | 노드마다 READ 켬 대 끔의 4 KiB 지연 중앙값 차가 2 %를 넘는다 |
| 회귀 없음: tcp 빌드는 gin-mirror의 비용 밖 예측을 원래 기준대로 맞힌다. rdma 빌드는 제어 경로와 무관한 예측을 원래 기준대로 맞힌다 | 그 예측 가운데 원래 판정식을 어기는 것이 있다 |
| 긴 hold의 생존 rank 사이 lane 넘침은 한계다(사용자 결정 14): 넘치면 그 받는 rank의 DISARM이고 데이터는 틀리지 않는다 | DISARM 없이 lane이 넘쳐 데이터가 기준과 다르다 |

## 3. 사전 예측 (측정 전에 작성)

초안이다. 문턱과 n은 pilot 뒤 사전 등록에서 고정한다. 판정은 유효한 시행만으로 센다(8절). "≥ k/n"은 유효 시행 n개 가운데 조건이 참인 것이 k개 이상이다.
시각은 생존 rank 자기 프로세스의 `mono_ms`이고, kill 시각은 실행기의 kill 줄을 같은 노드 시계로 잰다.

| 무엇을 예측했나 | 셀 | 시행마다의 조건 | 판정식(초안) | 근거 | 찾는 키 |
|---|---|---|---|---|---|
| kill의 죽음 판정이 FIN 하나에 기대지 않고 1 s 안 | `gc4_kill3_ow`(그리고 rdma 빌드의 gin-mirror kill 셀) | kill → 생존 rank마다 죽음 판정 20–250 ms `[초안, 설계 v2 뒤 확정]`, 판정 원인이 FIN+STALE, FIN+NORESP(확인 창 안에 READ가 끝나지 않음), EXITED 가운데 하나(원인마다 수는 보고), 판정 원인이 FIN 하나이거나 원격 접근 오류 하나인 줄 0 | ≥ 9/10 | 9.3절 판정 표, 사용자 결정 5 | `kill_judge_rdma` |
| RST로 죽어도 1 s 늦지 않음(rdma) | `gc4_rst_kill3@gc` | RST 줄이 있는 생존 rank마다 RST → 죽음 판정 20–250 ms `[초안, 설계 v2 뒤 확정]`, 복원 성공 | ≥ 9/10 | 9.3절 | `rst_judge_rdma` |
| RST 뒤 거절 간격 100 ms(tcp) | `gc4_rst_kill3@gct` | RST → 죽음 판정 100.5–106 ms `[초안, 설계 v2 뒤 확정]`(옛 1 002.9–1 003.2 ms `[측정]`; tcp 빌드가 옛 동작 전체를 되살리면 간격은 매개변수로만 100이고 회귀 셀은 1 000, 9.7절), 복원 성공 | ≥ 9/10 | 감지 설계, 사용자 결정(저녁) | `rst_judge_tcp` |
| 살아 있는 상대의 RST와 포트 닫힘은 rdma에서 판정 없음 | `gc4_rstgap_live300@gc` | 판정 0, 거절 0 | 5/5 | 사용자 결정 5 | `rstgap_live_rdma` |
| 같은 주입이 tcp에서 50 ms면 판정 없음, 300 ms면 거짓 죽음 | `gct4_rstgap_live50`, `gct4_rstgap_live300` `@gct` | 50 ms: 판정 0; 300 ms: 판정이 RST 뒤 100.5–106 ms(100 ms 간격의 대가) `[초안, 설계 v2 뒤 확정]` | ≥ 9/10, ≥ 4/5 | 감지 설계 | `rstgap_live_tcp` |
| FIN 없는 죽음, launcher 보고 | `gc4_fdhold_sock_kill3` | kill → 판정 100–250 ms `[초안, 설계 v2 뒤 확정]`, 원인 EXITED, 복원 성공, 데이터 같음 | ≥ 9/10 | 9.3, 9.5절; 관문 기다림 105.3–146.6 ms `[측정]` | `finless_exit_report` |
| FIN 없는 죽음, READ 실패 | `gc4_fdhold_sock_kill3_noreport`(증인 끔, launcher의 종료 보고 끔) | kill → 판정 3.5–4.5 s `[초안, 설계 v2 뒤 확정]`, 원인 "멈춘 박동 뒤 응답 없음", 복원 성공 | ≥ 4/5 | READ 재시도 초과 3.51–3.76 s `[측정: 문서 ../../../teardown_order/README.md]` | `finless_read_fail` |
| 옛 TCP 길의 FIN 없는 죽음 | `gct4_fdhold_sock_kill3@gct` | kill 뒤 20 s 안 판정 0, hold 0; 끝 시각(모름 거절이나 시행 한도)은 보고 | ≥ 4/5 | 1절 빈틈 3 | `finless_tcp_baseline` |
| 자식이 uverbs fd까지 쥐면 거절만 | `gc4_fdhold_uverbs_kill3`(셀 설정으로 복원 끔: 예비 프로세스 없음) | 죽음 판정(원인 EXITED 또는 박동 정체; 시각은 보고), 복원하지 않고 거절, 생존 rank는 fail-fast로 끝남, 판정 뒤 생존 window에 바뀐 칸은 보고 | ≥ 4/5 | 사용자 결정 13; 리뷰: 종료 보고가 곧 FENCED를 만들어 펜스가 이 셀을 막지 못하므로 거절은 셀 설정으로만 | `fdhold_uverbs_refuse` |
| 짧은 멈춤은 투명 | `gc4_stop1500`, `gc4_stop4000`, `gc4_stop8000` | 판정 0, 데이터 같음; 4 000과 8 000은 의심 줄(박동 정체 2 000–2 200 ms)이 있음 | 셀마다 ≥ 9/10 | 9.3절 문턱, gpu-detect 투명 | `stop_transparent` |
| 느린 상대는 판정 없음 | `gc4_slow_duty` | 의심 0, 판정 0; 단계 시간은 보고 | 5/5 | 9.3절 | `slow_no_judge` |
| 긴 멈춤은 펜스 뒤 복원 | `gc4_stop12000_fence` | 생존 rank마다 멈춤 판정이 STOP 뒤 10 000–10 300 ms, 판정 시각의 퍼짐 ≤ 200 ms, FENCING → FENCED → 활성화 차례, 판정 → 마지막 게시 ≤ 1 500 ms, CONT 때 대상 PID 없음, 펜스 뒤 생존 window에 바뀐 칸 0, 데이터 같음 | ≥ 9/10 | 9.4절 | `stall_fence_restore` |
| 긴 멈춤, 펜스 끔 | `gc4_stop12000_none` | 멈춤 판정 뒤 거절, fallback 뒤 대기가 오류로 풀림, 판정 뒤 생존 window에 바뀐 칸 0 | ≥ 4/5 | 9.4절 끝 | `stall_none_refuse` |
| 살아서 도는 프로세스의 펜스 | `gc4_freeze12000_fence`(박동 쓰기만 멈춤) | 멈춤 판정 10 000–10 300 ms, launcher가 종료하고 pidfd로 끝남을 봄, 펜스 뒤 바뀐 칸 0, 데이터 같음 | ≥ 4/5 | 9.4절 | `freeze_fence_restore` |
| 관리망 끊김의 투명 | `gc4_mgmt_mute8`(증인만 8 s 막음) | 판정 0, 기록 QP 잃음 0, 끊김 동안 확정된 체크포인트 ≥ 1, 데이터 같음 | 5/5 | 사용자 결정 8 | `mgmt_mute_transparent` |
| 같은 끊김의 옛 길 | `gct4_mgmt_mute8@gct` | 판정 0, 데이터 같음; helper 다시 걸기 줄과 끊김 동안 버린 체크포인트 수는 보고 | 5/5 | gin-reconnect의 8 s 끊김 셀 | `mgmt_mute_tcp` |
| 기록 QP 오류의 다시 짝 맺기 | `gc4_qperr_record` | 판정 0, UD 다시 짝 맺기로 세대 + 1, 그 쌍의 기록이 이어짐, 데이터 같음 | ≥ 4/5 | 9.1절, 사용자 결정 6 | `qp_err_repair` |
| 잃은 REJOIN datagram | `gc4_ud_drop_rejoin`(rank 3 kill, 첫 REJOIN datagram 버림) | 다시 보낸 REJOIN으로 복원 성공, 받아들임 1번(멱등) | ≥ 4/5 | 9.5절 | `ud_drop_rejoin` |
| credit 멈춤에도 기록 잃음 없음 | `gc4_credit_stall`(받는 쪽이 500 ms RECV를 다시 내지 않음) | RNR 0, 보내는 쪽 대기열로 미룸, 기록 잃음과 겹침 0, 데이터 같음 | 5/5 | 9.1절 credit | `credit_stall_no_loss` |
| 예비 프로세스 없음의 곧바른 fallback | `gc4_kill3_ow_spareabsent` | launcher가 곧바로 REFUSED, FENCED → fallback ≤ 100 ms(옛 1 000 ms 규칙 대신), 대기가 오류로 풀림 | ≥ 4/5 | 9.5절, 사용자 결정 2, 11 | `spare_absent_refused` |
| 증인 없는 kill | `gc4_kill3_ow_nowitness` | 판정 원인 EXITED(원격 접근 오류 하나로는 판정하지 않음), kill → 판정 100–250 ms `[초안, 설계 v2 뒤 확정]`, 복원 성공, 떠남과 죽음이 갈림(정상 종료 시행 끝의 hold 0) | ≥ 4/5 | 9.3절 | `kill_no_witness` |
| 복원 시간의 상한과 관문 | rdma 빌드의 gin-mirror 복원 셀 | 첫 죽음 판정 → 마지막 생존 rank 게시 ≤ 2 000 ms(학습 모양 ≤ 1 000 ms) `[초안, 설계 v2 뒤 확정]`(판정 줄이 launcher 보고 쪽으로 늦어지면 hold 시작과 띄우기 요청도 그만큼 늦음), 'later' 0번의 빠른 활성화 0(관문이 FENCED), LATER는 활성화마다 많아야 한 번 | ≥ 9/10(셀마다) | 9.4, 9.5절 | `restore_time_rdma` |
| 장애 없음: 생존 확인이 조용함 | `gc4_none_probe`(60 s), `gc4_none_ow` | READ 성공률 100 %, 박동이 는 간격의 최대 < 300 ms, 의심 0, 판정 0, 찢긴 줄 읽기 수는 보고, 입력 멈춤 ≤ 16 ms(학습 모양 ≤ 20 ms; gin-mirror 고정값) | 10/10, 5/5 | 9.2절 | `none_probe_clean` |
| 제어가 관리망에 없음 | rdma 빌드의 모든 시행 | 이 계층이 TCP로 보낸 기록과 자료 바이트 0(증인 BYE 빼고), 이 계층의 TCP 연결 수 = 증인 쌍 수(증인 끄면 0), 시행 kv에 두 GIN 포트의 `active_mtu`가 남고 4 096 | 모든 시행 | 9.6절 | `no_tcp_control` |
| 상태 페이지 READ의 비용 | 비용 가족 probe, `lat4k`, `lat256k`, `bw256k`, 노드 둘; 팔 `probe-off`, `probe-on`(`@gcp`), `tcp`(`@gctp`) | `probe-on` 대 `probe-off`의 4 KiB 지연 중앙값 차 | 노드마다 ≤ 2 %; 256 KiB 지연과 대역은 보고 | 9.2절 비용 | `cost_probe_lat4k` |
| 긴 hold의 lane(사용자 결정 14: 문서화한 한계) | 위 셀 가운데 hold가 1 s를 넘는 시행(멈춤 펜스, launcher의 LATER 한도) | 생존 rank 사이 lane 깨짐과 DISARM 수 | 넘치면 그 받는 rank의 DISARM이 예측이고 실패로 세지 않음; DISARM이 있어도 데이터는 같아야 함. 생존 rank끼리만 계속 주고받는 driver 셀은 gin-dynamic | 사용자 결정 14, 동적 예비 프로세스 리뷰 | `long_hold_lane` |
| 회귀(tcp 빌드) | gin-mirror 7절의 비용 밖 셀을 이름과 env 그대로 `@gct` | gin-mirror 예측 표의 원래 판정식 그대로 | 원래 기준 | 사용자 결정 1 | `regression_tcp`(gin-mirror의 찾는 키들) |
| 회귀(rdma 빌드, 제어와 무관한 예측) | 같은 셀 `@gc` | gin-mirror의 데이터 같음, 재실행 없음, 되살린 rank가 끝까지, 억제 정확, 내용이 pool에서 옴, 다시 이미지와 둘째 죽음 | 원래 기준 | 9.7절 회귀 행 | `regression_rdma` |
| 회귀(rdma 빌드, mirror 끈 길이 RDMA 저장소로) | gin-restore 셀(`rs4_*`) `@gc` | 데이터 같음, 재실행 없음, helper 소켓과 자료 소켓으로 보낸 이미지 바이트 0 | 원래 기준(k/n) | 사용자 결정 7 | `regression_rdma_mirror_off` |

**다시 예측해야 하는 옛 예측**(rdma 빌드에서 같은 결과를 기대할 수 없는 것; 끝난 실험의 결과와 해석은 바꾸지 않는다) `[추론]`.
- 복원 시간과 관문 열(`ow_restore_time`, `rg_restore_time`, 'later' 수, `activate_ms`): 관문이 FENCED로 바뀌어 빠른 모드가 없어지고 활성화 뒤 부분의 TCP 몫이
  없어진다. 위 `restore_time_rdma`가 대신한다.
- 예비 프로세스 없음(`rg_spare_absent_fallback`): 1 000 ms 규칙 대신 launcher의 곧바른 REFUSED. 위 `spare_absent_refused`가 대신한다.
- 무장 조건(`rg_nospare_failfast`): "등록이 있음"이 "그 노드 launcher와 짝 맺기가 됐고 예비 모드가 켜짐"이 된다(9.5절).
- mirror 끈 TCP 저장소를 보던 예측(`rg_*` 가운데 TCP 올리기와 FETCH를 전제한 것): 사용자 결정 7로 rdma 빌드에서는 RDMA 저장소를 탄다.
- gin-harden의 "FIN = 죽음"과 거절 1 000 ms 규칙, gin-reconnect의 8 s 끊김 셀의 다시 걸기 줄: rdma 빌드에서는 증인에만 닿는다.
- 장애 없음의 입력 멈춤 상한(`ow_none_clean` 16 ms, `train_none_clean` 20 ms): 감시 스레드의 일이 늘고 기록 왕복이 RDMA가 된다. 위 `none_probe_clean`에 같은 값을
  두고 pilot에서 다시 본다.

## 4. 범위

**포함.** 9절의 설계(제어 QP와 링, 상태 페이지, 생존 판정 표, 펜스 국면, launcher, 준비와 관리망에 남는 것, 충돌 표, 이행 단계), gin-mirror ln4 위의 구현(충돌이
닫히고 독립 리뷰를 반영한 뒤), launcher 프로그램, 시험 스위치, 7절의 셀. 같은 소스의 TCP 제어 빌드(회귀용). 미리 띄운 예비 프로세스가 launcher를 거쳐
등록되고 활성화되는 길.

**gin-dynamic에 넘기는 것(이 실험이 만들되 셀로 재지 않음).** launcher의 SPAWN(hold 시작 때 짝이 보냄, (rank, 새 화신)마다 한 번), 띄운 예비 프로세스의 한도
(`NCCL_GIN_RESTORE_SPARE_START_MS` 초안 5 000)와 끝남과 재생 실패의 REFUSED, 재생 전 LATER 대리 답(사용자 결정 4). 이 셋은 CPU 모형 시험까지만 하고, 동적
예비 프로세스의 복원 셀, 같은 rank의 둘째 kill(지금 driver는 예비 프로세스에서 단계 kill을 끄고 실행기는 같은 rank를 거절함), 긴 hold 셀은 gin-dynamic에서 한다.
동적 예비 프로세스 리뷰가 찾은 TCP 전제 열다섯 곳은 9.5절 끝 표에서 이 설계의 답으로 닫는다.

**제외.**
- 동시에 둘 이상 죽는 것, 짝과 그 짝이 함께 죽는 것, 복원 중의 둘째 죽음(gin-mirror 4절과 같은 단일 실패 범위).
- 실제 link down과 flap, 노드 고장, 재부팅, 드라이버 재적재, 방화벽 규칙 바꾸기, NIC의 ACK 타임아웃 floor 끄기(NIC function 전체 설정): 클러스터 규칙. 노드와
  선 판정 길은 설계와 CPU 모형까지만 하고 셀로 재지 않는다.
- 다른 노드의 예비 프로세스, 다른 GPU의 예비 프로세스(gin-dynamic 뒤).
- 다시 짝 맺기 때의 정확히 한 번 전달(사용자 결정 6), UD 조각내기(사용자 결정 9의 확인이 실패하면 rdma 길을 켜지 않음).
- NCCL 자신의 bootstrap과 net_ib 연결 맺기를 관리망에서 옮기는 것(NCCL 핵심, 초기화 때만; 9.6절).
- 실제 학습 framework(gin-train).

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드, NIC, GPU, CUDA | gin-mirror와 같다: rain(Quadro RTX 5000), sunny(RTX A4000), ConnectX-6, RoCE v2 직결, PMTU 4 096, CUDA 12.8 | gin-mirror 5절, `../../../ack_timeout/README.md`(이 문서에서 다시 확인하지 않음) |
| 랭크 배치 | 랭크 4개, GPU마다 둘(rain에 0과 2, sunny에 1과 3), 짝은 p xor 1, 예비 프로세스는 같은 노드 같은 GPU | gin-mirror 5절 |
| launcher | 노드마다 하나(rain, sunny), 실행기가 hold 시작 때 띄우고 끝에 끔. sunny는 ssh 하나로 띄움(시험 장치) | 계획 |
| 데이터 QP 시한 | `NCCL_IB_TIMEOUT=14`, retry 7. 이 NIC은 floor 때문에 재시도 초과가 3.5–3.8 s | `[측정: 문서 ack_timeout]` |
| 라이브러리 | gin-mirror ln4(`mi`) + 9절의 제어 계층(`gc`); 같은 소스의 TCP 제어 빌드(`gct`). 장치 코드는 바뀌지 않음(목표 0줄) | 구현 전 |
| 관리망 | 1 GbE. 이 계층에서는 증인 소켓만 쓴다(9.6절) | 사용자, 계획 |
| UD 경로 MTU | GIN 포트(rain `mlx5_1`, sunny `mlx5_0`)의 `active_mtu` 4 096, GIN 쌍의 경로 MTU 4 096 | `[측정: 문서]` 제어 경로 설계 리뷰가 2026-09-23 장치 캡처(`ibv_devinfo -v`)와 gin-restore 실행 가능성 kv에서 읽음; 이 문서에서 다시 보지 않음. 시행마다 kv에 기록(설계 v2 반영 대기) |

## 6. 변수

- **독립변수.** 제어 빌드(rdma `gc`, tcp `gct`), 장애(SIGKILL, RST로 죽기, 자식이 증인 소켓만 쥔 kill, 자식이 uverbs fd까지 쥔 kill, SIGSTOP 1 500, 4 000,
  8 000, 12 000 ms, 50 ms씩 멈춤 반복, 박동 쓰기만 멈춤, 살아 있는 RST와 포트 닫힘, 증인 8 s 막음, 기록 QP 오류 상태, UD datagram 버림, credit 멈춤), 펜스
  (`NCCL_GIN_RESTORE_FENCE=lineage|none`), 증인(`NCCL_GIN_CTRL_WITNESS=1|0`), launcher 종료 보고(켬, 끔: 시험 스위치), 상태 페이지 READ(켬, 끔: 비용 셀).
- **종속변수.** gin-mirror의 종속변수 전부(대기 결과, 데이터 비교, 단계 실행 수, 억제 수, 복원 단계별 시각, 입력 멈춤)와 더해서: 판정 종류와 시각(주입 또는
  마지막 박동 증가 → 판정), 생존 rank 사이 판정 시각의 퍼짐, READ 성공률과 지연(중앙값, 최대), 박동 증가 간격의 최대, 찢긴 줄 읽기 수, 의심과 멈춤 판정 수,
  증인 상태, 계보 국면 차례(FENCING, FENCED)와 시각, launcher의 종료와 pidfd 확인 시각, LATER 수, 펜스 뒤 생존 window에 바뀐 칸, 기록 QP 세대와 다시 짝 맺기
  수, 보내는 쪽 대기열 최고, 이 계층의 TCP 바이트와 연결 수, put 지연과 묶음 대역.
- **통제변수.** gin-mirror 6절의 통제변수 전부(mirror 켬, segment 자리 3, lane 1 MiB, 당기기 50 %, 시행마다 프로세스를 새로 띄움 등). 더해서: READ 주기
  `NCCL_GIN_TS_PROBE_MS` 100, READ 시한 500 ms, FIN 뒤 확인 창 W 20–50 ms(pilot의 장애 없는 박동 간격 최대에서 정함; 설계 v2 반영 대기), 의심 2 000 ms, 멈춤 10 000 ms, 데이터 경로 거부권 창 1 000 ms, READ 응답 없음의 다시 짝 맺기
  3번, RST 뒤 거절 간격 100 ms(tcp 빌드), 링 자리 64, outbox 8 MiB, 기록 QP의 timeout은 `NCCL_IB_TIMEOUT`(14)과 같음, 모든 rank가 같은 값(준비 합의).

## 7. 실험 셀, 반복 수, 대조군

초안이다. n은 감지 설계와 제어 경로 설계의 이행 계획에서 왔고 pilot의 시행 wall을 본 뒤 사전 등록에서 고정한다. 배치, 4 KiB 덮어쓰기 workload(`RS_OVERWRITE=1`),
단계 사이 5 000 µs, 복원 시한 20 000 ms는 gin-mirror와 같다. 멈춤 셀은 시행이 길어(12 000 ms 멈춤과 복원) 시행 한도를 60 s로 둔다 `[추론]`.

| 셀 | 조건 | 빌드와 반복 수 | 종류 |
|---|---|---|---|
| `gc4_none_ow` | 장애 없음 | `@gc` 5 | 대조 |
| `gc4_none_probe` | 장애 없음, 60 s 동안 보냄 | `@gc` 10 | 생존 확인의 조용함 |
| `gc4_kill3_ow` | rank 3 SIGKILL(실행기, 대부분 FIN) | `@gc` 10 | 판정 시간 |
| `gc4_kill3_ow_nowitness` | 같고 증인 끔 | `@gc` 5 | 증인 없는 판정 |
| `gc4_rst_kill3` | rank 3이 연결된 소켓에 linger 0을 두고 스스로 SIGKILL(생존 rank 모두 RST) | `@gc` 10, `@gct` 10 | RST |
| `gc4_rstgap_live300` | 살아 있는 rank 1이 연결 소켓을 linger 0으로 닫고 수신 대기를 300 ms 닫음(fail-fast) | `@gc` 5 | RST(살아 있음) |
| `gct4_rstgap_live50`, `gct4_rstgap_live300` | 같고 50 ms, 300 ms | `@gct` 10, 5 | 100 ms 간격의 대가 |
| `gc4_fdhold_sock_kill3` | rank 3이 자식을 fork해 증인 소켓을 넘긴 뒤 부모 SIGKILL | `@gc` 10 | FIN 없는 죽음 |
| `gc4_fdhold_sock_kill3_noreport` | 같고 증인 끔, launcher 종료 보고 끔 | `@gc` 5 | FIN 없는 죽음(READ) |
| `gct4_fdhold_sock_kill3` | 같은 주입, 옛 TCP 길(helper 소켓을 넘김) | `@gct` 5 | 대조 |
| `gc4_fdhold_uverbs_kill3` | 자식이 uverbs fd까지 쥠 | `@gc` 5 | 한계 셀(거절만) |
| `gc4_stop1500`, `gc4_stop4000`, `gc4_stop8000` | rank 3 SIGSTOP 그 길이 뒤 SIGCONT | `@gc` 각 10 | 투명 |
| `gc4_stop12000_fence` | 12 000 ms, `FENCE=lineage` | `@gc` 10 | 펜스와 복원 |
| `gc4_stop12000_none` | 12 000 ms, `FENCE=none` | `@gc` 5 | 거절 |
| `gc4_slow_duty` | rank 3에 SIGSTOP과 SIGCONT를 50 ms씩 20 s | `@gc` 5 | 느린 상대 |
| `gc4_freeze12000_fence` | rank 3의 박동 쓰기만 12 000 ms 멈춤(프로세스는 돎), `FENCE=lineage` | `@gc` 5 | 도는 프로세스의 펜스 |
| `gc4_mgmt_mute8`, `gct4_mgmt_mute8` | rank 1의 증인(tcp는 helper 소켓) 8 s 막음 | `@gc` 5, `@gct` 5 | 관리망 끊김 |
| `gc4_qperr_record` | rank 0과 rank 1 사이 기록 QP를 오류 상태로(시험 스위치) | `@gc` 5 | 다시 짝 맺기 |
| `gc4_ud_drop_rejoin` | rank 3 kill, 예비 프로세스의 첫 REJOIN datagram을 버림 | `@gc` 5 | UD 잃음 |
| `gc4_credit_stall` | rank 2가 500 ms 동안 RECV를 다시 내지 않음 | `@gc` 5 | credit |
| `gc4_kill3_ow_spareabsent` | rank 3 kill, launcher에 예비 프로세스 없음 | `@gc` 5 | 곧바른 fallback |
| gin-mirror 회귀(tcp) | gin-mirror 7절의 비용 밖 셀 전부를 이름과 env 그대로 | `@gct` 그 실험의 n | 회귀 |
| gin-mirror 회귀(rdma) | 같은 셀 | `@gc` 그 실험의 n | 회귀와 다시 예측 |
| 비용 가족 probe | 지표 `lat4k`, `lat256k`, `bw256k`, 노드 둘; 팔 `probe-off`, `probe-on`(`@gcp`), `tcp`(`@gctp`); gin-restore 9.15.6의 섞기 틀 | 팔마다 6 | 비용 |
| 빌드 검사 | 매크로 없는 프로그램 넷과 라이브러리 장치 객체를 `mi`와 비교(네 빌드 모두) | 빌드 검사 | 회귀 |
| CPU 시험 `gate_fenced` | main thread가 먼저 끝나고 다른 thread가 500 ms 더 사는 프로그램에서 옛 관문과 FENCED 관문 | 10 | 관문 |

- kill 셀은 gin-mirror처럼 실행기가 기록한 PID로 트래픽 중 kill한다. 멈춤 셀의 SIGSTOP과 SIGCONT도 실행기가 자기가 띄운 rank의 정확한 PID에만 보내고, 끝에
  CONT 뒤 그 PID에 SIGKILL로 정리한다.
- 비용 셀은 READ가 켜진 rdma 빌드와 끈 rdma 빌드를 같은 바이너리에서 `NCCL_GIN_TS_PROBE_MS=0`으로 가른다. tcp 팔은 회귀 대조다.
- gin-mirror 회귀 셀의 수는 시행 188(비용 밖)이라 두 빌드를 합치면 약 380 시행이다 `[측정: 문서 ../mirror/README.md의 시행 수(복원과 거절 168, 회귀 20)에서 셈; 추론]`. 줄일지는
  사전 등록에서 정한다.

## 8. 제외 기준과 중단 기준

초안이다. gin-mirror 8절(그리고 그 실험이 물려받은 gin-restore 8절)의 규칙을 그대로 쓰고 아래를 더한다.
- **제외(채점에서 빼고 채움).** gin-mirror의 제외 전부(kill이 첫 확정 무장 체크포인트 전, 셀이 정한 workload나 mirror 설정과 다르게 돈 시행 등). 더해서: launcher가
  시행 시작 때 두 노드 모두에서 준비되지 않은 시행(시작 문의 검사); 셀이 정한 제어 빌드, 펜스, 증인 설정과 다르게 돈 시행; 실행기의 SIGSTOP, SIGCONT, fork 자식
  주입 줄이 없거나 정한 시각보다 1 s 넘게 어긋난 시행. smoke와 pilot은 늘 제외.
- **중단(그 hold의 남은 시행을 멈추고 올림).** gin-mirror의 STOP 규칙 전부(CUDA 메모리 오류, 새 mlx5 명령 오류나 rain 펌웨어 명령 실패의 증가, 시행 뒤 남은
  프로세스, kv의 설정 오류나 NIC 오류, rain QUERY_QP 상한, pool 등록 실패, 남은 호스트 메모리, rain BAR1 시작 검사). 더해서:
  - launcher가 등록받지 않은 PID나 시작 시각이 다른 프로세스에 신호를 보내려 한 줄(launcher가 거절하고 적음; 하나라도 있으면 STOP_launcher).
  - 시행 뒤 멈춘(state T) 프로세스나 `gin_fdhold` 자식이 남음(실행기가 자기 PID에 CONT 뒤 SIGKILL, `pkill -x gin_fdhold`로 정리하고 STOP_left).
  - UD 경로 MTU가 2 048보다 작거나 rank 사이에서 다름(라이브러리가 rdma 길을 거절; 거절이면 그 hold를 시작하지 않음).
  - 기록 QP나 상태 페이지 READ QP의 비동기 이벤트(`ncclIbStats` 셈 > 0)가 시험 스위치 셀 밖에서 나옴.
- 다른 사용자 작업(gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 태그 작업)이 보이면 hold를 시작하지 않는다(`cluster_run.sh`의 시작 문). 이름으로 끄지 않고 실행기가
  기록한 PID만 끈다.

## 9. 설계와 실행 방법

### 9.1 제어 QP와 링

**QP 구성**(제어 경로 설계 2.1절; 모두 GIN PD 안 호스트 QP, 장치 코드 없음).

| 쓰임 | QP | 주인 스레드 | 속성 | 까닭 |
|---|---|---|---|---|
| 기록(지금 helper 소켓의 모든 종류) | GIN 문맥마다, 쌍마다 호스트 RC QP 하나. 양쪽이 자기 SQ로 SEND, 자기 RQ로 받음 | helper(준비 중에는 준비 스레드, 예비 프로세스는 driver가 쓰고 helper 시작 때 넘김; 지금 `pe.fd`를 넘기는 꼴, 10208) | timeout = `NCCL_IB_TIMEOUT`(14), retry 7, rnr_retry 7, RQ 64, max_rd_atomic 16(큰 자료 READ) | 재시도 초과가 데이터 QP와 같은 때(3.5–3.8 s) 와서 제어 길이 데이터 길보다 먼저 죽지 않게 함 `[측정: 문서 ack_timeout; 추론]` |
| 생존 READ | 쌍마다 호스트 RC QP 하나(SQ만) | 감시 스레드(`gdakiQ4Watch`, 20 µs 걸음, helper와 따로; 1280, 1300, 1590–1640) | 기록 QP와 같은 timeout, retry 7, max_rd_atomic 1, READ 시한 500 ms | helper는 펌웨어 단계(3 000 ms)나 라운드(25 000 ms) 안에서 막힐 수 있다(3274, 3282). 생존 확인이 helper에 매이면 안 된다 |
| 첫 만남, 다시 짝 맺기 | 문맥마다 UD QP 하나, Q_Key는 문맥 nonce의 아래 31비트 | helper | RQ 64 × (GRH 40 B + 2 KiB) | 아직 끝점을 모르는 상대(예비 프로세스, launcher, 오류 뒤의 쌍)와 연결 없이 첫 기록을 나눔. Q_Key가 다른 communicator의 datagram은 NIC이 버림 `[추론]` |
| launcher | rank마다, launcher마다 호스트 RC QP 하나 | rank 쪽 helper, launcher 쪽 단일 스레드 | 기록 QP와 같음 | 등록, 활성화 중계, 펜스, 종료 보고(9.5절) |
| 그대로 | 저장소 올리기, FETCH, mirror, NIC 복사 경로, GIN PD 루프백 | gin-mirror 그대로 | 바뀜 없음 | – |

- rank 4, launcher 둘이면 rank마다 새 호스트 QP 9개(기록 3, 생존 READ 3, UD 1, launcher 2), launcher마다 RC 4와 UD 1이다 `[추론]`.
- 호스트 QP 틀 `gdakiMiHostQpCreate`(16405–16578)를 RQ 깊이, 접근 비트, QP 종류, timeout을 인자로 받게 넓힌다(기본 인자는 지금 값). 모든 새 QP와 CQ는 자기
  `ncclIbStats`를 단다(널 문맥이면 net_ib 비동기 이벤트 스레드가 널을 역참조함; 16411–16435).
- CQ는 주인 스레드마다 따로다: helper의 CQ 하나(기록, UD, launcher QP)와 completion channel 하나, 감시 스레드의 CQ 하나(생존 READ QP). 두 스레드가 한 CQ를 걷지 않는다.
- **저장소 QP를 다시 쓰지 않는 까닭** `[소스, 추론]`: 맡긴 rank와 짝 사이에만 있고, 주인이 application 스레드이며, 그 QP가 오류면 다시 잇는 STORE_REQ가 제어
  길이라 고리가 생기고, 체크포인트마다 30 MiB WRITE(부하에서 19.1–19.4 ms, p99 20.1–24.1 ms `[측정: 문서 gin-mirror 9.8절 확인 3]`) 뒤에 기록이 줄을 선다.

**링과 흐름 제어.** rank마다 호스트 받기 영역 하나를 두고 보내는 상대마다 자리 64개(자리마다 2 KiB = 기록 1 872 B + 봉투 64 B)로 나눈다. 그 쌍 기록 QP의 RQ에
자리마다 RECV를 미리 내고, 보내는 쪽의 SEND 하나가 다음 RECV 하나를 쓴다. 영역의 MR은 LOCAL_WRITE만 주어 상대가 RDMA로 쓸 수 없다. rank 4, launcher 둘이면
(3 + 2) × 128 KiB = 640 KiB다.
- SEND/RECV를 고른 까닭: CQE가 completion channel로 helper의 `poll()`을 곧바로 깨우고(지금 helper는 소켓 묶음을 `poll(…, 1 ms)`로 기다림, 17808), CQE는 자료가 놓인
  뒤에 오며, 받는 메모리에 원격 쓰기 권한이 필요 없다. WRITE with immediate는 같은 비용에 원격 쓰기만 더하고, WRITE와 순번 낱말 폴링은 깨우기가 없어 기록마다
  0–1 ms 늦음이 PAUSE, PAUSED, RESUME 같은 차례에 쌓인다 `[추론]`.
- credit: 보내는 쪽은 보낸 순번 S와 받는 쪽이 다 쓴 수 C를 알고 S − C < 64일 때만 SEND를 낸다(그래서 RNR이 없음). C는 거꾸로 오는 기록의 봉투, 받는 쪽 상태
  페이지의 `rxConsumed` 칸(감시 스레드의 READ가 이미 가져옴), 그리고 막혔을 때만 helper가 기록 QP로 그 칸을 READ해서 온다. credit만 나르는 SEND와 원자 연산은 없다.
- 보내기는 막지 않는다: credit이 없으면 쌍마다 4 096 기록(약 7.6 MiB)의 보내는 쪽 대기열에 넣고, 차거나 시한이 지나면 지금 `gdakiTsSend`(8141–8162)의 "보내기
  실패"와 같은 값을 돌려준다. TCP의 커널 보내기 버퍼와 같은 노릇이다.
- helper는 CQ에서 꺼낸 기록을 상대마다의 받은 줄로 옮기고 자리의 RECV를 곧바로 다시 낸다. 지금 상대 소켓 하나를 읽는 자리(`gdakiTsPump`, 7곳)는 그 상대의 받은
  줄을 읽고, 거기서 지금의 park(`gdakiHoldDefer`, 상대마다 256개, 60 s; 5501–5510, 12965)로 간다. 상대마다 도착 차례는 지금과 같다.

**기록 형식.** 본문은 `struct gdakiTsMsg` 1 872 B 바이트 그대로이고, 앞에 64 B 봉투(`magic` 'GRCE', 판, 종류 RECORD/XFER/XFER_DONE/LAUNCHER/PAIR, 보낸 rank, 쌍의
세대, 순번, 거꾸로 credit, 문맥 nonce, 보낸 프로세스의 화신, 본문 길이)를 붙인다. 지금 종류 1–19, 32–38, 48–51은 그대로이고 비어 있는 52–63 가운데 넷만 새로
쓴다: 52 STALLED(멈춤 판정 방송), 53 DISPUTE(판정이 엇갈림), 54 FENCED(launcher가 보낸 것을 helper가 hold 기계에 넣음), 55 PROBE_SETUP(상태 페이지 단계에서만,
생존 READ QP 끝점을 helper 소켓으로 나눌 때). 모두 복원 기록 범위(11–63) 안이라 지금의 park 규칙을 따른다 `[소스: 5494]`. launcher와의 말은 기록이 아니라 고정
256 B 구조이고, 그 안의 ACTIVATE는 지금 `gdakiRsActivate` 64 B를 바이트 그대로 싣는다.

**큰 자료(outbox).** rank마다 8 MiB 호스트 영역(반 둘, REMOTE_READ만). 주는 쪽이 반 하나를 채우고 XFER(자리, 길이, rkey, 전송 번호, 끝 표시)를 보내면 받는 쪽이
READ하고 XFER_DONE을 돌려준다. 쓰는 곳은 STATE(로그 내보내기, 시험 셀에서는 KiB 단위), rkey 목록, 활성화 덩어리다. mirror 끈 길의 체크포인트와 FETCH는
outbox가 아니라 있는 RDMA 저장소 길(저장소 올리기 QP, FETCH QP; 16405–16676을 mirror 끔에도 쓰게 고침)로 간다(사용자 결정 7; 처음 설계 초안은 두 길을 함께
적었고 리뷰가 저장소 길 하나로 정함, 설계 v2 반영 대기). 반 4 MiB를 약 12 GB/s READ로 약 0.35 ms라 약 10 GB/s, 1 GbE 자료 소켓(약 110 MB/s)의 약 90배다 `[추론]`.

**차례와 잃음의 뜻**(사용자 결정 6: TCP 연결의 뜻과 같게 해서 hold, park, 라운드 코드를 바꾸지 않음).

| 지금(TCP) | RDMA 제어 | 근거 |
|---|---|---|
| 한 연결 안에서 차례대로, 빠짐과 겹침 없음 | 한 세대 안에서 RC가 차례대로. 받는 쪽은 순번 = 마지막 + 1을 확인하고 어긋나면 연결 잃음으로 침 | RC의 차례 규칙 `[추론]` |
| 연결을 잃으면 보내기 버퍼의 기록이 사라짐(STORE_ACK 꼬리가 잃은 CKPT_STABLE을 고침) | 기록 QP가 오류면 그 세대의 ACK 안 된 기록이 사라짐. 다시 짝 맺기가 세대를 올리고 받는 쪽은 옛 세대 봉투를 버림 | 15967–15971 |
| 다시 걸기(HELLO, HELLO_ACK, 세대) | UD 다시 짝 맺기, 세대 + 1. 증인의 다시 걸기는 증인 노릇으로만 | 8551–, 8437 |
| 라운드 안(커밋 전)의 FIN이나 reset은 라운드 취소 | 라운드 안의 기록 QP 오류가 라운드 취소, 상대는 "모름" | 11707 |
| BYE 뒤 FIN = 떠남 | BYE를 링으로 보내고 완료를 본 뒤 증인에도 BYE를 보내고 닫음. 떠남 판정은 증인의 "BYE 뒤 FIN" 그대로 | 8164–8212 |

**짝 맺기(UD).** datagram 하나 = 봉투 + 기록 1 872 B(또는 PAIR 구조)라 경로 MTU ≥ 2 048이 필요하다(사용자 결정 9). 차례는 지금 연결 차례처럼 낮은 rank가 시작한다
(17946–18158): (1) 시작 쪽이 기록 QP와 생존 READ QP를 INIT로 만들고 PAIR(두 끝점, 세대, 화신, nonce)를 상대 UD로, 답이 없으면 500 ms마다 다시; (2) 받는 쪽이
자기 QP를 RTR, RTS로 잇고 PAIR_ACK를 UD로, 같은 PAIR가 다시 오면 같은 답을 다시; (3) 시작 쪽이 RTR, RTS로 잇고 첫 RC 기록 CONNECTED를 보냄(받는 쪽은 그때까지
그 QP로 보내지 않음). 받는 QP가 RTR 전이면 RC 패킷이 버려지고 floor 때문에 다시 보내기가 536.9 ms 간격이 되므로 이 차례가 필요하다 `[측정: 문서 ack_timeout;
추론]`. 한도는 준비 `NCCL_GIN_TS_CONNECT_MS`(15 000), 다시 짝 맺기 `NCCL_GIN_TS_RECONNECT_MS`(10 000)이고, PAIR의 화신은 지금의 재연결 펜싱 규칙(gin-mirror 9.9절
표의 마지막 행)으로 가른다. 같은 차례가 준비의 모든 쌍, 오류 뒤 다시 짝 맺기, rank와 launcher, 예비 프로세스의 REJOIN을 덮는다.

### 9.2 상태 페이지

**배치.** rank마다 4 KiB 호스트 영역 하나(REMOTE_READ만)에 64 B 줄을 놓는다. 줄 0이 생존의 핵심이다.

```
struct gdakiCtrlPageCore {     // 줄 0, 64 B
  uint64_t ver;                // 줄 안 seqlock: 홀수 = 쓰는 중
  uint64_t watchBeat;          // 감시 스레드가 1 ms마다 올림(프로세스가 돈다)
  uint64_t helperBeat;         // helper 박동의 사본(helper가 돈다)
  uint64_t helperBusySinceUs;  // 펌웨어 단계나 라운드 시작, 0이면 바쁘지 않음
  uint64_t appStep;            // 마지막 ncclGinRestoreStep의 단계(보고만)
  uint32_t lastStableCkpt;     // 마지막 확정 체크포인트
  uint32_t incarnation;        // 이 rank를 맡은 프로세스의 화신
  uint32_t nonce32;            // 문맥 nonce의 아래 32비트
  uint16_t pageVersion, flags; // 떠나는 중(BYE 보냄), 복원 켬, mirror 켬
};
// 줄 1..: 줄마다 { uint64_t ver; 7 x uint64_t }
//   계보 보기(논리 rank마다 국면, cur, dead, hold 상태), livenessView(상대마다 마지막으로 박동이 는 때),
//   rxConsumed(상대마다 몫 고리에서 다 쓴 수), hold 요약(상대마다 상태, 화신, FENCING/FENCED)
```

- 박동을 둘로 나눈다: `watchBeat`는 "프로세스가 돈다", `helperBeat`는 "helper가 돈다"다. `watchBeat`가 오르고 `helperBeat`만 멈췄고 바쁨 시각이 한도 안이면
  "helper 바쁨"이다. 단계 번호와 체크포인트는 보고에만 쓴다(라이브러리는 application의 단계 간격을 모름).
- **일관성.** 페이지 전체의 seqlock은 쓰지 않는다: RDMA READ가 여러 캐시 줄을 어떤 차례로 읽는지 정해져 있지 않아 머리의 순번이 짝수여도 본문이 찢길 수 있다
  `[추론]`. 줄마다 `ver`를 홀수로(release) → 본문 → 짝수로(release) 쓴다. x86 저장 차례 아래에서 NIC이 한 캐시 줄을 한 순간의 모습으로 읽는다면 짝수 `ver` 줄은 그
  판이 다 들어 있다 `[추론; 한 줄 읽기의 원자성은 미확인, 9.8절 실행 가능성 확인]`. 홀수인 줄은 다음 pass에 다시 읽고 정체로 치지 않는다. 생존 판정은 줄 0만 쓴다.
  `nonce32`나 `incarnation`이 기대와 다르면 페이지 자리가 바뀐 것(되살린 프로세스)으로 보고 끝점 표에서 다시 읽는다.
- **쓰는 쪽.** 감시 스레드 하나(쓰는 쪽이 하나여야 함). helper와 다른 스레드는 원자 변수에 값을 두고 감시 스레드가 1 ms마다 옮겨 쓴다. 쓰는 것은 호스트 메모리뿐이다
  (장치, PCIe 쓰기, 펌웨어 명령 없음).
- **읽는 쪽.** 감시 스레드가 gated이고 거절 안 된 상대마다 100 ms마다 하나만 띄운다(줄 전부). 증인 FIN이나 RST, 기록 QP 오류를 helper가 알리면 곧바로, 확인 창
  W(20–50 ms) 뒤 한 번 더 줄 0을 읽는다(확인 READ; 처음 초안의 5 ms는 리뷰가 바꿈, 설계 v2 반영 대기). credit이 0일 때만 helper가 `rxConsumed` 줄을 READ한다. 짝의 무장은 맡은 rank의 `lastStableCkpt`와 launcher 페이지의 "예비 자리
  준비"를 본다.
- **계보 입력이 아니다.** 페이지는 판정과 보고의 입력이고, 계보 classify의 입력은 지금처럼 기록의 칸뿐이다(gin-mirror 9.9절의 oracle 시험이 그대로 선다).
- **비용** `[추론]`. READ 하나는 rank 4면 256 B, 상대마다 100 ms에 하나라 rank마다 초당 30번, 약 7.7 KB/s다. 데이터 QP가 아니라 put의 WQE 차례와 겹치지 않지만
  같은 포트와 PCIe를 나누므로 비용 셀이 잰다. 고정 메모리는 페이지 4 KiB, 링 640 KiB, outbox 8 MiB로 rank마다 약 8.7 MiB, 모두 호스트라 BAR1을 쓰지 않는다.
  gin-mirror의 4 KiB put 지연(off 팔) 11.26–12.29 µs `[측정: 문서 gin-mirror 2절]`에서 2 %는 0.23–0.25 µs이고, 이것은 그 실험의 pilot 사이 퍼짐(약 9 %)보다 작다.
  그래서 판정식의 2 %가 실행 사이 잡음 아래일 수 있다 `[추론]`. pilot에서 같은 팔 사이 퍼짐을 보고 사전 등록에서 정한다.
- **등록 차례.** 죽는 프로세스에서 MR이 QP보다 먼저 사라지면 READ는 원격 접근 오류(마지막 ACK 뒤 0.38–3.51 ms), QP가 먼저면 응답 없음(3.51–3.76 s)을 받는다
  `[측정: 문서 teardown_order]`. 페이지 MR은 준비 때 생존 READ QP보다 먼저 등록되므로 원격 접근 오류는 드물 것이다 `[추론]`. 판정은 원격 접근 오류에 기대지 않는다.

### 9.3 생존 판정 표

**신호마다의 시간.**

| 신호 | 언제 오나 | 근거 |
|---|---|---|
| 증인 FIN(BYE 없음) | SIGKILL 뒤 첫 오류 CQE보다 늘 먼저(270/270, 가장 작은 여유 0.43 ms), 지금 판정은 kill 뒤 약 0.1 ms | `[측정: 문서 teardown_order]` |
| 증인 "모름"(ETIMEDOUT) | 약 5 s(keepalive와 `TCP_USER_TIMEOUT`) | `[소스: 8122–8133]` |
| READ 응답 없음(재시도 초과) | floor 켬, retry 7에서 timeout과 상관없이 약 3.66 s; 죽은 상대 QP가 먼저 사라질 때 3.51–3.76 s | `[측정: 문서 ack_timeout, teardown_order]` |
| READ 원격 접근 오류 | 페이지 MR이 QP보다 먼저 사라질 때만, 0.38–3.51 ms | `[측정: 문서 teardown_order]` |
| READ 시한(띄운 READ가 500 ms 넘게 안 끝남) | 500 ms. 살아 있는 상대(멈춘 상대 포함)는 NIC이 답하므로 수 µs | `[측정: 문서 live_peer, 멈춘 상대의 쓰기 3.7–8.2 µs 완료; 추론]` |
| launcher 종료 보고(pidfd) | 스레드 그룹이 끝날 때. 원래 프로세스가 `/proc`에서 사라지기까지는 4 KiB 105.3–146.6 ms(n 44), 학습 모양 168.0–210.4 ms(n 10) | `[측정: gin-mirror 본 실행 activate_ms를 다시 셈; pidfd 때와 같은지는 미확인]` |
| 박동 정체 | 페이지 쓰기 1 ms, READ 100 ms마다 | 9.2절 |

**판정 표.** 입력은 생존 READ의 결과, 기록 QP 상태, 증인, launcher 보고다(있으면 launcher 보고가 가장 강함). "박동"은 줄 0의 `watchBeat`다.

| 생존 READ | 기록 QP | 증인 | launcher | 판정 | 반응 |
|---|---|---|---|---|---|
| 성공, 박동 늚 | RTS | 정상, 모름, 없음 | – | 살아 있음 | 없음. 증인이 모름이면 증인만 다시 건다(8 s 관리망 끊김이 여기) |
| 성공, 박동 늚 | RTS | FIN 또는 RST(BYE 없음) | – | 살아 있음, 증인 잃음 | 증인을 다시 걸고 줄 하나. 지금은 이 경우가 곧 죽음이다(사용자 결정 5로 바뀜) |
| 성공, 박동 늚 | 오류 | 아무것 | – | 살아 있음, 기록 길 잃음 | 라운드 안이면 취소, UD 다시 짝 맺기. 그동안 상대는 "모름" |
| 성공, `watchBeat` 늚, `helperBeat` 정체, 바쁨이 한도 안 | 아무것 | 아무것 | – | helper 바쁨 | 없음. 한도를 넘으면 아래 정체 행으로 |
| 성공, 박동 정체 2 000 ms 이상 | 아무것 | 정상, 모름, 없음 | 살아 있음 또는 없음 | 의심 | 줄 하나 |
| 성공, 박동 정체 10 000 ms 이상, 다른 생존 rank들도 그만큼 못 봄(분할 막이), 그 상대의 rmsn이 최근 1 000 ms 안에 늘지 않음(데이터 경로 거부권) | 아무것 | 정상, 모름, 없음 | 살아 있음 또는 없음 | 소프트웨어 멈춤 | STALLED 방송. 무장됐고 `FENCE=lineage`면 펜스 뒤 복원(9.4절), 아니면 거절 |
| 성공, FIN 때 READ와 확인 창 W(20–50 ms) 뒤 READ에서 박동 그대로 | 아무것 | FIN 또는 RST(BYE 없음) | – | 끝남 | 강한 증거(원인 FIN+STALE). hold 또는 거절(설계 v2 반영 대기) |
| 원격 접근 오류만 | 아무것 | 정상, 모름, 없음 | 살아 있음 또는 없음 | 판정 없음 | 페이지 rkey를 다시 받음(되살린 rank는 새 rkey). 원격 접근 오류 하나로는 끝남이 아니다: 살아 있는 상대도 같은 코드를 낸다(리뷰; 설계 v2 반영 대기) |
| 원격 접근 오류 + 둘째 신호(FIN, 박동 정체, 종료 보고) | 아무것 | 아무것 | 아무것 | 끝남 | 강한 증거(REMACC + 둘째 신호; 설계 v2 반영 대기) |
| 시한 넘음 또는 응답 없음 | 아무것 | FIN 또는 RST(BYE 없음) | – | 끝남 | 강한 증거(FIN+NORESP) |
| 응답 없음(재시도 초과) | 아무것 | 모름 | 응답 없음 또는 없음 | 노드 또는 선 닿지 않음 | 죽음으로 거절, 원인 LINKDOWN. 예비 프로세스가 같은 노드라 복원하지 않음 |
| 응답 없음(재시도 초과) | 아무것 | 정상 | 살아 있음, 그 PID 있음 | 그 프로세스의 RDMA 길만 깨짐 | 다시 짝 맺기를 3번까지, 그다음 "모름" 거절(강한 증거 아님) |
| 응답 없음(재시도 초과), 그 전 박동 정체 | 아무것 | 없음(증인 꺼짐) | 없음 | 끝남 | 강한 증거(멈춘 박동 뒤 응답 없음) |
| 아무것 | 아무것 | 아무것 | 종료 보고(PID와 시작 시각이 등록과 같음) | 끝남, 펜스 끝 | 가장 강한 증거(EXITED). 그 화신은 곧바로 FENCED |
| 아무것 | 아무것 | BYE 뒤 FIN | 아무것 | 떠남 | 지금과 같음 |
| 아무것 | 링의 BYE(또는 launcher에 낸 떠남 알림 LEFT) 뒤 | 아무것 | 종료 보고 | 떠남 | hold 없음. 정상 종료가 만드는 종료 보고를 죽음으로 읽지 않는다(리뷰가 찾은 거짓 hold; 증인을 꺼도 섬; 설계 v2 반영 대기) |
| 시한만 넘음(재시도 초과 전) | 아무것 | 정상, 모름 | 아무것 | 판정 없음 | 줄 하나, launcher 페이지를 곧바로 읽어 보고에 적음 |

- 마지막 행이 "제어 길이 데이터 길보다 먼저 죽지 않게"의 규칙이다: READ 시한 500 ms만으로는 아무것도 하지 않고, 노드와 선 판정은 하드웨어 재시도 초과(데이터
  QP와 같은 3.5–3.8 s)나 FIN, launcher 보고가 있어야 한다. 이 규칙은 제어 경로 설계의 권고이고 사용자 결정 열넷의 목록에 따로 적혀 있지 않다(9.7절 행).
- 노드 죽음과 선 끊김은 RNIC 쪽에서 가를 수 없다(launcher와 rank가 같은 선을 씀). 증인이 정상인데 RNIC 쪽이 모두 응답 없음이면 "선", 둘 다 응답 없음이면 "노드
  또는 두 선"이다. 결과(복원 안 함)는 같고 원인 줄만 다르다 `[추론]`.
- 표의 빈칸 `[미확인]`: READ 응답 없음 + 증인 정상 + launcher 보고 없음(보고를 끈 시험 스위치)인 경우가 행에 없다. `gc4_fdhold_sock_kill3_noreport`는 그래서 증인도
  끈다. 이 칸의 뜻은 독립 리뷰에서 정한다(9.7절).
- hold의 강한 증거 원인 이름은 넷이 된다: EXITED(BYE나 LEFT가 없을 때), FIN+STALE, FIN+NORESP(확인 창 안에 READ가 끝나지 않음), REMACC + 둘째 신호(그리고 증인
  꺼짐의 "멈춘 박동 뒤 응답 없음"). "ECONNREFUSED"는 증인의 다시 걸기에만 남는다. tcp 빌드는 옛 동작 전체(FIN = 죽음, 거절 1 000 ms, `/proc` 관문, TCP 활성화와
  자료 소켓, launcher 없음)를 되살리는 회귀 팔이고, RST 뒤 거절 간격은 그 빌드의 매개변수로만 둔다(설계 v2 반영 대기).

**문턱.**

| 이름 | 기본 | 뜻 | 8 s 관리망 끊김과의 관계 |
|---|---|---|---|
| `NCCL_GIN_TS_PROBE_MS` | 100 | READ 주기(0이면 생존 READ를 끔; 비용 셀) | 무관 |
| `NCCL_GIN_CTRL_PROBE_TIMEOUT_MS` | 500 | 띄운 READ의 시한(의심과 보고만, FIN과 겹치면 강한 증거) | 무관 |
| `NCCL_GIN_CTRL_FIN_CONFIRM_MS` | 20–50(초안의 5에서 바꿈) | FIN 뒤 확인 창 W: W 동안 박동이 그대로이거나 W 안에 READ가 끝나지 않으면 FIN과 겹쳐 강한 증거. pilot의 장애 없는 박동 간격 최대의 몇 배로 정함. FIN이 있을 때만 쓰는 짧은 시한이라 floor 규칙(9.7절)과 함께 사용자 결정을 받음(설계 v2 반영 대기) | 무관 |
| `NCCL_GIN_TS_SUSPECT_MS` | 2 000 | 의심(체크포인트 멈춤 시한과 같음, 14168) | 의심 줄만 |
| `NCCL_GIN_TS_STALL_MS` | 10 000 | 소프트웨어 멈춤. 투명해야 하는 8 s 정지와 8 s 끊김보다 길고 hold 시한 20 s의 절반 | 판정 없음 |
| `NCCL_GIN_TS_STALL_RMSN_MS` | 1 000 | 데이터 경로 거부권의 창(GPU가 아직 보내는 상대는 판정하지 않음) | 무관 |
| `NCCL_GIN_TS_PROBE_FAIL_N` | 3 | 증인 정상 + READ 응답 없음의 다시 짝 맺기 횟수 | 무관 |
| `NCCL_GIN_TS_RST_REFUSAL_GAP_MS` | 100 | tcp 빌드에서 RST 뒤 1 000 ms 안의 거절 간격(1 000이면 옛 동작) | 무관 |
| `NCCL_GIN_RESTORE_FENCE` | `lineage` | `lineage`: 멈춤 판정 뒤 펜스와 복원. `none`: 거절만 | 무관 |

범위 검사(준비 합의, 모든 rank가 같은 값): `10 × PROBE_MS ≤ SUSPECT_MS < STALL_MS`, `STALL_MS + 1 000 ≤ NCCL_GIN_RESTORE_MS`, `PROBE_TIMEOUT_MS ≥ 5 × PROBE_MS`,
`FIN_CONFIRM_MS`는 장애 없는 박동 간격 최대의 몇 배 이상. 장애 없는 단계 간격의 최대는 41.74 ms였다는 계산이 감지 설계에 있다(10 000 ms는 그 240배) `[미확인: 이 문서에서 다시 세지 않음]`.
`PROBE_TIMEOUT_MS` 500의 근거는 부하에서 가장 긴 호스트 RC 전송(30 MiB WRITE p99 24.1 ms)이고, 256 B READ의 부하 꼬리는 재지 않았다 `[미확인]`. pilot의 READ
지연 최대로 고정한다.

**판정 시각의 어림** `[추론]`.
- SIGKILL(FIN 있음): FIN은 kill 뒤 약 0.1 ms. 처음 초안은 확인 READ 둘(5 ms 간격)로 약 5–6 ms를 어림했으나, 리뷰가 그 어림이 측정된 정리 차례와 맞지 않음을
  찾았다: fd는 번호가 큰 것부터 풀리고(275/275), 첫 오류 CQE는 FIN 뒤 0.43 ms부터 오며, MR을 먼저 등록하면 QP가 먼저 사라진다 `[측정: 문서 teardown_order]`.
  그래서 FIN 뒤 둘째 READ는 대개 이미 사라진 QP에 닿아 끝나지 않는다. 확인 창 W(20–50 ms)를 두면 판정은 FIN + W(READ가 W 안에 끝나지 않음)이거나 launcher의
  종료 보고(105–147 ms) 가운데 이른 것이다 `[추론]`. 3절의 범위 20–250 ms는 이 어림이고 `[초안, 설계 v2 뒤 확정]`이다. 원인마다의 수는 보고한다.
- RST: 같은 확인 READ 길이라 RST에서 판정까지 FIN과 같은 크기다. tcp 빌드는 RST 뒤 첫 거절(1.1–1.3 ms 뒤 `[측정: 문서 감지 설계의 다시 셈]`) + 100 ms라
  100.5–106 ms다.
- FIN 없는 죽음, 보고 있음: 원래 프로세스의 스레드 그룹이 끝날 때(4 KiB 약 105–147 ms). 보고 없음(증인도 끔): 정리 중 QP가 사라진 뒤 첫 READ가 재시도 초과까지
  3.51–3.76 s, 그 앞에 정리(약 0.15 s)와 READ 주기(≤ 0.1 s)가 더해져 kill 뒤 약 3.6–4.0 s, 여유를 두어 3.5–4.5 s.
- 멈춘 상대: STOP 뒤 박동이 멈추고 10 000 ms + 판정 pass(≤ 2 × 100 ms)라 10 000–10 300 ms. 생존 rank들이 같은 상대의 페이지를 같은 주기로 읽으므로 판정 시각이 2 × 100 ms
  안에 모인다.

### 9.4 펜스: 계보의 국면

**왜.** 멈춘 상대는 살아 있고 그 QP는 RTS다. 복원은 생존 rank의 같은 QPN을 예비 프로세스에 다시 잇고(3068–3069), RC 요청에는 보낸 QP 번호가 없어 옛 프로세스의
쓰기를 가리는 것은 PSN뿐이다 `[추론]`. 깨어난 옛 화신의 중복 WRITE를 응답 쪽이 다시 쓰는지는 `[미확인]`이다. 그래서 복원 전에 옛 화신을 끝내고 그것을 확인한다
(사용자 결정, 저녁: 깃발은 하드웨어 쓰기를 막지 못하므로 QP 끊기와 종료 확인이 실행 내용이다).

**차례.**
1. **QP를 오류 상태로.** 멈춤을 판정한 생존 rank가 hold를 시작하면 시작 정지가 p로 가는 사용자 QP와 mirror QP를 2ERR로 바꾼다(13193 영역, 지금 그대로). 같은 자리에서
   p와의 기록 QP와 생존 READ QP도 오류 상태로 바꾼다. 그때부터 옛 프로세스가 깨어나도 생존 rank에 기록이나 READ 응답이 닿지 않는다.
2. **모두 보고.** 생존 rank마다 HOLDING(p, i)를 링으로 짝에게 보낸다(지금 그대로).
3. **종료 요청.** 짝은 모든 HOLDING이 모이면 p의 국면을 FENCING으로 두고 p 노드의 launcher에 FENCE(p, i, PID, 시작 시각)를 보낸다. launcher는 `pidfd_open`과 시작
   시각을 확인하고 `pidfd_send_signal(SIGKILL)`(멈춘 프로세스도 받음)로 종료한 뒤, pidfd가 읽기 가능해질 때(스레드 그룹이 끝남) FENCED(p, i)를 모든 rank의 launcher
   QP로 보낸다. 끝나지 않으면(D 상태) 보내지 않고 hold 시한의 fallback이 받는다.
4. **FENCED.** 생존 rank의 helper는 FENCED(p, i)를 계보에 넣는다(54번 기록과 같은 처리). 짝은 자기 계보가 FENCED일 때만 ACTIVATE를 낸다.
5. **kill로 끝난 경우.** launcher는 등록된 rank의 pidfd를 늘 쥐고 있어 프로세스가 스스로 끝나면 종료 보고(EXITED)를 모든 rank에 보낸다. 그 화신은 그 순간 FENCED다.
   그래서 SIGKILL 셀에서는 3번의 종료 요청이 필요 없고 펜스는 원래 프로세스의 정리 시간에 끝난다. 지금 관문의 'later' 기다림과 같은 크기다 `[추론]`.
6. **활성화**(9.5절).

**국면.** gin-mirror 9.9절의 국면(LIVE, HOLD_WAIT, HOLD_SUCC, ENDED, BAD)에 둘을 더한다. 보기 함수 `gdakiLnViewOf`의 입력에 (rank, 화신)마다의 펜스 표시를 더한다. 펜스 표시는 hold 칸의 CAS를 바꾸지
않는 따로 된 낱말이다(리뷰; 설계 v2 반영 대기).

| 국면 | 조건 | 들어가는 사건 | 받아들이는 것 |
|---|---|---|---|
| HOLD_WAIT | 칸이 붙잡은 상태, known = 칸 화신, 펜스 표시 없음 | 강한 죽음 증거나 멈춤 판정 + 무장 | HOLDING 모음 |
| FENCING(새) | 같고 짝이 FENCE를 보냄 | 모든 HOLDING 모임 | FENCED, EXITED; ACTIVATE와 REJOIN은 받지 않음 |
| FENCED(새) | 같고 그 화신의 FENCED나 EXITED를 받음 | FENCED, EXITED(hold 전에 온 EXITED는 그 화신에 표시를 미리 둠) | ACTIVATE(dead + 1), 그 뒤 REJOIN |
| HOLD_SUCC | 칸이 붙잡은 상태, known = 칸 화신 + 1 | REJOIN(dead + 1) 받아들임 | 지금 그대로 |

- classify 표의 FENCING, FENCED 행은 HOLD_WAIT 행과 같다(x < dead는 STALE, x = dead는 HELD_OLD, x > cur는 FUTURE). 바뀌는 것은 상태 조건 열이다: ACTIVATE와 REJOIN
  받아들임에 "FENCED"가 더해진다. 단위 시험 oracle의 다름 목록은 이 두 행과 관문 행만이어야 한다.
- 활성화 관문(`gdakiRsActExamine`, 4550)의 "Z = GO"를 없애고 활성화 기록이 FENCED를 실었을 때만 ACCEPTED한다. 예비 프로세스는 `/proc`을 스스로 보지 않는다.
  gin-mirror의 빠른 모드(Z를 끝남으로 봄, 8/95)는 사라진다.
- `NCCL_GIN_RESTORE_FENCE=none`이면 멈춤 판정은 거절만 하고 생존 QP는 오류로 남는다(옛 쓰기는 버려짐). fail-fast이거나 예비 프로세스가 없어도 같다.
- **불변식.** 논리 rank p로 가는 생존 rank의 QP(사용자, mirror, 기록, 생존 READ)는 p의 옛 화신 스레드가 하나라도 남은 동안 RTS가 아니다. 예외는 fd를 물려받은
  자식이다: helper와 증인 소켓은 fork 때 닫지만(`pthread_atfork`), uverbs fd는 막지 못한다. 자식이 uverbs fd까지 쥐면 부모가 끝나도 QP와 GPU 문맥이 남아 READ가
  성공하고 박동만 멈춘다. 그 셀은 복원하지 않고 거절만 하고 한계로 적는다(사용자 결정 13).
- 페이지의 계보 보기는 판정과 보고에만 쓰고 classify 입력이 아니다(9.2절).

### 9.5 launcher

- **무엇.** 노드마다 하나, 늘 있는 작은 프로그램(시험 장치 쪽 C, verbs와 pidfd, Unix 소켓). 실행기가 hold 시작 때 띄운다(sunny는 ssh 하나). RNIC 쪽에 UD QP 하나,
  rank마다 RC QP 하나, 상태 페이지 하나(박동, 예비 자리 상태). 노드 안에 Unix 소켓 하나(사용자 결정 3: fd 전달 때문). 단일 스레드다.
- **하는 일.** (1) 같은 노드 rank의 pidfd를 쥐고 종료 보고(EXITED)를 모든 rank에 보냄, (2) FENCE를 받으면 원래 프로세스를 종료하고 끝남을 확인한 뒤 FENCED,
  (3) 짝의 ACTIVATE를 예비 프로세스에 넘기고 답을 돌려줌(사용자 결정 11), (4) 예비 프로세스가 아직 없거나 재생 중이면 LATER를 한 번 보내고 준비되면 마지막 답을
  보냄(사용자 결정 4; 짝은 20 ms마다 다시 묻지 않음), (5) SPAWN을 받으면 (rank, 새 화신)마다 한 번만 예비 프로세스를 띄움(사용자 결정 12, hold 시작 때; gin-dynamic이
  쓸 길), (6) 띄운 예비 프로세스의 pidfd를 쥐고, 끝나거나 한도 안에 준비되지 않으면 REFUSED.
- **안전.** launcher는 등록받은 (PID, 시작 시각)에만 신호를 보낸다. 다르면 거절하고 줄을 남긴다(8절 STOP). 이 프로그램의 실패는 그 노드 rank들의 복원만 막는다:
  launcher QP가 응답 없음이면 짝은 그 노드의 예비 경로가 없다고 보고 fallback한다.
- **등록.** 원래 rank는 체크포인트마다 STORE_REQ 꼬리(mirror 켬)나 올리기 머리(mirror 끔)에 예비 등록을 싣는다(17236–17247, 15661–15680). 지금은 관리망 주소 32 B,
  PID, 시작 시각이다. rdma 빌드에서는 (경로 종류 = launcher, launcher 노드 번호, PID, 시작 시각, 화신)으로 바꾸고 판 번호를 올린다(사용자 결정 10; 공유 인터페이스
  `impl/rs_store_api.h`의 규약 글이 바뀜). 무장 조건 "등록이 있음"은 "그 노드 launcher와 짝 맺기가 됐고 예비 모드가 켜짐"이 된다.
- **활성화와 REJOIN 차례.** (1) 펜스(9.4절); (2) 짝이 활성화 덩어리(rank마다 화신, UD 끝점, 페이지, outbox; 저장소와 pool 자리; FETCH QP 끝점)를 outbox에 쓰고
  ACTIVATE(64 B + 덩어리 자리)를 launcher에 보냄; (3) 예비 프로세스가 Unix 소켓으로 "받을 수 있음"(재생, FETCH 버퍼 등록, Resume 진입 뒤)을 알리면 launcher가 덩어리를
  READ해 기록과 함께 넘기고, 예비 프로세스의 ACCEPTED와 FETCH QP 끝점을 짝에게 넘김. FETCH의 READY와 DONE도 같은 중계로 감; (4) 할 수 없으면 곧바로 REFUSED, 짝은
  곧바로 fallback(지금의 "거절 둘과 1 000 ms" 규칙은 rdma 빌드에서 없어짐); (5) 예비 프로세스가 생존 rank마다 REJOIN(32번 바이트 그대로)에 자기 기록 QP와 생존
  READ QP의 끝점을 붙여 UD로 보냄. 생존 rank는 지금의 받아들임 규칙(HELD, known + 1, nonce, 받아들임 순간의 park 검사, 거절된 rank에 FAIL) + FENCED로 가르고,
  받아들이면 그 쌍의 기록 QP를 예비 프로세스의 QPN으로 다시 잇고 REJOIN_ACK을 UD로 보냄. 같은 REJOIN에는 같은 답(멱등). 그 뒤 TOKEN, READY, DONE_RS, RESTORED,
  INJECTED, STORE_REQ는 링으로. STATE는 예비 프로세스가 생존 rank의 outbox를 READ하고, rkey 목록은 생존 rank가 예비 프로세스의 outbox를 READ함.
- **세 길 견줌**(제어 경로 설계 5.3절; 사용자 결정 2로 닫음). launcher가 늘 있는 끝점이 되어 아직 없는 프로세스도 등록할 수 있다. 생존 rank의 상태 페이지에 다른
  rank의 끝점을 싣는 길은 첫 RC를 맺을 길이 여전히 필요해 혼자 서지 못하고, 첫 교환만 관리망 소켓으로 하는 길은 사용자 결정과 맞지 않는다. 앞서 되살아난 생존
  rank의 새 끝점은 활성화 덩어리의 표가 싣는다(gin-mirror의 결정 (3)과 같은 길).

**동적 예비 프로세스 리뷰가 찾은 TCP 전제 열다섯과 이 설계의 답.**

| 리뷰 행 | TCP에 기대던 것 | 이 설계에서 |
|---|---|---|
| 1 | 등록이 관리망 주소라 아직 없는 프로세스를 주소로 등록 | 늘 있는 launcher를 등록(노드 번호, PID, 시작 시각, 화신). QPN과 rkey를 미리 알 필요 없음 |
| 2 | 짝이 시도마다 새 TCP 연결(500 ms) | 준비 때 맺은 짝과 launcher의 RC QP로 ACTIVATE. helper를 500 ms 막던 보내기가 없어짐 `[소스: 13710]` |
| 3 | 거절 둘과 1 000 ms 규칙 | launcher의 명시적 답(REFUSED 곧바로, LATER 한도). launcher QP의 재시도 초과나 답 없음 1 000 ms면 fallback |
| 4 | 재생 전 활성화 소켓과 LATER thread | launcher가 대신 LATER(사용자 결정 4). 예비 프로세스에 일찍 답하는 thread와 넘기기 틈이 없음 |
| 5 | 'later'와 20 ms 다시 묻기 | LATER 한 번, 준비되면 마지막 답(사건 기반) |
| 6 | 활성화 연결이 FETCH 끝점, READY, DONE을 나름 | launcher 중계로 같은 차례(사용자 결정 11) |
| 7 | REJOIN과 그 뒤 기록, 자료 소켓 | UD REJOIN 뒤 RC 링, STATE와 rkey 목록은 outbox READ |
| 8 | 재생 비교와 all-gather에 실은 제어 QP 정보 | all-gather에는 rank마다 고정 칸만, 그 칸은 "달라도 되는 칸". 쌍마다의 QPN은 짝 맺기가 나눔(9.6절) |
| 9 | 포트 bind(EADDRINUSE)로 중복 막기 | launcher의 (rank, 화신) 중복 막기와 Unix 소켓의 같은 (rank, 화신) 둘째 접속 거절. 늦게 뜬 예비 프로세스는 launcher가 종료 |
| 10 | 화신마다 다른 포트 | 기록의 화신, `NCCL_GIN_RESTORE_SPARE_INC` 검사, Q_Key와 nonce |
| 11 | hold 시작의 launcher hook(짧은 TCP 기록) | launcher QP의 SPAWN WR 하나(막지 않음) |
| 12 | launcher와 실행기 사이(ssh, 관리망 TCP) | 시험 장치라 남음. 라이브러리 쪽 말은 모두 RDMA |
| 13 | 활성화 관문(`/proc`) | FENCED(9.4절) |
| 14 | 예상 시간의 "활성화 뒤 67–71 ms" | TCP 손잡기가 없어지므로 다시 잼(지금 67.2–71.4 ms, n 45 `[측정]`). 줄 것으로 보되 크기는 `[미확인]` |
| 15 | 죽음 판정과 hook 시각(TCP 거절 둘, RST 1 s) | 9.3절 판정 표와 launcher 종료 보고. 띄우기 시각의 기준 줄을 판정 줄이나 EXITED 줄로 |

### 9.6 준비, bootstrap, 그리고 관리망에 남는 것

**작업 시작.** GIN collComm의 준비 all-gather(18011)는 이미 RDMA(net_ib isend/irecv)다 `[소스: 18011; gin.cc 45–110]`. 그 기록 `gdakiTsAddr`(17920–17927)에 rank마다
고정 칸을 더한다: UD 끝점 40 B, 상태 페이지(주소, rkey, 길이 16 B), outbox(16 B), launcher(노드 번호, launcher UD 끝점 40 B, 있음 표시), 제어 길(tcp 또는 rdma; 다르면
그 문맥은 fail-fast, Resume 조건 하나 더). rank마다 약 120 B이고, 이 all-gather는 늘 모든 rank가 부르므로 수가 어긋나지 않는다 `[소스: 17885–17889]`. 쌍마다의 RC
끝점은 싣지 않는다(UD 짝 맺기가 나눔). 예비 프로세스는 이 all-gather를 기록으로 대답하고 자기 칸만 새 값으로 바꾼다. 새 칸은 재생 비교(`gdakiRsSpareSetupMatch`,
4700, 18021)의 "달라도 되는 칸"에 넣는다.

**준비 차례.** (1) UD QP, 링, 페이지, outbox를 만들고 같은 노드 launcher의 Unix 소켓에 붙어 PID와 시작 시각을 알리고 launcher의 UD 끝점을 받음, (2) all-gather,
(3) 모든 gated 쌍의 짝 맺기, (4) 모든 launcher와 짝 맺기, (5) MIRROR_SETUP 같은 helper 시작 전 기록을 링으로, (6) 증인 소켓(켰을 때, 지금 코드 그대로).

**관리망에 남는 것.**

| 무엇 | 왜 | 범위 |
|---|---|---|
| NCCL 자신의 bootstrap(`ncclCommInitRank`)과 net_ib 연결 맺기 | NCCL 핵심이 `NCCL_SOCKET_IFNAME` 소켓으로 함. 초기화 때만이고 이 계층 밖. 예비 프로세스는 기록으로 재생해 쓰지 않음 | 라이브러리, 초기화 |
| 증인 소켓(선택, `NCCL_GIN_CTRL_WITNESS`) | "노드 죽음"과 "RNIC 선 끊김"을 가르는 유일한 길(launcher와 rank가 같은 RNIC 선을 씀). BYE와 FIN만 | 라이브러리, 상시 |
| 실행기가 launcher와 rank를 띄우는 ssh, `cluster_run.sh`, 로그 모으기 | 시험 장치 | 라이브러리 밖 |

복원 계층의 기록, 등록, 활성화, REJOIN, 큰 자료, 펜스, 종료 보고는 초기화 뒤 관리망을 쓰지 않는다. 같은 노드 안의 파일과 Unix 소켓(초기화 기록, launcher
끝점)은 네트워크가 아니다. `no_tcp_control`(3절)이 시행마다 이것을 센다.

**UD MTU.** UD datagram 하나(봉투 64 B + 기록 1 872 B)가 들려면 경로 MTU ≥ 2 048이어야 한다. testbed의 PMTU는 4 096이다 `[측정: 문서 ack_timeout]`. 제어 경로 설계
리뷰가 사용자 결정 9의 확인을 했다: GIN 포트 rain `mlx5_1`, sunny `mlx5_0`의 `active_mtu`가 둘 다 4 096이고, gin-restore 실행 가능성 kv의 경로 MTU도 4 096이다
`[측정: 문서, 리뷰가 2026-09-23과 2026-10-09 캡처에서 읽음]`. RoCE의 `active_mtu`는 netdev MTU에서 나오므로 준비 때 rank마다 `ibv_query_port`로 다시 보고 두 끝의
값을 준비 합의에 넣으며, 시행 kv에 남긴다(설계 v2 반영 대기). 못 맞추면 그 문맥은 rdma 길을 거절한다(조각내기는 만들지 않음).

### 9.7 기존 장치와의 충돌 표

열: 기존 장치 / 무엇이 부딪칠 수 있나 / 이 설계가 피하는 길 / 상태 / 근거(`[소스]`는 9절 머리의 호스트 파일 줄). "결정 n"은 2026-10-16 21시 무렵 사용자 결정의 번호(1절)다.

| 기존 장치 | 무엇이 부딪칠 수 있나 | 이 설계가 피하는 길 | 상태 | 근거 |
|---|---|---|---|---|
| helper 단일 스레드 주인(helper 소켓은 helper만, 다른 스레드는 기록을 넘김) | 링, UD, launcher QP를 누가 내고 걷나 | 모두 helper. 준비 스레드와 예비 프로세스 driver는 helper 시작 전에만 쓰고 넘김. 생존 READ QP와 페이지 쓰기는 감시 스레드. CQ를 스레드마다 따로 | 닫힘(설계) | 10208, 6290–6296 |
| 상대마다의 park(256개, 60 s, 도착 차례) | 기록이 CQ에서 와도 같은 차례인가 | CQ에서 꺼낸 기록을 그 상대의 받은 줄로, 거기서 지금의 park로. 자리는 복사 뒤 곧바로 다시 냄 | 닫힘(설계) | 5501–5510, 12965 |
| 투명 복구 라운드(REQ, ACK, DONE, 라운드 안 소켓 잃음 = 취소) | 라운드 기록이 RDMA로, 취소 조건 | 기록 QP 오류가 소켓 잃음 자리. 라운드 코드는 전송을 갈아 끼우는 자리 뒤라 그대로 | 닫힘(설계) | 11707, 12210–12240 |
| 재연결 기계(HELLO, PROBE, 거절 둘, 펜싱) | 기록 길과 증인 | 다시 짝 맺기가 기록 길을 맡고, 증인의 다시 걸기와 펜싱은 증인 노릇으로만 | 닫힘(설계) | 8302–8388, 8551–, 9110–9114 |
| gin-harden의 BYE와 FIN, 강한 증거 | FIN만으로 죽음 판정 | FIN + 확인 창 W(20–50 ms)의 READ(9.3절). 떠남은 링의 BYE(와 LEFT)로 가르고 증인의 "BYE 뒤 FIN"은 보조. FIN 규칙을 쓰는 셀은 rdma 빌드에서 다시 예측 | 닫힘(결정 5, 2026-10-16); 확인 창의 값은 설계 v2 반영 대기 | 5706–5711 |
| 정상 종료와 launcher 종료 보고 | 시행 끝의 정상 종료가 종료 보고를 만들고, 차례가 정해지지 않은 BYE와 엇갈려 모든 시행 끝에 거짓 hold가 생길 수 있음(리뷰) | rank가 끝나기 전 링에 BYE, launcher에 떠남 알림(LEFT). BYE나 LEFT를 받은 rank의 종료 보고는 떠남이고 hold하지 않음 | 설계 v2 반영 대기 | 9.3절 판정 표 |
| 원격 접근 오류의 뜻 | 원격 접근 오류 하나를 "끝남"으로 보면 살아 있는 상대(되살린 rank의 새 rkey)를 죽음으로 봄(리뷰) | 둘째 신호를 요구. REJOIN과 REJOIN_ACK에 페이지와 outbox의 (주소, rkey, 세대)를 실음 | 설계 v2 반영 대기 | 9.3절 판정 표, `../../../teardown_order/README.md` |
| kill 판정 시각의 어림 | 처음 초안의 "약 5–6 ms"가 측정된 정리 차례와 맞지 않음(리뷰) | 확인 창 W 20–50 ms; kill 셀의 예측을 READ 확인 길과 launcher 보고 길로 다시 적음(3절은 범위와 `[초안, 설계 v2 뒤 확정]`) | 설계 v2 반영 대기 | 9.3절 |
| 다시 짝 맺기 때 기록 잃음 | 정확히 한 번 전달을 할까 | TCP와 같은 뜻(세대가 바뀌면 ACK 안 된 기록은 사라짐, STORE_ACK 꼬리의 고침 그대로) | 닫힘(결정 6, 2026-10-16) | 15967–15971 |
| REJOIN 받아들임 차례(HELD, known + 1, nonce, park 검사, 거절된 rank에 FAIL) | UD라 같은 REJOIN이 여러 번 옴 | 규칙 그대로 + FENCED + (from, 화신, 예비 QPN)으로 멱등. 같은 REJOIN에는 같은 REJOIN_ACK | 닫힘(설계, 리뷰 대상) | 4599–, 9213–9227, 13411–13421 |
| 계보 classify의 입력 | 페이지의 계보 보기를 입력으로 쓸까 | 쓰지 않음. 입력은 기록의 칸 그대로. 새 국면 FENCING, FENCED와 펜스 표시 입력(9.4절) | 닫힘(설계) | 7050–7113, gin-mirror 9.9절 |
| 계보 상태 조건(HELD만, 거절된 rank에 FAIL, PUBLISHED류, 무장 조건) | 새 국면이 상태 조건을 지울까 | 새 국면은 화신 축만 나타내고 ACTIVATE와 REJOIN의 상태 조건에 FENCED만 더함. oracle 다름 목록은 새 행과 관문만 | 닫힘(설계) | gin-mirror 9.9절 규칙 표 |
| 활성화 관문(`/proc`, Z = 끝남) | 옛 화신의 다른 스레드가 자원을 쥔 창 | FENCED 요구(펜스 국면). 빠른 모드 8/95 `[측정]`가 사라지고 관문 기다림이 launcher 보고로 | 닫힘(사용자 결정, 2026-10-16 저녁) | 4550–4592 |
| 멈춘 상대의 반응 | 판정 뒤 거절할까 되살릴까 | 펜스 뒤 복원, `NCCL_GIN_RESTORE_FENCE=none`으로 끌 수 있음 | 닫힘(사용자 결정, 2026-10-16 저녁) | 9.4절 |
| fork가 물려준 fd | 펜스 불변식의 구멍 | helper와 증인 소켓은 fork 때 닫음. uverbs fd까지 물려받은 셀은 거절만, 한계 | 닫힘(결정 13, 2026-10-16) | 8135–8138 |
| 노드 죽음과 선 끊김의 구분 | RNIC 쪽에서 가를 수 없음 | 증인이 가름. 결과(복원 안 함)는 같고 원인 줄만 다름. 다른 노드 예비 프로세스가 생기면 다시 봄 | 닫힘(한계, 18절에 적을 것) | 9.3절 |
| READ 응답 없음의 시간(floor 규칙) | 감지 설계가 기대한 약 130 ms가 이 NIC에서 3.5–3.8 s | 노드와 선 판정은 하드웨어 재시도 초과나 FIN, launcher 보고에만. READ 시한 500 ms는 의심과 보고만. floor 끄기는 하지 않음. FIN이 있을 때만 쓰는 확인 창 W(20–50 ms)를 함께 정함 | 열림(사용자 결정 대기: 설계 권고이나 사용자 결정 열넷의 목록에 없음; 리뷰도 결정을 받아 적으라고 함) | 9.3절; ack_timeout |
| 감지 설계와 제어 경로 설계의 주인 다툼 | 제어 QP와 상태 페이지를 누가 만드나 | QP와 MR의 생성, 짝 맺기, 페이지 배치의 판은 제어 경로 몫. 페이지 칸의 뜻, READ 주기, 판정은 감지 몫. 준비 all-gather는 하나 | 닫힘(설계) | 9.1, 9.2절 |
| TCP 제어 길을 남길까 | 회귀와 옛 결과의 재현 | 빌드 스위치(`gct`)로 회귀용으로만, 아무것도 지우지 않음. tcp 빌드는 옛 스택 전체(TCP 기록, TCP 활성화와 자료 소켓, FIN = 죽음, 거절 1 000 ms, `/proc` 관문, launcher 없음)를 회귀 팔로 되살림. 두 빌드의 이름, md5, 장치 기계어 비교를 적음. 처음 설계 초안은 실행 시 env와 마지막 단계의 지움을 적어 결정과 어긋났음(리뷰) | 닫힘(결정 1, 2026-10-16); 스위치 범위는 설계 v2 반영 대기 | 9.8절 |
| 복원에 launcher가 반드시 있어야 하나 | 길이 둘이 됨 | 반드시 있음. 미리 띄운 예비 프로세스도 launcher를 거침 | 닫힘(결정 2, 2026-10-16) | 9.5절 |
| 노드 안의 말(rank, 예비 프로세스와 launcher) | TCP가 아닌 Unix 소켓을 쓸까 | Unix 소켓(fd 전달) | 닫힘(결정 3, 2026-10-16) | 9.5절 |
| 재생 전 활성화(동적 예비 프로세스의 앞 결정) | TCP listener의 LATER thread를 옮길 수 없음 | launcher가 대신 LATER, 한도(띄운 뒤 시작 한도, 예비 프로세스의 끝남, 재생 실패) | 닫힘(결정 4, 2026-10-16) | 9.5절 표 4행 |
| mirror 끈 길의 TCP 자료 소켓(UPLOAD 증분, TCP FETCH; 2026-10-15 결정은 "그대로") | "모두 옮긴다"와 맞지 않음 | rdma 빌드에서 mirror 끔도 있는 RDMA 저장소(늘 전체 이미지)와 READ FETCH(outbox 아님). 맡는 단계는 링과 기록 단계(9.8절). mirror 끈 회귀는 tcp 빌드로. 바뀌는 예측(`none_clean`, `rg_*`)과 메모리는 3절 | 닫힘(결정 7, 2026-10-16); 길 하나로 정한 것은 설계 v2 반영 대기 | 15335–15420, gin-mirror 9.7절 |
| 소켓 시험 스위치(`SOCK_MUTE`, `LISTEN_GAP`, `SOCK_UTO_MS`) | rdma 빌드에서 무엇을 막나 | 증인만 막음. 8 s 끊김 셀은 "증인만 끊김"의 투명. RDMA 길의 끊김은 새 스위치(기록 QP 오류, UD 버림, credit 멈춤, 페이지 쓰기 멈춤; 연구 빌드만) | 닫힘(결정 8, 2026-10-16) | 17757, 12095 |
| UD datagram 크기 | 경로 MTU | MTU ≥ 2 048을 rdma 길의 조건으로. 리뷰가 두 GIN 포트 `active_mtu` 4 096을 확인. 준비 합의에 두 끝의 값, 시행 kv에 기록 | 닫힘(결정 9, 2026-10-16; 시행마다의 기록은 설계 v2 반영 대기) | 9.6절 |
| 저장소 기록 50, 51과 등록 꼬리 | 꼬리의 관리망 주소 | 50, 51은 링으로 바이트 그대로. 꼬리의 예비 등록은 launcher 경로, 판 번호 올림 | 닫힘(결정 10, 2026-10-16) | 17236–17247 |
| 활성화 대화(ACTIVATE, 답, FETCH 끝점, READY, DONE) | 활성화 연결 하나에 실리던 차례 | launcher 중계로 같은 차례 | 닫힘(결정 11, 2026-10-16) | 8876–8887 |
| 예비 띄우기 요청의 때 | launcher가 스스로 띄울까 | 짝의 hold 시작에서 SPAWN. 셀은 gin-dynamic | 닫힘(결정 12, 2026-10-16) | 9.5절 |
| 긴 hold에서 생존 rank 사이 lane | hold 동안 체크포인트가 "a restore runs"로 거절되어 lane이 넘침(멈춤 펜스, launcher의 LATER 한도) | 이번에는 문서화한 한계: 예측은 DISARM이고 실패로 세지 않음(`long_hold_lane`). 설계 변경과 생존 rank끼리 주고받는 driver 셀은 gin-dynamic | 닫힘(결정 14, 2026-10-16) | 14873, gin-mirror 9.3절 |
| 저장소 올리기 QP, FETCH QP | 제어와 섞일까 | 섞지 않음(9.1절). FETCH 끝점 교환만 launcher 중계로 | 닫힘(설계) | 16405–16676 |
| mirror lane, MIRROR_SETUP(48) | 장치 길, helper 시작 전 기록 | 장치 그대로. 48은 준비 차례 (5)에서 링으로 | 닫힘(설계) | 695–716 |
| 비용 팔(off, on, mirror-self, mirror-peer) | 생존 READ와 credit READ가 같은 포트를 씀 | 비용 가족 probe를 따로 둠(READ 켬, 끔, tcp) | 측정으로 닫음 | 7절 |
| 체크포인트 입력 멈춤(≤ 16 ms, 학습 ≤ 20 ms) | 기록 왕복과 감시 스레드의 일이 바뀜 | 같은 상한을 두고 pilot에서 다시 봄 | 측정으로 닫음 | gin-mirror 3절 |
| 실행기(`run_mi.sh`의 예비 띄우기, 포트 고르기, 시작 문) | launcher가 띄우기를 맡음 | 실행기는 launcher를 띄우고 kill, 메타, 줄 모으기만. rdma 길에서 포트 고르기 없음 | 닫힘(시험 장치 일) | gin-mirror 9.8절 |
| 채점기의 줄("judged dead", "published", "restored as incarnation", "hold of rank … started", "armed", "disarmed", "is given up", `GIN/LN`) | 줄이 바뀌면 채점이 깨짐 | 줄 글자 그대로. 새 줄은 머리 `GIN/RC:` 하나, `why=` 꼴의 키 없음. 'later' 수와 `activate_ms`의 뜻이 바뀌므로 새 열 이름 | 닫힘(규칙) | `../mirror/impl/test/rows_mi.py` |
| 사전 등록된 gin-restore, gin-mirror 결과의 재현 | 새 빌드의 mirror 끈 길이 다른 길을 탐 | tcp 빌드가 옛 길을 그대로 지님(결정 1, 7). 끝난 실험의 결과와 해석은 바꾸지 않음 | 닫힘(결정 1, 7) | 두 실험의 `PREREG.txt` |
| net_ib 비동기 이벤트 스레드와 `ncclIbStats` | 새 QP와 CQ, UD QP의 이벤트 | 모두 자기 stats를 담. 셈이 0을 넘으면 그 QP는 오류로 침. UD QP를 RC처럼 세는지는 `[미확인]` | 닫힘(설계, 확인 하나 남음) | 16411–16435 |
| MR 접근 비트와 GIN PD | 상대가 링에 쓸 수 있나 | 링 LOCAL_WRITE만, 페이지와 outbox REMOTE_READ만. window rkey로는 닿지 않음 | 닫힘(설계) | 16513 |
| 정리 차례 | 늦은 READ, 늦은 SEND | BYE → 증인 BYE → QP 없앰 → MR 해제 → 메모리 해제(저장소 정리와 같은 꼴) | 닫힘(설계) | 17700–17745 |
| 감시 스레드 부하 | 20 µs 걸음에 READ와 페이지 쓰기 | 1 ms마다 쓰기, 100 ms마다 상대마다 READ와 CQ 걷기 하나. 펌웨어 명령 없음 | 닫힘(설계) | 1590–1640 |
| rain QUERY_QP 상한 | 새 QP가 QP 감시에 들어감 | 새 QP는 복원 QP 목록이 아니라 QUERY_QP 감시에 들지 않음 | 닫힘(설계) | 16412 |
| 멈추기 전 생존 rank의 장치 대기 | 판정 전 10 s 동안 생존 rank의 커널이 멈춘 상대의 신호를 기다림 | 장치 hold 한도와 대기 시한이 10 300 ms보다 길어야 함. gpu-detect의 8 s 투명이 근거이고 10–12 s는 잰 적 없음 | 열림(실행 가능성 확인으로 닫을 것, `[미확인]`) | gin-restore 9.2절 |
| 운영 빌드(`NCCL_GIN_TS_PRODUCTION`) | 시험 스위치 | 새 스위치도 그 빌드에서 빠짐(md5 비교) | 닫힘(설계) | 1283–1288 |
| fork 안전(`ibv_fork_init`, `RDMAV_FORK_SAFE`) | 등록 메모리와 fork | 새 영역은 `MADV_DONTFORK`. NCCL과 이 계층이 fork 안전을 켜는지는 `[미확인]` | 닫힘(설계, 확인 하나 남음) | 9.4절 |
| 제어 경로 설계의 독립 리뷰(2026-10-16) | 막는 문제 다섯(tcp 길의 범위, 결정 7의 길 둘, 원격 접근 오류 하나로 끝남, 정상 종료의 종료 보고, kill 판정 시각)과 고칠 것 스물하나(다시 짝 맺기의 credit과 자리, 유한한 rnr_retry, 받은 줄의 한도, SQ와 CQ 깊이, 접근 비트, 판정 입력의 정렬, helper 정체 행, REJOIN 내용, 되살린 rank의 launcher 등록, Unix 소켓에 실리는 말의 목록과 pidfd 넘기기, 떠남, 라운드 취소, 단계 사이의 기댐, fork 안전 검사 등) | 위 다섯 행은 이 문서에 표시했고, 나머지는 설계 v2가 받음 | 설계 v2 반영 대기 | 9.8절 리뷰 확인점 |

**결정으로 닫은 충돌.** 2026-10-16 저녁의 사용자 결정(감지 신호는 상태 페이지 READ, 멈춘 상대는 펜스 뒤 복원, 펜스는 계보 국면, 관문은 FENCED, RST 0.1 s, fork fd는
한계, 종료는 launcher)과 21시 무렵의 결정 열넷(1절)이 위 표의 "결정" 행을 닫았다. 제어 경로 설계가 열린 충돌로 둔 열셋 가운데 열둘이 결정 1–12에 대응하고, 남은
하나(READ 응답 없음의 시간)는 설계 권고대로 적었으나 결정 목록에 따로 없어 사용자 확인을 기다린다. 결정 13은 감지 설계의 fork fd 한계, 결정 14는 동적 예비
프로세스 리뷰의 lane 넘침이다.

**열린 것**(구현 전 닫아야 함; "충돌 먼저" 규칙): (1) 제어 경로 설계 v2(독립 리뷰의 막는 문제 다섯과 고칠 것)의 반영과 그 재검토, (2) floor 규칙과 확인 창 W의
사용자 결정(대기), (3) 판정 표의 빈칸(READ 응답 없음 + 증인 정상 + launcher 보고 없음), (4) 판정 전 10 s 동안의 장치 대기 한도(실행 가능성 확인). 사용자 결정
14(긴 hold의 lane 넘침은 문서화한 한계, DISARM 예측)는 닫혔다. 이것들이 닫히기 전에는 구현하지 않는다.

**이 문서의 선택**(독립 리뷰가 볼 것).

| 설계 | 상태 |
|---|---|
| tcp 빌드는 상태 페이지, launcher, 펜스 없이 옛 TCP 제어 스택 전체(gin-mirror의 뜻). RST 뒤 거절 간격은 그 빌드의 매개변수로만(회귀 셀은 1 000) | 이 문서의 선택이 리뷰와 같음. 사용자 결정 1의 "빌드 스위치"를 컴파일 때 스위치로 읽음(설계 v2 반영 대기) |
| kill → 판정 예측을 20–250 ms 범위로 둠(확인 창 W와 launcher 보고 가운데 이른 것) | 이 문서의 선택, `[초안, 설계 v2 뒤 확정]` |
| `gc4_fdhold_sock_kill3_noreport`는 증인도 꺼서 판정 표의 정의된 행을 탐 | 이 문서의 선택(빈칸은 위 열린 것 (3)) |
| 동적 예비 프로세스의 셀은 이 실험에서 돌리지 않음(SPAWN은 CPU 모형까지) | 이 문서의 선택(4절) |
| 비용 셀의 READ 켬과 끔을 같은 바이너리의 `NCCL_GIN_TS_PROBE_MS=0`으로 가름 | 이 문서의 선택 |

### 9.8 이행 단계와 병렬 나눔 (구현 전)

열린 것(9.7절 끝)이 닫히고 독립 리뷰를 반영하기 전에는 구현하지 않는다. 장치 코드는 모든 단계에서 0줄이다. 원칙: 먼저 공유 헤더와 전송을 갈아 끼우는 자리를
만들고, 그 뒤 서로 다른 함수만 고치는 세 단계를 따로 된 에이전트가 함께 구현하고, 마지막 단계는 셋을 합친 뒤에 한다.

| 단계 | 혼자 고치는 함수와 파일 | 부르기만 하는 것 | 크기 `[추론]` |
|---|---|---|---|
| 준비(갈아 끼우는 자리) | 공유 헤더 `impl/rs_ctrl_api.h`(봉투, 페이지 줄, 끝점 판 2, 기록 52–55, launcher 말 256 B, 매개변수 이름; `static_assert`로 64 B, 64 B, 40 B, 256 B); `gdakiTsSend`, `gdakiTsPump`, `gdakiHoldSend` 호출 26 + 7 + 17곳과 `pe.fd` 56곳을 `gdakiCtrlSend`, `gdakiCtrlPump`로(tcp 뒤끝은 지금 그대로); `gdakiMiHostQpCreate` 인자 넓힘; `gdakiTsSetup`을 all-gather와 연결(`gdakiTsSetupConnect`)로; `gdakiRsSpareRun`을 활성화 기다림과 REJOIN으로; `gdakiHoldActivate`를 결정과 보내기로; 빈 hook `gdakiCtrlOnHoldStart`, `gdakiCtrlLauncherSend`, `gdakiCtrlPeerToErr`; 빌드 스위치 | – | C++ 약 400–500, 헤더 약 200 |
| 상태 페이지와 펜스 | 새 `gdakiPage*`, `gdakiProbe*`; 감시 스레드 hook 한 줄; `gdakiHoldStart`의 펜스 갈래; 52–54 처리; 계보 FENCING, FENCED(`gdakiLnViewOf`, `gdakiLnClassify`); 관문 `gdakiRsActExamine`; 55번 PROBE_SETUP; `gdakiProbeToErr`; tcp 빌드의 RST 거절 간격 | `gdakiCtrlSend`, `gdakiCtrlLauncherSend` | C++ 약 1 000–1 200 |
| 링과 기록 | rdma 뒤끝 `gdakiCtrlRdma*`(QP, 링, credit, completion channel, outbox); `gdakiTsSetupConnect`의 짝 맺기; `gdakiTsReconnectStep`의 기록 길; `gdakiRsSpareRejoinAll`; `gdakiRsLogExport`의 받는 곳(outbox); `gdakiTsCloseAll`의 증인 BYE; `gdakiCtrlRecordToErr`; mirror 끈 길의 RDMA 저장소(결정 7) | 페이지의 `rxConsumed` 칸(준비 단계가 줄 배치를 고정) | C++ 약 1 300–1 600 |
| launcher | launcher 프로그램(새 폴더, C); rank 쪽 `gdakiCtrlLauncher*`; `gdakiCkptSelfOf`의 경로; STORE_REQ 꼬리와 올리기 머리(17236–17247, 15661–15680); `gdakiHoldActivateSend`; 활성화 기다림; `gdakiCtrlOnHoldStart`(SPAWN); 실행기와 채점기 | `gdakiCtrlSend`, 링 단계의 UD 짝 맺기 API, 펜스 단계의 `gdakiLnFenced` | 라이브러리 약 500–700, launcher 약 600–800, 실행기와 채점 약 300 |
| 증인(합친 뒤) | rdma 빌드에서 TCP 제어 갈래를 쓰지 않음(빌드 스위치 뒤로; 결정 1이라 지우지 않음), 증인 전용 코드, 증인 끄기 | – | 옮김 약 300 |

- 처음 제어 경로 설계는 마지막 단계에서 tcp 갈래를 지우는 안을 두었으나 결정 1로 지우지 않고 빌드 스위치 뒤에 둔다. tcp 빌드의 동일성은 매 단계 확인한다.
- **CPU 단위 모형.** 준비: 같은 기록 열을 tcp 뒤끝으로 보내 받은 바이트가 지금 함수와 같음, 기존 단위 시험(`rs_unit_host.cc`, `rs_spare_unit.cc`, `mi_unit_spare.cc`,
  `mi_unit_lineage.cc`, `mi_unit_store.cc`, `mi_unit_host.cc`)이 고침 없이 통과. 상태 페이지와 펜스: 줄 안 seqlock 모형(쓰는 thread와 무작위로 끼어드는 읽기, 짝수
  `ver` 줄의 찢김 0), 판정 표의 순수 함수를 입력 격자 전부로, 계보 oracle에 새 국면 둘(다름 목록이 새 행만), `gate_fenced` CPU 프로그램. 링: credit 모형(낸 RECV
  ≥ 날아가는 SEND, 세대 안 잃음과 겹침 0), UD 짝 맺기 모형(잃음, 겹침, 차례 바뀜, 옛 화신), 같은 사건 열에서 넘겨진 기록 열이 TCP 모형과 같음, park 동일.
  launcher: 상태 기계 모형(중복 SPAWN, LATER 한도, 띄우기 실패, 예비 프로세스 끝남, FENCE와 EXITED의 엇갈림, 같은 화신 둘째 접속), 등록 oracle(경로가 있으면
  지금 무장 판단과 같음), 동적 예비 프로세스 리뷰가 찾은 경쟁 셋(넘기기 틈, 일찍 답하는 thread의 상한, 잃는 ACCEPTED)의 장면.
- **동일성 확인(매 단계).** 장치 기계어 비교(매크로 없는 프로그램 넷과 라이브러리 장치 객체가 `mi`와 같음, gin-mirror의 방법), tcp 빌드의 pilot 회귀 묶음
  (`mi4_kill3_ow`, `mi4_kill2_kill3_ow`, `rs4_kill3`, `rs4_kill3_spareabsent`, `mi4_none_ow`)의 판정과 줄 수가 ln4 본 실행과 같은 범위, rdma 빌드에서 이 계층의
  TCP 보내기 바이트 0(증인 BYE 빼고).
- **실행 가능성 확인(구현 전이나 준비 단계와 함께, 채점 안 함).** (1) NIC이 CPU가 고쳐 쓰는 64 B 줄 하나를 한 순간의 모습으로 읽는가(망치 시험, 짝수 `ver` 줄의
  찢김 수); (2) Linux 5.15에서 여러 스레드인 CUDA 프로세스의 pidfd가 읽기 가능해지는 때가 스레드 그룹의 끝이고 그때 uverbs fd가 이미 닫혔는가; (3) rank마다 GIN
  포트의 active MTU; (4) 256 B READ의 부하 꼬리 지연; (5) 받는 QP가 RTR 전일 때의 RC 패킷 버림이 짝 맺기를 얼마나 늘리나; (6) fork 안전 설정; (7) UD QP의 비동기
  이벤트를 net_ib 이벤트 스레드가 세는가; (8) 활성화 뒤 부분(67.2–71.4 ms)에서 TCP 몫(tcp, rdma A/B); (9) sunny 노드 안 launcher의 띄우기 시간; (10) 판정 전 10–12 s
  동안 생존 rank의 장치 대기와 hold 한도가 견디는가.
- **리뷰 확인점.** (1) 코드 전: 이 문서 9절과 충돌 표를 다른 Opus 에이전트가 읽기만으로 검토(쓰는 중; 9.7절 마지막 행). (2) 준비 단계 뒤: 갈아 끼우는 자리의 tcp 동일성.
  (3) 단계마다 단위 시험 뒤 pilot 전: 그 단계의 모형, 시험 스위치가 운영 빌드에 없음(md5), launcher가 등록받은 PID와 시작 시각에만 닿음. (4) 합친 뒤: 링 단계 위에
  펜스와 launcher를 올린 빌드로 회귀 묶음 전부와 펜스 셀. 그 뒤 pilot, 사전 등록.
- 모든 클러스터 실행은 `harness/gpu-initiated/common/cluster_run.sh` 안이다.

**실행 방법(초안).** 빌드는 gin-mirror의 `build_mi.sh` 꼴을 따르는 이 폴더의 빌드 스크립트(구현 때)로 `gc`, `gct`, `gcp`, `gctp`를 만들고, 배포 묶음은 두 노드의 새
디렉터리에 둔다. 실행은 gin-mirror의 hold 틀(`hold_mi.sh`, `run_mi.sh`) 위에 launcher 띄우기, SIGSTOP과 SIGCONT, fork 자식 주입을 더한 실행기로 하고, 채점은
`rows_mi.py`에 9.3절의 열(판정 종류와 시각, 퍼짐, READ 성공률, 박동 간격, 찢긴 읽기, 증인 상태, 국면 차례, launcher 시각, 펜스 뒤 바뀐 칸, TCP 바이트)을 더한
채점기로 한다. 결과 폴더는 `results/<날짜>_<이름>/`, 원자료는 Release `data-YYYYMMDD`로 올린다. 명령은 구현 뒤 이 절과 [NOTES.md](NOTES.md)에 적는다.

### 9.9 이 testbed에서 넣을 수 있는 장애와 그 현실성

**넣는 것**(모두 연구 빌드의 시험 스위치나 실행기가 자기가 띄운 프로세스에만).
- **SIGKILL.** 실행기가 기록한 PID에(gin-mirror 그대로).
- **RST로 죽기.** `NCCL_GIN_TS_TEST_DIE_RST=<ms>`: 연결된 helper 소켓(rdma 빌드에서는 증인)에 `SO_LINGER {1, 0}`을 두고 스스로 SIGKILL.
- **살아 있는 RST와 포트 닫힘.** `NCCL_GIN_TS_TEST_RST_GAP=<시작>:<길이>`: 연결 소켓을 linger 0으로 닫고 수신 대기를 그 길이만큼 닫았다 다시 엶.
- **SIGSTOP과 SIGCONT.** 실행기가 자기 rank의 정확한 PID에. 느린 상대는 50 ms 간격 반복. 끝에서 CONT 뒤 SIGKILL로 정리.
- **박동 쓰기만 멈춤.** `NCCL_GIN_TS_TEST_FREEZE_PAGE=<ms>`: 감시 스레드가 그 길이만큼 박동만 쓰지 않음(프로세스는 돎).
- **fd를 쥔 자식 + 부모 SIGKILL.** `NCCL_GIN_TS_TEST_FD_HOLDER=sock|uverbs`: rank가 자식(`gin_fdhold`, `prctl(PR_SET_NAME)`)을 fork해 socketpair의 SCM_RIGHTS로 증인
  (tcp 빌드는 helper) 소켓만, 또는 uverbs fd까지 넘김. 자식은 60 s 뒤 끝나고 실행기가 `pkill -x gin_fdhold`로 정리. PDEATHSIG는 쓰지 않음.
- **launcher 종료 보고 끄기.** `NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=1`(launcher 쪽, 연구 빌드만).
- **RDMA 제어 길의 끊김.** 기록 QP를 오류 상태로(`NCCL_GIN_CTRL_TEST_QP_ERR`), UD datagram 버리기(`NCCL_GIN_CTRL_TEST_DROP_UD`), RECV 다시 내기 멈춤
  (`NCCL_GIN_CTRL_TEST_CREDIT_STALL`). 모두 자기 프로세스의 자기 QP에만.
- **관리망 끊김.** 기존 소켓 필터 스위치 `SOCK_MUTE`(프로세스 안에서 증인 소켓만 막음; 사용자 결정 8). 방화벽은 쓰지 않음.

**넣지 않는 것.** 실제 link down과 flap, 방화벽 규칙 바꾸기, 재부팅, 드라이버 재적재, `devlink reload`, NIC floor 바꾸기, PFC나 pause storm, 다른 사용자 프로세스.

**우리 주입의 현실성** `[문헌, 추론]`. 실제 큰 학습에서 작업을 멈추는 장애는 GPU와 GPU 메모리 문제가 가장 많고(Llama 3 405B의 54일 동안 예기치 않은 중단 419회 가운데
GPU 268회; 표의 백분율 열과 횟수가 어긋나 문헌 조사가 횟수로 다시 셈), 링크, 케이블, NIC 같은 백엔드 네트워크가 약 10%다(같은 기간 42회). 원인이 보이지 않는 hang과 timeout도 따로 큰 덩어리다(ByteRobust
Job Hang 9.9%). 이 실험의 주입은 다음과 같이 읽어야 한다. 상대 프로세스 SIGKILL은 프로세스 crash(CUDA error, segfault, OOM kill)와 NIC 쪽 결과와 제어 연결 신호가 같다.
RST로 죽기는 같은 crash에서 소켓에 읽지 않은 자료가 남은 경우이고, gin-mirror 본 실행에서 실제로 4/669 닫힘에서 나왔다 `[측정]`. 자식이 소켓을 쥔 채 부모가 죽는
주입은 커널이 연결을 닫지 못하는 호스트 crash나 전원 차단의 제어 경로 쪽 모양(FIN 없음)을 재현하고, 데이터 경로 쪽도 응답하는 QP가 없다는 점에서 같다. 그러나 그
노드의 launcher는 살아 있어 종료를 알린다. 실제 호스트 crash에서는 launcher도 함께 죽으므로, launcher 보고로 판정하는 셀은 프로세스 crash 쪽 결론이고 호스트
crash 쪽 결론은 보고를 끈 셀(READ 실패로 판정)에서만 나온다. 그 경우에도 같은 노드의 예비 프로세스는 쓸 수 없으므로 실제 호스트 crash에서는 복원이 아니라 판정과
거절까지만 말할 수 있다. SIGSTOP은 GPU hang, deadlock, CPU 정지처럼 NIC이 계속 응답해 오류가 없는 상태를 재현하지만 GPU 커널 자체의 정지는 아니고(호스트 프로세스
정지는 이미 도는 커널을 멈추지 않을 수 있음), 50 ms 반복은 느려짐이 아니라 짧은 멈춤의 반복이다. 박동 쓰기만 멈추는 주입은 감시 스레드 하나만 서는 소프트웨어
결함에 가깝고, 펜스가 도는 프로세스를 끝낸다는 것을 보이는 장치다. 기록 QP를 오류 상태로 바꾸는 주입은 전송 오류 뒤 QP가 닿는 최종 상태를 재현하지만 원인을
알려 주는 첫 오류 완료와 비동기 이벤트가 없고 QP 하나에만 곧바로 걸린다. 실제 링크 장애는 포트 이벤트 뒤 재시도 시간을 지나 그 포트의 QP가 함께 실패하고,
이 실험은 그 경우를 판정 표의 "노드 또는 선" 행으로 설계만 하고 재지 않는다. 증인만 막는 관리망 끊김은 관리망 스위치나 케이블 장애의 이 계층 쪽 모양이다. 실제
link down과 flap, PFC pause storm, 일부 패킷만 잃는 gray failure, 느려지기만 하는 장애, 여러 호스트의 동시 장애, GPU silent data corruption은 공유 testbed에서 안전하게
넣을 수 없어 넣지 않으므로, 이 실험의 결론은 그런 장애에 대해 아무것도 말하지 않는다. 문헌 출처는 20절이다.

## 10. 완료 조건과 QA 기준

- [ ] 모든 셀이 계획한 n만큼 실행됐다(제외와 실패를 따로 센 표 포함).
- [ ] 예측마다 판정(맞음/틀림/자료 없음)과 놓친 시행 목록이 있다.
- [ ] 핵심 수치를 원자료에서 다시 계산했다: 판정 종류와 시각(kill, RST, FIN 없는 죽음, 멈춤), 판정 시각의 퍼짐, 펜스 차례와 펜스 뒤 바뀐 칸, 복원 시간, READ 성공률과
  박동 간격, 이 계층의 TCP 바이트, 비용 중앙값.
- [ ] 다른 에이전트가 채점기를 보지 않고 원자료에서 판정 시각 셀과 펜스 셀의 판정을 다시 셌다(펜스 셀은 국면 차례를 줄의 시각으로 확인).
- [ ] 매크로 없는 프로그램의 기계어와 라이브러리 장치 객체가 `mi`와 같음을 네 빌드 모두에서 확인했다.
- [ ] tcp 빌드의 회귀 예측을 gin-mirror의 판정식 그대로 다시 채점했다.
- [ ] launcher가 등록받지 않은 프로세스에 신호를 보낸 줄이 0임을 원자료에서 확인했다.
- [ ] smoke, pilot, 제외 시행이 결과에 섞이지 않았다. 여러 실행의 범위와 대표 실행의 범위를 섞지 않았다.
- [ ] 원자료를 Release에 올리고 DATA.md에 적었다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀, 설계, 충돌 표 초안 (`DRAFT`, 2026-10-16)
- [x] 사용자 결정 열넷으로 충돌 표의 결정 행을 닫음(2026-10-16, 9.7절)
- [x] 제어 경로 설계의 독립 리뷰 받음(2026-10-16: 막는 문제 다섯; 이 문서의 해당 행을 "설계 v2 반영 대기"로 표시)
- [ ] 설계 v2 반영과 재검토(9.7절)
- [ ] floor 규칙과 확인 창 W의 사용자 결정, 판정 표의 빈칸, 판정 전 장치 대기(9.7절 끝의 열린 것)
- [ ] 실행 가능성 확인 열(9.8절, 채점 안 함)
- [ ] 준비 단계: 공유 헤더, 갈아 끼우는 자리, 빌드 스위치, CPU 단위 시험, tcp 동일성, 독립 리뷰
- [ ] 상태 페이지와 펜스, 링과 기록, launcher 단계의 병렬 구현, 빌드, CPU 단위 시험, 기계어 비교, 단계마다 독립 리뷰
- [ ] 합치기와 증인 단계, 다시 빌드, 회귀 묶음, 독립 리뷰
- [ ] 실행기, 채점기, 셀 파일, 예측 표 파일
- [ ] smoke와 pilot(채점 제외), 문턱과 n 고정
- [ ] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/gin-control-v1` 태그
- [ ] 본 실행 (`RUNNING`)
- [ ] 채점과 독립 재계산 (`QA`)
- [ ] 결과 정리, 원자료 release, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-16 | 초안 작성(DRAFT): 1–11절, 설계 9.1–9.9절, 충돌 표 9.7절. 근거는 저장소 밖의 설계 셋(제어 경로를 RDMA로 옮기는 설계 초안 690줄, 감지 빈틈 셋의 설계 v2, 동적 예비 프로세스 설계)과 리뷰 둘(동적 예비 프로세스 설계의 독립 리뷰; gin-mirror 9.9절의 계보 리뷰)과 장애 문헌 조사이고, 내용을 이 문서에 요약했다(파일은 링크하지 않음). 사용자 결정(2026-10-16 저녁과 21시 무렵의 열넷, 메인 세션이 전함)으로 충돌 표의 결정 행을 닫았다. 그 뒤 나온 제어 경로 설계의 독립 리뷰(막는 문제 다섯, 고칠 것 스물하나, nit 열하나)를 메인 세션의 지시대로 접었다: tcp는 옛 스택 전체를 되살리는 빌드 스위치(아무것도 지우지 않음), mirror 끈 체크포인트와 FETCH는 있는 RDMA 저장소로(outbox 아님), 원격 접근 오류 하나로는 끝남이 아님, 정상 종료는 떠남 알림(BYE 뒤 hold 없음), kill 판정은 확인 창 W 20–50 ms, 시행마다 `active_mtu` 기록(두 GIN 포트 4 096). 이 자리들은 "설계 v2 반영 대기"로, kill → 판정 시간 예측은 범위와 "초안, 설계 v2 뒤 확정"으로 표시. floor 규칙은 사용자 결정 대기, 결정 14는 문서화한 한계(DISARM 예측)로 적음. 1절과 9절의 gin-mirror 기준 수치(RST 지연 셋, 소켓 닫힘 원인 수, 복원 시간과 관문 기다림, 빠른 모드 8/95, 입력 멈춤 최대)는 gin-mirror 본 실행의 `trials_scored.csv`와 `raw/*.log`(로컬 worktree `gin-mirror-fix`의 결과 폴더, release `data-20261015`와 같은 원자료)에서 다시 셌다. 구현, 빌드, 클러스터 실행 없음 | 이 파일, 브랜치 `exp/gin-control` |

## 13. 사전 등록 이후 변경

사전 등록 전이다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 기준(대조): gin-mirror 본 실행 | `../mirror/results/20261015_main/`, Release `data-20261015` | 428 |

## 15. 결과 요약

`[미확인]`: 측정 전이다.

## 16. QA와 재현성

`[미확인]`: 측정 전이다. 재현에 필요한 기준은 gin-mirror 빌드 ln4([../mirror/impl/mi_layer.diff](../mirror/impl/mi_layer.diff), md5 `dcd30859`)다.

## 17. 결론

아직 없다.

## 18. 한계

초안에서 이미 아는 한계(측정 뒤 다시 쓴다): 노드 죽음과 선 끊김을 RNIC 쪽에서 가르지 못함(증인이 가름), fork 자식이 uverbs fd를 물려받으면 펜스가 자원을
없애지 못함(그 셀은 거절만), 긴 hold의 생존 rank 사이 lane 넘침(DISARM), 실제 link down과 노드 고장은 재지 않음(9.9절), 제어와 데이터가 같은 RNIC 포트를 써서 같은
선이 죽으면 함께 죽음.

## 19. 다음 작업

gin-dynamic(동적 예비 프로세스: 이 실험의 launcher SPAWN, LATER 대리 답, 한도 위에서; 같은 rank의 둘째 죽음, 긴 hold의 lane), 그다음 gin-train(실제 framework 연결).

## 20. 참고자료

- 앞 실험: [../restore/EXPERIMENT.md](../restore/EXPERIMENT.md), [../mirror/EXPERIMENT.md](../mirror/EXPERIMENT.md)(9.7절 충돌 표, 9.9절 계보, 18절 한계),
  [../../../gpu-detect/EXPERIMENT.md](../../../gpu-detect/EXPERIMENT.md), [../../../live_peer/EXPERIMENT.md](../../../live_peer/EXPERIMENT.md),
  [../harden/EXPERIMENT.md](../harden/EXPERIMENT.md), [../reconnect/EXPERIMENT.md](../reconnect/EXPERIMENT.md).
- NIC 동작: [../../../ack_timeout/README.md](../../../ack_timeout/README.md)(floor와 재시도 초과 시간), [../../../teardown_order/README.md](../../../teardown_order/README.md)
  (죽는 프로세스의 QP와 MR 해제 차례, FIN과 첫 오류 CQE).
- 문헌(9.9절과 1절): Meta, "The Llama 3 Herd of Models", arXiv 2407.21783(3.3.4절, Table 5); ByteDance, "Robust LLM Training Infrastructure at ByteDance", SOSP 2025,
  arXiv 2509.16293(Table 1); Jiang 외, "MegaScale", NSDI 2024; Kokolis 외, "Revisiting Reliability in Large-Scale Machine Learning Research Clusters", HPCA 2025;
  Dong 외, "Evolution of Aegis", NSDI 2025; Qian 외, "Alibaba HPN", SIGCOMM 2024; Guo 외, "RDMA over Commodity Ethernet at Scale", SIGCOMM 2016; Huang 외,
  "Gray Failure", HotOS 2017; rdma-core `ibv_poll_cq(3)`, `ibv_get_async_event(3)`; NVIDIA NCCL 환경 변수 문서(`NCCL_IB_TIMEOUT`, `NCCL_IB_RETRY_CNT`).
