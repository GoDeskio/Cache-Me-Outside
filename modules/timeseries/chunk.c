/* Gorilla-style chunk compression. See chunk.h for the source of the scheme. */
#include "chunk.h"

#include <stdlib.h>
#include <string.h>
#include <strings.h>

static uint64_t double_bits(double v) {
  uint64_t u;
  memcpy(&u, &v, sizeof(u));
  return u;
}

static double bits_double(uint64_t u) {
  double v;
  memcpy(&v, &u, sizeof(v));
  return v;
}

static int ensure_bytes(tsChunk *c, size_t nbytes) {
  if (nbytes <= c->alloc)
    return 0;
  size_t nalloc = c->alloc ? c->alloc : 64;
  while (nalloc < nbytes) {
    if (nalloc > (SIZE_MAX / 2))
      return -1;
    nalloc *= 2;
  }
  unsigned char *grown = realloc(c->data, nalloc);
  if (!grown)
    return -1;
  memset(grown + c->alloc, 0, nalloc - c->alloc);
  c->data = grown;
  c->alloc = nalloc;
  return 0;
}

/* Clamp the Gorilla leading-zero field to the 5 bits the paper uses.
 * Extra leading zeros become part of the stored meaningful bits. */
static void xor_shape(uint64_t xor, int *leading, int *trailing,
                      int *meaningful) {
  int lead = (int)__builtin_clzll(xor);
  int trail = (int)__builtin_ctzll(xor);
  if (lead > 31)
    lead = 31;
  int meaning = 64 - lead - trail;
  if (meaning < 1)
    meaning = 1;
  if (meaning > 64)
    meaning = 64;
  *leading = lead;
  *trailing = trail;
  *meaningful = meaning;
}

static int put_bits(tsChunk *c, uint64_t value, int n) {
  if (n <= 0)
    return 0;
  if (n > 64)
    return -1;
  size_t need = (size_t)(c->nbits + (uint32_t)n + 7) / 8;
  if (ensure_bytes(c, need) != 0)
    return -1;
  for (int i = n - 1; i >= 0; i--) {
    unsigned bit = (unsigned)((value >> i) & 1ull);
    size_t byte = c->nbits / 8;
    int shift = 7 - (int)(c->nbits % 8);
    if (bit)
      c->data[byte] |= (unsigned char)(1u << shift);
    c->nbits++;
  }
  return 0;
}

typedef struct bitr {
  const unsigned char *data;
  uint32_t nbits;
  uint32_t pos;
  int error;
} bitr;

static uint64_t get_bits(bitr *r, int n) {
  uint64_t value = 0;
  if (n <= 0)
    return 0;
  if (r->pos + (uint32_t)n > r->nbits) {
    r->error = 1;
    return 0;
  }
  for (int i = 0; i < n; i++) {
    size_t byte = r->pos / 8;
    int shift = 7 - (int)(r->pos % 8);
    unsigned bit = (r->data[byte] >> shift) & 1u;
    value = (value << 1) | bit;
    r->pos++;
  }
  return value;
}

static int64_t sign_extend(uint64_t value, int bits) {
  if (bits <= 0 || bits >= 64)
    return (int64_t)value;
  uint64_t sign = 1ull << (bits - 1);
  if (value & sign) {
    uint64_t mask = ~((1ull << bits) - 1ull);
    return (int64_t)(value | mask);
  }
  return (int64_t)value;
}

