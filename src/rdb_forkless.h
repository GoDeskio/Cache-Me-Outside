#ifndef __RDB_FORKLESS_H
#define __RDB_FORKLESS_H

#include "server.h"

/* Main-thread incremental snapshot. Distinct from the background-thread
 * forkless saver (forkless.c): this one never forks and never samples the
 * live keyspace after a key has been mutated. */
int snapshotForklessStart(const char *filename);
void snapshotForklessCancel(void);
int snapshotForklessInProgress(void);
void snapshotForklessCron(void);
void snapshotForklessBeforeWrite(serverDb *db, robj *key);
long long snapshotForklessKeysRemaining(void);
long long snapshotForklessCowKeys(void);
long long snapshotForklessSliceUsMax(void);

#endif
