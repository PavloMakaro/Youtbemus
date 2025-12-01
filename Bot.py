import asyncio
import logging
import sqlite3
import os
import uuid
import html
import importlib.util
import re
import urllib.parse
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ==============================================================================
# 1. КОНФИГУРАЦИЯ
# ==============================================================================
BOT_TOKEN = "8597344193:AAG9qMpW_-9g643by4L0209NE6WYRTF4bqI"
CHANNEL_ID = "@storemoduleTg"
STORE_DIR = "store"
DB_NAME = "universli_ultra.db"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Создаем папку для скриптов
if not os.path.exists(STORE_DIR):
    os.makedirs(STORE_DIR)

# ==============================================================================
# 2. МЕНЕДЖЕР БАЗЫ ДАННЫХ (Thread-Safe + Auto-Migration)
# ==============================================================================
class DatabaseManager:
    def __init__(self, db_name):
        self.db_name = db_name
        self.lock = asyncio.Lock()
        self.conn = None
        self.cursor = None

    def connect(self):
        """Подключение и инициализация таблиц."""
        self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.migrate_tables()

    def create_tables(self):
        """Создание базовой структуры."""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                active_module_uuid TEXT DEFAULT NULL
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS modules (
                uuid TEXT PRIMARY KEY,
                author_id INTEGER,
                code_path TEXT,
                name TEXT,
                description TEXT,
                is_public INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)
        self.conn.commit()

    def migrate_tables(self):
        """Автоматическое добавление колонок для совместимости со старыми версиями БД."""
        migrations = [
            "ALTER TABLE modules ADD COLUMN is_public INTEGER DEFAULT 1",
            "ALTER TABLE modules ADD COLUMN name TEXT DEFAULT 'Модуль'"
        ]
        for sql in migrations:
            try:
                self.cursor.execute(sql)
                self.conn.commit()
                logger.info(f"🔧 DB Migration applied: {sql}")
            except sqlite3.OperationalError:
                pass  # Колонка уже существует

    async def execute(self, sql: str, params: tuple = ()):
        """Безопасная запись в БД."""
        async with self.lock:
            try:
                self.cursor.execute(sql, params)
                self.conn.commit()
            except Exception as e:
                logger.error(f"DB Error: {e}")

    async def fetchone(self, sql: str, params: tuple = ()):
        async with self.lock:
            self.cursor.execute(sql, params)
            return self.cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()):
        async with self.lock:
            self.cursor.execute(sql, params)
            return self.cursor.fetchall()

# Инициализация БД
db = DatabaseManager(DB_NAME)
db.connect()

# ==============================================================================
# 3. AI И УТИЛИТЫ
# ==============================================================================

async def query_pollinations(prompt: str) -> str:
    """Запрос к AI с правильным кодированием URL."""
    # Используем quote для безопасности URL
    safe_prompt = urllib.parse.quote(prompt)
    # Добавляем seed для вариативности
    url = f"https://text.pollinations.ai/{safe_prompt}?model=openai&seed={os.urandom(2).hex()}"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.text()
                return ""
        except Exception as e:
            logger.error(f"AI Request Error: {e}")
            return ""