/* Bits required to append one sample, given the chunk's current predictor. */
static int bits_for_sample(const tsChunk *c, int64_t ts, double value) {
  int bits = 0;
  if (!c->has_prev)
    return 64 + 64;
  int64_t delta = ts - c->prev_ts;
  int64_t dod = delta - c->prev_delta;
  if (dod == 0)
    bits += 1;
  else if (dod >= -64 && dod <= 63)
    bits += 2 + 7;
  else if (dod >= -256 && dod <= 255)
    bits += 3 + 9;
  else if (dod >= -2048 && dod <= 2047)
    bits += 4 + 12;
  else
    bits += 4 + 64;

  uint64_t xor = double_bits(value) ^ c->prev_value_bits;
  if (xor == 0) {
    bits += 1;
    return bits;
  }
  int leading, trailing, meaningful;
  xor_shape(xor, &leading, &trailing, &meaningful);
  if (c->has_value_window && leading >= (int)c->prev_leading &&
      trailing >= (int)c->prev_trailing) {
    int window = 64 - (int)c->prev_leading - (int)c->prev_trailing;
    bits += 2 + window;
  } else {
    bits += 2 + 5 + 6 + meaningful;
  }
  return bits;
}

static int encode_dod(tsChunk *c, int64_t dod) {
  if (dod == 0)
    return put_bits(c, 0, 1);
  if (dod >= -64 && dod <= 63) {
    if (put_bits(c, 0x2, 2) != 0)
      return -1;
    return put_bits(c, (uint64_t)dod & 0x7f, 7);
  }
  if (dod >= -256 && dod <= 255) {
    if (put_bits(c, 0x6, 3) != 0)
      return -1;
    return put_bits(c, (uint64_t)dod & 0x1ff, 9);
  }
  if (dod >= -2048 && dod <= 2047) {
    if (put_bits(c, 0xe, 4) != 0)
      return -1;
    return put_bits(c, (uint64_t)dod & 0xfff, 12);
  }
  if (put_bits(c, 0xf, 4) != 0)
    return -1;
  return put_bits(c, (uint64_t)dod, 64);
}

static int encode_xor(tsChunk *c, uint64_t bits) {
  uint64_t xor = bits ^ c->prev_value_bits;
  if (xor == 0)
    return put_bits(c, 0, 1);
  if (put_bits(c, 1, 1) != 0)
    return -1;
  int leading, trailing, meaningful;
  xor_shape(xor, &leading, &trailing, &meaningful);

  if (c->has_value_window && leading >= (int)c->prev_leading &&
      trailing >= (int)c->prev_trailing) {
    int window = 64 - (int)c->prev_leading - (int)c->prev_trailing;
    if (window < 0)
      window = 0;
    if (window > 64)
      window = 64;
    if (put_bits(c, 0, 1) != 0)
      return -1;
    uint64_t field = c->prev_trailing >= 64 ? 0 : (xor >> c->prev_trailing);
    return put_bits(c, field, window);
  }
  if (put_bits(c, 1, 1) != 0)
    return -1;
  if (put_bits(c, (uint64_t)leading, 5) != 0)
    return -1;
  /* 0 means 64 meaningful bits. meaningful is never 0 on this path. */
  if (put_bits(c, meaningful == 64 ? 0 : (uint64_t)meaningful, 6) != 0)
    return -1;
  uint64_t field = trailing >= 64 ? 0 : (xor >> trailing);
  if (put_bits(c, field, meaningful) != 0)
    return -1;
  c->prev_leading = (uint8_t)leading;
  c->prev_trailing = (uint8_t)trailing;
  c->has_value_window = 1;
  return 0;
}

tsChunk *tsChunkCreate(size_t cap) {
  if (cap < 16)
    cap = 16;
  tsChunk *c = calloc(1, sizeof(*c));
  if (!c)
    return NULL;
  c->data = calloc(1, cap);
  if (!c->data) {
    free(c);
    return NULL;
  }
  c->cap = cap;
  c->alloc = cap;
  return c;
}

void tsChunkFree(tsChunk *c) {
  if (!c)
    return;
  free(c->data);
  free(c);
}

