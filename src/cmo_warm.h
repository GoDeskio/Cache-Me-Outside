/*
 * Copyright (c) Valkey Contributors
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */

/* Header that marks a warm-restart checkpoint as a complete file.
 * The payload itself is a normal snapshot. These helpers only check that the
 * bytes on disk still match the header written after a clean shutdown. */

#ifndef CMO_WARM_H
#define CMO_WARM_H

/* Write `<payload>.hdr` for the current payload bytes. 0 on success. */
int cmoWarmSeal(const char *payload_path);
/* 1 when the header matches the payload size and checksum, else 0. */
int cmoWarmHeaderOk(const char *payload_path);

#endif
