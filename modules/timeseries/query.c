/* Range, reverse-range, and bucket aggregation replies.
 *
 * Aggregation is a straight bucket walk over decoded samples. The C test
 * checks it against an independent naive implementation. */
#include "chunk.h"

#include "../src/valkeymodule.h"

#include <stdlib.h>
#include <string.h>

typedef struct collect_state {
  int64_t from;
  int64_t to;
  int filter_value;
  double vmin;
  double vmax;
  tsSample *samples;
  size_t n;
  size_t cap;
  int error;
} collect_state;

static int collect_sample(const tsSample *sample, void *ud) {
  collect_state *st = ud;
  if (sample->ts < st->from || sample->ts > st->to)
    return 0;
  if (st->filter_value &&
      (sample->value < st->vmin || sample->value > st->vmax))
    return 0;
  if (st->n == st->cap) {
    size_t ncap = st->cap ? st->cap * 2 : 64;
    tsSample *grown = realloc(st->samples, sizeof(tsSample) * ncap);
    if (!grown) {
      st->error = 1;
      return -1;
    }
    st->samples = grown;
    st->cap = ncap;
  }
  st->samples[st->n++] = *sample;
  return 0;
}

static void reply_sample(ValkeyModuleCtx *ctx, const tsSample *sample) {
  ValkeyModule_ReplyWithArray(ctx, 2);
  ValkeyModule_ReplyWithLongLong(ctx, (long long)sample->ts);
  ValkeyModule_ReplyWithDouble(ctx, sample->value);
}

/* Write the sample array for one series. Returns 0 on success. */
int tsReplySamples(ValkeyModuleCtx *ctx, const tsSeries *s, int64_t from,
                   int64_t to, int reverse, int agg, int64_t bucket,
                   long long max_count, int filter_value, double vmin,
                   double vmax) {
  collect_state st;
  memset(&st, 0, sizeof(st));
  st.from = from;
  st.to = to;
  st.filter_value = filter_value;
  st.vmin = vmin;
  st.vmax = vmax;
  if (s && tsSeriesVisit(s, collect_sample, &st) != 0) {
    free(st.samples);
    return -1;
  }
  if (st.error) {
    free(st.samples);
    return -1;
  }

  tsSample *out = st.samples;
  size_t n = st.n;
  if (agg != TS_AGG_NONE) {
    tsSample *agg_out = NULL;
    size_t agg_n = 0;
    if (tsAggregate(st.samples, st.n, agg, bucket, &agg_out, &agg_n) != 0) {
      free(st.samples);
      return -1;
    }
    free(st.samples);
    out = agg_out;
    n = agg_n;
  }
  if (reverse && n > 1) {
    for (size_t i = 0; i < n / 2; i++) {
      tsSample tmp = out[i];
      out[i] = out[n - 1 - i];
      out[n - 1 - i] = tmp;
    }
  }
  if (max_count >= 0 && (size_t)max_count < n)
    n = (size_t)max_count;

  ValkeyModule_ReplyWithArray(ctx, (long)n);
  for (size_t i = 0; i < n; i++)
    reply_sample(ctx, &out[i]);
  free(out);
  return 0;
}
