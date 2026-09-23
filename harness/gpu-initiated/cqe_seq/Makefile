# cqe_seq: Q1 of the GPU-initiated study (CPU verbs, no GPU).
#   make                 cqe_seq_client (requester, rain)
#   make probe_server    the harness responder, UNCHANGED source (../../server), built
#                        into this directory (run_cqe_seq.sh does this on sunny)
CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -Werror -std=gnu11
HARNESS := ../..
CPPFLAGS += -I$(HARNESS)/common
LDLIBS  := -libverbs -lpthread -lrt

COMMON  := $(HARNESS)/common/probe.c
HDR     := $(HARNESS)/common/probe.h

all: cqe_seq_client

cqe_seq_client: cqe_seq_client.c $(COMMON) $(HDR)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ cqe_seq_client.c $(COMMON) $(LDLIBS)

probe_server: $(HARNESS)/server/probe_server.c $(COMMON) $(HDR)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $(HARNESS)/server/probe_server.c $(COMMON) $(LDLIBS)

clean:
	rm -f cqe_seq_client probe_server

.PHONY: all clean
