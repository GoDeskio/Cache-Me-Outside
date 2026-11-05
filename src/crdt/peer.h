#ifndef CMO_CRDT_PEER_H
#define CMO_CRDT_PEER_H

#include "server.h"

void crdtInit(void);
void crdtCron(void);
int crdtCommandRejected(client *c);
void crdtObserveString(serverDb *db, robj *key, robj *val);
void crdtObserveCounter(serverDb *db, robj *key, long long delta);
void crdtObserveSetAdd(serverDb *db, robj *key, sds member);
void crdtObserveSetRemove(serverDb *db, robj *key, sds member);
void crdtObserveHashSet(serverDb *db, robj *key, sds field, sds value);
void crdtObserveHashDel(serverDb *db, robj *key, sds field);
void crdtObserveDelete(serverDb *db, robj *key);

#endif
