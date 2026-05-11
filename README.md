# MaxTarobot (MAX Messenger)

## Что это
`MaxTarobot` — бот Таро для мессенджера MAX.

Бот умеет:
- принимать вопрос пользователя;
- делать пробный и полный расклад;
- работать с подпиской и балансом;
- принимать оплату через YooKassa;
- хранить данные в SQLite;
- отправлять админ-уведомления и выполнять фоновую рассылку.

## Текущий статус
- Проект работает на `maxapi` (поддерживает `webhook` и `polling` fallback).
- Продакшен развернут на сервере в `/root/maxtarobot` (Docker).

## Структура проекта
- `main.py` — точка входа, роутеры, webhook/polling, фоновые задачи.
- `config.py` — конфигурация из `.env`.
- `max_handlers/` — обработчики MAX (`start`, `tarot`, `payments`, `admin`, `states`).
- `max_keyboards/` — inline-кнопки MAX.
- `services/` — бизнес-логика, интеграции, подписки, рассылка.
- `database/` — схема БД и CRUD.
- `media/` — карты Таро, шаблоны, временные файлы.

## Основные сценарии
1. Пользователь нажимает `/start` или кнопку меню.
2. Переходит в `/ask` и задает вопрос.
3. Получает пробный или полный расклад (в зависимости от баланса и trial).
4. При нехватке баланса переходит в оплату.
5. После успешной оплаты продолжается отложенный сценарий (`pending_actions`).

## Команды пользователя
- `/start`
- `/menu`
- `/ask`
- `/balance`
- `/help`
- `/invite`

## Команды администратора
- `/admin_help`
- `/botstats`
- `/adstats <метка>`
- `/adstats_all`
- `/adtag <метка>`
- `/genpromo <токены>`
- `/sub_check <ID>`
- `/sub_on <ID> <amount>`
- `/sub_off <ID>`
- `/sub_cancel <ID>`
- `/admin_add <ID>` (только owner)
- `/admin_del <ID>` (только owner)
- `/admin_list` (только owner)
- `/notify_test` (тест доставки админ-уведомлений)

Важно:
- В MAX нет полноценного аналога Telegram `command scope`.
- Ограничение доступа к админ-командам реализовано в коде.

## Админы и права
Настройка в `.env`:
- `ADMIN_IDS=...`
- `ADMIN_NOTIFY_IDS=...`

Логика:
- `ADMIN_IDS` — владельцы/базовые админы.
- Таблица `admins` — дополнительные админы.
- `ADMIN_NOTIFY_IDS` — получатели служебных уведомлений.

## Ключевые переменные окружения
- `MAX_BOT_TOKEN` — токен бота MAX.
- `MAX_USE_WEBHOOK` — `1` для webhook-режима, `0` для polling fallback.
- `MAX_WEBHOOK_URL` — публичный URL webhook (например `https://bot.example.com/max-webhook`).
- `MAX_WEBHOOK_SECRET` — секрет webhook (`X-Max-Bot-Api-Secret`).
- `MAX_WEBHOOK_HOST`, `MAX_WEBHOOK_PORT`, `MAX_WEBHOOK_PATH` — локальный listener.
- `DATABASE_PATH` — путь к SQLite (`/app/data/database.db` в Docker).
- `MEDIA_TEMP_DIR` — временная папка медиа.
- `YOOKASSA_*` — платежи.
- `SUB_*` — тарифы и лимиты.
- `REF_BONUS`, `TAROT_SPREAD_COST` — экономика.

Для прогресса генерации:
- `TAROT_PROGRESS_STICKER_CODE`
- `TAROT_PROGRESS_STICKER_URL`
- `TAROT_PROGRESS_TEXT`

## Локальный запуск
```bash
pip install -r requirements.txt
python main.py
```

Проверка синтаксиса:
```bash
python -m compileall main.py max_handlers max_keyboards services
```

## Docker
```bash
docker compose up -d --build
docker compose ps
docker compose logs -f bot
```

Webhook-порт публикуется через `MAX_WEBHOOK_PORT` (по умолчанию `8080`).

## Продакшен
Папка проекта:
- `/root/maxtarobot`

Данные вынесены в volume:
- `/root/maxtarobot/data` -> `/app/data`
- `/root/maxtarobot/media` -> `/app/media`

Проверки:
```bash
cd /root/maxtarobot
docker compose ps
docker compose logs --tail=120 bot
ls -la /root/maxtarobot/data
```

## Важно по стабильности
Не запускайте несколько инстансов бота с одним токеном одновременно.

Симптом:
- один клик пользователя вызывает несколько ответов.

Причина:
- одновременно работают несколько процессов `python main.py`/контейнеров с тем же токеном.

С учетом требований MAX от 11.05.2026 рекомендуется использовать `webhook` вместо `long polling`.

## Документы
- План миграции: `MAX_MIGRATION_PLAN.md`
- Архитектурный регламент: `agents.md`
