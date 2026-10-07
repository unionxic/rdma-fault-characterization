# completion_contract score

Scored by `score.py` against `predictions.csv` (tag prereg/completion-contract-v1). Per-trial values: `trials_scored.csv`.

| 예측 | n | 맞음 | 판정 | 놓친 시행 | 따로 센 시행 |
|---|--:|--:|---|---|---|
| NVSHMEM 3.4.5 CPU 프록시, 상대 kill: 죽은 뒤 첫 반복이 3–5 s에 돌아온다(10회 중 9회 이상, 30 s 넘는 시행 0회), 쓴 그대로 (P1 (a)) | 10 | 0 | **fails** | ahinit_cpu_host_memory_kill1_t1, ahinit_cpu_host_memory_kill1_t2, ahinit_cpu_host_memory_kill1_t3, ahinit_cpu_host_memory_kill1_t4, ahinit_cpu_host_memory_kill1_t5, ahinit_cpu_host_memory_kill1_t6, ahinit_cpu_host_memory_kill1_t7, ahinit_cpu_host_memory_kill1_t8, ahinit_cpu_host_memory_kill1_t9, ahinit_cpu_host_memory_kill1_t10 |  |
| 같은 예측, 3.4.5의 고정 타임아웃 20에 맞춘 창 50–70 s(90 s 넘는 시행 0회) (P1 (b)) | 10 | 10 | **holds** |  |  |
| NVSHMEM 3.4.5 GPU 처리, 상대 kill: 같다(5/5), 쓴 그대로 (P2 (a)) | 5 | 0 | **fails** | stock_gpu_kill1_t1, stock_gpu_kill1_t2, stock_gpu_kill1_t3, stock_gpu_kill1_t4, stock_gpu_kill1_t5 |  |
| 같은 예측, 창 50–70 s (P2 (b)) | 5 | 5 | **holds** |  |  |
| NVSHMEM 3.4.5 CPU 프록시, 장애 없음: 모든 반복이 돌아온다(5/5) (P3) | 5 | 5 | **holds** |  |  |
| NCCL GDAKI BlueFlame 처리 방식, 장애 없음: 첫 반복이 시간 초과, 받는 쪽 데이터 없음(10회 중 9회 이상, 정상 완료 0회) (P4) | 10 | 10 | **holds** |  |  |
| NCCL GDAKI 기본 처리 방식, 장애 없음: 모두 정상 완료(5/5) (P5) | 5 | 5 | **holds** |  |  |
| NCCL GDAKI CPU 프록시 처리 방식, 로컬 QP 오류: 호스트 오류가 나온다(5/5) (P6 F1) | 5 | 5 | **holds** |  |  |
| NCCL GDAKI CPU 프록시 처리 방식, 원격 접근 오류: 호스트 오류가 나온다(5/5) (P6 F2) | 5 | 5 | **holds** |  |  |
| NCCL GDAKI CPU 프록시 처리 방식, 상대 QP 오류: 호스트 오류가 나온다(5/5) (P6 F3) | 5 | 5 | **holds** |  |  |
| NCCL GDAKI CPU 프록시 처리 방식, 장애 없음: 오류 없이 정상 완료(5/5) (P7) | 5 | 5 | **holds** |  |  |
