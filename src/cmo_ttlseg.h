/*
 * Copyright (c) Valkey Contributors
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */

/* TTL segments group keys whose expiry falls in the same time bucket.
 * When the bucket's end time is reached, every key in it is due together.
 * The pure table does not delete database keys; the caller does. */

#ifndef CMO_TTLSEG_H
#define CMO_TTLSEG_H

#include <stddef.h>

typedef struct cmoTtlSegs cmoTtlSegs;
typedef void (*cmoTtlDueFn)(int dbid, const char *key, size_t keylen, void *userdata);

cmoTtlSegs *cmoTtlSegsCreate(long long width_ms);
void cmoTtlSegsFree(cmoTtlSegs *t);
void cmoTtlSegsTrack(cmoTtlSegs *t, int dbid, const char *key, size_t keylen, long long when_ms);
void cmoTtlSegsUntrack(cmoTtlSegs *t, int dbid, const char *key, size_t keylen);
void cmoTtlSegsDropDb(cmoTtlSegs *t, int dbid);
/* Hand every key whose bucket has ended to fn, then forget those keys.
 * Returns how many keys were handed over. */
int cmoTtlSegsReap(cmoTtlSegs *t, long long now_ms, cmoTtlDueFn fn, void *userdata);
int cmoTtlSegsCount(const cmoTtlSegs *t);

#endif
