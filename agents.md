# AGENTS.md

Универсальная спецификация-шаблон для Telegram SaaS-ботов на базе текущей оболочки проекта.

Документ предназначен одновременно для:
- разработчика (как техническая документация и операционный регламент),
- LLM-агента (как структурированная база для генерации новых ботов в другой нише).

Принцип: ядро платформы остается одинаковым, меняется только предметная часть продукта.

---

## 1. Назначение шаблона и правила адаптации под новую нишу

### Что обязательно
- Использовать этот документ как первичный источник требований для нового бота.
- Сохранять каркас платформы:
  - меню,
  - баланс и подписки,
  - платежи,
  - deeplinks,
  - админ-панель,
  - рассылки,
  - логирование,
  - БД и фоновые задачи.
- Любой новый бот строится по той же структуре слоев (`handlers/services/database/keyboards`).
- Все пользовательские и админские тексты оформлять в `HTML parse mode` (`<b>`, `<i>`, `<code>`, ссылки).

### Что заменяется под нишу
- `<PRODUCT_NAME>`: название продукта (пример: "Генератор презентаций ИИ", "Таро-бот").
- `<PRODUCT_UNIT>`: единица результата (пример: "презентация", "расклад", "отчет", "изображение", "видео").
- `<PRODUCT_FLOW>`: шаги пользовательского сценария генерации.
- `<PRODUCT_COST_*`>: экономика и тарифы.
- `<PRODUCT_SUPPORT>`: контакт поддержки.

### Готовые шаблоны

Шаблон позиционирования:
```text
<PRODUCT_NAME> — Telegram-бот для быстрого создания <PRODUCT_UNIT>.
Работает по подписке, поддерживает оплату через ЮKassa и Stars, имеет админку, deeplink-атрибуцию и автоворонки.
```

Шаблон адаптации (чек-лист):
```text
1) Переименовать продуктовые разделы меню.
2) Обновить обработчики генерации в services/handlers.
3) Сохранить неизменными платежи, подписки, БД, deeplinks, админку, рассылки.
4) Обновить пользовательские тексты и демо-контент.
5) Проверить команды, callback_data и логи.
```

---

## 2. Базовая архитектура (слои, FSM, фоновые воркеры)

### Что обязательно
- Точка входа `main.py`:
  - загрузка `Config`,
  - `setup_db`,
  - регистрация роутеров,
  - установка пользовательских и админских команд,
  - запуск фоновых задач:
    - `subscription_watcher(bot)`,
    - `smart_mailing_loop(bot)`,
  - запуск polling.
- Слои:
  - `handlers/`: Telegram-логика, FSM, callback/command.
  - `services/`: внешние API, бизнес-операции, фоновые циклы.
  - `database/`: схема и CRUD.
  - `keyboards/`: inline-кнопки и callback-маршрутизация.
- FSM обязателен для пошаговых сценариев (ожидание медиа, текста, длительности, таймкодов и т.д.).
- Все меню и действия через inline-кнопки.

### Что заменяется под нишу
- Продуктовые обработчики:
  - сейчас: `effects`, `photo_effects`, `photo_custom`, `photo_text`, `custom_gen`.
  - в новой нише: аналогичные сценарии под `<PRODUCT_UNIT>`.
- Интеграции нейросетей/API в `services/`.

### Готовые шаблоны

Рекомендуемая структура:
```text
project/
  main.py
  config.py
  .env
  requirements.txt
  database/
    db.py
    crud.py
    database.db
  handlers/
    __init__.py
    start.py
    <product_handlers>.py
    payments.py
    admin.py
  services/
    <product_api>.py
    generation.py
    yookassa.py
    subscription_tasks.py
    smart_mailer.py
    notify.py
  keyboards/
    main_menu.py
    payment_kb.py
    <product_kb>.py
  media/temp/
  Dockerfile
  docker-compose.yml
```

---

## 3. Обязательная схема БД (DDL, индексы, миграции)

### Что обязательно
- SQLite-ядро с WAL.
- Таблицы:
  - `users`,
  - `effects`,
  - `transactions`,
  - `promocodes`,
  - `pending_actions`,
  - `admins`,
  - `subscriptions`,
  - `mailer_state`.
- Индексы для:
  - UTM,
  - транзакций,
  - активных эффектов,
  - подписок,
  - pending-actions.
- Миграции через `ensure_schema` с `ALTER TABLE` для обратной совместимости.

