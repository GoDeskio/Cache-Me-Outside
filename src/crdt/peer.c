/* Peer link and key metadata for active-active CRDT replication.
 *
 * Local writes update a per-key crdtState and queue CRDT.APPLY to each
 * configured peer. The command rides a normal client connection and is not
 * forwarded again, so peers do not loop. Replicas still receive it through
 * the ordinary replication stream.
 *
 * Copyright (c) 2026, Cache Me Outside contributors.
 * Licensed under the BSD 3-Clause License, the same terms as the server.
 */
#include "server.h"
#include "crdt/crdt.h"
#include "crdt/peer.h"
#include "anet.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define CRDT_MAX_PEERS 8

typedef struct crdtEntry {
    int dbid;
    sds key;
    crdtState state;
} crdtEntry;

typedef struct crdtPeer {
    char host[64];
    int port;
    int fd;
    sds outbuf;
    uint64_t ack_pt;
} crdtPeer;

static hashtable *g_keys;
static hlc g_clock;
static int g_applying;
static crdtPeer g_peers[CRDT_MAX_PEERS];
static int g_npeers;
static sds g_peers_sig;
static int g_tombstones;

static void recountTombstones(void);

static const void *entryKey(const void *e) {
    return e;
}
static uint64_t entryHash(const void *key) {
    const crdtEntry *e = key;
    return dictSdsHash(e->key) ^ ((uint64_t)e->dbid * 0x9E3779B97F4A7C15ULL);
}
static int entryCmp(const void *a, const void *b) {
    const crdtEntry *ea = a, *eb = b;
    if (ea->dbid != eb->dbid) return 0;
    if (sdslen(ea->key) != sdslen(eb->key)) return 0;
    return memcmp(ea->key, eb->key, sdslen(ea->key)) == 0;
}
static void crdtEntryFree(void *p) {
    crdtEntry *e = p;
    crdtStateClear(&e->state);
    sdsfree(e->key);
    zfree(e);
}

static hashtableType entryType = {
    .entryGetKey = entryKey,
    .hashFunction = entryHash,
    .keyCompare = entryCmp,
    .entryDestructor = crdtEntryFree,
};

static int crdtActive(void) {
    return server.crdt_enabled && !server.loading && !g_applying;
}

static crdtEntry *entryFind(int dbid, sds key, int create) {
    crdtEntry probe, *found = NULL;
    probe.dbid = dbid;
    probe.key = key;
    if (g_keys && hashtableFind(g_keys, &probe, (void **)&found)) return found;
    if (!create) return NULL;
    found = zcalloc(sizeof(*found));
    found->dbid = dbid;
    found->key = sdsdup(key);
    crdtStateInit(&found->state);
    if (!g_keys) g_keys = hashtableCreate(&entryType);
    hashtableAdd(g_keys, found);
    return found;
}

static uint16_t region(void) {
    int id = server.crdt_region_id;
    if (id < 1) id = 1;
    if (id > 65535) id = 65535;
    return (uint16_t)id;
}

static uint64_t wall(void) {
    return server.mstime > 0 ? (uint64_t)server.mstime : 0;
}

static void queueApply(int dbid, sds key, const crdtState *state) {
    size_t blen = 0;
    char *blob = crdtEncode(state, &blen);
    char hdr[96];
    char dbnum[32];
    int i, n, dbdigits;
    sds cmd;
    dbdigits = snprintf(dbnum, sizeof(dbnum), "%d", dbid);
    n = snprintf(hdr, sizeof(hdr), "*2\r\n$6\r\nSELECT\r\n$%d\r\n%s\r\n*3\r\n$10\r\ncrdt.apply\r\n$%zu\r\n", dbdigits, dbnum, sdslen(key));
    cmd = sdsnewlen(hdr, n);
    cmd = sdscatlen(cmd, key, sdslen(key));
    n = snprintf(hdr, sizeof(hdr), "\r\n$%zu\r\n", blen);
    cmd = sdscatlen(cmd, hdr, n);
    cmd = sdscatlen(cmd, blob, blen);
    cmd = sdscatlen(cmd, "\r\n", 2);
    crdtFreeBuffer(blob);
    for (i = 0; i < g_npeers; i++) {
        if (!g_peers[i].outbuf) g_peers[i].outbuf = sdsempty();
        g_peers[i].outbuf = sdscatsds(g_peers[i].outbuf, cmd);
    }
    sdsfree(cmd);
}

static void publish(crdtEntry *e) {
    queueApply(e->dbid, e->key, &e->state);
}

