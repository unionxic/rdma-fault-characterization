# gin-control: 복원 계층의 제어 평면을 RDMA로 통합한다

gin-restore와 gin-mirror의 복원 계층은 제어 메시지와 생존 판정을 관리망 소켓에 기대어, 멈춘 상대와 조용한 죽음을 잡지 못하거나 늦게 잡았다. 이 실험은 제어
기록을 rank 사이 RC 링으로, 생존 판정을 상대 상태 페이지의 RDMA READ와 21행 판정 표로, 되살리기를 노드 데몬(launcher)의 펜스 뒤로 옮기고, 판정 시간과 투명성과
비용을 잰다. 연구의 중심은 GPU가 직접 통신하는 실행에서 어떤 장애 정보가 사라지고, 생존 rank를 되돌리지 않고 실패한 rank를 안전하게 교체하려면 무엇이
필요한가이다([EXPERIMENT.md](EXPERIMENT.md) 1절 끝의 복구 계약).

**현재 단계(2026-10-23).** `DRAFT`, 사전 등록 전이다. 계층, launcher, 실행기와 채점기를 구현했고 실제 NIC에서 smoke 다섯 번을 돌렸다. pilot과 본 실험은
아직 없다. 지금 상태, 다음 작업, 막는 것은 [EXPERIMENT.md "현재 상태"](EXPERIMENT.md#현재-상태)가 기준이고, 이 README에는 따로 적지 않는다.

**smoke가 보인 것의 범위.** smoke는 셀마다 n 1–2이고 채점하지 않았다. 장치가 실제 NIC에서 끝까지 도는지 본 것이고 결과 주장이 아니다. 한 번씩 본 것은
다음과 같다. SIGKILL 뒤 판정, 펜스, 예비 프로세스 활성화, 복원이 로그에 그 차례로 남았고 데이터가 같았다. 12 s SIGSTOP과 GPU hang에서는 약 10 s 뒤 멈춤
판정 다음 같은 차례였다. exec 없이 fork한 자식이 죽은 rank의 RDMA 자원을 붙잡아 상태 페이지 READ가 계속 성공하는 경우를 찾았고, 그래서 사전 등록 전에
예측 하나의 셀을 바꿨다. smoke마다의 해설은 `results/<날짜>_smoke<k>/SMOKE.md`, 요약은 EXPERIMENT.md 12절 그날 행과 18절이다.

**결론과 결과.** 아직 없다. 본 실험과 QA 뒤 EXPERIMENT.md 15–17절에 쓰고, 이 README도 그때 결과 형식으로 다시 쓴다.

**파일.**
- [EXPERIMENT.md](EXPERIMENT.md): 기준 문서. 질문과 복구 계약 1절, 예측 3절, 셀 7절, 제외 기준 8절, 설계 9절, 작업 목록 11절, 실행 기록 12절, 한계 18절, 차례 19절.
- [NOTES.md](NOTES.md): 구현 파일과 빌드, 시험, 실행, 채점 경로.
- `results/`: smoke 해설(`SMOKE.md`)과 시도마다의 `trials.csv`. 원자료 로그는 저장소에 없고 release도 아직 없다.
- 앞 실험: [../restore/](../restore/), [../mirror/](../mirror/).
