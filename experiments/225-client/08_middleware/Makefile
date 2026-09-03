# middleware client (225) — librdma_conn.a + librdma_fault.a 링크.
CC = gcc
CFLAGS = -Wall -O2 -I.. -I../07_fault_classify -I../06_recovery
LDLIBS = -libverbs

librdma_conn.a: rdma_conn.o
	ar rcs $@ rdma_conn.o

rdma_conn.o: rdma_conn.c rdma_conn.h
	$(CC) $(CFLAGS) -c rdma_conn.c

# rdma_conn은 rdma_poll/rdma_classify(librdma_fault)를 참조하므로 둘 다 링크.
demo_client: demo_client.c librdma_conn.a ../07_fault_classify/librdma_fault.a
	$(CC) $(CFLAGS) -o $@ demo_client.c -L. -lrdma_conn -L../07_fault_classify -lrdma_fault $(LDLIBS)

clean:
	rm -f *.o *.a demo_client demo_server

.PHONY: clean
