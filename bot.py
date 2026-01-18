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

# Список разрешённых пользователей (только они могут стать мастерами)
ALLOWED_MASTER_IDS = {961734387, 6704791903}  # ← замени на свои ID

# === Инициализация базы данных ===
def init_db():
    import os
    # Удаляем старую базу, чтобы избежать проблем со структурой
    if os.path.exists("salon.db"):
        os.remove("salon.db")
        print("🗑️ Старая база удалена")

    conn = sqlite3.connect('salon.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE masters (
        id INTEGER PRIMARY KEY,
        telegram_user_id INTEGER UNIQUE,
        name TEXT,
        photo_url TEXT,
        services TEXT
    )''')
    c.execute('''CREATE TABLE schedule (
        master_id INTEGER,
        date TEXT,
        time_slots TEXT
    )''')
    c.execute('''CREATE TABLE bookings (
        master_id INTEGER,
        client_name TEXT,
        client_phone TEXT,
        date TEXT,
        time TEXT
    )''')
    conn.commit()
    conn.close()
    print("✅ Новая база создана с правильной структурой")

# === Flask API ===
app_flask = Flask(__name__)

@app_flask.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    return response

@app_flask.route('/api/masters')
def api_masters():
    conn = sqlite3.connect('salon.db', check_same_thread=False)
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
    conn = sqlite3.connect('salon.db', check_same_thread=False)
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

@app_flask.route('/api/my-bookings-by-user/<int:user_id>')
def api_my_bookings_by_user(user_id):
    conn = sqlite3.connect('salon.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    master_row = conn.execute(
        "SELECT id FROM masters WHERE telegram_user_id = ?", (user_id,)
    ).fetchone()
    
    if not master_row:
        conn.close()
        return jsonify([])

    master_id = master_row["id"]
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
        bookings_url = f"https://admin-panel-rho-indol.vercel.app/bookings.html?user_id={user_id}"
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

            conn = sqlite3.connect('salon.db', check_same_thread=False)
            c = conn.cursor()

            # Проверяем, не зарегистрирован ли уже
            c.execute("SELECT id FROM masters WHERE telegram_user_id = ?", (user_id,))
            existing = c.fetchone()
            if existing:
                master_id = existing[0]
                await update.message.reply_text(f"✅ Вы уже зарегистрированы! Ваш ID: {master_id}")
            else:
                c.execute("INSERT INTO masters (telegram_user_id, name, photo_url, services) VALUES (?, ?, ?, ?)",
                          (user_id, data["name"].strip(), data.get("photo_url", "").strip(), json.dumps(data.get("services", []))))
                master_id = c.lastrowid

                for day in data.get("schedule", []):
                    if isinstance(day, dict) and "date" in day and "times" in day:
                        times_clean = [str(t).strip() for t in day["times"] if str(t).strip()]
                        if times_clean:
                            c.execute("INSERT INTO schedule (master_id, date, time_slots) VALUES (?, ?, ?)",
                                      (master_id, day["date"], json.dumps(times_clean)))
                await update.message.reply_text(f"✅ Вы успешно зарегистрированы как мастер! Ваш ID: {master_id}")

            conn.commit()
            conn.close()
        else:
            required = ["master_id", "name", "phone", "date", "time"]
            if not all(k in data for k in required):
                await update.message.reply_text("❌ Неполные данные записи.")
                return

            conn = sqlite3.connect('salon.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT INTO bookings (master_id, client_name, client_phone, date, time) VALUES (?, ?, ?, ?, ?)",
                      (data["master_id"], data["name"], data["phone"], data["date"], data["time"].strip()))
            conn.commit()
            conn.close()
            await update.message.reply_text("✅ Вы успешно записаны!")
    except Exception as e:
        print("💥 Ошибка:", str(e))
        import traceback
        traceback.print_exc()
        await update.message.reply_text("❌ Ошибка при обработке данных.")

# === Функция запуска Flask ===
def run_flask():
    port = int(os.getenv("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

# === Основная функция ===
def main():
    init_db()  # Создаём базу при старте

    # Запускаем Flask в фоне
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Запускаем Telegram бота
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
    app.add_handler(CallbackQueryHandler(register_callback, pattern="^register$"))
    app.run_polling()

if __name__ == "__main__":
    main()