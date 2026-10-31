/* Shared-nothing thread-per-core prototype.
 *
 * This is a research spike, not a production engine. Each shard owns a
 * private hash table and a request queue. The acceptor reads clients and
 * passes GET/SET/DEL/MGET/MULTI to the owning shard over that queue.
 * One shard (the default) does not enter this file's event loop: main()
 * keeps the stock Valkey engine so the existing test suite still applies.
 *
 * The design is from the shard-per-core description in the brief. No
 * Dragonfly or Garnet source was used.
 *
 * Copyright (c) 2026, Cache Me Outside contributors.
 * Licensed under the BSD 3-Clause License, the same terms as the server.
 */
#include "tpc/tpc.h"

#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#define TPC_SLOTS 16384
#define TPC_TABLE 4096

typedef struct tpc_item {
    char *key;
    int klen;
    char *val;
    int vlen;
    struct tpc_item *next;
} tpc_item;

typedef struct tpc_job {
    int op; /* 1 get, 2 set, 3 del, 4 dbsize */
    char *key;
    int klen;
    char *val;
    int vlen;
    char *reply;
    int rlen;
    int found;
    int done;
    pthread_mutex_t mu;
    pthread_cond_t cv;
    struct tpc_job *next;
} tpc_job;

typedef struct tpc_shard {
    int id;
    pthread_t thread;
    pthread_mutex_t mu;
    pthread_cond_t cv;
    tpc_job *head, *tail;
    tpc_item *table[TPC_TABLE];
    int nkeys;
    int stop;
} tpc_shard;

static tpc_shard *shards;
static int nshards;
static int listen_port = 6379;

static unsigned tpc_hash(const char *s, int n) {
    unsigned h = 2166136261u;
    int i;
    for (i = 0; i < n; i++) {
        h ^= (unsigned char)s[i];
        h *= 16777619u;
    }
    return h;
}

static int tpc_slot(const char *s, int n) {
    return (int)(tpc_hash(s, n) % TPC_SLOTS);
}

static int tpc_shard_of(const char *s, int n) {
    return tpc_slot(s, n) % nshards;
}

static tpc_item *tpc_find(tpc_shard *sh, const char *key, int klen, tpc_item ***prev) {
    unsigned b = tpc_hash(key, klen) % TPC_TABLE;
    tpc_item **p = &sh->table[b];
    while (*p) {
        if ((*p)->klen == klen && memcmp((*p)->key, key, (size_t)klen) == 0) {
            if (prev) *prev = p;
            return *p;
        }
        p = &(*p)->next;
    }
    if (prev) *prev = p;
    return NULL;
}

static void job_init(tpc_job *j) {
    memset(j, 0, sizeof(*j));
    pthread_mutex_init(&j->mu, NULL);
    pthread_cond_init(&j->cv, NULL);
}

static void job_finish_wait(tpc_job *j) {
    pthread_mutex_lock(&j->mu);
    while (!j->done) pthread_cond_wait(&j->cv, &j->mu);
    pthread_mutex_unlock(&j->mu);
}

static void shard_post(tpc_shard *sh, tpc_job *j) {
    pthread_mutex_lock(&sh->mu);
    if (sh->tail)
        sh->tail->next = j;
    else
        sh->head = j;
    sh->tail = j;
    j->next = NULL;
    pthread_cond_signal(&sh->cv);
    pthread_mutex_unlock(&sh->mu);
    job_finish_wait(j);
}

static void shard_exec(tpc_shard *sh, tpc_job *j) {
    tpc_item **prev = NULL;
    tpc_item *it = NULL;
    if (j->op == 4) {
        j->found = sh->nkeys;
        return;
    }
    it = tpc_find(sh, j->key, j->klen, &prev);
    if (j->op == 1) {
        if (it) {
            j->reply = malloc((size_t)it->vlen + 1);
            memcpy(j->reply, it->val, (size_t)it->vlen);
            j->rlen = it->vlen;
            j->found = 1;
        }
    } else if (j->op == 2) {
        if (!it) {
            it = calloc(1, sizeof(*it));
            it->key = malloc((size_t)j->klen + 1);
            memcpy(it->key, j->key, (size_t)j->klen);
            it->klen = j->klen;
            *prev = it;
            sh->nkeys++;
        } else {
            free(it->val);
        }
        it->val = malloc((size_t)j->vlen + 1);
        memcpy(it->val, j->val, (size_t)j->vlen);
        it->vlen = j->vlen;
        j->found = 1;
    } else if (j->op == 3) {
        if (it) {
            *prev = it->next;
            free(it->key);
            free(it->val);
            free(it);
            sh->nkeys--;
            j->found = 1;
        }
    }
}

