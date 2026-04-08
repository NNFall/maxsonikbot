from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from maxapi import F, Router
from maxapi.context import BaseContext
from maxapi.types import Command, CommandStart, MessageCallback, MessageCreated

from config import load_config
from database import crud
from max_keyboards import main_menu_attachments, menu_only_attachments
from services.notify import notify_admin

router = Router("start")
config = load_config()
logger = logging.getLogger(__name__)


def _extract_payload(args: list[str] | None) -> str | None:
    if not args:
        return None
    payload = (args[0] or "").strip()
    return payload or None


def _user_id(event: MessageCreated | MessageCallback) -> int | None:
    if getattr(event, "from_user", None):
        return int(event.from_user.user_id)
    if isinstance(event, MessageCreated) and event.message.sender:
        return int(event.message.sender.user_id)
    if isinstance(event, MessageCallback):
        return int(event.callback.user.user_id)
    return None


def _chat_id(event: MessageCreated | MessageCallback) -> int | None:
    message = getattr(event, "message", None)
    if message and message.recipient:
        return message.recipient.chat_id
    return None


async def _send_main_menu(bot, chat_id: int) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "🔮 <b>Таро Магия</b>\n"
            "Здравствуйте! Я сделаю расклад на 3 карты и дам разбор: текущая ситуация, препятствие и совет.\n"
            "Задайте вопрос — помогу увидеть направление и подсказки.\n\n"
            "Выберите раздел ниже 👇"
        ),
        attachments=main_menu_attachments(),
    )


async def _process_start(event: MessageCreated, payload: str | None) -> None:
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
                text=f"🎁 Промокод активирован. Начислено {credits} раскладов.",
            )
        else:
            await event.bot.send_message(
                chat_id=chat_id,
                text="Промокод недействителен или уже использован.",
            )

    if is_new:
        tag = utm_source or "без метки"
        username = f"@{event.from_user.username}" if event.from_user and event.from_user.username else "-"
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
            "1) Нажмите «Задать вопрос»\n"
            "2) Введите ваш вопрос\n"
            "3) Получите первую карту и разбор\n"
            "4) Откройте полный расклад\n\n"
            f"Поддержка: {config.support_contact}"
        ),
        attachments=menu_only_attachments(),
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
            f"Бонус: <b>{config.ref_bonus}</b> раскладов после первой покупки друга.\n\n"
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
        await event.answer(notification="Сообщение не найдено")
        return
    await event.answer(notification="Открываю меню")
    await _send_main_menu(event.bot, chat_id)


@router.message_callback(F.callback.payload == "menu:help")
async def cb_help(event: MessageCallback) -> None:
    chat_id = _chat_id(event)
    if chat_id is None:
        await event.answer(notification="Сообщение не найдено")
        return
    await event.answer(notification="Открываю помощь")
    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "❓ <b>Помощь</b>\n"
            "1) Нажмите «Задать вопрос»\n"
            "2) Введите ваш вопрос\n"
            "3) Получите первую карту и разбор\n"
            "4) Откройте полный расклад\n\n"
            f"Поддержка: {config.support_contact}"
        ),
        attachments=menu_only_attachments(),
    )


@router.message_callback(F.callback.payload == "menu:invite")
async def cb_invite(event: MessageCallback) -> None:
    await event.answer(notification="Готово")
    await _send_invite(event)
