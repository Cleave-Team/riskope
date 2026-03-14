{{- define "riskope.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "riskope.fullname" -}}
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

{{- define "riskope.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "riskope.labels" -}}
helm.sh/chart: {{ include "riskope.chart" . }}
{{ include "riskope.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "riskope.selectorLabels" -}}
app.kubernetes.io/name: {{ include "riskope.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "riskope.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "riskope.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "riskope.secretName" -}}
{{- printf "%s-secret" (include "riskope.fullname" .) }}
{{- end }}
