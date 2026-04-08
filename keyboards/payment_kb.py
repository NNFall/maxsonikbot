from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def plans_kb(plans: dict[str, object], callback_prefix: str = 'sub:plan') -> InlineKeyboardMarkup:
    rows = []
    for plan_id, plan in plans.items():
        period = getattr(plan, 'title', 'период').lower()
        prefix = '🔥' if plan_id == 'week' else '⭐'
        text = f"{prefix} {plan.price_rub} ₽ / {period} — {plan.generations} раскладов"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"{callback_prefix}:{plan_id}")])
    rows.append([InlineKeyboardButton(text='🏠 Меню', callback_data='menu:main')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def methods_kb(plan_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='💳 ЮKassa (авто)', callback_data=f"sub:method:yoo:{plan_id}")],
            [InlineKeyboardButton(text='⭐ Stars (разовая)', callback_data=f"sub:method:stars:{plan_id}")],
            [InlineKeyboardButton(text='⬅️ Назад', callback_data='menu:balance')],
        ]
    )


def choose_subscription_kb(
    plans: dict[str, object],
    cb_yoo_prefix: str = 'sub:choose:yoo',
    cb_stars_prefix: str = 'sub:choose:stars',
) -> InlineKeyboardMarkup:
    week = plans.get('week')
    month = plans.get('month')
    rows = []
    if week:
        period = week.title.lower() if hasattr(week, 'title') else 'неделя'
        rows.append([
            InlineKeyboardButton(
                text=f"\U0001F525 {week.price_rub} ₽ / {period} — {week.generations} раскладов",
                callback_data=f"{cb_yoo_prefix}:{week.id}",
            )
        ])
    if month:
        period = month.title.lower() if hasattr(month, 'title') else 'месяц'
        rows.append([
            InlineKeyboardButton(
                text=f"\u2B50 {month.price_rub} ₽ / {period} — {month.generations} раскладов",
                callback_data=f"{cb_yoo_prefix}:{month.id}",
            )
        ])
    if week:
        rows.append([
            InlineKeyboardButton(
                text=f"\u2B50 Купить {week.generations} раскладов ({week.price_stars} \u2B50)",
                callback_data=f"{cb_stars_prefix}:{week.id}",
            )
        ])
    if month:
        rows.append([
            InlineKeyboardButton(
                text=f"\u2B50 Купить {month.generations} раскладов ({month.price_stars} \u2B50)",
                callback_data=f"{cb_stars_prefix}:{month.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='menu:balance')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_manage_kb(plan_id: str, auto_renew: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text='🔄 Обновить подписку сейчас', callback_data='sub:renew_choose')],
    ]
    if auto_renew:
        rows.append([InlineKeyboardButton(text='❌ Отключить подписку', callback_data='sub:cancel')])
    rows.append([InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:main')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def choose_subscription_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='✅ Выбрать подписку', callback_data='sub:choose')],
        ]
    )


def pay_url_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='💳 Оплатить', url=url)],
            [InlineKeyboardButton(text='🏠 Меню', callback_data='menu:main')],
        ]
    )


def payment_success_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔮 Задать вопрос', callback_data='menu:ask')],
            [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:main')],
        ]
    )

