from __future__ import annotations

import asyncio
import json
import logging
import re

from maxapi import F, Router
from maxapi.context import BaseContext
from maxapi.types import Command, MessageCallback, MessageCreated

from config import load_config
from database import crud
from max_handlers.states import DreamState
from max_keyboards import (
    choose_subscription_attachments,
    dream_after_interpretation_attachments,
    dream_open_full_attachments,
)
from services.dream_context import get_context
from services.dream_reading_max import (
    run_dream_followup,
    run_paid_dream_interpretation,
    run_teaser_dream_interpretation,
)
from services.notify import notify_admin
from services.subscriptions import get_plans

router = Router("dream")
config = load_config()
logger = logging.getLogger(__name__)

TAG_RE = re.compile(r"<[^>]+>")
FOLLOWUP_SHORT = {
    "что",
    "что?",
    "почему",
    "почему?",
    "не понял",
    "непонятно",
    "поясни",
    "поясните",
    "объясни",
    "объясните",
    "что это значит",
    "что значит",
    "что означает",
    "подробнее",
}
FOLLOWUP_PHRASES = (
    "что это значит",
    "что значит",
    "что означает",
    "не понял",
    "непонятно",
    "поясни",
    "поясните",
    "объясни",
    "объясните",
    "можно подробнее",
    "как понять",
    "почему так",
    "уточни",
    "уточните",
)


def _extract_text(event: MessageCreated) -> str:
    body = event.message.body
    return (body.text or "").strip() if body else ""


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.strip().split())


def _user_id_from_event(event: MessageCreated | MessageCallback) -> int | None:
    if getattr(event, "from_user", None):
        return int(event.from_user.user_id)
    if isinstance(event, MessageCreated) and event.message.sender:
        return int(event.message.sender.user_id)
    if isinstance(event, MessageCallback):
        return int(event.callback.user.user_id)
    return None


def _chat_id_from_event(event: MessageCreated | MessageCallback) -> int | None:
    message = getattr(event, "message", None)
    if message and message.recipient:
        return message.recipient.chat_id
    return None


def _username_from_event(event: MessageCreated | MessageCallback) -> str | None:
    if getattr(event, "from_user", None):
        return event.from_user.username
    if isinstance(event, MessageCreated) and event.message.sender:
        return event.message.sender.username
    if isinstance(event, MessageCallback):
        return event.callback.user.username
    return None


def _is_followup_message(text: str | None) -> bool:
    normalized = _normalize_text(text).lower()
    if not normalized:
        return False
    if normalized in FOLLOWUP_SHORT:
        return True
    return any(phrase in normalized for phrase in FOLLOWUP_PHRASES)


async def _send_subscription_choice(bot, chat_id: int) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text="Выберите подписку 👇",
        attachments=choose_subscription_attachments(get_plans(), include_back=False),
    )


async def _send_ask_prompt(bot, chat_id: int) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "<b>Опишите сон</b>\n"
            "Напишите одним сообщением, что вам приснилось.\n\n"
            "Можно коротко, но лучше добавить детали: место, людей, предметы, эмоции и чем сон закончился."
        ),
    )


async def _process_dream(event: MessageCreated, context: BaseContext) -> None:
    uid = _user_id_from_event(event)
    chat_id = _chat_id_from_event(event)
    username = _username_from_event(event)
    if uid is None or chat_id is None:
        return

    dream_text = _normalize_text(_extract_text(event))
    if len(dream_text) < 10:
        await event.bot.send_message(chat_id=chat_id, text="Опишите сон чуть подробнее: хотя бы 1-2 предложения.")
        return
    if len(dream_text) > 1200:
        await event.bot.send_message(chat_id=chat_id, text="Сон слишком длинный. Сократите описание до 1200 символов.")
        return

    user = await crud.get_user(config.database_path, uid)
    if not user:
        await event.bot.send_message(chat_id=chat_id, text="Пользователь не найден. Нажмите /start")
        await context.clear()
        return

    await context.clear()
    await context.update_data(dream_text=dream_text)
    balance = await crud.get_balance(config.database_path, uid)
    cost = config.dream_interpretation_cost

    asyncio.create_task(
        notify_admin(
            event.bot,
            config.admin_notify_ids,
            f"🌙 Пользователь описал сон: {uid} (@{username or '-'})\nСон: {dream_text}",
        )
    )

    pending_payload = {
        "type": "dream_full",
        "dream_text": dream_text,
        "username": username,
    }

    if int(user.get("free_trial_used", 0)) == 0 and int(user.get("has_purchased", 0)) == 0 and balance < cost:
        ok, teaser_text = await run_teaser_dream_interpretation(event.bot, uid, chat_id, dream_text)
        if not ok:
            await event.bot.send_message(chat_id=chat_id, text="Не удалось разобрать сон. Попробуйте позже.")
            return

        await crud.set_free_trial_used(config.database_path, uid, 1)
        pending_payload["teaser_text"] = teaser_text
        await context.update_data(pending_action=json.dumps(pending_payload))
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Полный разбор покажет символы, возможные предупреждения, эмоциональный смысл "
                "и практический совет.\nНажмите кнопку ниже, чтобы открыть полный разбор."
            ),
            attachments=dream_open_full_attachments(),
        )
        return

    if balance < cost:
        await context.update_data(pending_action=json.dumps(pending_payload))
        await _send_subscription_choice(event.bot, chat_id)
        return

    ok = await run_paid_dream_interpretation(
        event.bot,
        user_id=uid,
        chat_id=chat_id,
        dream_text=dream_text,
        username=username,
    )
    if ok:
        await event.bot.send_message(
            chat_id=chat_id,
            text="✅ Толкование готово.\nМожете описать новый сон или вернуться в меню.",
            attachments=dream_after_interpretation_attachments(),
        )