def clean_python_code(raw_text: str) -> str:
    """Очищает Markdown разметку."""
    match = re.search(r"```python(.*?)```", raw_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw_text.strip()

async def deploy_module(user_id: int, code: str, is_public: bool, bot: Bot, status_msg: Message, origin_prompt: str = ""):
    """Основная логика: Сохранение -> Анализ AI -> БД -> Публикация."""
    
    # 1. Валидация
    if "def run" not in code:
        await status_msg.edit_text("❌ <b>Ошибка:</b> В коде нет функции `def run(text):`")
        return

    # 2. Сохранение файла
    mod_uuid = str(uuid.uuid4())[:8]
    file_path = os.path.join(STORE_DIR, f"{mod_uuid}.py")
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)

    await status_msg.edit_text("🧠 <b>AI анализирует код и придумывает название...</b>", parse_mode=ParseMode.HTML)

    # 3. Генерация метаданных (Название, Описание, Теги)
    # Берем начало кода для контекста
    code_snippet = code[:1500]
    
    analyze_prompt = (
        f"Analyze this python code provided by user. Context: '{origin_prompt}'. "
        "Create a short Creative Name (Title) in Russian и напиши какими командами использовать , a Description (max 2 sentences) in Russian, and Hashtags. "
        "Use '@@@' as separator. Strict Format: NAME@@@DESCRIPTION@@@HASHTAGS. "
        "Do not write anything else. "
        f"Code: {code_snippet}"
    )
    
    analysis = await query_pollinations(analyze_prompt)
    
    # Значения по умолчанию
    mod_name = "Пользовательский модуль"
    mod_desc = "Описание отсутствует"
    mod_tags = "#python #bot"

    # Парсинг ответа AI
    try:
        if "@@@" in analysis:
            parts = analysis.split("@@@")
            if len(parts) >= 3:
                mod_name = parts[0].strip().replace('"', '').replace('*', '')
                mod_desc = parts[1].strip()
                mod_tags = parts[2].strip()
    except Exception as e:
        logger.error(f"AI Parse Error: {e}")

    # 4. Сохранение в БД
    await db.execute(
        "INSERT INTO modules (uuid, author_id, code_path, name, description, is_public, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (mod_uuid, user_id, file_path, mod_name, mod_desc, 1 if is_public else 0, datetime.now().isoformat())
    )

    # 5. Публикация в канал (если публичный)
    if is_public:
        try:
            bot_info = await bot.get_me()
            deep_link = f"https://t.me/{bot_info.username}?start={mod_uuid}"
            
            post_text = (
                f"<b>🆕 {html.escape(mod_name)}</b>\n\n"
                f"📝 {html.escape(mod_desc)}\n\n"
                f"🏷 {html.escape(mod_tags)}\n\n"
                f"🆔 ID: <code>{mod_uuid}</code>"
            )
            
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📥 Установить", url=deep_link)]])
            await bot.send_message(CHANNEL_ID, post_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Channel Publish Error: {e}")

    # 6. Авто-установка пользователю
    await db.execute("UPDATE users SET active_module_uuid = ? WHERE user_id = ?", (mod_uuid, user_id))
    
    kb_exit = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Выключить модуль")]],
        resize_keyboard=True, is_persistent=True
    )
    
    await status_msg.delete()
    
    status_icon = "📢 Публичный" if is_public else "🔒 Приватный"
    
    await bot.send_message(
        user_id,
        f"✅ <b>Модуль установлен!</b>\n"
        f"⚙️ Статус: {status_icon}\n\n"
        f"📌 <b>{html.escape(mod_name)}</b>\n"
        f"<i>{html.escape(mod_desc)}</i>",
        reply_markup=kb_exit,
        parse_mode=ParseMode.HTML
    )

# ==============================================================================
# 4. РОУТЕРЫ И ЛОГИКА
# ==============================================================================
router_high = Router()  # 1. Выход
router_mid = Router()   # 2. Сессия
router_low = Router()   # 3. Меню

class CreateModule(StatesGroup):
    waiting_for_ai_prompt = State()
    waiting_for_manual_code = State()
    waiting_for_privacy_choice = State()

# --- ПРИОРИТЕТ 1: ВЫХОД ---
@router_high.message(F.text == "❌ Выключить модуль")
async def exit_module(message: Message):
    """Принудительный выход из активного модуля."""
    await db.execute("UPDATE users SET active_module_uuid = NULL WHERE user_id = ?", (message.from_user.id,))
    await message.answer(
        "<b>🔴 Модуль остановлен.</b>\nВозврат в систему.",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode=ParseMode.HTML
    )
    await show_kernel_menu(message)

