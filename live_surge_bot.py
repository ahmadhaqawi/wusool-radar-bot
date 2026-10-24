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

    # --- 3. نافذة منتصف النهار والمدارس (10:00 ص - 01:30 م) ---
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

    # --- 4. نافذة خروج الموظفات والظهيرة (01:30 م - 03:45 م) ---
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

    # --- 5. نافذة الذروة المسائية والمستشفيات (04:00 م - 07:00 م) ---
    {
        "id": "evening_dammam_hospitals",
        "name": "الدمام الطبية - شارع 11 ومحيط مستشفى المانع وتداوي",
        "lat": 26.4350, "lon": 50.1050,
        "peak_start": time(16, 15), "notice_start": time(15, 45),
        "target_routes": "المزروعية والخالدية وطريق الخليج بالدمام",
        "expected_price": "22 إلى 28 ريال",
        "tip": "تبديل ورديات الكادر الصحي ونقل موظفات وصول"
    },
    {
        "id": "evening_qatif_local",
        "name": "القطيف - شارع الأمير مساعد والحارث التميمي",
        "lat": 26.5600, "lon": 50.0100,
        "peak_start": time(16, 30), "notice_start": time(16, 0),
        "target_routes": "طريق أحد وطريق الخليج وأحياء القطيف الداخلية",
        "expected_price": "14 إلى 22 ريال",
        "tip": "طلبات وصول حصرية سريعة بكثافة عالية في وقت العصر"
    },
    {
        "id": "evening_khobar_to_saihat",
        "name": "الخبر (طريق الملك سعود) نحو سيهات (شارع 6 ب)",
        "lat": 26.2900, "lon": 50.2100,
        "peak_start": time(17, 0), "notice_start": time(16, 30),
        "target_routes": "سيهات والقطيف وغرب الدمام (عودة الموظفات)",
        "expected_price": "55 إلى 65 ريال",
        "tip": "مشوار ذهبي بطول 36 كم وعائد يتجاوز 60 ريالاً في ذروة المساء"
    },

    # --- 6. نافذة السهر والرحلات الساحلية (11:00 م - 02:30 ص) ---
    {
        "id": "night_corniche_dammam_saihat",
        "name": "طريق الخليج وسواحل الدمام وسيهات",
        "lat": 26.4750, "lon": 50.0950,
        "peak_start": time(23, 0), "notice_start": time(22, 30),
        "target_routes": "الشاطئ الغربي والجوهرة وكورنيش الدمام",
        "expected_price": "10 إلى 18 ريال",
        "tip": "مشاوير تنقل خفيفة وسريعة على امتداد الساحل ليلاً"
    },
    {
        "id": "night_khobar_qatif",
        "name": "كورنيش الخبر (شارع 62552) نحو القطيف",
        "lat": 26.3050, "lon": 50.2300,
        "peak_start": time(1, 45), "notice_start": time(1, 15),
        "target_routes": "القطيف شارع أحمد عيسى المرشدي وسيهات (42 كم)",
        "expected_price": "58 إلى 70 ريال",
        "tip": "شوارع سريعة خالية من الزحام وعوائد مرتفعة لطلبات السهر"
    }
]

# ==============================================================================
# 3. الدوال الحسابية وخادم فحص الصحة لمنصة Render
# ==============================================================================
def calculate_distance(lat1, lon1, lat2, lon2):
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Wusool Radar Active (Sun-Thu)".encode("utf-8"))

    def log_message(self, format, *args):
        return

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# ==============================================================================
# 4. مراقبة الموقع المباشر وتنبيه الاقتراب الميداني
# ==============================================================================
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.edited_message or update.message
    if not msg or not msg.location:
        return

    chat_id = msg.chat_id
    registered_chat_ids.add(chat_id)
    now = datetime.now(TIMEZONE)

    # التحقق: إيقاف التنبيهات يومي الجمعة والسبت
    if now.weekday() not in ACTIVE_WORK_DAYS:
        return

    curr = now.time()

    for spot in HOTSPOTS:
        if spot["notice_start"] <= spot["peak_start"]:
            in_win = spot["notice_start"] <= curr < spot["peak_start"]
        else:
            in_win = curr >= spot["notice_start"] or curr < spot["peak_start"]

        if in_win:
            dist = calculate_distance(msg.location.latitude, msg.location.longitude, spot["lat"], spot["lon"])
            key = f"live_{chat_id}_{spot['id']}_{now.strftime('%Y%m%d_%H')}"
            if dist <= ALERT_RADIUS_KM and key not in alert_history:
                alert_history[key] = True
                alert = (
                    "🎯 تنبيه رادار وصول: ذروة قريبة منك!\n\n"
                    f"📍 الموقع: {spot['name']}\n"
                    f"📏 المسافة منك: {dist:.1f} كم\n"
                    f"⏰ بدء الذروة: {spot['peak_start'].strftime('%I:%M %p')}\n"
                    f"🛣 الوجهات المتوقعة: {spot['target_routes']}\n"
                    f"💰 العائد المتوقع: {spot['expected_price']}\n\n"
                    f"💡 توجيه: {spot['tip']}"
                )
                await context.bot.send_message(chat_id=chat_id, text=alert)

