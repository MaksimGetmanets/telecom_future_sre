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

const pythonAssistantURL = "http://127.0.0.1:8000/diagnose"

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

	// Формируем основную часть сообщения.
	text := fmt.Sprintf(
		"%s *АЛЕРТ [%s]*\nИмя: %s\nNamespace: %s\nОписание: %s",
		statusEmoji,
		alert.Status,
		alertName,
		namespace,
		alert.Annotations["description"],
	)

	msg := tgbotapi.NewMessage(h.chatId, text)
	msg.ParseMode = "Markdown"

	// Закрытые инциденты отправляем без ИИ.
	if alert.Status != "firing" {
		if _, err := h.bot.Send(msg); err != nil {
			log.Printf("[ERROR] Ошибка отправки алерта: %v", err)
		}
		return
	}

	// Получаем диагноз до отправки сообщения в Telegram.
	diag, err := h.requestAIDiagnosis(alert)
	if err != nil {
		log.Printf("[ERROR] Ошибка ИИ-диагностики: %v", err)
		msg.Text += "\n\n⚠️ Диагностика ИИ временно недоступна."
	} else {
		msg.Text += fmt.Sprintf(
			"\n\n🧠 *Диагноз ИИ (%s)*\n\n"+
				"*Гипотеза:* %s\n"+
				"*Уверенность:* %.2f",
			diag.Model,
			diag.Hypothesis,
			diag.Confidence,
		)

		if len(diag.Evidence) > 0 {
			msg.Text += "\n\n*Обоснование:*\n"
			for _, evidence := range diag.Evidence {
				msg.Text += fmt.Sprintf("• %s\n", evidence)
			}
		}

		if diag.FallbackReason != "" {
			msg.Text += fmt.Sprintf(
				"\n⚠️ Причина перехода на резервный режим: %s",
				diag.FallbackReason,
			)
		}

		action := diag.SuggestedAction

		if diag.Validated && action.Type != "none" {
			var buttonText string

			switch action.Type {
			case "restart":
				buttonText = fmt.Sprintf("🔄 Перезапустить %s", action.Deployment)
			case "scale":
				buttonText = fmt.Sprintf(
					"📈 Масштабировать %s до %d реплик",
					action.Deployment,
					action.Replicas,
				)
			case "rollback":
				buttonText = fmt.Sprintf("⏪ Откатить %s", action.Deployment)
			}

			if buttonText != "" {
				callbackData := fmt.Sprintf(
					"exec:%s:%s:%d",
					action.Type,
					action.Deployment,
					action.Replicas,
				)

				msg.ReplyMarkup = tgbotapi.NewInlineKeyboardMarkup(
					tgbotapi.NewInlineKeyboardRow(
						tgbotapi.NewInlineKeyboardButtonData(
							buttonText,
							callbackData,
						),
					),
				)
			}
		} else if diag.RejectedReason != "" {
			msg.Text += fmt.Sprintf(
				"\n\n⚠️ *Авто-действие заблокировано:* %s",
				diag.RejectedReason,
			)
		}
	}

	// Единственная отправка сообщения для firing-алерта.
	if _, err := h.bot.Send(msg); err != nil {
		log.Printf("[ERROR] Ошибка отправки сообщения в Telegram: %v", err)
	}
}

type diagnosisResponse struct {
	Hypothesis     string   `json:"hypothesis"`
	Confidence     float64  `json:"confidence"`
	Evidence       []string `json:"evidence"`
	Validated      bool     `json:"validated"`
	RejectedReason string   `json:"rejected_reason"`
	Model          string   `json:"model"`
	FallbackReason string   `json:"fallback_reason"`

	SuggestedAction struct {
		Type       string `json:"type"`
		Deployment string `json:"deployment"`
		Replicas   int    `json:"replicas"`
	} `json:"suggested_action"`
}

func (h *Handler) requestAIDiagnosis(
	alert Alert,
) (*diagnosisResponse, error) {
	jsonData, err := json.Marshal(alert)
	if err != nil {
		return nil, fmt.Errorf("ошибка подготовки алерта: %w", err)
	}

	client := &http.Client{
		Timeout: 35 * time.Second,
	}

	req, err := http.NewRequest(
		http.MethodPost,
		pythonAssistantURL,
		bytes.NewBuffer(jsonData),
	)
	if err != nil {
		return nil, fmt.Errorf("ошибка создания запроса: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("Python-сервис недоступен: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf(
			"Python-сервис вернул HTTP %d",
			resp.StatusCode,
		)
	}

	var diag diagnosisResponse
	if err := json.NewDecoder(resp.Body).Decode(&diag); err != nil {
		return nil, fmt.Errorf("ошибка разбора ответа: %w", err)
	}

	return &diag, nil
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