static void *shard_main(void *arg) {
    tpc_shard *sh = arg;
    for (;;) {
        tpc_job *j;
        pthread_mutex_lock(&sh->mu);
        while (!sh->head && !sh->stop) pthread_cond_wait(&sh->cv, &sh->mu);
        if (sh->stop && !sh->head) {
            pthread_mutex_unlock(&sh->mu);
            break;
        }
        j = sh->head;
        sh->head = j->next;
        if (!sh->head) sh->tail = NULL;
        pthread_mutex_unlock(&sh->mu);
        shard_exec(sh, j);
        pthread_mutex_lock(&j->mu);
        j->done = 1;
        pthread_cond_signal(&j->cv);
        pthread_mutex_unlock(&j->mu);
    }
    return NULL;
}

static int append_buf(char **buf, int *len, int *cap, const char *s, int n) {
    if (*len + n + 1 > *cap) {
        int ncap = *cap ? *cap * 2 : 1024;
        while (ncap < *len + n + 1) ncap *= 2;
        *buf = realloc(*buf, (size_t)ncap);
        *cap = ncap;
    }
    memcpy(*buf + *len, s, (size_t)n);
    *len += n;
    (*buf)[*len] = 0;
    return 0;
}

static int reply_bulk(char **buf, int *len, int *cap, const char *s, int n) {
    char hdr[64];
    int h = snprintf(hdr, sizeof(hdr), "$%d\r\n", n);
    append_buf(buf, len, cap, hdr, h);
    append_buf(buf, len, cap, s, n);
    append_buf(buf, len, cap, "\r\n", 2);
    return 0;
}

static int reply_simple(char **buf, int *len, int *cap, const char *s) {
    append_buf(buf, len, cap, "+", 1);
    append_buf(buf, len, cap, s, (int)strlen(s));
    append_buf(buf, len, cap, "\r\n", 2);
    return 0;
}

static int reply_int(char **buf, int *len, int *cap, long long v) {
    char hdr[64];
    int h = snprintf(hdr, sizeof(hdr), ":%lld\r\n", v);
    append_buf(buf, len, cap, hdr, h);
    return 0;
}

static int reply_null(char **buf, int *len, int *cap) {
    append_buf(buf, len, cap, "$-1\r\n", 5);
    return 0;
}

static int reply_err(char **buf, int *len, int *cap, const char *s) {
    append_buf(buf, len, cap, "-", 1);
    append_buf(buf, len, cap, s, (int)strlen(s));
    append_buf(buf, len, cap, "\r\n", 2);
    return 0;
}

/* Parse one RESP array from buf. Returns bytes consumed, 0 if incomplete, -1 on error.
 * argv is malloc'd strings. */
static int parse_resp(const char *buf, int len, int *argc, char ***argv, int **argl) {
    const char *p = buf;
    const char *end = buf + len;
    int i, n;
    if (len < 4 || *p != '*') return 0;
    p++;
    n = 0;
    while (p < end && *p != '\r') {
        if (!isdigit((unsigned char)*p)) return -1;
        n = n * 10 + (*p - '0');
        p++;
    }
    if (p + 1 >= end || p[0] != '\r' || p[1] != '\n') return 0;
    p += 2;
    *argc = n;
    *argv = calloc((size_t)n, sizeof(char *));
    *argl = calloc((size_t)n, sizeof(int));
    for (i = 0; i < n; i++) {
        int blen = 0;
        if (p >= end) {
            *argc = 0;
            free(*argv);
            free(*argl);
            return 0;
        }
        if (*p != '$') return -1;
        p++;
        while (p < end && *p != '\r') {
            if (!isdigit((unsigned char)*p)) return -1;
            blen = blen * 10 + (*p - '0');
            p++;
        }
        if (p + 1 >= end || p[0] != '\r' || p[1] != '\n') {
            free(*argv);
            free(*argl);
            return 0;
        }
        p += 2;
        if (end - p < blen + 2) {
            free(*argv);
            free(*argl);
            return 0;
        }
        (*argv)[i] = malloc((size_t)blen + 1);
        memcpy((*argv)[i], p, (size_t)blen);
        (*argv)[i][blen] = 0;
        (*argl)[i] = blen;
        p += blen + 2;
    }
    return (int)(p - buf);
}

static void free_args(int argc, char **argv, int *argl) {
    int i;
    for (i = 0; i < argc; i++) free(argv[i]);
    free(argv);
    free(argl);
}

static int cmd_is(const char *s, const char *name) {
    return strcasecmp(s, name) == 0;
}

