package alert

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

const defaultPythonAssistantURL = "http://127.0.0.1:8000/diagnose"

type Handler struct {
	bot    *tgbotapi.BotAPI
	chatId int64
}

func NewHandler(bot *tgbotapi.BotAPI, chatId int64) *Handler {
	return &Handler{
		bot:    bot,
		chatId: chatId,
	}
}

func assistantURL() string {
	if url := os.Getenv("LLM_ASSISTANT_URL"); url != "" {
		return url
	}

	return defaultPythonAssistantURL
}

func (h *Handler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/alert", h.HandleWebhook)
}

func (h *Handler) HandleWebhook(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	defer r.Body.Close()

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

	baseText := fmt.Sprintf(
		"%s *АЛЕРТ [%s]*\nИмя: %s\nNamespace: %s\nОписание: %s",
		statusEmoji,
		alert.Status,
		alertName,
		namespace,
		alert.Annotations["description"],
	)

	if alert.Status != "firing" {
		msg := tgbotapi.NewMessage(h.chatId, baseText)
		msg.ParseMode = "Markdown"

		if _, err := h.bot.Send(msg); err != nil {
			log.Printf("[ERROR] Ошибка отправки алерта: %v", err)
		}
		return
	}

	// Сначала отправляем алерт, чтобы уведомление не потерялось,
	// даже если Python-ассистент временно недоступен.
	msg := tgbotapi.NewMessage(h.chatId, baseText)
	msg.ParseMode = "Markdown"

	sentMsg, err := h.bot.Send(msg)
	if err != nil {
		log.Printf("[ERROR] Ошибка отправки алерта: %v", err)
		return
	}

	// Диагностика будет добавлена в это же сообщение.
	go h.requestAIDiagnosis(alert, sentMsg.MessageID, baseText)
}

