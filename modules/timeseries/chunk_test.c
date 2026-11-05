/* Compression round-trip, aggregation reference, and the 1M-point budget.
 * Build: make -C modules/timeseries chunk_test &&
 * ./modules/timeseries/chunk_test
 */
#include "chunk.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;

static void expect(int cond, const char *msg) {
  if (!cond) {
    fprintf(stderr, "FAIL %s\n", msg);
    failures++;
  }
}

static int samples_equal(const tsSample *a, const tsSample *b) {
  uint64_t ba, bb;
  if (a->ts != b->ts)
    return 0;
  memcpy(&ba, &a->value, sizeof(ba));
  memcpy(&bb, &b->value, sizeof(bb));
  return ba == bb;
}

static int round_trip(const tsSample *in, uint32_t n, size_t chunk_bytes) {
  tsChunk *head = NULL;
  tsChunk *tail = NULL;
  for (uint32_t i = 0; i < n; i++) {
    if (!tail) {
      tail = tsChunkCreate(chunk_bytes);
      head = tail;
      if (!tail)
        return -1;
    }
    int rc = tsChunkAppend(tail, in[i].ts, in[i].value);
    if (rc == 1) {
      tsChunk *next = tsChunkCreate(chunk_bytes);
      if (!next)
        return -1;
      tail->next = next;
      tail = next;
      rc = tsChunkAppend(tail, in[i].ts, in[i].value);
    }
    if (rc != 0)
      return -1;
  }
  uint32_t seen = 0;
  for (tsChunk *c = head; c; c = c->next) {
    tsSample *out = NULL;
    uint32_t got = 0;
    if (tsChunkDecode(c, &out, &got) != 0)
      return -1;
    for (uint32_t i = 0; i < got; i++) {
      if (seen >= n || !samples_equal(&in[seen], &out[i])) {
        fprintf(stderr, "mismatch at %u ts %lld\n", seen,
                (long long)(seen < n ? in[seen].ts : -1));
        free(out);
        return -1;
      }
      seen++;
    }
    free(out);
  }
  tsChunk *c = head;
  while (c) {
    tsChunk *next = c->next;
    tsChunkFree(c);
    c = next;
  }
  return seen == n ? 0 : -1;
}

static void naive_avg(const tsSample *in, size_t n, int64_t bucket,
                      tsSample **out, size_t *out_n) {
  size_t cap = 8, count = 0;
  tsSample *acc = malloc(sizeof(tsSample) * cap);
  int open = 0;
  int64_t bts = 0;
  double sum = 0;
  uint64_t seen = 0;
  for (size_t i = 0; i < n; i++) {
    int64_t b = in[i].ts - (in[i].ts % bucket);
    if (!open || b != bts) {
      if (open) {
        acc[count].ts = bts;
        acc[count].value = sum / (double)seen;
        count++;
        if (count == cap) {
          cap *= 2;
          acc = realloc(acc, sizeof(tsSample) * cap);
        }
      }
      open = 1;
      bts = b;
      sum = in[i].value;
      seen = 1;
    } else {
      sum += in[i].value;
      seen++;
    }
  }
  if (open) {
    acc[count].ts = bts;
    acc[count].value = sum / (double)seen;
    count++;
  }
  *out = acc;
  *out_n = count;
}

static uint64_t rng_state = 0x123456789abcdefULL;

static uint64_t rnd(void) {
  rng_state = rng_state * 6364136223846793005ULL + 1ULL;
  return rng_state;
}

