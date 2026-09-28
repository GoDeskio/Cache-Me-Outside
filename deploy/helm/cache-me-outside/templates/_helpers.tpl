{{- define "cmo.name" -}}
cache-me-outside
{{- end -}}

{{- define "cmo.fullname" -}}
{{- printf "%s-%s" .Release.Name "cmo" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "cmo.labels" -}}
app.kubernetes.io/name: {{ include "cmo.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: cache-me-outside
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "cmo.selector" -}}
app.kubernetes.io/name: {{ include "cmo.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "cmo.dataReplicas" -}}
{{- if eq .Values.topology "standalone" -}}
1
{{- else if eq .Values.topology "sentinel" -}}
{{ add .Values.sentinel.replicas 1 }}
{{- else if eq .Values.topology "cluster" -}}
{{ mul .Values.cluster.primaries (add .Values.cluster.replicasPerPrimary 1) }}
{{- else -}}
{{- fail "topology must be standalone, sentinel, or cluster" -}}
{{- end -}}
{{- end -}}

{{- define "cmo.headless" -}}
{{ include "cmo.fullname" . }}-data-headless
{{- end -}}

{{- define "cmo.dataPodPrefix" -}}
{{ include "cmo.fullname" . }}-data
{{- end -}}

{{- define "cmo.authEnv" -}}
- name: CMO_ADMIN_USER
  valueFrom:
    secretKeyRef:
      name: {{ .Values.auth.existingSecret }}
      key: {{ .Values.auth.adminUserKey }}
- name: CMO_ADMIN_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.auth.existingSecret }}
      key: {{ .Values.auth.adminPasswordKey }}
- name: CMO_APP_USER
  valueFrom:
    secretKeyRef:
      name: {{ .Values.auth.existingSecret }}
      key: {{ .Values.auth.appUserKey }}
- name: CMO_APP_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.auth.existingSecret }}
      key: {{ .Values.auth.appPasswordKey }}
- name: CMO_REPL_USER
  valueFrom:
    secretKeyRef:
      name: {{ .Values.auth.existingSecret }}
      key: {{ .Values.auth.replUserKey }}
      optional: true
- name: CMO_REPL_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.auth.existingSecret }}
      key: {{ .Values.auth.replPasswordKey }}
      optional: true
- name: CMO_SENTINEL_USER
  valueFrom:
    secretKeyRef:
      name: {{ .Values.auth.existingSecret }}
      key: {{ .Values.auth.sentinelUserKey }}
      optional: true
- name: CMO_SENTINEL_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.auth.existingSecret }}
      key: {{ .Values.auth.sentinelPasswordKey }}
      optional: true
- name: CMO_CLUSTER_USER
  valueFrom:
    secretKeyRef:
      name: {{ .Values.auth.existingSecret }}
      key: {{ .Values.auth.clusterUserKey }}
      optional: true
- name: CMO_CLUSTER_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.auth.existingSecret }}
      key: {{ .Values.auth.clusterPasswordKey }}
      optional: true
{{- end -}}

{{- define "cmo.podSecurity" -}}
runAsNonRoot: true
runAsUser: 999
runAsGroup: 999
fsGroup: 999
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "cmo.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: false
capabilities:
  drop: ["ALL"]
{{- end -}}

{{- define "cmo.spread" -}}
{{- if .Values.scheduling.spread }}
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          topologyKey: kubernetes.io/hostname
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: {{ include "cmo.name" . }}
              app.kubernetes.io/instance: {{ .Release.Name }}
              app.kubernetes.io/component: {{ .component }}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        app.kubernetes.io/name: {{ include "cmo.name" . }}
        app.kubernetes.io/instance: {{ .Release.Name }}
        app.kubernetes.io/component: {{ .component }}
{{- end }}
{{- end -}}

{{- define "cmo.probes" -}}
readinessProbe:
  exec:
    command: ["/usr/local/bin/healthcheck.sh"]
  initialDelaySeconds: {{ .Values.probes.readiness.initialDelaySeconds }}
  periodSeconds: {{ .Values.probes.readiness.periodSeconds }}
  timeoutSeconds: {{ .Values.probes.readiness.timeoutSeconds }}
  failureThreshold: {{ .Values.probes.readiness.failureThreshold }}
livenessProbe:
  exec:
    command: ["/usr/local/bin/healthcheck.sh"]
  initialDelaySeconds: {{ .Values.probes.liveness.initialDelaySeconds }}
  periodSeconds: {{ .Values.probes.liveness.periodSeconds }}
  timeoutSeconds: {{ .Values.probes.liveness.timeoutSeconds }}
  failureThreshold: {{ .Values.probes.liveness.failureThreshold }}
{{- end -}}

{{- define "cmo.preStop" -}}
{{- if .Values.gracefulShutdown.enabled }}
lifecycle:
  preStop:
    exec:
      command:
        - /bin/sh
        - -c
        - 'valkey-cli -h 127.0.0.1 -p "$CMO_PORT" --user "$CMO_ADMIN_USER" -a "$CMO_ADMIN_PASSWORD" --no-auth-warning SHUTDOWN {{ .shutdownMode }}'
{{- end }}
{{- end -}}
