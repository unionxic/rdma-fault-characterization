CC = gcc
CFLAGS = -Wall -O2 -I..
LDFLAGS = -libverbs -lpthread

all: client

client: client.c ../recovery_common.h ../../05_counter_mapping/common.h
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f client

.PHONY: all clean