int main(void) {
  enum { N = 20000 };
  tsSample *in = malloc(sizeof(tsSample) * N);
  int64_t ts = 0;
  for (int i = 0; i < N; i++) {
    ts += 1 + (int64_t)(rnd() % 1000);
    /* Mix integers, fractions, and a run of identical values. */
    double v;
    if ((i % 17) == 0)
      v = (double)i;
    else if ((i % 17) == 1)
      v = (double)(i - 1);
    else
      v = (double)(int)(rnd() % 1000000) / 8.0;
    in[i].ts = ts;
    in[i].value = v;
  }
  expect(round_trip(in, N, 4096) == 0, "fuzz round trip");
  expect(round_trip(in, N, 128) == 0, "small chunk round trip");

  tsSample *agg = NULL;
  size_t agg_n = 0;
  expect(tsAggregate(in, 1000, TS_AGG_AVG, 5000, &agg, &agg_n) == 0,
         "aggregate");
  tsSample *naive = NULL;
  size_t naive_n = 0;
  naive_avg(in, 1000, 5000, &naive, &naive_n);
  expect(agg_n == naive_n, "agg count matches naive");
  if (agg_n == naive_n) {
    for (size_t i = 0; i < agg_n; i++) {
      if (agg[i].ts != naive[i].ts || agg[i].value != naive[i].value) {
        expect(0, "agg value matches naive");
        break;
      }
    }
  }
  free(agg);
  free(naive);

  /* Other reducers on a hand-built series. */
  tsSample hand[6] = {{0, 1}, {10, 5}, {20, 3}, {100, 4}, {110, 8}, {150, 1}};
  tsSample *min_out = NULL;
  size_t min_n = 0;
  expect(tsAggregate(hand, 6, TS_AGG_MIN, 100, &min_out, &min_n) == 0,
         "min agg");
  expect(min_n == 2, "min buckets");
  if (min_n == 2) {
    expect(min_out[0].ts == 0 && min_out[0].value == 1, "min bucket 0");
    expect(min_out[1].ts == 100 && min_out[1].value == 1, "min bucket 1");
  }
  free(min_out);
  tsSample *sum_out = NULL;
  size_t sum_n = 0;
  expect(tsAggregate(hand, 6, TS_AGG_SUM, 100, &sum_out, &sum_n) == 0,
         "sum agg");
  if (sum_n == 2) {
    expect(sum_out[0].value == 9, "sum bucket 0");
    expect(sum_out[1].value == 13, "sum bucket 1");
  }
  free(sum_out);
  tsSample *cnt = NULL;
  size_t cnt_n = 0;
  expect(tsAggregate(hand, 6, TS_AGG_COUNT, 100, &cnt, &cnt_n) == 0,
         "count agg");
  if (cnt_n == 2) {
    expect(cnt[0].value == 3 && cnt[1].value == 3, "count values");
  }
  free(cnt);
  tsSample *first = NULL;
  size_t first_n = 0;
  expect(tsAggregate(hand, 6, TS_AGG_FIRST, 100, &first, &first_n) == 0,
         "first agg");
  if (first_n == 2)
    expect(first[0].value == 1 && first[1].value == 4, "first values");
  free(first);
  tsSample *last = NULL;
  size_t last_n = 0;
  expect(tsAggregate(hand, 6, TS_AGG_LAST, 100, &last, &last_n) == 0,
         "last agg");
  if (last_n == 2)
    expect(last[0].value == 3 && last[1].value == 1, "last values");
  free(last);

  /* 1M smooth points must stay well under the 16-byte naive layout. */
  const uint32_t million = 1000000;
  size_t bytes = 0;
  uint32_t produced = 0;
  tsChunk *head = NULL;
  tsChunk *tail = NULL;
  for (uint32_t i = 0; i < million; i++) {
    if (!tail) {
      tail = tsChunkCreate(4096);
      head = tail;
    }
    int rc = tsChunkAppend(tail, (int64_t)i, (double)i * 0.1);
    if (rc == 1) {
      tsChunk *next = tsChunkCreate(4096);
      tail->next = next;
      tail = next;
      rc = tsChunkAppend(tail, (int64_t)i, (double)i * 0.1);
    }
    if (rc != 0) {
      expect(0, "1M append");
      break;
    }
    produced++;
  }
  for (tsChunk *c = head; c; c = c->next)
    bytes += tsChunkBytes(c);
  printf("1M points use %zu bytes (%.2f bytes/sample)\n", bytes,
         produced ? (double)bytes / (double)produced : 0.0);
  expect(bytes < 8u * 1024u * 1024u, "1M points under 8MB");
  /* Spot-check the compressed stream still decodes. */
  tsSample *spot = NULL;
  uint32_t spot_n = 0;
  expect(tsChunkDecode(head, &spot, &spot_n) == 0, "decode first chunk");
  if (spot_n > 0)
    expect(spot[0].ts == 0 && spot[0].value == 0, "first sample");
  free(spot);

  tsChunk *c = head;
  while (c) {
    tsChunk *next = c->next;
    tsChunkFree(c);
    c = next;
  }
  free(in);

  if (failures) {
    fprintf(stderr, "%d failure(s)\n", failures);
    return 1;
  }
  printf("OK\n");
  return 0;
}