int tsChunkAppend(tsChunk *c, int64_t ts, double value) {
  if (!c)
    return -1;
  if (c->count > 0) {
    int need = bits_for_sample(c, ts, value);
    size_t limit_bits = c->cap * 8;
    /* The struct cap is the target chunk size. Grow only to finish a
     * sample that was predicted to fit; a sample that would cross the
     * target starts a new chunk instead. */
    if ((size_t)c->nbits + (size_t)need > limit_bits)
      return 1;
  }
  if (!c->has_prev) {
    if (put_bits(c, (uint64_t)ts, 64) != 0)
      return -1;
    if (put_bits(c, double_bits(value), 64) != 0)
      return -1;
    c->first_ts = ts;
    c->last_ts = ts;
    c->prev_ts = ts;
    c->prev_delta = 0;
    c->prev_value_bits = double_bits(value);
    c->has_prev = 1;
    c->count = 1;
    return 0;
  }
  int64_t delta = ts - c->prev_ts;
  int64_t dod = delta - c->prev_delta;
  if (encode_dod(c, dod) != 0)
    return -1;
  if (encode_xor(c, double_bits(value)) != 0)
    return -1;
  c->prev_delta = delta;
  c->prev_ts = ts;
  c->prev_value_bits = double_bits(value);
  c->last_ts = ts;
  c->count++;
  return 0;
}

static int decode_one(bitr *r, tsChunk *state, int64_t *ts, double *value,
                      int first) {
  if (first) {
    *ts = (int64_t)get_bits(r, 64);
    uint64_t bits = get_bits(r, 64);
    if (r->error)
      return -1;
    *value = bits_double(bits);
    state->prev_ts = *ts;
    state->prev_delta = 0;
    state->prev_value_bits = bits;
    state->has_prev = 1;
    return 0;
  }
  uint64_t marker = get_bits(r, 1);
  int64_t dod;
  if (marker == 0) {
    dod = 0;
  } else {
    uint64_t marker2 = get_bits(r, 1);
    if (marker2 == 0) {
      dod = sign_extend(get_bits(r, 7), 7);
    } else {
      uint64_t marker3 = get_bits(r, 1);
      if (marker3 == 0) {
        dod = sign_extend(get_bits(r, 9), 9);
      } else {
        uint64_t marker4 = get_bits(r, 1);
        if (marker4 == 0)
          dod = sign_extend(get_bits(r, 12), 12);
        else
          dod = (int64_t)get_bits(r, 64);
      }
    }
  }
  if (r->error)
    return -1;
  int64_t delta = state->prev_delta + dod;
  *ts = state->prev_ts + delta;

  uint64_t xor_flag = get_bits(r, 1);
  uint64_t bits;
  if (xor_flag == 0) {
    bits = state->prev_value_bits;
  } else {
    uint64_t window_flag = get_bits(r, 1);
    if (window_flag == 0) {
      int window = 64 - (int)state->prev_leading - (int)state->prev_trailing;
      if (window < 0)
        window = 0;
      uint64_t field = get_bits(r, window);
      uint64_t xor
          = state->prev_trailing >= 64 ? 0 : (field << state->prev_trailing);
      bits = state->prev_value_bits ^ xor;
    } else {
      int leading = (int)get_bits(r, 5);
      int meaningful = (int)get_bits(r, 6);
      if (meaningful == 0)
        meaningful = 64;
      int trailing = 64 - leading - meaningful;
      if (trailing < 0) {
        r->error = 1;
        return -1;
      }
      uint64_t field = get_bits(r, meaningful);
      uint64_t xor = trailing >= 64 ? 0 : (field << trailing);
      bits = state->prev_value_bits ^ xor;
      state->prev_leading = (uint8_t)leading;
      state->prev_trailing = (uint8_t)trailing;
      state->has_value_window = 1;
    }
  }
  if (r->error)
    return -1;
  *value = bits_double(bits);
  state->prev_delta = delta;
  state->prev_ts = *ts;
  state->prev_value_bits = bits;
  return 0;
}

