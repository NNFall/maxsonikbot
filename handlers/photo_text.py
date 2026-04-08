from __future__ import annotations

import json
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config import load_config
from database import crud
from handlers.states import PhotoTextState
from keyboards.payment_kb import choose_subscription_prompt_kb
from services.balance_card import build_inactive_balance_text
from services.generation import run_text_image_generation

router = Router()
config = load_config()


@router.callback_query(F.data == 'menu:photo_text')
async def cb_photo_text(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        '🖼 <b>Создать изображение</b>\n'
        'Пришлите текстовый запрос, и я сгенерирую изображение.\n'
        'Пример: <i>человек на Эвересте с кока‑колой</i>.'
    )
    await state.set_state(PhotoTextState.waiting_prompt)


@router.message(Command('image'))
async def cmd_photo_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        '🖼 <b>Создать изображение</b>\n'
        'Пришлите текстовый запрос, и я сгенерирую изображение.\n'
        'Пример: <i>человек на Эвересте с кока‑колой</i>.'
    )
    await state.set_state(PhotoTextState.waiting_prompt)


@router.callback_query(F.data == 'again:photo_text')
async def cb_again_photo_text(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        '🖼 <b>Создать изображение</b>\n'
        'Пришлите текстовый запрос, и я сгенерирую изображение.\n'
        'Пример: <i>человек на Эвересте с кока‑колой</i>.'
    )
    await state.set_state(PhotoTextState.waiting_prompt)


@router.message(PhotoTextState.waiting_prompt)
async def photo_text_receive(message: Message, state: FSMContext) -> None:
    prompt = (message.text or '').strip()
    if not prompt:
        await message.answer('✍️ Пришлите текстовый запрос.')
        return

    balance = await crud.get_balance(config.database_path, message.from_user.id)
    if balance < config.photo_custom_cost:
        await state.update_data(
            pending_action=json.dumps(
                {
                    'type': 'photo_text',
                    'prompt': prompt,
                    'username': message.from_user.username,
                }
            )
        )
        balance_text = await build_inactive_balance_text(message.bot, balance, include_header=False)
        await message.answer(
            f'⚠️ <b>Недостаточно раскладов.</b>\n\n'
            f'{balance_text}',
            reply_markup=choose_subscription_prompt_kb(),
        )
        return

    await run_text_image_generation(
        message.bot,
        message.from_user.id,
        message.chat.id,
        prompt,
        username=message.from_user.username,
    )
    await state.clear()