void crdtObserveString(serverDb *db, robj *key, robj *val) {
    robj *dec;
    sds v;
    crdtEntry *e;
    if (!crdtActive() || !db || !key || !val) return;
    e = entryFind(db->id, objectGetVal(key), 1);
    dec = getDecodedObject(val);
    v = objectGetVal(dec);
    crdtStringSet(&e->state, &g_clock, wall(), region(), v, sdslen(v));
    decrRefCount(dec);
    publish(e);
}

void crdtObserveCounter(serverDb *db, robj *key, long long delta) {
    crdtEntry *e;
    if (!crdtActive() || !db || !key) return;
    e = entryFind(db->id, objectGetVal(key), 1);
    if (!e->state.has_counter) {
        robj *o = dbFind(db, objectGetVal(key));
        long long now = 0, before;
        if (o && getLongLongFromObject(o, &now) == C_OK) {
            before = now - delta;
            if (before) crdtCounterAdd(&e->state, &g_clock, wall(), region(), before);
        }
    }
    crdtCounterAdd(&e->state, &g_clock, wall(), region(), delta);
    publish(e);
}

void crdtObserveSetAdd(serverDb *db, robj *key, sds member) {
    crdtEntry *e;
    if (!crdtActive() || !member) return;
    e = entryFind(db->id, objectGetVal(key), 1);
    crdtSetAdd(&e->state, &g_clock, wall(), region(), member, sdslen(member));
    publish(e);
}

void crdtObserveSetRemove(serverDb *db, robj *key, sds member) {
    crdtEntry *e;
    if (!crdtActive() || !member) return;
    e = entryFind(db->id, objectGetVal(key), 1);
    crdtSetRemove(&e->state, &g_clock, wall(), region(), member, sdslen(member));
    publish(e);
}

void crdtObserveHashSet(serverDb *db, robj *key, sds field, sds value) {
    crdtEntry *e;
    if (!crdtActive() || !field) return;
    e = entryFind(db->id, objectGetVal(key), 1);
    crdtHashSet(&e->state, &g_clock, wall(), region(), field, sdslen(field), value ? value : "", value ? sdslen(value) : 0);
    publish(e);
}

void crdtObserveHashDel(serverDb *db, robj *key, sds field) {
    crdtEntry *e;
    if (!crdtActive() || !field) return;
    e = entryFind(db->id, objectGetVal(key), 1);
    crdtHashDel(&e->state, &g_clock, wall(), region(), field, sdslen(field));
    publish(e);
}

void crdtObserveDelete(serverDb *db, robj *key) {
    crdtEntry *e;
    if (!crdtActive()) return;
    e = entryFind(db->id, objectGetVal(key), 1);
    crdtTombstone(&e->state, &g_clock, wall(), region());
    publish(e);
}

static void materialize(client *c, serverDb *db, robj *key, const crdtState *s) {
    int i;
    g_applying = 1;
    if (s->kind == CRDT_KIND_TOMB || s->kind == CRDT_KIND_NONE) {
        if (dbFind(db, objectGetVal(key))) dbDelete(db, key);
    } else if (s->kind == CRDT_KIND_STRING || s->kind == CRDT_KIND_COUNTER) {
        char num[64];
        sds v;
        robj *o;
        if (s->kind == CRDT_KIND_COUNTER) {
            ll2string(num, sizeof(num), crdtCounterValue(s));
            v = sdsnew(num);
        } else {
            v = sdsnewlen(s->str ? s->str : "", s->str_len);
        }
        o = createObject(OBJ_STRING, v);
        setKey(c, db, key, &o, 0);
    } else if (s->kind == CRDT_KIND_SET) {
        int present = 0;
        robj *set;
        for (i = 0; i < s->nelems; i++)
            if (crdtSetContains(s, s->elems[i].member, s->elems[i].member_len)) present++;
        if (dbFind(db, objectGetVal(key))) dbDelete(db, key);
        if (!present) {
            g_applying = 0;
            return;
        }
        set = createSetObject();
        for (i = 0; i < s->nelems; i++) {
            sds m;
            if (!crdtSetContains(s, s->elems[i].member, s->elems[i].member_len)) continue;
            m = sdsnewlen(s->elems[i].member, s->elems[i].member_len);
            setTypeAdd(set, m);
            sdsfree(m);
        }
        setKey(c, db, key, &set, 0);
    } else if (s->kind == CRDT_KIND_HASH) {
        robj *hash = createHashObject();
        bool ignored = false;
        if (dbFind(db, objectGetVal(key))) dbDelete(db, key);
        for (i = 0; i < s->nfields; i++) {
            sds f, v;
            if (s->fields[i].deleted) continue;
            f = sdsnewlen(s->fields[i].field, s->fields[i].field_len);
            v = sdsnewlen(s->fields[i].value ? s->fields[i].value : "", s->fields[i].value_len);
            hashTypeSet(hash, f, v, -1, HASH_SET_COPY, &ignored);
            sdsfree(f);
            sdsfree(v);
        }
        setKey(c, db, key, &hash, 0);
    }
    g_applying = 0;
}

