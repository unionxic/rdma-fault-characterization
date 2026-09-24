CC ?= gcc
CFLAGS ?= -O2 -g -Wall -Wextra -Werror
LDLIBS = -libverbs -lmlx5

all: tr_probe

tr_probe: tr_probe.c tr_prm.h
	$(CC) $(CFLAGS) -o $@ tr_probe.c $(LDLIBS)

clean:
	rm -f tr_probe

.PHONY: all clean
