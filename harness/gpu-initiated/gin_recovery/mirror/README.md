# gin-mirror: 보낸 버퍼를 다시 쓰는 application에서도 죽은 rank를 되살린다

gin-restore의 재실행은 보낸 쪽 원본 버퍼를 다시 읽으므로, 보낸 버퍼를 단계마다 다시 쓰는 application에서는 바뀐 내용을 다시 넣는다. 이 실험은
보내는 rank의 NIC이 put의 내용을 받는 rank의 짝 호스트 메모리에 한 번 더 써 두고 복원이 그 사본을 쓰게 하는 설계를 세우고, 정확성과 비용을 잰다.

상태: `DRAFT`(설계와 기존 장치와의 충돌 표, 구현 전). 기준 문서는 [EXPERIMENT.md](EXPERIMENT.md)이고, 이 README는 실험이 끝날 때 형식대로 다시 쓴다.
