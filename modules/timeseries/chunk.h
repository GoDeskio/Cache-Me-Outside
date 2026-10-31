/* Time-series chunks and the in-memory series object.
 *
 * Sample compression follows the published Gorilla scheme
 * (Pelkonen et al., "Gorilla: A Fast, Scalable, In-Memory Time Series
 * Database", SIGMOD 2015): delta-of-delta timestamps and XOR'd doubles.
 * The bit layout is our own reading of that paper. A delta that does not
 * fit in 32 bits is stored in 64 bits so a chunk can hold any millisecond
 * timestamp. Nothing here is taken from another time-series product.
 *
 * Copyright (c) 2026, Cache Me Outside contributors.
 * Licensed under the BSD 3-Clause License, the same terms as the server.
 */
#ifndef CMO_TS_CHUNK_H
#define CMO_TS_CHUNK_H

#include <stddef.h>
#include <stdint.h>

#define TS_CHUNK_DEFAULT_BYTES 4096
#define TS_CHUNK_MIN_BYTES 128
#define TS_CHUNK_MAX_BYTES 65536

enum {
  TS_DUP_BLOCK = 0,
  TS_DUP_FIRST = 1,
  TS_DUP_LAST = 2,
  TS_DUP_MIN = 3,
  TS_DUP_MAX = 4,
  TS_DUP_SUM = 5
};

enum {
  TS_AGG_NONE = 0,
  TS_AGG_AVG = 1,
  TS_AGG_SUM = 2,
  TS_AGG_MIN = 3,
  TS_AGG_MAX = 4,
  TS_AGG_COUNT = 5,
  TS_AGG_FIRST = 6,
  TS_AGG_LAST = 7
};

typedef struct tsSample {
  int64_t ts;
  double value;
} tsSample;

typedef struct tsChunk tsChunk;

struct tsChunk {
  tsChunk *next;
  int64_t first_ts;
  int64_t last_ts;
  uint32_t count;
  size_t
      cap; /* Target size. A sample that would pass this starts a new chunk. */
  size_t alloc; /* Bytes allocated for data. May exceed cap to finish one
                   sample. */
  uint32_t nbits;
  unsigned char *data;
  int64_t prev_ts;
  int64_t prev_delta;
  uint64_t prev_value_bits;
  uint8_t prev_leading;
  uint8_t prev_trailing;
  int has_value_window;
  int has_prev;
};

typedef struct tsLabel {
  char *key;
  char *val;
} tsLabel;

typedef struct tsSeries tsSeries;

struct tsSeries {
  int64_t retention_ms;
  int dup_policy;
  size_t chunk_size;
  uint64_t total_samples;
  tsChunk *head;
  tsChunk *tail;
  int nlabels;
  tsLabel *labels;
  int64_t last_ts;
  double last_value;
  int has_sample;
  char *key;
  size_t key_len;
};

tsChunk *tsChunkCreate(size_t cap);
void tsChunkFree(tsChunk *c);
/* 0 appended, 1 chunk is full and the sample was not written, -1 error. */
int tsChunkAppend(tsChunk *c, int64_t ts, double value);
int tsChunkDecode(const tsChunk *c, tsSample **out, uint32_t *n);
int tsChunkRecompress(tsChunk *c, const tsSample *samples, uint32_t n);
size_t tsChunkBytes(const tsChunk *c);

size_t tsSeriesStorageBytes(const tsSeries *s);
int tsSeriesVisit(const tsSeries *s,
                  int (*fn)(const tsSample *sample, void *ud), void *ud);

/* agg is a TS_AGG_* value. bucket must be > 0 when agg is not TS_AGG_NONE.
 * On success *out is malloc'd and must be freed by the caller. */
int tsAggregate(const tsSample *in, size_t n, int agg, int64_t bucket,
                tsSample **out, size_t *out_n);
int tsAggFromName(const char *name);
const char *tsDupPolicyName(int policy);
int tsDupPolicyFromName(const char *name);

#endif
