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
TIME_WINDOW_MINUTES = 30  # Search window (+/-) around request timestamp

alert_history = {}  # { (chat_id, ride_id): last_alerted_date }

# Health check HTTP server for Render deployment
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
# Historical Rides Database (556 Entries: 16 Base + 9 Train Arrivals + 531 Extracted)
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
        "price": "50 - 62 ر.س",
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
        "price": "38 - 50 ر.س",
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
        "shift_type": "مطاعم والكافيهات"
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
    },

    # --- مواعيد وصول القطار لمحطة الدمام (التنبيه قبل الوصول بـ 30 دقيقة) ---
    {
        "id": "ride_train_01",
        "request_time": time(6, 59),  # قبل وصول قطار 07:29 ص بـ 30 دقيقة
        "train_arrival": "07:29 AM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
        "alert_radius_km": 15.0,
        "pickup_lat": 26.4033,
        "pickup_lon": 50.0956,
        "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)",
        "dropoff_name": "الدمام / الخبر / الظهران / القطيف / الجبيل",
        "price": "35 - 75 ر.س",
        "service_type": "وصول / UberX / UberXL (ركاب القطار)",
        "shift_type": "وصول القطار 07:29 ص - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"
    },
    {
        "id": "ride_train_02",
        "request_time": time(8, 49),  # قبل وصول قطار 09:19 ص بـ 30 دقيقة
        "train_arrival": "09:19 AM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
        "alert_radius_km": 15.0,
        "pickup_lat": 26.4033,
        "pickup_lon": 50.0956,
        "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)",
        "dropoff_name": "الدمام / الخبر / الظهران / القطيف",
        "price": "35 - 70 ر.س",
        "service_type": "وصول / UberX / UberXL (ركاب القطار)",
        "shift_type": "وصول القطار 09:19 ص - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"
    },
    {
        "id": "ride_train_03",
        "request_time": time(10, 52),  # قبل وصول قطار 11:22 ص بـ 30 دقيقة
        "train_arrival": "11:22 AM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
        "alert_radius_km": 15.0,
        "pickup_lat": 26.4033,
        "pickup_lon": 50.0956,
        "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)",
        "dropoff_name": "الدمام / الخبر / الظهران / القطيف",
        "price": "35 - 70 ر.س",
        "service_type": "وصول / UberX / UberXL (ركاب القطار)",
        "shift_type": "وصول القطار 11:22 ص - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"
    },
    {
        "id": "ride_train_04_weekend",
        "request_time": time(12, 55),  # قبل وصول قطار 01:25 م بـ 30 دقيقة (الجمعة والسبت)
        "train_arrival": "01:25 PM",
        "days": [4, 5],  # الجمعة والسبت فقط
        "alert_radius_km": 15.0,
        "pickup_lat": 26.4033,
        "pickup_lon": 50.0956,
        "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)",
        "dropoff_name": "الدمام / الخبر / الظهران / القطيف",
        "price": "35 - 70 ر.س",
        "service_type": "وصول / UberX / UberXL (ركاب القطار)",
        "shift_type": "وصول القطار 01:25 م - الجمعة والسبت (تنبيه قبل الموعد بـ 30 دقيقة)"
    },
    {
        "id": "ride_train_05",
        "request_time": time(15, 56),  # قبل وصول قطار 04:26 م بـ 30 دقيقة
        "train_arrival": "04:26 PM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
        "alert_radius_km": 15.0,
        "pickup_lat": 26.4033,
        "pickup_lon": 50.0956,
        "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)",
        "dropoff_name": "الدمام / الخبر / الظهران / القطيف",
        "price": "40 - 75 ر.س",
        "service_type": "وصول / UberX / UberXL (ركاب القطار)",
        "shift_type": "وصول القطار 04:26 م - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"
    },
    {
        "id": "ride_train_06",
        "request_time": time(18, 50),  # قبل وصول قطار 07:20 م بـ 30 دقيقة
        "train_arrival": "07:20 PM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
        "alert_radius_km": 15.0,
        "pickup_lat": 26.4033,
        "pickup_lon": 50.0956,
        "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)",
        "dropoff_name": "الدمام / الخبر / الظهران / القطيف",
        "price": "40 - 80 ر.س",
        "service_type": "وصول / UberX / UberXL (ركاب القطار)",
        "shift_type": "وصول القطار 07:20 م - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"
    },
    {
        "id": "ride_train_07_weekdays",
        "request_time": time(20, 28),  # قبل وصول قطار 08:58 م بـ 30 دقيقة (الأحد - الخميس)
        "train_arrival": "08:58 PM",
        "days": [6, 0, 1, 2, 3],  # من الأحد إلى الخميس فقط
        "alert_radius_km": 15.0,
        "pickup_lat": 26.4033,
        "pickup_lon": 50.0956,
        "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)",
        "dropoff_name": "الدمام / الخبر / الظهران / القطيف",
        "price": "40 - 80 ر.س",
        "service_type": "وصول / UberX / UberXL (ركاب القطار)",
        "shift_type": "وصول القطار 08:58 م - الأحد إلى الخميس (تنبيه قبل الموعد بـ 30 دقيقة)"
    },
    {
        "id": "ride_train_08",
        "request_time": time(22, 30),  # قبل وصول قطار 11:00 م بـ 30 دقيقة
        "train_arrival": "11:00 PM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
        "alert_radius_km": 15.0,
        "pickup_lat": 26.4033,
        "pickup_lon": 50.0956,
        "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)",
        "dropoff_name": "الدمام / الخبر / الظهران / القطيف",
        "price": "45 - 85 ر.س",
        "service_type": "وصول / UberX / UberXL (ركاب القطار)",
        "shift_type": "وصول القطار 11:00 م - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"
    },
    {
        "id": "ride_train_09",
        "request_time": time(23, 18),  # قبل وصول قطار 11:48 م بـ 30 دقيقة
        "train_arrival": "11:48 PM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
        "alert_radius_km": 15.0,
        "pickup_lat": 26.4033,
        "pickup_lon": 50.0956,
        "pickup_name": "الدمام - محطة قطار الدمام (سار SAR)",
        "dropoff_name": "الدمام / الخبر / الظهران / القطيف",
        "price": "45 - 90 ر.س",
        "service_type": "وصول / UberX / UberXL (ركاب القطار)",
        "shift_type": "وصول القطار 11:48 م - يومياً (تنبيه قبل الموعد بـ 30 دقيقة)"
    },

    # --- Extracted Rides from Google Drive AI Folder (531 Images) ---
    _r("ride_ai_001", 12, 49, 26.4234, 50.0645, "شارع 7ك. الدمام", "605. الدمام", "52.53 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_002", 7, 23, 26.5624, 49.9841, "شارع 298528. القطيف", "شارع الامام محمد بن عبد الوهاب 4074. الدمام", "46.38 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_003", 19, 53, 26.4270, 50.0895, "شارع ينبع. الدمام 32236. المملكة العربية السعودية", "ابو حماد الانصاري. الدمام 32275. السعودية", "22.01 ر.س", "Wusool", "رحلة قياسية"),
    _r("ride_ai_004", 16, 27, 26.4202, 50.0753, "العدامة", "K", "25.07 ر.س", "Wusool", "رحلة قصيرة"),
    _r("ride_ai_005", 12, 47, 26.4380, 50.0671, "طريق 38. الدمام", "شارع 111. الدمام", "46.88 ر.س", "UberX", "رحلة قياسية"),
    _r("ride_ai_006", 17, 23, 26.4351, 50.0821, "شارع فاطمة الزهراء. الدمام", "شارع 6ج 3470. الدمام", "25.87 ر.س", "Wusool", "رحلة قياسية"),
    _r("ride_ai_007", 4, 51, 26.4122, 50.0878, "شارع 10. الدمام", "شارع العبره 7318. الخبر", "40.91 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_008", 7, 30, 26.2891, 50.2098, "الخبر", "الخبر", "35.90 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_009", 15, 39, 26.2804, 50.1990, "plank and baker&cook. Al Khobar", "شارع 14 7912. الخبر", "30.23 ر.س", "Wusool حصري", "رحلة قياسية"),
    _r("ride_ai_010", 7, 14, 26.4157, 50.0683, "الدمام", "الدمام", "20.26 ر.س", "Wusool", "رحلة قياسية"),
    _r("ride_ai_011", 8, 44, 26.5759, 50.0179, "شارع الحسن بن علي 6428. القطيف", "2د 6938. الدمام", "24.08 ر.س", "Wusool حصري", "رحلة قياسية"),
    _r("ride_ai_012", 5, 20, 26.5414, 49.9971, "15. القطيف .32624 المملكة العربية السعودية", "شارع عثمان بن عفان. الدمام 32251. السعودية", "41.49 ر.س", "Wusool", "مشوار طويل (أكثر من 30 دقيقة)"),
    _r("ride_ai_013", 18, 35, 26.3974, 50.1065, "الخضرية", "Google", "22.02 ر.س", "Wusool", "رحلة قياسية"),
    _r("ride_ai_014", 23, 32, 26.4402, 50.0710, "شارع الخنساء. الدمام 32236. المملكة العربية", "السعودية", "17.99 ر.س", "Wusool", "رحلة قياسية"),
    _r("ride_ai_015", 23, 32, 26.4397, 50.0785, "شارع الحكمه 4654. الدمام", "الدمام", "13.12 ر.س", "Wusool", "رحلة قصيرة"),
    _r("ride_ai_016", 11, 27,
