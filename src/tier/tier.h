#ifndef CMO_TIER_H
#define CMO_TIER_H

#include "server.h"

/* String values live in an append-only log. The object keeps only this
 * pointer. OBJ_ENCODING_TIERED is defined in server.h. A command never sees
 * that encoding: lookup promotes the value back to a normal string first. */

typedef struct tierRef {
    uint64_t offset;
    uint32_t len;
    uint64_t crc;
} tierRef;

void tierCron(void);
robj *tierPromote(serverDb *db, robj *key, robj *o);
tierRef *tierAppend(const char *buf, size_t len);
sds tierReadRef(const tierRef *ref);
void tierMarkDead(const tierRef *ref);
void tierFreeRef(tierRef *ref);
void tierNotePromotion(void);
int tierCompact(tierRef **live, int nlive);
long long tierBytesOnDisk(void);
long long tierSpills(void);
long long tierPromotions(void);
long long tierDeadBytes(void);

#endif
