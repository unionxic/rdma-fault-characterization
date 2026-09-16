# Unified RDMA fault harness. Builds on both nodes (client + server + shared core).
CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -Werror -std=gnu11 -Icommon
LDLIBS  := -libverbs -lpthread -lrt

COMMON  := common/probe.c
HDR     := common/probe.h

all: probe_server probe_client

probe_server: server/probe_server.c $(COMMON) $(HDR)
	$(CC) $(CFLAGS) -o $@ server/probe_server.c $(COMMON) $(LDLIBS)

probe_client: client/probe_client.c $(COMMON) $(HDR)
	$(CC) $(CFLAGS) -o $@ client/probe_client.c $(COMMON) $(LDLIBS)

clean:
	rm -f probe_server probe_client

.PHONY: all clean
