# Kubernetes

`deploy/helm/cache-me-outside` runs on any cluster that can install a Helm chart: k3s, kind, or a managed Kubernetes service. It does not depend on one distribution. CI renders it with `helm lint` and kubeconform, and a kind cluster runs the standalone topology and a cluster-mode scale-out (3 primaries, add a 4th, read the key back).

## Install

Create the Secret first. The chart does not invent passwords and will not render them into a Secret.

```bash
kubectl create secret generic cache-me-outside-auth \
  --from-literal=admin-user=admin \
  --from-literal=admin-password='<16+ chars>' \
  --from-literal=app-user=app \
  --from-literal=app-password='<different 16+ chars>'

helm upgrade --install cmo deploy/helm/cache-me-outside \
  --set topology=standalone
```

`topology` is `standalone`, `sentinel`, or `cluster`.

What you get:

- A StatefulSet of data pods, each with its own PVC (`persistence.size`, default `1Gi`). `persistence.storageClass` is empty by default, which uses the cluster's default StorageClass. Set it when k3s, kind, or a managed cluster should use a different class. `persistence.accessMode` defaults to `ReadWriteOnce`
- A headless Service so pod DNS is stable (`<pod>.<release>-cmo-data-headless`). Service names come from the release. There is no Service named `redis` or `valkey`
- A PodDisruptionBudget (`maxUnavailable: 1`)
- Resource requests and limits from `values.yaml`
- Readiness and liveness probes that run the image health check
- A `preStop` hook that runs `SHUTDOWN SAVE` on data pods and `SHUTDOWN NOSAVE` on Sentinel, then a termination grace period (default 30 seconds)
- Preferred pod anti-affinity and topology spread on `kubernetes.io/hostname`, with `ScheduleAnyway`, so a one-node cluster can still place every pod and a multi-node cluster separates shards and replicas
- A NetworkPolicy that allows ingress from this release and from pods labeled `cache-me-outside.io/client=true`, and egress to those pods plus DNS. Set `networkPolicy.enabled` to `false` if the cluster does not enforce NetworkPolicy
- The same image entrypoint as Docker: ACL from the Secret, AOF and RDB on the volume, `maxmemory` and `io-threads` from values
- For `cluster`, a post-install Job that runs `valkey-cli --cluster create` once the pods answer `PING`, and skips that if `cluster_state` is already `ok`
- For `sentinel`, pod 0 is the initial primary (`CMO_ROLE=auto`), the other data pods replicaof it, and a second StatefulSet runs Sentinel

Pods run as uid 999 with privilege escalation off and a dropped capability set. `hostPort` is off. Setting `hostPort.enabled=true` with address `0.0.0.0`, `::`, or `*` fails the render. Inside one cluster the pods reach each other through DNS, so host ports are unnecessary. `cluster.announce.mode` defaults to `hostname`, and `cluster-announce-hostname` is `<pod>.<headless service>`.

`cluster.announce.mode=ip` is for a pod that must be reachable from a VM or a container outside this cluster. It requires `hostPort.enabled=true` and announces `status.hostIP` plus the published client and bus ports. The render fails if you ask for ip announce without a host port. The pod IP is not treated as a routable address.

There is no host LAN address in the chart.

## Metrics

`metrics.exporter.enabled` adds an `oliver006/redis_exporter` sidecar that scrapes the admin user on localhost. The app user cannot run `INFO`, so the exporter does not use it. `metrics.serviceMonitor.enabled` emits a `ServiceMonitor` for a Prometheus operator. Both default to off. kubeconform skips `ServiceMonitor` because that CRD is not in the stock Kubernetes schema. Leave the exporter off until you have a place to scrape port 9121.

## Rolling upgrade

`helm upgrade` with a new image tag rolls the StatefulSet one pod at a time (the default rolling strategy, highest ordinal first). Data pods run `SHUTDOWN SAVE` in `preStop` before the process is killed, so the volume has a fresh snapshot if the pod then comes back. A cluster primary with no replica is unavailable for its slots until that pod is ready again. Give those primaries a replica before you roll them if the working set cannot tolerate that gap. Sentinel pods shut down without `SAVE`.

After the roll, a cluster should still report `cluster_state:ok`. You do not re-run `cluster create`. A failed pod keeps its PVC, so the AOF is still there when it starts.

## Scale

Vertical: change `resources` and `maxmemory` (keep maxmemory at or below half the memory limit) and upgrade the release. That rolls the StatefulSet. For a live `CONFIG SET` on a pod that already has cgroup headroom, exec `valkey-cli` as the admin user the same way `deploy/scale-memory.sh` does. The chart does not ship that helper; the script talks to Docker.

Horizontal, cluster:

1. Raise the data replica count so the new ordinal exists. The chart's replica count is `primaries * (1 + replicasPerPrimary)`. To add one empty primary, increase `cluster.primaries` by one **or** scale the StatefulSet and then join the extra pod with the scale Job. If you change `cluster.primaries`, the init Job's `--cluster-replicas` math changes; prefer scaling the StatefulSet and using the scale Job so the existing slot map is not recreated.
2. Upgrade with the scale Job enabled:

```bash
helm upgrade cmo deploy/helm/cache-me-outside \
  --reuse-values \
  --set cluster.scaleJob.enabled=true \
  --set cluster.scaleJob.ordinal=6 \
  --set cluster.scaleJob.role=primary
```

The Job waits for that ordinal, `add-node`, and rebalances. `role=replica` also needs `cluster.scaleJob.primaryOrdinal`. Turn `cluster.scaleJob.enabled` back off afterwards so the next upgrade does not try to add the same ordinal again. The Job is skipped when the chart value is false.

Removing a shard is still the Docker script's drain (`CLUSTER` reshard until the node owns no slots, then del-node), run from a pod with `valkey-cli` against the in-cluster DNS names. Do not `kubectl delete` a primary that still owns slots.

Sentinel scale is `sentinel.replicas` and `sentinel.count` on upgrade. A new data ordinal other than `*-0` starts as a replica of pod 0. After a failover, pod 0 may be a replica; Sentinel's runtime view is authoritative, and a Sentinel pod restart rewrites its config from the current primary host env (pod 0) and then follows whatever role that pod reports.

## HPA

An HorizontalPodAutoscaler is the wrong tool here, and the chart does not include one.

The cache is stateful. CPU or memory pressure means the working set or the request rate does not fit the current pods. An HPA that adds a pod creates an empty Valkey process that owns no slots and serves no keys until something runs `add-node` and a rebalance. An HPA that deletes a pod drops whatever slots that pod owned. Sentinel failover is an availability event, not a scale event: the replica count you want is fixed by how many full copies you are willing to store.

Scale up by raising requests, limits, and `maxmemory` when one node can still hold the data. Scale out by the cluster steps above when it cannot. If you want a signal, scrape the admin user (the app user cannot run `INFO`) and page a person. Do not close that loop with an HPA.
