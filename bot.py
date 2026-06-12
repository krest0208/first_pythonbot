import asyncio
import logging
import re
import json
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ========== ТОКЕН (ВСТАВЬ СВОЙ) ==========
TOKEN = "8517689872:AAGfe2bFZE932QdzRQfDJu2K_-VYC8phIuY"
# =========================================

MASTER_ID = 1794103751
SERVICE_DURATION = 30

logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect('bookings.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            service TEXT,
            master TEXT,
            date TEXT,
            date_display TEXT,
            time TEXT,
            created_at TEXT,
            from_site INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active'
        )
    ''')
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

def save_booking(user_id, user_name, service, master, date, date_display, time, from_site=0):
    conn = sqlite3.connect('bookings.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO appointments (user_id, user_name, service, master, date, date_display, time, created_at, from_site)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, user_name, service, master, date, date_display, time, datetime.now().strftime("%d.%m.%Y %H:%M"), from_site))
    conn.commit()
    booking_id = cursor.lastrowid
    conn.close()
    return booking_id

def get_user_bookings(user_id):
    conn = sqlite3.connect('bookings.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, service, master, date_display, time, created_at
        FROM appointments
        WHERE user_id = ? AND status = 'active'
        ORDER BY date, time
    ''', (user_id,))
    result = cursor.fetchall()
    conn.close()
    return result

def get_all_bookings():
    conn = sqlite3.connect('bookings.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_name, service, master, date_display, time, created_at, from_site
        FROM appointments
        WHERE status = 'active'
        ORDER BY id DESC
    ''')
    result = cursor.fetchall()
    conn.close()
    return result

def cancel_booking_db(booking_id, user_id):
    conn = sqlite3.connect('bookings.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE appointments SET status = 'cancelled'
        WHERE id = ? AND user_id = ?
    ''', (booking_id, user_id))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

def is_slot_free(master, date, time):
    conn = sqlite3.connect('bookings.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM appointments
        WHERE master = ? AND date = ? AND time = ? AND status = 'active'
    ''', (master, date, time))
    count = cursor.fetchone()[0]
    conn.close()
    return count == 0

def get_free_slots(master, date):
    conn = sqlite3.connect('bookings.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT time FROM appointments
        WHERE master = ? AND date = ? AND status = 'active'
    ''', (master, date))
    busy = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    all_slots = []
    for hour in range(9, 21):
        if hour < 20:
            all_slots.append(f"{hour:02d}:00")
            all_slots.append(f"{hour:02d}:30")
        else:
            all_slots.append(f"20:00")
    
    free = [s for s in all_slots if s not in busy]
    return free

# Инициализация БД
init_db()

# ========== УСЛУГИ ==========
SERVICES = {
    "man_haircut": "💇‍♂️ Мужская стрижка",
    "woman_haircut": "💇‍♀️ Женская стрижка",
    "coloring": "🎨 Окрашивание",
    "styling": "✨ Укладка",
    "manicure": "💅 Маникюр",
}

PRICES = {
    "man_haircut": 800,
    "woman_haircut": 1500,
    "coloring": 3000,
    "styling": 1000,
    "manicure": 1200,
}

MASTERS = ["Анна", "Елена"]

greeted_users = set()
reminders_sent = set()

class Booking(StatesGroup):
    service = State()
    master = State()
    date = State()
    time = State()

# ========== КЛАВИАТУРЫ ==========
def get_main_menu_kb():
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Новая запись")],
            [KeyboardButton(text="📋 Мои записи")],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )
    return kb

