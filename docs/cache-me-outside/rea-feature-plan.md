# Feature plan from the REA competitor scan (2026-10-31)

Source: GoDeskio/rea-scans `cache-me-outside/FINDINGS.md` (20 targets). Base engine: **Valkey** (confirmed).
Every feature found is planned. Closed or license-incompatible sources (Dragonfly BSL, Aerospike AGPL, Redict LGPL, Redis 8 modules, all managed services) are rebuilt independently from public docs; no code is copied.
The order below is build order, not inclusion. Nothing here is implemented yet.

## Build order (top 10 first)
1. Console: create a DB in one click, connection string, eviction policy picker, fixed-size plans (P1)
2. TLS + per-app ACL users + encryption at rest (P1)
3. Automated off-volume backups with retention (P1)
4. Metrics dashboards: hit rate, memory, ops, latency (P1)
5. Scoped API keys (read-only, expiring) and management API/CLI/Terraform (P2)
6. Multi-tenant isolation + per-tenant rate limits + free tier + spend caps (P2)
7. Online scaling with atomic slot migration and multi-AZ failover (P2)
8. Live import from Redis/ElastiCache, fork-from-backup (P2)
9. Serverless plan with HTTP API and per-request billing (P3)
10. Vector search + semantic LLM cache + MCP server for AI agents (P2/P3)

## Full list

