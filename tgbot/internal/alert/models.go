package alert

// Alert описывает отдельный алерт из пачки Alertmanager
type Alert struct {
	Status      string            `json:"status"` // firing или resolved
	Labels      map[string]string `json:"labels"`
	Annotations map[string]string `json:"annotations"`
}

// WebhookPayload описывает структуру всего входящего POST-запроса
type WebhookPayload struct {
	Status string  `json:"status"`
	Alerts []Alert `json:"alerts"`
}
