/*
 * Copyright (c) Valkey Contributors
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */

#include "generated_wrappers.hpp"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

extern "C" {
#include "cmo_hybrid.h"
#include "zmalloc.h"
}

static int write_temp(char *path, size_t pathlen) {
    int n = snprintf(path, pathlen, "/tmp/cmo-hybrid-unit-%d.dat", (int)getpid());
    if (n < 0 || (size_t)n >= pathlen) return 0;
    return 1;
}

TEST(CmoHybrid, RoundTripAndDelete) {
    char path[128];
    cmoHybridStore *st;
    char *out;
    size_t outlen;
    const char *val = "abcdefghijklmnopqrstuvwxyz0123456789";

    ASSERT_TRUE(write_temp(path, sizeof(path)));
    st = cmoHybridStoreCreate(path, 1024 * 1024);
    ASSERT_TRUE(st != NULL);
    ASSERT_EQ(0, cmoHybridStorePut(st, 0, "user:1", 6, val, strlen(val)));
    ASSERT_EQ(1u, cmoHybridStoreLiveKeys(st));
    ASSERT_EQ(0, cmoHybridStoreGet(st, 0, "user:1", 6, &out, &outlen));
    ASSERT_EQ(strlen(val), outlen);
    ASSERT_EQ(0, memcmp(out, val, outlen));
    zfree(out);
    ASSERT_EQ(0, cmoHybridStoreDel(st, 0, "user:1", 6));
    ASSERT_EQ(0u, cmoHybridStoreLiveKeys(st));
    ASSERT_EQ(-1, cmoHybridStoreGet(st, 0, "user:1", 6, &out, &outlen));
    cmoHybridStoreFree(st);
    unlink(path);
}

TEST(CmoHybrid, SameKeyInTwoDatabases) {
    char path[128];
    cmoHybridStore *st;
    char *out;
    size_t outlen;

    ASSERT_TRUE(write_temp(path, sizeof(path)));
    st = cmoHybridStoreCreate(path, 1024 * 1024);
    ASSERT_TRUE(st != NULL);
    ASSERT_EQ(0, cmoHybridStorePut(st, 0, "k", 1, "db0", 3));
    ASSERT_EQ(0, cmoHybridStorePut(st, 1, "k", 1, "db1-value", 9));
    ASSERT_EQ(0, cmoHybridStoreGet(st, 0, "k", 1, &out, &outlen));
    ASSERT_EQ(3u, outlen);
    ASSERT_EQ(0, memcmp(out, "db0", 3));
    zfree(out);
    ASSERT_EQ(0, cmoHybridStoreGet(st, 1, "k", 1, &out, &outlen));
    ASSERT_EQ(9u, outlen);
    ASSERT_EQ(0, memcmp(out, "db1-value", 9));
    zfree(out);
    cmoHybridStoreDelDb(st, 0);
    ASSERT_EQ(-1, cmoHybridStoreGet(st, 0, "k", 1, &out, &outlen));
    ASSERT_EQ(0, cmoHybridStoreGet(st, 1, "k", 1, &out, &outlen));
    zfree(out);
    cmoHybridStoreFree(st);
    unlink(path);
}

TEST(CmoHybrid, CompactionKeepsLiveRecords) {
    char path[128];
    char tmp[160];
    cmoHybridStore *st;
    char body[128];
    char key[16];
    char *out;
    size_t outlen;
    int i;

    ASSERT_TRUE(write_temp(path, sizeof(path)));
    memset(body, 'x', sizeof(body));
    /* Small cap forces a rewrite once deleted records fill the file. */
    st = cmoHybridStoreCreate(path, 2500);
    ASSERT_TRUE(st != NULL);
    for (i = 0; i < 20; i++) {
        snprintf(key, sizeof(key), "k%d", i);
        ASSERT_EQ(0, cmoHybridStorePut(st, 0, key, strlen(key), body, sizeof(body)));
        if (i < 15) {
            ASSERT_EQ(0, cmoHybridStoreDel(st, 0, key, strlen(key)));
        }
    }
    ASSERT_TRUE(cmoHybridStoreCompactions(st) > 0);
    for (i = 15; i < 20; i++) {
        snprintf(key, sizeof(key), "k%d", i);
        ASSERT_EQ(0, cmoHybridStoreGet(st, 0, key, strlen(key), &out, &outlen));
        ASSERT_EQ(sizeof(body), outlen);
        ASSERT_EQ(0, memcmp(out, body, sizeof(body)));
        zfree(out);
    }
    ASSERT_EQ(5u, cmoHybridStoreLiveKeys(st));
    cmoHybridStoreFree(st);
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);
    unlink(path);
    unlink(tmp);
}
