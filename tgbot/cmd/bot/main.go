package main

import (
	"log"
	"main/internal/alert"
	"net/http"
	"os"
	"strconv"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
	"github.com/joho/godotenv"
)

const pathToEnv = ".env"

func main() {
	token, chatId := getConfig()

	bot, err := tgbotapi.NewBotAPI(token)
	if err != nil {
		log.Fatalf("Критическая ошибка инициализации бота: %v", err)
	}

	// Проверка связи
	msg := tgbotapi.NewMessage(chatId, "🚀 Бот запущен: принимаю алерты, дописываю ИИ-диагностику, действия выполняются после подтверждения.")
	if _, err := bot.Send(msg); err != nil {
		log.Printf("Предупреждение: проверьте связь с ботом: %v", err)
	}

	// Инициализируем хендлер алертов
	mux := http.NewServeMux()
	alertHandler := alert.NewHandler(bot, chatId)
	alertHandler.RegisterRoutes(mux)

	// Запускаем Long Polling для обработки нажатий на инлайн-кнопки
	go func() {
		u := tgbotapi.NewUpdate(0)
		u.Timeout = 60
		u.AllowedUpdates = []string{"callback_query"}
		updates := bot.GetUpdatesChan(u)

		for update := range updates {
			// Нас интересуют только клики по кнопкам (CallbackQuery)
			if update.CallbackQuery != nil {
				alertHandler.HandleCallback(update.CallbackQuery)
			}
		}
	}()

	log.Println("Бот готов к работе. Ожидание вебхуков от Alertmanager на порту :8080...")
	if err := http.ListenAndServe(":8080", mux); err != nil {
		log.Fatalf("Не удалось запустить HTTP сервер: %v", err)
	}
}

func getConfig() (token string, chatId int64) {
	if err := godotenv.Load(pathToEnv); err != nil {
		log.Println("Файл .env не найден, используются системные переменные окружения")
	}

	token = os.Getenv("TELEGRAM_BOT_TOKEN")
	chatIdStr := os.Getenv("TELEGRAM_CHAT_ID")

	chatId, err := strconv.ParseInt(chatIdStr, 10, 64)
	if err != nil {
		log.Fatalf("Критическая ошибка: неверный формат TELEGRAM_CHAT_ID: %v", err)
	}

	return token, chatId
}
