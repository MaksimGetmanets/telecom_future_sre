package alert

import (
	"bytes"
	"context"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"

	"main/internal/chats"
	"main/internal/diag"
)

// По умолчанию ассистент доступен через `kubectl -n monitoring port-forward svc/llm-assistant 8089:8080`.
const defaultAssistantURL = "http://127.0.0.1:8089/diagnose"

// Кнопки старше этого срока не выполняются: ситуация уже могла измениться.
const callbackTTL = 30 * time.Minute

// Telegram принимает не больше 4096 знаков в сообщении.
const maxMessageRunes = 3900

type Handler struct {
	// bot == nil: режим без Telegram, алерты и диагностика пишутся только в лог.
	bot *tgbotapi.BotAPI
	// chats: чаты, подключённые командой /start (и закреплённый TELEGRAM_CHAT_ID).
	chats *chats.Store
	// rem == nil, если REMEDIATOR_URL не задан: тогда бот только показывает диагностику, без кнопок.
	rem *diag.Client
	// registerCode: если задан (REGISTER_CODE), подключиться можно только командой /start <код>.
	registerCode string
}

func NewHandler(bot *tgbotapi.BotAPI, store *chats.Store) *Handler {
	return &Handler{
		bot:          bot,
		chats:        store,
		rem:          diag.NewClient(os.Getenv("REMEDIATOR_URL"), os.Getenv("REMEDIATOR_TOKEN")),
		registerCode: strings.TrimSpace(os.Getenv("REGISTER_CODE")),
	}
}

// sentMsg: сообщение, отправленное в конкретный чат (диагностика потом дописывается в каждое из них).
type sentMsg struct {
	chatID    int64
	messageID int
}

