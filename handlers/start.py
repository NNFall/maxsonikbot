from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import load_config
from database import crud
from keyboards.common_kb import menu_only_kb
from keyboards.main_menu import main_menu_kb
from services.notify import notify_admin

router = Router()
config = load_config()
logger = logging.getLogger(__name__)


def _parse_start_payload(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    payload = _parse_start_payload(message.text)

    existing = await crud.get_user(config.database_path, message.from_user.id)
    is_new = existing is None

    utm_source = None
    referrer_id = None
    promo_code = None

    if payload:
        if payload.startswith('ref_'):
            ref_val = payload.replace('ref_', '', 1)
            if ref_val.isdigit():
                referrer_id = int(ref_val)
        elif payload.startswith('promo_'):
            promo_code = payload.replace('promo_', '', 1)
        else:
            utm_source = payload

    await crud.add_user(config.database_path, message.from_user.id, utm_source, referrer_id)

    if promo_code:
        credits = await crud.use_promocode(config.database_path, promo_code, message.from_user.id)
        if credits:
            await crud.update_balance(config.database_path, message.from_user.id, credits)
            await message.answer(f'🎁 Промокод активирован. Начислено {credits} раскладов.')
        else:
            await message.answer('Промокод недействителен или уже использован.')

    if is_new:
        tag = utm_source or 'без метки'
        username = f'@{message.from_user.username}' if message.from_user.username else '-'
        asyncio.create_task(
            notify_admin(
                message.bot,
                config.admin_notify_ids,
                f'👤 Новый пользователь: {message.from_user.id} ({username}), метка: {tag}',
            )
        )

    try:
        await message.answer(
            '🔮 <b>Таро Магия</b>\n'
            'Здравствуйте! Я сделаю расклад на 3 карты и дам разбор: текущая ситуация, препятствие и совет.\n'
            'Задайте вопрос — я помогу увидеть направление и возможные подсказки.\n\n'
            'Выберите раздел ниже 👇',
            reply_markup=main_menu_kb(),
        )
    except TelegramForbiddenError:
        logger.warning('User blocked bot user_id=%s username=@%s', message.from_user.id, message.from_user.username)


@router.callback_query(F.data == 'menu:main')
async def cb_menu_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    try:
        await callback.message.answer(
            '🔮 <b>Таро Магия</b>\n'
            'Здравствуйте! Я сделаю расклад на 3 карты и дам разбор: текущая ситуация, препятствие и совет.\n'
            'Задайте вопрос — я помогу увидеть направление и возможные подсказки.\n\n'
            'Выберите раздел ниже 👇',
            reply_markup=main_menu_kb(),
        )
    except TelegramForbiddenError:
        logger.warning('User blocked bot user_id=%s username=@%s', callback.from_user.id, callback.from_user.username)


@router.message(Command('menu'))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    try:
        await message.answer(
            '🔮 <b>Таро Магия</b>\n'
            'Здравствуйте! Я сделаю расклад на 3 карты и дам разбор: текущая ситуация, препятствие и совет.\n'
            'Задайте вопрос — я помогу увидеть направление и возможные подсказки.\n\n'
            'Выберите раздел ниже 👇',
            reply_markup=main_menu_kb(),
        )
    except TelegramForbiddenError:
        logger.warning('User blocked bot user_id=%s username=@%s', message.from_user.id, message.from_user.username)


@router.callback_query(F.data == 'menu:help')
async def cb_help(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        '❓ <b>Помощь</b>\n'
        '1) Нажмите «Задать вопрос»\n'
        '2) Введите ваш вопрос\n'
        '3) Получите первую карту и разбор\n'
        '4) Откройте полный расклад\n\n'
        f'Поддержка: {config.support_contact}',
        reply_markup=menu_only_kb(),
    )


@router.message(Command('help'))
async def cmd_help(message: Message) -> None:
    await message.answer(
        '❓ <b>Помощь</b>\n'
        '1) Нажмите «Задать вопрос»\n'
        '2) Введите ваш вопрос\n'
        '3) Получите первую карту и разбор\n'
        '4) Откройте полный расклад\n\n'
        f'Поддержка: {config.support_contact}',
        reply_markup=menu_only_kb(),
    )


@router.callback_query(F.data == 'menu:invite')
async def cb_invite(callback: CallbackQuery) -> None:
    await callback.answer()
    bot_info = await callback.bot.get_me()
    link = f'https://t.me/{bot_info.username}?start=ref_{callback.from_user.id}'
    await callback.message.answer(
        '🤝 <b>Пригласить друга</b>\n'
        'Отправьте другу вашу персональную ссылку.\n'
        f'Бонус: <b>{config.ref_bonus}</b> раскладов после первой покупки друга.\n\n'
        f'Ваша ссылка:\n<code>{link}</code>',
        reply_markup=menu_only_kb(),
    )


@router.message(Command('invite'))
async def cmd_invite(message: Message) -> None:
    bot_info = await message.bot.get_me()
    link = f'https://t.me/{bot_info.username}?start=ref_{message.from_user.id}'
    await message.answer(
        '🤝 <b>Пригласить друга</b>\n'
        'Отправьте другу вашу персональную ссылку.\n'
        f'Бонус: <b>{config.ref_bonus}</b> раскладов после первой покупки друга.\n\n'
        f'Ваша ссылка:\n<code>{link}</code>',
        reply_markup=menu_only_kb(),
    )