### Что заменяется под нишу
- В `effects` можно хранить не только эффекты, а любые пресеты/продуктовые шаблоны.
- В `demo_type/demo_file_id` можно использовать медиа-референсы нужного формата.

### Готовые шаблоны

Полный DDL:
```sql
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,
    utm_source TEXT,
    referrer_id INTEGER,
    has_purchased INTEGER NOT NULL DEFAULT 0,
    referrer_rewarded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS effects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    button_name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    demo_file_id TEXT,
    demo_type TEXT,
    type TEXT NOT NULL DEFAULT 'video',
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,
    credits INTEGER NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    provider_payment_id TEXT,
    payload TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS promocodes (
    code TEXT PRIMARY KEY,
    credits INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    used_by INTEGER,
    used_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    action_payload TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    added_by INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER PRIMARY KEY,
    plan_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    auto_renew INTEGER NOT NULL DEFAULT 0,
    payment_method_id TEXT,
    current_period_start TEXT NOT NULL,
    current_period_end TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mailer_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_effect_id INTEGER,
    last_type TEXT,
    last_video_id INTEGER,
    last_photo_id INTEGER,
    updated_at TEXT NOT NULL
);
```

Индексы:
```sql
CREATE INDEX IF NOT EXISTS idx_users_utm ON users(utm_source);
CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_tx_status ON transactions(status);
CREATE INDEX IF NOT EXISTS idx_effects_active ON effects(is_active);
CREATE INDEX IF NOT EXISTS idx_effects_sort ON effects(sort_order);
CREATE INDEX IF NOT EXISTS idx_promocodes_active ON promocodes(is_active);
CREATE INDEX IF NOT EXISTS idx_pending_tx ON pending_actions(tx_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_end ON subscriptions(current_period_end);
```

Миграционные заметки:
```sql
ALTER TABLE effects ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;
ALTER TABLE effects ADD COLUMN type TEXT NOT NULL DEFAULT 'video';
ALTER TABLE mailer_state ADD COLUMN last_type TEXT;
ALTER TABLE mailer_state ADD COLUMN last_video_id INTEGER;
ALTER TABLE mailer_state ADD COLUMN last_photo_id INTEGER;
```

---

## 4. Deeplinks и атрибуция (`/start` payload)

### Что обязательно
- Поддержка payload форматов:
  - `ref_<id>`: реферальная ссылка,
  - `promo_<code>`: промокод,
  - `<utm_tag>`: рекламная метка.
- Логика `add_user`:
  - `INSERT OR IGNORE`,
  - `utm_source` и `referrer_id` заполняются через `COALESCE`, не перезаписываются повторным `/start`.
- Реф-бонус начислять только после первой оплаченной покупки приглашенного.
- Обязательно хранить `has_purchased` и `referrer_rewarded`.

### Что заменяется под нишу
- Названия/описания кампаний UTM.
- Размер `REF_BONUS`.

### Готовые шаблоны

Форматы ссылок:
```text
https://t.me/<bot_username>?start=ref_<USER_ID>
https://t.me/<bot_username>?start=promo_<CODE>
https://t.me/<bot_username>?start=<UTM_TAG>
```

Сценарий разбора:
```text
if payload startswith "ref_": referrer_id = int(...)
elif payload startswith "promo_": promo_code = ...
else: utm_source = payload
```

Антидублирование:
```text
utm_source = COALESCE(existing_utm_source, new_utm_source)
referrer_id = COALESCE(existing_referrer_id, new_referrer_id)
if referrer_id == user_id: ignore
```

---

## 5. Экономика и подписки

### Что обязательно
- Баланс пользователя хранится в `users.balance`.
- Тарифы (минимум 2): `week` и `month`.
- Подписка хранится в `subscriptions`:
  - `status` (`active`, `inactive`, `expired`),
  - `auto_renew`,
  - `current_period_start/end`,
  - `payment_method_id` (для автосписания ЮKassa).
- При любом продлении:
  - старый остаток сгорает,
  - начисляется новый лимит токенов тарифа.
- При отключенном автопродлении и окончании периода:
  - подписка в `expired`,
  - баланс `0`.

### Что заменяется под нишу
- `SUB_*` цены, лимиты, длительности.
- Формулировка для пользователя: "токены", "кредиты", "генерации" (в проекте сейчас единообразно "токены").

### Готовые шаблоны

Логика активной подписки:
```text
is_active = sub.status == 'active' and sub.auto_renew == 1
```

