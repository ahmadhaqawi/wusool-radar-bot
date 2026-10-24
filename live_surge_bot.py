import os
import math
import asyncio
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
    filters
)

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8913904158:AAGlWWCjkRcWWAueE1kHDozOrqjk09v2Wy8"
).strip()

TIMEZONE = pytz.timezone("Asia/Riyadh")
ALERT_RADIUS_KM = 8.0
ACTIVE_WORK_DAYS = [6, 0, 1, 2, 3]

alert_history = {}
registered_chat_ids = set()

HOTSPOTS = [
    {
        "id": "dawn_dammam_west",
        "name": "غرب وشمال الدمام - شارع عمر بن الخطاب",
        "lat": 26.4150, "lon": 50.0520,
        "peak_start": time(4, 30), "notice_start": time(4, 0),
        "target_routes": "رأس تنورة وبقيق والقطيف",
        "expected_price": "40 إلى 70 ريال",
        "tip": "تمركز عند مخارج طريق الجبيل السريع وطريق الظهران"
    },
    {
        "id": "dawn_qatif_to_dammam",
        "name": "القطيف - شارع 15 السريع نحو الدمام",
        "lat": 26.5400, "lon": 50.0200,
        "peak_start": time(5, 0), "notice_start": time(4, 30),
        "target_routes": "شارع عثمان بن عفان ووسط الدمام",
        "expected_price": "38 إلى 45 ريال",
        "tip": "مشاوير فجر سريعة تتجاوز 30 كم خالية من الزحام"
    },
    {
        "id": "dawn_dhahran_to_qatif",
        "name": "الظهران - شارع رابغ نحو طريق أحد بالقطيف",
        "lat": 26.3100, "lon": 50.1350,
        "peak_start": time(5, 15), "notice_start": time(4, 45),
        "target_routes": "طريق أحد وقلب القطيف (40 كم)",
        "expected_price": "44 إلى 48 ريال",
        "tip": "مشوار سفر سريع يربط الظهران بالقطيف في 27 دقيقة"
    },
    {
        "id": "dawn_dammam_aziziyah",
        "name": "غرب الدمام (بن أبي البر) نحو الخبر والعزيزية",
        "lat": 26.4000, "lon": 50.0800,
        "peak_start": time(5, 30), "notice_start": time(5, 0),
        "target_routes": "العزيزية والخبر الجنوبية شارع إبراهيم بن مهران",
        "expected_price": "33 إلى 45 ريال",
        "tip": "خطوط سريعة مفتوحة فجراً لنقل ورديات الشركات"
    },
    {
        "id": "dawn_khobar_baqiq",
        "name": "غرب الخبر - شارع الأمير نايف وطريق بقيق",
        "lat": 26.2800, "lon": 50.1800,
        "peak_start": time(5, 30), "notice_start": time(5, 0),
        "target_routes": "محافظة بقيق ومجمعات الطاقة",
        "expected_price": "80 إلى 105 ريال",
        "tip": "مشاوير سفر طويلة ذات عائد قياسي"
    },
    {
        "id": "morning_dhahran_khobar",
        "name": "الظهران (حي 18) نحو كورنيش وأبراج الخبر",
        "lat": 26.3050, "lon": 50.1400,
        "peak_start": time(6, 45), "notice_start": time(6, 15),
        "target_routes": "شارع الخندق وطريق الأمير فيصل بن فهد بالخبر",
        "expected_price": "27 إلى 35 ريال",
        "tip": "مشاوير سريعة تتيح إنجاز رحلتين متتاليتين في الساعة"
    },
    {
        "id": "morning_dhahran_qatif",
        "name": "الظهران التقنية نحو خالد بن الوليد بالقطيف",
        "lat": 26.3150, "lon": 50.1300,
        "peak_start": time(6, 45), "notice_start": time(6, 15),
        "target_routes": "شارع خالد بن الوليد بالقطيف وسيهات",
        "expected_price": "40 إلى 48 ريال",
        "tip": "نقل الكوادر الإدارية بين مقار الظهران ومحافظة القطيف"
    },
    {
        "id": "morning_qatif_hub",
        "name": "قلب القطيف - شارع ابن النباشي وشارع أحد",
        "lat": 26.5582, "lon": 50.0125,
        "peak_start": time(7, 0), "notice_start": time(6, 30),
        "target_routes": "الدمام (شارع محمد القرطبي) ومستشفيات الخبر",
        "expected_price": "36 إلى 64 ريال",
        "tip": "أعلى كثافة لطلبات موظفات وصول مع بدء الدوام"
    },
    {
        "id": "morning_qatif_awafi",
        "name": "القطيف - شارع العوافي نحو محاور الدمام السريعة",
        "lat": 26.5450, "lon": 50.0150,
        "peak_start": time(7, 0), "notice_start": time(6, 30),
        "target_routes": "الدمام السريع ومجمع الدوائر الحكومية (40 كم)",
        "expected_price": "35 إلى 42 ريال",
        "tip": "مشاوير طويلة تتجاوز 40 كم مع تدفق طلبات وصول حصرية"
    },
    {
        "id": "morning_saihat_dammam",
        "name": "سواحل سيهات وعنك نحو وسط الدمام",
        "lat": 26.4900, "lon": 50.0500,
        "peak_start": time(7, 0), "notice_start": time(6, 30),
        "target_routes": "طريق الخليج ومحاور الأعمال بوسط الدمام",
        "expected_price": "38 إلى 45 ريال",
        "tip": "تدفق مكثف لموظفات وصول من سيهات وعنك باتجاه الدمام"
    },
    {
        "id": "morning_dammam_to_qatif",
        "name": "طريق 1 بالدمام باتجاه القطيف",
        "lat": 26.4600, "lon": 50.0700,
        "peak_start": time(7, 15), "notice_start": time(6, 45),
        "target_routes": "شارع علي الأنصاري بالقطيف ومحاور سيهات",
        "expected_price": "46 إلى 58 ريال",
        "tip": "مشاوير تتجاوز 35 كم بعوائد مرتفعة وتقييم 5 نجوم"
    },
    {
        "id": "midday_dhahran_605",
        "name": "الظهران السريع نحو طريق 605 بالدمام",
        "lat": 26.3200, "lon": 50.1250,
        "peak_start": time(10, 0), "notice_start": time(9, 30),
        "target_routes": "المحاور السريعة نحو وسط وشمال الدمام (54 كم)",
        "expected_price": "45 إلى 60 ريال",
        "tip": "مشاوير طويلة خالية تماماً من الاختناق المروري"
    },
    {
        "id": "midday_khobar_jubail",
        "name": "الخبر (شارع 273914) نحو الجبيل الصناعية",
        "lat": 26.2900, "lon": 50.2050,
        "peak_start": time(11, 15), "notice_start": time(10, 45),
        "target_routes": "الجبيل الصناعية شارع اليمن (130 كم)",
        "expected_price": "105 إلى 125 ريال",
        "tip": "مشوار سفر إقليمي استراتيجي بعائد قياسي يتجاوز 100 ريال"
    },
    {
        "id": "noon_dammam_arterials",
        "name": "غرب الدمام - شارع 26 ب وطريق الملك سعود",
        "lat": 26.4250, "lon": 50.0650,
        "peak_start": time(11, 30), "notice_start": time(11, 0),
        "target_routes": "الدوائر الحكومية والأسواق المركزية بالدمام",
        "expected_price": "30 إلى 45 ريال",
        "tip": "مشاوير حيوية تربط أحياء غرب الدمام بالمحاور المركزية"
    },
    {
        "id": "noon_gulf_road_saihat",
        "name": "طريق الخليج بالدمام ومحور سيهات",
        "lat": 26.4700, "lon": 50.0900,
        "peak_start": time(11, 30), "notice_start": time(11, 0),
        "target_routes": "غرب الدمام شارع طاهر زمخشري وسيهات",
        "expected_price": "22 إلى 32 ريال",
        "tip": "خروج مبكر للورديات قبل زحام المدارس"
    },
    {
        "id": "afternoon_saihat_local",
        "name": "سيهات الداخلية - شارع عبدالعزيز القاضي والغدير",
        "lat": 26.4850, "lon": 50.0450,
        "peak_start": time(13, 45), "notice_start": time(13, 15),
        "target_routes": "أحياء غرناطة والشارع 15 ومحيط سيهات",
        "expected_price": "15 إلى 22 ريال",
        "tip": "مشاوير سريعة بدقائق معدودة تحقق معدل دوران مرتفع"
    },
    {
        "id": "noon_khobar_business",
        "name": "الخبر - طريق الأمير فيصل بن فهد وشارع مكة",
        "lat": 26.2950, "lon": 50.2105,
        "peak_start": time(12, 30), "notice_start": time(12, 0),
        "target_routes": "القطيف وسيهات وغرب الدمام عودة الموظفات",
        "expected_price": "45 إلى 65 ريال",
        "tip": "تمركز قرب الأبراج التجارية والمستشفيات الخاصة بالخبر"
    },
    {
        "id": "afternoon_dammam_to_khobar",
        "name": "وسط الدمام نحو شارع الأمير منصور بالخبر",
        "lat": 26.4100, "lon": 50.1000,
        "peak_start": time(14, 0), "notice_start": time(13, 30),
        "target_routes": "شارع الأمير منصور بالخبر والمجمعات الإدارية",
        "expected_price": "26 إلى 35 ريال",
        "tip": "حركة نشطة بين الدمام والخبر بعد انتهاء دوام الدوائر"
    },
    {
        "id": "evening_dammam_hospitals",
        "name": "الدمام الطبية - شارع 11 ومحيط مستشفى المانع وتداوي",
        "lat": 26.4350, "lon": 50.1050,
        "peak_start": time(16, 15), "notice_start": time(15, 45),
        "target_routes": "المزروعية والخالدية وطريق الخليج بالدمام",
        "expected_price": "22 إلى
