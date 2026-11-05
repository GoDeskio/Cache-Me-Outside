#include "crdt.h"

#include <stdlib.h>
#include <string.h>

static void *xmalloc(size_t n) {
    void *p = calloc(1, n ? n : 1);
    if (!p) abort();
    return p;
}

static char *xdup(const char *s, size_t n) {
    char *p = xmalloc(n + 1);
    if (n) memcpy(p, s, n);
    p[n] = '\0';
    return p;
}

static int tagEq(crdtTag a, crdtTag b) {
    return a.region == b.region && a.seq == b.seq;
}

static int tagHas(const crdtTag *t, int n, crdtTag x) {
    int i;
    for (i = 0; i < n; i++)
        if (tagEq(t[i], x)) return 1;
    return 0;
}

static void tagAdd(crdtTag **arr, int *n, crdtTag x) {
    if (tagHas(*arr, *n, x)) return;
    *arr = realloc(*arr, sizeof(crdtTag) * (size_t)(*n + 1));
    if (!*arr) abort();
    (*arr)[*n] = x;
    (*n)++;
}

void crdtStateInit(crdtState *s) {
    memset(s, 0, sizeof(*s));
}

void crdtStateClear(crdtState *s) {
    int i;
    free(s->str);
    free(s->pn);
    for (i = 0; i < s->nelems; i++) {
        free(s->elems[i].member);
        free(s->elems[i].adds);
        free(s->elems[i].rems);
    }
    free(s->elems);
    for (i = 0; i < s->nfields; i++) {
        free(s->fields[i].field);
        free(s->fields[i].value);
    }
    free(s->fields);
    memset(s, 0, sizeof(*s));
}

static void copyElem(crdtElem *d, const crdtElem *s) {
    memset(d, 0, sizeof(*d));
    d->member = xdup(s->member, s->member_len);
    d->member_len = s->member_len;
    if (s->nadds) {
        d->adds = xmalloc(sizeof(crdtTag) * (size_t)s->nadds);
        memcpy(d->adds, s->adds, sizeof(crdtTag) * (size_t)s->nadds);
        d->nadds = s->nadds;
    }
    if (s->nrems) {
        d->rems = xmalloc(sizeof(crdtTag) * (size_t)s->nrems);
        memcpy(d->rems, s->rems, sizeof(crdtTag) * (size_t)s->nrems);
        d->nrems = s->nrems;
    }
}

void crdtStateCopy(crdtState *dst, const crdtState *src) {
    int i;
    crdtStateClear(dst);
    dst->kind = src->kind;
    dst->clock = src->clock;
    dst->has_string = src->has_string;
    dst->has_counter = src->has_counter;
    dst->has_set = src->has_set;
    dst->has_hash = src->has_hash;
    dst->has_tomb = src->has_tomb;
    dst->string_clock = src->string_clock;
    dst->counter_clock = src->counter_clock;
    dst->set_clock = src->set_clock;
    dst->hash_clock = src->hash_clock;
    dst->tomb_clock = src->tomb_clock;
    dst->set_seq = src->set_seq;
    if (src->str) {
        dst->str = xdup(src->str, src->str_len);
        dst->str_len = src->str_len;
    }
    if (src->npn) {
        dst->pn = xmalloc(sizeof(crdtPn) * (size_t)src->npn);
        memcpy(dst->pn, src->pn, sizeof(crdtPn) * (size_t)src->npn);
        dst->npn = src->npn;
    }
    if (src->nelems) {
        dst->elems = xmalloc(sizeof(crdtElem) * (size_t)src->nelems);
        dst->nelems = src->nelems;
        for (i = 0; i < src->nelems; i++) copyElem(&dst->elems[i], &src->elems[i]);
    }
    if (src->nfields) {
        dst->fields = xmalloc(sizeof(crdtField) * (size_t)src->nfields);
        dst->nfields = src->nfields;
        for (i = 0; i < src->nfields; i++) {
            dst->fields[i].field = xdup(src->fields[i].field, src->fields[i].field_len);
            dst->fields[i].field_len = src->fields[i].field_len;
            dst->fields[i].value = src->fields[i].value ? xdup(src->fields[i].value, src->fields[i].value_len) : NULL;
            dst->fields[i].value_len = src->fields[i].value_len;
            dst->fields[i].clock = src->fields[i].clock;
            dst->fields[i].deleted = src->fields[i].deleted;
        }
    }
}

