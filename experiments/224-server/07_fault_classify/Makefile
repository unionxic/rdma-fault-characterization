CC = gcc
CFLAGS = -Wall -O2 -fPIC
LDFLAGS = -libverbs

all: librdma_fault.a test_classify

rdma_fault.o: rdma_fault.c rdma_fault.h
	$(CC) $(CFLAGS) -c rdma_fault.c

# 재사용 가능한 정적 라이브러리. 다른 프로그램은 이걸 -L. -lrdma_fault 로 링크한다.
librdma_fault.a: rdma_fault.o
	ar rcs $@ rdma_fault.o

# 분류 단위 테스트 (실제 RDMA 불필요, 가짜 wc로 분류만 검증)
test_classify: test_classify.c librdma_fault.a rdma_fault.h
	$(CC) $(CFLAGS) -o $@ test_classify.c -L. -lrdma_fault $(LDFLAGS)

test: test_classify
	./test_classify

clean:
	rm -f *.o *.a test_classify

.PHONY: all test clean
