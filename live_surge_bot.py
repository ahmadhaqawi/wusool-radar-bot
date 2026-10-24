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

# ==============================================================================
# 1. الإعدادات والمتغيرات العامة
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8913904158:AAGlWWCjkRcWWAueE1kHDozOrqjk09v2Wy8"
).strip()

TIMEZONE = pytz.timezone("Asia/Riyadh")
ALERT_RADIUS_KM = 8.0

# تفعيل التنبيهات لأيام العمل الرسمية فقط (من الأحد إلى الخميس):
# 6: الأحد | 0: الإثنين | 1: الثلاثاء | 2: الأربعاء | 3: الخميس
ACTIVE_WORK_DAYS = [6, 0, 1, 2, 3]

alert_history = {}
registered_chat_ids = set()

# ==============================================================================
# 2. قاعدة بيانات النقاط الساخنة الـ 21 الشاملة
# ==============================================================================
HOTSPOTS = [
    # --- 1. نافذة الفجر والورديات الباكرة (04:30 ص - 06:15 ص) ---
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

    # --- 2. نافذة دوامات الصباح الرسمية (06:30 ص - 08:30 ص) ---
    {
        "id": "morning_dhahran_khobar",
        "name": "الظهران (حي 18) نحو كورنيش وأبراج الخبر",
        "lat": 26.3050, "lon": 50.1400,
        "peak_start": time(6
