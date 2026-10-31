/* Active-active CRDT state for strings, counters, sets, and hashes.
 *
 * Strings and hash fields are last-writer-wins on a hybrid logical clock
 * (Kulkarni et al.). Counters are per-region PN-counters. Sets are
 * observed-remove sets. Deletes are tombstones. The merge is commutative,
 * associative, and idempotent for a fixed kind. A kind change or a tombstone
 * is decided by the clock so concurrent updates of different kinds still
 * converge.
 *
 * Copyright (c) 2026, Cache Me Outside contributors.
 * Licensed under the BSD 3-Clause License, the same terms as the server.
 */
#ifndef CMO_CRDT_H
#define CMO_CRDT_H

#include <stddef.h>
#include <stdint.h>

typedef struct hlc {
    uint64_t pt;
    uint32_t lc;
    uint16_t region;
} hlc;

/* Positive if a wins, negative if b wins, 0 if identical. */
int hlcCompare(const hlc *a, const hlc *b);
void hlcLocalEvent(hlc *h, uint64_t wall_ms, uint16_t region);
void hlcReceive(hlc *h, const hlc *remote, uint64_t wall_ms);

enum {
    CRDT_KIND_NONE = 0,
    CRDT_KIND_STRING = 1,
    CRDT_KIND_COUNTER = 2,
    CRDT_KIND_SET = 3,
    CRDT_KIND_HASH = 4,
    CRDT_KIND_TOMB = 5
};

typedef struct crdtPn {
    uint16_t region;
    uint64_t p;
    uint64_t n;
} crdtPn;

typedef struct crdtTag {
    uint16_t region;
    uint32_t seq;
} crdtTag;

typedef struct crdtElem {
    char *member;
    size_t member_len;
    crdtTag *adds;
    int nadds;
    crdtTag *rems;
    int nrems;
} crdtElem;

typedef struct crdtField {
    char *field;
    size_t field_len;
    char *value;
    size_t value_len;
    hlc clock;
    int deleted;
} crdtField;

typedef struct crdtState {
    int kind; /* Visible kind, derived after every mutation and merge. */
    hlc clock;
    int has_string, has_counter, has_set, has_hash, has_tomb;
    hlc string_clock, counter_clock, set_clock, hash_clock, tomb_clock;
    char *str;
    size_t str_len;
    crdtPn *pn;
    int npn;
    crdtElem *elems;
    int nelems;
    uint32_t set_seq;
    crdtField *fields;
    int nfields;
} crdtState;

void crdtStateInit(crdtState *s);
void crdtStateClear(crdtState *s);
void crdtStateCopy(crdtState *dst, const crdtState *src);
int crdtStateEqual(const crdtState *a, const crdtState *b);

void crdtMerge(crdtState *dst, const crdtState *src);

void crdtStringSet(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, const char *v, size_t n);
void crdtCounterAdd(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, int64_t delta);
long long crdtCounterValue(const crdtState *s);
void crdtSetAdd(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, const char *m, size_t n);
void crdtSetRemove(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, const char *m, size_t n);
int crdtSetContains(const crdtState *s, const char *m, size_t n);
void crdtHashSet(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, const char *f, size_t fn, const char *v, size_t vn);
void crdtHashDel(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, const char *f, size_t fn);
void crdtTombstone(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region);

/* 1 if the tombstone is old enough and every peer has observed `ack_pt`. */
int crdtTombstoneExpired(const crdtState *s, uint64_t now_ms, uint64_t gc_ms, uint64_t ack_pt);

char *crdtEncode(const crdtState *s, size_t *len);
void crdtFreeBuffer(void *p);
int crdtDecode(crdtState *s, const char *buf, size_t len);

#endif
