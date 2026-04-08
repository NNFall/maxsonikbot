from __future__ import annotations

from maxapi.types import CallbackButton
from maxapi.types.attachments.attachment import Attachment
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def tarot_open_full_attachments() -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="✅ Открыть полный расклад", payload="tarot:open_full"))
    return [kb.as_markup()]


def tarot_after_reading_attachments() -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🔮 Задать еще вопрос", payload="menu:ask"))
    kb.row(CallbackButton(text="🏠 Главное меню", payload="menu:main"))
    return [kb.as_markup()]