Карточка активной подписки:
```text
✅ Подписка активна
Тариф: <цена/период/лимит>
Остаток токенов: <balance>
Обновление токенов: <YYYY-MM-DD>
```

Карточка неактивной подписки:
```text
<b>Подписка с автосписанием</b>
🔥 <week.price_rub> ₽ / <week.title.lower()> — <week.generations> токенов
⭐ <month.price_rub> ₽ / <month.title.lower()> — <month.generations> токенов

⭐ <week.price_stars> ⭐ — <week.generations> токенов (разово)
⭐ <month.price_stars> ⭐ — <month.generations> токенов (разово)

Отключить можно в любой момент в /balance.
Переходя к оплате, вы соглашаетесь с офертой.
```

---

## 6. Платежи (ЮKassa + Stars): lifecycle, статусы, lock, retry

### Что обязательно
- Для ЮKassa:
  - первая покупка через redirect-платеж,
  - `save_payment_method=True`,
  - polling статуса платежа (`POLL_INTERVAL=5`, `POLL_TIMEOUT=600`),
  - при `succeeded` активировать подписку,
  - для повторного продления использовать `payment_method_id`.
- Для Stars:
  - отправка Telegram invoice,
  - обработка `pre_checkout_query`,
  - обработка `successful_payment`,
  - `auto_renew=0`.
- Локи/антидублирование:
  - `_payment_locks[user_id]`,
  - проверка pending-транзакции (`_guard_pending_payment`),
  - просроченные pending помечать `expired`.
- Payload для Stars должен быть уникальным (с UUID), чтобы повторные оплаты не конфликтовали.
- Поддерживать `pending_actions`: если пользователь оплатил в середине сценария, после успешной оплаты операция продолжается автоматически.

### Что заменяется под нишу
- Описание товаров/чека.
- Налоговые параметры в `.env`.
- Ссылки оферты и на возврат (`return_url`).

### Готовые шаблоны

Статусы транзакций:
```text
pending -> paid
pending -> expired
paid (финальный)
```

Тексты пользователю (точные шаблоны текущей оболочки):
```text
⏳ Оплата уже создана. Завершите предыдущую или дождитесь результата.
⏳ Оплата уже создается. Подождите пару секунд.
Оплата через ЮKassa. Нажмите кнопку ниже и завершите оплату.
✅ Подписка активирована. Токены начислены.
✅ Оплата прошла успешно.
Подписка выключена. Токены доступны до <date>.
🔄 Запрос на продление отправлен. Ожидаем подтверждение оплаты.
```

Тексты админам по платежам:
```text
💰 Успешная оплата (ЮKassa). Пользователь <id> (@<username>) , план <plan_id>
✅ Продлил подписку (ЮKassa). Пользователь <id> (@<username>) , план <plan_id>
💰 Успешная оплата (Stars). Пользователь <id> (@<username>)
❌ Продление не удалось (ошибка списания): <error>
❌ YooKassa config error: <error>
```

---

## 7. Универсальная продуктовая воронка (замена генерации видео/фото на ваш продукт)

### Что обязательно
- Разделить сценарии на 2 режима:
  - шаблоны (`effects`/presets),
  - свободный запрос (`custom prompt`).
- У каждого сценария:
  - валидация входа,
  - проверка баланса,
  - списание токенов,
  - запуск генерации/обработки,
  - доставка результата,
  - ошибка + возврат токенов,
  - админ-лог.
- Для длительных задач:
  - `create task -> poll status -> fetch result`.

### Что заменяется под нишу
- Тип входных данных:
  - фото,
  - текст,
  - файлы/документы,
  - комбинированный ввод.
- Тип результата `<PRODUCT_UNIT>`.
- Стоимость (`EFFECT_COST`, `CUSTOM_COST_PER_SEC`, `PHOTO_*` и т.п.).

### Готовые шаблоны

Шаблон бизнес-операции:
```text
1) if balance < cost: показать тарифы, сохранить pending action, stop
2) списать cost
3) try:
     - получить входной файл/текст
     - вызвать внешний API
     - получить результат
     - отправить результат пользователю
     - отправить success log админу
   except:
     - вернуть cost
     - отправить пользователю сообщение об ошибке
     - отправить error log админу
```

Шаблон post-result:
```text
✅ <PRODUCT_UNIT> создан(а)
Запрос: <короткий prompt>
[Кнопка "Сделать еще"]
[Кнопка "Главное меню"]
```

---

