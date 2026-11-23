# Makefile for Experiment 3: QP Recovery Overhead Decomposition (client side)
#
# Shares common.h, rdma_common.c/h with experiment1 via symlinks.
# Adds rdma_recovery.c/h for in-place QP state transitions.
# The server is in 224-server/01_cpu_baseline/experiment3 and runs on the responder.

CC      := gcc
CFLAGS  := -O2 -Wall -Werror -std=gnu11
LDFLAGS := -libverbs -lrdmacm -lpthread -lm

COMMON_SRC := rdma_common.c rdma_recovery.c
COMMON_HDR := common.h common3.h rdma_common.h rdma_recovery.h

CLIENT_SRC := client.c $(COMMON_SRC)

CLIENT := client

.PHONY: all clean

all: $(CLIENT)

$(CLIENT): $(CLIENT_SRC) $(COMMON_HDR)
	$(CC) $(CFLAGS) -o $@ client.c $(COMMON_SRC) $(LDFLAGS)
	@echo "Built: $@"

clean:
	rm -f $(CLIENT)
	@echo "Cleaned build artifacts"
