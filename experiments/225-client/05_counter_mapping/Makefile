CC = gcc
CFLAGS = -Wall -O2
LDFLAGS = -libverbs -lpthread

all: client server multi_client verify_qp_state verify_partial_write verify_interrupted_write ab_recovery silent_strategy

client: client.c common.h
	$(CC) $(CFLAGS) -o $@ client.c $(LDFLAGS)

multi_client: multi_client.c common.h multi_common.h
	$(CC) $(CFLAGS) -o $@ multi_client.c $(LDFLAGS)

server: server.c common.h
	$(CC) $(CFLAGS) -o $@ server.c $(LDFLAGS)

verify_qp_state: verify_qp_state.c common.h
	$(CC) $(CFLAGS) -o $@ verify_qp_state.c $(LDFLAGS)

verify_partial_write: verify_partial_write.c common.h
	$(CC) $(CFLAGS) -o $@ verify_partial_write.c $(LDFLAGS)

verify_interrupted_write: verify_interrupted_write.c common.h
	$(CC) $(CFLAGS) -o $@ verify_interrupted_write.c $(LDFLAGS)

ab_recovery: ab_recovery.c common.h
	$(CC) $(CFLAGS) -o $@ ab_recovery.c $(LDFLAGS)

# -msse4.2: hardware CRC32C (_mm_crc32_u64) for strategy C2. Software fallback
# present so it still builds without the flag, but the server (224) and this
# client MUST use the same path to agree on crc values -> both get -msse4.2.
silent_strategy: silent_strategy.c common.h
	$(CC) $(CFLAGS) -msse4.2 -o $@ silent_strategy.c $(LDFLAGS)

clean:
	rm -f client server multi_client verify_qp_state verify_partial_write verify_interrupted_write ab_recovery silent_strategy

.PHONY: all clean
