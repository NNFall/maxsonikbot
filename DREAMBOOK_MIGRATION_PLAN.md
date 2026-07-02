# План миграции MaxTarobot -> Сонник ИИ

Дата старта: 2026-05-17  
Текущий статус: `Этап 4 (завершен локально)`

## Цель

Сделать MAX-бота "Сонник ИИ" на базе существующего MaxTarobot, сохранив платформенную оболочку:
- MAX webhook/polling;
- баланс и подписки;
- YooKassa;
- pending-actions после оплаты;
- админ-команды и уведомления;
- smart-рассылку;
- SQLite и Docker-деплой.

Меняется только предметная часть: вместо Таро пользователь описывает сон, а бот дает толкование сна через текстовую нейросеть.

## План по файлам

### Документация и настройки
- `README.md` — обновить описание продукта, сценарии, команды и переменные.
- `.env.example` — заменить Tarot-переменные на Dreambook-переменные, сохранить совместимость старых ключей где полезно.
- `DREAMBOOK_MIGRATION_PLAN.md` — фиксировать этапы, измененные файлы, проверки и остаточные риски.

### Активный MAX-слой
- `main.py` — заменить описание `/ask` на сонник.
- `max_handlers/__init__.py` — подключить новый dream-router вместо tarot-router.
- `max_handlers/start.py` — обновить onboarding, help, invite и тексты промокодов.
- `max_handlers/payments.py` — оставить YooKassa и подписки, заменить pending-action на `dream_full`.
- `max_handlers/states.py` — заменить состояние ожидания вопроса Таро на ожидание описания сна.

### Продуктовые обработчики и сервисы
- `max_handlers/dream.py` — новый пользовательский сценарий:
  1. пользователь вводит сон;
  2. бот валидирует текст;
  3. при первом бесплатном сценарии дает короткое толкование;
  4. при балансе списывает 1 толкование и выдает полный разбор;
  5. при нехватке баланса сохраняет pending-action и ведет к подписке.
- `services/dream_ai.py` — генерация текста через текущие Kie/Replicate text-провайдеры.
- `services/dream_reading_max.py` — бизнес-операция списания, прогресса, отправки результата, возврата баланса при ошибке.
- `services/dream_context.py` — короткий контекст для уточняющих вопросов.
- `prompts/dream_prompts.py` — system/user prompts для короткого, полного и уточняющего толкования.
- `max_keyboards/dream_kb.py` — кнопки после результата и открытия полного разбора.

### Тексты и рассылки
- `max_keyboards/main_menu.py` — главное меню под сонник.
- `max_keyboards/payment_kb.py` — тарифы в "толкованиях".
- `prompts/mailer_push_templates.py` — push-шаблоны под сны.
- `services/smart_mailer_max.py` — CTA рассылки под "Сонник ИИ".
- `services/subscription_tasks_max.py` — пользовательские и админские тексты по автопродлению.
- `max_handlers/admin.py` — только текстовые замены единицы продукта, без изменения прав и командной логики.

## Этапы

### Этап 1. Аудит и план — завершен
- Изучены `agents.md`, `TELEGRAM_TO_MAX_AGENT_GUIDE.md`, `README.md`, `MAX_MIGRATION_PLAN.md`, `.env.example`, `main.py`, `config.py`.
- Найден активный MAX-каркас: `main.py`, `max_handlers/*`, `max_keyboards/*`, `services/*_max.py`.
- Найдены продуктовые Tarot-зависимости: `max_handlers/tarot.py`, `services/tarot_*`, `prompts/tarot_prompts.py`, `media/tarot/*`.
- Решение: не трогать БД, YooKassa, подписки, admin CRUD и Docker. Активный роутер заменить на dream-роутер, старые tarot-модули оставить как неактивную основу до отдельной чистки.

### Этап 2. Dreambook flow — завершен
- Добавлены `prompts/dream_prompts.py`, `services/dream_ai.py`, `services/dream_context.py`, `services/dream_reading_max.py`.
- Добавлен `max_handlers/dream.py`:
  - `/ask` и кнопка `menu:ask` ждут описание сна;
  - первый бесплатный сценарий дает короткое толкование;
  - полный разбор списывает `DREAM_INTERPRETATION_COST`;
  - при нехватке баланса сохраняется pending-action `dream_full`;
  - уточняющие сообщения после ответа обрабатываются через dream context.