static int bytesEq(const char *a, size_t an, const char *b, size_t bn) {
    if (an != bn) return 0;
    if (an == 0) return 1;
    return memcmp(a, b, an) == 0;
}

static int elemPresent(const crdtElem *e) {
    int i;
    for (i = 0; i < e->nadds; i++)
        if (!tagHas(e->rems, e->nrems, e->adds[i])) return 1;
    return 0;
}

int crdtSetContains(const crdtState *s, const char *m, size_t n) {
    int i;
    if (s->kind != CRDT_KIND_SET) return 0;
    for (i = 0; i < s->nelems; i++) {
        if (bytesEq(s->elems[i].member, s->elems[i].member_len, m, n)) return elemPresent(&s->elems[i]);
    }
    return 0;
}

long long crdtCounterValue(const crdtState *s) {
    long long v = 0;
    int i;
    if (s->kind != CRDT_KIND_COUNTER) return 0;
    for (i = 0; i < s->npn; i++) v += (long long)s->pn[i].p - (long long)s->pn[i].n;
    return v;
}

static int fieldsEq(const crdtState *a, const crdtState *b) {
    int i, j;
    if (a->nfields != b->nfields) return 0;
    for (i = 0; i < a->nfields; i++) {
        int found = 0;
        for (j = 0; j < b->nfields; j++) {
            if (!bytesEq(a->fields[i].field, a->fields[i].field_len, b->fields[j].field, b->fields[j].field_len)) continue;
            found = 1;
            if (a->fields[i].deleted != b->fields[j].deleted) return 0;
            if (!a->fields[i].deleted && !bytesEq(a->fields[i].value, a->fields[i].value_len, b->fields[j].value, b->fields[j].value_len))
                return 0;
            if (hlcCompare(&a->fields[i].clock, &b->fields[j].clock) != 0) return 0;
        }
        if (!found) return 0;
    }
    return 1;
}

static int tagsEq(const crdtTag *a, int na, const crdtTag *b, int nb) {
    int i;
    if (na != nb) return 0;
    for (i = 0; i < na; i++)
        if (!tagHas(b, nb, a[i])) return 0;
    return 1;
}

static int elemsEq(const crdtState *a, const crdtState *b) {
    int i;
    if (a->nelems != b->nelems) return 0;
    for (i = 0; i < a->nelems; i++) {
        int j, found = 0;
        for (j = 0; j < b->nelems; j++) {
            if (!bytesEq(a->elems[i].member, a->elems[i].member_len, b->elems[j].member, b->elems[j].member_len)) continue;
            found = 1;
            if (!tagsEq(a->elems[i].adds, a->elems[i].nadds, b->elems[j].adds, b->elems[j].nadds)) return 0;
            if (!tagsEq(a->elems[i].rems, a->elems[i].nrems, b->elems[j].rems, b->elems[j].nrems)) return 0;
        }
        if (!found) return 0;
    }
    return 1;
}

int crdtStateEqual(const crdtState *a, const crdtState *b) {
    if (a->kind != b->kind) return 0;
    if (hlcCompare(&a->clock, &b->clock) != 0) return 0;
    if (a->has_string != b->has_string || a->has_counter != b->has_counter || a->has_set != b->has_set ||
        a->has_hash != b->has_hash || a->has_tomb != b->has_tomb)
        return 0;
    if (a->has_string && (hlcCompare(&a->string_clock, &b->string_clock) != 0 || !bytesEq(a->str, a->str_len, b->str, b->str_len)))
        return 0;
    if (a->has_counter) {
        int i, j;
        if (a->npn != b->npn || hlcCompare(&a->counter_clock, &b->counter_clock) != 0) return 0;
        for (i = 0; i < a->npn; i++) {
            int found = 0;
            for (j = 0; j < b->npn; j++) {
                if (a->pn[i].region != b->pn[j].region) continue;
                found = 1;
                if (a->pn[i].p != b->pn[j].p || a->pn[i].n != b->pn[j].n) return 0;
            }
            if (!found) return 0;
        }
    }
    if (a->has_set && (hlcCompare(&a->set_clock, &b->set_clock) != 0 || !elemsEq(a, b))) return 0;
    if (a->has_hash && (hlcCompare(&a->hash_clock, &b->hash_clock) != 0 || !fieldsEq(a, b))) return 0;
    if (a->has_tomb && hlcCompare(&a->tomb_clock, &b->tomb_clock) != 0) return 0;
    return 1;
}

