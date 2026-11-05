/* Incremental RDB snapshot on the main thread.
 *
 * The snapshot is consistent with the moment it starts. Keys are copied into
 * the temp file a slice at a time. The first time a not-yet-saved key is
 * written or deleted, its pre-image is appended immediately (key-level
 * copy-on-write) and the live mutation proceeds. The previous dump.rdb is
 * replaced only by rename(2) after the footer and checksum are durable, so a
 * crash mid-snapshot leaves the last good file in place.
 *
 * This is not the background-thread forkless saver and does not use fork().
 *
 * Copyright (c) 2026, Cache Me Outside contributors.
 * Licensed under the BSD 3-Clause License, the same terms as the server.
 */
#include "server.h"
#include "rdb.h"
#include "rdb_forkless.h"
#include "forkless.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

extern int clusterRDBSaveSlotImports(rio *rdb, int rdbver);

typedef struct snapKey {
    int dbid;
    sds key;
} snapKey;

static int active = 0;
static int in_save = 0;
static FILE *fp = NULL;
static rio rdb;
static char temp_path[256];
static char finalfile[256];
static int last_dbid = -1;
static hashtable *pending = NULL;
static long long cow_keys = 0;
static long long slice_us_max = 0;
static long long dirty_before = 0;

static const void *snapEntryKey(const void *entry) {
    return entry;
}

static uint64_t snapHash(const void *key) {
    const snapKey *s = key;
    return dictSdsHash(s->key) ^ ((uint64_t)s->dbid * 0x9E3779B97F4A7C15ULL);
}

/* Hashtable compare returns non-zero when the keys are equal. */
static int snapCompare(const void *a, const void *b) {
    const snapKey *sa = a;
    const snapKey *sb = b;
    if (sa->dbid != sb->dbid) return 0;
    if (sdslen(sa->key) != sdslen(sb->key)) return 0;
    return memcmp(sa->key, sb->key, sdslen(sa->key)) == 0;
}

static void snapDestructor(void *entry) {
    snapKey *s = entry;
    sdsfree(s->key);
    zfree(s);
}

static hashtableType snapType = {
    .entryGetKey = snapEntryKey,
    .hashFunction = snapHash,
    .keyCompare = snapCompare,
    .entryDestructor = snapDestructor,
};

static void snapshotReset(void) {
    active = 0;
    in_save = 0;
    if (fp) {
        fclose(fp);
        fp = NULL;
    }
    if (temp_path[0]) {
        unlink(temp_path);
        temp_path[0] = '\0';
    }
    if (pending) {
        hashtableRelease(pending);
        pending = NULL;
    }
    last_dbid = -1;
    memset(&rdb, 0, sizeof(rdb));
}

static int snapshotWriteKey(int dbid, sds keystr) {
    serverDb *db;
    robj *val;
    robj keyobj;
    long long expire;

    if (dbid < 0 || dbid >= server.dbnum) return C_OK;
    db = server.db[dbid];
    val = db ? dbFind(db, keystr) : NULL;
    /* Deleted without a pre-image. The delete hook writes the pre-image
     * first, so this is only a missing key that was never present. */
    if (!val) return C_OK;

    if (last_dbid != dbid) {
        if (rdbSaveType(&rdb, RDB_OPCODE_SELECTDB) == -1) return C_ERR;
        if (rdbSaveLen(&rdb, dbid) == -1) return C_ERR;
        last_dbid = dbid;
    }
    initStaticStringObject(keyobj, keystr);
    expire = objectGetExpire(val);
    if (rdbSaveKeyValuePair(&rdb, &keyobj, val, expire, dbid, RDB_VERSION) == -1) return C_ERR;
    return C_OK;
}

static int snapshotPopOne(void) {
    void *found = NULL;
    snapKey *owned;
    sds keycopy;
    int dbid;
    int rc;

    if (!hashtableRandomEntry(pending, &found)) return C_OK;
    owned = found;
    keycopy = sdsdup(owned->key);
    dbid = owned->dbid;
    hashtableDelete(pending, owned);
    in_save = 1;
    rc = snapshotWriteKey(dbid, keycopy);
    in_save = 0;
    sdsfree(keycopy);
    return rc;
}

static int snapshotAddPending(int dbid, sds key) {
    snapKey *s = zcalloc(sizeof(*s));
    s->dbid = dbid;
    s->key = sdsdup(key);
    if (!hashtableAdd(pending, s)) {
        snapDestructor(s);
        return C_ERR;
    }
    return C_OK;
}

static int snapshotBuildPending(void) {
    int dbid;
    pending = hashtableCreate(&snapType);
    if (!pending) return C_ERR;
    for (dbid = 0; dbid < server.dbnum; dbid++) {
        serverDb *db = server.db[dbid];
        kvstoreIterator *it;
        void *next;
        if (!db || kvstoreSize(db->keys) == 0) continue;
        it = kvstoreIteratorInit(db->keys, HASHTABLE_ITER_SAFE);
        while (kvstoreIteratorNext(it, &next)) {
            robj *o = next;
            if (snapshotAddPending(dbid, objectGetKey(o)) != C_OK) {
                kvstoreIteratorRelease(it);
                return C_ERR;
            }
        }
        kvstoreIteratorRelease(it);
    }
    return C_OK;
}

int snapshotForklessInProgress(void) {
    return active;
}

long long snapshotForklessKeysRemaining(void) {
    if (!active || !pending) return 0;
    return (long long)hashtableSize(pending);
}

long long snapshotForklessCowKeys(void) {
    return cow_keys;
}

long long snapshotForklessSliceUsMax(void) {
    return slice_us_max;
}

