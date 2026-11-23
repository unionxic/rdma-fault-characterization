# evrec: async-event and port-counter recorder for one RDMA device (see NOTES.md).
CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -Werror -std=gnu11
LDLIBS  := -libverbs

all: evrec

evrec: evrec.c
	$(CC) $(CFLAGS) -o $@ evrec.c $(LDLIBS)

clean:
	rm -f evrec

.PHONY: all clean
