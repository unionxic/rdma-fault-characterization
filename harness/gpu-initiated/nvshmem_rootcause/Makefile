CC ?= gcc
CFLAGS ?= -O2 -g -Wall -Wextra -Werror
LDLIBS = -libverbs -lmlx5

all: nrc_devx

nrc_devx: nrc_devx.c nrc_prm.h
	$(CC) $(CFLAGS) -o $@ nrc_devx.c $(LDLIBS)

clean:
	rm -f nrc_devx

.PHONY: all clean
