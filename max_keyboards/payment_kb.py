from __future__ import annotations

from maxapi.types import CallbackButton, LinkButton
from maxapi.types.attachments.attachment import Attachment
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def choose_subscription_prompt_attachments() -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="✅ Выбрать подписку", payload="sub:choose"))
    kb.row(CallbackButton(text="🏠 Главное меню", payload="menu:main"))
    return [kb.as_markup()]


def choose_subscription_attachments(plans: dict[str, object], cb_yoo_prefix: str = "sub:choose:yoo") -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    week = plans.get("week")
    month = plans.get("month")
    if week:
        period = week.title.lower() if hasattr(week, "title") else "неделя"
        kb.row(
            CallbackButton(
                text=f"🔥 {week.price_rub} ₽ / {period} — {week.generations} толкований",
                payload=f"{cb_yoo_prefix}:{week.id}",
            )
        )
    if month:
        period = month.title.lower() if hasattr(month, "title") else "месяц"
        kb.row(
            CallbackButton(
                text=f"⭐ {month.price_rub} ₽ / {period} — {month.generations} толкований",
                payload=f"{cb_yoo_prefix}:{month.id}",
            )
        )
    kb.row(CallbackButton(text="⬅️ Назад", payload="menu:balance"))
    return [kb.as_markup()]


def subscription_manage_attachments(auto_renew: bool) -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🔄 Обновить подписку сейчас", payload="sub:renew_choose"))
    if auto_renew:
        kb.row(CallbackButton(text="❌ Отключить подписку", payload="sub:cancel"))
    kb.row(CallbackButton(text="🏠 Главное меню", payload="menu:main"))
    return [kb.as_markup()]


def pay_url_attachments(url: str) -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(LinkButton(text="💳 Оплатить", url=url))
    kb.row(CallbackButton(text="🏠 Главное меню", payload="menu:main"))
    return [kb.as_markup()]


def payment_success_attachments() -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🌙 Разобрать сон", payload="menu:ask"))
    kb.row(CallbackButton(text="🏠 Главное меню", payload="menu:main"))
    return [kb.as_markup()]
