/* Move cold large strings to the value log and bring them back on read.
 *
 * Copyright (c) 2026, Cache Me Outside contributors.
 * Licensed under the BSD 3-Clause License, the same terms as the server.
 */
#include "tier/tier.h"

/* Replace the string body with a log pointer and free the body now.
 * dbReplaceValue() can leave the old allocation charged: a refcount above 1
 * only decrements, and the swap path hands the sds to a throwaway object that
 * lazy-free may not reclaim before the next INFO. The key stays the same
 * hashtable entry, so this only rewrites that entry's value pointer. */
static int tierSpillObject(serverDb *db, robj *key, robj *o) {
    sds raw;
    tierRef *ref;
    UNUSED(db);
    UNUSED(key);
    if (!o || objectGetType(o) != OBJ_STRING) return 0;
    if (objectGetEncoding(o) != OBJ_ENCODING_RAW || o->hasembval) return 0;
    /* Another owner still needs the bytes. Try again on a later tick. */
    if (objectGetRefcount(o) != 1) return 0;
    raw = objectGetVal(o);
    if (sdslen(raw) < (size_t)server.tiering_min_value) return 0;
    if (server.tiering_idle_seconds > 0 && objectGetLRUIdleSecs(o) < (uint32_t)server.tiering_idle_seconds) return 0;
    ref = tierAppend(raw, sdslen(raw));
    if (!ref) return 0;
    objectSetEncoding(o, OBJ_ENCODING_TIERED);
    objectSetVal(o, ref);
    sdsfree(raw);
    return 1;
}

robj *tierPromote(serverDb *db, robj *key, robj *o) {
    tierRef *ref;
    sds raw;
    robj *neu;
    if (!o || objectGetEncoding(o) != OBJ_ENCODING_TIERED) return o;
    ref = objectGetVal(o);
    raw = tierReadRef(ref);
    if (!raw) return o;
    neu = createObject(OBJ_STRING, raw);
    dbReplaceValue(db, key, &neu);
    tierNotePromotion();
    return neu;
}

static int tierVisit(serverDb *db, int budget) {
    kvstoreIterator *it;
    void *next;
    int spilled = 0;
    if (!db || kvstoreSize(db->keys) == 0 || budget <= 0) return 0;
    it = kvstoreIteratorInit(db->keys, HASHTABLE_ITER_SAFE);
    while (budget > 0 && kvstoreIteratorNext(it, &next)) {
        robj *o = next;
        sds keystr;
        robj key;
        budget--;
        if (objectGetType(o) != OBJ_STRING) continue;
        if (objectGetEncoding(o) == OBJ_ENCODING_TIERED) continue;
        keystr = objectGetKey(o);
        initStaticStringObject(key, keystr);
        if (server.tiering_max_ram > 0 && (long long)zmalloc_used_memory() <= server.tiering_max_ram &&
            server.tiering_idle_seconds > 0 && objectGetLRUIdleSecs(o) < (uint32_t)server.tiering_idle_seconds)
            continue;
        if (tierSpillObject(db, &key, o)) spilled++;
        if (server.tiering_max_ram > 0 && (long long)zmalloc_used_memory() <= server.tiering_max_ram && spilled > 0 &&
            server.tiering_idle_seconds == 0)
            break;
    }
    kvstoreIteratorRelease(it);
    return spilled;
}

void tierCron(void) {
    int dbid;
    if (!server.tiering_enabled) return;
    for (dbid = 0; dbid < server.dbnum; dbid++) {
        if (server.db[dbid]) tierVisit(server.db[dbid], 64);
    }
    if (tierDeadBytes() > 4096 && tierDeadBytes() * 2 > tierBytesOnDisk()) {
        /* Collected by compact.c */
        extern int tierCompactLive(void);
        tierCompactLive();
    }
}