static void exec_one(int argc, char **argv, int *argl, char **out, int *olen, int *ocap) {
    if (argc < 1) return;
    if (cmd_is(argv[0], "PING")) {
        reply_simple(out, olen, ocap, argc >= 2 ? argv[1] : "PONG");
    } else if (cmd_is(argv[0], "GET") && argc == 2) {
        tpc_job j;
        job_init(&j);
        j.op = 1;
        j.key = argv[1];
        j.klen = argl[1];
        shard_post(&shards[tpc_shard_of(j.key, j.klen)], &j);
        if (j.found)
            reply_bulk(out, olen, ocap, j.reply, j.rlen);
        else
            reply_null(out, olen, ocap);
        free(j.reply);
        pthread_mutex_destroy(&j.mu);
        pthread_cond_destroy(&j.cv);
    } else if (cmd_is(argv[0], "SET") && argc >= 3) {
        tpc_job j;
        job_init(&j);
        j.op = 2;
        j.key = argv[1];
        j.klen = argl[1];
        j.val = argv[2];
        j.vlen = argl[2];
        shard_post(&shards[tpc_shard_of(j.key, j.klen)], &j);
        reply_simple(out, olen, ocap, "OK");
        pthread_mutex_destroy(&j.mu);
        pthread_cond_destroy(&j.cv);
    } else if (cmd_is(argv[0], "DEL") && argc == 2) {
        tpc_job j;
        job_init(&j);
        j.op = 3;
        j.key = argv[1];
        j.klen = argl[1];
        shard_post(&shards[tpc_shard_of(j.key, j.klen)], &j);
        reply_int(out, olen, ocap, j.found ? 1 : 0);
        pthread_mutex_destroy(&j.mu);
        pthread_cond_destroy(&j.cv);
    } else if (cmd_is(argv[0], "MGET") && argc >= 2) {
        int i;
        char hdr[32];
        int h = snprintf(hdr, sizeof(hdr), "*%d\r\n", argc - 1);
        append_buf(out, olen, ocap, hdr, h);
        for (i = 1; i < argc; i++) {
            tpc_job j;
            job_init(&j);
            j.op = 1;
            j.key = argv[i];
            j.klen = argl[i];
            shard_post(&shards[tpc_shard_of(j.key, j.klen)], &j);
            if (j.found)
                reply_bulk(out, olen, ocap, j.reply, j.rlen);
            else
                reply_null(out, olen, ocap);
            free(j.reply);
            pthread_mutex_destroy(&j.mu);
            pthread_cond_destroy(&j.cv);
        }
    } else if (cmd_is(argv[0], "DBSIZE")) {
        int i, total = 0;
        for (i = 0; i < nshards; i++) {
            tpc_job j;
            job_init(&j);
            j.op = 4;
            shard_post(&shards[i], &j);
            total += j.found;
            pthread_mutex_destroy(&j.mu);
            pthread_cond_destroy(&j.cv);
        }
        reply_int(out, olen, ocap, total);
    } else if (cmd_is(argv[0], "INFO")) {
        char body[256];
        int n = snprintf(body, sizeof(body), "engine:tpc\r\nshards:%d\r\nslots:%d\r\n", nshards, TPC_SLOTS);
        reply_bulk(out, olen, ocap, body, n);
    } else if (cmd_is(argv[0], "COMMAND")) {
        reply_simple(out, olen, ocap, "OK");
    } else {
        reply_err(out, olen, ocap, "ERR unknown command in tpc prototype");
    }
}

typedef struct queued_cmd {
    int argc;
    char **argv;
    int *argl;
    struct queued_cmd *next;
} queued_cmd;

