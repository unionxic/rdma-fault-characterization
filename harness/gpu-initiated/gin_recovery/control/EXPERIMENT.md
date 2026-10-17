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
| 마지막 갱신 | 2026-10-17 아침, 사용자 결정 셋(펜스 거부는 실패, 멈춤 오차 ±100 ms, 장치 쪽 segment 비트 2c); 통합 2와 2c 진행. 빌드됨, 클러스터 실행 없음 |

표시: `[측정]` 원자료에서 이 문서가 다시 셈, `[측정: 문서]` QA를 거친 다른 실험 문서의 값을 옮김(이 문서에서 다시 세지 않음), `[소스]` 코드에서 읽음,
`[문헌]` 논문이나 공개 문서, `[추론]` 해석, `[미확인]` 확인 안 함.

**줄 번호.** `[소스]`의 줄 번호는 따로 적지 않으면 gin-mirror 빌드 ln4의 호스트 파일 `gin_host_gdaki.cc`(md5 `0ab4e636`, 24 507줄)의 줄이다. 그 파일은
[../mirror/impl/mi_layer.diff](../mirror/impl/mi_layer.diff)(md5 `dcd30859`)를 적용한 트리의 것이다(재현은 [../mirror/NOTES.md](../mirror/NOTES.md)).

**근거 문서.** 이 초안은 저장소 밖의 설계 문서 셋(제어 경로를 RDMA로 옮기는 설계 초안, 감지 빈틈 셋의 설계 v2, 동적 예비 프로세스 설계)과 리뷰 둘(동적 예비
프로세스 설계의 독립 리뷰, gin-mirror 9.9절의 계보 리뷰)과 장애 문헌 조사에서 왔다. 그 파일들은 링크하지 않고 필요한 내용을 이 문서에 옮겨 적었다. 그 뒤 제어 경로
설계의 독립 리뷰(2026-10-16, 막는 문제 다섯, 고칠 것 스물하나, nit 열하나)가 나왔고, 그것과 사용자 결정 열넷을 반영한 제어 경로 설계 v2(같은 날, 바뀐 것 스물일곱)를
이 문서에 접었다(12절 둘째 행). 2026-10-17에는 설계 v2와 이 문서의 둘째 독립 재검토(막는 문제 넷, 고칠 것 열여덟, nit 열)가 나왔고, 그것에 답한 제어 경로 설계 v3(1 225줄, md5 `a548b5c2`)를
접었다(12절 넷째 행). 설계 v3에서 새로 옮기거나 바꾼 수치는 `[설계 v3]`로, v2 그대로인 수치는 `[설계 v2]`로 적고, 이 문서가 원자료에서 다시 센 것만 `[측정]`이다. 동적 예비 프로세스 설계 v2는 launcher와
예비 프로세스 사이의 경계(노드 안 인사, 준비됨 알림)에만 썼다(4절).

**말.** gin-restore와 gin-mirror의 말(논리 rank, 예비 프로세스, 짝, 체크포인트, 입력 멈춤, hold, 화신, 계보, 국면, lane, DISARM)은
[../restore/EXPERIMENT.md](../restore/EXPERIMENT.md)와 [../mirror/EXPERIMENT.md](../mirror/EXPERIMENT.md) 머리말, 9.9절과 같다. 이 실험에서 더 쓰는 말:
- 기록: helper가 상대와 주고받는 고정 크기 제어 메시지(`struct gdakiTsMsg`, 1 872 B). 지금은 TCP helper 소켓, 이 실험에서는 RC QP의 SEND/RECV로 간다.
- 링: 받는 rank가 보내는 상대마다 미리 낸 RECV 자리 64개. 기록 하나가 자리 하나를 쓴다.
- 상태 페이지: rank마다 호스트 메모리의 4 KiB 영역. 상대가 RDMA READ로 읽어 생존을 판정한다. 박동은 그 페이지에서 1 ms마다 오르는 칸이다.
- 증인: 관리망에 남기는 TCP 소켓. BYE와 FIN만 보고, 혼자서는 판정하지 않는다.
- launcher: 노드마다 늘 떠 있는 작은 관리 프로세스. RDMA로 rank들과 이어지고, 예비 등록을 대신 받고, 활성화를 중계하고, 펜스를 집행하고(원래 프로세스를
  종료하고 pidfd로 끝남을 확인), 같은 노드 rank의 종료를 알린다.
- 펜스: 살아 있을 수 있는 옛 화신이 생존 rank의 QP와 window에 다시 닿지 않게 하는 차례. 생존 rank의 그 상대 QP를 오류 상태로 → 모든 생존 rank의 보고 →
  launcher의 종료와 확인. 계보 HOLD_WAIT 안의 보고 이름 FENCING, FENCED와 hold 칸 옆의 펜스 낱말로 나타낸다(9.4절; 계보의 국면 값은 바꾸지 않음).

| 빌드 키 | 내용 | 쓰는 곳 |
|---|---|---|
| `gc` | 이 실험의 연구 빌드: gin-mirror ln4 위에 9절의 RDMA 제어 계층(제어 길 rdma) | 새 셀, rdma 회귀 |
| `gct` | 같은 소스를 컴파일 때 스위치 `NCCL_GIN_CTRL_TCP=1`로 빌드(옛 TCP 제어 스택 전체; 전처리 결과가 ln4와 같아야 함; 9.3, 9.8절) | tcp 회귀 |
| `gctc` | `NCCL_GIN_CTRL_TCP=1`과 둘째 매크로 `NCCL_GIN_CTRL_TCP_CELLS=1`(tcp 쪽 대조 셀이 쓰는 RST 간격 매개변수와 시험 스위치 `DIE_RST`, `RST_GAP`, `FD_HOLDER`의 helper 소켓 갈래; ln4에 없음) `[설계 v3 2.0절]` | tcp 쪽 대조 셀만(회귀 증거 아님) |
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

초안이다(2026-10-16, 설계 v3로 2026-10-17 고침). 수치는 설계의 어림이고 pilot 뒤 사전 등록에서 고친다.

| 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|
| FIN을 증인으로만 써도 kill의 죽음 판정은 1 s 안이다. 판정은 증인 FIN의 때 t_F에 READ1, t_F + W/2에 READ2를 내고 t_F + W에 서므로 kill → 판정이 늘 FIN + W(W 20–50 ms면 약 20–51 ms)다. 확인 창이 "확인 못함"이면 launcher의 종료 보고(102–206 ms)에서 선다 `[설계 v3 4.2, 4.6절; 추론]`. W는 pilot이 정한다 `[초안]` | `gc4_kill3_ow`류에서 확인 창으로 판정한 시행(FIN+STALE, FIN+NORESP, REMACC+FIN)의 증인 FIN → 첫 생존 rank의 판정이 W–W + 1 ms 밖이거나, 원인이 FIN 하나, 원격 접근 오류 하나, 시한 하나인 판정 줄이 있거나, kill → 판정이 206 ms를 넘는다 |
| RST는 더 이상 판정을 1 s 늦추지 않는다. rdma 빌드에서는 RST도 확인 창을 부를 뿐이라 RST → 판정이 RST + W다 `[설계 v3 4.2절]`. tcp 대조 빌드(`gctc`)에서 RST 뒤 거절 간격을 100 ms로 두면(RST 셀만; 기본 1 000, 2026-10-16 밤 사용자 결정) RST → 죽음이 100.5–106 ms다 `[추론: 감지 설계의 어림]` | RST 셀에서 rdma 빌드의 RST → 판정이 W–W + 1 ms 밖이거나, 간격 100 ms를 둔 `gctc` 시행에서 106 ms를 넘는다 |
| FIN 없는 죽음은 launcher의 종료 보고로 원래 프로세스의 정리 시간(4 KiB 102.0–143.1 ms `[설계 v2 4.1절, 측정: 문서 동적 예비 프로세스 리뷰]`; 이 문서가 다시 센 관문 기다림 105.3–146.6 ms `[측정]`)에 판정되고, launcher가 끝남을 감추고 증인도 없으면 상태 페이지 READ의 하드웨어 재시도 초과(3.51–3.76 s `[측정: 문서 teardown_order]`)로 kill 뒤 약 3.6–4.0 s, 여유를 두어 3.5–4.5 s에 판정되고(판정 표 11행, 원인 NORESP) 펜스가 그것을 확인한 뒤 복원된다 `[설계 v3 4.2, 4.6절; 추론]`. 옛 TCP 길은 20 s 안에 판정하지 못한다 `[추론]` | 보고 있는 셀에서 kill → 판정이 100–150 ms 밖이거나, 보고 없는 셀에서 3.5–4.5 s 밖이다(READ 재시도 초과가 아닌 길로 판정) |
| 멈춘 상대는 박동 정체 10 000 ms 전에는 판정되지 않고, 넘으면 모든 생존 rank가 2 × 100 ms 안에 멈춤을 판정하며, 펜스 뒤 되살아나고, 펜스 뒤 옛 화신의 쓰기는 0이다 | 8 000 ms 이하 멈춤에서 판정이 있거나, 12 000 ms 멈춤에서 판정이 10 000–10 300 ms 밖이거나, 펜스 뒤 생존 window에 바뀐 칸이 있거나, 데이터가 기준과 다르다 |
| `watchBeat`는 오르고 helper만 멈춘 rank도 helper 박동 정체 10 000 ms 전에는 판정되지 않고, 넘으면 펜스 뒤 되살아난다 `[설계 v3 4.2절 15행]`. 펜스로 둔다(2026-10-17 사용자 결정 1)(9.7절 끝 v3 목록 1) | 12 000 ms helper 멈춤에서 판정이 10 000–10 300 ms 밖이거나, 펜스 뒤 바뀐 칸이 있거나, 데이터가 기준과 다르다 |
| 관리망 8 s 끊김(증인만 막음)에서 판정 0, 기록 길 다시 짝 맺기 0, 그 사이에도 체크포인트가 확정된다 | 판정이나 기록 길 잃음이 있거나, 끊김 동안 확정된 체크포인트가 0이다 |
| 상태 페이지 READ는 따로 된 QP의 256 B READ라 4 KiB put 지연 중앙값을 2 % 넘게 바꾸지 않는다 `[추론]`. 2 %는 실행 사이 퍼짐보다 작아 pilot이 문턱을 다시 정한다(9.9절 끝) `[초안]` | 노드마다 READ 켬 대 끔의 4 KiB 지연 중앙값 차가 문턱(초안 2 %)을 넘는다 |
| 회귀 없음: tcp 빌드는 gin-mirror의 비용 밖 예측을 원래 기준대로 맞힌다. rdma 빌드는 제어 경로와 무관한 예측을 원래 기준대로 맞힌다 | 그 예측 가운데 원래 판정식을 어기는 것이 있다 |
| 긴 hold의 생존 rank 사이 lane 넘침은 한계다(사용자 결정 14): 넘치면 그 받는 rank의 DISARM이고 데이터는 틀리지 않는다 | DISARM 없이 lane이 넘쳐 데이터가 기준과 다르다 |

## 3. 사전 예측 (측정 전에 작성)

초안이다. 문턱과 n은 pilot 뒤 사전 등록에서 고정한다. 예측 표 파일 [impl/test/predictions_gc.csv](impl/test/predictions_gc.csv)가 이 표를 기계가 읽는 꼴로 옮겼고,
이 표에 수치나 목록이 없던 여섯은 시험 쪽 리뷰의 권고 값으로 채워 `[초안: 사전 등록 전 확정]`으로 적었다(아래 행). 판정은 유효한 시행만으로 센다(8절). "≥ k/n"은 유효 시행 n개 가운데 조건이 참인 것이 k개 이상이다.
이 실험의 셀 키는 유효 시행이 계획 n보다 적으면 "자료 부족"이다(제외는 채움, 8절). 여러 셀을 묶는 키(`build:gc`처럼 빌드의 모든 시행을 보는 것)는 들어간 셀이 모두 계획 n을 채울 때만
판정한다. gin-mirror의 찾는 키(회귀 행)는 그 실험의 규칙 그대로다 `[초안: 사전 등록 전 확정]`.
시각은 생존 rank 자기 프로세스의 `mono_ms`이고, kill 시각은 실행기의 kill 줄을 같은 노드 시계로 잰다. 같은 노드의 두 프로세스는 두 `mono_ms`를 견준다. 노드 사이 간격(sunny의 kill 줄과
rain 생존 rank의 판정 줄 같은 것)은 실행기가 시행 앞뒤로 잰 두 노드의 시계 차로 두 `mono_ms`를 한 노드 시계에 옮겨 견준다. 시계 차는 한 ssh 세션 안의 왕복 열 번 가운데 가장 짧은 것이고 왕복
시간도 함께 남긴다. 시계 차나 줄의 `mono_ms`가 없을 때만 수신 시계를 쓰고, 열 `kill_judge_clock`, `judge_spread_clock`, `publish_clock`이 어느 쪽인지 적는다 `[초안: 사전 등록 전 확정]`.

| 무엇을 예측했나 | 셀 | 시행마다의 조건 | 판정식(초안) | 근거 | 찾는 키 |
|---|---|---|---|---|---|
| kill의 죽음 판정이 FIN 하나에 기대지 않고 1 s 안 | `gc4_kill3_ow`, 그리고 rdma 빌드의 gin-mirror kill 셀 여덟(`mi4_kill3_ow`, `mi4_kill1_ow`, `mi4_kill3_ckpt_ow`, `mi4_seg_4k`, `mi4_seg_32k`, `mi4_seg_128k`, `mi4_pull`, `rs4_kill3_mion`, 모두 `@gc`) | 생존 rank마다 확인 창으로 판정(원인 FIN+STALE, FIN+NORESP, REMACC+FIN)이면 증인 FIN → 판정 W–W + 1 ms(kill → 판정 약 20–51 ms; 판정은 원인과 상관없이 t_F + W) `[설계 v3 4.2, 4.6절]`, 창이 "확인 못함"이라 원인 EXITED면 kill → 판정 102–206 ms `[설계 v2 4.1절]`(원인마다 수는 보고, FIN+NORESP가 많을 것 `[추론]`); 판정 원인이 FIN 하나, 원격 접근 오류 하나, 시한 하나인 줄 0. W 값은 pilot이 정함 `[초안]` | 셀마다 따로: `gc4_kill3_ow` ≥ 9/10; gin-mirror kill 셀은 k = n − 1(n 10인 `mi4_kill3_ow`는 ≥ 9/10, n 5인 나머지 일곱은 ≥ 4/5) `[초안: 사전 등록 전 확정]` | 9.3절 판정 표, 사용자 결정 5 | `kill_judge_rdma` |
| RST로 죽어도 1 s 늦지 않음(rdma) | `gc4_rst_kill3@gc` | RST 줄이 있는 생존 rank마다 RST → 판정 W–W + 1 ms(원인 FIN+STALE, FIN+NORESP, REMACC+FIN; 창이 "확인 못함"이면 EXITED로 kill + 102–206 ms) `[설계 v3 4.2절]`, 복원 성공 | ≥ 9/10 | 9.3절 | `rst_judge_rdma` |
| RST 뒤 거절 간격 100 ms(tcp 대조) | `gc4_rst_kill3@gctc` | RST → 죽음 판정 100.5–106 ms(옛 1 002.9–1 003.2 ms `[측정]`), 복원 성공. 값은 감지 설계의 어림. 간격 매개변수는 tcp 대조 빌드에만 있고 기본 1 000, 이 셀만 100(2026-10-16 밤 사용자 결정; 9.3절) | ≥ 9/10 | 감지 설계, 사용자 결정(저녁, 밤) | `rst_judge_tcp` |
| 살아 있는 상대의 RST와 포트 닫힘은 rdma에서 판정 없음 | `gc4_rstgap_live300@gc` | 판정 0, 거절 0(확인 창이 살아 있음으로 끝남, 판정 표 8행) | 5/5 | 사용자 결정 5 | `rstgap_live_rdma` |
| 같은 주입이 tcp에서 50 ms면 판정 없음, 300 ms면 거짓 죽음 | `gct4_rstgap_live50`, `gct4_rstgap_live300` `@gctc`(간격 100) | 50 ms: 판정 0; 300 ms: 판정이 RST 뒤 100.5–106 ms(100 ms 간격의 대가; 감지 설계의 어림) | ≥ 9/10, ≥ 4/5 | 감지 설계 | `rstgap_live_tcp` |
| FIN 없는 죽음, launcher 보고 | `gc4_fdhold_sock_kill3` | kill → 판정 100–150 ms(원래 프로세스의 정리 시간 102.0–143.1 ms `[설계 v2 4.1, 4.6절]`과 이 문서의 관문 기다림 105.3–146.6 ms `[측정]`을 덮음), 원인 EXITED, 복원 성공, 데이터 같음 | ≥ 9/10 | 9.3, 9.5절 | `finless_exit_report` |
| FIN 없는 죽음, READ 실패 | `gc4_fdhold_sock_kill3_noreport`(증인 끔, 시험 스위치 `NO_EXIT_REPORT`: launcher가 EXITED 말만 끔; FENCED, LEFT, REG_NOTE, 페이지 낱말은 그대로이고 판정은 끝남을 말로만 읽어 launcher 열이 "정보 없음") | kill → 판정 3.5–4.5 s(READ 하드웨어 재시도 초과 3.51–3.76 s `[측정: 문서 ../../../teardown_order/README.md]` + 정리 약 0.15 s + READ 주기 ≤ 0.1 s; `[설계 v3 4.6절에서 어림]`), 원인 NORESP(판정 표 11행: 증인 꺼짐 + launcher 정보 없음 + 하드웨어 응답 없음), 판정 앞에 READ 시한 줄(약 0.5 s)이 하나 이상 있어야 하고 그 줄은 판정이 아님, 판정 뒤 FENCE → 곧바로 FENCED → 활성화, 복원 성공, 데이터 같음 | ≥ 4/5 | 9.3절 판정 표; 11행은 2026-10-17 사용자 결정 2로 둠(9.7절 끝 v3 목록 2) | `finless_read_fail` |
| 옛 TCP 길의 FIN 없는 죽음 | `gct4_fdhold_sock_kill3@gctc` | kill 뒤 20 s 안 판정 0, hold 0; 끝 시각(모름 거절이나 시행 한도)은 보고 | ≥ 4/5 | 1절 빈틈 3 | `finless_tcp_baseline` |
| 자식이 uverbs fd까지 쥐면 거절만 | `gc4_fdhold_uverbs_kill3`(셀 설정으로 복원 끔: 예비 프로세스 없음) | 죽음 판정(원인 EXITED 또는 박동 정체; 시각은 보고), 복원하지 않고 거절, 생존 rank는 fail-fast로 끝남, 판정 뒤 생존 window에 바뀐 칸은 보고 | ≥ 4/5 | 사용자 결정 13; 리뷰: 종료 보고가 곧 FENCED를 만들어 펜스가 이 셀을 막지 못하므로 거절은 셀 설정으로만 | `fdhold_uverbs_refuse` |
| 짧은 멈춤은 투명 | `gc4_stop1500`, `gc4_stop4000`, `gc4_stop8000` | 판정 0, 데이터 같음; 4 000과 8 000은 의심 줄(박동 정체 2 000–2 200 ms)이 있음 | 셀마다 ≥ 9/10 | 9.3절 문턱, gpu-detect 투명 | `stop_transparent` |
| 느린 상대는 판정 없음 | `gc4_slow_duty` | 의심 0, 판정 0; 단계 시간은 보고 | 5/5 | 9.3절 | `slow_no_judge` |
| 긴 멈춤은 펜스 뒤 복원 | `gc4_stop12000_fence` | 생존 rank마다 멈춤 판정이 STOP 뒤 10 000–10 300 ms(분할 막이 문턱 `STALL_MS` − 2 × `PROBE_MS` `[설계 v3 3.4절]`), 판정 시각의 퍼짐 ≤ 200 ms, FENCE 보냄 → FENCED → 활성화 차례(보고 이름 FENCING, FENCED), 판정 → 마지막 게시 ≤ 1 500 ms, CONT 때 대상 PID 없음, 펜스 뒤 생존 window에 바뀐 칸 0, 데이터 같음 | ≥ 9/10 | 9.4절 | `stall_fence_restore` |
| 긴 멈춤, 펜스 끔 | `gc4_stop12000_none` | 멈춤 판정 뒤 거절, fallback 뒤 대기가 오류로 풀림, 판정 뒤 생존 window에 바뀐 칸 0 | ≥ 4/5 | 9.4절 끝 | `stall_none_refuse` |
| 살아서 도는 프로세스의 펜스 | `gc4_freeze12000_fence`(박동 쓰기만 멈춤) | 멈춤 판정 10 000–10 300 ms, launcher가 종료하고 pidfd로 끝남을 봄, 펜스 뒤 바뀐 칸 0, 데이터 같음 | ≥ 4/5 | 9.4절 | `freeze_fence_restore` |
| helper만 멈춘 rank의 펜스 | `gc4_helper_freeze12000`(시험 스위치 `FREEZE_PAGE=12000:helper`: `helperBeat` 쓰기만 멈춤, `watchBeat`와 프로세스는 돎) | helper 멈춤 판정(원인 STALL_HELPER)이 멈춤 시작 뒤 10 000–10 300 ms, launcher가 종료하고 pidfd로 끝남을 봄, 펜스 뒤 바뀐 칸 0, 복원 성공, 데이터 같음 `[설계 v3 4.2절 15행]` | ≥ 4/5 | 9.3절; 펜스는 2026-10-17 사용자 결정 1(9.7절 끝 v3 목록 1) | `helper_stall_fence` |
| 관리망 끊김의 투명 | `gc4_mgmt_mute8`(증인만 8 s 막음) | 판정 0, 기록 QP 잃음 0(기록 QP 다시 짝 맺기 0이고 잃은 기록 0), 끊김 동안 확정된 체크포인트 ≥ 1, 데이터 같음 | 5/5 | 사용자 결정 8 | `mgmt_mute_transparent` |
| 같은 끊김의 옛 길 | `gct4_mgmt_mute8@gct` | 판정 0, 데이터 같음; helper 다시 걸기 줄과 끊김 동안 버린 체크포인트 수는 보고 | 5/5 | gin-reconnect의 8 s 끊김 셀 | `mgmt_mute_tcp` |
| 기록 QP 오류의 다시 짝 맺기 | `gc4_qperr_record`(높은 rank 1 쪽 QP만 오류) | 판정 0, ERR를 본 rank 1이 PAIR(기록, 세대 + 1)를 보내 기록 QP 세대 + 1, 생존 READ QP의 세대는 그대로이고 그 쌍의 READ 실패 0, 그 쌍의 기록이 이어짐, 데이터 같음 `[설계 v3 2.5절]` | ≥ 4/5 | 9.1절, 사용자 결정 6 | `qp_err_repair` |
| 잃은 REJOIN datagram | `gc4_ud_drop_rejoin`(rank 3 kill, 첫 REJOIN datagram 버림) | 다시 보낸 REJOIN으로 복원 성공, 받아들임 1번(멱등), 예비 프로세스에 보낸 FAIL 0 | ≥ 4/5 | 9.5절 | `ud_drop_rejoin` |
| credit 멈춤에도 기록 잃음 없음 | `gc4_credit_stall`(받는 쪽이 500 ms RECV를 다시 내지 않음) | RNR 0, 보내는 쪽 대기열로 미룸, 기록 잃음과 겹침 0, 데이터 같음 | 5/5 | 9.1절 credit | `credit_stall_no_loss` |
| 무장됐으나 활성화 때 예비 프로세스가 없음의 곧바른 fallback | `gc4_kill3_ow_spareabsent`(실행기가 무장된 예비 프로세스를 자기 PID로 끝낸 뒤 5 ms 안에 rank 3 kill) | launcher가 ACTIVATE에 곧바로 REFUSED(까닭 "예비 프로세스 끝남"), FENCED → fallback ≤ 100 ms(옛 1 000 ms 규칙 대신), 대기가 오류로 풀림 `[설계 v3 4.6, 5.4절]` | ≥ 4/5 | 9.5절, 사용자 결정 2, 11 | `spare_absent_refused` |
| 증인 없는 kill | `gc4_kill3_ow_nowitness` | 판정 원인 EXITED(원격 접근 오류 하나로는 판정하지 않음), kill → 판정 100–150 ms(4 KiB 정리 시간 102.0–143.1 ms `[설계 v2 4.6절]`), 첫 판정 → 마지막 생존 rank 게시 68.4–74.4 ms(판정과 FENCED가 같은 사건이라 활성화 뒤 부분 67.2–71.4 ms와 FETCH 1.2–3.0 ms만 남음; 4 KiB 셀의 값 `[설계 v3 4.6절]`), 복원 성공, 떠남과 죽음이 갈림(정상 종료 시행 끝의 hold 0: 대상의 첫 복원 뒤 시작된 hold가 어느 rank에도 없음) | ≥ 4/5 | 9.3절 | `kill_no_witness` |
| 복원 시간과 관문 | rdma 빌드의 gin-mirror 한 죽음 복원 셀(증인 켬): `mi4_kill3_ow`, `mi4_kill1_ow`, `mi4_kill3_ckpt_ow`, `mi4_seg_4k`, `mi4_seg_32k`, `mi4_seg_128k`, `mi4_pull`, `rs4_kill3_mion`, `mi4_train_kill3`, 모두 `@gc` | 첫 죽음 판정 → 마지막 생존 rank 게시: 4 KiB 약 120–197 ms, 학습 모양 약 195–286 ms(지금보다 약 W 짧음) `[설계 v2 4.6절]`; kill → 마지막 게시: 지금 ± 20 ms, 곧 4 KiB 154.5–240.5 ms, 학습 229.6–318.0 ms(지금 174.5–220.5 ms, 249.6–298.0 ms `[측정]`, 1절; 지금은 판정이 kill 뒤 0.07–0.31 ms라 판정 기준 값을 kill 기준으로 씀); 상한 ≤ 2 000 ms(학습 ≤ 1 000 ms)는 그대로; 'later' 0번의 빠른 활성화 0(관문이 FENCED), LATER는 활성화마다 많아야 한 번(rdma 빌드에서는 launcher가 대신 답하므로 launcher 줄의 LATER 수로 셈). 3절의 "약" 범위를 그대로 문턱으로 씀 `[초안: 사전 등록 전 확정]`. 아래 메모 | 셀마다: n 10 셀(`mi4_kill3_ow`, `mi4_train_kill3`) ≥ 9/10, n 5 셀(나머지 일곱) ≥ 4/5 `[초안: 사전 등록 전 확정]` | 9.4, 9.5절 | `restore_time_rdma` |
| 장애 없음: 생존 확인이 조용함 | `gc4_none_probe`(60 s), `gc4_none_ow` | READ 성공률 100 %(상대의 끝, 곧 그 상대의 BYE, LEFT, 판정 뒤에 낸 READ는 뺌), 박동이 는 간격의 최대 < 300 ms(첫 성공 READ부터 상대의 끝 전까지에서 잼), 의심 0, 판정 0, 찢긴 줄 읽기 수는 보고, 입력 멈춤 ≤ 16 ms(학습 모양 ≤ 20 ms; gin-mirror 고정값) | 10/10, 5/5 | 9.2절 | `none_probe_clean` |
| 제어가 관리망에 없음 | rdma 빌드의 모든 시행 | 이 계층이 TCP로 보낸 기록과 자료 바이트 0(증인 BYE 빼고; 라이브러리의 제어 요약 줄), 실행기가 트래픽 중 두 번 읽은 rank 프로세스의 TCP 보낸 바이트 증가 0(`ss`, 커널의 셈; NCCL 자신의 소켓도 그 창에서 조용하다는 `[추론]`이라 pilot에서 확인), 이 계층의 TCP 연결 수와 증인 연결 수가 설정에서 센 증인 수((N − 1) × 요약을 낸 프로세스 수; 증인 끄면 0)와 같음(라이브러리의 두 셈끼리가 아니라 설정과 견줌), 실행기가 읽은 두 GIN 포트의 `active_mtu`와 시행 kv `active_mtu`가 4 096; `ss`로 읽은 연결 수는 보고(NCCL bootstrap 소켓 수를 pilot이 재면 사전 등록 때 조건에 더함) `[초안: 사전 등록 전 확정]` | 모든 시행 | 9.6절 | `no_tcp_control` |
| 상태 페이지 READ의 비용 | 비용 가족 probe, `lat4k`, `lat256k`, `bw256k`, 노드 둘; 팔 `probe-off`, `probe-on`(`@gcp`), `tcp`(`@gctp`) | `probe-on` 대 `probe-off`의 4 KiB 지연 중앙값 차 | 노드마다 차 ≤ 문턱, 문턱 = max(2 %, pilot에서 잰 `probe-off` 두 묶음 사이 4 KiB 지연 중앙값 차의 두 배), 한쪽 판정(느려짐만 셈) `[초안: 사전 등록 전 확정]`(9.9절 끝); 256 KiB 지연과 대역은 보고 | 9.2절 비용 | `cost_probe_lat4k` |
| 긴 hold의 lane(사용자 결정 14: 문서화한 한계) | 위 셀 가운데 hold가 1 s를 넘는 시행(멈춤 펜스, launcher의 LATER 한도) | 생존 rank 사이 lane 깨짐과 DISARM 수 | 넘치면 그 받는 rank의 DISARM이 예측이고 실패로 세지 않음; DISARM이 있어도 데이터는 같아야 함. 대상 시행이 0이면 "자료 없음"이고 실패가 아님. 생존 rank끼리만 계속 주고받는 driver 셀은 gin-dynamic | 사용자 결정 14, 동적 예비 프로세스 리뷰 | `long_hold_lane` |
| FENCED 관문은 마지막 thread를 기다림 | CPU 시험 `gate_fenced`: 실제 자식 프로세스(main thread가 먼저 끝나고 둘째 thread가 500 ms 더 삶; [impl/test/gate_proc_gc.py](impl/test/gate_proc_gc.py)), 시행 열 번은 프로세스 열 개 | 옛 관문(`/proc`, Z = GO)은 둘째 thread가 끝나기 전에 GO; FENCED 관문(pidfd)은 둘째 thread가 끝난 뒤 0–5 ms 안에 GO이고, 시험 장치가 따로 잰 pidfd 읽힘 시각과 5 ms 안; 두 관문의 차이(약 500 ms)는 보고 `[초안: 사전 등록 전 확정]`. 관문 시각은 `impl/gate_fenced.cc`의 실제 pid 모드가 내야 하고 그 전에는 자료 부족이다(지금 그 파일은 시간표 모형이라 이 예측의 시험이 아님, 12절) | 10/10 | 9.4절, 사용자 결정(저녁) | `gate_fenced` |
| 회귀(tcp 빌드) | gin-mirror 7절의 비용 밖 셀을 이름과 env 그대로 `@gct` | gin-mirror 예측 표의 원래 판정식 그대로. 둘째 죽음 셀에서 둘째 kill이 다시 무장보다 먼저 났거나, 첫 복원이 실패했거나, 다시 무장이 오지 않은 시행은 빼지 않고 조건 불충족으로 셈(gin-mirror 8절 그대로) | 원래 기준 | 사용자 결정 1 | `regression_tcp`(gin-mirror의 찾는 키들) |
| 회귀(rdma 빌드, 제어와 무관한 예측) | 같은 셀 `@gc` | gin-mirror 예측 열둘을 원래 판정식으로: `ow_wait_held`(대기 붙잡힘), `ow_data_equal`, `ow_no_reexec`, `ow_revived_done`, `ow_suppress_exact`, `ow_from_pool`, `ckpt_kill_ow`, `kill_other_ow`, `reimage_after_restore`, `second_death_restored`, `train_data_equal`, `train_second_death`. 둘째 죽음 둘의 시간 몫(≤ 2 000 ms, 학습 ≤ 1 000 ms)은 gin-mirror 원래 기준. 둘째 kill과 첫 복원 실패는 위 행과 같이 조건 불충족으로 셈. `store_rdma`와 `train_paced_import`를 넣을지는 열림. 어느 예측도 보지 않는 gin-mirror 셀(거절, mirror 끔 대조, 당기기, 넘침, 간격)은 `@gc`로 돌고 보고만 `[초안: 사전 등록 전 확정]` | 원래 기준 | 9.7절 회귀 행 | `regression_rdma` |
| 회귀(rdma 빌드, mirror 끈 길이 RDMA 저장소로) | gin-restore 셀 `rs4_kill3`, `rs4_kill3_ckpt`, `rs4_kill1`, `rs4_none`, 모두 `@gc` | 데이터 같음과 재실행 없음(`rs4_kill3`은 gin-mirror의 `rg_data_equal`, `rg_no_reexec`; `rs4_kill3_ckpt`, `rs4_kill1`은 같은 두 조건; `rs4_none`은 데이터 같음), helper 소켓과 자료 소켓으로 보낸 이미지 바이트 0 | gin-mirror의 원래 k(`rs4_kill3`은 원래 기준, n 5인 `rs4_kill3_ckpt`, `rs4_kill1`은 ≥ 4/5, `rs4_none`은 모든 유효 시행); 이미지 바이트 0은 구조적 성질이라 셀마다 모든 유효 시행 `[초안: 사전 등록 전 확정]` | 사용자 결정 7 | `regression_rdma_mirror_off` |

**예측 표 파일이 더하거나 이렇게 읽은 조건**(시험 쪽 리뷰가 대조해 찾은 것; 위 표의 글에는 없거나 뜻이 둘이라 사전 등록 전에 이 꼴로 고정한다) `[초안: 사전 등록 전 확정]`.
- RST 두 행(`rst_judge_rdma`, `rst_judge_tcp`): RST 줄을 본 생존 rank가 하나 이상이어야 한다(하나도 없으면 그 시행은 주입이 시험되지 않은 것). 생존 rank 셋 모두가 RST를 봐야 하는지는 열림.
- RST tcp의 "복원 성공"은 대기 붙잡힘, 데이터 같음, 되살린 rank가 끝까지의 셋으로 읽는다.
- uverbs 셀의 "fail-fast로 끝남"은 모든 생존 rank의 대기가 풀림으로 읽는다.
- 짧은 멈춤의 "데이터 같음"은 gin-mirror의 두 열(`data_equal`, `ow_data_equal`)로 읽는다. 4 000, 8 000의 "의심 줄이 있음"은 지금 시행에 의심 줄이 하나 이상으로 읽고, 생존 rank마다여야 하는지는 열림.
- 장애 없음의 학습 모양 ≤ 20 ms는 두 셀이 학습 모양이 아니라 쓰지 않는다.
- FIN 없는 죽음 READ 실패의 "곧바로 FENCED"는 수치가 없어 FENCE에서 FENCED까지의 시각을 보고만 한다.
- 회귀(rdma)에서 어느 예측도 보지 않는 gin-mirror 셀은 보고만이다(위 행).
- 셀 값의 자리 표시(`DIE_RST` 3 000 ms의 기준점, `RST_GAP` 시작, `FREEZE_PAGE` 시작, `QP_ERR`, `CREDIT_STALL`, `DROP_UD`의 값 꼴, `gc4_none_probe`와 멈춤, 끊김 셀의 `STEPS`)와 W는 셀 파일의 `todo`에 있고 pilot 뒤 정한다.

**복원 시간 예측에 대한 메모** `[추론]`. 제어 경로 리뷰는 "관문의 'later' 기다림이 없어져 판정 줄에서 잰 복원이 짧아진다"고 보았지만, 설계 v2 4.6절 끝은 다르게 셈했고
이 문서는 그 셈을 따른다. 지금의 'later' 기다림(102.0–143.1 ms `[설계 v2, 측정: 문서 동적 예비 프로세스 리뷰]`; 이 문서가 다시 센 `activate_ms`는 105.3–146.6 ms
`[측정]`)은 죽은 프로세스의 정리 시간이고, FENCED도 같은 사건(스레드 그룹이 끝남)을 기다린다. 옛 관문은 Z를 끝남으로 쳤고 pidfd도 그때 읽힌다. 그래서 kill에서
활성화까지는 거의 같고, 판정 줄에서 잰 복원이 짧아지는 몫은 'later' 전체가 아니라 판정이 늦어진 약 W와 20 ms 다시 묻기 걸음뿐이다. 예외는 증인을 끈 셀이다:
판정(EXITED)과 FENCED가 같은 사건이라 판정 줄에서 잰 복원이 활성화 뒤 부분과 FETCH(4 KiB 68.4–74.4 ms `[설계 v3 4.6절]`)로 줄어든다. `restore_time_rdma`의 kill 기준 범위는 이 셈을 시험한다.

**다시 예측해야 하는 옛 예측**(rdma 빌드에서 같은 결과를 기대할 수 없는 것; 끝난 실험의 결과와 해석은 바꾸지 않는다) `[추론]`.
- 복원 시간과 관문 열(`ow_restore_time`, `rg_restore_time`, 'later' 수, `activate_ms`): 관문이 FENCED로 바뀌어 빠른 모드가 없어지고 활성화 뒤 부분의 TCP 몫이
  없어진다. 위 `restore_time_rdma`가 대신한다.