# --- ПРИОРИТЕТ 2: АКТИВНАЯ СЕССИЯ ---
async def is_session_active(message: Message) -> bool:
    if not message.from_user: return False
    res = await db.fetchone("SELECT active_module_uuid FROM users WHERE user_id = ?", (message.from_user.id,))
    return res is not None and res[0] is not None

@router_mid.message(is_session_active)
async def module_runtime_handler(message: Message):
    """Перехват сообщений и отправка в модуль."""
    user_id = message.from_user.id
    row = await db.fetchone("SELECT active_module_uuid FROM users WHERE user_id = ?", (user_id,))
    module_uuid = row[0]

    mod_row = await db.fetchone("SELECT code_path FROM modules WHERE uuid = ?", (module_uuid,))
    if not mod_row:
        await message.answer("⚠️ Ошибка: Файл модуля не найден. Сброс сессии.")
        await db.execute("UPDATE users SET active_module_uuid = NULL WHERE user_id = ?", (user_id,))
        return

    file_path = mod_row[0]

    try:
        # Динамический импорт
        spec = importlib.util.spec_from_file_location(f"mod_{module_uuid}", file_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Выполнение run()
            if hasattr(module, 'run'):
                user_text = message.text if message.text else ""
                output = module.run(user_text)
                await message.answer(html.escape(str(output)), parse_mode=ParseMode.HTML)
            else:
                await message.answer("⚠️ В модуле нет функции `run(text)`.")
    except Exception as e:
        await message.answer(f"🔥 <b>Ошибка модуля:</b>\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)

# --- ПРИОРИТЕТ 3: ЯДРО (МЕНЮ) ---

async def show_kernel_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✨ Создать с AI", callback_data="create_ai"),
            InlineKeyboardButton(text="📥 Загрузить код", callback_data="create_manual")
        ],
        [InlineKeyboardButton(text="📂 Мои модули", callback_data="list_modules")]
    ])
    await message.answer(
        "<b>🖥 UNIVERSLI ULTRA OS</b>\n\nЯдро активно. Выберите действие:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

@router_low.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    
    # Проверка Deep Link (установка модуля)
    if command.args:
        mod_uuid = command.args
        mod_row = await db.fetchone("SELECT uuid, name, description FROM modules WHERE uuid = ?", (mod_uuid,))
        if mod_row:
            mid, mname, mdesc = mod_row
            await db.execute("UPDATE users SET active_module_uuid = ? WHERE user_id = ?", (mid, user_id))
            
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="❌ Выключить модуль")]],
                resize_keyboard=True, is_persistent=True
            )
            await message.answer(
                f"<b>📥 Загружен модуль: {html.escape(mname)}</b>\n\n{html.escape(mdesc)}",
                reply_markup=kb, parse_mode=ParseMode.HTML
            )
            return
        else:
            await message.answer("❌ Модуль не найден.")
    
    await show_kernel_menu(message)

# --- FSM: СОЗДАНИЕ ЧЕРЕЗ AI ---
@router_low.callback_query(F.data == "create_ai")
async def start_create_ai(call: CallbackQuery, state: FSMContext):
    await call.message.answer("🤖 <b>Конструктор AI</b>\n\nОпишите, что должен делать бот.", parse_mode=ParseMode.HTML)
    await state.set_state(CreateModule.waiting_for_ai_prompt)
    await call.answer()

@router_low.message(CreateModule.waiting_for_ai_prompt)
async def generate_ai_code(message: Message, state: FSMContext):
    user_prompt = message.text
    status_msg = await message.answer("⏳ <b>Генерация кода...</b>")
    
    # Промпт для генерации Python
    system_prompt = (
        "You are a Python generator. Write a Python script with a function `def run(text):` that returns a string. "
        "Standard python libs only. Task: " + user_prompt + ". "
        "Return ONLY raw python code."
    )
    
    raw_code = await query_pollinations(system_prompt)
    clean_code = clean_python_code(raw_code)
    
    await state.update_data(code=clean_code, origin_prompt=user_prompt)
    await ask_privacy(message, state, status_msg)

