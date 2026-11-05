/* Append-only value log. Records are checksummed. A torn tail (crash during
 * append) is dropped the next time the file is opened. Compaction writes a
 * new file and renames it over the old one, so a crash before rename leaves
 * the previous log intact.
 *
 * Layout of one record: magic u32, length u32, crc64 u64, payload.
 * Ideas from memcached extstore and KeyDB FLASH (BSD) stopped at "append-only
 * value log plus a pointer". This file is not derived from either.
 *
 * Copyright (c) 2026, Cache Me Outside contributors.
 * Licensed under the BSD 3-Clause License, the same terms as the server.
 */
#include "tier/tier.h"

#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>

#define TIER_MAGIC 0xC0E71067u

static int tier_fd = -1;
static uint64_t tier_end = 0;
static long long tier_dead = 0;
static long long tier_spills = 0;
static long long tier_promotions = 0;
static int tier_torn = 0;

static uint64_t tier_crc(const unsigned char *p, size_t n) {
    uint64_t c = 0xcbf29ce484222325ULL;
    size_t i;
    for (i = 0; i < n; i++) {
        c ^= p[i];
        c *= 0x100000001b3ULL;
    }
    return c;
}

static int tier_open(void) {
    if (tier_fd >= 0) return C_OK;
    if (!server.tiering_path || !server.tiering_path[0]) return C_ERR;
    tier_fd = open(server.tiering_path, O_RDWR | O_CREAT, 0644);
    if (tier_fd < 0) {
        serverLog(LL_WARNING, "Tiering open %s failed: %s", server.tiering_path, strerror(errno));
        return C_ERR;
    }
    tier_end = 0;
    for (;;) {
        unsigned char hdr[16];
        uint32_t magic, len;
        uint64_t crc, got;
        ssize_t n = pread(tier_fd, hdr, sizeof(hdr), (off_t)tier_end);
        if (n == 0) break;
        if (n != (ssize_t)sizeof(hdr)) {
            tier_torn = 1;
            break;
        }
        memcpy(&magic, hdr, 4);
        memcpy(&len, hdr + 4, 4);
        memcpy(&crc, hdr + 8, 8);
        if (magic != TIER_MAGIC || len > 64 * 1024 * 1024) {
            tier_torn = 1;
            break;
        }
        {
            unsigned char *buf = zmalloc(len ? len : 1);
            ssize_t rn = pread(tier_fd, buf, len, (off_t)(tier_end + 16));
            if (rn != (ssize_t)len) {
                zfree(buf);
                tier_torn = 1;
                break;
            }
            got = tier_crc(buf, len);
            zfree(buf);
            if (got != crc) {
                tier_torn = 1;
                break;
            }
        }
        tier_end += 16 + len;
    }
    if (tier_torn) {
        if (ftruncate(tier_fd, (off_t)tier_end) == 0) {
            serverLog(LL_WARNING, "Tiering dropped a torn tail at offset %llu", (unsigned long long)tier_end);
        }
    }
    return C_OK;
}

tierRef *tierAppend(const char *buf, size_t len) {
    unsigned char hdr[16];
    uint32_t magic = TIER_MAGIC;
    uint32_t ulen = (uint32_t)len;
    uint64_t crc;
    tierRef *ref;
    if (tier_open() != C_OK) return NULL;
    if (len > 0xffffffffu) return NULL;
    crc = tier_crc((const unsigned char *)buf, len);
    memcpy(hdr, &magic, 4);
    memcpy(hdr + 4, &ulen, 4);
    memcpy(hdr + 8, &crc, 8);
    if (pwrite(tier_fd, hdr, sizeof(hdr), (off_t)tier_end) != (ssize_t)sizeof(hdr)) return NULL;
    if (len && pwrite(tier_fd, buf, len, (off_t)(tier_end + 16)) != (ssize_t)len) return NULL;
    ref = zmalloc(sizeof(*ref));
    ref->offset = tier_end;
    ref->len = ulen;
    ref->crc = crc;
    tier_end += 16 + len;
    tier_spills++;
    if (server.tiering_debug_crash_after > 0 && tier_spills >= server.tiering_debug_crash_after) {
        unsigned char junk[8] = {1, 2, 3, 4, 5, 6, 7, 8};
        pwrite(tier_fd, junk, sizeof(junk), (off_t)tier_end);
        _exit(0);
    }
    return ref;
}

