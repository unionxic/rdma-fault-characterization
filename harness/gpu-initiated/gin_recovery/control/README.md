# gin-control: 복원 계층의 제어와 생존 확인을 관리망 TCP에서 RDMA로 옮긴다

gin-restore와 gin-mirror의 복원 계층은 제어 메시지와 죽음 판정을 관리망의 TCP 소켓에 기대어, 멈춘 상대와 FIN 없는 죽음을 잡지 못하거나 늦게 잡았다. 이 실험은
제어를 데이터망 RDMA로 옮기고 상대의 상태 페이지를 RDMA READ로 읽어 생존을 판정하며, 노드마다의 launcher가 옛 프로세스를 끝낸 뒤에만 되살리는 설계를 세우고,
판정 시간, 투명성, 비용을 잰다.

상태: `DRAFT`(설계와 기존 장치와의 충돌 표, 구현 전). 기준 문서는 [EXPERIMENT.md](EXPERIMENT.md)이고, 이 README는 실험이 끝날 때 형식대로 다시 쓴다.
