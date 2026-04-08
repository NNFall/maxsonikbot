from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from maxapi import F, Router
from maxapi.context import BaseContext
from maxapi.types import Command, MessageCallback, MessageCreated

from config import load_config
from database import crud
from max_handlers.states import TarotState
from max_keyboards import (
    choose_subscription_prompt_attachments,
    main_menu_attachments,
    tarot_after_reading_attachments,
    tarot_open_full_attachments,
)
from prompts.tarot_prompts import paywall_text
from services.notify import notify_admin
from services.subscriptions import get_plans
from services.tarot_ai import generate_tarot_followup_text
from services.tarot_context import get_context, set_context
from services.tarot_deck import draw_cards, load_deck, restore_drawn_cards
from services.tarot_reading_max import run_paid_tarot_reading, run_tarot_continuation, run_teaser_tarot_reading

router = Router("tarot")
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
    "что дальше",
    "и что дальше",
    "подробнее",
}
FOLLOWUP_PHRASES = (
    "что это значит",
    "что значит",
    "не понял",
    "непонятно",
    "поясни",
    "поясните",
    "объясни",
    "объясните",
    "можно подробнее",
    "как понять",
    "почему так",
    "и что дальше",
    "что дальше",
    "уточни",
    "уточните",
)


def _extract_text(event: MessageCreated) -> str:
    body = event.message.body
    return (body.text or "").strip() if body else ""


def _normalize_question(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.strip().split())


def _serialize_cards(cards) -> list[dict]:
    return [{"slug": card.card.slug, "rev": int(card.is_reversed)} for card in cards]


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
    if not text:
        return False
    normalized = _normalize_question(text).lower()
    if not normalized:
        return False
    if normalized in FOLLOWUP_SHORT:
        return True
    return any(phrase in normalized for phrase in FOLLOWUP_PHRASES)


def _plain_text(text: str) -> str:
    plain = TAG_RE.sub("", text or "")
    return plain.replace("*", "").replace("_", "").replace("`", "").strip()


async def _send_markdown_safe(bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text, format="markdown")
    except Exception:
        await bot.send_message(chat_id=chat_id, text=_plain_text(text))


def _build_inactive_balance_text(balance: int) -> str:
    plans = get_plans()
    week = plans.get("week")
    month = plans.get("month")
    week_period = week.title.lower() if week else "неделя"
    month_period = month.title.lower() if month else "месяц"
    return (
        "⚠️ <b>Недостаточно раскладов.</b>\n"
        f"🔮 Доступно: <b>{balance}</b>\n\n"
        "<b>Подписка</b>\n"
        f"🔥 {week.price_rub} ₽ / {week_period} — {week.generations} раскладов\n"
        f"⭐ {month.price_rub} ₽ / {month_period} — {month.generations} раскладов\n\n"
        f"Переходя к оплате, вы соглашаетесь с <a href=\"{config.offer_url}\">офертой</a>."
    )


async def _send_ask_prompt(bot, chat_id: int) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "<b>Задайте вопрос таро</b>\n"
            "Примеры:\n"
            "• <i>Когда в моей жизни появятся серьезные отношения?</i>\n"
            "• <i>Что поможет мне увеличить доход?</i>\n\n"
            "Я сделаю расклад и дам подробный разбор."
        ),
    )


async def _handle_followup(event: MessageCreated, ctx) -> None:
    uid = _user_id_from_event(event)
    chat_id = _chat_id_from_event(event)
    if uid is None or chat_id is None:
        return

    cards = restore_drawn_cards(config.tarot_cards_dir, ctx.cards_payload)
    if ctx.mode == "teaser" and cards:
        cards = [cards[0]]
    try:
        text = await generate_tarot_followup_text(
            ctx.question,
            _normalize_question(_extract_text(event)),
            cards,
            ctx.last_text,
            ctx.mode,
        )
        await _send_markdown_safe(event.bot, chat_id, text)
        set_context(
            user_id=uid,
            question=ctx.question,
            cards_payload=ctx.cards_payload,
            mode=ctx.mode,
            last_text=text,
        )
    except Exception as e:
        logger.exception("Tarot followup failed user_id=%s", uid)
        await event.bot.send_message(chat_id=chat_id, text="Не удалось уточнить расклад. Попробуйте позже.")
        await notify_admin(
            event.bot,
            config.admin_notify_ids,
            f"❌ Ошибка уточнения расклада: {e} (user {uid} @{_username_from_event(event) or '-'})",
        )


