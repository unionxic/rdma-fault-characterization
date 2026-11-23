# blind-apps 채점

score.py가 만든 파일이다. 손으로 고치지 않는다.

## 봉인과 입력

- schedule sha256 ff04f71187601c36, PREREG.txt ff04f71187601c36: same
- schedule_gen.py verify: OK
- blind trials whose recorded entry differs from the schedule: 0 []
- scheduled trials without a result: 0 []
- DDP reference sha256 per rank: {0: '9d051c49d3ebdcc3', 1: '9d051c49d3ebdcc3'} (agree)
- judgments /home/unionxic/rdma-error-wt/blind-apps/harness/blind/results/20261009/judgments.csv sha256 afb3ae06de9254b6b8bef419390e786c97286807e46e9b8e6ec518ac3b24a807

## 예측별 판정

| id | 종류 | 선택 | 판정 | n | 식(값 대입) | 거짓인 시행 |
|---|---|---|---|--:|---|---|
| D1 | S | `ddp:none` | 맞음 | 8 | `8 >= n - 1` | outcome == "TRANSPARENT": - |
| D2 | S | `ddp:sqp` | 맞음 | 10 | `10 >= ceil(0.9 * n)` | outcome == "TRANSPARENT" and n_rec >= 1: - |
| D3 | S | `ddp:rqp` | 맞음 | 10 | `10 >= ceil(0.9 * n)` | outcome == "TRANSPARENT" and n_rec >= 1: - |
| D4 | S | `ddp:srq` | 틀림 | 6 | `0 >= n - 2 and 6 == n` | outcome == "HUNG" and timeout_first == 1 and dt_err <= 45: 37f61f7b,55f19881,a27938a8,a5497f6d,b3596cab,fb20e695; outcome in ("HUNG", "TRANSPARENT"): - |
| D5 | S | `ddp:kill` | 맞음 | 8 | `8 >= n - 1` | outcome == "DECLINED" and dt_err <= 5 and dt_end <= 20: - |
| D6 | S | `ddp:stop` | 맞음 | 8 | `8 >= n - 1` | outcome == "TRANSPARENT" and n_death == 0: - |
| D7 | S | `ddp:mute` | 맞음 | 6 | `6 >= n - 1` | outcome == "TRANSPARENT" and n_death == 0: - |
| G1 | S | `gin:none` | 맞음 | 8 | `8 >= n - 1` | outcome == "TRANSPARENT": - |
| G2 | S | `gin:qperr` | 틀림 | 16 | `2 >= ceil(0.85 * n)` | outcome == "TRANSPARENT" and n_rec >= 1: 1f3a059c,2985f04b,46548938,4697f8f1,5cc2b822,93b96765,a4157450,b11ce946,be33f162,cbeece3e,d3b36aba,e1a39229,e5b41fdd,ed8a659a |
| G3 | S | `gin:kill` | 맞음 | 10 | `10 == n and 10 >= n - 1` | outcome in ("DECLINED", "HUNG"): -; dt_err <= 5: - |
| G4 | S | `gin:stop` | 맞음 | 10 | `10 >= n - 1` | outcome == "TRANSPARENT" and n_death == 0: - |
| G5 | S | `gin:mute` | 맞음 | 12 | `12 >= n - 2` | outcome == "TRANSPARENT" and n_death == 0: - |
| N1 | S | `nvs:none` | 맞음 | 8 | `8 >= n - 1` | outcome == "TRANSPARENT": - |
| N2 | S | `nvs:qperr` | 맞음 | 14 | `14 >= ceil(0.85 * n)` | outcome == "TRANSPARENT" and n_rec >= 1: - |
| N3 | S | `nvs:remacc` | 맞음 | 8 | `8 == n and 8 >= n - 1` | outcome in ("DECLINED", "HUNG"): -; dt_err <= 3: - |
| N4 | S | `nvs:kill` | 틀림 | 7 | `7 == n and 0 >= n - 1` | outcome in ("DECLINED", "HUNG"): -; dt_err <= 3: 21a06d5e,2f9ea2f0,6fd46a59,76712ff9,929d7e4b,bdc23a73,d047aadd |
| N5 | S | `nvs:stop` | 틀림 | 7 | `5 >= n - 1` | outcome == "TRANSPARENT" and n_death == 0: 37bd4c3d,800579c9 |
| N6 | S | `nvs:mute` | 맞음 | 6 | `6 >= n - 1` | outcome == "TRANSPARENT" and n_death == 0: - |
| X1 | S | `gin:*+nvs:*` | 틀림 | 106 | `2 == 0` | outcome == "SILENT_WRONG": 01b1e4de,02cdcf6e,072436e2,087042c4,0c39f264,16d4f188,1c53ff53,1f215dc7,1f3a059c,2110ff21,21a06d5e,26186903,26569698,2917ca09,2985f04b,2b9ee5a1,2f25fbbd,2f9ea2f0,31931f8f,31d1a0b1,373e7f03,3fa9efe0,3fd25800,401d627f,46548938,4697f8f1,4730fa06,50b1ee08,52612053,54f4eacd,557f5388,55fa6493,5b41efa1,5b434150,5cc2b822,63e81d2a,673c0940,6f1e1436,6fd46a59,7538e907,7614d2ac,76712ff9,767c64bc,76dced25,77ce7ec4,80b0e284,81718e63,8a13fdcd,8e9aefc9,912a5e0e,91596709,920f63f0,929d7e4b,93b96765,98f780ef,990cf62f,9de3c621,9fbfecaa,a0d64814,a12a8def,a3b9c7be,a4157450,a4be5433,ac3281ef,ac3f9861,ad469aca,afffcaba,b11ce946,b29e12db,b5b7e060,b9acd57e,bbbe4795,bd0e9205,bdc23a73,be33f162,be9e8f24,c082f02e,c09b8f90,c2b466da,c39b768b,c6c09d83,c83766de,cbeece3e,d047aadd,d21d7a88,d272651a,d3b36aba,d41df043,d4c78b66,d58e960b,dd65aa32,de94807c,e1a39229,e20b80f2,e303601e,e392a0dd,e5b41fdd,e6515f7d,e89250ce,ed8a659a,ee951050,ef3878e1,f91cd813,fc2c1bd7 |
| X2 | S | `ddp:*` | 맞음 | 56 | `0 == 0` | outcome == "SILENT_WRONG": 08abd11c,1051552a,14b53b80,17c44ef4,2213fe62,25277b30,2da6c3bf,37f61f7b,39157764,3c4b5ea8,40cf0279,42ccd0c4,4b4069cd,4b99dd0a,51031ab3,526f5e19,55f19881,66925fa7,67d07f50,68cd5cee,6d031cad,713f4748,74d999b1,753e63ae,7f1ed43a,85ddb86e,8a85d9e2,8b6b2848,9246c035,99ff04ad,9dd7d30d,a0d8988c,a1f9b58f,a27938a8,a5497f6d,a6a93f41,a8607fe2,ac6e8117,b0a59128,b16bf1c7,b3596cab,b3e21f6d,b89b7575,bbeabcee,c39b9f83,d0d42caf,d0f237cb,e031cd26,e0aca552,e0b7f5e4,e599a827,e912f461,eaa902ae,edad63f4,f3e32915,fb20e695 |
| E1 | E | `*:*` | 맞음 | 162 | `162 >= ceil(0.85 * n)` | j_ok_outcome == 1: - |
| E2 | E | `ddp:sqp+ddp:rqp+gin:qperr+nvs:qperr` | 맞음 | 50 | `50 >= ceil(0.8 * n)` | j_ok_class == 1: - |
| E3 | E | `ddp:kill+gin:kill+nvs:kill` | 맞음 | 25 | `25 >= ceil(0.9 * n)` | j_ok_class == 1: - |
| E4 | E | `*:none` | 맞음 | 24 | `24 >= ceil(0.75 * n)` | j_class == "none": - |
| E5 | E | `ddp:stop+ddp:mute` | 맞음 | 14 | `11 >= ceil(0.6 * n)` | j_ok_class == 1: 8a85d9e2,9246c035,edad63f4 |

