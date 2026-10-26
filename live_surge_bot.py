import os
import math
import asyncio
import threading
from datetime import datetime, time, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
    "TELEGRAM_BOT_TOKEN", "8786819830:AAF85r2H4SJ6Z34qpbkStybjanAgIMfaHQA"
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

# ==============================================================================
# Historical Rides Database (556 Entries: 16 Base + 9 Train Arrivals + 531 Extracted from AI Folder)
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

    # --- مواعيد وصول القطار لمحطة الدمام (التنبيه قبل الوصول بـ 30 دقيقة) - photo_2026-10-23_23-51-08.jpg ---
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
    {
        "id": "ride_ai_001",  # IMG_1927.JPG
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
        "id": "ride_ai_002",  # IMG_1928.JPG
        "request_time": time(7, 23),
        "pickup_lat": 26.5624,
        "pickup_lon": 49.9841,
        "pickup_name": "شارع 298528. القطيف ة",
        "dropoff_name": "شارع الامام محمد بن عبد الوهاب 4074. الدمام",
        "price": "46.38 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_003",  # IMG_1929.JPG
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
        "id": "ride_ai_004",  # IMG_1930.JPG
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
        "id": "ride_ai_005",  # IMG_1931.JPG
        "request_time": time(12, 47),
        "pickup_lat": 26.4380,
        "pickup_lon": 50.0671,
        "pickup_name": "طريق 38. الدمام ل",
        "dropoff_name": "شارع 111. الدمام",
        "price": "46.88 ر.س",
        "service_type": "UberX",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_006",  # IMG_1932.JPG
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
        "id": "ride_ai_007",  # IMG_1933.JPG
        "request_time": time(4, 51),
        "pickup_lat": 26.4122,
        "pickup_lon": 50.0878,
        "pickup_name": "شارع 10. الدمام ل",
        "dropoff_name": "شارع العبره 7318. الخبر",
        "price": "40.91 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_008",  # IMG_1934.JPG
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
        "id": "ride_ai_009",  # IMG_1935.JPG
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
        "id": "ride_ai_010",  # IMG_1936.JPG
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
        "id": "ride_ai_011",  # IMG_1937.JPG
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
        "id": "ride_ai_012",  # IMG_1938.JPG
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
        "id": "ride_ai_013",  # IMG_1939.JPG
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
        "id": "ride_ai_014",  # IMG_1940.JPG
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
        "id": "ride_ai_015",  # IMG_1941.JPG
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
        "id": "ride_ai_016",  # IMG_1942.JPG
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
        "id": "ride_ai_017",  # IMG_1943.JPG
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
        "id": "ride_ai_018",  # IMG_1944.JPG
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
        "id": "ride_ai_019",  # IMG_1945.JPG
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
        "id": "ride_ai_020",  # IMG_1946.JPG
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
        "id": "ride_ai_021",  # IMG_1947.JPG
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
        "id": "ride_ai_022",  # IMG_1948.JPG
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
        "id": "ride_ai_023",  # IMG_1949.JPG
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
        "id": "ride_ai_024",  # IMG_1950.JPG
        "request_time": time(6, 13),
        "pickup_lat": 26.4794,
        "pickup_lon": 50.0426,
        "pickup_name": "شارع النسيم 5210. سيهات 6",
        "dropoff_name": "شارع القرية العليا 7245. الخبر",
        "price": "49.44 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_025",  # IMG_1951.JPG
        "request_time": time(15, 24),
        "pickup_lat": 26.4388,
        "pickup_lon": 50.0949,
        "pickup_name": "طريق الملك سعود بن عبد العزيز 8867. الخبر ة",
        "dropoff_name": "ب 8202. سيهات",
        "price": "52.60 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_026",  # IMG_1952.JPG
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
        "id": "ride_ai_027",  # IMG_1953.JPG
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
        "id": "ride_ai_028",  # IMG_1954.JPG
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
        "id": "ride_ai_029",  # IMG_1955.JPG
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
        "id": "ride_ai_030",  # IMG_1956.JPG
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
        "id": "ride_ai_031",  # IMG_1957.JPG
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
        "id": "ride_ai_032",  # IMG_1958.JPG
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
        "id": "ride_ai_033",  # IMG_1959.JPG
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
        "id": "ride_ai_034",  # IMG_1960.JPG
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
        "id": "ride_ai_035",  # IMG_1961.JPG
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
        "id": "ride_ai_036",  # IMG_1962.JPG
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
        "id": "ride_ai_037",  # IMG_1963.JPG
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
        "id": "ride_ai_038",  # IMG_1964.JPG
        "request_time": time(8, 7),
        "pickup_lat": 26.5442,
        "pickup_lon": 49.9989,
        "pickup_name": "شارع 76622. القطيف 6",
        "dropoff_name": "شارع الأمير محمد بن عبد العزيز 7775. الخبر",
        "price": "61.70 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_039",  # IMG_1965.JPG
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
        "id": "ride_ai_040",  # IMG_1966.JPG
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
        "id": "ride_ai_041",  # IMG_1967.JPG
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
        "id": "ride_ai_042",  # IMG_1968.JPG
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
        "id": "ride_ai_043",  # IMG_1969.JPG
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
        "id": "ride_ai_044",  # IMG_1970.JPG
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
        "id": "ride_ai_045",  # IMG_1971.JPG
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
        "id": "ride_ai_046",  # IMG_1972.JPG
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
        "id": "ride_ai_047",  # IMG_1973.JPG
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
        "id": "ride_ai_048",  # IMG_1974.JPG
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
        "id": "ride_ai_049",  # IMG_1975.JPG
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
        "id": "ride_ai_050",  # IMG_1976.JPG
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
        "id": "ride_ai_051",  # IMG_1977.JPG
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
        "id": "ride_ai_052",  # IMG_1978.JPG
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
        "id": "ride_ai_053",  # IMG_1979.JPG
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
        "id": "ride_ai_054",  # IMG_1980.JPG
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
        "id": "ride_ai_055",  # IMG_1981.JPG
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
        "id": "ride_ai_056",  # IMG_1982.JPG
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
        "id": "ride_ai_057",  # IMG_1983.JPG
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
        "id": "ride_ai_058",  # IMG_1984.JPG
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
        "id": "ride_ai_059",  # IMG_1985.JPG
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
        "id": "ride_ai_060",  # IMG_1986.JPG
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
        "id": "ride_ai_061",  # IMG_1987.JPG
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
        "id": "ride_ai_062",  # IMG_1988.JPG
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
        "id": "ride_ai_063",  # IMG_1989.JPG
        "request_time": time(6, 47),
        "pickup_lat": 26.5427,
        "pickup_lon": 50.0276,
        "pickup_name": "شارع صفوان ابو معدان 3371. القطيف ل",
        "dropoff_name": "شارع 20. الخبر",
        "price": "37.31 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_064",  # IMG_1990.JPG
        "request_time": time(6, 47),
        "pickup_lat": 26.2944,
        "pickup_lon": 50.2063,
        "pickup_name": "شارع 32152. الخبر ة",
        "dropoff_name": "المغيرة بن شعبة 7539. القطيف",
        "price": "49.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_065",  # IMG_1991.JPG
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
        "id": "ride_ai_066",  # IMG_1992.JPG
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
        "id": "ride_ai_067",  # IMG_1993.JPG
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
        "id": "ride_ai_068",  # IMG_1994.JPG
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
        "id": "ride_ai_069",  # IMG_1995.JPG
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
        "id": "ride_ai_070",  # IMG_1996.JPG
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
        "id": "ride_ai_071",  # IMG_1997.JPG
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
        "id": "ride_ai_072",  # IMG_1998.JPG
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
        "id": "ride_ai_073",  # IMG_1999.JPG
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
        "id": "ride_ai_074",  # IMG_2001.JPG
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
        "id": "ride_ai_075",  # IMG_2002.JPG
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
        "id": "ride_ai_076",  # IMG_2003.JPG
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
        "id": "ride_ai_077",  # IMG_2004.JPG
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
        "id": "ride_ai_078",  # IMG_2005.JPG
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
        "id": "ride_ai_079",  # IMG_2006.JPG
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
        "id": "ride_ai_080",  # IMG_2007.JPG
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
        "id": "ride_ai_081",  # IMG_2008.JPG
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
        "id": "ride_ai_082",  # IMG_2009.JPG
        "request_time": time(9, 24),
        "pickup_lat": 26.2779,
        "pickup_lon": 50.1888,
        "pickup_name": "شارع جازان 8645. الخبر",
        "dropoff_name": "اية Nakheel Mall. Dammam",
        "price": "28.71 ر.س",
        "service_type": "Wusool حصري",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_083",  # IMG_2010.JPG
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
        "id": "ride_ai_084",  # IMG_2011.JPG
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
        "id": "ride_ai_085",  # IMG_2012.JPG
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
        "id": "ride_ai_086",  # IMG_2013.JPG
        "request_time": time(4, 47),
        "pickup_lat": 26.3021,
        "pickup_lon": 50.1986,
        "pickup_name": "شارع الثالث والعشرون 3395. الخبر ة",
        "dropoff_name": "3566 Prince Faisal Bin Fahd Road. Doha Al Janubiyah. Az Zahran",
        "price": "19.29 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_087",  # IMG_2014.JPG
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
        "id": "ride_ai_088",  # IMG_2015.JPG
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
        "id": "ride_ai_089",  # IMG_2016.JPG
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
        "id": "ride_ai_090",  # IMG_2017.JPG
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
        "id": "ride_ai_091",  # IMG_2029.JPG
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
        "id": "ride_ai_092",  # IMG_2030.JPG
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
        "id": "ride_ai_093",  # IMG_2031.JPG
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
        "id": "ride_ai_094",  # IMG_2032.JPG
        "request_time": time(13, 12),
        "pickup_lat": 26.4154,
        "pickup_lon": 50.0783,
        "pickup_name": "11 مدينة الملك فيصل الجامعية 3193. الدمام ة",
        "dropoff_name": "شارع العدل 2990. الدمام",
        "price": "36.33 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_095",  # IMG_2033.JPG
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
        "id": "ride_ai_096",  # IMG_2034.JPG
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
        "id": "ride_ai_097",  # IMG_2035.JPG
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
        "id": "ride_ai_098",  # IMG_2036.JPG
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
        "id": "ride_ai_099",  # IMG_2037.JPG
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
        "id": "ride_ai_100",  # IMG_2038.JPG
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
        "id": "ride_ai_101",  # IMG_2039.JPG
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
        "id": "ride_ai_102",  # IMG_2040.JPG
        "request_time": time(4, 58),
        "pickup_lat": 26.2764,
        "pickup_lon": 50.2278,
        "pickup_name": "شارع الجبهاء 6919. الخبر ة",
        "dropoff_name": "شارع 19 6914. الدمام",
        "price": "42.60 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_103",  # IMG_2041.JPG
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
        "id": "ride_ai_104",  # IMG_2042.JPG
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
        "id": "ride_ai_105",  # IMG_2043.JPG
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
        "id": "ride_ai_106",  # IMG_2044.JPG
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
        "id": "ride_ai_107",  # IMG_2045.JPG
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
        "id": "ride_ai_108",  # IMG_2046.JPG
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
        "id": "ride_ai_109",  # IMG_2047.JPG
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
        "id": "ride_ai_110",  # IMG_2048.JPG
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
        "id": "ride_ai_111",  # IMG_2049.JPG
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
        "id": "ride_ai_112",  # IMG_2050.JPG
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
        "id": "ride_ai_113",  # IMG_2051.JPG
        "request_time": time(14, 2),
        "pickup_lat": 26.2899,
        "pickup_lon": 50.1943,
        "pickup_name": "شارع الوادي الاخضر 2164 الخبر ه",
        "dropoff_name": "شارع 17ج 6559. القطيف",
        "price": "64.82 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_114",  # IMG_2052.JPG
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
        "id": "ride_ai_115",  # IMG_2053.JPG
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
        "id": "ride_ai_116",  # IMG_2054.JPG
        "request_time": time(11, 1),
        "pickup_lat": 26.5573,
        "pickup_lon": 50.0292,
        "pickup_name": "طريق أحد 3569. القطيف 6",
        "dropoff_name": "شارع زبير بن العوام 7912. الدمام",
        "price": "44.07 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_117",  # IMG_2055.JPG
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
        "id": "ride_ai_118",  # IMG_2056.JPG
        "request_time": time(11, 5),
        "pickup_lat": 26.5784,
        "pickup_lon": 49.9914,
        "pickup_name": "18 ب 6805. القطيف 6",
        "dropoff_name": "وادي العمارية 6283. الخبر",
        "price": "60.76 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_119",  # IMG_2057.JPG
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
        "id": "ride_ai_120",  # IMG_2058.JPG
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
        "id": "ride_ai_121",  # IMG_2059.JPG
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
        "id": "ride_ai_122",  # IMG_2060.JPG
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
        "id": "ride_ai_123",  # IMG_2061.JPG
        "request_time": time(11, 44),
        "pickup_lat": 25.3955,
        "pickup_lon": 49.5768,
        "pickup_name": "شارع عبد الله الساعدي 3366. الأحساء",
        "dropoff_name": "b Al-Ahsa International Airport (HOF). Hofuf",
        "price": "25.00 ر.س",
        "service_type": "Wusool",
        "shift_type": "رحلة قياسية"
    },
    {
        "id": "ride_ai_124",  # IMG_2062.JPG
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
        "id": "ride_ai_125",  # IMG_2063.JPG
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
        "id": "ride_ai_126",  # IMG_2064.JPG
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
        "id": "ride_ai_127",  # IMG_2065.JPG
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
        "id": "ride_ai_128",  # IMG_2066.JPG
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
        "id": "ride_ai_129",  # IMG_2067.JPG
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
        "id": "ride_ai_130",  # IMG_2068.JPG
        "request_time": time(4, 59),
        "pickup_lat": 26.2836,
        "pickup_lon": 50.1936,
        "pickup_name": "غيلان ابن عقبة 6823. الخبر 6",
        "dropoff_name": "شارع 881424. الدمام",
        "price": "49.38 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_131",  # IMG_2069.JPG
        "request_time": time(15, 5),
        "pickup_lat": 26.3026,
        "pickup_lon": 50.2011,
        "pickup_name": "غيلان ابن عقبة 6823. الخبر ه",
        "dropoff_name": "شارع 881424. الدمام",
        "price": "50.66 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_132",  # IMG_2070.JPG
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
        "id": "ride_ai_133",  # IMG_2071.JPG
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
        "id": "ride_ai_134",  # IMG_2072.JPG
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
        "id": "ride_ai_135",  # IMG_2073.JPG
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
        "id": "ride_ai_136",  # IMG_2074.JPG
        "request_time": time(17, 40),
        "pickup_lat": 26.5589,
        "pickup_lon": 50.0094,
        "pickup_name": "شترع عمار بن يلسر 3075. القطيف",
        "dropoff_name": "شارع 705911. الدمام",
        "price": "34.98 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_137",  # IMG_2075.JPG
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
        "id": "ride_ai_138",  # IMG_2076.JPG
        "request_time": time(13, 8),
        "pickup_lat": 26.5629,
        "pickup_lon": 49.9924,
        "pickup_name": "124 7435. القطيف 6",
        "dropoff_name": "شارع 333313 الخبر",
        "price": "55.86 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_139",  # IMG_2077.JPG
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
        "id": "ride_ai_140",  # IMG_2078.JPG
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
        "id": "ride_ai_141",  # IMG_2079.JPG
        "request_time": time(15, 24),
        "pickup_lat": 26.4388,
        "pickup_lon": 50.0949,
        "pickup_name": "طريق الملك سعود بن عبد العزيز 8867. الخبر ة",
        "dropoff_name": "ب 8202. سيهات",
        "price": "52.60 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_142",  # IMG_2080.JPG
        "request_time": time(6, 13),
        "pickup_lat": 26.4794,
        "pickup_lon": 50.0426,
        "pickup_name": "شارع النسيم 5210. سيهات 6",
        "dropoff_name": "شارع القرية العليا 7245. الخبر",
        "price": "49.44 ر.س",
        "service_type": "Wusool",
        "shift_type": "مشوار طويل (أكثر من 30 دقيقة)"
    },
    {
        "id": "ride_ai_143",  # IMG_2081.JPG
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
        "id": "ride_ai_144",  # IMG_2082.JPG
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
        "id": "ride_ai_145",  # IMG_2083.JPG
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
        "id": "ride_ai_146",  # IMG_2084.JPG
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
        "id": "ride_ai_147",  # IMG_2085.JPG
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
        "id": "ride_ai_148",  # IMG_2086.JPG
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
        "id": "ride_ai_149",  # IMG_2087.JPG
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
        "id": "ride_ai_150",  # IMG_2088.JPG
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
        "id": "ride_ai_151",  # IMG_2089.JPG
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
        "id": "ride