# --- FSM: РУЧНАЯ ЗАГРУЗКА ---
@router_low.callback_query(F.data == "create_manual")
async def start_create_manual(call: CallbackQuery, state: FSMContext):
    await call.message.answer(
        "👨‍💻 <b>Ручная загрузка</b>\n\n"
        "Пришлите <b>текст кода</b> или <b>файл .py</b>.\n"
        "Требование: Функция <code>def run(text):</code>",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(CreateModule.waiting_for_manual_code)
    await call.answer()

@router_low.message(CreateModule.waiting_for_manual_code)
async def receive_manual_code(message: Message, state: FSMContext, bot: Bot):
    code = ""
    status_msg = await message.answer("⏳ <b>Чтение данных...</b>")

    if message.document:
        if not message.document.file_name.endswith('.py'):
            await status_msg.edit_text("❌ Разрешены только .py файлы")
            return
        
        file_io = await bot.download(message.document)
        try:
            code = file_io.read().decode('utf-8')
        except:
            await status_msg.edit_text("❌ Ошибка кодировки файла (нужен UTF-8).")
            return

    elif message.text:
        code = clean_python_code(message.text)
    
    else:
        await status_msg.edit_text("❌ Пришлите текст или файл.")
        return

    await state.update_data(code=code, origin_prompt="Manual Upload")
    await ask_privacy(message, state, status_msg)

# --- FSM: ВЫБОР ПРИВАТНОСТИ ---
async def ask_privacy(message: Message, state: FSMContext, old_msg: Message):
    """Спрашиваем пользователя, публиковать ли модуль."""
    try: await old_msg.delete()
    except: pass

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Публичный (В канал)", callback_data="privacy_public")],
        [InlineKeyboardButton(text="🔒 Приватный (Личный)", callback_data="privacy_private")]
    ])
    
    await message.answer("👀 <b>Уровень доступа:</b>", reply_markup=kb, parse_mode=ParseMode.HTML)
    await state.set_state(CreateModule.waiting_for_privacy_choice)

@router_low.callback_query(CreateModule.waiting_for_privacy_choice)
async def finish_creation(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    code = data.get("code")
    origin = data.get("origin_prompt")
    is_public = (call.data == "privacy_public")
    
    try: await call.message.delete()
    except: pass

    status_msg = await call.message.answer("⏳ <b>Финализация установки...</b>")
    await deploy_module(call.from_user.id, code, is_public, bot, status_msg, origin_prompt=origin)
    await state.clear()
    await call.answer()

# --- СПИСОК МОДУЛЕЙ ---
@router_low.callback_query(F.data == "list_modules")
async def list_modules(call: CallbackQuery):
    user_id = call.from_user.id
    rows = await db.fetchall("SELECT uuid, name, is_public FROM modules WHERE author_id = ?", (user_id,))
    
    if not rows:
        await call.answer("У вас пока нет модулей.", show_alert=True)
        return

    text = "<b>📂 Ваши модули:</b>\n"
    kb_rows = []
    
    for r in rows:
        mid, mname, is_pub = r
        icon = "📢" if is_pub else "🔒"
        text += f"\n{icon} <b>{html.escape(mname)}</b>\nID: <code>{mid}</code>"
        kb_rows.append([InlineKeyboardButton(text=f"🚀 {mname}", url=f"https://t.me/{(await call.bot.get_me()).username}?start={mid}")])

    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode=ParseMode.HTML)

@router_low.callback_query(F.data == "back_to_menu")
async def back_menu(call: CallbackQuery):
    await call.message.delete()
    await show_kernel_menu(call.message)

# ==============================================================================
# 5. ЗАПУСК
# ==============================================================================
async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Порядок регистрации важен!
    dp.include_router(router_high)  # 1. Выход
    dp.include_router(router_mid)   # 2. Сессия
    dp.include_router(router_low)   # 3. Меню

    await bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("🚀 UNIVERSLI ULTRA OS STARTED")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
