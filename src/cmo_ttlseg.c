/*
 * Copyright (c) Valkey Contributors
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */

/* TTL-grouped storage.
 *
 * Keys with an expiry are placed in a segment whose end is the expiry
 * rounded up to a fixed width. One comparison then drops every key in a
 * finished segment, instead of sampling keys one by one. On-access expiry
 * is unchanged: a key read before the segment ends still uses its exact TTL.
 * Segments only change how keys that nobody reads are reclaimed.
 *
 * The bucket math and the table live behind cmoTtlSegs so they can be tested
 * without a server. The server hooks below are no-ops unless
 * cmo-ttl-segments is on. */

#include "server.h"

#include "cmo_ttlseg.h"

#include <string.h>

#define TTL_BUCKETS 1024

typedef struct ttlNode {
    int dbid;
    long long end_ms;
    sds key;
    struct ttlNode *next;
    struct ttlNode *hnext;
} ttlNode;

typedef struct ttlSeg {
    long long end_ms;
    ttlNode *head;
    int count;
    struct ttlSeg *next;
} ttlSeg;

struct cmoTtlSegs {
    long long width_ms;
    int count;
    ttlSeg *segs;
    ttlNode *buckets[TTL_BUCKETS];
};

static cmoTtlSegs *Segs = NULL;
static uint64_t StatReaped = 0;

static unsigned bucket_of(int dbid, const char *key, size_t keylen) {
    unsigned h = 2166136261u ^ (unsigned)dbid;
    size_t i;
    for (i = 0; i < keylen; i++) {
        h ^= (unsigned char)key[i];
        h *= 16777619u;
    }
    return h % TTL_BUCKETS;
}

static long long bucket_end(long long width, long long when) {
    if (when <= 0) return width;
    if (when % width == 0) return when;
    return when - (when % width) + width;
}

static ttlNode *find_node(cmoTtlSegs *t, int dbid, const char *key, size_t keylen, ttlNode ***prev_out) {
    unsigned b = bucket_of(dbid, key, keylen);
    ttlNode **prev = &t->buckets[b];
    ttlNode *n;
    for (n = *prev; n; prev = &n->hnext, n = n->hnext) {
        if (n->dbid == dbid && sdslen(n->key) == keylen && memcmp(n->key, key, keylen) == 0) {
            if (prev_out) *prev_out = prev;
            return n;
        }
    }
    return NULL;
}

static void unlink_node(cmoTtlSegs *t, ttlNode *n) {
    ttlSeg **sp;
    ttlNode **np;
    ttlNode **hprev = NULL;

    find_node(t, n->dbid, n->key, sdslen(n->key), &hprev);
    if (hprev && *hprev == n) *hprev = n->hnext;

    for (sp = &t->segs; *sp; sp = &(*sp)->next) {
        if ((*sp)->end_ms != n->end_ms) continue;
        for (np = &(*sp)->head; *np; np = &(*np)->next) {
            if (*np == n) {
                *np = n->next;
                (*sp)->count--;
                t->count--;
                if ((*sp)->head == NULL) {
                    ttlSeg *dead = *sp;
                    *sp = dead->next;
                    zfree(dead);
                }
                return;
            }
        }
    }
}

cmoTtlSegs *cmoTtlSegsCreate(long long width_ms) {
    cmoTtlSegs *t = zcalloc(sizeof(*t));
    t->width_ms = width_ms > 0 ? width_ms : 1;
    return t;
}

void cmoTtlSegsFree(cmoTtlSegs *t) {
    ttlSeg *s;
    if (!t) return;
    s = t->segs;
    while (s) {
        ttlSeg *next = s->next;
        ttlNode *n = s->head;
        while (n) {
            ttlNode *nn = n->next;
            sdsfree(n->key);
            zfree(n);
            n = nn;
        }
        zfree(s);
        s = next;
    }
    zfree(t);
}

void cmoTtlSegsUntrack(cmoTtlSegs *t, int dbid, const char *key, size_t keylen) {
    ttlNode *n;
    if (!t) return;
    n = find_node(t, dbid, key, keylen, NULL);
    if (!n) return;
    unlink_node(t, n);
    sdsfree(n->key);
    zfree(n);
}

