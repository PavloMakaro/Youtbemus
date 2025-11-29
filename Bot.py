import logging
import requests
import time
import json
import base64
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode, ChatAction

# --- КОНФИГУРАЦИЯ ---
TOKEN = "8377691734:AAGywySfCYU8lI9UWQUHW9CHdEKFXkl2fe8"
ADMIN_ID = None  # Можете вписать свой ID для отладки

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- МОЗГ БОТА (API POLLINATIONS) ---
class PollinationsBrain:
    def __init__(self):
        self.base_text_url = "https://text.pollinations.ai/"
        self.models_list_url = "https://text.pollinations.ai/models"
        self.image_url_base = "https://pollinations.ai/p/"
        
        # Кэш моделей
        self.text_models = []
        self.last_models_update = 0
        self.default_text_model = "openai" # Фолбэк
        self.default_image_model = "flux"

        # Первичная загрузка моделей
        self.refresh_models()

    def refresh_models(self):
        """Загружает реальные рабочие модели с API"""
        # Обновляем не чаще раза в час, чтобы не спамить
        if time.time() - self.last_models_update < 3600 and self.text_models:
            return

        try:
            response = requests.get(self.models_list_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Извлекаем имена моделей. Фильтруем те, у которых есть 'name'
                self.text_models = [m.get('name') for m in data if m.get('name')]
                self.last_models_update = time.time()
                logger.info(f"✅ Models updated. Found {len(self.text_models)} models.")
                # Если openai нет в списке, ставим первую попавшуюся как дефолт
                if self.default_text_model not in self.text_models and self.text_models:
                    self.default_text_model = self.text_models[0]
            else:
                logger.error(f"Failed to fetch models: Status {response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching models: {e}")
            # Фолбэк список, если сайт лежит
            if not self.text_models:
                self.text_models = ["openai", "gpt-4o", "claude-3-opus", "mistral-large", "gemini"]

    def generate_text(self, messages, model, seed=None):
        """Генерация текста с учетом контекста"""
        payload = {
            "messages": messages,
            "model": model,
            "jsonMode": False
        }
        if seed: payload["seed"] = seed

        try:
            # Используем session для keep-alive
            with requests.Session() as s:
                response = s.post(self.base_text_url, json=payload, timeout=60)
                if response.status_code == 200:
                    return response.text
                return f"⚠️ Ошибка API ({response.status_code}): {response.text[:100]}"
        except Exception as e:
            return f"⚠️ Ошибка соединения: {e}"

    def generate_image_url(self, prompt, model="flux", seed=None):
        """Генерация ссылки на картинку"""
        import urllib.parse
        clean_prompt = urllib.parse.quote(prompt)
        url = f"{self.image_url_base}{clean_prompt}?width=1024&height=1024&model={model}&nologo=true"
        if seed: url += f"&seed={seed}"
        return url

brain = PollinationsBrain()

# --- ЛОГИКА УПРАВЛЕНИЯ КОНТЕКСТОМ ---

SYSTEM_PROMPT = {
    "role": "system", 
    "content": (
        "Ты — универсальный AI-агент. Твоя задача — быть максимально полезным. "
        "Ты умеешь писать код, анализировать текст и поддерживать беседу. "
        "Если пользователь просит нарисовать что-то, отвечай коротким подтверждением, бот сам сгенерирует фото. "
        "Отвечай кратко и по делу, если не просят длинного объяснения."
    )
}

async def check_context_expiry(context, chat_id):
    """
    Проверяет, не прошел ли час с последнего сообщения.
    Если прошел — сбрасывает историю.
    """
    last_time = context.user_data.get('last_interaction', 0)
    current_time = time.time()
    
    # 3600 секунд = 1 час
    if current_time - last_time > 3600 and last_time != 0:
        context.user_data['history'] = [SYSTEM_PROMPT]
        context.user_data['last_interaction'] = current_time
        return True # Контекст сброшен
    
    context.user_data['last_interaction'] = current_time
    return False

async def reset_context(update, context):
    """Ручной сброс контекста"""
    context.user_data['history'] = [SYSTEM_PROMPT]
    context.user_data['last_interaction'] = time.time()
    await update.message.reply_text("🧹 Память очищена. Мы начали новый диалог!", parse_mode=ParseMode.MARKDOWN)

# --- ХЕНДЛЕРЫ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    
    # Инициализация дефолтных настроек
    if 'text_model' not in context.user_data: 
        context.user_data['text_model'] = brain.default_text_model
    if 'image_model' not in context.user_data: 
        context.user_data['image_model'] = brain.default_image_model
    
    # Сброс истории при старте
    context.user_data['history'] = [SYSTEM_PROMPT]
    context.user_data['last_interaction'] = time.time()

    text = (
        f"Привет, {user}! 🤖\n\n"
        "Я готов к работе. Я автоматически подстраиваюсь под твои запросы.\n"
        "🕒 **Фишка:** Если мы не общаемся час, я забуду контекст, чтобы начать с чистого листа.\n"
        "🔄 **Сброс:** Напиши *'сброс'*, *'новый диалог'* или *'забудь'*, чтобы очистить память вручную.\n\n"
        "Доступные команды:\n"
        "/models - Список моделей\n"
        "/settings - Текущие настройки\n"
        "Просто напиши что-нибудь!"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    chat_id = update.effective_chat.id
    
    # 0. Проверка на сброс по времени
    if await check_context_expiry(context, chat_id):
        await update.message.reply_text("⏳ Прошел час, я начал новый диалог, чтобы не путаться.", quote=False)

    # 1. Проверка на команду ручного сброса
    reset_keywords = ['сброс', 'reset', 'забудь', 'новый диалог', 'очисти', 'new chat', 'clear']
    if user_text.lower().strip() in reset_keywords:
        await reset_context(update, context)
        return

    # 2. Ищем явную просьбу сменить модель
    # Пример: "Используй модель gpt-4"
    text_lower = user_text.lower()
    brain.refresh_models() # Убедимся что список свежий
    
    # Простой парсинг смены модели
    found_model = None
    for m in brain.text_models:
        if m in text_lower and ("используй" in text_lower or "use" in text_lower or "модель" in text_lower):
            found_model = m
            break
            
    if found_model:
        context.user_data['text_model'] = found_model
        await update.message.reply_text(f"✅ Переключился на модель: **{found_model}**", parse_mode=ParseMode.MARKDOWN)
        # Не прерываем, вдруг там был еще и вопрос

    # 3. Рисование (Image Generation)
    draw_triggers = ["нарисуй", "сгенерируй", "фото", "картинка", "draw", "image of", "picture"]
    is_draw_request = any(user_text.lower().startswith(t) for t in draw_triggers)

    if is_draw_request:
        # Чистим промпт
        prompt = user_text
        for t in draw_triggers:
            prompt = re.sub(t, "", prompt, flags=re.IGNORECASE)
        prompt = prompt.strip()
        
        current_img_model = context.user_data.get('image_model', 'flux')
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        
        img_url = brain.generate_image_url(prompt, model=current_img_model, seed=update.message.message_id)
        
        try:
            await update.message.reply_photo(img_url, caption=f"🎨 **{current_img_model}**", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text(f"Не удалось загрузить фото: {e}")
        return

    # 4. Текстовый диалог (с памятью)
    current_model = context.user_data.get('text_model', 'openai')
    history = context.user_data.get('history', [SYSTEM_PROMPT])
    
    # Добавляем сообщение пользователя
    history.append({"role": "user", "content": user_text})
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    response = brain.generate_text(history, model=current_model)
    
    # Добавляем ответ бота
    history.append({"role": "assistant", "content": response})
    
    # Оптимизация памяти (Rolling Window)
    # Оставляем System Prompt [0] и последние 14 сообщений
    if len(history) > 16:
        history = [history[0]] + history[-15:]
    
    context.user_data['history'] = history
    
    await update.message.reply_text(response)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка Vision (GPT-4o)"""
    photo_file = await update.message.photo[-1].get_file()
    
    from io import BytesIO
    buffer = BytesIO()
    await photo_file.download_to_memory(buffer)
    img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    user_caption = update.message.caption if update.message.caption else "Что на фото?"
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    # Для Vision лучше использовать чистый запрос без длинной истории, 
    # либо добавлять его в историю как vision-контент (сложнее реализация).
    # Сделаем одноразовый запрос для надежности.
    payload_msg = [
        {"role": "user", "content": [
            {"type": "text", "text": user_caption},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
        ]}
    ]
    
    response = brain.generate_text(payload_msg, model="gpt-4o") # Принудительно gpt-4o для зрения
    await update.message.reply_text(response)


# --- МЕНЮ ВЫБОРА МОДЕЛЕЙ (С ПАГИНАЦИЕЙ) ---
async def show_models_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brain.refresh_models()
    models = brain.text_models
    
    # Показываем первые 10 моделей (Telegram не пустит 100 кнопок)
    keyboard = []
    for m in models[:10]:
        keyboard.append([InlineKeyboardButton(m, callback_data=f"setmod_{m}")])
    
    keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data="refresh_api")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = f"🔍 Найдено {len(models)} моделей в API.\nТекущая: **{context.user_data.get('text_model')}**\nВыберите из популярных:"
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("setmod_"):
        new_model = data.replace("setmod_", "")
        context.user_data['text_model'] = new_model
        await query.edit_message_text(f"✅ Успешно! Текстовая модель теперь: **{new_model}**", parse_mode=ParseMode.MARKDOWN)
    
    elif data == "refresh_api":
        brain.text_models = [] # сброс кэша
        brain.refresh_models()
        await query.edit_message_text(f"Список обновлен. Найдено {len(brain.text_models)} моделей. Напишите /models снова.")

# --- ЗАПУСК ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("models", show_models_command))
    
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot is running with Context Management & Real API fetching...")
    app.run_polling()
