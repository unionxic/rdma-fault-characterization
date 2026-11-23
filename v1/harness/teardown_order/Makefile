# Build all three programs on rain (CUDA 12.8); fp_launcher and fp_responder are
# copied to sunny (~/fp-bundle/) by run_variant.sh. cudart is linked statically so
# the victim does not depend on the CUDA runtime installed on the responder node;
# libcuda.so.1 comes from the responder's driver.
CUDA    ?= /usr/local/cuda-12.8
CFLAGS  ?= -O2 -g -Wall -Wextra -Werror -std=gnu11
LDLIBS  := -lmlx5 -libverbs

all: fp_requester fp_launcher fp_responder

fp_requester: fp_requester.c fp_common.c fp_common.h
	$(CC) $(CFLAGS) -o $@ fp_requester.c fp_common.c $(LDLIBS)

fp_launcher: fp_launcher.c fp_common.c fp_common.h
	$(CC) $(CFLAGS) -o $@ fp_launcher.c fp_common.c $(LDLIBS)

fp_responder: fp_responder.c fp_common.c fp_common.h fp_devx.c fp_devx.h
	$(CC) $(CFLAGS) -I$(CUDA)/include -o $@ fp_responder.c fp_common.c fp_devx.c \
	    $(CUDA)/lib64/libcudart_static.a -L$(CUDA)/lib64/stubs -lcuda $(LDLIBS) -ldl -lpthread -lrt

clean:
	rm -f fp_requester fp_launcher fp_responder

.PHONY: all clean
