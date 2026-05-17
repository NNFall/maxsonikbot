from __future__ import annotations

import logging
import re
from contextlib import suppress

from maxapi.enums.attachment import AttachmentType
from maxapi.enums.parse_mode import ParseMode
from maxapi.enums.sender_action import SenderAction
from maxapi.types import Attachment, StickerAttachmentPayload

from config import load_config
from database import crud
from services.dream_ai import generate_dream_followup_text, generate_dream_interpretation_text
from services.dream_context import set_context
from services.notify import notify_admin

logger = logging.getLogger(__name__)
TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(text: str) -> str:
    cleaned = TAG_RE.sub("", text or "").strip()
    return cleaned.replace("*", "").replace("_", "").replace("`", "")


def _extract_mid(send_result) -> str | None:
    try:
        return send_result.message.body.mid
    except Exception:
        return None


async def _send_markdown_safe(bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text, format=ParseMode.MARKDOWN)
    except Exception:
        await bot.send_message(chat_id=chat_id, text=_plain_text(text))


async def _start_progress_feedback(bot, chat_id: int, cfg) -> tuple[str | None, str | None]:
    sticker_mid: str | None = None
    text_mid: str | None = None

    sticker_code = (cfg.dream_progress_sticker_code or cfg.dream_progress_sticker_id or "").strip()
    sticker_url = (cfg.dream_progress_sticker_url or "").strip()

    if sticker_code and sticker_url:
        try:
            sticker_res = await bot.send_message(
                chat_id=chat_id,
                attachments=[
                    Attachment(
                        type=AttachmentType.STICKER,
                        payload=StickerAttachmentPayload(url=sticker_url, code=sticker_code),
                    )
                ],
            )
            sticker_mid = _extract_mid(sticker_res)
        except Exception:
            logger.exception("Failed to send dream progress sticker chat_id=%s", chat_id)

    try:
        progress_res = await bot.send_message(
            chat_id=chat_id,
            text=(cfg.dream_progress_text or "🌙 Разбираю сон и собираю толкование..."),
        )
        text_mid = _extract_mid(progress_res)
    except Exception:
        logger.exception("Failed to send dream progress message chat_id=%s", chat_id)

    with suppress(Exception):
        await bot.send_action(chat_id=chat_id, action=SenderAction.TYPING_ON)

    return sticker_mid, text_mid


async def _stop_progress_feedback(bot, sticker_mid: str | None, text_mid: str | None) -> None:
    for mid in (text_mid, sticker_mid):
        if not mid:
            continue
        with suppress(Exception):
            await bot.delete_message(message_id=mid)


async def run_teaser_dream_interpretation(bot, user_id: int, chat_id: int, dream_text: str) -> tuple[bool, str]:
    cfg = load_config()
    sticker_mid, text_mid = await _start_progress_feedback(bot, chat_id, cfg)
    try:
        text = await generate_dream_interpretation_text(dream_text, mode="teaser")
    except Exception:
        logger.exception("Dream teaser failed user_id=%s", user_id)
        await _stop_progress_feedback(bot, sticker_mid, text_mid)
        return False, ""

    await _stop_progress_feedback(bot, sticker_mid, text_mid)
    await _send_markdown_safe(bot, chat_id, text)
    set_context(user_id=user_id, dream_text=dream_text, mode="teaser", last_text=text)
    return True, text


async def run_paid_dream_interpretation(
    bot,
    user_id: int,
    chat_id: int,
    dream_text: str,
    username: str | None = None,
) -> bool:
    cfg = load_config()
    cost = cfg.dream_interpretation_cost
    balance = await crud.get_balance(cfg.database_path, user_id)
    if balance < cost:
        return False

    await crud.update_balance(cfg.database_path, user_id, -cost)
    sticker_mid: str | None = None
    text_mid: str | None = None
    try:
        sticker_mid, text_mid = await _start_progress_feedback(bot, chat_id, cfg)
        text = await generate_dream_interpretation_text(dream_text, mode="full")
        await _stop_progress_feedback(bot, sticker_mid, text_mid)
        sticker_mid = None
        text_mid = None

        await _send_markdown_safe(bot, chat_id, text)
        set_context(user_id=user_id, dream_text=dream_text, mode="full", last_text=text)
        await notify_admin(
            bot,
            cfg.admin_notify_ids,
            f"✅ Успешное толкование сна. Пользователь {user_id} (@{username or '-'})",
        )
        return True
    except Exception as e:
        logger.exception("Dream interpretation failed user_id=%s", user_id)
        await crud.update_balance(cfg.database_path, user_id, cost)
        await bot.send_message(chat_id=chat_id, text="❌ Не удалось разобрать сон. Лимит толкований возвращен.")
        await notify_admin(
            bot,
            cfg.admin_notify_ids,
            f"❌ Ошибка толкования сна: {e} (user {user_id} @{username or '-'})",
        )
        return False
    finally:
        await _stop_progress_feedback(bot, sticker_mid, text_mid)


async def run_dream_followup(
    bot,
    user_id: int,
    chat_id: int,
    dream_text: str,
    followup: str,
    last_text: str,
    mode: str,
    username: str | None = None,
) -> bool:
    cfg = load_config()
    sticker_mid, text_mid = await _start_progress_feedback(bot, chat_id, cfg)
    try:
        text = await generate_dream_followup_text(dream_text, followup, last_text, mode)
        await _stop_progress_feedback(bot, sticker_mid, text_mid)
        sticker_mid = None
        text_mid = None
        await _send_markdown_safe(bot, chat_id, text)
        set_context(user_id=user_id, dream_text=dream_text, mode=mode, last_text=text)
        return True
    except Exception as e:
        logger.exception("Dream followup failed user_id=%s", user_id)
        await bot.send_message(chat_id=chat_id, text="Не удалось уточнить толкование. Попробуйте позже.")
        await notify_admin(
            bot,
            cfg.admin_notify_ids,
            f"❌ Ошибка уточнения сна: {e} (user {user_id} @{username or '-'})",
        )
        return False
    finally:
        await _stop_progress_feedback(bot, sticker_mid, text_mid)
