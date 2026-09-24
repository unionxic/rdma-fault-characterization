# ackt: RETRY_EXC detection vs IB ACK timeout tester (see README.md).
# Reuses the unified harness core (../common/probe.c) read-only.
CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -Werror -std=gnu11 -I../common
LDLIBS  := -libverbs -lpthread -lrt
OUT     ?= .

all: $(OUT)/ackt

$(OUT)/ackt: src/ackt.c ../common/probe.c ../common/probe.h
	$(CC) $(CFLAGS) -o $@ src/ackt.c ../common/probe.c $(LDLIBS)

clean:
	rm -f $(OUT)/ackt

.PHONY: all clean
