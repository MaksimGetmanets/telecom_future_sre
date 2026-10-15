package alert

import (
	"bytes"
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"main/internal/chats"
)

type syncBuf struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (s *syncBuf) Write(p []byte) (int, error) { s.mu.Lock(); defer s.mu.Unlock(); return s.b.Write(p) }
func (s *syncBuf) String() string              { s.mu.Lock(); defer s.mu.Unlock(); return s.b.String() }

func captureLog(t *testing.T) *syncBuf {
	t.Helper()
	buf := &syncBuf{}
	log.SetOutput(buf)
	t.Cleanup(func() { log.SetOutput(nil) })
	return buf
}

func waitFor(t *testing.T, buf *syncBuf, substr string) string {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if out := buf.String(); strings.Contains(out, substr) {
			return out
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("в логе нет %q:\n%s", substr, buf.String())
	return ""
}

const firingAlert = `{"status":"firing","alerts":[{"status":"firing",
 "labels":{"alertname":"DemoHighErrorRate","namespace":"demo","deployment":"orders","severity":"page"},
 "annotations":{"description":"5xx выше нормы <b>orders</b>"}}]}`

// Без токена Telegram бот не падает: алерт и ИИ-диагностика уходят в лог.
func TestLogModeWithoutTelegram(t *testing.T) {
	buf := captureLog(t)
	assistant := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"hypothesis":"orders отдаёт 5xx","confidence":0.8,"evidence":["error_ratio=0.5"],
		 "validated":true,"model":"rules","suggested_action":{"type":"restart","deployment":"orders"}}`))
	}))
	defer assistant.Close()
	t.Setenv("LLM_ASSISTANT_URL", assistant.URL)
	t.Setenv("REMEDIATOR_URL", "")

	h := NewHandler(nil, chats.Open(""))
	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/alert", strings.NewReader(firingAlert)))
	if rec.Code != http.StatusOK {
		t.Fatalf("HTTP %d", rec.Code)
	}
	out := waitFor(t, buf, "[DIAG]")
	for _, want := range []string{"[MSG]", "DemoHighErrorRate", "orders отдаёт 5xx", "restart"} {
		if !strings.Contains(out, want) {
			t.Errorf("в логе нет %q:\n%s", want, out)
		}
	}
	// разметка бота в лог не попадает, а текст из самого алерта сохраняется как есть
	if strings.Contains(out, "<b>АЛЕРТ") || strings.Contains(out, "<code>") || !strings.Contains(out, "<b>orders</b>") {
		t.Errorf("лог должен быть без разметки бота, но с исходным описанием алерта:\n%s", out)
	}
}

// Ассистент недоступен: алерт всё равно доходит, причина пишется в лог.
func TestLogModeAssistantDown(t *testing.T) {
	buf := captureLog(t)
	t.Setenv("LLM_ASSISTANT_URL", "http://127.0.0.1:1/diagnose")
	h := NewHandler(nil, chats.Open(""))
	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/alert", strings.NewReader(firingAlert)))
	if rec.Code != http.StatusOK {
		t.Fatalf("HTTP %d", rec.Code)
	}
	waitFor(t, buf, "не удалось получить ИИ-диагностику")
}

func TestResolvedAlertAndBadRequests(t *testing.T) {
	buf := captureLog(t)
	h := NewHandler(nil, chats.Open(""))
	mux := http.NewServeMux()
	h.RegisterRoutes(mux)

	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/alert",
		strings.NewReader(`{"alerts":[{"status":"resolved","labels":{"alertname":"X","namespace":"demo"}}]}`)))
	if rec.Code != http.StatusOK || !strings.Contains(buf.String(), "resolved") {
		t.Errorf("resolved: HTTP %d, лог:\n%s", rec.Code, buf.String())
	}
	rec = httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/alert", nil))
	if rec.Code != http.StatusMethodNotAllowed {
		t.Errorf("GET: HTTP %d", rec.Code)
	}
	rec = httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/alert", strings.NewReader("не json")))
	if rec.Code != http.StatusBadRequest {
		t.Errorf("мусор: HTTP %d", rec.Code)
	}
}

// Без бота команды и кнопки не обрабатываются и не падают.
func TestNilBotIgnoresMessagesAndCallbacks(t *testing.T) {
	h := NewHandler(nil, chats.Open(""))
	h.HandleMessage(nil)
	h.HandleCallback(nil)
}
