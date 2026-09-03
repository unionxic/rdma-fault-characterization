# verify server (224) — 분류 라이브러리 불필요(fault 조건만 만든다).
CC = gcc
CFLAGS = -Wall -O2 -I..
LDLIBS = -libverbs

server: server.c ../05_counter_mapping/common.h
	$(CC) $(CFLAGS) -o $@ server.c $(LDLIBS)

clean:
	rm -f server

.PHONY: clean
