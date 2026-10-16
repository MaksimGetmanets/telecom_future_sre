{{/* Общие лейблы. Передавать нужно словарь: (dict "name" "gateway" "root" $) */}}
{{- define "demo.labels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/part-of: demo-shop
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end -}}

{{- define "demo.selector" -}}
app.kubernetes.io/name: {{ .name }}
{{- end -}}