- 예비 프로세스 없음(`rg_spare_absent_fallback`): 무장 조건이 예비 자리 HELLO를 요구하므로(9.5절) 예비 프로세스가 처음부터 없는 그 셀은 rdma 빌드에서 무장되지 않고 fail-fast가 된다
  `[설계 v3 4.6절]`. "무장됐으나 활성화 때 없음"은 위 `spare_absent_refused`가 잰다. 이 해석은 9.7절 끝 v3 목록 6이다.
- 무장 조건(`rg_nospare_failfast`): "등록이 있음"이 "그 노드 launcher와 짝 맺기가 됐고 launcher가 이 화신의 pidfd를 쥐며, (rank, i + 1)의 예비 자리가 HELLO 이상"이 된다(9.5절).
  예비 프로세스가 없으면 무장되지 않으므로 판정은 gin-mirror와 같은 fail-fast이고, kill에 견준 시각만 W만큼 늦다 `[설계 v3 4.6절]`.
- mirror 끈 TCP 저장소를 보던 예측(`rg_*` 가운데 TCP 올리기와 FETCH를 전제한 것): 사용자 결정 7로 rdma 빌드에서는 RDMA 저장소를 탄다.
- gin-harden의 "FIN = 죽음"과 거절 1 000 ms 규칙, gin-reconnect의 8 s 끊김 셀의 다시 걸기 줄: rdma 빌드에서는 증인에만 닿는다.
- 장애 없음의 입력 멈춤 상한(`ow_none_clean` 16 ms, `train_none_clean` 20 ms): 감시 스레드의 일이 늘고 기록 왕복이 RDMA가 된다. 위 `none_probe_clean`에 같은 값을
  두고 pilot에서 다시 본다.

## 4. 범위

**포함.** 9절의 설계(제어 QP와 링, 상태 페이지, 생존 판정 표, 펜스 국면, launcher, 준비와 관리망에 남는 것, 충돌 표, 이행 단계), gin-mirror ln4 위의 구현(충돌이
닫히고 독립 리뷰를 반영한 뒤), launcher 프로그램, 시험 스위치, 7절의 셀. 같은 소스의 TCP 제어 빌드(회귀용). 미리 띄운 예비 프로세스가 launcher를 거쳐
등록되고 활성화되는 길.

**gin-dynamic과의 경계**(동적 예비 프로세스 설계 v2의 열린 것 1의 권고를 이 문서의 선택으로 씀; 9.7절 "이 문서의 선택"). 이 실험의 launcher는 등록(노드 안 인사와
pidfd), 종료 보고(EXITED)와 LEFT, FENCE와 FENCED, 미리 띄운 예비 프로세스의 중계(예비 프로세스가 아직 준비되지 않았으면 LATER를 한 번 대신 답함; 사용자 결정 4),
예비 프로세스의 노드 안 인사(Unix 소켓의 HELLO, 자기 pidfd를 넘김), 준비됨, 재생 실패 알림의 규약까지 만든다. SPAWN은 준비 단계의 공유 헤더에 종류만 두고 launcher가 "spawn not built"로 REFUSED한다(짝은
사용자 결정 12대로 hold 시작 때 보냄). SPAWN 실행, 띄운 예비 프로세스의 두 한도(인사 2 000 ms, 준비 `NCCL_GIN_RESTORE_SPARE_START_MS` 5 000 `[설계 v2, 초안]`), 그
시험 스위치, 동적 예비 프로세스의 복원 셀, 같은 rank의 둘째 kill(지금 driver는 예비 프로세스에서 단계 kill을 끄고 실행기는 같은 rank를 거절함), 긴 hold 셀은 gin-dynamic에서 한다.
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
| launcher | 노드마다 하나(rain, sunny), 실행기가 클러스터 hold 시작 때 한 번 띄우고(시행마다가 아님) hold 끝에 끔. sunny는 ssh 하나로 띄움(시험 장치). 실행기는 시행 앞뒤로 launcher마다 pid와 시작 시각을 남김 `[설계 v3 5.2절]` | 계획 |
| 데이터 QP 시한 | `NCCL_IB_TIMEOUT=14`, retry 7. 이 NIC은 floor 때문에 재시도 초과가 3.5–3.8 s | `[측정: 문서 ack_timeout]` |
| 라이브러리 | gin-mirror ln4(`mi`) + 9절의 제어 계층(`gc`); 같은 소스의 TCP 제어 빌드(`gct`). 장치 코드 변경은 mirror 끈 rank의 더러운 segment 표시(2c)만; 그 밖은 바뀌지 않음(2026-10-17 사용자 결정) | 구현 전 |
| 관리망 | 1 GbE. 이 계층에서는 증인 소켓만 쓴다(9.6절) | 사용자, 계획 |
| UD 경로 MTU | GIN 포트(rain `mlx5_1`, sunny `mlx5_0`)의 `active_mtu` 4 096, GIN 쌍의 경로 MTU 4 096 | `[측정: 문서]` 제어 경로 설계 리뷰가 2026-09-23 장치 캡처(`ibv_devinfo -v`)와 gin-restore 실행 가능성 kv에서 읽음; 이 문서에서 다시 보지 않음. RoCE의 `active_mtu`는 netdev MTU를 따르므로 준비 때 rank마다 `ibv_query_port`로 ≥ 2 048을 검사하고(못 맞추면 Resume 조건 42로 fail-fast) 시행 kv `active_mtu`에 남긴다 `[설계 v2 2.5절]` |

## 6. 변수

- **독립변수.** 제어 빌드(rdma `gc`, tcp `gct`), 장애(SIGKILL, RST로 죽기, 자식이 증인 소켓만 쥔 kill, 자식이 uverbs fd까지 쥔 kill, SIGSTOP 1 500, 4 000,
  8 000, 12 000 ms, 50 ms씩 멈춤 반복, 박동 쓰기만 멈춤, 살아 있는 RST와 포트 닫힘, 증인 8 s 막음, 기록 QP 오류 상태, UD datagram 버림, credit 멈춤), 펜스
  (`NCCL_GIN_RESTORE_FENCE=lineage|none`), 증인(`NCCL_GIN_CTRL_WITNESS=1|0`, 기본 1), launcher 종료 보고(켬, 끔: 시험 스위치), 상태 페이지 READ(켬, 끔: 비용 셀).
- **종속변수.** gin-mirror의 종속변수 전부(대기 결과, 데이터 비교, 단계 실행 수, 억제 수, 복원 단계별 시각, 입력 멈춤)와 더해서: 판정 종류와 시각(주입 또는
  마지막 박동 증가 → 판정), 생존 rank 사이 판정 시각의 퍼짐, READ 성공률과 지연(중앙값, 최대), 박동 증가 간격의 최대, 찢긴 줄 읽기 수, 의심과 멈춤 판정 수,
  증인 상태, 계보 국면 차례(FENCING, FENCED)와 시각, launcher의 종료와 pidfd 확인 시각, LATER 수, 펜스 뒤 생존 window에 바뀐 칸, 기록 QP 세대와 다시 짝 맺기
  수, 보내는 쪽 대기열 최고, 이 계층의 TCP 바이트와 연결 수, put 지연과 묶음 대역.
- **통제변수.** gin-mirror 6절의 통제변수 전부(mirror 켬, segment 자리 3, lane 1 MiB, 당기기 50 %, 시행마다 프로세스를 새로 띄움 등). 더해서: READ 주기
  `NCCL_GIN_TS_PROBE_MS` 100, READ 시한 500 ms, FIN이나 RST 뒤 확인 창 W(`NCCL_GIN_CTRL_CONFIRM_MS`, 20–50 ms `[초안]`: pilot의 장애 없는 셀에서 잰 `watchBeat` 간격 최대의
  5배 이상, 20 ms 아래로는 두지 않음 `[설계 v2 4.3절]`), 의심 2 000 ms, 멈춤 10 000 ms, 데이터 경로 거부권 창 1 000 ms, READ 응답 없음의 다시 짝 맺기 3번, RST 뒤 거절
  간격(tcp 대조 빌드의 매개변수, 기본 1 000, RST 셀만 100; 9.3절), 링 자리 64, outbox 2 × 1 MiB, 기록 QP의 timeout은 `NCCL_IB_TIMEOUT`(14)과 같음, 모든 rank가 같은 값(준비 합의).
  감시 스레드의 QP 감시 `NCCL_GIN_Q4_QPWATCH_MS=0`과 helper 쪽 `NCCL_GIN_TS_QPWATCH_MS=10`(학습 셀 50)은 gin-mirror 실행기 그대로 둔다(`../mirror/impl/test/run_mi.sh` 39, 71, 177,
  181행 `[소스]`): 감시 스레드가 QUERY_QP를 내면 `watchBeat` 간격이 늘어 W를 정하는 셀이 흐려진다 `[설계 v3 4.3절]`. LATER 뒤 launcher 박동 한도 `NCCL_GIN_CTRL_LAUNCHER_STALL_MS`
  (1 000, 2026-10-17 사용자 결정 4)와 `NCCL_GIN_RESTORE_SPARE_START_MS`(5 000, ACTIVATE부터) `[설계 v3 4.3절]`.

## 7. 실험 셀, 반복 수, 대조군

초안이다. n은 감지 설계와 제어 경로 설계의 이행 계획에서 왔고 pilot의 시행 wall을 본 뒤 사전 등록에서 고정한다. 배치, 4 KiB 덮어쓰기 workload(`RS_OVERWRITE=1`),
단계 사이 5 000 µs, 복원 시한 20 000 ms는 gin-mirror와 같다. 멈춤 셀은 시행이 길어(12 000 ms 멈춤과 복원) 시행 한도를 60 s로 둔다 `[추론]`.

| 셀 | 조건 | 빌드와 반복 수 | 종류 |
|---|---|---|---|
| `gc4_none_ow` | 장애 없음 | `@gc` 5 | 대조 |
| `gc4_none_probe` | 장애 없음, 60 s 동안 보냄 | `@gc` 10 | 생존 확인의 조용함 |
| `gc4_kill3_ow` | rank 3 SIGKILL(실행기, 대부분 FIN) | `@gc` 10 | 판정 시간 |
| `gc4_kill3_ow_nowitness` | 같고 증인 끔 | `@gc` 5 | 증인 없는 판정 |
| `gc4_rst_kill3` | rank 3이 연결된 소켓에 linger 0을 두고 스스로 SIGKILL(생존 rank 모두 RST) | `@gc` 10, `@gctc` 10(간격 100) | RST |
| `gc4_rstgap_live300` | 살아 있는 rank 1이 연결 소켓을 linger 0으로 닫고 수신 대기를 300 ms 닫음(fail-fast; 대상 `SUBJECT_RANK=1`) | `@gc` 5 | RST(살아 있음) |
| `gct4_rstgap_live50`, `gct4_rstgap_live300` | 같고 50 ms, 300 ms(대상 `SUBJECT_RANK=1`) | `@gctc` 10, 5(간격 100) | 100 ms 간격의 대가 |
| `gc4_fdhold_sock_kill3` | rank 3이 자식을 fork해 증인 소켓을 넘긴 뒤 부모 SIGKILL | `@gc` 10 | FIN 없는 죽음 |
| `gc4_fdhold_sock_kill3_noreport` | 같고 증인 끔, 시험 스위치 `NO_EXIT_REPORT`(launcher가 EXITED 말만 보내지 않음; FENCED, LEFT, REG_NOTE, 페이지 낱말은 그대로). 증인이 꺼져 자식이 넘겨받는 소켓은 없고, 이 셀이 보는 것은 launcher가 끝남을 모를 때의 READ 판정 길이다 | `@gc` 5 | FIN 없는 죽음(READ) |
| `gct4_fdhold_sock_kill3` | 같은 주입, 옛 TCP 길(helper 소켓을 넘김) | `@gctc` 5 | 대조 |
| `gc4_fdhold_uverbs_kill3` | 자식이 uverbs fd까지 쥠 | `@gc` 5 | 한계 셀(거절만) |
| `gc4_stop1500`, `gc4_stop4000`, `gc4_stop8000` | rank 3 SIGSTOP 그 길이 뒤 SIGCONT | `@gc` 각 10 | 투명 |
| `gc4_stop12000_fence` | 12 000 ms, `FENCE=lineage` | `@gc` 10 | 펜스와 복원 |
| `gc4_stop12000_none` | 12 000 ms, `FENCE=none` | `@gc` 5 | 거절 |
| `gc4_slow_duty` | rank 3에 SIGSTOP과 SIGCONT를 50 ms씩 20 s | `@gc` 5 | 느린 상대 |
| `gc4_freeze12000_fence` | rank 3의 박동 쓰기만 12 000 ms 멈춤(프로세스는 돎), `FENCE=lineage`(대상 `SUBJECT_RANK=3`) | `@gc` 5 | 도는 프로세스의 펜스 |
| `gc4_helper_freeze12000` | rank 3의 `helperBeat` 쓰기만 12 000 ms 멈춤(`FREEZE_PAGE=12000:helper`; `watchBeat`와 프로세스는 돎), `FENCE=lineage`(대상 `SUBJECT_RANK=3`) | `@gc` 5 | helper만 멈춘 rank의 펜스(판정 표 15행) |
| `gc4_mgmt_mute8`, `gct4_mgmt_mute8` | rank 1의 증인(tcp는 helper 소켓) 8 s 막음(대상 `SUBJECT_RANK=1`) | `@gc` 5, `@gct` 5 | 관리망 끊김 |
| `gc4_qperr_record` | rank 0과 rank 1 사이 기록 QP 가운데 높은 rank 1 쪽 하나만 로컬에서 오류 상태로(시험 스위치; 낮은 rank 쪽은 RTS 그대로; 대상 `SUBJECT_RANK=1`) | `@gc` 5 | 다시 짝 맺기(어느 쪽이든 시작) |
| `gc4_ud_drop_rejoin` | rank 3 kill, 예비 프로세스의 첫 REJOIN datagram을 버림 | `@gc` 5 | UD 잃음 |
| `gc4_credit_stall` | rank 2가 500 ms 동안 RECV를 다시 내지 않음(대상 `SUBJECT_RANK=2`) | `@gc` 5 | credit |
| `gc4_kill3_ow_spareabsent` | 예비 프로세스가 HELLO를 보내 rank 3이 무장된 뒤, 실행기가 그 예비 프로세스를 자기 PID로 끝내고 5 ms 안에 rank 3 kill(처음부터 예비 프로세스가 없으면 무장되지 않아 fail-fast라 이렇게 바꿈, 9.5절) | `@gc` 5 | 곧바른 fallback |
| gin-mirror 회귀(tcp) | gin-mirror 7절의 비용 밖 셀 전부를 이름과 env 그대로 | `@gct` 그 실험의 n | 회귀 |
| gin-mirror 회귀(rdma) | 같은 셀 | `@gc` 그 실험의 n | 회귀와 다시 예측 |
| 비용 가족 probe | 지표 `lat4k`, `lat256k`, `bw256k`, 노드 둘; 팔 `probe-off`, `probe-on`(`@gcp`), `tcp`(`@gctp`); gin-restore 9.15.6의 섞기 틀 | 팔마다 6 | 비용 |
| 빌드 검사 | 매크로 없는 프로그램 넷과 라이브러리 장치 객체를 `mi`와 비교(다섯 빌드 `gc`, `gct`, `gctc`, `gcp`, `gctp` 모두); `gct`의 호스트 파일 전처리 결과를 ln4와 비교 | 빌드 검사 | 회귀 |
| CPU 시험 `gate_fenced` | main thread가 먼저 끝나고 다른 thread가 500 ms 더 사는 프로그램에서 옛 관문과 FENCED 관문(예측 `gate_fenced`) | 10 | 관문 |

- 시험 스위치로 넣는 셀 아홉(위의 `SUBJECT_RANK` 표시)은 kill이나 멈춤을 받는 rank가 없어 실행기가 대상 rank를 셀 파일의 `SUBJECT_RANK`로 받는다. 채점기의
  판정, 펜스, launcher 열은 대상 rank를 기준으로 센다(시험 쪽 리뷰 막는 문제 2).
- kill 셀은 gin-mirror처럼 실행기가 기록한 PID로 트래픽 중 kill한다. 멈춤 셀의 SIGSTOP과 SIGCONT도 실행기가 자기가 띄운 rank의 정확한 PID에만 보내고, 끝에
  CONT 뒤 그 PID에 SIGKILL로 정리한다.
- 비용 셀은 READ가 켜진 rdma 빌드와 끈 rdma 빌드를 같은 바이너리에서 `NCCL_GIN_TS_PROBE_MS=0`으로 가른다. tcp 팔은 회귀 대조다.
- gin-mirror 회귀 셀의 수는 시행 188(비용 밖)이라 두 빌드를 합치면 약 380 시행이다 `[측정: 문서 ../mirror/README.md의 시행 수(복원과 거절 168, 회귀 20)에서 셈; 추론]`. 줄일지는
  사전 등록에서 정한다.

## 8. 제외 기준과 중단 기준

초안이다. gin-mirror 8절(그리고 그 실험이 물려받은 gin-restore 8절)의 규칙을 그대로 쓰고 아래를 더한다. 채점기([impl/test/score_gc.py](impl/test/score_gc.py))와 hold
([impl/test/hold_gc.sh](impl/test/hold_gc.sh))는 아래 규칙을 같은 줄 꼴과 같은 규칙으로 센다(2026-10-17 시험 쪽 리뷰와 고침, 12절).
- **제외(채점에서 빼고 채움).** gin-mirror의 제외 전부(kill이 첫 확정 무장 체크포인트 전, 셀이 정한 workload나 mirror 설정과 다르게 돈 시행 등). 더해서:
  - 주입이 첫 확정 무장 체크포인트 전인 시행. 예비 프로세스가 있는 주입 셀 모두에 건다(kill에 더해 SIGSTOP, `FREEZE_PAGE`, 스스로 죽는 `DIE_RST`의 주입 줄 시각으로 셈).
  - launcher가 시행 시작 때 두 노드 모두에서 준비되지 않은 시행(시작 문의 검사).
  - 셀이 정한 제어 빌드, 펜스, 증인 설정, launcher env(`NO_EXIT_REPORT` 등), W(`NCCL_GIN_CTRL_CONFIRM_MS`, 사전 등록 값), READ 주기(`NCCL_GIN_TS_PROBE_MS`)와 다르게 돈 시행.
  - 실행기의 SIGSTOP, SIGCONT, fork 자식 주입 줄이 없거나 정한 시각보다 1 s 넘게 어긋난 시행. `gc4_kill3_ow_spareabsent`에서 예비 프로세스 kill과 rank 3 kill의 간격이
    5 ms를 넘은 시행(`inject_late`; 간격은 같은 노드의 `mono_ms`로 잼).
  - 시행 중 launcher가 끝났거나(실행기가 시행 앞뒤로 남긴 launcher의 pid나 시작 시각이 다름) 시험 스위치 셀 밖에서 launcher QP가 ERR가 된 시행(그 노드 rank의 복원이 막힘;
    셈하는 규칙은 아래 STOP_launcher) `[설계 v3 5.2절]`.
  - `gc4_kill3_ow_spareabsent`에서 예비 프로세스를 끝낸 뒤 rank 3 kill 전에 체크포인트가 확정되어 무장이 풀린 시행.
  - smoke와 pilot은 늘 제외하고 본 실행과 따로 센다. pilot과 smoke hold(P0–P4, 비용 pilot `costpilot*`)는 이름이 `pilot`이나 `smoke`로 시작하는 결과 폴더에서만 돌고, 본 실행
    hold(C*, RG-*, COST-*)는 그런 폴더에서 거절된다. P0은 smoke로 센다. 9.9절 끝의 채점하지 않는 멈춤 pilot 셀은 따로 된 이름 `gc4_stop12000_pilot`(hold P4)을 쓴다.
- **둘째 죽음은 빼지 않는다**(2026-10-17 조율 세션 결정, 시험 쪽 리뷰 막는 문제 3). `@gct`와 `@gc` 모두 gin-mirror 8절의 사전 등록 규칙 그대로다: 둘째 kill이 다시 무장보다
  먼저 난 시행, 첫 복원이 실패한 시행, 다시 무장이 오지 않은 시행은 빼지 않고 그 예측의 조건 불충족으로 센다. 이 문서의 앞 초안에 있던 "둘째 kill이 그 rank의 다시 무장
  줄 전인 시행은 제외"는 tcp 회귀의 원래 기준을 바꾸고 첫 복원 실패를 "자료 부족"으로 숨겨 없앴다. 다시 무장 전의 kill이 몇 번이었는지는 SCORE.md에 셀마다 보고한다.
- **중단(그 hold의 남은 시행을 멈추고 올림).** gin-mirror의 STOP 규칙 전부(CUDA 메모리 오류, 새 mlx5 명령 오류나 rain 펌웨어 명령 실패의 증가, 시행 뒤 남은
  프로세스, kv의 설정 오류나 NIC 오류, rain QUERY_QP 상한, pool 등록 실패, 남은 호스트 메모리, rain BAR1 시작 검사). 더해서:
  - launcher는 hold마다 노드마다 하나다(5절). 시행 시작 때 두 launcher의 등록 표가 비어 있지 않으면(앞 시행의 (rank, 화신)이 EXITED, LEFT, FENCED로 끝나지 않았거나 예비 자리가
    남음) 그 시행을 돌리지 않고 STOP_launcher. 한 hold의 셀은 launcher env가 하나여야 한다(`NO_EXIT_REPORT` 셀은 hold C6에 혼자).
  - launcher가 등록받거나 띄운 pidfd가 아닌 프로세스에 신호를 보내려 한 줄(launcher가 거절하고 적음; 하나라도 있으면 STOP_launcher).
  - 시행 중 launcher가 끝나거나 그 Unix 소켓이 끊김, 시험 스위치 셀 밖의 launcher QP ERR(그 시행은 위의 제외로 치고 hold를 멈춤; STOP_launcher).
  - 등록의 pid 검사 실패 줄(pidfd의 pid가 접속한 쪽 pid와 다르거나 시작 시각이 다름; launcher가 거절하고 적음; STOP_launcher) `[설계 v3 5.2절]`.
  - **STOP_launcher 줄의 꼴.** launcher 줄 가운데 `(STOP_launcher)`로 끝나는 것(등록받지 않은 프로세스에 신호, FENCE_NAK, RNIC 전송 실패)과 `(STOP_launcher: …)` 꼴(pid 검사
    실패: `… (STOP_launcher: a pidfd that is not the peer's own)`) 둘 다 센다 `[소스: impl/launcher/gin_launcher.c]`. hold는 시행마다 그 시행 조각을, hold 끝에는 launcher 로그
    꼬리를 한 번 더 본다.
  - **시험 스위치 셀 밖의 launcher QP ERR를 세는 규칙.** 시험 스위치 셀(`QP_ERR`, `DROP_UD`, `CREDIT_STALL`) 밖에서, 그 시행의 시작 표지(`trial_start`) 뒤이고 launcher 줄의 첫
    "is leaving" 전이며 시행의 대상 rank가 아닌 rank에서 난 QP 잃음 줄만 센다. 끝날 때(떠남 뒤)의 QP 잃음과 대상 rank의 것은 세지 않는다.
  - **채점 규칙**(이 문서가 정함, DRAFT): launcher의 줄 "refused to signal … (STOP_launcher)"는 등록받지 않은 프로세스에 신호를 보내려 한 경우뿐 아니라, launcher가 쥐지 않은 pidfd의
    (rank, 화신)에 대한 FENCE에서 나온 경우(FENCE_NAK)에도 STOP_launcher로 센다. 짝은 FENCE_NAK에 곧바로 fallback한다 `[설계 v3 4.4절]`. FENCE_NAK이 난 그 시행을 제외로 칠지
    실패로 셀지는 열림(9.7절 끝 열린 것 3; 지금 채점기는 셈).
  - 시행 앞뒤 RNR 카운터(`rnr_nak_retry_err` 같은 port counter)의 증가가 credit 멈춤 셀 밖에서 나옴(credit 셈이 맞으면 0 `[설계 v2 2.2절]`). 포트 전체의 수라 같은 포트의
    다른 사용자 트래픽도 셀 수 있어, STOP 줄에 증가량과 시행 wall을 함께 적는다.
  - 시행 뒤 멈춘(state T) 프로세스나 `gin_fdhold` 자식이 남음(STOP_left). 실행기는 자기가 기록한 rank PID에만 CONT 뒤 SIGKILL을 보낸다. fd를 쥔 자식은 이름으로 끄지 않고, fork
    줄의 PID를 uid, 이름, 같은 노드의 부모 시작 tick과 견준 뒤에만 그 PID로 끈다(짝의 판정 줄 + 1 s 뒤, 판정이 없으면 kill + 25 s 뒤).
  - UD 경로 MTU가 2 048보다 작거나 rank 사이에서 다름(라이브러리가 rdma 길을 거절; 거절이면 그 hold를 시작하지 않음). 실행기가 시행 뒤 읽은 `active_mtu`가 시행 앞과 다름도
    STOP_mtu다.
  - 기록 QP나 상태 페이지 READ QP의 비동기 이벤트(`ncclIbStats` 셈 > 0)가 시험 스위치 셀 밖에서 나옴.
- 멈춤 길이의 허용(정한 길이보다 1 s 넘게 어긋나면 제외)을 좁힐지(시험 쪽 리뷰 권고 50 ms)는 열림(9.7절 끝 열린 것 4).
- 다른 사용자 작업(gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 태그 작업)이 보이면 hold를 시작하지 않는다(`cluster_run.sh`의 시작 문). 이름으로 끄지 않고 실행기가
  기록한 PID만 끈다.

## 9. 설계와 실행 방법

### 9.1 제어 QP와 링

**QP 구성**(제어 경로 설계 2.1절; 모두 GIN PD 안 호스트 QP, 장치 코드 없음).

| 쓰임 | QP | 주인 스레드 | 속성 | 까닭 |
|---|---|---|---|---|
| 기록(지금 helper 소켓의 모든 종류) | `gdaki_context`마다(그 안의 하위 문맥마다가 아님), 쌍마다 호스트 RC QP 하나. 양쪽이 자기 SQ로 SEND, 자기 RQ로 받음 | helper(준비 중에는 준비 스레드, 예비 프로세스는 driver가 쓰고 helper 시작 때 넘김; 지금 `pe.fd`를 넘기는 꼴, 10208) | timeout = `NCCL_IB_TIMEOUT`(14), retry 7, rnr_retry 3(유한), SQ 96(자리 64 + READ 16 + 여유 16), RQ 64, max_rd_atomic 16(큰 자료 READ), 접근 비트 REMOTE_READ만 `[설계 v2 2.1절]` | 재시도 초과가 데이터 QP와 같은 때(3.5–3.8 s) 와서 제어 길이 데이터 길보다 먼저 죽지 않게 함 `[측정: 문서 ack_timeout; 추론]`. credit 셈에 버그가 있으면 RNR NAK가 끝없이 돌지 않고 오류 상태로 드러남 |
| 생존 READ | 쌍마다 호스트 RC QP 하나(SQ 4, RQ 0) | 감시 스레드(`gdakiQ4Watch`, 20 µs 걸음, helper와 따로; 1280, 1300, 1590–1640). 상태 바꿈(오류 상태, RESET, 다시 잇기)도 감시 스레드가 함: helper가 그 쌍의 요청 낱말을 세우면 감시 스레드가 READ를 멈추고 flush를 걷은 뒤 바꾸고 낱말을 지움 | 기록 QP와 같은 timeout, retry 7, max_rd_atomic 1, 접근 비트 REMOTE_READ만, READ 시한 500 ms | helper는 펌웨어 단계(3 000 ms)나 라운드(25 000 ms) 안에서 막힐 수 있다(3274, 3282). 생존 확인이 helper에 매이면 안 된다. 넘기기 규약은 RESET 중의 post 실패를 READ 실패로 세지 않게 함 |
| 첫 만남, 다시 짝 맺기 | 문맥마다 UD QP 하나(SQ 64, RQ 64), Q_Key는 문맥 nonce의 아래 31비트(launcher UD QP는 launcher 자신의 Q_Key, 노드 안 인사로 받음) | helper | RQ 64 × (GRH 40 B + 2 KiB) | 아직 끝점을 모르는 상대(예비 프로세스, launcher, 오류 뒤의 쌍)와 연결 없이 첫 기록을 나눔. Q_Key가 다른 communicator의 datagram은 NIC이 버림 `[추론]` |
| launcher | rank마다, launcher마다 호스트 RC QP 둘: 기록 QP(launcher 말; launcher가 rank의 outbox를 READ하므로 rank 쪽 `max_dest_rd_atomic` ≥ 1, outbox REMOTE_READ)와 생존 READ QP(rank가 launcher 페이지를 READ; launcher는 그 QP에 내지 않음). 따로 짝 맺고 다시 맺음 `[설계 v3 2.1절; 측정: launcher 헤더를 읽음]` | 기록 QP: rank 쪽 helper, launcher 쪽 단일 스레드. 생존 READ QP: rank 쪽 감시 스레드 | 기록 QP와 같음 | 등록, 활성화 중계, 펜스, 종료 보고(9.5절) |
| 그대로 | 저장소 올리기, FETCH, mirror, NIC 복사 경로, GIN PD 루프백 | gin-mirror 그대로 | 바뀜 없음 | – |

- rank 4, launcher 둘이면 rank마다 새 호스트 QP 11개(기록 3, 생존 READ 3, UD 1, launcher 2 × 2), launcher마다 RC 8과 UD 1이다 `[설계 v3 2.1절; 추론]`(설계 v2의 9개는 launcher 몫을
  하나로 셈).
- 호스트 QP 틀 `gdakiMiHostQpCreate`(16405–16578)는 지금 QP마다 자기 CQ를 만들고(16490) RQ가 1이다(16501) `[소스]`. 이것을 SQ와 RQ 깊이, 접근 비트, QP 종류, timeout,
  rnr_retry에 더해 바깥 CQ(또는 없음), completion channel, UD Q_Key를 인자로 받게 넓힌다(기본 인자는 지금 값) `[설계 v3 2.1절]`. 모든 새 QP와 CQ는 자기 `ncclIbStats`를 단다
  (널 문맥이면 net_ib 비동기 이벤트 스레드가 널을 역참조함; 16411–16435). 공유 CQ의 `cq_context`는 QP 하나의 stats일 수 없어, CQ의 주인이 쥐고 그 CQ의 모든 QP보다 오래 사는
  stats로 둔다(없애는 차례: QP → CQ → channel → stats) `[설계 v3 2.1절; 추론]`.
- CQ는 주인 스레드마다 따로다: helper의 CQ 하나(기록, UD, launcher QP)와 completion channel 하나, 감시 스레드의 CQ 하나(생존 READ QP). 두 스레드가 한 CQ를 걷지 않는다.
  helper CQ는 기록 QP 셋과 launcher QP 둘의 (SQ + RQ) 5 × 160 = 800에 UD의 128을 받아야 해서 1 024, 감시 스레드 CQ는 64다. CQ가 넘치면 그 CQ의 모든 QP가 오류 상태가
  되어 모든 쌍이 한꺼번에 기록 길을 잃기 때문이다. completion channel은 깨면 걷고 다시 무장한 뒤 한 번 더 걷는다 `[설계 v2 2.1절]`.
- **저장소 QP를 다시 쓰지 않는 까닭** `[소스, 추론]`: 맡긴 rank와 짝 사이에만 있고, 주인이 application 스레드이며, 그 QP가 오류면 다시 잇는 STORE_REQ가 제어
  길이라 고리가 생기고, 체크포인트마다 30 MiB WRITE(부하에서 19.1–19.4 ms, p99 20.1–24.1 ms `[측정: 문서 gin-mirror 9.8절 확인 3]`) 뒤에 기록이 줄을 선다.

**링과 흐름 제어.** rank마다 호스트 받기 영역 하나를 두고 보내는 상대마다 자리 64개(자리마다 2 KiB = 기록 1 872 B + 봉투 64 B)로 나눈다. 그 쌍 기록 QP의 RQ에
자리마다 RECV를 미리 내고, 보내는 쪽의 SEND 하나가 다음 RECV 하나를 쓴다. 영역의 MR은 LOCAL_WRITE만 주어 상대가 RDMA로 쓸 수 없다. rank 4, launcher 둘이면
(3 + 2) × 128 KiB = 640 KiB다.
- SEND/RECV를 고른 까닭: CQE가 completion channel로 helper의 `poll()`을 곧바로 깨우고(지금 helper는 소켓 묶음을 `poll(…, 1 ms)`로 기다림, 17808), CQE는 자료가 놓인
  뒤에 오며, 받는 메모리에 원격 쓰기 권한이 필요 없다. WRITE with immediate는 같은 비용에 원격 쓰기만 더하고, WRITE와 순번 낱말 폴링은 깨우기가 없어 기록마다
  0–1 ms 늦음이 PAUSE, PAUSED, RESUME 같은 차례에 쌓인다 `[추론]`.
- credit: 보내는 쪽은 그 쌍의 지금 세대 g에서 보낸 순번 S와 받는 쪽이 다 쓴 수 C를 알고 S − C < 64일 때만 SEND를 낸다(그래서 RNR이 없음). C는 거꾸로 오는 기록의
  봉투(`gen`이 g일 때만), 받는 쪽 상태 페이지의 소비 낱말 `(gen << 32) | count`(감시 스레드의 READ가 이미 가져옴; 낱말의 gen이 g가 아니면 버림), 그리고 막혔을 때만
  helper가 기록 QP로 같은 낱말을 READ해서 온다. credit만 나르는 SEND와 원자 연산은 없다 `[설계 v2 2.2절]`. 소비 수는 세대마다 0부터이고, 옛 세대의 도착은 새 세대의 수에
  넣지 않는다(그래야 S − C가 음수가 되지 않음) `[설계 v3 2.2절]`.
- launcher 고리의 credit: launcher는 EXITED, LEFT, FENCED처럼 한 방향으로만 말할 때가 있어 봉투만으로는 credit이 돌아오지 않는다. 그래서 rank 페이지에 launcher 몫
  `rxConsumedL[nLaunchers]`, launcher 페이지에 rank마다 credit 칸(launcher 헤더의 `glPageCredit.consumed`; 설계 v3와 이 문서의 앞 판은 `rxConsumed[N]`으로 적음)을 두고 같은 세 길을 쓴다
  `[설계 v3 2.2, 3.6절; 소스: launcher_msg.h]`.
- 세대와 자리 `[설계 v2 2.2절]`: 두 끝 모두 RTR로 가기 전에 RECV 64개를 낸다. `wr_id`에 (쌍, 세대, 자리)를 싣고, QP를 RESET에서 다시 쓸 때 옛 세대의 CQE(flush와 아직 안
  걷은 성공)를 다 걷기 전에는 그 자리에 새 RECV를 내지 않으며 옛 세대 CQE의 기록은 버린다. 세대가 바뀌면 보내는 쪽 대기열의 아직 안 낸 기록도 버리고 부른 쪽에는
  지금의 "보내기 실패"로 알린다(사용자 결정 6).
- 보내기는 막지 않는다: credit이 없으면 쌍마다 4 096 기록(약 7.6 MiB)까지의 보내는 쪽 대기열(필요할 때 늘림)에 넣고, 차거나 시한이 지나면 지금 `gdakiTsSend`(8141–8162)의
  "보내기 실패"와 같은 값을 돌려준다. TCP의 커널 보내기 버퍼와 같은 노릇이다.
- helper는 CQ에서 꺼낸 기록을 상대마다의 받은 줄(inbox)로 옮기고 자리의 RECV를 곧바로 다시 낸다. inbox는 상대마다 4 096 기록까지만 두고(필요할 때 늘림) 한도에 닿으면
  자리를 다시 내지 않는다(credit을 돌려주지 않음; TCP에서 받는 소켓 버퍼가 찰 때와 같음) `[설계 v2 2.2절]`. 지금 상대 소켓 하나를 읽는 자리(`gdakiTsPump`, 7곳)는 그
  상대의 inbox를 읽고, 거기서 지금의 park(`gdakiHoldDefer`, 상대마다 256개, 60 s; 5501–5510, 12965)로 간다. 상대마다 도착 차례는 지금과 같다. RNR 카운터는 시행 앞뒤로 남긴다.

