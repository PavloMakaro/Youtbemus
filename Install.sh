#!/bin/bash

# Проверка, запущен ли скрипт от root
if [ "$(id -u)" != "0" ]; then
    echo "Этот скрипт должен быть запущен с правами root. Используйте sudo."
    exit 1
fi

# Переходим в директорию для установки
INSTALL_DIR="/opt/youtube_music_bot"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR" || { echo "Не удалось перейти в директорию $INSTALL_DIR"; exit 1; }

# Остановка старого бота, если он запущен
echo "Проверка запущенного бота..."
if systemctl is-active --quiet youtube_music_bot.service; then
    echo "Останавливаю работающий бот..."
    systemctl stop youtube_music_bot.service
    sleep 3
    echo "Старый бот остановлен."
else
    echo "Бот не запущен, продолжаем установку..."
fi

echo "Загрузка файла bot.py с GitHub..."
wget -qO bot.py https://raw.githubusercontent.com/PavloMakaro/Youtbemus/main/Bot.py

if [ $? -ne 0 ]; then
    echo "Ошибка: Не удалось загрузить bot.py. Проверьте путь и доступность файла."
    exit 1
fi

echo "Создание файла requirements.txt..."
cat > requirements.txt << EOF
python-telegram-bot==20.7
yt-dlp==2023.11.16
ffmpeg-python==0.2.0
requests==2.31.0
aiogram 
aiohttp
EOF

echo "Обновление списка пакетов..."
apt update -y

echo "Установка необходимых пакетов..."
apt install python3-full ffmpeg wget curl -y

# Создание и активация виртуального окружения
echo "Создание виртуального окружения..."
python3 -m venv youtube_bot_env

echo "Активация виртуального окружения..."
source youtube_bot_env/bin/activate

# Установка зависимостей
echo "Установка зависимостей из requirements.txt..."
pip install --upgrade pip
pip install -r requirements.txt

# Проверяем установку FFmpeg
echo "Проверка установки FFmpeg..."
if ! command -v ffmpeg &> /dev/null; then
    echo "❌ FFmpeg не установлен. Пытаюсь установить..."
    apt install ffmpeg -y
fi

# Проверяем установку Python пакетов
echo "Проверка установленных пакетов..."
pip list | grep -E "(telegram|yt-dlp|ffmpeg)"

# Создаем systemd юнит для автозапуска бота
echo "Создание systemd юнита для бота..."
SERVICE_FILE="/etc/systemd/system/youtube_music_bot.service"

cat << EOF > "$SERVICE_FILE"
[Unit]
Description=YouTube Music Downloader Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment=PATH=$INSTALL_DIR/youtube_bot_env/bin
ExecStart=$INSTALL_DIR/youtube_bot_env/bin/python3 $INSTALL_DIR/bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Настройка прав
echo "Настройка прав доступа..."
chmod 644 "$SERVICE_FILE"
chmod +x bot.py

# Включение и запуск сервиса
echo "Перезагрузка systemd демона..."
systemctl daemon-reload
echo "Включение сервиса youtube_music_bot..."
systemctl enable youtube_music_bot.service

echo "Запуск нового бота..."
systemctl start youtube_music_bot.service

# Проверка статуса
echo "Ожидание запуска бота..."
sleep 7

if systemctl is-active --quiet youtube_music_bot.service; then
    echo "✅ Новый бот успешно запущен!"
    echo "📝 Токен бота: 8377691734:AAGywySfCYU8lI9UWQUHW9CHdEKFXkl2fe8"
else
    echo "⚠️  Бот не запустился автоматически. Проверяем логи..."
    journalctl -u youtube_music_bot.service -n 10 --no-pager
    echo ""
    echo "📋 Для просмотра полных логов выполните: journalctl -u youtube_music_bot.service -f"
fi

# Деактивация виртуального окружения
deactivate

echo ""
echo "🎵 YouTube Music Downloader Bot успешно установлен/обновлен!"
echo ""
echo "📋 Команды управления:"
echo "   Статус бота: systemctl status youtube_music_bot.service"
echo "   Просмотр логов: journalctl -u youtube_music_bot.service -f"
echo "   Остановить бота: systemctl stop youtube_music_bot.service"
echo "   Перезапустить бота: systemctl restart youtube_music_bot.service"
echo "   Включить автозапуск: systemctl enable youtube_music_bot.service"
echo ""
echo "🤖 Бот будет автоматически запускаться после перезагрузки сервера."
echo "📁 Директория установки: $INSTALL_DIR"
echo "🔧 Виртуальное окружение: $INSTALL_DIR/youtube_bot_env"
echo ""
echo "⚠️  Токен бота уже встроен в код: 8377691734:AAGywySfCYU8lI9UWQUHW9CHdEKFXkl2fe8"
