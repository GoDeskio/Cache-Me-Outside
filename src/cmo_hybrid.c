/*
 * Copyright (c) Valkey Contributors
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */

/* Hybrid DRAM + flash storage for large string values.
 *
 * Small values stay in the keyspace. A string at least cmo-hybrid-min-value
 * bytes is copied into an append-only flash log and, once nothing else holds
 * the object, the keyspace value is replaced by a 12-byte locator. The DRAM
 * index is the authority for which keys are spilled: the locator is only a
 * marker so readers can tell a spilled value from a short user string.
 * Lookup promotes the value back into DRAM. The flash file is rebuilt on
 * process start; durability stays with RDB and AOF, which write the real
 * bytes rather than the locator.
 *
 * Spill runs only when the database object has refcount 1. SET keeps that
 * object in the client's argv until the command has been propagated, so the
 * replica and the AOF see the original value. */

#include "server.h"

#include "bgiteration.h"
#include "cmo_hybrid.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define CMO_HYBRID_MAGIC "CMOHYB01"
#define CMO_HYBRID_HDR 64
#define CMO_REC_MAGIC 0x31425948u
#define CMO_LOCATOR "CMOHYBL1"
#define CMO_LOCATOR_LEN 12 /* 8 byte magic + native dbid */
#define CMO_REC_HDR 24

#define ENT_EMPTY 0
#define ENT_LIVE 1
#define ENT_TOMB 2

typedef struct cmoHEnt {
    uint64_t hash;
    uint64_t offset;
    uint32_t keylen;
    uint32_t vallen;
    uint32_t crc;
    uint32_t rec_bytes;
    int dbid;
    int state;
    char *key;
} cmoHEnt;

struct cmoHybridStore {
    char *path;
    int fd;
    size_t max_bytes;
    uint64_t write_off;
    uint64_t live_bytes;
    uint64_t dead_bytes;
    uint64_t compactions;
    size_t live_keys;
    size_t tombs;
    size_t cap;
    cmoHEnt *slots;
};

typedef struct cmoPend {
    int dbid;
    int tries;
    sds key;
    struct cmoPend *next;
} cmoPend;

static cmoHybridStore *Store = NULL;
static cmoPend *Pending = NULL;
static int PendingCount = 0;

static uint64_t StatSpills = 0;
static uint64_t StatPromotions = 0;
static uint64_t StatSkippedFull = 0;
static uint64_t StatReadErrors = 0;

static uint64_t align8(uint64_t n) {
    return (n + 7u) & ~7u;
}

static void ensure_crc(void) {
    static int ready = 0;
    if (!ready) {
        crc64_init();
        ready = 1;
    }
}

static uint64_t key_hash(int dbid, const char *key, size_t keylen) {
    uint64_t h = crc64(0, (const unsigned char *)key, keylen);
    h ^= (uint64_t)(uint32_t)dbid * 0x9E3779B97F4A7C15ULL;
    return h ? h : 1;
}

