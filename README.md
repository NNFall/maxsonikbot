# MaxTarobot (MAX Messenger)

## Что это
Проект `MaxTarobot` — это миграция рабочего Telegram-бота Таро в мессенджер MAX.

Бот:
- принимает вопрос пользователя;
- делает пробный/полный расклад;
- ведет пользователя к подписке;
- принимает оплату через YooKassa;
- хранит баланс, подписки, транзакции и админ-метрики в SQLite;
- отправляет админ-уведомления и выполняет фоновую рассылку.

## Текущий статус
- Рабочая MAX-версия запущена через `maxapi`.
- Бэкап старой Telegram-версии лежит в `previous_tg_bot/`.
- Продакшен-деплой: `/root/maxtarobot` (Linux, Docker).

## Структура проекта
- `main.py` — entrypoint, роутеры, запуск polling и фоновых задач.
- `config.py` — загрузка конфигурации из `.env`.
- `max_handlers/` — обработчики MAX (start, tarot, payments, admin, states).
- `max_keyboards/` — inline-кнопки MAX.
- `services/` — бизнес-логика, интеграции, рассылка, подписки.
- `database/` — схема SQLite и CRUD.
- `media/` — таро-карты, шаблоны и временные файлы.
- `previous_tg_bot/` — архив Telegram-версии для сравнения/отката.

## Основные сценарии
1. Пользователь нажимает `/start` или кнопку меню.
2. Задает вопрос (`/ask` или `menu:ask`).
3. Получает пробную карту или полный расклад (в зависимости от баланса и trial).
4. При нехватке баланса — переход к подписке и оплате.
5. После успешной оплаты — автопродолжение отложенного действия (`pending_actions`).

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

Важно:
- В MAX сейчас нет отдельного command scope, как в Telegram.
- Поэтому команды нельзя официально “показывать только админам” в UI.
- Ограничение реализовано на уровне кода: не-админ команды не выполнит.

## Админы и права
Настройка через `.env`:
- `ADMIN_IDS=5462936,7476208806,190796855`
- `ADMIN_NOTIFY_IDS=5462936`

Логика:
- `ADMIN_IDS` — владельцы/базовые админы (owner-права для `/admin_add`, `/admin_del`, `/admin_list`).
- Таблица `admins` — дополнительные админы (`/admin_add`).
- `ADMIN_NOTIFY_IDS` — кому отправлять важные служебные уведомления.

## Переменные окружения (ключевые)
- `MAX_BOT_TOKEN` — токен MAX-бота.
- `DATABASE_PATH` — путь к SQLite (в Docker: `/app/data/database.db`).
- `MEDIA_TEMP_DIR` — temp-папка медиа.
- `KIE_*`, `REPLICATE_*` — LLM/генерация.
- `YOOKASSA_*` — платежи.
- `SUB_*` — тарифы и лимиты.
- `REF_BONUS`, `TAROT_SPREAD_COST` — экономика продукта.

## Локальный запуск
```bash
pip install -r requirements.txt
python main.py
```

Проверка синтаксиса:
```bash
python -m compileall main.py max_handlers max_keyboards services
```

## Docker запуск (локально/сервер)
```bash
docker compose up -d --build
docker compose ps
docker compose logs -f bot
```

## Продакшен (сервер)
Целевая папка:
- `/root/maxtarobot`

Данные вынесены наружу контейнера:
- `/root/maxtarobot/data` -> `/app/data`
- `/root/maxtarobot/media` -> `/app/media`

Проверки на сервере:
```bash
cd /root/maxtarobot
docker compose ps
docker compose logs --tail=120 bot
ls -la /root/maxtarobot/data
```

## Важное по стабильности
Не запускать несколько инстансов бота с одним токеном одновременно.

Симптом:
- один клик пользователя вызывает несколько разных ответов.

Причина:
- параллельно работают несколько `python main.py`/контейнеров с тем же бот-токеном.

Что делать:
1. Оставить только один продакшен-инстанс.
2. Остановить локальные тестовые процессы перед прод-тестом.
3. Проверить `docker ps` и `ps aux | grep main.py`.

## Миграционный контекст
- Подробный план и журнал изменений: `MAX_MIGRATION_PLAN.md`.
- Источник архитектуры платформы: `agents.md`.
- Старый бот (Telegram): `previous_tg_bot/`.
