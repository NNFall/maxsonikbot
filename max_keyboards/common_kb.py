from __future__ import annotations

from maxapi.types import CallbackButton
from maxapi.types.attachments.attachment import Attachment
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def menu_only_attachments() -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(CallbackButton(text="🏠 Главное меню", payload="menu:main"))
    return [kb.as_markup()]
