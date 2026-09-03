# middleware server (224) — librdma_conn.a + librdma_fault.a 링크.
# rdma_conn은 분류 심볼(rdma_poll)을 참조하므로 server도 librdma_fault가 필요하다.
CC = gcc
CFLAGS = -Wall -O2 -I.. -I../07_fault_classify -I../06_recovery
LDLIBS = -libverbs

librdma_conn.a: rdma_conn.o
	ar rcs $@ rdma_conn.o

rdma_conn.o: rdma_conn.c rdma_conn.h
	$(CC) $(CFLAGS) -c rdma_conn.c

demo_server: demo_server.c librdma_conn.a ../07_fault_classify/librdma_fault.a
	$(CC) $(CFLAGS) -o $@ demo_server.c -L. -lrdma_conn -L../07_fault_classify -lrdma_fault $(LDLIBS)

clean:
	rm -f *.o *.a demo_server demo_client

.PHONY: clean