## 8. Smart-рассылка (preview/start/progress/finish, фильтрация, ротация)

### Что обязательно
- Фоновый цикл рассылки (`smart_mailing_loop`).
- Перед запуском:
  - preview админам за 30 минут.
- На старте:
  - посчитать аудиторию (без активной подписки),
  - отправить стартовое сообщение всем админам.
- Во время отправки:
  - темп ~25 msg/sec,
  - прогресс раз в минуту через edit.
- После окончания:
  - финальная статистика.
- Цикл каждые 12 часов.
- Хранить состояние в `mailer_state`:
  - последний эффект,
  - последний тип (`video/photo`),
  - timestamps.

### Что заменяется под нишу
- Контент рассылки (`demo`, текст, CTA).
- Правила сегментации (сейчас: только пользователи без активной подписки).

### Готовые шаблоны

Тексты рассылки (текущая оболочка):
```text
Попробуйте этот эффект! 👇
<button_name>
```

Preview админам:
```text
⚠️ <b>Внимание!</b> Через 30 минут начнется автоматическая рассылка.
Эффект: <b><button_name></b>
```

Старт:
```text
🚀 <b>Рассылка началась!</b>
Эффект: <b><button_name></b>
Целевая аудитория: <b><total></b> чел.
```

Прогресс:
```text
⏳ <b>Идет рассылка...</b>
Отправлено: <sent> из <total> (<percent>%)
Ошибок/Блокировок: <errors>
```

Финиш:
```text
✅ <b>Рассылка завершена.</b>
Успешно доставлено: <sent>
Не доставлено (бот заблокирован): <blocked>
Следующая рассылка через 12 часов.
Ошибок: <failed>   # строка добавляется, если failed > 0
```

---

## 9. Команды, права, уведомления админам и формат логов

### Что обязательно
- Устанавливать команды:
  - глобальные пользовательские через `bot.set_my_commands(user_cmds)`,
  - расширенные админские через `BotCommandScopeChat(chat_id=admin_id)`.
- Роли:
  - супер-админы из `ADMIN_IDS`,
  - дополнительные админы в таблице `admins`.
- Любое ключевое событие отправлять в `notify_admin`.

### Что заменяется под нишу
- Продуктовые команды (`/effects`, `/custom`, `/image` и т.д.) под домен проекта.

### Готовые шаблоны

Пользовательские команды текущей оболочки:
```text
/start
/menu
/balance
/help
/photo_ideas
/photo_edit
/image
/effects
/custom
/concat
/cut
/invite
```

Админские команды текущей оболочки:
```text
/add_session
/session_del
/sub_on <ID> <amount>
/sub_off <ID>
/sub_check <ID>
/sub_cancel <ID>
/adstats <метка>
/adstats_all
/botstats
/adtag <метка>
/genpromo <кол-во токенов>
/set_top
/get_prompt
/admin_add <ID>
/admin_del <ID>
/admin_list
```

Тексты админ-логов (актуальные шаблоны):
```text
👤 Новый пользователь: <user_id> (@<username>), метка: <tag>
🎁 Создан промокод на <credits> токенов: <code>

💰 Успешная оплата (ЮKassa). Пользователь <id> (@<username>) , план <plan_id>
✅ Продлил подписку (ЮKassa). Пользователь <id> (@<username>) , план <plan_id>
💰 Успешная оплата (Stars). Пользователь <id> (@<username>)
❌ Продление не удалось (ошибка списания): <error>
❌ Отключил подписку. Пользователь <id> (@<username>)

✅ Автосписание: пользователь <id>, статус успех, тариф <plan_id>
❌ Автосписание: пользователь <id>, статус ошибка. Причина: <error>
❌ Автосписание: пользователь <id>, статус <status>, тариф <plan_id>

✅ Успешная генерация (Эффект). Пользователь <id> (@<username>) , эффект <effect_id>
✅ Успешная генерация (Фото-эффект). Пользователь <id> (@<username>) , эффект <effect_id>
✅ Успешная генерация (Свой промпт). Пользователь <id> (@<username>)
✅ Успешная генерация (ИИ-Фотошоп). Пользователь <id> (@<username>)
✅ Успешная генерация (Текст→Фото). Пользователь <id> (@<username>)
❌ Ошибка Kie.ai: <error> (user <id> @<username>)
❌ Ошибка Kie.ai (image): <error> (user <id> @<username>)
❌ Ошибка Kie.ai (text image): <error> (user <id> @<username>)
❌ Ошибка <error_source>: <error> (user <id> @<username>)

✅ Склейка видео выполнена. Пользователь <id> (@<username>)
✅ Вырезан фрагмент. Пользователь <id> (@<username>)
❌ Ошибка FFmpeg: <error> (user <id> @<username>)
❌ Ошибка FFmpeg (cut): <error> (user <id> @<username>)
```

