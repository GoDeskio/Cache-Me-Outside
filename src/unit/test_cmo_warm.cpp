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
#include "cmo_warm.h"
}

TEST(CmoWarm, SealMatchesUntilThePayloadChanges) {
    char path[128];
    FILE *fp;
    int n;

    n = snprintf(path, sizeof(path), "/tmp/cmo-warm-unit-%d.bin", (int)getpid());
    ASSERT_TRUE(n > 0 && (size_t)n < sizeof(path));
    fp = fopen(path, "wb");
    ASSERT_TRUE(fp != NULL);
    ASSERT_EQ(5u, fwrite("hello", 1, 5, fp));
    fclose(fp);

    ASSERT_EQ(0, cmoWarmSeal(path));
    ASSERT_EQ(1, cmoWarmHeaderOk(path));

    fp = fopen(path, "r+b");
    ASSERT_TRUE(fp != NULL);
    ASSERT_EQ(0, fseek(fp, 0, SEEK_SET));
    ASSERT_EQ(1u, fwrite("H", 1, 1, fp));
    fclose(fp);
    ASSERT_EQ(0, cmoWarmHeaderOk(path));

    unlink(path);
    n = snprintf(path, sizeof(path), "/tmp/cmo-warm-unit-%d.bin.hdr", (int)getpid());
    ASSERT_TRUE(n > 0);
    unlink(path);
}