static int pread_full(int fd, void *buf, size_t n, uint64_t off) {
    unsigned char *p = buf;
    while (n) {
        ssize_t r = pread(fd, p, n, (off_t)off);
        if (r < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (r == 0) return -1;
        p += r;
        n -= (size_t)r;
        off += (uint64_t)r;
    }
    return 0;
}

static int pwrite_full(int fd, const void *buf, size_t n, uint64_t off) {
    const unsigned char *p = buf;
    while (n) {
        ssize_t r = pwrite(fd, p, n, (off_t)off);
        if (r < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (r == 0) return -1;
        p += r;
        n -= (size_t)r;
        off += (uint64_t)r;
    }
    return 0;
}

static int write_file_header(int fd, uint64_t write_off) {
    unsigned char hdr[CMO_HYBRID_HDR];
    memset(hdr, 0, sizeof(hdr));
    memcpy(hdr, CMO_HYBRID_MAGIC, 8);
    hdr[8] = 1; /* version */
    memcpy(hdr + 16, &write_off, sizeof(write_off));
    return pwrite_full(fd, hdr, sizeof(hdr), 0);
}

static int find_slot(cmoHybridStore *st, uint64_t hash, int dbid, const char *key, size_t keylen, int *found) {
    size_t mask = st->cap - 1;
    size_t i = (size_t)hash & mask;
    size_t first_tomb = (size_t)-1;
    size_t n;

    *found = 0;
    for (n = 0; n < st->cap; n++) {
        cmoHEnt *e = &st->slots[i];
        if (e->state == ENT_EMPTY) {
            return first_tomb != (size_t)-1 ? (int)first_tomb : (int)i;
        }
        if (e->state == ENT_TOMB) {
            if (first_tomb == (size_t)-1) first_tomb = i;
        } else if (e->hash == hash && e->dbid == dbid && e->keylen == keylen && memcmp(e->key, key, keylen) == 0) {
            *found = 1;
            return (int)i;
        }
        i = (i + 1) & mask;
    }
    return first_tomb != (size_t)-1 ? (int)first_tomb : -1;
}

static int grow(cmoHybridStore *st) {
    size_t ncap = st->cap * 2;
    cmoHEnt *nslots = zcalloc(ncap * sizeof(cmoHEnt));
    cmoHEnt *old = st->slots;
    size_t ocap = st->cap;
    size_t i;

    st->slots = nslots;
    st->cap = ncap;
    st->tombs = 0;
    for (i = 0; i < ocap; i++) {
        int found, slot;
        if (old[i].state != ENT_LIVE) continue;
        slot = find_slot(st, old[i].hash, old[i].dbid, old[i].key, old[i].keylen, &found);
        if (slot < 0) {
            zfree(nslots);
            st->slots = old;
            st->cap = ocap;
            return -1;
        }
        st->slots[slot] = old[i];
    }
    zfree(old);
    return 0;
}

static int read_record(cmoHybridStore *st, const cmoHEnt *e, char **out, size_t *outlen) {
    unsigned char hdr[CMO_REC_HDR];
    uint32_t magic, dbid, keylen, vallen, crc, pad;
    char *keybuf = NULL;
    char *val = NULL;
    uint32_t got;

    if (pread_full(st->fd, hdr, sizeof(hdr), e->offset) != 0) return -1;
    memcpy(&magic, hdr, 4);
    memcpy(&dbid, hdr + 4, 4);
    memcpy(&keylen, hdr + 8, 4);
    memcpy(&vallen, hdr + 12, 4);
    memcpy(&crc, hdr + 16, 4);
    memcpy(&pad, hdr + 20, 4);
    (void)pad;
    if (magic != CMO_REC_MAGIC || dbid != (uint32_t)e->dbid || keylen != e->keylen || vallen != e->vallen) return -1;
    keybuf = zmalloc(keylen ? keylen : 1);
    if (keylen && pread_full(st->fd, keybuf, keylen, e->offset + CMO_REC_HDR) != 0) {
        zfree(keybuf);
        return -1;
    }
    if (keylen && memcmp(keybuf, e->key, keylen) != 0) {
        zfree(keybuf);
        return -1;
    }
    zfree(keybuf);
    val = zmalloc(vallen ? vallen : 1);
    if (vallen && pread_full(st->fd, val, vallen, e->offset + CMO_REC_HDR + keylen) != 0) {
        zfree(val);
        return -1;
    }
    got = (uint32_t)crc64(0, (const unsigned char *)val, vallen);
    if (got != crc) {
        zfree(val);
        return -1;
    }
    *out = val;
    *outlen = vallen;
    return 0;
}

static int compact_store(cmoHybridStore *st) {
    sds tmp;
    int fd;
    uint64_t off = CMO_HYBRID_HDR;
    uint64_t *saved_off = NULL;
    size_t i;

    if (st->dead_bytes == 0) return 0;
    saved_off = zmalloc(st->cap * sizeof(*saved_off));
    for (i = 0; i < st->cap; i++) saved_off[i] = st->slots[i].offset;
    tmp = sdscat(sdsnew(st->path), ".tmp");
    fd = open(tmp, O_CREAT | O_TRUNC | O_RDWR | O_CLOEXEC, 0644);
    if (fd < 0) {
        zfree(saved_off);
        sdsfree(tmp);
        return -1;
    }
    if (write_file_header(fd, CMO_HYBRID_HDR) != 0) {
        zfree(saved_off);
        close(fd);
        unlink(tmp);
        sdsfree(tmp);
        return -1;
    }
    for (i = 0; i < st->cap; i++) {
        cmoHEnt *e = &st->slots[i];
        unsigned char hdr[CMO_REC_HDR];
        char *val = NULL;
        size_t vallen = 0;
        uint32_t magic = CMO_REC_MAGIC;
        uint32_t dbid, keylen, crc, zero = 0;
        uint32_t rec;

        if (e->state != ENT_LIVE) continue;
        if (read_record(st, e, &val, &vallen) != 0) {
            for (i = 0; i < st->cap; i++) st->slots[i].offset = saved_off[i];
            zfree(saved_off);
            close(fd);
            unlink(tmp);
            sdsfree(tmp);
            return -1;
        }
        memset(hdr, 0, sizeof(hdr));
        dbid = (uint32_t)e->dbid;
        keylen = e->keylen;
        crc = e->crc;
        memcpy(hdr, &magic, 4);
        memcpy(hdr + 4, &dbid, 4);
        memcpy(hdr + 8, &keylen, 4);
        memcpy(hdr + 12, &e->vallen, 4);
        memcpy(hdr + 16, &crc, 4);
        memcpy(hdr + 20, &zero, 4);
        rec = (uint32_t)align8(CMO_REC_HDR + e->keylen + e->vallen);
        if (pwrite_full(fd, hdr, sizeof(hdr), off) != 0 ||
            (e->keylen && pwrite_full(fd, e->key, e->keylen, off + CMO_REC_HDR) != 0) ||
            (vallen && pwrite_full(fd, val, vallen, off + CMO_REC_HDR + e->keylen) != 0)) {
            zfree(val);
            for (i = 0; i < st->cap; i++) st->slots[i].offset = saved_off[i];
            zfree(saved_off);
            close(fd);
            unlink(tmp);
            sdsfree(tmp);
            return -1;
        }
        zfree(val);
        e->offset = off;
        e->rec_bytes = rec;
        off += rec;
    }
    if (write_file_header(fd, off) != 0 || fsync(fd) != 0) {
        for (i = 0; i < st->cap; i++) st->slots[i].offset = saved_off[i];
        zfree(saved_off);
        close(fd);
        unlink(tmp);
        sdsfree(tmp);
        return -1;
    }
    close(st->fd);
    close(fd);
    if (rename(tmp, st->path) != 0) {
        for (i = 0; i < st->cap; i++) st->slots[i].offset = saved_off[i];
        zfree(saved_off);
        sdsfree(tmp);
        st->fd = open(st->path, O_RDWR | O_CLOEXEC);
        return -1;
    }
    zfree(saved_off);
    sdsfree(tmp);
    st->fd = open(st->path, O_RDWR | O_CLOEXEC);
    if (st->fd < 0) return -1;
    st->write_off = off;
    st->dead_bytes = 0;
    st->live_bytes = off - CMO_HYBRID_HDR;
    st->compactions++;
    return 0;
}

cmoHybridStore *cmoHybridStoreCreate(const char *path, size_t max_bytes) {
    cmoHybridStore *st;
    int fd;

    ensure_crc();
    if (!path || !path[0] || max_bytes < CMO_HYBRID_HDR + 64) return NULL;
    fd = open(path, O_CREAT | O_TRUNC | O_RDWR | O_CLOEXEC, 0644);
    if (fd < 0) return NULL;
    if (write_file_header(fd, CMO_HYBRID_HDR) != 0) {
        close(fd);
        return NULL;
    }
    st = zcalloc(sizeof(*st));
    st->path = zstrdup(path);
    st->fd = fd;
    st->max_bytes = max_bytes;
    st->write_off = CMO_HYBRID_HDR;
    st->cap = 1024;
    st->slots = zcalloc(st->cap * sizeof(cmoHEnt));
    return st;
}

void cmoHybridStoreFree(cmoHybridStore *st) {
    size_t i;
    if (!st) return;
    if (st->fd >= 0) {
        fsync(st->fd);
        close(st->fd);
    }
    for (i = 0; i < st->cap; i++) {
        if (st->slots[i].state == ENT_LIVE) zfree(st->slots[i].key);
    }
    zfree(st->slots);
    zfree(st->path);
    zfree(st);
}

static int insert_entry(cmoHybridStore *st, uint64_t hash, int dbid, const char *key, size_t keylen, uint64_t offset, uint32_t vallen, uint32_t crc, uint32_t rec_bytes) {
    int found, slot;
    cmoHEnt *e;

    if ((st->live_keys + st->tombs + 1) * 10 >= st->cap * 7) {
        if (grow(st) != 0) return -1;
    }
    slot = find_slot(st, hash, dbid, key, keylen, &found);
    if (slot < 0) return -1;
    e = &st->slots[slot];
    if (found) {
        st->dead_bytes += e->rec_bytes;
        st->live_bytes -= e->rec_bytes;
        zfree(e->key);
        st->live_keys--;
    } else if (e->state == ENT_TOMB) {
        st->tombs--;
    }
    e->hash = hash;
    e->offset = offset;
    e->keylen = (uint32_t)keylen;
    e->vallen = vallen;
    e->crc = crc;
    e->rec_bytes = rec_bytes;
    e->dbid = dbid;
    e->state = ENT_LIVE;
    e->key = zmalloc(keylen ? keylen : 1);
    if (keylen) memcpy(e->key, key, keylen);
    st->live_keys++;
    st->live_bytes += rec_bytes;
    return 0;
}

int cmoHybridStorePut(cmoHybridStore *st, int dbid, const char *key, size_t keylen, const char *val, size_t vallen) {
    uint64_t need, hash;
    uint32_t crc, magic, dbid32, keylen32, vallen32, zero;
    unsigned char hdr[CMO_REC_HDR];
    int found;

    if (!st || keylen > UINT32_MAX || vallen > UINT32_MAX) return -1;
    ensure_crc();
    hash = key_hash(dbid, key, keylen);
    find_slot(st, hash, dbid, key, keylen, &found);
    if (found) cmoHybridStoreDel(st, dbid, key, keylen);
    need = align8(CMO_REC_HDR + keylen + vallen);
    if (st->write_off + need > st->max_bytes) {
        if (compact_store(st) != 0 || st->write_off + need > st->max_bytes) return -1;
    }
    crc = (uint32_t)crc64(0, (const unsigned char *)val, vallen);
    magic = CMO_REC_MAGIC;
    dbid32 = (uint32_t)dbid;
    keylen32 = (uint32_t)keylen;
    vallen32 = (uint32_t)vallen;
    zero = 0;
    memset(hdr, 0, sizeof(hdr));
    memcpy(hdr, &magic, 4);
    memcpy(hdr + 4, &dbid32, 4);
    memcpy(hdr + 8, &keylen32, 4);
    memcpy(hdr + 12, &vallen32, 4);
    memcpy(hdr + 16, &crc, 4);
    memcpy(hdr + 20, &zero, 4);
    if (pwrite_full(st->fd, hdr, sizeof(hdr), st->write_off) != 0) return -1;
    if (keylen && pwrite_full(st->fd, key, keylen, st->write_off + CMO_REC_HDR) != 0) return -1;
    if (vallen && pwrite_full(st->fd, val, vallen, st->write_off + CMO_REC_HDR + keylen) != 0) return -1;
    if (insert_entry(st, hash, dbid, key, keylen, st->write_off, vallen32, crc, (uint32_t)need) != 0) return -1;
    st->write_off += need;
    write_file_header(st->fd, st->write_off);
    return 0;
}

int cmoHybridStoreGet(cmoHybridStore *st, int dbid, const char *key, size_t keylen, char **out, size_t *outlen) {
    uint64_t hash;
    int found, slot;

    if (!st) return -1;
    ensure_crc();
    hash = key_hash(dbid, key, keylen);
    slot = find_slot(st, hash, dbid, key, keylen, &found);
    if (!found || slot < 0) return -1;
    if (read_record(st, &st->slots[slot], out, outlen) != 0) return -1;
    return 0;
}

int cmoHybridStoreDel(cmoHybridStore *st, int dbid, const char *key, size_t keylen) {
    uint64_t hash;
    int found, slot;
    cmoHEnt *e;

    if (!st) return -1;
    hash = key_hash(dbid, key, keylen);
    slot = find_slot(st, hash, dbid, key, keylen, &found);
    if (!found || slot < 0) return -1;
    e = &st->slots[slot];
    st->dead_bytes += e->rec_bytes;
    if (st->live_bytes >= e->rec_bytes)
        st->live_bytes -= e->rec_bytes;
    else
        st->live_bytes = 0;
    st->live_keys--;
    st->tombs++;
    zfree(e->key);
    e->key = NULL;
    e->state = ENT_TOMB;
    return 0;
}

void cmoHybridStoreDelDb(cmoHybridStore *st, int dbid) {
    size_t i;
    if (!st) return;
    for (i = 0; i < st->cap; i++) {
        cmoHEnt *e = &st->slots[i];
        if (e->state == ENT_LIVE && e->dbid == dbid) cmoHybridStoreDel(st, dbid, e->key, e->keylen);
    }
}

uint64_t cmoHybridStoreLiveBytes(const cmoHybridStore *st) {
    return st ? st->live_bytes : 0;
}
uint64_t cmoHybridStoreFileBytes(const cmoHybridStore *st) {
    return st ? st->write_off : 0;
}
size_t cmoHybridStoreLiveKeys(const cmoHybridStore *st) {
    return st ? st->live_keys : 0;
}
uint64_t cmoHybridStoreCompactions(const cmoHybridStore *st) {
    return st ? st->compactions : 0;
}

/* --- server integration -------------------------------------------------- */

static int locator_dbid(const robj *obj, uint32_t *dbid) {
    sds v;
    if (!obj || objectGetType(obj) != OBJ_STRING || !obj->hasembkey) return 0;
    if (!sdsEncodedObject(obj)) return 0;
    v = objectGetVal(obj);
    if (sdslen(v) != CMO_LOCATOR_LEN || memcmp(v, CMO_LOCATOR, 8) != 0) return 0;
    memcpy(dbid, v + 8, sizeof(*dbid));
    return 1;
}

static int looks_like_locator(const robj *obj) {
    uint32_t dbid;
    return locator_dbid(obj, &dbid);
}

int cmoHybridIsSpilled(const robj *obj) {
    sds key;
    uint32_t dbid;
    uint64_t hash;
    int found, slot;
    if (!Store || !server.cmo_hybrid_enabled || !locator_dbid(obj, &dbid)) return 0;
    if ((int)dbid >= server.dbnum) return 0;
    key = objectGetKey(obj);
    hash = key_hash((int)dbid, key, sdslen(key));
    slot = find_slot(Store, hash, (int)dbid, key, sdslen(key), &found);
    return found && slot >= 0;
}

sds cmoHybridMaterialize(const robj *obj) {
    sds key;
    uint32_t dbid;
    char *buf = NULL;
    size_t len = 0;
    sds out;

    if (!cmoHybridIsSpilled(obj)) return NULL;
    key = objectGetKey(obj);
    memcpy(&dbid, ((sds)objectGetVal(obj)) + 8, sizeof(dbid));
    if (cmoHybridStoreGet(Store, (int)dbid, key, sdslen(key), &buf, &len) != 0) {
        StatReadErrors++;
        return NULL;
    }
    out = sdsnewlen(buf, len);
    zfree(buf);
    return out;
}

static robj *swap_value(serverDb *db, robj *old, robj *neu) {
    sds keycopy;
    long long exp;
    int idx;
    void **ref;
    unsigned int lru;

    keycopy = sdsdup(objectGetKey(old));
    exp = objectGetExpire(old);
    lru = objectGetLRU(old);
    idx = getKVStoreIndexForKey(keycopy);
    ref = kvstoreHashtableFindRef(db->keys, idx, keycopy);
    if (!ref || *ref != old) {
        sdsfree(keycopy);
        return NULL;
    }
    objectSetLRU(neu, lru);
    /* objectSetKeyAndExpire consumes neu and returns the embedded-key object.
     * Point the dictionaries at that object before releasing the previous one,
     * which is the dictionary's only reference. */
    neu = objectSetKeyAndExpire(neu, keycopy, exp);
    *ref = neu;
    if (exp != EXPIRY_NONE) {
        void **eref = kvstoreHashtableFindRef(db->expires, idx, keycopy);
        if (eref) *eref = neu;
    }
    bgIteration_updateDbEntryPtr(old, neu);
    decrRefCount(old);
    sdsfree(keycopy);
    return neu;
}

robj *cmoHybridPromote(serverDb *db, robj *key, robj *val) {
    sds real;
    robj *neu, *installed;
    UNUSED(key);
    if (!cmoHybridIsSpilled(val)) return val;
    real = cmoHybridMaterialize(val);
    if (!real) return val;
    neu = createStringObject(real, sdslen(real));
    sdsfree(real);
    installed = swap_value(db, val, neu);
    if (!installed) {
        decrRefCount(neu);
        return val;
    }
    cmoHybridStoreDel(Store, db->id, objectGetKey(installed), sdslen(objectGetKey(installed)));
    StatPromotions++;
    return installed;
}

static void note_pending(serverDb *db, sds key) {
    cmoPend *p;
    if (PendingCount > 100000) return;
    p = zmalloc(sizeof(*p));
    p->dbid = db->id;
    p->tries = 0;
    p->key = sdsdup(key);
    p->next = Pending;
    Pending = p;
    PendingCount++;
}

void cmoHybridObserveWrite(serverDb *db, robj *key, robj *val) {
    sds k;
    size_t len;
    if (!server.cmo_hybrid_enabled || !Store || server.loading) return;
    k = objectGetVal(key);
    cmoHybridStoreDel(Store, db->id, k, sdslen(k));
    if (!val || objectGetType(val) != OBJ_STRING || !sdsEncodedObject(val)) return;
    if (looks_like_locator(val)) return;
    len = sdslen((sds)objectGetVal(val));
    if (len < server.cmo_hybrid_min_value) return;
    note_pending(db, k);
}

void cmoHybridForgetObject(serverDb *db, robj *key) {
    sds k;
    if (!server.cmo_hybrid_enabled || !Store) return;
    k = objectGetVal(key);
    cmoHybridStoreDel(Store, db->id, k, sdslen(k));
}

void cmoHybridForgetDb(int dbnum) {
    int i;
    if (!Store) return;
    if (dbnum < 0) {
        for (i = 0; i < server.dbnum; i++) cmoHybridStoreDelDb(Store, i);
    } else {
        cmoHybridStoreDelDb(Store, dbnum);
    }
}

static int try_spill(cmoPend *p) {
    serverDb *db;
    robj *val, *neu, *installed;
    sds v;
    size_t len;

    if (p->dbid < 0 || p->dbid >= server.dbnum) return 1;
    db = server.db[p->dbid];
    if (!db) return 1;
    val = dbFind(db, p->key);
    if (!val) return 1;
    if (objectGetType(val) != OBJ_STRING || !sdsEncodedObject(val)) return 1;
    if (looks_like_locator(val)) return 1;
    v = objectGetVal(val);
    len = sdslen(v);
    if (len < server.cmo_hybrid_min_value) return 1;
    if (objectGetRefcount(val) != 1) return 0;
    if (cmoHybridStorePut(Store, db->id, p->key, sdslen(p->key), v, len) != 0) {
        StatSkippedFull++;
        return 1;
    }
    {
        char loc[CMO_LOCATOR_LEN];
        uint32_t dbid = (uint32_t)db->id;
        memcpy(loc, CMO_LOCATOR, 8);
        memcpy(loc + 8, &dbid, sizeof(dbid));
        neu = createStringObject(loc, CMO_LOCATOR_LEN);
    }
    installed = swap_value(db, val, neu);
    if (!installed) {
        decrRefCount(neu);
        cmoHybridStoreDel(Store, db->id, p->key, sdslen(p->key));
        return 1;
    }
    StatSpills++;
    return 1;
}

void cmoHybridDrainPending(void) {
    cmoPend **pp;
    cmoPend *tail;
    int steps = 0;

    if (!server.cmo_hybrid_enabled || !Store || server.loading) return;
    pp = &Pending;
    while (*pp && steps < 64) {
        cmoPend *p = *pp;
        int drop;
        steps++;
        p->tries++;
        drop = try_spill(p);
        if (!drop && p->tries < 100) {
            /* A client still holds the value. Park it at the tail. */
            *pp = p->next;
            p->next = NULL;
            if (Pending == NULL) {
                Pending = p;
            } else {
                tail = Pending;
                while (tail->next) tail = tail->next;
                if (tail != p) tail->next = p;
            }
            continue;
        }
        *pp = p->next;
        sdsfree(p->key);
        zfree(p);
        PendingCount--;
    }
}

void cmoHybridOpen(void) {
    if (Store) return;
    if (!server.cmo_hybrid_enabled) return;
    if (!server.cmo_hybrid_file || !server.cmo_hybrid_file[0]) {
        serverLog(LL_WARNING, "cmo-hybrid-enabled requires cmo-hybrid-file; hybrid storage disabled");
        server.cmo_hybrid_enabled = 0;
        return;
    }
    Store = cmoHybridStoreCreate(server.cmo_hybrid_file, server.cmo_hybrid_max_bytes);
    if (!Store) {
        serverLog(LL_WARNING, "Cannot open hybrid flash file %s: %s. Hybrid storage disabled.", server.cmo_hybrid_file,
                  strerror(errno));
        server.cmo_hybrid_enabled = 0;
    } else {
        serverLog(LL_NOTICE, "Hybrid flash log %s (min value %zu, cap %zu)", server.cmo_hybrid_file,
                  server.cmo_hybrid_min_value, server.cmo_hybrid_max_bytes);
    }
}

void cmoHybridClose(void) {
    cmoPend *p;
    cmoHybridStoreFree(Store);
    Store = NULL;
    while ((p = Pending)) {
        Pending = p->next;
        sdsfree(p->key);
        zfree(p);
    }
    PendingCount = 0;
}

sds cmoHybridCatInfo(sds info) {
    info = sdscatprintf(info,
                        "cmo_hybrid_enabled:%d\r\n"
                        "cmo_hybrid_spilled_keys:%zu\r\n"
                        "cmo_hybrid_live_bytes:%llu\r\n"
                        "cmo_hybrid_file_bytes:%llu\r\n"
                        "cmo_hybrid_spills:%llu\r\n"
                        "cmo_hybrid_promotions:%llu\r\n"
                        "cmo_hybrid_spill_skipped_full:%llu\r\n"
                        "cmo_hybrid_read_errors:%llu\r\n"
                        "cmo_hybrid_compactions:%llu\r\n"
                        "cmo_hybrid_min_value:%zu\r\n",
                        server.cmo_hybrid_enabled, cmoHybridStoreLiveKeys(Store),
                        (unsigned long long)cmoHybridStoreLiveBytes(Store),
                        (unsigned long long)cmoHybridStoreFileBytes(Store), (unsigned long long)StatSpills,
                        (unsigned long long)StatPromotions, (unsigned long long)StatSkippedFull,
                        (unsigned long long)StatReadErrors, (unsigned long long)cmoHybridStoreCompactions(Store),
                        server.cmo_hybrid_min_value);
    return info;
}
