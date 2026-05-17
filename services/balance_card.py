from __future__ import annotations

from urllib.parse import quote

from config import load_config
from services.subscriptions import get_plans


async def _balance_link(bot) -> str:
    try:
        me = await bot.get_me()
        if me.username:
            return f'tg://resolve?domain={me.username}&text={quote("/balance")}'
    except Exception:
        pass
    return '/balance'


async def build_inactive_balance_text(bot, balance: int, include_header: bool = True) -> str:
    cfg = load_config()
    plans = get_plans()
    week = plans.get('week')
    month = plans.get('month')

    balance_link = await _balance_link(bot)
    balance_hint = f'<a href="{balance_link}">/balance</a>' if balance_link != '/balance' else '<code>/balance</code>'
    week_period = week.title.lower() if week else 'неделя'
    month_period = month.title.lower() if month else 'месяц'

    header = ''
    if include_header:
        header = (
            '❌ <b>Подписка не активна</b>\n'
            f'🌙 <b>Толкования:</b> {balance}\n\n'
        )

    return (
        f'{header}'
        '<b>Подписка с автосписанием</b>\n'
        f'🔥 {week.price_rub} ₽ / {week_period} — {week.generations} толкований\n'
        f'⭐ {month.price_rub} ₽ / {month_period} — {month.generations} толкований\n\n'
        f'⭐ {week.price_stars} ⭐ — {week.generations} толкований (разово)\n'
        f'⭐ {month.price_stars} ⭐ — {month.generations} толкований (разово)\n\n'
        f'Отключить можно в любой момент в {balance_hint}.\n\n'
        f'Переходя к оплате, вы соглашаетесь с <a href="{cfg.offer_url}">офертой</a>.'
    )

