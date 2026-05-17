from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from maxapi import F, Router
from maxapi.context import BaseContext
from maxapi.types import BotStarted, Command, CommandStart, MessageCallback, MessageCreated

from config import load_config
from database import crud
from max_keyboards import help_attachments, main_menu_attachments, menu_only_attachments
from services.notify import notify_admin

router = Router("start")
config = load_config()
logger = logging.getLogger(__name__)


def _extract_payload(args: list[str] | None) -> str | None:
    if not args:
        return None
    payload = (args[0] or "").strip()
    return payload or None


def _user_id(event: MessageCreated | MessageCallback | BotStarted) -> int | None:
    if isinstance(event, BotStarted):
        return int(event.user.user_id)
    if getattr(event, "from_user", None):
        return int(event.from_user.user_id)
    if isinstance(event, MessageCreated) and event.message.sender:
        return int(event.message.sender.user_id)
    if isinstance(event, MessageCallback):
        return int(event.callback.user.user_id)
    return None


def _chat_id(event: MessageCreated | MessageCallback | BotStarted) -> int | None:
    if isinstance(event, BotStarted):
        return int(event.chat_id)
    message = getattr(event, "message", None)
    if message and message.recipient:
        return message.recipient.chat_id
    return None


def _username(event: MessageCreated | MessageCallback | BotStarted) -> str | None:
    if isinstance(event, BotStarted):
        return event.user.username
    if getattr(event, "from_user", None):
        return event.from_user.username
    if isinstance(event, MessageCallback):
        return event.callback.user.username
    return None


async def _send_main_menu(bot, chat_id: int) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "🌙 <b>Сонник ИИ</b>\n"
            "Здравствуйте! Опишите, что вам приснилось, а я разберу значение сна: символы, возможные знаки, "
            "предупреждения, эмоциональный смысл и практический совет.\n\n"
            "Выберите раздел ниже 👇"
        ),
        attachments=main_menu_attachments(),
    )


async def _process_start(event: MessageCreated | BotStarted, payload: str | None) -> None:
    uid = _user_id(event)
    chat_id = _chat_id(event)
    if uid is None or chat_id is None:
        return

    existing = await crud.get_user(config.database_path, uid)
    is_new = existing is None

    utm_source = None
    referrer_id = None
    promo_code = None

    if payload:
        if payload.startswith("ref_"):
            ref_val = payload.replace("ref_", "", 1)
            if ref_val.isdigit():
                referrer_id = int(ref_val)
        elif payload.startswith("promo_"):
            promo_code = payload.replace("promo_", "", 1)
        else:
            utm_source = payload

    await crud.add_user(config.database_path, uid, utm_source, referrer_id)

    if promo_code:
        credits = await crud.use_promocode(config.database_path, promo_code, uid)
        if credits:
            await crud.update_balance(config.database_path, uid, credits)
            await event.bot.send_message(
                chat_id=chat_id,
                text=f"🎁 Промокод активирован. Начислено {credits} толкований.",
            )
        else:
            await event.bot.send_message(
                chat_id=chat_id,
                text="Промокод недействителен или уже использован.",
            )

    if is_new:
        tag = utm_source or "без метки"
        raw_username = _username(event)
        username = f"@{raw_username}" if raw_username else "-"
        asyncio.create_task(
            notify_admin(
                event.bot,
                config.admin_notify_ids,
                f"👤 Новый пользователь: {uid} ({username}), метка: {tag}",
            )
        )

    await _send_main_menu(event.bot, chat_id)


@router.message_created(CommandStart())
async def cmd_start(event: MessageCreated, args: list[str], context: BaseContext) -> None:
    await context.clear()
    payload = _extract_payload(args)
    await _process_start(event, payload)


@router.bot_started()
async def on_bot_started(event: BotStarted, context: BaseContext) -> None:
    await context.clear()
    await _process_start(event, event.payload)


@router.message_created(Command("menu"))
async def cmd_menu(event: MessageCreated, context: BaseContext) -> None:
    await context.clear()
    chat_id = _chat_id(event)
    if chat_id is None:
        return
    await _send_main_menu(event.bot, chat_id)


@router.message_created(Command(["start", "старт"], prefix=""))
async def cmd_start_plain_text(event: MessageCreated, args: list[str], context: BaseContext) -> None:
    await context.clear()
    payload = _extract_payload(args)
    await _process_start(event, payload)


@router.message_created(Command("help"))
async def cmd_help(event: MessageCreated) -> None:
    chat_id = _chat_id(event)
    if chat_id is None:
        return
    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "❓ <b>Помощь</b>\n"
            "1) Нажмите «Разобрать сон»\n"
            "2) Опишите сон одним сообщением\n"
            "3) Получите короткое пробное толкование или полный разбор\n"
            "4) При необходимости оформите подписку"
        ),
        attachments=help_attachments(config.support_contact),
    )


async def _send_invite(event: MessageCreated | MessageCallback) -> None:
    uid = _user_id(event)
    chat_id = _chat_id(event)
    if uid is None or chat_id is None:
        return

    me = await event.bot.get_me()
    username = me.username
    deeplink = f"https://max.ru/{username}?start={quote(f'ref_{uid}', safe='')}"
    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "🤝 <b>Пригласить друга</b>\n"
            "Отправьте другу персональную ссылку.\n"
            f"Бонус: <b>{config.ref_bonus}</b> толкований после первой покупки друга.\n\n"
            f"Ваша ссылка:\n<code>{deeplink}</code>"
        ),
        attachments=menu_only_attachments(),
    )


@router.message_created(Command("invite"))
async def cmd_invite(event: MessageCreated) -> None:
    await _send_invite(event)


@router.message_callback(F.callback.payload == "menu:main")
async def cb_menu_main(event: MessageCallback, context: BaseContext) -> None:
    await context.clear()
    chat_id = _chat_id(event)
    if chat_id is None:
        await event.answer()
        return
    await event.answer()
    await _send_main_menu(event.bot, chat_id)


@router.message_callback(F.callback.payload == "menu:help")
async def cb_help(event: MessageCallback) -> None:
    chat_id = _chat_id(event)
    if chat_id is None:
        await event.answer()
        return
    await event.answer()
    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "❓ <b>Помощь</b>\n"
            "1) Нажмите «Разобрать сон»\n"
            "2) Опишите сон одним сообщением\n"
            "3) Получите короткое пробное толкование или полный разбор\n"
            "4) При необходимости оформите подписку"
        ),
        attachments=help_attachments(config.support_contact),
    )


@router.message_callback(F.callback.payload == "menu:invite")
async def cb_invite(event: MessageCallback) -> None:
    await event.answer()
    await _send_invite(event)
