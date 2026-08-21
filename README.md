# 🧠 Telegram Second Brain

Telegram-native личная база знаний. Пользователь пересылает боту пост, ссылку, файл, видео или заметку, а бот сохраняет материал, определяет категорию и делает его доступным в Mini App. Поиск работает по словам без внешних сервисов и по смыслу, если подключён OpenAI API.

## Что уже работает

- сохранение текста, ссылок, фото, видео, аудио, voice и документов;
- сохранение источника пересланного сообщения и ссылки на публичный Telegram-канал;
- автоматические категории плюс создание и переименование личных категорий;
- SQLite + FTS5 для быстрого полнотекстового поиска и Railway Volume для постоянного хранения;
- embeddings и семантический поиск человеческим языком;
- избранное, прочитано/не прочитано и умные напоминания свободной фразой;
- OCR изображений, чтение PDF/TXT и расшифровка аудио/видео через OpenAI;
- массовый выбор карточек и групповые действия;
- полное удаление профиля и всех связанных данных с двойным подтверждением;
- AI-суммаризация с локальным extractive fallback;
- адаптивный Telegram Mini App;
- проверка подписи `Telegram.WebApp.initData` на сервере;
- бесплатный лимит сохранений и ежемесячная PRO-подписка через Telegram Stars;
- Docker/Compose, healthcheck и тесты.

## Архитектура

```text
Telegram message ──► aiogram bot ──► classifier ──► SQLite + FTS5
                           │                              │
                           ├──► OpenAI embeddings         │
                           ├──► reminder worker           │
                           └──► Stars subscription        │
                                                          ▼
Telegram Mini App ◄──── FastAPI + initData validation ◄── API
```

Бот, REST API, статический Mini App и воркер напоминаний запускаются одним процессом. Для polling должен работать ровно один экземпляр приложения. При горизонтальном масштабировании вынесите бота и воркер в отдельный процесс либо перейдите на webhook.

## Быстрый запуск

### 1. Создайте Telegram-бота

