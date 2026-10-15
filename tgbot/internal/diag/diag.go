// Package diag: разбор ответа LLM-ассистента, оформление сообщения для Telegram (HTML)
// и клиент remediator для действий, подтверждённых человеком.
// Пакет не зависит от Telegram-библиотеки, поэтому покрыт обычными тестами `go test`.
package diag

import (
	"encoding/json"
	"fmt"
	"html"
	"io"
	"regexp"
	"strconv"
	"strings"
)

// Action: действие, которое предложил ассистент (уже прошло проверку на стороне llm-assistant).
type Action struct {
	Type       string `json:"type"`
	Deployment string `json:"deployment"`
	Replicas   int    `json:"replicas"`
}

// Diagnosis: ответ POST /diagnose.
type Diagnosis struct {
	Hypothesis     string   `json:"hypothesis"`
	Confidence     float64  `json:"confidence"`
	Evidence       []string `json:"evidence"`
	Validated      bool     `json:"validated"`
	RejectedReason string   `json:"rejected_reason"`
	Model          string   `json:"model"`
	FallbackReason *string  `json:"fallback_reason"`
	Suggested      Action   `json:"suggested_action"`
}

const (
	maxHypothesis = 600
	maxEvidence   = 300
	maxItems      = 6
)

// Parse читает ответ ассистента.
func Parse(r io.Reader) (Diagnosis, error) {
	var d Diagnosis
	if err := json.NewDecoder(io.LimitReader(r, 1<<20)).Decode(&d); err != nil {
		return Diagnosis{}, err
	}
	return d, nil
}

// Actionable: кнопку «Выполнить» показываем, только если ассистент предложил restart или scale
// и его предложение прошло проверку (белый список, namespace, лимит реплик).
func (d Diagnosis) Actionable() bool {
	return d.Validated && d.Suggested.Deployment != "" &&
		(d.Suggested.Type == "restart" || d.Suggested.Type == "scale")
}

// Esc экранирует текст для parse_mode=HTML. Всё, что приходит из алертов и от LLM, должно идти через него:
// символы _ * ` [ ломали Markdown, и Telegram отклонял сообщение целиком.
func Esc(s string) string { return html.EscapeString(s) }

func cut(s string, n int) string {
	r := []rune(strings.TrimSpace(s))
	if len(r) <= n {
		return string(r)
	}
	return string(r[:n]) + "…"
}

// FormatHTML: блок диагностики, который дописывается к сообщению алерта.
func FormatHTML(d Diagnosis) string {
	var b strings.Builder
	model := d.Model
	if model == "" {
		model = "не указан"
	}
	fmt.Fprintf(&b, "\n\n🧠 <b>Диагностика (%s)</b>\n\n<b>Гипотеза:</b> %s\n<b>Уверенность:</b> %.2f",
		Esc(model), Esc(cut(d.Hypothesis, maxHypothesis)), d.Confidence)

	if n := len(d.Evidence); n > 0 {
		b.WriteString("\n\n<b>Подтверждающие данные:</b>\n")
		for i, e := range d.Evidence {
			if i == maxItems {
				break
			}
			fmt.Fprintf(&b, "• %s\n", Esc(cut(e, maxEvidence)))
		}
	}
	if d.FallbackReason != nil && *d.FallbackReason != "" {
		fmt.Fprintf(&b, "\n⚠️ Резервный режим (правила): %s", Esc(cut(*d.FallbackReason, maxEvidence)))
	}

	a := d.Suggested
	switch {
	case !d.Validated && d.RejectedReason != "":
		fmt.Fprintf(&b, "\n\n⚠️ <b>Предложение отклонено проверкой:</b> %s", Esc(d.RejectedReason))
	case !d.Validated:
		b.WriteString("\n\n⚠️ Предложение не прошло проверку.")
	case a.Type == "" || a.Type == "none":
		b.WriteString("\n\nАвтоматическое действие не предлагается.")
	case d.Actionable():
		fmt.Fprintf(&b, "\n\n<b>Предлагаемое действие:</b> %s <code>%s</code>", Esc(a.Type), Esc(a.Deployment))
		if a.Type == "scale" {
			fmt.Fprintf(&b, " до %d реплик", a.Replicas)
		}
		b.WriteString("\nМодель только советует: выполнится после вашего подтверждения.")
	default:
		fmt.Fprintf(&b, "\n\nДействие %s не выполняется из бота.", Esc(a.Type))
	}
	return b.String()
}

// --- данные кнопок (Telegram разрешает до 64 байт) ---

var nameRe = regexp.MustCompile(`^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$`)

// Callback: разобранное нажатие кнопки.
type Callback struct {
	Reject     bool
	Action     string
	Namespace  string
	Deployment string
	Replicas   int
}

// EncodeExec: "x|restart|demo|orders|0".
func EncodeExec(namespace string, a Action) string {
	return fmt.Sprintf("x|%s|%s|%s|%d", a.Type, namespace, a.Deployment, a.Replicas)
}

// EncodeReject: кнопка «Отклонить».
func EncodeReject() string { return "n" }

// ParseCallback проверяет данные кнопки заново: из чата они приходят «как есть» и им нельзя верить.
func ParseCallback(data string) (Callback, error) {
	if data == "n" {
		return Callback{Reject: true}, nil
	}
	parts := strings.Split(data, "|")
	if len(parts) != 5 || parts[0] != "x" {
		return Callback{}, fmt.Errorf("неизвестный формат кнопки")
	}
	action, ns, dep := parts[1], parts[2], parts[3]
	if action != "restart" && action != "scale" {
		return Callback{}, fmt.Errorf("действие %q не разрешено", action)
	}
	if !nameRe.MatchString(ns) || !nameRe.MatchString(dep) {
		return Callback{}, fmt.Errorf("недопустимое имя namespace или deployment")
	}
	replicas, err := strconv.Atoi(parts[4])
	if err != nil || replicas < 0 || replicas > 10 {
		return Callback{}, fmt.Errorf("недопустимое число реплик")
	}
	return Callback{Action: action, Namespace: ns, Deployment: dep, Replicas: replicas}, nil
}

var tagRe = regexp.MustCompile(`</?[a-z]+[^>]*>`)

// PlainText убирает HTML-теги разметки. Нужен как запасной вариант: если Telegram всё же отклонил разметку,
// сообщение отправляется простым текстом, а не теряется.
func PlainText(s string) string { return html.UnescapeString(tagRe.ReplaceAllString(s, "")) }

// Trunc обрезает строку по числу символов (не байт) и добавляет «…».
func Trunc(s string, n int) string { return cut(s, n) }