void snapshotForklessBeforeWrite(serverDb *db, robj *key) {
    snapKey probe;
    void *found = NULL;
    snapKey *owned;
    sds keycopy;
    int dbid;
    int rc;

    if (!active || in_save || !db || !key || !pending) return;
    probe.dbid = db->id;
    probe.key = objectGetVal(key);
    if (!probe.key) return;
    if (!hashtableFind(pending, &probe, &found)) return;

    owned = found;
    keycopy = sdsdup(owned->key);
    dbid = owned->dbid;
    hashtableDelete(pending, owned);
    cow_keys++;
    in_save = 1;
    rc = snapshotWriteKey(dbid, keycopy);
    in_save = 0;
    sdsfree(keycopy);
    if (rc != C_OK) {
        serverLog(LL_WARNING, "Forkless snapshot failed while copying a key pre-image");
        snapshotForklessCancel();
    }
}

int snapshotForklessStart(const char *filename) {
    rdbSaveInfo rsi, *rsiptr;

    if (active || isForkBgsaveInProgress() || isForklessSaveInProgress()) return C_ERR;
    if (!filename) return C_ERR;

    snprintf(temp_path, sizeof(temp_path), "temp-forkless-%d.rdb", (int)getpid());
    snprintf(finalfile, sizeof(finalfile), "%s", filename);
    fp = fopen(temp_path, "w");
    if (!fp) {
        serverLog(LL_WARNING, "Forkless snapshot failed to open %s: %s", temp_path, strerror(errno));
        temp_path[0] = '\0';
        return C_ERR;
    }
    rioInitWithFile(&rdb, fp);
    if (server.rdb_save_incremental_fsync) rioSetAutoSync(&rdb, REDIS_AUTOSYNC_BYTES);

    rsiptr = rdbPopulateSaveInfo(&rsi);
    if (rdbWriteHeader(&rdb, REPLICA_REQ_NONE, RDB_VERSION, RDBFLAGS_NONE, rsiptr) == C_ERR) goto err;
    if (server.cluster_enabled && clusterRDBSaveSlotImports(&rdb, RDB_VERSION) == C_ERR) goto err;
    /* Pending is built before `active` so the scan cannot race a mutation.
     * The server is single-threaded: no command runs until we return. */
    if (snapshotBuildPending() != C_OK) goto err;

    dirty_before = server.dirty;
    cow_keys = 0;
    slice_us_max = 0;
    last_dbid = -1;
    server.dirty_before_bgsave = server.dirty;
    server.lastbgsave_try = time(NULL);
    server.rdb_save_time_start = time(NULL);
    server.stat_rdb_saves++;
    active = 1;
    serverLog(LL_NOTICE, "Forkless snapshot started, %lld keys queued into %s",
              pending ? (long long)hashtableSize(pending) : 0, temp_path);
    return C_OK;

err:
    serverLog(LL_WARNING, "Forkless snapshot failed to start");
    snapshotReset();
    server.lastbgsave_status = C_ERR;
    return C_ERR;
}

static int snapshotFinish(void) {
    if (rdbWriteFooter(&rdb, REPLICA_REQ_NONE) == C_ERR) return C_ERR;
    if (fflush(fp) != 0) return C_ERR;
    if (fsync(fileno(fp)) != 0) return C_ERR;
    if (fclose(fp) != 0) {
        fp = NULL;
        return C_ERR;
    }
    fp = NULL;
    /* Readers keep seeing the previous dump until this rename. */
    if (rename(temp_path, finalfile) == -1) {
        serverLog(LL_WARNING, "Forkless snapshot rename %s -> %s failed: %s", temp_path, finalfile, strerror(errno));
        unlink(temp_path);
        temp_path[0] = '\0';
        return C_ERR;
    }
    temp_path[0] = '\0';
    if (fsyncFileDir(finalfile) != 0) {
        serverLog(LL_WARNING, "Forkless snapshot fsync dir failed: %s", strerror(errno));
    }
    if (pending) {
        hashtableRelease(pending);
        pending = NULL;
    }
    active = 0;
    server.dirty -= dirty_before;
    if (server.dirty < 0) server.dirty = 0;
    server.lastsave = time(NULL);
    server.lastbgsave_status = C_OK;
    server.lastbgsave_type = RDB_BGSAVE_TYPE_FORKLESS;
    server.rdb_save_time_last = time(NULL) - server.rdb_save_time_start;
    server.rdb_save_time_start = -1;
    serverLog(LL_NOTICE, "Forkless snapshot saved on disk (%lld keys copied on write)", cow_keys);
    return C_OK;
}

void snapshotForklessCron(void) {
    int budget;
    int wrote = 0;
    long long start;
    long long took;

    if (!active) return;
    budget = server.snapshot_forkless_slice_keys;
    if (budget < 1) budget = 1;
    start = ustime();
    while (pending && hashtableSize(pending) > 0 && wrote < budget) {
        if (wrote > 0 && ustime() - start > 1000) break;
        if (snapshotPopOne() != C_OK) {
            serverLog(LL_WARNING, "Forkless snapshot write failed");
            snapshotForklessCancel();
            server.lastbgsave_status = C_ERR;
            return;
        }
        wrote++;
    }
    took = ustime() - start;
    if (took > slice_us_max) slice_us_max = took;
    if (active && (!pending || hashtableSize(pending) == 0)) {
        if (snapshotFinish() != C_OK) {
            snapshotReset();
            server.lastbgsave_status = C_ERR;
            server.rdb_save_time_start = -1;
        }
    }
}

void snapshotForklessCancel(void) {
    if (!active && !fp && !pending) return;
    serverLog(LL_NOTICE, "Forkless snapshot cancelled; previous dump left in place");
    snapshotReset();
    server.rdb_save_time_start = -1;
    server.lastbgsave_status = C_ERR;
}
