# Makefile for Experiment 4: NIC Retry Boundary
# Reuses experiment1's server binary; only the client is built here.

CC      := gcc
CFLAGS  := -O2 -Wall -Werror -std=gnu11
LDFLAGS := -libverbs -lrdmacm -lpthread -lm

COMMON_SRC := rdma_common.c
COMMON_HDR := common.h rdma_common.h

CLIENT := client

.PHONY: all clean

all: $(CLIENT)

$(CLIENT): client.c $(COMMON_SRC) $(COMMON_HDR)
	$(CC) $(CFLAGS) -o $@ client.c $(COMMON_SRC) $(LDFLAGS)
	@echo "Built: $@"

clean:
	rm -f $(CLIENT)
