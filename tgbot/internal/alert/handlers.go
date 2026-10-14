package alert

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

type Handler struct {
	bot    *tgbotapi.BotAPI
	chatId int64
}

// NewHandler инициализирует зависимости для обработки алертов
func NewHandler(bot *tgbotapi.BotAPI, chatId int64) *Handler {
	return &Handler{
		bot:    bot,
		chatId: chatId,
	}
}

// RegisterRoutes регистрирует эндпоинты в http.ServeMux
func (h *Handler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/alert", h.HandleWebhook)
}

// HandleWebhook обрабатывает входящие запросы от Alertmanager
func (h *Handler) HandleWebhook(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var payload WebhookPayload
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		log.Printf("[ERROR] Ошибка парсинга JSON: %v", err)
		http.Error(w, "Bad request", http.StatusBadRequest)
		return
	}

	for _, alert := range payload.Alerts {
		h.processAlert(alert)
	}

	w.WriteHeader(http.StatusOK)
}

func (h *Handler) processAlert(alert Alert) {
	severity := alert.Labels["severity"]
	namespace := alert.Labels["namespace"]
	alertName := alert.Labels["alertname"]

	statusEmoji := "🚨"
	if alert.Status == "resolved" {
		statusEmoji = "✅"
	} else if severity == "warning" {
		statusEmoji = "⚠️"
	}

	text := fmt.Sprintf("%s **АЛЕРТ [%s]**\nИмя: %s\nNamespace: %s\nОписание: %s",
		statusEmoji,
		alert.Status,
		alertName,
		namespace,
		alert.Annotations["description"],
	)

	// Триггер автоматического восстановления
	if namespace == "demo" && alert.Status == "firing" {
		text += "\n\n🛠 *Запущено автоматическое восстановление (Remediator)...*"
		go h.runRemediation(alert.Labels["service"])
	}

	tgMsg := tgbotapi.NewMessage(h.chatId, text)
	tgMsg.ParseMode = "Markdown"

	if _, err := h.bot.Send(tgMsg); err != nil {
		log.Printf("[ERROR] Не удалось отправить сообщение в Telegram: %v", err)
	}
}

func (h *Handler) runRemediation(serviceName string) {
	log.Printf("[INFO] Выполняю автоматический перезапуск сервиса: %s", serviceName)
	// Ваша логика перезапуска (kubectl, docker, bash-скрипт)
}