func assistantURL() string {
	if url := os.Getenv("LLM_ASSISTANT_URL"); url != "" {
		return url
	}
	return defaultAssistantURL
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

// sendHTML отправляет сообщение с разметкой HTML. Если Telegram отклонил разметку, шлёт тот же текст без тегов:
// алерт не должен теряться из-за форматирования.
func (h *Handler) sendHTML(chatID int64, text string, replyTo int, markup *tgbotapi.InlineKeyboardMarkup) (tgbotapi.Message, error) {
	msg := tgbotapi.NewMessage(chatID, text)
	msg.ParseMode = tgbotapi.ModeHTML
	msg.ReplyToMessageID = replyTo
	if markup != nil {
		msg.ReplyMarkup = *markup
	}
	sent, err := h.bot.Send(msg)
	if err != nil && strings.Contains(err.Error(), "parse entities") {
		log.Printf("[WARN] Telegram отклонил HTML, отправляю простым текстом: %v", err)
		msg.Text = diag.PlainText(text)
		msg.ParseMode = ""
		return h.bot.Send(msg)
	}
	return sent, err
}

func (h *Handler) editHTML(chatID int64, messageID int, text string, markup *tgbotapi.InlineKeyboardMarkup) error {
	edit := tgbotapi.NewEditMessageText(chatID, messageID, text)
	edit.ParseMode = tgbotapi.ModeHTML
	edit.ReplyMarkup = markup
	_, err := h.bot.Send(edit)
	if err != nil && strings.Contains(err.Error(), "parse entities") {
		log.Printf("[WARN] Telegram отклонил HTML при правке, обновляю простым текстом: %v", err)
		edit.Text = diag.PlainText(text)
		edit.ParseMode = ""
		_, err = h.bot.Send(edit)
	}
	return err
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

	// Всё, что пришло из алерта, экранируем: описания часто содержат символы _ * < > &.
	baseText := fmt.Sprintf(
		"%s <b>АЛЕРТ [%s]</b>\nИмя: %s\nNamespace: %s\nОписание: %s",
		statusEmoji,
		diag.Esc(alert.Status),
		diag.Esc(alertName),
		diag.Esc(namespace),
		diag.Esc(diag.Trunc(alert.Annotations["description"], 500)),
	)

	sent := h.broadcast(baseText)
	if alert.Status != "firing" {
		return
	}
	// Алерт уже отправлен, поэтому он не потеряется, даже если ассистент недоступен.
	// Диагностика дописывается в эти же сообщения (или пишется в лог, если нет ни бота, ни подключённых чатов).
	go h.requestAIDiagnosis(alert, sent, baseText)
}

// broadcast отправляет сообщение во все подключённые чаты. Без бота или без подключённых чатов пишет в лог:
// платформа должна работать и без Telegram.
func (h *Handler) broadcast(text string) []sentMsg {
	targets := h.chats.All()
	if h.bot == nil || len(targets) == 0 {
		log.Printf("[MSG] %s", oneLine(text))
		if h.bot != nil {
			log.Printf("[HINT] ни один чат не подключён: напишите боту /start")
		}
		return nil
	}
	var sent []sentMsg
	for _, id := range targets {
		m, err := h.sendHTML(id, text, 0, nil)
		if err != nil {
			log.Printf("[ERROR] Ошибка отправки в чат %d: %v", id, err)
			continue
		}
		sent = append(sent, sentMsg{chatID: id, messageID: m.MessageID})
	}
	return sent
}

// Announce: сообщение всем подключённым чатам (например, о запуске бота).
func (h *Handler) Announce(text string) { h.broadcast(text) }

func oneLine(htmlText string) string {
	var parts []string
	for _, line := range strings.Split(diag.PlainText(htmlText), "\n") {
		if line = strings.TrimSpace(line); line != "" {
			parts = append(parts, line)
		}
	}
	return strings.Join(parts, " | ")
}

func (h *Handler) requestAIDiagnosis(alert Alert, sent []sentMsg, baseText string) {
	jsonData, err := json.Marshal(alert)
	if err != nil {
		log.Printf("[ERROR] Ошибка маршалинга алерта: %v", err)
		h.appendDiagnosisError(sent, baseText, "не удалось подготовить запрос")
		return
	}

	req, err := http.NewRequest(http.MethodPost, assistantURL(), bytes.NewReader(jsonData))
	if err != nil {
		log.Printf("[ERROR] Ошибка создания запроса к ИИ: %v", err)
		h.appendDiagnosisError(sent, baseText, "не удалось создать запрос")
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if token := os.Getenv("DIAGNOSE_TOKEN"); token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}

	resp, err := (&http.Client{Timeout: 35 * time.Second}).Do(req)
	if err != nil {
		log.Printf("[ERROR] LLM-ассистент недоступен: %v", err)
		h.appendDiagnosisError(sent, baseText, "ассистент недоступен")
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		log.Printf("[ERROR] LLM-ассистент вернул HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
		h.appendDiagnosisError(sent, baseText, fmt.Sprintf("ассистент вернул HTTP %d", resp.StatusCode))
		return
	}

	d, err := diag.Parse(resp.Body)
	if err != nil {
		log.Printf("[ERROR] Ошибка декодирования ответа ИИ: %v", err)
		h.appendDiagnosisError(sent, baseText, "не удалось прочитать ответ ассистента")
		return
	}

	text := baseText + diag.FormatHTML(d)
	if len([]rune(text)) > maxMessageRunes {
		text = diag.Trunc(baseText, 1000) + diag.Trunc(diag.FormatHTML(d), maxMessageRunes-1000)
	}
	if len(sent) == 0 {
		log.Printf("[DIAG] %s", oneLine(diag.FormatHTML(d)))
		return
	}
	markup := h.keyboard(alert.Labels["namespace"], d)
	for _, m := range sent {
		if err := h.editHTML(m.chatID, m.messageID, text, markup); err != nil {
			log.Printf("[ERROR] Не удалось обновить сообщение алерта в чате %d: %v", m.chatID, err)
		}
	}
}

// keyboard: кнопки подтверждения, только если ассистент предложил проверенное действие и remediator настроен.
func (h *Handler) keyboard(namespace string, d diag.Diagnosis) *tgbotapi.InlineKeyboardMarkup {
	if h.rem == nil || namespace == "" || !d.Actionable() {
		return nil
	}
	label := fmt.Sprintf("✅ Выполнить: %s %s", d.Suggested.Type, d.Suggested.Deployment)
	if d.Suggested.Type == "rollback" {
		label = fmt.Sprintf("↩️ Выполнить: rollback %s", d.Suggested.Deployment)
	}
	if d.Suggested.Type == "scale" {
		label += fmt.Sprintf(" → %d", d.Suggested.Replicas)
	}
	m := tgbotapi.NewInlineKeyboardMarkup(
		tgbotapi.NewInlineKeyboardRow(
			tgbotapi.NewInlineKeyboardButtonData(label, diag.EncodeExec(namespace, d.Suggested)),
			tgbotapi.NewInlineKeyboardButtonData("❌ Отклонить", diag.EncodeReject()),
		),
	)
	return &m
}

func (h *Handler) appendDiagnosisError(sent []sentMsg, baseText, reason string) {
	if len(sent) == 0 {
		log.Printf("[DIAG] не удалось получить ИИ-диагностику: %s", reason)
		return
	}
	text := baseText + "\n\n⚠️ <b>Не удалось получить ИИ-диагностику:</b> " + diag.Esc(reason)
	for _, m := range sent {
		if err := h.editHTML(m.chatID, m.messageID, text, nil); err != nil {
			log.Printf("[ERROR] Не удалось добавить ошибку диагностики в чат %d: %v", m.chatID, err)
		}
	}
}

func (h *Handler) answer(callbackID, text string) {
	if h.bot == nil {
		return
	}
	if _, err := h.bot.Request(tgbotapi.NewCallback(callbackID, text)); err != nil {
		log.Printf("[ERROR] Не удалось ответить на нажатие кнопки: %v", err)
	}
}

func (h *Handler) clearKeyboard(m *tgbotapi.Message) {
	empty := tgbotapi.InlineKeyboardMarkup{InlineKeyboard: [][]tgbotapi.InlineKeyboardButton{}}
	if _, err := h.bot.Request(tgbotapi.NewEditMessageReplyMarkup(m.Chat.ID, m.MessageID, empty)); err != nil {
		log.Printf("[WARN] Не удалось убрать кнопки: %v", err)
	}
}

func userLabel(u *tgbotapi.User) string {
	switch {
	case u == nil:
		return "неизвестный пользователь"
	case u.UserName != "":
		return "@" + u.UserName
	default:
		return fmt.Sprintf("id %d", u.ID)
	}
}

// HandleCallback: нажатие кнопки «Выполнить» или «Отклонить» под диагностикой.
// Бот ничего не решает сам: действие выполняет remediator со всеми своими ограничениями.
func (h *Handler) HandleCallback(cb *tgbotapi.CallbackQuery) {
	if cb == nil || cb.Message == nil || h.bot == nil {
		return
	}
	// Принимаем кнопки только из подключённых чатов.
	if cb.Message.Chat == nil || !h.chats.Has(cb.Message.Chat.ID) {
		log.Printf("[WARN] Кнопка из постороннего чата отклонена (пользователь %s)", userLabel(cb.From))
		h.answer(cb.ID, "Нет доступа")
		return
	}
	if time.Since(time.Unix(int64(cb.Message.Date), 0)) > callbackTTL {
		h.answer(cb.ID, "Кнопка устарела, дождитесь нового алерта")
		h.clearKeyboard(cb.Message)
		return
	}
	parsed, err := diag.ParseCallback(cb.Data)
	if err != nil {
		log.Printf("[WARN] Некорректные данные кнопки %q: %v", cb.Data, err)
		h.answer(cb.ID, "Некорректная кнопка")
		return
	}

	who := userLabel(cb.From)
	// Сначала убираем кнопки: повторное нажатие не отправит второй запрос.
	h.clearKeyboard(cb.Message)

	if parsed.Reject {
		h.answer(cb.ID, "Отклонено")
		if _, err := h.sendHTML(cb.Message.Chat.ID, "❌ Предложение отклонено: "+diag.Esc(who), cb.Message.MessageID, nil); err != nil {
			log.Printf("[ERROR] Не удалось сообщить об отклонении: %v", err)
		}
		return
	}
	if h.rem == nil {
		h.answer(cb.ID, "remediator не подключён")
		return
	}

	h.answer(cb.ID, "Выполняю…")
	log.Printf("[INFO] %s подтвердил %s %s/%s", who, parsed.Action, parsed.Namespace, parsed.Deployment)

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	res, err := h.rem.Execute(ctx, parsed)
	text := ""
	if err != nil {
		log.Printf("[ERROR] Ошибка выполнения действия: %v", err)
		text = "❌ Не удалось выполнить действие: " + diag.Esc(err.Error())
	} else {
		text = res.FormatHTML() + "\nПодтвердил: " + diag.Esc(who)
	}
	if _, err := h.sendHTML(cb.Message.Chat.ID, text, cb.Message.MessageID, nil); err != nil {
		log.Printf("[ERROR] Не удалось сообщить результат действия: %v", err)
	}
}

// HandleMessage: команды /start (подключить чат) и /stop (отключить). Остальные сообщения игнорируются.
func (h *Handler) HandleMessage(m *tgbotapi.Message) {
	if m == nil || m.Chat == nil || h.bot == nil || !m.IsCommand() {
		return
	}
	chatID := m.Chat.ID
	reply := func(text string) {
		if _, err := h.sendHTML(chatID, text, 0, nil); err != nil {
			log.Printf("[ERROR] Не удалось ответить на команду в чате %d: %v", chatID, err)
		}
	}
	switch m.Command() {
	case "start":
		if h.registerCode != "" &&
			subtle.ConstantTimeCompare([]byte(strings.TrimSpace(m.CommandArguments())), []byte(h.registerCode)) != 1 {
			log.Printf("[WARN] /start без верного кода из чата %d (%s)", chatID, userLabel(m.From))
			reply("Чтобы подключить чат, отправьте <code>/start КОД</code>.")
			return
		}
		added, err := h.chats.Add(chatID)
		if err != nil {
			log.Printf("[WARN] Не удалось сохранить список чатов (чат подключён до перезапуска бота): %v", err)
		}
		if !added {
			reply(fmt.Sprintf("ℹ️ Этот чат уже подключён. Chat id: <code>%d</code>", chatID))
			return
		}
		log.Printf("[INFO] Подключён чат %d (%s)", chatID, userLabel(m.From))
		reply(fmt.Sprintf("✅ <b>Чат подключён.</b>\nСюда будут приходить алерты SRE-платформы с ИИ-диагностикой и кнопками действий.\n"+
			"Chat id: <code>%d</code>\nОтключить: /stop", chatID))
	case "stop":
		removed, err := h.chats.Remove(chatID)
		if err != nil {
			log.Printf("[WARN] Не удалось сохранить список чатов: %v", err)
		}
		switch {
		case removed:
			log.Printf("[INFO] Отключён чат %d (%s)", chatID, userLabel(m.From))
			reply("🔕 Чат отключён. Подключить снова: /start")
		case h.chats.Has(chatID):
			reply("Этот чат закреплён в конфигурации бота (TELEGRAM_CHAT_ID), командой его не отключить.")
		default:
			reply("Этот чат и не был подключён.")
		}
	}
}