**기록 형식.** 본문은 `struct gdakiTsMsg` 1 872 B 바이트 그대로이고, 앞에 64 B 봉투(`magic` 'GRCE', 판, 종류 RECORD/XFER/XFER_DONE/LAUNCHER/PAIR, 보낸 rank, 쌍의
세대, 순번, 거꾸로 credit, 문맥 nonce, 보낸 프로세스의 화신, 본문 길이)를 붙인다. 이름 붙은 칸의 합은 56 B라 `rsv[16]`으로 64 B를 맞추고(설계 v2의 `rsv[8]`은 셈 오류),
공유 헤더와 launcher 헤더가 크기와 칸마다의 위치를 `static_assert`로 같게 단언한다 `[설계 v3 2.3절; 측정: 셈]`. 지금 종류 1–19, 32–38, 48–51은 그대로이고 비어 있는 52–63 가운데 넷만 새로
쓴다: 52 STALLED(멈춤 판정 방송), 53 DISPUTE(판정이 엇갈림), 54 FENCED(launcher가 보낸 것을 helper가 hold 기계에 넣음), 55 PROBE_SETUP(1단계의 이름 붙인 개발 발판에서만:
생존 READ QP 끝점을 helper TCP 소켓으로 나눔, 2단계가 합쳐지면 55번과 함께 사라짐; 9.8절). 모두 복원 기록 범위(11–63) 안이라 지금의 park 규칙을 따른다 `[소스: 5494]`. launcher와의 말은 기록이 아니라 고정
256 B 구조(머리 64 B + 본문 192 B, 봉투와 합쳐 320 B, 종류 열일곱)이고, 그 안의 ACTIVATE는 지금 `gdakiRsActivate` 64 B를 바이트 그대로 싣는다. 이 배치는 2026-10-17에 빌드된 launcher의
헤더 `impl/launcher/launcher_msg.h`가 고정하고 설계 v3와 이 문서는 그것을 따른다(md5는 처음 빌드 때 `30a05c7f`, 준비 단계 리뷰 고침 뒤 `897641f3`: CONNECTED 종류 6을 rank 사이 전용으로
적음) `[측정: 헤더의 static_assert를 읽음; md5는 2026-10-17 다시 봄]`.

**큰 자료(outbox).** rank마다 2 × 1 MiB 호스트 영역(반 둘, REMOTE_READ만). 주는 쪽이 반 하나를 채우고 XFER(자리, 길이, rkey, 전송 번호, 끝 표시)를 보내면 받는 쪽이
기록 QP로 READ하고 XFER_DONE을 돌려준다. 쓰는 곳은 셋뿐이다: STATE(로그 내보내기, 한도 1 GiB, 시험 셀에서는 KiB 단위), rkey 목록(≤ 64 KiB), 활성화 덩어리 `[설계 v2 2.3절]`.
mirror 끈 길의 체크포인트와 FETCH는 outbox로 가지 않고 있는 RDMA 저장소 길 하나로 간다(사용자 결정 7; 처음 설계 초안은 두 길을 함께 적었고 리뷰와 설계 v2가 저장소
길 하나로 정함). rdma 빌드에서는 mirror 끈 프로세스도 mirror 켬의 저장소 길을 그대로 쓴다: 맡긴 rank가 입력 멈춤 안에서 고정 호스트 버퍼로 D2H 복사, 멈춤 밖에서
올리기 QP로 짝의 저장소에 늘 전체 이미지를 WRITE, 예비 프로세스는 활성화 뒤 FETCH QP로 READ. `gdakiStoreOn`(16742)을 복원이 켜진 모든 프로세스로 넓히고, 지금의 TCP
증분 길(15073–15335, 15478)은 tcp 빌드에만 남는다 `[설계 v2 2.8절; 소스]`. 반 1 MiB를 약 12 GB/s READ로 약 0.09 ms라 약 8 GB/s, 1 GbE 자료 소켓(약 110 MB/s)의 약 70배다
`[설계 v2, 추론]`. mirror 끔에서 생기는 메모리(약 3I + 5 MiB)는 9.7절 끝 결정 대기 2였고, 2026-10-16 밤 (가)로 닫혔다(한도는 BAR1의 것, 호스트 저장소는 쓴 양만 보고).

**차례와 잃음의 뜻**(사용자 결정 6: TCP 연결의 뜻과 같게 해서 hold, park, 라운드 코드를 바꾸지 않음).

| 지금(TCP) | RDMA 제어 | 근거 |
|---|---|---|
| 한 연결 안에서 차례대로, 빠짐과 겹침 없음 | 한 세대 안에서 RC가 차례대로. 받는 쪽은 순번 = 마지막 + 1을 확인하고 어긋나면 연결 잃음으로 침 | RC의 차례 규칙 `[추론]` |
| 연결을 잃으면 보내기 버퍼의 기록이 사라짐(STORE_ACK 꼬리가 잃은 CKPT_STABLE을 고침) | 기록 QP가 오류면 그 세대의 ACK 안 된 기록이 사라짐. 다시 짝 맺기가 세대를 올리고 받는 쪽은 옛 세대 봉투를 버림 | 15967–15971 |
| 다시 걸기(HELLO, HELLO_ACK, 세대) | UD 다시 짝 맺기, 그 종류의 세대 + 1. ERR를 본 쪽이 어느 쪽이든 시작하고, 기록 QP와 생존 READ QP는 따로 다시 맺음. 증인의 다시 걸기는 증인 노릇으로만 | 8551–, 8437; `[설계 v3 2.5절]` |
| 라운드 안(커밋 전)의 FIN이나 reset은 라운드 취소 | 라운드 안에서 판정 표가 그 상대를 "모름" 이상으로 바꾸거나(증인 FIN이나 RST의 확인 창, launcher 보고 가운데 먼저 온 것) 그 쌍의 기록 QP가 오류이거나 상대의 PAIR(기록, 세대 + 1)가 오면 라운드 취소, 상대는 "모름". 기록 QP 오류는 생존 판정의 입력이 아니다 `[설계 v3 2.4절]`. 죽은 상대의 기록 QP는 나가 있는 SEND가 있을 때만 약 3.66 s 뒤 오류가 되므로 그것만 기다리지 않음 | 11707; `[설계 v2 2.4절]` |
| BYE 뒤 FIN = 떠남 | 떠나는 rank는 노드 안 소켓으로 launcher에 "떠남"을 알리고, BYE를 링으로 보내 완료를 본 뒤, 증인에도 BYE를 보내고 닫음. 떠남은 링의 BYE나 launcher의 LEFT로 가름(증인을 꺼도 섬). 증인의 "BYE 뒤 FIN"은 보고만 | 8164–8212; `[설계 v2 2.4, 4.2절]` |
| 닫으면 보낸 바이트는 감 | FAIL을 보내고 닫는 자리, 거절한 상대에 답하고 끊는 자리, BYE는 SEND의 완료를(한도 안에서) 기다린 뒤 QP를 없앰(RC는 QP를 없애면 나가지 않은 WR이 사라짐) | `[설계 v2 2.4절]` |

**짝 맺기(UD).** datagram 하나 = 봉투 + 기록 1 872 B(또는 PAIR 구조)라 경로 MTU ≥ 2 048이 필요하다(사용자 결정 9). 짝 맺기는 QP 종류마다 따로 하고 세대도 따로다: 기록 QP
(REC)와 생존 READ QP(PRB). 기록 QP가 오류여도 생존 READ QP는 RTS 그대로라 다시 맺는 동안 생존 판정이 눈멀지 않는다 `[설계 v3 2.5절]`. PAIR 본문은 종류, 세대, 화신, nonce, 그
종류 QP의 끝점(새로 뽑은 PSN), 페이지와 outbox의 (주소, rkey, 길이), 보내는 쪽 UD 끝점과 Q_Key다(낡은 rkey도 다시 짝 맺기가 고치고, launcher가 다른 노드 rank에 답할 Q_Key를
여기서 얻음). 지금 PSN은 QP를 만들 때만 뽑으므로(16436–16440, 16516) `[소스]` RESET으로 다시 쓸 때마다 다시 뽑는다. 준비 때는 지금 연결 차례처럼 낮은 rank가 시작하고
(17946–18158), 다시 짝 맺기는 ERR를 본 쪽이 어느 쪽이든 PAIR(종류, g + 1)를 보낸다. 그 PAIR가 곧 상대에게 주는 알림이다: 로컬에서 오류가 된 RC QP의 상대 QP는 RTS 그대로라
쉬는 쌍이면 끝내 모르기 때문이다 `[설계 v3 2.5절; 추론]`. 엇갈리면 낮은 rank의 PAIR가 이긴다. 차례: (1) 시작 쪽이 그 종류의 QP를 INIT로 만들고(기록이면 RECV 64개를 내고)
PAIR를 상대 UD로, 답이 없으면 500 ms마다 다시; (2) 받는 쪽이 옛 QP를 오류 → RESET으로(또는 새 QP), 새 PSN, 기록이면 RECV 64개를 낸 뒤 RTR, RTS로 잇고 PAIR_ACK을 UD로,
같은 PAIR가 다시 오면 같은 답을 다시; (3) 시작 쪽이 RTR, RTS로 잇고, 기록이면 첫 RC 기록 CONNECTED를 보냄(받는 쪽은 그때까지 그 QP로 보내지 않음), 생존 READ면 PAIR_DONE을
UD로 보냄(받는 쪽은 그것을 받거나 500 ms 뒤 READ를 시작; 그 세대에 성공한 READ가 나오기 전의 생존 입력은 "확인 못함"). 받는 QP가 RTR 전이면 RC 패킷이 버려지고 floor 켬에서는 적응형 재전송 뒤 정규 간격이 536.9 ms까지라 이 차례가
필요하다 `[측정: 문서 ack_timeout; 설계 v2 2.5절; 추론]`. 한도는 준비 `NCCL_GIN_TS_CONNECT_MS`(15 000), 다시 짝 맺기 `NCCL_GIN_TS_RECONNECT_MS`(10 000)이고, PAIR의 화신은 지금의 재연결 펜싱 규칙(gin-mirror 9.9절
표의 마지막 행)으로 가른다. 같은 차례가 준비의 모든 쌍, 오류 뒤 다시 짝 맺기, rank와 launcher를 덮는다. 예비 프로세스의 REJOIN은 같은 끝점 꼴에 따로 된 종류와 멱등 표를 쓴다(9.5절). launcher 쪽은 짝 맺기마다 새 QP를 만들고(늘 새 PSN), 그 rank와의
기록 QP가 깨지면 launcher가 스스로 PAIR(기록, 세대 + 1)를 500 ms마다 10 000 ms까지 보낸다. 둘이 함께 시작하면 rank의 PAIR가 이긴다. PAIR 본문은 112 B(세대, UD Q_Key, 그 종류 QP 끝점
40 B, UD 끝점, 페이지 자리, 상대 말의 소비 수 낱말 자리 `creditOff`), PAIR_ACK은 72 B다 `[설계 v3 2.5절; 측정: launcher 헤더를 읽음]`.

### 9.2 상태 페이지

**배치.** rank마다 4 KiB 호스트 영역 하나(REMOTE_READ만). 판정에 쓰는 것은 정렬된 8 B 낱말뿐이고, 낱말 하나가 스스로 뜻을 갖는다 `[설계 v2 3.1절]`.

```
// 줄 0(64 B, 판정 낱말; 모두 8 B 정렬, 쓰는 쪽은 감시 스레드 하나, 낱말마다 8 B 저장)
uint64_t watchBeat;      // 감시 스레드가 1 ms마다 올림("프로세스가 돈다")
uint64_t helperBeat;     // helper 박동의 사본("helper가 돈다")
uint64_t helperBusy;     // (바쁨 번호 << 32) | 한도 ms, 0이면 바쁘지 않음(펌웨어 단계, 라운드)
uint64_t incNonce;       // (incarnation << 32) | nonce32
uint64_t flags;          // 떠나는 중(BYE 보냄), 복원 켬, mirror 켬, 페이지 판 번호
uint64_t appStep;        // 마지막 ncclGinRestoreStep의 단계(보고만)
uint64_t lastStableCkpt; // 마지막 확정 체크포인트(보고와 짝의 대조)
uint64_t rsv;
// 줄 1..: 상대마다 8 B 낱말
uint64_t rxConsumed[N];  // (gen << 32) | 그 상대의 몫 고리에서 다 쓴 수(credit, 9.1절)
uint64_t rxConsumedL[NL];// (gen << 32) | 그 launcher에서 받아 다 쓴 수(launcher 고리의 credit; 설계 v3)
uint64_t staleMs[N];     // 이 rank가 본 그 상대의 박동 정체 길이(분할 막이)
// 그 뒤 줄들: 여러 낱말이 한 뜻인 보고(줄마다 { uint64_t ver; 7 x uint64_t }, 줄 안 seqlock)
//   계보 보기(논리 rank마다 국면, cur, dead, hold 상태), hold 요약(상대마다 상태, 화신, fencedPlus1, FENCE 보냄)
```

rank 4, launcher 둘이면 판정 낱말이 줄 0과 80 B(줄 둘), 보고 줄 둘이라 주기 READ 하나가 320 B다 `[설계 v3 3.1절; 추론]`(설계 v2는 256 B). 줄 1의 차례(`rxConsumed`, `rxConsumedL`,
`staleMs`)는 준비 단계 헤더의 `gdakiCtrlPageLayoutOf`가 기준이고 설계 v3의 차례(`staleMs`가 둘째)와 다르다. 자리는 늘 그 함수에서 얻는다(준비 단계 리뷰 nit 15) `[소스: impl/rs_ctrl_api.h]`.

- 박동을 둘로 나눈다: `watchBeat`는 "프로세스가 돈다", `helperBeat`는 "helper가 돈다"다. `watchBeat`가 오르고 `helperBeat`만 멈췄고 바쁨 번호가 있으며 한도 안이면
  "helper 바쁨"이다. 읽는 쪽은 새 바쁨 번호를 처음 본 때부터 자기 시계로 한도를 잰다(쓰는 쪽의 시각을 견주지 않음). 단계 번호와 체크포인트는 보고에만 쓴다(라이브러리는
  application의 단계 간격을 모름).
- **일관성.** 판정은 정렬된 8 B 낱말만 쓴다. x86의 정렬된 8 B 저장은 원자적이고 PCIe completion은 RCB 경계(64 또는 128 B)에서만 쪼개지므로 정렬된 8 B 하나는 READ 안에서
  한 순간의 값이다 `[설계 v2 3.2절; 추론]`. 그래서 판정은 줄 원자성에 기대지 않는다. 줄 안 seqlock(`ver`를 홀수로(release) → 본문 → 짝수로(release))은 여러 낱말이 한 뜻인
  보고 줄에만 쓴다. NIC이 64 B 줄 하나를 한 READ에서 한 순간의 모습으로 읽는지는 규격이 주지 않고 NVIDIA 문서에서도 찾지 못했다 `[미확인]`. 그래서 망치 시험(9.8절 실행
  가능성 확인 1)을 남기고, 찢긴 보고 줄은 버리고 센다(`page_torn_n`). 홀수인 보고 줄은 다음 pass로 미루고, 확인 창의 READ는 판정 낱말만 보므로 찢김을 기다리지 않는다.
  `incNonce`가 기대와 다르면 그 상대의 페이지 자리가 바뀐 것(되살린 프로세스)이다. 새 rkey는 REJOIN과 REJOIN_ACK이 싣고(9.5절), 그 전에는 그 상대를 READ하지 않는다.
- **쓰는 쪽.** 감시 스레드 하나(쓰는 쪽이 하나여야 함). helper와 다른 스레드는 원자 변수에 값을 두고 감시 스레드가 1 ms마다 옮겨 쓴다. 쓰는 것은 호스트 메모리뿐이다
  (장치, PCIe 쓰기, 펌웨어 명령 없음).
- **읽는 쪽.** 감시 스레드가 gated이고 거절 안 된 상대마다 100 ms마다 하나만 띄운다(페이지 전부). 증인 FIN이나 RST(링과 증인 어디에도 BYE 없음)를 helper가 알리면 확인 창을
  연다: 그 때 t_F에 줄 0의 READ1, t_F + W/2에 READ2, t_F + W에 판정(9.3절). 기록 QP 오류는 창을 열지 않는다(처음 초안의 5 ms 간격 둘은 리뷰가 버렸고, 설계 v2의 "W 뒤 READ"는
  둘째 재검토가 판정 시각과 READ2의 시한이 없다고 찾아 설계 v3가 이 꼴로 정함) `[설계 v3 4.2절]`. W는 20–50 ms 사이에서 pilot의 장애 없는 셀에서
  잰 `watchBeat` 간격 최대의 5배 이상으로, 20 ms 아래로는 두지 않고 정한다 `[설계 v2 4.3절]` `[초안]`. 간격 최대가 10 ms를 넘으면 W가 50 ms를 넘을 수 있고 그때 3절의
  kill 예측을 다시 고친다. credit이 0일 때만 helper가 `rxConsumed` 낱말을 READ한다. 무장 조건은 launcher의 예비 자리 낱말(REG_NOTE와 페이지)을 조건으로 쓴다(9.5절, 설계 v2는
  보고만이었음).
- **정체의 길이**는 같은 읽는 쪽의 성공한 두 READ 사이에서 잰다 `[설계 v2 3.4절]`. 상대마다 (마지막 값, 그 값을 처음 본 성공 READ의 자기 시각)을 두고, 같은 값이 이어지면
  지금 성공 READ의 시각 − 처음 본 시각이 정체다. 그 사이 성공 READ 둘의 간격이 2 × `PROBE_MS`를 넘은 적이 있으면(읽는 쪽 자신이 멈췄거나 READ가 실패함) 처음 본 시각을
  지금으로 되돌린다. 그래서 SIGSTOP 뒤 깨어난 읽는 쪽은 자기 멈춤을 상대의 정체로 보지 않는다. 분할 막이는 다른 생존 rank의 `staleMs`(많아야 2 × `PROBE_MS` 늦은 값)를
  `STALL_MS` − 2 × `PROBE_MS`(기본 9 800 ms)와 견준다. 그래야 멈춤 판정이 10 000–10 300 ms에 남는다 `[설계 v3 3.4절; 추론]`.
- **launcher 페이지**(설계 v3 3.6절, launcher 헤더의 `struct glPage` 그대로). launcher마다 4 KiB(REMOTE_READ만, 쓰는 쪽은 launcher 스레드 하나, 정렬된 8 B 낱말): 줄 0(박동 `beat`가
  적어도 10 ms마다 오름, `monoMs`, 노드, Q_Key), 등록 칸 62개(칸마다 32 B: nonce, 등록 낱말 = (상태 NONE, ALIVE, EXITED, LEFT, FENCED, rank, 화신), 예비 자리 낱말 = (상태 NONE,
  REPLAYING, READY, OFFERED, ACCEPTED, FAILED, ABORTED, rank, 예비 프로세스의 화신), `spareSinceMs`), credit 칸 64개(칸마다 32 B: nonce, (rank, 화신), 그 rank의 말을 다 쓴 수).
  rank는 그 launcher와의 생존 READ QP로 줄 0과 등록 칸(2 048 B)을 끌어 읽는다(9.3절의 때뿐). 같은 낱말은 REG_NOTE 말로도 온다. 판정에서 등록 낱말은 "launcher가 이 프로세스를 ALIVE로
  쥠"의 증거로만 쓰고 끝남은 EXITED, FENCED 말로만 읽는다 `[설계 v3 3.6, 4.2절]`.
- **계보 입력이 아니다.** 페이지는 판정과 보고의 입력이고, 계보 classify의 입력은 지금처럼 기록의 칸뿐이다(gin-mirror 9.9절의 oracle 시험이 그대로 선다).
- **비용** `[추론]`. READ 하나는 rank 4면 320 B, 상대마다 100 ms에 하나라 rank마다 초당 30번, 약 9.6 KB/s다 `[설계 v3 3.5절]`. 데이터 QP가 아니라 put의 WQE 차례와 겹치지 않지만
  같은 포트와 PCIe를 나누므로 비용 셀이 잰다. 제어 몫의 고정 메모리는 페이지 4 KiB, 링 640 KiB, UD RQ와 SQ, outbox 2 × 1 MiB로 rank마다 약 2.9 MiB이고, 보내는 쪽
  대기열과 inbox는 평소 0, 필요할 때 상대마다 많아야 약 7.6 MiB와 7.3 MiB다 `[설계 v2 3.5절]`. 2a-1 코드의 실제 몫은 이보다 많다고 1단계와 2a-1 코드 리뷰가 셈했다(보내기 영역 rank 4면
  512 KiB, `inStage` 1 MiB, MR 일곱과 1단계 페이지의 둘; 리뷰 nit 10) `[미확인: 이 문서에서 다시 세지 않음]`. 고친 코드로 다시 센 뒤 이 값을 고친다. 모두 호스트라 BAR1을 쓰지 않는다. mirror 끈 rank의 저장소 몫은 9.1절 큰 자료.
  gin-mirror의 4 KiB put 지연(off 팔) 11.26–12.29 µs `[측정: 문서 gin-mirror 2절]`에서 2 %는 0.23–0.25 µs이고, 이것은 그 실험의 pilot 사이 퍼짐(약 9 %)보다 작다.
  그래서 판정식의 2 %가 실행 사이 잡음 아래일 수 있다 `[추론]`. pilot에서 같은 팔 사이 퍼짐을 보고 사전 등록에서 정한다(9.9절 끝).
- **등록 차례.** 죽는 프로세스에서 MR이 QP보다 먼저 사라지면 READ는 원격 접근 오류(마지막 ACK 뒤 0.38–3.51 ms), QP가 먼저면 응답 없음(3.51–3.76 s)을 받는다
  `[측정: 문서 teardown_order]`. 페이지 MR은 준비 때 생존 READ QP보다 먼저 등록되므로 원격 접근 오류는 드물 것이다 `[추론]`. 판정은 원격 접근 오류에 기대지 않는다.

### 9.3 생존 판정 표

**신호마다의 시간.**

| 신호 | 언제 오나 | 근거 |
|---|---|---|
| 증인 FIN(BYE 없음) | SIGKILL 뒤 첫 오류 CQE보다 늘 먼저(270/270, 가장 작은 여유 0.43 ms), 지금 판정은 kill 뒤 약 0.1 ms | `[측정: 문서 teardown_order]` |
| 증인 "모름"(ETIMEDOUT) | 약 5 s(keepalive와 `TCP_USER_TIMEOUT`) | `[소스: 8122–8133]` |
| READ 응답 없음(재시도 초과) | floor 켬, retry 7에서 timeout과 상관없이 약 3.66 s; 죽은 상대 QP가 먼저 사라질 때 3.51–3.76 s | `[측정: 문서 ack_timeout, teardown_order]` |
| READ 원격 접근 오류 | 페이지 MR이 QP보다 먼저 사라질 때, 0.38–3.51 ms. 살아 있는 상대가 MR을 풀어도 같은 코드(90/90) | `[측정: 문서 teardown_order]` |
| READ 시한(띄운 READ가 500 ms 넘게 안 끝남) | 500 ms. 살아 있는 상대(멈춘 상대 포함)는 NIC이 답하므로 수 µs | `[측정: 문서 live_peer, 멈춘 상대의 쓰기 3.7–8.2 µs 완료; 추론]` |
| launcher 종료 보고(pidfd) | 스레드 그룹이 끝날 때. 원래 프로세스가 `/proc`에서 사라지기까지는 4 KiB 105.3–146.6 ms(n 44), 학습 모양 168.0–210.4 ms(n 10)(관문 기다림 `activate_ms`); 설계 v2가 쓰는 정리 시간('later' 기다림)은 4 KiB 102.0–143.1 ms, 학습 164–206 ms | `[측정: gin-mirror 본 실행 activate_ms를 다시 셈]`; `[설계 v2 4.1절, 측정: 문서 동적 예비 프로세스 리뷰]`; pidfd 때와 같은지는 `[미확인]` |
| launcher LEFT | 떠남을 알린 프로세스가 끝날 때 | 9.5절 |
| 박동 정체 | 페이지 쓰기 1 ms, READ 100 ms마다 | 9.2절 |

**판정 표**(설계 v3 4.2절; 두 문서의 행이 같음: 21행). 설계 v2의 표(18행)와 이 문서의 v2 판(20행)은 입력 조합을 빠짐없이, 한 번씩 덮지 않았고 두 문서의 행 수도 달랐다
(둘째 재검토의 막는 문제 2). 설계 v3는 입력마다 값 목록을 고정하고 위에서부터 첫 일치가 이기는 목록으로 쓴다. 상대 p와 그 지금 화신 i(계보 보기의 cur, HOLD_WAIT이면 dead)마다
감시 스레드와 helper가 같은 순수 함수를 부른다. 기록 QP의 상태는 생존 입력이 아니다: 기록 QP 오류는 그 쌍의 기록 길 다시 짝 맺기와 라운드 취소만 부른다(9.1절).

입력과 값 `[설계 v3 4.2절]`:
- **L(launcher)**, 다섯 값. 떠남: LEFT(p, i) 말이나 등록 낱말 (LEFT, p, i). 끝남: EXITED(p, i)나 FENCED(p, i) 말(말은 (rank, 화신, nonce)를 싣고 계보 분류가 CURRENT나 HELD_OLD일 때만
  씀). 살아 있음: 마지막 끌어 읽기가 성공했고 등록 낱말이 (ALIVE, p, i). 정보 없음: 끌어 읽기는 성공했으나 낱말이 (ALIVE, p, i)도 (LEFT, p, i)도 아님(NONE, EXITED, FENCED, 다른 화신,
  칸 없음; 낱말과 REG_NOTE의 EXITED는 끝남으로 치지 않음, 9.2절). 무응답: 끌어 읽기가 하드웨어 응답 없음이나 시한으로 끝남, 그 launcher와의 QP가 오류, 짝 맺기 없음, 또는 launcher
  박동이 `LAUNCHER_STALL_MS` 넘게 그대로. "그 프로세스 있음"을 읽는 곳은 이 끌어 읽기의 등록 낱말이다(설계 v2의 열에는 읽을 곳이 없었음).
- **B(BYE)**: 이 세대에서 p의 링 BYE, 증인 BYE, 또는 페이지 `flags`의 "떠나는 중"을 봄 / 없음.
- **W(증인과 확인 창)**, 아홉 값: 정상; 모름(ETIMEDOUT, 도달 불가, 다시 거는 중, 그리고 창이 끝나 다 쓴 FIN이나 RST); 꺼짐; 창 진행 중; 창 끝 다섯(살아 있음, STALE, NORESP,
  REMACC, 확인 못함). B가 있을 때의 FIN은 창을 열지 않고 보고만 한다.
- **R(생존 READ)**, 열세 값: (1) 늚, (2) 정체 < `SUSPECT_MS`, (3) 정체 `SUSPECT_MS`–`STALL_MS`, (4) 정체 ≥ `STALL_MS`이나 분할 막이나 데이터 경로 거부권이 막음, (5) 멈춤(정체 ≥
  `STALL_MS` + 분할 막이 + 거부권), (6) helper 바쁨(`watchBeat` 늚, `helperBeat` 정체, 바쁨 번호가 있고 자기 시계로 한도 안), (7) helper 정체 `SUSPECT_MS`–`STALL_MS`(바쁨 없음 또는 한도
  지남), (8) helper 정체 ≥ `STALL_MS`이나 막이가 막음, (9) helper 멈춤(helper 정체 ≥ `STALL_MS` + 분할 막이), (10) 원격 접근 오류, (11) 하드웨어 응답 없음(재시도 초과 CQE),
  (12) 시한만(`PROBE_TIMEOUT_MS` 지남, CQE 없음), (13) 확인 못함(이 세대에 RTS로 성공한 READ가 없음, 넘기기 중, `PROBE_MS=0`). 확인 창의 READ는 R에 들지 않는다.

목록(차례가 우선순위, 빈칸은 "앞 행에 걸리지 않은 아무것"; 설계 v3 4.2절의 표를 그대로 옮기고 절 번호만 이 문서의 것으로 바꿈):

| 차례 | L | B | W | R | 판정 | 반응 | 원인 이름 |
|---|---|---|---|---|---|---|---|
| 1 | 떠남 | | | | 떠남 | hold로 가지 않음(리뷰 B4) | – |
| 2 | | 있음 | | | 떠남 | 지금의 BYE 처리. 그 뒤의 끝남도 떠남으로 침 | – |
| 3 | 끝남 | | | | 끝남, 펜스 끝 | hold 또는 거절(무장이면 hold). `fencedPlus1[p] = i + 1`(9.4절) | EXITED |
| 4 | | | 창 끝 STALE | | 끝남 | hold 또는 거절 | FIN+STALE |
| 5 | | | 창 끝 NORESP | | 끝남 | hold 또는 거절 | FIN+NORESP |
| 6 | | | 창 끝 REMACC | | 끝남 | hold 또는 거절 | REMACC+FIN |
| 7 | | | 창 진행 중 | | 기다림 | t_F + W까지 아래 행을 보지 않음 | – |
| 8 | | | 창 끝 살아 있음 | | 살아 있음, 증인 잃음 | 증인을 다시 걸고 줄 하나. W는 모름이 됨. tcp 빌드에서는 이 경우가 곧 죽음 | – |
| 9 | | | 창 끝 확인 못함 | | 판정 없음 | 줄 하나. W는 모름이 됨. launcher 보고나 하드웨어 응답 없음을 기다림 | – |
| 10 | 무응답 | | | 하드웨어 응답 없음 | 노드 또는 선 닿지 않음 | 죽음으로 거절, 복원 없음(예비 프로세스가 같은 노드) | LINKDOWN |
| 11 | 정보 없음 | | 꺼짐 | 하드웨어 응답 없음 | 끝남(펜스가 확인) | hold 또는 거절. 활성화는 FENCED 뒤(9.4절) | NORESP |
| 12 | | | | 하드웨어 응답 없음 | 그 프로세스의 RDMA 길만 깨짐 | 생존 READ QP 다시 짝 맺기를 `PROBE_FAIL_N`(3)번까지(시도마다 약 3.66 s라 약 11 s 이상), 그다음 "모름" 거절(강한 증거 아님) | – |
| 13 | | | | 확인 못함 | 판정 없음 | 기다림(다시 짝 맺기 한도 안), 줄 하나 | – |
| 14 | | | | 멈춤 | 소프트웨어 멈춤 | STALLED 방송. 무장됐고 `NCCL_GIN_RESTORE_FENCE=lineage`이며 launcher와 짝을 맺었으면 펜스 뒤 복원(9.4절), 아니면 거절 | STALL |
| 15 | | | | helper 멈춤 | 소프트웨어 멈춤(helper) | 14행과 같음. helper가 멈춘 rank는 라운드와 기록을 처리하지 못한다. 펜스로 둘지 거절만 할지는 사용자 결정 목록(9.7절 끝 v3 목록 1) | STALL_HELPER |
| 16 | | | | 원격 접근 오류 | 판정 없음 | 생존 READ QP 다시 짝 맺기. 같은 상대가 `PROBE_FAIL_N`번 이어 실패하면 "모름" 거절(강한 증거 아님). 페이지 rkey가 낡았을 수 있음(9.2절) | – |
| 17 | | | | 시한만 | 판정 없음 | 줄 하나. p 노드의 launcher 페이지를 곧바로 끌어 읽음(그 결과가 다음 부름의 L) | – |
| 18 | | | | (3), (4), (7), (8) | 의심 | 줄 하나. 정체는 바쁨이 없을 때, 또는 한도가 끝난 때부터 셈 | – |
| 19 | | | | helper 바쁨 | helper 바쁨 | 없음 | – |
| 20 | | | | 늚, 정체 < `SUSPECT_MS` | 살아 있음 | 없음. 증인이 모름이면 증인만 다시 건다(8 s 관리망 끊김이 여기) | – |
| 21 | | | | | 판정 없음 | 닿지 않음(1단계 격자 1 170점에서 0점; 리뷰가 적은 행마다의 점 수: 1행 234, 2행 468, 3행 117, 4–9행 39씩, 10행 3, 11행 1, 12행 5, 13–17행 9씩, 18행 36, 19행 9, 20행 18). 표를 빠짐없이 적으려고 남김. 코드는 이 자리에 "닿지 않음" 주석을 둠 | – |

- **빠짐과 겹침이 없음** `[설계 v3 4.2절; 추론]`. 1–9행을 지나면 L은 살아 있음, 정보 없음, 무응답, B는 없음, W는 정상, 모름, 꺼짐이다. 하드웨어 응답 없음은 10–12행이 L과 W의 모든 경우를
  덮고(무응답 → 10, 정보 없음 + 꺼짐 → 11, 나머지 → 12), R의 다른 열두 값은 13–20행이 하나씩 받아 21행에는 닿는 입력이 없다. 1단계 CPU 모형이 입력 격자 1 170점(5 × 2 × 9 × 13)에서
  21행에 닿는 점 0, 1–20행이 모두 한 점 이상, floor 성질(거절이나 hold를 내는 점은 모두 launcher 끝남, 창 확인됨, 하드웨어 응답 없음, 멈춤 가운데 하나를 가짐)을 단언한다(9.8절).
  통합 트리의 단위 시험(`gc_unit_p1`, 판정 함수는 헤더의 `gdakiCtrlJudge`)이 그 셋을 통과했다 `[측정: 통합 에이전트의 보고 impl/notes_int.md, unit_int.log; 이 문서에서 다시 돌리지 않음]`.
  다만 1단계와 2a-1 코드 리뷰는 그 시험의 "독립 참조"가 같은 if 사슬의 사본이라 독립이 아니라고 보았고, 21행 칸에 적은 행마다의 점 수를 단언하라고 권했다(고칠 것 6). 그 점 수는
  이 문서가 값 목록(L 5, B 2, W 9, R 13)에서 다시 셌고 리뷰의 수와 같다(합 1 170) `[측정: 셈]`. 그 단언을 넣는 것은 고침 몫이다.
- **R 값을 고르는 차례** `[미확인]`. R은 값 열셋 가운데 하나지만 실제 입력은 박동 둘(`watchBeat`, `helperBeat`)과 마지막 READ의 결과다. 둘 다 정체이거나 READ 오류와 앞선 정체가
  겹칠 때 어느 R을 고르는지 설계 v3 4.2절에 없다(1단계와 2a-1 코드 리뷰 고칠 것 1). 고침이 차례(마지막 READ가 오류면 (10)–(12), `watchBeat`가 정체면 (2)–(5), 늚이면 helper 쪽
  (6)–(9) 같은 꼴)를 정해 순수 함수로 시험하고 이 절에 적는다. 오류 CQE 가운데 (11)이 되는 것은 재시도 초과뿐이다(같은 리뷰 막는 문제 5; floor 규칙).
- **확인 창**(둘째 재검토의 막는 문제 3) `[설계 v3 4.2절]`. 여는 것은 B가 없을 때의 증인 FIN이나 RST뿐이다(기록 QP 오류, 시한, 원격 접근 오류는 열지 않음; 설계 v2는 기록 QP 오류로도
  열었고 그 "확인됨"을 받는 행이 없었으며 판정에 쓰면 floor 규칙을 어겼다). t_F에 생존 READ QP가 이 세대에 RTS로 성공한 READ가 없으면 곧바로 "확인 못함"이고, 아니면 READ1(줄 0)을 낸다.
  t_F + W/2에 READ2, t_F + W에 판정한다: 원격 접근 오류가 하나라도 있으면 REMACC; 아니면 어느 하나라도 끝나지 않았으면 NORESP; 아니면 `incNonce`가 기대와 다르면 확인 못함; 아니면
  READ2의 `watchBeat`가 READ1보다 크면 살아 있음, 같으면 STALE. 판정은 늘 t_F + W(+ 감시 스레드 한 걸음)이고, 설계 v2의 "원격 접근 오류면 더 이름"은 버렸다. 판정 뒤에 끝나는 창의 READ
  완료는 버린다. 거짓 STALE의 여유는 W/2 ≥ 2.5 × 장애 없는 `watchBeat` 간격 최대다(결정 (가)의 W ≥ 5배에서); 넓힐지는 9.7절 끝 v3 목록 5.
- **11행이 안전한 까닭** `[설계 v3 4.2절; 추론]`. 운영에서는 launcher의 끝남 말(102–206 ms)이 하드웨어 응답 없음(3.5–3.8 s)보다 훨씬 먼저 오므로 이 행은 그 말을 잃었거나 시험
  스위치 `NO_EXIT_REPORT`가 그것을 끈 때만 생긴다. 판정이 틀려 살아 있는 프로세스를 끝남으로 보아도 짝의 FENCE가 그 프로세스를 끝내고 FENCED 뒤에만 활성화하므로 데이터가 섞이지 않는다.
  증인이 켜져 있으면(정상, 모름) 12행으로 가서 hold하지 않는다. 이 행을 둘지는 9.7절 끝 v3 목록 2다.
- **EXITED와 박동 늚**(둘째 재검토가 DISPUTE를 제안). 3행이 이긴다. 다른 QP의 READ 완료와 launcher 말 사이에는 차례가 없어 "함께"를 정할 수 없고, 남의 pidfd(필수 pid 검사)와 옛 화신의
  EXITED(계보 분류)는 다른 규칙이 막는다 `[설계 v3 4.2절]`. 리뷰와 다르게 정한 것이라 9.7절 끝 v3 목록 7에 올렸다.
