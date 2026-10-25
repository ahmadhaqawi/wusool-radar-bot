import os
import csv
import threading
from datetime import datetime, time
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
TIME_WINDOW_MINUTES = 30

alert_history = {}

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is operational.")

def run_health_server():
    server = HTTPServer(("0.0.0.0", 10000), HealthHandler)
    server.serve_forever()

def _r(id_, h, m, lat, lon, pickup, dropoff, price, service_type="Wusool", shift_type="رحلة قياسية"):
    return {
        "id": id_,
        "request_time": time(h, m),
        "pickup_lat": lat,
        "pickup_lon": lon,
        "pickup_name": pickup,
        "dropoff_name": dropoff,
        "price": price,
        "service_type": service_type,
        "shift_type": shift_type,
    }

# ==============================================================================
# Historical Rides Database (Base + Dammam Train Station + Extracted AI Hotspots)
# ==============================================================================
HISTORICAL_RIDES = [
    # --- الفترة الصباحية والورديات (04:30 - 08:30) ---
    _r("ride_dawn_01", 4, 30, 26.4150, 50.0520, "غرب الدمام - شارع عمر بن الخطاب / أبو أوس الأسلمي", "مصفاة رأس تنورة / شركات الجبيل", "45 - 70 ر.س", "سفر / شركات", "دوام مبكر ورديات"),
    _r("ride_dawn_02", 4, 45, 26.2910, 50.2150, "الخبر - طريق الملك عبدالله / الكورنيش", "مطار الملك فهد الدولي (DMM)", "65 - 110 ر.س", "UberXL / مطار", "رحلات طيران مبكرة"),
    _r("ride_morning_03", 6, 40, 26.5580, 50.0120, "القطيف - حي الفلاح / طريق أبو ذر", "الدمام - شارع خلف بن تميم / مجمعات الأعمال", "40 - 65 ر.س", "وصول", "دوام حكومي ومكتبي"),
    _r("ride_morning_04", 7, 0, 26.5170, 50.0340, "القطيف - سيهات / شارع علي الأنصاري", "الدمام - طريق 1 والواجهة البحرية", "55 - 65 ر.س", "وصول موظفين", "ذروة دوام صباحي"),
    _r("ride_morning_05", 7, 25, 26.3780, 50.1320, "الدمام - طريق الأمير محمد بن فهد / الظهران", "الظهران - بوابة أرامكو والمدينة الأكاديمية", "35 - 48 ر.س", "أوبر X", "دوام شركات الظهران"),
    _r("ride_morning_06", 7, 45, 26.4350, 50.1040, "الدمام - حي الشاطئ الشرقي / شارع الأشرعة", "الخبر - الحزام الذهبي / طريق الملك فيصل", "42 - 55 ر.س", "وصول / أوبر", "انتقال موظفين بين المدن"),

    # --- فترة الظهر وخروج الدوامات (11:45 - 14:45) ---
    _r("ride_midday_07", 12, 30, 26.4020, 50.0780, "الدمام - الفيصلية / شارع سهل بن صخر", "الخبر - شارع 25هـ / حي العزيزية", "38 - 48 ر.س", "وصول", "خروج مدارس ومعاهد"),
    _r("ride_midday_08", 13, 15, 26.4420, 50.0890, "الدمام - شارع 13 الصفا", "القطيف - حي داود القزاز وصفوى", "50 - 62 ر.س", "وصول", "خروج موظفي وردية النهار"),
    _r("ride_midday_09", 13, 40, 26.2840, 50.1980, "الخبر - العقربية / شارع 10 تقاطع مكة", "الدمام - حي المزروعية وحي الطبيشي", "40 - 52 ر.س", "أوبر X", "عودة الموظفين لمنازلهم"),
    _r("ride_midday_10", 14, 10, 26.3120, 50.1450, "الظهران - طريق الملك فهد محيط أرامكو", "بقيق / الأحساء طريق سريع", "80 - 130 ر.س", "سفر / بين مدن", "انصراف مهندسين وشركات مقاولات"),

    # --- فترة العصر والمساء (15:30 - 23:30) ---
    _r("ride_afternoon_11", 16, 20, 26.5310, 50.0240, "القطيف - عنك / شارع ابن النباشي", "الدمام - مجمع النخيل مول / شارع محمد القرطبي", "35 - 45 ر.س", "أوبر X", "مشاوير تسوق مسائية"),
    _r("ride_afternoon_12", 16, 45, 26.4110, 50.1190, "الدمام - عبدالله فؤاد / شارع عبدالرحمن البزاز", "الخبر - كورنيش الخبر الشمالي / شارع الأمير تركي", "48 - 60 ر.س", "وصول / أوبر", "مشاوير ترفيه ومطاعم"),
    _r("ride_afternoon_13", 17, 15, 26.3312, 50.1925, "الظهران / الخبر - مجمع الظهران بوابة 4", "الدمام - حي المنار وحي طيبة", "38 - 50 ر.س", "وصول", "تسوق وموظفي مبيعات"),
    _r("ride_evening_14", 19, 10, 26.3050, 50.2030, "الخبر - شارع الأمير فيصل بن فهد (البيبسي)", "الدمام - الشاطئ الغربي وطريق الخليج", "45 - 55 ر.س", "أوبر X", "مطاعم والكافيهات"),
    _r("ride_night_15", 22, 15, 26.4520, 50.1280, "الدمام - حي الشاطئ / مارينا مول", "القطيف - حي المجيدية وتاروت", "45 - 60 ر.س", "وصول / أوبر", "إغلاق المولات والعودة للمنازل"),
    _r("ride_night_16", 23, 30, 26.4710, 49.7980, "مطار الملك فهد الدولي (صالة القدوم)", "الخبر - الحزام الذهبي / الظهران", "90 - 130 ر.س", "UberXL / مطار", "رحلات قدوم ليلية"),

    # --- مواعيد وصول القطار لمحطة الدمام (التنبيه قبل الوصول بـ 30 دقيقة) ---
    {"id": "ride_train_01", "request_time": time(6, 59), "train_arrival": "07:29 AM", "days": [6, 0, 1, 2, 3, 4, 5], "alert_radius_km": 15.0, "pickup_lat": 26.4033, "pickup_lon": 50.0956, "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)", "dropoff_name": "الدمام / الخبر / الظهران / القطيف / الجبيل", "price": "35 - 75 ر.س", "service_type": "وصول / UberX / UberXL (ركاب القطار)", "shift_type": "وصول القطار 07:29 ص - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"},
    {"id": "ride_train_02", "request_time": time(8, 49), "train_arrival": "09:19 AM", "days": [6, 0, 1, 2, 3, 4, 5], "alert_radius_km": 15.0, "pickup_lat": 26.4033, "pickup_lon": 50.0956, "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)", "dropoff_name": "الدمام / الخبر / الظهران / القطيف", "price": "35 - 70 ر.س", "service_type": "وصول / UberX / UberXL (ركاب القطار)", "shift_type": "وصول القطار 09:19 ص - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"},
    {"id": "ride_train_03", "request_time": time(10, 52), "train_arrival": "11:22 AM", "days": [6, 0, 1, 2, 3, 4, 5], "alert_radius_km": 15.0, "pickup_lat": 26.4033, "pickup_lon": 50.0956, "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)", "dropoff_name": "الدمام / الخبر / الظهران / القطيف", "price": "35 - 70 ر.س", "service_type": "وصول / UberX / UberXL (ركاب القطار)", "shift_type": "وصول القطار 11:22 ص - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"},
    {"id": "ride_train_04_weekend", "request_time": time(12, 55), "train_arrival": "01:25 PM", "days": [4, 5], "alert_radius_km": 15.0, "pickup_lat": 26.4033, "pickup_lon": 50.0956, "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)", "dropoff_name": "الدمام / الخبر / الظهران / القطيف", "price": "35 - 70 ر.س", "service_type": "وصول / UberX / UberXL (ركاب القطار)", "shift_type": "وصول القطار 01:25 م - الجمعة والسبت (تنبيه قبل الموعد بـ 30 دقيقة)"},
    {"id": "ride_train_05", "request_time": time(15, 56), "train_arrival": "04:26 PM", "days": [6, 0, 1, 2, 3, 4, 5], "alert_radius_km": 15.0, "pickup_lat": 26.4033, "pickup_lon": 50.0956, "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)", "dropoff_name": "الدمام / الخبر / الظهران / القطيف", "price": "40 - 75 ر.س", "service_type": "وصول / UberX / UberXL (ركاب القطار)", "shift_type": "وصول القطار 04:26 م - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"},
    {"id": "ride_train_06", "request_time": time(18, 50), "train_arrival": "07:20 PM", "days": [6, 0, 1, 2, 3, 4, 5], "alert_radius_km": 15.0, "pickup_lat": 26.4033, "pickup_lon": 50.0956, "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)", "dropoff_name": "الدمام / الخبر / الظهران / القطيف", "price": "40 - 80 ر.س", "service_type": "وصول / UberX / UberXL (ركاب القطار)", "shift_type": "وصول القطار 07:20 م - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"},
    {"id": "ride_train_07_weekdays", "request_time": time(20, 28), "train_arrival": "08:58 PM", "days": [6, 0, 1, 2, 3], "alert_radius_km": 15.0, "pickup_lat": 26.4033, "pickup_lon": 50.0956, "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)", "dropoff_name": "الدمام / الخبر / الظهران / القطيف", "price": "40 - 80 ر.س", "service_type": "وصول / UberX / UberXL (ركاب القطار)", "shift_type": "وصول القطار 08:58 م - الأحد إلى الخميس (تنبيه قبل الموعد بـ 30 دقيقة)"},
    {"id": "ride_train_08", "request_time": time(22, 30), "train_arrival": "11:00 PM", "days": [6, 0, 1, 2, 3, 4, 5], "alert_radius_km": 15.0, "pickup_lat": 26.4033, "pickup_lon": 50.0956, "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)", "dropoff_name": "الدمام / الخبر / الظهران / القطيف", "price": "45 - 85 ر.س", "service_type": "وصول / UberX / UberXL (ركاب القطار)", "shift_type": "وصول القطار 11:00 م - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"},
    {"id": "ride_train_09", "request_time": time(23, 18), "train_arrival": "11:48 PM", "days": [6, 0, 1, 2, 3, 4, 5], "alert_radius_km": 15.0, "pickup_lat": 26.4033, "pickup_lon": 50.0956, "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)", "dropoff_name": "الدمام / الخبر / الظهران / القطيف", "price": "45 - 90 ر.س", "service_type": "وصول / UberX / UberXL (ركاب القطار)", "shift_type": "وصول القطار 11:48 م - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"},

    # --- أبرز الطلبات المستخرجة من مجلد AI ---
    _r("ride_ai_001", 12, 49, 26.4234, 50.0645, "شارع 7ك. الدمام", "605. الدمام", "52.53 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_002", 7, 23, 26.5624, 49.9841, "شارع 298528. القطيف", "شارع الامام محمد بن عبد الوهاب 4074. الدمام", "46.38 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_007", 4, 51, 26.4122, 50.0878, "شارع 10. الدمام", "شارع العبره 7318. الخبر", "40.91 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_012", 5, 20, 26.5414, 49.9971, "القطيف 32624", "شارع عثمان بن عفان. الدمام", "41.49 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_022", 16, 25, 26.4017, 50.0813, "شارع الحسن البصري 3831. الدمام", "شارع طارق بن زياد 3779 الخبر", "42.27 ر.س", "Wusool حصري", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_024", 6, 13, 26.4794, 50.0426, "شارع النسيم 5210. سيهات", "شارع القرية العليا 7245. الخبر", "49.44 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_025", 15, 24, 26.4388, 50.0949, "طريق الملك سعود بن عبد العزيز 8867. الخبر", "ب 8202. سيهات", "52.60 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_030", 12, 42, 26.2994, 50.1900, "طريق الملك فيصل بن عبد العزيز. الخبر", "24 7435. القطيف", "47.69 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_035", 5, 0, 26.2999, 50.2061, "شارع الأمير ماجد بن عبدالعزيز 7283. الخبر", "شارع سمية بنت اسلم 3261. الدمام", "42.42 ر.س", "Wusool حصري", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_038", 8, 7, 26.5442, 49.9989, "شارع 76622. القطيف", "شارع الأمير محمد بن عبد العزيز 7775. الخبر", "61.70 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_048", 15, 50, 26.2816, 50.1851, "شارع طارق بن زياد 2251 الخبر", "شارع 646416. القطيف", "49.99 ر.س", "Wusool حصري", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_049", 17, 26, 26.2764, 50.1936, "التعاطف 3489. الخبر", "605. الدمام", "67.55 ر.س", "Wusool حصري", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_051", 7, 29, 26.2749, 50.2154, "الشارع الثاني 8215، الخبر", "المزروعية، الدمام", "33.90 ر.س", "Wusool", "رحلة قياسية"),
    _r("ride_ai_052", 17, 34, 26.2872, 50.2070, "الشارع الثاني 8215. الخبر", "المزروعية. الدمام", "31.63 ر.س", "Wusool", "رحلة قياسية"),
    _r("ride_ai_060", 4, 5, 26.4190, 50.0479, "شارع عمر بن الخطاب 8615. الدمام", "شارع العلاء ابن محمد 4399. الخبر", "36.20 ر.س", "Wusool", "رحلة قياسية"),
    _r("ride_ai_068", 3, 47, 26.4374, 50.1023, "شارع أبو أوس الأسلمي 2810 الدمام", "شارع عبد الله بن عمر 7065. رأس تنورة", "43.16 ر.س", "Wusool حصري", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_069", 4, 49, 26.2761, 50.2041, "شارع عبد الرحمن الداخل 4298. الخبر", "شارع الدمام 7588. رأس تنورة", "79.94 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_074", 9, 19, 26.4032, 50.0973, "شارع الهدى 4807. الدمام", "شارع الملك سلمان بن عبد العزيز 2655. رأس تنورة", "46.84 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_084", 14, 45, 26.3056, 50.1955, "طريق الأمير فيصل بن فهد بن عبد العزيز 3132. الخبر", "طريق أحد. القطيف", "62.94 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_090", 18, 1, 26.2696, 50.1986, "طارق بن زياد. الخبر", "شارع الحسن بن علي 6511. القطيف", "54.53 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_110", 3, 56, 26.5654, 50.0009, "الكوثر 3730. القطيف", "شارع خلف بن تميم 2770. الدمام", "39.02 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_132", 5, 56, 26.2949, 50.1888, "شارع الأمير نايف بن عبد العزيز 8375. الخبر", "شارع محمد الكوفي 9138. بقيق", "102.37 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_187", 16, 32, 26.4180, 50.1018, "شارع الطبيعة 3010. الدمام", "طريق 2882118. الجبيل الصناعية", "84.05 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_194", 17, 30, 26.5619, 50.0183, "الفلاح 3801. القطيف", "شارع خلف بن تميم 2770. الدمام", "37.98 ر.س", "Wusool حصري", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_201", 4, 7, 26.4090, 50.0695, "شارع 15ب 7520. الدمام", "شارع الملك فيصل الغربي 6234. الجبيل", "60.90 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_351", 7, 7, 26.5884, 50.0141, "شارع علي الأنصاري 4776. القطيف", "طريق 1. الدمام", "60.81 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_388", 13, 39, 26.4412, 50.0897, "شارع 13 الصفا. الدمام", "شارع داود القزاز 3469 القطيف", "55.63 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_502", 10, 12, 26.3041, 50.2221, "جامعة الملك فهد للبترول 4104. الظهران", "القطيف", "47.71 ر.س", "Wusool حصري", "مشوار طويل (أكثر من 30 دقيقة)"),
]

