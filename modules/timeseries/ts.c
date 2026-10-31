/* TS.* time-series type.
 *
 * Command names follow the usual TS.* client API. Storage, compression,
 * and query execution are implemented in this module. See chunk.h.
 *
 * Copyright (c) 2026, Cache Me Outside contributors.
 * Licensed under the BSD 3-Clause License, the same terms as the server.
 */
#include "chunk.h"

#include "../src/valkeymodule.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

static ValkeyModuleType *TsType;

int tsReplySamples(ValkeyModuleCtx *ctx, const tsSeries *s, int64_t from,
                   int64_t to, int reverse, int agg, int64_t bucket,
                   long long max_count, int filter_value, double vmin,
                   double vmax);

static char *dup_cstr(const char *p, size_t len) {
  char *s = malloc(len + 1);
  if (!s)
    return NULL;
  memcpy(s, p, len);
  s[len] = '\0';
  return s;
}

static tsSeries *series_create(size_t chunk_size, int64_t retention,
                               int dup_policy) {
  tsSeries *s = calloc(1, sizeof(*s));
  if (!s)
    return NULL;
  if (chunk_size < TS_CHUNK_MIN_BYTES)
    chunk_size = TS_CHUNK_MIN_BYTES;
  if (chunk_size > TS_CHUNK_MAX_BYTES)
    chunk_size = TS_CHUNK_MAX_BYTES;
  s->chunk_size = chunk_size;
  s->retention_ms = retention;
  s->dup_policy = dup_policy;
  return s;
}

static void series_clear_chunks(tsSeries *s) {
  tsChunk *c = s->head;
  while (c) {
    tsChunk *next = c->next;
    tsChunkFree(c);
    c = next;
  }
  s->head = s->tail = NULL;
  s->total_samples = 0;
  s->has_sample = 0;
}

static void series_free(tsSeries *s) {
  if (!s)
    return;
  series_clear_chunks(s);
  for (int i = 0; i < s->nlabels; i++) {
    free(s->labels[i].key);
    free(s->labels[i].val);
  }
  free(s->labels);
  free(s->key);
  free(s);
}

static void series_set_key(tsSeries *s, const char *key, size_t len) {
  char *copy = dup_cstr(key, len);
  if (!copy)
    return;
  free(s->key);
  s->key = copy;
  s->key_len = len;
}

static int series_set_label(tsSeries *s, const char *key, const char *val) {
  for (int i = 0; i < s->nlabels; i++) {
    if (strcmp(s->labels[i].key, key) == 0) {
      char *copy = strdup(val);
      if (!copy)
        return -1;
      free(s->labels[i].val);
      s->labels[i].val = copy;
      return 0;
    }
  }
  tsLabel *grown =
      realloc(s->labels, sizeof(tsLabel) * (size_t)(s->nlabels + 1));
  if (!grown)
    return -1;
  s->labels = grown;
  s->labels[s->nlabels].key = strdup(key);
  s->labels[s->nlabels].val = strdup(val);
  if (!s->labels[s->nlabels].key || !s->labels[s->nlabels].val)
    return -1;
  s->nlabels++;
  return 0;
}

static int chunk_push_sample(tsSeries *s, int64_t ts, double value) {
  if (!s->tail) {
    s->head = s->tail = tsChunkCreate(s->chunk_size);
    if (!s->tail)
      return -1;
  }
  int rc = tsChunkAppend(s->tail, ts, value);
  if (rc == 1) {
    tsChunk *n = tsChunkCreate(s->chunk_size);
    if (!n)
      return -1;
    s->tail->next = n;
    s->tail = n;
    rc = tsChunkAppend(s->tail, ts, value);
  }
  if (rc != 0)
    return -1;
  s->total_samples++;
  s->last_ts = ts;
  s->last_value = value;
  s->has_sample = 1;
  return 0;
}

static int rebuild_from_samples(tsSeries *s, const tsSample *samples,
                                size_t n) {
  series_clear_chunks(s);
  for (size_t i = 0; i < n; i++) {
    if (chunk_push_sample(s, samples[i].ts, samples[i].value) != 0)
      return -1;
  }
  return 0;
}

typedef struct gather_state {
  tsSample *samples;
  size_t n;
  size_t cap;
  int error;
} gather_state;

