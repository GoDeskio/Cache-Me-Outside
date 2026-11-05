/*
 * Copyright (c) Valkey Contributors
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */

/* DRAM + flash value log used by the hybrid cache.
 *
 * The log is a cache, not a durability record. Callers keep the authoritative
 * value in the keyspace until they choose to spill it, and a restart truncates
 * the file. These functions do not touch the server global, so unit tests can
 * drive them directly. */

#ifndef CMO_HYBRID_H
#define CMO_HYBRID_H

#include <stddef.h>
#include <stdint.h>

typedef struct cmoHybridStore cmoHybridStore;

/* Create or replace `path`. `max_bytes` includes the file header. */
cmoHybridStore *cmoHybridStoreCreate(const char *path, size_t max_bytes);
void cmoHybridStoreFree(cmoHybridStore *st);

/* Copy val into the log. Replaces any previous record for the same key.
 * Returns 0, or -1 when the value does not fit. */
int cmoHybridStorePut(cmoHybridStore *st, int dbid, const char *key, size_t keylen, const char *val, size_t vallen);
/* On success, *out is a zmalloc buffer of *outlen bytes. */
int cmoHybridStoreGet(cmoHybridStore *st, int dbid, const char *key, size_t keylen, char **out, size_t *outlen);
int cmoHybridStoreDel(cmoHybridStore *st, int dbid, const char *key, size_t keylen);
void cmoHybridStoreDelDb(cmoHybridStore *st, int dbid);

uint64_t cmoHybridStoreLiveBytes(const cmoHybridStore *st);
uint64_t cmoHybridStoreFileBytes(const cmoHybridStore *st);
size_t cmoHybridStoreLiveKeys(const cmoHybridStore *st);
uint64_t cmoHybridStoreCompactions(const cmoHybridStore *st);

#endif