---

## 10. UX-правила сообщений и меню

### Что обязательно
- ParseMode: `HTML`.
- Все кнопки — inline.
- Логика по умолчанию: новое сообщение при переходах (лентой).
- Допустимое исключение: pagination (вперед/назад) можно `edit_message_text`.
- В каждом вторичном разделе иметь возврат в меню.
- Тексты краткие и структурированные:
  - заголовок,
  - действие пользователя,
  - ограничения/цена (если нужно),
  - CTA.

### Что заменяется под нишу
- Продуктовые названия разделов меню.
- Инструкции в сценариях отправки данных.

### Готовые шаблоны

Шаблон главного меню:
```text
📸 Идеи для фото
🎨 ИИ-Фотошоп (Свой промпт)
🖼 Создать изображение
✨ Видео-эффекты
🎬 Создать видео (Свой промпт)
📼 Инструменты (Склейка/Обрезка)
💳 Баланс / Купить кредиты
❓ Помощь
```

Шаблон fallback:
```text
Выберите режим ниже 👇
```

Шаблон ошибки недостатка средств:
```text
⚠️ <b>Недостаточно токенов.</b>
<карточка тарифов>
[✅ Выбрать подписку]
```

---

## 11. Полный `.env`-шаблон, Docker/деплой, внешнее хранение БД, FFmpeg-паттерн

### Что обязательно
- Все секреты и параметры только через `.env`.
- На сервере использовать `docker compose`.
- БД хранить вне контейнера (`volume`) для перезапусков/обновлений.
- Временные медиа также в volume.
- FFmpeg:
  - в контейнере должен быть установлен,
  - путь в `FFMPEG_PATH`.

### Что заменяется под нишу
- API ключи продукта.
- Тарифы и цены.
- Оферта/поддержка/брендовые ссылки.

### Готовые шаблоны

`.env` baseline:
```env
BOT_TOKEN=

KIE_API_KEY=
KIE_API_URL=https://api.kie.ai/api/v1/jobs/createTask
KIE_IMAGE_MODEL=grok-imagine/image-to-image
KIE_TEXT_IMAGE_MODEL=grok-imagine/text-to-image

REPLICATE_API_TOKEN=
REPLICATE_API_URL=https://api.replicate.com/v1/predictions
REPLICATE_MODEL_VERSION=
REPLICATE_IMAGE_FIELD=image
REPLICATE_ASPECT_RATIO_MODE=match

YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RECEIPT_EMAIL=
YOOKASSA_RECEIPT_PHONE=
YOOKASSA_TAX_SYSTEM_CODE=
YOOKASSA_VAT_CODE=1
YOOKASSA_ITEM_NAME=Подписка на токены
YOOKASSA_PAYMENT_SUBJECT=
YOOKASSA_PAYMENT_MODE=

STARS_PROVIDER_TOKEN=

ADMIN_IDS=
ADMIN_NOTIFY_IDS=

DATABASE_PATH=/app/data/database.db
MEDIA_TEMP_DIR=/app/media/temp
FFMPEG_PATH=ffmpeg

REF_BONUS=20
EFFECT_COST=10
CUSTOM_COST_PER_SEC=5
PHOTO_EFFECT_COST=4
PHOTO_CUSTOM_COST=4
STARS_RUB_RATE=2.0

SYSTEM_PROMPT=

SUB_WEEK_PRICE_RUB=199
SUB_WEEK_PRICE_STARS=199
SUB_WEEK_GENERATIONS=60
SUB_WEEK_DAYS=7

SUB_MONTH_PRICE_RUB=499
SUB_MONTH_PRICE_STARS=499
SUB_MONTH_GENERATIONS=100
SUB_MONTH_DAYS=30
```

`docker-compose.yml` принцип:
```yaml
services:
  bot:
    build: .
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./media:/app/media
    restart: always
```

Команды эксплуатации:
```bash
docker compose up -d --build
docker compose logs -f
docker compose logs -f bot
docker compose ps
docker compose restart
docker compose down
docker compose exec bot bash
```

---