1. Откройте [@BotFather](https://t.me/BotFather).
2. Выполните `/newbot` и задайте имя, например `Second Brain`.
3. Выберите свободный username, например `savebrain_bot` (конкретное имя может быть занято).
4. Скопируйте выданный токен.

### 2. Подготовьте окружение

Требуется Python 3.11+.

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
cp .env.example .env
```

На Windows вместо `cp` используйте:

```powershell
Copy-Item .env.example .env
```

Минимально заполните `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=токен_от_BotFather
PUBLIC_URL=https://ваш-публичный-домен.example
```

Проверьте токен и установите список команд бота:

```bash
python scripts/setup_bot.py
```

`PUBLIC_URL` обязан быть HTTPS-адресом этого же приложения. Без него бот и локальная веб-версия работают, но Telegram не покажет кнопку Mini App.

### 3. Запустите

```bash
python -m app
```

Локальные адреса:

- Mini App: <http://localhost:8000>
- healthcheck: <http://localhost:8000/api/health>
- OpenAPI в dev-режиме: <http://localhost:8000/docs>

В обычном браузере Mini App использует тестового пользователя `1`, только когда `DEV_MODE=true`. В production этот обход обязательно должен быть выключен.

## Запуск через Docker

```bash
cp .env.example .env
# заполните .env
docker compose up --build -d
docker compose logs -f second-brain
```

SQLite хранится в named volume `second-brain-data`.

## AI-поиск и суммаризация

Без `OPENAI_API_KEY` используется локальный FTS5 и локальная краткая выжимка. Если ключ задан,
при сохранении создаётся embedding, поиск смешивает семантическую близость с полнотекстовым
совпадением, а кнопка `✨ AI-кратко` суммаризирует текст через OpenAI Responses API.

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_TEXT_MODEL=gpt-5.4-nano
OPENAI_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
```

Старые записи, созданные без ключа, продолжат находиться полнотекстовым поиском. Для production имеет смысл добавить фоновый backfill embeddings и заменить JSON-векторы в SQLite на pgvector/Qdrant при росте коллекций выше нескольких тысяч объектов на пользователя.

## PRO через Telegram Stars

Команда `/pro` отправляет подписной invoice:

- валюта `XTR`;
- период 30 дней (`2592000` секунд);
- цена из `PRO_PRICE_STARS`;
- pre-checkout проверяет payload, валюту и сумму;
- доступ включается только после `successful_payment`;
- `telegram_payment_charge_id` сохраняется для идемпотентности и возможного возврата.

Перед production-запуском обязательно замените:

```dotenv
SUPPORT_USERNAME=реальный_username_поддержки
TERMS_URL=https://ваш-домен.example/terms
```

Проверьте команды `/terms` и `/paysupport`, протестируйте оплату в тестовом окружении Telegram и настройте резервное копирование БД с таблицей `payments`.

## Команды бота

| Команда | Назначение |
|---|---|
| `/start` | приветствие и кнопка Mini App |
| `/app` | открыть личную базу |
| `/search запрос` | поиск по смыслу или FTS |
| `/stats` | статистика коллекции |
| `/pro` | подписка PRO через Stars |
| `/terms` | условия использования |
| `/paysupport` | помощь по оплате |
| `/help` | краткая инструкция |

После сохранения доступны inline-действия: избранное, прочитано, напомнить завтра, через месяц или обычной фразой и суммаризировать.
Категорию можно изменить кнопкой `📂 Категория`, а активное напоминание — отменить кнопкой `🔕`.
В Mini App кнопка `⚙ Категории` создаёт новые категории и переименовывает любые существующие.
Кнопка `Выбрать` включает массовое управление, а `Приватность и данные` позволяет полностью удалить аккаунт.

## Постоянная база данных на Railway

Файл SQLite внутри обычного Railway deployment хранится на временном диске и исчезает при
следующем развёртывании. Чтобы данные сохранялись:

1. В проекте Railway откройте сервис `NuvraBot` → **Volumes** → **Add Volume**.
2. Укажите mount path `/app/data`.
3. В **Variables** добавьте `RAILWAY_RUN_UID=0`, потому что Railway монтирует Volume от root.
4. Сделайте redeploy. `RAILWAY_VOLUME_MOUNT_PATH` Railway добавит автоматически; приложение
   само выберет `/app/data/second_brain.sqlite3`.
5. Откройте `/api/health` и убедитесь, что `storage_persistent` равен `true`.

После этого сохранения, категории, напоминания, PRO-статус и платежи переживают redeploy.
Для восстановления данных настройте расписание в разделе **Backups** подключённого Volume.

## Настройки

| Переменная | По умолчанию | Описание |
|---|---:|---|
| `TELEGRAM_BOT_TOKEN` | пусто | токен BotFather |
| `PUBLIC_URL` | пусто | публичный HTTPS URL Mini App |
| `DATABASE_PATH` | `data/second_brain.sqlite3` | файл SQLite |
| `DEV_MODE` | `true` | dev-доступ к API и `/docs` |
| `RUN_BOT` | `true` | запуск polling в процессе API |
| `FREE_ITEMS_LIMIT` | `500` | бесплатный лимит |
| `PRO_PRICE_STARS` | `299` | цена за 30 дней в Stars |
| `REMINDER_POLL_SECONDS` | `30` | частота проверки напоминаний |
| `OPENAI_TRANSCRIPTION_MODEL` | `gpt-4o-mini-transcribe` | модель распознавания речи |
| `RECOGNITION_MAX_BYTES` | `20000000` | максимальный размер вложения для распознавания |
| `MEDIA_CONTEXT_WINDOW_SECONDS` | `600` | сколько секунд ждать отдельное описание после медиа без подписи |
| `OPENAI_API_KEY` | пусто | включает AI-возможности |

## Проверки

```bash
ruff check .
pytest
```

Для локального просмотра интерфейса с демо-данными:

```bash
python scripts/seed_demo.py
python -m app
```

Откройте <http://localhost:8000> при `DEV_MODE=true`.

## Безопасность и production checklist

- Никогда не коммитьте `.env` и токены.
- Отключите `DEV_MODE`.
- Используйте HTTPS и один стабильный origin Mini App.
- Храните резервные копии `data/second_brain.sqlite3` и проверяйте восстановление.
- Ограничьте доступ к `/docs` и логам.
- Добавьте rate limiting на API перед публичным масштабированием.
- Установите настоящие условия, privacy policy и контакт поддержки.
- Не запускайте несколько polling-процессов с одним токеном.

## Ближайшие расширения

- OCR изображений и PDF;
- расшифровка voice/audio;
- ручные теги и вложенные коллекции;
- импорт истории Telegram;
- PostgreSQL + pgvector для масштабирования;
- webhook deployment и очередь фоновых задач;
- управление/отмена Stars-подписки и административная панель возвратов.

## Лицензия

MIT
