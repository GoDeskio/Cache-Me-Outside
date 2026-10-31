/*
 * Copyright (c) Valkey Contributors
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */

/* Warm restart keeps the cache across a process restart without turning RDB
 * saves or AOF on. A clean shutdown writes a snapshot plus a checksum header.
 * The next start loads that snapshot only when the durability files did not
 * already load a dataset. A crash mid-write leaves the previous header in
 * place, or none, so a torn file is not treated as a checkpoint.
 *
 * The snapshot uses this server's own snapshot writer. The header is the part
 * that makes the file a warm-restart image rather than the configured RDB. */

#include "server.h"

#include "cmo_warm.h"
#include "rdb.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define CMO_WARM_MAGIC "CMOWARM1"
#define CMO_WARM_HDR 40

static void ensure_crc(void) {
    static int ready = 0;
    if (!ready) {
        crc64_init();
        ready = 1;
    }
}

static int crc_file(FILE *fp, uint64_t *crc_out, uint64_t *size_out) {
    unsigned char buf[65536];
    uint64_t crc = 0;
    uint64_t size = 0;
    size_t n;

    ensure_crc();
    if (fseek(fp, 0, SEEK_SET) != 0) return -1;
    while ((n = fread(buf, 1, sizeof(buf), fp)) > 0) {
        crc = crc64(crc, buf, n);
        size += n;
    }
    if (ferror(fp)) return -1;
    *crc_out = crc;
    *size_out = size;
    return 0;
}

static void header_path(const char *payload, char *out, size_t outlen) {
    snprintf(out, outlen, "%s.hdr", payload);
}

int cmoWarmSeal(const char *payload_path) {
    FILE *fp;
    char hdr_path[1024];
    char tmp_path[1100];
    unsigned char hdr[CMO_WARM_HDR];
    uint64_t crc = 0, size = 0, when;
    uint32_t version = 1;
    FILE *hf;

    if (!payload_path || strlen(payload_path) > 900) return -1;
    fp = fopen(payload_path, "rb");
    if (!fp) return -1;
    if (crc_file(fp, &crc, &size) != 0) {
        fclose(fp);
        return -1;
    }
    fclose(fp);

    memset(hdr, 0, sizeof(hdr));
    memcpy(hdr, CMO_WARM_MAGIC, 8);
    memcpy(hdr + 8, &version, sizeof(version));
    memcpy(hdr + 16, &size, sizeof(size));
    memcpy(hdr + 24, &crc, sizeof(crc));
    when = (uint64_t)time(NULL);
    memcpy(hdr + 32, &when, sizeof(when));

    header_path(payload_path, hdr_path, sizeof(hdr_path));
    snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", hdr_path);
    hf = fopen(tmp_path, "wb");
    if (!hf) return -1;
    if (fwrite(hdr, 1, sizeof(hdr), hf) != sizeof(hdr)) {
        fclose(hf);
        unlink(tmp_path);
        return -1;
    }
    if (fflush(hf) != 0 || fsync(fileno(hf)) != 0) {
        fclose(hf);
        unlink(tmp_path);
        return -1;
    }
    fclose(hf);
    if (rename(tmp_path, hdr_path) != 0) {
        unlink(tmp_path);
        return -1;
    }
    return 0;
}

int cmoWarmHeaderOk(const char *payload_path) {
    FILE *fp;
    FILE *hf;
    char hdr_path[1024];
    unsigned char hdr[CMO_WARM_HDR];
    uint32_t version = 0;
    uint64_t size = 0, crc = 0, file_size = 0, file_crc = 0;

    if (!payload_path) return 0;
    header_path(payload_path, hdr_path, sizeof(hdr_path));
    hf = fopen(hdr_path, "rb");
    if (!hf) return 0;
    if (fread(hdr, 1, sizeof(hdr), hf) != sizeof(hdr)) {
        fclose(hf);
        return 0;
    }
    fclose(hf);
    if (memcmp(hdr, CMO_WARM_MAGIC, 8) != 0) return 0;
    memcpy(&version, hdr + 8, sizeof(version));
    memcpy(&size, hdr + 16, sizeof(size));
    memcpy(&crc, hdr + 24, sizeof(crc));
    if (version != 1) return 0;

    fp = fopen(payload_path, "rb");
    if (!fp) return 0;
    if (crc_file(fp, &file_crc, &file_size) != 0) {
        fclose(fp);
        return 0;
    }
    fclose(fp);
    return file_size == size && file_crc == crc;
}

void cmoWarmSave(void) {
    rdbSaveInfo rsi, *rsiptr;

    if (!server.cmo_warm_enabled || !server.cmo_warm_file || !server.cmo_warm_file[0]) return;
    if (server.loading) return;
    if (server.rdb_filename && strcmp(server.cmo_warm_file, server.rdb_filename) == 0) {
        serverLog(LL_WARNING, "cmo-warm-file must not be the same path as dbfilename; warm restart skipped");
        return;
    }
    serverLog(LL_NOTICE, "Writing warm-restart checkpoint to %s", server.cmo_warm_file);
    rsiptr = rdbPopulateSaveInfo(&rsi);
    if (rdbSave(REPLICA_REQ_NONE, server.cmo_warm_file, rsiptr, RDBFLAGS_NONE) != C_OK) {
        serverLog(LL_WARNING, "Warm-restart checkpoint failed");
        return;
    }
    if (cmoWarmSeal(server.cmo_warm_file) != 0) {
        serverLog(LL_WARNING, "Warm-restart checkpoint header failed: %s", strerror(errno));
        unlink(server.cmo_warm_file);
    }
}

void cmoWarmTryLoad(void) {
    rdbSaveInfo rsi = RDB_SAVE_INFO_INIT;
    int ret;

    if (!server.cmo_warm_enabled || !server.cmo_warm_file || !server.cmo_warm_file[0]) return;
    if (!cmoWarmHeaderOk(server.cmo_warm_file)) {
        serverLog(LL_NOTICE, "No valid warm-restart checkpoint at %s", server.cmo_warm_file);
        return;
    }
    serverLog(LL_NOTICE, "Loading warm-restart checkpoint from %s", server.cmo_warm_file);
    ret = rdbLoad(server.cmo_warm_file, &rsi, RDBFLAGS_NONE);
    if (ret != RDB_OK) {
        serverLog(LL_WARNING, "Warm-restart checkpoint %s could not be loaded", server.cmo_warm_file);
    }
}
