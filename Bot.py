import logging
import requests
import time
import re
import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode, ChatAction

# --- КОНФИГУРАЦИЯ ---
TOKEN = "8377691734:AAGywySfCYU8lI9UWQUHW9CHdEKFXkl2fe8"

# Логирование (чтобы видеть ошибки в консоли, а не в чате)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class PollinationsBrain:
    def __init__(self):
        self.text_url = "https://text.pollinations.ai/"
        self.image_base = "https://pollinations.ai/p/"
        
        # 1. ЖЕСТКИЙ СПИСОК БЕСПЛАТНЫХ МОДЕЛЕЙ (Самые надежные)
        # 'openai' - это авто-роутер на доступную сейчас модель (часто gpt-4o-mini)
        self.safe_text_models = ["openai", "mistral", "mistral-large", "llama", "qwen", "searchgpt"]
        self.safe_image_models = ["flux", "flux-realism", "flux-anime", "flux-3d", "turbo"]
        
        self.current_text_model = "openai" # Самая стабильная по умолчанию

    def generate_text_safe(self, messages, model_preference=None, seed=None):
        """
        Пытается сгенерировать текст. 
        Если выбранная модель падает с ошибкой 402/404, переключается на запасную.
        """
        # Если модель не передана, берем дефолтную 'openai'
        model_to_use = model_preference if model_preference else "openai"
        
        payload = {
            "messages": messages,
            "model": model_to_use,
            "jsonMode": False
        }
        if seed: payload["seed"] = seed

        try:
            # Таймаут 60 сек
            response = requests.post(self.text_url, json=payload, timeout=60)
            
            # Если успех
            if response.status_code == 200:
                return response.text
            
            # Если ошибка доступа (402) или не найдено (404) -> ПРОБУЕМ ЗАПАСНУЮ
            if response.status_code in [402, 404]:
                logger.warning(f"Model {model_to_use} failed ({response.status_code}). Switching to backup.")
                # Фолбэк на 'openai' (самый надежный бесплатный эндпоинт)
                payload["model"] = "openai"
                fallback_resp = requests.post(self.text_url, json=payload, timeout=60)
                if fallback_resp.status_code == 200:
                    return f"{fallback_resp.text}\n\n_(Примечание: Запрошенная модель недоступна, ответ от базовой модели)_"
                else:
                    return f"⚠️ Сервер перегружен (Error {fallback_resp.status_code}). Попробуйте позже."
            
            return f"Error: {response.text}"

        except requests.exceptions.Timeout:
            return "⚠️ Время ожидания истекло. Попробуйте упростить запрос."
        except Exception as e:
            return f"⚠️ Ошибка соединения: {e}"

    def generate_image_url(self, prompt, model="flux", seed=None):
        """Генерация ссылки на картинку (без 404, так как это просто ссылка)"""
        import urllib.parse
        # Очищаем промпт
        clean_prompt = re.sub(r'[^\w\s\-\.,]', '', prompt)[:300] # Убираем мусор, обрезаем длину
        encoded = urllib.parse.quote(clean_prompt)
        
        # Случайное число для seed, если не задано, чтобы картинки были разными
        if not seed:
            import random
            seed = random.randint(1, 999999)
            
        url = f"{self.image_base}{encoded}?width=1024&height=1024&model={model}&nologo=true&seed={seed}"
        return url, seed

brain = PollinationsBrain()

# --- ЛОГИКА БОТА ---

SYSTEM_PROMPT = {
    "role": "system", 
    "content": "You are a helpful AI assistant using Pollinations API. Be concise."
}

