CC = gcc
CFLAGS = -Wall -O2
LDFLAGS = -libverbs -lpthread

# NOTE: verify_qp_state / verify_partial_write / verify_interrupted_write are
# client-side (225) driver programs; on the 224 responder only client.c,
# server.c and multi_server.c exist, so they are NOT build targets here.
all: client server multi_server

client: client.c common.h
	$(CC) $(CFLAGS) -o $@ client.c $(LDFLAGS)

# -msse4.2 enables the hardware CRC32C path in server.c (strategy-C VERIFY_CRC).
# The x86 Xeon supports it; server.c also carries a software fallback so it still
# builds without the flag. Harmless ISA enable for the existing handlers.
server: server.c common.h
	$(CC) $(CFLAGS) -msse4.2 -o $@ server.c $(LDFLAGS)

multi_server: multi_server.c common.h
	$(CC) $(CFLAGS) -o $@ multi_server.c $(LDFLAGS)

clean:
	rm -f client server multi_server

.PHONY: all clean
