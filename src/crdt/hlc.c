#include "crdt.h"

int hlcCompare(const hlc *a, const hlc *b) {
    if (a->pt != b->pt) return a->pt > b->pt ? 1 : -1;
    if (a->lc != b->lc) return a->lc > b->lc ? 1 : -1;
    if (a->region != b->region) return a->region > b->region ? 1 : -1;
    return 0;
}

void hlcLocalEvent(hlc *h, uint64_t wall_ms, uint16_t region) {
    h->region = region;
    if (wall_ms > h->pt) {
        h->pt = wall_ms;
        h->lc = 0;
    } else {
        h->lc++;
    }
}

void hlcReceive(hlc *h, const hlc *remote, uint64_t wall_ms) {
    uint64_t maxpt = h->pt;
    if (remote->pt > maxpt) maxpt = remote->pt;
    if (wall_ms > maxpt) maxpt = wall_ms;
    if (maxpt == h->pt && maxpt == remote->pt) {
        uint32_t lc = h->lc > remote->lc ? h->lc : remote->lc;
        h->lc = lc + 1;
    } else if (maxpt == h->pt) {
        h->lc++;
    } else if (maxpt == remote->pt) {
        h->lc = remote->lc + 1;
    } else {
        h->lc = 0;
    }
    h->pt = maxpt;
}
