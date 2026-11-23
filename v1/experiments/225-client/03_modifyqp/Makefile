CC      := gcc
CFLAGS  := -O2 -Wall -Werror -std=gnu11
LDFLAGS := -libverbs -lrdmacm -lpthread -lm

.PHONY: all clean

all: client

client: client.c rdma_common.c common.h rdma_common.h
	$(CC) $(CFLAGS) -o $@ client.c rdma_common.c $(LDFLAGS)

clean:
	rm -f client