static crdtPn *pnSlot(crdtState *s, uint16_t region) {
    int i;
    for (i = 0; i < s->npn; i++)
        if (s->pn[i].region == region) return &s->pn[i];
    s->pn = realloc(s->pn, sizeof(crdtPn) * (size_t)(s->npn + 1));
    if (!s->pn) abort();
    memset(&s->pn[s->npn], 0, sizeof(crdtPn));
    s->pn[s->npn].region = region;
    return &s->pn[s->npn++];
}

static void mergePn(crdtState *dst, const crdtState *src) {
    int i;
    for (i = 0; i < src->npn; i++) {
        crdtPn *slot = pnSlot(dst, src->pn[i].region);
        if (src->pn[i].p > slot->p) slot->p = src->pn[i].p;
        if (src->pn[i].n > slot->n) slot->n = src->pn[i].n;
    }
}

static crdtElem *findElem(crdtState *s, const char *m, size_t n, int create) {
    int i;
    for (i = 0; i < s->nelems; i++)
        if (bytesEq(s->elems[i].member, s->elems[i].member_len, m, n)) return &s->elems[i];
    if (!create) return NULL;
    s->elems = realloc(s->elems, sizeof(crdtElem) * (size_t)(s->nelems + 1));
    if (!s->elems) abort();
    memset(&s->elems[s->nelems], 0, sizeof(crdtElem));
    s->elems[s->nelems].member = xdup(m, n);
    s->elems[s->nelems].member_len = n;
    return &s->elems[s->nelems++];
}

static void mergeElem(crdtElem *d, const crdtElem *s) {
    int i;
    for (i = 0; i < s->nadds; i++) tagAdd(&d->adds, &d->nadds, s->adds[i]);
    for (i = 0; i < s->nrems; i++) tagAdd(&d->rems, &d->nrems, s->rems[i]);
}

static void mergeSet(crdtState *dst, const crdtState *src) {
    int i;
    for (i = 0; i < src->nelems; i++) {
        crdtElem *e = findElem(dst, src->elems[i].member, src->elems[i].member_len, 1);
        mergeElem(e, &src->elems[i]);
    }
}

static crdtField *findField(crdtState *s, const char *f, size_t n, int create) {
    int i;
    for (i = 0; i < s->nfields; i++)
        if (bytesEq(s->fields[i].field, s->fields[i].field_len, f, n)) return &s->fields[i];
    if (!create) return NULL;
    s->fields = realloc(s->fields, sizeof(crdtField) * (size_t)(s->nfields + 1));
    if (!s->fields) abort();
    memset(&s->fields[s->nfields], 0, sizeof(crdtField));
    s->fields[s->nfields].field = xdup(f, n);
    s->fields[s->nfields].field_len = n;
    return &s->fields[s->nfields++];
}

static void mergeHash(crdtState *dst, const crdtState *src) {
    int i;
    for (i = 0; i < src->nfields; i++) {
        const crdtField *sf = &src->fields[i];
        crdtField *df = findField(dst, sf->field, sf->field_len, 1);
        if (hlcCompare(&sf->clock, &df->clock) > 0) {
            free(df->value);
            df->value = sf->value ? xdup(sf->value, sf->value_len) : NULL;
            df->value_len = sf->value_len;
            df->deleted = sf->deleted;
            df->clock = sf->clock;
        }
    }
}

static void refreshVisible(crdtState *s) {
    hlc best;
    int kind = CRDT_KIND_NONE;
    memset(&best, 0, sizeof(best));
    s->kind = CRDT_KIND_NONE;
    memset(&s->clock, 0, sizeof(s->clock));
    if (s->has_string && hlcCompare(&s->string_clock, &best) > 0) {
        best = s->string_clock;
        kind = CRDT_KIND_STRING;
    }
    if (s->has_counter && hlcCompare(&s->counter_clock, &best) > 0) {
        best = s->counter_clock;
        kind = CRDT_KIND_COUNTER;
    }
    if (s->has_set && hlcCompare(&s->set_clock, &best) > 0) {
        best = s->set_clock;
        kind = CRDT_KIND_SET;
    }
    if (s->has_hash && hlcCompare(&s->hash_clock, &best) > 0) {
        best = s->hash_clock;
        kind = CRDT_KIND_HASH;
    }
    if (s->has_tomb && hlcCompare(&s->tomb_clock, &best) > 0) {
        best = s->tomb_clock;
        kind = CRDT_KIND_TOMB;
    }
    s->kind = kind;
    s->clock = best;
}

