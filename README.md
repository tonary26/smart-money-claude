# SMC Full Bot

Telegram-бот сканирует фьючерсные пары Bybit по существующей SMC-логике,
отправляет сигналы и контролирует сценарии A/B. Бот использует Telegram
polling, поэтому домен, SSL-сертификат и открытые входящие порты не нужны.

## Структура

- `bot.py` - точка запуска.
- `smc_bot/config.py` - переменные окружения и существующие константы.
- `smc_bot/exchange.py` - клиент Bybit и загрузка свечей.
- `smc_bot/watchlist.py` - чтение и запись `coins.json`.
- `smc_bot/state.py` - типы состояния экземпляра бота.
- `smc_bot/analysis.py` - существующая логика SMC-анализа.
- `smc_bot/simulation.py` - существующие сценарии A/B и мониторинг.
- `smc_bot/handlers.py` - Telegram-команды.
- `smc_bot/jobs.py` - сканирование и мониторинг.
- `smc_bot/app.py` - сборка и запуск Telegram-приложения.

## Развертывание на Beget

Нужен облачный VPS/VDS Beget, а не обычный виртуальный хостинг. При создании
сервера выберите готовый образ Docker: в нём уже установлены Docker и Docker
Compose.

Подключитесь к серверу по SSH:

```bash
ssh root@IP_СЕРВЕРА
```

Установите Git, если его нет:

```bash
apt update
apt install -y git
```

Загрузите проект:

```bash
cd /opt
git clone URL_РЕПОЗИТОРИЯ smart-money
cd smart-money
```

Создайте серверный файл с секретами:

```bash
cp .env.example .env
nano .env
```

Заполните четыре значения:

```dotenv
BYBIT_API_KEY=...
BYBIT_API_SECRET=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Запустите бота:

```bash
docker compose up -d --build
```

Проверьте контейнер и логи:

```bash
docker compose ps
docker compose logs -f bot
```

Контейнер использует `restart: unless-stopped`, поэтому автоматически
перезапускается после ошибки и перезагрузки VPS.

## Управление

Перезапуск:

```bash
docker compose restart bot
```

Обновление:

```bash
git pull
docker compose up -d --build
```

Остановка:

```bash
docker compose down
```

Резервная копия списка монет:

```bash
cp coins.json "coins.backup.$(date +%Y%m%d-%H%M%S).json"
```

`coins.json` подключён в контейнер как bind mount. Изменения через `/add` и
`/remove` сохраняются после перезапуска и пересборки.

## Безопасность

`.env` не копируется в Docker-образ и не должен попадать в Git. Поскольку файл
раньше отслеживался репозиторием, перед публикацией необходимо перевыпустить
ключи Bybit и токен Telegram. Удаление `.env` из текущего состояния Git не
удаляет секреты из старых коммитов.

Не публикуйте содержимое `.env` в сообщениях, логах и скриншотах.

## Локальная проверка

```powershell
$env:PYTHONPATH=(Resolve-Path '.deps').Path
python -m unittest discover -s tests -v
python -m compileall bot.py smc_bot tests
docker compose --env-file .env.example config
```
