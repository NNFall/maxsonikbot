from __future__ import annotations

from maxapi.types import CallbackButton, LinkButton
from maxapi.types.attachments.attachment import Attachment
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def menu_only_attachments() -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🏠 Главное меню", payload="menu:main"))
    return [kb.as_markup()]


def help_attachments(support_url: str | None) -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    if support_url and support_url.startswith(("http://", "https://")):
        kb.row(LinkButton(text="🛟 Техподдержка", url=support_url))
    kb.row(CallbackButton(text="🏠 Главное меню", payload="menu:main"))
    return [kb.as_markup()]
