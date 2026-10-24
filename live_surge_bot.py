import logging
import asyncio
from datetime import datetime, time, timedelta
from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    return 'Bot is running!'

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

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Bot Token
BOT_TOKEN = "8913904158:AAGlWWCjkRcWWAueE1kHDozOrqjk09v2Wy8"

# Key Coordinates (Home/Work Nodes)
LOCATIONS = {
    "القطيف (المنزل - نقطة الانطلاق)": {"lat": 26.5492, "lon": 50.0178},
    "الدمام (وجهة العمل - نقاط العودة)": {"lat": 26.3920, "lon": 50.1111},
}

# Recurring Daily Schedule (Sunday - Thursday)
SCHEDULE = {
    "الاثنين": [
        {"time": "05:30", "from": "القطيف (المنزل - نقطة الانطلاق)", "to": "الدمام (وجهة العمل - نقاط العودة)"},
        {"time": "19:00", "from": "الدمام (وجهة العمل - نقاط العودة)", "to": "القطيف (المنزل - نقطة الانطلاق)"},
    ],
    "الثلاثاء": [
        {"time": "05:30", "from": "القطيف (المنزل - نقطة الانطلاق)", "to": "الدمام (وجهة العمل - نقاط العودة)"},
        {"time": "19:00", "from": "الدمام (وجهة العمل - نقاط العودة)", "to": "القطيف (المنزل - نقطة الانطلاق)"},
    ],
    "الاربعاء": [
        {"time": "05:30", "from": "القطيف (المنزل - نقطة الانطلاق)", "to": "الدمام (وجهة العمل - نقاط العودة)"},
        {"time": "19:00", "from": "الدمام (وجهة العمل - نقاط العودة)", "to": "القطيف (المنزل - نقطة الانطلاق)"},
    ],
    "الخميس": [
        {"time": "05:30", "from": "القطيف (المنزل - نقطة الانطلاق)", "to": "الدمام (وجهة العمل - نقاط العودة)"},
        {"time": "19:00", "from": "الدمام (وجهة العمل - نقاط العودة)", "to": "القطيف (المنزل - نقطة الانطلاق)"},
    ],
    "الاحد": [
        {"time": "05:30", "from": "القطيف (المنزل - نقطة الانطلاق)", "to": "الدمام (وجهة العمل - نقاط العودة)", "type": "الذهاب للعمل"},
        {"time": "15:30", "from": "الدمام (وجهة العمل - نقاط العودة)", "to": "سيهات (لسن) ثم القطيف (المنزل)", "type": "العودة للمنزل"},
        {"time": "19:00", "from": "القطيف (المنزل)", "to": "الدمام", "type": "الذهاب للعمل"},
    ]
}

async def check_schedule(current_loc, chat_id, context):
    """Checks recurring schedules and predicts upcoming rides."""
    now = datetime.now()
    day_name = now.strftime('%A')
    days_map = {
        'Sunday': 'الاحد', 'Monday': 'الاثنين', 'Tuesday': 'الثلاثاء',
        'Wednesday': 'الاربعاء', 'Thursday': 'الخميس', 'Friday': 'الجمعة',
        'Saturday': 'السبت'
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
            origin_coords = LOCATIONS[event["from"]]
            distance = geodesic(current_loc, origin_coords).kilometers

            # Trigger if within 3km of origin
            if distance <= 3:
                msg = (
                    f"🚨 تنبيه: تحرك مرتقب في غضون {time_difference:.1f} دقيقة.\n"
                    f"📍 الموقع الحالي: {distance:.1f} كم عن موقعك.\n"
                    "🚗 استعد لاستقبال طلبات 'وصول' الآن."
                )
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles real-time location tracking safely."""
    if update.message and update.message.location:
        chat_id = update.effective_chat.id
        current_loc = (update.message.location.latitude, update.message.location.longitude)

        await check_schedule(current_loc, chat_id, context)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Activates the bot."""
    await update.message.reply_text(
        "مرحباً كابيتان! البوت جاهز لمراقبة موقعك والتنبؤ برحلاتك المتكررة. يرجى إرسال موقعك اللحظي لتفعيل المتابعة."
    )

if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))

    print("🤖 Bot is running and tracking locations...")

    # Run Flask in a separate thread
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()

    application.run_polling()