void crdtMerge(crdtState *dst, const crdtState *src) {
    if (!src) return;
    if (src->has_string && (!dst->has_string || hlcCompare(&src->string_clock, &dst->string_clock) > 0)) {
        free(dst->str);
        dst->str = src->str ? xdup(src->str, src->str_len) : NULL;
        dst->str_len = src->str_len;
        dst->string_clock = src->string_clock;
        dst->has_string = 1;
    }
    if (src->has_counter) {
        if (!dst->has_counter) dst->has_counter = 1;
        mergePn(dst, src);
        if (hlcCompare(&src->counter_clock, &dst->counter_clock) > 0) dst->counter_clock = src->counter_clock;
    }
    if (src->has_set) {
        if (!dst->has_set) dst->has_set = 1;
        mergeSet(dst, src);
        if (hlcCompare(&src->set_clock, &dst->set_clock) > 0) dst->set_clock = src->set_clock;
    }
    if (src->has_hash) {
        if (!dst->has_hash) dst->has_hash = 1;
        mergeHash(dst, src);
        if (hlcCompare(&src->hash_clock, &dst->hash_clock) > 0) dst->hash_clock = src->hash_clock;
    }
    if (src->has_tomb && (!dst->has_tomb || hlcCompare(&src->tomb_clock, &dst->tomb_clock) > 0)) {
        dst->has_tomb = 1;
        dst->tomb_clock = src->tomb_clock;
    }
    refreshVisible(dst);
}

static void bump(hlc *local, hlc *slot, uint64_t wall, uint16_t region) {
    hlcLocalEvent(local, wall, region);
    *slot = *local;
}

void crdtStringSet(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, const char *v, size_t n) {
    free(s->str);
    s->has_string = 1;
    s->str = xdup(v ? v : "", n);
    s->str_len = n;
    bump(local, &s->string_clock, wall_ms, region);
    refreshVisible(s);
}

void crdtCounterAdd(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, int64_t delta) {
    crdtPn *slot = pnSlot(s, region);
    s->has_counter = 1;
    if (delta >= 0) slot->p += (uint64_t)delta;
    else slot->n += (uint64_t)(-delta);
    bump(local, &s->counter_clock, wall_ms, region);
    refreshVisible(s);
}

void crdtSetAdd(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, const char *m, size_t n) {
    crdtElem *e;
    crdtTag tag;
    s->has_set = 1;
    s->set_seq++;
    tag.region = region;
    tag.seq = s->set_seq;
    e = findElem(s, m, n, 1);
    tagAdd(&e->adds, &e->nadds, tag);
    bump(local, &s->set_clock, wall_ms, region);
    refreshVisible(s);
}

void crdtSetRemove(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, const char *m, size_t n) {
    crdtElem *e;
    int i;
    if (!s->has_set) return;
    e = findElem(s, m, n, 0);
    if (!e) return;
    for (i = 0; i < e->nadds; i++) tagAdd(&e->rems, &e->nrems, e->adds[i]);
    bump(local, &s->set_clock, wall_ms, region);
    refreshVisible(s);
}

void crdtHashSet(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, const char *f, size_t fn, const char *v, size_t vn) {
    crdtField *field;
    s->has_hash = 1;
    field = findField(s, f, fn, 1);
    free(field->value);
    field->value = xdup(v ? v : "", vn);
    field->value_len = vn;
    field->deleted = 0;
    hlcLocalEvent(local, wall_ms, region);
    field->clock = *local;
    s->hash_clock = *local;
    refreshVisible(s);
}

void crdtHashDel(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region, const char *f, size_t fn) {
    crdtField *field;
    if (!s->has_hash) return;
    field = findField(s, f, fn, 1);
    free(field->value);
    field->value = NULL;
    field->value_len = 0;
    field->deleted = 1;
    hlcLocalEvent(local, wall_ms, region);
    field->clock = *local;
    s->hash_clock = *local;
    refreshVisible(s);
}

void crdtTombstone(crdtState *s, hlc *local, uint64_t wall_ms, uint16_t region) {
    s->has_tomb = 1;
    bump(local, &s->tomb_clock, wall_ms, region);
    refreshVisible(s);
}

int crdtTombstoneExpired(const crdtState *s, uint64_t now_ms, uint64_t gc_ms, uint64_t ack_pt) {
    if (s->kind != CRDT_KIND_TOMB) return 0;
    if (s->clock.pt > ack_pt) return 0;
    if (now_ms < s->clock.pt) return 0;
    return now_ms - s->clock.pt >= gc_ms;
}