async def _open_full_from_pending(event: MessageCallback, context: BaseContext) -> None:
    uid = _user_id_from_event(event)
    chat_id = _chat_id_from_event(event)
    username = _username_from_event(event)
    if uid is None or chat_id is None:
        await event.answer()
        return

    data = await context.get_data()
    pending_payload = data.get("pending_action")
    pending_action: dict | None = None
    if pending_payload:
        try:
            pending_action = json.loads(pending_payload)
        except json.JSONDecodeError:
            pending_action = None

    if not pending_action or pending_action.get("type") != "dream_full":
        ctx = get_context(uid)
        if ctx and ctx.mode == "teaser":
            pending_action = {
                "type": "dream_full",
                "dream_text": ctx.dream_text,
                "username": username,
                "teaser_text": ctx.last_text,
            }
            await context.update_data(pending_action=json.dumps(pending_action))

    if not pending_action or pending_action.get("type") != "dream_full":
        await event.answer()
        await event.bot.send_message(chat_id=chat_id, text="Не найден активный сон. Опишите сон заново.")
        return

    balance = await crud.get_balance(config.database_path, uid)
    if balance < config.dream_interpretation_cost:
        await event.answer()
        await _send_subscription_choice(event.bot, chat_id)
        return

    await event.answer()
    dream_text = pending_action.get("dream_text") or ""
    ok = await run_paid_dream_interpretation(
        event.bot,
        user_id=uid,
        chat_id=chat_id,
        dream_text=dream_text,
        username=username,
    )
    if ok:
        await context.update_data(pending_action="")
        await event.bot.send_message(
            chat_id=chat_id,
            text="✅ Толкование готово.\nМожете описать новый сон или вернуться в меню.",
            attachments=dream_after_interpretation_attachments(),
        )


async def _handle_followup(event: MessageCreated, ctx) -> None:
    uid = _user_id_from_event(event)
    chat_id = _chat_id_from_event(event)
    username = _username_from_event(event)
    if uid is None or chat_id is None:
        return

    await run_dream_followup(
        event.bot,
        user_id=uid,
        chat_id=chat_id,
        dream_text=ctx.dream_text,
        followup=_normalize_text(_extract_text(event)),
        last_text=ctx.last_text,
        mode=ctx.mode,
        username=username,
    )


@router.message_created(Command("ask"))
async def cmd_ask(event: MessageCreated, context: BaseContext) -> None:
    chat_id = _chat_id_from_event(event)
    if chat_id is None:
        return
    await context.clear()
    await _send_ask_prompt(event.bot, chat_id)
    await context.set_state(DreamState.waiting_dream)


@router.message_callback(F.callback.payload == "menu:ask")
async def cb_menu_ask(event: MessageCallback, context: BaseContext) -> None:
    chat_id = _chat_id_from_event(event)
    if chat_id is None:
        await event.answer()
        return
    await event.answer()
    await context.clear()
    await _send_ask_prompt(event.bot, chat_id)
    await context.set_state(DreamState.waiting_dream)


@router.message_callback(F.callback.payload == "dream:open_full")
async def cb_dream_open_full(event: MessageCallback, context: BaseContext) -> None:
    await _open_full_from_pending(event, context)


@router.message_created(states=DreamState.waiting_dream)
async def dream_text_received(event: MessageCreated, context: BaseContext) -> None:
    await context.set_state(None)
    await _process_dream(event, context)


@router.message_created()
async def dream_fallback(event: MessageCreated, context: BaseContext) -> None:
    text = _extract_text(event)
    if not text:
        return
    if text.startswith("/"):
        return

    ctx = get_context(_user_id_from_event(event) or 0)
    if ctx and _is_followup_message(text):
        await _handle_followup(event, ctx)
        return

    await _process_dream(event, context)
