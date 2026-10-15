package diag

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const sample = `{"hypothesis":"Рост 5xx: утечка в *orders* [v1.2] <b>x</b>","confidence":0.85,
"evidence":["error_ratio_5m=0.21","pod_restarts=3"],"validated":true,"rejected_reason":null,"model":"rules",
"fallback_reason":null,"suggested_action":{"type":"restart","deployment":"orders","replicas":0}}`

func TestParseAndFormatEscapesEverything(t *testing.T) {
	d, err := Parse(strings.NewReader(sample))
	if err != nil {
		t.Fatal(err)
	}
	out := FormatHTML(d)
	if strings.Contains(out, "<b>x</b>") || !strings.Contains(out, "&lt;b&gt;x&lt;/b&gt;") {
		t.Fatalf("HTML из ответа LLM не экранирован: %s", out)
	}
	for _, want := range []string{"Диагностика (rules)", "0.85", "error_ratio_5m=0.21", "restart", "<code>orders</code>", "после вашего подтверждения"} {
		if !strings.Contains(out, want) {
			t.Errorf("в сообщении нет %q:\n%s", want, out)
		}
	}
	if !d.Actionable() {
		t.Error("restart orders должен быть исполнимым")
	}
}

func TestNotActionable(t *testing.T) {
	cases := map[string]string{
		"отклонено": `{"hypothesis":"x","validated":false,"rejected_reason":"namespace 'prod' не разрешён","suggested_action":{"type":"none","deployment":"orders"}}`,
		"none":      `{"hypothesis":"x","validated":true,"suggested_action":{"type":"none","deployment":""}}`,
		"rollback":  `{"hypothesis":"x","validated":true,"suggested_action":{"type":"rollback","deployment":"orders"}}`,
		"без цели":  `{"hypothesis":"x","validated":true,"suggested_action":{"type":"restart","deployment":""}}`,
	}
	for name, body := range cases {
		d, err := Parse(strings.NewReader(body))
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if d.Actionable() {
			t.Errorf("%s: кнопка не должна показываться", name)
		}
		_ = FormatHTML(d)
	}
}

func TestFormatLimitsLength(t *testing.T) {
	d := Diagnosis{Hypothesis: strings.Repeat("я", 5000), Validated: true}
	for i := 0; i < 20; i++ {
		d.Evidence = append(d.Evidence, strings.Repeat("e", 1000))
	}
	if n := len([]rune(FormatHTML(d))); n > 3500 {
		t.Fatalf("сообщение слишком длинное для Telegram: %d знаков", n)
	}
}

func TestCallbackRoundTripAndLimits(t *testing.T) {
	data := EncodeExec("demo", Action{Type: "scale", Deployment: "orders", Replicas: 3})
	if len(data) > 64 {
		t.Fatalf("данные кнопки длиннее 64 байт: %d", len(data))
	}
	cb, err := ParseCallback(data)
	if err != nil || cb.Action != "scale" || cb.Namespace != "demo" || cb.Deployment != "orders" || cb.Replicas != 3 {
		t.Fatalf("разбор: %+v, %v", cb, err)
	}
	if cb, err := ParseCallback(EncodeReject()); err != nil || !cb.Reject {
		t.Fatalf("отклонение: %+v, %v", cb, err)
	}
}

func TestParseCallbackRejectsGarbage(t *testing.T) {
	for _, bad := range []string{"", "x", "x|restart|demo|orders", "x|delete|demo|orders|0", "x|restart|De mo|orders|0",
		"x|restart|demo|orders;rm|0", "x|restart|demo|orders|abc", "x|scale|demo|orders|99", "x|restart|demo|orders|-1", "y|restart|demo|orders|0"} {
		if _, err := ParseCallback(bad); err == nil {
			t.Errorf("%q должно быть отклонено", bad)
		}
	}
}

func TestClientExecute(t *testing.T) {
	var got map[string]any
	var auth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		if r.URL.Path != "/execute" || r.Method != http.MethodPost {
			http.NotFound(w, r)
			return
		}
		_ = json.NewDecoder(r.Body).Decode(&got)
		_ = json.NewEncoder(w).Encode(map[string]any{"status": "executed", "action": "scale", "namespace": "demo",
			"deployment": "orders", "detail": "replicas 2 -> 3 (по подтверждению)", "replicas_from": 2, "replicas_to": 3})
	}))
	defer srv.Close()

	c := NewClient(srv.URL+"/", "s3cret")
	res, err := c.Execute(context.Background(), Callback{Action: "scale", Namespace: "demo", Deployment: "orders", Replicas: 3})
	if err != nil {
		t.Fatal(err)
	}
	if auth != "Bearer s3cret" || got["action"] != "scale" || got["replicas"].(float64) != 3 || got["source"] != "telegram" {
		t.Fatalf("запрос: auth=%q body=%v", auth, got)
	}
	if res.Status != "executed" || !strings.Contains(res.FormatHTML(), "Выполнено") {
		t.Fatalf("ответ: %+v", res)
	}
}

func TestClientErrors(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Error(w, "unauthorized", 401) }))
	defer srv.Close()
	if _, err := NewClient(srv.URL, "").Execute(context.Background(), Callback{Action: "restart", Namespace: "demo", Deployment: "orders"}); err == nil ||
		!strings.Contains(err.Error(), "401") {
		t.Fatalf("ожидалась ошибка 401, получено %v", err)
	}
	if NewClient("  ", "t") != nil {
		t.Fatal("без URL клиент не создаётся: бот работает без кнопок")
	}
}

func TestExecResultFormats(t *testing.T) {
	for status, want := range map[string]string{"executed": "Выполнено", "dry_run": "dry-run", "skipped_guard": "предохранитель",
		"error": "Ошибка", "rejected": "Не выполнено"} {
		out := ExecResult{Status: status, Action: "restart", Namespace: "demo", Deployment: "orders", Detail: "a<b"}.FormatHTML()
		if !strings.Contains(out, want) || strings.Contains(out, "a<b") {
			t.Errorf("%s: %q", status, out)
		}
	}
}

func TestPlainTextAndTrunc(t *testing.T) {
	got := PlainText("<b>Гипотеза:</b> a &lt;b&gt; <code>orders</code>")
	if got != "Гипотеза: a <b> orders" {
		t.Fatalf("PlainText: %q", got)
	}
	if Trunc("абвгд", 3) != "абв…" || Trunc("аб", 3) != "аб" {
		t.Fatal("Trunc режет не по символам")
	}
}
