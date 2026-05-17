from __future__ import annotations

from maxapi.types import CallbackButton
from maxapi.types.attachments.attachment import Attachment
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def dream_open_full_attachments() -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="✅ Открыть полный разбор", payload="dream:open_full"))
    return [kb.as_markup()]


def dream_after_interpretation_attachments() -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🌙 Разобрать еще сон", payload="menu:ask"))
    kb.row(CallbackButton(text="🏠 Главное меню", payload="menu:main"))
    return [kb.as_markup()]
