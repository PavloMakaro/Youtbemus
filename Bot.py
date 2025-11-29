import logging
import re
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode, ChatAction

# --- КОНФИГУРАЦИЯ ---
# ВАЖНО: Вы "светите" токен в интернете. Я использовал его для кода, 
# но рекомендую отозвать его у BotFather и получить новый для безопасности.
TOKEN = "8377691734:AAGywySfCYU8lI9UWQUHW9CHdEKFXkl2fe8"

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- API КЛИЕНТ POLLINATIONS ---
class PollinationsAPI:
    def __init__(self):
        self.text_url = "https://text.pollinations.ai/"
        self.image_url = "https://pollinations.ai/p/"
        self.models_url = "https://text.pollinations.ai/models"
        
        # Кэшируем модели при запуске
        self.available_text_models = self.fetch_text_models()
        # Список популярных моделей изображений (API для списка изображений нестабильно, лучше задать базовые)
        self.available_image_models = ["flux", "flux-realism", "flux-anime", "flux-3d", "turbo"]

    def fetch_text_models(self):
        try:
            response = requests.get(self.models_url)
            if response.status_code == 200:
                models = response.json()
                # Извлекаем имена моделей
                return [m['name'] for m in models]
        except Exception as e:
            logging.error(f"Error fetching models: {e}")
        # Фолбэк, если API недоступен
        return ["openai", "gpt-4o-mini", "claude-3-haiku", "mistral", "llama"]

    def generate_text(self, messages, model="openai", seed=None):
        """
        Генерация текста. 
        messages: список словарей [{'role': 'user', 'content': '...'}, ...]
        """
        payload = {
            "messages": messages,
            "model": model,
            "jsonMode": False
        }
        if seed:
            payload["seed"] = seed

        try:
            # Используем POST для надежности с длинными диалогами
            response = requests.post(self.text_url, json=payload, stream=True)
            if response.status_code == 200:
                # Pollinations возвращает поток текста, собираем его
                return response.text
            else:
                return f"Error: API returned {response.status_code}"
        except Exception as e:
            return f"Connection Error: {e}"

    def generate_image_url(self, prompt, model="flux", width=1024, height=1024, seed=None):
        """Возвращает URL для генерации изображения"""
        # Чистим промпт от URL-небезопасных символов
        import urllib.parse
        encoded_prompt = urllib.parse.quote(prompt)
        url = f"{self.image_url}{encoded_prompt}?width={width}&height={height}&model={model}&nologo=true"
        if seed:
            url += f"&seed={seed}"
        return url

api = PollinationsAPI()

# --- ЛОГИКА АГЕНТА ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_first_name = update.effective_user.first_name
    welcome_text = (
        f"Привет, {user_first_name}! Я умный AI-агент.\n\n"
        "🧠 **Я умею:**\n"
        "1. Общаться разными текстовыми моделями (GPT, Claude, Mistral).\n"
        "2. Рисовать изображения (Flux, Stable Diffusion).\n"
        "3. Понимать твои просьбы о смене настроек.\n\n"
        "🖌 **Попробуй написать:**\n"
        "- *Нарисуй киберпанк город*\n"
        "- *Расскажи сказку про кота*\n"
        "- *Какие у тебя есть модели?*\n"
        "- *Включи модель gpt-4*"
    )
    # Инициализация настроек пользователя по умолчанию
    if 'text_model' not in context.user_data:
        context.user_data['text_model'] = 'openai'
    if 'image_model' not in context.user_data:
        context.user_data['image_model'] = 'flux'
    if 'history' not in context.user_data:
        context.user_data['history'] = [{"role": "system", "content": "You are a helpful AI assistant."}]

    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