func (h *Handler) requestAIDiagnosis(
	alert Alert,
	parentMsgID int,
	baseText string,
) {
	jsonData, err := json.Marshal(alert)
	if err != nil {
		log.Printf("[ERROR] Ошибка маршалинга алерта: %v", err)
		h.appendDiagnosisError(parentMsgID, baseText, "не удалось подготовить запрос")
		return
	}

	client := &http.Client{
		Timeout: 35 * time.Second,
	}

	req, err := http.NewRequest(
		http.MethodPost,
		assistantURL(),
		bytes.NewReader(jsonData),
	)
	if err != nil {
		log.Printf("[ERROR] Ошибка создания запроса к ИИ: %v", err)
		h.appendDiagnosisError(parentMsgID, baseText, "не удалось создать запрос")
		return
	}

	req.Header.Set("Content-Type", "application/json")

	// Токен необязателен, если DIAGNOSE_TOKEN не настроен на Python-сервисе.
	if token := os.Getenv("DIAGNOSE_TOKEN"); token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}

	resp, err := client.Do(req)
	if err != nil {
		log.Printf("[ERROR] Python-ассистент недоступен: %v", err)
		h.appendDiagnosisError(parentMsgID, baseText, "Python-ассистент недоступен")
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		log.Printf(
			"[ERROR] Python-ассистент вернул HTTP %d: %s",
			resp.StatusCode,
			strings.TrimSpace(string(body)),
		)

		h.appendDiagnosisError(
			parentMsgID,
			baseText,
			fmt.Sprintf("ассистент вернул HTTP %d", resp.StatusCode),
		)
		return
	}

	var diag struct {
		Hypothesis      string   `json:"hypothesis"`
		Confidence      float64  `json:"confidence"`
		Evidence        []string `json:"evidence"`
		Validated       bool     `json:"validated"`
		RejectedReason  string   `json:"rejected_reason"`
		Model           string   `json:"model"`
		FallbackReason  *string  `json:"fallback_reason"`
		SuggestedAction struct {
			Type       string `json:"type"`
			Deployment string `json:"deployment"`
			Replicas   int    `json:"replicas"`
		} `json:"suggested_action"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&diag); err != nil {
		log.Printf("[ERROR] Ошибка декодирования ответа ИИ: %v", err)
		h.appendDiagnosisError(parentMsgID, baseText, "не удалось прочитать ответ ассистента")
		return
	}

	var result strings.Builder

	model := diag.Model
	if model == "" {
		model = "не указан"
	}

	fmt.Fprintf(
		&result,
		"\n\n🧠 *Диагностика (%s)*\n\n*Гипотеза:* %s\n*Уверенность:* %.2f",
		model,
		diag.Hypothesis,
		diag.Confidence,
	)

	if len(diag.Evidence) > 0 {
		result.WriteString("\n\n*Подтверждающие данные:*\n")

		for _, evidence := range diag.Evidence {
			fmt.Fprintf(&result, "• %s\n", evidence)
		}
	}

	if diag.FallbackReason != nil && *diag.FallbackReason != "" {
		fmt.Fprintf(
			&result,
			"\n⚠️ Причина перехода в резервный режим: %s",
			*diag.FallbackReason,
		)
	}

	action := diag.SuggestedAction

	if !diag.Validated {
		if diag.RejectedReason != "" {
			fmt.Fprintf(
				&result,
				"\n\n⚠️ *Предлагаемое действие отклонено проверкой:* %s",
				diag.RejectedReason,
			)
		} else {
			result.WriteString("\n\n⚠️ Предлагаемое действие не прошло проверку.")
		}
	} else if action.Type == "" || action.Type == "none" {
		result.WriteString("\n\nАвтоматическое действие не предлагается.")
	} else {
		fmt.Fprintf(
			&result,
			"\n\n*Предлагаемое действие:* %s — `%s`",
			action.Type,
			action.Deployment,
		)

		if action.Type == "scale" {
			fmt.Fprintf(&result, " до %d реплик", action.Replicas)
		}

		// Кнопку исполнения пока не добавляем:
		// реальная ремедиация в runRemediation ещё не реализована.
		result.WriteString(
			"\nВыполнение действия пока не подключено.",
		)
	}

	edit := tgbotapi.NewEditMessageText(
		h.chatId,
		parentMsgID,
		baseText+result.String(),
	)
	edit.ParseMode = "Markdown"

	if _, err := h.bot.Send(edit); err != nil {
		log.Printf("[ERROR] Не удалось обновить сообщение алерта: %v", err)
	}
}

func (h *Handler) appendDiagnosisError(
	messageID int,
	baseText string,
	reason string,
) {
	text := baseText + "\n\n⚠️ *Не удалось получить ИИ-диагностику:* " + reason

	edit := tgbotapi.NewEditMessageText(
		h.chatId,
		messageID,
		text,
	)
	edit.ParseMode = "Markdown"

	if _, err := h.bot.Send(edit); err != nil {
		log.Printf("[ERROR] Не удалось добавить ошибку диагностики в Telegram: %v", err)
	}
}

// Обработчик оставлен для старых сообщений с кнопками.
// Новые кнопки не создаются, пока выполнение ремедиации не реализовано.
func (h *Handler) HandleCallback(cb *tgbotapi.CallbackQuery) {
	if cb == nil || cb.Data == "" || !strings.HasPrefix(cb.Data, "exec:") {
		return
	}

	_, err := h.bot.Request(
		tgbotapi.NewCallback(
			cb.ID,
			"Действие пока не выполняется: ремедиация не подключена",
		),
	)
	if err != nil {
		log.Printf("[ERROR] Не удалось ответить на нажатие кнопки: %v", err)
	}

	log.Printf(
		"[WARN] Запрошено действие через старую кнопку, но выполнение не подключено: %s",
		cb.Data,
	)

	parts := strings.Split(cb.Data, ":")
	if len(parts) < 4 || cb.Message == nil {
		return
	}

	updatedText := cb.Message.Text +
		"\n\n⚠️ Действие не выполнено: механизм ремедиации ещё не подключён."

	edit := tgbotapi.NewEditMessageText(
		h.chatId,
		cb.Message.MessageID,
		updatedText,
	)
	edit.ParseMode = "Markdown"
	edit.ReplyMarkup = &tgbotapi.InlineKeyboardMarkup{
		InlineKeyboard: [][]tgbotapi.InlineKeyboardButton{},
	}

	if _, err := h.bot.Send(edit); err != nil {
		log.Printf("[ERROR] Не удалось обновить сообщение после нажатия: %v", err)
	}

	// Разбираем данные старой кнопки, чтобы проверить формат.
	_, _ = strconv.Atoi(parts[3])
}
