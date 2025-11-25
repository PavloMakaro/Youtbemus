import os
import logging
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import yt_dlp
import tempfile
import asyncio
from urllib.parse import urlparse

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = "8377691734:AAGywySfCYU8lI9UWQUHW9CHdEKFXkl2fe8"

class YouTubeDownloader:
    def __init__(self):
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': '%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'noplaylist': False,
        }

    def download_audio(self, url, download_path):
        """Скачивание аудио"""
        try:
            opts = self.ydl_opts.copy()
            opts['outtmpl'] = os.path.join(download_path, '%(title)s.%(ext)s')
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)
                base = os.path.splitext(downloaded_file)[0]
                mp3_file = base + '.mp3'
                
                if os.path.exists(mp3_file):
                    return mp3_file, info
                elif os.path.exists(downloaded_file):
                    return downloaded_file, info
                else:
                    return None, info
                    
        except Exception as e:
            logger.error(f"Ошибка скачивания: {e}")
            return None, None

    def get_playlist_info(self, url):
        """Получение информации о плейлисте"""
        try:
            opts = {
                'extract_flat': True,
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    return {
                        'title': info.get('title', 'Неизвестный плейлист'),
                        'video_count': len(info['entries']),
                        'videos': [
                            {
                                'title': entry.get('title', 'Неизвестно'),
                                'url': f"https://www.youtube.com/watch?v={entry['id']}",
                                'id': entry['id']
                            }
                            for entry in info['entries']
                        ]
                    }
                return None
        except Exception as e:
            logger.error(f"Ошибка получения информации о плейлисте: {e}")
            return None

async def start(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /start"""
    user = update.effective_user
    logger.info(f"Пользователь {user.first_name} (ID: {user.id}) запустил бота")
    
    welcome_text = """
🎵 YouTube Music Downloader

Отправьте ссылку на:
• YouTube видео - для скачивания одного трека
• YouTube плейлист - для скачивания всего плейлиста

Бот автоматически определит тип контента и начнет загрузку.
    """
    
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /help"""
    help_text = """
🤖 Помощь:

📥 Просто отправьте ссылку на YouTube видео или плейлист

🔗 Поддерживаемые форматы:
• https://www.youtube.com/watch?v=...
• https://youtu.be/...
• https://www.youtube.com/playlist?list=...

⚡ Плейлисты скачиваются потоком без лишних сообщений
    """
    
    await update.message.reply_text(help_text)

async def handle_message(update: Update, context: CallbackContext) -> None:
    """Обработчик текстовых сообщений"""
    user = update.effective_user
    text = update.message.text
    
    logger.info(f"Пользователь {user.id} отправил: {text}")
    
    if is_youtube_url(text):
        if 'playlist' in text:
            await process_playlist(update, context, text)
        else:
            await process_single_video(update, context, text)
    else:
        await update.message.reply_text("❌ Отправьте валидную YouTube ссылку")

async def process_single_video(update: Update, context: CallbackContext, url: str) -> None:
    """Обработка скачивания одиночного видео"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    try:
        status_msg = await update.message.reply_text("⏬ Скачиваю аудио...")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = YouTubeDownloader()
            
            audio_file, info = downloader.download_audio(url, temp_dir)
            
            if not audio_file or not os.path.exists(audio_file):
                await status_msg.edit_text("❌ Ошибка при скачивании")
                return
            
            file_size = os.path.getsize(audio_file)
            if file_size > 50 * 1024 * 1024:
                await status_msg.edit_text("❌ Файл слишком большой (максимум 50MB)")
                return
            
            # Отправляем файл с обложкой и метаданными
            title = info.get('title', 'Аудио') if info else 'Аудио'
            uploader = info.get('uploader', 'Неизвестно') if info else 'Неизвестно'
            thumbnail = info.get('thumbnail', '') if info else ''
            
            with open(audio_file, 'rb') as audio:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=InputFile(audio, filename=os.path.basename(audio_file)),
                    title=title[:64],  # Ограничение длины названия
                    performer=uploader[:64],  # Ограничение длины исполнителя
                    thumb=thumbnail if thumbnail else None
                )
            
            await status_msg.delete()
            logger.info(f"Успешно отправлен аудиофайл пользователю {user.id}")
            
    except Exception as e:
        logger.error(f"Ошибка при обработке видео для пользователя {user.id}: {e}")
        await update.message.reply_text("❌ Ошибка при обработке видео")

async def process_playlist(update: Update, context: CallbackContext, url: str) -> None:
    """Обработка скачивания плейлиста - УСКОРЕННАЯ ВЕРСИЯ"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    try:
        status_msg = await update.message.reply_text("🎵 Обрабатываю плейлист...")
        
        downloader = YouTubeDownloader()
        playlist_info = downloader.get_playlist_info(url)
        
        if not playlist_info:
            await status_msg.edit_text("❌ Не удалось получить информацию о плейлисте")
            return
        
        total_videos = len(playlist_info['videos'])
        await status_msg.edit_text(f"🎵 Найден плейлист: {playlist_info['title']}\n📊 Треков: {total_videos}\n\n⏬ Начинаю загрузку...")
        
        successful_downloads = 0
        failed_downloads = 0
        
        # Скачиваем каждое видео из плейлиста БЕЗ ЛИШНИХ СООБЩЕНИЙ
        for index, video in enumerate(playlist_info['videos'], 1):
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    audio_file, info = downloader.download_audio(video['url'], temp_dir)
                    
                    if audio_file and os.path.exists(audio_file):
                        file_size = os.path.getsize(audio_file)
                        if file_size <= 50 * 1024 * 1024:  # 50MB limit
                            title = info.get('title', 'Аудио') if info else 'Аудио'
                            uploader = info.get('uploader', 'Неизвестно') if info else 'Неизвестно'
                            thumbnail = info.get('thumbnail', '') if info else ''
                            
                            with open(audio_file, 'rb') as audio:
                                await context.bot.send_audio(
                                    chat_id=chat_id,
                                    audio=InputFile(audio, filename=os.path.basename(audio_file)),
                                    title=title[:64],
                                    performer=uploader[:64],
                                    thumb=thumbnail if thumbnail else None
                                )
                            successful_downloads += 1
                            logger.info(f"Успешно скачан файл {index}/{total_videos} для пользователя {user.id}")
                        else:
                            failed_downloads += 1
                            logger.warning(f"Файл слишком большой: {video['title']}")
                    else:
                        failed_downloads += 1
                        logger.error(f"Ошибка скачивания файла: {video['title']}")
                
                # Небольшая задержка между отправками чтобы не перегружать
                if index % 5 == 0:  # Каждые 5 треков
                    await asyncio.sleep(1)
                
            except Exception as e:
                failed_downloads += 1
                logger.error(f"Ошибка при скачивании видео {index}: {e}")
                continue
        
        # Финальное сообщение только с результатом
        result_text = f"""
✅ Завершено скачивание плейлиста!
📁 {playlist_info['title']}
✅ Успешно: {successful_downloads} треков
❌ Не удалось: {failed_downloads} треков
        """
        await update.message.reply_text(result_text)
        logger.info(f"Завершено скачивание плейлиста для пользователя {user.id}: {successful_downloads}/{total_videos} успешно")
        
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"Критическая ошибка при обработке плейлиста для пользователя {user.id}: {e}")
        await update.message.reply_text("❌ Ошибка при обработке плейлиста")

def is_youtube_url(url: str) -> bool:
    """Проверка, является ли ссылка YouTube ссылкой"""
    parsed = urlparse(url)
    return any(domain in parsed.netloc for domain in ['youtube.com', 'youtu.be'])

def main() -> None:
    """Основная функция запуска бота"""
    logger.info("Запуск YouTube Music Downloader Bot...")
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    logger.info("Бот запущен и готов к работе!")
    print("🤖 Бот запущен! Нажмите Ctrl+C для остановки")
    
    application.run_polling()

if __name__ == '__main__':
    main()
