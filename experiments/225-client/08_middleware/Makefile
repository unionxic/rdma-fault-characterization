# middleware client (225) — librdma_conn.a + librdma_fault.a 링크.
CC = gcc
CFLAGS = -Wall -O2 -I.. -I../07_fault_classify -I../06_recovery
LDLIBS = -libverbs

FAULT_LIB = ../07_fault_classify/librdma_fault.a

all: librdma_conn.a demo_client

librdma_conn.a: rdma_conn.o
	ar rcs $@ rdma_conn.o

rdma_conn.o: rdma_conn.c rdma_conn.h ../07_fault_classify/rdma_fault.h \
	     ../06_recovery/recovery_common.h ../05_counter_mapping/common.h
	$(CC) $(CFLAGS) -c rdma_conn.c

# Build the classification lib if it (or its sources) is out of date.
$(FAULT_LIB): ../07_fault_classify/rdma_fault.c ../07_fault_classify/rdma_fault.h
	$(MAKE) -C ../07_fault_classify librdma_fault.a

# rdma_conn은 rdma_poll/rdma_classify(librdma_fault)를 참조하므로 둘 다 링크.
demo_client: demo_client.c librdma_conn.a $(FAULT_LIB)
	$(CC) $(CFLAGS) -o $@ demo_client.c -L. -lrdma_conn -L../07_fault_classify -lrdma_fault $(LDLIBS)

clean:
	rm -f *.o *.a demo_client demo_server

.PHONY: all clean
