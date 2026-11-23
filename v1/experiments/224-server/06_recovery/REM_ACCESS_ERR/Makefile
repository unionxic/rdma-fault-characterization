CC = gcc
CFLAGS = -Wall -O2 -I..
LDFLAGS = -libverbs -lpthread

all: server

server: server.c ../recovery_common.h ../../05_counter_mapping/common.h
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f server

.PHONY: all clean
