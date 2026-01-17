import os
from telegram.ext import Application, CommandHandler, ContextTypes

# Получаем токен из переменной окружения с именем "BOT_TOKEN"
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в переменных окружения!")

async def start(update, context):
    await update.message.reply_text("✅ Бот работает!")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()