- Добавлен `max_keyboards/dream_kb.py` с кнопками открытия полного разбора и повторного сценария.
- В `max_handlers/__init__.py` активный роутер заменен с `tarot` на `dream`.

### Этап 3. Платежи, тексты, README и env — завершен
- `max_handlers/payments.py` оставляет YooKassa/подписки без смены механики, но автопродолжает `dream_full`.
- `config.py` добавляет `DREAM_INTERPRETATION_COST`, `DREAM_PROGRESS_*` и нормализует стандартное старое `YOOKASSA_ITEM_NAME=Подписка на расклады` в новое название.
- `main.py`, `max_handlers/start.py`, `max_handlers/admin.py`, `max_keyboards/*`, `services/smart_mailer_max.py`, `services/subscription_tasks_max.py`, `prompts/mailer_push_templates.py` обновлены под сонник.
- `.env.example` переписан под "Сонник ИИ".
- `README.md` обновлен под новый продукт, сценарии, команды и переменные.
- `tools/test_text_llm.py` теперь тестирует dream LLM-chain.

### Этап 4. Проверки — завершен локально
- Выполнено: `python -m compileall main.py max_handlers max_keyboards services prompts tools/test_text_llm.py`.
- Выполнено: импорт `max_handlers.all_routers`, активные роутеры `['start', 'payments', 'admin', 'dream']`.
- Выполнено: проверка `load_config()` для `dream_interpretation_cost`, `dream_progress_text`, `yookassa_item_name`.
- Выполнено: `git diff --check`.
- Выполнено: поиск старых Tarot-формулировок в активных файлах. Найдены только legacy-файлы `max_handlers/tarot.py`, `max_keyboards/tarot_kb.py`, `services/tarot_*`, `prompts/tarot_prompts.py`, которые больше не подключены в `all_routers`.
- Выполнено: `tools/test_text_llm.py` на fallback-ответе. Внешние Kie/Replicate вызовы не проверены из-за сетевых ограничений локальной среды.

### Этап 5. GitHub и серверный деплой — завершен
- Репозиторий переключен на `https://github.com/NNFall/maxsonikbot`.
- Изменения закоммичены и отправлены в `origin/main`.
- На сервере `/root/maxsonikbot` развернут код из репозитория, commit `165269a`.
- Production `.env` собран из локальной рабочей конфигурации и нового MAX-токена без вывода секретов в логи.
- Бот запущен через Docker Compose как отдельный контейнер `maxsonikbot-bot-1`.
- Режим запуска: polling, потому что публичный webhook-домен не был указан. Порт контейнера: `18083`.
- Внешние volume-папки сохранены:
  - `/root/maxsonikbot/data` для SQLite;
  - `/root/maxsonikbot/media/temp` для временных файлов.
- Проверено по логам старта:
  - MAX API определяет бота как `Сонник ИИ`;
  - зарегистрировано 36 обработчиков событий;
  - база `/root/maxsonikbot/data/database.db` создана;
  - контейнер находится в статусе `running`.

### Этап 6. Уточнение платежного UX и тестовая ЮKassa — завершен
- После пробного толкования кнопка `Открыть полный разбор` теперь сразу показывает экран `Выберите подписку 👇` с тарифами, без промежуточной кнопки выбора подписки.
- Для прямого выбора подписки из dream-flow скрыта лишняя кнопка `Назад`; пользователь видит только тарифные кнопки.
- Бизнес-логика автопродолжения не менялась: после успешной YooKassa-оплаты pending-action `dream_full` автоматически запускает полный разбор сна.
- Дефолтные тарифы обновлены:
  - неделя: 199 ₽, 15 толкований;
  - месяц: 499 ₽, 100 толкований.
- Локальный и серверный `.env` переключены на тестовые данные ЮKassa без коммита секретов в репозиторий.

### Этап 7. Форматирование толкований — завершен
- Промпты dream-flow переведены на MAX Markdown с жирными заголовками через двойные звездочки.
- В заголовки полного разбора добавлены умеренные эмодзи:
  - `🌙 Краткое значение`;
  - `🔮 Символы и знаки`;
  - `⚠️ Предупреждение`;
  - `💭 Эмоциональный смысл`;
  - `🧭 Практический совет`.
