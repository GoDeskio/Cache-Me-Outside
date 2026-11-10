# DDR3 network-RAM tier

**Status: PARKED / possibility.** This is a research spec, not a shipping feature and not a commitment to build or buy hardware. Nothing here is implemented in Cache-Me-Outside. Do not treat a merge of this document as a deploy, a purchase, or a schedule.

Recorded 2026-11-11 after a discussion of [Astera Labs' Leo 2](https://www.asteralabs.com/products/leo-smart-memory-controllers/) and the practical alternative: turn an old DDR3 server into a network RAM node. The idea stays in this tree so the hardware, the runbook, and the Cache-Me-Outside work are in one place if anyone picks it up later.

Examples use the documentation prefix `203.0.113.0/24` (TEST-NET-3), the same convention as [virtual machines](../cache-me-outside/virtual-machines.md). They are not addresses on a real network. Do not commit an inventory of real machines or any secrets.

## 1. Why the CXL route is out

[Astera Labs Leo](https://www.asteralabs.com/products/leo-smart-memory-controllers/) is a family of smart memory controllers. The product the Short shows is the add-in-card form: a custom ASIC on a PCIe card with many DIMM slots. The host sees that memory as extra capacity over [CXL](https://www.computeexpresslink.org/) (or, for the Leo X-Series, a PCIe-mode path aimed at accelerators). Astera's own pages and the September 2026 product brief describe the current Leo 2 E-Series and P-Series as:

- CXL 3.2 (with CXL 2.0 backward compatibility) and PCIe 6 host connectivity (x16, or 2×8 on the P-Series).
- Up to four DDR5 channels at up to 6400 MT/s (2 DIMMs per channel) or four DDR4 channels at up to 3200 MT/s (3 DIMMs per channel).
- Add-in cards such as the A2000, with up to 8 DDR5 RDIMM slots (Astera quotes up to 4 TB) or 12 DDR4 RDIMM slots (Astera quotes up to 768 GB).
- A design goal of *reusing already-deployed DDR4* in newer cloud servers, not inventing a new medium.

The Short that prompted this note is <https://youtube.com/shorts/qZslBJMTYd4>.

A DDR3 version of the same idea is not a weekend project:

- Commercial CXL memory controllers, including Leo, are built for DDR4 and DDR5. There is no commercial CXL controller, that this research found, whose DRAM interface is DDR3.
- CXL memory expansion itself only appears on server CPUs from roughly 2023 onward (Intel Xeon Scalable 4th gen "Sapphire Rapids" and later; AMD EPYC 9004 "Genoa" and later). A DDR3 platform has no CXL host port to plug a card into, and a modern CXL host has no DDR3 memory channels.
- Building a custom ASIC would be a multi-year, multi-million-dollar product. An FPGA prototype with a CXL controller IP block is a research exercise: development boards cost thousands of dollars, the work is months of firmware, and those boards are designed around DDR4 and DDR5, so DDR3 would need extra bridging. The result would be slow DDR3, made slower by the fabric, attached to a CPU that already has faster local memory.

The practical version does not try to make DDR3 look like local memory on a new CPU. It leaves the sticks in the old server and reaches that RAM over the network.

## 2. Architecture, and how it plugs into Cache-Me-Outside

Cache-Me-Outside is a Valkey-based cache. The server, the RESP protocol, and the command names stay Valkey's. [Operator docs](../cache-me-outside/README.md) already describe several layers that this idea has to sit *beside*, not replace:

| Layer | What it is today | Relation to far-RAM |
| --- | --- | --- |
| Near cache | Process-local memory, with RESP3 `CLIENT TRACKING`. See [near-cache](../cache-me-outside/near-cache.md). | Still the closest tier. A far-RAM miss can still hit here on the next read. |
| Primary CMO hosts | Valkey on Docker, a VM `.deb`, or Kubernetes, in standalone, Sentinel, or cluster form. See [deploy](../cache-me-outside/deploy.md), [scaling](../cache-me-outside/scaling.md), [targets](../cache-me-outside/targets.md). | Remain the default place for hot keys and for any data that must survive a far-RAM outage. |
| Hybrid flash log | Large strings spill to a *local* flash file; keys stay in DRAM. Off unless configured. See [hybrid storage](../cache-me-outside/hybrid-storage.md). | A different axis (local DRAM vs local flash on the same process). Do not put `cmo-hybrid-file` on a remote RAM disk: the log is already truncated on process start, and a network drop would add a second, surprising failure. |
| TTL segments | Keys that expire in the same bucket are deleted together. Off unless configured. See [ttl-segments](../cache-me-outside/ttl-segments.md). | Can be enabled on a far-RAM Valkey process the same way as on any other host. |
| Object / snapshot tier | Spill RDB/AOF copies to S3 or R2 (`tools/objtier`). | Durability for *backups*, not a substitute for far-RAM. Far-RAM is volatile and must not be the only copy of anything you need to keep. |
| Console and management API | `/console` and `tools/mgmt` create, limit, browse, and delete databases (tenants). See [management API](../cache-me-outside/management-api.md). | Today they do not register a host as a volatile tier. That is proposed work, below. |
| SDKs | Go, Node, and Python clients, plus the near-cache helper. | Today they talk to a host or a Sentinel/cluster set. Tier hints and failover around a volatile host are proposed work. |

The DDR3 box is a **far-RAM** node: a pool of DRAM that is one network hop away, sitting between local RAM and SSD in *capacity and cost*, not in latency. It is useful in two ways, and only the first is a native Cache-Me-Outside host.

### 2.1 Path A — application cache (the CMO host)

Install Cache-Me-Outside on the DDR3 server with the VM package or `./up.sh node`, give it a large `maxmemory`, and point selected clients at it. Persistence is **off** on this profile (see the runbook). The node is just another Valkey endpoint: TLS or a private network, the usual admin/app ACL users, one bind address, never `0.0.0.0`.

This is the path that fits the product. Other GoDesk apps already speak Redis/Valkey. A planned memcached listener ([feature plan](../cache-me-outside/rea-feature-plan.md) item 2) is not in the tree today, so do not stand up a separate memcached process and call it a Cache-Me-Outside host.

A reasonable key placement, once SDKs grow a hint, is:

1. Near cache, then the primary CMO host, for small hot keys and for anything that cannot be rebuilt.
2. The far-RAM host for large, reconstructable, TTL'd values: build caches, ephemeral job state, model or compile scratch that is already a cache, session-like data the app can recreate.
3. On far-RAM failure or timeout, treat the read as a miss and the write as skipped or redirected to the primary host. The request must not fail closed just because far-RAM is down.

Eviction on the far-RAM process itself is ordinary Valkey `maxmemory-policy`, defaulting to `allkeys-lru` like the rest of CMO. A console flag `volatile=true` / `tier=far-ram` tells operators and clients that a flush, a reboot, or a health-check failure is expected to empty the node.

### 2.2 Path B — block RAM disk (adjacent infrastructure)

The same box can export a RAM disk over NVMe-over-Fabrics TCP (`nvmet-tcp`). Clients attach it with `nvme connect` and use it as:

- high-priority *additional* swap, in front of a smaller local swap or zram device that must remain present;
- a `bcache` or `lvmcache` front for a slower disk;
- scratch space (build trees, container layers, temporary datasets).

NBD or iSCSI are acceptable fallbacks if NVMe-oF TCP is unavailable; NVMe-oF TCP is the preferred Linux-native path and needs no extra userspace target daemon.

This path is **not** a Cache-Me-Outside feature. It does not speak RESP. The console does not provision namespaces. The runbook is here because the same machine can offer both, and because a badly configured remote swap can hang a client kernel. Cache-Me-Outside code should not take a hard dependency on the block device being present.

### 2.3 Volatility rule

RAM loses everything when the node loses power, panics, or reboots. Put only cache, swap, or scratch on it. The OS disk on the DDR3 server can hold the system image and, if someone insists, an RDB as a *warm-start hint* — that does not make the dataset durable, and it is still the wrong place for unique data.

### 2.4 Console, health, and SDK hints (proposed)

None of the following exists yet. It is the shape that would make path A a first-class CMO tier.

- **Registration.** An operator adds the node in the console / management API with its announce address, port, `tier=far-ram`, `volatile=true`, and a capacity figure (`maxmemory`). The record is inventory, not an automatic cluster join. The node can be a standalone cache, or a member of its own Sentinel group. It should not take hash slots in a durable cluster unless every replica of those slots is also volatile and the slot range is documented as such — the safer default is a separate standalone or Sentinel deployment.
- **Health.** A periodic authenticated `PING`, plus `INFO memory` and `INFO server` (including `cmo_version`) from a checker that uses the admin user or a narrow health user. Consecutive failures mark the host `down`. A host that is `down` is removed from the SDK's far-RAM target list until it is `up` again. Health is not a substitute for client timeouts.
- **Eviction and drain.** From the console, an operator can "drain" the node: clients stop sending new keys, existing keys age out or are deleted, then the process can be stopped. A crash is equivalent to an immediate flush.
- **SDK hints.** A per-command or per-key option such as `tier=far` (name to be bikeshed) meaning "prefer the volatile host, fall back to miss/primary." Timeouts on this path must be short and independent of the primary-host timeout. The near-cache helper should still cache far-RAM hits, and must drop them on invalidation or on a flush message.

## 3. Hardware bill of materials

All prices below are **rough used-market ranges as of late 2025 and 2026 listings, to be verified at purchase time**. They are not quotes, not a shopping list, and not a claim that any of this hardware is already on site. A platform already sitting in a rack, with the DIMMs already paid for, is a different cost story from buying the same parts.

### 3.1 Platforms that make sense

The useful DDR3 servers are dual-socket Intel Xeon E5-2600 and E5-2600 v2 machines with many DIMM slots, typically 2U rack boxes from around 2012–2014. Examples of the class (not an endorsement of a vendor or a specific unit):

- Dell PowerEdge R720 / R720xd (24 DIMM slots)
- HP ProLiant DL380p Gen8 (24 DIMM slots)
- Supermicro X9 dual-socket boards in a 2U chassis with 16 or 24 slots

Why this class:

- Four memory channels per CPU, eight channels in a dual-socket board.
- Official support for large ECC registered memory. On a 24-slot board, a common official ceiling is **768 GB** with 32 GB load-reduced DIMMs (LRDIMM), or **384 GB** with 16 GB registered DIMMs (RDIMM). 256 GB (for example 16 × 16 GB) is a comfortable, easier-to-source working point. Confirm the board's own memory population rules; some boards have 16 or 12 slots and a lower ceiling.
- Out-of-band management (iDRAC, iLO, IPMI) so power and temperature can be read without standing in front of the box.
- PCIe slots that accept a 10 or 25 gigabit NIC.

Prefer v2 CPUs (Ivy Bridge-EP, for example E5-2670 v2, 10 cores, 115 W TDP) over v1 when there is a choice: slightly more cores, slightly better efficiency, same memory generation. Low-TDP "L" parts exist if the box will be mostly idle.

Do not chase single-socket desktop boards, non-ECC consumer DDR3, or blade chassis unless the blades and the enclosure are already on hand. The value is *capacity with ECC*, not a new compute cluster.

### 3.2 Memory and ECC

Use **ECC** RDIMM or LRDIMM only, the grade the board's manual lists. Do not mix RDIMM and LRDIMM in the same machine. Do not mix ranks or voltages carelessly; a channel runs at the slowest and most conservative common setting. Prefer a matched set, populated in the official channel order (usually four DIMMs at a time, per CPU, for interleaved bandwidth).

ECC matters here more than it does in a desktop: a multi-hundred-gigabyte RAM disk or Valkey process that silently corrupts a bit will evict, serve, or swap garbage. The server-class parts already include ECC; do not disable it in firmware.

DDR3-1600 (PC3-12800) is the usual target for this generation. Faster official bins are uncommon and not worth a premium.

### 3.3 Network

The link is the bottleneck (see §4). 1 gigabit Ethernet is too slow for this role (theoretical 125 MB/s). Plan on 10 or 25 gigabit.

| Item | Notes | Rough used price (estimate, verify) |
| --- | --- | --- |
| NIC, 10 GbE | Mellanox ConnectX-3 (now NVIDIA) or Intel X520, SFP+ | often about $20–80 per card |
| NIC, 25 GbE | Mellanox ConnectX-4 / ConnectX-4 Lx or Intel XXV710, SFP28 | often about $40–100 per card |
| Intel X710 | Common 10 GbE SFP+ alternative | often about $30–80 per card |
| DAC / SFP+ (or SFP28) cable | Direct-attach copper for short in-rack runs; match the transceiver family to both ends | often about $10–30 per cable |
| Switch | A small used SFP+ or SFP28 switch, or a direct NIC-to-NIC DAC if only one client talks to the node | used 8–16 port 10 GbE switches are often about $50–250; 25 GbE more. Verify optics compatibility. |
| One NIC in *each* client that will use the node | The DDR3 box and Jonathan / a GoDesk server / another host each need a port on the same isolated network | same NIC ranges as above |

A direct DAC between two machines is enough for a first test and avoids a switch. A switch is better once more than two machines share the node.

### 3.4 Power, cooling, and UPS

These boxes were designed for a data-center aisle. They are loud and they draw more than a modern small host.

Published figures for the Dell R720 class (dual E5-2600 / E5-2600 v2) span a wide range because memory, drives, and cards dominate idle draw. Dell's ENERGY STAR sheet, SPECpower results, and later summaries of those sources put common two-CPU builds roughly in **85–150 W at idle** and **about 215–410 W at a heavy load**, with stripped, tuned, one-SSD lab builds lower and memory-and-disk-heavy builds higher. A far-RAM node with many DIMMs, a 10/25 GbE card, and few or no spinning disks should be measured on *this* unit (iDRAC / iLO / a plug-in meter) rather than assumed from a datasheet. Treat the band above as **approximate orientation, not a rating**.

A UPS is for a clean OS shutdown and to give clients time to drain, not for keeping the RAM disk alive as durable storage. Size it from a measured wall draw with headroom for both power supplies if they are on one UPS, and test a scheduled shutdown hook. After the battery is exhausted, the RAM contents are still gone.

Keep the node in a place that can take the noise and the heat. Do not put a 2U dual-socket server in a quiet office without checking the fans first.

### 3.5 Other parts

- A small boot device (SATA SSD or SD/USB, a few tens of GB) for Debian or Proxmox. The cache does not live here.
- Redundant power supplies if the chassis has them, on separate circuits if that is easy, otherwise one circuit and a UPS.
- Rails or a shelf; these chassis are heavy once they are full of DIMMs.
- Spares: at least one extra DIMM of the same part and one extra DAC, if the used parts were cheap, because this generation is out of vendor support.

### 3.6 A worked capacity sketch (illustrative)

For a 24-slot board filled with 16 GB RDIMMs (384 GB raw): leave about 8–16 GB for the OS and, if path A and path B share the box, a hard cap so they cannot balloon into each other. A starting split might be 200–250 GB `maxmemory` for Valkey and the rest for a RAM disk, or the entire remainder for only one of the two paths. These numbers are a planning sketch, not a tuned config.

## 4. Expected performance (approximate)

Every number in this section is **approximate** and is here for orientation. Measure the real path with the acceptance tests in §9 before anyone relies on it. Sources for the order-of-magnitude figures include the JEDEC/PC3-12800 line rate, common programmer latency tables, vendor link rates, and published NVMe/TCP software-stack writeups. They are not measurements of a GoDesk machine.

| Path | Approximate bandwidth | Approximate latency | Notes |
| --- | --- | --- | --- |
| Local DDR3-1600, one channel | 12.8 GB/s theoretical | on the order of 50–100 ns for a memory reference | Eight channels in a dual-socket E5 board are about 100 GB/s theoretical, far more than the network will use |
| Local DDR4/DDR5 on a modern host | higher per channel than DDR3 | same nanosecond class | The client's *own* RAM remains the fastest tier |
| 10 GbE, line rate | 1.25 GB/s theoretical; a little less in real TCP | tens of microseconds for a short uncongested hop, often more through the kernel socket path | Jumbo frames (MTU 9000) usually help throughput |
| 25 GbE, line rate | 3.125 GB/s theoretical | similar latency class to 10 GbE, more headroom | Still orders of magnitude slower than local DRAM |
| NVMe-oF TCP over 10 GbE, software stack | often close to the NIC, not close to local DRAM | published software-stack tests often land in the **low-to-mid hundreds of microseconds** for I/O, worse under load | This is the block-path tax: protocol + TCP + kernel |
| Local NVMe SSD | roughly 3–8 GB/s sequential on PCIe 3 x4 / 4 x4, device-dependent | often tens of microseconds for a 4 K read on a decent SSD, with a long tail under write pressure | Beats 10 GbE on bulk throughput; no network tax |
| SATA SSD | roughly 0.5 GB/s | usually hundreds of microseconds | Far-RAM usually wins on latency and on write wear |
| Spinning disk | roughly 100–200 MB/s sequential, very little random I/O | milliseconds | Far-RAM wins clearly |

**Where far-RAM wins**

- Against HDD, and usually against SATA SSD, for scratch and swap: lower latency, more IOPS, and DRAM does not wear out.
- As *shared* capacity: several machines can use one pool without each of them buying more local RAM.
- As a place to put reconstructable cache data that would otherwise evict hotter keys from a primary CMO host, or that would burn write cycles on a client SSD (swap, container layers, build caches).
- On cost, **when the DDR3 server and the DIMMs are already owned**. Buying used DDR3 on the open market is a weaker story; used DDR4 ECC is often in a similar dollars-per-gigabyte band and can sit in a newer machine as *local* RAM. Verify current prices before buying parts "to save money."

**Where far-RAM loses**

- Against the client's local DRAM, always. This is not a CXL expander.
- Against a local NVMe SSD on sequential bandwidth, especially on 10 GbE (about 1.25 GB/s versus several GB/s). 25 GbE narrows that gap and may or may not win; measure it.
- Against local NVMe on latency. Hundreds of microseconds over TCP is not "as fast as RAM." It is "a fast network disk."
- When the link is 1 GbE, congested, or the MTU is wrong.
- When the data must survive a reboot.

For path A (Valkey), the relevant comparison is "a remote Redis/Valkey on a LAN," typically a few hundred microseconds to a millisecond for small GET/SET on a quiet 10 GbE network, not "local memory." That is a normal cache-server hop and is the right expectation for Cache-Me-Outside clients.

## 5. OS setup runbook

This runbook assumes Debian 12 (Bookworm) on the DDR3 node, which matches the [VM package](../cache-me-outside/virtual-machines.md) baseline, and a Linux client. Proxmox is fine as a host OS if the RAM disk and Valkey run on the host or in a VM that is given almost all of the RAM; do not casually nest the RAM disk inside a VM without measuring. Commands below use documentation addresses. Substitute the real isolated addresses at apply time. They must not be committed.

Packages on the node: `nvme-cli`, `iproute2`, `iptables` or `nftables`. For path A, the Cache-Me-Outside `.deb` (or a Valkey build with `BUILD_TLS=yes`). On the client: `nvme-cli`, and `fio` plus `valkey-benchmark` or `memtier_benchmark` for tests.

Kernel modules: `brd` or `zram` (path B), `nvmet`, `nvmet-tcp` (path B target), `nvme-tcp` (path B client). Configfs must be mounted at `/sys/kernel/config`.

### 5.1 Path B — RAM disk on the node

**`brd`** is a simple uncompressed RAM disk. `rd_size` is in **kilobytes** and applies to each disk. The module cannot be resized after load; unload it (no mounted or exported disks) and reload to change the size. Example: one 120 GiB disk, leaving the rest of RAM for the OS and, if used, Valkey:

```bash
# 120 GiB = 120 * 1024 * 1024 KiB
modprobe brd rd_nr=1 rd_size=$((120 * 1024 * 1024))
# /dev/ram0 is the device. Do not mkfs if the consumer will use it as raw swap or a cache backing store.
```

**`zram`** compresses pages, so the *visible* disk can be larger than the RAM it occupies, at the cost of CPU and a less predictable size. The kernel documentation warns that a zram disk bigger than about twice physical RAM is usually a waste. Prefer `brd` when the point is a known, reserved number of gigabytes. A zram example:

```bash
modprobe zram num_devices=1
echo 1 > /sys/block/zram0/reset
# optional: echo lz4 > /sys/block/zram0/comp_algorithm
echo 120G > /sys/block/zram0/disksize
# device is /dev/zram0
```

Pick one. The rest of this runbook uses `/dev/ram0`.

### 5.2 Path B — NVMe-oF TCP target (`configfs`)

IANA's recommended port for NVMe/TCP is **4420**. Use a documentation NQN; on a real box, pick a stable, unique NQN and do not recycle it.

```bash
modprobe nvmet
modprobe nvmet-tcp
mount -t configfs none /sys/kernel/config 2>/dev/null || true

NQN=nqn.2026-11.org.godesk:cmo:far-ram
HOST_NQN=nqn.2026-11.org.godesk:cmo:client-1
LISTEN=203.0.113.10
PORT=4420
DEV=/dev/ram0

mkdir -p /sys/kernel/config/nvmet/subsystems/$NQN
echo 0 > /sys/kernel/config/nvmet/subsystems/$NQN/attr_allow_any_host

mkdir -p /sys/kernel/config/nvmet/subsystems/$NQN/namespaces/1
echo -n "$DEV" > /sys/kernel/config/nvmet/subsystems/$NQN/namespaces/1/device_path
echo 1 > /sys/kernel/config/nvmet/subsystems/$NQN/namespaces/1/enable

# Restrict to a named host, then set DH-HMAC-CHAP (kernel 6.0+ with CONFIG_NVME_TARGET_AUTH).
mkdir -p /sys/kernel/config/nvmet/hosts/$HOST_NQN
# Generate a secret on a machine with a current nvme-cli. Do not commit it.
#   nvme gen-dhchap-key --nqn=$HOST_NQN          # older nvme-cli
#   nvme keys gen-kxchap-secret                  # nvme-cli 3.x (name may differ; check --help)
# echo 'DHHC-1:00:....' > /sys/kernel/config/nvmet/hosts/$HOST_NQN/dhchap_key
# optional bidirectional: echo 'DHHC-1:00:....' > .../dhchap_ctrl_key
# echo hmac(sha256) > /sys/kernel/config/nvmet/hosts/$HOST_NQN/dhchap_hash
# echo ffdhe2048    > /sys/kernel/config/nvmet/hosts/$HOST_NQN/dhchap_dhgroup
ln -s /sys/kernel/config/nvmet/hosts/$HOST_NQN \
      /sys/kernel/config/nvmet/subsystems/$NQN/allowed_hosts/$HOST_NQN

mkdir -p /sys/kernel/config/nvmet/ports/1
echo ipv4  > /sys/kernel/config/nvmet/ports/1/addr_adrfam
echo tcp   > /sys/kernel/config/nvmet/ports/1/addr_trtype
echo $LISTEN > /sys/kernel/config/nvmet/ports/1/addr_traddr
echo $PORT   > /sys/kernel/config/nvmet/ports/1/addr_trsvcid
ln -s /sys/kernel/config/nvmet/subsystems/$NQN \
      /sys/kernel/config/nvmet/ports/1/subsystems/$NQN
```

`nvmetcli` can save and restore a subset of this to `/etc/nvmet/config.json`. As of common current versions it may **silently drop DH-HMAC-CHAP attributes**. If authentication is enabled, keep a script that writes the `configfs` keys after `nvmetcli restore`, or do the whole setup from the systemd unit below.

NBD (`nbd-server` / `nbd-client`) or `tgt`/`lio` iSCSI are the fallbacks. They are not written out here; the security and volatility rules are the same.

### 5.3 systemd units that recreate the RAM disk and target at boot

The RAM disk is empty after every reboot. The units must create it before the target comes up, and they must not assume leftover `configfs` state.

`/etc/modules-load.d/cmo-far-ram.conf`:

```
brd
nvmet
nvmet-tcp
```

`/etc/modprobe.d/cmo-brd.conf` (size must match the unit; 120 GiB in KiB):

```
options brd rd_nr=1 rd_size=125829120
```

`/usr/local/sbin/cmo-nvmet-up.sh` should wrap the `configfs` steps and read the DH-HMAC-CHAP secret from a mode `0600` file under `/etc/cmo-far-ram/` (not in this repo). A matching `cmo-nvmet-down.sh` disables the namespace, removes the links, and can unload nothing if Valkey still needs the machine.

`/etc/systemd/system/cmo-nvmet.service`:

```ini
[Unit]
Description=CMO far-RAM NVMe-oF TCP target
After=network-online.target sys-kernel-config.mount
Wants=network-online.target
ConditionPathExists=/dev/ram0

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/cmo-nvmet-up.sh
ExecStop=/usr/local/sbin/cmo-nvmet-down.sh

[Install]
WantedBy=multi-user.target
```

If `brd` is not loaded by `modules-load` early enough, add a `cmo-brd.service` that runs `modprobe brd ...` and make `cmo-nvmet.service` `After=` and `Requires=` it.

### 5.4 Huge pages and NUMA

On the DDR3 node:

- Follow the usual Valkey/Redis host advice: `vm.overcommit_memory=1`, and disable transparent huge pages (`echo never > /sys/kernel/mm/transparent_hugepage/enabled` and the same for `defrag`), persisted with a `tmpfiles.d` snippet or a oneshot unit. THP has a long history of latency spikes under the allocator Valkey uses.
- Explicit huge pages are optional and not required for a first bring-up.
- Dual-socket boards are NUMA. A Valkey process that is left to wander will sometimes pay for remote-node memory. For a dataset that fits in one socket, pin with `numactl --cpunodebind=0 --membind=0`. For a dataset larger than one socket, `numactl --interleave=all` is the usual starting point. Measure both if the numbers look uneven.
- If path A and path B share the box, give each a hard budget (`maxmemory` for Valkey; a fixed `rd_size` for `brd`) so one cannot starve the other into the OOM killer.

On the client, no special huge-page setup is required for `nvme connect`.

### 5.5 Path B — client connect, swap, cache, scratch

```bash
modprobe nvme-tcp
# Secret stays in a 0600 file, not in the shell history if you can avoid it.
nvme connect -t tcp -a 203.0.113.10 -s 4420 \
  -n nqn.2026-11.org.godesk:cmo:far-ram \
  --hostnqn=nqn.2026-11.org.godesk:cmo:client-1 \
  --dhchap-secret="DHHC-1:00:...." \
  --ctrl-loss-tmo=30
# Device appears as /dev/nvmeXn1 (check nvme list).
```

`ctrl-loss-tmo` is the seconds the initiator keeps retrying after the controller is lost. The common default is **600**. For a *filesystem* that must ride out a short blip, some vendors recommend `-1` (retry without a limit). For **swap or a cache device**, a long or infinite timeout is the wrong default: the kernel can sit in I/O for minutes and look wedged. Start with a short value such as **30**, keep a local fallback, and tune after tests. See §7.

Persist the connect with `/etc/nvme/discovery.conf` plus `nvmf-autoconnect`, or a oneshot `cmo-nvme-connect.service` on the client, ordered before swap or mount units.

**Swap** (additional, never the only swap):

```bash
mkswap /dev/nvme0n1
swapon -p 10 /dev/nvme0n1
# Local fallback remains, at a lower priority, for example a 4–8 GiB zram or a local partition:
#   swapon -p 1 /dev/zram0
```

`/etc/fstab` lines must be `nofail` so a missing node does not stall boot:

```
/dev/disk/by-id/nvme-... none swap sw,pri=10,nofail 0 0
```

Prefer a systemd `.swap` unit that `After=` and `Wants=` the connect service, with `TimeoutSec=` bounded, rather than hoping `fstab` will wait long enough and then continue.

**`bcache` sketch** (the cache device is empty after every far-RAM reboot; the backing disk keeps the data, but the cache must be reattached and will start cold):

```bash
# One-time on the backing disk only. This is destructive to that disk's current contents.
# make-bcache -B /dev/sdX -C /dev/nvme0n1
# After a far-RAM reboot: recreate or re-register the cache device, then attach it.
# echo <cache-set-uuid> > /sys/block/bcache0/bcache/attach
```

**`lvmcache` sketch** (same cold-cache-after-reboot rule):

```bash
# pvcreate /dev/nvme0n1
# vgextend data-vg /dev/nvme0n1
# lvcreate --type cache --cachemode writeback -l 100%PVS -n cache0 data-vg /dev/nvme0n1
# writeback is faster and will lose dirty cache pages when the node dies; writethrough is safer and slower.
```

**Scratch**: put a filesystem on the namespace only if every mount is `nofail`, the unit does not sit on the boot path of the root disk, and the application treats the tree as disposable. `/etc/fstab`:

```
/dev/disk/by-id/nvme-... /mnt/far-ram ext4 nofail,x-systemd.device-timeout=10 0 0
```

Do not put `/`, `/var`, or any unique data on this device.

### 5.6 Path A — Valkey / Cache-Me-Outside on the node

Install the `.deb` as in [virtual machines](../cache-me-outside/virtual-machines.md), or run `./up.sh node` with `CMO_ANNOUNCE_IP` and `CMO_BIND_ADDRESS` set to the isolated address (one address, never `0.0.0.0`). Then apply a **volatile** profile. Today that profile is not a shipped env flag; it is a documented override:

```
# persist nothing; this host is a cache, and a fork of a huge dataset is expensive
save ""
appendonly no

maxmemory 200gb
maxmemory-policy allkeys-lru

protected-mode yes
bind 203.0.113.10 127.0.0.1
# Prefer TLS once BUILD_TLS=yes is how the node is built (roadmap item 1).
# tls-port 6379
# port 0
# tls-cert-file ...
# tls-key-file ...
# tls-ca-cert-file ...

# ACL: same shape as deploy/valkey.conf. default user disabled.
# admin and app passwords live in the environment file, mode 0600, not in git.
```

Leave `CMO_CONTAINER_MEMORY` / the systemd memory limit well above `maxmemory` if this process still runs under cgroup caps. With persistence off, fork headroom for `BGSAVE` matters less, but client buffers and fragmentation still exist; do not set `maxmemory` equal to physical RAM.

`vm.overcommit_memory=1` remains required.

## 6. Networking and security

Cache-Me-Outside is a home-lab cache on a LAN, not an Internet-facing service ([security](../cache-me-outside/security.md)). A far-RAM node is worse to expose than a primary host: it may export a raw block device.

- Put the node and its clients on an **isolated VLAN** (or a dedicated DAC/switch) that does not route to the public Internet and does not share a broadcast domain with untrusted devices. Management (iDRAC/iLO) stays on the management network, not on this VLAN, and is not opened to the world.
- Bind Valkey and `nvmet-tcp` to the isolated address only. `deploy/up.sh` and the VM unit already refuse `0.0.0.0`, `::`, and `*`. Keep that rule.
- Firewall the node: allow TCP 6379 (or the TLS port) from known client addresses for path A; allow TCP 4420 from known client addresses for path B; allow SSH and out-of-band management from an admin network only. Drop the rest. Do not publish 4420 or 6379 on a WAN router.
- Authenticate the block path with **DH-HMAC-CHAP** (`attr_allow_any_host=0`, per-host NQN, `dhchap_key`). A shared VLAN is not enough. If the kernel or `nvme-cli` on a given release cannot do in-band auth, wrap the path in **WireGuard** (or equivalent) and still keep the VLAN isolated; do not silently run an open target "just for the lab" on a shared network.
- Authenticate Valkey with the usual ACL users. Turn on TLS when the build supports it. Until then, rely on the isolated network and on WireGuard if the VLAN is not cleanly isolated.
- Set **MTU 9000** (jumbo frames) on the isolated VLAN, end to end: NICs, switch ports, and the host and VM interfaces. A mismatch causes hard-to-debug loss and terrible throughput. Confirm with `ping -M do -s 8972 203.0.113.10` (or the equivalent) before measuring.
- Disable unnecessary services on the DDR3 box. It should be a cache and, if used, an NVMe target, not a general login host.

## 7. Failure modes

The central fact is unchanged: **if the node dies or reboots, the data on it is gone.**

| Event | What happens | Mitigation |
| --- | --- | --- |
| Planned reboot or crash of the DDR3 node | RAM disk contents are empty; Valkey dataset is empty (persistence off). Clients see a disconnect. | Drain in the console first when you can. Clients treat far-RAM as a miss. Block consumers use `nofail`, a short `ctrl-loss-tmo`, and a local fallback. |
| NIC, cable, switch, or VLAN blip | Same as a disconnect, possibly short. | Jumbo-frame consistency, a spare DAC, and health checks. Valkey clients time out and fail over. |
| Client uses remote swap and the device stalls | The kernel may wait in swap I/O. With a long `ctrl-loss-tmo` (default 600 s, or `-1`) the machine can look **hung**. When the path finally errors, processes that needed those pages can be killed (for example with SIGBUS) or the box can go into recovery I/O. Under memory pressure this can coincide with the **OOM killer**. | Always keep a **local** swap or zram of a few gigabytes at a lower priority. Use a short `ctrl-loss-tmo`. Do not enable remote swap on an interactive desktop until it has been fault-injected (unplug the cable under load) and the client has recovered cleanly. Prefer path A over remote swap when in doubt. |
| `writeback` `bcache`/`lvmcache` and a node death | Dirty pages in the cache are lost. The backing disk is consistent only if the cache was in writethrough, or if the writeback set was clean. | Use writethrough unless the data is already disposable. After a node death, recreate or reattach a *cold* cache; do not assume the old cache-set UUID still has valid pages. |
| Valkey OOM or `maxmemory` hit | Ordinary evictions, or errors if the policy is `noeviction`. | `allkeys-lru`, a cap below physical RAM, and monitoring of evicted keys. |
| Mixing path A and path B without budgets | The RAM disk grows, Valkey grows, the kernel OOM-kills one of them (or something else). | Fixed `rd_size` and `maxmemory`, plus a memory cgroup on the Valkey unit. |
| Power loss mid-shutdown | OS disk can be unclean; RAM is gone either way. | UPS plus a shutdown hook that stops accepting client I/O, then stops Valkey, then powers off. This protects the OS disk, not the cache contents. |
| Silent DRAM errors | Wrong bytes in the cache or swap. | ECC, firmware left in ECC mode, replace failing DIMMs from iDRAC/iLO memory logs. |

Cache-Me-Outside graceful degradation (proposed, path A):

- A far-RAM timeout or connection error is a **miss**, not an application error, when the key was optional or can be rebuilt.
- Writes that were aimed at far-RAM can be skipped or sent to the primary host, according to the hint. They must not block the primary write path.
- Health checks mark the host down; the SDK stops sending to it until it is up.
- The console shows the host as down and empty after a restart, never as "recovered with last night's keys" unless a warm-start RDB was explicitly configured and loaded (and even then, treat it as stale-and-best-effort).

## 8. Monitoring, power, and cost per GB

**Monitoring.** Run [Prometheus `node_exporter`](https://github.com/prometheus/node_exporter) on the DDR3 box (CPU, memory, NIC, disk, hwmon). If Beszel is already the lab's host monitor, it can watch the same machine; use whichever is already deployed rather than inventing a third agent. For path A, scrape Valkey with the exporter pattern already discussed in [roadmap](../cache-me-outside/roadmap.md) item 4 and the Grafana bundle under `deploy/grafana/` (`INFO` is `@dangerous`, so the app user cannot scrape it). Watch at least: link up/down, NIC errors and drops, memory used vs `maxmemory`, evictions, connected clients, `PING` latency, NVMe-oF connection counts, and (on the client) whether the `nvme` device is present. Out-of-band power and temperature (iDRAC/iLO) belong on the same dashboard if they are reachable from the management network.

**Power.** See the approximate idle/load band in §3.4. Yearly energy is `watts × 8.760` kWh. Cost is that figure times the local rate; do not copy a US average into a production budget. A box that sits at 150 W is on the order of 1,300 kWh/year *before* the rate is applied. If the only reason to keep the machine powered is this tier, compare that bill to the cost of a modest pile of used DDR4 in a host you already leave on.

**Cost per GB.** Compute it two ways, both as estimates:

- *Sunk hardware:* if the chassis and DIMMs are already owned, the incremental capital is the NIC, cable, and maybe a boot SSD. Capacity cost is then dominated by power.
- *Bought used:* 16 GB DDR3-1600 ECC RDIMMs have appeared in 2026 vendor lists around the mid tens of dollars each, and 32 GB LRDIMMs higher than that; a used dual-socket 2U chassis of this generation has appeared in public listings often around the low-to-mid hundreds of dollars, sometimes more with more RAM included. **Verify at purchase time.** Used DDR4 ECC is often in a similar dollars-per-GB range and can be local RAM in a newer machine, which is a better place for it. New DDR5 server memory is typically much more expensive per GB, but it is also faster, more efficient, and local. The far-RAM project makes the most sense as a reuse of parts that would otherwise sit in a closet, not as a plan to buy a generation of memory that the rest of the lab is leaving behind.

## 9. Acceptance test plan

Run these on the isolated VLAN, with jumbo frames confirmed, before any client uses the node for swap or for application traffic. Record the exact hardware, kernel, MTU, and commands with the results. The pass criteria are **proposed starting gates**, to be tightened after the first measured baseline; they are not claims about a machine that has already been tested.

### 9.1 Block path

1. Fault injection: `nvme connect`, write a pattern with `dd` or `fio`, unplug the cable or reboot the target, confirm the client stays usable, local swap still works, and no unit on the boot path hangs past its timeout.
2. `fio` against the NVMe-oF device, at least:
   - sequential read and write, 1 MiB blocks, several jobs;
   - random 4 K read and write, queue depths 1 and 32.
3. Compare the same `fio` jobs against a local NVMe SSD and, if one exists, a local SATA SSD or HDD, on the same client.

Proposed gates:

- Sequential throughput on 10 GbE is in the same order of magnitude as the NIC (a large fraction of 1.25 GB/s), not in the HDD range. If it is stuck near 1 GbE speeds, fix MTU, negotiation, or the CPU on the target before continuing.
- Latency is in the microsecond-to-low-millisecond class, not the multi-millisecond HDD class.
- The path is not required to beat local NVMe. If it is much worse than a good local SSD on both bandwidth *and* latency, treat the block path as "shared scratch / swap only," not as a cache in front of that SSD.

### 9.2 Application path

1. Authenticated `PING` and a small `SET`/`GET` from a client on the VLAN, through the same bind address the apps will use.
2. `valkey-benchmark` or `memtier_benchmark` for small and large values (for example 64 B and 4 KiB, and a run with values near the size you actually want to store). Use the app user, not admin.
3. Fill to a known fraction of `maxmemory`, confirm `allkeys-lru` evicts, and confirm a process restart leaves an empty dataset (persistence off).
4. Kill the Valkey process or the machine during a benchmark and confirm a CMO client with the proposed hint returns a miss or falls back, rather than hanging.

Proposed gates:

- A quiet-LAN `PING` and small GET/SET stay in the sub-millisecond to low-millisecond range typical of a local Redis/Valkey hop. If they do not, debug the network before talking about tiers.
- A restart is visibly empty.
- A downed host does not take the primary CMO path down with it.

## 10. Phased Cache-Me-Outside work

Documentation of the possibility is this file. Code work starts only if someone decides to un-park it. Estimates are **rough calendar-day ranges for a single engineer who already knows this tree**, not a quote.

| Phase | What | Touches | Rough effort |
| --- | --- | --- | --- |
| P0 | A shipped "volatile host" profile: persistence off, bind/TLS/ACL unchanged, documented env flags so a VM or `./up.sh node` does not have to be hand-edited | `deploy/` env and `valkey.conf` templates, VM unit, docs | about 0.5–1 day |
| P1 | Management API: register, list, health, drain, and mark `tier=far-ram` / `volatile` hosts. No automatic slot moves. | `tools/mgmt`, OpenAPI | about 2–4 days |
| P2 | Console: show those hosts, their health, memory, and evictions, and a drain control. Do not imply durability. | `site/static/console.html` / `console.js`, management API | about 3–5 days |
| P3 | SDK hints, short independent timeouts, and fail-open to a miss or to the primary host. Same behaviour in Go, Node, and Python, and in the near-cache helper for hits that came from far-RAM. | `sdk/go`, `sdk/node`, `sdk/python`, `tools/nearcache` | about 3–5 days |
| P4 | Optional host agent on the node: reports `INFO`, link state, RAM disk / `nvmet` state if present, and registers with the management API. | a new small tool under `tools/`, systemd unit in the `.deb` | about 3–5 days |
| P5 | Grafana: a panel on the existing CMO dashboards for far-RAM hosts (memory, evictions, `PING` latency, up/down). | `deploy/grafana/`, `tools/grafana` | about 1–2 days |

A realistic total, if all of the above is wanted and hardware is already on the network, is on the order of **two to three weeks** of focused work, plus the bring-up and acceptance tests in this document. The block-path runbook does not need product code; it needs an operator and a maintenance window.

Do not start P1–P5 until P0 exists and the acceptance tests on real hardware have a recorded baseline. If the baseline is disappointing, stop.

## 11. Which GoDesk machines could use it

The **consumers** of a far-RAM node, if one is built, could include Jonathan, Dad's computer, and the GoDesk servers, each with a 10 or 25 GbE path into the isolated VLAN. That is a statement about possible clients, not a wiring plan, and it is not a decision to attach any of them.

Whether GoDesk already owns a suitable **DDR3 server**, and which machine that would be, is an **open question**. This document does not assume that a particular chassis is available, is free, or should be re-imaged. Finding or buying a donor belongs to a later decision.

Interactive desktops (if Dad's computer or a similar machine is used as a client) should start with path A, not with remote swap, until fault injection on that machine looks safe.

## 12. Open questions and risks

- Is there a donor DDR3 server with ECC and enough slots, already owned, that can be dedicated? If the answer is no, buying one may lose to putting used DDR4 in a host that is already always on.
- Can 10 or 25 GbE be run cleanly to the clients that would actually use the node (cabling, a switch or a DAC, MTU, a free PCIe slot)?
- Is the power and noise budget acceptable where the chassis would live? Measure that chassis; do not rely on the ranges in §3.4.
- Path A, path B, or both? Sharing the box needs memory budgets. Remote swap is the highest-risk client configuration.
- Kernel and `nvme-cli` versions on the node and on each client: DH-HMAC-CHAP needs a recent enough kernel (`CONFIG_NVME_TARGET_AUTH`) and a `nvme-cli` that can generate and pass keys. Confirm before promising in-band auth.
- Should a volatile host ever join a durable Valkey cluster, or must it always be a separate standalone/Sentinel deployment? The safer default is separate.
- Who owns operations (firmware, DIMM replacement, VLAN, secrets for DH-HMAC-CHAP and ACL) once the box is on?
- Legal and brand: this document cites Astera Labs and the Short for context. A product page or UI must not imply a partnership, a Leo-compatible device, or CXL support.
- Security: a raw block export is a disk on the network. A mistake in `attr_allow_any_host` or a bind to the wrong address is a data-exfiltration and corruption risk. Treat the firewall and auth steps as mandatory, including in a "temporary" lab setup.
- Opportunity cost: used DDR4 in existing modern hosts, or simply giving a primary CMO host more of *its* RAM, may beat this entire project on latency and on operational simplicity. Revisit that comparison with current prices before un-parking the work.

## References

- Astera Labs, Leo Smart Memory Controllers: <https://www.asteralabs.com/products/leo-smart-memory-controllers/>
- Astera Labs, Leo X / Leo 2 product brief (September 2026): <https://www.asteralabs.com/wp-content/uploads/2026/09/Product_Brief_Leo-X-Leo-2_Smart_Memory_Controllers_Final-1.pdf>
- The Short that started the discussion: <https://youtube.com/shorts/qZslBJMTYd4>
- Linux kernel, RAM disk (`brd`): <https://docs.kernel.org/admin-guide/blockdev/ramdisk.html>
- Linux kernel, zram: <https://docs.kernel.org/admin-guide/blockdev/zram.html>
- Linux kernel, `configfs` NVMe target attributes (including DH-HMAC-CHAP): <https://www.kernel.org/doc/Documentation/ABI/stable/configfs-nvmet>
- ArchWiki, NVMe over Fabrics (connect, `nvmetcli` limits, DH-HMAC-CHAP): <https://wiki.archlinux.org/title/NVMe_over_Fabrics>
- SUSE, NVMe-oF and `ctrl-loss-tmo`: <https://documentation.suse.com/sles/15-SP6/html/SLES-all/cha-nvmeof.html>
- Cache-Me-Outside operator docs: [README](../cache-me-outside/README.md), [scaling](../cache-me-outside/scaling.md), [security](../cache-me-outside/security.md), [hybrid storage](../cache-me-outside/hybrid-storage.md), [near cache](../cache-me-outside/near-cache.md), [virtual machines](../cache-me-outside/virtual-machines.md)
