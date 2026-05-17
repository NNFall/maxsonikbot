# Сонник ИИ (MAX Messenger)

## Что это
`Сонник ИИ` — MAX-бот для толкования снов через текстовую нейросеть.

Бот умеет:
- принимать описание сна от пользователя;
- делать короткое пробное толкование;
- делать полный разбор сна: значение, символы, возможные знаки, предупреждения, эмоциональный смысл и практический совет;
- работать с подпиской и балансом;
- принимать оплату через YooKassa;
- продолжать отложенный разбор после успешной оплаты;
- хранить данные в SQLite;
- отправлять админ-уведомления и выполнять фоновую smart-рассылку.

## Текущий статус
- Проект работает на `maxapi` и поддерживает `webhook` или polling fallback.
- Платформенная оболочка сохранена от MaxTarobot: YooKassa, подписки, баланс, админка, рассылка, БД и Docker.
- Активный продуктовый сценарий находится в `max_handlers/dream.py`, `services/dream_*.py`, `prompts/dream_prompts.py`.

## Структура проекта
- `main.py` — точка входа, роутеры, webhook/polling, фоновые задачи.
- `config.py` — конфигурация из `.env`.
- `max_handlers/` — обработчики MAX (`start`, `dream`, `payments`, `admin`, `states`).
- `max_keyboards/` — inline-кнопки MAX.
- `services/` — бизнес-логика, нейросеть, подписки, рассылка, уведомления.
- `database/` — схема БД и CRUD.
- `prompts/` — промпты сонника и push-шаблоны.
- `media/` — временные файлы и оставшиеся legacy-ассеты.

## Основной сценарий
1. Пользователь нажимает `/start` или кнопку меню.
2. Переходит в `/ask` и описывает сон.
3. Если пользователь новый и нет баланса, получает короткое пробное толкование.
4. Полный разбор стоит 1 толкование с баланса.
5. При нехватке баланса бот предлагает подписку.
6. После успешной оплаты продолжается отложенный сценарий (`pending_actions`).

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
- `/genpromo <толкования>`
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
- Доступ к админ-командам ограничен в коде.

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
- `MAX_WEBHOOK_URL` — публичный URL webhook.
- `MAX_WEBHOOK_SECRET` — секрет webhook (`X-Max-Bot-Api-Secret`).
- `MAX_WEBHOOK_HOST`, `MAX_WEBHOOK_PORT`, `MAX_WEBHOOK_PATH` — локальный listener.
- `DATABASE_PATH` — путь к SQLite (`/app/data/database.db` в Docker).
- `MEDIA_TEMP_DIR` — временная папка.
- `YOOKASSA_*` — платежи.
- `SUB_*` — тарифы и лимиты.
- `REF_BONUS`, `DREAM_INTERPRETATION_COST` — экономика продукта.
- `DREAM_PROGRESS_STICKER_CODE`, `DREAM_PROGRESS_STICKER_URL`, `DREAM_PROGRESS_TEXT` — прогресс генерации.

Код сохраняет совместимость с частью старых `TAROT_*` переменных как fallback, но для нового деплоя используйте `DREAM_*`.

## Локальный запуск
```bash
pip install -r requirements.txt
python main.py
```

Проверка синтаксиса:
```bash
python -m compileall main.py max_handlers max_keyboards services prompts
```

Проверка текстовой LLM-цепочки:
```bash
python tools/test_text_llm.py --dream "Мне приснилось, что я ищу дверь в темном доме" --mode full
```

## Docker
```bash
docker compose up -d --build
docker compose ps
docker compose logs -f bot
```

Webhook-порт публикуется через `MAX_WEBHOOK_PORT` (по умолчанию `8080`).

## Продакшен
Данные должны быть вынесены в volume:
- `./data` -> `/app/data`
- `./media` -> `/app/media`

Проверки:
```bash
docker compose ps
docker compose logs --tail=120 bot
ls -la ./data
```

## Важно по стабильности
Не запускайте несколько инстансов бота с одним токеном одновременно.

Симптом:
- один клик пользователя вызывает несколько ответов.

Причина:
- одновременно работают несколько процессов `python main.py` или контейнеров с тем же токеном.

С учетом требований MAX рекомендуется использовать `webhook` вместо long polling для продакшена.

## Документы
- Новый план миграции ниши: `DREAMBOOK_MIGRATION_PLAN.md`
- История переноса Telegram -> MAX: `MAX_MIGRATION_PLAN.md`
- Архитектурный регламент: `agents.md`
- Инструкция по MAX-переносу: `TELEGRAM_TO_MAX_AGENT_GUIDE.md`
