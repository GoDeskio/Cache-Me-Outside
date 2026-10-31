# Thread-per-core prototype: benchmark and go / no-go

This is a research spike. It is not a production engine. The question is whether a shared-nothing shard-per-core loop beats the stock Valkey server with its I/O threads on this machine. Nothing in the prototype was taken from Dragonfly or Garnet.

## What was built

`valkey-server --engine=tpc --tpc-shards N`

- `N=1` strips `--engine=tpc` and keeps the stock command path. Every slot stays on the one core that already runs the server. The type suites were run in this mode (1327 passed). A normal `make test` does not pass the flag; the argument scan is a no-op and the stock engine is unchanged (5889 passed, 0 failed).
- `N>1` replaces the process with `src/tpc/tpc.c`. Each shard owns a private hash table and a request queue. The acceptor reads clients and passes `GET`, `SET`, `DEL`, `MGET`, and `MULTI`/`EXEC` to the owning shard. Cross-shard commands are one message per key, waited on in shard order.

Sharding uses a local FNV-1a hash modulo 16384 slots, then modulo the shard count. It is not the cluster slot table.

## How it was measured

The host has 4 cores. Runs at 16 and 64 cores were not possible here. `memtier_benchmark` is not installed; the numbers below are from `valkey-benchmark` (40,000 requests, 16 clients, 32-byte values), which is the same GET and SET workload shape. Separate SET and GET passes stand in for a mixed 1:10 ratio. Pipeline depth is `-P`.

Stock is `valkey-server` with `io-threads 1`, the current default.

| Engine | Pipeline | SET req/s | GET req/s | SET p99 ms | GET p99 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stock, 1 I/O thread | 1 | 167,364 | 166,667 | 0.071 | 0.079 |
| Stock, 1 I/O thread | 16 | 1,290,323 | 1,600,000 | 0.375 | 0.207 |
| TPC, 2 shards | 1 | 136,054 | 139,860 | 0.111 | 0.103 |
| TPC, 2 shards | 16 | 5,767 | 5,798 | 0.807 | 0.975 |
| TPC, 4 shards | 1 | 139,373 | 141,343 | 0.143 | 0.111 |
| TPC, 4 shards | 16 | 5,778 | 5,785 | 0.823 | 1.031 |

Adding shards did not raise throughput. At pipeline 1 the prototype is about 80% of stock. At pipeline 16 it is under 1% of stock.

## Why

The stock server runs the command on the thread that already owns the data. The prototype posts every command onto a mutex and condition variable and waits. That handshake is more expensive than the GET itself, and it serializes the pipeline: the acceptor does not overlap the next request with the shard. More shards add more queues and do not remove the handshake.

A production thread-per-core engine would have to run the command inside the shard thread, with the client socket owned by that shard, and would have to pipeline without a round trip per key. That is a different server than this spike.

## Decision

**No-go.** Do not replace the stock engine with this prototype. Keep `--engine=tpc --tpc-shards 1` as the stock path, and keep the multi-shard binary only as a measurement harness. Revisit only if a later design puts the command path on the shard thread and beats the table above on pipelined GET/SET.
