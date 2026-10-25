from datetime import datetime, time
import logging
import threading
import time as time_module
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask
from geopy.distance import geodesic

app = Flask(__name__)

@app.route('/')
def home():
    return 'Bot is running!'

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

BOT_TOKEN = "8913904158:AAGlWWCjkRcWWAueE1kHDozOrqjk09v2Wy8"

HOTSPOTS = [
    {
        "id": "morning_qatif_falah",
        "name": "القطيف - الفلاح / طريق أبو در",
        "lat": 26.5580,
        "lon": 50.0120,
        "peak_start": time(7, 0),
        "peak_end": time(8, 30),
        "notice_start": time(6, 30),
        "target_routes": "الدمام (شارع خلف بن تميم، طريق 1) ومناطق الشركات",
        "expected_price": "40 – 65 ر.س",
        "tip": "تمركز بالقرب من مخارج القطيف السريعة المتجهة جنوباً نحو الدمام والظهران."
    },
    {
        "id": "morning_qatif_ansari",
        "name": "القطيف - شارع علي الأنصاري / سيهات",
        "lat": 26.5170,
        "lon": 50.0340,
        "peak_start": time(7, 0),
        "peak_end": time(8, 0),
        "notice_start": time(6, 40),
        "target_routes": "طريق 1 والواجهة البحرية بالدمام",
        "expected_price": "55 – 65 ر.س",
        "tip": "طلبات وصول وموظفين باتجاه مجمعات الدوائر بالدمام."
    },
    {
        "id": "morning_dammam_west",
        "name": "غرب وشمال الدمام (شارع عمر بن الخطاب / الضاحية)",
        "lat": 26.4150,
        "lon": 50.0520,
        "peak_start": time(6, 30),
        "peak_end": time(8, 30),
        "notice_start": time(6, 0),
        "target_routes": "رأس تنورة، مصفاة أرامكو، والجبيل",
        "expected_price": "45 – 75 ر.س",
        "tip": "تمركز عند مخارج طريق الجبيل السريع لاقتناص مشاوير المسافات الطويلة."
    },
    {
        "id": "midday_dammam_sahl",
        "name": "الدمام - شارع سهل بن صخر / الفيصلية",
        "lat": 26.4020,
        "lon": 50.0780,
        "peak_start": time(12, 15),
        "peak_end": time(13, 30),
        "notice_start": time(11, 45),
        "target_routes": "الخبر (شارع 25هـ، العزيزية، الحزام الذهبي)",
        "expected_price": "38 – 45 ر.س",
        "tip": "طلبات تنقل عائلات وموظفات بين غرب الدمام والخبر الجنوبية."
    },
    {
        "id": "midday_dammam_safwa_route",
        "name": "الدمام - شارع 13 الصفا",
        "lat": 26.4420,
        "lon": 50.0890,
        "peak_start": time(13, 15),
        "peak_end": time(14, 15),
        "notice_start": time(12, 45),
        "target_routes": "القطيف (داود القزاز) وصفوى ورأس تنورة",
        "expected_price": "50 – 60 ر.س",
        "tip": "خط رجعة للموظفين والطلاب العائدين شمالاً."
    },
    {
        "id": "midday_dammam_mohd_fahd",
        "name": "الدمام - طريق الأمير محمد بن فهد / الظهران",
        "lat": 26.3780,
        "lon": 50.1320,
        "peak_start": time(13, 20),
        "peak_end": time(14, 30),
        "notice_start": time(13, 0),
        "target_routes": "حي الغرائب والواحة ومناطق وسط الدمام",
        "expected_price": "40 – 48 ر.س",
        "tip": "تمركز بين تقاطعات طريق الملك فهد وطريق الأمير محمد بن فهد."
    },
    {
        "id": "midday_khobar_corniche_kingabdullah",
        "name": "الخبر - طريق الملك عبدالله / الكورنيش",
        "lat": 26.2910,
        "lon": 50.2150,
        "peak_start": time(13, 30),
        "peak_end": time(14, 45),
        "notice_start": time(13, 0),
        "target_routes": "شمال الدمام ومطار الملك فهد الدولي (DMM)",
        "expected_price": "60 – 110 ر.س (طلبات UberXL ومطار)",
        "tip": "تجمع رحلات المسافرين ورجال الأعمال في الفنادق ومقرات الشركات."
    },
    {
        "id": "afternoon_qatif_tarout",
        "name": "القطيف - شارع ابن النباشي / عنك / سيهات",
        "lat": 26.5310,
        "lon": 50.0240,
        "peak_start": time(16, 0),
        "peak_end": time(17, 30),
        "notice_start": time(15, 30),
        "target_routes": "الدمام (شارع محمد القرطبي / الشاطئ)",
        "expected_price": "35 – 45 ر.س",
        "tip": "طلبات التسوق والمشاوير المسائية المتجهة للمجمعات التجارية بالدمام."
    },
    {
        "id": "afternoon_dammam_bazzaz",
        "name": "الدمام - شارع عبدالرحمن البزاز / عبدالله فؤاد",
        "lat": 26.4110,
        "lon": 50.1190,
        "peak_start": time(16, 30),
        "peak_end": time(18, 0),
        "notice_start": time(16, 0),
        "target_routes": "الخبر (شارع الأمير تركي بن عبدالعزيز / الكورنيش)",
        "expected_price": "50 – 60 ر.س",
        "tip": "حركة تسوق وزيارات عائلية باتجاه واجهة الخبر البحرية."
    },
    {
        "id": "evening_dhahran_khobar",
        "name": "الظهران - شارع 733491 / محيط أرامكو والجامعة",
        "lat": 26.3120,
        "lon": 50.1450,
        "peak_start": time(18, 0),
        "peak_end": time(19, 30),
        "notice_start": time(17, 30),
        "target_routes": "القطيف (خالد بن الوليد) وغرب الدمام",
        "expected_price": "40 – 50 ر.س",
        "tip": "خروج ورش عمل وموظفي شركات ومقاولات الظهران."
    }
]

def calculate_distance(lat1, lon1, lat2, lon2):
    return geodesic((lat1, lon1), (lat2, lon2)).kilometers

def check_active_hotspots(current_time, captain_lat, captain_lon, radius_km=8.0):
    matched = []
    cur_minutes = current_time.hour * 60 + current_time.minute

    for spot in HOTSPOTS:
        n_min = spot["notice_start"].hour * 60 + spot["notice_start"].minute
        p_end = spot["peak_end"].hour * 60 + spot["peak_end"].minute

        if n_min <= cur_minutes <= p_end:
            dist = calculate_distance(captain_lat, captain_lon, spot["lat"], spot["lon"])
            if dist <= radius_km:
                matched.append((spot, dist))
    return matched

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.location:
        chat_id = update.effective_chat.id
        captain_loc = (update.message.location.latitude, update.message.location.longitude)
        now = datetime.now().time()

        active_spots = check_active_hotspots(now, captain_loc[0], captain_loc[1])

        if active_spots:
            for spot, dist in active_spots:
                msg = (
                    f"🚨 تنبيه: تحرك مرتقب في منطقة {spot['name']}.\n"
                    f"📍 المسافة الحالية: {dist:.1f} كم.\n"
                    f"🎯 الوجهات المتوقعة: {spot['target_routes']}\n"
                    f"💰 السعر المتوقع: {spot['expected_price']}\n"
                    f"💡 نصيحة: {spot['tip']}"
                )
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً كباتن! البوت جاهز لمراقبة موقعك والتنبؤ بطلبات 'وصول' و'أوبر' بناءً على التمركزات النشطة."
    )

if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))

    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    application.run_polling()
