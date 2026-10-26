import threading
import logging
import time
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask
import requests

# إعداد السجلات
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# إعدادات البوت - تأكد من وضع رمز التوكين الخاص بك هنا
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TIMEZONE = pytz.timezone("Asia/Riyadh")

alert_history = {}

# خادم Flask بسيط لإبقاء تطبيق Render نشطاً
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_health_server():
    app.run(host="0.0.0.0", port=10000)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚀 رادار الطلبات المباشر مفعل.\n"
        f"قاعدة البيانات محدثة وتضم {len(HISTORICAL_RIDES)} طلب سابق.\n"
        "أرسل موقعك المباشر (Live Location) لربطه بسجل الطلبات السابقة وإشعارك بالطلبات المحتملة في نفس التوقيت والمنطقة."
    )
    await update.message.reply_text(msg)

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.edited_message
    if not msg or not msg.location:
        return

    chat_id = update.effective_chat.id
    c_lat = msg.location.latitude
    c_lon = msg.location.longitude

    now_dt = datetime.now(TIMEZONE)
    today_str = now_dt.strftime("%Y-%m-%d")

    matching_rides = find_matching_rides(c_lat, c_lon, now_dt)

    for ride, dist, diff_min in matching_rides:
        history_key = (chat_id, ride["id"])
        if alert_history.get(history_key) == today_str:
            continue

        alert_history[history_key] = today_str

        lat = ride["pickup_lat"]
        lon = ride["pickup_lon"]
        maps_url = f"https://www.google.com/maps?q={lat},{lon}"

        location_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🗺 فتح الموقع في خرائط قوقل", url=maps_url)]]
        )

        if "train_arrival" in ride:
            alert_text = (
                f"🚆 *تنبيه وصول قطار لمحطة الدمام (قبل الموعد بـ 30 دقيقة)!*\n\n"
                f"📍 *الموقع:* {ride['pickup_name']}\n"
                f"🗺 *خريطة الموقع:* [اضغط هنا لفتح الخريطة]({maps_url})\n"
                f"📏 *يبعد عنك:* {dist:.1f} كم\n"
                f"⏰ *وقت التنبيه:* {ride['request_time'].strftime('%I:%M %p')} (موعد وصول القطار: {ride['train_arrival']})\n"
                f"🎯 *الوجهة المسجلة:* {ride['dropoff_name']}\n"
                f"💰 *السعر المتوقع:* {ride['price']}\n"
                f"🚖 *النوع:* {ride['service_type']}\n"
                f"ℹ️ *الملاحظة:* {ride['shift_type']}."
            )
        else:
            alert_text = (
                f"🎯 *طلب محتمل في نفس التوقيت!*\n\n"
                f"📍 *الموقع:* {ride['pickup_name']}\n"
                f"🗺 *خريطة الموقع:* [اضغط هنا لفتح الخريطة]({maps_url})\n"
                f"📏 *يبعد عنك:* {dist:.1f} كم\n"
                f"⏰ *وقت الطلب السابق:* {ride['request_time'].strftime('%I:%M %p')}\n"
                f"🎯 *الوجهة المسجلة:* {ride['dropoff_name']}\n"
                f"💰 *السعر السابق:* {ride['price']}\n"
                f"🚖 *النوع:* {ride['service_type']}\n"
                f"ℹ️ *الملاحظة:* تم تسجيل طلب مطابق سابقاً من هذه النقطة في نفس هذا الوقت ({ride['shift_type']})."
            )

        await context.bot.send_message(
            chat_id=chat_id,
            text=alert_text,
            parse_mode="Markdown",
            reply_markup=location_keyboard,
        )
        await context.bot.send_location(
            chat_id=chat_id,
            latitude=lat,
            longitude=lon,
        )

if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))

    app.run_polling()
