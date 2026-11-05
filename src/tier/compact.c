/* Gather live tier pointers and rewrite the value log.
 *
 * Copyright (c) 2026, Cache Me Outside contributors.
 * Licensed under the BSD 3-Clause License, the same terms as the server.
 */
#include "tier/tier.h"

int tierCompactLive(void) {
    tierRef **live = NULL;
    int n = 0, cap = 0, dbid;
    int rc;
    for (dbid = 0; dbid < server.dbnum; dbid++) {
        serverDb *db = server.db[dbid];
        kvstoreIterator *it;
        void *next;
        if (!db) continue;
        it = kvstoreIteratorInit(db->keys, 0);
        while (kvstoreIteratorNext(it, &next)) {
            robj *o = next;
            if (objectGetType(o) != OBJ_STRING || objectGetEncoding(o) != OBJ_ENCODING_TIERED) continue;
            if (n == cap) {
                cap = cap ? cap * 2 : 16;
                live = zrealloc(live, sizeof(*live) * (size_t)cap);
            }
            live[n++] = objectGetVal(o);
        }
        kvstoreIteratorRelease(it);
    }
    rc = tierCompact(live, n);
    zfree(live);
    return rc;
}
