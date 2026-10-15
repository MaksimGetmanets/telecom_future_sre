package diag

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Client вызывает POST /execute у remediator. Все ограничения (namespace, действия, пауза, лимит в час,
// dry-run) проверяет сам remediator, бот только передаёт решение человека.
type Client struct {
	baseURL string
	token   string
	http    *http.Client
}

// NewClient возвращает nil, если URL не задан: тогда бот показывает диагностику без кнопок.
func NewClient(baseURL, token string) *Client {
	baseURL = strings.TrimRight(strings.TrimSpace(baseURL), "/")
	if baseURL == "" {
		return nil
	}
	return &Client{baseURL: baseURL, token: token, http: &http.Client{Timeout: 15 * time.Second}}
}

// ExecResult: ответ remediator.
type ExecResult struct {
	Status       string `json:"status"`
	Detail       string `json:"detail"`
	Action       string `json:"action"`
	Namespace    string `json:"namespace"`
	Deployment   string `json:"deployment"`
	DryRun       bool   `json:"dry_run"`
	ReplicasFrom int    `json:"replicas_from"`
	ReplicasTo   int    `json:"replicas_to"`
}

// Execute отправляет подтверждённое действие.
func (c *Client) Execute(ctx context.Context, cb Callback) (ExecResult, error) {
	body := map[string]any{
		"action": cb.Action, "namespace": cb.Namespace, "deployment": cb.Deployment, "source": "telegram",
	}
	if cb.Replicas > 0 {
		body["replicas"] = cb.Replicas
	}
	raw, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/execute", bytes.NewReader(raw))
	if err != nil {
		return ExecResult{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return ExecResult{}, fmt.Errorf("remediator недоступен: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return ExecResult{}, fmt.Errorf("remediator вернул HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(msg)))
	}
	var res ExecResult
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&res); err != nil {
		return ExecResult{}, fmt.Errorf("не удалось прочитать ответ remediator: %w", err)
	}
	return res, nil
}

// FormatHTML: итог действия для сообщения в чате.
func (r ExecResult) FormatHTML() string {
	target := Esc(r.Namespace + "/" + r.Deployment)
	switch r.Status {
	case "executed":
		return fmt.Sprintf("✅ Выполнено: %s <code>%s</code>\n%s", Esc(r.Action), target, Esc(r.Detail))
	case "dry_run":
		return fmt.Sprintf("🧪 Режим dry-run, в кластере ничего не изменено: %s <code>%s</code>", Esc(r.Action), target)
	case "skipped_guard":
		return fmt.Sprintf("⏳ Не выполнено, сработал предохранитель: %s", Esc(r.Detail))
	case "skipped_at_max":
		return fmt.Sprintf("ℹ️ Не выполнено: %s", Esc(r.Detail))
	case "error":
		return fmt.Sprintf("❌ Ошибка выполнения: %s", Esc(r.Detail))
	default:
		return fmt.Sprintf("⚠️ Не выполнено (%s): %s", Esc(r.Status), Esc(r.Detail))
	}
}