def get_services_kb():
    kb = []
    for key in SERVICES:
        kb.append([InlineKeyboardButton(text=f"{SERVICES[key]} — {PRICES[key]}₽", callback_data=f"svc_{key}")])
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_masters_kb():
    kb = []
    for m in MASTERS:
        kb.append([InlineKeyboardButton(text=m, callback_data=f"mst_{m}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_services")])
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_date_kb():
    kb = [
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="date_today")],
        [InlineKeyboardButton(text="📅 Завтра", callback_data="date_tomorrow")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_masters")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_time_kb(master, date):
    free_slots = get_free_slots(master, date)
    buttons = [InlineKeyboardButton(text=slot, callback_data=f"time_{slot}") for slot in free_slots]
    rows = [buttons[i:i+3] for i in range(0, len(buttons), 3)]
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    markup.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_date")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return markup

def get_free_slots_text(master, date):
    free = get_free_slots(master, date)
    if not free:
        return "❌ На сегодня всё занято"
    text = "🟢 Свободные окна:\n"
    for slot in free:
        text += f"   • {slot}\n"
    return text

# ========== НАПОМИНАНИЯ ==========
async def reminder_checker():
    while True:
        try:
            now = datetime.now()
            current_date = now.strftime("%d.%m.%Y")
            conn = sqlite3.connect('bookings.db')
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, user_id, service, master, date_display, time
                FROM appointments
                WHERE date = ? AND status = 'active'
            ''', (current_date,))
            apps = cursor.fetchall()
            conn.close()
            
            for app in apps:
                key = f"{app[0]}"
                if key in reminders_sent:
                    continue
                app_hour = int(app[5].split(':')[0])
                app_min = int(app[5].split(':')[1])
                reminder_hour = app_hour - 1
                if now.hour == reminder_hour and now.minute == app_min:
                    await bot.send_message(
                        app[1],
                        f"⏰ <b>НАПОМИНАНИЕ!</b>\n\n"
                        f"Через час у вас {SERVICES[app[2]]} у {app[3]}.\n"
                        f"📅 {app[4]}\n"
                        f"⏰ {app[5]}",
                        parse_mode="HTML"
                    )
                    reminders_sent.add(key)
        except Exception as e:
            print(f"Ошибка напоминаний: {e}")
        await asyncio.sleep(60)

# ========== ОБРАБОТЧИК ЗАПИСЕЙ С САЙТА ==========
@dp.message(lambda message: message.text and message.text.startswith("BOOKING_FROM_SITE:"))
async def handle_site_booking(message: types.Message):
    try:
        data_str = message.text.replace("BOOKING_FROM_SITE:", "")
        data = json.loads(data_str)
        
        client_name = data.get("client_name")
        client_telegram = data.get("client_telegram")
        service = data.get("service")
        master = data.get("master")
        date = data.get("date")
        time = data.get("time")
        
        service_names = {
            "man_haircut": "Мужская стрижка",
            "woman_haircut": "Женская стрижка",
            "coloring": "Окрашивание",
            "styling": "Укладка",
            "manicure": "Маникюр"
        }
        prices = {
            "man_haircut": 800,
            "woman_haircut": 1500,
            "coloring": 3000,
            "styling": 1000,
            "manicure": 1200
        }
        
        service_name = service_names.get(service, service)
        price = prices.get(service, 0)
        
        if not is_slot_free(master, date, time):
            await message.answer("❌ Это время уже занято!")
            return
        
        save_booking(MASTER_ID, client_name, service, master, date, date, time, from_site=1)
        
        await bot.send_message(
            MASTER_ID,
            f"🔔 <b>НОВАЯ ЗАПИСЬ С САЙТА!</b>\n\n"
            f"👤 Клиент: {client_name}\n"
            f"📱 Telegram: {client_telegram}\n"
            f"💇 Услуга: {service_name} — {price}₽\n"
            f"👤 Мастер: {master}\n"
            f"📅 Дата: {date}\n"
            f"⏰ Время: {time}",
            parse_mode="HTML"
        )
        
        if client_telegram and client_telegram != "не указан":
            try:
                clean_telegram = client_telegram.replace("@", "")
                await bot.send_message(
                    clean_telegram,
                    f"✅ <b>Вы записаны в салон «Анна Стилист»!</b>\n\n"
                    f"💇 Услуга: {service_name}\n"
                    f"👤 Мастер: {master}\n"
                    f"📅 Дата: {date}\n"
                    f"⏰ Время: {time}\n\n"
                    f"📍 г. Шахты, ул. Советская, 15\n\n"
                    f"Ждём вас! 🔔",
                    parse_mode="HTML"
                )
            except:
                pass
        
        print(f"[✓] Запись с сайта: {client_name} -> {service_name} {date} {time}")
        
    except Exception as e:
        print(f"[×] Ошибка обработки записи с сайта: {e}")

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    if user_id not in greeted_users:
        greeted_users.add(user_id)
        await message.answer(
            "<b>Добро пожаловать в салон «Анна Стилист»!</b>\n\n"
            "Я помогу вам записаться на услугу.\n\n"
            "<b>Что я умею:</b>\n"
            "• Запись на стрижку, маникюр и другие услуги\n"
            "• Выбор мастера (Анна или Елена)\n"
            "• Выбор даты (сегодня/завтра)\n"
            "• Выбор времени (кнопками)\n"
            "• Напоминание о записи за час\n\n"
            "👇 <b>Нажмите кнопку «📅 Новая запись»</b>",
            parse_mode="HTML",
            reply_markup=get_main_menu_kb()
        )
    else:
        await message.answer(
            "✂️ <b>Анна Стилист</b>\n\nДобро пожаловать!\nВыберите услугу:",
            parse_mode="HTML",
            reply_markup=get_services_kb()
        )
        await state.set_state(Booking.service)

@dp.message(lambda message: message.text == "📅 Новая запись")
async def new_booking(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "✂️ <b>Анна Стилист</b>\n\nВыберите услугу:",
        parse_mode="HTML",
        reply_markup=get_services_kb()
    )
    await state.set_state(Booking.service)

@dp.message(lambda message: message.text == "📋 Мои записи")
async def show_my_appointments(message: types.Message):
    await my_appointments(message)

@dp.message(lambda message: message.text == "❌ Отмена")
async def cancel_from_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено. /start", reply_markup=get_main_menu_kb())

@dp.callback_query(Booking.service)
async def cb_service(call: types.CallbackQuery, state: FSMContext):
    if call.data == "cancel":
        await call.message.edit_text("❌ Отменено. /start", reply_markup=get_main_menu_kb())
        await state.clear()
        await call.answer()
        return
    
    if call.data.startswith("svc_"):
        service_key = call.data[4:]
        await state.update_data(service=service_key)
        await call.message.edit_text("💇 Выберите мастера:", reply_markup=get_masters_kb())
        await state.set_state(Booking.master)
    await call.answer()

@dp.callback_query(Booking.master)
async def cb_master(call: types.CallbackQuery, state: FSMContext):
    if call.data == "cancel":
        await call.message.edit_text("❌ Отменено. /start", reply_markup=get_main_menu_kb())
        await state.clear()
        await call.answer()
        return
    
    if call.data == "back_services":
        await call.message.edit_text("✂️ Выберите услугу:", reply_markup=get_services_kb())
        await state.set_state(Booking.service)
        await call.answer()
        return
    
    if call.data.startswith("mst_"):
        master_name = call.data[4:]
        await state.update_data(master=master_name)
        await call.message.edit_text("📅 Выберите дату:", reply_markup=get_date_kb())
        await state.set_state(Booking.date)
    await call.answer()

@dp.callback_query(Booking.date)
async def cb_date(call: types.CallbackQuery, state: FSMContext):
    if call.data == "cancel":
        await call.message.edit_text("❌ Отменено. /start", reply_markup=get_main_menu_kb())
        await state.clear()
        await call.answer()
        return
    
    if call.data == "back_masters":
        await call.message.edit_text("💇 Выберите мастера:", reply_markup=get_masters_kb())
        await state.set_state(Booking.master)
        await call.answer()
        return
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    if call.data == "date_today":
        date_obj = today
    elif call.data == "date_tomorrow":
        date_obj = today + timedelta(days=1)
    else:
        await call.answer()
        return
    
    date_str = date_obj.strftime("%d.%m.%Y")
    date_display = f"{date_obj.day}.{date_obj.month}"
    await state.update_data(date=date_str, date_display=date_display)
    
    data = await state.get_data()
    free_slots_text = get_free_slots_text(data["master"], date_str)
    
    await call.message.edit_text(
        f"✅ Дата: {date_display}\n\n"
        f"⏰ Выберите время:\n\n{free_slots_text}",
        reply_markup=get_time_kb(data["master"], date_str)
    )
    await state.set_state(Booking.time)
    await call.answer()

@dp.callback_query(Booking.time)
async def cb_time(call: types.CallbackQuery, state: FSMContext):
    if call.data == "cancel":
        await call.message.edit_text("❌ Отменено. /start", reply_markup=get_main_menu_kb())
        await state.clear()
        await call.answer()
        return
    
    if call.data == "back_date":
        await call.message.edit_text("📅 Выберите дату:", reply_markup=get_date_kb())
        await state.set_state(Booking.date)
        await call.answer()
        return
    
    if call.data.startswith("time_"):
        time_str = call.data[5:]
        data = await state.get_data()
        
        if not is_slot_free(data["master"], data["date"], time_str):
            free_slots_text = get_free_slots_text(data["master"], data["date"])
            await call.message.edit_text(
                f"❌ {data['master']} уже занята в {time_str}!\n\n{free_slots_text}\n\nВыберите другое время:",
                reply_markup=get_time_kb(data["master"], data["date"])
            )
            await call.answer()
            return
        
        booking_id = save_booking(
            call.from_user.id,
            call.from_user.full_name,
            data["service"],
            data["master"],
            data["date"],
            data["date_display"],
            time_str,
            from_site=0
        )
        
        service_name = SERVICES[data["service"]]
        price = PRICES[data["service"]]
        time_minutes = int(time_str.split(':')[0]) * 60 + int(time_str.split(':')[1])
        end_time = f"{(time_minutes + SERVICE_DURATION) // 60:02d}:{(time_minutes + SERVICE_DURATION) % 60:02d}"
        
        await call.message.edit_text(
            f"✅ <b>ЗАПИСЬ ОФОРМЛЕНА!</b>\n\n"
            f"💇 {service_name}\n"
            f"💰 {price} ₽\n"
            f"👤 {data['master']}\n"
            f"📅 {data['date_display']}\n"
            f"⏰ {time_str} — {end_time}\n\n"
            f"🔔 Я напомню о записи за час.\n\n"
            f"Номер записи: #{booking_id}",
            parse_mode="HTML"
        )
        
        await call.message.answer("🏠 Главное меню:", reply_markup=get_main_menu_kb())
        
        # Уведомление мастеру
        try:
            await bot.send_message(
                MASTER_ID,
                f"🔔 <b>НОВАЯ ЗАПИСЬ ИЗ БОТА!</b>\n\n"
                f"👤 {call.from_user.full_name}\n"
                f"💇 {service_name}\n"
                f"💰 {price} ₽\n"
                f"👤 {data['master']}\n"
                f"📅 {data['date_display']}\n"
                f"⏰ {time_str} — {end_time}",
                parse_mode="HTML"
            )
        except:
            pass
        
        await state.clear()
        await call.answer()

# ========== КОМАНДЫ ДЛЯ КЛИЕНТА ==========
@dp.message(Command("my"))
async def my_appointments(message: types.Message):
    bookings = get_user_bookings(message.from_user.id)
    if not bookings:
        await message.answer("📭 Нет записей. /start", reply_markup=get_main_menu_kb())
        return
    
    text = "📋 <b>Ваши записи</b>\n\n"
    for b in bookings:
        service_name = SERVICES[b[1]]
        price = PRICES[b[1]]
        text += f"<b>#{b[0]}</b>\n"
        text += f"💇 {service_name} — {price}₽\n"
        text += f"👤 {b[2]}\n"
        text += f"📅 {b[3]}\n"
        text += f"⏰ {b[4]}\n"
        text += f"🕐 {b[5]}\n\n"
    
    text += "Чтобы отменить запись, напишите: /cancel_booking НОМЕР"
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu_kb())

@dp.message(Command("cancel_booking"))
async def cancel_booking(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ Используйте: /cancel_booking НОМЕР_ЗАПИСИ\n\nНомер записи можно посмотреть в /my")
        return
    
    try:
        booking_id = int(parts[1])
    except:
        await message.answer("❌ Номер должен быть числом")
        return
    
    if cancel_booking_db(booking_id, message.from_user.id):
        reminders_sent.discard(str(booking_id))
        await message.answer(f"✅ Запись #{booking_id} отменена!", reply_markup=get_main_menu_kb())
        
        try:
            await bot.send_message(MASTER_ID, f"⚠️ <b>ЗАПИСЬ ОТМЕНЕНА!</b>\n\nНомер: #{booking_id}", parse_mode="HTML")
        except:
            pass
    else:
        await message.answer("❌ Запись не найдена или это не ваша запись")

# ========== КОМАНДЫ ДЛЯ МАСТЕРА ==========
@dp.message(Command("admin"))
async def admin_view(message: types.Message):
    if message.from_user.id != MASTER_ID:
        await message.answer("⛔ Нет доступа")
        return
    
    bookings = get_all_bookings()
    if not bookings:
        await message.answer("📭 Нет записей")
        return
    
    text = "📊 <b>ВСЕ ЗАПИСИ</b>\n\n"
    for b in bookings:
        source = "🌐 Сайт" if b[7] else "🤖 Бот"
        service_name = SERVICES[b[2]]
        price = PRICES[b[2]]
        text += f"<b>#{b[0]}</b> {source}\n"
        text += f"👤 {b[1]}\n"
        text += f"💇 {service_name} — {price}₽\n"
        text += f"👤 {b[3]}\n"
        text += f"📅 {b[4]}\n"
        text += f"⏰ {b[5]}\n"
        text += f"🕐 {b[6]}\n\n"
        
        if len(text) > 3500:
            await message.answer(text, parse_mode="HTML")
            text = ""
    if text:
        await message.answer(text, parse_mode="HTML")

@dp.message(Command("cancel"))
async def cancel_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено. /start", reply_markup=get_main_menu_kb())

async def main():
    print("✅ БОТ ЗАПУЩЕН!")
    print("📦 База данных SQLite подключена")
    print("🔒 Защита от двойных записей включена")
    print("🔔 Напоминания о записях включены (за час)")
    print("🌐 Поддержка записей с сайта включена")
    
    asyncio.create_task(reminder_checker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())