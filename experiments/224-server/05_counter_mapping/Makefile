CC = gcc
CFLAGS = -Wall -O2
LDFLAGS = -libverbs -lpthread

all: client server multi_server verify_qp_state verify_partial_write

client: client.c common.h
	$(CC) $(CFLAGS) -o $@ client.c $(LDFLAGS)

# -msse4.2 enables the hardware CRC32C path in server.c (strategy-C VERIFY_CRC).
# The x86 Xeon supports it; server.c also carries a software fallback so it still
# builds without the flag. Harmless ISA enable for the existing handlers.
server: server.c common.h
	$(CC) $(CFLAGS) -msse4.2 -o $@ server.c $(LDFLAGS)

multi_server: multi_server.c common.h
	$(CC) $(CFLAGS) -o $@ multi_server.c $(LDFLAGS)

verify_qp_state: verify_qp_state.c common.h
	$(CC) $(CFLAGS) -o $@ verify_qp_state.c $(LDFLAGS)

verify_partial_write: verify_partial_write.c common.h
	$(CC) $(CFLAGS) -o $@ verify_partial_write.c $(LDFLAGS)

clean:
	rm -f client server multi_server verify_qp_state verify_partial_write

.PHONY: all clean
