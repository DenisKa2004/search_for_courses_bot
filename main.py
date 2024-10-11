import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Загрузка переменных окружения из файла .env
load_dotenv()

# Инициализация объекта бота, токен берется из переменной окружения BOT_TOKEN
bot = Bot(os.getenv('BOT_TOKEN'))

# Инициализация хранилища для состояний (FSM)
storage = MemoryStorage()

# Инициализация диспетчера для управления событиями и сообщениями
dp = Dispatcher(storage=storage)

# Определение состояний
class Form(StatesGroup):
    consent = State()
    fio = State()
    phone = State()
    direction = State()
    course_type = State()
    course_selection = State()

# Функция для создания клавиатуры из списка кнопок
def create_keyboard(buttons):
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True
    )

# Настройка доступа к Google Sheets
def get_sheets_client():
    # Проверка наличия файла credentials.json
    if not os.path.exists('credentials.json'):
        raise FileNotFoundError("Файл 'credentials.json' не найден. Пожалуйста, разместите его в корневой папке проекта.")

    scope = ["https://spreadsheets.google.com/feeds", 
             "https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive.file", 
             "https://www.googleapis.com/auth/drive"]

    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    return client

def get_courses_from_google_sheets():
    client = get_sheets_client()

    # Откройте таблицу по URL
    sheet = client.open_by_url(os.getenv('SHEETS_URL')).sheet1

    # Получите все записи
    data = sheet.get_all_records()

    # Структурируем данные
    courses = {}
    for row in data:
        direction = row['Направление'].strip()
        course_type = row['Тип курса'].strip()
        course_name = row['Название курса'].strip()
        course_link = row['Ссылка на курс'].strip()

        if direction not in courses:
            courses[direction] = {}
        if course_type not in courses[direction]:
            courses[direction][course_type] = []
        courses[direction][course_type].append({
            "name": course_name,
            "link": course_link
        })

    return courses

def add_user_to_google_sheets(fio, phone, direction):
    client = get_sheets_client()

    # Получаем второй лист таблицы
    sheet = client.open_by_url(os.getenv('SHEETS_URL')).get_worksheet(1)

    # Запись данных пользователя в новую строку
    sheet.append_row([fio, phone, direction])

try:
    # Получаем курсы при запуске бота
    COURSES = get_courses_from_google_sheets()
except FileNotFoundError as e:
    print(e)
    COURSES = {}

# Обработчик команды "/start"
@dp.message(CommandStart())
async def handle_start(message: types.Message, state: FSMContext):
    buttons = [
        [KeyboardButton(text="Согласен")]
    ]
    keyboard = create_keyboard(buttons)
    await message.answer("Вы согласны на обработку персональных данных?", reply_markup=keyboard)
    await state.set_state(Form.consent)

# Обработка согласия
@dp.message(Form.consent)
async def handle_consent(message: types.Message, state: FSMContext):
    if message.text == "Согласен":
        await message.answer("Пожалуйста, введите ваше ФИО:", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Form.fio)
    else:
        await message.answer("Для продолжения требуется согласие на обработку персональных данных.", reply_markup=ReplyKeyboardRemove())
        await state.clear()

# Ввод ФИО
@dp.message(Form.fio)
async def handle_fio(message: types.Message, state: FSMContext):
    fio = message.text.strip()
    if not fio:
        await message.answer("ФИО не может быть пустым. Пожалуйста, введите ваше ФИО:")
        return
    await state.update_data(fio=fio)
    await message.answer("Введите ваш номер телефона:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.phone)

# Ввод номера телефона
@dp.message(Form.phone)
async def handle_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not phone:
        await message.answer("Номер телефона не может быть пустым. Пожалуйста, введите ваш номер телефона:")
        return
    await state.update_data(phone=phone)

    # Выбор направления
    directions = list(COURSES.keys())
    buttons = [[KeyboardButton(text=direction)] for direction in directions]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer("Выберите направление обучения:", reply_markup=keyboard)
    await state.set_state(Form.direction)

# Обработка выбора направления
@dp.message(Form.direction)
async def handle_direction(message: types.Message, state: FSMContext):
    direction = message.text.strip()
    if direction not in COURSES:
        await message.answer("Пожалуйста, выберите направление из предложенных кнопок.")
        return
    await state.update_data(direction=direction)

    # Запись данных пользователя в Google Sheets
    data = await state.get_data()
    fio = data.get("fio")
    phone = data.get("phone")
    add_user_to_google_sheets(fio, phone, direction)

    # Выбор типа курса
    course_types = list(COURSES[direction].keys())
    buttons = [[KeyboardButton(text=ctype)] for ctype in course_types]
    keyboard = create_keyboard(buttons)
    await message.answer("Выберите тип курса:", reply_markup=keyboard)
    await state.set_state(Form.course_type)

# Обработка выбора типа курса
@dp.message(Form.course_type)
async def handle_course_type(message: types.Message, state: FSMContext):
    course_type = message.text.strip()
    if course_type not in ["Бесплатные", "Платные"]:
        await message.answer("Пожалуйста, выберите 'Бесплатные' или 'Платные' курсы.")
        return
    await state.update_data(course_type=course_type)

    data = await state.get_data()
    direction = data.get("direction")

    courses = COURSES.get(direction, {}).get(course_type, [])
    if not courses:
        await message.answer("Курсы по выбранному направлению и типу не найдены.")
        await state.clear()
        return

    # Ограничение до 5 курсов
    courses_to_show = courses[:5]

    buttons = [[KeyboardButton(text=course["name"])] for course in courses_to_show]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer("Выберите курс из списка ниже:", reply_markup=keyboard)
    await state.set_state(Form.course_selection)

# Обработка выбора курса
@dp.message(Form.course_selection)
async def handle_course_selection(message: types.Message, state: FSMContext):
    selected_course_name = message.text.strip()
    data = await state.get_data()
    direction = data.get("direction")
    course_type = data.get("course_type")

    courses = COURSES.get(direction, {}).get(course_type, [])
    selected_course = next((course for course in courses if course["name"] == selected_course_name), None)

    if not selected_course:
        await message.answer("Пожалуйста, выберите курс из предложенных кнопок.")
        return

    # Отправка ссылки на выбранный курс
    course_link = selected_course["link"]
    await message.answer(
        f"Вы выбрали курс: {selected_course_name}\nПерейдите по ссылке для доступа к курсу: {course_link}",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.clear()

# Основная асинхронная функция программы
async def main():
    # Настройка логирования, чтобы выводить сообщения с уровнем INFO и выше
    logging.basicConfig(level=logging.INFO)

    # Запуск процесса опроса сообщений от пользователей
    await dp.start_polling(bot)

# Проверка, что скрипт запущен напрямую
if __name__ == '__main__':
    # Запуск основного асинхронного процесса
    asyncio.run(main())
