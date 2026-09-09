{{/*
Expand the name of the chart.
*/}}
{{- define "support-bot.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully-qualified app name.
Truncated at 63 chars because some Kubernetes name fields are limited to this.
*/}}
{{- define "support-bot.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "support-bot.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "support-bot.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: support-bot
{{- end }}

{{/*
Selector labels (stable across upgrades).
*/}}
{{- define "support-bot.selectorLabels" -}}
app.kubernetes.io/name: {{ include "support-bot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Component-specific name helper.
*/}}
{{- define "support-bot.componentName" -}}
{{- $component := index . 1 -}}
{{- $ctx := index . 0 -}}
{{- printf "%s-%s" (include "support-bot.fullname" $ctx) $component | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Image reference.
*/}}
{{- define "support-bot.image" -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) }}
{{- end }}

{{/*
Secret name.
*/}}
{{- define "support-bot.secretName" -}}
{{- printf "%s-secrets" (include "support-bot.fullname" .) }}
{{- end }}

{{/*
ConfigMap name.
*/}}
{{- define "support-bot.configMapName" -}}
{{- printf "%s-config" (include "support-bot.fullname" .) }}
{{- end }}
