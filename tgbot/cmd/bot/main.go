package main

import (
	"log"
	"main/internal/alert"
	"main/internal/chats"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
	"github.com/joho/godotenv"
)

const pathToEnv = ".env"

type config struct {
	token     string
	pinned    []int64 // TELEGRAM_CHAT_ID: необязателен, чаты можно подключать командой /start
	storePath string
	port      string
}

func main() {
	cfg := getConfig()

	var bot *tgbotapi.BotAPI
	if cfg.token == "" {
		log.Println("[WARN] TELEGRAM_BOT_TOKEN не задан: режим без Telegram, алерты и диагностика пишутся в лог.")
	} else if b, err := tgbotapi.NewBotAPI(cfg.token); err != nil {
		// Не падаем: платформа должна работать и с неверным токеном или без доступа к Telegram.
		log.Printf("[ERROR] Не удалось подключиться к Telegram (проверьте TELEGRAM_BOT_TOKEN и сеть): %v. Работаю в режиме лога.", err)
	} else {
		bot = b
		log.Printf("Авторизован в Telegram как @%s", bot.Self.UserName)
	}

	store := chats.Open(cfg.storePath, cfg.pinned...)
	alertHandler := alert.NewHandler(bot, store)

	mux := http.NewServeMux()
	alertHandler.RegisterRoutes(mux)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("ok")) })

	if bot != nil {
		// Long polling: команды /start, /stop и нажатия на инлайн-кнопки.
		go func() {
			u := tgbotapi.NewUpdate(0)
			u.Timeout = 60
			u.AllowedUpdates = []string{"message", "callback_query"}
			for update := range bot.GetUpdatesChan(u) {
				switch {
				case update.CallbackQuery != nil:
					alertHandler.HandleCallback(update.CallbackQuery)
				case update.Message != nil:
					alertHandler.HandleMessage(update.Message)
				}
			}
		}()
		if len(store.All()) == 0 {
			log.Println("[HINT] Ни один чат не подключён: откройте бота в Telegram и отправьте ему /start.")
		} else {
			alertHandler.Announce("🚀 Бот запущен: принимаю алерты, дописываю ИИ-диагностику, действия выполняются после подтверждения.")
		}
	}

	log.Printf("Бот готов к работе. Ожидание вебхуков от Alertmanager на порту :%s...", cfg.port)
	srv := &http.Server{Addr: ":" + cfg.port, Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	if err := srv.ListenAndServe(); err != nil {
		log.Fatalf("Не удалось запустить HTTP сервер: %v", err)
	}
}

func getConfig() config {
	if err := godotenv.Load(pathToEnv); err != nil {
		log.Println("Файл .env не найден, используются системные переменные окружения")
	}
	cfg := config{
		token:     strings.TrimSpace(os.Getenv("TELEGRAM_BOT_TOKEN")),
		storePath: os.Getenv("CHAT_STORE_PATH"),
		port:      os.Getenv("PORT"),
	}
	if cfg.storePath == "" {
		cfg.storePath = ".tgbot/chats.json"
	}
	if cfg.port == "" {
		cfg.port = "8080"
	}
	// Один или несколько chat id через запятую. Пусто или заглушка из .env.example: чаты подключаются по /start.
	for _, part := range strings.Split(os.Getenv("TELEGRAM_CHAT_ID"), ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		id, err := strconv.ParseInt(part, 10, 64)
		if err != nil {
			log.Printf("[WARN] TELEGRAM_CHAT_ID: %q не число, пропускаю (чат можно подключить командой /start)", part)
			continue
		}
		cfg.pinned = append(cfg.pinned, id)
	}
	return cfg
}
