# middleware server (224) — librdma_conn.a + librdma_fault.a 링크.
# rdma_conn은 분류 심볼(rdma_poll)을 참조하므로 server도 librdma_fault가 필요하다.
CC = gcc
CFLAGS = -Wall -O2 -I.. -I../07_fault_classify -I../06_recovery
LDLIBS = -libverbs

FAULT_LIB = ../07_fault_classify/librdma_fault.a

all: librdma_conn.a demo_server

librdma_conn.a: rdma_conn.o
	ar rcs $@ rdma_conn.o

rdma_conn.o: rdma_conn.c rdma_conn.h ../07_fault_classify/rdma_fault.h \
	     ../06_recovery/recovery_common.h ../05_counter_mapping/common.h
	$(CC) $(CFLAGS) -c rdma_conn.c

# Build the classification lib if it (or its sources) is out of date.
$(FAULT_LIB): ../07_fault_classify/rdma_fault.c ../07_fault_classify/rdma_fault.h
	$(MAKE) -C ../07_fault_classify librdma_fault.a

demo_server: demo_server.c librdma_conn.a $(FAULT_LIB)
	$(CC) $(CFLAGS) -o $@ demo_server.c -L. -lrdma_conn -L../07_fault_classify -lrdma_fault $(LDLIBS)

clean:
	rm -f *.o *.a demo_server demo_client

.PHONY: all clean