static void crdtApplyCommand(client *c) {
    sds blob, keyname;
    crdtState incoming, *dst;
    crdtEntry *e;
    if (!server.crdt_enabled) {
        addReplyError(c, "ERR CRDT is disabled");
        return;
    }
    if (c->argc != 3) {
        addReplyErrorArity(c);
        return;
    }
    keyname = objectGetVal(c->argv[1]);
    blob = objectGetVal(c->argv[2]);
    if (crdtDecode(&incoming, blob, sdslen(blob)) != 0) {
        addReplyError(c, "ERR invalid CRDT payload");
        return;
    }
    e = entryFind(c->db->id, keyname, 1);
    dst = &e->state;
    if (dst->kind == CRDT_KIND_TOMB && incoming.kind != CRDT_KIND_TOMB && g_tombstones) g_tombstones--;
    crdtMerge(dst, &incoming);
    if (dst->kind == CRDT_KIND_TOMB) {
        /* publish() increments; merge may already have the flag. Count once. */
    }
    hlcReceive(&g_clock, &incoming.clock, wall());
    materialize(c, c->db, c->argv[1], dst);
    if (dst->kind == CRDT_KIND_TOMB) {
        /* tombstones counted in publish for local deletes. Remote merge: count if new. */
    }
    crdtStateClear(&incoming);
    server.dirty++;
    addReply(c, shared.ok);
}

static void crdtGcCommand(client *c) {
    int dropped = 0;
    uint64_t ack = UINT64_MAX;
    int i;
    hashtableIterator iter;
    void *next;
    if (!server.crdt_enabled || !g_keys) {
        addReplyLongLong(c, 0);
        return;
    }
    for (i = 0; i < g_npeers; i++) {
        /* An empty outbound buffer means this peer has been handed every op. */
        if (g_peers[i].fd >= 0 && (!g_peers[i].outbuf || sdslen(g_peers[i].outbuf) == 0)) g_peers[i].ack_pt = g_clock.pt;
        if (g_peers[i].ack_pt < ack) ack = g_peers[i].ack_pt;
    }
    if (g_npeers == 0) ack = wall();
    hashtableInitIterator(&iter, g_keys, HASHTABLE_ITER_SAFE);
    while (hashtableNext(&iter, &next)) {
        crdtEntry *e = next;
        uint64_t gc = server.crdt_tombstone_gc_ms > 0 ? (uint64_t)server.crdt_tombstone_gc_ms : 0;
        if (!crdtTombstoneExpired(&e->state, wall(), gc, ack)) continue;
        hashtableDelete(g_keys, e);
        dropped++;
    }
    hashtableCleanupIterator(&iter);
    addReplyLongLong(c, dropped);
}

static void crdtInfoCommand(client *c) {
    int connected = 0, i;
    sds out;
    recountTombstones();
    for (i = 0; i < g_npeers; i++)
        if (g_peers[i].fd >= 0) connected++;
    out = sdscatprintf(sdsempty(), "keys:%zu\r\ntombstones:%d\r\npeers:%d\r\npeers_connected:%d\r\n",
                       g_keys ? hashtableSize(g_keys) : 0, g_tombstones, g_npeers, connected);
    addReplyBulkSds(c, out);
}

static int nameIs(struct serverCommand *cmd, const char *n) {
    if (!cmd || !cmd->fullname) return 0;
    return strcasecmp(cmd->fullname, n) == 0;
}

int crdtCommandRejected(client *c) {
    struct serverCommand *cmd;
    if (!server.crdt_enabled || !c || !c->cmd) return 0;
    cmd = c->cmd;
    if (!(cmd->flags & CMD_WRITE)) return 0;
    if (nameIs(cmd, "set") || nameIs(cmd, "setnx") || nameIs(cmd, "setex") || nameIs(cmd, "psetex") || nameIs(cmd, "mset") ||
        nameIs(cmd, "del") || nameIs(cmd, "unlink") || nameIs(cmd, "incr") || nameIs(cmd, "decr") || nameIs(cmd, "incrby") ||
        nameIs(cmd, "decrby") || nameIs(cmd, "sadd") || nameIs(cmd, "srem") || nameIs(cmd, "hset") || nameIs(cmd, "hmset") ||
        nameIs(cmd, "hdel") || nameIs(cmd, "crdt.apply") || nameIs(cmd, "crdt.gc") || nameIs(cmd, "crdt.info") ||
        nameIs(cmd, "flushall") || nameIs(cmd, "flushdb") || nameIs(cmd, "select") || nameIs(cmd, "ping") ||
        nameIs(cmd, "config") || nameIs(cmd, "debug") || nameIs(cmd, "module") || nameIs(cmd, "replicaof") ||
        nameIs(cmd, "slaveof") || nameIs(cmd, "shutdown") || nameIs(cmd, "bgsave") || nameIs(cmd, "save") ||
        nameIs(cmd, "bgrewriteaof") || nameIs(cmd, "acl") || nameIs(cmd, "command") || nameIs(cmd, "hello") ||
        nameIs(cmd, "auth") || nameIs(cmd, "client") || nameIs(cmd, "info"))
        return 0;
    return 1;
}

