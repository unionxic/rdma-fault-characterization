# Makefile for Experiment 3: QP Recovery Overhead Decomposition (server side)
#
# Shares common.h, rdma_common.c/h with experiment1 via symlinks.
# Adds rdma_recovery.c/h for in-place QP state transitions.
# The client and the orchestrator are in 225-client/01_cpu_baseline/experiment3.

CC      := gcc
CFLAGS  := -O2 -Wall -Werror -std=gnu11
LDFLAGS := -libverbs -lrdmacm -lpthread -lm

COMMON_SRC := rdma_common.c rdma_recovery.c
COMMON_HDR := common.h common3.h rdma_common.h rdma_recovery.h

SERVER_SRC := server.c $(COMMON_SRC)

SERVER := server

.PHONY: all clean

all: $(SERVER)

$(SERVER): $(SERVER_SRC) $(COMMON_HDR)
	$(CC) $(CFLAGS) -o $@ server.c $(COMMON_SRC) $(LDFLAGS)
	@echo "Built: $@"

clean:
	rm -f $(SERVER)
	@echo "Cleaned build artifacts"
