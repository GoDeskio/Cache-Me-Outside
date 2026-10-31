# Time-series module. The .so is loaded with MODULE LOAD. chunk_test is a
# standalone compressor check and does not link the server.

uname_S := $(shell sh -c 'uname -s 2>/dev/null || echo not')

ifeq ($(uname_S),Linux)
	SHOBJ_CFLAGS ?= -W -Wall -Wno-missing-field-initializers -fno-common -g -ggdb -std=gnu11 -O2
	SHOBJ_LDFLAGS ?= -shared
	LD ?= gcc
	CC ?= gcc
else
	SHOBJ_CFLAGS ?= -W -Wall -Wno-missing-field-initializers -dynamic -fno-common -g -ggdb -std=gnu11 -O2
	SHOBJ_LDFLAGS ?= -bundle -undefined dynamic_lookup
	LD ?= $(CC)
endif

CFLAGS_MOD = -I. -I../../src $(CFLAGS) $(SHOBJ_CFLAGS) -fPIC

.PHONY: all clean

all: timeseries.so chunk_test

chunk.o: chunk.c chunk.h
	$(CC) $(CFLAGS_MOD) -c chunk.c -o chunk.o

query.o: query.c chunk.h
	$(CC) $(CFLAGS_MOD) -c query.c -o query.o

ts.o: ts.c chunk.h
	$(CC) $(CFLAGS_MOD) -c ts.c -o ts.o

timeseries.so: ts.o chunk.o query.o
	$(LD) -o $@ ts.o chunk.o query.o $(SHOBJ_LDFLAGS) $(LIBS) -lm

chunk_test: chunk_test.c chunk.c chunk.h
	$(CC) -I. -std=gnu11 -Wall -Wextra -O2 -g -o $@ chunk_test.c chunk.c -lm

clean:
	rm -f *.o timeseries.so chunk_test
