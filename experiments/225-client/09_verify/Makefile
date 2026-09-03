# verify client (225) — 분류 라이브러리(librdma_fault.a)를 링크한다.
CC = gcc
CFLAGS = -Wall -O2 -I.. -I../07_fault_classify
LDLIBS = -libverbs

client: client.c ../05_counter_mapping/common.h ../07_fault_classify/rdma_fault.h ../07_fault_classify/librdma_fault.a
	$(CC) $(CFLAGS) -o $@ client.c -L../07_fault_classify -lrdma_fault $(LDLIBS)

clean:
	rm -f client

.PHONY: clean
