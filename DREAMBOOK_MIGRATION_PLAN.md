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

## Риски

- В проекте есть незакоммиченное изменение в `max_handlers/admin.py`; правки в этом файле должны быть только точечными текстовыми заменами.
- Реальная проверка YooKassa и MAX webhook требует живых токенов и внешнего сервера, локально можно проверить только синтаксис и связность кода.
- Старые `tarot_*` файлы остаются в репозитории как неактивные; это безопаснее для первого этапа, но позже их можно удалить отдельной чисткой.
- Перед деплоем нужно обновить production `.env` по `.env.example`, особенно `MAX_WEBHOOK_PATH`, `DREAM_*`, `YOOKASSA_ITEM_NAME`.
