from __future__ import annotations

import json
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config import load_config
from database import crud
from handlers.states import CustomState
from keyboards.custom_kb import duration_kb
from keyboards.payment_kb import choose_subscription_prompt_kb
from services.balance_card import build_inactive_balance_text
from services.generation import run_custom_generation

router = Router()
config = load_config()


@router.callback_query(F.data == 'menu:custom')
async def cb_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        '📝 <b>Свой промпт</b>\n'
        'Пришлите фото и текстовый запрос. Можно по отдельности.\n'
        'Пример: <i>пусть девушка надевает черные очки</i>.\n'
        f'Цена: <b>{config.custom_cost_per_sec}</b> раскладов за секунду.'
    )
    await state.set_state(CustomState.waiting_photo_text)


@router.message(Command('custom'))
async def cmd_custom(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        '📝 <b>Свой промпт</b>\n'
        'Пришлите фото и текстовый запрос. Можно по отдельности.\n'
        'Пример: <i>пусть девушка надевает черные очки</i>.\n'
        f'Цена: <b>{config.custom_cost_per_sec}</b> раскладов за секунду.'
    )
    await state.set_state(CustomState.waiting_photo_text)


@router.callback_query(F.data == 'again:custom')
async def cb_again_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        '📝 <b>Свой промпт</b>\n'
        'Пришлите фото и текстовый запрос. Можно по отдельности.\n'
        'Пример: <i>пусть девушка надевает черные очки</i>.\n'
        f'Цена: <b>{config.custom_cost_per_sec}</b> раскладов за секунду.'
    )
    await state.set_state(CustomState.waiting_photo_text)


@router.message(CustomState.waiting_photo_text)
async def custom_receive(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt = data.get('prompt')
    photo_file_id = data.get('photo_file_id')
    photo_width = data.get('photo_width')
    photo_height = data.get('photo_height')

    if message.photo:
        photo = message.photo[-1]
        photo_file_id = photo.file_id
        photo_width = photo.width
        photo_height = photo.height
        if message.caption:
            prompt = message.caption.strip()

    if message.text and not message.photo:
        prompt = message.text.strip()

    await state.update_data(
        photo_file_id=photo_file_id,
        photo_width=photo_width,
        photo_height=photo_height,
        prompt=prompt,
    )

    if not photo_file_id:
        await message.answer('📸 Пришлите фото.')
        return
    if not prompt:
        await message.answer('✍️ Пришлите текстовый запрос.')
        return

    await message.answer(
        f'⏱ <b>Выберите длительность</b>\n'
        f'Цена: <b>{config.custom_cost_per_sec}</b> раскладов за секунду.',
        reply_markup=duration_kb(1, 6)
    )
    await state.set_state(CustomState.waiting_duration)


@router.callback_query(CustomState.waiting_duration, F.data.startswith('dur:'))
async def custom_duration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    sec_str = callback.data.split(':', 1)[1]
    if not sec_str.isdigit():
        return
    duration = int(sec_str)
    cost = duration * config.custom_cost_per_sec

    data = await state.get_data()
    photo_file_id = data.get('photo_file_id')
    prompt = data.get('prompt')
    photo_width = data.get('photo_width')
    photo_height = data.get('photo_height')
    if not photo_file_id or not prompt:
        await callback.message.answer('⚠️ Данные потеряны. Начните заново.')
        await state.clear()
        return

    balance = await crud.get_balance(config.database_path, callback.from_user.id)
    if balance < cost:
        await state.update_data(
            pending_action=json.dumps(
                {
                    'type': 'custom',
                    'photo_file_id': photo_file_id,
                    'prompt': prompt,
                    'duration': duration,
                    'photo_width': photo_width,
                    'photo_height': photo_height,
                    'username': callback.from_user.username,
                }
            )
        )
        balance_text = await build_inactive_balance_text(callback.bot, balance, include_header=False)
        await callback.message.answer(
            f'⚠️ <b>Недостаточно раскладов.</b>\n\n'
            f'{balance_text}',
            reply_markup=choose_subscription_prompt_kb(),
        )
        return

    await run_custom_generation(
        callback.bot,
        callback.from_user.id,
        callback.message.chat.id,
        photo_file_id,
        prompt,
        duration,
        photo_width=photo_width,
        photo_height=photo_height,
        username=callback.from_user.username,
    )
    await state.clear()

