import asyncio
import logging
import re
import json
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

appointments = []
next_id = 1
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

def get_time_kb():
    buttons = []
    for hour in range(9, 21):
        buttons.append(InlineKeyboardButton(text=f"{hour:02d}:00", callback_data=f"time_{hour:02d}:00"))
        if hour < 20:
            buttons.append(InlineKeyboardButton(text=f"{hour:02d}:30", callback_data=f"time_{hour:02d}:30"))
    
    rows = [buttons[i:i+3] for i in range(0, len(buttons), 3)]
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    markup.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_date")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return markup

# ========== ФУНКЦИИ ==========
def time_to_minutes(time_str: str) -> int:
    try:
        h, m = map(int, time_str.split(':'))
        return h * 60 + m
    except:
        return -1

def is_slot_occupied(master: str, date: str, time_str: str) -> bool:
    t = time_to_minutes(time_str)
    for app in appointments:
        if app["master"] == master and app["date"] == date:
            bt = time_to_minutes(app["time"])
            if abs(t - bt) < SERVICE_DURATION:
                return True
    return False

def get_free_slots_text(master: str, date: str) -> str:
    busy = []
    for app in appointments:
        if app["master"] == master and app["date"] == date:
            busy.append(time_to_minutes(app["time"]))
    
    if not busy:
        return "✅ Весь день свободен (9:00-20:00)"
    
    busy.sort()
    free = []
    current = 9 * 60
    for b in busy:
        if current + SERVICE_DURATION <= b:
            free.append((current, b))
        current = max(current, b + SERVICE_DURATION)
    if current < 20 * 60:
        free.append((current, 20 * 60))
    
    if not free:
        return "❌ На сегодня всё занято"
    
    text = "🟢 Свободные окна:\n"
    for s, e in free:
        text += f"   • {s//60:02d}:{s%60:02d} - {e//60:02d}:{e%60:02d}\n"
    return text

# ========== НАПОМИНАНИЯ ==========
async def reminder_checker():
    while True:
        try:
            now = datetime.now()
            current_date = now.strftime("%d.%m.%Y")
            for app in appointments:
                key = f"{app['id']}"
                if key in reminders_sent:
                    continue
                if app["date"] == current_date:
                    app_hour = int(app["time"].split(':')[0])
                    app_min = int(app["time"].split(':')[1])
                    reminder_hour = app_hour - 1
                    if now.hour == reminder_hour and now.minute == app_min:
                        await bot.send_message(
                            app["user_id"],
                            f"⏰ <b>НАПОМИНАНИЕ!</b>\n\n"
                            f"Через час у вас {SERVICES[app['service']]} у {app['master']}.\n"
                            f"📅 {app['date_display']}\n"
                            f"⏰ {app['time']}",
                            parse_mode="HTML"
                        )
                        reminders_sent.add(key)
        except:
            pass
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
        
        # Сохраняем запись в список
        global next_id
        booking_id = next_id
        next_id += 1
        
        appointments.append({
            "id": booking_id,
            "user_id": MASTER_ID,
            "user_name": client_name,
            "service": service,
            "master": master,
            "date": date,
            "date_display": date,
            "time": time,
            "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "from_site": True
        })
        
        # Уведомление мастеру
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
        
        # Уведомление клиенту (если указан Telegram)
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

