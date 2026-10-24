import logging
import asyncio
from datetime import datetime, time, timedelta
from flask import flask
app = Flask(__name__)
@app.route(‘/‘)
def home():
    return “Bot is running!”
import threading
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from geopy.distance import geodesic

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# 🔑 Bot Token
BOT_TOKEN = "8913904158:AAGlWWCjkRcWWAueE1kHDozOrqjk09v2Wy8"

# 📍 Key Coordinates (Home/Work Nodes)
LOCATIONS = {
    "القطيف (المنزل - نقاط الانطلاق)": {"lat": 26.5492, "lon": 50.0076},
    "الدمام (وجهة العمل - نقاط العودة)": {"lat": 26.3920, "lon": 50.0630},
    "الخبر (وجهة العمل - نقاط العودة)": {"lat": 26.3142, "lon": 50.1986},
}

# 🔄 Recurring Daily Schedule (Sunday - Thursday)
SCHEDULE = {
    "الأحد": [
        {"time": "05:30", "from": "القطيف (المنزل - نقاط الانطلاق)", "to": "الدمام/الخبر (أماكن العمل)", "type": "الذهاب للعمل"},
        {"time": "19:00", "from": "الدمام/الخبر (أماكن العمل)", "to": "القطيف (المنزل)", "type": "العودة للمنزل"},
    ],
    "الاثنين": [
        {"time": "05:30", "from": "القطيف (المنزل - نقاط الانطلاق)", "to": "الدمام/الخبر (أماكن العمل)", "type": "الذهاب للعمل"},
        {"time": "19:00", "from": "الدمام/الخبر (أماكن العمل)", "to": "القطيف (المنزل)", "type": "العودة للمنزل"},
    ],
    "الثلاثاء": [
        {"time": "05:30", "from": "القطيف (المنزل - نقاط الانطلاق)", "to": "الدمام/الخبر (أماكن العمل)", "type": "الذهاب للعمل"},
        {"time": "19:00", "from": "الدمام/الخبر (أماكن العمل)", "to": "القطيف (المنزل)", "type": "العودة للمنزل"},
    ],
    "الأربعاء": [
        {"time": "05:30", "from": "القطيف (المنزل - نقاط الانطلاق)", "to": "الدمام/الخبر (أماكن العمل)", "type": "الذهاب للعمل"},
        {"time": "19:00", "from": "الدمام/الخبر (أماكن العمل)", "to": "القطيف (المنزل)", "type": "العودة للمنزل"},
    ],
    "الخميس": [
        {"time": "05:30", "from": "القطيف (المنزل - نقاط الانطلاق)", "to": "الدمام/الخبر (أماكن العمل)", "type": "الذهاب للعمل"},
        {"time": "19:00", "from": "الدمام/الخبر (أماكن العمل)", "to": "القطيف (المنزل)", "type": "العودة للمنزل"},
    ],
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Activates the bot."""
    await update.message.reply_text(
        "مرحباً كابتن! البوت جاهز لمراقبة موقعك والتنبؤ برحلاتك المتكررة. "
        "يرجى إرسال موقعك اللحظي لتفعيل المتابعة."
    )

async def check_schedule(current_loc: tuple, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Checks recurring schedules and predicts upcoming requests."""
    now = datetime.now()
    day_name = now.strftime("%A")
    days_map = {
        "Sunday": "الأحد", "Monday": "الاثنين", "Tuesday": "الثلاثاء",
        "Wednesday": "الأربعاء", "Thursday": "الخميس"
    }
    
    today_arabic = days_map.get(day_name)
    if not today_arabic or today_arabic not in SCHEDULE:
        return

    current_time = now.time()
    
    for event in SCHEDULE[today_arabic]:
        event_time = datetime.strptime(event["time"], "%H:%M").time()
        event_datetime = datetime.combine(datetime.today(), event_time)
        
        # Check if the event is within the next 20 minutes
        time_difference = (event_datetime - now).total_seconds() / 60
        
        if 0 <= time_difference <= 20:
            origin_coords = (LOCATIONS[event["from"]]["lat"], LOCATIONS[event["from"]]["lon"])
            distance = geodesic(current_loc, origin_coords).kilometers
            
            # Predict only if within 5km of origin
            if distance <= 5.0:
                message = (
                    f"🔔 *تنبؤ بطلب متكرر!* ({event['type']})\n\n"
                    f"🕒 الموعد المتوقع: {event['time']}\n"
                    f"📍 منطقة الانطلاق: {event['from']}\n"
                    f"🏢 الوجهة: {event['to']}\n"
                    f"🚗 تبعد {distance:.1f} كم عن موقعك الحالي.\n\n"
                    "استعد لاستقبال طلبات 'وصول' الآن."
                )
                await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles real-time location tracking safely."""
    if update.message and update.message.location:
        chat_id = update.effective_chat.id
        current_loc = (update.message.location.latitude, update.message.location.longitude)
        
        await check_schedule(current_loc, chat_id, context)

if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    
    print("🤖 Bot is running and tracking locations...")
    application.run_polling()
threading.Thread(target=lambda: app.run(host=‘0.0.0.0’, port=10000)).start