# ==============================================================================
# 5. التنبيهات المجدولة الاستباقية (قبل 30 دقيقة من كل ذروة)
# ==============================================================================
async def scheduled_monitor(app):
    while True:
        try:
            now = datetime.now(TIMEZONE)
            if now.weekday() in ACTIVE_WORK_DAYS:
                curr = now.time()
                for spot in HOTSPOTS:
                    if curr.hour == spot["notice_start"].hour and curr.minute == spot["notice_start"].minute:
                        cron_key = f"cron_{spot['id']}_{now.strftime('%Y%m%d_%H%M')}"
                        if cron_key not in alert_history:
                            alert_history[cron_key] = True
                            broadcast = (
                                "⏰ تنبيه دوام وصول: ذروة تبدأ بعد 30 دقيقة!\n\n"
                                f"📍 الموقع: {spot['name']}\n"
                                f"⏳ الموعد: {spot['peak_start'].strftime('%I:%M %p')}\n"
                                f"🛣 الوجهات: {spot['target_routes']}\n"
                                f"💵 السعر التقديري: {spot['expected_price']}\n\n"
                                f"🧭 الخطة: {spot['tip']}"
                            )
                            for cid in list(registered_chat_ids):
                                try:
                                    await app.bot.send_message(chat_id=cid, text=broadcast)
                                except Exception:
                                    pass
        except Exception:
            pass
        await asyncio.sleep(30)

# ==============================================================================
# 6. الأوامر التفاعلية
# ==============================================================================
async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    registered_chat_ids.add(update.effective_chat.id)
    now = datetime.now(TIMEZONE)
    days_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    day_ar = days_ar[now.weekday()]
    status = "يوم عمل رسمي (أحد-خميس)" if now.weekday() in ACTIVE_WORK_DAYS else "عطلة نهاية الأسبوع"

    await update.message.reply_text(
        f"🔔 [فحص إشعار تجريبي ناجح!]\n\n"
        f"📅 اليوم الحالي: {day_ar} ({status})\n"
        f"📍 إجمالي النقاط الساخنة المعتمدة: {len(HOTSPOTS)} نقطة\n"
        "الرادار متصل بنجاح وجاهز لاستقبال موقعك المباشر في أيام العمل."
    )

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    registered_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text(
        "🚖 رادار وصول الشرقية الشامل نشط الآن!\n\n"
        "📅 جدول العمل: من الأحد إلى الخميس فقط.\n\n"
        "1. أرسل /test لتجربة التنبيه والصوت فوراً.\n"
        "2. شارك الموقع المباشر (Live Location) لمدة 8 ساعات قبل بدء الوردية."
    )

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TIMEZONE)
    days_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    day_ar = days_ar[now.weekday()]
    active_str = "مفعّل (يوم عمل)" if now.weekday() in ACTIVE_WORK_DAYS else "متوقف مؤقتاً (إجازة أسبوعية)"
    await update.message.reply_text(
        f"✅ حالة الرادار:\n"
        f"📅 اليوم: {day_ar} ({active_str})\n"
        f"🕒 التوقيت: {now.strftime('%I:%M:%S %p')}\n"
        f"📍 نطاق التنبيه الميداني: {ALERT_RADIUS_KM} كم\n"
        f"🎯 عدد المواقع المراقبة: {len(HOTSPOTS)} موقعاً"
    )

async def hotspots_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 دليل النقاط الساخنة المعتمدة (الأحد - الخميس):\n\n"
    for s in HOTSPOTS:
        text += (
            f"🔹 {s['name']}\n"
            f"⏰ الذروة: {s['peak_start'].strftime('%I:%M %p')} (تنبيه: {s['notice_start'].strftime('%I:%M %p')})\n"
            f"💰 المتوقع: {s['expected_price']}\n"
            f"🛣 الوجهات: {s['target_routes']}\n\n"
        )
    await update.message.reply_text(text)

# ==============================================================================
# 7. نقطة البدء
# ==============================================================================
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("hotspots", hotspots_cmd))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))

    loop = asyncio.get_event_loop()
    loop.create_task(scheduled_monitor(app))

    app.run_polling()

if __name__ == "__main__":
    main()