async def _process_question(event: MessageCreated, context: BaseContext) -> None:
    uid = _user_id_from_event(event)
    chat_id = _chat_id_from_event(event)
    username = _username_from_event(event)
    if uid is None or chat_id is None:
        return

    question = _normalize_question(_extract_text(event))
    if len(question) < 4:
        await event.bot.send_message(chat_id=chat_id, text="Сформулируйте вопрос чуть подробнее.")
        return
    if len(question) > 350:
        await event.bot.send_message(chat_id=chat_id, text="Слишком длинный вопрос. Сократите его до 350 символов.")
        return

    user = await crud.get_user(config.database_path, uid)
    if not user:
        await event.bot.send_message(chat_id=chat_id, text="Пользователь не найден. Нажмите /start")
        await context.clear()
        return

    deck = load_deck(config.tarot_cards_dir)
    if len(deck) < 3:
        await event.bot.send_message(
            chat_id=chat_id,
            text="В колоде недостаточно карт. Добавьте минимум 3 файла в папку карт.",
        )
        return

    await context.clear()
    await context.update_data(tarot_question=question)
    balance = await crud.get_balance(config.database_path, uid)

    asyncio.create_task(
        notify_admin(
            event.bot,
            config.admin_notify_ids,
            f"🔮 Пользователь задал вопрос: {uid} (@{username or '-'})\nВопрос: {question}",
        )
    )

    if (
        int(user.get("free_trial_used", 0)) == 0
        and int(user.get("has_purchased", 0)) == 0
        and balance < config.tarot_spread_cost
    ):
        cards = draw_cards(deck, count=1)
        cards_payload = _serialize_cards(cards)
        await event.bot.send_message(chat_id=chat_id, text="🔮 Открываю первую карту...")
        ok, payload, first_text = await run_teaser_tarot_reading(
            event.bot,
            user_id=uid,
            chat_id=chat_id,
            question=question,
            cards_payload=cards_payload,
        )
        if not ok:
            await event.bot.send_message(chat_id=chat_id, text="Не удалось открыть первую карту. Попробуйте позже.")
            return

        await crud.set_free_trial_used(config.database_path, uid, 1)
        await context.update_data(
            pending_action=json.dumps(
                {
                    "type": "tarot_full",
                    "question": question,
                    "username": username,
                    "first_card": payload[0] if payload else None,
                    "first_text": first_text,
                }
            )
        )
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Продолжение расклада в двух оставшихся картах дает главный ответ.\n"
                "Нажмите кнопку ниже, чтобы открыть полный расклад."
            ),
            attachments=tarot_open_full_attachments(),
        )
        return

    if balance < config.tarot_spread_cost:
        await context.update_data(
            pending_action=json.dumps(
                {
                    "type": "tarot_full",
                    "question": question,
                    "username": username,
                }
            )
        )
        await event.bot.send_message(
            chat_id=chat_id,
            text=_build_inactive_balance_text(balance),
            attachments=choose_subscription_prompt_attachments(),
        )
        return

    cards = draw_cards(deck, count=3)
    cards_payload = _serialize_cards(cards)
    await context.update_data(tarot_cards=cards_payload)
    await event.bot.send_message(chat_id=chat_id, text="🔮 Выполняю полный расклад...")
    ok = await run_paid_tarot_reading(
        event.bot,
        user_id=uid,
        chat_id=chat_id,
        question=question,
        username=username,
        cards_payload=cards_payload,
    )
    if ok:
        await event.bot.send_message(
            chat_id=chat_id,
            text="✅ Расклад завершен.\nЕсли хотите, задайте новый вопрос или вернитесь в меню.",
            attachments=tarot_after_reading_attachments(),
        )