판정 수: 맞음 20, 틀림 5

## 제외와 무효(따로 셈)

| 작업 | 장애 | 계획 | 유효 | 미적용 | 시작 실패 |
|---|---|--:|--:|--:|--:|
| ddp | kill | 8 | 8 | 0 | 0 |
| ddp | mute | 6 | 6 | 0 | 0 |
| ddp | none | 8 | 8 | 0 | 0 |
| ddp | rqp | 10 | 10 | 0 | 0 |
| ddp | sqp | 10 | 10 | 0 | 0 |
| ddp | srq | 6 | 6 | 0 | 0 |
| ddp | stop | 8 | 8 | 0 | 0 |
| gin | kill | 10 | 10 | 0 | 0 |
| gin | mute | 12 | 12 | 0 | 0 |
| gin | none | 8 | 8 | 0 | 0 |
| gin | qperr | 16 | 16 | 0 | 0 |
| gin | stop | 10 | 10 | 0 | 0 |
| nvs | kill | 8 | 7 | 1 | 0 |
| nvs | mute | 8 | 6 | 2 | 0 |
| nvs | none | 8 | 8 | 0 | 0 |
| nvs | qperr | 14 | 14 | 0 | 0 |
| nvs | remacc | 8 | 8 | 0 | 0 |
| nvs | stop | 8 | 7 | 1 | 0 |