| # | Feature | Seen in | How it works | Status | Phase |
|---|---|---|---|---|---|
| 1 | RESP2/RESP3 Redis-protocol compatibility | Valkey, all engines | Wire-compatible; existing clients work | Include (Valkey) | P1 |
| 2 | Memcached text/meta protocol listener | Dragonfly, Memcached, ElastiCache | Second listener mapped onto string keys | Include (rebuild over Valkey) | P4 |
| 3 | Core data types (string/hash/list/set/zset/stream/geo/HLL/bitmap) | Valkey | Native | Include | P1 |
| 4 | JSON documents | Redis Cloud, Valkey-json, MemoryDB | valkey-json module (BSD) | Include | P2 |
| 5 | Bloom/probabilistic filters (bloom, cuckoo, top-k, CMS) | Redis Cloud, valkey-bloom | valkey-bloom (BSD); others rebuild | Include | P2 |
| 6 | Time series type | Redis Cloud | Rebuild as module (RedisTimeSeries not BSD) | Include (rebuild) | P4 |
| 7 | Field-level hash expiry (HEXPIRE) / EXPIREMEMBER | Valkey 9, KeyDB | Per-field TTL | Include | P1 |
| 8 | Lua scripting + Functions | Valkey | Native | Include | P1 |
| 9 | Custom server-side procedures | Garnet, Hazelcast entry processors | Valkey modules API, sandboxed | Include | P4 |
| 10 | RDB snapshots | Valkey | Native | Include | P1 |
| 11 | AOF everysec | Valkey | Native (already on) | Include | P1 |
| 12 | Forkless snapshots | Dragonfly (BSL), Garnet | Incremental per-shard snapshot w/o fork | Include (rebuild) | P4 |
| 13 | Durable multi-AZ transaction log (DB-grade durability) | MemoryDB | Ack writes after log quorum | Include (rebuild) | P4 |
| 14 | Async replication + read replicas | Valkey, all managed | Native | Include | P1 |
| 15 | Sentinel automatic failover | Valkey | Native (shipped `up.sh sentinel`) | Include | P1 |
| 16 | Cluster sharding, 16384 slots | Valkey | Native (shipped) | Include | P1 |
| 17 | Atomic slot migration / zero-downtime resharding | Valkey 9, Memorystore | Native | Include | P2 |
| 18 | Online vertical/horizontal scaling from console | ElastiCache, Memorystore, Aiven, DO | Orchestrator adds node, migrates slots | Include | P2 |
| 19 | Multi-AZ placement + auto-failover SLA | ElastiCache, Azure, Redis Cloud | Spread replicas across zones/hosts | Include | P2 |
| 20 | Active-active multi-master (CRDT) | Redis Cloud (closed), Azure, KeyDB (BSD) | Conflict-free merges per type | Include (rebuild; KeyDB ideas BSD) | P4 |
| 21 | Global datastore / cross-region read replicas | ElastiCache, Memorystore, Upstash | Primary region + async replica regions | Include | P3 |
| 22 | I/O threads / multi-core | Valkey 8, KeyDB, Dragonfly, Garnet | Valkey io-threads; tune via bench | Include | P1 |
| 23 | Shared-nothing thread-per-core engine | Dragonfly (BSL), Garnet | Rebuild later only if bench justifies | Include (rebuild, research) | P4 |
| 24 | SSD/flash data tiering | Redis on Flash, ElastiCache r6gd, Dragonfly, KeyDB FLASH, Memcached extstore, Aerospike | Cold values on NVMe, keys in RAM | Include (rebuild; extstore/KeyDB ideas BSD) | P4 |
| 25 | Disk-first Redis-compatible tier (bigger than RAM) | Pika, Kvrocks | Offer Kvrocks-backed plan (Apache-2.0) | Include | P4 |
| 26 | Cloud object-storage tier | Garnet | Spill checkpoints to S3/R2 | Include | P4 |
| 27 | TLS in transit (+ mTLS) | all | BUILD_TLS=yes | Include | P1 |
| 28 | ACL users per app, key/command patterns | Valkey, all managed | Native; per-app users (roadmap #3) | Include | P1 |
| 29 | Encryption at rest | all managed | Encrypted volumes + Encryptoglyph-managed keys | Include | P1 |
| 30 | Customer-managed keys (BYOK) | ElastiCache, Azure, Memorystore | KMS key per tenant via Encryptoglyph | Include | P3 |
| 31 | IAM/OIDC token auth (no static passwords) | ElastiCache, Memorystore, Azure Entra | Short-lived tokens → ACL user | Include | P3 |
| 32 | Private networking (VPC peering / PrivateLink / PSC) | all managed | WireGuard/peering per tenant | Include | P3 |
| 33 | IP allow-list / trusted sources | DO, Aiven, Upstash | Firewall per DB | Include | P2 |
| 34 | Audit log of admin + ACL denials | Redis Cloud, Azure | ACL LOG shipper → SIEM (roadmap #5) | Include | P2 |
| 35 | SSO/SAML + RBAC for console | Redis Cloud, Aiven | Team roles | Include | P3 |
| 36 | Compliance pack (SOC2/HIPAA controls) | managed vendors | Process + evidence | Include | P4 |
| 37 | Multi-tenant isolation (DB per tenant, namespaces) | Upstash, Momento, Kvrocks namespaces | Container/VM per DB; namespace tokens for small plans | Include | P2 |
| 38 | Noisy-neighbor limits (ops/s, conn, bandwidth) | Upstash, Momento | Per-tenant rate limits at proxy | Include | P2 |
| 39 | Serverless (no node sizing, auto-scale) | ElastiCache Serverless, Upstash, Momento | Proxy + pooled cluster, slot rebalancing | Include (rebuild) | P3 |
| 40 | Per-request / per-GB billing | Upstash, Momento, ElastiCache ECPU, Workers KV | Metering at proxy → Stripe usage records | Include | P3 |
| 41 | Fixed-size node plans | DO, Aiven, Redis Cloud | Simple monthly price per size | Include | P1 |
| 42 | Free tier | Upstash, Redis Cloud, Momento, Workers KV | Small shared DB, no card | Include | P2 |
| 43 | Reserved/committed-use discount | ElastiCache, Azure | 1-3yr commit pricing | Include | P3 |
| 44 | Budget caps / spend alerts | Upstash | Hard cap stops overage | Include | P2 |
| 45 | HTTP/REST API for edge & serverless | Upstash, Momento, Workers KV | HTTPS → command proxy | Include (rebuild) | P3 |
| 46 | Edge read cache / global edge reads | Workers KV, Upstash global | Read-through edge nodes, eventual consistency | Include (rebuild) | P3 |
| 47 | Eviction policy picker (LRU/LFU/TTL/noeviction) | Valkey, DO, all | maxmemory-policy in console | Include | P1 |
| 48 | Cache-optimized eviction mode | Dragonfly cache mode, Memcached LRU crawler | Better hit ratio under pressure | Include (rebuild) | P4 |
| 49 | Client-side caching / near cache | Valkey tracking, Hazelcast near cache | RESP3 CLIENT TRACKING + SDK helper | Include | P3 |
| 50 | Metrics dashboards (hit rate, mem, ops, latency) | all managed | Exporter → Prometheus/Grafana in console | Include | P1 |
| 51 | Slowlog / latency monitor / hot & big keys | Valkey, Azure, Redis Cloud | Console views over SLOWLOG/LATENCY/--hotkeys | Include | P2 |
| 52 | Alerts (memory, evictions, failover) | all managed | Alert rules → email/Slack/webhook | Include | P2 |
| 53 | Metrics/log export integrations (Datadog, OTel) | Aiven, Redis Cloud | OTLP export | Include | P3 |
| 54 | Automated daily backups + retention | all managed | Off-volume RDB/AOF copies (roadmap #2/#9) | Include | P1 |
| 55 | Point-in-time restore | MemoryDB, Redis Cloud | AOF replay to timestamp | Include | P3 |
| 56 | Fork/clone DB from backup | Aiven | Restore into new DB | Include | P2 |
| 57 | Import/migration from Redis/ElastiCache (live) | Redis Cloud, Memorystore, Aiven | REPLICAOF/RIOT-style sync tool | Include | P2 |
| 58 | Export backup to customer bucket | ElastiCache, Redis Cloud | RDB to S3/R2 | Include | P2 |
| 59 | Official SDKs + recipes | Momento, Upstash | Thin wrappers over valkey-glide (Apache-2.0) | Include | P2 |
| 60 | Ratelimit / session / lock / leaderboard helpers | Upstash ratelimit, Momento | SDK recipes | Include | P2 |
| 61 | Web console: create DB in 1 click, connect strings | DO, Upstash, Aiven | Console wizard | Include | P1 |
| 62 | In-browser data browser + CLI | Upstash, Redis Insight | Key explorer, eye toggle on secrets | Include | P2 |
| 63 | API keys: scoped, read-only, expiring, disposable | Upstash, Momento | Token service → ACL users | Include | P2 |
| 64 | Management REST API + Terraform provider + CLI | all managed | OpenAPI + TF provider | Include | P2 |
| 65 | Pub/Sub + sharded pub/sub | Valkey | Native | Include | P1 |
| 66 | Managed topics / webhooks on key events | Momento Topics, Upstash QStash | Keyspace notifications → webhooks | Include (rebuild) | P3 |
| 67 | Write-through / write-behind to databases | Hazelcast, Ignite | Connector workers (Postgres/Mongo) | Include | P4 |
| 68 | SQL query over cached data | Ignite, Hazelcast | Rebuild via search module | Include (rebuild) | P4 |
| 69 | Secondary indexes / full-text search | Redis Search, Aerospike, Kvrocks | valkey-search (BSD) | Include | P3 |
| 70 | Vector search (KNN, HNSW) | valkey-search, MemoryDB, Memorystore, Redis Cloud, Aerospike | valkey-search | Include | P3 |
| 71 | Semantic LLM cache | Redis LangCache, Upstash semantic-cache | Embedding + vector lookup, TTL | Include (rebuild) | P3 |
| 72 | AI agent memory / MCP server | Redis MCP, Upstash MCP | MCP server over management + data API | Include | P2 |
| 73 | Strong consistency mode | Aerospike SC, Hazelcast CP | WAIT/WAITAOF + quorum writes option | Include (rebuild) | P4 |
| 74 | Kubernetes operator | Redis Enterprise, Dragonfly operator | Helm shipped; operator later | Include | P3 |
| 75 | Uptime SLA tiers (99.9 → 99.999) | Redis Cloud, ElastiCache | Topology-backed SLAs | Include | P3 |
| 76 | Upgrade management / maintenance windows | all managed | Rolling replica-first upgrades | Include | P2 |
| 77 | RDMA transport | Valkey (experimental) | Native build flag | Include (experimental) | P4 |
