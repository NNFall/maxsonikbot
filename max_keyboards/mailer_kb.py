from __future__ import annotations

from maxapi.types import CallbackButton
from maxapi.types.attachments.attachment import Attachment
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def mailer_attachments() -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🌙 Разобрать сон", payload="menu:ask"))
    kb.row(CallbackButton(text="🏠 Главное меню", payload="menu:main"))
    return [kb.as_markup()]