- Добавлена страховка в `services/dream_ai.py`: если модель вернет заголовки без разметки, в HTML или через одинарные звездочки, код приведет их к жирному MAX Markdown.
- Fallback-ответы тоже обновлены на новый формат.

### Этап 8. Подсказка перед вводом сна — завершен
- В сообщение `Опишите сон` добавлен короткий пример с местом, персонажем, предметом и эмоцией.
- Метка `Пример:` выделена жирным через HTML-разметку.
- Логика обработки сна, оплаты и автопродолжения не менялась.

### Этап 9. Push-рассылки и оферта — завершен
- Файл `prompts/mailer_push_templates.py` обновлен: добавлены 20 вариантов push-текстов под сонник в стиле "что вам приснилось сегодня" и "давайте разберем сон".
- Inline-кнопка рассылки изменена на `🌙 Разобрать сон` с переходом в сценарий описания сна.
- URL оферты обновлен на `https://dimonk95.github.io/sonnikmax/` в `.env.example`, дефолте `config.py` и production `.env`.
- Механика smart-mailer не менялась: preview админам, фильтр пользователей с активной подпиской, прогресс и цикл 12 часов сохранены.

### Этап 10. Боевая ЮKassa — завершен
- Локальный и серверный `.env` переключены с тестовой ЮKassa на боевой shop id `1360576`.
- Секретный live-ключ не хранится в репозитории и не добавлялся в tracked-файлы.
- Контейнер `maxsonikbot-bot-1` пересоздан, внутри контейнера проверено: shop id `1360576`, live-ключ присутствует.

### Этап 11. Cross-link на Таро-бота — завершен
- В главное меню сонника добавлена вторая кнопка `🔮 Сделать расклад`.
- Кнопка ведет внешней ссылкой на `https://max.ru/id644009650098_bot?start=sonik`.
- Основная кнопка `🌙 Разобрать сон` и все платежные/админские сценарии не менялись.

### Этап 12. Переход MAX API на platform-api2 — завершен
- Добавлена переменная `MAX_API_URL` с дефолтом `https://platform-api2.max.ru`.
- После создания `Bot(...)` вызывается `bot.set_api_url(config.max_api_url)`.
- В Docker-образ добавлены доверенные сертификаты Минцифры:
  - `certs/russian_trusted_root_ca.crt`;
  - `certs/russian_trusted_sub_ca_ssl_rsa2024.crt`.
- `Dockerfile` устанавливает `ca-certificates`, копирует сертификаты в trust store и выполняет `update-ca-certificates`.
- Для Python-запросов установлены `SSL_CERT_FILE` и `REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt`.

### Этап 13. Защита от рассинхрона подписок — завершен
- Проверена production-БД на состояние `status != active AND auto_renew = 1`: найдено 0 строк.
- Найдены и очищены 5 старых строк `inactive/expired` с сохраненным `payment_method_id`.
- `cancel_subscription` теперь одновременно ставит `auto_renew = 0` и очищает `payment_method_id`.
- Перевод подписки в `inactive` или `expired` через `mark_subscription_status` теперь также очищает `auto_renew` и `payment_method_id`.
- В watcher добавлена санитарная чистка `cleanup_inconsistent_subscriptions`, чтобы старые рассинхроны исправлялись автоматически.
- Истечение подписки в `payments._expire_if_needed` и `subscription_tasks_max.process_due_subscriptions` теперь проходит через `expire_subscription`.

## Риски

- Реальная проверка YooKassa требует тестовой или боевой оплаты. Код оплат и подписок не ломался, но сценарий начисления после оплаты нужно пройти вручную в MAX.
- MAX webhook пока не включен: запуск идет через polling. Для webhook потребуется публичный HTTPS-домен, `MAX_WEBHOOK_URL`, `MAX_WEBHOOK_PATH` и проверка входящих запросов.
- Старые `tarot_*` файлы остаются в репозитории как неактивные; это безопаснее для первого этапа, но позже их можно удалить отдельной чисткой.
- Внешние Kie/Replicate вызовы не проверялись локально из-за сетевых ограничений. На сервере нужно проверить первый живой разбор сна в MAX.