/* Compact binary form. Lengths are little-endian. */
static void putU8(char **p, uint8_t v) {
    *(*p)++ = (char)v;
}
static void putU16(char **p, uint16_t v) {
    memcpy(*p, &v, 2);
    *p += 2;
}
static void putU32(char **p, uint32_t v) {
    memcpy(*p, &v, 4);
    *p += 4;
}
static void putU64(char **p, uint64_t v) {
    memcpy(*p, &v, 8);
    *p += 8;
}
static void putHlc(char **p, const hlc *h) {
    putU64(p, h->pt);
    putU32(p, h->lc);
    putU16(p, h->region);
}
static void putBytes(char **p, const char *s, size_t n) {
    putU32(p, (uint32_t)n);
    if (n) memcpy(*p, s, n);
    *p += n;
}

static size_t encodedSize(const crdtState *s) {
    size_t n = 1 + 1 + 8 + 4 + 2;
    int i;
    if (s->kind == CRDT_KIND_STRING) n += 4 + s->str_len;
    else if (s->kind == CRDT_KIND_COUNTER) n += 2 + (size_t)s->npn * (2 + 8 + 8);
    else if (s->kind == CRDT_KIND_SET) {
        n += 4;
        for (i = 0; i < s->nelems; i++) {
            n += 4 + s->elems[i].member_len;
            n += 4 + (size_t)s->elems[i].nadds * 6;
            n += 4 + (size_t)s->elems[i].nrems * 6;
        }
    } else if (s->kind == CRDT_KIND_HASH) {
        n += 4;
        for (i = 0; i < s->nfields; i++) {
            n += 4 + s->fields[i].field_len;
            n += 4 + s->fields[i].value_len;
            n += 8 + 4 + 2 + 1;
        }
    }
    return n;
}

void crdtFreeBuffer(void *p) {
    free(p);
}

char *crdtEncode(const crdtState *s, size_t *len) {
    size_t cap = encodedSize(s);
    char *buf = xmalloc(cap);
    char *p = buf;
    int i, t;
    putU8(&p, 1);
    putU8(&p, (uint8_t)s->kind);
    putHlc(&p, &s->clock);
    if (s->kind == CRDT_KIND_STRING) putBytes(&p, s->str ? s->str : "", s->str_len);
    else if (s->kind == CRDT_KIND_COUNTER) {
        putU16(&p, (uint16_t)s->npn);
        for (i = 0; i < s->npn; i++) {
            putU16(&p, s->pn[i].region);
            putU64(&p, s->pn[i].p);
            putU64(&p, s->pn[i].n);
        }
    } else if (s->kind == CRDT_KIND_SET) {
        putU32(&p, (uint32_t)s->nelems);
        for (i = 0; i < s->nelems; i++) {
            putBytes(&p, s->elems[i].member, s->elems[i].member_len);
            putU32(&p, (uint32_t)s->elems[i].nadds);
            for (t = 0; t < s->elems[i].nadds; t++) {
                putU16(&p, s->elems[i].adds[t].region);
                putU32(&p, s->elems[i].adds[t].seq);
            }
            putU32(&p, (uint32_t)s->elems[i].nrems);
            for (t = 0; t < s->elems[i].nrems; t++) {
                putU16(&p, s->elems[i].rems[t].region);
                putU32(&p, s->elems[i].rems[t].seq);
            }
        }
    } else if (s->kind == CRDT_KIND_HASH) {
        putU32(&p, (uint32_t)s->nfields);
        for (i = 0; i < s->nfields; i++) {
            putBytes(&p, s->fields[i].field, s->fields[i].field_len);
            putBytes(&p, s->fields[i].value ? s->fields[i].value : "", s->fields[i].deleted ? 0 : s->fields[i].value_len);
            putHlc(&p, &s->fields[i].clock);
            putU8(&p, (uint8_t)s->fields[i].deleted);
        }
    }
    *len = (size_t)(p - buf);
    return buf;
}

