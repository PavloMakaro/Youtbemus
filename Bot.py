import os
import logging
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import yt_dlp
import requests
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
            'quiet': False,
            'no_warnings': False,
        }

    def get_video_info(self, url):
        """Получение информации о видео"""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', 'Неизвестно'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Неизвестно'),
                    'thumbnail': info.get('thumbnail', ''),
                    'url': url
                }
        except Exception as e:
            logger.error(f"Ошибка получения информации: {e}")
            return None

    def download_audio(self, url, download_path):
        """Скачивание аудио"""
        try:
            opts = self.ydl_opts.copy()
            opts['outtmpl'] = os.path.join(download_path, '%(title)s.%(ext)s')
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)
                # Заменяем расширение на .mp3 после обработки
                base = os.path.splitext(downloaded_file)[0]
                mp3_file = base + '.mp3'
                
                if os.path.exists(mp3_file):
                    return mp3_file
                elif os.path.exists(downloaded_file):
                    return downloaded_file
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"Ошибка скачивания: {e}")
            return None

    def get_playlist_info(self, url):
        """Получение информации о плейлисте"""
        try:
            opts = {
                'extract_flat': True,
                'quiet': False,
                'no_warnings': False,
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
                                'duration': entry.get('duration', 0)
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
🎵 Добро пожаловать в YouTube Music Downloader! 🎵

Я могу скачать аудио из YouTube видео и плейлистов.

📋 Доступные команды:
/start - начать работу
/download - скачать аудио
/playlist - скачать плейлист
/help - помощь

📝 Просто отправьте мне ссылку на YouTube видео или плейлист, и я скачаю аудио!

⚠️ Внимание: Используйте бота только для скачивания контента, на который у вас есть права.
    """
    
    await update.message.reply_text(welcome_text)
    logger.info(f"Отправлено приветственное сообщение пользователю {user.id}")

async def help_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /help"""
    user = update.effective_user
    logger.info(f"Пользователь {user.id} запросил помощь")
    
    help_text = """
🤖 Помощь по использованию бота:

📥 Скачать одно видео:
Отправьте команду /download или просто пришлите ссылку на YouTube видео

🎵 Скачать плейлист:
Отправьте команду /playlist или пришлите ссылку на YouTube плейлист

🔗 Поддерживаемые форматы ссылок:
• https://www.youtube.com/watch?v=...
• https://youtu.be/...
• https://www.youtube.com/playlist?list=...
• https://youtube.com/playlist?list=...

⚡ Бот автоматически определит тип контента по ссылке!

📊 Лимиты:
• Максимальный размер файла: 50MB (ограничение Telegram)
• Для больших файлов используйте сжатое аудио
    """
    
    await update.message.reply_text(help_text)
    logger.info(f"Отправлена помощь пользователю {user.id}")

async def handle_download(update: Update, context: CallbackContext) -> None:
    """Обработчик скачивания одиночного видео"""
    user = update.effective_user
    logger.info(f"Пользователь {user.id} начал процесс скачивания")
    
    if not context.args and not update.message.text:
        await update.message.reply_text("❌ Пожалуйста, отправьте ссылку на YouTube видео после команды /download или просто пришлите ссылку")
        return
    
    url = context.args[0] if context.args else update.message.text
    
    if not is_youtube_url(url):
        await update.message.reply_text("❌ Это не похоже на валидную YouTube ссылку")
        logger.warning(f"Пользователь {user.id} отправил невалидную ссылку: {url}")
        return
    
    await process_single_video(update, context, url)

async def handle_playlist(update: Update, context: CallbackContext) -> None:
    """Обработчик скачивания плейлиста"""
    user = update.effective_user
    logger.info(f"Пользователь {user.id} начал процесс скачивания плейлиста")
    
    if not context.args and not update.message.text:
        await update.message.reply_text("❌ Пожалуйста, отправьте ссылку на YouTube плейлист после команды /playlist")
        return
    
    url = context.args[0] if context.args else update.message.text
    
    if not is_youtube_url(url):
        await update.message.reply_text("❌ Это не похоже на валидную YouTube ссылку")
        logger.warning(f"Пользователь {user.id} отправил невалидную ссылку плейлиста: {url}")
        return
    
    await process_playlist(update, context, url)

async def handle_message(update: Update, context: CallbackContext) -> None:
    """Обработчик текстовых сообщений"""
    user = update.effective_user
    text = update.message.text
    
    logger.info(f"Пользователь {user.id} отправил сообщение: {text}")
    
    if is_youtube_url(text):
        if 'playlist' in text:
            await process_playlist(update, context, text)
        else:
            await process_single_video(update, context, text)
    else:
        await update.message.reply_text("❌ Пожалуйста, отправьте валидную YouTube ссылку")
        logger.warning(f"Пользователь {user.id} отправил не YouTube ссылку: {text}")

async def process_single_video(update: Update, context: CallbackContext, url: str) -> None:
    """Обработка скачивания одиночного видео"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    try:
        # Отправляем сообщение о начале обработки
        status_msg = await update.message.reply_text("🔍 Получаю информацию о видео...")
        logger.info(f"Начата обработка видео для пользователя {user.id}: {url}")
        
        # Создаем временную директорию
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = YouTubeDownloader()
            
            # Получаем информацию о видео
            video_info = downloader.get_video_info(url)
            if not video_info:
                await status_msg.edit_text("❌ Не удалось получить информацию о видео. Проверьте ссылку.")
                logger.error(f"Ошибка получения информации о видео для пользователя {user.id}")
                return
            
            # Обновляем статус
            duration_str = format_duration(video_info['duration'])
            info_text = f"""
🎬 Информация о видео:
📝 Название: {video_info['title']}
⏱ Длительность: {duration_str}
👤 Автор: {video_info['uploader']}
            """
            await status_msg.edit_text(info_text + "\n\n⏬ Начинаю скачивание...")
            logger.info(f"Получена информация о видео для пользователя {user.id}: {video_info['title']}")
            
            # Скачиваем аудио
            await status_msg.edit_text("📥 Скачиваю аудио...")
            audio_file = downloader.download_audio(url, temp_dir)
            
            if not audio_file or not os.path.exists(audio_file):
                await status_msg.edit_text("❌ Ошибка при скачивании аудио")
                logger.error(f"Ошибка скачивания аудио для пользователя {user.id}")
                return
            
            # Отправляем файл
            await status_msg.edit_text("📤 Отправляю аудиофайл...")
            logger.info(f"Начинаю отправку файла пользователю {user.id}: {audio_file}")
            
            file_size = os.path.getsize(audio_file)
            if file_size > 50 * 1024 * 1024:  # 50MB limit
                await status_msg.edit_text("❌ Файл слишком большой для отправки через Telegram (максимум 50MB)")
                logger.warning(f"Файл слишком большой для пользователя {user.id}: {file_size} bytes")
                return
            
            with open(audio_file, 'rb') as audio:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=InputFile(audio, filename=os.path.basename(audio_file)),
                    title=video_info['title'],
                    performer=video_info['uploader'],
                    caption=f"🎵 {video_info['title']}\n👤 {video_info['uploader']}"
                )
            
            await status_msg.delete()
            logger.info(f"Успешно отправлен аудиофайл пользователю {user.id}")
            
    except Exception as e:
        logger.error(f"Критическая ошибка при обработке видео для пользователя {user.id}: {e}")
        await update.message.reply_text("❌ Произошла ошибка при обработке видео")
        try:
            await status_msg.delete()
        except:
            pass

async def process_playlist(update: Update, context: CallbackContext, url: str) -> None:
    """Обработка скачивания плейлиста"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    try:
        status_msg = await update.message.reply_text("🔍 Анализирую плейлист...")
        logger.info(f"Начата обработка плейлиста для пользователя {user.id}: {url}")
        
        downloader = YouTubeDownloader()
        playlist_info = downloader.get_playlist_info(url)
        
        if not playlist_info:
            await status_msg.edit_text("❌ Не удалось получить информацию о плейлисте")
            logger.error(f"Ошибка получения информации о плейлисте для пользователя {user.id}")
            return
        
        # Показываем информацию о плейлисте
        info_text = f"""
🎵 Информация о плейлисте:
📁 Название: {playlist_info['title']}
📊 Количество видео: {playlist_info['video_count']}

⚠️ Скачивание плейлиста может занять некоторое время.
Начинаю обработку...
        """
        await status_msg.edit_text(info_text)
        logger.info(f"Начат процесс скачивания плейлиста для пользователя {user.id}: {playlist_info['title']}")
        
        successful_downloads = 0
        total_videos = len(playlist_info['videos'])
        
        # Скачиваем каждое видео из плейлиста
        for index, video in enumerate(playlist_info['videos'], 1):
            try:
                progress_msg = await update.message.reply_text(
                    f"📥 Скачиваю {index}/{total_videos}: {video['title']}"
                )
                logger.info(f"Скачивание {index}/{total_videos} для пользователя {user.id}: {video['title']}")
                
                with tempfile.TemporaryDirectory() as temp_dir:
                    audio_file = downloader.download_audio(video['url'], temp_dir)
                    
                    if audio_file and os.path.exists(audio_file):
                        file_size = os.path.getsize(audio_file)
                        if file_size <= 50 * 1024 * 1024:  # 50MB limit
                            with open(audio_file, 'rb') as audio:
                                await context.bot.send_audio(
                                    chat_id=chat_id,
                                    audio=InputFile(audio, filename=os.path.basename(audio_file)),
                                    title=video['title'],
                                    caption=f"🎵 {video['title']}\n📁 Из плейлиста: {playlist_info['title']}\n#{index}"
                                )
                            successful_downloads += 1
                            logger.info(f"Успешно скачан файл {index} для пользователя {user.id}")
                        else:
                            logger.warning(f"Файл слишком большой для отправки: {video['title']}")
                    else:
                        logger.error(f"Ошибка скачивания файла: {video['title']}")
                
                await progress_msg.delete()
                await asyncio.sleep(1)  # Задержка между отправками
                
            except Exception as e:
                logger.error(f"Ошибка при скачивании видео {index} для пользователя {user.id}: {e}")
                continue
        
        # Финальное сообщение
        result_text = f"""
✅ Завершено скачивание плейлиста!
📁 Плейлист: {playlist_info['title']}
✅ Успешно скачано: {successful_downloads}/{total_videos} треков
        """
        await update.message.reply_text(result_text)
        logger.info(f"Завершено скачивание плейлиста для пользователя {user.id}: {successful_downloads}/{total_videos} успешно")
        
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"Критическая ошибка при обработке плейлиста для пользователя {user.id}: {e}")
        await update.message.reply_text("❌ Произошла ошибка при обработке плейлиста")
        try:
            await status_msg.delete()
        except:
            pass

def is_youtube_url(url: str) -> bool:
    """Проверка, является ли ссылка YouTube ссылкой"""
    parsed = urlparse(url)
    return any(domain in parsed.netloc for domain in ['youtube.com', 'youtu.be'])

def format_duration(seconds: int) -> str:
    """Форматирование длительности в читаемый вид"""
    if not seconds:
        return "Неизвестно"
    
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"

def main() -> None:
    """Основная функция запуска бота"""
    logger.info("Запуск YouTube Music Downloader Bot...")
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("download", handle_download))
    application.add_handler(CommandHandler("playlist", handle_playlist))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    logger.info("Бот запущен и готов к работе!")
    print("🤖 Бот запущен! Нажмите Ctrl+C для остановки")
    
    application.run_polling()

if __name__ == '__main__':
    main()
