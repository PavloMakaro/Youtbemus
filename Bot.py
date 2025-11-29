import logging
import requests
import json
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8377691734:AAGywySfCYU8lI9UWQUHW9CHdEKFXkl2fe8"  # Твой токен

# API Pollinations
TEXT_API_URL = "https://text.pollinations.ai/"
IMAGE_API_URL = "https://pollinations.ai/p/"
MODELS_LIST_URL = "https://text.pollinations.ai/models"

# Настройки логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Хранилище настроек пользователей (в памяти)
# Структура: {user_id: {"text_model": "openai", "image_model": "flux", "history": []}}
user_preferences = {}

# Ключевые слова для триггеров
IMAGE_TRIGGERS = ["нарисуй", "изображение", "фото", "сгенерируй", "image", "picture", "draw", "paint"]
MODEL_QUERY_TRIGGERS = ["какие модели", "смени модель", "список моделей", "change model", "models"]

async def get_available_models():
    """Получает список моделей с API, возвращает дефолтные при ошибке."""
    try:
        response = requests.get(MODELS_LIST_URL, timeout=5)
        if response.status_code == 200:
            models = response.json()
            # Фильтруем или разделяем, если API дает типы. 
            # Обычно Pollinations возвращает список текстовых моделей.
            # Добавим вручную популярные для надежности.
            text_models = [m['name'] for m in models] if isinstance(models, list) else ["openai", "qwen", "mistral", "llama"]
            return text_models
    except Exception as e:
        logging.error(f"Error fetching models: {e}")
    
    return ["openai", "mistral", "llama", "searchgpt", "qwen-coder"]

async def get_user_prefs(user_id):
    """Получает или создает настройки пользователя."""
    if user_id not in user_preferences:
        user_preferences[user_id] = {
            "text_model": "openai",
            "image_model": "flux", # flux, turbo
            "history": [] # История сообщений для контекста
        }
    return user_preferences[user_id]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    prefs = await get_user_prefs(user.id)
    
    welcome_text = (
        f"Привет, {user.first_name}! Я твой универсальный AI-агент.\n\n"
        f"🧠 **Текущий мозг:** `{prefs['text_model']}`\n"
        f"🎨 **Художник:** `{prefs['image_model']}`\n\n"
        "**Что я умею:**\n"
        "1. Просто общайся со мной — я отвечу текстом.\n"
        "2. Напиши **'Нарисуй [что-то]'**, и я сгенерирую картинку.\n"
        "3. Спроси **'Какие есть модели?'**, чтобы переключить мои настройки.\n\n"
        "Попробуй удивить меня запросом!"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def show_models_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает клавиатуру для выбора моделей."""
    text_models = await get_available_models()
    
    # Создаем кнопки для текстовых моделей
    keyboard = []
    keyboard.append([InlineKeyboardButton("📝 --- Текстовые модели ---", callback_data="ignore")])
    
    row = []
    for model in text_models[:6]: # Берем первые 6, чтобы не спамить
        row.append(InlineKeyboardButton(model, callback_data=f"set_text_{model}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Кнопки для графических моделей
    keyboard.append([InlineKeyboardButton("🎨 --- Модели изображений ---", callback_data="ignore")])
    image_models = ["flux", "turbo", "midjourney"] # midjourney в pollinations это часто стиль, но оставим как опцию
    img_row = [InlineKeyboardButton(m, callback_data=f"set_image_{m}") for m in image_models]
    keyboard.append(img_row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = "⚙️ **Панель управления моделями**\nВыберите, какой движок мне использовать:"
    
    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        # Если вызвано из callback
        await update.callback_query.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия кнопок смены моделей."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    prefs = await get_user_prefs(user_id)

    if data == "ignore":
        return

    if data.startswith("set_text_"):
        new_model = data.replace("set_text_", "")
        prefs['text_model'] = new_model
        await query.edit_message_text(f"✅ Готово! Теперь я использую текстовую модель: **{new_model}**", parse_mode='Markdown')
        
    elif data.startswith("set_image_"):
        new_model = data.replace("set_image_", "")
        prefs['image_model'] = new_model
        await query.edit_message_text(f"✅ Готово! Теперь я рисую с помощью: **{new_model}**", parse_mode='Markdown')

async def generate_image(prompt, model):
    """Генерирует ссылку на изображение."""
    seed = random.randint(0, 999999)
    # Формируем URL. Pollinations API прост: GET запрос
    # safe=true добавляем для безопасности, nologo=true убирает лого
    url = f"{IMAGE_API_URL}{requests.utils.quote(prompt)}?model={model}&seed={seed}&nologo=true"
    return url

async def generate_text_response(history, model):
    """Генерирует текст через Pollinations."""
    payload = {
        "messages": history,
        "model": model,
        "jsonMode": False
    }
    
    try:
        response = requests.post(TEXT_API_URL, json=payload, timeout=30)
        if response.status_code == 200:
            return response.text
        else:
            return f"Ошибка API ({response.status_code}): {response.text}"
    except Exception as e:
        return f"Произошла ошибка соединения: {e}"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_id = update.effective_user.id
    prefs = await get_user_prefs(user_id)
    
    if not user_text:
        return

    text_lower = user_text.lower()

    # 1. Проверка: Хочет ли пользователь сменить настройки?
    if any(trigger in text_lower for trigger in MODEL_QUERY_TRIGGERS):
        await show_models_keyboard(update, context)
        return

    # 2. Проверка: Хочет ли пользователь изображение?
    # Если есть ключевое слово ИЛИ длина запроса короткая и начинается с "a " (английский промпт)
    is_image_request = any(trigger in text_lower for trigger in IMAGE_TRIGGERS)
    
    if is_image_request:
        status_msg = await update.message.reply_text(f"🎨 Генерирую изображение ({prefs['image_model']})...")
        try:
            # Чистим промпт от триггерных слов для лучшего качества
            clean_prompt = user_text
            for trigger in IMAGE_TRIGGERS:
                clean_prompt = clean_prompt.replace(trigger, "", 1) # убираем только первое вхождение
            
            image_url = await generate_image(clean_prompt.strip(), prefs['image_model'])
            
            # Отправляем картинку
            await update.message.reply_photo(photo=image_url, caption=f"🖼 `{clean_prompt.strip()}`\nМодель: {prefs['image_model']}", parse_mode='Markdown')
            await context.bot.delete_message(chat_id=user_id, message_id=status_msg.message_id)
        except Exception as e:
            await status_msg.edit_text(f"Не удалось сгенерировать изображение. Ошибка: {e}")
        return

    # 3. Обработка текстового запроса (LLM)
    status_msg = await update.message.reply_text("🤔 Думаю...")
    
    # Формируем историю (простая реализация: системный промпт + последний запрос)
    # Можно расширить до хранения последних N сообщений
    messages = [
        {"role": "system", "content": "Ты полезный, умный и веселый ассистент. Отвечай в формате Markdown. Если пользователь просит код, давай код."},
        {"role": "user", "content": user_text}
    ]
    
    response_text = await generate_text_response(messages, prefs['text_model'])
    
    try:
        await status_msg.edit_text(response_text, parse_mode='Markdown')
    except:
        # Если Markdown сломался (бывает с спецсимволами), отправляем как простой текст
        await status_msg.edit_text(response_text)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("settings", show_models_keyboard))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print(f"Бот запущен! Токен: {BOT_TOKEN}")
    app.run_polling()

if __name__ == '__main__':
    main()
