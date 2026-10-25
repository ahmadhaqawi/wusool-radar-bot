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
    # --- Morning Peak & Shift Work (04:30 - 08:30) ---
    {
        "id": "ride_dawn_01",
        "request_time": time(4, 30),
        "pickup_lat": 26.4150,
        "pickup_lon": 50.0520,
        "pickup_name": "غرب الدمام - شارع عمر بن الخطاب / أبو أوس الأسلمي",
        "dropoff_name": "مصفاة رأس تنورة / شركات الجبيل",
        "price": "45 - 70 ر.س",
        "service_type": "سفر / شركات",
        "shift_type": "دوام مبكر ورديات"
    },
    {
        "id": "ride_dawn_02",
        "request_time": time(4, 45),
        "pickup_lat": 26.2910,
        "pickup_lon": 50.2150,
        "pickup_name": "الخبر - طريق الملك عبدالله / الكورنيش",
        "dropoff_name": "مطار الملك فهد الدولي (DMM)",
        "price": "65 - 110 ر.س",
        "service_type": "UberXL / مطار",
        "shift_type": "رحلات طيران مبكرة"
    },
    {
        "id": "ride_morning_03",
        "request_time": time(6, 40),
        "pickup_lat": 26.5580,
        "pickup_lon": 50.0120,
        "pickup_name": "القطيف - حي الفلاح / طريق أبو در",
        "dropoff_name": "الدمام - شارع خلف بن تميم / مجمعات الأعمال",
        "price": "40 - 65 ر.س",
        "service_type": "وصول",
        "shift_type": "دوام حكومي ومكتبي"
    },
    {
        "id": "ride_morning_04",
        "request_time": time(7, 0),
        "pickup_lat": 26.5170,
        "pickup_lon": 50.0340,
        "pickup_name": "القطيف - سيهات / شارع علي الأنصاري",
        "dropoff_name": "الدمام - طريق 1 والواجهة البحرية",
        "price": "55 - 65 ر.س",
        "service_type": "وصول موظفين",
        "shift_type": "ذروة دوام صباحي"
    },
    {
        "id": "ride_morning_05",
        "request_time": time(7, 25),
        "pickup_lat": 26.3780,
        "pickup_lon": 50.1320,
        "pickup_name": "الدمام - طريق الأمير محمد بن فهد / الظهران",
        "dropoff_name": "الظهران - بوابة أرامكو والمدينة الأكاديمية",
        "price": "35 - 48 ر.س",
        "service_type": "أوبر X",
        "shift_type": "دوام شركات الظهران"
    },
    {
        "id": "ride_morning_06",
        "request_time": time(7, 45),
        "pickup_lat": 26.4350,
        "pickup_lon": 50.1040,
        "pickup_name": "الدمام - حي الشاطئ الشرقي / شارع الأشرعة",
        "dropoff_name": "الخبر - الحزام الذهبي / طريق الملك فيصل",
        "price": "42 - 55 ر.س",
        "service_type": "وصول / أوبر",
        "shift_type": "انتقال موظفين بين المدن"
    },

    # --- Midday School & Shift Release (11:45 - 14:45) ---
    {
        "id": "ride_midday_07",
        "request_time": time(12, 30),
        "pickup_lat": 26.4020,
        "pickup_lon": 50.0780,
        "pickup_name": "الدمام - الفيصلية / شارع سهل بن صخر",
        "dropoff_name": "الخبر - شارع 25هـ / حي العزيزية",
        "price": "38 - 48 ر.س",
        "service_type": "وصول",
        "shift_type": "خروج مدارس ومعاهد"
    },
    {
        "id": "ride_midday_08",
        "request_time": time(13, 15),
        "pickup_lat": 26.4420,
        "pickup_lon": 50.0890,
        "pickup_name": "الدمام - شارع 13 الصفا",
        "dropoff_name": "القطيف - حي داود القزاز وصفوى",
        "price": "50 - 62 r.s",
        "service_type": "وصول",
        "shift_type": "خروج موظفي وردية النهار"
    },
    {
        "id": "ride_midday_09",
        "request_time": time(13, 40),
        "pickup_lat": 26.2840,
        "pickup_lon": 50.1980,
        "pickup_name": "الخبر - العقربية / شارع 10 تقاطع مكة",
        "dropoff_name": "الدمام - حي المزروعية وحي الطبيشي",
        "price": "40 - 52 ر.س",
        "service_type": "أوبر X",
        "shift_type": "عودة الموظفين لمنازلهم"
    },
    {
        "id": "ride_midday_10",
        "request_time": time(14, 10),
        "pickup_lat": 26.3120,
        "pickup_lon": 50.1450,
        "pickup_name": "الظهران - طريق الملك فهد محيط أرامكو",
        "dropoff_name": "بقيق / الأحساء طريق سريع",
        "price": "80 - 130 ر.س",
        "service_type": "سفر / بين مدن",
        "shift_type": "انصراف مهندسين وشركات مقاولات"
    },

    # --- Afternoon Commercial & Shopping Peak (15:30 - 18:30) ---
    {
        "id": "ride_afternoon_11",
        "request_time": time(16, 20),
        "pickup_lat": 26.5310,
        "pickup_lon": 50.0240,
        "pickup_name": "القطيف - عنك / شارع ابن النباشي",
        "dropoff_name": "الدمام - مجمع النخيل مول / شارع محمد القرطبي",
        "price": "35 - 45 ر.س",
        "service_type": "أوبر X",
        "shift_type": "مشاوير تسوق مسائية"
    },
    {
        "id": "ride_afternoon_12",
        "request_time": time(16, 45),
        "pickup_lat": 26.4110,
        "pickup_lon": 50.1190,
        "pickup_name": "الدمام - عبدالله فؤاد / شارع عبدالرحمن البزاز",
        "dropoff_name": "الخبر - كورنيش الخبر الشمالي / شارع الأمير تركي",
        "price": "48 - 60 ر.س",
        "service_type": "وصول / أوبر",
        "shift_type": "مشاوير ترفيه ومطاعم"
    },
    {
        "id": "ride_afternoon_13",
        "request_time": time(17, 15),
        "pickup_lat": 26.3312,
        "pickup_lon": 50.1925,
        "pickup_name": "الظهران / الخبر - مجمع الظهران بوابة 4",
        "dropoff_name": "الدمام - حي المنار وحي طيبة",
        "price": "38 - 50 ر.с",
        "service_type": "وصول",
        "shift_type": "تسوق وموظفي مبيعات"
    },

    # --- Evening & Night Shifts (18:30 - 23:30) ---
    {
        "id": "ride_evening_14",
        "request_time": time(19, 10),
        "pickup_lat": 26.3050,
        "pickup_lon": 50.2030,
        "pickup_name": "الخبر - شارع الأمير فيصل بن فهد (البيبسي)",
        "dropoff_name": "الدمام - الشاطئ الغربي وطريق الخليج",
        "price": "45 - 55 ر.س",
        "service_type": "أوبر X",
        "shift_type": "مطاعم وكافيهات"
    },
    {
        "id": "ride_night_15",
        "request_time": time(22, 15),
        "pickup_lat": 26.4520,
        "pickup_lon": 50.1280,
        "pickup_name": "الدمام - حي الشاطئ / مارينا مول",
        "dropoff_name": "القطيف - حي المجيدية وتاروت",
        "price": "45 - 60 ر.س",
        "service_type": "وصول / أوبر",
        "shift_type": "إغلاق المولات والعودة للمنازل"
    },
    {
        "id": "ride_night_16",
        "request_time": time(23, 30),
        "pickup_lat": 26.4710,
        "pickup_lon": 49.7980,
        "pickup_name": "مطار الملك فهد الدولي (صالة القدوم)",
        "dropoff_name": "الخبر - الحزام الذهبي / الظهران",
        "price": "90 - 130 ر.س",
        "service_type": "UberXL / مطار",
        "shift_type": "رحلات قدوم ليلية"
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
        "🚀 رادار الطلبات المباشר مفعل.\n"
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
