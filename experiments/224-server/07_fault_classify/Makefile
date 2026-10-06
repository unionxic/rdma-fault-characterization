CC = gcc
CFLAGS = -Wall -O2 -fPIC
LDFLAGS = -libverbs

# 224 쪽은 08_middleware의 demo_server가 링크할 라이브러리만 만든다.
# 분류 단위 테스트(test_classify)는 225-client/07_fault_classify에 있다.
all: librdma_fault.a

rdma_fault.o: rdma_fault.c rdma_fault.h
	$(CC) $(CFLAGS) -c rdma_fault.c

# 재사용 가능한 정적 라이브러리. 다른 프로그램은 이걸 -L. -lrdma_fault 로 링크한다.
librdma_fault.a: rdma_fault.o
	ar rcs $@ rdma_fault.o

clean:
	rm -f *.o *.a

.PHONY: all clean
