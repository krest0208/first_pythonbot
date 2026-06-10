import asyncio
import logging
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ========== ТОКЕН ==========
TOKEN = "8517689872:AAGfe2bFZE932QdzRQfDJu2K_-VYC8phIuY"
# ===========================

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

# Хранилище
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
    """Клавиатура для выбора даты с кнопкой Назад"""
    kb = [
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="date_today")],
        [InlineKeyboardButton(text="📅 Завтра", callback_data="date_tomorrow")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_masters")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_time_kb():
    """Клавиатура для выбора времени с кнопкой Назад"""
    kb = []
    # Часы с 9 до 20
    for hour in range(9, 21):
        kb.append([InlineKeyboardButton(text=f"{hour:02d}:00", callback_data=f"time_{hour:02d}:00")])
        if hour < 20:
            kb.append([InlineKeyboardButton(text=f"{hour:02d}:30", callback_data=f"time_{hour:02d}:30")])
    
    # Разбиваем на ряды по 3 кнопки
    rows = [kb[i:i+3] for i in range(0, len(kb), 3)]
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

def is_slot_occupied(master: str, date: str, time_str: str, exclude_id: int = None) -> bool:
    t = time_to_minutes(time_str)
    if t == -1:
        return False
    for app in appointments:
        if app["master"] == master and app["date"] == date:
            if exclude_id is not None and app["id"] == exclude_id:
                continue
            bt = time_to_minutes(app["time"])
            if bt == -1:
                continue
            if abs(t - bt) < SERVICE_DURATION:
                return True
    return False

def get_free_slots_text(master: str, date: str) -> str:
    busy = []
    for app in appointments:
        if app["master"] == master and app["date"] == date:
            busy.append(time_to_minutes(app["time"]))
    
    if not busy:
        return "✅ Весь день свободен (9:00 - 20:00)"
    
    busy.sort()
    free_slots = []
    current = 9 * 60
    
    for b in busy:
        if current + SERVICE_DURATION <= b:
            free_slots.append((current, b))
        current = max(current, b + SERVICE_DURATION)
    
    if current < 20 * 60:
        free_slots.append((current, 20 * 60))
    
    if not free_slots:
        return "❌ На сегодня всё занято"
    
    text = "🟢 Свободные окна:\n"
    for start, end in free_slots:
        start_str = f"{start // 60:02d}:{start % 60:02d}"
        end_str = f"{end // 60:02d}:{end % 60:02d}"
        text += f"   • {start_str} - {end_str}\n"
    return text

# ========== ФУНКЦИЯ НАПОМИНАНИЯ ==========
async def reminder_checker():
    while True:
        try:
            now = datetime.now()
            current_hour = now.hour
            current_minute = now.minute
            current_date = now.strftime("%d.%m.%Y")
            
            for app in appointments:
                reminder_key = f"{app['id']}"
                if reminder_key in reminders_sent:
                    continue
                
                if app["date"] == current_date:
                    app_hour = int(app["time"].split(':')[0])
                    app_minute = int(app["time"].split(':')[1])
                    
                    reminder_hour = app_hour - 1 if app_hour > 0 else 23
                    
                    if current_hour == reminder_hour and abs(current_minute - app_minute) <= 1:
                        service_name = SERVICES[app["service"]]
                        try:
                            await bot.send_message(
                                app["user_id"],
                                f"⏰ <b>НАПОМИНАНИЕ!</b>\n\n"
                                f"Через час у вас {service_name} у {app['master']}.\n"
                                f"📅 {app['date_display']}\n"
                                f"⏰ {app['time']}\n\n"
                                f"Ждём вас в салоне! 💇",
                                parse_mode="HTML"
                            )
                            reminders_sent.add(reminder_key)
                            print(f"[✓] Напоминание отправлено #{app['id']}")
                        except Exception as e:
                            print(f"[×] Ошибка: {e}")
            
            if now.minute % 10 == 0:
                to_remove = []
                for app in appointments:
                    if app["date"] < current_date:
                        to_remove.append(f"{app['id']}")
                    elif app["date"] == current_date:
                        app_hour = int(app["time"].split(':')[0])
                        if current_hour > app_hour + 1:
                            to_remove.append(f"{app['id']}")
                for key in to_remove:
                    reminders_sent.discard(key)
            
        except Exception as e:
            print(f"[×] Ошибка: {e}")
        
        await asyncio.sleep(60)

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    if user_id not in greeted_users:
        greeted_users.add(user_id)
        welcome_text = (
            "<b>Добро пожаловать в салон «Анна Стилист»!</b>\n\n"
            "Я помогу вам записаться на услугу.\n\n"
            "<b>Что я умею:</b>\n"
        "• Запись на стрижку, маникюр и другие услуги\n"            
            "• Выбор мастера (Анна или Елена)\n"
            "• Умный ввод даты (завтра, 15.06)\n"
            "• Умный ввод времени (14:00 или 14)\n"
            "• Напоминание о записи за час\n\n"
            "<b>Нажмите кнопку «📅 Новая запись»</b>"
        )
        await message.answer(welcome_text, parse_mode="HTML", reply_markup=get_main_menu_kb())
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
        
        await call.message.edit_text(
            f"📅 Выберите дату:",
            reply_markup=get_date_kb()
        )
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
        date_str = date_obj.strftime("%d.%m.%Y")
        date_display = f"{date_obj.day}.{date_obj.month}"
        await state.update_data(date=date_str, date_display=date_display)
        
        data = await state.get_data()
        free_slots = get_free_slots_text(data["master"], date_str)
        
        await call.message.edit_text(
            f"✅ Дата: {date_display}\n\n"
            f"⏰ Выберите время:\n\n"
            f"{free_slots}",
            reply_markup=get_time_kb()
        )
        await state.set_state(Booking.time)
        
    elif call.data == "date_tomorrow":
        date_obj = today + timedelta(days=1)
        date_str = date_obj.strftime("%d.%m.%Y")
        date_display = f"{date_obj.day}.{date_obj.month}"
        await state.update_data(date=date_str, date_display=date_display)
        
        data = await state.get_data()
        free_slots = get_free_slots_text(data["master"], date_str)
        
        await call.message.edit_text(
            f"✅ Дата: {date_display}\n\n"
            f"⏰ Выберите время:\n\n"
            f"{free_slots}",
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
        
        # Проверяем, не занято ли время
        if is_slot_occupied(data["master"], data["date"], time_str):
            free_slots = get_free_slots_text(data["master"], data["date"])
            await call.message.edit_text(
                f"❌ {data['master']} уже занята в {time_str}!\n\n"
                f"{free_slots}\n\n"
                f"Выберите другое время:",
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
            "created_at": datetime.now().strftime("%d.%m.%Y %H:%M")
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
            f"🔔 Я напомню о записи за час.\n\n"
            f"Чтобы отменить запись, используйте /my",
            parse_mode="HTML"
        )
        
        # Показываем главное меню
        await call.message.answer("🏠 Главное меню:", reply_markup=get_main_menu_kb())
        
        # Уведомление мастеру
        try:
            await bot.send_message(
                MASTER_ID,
                f"🔔 <b>НОВАЯ ЗАПИСЬ!</b>\n\n"
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

# ========== КОМАНДЫ ==========
@dp.message(Command("my"))
async def my_appointments(message: types.Message):
    user_apps = [a for a in appointments if a["user_id"] == message.from_user.id]
    if not user_apps:
        await message.answer("📭 Нет записей. /start", reply_markup=get_main_menu_kb())
        return
    
    text = "📋 <b>Ваши записи</b>\n\n"
    for a in user_apps:
        service_name = SERVICES[a["service"]]
        price = PRICES[a["service"]]
        text += f"<b>#{a['id']}</b>\n"
        text += f"💇 {service_name} — {price}₽\n"
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
    
    service_name = SERVICES[booking_to_cancel["service"]]
    price = PRICES[booking_to_cancel["service"]]
    
    await message.answer(
        f"✅ <b>ЗАПИСЬ ОТМЕНЕНА!</b>\n\n"
        f"💇 {service_name}\n"
        f"💰 {price} ₽\n"
        f"👤 {booking_to_cancel['master']}\n"
        f"📅 {booking_to_cancel['date_display']}\n"
        f"⏰ {booking_to_cancel['time']}\n\n"
        f"Время освободилось. /start - новая запись",
        parse_mode="HTML",
        reply_markup=get_main_menu_kb()
    )
    
    try:
        await bot.send_message(
            MASTER_ID,
            f"⚠️ <b>ЗАПИСЬ ОТМЕНЕНА!</b>\n\n"
            f"👤 {booking_to_cancel['user_name']}\n"
            f"💇 {service_name}\n"
            f"💰 {price} ₽\n"
            f"👤 {booking_to_cancel['master']}\n"
            f"📅 {booking_to_cancel['date_display']}\n"
            f"⏰ {booking_to_cancel['time']}",
            parse_mode="HTML"
        )
    except:
        pass

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
        service_name = SERVICES[a["service"]]
        price = PRICES[a["service"]]
        text += f"<b>#{a['id']}</b>\n"
        text += f"👤 {a['user_name']}\n"
        text += f"💇 {service_name} — {price}₽\n"
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

async def main():
    print("✅ БОТ ЗАПУЩЕН!")
    print("🔒 Проверка занятых слотов включена")
    print("🔔 Напоминания о записях включены (за час)")
    print("🔙 Кнопка «Назад» добавлена на всех этапах")
    
    asyncio.create_task(reminder_checker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())