/*
 * Copyright (c) Valkey Contributors
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "generated_wrappers.hpp"

#include <string.h>

extern "C" {
#include "cmo_ttlseg.h"
#include "sds.h"
}

typedef struct due_buf {
    int n;
    int dbid[8];
    sds key[8];
} due_buf;

static void record_due(int dbid, const char *key, size_t keylen, void *userdata) {
    due_buf *b = (due_buf *)userdata;
    if (b->n >= 8) return;
    b->dbid[b->n] = dbid;
    b->key[b->n] = sdsnewlen(key, keylen);
    b->n++;
}

static void free_due(due_buf *b) {
    int i;
    for (i = 0; i < b->n; i++) sdsfree(b->key[i]);
}

TEST(CmoTtlSeg, ReapDropsAFinishedBucketOnly) {
    cmoTtlSegs *t = cmoTtlSegsCreate(1000);
    due_buf due;
    int n;

    memset(&due, 0, sizeof(due));
    cmoTtlSegsTrack(t, 0, "a", 1, 100);
    cmoTtlSegsTrack(t, 0, "b", 1, 900);
    cmoTtlSegsTrack(t, 1, "later", 5, 1500);
    ASSERT_EQ(3, cmoTtlSegsCount(t));

    n = cmoTtlSegsReap(t, 1000, record_due, &due);
    ASSERT_EQ(2, n);
    ASSERT_EQ(2, due.n);
    ASSERT_EQ(1, cmoTtlSegsCount(t));
    ASSERT_TRUE((strcmp(due.key[0], "a") == 0 && strcmp(due.key[1], "b") == 0) ||
                (strcmp(due.key[0], "b") == 0 && strcmp(due.key[1], "a") == 0));

    n = cmoTtlSegsReap(t, 1000, record_due, &due);
    ASSERT_EQ(0, n);
    n = cmoTtlSegsReap(t, 2000, record_due, &due);
    ASSERT_EQ(1, n);
    ASSERT_EQ(0, strcmp(due.key[2], "later"));
    ASSERT_EQ(1, due.dbid[2]);
    ASSERT_EQ(0, cmoTtlSegsCount(t));
    free_due(&due);
    cmoTtlSegsFree(t);
}

TEST(CmoTtlSeg, MovingAKeyLeavesTheOldBucket) {
    cmoTtlSegs *t = cmoTtlSegsCreate(1000);
    due_buf due;
    int n;

    memset(&due, 0, sizeof(due));
    cmoTtlSegsTrack(t, 0, "a", 1, 100);
    cmoTtlSegsTrack(t, 0, "a", 1, 2500);
    cmoTtlSegsUntrack(t, 0, "gone", 4);
    ASSERT_EQ(1, cmoTtlSegsCount(t));
    n = cmoTtlSegsReap(t, 1000, record_due, &due);
    ASSERT_EQ(0, n);
    n = cmoTtlSegsReap(t, 3000, record_due, &due);
    ASSERT_EQ(1, n);
    ASSERT_EQ(0, strcmp(due.key[0], "a"));
    free_due(&due);
    cmoTtlSegsFree(t);
}
