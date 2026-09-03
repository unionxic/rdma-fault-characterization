# Makefile for Experiment 3: QP Recovery Overhead Decomposition
#
# Shares common.h, rdma_common.c/h with experiment1 via symlinks.
# Adds rdma_recovery.c/h for in-place QP state transitions.

CC      := gcc
CFLAGS  := -O2 -Wall -Werror -std=gnu11
LDFLAGS := -libverbs -lrdmacm -lpthread -lm

COMMON_SRC := rdma_common.c rdma_recovery.c
COMMON_HDR := common.h common3.h rdma_common.h rdma_recovery.h

CLIENT_SRC := client.c $(COMMON_SRC)
SERVER_SRC := server.c $(COMMON_SRC)

CLIENT := client
SERVER := server

.PHONY: all clean

all: $(CLIENT) $(SERVER)

$(CLIENT): $(CLIENT_SRC) $(COMMON_HDR)
	$(CC) $(CFLAGS) -o $@ client.c $(COMMON_SRC) $(LDFLAGS)
	@echo "Built: $@"

$(SERVER): $(SERVER_SRC) $(COMMON_HDR)
	$(CC) $(CFLAGS) -o $@ server.c $(COMMON_SRC) $(LDFLAGS)
	@echo "Built: $@"

clean:
	rm -f $(CLIENT) $(SERVER)
	@echo "Cleaned build artifacts"
