# bot.py
import os
import sqlite3
import json
import threading
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# === Настройки ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в переменных окружения!")

# Список разрешённых ID (замените на свои)
ALLOWED_MASTER_IDS = {961734387, 6704791903}  # ← ЗАМЕНИ НА СВОЙ TELEGRAM ID!

# === Инициализация базы данных ===
def init_db():
    conn = sqlite3.connect('salon.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS masters (
        id INTEGER PRIMARY KEY,
        name TEXT,
        photo_url TEXT,
        services TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS schedule (
        master_id INTEGER,
        date TEXT,
        time_slots TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS bookings (
        master_id INTEGER,
        client_name TEXT,
        client_phone TEXT,
        date TEXT,
        time TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# === Flask API ===
app_flask = Flask(__name__)

@app_flask.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    return response

@app_flask.route('/api/masters')
def api_masters():
    conn = sqlite3.connect('salon.db')
    conn.row_factory = sqlite3.Row
    masters = conn.execute("SELECT * FROM masters").fetchall()
    conn.close()
    return jsonify([{
        "id": m["id"],
        "name": m["name"],
        "photo_url": m["photo_url"].strip(),
        "services": json.loads(m["services"])
    } for m in masters])

@app_flask.route('/api/available-slots/<int:master_id>')
def api_available_slots(master_id):
    conn = sqlite3.connect('salon.db')
    c = conn.cursor()
    c.execute("SELECT date, time_slots FROM schedule WHERE master_id = ?", (master_id,))
    schedule_rows = c.fetchall()
    c.execute("SELECT date, time FROM bookings WHERE master_id = ?", (master_id,))
    booked = set((row[0], row[1].strip()) for row in c.fetchall())
    conn.close()

    result = {}
    for date, time_slots_json in schedule_rows:
        time_slots = json.loads(time_slots_json)
        result[date] = []
        for t in time_slots:
            t_clean = t.strip()
            result[date].append({
                "time": t_clean,
                "available": (date, t_clean) not in booked
            })
    return jsonify(result)

# 👇 НОВЫЙ МАРШРУТ: МОИ ЗАПИСИ 👇
@app_flask.route('/api/my-bookings/<int:master_id>')
def api_my_bookings(master_id):
    conn = sqlite3.connect('salon.db')
    conn.row_factory = sqlite3.Row
    bookings = conn.execute("""
        SELECT client_name, client_phone, date, time 
        FROM bookings 
        WHERE master_id = ? 
        ORDER BY date, time
    """, (master_id,)).fetchall()
    conn.close()
    
    return jsonify([{
        "client_name": b["client_name"],
        "client_phone": b["client_phone"],
        "date": b["date"],
        "time": b["time"]
    } for b in bookings])

@app_flask.route('/')
def home():
    return {"status": "Salon Bot API is running"}

# === Telegram бот ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("Записаться", web_app={"url": "https://bot-regis.vercel.app"})]
    ]
    
    if user_id in ALLOWED_MASTER_IDS:
        keyboard.append([InlineKeyboardButton("Стать мастером", callback_data="register")])
        # 🔑 Укажи свой ID мастера (посмотри в базе или через /api/masters)
        MASTER_ID = 6704791903, 961734387  # ← ЗАМЕНИ НА СВОЙ ID!
        bookings_url = f"https://твоя-админка.vercel.app/bookings.html?master_id={MASTER_ID}"
        keyboard.append([InlineKeyboardButton("Мои записи", web_app={"url": bookings_url})])
    
    await update.message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def register_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "Нажмите кнопку ниже, чтобы зарегистрироваться как мастер:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📝 Зарегистрироваться",
                web_app={"url": "https://admin-bot-zeta.vercel.app"}
            )
        ]])
    )

async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        raw_data = update.message.web_app_data.data
        data = json.loads(raw_data)

        if data.get("is_master_registration"):
            if user_id not in ALLOWED_MASTER_IDS:
                await update.message.reply_text("❌ У вас нет прав на регистрацию мастера.")
                return
            
            conn = sqlite3.connect('salon.db')
            c = conn.cursor()
            c.execute("INSERT INTO masters (name, photo_url, services) VALUES (?, ?, ?)",
                      (data["name"], data["photo_url"].strip(), json.dumps(data["services"])))
            master_id = c.lastrowid
            for day in data["schedule"]:
                times_clean = [t.strip() for t in day["times"]]
                c.execute("INSERT INTO schedule (master_id, date, time_slots) VALUES (?, ?, ?)",
                          (master_id, day["date"], json.dumps(times_clean)))
            conn.commit()
            conn.close()
            await update.message.reply_text(f"✅ Вы успешно зарегистрированы как мастер! Ваш ID: {master_id}")
        else:
            conn = sqlite3.connect('salon.db')
            c = conn.cursor()
            c.execute("INSERT INTO bookings (master_id, client_name, client_phone, date, time) VALUES (?, ?, ?, ?, ?)",
                      (data["master_id"], data["name"], data["phone"], data["date"], data["time"].strip()))
            conn.commit()
            conn.close()
            await update.message.reply_text("✅ Вы успешно записаны!")
    except Exception as e:
        print("Ошибка:", e)
        await update.message.reply_text("❌ Ошибка при обработке данных. Попробуйте снова.")

# === Запуск ===
def run_flask():
    port = int(os.getenv("PORT", 5000))
    app_flask.run(host='0.0.0.0', port=port)

def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
    app.add_handler(CallbackQueryHandler(register_callback, pattern="^register$"))
    app.run_polling()

if __name__ == "__main__":
    main()