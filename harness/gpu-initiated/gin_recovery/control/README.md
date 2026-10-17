# gin-control: 복원 계층의 제어 평면을 RDMA로 통합한다

gin-restore와 gin-mirror의 복원 계층은 제어 메시지와 생존 판정을 관리망 소켓에 기대어, 멈춘 상대와 조용한 죽음을 잡지 못하거나 늦게 잡았다. 이 실험은 제어
기록을 rank 사이 RC 링으로, 생존 판정을 상대 상태 페이지의 RDMA READ와 21행 판정 표로, 되살리기를 노드 데몬(launcher)의 펜스 뒤로 옮기고, 판정 시간과 투명성과
비용을 잰다.

상태: `DRAFT`, **RDMA 제어 평면 통합 구축 진행 중**. 준비 단계, 상태 페이지와 READ 감지, 링과 짝 맺기, mirror 끈 저장소, launcher와 rank 쪽 연결, 실행기와
채점기가 CPU 빌드와 단위 시험까지 끝났고, 한 트리로 합치는 중이다. 클러스터 실행은 아직 없다. 기준 문서는 [EXPERIMENT.md](EXPERIMENT.md)이고, 이 README는
실험이 끝날 때 형식대로 다시 쓴다.
