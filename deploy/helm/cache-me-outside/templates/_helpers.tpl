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
