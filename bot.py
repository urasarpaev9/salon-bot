# bot.py
import os
import sqlite3
import json
from threading import Thread
from dotenv import load_dotenv
from flask import Flask, jsonify

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# === Инициализация базы данных ===
def init_db():
    conn = sqlite3.connect('salon.db')
    c = conn.cursor()
    # Мастера
    c.execute('''CREATE TABLE IF NOT EXISTS masters (
        id INTEGER PRIMARY KEY,
        name TEXT,
        photo_url TEXT,
        services TEXT
    )''')
    # Расписание
    c.execute('''CREATE TABLE IF NOT EXISTS schedule (
        master_id INTEGER,
        date TEXT,
        time_slots TEXT
    )''')
    # Записи клиентов
    c.execute('''CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY,
        master_id INTEGER,
        client_name TEXT,
        client_phone TEXT,
        date TEXT,
        time TEXT,
        service TEXT
    )''')

    # Добавляем тестового мастера (только если таблица пуста)
    c.execute("SELECT COUNT(*) FROM masters")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO masters (name, photo_url, services) VALUES (?, ?, ?)",
                  ("Анна", "https://i.imgur.com/8KmWnJQ.jpg", '["Маникюр", "Педикюр"]'))
        master_id = c.lastrowid
        c.execute("INSERT INTO schedule (master_id, date, time_slots) VALUES (?, ?, ?)",
                  (master_id, "2026-01-20", '["10:00", "14:00"]'))
        c.execute("INSERT INTO schedule (master_id, date, time_slots) VALUES (?, ?, ?)",
                  (master_id, "2026-01-21", '["11:00", "15:00"]'))

    conn.commit()
    conn.close()

# === Flask API (для будущего использования) ===
app_flask = Flask(__name__)

@app_flask.route('/api/masters')
def api_masters():
    conn = sqlite3.connect('salon.db')
    conn.row_factory = sqlite3.Row
    masters = conn.execute("SELECT * FROM masters").fetchall()
    conn.close()
    return jsonify([{
        "id": m["id"],
        "name": m["name"],
        "photo_url": m["photo_url"],
        "services": json.loads(m["services"])
    } for m in masters])
@app_flask.route('/api/available-slots/<int:master_id>')

def api_available_slots(master_id):
    conn = sqlite3.connect('salon.db')
    c = conn.cursor()

    # Получаем всё расписание мастера
    c.execute("SELECT date, time_slots FROM schedule WHERE master_id = ?", (master_id,))
    schedule_rows = c.fetchall()

    # Получаем занятые слоты
    c.execute("SELECT date, time FROM bookings WHERE master_id = ?", (master_id,))
    booked = set((row[0], row[1]) for row in c.fetchall())

    conn.close()

    # Формируем доступные слоты
    available = {}
    for date, time_slots_json in schedule_rows:
        time_slots = json.loads(time_slots_json)
        free_slots = [t for t in time_slots if (date, t) not in booked]
        if free_slots:
            available[date] = free_slots

    return jsonify(available)

# === Telegram Bot ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(
        "💅 Записаться",
        web_app={"url": "https://bot-regis.vercel.app "}  # ← замени на свою клиентскую ссылку
    )]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Хотите записаться к мастеру?", reply_markup=reply_markup)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(
        "🛠️ Стать мастером",
        web_app={"url": "https://admin-bot-zeta.vercel.app"}  # ← замени на свою админ-ссылку
    )]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Хотите зарегистрироваться как мастер? Заполните форму:", reply_markup=reply_markup)

async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        raw_data = update.message.web_app_data.data
        data = json.loads(raw_data)

        if data.get("is_master_registration"):
            # === РЕГИСТРАЦИЯ МАСТЕРА ===
            conn = sqlite3.connect('salon.db')
            c = conn.cursor()
            c.execute("INSERT INTO masters (name, photo_url, services) VALUES (?, ?, ?)",
                      (data['name'], data['photo_url'], json.dumps(data['services'])))
            master_id = c.lastrowid

            for slot in data.get('schedule', []):
                c.execute("INSERT INTO schedule (master_id, date, time_slots) VALUES (?, ?, ?)",
                          (master_id, slot['date'], json.dumps(slot['times'])))
            conn.commit()
            conn.close()
            await update.message.reply_text("✅ Вы успешно зарегистрированы как мастер!")

        else:
            # === ЗАПИСЬ КЛИЕНТА ===
            master_id = data["master_id"]
            date = data["date"]
            time = data["time"]
            service = data["service"]
            name = data["name"]
            phone = data["phone"]

            conn = sqlite3.connect('salon.db')
            c = conn.cursor()
            c.execute("""INSERT INTO bookings 
                         (master_id, client_name, client_phone, date, time, service)
                         VALUES (?, ?, ?, ?, ?, ?)""",
                      (master_id, name, phone, date, time, service))
            conn.commit()
            conn.close()

            await update.message.reply_text("✅ Вы успешно записаны! Мастер скоро свяжется с вами.")

    except Exception as e:
        print("Ошибка обработки WebApp данных:", e)
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте снова.")


# === Запуск Flask в фоне ===
def run_flask():
    app_flask.run(port=5000, debug=False, use_reloader=False)

# === Основная функция ===
def main():
    init_db()
    
    # Запускаем Flask API в отдельном потоке
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Создаём Telegram-бота
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
    
    # Запускаем бота
    application.run_polling()

if __name__ == "__main__":
    main()