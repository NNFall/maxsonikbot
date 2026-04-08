from __future__ import annotations

from maxapi.types import MessageButton
from maxapi.types.attachments.attachment import Attachment
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def admin_help_attachments() -> list[Attachment]:
    kb = InlineKeyboardBuilder()
    kb.row(MessageButton(text="/admin_help"), MessageButton(text="/botstats"))
    kb.row(MessageButton(text="/adstats_all"), MessageButton(text="/admin_list"))
    return [kb.as_markup()]
