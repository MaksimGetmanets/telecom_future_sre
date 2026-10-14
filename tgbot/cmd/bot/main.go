package main

import (
	"fmt"
	"os"

	"github.com/joho/godotenv"
)

const pathToEnv = "../../.env"

func main() {
	err := godotenv.Load(pathToEnv)
	if err != nil {
		fmt.Println(err)
	}
	token := os.Getenv("TELEGRAM_BOT_TOKEN")
	chatId := os.Getenv("TELEGRAM_CHAT_ID")
	fmt.Println(token)
	fmt.Println(chatId)
}