# --- ПРОВЕРКА И СБРОС КОНТЕКСТА ---
async def check_context(context, chat_id):
    last_time = context.user_data.get('last_time', 0)
    if time.time() - last_time > 3600: # 1 час
        context.user_data['history'] = [SYSTEM_PROMPT]
        context.user_data['last_time'] = time.time()
        return True
    context.user_data['last_time'] = time.time()
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['history'] = [SYSTEM_PROMPT]
    context.user_data['txt_model'] = "openai"
    context.user_data['img_model'] = "flux"
    context.user_data['last_time'] = time.time()
    
    await update.message.reply_text(
        "👋 **Я починился!**\n\n"
        "Теперь я автоматически обхожу платные модели.\n"
        "Пиши что угодно или проси *'нарисуй кота'*.\n"
        "Если модель будет недоступна, я использую запасную.",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    # 1. Проверка времени (сброс через час)
    if await check_context(context, chat_id):
        await update.message.reply_text("⏳ Начал новый диалог (прошел час).")

    # 2. Ручной сброс
    if text.lower() in ['сброс', 'reset', '/reset']:
        context.user_data['history'] = [SYSTEM_PROMPT]
        await update.message.reply_text("🧹 Память очищена.")
        return

    # 3. Смена настроек текстом ("используй модель mistral")
    lower_text = text.lower()
    if "используй" in lower_text or "use model" in lower_text:
        # Проверяем безопасные модели
        for m in brain.safe_text_models:
            if m in lower_text:
                context.user_data['txt_model'] = m
                await update.message.reply_text(f"✅ Окей, пробую использовать модель: **{m}**", parse_mode=ParseMode.MARKDOWN)
                return
        for m in brain.safe_image_models:
            if m in lower_text:
                context.user_data['img_model'] = m
                await update.message.reply_text(f"🎨 Для рисования теперь: **{m}**", parse_mode=ParseMode.MARKDOWN)
                return

    # 4. Рисование
    draw_triggers = ["нарисуй", "сгенерируй", "фото", "draw", "image"]
    if any(text.lower().startswith(t) for t in draw_triggers):
        # Чистим запрос
        prompt = text
        for t in draw_triggers:
            prompt = re.sub(t, "", prompt, flags=re.IGNORECASE)
        
        model = context.user_data.get('img_model', 'flux')
        
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        
        # Генерируем URL
        img_url, seed = brain.generate_image_url(prompt, model=model)
        
        try:
            # Попытка отправить фото (Telegram сам загрузит по ссылке)
            await update.message.reply_photo(img_url, caption=f"🖼 **{model}** (Seed: {seed})", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            # Если Telegram не смог загрузить (таймаут), отправляем ссылкой
            await update.message.reply_text(f"⚠️ Не смог загрузить картинку в чат (сервер занят), но вот ссылка:\n{img_url}")
        return

    # 5. Текст
    current_model = context.user_data.get('txt_model', 'openai')
    history = context.user_data.get('history', [SYSTEM_PROMPT])
    history.append({"role": "user", "content": text})
    
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    
    # ВАЖНО: Вызов безопасной функции генерации
    response_text = brain.generate_text_safe(history, model_preference=current_model)
    
    history.append({"role": "assistant", "content": response_text})
    if len(history) > 12: history = [history[0]] + history[-11:]
    context.user_data['history'] = history
    
    await update.message.reply_text(response_text)


# --- КНОПКИ (Только рабочие) ---
async def show_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    # Текстовые
    row = []
    for m in ["openai", "mistral", "searchgpt"]:
        row.append(InlineKeyboardButton(m, callback_data=f"set_{m}"))
    keyboard.append(row)
    
    # Картинки
    row = []
    for m in ["flux", "flux-realism", "flux-anime"]:
        row.append(InlineKeyboardButton(m, callback_data=f"img_{m}"))
    keyboard.append(row)
    
    await update.message.reply_text("🛠 **Рабочие модели:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("set_"):
        m = data.split("_")[1]
        context.user_data['txt_model'] = m
        await query.edit_message_text(f"Текст: {m}")
    elif data.startswith("img_"):
        m = data.split("_")[1]
        context.user_data['img_model'] = m
        await query.edit_message_text(f"Картинки: {m}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("models", show_models))
    app.add_handler(CallbackQueryHandler(btn_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot fixed and running...")
    app.run_polling()
