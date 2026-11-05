/* Randomized checks that merge is commutative, associative, and idempotent,
 * plus hybrid-clock skew and tombstone GC. */
#include "crdt.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;

static void expect(int cond, const char *msg) {
    if (!cond) {
        fprintf(stderr, "FAIL %s\n", msg);
        failures++;
    }
}

static uint64_t rng = 0x123456789abcdefULL;
static uint64_t rnd(void) {
    rng = rng * 6364136223846793005ULL + 1ULL;
    return rng;
}

static void randomOp(crdtState *s, hlc *clock, uint16_t region, uint64_t wall) {
    int op = (int)(rnd() % 7);
    char member[8];
    member[0] = 'a' + (char)(rnd() % 5);
    member[1] = '\0';
    if (op == 0) crdtStringSet(s, clock, wall, region, member, 1);
    else if (op == 1) crdtCounterAdd(s, clock, wall, region, (int64_t)(rnd() % 5) - 1);
    else if (op == 2) crdtSetAdd(s, clock, wall, region, member, 1);
    else if (op == 3) crdtSetRemove(s, clock, wall, region, member, 1);
    else if (op == 4) crdtHashSet(s, clock, wall, region, member, 1, "v", 1);
    else if (op == 5) crdtHashDel(s, clock, wall, region, member, 1);
    else crdtTombstone(s, clock, wall, region);
}

int main(void) {
    int trial;
    hlc zero;
    memset(&zero, 0, sizeof(zero));

    /* Clock does not move backwards when the wall clock does. */
    {
        hlc h;
        memset(&h, 0, sizeof(h));
        hlcLocalEvent(&h, 1000, 1);
        hlcLocalEvent(&h, 500, 1);
        expect(h.pt == 1000 && h.lc == 1, "local clock resists skew");
        hlc remote = h;
        remote.pt = 2000;
        remote.lc = 3;
        remote.region = 2;
        hlcReceive(&h, &remote, 100);
        expect(h.pt == 2000 && h.lc == 4, "receive keeps the max physical time");
    }

    for (trial = 0; trial < 200; trial++) {
        crdtState a, b, c, ab, ba, ab_c, bc, a_bc, aa;
        hlc ca, cb, cc;
        int step;
        memset(&ca, 0, sizeof(ca));
        memset(&cb, 0, sizeof(cb));
        memset(&cc, 0, sizeof(cc));
        crdtStateInit(&a);
        crdtStateInit(&b);
        crdtStateInit(&c);
        for (step = 0; step < 8; step++) {
            randomOp(&a, &ca, 1, 1000 + (rnd() % 50));
            randomOp(&b, &cb, 2, 1000 + (rnd() % 80));
            randomOp(&c, &cc, 3, 900 + (rnd() % 200));
        }
        crdtStateInit(&ab);
        crdtStateInit(&ba);
        crdtStateCopy(&ab, &a);
        crdtStateCopy(&ba, &b);
        crdtMerge(&ab, &b);
        crdtMerge(&ba, &a);
        expect(crdtStateEqual(&ab, &ba), "commutative");

        crdtStateInit(&aa);
        crdtStateCopy(&aa, &ab);
        crdtMerge(&aa, &b);
        crdtMerge(&aa, &a);
        expect(crdtStateEqual(&aa, &ab), "idempotent");

        crdtStateInit(&ab_c);
        crdtStateCopy(&ab_c, &ab);
        crdtMerge(&ab_c, &c);
        crdtStateInit(&bc);
        crdtStateCopy(&bc, &b);
        crdtMerge(&bc, &c);
        crdtStateInit(&a_bc);
        crdtStateCopy(&a_bc, &a);
        crdtMerge(&a_bc, &bc);
        expect(crdtStateEqual(&ab_c, &a_bc), "associative");

        crdtStateClear(&a);
        crdtStateClear(&b);
        crdtStateClear(&c);
        crdtStateClear(&ab);
        crdtStateClear(&ba);
        crdtStateClear(&ab_c);
        crdtStateClear(&bc);
        crdtStateClear(&a_bc);
        crdtStateClear(&aa);
    }

    {
        crdtState one, dec;
        hlc c;
        size_t n = 0;
        char *buf;
        memset(&c, 0, sizeof(c));
        crdtStateInit(&one);
        crdtStringSet(&one, &c, 50, 1, "hello", 5);
        crdtCounterAdd(&one, &c, 60, 1, 3);
        buf = crdtEncode(&one, &n);
        expect(crdtDecode(&dec, buf, n) == 0, "decode visible counter");
        expect(dec.kind == CRDT_KIND_COUNTER && crdtCounterValue(&dec) == 3, "visible value survived encode");
        crdtStateClear(&one);
        crdtStateClear(&dec);
        free(buf);
    }

    /* PN-counter: concurrent +1 and +1 is 2, in either order. */
    {
        crdtState a, b;
        hlc ca, cb;
        memset(&ca, 0, sizeof(ca));
        memset(&cb, 0, sizeof(cb));
        crdtStateInit(&a);
        crdtStateInit(&b);
        crdtCounterAdd(&a, &ca, 10, 1, 1);
        crdtCounterAdd(&b, &cb, 10, 2, 1);
        crdtMerge(&a, &b);
        expect(crdtCounterValue(&a) == 2, "pn counter converges to 2");
        crdtMerge(&a, &b);
        expect(crdtCounterValue(&a) == 2, "pn counter merge is idempotent");
        crdtStateClear(&a);
        crdtStateClear(&b);
    }

    /* OR-set: add on one side, remove on the other after both observed the add. */
    {
        crdtState a, b;
        hlc ca, cb;
        memset(&ca, 0, sizeof(ca));
        memset(&cb, 0, sizeof(cb));
        crdtStateInit(&a);
        crdtStateInit(&b);
        crdtSetAdd(&a, &ca, 10, 1, "x", 1);
        crdtStateCopy(&b, &a);
        cb = ca;
        crdtSetRemove(&a, &ca, 20, 1, "x", 1);
        crdtSetAdd(&b, &cb, 20, 2, "x", 1);
        crdtMerge(&a, &b);
        /* Remove observed the first tag; B added a fresh tag. Element stays. */
        expect(crdtSetContains(&a, "x", 1) == 1, "or-set concurrent add wins over observed remove");
        crdtStateClear(&a);
        crdtStateClear(&b);
    }

    /* Tombstone GC waits for peer acknowledgement. */
    {
        crdtState s;
        hlc c;
        memset(&c, 0, sizeof(c));
        crdtStateInit(&s);
        crdtStringSet(&s, &c, 1000, 1, "z", 1);
        crdtTombstone(&s, &c, 5000, 1);
        expect(crdtTombstoneExpired(&s, 9000, 1000, 1000) == 0, "gc waits for ack");
        expect(crdtTombstoneExpired(&s, 9000, 1000, 5000) == 1, "gc after ack and age");
        crdtStateClear(&s);
    }

    if (failures) {
        fprintf(stderr, "%d failure(s)\n", failures);
        return 1;
    }
    printf("OK\n");
    return 0;
}