static void registerCmd(const char *name, serverCommandProc *proc, int arity, uint64_t flags) {
    struct serverCommand *cmd = zcalloc(sizeof(*cmd));
    cmd->declared_name = name;
    cmd->fullname = sdsnew(name);
    cmd->current_name = cmd->fullname;
    cmd->proc = proc;
    cmd->arity = arity;
    cmd->flags = flags;
    cmd->summary = name;
    hashtableAdd(server.commands, cmd);
    hashtableAdd(server.orig_commands, cmd);
}

void crdtInit(void) {
    registerCmd("crdt.apply", crdtApplyCommand, 3, CMD_WRITE | CMD_DENYOOM | CMD_FAST);
    registerCmd("crdt.gc", crdtGcCommand, 1, CMD_WRITE | CMD_FAST);
    registerCmd("crdt.info", crdtInfoCommand, 1, CMD_READONLY | CMD_FAST);
}

static void closePeer(crdtPeer *p) {
    if (p->fd >= 0) close(p->fd);
    p->fd = -1;
}

static void parsePeers(void) {
    char *copy, *save = NULL, *tok;
    int i;
    sds sig = server.crdt_peers ? sdsnew(server.crdt_peers) : sdsempty();
    if (g_peers_sig && sdscmp(g_peers_sig, sig) == 0) {
        sdsfree(sig);
        return;
    }
    sdsfree(g_peers_sig);
    g_peers_sig = sig;
    for (i = 0; i < g_npeers; i++) {
        closePeer(&g_peers[i]);
        sdsfree(g_peers[i].outbuf);
        g_peers[i].outbuf = NULL;
    }
    g_npeers = 0;
    if (!server.crdt_peers || !server.crdt_peers[0]) return;
    copy = zstrdup(server.crdt_peers);
    for (tok = strtok_r(copy, ",", &save); tok && g_npeers < CRDT_MAX_PEERS; tok = strtok_r(NULL, ",", &save)) {
        char *colon = strrchr(tok, ':');
        crdtPeer *p;
        int port;
        while (*tok == ' ') tok++;
        if (!colon) continue;
        port = atoi(colon + 1);
        if (port <= 0 || port > 65535) continue;
        if ((size_t)(colon - tok) >= sizeof(g_peers[0].host)) continue;
        p = &g_peers[g_npeers++];
        memset(p, 0, sizeof(*p));
        memcpy(p->host, tok, (size_t)(colon - tok));
        p->host[colon - tok] = '\0';
        p->port = port;
        p->fd = -1;
    }
    zfree(copy);
}

static void flushPeers(void) {
    int i;
    char err[ANET_ERR_LEN];
    for (i = 0; i < g_npeers; i++) {
        crdtPeer *p = &g_peers[i];
        ssize_t n;
        char sink[512];
        if (p->fd < 0) {
            p->fd = anetTcpNonBlockConnect(err, p->host, p->port);
            if (p->fd >= 0) anetEnableTcpNoDelay(err, p->fd);
        }
        if (p->fd < 0 || !p->outbuf || sdslen(p->outbuf) == 0) continue;
        n = write(p->fd, p->outbuf, sdslen(p->outbuf));
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINPROGRESS) continue;
            closePeer(p);
            continue;
        }
        if (n > 0) {
            sdsrange(p->outbuf, n, -1);
            p->ack_pt = g_clock.pt;
        }
        while (read(p->fd, sink, sizeof(sink)) > 0) {
        }
    }
}

static void recountTombstones(void) {
    hashtableIterator iter;
    void *next;
    g_tombstones = 0;
    if (!g_keys) return;
    hashtableInitIterator(&iter, g_keys, 0);
    while (hashtableNext(&iter, &next)) {
        crdtEntry *e = next;
        if (e->state.kind == CRDT_KIND_TOMB) g_tombstones++;
    }
    hashtableCleanupIterator(&iter);
}

void crdtCron(void) {
    if (!server.crdt_enabled) return;
    parsePeers();
    flushPeers();
    recountTombstones();
}