async def _open_full_from_pending(event: MessageCallback, context: BaseContext) -> None:
    uid = _user_id_from_event(event)
    chat_id = _chat_id_from_event(event)
    username = _username_from_event(event)
    if uid is None or chat_id is None:
        await event.answer(notification="Сообщение не найдено")
        return

    data = await context.get_data()
    pending_payload = data.get("pending_action")
    pending_action: dict | None = None
    if pending_payload:
        try:
            pending_action = json.loads(pending_payload)
        except json.JSONDecodeError:
            pending_action = None

    if not pending_action or pending_action.get("type") != "tarot_full":
        ctx = get_context(uid)
        if ctx and ctx.mode == "teaser" and ctx.cards_payload:
            pending_action = {
                "type": "tarot_full",
                "question": ctx.question,
                "username": username,
                "first_card": ctx.cards_payload[0],
                "first_text": ctx.last_text,
            }
            await context.update_data(pending_action=json.dumps(pending_action))

    if not pending_action or pending_action.get("type") != "tarot_full":
        await event.answer(notification="Нет активного расклада")
        await event.bot.send_message(chat_id=chat_id, text="Не найден активный расклад. Задайте вопрос заново.")
        return

    balance = await crud.get_balance(config.database_path, uid)
    if balance < config.tarot_spread_cost:
        await event.answer(notification="Недостаточно раскладов")
        await event.bot.send_message(
            chat_id=chat_id,
            text=f"{paywall_text()}\n\n{_build_inactive_balance_text(balance)}",
            attachments=choose_subscription_prompt_attachments(),
        )
        return

    await event.answer(notification="Открываю полный расклад")
    await event.bot.send_message(chat_id=chat_id, text="🔮 Продолжаю расклад...")

    question = pending_action.get("question") or ""
    first_card = pending_action.get("first_card")
    first_text = pending_action.get("first_text") or ""
    ok = False
    if isinstance(first_card, dict):
        ok = await run_tarot_continuation(
            event.bot,
            user_id=uid,
            chat_id=chat_id,
            question=question,
            username=username,
            first_card_payload=first_card,
            first_text=first_text,
        )
    else:
        cards_payload = pending_action.get("cards")
        ok = await run_paid_tarot_reading(
            event.bot,
            user_id=uid,
            chat_id=chat_id,
            question=question,
            username=username,
            cards_payload=cards_payload if isinstance(cards_payload, list) else None,
        )

    if ok:
        await context.update_data(pending_action="")
        await event.bot.send_message(
            chat_id=chat_id,
            text="✅ Расклад завершен.\nЕсли хотите, задайте новый вопрос или вернитесь в меню.",
            attachments=tarot_after_reading_attachments(),
        )


@router.message_created(Command("ask"))
async def cmd_ask(event: MessageCreated, context: BaseContext) -> None:
    chat_id = _chat_id_from_event(event)
    if chat_id is None:
        return
    await context.clear()
    await _send_ask_prompt(event.bot, chat_id)
    await context.set_state(TarotState.waiting_question)


@router.message_callback(F.callback.payload == "menu:ask")
async def cb_menu_ask(event: MessageCallback, context: BaseContext) -> None:
    chat_id = _chat_id_from_event(event)
    if chat_id is None:
        await event.answer(notification="Сообщение не найдено")
        return
    await event.answer(notification="Жду ваш вопрос")
    await context.clear()
    await _send_ask_prompt(event.bot, chat_id)
    await context.set_state(TarotState.waiting_question)


@router.message_callback(F.callback.payload == "tarot:open_full")
async def cb_tarot_open_full(event: MessageCallback, context: BaseContext) -> None:
    await _open_full_from_pending(event, context)


@router.message_created(states=TarotState.waiting_question)
async def tarot_question_received(event: MessageCreated, context: BaseContext) -> None:
    await context.set_state(None)
    await _process_question(event, context)


@router.message_created()
async def tarot_fallback(event: MessageCreated, context: BaseContext) -> None:
    text = _extract_text(event)
    if not text:
        return
    if text.startswith("/"):
        return

    ctx = get_context(_user_id_from_event(event) or 0)
    if ctx and _is_followup_message(text):
        await _handle_followup(event, ctx)
        return

    await _process_question(event, context)
