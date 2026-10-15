package alert

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

const pythonAssistantURL = "http://127.0.0"

type Handler struct {
	bot    *tgbotapi.BotAPI
	chatId int64
}

func NewHandler(bot *tgbotapi.BotAPI, chatId int64) *Handler {
	return &Handler{bot: bot, chatId: chatId}
}

func (h *Handler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/alert", h.HandleWebhook)
}

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
		statusEmoji, alert.Status, alertName, namespace, alert.Annotations["description"])

	tgMsg := tgbotapi.NewMessage(h.chatId, text)
	tgMsg.ParseMode = "Markdown"

	sentMsg, err := h.bot.Send(tgMsg)
	if err != nil {
		log.Printf("[ERROR] Ошибка отправки базового алерта: %v", err)
		return
	}

	// Запускаем ИИ-диагностику только для активных инцидентов
	if alert.Status == "firing" {
		go h.requestAIDiagnosis(alert, sentMsg.MessageID)
	}
}

func (h *Handler) requestAIDiagnosis(alert Alert, parentMsgID int) {
	jsonData, err := json.Marshal(alert)
	if err != nil {
		log.Printf("[ERROR] Ошибка маршалинга для ИИ: %v", err)
		return
	}

	client := &http.Client{Timeout: 35 * time.Second}
	req, err := http.NewRequest("POST", pythonAssistantURL, bytes.NewBuffer(jsonData))
	if err != nil {
		log.Printf("[ERROR] Ошибка создания запроса к ИИ: %v", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		log.Printf("[ERROR] ИИ-сервис на Python недоступен: %v", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("[ERROR] Python ИИ-сервис вернул статус %d", resp.StatusCode)
		return
	}

	var diag struct {
		Hypothesis      string   `json:"hypothesis"`
		Confidence      float64  `json:"confidence"`
		Evidence        []string `json:"evidence"`
		Validated       bool     `json:"validated"`
		RejectedReason  string   `json:"rejected_reason"`
		Model           string   `json:"model"`
		SuggestedAction struct {
			Type       string `json:"type"`
			Deployment string `json:"deployment"`
			Replicas   int    `json:"replicas"`
		} `json:"suggested_action"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&diag); err != nil {
		log.Printf("[ERROR] Ошибка декодирования ответа ИИ: %v", err)
		return
	}

	aiText := fmt.Sprintf("🧠 *Диагноз ИИ (%s)*\n\n*Гипотеза:* %s\n*Уверенность:* %.2f\n\n",
		diag.Model, diag.Hypothesis, diag.Confidence)

	if len(diag.Evidence) > 0 {
		aiText += "*Улики:*\n"
		for _, e := range diag.Evidence {
			aiText += fmt.Sprintf("• `%s`\n", e)
		}
		aiText += "\n"
	}

	replyMsg := tgbotapi.NewMessage(h.chatId, aiText)
	replyMsg.ReplyToMessageID = parentMsgID
	replyMsg.ParseMode = "Markdown"

	actionType := diag.SuggestedAction.Type
	if diag.Validated && actionType != "none" {
		buttonText := ""
		switch actionType {
		case "restart":
			buttonText = fmt.Sprintf("🔄 Перезапустить %s", diag.SuggestedAction.Deployment)
		case "scale":
			buttonText = fmt.Sprintf("📈 Нарастить %s до %d реплик", diag.SuggestedAction.Deployment, diag.SuggestedAction.Replicas)
		case "rollback":
			buttonText = fmt.Sprintf("⏪ Откатить %s", diag.SuggestedAction.Deployment)
		}

		// Формат callback-даты: exec:<action>:<deployment>:<replicas>
		callbackData := fmt.Sprintf("exec:%s:%s:%d", actionType, diag.SuggestedAction.Deployment, diag.SuggestedAction.Replicas)
		replyMsg.ReplyMarkup = tgbotapi.NewInlineKeyboardMarkup(
			tgbotapi.NewInlineKeyboardRow(tgbotapi.NewInlineKeyboardButtonData(buttonText, callbackData)),
		)
	} else if diag.RejectedReason != "" {
		replyMsg.Text += fmt.Sprintf("⚠️ *Авто-действие заблокировано:* %s", diag.RejectedReason)
	}

	if _, err := h.bot.Send(replyMsg); err != nil {
		log.Printf("[ERROR] Ошибка отправки диагноза в Telegram: %v", err)
	}
}

// HandleCallback перехватывает клики по кнопкам под диагнозом
// HandleCallback перехватывает клики по кнопкам под диагнозом
func (h *Handler) HandleCallback(cb *tgbotapi.CallbackQuery) {
	// ИСПРАВЛЕНО: strings.HasPrefix вместо strings.Prefix
	if cb.Data == "" || !strings.HasPrefix(cb.Data, "exec:") {
		return
	}

	// Парсим данные из кнопки: exec:scale:orders:3
	parts := strings.Split(cb.Data, ":")
	if len(parts) < 4 {
		return
	}
	actionType := parts[1]
	deployment := parts[2]
	replicas, _ := strconv.Atoi(parts[3])

	// Всплывающее уведомление в клиенте Telegram, чтобы кнопка "отжалась"
	alertUser := tgbotapi.NewCallback(cb.ID, fmt.Sprintf("Запущено: %s для %s", actionType, deployment))
	h.bot.Request(alertUser)

	// Запускаем реальный процесс ремедиации в фоне
	go h.runRemediation(actionType, deployment, replicas)

	// Обновляем исходное сообщение: убираем кнопку и пишем, кто применил фикс
	userWhoPressed := cb.From.FirstName
	if cb.From.UserName != "" {
		userWhoPressed = "@" + cb.From.UserName
	}

	statusText := fmt.Sprintf("\n\n⚙️ *Применено действие:* `%s` инженером %s", actionType, userWhoPressed)
	updatedText := cb.Message.Text + statusText

	// Формируем конфигурацию для изменения текста сообщения
	editMsg := tgbotapi.NewEditMessageText(h.chatId, cb.Message.MessageID, updatedText)
	editMsg.ParseMode = "Markdown"

	// Передаем пустую клавиатуру, чтобы полностью скрыть кнопку после клика
	emptyKeyboard := tgbotapi.NewInlineKeyboardMarkup([]tgbotapi.InlineKeyboardButton{})
	editMsg.ReplyMarkup = &emptyKeyboard

	// ИСПРАВЛЕНО: h.bot.Send вместо несуществующего McChat
	if _, err := h.bot.Send(editMsg); err != nil {
		log.Printf("[ERROR] Не удалось обновить инлайн-кнопку: %v", err)
	}
}

func (h *Handler) runRemediation(actionType, deployment string, replicas int) {
	log.Printf("[INFO] Выполняю экшен '%s' над деплоем '%s' (целевые реплики: %d)", actionType, deployment, replicas)
	// Сюда вставляй свой kubectl patch, bash скрипт или вызовы Kubernetes Go Client SDK
}