sds tierReadRef(const tierRef *ref) {
    unsigned char hdr[16];
    uint32_t magic, len;
    uint64_t crc;
    sds out;
    ssize_t n;
    if (!ref || tier_open() != C_OK) return NULL;
    n = pread(tier_fd, hdr, sizeof(hdr), (off_t)ref->offset);
    if (n != (ssize_t)sizeof(hdr)) return NULL;
    memcpy(&magic, hdr, 4);
    memcpy(&len, hdr + 4, 4);
    memcpy(&crc, hdr + 8, 8);
    if (magic != TIER_MAGIC || len != ref->len || crc != ref->crc) return NULL;
    out = sdsnewlen(NULL, len);
    if (len && pread(tier_fd, out, len, (off_t)(ref->offset + 16)) != (ssize_t)len) {
        sdsfree(out);
        return NULL;
    }
    if (tier_crc((unsigned char *)out, len) != crc) {
        sdsfree(out);
        return NULL;
    }
    return out;
}

void tierMarkDead(const tierRef *ref) {
    if (!ref) return;
    tier_dead += 16 + ref->len;
}

void tierFreeRef(tierRef *ref) {
    zfree(ref);
}

long long tierBytesOnDisk(void) {
    return (long long)tier_end;
}
long long tierSpills(void) {
    return tier_spills;
}
long long tierPromotions(void) {
    return tier_promotions;
}
long long tierDeadBytes(void) {
    return tier_dead;
}
void tierNotePromotion(void) {
    tier_promotions++;
}

/* Rewrite live records. `live` is an array of refs still installed in keys.
 * Offsets inside those refs are updated. Returns C_OK, or _exit()s first
 * when tiering-debug-exit-before-rename is set. */
int tierCompact(tierRef **live, int nlive) {
    char tmp[512];
    int fd, i;
    uint64_t end = 0;
    if (tier_fd < 0 || nlive < 0) return C_ERR;
    snprintf(tmp, sizeof(tmp), "%s.compact", server.tiering_path);
    fd = open(tmp, O_RDWR | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return C_ERR;
    for (i = 0; i < nlive; i++) {
        sds payload = tierReadRef(live[i]);
        unsigned char hdr[16];
        uint32_t magic = TIER_MAGIC;
        uint32_t len;
        uint64_t crc;
        if (!payload) {
            close(fd);
            unlink(tmp);
            return C_ERR;
        }
        len = (uint32_t)sdslen(payload);
        crc = tier_crc((unsigned char *)payload, len);
        memcpy(hdr, &magic, 4);
        memcpy(hdr + 4, &len, 4);
        memcpy(hdr + 8, &crc, 8);
        if (pwrite(fd, hdr, sizeof(hdr), (off_t)end) != (ssize_t)sizeof(hdr) ||
            (len && pwrite(fd, payload, len, (off_t)(end + 16)) != (ssize_t)len)) {
            sdsfree(payload);
            close(fd);
            unlink(tmp);
            return C_ERR;
        }
        live[i]->offset = end;
        live[i]->crc = crc;
        end += 16 + len;
        sdsfree(payload);
    }
    if (fsync(fd) != 0) {
        close(fd);
        unlink(tmp);
        return C_ERR;
    }
    if (server.tiering_debug_exit_before_rename) {
        close(fd);
        _exit(0);
    }
    close(fd);
    if (rename(tmp, server.tiering_path) != 0) {
        unlink(tmp);
        return C_ERR;
    }
    close(tier_fd);
    tier_fd = open(server.tiering_path, O_RDWR, 0644);
    tier_end = end;
    tier_dead = 0;
    return tier_fd >= 0 ? C_OK : C_ERR;
}