- 17행이 "제어 길이 데이터 길보다 먼저 죽지 않게"의 규칙이다(사용자 결정 (가), 2026-10-16 밤): READ 시한 500 ms만으로는 아무것도 하지 않고, 시한이 판정에 드는 것은 FIN이나 RST와 겹친
  확인 창 안뿐이며(5행), 노드와 선 판정(10행)과 11행은 하드웨어 재시도 초과(데이터 QP와 같은 3.5–3.8 s)를 요구한다.
- 원격 접근 오류 하나는 판정이 아니다(16행). 살아 있는 상대도 같은 코드를 내고(90/90), 되살린 프로세스의 새 rkey를 모르는 생존 rank가 옛 rkey로 읽는 자리가 있을 수 있다. REJOIN,
  REJOIN_ACK, PAIR, PAIR_ACK이 새 rkey를 실어 그 자리를 막지만(9.1, 9.5절) 판정은 그것에 기대지 않는다. launcher 끝남과 겹치면 3행이 이기고 원인은 EXITED다(설계 v2의 REMACC+EXITED는
  줄의 `remacc=1` 칸으로만 남음).
- **증인 자신의 고장.** 한 방향 끊김에서는 먼저 시간이 다 된 쪽 커널이 살아 있는 연결을 RST로 끊는다. RST는 확인 창을 부를 뿐이고 박동이 늘면 8행이다. 증인의 다시 걸기와 확인
  접속의 "거절 둘"(8361–8388), 다시 걸기 한도는 W = 모름으로만 남고 거절이 되지 않는다. 증인의 기본값은 켬이다 `[설계 v2 4.2, 4.3절]`.
- 노드 죽음과 선 끊김은 RNIC 쪽에서 가를 수 없다(launcher와 rank가 같은 선을 씀). 10행에서 증인이 정상이면 원인 줄은 "line", 모름이나 꺼짐이면 "node or line"이다. 결과(복원 안 함)는
  같다 `[추론]`.
- hold의 강한 증거 원인 이름은 rdma 빌드에서 일곱이다: EXITED(3행), FIN+STALE(4행), FIN+NORESP(5행), REMACC+FIN(6행), NORESP(11행), STALL(14행), STALL_HELPER(15행) `[설계 v3 4.5절]`.
  거절 원인 LINKDOWN(10행)은 hold가 아니다. "REMACC" 하나, 시한 하나, "ECONNREFUSED"는 강한 증거가 아니고, "ECONNREFUSED"는 증인의 다시 걸기에만 남는다.
- **tcp 빌드**(사용자 결정 1, 설계 v2 2.0절). 컴파일 때의 매크로 `NCCL_GIN_CTRL_TCP=1`로 빌드하고 실행 시 env로 고르지 않는다(처음 초안의 "같은 바이너리 A/B"는 없앰).
  새 코드는 모두 `#if !NCCL_GIN_CTRL_TCP` 안에 두고 아무것도 지우지 않는다. tcp 빌드는 옛 동작 전체(TCP 기록과 자료 소켓, TCP 활성화, FIN = 죽음, 거절 둘과 1 000 ms,
  `/proc` 관문, `gdakiHoldStrongCause`의 "FIN"과 "ECONNREFUSED", launcher, 상태 페이지, UD 없음)를 되살리는 회귀 팔이다. 목표는 tcp 빌드의 호스트 파일 전처리 결과가 ln4
  (md5 `0ab4e636`)의 것과 줄 표시를 빼고 같은 것이고, 그렇게 되지 않는 자리는 목록으로 적는다 `[설계 v2 2.0절; 추론: 모든 바뀜이 매크로 안일 때만 섬]`. tcp 빌드가
  되살리는 것은 ln4(gin-mirror 본 실행 빌드)의 동작이고, gin-restore의 결과는 그 실험의 i5 빌드와 release `data-20261013`만이 재현한다. RST 뒤 거절 간격(감지 설계의
  100 ms 제안)은 rdma 빌드에서 필요 없고(RST가 확인 창을 부름) tcp 쪽에만 매개변수로 닿는다. 그 매개변수와 tcp 대조 셀이 쓰는 시험 스위치(`DIE_RST`, `RST_GAP`, `FD_HOLDER`의 helper
  소켓 갈래)는 ln4에 없으므로(호스트 파일에서 0건 `[소스: grep]`) 둘째 매크로 `NCCL_GIN_CTRL_TCP_CELLS=1` 뒤에 둔다. 그래서 `gct`(첫 매크로만)는 ln4와 전처리가 같아야 하는 회귀 팔로
  남고, 두 매크로를 다 켠 `gctc`는 tcp 대조 셀만 돈다 `[설계 v3 2.0절]`. 그래서 `gctc`의 전처리 결과는 ln4와 그 매개변수만큼 다른 것이 뜻한 바다(통합 트리에서 2 hunk 3줄, 9.8절). 간격의 기본은 1 000(옛 동작)이고 RST 셀만 100이다(2026-10-16 밤 사용자 결정).

**문턱.**

| 이름 | 기본 | 뜻 | 8 s 관리망 끊김과의 관계 |
|---|---|---|---|
| `NCCL_GIN_TS_PROBE_MS` | 100 | READ 주기(0이면 주기 READ, credit의 페이지 낱말 길, 확인 창이 모두 꺼짐; 비용 셀만) `[설계 v3 4.3절]` | 무관 |
| `NCCL_GIN_CTRL_PROBE_TIMEOUT_MS` | 500 | 띄운 READ의 시한(의심과 보고만, FIN과 겹치면 강한 증거) | 무관 |
| `NCCL_GIN_CTRL_CONFIRM_MS`(W) | 20–50 `[초안]`(처음 초안의 5에서 바꿈), pilot로 고정 | FIN이나 RST 뒤 확인 창: t_F에 READ1, t_F + W/2에 READ2, t_F + W에 판정; 박동이 그대로이거나 t_F + W까지 READ가 끝나지 않으면 FIN과 겹쳐 강한 증거 `[설계 v3 4.2절]`. 1단계 pilot의 장애 없는 `watchBeat` 간격 최대의 5배 이상, 20 ms 아래로는 두지 않음 `[설계 v2 4.3절]`. 살아 있는 rank도 FIN을 낼 수 있어 감시 스레드가 W 넘게 스케줄되지 않으면 거짓 죽음이므로 이 여유를 둔다. FIN이 있을 때만 쓰는 짧은 시한이고, floor 규칙과 함께 2026-10-16 밤 사용자 결정 (가)로 정함. 감시 스레드의 QP 감시를 끈 장애 없는 셀에서 잼(6절 통제변수) | 무관(증인이 FIN을 낼 때만) |
| `NCCL_GIN_CTRL_WITNESS` | 1(켬) | 관리망 증인 소켓 | 8 s 끊김에서 증인만 모름 → 첫 행(살아 있음). 증인이 모름이 되는 때는 약 5 s |
| `NCCL_GIN_TS_SUSPECT_MS` | 2 000 | 의심(체크포인트 멈춤 시한과 같음, 14168) | 의심 줄만 |
| `NCCL_GIN_TS_STALL_MS` | 10 000 | 소프트웨어 멈춤. 투명해야 하는 8 s 정지와 8 s 끊김보다 길고 hold 시한 20 s의 절반 | 판정 없음 |
| `NCCL_GIN_TS_STALL_RMSN_MS` | 1 000 | 데이터 경로 거부권의 창(GPU가 아직 보내는 상대는 판정하지 않음) | 무관 |
| `NCCL_GIN_TS_PROBE_FAIL_N` | 3 | 증인 정상 + READ 응답 없음의 다시 짝 맺기 횟수 | 무관 |
| `NCCL_GIN_TS_RST_REFUSAL_GAP_MS` | 1 000(2026-10-16 밤 사용자 결정; RST 셀만 100) | tcp 대조 빌드(`gctc`)에만: RST 뒤 1 000 ms 안의 거절 간격(1 000이면 옛 동작) | 무관 |
| LATER 뒤 짝의 한도 `NCCL_GIN_CTRL_LATER_MS` | 1 000(2026-10-17 사용자 결정 4; 준비 단계 헤더의 초안 5 000은 통합 때 1 000으로 고침) | 짝이 LATER를 받은 뒤 스스로 셈. 넘으면 ABORT를 보내고 fallback(이 실험의 launcher는 LATER 뒤 자기 한도가 없음) `[설계 v3 4.3, 5.4절]` | 무관 |
| `NCCL_GIN_CTRL_LAUNCHER_STALL_MS` | 1 000(2026-10-17 사용자 결정 4) | launcher 페이지 박동(적어도 10 ms마다 오름)의 정체 한도. 넘거나 launcher QP 오류면 launcher 잃음 `[설계 v3 4.3절]` | 무관 |
| `NCCL_GIN_RESTORE_FENCE` | `lineage` | `lineage`: 멈춤 판정 뒤 펜스와 복원. `none`: 거절만 | 무관 |

범위 검사(준비 합의, 모든 rank가 같은 값): `10 × PROBE_MS ≤ SUSPECT_MS < STALL_MS`, `STALL_MS + 1 000 ≤ NCCL_GIN_RESTORE_MS`, `PROBE_TIMEOUT_MS ≥ 5 × PROBE_MS`,
`20 ≤ CONFIRM_MS < PROBE_TIMEOUT_MS`, `SPARE_START_MS + 1 000 ≤ NCCL_GIN_RESTORE_MS` `[설계 v2 4.3절]`, `PROBE_MS ≤ LAUNCHER_STALL_MS`, `LATER_MS + 1 000 ≤ NCCL_GIN_RESTORE_MS`
(`PROBE_MS=0`이면 W 검사는 하지 않음) `[설계 v3 4.3절]`. 장애 없는 단계 간격의 최대는 41.74 ms였다는 계산이 감지 설계에 있다(10 000 ms는 그 240배) `[미확인: 이 문서에서 다시 세지 않음]`.
`PROBE_TIMEOUT_MS` 500의 근거는 부하에서 가장 긴 호스트 RC 전송(30 MiB WRITE p99 24.1 ms)이고, 256 B READ의 부하 꼬리는 재지 않았다 `[미확인]`. pilot의 READ
지연 최대로 고정한다.

**판정 시각의 어림** `[추론]`.
- SIGKILL(FIN 있음): 지금의 FIN 판정은 kill 뒤 0.07–0.31 ms `[설계 v2 4.1절, 측정: 문서 gin-restore pilot]`. 처음 초안은 확인 READ 둘(5 ms 간격)로 약 5–6 ms를 어림했으나, 리뷰가 그 어림이 측정된
  정리 차례와 맞지 않음을 찾았다: fd는 번호가 큰 것부터 풀리고(275/275), 첫 오류 CQE는 FIN 뒤 0.43 ms부터 오며, MR을 먼저 등록하면 QP가 먼저 사라진다 `[측정: 문서
  teardown_order]`. 그래서 t_F의 READ1은 아직 있는 QP에서 끝나 멈춘 박동을 읽고, t_F + W/2의 READ2는 대개 사라진 QP에 닿아 끝나지 않는다. 설계 v3는 판정을 늘 t_F + W로 두므로
  증인 FIN → 판정 W–W + 1 ms, kill → 판정 약 20–51 ms(W 20–50)이고 원인은 FIN+NORESP가 많을 것이다 `[설계 v3 4.2, 4.6절; 추론]`. 창이 "확인 못함"이면 launcher 보고(102–206 ms)다. 3절의 kill
  예측이 이 값이고, W 값만 pilot이 정한다 `[초안]`. 원인마다의 수는 보고한다.
- RST: 같은 확인 창이라 RST에서 판정까지 FIN과 같은 크기(RST + W)다. tcp 빌드는 RST 뒤 첫 거절(1.1–1.3 ms 뒤 `[측정: 문서 감지 설계의 다시 셈]`) + 100 ms라
  100.5–106 ms다(간격 100을 둔 셀만).
- FIN 없는 죽음, 보고 있음: 원래 프로세스의 스레드 그룹이 끝날 때(4 KiB 102.0–143.1 ms `[설계 v2 4.1절]`). EXITED 말이 꺼짐(증인도 끔): 정리 중 QP가 사라진 뒤 첫 READ가 시한(500 ms,
  17행; 끌어 읽은 launcher 낱말은 ALIVE가 아니라 "정보 없음")을 지나 하드웨어 재시도 초과까지 3.51–3.76 s, 그 앞에 정리(약 0.15 s)와 READ 주기(≤ 0.1 s)가 더해져 kill 뒤 약 3.6–4.0 s,
  여유를 두어 3.5–4.5 s에 11행(NORESP)으로 판정되고, FENCE는 곧바로 FENCED를 받는다 `[설계 v3 4.6절; 추론]`.
- 판정 줄에서 잰 복원 시간은 3절의 메모: kill에서 복원 끝까지는 지금과 ± 20 ms 안이고, 판정 줄 기준으로는 약 W 짧다 `[설계 v2 4.6절; 추론]`.
- 멈춘 상대: STOP 뒤 박동이 멈추고 10 000 ms + 판정 pass(≤ 2 × 100 ms)라 10 000–10 300 ms(분할 막이가 다른 rank의 늦은 `staleMs`를 `STALL_MS` − 2 × `PROBE_MS`와 견주므로 늘지 않음 `[설계 v3 3.4절]`). helper만 멈춘 rank도 같은 셈이다. 생존 rank들이 같은 상대의 페이지를 같은 주기로 읽으므로 판정 시각이 2 × 100 ms
  안에 모인다.

### 9.4 펜스: 계보의 국면(HOLD_WAIT 안의 보고 이름)

**왜.** 멈춘 상대는 살아 있고 그 QP는 RTS다. 복원은 생존 rank의 같은 QPN을 예비 프로세스에 다시 잇고(3068–3069), RC 요청에는 보낸 QP 번호가 없어 옛 프로세스의
쓰기를 가리는 것은 PSN뿐이다 `[추론]`. 깨어난 옛 화신의 중복 WRITE를 응답 쪽이 다시 쓰는지는 `[미확인]`이다. 그래서 복원 전에 옛 화신을 끝내고 그것을 확인한다
(사용자 결정, 저녁: 깃발은 하드웨어 쓰기를 막지 못하므로 QP 끊기와 종료 확인이 실행 내용이다).

**차례.**
1. **QP를 오류 상태로.** 멈춤을 판정한 생존 rank가 hold를 시작하면 시작 정지가 p로 가는 사용자 QP와 mirror QP를 2ERR로 바꾼다(13193 영역, 지금 그대로). 같은 자리에서
   p와의 기록 QP, 생존 READ QP(감시 스레드에 넘김, 9.1절), 짝이면 p가 맡긴 저장소 응답 쪽 QP도 오류 상태로 바꾼다. 저장소 응답 쪽 QP가 지금 hold 시작에 오류로 가는지는
   `[미확인]`이고 펜스의 불변식에 넣는다 `[설계 v2 4.4절]`. 그때부터 옛 프로세스가 깨어나도 생존 rank에 기록이나 READ 응답이 닿지 않는다.
2. **모두 보고.** 생존 rank마다 HOLDING(p, i)를 링으로 짝에게 보낸다(지금 그대로). 시작 정지가 HOLDING보다 먼저이므로 "모든 HOLDING이 모임"은 "모든 생존 rank의 p로 가는
   QP가 오류 상태"를 뜻한다.
3. **종료 요청.** 짝은 모든 HOLDING이 모였고 펜스 낱말이 아직 그 화신을 가리키지 않으면 **늘** p 노드의 launcher에 FENCE(p, i, nonce)를 보낸다(kill에서 EXITED가 먼저 왔으면
   보내지 않음) `[설계 v3 4.4절]`. launcher는 등록 때 받은 (p, i)의 pidfd에만 `pidfd_send_signal(SIGKILL)`(멈춘 프로세스도 받음)을 보내 종료한 뒤, pidfd가 읽기 가능해질 때(스레드 그룹이
   끝남) FENCED(p, i, nonce)를 모든 rank의 launcher QP로 보낸다. 이미 끝나 있었으면 곧바로 FENCED다. 끝나지 않으면(D 상태) 보내지 않고 hold 시한의 fallback이 받는다. launcher가 그
   (p, i)의 pidfd를 쥐지 않았으면 신호를 보내지 않고 FENCE_NAK과 "refused to signal … (STOP_launcher)" 줄을 내며, 짝은 곧바로 fallback한다(8절의 채점 규칙). 한 사건 한 말: FENCE가
   왔으면 FENCED가 EXITED와 LEFT를 대신한다(launcher 그대로) `[측정: launcher 소스를 읽음]`.
4. **펜스 낱말 `fencedPlus1`**(둘째 재검토의 막는 문제 1) `[설계 v3 4.4절]`. 논리 rank마다 hold 칸 옆의 64비트 낱말 하나: 0 = 펜스 없음, i + 1 = 화신 i가 끝났음을 launcher가 확인함. 설계 v3는 32비트 낱말과 그 `static_assert`를 적었으나,
   준비 단계 헤더는 i + 1의 넘침을 없애려 64비트로 두고 그 까닭과 크기를 단언한다. 준비 단계 리뷰(nit 4)가 64비트가 맞다고 보아 문서 쪽을 고쳤다 `[소스: impl/rs_ctrl_api.h]`.
   선 위의 EXITED와 FENCED는 화신 i를 그대로 싣고 메모리 낱말만 + 1이다. 설계 v2의 `fencedInc`(= i)는 준비 직후의 0이 "화신 0이 펜스됨"과 같아, 첫 죽음(거의 늘 화신 0)의 hold가
   시작되는 순간 활성화 조건이 이미 참이었다(멈춘 상대의 펜스 셀에서 옛 화신이 살아 있는 채 복원될 수 있었음). 0xFFFFFFFF를 "없음"으로 두는 안 대신 이것을 고른 까닭: 0으로 채운 상태
   (memset, 구조체 초기화, 예비 프로세스의 재생)가 곧 "없음"이라 초기화를 하나 빠뜨려도 "펜스됨"으로 읽히지 않는다. helper는 끝남 말(EXITED, FENCED)을 받으면 계보 분류가 CURRENT나
   HELD_OLD일 때만 `max(낱말, i + 1)`로 올린다. 낱말은 내려가지 않고 지우지도 않는다(다음 화신 i + 1의 hold는 i + 2를 요구). hold 칸의 원자 상태(감시 스레드의 시한 CAS, 14095)는
   바꾸지 않는다.
5. **활성화가 확인하는 곳**은 짝의 활성화 결정 하나다: 모든 HOLDING과 `fencedPlus1[p] = dead + 1`을 함께 요구한다. kill에서는 종료 보고가 곧 펜스 끝이므로 낱말이 어떤 HOLDING보다
   먼저 설 수 있다(9.5절). REJOIN 받아들임은 짝에서만 같은 조건을 다시 본다(방어 검사). 짝이 아닌 생존 rank의 REJOIN 받아들임에는 FENCED 조건을 두지 않는다: REJOIN(i + 1)은 짝의
   ACTIVATE가 받아들여진 뒤에만 생기고 그 활성화가 이미 FENCED를 요구했다. 그래서 모든 복원이 모든 생존 rank의 launcher QP에 기대지 않는다 `[설계 v3 4.4절; 추론]`. launcher도
   원래 프로세스의 pidfd가 아직 읽히지 않은 (rank, 화신)의 ACTIVATE를 거절한다(둘째 문) `[측정: launcher 헤더를 읽음]`.
6. **kill로 끝난 경우.** launcher는 등록된 rank의 pidfd를 늘 쥐고 있어 프로세스가 스스로 끝나면 종료 보고(EXITED)를 모든 rank에 보낸다. 그 화신은 그 순간 펜스 끝이다.
   그래서 SIGKILL 셀에서는 3번의 종료 요청이 필요 없고 펜스는 원래 프로세스의 정리 시간(102–206 ms `[설계 v2 4.4절]`)에 끝난다. 지금 관문의 'later' 기다림과 같은 크기다 `[추론]`.
   EXITED 말을 끈 셀(`NO_EXIT_REPORT`)에서는 3번의 FENCE가 곧바로 FENCED를 받는다(스위치는 FENCED를 끄지 않음).

**국면은 바꾸지 않는다**(둘째 재검토의 막는 문제 1) `[설계 v3 4.4절; 소스: rs_lineage_api.h]`. 설계 v2를 접은 이 문서의 앞 판은 FENCING, FENCED를 국면 표의 행으로 두고 보기 함수
`gdakiLnViewOf`의 입력에 펜스 낱말을 더하라고 적었다. 계보 헤더는 국면이 "the incarnation axis only"(L:39)이고 "No wire, device or side-table change"(L:11)이며, 분류는
HOLD_WAIT, HOLD_SUCC가 아닌 국면을 모두 LIVE 규칙으로 처리한다(L:109 `default:  // LIVE; BAD as LIVE with cur = known`). 새 국면 값이 들어가면 HOLD_WAIT의 x = dead가 HELD_OLD가 아니라
CURRENT가 되어 죽은 화신의 기록이 받아들여진다. 그래서 gin-mirror의 국면(LIVE, HOLD_WAIT, HOLD_SUCC, ENDED, BAD)과 `gdakiLnViewOf`의 서명은 그대로 두고, 보고용 이름만 따로 된 순수
함수 `gdakiLnFenceOf(view, fencedPlus1, fenceSent)`가 낸다. 이 함수와 상수는 이 실험의 공유 헤더 `impl/rs_ctrl_api.h`에 두므로 `../mirror/impl/rs_lineage_api.h`는 바이트 그대로이고
사본도 필요 없다(9.8절 파일 자리).

| 보고 이름(`gdakiLnFenceOf`) | 조건(view.phase = HOLD_WAIT일 때만) | 받아들이는 것 |
|---|---|---|
| NONE | FENCE를 아직 보내지 않았고 `fencedPlus1 ≠ dead + 1` | HOLDING 모음 |
| FENCING | FENCE를 보냄, `fencedPlus1 ≠ dead + 1` | FENCED, EXITED; ACTIVATE는 내지 않음 |
| FENCED | `fencedPlus1 = dead + 1`(FENCED 또는 EXITED, hold 전에 온 EXITED 포함) | 모든 HOLDING이 모였으면 ACTIVATE(dead + 1), 그 뒤 REJOIN |

- classify는 그대로 HOLD_WAIT 행을 쓴다(x < dead는 STALE, x = dead는 HELD_OLD, x > cur는 FUTURE). 바뀌는 것은 짝의 활성화 결정과 짝의 REJOIN 받아들임에 "`fencedPlus1` = dead + 1"이
  더해지는 것뿐이고, 단위 시험 oracle의 다름 목록은 활성화 관문의 칸만이어야 한다. 단위 시험 장면: 준비 직후 모든 rank가 펜스 없음, 화신 0의 hold 시작 직후 활성화 거절, hold 전에 온
  EXITED(0) 뒤 모든 HOLDING이 모이면 활성화, 옛 화신의 FENCED(i − 1)는 화신 i의 hold를 풀지 않음, FUTURE와 STALE의 EXITED는 낱말을 바꾸지 않음 `[설계 v3 4.4, 7.3절]`.
- 활성화 관문(`gdakiRsActExamine`, 4550)의 "Z = GO"를 없애고 활성화 기록이 FENCED를 실었을 때만 ACCEPTED한다. 예비 프로세스는 `/proc`을 스스로 보지 않는다.
  gin-mirror의 빠른 모드(Z를 끝남으로 봄, 8/95)는 사라진다. 이행 중(9.8절 1단계)에는 이 관문을 launcher와 짝을 맺은 문맥에서만 켜고, 없으면 `/proc` 관문을 쓴다.
  통합 트리에서는 그 조건(`launcherPaired`)이 3단계 전이라 상수 거짓이어서 FENCED 관문이 늘 꺼져 있다 `[측정: 문서 impl/notes_int.md]`. 1단계와 2a-1 코드 리뷰(고칠 것 5)대로
  3단계가 합쳐지면 rdma 빌드에서 `/proc` 갈래를 없애고 FENCED 하나만 요구하며, 그 전의 이행 기간에는 문맥마다 한 번 선 "launcher와 짝 맺음"을 내려가지 않는 걸쇠로 둔다.
- `NCCL_GIN_RESTORE_FENCE=none`이면 멈춤 판정은 거절만 하고 생존 QP는 오류로 남는다(옛 쓰기는 버려짐). fail-fast이거나 예비 프로세스가 없어도 같다.
- **불변식.** 논리 rank p로 가는 생존 rank의 QP(사용자, mirror, 기록, 생존 READ, 저장소 응답 쪽)는 p의 옛 화신 스레드가 하나라도 남은 동안 RTS가 아니다. 남는 입구는
  UD이고, UD의 모든 종류는 화신을 보고 HELD인 rank의 옛 화신을 버린다. 예외는 fd를 물려받은 자식이다: helper와 증인 소켓은 fork 때 닫지만(`pthread_atfork`), uverbs fd는
  막지 못한다. 자식이 uverbs fd까지 쥐면 부모가 끝나도 QP와 GPU 문맥이 남아 READ가 성공하고 박동만 멈춘다. launcher는 부모의 pidfd만 보므로 종료 보고가 곧 FENCED를
  만들고 펜스는 이 경우를 막지 못한다. 그래서 그 셀은 셀 설정(예비 프로세스 없음)으로만 복원하지 않고 거절하며 한계로 적는다(사용자 결정 13, 9.9절 끝).
- 페이지의 계보 보기는 판정과 보고에만 쓰고 classify 입력이 아니다(9.2절).

### 9.5 launcher

- **무엇.** 노드마다 하나, 늘 있는 작은 프로그램(시험 장치 쪽 C, verbs와 pidfd, Unix 소켓). 2026-10-17에 `impl/launcher/`로 빌드됐다(12절 다섯째 행). 실행기가 클러스터 hold 시작
  때 한 번 띄우고(시행마다가 아님) 끝에 끈다(sunny는 ssh 하나). RNIC 쪽에 UD QP 하나, rank마다 RC QP 둘(기록, 생존 READ), launcher 페이지 하나(9.2절). 노드 안에 Unix 소켓 하나(사용자
  결정 3: fd 전달 때문; SOCK_SEQPACKET, 경로의 디렉터리는 자기 uid의 0700). 단일 스레드, poll 하나다 `[설계 v3 5.2절; 측정: launcher README와 헤더를 읽음]`.
- **말의 배치.** Unix 소켓 말 일곱 종류(`GL_U_*`, 256 B = 머리 64 B + 본문 192 B; 활성화 바이트만 뒤에 덩어리, 한도 64 KiB)와 RNIC 쪽 launcher 말 열일곱 종류(`GL_K_*`: PAIR, PAIR_ACK,
  CONNECTED, REG_NOTE, EXITED, LEFT, FENCE, FENCED, FENCE_NAK, ACTIVATE, ACT_ANSWER, FETCH_EP, FETCH_READY, FETCH_DONE, ABORT, SPAWN, REFUSED; 봉투 64 B + 말 256 B = 320 B), 끝점 40 B는
  `impl/launcher/launcher_msg.h`(지금 md5 `897641f3`; 처음 빌드 판 `30a05c7f`)가 `static_assert`로 고정하고, 설계 v3와 rank 쪽 공유 헤더는 그것을 따른다 `[측정: 헤더를 읽음]`.
- **하는 일.** (1) 같은 노드 rank의 pidfd를 쥐고, 끝나면 한 사건 한 말로 모든 rank에 알림: FENCE가 왔으면 FENCED, 아니면 LEAVING 뒤면 LEFT, 아니면 EXITED. 말은 (rank, 화신, nonce)를
  싣고, 받는 rank는 계보 분류가 CURRENT나 HELD_OLD일 때만 쓰며 FUTURE와 STALE은 버리고 `GIN/LN` 줄 하나를 남긴다. rank가 되지 않은 예비 프로세스의 끝남은 EXITED가 아니고 활성화 답과
  예비 자리 낱말로만 알린다 `[설계 v3 5.2절]`. (2) FENCE를 받으면 등록받은 pidfd에만 신호를 보내 원래 프로세스를 종료하고 스레드 그룹이 끝났음을 확인한 뒤 FENCED; 쥔 것이 없으면
  FENCE_NAK(9.4절). (3) 짝의 ACTIVATE를 등록 표로 먼저 보고(nonce, rank, 화신 = 끝난 화신 + 1) 예비 프로세스에 넘기고 답을 돌려줌(사용자 결정 11). (4) 예비 프로세스가 HELLO 전이면
  곧바로 REFUSED(까닭 "예비 프로세스 없음"), HELLO 뒤 READY 전이면 LATER를 한 번 보내고 READY가 오면 넘김(사용자 결정 4; 짝은 20 ms마다 다시 묻지 않음), 예비 프로세스가 끝났으면
  REFUSED(까닭 "예비 프로세스 끝남"), 원래 프로세스의 pidfd가 아직 안 읽혔으면 REFUSED. (5) SPAWN은 따로 된 종류 REFUSED(sub = SPAWN, "spawn not built"; 4절의 경계, 실행은
  gin-dynamic)로 답하고, 짝은 이 종류로는 결코 fallback하지 않는다(활성화 답이 아님; 둘째 재검토의 고칠 것 1). (6) 쓰이지 않은 예비 프로세스는 그 pidfd로 종료함. (7) 그 rank와의 기록
  QP가 깨지면 스스로 PAIR(기록, 세대 + 1)를 500 ms마다 10 000 ms까지 보냄(9.1절). (8) 예비 프로세스가 ACCEPTED를 낸 뒤에는 짝과의 launcher QP가 끊기거나 다시 짝 맺어도
  활성화를 그만두지 않고(줄 하나만 남김) FETCH 말은 다시 맺은 QP로 보낸다. ACCEPTED 뒤의 활성화를 끝내는 것은 짝의 명시 ABORT와 FENCE뿐이다. 준비 단계 리뷰(고칠 것 12)는
  "FETCH_DONE 뒤만 빼기"를 권했고, 고침은 조율 세션의 지시대로 ACCEPTED 전부를 뺐다(FETCH 전후 같음) `[측정: 문서 impl/notes_prepfix.md; launcher 단위 시험 장면 lost_accepted]`.
- **노드 안 Unix 소켓에 실리는 말**(사용자 결정 3의 설계 해석: 활성화 바이트와 "떠남"도 싣고, PID와 시작 시각 대신 pidfd를 넘김; 설계는 "사용자가 반대하지 않으면" 이 해석을 쓴다고
  적음; 종류 이름은 launcher 헤더) `[설계 v2 5.2절; 측정: launcher 헤더를 읽음]`.

  | 말 | 방향 | 내용 |
  |---|---|---|
  | 등록(`GL_U_REGISTER`) | rank → launcher | (rank, 화신, nonce) + 자기 pidfd(SCM_RIGHTS). launcher는 `SO_PEERCRED`의 uid가 자기와 같고 pid 검사(아래)가 맞을 때만 받음 |
  | 인사 답(`GL_U_HELLO_ACK`) | launcher → rank, 예비 | 받음/거절(까닭), launcher의 노드 번호, UD 끝점, Q_Key, launcher 페이지 자리와 자기 칸 번호 |
  | 떠남(`GL_U_LEAVING`) | rank → launcher | (rank, 화신). BYE 전에, communicator를 없앨 때. 등록한 연결로 온 것만 셈 |
  | 예비 등록(`GL_U_SPARE_HELLO`) | 예비 프로세스 → launcher | (rank, 새 화신, 0이 아닌 nonce) + 자기 pidfd. 같은 (rank, 화신)의 둘째 접속은 거절 |
  | 준비됨, 재생 실패(`GL_U_SPARE_STATUS`) | 예비 프로세스 → launcher | 재생, FETCH 버퍼 join, Resume 진입이 끝남 / 실패 |
  | 활성화 바이트(`GL_U_ACT_BYTES`) | launcher → 예비 프로세스 | `gdakiRsActivate` 기록과 활성화 덩어리(지금 TCP 활성화 연결의 바이트 그대로) |
  | 답과 FETCH 차례(`GL_U_ACT_TALK`) | 예비 프로세스 ↔ launcher | ACCEPTED, LATER, REFUSED, 자기 FETCH QP 끝점, READY, DONE, ABORT |

- **pid 검사는 필수이고 끌 수 없다**(둘째 재검토의 고칠 것 11) `[설계 v3 5.2절]`. launcher는 넘겨받은 pidfd의 pid(`/proc/self/fdinfo`의 `Pid:`)가 `SO_PEERCRED`의 pid와 같고 그 pid의
  시작 시각이 접속 때와 같을 때만 받는다. 다르면 거절하고 STOP_launcher 줄을 남긴다(8절). 같은 uid의 다른 프로세스(자식 등)의 pidfd를 넘겨 뒤의 FENCE가 그 프로세스를 끝내는 일을 막는다.
- **pidfd 사실**(launcher 단위 시험) `[측정: impl/launcher/README_launcher.md가 적은 launcher_unit 네 번 실행(n 4)의 범위, rain Linux 5.15.0-97, fork한 자식(CUDA와 verbs 없음);
  이 문서에서 로그를 다시 세지 않음]`:
  - main thread가 끝나고 다른 thread가 300 ms 더 살면 `/proc`은 Z인데 pidfd는 마지막 thread가 끝날 때(+301.1–301.5 ms)에만 읽힌다. 옛 관문이 Z를 끝남으로 친 창을 pidfd가 닫는다
    (`gate_fenced` 예측의 바탕). 그 창 안의 FENCE는 SIGKILL 뒤 2.13–2.69 ms에 FENCED였다.
  - 거두지 않은 zombie의 pidfd는 읽히고 `pidfd_send_signal`은 0을 돌려준다. 거둔 뒤에는 ESRCH다.
  - 주 thread가 아닌 thread의 TID로 `pidfd_open`하면 EINVAL이다.
  - 멈춘(T) 프로세스에 pidfd로 보낸 SIGKILL은 닿고 0.46–0.62 ms 뒤 pidfd가 읽힌다(멈춤 펜스의 바탕).
  - LEAVING을 보내고 곧바로 끝난 프로세스는 80/80 LEFT, 0/80 EXITED였다.
  - SCM_RIGHTS로 받은 pidfd의 fdinfo `Pid:`가 보낸 프로세스의 pid였다(pid 검사의 바탕).
  - `[미확인]`: 여러 thread인 CUDA 프로세스의 pidfd가 읽힐 때 uverbs fd와 GPU fd가 이미 닫혔는가, sunny(6.8)에서도 같은가. 둘 다 9.8절 실행 가능성 확인이다.
- **rank 쪽이 지킬 것**(launcher가 기대는 것) `[설계 v3 5.2절]`: 예비 프로세스는 SPARE_HELLO에 0이 아닌 nonce를 싣는다; 등록한 Unix 소켓 연결은 프로세스가 사는 동안 열어 두고
  `SOCK_CLOEXEC`이며 fork 때 자식에서 닫는다(LEAVING은 그 연결로만 셈); rank의 launcher 기록 QP는 `max_dest_rd_atomic` ≥ 1이고 outbox MR은 REMOTE_READ다(launcher가 짝의 outbox에서
  덩어리를 READ함); rank는 REFUSED 종류로는 결코 fallback하지 않는다.
- **정상 종료.** rank는 BYE 전에 노드 안 소켓으로 "떠남"을 알리고, launcher는 그 프로세스가 끝나면 종료 보고 대신 LEFT를 보낸다. 생존 rank는 LEFT나, BYE를 받은 rank의
  끝남을 떠남으로 치고 어떤 경우에도 hold로 가지 않는다(9.3절 1, 2행). 링 기록과 launcher 말 사이의 차례는 정하지 않으므로 BYE와 종료 보고의 차례에 기대는 규칙은 두지 않는다
  `[설계 v2 2.4, 4.2, 5.2절]`.
- **안전.** launcher가 신호를 보내는 대상은 자기가 등록받거나 띄운 pidfd뿐이고 pid로 신호를 보내는 길은 없다(저장소 규칙 "내가 띄운 것만 끈다"). 다르면 거절하고 줄을 남긴다(8절 STOP).
  이 프로그램의 실패는 그 노드 rank들의 복원만 막는다: launcher QP의 첫 답이 1 000 ms(소프트웨어 시한) 안에 없으면 짝은 그 노드의 예비 경로가 없다고 보고 fallback하고, 재시도
  초과(3.66 s)를 기다리지 않는다. 생존 판정에서 launcher 실패는 L = 무응답일 뿐이고 그것만으로 어떤 rank도 거절하지 않는다(9.3절).
