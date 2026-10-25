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
TIME_WINDOW_MINUTES = 30  # Search window (+/-) around request timestamp

alert_history = {}  # { (chat_id, ride_id): last_alerted_date }

# Health check HTTP server for Render deployment
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is operational.")

def run_health_server():
    server = HTTPServer(("0.0.0.0", 10000), HealthHandler)
    server.serve_forever()

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
        "request_time": time(6, 59),  # قبل وصول قطار 07:29 ص بـ 30 دقيقة
        "train_arrival": "07:29 AM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
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
        "request_time": time(8, 49),  # قبل وصول قطار 09:19 ص بـ 30 دقيقة
        "train_arrival": "09:19 AM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
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
        "request_time": time(10, 52),  # قبل وصول قطار 11:22 ص بـ 30 دقيقة
        "train_arrival": "11:22 AM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
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
        "request_time": time(12, 55),  # قبل وصول قطار 01:25 م بـ 30 دقيقة (الجمعة والسبت)
        "train_arrival": "01:25 PM",
        "days": [4, 5],  # الجمعة والسبت فقط
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
        "request_time": time(15, 56),  # قبل وصول قطار 04:26 م بـ 30 دقيقة
        "train_arrival": "04:26 PM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
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
        "request_time": time(18, 50),  # قبل وصول قطار 07:20 م بـ 30 دقيقة
        "train_arrival": "07:20 PM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
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
        "request_time": time(20, 28),  # قبل وصول قطار 08:58 م بـ 30 دقيقة (الأحد - الخميس)
        "train_arrival": "08:58 PM",
        "days": [6, 0, 1, 2, 3],  # من الأحد إلى الخميس فقط
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
        "request_time": time(22, 30),  # قبل وصول قطار 11:00 م بـ 30 دقيقة
        "train_arrival": "11:00 PM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
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
        "request_time": time(23, 18),  # قبل وصول قطار 11:48 م بـ 30 دقيقة
        "train_arrival": "11:48 PM",
        "days": [6, 0, 1, 2, 3, 4, 5],  # يومياً (الأحد - السبت)
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
    {
        "id": "ride_ai_001",  # IMG_1927.JPG
        "request_time": time(12, 49),
        "pickup_lat": 26.4234,
        "pickup_lon": 50.0645,
        "pickup_name": "شارع 7ك. الدمام",
        "dropoff_name": "605. الدمام",
        "price": "52.53 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_002",  # IMG_1928.JPG
        "request_time": time(7, 23),
        "pickup_lat": 26.5624,
        "pickup_lon": 49.9841,
        "pickup_name": "شارع 298528. القطيف",
        "dropoff_name": "شارع الامام محمد بن عبد الوهاب 4074. الدمام",
        "price": "46.38 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_003",  # IMG_1929.JPG
        "request_time": time(19, 53),
        "pickup_lat": 26.4270,
        "pickup_lon": 50.0895,
        "pickup_name": "شارع ينبع. الدمام 32236. المملكة العربية السعودية",
        "dropoff_name": "ابو حماد الانصاري. الدمام 32275. السعودية",
        "price": "22.01 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_004",  # IMG_1930.JPG
        "request_time": time(16, 27),
        "pickup_lat": 26.4202,
        "pickup_lon": 50.0753,
        "pickup_name": "العدامة",
        "dropoff_name": "K",
        "price": "25.07 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_005",  # IMG_1931.JPG
        "request_time": time(12, 47),
        "pickup_lat": 26.4380,
        "pickup_lon": 50.0671,
        "pickup_name": "طريق 38. الدمام",
        "dropoff_name": "شارع 111. الدمام",
        "price": "46.88 ر.س",
        "service_type": "UberX",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_006",  # IMG_1932.JPG
        "request_time": time(17, 23),
        "pickup_lat": 26.4351,
        "pickup_lon": 50.0821,
        "pickup_name": "شارع فاطمة الزهراء. الدمام",
        "dropoff_name": "شارع 6ج 3470. الدمام",
        "price": "25.87 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_007",  # IMG_1933.JPG
        "request_time": time(4, 51),
        "pickup_lat": 26.4122,
        "pickup_lon": 50.0878,
        "pickup_name": "شارع 10. الدمام",
        "dropoff_name": "شارع العبره 7318. الخبر",
        "price": "40.91 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_008",  # IMG_1934.JPG
        "request_time": time(7, 30),
        "pickup_lat": 26.2891,
        "pickup_lon": 50.2098,
        "pickup_name": "الخبر",
        "dropoff_name": "الخبر",
        "price": "35.90 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_009",  # IMG_1935.JPG
        "request_time": time(15, 39),
        "pickup_lat": 26.2804,
        "pickup_lon": 50.1990,
        "pickup_name": "plank and baker&cook. Al Khobar",
        "dropoff_name": "شارع 14 7912. الخبر",
        "price": "30.23 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_010",  # IMG_1936.JPG
        "request_time": time(7, 14),
        "pickup_lat": 26.4157,
        "pickup_lon": 50.0683,
        "pickup_name": "الدمام",
        "dropoff_name": "الدمام",
        "price": "20.26 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_011",  # IMG_1937.JPG
        "request_time": time(8, 44),
        "pickup_lat": 26.5759,
        "pickup_lon": 50.0179,
        "pickup_name": "شارع الحسن بن علي 6428. القطيف",
        "dropoff_name": "2د 6938. الدمام",
        "price": "24.08 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_012",  # IMG_1938.JPG
        "request_time": time(5, 20),
        "pickup_lat": 26.5414,
        "pickup_lon": 49.9971,
        "pickup_name": "15. القطيف .32624 المملكة العربية السعودية",
        "dropoff_name": "شارع عثمان بن عفان. الدمام 32251. السعودية",
        "price": "41.49 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_013",  # IMG_1939.JPG
        "request_time": time(18, 35),
        "pickup_lat": 26.3974,
        "pickup_lon": 50.1065,
        "pickup_name": "الخضرية",
        "dropoff_name": "Google",
        "price": "22.02 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_014",  # IMG_1940.JPG
        "request_time": time(23, 32),
        "pickup_lat": 26.4402,
        "pickup_lon": 50.0710,
        "pickup_name": "شارع الخنساء. الدمام 32236. المملكة العربية",
        "dropoff_name": "السعودية",
        "price": "17.99 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_015",  # IMG_1941.JPG
        "request_time": time(23, 32),
        "pickup_lat": 26.4397,
        "pickup_lon": 50.0785,
        "pickup_name": "شارع الحكمه 4654. الدمام",
        "dropoff_name": "الدمام",
        "price": "13.12 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_016",  # IMG_1942.JPG
        "request_time": time(11, 27),
        "pickup_lat": 26.4084,
        "pickup_lon": 50.1095,
        "pickup_name": "شمال) مشارف",
        "dropoff_name": "الدمام الشرقي",
        "price": "23.66 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_017",  # IMG_1943.JPG
        "request_time": time(13, 58),
        "pickup_lat": 26.5042,
        "pickup_lon": 50.0438,
        "pickup_name": "5:27",
        "dropoff_name": "النابية",
        "price": "15.84 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_018",  # IMG_1944.JPG
        "request_time": time(13, 58),
        "pickup_lat": 26.5680,
        "pickup_lon": 50.0094,
        "pickup_name": "المروءة 2739. القطيف",
        "dropoff_name": "شارع الحادي عشرة 7125. الدمام",
        "price": "34.89 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_019",  # IMG_1945.JPG
        "request_time": time(13, 58),
        "pickup_lat": 26.5844,
        "pickup_lon": 50.0007,
        "pickup_name": "شارع عبدالله بن حارث 6851. القطيف",
        "dropoff_name": "طريق اكثم بن صيفي 4292. الدمام",
        "price": "39.76 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_020",  # IMG_1946.JPG
        "request_time": time(8, 25),
        "pickup_lat": 26.4092,
        "pickup_lon": 50.0643,
        "pickup_name": "شارع 26 ب 8131. الدمام",
        "dropoff_name": "شارع الشهاب الطائفي 3406. الخبر",
        "price": "23.58 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_021",  # IMG_1947.JPG
        "request_time": time(6, 48),
        "pickup_lat": 26.5584,
        "pickup_lon": 49.9839,
        "pickup_name": "شارع حجر ابن عدي 4525. القطيف",
        "dropoff_name": "شارع الصواري 77844. القطيف",
        "price": "11.34 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_022",  # IMG_1948.JPG
        "request_time": time(16, 25),
        "pickup_lat": 26.4017,
        "pickup_lon": 50.0813,
        "pickup_name": "شارع الحسن البصري 3831. الدمام",
        "dropoff_name": "شارع طارق بن زياد 3779 الخبر",
        "price": "42.27 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_023",  # IMG_1949.JPG
        "request_time": time(6, 6),
        "pickup_lat": 26.4137,
        "pickup_lon": 50.0881,
        "pickup_name": "Dammam. SA 4800",
        "dropoff_name": "الدمام",
        "price": "58.67 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_024",  # IMG_1950.JPG
        "request_time": time(6, 13),
        "pickup_lat": 26.4794,
        "pickup_lon": 50.0426,
        "pickup_name": "شارع النسيم 5210. سيهات",
        "dropoff_name": "شارع القرية العليا 7245. الخبر",
        "price": "49.44 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_025",  # IMG_1951.JPG
        "request_time": time(15, 24),
        "pickup_lat": 26.4388,
        "pickup_lon": 50.0949,
        "pickup_name": "طريق الملك سعود بن عبد العزيز 8867. الخبر",
        "dropoff_name": "ب 8202. سيهات",
        "price": "52.60 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_026",  # IMG_1952.JPG
        "request_time": time(17, 24),
        "pickup_lat": 26.4871,
        "pickup_lon": 50.0333,
        "pickup_name": "سيهات",
        "dropoff_name": "سيهات",
        "price": "60.49 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_027",  # IMG_1953.JPG
        "request_time": time(17, 24),
        "pickup_lat": 26.5507,
        "pickup_lon": 50.0134,
        "pickup_name": "74026. القطيف",
        "dropoff_name": "الأسراب 2423 الخبر",
        "price": "46.66 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_028",  # IMG_1954.JPG
        "request_time": time(17, 24),
        "pickup_lat": 26.2891,
        "pickup_lon": 50.2098,
        "pickup_name": "الخبر",
        "dropoff_name": "شارع الثالث والعشرون 3366. الخبر",
        "price": "21.00 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_029",  # IMG_1955.JPG
        "request_time": time(17, 24),
        "pickup_lat": 27.0176,
        "pickup_lon": 49.6547,
        "pickup_name": "طريق الظهران الجبيل السريع 7960. الدمام",
        "dropoff_name": "شارع عبد الملك العصامي 2221 الخبر",
        "price": "48.30 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_030",  # IMG_1956.JPG
        "request_time": time(12, 42),
        "pickup_lat": 26.2994,
        "pickup_lon": 50.1900,
        "pickup_name": "طريق الملك فيصل بن عبد العزيز. الخبر",
        "dropoff_name": "24 7435. القطيف",
        "price": "47.69 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_031",  # IMG_1957.JPG
        "request_time": time(12, 42),
        "pickup_lat": 26.5607,
        "pickup_lon": 50.0332,
        "pickup_name": "و شارع الأمير بندر بن عبد العزيز 3085 الرياض",
        "dropoff_name": "شارع الأنهار 2617 الرياض",
        "price": "73.26 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_032",  # IMG_1958.JPG
        "request_time": time(2, 52),
        "pickup_lat": 26.2996,
        "pickup_lon": 50.2171,
        "pickup_name": "شارع الوادي الاخضر 2164. الخبر",
        "dropoff_name": "شارع الربيعية 766913. القطيف",
        "price": "56.44 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_033",  # IMG_1959.JPG
        "request_time": time(13, 14),
        "pickup_lat": 26.5588,
        "pickup_lon": 50.0282,
        "pickup_name": "شارع عثمان الداغستاني 8001. الرياض",
        "dropoff_name": "طريق الملك فهد بن عبد العزيز 7315. الرياض",
        "price": "33.21 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_034",  # IMG_1960.JPG
        "request_time": time(14, 34),
        "pickup_lat": 26.2736,
        "pickup_lon": 50.2093,
        "pickup_name": "شارع الأمير ناصر 7416. الخبر",
        "dropoff_name": "10هـ 7414. الدمام",
        "price": "41.86 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_035",  # IMG_1961.JPG
        "request_time": time(5, 0),
        "pickup_lat": 26.2999,
        "pickup_lon": 50.2061,
        "pickup_name": "شارع الأمير ماجد بن عبدالعزيز 7283. الخبر",
        "dropoff_name": "شارع سمية بنت اسلم 3261. الدمام",
        "price": "42.42 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_036",  # IMG_1962.JPG
        "request_time": time(10, 41),
        "pickup_lat": 26.2845,
        "pickup_lon": 50.2204,
        "pickup_name": "طريق الكورنيش 6592. الدمام",
        "dropoff_name": "شارع السابع عشر 4131. الخبر",
        "price": "29.81 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_037",  # IMG_1963.JPG
        "request_time": time(0, 16),
        "pickup_lat": 26.4037,
        "pickup_lon": 50.1035,
        "pickup_name": "11:10 م",
        "dropoff_name": "الشاطئ الغربي",
        "price": "6.19 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_038",  # IMG_1964.JPG
        "request_time": time(8, 7),
        "pickup_lat": 26.5442,
        "pickup_lon": 49.9989,
        "pickup_name": "شارع 76622. القطيف",
        "dropoff_name": "شارع الأمير محمد بن عبد العزيز 7775. الخبر",
        "price": "61.70 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_039",  # IMG_1965.JPG
        "request_time": time(8, 1),
        "pickup_lat": 26.5496,
        "pickup_lon": 50.0206,
        "pickup_name": "شارع عبد الملك بن أبي علي 4243. القطيف",
        "dropoff_name": "شارع بقيق 2407. الدمام",
        "price": "32.11 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_040",  # IMG_1966.JPG
        "request_time": time(8, 57),
        "pickup_lat": 26.5779,
        "pickup_lon": 49.9896,
        "pickup_name": "شارع 2 ب 6962. القطيف",
        "dropoff_name": "شارع الأمير محمد بن فهد 9369. الدمام",
        "price": "33.11 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_041",  # IMG_1967.JPG
        "request_time": time(12, 30),
        "pickup_lat": 26.5449,
        "pickup_lon": 50.0244,
        "pickup_name": "شارع القارب 2531. القطيف",
        "dropoff_name": "Custodian of The Two Holy Mosques Rd. Al- Thuqbah. Al Khobar",
        "price": "41.52 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_042",  # IMG_1968.JPG
        "request_time": time(0, 56),
        "pickup_lat": 26.4382,
        "pickup_lon": 50.0970,
        "pickup_name": "605, الدمام",
        "dropoff_name": "22أ 7337, الدمام",
        "price": "32.59 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_043",  # IMG_1969.JPG
        "request_time": time(0, 56),
        "pickup_lat": 26.4157,
        "pickup_lon": 50.0683,
        "pickup_name": "الدمام",
        "dropoff_name": "الدمام",
        "price": "42.49 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_044",  # IMG_1970.JPG
        "request_time": time(0, 56),
        "pickup_lat": 26.5737,
        "pickup_lon": 50.0074,
        "pickup_name": "القطيف",
        "dropoff_name": "القطيف",
        "price": "42.49 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_045",  # IMG_1971.JPG
        "request_time": time(0, 56),
        "pickup_lat": 26.5854,
        "pickup_lon": 50.0261,
        "pickup_name": "شارع زهران 3464 القطيف",
        "dropoff_name": "طريق الملك فهد بن عبد العزيز 7777. الخبر",
        "price": "42.49 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_046",  # IMG_1972.JPG
        "request_time": time(14, 5),
        "pickup_lat": 26.3526,
        "pickup_lon": 50.2076,
        "pickup_name": "Kempinski Al Othman Hotel Al Khobar. Al Khobar",
        "dropoff_name": "شارع الأمير محمد بن فهد 8384. الدمام",
        "price": "22.21 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_047",  # IMG_1973.JPG
        "request_time": time(14, 14),
        "pickup_lat": 26.4365,
        "pickup_lon": 50.0898,
        "pickup_name": "شارع سعد بن أبي وقاص. الدمام",
        "dropoff_name": "605. الدمام",
        "price": "41.33 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_048",  # IMG_1974.JPG
        "request_time": time(15, 50),
        "pickup_lat": 26.2816,
        "pickup_lon": 50.1851,
        "pickup_name": "شارع طارق بن زياد 2251 الخبر",
        "dropoff_name": "شارع 646416. القطيف",
        "price": "49.99 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_049",  # IMG_1975.JPG
        "request_time": time(17, 26),
        "pickup_lat": 26.2764,
        "pickup_lon": 50.1936,
        "pickup_name": "التعاطف 3489. الخبر",
        "dropoff_name": "605. الدمام",
        "price": "67.55 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_050",  # IMG_1976.JPG
        "request_time": time(6, 38),
        "pickup_lat": 26.2349,
        "pickup_lon": 50.2013,
        "pickup_name": "شارع العلا 6759. الخبر",
        "dropoff_name": "طريق الظهران الدمام 7125. الظهران",
        "price": "17.88 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_051",  # IMG_1977.JPG
        "request_time": time(7, 29),
        "pickup_lat": 26.2749,
        "pickup_lon": 50.2154,
        "pickup_name": "الشارع الثاني 8215, الخبر",
        "dropoff_name": "Al Mazruiyah, Dammam",
        "price": "33.90 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_052",  # IMG_1978.JPG
        "request_time": time(17, 34),
        "pickup_lat": 26.2872,
        "pickup_lon": 50.2070,
        "pickup_name": "الشارع الثاني 8215. الخبر",
        "dropoff_name": "Al Mazruiyah. Dammam",
        "price": "31.63 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_053",  # IMG_1979.JPG
        "request_time": time(17, 34),
        "pickup_lat": 26.2872,
        "pickup_lon": 50.2070,
        "pickup_name": "الشارع الثاني 8215. الخبر",
        "dropoff_name": "Al Mazruiyah. Dammam",
        "price": "38.27 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_054",  # IMG_1980.JPG
        "request_time": time(17, 45),
        "pickup_lat": 26.2872,
        "pickup_lon": 50.2070,
        "pickup_name": "الشارع الثاني 8215. الخبر",
        "dropoff_name": "Al Mazruiyah. Dammam",
        "price": "31.68 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_055",  # IMG_1981.JPG
        "request_time": time(7, 43),
        "pickup_lat": 26.2749,
        "pickup_lon": 50.2154,
        "pickup_name": "الشارع الثاني 8215, الخبر",
        "dropoff_name": "Al Mazruiyah, Dammam",
        "price": "38.27 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_056",  # IMG_1982.JPG
        "request_time": time(21, 27),
        "pickup_lat": 26.4088,
        "pickup_lon": 50.1023,
        "pickup_name": "طريق ابو هريرة 3188, الدمام",
        "dropoff_name": "بوليفارد الجامعة, الظهران",
        "price": "28.18 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_057",  # IMG_1983.JPG
        "request_time": time(12, 50),
        "pickup_lat": 26.5534,
        "pickup_lon": 50.0037,
        "pickup_name": "شارع الحسين بن مهران 9562. القطيف",
        "dropoff_name": "طريق الملك سعود بن عبد العزيز 2820 الخبر",
        "price": "42.75 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_058",  # IMG_1984.JPG
        "request_time": time(13, 55),
        "pickup_lat": 26.4022,
        "pickup_lon": 50.1071,
        "pickup_name": "شارع الميناء 2407. الدمام",
        "dropoff_name": "شارع الملك سعود بن عبد العزيز 4159. الدمام",
        "price": "11.46 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_059",  # IMG_1985.JPG
        "request_time": time(3, 59),
        "pickup_lat": 26.4130,
        "pickup_lon": 50.0579,
        "pickup_name": "شارع سلمان الفارسي, الدمام",
        "dropoff_name": "شارع 41 7289, الدمام",
        "price": "29.59 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_060",  # IMG_1986.JPG
        "request_time": time(4, 5),
        "pickup_lat": 26.4190,
        "pickup_lon": 50.0479,
        "pickup_name": "شارع عمر بن الخطاب 8615. الدمام",
        "dropoff_name": "شارع العلاء ابن محمد 4399. الخبر",
        "price": "36.20 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_061",  # IMG_1987.JPG
        "request_time": time(6, 47),
        "pickup_lat": 26.2859,
        "pickup_lon": 50.2186,
        "pickup_name": "شارع تيماء 3188. الخبر",
        "dropoff_name": "شارع 15ب 7520. الدمام",
        "price": "136.87 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_062",  # IMG_1988.JPG
        "request_time": time(6, 47),
        "pickup_lat": 26.5632,
        "pickup_lon": 50.0136,
        "pickup_name": "شارع جابر بن عبد الله 3386. القطيف",
        "dropoff_name": "شارع 16د 7455. الدمام",
        "price": "20.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_063",  # IMG_1989.JPG
        "request_time": time(6, 47),
        "pickup_lat": 26.5427,
        "pickup_lon": 50.0276,
        "pickup_name": "شارع صفوان ابو معدان 3371. القطيف",
        "dropoff_name": "شارع 20. الخبر",
        "price": "37.31 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_064",  # IMG_1990.JPG
        "request_time": time(6, 47),
        "pickup_lat": 26.2944,
        "pickup_lon": 50.2063,
        "pickup_name": "شارع 32152. الخبر",
        "dropoff_name": "المغيرة بن شعبة 7539. القطيف",
        "price": "49.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_065",  # IMG_1991.JPG
        "request_time": time(12, 24),
        "pickup_lat": 26.2832,
        "pickup_lon": 50.1245,
        "pickup_name": "شارع راس تنوره 2342 الظهران",
        "dropoff_name": "شارع الصحابة 4782. القطيف",
        "price": "39.34 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_066",  # IMG_1992.JPG
        "request_time": time(12, 24),
        "pickup_lat": 26.2621,
        "pickup_lon": 50.2263,
        "pickup_name": "شارع 20. الخبر",
        "dropoff_name": "شارع 751711. الدمام",
        "price": "35.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_067",  # IMG_1993.JPG
        "request_time": time(3, 47),
        "pickup_lat": 26.2952,
        "pickup_lon": 50.1563,
        "pickup_name": "طريق الملك عبد العزيز 3863. الظهران",
        "dropoff_name": "شارع 753522. الظهران",
        "price": "18.61 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_068",  # IMG_1994.JPG
        "request_time": time(3, 47),
        "pickup_lat": 26.4374,
        "pickup_lon": 50.1023,
        "pickup_name": "شارع أبو أوس الأسلمي 2810 الدمام",
        "dropoff_name": "شارع عبد الله بن عمر 7065. رأس تنورة",
        "price": "43.16 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_069",  # IMG_1995.JPG
        "request_time": time(4, 49),
        "pickup_lat": 26.2761,
        "pickup_lon": 50.2041,
        "pickup_name": "شارع عبد الرحمن الداخل 4298. الخبر",
        "dropoff_name": "شارع الدمام 7588. رأس تنورة",
        "price": "79.94 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_070",  # IMG_1996.JPG
        "request_time": time(15, 13),
        "pickup_lat": 26.4432,
        "pickup_lon": 50.0678,
        "pickup_name": "شارع علي آل مغامس 2692. الدمام",
        "dropoff_name": "شارع النابغة التغلي 7573. الخبر",
        "price": "42.39 ر.س",
        "service_type": "Comfort",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_071",  # IMG_1997.JPG
        "request_time": time(15, 13),
        "pickup_lat": 26.4200,
        "pickup_lon": 50.0891,
        "pickup_name": "شارع أبو أوس الأسلمي. الدمام",
        "dropoff_name": "طريق الخليج 3544. الدمام",
        "price": "9.12 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_072",  # IMG_1998.JPG
        "request_time": time(22, 18),
        "pickup_lat": 26.3236,
        "pickup_lon": 50.1454,
        "pickup_name": "طريق المدارس, الظهران",
        "dropoff_name": "طريق الحزام الاكاديمي 4602, الظهران",
        "price": "19.32 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_073",  # IMG_1999.JPG
        "request_time": time(19, 0),
        "pickup_lat": 26.4210,
        "pickup_lon": 50.1038,
        "pickup_name": "شارع 13ب 7898, الدمام",
        "dropoff_name": "طريق 117 2771, الدمام",
        "price": "21.10 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_074",  # IMG_2001.JPG
        "request_time": time(9, 19),
        "pickup_lat": 26.4032,
        "pickup_lon": 50.0973,
        "pickup_name": "شارع الهدى 4807. الدمام",
        "dropoff_name": "شارع الملك سلمان بن عبد العزيز 2655. رأس تنورة",
        "price": "46.84 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_075",  # IMG_2002.JPG
        "request_time": time(9, 19),
        "pickup_lat": 26.5629,
        "pickup_lon": 49.9969,
        "pickup_name": "شارع احمد بن صفوان 3807. القطيف",
        "dropoff_name": "طريق الأمير فيصل بن فهد بن عبدالعزيز الظهران",
        "price": "50.96 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_076",  # IMG_2003.JPG
        "request_time": time(9, 19),
        "pickup_lat": 26.5809,
        "pickup_lon": 50.0264,
        "pickup_name": "219214. القطيف",
        "dropoff_name": "3ج 8622. الدمام",
        "price": "25.16 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_077",  # IMG_2004.JPG
        "request_time": time(9, 19),
        "pickup_lat": 26.5559,
        "pickup_lon": 50.0296,
        "pickup_name": "شارع 774516. القطيف",
        "dropoff_name": "شارع 691536. الدمام",
        "price": "42.73 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_078",  # IMG_2005.JPG
        "request_time": time(19, 17),
        "pickup_lat": 26.4035,
        "pickup_lon": 50.1044,
        "pickup_name": "طريق ابو هريرة 3387. الدمام",
        "dropoff_name": "ابو حامد الغزالي. الدمام",
        "price": "125.62 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_079",  # IMG_2006.JPG
        "request_time": time(9, 24),
        "pickup_lat": 26.4035,
        "pickup_lon": 50.1044,
        "pickup_name": "طريق ابو هريرة 3387. الدمام",
        "dropoff_name": "شارع 613. الدمام",
        "price": "24.00 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_080",  # IMG_2007.JPG
        "request_time": time(9, 24),
        "pickup_lat": 26.2671,
        "pickup_lon": 50.1953,
        "pickup_name": "شارع الأمير مشاري بن عبدالعزيز 6235. الخبر",
        "dropoff_name": "شارع الملك خالد بن عبدالعزيز الدمام",
        "price": "35.09 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_081",  # IMG_2008.JPG
        "request_time": time(9, 24),
        "pickup_lat": 26.4306,
        "pickup_lon": 50.0975,
        "pickup_name": "طريق الملك خالد 8073. الخبر",
        "dropoff_name": "شارع زيد بن حارثة 3813. الدمام",
        "price": "25.53 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_082",  # IMG_2009.JPG
        "request_time": time(9, 24),
        "pickup_lat": 26.2779,
        "pickup_lon": 50.1888,
        "pickup_name": "شارع جازان 8645. الخبر",
        "dropoff_name": "Nakheel Mall. Dammam",
        "price": "28.71 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_083",  # IMG_2010.JPG
        "request_time": time(11, 15),
        "pickup_lat": 26.3006,
        "pickup_lon": 50.2326,
        "pickup_name": "شارع 6 ج 2689. الخبر",
        "dropoff_name": "605. الدمام",
        "price": "57.08 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_084",  # IMG_2011.JPG
        "request_time": time(14, 45),
        "pickup_lat": 26.3056,
        "pickup_lon": 50.1955,
        "pickup_name": "طريق الأمير فيصل بن فهد بن عبد العزيز 3132. الخبر",
        "dropoff_name": "طريق أحد. القطيف",
        "price": "62.94 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_085",  # IMG_2012.JPG
        "request_time": time(4, 47),
        "pickup_lat": 26.2704,
        "pickup_lon": 50.2193,
        "pickup_name": "شارع ابو الحسن الحراني 7008. الخبر",
        "dropoff_name": "شارع 785077. الدمام",
        "price": "54.75 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_086",  # IMG_2013.JPG
        "request_time": time(4, 47),
        "pickup_lat": 26.3021,
        "pickup_lon": 50.1986,
        "pickup_name": "شارع الثالث والعشرون 3395. الخبر",
        "dropoff_name": "3566 Prince Faisal Bin Fahd Road. Doha Al Janubiyah. Az Zahran",
        "price": "19.29 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_087",  # IMG_2014.JPG
        "request_time": time(11, 17),
        "pickup_lat": 26.3031,
        "pickup_lon": 50.1881,
        "pickup_name": "شارع 25 3054, الخبر",
        "dropoff_name": "شارع الكرامة 3577, الظهران",
        "price": "9.91 ر.س",
        "service_type": "Comfort حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_088",  # IMG_2015.JPG
        "request_time": time(11, 17),
        "pickup_lat": 26.5851,
        "pickup_lon": 50.0094,
        "pickup_name": "شارع حجر ابن عدي 6797. القطيف",
        "dropoff_name": "طريق الخليج. الدمام",
        "price": "27.63 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_089",  # IMG_2016.JPG
        "request_time": time(4, 44),
        "pickup_lat": 26.4087,
        "pickup_lon": 50.0465,
        "pickup_name": "شارع أمير المؤمنين عمر بن الخطاب 7364. الدمام",
        "dropoff_name": "شارع 3883809. القطيف",
        "price": "42.18 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_090",  # IMG_2017.JPG
        "request_time": time(18, 1),
        "pickup_lat": 26.2696,
        "pickup_lon": 50.1986,
        "pickup_name": "طارق بن زياد. الخبر",
        "dropoff_name": "شارع الحسن بن علي 6511. القطيف",
        "price": "54.53 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_091",  # IMG_2029.JPG
        "request_time": time(8, 14),
        "pickup_lat": 26.4132,
        "pickup_lon": 50.0893,
        "pickup_name": "شارع نعيم بن يزيد 3042. الدمام",
        "dropoff_name": "طريق الأمير محمد بن فهد 7298. الدمام",
        "price": "30.76 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_092",  # IMG_2030.JPG
        "request_time": time(18, 15),
        "pickup_lat": 26.4105,
        "pickup_lon": 50.0836,
        "pickup_name": "شارع 88111. الدمام",
        "dropoff_name": "783711. الدمام",
        "price": "22.65 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_093",  # IMG_2031.JPG
        "request_time": time(18, 15),
        "pickup_lat": 26.2947,
        "pickup_lon": 50.1538,
        "pickup_name": "شارع أضواء صناعية. الظهران",
        "dropoff_name": "شارع الحزام الذهبي 6929. الظهران",
        "price": "32.26 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_094",  # IMG_2032.JPG
        "request_time": time(13, 12),
        "pickup_lat": 26.4154,
        "pickup_lon": 50.0783,
        "pickup_name": "11 مدينة الملك فيصل الجامعية 3193. الدمام",
        "dropoff_name": "شارع العدل 2990. الدمام",
        "price": "36.33 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_095",  # IMG_2033.JPG
        "request_time": time(13, 13),
        "pickup_lat": 26.2932,
        "pickup_lon": 50.2268,
        "pickup_name": "شارع الأمير مشاري بن عبد العزيز 6235. الخبر",
        "dropoff_name": "طريق الأمير نايف بن عبد العزيز. الدمام",
        "price": "43.05 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_096",  # IMG_2034.JPG
        "request_time": time(3, 20),
        "pickup_lat": 26.4245,
        "pickup_lon": 50.0848,
        "pickup_name": "شارع 80209. الدمام",
        "dropoff_name": "شارع مكة المكرمة 6616. الخبر",
        "price": "30.00 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_097",  # IMG_2035.JPG
        "request_time": time(14, 36),
        "pickup_lat": 26.4308,
        "pickup_lon": 50.1086,
        "pickup_name": "شارع الأمير محمد بن فهد 8945. الدمام",
        "dropoff_name": "طريق الأمير نايف بن عبد العزيز 4985. الأحساء",
        "price": "155.04 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_098",  # IMG_2036.JPG
        "request_time": time(4, 49),
        "pickup_lat": 26.5514,
        "pickup_lon": 49.9981,
        "pickup_name": "شارع جعفر الطيار 3546. القطيف",
        "dropoff_name": "شارع الاميلح 6546. القطيف",
        "price": "17.46 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_099",  # IMG_2037.JPG
        "request_time": time(14, 56),
        "pickup_lat": 26.2991,
        "pickup_lon": 50.2251,
        "pickup_name": "شارع الأمير حمود بن عبد العزيز. الخبر",
        "dropoff_name": "شارع اسحق بن ميسره 3269. الدمام",
        "price": "43.16 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_100",  # IMG_2038.JPG
        "request_time": time(4, 58),
        "pickup_lat": 26.9953,
        "pickup_lon": 49.6690,
        "pickup_name": "شارع 11أ 4600, الجبيل",
        "dropoff_name": "الشاطئ 8830, الجبيل",
        "price": "29.42 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_101",  # IMG_2039.JPG
        "request_time": time(4, 58),
        "pickup_lat": 26.2889,
        "pickup_lon": 50.2218,
        "pickup_name": "شارع الانداس. الخبر",
        "dropoff_name": "شارع زياد بن جارية 4272. الدمام",
        "price": "43.14 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_102",  # IMG_2040.JPG
        "request_time": time(4, 58),
        "pickup_lat": 26.2764,
        "pickup_lon": 50.2278,
        "pickup_name": "شارع الجبهاء 6919. الخبر",
        "dropoff_name": "شارع 19 6914. الدمام",
        "price": "42.60 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_103",  # IMG_2041.JPG
        "request_time": time(4, 0),
        "pickup_lat": 26.4524,
        "pickup_lon": 50.1131,
        "pickup_name": "طريق الخليج 8090. سيهات",
        "dropoff_name": "شارع الشهادة 3189. القطيف",
        "price": "18.67 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_104",  # IMG_2042.JPG
        "request_time": time(6, 33),
        "pickup_lat": 26.4064,
        "pickup_lon": 50.0851,
        "pickup_name": "شارع 147 7203. الدمام",
        "dropoff_name": "شارع 62552. الخبر",
        "price": "50.69 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_105",  # IMG_2043.JPG
        "request_time": time(6, 33),
        "pickup_lat": 26.5519,
        "pickup_lon": 50.0001,
        "pickup_name": "شارع البناء 4925. القطيف",
        "dropoff_name": "12و 7243. الدمام",
        "price": "45.78 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_106",  # IMG_2044.JPG
        "request_time": time(7, 53),
        "pickup_lat": 26.5644,
        "pickup_lon": 50.0334,
        "pickup_name": "شارع جعفر الطيار 7499. القطيف",
        "dropoff_name": "شارع الشهاب الطائفي 3406. الخبر",
        "price": "65.04 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_107",  # IMG_2045.JPG
        "request_time": time(7, 53),
        "pickup_lat": 26.5684,
        "pickup_lon": 49.9911,
        "pickup_name": "شارع 676022. القطيف",
        "dropoff_name": "شارع 3684923. القطيف",
        "price": "24.46 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_108",  # IMG_2046.JPG
        "request_time": time(11, 50),
        "pickup_lat": 26.4362,
        "pickup_lon": 50.0723,
        "pickup_name": "شارع 11 2923, الدمام",
        "dropoff_name": "طريق الأشرعه 5396, الدمام",
        "price": "18.12 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_109",  # IMG_2047.JPG
        "request_time": time(3, 56),
        "pickup_lat": 26.4122,
        "pickup_lon": 50.0925,
        "pickup_name": "شارع يحيى بن ياقوت 5403. الدمام",
        "dropoff_name": "شارع الخليل بن احمد 4630. الدمام",
        "price": "21.40 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_110",  # IMG_2048.JPG
        "request_time": time(3, 56),
        "pickup_lat": 26.5654,
        "pickup_lon": 50.0009,
        "pickup_name": "الكوثر 3730. القطيف",
        "dropoff_name": "شارع خلف بن تميم 2770. الدمام",
        "price": "39.02 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_111",  # IMG_2049.JPG
        "request_time": time(8, 34),
        "pickup_lat": 26.5614,
        "pickup_lon": 49.9929,
        "pickup_name": "العطاء 2928 القطيف",
        "dropoff_name": "شارع حسان بن ثابت 7502. القطيف",
        "price": "12.00 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_112",  # IMG_2050.JPG
        "request_time": time(8, 34),
        "pickup_lat": 26.4390,
        "pickup_lon": 50.1113,
        "pickup_name": "طريق الملك عبد الله بن عبد العزيز. الخبر",
        "dropoff_name": "الدمام",
        "price": "53.44 ر.س",
        "service_type": "Comfort حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_113",  # IMG_2051.JPG
        "request_time": time(14, 2),
        "pickup_lat": 26.2899,
        "pickup_lon": 50.1943,
        "pickup_name": "شارع الوادي الاخضر 2164 الخبر",
        "dropoff_name": "شارع 17ج 6559. القطيف",
        "price": "64.82 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_114",  # IMG_2052.JPG
        "request_time": time(16, 17),
        "pickup_lat": 26.4347,
        "pickup_lon": 50.0753,
        "pickup_name": "شارع 613, الدمام",
        "dropoff_name": "شارع 12أ 8359, الدمام",
        "price": "26.55 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_115",  # IMG_2053.JPG
        "request_time": time(10, 57),
        "pickup_lat": 26.5866,
        "pickup_lon": 50.0266,
        "pickup_name": "شارع الشهادة 2968. القطيف",
        "dropoff_name": "شارع بشار بن برد 2898 الخبر",
        "price": "53.49 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_116",  # IMG_2054.JPG
        "request_time": time(11, 1),
        "pickup_lat": 26.5573,
        "pickup_lon": 50.0292,
        "pickup_name": "طريق أحد 3569. القطيف",
        "dropoff_name": "شارع زبير بن العوام 7912. الدمام",
        "price": "44.07 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_117",  # IMG_2055.JPG
        "request_time": time(11, 1),
        "pickup_lat": 26.5635,
        "pickup_lon": 50.0214,
        "pickup_name": "طريق أحد 3569. القطيف",
        "dropoff_name": "شارع زبير بن العوام 7912. الدمام",
        "price": "40.92 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_118",  # IMG_2056.JPG
        "request_time": time(11, 5),
        "pickup_lat": 26.5784,
        "pickup_lon": 49.9914,
        "pickup_name": "18 ب 6805. القطيف",
        "dropoff_name": "وادي العمارية 6283. الخبر",
        "price": "60.76 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_119",  # IMG_2057.JPG
        "request_time": time(11, 44),
        "pickup_lat": 26.4506,
        "pickup_lon": 50.1161,
        "pickup_name": "طريق الخليج 6750, القطيف",
        "dropoff_name": "14د 7633, الدمام",
        "price": "30.27 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_120",  # IMG_2058.JPG
        "request_time": time(12, 22),
        "pickup_lat": 26.5417,
        "pickup_lon": 50.0219,
        "pickup_name": "758822. القطيف",
        "dropoff_name": "شارع دوار الادارة 4137. الظهران",
        "price": "53.27 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_121",  # IMG_2059.JPG
        "request_time": time(2, 49),
        "pickup_lat": 26.3977,
        "pickup_lon": 50.0883,
        "pickup_name": "شارع 2 الفردوس 8462, الدمام",
        "dropoff_name": "شارع 1ب 3090, الخبر",
        "price": "35.48 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_122",  # IMG_2060.JPG
        "request_time": time(11, 44),
        "pickup_lat": 26.4612,
        "pickup_lon": 50.1335,
        "pickup_name": "طريق الأشرعه 5396. الدمام",
        "dropoff_name": "طريق أحد 3942. القطيف",
        "price": "25.78 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_123",  # IMG_2061.JPG
        "request_time": time(11, 44),
        "pickup_lat": 25.3955,
        "pickup_lon": 49.5768,
        "pickup_name": "شارع عبد الله الساعدي 3366. الأحساء",
        "dropoff_name": "Al-Ahsa International Airport (HOF). Hofuf",
        "price": "25.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_124",  # IMG_2062.JPG
        "request_time": time(11, 44),
        "pickup_lat": 26.4077,
        "pickup_lon": 50.0680,
        "pickup_name": "طريق 384910. الدمام",
        "dropoff_name": "ممر ح 3376. رأس تنورة",
        "price": "69.91 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_125",  # IMG_2063.JPG
        "request_time": time(15, 24),
        "pickup_lat": 26.5836,
        "pickup_lon": 50.0096,
        "pickup_name": "24أ 7435, القطيف",
        "dropoff_name": "شارع 13 3333, الخبر",
        "price": "54.87 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_126",  # IMG_2064.JPG
        "request_time": time(15, 24),
        "pickup_lat": 26.5836,
        "pickup_lon": 50.0096,
        "pickup_name": "24أ 7435, القطيف",
        "dropoff_name": "شارع 13 3333, الخبر",
        "price": "54.87 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_127",  # IMG_2065.JPG
        "request_time": time(3, 52),
        "pickup_lat": 26.4094,
        "pickup_lon": 50.1098,
        "pickup_name": "33 ميناء الملك عبد العزيز 3374. الدمام",
        "dropoff_name": "23 ب 8310. الدمام",
        "price": "45.38 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_128",  # IMG_2066.JPG
        "request_time": time(3, 59),
        "pickup_lat": 26.2864,
        "pickup_lon": 50.1480,
        "pickup_name": "شارع 1 8588, الظهران",
        "dropoff_name": "10 ه 6945, الدمام",
        "price": "33.57 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_129",  # IMG_2067.JPG
        "request_time": time(4, 49),
        "pickup_lat": 26.4190,
        "pickup_lon": 50.0894,
        "pickup_name": "طريق الملك فهد بن عبد العزيز 9198. الظهران",
        "dropoff_name": "شارع اسحق بن الجراح 3045. الدمام",
        "price": "35.53 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_130",  # IMG_2068.JPG
        "request_time": time(4, 59),
        "pickup_lat": 26.2836,
        "pickup_lon": 50.1936,
        "pickup_name": "غيلان ابن عقبة 6823. الخبر",
        "dropoff_name": "شارع 881424. الدمام",
        "price": "49.38 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_131",  # IMG_2069.JPG
        "request_time": time(15, 5),
        "pickup_lat": 26.3026,
        "pickup_lon": 50.2011,
        "pickup_name": "غيلان ابن عقبة 6823. الخبر",
        "dropoff_name": "شارع 881424. الدمام",
        "price": "50.66 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_132",  # IMG_2070.JPG
        "request_time": time(5, 56),
        "pickup_lat": 26.2949,
        "pickup_lon": 50.1888,
        "pickup_name": "شارع الأمير نايف بن عبد العزيز 8375. الخبر",
        "dropoff_name": "شارع محمد الكوفي 9138. بقيق",
        "price": "102.37 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_133",  # IMG_2071.JPG
        "request_time": time(18, 55),
        "pickup_lat": 26.2947,
        "pickup_lon": 50.1233,
        "pickup_name": "شارع 212 غرب الظهران 8476 الظهران",
        "dropoff_name": "شارع ابن طولون 4875. رأس تنورة",
        "price": "58.42 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_134",  # IMG_2072.JPG
        "request_time": time(2, 4),
        "pickup_lat": 26.2921,
        "pickup_lon": 50.1968,
        "pickup_name": "شارع عبد الله بن حذافه 7571. الخبر",
        "dropoff_name": "شارع الهيثم بن عدي 3776. القطيف",
        "price": "35.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_135",  # IMG_2073.JPG
        "request_time": time(17, 40),
        "pickup_lat": 26.4180,
        "pickup_lon": 50.0648,
        "pickup_name": "طريق أبو حدرية 7683. الدمام",
        "dropoff_name": "شارع 29034. الخبر",
        "price": "46.34 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_136",  # IMG_2074.JPG
        "request_time": time(17, 40),
        "pickup_lat": 26.5589,
        "pickup_lon": 50.0094,
        "pickup_name": "شارع عمار بن ياسر 3075. القطيف",
        "dropoff_name": "شارع 705911. الدمام",
        "price": "34.98 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_137",  # IMG_2075.JPG
        "request_time": time(17, 40),
        "pickup_lat": 26.5639,
        "pickup_lon": 50.0271,
        "pickup_name": "124 7435. القطيف",
        "dropoff_name": "شارع 333313 الخبر",
        "price": "56.94 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_138",  # IMG_2076.JPG
        "request_time": time(13, 8),
        "pickup_lat": 26.5629,
        "pickup_lon": 49.9924,
        "pickup_name": "124 7435. القطيف",
        "dropoff_name": "شارع 333313 الخبر",
        "price": "55.86 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_139",  # IMG_2077.JPG
        "request_time": time(18, 2),
        "pickup_lat": 26.2991,
        "pickup_lon": 50.2098,
        "pickup_name": "الشارع الثالث 4314. الخبر",
        "dropoff_name": "ية و على",
        "price": "31.87 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_140",  # IMG_2078.JPG
        "request_time": time(18, 2),
        "pickup_lat": 26.4302,
        "pickup_lon": 50.1080,
        "pickup_name": "شارع 3ج 6615. الدمام",
        "dropoff_name": "الدمام",
        "price": "24.73 ر.س",
        "service_type": "Comfort حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_141",  # IMG_2079.JPG
        "request_time": time(15, 24),
        "pickup_lat": 26.4388,
        "pickup_lon": 50.0949,
        "pickup_name": "طريق الملك سعود بن عبد العزيز 8867. الخبر",
        "dropoff_name": "ب 8202. سيهات",
        "price": "52.60 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_142",  # IMG_2080.JPG
        "request_time": time(6, 13),
        "pickup_lat": 26.4794,
        "pickup_lon": 50.0426,
        "pickup_name": "شارع النسيم 5210. سيهات",
        "dropoff_name": "شارع القرية العليا 7245. الخبر",
        "price": "49.44 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_143",  # IMG_2081.JPG
        "request_time": time(16, 25),
        "pickup_lat": 26.4017,
        "pickup_lon": 50.0813,
        "pickup_name": "شارع الحسن البصري 3831. الدمام",
        "dropoff_name": "شارع طارق بن زياد 3779 الخبر",
        "price": "42.27 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_144",  # IMG_2082.JPG
        "request_time": time(16, 25),
        "pickup_lat": 26.5722,
        "pickup_lon": 50.0214,
        "pickup_name": "شارع 1 ج 7003. القطيف",
        "dropoff_name": "شارع المتنبي 4038. الدمام",
        "price": "48.06 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_145",  # IMG_2083.JPG
        "request_time": time(8, 25),
        "pickup_lat": 26.4092,
        "pickup_lon": 50.0643,
        "pickup_name": "شارع 26 ب 8131. الدمام",
        "dropoff_name": "شارع الشهاب الطائفي 3406. الخبر",
        "price": "23.58 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_146",  # IMG_2084.JPG
        "request_time": time(8, 25),
        "pickup_lat": 26.5844,
        "pickup_lon": 50.0007,
        "pickup_name": "شارع عبدالله بن حارث 6851. القطيف",
        "dropoff_name": "طريق اكثم بن صيفي 4292. الدمام",
        "price": "39.76 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_147",  # IMG_2085.JPG
        "request_time": time(22, 27),
        "pickup_lat": 26.4871,
        "pickup_lon": 50.0333,
        "pickup_name": "سيهات",
        "dropoff_name": "عمر بن عبد العزيز, سيهات",
        "price": "52.57 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_148",  # IMG_2086.JPG
        "request_time": time(8, 44),
        "pickup_lat": 26.5759,
        "pickup_lon": 50.0179,
        "pickup_name": "شارع الحسن بن علي 6428. القطيف",
        "dropoff_name": "2د 6938. الدمام",
        "price": "24.08 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_149",  # IMG_2087.JPG
        "request_time": time(4, 57),
        "pickup_lat": 26.4378,
        "pickup_lon": 50.1045,
        "pickup_name": "شارع الأمير محمد بن فهد 9369. الدمام",
        "dropoff_name": "طريق حمزة بن عبد المطلب 2767. الدمام",
        "price": "33.88 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_150",  # IMG_2088.JPG
        "request_time": time(15, 39),
        "pickup_lat": 26.2804,
        "pickup_lon": 50.1990,
        "pickup_name": "plank and baker&cook. Al Khobar",
        "dropoff_name": "شارع 791214. الخبر",
        "price": "30.23 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_151",  # IMG_2089.JPG
        "request_time": time(7, 30),
        "pickup_lat": 26.2891,
        "pickup_lon": 50.2098,
        "pickup_name": "الخبر",
        "dropoff_name": "الخبر",
        "price": "35.90 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_152",  # IMG_2090.JPG
        "request_time": time(4, 51),
        "pickup_lat": 26.4227,
        "pickup_lon": 50.0723,
        "pickup_name": "شارع 10. الدمام",
        "dropoff_name": "شارع العبره 7318. الخبر",
        "price": "40.91 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_153",  # IMG_2091.JPG
        "request_time": time(17, 23),
        "pickup_lat": 26.4351,
        "pickup_lon": 50.0821,
        "pickup_name": "شارع فاطمة الزهراء. الدمام",
        "dropoff_name": "شارع 6 ج 3470. الدمام",
        "price": "25.87 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_154",  # IMG_2092.JPG
        "request_time": time(17, 23),
        "pickup_lat": 26.4129,
        "pickup_lon": 50.1093,
        "pickup_name": "11 الريان 7453. الدمام",
        "dropoff_name": "شارع التسامح 8530. الخبر",
        "price": "40.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_155",  # IMG_2093.JPG
        "request_time": time(17, 23),
        "pickup_lat": 26.5884,
        "pickup_lon": 50.0141,
        "pickup_name": "شارع علي الأنصاري 4776. القطيف",
        "dropoff_name": "طريق الدمام",
        "price": "53.83 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_156",  # IMG_2094.JPG
        "request_time": time(17, 23),
        "pickup_lat": 26.5804,
        "pickup_lon": 49.9891,
        "pickup_name": "شارع 12ب 7212. القطيف",
        "dropoff_name": "شارع عبدالرحمن بن حبيب 2146. الدمام",
        "price": "37.73 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_157",  # IMG_2095.JPG
        "request_time": time(17, 23),
        "pickup_lat": 26.2861,
        "pickup_lon": 50.1936,
        "pickup_name": "الشارع السادس 8271. الخبر",
        "dropoff_name": "شارع أمير المؤمنين عمر بن الخطاب 8175 الدمام",
        "price": "3.30 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_158",  # IMG_2096.JPG
        "request_time": time(8, 44),
        "pickup_lat": 26.4427,
        "pickup_lon": 50.0725,
        "pickup_name": "2 ب 7640. الدمام",
        "dropoff_name": "شارع 85. الدمام",
        "price": "50.19 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_159",  # IMG_2097.JPG
        "request_time": time(8, 44),
        "pickup_lat": 26.5809,
        "pickup_lon": 49.9954,
        "pickup_name": "عبدالله بن عباس 6545. القطيف",
        "dropoff_name": "القطيف",
        "price": "36.44 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_160",  # IMG_2098.JPG
        "request_time": time(8, 44),
        "pickup_lat": 26.4207,
        "pickup_lon": 50.0678,
        "pickup_name": "شارع 874424. الدمام",
        "dropoff_name": "الدمام",
        "price": "28.20 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_161",  # IMG_2099.JPG
        "request_time": time(9, 54),
        "pickup_lat": 26.4382,
        "pickup_lon": 50.0970,
        "pickup_name": "605, الدمام",
        "dropoff_name": "10أ 8211, الدمام",
        "price": "54.72 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_162",  # IMG_2100.JPG
        "request_time": time(5, 54),
        "pickup_lat": 26.4434,
        "pickup_lon": 50.0998,
        "pickup_name": "شارع 64216. الدمام",
        "dropoff_name": "شارع الخنساء. الدمام",
        "price": "19.23 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_163",  # IMG_2101.JPG
        "request_time": time(1, 7),
        "pickup_lat": 26.5644,
        "pickup_lon": 50.0334,
        "pickup_name": "شارع جعفر الطيار 7499. القطيف",
        "dropoff_name": "شارع الشهاب الطائفي ا الخبر",
        "price": "50.36 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_164",  # IMG_2102.JPG
        "request_time": time(13, 39),
        "pickup_lat": 26.4432,
        "pickup_lon": 50.0731,
        "pickup_name": "13 مدينة الملك فيصل الجامعية 6431. الدمام",
        "dropoff_name": "شارع 57124. القطيف",
        "price": "50.80 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_165",  # IMG_2103.JPG
        "request_time": time(13, 43),
        "pickup_lat": 26.4380,
        "pickup_lon": 50.0716,
        "pickup_name": "703310. الدمام",
        "dropoff_name": "شارع 8 ج 6614. الدمام",
        "price": "61.50 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_166",  # IMG_2104.JPG
        "request_time": time(10, 0),
        "pickup_lat": 26.4227,
        "pickup_lon": 50.0962,
        "pickup_name": "شارع الورود 3411. الدمام",
        "dropoff_name": "2 الفردوس 7914. الدمام",
        "price": "13.01 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_167",  # IMG_2105.JPG
        "request_time": time(6, 11),
        "pickup_lat": 26.5741,
        "pickup_lon": 50.0089,
        "pickup_name": "شارع 29ب 9366. القطيف",
        "dropoff_name": "شارع السعادة. الدمام",
        "price": "33.83 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_168",  # IMG_2106.JPG
        "request_time": time(6, 12),
        "pickup_lat": 26.4427,
        "pickup_lon": 50.0725,
        "pickup_name": "شارع مصعب الزبيدي 8946. الدمام",
        "dropoff_name": "طريق حزام المدارس 8576. الظهران",
        "price": "31.75 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_169",  # IMG_2107.JPG
        "request_time": time(16, 22),
        "pickup_lat": 26.4380,
        "pickup_lon": 50.0903,
        "pickup_name": "شارع نايف بن مالك 3910. الدمام",
        "dropoff_name": "11ب 7857 الدمام",
        "price": "22.82 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_170",  # IMG_2108.JPG
        "request_time": time(6, 28),
        "pickup_lat": 26.3006,
        "pickup_lon": 50.2143,
        "pickup_name": "شارع ابو جعفر بن هارون 7529. الخبر",
        "dropoff_name": "شارع 2 الفردوس 8462. الدمام",
        "price": "41.12 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_171",  # IMG_2109.JPG
        "request_time": time(6, 43),
        "pickup_lat": 26.5884,
        "pickup_lon": 50.0141,
        "pickup_name": "شارع علي الأنصاري 4776. القطيف",
        "dropoff_name": "طريق الدمام",
        "price": "48.76 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_172",  # IMG_2110.JPG
        "request_time": time(6, 44),
        "pickup_lat": 26.5414,
        "pickup_lon": 50.0001,
        "pickup_name": "شارع ابن منظور 5074. القطيف",
        "dropoff_name": "طريق الملك عبد العزيز 6352. سيهات",
        "price": "29.55 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_173",  # IMG_2111.JPG
        "request_time": time(7, 11),
        "pickup_lat": 26.4025,
        "pickup_lon": 50.1028,
        "pickup_name": "شارع 874424 الدمام",
        "dropoff_name": "Dammam",
        "price": "36.33 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_174",  # IMG_2112.JPG
        "request_time": time(7, 11),
        "pickup_lat": 26.5499,
        "pickup_lon": 50.0130,
        "pickup_name": "شارع عمار بن ياسر 4841. القطيف",
        "dropoff_name": "شارع عبدالله بن الربيع 2208 الدمام",
        "price": "36.64 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_175",  # IMG_2113.JPG
        "request_time": time(7, 11),
        "pickup_lat": 26.5499,
        "pickup_lon": 50.0130,
        "pickup_name": "شارع عمار بن ياسر 4841. القطيف",
        "dropoff_name": "شارع عبدالله بن الربيع 2208. الدمام",
        "price": "36.64 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_176",  # IMG_2114.JPG
        "request_time": time(3, 57),
        "pickup_lat": 26.4417,
        "pickup_lon": 50.1170,
        "pickup_name": "طريق الملك عبد الله بن عبد العزيز 7512. الدمام",
        "dropoff_name": "شارع ابو هريرة 6493. الدمام",
        "price": "18.03 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_177",  # IMG_2115.JPG
        "request_time": time(14, 10),
        "pickup_lat": 26.4442,
        "pickup_lon": 50.0673,
        "pickup_name": "Noodlez. Dammam",
        "dropoff_name": "شارع صالح بن حنبل 7466. الخبر",
        "price": "15.87 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_178",  # IMG_2116.JPG
        "request_time": time(4, 9),
        "pickup_lat": 26.3278,
        "pickup_lon": 50.1646,
        "pickup_name": "شارع أبن تيمية 4620. الظهران",
        "dropoff_name": "3566 Prince Faisal Bin Fahd Road. Doha Al Janubiyah. Az Zahran",
        "price": "34.35 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_179",  # IMG_2117.JPG
        "request_time": time(16, 23),
        "pickup_lat": 26.7218,
        "pickup_lon": 50.0802,
        "pickup_name": "شارع بريره, رأس تنورة",
        "dropoff_name": "6أ 8363, سيهات",
        "price": "57.56 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_180",  # IMG_2118.JPG
        "request_time": time(12, 5),
        "pickup_lat": 26.5572,
        "pickup_lon": 49.9977,
        "pickup_name": "18د 6491, القطيف",
        "dropoff_name": "شارع 13 3333, الخبر",
        "price": "52.53 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_181",  # IMG_2119.JPG
        "request_time": time(12, 45),
        "pickup_lat": 26.5582,
        "pickup_lon": 49.9921,
        "pickup_name": "758914. القطيف",
        "dropoff_name": "شارع المبرز الخبر",
        "price": "46.82 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_182",  # IMG_2120.JPG
        "request_time": time(2, 48),
        "pickup_lat": 26.5666,
        "pickup_lon": 49.9899,
        "pickup_name": "شارع حزام الرضا 2780. القطيف",
        "dropoff_name": "605. الدمام",
        "price": "43.49 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_183",  # IMG_2121.JPG
        "request_time": time(5, 22),
        "pickup_lat": 26.3041,
        "pickup_lon": 50.2003,
        "pickup_name": "طريق الأمير فيصل بن فهد 6864. الظهران",
        "dropoff_name": "شارع العاشر 3045 الخبر",
        "price": "17.74 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_184",  # IMG_2122.JPG
        "request_time": time(5, 22),
        "pickup_lat": 26.5552,
        "pickup_lon": 49.9861,
        "pickup_name": "شارع حسن الغنام 4893. القطيف",
        "dropoff_name": "طريق الظهران الجبيل السريع 7960. الدمام",
        "price": "40.64 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_185",  # IMG_2123.JPG
        "request_time": time(5, 22),
        "pickup_lat": 26.5496,
        "pickup_lon": 50.0206,
        "pickup_name": "شارع عبد الملك بن أبي علي 4243. القطيف",
        "dropoff_name": "شارع بقيق 2407. الدمام",
        "price": "41.75 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_186",  # IMG_2124.JPG
        "request_time": time(2, 3),
        "pickup_lat": 26.2771,
        "pickup_lon": 50.1836,
        "pickup_name": "شارع 62552. الخبر",
        "dropoff_name": "شارع أحمد عيسى المرشدي 6851. القطيف",
        "price": "65.42 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_187",  # IMG_2125.JPG
        "request_time": time(16, 32),
        "pickup_lat": 26.4180,
        "pickup_lon": 50.1018,
        "pickup_name": "شارع الطبيعة 3010. الدمام",
        "dropoff_name": "طريق 2882118. الجبيل الصناعية",
        "price": "84.05 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_188",  # IMG_2126.JPG
        "request_time": time(14, 58),
        "pickup_lat": 26.3199,
        "pickup_lon": 50.1498,
        "pickup_name": "شارع إبراهيم الدينوري 7244. الظهران",
        "dropoff_name": "شارع الاخلاص 4273. القطيف",
        "price": "48.42 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_189",  # IMG_2127.JPG
        "request_time": time(18, 36),
        "pickup_lat": 26.4147,
        "pickup_lon": 50.0785,
        "pickup_name": "طريق 19 7098, الدمام",
        "dropoff_name": "شارع 4, الخبر",
        "price": "32.45 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_190",  # IMG_2128.JPG
        "request_time": time(1, 44),
        "pickup_lat": 26.5479,
        "pickup_lon": 50.0226,
        "pickup_name": "شارع 298528. القطيف",
        "dropoff_name": "شارع الامام محمد بن عبد الوهاب 4074. الدمام",
        "price": "50.80 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_191",  # IMG_2129.JPG
        "request_time": time(1, 44),
        "pickup_lat": 26.5487,
        "pickup_lon": 50.0132,
        "pickup_name": "شارع عمار بن ياسر 4943. القطيف",
        "dropoff_name": "شارع الحارث بن أوس 2651 الدمام",
        "price": "35.72 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_192",  # IMG_2130.JPG
        "request_time": time(7, 28),
        "pickup_lat": 26.5831,
        "pickup_lon": 50.0301,
        "pickup_name": "شارع القافلة 2548. القطيف",
        "dropoff_name": "طريق الملك فهد بن عبد العزيز 9466. الخبر",
        "price": "20.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_193",  # IMG_2131.JPG
        "request_time": time(17, 30),
        "pickup_lat": 26.4427,
        "pickup_lon": 50.0776,
        "pickup_name": "عباد بن عبد الله 2558. الدمام",
        "dropoff_name": "شارع 36684. الخبر",
        "price": "34.86 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_194",  # IMG_2132.JPG
        "request_time": time(17, 30),
        "pickup_lat": 26.5619,
        "pickup_lon": 50.0183,
        "pickup_name": "الفلاح 3801. القطيف",
        "dropoff_name": "شارع خلف بن تميم 2770. الدمام",
        "price": "37.98 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_195",  # IMG_2133.JPG
        "request_time": time(17, 30),
        "pickup_lat": 26.4157,
        "pickup_lon": 50.0686,
        "pickup_name": "شارع ابو عنبس بن جبر 4690. الدمام",
        "dropoff_name": "شارع 1 ب 6646 الخبر",
        "price": "36.85 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_196",  # IMG_2134.JPG
        "request_time": time(17, 30),
        "pickup_lat": 26.5824,
        "pickup_lon": 50.0039,
        "pickup_name": "شارع البناء 4897. القطيف",
        "dropoff_name": "شارع زيد بن حارثة 3813. الدمام",
        "price": "37.86 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_197",  # IMG_2135.JPG
        "request_time": time(17, 14),
        "pickup_lat": 26.4102,
        "pickup_lon": 50.1043,
        "pickup_name": "شارع رافع بن رافع 3417. الدمام",
        "dropoff_name": "شارع 12 ب 8263. الدمام",
        "price": "30.49 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_198",  # IMG_2136.JPG
        "request_time": time(18, 38),
        "pickup_lat": 26.4040,
        "pickup_lon": 50.0665,
        "pickup_name": "24د 7298. الدمام",
        "dropoff_name": "حيان ابن المنذر 3957. الدمام",
        "price": "14.37 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_199",  # IMG_2137.JPG
        "request_time": time(15, 26),
        "pickup_lat": 26.4385,
        "pickup_lon": 50.1099,
        "pickup_name": "طريق الأمير محمد بن فهد 8277. الدمام",
        "dropoff_name": "شارع 32201. رأس تنورة",
        "price": "57.61 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_200",  # IMG_2138.JPG
        "request_time": time(5, 56),
        "pickup_lat": 26.4287,
        "pickup_lon": 50.0776,
        "pickup_name": "شارع بن ابي البر 3827. الدمام",
        "dropoff_name": "شارع ابراهيم بن مهران 4645. الخبر",
        "price": "33.02 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_201",  # IMG_2139.JPG
        "request_time": time(4, 7),
        "pickup_lat": 26.4090,
        "pickup_lon": 50.0695,
        "pickup_name": "شارع 15ب 7520. الدمام",
        "dropoff_name": "شارع الملك فيصل الغربي 6234. الجبيل",
        "price": "60.90 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_202",  # IMG_2140.JPG
        "request_time": time(3, 30),
        "pickup_lat": 26.5496,
        "pickup_lon": 50.0079,
        "pickup_name": "شارع رافع ابن الحارث 2949. القطيف",
        "dropoff_name": "605. الدمام",
        "price": "41.07 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_203",  # IMG_2141.JPG
        "request_time": time(6, 26),
        "pickup_lat": 26.5220,
        "pickup_lon": 49.9856,
        "pickup_name": "شارع علي الجشي 6357. القطيف",
        "dropoff_name": "شارع سلمان الفارسي الدمام",
        "price": "53.54 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_204",  # IMG_2142.JPG
        "request_time": time(6, 38),
        "pickup_lat": 26.5884,
        "pickup_lon": 50.0141,
        "pickup_name": "شارع علي الأنصاري 4776. القطيف",
        "dropoff_name": "طريق الدمام",
        "price": "52.44 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_205",  # IMG_2143.JPG
        "request_time": time(7, 14),
        "pickup_lat": 26.4427,
        "pickup_lon": 50.0725,
        "pickup_name": "2 ب 7640. الدمام",
        "dropoff_name": "شارع 85. الدمام",
        "price": "59.81 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_206",  # IMG_2144.JPG
        "request_time": time(7, 14),
        "pickup_lat": 26.5489,
        "pickup_lon": 50.0214,
        "pickup_name": "786210. القطيف",
        "dropoff_name": "شارع 6723105. الدمام",
        "price": "63.75 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_207",  # IMG_2145.JPG
        "request_time": time(7, 14),
        "pickup_lat": 26.5539,
        "pickup_lon": 50.0109,
        "pickup_name": "شارع 70856. القطيف",
        "dropoff_name": "شارع الأمير محمد بن فهد 7426. الدمام",
        "price": "41.53 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_208",  # IMG_2146.JPG
        "request_time": time(7, 14),
        "pickup_lat": 26.5487,
        "pickup_lon": 50.0321,
        "pickup_name": "شارع 76622. القطيف",
        "dropoff_name": "شارع الوادي الاخضر 2164 الخبر",
        "price": "57.06 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_209",  # IMG_2147.JPG
        "request_time": time(8, 41),
        "pickup_lat": 26.5821,
        "pickup_lon": 50.0219,
        "pickup_name": "ب 6559. القطيف",
        "dropoff_name": "شارع ابو العباس المؤدب 3428. الدمام",
        "price": "30.55 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_210",  # IMG_2148.JPG
        "request_time": time(8, 41),
        "pickup_lat": 26.5614,
        "pickup_lon": 50.0169,
        "pickup_name": "شارع 71567. القطيف",
        "dropoff_name": "شارع 7د 7679. الدمام",
        "price": "40.51 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_211",  # IMG_2149.JPG
        "request_time": time(8, 43),
        "pickup_lat": 26.5636,
        "pickup_lon": 49.9931,
        "pickup_name": "شارع 2 ب 6927. القطيف",
        "dropoff_name": "شارع الأمير محمد بن فهد 9369. الدمام",
        "price": "40.54 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_212",  # IMG_2150.JPG
        "request_time": time(12, 3),
        "pickup_lat": 26.4075,
        "pickup_lon": 50.0795,
        "pickup_name": "شارع 613. الدمام",
        "dropoff_name": "شارع 9 ب 6420. الدمام",
        "price": "14.82 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_213",  # IMG_2151.JPG
        "request_time": time(17, 9),
        "pickup_lat": 26.4270,
        "pickup_lon": 50.0713,
        "pickup_name": "Dammam",
        "dropoff_name": "شارع 1 7175, الدمام",
        "price": "32.42 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_214",  # IMG_2152.JPG
        "request_time": time(6, 36),
        "pickup_lat": 26.3972,
        "pickup_lon": 50.0981,
        "pickup_name": "شارع محمد بن الحنفية 7011. الدمام",
        "dropoff_name": "طريق الأمير سلطان بن عبد العزيز 2964. الخبر",
        "price": "54.83 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_215",  # IMG_2153.JPG
        "request_time": time(12, 26),
        "pickup_lat": 26.3982,
        "pickup_lon": 50.0785,
        "pickup_name": "شارع 7 ب 7112. الدمام",
        "dropoff_name": "شارع الأزد 2881. سيهات",
        "price": "25.84 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_216",  # IMG_2154.JPG
        "request_time": time(14, 33),
        "pickup_lat": 26.5624,
        "pickup_lon": 50.0266,
        "pickup_name": "شارع البناء 7884. القطيف",
        "dropoff_name": "طريق الملك فيصل بن عبدالعزيز. الخبر",
        "price": "46.80 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_217",  # IMG_2155.JPG
        "request_time": time(12, 36),
        "pickup_lat": 26.4097,
        "pickup_lon": 50.1006,
        "pickup_name": "شارع 2 الفردوس 8462. الدمام",
        "dropoff_name": "شارع 673535. القطيف",
        "price": "37.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_218",  # IMG_2156.JPG
        "request_time": time(4, 31),
        "pickup_lat": 26.4237,
        "pickup_lon": 50.0853,
        "pickup_name": "شارع يوسف بن النحوي 4482. الدمام",
        "dropoff_name": "شارع 652516. القطيف",
        "price": "21.10 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_219",  # IMG_2157.JPG
        "request_time": time(4, 31),
        "pickup_lat": 26.4204,
        "pickup_lon": 50.0686,
        "pickup_name": "شارع ابن معصوم المدني 6702. الدمام",
        "dropoff_name": "شارع الأمام علي بن ابي طالب 8449. الدمام",
        "price": "29.79 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_220",  # IMG_2158.JPG
        "request_time": time(11, 44),
        "pickup_lat": 26.3041,
        "pickup_lon": 50.2003,
        "pickup_name": "طريق الأمير فيصل بن فهد 6864. الظهران",
        "dropoff_name": "شارع ربيعة بن قيس 3795. الدمام",
        "price": "23.28 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_221",  # IMG_2159.JPG
        "request_time": time(11, 44),
        "pickup_lat": 26.5777,
        "pickup_lon": 50.0309,
        "pickup_name": "شارع النعمان بن ثابت 4564. القطيف",
        "dropoff_name": "شارع البديع 4027. القطيف",
        "price": "18.45 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_222",  # IMG_2160.JPG
        "request_time": time(11, 44),
        "pickup_lat": 26.5628,
        "pickup_lon": 50.0275,
        "pickup_name": "طريق أحد 4450. القطيف",
        "dropoff_name": "شارع 844826. الدمام",
        "price": "34.76 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_223",  # IMG_2161.JPG
        "request_time": time(12, 12),
        "pickup_lat": 26.2884,
        "pickup_lon": 50.2263,
        "pickup_name": "شارع محب الدين السعدي 6951. الخبر",
        "dropoff_name": "605. الدمام",
        "price": "53.52 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_224",  # IMG_2162.JPG
        "request_time": time(12, 12),
        "pickup_lat": 26.5614,
        "pickup_lon": 50.0256,
        "pickup_name": "شارع العاصفة 3432. القطيف",
        "dropoff_name": "الشارع الثامن عشر 7063. الدمام",
        "price": "54.51 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_225",  # IMG_2163.JPG
        "request_time": time(9, 0),
        "pickup_lat": 26.5417,
        "pickup_lon": 49.9851,
        "pickup_name": "طريق الملك فيصل بن عبد العزيز القطيف",
        "dropoff_name": "شارع الاعتدال 2308 القطيف",
        "price": "23.59 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_226",  # IMG_2164.JPG
        "request_time": time(13, 48),
        "pickup_lat": 26.2824,
        "pickup_lon": 50.2238,
        "pickup_name": "شارع مكة المكرمة 2512. الخبر",
        "dropoff_name": "شارع سهل بن عتيك 3530. القطيف",
        "price": "51.25 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_227",  # IMG_2165.JPG
        "request_time": time(15, 1),
        "pickup_lat": 26.4126,
        "pickup_lon": 50.0887,
        "pickup_name": "طريق الملك فهد بن عبد العزيز 6371. الخبر",
        "dropoff_name": "شارع 73875. الدمام",
        "price": "61.70 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_228",  # IMG_2166.JPG
        "request_time": time(15, 11),
        "pickup_lat": 26.2834,
        "pickup_lon": 50.2141,
        "pickup_name": "شارع 333313. الخبر",
        "dropoff_name": "شارع 20 3857. القطيف",
        "price": "54.51 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_229",  # IMG_2167.JPG
        "request_time": time(6, 57),
        "pickup_lat": 26.2792,
        "pickup_lon": 50.1558,
        "pickup_name": "شارع الثامن عشر 7576. الظهران",
        "dropoff_name": "شارع الخندق 4629. الخبر",
        "price": "27.12 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_230",  # IMG_2168.JPG
        "request_time": time(6, 57),
        "pickup_lat": 26.5619,
        "pickup_lon": 50.0183,
        "pickup_name": "الفلاح 3801. القطيف",
        "dropoff_name": "شارع خلف بن تميم 2770. الدمام",
        "price": "37.00 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_231",  # IMG_2169.JPG
        "request_time": time(6, 57),
        "pickup_lat": 26.5894,
        "pickup_lon": 49.9999,
        "pickup_name": "شارع حمزة بن عبد المطلب 6245. القطيف",
        "dropoff_name": "طريق ابن هشام الدمام",
        "price": "33.45 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_232",  # IMG_2170.JPG
        "request_time": time(1, 44),
        "pickup_lat": 26.4054,
        "pickup_lon": 50.0960,
        "pickup_name": "شارع النصر 8499. الدمام",
        "dropoff_name": "شارع عبد الغني الحجار 6727. القطيف",
        "price": "35.36 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_233",  # IMG_2171.JPG
        "request_time": time(2, 2),
        "pickup_lat": 26.5759,
        "pickup_lon": 50.0044,
        "pickup_name": "الولاء 2589. القطيف",
        "dropoff_name": "شارع 16 6953. الدمام",
        "price": "45.34 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_234",  # IMG_2172.JPG
        "request_time": time(11, 55),
        "pickup_lat": 26.5774,
        "pickup_lon": 49.9861,
        "pickup_name": "شارع الفضل اليزيدي 3654. القطيف",
        "dropoff_name": "شارع 875347. الدمام",
        "price": "46.19 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_235",  # IMG_2173.JPG
        "request_time": time(6, 19),
        "pickup_lat": 26.2824,
        "pickup_lon": 50.2328,
        "pickup_name": "شارع تيماء 3188. الخبر",
        "dropoff_name": "شارع 334611. الخبر",
        "price": "20.89 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_236",  # IMG_2174.JPG
        "request_time": time(6, 19),
        "pickup_lat": 26.5619,
        "pickup_lon": 50.0183,
        "pickup_name": "الفلاح 3801. القطيف",
        "dropoff_name": "شارع خلف بن تميم 2770. الدمام",
        "price": "38.62 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_237",  # IMG_2175.JPG
        "request_time": time(12, 2),
        "pickup_lat": 26.3017,
        "pickup_lon": 50.1360,
        "pickup_name": "شارع 733491. الظهران",
        "dropoff_name": "2927 Khaleej Rd. As Salam. Dammam",
        "price": "41.25 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_238",  # IMG_2176.JPG
        "request_time": time(4, 32),
        "pickup_lat": 26.2579,
        "pickup_lon": 50.1896,
        "pickup_name": "6189617. الخبر",
        "dropoff_name": "شارع الأزدهار 3445. الدمام",
        "price": "45.21 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_239",  # IMG_2177.JPG
        "request_time": time(4, 34),
        "pickup_lat": 26.2982,
        "pickup_lon": 50.2171,
        "pickup_name": "شارع الأمير تركي بن عبدالعزيز 6311. الخبر",
        "dropoff_name": "شارع أوس بن ثابت 6554. الظهران",
        "price": "20.28 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_240",  # IMG_2178.JPG
        "request_time": time(5, 39),
        "pickup_lat": 26.4010,
        "pickup_lon": 50.0750,
        "pickup_name": "شارع شعيب العبدي 2969. الدمام",
        "dropoff_name": "شارع إسحاق الشيباني 2470. الدمام",
        "price": "26.10 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_241",  # IMG_2179.JPG
        "request_time": time(16, 23),
        "pickup_lat": 26.4129,
        "pickup_lon": 50.0705,
        "pickup_name": "شارع 19 7185. الدمام",
        "dropoff_name": "شارع الملك خالد بن عبد العزيز 8301. الخبر",
        "price": "41.64 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_242",  # IMG_2180.JPG
        "request_time": time(7, 58),
        "pickup_lat": 26.5859,
        "pickup_lon": 50.0196,
        "pickup_name": "7192. القطيف شارع حجر بن عدي",
        "dropoff_name": "شارع خالد ابن الوليد 3834. الدمام",
        "price": "52.80 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_243",  # IMG_2181.JPG
        "request_time": time(7, 58),
        "pickup_lat": 26.4407,
        "pickup_lon": 50.0806,
        "pickup_name": "605. الدمام",
        "dropoff_name": "شارع أبو إسحاق الأبناسي 3797. الدمام",
        "price": "46.31 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_244",  # IMG_2182.JPG
        "request_time": time(13, 1),
        "pickup_lat": 26.4189,
        "pickup_lon": 50.0791,
        "pickup_name": "طريق الملك فهد بن عبد العزيز 6245. الخبر",
        "dropoff_name": "شارع علي الأنصاري 4880. القطيف",
        "price": "56.85 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_245",  # IMG_2183.JPG
        "request_time": time(18, 2),
        "pickup_lat": 26.4157,
        "pickup_lon": 50.0683,
        "pickup_name": "الدمام",
        "dropoff_name": "شارع العواصم 3411. الدمام",
        "price": "64.39 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_246",  # IMG_2184.JPG
        "request_time": time(18, 2),
        "pickup_lat": 26.5724,
        "pickup_lon": 50.0251,
        "pickup_name": "شارع رباح ابن المعترف 5618. القطيف",
        "dropoff_name": "شارع ابراهيم بن قيس 6524. القطيف",
        "price": "33.58 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_247",  # IMG_2185.JPG
        "request_time": time(6, 20),
        "pickup_lat": 26.4200,
        "pickup_lon": 50.0908,
        "pickup_name": "12هـ 7607. الدمام",
        "dropoff_name": "طريق الملك فيصل بن عبد العزيز القطيف",
        "price": "28.59 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_248",  # IMG_2186.JPG
        "request_time": time(7, 19),
        "pickup_lat": 26.5531,
        "pickup_lon": 50.0221,
        "pickup_name": "775329. القطيف",
        "dropoff_name": "شارع 19ج 7209. الدمام",
        "price": "47.57 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_249",  # IMG_2187.JPG
        "request_time": time(7, 19),
        "pickup_lat": 26.4345,
        "pickup_lon": 50.0813,
        "pickup_name": "شارع الأنشاء 2371. الدمام",
        "dropoff_name": "شارع كعب بن جمار 3469 الدمام",
        "price": "34.83 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_250",  # IMG_2188.JPG
        "request_time": time(7, 19),
        "pickup_lat": 26.5782,
        "pickup_lon": 50.0299,
        "pickup_name": "جبر الكندي 4517. القطيف",
        "dropoff_name": "شارع ابواقد النميري 4379. الدمام",
        "price": "47.23 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_251",  # IMG_2189.JPG
        "request_time": time(0, 47),
        "pickup_lat": 26.4172,
        "pickup_lon": 50.0940,
        "pickup_name": "شارع حمد الحقيل 2886. الدمام",
        "dropoff_name": "شارع ابن فارس 4560. الدمام",
        "price": "24.43 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_252",  # IMG_2190.JPG
        "request_time": time(0, 47),
        "pickup_lat": 26.4840,
        "pickup_lon": 50.0440,
        "pickup_name": "شارع الأزد 2881. سيهات",
        "dropoff_name": "شارع 7 ب 7130 الدمام",
        "price": "29.64 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_253",  # IMG_2191.JPG
        "request_time": time(17, 25),
        "pickup_lat": 26.4144,
        "pickup_lon": 50.1073,
        "pickup_name": "شارع 144 9334. الدمام",
        "dropoff_name": "شارع 669393. الدمام",
        "price": "44.35 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_254",  # IMG_2192.JPG
        "request_time": time(6, 47),
        "pickup_lat": 26.4109,
        "pickup_lon": 50.0698,
        "pickup_name": "شارع سليم اللبيثي 4055. الدمام",
        "dropoff_name": "شارع الأمير تركي بن عبدالعزيز. الخبر",
        "price": "51.06 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_255",  # IMG_2193.JPG
        "request_time": time(9, 49),
        "pickup_lat": 26.2806,
        "pickup_lon": 50.2213,
        "pickup_name": "شارع الأمير طلال بن عبد العزيز 8067. الخبر",
        "dropoff_name": "الشارع العاشر 3597. الخبر",
        "price": "41.79 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_256",  # IMG_2194.JPG
        "request_time": time(9, 49),
        "pickup_lat": 26.4432,
        "pickup_lon": 50.0868,
        "pickup_name": "Nakheel Mall. Dammam ة",
        "dropoff_name": "شارع الابكين 6475. القطيف",
        "price": "36.53 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_257",  # IMG_2196.JPG
        "request_time": time(21, 57),
        "pickup_lat": 26.2674,
        "pickup_lon": 50.2035,
        "pickup_name": "الراشد مول الخبر",
        "dropoff_name": "Google",
        "price": "38.58 ر.س",
        "service_type": "Comfort",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_258",  # IMG_2198.JPG
        "request_time": time(16, 30),
        "pickup_lat": 26.5789,
        "pickup_lon": 49.9951,
        "pickup_name": "شارع أحد 3350. القطيف",
        "dropoff_name": "11ب 7857. الدمام",
        "price": "55.84 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_259",  # IMG_2199.JPG
        "request_time": time(17, 3),
        "pickup_lat": 26.5439,
        "pickup_lon": 49.9856,
        "pickup_name": "شارع 31019. القطيف",
        "dropoff_name": "طريق 7390103. الدمام",
        "price": "75.55 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_260",  # IMG_2200.JPG
        "request_time": time(17, 5),
        "pickup_lat": 26.5674,
        "pickup_lon": 50.0111,
        "pickup_name": "شارع 31019. القطيف",
        "dropoff_name": "طريق الملك عبد العزيز 4054. الدمام",
        "price": "76.35 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_261",  # IMG_2201.JPG
        "request_time": time(7, 37),
        "pickup_lat": 26.5514,
        "pickup_lon": 50.0231,
        "pickup_name": "شارع المركب 8375. القطيف",
        "dropoff_name": "طريق قطب الدين الشافعي. الدمام",
        "price": "53.03 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_262",  # IMG_2202.JPG
        "request_time": time(14, 25),
        "pickup_lat": 26.4357,
        "pickup_lon": 50.0993,
        "pickup_name": "شارع داوود بن عمر 2570. الدمام",
        "dropoff_name": "شارع 1 ب 7196. الدمام",
        "price": "24.52 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_263",  # IMG_2203.JPG
        "request_time": time(6, 2),
        "pickup_lat": 26.5734,
        "pickup_lon": 49.9977,
        "pickup_name": "شارع سلمة الهذلي 4653. القطيف",
        "dropoff_name": "الهديل 4462. القطيف",
        "price": "18.25 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_264",  # IMG_2204.JPG
        "request_time": time(8, 41),
        "pickup_lat": 26.5574,
        "pickup_lon": 50.0316,
        "pickup_name": "شارع فضل ابن سهل 4808. القطيف",
        "dropoff_name": "شارع الأمير فواز بن عبد العزيز 7711. الخبر",
        "price": "62.70 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_265",  # IMG_2205.JPG
        "request_time": time(8, 41),
        "pickup_lat": 21.5243,
        "pickup_lon": 39.1918,
        "pickup_name": "شارع عبد الجبار الحصري 9027. جدة",
        "dropoff_name": "شارع محمد الرميح 4046. جدة",
        "price": "35.44 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_266",  # IMG_2206.JPG
        "request_time": time(6, 55),
        "pickup_lat": 26.4157,
        "pickup_lon": 50.0683,
        "pickup_name": "الدمام",
        "dropoff_name": "الدمام",
        "price": "64.40 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_267",  # IMG_2207.JPG
        "request_time": time(7, 5),
        "pickup_lat": 26.5472,
        "pickup_lon": 50.0321,
        "pickup_name": "شارع الرياض 5162. القطيف",
        "dropoff_name": "طريق الثامن والعشرون 3814. الدمام",
        "price": "39.01 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_268",  # IMG_2208.JPG
        "request_time": time(7, 5),
        "pickup_lat": 26.4124,
        "pickup_lon": 50.1015,
        "pickup_name": "شارع أوس بن الحدثان 2754. الدمام",
        "dropoff_name": "شارع الاصيل 3623. الدمام",
        "price": "19.37 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_269",  # IMG_2209.JPG
        "request_time": time(7, 5),
        "pickup_lat": 26.5784,
        "pickup_lon": 49.9904,
        "pickup_name": "شارع 665922. القطيف",
        "dropoff_name": "شارع الملك عبد العزيز 4614. الدمام",
        "price": "36.09 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_270",  # IMG_2210.JPG
        "request_time": time(18, 36),
        "pickup_lat": 26.4015,
        "pickup_lon": 50.0861,
        "pickup_name": "شارع المنتزه 4066. الدمام",
        "dropoff_name": "شارع 876211. الدمام",
        "price": "24.76 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_271",  # IMG_2211.JPG
        "request_time": time(11, 51),
        "pickup_lat": 26.5849,
        "pickup_lon": 50.0246,
        "pickup_name": "شارع ابن النفيس 2943. القطيف",
        "dropoff_name": "42301. الدمام",
        "price": "52.25 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_272",  # IMG_2212.JPG
        "request_time": time(19, 13),
        "pickup_lat": 26.4102,
        "pickup_lon": 50.1135,
        "pickup_name": "1 4230, الدمام",
        "dropoff_name": "شارع امين المحبي 4848, الدمام",
        "price": "35.82 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_273",  # IMG_2223.JPG
        "request_time": time(19, 13),
        "pickup_lat": 26.4133,
        "pickup_lon": 50.0560,
        "pickup_name": "شارع أمير المؤمنين عمر بن الخطاب. الدمام",
        "dropoff_name": "شارع كعب بن مالك 7977. الجبيل",
        "price": "51.53 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_274",  # IMG_2224.JPG
        "request_time": time(13, 51),
        "pickup_lat": 26.4305,
        "pickup_lon": 50.0693,
        "pickup_name": "شارع زيد بن حارثة 3813, الدمام",
        "dropoff_name": "1 4230, الدمام",
        "price": "26.98 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_275",  # IMG_2225.JPG
        "request_time": time(13, 51),
        "pickup_lat": 26.2746,
        "pickup_lon": 50.2168,
        "pickup_name": "شارع الرابع 4778 الخبر",
        "dropoff_name": "شارع السكينة 4340. الدمام",
        "price": "29.88 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_276",  # IMG_2226.JPG
        "request_time": time(13, 51),
        "pickup_lat": 26.4147,
        "pickup_lon": 50.1018,
        "pickup_name": "42301. الدمام",
        "dropoff_name": "شارع الصدفة 67201. القطيف",
        "price": "49.93 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_277",  # IMG_2227.JPG
        "request_time": time(11, 38),
        "pickup_lat": 26.2969,
        "pickup_lon": 50.2206,
        "pickup_name": "شارع 273914. الخبر",
        "dropoff_name": "شارع اليمن 4382. الجبيل الصناعية",
        "price": "109.84 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_278",  # IMG_2228.JPG
        "request_time": time(11, 38),
        "pickup_lat": 26.2824,
        "pickup_lon": 50.2225,
        "pickup_name": "شارع 273914. الخبر",
        "dropoff_name": "شارع اليمن 4382. الجبيل الصناعية",
        "price": "109.84 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_279",  # IMG_2229.JPG
        "request_time": time(7, 57),
        "pickup_lat": 26.4252,
        "pickup_lon": 50.0813,
        "pickup_name": "شارع 6 ج 7974. الدمام",
        "dropoff_name": "شارع الأمير حمود بن عبد العزيز. الخبر",
        "price": "45.31 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_280",  # IMG_2230.JPG
        "request_time": time(7, 57),
        "pickup_lat": 26.4816,
        "pickup_lon": 50.0459,
        "pickup_name": "الورد 3132. سيهات",
        "dropoff_name": "جنادة الازدي 2936. سيهات",
        "price": "24.24 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_281",  # IMG_2231.JPG
        "request_time": time(3, 45),
        "pickup_lat": 26.2844,
        "pickup_lon": 50.1395,
        "pickup_name": "الظهران",
        "dropoff_name": "شارع الصابوني 3602, الدمام",
        "price": "41.14 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_282",  # IMG_2232.JPG
        "request_time": time(3, 45),
        "pickup_lat": 26.4352,
        "pickup_lon": 50.0925,
        "pickup_name": "طريق 1. الدمام",
        "dropoff_name": "شارع علي الأنصاري 4776. القطيف",
        "price": "46.24 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_283",  # IMG_2233.JPG
        "request_time": time(4, 21),
        "pickup_lat": 26.4447,
        "pickup_lon": 50.0966,
        "pickup_name": "طريق الثامن عشر 7832. الدمام",
        "dropoff_name": "شارع الحمراء 7814470. الجبيل",
        "price": "93.74 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_284",  # IMG_2234.JPG
        "request_time": time(4, 21),
        "pickup_lat": 26.2579,
        "pickup_lon": 50.1921,
        "pickup_name": "شارع 282326. الخبر",
        "dropoff_name": "شارع سعيد بن مبارك 3214. الدمام",
        "price": "49.35 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_285",  # IMG_2235.JPG
        "request_time": time(7, 26),
        "pickup_lat": 26.3006,
        "pickup_lon": 50.2120,
        "pickup_name": "شارع قدامة بن جعفر 7911. الخبر",
        "dropoff_name": "طريق ابو حدرية 95 7627. الدمام",
        "price": "24.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_286",  # IMG_2236.JPG
        "request_time": time(7, 26),
        "pickup_lat": 26.5489,
        "pickup_lon": 49.9964,
        "pickup_name": "شارع النعمان بن عدي ) 4129. القطيف",
        "dropoff_name": "شارع المنتدر. القطيف",
        "price": "23.08 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_287",  # IMG_2237.JPG
        "request_time": time(19, 42),
        "pickup_lat": 26.5649,
        "pickup_lon": 49.9944,
        "pickup_name": "1ب 7321, القطيف",
        "dropoff_name": "4ب 8135, سيهات",
        "price": "20.44 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_288",  # IMG_2238.JPG
        "request_time": time(19, 52),
        "pickup_lat": 26.5711,
        "pickup_lon": 50.0216,
        "pickup_name": "شارع 3 7614, القطيف",
        "dropoff_name": "شارع الاميلح 6546, القطيف",
        "price": "19.56 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_289",  # IMG_2239.JPG
        "request_time": time(13, 51),
        "pickup_lat": 26.2902,
        "pickup_lon": 50.1930,
        "pickup_name": "شارع شبيب بن قرة 6593. الخبر",
        "dropoff_name": "شارع 892032. الدمام",
        "price": "43.00 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_290",  # IMG_2240.JPG
        "request_time": time(8, 34),
        "pickup_lat": 26.5454,
        "pickup_lon": 50.0326,
        "pickup_name": "شارع 41268. القطيف",
        "dropoff_name": "شارع الهيثم بن عدي 3742. القطيف",
        "price": "17.32 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_291",  # IMG_2241.JPG
        "request_time": time(8, 37),
        "pickup_lat": 26.9796,
        "pickup_lon": 49.6553,
        "pickup_name": "طريق الظهران الجبيل السريع 7292. الدمام",
        "dropoff_name": "شارع الأمير بندر بن عبد العزيز 2599. رأس تنورة",
        "price": "36.44 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_292",  # IMG_2242.JPG
        "request_time": time(19, 52),
        "pickup_lat": 26.5711,
        "pickup_lon": 50.0216,
        "pickup_name": "شارع 3 7614, القطيف",
        "dropoff_name": "شارع الاميلح 6546, القطيف",
        "price": "19.56 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_293",  # IMG_2243.JPG
        "request_time": time(19, 52),
        "pickup_lat": 26.4090,
        "pickup_lon": 50.0688,
        "pickup_name": "شارع الغيث 3204, الدمام",
        "dropoff_name": "شارع يبرين 2846, الخبر",
        "price": "35.22 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_294",  # IMG_2244.JPG
        "request_time": time(7, 12),
        "pickup_lat": 26.5866,
        "pickup_lon": 50.0206,
        "pickup_name": "شارع العوافي 5179. القطيف",
        "dropoff_name": "طريق 2771117. الدمام",
        "price": "36.41 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_295",  # IMG_2245.JPG
        "request_time": time(7, 12),
        "pickup_lat": 26.5654,
        "pickup_lon": 50.0009,
        "pickup_name": "الكوثر 3730. القطيف",
        "dropoff_name": "شارع خلف بن تميم 2770. الدمام",
        "price": "29.28 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_296",  # IMG_2246.JPG
        "request_time": time(9, 16),
        "pickup_lat": 26.5829,
        "pickup_lon": 49.9871,
        "pickup_name": "شارع الكتبي 4155. القطيف",
        "dropoff_name": "شارغ عبد الزاق بن همام 7898. الدمام",
        "price": "36.13 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_297",  # IMG_2247.JPG
        "request_time": time(9, 16),
        "pickup_lat": 26.5531,
        "pickup_lon": 49.9992,
        "pickup_name": "شارع الريف 3628. القطيف",
        "dropoff_name": "عبد الرحمن بن عوف 3726. الدمام",
        "price": "50.76 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_298",  # IMG_2248.JPG
        "request_time": time(8, 46),
        "pickup_lat": 26.5614,
        "pickup_lon": 50.0169,
        "pickup_name": "شارع 71567. القطيف",
        "dropoff_name": "شارع 7د 7679. الدمام",
        "price": "42.41 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_299",  # IMG_2249.JPG
        "request_time": time(8, 46),
        "pickup_lat": 26.4057,
        "pickup_lon": 50.0773,
        "pickup_name": "شارع اسماعیل بن اويس 2685. الدمام",
        "dropoff_name": "الجبيل Unnamed Road",
        "price": "87.99 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_300",  # IMG_2250.JPG
        "request_time": time(8, 46),
        "pickup_lat": 26.3997,
        "pickup_lon": 50.0753,
        "pickup_name": "شارع سعيد بن مبارك 3210. الدمام",
        "dropoff_name": "شارع 282326 الخبر",
        "price": "30.90 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_301",  # IMG_2251.JPG
        "request_time": time(2, 45),
        "pickup_lat": 26.3004,
        "pickup_lon": 50.2326,
        "pickup_name": "Al Ulaya. 8 all. Al Khobar",
        "dropoff_name": "طريق حمزة بن عبد المطلب 2753. الدمام",
        "price": "28.62 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_302",  # IMG_2252.JPG
        "request_time": time(4, 23),
        "pickup_lat": 26.4440,
        "pickup_lon": 50.1030,
        "pickup_name": "مجمع الهدي 3236. الدمام",
        "dropoff_name": "شارع حجر ابن عدي 7262. القطيف",
        "price": "38.34 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_303",  # IMG_2253.JPG
        "request_time": time(4, 23),
        "pickup_lat": 26.5628,
        "pickup_lon": 50.0275,
        "pickup_name": "طريق أحد 4450. القطيف",
        "dropoff_name": "شارع 6897101. الدمام",
        "price": "52.38 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_304",  # IMG_2254.JPG
        "request_time": time(4, 23),
        "pickup_lat": 26.5628,
        "pickup_lon": 50.0275,
        "pickup_name": "طريق أحد 4450. القطيف",
        "dropoff_name": "شارع 6897101. الدمام",
        "price": "61.70 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_305",  # IMG_2255.JPG
        "request_time": time(4, 23),
        "pickup_lat": 26.5499,
        "pickup_lon": 50.0130,
        "pickup_name": "شارع عمار بن ياسر 4841. القطيف",
        "dropoff_name": "شارع عبد الله بن الربيع 2208. الدمام",
        "price": "37.98 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_306",  # IMG_2256.JPG
        "request_time": time(4, 23),
        "pickup_lat": 26.5647,
        "pickup_lon": 49.9854,
        "pickup_name": "شارع العزة 5057. القطيف",
        "dropoff_name": "شارع ابو الفضل البيهقي 3434. سيهات",
        "price": "38.51 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_307",  # IMG_2257.JPG
        "request_time": time(4, 23),
        "pickup_lat": 26.5412,
        "pickup_lon": 49.9901,
        "pickup_name": "شارع 79212. القطيف",
        "dropoff_name": "شارع ابن الجوزي 8446. الدمام",
        "price": "36.59 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_308",  # IMG_2258.JPG
        "request_time": time(15, 49),
        "pickup_lat": 26.4200,
        "pickup_lon": 50.0891,
        "pickup_name": "شارع أبو أوس الأسلمي. الدمام",
        "dropoff_name": "شارع أحد 3350. القطيف",
        "price": "27.62 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_309",  # IMG_2259.JPG
        "request_time": time(15, 49),
        "pickup_lat": 26.6563,
        "pickup_lon": 49.9481,
        "pickup_name": "القطيف 7951890. صفوى",
        "dropoff_name": "شارع 1 الخبر",
        "price": "56.06 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_310",  # IMG_2260.JPG
        "request_time": time(15, 49),
        "pickup_lat": 26.6387,
        "pickup_lon": 49.9643,
        "pickup_name": "ابن ارسلان 6862. صفوی",
        "dropoff_name": "شارع 1 الخبر",
        "price": "2.28 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_311",  # IMG_2261.JPG
        "request_time": time(15, 49),
        "pickup_lat": 26.6387,
        "pickup_lon": 49.9643,
        "pickup_name": "ابن ارسلان 6862. صفوی",
        "dropoff_name": "شارع 1 الخبر",
        "price": "44.95 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_312",  # IMG_2262.JPG
        "request_time": time(8, 14),
        "pickup_lat": 26.4249,
        "pickup_lon": 50.0795,
        "pickup_name": "شارع النابغة الجعدي 2978. الدمام",
        "dropoff_name": "شارع الاعتماد 2479. القطيف",
        "price": "29.96 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_313",  # IMG_2263.JPG
        "request_time": time(18, 59),
        "pickup_lat": 26.4417,
        "pickup_lon": 50.1170,
        "pickup_name": "طريق الملك عبد الله 8248. الأحساء",
        "dropoff_name": "شارع سليمان الانصاري 7904. الأحساء",
        "price": "30.99 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_314",  # IMG_2264.JPG
        "request_time": time(18, 59),
        "pickup_lat": 26.4347,
        "pickup_lon": 50.1131,
        "pickup_name": "Al Saybaniu Street 4668, Dammam",
        "dropoff_name": "Sultan Square Khobar, الخبر",
        "price": "23.01 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_315",  # IMG_2265.JPG
        "request_time": time(18, 33),
        "pickup_lat": 26.3963,
        "pickup_lon": 50.0880,
        "pickup_name": "شارع الفردوس 4376. الدمام",
        "dropoff_name": "شارع الامير محمد بن نايف بن عبد العزيز 2994 الخبر",
        "price": "38.72 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_316",  # IMG_2266.JPG
        "request_time": time(18, 33),
        "pickup_lat": 26.3552,
        "pickup_lon": 50.1883,
        "pickup_name": "غرناطة 6417. الخبر",
        "dropoff_name": "شارع 17 7518. الدمام",
        "price": "29.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_317",  # IMG_2267.JPG
        "request_time": time(3, 52),
        "pickup_lat": 26.5836,
        "pickup_lon": 50.0019,
        "pickup_name": "شارع الطبيعة 3303. القطيف",
        "dropoff_name": "طريق أحد 4867. القطيف",
        "price": "19.52 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_318",  # IMG_2268.JPG
        "request_time": time(4, 14),
        "pickup_lat": 26.4075,
        "pickup_lon": 50.0795,
        "pickup_name": "شارع 613. الدمام",
        "dropoff_name": "شارع 6340308. الجبيل",
        "price": "56.93 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_319",  # IMG_2269.JPG
        "request_time": time(12, 9),
        "pickup_lat": 26.2996,
        "pickup_lon": 50.2148,
        "pickup_name": "عبد الله بن ذهلان 3243. الخبر",
        "dropoff_name": "شارع الحسين بن عرفطة 7467. الخبر",
        "price": "12.17 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_320",  # IMG_2270.JPG
        "request_time": time(1, 0),
        "pickup_lat": 26.3031,
        "pickup_lon": 50.2005,
        "pickup_name": "شارع 1 3274, الخبر",
        "dropoff_name": "شارع مكة المكرمة 8180, سيهات",
        "price": "24.11 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_321",  # IMG_2271.JPG
        "request_time": time(1, 0),
        "pickup_lat": 26.4389,
        "pickup_lon": 50.0673,
        "pickup_name": "شارع ابن الورد 3242. الدمام",
        "dropoff_name": "شارع الملك سعود بن عبد العزيز. الدمام",
        "price": "20.91 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_322",  # IMG_2272.JPG
        "request_time": time(1, 0),
        "pickup_lat": 26.3021,
        "pickup_lon": 50.1930,
        "pickup_name": "شارع 31026. الخبر",
        "dropoff_name": "طريق الأمام علي بن ابي طالب 6797. الدمام",
        "price": "34.64 ر.س",
        "service_type": "Comfort حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_323",  # IMG_2273.JPG
        "request_time": time(1, 0),
        "pickup_lat": 26.3980,
        "pickup_lon": 50.0968,
        "pickup_name": "Dammam Saudi Arabia. Dammam",
        "dropoff_name": "شارع الأمير منصور بن عبد العزيز 8136. الخبر",
        "price": "36.70 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_324",  # IMG_2274.JPG
        "request_time": time(1, 0),
        "pickup_lat": 26.3980,
        "pickup_lon": 50.0968,
        "pickup_name": "Dammam Saudi Arabia. Dammam",
        "dropoff_name": "شارع الأمير منصور بن عبد العزيز 8136. الخبر",
        "price": "26.50 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_325",  # IMG_2275.JPG
        "request_time": time(11, 7),
        "pickup_lat": 26.4240,
        "pickup_lon": 50.0846,
        "pickup_name": "ابو حامد الغزالي. الدمام",
        "dropoff_name": "شارع 282326. الخبر",
        "price": "35.81 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_326",  # IMG_2276.JPG
        "request_time": time(11, 7),
        "pickup_lat": 26.2951,
        "pickup_lon": 50.2058,
        "pickup_name": "شارع ربيعة بن السكن 6748. الخبر",
        "dropoff_name": "س اشبيليه 116 الفرعي 3296. الجبيل",
        "price": "98.55 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_327",  # IMG_2277.JPG
        "request_time": time(11, 19),
        "pickup_lat": 26.4034,
        "pickup_lon": 50.0906,
        "pickup_name": "10 7961. الدمام المسافة 470 كلين",
        "dropoff_name": "شارع عبد الرحمن ابن كعب الانصاري 8192. الخبر",
        "price": "31.39 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_328",  # IMG_2278.JPG
        "request_time": time(11, 19),
        "pickup_lat": 26.3036,
        "pickup_lon": 50.2261,
        "pickup_name": "شارع 1ب 2750. الخبر",
        "dropoff_name": "شارع اسحاق بن طليق 4272 الدمام",
        "price": "65.30 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_329",  # IMG_2279.JPG
        "request_time": time(11, 4),
        "pickup_lat": 26.5729,
        "pickup_lon": 50.0009,
        "pickup_name": "شارع ايمن بن عبيد 3571. القطيف",
        "dropoff_name": "طريق الخليج 3544. الدمام",
        "price": "28.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_330",  # IMG_2280.JPG
        "request_time": time(13, 15),
        "pickup_lat": 26.5662,
        "pickup_lon": 49.9921,
        "pickup_name": "شارع 14 8162, القطيف",
        "dropoff_name": "605, الدمام",
        "price": "28.42 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_331",  # IMG_2281.JPG
        "request_time": time(4, 21),
        "pickup_lat": 26.3985,
        "pickup_lon": 50.1135,
        "pickup_name": "شارع الفضل الطبري 7279. الدمام",
        "dropoff_name": "طريق القدس 3699. الجبيل الصناعية",
        "price": "84.71 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_332",  # IMG_2282.JPG
        "request_time": time(4, 21),
        "pickup_lat": 26.4032,
        "pickup_lon": 50.0710,
        "pickup_name": "شارع الفيروز 2993. الدمام",
        "dropoff_name": "شارع 3656907. الجبيل",
        "price": "49.76 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_333",  # IMG_2283.JPG
        "request_time": time(4, 21),
        "pickup_lat": 26.4315,
        "pickup_lon": 50.0783,
        "pickup_name": "شارع ينبع 7918. الدمام",
        "dropoff_name": "شارع 7529470. القطيف",
        "price": "44.54 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_334",  # IMG_2284.JPG
        "request_time": time(4, 9),
        "pickup_lat": 26.4090,
        "pickup_lon": 50.0985,
        "pickup_name": "الشارع الثامن عشر 6929. الدمام",
        "dropoff_name": "شارع جلال السيوطي 5247. الدمام",
        "price": "12.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_335",  # IMG_2285.JPG
        "request_time": time(4, 18),
        "pickup_lat": 26.4404,
        "pickup_lon": 50.1018,
        "pickup_name": "شارع 4617117. الدمام",
        "dropoff_name": "طريق أحد 3618. القطيف",
        "price": "41.31 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_336",  # IMG_2286.JPG
        "request_time": time(4, 43),
        "pickup_lat": 26.4090,
        "pickup_lon": 50.0716,
        "pickup_name": "شارع الإمام محمد بن سعود 4088. الدمام",
        "dropoff_name": "شارع عبد الجليل القرطبي. الدمام",
        "price": "21.68 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_337",  # IMG_2287.JPG
        "request_time": time(4, 43),
        "pickup_lat": 26.5680,
        "pickup_lon": 50.0094,
        "pickup_name": "المروءة 2739. القطيف",
        "dropoff_name": "شارع الحادي عشرة 7125. الدمام",
        "price": "34.32 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_338",  # IMG_2288.JPG
        "request_time": time(10, 29),
        "pickup_lat": 26.5669,
        "pickup_lon": 49.9871,
        "pickup_name": "شارع 668712. القطيف",
        "dropoff_name": "شارع الخندق 4629. الخبر",
        "price": "61.70 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_339",  # IMG_2289.JPG
        "request_time": time(4, 28),
        "pickup_lat": 26.5629,
        "pickup_lon": 49.9969,
        "pickup_name": "شارع احمد بن صفوان 3807. القطيف",
        "dropoff_name": "Omar Ibn Al Khattab St. Dammam",
        "price": "40.12 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_340",  # IMG_2290.JPG
        "request_time": time(4, 26),
        "pickup_lat": 26.5779,
        "pickup_lon": 50.0044,
        "pickup_name": "شارع 8162100. القطيف",
        "dropoff_name": "شارع الرياض 3403. القطيف",
        "price": "16.52 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_341",  # IMG_2291.JPG
        "request_time": time(16, 8),
        "pickup_lat": 26.3083,
        "pickup_lon": 50.2035,
        "pickup_name": "طريق الأمير فيصل بن فهد 6864. الظهران",
        "dropoff_name": "شارع بلال بن رباح. القطيف",
        "price": "49.14 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_342",  # IMG_2292.JPG
        "request_time": time(6, 17),
        "pickup_lat": 26.4390,
        "pickup_lon": 50.1113,
        "pickup_name": "طريق الملك عبد الله بن عبد العزيز. الخبر",
        "dropoff_name": "شارع المجمعه 7615. الخبر",
        "price": "17.10 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_343",  # IMG_2293.JPG
        "request_time": time(17, 1),
        "pickup_lat": 26.5767,
        "pickup_lon": 50.0652,
        "pickup_name": "شارع تاروت 3638509. القطيف",
        "dropoff_name": "مجمع الهدي 3236. الدمام",
        "price": "44.87 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_344",  # IMG_2294.JPG
        "request_time": time(7, 1),
        "pickup_lat": 26.5499,
        "pickup_lon": 50.0130,
        "pickup_name": "شارع عمار بن ياسر 4841. القطيف",
        "dropoff_name": "شارع عبدالله بن الربيع 2208 الدمام",
        "price": "34.08 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_345",  # IMG_2295.JPG
        "request_time": time(8, 47),
        "pickup_lat": 26.4225,
        "pickup_lon": 50.1125,
        "pickup_name": "شارع الدرداء 2996. الدمام",
        "dropoff_name": "الشارع الشرقي 7722. الخبر",
        "price": "39.13 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_346",  # IMG_2296.JPG
        "request_time": time(13, 55),
        "pickup_lat": 26.2881,
        "pickup_lon": 50.2193,
        "pickup_name": "الملك فيصل ابن عبد العزيز سعود 7863. الخبر",
        "dropoff_name": "شارع النعمان بن بشير 4045. القطيف",
        "price": "43.19 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_347",  # IMG_2297.JPG
        "request_time": time(7, 40),
        "pickup_lat": 26.5449,
        "pickup_lon": 50.0011,
        "pickup_name": "شارع صالح الزايدي 3491. القطيف",
        "dropoff_name": "شارع بلال بن رباح 3237. الدمام",
        "price": "29.03 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_348",  # IMG_2298.JPG
        "request_time": time(19, 48),
        "pickup_lat": 26.4157,
        "pickup_lon": 50.0683,
        "pickup_name": "الدمام",
        "dropoff_name": "613, الجبيل",
        "price": "68.22 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_349",  # IMG_2299.JPG
        "request_time": time(19, 48),
        "pickup_lat": 26.4227,
        "pickup_lon": 50.0921,
        "pickup_name": "شارع ابوخلاد الأنصاري 4078. الدمام",
        "dropoff_name": "Dammam",
        "price": "29.36 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_350",  # IMG_2300.JPG
        "request_time": time(5, 27),
        "pickup_lat": 26.2867,
        "pickup_lon": 50.1446,
        "pickup_name": "شارع رابغ 3580. الظهران",
        "dropoff_name": "طريق أحد 3557. القطيف",
        "price": "46.29 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_351",  # IMG_2301.JPG
        "request_time": time(7, 7),
        "pickup_lat": 26.5884,
        "pickup_lon": 50.0141,
        "pickup_name": "شارع علي الأنصاري 4776. القطيف",
        "dropoff_name": "طريق 1. الدمام",
        "price": "60.81 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_352",  # IMG_2302.JPG
        "request_time": time(7, 7),
        "pickup_lat": 26.5884,
        "pickup_lon": 50.0141,
        "pickup_name": "شارع علي الأنصاري 4776. القطيف",
        "dropoff_name": "طريق 1. الدمام",
        "price": "61.69 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_353",  # IMG_2303.JPG
        "request_time": time(7, 8),
        "pickup_lat": 26.5689,
        "pickup_lon": 49.9944,
        "pickup_name": "Ali Al Ansari Street 4776. Al Qatif",
        "dropoff_name": "طريق 1 Dammam",
        "price": "48.29 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_354",  # IMG_2304.JPG
        "request_time": time(10, 41),
        "pickup_lat": 26.4506,
        "pickup_lon": 50.1161,
        "pickup_name": "طريق الخليج 6750, القطيف",
        "dropoff_name": "شارع 25 6684, الدمام",
        "price": "31.83 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_355",  # IMG_2305.JPG
        "request_time": time(10, 41),
        "pickup_lat": 26.3029,
        "pickup_lon": 50.2141,
        "pickup_name": "شارع المبرز الخبر",
        "dropoff_name": "7589114. القطيف",
        "price": "52.40 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_356",  # IMG_2306.JPG
        "request_time": time(4, 48),
        "pickup_lat": 26.3202,
        "pickup_lon": 50.1260,
        "pickup_name": "شارع إبراهيم الدينوري 7244 الظهران",
        "dropoff_name": "شارع الاخلاص 4273. القطيف",
        "price": "51.77 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_357",  # IMG_2307.JPG
        "request_time": time(4, 48),
        "pickup_lat": 26.4536,
        "pickup_lon": 50.1179,
        "pickup_name": "طريق الخليج. الدمام",
        "dropoff_name": "شارع طاهر زمخشري 3059. الدمام",
        "price": "17.84 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_358",  # IMG_2308.JPG
        "request_time": time(15, 18),
        "pickup_lat": 26.4382,
        "pickup_lon": 50.0970,
        "pickup_name": "605, الدمام",
        "dropoff_name": "شارع 17ب 7460, الظهران",
        "price": "44.76 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_359",  # IMG_2309.JPG
        "request_time": time(7, 44),
        "pickup_lat": 26.4157,
        "pickup_lon": 50.0683,
        "pickup_name": "الدمام",
        "dropoff_name": "شارع 24626 الخبر",
        "price": "70.02 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_360",  # IMG_2310.JPG
        "request_time": time(10, 18),
        "pickup_lat": 26.4099,
        "pickup_lon": 50.0750,
        "pickup_name": "Nakheel Mall. Dammam",
        "dropoff_name": "شارع الابكين 6475. القطيف",
        "price": "34.18 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_361",  # IMG_2311.JPG
        "request_time": time(10, 18),
        "pickup_lat": 26.3237,
        "pickup_lon": 50.1628,
        "pickup_name": "شارع 733491. الظهران",
        "dropoff_name": "خالد بن الوليد 7864. القطيف",
        "price": "43.57 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_362",  # IMG_2312.JPG
        "request_time": time(10, 18),
        "pickup_lat": 26.4200,
        "pickup_lon": 50.0683,
        "pickup_name": "شارع ابن زیاد 3834. الدمام",
        "dropoff_name": "شارع الرياض 3602. القطيف",
        "price": "35.46 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_363",  # IMG_2313.JPG
        "request_time": time(10, 18),
        "pickup_lat": 26.4060,
        "pickup_lon": 50.1023,
        "pickup_name": "شارع 31 6305, الدمام",
        "dropoff_name": "شارع 2 6255, الخبر",
        "price": "45.56 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_364",  # IMG_2314.JPG
        "request_time": time(10, 18),
        "pickup_lat": 26.4184,
        "pickup_lon": 50.0888,
        "pickup_name": "شارع اسماعیل بن اويس 2685 الدمام",
        "dropoff_name": "الجبيل.Unnamed Road",
        "price": "85.19 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_365",  # IMG_2315.JPG
        "request_time": time(4, 56),
        "pickup_lat": 26.4407,
        "pickup_lon": 50.0806,
        "pickup_name": "605. الدمام",
        "dropoff_name": "الطريق فردوس 3627. الظهران",
        "price": "61.86 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_366",  # IMG_2316.JPG
        "request_time": time(9, 19),
        "pickup_lat": 26.4150,
        "pickup_lon": 50.0831,
        "pickup_name": "شارع الحرث الطائي 3941. الدمام",
        "dropoff_name": "شارع عبد الزاق بن همام 7796. الدمام",
        "price": "45.63 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_367",  # IMG_2317.JPG
        "request_time": time(7, 2),
        "pickup_lat": 26.4315,
        "pickup_lon": 50.0891,
        "pickup_name": "شارع 120 9066. الدمام",
        "dropoff_name": "شارع 2 7967. الدمام",
        "price": "40.32 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_368",  # IMG_2318.JPG
        "request_time": time(9, 9),
        "pickup_lat": 26.5499,
        "pickup_lon": 50.0130,
        "pickup_name": "شارع عمار بن ياسر 4841. القطيف",
        "dropoff_name": "شارع عبدالله بن الربيع 2208. الدمام",
        "price": "35.81 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_369",  # IMG_2319.JPG
        "request_time": time(12, 25),
        "pickup_lat": 26.3149,
        "pickup_lon": 50.1591,
        "pickup_name": "شارع ابن تيمية 3111. الظهران",
        "dropoff_name": "شارع 15 6930. الظهران",
        "price": "22.54 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_370",  # IMG_2320.JPG
        "request_time": time(4, 46),
        "pickup_lat": 26.4631,
        "pickup_lon": 50.1117,
        "pickup_name": "شارع الامير مساعد بن عبد العزيز 7305. القطيف",
        "dropoff_name": "الحارث التميمي 6543. القطيف",
        "price": "14.09 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_371",  # IMG_2321.JPG
        "request_time": time(4, 46),
        "pickup_lat": 26.4432,
        "pickup_lon": 50.0881,
        "pickup_name": "شارع 26 ب 6320 الدمام",
        "dropoff_name": "شارع الملك سعود بن عبد العزيز الدمام",
        "price": "34.55 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_372",  # IMG_2322.JPG
        "request_time": time(4, 46),
        "pickup_lat": 26.5764,
        "pickup_lon": 49.9864,
        "pickup_name": "شارع 35 6735, القطيف",
        "dropoff_name": "شارع 2 8418, الدمام",
        "price": "54.30 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_373",  # IMG_2323.JPG
        "request_time": time(8, 26),
        "pickup_lat": 26.5839,
        "pickup_lon": 50.0231,
        "pickup_name": "شارع صلاح الدين الصبوري 3755. القطيف",
        "dropoff_name": "219214. القطيف",
        "price": "16.92 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_374",  # IMG_2324.JPG
        "request_time": time(8, 26),
        "pickup_lat": 26.3222,
        "pickup_lon": 50.1303,
        "pickup_name": "شارع 706873. الظهران",
        "dropoff_name": "605. الدمام",
        "price": "68.44 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_375",  # IMG_2325.JPG
        "request_time": time(3, 23),
        "pickup_lat": 26.2767,
        "pickup_lon": 50.2303,
        "pickup_name": "شارع 81058. الخبر",
        "dropoff_name": "طريق الأمير محمد بن فهد 7330. الدمام",
        "price": "29.52 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_376",  # IMG_2326.JPG
        "request_time": time(13, 34),
        "pickup_lat": 26.3022,
        "pickup_lon": 50.1975,
        "pickup_name": "طريق الأمير فيصل بن فهد بن عبدالعزيز. الخبر",
        "dropoff_name": "شارع المعرفة 7586. القطيف",
        "price": "59.70 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_377",  # IMG_2327.JPG
        "request_time": time(13, 34),
        "pickup_lat": 26.4227,
        "pickup_lon": 50.1003,
        "pickup_name": "شارع 1 8878, الدمام",
        "dropoff_name": "605, الدمام",
        "price": "39.96 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_378",  # IMG_2328.JPG
        "request_time": time(14, 11),
        "pickup_lat": 26.3170,
        "pickup_lon": 50.1564,
        "pickup_name": "شارع دومة الجندل 4271. الظهران",
        "dropoff_name": "شارع الجبهاء 6919. الخبر",
        "price": "4.90 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_379",  # IMG_2329.JPG
        "request_time": time(16, 28),
        "pickup_lat": 26.4332,
        "pickup_lon": 50.0823,
        "pickup_name": "شارع 4467605. الدمام",
        "dropoff_name": "شارع الحارث بن الربيع 3910. الدمام",
        "price": "42.86 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_380",  # IMG_2330.JPG
        "request_time": time(1, 11),
        "pickup_lat": 26.4082,
        "pickup_lon": 50.0778,
        "pickup_name": "شارع 712045. الدمام",
        "dropoff_name": "طريق الأمير فيصل بن فهد 6686. الظهران",
        "price": "45.29 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_381",  # IMG_2331.JPG
        "request_time": time(1, 11),
        "pickup_lat": 26.3985,
        "pickup_lon": 50.1060,
        "pickup_name": "شارع 265878. الدمام",
        "dropoff_name": "شارع ابن بطوطة 7840. الظهران",
        "price": "45.48 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_382",  # IMG_2332.JPG
        "request_time": time(12, 31),
        "pickup_lat": 26.3972,
        "pickup_lon": 50.1113,
        "pickup_name": "شارع سهل بن صخر 7461. الدمام",
        "dropoff_name": "شارع 25هـ 4927. الخبر",
        "price": "40.51 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_383",  # IMG_2333.JPG
        "request_time": time(12, 31),
        "pickup_lat": 26.4010,
        "pickup_lon": 50.0780,
        "pickup_name": "شارع عبد الرحمن البزاز 8346. الدمام",
        "dropoff_name": "شارع الأمير تركي بن عبد العزيز 7346. الخبر",
        "price": "55.77 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_384",  # IMG_2334.JPG
        "request_time": time(12, 31),
        "pickup_lat": 26.5632,
        "pickup_lon": 50.0209,
        "pickup_name": "شارع ابن النباشي 4057. القطيف",
        "dropoff_name": "شارع محمد القرطبي 7637. الدمام",
        "price": "37.64 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_385",  # IMG_2335.JPG
        "request_time": time(12, 31),
        "pickup_lat": 25.3725,
        "pickup_lon": 49.5928,
        "pickup_name": "شارع محمد بن عبدالله الكسائي 3597. الأحساء",
        "dropoff_name": "انس بن مالك 2461. المبرز",
        "price": "15.90 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_386",  # IMG_2336.JPG
        "request_time": time(1, 45),
        "pickup_lat": 26.4388,
        "pickup_lon": 50.1069,
        "pickup_name": "طريق الملك عبد الله بن عبد العزيز الخبر",
        "dropoff_name": "605. الدمام",
        "price": "106.12 ر.س",
        "service_type": "UberXL",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_387",  # IMG_2337.JPG
        "request_time": time(13, 37),
        "pickup_lat": 26.4293,
        "pickup_lon": 50.1081,
        "pickup_name": "طريق الأمير محمد بن فهد 8213. الدمام",
        "dropoff_name": "الغرائب 2873. الدمام",
        "price": "42.97 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_388",  # IMG_2338.JPG
        "request_time": time(13, 39),
        "pickup_lat": 26.4412,
        "pickup_lon": 50.0897,
        "pickup_name": "شارع 13 الصفا. الدمام",
        "dropoff_name": "شارع داود القزاز 3469 القطيف",
        "price": "55.63 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_389",  # IMG_2339.JPG
        "request_time": time(1, 44),
        "pickup_lat": 26.4407,
        "pickup_lon": 50.0806,
        "pickup_name": "605. الدمام",
        "dropoff_name": "Dammam",
        "price": "13.78 ر.س",
        "service_type": "UberX",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_390",  # IMG_2341.JPG
        "request_time": time(18, 49),
        "pickup_lat": 26.4238,
        "pickup_lon": 50.0789,
        "pickup_name": "شارع فاطمة الزهراء 8214, الدمام",
        "dropoff_name": "طريق الانصار 3856, الجبيل",
        "price": "87.13 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_391",  # IMG_2342.JPG
        "request_time": time(18, 49),
        "pickup_lat": 26.5619,
        "pickup_lon": 50.0183,
        "pickup_name": "الفلاح 3801. القطيف",
        "dropoff_name": "شارع خلف بن تميم 2770. الدمام",
        "price": "40.92 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_392",  # photo_100_2026-10-24_00-39-06.jpg
        "request_time": time(18, 49),
        "pickup_lat": 26.5859,
        "pickup_lon": 49.9864,
        "pickup_name": "2 ب 7600. القطيف",
        "dropoff_name": "شارع العباس بن عبد المطلب. الدمام",
        "price": "30.84 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_393",  # photo_10_2026-10-24_00-39-05.jpg
        "request_time": time(6, 30),
        "pickup_lat": 26.5892,
        "pickup_lon": 50.0124,
        "pickup_name": "شارع السماوي 7887. القطيف",
        "dropoff_name": "طريق الأمير فيصل بن فهد 7266. الظهران",
        "price": "37.82 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_394",  # photo_10_2026-10-24_00-40-27.jpg
        "request_time": time(7, 35),
        "pickup_lat": 26.2861,
        "pickup_lon": 50.1936,
        "pickup_name": "الشارع السادس 8271. الخبر",
        "dropoff_name": "شارع أمير المؤمنين عمر بن الخطاب 8175. الدمام",
        "price": "30.05 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_395",  # photo_11_2026-10-24_00-39-05.jpg
        "request_time": time(7, 35),
        "pickup_lat": 26.4350,
        "pickup_lon": 50.0930,
        "pickup_name": "شارع الأزهري 4406. الدمام",
        "dropoff_name": "الشارع الثالث 4314. الخبر",
        "price": "34.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_396",  # photo_11_2026-10-24_00-40-27.jpg
        "request_time": time(7, 35),
        "pickup_lat": 26.3009,
        "pickup_lon": 50.1983,
        "pickup_name": "شارع 306211 الخبر",
        "dropoff_name": "شارع 306211. الخبر",
        "price": "17.75 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_397",  # photo_12_2026-10-24_00-39-05.jpg
        "request_time": time(19, 21),
        "pickup_lat": 26.4215,
        "pickup_lon": 50.0958,
        "pickup_name": "شارع 42ب 7783, الدمام",
        "dropoff_name": "شارع عرفات 2483, الدمام",
        "price": "26.02 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_398",  # photo_12_2026-10-24_00-40-27.jpg
        "request_time": time(8, 53),
        "pickup_lat": 26.4102,
        "pickup_lon": 50.0728,
        "pickup_name": "شارع 862024. الدمام",
        "dropoff_name": "طريق الأمير فيصل بن فهد بن عبدالعزيز. الظهران",
        "price": "3.00 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_399",  # photo_13_2026-10-24_00-39-05.jpg
        "request_time": time(2, 50),
        "pickup_lat": 26.4069,
        "pickup_lon": 50.0673,
        "pickup_name": "طريق ابو بكر الخوارزمي 4264. الدمام",
        "dropoff_name": "شارع ابن الزيات 3711 الخبر",
        "price": "41.68 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_400",  # photo_13_2026-10-24_00-40-27.jpg
        "request_time": time(12, 27),
        "pickup_lat": 26.7154,
        "pickup_lon": 50.0541,
        "pickup_name": "شارع 44185. رأس تنورة",
        "dropoff_name": "الشارع الثامن عشر 6841. الدمام",
        "price": "54.01 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_401",  # photo_14_2026-10-24_00-39-05.jpg
        "request_time": time(2, 53),
        "pickup_lat": 26.4305,
        "pickup_lon": 50.0686,
        "pickup_name": "شارع 26 ب 6847. الدمام",
        "dropoff_name": "Custodian of The Two Holy Mosques Rd. Al- Thuqbah. Al Khobar",
        "price": "30.87 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_402",  # photo_14_2026-10-24_00-40-27.jpg
        "request_time": time(1, 7),
        "pickup_lat": 26.5839,
        "pickup_lon": 50.0231,
        "pickup_name": "شارع صلاح الدين الصبوري 3755. القطيف",
        "dropoff_name": "18 3543. الدمام",
        "price": "39.78 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_403",  # photo_15_2026-10-24_00-39-05.jpg
        "request_time": time(12, 59),
        "pickup_lat": 26.4034,
        "pickup_lon": 50.0945,
        "pickup_name": "شارع 824438. الدمام",
        "dropoff_name": "طريق الأمير فيصل بن فهد 7266. الظهران",
        "price": "34.30 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_404",  # photo_15_2026-10-24_00-40-27.jpg
        "request_time": time(12, 59),
        "pickup_lat": 26.2831,
        "pickup_lon": 50.1968,
        "pickup_name": "شارع عامر بن البكير 7888. الخبر",
        "dropoff_name": "الدمام.Unnamed Road",
        "price": "36.62 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_405",  # photo_16_2026-10-24_00-39-05.jpg
        "request_time": time(16, 52),
        "pickup_lat": 26.5864,
        "pickup_lon": 49.9856,
        "pickup_name": "ب 6505. القطيف",
        "dropoff_name": "طريق 3616125. الدمام",
        "price": "52.05 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_406",  # photo_16_2026-10-24_00-40-27.jpg
        "request_time": time(16, 52),
        "pickup_lat": 26.5567,
        "pickup_lon": 49.9989,
        "pickup_name": "شارع السد 4834. القطيف",
        "dropoff_name": "طريق الامير نايف بن عبدالعزيز. الدمام",
        "price": "25.79 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_407",  # photo_17_2026-10-24_00-39-05.jpg
        "request_time": time(16, 52),
        "pickup_lat": 26.5621,
        "pickup_lon": 50.0159,
        "pickup_name": "شارع 822511. القطيف",
        "dropoff_name": "طريق الإمام علي بن أبي طالب 6687. القطيف",
        "price": "27.99 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_408",  # photo_17_2026-10-24_00-40-27.jpg
        "request_time": time(16, 52),
        "pickup_lat": 26.2714,
        "pickup_lon": 50.2326,
        "pickup_name": "شارع الوادي الاخضر 2164 الخبر",
        "dropoff_name": "شارع الربيعية 766913. القطيف",
        "price": "46.83 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_409",  # photo_18_2026-10-24_00-39-05.jpg
        "request_time": time(16, 52),
        "pickup_lat": 26.4022,
        "pickup_lon": 50.0798,
        "pickup_name": "طريق الملك فهد بن عبد العزيز 2600. الدمام",
        "dropoff_name": "شارع القدس 8659. القطيف",
        "price": "33.49 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_410",  # photo_18_2026-10-24_00-40-27.jpg
        "request_time": time(2, 52),
        "pickup_lat": 26.2996,
        "pickup_lon": 50.2171,
        "pickup_name": "شارع الوادي الاخضر 2164. الخبر",
        "dropoff_name": "شارع الربيعية 766913. القطيف",
        "price": "47.34 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_411",  # photo_19_2026-10-24_00-39-05.jpg
        "request_time": time(17, 48),
        "pickup_lat": 26.4045,
        "pickup_lon": 50.0731,
        "pickup_name": "شارع 36 7806, الدمام",
        "dropoff_name": "طريق 218, الجبيل",
        "price": "71.06 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_412",  # photo_19_2026-10-24_00-40-27.jpg
        "request_time": time(17, 48),
        "pickup_lat": 26.3004,
        "pickup_lon": 50.1258,
        "pickup_name": "152 غرب الظهران 4475. الظهران",
        "dropoff_name": "شارع داود القزاز 3469 القطيف",
        "price": "59.13 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_413",  # photo_1_2026-10-24_00-39-05.jpg
        "request_time": time(17, 50),
        "pickup_lat": 26.4227,
        "pickup_lon": 50.0695,
        "pickup_name": "شارع اسماعيل الزاهد 6781. الدمام",
        "dropoff_name": "شارع ابن عبادة 4016. الدمام",
        "price": "19.59 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_414",  # photo_1_2026-10-24_00-40-27.jpg
        "request_time": time(17, 50),
        "pickup_lat": 26.4147,
        "pickup_lon": 50.0821,
        "pickup_name": "شارع 802229. الدمام",
        "dropoff_name": "شارع 81439. الدمام",
        "price": "26.93 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_415",  # photo_2026-10-18_14-43-53.jpg
        "request_time": time(16, 26),
        "pickup_lat": 26.4157,
        "pickup_lon": 50.0683,
        "pickup_name": "الدمام",
        "dropoff_name": "الدمام",
        "price": "35.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_416",  # photo_2026-10-23_23-50-07.jpg
        "request_time": time(2, 43),
        "pickup_lat": 26.5782,
        "pickup_lon": 50.0299,
        "pickup_name": "جبر الكندي 4517. القطيف",
        "dropoff_name": "سليم الرازي 8314 صفوى",
        "price": "36.19 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_417",  # photo_20_2026-10-24_00-39-05.jpg
        "request_time": time(18, 57),
        "pickup_lat": 26.4320,
        "pickup_lon": 50.0791,
        "pickup_name": "شارع 19 6914. الدمام",
        "dropoff_name": "شارع عثمان بن قيس 7334. الخبر",
        "price": "39.98 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_418",  # photo_20_2026-10-24_00-40-27.jpg
        "request_time": time(18, 57),
        "pickup_lat": 26.3004,
        "pickup_lon": 50.1258,
        "pickup_name": "152 غرب الظهران 4475. الظهران",
        "dropoff_name": "شارع داود القزاز 3469 القطيف",
        "price": "59.13 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_419",  # photo_21_2026-10-24_00-39-06.jpg
        "request_time": time(18, 57),
        "pickup_lat": 26.5824,
        "pickup_lon": 50.0039,
        "pickup_name": "شارع البناء 4897. القطيف",
        "dropoff_name": "شارع الخنساء 2781. الدمام",
        "price": "37.11 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_420",  # photo_21_2026-10-24_00-40-27.jpg
        "request_time": time(13, 47),
        "pickup_lat": 26.4190,
        "pickup_lon": 50.0770,
        "pickup_name": "طريق الملك فهد بن عبد العزيز 9466. الخبر",
        "dropoff_name": "شارع القافلة 2548. القطيف",
        "price": "42.54 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_421",  # photo_22_2026-10-24_00-39-06.jpg
        "request_time": time(14, 0),
        "pickup_lat": 26.4156,
        "pickup_lon": 50.0821,
        "pickup_name": "طريق الملك فهد بن عبد العزيز 2600. الدمام",
        "dropoff_name": "شارع عثمان المري 4370. الدمام",
        "price": "33.41 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_422",  # photo_22_2026-10-24_00-40-27.jpg
        "request_time": time(13, 52),
        "pickup_lat": 26.4090,
        "pickup_lon": 50.0791,
        "pickup_name": "طريق الملك فهد بن عبد العزيز 6847. الخبر",
        "dropoff_name": "طريق 156 6948. الدمام",
        "price": "31.44 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_423",  # photo_23_2026-10-24_00-39-06.jpg
        "request_time": time(10, 59),
        "pickup_lat": 26.2932,
        "pickup_lon": 50.1358,
        "pickup_name": "طريق عثمان بن عفان 2415. الظهران",
        "dropoff_name": "شارع مصعب بن الزبير 6940. القطيف",
        "price": "33.07 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_424",  # photo_23_2026-10-24_00-40-27.jpg
        "request_time": time(4, 4),
        "pickup_lat": 26.2872,
        "pickup_lon": 50.1906,
        "pickup_name": "شارع معقل بن سنان 7582. الخبر",
        "dropoff_name": "19 7395. القطيف",
        "price": "50.05 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_425",  # photo_24_2026-10-24_00-39-06.jpg
        "request_time": time(7, 19),
        "pickup_lat": 26.2654,
        "pickup_lon": 50.1870,
        "pickup_name": "شارع 284116. الخبر",
        "dropoff_name": "طريق الملك فهد بن عبد العزيز 9198 الظهران",
        "price": "25.66 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_426",  # photo_24_2026-10-24_00-40-27.jpg
        "request_time": time(4, 7),
        "pickup_lat": 26.4147,
        "pickup_lon": 50.0827,
        "pickup_name": "طريق الملك فهد 3030. الدمام",
        "dropoff_name": "شارع 3 7105. القطيف",
        "price": "49.00 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_427",  # photo_25_2026-10-24_00-39-06.jpg
        "request_time": time(17, 35),
        "pickup_lat": 26.2944,
        "pickup_lon": 50.2081,
        "pickup_name": "شارع ابو عبد الرحمن بن عقيل 7106. الخبر",
        "dropoff_name": "5631 Cooperative Council Road Al Khuzama. Al Khobar 34721 8244. Saudi Arabia. AI",
        "price": "11.58 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_428",  # photo_25_2026-10-24_00-40-27.jpg
        "request_time": time(3, 50),
        "pickup_lat": 26.3177,
        "pickup_lon": 50.1628,
        "pickup_name": "شارع دوار الادارة 4137. الظهران",
        "dropoff_name": "شارع الحني 3503. القطيف",
        "price": "55.87 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_429",  # photo_26_2026-10-24_00-39-06.jpg
        "request_time": time(17, 35),
        "pickup_lat": 26.2621,
        "pickup_lon": 50.2116,
        "pickup_name": "شارع حبيب ابن الضحاك 7348. الخبر",
        "dropoff_name": "بوابة الميناء. الدمام",
        "price": "25.31 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_430",  # photo_26_2026-10-24_00-40-27.jpg
        "request_time": time(14, 4),
        "pickup_lat": 26.2872,
        "pickup_lon": 50.1906,
        "pickup_name": "شارع معقل بن سنان 7582. الخبر",
        "dropoff_name": "19 7395. القطيف",
        "price": "51.89 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_431",  # photo_27_2026-10-24_00-39-06.jpg
        "request_time": time(12, 42),
        "pickup_lat": 26.4350,
        "pickup_lon": 50.0881,
        "pickup_name": "شارع التوفيق 4383. الدمام",
        "dropoff_name": "605. الدمام",
        "price": "57.06 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_432",  # photo_27_2026-10-24_00-40-27.jpg
        "request_time": time(17, 45),
        "pickup_lat": 26.2614,
        "pickup_lon": 50.1866,
        "pickup_name": "شارع صلاح الدين الأيوبي 3166. الخبر",
        "dropoff_name": "605. الدمام",
        "price": "37.45 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_433",  # photo_28_2026-10-24_00-39-06.jpg
        "request_time": time(12, 44),
        "pickup_lat": 26.4350,
        "pickup_lon": 50.0881,
        "pickup_name": "شارع التوفيق 4383. الدمام",
        "dropoff_name": "605. الدمام",
        "price": "51.60 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_434",  # photo_28_2026-10-24_00-40-27.jpg
        "request_time": time(8, 49),
        "pickup_lat": 26.4124,
        "pickup_lon": 50.0933,
        "pickup_name": "طريق الملك فيصل بن عبدالعزيز. الدمام",
        "dropoff_name": "شارع معالي المهندس علي النعيمي 7109. الظهران",
        "price": "27.27 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_435",  # photo_29_2026-10-24_00-39-06.jpg
        "request_time": time(4, 5),
        "pickup_lat": 26.3074,
        "pickup_lon": 50.1533,
        "pickup_name": "شارع دوار الادارة 4137. الظهران",
        "dropoff_name": "شارع الحني 3503. القطيف",
        "price": "56.79 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_436",  # photo_29_2026-10-24_00-40-27.jpg
        "request_time": time(7, 11),
        "pickup_lat": 26.4234,
        "pickup_lon": 50.1015,
        "pickup_name": "شارع النعمان ابن مالك 7965. الدمام",
        "dropoff_name": "605. الدمام",
        "price": "39.75 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_437",  # photo_2_2026-10-24_00-39-05.jpg
        "request_time": time(20, 8),
        "pickup_lat": 26.2801,
        "pickup_lon": 50.1978,
        "pickup_name": "شارع 14 أ 3271, الخبر",
        "dropoff_name": "شارع 20 3363, الخبر",
        "price": "27.41 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_438",  # photo_2_2026-10-24_00-40-27.jpg
        "request_time": time(18, 40),
        "pickup_lat": 26.4257,
        "pickup_lon": 50.0678,
        "pickup_name": "شارع اليسر 2750, الدمام",
        "dropoff_name": "شارع مكة, الدمام",
        "price": "20.49 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_439",  # photo_30_2026-10-24_00-39-06.jpg
        "request_time": time(18, 40),
        "pickup_lat": 26.5764,
        "pickup_lon": 49.9996,
        "pickup_name": "شارع خالد بن سلمه 3219. القطيف 605",
        "dropoff_name": "طريق الظهران الجبيل السريع 7960. الدمام",
        "price": "28.40 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_440",  # photo_30_2026-10-24_00-40-27.jpg
        "request_time": time(7, 40),
        "pickup_lat": 26.2942,
        "pickup_lon": 50.1683,
        "pickup_name": "شارع 13 الشفاء 3335. الظهران",
        "dropoff_name": "شارع النضر بن الحارث 6525. الدمام",
        "price": "52.14 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_441",  # photo_31_2026-10-24_00-39-06.jpg
        "request_time": time(18, 35),
        "pickup_lat": 26.3122,
        "pickup_lon": 50.1258,
        "pickup_name": "شارع الظهران 8503 الظهران",
        "dropoff_name": "شارع عرفات 2483. الدمام",
        "price": "45.88 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_442",  # photo_31_2026-10-24_00-40-27.jpg
        "request_time": time(18, 35),
        "pickup_lat": 26.5531,
        "pickup_lon": 49.9992,
        "pickup_name": "شارع الريف 3628. القطيف",
        "dropoff_name": "عبد الرحمن بن عوف 3726. الدمام",
        "price": "43.02 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_443",  # photo_32_2026-10-24_00-39-06.jpg
        "request_time": time(18, 35),
        "pickup_lat": 26.5824,
        "pickup_lon": 50.0039,
        "pickup_name": "شارع البناء 4897. القطيف",
        "dropoff_name": "شارع زيد بن حارثة 3813. الدمام",
        "price": "35.37 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_444",  # photo_32_2026-10-24_00-40-27.jpg
        "request_time": time(18, 35),
        "pickup_lat": 26.5531,
        "pickup_lon": 49.9992,
        "pickup_name": "شارع الريف 3628. القطيف",
        "dropoff_name": "عبد الرحمن بن عوف 3726. الدمام",
        "price": "43.02 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_445",  # photo_33_2026-10-24_00-39-06.jpg
        "request_time": time(18, 35),
        "pickup_lat": 26.9908,
        "pickup_lon": 49.6593,
        "pickup_name": "طريق 3370112. الجبيل",
        "dropoff_name": "عبد الرحيم الخطيب 3636. الدمام",
        "price": "75.75 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_446",  # photo_33_2026-10-24_00-40-27.jpg
        "request_time": time(18, 35),
        "pickup_lat": 26.5481,
        "pickup_lon": 49.9954,
        "pickup_name": "ب 6525. القطيف",
        "dropoff_name": "طريق الملك فيصل بن عبد العزيز القطيف",
        "price": "19.37 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_447",  # photo_34_2026-10-24_00-39-06.jpg
        "request_time": time(3, 41),
        "pickup_lat": 26.4612,
        "pickup_lon": 50.1335,
        "pickup_name": "طريق الأشرعه 5396. الدمام",
        "dropoff_name": "شارع 87875. الدمام",
        "price": "26.06 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_448",  # photo_34_2026-10-24_00-40-27.jpg
        "request_time": time(3, 41),
        "pickup_lat": 26.5759,
        "pickup_lon": 50.0271,
        "pickup_name": "شارع عثمان الدقاق 7763. القطيف",
        "dropoff_name": "طريق الفرعي الملك سعود بن عبدالعزيز. الخبر",
        "price": "43.67 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_449",  # photo_35_2026-10-24_00-39-06.jpg
        "request_time": time(7, 55),
        "pickup_lat": 26.3977,
        "pickup_lon": 50.0958,
        "pickup_name": "شارع الرضاء 3490. الدمام",
        "dropoff_name": "شارع الأمير مشعل بن عبد العزيز 2446. الدمام",
        "price": "25.42 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_450",  # photo_35_2026-10-24_00-40-27.jpg
        "request_time": time(3, 10),
        "pickup_lat": 26.5614,
        "pickup_lon": 50.0256,
        "pickup_name": "شارع العاصفة 3432. القطيف",
        "dropoff_name": "الشارع الثامن عشر 7063. الدمام",
        "price": "38.46 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_451",  # photo_36_2026-10-24_00-39-06.jpg
        "request_time": time(11, 27),
        "pickup_lat": 26.4337,
        "pickup_lon": 50.1063,
        "pickup_name": "شارع 7 8002, الدمام",
        "dropoff_name": "شارع 20, الخبر",
        "price": "28.57 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_452",  # photo_36_2026-10-24_00-40-27.jpg
        "request_time": time(4, 11),
        "pickup_lat": 26.2616,
        "pickup_lon": 50.1838,
        "pickup_name": "شارع اسحاق بن الفرات 6220. الخبر",
        "dropoff_name": "طريق عمر بن الخطاب. الدمام",
        "price": "41.32 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_453",  # photo_37_2026-10-24_00-39-06.jpg
        "request_time": time(4, 11),
        "pickup_lat": 26.3068,
        "pickup_lon": 50.1957,
        "pickup_name": "طريق الأمير فيصل بن فهد بن عبدالعزيز. الظهران",
        "dropoff_name": "طريق حمزة بن عبد المطلب 2753. الدمام",
        "price": "23.45 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_454",  # photo_37_2026-10-24_00-40-27.jpg
        "request_time": time(3, 59),
        "pickup_lat": 26.4294,
        "pickup_lon": 50.1133,
        "pickup_name": "شارع ابن نباته 4777. ابها",
        "dropoff_name": "شارع خريم 6375. ابها",
        "price": "15.72 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_455",  # photo_38_2026-10-24_00-39-06.jpg
        "request_time": time(10, 2),
        "pickup_lat": 27.0691,
        "pickup_lon": 49.5793,
        "pickup_name": "شارع مدينة الجبيل الصناعيه 4091 4434. الجبيل الصناعية",
        "dropoff_name": "شارع الملك فيصل الغربي. الجبيل",
        "price": "22.09 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_456",  # photo_38_2026-10-24_00-40-27.jpg
        "request_time": time(10, 2),
        "pickup_lat": 26.2594,
        "pickup_lon": 50.1923,
        "pickup_name": "شارع الاحرار 7473 الخبر",
        "dropoff_name": "شارع 739820. الدمام",
        "price": "50.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_457",  # photo_39_2026-10-24_00-39-06.jpg
        "request_time": time(16, 33),
        "pickup_lat": 26.3959,
        "pickup_lon": 50.0933,
        "pickup_name": "طريق حمزة بن عبد المطلب 7522. الدمام",
        "dropoff_name": "3730 16th Street. Al Khobar Al Shamalia. Al",
        "price": "61.30 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_458",  # photo_3_2026-10-24_00-39-05.jpg
        "request_time": time(16, 33),
        "pickup_lat": 26.5689,
        "pickup_lon": 49.9884,
        "pickup_name": "شارع الاكموم 4684. القطيف",
        "dropoff_name": "مشوار لمدة 1 س، 11 د لمسافة 102.3",
        "price": "87.10 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_459",  # photo_3_2026-10-24_00-40-27.jpg
        "request_time": time(18, 40),
        "pickup_lat": 26.4407,
        "pickup_lon": 50.0953,
        "pickup_name": "شارع القارب 8361, الدمام",
        "dropoff_name": "شارع 14 أ 2902, الخبر",
        "price": "20.90 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_460",  # photo_40_2026-10-24_00-39-06.jpg
        "request_time": time(7, 33),
        "pickup_lat": 26.4255,
        "pickup_lon": 50.0903,
        "pickup_name": "شارع 26ب 8131. الدمام",
        "dropoff_name": "طريق الملك فهد بن عبد العزيز 6245. الخبر",
        "price": "27.07 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_461",  # photo_41_2026-10-24_00-39-06.jpg
        "request_time": time(7, 45),
        "pickup_lat": 26.4202,
        "pickup_lon": 50.1033,
        "pickup_name": "شارع الحياه 3296. الدمام",
        "dropoff_name": "605. الدمام",
        "price": "45.94 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_462",  # photo_42_2026-10-24_00-39-06.jpg
        "request_time": time(10, 20),
        "pickup_lat": 26.4030,
        "pickup_lon": 50.1013,
        "pickup_name": "26ج 6843. الدمام",
        "dropoff_name": "605. الدمام",
        "price": "29.95 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_463",  # photo_43_2026-10-24_00-39-06.jpg
        "request_time": time(4, 29),
        "pickup_lat": 26.4069,
        "pickup_lon": 50.0788,
        "pickup_name": "طريق قطب الدين الشافعي. الدمام",
        "dropoff_name": "شارع 27 ب 8547. الدمام",
        "price": "31.55 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_464",  # photo_44_2026-10-24_00-39-06.jpg
        "request_time": time(8, 8),
        "pickup_lat": 26.5842,
        "pickup_lon": 50.0331,
        "pickup_name": "شارع 652516. القطيف",
        "dropoff_name": "طريق الأمير فيصل بن فهد بن عبد العزيز 3132. الخبر",
        "price": "45.27 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_465",  # photo_45_2026-10-24_00-39-06.jpg
        "request_time": time(10, 39),
        "pickup_lat": 26.4309,
        "pickup_lon": 50.0838,
        "pickup_name": "شارع 14ب 8354. الدمام",
        "dropoff_name": "شارع المغيره ابن شعبه 6615. الخبر",
        "price": "21.62 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_466",  # photo_46_2026-10-24_00-39-06.jpg
        "request_time": time(10, 39),
        "pickup_lat": 26.3227,
        "pickup_lon": 50.1380,
        "pickup_name": "Mall of Dhahran Boulevard. Az Zahran",
        "dropoff_name": "221 ضاحية الملك فهد 6250. الدمام",
        "price": "24.39 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_467",  # photo_47_2026-10-24_00-39-06.jpg
        "request_time": time(16, 32),
        "pickup_lat": 26.3970,
        "pickup_lon": 50.0855,
        "pickup_name": "داوود الانطاكي 3738. الدمام",
        "dropoff_name": "طريق الملك خالد 7215. الخبر",
        "price": "22.18 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_468",  # photo_48_2026-10-24_00-39-06.jpg
        "request_time": time(17, 31),
        "pickup_lat": 26.4427,
        "pickup_lon": 50.0925,
        "pickup_name": "شارع 122 7791. الدمام",
        "dropoff_name": "طريق الأمير فيصل بن فهد بن عبدالعزيز. الخبر",
        "price": "24.20 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_469",  # photo_49_2026-10-24_00-39-06.jpg
        "request_time": time(7, 31),
        "pickup_lat": 26.4057,
        "pickup_lon": 50.0838,
        "pickup_name": "شارع 33 6677, الدمام",
        "dropoff_name": "شارع سلمان الفارسي, الدمام",
        "price": "26.04 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_470",  # photo_4_2026-10-24_00-39-05.jpg
        "request_time": time(7, 31),
        "pickup_lat": 26.5839,
        "pickup_lon": 50.0231,
        "pickup_name": "شارع صلاح الدين الصبوري 3755. القطيف",
        "dropoff_name": "18 3543. الدمام",
        "price": "41.36 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_471",  # photo_4_2026-10-24_00-40-27.jpg
        "request_time": time(18, 41),
        "pickup_lat": 26.4204,
        "pickup_lon": 50.1065,
        "pickup_name": "شارع 35 7927, الدمام",
        "dropoff_name": "طريق الملك عبدالعزيز 3863, الظهران",
        "price": "14.78 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_472",  # photo_50_2026-10-24_00-39-06.jpg
        "request_time": time(17, 34),
        "pickup_lat": 26.4054,
        "pickup_lon": 50.1048,
        "pickup_name": "شارع ابو الحسن السلمي 3374. الدمام",
        "dropoff_name": "شارع 8681605. الخبر",
        "price": "31.53 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_473",  # photo_51_2026-10-24_00-39-06.jpg
        "request_time": time(7, 36),
        "pickup_lat": 26.4097,
        "pickup_lon": 50.1101,
        "pickup_name": "شارع مصعب الزبير 3619. الدمام",
        "dropoff_name": "طريق عثمان بن عفان 2415. الظهران",
        "price": "17.49 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_474",  # photo_52_2026-10-24_00-39-06.jpg
        "request_time": time(17, 43),
        "pickup_lat": 26.4455,
        "pickup_lon": 50.0990,
        "pickup_name": "24ب 6761. الدمام",
        "dropoff_name": "شارع الخنساء 8388. الدمام",
        "price": "24.97 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_475",  # photo_53_2026-10-24_00-39-06.jpg
        "request_time": time(17, 45),
        "pickup_lat": 26.4255,
        "pickup_lon": 50.0988,
        "pickup_name": "شارع محمود بن الفضل 3959. الدمام",
        "dropoff_name": "شارع الشعاب 4327. الدمام",
        "price": "12.75 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_476",  # photo_54_2026-10-24_00-39-06.jpg
        "request_time": time(17, 58),
        "pickup_lat": 26.4225,
        "pickup_lon": 50.0728,
        "pickup_name": "شارع الخوارزمي 2439. الدمام",
        "dropoff_name": "شارع 16د 7455. الدمام",
        "price": "26.41 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_477",  # photo_55_2026-10-24_00-39-06.jpg
        "request_time": time(5, 52),
        "pickup_lat": 26.2896,
        "pickup_lon": 50.2326,
        "pickup_name": "شارع الخندق 7865. الخبر",
        "dropoff_name": "شارع 44593. القطيف",
        "price": "40.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_478",  # photo_56_2026-10-24_00-39-06.jpg
        "request_time": time(8, 35),
        "pickup_lat": 26.5844,
        "pickup_lon": 50.0007,
        "pickup_name": "شارع عبدالله بن حارث 6851. القطيف",
        "dropoff_name": "طريق اكثم بن صيفي 4292. الدمام",
        "price": "38.43 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_479",  # photo_57_2026-10-24_00-39-06.jpg
        "request_time": time(8, 35),
        "pickup_lat": 26.5561,
        "pickup_lon": 50.0261,
        "pickup_name": "شارع ابو قاسم الشابي 6539. القطيف",
        "dropoff_name": "شارع 20 الخبر",
        "price": "58.21 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_480",  # photo_58_2026-10-24_00-39-06.jpg
        "request_time": time(8, 35),
        "pickup_lat": 26.5831,
        "pickup_lon": 50.0044,
        "pickup_name": "شارع عمر بن معاوية 3611. القطيف",
        "dropoff_name": "Nakheel Mall. Dammam",
        "price": "38.58 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_481",  # photo_59_2026-10-24_00-39-06.jpg
        "request_time": time(7, 31),
        "pickup_lat": 26.4347,
        "pickup_lon": 50.0648,
        "pickup_name": "شارع ابو الدرداء 4820. الدمام",
        "dropoff_name": "الخبر",
        "price": "43.42 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_482",  # photo_5_2026-10-24_00-39-05.jpg
        "request_time": time(13, 21),
        "pickup_lat": 26.5759,
        "pickup_lon": 50.0271,
        "pickup_name": "شارع عثمان الدقاق 7763. القطيف",
        "dropoff_name": "طريق الأمير فيصل بن فهد. الظهران",
        "price": "46.41 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_483",  # photo_5_2026-10-24_00-40-27.jpg
        "request_time": time(6, 41),
        "pickup_lat": 26.4187,
        "pickup_lon": 50.0750,
        "pickup_name": "شارع اليسر 2750. الدمام",
        "dropoff_name": "شارع مكة. الدمام",
        "price": "20.49 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_484",  # photo_60_2026-10-24_00-39-06.jpg
        "request_time": time(6, 41),
        "pickup_lat": 26.5666,
        "pickup_lon": 49.9899,
        "pickup_name": "شارع حزام الرضا 2780. القطيف",
        "dropoff_name": "605. الدمام",
        "price": "41.48 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_485",  # photo_61_2026-10-24_00-39-06.jpg
        "request_time": time(6, 41),
        "pickup_lat": 26.5666,
        "pickup_lon": 49.9899,
        "pickup_name": "شارع حزام الرضا 2780. القطيف",
        "dropoff_name": "605. الدمام",
        "price": "39.85 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_486",  # photo_62_2026-10-24_00-39-06.jpg
        "request_time": time(3, 49),
        "pickup_lat": 27.0006,
        "pickup_lon": 49.6405,
        "pickup_name": "شارع كعب بن سعد 8056. الجبيل",
        "dropoff_name": "شارع الاعشى 8744. الجبيل الصناعية",
        "price": "33.20 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_487",  # photo_63_2026-10-24_00-39-06.jpg
        "request_time": time(2, 40),
        "pickup_lat": 26.4305,
        "pickup_lon": 50.0923,
        "pickup_name": "شارع الزواوي 4654, الدمام",
        "dropoff_name": "بوليفارد الظهران مول, الظهران",
        "price": "22.40 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_488",  # photo_64_2026-10-24_00-39-06.jpg
        "request_time": time(12, 41),
        "pickup_lat": 26.4257,
        "pickup_lon": 50.0818,
        "pickup_name": "شارع أبو أوس الأسلمي 2810. الدمام",
        "dropoff_name": "شارع عبد الله جفري 8200. الخبر",
        "price": "26.98 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_489",  # photo_65_2026-10-24_00-39-06.jpg
        "request_time": time(12, 45),
        "pickup_lat": 26.4387,
        "pickup_lon": 50.1050,
        "pickup_name": "شارع 8 ب 7681. الدمام",
        "dropoff_name": "605. الدمام",
        "price": "38.65 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_490",  # photo_66_2026-10-24_00-39-06.jpg
        "request_time": time(12, 50),
        "pickup_lat": 26.4060,
        "pickup_lon": 50.1030,
        "pickup_name": "13 6959. الدمام",
        "dropoff_name": "طريق الأمير فيصل بن فهد بن عبد العزيز 2230 الخبر",
        "price": "35.30 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_491",  # photo_67_2026-10-24_00-39-06.jpg
        "request_time": time(5, 5),
        "pickup_lat": 26.2959,
        "pickup_lon": 50.1958,
        "pickup_name": "طريق الملك سلمان بن عبد العزيز 3223. الخبر",
        "dropoff_name": "شارع 248816. الخبر",
        "price": "21.50 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_492",  # photo_68_2026-10-24_00-39-06.jpg
        "request_time": time(5, 5),
        "pickup_lat": 26.5846,
        "pickup_lon": 50.0086,
        "pickup_name": "شارع سعيد بن القشب 7437. القطيف",
        "dropoff_name": "طريق الأمير فيصل بن فهد بن عبدالعزيز. الظهران",
        "price": "45.93 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_493",  # photo_69_2026-10-24_00-39-06.jpg
        "request_time": time(1, 1),
        "pickup_lat": 26.4102,
        "pickup_lon": 50.1135,
        "pickup_name": "1 4230, الدمام",
        "dropoff_name": "شارع النابغة التغلبي 7573, الخبر",
        "price": "31.48 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_494",  # photo_6_2026-10-24_00-39-05.jpg
        "request_time": time(13, 45),
        "pickup_lat": 26.4102,
        "pickup_lon": 50.1135,
        "pickup_name": "1 4230, الدمام",
        "dropoff_name": "شارع 33 4197, الخبر",
        "price": "48.38 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_495",  # photo_6_2026-10-24_00-40-27.jpg
        "request_time": time(18, 42),
        "pickup_lat": 26.4382,
        "pickup_lon": 50.1078,
        "pickup_name": "شارع 37أ 6887, الدمام",
        "dropoff_name": "شارع 9 7977, الدمام",
        "price": "19.34 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_496",  # photo_70_2026-10-24_00-39-06.jpg
        "request_time": time(3, 50),
        "pickup_lat": 26.5531,
        "pickup_lon": 50.0331,
        "pickup_name": "شارع ابو عبد الله الحسيني 3654. القطيف",
        "dropoff_name": "شارع 781521. الدمام",
        "price": "27.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_497",  # photo_71_2026-10-24_00-39-06.jpg
        "request_time": time(9, 11),
        "pickup_lat": 26.9951,
        "pickup_lon": 49.6415,
        "pickup_name": "Unnamed Road, الجبيل",
        "dropoff_name": "شارع العاذر 7722, الجبيل الصناعية",
        "price": "24.49 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_498",  # photo_72_2026-10-24_00-39-06.jpg
        "request_time": time(0, 33),
        "pickup_lat": 26.4192,
        "pickup_lon": 50.0713,
        "pickup_name": "انيف بن حبيب 3661. الدمام",
        "dropoff_name": "شارع السروات 8597. الجبيل الصناعية",
        "price": "82.88 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_499",  # photo_73_2026-10-24_00-39-06.jpg
        "request_time": time(0, 33),
        "pickup_lat": 26.4294,
        "pickup_lon": 50.0993,
        "pickup_name": "الامير متعب ابن عبد العزيز 7064. الدمام",
        "dropoff_name": "شارع ابراهيم الازدي 4030. الخبر",
        "price": "38.09 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_500",  # photo_74_2026-10-24_00-39-06.jpg
        "request_time": time(19, 38),
        "pickup_lat": 26.5597,
        "pickup_lon": 49.9916,
        "pickup_name": "شارع 20جـ 7115. القطيف",
        "dropoff_name": "9. القطيف",
        "price": "22.20 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_501",  # photo_75_2026-10-24_00-39-06.jpg
        "request_time": time(19, 38),
        "pickup_lat": 26.4300,
        "pickup_lon": 50.0716,
        "pickup_name": "شارع فاطمة الزهراء الدمام",
        "dropoff_name": "شارع البيروني 7363. الجبيل الصناعية",
        "price": "77.37 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_502",  # photo_76_2026-10-24_00-39-06.jpg
        "request_time": time(10, 12),
        "pickup_lat": 26.3041,
        "pickup_lon": 50.2221,
        "pickup_name": "جامعة الملك فهد للبترول 4104. الظهران",
        "dropoff_name": "3B 6854. Al Qatif",
        "price": "47.71 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_503",  # photo_77_2026-10-24_00-39-06.jpg
        "request_time": time(13, 8),
        "pickup_lat": 26.3184,
        "pickup_lon": 50.1213,
        "pickup_name": "شارع 22 الشفاء 3542. الظهران",
        "dropoff_name": "Khaleej Rd. Al Aziziyah. Dammam",
        "price": "50.64 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_504",  # photo_78_2026-10-24_00-39-06.jpg
        "request_time": time(13, 45),
        "pickup_lat": 26.4027,
        "pickup_lon": 50.0718,
        "pickup_name": "13 مدينة الملك فيصل الجامعية 6397. الدمام",
        "dropoff_name": "شارع 807337. الدمام",
        "price": "58.39 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_505",  # photo_79_2026-10-24_00-39-06.jpg
        "request_time": time(4, 25),
        "pickup_lat": 26.2694,
        "pickup_lon": 50.2128,
        "pickup_name": "Abu Al Dwr Al Rumi Street 6651. Al Khobar",
        "dropoff_name": "King Abdullah Bin Abdulaziz Street 2341. Ras Tanurah",
        "price": "57.69 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_506",  # photo_7_2026-10-24_00-39-05.jpg
        "request_time": time(13, 45),
        "pickup_lat": 26.4102,
        "pickup_lon": 50.1135,
        "pickup_name": "1 4230, الدمام",
        "dropoff_name": "شارع 33 4197, الخبر",
        "price": "48.38 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_507",  # photo_7_2026-10-24_00-40-27.jpg
        "request_time": time(7, 41),
        "pickup_lat": 26.4077,
        "pickup_lon": 50.0748,
        "pickup_name": "طريق الملك فهد بن عبد العزيز 8622. الخبر",
        "dropoff_name": "عبد الرزاق بن همام 9147. الدمام",
        "price": "24.04 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_508",  # photo_80_2026-10-24_00-39-06.jpg
        "request_time": time(7, 45),
        "pickup_lat": 26.4132,
        "pickup_lon": 50.0641,
        "pickup_name": "شارع يوسف الشافعي 6741. الدمام",
        "dropoff_name": "شارع محمد الكوفي 9138. بقيق",
        "price": "54.64 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_509",  # photo_81_2026-10-24_00-39-06.jpg
        "request_time": time(7, 40),
        "pickup_lat": 26.5412,
        "pickup_lon": 49.9984,
        "pickup_name": "القسمة 2683. القطيف",
        "dropoff_name": "طريق الملك فيصل بن عبد العزيز. الخبر",
        "price": "40.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_510",  # photo_82_2026-10-24_00-39-06.jpg
        "request_time": time(1, 1),
        "pickup_lat": 26.4042,
        "pickup_lon": 50.0978,
        "pickup_name": "طريق حمزة بن عبد المطلب 2753. الدمام",
        "dropoff_name": "طريق الأمير فيصل بن فهد بن عبد العزيز. الظهران",
        "price": "31.06 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_511",  # photo_83_2026-10-24_00-39-06.jpg
        "request_time": time(11, 9),
        "pickup_lat": 26.4309,
        "pickup_lon": 50.0838,
        "pickup_name": "شارع 14ب 8354. الدمام",
        "dropoff_name": "شارع المغيره ابن شعبه 6615. الخبر",
        "price": "21.34 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_512",  # photo_84_2026-10-24_00-39-06.jpg
        "request_time": time(1, 38),
        "pickup_lat": 26.4069,
        "pickup_lon": 50.0788,
        "pickup_name": "طريق قطب الدين الشافعي. الدمام",
        "dropoff_name": "شارع ابو عبد الله المخزومي 7198. القطيف",
        "price": "22.27 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_513",  # photo_85_2026-10-24_00-39-06.jpg
        "request_time": time(1, 38),
        "pickup_lat": 26.5462,
        "pickup_lon": 49.9871,
        "pickup_name": "شارع 79465. القطيف",
        "dropoff_name": "شارع الملك سعود بن عبد العزيز 2028. الدمام",
        "price": "28.84 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_514",  # photo_86_2026-10-24_00-39-06.jpg
        "request_time": time(1, 38),
        "pickup_lat": 26.5644,
        "pickup_lon": 50.0334,
        "pickup_name": "شارع جعفر الطيار 7499. القطيف",
        "dropoff_name": "طريق الأمير فيصل بن فهد بن عبدالعزيز الظهران",
        "price": "57.06 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_515",  # photo_87_2026-10-24_00-39-06.jpg
        "request_time": time(6, 3),
        "pickup_lat": 26.4157,
        "pickup_lon": 50.0683,
        "pickup_name": "الدمام",
        "dropoff_name": "الدمام",
        "price": "25.77 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_516",  # photo_88_2026-10-24_00-39-06.jpg
        "request_time": time(6, 3),
        "pickup_lat": 26.2934,
        "pickup_lon": 50.2188,
        "pickup_name": "شارع 19د 3047, الخبر",
        "dropoff_name": "605, الدمام",
        "price": "83.16 ر.س",
        "service_type": "UberXL حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_517",  # photo_89_2026-10-24_00-39-06.jpg
        "request_time": time(3, 17),
        "pickup_lat": 26.3016,
        "pickup_lon": 50.2193,
        "pickup_name": "شارع الأول 3993, الخبر",
        "dropoff_name": "34ب 4272, الخبر",
        "price": "49.59 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_518",  # photo_8_2026-10-24_00-39-05.jpg
        "request_time": time(13, 45),
        "pickup_lat": 26.4102,
        "pickup_lon": 50.1135,
        "pickup_name": "1 4230, الدمام",
        "dropoff_name": "شارع 33 4197, الخبر",
        "price": "48.38 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_519",  # photo_8_2026-10-24_00-40-27.jpg
        "request_time": time(13, 45),
        "pickup_lat": 26.2233,
        "pickup_lon": 50.1943,
        "pickup_name": "شارع العلا 6879, الخبر",
        "dropoff_name": "1ب 8577, الدمام",
        "price": "25.55 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_520",  # photo_90_2026-10-24_00-39-06.jpg
        "request_time": time(13, 45),
        "pickup_lat": 26.4795,
        "pickup_lon": 50.0456,
        "pickup_name": "شارع سيهات 7308 الخبر",
        "dropoff_name": "شارع العاشر 7102. الخبر",
        "price": "12.00 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قصيرة"
    },
    {
        "id": "ride_ai_521",  # photo_91_2026-10-24_00-39-06.jpg
        "request_time": time(13, 45),
        "pickup_lat": 26.5504,
        "pickup_lon": 49.9914,
        "pickup_name": "شارع ابو ذر الغفاري. القطيف",
        "dropoff_name": "الشارع الثامن والعشرون. الدمام",
        "price": "27.28 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_522",  # photo_92_2026-10-24_00-39-06.jpg
        "request_time": time(2, 18),
        "pickup_lat": 26.4052,
        "pickup_lon": 50.1131,
        "pickup_name": "شارع 83229. الدمام",
        "dropoff_name": "ات و 37 عليها",
        "price": "29.99 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_523",  # photo_93_2026-10-24_00-39-06.jpg
        "request_time": time(4, 26),
        "pickup_lat": 26.4378,
        "pickup_lon": 50.1045,
        "pickup_name": "شارع الأمير محمد بن فهد 9369. الدمام",
        "dropoff_name": "شارع الاوزاعي 3080. الدمام",
        "price": "19.85 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_524",  # photo_94_2026-10-24_00-39-06.jpg
        "request_time": time(17, 57),
        "pickup_lat": 26.4167,
        "pickup_lon": 50.0738,
        "pickup_name": "شارع 613. الدمام",
        "dropoff_name": "شارع 4487595. الجبيل",
        "price": "58.28 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_525",  # photo_95_2026-10-24_00-39-06.jpg
        "request_time": time(8, 1),
        "pickup_lat": 26.4300,
        "pickup_lon": 50.1011,
        "pickup_name": "شارع ابو القاسم ادريس 3192. الدمام",
        "dropoff_name": "شارع الملك فهد بن عبد العزيز 7167. الخبر",
        "price": "31.37 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_526",  # photo_96_2026-10-24_00-39-06.jpg
        "request_time": time(8, 1),
        "pickup_lat": 26.5517,
        "pickup_lon": 50.0269,
        "pickup_name": "طريق أحد 4130. القطيف",
        "dropoff_name": "شارع الخوارزمي 2444. الدمام",
        "price": "28.58 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_527",  # photo_97_2026-10-24_00-39-06.jpg
        "request_time": time(8, 1),
        "pickup_lat": 26.5621,
        "pickup_lon": 50.0159,
        "pickup_name": "شارع 822511. القطيف",
        "dropoff_name": "طريق الإمام علي بن أبي طالب 6687. القطيف",
        "price": "24.92 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_528",  # photo_98_2026-10-24_00-39-06.jpg
        "request_time": time(8, 1),
        "pickup_lat": 26.3974,
        "pickup_lon": 50.0686,
        "pickup_name": "شارع فضالة بن عبيد. الدمام",
        "dropoff_name": "طريق الكرامة 8817. الجبيل الصناعية",
        "price": "63.78 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_529",  # photo_99_2026-10-24_00-39-06.jpg
        "request_time": time(19, 1),
        "pickup_lat": 26.2990,
        "pickup_lon": 50.2048,
        "pickup_name": "طريق الأمير فيصل بن فهد 6864",
        "dropoff_name": "الظهران",
        "price": "35.00 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_530",  # photo_9_2026-10-24_00-39-05.jpg
        "request_time": time(11, 49),
        "pickup_lat": 26.4147,
        "pickup_lon": 50.1018,
        "pickup_name": "42301. الدمام",
        "dropoff_name": "شارع 27 ب 3992. الخبر",
        "price": "58.76 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_531",  # photo_9_2026-10-24_00-40-27.jpg
        "request_time": time(7, 35),
        "pickup_lat": 26.2649,
        "pickup_lon": 50.1951,
        "pickup_name": "شارع الخامس والعشرون 5229. الخبر",
        "dropoff_name": "شارع الأمير سلطان بن عبدالعزيز 3231. الدمام",
        "price": "25.81 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
]

# ==============================================================================
# Matching Engine
# ==============================================================================
def find_matching_rides(captain_lat, captain_lon, now_dt):
    matches = []
    current_minutes = now_dt.hour * 60 + now_dt.minute
    current_weekday = now_dt.weekday()  # Monday=0 .. Sunday=6

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

    # Prioritize train arrival alerts first when active, then distance proximity and time alignment
    matches.sort(key=lambda x: (0 if "train_arrival" in x[0] else 1, x[1], x[2]))
    return matches

# ==============================================================================
# Telegram Handlers
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚀 رادار الطلبات المباشر مفعل.\n"
        f"قاعدة البيانات محدثة وتضم {len(HISTORICAL_RIDES)} طلب سابق (شاملة مواعيد وصول قطار الدمام قبل الموعد بـ 30 دقيقة).\n"
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

        if "train_arrival" in ride:
            alert_text = (
                f"🚆 *تنبيه وصول قطار لمحطة الدمام (قبل الموعد بـ 30 دقيقة)!*\n\n"
                f"📍 *الموقع:* {ride['pickup_name']}\n"
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