int tsChunkDecode(const tsChunk *c, tsSample **out, uint32_t *n) {
  if (!c || !out || !n)
    return -1;
  *out = NULL;
  *n = 0;
  if (c->count == 0)
    return 0;
  tsSample *samples = malloc(sizeof(tsSample) * c->count);
  if (!samples)
    return -1;
  bitr r = {.data = c->data, .nbits = c->nbits, .pos = 0, .error = 0};
  tsChunk state;
  memset(&state, 0, sizeof(state));
  for (uint32_t i = 0; i < c->count; i++) {
    if (decode_one(&r, &state, &samples[i].ts, &samples[i].value, i == 0) !=
        0) {
      free(samples);
      return -1;
    }
  }
  *out = samples;
  *n = c->count;
  return 0;
}

int tsChunkRecompress(tsChunk *c, const tsSample *samples, uint32_t n) {
  tsChunk *next = c->next;
  size_t cap = c->cap ? c->cap : TS_CHUNK_DEFAULT_BYTES;
  tsChunk *fresh = tsChunkCreate(cap);
  if (!fresh)
    return -1;
  for (uint32_t i = 0; i < n; i++) {
    int rc;
    do {
      rc = tsChunkAppend(fresh, samples[i].ts, samples[i].value);
      if (rc == 1) {
        if (fresh->cap > (SIZE_MAX / 2)) {
          tsChunkFree(fresh);
          return -1;
        }
        fresh->cap *= 2;
      }
    } while (rc == 1);
    if (rc != 0) {
      tsChunkFree(fresh);
      return -1;
    }
  }
  free(c->data);
  *c = *fresh;
  c->next = next;
  free(fresh);
  return 0;
}

size_t tsChunkBytes(const tsChunk *c) {
  if (!c)
    return 0;
  return sizeof(*c) + c->alloc;
}

size_t tsSeriesStorageBytes(const tsSeries *s) {
  size_t n = sizeof(*s);
  if (!s)
    return 0;
  for (tsChunk *c = s->head; c; c = c->next)
    n += tsChunkBytes(c);
  n += (size_t)s->nlabels * sizeof(tsLabel);
  for (int i = 0; i < s->nlabels; i++) {
    if (s->labels[i].key)
      n += strlen(s->labels[i].key) + 1;
    if (s->labels[i].val)
      n += strlen(s->labels[i].val) + 1;
  }
  if (s->key)
    n += s->key_len + 1;
  return n;
}

int tsSeriesVisit(const tsSeries *s,
                  int (*fn)(const tsSample *sample, void *ud), void *ud) {
  if (!s || !fn)
    return -1;
  for (const tsChunk *c = s->head; c; c = c->next) {
    tsSample *samples = NULL;
    uint32_t n = 0;
    if (tsChunkDecode(c, &samples, &n) != 0)
      return -1;
    for (uint32_t i = 0; i < n; i++) {
      int rc = fn(&samples[i], ud);
      if (rc != 0) {
        free(samples);
        return rc;
      }
    }
    free(samples);
  }
  return 0;
}

