from __future__ import annotations

from maxapi.types import CallbackButton, LinkButton
from maxapi.types.attachments.attachment import Attachment
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def main_menu_attachments() -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🌙 Разобрать сон", payload="menu:ask"))
    kb.row(LinkButton(text="🔮 Сделать расклад", url="https://max.ru/id644009650098_bot?start=sonik"))
    kb.row(CallbackButton(text="💳 Баланс / Подписка", payload="menu:balance"))
    kb.row(CallbackButton(text="❓ Помощь", payload="menu:help"))
    kb.row(CallbackButton(text="🤝 Пригласить друга", payload="menu:invite"))
    return [kb.as_markup()]