async def show_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает клавиатуру с выбором типа моделей"""
    keyboard = [
        [InlineKeyboardButton("📝 Текстовые модели", callback_data='list_text_models')],
        [InlineKeyboardButton("🎨 Графические модели", callback_data='list_image_models')],
        [InlineKeyboardButton("⚙️ Текущие настройки", callback_data='show_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Что будем настраивать?", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_text_lower = user_text.lower()
    
    # Инициализация данных, если бот перезапускался
    if 'text_model' not in context.user_data: context.user_data['text_model'] = 'openai'
    if 'image_model' not in context.user_data: context.user_data['image_model'] = 'flux'
    if 'history' not in context.user_data: context.user_data['history'] = [{"role": "system", "content": "You are a helpful and smart AI assistant."}]

    # 1. АНАЛИЗ НАМЕРЕНИЙ (INTENT RECOGNITION)
    
    # A. Запрос на список моделей
    if any(phrase in user_text_lower for phrase in ["какие модели", "список моделей", "покажи модели", "what models"]):
        await show_models(update, context)
        return

    # B. Запрос на смену модели текстом (например: "Используй gpt-4")
    # Простейший поиск названия модели в тексте
    found_text_model = next((m for m in api.available_text_models if m in user_text_lower), None)
    found_image_model = next((m for m in api.available_image_models if m in user_text_lower), None)

    if "используй" in user_text_lower or "включи" in user_text_lower or "use" in user_text_lower:
        if found_text_model:
            context.user_data['text_model'] = found_text_model
            await update.message.reply_text(f"✅ Готово! Переключился на текстовую модель: **{found_text_model}**", parse_mode=ParseMode.MARKDOWN)
            return
        elif found_image_model:
            context.user_data['image_model'] = found_image_model
            await update.message.reply_text(f"✅ Готово! Теперь рисую через: **{found_image_model}**", parse_mode=ParseMode.MARKDOWN)
            return

    # C. Запрос на генерацию изображения
    # Ключевые слова-триггеры
    image_triggers = ["нарисуй", "сгенерируй", "создай изображение", "фото", "картинка", "draw", "generate image", "picture of"]
    is_image_request = any(trigger in user_text_lower for trigger in image_triggers)

    if is_image_request:
        # Пытаемся очистить промпт от триггерных слов для лучшего качества
        clean_prompt = user_text
        for trigger in image_triggers:
            clean_prompt = re.sub(trigger, "", clean_prompt, flags=re.IGNORECASE)
        clean_prompt = clean_prompt.strip()
        
        if len(clean_prompt) < 2:
            clean_prompt = user_text # Если стерли всё, используем оригинал

        current_img_model = context.user_data['image_model']
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
        
        image_url = api.generate_image_url(clean_prompt, model=current_img_model, seed=update.message.message_id)
        
        try:
            caption = f"🎨 **{current_img_model}**: {clean_prompt}"
            await update.message.reply_photo(photo=image_url, caption=caption[:1000], parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text(f"Не удалось загрузить изображение. Попробуйте еще раз. Ошибка: {e}")
        return

    # 2. ЕСЛИ ЭТО ОБЫЧНЫЙ ТЕКСТОВЫЙ ЗАПРОС
    
    # Добавляем сообщение пользователя в историю
    history = context.user_data['history']
    history.append({"role": "user", "content": user_text})
    
    # Ограничиваем историю последними 10 сообщениями, чтобы не перегружать контекст
    if len(history) > 12:
        history = [history[0]] + history[-11:] # Оставляем системный промпт + последние 10

    current_txt_model = context.user_data['text_model']
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    # Генерируем ответ
    ai_response = api.generate_text(history, model=current_txt_model)
    
    # Добавляем ответ бота в историю
    history.append({"role": "assistant", "content": ai_response})
    context.user_data['history'] = history

    # Отправляем ответ (Markdown может выдавать ошибки если модель вернет битый маркдаун, поэтому безопаснее просто текст или HTML, но попробуем MD)
    try:
        await update.message.reply_text(ai_response, parse_mode=None) # parse_mode=None чтобы избежать ошибок форматирования от нейросети
    except Exception:
        # Если ответ слишком длинный или кривой
        await update.message.reply_text(ai_response[:4000])

# --- ОБРАБОТЧИК КНОПОК ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == 'list_text_models':
        # Создаем кнопки для первых 10 моделей (Telegram не любит слишком много кнопок сразу)
        keyboard = []
        for model in api.available_text_models[:10]: # Берем топ-10
            keyboard.append([InlineKeyboardButton(model, callback_data=f"set_text_{model}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
        await query.edit_message_text(text="Выберите текстовую модель:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == 'list_image_models':
        keyboard = []
        for model in api.available_image_models:
            keyboard.append([InlineKeyboardButton(model, callback_data=f"set_image_{model}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
        await query.edit_message_text(text="Выберите модель для рисования:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("set_text_"):
        model_name = data.replace("set_text_", "")
        context.user_data['text_model'] = model_name
        await query.edit_message_text(text=f"✅ Текстовая модель изменена на: **{model_name}**", parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("set_image_"):
        model_name = data.replace("set_image_", "")
        context.user_data['image_model'] = model_name
        await query.edit_message_text(text=f"✅ Графическая модель изменена на: **{model_name}**", parse_mode=ParseMode.MARKDOWN)

    elif data == 'show_settings':
        txt = context.user_data.get('text_model', 'openai')
        img = context.user_data.get('image_model', 'flux')
        text = f"⚙️ **Текущие настройки:**\n\n📝 Текст: `{txt}`\n🎨 Картинки: `{img}`"
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
        await query.edit_message_text(text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "main_menu":
        await show_models(update, context) # Переиспользуем функцию, но нужно адаптировать message/query
        # Для простоты просто удалим старое и пришлем новое или отредактируем текст
        keyboard = [
            [InlineKeyboardButton("📝 Текстовые модели", callback_data='list_text_models')],
            [InlineKeyboardButton("🎨 Графические модели", callback_data='list_image_models')],
            [InlineKeyboardButton("⚙️ Текущие настройки", callback_data='show_settings')]
        ]
        await query.edit_message_text("Что будем настраивать?", reply_markup=InlineKeyboardMarkup(keyboard))

# --- ЗАПУСК ---

if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("models", show_models))
    
    # Обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Основной обработчик сообщений (должен быть последним)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("Bot is running...")
    application.run_polling()