# ========== ОБРАБОТЧИКИ КНОПОК ==========
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
    free_slots = get_free_slots_text(data["master"], date_str)
    
    await call.message.edit_text(
        f"✅ Дата: {date_display}\n\n"
        f"⏰ Выберите время:\n\n{free_slots}",
        reply_markup=get_time_kb()
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
        
        if is_slot_occupied(data["master"], data["date"], time_str):
            free_slots = get_free_slots_text(data["master"], data["date"])
            await call.message.edit_text(
                f"❌ {data['master']} уже занята в {time_str}!\n\n{free_slots}\n\nВыберите другое время:",
                reply_markup=get_time_kb()
            )
            await call.answer()
            return
        
        global next_id
        booking_id = next_id
        next_id += 1
        
        appointments.append({
            "id": booking_id,
            "user_id": call.from_user.id,
            "user_name": call.from_user.full_name,
            "service": data["service"],
            "master": data["master"],
            "date": data["date"],
            "date_display": data["date_display"],
            "time": time_str,
            "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "from_site": False
        })
        
        service_name = SERVICES[data["service"]]
        price = PRICES[data["service"]]
        
        await call.message.edit_text(
            f"✅ <b>ЗАПИСЬ ОФОРМЛЕНА!</b>\n\n"
            f"💇 {service_name}\n"
            f"💰 {price} ₽\n"
            f"👤 {data['master']}\n"
            f"📅 {data['date_display']}\n"
            f"⏰ {time_str}\n\n"
            f"🔔 Я напомню о записи за час.",
            parse_mode="HTML"
        )
        
        await call.message.answer("🏠 Главное меню:", reply_markup=get_main_menu_kb())
        
        # Уведомление мастеру (для записей из бота)
        try:
            await bot.send_message(
                MASTER_ID,
                f"🔔 <b>НОВАЯ ЗАПИСЬ ИЗ БОТА!</b>\n\n"
                f"👤 {call.from_user.full_name}\n"
                f"💇 {service_name}\n"
                f"💰 {price} ₽\n"
                f"👤 {data['master']}\n"
                f"📅 {data['date_display']}\n"
                f"⏰ {time_str}",
                parse_mode="HTML"
            )
        except:
            pass
        
        await state.clear()
        await call.answer()

# ========== КОМАНДЫ ДЛЯ КЛИЕНТА ==========
@dp.message(Command("my"))
async def my_appointments(message: types.Message):
    user_apps = [a for a in appointments if a["user_id"] == message.from_user.id]
    if not user_apps:
        await message.answer("📭 Нет записей. /start", reply_markup=get_main_menu_kb())
        return
    
    text = "📋 <b>Ваши записи</b>\n\n"
    for a in user_apps:
        text += f"<b>#{a['id']}</b>\n"
        text += f"💇 {SERVICES[a['service']]} — {PRICES[a['service']]}₽\n"
        text += f"👤 {a['master']}\n"
        text += f"📅 {a['date_display']}\n"
        text += f"⏰ {a['time']}\n"
        text += f"🕐 Записано: {a['created_at']}\n\n"
    
    text += "\nЧтобы отменить запись, напишите: /cancel_booking НОМЕР"
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
    
    booking_to_cancel = None
    for a in appointments:
        if a["id"] == booking_id and a["user_id"] == message.from_user.id:
            booking_to_cancel = a
            break
    
    if not booking_to_cancel:
        await message.answer("❌ Запись с таким номером не найдена или это не ваша запись")
        return
    
    appointments.remove(booking_to_cancel)
    reminders_sent.discard(str(booking_id))
    
    await message.answer(
        f"✅ <b>ЗАПИСЬ ОТМЕНЕНА!</b>\n\n"
        f"💇 {SERVICES[booking_to_cancel['service']]} — {PRICES[booking_to_cancel['service']]}₽\n"
        f"👤 {booking_to_cancel['master']}\n"
        f"📅 {booking_to_cancel['date_display']}\n"
        f"⏰ {booking_to_cancel['time']}",
        parse_mode="HTML",
        reply_markup=get_main_menu_kb()
    )
    
    try:
        await bot.send_message(
            MASTER_ID,
            f"⚠️ <b>ЗАПИСЬ ОТМЕНЕНА!</b>\n\n"
            f"👤 {booking_to_cancel['user_name']}\n"
            f"💇 {SERVICES[booking_to_cancel['service']]} — {PRICES[booking_to_cancel['service']]}₽\n"
            f"👤 {booking_to_cancel['master']}\n"
            f"📅 {booking_to_cancel['date_display']}\n"
            f"⏰ {booking_to_cancel['time']}",
            parse_mode="HTML"
        )
    except:
        pass

# ========== КОМАНДЫ ДЛЯ МАСТЕРА ==========
@dp.message(Command("admin"))
async def admin_view(message: types.Message):
    if message.from_user.id != MASTER_ID:
        await message.answer("⛔ Нет доступа")
        return
    
    if not appointments:
        await message.answer("📭 Нет записей")
        return
    
    text = "📊 <b>Все записи</b>\n\n"
    for a in appointments:
        source = "🌐 Сайт" if a.get("from_site") else "🤖 Бот"
        text += f"<b>#{a['id']}</b> {source}\n"
        text += f"👤 {a['user_name']}\n"
        text += f"💇 {SERVICES[a['service']]} — {PRICES[a['service']]}₽\n"
        text += f"👤 {a['master']}\n"
        text += f"📅 {a['date_display']}\n"
        text += f"⏰ {a['time']}\n"
        text += f"🕐 {a['created_at']}\n\n"
        
        if len(text) > 3500:
            await message.answer(text, parse_mode="HTML")
            text = ""
    if text:
        await message.answer(text, parse_mode="HTML")

@dp.message(Command("cancel"))
async def cancel_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено. /start", reply_markup=get_main_menu_kb())

# ========== ЗАПУСК ==========
async def main():
    print("✅ БОТ ЗАПУЩЕН!")
    print("🔒 Проверка занятых слотов включена")
    print("🔔 Напоминания о записях включены (за час)")
    print("🌐 Поддержка записей с сайта включена")
    
    asyncio.create_task(reminder_checker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())