- **LATER 뒤의 한도**(둘째 재검토의 고칠 것 13) `[설계 v3 5.4절; 측정: launcher 헤더와 README를 읽음]`. 이 실험의 launcher는 LATER 뒤 자기 한도가 없다: READY, 재생 실패, 예비
  프로세스의 끝남, 짝의 ABORT만 기다림을 끝낸다. 대신 LATER에 예비 프로세스의 상태와 그 나이(HELLO부터)를 싣고, 페이지의 예비 자리 낱말과 `spareSinceMs`, 박동이 그 뒤에도 움직인다.
  그래서 한도는 짝이 센다: 넘으면 ABORT를 보내고 fallback한다(ABORT 뒤의 ACCEPTED는 launcher가 버림). 짝은 LATER 뒤 그 launcher 페이지를 100 ms마다 끌어 읽고 박동이
  `LAUNCHER_STALL_MS`(1 000) 넘게 서거나 launcher QP가 오류면 launcher 잃음으로 친다. 그래서 READY를 보내지 않는 예비 프로세스나 LATER 뒤 죽은 launcher가 생존 rank를 hold 시한(20 s)까지
  붙잡지 않는다. 한도의 값은 짝이 LATER를 받은 때부터 1 000 ms(`NCCL_GIN_CTRL_LATER_MS`)이고 `LAUNCHER_STALL_MS`도 1 000이다(2026-10-17 사용자 결정 4, 9.7절 끝 v3 목록 4). 헤더 기본값도
  1 000이다(준비 단계 헤더의 초안 5 000을 통합 때 고침) `[소스: impl/rs_ctrl_api.h]`.
- **등록과 무장.** 원래 rank는 체크포인트마다 STORE_REQ 꼬리에 예비 등록을 싣는다(사용자 결정 7로 mirror 끔도 저장소 길; 17236–17247). 지금은 관리망 주소 32 B, PID, 시작 시각이다.
  rdma 빌드에서는 (경로 종류 = launcher, launcher 노드 번호, rank, 화신)으로 바꾸고 판 번호를 올린다(사용자 결정 10; 판을 올린 `rs_store_api.h`의 사본은 `impl/`에 둠, 9.8절). PID와
  시작 시각은 싣지 않는다: launcher가 (rank, 화신)의 pidfd를 쥐기 때문이다. **무장**(둘째 재검토의 고칠 것 8): 체크포인트의 무장 비트는 지금 `ck->rep.allArmable() &&
  gdakiCkptSelfOf().haveSpare`(14981) `[소스]`이고, rdma 빌드의 `haveSpare`는 launcher 헤더의 `gl_path_exists`와 같다: 자기 노드 launcher가 이 화신의 등록을 받았고, 그 launcher와의
  기록 QP가 CONNECTED, 그 launcher의 REG_NOTE나 페이지 등록 낱말이 (ALIVE, rank, i), 예비 자리 낱말이 (rank, i + 1)의 REPLAYING, READY, OFFERED 가운데 하나(HELLO 이상), 모든 launcher와
  짝 맺음, LEAVING 안 보냄 `[설계 v3 5.4절; 측정: 헤더를 읽음]`. 설계 v2의 조건("launcher와 짝 맺기 + pidfd를 쥠")은 launcher만 있으면 늘 참이라, 예비 프로세스가 없는 셀도 무장되어
  hold → REFUSED → fallback이 되었을 것이다. 무장 표시는 체크포인트 때 다는 것이라, 무장된 체크포인트 뒤 예비 프로세스가 끝나면 다음 체크포인트까지는 무장된 채이고 활성화가 REFUSED로
  끝난다(`gc4_kill3_ow_spareabsent`가 이것을 잼).