## 12. Операционные чеклисты: запуск за 1 день, pre-release, incident runbook, prompt-pack

### Что обязательно
- Перед релизом пройти технический чек-лист.
- Для инцидентов иметь стандартные процедуры:
  - платежи,
  - API генерации,
  - рассылка,
  - деградация БД/диска.
- Работать поэтапно в чате:
  - крупными блоками,
  - после каждого блока мини-ревизия.

### Что заменяется под нишу
- Продуктовые acceptance-критерии и ключевые метрики.

### Готовые шаблоны

Запуск нового бота за 1 день:
```text
1) Скопировать каркас проекта.
2) Обновить .env и брендовые тексты.
3) Настроить продуктовые handlers/services.
4) Проверить БД, платежи, deeplink, подписки.
5) Запустить smoke-тест и деплой через Docker.
6) Проверить админ-логи и первую рассылку.
```

Pre-release checklist:
```text
[ ] Все команды установлены (user/admin).
[ ] Все callback_data обрабатываются.
[ ] Недостаток токенов ведет в подписку.
[ ] Успешная оплата начисляет баланс.
[ ] Продление подписки корректно перезаписывает баланс и даты.
[ ] Отключение подписки не обнуляет токены до конца периода.
[ ] Deeplink ref/promo/utm работает.
[ ] Админ-логи приходят по всем ключевым событиям.
[ ] Рассылка: preview -> start -> progress -> finish.
[ ] Временные файлы очищаются после обработки.
```

Incident runbook:
```text
Платежи не проходят:
1) Проверить YOOKASSA_* в .env
2) Проверить логи poll/recurrent/receipt
3) Проверить pending транзакции и их возраст
4) Проверить webhook/poll доступность API

Не начислилось после оплаты:
1) Найти transaction по payload/provider
2) Проверить статус paid/pending/expired
3) Проверить successful_payment обработчик
4) При необходимости ручная компенсация через /sub_on

Генерация падает:
1) Проверить ключи внешнего API
2) Проверить poll timeout/retry
3) Проверить возврат токенов при ошибке
4) Проверить уведомление админу с причиной
```

LLM Agent Prompt #1 (создание нового бота на каркасе):
```text
Ты инженер, который адаптирует существующий Telegram SaaS-каркас под новый продукт <PRODUCT_NAME>.
Используй AGENTS.md как единственный источник архитектурных и операционных правил.
Не ломай оболочку: платежи, подписки, deeplinks, админку, рассылки, БД оставь совместимыми.
Измени только продуктовые модули, тексты и переменные ниши.
Сначала выдай план миграции по слоям, затем внеси изменения, затем отчитай тест-кейсы и риски.
```

LLM Agent Prompt #2 (миграция ниши A -> B):
```text
Выполни миграцию проекта из ниши <A> в нишу <B>, сохранив платформенный каркас и все интеграции монетизации.
Нужны: обновление меню/текстов, продуктовых handlers/services, seed-шаблонов и документации.
Покажи таблицу "что было -> что стало" и список неизменяемых подсистем.
```

LLM Agent Prompt #3 (аудит готовности к продакшену):
```text
Проведи production-readiness аудит по AGENTS.md.
Проверь: команды, платежные сценарии, автопродление, рассылку, deeplinks, БД-миграции, очистку temp-файлов, админ-логирование.
Отчет в формате:
1) Критичные проблемы
2) Средние риски
3) Что готово
4) Что исправить до релиза
```

Режим поэтапной выдачи в чате (для больших документов):
```text
Этап 1: Архитектура + БД + Deeplinks
Этап 2: Экономика + Платежи + Подписки
Этап 3: UX-тексты + Команды + Админ-логи
Этап 4: Рассылки + Деплой + Чеклисты + Prompt-pack
```

---

## Приложение: карта неизменяемого ядра

Компоненты, которые рекомендуется не ломать при смене ниши:
- `database/db.py` и контракт таблиц.
- `database/crud.py` (особенно подписки, транзакции, pending_actions, mailer_state).
- `handlers/payments.py`.
- `services/subscription_tasks.py`.
- `services/smart_mailer.py`.
- `services/notify.py`.
- Поток команд в `main.py`.

Компоненты, которые обычно адаптируются под нишу:
- продуктовые `handlers/*`,
- продуктовые `services/*`,
- `keyboards/main_menu.py` и продуктовые клавиатуры,
- seed-данные эффектов/шаблонов,
- тексты помощи и onboarding.