int tsAggregate(const tsSample *in, size_t n, int agg, int64_t bucket,
                tsSample **out, size_t *out_n) {
  if (!out || !out_n)
    return -1;
  *out = NULL;
  *out_n = 0;
  if (agg == TS_AGG_NONE || n == 0) {
    if (n == 0)
      return 0;
    tsSample *copy = malloc(sizeof(tsSample) * n);
    if (!copy)
      return -1;
    memcpy(copy, in, sizeof(tsSample) * n);
    *out = copy;
    *out_n = n;
    return 0;
  }
  if (bucket <= 0)
    return -1;
  size_t cap = 16;
  size_t count = 0;
  tsSample *acc = malloc(sizeof(tsSample) * cap);
  if (!acc)
    return -1;
  int open = 0;
  int64_t bucket_ts = 0;
  double sum = 0;
  double extreme = 0;
  double first = 0;
  double last = 0;
  uint64_t seen = 0;

  for (size_t i = 0; i < n; i++) {
    int64_t b = in[i].ts - (in[i].ts % bucket);
    /* int64 division truncates toward zero. Timestamps we accept are >= 0,
     * so this matches the usual floor alignment. */
    if (!open || b != bucket_ts) {
      if (open) {
        if (count == cap) {
          size_t ncap = cap * 2;
          tsSample *grown = realloc(acc, sizeof(tsSample) * ncap);
          if (!grown) {
            free(acc);
            return -1;
          }
          acc = grown;
          cap = ncap;
        }
        acc[count].ts = bucket_ts;
        if (agg == TS_AGG_AVG)
          acc[count].value = seen ? sum / (double)seen : 0;
        else if (agg == TS_AGG_SUM)
          acc[count].value = sum;
        else if (agg == TS_AGG_MIN || agg == TS_AGG_MAX)
          acc[count].value = extreme;
        else if (agg == TS_AGG_COUNT)
          acc[count].value = (double)seen;
        else if (agg == TS_AGG_FIRST)
          acc[count].value = first;
        else
          acc[count].value = last;
        count++;
      }
      open = 1;
      bucket_ts = b;
      sum = in[i].value;
      extreme = in[i].value;
      first = in[i].value;
      last = in[i].value;
      seen = 1;
    } else {
      sum += in[i].value;
      if (agg == TS_AGG_MIN && in[i].value < extreme)
        extreme = in[i].value;
      if (agg == TS_AGG_MAX && in[i].value > extreme)
        extreme = in[i].value;
      last = in[i].value;
      seen++;
    }
  }
  if (open) {
    if (count == cap) {
      tsSample *grown = realloc(acc, sizeof(tsSample) * (cap + 1));
      if (!grown) {
        free(acc);
        return -1;
      }
      acc = grown;
    }
    acc[count].ts = bucket_ts;
    if (agg == TS_AGG_AVG)
      acc[count].value = seen ? sum / (double)seen : 0;
    else if (agg == TS_AGG_SUM)
      acc[count].value = sum;
    else if (agg == TS_AGG_MIN || agg == TS_AGG_MAX)
      acc[count].value = extreme;
    else if (agg == TS_AGG_COUNT)
      acc[count].value = (double)seen;
    else if (agg == TS_AGG_FIRST)
      acc[count].value = first;
    else
      acc[count].value = last;
    count++;
  }
  *out = acc;
  *out_n = count;
  return 0;
}

int tsAggFromName(const char *name) {
  if (!name)
    return -1;
  if (!strcasecmp(name, "avg"))
    return TS_AGG_AVG;
  if (!strcasecmp(name, "sum"))
    return TS_AGG_SUM;
  if (!strcasecmp(name, "min"))
    return TS_AGG_MIN;
  if (!strcasecmp(name, "max"))
    return TS_AGG_MAX;
  if (!strcasecmp(name, "count"))
    return TS_AGG_COUNT;
  if (!strcasecmp(name, "first"))
    return TS_AGG_FIRST;
  if (!strcasecmp(name, "last"))
    return TS_AGG_LAST;
  return -1;
}

const char *tsDupPolicyName(int policy) {
  switch (policy) {
  case TS_DUP_FIRST:
    return "FIRST";
  case TS_DUP_LAST:
    return "LAST";
  case TS_DUP_MIN:
    return "MIN";
  case TS_DUP_MAX:
    return "MAX";
  case TS_DUP_SUM:
    return "SUM";
  default:
    return "BLOCK";
  }
}

int tsDupPolicyFromName(const char *name) {
  if (!name)
    return -1;
  if (!strcasecmp(name, "block"))
    return TS_DUP_BLOCK;
  if (!strcasecmp(name, "first"))
    return TS_DUP_FIRST;
  if (!strcasecmp(name, "last"))
    return TS_DUP_LAST;
  if (!strcasecmp(name, "min"))
    return TS_DUP_MIN;
  if (!strcasecmp(name, "max"))
    return TS_DUP_MAX;
  if (!strcasecmp(name, "sum"))
    return TS_DUP_SUM;
  return -1;
}