- **활성화와 REJOIN 차례.** (1) 펜스(9.4절); 짝은 모든 HOLDING과 FENCED 전에는 ACTIVATE를 내지 않는다. (2) 짝이 활성화 덩어리(판 올림: rank마다 화신, UD 끝점, 페이지,
  outbox; 저장소 자리, mirror 켬이면 pool 자리; FETCH QP 끝점)를 outbox에 쓰고 ACTIVATE(64 B + 덩어리 자리)를 launcher에 보냄. 앞서 되살아난 생존 rank의 끝점은 mirror 켬과
  끔 모두 이 표가 덮는다. (3) 예비 프로세스가 Unix 소켓으로 준비됨(재생, FETCH 버퍼 join, Resume 진입 뒤)을 알리면 launcher가 덩어리를 짝의 outbox에서 READ해 기록과 함께
  넘기고, 예비 프로세스의 ACCEPTED와 FETCH QP 끝점을 짝에게 넘김. FETCH의 READY와 DONE도 같은 중계로 감. (4) 활성화의 REFUSED에는 짝이 곧바로 fallback(지금의 "거절 둘과
  1 000 ms" 규칙은 rdma 빌드에서 없어짐). (5) 예비 프로세스가 생존 rank마다 rank 차례로 REJOIN(32번)을 UD로 보낸다. 본문은 지금 바이트 그대로이고, REJOIN이 쓰지 않는 `nrp` 칸
  (64 × 4 B = 256 B, 5222)에 자기 기록 QP와 생존 READ QP의 끝점(각 40 B, 새 PSN), UD 끝점, 페이지와 outbox의 (주소, rkey, 길이), 세대, Q_Key를 싣는다(156 B `[추론]`). 그래서
  datagram은 1 936 B 그대로다. `nrp`가 비어 있음은 확인했다 `[소스]`: REJOIN은 `memset` 뒤 type, from, nonce, pad, `executed[0..1]`, `tok`, `nqp`, `executed[2..]`의 끝점 72 B만
  채우고(10146–10166, 9443–9445, 4664), REJOIN_ACK은 type, from, nonce, pad, round, `executed[0..1]`만 채운다(9563–9570); `nrp`는 REQ와 ACK(11874, 12191), 체크포인트 기록(14590,
  14746)에서만 쓰인다. 생존 rank는 지금의 받아들임 규칙(HELD, known + 1, nonce, 받아들임 순간의 park 검사, 거절된 rank에 FAIL)으로 가르고 짝은 펜스 낱말도 다시 본다(9.4절 5번).
  받아들이면 그 쌍의 기록 QP와 생존 READ QP를 RESET에서 예비 프로세스의 QPN으로 다시 잇고(새 PSN), 그 상대의 페이지와 outbox 칸을 새 값으로 바꾼 뒤 REJOIN_ACK을 UD로 보낸다.
  REJOIN_ACK의 `nrp`에는 자기 두 QP 끝점과 새 PSN, 페이지와 outbox 칸을 싣는다. **멱등**(둘째 재검토의 고칠 것 10) `[설계 v3 5.4절]`: 멱등 표는 REJOIN 종류에만 두고(PAIR의 표와 따로)
  그 rank가 HELD인 동안만 쓴다. 받아들인 뒤 같은 (from, 화신, 예비 QPN)의 REJOIN이 다시 오면 저장한 REJOIN_ACK만 다시 보내고 QP는 건드리지 않는다. 같은 (from, 화신)인데 QPN이 다른
  REJOIN은 FAIL 대신 버리고 `GIN/LN` 줄 하나를 남긴다: FAIL은 예비 프로세스를 곧바로 그만두게 하므로(10193–10197) 떠도는 datagram 하나가 복원 전체를 끝낼 수 있었다 `[소스]`. 예비
  프로세스는 한 REJOIN 시도 안에서 QP를 다시 만들지 않는다. 생존 rank는 예비 프로세스의 첫 RC 기록(CONNECTED) 전에는 그 QP로 보내지 않는다(지금은 받아들인 뒤 곧바로 TOKEN을 냄,
  9632). (6) 그 뒤 TOKEN, READY, DONE_RS, RESTORED, INJECTED, STORE_REQ는 링으로. STATE는 예비 프로세스가 생존 rank의 outbox를 READ하고, rkey 목록은 생존 rank가 예비
  프로세스의 outbox를 READ함.
- **되살린 rank의 다시 무장**(설계 v2 5.4절 7번). 되살린 프로세스는 두 launcher와 짝을 맺고(자기 노드 launcher에는 예비 등록으로 이미 붙어 있음), launcher는 그 rank의 등록을
  화신 i + 1의 pidfd로 바꾼다. 둘 다 끝나기 전에는 그 rank의 체크포인트에 무장 표시를 달지 않는다. 그래야 그 뒤 다른 rank가 죽을 때 되살린 rank가 종료 보고와 FENCED를
  받고, 짝이면 활성화를 낼 수 있다. **되살린 rank를 짝으로 둔 rank**(둘째 재검토의 고칠 것 14) `[설계 v3 5.4절]`: 이 testbed에서 짝은 p xor 1이라 되살린 rank는 늘 다른 rank w의
  짝이다. 짝은 STORE_ACK 꼬리에 "w 노드의 launcher와 짝 맺음" 비트를 싣고, w는 그 비트가 있는 STORE_ACK을 받은 뒤에만 자기 체크포인트에 무장 표시를 단다. 둘째 죽음 셀(gin-mirror
  회귀의 `mi4_kill2_kill3_ow`: 3의 짝은 되살린 2)은 3의 다시 무장 줄 뒤에 둘째 kill을 내야 하고, 아니면 8절의 제외다.
- **세 길 견줌**(제어 경로 설계 5.3절; 사용자 결정 2로 닫음). launcher가 늘 있는 끝점이 되어 아직 없는 프로세스도 등록할 수 있다. 생존 rank의 상태 페이지에 다른
  rank의 끝점을 싣는 길은 첫 RC를 맺을 길이 여전히 필요해 혼자 서지 못하고, 첫 교환만 관리망 소켓으로 하는 길은 사용자 결정과 맞지 않는다. 앞서 되살아난 생존
  rank의 새 끝점은 활성화 덩어리의 표가 싣는다(gin-mirror의 결정 (3)과 같은 길).

**동적 예비 프로세스 리뷰가 찾은 TCP 전제 열다섯과 이 설계의 답.**

| 리뷰 행 | TCP에 기대던 것 | 이 설계에서 |
|---|---|---|
| 1 | 등록이 관리망 주소라 아직 없는 프로세스를 주소로 등록 | 늘 있는 launcher를 등록(노드 번호, rank, 화신; 프로세스는 pidfd로 launcher에 붙음). QPN, rkey, PID를 미리 알 필요 없음 |
| 2 | 짝이 시도마다 새 TCP 연결(500 ms) | 준비 때 맺은 짝과 launcher의 RC QP로 ACTIVATE. helper를 500 ms 막던 보내기가 없어짐 `[소스: 13710]` |
| 3 | 거절 둘과 1 000 ms 규칙 | launcher의 명시적 답(REFUSED 곧바로, LATER 한도). launcher QP의 재시도 초과나 답 없음 1 000 ms면 fallback |
| 4 | 재생 전 활성화 소켓과 LATER thread | launcher가 대신 LATER(사용자 결정 4). 예비 프로세스에 일찍 답하는 thread와 넘기기 틈이 없음 |
| 5 | 'later'와 20 ms 다시 묻기 | LATER 한 번, 준비되면 마지막 답(사건 기반) |
| 6 | 활성화 연결이 FETCH 끝점, READY, DONE을 나름 | launcher 중계로 같은 차례(사용자 결정 11) |
| 7 | REJOIN과 그 뒤 기록, 자료 소켓 | UD REJOIN 뒤 RC 링, STATE와 rkey 목록은 outbox READ |
| 8 | 재생 비교와 all-gather에 실은 제어 QP 정보 | all-gather에는 rank마다 고정 칸만, 그 칸은 "달라도 되는 칸". 쌍마다의 QPN은 짝 맺기가 나눔(9.6절) |
| 9 | 포트 bind(EADDRINUSE)로 중복 막기 | launcher의 (rank, 화신) 중복 막기와 Unix 소켓의 같은 (rank, 화신) 둘째 접속 거절. 늦게 뜬 예비 프로세스는 launcher가 종료 |
| 10 | 화신마다 다른 포트 | 기록의 화신, `NCCL_GIN_RESTORE_SPARE_INC` 검사, Q_Key와 nonce |
| 11 | hold 시작의 launcher hook(짧은 TCP 기록) | launcher QP의 SPAWN WR 하나(막지 않음). 이 실험의 launcher는 "spawn not built"로 REFUSED(4절) |
| 12 | launcher와 실행기 사이(ssh, 관리망 TCP) | 시험 장치라 남음. 라이브러리 쪽 말은 모두 RDMA |
| 13 | 활성화 관문(`/proc`) | FENCED(9.4절) |
| 14 | 예상 시간의 "활성화 뒤 67–71 ms" | TCP 손잡기가 없어지므로 다시 잼(지금 67.2–71.4 ms, n 45 `[측정]`). 줄 것으로 보되 크기는 `[미확인]` |
| 15 | 죽음 판정과 hook 시각(TCP 거절 둘, RST 1 s) | 9.3절 판정 표와 launcher 종료 보고. 띄우기 시각의 기준 줄을 판정 줄이나 EXITED 줄로 |

### 9.6 준비, bootstrap, 그리고 관리망에 남는 것

**작업 시작.** GIN collComm의 준비 all-gather(18011)는 이미 RDMA(net_ib isend/irecv)다 `[소스: 18011; gin.cc 45–110]`. 그 기록 `gdakiTsAddr`(17920–17927)에 rank마다
고정 칸을 더한다(설계 v2 5.1절; rank마다 약 130 B). 이 all-gather는 늘 모든 rank가 부르므로 칸을 더해도 수가 어긋나지 않는다 `[소스: 17885–17889]`. 쌍마다의 RC
끝점은 싣지 않는다(UD 짝 맺기가 나눔).

| 칸 | 크기 | 재생 비교 | 뜻 |
|---|---|---|---|
| 지금 칸(magic, rank, 관리망 주소, salt, policy, policyPad) | 그대로 | 지금 그대로(주소만 달라도 됨) | 관리망 주소는 증인 소켓에만 씀 |
| 제어 길 | 4 B | 엄격히 같아야 함 | 빌드(tcp, rdma). 한 rank라도 다르면 그 문맥은 fail-fast |
| launcher 노드 번호 | 4 B | 엄격히 같아야 함 | 그 rank 노드의 launcher |
| launcher UD 끝점과 Q_Key | 44 B | 달라도 됨 | 같은 노드 Unix 소켓에서 받음 |
| UD 끝점 | 40 B | 달라도 됨 | 첫 만남 |
| 상태 페이지 | 주소 8 + rkey 4 + 길이 4 | 달라도 됨 | 생존 READ |
| outbox | 주소 8 + rkey 4 + 길이 4 | 달라도 됨 | 큰 자료 READ |
| `active_mtu` | 4 B | 달라도 됨 | 준비 합의 |

- 예비 프로세스는 이 all-gather를 기록으로 대답하고 자기 칸만 새 값으로 바꾼다. 재생 비교(`gdakiRsSpareSetupMatch`, 4700, 18018–18021)에는 위 표의 "달라도 됨"만 허용
  칸으로 넣는다. 다른 rank의 칸은 원래 프로세스가 준비할 때의 값이므로, 그 뒤 되살아난 생존 rank의 끝점은 활성화 덩어리의 표가 덮는다(mirror 켬과 끔 모두).
- **준비 검사**(Resume 조건의 초안 번호; 지금 조건은 40까지, gin-mirror 9.7절) `[설계 v2 5.1절]`: 41 복원을 청했는데 그 노드 launcher와 짝을 맺지 못함(사용자 결정 2), 42
  `active_mtu < IBV_MTU_2048`인 rank가 있음(사용자 결정 9), 43 `ibv_is_fork_initialized()`가 `IBV_FORK_UNNEEDED`가 아님(rain 5.15, sunny 6.8에서 맞을 것 `[추론, 미확인]`),
  44 제어 길이나 launcher 노드 번호가 rank 사이 또는 재생 기록과 다름. 넷 다 그 문맥을 fail-fast로 둔다. 새 영역은 `MADV_DONTFORK`로 둔다.

**준비 차례.** (1) UD QP, 링, 페이지, outbox를 만들고 같은 노드 launcher의 Unix 소켓에 붙어 등록(자기 pidfd를 SCM_RIGHTS로)하고 launcher의 노드 번호, UD 끝점, Q_Key를 받음, (2) all-gather,
(3) 모든 gated 쌍의 짝 맺기, (4) 모든 launcher와 짝 맺기, (5) MIRROR_SETUP 같은 helper 시작 전 기록을 링으로, (6) 증인 소켓(켰을 때, 지금 코드 그대로).

**`r->ctrl`과 UD 끝점을 만드는 자리**(이 문서의 선택, 2026-10-17 통합; 9.7절 끝 선택 표). 설계 v3는 제어 계층 상태 `r->ctrl`을 연결 부분 `gdakiTsSetupConnect` 안에서 만든다고 적었고,
고친 준비 단계도 all-gather 뒤, 연결 부분 앞에서 만들었다. 위 차례 (1)대로 UD 끝점, 페이지와 outbox의 자리를 all-gather 칸에 실으려면 그것들이 all-gather 전에 있어야 한다.
그래서 통합 트리는 `r->ctrl`을 `gdakiTsSetup`의 all-gather 바로 앞에서 만든다(`#if !NCCL_GIN_CTRL_TCP` 안이라 tcp 전처리는 그대로) `[측정: 문서 impl/notes_int.md]`. 링과 UD QP를
그 자리에서 만들고 끝점을 칸에 싣는 것은 2a-2이고, 지금 `r->ctrl->ring`은 늘 비어 있다.

**관리망에 남는 것.**

| 무엇 | 왜 | 범위 |
|---|---|---|
| NCCL 자신의 bootstrap(`ncclCommInitRank`)과 net_ib 연결 맺기 | NCCL 핵심이 `NCCL_SOCKET_IFNAME` 소켓으로 함. 초기화 때만이고 이 계층 밖. 예비 프로세스는 기록으로 재생해 쓰지 않음 | 라이브러리, 초기화 |
| 증인 소켓(`NCCL_GIN_CTRL_WITNESS`, 기본 켬) | "노드 죽음"과 "RNIC 선 끊김"을 가르는 유일한 길(launcher와 rank가 같은 RNIC 선을 씀), FIN으로 확인 창을 빨리 부름. BYE와 FIN만 | 라이브러리, 상시 |
| 실행기가 launcher와 rank를 띄우는 ssh, `cluster_run.sh`, 로그 모으기 | 시험 장치 | 라이브러리 밖 |

복원 계층의 기록, 등록, 활성화, REJOIN, 큰 자료, 펜스, 종료 보고는 초기화 뒤 관리망을 쓰지 않는다. 같은 노드 안의 파일과 Unix 소켓(초기화 기록, launcher
끝점)은 네트워크가 아니다. `no_tcp_control`(3절)이 시행마다 이것을 센다.

**UD MTU.** UD datagram 하나(봉투 64 B + 기록 1 872 B)가 들려면 경로 MTU ≥ 2 048이어야 한다. testbed의 PMTU는 4 096이다 `[측정: 문서 ack_timeout]`. 제어 경로 설계
리뷰가 사용자 결정 9의 확인을 했다: GIN 포트 rain `mlx5_1`, sunny `mlx5_0`의 `active_mtu`가 둘 다 4 096이고, gin-restore 실행 가능성 kv의 경로 MTU도 4 096이다
`[측정: 문서, 리뷰가 2026-09-23과 2026-10-09 캡처에서 읽음]`. RoCE의 `active_mtu`는 netdev MTU를 따라 바뀌고 옛 클러스터는 1 024였다. 그래서 준비 때 rank마다
`ibv_query_port`의 `active_mtu ≥ IBV_MTU_2048`을 보고 그 값을 준비 합의(all-gather의 `active_mtu` 칸)에 넣으며, 시행 kv `active_mtu`에 남긴다 `[설계 v2 2.5절]`. 한 rank라도
못 맞추면 그 문맥의 복원은 켜지지 않고 fail-fast다(Resume 조건 42; 조각내기는 만들지 않음).

### 9.7 기존 장치와의 충돌 표

열: 기존 장치 / 무엇이 부딪칠 수 있나 / 이 설계가 피하는 길 / 상태 / 근거(`[소스]`는 9절 머리의 호스트 파일 줄). "결정 n"은 2026-10-16 21시 무렵 사용자 결정의 번호(1절)다.

| 기존 장치 | 무엇이 부딪칠 수 있나 | 이 설계가 피하는 길 | 상태 | 근거 |
|---|---|---|---|---|
| helper 단일 스레드 주인(helper 소켓은 helper만, 다른 스레드는 기록을 넘김) | 링, UD, launcher QP를 누가 내고 걷나 | 모두 helper. 준비 스레드와 예비 프로세스 driver는 helper 시작 전에만 쓰고 넘김. 생존 READ QP와 페이지 쓰기는 감시 스레드. CQ를 스레드마다 따로 | 닫힘(설계) | 10208, 6290–6296 |
| 상대마다의 park(256개, 60 s, 도착 차례) | 기록이 CQ에서 와도 같은 차례인가 | CQ에서 꺼낸 기록을 그 상대의 inbox(한도 4 096, 한도에서는 credit을 돌려주지 않음)로, 거기서 지금의 park로. 자리는 복사 뒤 곧바로 다시 냄 | 닫힘(설계) | 5501–5510, 12965 |
| 투명 복구 라운드(REQ, ACK, DONE, 라운드 안 소켓 잃음 = 취소) | 라운드 기록이 RDMA로, 취소 조건 | 판정 표가 상대를 "모름" 이상으로 바꾸면 취소(기록 QP 오류의 약 3.66 s를 기다리지 않음; 설계 v2 2.4절). 라운드 코드는 전송을 갈아 끼우는 자리 뒤라 그대로 | 닫힘(설계) | 11707, 12210–12240 |
| 재연결 기계(HELLO, PROBE, 거절 둘, 펜싱) | 기록 길과 증인 | 다시 짝 맺기가 기록 길을 맡고, 증인의 다시 걸기와 거절, 한도는 증인 상태로만 남고 거절이 되지 않음 | 닫힘(설계) | 8302–8388, 8551–, 9110–9114 |
| gin-harden의 BYE와 FIN, 강한 증거 | FIN만으로 죽음 판정 | 증인 FIN이나 RST(BYE 없음)의 확인 창: t_F에 READ1, t_F + W/2에 READ2, t_F + W에 판정(9.3절). 떠남은 링의 BYE, 증인 BYE, LEFT로 가르고 증인의 "BYE 뒤 FIN"은 보고만. FIN 규칙을 쓰는 셀은 rdma 빌드에서 다시 예측. tcp 빌드는 지금 그대로 | 닫힘(설계 v3, 2026-10-17)(결정 5; floor 규칙과 W는 2026-10-16 밤 사용자 결정 (가)). W의 값만 pilot | 5706–5711 |
| 정상 종료와 launcher 종료 보고 | 시행 끝의 정상 종료가 종료 보고를 만들고, 차례가 정해지지 않은 BYE와 엇갈려 모든 시행 끝에 거짓 hold가 생길 수 있음(리뷰) | rank가 BYE 전에 노드 안 소켓으로 "떠남"을 알리고 launcher는 종료 보고 대신 LEFT를 보냄. BYE를 받은 rank의 종료 보고도 떠남. 어떤 경우에도 hold하지 않음(증인을 꺼도 섬) | 닫힘(설계 v2 4.2, 5.2절) | 9.3절 판정 표, 9.5절 |
| 원격 접근 오류의 뜻 | 원격 접근 오류 하나를 "끝남"으로 보면 살아 있는 상대(되살린 rank의 새 rkey)를 죽음으로 봄(리뷰) | 원격 접근 오류 하나는 판정 없음(9.3절 16행: 다시 짝 맺기, `PROBE_FAIL_N`번 뒤 "모름" 거절). FIN과 겹칠 때만 강한 증거(REMACC+FIN), launcher 끝남과 겹치면 원인은 EXITED. REJOIN, REJOIN_ACK, PAIR, PAIR_ACK이 새 끝점과 (주소, rkey)를 실음. REJOIN과 REJOIN_ACK의 `nrp`가 비어 있음은 확인(10146–10166, 9563–9570) | 닫힘(설계 v3, 2026-10-17) | 9.3절 판정 표, 9.5절, `../../../teardown_order/README.md` |
| kill 판정 시각의 어림 | 처음 초안의 "약 5–6 ms"가 측정된 정리 차례와 맞지 않음(리뷰); 설계 v2의 확인 창에는 판정 시각과 READ2의 시한이 없었음(둘째 재검토의 막는 문제 3) | 판정은 늘 t_F + W(증인 FIN → 판정 W–W + 1 ms, kill → 판정 약 20–51 ms), 창이 "확인 못함"이면 launcher 보고(102–206 ms). 기록 QP 오류는 창을 열지 않음. 판정 줄에서 잰 복원은 약 W 짧고 kill → 복원 끝은 지금 ± 20 ms | 닫힘(설계 v3, 2026-10-17); W 값만 `[초안]` | 9.3절, 3절 메모 |
| 다시 짝 맺기 때 기록 잃음 | 정확히 한 번 전달을 할까 | TCP와 같은 뜻(세대가 바뀌면 ACK 안 된 기록은 사라짐, STORE_ACK 꼬리의 고침 그대로) | 닫힘(결정 6, 2026-10-16) | 15967–15971 |
| REJOIN 받아들임 차례(HELD, known + 1, nonce, park 검사, 거절된 rank에 FAIL) | UD라 같은 REJOIN이 여러 번 옴; 생존 rank가 낡은 rkey를 쥠; 다른 QPN에 FAIL이면 떠도는 datagram 하나가 예비 프로세스를 그만두게 함(10193–10197) | 규칙 그대로 + 짝은 펜스 낱말 검사. 멱등 표는 REJOIN 종류에만, HELD 동안만; 받아들인 뒤 같은 QPN은 저장한 REJOIN_ACK만, 다른 QPN은 버리고 `GIN/LN` 줄(FAIL 아님); 예비 프로세스의 CONNECTED 전에는 그 QP로 보내지 않음 | 닫힘(설계 v3, 2026-10-17) | 4599–, 9213–9227, 13411–13421, 9632 |
| 계보 classify의 입력 | 페이지의 계보 보기를 입력으로 쓸까; FENCED를 국면으로 둘까 | 쓰지 않음. 입력은 기록의 칸 그대로. 펜스는 hold 칸 옆의 `fencedPlus1`(0 = 없음, i + 1 = 화신 i 펜스됨), 국면 값과 `gdakiLnViewOf`는 그대로, 보고 이름은 `gdakiLnFenceOf`(9.4절). 국면으로 넣으면 classify의 기본 행이 죽은 화신을 CURRENT로 봄(L:109). 계보 헤더는 바이트 그대로 | 닫힘(설계 v3, 2026-10-17) | 7050–7113, 14095, `rs_lineage_api.h` 11, 39, 109행, gin-mirror 9.9절 |
| 계보 상태 조건(HELD만, 거절된 rank에 FAIL, PUBLISHED류, 무장 조건) | 새 국면이 상태 조건을 지울까; 펜스 낱말의 0이 "화신 0 펜스됨"과 갈리지 않음(둘째 재검토의 막는 문제 1) | 국면을 더하지 않음. 짝의 활성화 결정과 짝의 REJOIN 받아들임에 "`fencedPlus1` = dead + 1"만 더함; 짝이 아닌 rank의 REJOIN에는 펜스 조건 없음. oracle 다름 목록은 관문 칸만 | 닫힘(설계 v3, 2026-10-17) | gin-mirror 9.9절 규칙 표 |
| 활성화 관문(`/proc`, Z = 끝남) | 옛 화신의 다른 스레드가 자원을 쥔 창 | FENCED 요구(펜스 국면). 빠른 모드 8/95 `[측정]`가 사라지고 관문 기다림이 launcher 보고로 | 닫힘(사용자 결정, 2026-10-16 저녁) | 4550–4592 |
| 멈춘 상대의 반응 | 판정 뒤 거절할까 되살릴까 | 펜스 뒤 복원, `NCCL_GIN_RESTORE_FENCE=none`으로 끌 수 있음 | 닫힘(사용자 결정, 2026-10-16 저녁) | 9.4절 |
| fork가 물려준 fd | 펜스 불변식의 구멍 | helper와 증인 소켓은 fork 때 닫음. uverbs fd까지 물려받은 셀은 셀 설정(예비 프로세스 없음)으로만 거절, 한계. launcher의 종료 보고가 곧 FENCED를 만들어 펜스로는 막지 못함 | 닫힘(결정 13, 2026-10-16; 설계 v2 6.4절) | 8135–8138 |
| 노드 죽음과 선 끊김의 구분 | RNIC 쪽에서 가를 수 없음 | 증인이 가름. 결과(복원 안 함)는 같고 원인 줄만 다름. 다른 노드 예비 프로세스가 생기면 다시 봄 | 닫힘(한계, 18절에 적을 것) | 9.3절 |
| READ 응답 없음의 시간(floor 규칙) | 감지 설계가 기대한 약 130 ms가 이 NIC에서 3.5–3.8 s | 노드와 선 판정(9.3절 10행)과 11행은 하드웨어 재시도 초과에만. READ 시한 500 ms는 의심과 보고만(17행), 시한은 FIN이나 RST와 겹친 확인 창 안에서만 판정에 듦(5행). floor 끄기는 하지 않음 | 닫힘(사용자 결정 (가), 2026-10-16 밤; 표는 설계 v3) | 9.3절; ack_timeout |
| 판정 표의 빠짐과 겹침(둘째 재검토의 막는 문제 2) | 입력 조합이 어느 행에도 들지 않거나 두 행에 듦; launcher 열의 값과 읽는 곳이 없음; 두 문서의 행 수가 다름(18, 20) | 입력 넷(L, B, W, R)의 값 목록과 첫 일치 21행(두 문서 같음), 21행에 닿는 점 0을 CPU 모형이 단언. "하드웨어 응답 없음 + 증인 꺼짐"은 launcher 무응답이면 거절(10행), 살아 있으나 정보 없음이면 펜스가 확인하는 hold(11행) | 닫힘(설계 v3, 2026-10-17); 11행을 둘지는 v3 목록 2 | 9.3절 |
| 한쪽만 오류인 기록 QP(둘째 재검토의 막는 문제 4) | 낮은 rank만 시작하면 높은 rank 쪽 오류가 돌아오지 않음; 기록 다시 맺기가 생존 READ를 끊음; RESET으로 다시 쓴 QP의 PSN이 그대로 | 어느 쪽이든 PAIR(종류, 세대 + 1)를 보내고 그것이 상대에게 주는 알림, 엇갈리면 낮은 rank(launcher와는 rank)가 이김; 기록 QP와 생존 READ QP를 따로 짝 맺음; 매번 새 PSN, 옛 세대 도착은 새 세대 소비 수에 안 듦 | 닫힘(설계 v3, 2026-10-17) | 9.1절; 16436–16440, 16516 |
| 무장 조건과 예비 프로세스(둘째 재검토의 고칠 것 8) | 설계 v2의 조건이 launcher만 있으면 참이라 예비 프로세스 없는 셀이 무장됨 | `haveSpare` = launcher 헤더의 `gl_path_exists`(자기 launcher와 CONNECTED, 등록 낱말 ALIVE, 예비 자리 HELLO 이상, 모든 launcher와 짝 맺음). `rg_nospare_failfast`는 fail-fast, `rg_spare_absent_fallback`은 rdma 빌드에서 fail-fast로 다시 예측; 무장 뒤 예비 프로세스가 사라지는 셀은 `gc4_kill3_ow_spareabsent` | 닫힘(설계 v3, 2026-10-17); 셀의 뜻은 v3 목록 6 | 9.5절, 14981 |
| 되살린 짝과 둘째 죽음(둘째 재검토의 고칠 것 14) | 되살린 rank를 짝으로 둔 rank가 짝의 launcher 짝 맺기 전에 무장됨 | 짝의 STORE_ACK 꼬리에 "w 노드 launcher와 짝 맺음" 비트, w는 그 뒤에만 무장. 둘째 kill이 다시 무장 줄 전이면 제외(8절) | 닫힘(설계 v3, 2026-10-17) | 9.5절 |
| launcher 고리의 credit, 봉투 크기, 말의 배치(둘째 재검토의 고칠 것 6, 7; launcher 프로그램) | launcher가 한 방향으로만 말할 때 credit이 돌아오지 않음; 봉투 칸 합 56 B | rank 페이지의 `rxConsumedL`과 launcher 페이지의 credit 칸, 자리는 PAIR의 `creditOff`; 봉투 64 B(`rsv[16]`). 배치는 빌드된 launcher 헤더(`launcher_msg.h`, 처음 빌드 판 md5 `30a05c7f`, 지금 `897641f3`)를 기준으로 함 | 닫힘(설계 v3, 2026-10-17) | 9.1, 9.2절 |
| 말의 화신과 pid 검사(둘째 재검토의 고칠 것 11, 12) | 같은 uid 다른 프로세스의 pidfd; 옛 화신이나 예비 등록의 끝남을 EXITED로 읽음 | pid 검사는 필수이고 끌 수 없음(launcher 그대로). EXITED, LEFT, FENCED는 (rank, 화신, nonce), CURRENT나 HELD_OLD만 씀. 예비 등록의 끝남은 활성화 답과 낱말로만 | 닫힘(설계 v3, 2026-10-17) | 9.5절 |
| helper만 멈춘 rank의 펜스(둘째 재검토의 고칠 것 15) | 살아 있는 프로세스를 helper 정체 하나로 펜스함; 셀과 예측이 없었음 | 9.3절 15행은 펜스 길(설계 기본), 셀 `gc4_helper_freeze12000`과 예측 `helper_stall_fence`를 둠. `helperBusy`를 세우는 자리 목록은 준비 단계 헤더 | 닫힘(2026-10-17 사용자 결정 1: 펜스 뒤 복원; 아래 v3 목록 1) | 9.3절, 3절 |
| 다른 실험의 고정 파일과 이 실험의 파일 자리(둘째 재검토의 고칠 것 2) | `mirror/impl/rs_*_api.h`를 고치면 gin-mirror의 `PREREG.txt` 5행(`mi_layer.diff` md5 `dcd30859`)과 api 검사가 깨짐 | 새 파일과 바뀐 헤더 사본(`rs_ctrl_api.h`, 판을 올린 `rs_store_api.h`)은 `impl/`에만, 계층 diff는 ln4 위의 따로 된 파일. 계보 헤더는 바꾸지 않음 | 닫힘(설계 v3, 2026-10-17) | 9.8절, `../mirror/PREREG.txt` |
| 감지 설계와 제어 경로 설계의 주인 다툼 | 제어 QP와 상태 페이지를 누가 만드나 | QP와 MR의 생성, 짝 맺기, 페이지 배치의 판은 제어 경로 몫. 페이지 칸의 뜻, READ 주기, 판정은 감지 몫. 준비 all-gather는 하나 | 닫힘(설계) | 9.1, 9.2절 |
| TCP 제어 길을 남길까 | 회귀와 옛 결과의 재현 | 컴파일 때의 빌드 스위치 `NCCL_GIN_CTRL_TCP=1`(`gct`)로 회귀용으로만, 아무것도 지우지 않음(4단계는 TCP 코드를 스위치 뒤로 묶기만). tcp 빌드는 옛 스택 전체(TCP 기록, TCP 활성화와 자료 소켓, FIN = 죽음, 거절 1 000 ms, `/proc` 관문, launcher 없음)를 회귀 팔로 되살리고, 전처리 결과가 ln4와 같은 것을 목표로 함(안 되는 자리는 목록). 두 빌드의 이름, md5, 장치 기계어 비교를 적음. tcp 대조 셀의 더함(RST 간격, `DIE_RST`, `RST_GAP`, `FD_HOLDER`의 helper 소켓 갈래)은 둘째 매크로 뒤의 `gctc`로(설계 v3 2.0절). 처음 설계 초안은 실행 시 env와 마지막 단계의 지움을 적어 결정과 어긋났음(리뷰) | 닫힘(결정 1, 2026-10-16; 설계 v2 2.0절; 둘째 매크로는 설계 v3, 2026-10-17) | 9.3, 9.8절 |
| 복원에 launcher가 반드시 있어야 하나 | 길이 둘이 됨 | 반드시 있음. 미리 띄운 예비 프로세스도 launcher를 거침 | 닫힘(결정 2, 2026-10-16) | 9.5절 |
| 노드 안의 말(rank, 예비 프로세스와 launcher) | TCP가 아닌 Unix 소켓을 쓸까 | Unix 소켓(fd 전달). 설계 v2의 해석: 등록은 pidfd를 SCM_RIGHTS로, `SO_PEERCRED`로 확인; 활성화 바이트와 "떠남"도 실음(9.5절의 말 목록) | 닫힘(결정 3, 2026-10-16); 해석은 설계 v2가 "사용자가 반대하지 않으면"으로 적음 | 9.5절 |
| 재생 전 활성화(동적 예비 프로세스의 앞 결정) | TCP listener의 LATER thread를 옮길 수 없음; LATER 뒤 한도의 기준점(둘째 재검토의 고칠 것 13) | launcher가 대신 LATER를 한 번. 이 실험의 launcher는 LATER 뒤 자기 한도가 없어 짝이 세고 넘으면 ABORT, launcher 박동 정체 `LAUNCHER_STALL_MS`면 launcher 잃음(9.5절). 한도는 1 000 ms, `LAUNCHER_STALL_MS`도 1 000 | 닫힘(결정 4, 2026-10-16; 틀은 설계 v3; 값은 2026-10-17 사용자 결정 4, 아래 v3 목록 4) | 9.5절 |
| mirror 끈 길의 TCP 자료 소켓(UPLOAD 증분, TCP FETCH; 2026-10-15 결정은 "그대로") | "모두 옮긴다"와 맞지 않음 | rdma 빌드에서 mirror 끔도 있는 RDMA 저장소 길 하나(늘 전체 이미지 WRITE와 FETCH QP의 READ; outbox로 보내지 않음). outbox는 STATE, rkey 목록, 활성화 덩어리만(2 × 1 MiB). 맡는 단계는 링과 기록 단계(9.8절). mirror 끈 회귀는 tcp 빌드로. 바뀌는 예측(`none_clean`, `rg_*`)은 3절, 메모리는 열린 것의 결정 대기 2 | 닫힘(결정 7, 2026-10-16; 설계 v2 2.3, 2.8절) | 15335–15420, gin-mirror 9.7절 |
| 소켓 시험 스위치(`SOCK_MUTE`, `LISTEN_GAP`, `SOCK_UTO_MS`) | rdma 빌드에서 무엇을 막나 | 증인만 막음. 8 s 끊김 셀은 "증인만 끊김"의 투명. RDMA 길의 끊김은 새 스위치(기록 QP 오류, UD 버림, credit 멈춤, 페이지 쓰기 멈춤; 연구 빌드만) | 닫힘(결정 8, 2026-10-16) | 17757, 12095 |
| UD datagram 크기 | 경로 MTU | MTU ≥ 2 048을 rdma 길의 조건으로(Resume 조건 42). 리뷰가 두 GIN 포트 `active_mtu` 4 096을 확인. 준비 때 rank마다 `ibv_query_port`로 검사, 준비 합의에 값, 시행 kv `active_mtu`에 기록 | 닫힘(결정 9, 2026-10-16; 설계 v2 2.5절) | 9.6절 |
| 저장소 기록 50, 51과 등록 꼬리 | 꼬리의 관리망 주소 | 50, 51은 링으로 바이트 그대로. 꼬리의 예비 등록은 launcher 경로, 판 번호 올림 | 닫힘(결정 10, 2026-10-16) | 17236–17247 |
| 활성화 대화(ACTIVATE, 답, FETCH 끝점, READY, DONE) | 활성화 연결 하나에 실리던 차례 | launcher 중계로 같은 차례 | 닫힘(결정 11, 2026-10-16) | 8876–8887 |
| 예비 띄우기 요청의 때 | launcher가 스스로 띄울까 | 짝의 hold 시작에서 SPAWN. 이 실험의 launcher는 "spawn not built"로 REFUSED, 실행과 셀은 gin-dynamic(4절) | 닫힘(결정 12, 2026-10-16) | 9.5절 |
| 긴 hold에서 생존 rank 사이 lane | hold 동안 체크포인트가 "a restore runs"로 거절되어 lane이 넘침(멈춤 펜스, launcher의 LATER 한도) | 이번에는 문서화한 한계: 예측은 DISARM이고 실패로 세지 않음(`long_hold_lane`). 설계 변경과 생존 rank끼리 주고받는 driver 셀은 gin-dynamic | 닫힘(결정 14, 2026-10-16) | 14873, gin-mirror 9.3절 |
| 저장소 올리기 QP, FETCH QP | 제어와 섞일까 | 섞지 않음(9.1절). FETCH 끝점 교환만 launcher 중계로 | 닫힘(설계) | 16405–16676 |
| mirror lane, MIRROR_SETUP(48) | 장치 길, helper 시작 전 기록 | 장치 그대로. 48은 준비 차례 (5)에서 링으로 | 닫힘(설계) | 695–716 |
| 비용 팔(off, on, mirror-self, mirror-peer) | 생존 READ와 credit READ가 같은 포트를 씀 | 비용 가족 probe를 따로 둠(READ 켬, 끔, tcp) | 측정으로 닫음 | 7절 |
| 체크포인트 입력 멈춤(≤ 16 ms, 학습 ≤ 20 ms) | 기록 왕복과 감시 스레드의 일이 바뀜 | 같은 상한을 두고 pilot에서 다시 봄 | 측정으로 닫음 | gin-mirror 3절 |
| 실행기(`run_mi.sh`의 예비 띄우기, 포트 고르기, 시작 문) | launcher가 띄우기를 맡음 | 실행기는 launcher를 띄우고 kill, 메타, 줄 모으기만. rdma 길에서 포트 고르기 없음 | 닫힘(시험 장치 일) | gin-mirror 9.8절 |
| 채점기의 줄("judged dead", "published", "restored as incarnation", "hold of rank … started", "armed", "disarmed", "is given up", `GIN/LN`) | 줄이 바뀌면 채점이 깨짐 | 줄 글자 그대로. 새 줄은 머리 `GIN/RC:` 하나, `why=` 꼴의 키 없음. 'later' 수와 `activate_ms`의 뜻이 바뀌므로 새 열 이름 | 닫힘(규칙) | `../mirror/impl/test/rows_mi.py` |
| 사전 등록된 gin-restore, gin-mirror 결과의 재현 | 새 빌드의 mirror 끈 길이 다른 길을 탐 | tcp 빌드가 옛 길을 그대로 지님(결정 1, 7). 끝난 실험의 결과와 해석은 바꾸지 않음 | 닫힘(결정 1, 7) | 두 실험의 `PREREG.txt` |
| net_ib 비동기 이벤트 스레드와 `ncclIbStats` | 새 QP와 CQ, UD QP의 이벤트 | 모두 자기 stats를 담. 셈이 0을 넘으면 그 QP는 오류로 침. UD QP를 RC처럼 세는지는 `[미확인]` | 닫힘(설계, 확인 하나 남음) | 16411–16435 |
| MR과 QP 접근 비트, GIN PD | 상대가 링이나 window에 쓸 수 있나 | 링 LOCAL_WRITE만, 페이지와 outbox REMOTE_READ만, 새 RC QP는 REMOTE_READ만(같은 GIN PD의 REMOTE_WRITE MR에는 rkey만 알면 어느 RC QP로든 쓸 수 있고 launcher는 다른 프로세스이므로) | 닫힘(설계 v2 2.1절) | 16513 |
| 정리 차례 | 늦은 READ, 늦은 SEND | 떠남 → BYE(완료를 봄) → 증인 BYE → QP 없앰 → MR 해제 → 메모리 해제(저장소 정리와 같은 꼴) | 닫힘(설계 v2 6.1절) | 17700–17745 |
| 감시 스레드 부하 | 20 µs 걸음에 READ와 페이지 쓰기, 생존 READ QP의 상태 바꿈 | 1 ms마다 쓰기, 100 ms마다 상대마다 READ와 CQ 걷기 하나, 상태 바꿈은 hold와 짝 맺기 때만(helper가 요청 낱말을 세우는 넘기기 규약). 펌웨어 명령 없음 | 닫힘(설계 v2 2.1절) | 1590–1640 |
| rain QUERY_QP 상한과 명령 slot | 새 QP가 QP 감시에 들어감 | 새 QP는 복원 QP 목록이 아니라 QUERY_QP 감시에 들지 않음. 펌웨어 명령은 준비 때 rank마다 대략 QP 9 × 4 + CQ 2 + MR 3, hold마다 2, 다시 짝 맺기마다 4로 셈에 넣음 `[설계 v2 2.1절, 추론]` | 닫힘(설계) | 16412 |
| 멈추기 전 생존 rank의 장치 대기 | 판정 전 10 s 동안 생존 rank의 커널이 멈춘 상대의 신호를 기다림 | 장치 hold 한도와 대기 시한이 10 300 ms보다 길어야 함. gpu-detect의 8 s 투명이 근거이고 10–12 s는 잰 적 없음 `[미확인]`. 채점하지 않는 pilot 셀 하나로 잼(9.9절 끝) | 열림(pilot 셀로 닫을 것) | gin-restore 9.2절 |
| 운영 빌드(`NCCL_GIN_TS_PRODUCTION`) | 시험 스위치 | 새 스위치도 그 빌드에서 빠짐(md5 비교) | 닫힘(설계) | 1283–1288 |
| fork 안전(`ibv_fork_init`, `RDMAV_FORK_SAFE`) | 등록 메모리와 fork | 준비 검사 43(`ibv_is_fork_initialized()`가 `IBV_FORK_UNNEEDED`가 아니면 fail-fast), 새 영역은 `MADV_DONTFORK`. rain 5.15, sunny 6.8에서 실제로 `IBV_FORK_UNNEEDED`가 돌아오는지는 `[미확인]` | 닫힘(설계 v2 5.1절, 확인 하나 남음) | 9.6절 |
| 제어 경로 설계의 독립 리뷰(2026-10-16) | 막는 문제 다섯(tcp 길의 범위, 결정 7의 길 둘, 원격 접근 오류 하나로 끝남, 정상 종료의 종료 보고, kill 판정 시각)과 고칠 것 스물하나(다시 짝 맺기의 credit과 자리, 유한한 rnr_retry, 받은 줄의 한도, SQ와 CQ 깊이, 접근 비트, 판정 입력의 정렬, helper 정체 행, REJOIN 내용, 되살린 rank의 launcher 등록, Unix 소켓에 실리는 말의 목록과 pidfd 넘기기, 떠남, 라운드 취소, 단계 사이의 기댐, fork 안전 검사 등) | 설계 v2(바뀐 것 스물일곱)가 모두 받았고 이 문서의 해당 자리에 접음(9.1–9.8절). 리뷰와 다르게 셈한 것은 kill 셀의 복원 시간 하나(3절 메모) | 닫힘(설계 v2); v2의 독립 재검토는 다음 행 | 9.8절 리뷰 확인점 |
| 설계 v2와 이 문서의 둘째 독립 재검토(2026-10-17) | 막는 문제 넷(펜스 낱말의 0, 판정 표의 빠짐과 겹침, 확인 창의 시각, 한쪽만 오류인 기록 QP의 다시 짝 맺기)과 고칠 것 열여덟, nit 열, 준비 단계와 launcher 절 | 설계 v3가 막는 문제 넷을 닫고 고칠 것 열여덟과 nit 열을 모두 접음(리뷰와 다르게 정한 것: EXITED와 박동 늚이 함께일 때 DISPUTE 대신 EXITED, 확인 창의 원격 접근 오류도 t_F + W에 판정). 이 문서의 해당 자리에 접음(2, 3, 7, 8, 9절) | 닫힘(설계 v3, 2026-10-17); 사용자 결정 목록은 아래 | 12절 넷째 행 |

**결정으로 닫은 충돌.** 2026-10-16 저녁의 사용자 결정(감지 신호는 상태 페이지 READ, 멈춘 상대는 펜스 뒤 복원, 펜스는 계보 국면, 관문은 FENCED, RST 0.1 s, fork fd는
한계, 종료는 launcher)과 21시 무렵의 결정 열넷(1절)이 위 표의 "결정" 행을 닫았다. 제어 경로 설계가 열린 충돌로 둔 열셋 가운데 열둘이 결정 1–12에 대응하고, 남은
하나(READ 응답 없음의 시간)는 설계 권고대로 적었으나 결정 목록에 따로 없어 사용자 확인을 기다린다(아래 결정 대기 1). 결정 13은 감지 설계의 fork fd 한계, 결정 14는 동적 예비
프로세스 리뷰의 lane 넘침이다.

**열린 것**(구현 전 닫아야 할 것은 2026-10-17까지 모두 닫혔고, 아래 3과 4는 사전 등록 전에 닫을 것; "충돌 먼저" 규칙). 설계 v2를 접은 뒤(2026-10-16) 남은 것이다. 처음 초안의 열린 것 가운데 판정 표의 빈칸(READ 응답 없음 + 증인
정상 + launcher 보고 없음)은 9.3절 표의 행으로 닫았고, 판정 전 장치 대기는 (2)로 옮겼다. 사용자 결정 14(긴 hold의 lane 넘침은 문서화한 한계, DISARM 예측)는 닫혀 있다.

1. **설계 v2의 독립 재검토**(설계 v2 7.5절 1번). 끝남(2026-10-17): 막는 문제 넷, 고칠 것 열여덟, nit 열. 첫 리뷰의 막는 문제 다섯 가운데 넷은 닫혔고 다섯째(kill 판정 시각과 W)는
   반만 닫혔다고 보았다. 설계 v3가 모두 받았고 이 문서에 접었다(위 표의 둘째 재검토 행, 12절 넷째 행).
2. **판정 전 10 s 동안 생존 rank의 장치 대기**: 채점하지 않는 pilot 셀로 잰다(9.9절 끝).

**사용자 결정(2026-10-16 밤, 메인 세션이 아래 넷과 어긋남 1을 권고와 함께 올리고 사용자가 모두 권고대로 정함).** 결정 대기 1은 (가), 2는 (가), 3은
거둠, 4는 셀을 넣되 gin-dynamic에서(이 실험의 셀은 예비 프로세스가 미리 떠 있어 긴 hold가 없음). 어긋남 1은 메인 세션의 해석대로: 간격 매개변수는 tcp 빌드에만 두고
기본값 1 000(옛 동작, 전처리 동일 목표 유지), RST 셀만 100으로 돌린다. 저녁 결정 "0.1 s"는 RST 셀의 값으로 남는다. 같은 때 사용자가 "에이전트 3개"로 다음 묶음을
정했다: 설계 v2와 이 문서의 독립 재검토, 준비 단계(갈아 끼우는 자리), launcher 프로그램을 함께 시작하고, 1단계와 2단계는 재검토의 막는 문제를 접은 뒤 시작한다
(아래 9.8절의 "코드 전 재검토" 확인점은 1단계와 2단계에 적용). 아래는 결정 전의 기록이다.

- **결정 대기 1. floor 규칙과 확인 창 W**(설계 v2 6.3절 1번). 이 NIC에서 READ의 응답 없음은 3.5–3.8 s다. 안 (가): 노드와 선 판정은 하드웨어 재시도 초과, FIN이나 RST, launcher
  보고에만 기대고, 소프트웨어 시한은 FIN이나 RST와 겹친 확인 창 W 안에서만 판정에 들며 그 밖에서는 의심과 보고뿐이다. W는 20–50 ms 사이에서 1단계 pilot의 장애 없는
  `watchBeat` 간격 최대의 5배 이상으로 고정한다. 안 (나): 소프트웨어 시한(500 ms)만으로도 노드와 선을 판정한다(FIN 없는 노드 죽음을 약 0.5 s에 잡지만 데이터 QP가 견뎠을
  짧은 RNIC 끊김을 죽음으로 볼 수 있음). floor 끄기는 NIC function 전체 설정이라 어느 안에도 없다. **권고: (가)**(설계 v2). 확인 창은 FIN이 있을 때만 열리므로 FIN 없는
  RNIC 끊김에는 닿지 않고 판정이 데이터 길보다 먼저 서지 않는다.
- **결정 대기 2. gin-restore의 비용 한도 "4 rank에서 rank마다 더하는 메모리 ≤ 64 MiB"가 호스트 고정 메모리에도 드는가**(설계 v2 6.3절 2번). 사용자 결정 7로 mirror 끈 rank가 올리기
  버퍼와 짝으로서 맡은 저장소 두 칸 때문에 약 3I + 5 MiB를 더 쥔다(I = 20 MiB면 약 65 MiB) `[설계 v2 3.5절, 추론]`. 그 한도는 gin-restore가 제안하고 사용자 확인을 기다리는
  것이다. 안 (가): 한도는 BAR1과 장치 메모리의 것이고(제안 글의 "rain BAR1의 4분의 1") 호스트 저장소는 넣지 않고 쓴 양만 보고한다. 안 (나): 호스트 고정 메모리도 들고, 그러면
  mirror 끔 저장소를 한 칸으로 줄이는 설계를 더 해야 한다. **권고: (가)**(설계 v2). 한도 글이 BAR1에 묶여 있고 gin-mirror가 이미 호스트 pool 수백 MiB를 쓴다.
- **결정 대기 3. 앞선 결정 "복원 중 'a restore runs' 거절은 남긴 당기기의 시도 수를 쓰지 않음"(동적 예비 프로세스 설계의 앞 결정 (2)(나))을 거둘까**(동적 예비 프로세스 설계 v2
  5.2절 3번). 그 코드 바뀜은 hold 안의 lane 넘침을 막지 못하고, 효과가 있는 띠(4 KiB hold 약 1.6–1.7 s)에 드는 계획 셀이 없다 `[설계 v2, 추론]`. **권고: 거둠(그 코드
  바뀜을 빼기)**(동적 예비 프로세스 설계 v2). 2026-10-16 저녁의 "추천대로"를 뒤집는 것이라 사용자 확인이 필요하다.
- **결정 대기 4. 생존 rank끼리 hold 동안에도 계속 주고받는 셀을 둘까**(동적 예비 프로세스 설계 v2 5.2절 7번). 새 driver 작업 80–140줄이 들고, 빼면 긴 hold의 lane 한계는
  계산으로만 적힌다. 동적 예비 프로세스 설계 v2는 그 셀 하나(3 시행)를 gin-dynamic 계획에 넣고 열린 것으로 둔다. **권고: 이 실험에는 넣지 않음**(사용자 결정 14가 그 driver
  셀을 gin-dynamic으로 보냄); 둘지는 gin-dynamic 사전 등록 전에 정한다.
- **어긋남 1(보고만, 결정을 바꾸지 않음).** 2026-10-16 저녁의 사용자 결정 "RST 뒤 거절 간격 0.1 s"와 설계 v2 2.0절의 "tcp 빌드는 옛 동작 전체, 전처리 결과가 ln4와
  같은 것이 목표"가 부딪친다: rdma 빌드에는 그 간격이 필요 없고(RST가 확인 창을 부름), tcp 빌드에 매개변수를 두면 동일 목표의 예외가 되며, 기본값을 100으로 두면 tcp
  빌드가 옛 동작이 아니다. 이 문서는 매개변수를 tcp 빌드에만 두고 회귀 셀 1 000, RST 셀 100으로 적었다(9.3절). 기본값과 결정의 뜻은 사용자에게 올린다.

위 결정으로 모두 닫혔다(2026-10-16 밤).

**설계 v3가 사용자에게 올리는 것**(2026-10-17; 설계 v3 6.3절 끝과 같은 목록. 이 문서와 설계는 정하지 않고, 괄호는 지금 적어 둔 기본이다. 사전 등록 전에 닫는다).
1. **helper만 멈춘 rank를 펜스할까**(9.3절 15행). `watchBeat`는 오르고 `helperBeat`만 10 000 ms 넘게 선 프로세스는 살아 있다. (기본: 14행과 같은 펜스 뒤 복원; 셀
   `gc4_helper_freeze12000`, 예측 `helper_stall_fence`.) 다른 안은 거절만이다. 2026-10-16 저녁 결정은 "멈춘 상대"만 다뤘다.
2. **9.3절 11행을 둘까.** 증인 꺼짐 + launcher 정보 없음 + 하드웨어 응답 없음을 끝남(NORESP)으로 보고 펜스가 확인하게 하는 행이다. 운영에서는 생기지 않고 `NO_EXIT_REPORT` 셀이 탄다.
   (기본: 둠; `finless_read_fail`은 kill 뒤 3.5–4.5 s 판정, 복원 성공.) 다른 안은 둘째 재검토가 적은 대로 "노드 닿지 않음, 거절"로 두고 그 셀을 거절 예측으로 바꾸는 것이다.
3. **launcher 페이지와 REG_NOTE의 EXITED 상태를 끝남으로 칠까**(9.2절). (기본: 치지 않음; 끝남은 EXITED, FENCED 말로만.) 빌드된 launcher의 `NO_EXIT_REPORT`는 EXITED 말만 끄므로, 낱말을
   끝남으로 치면 그 셀이 REG_NOTE로 kill 뒤 약 0.1–0.2 s에 판정되어 READ 실패의 길을 재지 못한다. 다른 안은 낱말도 끝남으로 치고 `finless_read_fail`을 빼거나 launcher 스위치를 넓히는 것이다.
4. **LATER 뒤 한도의 값**(9.5절). 이 실험의 launcher는 LATER 뒤 자기 한도가 없고, 짝이 세어 넘으면 ABORT를 보낸다. 후보: (가) 짝이 LATER를 받은 때부터 5 000 ms, (나) LATER에 실린
   예비 프로세스의 나이를 더해 HELLO부터 5 000 ms, (다) 옛 TCP 길과 같은 1 000 ms. 조율 세션의 권고는 (다)다(이 실험의 예비 프로세스는 미리 떠 있고, 실험은 지금보다 나쁘지 않음을
   약속하며, 예비 프로세스를 띄우는 gin-dynamic이 그 값을 올림). `LAUNCHER_STALL_MS`(초안 1 000)도 함께 정한다.
5. **확인 창 READ 사이의 여유**(9.3절). 결정 (가)의 "W ≥ 5 × 장애 없는 `watchBeat` 간격 최대"에서 READ1과 READ2 사이는 W/2라 여유가 2.5배다. (기본: 결정 그대로.) 다른 안은 W ≥ 10 ×
   간격 최대(20–50 ms 안에서)다.
6. **예비 프로세스 없음 셀의 뜻**(3절, 7절). 무장 조건이 예비 자리 HELLO를 요구하면 gin-mirror의 `rs4_kill3_spareabsent`는 rdma 빌드에서 무장 없음 fail-fast가 된다. (기본: 그 회귀
   예측을 fail-fast로 다시 쓰고, "무장됐으나 활성화 때 없음"은 `gc4_kill3_ow_spareabsent`가 실행기의 예비 프로세스 kill로 잼.)
7. **EXITED와 박동 늚이 함께일 때**(9.3절). 둘째 재검토는 DISPUTE(hold 없음)를 제안했고 설계 v3는 EXITED가 이기게 두었다. 리뷰와 다르게 정한 것이라 확인을 받는다.
8. **저녁 결정 "펜스는 계보의 국면 하나"의 읽기**(9.4절). 설계 v3는 계보의 국면 값을 더하지 않고 HOLD_WAIT 안의 보고 이름(FENCING, FENCED)과 hold 칸 옆의 펜스 낱말로 나타낸다(국면 값을
   더하면 classify가 죽은 화신을 CURRENT로 봄). 결정의 뜻과 맞는지 확인을 받는다.

**사용자 결정(2026-10-17 새벽, "추천대로"; 조율 세션이 위 여덟을 권고와 함께 올림).** 1 펜스 뒤 복원(기본대로). 2 11행을 둠. 3 페이지와 REG_NOTE의 EXITED 낱말은 끝남이 아님(끝남은 EXITED, FENCED 말로만). 4 (다) LATER 뒤 한도 1 000 ms(`NCCL_GIN_CTRL_LATER_MS`), `LAUNCHER_STALL_MS`도 1 000. 5 W ≥ 10 × 장애 없는 `watchBeat` 간격 최대(20–50 ms 안에서; READ1과 READ2 사이 여유 5배). 6 기본대로(`rs4_kill3_spareabsent`는 fail-fast로 다시 예측, 활성화 때 없음은 `gc4_kill3_ow_spareabsent`). 7 EXITED가 이김. 8 보고 이름으로 읽음. 1단계 구현은 이 값을 기본으로 둔다(각 항목이 표 한 행이나 매개변수 하나).

남은 열린 것은 (2) 판정 전 장치 대기의 pilot 셀과, 2026-10-17 시험 쪽 리뷰가 사전 등록 전 결정으로 남긴 아래 둘이다.

3. **FENCE_NAK이 난 시행을 제외로 칠지 실패로 셀지**(8절 채점 규칙). 그 줄은 STOP_launcher로 hold를 멈추게 하지만, 그 시행 자체의 판정은 정하지 않았다. 지금 채점기는 그 시행을 센다.
4. **멈춤 길이 허용 1 s를 좁힐지**(8절 제외; 시험 쪽 리뷰 nit 7). 1 500 ms 멈춤에 1 s 허용은 넓다. 리뷰 권고는 50 ms다.

**이 문서의 선택**(독립 리뷰가 볼 것).

| 설계 | 상태 |
|---|---|
| tcp 빌드는 상태 페이지, launcher, 펜스 없이 옛 TCP 제어 스택 전체(gin-mirror의 뜻). 컴파일 때 스위치 `NCCL_GIN_CTRL_TCP=1`. RST 뒤 거절 간격과 tcp 대조 셀의 시험 스위치는 둘째 매크로 뒤의 `gctc`로만(기본 1 000, RST 셀만 100) | 설계 v3 2.0절과 같음. 간격 기본값은 2026-10-16 밤 결정 |
| kill → 판정 예측을 늘 t_F + W로(원인 FIN+STALE, FIN+NORESP, REMACC+FIN), 창이 "확인 못함"이면 EXITED의 시각을 따로 둠 | 설계 v3 4.2, 4.6절; W 값만 `[초안]` |
| `gc4_fdhold_sock_kill3_noreport`는 증인도 꺼서 9.3절 11행(증인 꺼짐 + launcher 정보 없음 + 하드웨어 응답 없음 → 펜스가 확인하는 hold)을 탐(증인을 켜면 12행이라 hold 없음) | 설계 v3 4.2절; 11행을 둘지는 위 v3 목록 2 |
| 동적 예비 프로세스의 셀은 이 실험에서 돌리지 않음. launcher는 노드 안 인사, 준비됨, 재생 실패 알림의 규약까지 만들고 SPAWN은 "spawn not built"로 REFUSED | 동적 예비 프로세스 설계 v2 5.2절 1번의 권고를 이 문서의 선택으로 씀(4절) |
| 비용 셀의 READ 켬과 끔을 같은 rdma 바이너리의 `NCCL_GIN_TS_PROBE_MS=0`으로 가름(tcp와 rdma는 빌드로만 가름) | 이 문서의 선택 |
| `r->ctrl`(제어 계층 상태)을 `gdakiTsSetup`의 all-gather 바로 앞에서 만들고, 링과 UD 끝점도 그 자리에서 만듦(설계 v3는 연결 부분 `gdakiTsSetupConnect` 안). UD 끝점과 페이지, outbox 자리를 all-gather 칸에 실으려면 그것들이 all-gather 전에 있어야 하기 때문(9.6절) | 이 문서의 선택(2026-10-17 통합 때). `r->ctrl`은 통합 트리에서 그 자리에 있고, 링과 UD QP를 거기서 만드는 것은 2a-2 |

### 9.8 이행 단계와 병렬 나눔 (구현 전)

열린 것(9.7절 끝)의 결정 대기는 2026-10-16 밤 사용자 결정으로 닫혔고, 둘째 독립 재검토(2026-10-17)의 막는 문제 넷은 설계 v3로 닫혔다. 준비 단계와 3단계의 launcher 프로그램은 재검토와 함께
시작했고(launcher는 2026-10-17 빌드됨), 1단계와 2단계는 설계 v3를 접은 이 문서 위에서 시작한다. 장치 코드는 2c(더러운 segment 표시)를 빼고 모든 단계에서 0줄이다. 처음 초안은 "모든 단계 0줄"을 목표로 두었으나 2026-10-17 사용자가 "최대한 외부 코드 말고 내부를 수정"하는 쪽을 택해, mirror 끈 rank의 체크포인트 멈춤(전체 이미지 복사, 모형 2.25배)을 장치 쪽 segment 비트로 줄인다. 장치 동일성 검사는 "매크로 없는 프로그램은 ln4와 같음, 매크로 있는 장치 객체는 비트맵 차이만"으로 바뀐다. 원칙: 먼저 공유 헤더와 전송을 갈아 끼우는 자리를
만들고, 그 뒤 서로 다른 함수만 고치는 세 단계를 따로 된 에이전트가 함께 구현하고, 마지막 단계는 셋을 합친 뒤에 한다.

| 단계 | 혼자 고치는 함수와 파일 | 부르기만 하는 것 | 크기 `[설계 v2, 추론]` |
|---|---|---|---|
| 준비(갈아 끼우는 자리) | 공유 헤더 `impl/rs_ctrl_api.h`(봉투 64 B와 `rsv[16]`(칸마다의 위치를 launcher 헤더와 `static_assert`로 같게), 페이지 낱말과 `rxConsumedL`, 끝점 판 2(40 B), PAIR 종류(기록, 생존 READ)와 본문(launcher 헤더의 `glPairBody` 112 B, `creditOff` 포함), 기록 52–55, launcher 말(launcher 헤더 `launcher_msg.h`를 포함: 열일곱 종류, 256 B; EXITED, LEFT, FENCED는 (rank, 화신, nonce); SPAWN 거절과 활성화 답은 다른 종류), Unix 소켓 말 일곱 종류, 매개변수 이름, `fencedPlus1` 상수와 `gdakiLnFenceOf`, 판정 입력 값과 판정 함수의 서명, 확인 창의 결과 값 다섯, REJOIN과 REJOIN_ACK의 `nrp` 배치(비어 있음 확인), `helperBusy`를 세우는 자리 목록, 바깥 CQ의 수명 규칙; `static_assert`로 봉투 64 B, 끝점 40 B, launcher 말 256 B, 판정 낱말과 launcher 페이지 낱말의 8 B 정렬, `nrp` 배치 ≤ 256 B) `[설계 v3 7.1절]`; `NCCL_GIN_CTRL_TCP`와 둘째 매크로 `NCCL_GIN_CTRL_TCP_CELLS` 뼈대; `gdakiTsSend`, `gdakiTsPump`, `gdakiHoldSend` 호출 26 + 7 + 17곳을 자리마다 (증인, 기록, 자료, REJOIN, 활성화)로 가른 표와 함께 `gdakiCtrlSend`, `gdakiCtrlPump`로(`gdakiTsSend` 26곳 = 정의 1, 증인 7(8173, 8498, 8609, 8711, 8798, 8843, 18130; rdma 빌드에서도 증인 소켓), 자료 2(14251, 15643), REJOIN 2(9571, 10192), 기록 14(10295의 READY는 기록; 설계 v3 7.1절의 REJOIN 3, 기록 13을 자리 표 `impl/gc_sites.tsv`대로 고침, 준비 단계 리뷰 nit 16) `[소스: grep]`; tcp 빌드에서는 모두 지금 호출로 펴짐); `pe.fd` 56곳을 증인으로 남을 자리와 기록 길로 갈 자리로 가른 목록과 바꿈; `gdakiMiHostQpCreate` 인자 넓힘(SQ와 RQ 깊이, 접근 비트, QP 종류, timeout, rnr_retry, 바깥 CQ, completion channel, UD Q_Key; 기본 인자는 지금 값); `gdakiTsSetup`을 all-gather와 연결(`gdakiTsSetupConnect`)로; `gdakiRsSpareRun`을 활성화 기다림(`gdakiRsSpareActivateWait`)과 REJOIN(`gdakiRsSpareRejoinAll`)으로; `gdakiHoldActivate`를 결정과 보내기로; 생존 READ QP의 API(만들기, 끝점 내기, 기록과 따로 된 잇기와 다시 잇기, 오류 상태로, "이 세대에서 성공함" 조회); 빈 hook `gdakiCtrlOnHoldStart`, `gdakiCtrlLauncherSend`, `gdakiCtrlPeerToErr`, `gdakiLnFenced` | – | C++ 약 600–800, 헤더 약 250 |
| 1 상태 페이지, READ 감지, 펜스 | 새 `gdakiPage*`, `gdakiProbe*`(감시 스레드의 READ, 걷기, 상태 바꿈, 넘기기); 감시 스레드 hook 한 줄; 판정 표(21행)와 확인 창(t_F, t_F + W/2, t_F + W); `gdakiHoldStart`의 펜스 갈래(1단계는 멈춤 판정을 거절만); 52–54 처리; 펜스 낱말 `fencedPlus1`과 `gdakiLnFenced`(계보 헤더는 그대로); 관문 `gdakiRsActExamine`(launcher와 짝을 맺은 문맥에서만 FENCED, 없으면 `/proc`); 55번 PROBE_SETUP(이름 붙인 개발 발판: 생존 READ QP 끝점을 helper TCP 소켓으로 나눔, 2단계가 합쳐지면 55번과 함께 사라짐); `gdakiProbeToErr`; launcher 페이지 끌어 읽기(감시 스레드, 그 launcher와의 생존 READ QP); 시험 스위치 `DIE_RST`, `RST_GAP`, `FD_HOLDER`, `FREEZE_PAGE`(`<ms>:helper` 갈래 포함)와 tcp 대조의 RST 간격(둘째 매크로 뒤) | `gdakiCtrlSend`, `gdakiCtrlLauncherSend`(3단계 전에는 빈 것) | C++ 약 1 000–1 200 |
| 2 링과 기록, mirror 끔 저장소 | rdma 뒤끝 `gdakiCtrlRdma*`(QP, 링, credit과 세대, inbox 한도, completion channel, outbox); `gdakiTsSetupConnect`의 짝 맺기와 MTU, fork 검사; `gdakiTsReconnectStep`의 기록 길(어느 쪽이든 시작하는 PAIR(종류, 세대 + 1), 기록과 생존 READ를 따로, 매번 새 PSN, launcher가 시작한 PAIR 받기); `gdakiRsSpareRejoinAll`(UD REJOIN, `nrp`의 새 끝점과 rkey, REJOIN 멱등 표와 다른 QPN 버림, CONNECTED 전 보내기 없음); `gdakiRsLogExport`의 받는 곳(outbox)과 예비 프로세스의 STATE 받기; `gdakiTsCloseAll`의 BYE 차례; `gdakiCtrlRecordToErr`; 시험 스위치 `QP_ERR`, `DROP_UD`, `CREDIT_STALL`; 결정 7(`gdakiStoreOn`을 mirror 끔으로 넓힘, mirror 끈 올리기와 FETCH를 저장소로, 덩어리의 저장소 칸, `gdakiStoreWardToErr`) | 페이지의 `rxConsumed` 낱말(배치는 준비 단계가 고정) | C++ 약 1 500–1 900 |
| 3 launcher, 등록, 활성화 | launcher 프로그램(`impl/launcher/`, 2026-10-17 빌드됨: C, Unix 소켓, 끌 수 없는 pid 검사, pidfd, verbs, launcher 페이지, EXITED, LEFT, FENCE, FENCED, FENCE_NAK, 한 사건 한 말, launcher가 시작하는 다시 짝 맺기, 중계, ABORT, SPAWN은 따로 된 REFUSED, 시험 스위치 `NO_EXIT_REPORT`); rank 쪽이 지킬 것(SPARE_HELLO의 0 아닌 nonce, 등록 연결은 CLOEXEC이고 fork 때 닫으며 LEAVING은 그 연결로만, launcher 기록 QP의 `max_dest_rd_atomic` ≥ 1과 outbox REMOTE_READ, REFUSED 종류로 fallback하지 않음); rank 쪽 `gdakiCtrlLauncher*`(떠남 알림 포함); `gdakiCkptSelfOf`의 경로; STORE_REQ 꼬리(17236–17247); `gdakiHoldActivateSend`; `gdakiRsSpareActivateWait`; 무장 조건(`haveSpare` = launcher 헤더의 `gl_path_exists`); 되살린 rank의 launcher 짝 맺기와 다시 무장, 되살린 짝의 STORE_ACK 비트; LATER 뒤 짝의 한도와 ABORT, launcher 박동 감시; FENCE_NAK에 fallback; 실행기(launcher pid와 시작 시각을 시행 앞뒤로)와 채점기 | `gdakiCtrlSend`, 2단계의 UD 짝 맺기 API, 1단계의 `gdakiLnFenced` | 라이브러리 약 500–700, launcher 약 700–900, 실행기와 채점 약 300 |
| 4 TCP를 스위치 뒤로(합친 뒤) | 남은 TCP 전용 코드(TCP 자료 소켓, 활성화 소켓, FIN = 죽음, 거절 1 000 ms, `/proc` 관문)를 지우지 않고 `NCCL_GIN_CTRL_TCP` 뒤로 묶음(결정 1). rdma 빌드에는 증인 코드만 남음. 두 빌드의 회귀 | – | 묶는 바꿈 약 300–500, 지움 없음 |

**단계마다 지금 상태**(2026-10-17 끝; 근거는 12절의 행과 각 노트, 이 문서는 빌드와 시험을 다시 돌리지 않았다). 단계 2는 2a-1(링과 짝 맺기 모형, verbs 뒤끝을 빌드만), 2a-2(호출 자리 연결),
2b(mirror 끈 저장소와 2단계 시험 스위치)로 나눴다(12절).

| 단계 | 상태 | 근거 |
|---|---|---|
| 준비 | 리뷰(막는 문제 2, 고칠 것 15, nit 16)를 고침. `impl/gc_layer.diff` `0df79ae2` | `impl/notes_prepfix.md`, 커밋 `fd4ae2d6` |
| 1 | 고친 준비 단계 위에 통합됨. 코드 리뷰의 막는 문제 여섯(확인 창과 PROBE_SETUP 보내기의 부르는 곳 0, 생존 READ 버퍼 공유, 분할 막이의 뜻 거꾸로, 시한 뒤 READ 재발행, 오류 CQE 분류, 감시 스레드의 helper 전용 호출)은 열려 있고 고치는 중. 1단계 몫 시험 스위치(`DIE_RST`, `RST_GAP`, `FD_HOLDER`, `FREEZE_PAGE`)는 아직 0건 | `impl/notes_int.md`, `REVIEW_P12.md`(저장소 밖) |
| 2a-1 | 통합됨. 막는 문제 둘(짝 맺기 모형에 HELD와 계보 입력 없음, 세대 바뀜이 ACK된 기록을 버리고 라운드 취소가 없음)은 열려 있고 고치는 중. 모형과 뒤끝은 살아 있는 길에서 부르는 곳 0 | 같음 |
| 2b | 진행 중 | 조율 세션 |
| 2a-2, 3(rank 쪽) | 다음. 2a-2는 2a-1의 막는 문제 둘을 먼저 닫은 뒤 묶음 | `impl/notes_int.md` 끝 |
| 3(launcher 프로그램) | 빌드됨, 리뷰를 고침, 단위 시험 20 장면 414 검사(verbs 전송은 빌드만) | `impl/launcher/README_launcher.md`, `impl/notes_prepfix.md` |
| 4 | 시작 전 | – |

- **트리 키**(`impl/build_gc.sh`의 `BR=`; 빌드 키 `gc`, `gct` 같은 것과 다름). `prep`는 고친 준비 단계 트리. `p1`, `p2`는 1단계와 2a-1을 옛 준비 단계(`f5061a31`) 위에서 처음 빌드한 그대로의
  기록이고(입력은 고정 사본, 시험 소스는 커밋 `73be8802`, `494cd666`의 것), 통합 때 키만 넣고 돌리지 않았다 `[미확인]`. `int`는 고친 준비 단계 위에 1단계와 2a-1을 합친 통합 트리이고
  그 diff가 `impl/gc_layer_int.diff`(`a7600a46`, ln4 대비 4 312줄, 호스트 파일 하나)다. 고침과 다음 단계는 `int` 트리 위에서 한다.
- **`gctc`의 전처리 결과.** 통합 트리에서 `gct`, `gctp`는 ln4와 0 hunk이고, `gctc`는 1단계의 RST 거절 간격 매개변수만큼(2 hunk 3줄: 매개변수 정의 한 줄, `>= 1000.0`이 그 매개변수가 된 한 줄)
  다르다. 둘째 매크로가 그 코드만 켜도록 정한 대로다(9.3절) `[측정: 통합 에이전트의 보고 impl/notes_int.md, pre_int.log; 이 문서에서 다시 돌리지 않음]`.

- 처음 제어 경로 설계는 마지막 단계에서 tcp 갈래를 지우는 안을 두었으나 결정 1로 지우지 않고 빌드 스위치 뒤에 둔다. tcp 빌드(`gct`)의 동일성은 매 단계 확인한다.
- **파일 자리**(둘째 재검토의 고칠 것 2) `[설계 v3 7.1절]`. 새 파일과 바뀐 헤더 사본(`rs_ctrl_api.h`, 판을 올린 `rs_store_api.h`)은 모두 이 폴더의 `impl/`에 두고, 이 실험의 계층
  diff는 ln4 위의 따로 된 파일(`impl/gc_layer.diff`)로 만든다. gin-mirror의 `PREREG.txt` 5행이 고정한 `../mirror/impl/mi_layer.diff`(md5 `dcd30859`)는 `../mirror/impl/rs_*_api.h`를
  바이트 그대로 붙인 것이라(`build_mi.sh api` 검사) `../mirror/impl/*`와 그 diff는 읽기만 한다. 계보 헤더 `rs_lineage_api.h`는 바꾸지 않는다(9.4절).
- **시험 스위치와 주인 단계**(둘째 재검토의 고칠 것 3) `[설계 v3 7.1절]`. 1단계: `NCCL_GIN_TS_TEST_DIE_RST`, `..._RST_GAP`, `..._FD_HOLDER`(rdma는 증인 소켓, tcp 대조는 helper
  소켓 갈래를 둘째 매크로 뒤에), `..._FREEZE_PAGE`(`<ms>`는 두 박동, `<ms>:helper`는 `helperBeat`만), tcp 대조의 `NCCL_GIN_TS_RST_REFUSAL_GAP_MS`(둘째 매크로 뒤). 2단계:
  `NCCL_GIN_CTRL_TEST_QP_ERR`, `..._DROP_UD`, `..._CREDIT_STALL`. 3단계: `NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT`(launcher 쪽, EXITED 말만 끔). 모두 연구 빌드만이고 운영 빌드에서 빠진다.
- **단계 사이의 기댐**(설계 v2 7.1절). (1) FENCED를 만드는 것은 launcher(3단계)라 1단계는 멈춤 판정을 거절만 하고(`FENCE=none`처럼), FENCED 관문은 launcher와 짝을 맺은
  문맥에서만 켠다. 3단계가 합쳐지면 켜진다. (2) 생존 READ QP의 생성과 감시는 1단계, 짝 맺기는 2단계라, 그 사이 1단계 개발 빌드는 55번 PROBE_SETUP을 helper TCP 소켓으로
  나눈다. 이것은 "라이브러리 내부 통신은 RDMA 먼저"의 이름 붙인 예외(1단계 개발 발판)이고 2단계가 합쳐지면 사라진다. (3) 1단계와 3단계의 개발 빌드는 2단계 전까지 갈아
  끼우는 자리의 TCP 뒤끝으로 기록을 나르는 섞인 빌드다. 그 빌드의 pilot은 새 판정 규칙을 보는 개발 자료이고 회귀 증거가 아니다. 회귀 증거는 tcp 빌드에서만 낸다.
- **CPU 단위 모형.** 준비: 같은 기록 열을 tcp 뒤끝으로 보내 받은 바이트가 지금 함수와 같음, 기존 단위 시험(`rs_unit_host.cc`, `rs_spare_unit.cc`, `mi_unit_spare.cc`,
  `mi_unit_lineage.cc`, `mi_unit_store.cc`, `mi_unit_host.cc`)이 두 빌드에서 고침 없이 통과. 상태 페이지와 펜스: 판정 낱말 모형(정렬된 8 B만 읽음), 보고 줄의 줄 안
  seqlock 모형(쓰는 thread와 무작위로 끼어드는 읽기, 짝수 `ver` 줄의 찢김 0), 정체 정의 모형(읽는 쪽이 멈춘 경우 포함, 분할 막이 문턱), 판정 함수를 입력 격자 1 170점 전부로
  (21행에 닿는 점 0, 모든 행 한 점 이상, floor 성질), 확인 창 모형(READ 완료 시각을 무작위로; 판정이 늘 t_F + W, "확인 못함"의 조건), 펜스 낱말 모형(9.4절의 장면; 이 실험의 단위
  시험, 계보 oracle의 다름 목록이 관문 칸만), `gate_fenced` CPU 프로그램(3절 예측; 그 시험은 실제 자식 프로세스의 `impl/test/gate_proc_gc.py`이고, 지금 `impl/gate_fenced.cc`는 넣은 값을 되읽는 시간표 모형이라 예측의 시험이 아님). 링: credit 모형(무작위 묶음과 다시 내기, 세대 바뀜: 낸 RECV ≥ 날아가는
  SEND, 옛 세대 CQE 버림, 세대 안 잃음과 겹침 0), inbox 한도 모형, UD 짝 맺기 모형(잃음, 겹침, 차례 바뀜, 옛 화신; 높은 rank만 오류, 한쪽만 오류인 쉬는 쌍, 두 쪽이 엇갈려 PAIR(g + 1), 기록 다시 맺기 동안 생존 READ QP는 그대로, 매번
  새 PSN, 옛 세대 도착이 새 세대 소비 수에 안 듦; REJOIN: 받아들인 뒤 같은 QPN은 저장한 답만, 다른 QPN은 버림, CONNECTED 전 보내기 없음), 같은 사건 열에서 넘겨진 기록 열이
  TCP 모형과 같음, park 동일, mirror 끔 저장소 모형(`mi_unit_store.cc` 넓힘). launcher: 상태 기계 모형(LATER, 예비 프로세스 끝남, FENCE와 EXITED의 엇갈림, LEFT와 BYE의
  엇갈림, 같은 화신 둘째 접속, 남의 pidfd에 신호 없음, SPAWN의 "spawn not built" 답), 등록 oracle(경로가 있으면 지금 무장 판단과 같음), 동적 예비 프로세스 리뷰가 찾은 경쟁
  셋(넘기기 틈, 일찍 답하는 thread의 상한, 잃는 ACCEPTED)의 장면. launcher 단위 시험은 2026-10-17에 돌았다: 장면 18개, 검사 418개, 4/4 실행 통과(ASan, UBSan; 프로세스 안 시험 전송과
  스스로 fork한 자식만; verbs 전송은 빌드만 하고 돌리지 않음) `[측정: 조율 세션의 보고와 impl/launcher/README_launcher.md; 이 문서에서 다시 돌리지 않음]`.
- **동일성 확인(매 단계).** 장치 기계어 비교(매크로 없는 프로그램 넷과 라이브러리 장치 객체가 `mi`와 같음, gin-mirror의 방법), tcp 빌드의 pilot 회귀 묶음
  (`mi4_kill3_ow`, `mi4_kill2_kill3_ow`, `rs4_kill3`, `rs4_kill3_spareabsent`, `mi4_none_ow`)의 판정과 줄 수가 ln4 본 실행과 같은 범위, rdma 빌드에서 이 계층의
  TCP 보내기 바이트 0(증인 BYE 빼고). 지금까지의 장치 객체 비교는 장치 헤더 digest가 같아 장치 객체를 다시 빌드하지 않은 사본을 견준 것이라 구성상 같다. 그래서 결과 문장은
  "장치 객체 207개가 ln4와 같음"이 아니라 "장치 헤더 digest가 같아 장치 객체를 다시 빌드하지 않음"으로 쓴다(준비 단계 리뷰 nit 8)
  `[측정: 문서 impl/notes_prepfix.md, impl/notes_int.md의 ident 로그 요약]`.
- **실행 가능성 확인(구현 전이나 준비 단계와 함께, 채점 안 함).** (1) NIC이 CPU가 고쳐 쓰는 64 B 줄 하나를 한 순간의 모습으로 읽는가(망치 시험, 짝수 `ver` 줄의
  찢김 수; 판정은 이것에 기대지 않고 보고 줄만 기댐); (2) 여러 스레드인 CUDA 프로세스의 pidfd가 읽기 가능해질 때 uverbs fd와 GPU fd가 이미 닫혔는가, 그리고 sunny(6.8)의 pidfd가
  rain(5.15)과 같이 동작하는가(fdinfo `Pid:`, 스레드 그룹의 끝에 읽힘; CUDA 없는 자식으로 rain에서 잰 사실은 9.5절); (3) rank마다 GIN
  포트의 active MTU; (4) 256 B READ의 부하 꼬리 지연; (5) 받는 QP가 RTR 전일 때의 RC 패킷 버림이 짝 맺기를 얼마나 늘리나; (6) fork 안전 설정; (7) UD QP의 비동기
  이벤트를 net_ib 이벤트 스레드가 세는가; (8) 활성화 뒤 부분(67.2–71.4 ms)에서 TCP 몫(tcp, rdma A/B); (9) sunny 노드 안 launcher의 띄우기 시간; (10) 판정 전 10–12 s
  동안 생존 rank의 장치 대기와 hold 한도가 견디는가(채점하지 않는 pilot 셀, 9.9절 끝); (11) 장애 없는 셀의 `watchBeat` 간격 최대(W를 정함, QP 감시 끔)와 W/2 동안의 박동 증가; (12) 닫힘(2026-10-17):
  REJOIN과 REJOIN_ACK은 `nrp`를 쓰지 않는다(9.5절의 줄 번호) `[소스]`; (13) hold 시작에서 저장소 응답 쪽 QP가 오류 상태로 가는가; (14) tcp 빌드(`gct`)의 전처리 결과를 ln4와 같게 만들 수
  있는가(안 되는 자리의 목록); (15) 하드웨어 응답 없음이 살아 있는 노드의 오류 상태 응답 쪽 QP에서도 오는가(9.3절 12행의 해석).
- **리뷰 확인점.** (1) 코드 전: 설계 v2와 이 문서 9절, 충돌 표를 다른 Opus 에이전트가 읽기만으로 재검토(9.7절 끝 열린 것 1; 끝남, 2026-10-17, 설계 v3가 받음). (2) 준비 단계 뒤: 갈아 끼우는 자리의 tcp 동일성.
  (3) 단계마다 단위 시험 뒤 pilot 전: 그 단계의 모형, 시험 스위치가 운영 빌드에 없음(md5), launcher가 등록받거나 띄운 pidfd에만 닿음. (4) 합친 뒤: 링 단계 위에
  펜스와 launcher를 올린 빌드로 회귀 묶음 전부와 펜스 셀. 그 뒤 pilot, 사전 등록.
- 모든 클러스터 실행은 `harness/gpu-initiated/common/cluster_run.sh` 안이다.

**실행 방법(초안).** 시험 쪽 파일은 [impl/test/](impl/test/)에 있고 설명과 TODO는 [impl/test/notes_test.md](impl/test/notes_test.md)다. 지금까지 돌린 것은 로컬 Python 자체
시험, `bash -n`, `check_cells_gc.py`뿐이고 클러스터에서는 아무것도 돌지 않았다(12절). 차례는 빌드(`impl/build_gc.sh`) → 배포(`deploy_gc.sh`, 두 노드의 새 묶음) →
hold 사슬(`RS_SET=<set> chain_gc.sh <결과 폴더> <hold> …`; hold마다 `harness/gpu-initiated/common/cluster_run.sh` 안) → 채점(`score_gc.py <결과 폴더>`)이다. 결과 폴더는
`results/<날짜>_<이름>/`, pilot과 smoke는 이름이 `pilot`이나 `smoke`로 시작하는 폴더(8절), 원자료는 Release `data-YYYYMMDD`로 올린다. 명령의 전문은 실행 뒤 [NOTES.md](NOTES.md)에 적는다.

| 파일 | 하는 일 |
|---|---|
| `impl/build_gc.sh` | 트리 키(`BR=`)마다 새 스크래치 트리에서 빌드 키 넷(`gc`, `gcp`, `gct`, `gctp`)을 빌드하고 unit, pre(`gctc` 포함 전처리 비교), sites, ident, diff를 돌림. `gctc` 라이브러리 단계는 아직 없음(전처리 검사만) |
| `impl/test/deploy_gc.sh` | 두 노드의 새 디렉터리 `~/rs-bundle/<RS_SET>/`에 라이브러리, driver, launcher를 둠(있으면 거절, 앞뒤 md5) |
| `impl/test/chain_gc.sh` | hold 사슬. hold마다 `cluster_run.sh`로 락과 한가한 링크를 기다린 뒤 `hold_gc.sh`를 부르고, hold 출력 전체를 IPv4 가림으로 보냄 |
| `impl/test/hold_gc.sh` | hold 하나: 노드마다 launcher 하나 띄우고 끄기, 셀의 n번(`cells_gc.sh`), 8절의 STOP 검사(두 STOP_launcher 꼴, launcher QP ERR 규칙, MTU 앞뒤, RNR, 남은 프로세스) |
| `impl/test/launcher_gc.sh` | launcher 하나(start, info, mark, table, stop). 0700 소켓 디렉터리, 준비 실패 때 스스로 끔, 기록한 PID와 시작 시각에만 신호 |
| `impl/test/run_gc.sh` | 시행 하나: 9.9절 주입(기록한 PID에만, 이름과 부모 확인), `SUBJECT_RANK`, 시행 시작 때 등록 표 검사, 시행 표지, 노드 시계 차, `ss` 스냅숏 둘, `active_mtu`, RNR 카운터, fd 자식 끄기 |
| `impl/test/remote_gc.sh` | 원격 셸에 넘기는 명령을 한 번만 따옴표로 쌈(`rcmd`, `pcmd`, `sunny_sh`), 공용 읽기 질의(`MTU_Q`, `RNR_Q`, `GID_PROBE`), IPv4 가림 식 |
| `impl/test/run_cost_gc.sh` | 비용 가족 probe의 실행 하나(팔 `probe-off`, `probe-on`은 `gcp`, `tcp`는 `gctp`) |
| `impl/test/gate_proc_gc.py` | `gate_fenced`의 실제 프로세스 시험(CPU만): main thread가 먼저 끝나는 자식, 따로 잰 Z와 pidfd 시각. 관문 시각은 `impl/gate_fenced.cc`의 `--pid` 모드가 내야 함(아직 없음) |
| `impl/test/rows_gc.py`, `impl/test/score_gc.py` | 시행별 열과 채점. gin-mirror의 `rows_mi.py`, `score.py`를 고치지 않고 불러 씀. 제외, STOP 줄, 자료 부족 규칙, smoke와 pilot을 따로 셈 |
| `impl/test/check_cells_gc.py`, `impl/test/test_rows_gc.py` | 셀 파일과 예측 표를 3, 7절에 맞춰 봄; 합성 로그 자체 시험 |

**라이브러리가 낼 줄**(시험 쪽 리뷰가 요구한 꼴 열둘; `rows_gc.py`가 읽음). 모든 줄 끝에 ` mono_ms=%.3f`(그 프로세스의 CLOCK_MONOTONIC, ms)가 붙고 `%s`는 공백 없는 낱말이다.
줄 꼴의 전체 표(의심, READ 시한, 증인 잃음, 링 요약, 짝 맺기 셋, 2단계 시험 스위치 셋의 줄 포함)는 `notes_test.md`의 "라이브러리 쪽이 낼 줄"이고, 아래는 그 가운데 리뷰가 요구한 것이다.
트리에 이미 있는 것은 죽음 판정 줄의 꼴(ln4 그대로; rdma 원인 이름은 아직), 1단계의 멈춤 판정 줄과 상태 페이지 줄뿐이고 나머지는 1–3단계가 낸다(`notes_test.md` 표의 "있음"과 `TODO(pN)`).

| # | 줄 | 꼴 | 낼 단계 |
|---|---|---|---|
| 1 | 죽음 판정 | `GIN/TS: rank %d: rank %d judged dead (cause=%s)`. rdma 빌드의 원인은 낱말 하나(`EXITED`, `FIN+STALE`, `FIN+NORESP`, `REMACC+FIN`, `NORESP`, `LINKDOWN`). 멈춤(14, 15행)은 `judged stalled` 줄 하나만 내고 이 줄을 함께 내지 않음 | 1 |
| 2 | 확인 창 | 열림 `GIN/RC: rank %d: confirm window for rank %d opened by FIN\|RST W=%d`(시각은 t_F), 닫힘 `GIN/RC: rank %d: confirm window for rank %d closed: alive\|STALE\|NORESP\|REMACC\|unconfirmed` | 1 |
| 3 | READ 요약 | `GIN/RC: rank %d: probe summary peer=%d reads=%u ok=%u remacc=%u noresp=%u timeout=%u gen=%u lat_med_us=%.1f lat_max_us=%.1f beat_gap_max_ms=%.1f torn=%u after_end_reads=%u after_end_ok=%u`(끝낼 때 상대마다). `after_end_*`는 상대의 BYE, LEFT, 판정 뒤 READ(`reads`, `ok`에 든 채 따로 셈), `beat_gap_max_ms`는 첫 성공 READ부터 상대의 끝 전까지, `torn`은 짝수 `ver` 줄의 찢김 수. 처음 세대 `gen`은 상태 페이지 줄이나 첫 짝 맺기 줄에 실음 | 1 |
| 4 | 제어 요약 | `GIN/RC: rank %d: control summary tcp_record_bytes=%llu tcp_data_bytes=%llu tcp_conns=%u witness_conns=%u records_lost=%u records_dup=%u repairs=%u sendq_deferred=%u sendq_max=%u rnr=%u async=%u active_mtu=%u`(끝낼 때와 확정 체크포인트마다, 모든 프로세스). TCP 바이트는 `gdakiCtrlSend`의 TCP 갈래에서 실제 보낸 것, `tcp_conns`는 증인 등록과 따로 셈, 받는 쪽 상대별 `tcp_rx_bytes_peer<p>=`, `async`는 `async_rec=`, `async_read=`, `async_la=`로 나눔, kv에 `active_mtu=` | 2 |
| 5 | launcher 소켓 끊김 | `GIN/RC: rank %d: launcher Unix socket closed (%s)`(rank나 예비 프로세스가 launcher 연결을 잃을 때; 8절 STOP_launcher) | 3 |
| 6 | fd를 쥔 자식 | `GIN/TS: rank %d: test switch FD_HOLDER=sock\|uverbs: child gin_fdhold pid=%d holds %d fd(s)`(증인을 끈 셀은 `holds 0`). 자식은 넘겨받은 fd 밖을 모두 닫고 0–2를 `/dev/null`로 돌림 | 1 |
| 7 | 시험 스위치 시작과 끝 | `GIN/TS: rank %d: test switch DIE_RST: linger 0 on %d socket(s); SIGKILL now`(SIGKILL 직전); `GIN/RC: rank %d: test switch FREEZE_PAGE=%d[:helper]: %s frozen`과 `GIN/RC: rank %d: test switch FREEZE_PAGE: beats resumed`; `GIN/TS: rank %d: test switch RST_GAP: %d socket(s) reset, listener closed for %d ms`과 `GIN/TS: rank %d: test switch RST_GAP: listener reopened`. 줄마다 `after_ckpt_ms=%d`(첫 무장 확정 체크포인트 뒤) | 1 |
| 8 | 활성화와 무장 | rdma 빌드에서도 지금 글 그대로: `GINRS step rank=R step=S released=0`, `rank P armed at its stable checkpoint K`, `every survivor holds rank P: its spare activated (…), N 'later' answers`, `restore round with rank P published`, `rank P restored as incarnation I`, `hold of rank P started`, `is given up`. 'later' 수는 launcher가 대신 답한 LATER 수 | 3 |
| 9 | 펜스와 바뀐 칸 | `GIN/RC: rank %d: rank %d (incarnation %u) fence FENCING: FENCE sent to the launcher of node %u`(짝), `GIN/RC: rank %d: rank %d (incarnation %u) fence FENCED (by FENCED\|EXITED from node %u)`(짝, 펜스 낱말이 선 때), `GIN/RC: rank %d: window check after the fence\|judgement of rank %d: changed=%u cells against=snapshot_at_judgement`(생존 rank마다) | 3(바뀐 칸은 driver도 가능) |
| 10 | launcher 표 | `GIN/LA: node %u: table: %d registered, %d spares`(등록 표가 바뀔 때마다). 그 전까지는 `launcher_gc.sh table`이 launcher의 지금 줄로 표를 읽음 | launcher |
| 11 | 복원 끔과 fail-fast의 생존 확인 | `NCCL_GIN_RESTORE=0`, `FAULT_POLICY=failfast`인 살아 있는 RST 셀에서도 상태 페이지, READ, 확인 창이 돌고 상태 페이지 줄(`GIN/RC: rank %d: status page up (…)`)을 냄. 돌지 않으면 그 셀은 아무것도 재지 않음 `[미확인]` | 1 |
| 12 | 시계 | 모든 `mono_ms=`가 CLOCK_MONOTONIC. launcher는 그렇고 rank 쪽 `gdakiQ4MonoMs`의 몸체는 diff 밖이라 `[미확인]` | 1(확인) |

### 9.9 이 testbed에서 넣을 수 있는 장애와 그 현실성

**넣는 것**(모두 연구 빌드의 시험 스위치나 실행기가 자기가 띄운 프로세스에만).
- **SIGKILL.** 실행기가 기록한 PID에(gin-mirror 그대로).
- **RST로 죽기.** `NCCL_GIN_TS_TEST_DIE_RST=<ms>`: 연결된 소켓(rdma 빌드는 증인, tcp 대조 `gctc`는 helper 소켓; tcp 쪽 갈래는 둘째 매크로 뒤)에 `SO_LINGER {1, 0}`을 두고 스스로 SIGKILL.
- **살아 있는 RST와 포트 닫힘.** `NCCL_GIN_TS_TEST_RST_GAP=<시작>:<길이>`: 연결 소켓을 linger 0으로 닫고 수신 대기를 그 길이만큼 닫았다 다시 엶.
- **SIGSTOP과 SIGCONT.** 실행기가 자기 rank의 정확한 PID에. 느린 상대는 50 ms 간격 반복. 끝에서 CONT 뒤 SIGKILL로 정리.
- **박동 쓰기만 멈춤.** `NCCL_GIN_TS_TEST_FREEZE_PAGE=<ms>`: 감시 스레드가 그 길이만큼 박동만 쓰지 않음(프로세스는 돎). `<ms>:helper`는 `helperBeat`만 멈춤(`watchBeat`는 오름;
  `gc4_helper_freeze12000`) `[설계 v3 7.1절]`.
- **fd를 쥔 자식 + 부모 SIGKILL.** `NCCL_GIN_TS_TEST_FD_HOLDER=sock|uverbs`: rank가 자식(`gin_fdhold`, `prctl(PR_SET_NAME)`)을 fork해 socketpair의 SCM_RIGHTS로 증인
  (tcp 빌드는 helper) 소켓만, 또는 uverbs fd까지 넘김. 자식은 60 s 뒤 끝나고, 실행기는 이름으로 끄지 않고 fork 줄의 PID를 uid, 이름, 같은 노드의 부모 시작 tick과 견준 뒤에만 그 PID로 정리(8절). PDEATHSIG는 쓰지 않음.
- **launcher 종료 보고 끄기.** `NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=1`(launcher 쪽, 연구 빌드만): EXITED 말만 끈다. FENCED, LEFT, REG_NOTE, 페이지 낱말은 그대로다(빌드된 launcher 그대로)
  `[측정: launcher 소스를 읽음]`. 판정은 끝남을 말로만 읽으므로 그 셀의 launcher 열은 "정보 없음"이다(9.3절).
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

**설계 v2를 접으며 셀 쪽에 남긴 사실 셋.**
- **READ 비용 문턱.** 3절의 문턱 2 %는 gin-mirror 4 KiB put 지연(off 팔) 11.26–12.29 µs `[측정: 문서 gin-mirror 2절]`에서 0.23–0.25 µs이고, 이것은 gin-mirror pilot 사이의
  퍼짐(약 9 %)보다 작다. 그래서 2 %는 실행 사이 잡음 아래일 수 있다 `[추론]`. pilot에서 같은 팔 사이 퍼짐을 재고, 사전 등록에서 문턱을 그 잰 퍼짐으로 정한다(초안 2 %는
  자리 표시).
- **uverbs fd를 쥔 자식 셀은 셀 설정으로만 거절한다.** launcher는 부모의 pidfd만 보므로 부모가 끝나면 종료 보고가 곧 FENCED를 만들고 활성화로 간다. 자식이 쥔 QP는 살아
  있고 같은 QPN이 다시 이어지면 옛 QP를 막는 것은 PSN뿐이다 `[설계 v2 6.4절; 추론, 미확인]`. 라이브러리는 이 경우를 알아낼 길이 없으므로 `gc4_fdhold_uverbs_kill3`는
  예비 프로세스를 두지 않는 셀 설정으로 복원을 막는다(사용자 결정 13). 소켓만 쥔 자식 셀은 이 한계가 아니고 launcher 보고로 복원된다.
- **멈춤 판정 전 생존 rank의 장치 대기.** 12 000 ms 멈춤 셀에서 생존 rank의 커널은 판정(약 10 s) 전까지 멈춘 상대의 신호를 기다린다. 그 대기와 장치 hold 한도가 10 300 ms
  넘게 견디는지는 잰 적이 없다(gpu-detect는 8 s 투명까지 보였음 `[측정: 문서 ../../../gpu-detect/EXPERIMENT.md]`) `[미확인]`. 채점하지 않는 pilot 셀 하나(rank 3 SIGSTOP
  12 000 ms, 생존 rank의 장치 대기 시각과 hold 한도 줄을 봄)로 잰 뒤 `gc4_stop12000_*`의 사전 등록 여부를 정한다.

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
- [x] 제어 경로 설계의 독립 리뷰 받음(2026-10-16: 막는 문제 다섯; 이 문서의 해당 자리를 설계 v2를 기다린다고 표시)
- [x] 설계 v2 반영(2026-10-16: 표시한 자리를 v2로 닫음, kill 셀 예측을 v2 4.6절 값으로, 판정 표의 빈칸 행; 12절 둘째 행)
- [x] 설계 v2의 독립 재검토(9.7절 끝 열린 것 1) — 2026-10-17: 막는 문제 넷, 고칠 것 열여덟, nit 열
- [x] 설계 v3 반영(2026-10-17: 막는 문제 넷을 닫고 고칠 것과 nit을 모두 접음, 판정 표 21행을 두 문서에 같게, 빌드된 launcher의 헤더에 맞춤; 12절 넷째 행)
- [x] launcher 프로그램(`impl/launcher/`): 빌드됨, CPU 단위 시험 장면 18, 검사 418, 4/4 실행 통과, verbs 전송은 빌드만(실행 안 함) — 2026-10-17, 조율 세션의 보고(12절 다섯째 행)
- [x] 설계 v3의 사용자 결정 여덟(9.7절 끝 v3 목록) — 2026-10-17 새벽 모두 권고대로
- [x] 사용자 결정 대기 넷(floor 규칙과 W, 메모리 한도의 뜻, 당기기 시도 수 결정을 거둘지, 계속 주고받는 셀)과 어긋남 1(9.7절 끝) — 2026-10-16 밤 모두 결정
- [ ] 판정 전 장치 대기의 pilot 셀(9.9절 끝)
- [ ] 실행 가능성 확인 열(9.8절, 채점 안 함)
- [x] 준비 단계: 공유 헤더, 갈아 끼우는 자리, 빌드 스위치, CPU 단위 시험, tcp 동일성 (2026-10-17; 독립 리뷰는 남음)
- [x] 준비 단계의 독립 리뷰(저장소 밖 `REVIEW_PREP.md`: 막는 문제 둘, 고칠 것 15, nit 16)와 고침(2026-10-17; 받기 seam, 채널 seam 넷, 헤더 고침, launcher 넷; `impl/notes_prepfix.md`)
- [ ] 1단계(상태 페이지, READ 감지, 판정 표 21행, 확인 창, 펜스 낱말과 보고 이름, 기록 52–55, 관문 순수 함수) — 코드 리뷰(2026-10-17)가 막는 문제 여섯을 찾음(확인 창과 PROBE_SETUP 보내기는 부르는 곳 0, 생존 READ 버퍼 공유, 분할 막이 뜻 거꾸로, 500 ms 뒤 READ 재발행으로 SQ 넘침, 오류 CQE 분류, 감시 스레드의 helper 전용 호출); 고침 전까지 미완. 처음 보고: `impl/gc_layer_p1.diff` 빌드됨(gc, gct, gcp, gctp), CPU 단위 시험 통과(gc_unit_p1 83 467, gate_fenced 10/10은 시간표 모형이라 3절 `gate_fenced`의 시험이 아님), 장치 207×4 동일(다시 빌드하지 않은 사본), tcp 전처리 0 hunk — 2026-10-17(`impl/notes_p1.md`). 고친 준비 단계 위로 통합됨(아래), 막는 문제 여섯은 고치는 중
- [ ] 2a-1(링과 credit 모형, UD 짝 맺기와 REJOIN 모형, verbs back end 빌드만) — 코드 리뷰가 막는 문제 둘을 찾음(짝 맺기 모형에 HELD와 계보 입력 없음, 세대 바뀜이 ACK된 기록을 버리고 라운드 취소 없음); 고침 전까지 미완. 처음 보고: `impl/gc_layer_p2.diff`, gc_unit_p2 rdma 2 781 801 검사 통과 — 2026-10-17(`impl/notes_p2.md`). 고친 준비 단계 위로 통합됨(아래), 막는 문제 둘은 고치는 중
- [x] 1단계와 2a-1을 고친 준비 단계(`gc_layer.diff` `0df79ae2`) 위로 통합: `impl/gc_layer_int.diff` `a7600a46`(ln4 대비 4 312줄, 호스트 파일만, 장치 0줄), 충돌 넷, 중복은 헤더 판으로, LATER 기본 1 000, `r->ctrl`은 all-gather 앞; 네 빌드 경고 0, 단위 두 빌드 통과 — 2026-10-17, 커밋 `9dbcabe3`(`impl/notes_int.md`). 통합만 끝났고 1단계와 2a-1은 끝나지 않음
- [ ] 고침 단계: 1단계와 2a-1 코드 리뷰(`REVIEW_P12.md`)의 막는 문제 8, 고칠 것, nit을 통합 트리 위에서 고침, 부르는 곳 0인 코드 잇기(확인 창, 범위 검사, 생존 READ QP 짝 맺기), 1단계 시험 스위치 넷
- [ ] 2b mirror 끔 저장소(결정 7)와 2단계 시험 스위치 셋 — 진행 중
- [ ] 2a-2 호출 자리 연결(링 만들기, seam 본문, 페이지 소비 낱말 묶기, 짝 맺기 wiring; 2a-1 막는 문제 둘을 먼저 닫음)
- [ ] 3단계 rank 쪽(launcher 짝 맺기, 등록과 무장, 활성화 중계, FENCED 관문의 `launcherPaired`, L의 유도)
- [ ] 고친 단계마다와 합친 뒤의 독립 재리뷰
- [ ] 4단계(남은 TCP 코드를 스위치 뒤로), 다시 빌드, 회귀 묶음
- [x] 실행기, 채점기, 셀 파일, 예측 표 초안(`impl/test/`: cells_gc.json 27셀, predictions_gc.csv 31행, run_gc.sh, hold_gc.sh, launcher_gc.sh, rows_gc.py, score_gc.py, deploy_gc.sh) — 2026-10-17, 합성 로그 자체 시험 39/39, 셸은 bash -n만(`impl/test/notes_test.md`)
- [x] 시험 쪽 독립 리뷰(저장소 밖 `REVIEW_TEST.md`: 막는 문제 4, 고칠 것 19, nit 21)와 고침: 원격 명령 따옴표, 시험 스위치 셀의 대상 rank, 둘째 죽음 제외 없앰, 두 STOP_launcher 꼴과 launcher QP ERR 규칙, 실제 프로세스 관문 시험, 리뷰가 놓친 결함 하나; 자체 시험 62/62 — 2026-10-17, 커밋 `4eadfe49`. 3절의 `todo` 여섯은 권고 값을 `[초안: 사전 등록 전 확정]`으로 적음, 8절 규칙 반영
- [ ] 라이브러리가 9.8절의 줄 꼴 열둘을 냄(1–3단계), `gctc` 라이브러리 빌드 단계, `impl/gate_fenced.cc`의 실제 pid 모드
- [ ] smoke와 pilot(채점 제외), W와 셀 값의 자리 표시, 문턱과 n 고정, 8절 열린 것 둘(9.7절 끝 3, 4)
- [ ] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/gin-control-v1` 태그
- [ ] 본 실행 (`RUNNING`)
- [ ] 채점과 독립 재계산 (`QA`)
- [ ] 결과 정리, 원자료 release, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-16 | 초안 작성(DRAFT): 1–11절, 설계 9.1–9.9절, 충돌 표 9.7절. 근거는 저장소 밖의 설계 셋(제어 경로를 RDMA로 옮기는 설계 초안 690줄, 감지 빈틈 셋의 설계 v2, 동적 예비 프로세스 설계)과 리뷰 둘(동적 예비 프로세스 설계의 독립 리뷰; gin-mirror 9.9절의 계보 리뷰)과 장애 문헌 조사이고, 내용을 이 문서에 요약했다(파일은 링크하지 않음). 사용자 결정(2026-10-16 저녁과 21시 무렵의 열넷, 메인 세션이 전함)으로 충돌 표의 결정 행을 닫았다. 그 뒤 나온 제어 경로 설계의 독립 리뷰(막는 문제 다섯, 고칠 것 스물하나, nit 열하나)를 메인 세션의 지시대로 접었다: tcp는 옛 스택 전체를 되살리는 빌드 스위치(아무것도 지우지 않음), mirror 끈 체크포인트와 FETCH는 있는 RDMA 저장소로(outbox 아님), 원격 접근 오류 하나로는 끝남이 아님, 정상 종료는 떠남 알림(BYE 뒤 hold 없음), kill 판정은 확인 창 W 20–50 ms, 시행마다 `active_mtu` 기록(두 GIN 포트 4 096). 이 자리들은 설계 v2를 기다린다는 표시로, kill → 판정 시간 예측은 범위와 초안 표시로 남김(둘째 행에서 닫음). floor 규칙은 사용자 결정 대기, 결정 14는 문서화한 한계(DISARM 예측)로 적음. 1절과 9절의 gin-mirror 기준 수치(RST 지연 셋, 소켓 닫힘 원인 수, 복원 시간과 관문 기다림, 빠른 모드 8/95, 입력 멈춤 최대)는 gin-mirror 본 실행의 `trials_scored.csv`와 `raw/*.log`(로컬 worktree `gin-mirror-fix`의 결과 폴더, release `data-20261015`와 같은 원자료)에서 다시 셌다. 구현, 빌드, 클러스터 실행 없음 | 이 파일, 브랜치 `exp/gin-control` |
| 2026-10-16 | 제어 경로 설계 v2(저장소 밖, 888줄, 바뀐 것 스물일곱; 제어 경로 설계의 독립 리뷰와 사용자 결정 열넷에 대한 답)를 접었다. 동적 예비 프로세스 설계 v2는 launcher와 예비 프로세스의 경계에만 썼다. 바뀐 것: 설계 v2를 기다린다는 표시 24곳을 모두 v2 내용으로 닫음(머리, 체크리스트, 첫 행의 문구 포함); `[초안, 설계 v2 뒤 확정]` 표시 15곳을 모두 없앰: 가설 셋과 예측 여섯(`kill_judge_rdma`, `rst_judge_rdma`, `finless_exit_report`, `finless_read_fail`, `kill_no_witness`, `restore_time_rdma`)은 v2 4.6절 값과 셀마다의 범위로 바꾸고, tcp RST 예측 둘(`rst_judge_tcp`, `rstgap_live_tcp`)은 v2에 값이 없어 감지 설계의 어림을 두고 새 표시(어긋남 1)를 닮, 나머지 넷(머리말, 9.3절 어림, 충돌 행, 선택 행)은 v2로 닫음; W에 기대는 값에만 `[초안]`을 남김. 판정 표는 17행에서 20행(빈칸 행 "READ 응답 없음 + 증인 정상 + launcher 보고 없음", helper 의심, helper 멈춤을 더하고 원격 접근 오류 행을 v2 꼴로 나눔). 더한 표: all-gather 칸 8행(제어 길과 launcher 노드는 엄격히 같아야 함), Unix 소켓 말 7행(pidfd, `SO_PEERCRED`); Resume 조건 41–44; 복원 시간 예측 옆에 리뷰와 다르게 셈한 몫의 `[추론]` 메모; 9.9절 끝에 비용 문턱, uverbs 자식 셀, 판정 전 장치 대기의 셋. 수치는 `[설계 v2]`로 적었고 이 문서가 새로 다시 센 수치는 없다(1절의 gin-mirror 기준 수치는 첫 행의 다시 셈 그대로). 첫 행이 적은 앞선 리뷰 둘(동적 예비 프로세스 설계의 리뷰, 계보 리뷰)은 맞아 고치지 않았다. 남은 것: 설계 v2의 독립 재검토, 사용자 결정 대기 넷(floor 규칙과 W, 권고 (가); 메모리 한도가 호스트 고정 메모리에도 드는가, 권고 (가); 당기기 시도 수 결정을 거둘지, 권고 거둠; 계속 주고받는 셀, 권고 이 실험에는 넣지 않음), 앞 결정 "RST 0.1 s"와 v2 2.0절의 어긋남 하나(보고만), W 값(pilot), REJOIN_ACK의 `nrp`와 64 B 한 줄 READ의 원자성 `[미확인]`, 판정 전 장치 대기의 pilot 셀(9.7절 끝, 9.9절 끝). 구현, 빌드, 클러스터 실행 없음 | 이 파일, 브랜치 `exp/gin-control` |
| 2026-10-16 | 사용자 결정(밤): 9.7절 끝의 결정 대기 넷을 권고대로(floor 규칙 (가), 메모리 한도는 BAR1의 것 (가), 당기기 시도 수 결정 거둠, 계속 주고받는 셀은 gin-dynamic에 넣음)와 어긋남 1(간격은 tcp 빌드 매개변수, 기본 1 000, RST 셀만 100)로 닫음. 다음 묶음은 에이전트 셋: 설계 v2와 이 문서의 독립 재검토, 준비 단계, launcher 프로그램. 1단계와 2단계는 재검토 뒤. 구현 시작 전, 빌드와 클러스터 실행 없음 | 이 파일 |
| 2026-10-17 | 설계 v2와 이 문서의 둘째 독립 재검토(저장소 밖 `REVIEW2.md`, 248줄: 막는 문제 넷, 고칠 것 열여덟, nit 열, 준비 단계와 launcher 절)에 답한 제어 경로 설계 v3(저장소 밖, 1 225줄, md5 `a548b5c2`; v2는 `DESIGN.v2.bak` md5 `c337e4a2`로 남김)를 접었다. 막는 문제 넷을 모두 닫음: (1) 펜스 낱말은 `fencedPlus1`(0 = 없음)이고 계보 국면 값과 `gdakiLnViewOf`는 그대로(보고 이름은 따로 된 `gdakiLnFenceOf`, 계보 헤더는 바이트 그대로); (2) 판정 표는 입력 넷의 값 목록과 첫 일치 21행, 두 문서 같은 행, 빈칸이던 "하드웨어 응답 없음 + 증인 꺼짐"은 launcher 무응답이면 거절, 정보 없음이면 펜스가 확인하는 hold; (3) 확인 창은 t_F, t_F + W/2, t_F + W에 판정 하나, 기록 QP 오류는 창을 열지 않음; (4) 다시 짝 맺기는 기록과 생존 READ를 따로, 어느 쪽이든 시작, 매번 새 PSN, REJOIN의 다른 QPN은 FAIL 대신 버림. 고칠 것 열여덟과 nit 열은 모두 접었고 버린 것은 없다. 리뷰의 고침과 다르게 정한 것 셋: EXITED와 박동 늚이 함께일 때 DISPUTE 대신 EXITED가 이김, 확인 창의 원격 접근 오류도 t_F + W에 판정, 계보 헤더 사본은 필요 없어 만들지 않음. REJOIN과 REJOIN_ACK의 `nrp`가 비어 있음을 호스트 파일 줄로 확인해 `[미확인]` 둘을 닫음(10146–10166, 9563–9570). 이 문서에서 바뀐 것: 머리(빌드 키 `gctc` 더함), 2절 가설 셋을 고치고 하나 더함, 3절 예측 열셋을 고치고 둘 더함(`helper_stall_fence`, `gate_fenced`; 29 → 31), 다시 예측 목록 둘(`rg_spare_absent_fallback`, `rg_nospare_failfast`), 5, 6절의 launcher와 통제변수(QP 감시 끔, LATER 뒤 한도), 7절 셀 여덟을 고치고 하나 더함(`gc4_helper_freeze12000`; 26 → 27), 8절 제외 셋, 중단 둘, 채점 규칙 하나, 9.1–9.6절 설계, 9.3절 판정 표 20 → 21행(모두 새로 씀), 9.4절 국면 표를 보고 이름 표로, 9.7절 충돌 표 열 행을 고치고 아홉 행을 더함(45 → 54), 9.7절 끝에 사용자 결정 목록 여덟, 9.8절 단계 표 넷과 파일 자리, 시험 스위치 주인, 단위 모형, 실행 가능성 확인, 9.9절 스위치 셋. 수치는 설계 v3에서 새로 옮기거나 바뀐 것을 `[설계 v3]`로 적었다. 이 문서가 원자료에서 새로 다시 센 수치는 없다. 구현, 빌드, 클러스터 실행 없음 | 이 파일, 브랜치 `exp/gin-control` |
| 2026-10-17 | launcher 프로그램(`impl/launcher/`)이 빌드됐다고 조율 세션이 알림: CPU 단위 시험 장면 18, 검사 418, 4/4 실행 통과(ASan, UBSan), verbs 전송은 빌드만 하고 돌리지 않음. `launcher_msg.h` md5 `30a05c7f`(이 문서가 md5를 다시 확인: 같음). 둘째 재검토 5절 launcher 행의 바꿀 것 가운데 여섯(끌 수 없는 pid 검사, 등록마다 상태 낱말과 예비 자리 낱말, rank마다 소비 수, 한 사건 한 말, `NO_EXIT_REPORT`가 FENCED를 끄지 않음, 다른 노드 rank의 Q_Key를 PAIR 본문에)을 적용했고, LATER 뒤 한도는 사용자 결정으로 남김(9.7절 끝 v3 목록 4). 설계 v3와 이 문서는 선 위 배치(봉투 64 B, launcher 말 256 B, 종류 열일곱과 일곱, launcher 페이지 4 KiB, 끝점 40 B)를 그 헤더에 맞췄다. 단위 시험이 잰 pidfd 사실(rain 5.15, n 4)을 9.5절에 옮겼고 로그는 다시 세지 않았다. 이 문서는 시험을 돌리지 않았다 | `impl/launcher/README_launcher.md`, `impl/launcher/launcher_msg.h` |
| 2026-10-17 | 준비 단계 구현. ln4(`mi_layer.diff` dcd30859) 위의 `impl/gc_layer.diff`(f5061a31, 1 706줄, 호스트 파일만, 장치 코드 0줄). 공유 헤더 `impl/rs_ctrl_api.h`(봉투 64 B, 페이지 낱말, 끝점 판 2, PAIR, REJOIN nrp, 펜스 낱말, 기록 52–55, 매개변수 이름, swap 지점과 주인). `gdakiTsSend` 25곳 가운데 18곳을 `gdakiCtrlSend`로, 증인 7곳은 그대로. `gdakiTsPump` 6곳 가운데 5곳을 `gdakiCtrlPump`로. `gdakiHoldSend` 15곳은 본문 swap으로. `pe.fd` 56곳은 기록 26, 증인 28, back end 2로 나눠 `impl/gc_sites.tsv`에 적음 [측정: 소스]. 재검토의 준비 단계 항목과 launcher 페이지 결정(launcher_msg.h의 glPage 배치를 따름)을 반영. 시험 스위치는 둘째 매크로 `NCCL_GIN_CTRL_TCP_CELLS` 뒤 | `impl/build_gc.sh`, 스크래치 `agent_gc_prep/*_prep.log` |
| 2026-10-17 | gc, gct, gcp, gctp 빌드됨(경고 0). tcp 빌드의 전처리 결과는 ln4와 줄 수가 같고, 트리 경로와 `__LINE__`을 정규화하면 같다(gct, gctp, gctc 모두 hunk 0) [측정]. 매크로 없는 프로그램 넷의 16 조합과 장치 객체 207개×4가 ln4와 같다. 장치 객체는 다시 빌드되지 않은 사본이다 [측정]. CPU 단위 시험(mi_unit 다섯, rs_unit_host, rs_spare_unit, gc_unit_prep 1 026 745 checks rdma, 7 842 tcp)이 두 빌드에서 실패 0 [측정]. rs_spare_unit은 ln4 때부터 gin-mirror 사유 문자열 7개를 `-include`로 넘겨야 컴파일된다 [측정]. launcher 프로그램 커밋 3323f8f1, 설계 v3 커밋 a0404682. 클러스터 실행 없음 | `pre_prep.log`, `ident_prep.log`, `unit_prep.log` |
| 2026-10-17 | 사용자 결정(새벽, "추천대로"): 설계 v3가 올린 여덟을 모두 권고대로 닫음(9.7절 끝). 준비 단계와 launcher 코드의 독립 리뷰(저장소 밖 `REVIEW_PREP.md`: 막는 문제 둘(받는 쪽 seam 빠짐: 응답 DONE 기다림, serveWait=0 ACK, MIRROR_SETUP 기다림, 예비 프로세스의 REJOIN_ACK, TOKEN, DONE_RS, 수신 소켓의 REJOIN, DATA, REJOIN FAIL 답; `gdakiCtrlFd` 한 이름이 채널 검사 19곳, poll fd 3곳, 대입 1곳을 묶음), 고칠 것 15, nit 16; tcp 전처리 동일성은 리뷰어가 다시 세어 맞음; 단위 시험 수 부풀림(credit 불변식 백만 회, 등록 oracle 항등 44개) 지적). 고침 에이전트 시작(받기 seam `gdakiCtrlRecv`/`gdakiCtrlRecvOn`과 REJOIN 답 seam, `gdakiCtrlChanUp(r, peer)`/`gdakiCtrlPollFd`/대입으로 가름, launcher의 READ 중 ABORT 버퍼 해제, 핸들 재사용, ACCEPTED 뒤 연결 끊김 SIGKILL, AH 캐시). 둘째 매크로 이름을 코드대로 `NCCL_GIN_CTRL_TCP_CELLS`/`gctc`로 통일(문서는 `_EXT`/`gctx`였음). 2단계는 두 번 코드 전에 멈춰(출력 안전 검사) 2a-1(링, credit, 짝 맺기 모형과 back end)로 좁혀 다시 시작; 호출 자리 연결은 2a-2, mirror 끔 저장소는 2b. 클러스터 실행 없음 | 이 파일 |
| 2026-10-17 | 1단계 구현(`impl/gc_layer_p1.diff` 2fc1ad01, 778줄, 호스트만, 장치 0줄; 준비 단계 f5061a31 위). 판정 표 21행 순수 함수를 입력 격자 1 170점에서 독립 참조와 전수 비교: 모두 정확히 한 행, 21행에 닿는 점 0(죽은 행; 통합 때 표에서 "닿지 않음"으로 표시), hold와 거절 행은 모두 floor 규칙의 증거(launcher 끝남, 확인 창 확정, 하드웨어 응답 없음, 멈춤) 중 하나 [측정: 단위 시험]. 확인 창 t_F, t_F + W/2, t_F + W(incNonce, 감싸는 박동 비교), 펜스 낱말 fencedPlus1과 보고 이름(계보 헤더 그대로), 기록 52–55와 PROBE_SETUP 발판, 1단계는 멈춤 거절만, 관문은 순수 함수(launcher 없으면 /proc). 결정 여덟은 한 행이나 매개변수 하나씩. 네 빌드 경고 0, 단위 두 빌드 통과, 장치 207×4와 프로그램 16/16 ln4 동일, gct, gctp 전처리 0 hunk. 커밋 73be8802 | `impl/notes_p1.md`, `impl/gc_unit_p1.cc`, `impl/gate_fenced.cc` |
| 2026-10-17 | 2단계는 에이전트가 두 번 코드 전에 멈춰(출력 안전 검사) 2a-1로 좁힘. 2a-1 구현(`impl/gc_layer_p2.diff` d571b977, 1 552줄 추가, 호스트만, 장치 0줄; 준비 단계 f5061a31 pin 위): 링 모형(64칸, 세대 꼬리표 credit, 큐와 inbox 4 096, 세대 바뀜, CONNECTED 전 송신 보류, framing), 짝 맺기 모형(두 종류, 어느 쪽이든 시작, 낮은 rank 우선, launcher에는 rank 우선, 새 PSN, REJOIN 멱등은 HELD만, 다른 QPN은 버림 + GIN/LN 한 줄), verbs back end 29함수(빌드만, 아무 데서도 안 부름; UD AH와 CQ 이벤트 wrapper 넷은 적재된 libibverbs에서 dlsym). gc_unit_p2 rdma 2 781 801 검사 0 실패(세대 바뀜 104회의 credit, inbox 한도, 기록 10 872개가 TCP 길과 바이트 같고 park 같음, 다시 짝 맺기 12 000회) [측정]. 네 빌드 경고 0, 전처리 0 hunk, 장치 동일. 2a-2 필수 순서: 기록 길 켜기 전 페이지의 소비 낱말을 묶어야 함(아니면 한 방향 64개 뒤 멈춤). 커밋 494cd666 | `impl/notes_p2.md`(2a-2 발견 여덟과 리뷰 항목), `impl/gc_unit_p2.cc`, `impl/rs_ctrl_api_p2.diff` |
| 2026-10-17 | 시험 쪽 초안(`impl/test/`): 셀 파일(7절 27행 ↔ 27 셀, 본 실행 hold C1–C11, pilot hold P0–P4는 채점 안 함, gin-mirror 회귀 hold 여덟을 @gct와 @gc로, 비용 가족), 예측 표(3절 31행; 3절에 수치가 없는 여섯은 todo 열: restore_time_rdma n 5 셀의 k 4, gate_fenced 490–510 ms, regression_rdma의 gin-mirror ID 11개, regression_rdma_mirror_off 셀과 k, kill_judge_rdma 범위, 2 % 문턱), 대조 스크립트(3절 키 31 ↔ 7절 27행), 실행기(노드마다 launcher 먼저, 기록한 PID에만 신호(이름과 부모 확인), SIGSTOP/SIGCONT 지속 측정, fork 자식, 둘째 kill은 모든 생존자 "armed" 뒤, spare를 5 ms 먼저, active_mtu와 RNR 카운터, rank BYE 뒤 launcher 마지막), hold(STOP_launcher, STOP_rnr, STOP_mtu, STOP_async, STOP_left), 행 추출과 채점기(gin-mirror의 rows_mi.py와 score.py를 고치지 않고 적재, smoke와 pilot 분리), 배포 스크립트. launcher 범위는 5절대로 hold마다(시행마다도 선택 가능). 라이브러리가 아직 안 내는 줄 꼴은 notes_test.md 표가 정함. 합성 로그 자체 시험 39/39 통과(로컬 Python) [측정], 셸은 bash -n만. 커밋 afc164ff | `impl/test/notes_test.md`, `impl/test/cells_gc.json`, `impl/test/predictions_gc.csv` |
| 2026-10-17 | 준비 단계와 launcher 고침(코드 리뷰 반영; `impl/notes_prepfix.md`). 받기 seam `gdakiCtrlRecv`(11896, 12024, 22372)와 `gdakiCtrlRecvOn`(10192, 10235, 10297), REJOIN 답 seam `gdakiCtrlRejoinFail`(8777, 9536); `gdakiCtrlFd` 없애고 `gdakiCtrlChanUp` 19, `gdakiCtrlPollFd` 3, `gdakiCtrlChanInstall` 1, `gdakiCtrlChanGen` 2; 자리 표 149행, tcp 갈래 32개가 ln4 글 그대로임을 `sites`가 검사. 헤더: 확인 창 서명(incarnation 입력, 감싸는 비교), CQ 셈에 launcher 생존 QP, nrp 168 B와 memcpy put/get, CONNECTED 종류 6과 PAIR_STEP_DONE, `gdakiLnFenceOf`, 판정 enum, 문턱 struct와 v3 범위 검사, 생존 QP 소프트웨어 상태(QUERY_QP는 설정과 진단만), 단계마다 하위 블록과 free hook 셋, `gdakiCtrlActFenceOk`. launcher: READ 중 버퍼는 완료 때만 해제, 핸들 일련번호, ACCEPTED 뒤 QP 끊김에 abort 없음, AH를 (GID, LID)로 캐시, `--tc`. 시험 수를 장면마다 한 번으로(준비 rdma 116/366, tcp 48/174; launcher 20 장면 414 검사 3/3) 0 실패; 고침 전 launcher로 돌린 음성 대조는 heap-use-after-free와 lost_accepted 실패 [측정]. 네 빌드 경고 0, gct, gctp, gctc 전처리 0 hunk, 장치 동일. .gitignore의 tsv 허용을 gc_sites.tsv 하나로 좁힘. 1단계와 2a-1은 이 고침 전 준비 단계 위라 옮겨야 함. 커밋 fd4ae2d6 | `impl/notes_prepfix.md`, 스크래치 `agent_gc_prep/*_prepfix2.log`, `launcher_build2/` |
| 2026-10-17 | 1단계와 2a-1 코드의 독립 리뷰(저장소 밖 `REVIEW_P12.md`): 막는 문제 8, 고칠 것 18, nit 16. 1단계: 확인 창(READ1, READ2, t_F + W 판정)과 PROBE_SETUP 보내기를 부르는 곳이 0이라 notes_p1과 앞 12절 행의 "구현"은 틀림(코드는 있으나 살아 있지 않음; 이 행이 정정); 모든 상대의 생존 READ가 scratch 버퍼 하나로 떨어져 박동이 섞임; 분할 막이가 "다른 rank들이 본 p의 정체"가 아니라 "이 rank가 본 다른 상대의 정체"를 견줌(4 rank에서 멈춤 판정 안 나고 고립 때 거짓 멈춤); 500 ms 시한 뒤 READ 재발행으로 SQ 4 넘침과 err 고정(10–12행에 못 닿아 `finless_read_fail` 불가); 원격 접근 오류 아닌 모든 오류 CQE를 하드웨어 응답 없음으로 침(floor 규칙 위반 가능); 감시 스레드가 helper 전용 함수와 펌웨어 명령을 부르고 걸쇠 없음. 2a-1: 짝 맺기 모형에 HELD와 계보 입력이 없어 옛 화신의 PAIR를 받아 RTS로 이음(펜스 불변식 깨짐); 세대 바뀜이 RC가 ACK한 기록과 inbox를 버리고 상대가 시작한 다시 짝 맺기는 라운드 취소를 안 냄(결정 6과 어긋남). 격자 시험의 "독립 참조"는 같은 if 사슬 복사라 독립 아님(리뷰가 행마다 기대 점 수를 적음: 1행 234, 2행 468, 3행 117, 4–9행 39씩, 10행 3, 11행 1, 12행 5, 13–17행 9씩, 18행 36, 19행 9, 20행 18, 21행 0). `gate_fenced.cc`는 넣은 값을 되읽는 모형이라 예측의 시험이 아님. 헤더 LATER 기본값 5 000 대 결정 1 000 충돌. 규칙 준수는 확인됨(장치 0줄, 전처리 0 hunk, 고정 파일 그대로). 통합 뒤 고침 에이전트가 여덟을 닫은 뒤에야 1단계와 2a-1을 끝난 것으로 적는다 | `REVIEW_P12.md`(저장소 밖), 11절 |
| 2026-10-17 | 1단계와 2a-1의 통합(CPU와 빌드만). 고친 준비 단계(`gc_layer.diff` `0df79ae2`) 위에 1단계와 2a-1을 3-way로 합쳤다. 충돌 넷(1단계 셋: 준비 영역의 "[1] page" 하위 영역, "[3] launcher" 하위 영역 끝, `gdakiCtrlFree`; 2a-1 하나: 준비 영역 끝 뒤의 같은 자리)은 모두 고친 준비 단계 쪽으로 풀거나 둘 다 두었다. 중복은 헤더와 고친 준비 단계 쪽을 남기고 지웠다: 1단계의 판정 enum과 행 함수(표는 헤더 "[1] page" 하위 블록의 `gdakiCtrlJudge`로 옮기고 21행에 "닿지 않음" 주석), `gdakiCtrlConfirmP1`, 1단계의 `gdakiLnFenceOf`, LATER와 launcher 정체 매개변수의 재정의, 두 인자 `gdakiCtrlChanUp` 자리 표시, `gdakiCtrlStateOf`; 2a-1의 `PAIR_STEP_DONE` 정의, 자체 nrp put/get, PAIR 본문으로 실은 CONNECTED(헤더의 봉투 종류 6으로 바꿈). 헤더 `rs_ctrl_api.h`는 `998b493b` → `948b3ecf`(판정 표 몸, LATER 기본 5 000 → 1 000). 코드 리뷰의 통합 항목 가운데 `r->ctrl`을 all-gather 앞으로(9.6절, 이 문서의 선택으로 적음), 단계 영역을 하위 영역 안으로, 생존 READ `wr_id`에 세대, 페이지 배치의 `nLaunchers` 칸을 반영했다. 확인: 네 빌드(gc, gcp, gct, gctp) 빌드됨, 경고 0; `pre`는 gct, gctp가 ln4와 0 hunk, gctc는 RST 간격 매개변수만큼 2 hunk 3줄(뜻한 대로); `api`, `syn`, `sites`(149행, tcp 갈래 33개가 ln4 글 그대로) 통과; 단위 시험 두 빌드 통과(`gc_unit_prep` rdma 366, tcp 174 검사; `gc_unit_p1` 84 672 검사, 격자 1 170점에서 21행 0점; `gate_fenced` 10/10은 시간표 모형; `gc_unit_p2` 2 781 807 검사; gin-mirror와 gin-restore의 일곱 실패 0; n 1); `ident`는 매크로 없는 프로그램 16/16과 장치 객체 207개 × 4가 같음(다시 빌드하지 않은 사본) `[측정: 통합 에이전트의 보고 impl/notes_int.md와 logs_int/*; 이 문서에서 다시 돌리지 않음]`. 부르는 곳이 0인 코드: 1단계의 확인 창(`gdakiCtrlWofConfirm`, `gdakiCtrlConfirmW`), `gdakiCtrlActGate`, `gdakiCtrlProbeSetupSend`, 헤더의 `gdakiCtrlConfirmVerdict`와 `gdakiCtrlThresholdsOk`, 2a-1의 모형과 뒤끝 전부(`r->ctrl->ring`은 늘 비어 있음); `gdakiCtrlActFenceOk`는 `launcherPaired = false`라 늘 참. 코드 리뷰의 막는 문제 8은 통합 몫이 아니라 고치지 않았고, 그래서 1단계와 2a-1은 끝나지 않았다. 산출물 `impl/gc_layer_int.diff` `a7600a46`(ln4 커밋 대비 4 312줄, 호스트 파일 하나, 장치 0줄). 이 문서는 9.3절 21행을 "닿지 않음"으로, 9.4–9.6, 9.8절을 이 상태에 맞췄다. 클러스터 실행 없음. 커밋 `9dbcabe3` | `impl/notes_int.md`, `impl/gc_layer_int.diff` |
| 2026-10-17 | 시험 쪽 독립 리뷰(저장소 밖 `REVIEW_TEST.md`: 막는 문제 4, 고칠 것 19, nit 21)와 고침. 막는 문제: sunny `active_mtu` 조회의 원격 따옴표(새 `remote_gc.sh`), 시험 스위치 셀 아홉의 대상 rank(`SUBJECT_RANK`, 7절), 둘째 죽음 제외(조율 세션 결정으로 `@gct`, `@gc` 모두 gin-mirror 8절 규칙: 빼지 않고 조건 불충족으로 셈), hold 쪽 STOP_launcher 두 꼴과 시험 스위치 밖 launcher QP ERR 규칙. 고칠 것: 실제 프로세스 관문 시험(`gate_proc_gc.py`), 노드 사이 시계 차, fd 자식을 PID로 끄기, launcher 시작 실패 때 정리, 시행 표지로 자른 launcher 조각, 자료 부족 규칙, 설정 다름(launcher env, W, READ 주기), 첫 체크포인트 전 제외 넓힘, 짝 kill 5 ms(`inject_late`), `ss` 스냅숏, pilot 폴더 규칙 등. 반영하지 않은 것: nit 3, 18(문서 몫; 이 문서의 8, 9.1, 9.5, 9.9절에서 고침), nit 7(사전 등록 결정, 9.7절 끝 열린 것 4), nit 21(`gctc` 라이브러리 단계, `build_gc.sh` 몫). 3절에 수치나 목록이 없던 여섯은 리뷰 권고 값(D3–D8)을 예측 표 파일에 넣었고 이 문서 3절에 `[초안: 사전 등록 전 확정]`으로 적었다. D1(launcher는 hold마다, 시행 시작 때 등록 표 검사)과 D2(둘째 죽음은 빼지 않음)는 조율 세션 결정이다. 리뷰가 놓친 결함 하나를 자체 시험이 찾았다: 펜스로 끝난 대상(실행기 kill 없음)을 gin-mirror 열이 살아 있는 rank로 쳐서 펜스 셀 셋의 데이터 같음 열이 늘 0이었고, 펜스로 끝난 대상을 kill된 rank로 세도록 고쳤다(`rows_gc.py`). 자체 시험 39 → 62 검사, 실패 0(로컬 Python), `check_cells_gc.py` ok, 셸 여덟은 `bash -n`만(shellcheck 없음) `[측정: notes_test.md의 고침 기록; 이 문서는 시험을 다시 돌리지 않음]`. `gate_proc_gc.py`를 로컬(커널 5.15)에서 3회 돌린 smoke: Z 0.39–0.40 ms, 둘째 thread 끝 500.04–500.52 ms, pidfd 읽힘 500.69–501.17 ms(n 3, smoke라 본 실험에 들지 않음; 관문 시각은 `gate_fenced.cc`의 pid 모드가 없어 아직 없음) `[측정: 같은 기록]`. 이 문서는 3, 7, 8절을 고친 뒤 `check_cells_gc.py`를 돌려 ok를 보았다 `[측정]`. 클러스터 실행 없음. 커밋 `4eadfe49` | `impl/test/notes_test.md`(고침), `impl/test/predictions_gc.csv`, `impl/test/cells_gc.json`, `REVIEW_TEST.md`(저장소 밖) |
| 2026-10-17 | 결함 여덟 고침(커밋 a5f7ef0b)과 2b(커밋 21ceb8c3)의 재리뷰(저장소 밖 `REVIEW_FIX12_P2B.md`): 앞선 막는 문제 여덟은 닫힘 7, 부분 1(확인 창). 새 막는 문제 셋: 창 READ1의 원격 접근 오류가 QP를 깨뜨려 READ2가 못 나가 6행(REMACC+FIN)이 살아 있는 길에서 나올 수 없음(CPU 시험은 READ2를 따로 내는 모형이라 실제와 다름); 감시 스레드가 W/2 넘게 늦으면 한 걸음에 POST1·POST2·JUDGE가 겹쳐 거짓 NORESP(5행 hold); R 값 8, 9에 데이터 경로 거부권이 걸려 helper만 멈춘 셀에서 15행에 못 닿음(`helper_stall_fence` 불가). 고칠 것 14, nit 13. 2b는 설계대로이고 HEAD 트리와 글자 충돌 없음; mirror 끈 셀이 멈춤 안에서 D2H를 하고 늘 전체 이미지를 올리므로(단위 모형 2.25배) 사전 등록 전에 그 셀의 복원 시간과 멈춤 예측을 다시 쓸 것[미결]; mirror 끈 예비 프로세스의 FETCH 버퍼 512 MiB 상한. 셋을 고치는 에이전트 시작(`agent_gc_fix3/`, `gc_layer_fix3.diff`). 2a-2는 에이전트가 세 번째로 코드 전에 멈춰(출력 안전 필터) 2a-2-A(설정과 링 만들기, 첫 짝 맺기, 55번 제거), 2a-2-B(seam 본문, 증인 읽기), 2a-2-C(REJOIN, 상태 전송, 판정 실효화)로 쪼갬; 3단계 rank 쪽 진행 중. 클러스터 실행 없음 | `REVIEW_FIX12_P2B.md`(저장소 밖) |
| 2026-10-17 | 새 막는 문제 셋 고침(커밋 34d52ef6, `impl/gc_layer_fix3.diff`): 원격 접근 오류는 READ1에서 판정(설계 4.2절의 판정 차례), 감시 스레드는 한 걸음에 창 동작 하나(늦으면 "확인 못함", 판정 시각은 max(t_F + W, READ2 + W/2)), helper 멈춤 행의 데이터 경로 거부권은 박동에만, `staleMs` 미관측 표시, CONNECT의 계보 검사, 연결된 적 없는 세대의 −1 없음, 펌웨어 명령은 모두 helper로. 2a-2-A(커밋 45900d7e, `impl/gc_layer_p2a2.diff`): all-gather 전에 링 생성과 168 B 제어 블록(기록 56 → 224 B), 합의 검사(44 제어 경로·문턱 불일치, 42 MTU < 2 048이면 투명 복구 끔), Resume 41–44, 첫 짝 맺기와 페이지 소비 낱말 묶기, 55번 발판 제거, comp channel wrapper 둘을 dlsym으로(NCCL ibvwrap에 선언만 있음). 3단계 리뷰(저장소 밖 `REVIEW_P3.md`: 막는 문제 2, 고칠 것 10, nit 13)와 고침(커밋 f5f6a085): 펜스 뒤 바뀐 칸 줄이 늘 0이던 것을 창 내용 64 B 조각 해시로 고침(시험에서 멈춤 뒤 늦은 쓰기가 changed=16), 등록 순서 충돌(nonce는 all-gather 뒤에 생김)은 **이 문서의 선택**으로 풂: launcher 끝점은 고정값이라 all-gather 전에 nonce 없는 INFO 조회(새 Unix 종류 8, 9; launcher 쪽 추가 진행 중)로 받고 REGISTER는 뒤에; launcher의 LEFT·EXITED가 판정 입력에 들어감, 되살아난 짝의 무장 비트, STORE_REQ 꼬리의 rdma 등록은 새 magic(9.8절의 "판 올린 헤더 사본" 대신; 어긋남 기록). 모두 네 빌드 경고 0, tcp 전처리 ln4와 같음, 장치 동일, 단위 시험 두 빌드 통과 [측정: 로그]. 스크래치 디스크가 꽉 차 빌드가 멈춘 적 있음(합쳐진 가지의 build 폴더만 지워 20 GB 회수). 2a-2-B 진행 중. 클러스터 실행 없음 | `impl/notes_fix3.md`, `impl/notes_p2a2.md`, `impl/notes_p3.md` |
| 2026-10-17 | 사용자 결정(아침): 펜스 거부(FENCE_NAK) 시행은 제외하지 않고 실패로 센다(등록 실패, launcher 표 잃음, 재등록 어긋남은 모두 우리 장치의 실패); SIGSTOP 셀의 멈춤 길이 허용 오차는 1 s에서 ±100 ms로(노드 안 시계; pilot 퍼짐을 보고 더 줄일 수 있음); mirror 끈 rank의 체크포인트 멈춤은 호스트 쪽 우회(스냅샷, 짝의 직접 READ)가 아니라 장치 쪽 더러운 segment 비트(2c, put마다 비트 하나)로 줄인다 — 초안의 "장치 코드 0줄" 목표는 사용자 요구가 아니었고 사용자는 내부 수정을 선호함. 2c 에이전트 시작(`agent_gc_p2c/`; 장치 객체 다시 빌드, 매크로 없는 프로그램은 ln4와 같아야 함). 통합 2(고침3 + 3단계 + 2a-2 A·B + 헤더 요청 셋 + 접착 여섯) 진행 중. launcher INFO 조회 커밋 f8e3216e | 이 파일, 8절 |
| 2026-10-17 | 2c 소스 확인(`impl/notes_p2c.md`, 코드 없음): mirror 끈 rank에는 바뀐 segment 기록이 없음(장치는 `miOn`일 때만 표시, 호스트는 mirror 켬일 때만 칸을 만듦) [소스]. 2b의 멈춤 안은 모든 영역의 전체 복사(20 MiB ≈ 1.6 ms), 밖은 slot 전체 쓰기(2b 단위 로그 125회에 94 806 977 B, 늘 전체) [측정]. **아침에 적은 "put마다 더러운 segment 비트" 설계는 틀림**: 이미지에는 등록 버퍼와 신호·카운터 표가 들고 rank 자신의 커널이 보내기 창과 등록 버퍼를 쓰므로(gin_mi.cu 329, 343, 382, 384) 들어오는 put의 비트만으로는 그 쓰기를 놓쳐 체크포인트가 틀린다. 대안 둘: (1) 라이브러리 안 스캔 커널(onerank.cu 끝, 64 KiB segment마다 해시, 바뀐 것만 복사; 장치 헤더 0줄이나 장치 객체는 네 빌드 모두 바뀜; 멈춤이 2 %·10 %·50 % 더러움에서 2b의 약 8 %·16 %·56 % [추론]; **학습 모양 셀은 거의 100 % 더러워 이득 없음**), (2) gin-restore처럼 멈춤 안에서는 GPU 안 복사만 하고 전송은 밖에서(장치 코드 0줄, 더러움과 무관하게 멈춤이 줄어듦, GPU 메모리 이미지 크기만큼). 구현은 사용자 지시로 다음 주 목요일로 미룸; 어느 안으로 갈지는 그때 결정(조율 세션 권고: 학습 모양에도 듣는 (2)를 먼저, 스캔은 선택) | `impl/notes_p2c.md` |

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
없애지 못함(그 셀은 셀 설정으로 거절만), 긴 hold의 생존 rank 사이 lane 넘침(DISARM), 실제 link down과 노드 고장은 재지 않음(9.9절), 제어와 데이터가 같은 RNIC 포트를 써서 같은
선이 죽으면 함께 죽음. 설계 v2가 더한 한계 `[설계 v2 6.4절]`: UD는 Q_Key(모든 datagram에 평문으로 실린 nonce의 아래 31비트)만 맞으면 받고 RC 응답 쪽의 보낸 쪽 검사 범위는
`[미확인]`이라, HELD인 동안 위조한 REJOIN이 복원을 가로챌 수 있음(이 testbed에서는 받아들이는 위험); 펜스는 프로세스 전체를 종료해 그 프로세스의 다른 communicator도 함께
끝남; application 스레드나 GPU가 멈춰도 감시 스레드가 돌면 박동은 늘어 페이지로는 잡히지 않음(데이터 길의 감지와 체크포인트 멈춤 시한에 맡김). 비용 문턱 2 %가 실행 사이
퍼짐보다 작은 것과 판정 전 장치 대기가 잰 적 없는 것은 9.9절 끝.

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
