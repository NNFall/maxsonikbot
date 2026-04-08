from __future__ import annotations

import json
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config import load_config
from database import crud
from handlers.states import PhotoCustomState
from keyboards.payment_kb import choose_subscription_prompt_kb
from services.balance_card import build_inactive_balance_text
from services.generation import run_photo_custom_generation

router = Router()
config = load_config()


@router.callback_query(F.data == 'menu:photo_custom')
async def cb_photo_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        '🎨 <b>ИИ-Фотошоп</b>\n'
        'Пришлите фото и описание того, как его изменить. Можно по отдельности.\n'
        'Пример: <i>добавь в руки большой букет роз</i> или <i>добавь шляпу на голову</i>.'
    )
    await state.set_state(PhotoCustomState.waiting_photo_text)


@router.message(Command('photo_edit'))
async def cmd_photo_custom(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        '🎨 <b>ИИ-Фотошоп</b>\n'
        'Пришлите фото и описание того, как его изменить. Можно по отдельности.\n'
        'Пример: <i>добавь в руки большой букет роз</i> или <i>добавь шляпу на голову</i>.'
    )
    await state.set_state(PhotoCustomState.waiting_photo_text)


@router.callback_query(F.data == 'again:photo_custom')
async def cb_again_photo_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        '🎨 <b>ИИ-Фотошоп</b>\n'
        'Пришлите фото и описание того, как его изменить. Можно по отдельности.\n'
        'Пример: <i>добавь в руки большой букет роз</i> или <i>добавь шляпу на голову</i>.'
    )
    await state.set_state(PhotoCustomState.waiting_photo_text)


@router.message(PhotoCustomState.waiting_photo_text)
async def photo_custom_receive(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt = data.get('prompt')
    photo_file_id = data.get('photo_file_id')

    if message.photo:
        photo = message.photo[-1]
        photo_file_id = photo.file_id
        if message.caption:
            prompt = message.caption.strip()

    if message.text and not message.photo:
        prompt = message.text.strip()

    await state.update_data(
        photo_file_id=photo_file_id,
        prompt=prompt,
    )

    if not photo_file_id:
        await message.answer('📸 Пришлите фото.')
        return
    if not prompt:
        await message.answer('✍️ Пришлите текстовый запрос.')
        return

    balance = await crud.get_balance(config.database_path, message.from_user.id)
    if balance < config.photo_custom_cost:
        await state.update_data(
            pending_action=json.dumps(
                {
                    'type': 'photo_custom',
                    'photo_file_id': photo_file_id,
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

    await run_photo_custom_generation(
        message.bot,
        message.from_user.id,
        message.chat.id,
        photo_file_id,
        prompt,
        username=message.from_user.username,
    )
    await state.clear()
