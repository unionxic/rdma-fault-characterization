# Makefile for Experiment 1: RDMA Fault Detection Latency Baseline
#
# Part of: GPU-Initiated RDMA Fault Recovery Research
#
# Builds client (Server A) and server (Server B) binaries.
# Requires: libibverbs-dev, librdmacm-dev from rdma-core

CC      := gcc
CFLAGS  := -O2 -Wall -Werror -std=gnu11
LDFLAGS := -libverbs -lrdmacm -lpthread -lm

# Source files
COMMON_SRC := rdma_common.c
COMMON_HDR := common.h rdma_common.h

CLIENT_SRC := client.c $(COMMON_SRC)
SERVER_SRC := server.c $(COMMON_SRC)

# Targets
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

# Debug build (with symbols, no optimization, address sanitizer)
.PHONY: debug
debug: CFLAGS := -g -O0 -Wall -Werror -std=gnu11 -fsanitize=address
debug: LDFLAGS += -fsanitize=address
debug: clean all
	@echo "Built debug binaries with AddressSanitizer"

# Check that required libraries are installed
.PHONY: check-deps
check-deps:
	@echo "Checking dependencies..."
	@pkg-config --exists libibverbs 2>/dev/null && echo "  libibverbs: OK" || echo "  libibverbs: MISSING (install libibverbs-dev)"
	@pkg-config --exists librdmacm 2>/dev/null && echo "  librdmacm: OK" || echo "  librdmacm: MISSING (install librdmacm-dev)"
	@which ibv_devinfo >/dev/null 2>&1 && echo "  ibv_devinfo: OK" || echo "  ibv_devinfo: MISSING (install rdma-core)"
	@which ibstat >/dev/null 2>&1 && echo "  ibstat: OK" || echo "  ibstat: MISSING (install rdma-core)"
	@echo "Done."