static int gather_all(const tsSample *sample, void *ud) {
  gather_state *st = ud;
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

static int load_all_samples(const tsSeries *s, tsSample **out, size_t *n) {
  gather_state st;
  memset(&st, 0, sizeof(st));
  if (tsSeriesVisit(s, gather_all, &st) != 0 || st.error) {
    free(st.samples);
    return -1;
  }
  *out = st.samples;
  *n = st.n;
  return 0;
}

static int trim_retention(tsSeries *s) {
  if (s->retention_ms <= 0 || !s->has_sample)
    return 0;
  int64_t cutoff = s->last_ts - s->retention_ms;
  int dropped_whole = 0;
  while (s->head && s->head->last_ts < cutoff) {
    tsChunk *dead = s->head;
    s->head = dead->next;
    if (s->total_samples >= dead->count)
      s->total_samples -= dead->count;
    else
      s->total_samples = 0;
    tsChunkFree(dead);
    dropped_whole = 1;
  }
  if (!s->head) {
    s->tail = NULL;
    s->has_sample = 0;
    s->total_samples = 0;
    return 0;
  }
  if (dropped_whole && s->head) {
    /* tail pointer is unchanged unless we dropped everything. */
  }
  if (s->head->first_ts < cutoff) {
    tsSample *samples = NULL;
    uint32_t n = 0;
    if (tsChunkDecode(s->head, &samples, &n) != 0)
      return -1;
    uint32_t keep = 0;
    for (uint32_t i = 0; i < n; i++) {
      if (samples[i].ts >= cutoff)
        samples[keep++] = samples[i];
    }
    uint32_t removed = n - keep;
    if (s->total_samples >= removed)
      s->total_samples -= removed;
    else
      s->total_samples = 0;
    if (tsChunkRecompress(s->head, samples, keep) != 0) {
      free(samples);
      return -1;
    }
    free(samples);
  }
  if (s->total_samples == 0)
    s->has_sample = 0;
  return 0;
}

static int rewrite_last_sample(tsSeries *s, double value) {
  if (!s->tail || s->tail->count == 0)
    return -1;
  tsSample *samples = NULL;
  uint32_t n = 0;
  if (tsChunkDecode(s->tail, &samples, &n) != 0 || n == 0) {
    free(samples);
    return -1;
  }
  samples[n - 1].value = value;
  int rc = tsChunkRecompress(s->tail, samples, n);
  free(samples);
  if (rc != 0)
    return -1;
  s->last_value = value;
  return 0;
}

/* 0 stored, 1 duplicate ignored (FIRST), -1 block, -2 older, -3 oom. */
static int series_add(tsSeries *s, int64_t ts, double value) {
  if (s->has_sample && ts < s->last_ts)
    return -2;
  if (s->has_sample && ts == s->last_ts) {
    double updated = value;
    if (s->dup_policy == TS_DUP_BLOCK)
      return -1;
    if (s->dup_policy == TS_DUP_FIRST)
      return 1;
    if (s->dup_policy == TS_DUP_MIN)
      updated = value < s->last_value ? value : s->last_value;
    else if (s->dup_policy == TS_DUP_MAX)
      updated = value > s->last_value ? value : s->last_value;
    else if (s->dup_policy == TS_DUP_SUM)
      updated = s->last_value + value;
    if (rewrite_last_sample(s, updated) != 0)
      return -3;
    return 0;
  }
  if (chunk_push_sample(s, ts, value) != 0)
    return -3;
  if (trim_retention(s) != 0)
    return -3;
  return 0;
}

static int series_delete_range(tsSeries *s, int64_t from, int64_t to,
                               long long *removed) {
  tsSample *samples = NULL;
  size_t n = 0;
  if (load_all_samples(s, &samples, &n) != 0)
    return -1;
  size_t keep = 0;
  long long gone = 0;
  for (size_t i = 0; i < n; i++) {
    if (samples[i].ts >= from && samples[i].ts <= to) {
      gone++;
      continue;
    }
    samples[keep++] = samples[i];
  }
  if (rebuild_from_samples(s, samples, keep) != 0) {
    free(samples);
    return -1;
  }
  free(samples);
  *removed = gone;
  return 0;
}

static int label_equals(const tsSeries *s, const char *key, const char *val) {
  for (int i = 0; i < s->nlabels; i++) {
    if (strcmp(s->labels[i].key, key) == 0 &&
        strcmp(s->labels[i].val, val) == 0)
      return 1;
  }
  return 0;
}

typedef struct tsFilter {
  char *expr;
  char *key;
  char *val;
  int negate;
} tsFilter;

static int parse_filter(const char *expr, tsFilter *f) {
  const char *neq = strstr(expr, "!=");
  const char *eq = strchr(expr, '=');
  f->expr = NULL;
  f->key = NULL;
  f->val = NULL;
  f->negate = 0;
  if (neq) {
    f->negate = 1;
    f->key = dup_cstr(expr, (size_t)(neq - expr));
    f->val = strdup(neq + 2);
  } else if (eq && eq != expr) {
    f->key = dup_cstr(expr, (size_t)(eq - expr));
    f->val = strdup(eq + 1);
  } else {
    return -1;
  }
  if (!f->key || !f->val || f->key[0] == '\0') {
    free(f->key);
    free(f->val);
    return -1;
  }
  return 0;
}

static int filters_match(const tsSeries *s, const tsFilter *filters,
                         int nfilters) {
  for (int i = 0; i < nfilters; i++) {
    int eq = label_equals(s, filters[i].key, filters[i].val);
    if (filters[i].negate) {
      if (eq)
        return 0;
    } else if (!eq) {
      return 0;
    }
  }
  return 1;
}

static void reply_labels(ValkeyModuleCtx *ctx, const tsSeries *s) {
  ValkeyModule_ReplyWithArray(ctx, s->nlabels);
  for (int i = 0; i < s->nlabels; i++) {
    ValkeyModule_ReplyWithArray(ctx, 2);
    ValkeyModule_ReplyWithCString(ctx, s->labels[i].key);
    ValkeyModule_ReplyWithCString(ctx, s->labels[i].val);
  }
}

static int parse_timestamp(ValkeyModuleCtx *ctx, ValkeyModuleString *arg,
                           int64_t *out, int allow_star) {
  size_t len = 0;
  const char *p = ValkeyModule_StringPtrLen(arg, &len);
  if (allow_star && len == 1 && p[0] == '*') {
    *out = (int64_t)ValkeyModule_Milliseconds();
    return 0;
  }
  if (len == 1 && p[0] == '-') {
    *out = INT64_MIN;
    return 0;
  }
  if (len == 1 && p[0] == '+') {
    *out = INT64_MAX;
    return 0;
  }
  long long v;
  if (ValkeyModule_StringToLongLong(arg, &v) != VALKEYMODULE_OK || v < 0) {
    ValkeyModule_ReplyWithError(ctx, "ERR invalid timestamp");
    return -1;
  }
  *out = (int64_t)v;
  return 0;
}

static int open_series(ValkeyModuleCtx *ctx, ValkeyModuleString *keyname,
                       tsSeries **out, ValkeyModuleKey **kout, int create,
                       int64_t retention, int dup_policy, size_t chunk_size) {
  ValkeyModuleKey *key = ValkeyModule_OpenKey(
      ctx, keyname, VALKEYMODULE_READ | VALKEYMODULE_WRITE);
  int type = ValkeyModule_KeyType(key);
  if (type != VALKEYMODULE_KEYTYPE_EMPTY &&
      ValkeyModule_ModuleTypeGetType(key) != TsType) {
    ValkeyModule_ReplyWithError(ctx, VALKEYMODULE_ERRORMSG_WRONGTYPE);
    return -1;
  }
  tsSeries *s = NULL;
  if (type == VALKEYMODULE_KEYTYPE_EMPTY) {
    if (!create) {
      *out = NULL;
      *kout = key;
      return 0;
    }
    s = series_create(chunk_size, retention, dup_policy);
    if (!s) {
      ValkeyModule_ReplyWithError(ctx, "ERR out of memory");
      return -1;
    }
    size_t klen = 0;
    const char *k = ValkeyModule_StringPtrLen(keyname, &klen);
    series_set_key(s, k, klen);
    ValkeyModule_ModuleTypeSetValue(key, TsType, s);
  } else {
    s = ValkeyModule_ModuleTypeGetValue(key);
  }
  *out = s;
  *kout = key;
  return 0;
}

static int parse_create_options(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                                int argc, int start, int64_t *retention,
                                int *dup_policy, size_t *chunk_size,
                                int *labels_at) {
  *labels_at = -1;
  for (int i = start; i < argc; i++) {
    size_t len = 0;
    const char *tok = ValkeyModule_StringPtrLen(argv[i], &len);
    if (!strcasecmp(tok, "RETENTION")) {
      long long v;
      if (i + 1 >= argc ||
          ValkeyModule_StringToLongLong(argv[++i], &v) != VALKEYMODULE_OK ||
          v < 0) {
        ValkeyModule_ReplyWithError(ctx, "ERR invalid RETENTION");
        return -1;
      }
      *retention = (int64_t)v;
    } else if (!strcasecmp(tok, "DUPLICATE_POLICY") ||
               !strcasecmp(tok, "ON_DUPLICATE")) {
      if (i + 1 >= argc) {
        ValkeyModule_ReplyWithError(ctx, "ERR missing duplicate policy");
        return -1;
      }
      size_t plen = 0;
      const char *pol = ValkeyModule_StringPtrLen(argv[++i], &plen);
      int parsed = tsDupPolicyFromName(pol);
      if (parsed < 0) {
        ValkeyModule_ReplyWithError(ctx, "ERR invalid duplicate policy");
        return -1;
      }
      *dup_policy = parsed;
    } else if (!strcasecmp(tok, "CHUNK_SIZE")) {
      long long v;
      if (i + 1 >= argc ||
          ValkeyModule_StringToLongLong(argv[++i], &v) != VALKEYMODULE_OK ||
          v <= 0) {
        ValkeyModule_ReplyWithError(ctx, "ERR invalid CHUNK_SIZE");
        return -1;
      }
      *chunk_size = (size_t)v;
    } else if (!strcasecmp(tok, "ENCODING")) {
      if (i + 1 >= argc) {
        ValkeyModule_ReplyWithError(ctx, "ERR missing ENCODING");
        return -1;
      }
      i++; /* Accepted for clients. Samples are always stored compressed. */
    } else if (!strcasecmp(tok, "LABELS")) {
      *labels_at = i + 1;
      if (((argc - *labels_at) % 2) != 0) {
        ValkeyModule_ReplyWithError(ctx, "ERR LABELS requires key value pairs");
        return -1;
      }
      return 0;
    } else {
      ValkeyModule_ReplyWithError(ctx, "ERR syntax error");
      return -1;
    }
  }
  return 0;
}

static int apply_labels(ValkeyModuleCtx *ctx, tsSeries *s,
                        ValkeyModuleString **argv, int begin, int end) {
  for (int i = begin; i + 1 < end; i += 2) {
    size_t klen = 0, vlen = 0;
    const char *k = ValkeyModule_StringPtrLen(argv[i], &klen);
    const char *v = ValkeyModule_StringPtrLen(argv[i + 1], &vlen);
    char *ks = dup_cstr(k, klen);
    char *vs = dup_cstr(v, vlen);
    if (!ks || !vs || series_set_label(s, ks, vs) != 0) {
      free(ks);
      free(vs);
      ValkeyModule_ReplyWithError(ctx, "ERR out of memory");
      return -1;
    }
    free(ks);
    free(vs);
  }
  return 0;
}

static int TsCreate_Command(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                            int argc) {
  ValkeyModule_AutoMemory(ctx);
  if (argc < 2)
    return ValkeyModule_WrongArity(ctx);
  int64_t retention = 0;
  int dup_policy = TS_DUP_BLOCK;
  size_t chunk_size = TS_CHUNK_DEFAULT_BYTES;
  int labels_at = -1;
  if (parse_create_options(ctx, argv, argc, 2, &retention, &dup_policy,
                           &chunk_size, &labels_at) != 0)
    return VALKEYMODULE_OK;

  ValkeyModuleKey *key = ValkeyModule_OpenKey(
      ctx, argv[1], VALKEYMODULE_READ | VALKEYMODULE_WRITE);
  if (ValkeyModule_KeyType(key) != VALKEYMODULE_KEYTYPE_EMPTY) {
    return ValkeyModule_ReplyWithError(ctx, "ERR key already exists");
  }
  tsSeries *s = series_create(chunk_size, retention, dup_policy);
  if (!s)
    return ValkeyModule_ReplyWithError(ctx, "ERR out of memory");
  size_t klen = 0;
  const char *k = ValkeyModule_StringPtrLen(argv[1], &klen);
  series_set_key(s, k, klen);
  if (labels_at >= 0 && apply_labels(ctx, s, argv, labels_at, argc) != 0) {
    series_free(s);
    return VALKEYMODULE_OK;
  }
  ValkeyModule_ModuleTypeSetValue(key, TsType, s);
  ValkeyModule_ReplicateVerbatim(ctx);
  return ValkeyModule_ReplyWithSimpleString(ctx, "OK");
}

static int add_one(ValkeyModuleCtx *ctx, ValkeyModuleString *keyname,
                   int64_t ts, double value, int create, int64_t retention,
                   int dup_policy, size_t chunk_size, int64_t *stored_ts) {
  tsSeries *s = NULL;
  ValkeyModuleKey *key = NULL;
  if (open_series(ctx, keyname, &s, &key, create, retention, dup_policy,
                  chunk_size) != 0)
    return -1;
  if (!s) {
    ValkeyModule_ReplyWithError(ctx, "ERR key does not exist");
    return -1;
  }
  /* Creation options on TS.ADD apply only when this command created the key.
   * An existing series keeps the policy it was created with. */
  int rc = series_add(s, ts, value);
  if (rc == -1) {
    ValkeyModule_ReplyWithError(ctx, "ERR duplicate sample");
    return -1;
  }
  if (rc == -2) {
    ValkeyModule_ReplyWithError(
        ctx, "ERR timestamp is older than the latest sample");
    return -1;
  }
  if (rc == -3) {
    ValkeyModule_ReplyWithError(ctx, "ERR out of memory");
    return -1;
  }
  *stored_ts = ts;
  return 0;
}

static int TsAdd_Command(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                         int argc) {
  ValkeyModule_AutoMemory(ctx);
  if (argc < 4)
    return ValkeyModule_WrongArity(ctx);
  int64_t ts;
  if (parse_timestamp(ctx, argv[2], &ts, 1) != 0)
    return VALKEYMODULE_OK;
  if (ts < 0)
    return ValkeyModule_ReplyWithError(ctx, "ERR invalid timestamp");
  double value;
  if (ValkeyModule_StringToDouble(argv[3], &value) != VALKEYMODULE_OK) {
    return ValkeyModule_ReplyWithError(ctx, "ERR invalid value");
  }
  int64_t retention = 0;
  int dup_policy = TS_DUP_BLOCK;
  size_t chunk_size = TS_CHUNK_DEFAULT_BYTES;
  int labels_at = -1;
  if (argc > 4 &&
      parse_create_options(ctx, argv, argc, 4, &retention, &dup_policy,
                           &chunk_size, &labels_at) != 0)
    return VALKEYMODULE_OK;

  int64_t stored = 0;
  if (add_one(ctx, argv[1], ts, value, 1, retention, dup_policy, chunk_size,
              &stored) != 0)
    return VALKEYMODULE_OK;
  tsSeries *s = NULL;
  ValkeyModuleKey *key = ValkeyModule_OpenKey(
      ctx, argv[1], VALKEYMODULE_READ | VALKEYMODULE_WRITE);
  s = ValkeyModule_ModuleTypeGetValue(key);
  if (s && labels_at >= 0 && s->total_samples <= 1 &&
      apply_labels(ctx, s, argv, labels_at, argc) != 0)
    return VALKEYMODULE_OK;
  ValkeyModule_ReplicateVerbatim(ctx);
  return ValkeyModule_ReplyWithLongLong(ctx, (long long)stored);
}

static int TsMadd_Command(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                          int argc) {
  ValkeyModule_AutoMemory(ctx);
  if (argc < 4 || ((argc - 1) % 3) != 0)
    return ValkeyModule_WrongArity(ctx);
  int n = (argc - 1) / 3;
  ValkeyModule_ReplyWithArray(ctx, n);
  for (int i = 0; i < n; i++) {
    int base = 1 + i * 3;
    int64_t ts;
    size_t len = 0;
    const char *p = ValkeyModule_StringPtrLen(argv[base + 1], &len);
    int ts_ok = 1;
    if (len == 1 && p[0] == '*')
      ts = (int64_t)ValkeyModule_Milliseconds();
    else {
      long long v;
      if (ValkeyModule_StringToLongLong(argv[base + 1], &v) !=
              VALKEYMODULE_OK ||
          v < 0)
        ts_ok = 0;
      else
        ts = (int64_t)v;
    }
    double value;
    int val_ok =
        ValkeyModule_StringToDouble(argv[base + 2], &value) == VALKEYMODULE_OK;
    if (!ts_ok || !val_ok) {
      ValkeyModule_ReplyWithError(ctx, "ERR invalid timestamp or value");
      continue;
    }
    /* ReplyWithError inside an array element is not how the module API
     * reports a per-item error. Use a bulk error string instead. */
    ValkeyModuleKey *key = ValkeyModule_OpenKey(
        ctx, argv[base], VALKEYMODULE_READ | VALKEYMODULE_WRITE);
    int type = ValkeyModule_KeyType(key);
    if (type != VALKEYMODULE_KEYTYPE_EMPTY &&
        ValkeyModule_ModuleTypeGetType(key) != TsType) {
      ValkeyModule_ReplyWithSimpleString(ctx, "ERR wrong type");
      continue;
    }
    tsSeries *s = NULL;
    if (type == VALKEYMODULE_KEYTYPE_EMPTY) {
      s = series_create(TS_CHUNK_DEFAULT_BYTES, 0, TS_DUP_BLOCK);
      if (!s) {
        ValkeyModule_ReplyWithSimpleString(ctx, "ERR out of memory");
        continue;
      }
      size_t klen = 0;
      const char *k = ValkeyModule_StringPtrLen(argv[base], &klen);
      series_set_key(s, k, klen);
      ValkeyModule_ModuleTypeSetValue(key, TsType, s);
    } else {
      s = ValkeyModule_ModuleTypeGetValue(key);
    }
    int rc = series_add(s, ts, value);
    if (rc < 0) {
      const char *msg = rc == -2
                            ? "ERR timestamp is older than the latest sample"
                        : rc == -1 ? "ERR duplicate sample"
                                   : "ERR out of memory";
      ValkeyModule_ReplyWithSimpleString(ctx, msg);
      continue;
    }
    ValkeyModule_ReplyWithLongLong(ctx, (long long)ts);
  }
  ValkeyModule_ReplicateVerbatim(ctx);
  return VALKEYMODULE_OK;
}

static int TsGet_Command(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                         int argc) {
  ValkeyModule_AutoMemory(ctx);
  if (argc != 2)
    return ValkeyModule_WrongArity(ctx);
  tsSeries *s = NULL;
  ValkeyModuleKey *key = NULL;
  if (open_series(ctx, argv[1], &s, &key, 0, 0, TS_DUP_BLOCK,
                  TS_CHUNK_DEFAULT_BYTES) != 0)
    return VALKEYMODULE_OK;
  if (!s || !s->has_sample)
    return ValkeyModule_ReplyWithArray(ctx, 0);
  ValkeyModule_ReplyWithArray(ctx, 2);
  ValkeyModule_ReplyWithLongLong(ctx, (long long)s->last_ts);
  ValkeyModule_ReplyWithDouble(ctx, s->last_value);
  return VALKEYMODULE_OK;
}

static int parse_range_suffix(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                              int argc, int start, int *agg, int64_t *bucket,
                              long long *count, int *filter_value, double *vmin,
                              double *vmax) {
  *agg = TS_AGG_NONE;
  *bucket = 0;
  *count = -1;
  *filter_value = 0;
  for (int i = start; i < argc; i++) {
    const char *tok = ValkeyModule_StringPtrLen(argv[i], NULL);
    if (!strcasecmp(tok, "AGGREGATION")) {
      if (i + 2 >= argc) {
        ValkeyModule_ReplyWithError(ctx, "ERR syntax error");
        return -1;
      }
      *agg = tsAggFromName(ValkeyModule_StringPtrLen(argv[++i], NULL));
      long long b;
      if (*agg < 0 ||
          ValkeyModule_StringToLongLong(argv[++i], &b) != VALKEYMODULE_OK ||
          b <= 0) {
        ValkeyModule_ReplyWithError(ctx, "ERR invalid AGGREGATION");
        return -1;
      }
      *bucket = (int64_t)b;
    } else if (!strcasecmp(tok, "COUNT")) {
      long long c;
      if (i + 1 >= argc ||
          ValkeyModule_StringToLongLong(argv[++i], &c) != VALKEYMODULE_OK ||
          c < 0) {
        ValkeyModule_ReplyWithError(ctx, "ERR invalid COUNT");
        return -1;
      }
      *count = c;
    } else if (!strcasecmp(tok, "FILTER_BY_VALUE")) {
      if (i + 2 >= argc ||
          ValkeyModule_StringToDouble(argv[i + 1], vmin) != VALKEYMODULE_OK ||
          ValkeyModule_StringToDouble(argv[i + 2], vmax) != VALKEYMODULE_OK) {
        ValkeyModule_ReplyWithError(ctx, "ERR invalid FILTER_BY_VALUE");
        return -1;
      }
      i += 2;
      *filter_value = 1;
    } else {
      ValkeyModule_ReplyWithError(ctx, "ERR syntax error");
      return -1;
    }
  }
  return 0;
}

static int range_command(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                         int argc, int reverse) {
  ValkeyModule_AutoMemory(ctx);
  if (argc < 4)
    return ValkeyModule_WrongArity(ctx);
  int64_t from, to;
  if (parse_timestamp(ctx, argv[2], &from, 0) != 0)
    return VALKEYMODULE_OK;
  if (parse_timestamp(ctx, argv[3], &to, 0) != 0)
    return VALKEYMODULE_OK;
  if (from == INT64_MIN)
    from = 0;
  int agg, filter_value;
  int64_t bucket;
  long long count;
  double vmin, vmax;
  if (parse_range_suffix(ctx, argv, argc, 4, &agg, &bucket, &count,
                         &filter_value, &vmin, &vmax) != 0)
    return VALKEYMODULE_OK;
  tsSeries *s = NULL;
  ValkeyModuleKey *key = NULL;
  if (open_series(ctx, argv[1], &s, &key, 0, 0, TS_DUP_BLOCK,
                  TS_CHUNK_DEFAULT_BYTES) != 0)
    return VALKEYMODULE_OK;
  if (tsReplySamples(ctx, s, from, to, reverse, agg, bucket, count,
                     filter_value, vmin, vmax) != 0) {
    return ValkeyModule_ReplyWithError(ctx, "ERR query failed");
  }
  return VALKEYMODULE_OK;
}

static int TsRange_Command(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                           int argc) {
  return range_command(ctx, argv, argc, 0);
}

static int TsRevRange_Command(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                              int argc) {
  return range_command(ctx, argv, argc, 1);
}

typedef struct mrange_hit {
  tsSeries *series;
  char *key;
} mrange_hit;

typedef struct mrange_scan {
  tsFilter *filters;
  int nfilters;
  mrange_hit *hits;
  int n;
  int cap;
} mrange_scan;

/* Called by ValkeyModule_Scan. The key object is owned by the scan when it
 * is passed in. A missing key is opened for this call only; AutoMemory on
 * the command context releases that handle. */
static void mrange_on_key(ValkeyModuleCtx *ctx, ValkeyModuleString *keyname,
                          ValkeyModuleKey *key, void *privdata) {
  mrange_scan *st = privdata;
  if (!key)
    key = ValkeyModule_OpenKey(ctx, keyname, VALKEYMODULE_READ);
  if (!key)
    return;
  if (ValkeyModule_KeyType(key) != VALKEYMODULE_KEYTYPE_MODULE ||
      ValkeyModule_ModuleTypeGetType(key) != TsType)
    return;
  tsSeries *s = ValkeyModule_ModuleTypeGetValue(key);
  if (!s || !filters_match(s, st->filters, st->nfilters))
    return;
  if (st->n == st->cap) {
    int ncap = st->cap ? st->cap * 2 : 8;
    mrange_hit *grown = realloc(st->hits, sizeof(*grown) * (size_t)ncap);
    if (!grown)
      return;
    st->hits = grown;
    st->cap = ncap;
  }
  size_t klen = 0;
  const char *k = ValkeyModule_StringPtrLen(keyname, &klen);
  st->hits[st->n].series = s;
  st->hits[st->n].key = dup_cstr(k, klen);
  st->n++;
}

static int TsMrange_Command(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                            int argc) {
  ValkeyModule_AutoMemory(ctx);
  if (argc < 4)
    return ValkeyModule_WrongArity(ctx);
  int64_t from, to;
  if (parse_timestamp(ctx, argv[1], &from, 0) != 0)
    return VALKEYMODULE_OK;
  if (parse_timestamp(ctx, argv[2], &to, 0) != 0)
    return VALKEYMODULE_OK;
  if (from < 0)
    from = 0;
  int withlabels = 0;
  int filter_at = -1;
  int agg = TS_AGG_NONE;
  int64_t bucket = 0;
  long long count = -1;
  for (int i = 3; i < argc; i++) {
    const char *tok = ValkeyModule_StringPtrLen(argv[i], NULL);
    if (!strcasecmp(tok, "WITHLABELS")) {
      withlabels = 1;
    } else if (!strcasecmp(tok, "FILTER")) {
      filter_at = i + 1;
      break;
    } else if (!strcasecmp(tok, "AGGREGATION")) {
      if (i + 2 >= argc)
        return ValkeyModule_ReplyWithError(ctx, "ERR syntax error");
      agg = tsAggFromName(ValkeyModule_StringPtrLen(argv[++i], NULL));
      long long b;
      if (agg < 0 ||
          ValkeyModule_StringToLongLong(argv[++i], &b) != VALKEYMODULE_OK ||
          b <= 0) {
        return ValkeyModule_ReplyWithError(ctx, "ERR invalid AGGREGATION");
      }
      bucket = (int64_t)b;
    } else if (!strcasecmp(tok, "COUNT")) {
      long long c;
      if (i + 1 >= argc ||
          ValkeyModule_StringToLongLong(argv[++i], &c) != VALKEYMODULE_OK ||
          c < 0) {
        return ValkeyModule_ReplyWithError(ctx, "ERR invalid COUNT");
      }
      count = c;
    } else {
      return ValkeyModule_ReplyWithError(ctx, "ERR syntax error");
    }
  }
  if (filter_at < 0 || filter_at >= argc)
    return ValkeyModule_ReplyWithError(ctx, "ERR FILTER is required");
  int nfilters = argc - filter_at;
  tsFilter *filters = calloc((size_t)nfilters, sizeof(tsFilter));
  if (!filters)
    return ValkeyModule_ReplyWithError(ctx, "ERR out of memory");
  for (int i = 0; i < nfilters; i++) {
    if (parse_filter(ValkeyModule_StringPtrLen(argv[filter_at + i], NULL),
                     &filters[i]) != 0) {
      ValkeyModule_ReplyWithError(ctx, "ERR invalid filter");
      for (int j = 0; j < i; j++) {
        free(filters[j].key);
        free(filters[j].val);
      }
      free(filters);
      return VALKEYMODULE_OK;
    }
  }

  /* Scan the live keyspace. A side index would still point at values that
   * FLUSH / DEBUG RELOAD has unlinked but not freed yet (lazy free runs off
   * the main thread). */
  mrange_scan scan;
  memset(&scan, 0, sizeof(scan));
  scan.filters = filters;
  scan.nfilters = nfilters;
  ValkeyModuleScanCursor *cursor = ValkeyModule_ScanCursorCreate();
  while (ValkeyModule_Scan(ctx, cursor, mrange_on_key, &scan)) {
  }
  ValkeyModule_ScanCursorDestroy(cursor);

  ValkeyModule_ReplyWithArray(ctx, scan.n);
  for (int i = 0; i < scan.n; i++) {
    tsSeries *s = scan.hits[i].series;
    ValkeyModule_ReplyWithArray(ctx, 3);
    ValkeyModule_ReplyWithCString(ctx,
                                  scan.hits[i].key ? scan.hits[i].key : "");
    if (withlabels)
      reply_labels(ctx, s);
    else
      ValkeyModule_ReplyWithArray(ctx, 0);
    if (tsReplySamples(ctx, s, from, to, 0, agg, bucket, count, 0, 0, 0) != 0) {
      ValkeyModule_ReplyWithArray(ctx, 0);
    }
    free(scan.hits[i].key);
  }
  free(scan.hits);
  for (int i = 0; i < nfilters; i++) {
    free(filters[i].key);
    free(filters[i].val);
  }
  free(filters);
  return VALKEYMODULE_OK;
}

static int TsDel_Command(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                         int argc) {
  ValkeyModule_AutoMemory(ctx);
  if (argc != 4)
    return ValkeyModule_WrongArity(ctx);
  int64_t from, to;
  if (parse_timestamp(ctx, argv[2], &from, 0) != 0)
    return VALKEYMODULE_OK;
  if (parse_timestamp(ctx, argv[3], &to, 0) != 0)
    return VALKEYMODULE_OK;
  if (from < 0)
    from = 0;
  tsSeries *s = NULL;
  ValkeyModuleKey *key = NULL;
  if (open_series(ctx, argv[1], &s, &key, 0, 0, TS_DUP_BLOCK,
                  TS_CHUNK_DEFAULT_BYTES) != 0)
    return VALKEYMODULE_OK;
  if (!s)
    return ValkeyModule_ReplyWithLongLong(ctx, 0);
  long long removed = 0;
  if (series_delete_range(s, from, to, &removed) != 0)
    return ValkeyModule_ReplyWithError(ctx, "ERR delete failed");
  ValkeyModule_ReplicateVerbatim(ctx);
  return ValkeyModule_ReplyWithLongLong(ctx, removed);
}

static int TsLabel_Command(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                           int argc) {
  ValkeyModule_AutoMemory(ctx);
  if (argc != 4)
    return ValkeyModule_WrongArity(ctx);
  tsSeries *s = NULL;
  ValkeyModuleKey *key = NULL;
  if (open_series(ctx, argv[1], &s, &key, 0, 0, TS_DUP_BLOCK,
                  TS_CHUNK_DEFAULT_BYTES) != 0)
    return VALKEYMODULE_OK;
  if (!s)
    return ValkeyModule_ReplyWithError(ctx, "ERR key does not exist");
  if (apply_labels(ctx, s, argv, 2, 4) != 0)
    return VALKEYMODULE_OK;
  ValkeyModule_ReplicateVerbatim(ctx);
  return ValkeyModule_ReplyWithSimpleString(ctx, "OK");
}

static void *TsRdbLoad(ValkeyModuleIO *rdb, int encver) {
  if (encver != 1)
    return NULL;
  int64_t retention = (int64_t)ValkeyModule_LoadSigned(rdb);
  int dup_policy = (int)ValkeyModule_LoadUnsigned(rdb);
  uint64_t chunk_size = ValkeyModule_LoadUnsigned(rdb);
  uint64_t nlabels = ValkeyModule_LoadUnsigned(rdb);
  tsSeries *s = series_create((size_t)chunk_size, retention, dup_policy);
  if (!s)
    return NULL;
  for (uint64_t i = 0; i < nlabels; i++) {
    size_t klen = 0, vlen = 0;
    char *k = ValkeyModule_LoadStringBuffer(rdb, &klen);
    char *v = ValkeyModule_LoadStringBuffer(rdb, &vlen);
    if (!k || !v) {
      if (k)
        ValkeyModule_Free(k);
      if (v)
        ValkeyModule_Free(v);
      series_free(s);
      return NULL;
    }
    char *ks = dup_cstr(k, klen);
    char *vs = dup_cstr(v, vlen);
    ValkeyModule_Free(k);
    ValkeyModule_Free(v);
    if (!ks || !vs || series_set_label(s, ks, vs) != 0) {
      free(ks);
      free(vs);
      series_free(s);
      return NULL;
    }
    free(ks);
    free(vs);
  }
  uint64_t nsamples = ValkeyModule_LoadUnsigned(rdb);
  for (uint64_t i = 0; i < nsamples; i++) {
    int64_t ts = (int64_t)ValkeyModule_LoadSigned(rdb);
    double value = ValkeyModule_LoadDouble(rdb);
    if (chunk_push_sample(s, ts, value) != 0) {
      series_free(s);
      return NULL;
    }
  }
  const ValkeyModuleString *keyname = ValkeyModule_GetKeyNameFromIO(rdb);
  if (keyname) {
    size_t klen = 0;
    const char *k = ValkeyModule_StringPtrLen(keyname, &klen);
    series_set_key(s, k, klen);
  }
  if (ValkeyModule_IsIOError(rdb)) {
    series_free(s);
    return NULL;
  }
  return s;
}

static void TsRdbSave(ValkeyModuleIO *rdb, void *value) {
  tsSeries *s = value;
  ValkeyModule_SaveSigned(rdb, s->retention_ms);
  ValkeyModule_SaveUnsigned(rdb, (uint64_t)s->dup_policy);
  ValkeyModule_SaveUnsigned(rdb, (uint64_t)s->chunk_size);
  ValkeyModule_SaveUnsigned(rdb, (uint64_t)s->nlabels);
  for (int i = 0; i < s->nlabels; i++) {
    ValkeyModule_SaveStringBuffer(rdb, s->labels[i].key,
                                  strlen(s->labels[i].key));
    ValkeyModule_SaveStringBuffer(rdb, s->labels[i].val,
                                  strlen(s->labels[i].val));
  }
  tsSample *samples = NULL;
  size_t n = 0;
  if (load_all_samples(s, &samples, &n) != 0) {
    ValkeyModule_SaveUnsigned(rdb, 0);
    return;
  }
  ValkeyModule_SaveUnsigned(rdb, (uint64_t)n);
  for (size_t i = 0; i < n; i++) {
    ValkeyModule_SaveSigned(rdb, samples[i].ts);
    ValkeyModule_SaveDouble(rdb, samples[i].value);
  }
  free(samples);
}

static void TsAofRewrite(ValkeyModuleIO *aof, ValkeyModuleString *key,
                         void *value) {
  tsSeries *s = value;
  ValkeyModule_EmitAOF(aof, "TS.CREATE", "sclcc", key, "RETENTION",
                       (long long)s->retention_ms, "DUPLICATE_POLICY",
                       tsDupPolicyName(s->dup_policy));
  for (int i = 0; i < s->nlabels; i++) {
    ValkeyModule_EmitAOF(aof, "TS.LABEL", "scc", key, s->labels[i].key,
                         s->labels[i].val);
  }
  tsSample *samples = NULL;
  size_t n = 0;
  if (load_all_samples(s, &samples, &n) != 0)
    return;
  for (size_t i = 0; i < n; i++) {
    char buf[64];
    snprintf(buf, sizeof(buf), "%.17g", samples[i].value);
    ValkeyModule_EmitAOF(aof, "TS.ADD", "slc", key, (long long)samples[i].ts,
                         buf);
  }
  free(samples);
}

static size_t TsMemUsage(const void *value) {
  return tsSeriesStorageBytes(value);
}

static void TsFree(void *value) { series_free(value); }

static void TsDigest(ValkeyModuleDigest *md, void *value) {
  tsSeries *s = value;
  tsSample *samples = NULL;
  size_t n = 0;
  if (load_all_samples(s, &samples, &n) != 0)
    return;
  for (size_t i = 0; i < n; i++) {
    ValkeyModule_DigestAddLongLong(md, samples[i].ts);
    uint64_t bits;
    memcpy(&bits, &samples[i].value, sizeof(bits));
    ValkeyModule_DigestAddStringBuffer(md, (char *)&bits, sizeof(bits));
  }
  free(samples);
  ValkeyModule_DigestEndSequence(md);
}

int ValkeyModule_OnLoad(ValkeyModuleCtx *ctx, ValkeyModuleString **argv,
                        int argc) {
  VALKEYMODULE_NOT_USED(argv);
  VALKEYMODULE_NOT_USED(argc);
  if (ValkeyModule_Init(ctx, "timeseries", 1, VALKEYMODULE_APIVER_1) ==
      VALKEYMODULE_ERR)
    return VALKEYMODULE_ERR;

  ValkeyModuleTypeMethods tm = {.version = VALKEYMODULE_TYPE_METHOD_VERSION,
                                .rdb_load = TsRdbLoad,
                                .rdb_save = TsRdbSave,
                                .aof_rewrite = TsAofRewrite,
                                .mem_usage = TsMemUsage,
                                .free = TsFree,
                                .digest = TsDigest};
  TsType = ValkeyModule_CreateDataType(ctx, "cmo-ts-v1", 1, &tm);
  if (TsType == NULL)
    return VALKEYMODULE_ERR;

  if (ValkeyModule_CreateCommand(ctx, "ts.create", TsCreate_Command,
                                 "write deny-oom", 1, 1, 1) == VALKEYMODULE_ERR)
    return VALKEYMODULE_ERR;
  if (ValkeyModule_CreateCommand(ctx, "ts.add", TsAdd_Command, "write deny-oom",
                                 1, 1, 1) == VALKEYMODULE_ERR)
    return VALKEYMODULE_ERR;
  if (ValkeyModule_CreateCommand(ctx, "ts.madd", TsMadd_Command,
                                 "write deny-oom", 1, -3,
                                 3) == VALKEYMODULE_ERR)
    return VALKEYMODULE_ERR;
  if (ValkeyModule_CreateCommand(ctx, "ts.get", TsGet_Command, "readonly", 1, 1,
                                 1) == VALKEYMODULE_ERR)
    return VALKEYMODULE_ERR;
  if (ValkeyModule_CreateCommand(ctx, "ts.range", TsRange_Command, "readonly",
                                 1, 1, 1) == VALKEYMODULE_ERR)
    return VALKEYMODULE_ERR;
  if (ValkeyModule_CreateCommand(ctx, "ts.revrange", TsRevRange_Command,
                                 "readonly", 1, 1, 1) == VALKEYMODULE_ERR)
    return VALKEYMODULE_ERR;
  if (ValkeyModule_CreateCommand(ctx, "ts.mrange", TsMrange_Command, "readonly",
                                 0, 0, 0) == VALKEYMODULE_ERR)
    return VALKEYMODULE_ERR;
  if (ValkeyModule_CreateCommand(ctx, "ts.del", TsDel_Command, "write", 1, 1,
                                 1) == VALKEYMODULE_ERR)
    return VALKEYMODULE_ERR;
  if (ValkeyModule_CreateCommand(ctx, "ts.label", TsLabel_Command,
                                 "write deny-oom", 1, 1, 1) == VALKEYMODULE_ERR)
    return VALKEYMODULE_ERR;
  return VALKEYMODULE_OK;
}