static int need(const char *p, const char *end, size_t n) {
    return p + n <= end;
}
static int getU8(const char **p, const char *end, uint8_t *o) {
    if (!need(*p, end, 1)) return -1;
    *o = (uint8_t) * (*p)++;
    return 0;
}
static int getU16(const char **p, const char *end, uint16_t *o) {
    if (!need(*p, end, 2)) return -1;
    memcpy(o, *p, 2);
    *p += 2;
    return 0;
}
static int getU32(const char **p, const char *end, uint32_t *o) {
    if (!need(*p, end, 4)) return -1;
    memcpy(o, *p, 4);
    *p += 4;
    return 0;
}
static int getU64(const char **p, const char *end, uint64_t *o) {
    if (!need(*p, end, 8)) return -1;
    memcpy(o, *p, 8);
    *p += 8;
    return 0;
}
static int getHlc(const char **p, const char *end, hlc *h) {
    if (getU64(p, end, &h->pt) || getU32(p, end, &h->lc) || getU16(p, end, &h->region)) return -1;
    return 0;
}
static int getBytes(const char **p, const char *end, char **out, size_t *n) {
    uint32_t len;
    if (getU32(p, end, &len)) return -1;
    if (!need(*p, end, len)) return -1;
    *out = xdup(*p, len);
    *n = len;
    *p += len;
    return 0;
}

int crdtDecode(crdtState *s, const char *buf, size_t len) {
    const char *p = buf;
    const char *end = buf + len;
    uint8_t ver, kind;
    uint32_t count, i, t, ntags;
    crdtStateInit(s);
    if (getU8(&p, end, &ver) || ver != 1) return -1;
    if (getU8(&p, end, &kind) || getHlc(&p, end, &s->clock)) return -1;
    s->kind = kind;
    if (kind == CRDT_KIND_STRING) s->has_string = 1, s->string_clock = s->clock;
    else if (kind == CRDT_KIND_COUNTER) s->has_counter = 1, s->counter_clock = s->clock;
    else if (kind == CRDT_KIND_SET) s->has_set = 1, s->set_clock = s->clock;
    else if (kind == CRDT_KIND_HASH) s->has_hash = 1, s->hash_clock = s->clock;
    else if (kind == CRDT_KIND_TOMB) s->has_tomb = 1, s->tomb_clock = s->clock;
    if (kind == CRDT_KIND_STRING) {
        if (getBytes(&p, end, &s->str, &s->str_len)) return -1;
    } else if (kind == CRDT_KIND_COUNTER) {
        uint16_t npn;
        if (getU16(&p, end, &npn)) return -1;
        s->pn = npn ? xmalloc(sizeof(crdtPn) * npn) : NULL;
        s->npn = npn;
        for (i = 0; i < npn; i++) {
            if (getU16(&p, end, &s->pn[i].region) || getU64(&p, end, &s->pn[i].p) || getU64(&p, end, &s->pn[i].n)) return -1;
        }
    } else if (kind == CRDT_KIND_SET) {
        if (getU32(&p, end, &count)) return -1;
        s->elems = count ? xmalloc(sizeof(crdtElem) * count) : NULL;
        s->nelems = (int)count;
        for (i = 0; i < count; i++) {
            if (getBytes(&p, end, &s->elems[i].member, &s->elems[i].member_len)) return -1;
            if (getU32(&p, end, &ntags)) return -1;
            s->elems[i].nadds = (int)ntags;
            s->elems[i].adds = ntags ? xmalloc(sizeof(crdtTag) * ntags) : NULL;
            for (t = 0; t < ntags; t++) {
                if (getU16(&p, end, &s->elems[i].adds[t].region) || getU32(&p, end, &s->elems[i].adds[t].seq)) return -1;
            }
            if (getU32(&p, end, &ntags)) return -1;
            s->elems[i].nrems = (int)ntags;
            s->elems[i].rems = ntags ? xmalloc(sizeof(crdtTag) * ntags) : NULL;
            for (t = 0; t < ntags; t++) {
                if (getU16(&p, end, &s->elems[i].rems[t].region) || getU32(&p, end, &s->elems[i].rems[t].seq)) return -1;
            }
        }
    } else if (kind == CRDT_KIND_HASH) {
        if (getU32(&p, end, &count)) return -1;
        s->fields = count ? xmalloc(sizeof(crdtField) * count) : NULL;
        s->nfields = (int)count;
        for (i = 0; i < count; i++) {
            uint8_t del;
            if (getBytes(&p, end, &s->fields[i].field, &s->fields[i].field_len)) return -1;
            if (getBytes(&p, end, &s->fields[i].value, &s->fields[i].value_len)) return -1;
            if (getHlc(&p, end, &s->fields[i].clock) || getU8(&p, end, &del)) return -1;
            s->fields[i].deleted = del;
        }
    } else if (kind != CRDT_KIND_TOMB && kind != CRDT_KIND_NONE) {
        return -1;
    }
    return p == end ? 0 : -1;
}
