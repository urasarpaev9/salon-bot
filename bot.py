import os
from telegram.ext import Application, CommandHandler, ContextTypes

async def start(update, context):
    await update.message.reply_text("✅ Бот работает!")

def main():
    app = Application.builder().token(os.getenv("8544508419:AAEcYmgyx-jd1hgiVWrbiryGMMRBGfmhBAQ")).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()