static void handle_client(int fd) {
    char *in = NULL;
    int inlen = 0, incap = 0;
    int multi = 0;
    queued_cmd *qhead = NULL, *qtail = NULL;
    for (;;) {
        char tmp[4096];
        int n = (int)read(fd, tmp, sizeof(tmp));
        int consumed = 0;
        if (n == 0) break;
        if (n < 0) {
            if (errno == EINTR) continue;
            break;
        }
        append_buf(&in, &inlen, &incap, tmp, n);
        while (consumed < inlen) {
            int argc = 0;
            char **argv = NULL;
            int *argl = NULL;
            int used = parse_resp(in + consumed, inlen - consumed, &argc, &argv, &argl);
            char *out = NULL;
            int olen = 0, ocap = 0;
            if (used == 0) break;
            if (used < 0) {
                reply_err(&out, &olen, &ocap, "ERR protocol error");
                if (olen) write(fd, out, (size_t)olen);
                free(out);
                free(in);
                return;
            }
            consumed += used;
            if (argc >= 1 && cmd_is(argv[0], "MULTI")) {
                multi = 1;
                reply_simple(&out, &olen, &ocap, "OK");
                free_args(argc, argv, argl);
            } else if (argc >= 1 && cmd_is(argv[0], "EXEC")) {
                char hdr[32];
                int count = 0;
                queued_cmd *q;
                for (q = qhead; q; q = q->next) count++;
                {
                    int h = snprintf(hdr, sizeof(hdr), "*%d\r\n", count);
                    append_buf(&out, &olen, &ocap, hdr, h);
                }
                while (qhead) {
                    q = qhead;
                    qhead = q->next;
                    exec_one(q->argc, q->argv, q->argl, &out, &olen, &ocap);
                    free_args(q->argc, q->argv, q->argl);
                    free(q);
                }
                qtail = NULL;
                multi = 0;
                free_args(argc, argv, argl);
            } else if (argc >= 1 && cmd_is(argv[0], "DISCARD")) {
                while (qhead) {
                    queued_cmd *q = qhead;
                    qhead = q->next;
                    free_args(q->argc, q->argv, q->argl);
                    free(q);
                }
                qtail = NULL;
                multi = 0;
                reply_simple(&out, &olen, &ocap, "OK");
                free_args(argc, argv, argl);
            } else if (multi) {
                queued_cmd *q = calloc(1, sizeof(*q));
                q->argc = argc;
                q->argv = argv;
                q->argl = argl;
                if (qtail)
                    qtail->next = q;
                else
                    qhead = q;
                qtail = q;
                reply_simple(&out, &olen, &ocap, "QUEUED");
            } else {
                exec_one(argc, argv, argl, &out, &olen, &ocap);
                free_args(argc, argv, argl);
            }
            if (olen) {
                int off = 0;
                while (off < olen) {
                    int w = (int)write(fd, out + off, (size_t)(olen - off));
                    if (w <= 0) break;
                    off += w;
                }
            }
            free(out);
        }
        if (consumed > 0) {
            memmove(in, in + consumed, (size_t)(inlen - consumed));
            inlen -= consumed;
        }
    }
    free(in);
    close(fd);
}

static void *client_thread(void *arg) {
    int fd = *(int *)arg;
    free(arg);
    handle_client(fd);
    return NULL;
}

static void tpc_run_clients(int shards_n, int port) {
    int i, lfd, opt = 1;
    struct sockaddr_in addr;
    nshards = shards_n;
    listen_port = port;
    shards = calloc((size_t)nshards, sizeof(*shards));
    for (i = 0; i < nshards; i++) {
        shards[i].id = i;
        pthread_mutex_init(&shards[i].mu, NULL);
        pthread_cond_init(&shards[i].cv, NULL);
        pthread_create(&shards[i].thread, NULL, shard_main, &shards[i]);
    }
    lfd = socket(AF_INET, SOCK_STREAM, 0);
    setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(lfd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        perror("tpc bind");
        exit(1);
    }
    listen(lfd, 512);
    fprintf(stderr, "TPC prototype listening on 127.0.0.1:%d with %d shards\n", port, nshards);
    for (;;) {
        int cfd = accept(lfd, NULL, NULL);
        pthread_t th;
        int *fd;
        if (cfd < 0) continue;
        fd = malloc(sizeof(int));
        *fd = cfd;
        pthread_create(&th, NULL, client_thread, fd);
        pthread_detach(th);
    }
}

int tpcConsumeArgs(int *argc, char ***argvp) {
    char **av = *argvp;
    int i, w = 1, shards_n = 1, engine = 0, port = 6379;
    for (i = 1; i < *argc; i++) {
        if (!strcmp(av[i], "--engine=tpc")) {
            engine = 1;
            continue;
        }
        if (!strcmp(av[i], "--engine") && i + 1 < *argc && !strcmp(av[i + 1], "tpc")) {
            engine = 1;
            i++;
            continue;
        }
        if (!strncmp(av[i], "--tpc-shards=", 13)) {
            shards_n = atoi(av[i] + 13);
            continue;
        }
        if (!strcmp(av[i], "--tpc-shards") && i + 1 < *argc) {
            shards_n = atoi(av[++i]);
            continue;
        }
        if (!strcmp(av[i], "--port") && i + 1 < *argc) port = atoi(av[i + 1]);
        av[w++] = av[i];
    }
    av[w] = NULL;
    *argc = w;
    if (engine && shards_n > 1) {
        if (shards_n > 256) shards_n = 256;
        tpc_run_clients(shards_n, port);
        exit(0);
    }
    return engine && shards_n <= 1;
}