def find_matching_rides(captain_lat, captain_lon, now_dt):
    matches = []
    current_minutes = now_dt.hour * 60 + now_dt.minute
    current_weekday = now_dt.weekday()

    for ride in HISTORICAL_RIDES:
        allowed_days = ride.get("days")
        if allowed_days is not None and current_weekday not in allowed_days:
            continue

        ride_minutes = ride["request_time"].hour * 60 + ride["request_time"].minute
        diff_minutes = abs(current_minutes - ride_minutes)
        diff_minutes = min(diff_minutes, 1440 - diff_minutes)

        if diff_minutes <= TIME_WINDOW_MINUTES:
            dist = geodesic((captain_lat, captain_lon), (ride["pickup_lat"], ride["pickup_lon"])).kilometers
            max_radius = ride.get("alert_radius_km", ALERT_RADIUS_KM)
            if dist <= max_radius:
                matches.append((ride, dist, diff_minutes))

    matches.sort(key=lambda x: (0 if "train_arrival" in x[0] else 1, x[1], x[2]))
    return matches

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚀 رادار الطلبات المباشر مفعل.\n"
        f"قاعدة البيانات محدثة وتضم {len(HISTORICAL_RIDES)} موقعاً وجدول قطارات الدمام.\n"
        "أرسل موقعك المباشر (Live Location) لإشعارك بالطلبات المحتملة ومواعيد وصول القطار قبل الموعد بـ 30 دقيقة."
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

    for ride, dist, diff_min in find_matching_rides(c_lat, c_lon, now_dt):
        history_key = (chat_id, ride["id"])
        if alert_history.get(history_key) == today_str:
            continue
        alert_history[history_key] = today_str

        if "train_arrival" in ride:
            alert_text = (
                f"🚆 *تنبيه وصول قطار لمحطة الدمام (قبل الموعد بـ 30 دقيقة)!*\n\n"
                f"📍 *الموقع:* {ride['pickup_name']}\n"
                f"📏 *يبعد عنك:* {dist:.1f} كم\n"
                f"⏰ *وقت التنبيه:* {ride['request_time'].strftime('%I:%M %p')} (وصول القطار: {ride['train_arrival']})\n"
                f"🎯 *الوجهة المسجلة:* {ride['dropoff_name']}\n"
                f"💰 *السعر المتوقع:* {ride['price']}\n"
                f"🚖 *النوع:* {ride['service_type']}\n"
                f"ℹ️ *الملاحظة:* {ride['shift_type']}."
            )
        else:
            alert_text = (
                f"🎯 *طلب محتمل في نفس التوقيت!*\n\n"
                f"📍 *الموقع:* {ride['pickup_name']}\n"
                f"📏 *يبعد عنك:* {dist:.1f} كم\n"
                f"⏰ *وقت الطلب السابق:* {ride['request_time'].strftime('%I:%M %p')}\n"
                f"🎯 *الوجهة المسجلة:* {ride['dropoff_name']}\n"
                f"💰 *السعر السابق:* {ride['price']}\n"
                f"🚖 *النوع:* {ride['service_type']}\n"
                f"ℹ️ *الملاحظة:* تم تسجيل طلب مطابق سابقاً من هذه النقطة في نفس هذا الوقت ({ride['shift_type']})."
            )

        await context.bot.send_message(chat_id=chat_id, text=alert_text, parse_mode="Markdown")

if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.run_polling()
