import os
import math
import asyncio
import threading
from datetime import datetime, time, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import pytz
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from geopy.distance import geodesic

# ==============================================================================
# Configuration & State
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN", "8913904158:AAGlWWCjkRcWWAueE1kHDozOrqjk09v2Wy8"
)
TIMEZONE = pytz.timezone("Asia/Riyadh")
ALERT_RADIUS_KM = 5.0
TIME_WINDOW_MINUTES = 30  # Lookahead / lookbehind window around exact request time

alert_history = {}  # { (chat_id, ride_id): last_alerted_date }

# Dummy health check server for Render deployment
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is operational.")

def run_health_server():
    server = HTTPServer(("0.0.0.0", 10000), HealthHandler)
    server.serve_forever()

# ==============================================================================
# Historical Rides Database (Extracted Directly from Image Data)
# ==============================================================================
HISTORICAL_RIDES = [
    {
        "id": "ride_001",
        "request_time": time(4, 42),
        "pickup_lat": 26.3780,
        "pickup_lon": 50.1320,
        "pickup_name": "الدمام - طريق الأمير محمد بن فهد",
        "dropoff_name": "حي الغرائب / الواحة",
        "price": "40 - 48 ر.س",
        "service_type": "وصول / أوبر",
        "details": "طلب مسجل سابقاً الساعة 04:42 ص"
    },
    {
        "id": "ride_002",
        "request_time": time(4, 45),
        "pickup_lat": 26.2910,
        "pickup_lon": 50.2150,
        "pickup_name": "الخبر - طريق الملك عبدالله / الكورنيش",
        "dropoff_name": "مطار الملك فهد الدولي (DMM)",
        "price": "60 - 110 ر.س",
        "service_type": "UberXL / مطار",
        "details": "طلب فندقي / سفر مسجل الساعة 04:45 ص"
    },
    {
        "id": "ride_003",
        "request_time": time(6, 45),
        "pickup_lat": 26.5580,
        "pickup_lon": 50.0120,
        "pickup_name": "القطيف - شارع الفلاح / طريق أبو در",
        "dropoff_name": "الدمام - شارع خلف بن تميم",
        "price": "45 - 65 ر.س",
        "service_type": "وصول موظفين",
        "details": "طلب متكرر صباحي الساعة 06:45 ص"
    },
    {
        "id": "ride_004",
        "request_time": time(7, 10),
        "pickup_lat": 26.5170,
        "pickup_lon": 50.0340,
        "pickup_name": "القطيف - شارع علي الأنصاري",
        "dropoff_name": "الدمام - طريق 1",
        "price": "55 - 65 ر.س",
        "service_type": "وصول",
        "details": "طلب دوام مسجل الساعة 07:10 ص"
    },
    {
        "id": "ride_005",
        "request_time": time(12, 35),
        "pickup_lat": 26.4020,
        "pickup_lon": 50.0780,
        "pickup_name": "الدمام - شارع سهل بن صخر",
        "dropoff_name": "الخبر - شارع 25هـ",
        "price": "38 - 45 ر.س",
        "service_type": "أوبر X",
        "details": "طلب ظهيرة مسجل الساعة 12:35 م"
    },
    {
        "id": "ride_006",
        "request_time": time(13, 20),
        "pickup_lat": 26.4420,
        "pickup_lon": 50.0890,
        "pickup_name": "الدمام - شارع 13 الصفا",
        "dropoff_name": "القطيف - داود القزاز",
        "price": "50 - 60 ر.س",
        "service_type": "وصول",
        "details": "طلب عودة موظفين الساعة 01:20 م"
    },
    {
        "id": "ride_007",
        "request_time": time(16, 25),
        "pickup_lat": 26.5310,
        "pickup_lon": 50.0240,
        "pickup_name": "القطيف - شارع ابن النباشي",
        "dropoff_name": "الدمام - شارع محمد القرطبي",
        "price": "35 - 45 ر.س",
        "service_type": "أوبر X",
        "details": "طلب مشاوير مسائية الساعة 04:25 م"
    },
    {
        "id": "ride_008",
        "request_time": time(16, 50),
        "pickup_lat": 26.4110,
        "pickup_lon": 50.1190,
        "pickup_name": "الدمام - شارع عبدالرحمن البزاز",
        "dropoff_name": "الخبر - طريق الأمير تركي",
        "price": "50 - 60 ر.س",
        "service_type": "وصول / أوبر",
        "details": "طلب تسوق مسجل الساعة 04:50 م"
    },
    {
        "id": "ride_009",
        "request_time": time(18, 15),
        "pickup_lat": 26.3120,
        "pickup_lon": 50.1450,
        "pickup_name": "الظهران - شارع 733491",
        "dropoff_name": "القطيف - خالد بن الوليد",
        "price": "40 - 50 r.s",
        "service_type": "أوبر X",
        "details": "طلب مسائي مسجل الساعة 06:15 م"
    }
]

# ==============================================================================
# Matching Engine
# ==============================================================================
def find_matching_rides(captain_lat, captain_lon, now_dt):
    matches = []
    current_minutes = now_dt.hour * 60 + now_dt.minute

    for ride in HISTORICAL_RIDES:
        ride_minutes = ride["request_time"].hour * 60 + ride["request_time"].minute
        diff_minutes = abs(current_minutes - ride_minutes)
        diff_minutes = min(diff_minutes, 1440 - diff_minutes)

        if diff_minutes <= TIME_WINDOW_MINUTES:
            dist = geodesic((captain_lat, captain_lon), (ride["pickup_lat"], ride["pickup_lon"])).kilometers
            if dist <= ALERT_RADIUS_KM:
                matches.append((ride, dist, diff_minutes))

    # Sort matches by closest distance then time closeness
    matches.sort(key=lambda x: (x[1], x[2]))
    return matches

# ==============================================================================
# Telegram Handlers
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚀 رادار الطلبات المباشر مفعل.\n"
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

        alert_text = (
            f"🎯 *طلب محتمل في نفس التوقيت!*\n\n"
            f"📍 *الموقع:* {ride['pickup_name']}\n"
            f"📏 *يبعد عنك:* {dist:.1f} كم\n"
            f"⏰ *وقت الطلب السابق:* {ride['request_time'].strftime('%I:%M %p')}\n"
            f"🎯 *الوجهة المسجلة:* {ride['dropoff_name']}\n"
            f"💰 *السعر السابق:* {ride['price']}\n"
            f"🚖 *النوع:* {ride['service_type']}\n"
            f"ℹ️ *الملاحظة:* تم تسجيل طلب مطابق سابقاً من هذه النقطة في نفس هذا الوقت."
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=alert_text,
            parse_mode="Markdown"
        )

# ==============================================================================
# Main Entry Point
# ==============================================================================
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))

    app.run_polling()