void cmoTtlSegsTrack(cmoTtlSegs *t, int dbid, const char *key, size_t keylen, long long when_ms) {
    long long end;
    ttlSeg **sp;
    ttlSeg *seg;
    ttlNode *n;
    unsigned b;

    if (!t || !key) return;
    cmoTtlSegsUntrack(t, dbid, key, keylen);
    end = bucket_end(t->width_ms, when_ms);
    for (sp = &t->segs; *sp && (*sp)->end_ms < end; sp = &(*sp)->next) {
    }
    if (*sp == NULL || (*sp)->end_ms != end) {
        seg = zcalloc(sizeof(*seg));
        seg->end_ms = end;
        seg->next = *sp;
        *sp = seg;
    } else {
        seg = *sp;
    }
    n = zcalloc(sizeof(*n));
    n->dbid = dbid;
    n->end_ms = end;
    n->key = sdsnewlen(key, keylen);
    n->next = seg->head;
    seg->head = n;
    seg->count++;
    t->count++;
    b = bucket_of(dbid, key, keylen);
    n->hnext = t->buckets[b];
    t->buckets[b] = n;
}

void cmoTtlSegsDropDb(cmoTtlSegs *t, int dbid) {
    ttlSeg *s;
    if (!t) return;
    if (dbid < 0) {
        /* Drop every database by reaping far in the future. */
        cmoTtlSegsReap(t, LLONG_MAX, NULL, NULL);
        return;
    }
    s = t->segs;
    while (s) {
        ttlNode *n = s->head;
        ttlSeg *next_seg = s->next;
        while (n) {
            ttlNode *nn = n->next;
            if (n->dbid == dbid) {
                unlink_node(t, n);
                sdsfree(n->key);
                zfree(n);
            }
            n = nn;
        }
        s = next_seg;
    }
}

int cmoTtlSegsReap(cmoTtlSegs *t, long long now_ms, cmoTtlDueFn fn, void *userdata) {
    int nkeys = 0;
    if (!t) return 0;
    while (t->segs && t->segs->end_ms <= now_ms) {
        ttlSeg *s = t->segs;
        t->segs = s->next;
        while (s->head) {
            ttlNode *n = s->head;
            ttlNode **hprev = NULL;
            s->head = n->next;
            s->count--;
            t->count--;
            find_node(t, n->dbid, n->key, sdslen(n->key), &hprev);
            if (hprev && *hprev == n) *hprev = n->hnext;
            nkeys++;
            if (fn) fn(n->dbid, n->key, sdslen(n->key), userdata);
            sdsfree(n->key);
            zfree(n);
        }
        zfree(s);
    }
    return nkeys;
}

int cmoTtlSegsCount(const cmoTtlSegs *t) {
    return t ? t->count : 0;
}

static void ensure_segs(void) {
    if (!Segs) Segs = cmoTtlSegsCreate(server.cmo_ttl_segment_ms);
}

static void reap_one(int dbid, const char *key, size_t keylen, void *userdata) {
    serverDb *db;
    robj *kobj;
    int idx;
    UNUSED(userdata);
    if (dbid < 0 || dbid >= server.dbnum) return;
    db = server.db[dbid];
    if (!db) return;
    kobj = createStringObject(key, keylen);
    idx = getKVStoreIndexForKey(objectGetVal(kobj));
    if (dbFind(db, objectGetVal(kobj)) != NULL) {
        deleteExpiredKeyAndPropagateWithDictIndex(db, kobj, idx);
        StatReaped++;
    }
    decrRefCount(kobj);
}

void cmoTtlSegOnExpire(serverDb *db, robj *key, long long when_ms) {
    sds k;
    if (!server.cmo_ttl_segments || !key) return;
    ensure_segs();
    k = objectGetVal(key);
    cmoTtlSegsTrack(Segs, db->id, k, sdslen(k), when_ms);
}

void cmoTtlSegOnUnexpire(serverDb *db, robj *key) {
    sds k;
    if (!Segs || !key) return;
    k = objectGetVal(key);
    cmoTtlSegsUntrack(Segs, db->id, k, sdslen(k));
}

void cmoTtlSegOnFlush(int dbnum) {
    if (!Segs) return;
    cmoTtlSegsDropDb(Segs, dbnum);
}

void cmoTtlSegCron(void) {
    if (!server.cmo_ttl_segments || !Segs) return;
    cmoTtlSegsReap(Segs, server.mstime, reap_one, NULL);
}

sds cmoTtlSegCatInfo(sds info) {
    return sdscatprintf(info,
                        "cmo_ttl_segments:%d\r\n"
                        "cmo_ttl_segment_ms:%lld\r\n"
                        "cmo_ttl_tracked_keys:%d\r\n"
                        "cmo_ttl_reaped_keys:%llu\r\n",
                        server.cmo_ttl_segments, server.cmo_ttl_segment_ms, cmoTtlSegsCount(Segs),
                        (unsigned long long)StatReaped);
}
