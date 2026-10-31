#ifndef CMO_TPC_H
#define CMO_TPC_H

/* Returns 1 if --engine=tpc was requested. When shards > 1 this does not
 * return: it runs the prototype and exits. When shards == 1 the extra
 * arguments are removed and the caller keeps the stock server. */
int tpcConsumeArgs(int *argc, char ***argv);

#endif
