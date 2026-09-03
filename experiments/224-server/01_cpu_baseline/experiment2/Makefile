# Makefile for Experiment 2: CPU Polling Interval Blind Window
#
# Part of: GPU-Initiated RDMA Fault Recovery Research
#
# Builds only the client binary. The server binary from experiment1 is
# reused directly (no server.c in this experiment).
#
# Shared source files (common.h, rdma_common.h, rdma_common.c) are
# symlinked from ../experiment1/.

CC      := gcc
CFLAGS  := -O2 -Wall -Werror -std=gnu11
LDFLAGS := -libverbs -lrdmacm -lpthread -lm

COMMON_SRC := rdma_common.c
COMMON_HDR := common.h rdma_common.h

CLIENT_SRC := client.c $(COMMON_SRC)
CLIENT     := client

.PHONY: all clean check-deps check-symlinks

all: check-symlinks $(CLIENT)

$(CLIENT): $(CLIENT_SRC) $(COMMON_HDR)
	$(CC) $(CFLAGS) -o $@ client.c $(COMMON_SRC) $(LDFLAGS)
	@echo "Built: $@"

check-symlinks:
	@test -L common.h && test -e common.h || \
		{ echo "ERROR: common.h symlink missing. Run: ln -s ../experiment1/common.h ."; exit 1; }
	@test -L rdma_common.h && test -e rdma_common.h || \
		{ echo "ERROR: rdma_common.h symlink missing. Run: ln -s ../experiment1/rdma_common.h ."; exit 1; }
	@test -L rdma_common.c && test -e rdma_common.c || \
		{ echo "ERROR: rdma_common.c symlink missing. Run: ln -s ../experiment1/rdma_common.c ."; exit 1; }

clean:
	rm -f $(CLIENT)
	@echo "Cleaned build artifacts"

.PHONY: debug
debug: CFLAGS := -g -O0 -Wall -Werror -std=gnu11 -fsanitize=address
debug: LDFLAGS += -fsanitize=address
debug: clean all

check-deps:
	@echo "Checking dependencies..."
	@pkg-config --exists libibverbs 2>/dev/null && echo "  libibverbs: OK" || echo "  libibverbs: MISSING"
	@pkg-config --exists librdmacm 2>/dev/null && echo "  librdmacm: OK" || echo "  librdmacm: MISSING"
	@test -x ../experiment1/server && echo "  experiment1/server: OK" || echo "  experiment1/server: MISSING (build experiment1 first)"
	@echo "Done."
